# -*- coding: utf-8 -*-
"""Выгрузка PDF «как в оригинале»: перевод встаёт НА МЕСТО оригинала.

ЗАЧЕМ ОТДЕЛЬНАЯ ДОРОГА. У .docx выгрузка 1в1 подменяет текст в САМОМ файле
клиента, и всё, чего мы не тронули, остаётся байт в байт. У PDF так нельзя:
при импорте мы берём из него только текстовый слой и собираем НОВЫЙ документ
Word, а печать этого документа даёт ровный поток абзацев — ни колонок,
ни рисунков на местах, ни полей, ни кегля. Для книги, снятой со сканера
(каждая страница — фотография), это значит «вёрстки нет вовсе».

ЧТО ДЕЛАЕМ. Берём ИСХОДНЫЙ PDF как он есть и поверх каждой страницы кладём
один слой: закрашиваем прямоугольник, где стоял абзац оригинала, цветом
его же бумаги и печатаем туда перевод. Всё остальное — рисунки, схемы,
колонтитулы, фон страницы — остаётся нетронутым, потому что мы его
не пересобираем.

ТРИ ПРАВИЛА, КОТОРЫЕ НЕЛЬЗЯ ОСЛАБЛЯТЬ.

1. **Текст не режется.** Перевод на узбекский длиннее русского оригинала
   примерно на пятую часть, и в рамку он не влезает. Уменьшаем кегль, пока
   не влезет (`FIT_STEP`, не ниже `MIN_SIZE_SHARE` от исходного). Не влез
   и на полу — печатаем как есть, с выходом за рамку, и считаем такие абзацы
   (`overflow`): обрезанный перевод — это потерянный текст клиента, а рамка
   всего лишь оформление.

2. **Непереведённое НЕ закрашивается.** Абзац без перевода остаётся
   оригиналом на своём месте — так же, как в выгрузке .docx. Закрасить его
   значило бы стереть текст книги.

3. **Цвет бумаги берётся С САМОГО МЕСТА.** Белый прямоугольник на жёлтой
   бумаге скана — заплатка, и ровно так же видна заплатка «чистого» тона
   из поля страницы: бумага темнеет к корешку, а сквозь лист просвечивает
   оборот. Поэтому тон меряется ПОД рамкой, полосами и по высокому
   процентилю яркости (`_strip_colors`). Нечем мерить (нет рендера) —
   белый, и это считается числом (`nocolor`), а не замалчивается.

ЧЕГО ЭТА ДОРОГА НЕ УМЕЕТ, и это названо, а не умолчано:
  • колонтитулы и номера страниц остаются на языке оригинала (при импорте
    они снимаются и сегментами не становятся — переводить нечего);
  • страница с повёрнутым `/Rotate` не трогается вовсе;
  • текст внутри рисунков живёт своей дорогой (разбор картинок);
  • **прежний текст остаётся ПОД закраской**: мы кладём слой поверх
    страницы, а не переписываем её содержимое. На глаз его нет, но
    «скопировать текст» из готового файла отдаст и его тоже. У книги,
    снятой со сканера, это невидимый слой распознавателя — там это
    безразлично; у цифрового PDF копия будет смешанной. Вынимать чужие
    операторы из содержимого страницы значит переписывать файл клиента
    ради того, чего не видно, — цена выше пользы.
"""

import io
import os
import statistics
from pathlib import Path

# Шрифт перевода. Своего у нас нет и быть не должно: нужен тот, в котором
# есть письменность целевого языка (узбекская кириллица, казахская, любая
# другая). Берём первый найденный из списка — на сервере это DejaVu,
# он лежит рядом с LibreOffice.
FONT_CANDIDATES = {
    "": [os.environ.get("LAYOUT_FONT", ""),
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
         "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/arial.ttf"],
    "b": [os.environ.get("LAYOUT_FONT_BOLD", ""),
          "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
          "C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "i": [os.environ.get("LAYOUT_FONT_ITALIC", ""),
          "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
          "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
          "C:/Windows/Fonts/timesi.ttf", "C:/Windows/Fonts/ariali.ttf"],
    "bi": [os.environ.get("LAYOUT_FONT_BOLDITALIC", ""),
           "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
           "C:/Windows/Fonts/timesbi.ttf", "C:/Windows/Fonts/arialbi.ttf"],
}
FONT_NAME = "LayoutBody"

# Насколько уменьшать кегль за шаг и докуда. Ниже — нечитаемо, и честный
# выход за рамку лучше, чем «влезло, но не читается».
FIT_STEP = 0.97
MIN_SIZE_SHARE = float(os.environ.get("LAYOUT_MIN_SIZE_SHARE", "0.55"))
MIN_SIZE_PT = 5.0
# Разрешение, на котором меряется цвет бумаги: нам нужен не рисунок,
# а средний цвет кольца вокруг рамки.
SAMPLE_DPI = int(os.environ.get("LAYOUT_SAMPLE_DPI", "36"))
# Запас закраски вокруг рамки, в долях кегля: засечки и выносные элементы
# выходят за базовые линии, а рамка считалась по ним.
PAD_SHARE = 0.18
# На сколько полос режется закраска поперёк страницы.
FILL_STRIPS = 10
# Сколько разных знаков перевода шрифт вправе не знать. Ноль был бы слишком
# строг: в тексте попадается редкий символ, который нарисуется квадратом,
# и ронять из-за него всю выгрузку незачем.
GLYPH_MISS_MAX = int(os.environ.get("LAYOUT_GLYPH_MISS_MAX", "3"))
# Какой процентиль яркости полосы считать бумагой (буквы — тёмный хвост).
PAPER_Q = 0.75


class NotAvailable(Exception):
    """Нечем собрать: нет библиотеки или шрифта. Не ошибка данных —
    отсутствие возможности, и отвечать на неё надо словами."""


def font_path(style: str = "") -> str:
    """Файл шрифта под начертание. Нет своего файла — берём обычный:
    напечатать светлым вместо курсива честнее, чем не напечатать вовсе
    (на боевом сервере из DejaVu Serif есть обычный и полужирный)."""
    for p in FONT_CANDIDATES.get(style or "", []):
        if p and Path(p).exists():
            return p
    return "" if not style else font_path("b" if style == "bi" else "")


def available() -> tuple:
    """(можно ли, почему нет). Спрашивается ДО нажатия: предлагать формат,
    которого на этом сервере нет, — врать."""
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False, "не установлен reportlab"
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False, "не установлен pypdf"
    if not font_path(""):
        return False, "не найден шрифт с нужной письменностью"
    return True, ""


def _register_fonts() -> dict:
    """{начертание: имя шрифта}. Одно и то же имя у двух начертаний
    законно: файла может не быть, и тогда начертание просто совпадает."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    out = {}
    for style in ("", "b", "i", "bi"):
        path = font_path(style)
        if not path:
            continue
        name = FONT_NAME + (style or "R")
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, path))
        out[style] = name
    return out


def _wrap(text: str, width: float, size: float, indent: float, sw, font: str) -> list:
    """Строки абзаца по ширине рамки. Первая — с отступом оригинала.
    Слово длиннее строки не режется: переносов по слогам мы не умеем,
    а выдуманный перенос хуже вылезшего слова."""
    lines, cur = [], ""
    for w in (text or "").split():
        avail = width - (indent if not lines else 0.0)
        probe = (cur + " " + w) if cur else w
        if cur and sw(probe, font, size) > avail:
            lines.append(cur)
            cur = w
        else:
            cur = probe
    if cur:
        lines.append(cur)
    return lines


def _fit(text: str, boxes: list, sw, font: str) -> tuple:
    """(кегль, межстрочный, [строки] на каждую рамку, влез ли).

    Абзац бывает разорван концом страницы — рамок несколько, и кегль у них
    ОДИН: разный кегль на двух половинах одного абзаца читается как брак."""
    base = max((b["size"] for b in boxes), default=10.0) or 10.0
    lead0 = max((b["lead"] for b in boxes), default=base * 1.2) or base * 1.2
    floor = max(MIN_SIZE_PT, base * MIN_SIZE_SHARE)
    size = base
    while True:
        lead = lead0 * (size / base)
        rest, per_box, fits = text, [], True
        for k, b in enumerate(boxes):
            width = max(1.0, b["x1"] - b["x0"])
            cap = max(1, int((b["top"] - b["bottom"] + 0.35 * size) / lead))
            lines = _wrap(rest, width, size, b["indent"] if k == 0 else 0.0, sw, font)
            if k == len(boxes) - 1:
                per_box.append(lines)
                fits = len(lines) <= cap
                rest = ""
            else:
                per_box.append(lines[:cap])
                # Что не влезло в эту рамку — в следующую, целыми словами:
                # строку резать нельзя, её ширина уже посчитана.
                rest = " ".join(lines[cap:])
        if fits or size <= floor:
            return size, lead, per_box, fits
        size *= FIT_STEP


def _page_samples(pdf_bytes: bytes, pages: list) -> dict:
    """{страница: (картинка, масштаб)} в низком разрешении — только чтобы
    померить цвет бумаги. Нет рендера — пустой ответ: закраска будет белой,
    и это считается числом, а не замалчивается."""
    try:
        import pypdfium2 as pdfium
        from PIL import Image  # noqa: F401
    except ImportError:
        return {}
    try:
        doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    except Exception:
        return {}
    out, scale = {}, SAMPLE_DPI / 72.0
    for i in pages:
        try:
            page = doc[i]
            # Начало отсчёта у отрисованной страницы — её CropBox, а рамки
            # абзацев лежат в координатах самого PDF (MediaBox). У печатной
            # вёрстки с вылетами это разные прямоугольники, и цвет бумаги
            # мерился бы не под тем абзацем.
            try:
                cb = [float(v) for v in page.get_cropbox()]
            except Exception:
                cb = [0.0, 0.0, 0.0, 0.0]
            out[i] = (page.render(scale=scale).to_pil().convert("RGB"), scale, cb)
            page.close()
        except Exception:
            continue
    return out


def _strip_colors(sample, box: dict, pad: float, n: int) -> list:
    """Цвет бумаги полосами поперёк рамки — по САМОЙ странице под ней.

    Меряем не вокруг рамки, а внутри: у книги, снятой со сканера, бумага
    темнеет к корешку, сквозь лист просвечивает оборот, и чистый тон из поля
    ложится на это место светлой заплаткой. Берём высокий процентиль яркости
    полосы: буквы занимают меньшую часть её площади, поэтому процентиль
    и есть бумага — с её здешним тоном и просветом оборота. Медиана взяла бы
    середину между бумагой и буквами, то есть серое.
    """
    if not sample:
        return [(1.0, 1.0, 1.0)] * n
    im, scale, cb = sample
    W, H = im.size
    x0, x1 = (box["x0"] - pad - cb[0]) * scale, (box["x1"] + pad - cb[0]) * scale
    y0 = H - (box["top"] + pad - cb[1]) * scale
    y1 = H - (box["bottom"] - pad - cb[1]) * scale
    step = max(1.0, (x1 - x0) / n)
    out = []
    for k in range(n):
        px0, px1 = int(x0 + k * step), int(x0 + (k + 1) * step) + 1
        box_px = (max(0, px0), max(0, int(y0)), min(W, max(px0 + 1, px1)), min(H, max(int(y0) + 1, int(y1))))
        try:
            crop = im.crop(box_px)
            data = list(crop.getdata())
        except Exception:
            data = []
        if not data:
            out.append(out[-1] if out else (1.0, 1.0, 1.0))
            continue
        col = []
        for ch in range(3):
            vals = sorted(p[ch] for p in data)
            col.append(vals[min(len(vals) - 1, int(PAPER_Q * len(vals)))] / 255.0)
        out.append(tuple(col))
    return out


def _fill_box(c, box: dict, pad: float, colors: list):
    """Закраска рамки полосами. Полосы кладутся с нахлёстом внутрь, но
    НЕ ЗА правый край: вылезший кусок виден на поле прямоугольником."""
    x0, y0 = box["x0"] - pad, box["bottom"] - pad
    w, h = (box["x1"] - box["x0"]) + 2 * pad, (box["top"] - box["bottom"]) + 2 * pad
    n = max(1, len(colors))
    step = w / float(n)
    for k, col in enumerate(colors):
        left = x0 + k * step
        right = min(x0 + w, left + step * 1.6)
        c.setFillColorRGB(*col)
        c.rect(left, y0, right - left, h, stroke=0, fill=1)


def _missing_glyphs(fonts: dict, texts: dict) -> int:
    """Сколько РАЗНЫХ знаков перевода шрифт не знает.

    Файл шрифта на диске есть — это ещё не значит, что в нём есть
    письменность целевого языка: у DejaVu нет ни арабского, ни китайского,
    и страница вышла бы из пустых квадратов. Спрашиваем сам шрифт."""
    try:
        from reportlab.pdfbase import pdfmetrics
        face = pdfmetrics.getFont(fonts.get("") or FONT_NAME).face
    except Exception:
        return 0                 # спросить не у кого — не выдумываем отказ
    chars = set()
    for t in texts.values():
        chars.update(t or "")
        if len(chars) > 2000:
            break
    miss = 0
    for ch in chars:
        if ch.isspace():
            continue
        try:
            if not face.charToGlyph.get(ord(ch)):
                miss += 1
        except Exception:
            return 0
    return miss


def build(pdf_bytes: bytes, layout: dict, texts: dict) -> tuple:
    """(PDF, отчёт). `layout` — {"boxes": {номер абзаца: [рамки]}},
    `texts` — {номер абзаца: перевод}. Абзац без перевода не трогается."""
    ok, why = available()
    if not ok:
        raise NotAvailable(why)
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from pypdf import PdfReader, PdfWriter
    fonts = _register_fonts()
    sw = pdfmetrics.stringWidth
    miss = _missing_glyphs(fonts, texts)
    if miss > GLYPH_MISS_MAX:
        raise NotAvailable("шрифт %s не знает %d знаков перевода — письменность "
                           "целевого языка в нём отсутствует; задайте LAYOUT_FONT"
                           % (os.path.basename(font_path("")), miss))

    reader = PdfReader(io.BytesIO(pdf_bytes))
    stats = {"pages": len(reader.pages), "paragraphs": 0, "shrunk": 0,
             "overflow": 0, "nocolor": 0, "rotated": 0, "bold": 0, "italic": 0,
             "glyphMiss": miss}

    # Повёрнутая страница: наш слой лёг бы боком. Оставляем её оригиналом —
    # это честнее испорченной. Решается ДО раскладки: абзац, чья вторая
    # половина попала на такую страницу, не должен считаться сделанным.
    skip = set()
    for i, page in enumerate(reader.pages):
        try:
            if int(page.get("/Rotate") or 0) % 360:
                skip.add(i)
        except Exception:
            pass

    # Раскладка считается ПО АБЗАЦУ, один раз, а не на каждой его странице:
    # абзац бывает разорван концом страницы, и счёт «на страницу» удваивал
    # и работу в отчёте, и честное число не влезших.
    plan: list = []
    pages_used: set = set()
    for key, boxes in (layout.get("boxes") or {}).items():
        idx = int(key)
        text = (texts.get(idx) or "").strip()
        if not text or not boxes:
            continue
        if any(int(b["page"]) in skip for b in boxes):
            stats["rotated"] += 1
            continue
        style = boxes[0].get("style") or ""
        font = fonts.get(style) or fonts[""]
        size, lead, per_box, fits = _fit(text, boxes, sw, font)
        stats["paragraphs"] += 1
        stats["bold"] += 1 if "b" in style else 0
        stats["italic"] += 1 if "i" in style else 0
        if size < max(b["size"] for b in boxes) - 0.01:
            stats["shrunk"] += 1
        if not fits:
            stats["overflow"] += 1
        plan.append((idx, boxes, per_box, size, lead, font))
        pages_used.update(int(b["page"]) for b in boxes)

    samples = _page_samples(pdf_bytes, sorted(pages_used))
    # Не измерена бумага ровно там, где её не отрисовали: закраска будет белой,
    # и число сказано. Считать «всё или ничего» нельзя — часть страниц может
    # не отрисоваться, и отчёт тогда врал бы про остальные.
    stats["nocolor"] = len([i for i in pages_used if i not in samples])

    # Слой на ВСЕ страницы — одним документом, а не по одному на страницу:
    # reportlab встраивает шрифт в каждый собранный файл, и на книге это
    # 378 копий шрифта, то есть десятки мегабайт из ничего.
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    order: list = []
    drawn = 0
    for i, page in enumerate(reader.pages):
        if i not in pages_used:
            order.append(None)
            continue
        mb = page.mediabox
        c.setPageSize((float(mb.width), float(mb.height)))
        for _idx, boxes, per_box, size, lead, font in plan:
            for n, (b, lines) in enumerate(zip(boxes, per_box)):
                if int(b["page"]) != i:
                    continue
                # Закраска идёт и у ПУСТОЙ рамки: перевод мог целиком влезть
                # в первую половину абзаца, а во второй остался бы оригинал —
                # рядом с готовым переводом того же абзаца.
                pad = PAD_SHARE * max(b["size"], 1.0)
                _fill_box(c, b, pad, _strip_colors(samples.get(i), b, pad, FILL_STRIPS))
                if not lines:
                    continue
                c.setFillColorRGB(0, 0, 0)
                c.setFont(font, size)
                y = b["top"] - 0.85 * size
                for k, line in enumerate(lines):
                    c.drawString(b["x0"] + (b["indent"] if (k == 0 and n == 0) else 0.0), y, line)
                    y -= lead
        order.append(drawn)
        drawn += 1
        c.showPage()
    c.save()
    buf.seek(0)
    overlay = PdfReader(buf)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if order[i] is not None:
            try:
                page.merge_page(overlay.pages[order[i]])
            except Exception as e:
                raise NotAvailable("слой не лёг на страницу %d: %s" % (i + 1, e))
        writer.add_page(page)
    # Слой поверх страницы пишется несжатым потоком, и на книге это лишние
    # десятки мегабайт: жмём то, что собрали сами.
    try:
        for page in writer.pages:
            page.compress_content_streams()
    except Exception:
        pass
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), stats
