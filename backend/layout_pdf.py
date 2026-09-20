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

ЧЕТВЁРТОЕ ПРАВИЛО: **закраска считается ПО КРАСКЕ, а не по рамке.**
Рамка абзаца считается по текстовому слою, а конец строки в нём —
ОЦЕНКА по средней ширине знака (см. `pdfpages_worker._geometry`): у книги
из распознавателя она врёт на несколько знаков, и справа от перевода
оставался хвост оригинала («Асалнинг энг оддий таҳлили *еда*»). Поэтому
перед закраской рамка раздвигается по самой странице: пока в её полосе
сразу за краем стоит краска, край едет дальше (`_ink_box`), и
останавливается на первом настоящем пробеле. Ошибиться в эту сторону
безопасно: закрашиваем бумагу цветом этой же бумаги.

ЧЕГО ЭТА ДОРОГА НЕ УМЕЕТ, и это названо, а не умолчано:
  • страница с повёрнутым `/Rotate` не трогается вовсе;
  • текст внутри рисунков, стоящих НА текстовой странице, живёт своей
    дорогой (разбор картинок): его рамки считаны в пикселях картинки,
    а не в точках страницы. Текст страниц-КАРТИНОК (обложка, скан) сюда
    приходит рамками (`extra`) и печатается наравне с абзацами;
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
# У надписи СО СТРАНИЦЫ-КАРТИНКИ пол ниже, и это не небрежность: её рамка
# обведена вокруг самих букв, запаса вокруг нет вовсе, а перевод длиннее
# оригинала — на обложке «Священник Александр Лазебный» уезжало за край
# страницы. Мелко, но целиком, лучше, чем крупно и мимо листа.
MIN_SIZE_SHARE_IMAGE = float(os.environ.get("LAYOUT_MIN_SIZE_SHARE_IMAGE", "0.3"))
MIN_SIZE_PT = 5.0
# Разрешение, на котором меряется бумага и краска. Страница рисуется ПО ОДНОЙ
# и тут же забывается (`_Sampler`), поэтому разрешение можно держать выше:
# прежние 36 точек на дюйм — это полпикселя на типографский пункт, и хвост
# оригинала в три знака (`еда`) на нём почти не виден. Все страницы разом
# держать в памяти нельзя: книга в 378 страниц — это сотни мегабайт.
SAMPLE_DPI = int(os.environ.get("LAYOUT_SAMPLE_DPI", "72"))
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
# У надписи НА КАРТИНКЕ «бумага» — сама фотография: высокий процентиль берёт
# её блик и кладёт белую заплатку посреди жёлтой обложки. Там фон — медиана.
PAPER_Q_IMAGE = float(os.environ.get("LAYOUT_PAPER_Q_IMAGE", "0.5"))
# Докуда раздвигать закраску по краске: доля ширины рамки и потолок в пунктах.
# Оба нужны: у короткого заголовка доля вырождается в ничто, а у абзаца
# во всю полосу — в пол-страницы.
INK_EXPAND_SHARE = float(os.environ.get("LAYOUT_INK_EXPAND", "0.6"))
INK_EXPAND_MAX = float(os.environ.get("LAYOUT_INK_EXPAND_MAX", "140"))
# Какой пробел считать настоящим (в долях кегля): пробел между словами уже
# него, межколонник — шире. Ошибка в меньшую сторону оставляет хвост
# оригинала, в большую — заезжает в соседнюю колонку.
INK_GAP_SHARE = float(os.environ.get("LAYOUT_INK_GAP", "0.9"))
# Насколько темнее бумаги считать краской.
INK_DARK = float(os.environ.get("LAYOUT_INK_DARK", "0.82"))
# Ниже этой яркости бумага считается тёмной, и перевод печатается светлым.
DARK_PAPER = float(os.environ.get("LAYOUT_DARK_PAPER", "0.45"))


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
    image = bool(boxes and boxes[0].get("image"))
    share = MIN_SIZE_SHARE_IMAGE if image else MIN_SIZE_SHARE
    floor = max(MIN_SIZE_PT, base * share)
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
                if image and fits:
                    # У надписи с картинки рамка обведена вокруг самих букв,
                    # и вылезшее слово ложится не на поле страницы, а на сам
                    # рисунок. Слово длиннее строки перенести нечем — значит
                    # ужимаем кегль, пока не влезет. У текстовой рамки это
                    # правило не нужно и вредно: там есть поля, а ужимать
                    # абзац из-за одного длинного слова значит менять вёрстку.
                    fits = all(sw(ln, font, size) <= width for ln in lines)
                rest = ""
            else:
                per_box.append(lines[:cap])
                # Что не влезло в эту рамку — в следующую, целыми словами:
                # строку резать нельзя, её ширина уже посчитана.
                rest = " ".join(lines[cap:])
        if fits or size <= floor:
            return size, lead, per_box, fits
        size *= FIT_STEP


def _unfrac(b: dict, mb) -> None:
    """Рамка, названная долями листа, — в точки страницы, на месте.

    Доли считаны по картинке страницы: x — слева направо, y — СВЕРХУ вниз,
    как у пикселей; в PDF ось y смотрит вверх, поэтому верх и низ меняются
    местами. Кегль и межстрочный — доли ВЫСОТЫ листа."""
    x, y = float(mb.left), float(mb.bottom)
    w, h = float(mb.width), float(mb.height)
    b["x0"], b["x1"] = x + b["x0"] * w, x + b["x1"] * w
    b["top"], b["bottom"] = y + (1.0 - b["top"]) * h, y + (1.0 - b["bottom"]) * h
    b["size"], b["lead"] = max(1.0, b["size"] * h), max(1.0, b["lead"] * h)
    b["frac"] = 0


class _Sampler:
    """Отрисованная страница — по ОДНОЙ за раз.

    Раньше все нужные страницы рисовались разом и лежали в памяти до конца
    сборки: на книге в 378 страниц это сотни мегабайт у единственного
    воркера, и ровно поэтому разрешение держали нищим. Страницы обходятся
    по порядку, значит помнить надо одну: снимок отдаётся по номеру,
    прошлый забывается. Нет рендера — снимков нет вовсе, закраска будет
    белой, и это считается числом (`nocolor`), а не замалчивается."""

    def __init__(self, pdf_bytes: bytes):
        self.doc = None
        self.scale = SAMPLE_DPI / 72.0
        self.cur: tuple = (None, None)
        self.missed: set = set()
        try:
            import pypdfium2 as pdfium
            from PIL import Image  # noqa: F401
            self.doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
        except Exception:
            self.doc = None

    def page(self, i: int):
        """(картинка, масштаб, CropBox) | None."""
        if self.cur[0] == i:
            return self.cur[1]
        if self.doc is None:
            self.missed.add(i)
            return None
        sample = None
        try:
            page = self.doc[i]
            # Начало отсчёта у отрисованной страницы — её CropBox, а рамки
            # абзацев лежат в координатах самого PDF (MediaBox). У печатной
            # вёрстки с вылетами это разные прямоугольники, и цвет бумаги
            # мерился бы не под тем абзацем.
            try:
                cb = [float(v) for v in page.get_cropbox()]
            except Exception:
                cb = [0.0, 0.0, 0.0, 0.0]
            im = page.render(scale=self.scale).to_pil().convert("RGB")
            sample = (im, self.scale, cb, im.convert("L"))
            page.close()
        except Exception:
            sample = None
        if sample is None:
            self.missed.add(i)
        self.cur = (i, sample)
        return sample


def _col_mins(gray, x0: int, x1: int, y0: int, y1: int) -> list:
    """Самый тёмный пиксель каждого столбца полосы. По столбцам, а не по
    средней яркости: тонкая буква на светлой бумаге даёт среднее «почти
    бумага», и хвост оригинала остался бы незакрашенным."""
    x0, x1 = max(0, int(x0)), min(gray.size[0], int(x1))
    y0, y1 = max(0, int(y0)), min(gray.size[1], int(y1))
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return []
    data = gray.crop((x0, y0, x1, y1)).tobytes()
    try:
        import numpy as np
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w).min(axis=0).tolist()
    except Exception:
        out = [255] * w
        for r in range(h):
            row = data[r * w:(r + 1) * w]
            for c in range(w):
                if row[c] < out[c]:
                    out[c] = row[c]
        return out


def _ink_box(sample, box: dict, pad: float, paper: float) -> tuple:
    """(x0, x1) закраски, раздвинутые по КРАСКЕ страницы.

    Конец строки в текстовом слое — оценка по средней ширине знака, и у книги
    из распознавателя она врёт: справа от перевода оставался хвост оригинала.
    Смотрим на саму страницу: идём от края рамки наружу, пока в её полосе
    стоит краска, и останавливаемся на первом настоящем пробеле
    (`INK_GAP_SHARE` кегля — шире межсловного и уже межколонника).
    Ошибиться в эту сторону безопасно: мы закрашиваем бумагу цветом
    этой же бумаги."""
    x0, x1 = box["x0"], box["x1"]
    if not sample:
        return x0, x1
    im, scale, cb, gray = sample
    W, H = im.size
    size = max(box.get("size") or 10.0, 1.0)
    ytop = H - (box["top"] + pad - cb[1]) * scale
    ybot = H - (box["bottom"] - pad - cb[1]) * scale
    y0, y1 = int(min(ytop, ybot)), int(max(ytop, ybot)) + 1
    if y1 - y0 < 2:
        return x0, x1
    dark = INK_DARK * paper * 255.0
    # Потолок раздвижки: доля ширины рамки, но не меньше нескольких кеглей —
    # у короткого заголовка доля вырождается в ничто, а хвост у него ровно
    # такой же («Кириш *ие*»).
    limit = max(1, int(min(max(INK_EXPAND_SHARE * (x1 - x0), 4 * size),
                           INK_EXPAND_MAX) * scale))
    gap = max(1, int(round(INK_GAP_SHARE * size * scale)))
    left = (x0 - pad - cb[0]) * scale
    right = (x1 + pad - cb[0]) * scale
    # Вправо: столбцы от правого края наружу.
    mins = _col_mins(gray, right, right + limit, y0, y1)
    run, reach = 0, 0
    for k, v in enumerate(mins):
        if v < dark:
            run, reach = 0, k + 1
        else:
            run += 1
            if run >= gap:
                break
    x1 = x1 + reach / scale if reach else x1
    # Влево: столбцы от левого края наружу, то есть справа налево.
    mins = _col_mins(gray, left - limit, left, y0, y1)
    run, reach = 0, 0
    for k, v in enumerate(reversed(mins)):
        if v < dark:
            run, reach = 0, k + 1
        else:
            run += 1
            if run >= gap:
                break
    x0 = x0 - reach / scale if reach else x0
    return x0, x1


def _strip_colors(sample, box: dict, pad: float, n: int, x0f=None, x1f=None, q: float = PAPER_Q) -> list:
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
    im, scale, cb = sample[0], sample[1], sample[2]
    W, H = im.size
    bx0 = box["x0"] if x0f is None else x0f
    bx1 = box["x1"] if x1f is None else x1f
    x0, x1 = (bx0 - pad - cb[0]) * scale, (bx1 + pad - cb[0]) * scale
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
            col.append(vals[min(len(vals) - 1, int(q * len(vals)))] / 255.0)
        out.append(tuple(col))
    return out


def _fill_box(c, box: dict, pad: float, colors: list, x0f=None, x1f=None):
    """Закраска рамки полосами. Полосы кладутся с нахлёстом внутрь, но
    НЕ ЗА правый край: вылезший кусок виден на поле прямоугольником.
    `x0f`/`x1f` — края, раздвинутые по краске (`_ink_box`): закрашиваем
    то, что на странице НАПЕЧАТАНО, а не то, что насчитал текстовый слой."""
    bx0 = box["x0"] if x0f is None else x0f
    bx1 = box["x1"] if x1f is None else x1f
    x0, y0 = bx0 - pad, box["bottom"] - pad
    w, h = (bx1 - bx0) + 2 * pad, (box["top"] - box["bottom"]) + 2 * pad
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


def build(pdf_bytes: bytes, layout: dict, texts: dict, extra: "list | None" = None) -> tuple:
    """(PDF, отчёт).

    `layout` — {"boxes": {номер абзаца: [рамки]}}, `texts` — {номер абзаца:
    перевод}. Абзац без перевода не трогается.

    `extra` — [{"text": …, "boxes": […]}]: рамки, у которых номера абзаца
    нет вовсе. Ими приходит текст страниц-КАРТИНОК (обложка, скан): его
    рамки считал разбор надписей, и в раскладку текстового слоя им не
    попасть по построению. Печатаются наравне с абзацами.

    Рамка с `repeat` — ОДИН И ТОТ ЖЕ текст на каждой своей странице
    (колонтитул), а не продолжение абзаца: разложить его по рамкам, как
    абзац, значило бы напечатать первую половину названия книги на одной
    странице, а вторую — на следующей."""
    ok, why = available()
    if not ok:
        raise NotAvailable(why)
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from pypdf import PdfReader, PdfWriter
    fonts = _register_fonts()
    sw = pdfmetrics.stringWidth
    all_texts = dict(texts)
    for k, it in enumerate(extra or []):
        all_texts["x%d" % k] = it.get("text") or ""
    miss = _missing_glyphs(fonts, all_texts)
    if miss > GLYPH_MISS_MAX:
        raise NotAvailable("шрифт %s не знает %d знаков перевода — письменность "
                           "целевого языка в нём отсутствует; задайте LAYOUT_FONT"
                           % (os.path.basename(font_path("")), miss))

    reader = PdfReader(io.BytesIO(pdf_bytes))
    stats = {"pages": len(reader.pages), "paragraphs": 0, "shrunk": 0,
             "overflow": 0, "nocolor": 0, "rotated": 0, "bold": 0, "italic": 0,
             # Колонтитулы (одна надпись на многих страницах) и надписи
             # со страниц-картинок: обе дороги молчали до сих пор, и обе
             # оставляли на готовой книге русские строки.
             "repeated": 0, "repeatBoxes": 0, "imageBoxes": 0,
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

    jobs = [(int(key), (texts.get(int(key)) or "").strip(), boxes)
            for key, boxes in (layout.get("boxes") or {}).items()]
    jobs += [("x%d" % k, (it.get("text") or "").strip(), it.get("boxes") or [])
             for k, it in enumerate(extra or [])]
    # Рамка надписи со страницы-картинки считана в ПИКСЕЛЯХ этой картинки,
    # и перевести её в точки страницы может только тот, кто держит сам PDF:
    # приходит она долями листа (`frac`), раскрывается здесь.
    for _idx, _t, boxes in jobs:
        for b in boxes:
            if b.get("frac") and 0 <= int(b["page"]) < len(reader.pages):
                _unfrac(b, reader.pages[int(b["page"])].mediabox)

    # ПЕРВЫЙ ПРОХОД: меряем бумагу и краску — по одной странице за раз
    # (страница рисуется и тут же забывается). Меряем ДО раскладки, потому
    # что раздвинутая по краске рамка шире, а в ширину рамки укладывается
    # перевод: померив после, мы разложили бы текст по неверной ширине.
    sampler = _Sampler(pdf_bytes)
    live_boxes: dict = {}
    for idx, text, boxes in jobs:
        if not text or not boxes:
            continue
        for b in boxes:
            pg = int(b["page"])
            if pg not in skip:
                live_boxes.setdefault(pg, []).append(b)
    for pg in sorted(live_boxes):
        sample = sampler.page(pg)
        for b in live_boxes[pg]:
            pad = PAD_SHARE * max(b["size"], 1.0)
            # На бумаге буквы — тёмный хвост, и бумага это высокий процентиль
            # яркости. На КАРТИНКЕ «бумага» — сама фотография, и высокий
            # процентиль берёт её блик: белая заплатка посреди жёлтой обложки.
            # Там правильный ответ — медиана: фон занимает больше места,
            # чем буквы.
            q = PAPER_Q_IMAGE if b.get("image") else PAPER_Q
            colors = _strip_colors(sample, b, pad, FILL_STRIPS, q=q)
            paper = max(sum(col) / 3.0 for col in colors) if colors else 1.0
            if b.get("image"):
                # Надпись СО СТРАНИЦЫ-КАРТИНКИ по краске не раздвигается:
                # её рамку мерил разбор картинок по самой картинке, она точна,
                # а на обложке «краска» — это фотография, и раздвижение
                # закрасило бы её до потолка.
                x0, x1 = b["x0"], b["x1"]
            else:
                x0, x1 = _ink_box(sample, b, pad, paper)
            if x1 - x0 > b["x1"] - b["x0"] + 0.5:
                # Рамка поехала по краске — и цвет бумаги надо мерить
                # по НОВОЙ ширине, иначе полосы лягут не на своё место.
                colors = _strip_colors(sample, b, pad, FILL_STRIPS, x0, x1, q=q)
            # Рамка ТЕПЕРЬ такая: по ней и раскладывается перевод. Строка
            # оригинала начиналась там, где стоит её краска, — значит там же
            # начинается и перевод.
            # Отступ первой строки считался ОТ ПРЕЖНЕГО края: рамка уехала
            # влево — отступ на столько же вырос, иначе красная строка
            # оригинала превратилась бы в ровный край.
            b["indent"] = max(0.0, b.get("indent") or 0.0) + max(0.0, b["x0"] - x0)
            b["x0"], b["x1"] = x0, x1
            b["_fill"] = (colors, paper, pad)

    # Раскладка считается ПО АБЗАЦУ, один раз, а не на каждой его странице:
    # абзац бывает разорван концом страницы, и счёт «на страницу» удваивал
    # и работу в отчёте, и честное число не влезших.
    plan: list = []
    pages_used: set = set()
    for idx, text, boxes in jobs:
        if not text or not boxes:
            continue
        live = [b for b in boxes if int(b["page"]) not in skip]
        if len(live) != len(boxes):
            # У повторяющейся надписи повёрнутая страница отнимает ОДНУ
            # рамку, а не всю работу: на остальных её печатать можно.
            if not (boxes and boxes[0].get("repeat")) or not live:
                stats["rotated"] += 1
                continue
        groups = [[b] for b in live] if live[0].get("repeat") else [live]
        stats["paragraphs"] += 1
        style = live[0].get("style") or ""
        stats["bold"] += 1 if "b" in style else 0
        stats["italic"] += 1 if "i" in style else 0
        if live[0].get("repeat"):
            stats["repeated"] += 1
            stats["repeatBoxes"] += len(groups)
        if live[0].get("image"):
            stats["imageBoxes"] += len(live)
        shrunk = over = False
        for grp in groups:
            font = fonts.get(grp[0].get("style") or "") or fonts[""]
            size, lead, per_box, fits = _fit(text, grp, sw, font)
            shrunk = shrunk or size < max(b["size"] for b in grp) - 0.01
            over = over or not fits
            plan.append((idx, grp, per_box, size, lead, font))
            pages_used.update(int(b["page"]) for b in grp)
        stats["shrunk"] += 1 if shrunk else 0
        stats["overflow"] += 1 if over else 0


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
        # ЗАЛИВКА идёт первой и вся разом, а текст — вторым проходом.
        # Рамки надписей с картинки законно пересекаются (заголовок над двумя
        # колонками, стилизованная обложка), и заливка второй рамки стирала бы
        # уже написанный перевод первой — с отчётом «обе написаны». Тот же
        # закон, что в `image_text.render_target`.
        here = [(b, lines, size, lead, font, n)
                for _idx, boxes, per_box, size, lead, font in plan
                for n, (b, lines) in enumerate(zip(boxes, per_box))
                if int(b["page"]) == i]
        for b, _lines, _size, _lead, _font, _n in here:
            # Закраска идёт и у ПУСТОЙ рамки: перевод мог целиком влезть
            # в первую половину абзаца, а во второй остался бы оригинал —
            # рядом с готовым переводом того же абзаца.
            colors, _paper, pad = b.get("_fill") or ([(1.0, 1.0, 1.0)] * FILL_STRIPS, 1.0,
                                                     PAD_SHARE * max(b["size"], 1.0))
            _fill_box(c, b, pad, colors)
        for b, lines, size, lead, font, n in here:
            paper = (b.get("_fill") or (None, 1.0, None))[1]
            if not lines:
                continue
            # Чёрным по тёмному не читается: на обложке и на тёмной плашке
            # перевод печатается светлым. Цвет берётся у самой бумаги под
            # рамкой — там же, где и закраска.
            c.setFillColorRGB(*((1, 1, 1) if paper < DARK_PAPER else (0, 0, 0)))
            c.setFont(font, size)
            y = b["top"] - 0.85 * size
            for k, line in enumerate(lines):
                c.drawString(b["x0"] + (b["indent"] if (k == 0 and n == 0) else 0.0), y, line)
                y -= lead
        order.append(drawn)
        drawn += 1
        c.showPage()
    c.save()
    # Не измерена бумага ровно там, где её не отрисовали: закраска вышла
    # белой, и число сказано. Считать «всё или ничего» нельзя — часть
    # страниц может не отрисоваться, и отчёт тогда врал бы про остальные.
    stats["nocolor"] = len(sampler.missed & pages_used)
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
