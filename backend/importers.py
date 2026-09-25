# -*- coding: utf-8 -*-
"""Импорт файла любого поддержанного формата — ЧЕРЕЗ .docx — и возврат
перевода В ТОМ ЖЕ формате.

Зачем именно так. Весь конвейер проекта стоит на .docx: разбор абзацев
(`_docx_paragraph_texts`), якоря «абзац → сегмент», хранение исходника,
экспорт «как в оригинале», разбор надписей на картинках (`image_text`).
Второй конвейер под Excel, HTML и картинки означал бы второй набор якорей,
второй экспорт и второй разбор картинок — и все они однажды разошлись бы
с первым. Поэтому чужой формат сначала ПРЕВРАЩАЕТСЯ в .docx, а дальше идёт
штатной дорогой.

**Слот.** У текстовых форматов файл режется на СЛОТЫ — куски текста
с адресом в исходнике (строка txt, ячейка csv/xlsx, абзац слайда, блочный
пробег html). Слот i становится абзацем i собранного .docx — ВКЛЮЧАЯ пустые
(пустой абзац): номер абзаца и есть якорь сегмента, и выброшенный пустой слот
сдвинул бы все номера. Обратная запись (`write_back`) считает адреса заново
ТЕМ ЖЕ кодом по хранимому оригиналу (`data/sources/{pid}.orig.<ext>`)
и кладёт перевод абзаца i в слот i; непереведённый слот остаётся как был.
Хранить адреса рядом незачем: разбор детерминирован, а исходник лежит.
**Правила резки меняются**, поэтому на проекте лежит отпечаток слотов
(`slots_sha`): разошёлся — выгрузка отказывает (400), а не кладёт переводы
в чужие ячейки молча. Сменённое правило резки получает номер (`SLOT_RULE`),
а прежнее остаётся: отпечаток старого проекта сходится с прежним правилом,
и им же выгрузка раскладывает переводы (`slots_rule_for`).

Что теряется, названо честно (`note` при импорте):
  * xlsx — обратная запись через openpyxl: картинки, диаграммы, фигуры
    и примечания листа не переживают перезапись, формулы и числа не
    трогаются, перенос строки внутри ячейки становится пробелом;
  * html — внутри переведённого пробега инлайн-разметка (<b>, <a>) не
    сохраняется: пробег заменяется текстом перевода; картинки и прочие
    вставки (<img>, <iframe>, <input>…) режут пробег и остаются на месте;
    атрибуты (title, alt) не переводятся;
  * pptx — абзац слайда получает перевод целиком в первый прогон, выделения
    внутри абзаца теряются; поля (номер слайда, дата) не трогаются; заметки,
    диаграммы и SmartArt не переводятся;
  * srt/vtt — перевод встаёт в ту же реплику, время не трогается; разметка
    внутри реплики (курсив, цвет) не сохраняется;
  * json/xml/po/yaml/rtf/odt/ods/odp — только Word-документом:
    построчная обратная запись сломала бы их синтаксис;
  * картинки и скан-PDF — перевод возвращается перерисовкой надписей
    (см. `image_text`), это делает экспорт «как в оригинале» по .docx,
    а картинки достаются из него; pdf с текстовым слоем — PDF из .docx
    конвертером (`topdf`), не исходный файл.

Ни одного вызова модели. Потолки размера — те же, что у сметы (`textcount`).
"""
import csv
import hashlib
import html as _html
import io
import os
import re
import zipfile
from typing import Optional

try:
    import textcount
    import pdftext
except ImportError:                                   # pragma: no cover
    from . import textcount                            # type: ignore
    from . import pdftext                              # type: ignore

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
# Что принимаем. Смета умеет то же плюс .pdf; картинки — только здесь.
SUPPORTED_EXT = sorted(set(textcount.SUPPORTED_EXT) | IMAGE_EXT)
# Построчные форматы с обратной записью: строка — слот.
LINE_EXT = {".txt", ".md", ".markdown", ".log", ""}
# Форматы, которые умеем вернуть В ТОМ ЖЕ виде (обратной записью по слотам).
WRITEBACK_EXT = LINE_EXT | {".csv", ".tsv", ".xlsx", ".html", ".htm", ".pptx", ".srt", ".vtt"}
# Строки PDF склеиваются в абзац, пока не встретится конец предложения,
# пустая строка или потолок длины: без потолка титульный лист с сотней
# коротких строк без точек стал бы одним абзацем на страницу.
PDF_PARA_MAX = 1200
_PDF_END_RE = re.compile(r"[.!?…:;»”\")\]]\s*$")
# Максимальная ширина картинки в .docx — ширина листа A4 с полями.
_PIC_WIDTH_IN = 6.3
# Управляющие символы, которых lxml в тексте абзаца не принимает.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def ext_of(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in (filename or "") else ""


def kind_of(filename: str) -> str:
    """docx | image | pdf | text | unsupported — что делать с файлом."""
    ext = ext_of(filename)
    if ext == ".docx":
        return "docx"
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in textcount.TEXT_EXT or ext in textcount.ZIP_EXT or not ext:
        return "text"
    return "unsupported"


# Версия ПРАВИЛА резки слотов. 1 — прежнее: у html каждый тег — пробел,
# у pptx `<a:br/>` ничего не давал и мягкий перенос оставался в тексте;
# 2 — текущее (`_html_run_text`, `_pptx_para_text`). Отпечаток `slotsSha`
# старого проекта снят правилом 1, и без версий выгрузка «как в оригинале»
# у него отказывала бы 400 навсегда: повторная заливка того же файла — 409
# дубликата, а повторный импорт — новые платные сегменты там, где текст
# слота сменился. Поэтому выгрузка подбирает правило по отпечатку
# (`slots_rule_for`) и тем же правилом кладёт переводы (`write_back`).
SLOT_RULE = 2
SLOT_RULES = (2, 1)             # порядок перебора: сначала текущее


def slots_sha(slots: list) -> str:
    """Отпечаток слотов: по нему выгрузка проверяет, что резка не изменилась."""
    h = hashlib.sha1()
    for s in slots:
        h.update((s or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _document():
    from docx import Document  # type: ignore
    return Document()


def _clean(s: str) -> str:
    return _CTRL_RE.sub(" ", s or "")


def _encoding_of(enc: str, content: bytes = b"") -> str:
    """Кодировка исходника для обратной записи — та же, в какой он пришёл:
    страница с <meta charset="windows-1251"> в UTF-8 показалась бы кашей.
    «utf-8-sig» декодирует и файл без BOM — BOM пишем только туда, где он был."""
    enc = (enc or "utf-8").replace("/lossy", "")
    if not enc or enc == "lossy":
        return "utf-8"
    if enc.lower() in ("utf-8-sig", "utf_8_sig"):
        return "utf-8-sig" if content[:3] == b"\xef\xbb\xbf" else "utf-8"
    return enc


# ─── Картинки ────────────────────────────────────────────────────────

def _exif_upright(im):
    """Фото со смартфона лежит боком: ориентация записана в EXIF, а Word
    (и разбор надписей) читают пиксели как есть. Поворачиваем по EXIF."""
    try:
        from PIL import ImageOps  # type: ignore
        return ImageOps.exif_transpose(im) or im
    except Exception:
        return im


def _png_with_index(im, index: int) -> bytes:
    """PNG с номером кадра в метаданных. python-docx ДЕДУПЛИЦИРУЕТ картинки
    по sha1: две одинаковые страницы скана (пустые обороты — норма) дали бы
    одну часть, и выгрузка была бы короче оригинала. Номер в tEXt делает
    байты разными, пиксели — те же."""
    from PIL import PngImagePlugin  # type: ignore
    info = PngImagePlugin.PngInfo()
    info.add_text("medcat-page", str(index))
    out = io.BytesIO()
    im.save(out, format="PNG", pnginfo=info)
    return out.getvalue()


def _to_png_or_keep(data: bytes, ext: str) -> tuple:
    """Картинка для .docx: png/jpeg остаются как есть (сохраняются EXIF и
    профиль), кроме JPEG с EXIF-поворотом — тот перекодируется в правильном
    положении; остальное перекодируется в PNG — Word (и python-docx) webp
    не берут. Возвращает (bytes, ext)."""
    try:
        from PIL import Image  # type: ignore
        im = Image.open(io.BytesIO(data))
        orient = 1
        try:
            orient = int((im.getexif() or {}).get(274, 1) or 1)
        except Exception:
            orient = 1
        if ext == ".png" or (ext in (".jpg", ".jpeg") and orient == 1):
            return data, ext
        im = _exif_upright(im)
        out = io.BytesIO()
        if ext in (".jpg", ".jpeg"):
            im.convert("RGB").save(out, format="JPEG", quality=92)
            return out.getvalue(), ext
        if im.mode not in ("RGB", "RGBA", "L", "P"):
            im = im.convert("RGB")
        im.save(out, format="PNG")
        return out.getvalue(), ".png"
    except textcount.Unsupported:
        raise
    except Exception as e:
        raise textcount.Unsupported("Картинка %s не читается: %s" % (ext, e))


def _frames(data: bytes, ext: str) -> list:
    """[(bytes, ext)] — кадры многостраничного TIFF (скан книги) отдельными
    картинками PNG (с номером кадра — см. `_png_with_index`); у прочих
    форматов — одна, как есть."""
    if ext not in (".tif", ".tiff"):
        return [(data, ext)]
    try:
        from PIL import Image, ImageSequence  # type: ignore
        im = Image.open(io.BytesIO(data))
        out = []
        for i, frame in enumerate(ImageSequence.Iterator(im)):
            fr = _exif_upright(frame.copy())
            if fr.mode not in ("RGB", "L", "1", "P", "RGBA"):
                fr = fr.convert("RGB")
            out.append((_png_with_index(fr, i), ".png"))
        return out or [(data, ext)]
    except Exception:
        return [(data, ext)]


def images_to_docx(images: list) -> bytes:
    """[(bytes, ext)] → .docx, по картинке на абзац. Страницы скана приходят
    PNG с номером в метаданных — одинаковые страницы не схлопываются."""
    from docx.shared import Inches  # type: ignore
    doc = _document()
    n = 0
    for data, ext in images:
        if not data:
            continue
        for frame, f_ext in _frames(data, ext):        # кадры считаются ОДИН раз
            pic, pic_ext = _to_png_or_keep(frame, f_ext)
            try:
                doc.add_picture(io.BytesIO(pic), width=Inches(_PIC_WIDTH_IN))
                n += 1
            except Exception as e:
                raise textcount.Unsupported("Картинка не вставилась в документ: %s" % e)
    if not n:
        raise textcount.Unsupported("Ни одной читаемой картинки не нашлось")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def scan_pages_to_docx(pages: list) -> bytes:
    """Страницы скан-PDF (bytes картинок) → .docx; каждая страница получает
    номер в метаданных PNG, чтобы одинаковые не схлопнулись."""
    from PIL import Image  # type: ignore
    imgs = []
    for i, data in enumerate(pages):
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            im = _exif_upright(im)
            if im.mode not in ("RGB", "L", "1", "P", "RGBA"):
                im = im.convert("RGB")
            imgs.append((_png_with_index(im, i), ".png"))
        except Exception:
            continue
    return images_to_docx(imgs)


def images_from_docx(docx_bytes: bytes) -> list:
    """[(имя части, bytes)] — растровые картинки пакета в порядке частей.
    У документа, собранного `images_to_docx`, части идут image1, image2, …
    в порядке вставки (каждая уникальна — см. `_png_with_index`); из
    ВЫГРУЗКИ 1в1 достаём перерисованные."""
    out = []
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        names = [n for n in z.namelist() if n.startswith("word/media/")]

        def num(n):
            m = re.search(r"(\d+)", n.rsplit("/", 1)[-1])
            return int(m.group(1)) if m else 0
        for n in sorted(names, key=num):
            out.append((n, z.read(n)))
    return out


def images_to_file(images: list, ext: str) -> bytes:
    """Картинки → файл исходного вида: одна картинка — как есть (перекодируется
    в исходное расширение), многостраничный TIFF — обратно многостраничным
    (режим кадра сохраняется: 1-битный факс не раздувается в RGB), скан-PDF —
    PDF из страниц; ширина страницы — как у A4 при пикселях скана. Текстового
    слоя у скана не было — нет и здесь."""
    from PIL import Image  # type: ignore
    ext = (ext or "").lower()
    frames = [Image.open(io.BytesIO(b)) for _n, b in images if b]
    if not frames:
        raise textcount.Unsupported("В выгрузке нет ни одной картинки")
    for im in frames:
        im.load()
    out = io.BytesIO()
    if ext == ".pdf":
        pages = [im.convert("RGB") if im.mode not in ("RGB", "L") else im for im in frames]
        dpi = max(72.0, pages[0].size[0] / 8.27)        # ширина A4 в дюймах
        pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:], resolution=dpi)
        return out.getvalue()
    if ext in (".tif", ".tiff"):
        pages = [im if im.mode in ("1", "L", "RGB", "P") else im.convert("RGB") for im in frames]
        comp = "group4" if all(p.mode == "1" for p in pages) else "tiff_lzw"
        pages[0].save(out, format="TIFF", save_all=True, append_images=pages[1:], compression=comp)
        return out.getvalue()
    im = frames[0]
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".bmp": "BMP",
           ".gif": "GIF"}.get(ext, "PNG")
    if fmt == "JPEG":
        im = im.convert("RGB")
    elif fmt in ("BMP", "GIF") and im.mode not in ("RGB", "P", "L"):
        im = im.convert("RGB")
    im.save(out, format=fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    return out.getvalue()


# ─── Слоты текстовых форматов ────────────────────────────────────────

_HTML_BLOCK = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
               "table", "section", "article", "header", "footer", "blockquote", "pre", "dd", "dt",
               "figcaption", "caption", "title", "hr", "form", "fieldset", "legend", "nav", "aside",
               "main", "address", "summary", "details", "td", "th", "thead", "tbody", "tfoot",
               "option", "label", "button", "figure", "body", "html", "head", "dl", "menu",
               # Вставки внутри абзаца режут пробег и остаются на месте:
               # иначе обратная запись стёрла бы картинку вместе с диапазоном.
               "img", "iframe", "video", "audio", "input", "select", "textarea", "object",
               "embed", "canvas", "picture", "source", "map", "area"}
_HTML_SKIP = {"script", "style", "noscript", "template", "svg", "math"}


_HTML_BR_RE = re.compile(r"<br\b[^>]*>", re.I)
_HTML_ANY_TAG_RE = re.compile(r"<!--.*?-->|<[^>]*>", re.S)


def _html_run_text(raw: str, rule: int = SLOT_RULE) -> str:
    """Текст пробега так, как его видит читатель страницы: инлайн-тег — не
    пробел («полн<b>ый</b>» — одно слово, «H<sub>2</sub>O» — «H2O»,
    «<a>ссылка</a>.» — без пробела перед точкой), `<br>` — пробел, мягкий
    перенос (`&shy;`, `<wbr>`) в тексте не остаётся. Прежде (правило 1)
    каждый тег становился пробелом и резал слова посередине; правило 1
    оставлено для проектов, залитых до смены (см. `SLOT_RULE`)."""
    if rule < 2:
        return " ".join(_html.unescape(re.sub(r"<[^>]*>", " ", raw)).split())
    s = _HTML_BR_RE.sub(" ", raw)
    s = _HTML_ANY_TAG_RE.sub("", s)
    s = _html.unescape(s).replace("­", "")
    return " ".join(s.split())


def html_slots(text: str, rule: int = SLOT_RULE) -> list:
    """[(текст пробега, (начало, конец))] — блочные текстовые пробеги HTML
    с ОФФСЕТАМИ в исходной строке. Пробег — всё между двумя блочными тегами
    (инлайн-теги внутри остаются частью пробега: «Абзац <b>жирный</b> текст»
    — один слот, как в .docx). Ячейки таблицы — свои пробеги. Обратная
    запись заменяет диапазон текстом перевода, и инлайн-разметка внутри
    теряется — это названо в докстроке модуля. Оффсеты строк считаются
    по «\\n», как считает их `HTMLParser.getpos()` (а не `splitlines`,
    у которого границ строк больше)."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.out, self.skip = [], 0
            self.run_start = None          # оффсет начала текущего пробега
            self.has_text = False

        def _off(self):
            line, col = self.getpos()
            return self.line_off[line - 1] + col

        def _cut(self, end):
            if self.run_start is not None and self.has_text and end > self.run_start:
                raw = self.src[self.run_start:end]
                txt = _html_run_text(raw, rule)
                if txt:
                    self.out.append((txt, (self.run_start, end)))
            self.run_start = None
            self.has_text = False

        def handle_starttag(self, tag, attrs):
            off = self._off()
            if tag in _HTML_SKIP:
                self._cut(off)
                self.skip += 1
            elif tag in _HTML_BLOCK:
                self._cut(off)
            elif self.run_start is None and not self.skip:
                self.run_start = off

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            # Одиночная вставка (<img/>): пробег после неё начинается заново.
            if tag in _HTML_BLOCK:
                self.run_start = None

        def handle_endtag(self, tag):
            off = self._off()
            if tag in _HTML_SKIP:
                self.skip = max(0, self.skip - 1)
                self.run_start = None
            elif tag in _HTML_BLOCK:
                self._cut(off)

        def handle_data(self, data):
            if self.skip:
                return
            off = self._off()
            if self.run_start is None:
                self.run_start = off
            if data.strip():
                self.has_text = True

        def handle_entityref(self, name):
            self.handle_data("&" + name + ";")

        def handle_charref(self, name):
            self.handle_data("&#" + name + ";")

        def handle_comment(self, data):
            pass

    p = P()
    p.src = text or ""
    offs, acc = [], 0
    for line in p.src.split("\n"):
        offs.append(acc)
        acc += len(line) + 1
    offs.append(acc)
    p.line_off = offs
    p.feed(p.src)
    p.close()
    p._cut(len(p.src))
    # Пробег обрезается по краям до текста: заменять ведущие пробелы/переносы
    # незачем, а сохранить их — значит сохранить отступы разметки.
    out = []
    for txt, (a, b) in p.out:
        raw = p.src[a:b]
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw) - len(raw.rstrip())
        out.append((txt, (a + lead, b - trail)))
    return out


def html_paragraphs(text: str) -> list:
    """Тексты пробегов HTML — для .docx при импорте (см. `html_slots`)."""
    return [t for t, _rng in html_slots(text)]


def _pptx_slide_names(z: zipfile.ZipFile) -> list:
    """Слайды в ПОРЯДКЕ ПОКАЗА: по `p:sldIdLst` презентации через rels,
    а не по номеру файла — после перестановки слайдов файлы не переименовываются."""
    names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    by_num = sorted(names, key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    try:
        pres = z.read("ppt/presentation.xml").decode("utf-8", "replace")
        rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8", "replace")
        rid_to = {}
        for m in re.finditer(r"<Relationship\b[^>]*>", rels):
            tag = m.group(0)
            rid = re.search(r'\bId="([^"]+)"', tag)
            tgt = re.search(r'\bTarget="([^"]+)"', tag)
            if rid and tgt:
                t = tgt.group(1).lstrip("/")
                rid_to[rid.group(1)] = t if t.startswith("ppt/") else "ppt/" + t
        order = []
        for m in re.finditer(r"<p:sldId\b[^>]*\br:id=\"([^\"]+)\"", pres):
            name = rid_to.get(m.group(1))
            if name in names and name not in order:
                order.append(name)
        return order + [n for n in by_num if n not in order]
    except Exception:
        return by_num


_A_P_RE = re.compile(r"<a:p\b[^>]*>.*?</a:p>", re.S)
_A_T_RE = re.compile(r"<a:t(?:\s[^>]*)?>(.*?)</a:t>|<a:t(?:\s[^>]*)?/>", re.S)
_A_FLD_RE = re.compile(r"<a:fld\b[^>]*>.*?</a:fld>", re.S)
_A_BR_RE = re.compile(r"<a:br\b[^>]*/>|<a:br\b[^>]*>.*?</a:br>", re.S)


def _pptx_para_text(p_xml: str, rule: int = SLOT_RULE) -> str:
    """Текст абзаца без ПОЛЕЙ (номер слайда, дата): их считает PowerPoint,
    и перевод в них исчез бы при первом открытии. Разрыв строки внутри
    абзаца (`<a:br/>`, Shift+Enter) — пробел: без него последнее слово
    одной строки слипалось с первым следующей («ТашкентУзбекистан»).
    Мягкий перенос в тексте не остаётся. Правило 1 (до смены, см.
    `SLOT_RULE`) — без того и другого."""
    if rule < 2:
        parts = [_html.unescape(m.group(1) or "") for m in _A_T_RE.finditer(_A_FLD_RE.sub("", p_xml))]
        return " ".join("".join(parts).split())
    body = _A_BR_RE.sub("<a:t> </a:t>", _A_FLD_RE.sub("", p_xml))
    parts = [_html.unescape(m.group(1) or "") for m in _A_T_RE.finditer(body)]
    return " ".join("".join(parts).replace("­", "").split())


def pptx_slots(content: bytes, rule: int = SLOT_RULE) -> list:
    """[(текст абзаца, (часть, номер абзаца в части))] — абзацы `<a:p>`
    на слайдах в порядке показа (заметки к слайдам не берутся)."""
    out = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for name in _pptx_slide_names(z):
            xml = z.read(name).decode("utf-8", "replace")
            for i, m in enumerate(_A_P_RE.finditer(xml)):
                out.append((_pptx_para_text(m.group(0), rule), (name, i)))
    return out


def _pptx_write(content: bytes, repl: dict) -> bytes:
    """repl: {(часть, номер абзаца): перевод}. Первый `<a:t>` абзаца ВНЕ поля
    получает весь текст, остальные вне полей пустеют; поля не трогаются;
    абзац без `<a:t>` не трогается. Прочие части пакета — байт в байт."""
    src = zipfile.ZipFile(io.BytesIO(content))
    parts = {k[0] for k in repl}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename in parts:
                xml = data.decode("utf-8", "replace")
                counter = [0]

                def fix_p(m):
                    i = counter[0]
                    counter[0] += 1
                    new = repl.get((item.filename, i))
                    if new is None:
                        return m.group(0)
                    p_xml = m.group(0)
                    # Поля вырезаем на время правки и возвращаем на место.
                    holes = []

                    def keep_fld(mf):
                        holes.append(mf.group(0))
                        return "\x00FLD%d\x00" % (len(holes) - 1)
                    body = _A_FLD_RE.sub(keep_fld, p_xml)
                    first = [True]

                    def fix_t(mt):
                        if first[0]:
                            first[0] = False
                            return "<a:t>%s</a:t>" % _html.escape(new, quote=False)
                        return "<a:t></a:t>"
                    body = _A_T_RE.sub(fix_t, body)
                    for j, h in enumerate(holes):
                        body = body.replace("\x00FLD%d\x00" % j, h)
                    return body
                xml = _A_P_RE.sub(fix_p, xml)
                data = xml.encode("utf-8")
            dst.writestr(item, data)
    return out.getvalue()


def xlsx_slots(content: bytes) -> list:
    """[(текст ячейки, (лист, координата))] — строковые ячейки без формул,
    по листам и строкам. Числа и формулы — не текст, переводить нечего."""
    from openpyxl import load_workbook  # type: ignore
    wb = load_workbook(io.BytesIO(content), data_only=False)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.strip() and not v.startswith("="):
                    out.append((v, (ws.title, c.coordinate)))
    return out


def _xlsx_write(content: bytes, repl: dict) -> bytes:
    from openpyxl import load_workbook  # type: ignore
    wb = load_workbook(io.BytesIO(content))
    for (sheet, coord), new in repl.items():
        try:
            wb[sheet][coord].value = new
        except Exception:
            continue
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _csv_dialect(text: str, ext: str):
    if ext == ".tsv":
        return "excel-tab"
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except Exception:
        return "excel"


def csv_slots(text: str, ext: str) -> list:
    """[(текст ячейки, (строка, столбец))] — КАЖДАЯ ячейка (пустая тоже:
    иначе номера ячеек уехали бы), построчно."""
    rows = list(csv.reader(io.StringIO(text), dialect=_csv_dialect(text, ext)))
    return [(cell, (r, c)) for r, row in enumerate(rows) for c, cell in enumerate(row)]


def _csv_write(text: str, ext: str, repl: dict) -> str:
    dialect = _csv_dialect(text, ext)
    rows = list(csv.reader(io.StringIO(text), dialect=dialect))
    for (r, c), new in repl.items():
        if r < len(rows) and c < len(rows[r]):
            rows[r][c] = new
    out = io.StringIO()
    w = csv.writer(out, dialect=dialect, lineterminator="\r\n" if "\r\n" in text[:4096] else "\n")
    w.writerows(rows)
    return out.getvalue()


def line_slots(text: str) -> list:
    """[(строка без отступа, номер)] — каждая строка файла, пустые тоже."""
    return [(ln.strip(), i) for i, ln in enumerate(text.split("\n"))]


def _lines_write(text: str, repl: dict) -> str:
    """Перевод строки — на место её текста, ОТСТУП и хвост строки (\\r)
    сохраняются: вложенные списки и код в .md иначе выровнялись бы в ноль."""
    lines = text.split("\n")
    out = []
    for i, ln in enumerate(lines):
        if i in repl:
            body = ln.rstrip("\r")
            lead = body[:len(body) - len(body.lstrip())]
            out.append(lead + repl[i] + ln[len(body):])
        else:
            out.append(ln)
    return "\n".join(out)


# ─── Субтитры: реплика — слот, время — неприкосновенно ────────────────
# Реплика SRT/VTT — единица ВРЕМЕНИ, и перевод обязан встать в ту же
# реплику с тем же таймингом: номер, строка времени, настройки реплики VTT
# и шапка остаются байт в байт, меняются только строки текста. Текст слота —
# тот же, что у сметы (`textcount._cue_blocks`: строки реплики через пробел,
# разметка голоса и курсива снята), иначе смета и сегменты разошлись бы.
# Из этих же реплик берёт тайминги озвучка (`media`), поэтому разбор ОДИН.
_CUE_TIMES_RE = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})")
_BOM = b"\xef\xbb\xbf"
CUE_LINE_CHARS = 42         # ширина строки субтитра: принятая норма ТВ и стримингов


def cue_seconds(stamp: str) -> float:
    """«01:02:03,450» / «02:03.450» → секунды."""
    parts = stamp.replace(",", ".").split(":")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return round(sec, 3)


def cue_list(text: str) -> list:
    """[{text, lines: [номера строк текста], start, end}] — реплики файла
    субтитров. Правила те же, что у `textcount._cue_blocks` (шапка и блоки
    NOTE/STYLE/REGION — не текст; номер и имя реплики до строки времени —
    не текст; реплики без пустой строки между ними различаются по строке
    времени); у блока без строки времени start/end — None."""
    out = []
    cur, idx = [], []
    start = end = None
    skip = timed = False

    def flush():
        if cur:
            out.append({"text": " ".join(cur), "lines": list(idx), "start": start, "end": end})

    for n, raw in enumerate(text.split("\n")):
        line = raw.rstrip("\r").strip()
        if not line:
            flush()
            cur, idx, skip, timed = [], [], False, False
            start = end = None
            continue
        if skip:
            continue
        if not cur and (line.upper().startswith("WEBVTT") or line.split(" ")[0] in ("NOTE", "STYLE", "REGION")):
            skip = True
            continue
        m = _CUE_TIMES_RE.match(line)
        if m:
            if timed:
                if cur and cur[-1].isdigit():
                    cur.pop()
                    idx.pop()
                flush()
            cur, idx, timed = [], [], True
            start, end = cue_seconds(m.group(1)), cue_seconds(m.group(2))
            continue
        if not cur and line.isdigit():
            continue
        t = _html.unescape(textcount._CUE_TAG_RE.sub("", line)).strip()
        if t:
            cur.append(t)
            idx.append(n)
    flush()
    return out


def wrap_cue(text: str, width: int = CUE_LINE_CHARS) -> list:
    """Перевод реплики — в строки экрана. До `width` знаков — одна строка;
    длиннее — две РАВНЫЕ по длине (разрез на пробеле ближе к середине):
    «лесенка» из длинной и короткой строки читается хуже. Письмо без
    пробелов (иероглифы) не режется — переносит плеер."""
    t = " ".join((text or "").split())
    if len(t) <= width or " " not in t:
        return [t]
    mid = len(t) // 2
    cut = min((i for i, ch in enumerate(t) if ch == " "), key=lambda i: abs(i - mid))
    head, tail = t[:cut], t[cut + 1:]
    if len(tail) > width * 1.6 and " " in tail:     # очень длинная реплика: третья строка
        return [head] + wrap_cue(tail, width)
    return [head, tail]


def _cues_write(text: str, repl: dict) -> str:
    """Перевод реплики i — на место её строк текста; время, номер, шапка
    и настройки VTT не трогаются. Конец строки (\\r\\n) — как в исходнике."""
    lines = text.split("\n")
    cues = cue_list(text)
    drop, put = set(), {}
    for i, t in repl.items():
        if not (0 <= i < len(cues)) or not cues[i]["lines"]:
            continue
        ln = cues[i]["lines"]
        put[ln[0]] = wrap_cue(t)
        drop.update(ln[1:])
    out = []
    for n, raw in enumerate(lines):
        if n in drop:
            continue
        if n in put:
            eol = "\r" if raw.endswith("\r") else ""
            out.extend(s + eol for s in put[n])
            continue
        out.append(raw)
    return "\n".join(out)


def _stamp(sec: float, sep: str) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, ms)


def render_cues(cues: list, ext: str) -> str:
    """[{start, end, text}] → текст .srt или .vtt. Реплики без времени
    пропускаются: без времени субтитр показать негде."""
    vtt = ext == ".vtt"
    out = ["WEBVTT", ""] if vtt else []
    n = 0
    for c in cues:
        if c.get("start") is None or c.get("end") is None \
                or not ((c.get("text") or "").strip() or any((c.get("screen") or []))):
            continue
        n += 1
        if not vtt:
            out.append(str(n))
        sep = "." if vtt else ","
        out.append("%s --> %s" % (_stamp(c["start"], sep), _stamp(c["end"], sep)))
        # `screen` — готовые строки экрана (двуязычные субтитры: оригинал,
        # под ним перевод), иначе текст реплики раскладывается сам. Не
        # `lines`: так `cue_list` называет номера строк файла.
        out.extend([ln for ln in c["screen"] if ln] if c.get("screen") else wrap_cue(c["text"]))
        out.append("")
    return "\n".join(out)


def extract_slots(filename: str, content: bytes, rule: int = SLOT_RULE) -> dict:
    """{slots: [текст], kind, note, writeback: bool, enc} — слоты текстового
    файла. Слот i станет абзацем i собранного .docx. Форматы без обратной
    записи отдают куски `textcount.extract` и обратно выгружаются
    Word-документом. `rule` — версия правила резки (`SLOT_RULE`), нужна
    только выгрузке старых проектов."""
    ext = ext_of(filename)
    kind = ext[1:] if ext else "text"
    if ext in LINE_EXT:
        text, enc = textcount._decode(content)
        if "\x00" in text[:4096]:
            raise textcount.Unsupported("Двоичный файл: текста в нём нет. Поддерживаются: %s"
                                        % ", ".join(SUPPORTED_EXT))
        note = "Текст разложен по строкам; обратно выгружается таким же файлом."
        if enc.endswith("lossy"):
            note += " Кодировка файла не опознана — часть символов заменена."
        return {"slots": [_clean(ln) for ln, _i in line_slots(text)], "kind": kind or "text",
                "note": note, "writeback": True, "enc": enc}
    if ext in (".csv", ".tsv"):
        text, enc = textcount._decode(content)
        return {"slots": [_clean(c) for c, _a in csv_slots(text, ext)], "kind": kind,
                "note": "Каждая ячейка — своя строка; обратно выгружается такой же таблицей.",
                "writeback": True, "enc": enc}
    if ext in (".html", ".htm"):
        text, enc = textcount._decode(content)
        return {"slots": [_clean(t) for t, _r in html_slots(text, rule)], "kind": kind,
                "note": "Текст взят по блокам разметки; обратно выгружается той же страницей — "
                        "выделения внутри абзаца (жирный, ссылки) в переводе не сохраняются.",
                "writeback": True, "enc": enc}
    if ext == ".xlsx":
        try:
            slots = [_clean(t) for t, _a in xlsx_slots(content)]
        except Exception as e:
            raise textcount.Unsupported("Книга Excel не читается: %s" % e)
        return {"slots": slots, "kind": "xlsx",
                "note": "Переводятся текстовые ячейки; числа и формулы остаются. Обратно "
                        "выгружается такая же книга — картинки, диаграммы, фигуры и примечания "
                        "листов при этом не сохраняются, перенос строки в ячейке становится пробелом.",
                "writeback": True, "enc": None}
    if ext == ".pptx":
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise textcount.Unsupported("Файл .pptx повреждён: это не пакет OOXML")
        return {"slots": [_clean(t) for t, _a in pptx_slots(content, rule)], "kind": "pptx",
                "note": "Переводится текст слайдов; обратно выгружается та же презентация — "
                        "выделения внутри абзаца не сохраняются, поля (номер слайда, дата) "
                        "не трогаются, заметки, диаграммы и SmartArt не переводятся.",
                "writeback": True, "enc": None}
    if ext in (".srt", ".vtt"):
        text, enc = textcount._decode(content)
        return {"slots": [_clean(c["text"]) for c in cue_list(text)], "kind": kind,
                "note": "Реплики разобраны по времени; обратно выгружается таким же файлом субтитров "
                        "с прежними таймингами. Разметка внутри реплики (курсив, цвет) в переводе "
                        "не сохраняется.",
                "writeback": True, "enc": enc}
    # Остальное (json, xml, po, yaml, rtf, odt/ods/odp …) — кусками
    # сметы, без обратной записи: построчная запись сломала бы синтаксис.
    got = textcount.extract(filename, content)
    blocks = [_clean(b) if isinstance(b, str) else str(b) for b in got["blocks"]]
    lost = {"ods": "раскладка листа", "odp": "раскладка слайдов", "odt": "оформление"}
    note = ("Файл %s превращён в документ Word: %s не переносится, обратно выгружается "
            "Word-документом." % (got["kind"], lost.get(got["kind"], "разметка")))
    if got.get("notes"):
        note += " " + " ".join(got["notes"])
    return {"slots": blocks, "kind": got["kind"], "note": note, "writeback": False, "enc": None}


def slots_rule_for(filename: str, content: bytes, sha: str) -> Optional[int]:
    """Версия правила резки, которой снят отпечаток `sha` проекта, или None —
    ни одна не сходится (файл или разбор изменились так, что номера слотов
    уже не те). Правила перебираются от текущего: у файла без различий
    между ними отпечатки совпадают, и берётся текущее."""
    for rule in SLOT_RULES:
        if slots_sha(extract_slots(filename, content, rule)["slots"]) == sha:
            return rule
        if ext_of(filename) not in (".html", ".htm", ".pptx"):
            break                       # у прочих форматов правило одно
    return None


def write_back(filename: str, content: bytes, translations: dict, rule: int = SLOT_RULE) -> bytes:
    """Перевод в файл ИСХОДНОГО формата: translations — {номер слота: текст}.
    Адреса слотов считаются заново по оригиналу тем же кодом, что при
    импорте, и тем же правилом резки (`rule`, см. `slots_rule_for`): от
    правила у html зависит, какой пробег пуст и выпадает из счёта.
    Кодировка текста — исходная. Непереведённые слоты остаются."""
    ext = ext_of(filename)
    if ext in (".csv", ".tsv"):
        text, enc = textcount._decode(content)
        addr = [a for _c, a in csv_slots(text, ext)]
        repl = {addr[i]: t for i, t in translations.items() if 0 <= i < len(addr)}
        return _csv_write(text, ext, repl).encode(_encoding_of(enc, content), errors="replace")
    if ext in (".html", ".htm"):
        text, enc = textcount._decode(content)
        ranges = [r for _t, r in html_slots(text, rule)]
        pieces, pos = [], 0
        for i, (a, b) in enumerate(ranges):
            if i in translations and a >= pos:
                pieces.append(text[pos:a])
                pieces.append(_html.escape(translations[i], quote=False))
                pos = b
        pieces.append(text[pos:])
        return "".join(pieces).encode(_encoding_of(enc, content), errors="xmlcharrefreplace")
    if ext == ".xlsx":
        addr = [a for _t, a in xlsx_slots(content)]
        repl = {addr[i]: t for i, t in translations.items() if 0 <= i < len(addr)}
        return _xlsx_write(content, repl)
    if ext == ".pptx":
        addr = [a for _t, a in pptx_slots(content)]
        repl = {addr[i]: t for i, t in translations.items() if 0 <= i < len(addr)}
        return _pptx_write(content, repl)
    if ext in (".srt", ".vtt"):
        text, enc = textcount._decode(content)
        bom = content[:3] == _BOM
        body = _cues_write(text, dict(translations)).encode(_encoding_of(enc, content), errors="replace")
        return (_BOM + body) if bom and not body.startswith(_BOM) else body
    if ext in LINE_EXT:
        text, enc = textcount._decode(content)
        bom = content[:3] == b"\xef\xbb\xbf"
        body = _lines_write(text, dict(translations)).encode(_encoding_of(enc, content), errors="replace")
        return (b"\xef\xbb\xbf" + body) if bom and not body.startswith(b"\xef\xbb\xbf") else body
    raise textcount.Unsupported("Для формата %s обратной записи нет — выгружайте Word-документом" % ext)


# ─── Сборка .docx ────────────────────────────────────────────────────

def paragraphs_to_docx(paragraphs: list, keep_empty: bool = False) -> bytes:
    """Абзацы → .docx. `keep_empty` — пустой абзац на пустой слот: номер
    абзаца и есть якорь, выброшенный пустой слот сдвинул бы все номера."""
    doc = _document()
    n = 0
    for p in paragraphs:
        p = _clean(p or "").strip()
        if not p and not keep_empty:
            continue
        doc.add_paragraph(p)
        n += bool(p)
    if not n:
        raise textcount.Unsupported("Из файла не извлеклось ни одного куска текста")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def join_pdf_lines(lines: list) -> list:
    """Визуальные строки PDF → абзацы (см. `pdftext.join_lines`): конец
    абзаца — конец предложения, пустая строка, заголовок или потолок длины;
    перенос слова снимается — мягкий всегда, дефисный при строчной дальше."""
    return pdftext.join_lines(lines)


def mixed_to_docx(items: list, page_images: dict, figures: "dict | None" = None) -> tuple:
    """[("p", текст[, рамки]) | ("img", страница, строки-запасной вариант) |
    ("fig", страница, рамка)] → (.docx, {images, figures, layout}). Страница,
    у которой картинку из PDF достать не удалось, кладётся своими строками:
    потерять её молча нельзя. Рисунок, который не вырезался, пропускается —
    текст вокруг него от этого не страдает.

    `layout` — {номер абзаца в .docx: рамки на страницах}: по нему выгрузка
    «как в оригинале» возвращает перевод на то место, где стоял оригинал.
    Номер абзаца — тот же якорь, которым связаны сегменты."""
    from docx.shared import Inches  # type: ignore
    from PIL import Image  # type: ignore
    doc = _document()
    figures = figures or {}
    layout: dict = {}
    n_text = n_img = n_fig = 0
    n_para = 0                     # сколько абзацев уже в документе
    for it in items:
        if it[0] == "p":
            t = _clean(it[1] or "").strip()
            if t:
                doc.add_paragraph(t)
                if len(it) > 2 and it[2]:
                    layout[n_para] = it[2]
                n_para += 1
                n_text += 1
            continue
        if it[0] == "fig":
            data = figures.get((it[1], tuple(it[2])))
            if not data:
                continue
            try:
                # Своей шириной, а не во всю полосу: рисунок в книге бывает
                # с ладонь, и растянутый на страницу он врал бы о вёрстке.
                im = Image.open(io.BytesIO(data))
                im.load()
                w_in = min(_PIC_WIDTH_IN, max(1.2, im.size[0] / float(textcount.FIG_RENDER_DPI)))
            except Exception:
                continue
            try:
                # Абзац считается, даже если картинка НЕ вставилась: python-docx
                # заводит абзац первым делом и при отказе оставляет его в
                # документе. Не посчитать его — сдвинуть номера всех следующих,
                # то есть посадить переводы выгрузки 1в1 на чужие абзацы.
                doc.add_picture(io.BytesIO(data), width=Inches(w_in))
                n_fig += 1
            except Exception:
                pass
            n_para += 1
            continue
        idx = it[1]
        data = page_images.get(idx)
        placed = False
        if data:
            pic = None
            try:
                im = Image.open(io.BytesIO(data))
                im.load()
                im = _exif_upright(im)
                if im.mode not in ("RGB", "L", "1", "P", "RGBA"):
                    im = im.convert("RGB")
                pic = _png_with_index(im, idx)
            except Exception:
                pic = None
            if pic is not None:
                try:
                    doc.add_picture(io.BytesIO(pic), width=Inches(_PIC_WIDTH_IN))
                    n_img += 1
                    placed = True
                except Exception:
                    placed = False
                # Абзац остаётся в документе при любом исходе вставки —
                # см. выше: несосчитанный сдвинул бы номера всех следующих.
                n_para += 1
        if not placed:
            for line in (it[2] if len(it) > 2 else []) or []:
                t = _clean(line or "").strip()
                if t:
                    doc.add_paragraph(t)
                    n_para += 1
                    n_text += 1
    if not n_text and not n_img:
        raise textcount.Unsupported("Из файла не извлеклось ни одного куска текста")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), {"images": n_img, "figures": n_fig, "layout": layout}


def pdf_to_docx(content: bytes) -> tuple:
    """(.docx, kind, note, страниц-картинок). Текстовый слой → абзацы через
    чистку `pdftext` (переносы, колонтитулы, номера, мусор, буквицы);
    страница с ненадёжным слоем — картинкой под чтение зрячей моделью;
    скан целиком → картинки страниц."""
    notes: list = []
    try:
        pages, geoms = textcount._pdf_pages_geom(content, notes)
    except textcount.Scan as s:
        pages_n = getattr(s, "pages", 0) or 0
        textcount.progress("pictures")
        idx = list(range(pages_n))
        imgs = [data for _i, data in textcount.pdf_page_pictures(content, idx) if data]
        if not imgs:
            raise textcount.Unsupported("PDF-скан без извлекаемых картинок страниц — "
                                        "распечатайте его в PNG/JPG постранично")
        return (scan_pages_to_docx(imgs), "scan",
                "PDF без текстового слоя: %d страниц положены картинками; текст с них "
                "читается автоматически. Обратно выгружается PDF из страниц с переведёнными "
                "надписями." % len(imgs), len(imgs), None)
    textcount.progress("clean")
    res = pdftext.clean(pages, geom=geoms)
    textcount.progress("build")
    page_images: dict = {}
    if res["imagePages"]:
        try:
            # Отрисованная страница, а без рендера — только вложенная картинка
            # размером со страницу: у цифрового PDF крупнейшая картинка —
            # логотип, и текст страницы за ним потерялся бы.
            for i, data in textcount.pdf_page_pictures(content, res["imagePages"], full_page=True):
                if data:
                    page_images[i] = data
        except Exception:
            page_images = {}
    # Рисунки внутри страниц: вырезаются из отрисованных страниц ОДНИМ
    # заходом — страница рисуется один раз на все свои рисунки.
    figures: dict = {}
    fig_stats: dict = {"blank": 0}
    fig_boxes = [(it[1], tuple(it[2])) for it in res["items"] if it[0] == "fig"]
    if fig_boxes:
        textcount.progress("figures")
        try:
            figures, fig_stats = textcount.pdf_crop_figures(content, fig_boxes)
        except Exception:
            figures, fig_stats = {}, {"blank": 0}
    docx_bytes, built = mixed_to_docx(res["items"], page_images, figures)
    n_img, n_fig = built["images"], built["figures"]
    # Лоскут края страницы рисунком не считается (`_has_ink`) — и это
    # не потеря: считаем их отдельно от тех, что не вырезались.
    n_fig_lost = len(fig_boxes) - n_fig - int(fig_stats.get("blank") or 0)
    n_text_fallback = len(res["imagePages"]) - n_img
    r = res["report"]
    removed = []
    if r.get("softHyphens") or r.get("hyphensJoined"):
        removed.append("переносов слов %d" % (r.get("softHyphens", 0) + r.get("hyphensJoined", 0)))
    if r.get("runningHeads"):
        removed.append("колонтитулов %d" % r["runningHeads"])
    if r.get("pageNumbers"):
        removed.append("номеров страниц %d" % r["pageNumbers"])
    junk = r.get("ornaments", 0) + r.get("junkLines", 0) + r.get("borderLines", 0)
    if junk:
        removed.append("строк мусора распознавания %d" % junk)
    if r.get("dropCaps"):
        removed.append("восстановлено буквиц %d" % r["dropCaps"])
    if r.get("scripts"):
        # Дробь, степень, индекс: распознаватель отдаёт их отдельной «строкой»,
        # и без склейки числитель уезжал в начало абзаца.
        removed.append("собрано дробей и индексов %d" % r["scripts"])
    note = ("PDF: текст взят из текстового слоя, строки склеены в абзацы"
            + ("; снято: " + ", ".join(removed) if removed else "") + ".")
    if r.get("headParagraphs"):
        # Колонтитул снят СО СТРАНИЦЫ, но не выброшен: он стоит отдельным
        # абзацем в конце — одним на всю книгу, — и выгрузка «как в оригинале»
        # печатает его перевод на каждой странице, где он был.
        note += (" Колонтитулы (%d) вынесены отдельными абзацами: переводятся "
                 "один раз и встают на каждую свою страницу." % r["headParagraphs"])
    if n_fig:
        note += " Рисунков перенесено в документ: %d." % n_fig
    if n_fig_lost > 0:
        # Молчать нельзя: рисунок, не попавший в документ, из выгрузки
        # пропадёт, а подпись под ним останется.
        note += " Рисунков не удалось вырезать: %d." % n_fig_lost
    if n_img:
        note += (" Страниц с ненадёжным текстовым слоем положено картинками: %d — "
                 "текст с них читается автоматически." % n_img)
    if n_text_fallback > 0:
        note += (" Страниц с ненадёжным слоем без картинки страницы оставлено текстом "
                 "как есть: %d." % n_text_fallback)
    note += (" Надписи внутри картинок не разобраны. Обратно выгружается PDF, "
             "собранный из документа Word.")
    return (docx_bytes, "pdf", note, n_img,
            {"boxes": built["layout"], "pages": res.get("pageBoxes") or []})


def to_docx(filename: str, content: bytes) -> dict:
    """{docx, kind, note, converted, writeback, slotsSha}.

    .docx отдаётся как есть; остальное превращается. Ошибки формата —
    `textcount.Unsupported` / `TooBig` / `NotAvailable`: вызывающий
    переводит их в 415 / 413 / 503 с текстом причины."""
    if not content:
        raise textcount.Unsupported("Файл пустой")
    if len(content) > textcount.MAX_BYTES:
        raise textcount.TooBig("Файл больше %d МБ — разберите его по частям"
                               % (textcount.MAX_BYTES // 1024 // 1024))
    kind = kind_of(filename)
    ext = ext_of(filename)
    if kind == "docx":
        return {"docx": content, "kind": "docx", "note": None, "converted": False,
                "writeback": True, "slotsSha": None}
    if kind == "image":
        return {"docx": images_to_docx([(content, ext)]), "kind": "image", "converted": True,
                "writeback": True, "slotsSha": None,
                "note": "Картинка положена в документ; текст с неё читается автоматически. "
                        "Обратно выгружается такая же картинка с переведёнными надписями."}
    if kind == "pdf":
        docx_bytes, k, note, n_img, layout = pdf_to_docx(content)
        return {"docx": docx_bytes, "kind": k, "note": note, "converted": True,
                "writeback": True, "slotsSha": None, "layout": layout,
                # Страницы, легшие картинками из-за ненадёжного слоя: по ним
                # `_auto_read_images` ставит чтение и у PDF с текстом.
                "imagePages": n_img if k == "pdf" else 0}
    if kind == "text":
        got = extract_slots(filename, content)
        docx_bytes = paragraphs_to_docx(got["slots"], keep_empty=got["writeback"])
        return {"docx": docx_bytes, "kind": got["kind"], "note": got["note"], "converted": True,
                "writeback": got["writeback"],
                "slotsSha": slots_sha(got["slots"]) if got["writeback"] else None}
    raise textcount.Unsupported("Формат %s не поддерживается. Поддерживаются: %s"
                                % (ext or "без расширения", ", ".join(SUPPORTED_EXT)))
