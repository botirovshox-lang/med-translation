"""Объём файла в знаках и в условных переводческих страницах.

Зачем отдельный модуль: расчёт стоимости обязан отвечать на вопрос «сколько
здесь работы» ДО импорта проекта и без единого вызова модели. Правила счёта
живут здесь одни на всех — и для загруженного файла, и для готового проекта:
две копии однажды разойдутся, и под соседними кнопками встанут разные суммы.

Три закона, которые нельзя ослаблять:

1. **Не извлеклось — это ошибка, а не ноль.** Формат, из которого текст
   не достаётся (скан в PDF, старый .doc, картинка), обязан сказать об этом
   вслух: посчитанный нулём файл выглядит как бесплатный. Тот же закон, что
   у инварианта «никаких демо-заглушек».

2. **Молча не вычитаем ничего.** Повторы, номера страниц и короткие абзацы
   считаются и показываются ОТДЕЛЬНОЙ строкой, но из объёма не вычитаются:
   скидка за повторы — решение продавца, а не арифметика.

3. **Текст, впечатанный в картинки, здесь не виден.** Он живёт только
   в растре (`image_text.py`) и в счёт не попадает — об этом сказано
   в `notes`, а не умолчано.
"""

from __future__ import annotations

import html as _html
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Callable, Optional

# ─── Норма страницы ─────────────────────────────────────────────────
# Два файла и порядок важен: data/ идёт вторым и побеждает — как у справочника
# рангов моделей. Норма страницы меняется чаще, чем выходят релизы (её диктует
# договор с клиентом), и правка одной строки не должна требовать выката.
NORM_FILES = [Path(__file__).with_name("page_norms.json"),
              Path(__file__).with_name("data") / "page_norms.json"]
_NORMS_CACHE: dict = {}
_NORMS_STAMP: tuple = ()


def norms() -> dict:
    """Таблица норм. Перечитывается по времени правки файлов, а не разово:
    иначе правленую норму увидел бы только рестарт сервиса."""
    global _NORMS_CACHE, _NORMS_STAMP
    stamp = tuple((p.stat().st_mtime_ns if p.exists() else 0) for p in NORM_FILES)
    if _NORMS_CACHE and stamp == _NORMS_STAMP:
        return _NORMS_CACHE
    out = {"default": 1800, "basis": {}, "rows": {}, "files": []}
    for p in NORM_FILES:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except Exception as e:
            # Битая таблица не роняет сервис и не подменяется пустой молча:
            # без неё считать было бы нечем, и об этом надо знать.
            print("[backend] таблица норм %s не прочитана: %s" % (p, e))
            continue
        out["files"].append(str(p))
        if data.get("default"):
            out["default"] = int(data["default"])
        out["basis"] = data.get("basis") or out["basis"]
        for r in data.get("norms") or []:
            out["rows"][str(r["lang"]).upper()] = r
    _NORMS_CACHE, _NORMS_STAMP = out, stamp
    return out


def norm_for(lang: str, overrides: Optional[dict] = None) -> dict:
    """Сколько знаков идёт за страницу для ЭТОГО языка исходника.

    Порядок: переопределение организации → таблица → default. Откуда взято
    число, говорится словом (`source`): «взяли по умолчанию» человек обязан
    видеть, иначе он примет догадку за норму своего языка."""
    code = (lang or "").strip().upper()
    t = norms()
    unit = "chars_with_spaces"    # величина, которую делят на норму — названа всегда
    if overrides:
        v = overrides.get(code) or overrides.get(code.lower())
        if v:
            return {"lang": code, "chars": int(v), "source": "tenant", "unit": unit,
                    "spaceless": False, "basis": "tenant"}
    row = t["rows"].get(code)
    if row:
        return {"lang": code, "chars": int(row["chars"]), "source": "table", "unit": unit,
                "spaceless": bool(row.get("spaceless")), "basis": row.get("basis")}
    # Языка нет в таблице — число взято по умолчанию, и ответ обязан сказать
    # это словом: догадка, поданная как расчёт, и есть враньё в смете.
    return {"lang": code, "chars": t["default"], "source": "default", "unit": unit,
            "spaceless": False, "basis": "assumed"}


# ─── Счёт знаков ────────────────────────────────────────────────────
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Текст, приведённый к тому виду, в котором его считает Word: перевод
    строки — не знак, а разделитель, поэтому любая череда пробелов и переводов
    строки становится ОДНИМ пробелом. Без этого файл с двойными переносами
    оказывался бы дороже того же текста в один абзац."""
    return _WS_RE.sub(" ", _CTRL_RE.sub(" ", text or "")).strip()


def _is_wordish(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N") or cat[0] == "M"


def count_blocks(blocks: list) -> dict:
    """Объём по списку кусков текста (абзац, ячейка, надпись — что дал формат).

    Повторы считаются по ТОЧНОМУ совпадению нормализованного куска: нечёткого
    сравнения здесь нет и не обещается — скидку за похожие абзацы считает
    память переводов, а не счётчик знаков."""
    norm_blocks = [normalize(b) for b in blocks]
    norm_blocks = [b for b in norm_blocks if b]
    # Куски НЕ склеиваются через разделитель, и это не мелочь: знак абзаца
    # Word в «Знаках (с пробелами)» не считает, а склейка через пробел
    # добавляла бы по знаку на абзац — на книге в 2670 абзацев это лишние
    # полторы страницы в счёте клиенту, взявшиеся из нашего разделителя.
    chars = sum(len(b) for b in norm_blocks)
    no_spaces = sum(1 for b in norm_blocks for c in b if not c.isspace())
    words = sum(len([w for w in b.split(" ") if any(_is_wordish(c) for c in w)])
                for b in norm_blocks)
    seen, repeat_chars, repeat_blocks = set(), 0, 0
    for b in norm_blocks:
        if b in seen:
            repeat_chars += len(b)
            repeat_blocks += 1
        else:
            seen.add(b)
    return {"chars": chars, "charsNoSpaces": no_spaces, "words": words,
            "blocks": len(norm_blocks), "repeatBlocks": repeat_blocks,
            "repeatChars": min(repeat_chars, chars)}


def pages_of(chars: int, norm_chars: int, min_pages: float = 1.0,
             round_to: float = 0.1) -> dict:
    """Страницы: точные и к оплате. Округление и минимум — условия продавца,
    поэтому они ПАРАМЕТРЫ, а не зашитые числа, и оба уезжают в ответ: сумма,
    посчитанная по невидимому правилу, не проверяется человеком никак."""
    norm_chars = max(1, int(norm_chars or 1))
    exact = chars / float(norm_chars)
    step = float(round_to or 0)
    if step > 0:
        # ceil со страховкой от двоичной погрешности: 1800 знаков при норме
        # 1800 — это ровно одна страница, а не 1.1 из-за 1.0000000000000002
        billed = -(-round(exact / step, 6) // 1) * step
    else:
        billed = exact
    billed = max(float(min_pages or 0), billed)
    return {"exact": round(exact, 3), "billed": round(billed + 1e-9, 3),
            "normChars": norm_chars, "minPages": float(min_pages or 0),
            "roundTo": step}


# ─── Извлечение текста ──────────────────────────────────────────────
class Unsupported(Exception):
    """Формат не разбирается — говорим об этом прямо, а не считаем нулём."""


class NotAvailable(Exception):
    """Формат поддержан, но прочитать его сейчас нечем (нет библиотеки).

    Отдельно от `Unsupported` намеренно: «мы такое не считаем» и «на сервере
    не хватает модуля» — разные ответы (415 и 503) и разные действия. Тот же
    закон, что у отсутствующего ключа OpenAI: причина называется вслух."""


class TooBig(Exception):
    """Файл больше потолка. Воркер ОДИН (инвариант 1), и разбор чужого
    пакета на сотню мегабайт блокирует сервис всем арендаторам."""


TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".po", ".srt",
            ".vtt", ".json", ".xml", ".html", ".htm", ".rtf", ".yml", ".yaml"}
ZIP_EXT = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
SUPPORTED_EXT = sorted(TEXT_EXT | ZIP_EXT | {".pdf"})

MAX_BYTES = 32 * 1024 * 1024        # сам файл
MAX_UNPACKED = 256 * 1024 * 1024    # распакованный пакет: защита от zip-бомбы
MAX_PART = 24 * 1024 * 1024         # ОДНА часть пакета: её мы разворачиваем в строку
MAX_MEMBERS = 5000                  # частей в пакете


def _decode(raw: bytes) -> tuple:
    """(текст, как декодировали). Кодировку определяем перебором, а не гадаем:
    неверная кодировка не портит ЧИСЛО знаков (символ есть символ), но портит
    показанный человеку кусок текста, по которому он проверяет, то ли посчитали."""
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/lossy"


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_SRT_TIME_RE = re.compile(r"^\s*(\d+\s*$|[\d:,.\->\s]+$)")
_RTF_CTRL_RE = re.compile(r"\\[a-zA-Z]+-?\d* ?|[{}]|\\\n")


def _blocks_from_plain(text: str, ext: str) -> list:
    if ext in (".html", ".htm", ".xml"):
        text = _SCRIPT_RE.sub(" ", text)
        text = _html.unescape(_TAG_RE.sub("\n", text))
    elif ext == ".rtf":
        text = _RTF_CTRL_RE.sub(" ", text)
    elif ext in (".srt", ".vtt"):
        text = "\n".join(l for l in text.splitlines() if not _SRT_TIME_RE.match(l))
    elif ext == ".json":
        # Считаем ТОЛЬКО строковые значения: ключи и скобки — разметка, а не
        # текст к переводу; развалившийся JSON считаем как простой текст.
        try:
            vals: list = []

            def walk(o):
                if isinstance(o, str):
                    vals.append(o)
                elif isinstance(o, dict):
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(json.loads(text))
            return vals
        except Exception:
            pass
    return text.splitlines()


def _zip_xml_texts(zf: zipfile.ZipFile, names: list, tag: str) -> list:
    """Тексты одного тега из перечисленных частей пакета. Разбор регуляркой,
    а не деревом: нам нужен только текст, а части бывают на десятки мегабайт."""
    rx = re.compile(r"(?s)<(?:[a-zA-Z0-9]+:)?%s(?:\s[^>]*)?>(.*?)</(?:[a-zA-Z0-9]+:)?%s>" % (tag, tag))
    out = []
    for n in names:
        try:
            if zf.getinfo(n).file_size > MAX_PART:
                raise TooBig("Часть пакета %s больше %d МБ" % (n, MAX_PART // 1024 // 1024))
            body = zf.read(n).decode("utf-8", errors="replace")
        except KeyError:
            continue
        for m in rx.finditer(body):
            out.append(_html.unescape(_TAG_RE.sub("", m.group(1))))
    return out


def _blocks_from_zip(ext: str, content: bytes, notes: list) -> list:
    zf = zipfile.ZipFile(io.BytesIO(content))
    infos = zf.infolist()
    # Потолки считаются ДО чтения: распакованный размер объявлен в самом
    # пакете, и проверить его дешевле, чем узнать о бомбе по кончившейся памяти
    # единственного воркера.
    if len(infos) > MAX_MEMBERS:
        raise TooBig("В пакете %d частей — больше потолка %d" % (len(infos), MAX_MEMBERS))
    total = sum(i.file_size for i in infos)
    if total > MAX_UNPACKED:
        raise TooBig("Распакованный пакет — %d МБ, потолок %d МБ"
                     % (total // 1024 // 1024, MAX_UNPACKED // 1024 // 1024))
    names = zf.namelist()
    if ext == ".xlsx":
        # sharedStrings — общий пул строк книги; inline-строки лежат в листах.
        blocks = _zip_xml_texts(zf, ["xl/sharedStrings.xml"], "t")
        blocks += _zip_xml_texts(zf, [n for n in names if n.startswith("xl/worksheets/")], "t")
        notes.append("Формулы и числа в счёт не идут — считается только текст ячеек.")
        return blocks
    if ext == ".pptx":
        slides = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
        notes.append("Заметки к слайдам не считаются: они не идут в перевод по умолчанию.")
        return _zip_xml_texts(zf, slides, "t")
    if ext in (".odt", ".ods", ".odp"):
        if zf.getinfo("content.xml").file_size > MAX_PART:
            raise TooBig("content.xml больше %d МБ" % (MAX_PART // 1024 // 1024))
        body = zf.read("content.xml").decode("utf-8", errors="replace")
        body = re.sub(r"(?s)<office:(automatic-)?styles.*?</office:(automatic-)?styles>", " ", body)
        return [_html.unescape(x) for x in _TAG_RE.sub("\n", body).splitlines()]
    # .docx: запасной разбор — без python-docx. Колонтитулы включены (их
    # переводят), поля и скрытый текст остаются в счёте: спрятать их значит
    # занизить объём молча.
    parts = [n for n in names if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n)]
    return _zip_xml_texts(zf, sorted(parts), "t")


def extract(filename: str, content: bytes,
            docx_paragraphs: Optional[Callable[[bytes], list]] = None) -> dict:
    """{blocks, kind, notes} — куски текста файла в порядке документа.

    `docx_paragraphs` — разбор .docx ТЕМ ЖЕ кодом, что и импорт проекта
    (`_docx_paragraphs` в main.py). Свой разбор был бы вторым мнением о том,
    что в этом файле считать текстом, и смета разошлась бы с числом сегментов,
    которые потом появятся в проекте."""
    if not content:
        raise Unsupported("Файл пустой")
    if len(content) > MAX_BYTES:
        raise TooBig("Файл больше %d МБ — разберите его по частям"
                     % (MAX_BYTES // 1024 // 1024))
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in (filename or "") else ""
    notes: list = []
    if ext == ".docx" and docx_paragraphs is not None:
        try:
            return {"blocks": docx_paragraphs(content), "kind": "docx", "notes": notes}
        except Exception as e:
            notes.append("Разбор python-docx не сработал (%s) — считано по XML пакета." % e)
    if ext in ZIP_EXT:
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise Unsupported("Файл %s повреждён: это не пакет OOXML/ODF" % ext)
        try:
            blocks = _blocks_from_zip(ext, content, notes)
        except (TooBig, Unsupported, NotAvailable):
            raise
        except Exception as e:
            # Битый или необычный пакет — отказ с причиной, а не 500: человеку
            # нужно знать, что делать с ЕГО файлом, а не что у нас упало.
            raise Unsupported("Пакет %s не разобрался (%s: %s). Пересохраните файл."
                              % (ext, type(e).__name__, e))
        return {"blocks": blocks, "kind": ext[1:], "notes": notes}
    if ext == ".pdf":
        blocks = _pdf_blocks(content, notes)
        return {"blocks": blocks, "kind": "pdf", "notes": notes}
    if ext in TEXT_EXT or not ext:
        text, enc = _decode(content)
        if "\x00" in text[:4096]:
            raise Unsupported("Двоичный файл: текста в нём нет. Поддерживаются: %s"
                              % ", ".join(SUPPORTED_EXT))
        if enc.endswith("lossy"):
            notes.append("Кодировка файла не опознана — часть символов заменена; "
                         "число знаков верно, показанный кусок текста может быть искажён.")
        return {"blocks": _blocks_from_plain(text, ext), "kind": ext[1:] or "text",
                "notes": notes}
    if ext == ".doc":
        raise Unsupported("Старый .doc не разбирается — пересохраните в .docx")
    raise Unsupported("Формат %s не поддерживается. Поддерживаются: %s"
                      % (ext or "без расширения", ", ".join(SUPPORTED_EXT)))


def _pdf_blocks(content: bytes, notes: list) -> list:
    """PDF читаем только настоящей библиотекой. Нет её — говорим об этом,
    а не возвращаем пустоту: пустой список неотличим от «в файле нет текста»."""
    try:
        from pypdf import PdfReader          # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader     # type: ignore
        except ImportError:
            raise NotAvailable("PDF не прочитать: на сервере нет модуля pypdf "
                               "(pip install pypdf). Формат поддержан — не хватает "
                               "библиотеки.")
    try:
        reader = PdfReader(io.BytesIO(content))
        blocks = []
        for page in reader.pages:
            blocks.extend((page.extract_text() or "").splitlines())
    except Exception as e:
        raise Unsupported("PDF не читается: %s" % e)
    if not any(normalize(b) for b in blocks):
        raise Unsupported("В PDF нет текстового слоя — это скан. Объём такого файла "
                          "считается только после распознавания.")
    notes.append("PDF: текст извлечён из текстового слоя; надписи внутри картинок "
                 "в счёт не идут.")
    return blocks


def measure(filename: str, content: bytes, lang: str, overrides: Optional[dict] = None,
            min_pages: float = 1.0, round_to: float = 0.1,
            docx_paragraphs: Optional[Callable[[bytes], list]] = None) -> dict:
    """Полный ответ по файлу: объём, норма, страницы. Цены здесь нет намеренно —
    она приходит из ценовой карточки организации, и смешивать «сколько тут
    знаков» с «сколько это стоит» в одной функции значит однажды посчитать
    объём по чужому прайсу."""
    got = extract(filename, content, docx_paragraphs=docx_paragraphs)
    counts = count_blocks(got["blocks"])
    if not counts["chars"]:
        # Ноль знаков — это отказ, а не смета на ноль: пустой результат
        # неотличим от пустого файла, а счёт на ноль выглядит как «бесплатно».
        raise Unsupported("Из файла не извлеклось ни одного знака (кусков текста: %d). "
                          "Если это скан или текст в картинках — объём считается "
                          "только после распознавания." % len(got["blocks"]))
    if got["kind"] in ("csv", "tsv"):
        got["notes"].append("Заголовки столбцов и разделители посчитаны как текст: "
                            "что переводить в таблице, решает человек.")
    norm = norm_for(lang, overrides)
    if norm["spaceless"]:
        got["notes"].append("В этом письме слова не отделяются пробелами — норма задана "
                            "прямо в знаках, счёт слов там условен.")
    return {"file": filename, "kind": got["kind"], "notes": got["notes"],
            "counts": counts, "norm": norm,
            "pages": pages_of(counts["chars"], norm["chars"], min_pages, round_to)}
