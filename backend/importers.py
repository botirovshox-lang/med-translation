# -*- coding: utf-8 -*-
"""Импорт файла любого поддержанного формата — ЧЕРЕЗ .docx.

Зачем именно так. Весь конвейер проекта стоит на .docx: разбор абзацев
(`_docx_paragraph_texts`), якоря «абзац → сегмент», хранение исходника,
экспорт «как в оригинале», разбор надписей на картинках (`image_text`).
Второй конвейер под Excel, HTML и картинки означал бы второй набор якорей,
второй экспорт и второй разбор картинок — и все они однажды разошлись бы
с первым. Поэтому чужой формат сначала ПРЕВРАЩАЕТСЯ в .docx, а дальше идёт
штатной дорогой:

  * текстовые форматы (txt, md, html, csv, xlsx, pptx, odt …) — куски текста
    берёт `textcount.extract` — ТОТ ЖЕ разбор, что у сметы, поэтому смета
    и число строк проекта считаются по одним кускам; каждый кусок — абзац;
  * PDF с текстовым слоем — строки страниц склеиваются в абзацы (pypdf
    отдаёт визуальные строки; сегмент-обрывок без контекста переводится
    хуже); PDF-скан — картинка каждой страницы;
  * картинки (png, jpg, webp, …) — по картинке на абзац; текст с них читает
    штатный разбор надписей (платно, по кнопке), а не импорт.

Что теряется, названо честно (`note` в ответе): у Excel и PowerPoint
раскладка листа/слайда в .docx не переносится — обратно они выгружаются
Word-документом или таблицей Excel из сегментов, а не файлом 1в1.
Оригинал при этом хранится рядом (`data/sources/{pid}.orig.<ext>`):
когда появится выгрузка 1в1 для этих форматов, ей будет во что писать.

Ни одного вызова модели. Потолки размера — те же, что у сметы (`textcount`).
"""
import io
import os
import re
from typing import Optional

try:
    import textcount
except ImportError:                                   # pragma: no cover
    from . import textcount                            # type: ignore

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
# Что принимаем. Смета умеет то же плюс .pdf; картинки — только здесь.
SUPPORTED_EXT = sorted(set(textcount.SUPPORTED_EXT) | IMAGE_EXT)
# Строки PDF склеиваются в абзац, пока не встретится конец предложения,
# пустая строка или потолок длины: без потолка титульный лист с сотней
# коротких строк без точек стал бы одним абзацем на страницу.
PDF_PARA_MAX = 1200
_PDF_END_RE = re.compile(r"[.!?…:;»”\")\]]\s*$")
# Максимальная ширина картинки в .docx — ширина листа A4 с полями.
_PIC_WIDTH_IN = 6.3


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


def _document():
    from docx import Document  # type: ignore
    return Document()


def _exif_upright(im):
    """Фото со смартфона лежит боком: ориентация записана в EXIF, а Word
    (и разбор надписей) читают пиксели как есть. Поворачиваем по EXIF."""
    try:
        from PIL import ImageOps  # type: ignore
        return ImageOps.exif_transpose(im) or im
    except Exception:
        return im


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
    картинками PNG; у прочих форматов — одна, как есть."""
    if ext not in (".tif", ".tiff"):
        return [(data, ext)]
    try:
        from PIL import Image, ImageSequence  # type: ignore
        im = Image.open(io.BytesIO(data))
        out = []
        for frame in ImageSequence.Iterator(im):
            buf = io.BytesIO()
            _exif_upright(frame.convert("RGB")).save(buf, format="PNG")
            out.append((buf.getvalue(), ".png"))
        return out or [(data, ext)]
    except Exception:
        return [(data, ext)]


def images_to_docx(images: list) -> bytes:
    """[(bytes, ext)] → .docx, по картинке на абзац."""
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


_HTML_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
               "table", "section", "article", "header", "footer", "blockquote", "pre", "dd", "dt",
               "figcaption", "caption", "title", "hr", "form", "fieldset", "legend", "nav", "aside",
               "main", "address", "summary", "details"}
_HTML_SKIP = {"script", "style", "noscript", "template", "svg"}


def html_paragraphs(text: str) -> list:
    """HTML → абзацы по БЛОЧНЫМ тегам. Смета режет по любому тегу (ей всё
    равно, где граница слова), а сегменту это не годится: «Абзац <b>жирный</b>
    текст» разваливался бы на три строки без смысла. Ячейки строки таблицы
    идут в один абзац через « | »."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out, self.buf, self.skip, self.cell = [], [], 0, 0

        def flush(self):
            s = " ".join("".join(self.buf).split())
            if s:
                self.out.append(s)
            self.buf = []

        def handle_starttag(self, tag, attrs):
            if tag in _HTML_SKIP:
                self.skip += 1
            elif tag == "br":
                # <br> — разрыв строки ВНУТРИ абзаца (в .docx это w:br), а не
                # новый абзац: адрес в две строки остаётся одним сегментом.
                self.buf.append(" ")
            elif tag in ("td", "th"):
                self.cell += 1
                if "".join(self.buf).strip():
                    self.buf.append(" | ")
            elif tag in ("tr", "table"):
                self.cell = 0
                self.flush()
            elif tag in _HTML_BLOCK and not self.cell:
                # Блочный тег внутри ячейки строку таблицы не рвёт: строка — один абзац.
                self.flush()

        def handle_endtag(self, tag):
            if tag in _HTML_SKIP:
                self.skip = max(0, self.skip - 1)
            elif tag == "br":
                pass
            elif tag in ("td", "th"):
                self.cell = max(0, self.cell - 1)
            elif tag in ("tr", "table"):
                self.cell = 0
                self.flush()
            elif tag in _HTML_BLOCK and not self.cell:
                self.flush()

        def handle_data(self, data):
            if not self.skip:
                self.buf.append(data)

    p = P()
    p.feed(text or "")
    p.close()
    p.flush()
    return p.out


def paragraphs_to_docx(paragraphs: list) -> bytes:
    doc = _document()
    n = 0
    for p in paragraphs:
        p = (p or "").strip()
        if not p:
            continue
        doc.add_paragraph(p)
        n += 1
    if not n:
        raise textcount.Unsupported("Из файла не извлеклось ни одного куска текста")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def join_pdf_lines(lines: list) -> list:
    """Визуальные строки PDF → абзацы. Конец абзаца — конец предложения,
    пустая строка или потолок длины. Перенос слова по дефису в конце
    строки снимается («тубер-» + «кулёз» → «туберкулёз»)."""
    out, buf = [], ""
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            continue
        if buf.endswith("-") and line[:1].islower():
            buf = buf[:-1] + line
        else:
            buf = (buf + " " + line) if buf else line
        if _PDF_END_RE.search(buf) or len(buf) >= PDF_PARA_MAX:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def pdf_to_docx(content: bytes) -> tuple:
    """(.docx, kind, note). Текстовый слой → абзацы; скан → картинки страниц."""
    notes: list = []
    try:
        lines = textcount._pdf_blocks(content, notes)
    except textcount.Scan as s:
        pages = getattr(s, "pages", 0) or 0
        idx = list(range(pages))
        imgs = [(data, ".png") for _i, data in textcount.pdf_page_images(content, idx) if data]
        if not imgs:
            raise textcount.Unsupported("PDF-скан без извлекаемых картинок страниц — "
                                        "распечатайте его в PNG/JPG постранично")
        return (images_to_docx(imgs), "scan",
                "PDF без текстового слоя: %d страниц положены картинками; текст с них "
                "читает разбор надписей (платно, по кнопке)." % len(imgs))
    paras = join_pdf_lines(lines)
    return (paragraphs_to_docx(paras), "pdf",
            "PDF: текст взят из текстового слоя, строки склеены в абзацы; "
            "надписи внутри картинок не разобраны. Обратно выгружается Word-документом.")


def to_docx(filename: str, content: bytes) -> dict:
    """{docx: bytes, kind: str, note: str|None, converted: bool}.

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
        return {"docx": content, "kind": "docx", "note": None, "converted": False}
    if kind == "image":
        return {"docx": images_to_docx([(content, ext)]), "kind": "image", "converted": True,
                "note": "Картинка положена в документ; текст с неё читает разбор надписей "
                        "(платно, по кнопке). Обратно выгружается Word-документом с картинкой."}
    if kind == "pdf":
        docx_bytes, k, note = pdf_to_docx(content)
        return {"docx": docx_bytes, "kind": k, "note": note, "converted": True}
    if kind == "text":
        got = textcount.extract(filename, content)
        blocks = got["blocks"]
        if got["kind"] in ("html", "htm"):
            text, _enc = textcount._decode(content)
            blocks = html_paragraphs(text)
        if got["kind"] in ("csv", "tsv"):
            # Строка таблицы — один кусок: ячейки через табуляцию остаются
            # в одном сегменте, иначе колонки перемешаются в переводе.
            blocks = [b.replace("\t", " | ") if isinstance(b, str) else b for b in blocks]
        docx_bytes = paragraphs_to_docx(blocks)
        lost = {"xlsx": "раскладка листа", "pptx": "раскладка слайдов", "ods": "раскладка листа",
                "odp": "раскладка слайдов", "html": "разметка страницы", "htm": "разметка страницы"}
        note = ("Файл %s превращён в документ Word: %s не переносится, обратно выгружается "
                "Word-документом (Excel — ещё и таблицей из строк)." % (got["kind"], lost[got["kind"]])
                if got["kind"] in lost else
                "Текст разложен по абзацам; обратно выгружается Word-документом.")
        if got.get("notes"):
            note += " " + " ".join(got["notes"])
        return {"docx": docx_bytes, "kind": got["kind"], "note": note, "converted": True}
    raise textcount.Unsupported("Формат %s не поддерживается. Поддерживаются: %s"
                                % (ext or "без расширения", ", ".join(SUPPORTED_EXT)))
