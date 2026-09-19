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
import os
import json
import re
import sys
import threading
import unicodedata
import zipfile
from collections import OrderedDict
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


def norm_for(lang: str, overrides: Optional[dict] = None,
             words_per_page: Optional[int] = None) -> dict:
    """Норма страницы для языка ИСХОДНИКА и ЕДИНИЦА, в которой она задана.

    Единица — СЛОВА (`basis.wordsPerPage`, 250 на страницу), одна на все языки:
    работа переводчика соразмерна числу слов, а не букв, а норма в знаках была
    лишь пересчётом тех же 250 слов через среднюю длину слова языка — и на
    учебнике с длинными словами давала на 16% больше страниц, чем слова.
    Знаки остаются ТОЛЬКО у письма без пробелов (`spaceless`): там слова нечем
    считать, и норма задана прямо в знаках по отраслевой договорённости.
    `overrides` — {язык: знаков} организации, действует для письма без
    пробелов; `words_per_page` — её же число слов на страницу. `chars`
    у словесной нормы — справочный пересчёт («≈ столько знаков»), а `perPage` —
    то, на что делят. Откуда взято число, говорится словом (`source`)."""
    code = (lang or "").strip().upper()
    t = norms()
    row = t["rows"].get(code)
    if row and row.get("spaceless"):
        v = (overrides or {}).get(code) or (overrides or {}).get(code.lower())
        if v:
            return {"lang": code, "unit": "chars", "perPage": int(v), "chars": int(v),
                    "source": "tenant", "spaceless": True, "basis": "tenant"}
        return {"lang": code, "unit": "chars", "perPage": int(row["chars"]),
                "chars": int(row["chars"]), "source": "table", "spaceless": True,
                "basis": row.get("basis")}
    wpp = int(words_per_page) if words_per_page else int((t["basis"] or {}).get("wordsPerPage") or 250)
    return {"lang": code, "unit": "words", "perPage": wpp, "wordsPerPage": wpp,
            "chars": int(row["chars"]) if row else t["default"],
            # Языка нет в таблице — слова считаются всё равно, но человек обязан
            # знать: если это письмо без пробелов, счёт слов там бессмыслен.
            "source": "tenant" if words_per_page else ("table" if row else "default"),
            "spaceless": False, "basis": "tenant" if words_per_page else "words"}


def amount_of(counts: dict, norm: dict) -> int:
    """Что делить на норму: слова, а у письма без пробелов — знаки."""
    return int(counts["words"] if norm.get("unit") == "words" else counts["chars"])


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


def pages_of(amount: int, per_page: int, min_pages: float = 1.0,
             round_to: float = 0.1) -> dict:
    """Страницы: точные и к оплате. Округление и минимум — условия продавца,
    поэтому они ПАРАМЕТРЫ, а не зашитые числа, и оба уезжают в ответ: сумма,
    посчитанная по невидимому правилу, не проверяется человеком никак."""
    per_page = max(1, int(per_page or 1))
    exact = amount / float(per_page)
    step = float(round_to or 0)
    if step > 0:
        # ceil со страховкой от двоичной погрешности: 1800 знаков при норме
        # 1800 — это ровно одна страница, а не 1.1 из-за 1.0000000000000002
        billed = -(-round(exact / step, 6) // 1) * step
    else:
        billed = exact
    billed = max(float(min_pages or 0), billed)
    return {"exact": round(exact, 3), "billed": round(billed + 1e-9, 3),
            "perPage": per_page, "minPages": float(min_pages or 0),
            "roundTo": step}


# ─── Извлечение текста ──────────────────────────────────────────────
class Unsupported(Exception):
    """Формат не разбирается — говорим об этом прямо, а не считаем нулём."""


class NotAvailable(Exception):
    """Формат поддержан, но прочитать его сейчас нечем (нет библиотеки).

    Отдельно от `Unsupported` намеренно: «мы такое не считаем» и «на сервере
    не хватает модуля» — разные ответы (415 и 503) и разные действия. Тот же
    закон, что у отсутствующего ключа OpenAI: причина называется вслух."""


class Scan(Unsupported):
    """PDF без текстового слоя: страниц знаем, текста — нет. Отказ от счёта
    остаётся (наследует Unsupported), но число страниц уезжает вызывающему:
    по нему считают выборку для распознавания."""

    def __init__(self, msg: str, pages: int):
        super().__init__(msg)
        self.pages = pages


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
MAX_XML_PART = 64 * 1024 * 1024     # одна XML-часть: lxml строит дерево в памяти


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


# Строка времени субтитра: «00:00:01,000 --> 00:00:03,500» и у VTT — с
# настройками реплики за ней («align:start position:10%»).
_CUE_TIME_RE = re.compile(r"^\s*(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}")
_CUE_TAG_RE = re.compile(r"</?(?:[bciu]|v|lang|ruby|rt|font)(?:[ .][^>]*)?>|<\d{2}:[\d:.]+>", re.I)


def _cue_blocks(text: str) -> list:
    """Субтитры: РЕПЛИКА — один кусок. Строки внутри реплики — это перенос
    для экрана, а не конец фразы: «Мы ещё не знали, что / всё кончится
    иначе» по строкам переводилось бы двумя обрывками. Реплики между собой
    не склеиваются: реплика — единица времени, и фраза, растянутая на две
    реплики, так и остаётся двумя кусками. Номер реплики, строка времени,
    заголовок WEBVTT и блоки NOTE/STYLE/REGION — не текст; разметка голоса
    и курсива (<v Анна>, <i>) снимается."""
    out, cur = [], []
    skip = False
    timed = False                             # в этом блоке уже была строка времени
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if cur:
                out.append(" ".join(cur))
            cur, skip, timed = [], False, False
            continue
        if skip:
            continue
        if not cur and (line.upper().startswith("WEBVTT") or line.split(" ")[0] in ("NOTE", "STYLE", "REGION")):
            skip = True                       # шапка и служебные блоки VTT — до пустой строки
            continue
        if _CUE_TIME_RE.match(line):
            if timed:
                # Реплики без пустой строки между ними (так пишут иные
                # конвертеры): накопленное — текст ПРЕДЫДУЩЕЙ реплики, и
                # только номер в его хвосте — номер этой. Сброс без записи
                # терял бы текст всех реплик, кроме последней.
                if cur and cur[-1].isdigit():
                    cur.pop()
                if cur:
                    out.append(" ".join(cur))
            cur, timed = [], True             # до первого времени блока — номер/имя реплики
            continue
        if not cur and line.isdigit():
            continue
        t = _html.unescape(_CUE_TAG_RE.sub("", line)).strip()
        if t:
            cur.append(t)
    if cur:
        out.append(" ".join(cur))
    return out


_RTF_SKIP_DEST = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header", "footer",
                  "headerl", "headerr", "headerf", "footerl", "footerr", "footerf", "listtable",
                  "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "themedata", "colorschememapping",
                  "latentstyles", "datastore", "fldinst", "bkmkstart", "bkmkend", "revtbl", "pgdsctbl"}
_RTF_TOKEN_RE = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}]+)", re.S)


def _rtf_paragraphs(text: str) -> list:
    """Текст RTF по АБЗАЦАМ. Прежний разбор снимал управляющие слова
    регуляркой, и это ломало сегменты трижды: абзацы делились по переводам
    строки ИСХОДНИКА (редактор переносит RTF-код где придётся, посреди
    фразы), а не по `\\par`; кириллица в `\\'e0` и `\\u1072` оставалась
    кодами; таблица шрифтов и стилей шла в текст. Здесь — маленький
    разборщик: группы, пропуск служебных групп, `\\'hh` в кодировке
    документа (`\\ansicpg`), `\\uN` с пропуском замены (`\\ucN`), мягкий
    перенос `\\-` снимается, неразрывный дефис `\\_` — дефис."""
    enc = "cp1252"
    m = re.search(r"\\ansicpg(\d+)", text)
    if m:
        enc = "cp" + m.group(1)
    out: list = []
    buf: list = []
    pend = bytearray()
    stack: list = []                  # (skip, uc) на входе в группу
    skip, uc, skip_chars = False, 1, 0
    star = False

    def flush_bytes():
        if pend:
            try:
                buf.append(bytes(pend).decode(enc, errors="replace"))
            except LookupError:
                buf.append(bytes(pend).decode("cp1252", errors="replace"))
            pend.clear()

    def para():
        flush_bytes()
        t = " ".join("".join(buf).split())
        # Знак вне BMP (эмодзи) RTF пишет ПАРОЙ суррогатов `\u-10179?\u-8704?`:
        # по отдельности это одинокие половинки, и первый же encode("utf-8")
        # падал. Пары собираются, одинокая половинка — знак замены.
        t = t.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
        if t:
            out.append(t)
        buf.clear()

    for m in _RTF_TOKEN_RE.finditer(text):
        word, num, hexb, sym, brace, plain = m.groups()
        if brace == "{":
            stack.append((skip, uc))
            star = False
            continue
        if brace == "}":
            flush_bytes()
            skip, uc = stack.pop() if stack else (False, 1)
            continue
        if skip_chars and (plain is not None or hexb is not None or sym is not None):
            # Замена после \uN: один «знак» — байт \'hh, символ или буква.
            if plain is not None:
                n = min(skip_chars, len(plain))
                plain = plain[n:]
                skip_chars -= n
                if not plain:
                    continue
            else:
                skip_chars -= 1
                continue
        if word is not None:
            if star or word in _RTF_SKIP_DEST:
                skip = True
                star = False
                continue
            if skip:
                continue
            if word in ("par", "sect", "page", "row"):
                para()
            elif word in ("line", "tab", "cell"):
                flush_bytes()
                buf.append(" ")
            elif word == "uc":
                uc = max(0, min(int(num or 1), 16))
            elif word == "u":
                flush_bytes()
                n = int(num or 0)
                n = n + 65536 if n < 0 else n
                # По спецификации N — 16-битное со знаком; что вне Юникода
                # (`香9999`, `\u-99999`) — не знак, а порча файла: пропускаем.
                if 0 < n <= 0x10FFFF:
                    buf.append(chr(n))
                skip_chars = uc
            elif word in ("emdash", "endash"):
                flush_bytes()
                buf.append("—" if word == "emdash" else "–")
            elif word in ("lquote", "rquote", "ldblquote", "rdblquote"):
                flush_bytes()
                buf.append({"lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”"}[word])
            continue
        if sym is not None:
            if sym == "*":
                star = True
                continue
            if skip:
                continue
            if sym in "\\{}":
                flush_bytes()
                buf.append(sym)
            elif sym == "~":
                flush_bytes()
                buf.append(" ")
            elif sym == "_":
                flush_bytes()
                buf.append("-")
            elif sym in "\r\n":
                para()                        # «\» с переводом строки — это \par
            # «\-» — мягкий перенос: в тексте его нет
            continue
        if skip:
            continue
        if hexb is not None:
            pend.append(int(hexb, 16))
            continue
        if plain is not None:
            flush_bytes()
            buf.append(plain.replace("\r", "").replace("\n", ""))
    para()
    return out


_PO_STR_RE = re.compile(r'^\s*(msgid|msgid_plural|msgstr(?:\[\d+\])?|msgctxt)\s+"(.*)"\s*$')
_PO_CONT_RE = re.compile(r'^\s*"(.*)"\s*$')


def _po_blocks(text: str) -> list:
    """Каталог gettext: переводить нужно ИСХОДНЫЕ строки (msgid и
    msgid_plural), а не строки файла: `msgid "Hello"` по строкам давало
    сегмент вместе с ключевым словом и кавычками, а длинная строка,
    разбитая на продолжения `"…"`, — по сегменту на кусок. Шапка (пустой
    msgid) и комментарии — не текст."""
    out, key, val = [], None, []

    def done():
        if key in ("msgid", "msgid_plural"):
            s = re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), "".join(val))
            if s.strip():
                out.append(s)

    for line in text.splitlines():
        m = _PO_STR_RE.match(line)
        if m:
            done()
            key, val = m.group(1), [m.group(2)]
            continue
        m = _PO_CONT_RE.match(line)
        if m and key:
            val.append(m.group(1))
            continue
        done()
        key, val = None, []
    done()
    return out


def _blocks_from_plain(text: str, ext: str) -> list:
    if ext in (".html", ".htm", ".xml"):
        text = _SCRIPT_RE.sub(" ", text)
        text = _html.unescape(_TAG_RE.sub("\n", text))
    elif ext == ".rtf":
        if text.lstrip().startswith("{\\rtf"):
            # Разборщик маленький, а RTF бывает какой угодно: любой его сбой —
            # прежний грубый разбор ниже, а не 500 на смете и импорте.
            try:
                return _rtf_paragraphs(text)
            except Exception:
                pass
        text = _RTF_CTRL_RE.sub(" ", text)
    elif ext in (".srt", ".vtt"):
        return _cue_blocks(text)
    elif ext == ".po":
        return _po_blocks(text)
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


def _zip_xml_texts(zf: zipfile.ZipFile, names: list, tag: str,
                   unit: str = "p", breaks: tuple = ("tab", "ptab", "br", "cr")) -> list:
    """Тексты одного тега из перечисленных частей пакета, СКЛЕЕННЫЕ по абзацу.

    Разбор регуляркой, а не деревом: нам нужен только текст, а части бывают
    на десятки мегабайт. Куски `t` нельзя отдавать поштучно: Word и PowerPoint
    режут абзац на прогоны по оформлению («Жирное », «слово», « стоит…»),
    и каждый кусок, посчитанный отдельно, теряет пробел на границе после
    `normalize` — по знаку на каждое выделение, то есть занижение молча.
    Поэтому часть режется по ОТКРЫВАЮЩЕМУ тегу абзаца (`unit`: `w:p`/`a:p`,
    у xlsx — строка `si`/`is`), а закрывающие не ищутся: вложенный абзац
    (надпись внутри абзаца) при парном поиске уносил бы хвост внешнего.
    `breaks` — табуляция и разрыв строки: не текст, но делят слова, без них
    «и<tab>табуляцией» склеивается в одно слово. Каждый становится пробелом."""
    rx_t = re.compile(r"(?s)<(?:[a-zA-Z0-9]+:)?%s(?:\s[^>]*)?>(.*?)</(?:[a-zA-Z0-9]+:)?%s>" % (tag, tag))
    rx_unit = re.compile(r"<(?:[a-zA-Z0-9]+:)?(?:%s)(?:\s[^>]*)?>" % unit)
    rx_brk = (re.compile(r"<(?:[a-zA-Z0-9]+:)?(?:%s)(?:\s[^>]*)?/?>" % "|".join(breaks))
              if breaks else None)
    out = []
    for n in names:
        try:
            if zf.getinfo(n).file_size > MAX_PART:
                raise TooBig("Часть пакета %s больше %d МБ" % (n, MAX_PART // 1024 // 1024))
            body = zf.read(n).decode("utf-8", errors="replace")
        except KeyError:
            continue
        if rx_brk is not None:
            body = rx_brk.sub("<%s> </%s>" % (tag, tag), body)
        for chunk in rx_unit.split(body):
            texts = [_html.unescape(_TAG_RE.sub("", m.group(1))) for m in rx_t.finditer(chunk)]
            if texts:
                out.append("".join(texts))
    return out


_XLSX_SI_RE = re.compile(r"<si>(.*?)</si>", re.S)
_XLSX_C_RE = re.compile(r"<c(?=[\s/>])([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_XLSX_T_RE = re.compile(r"<t(?:\s[^>]*)?>(.*?)</t>", re.S)


def _xlsx_cell_texts(zf: "zipfile.ZipFile", names: list) -> Optional[list]:
    """Текст КАЖДОЙ строковой ячейки книги по листам и строкам: общие строки
    (t="s") — по номеру в пуле, inline (t="inlineStr") — из самой ячейки.
    Формулы (t="str" с <f>) и числа не считаются. None — разбор не удался,
    вызывающий берёт запасной счёт по пулу."""
    try:
        shared = []
        if "xl/sharedStrings.xml" in names:
            if zf.getinfo("xl/sharedStrings.xml").file_size > MAX_PART:
                raise TooBig("sharedStrings.xml больше %d МБ" % (MAX_PART // 1024 // 1024))
            xml = zf.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
            for m in _XLSX_SI_RE.finditer(xml):
                shared.append(_html.unescape("".join(_XLSX_T_RE.findall(m.group(1)))))
        out = []
        sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        for n in sheets:
            if zf.getinfo(n).file_size > MAX_PART:
                raise TooBig("%s больше %d МБ" % (n, MAX_PART // 1024 // 1024))
            xml = zf.read(n).decode("utf-8", errors="replace")
            for m in _XLSX_C_RE.finditer(xml):
                attrs, body = m.group(1) or "", m.group(2) or ""
                tm = re.search(r'(?:^|\s)t="([^"]+)"', attrs)
                kind = tm.group(1) if tm else ""
                if kind == "s":
                    vm = re.search(r"<v>(.*?)</v>", body, re.S)
                    if vm and vm.group(1).strip().isdigit():
                        i = int(vm.group(1))
                        if i < len(shared):
                            out.append(shared[i])
                elif kind == "inlineStr":
                    out.append(_html.unescape("".join(_XLSX_T_RE.findall(body))))
        return out
    except TooBig:
        raise
    except Exception:
        return None


_ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_ODF_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"


def _odf_blocks(raw: bytes) -> Optional[list]:
    """Абзацы ODF (odt/ods/odp) по элементам `text:p` и `text:h`. Прежний
    разбор ставил перевод строки на КАЖДЫЙ тег, и выделение внутри абзаца
    («Абзац <text:span>жирный</text:span> текст») резало его на три
    сегмента, а `<text:s/>` (повтор пробела) склеивал слова. Здесь инлайн
    (span, a, s, tab, line-break, мягкий разрыв страницы) — часть абзаца;
    сноска и надпись внутри абзаца — свои абзацы ПОСЛЕ него; комментарии
    рецензента не текст. None — XML не разобрался (тогда прежний разбор)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(raw)
    except Exception:
        return None
    T, O = "{%s}" % _ODF_TEXT, "{%s}" % _ODF_OFFICE
    body = root.find(O + "body")
    if body is None:
        return None
    out: list = []

    def para(el) -> None:
        buf: list = []
        later: list = []                  # сноски, надписи — после абзаца

        def walk(e, top=False):
            tag = e.tag
            if not top:
                if tag == T + "s":
                    # Повтор пробела `c` — ОДИН пробел: пробелы всё равно
                    # схлопываются ниже, а `c="999999999"` строил бы гигабайт.
                    buf.append(" ")
                elif tag in (T + "tab", T + "line-break"):
                    buf.append(" ")
                elif tag in (T + "note", T + "p", T + "h") or tag.endswith("}frame"):
                    later.append(e)
                    buf.append(e.tail or "")
                    return
                elif tag in (O + "annotation", O + "annotation-end", T + "bookmark-ref"):
                    buf.append(e.tail or "")
                    return
            if e.text and tag != T + "s":
                buf.append(e.text)
            for ch in e:
                walk(ch)
            if not top:
                buf.append(e.tail or "")
        walk(el, top=True)
        t = " ".join("".join(buf).replace("­", "").split())
        if t:
            out.append(t)
        for e in later:
            block(e)

    def block(e) -> None:
        if e.tag in (T + "p", T + "h"):
            para(e)
            return
        if e.tag in (O + "annotation",):
            return
        for ch in e:
            block(ch)

    # Обход рекурсивный: вложенность в тысячи уровней (порча или бомба) —
    # RecursionError, и тогда, как и при любом сбое разбора, прежний разбор.
    try:
        block(body)
    except Exception:
        return None
    return out


def check_zip(content: bytes) -> "zipfile.ZipFile":
    """Потолки пакета ДО чтения: распакованный размер объявлен в самом
    пакете, и проверить его дешевле, чем узнать о бомбе по кончившейся памяти
    единственного воркера. Отдельной функцией, потому что те же потолки
    нужны импорту и «приложить исходник» в main.py — иначе смета была
    защищена, а импорт того же файла нет."""
    zf = zipfile.ZipFile(io.BytesIO(content))
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise TooBig("В пакете %d частей — больше потолка %d" % (len(infos), MAX_MEMBERS))
    total = sum(i.file_size for i in infos)
    if total > MAX_UNPACKED:
        raise TooBig("Распакованный пакет — %d МБ, потолок %d МБ"
                     % (total // 1024 // 1024, MAX_UNPACKED // 1024 // 1024))
    # Общий потолок пакета мало что говорит об ОДНОЙ части: document.xml
    # на 200 МБ — это гигабайты дерева lxml на единственном воркере.
    for i in infos:
        if i.filename.lower().endswith(".xml") and i.file_size > MAX_XML_PART:
            raise TooBig("Часть %s — %d МБ, потолок %d МБ"
                         % (i.filename, i.file_size // 1024 // 1024, MAX_XML_PART // 1024 // 1024))
    return zf


def _blocks_from_zip(ext: str, content: bytes, notes: list) -> list:
    zf = check_zip(content)
    names = zf.namelist()
    if ext == ".xlsx":
        # ПО ЯЧЕЙКАМ, а не по пулу sharedStrings: пул хранит уникальные строки,
        # и заголовок, стоящий в пяти тысячах строк, считался бы один раз —
        # а импорт заводит сегмент на КАЖДУЮ ячейку (обратная запись кладёт
        # в каждую свой перевод). Смета и списание обязаны сходиться.
        blocks = _xlsx_cell_texts(zf, names)
        if blocks is None:
            blocks = _zip_xml_texts(zf, ["xl/sharedStrings.xml"], "t", unit="si|is", breaks=())
            blocks += _zip_xml_texts(zf, [n for n in names if n.startswith("xl/worksheets/")], "t",
                                     unit="si|is", breaks=())
        notes.append("Формулы и числа в счёт не идут — считается только текст ячеек.")
        return blocks
    if ext == ".pptx":
        slides = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
        notes.append("Заметки к слайдам не считаются: они не идут в перевод по умолчанию.")
        return _zip_xml_texts(zf, slides, "t")
    if ext in (".odt", ".ods", ".odp"):
        if zf.getinfo("content.xml").file_size > MAX_PART:
            raise TooBig("content.xml больше %d МБ" % (MAX_PART // 1024 // 1024))
        raw = zf.read("content.xml")
        got = _odf_blocks(raw)
        if got is not None:
            return got
        body = raw.decode("utf-8", errors="replace")
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


SOFT_HYPHEN = "\u00ad"


# ─── Ход долгого разбора ────────────────────────────────────────────
# Разбор книги идёт секунды, а запрос у браузера один: без хода работы
# человек видит застывшую кнопку и жмёт её снова. Обработчик кладёт сюда
# функцию `cb(stage, done, total)` на время СВОЕГО потока (threading.local:
# разборы идут параллельно, и чужой ход не должен попадать в чужую полосу).
_PROGRESS = threading.local()


def set_progress(cb: Optional[Callable]) -> None:
    _PROGRESS.cb = cb


def progress(stage: str, done: int = 0, total: int = 0) -> None:
    cb = getattr(_PROGRESS, "cb", None)
    if cb is None:
        return
    try:
        cb(stage, done, total)
    except Exception:
        pass                       # показ хода не вправе ронять разбор


# Страницы PDF кэшируются ПО СОДЕРЖИМОМУ: проба, смета и загрузка того же
# файла идут подряд, и каждая читала книгу заново (31 с на 378 страниц,
# трижды). Ответ — либо строки страниц, либо число страниц скана.
_PAGES_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_PAGES_CACHE_MAX = 4
_PAGES_LOCK = threading.Lock()
PDF_PARALLEL_MIN_PAGES = int(os.environ.get("PDF_PARALLEL_MIN_PAGES", "24"))
PDF_WORKERS = max(1, int(os.environ.get("PDF_WORKERS", str(min(4, os.cpu_count() or 1)))))
PDF_WORKER_TIMEOUT = int(os.environ.get("PDF_WORKER_TIMEOUT", "600"))


def _pdf_extract_parallel(content: bytes, n_pages: int, workers: int) -> Optional[list]:
    """Строки страниц — несколькими процессами (`pdfpages_worker.py`), каждый
    берёт свой непрерывный кусок книги. None — не вышло (нет python, упал
    ребёнок, таймаут): тогда вызывающий читает сам, по-старому. Молча
    половину книги не теряем: ответ либо полный, либо None."""
    import subprocess
    script = str(Path(__file__).with_name("pdfpages_worker.py"))
    step = -(-n_pages // workers)
    ranges = [(a, min(a + step, n_pages)) for a in range(0, n_pages, step)]
    pages: list = [None] * n_pages
    geoms: list = [None] * n_pages
    done = [0]
    lock = threading.Lock()
    failed = []
    cb = getattr(_PROGRESS, "cb", None)

    def run(a: int, b: int) -> None:
        try:
            proc = subprocess.Popen([sys.executable, script, str(a), str(b)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        except Exception as e:
            failed.append(str(e))
            return
        timer = threading.Timer(PDF_WORKER_TIMEOUT, proc.kill)
        timer.start()
        try:
            err_box: list = []
            # stderr читаем отдельно: заполненный канал ошибок остановил бы
            # ребёнка, а родитель ждал бы его stdout вечно.
            t_err = threading.Thread(target=lambda: err_box.append(proc.stderr.read()), daemon=True)
            t_err.start()
            try:
                proc.stdin.write(content)
                proc.stdin.close()
            except Exception as e:
                failed.append(str(e))
            for raw in proc.stdout:
                try:
                    row = json.loads(raw)
                    i, lines = row[0], row[1]
                except Exception:
                    continue
                pages[i] = lines
                geoms[i] = row[2] if len(row) > 2 else None
                with lock:
                    done[0] += 1
                    n = done[0]
                if cb is not None:
                    try:
                        cb("read", n, n_pages)
                    except Exception:
                        pass
            proc.wait()
            t_err.join(timeout=5)
            if proc.returncode != 0:
                failed.append((b"".join(err_box) or b"").decode("utf-8", "replace")[:300])
        finally:
            timer.cancel()

    threads = [threading.Thread(target=run, args=r, daemon=True) for r in ranges]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if failed or any(p is None for p in pages):
        print("[textcount] параллельное чтение PDF не удалось (%s) — читаю в одном процессе"
              % "; ".join(x for x in failed if x)[:300], file=sys.stderr)
        return None
    return pages, geoms


def _page_lines(page) -> tuple:
    """(строки, геометрия | None) страницы — тем же кодом, что у дочерних
    процессов (`pdfpages_worker.page_lines`): чтение в одном процессе и
    в четырёх обязано давать одно и то же."""
    try:
        try:
            import pdfpages_worker as _pw        # type: ignore
        except ImportError:
            from . import pdfpages_worker as _pw  # type: ignore
        return _pw.page_lines(page)
    except Exception:
        return (page.extract_text() or "").splitlines(), None


def _pdf_read_pages(content: bytes) -> tuple:
    """("ok", строки страниц, геометрия страниц) или ("scan", число страниц).
    Без кэша."""
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
        n = len(reader.pages)
        got = None
        if n >= PDF_PARALLEL_MIN_PAGES and PDF_WORKERS > 1:
            got = _pdf_extract_parallel(content, n, min(PDF_WORKERS, n))
        if got is None:
            pages, geoms = [], []
            for k, page in enumerate(reader.pages):
                ls, g = _page_lines(page)
                pages.append(ls)
                geoms.append(g)
                progress("read", k + 1, n)
        else:
            pages, geoms = got
    except (NotAvailable,):
        raise
    except Exception as e:
        raise Unsupported("PDF не читается: %s" % e)
    if not any(normalize(b) for ls in pages for b in ls):
        return ("scan", n)
    return ("ok", pages, geoms)


def _pdf_pages(content: bytes, notes: list) -> list:
    """Строки текстового слоя ПО СТРАНИЦАМ (список списков): границы страниц
    нужны импорту — по ним снимаются колонтитулы и номера. PDF читаем только настоящей библиотекой. Нет её — говорим об этом,
    а не возвращаем пустоту: пустой список неотличим от «в файле нет текста».

    Большая книга читается несколькими процессами, а ответ кэшируется по
    содержимому: проба, смета и загрузка того же файла идут подряд. Наружу
    уходит КОПИЯ: чистка правит строки на месте."""
    return _pdf_pages_geom(content, notes)[0]


def _pdf_pages_geom(content: bytes, notes: list) -> tuple:
    """(строки по страницам, геометрия по страницам) — см. `_pdf_pages`;
    геометрия страницы — `pdfpages_worker.page_lines` или None."""
    import hashlib
    key = hashlib.sha1(content).hexdigest()
    with _PAGES_LOCK:
        hit = _PAGES_CACHE.get(key)
        if hit is not None:
            _PAGES_CACHE.move_to_end(key)
    if hit is None:
        hit = _pdf_read_pages(content)
        with _PAGES_LOCK:
            _PAGES_CACHE[key] = hit
            while len(_PAGES_CACHE) > _PAGES_CACHE_MAX:
                _PAGES_CACHE.popitem(last=False)
    else:
        n = hit[1] if hit[0] == "scan" else len(hit[1])
        progress("read", n, n)
    if hit[0] == "scan":
        raise Scan("В PDF нет текстового слоя — это скан. Объём такого файла "
                   "считается только после распознавания.", hit[1])
    notes.append("PDF: текст извлечён из текстового слоя; надписи внутри картинок "
                 "в счёт не идут.")
    geoms = hit[2] if len(hit) > 2 else [None] * len(hit[1])
    return [list(ls) for ls in hit[1]], list(geoms)


def _pdf_blocks(content: bytes, notes: list) -> list:
    """Строки текстового слоя ОДНИМ списком — для сметы. Мягкий перенос
    (U+00AD) на конце строки склеивается со следующей: разрезанное им слово
    иначе считалось бы двумя словами — на боевой книге 3576 таких переносов,
    то есть страницы к оплате завышались на каждом абзаце. Остальная чистка
    (колонтитулы, номера страниц, мусор) здесь НЕ делается: смета молча
    не вычитает ничего, а импорт называет снятое числом."""
    blocks: list = []
    for ls in _pdf_pages(content, notes):
        buf = ""
        for line in ls:
            if buf.rstrip().endswith(SOFT_HYPHEN):
                buf = buf.rstrip()[:-1] + line.lstrip()
            else:
                if buf:
                    blocks.append(buf)
                buf = line
        if buf:
            blocks.append(buf)
    return [b.replace(SOFT_HYPHEN, "") for b in blocks]


SCAN_SAMPLE_PAGES = int(os.environ.get("SCAN_SAMPLE_PAGES", "6"))


def sample_indices(n_pages: int, k: int) -> list:
    """Номера страниц выборки — k штук, разложенных по документу равномерно
    (первая и последняя страницы книги — титул и выходные данные, середина
    интервалов честнее краёв)."""
    n = max(0, int(n_pages))
    k = max(1, min(int(k or 1), n)) if n else 0
    return sorted({int((i + 0.5) * n / k) for i in range(k)})


PAGE_IMAGE_ASPECT_TOL = 0.12
PAGE_RENDER_DPI = int(os.environ.get("PAGE_RENDER_DPI", "144"))


def pdf_render_pages(content: bytes, indices: list, dpi: int = 0) -> Optional[list]:
    """[(номер страницы, PNG bytes | None)] — страницы, ОТРИСОВАННЫЕ целиком
    (pypdfium2). None вместо списка — рендера нет (модуль не поставлен):
    вызывающий берёт вложенную картинку. Зачем рендер, если у скана страница
    и есть картинка: у многослойного скана (DjVu-в-PDF, обложка боевой книги)
    страница — это ФОН + маска с текстом + цветной слой, и крупнейшая
    вложенная картинка (фон) несёт только заголовок, а мелкий текст лежит
    в маске. Отдать зрячей модели фон значит прочитать половину. Рендер
    собирает слои так, как их видит читатель."""
    try:
        import pypdfium2 as pdfium      # type: ignore
    except ImportError:
        return None
    out = []
    try:
        pdf = pdfium.PdfDocument(io.BytesIO(content))
    except Exception:
        return None
    scale = float(dpi or PAGE_RENDER_DPI) / 72.0
    for i in indices:
        data = None
        try:
            page = pdf[i]
            im = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="PNG", optimize=False)
            data = buf.getvalue()
            page.close()
        except Exception:
            data = None
        out.append((i, data))
    try:
        pdf.close()
    except Exception:
        pass
    return out


def pdf_page_pictures(content: bytes, indices: list, full_page: bool = False) -> list:
    """Картинка каждой запрошенной страницы: отрисованная, если есть рендер,
    иначе вложенная (`pdf_page_images`). Один вход для скана, для страниц
    с ненадёжным текстовым слоем и для выборки сметы — чтобы «страница
    как картинка» везде значила одно и то же."""
    rendered = pdf_render_pages(content, indices)
    if rendered is not None and any(d for _i, d in rendered):
        return rendered
    return pdf_page_images(content, indices, full_page=full_page)


def pdf_page_images(content: bytes, indices: list, full_page: bool = False) -> list:
    """[(номер страницы, bytes картинки | None)] — самая крупная картинка каждой
    из запрошенных страниц. Без рендера: у скана страница и есть картинка,
    и pypdf достаёт её как лежит. Нечитаемая (кодек без декодера) или пустая
    страница — None, а не пропуск: число ответов равно числу запрошенных.

    `full_page=True` — годится только картинка РАЗМЕРОМ СО СТРАНИЦУ (пропорции
    как у mediabox): у PDF с текстовым слоем самая крупная картинка страницы —
    это логотип или рисунок, и положить его вместо страницы значило бы
    выбросить её текст и отправить логотип зрячей модели за деньги."""
    from pypdf import PdfReader          # type: ignore
    reader = PdfReader(io.BytesIO(content))
    out = []
    for i in indices:
        best = None
        try:
            page = reader.pages[i]
            try:
                pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            except Exception:
                pw = ph = 0.0
            for im in page.images:
                w, h = im.image.size
                if full_page and pw and ph and w and h:
                    if abs((w / h) - (pw / ph)) > PAGE_IMAGE_ASPECT_TOL * (pw / ph):
                        continue
                if best is None or w * h > best[0]:
                    best = (w * h, im.data)
        except Exception:
            best = None
        out.append((i, best[1] if best else None))
    return out


def measure(filename: str, content: bytes, lang: str, overrides: Optional[dict] = None,
            min_pages: float = 1.0, round_to: float = 0.1,
            docx_paragraphs: Optional[Callable[[bytes], list]] = None,
            words_per_page: Optional[int] = None) -> dict:
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
    norm = norm_for(lang, overrides, words_per_page)
    if norm["spaceless"]:
        got["notes"].append("В этом письме слова не отделяются пробелами — норма задана "
                            "прямо в знаках, счёт слов там условен.")
    return {"file": filename, "kind": got["kind"], "notes": got["notes"],
            "counts": counts, "norm": norm,
            "pages": pages_of(amount_of(counts, norm), norm["perPage"], min_pages, round_to)}
