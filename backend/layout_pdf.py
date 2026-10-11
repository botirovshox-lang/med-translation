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

# Замок pdfium: он не потокобезопасен, и падает не исключением, а всем
# процессом (см. backend/pdfium_gate.py). Импорт двумя путями — модуль
# живёт и пакетом `backend`, и плоско (так его берут тесты).
try:
    from backend.pdfium_gate import LOCK as PDFIUM_LOCK
except ImportError:                                  # pragma: no cover
    from pdfium_gate import LOCK as PDFIUM_LOCK

# Шрифт перевода. Своего у нас нет и быть не должно: нужен тот, в котором
# есть письменность целевого языка (узбекская кириллица, казахская, любая
# другая). Берём первый найденный из списка — на сервере это DejaVu,
# он лежит рядом с LibreOffice.
# Свои шрифты из репозитория (Noto — те же, что у субтитров видео): они
# есть на сервере ВСЕГДА, в них латиница, кириллица (с узбекской, казахской,
# таджикской) и греческий, и они уже DejaVu — ближе к гарнитурам книг.
_REPO_FONTS = str(Path(__file__).resolve().parent.parent / "frontend" / "vendor" / "fonts" / "sub")
FONT_CANDIDATES = {
    "": [os.environ.get("LAYOUT_FONT", ""),
         _REPO_FONTS + "/NotoSerif-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
         "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/arial.ttf"],
    "b": [os.environ.get("LAYOUT_FONT_BOLD", ""),
          _REPO_FONTS + "/NotoSerif-Bold.ttf",
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
# Гарнитура перевода — ТА ЖЕ, что у оригинала: рубленая там, где абзац
# набран рубленым (Helvetica, DIN, Calibri), моноширинная — у кода. Семейство
# узнаёт разбор PDF по имени шрифта (`pdfpages_worker._family`), а печатаем
# мы своим файлом той же гарнитуры: шрифт оригинала встроен подмножеством —
# в нём только буквы ЕГО языка, и перевод вышел бы квадратами. Нет файла
# семейства — печатается шрифтом с засечками (`FONT_CANDIDATES`), как прежде.
FAMILY_CANDIDATES = {
    "sans": {
        "": [os.environ.get("LAYOUT_FONT_SANS", ""),
             _REPO_FONTS + "/NotoSans-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
             "C:/Windows/Fonts/arial.ttf"],
        "b": [os.environ.get("LAYOUT_FONT_SANS_BOLD", ""),
              _REPO_FONTS + "/NotoSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf"],
        "i": [os.environ.get("LAYOUT_FONT_SANS_ITALIC", ""),
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
              "C:/Windows/Fonts/ariali.ttf"],
        "bi": [os.environ.get("LAYOUT_FONT_SANS_BOLDITALIC", ""),
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
               "C:/Windows/Fonts/arialbi.ttf"],
    },
    "mono": {
        "": [os.environ.get("LAYOUT_FONT_MONO", ""),
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
             "C:/Windows/Fonts/cour.ttf"],
        "b": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
              "C:/Windows/Fonts/courbd.ttf"],
        "i": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationMono-Italic.ttf",
              "C:/Windows/Fonts/couri.ttf"],
        "bi": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationMono-BoldItalic.ttf",
               "C:/Windows/Fonts/courbi.ttf"],
    },
}
# Запасной шрифт — DejaVu из репозитория: в нём армянский, грузинский,
# греческий и вся кириллица, которых нет в Noto Sans/Serif. Он стоит
# ПОСЛЕДНИМ: выбирается, только когда первые не знают букв перевода
# (`font_path(chars=)`). Только обычный и полужирный — курсив из них
# дорисует печать.
_REPO_FALLBACK = {"": [_REPO_FONTS + "/DejaVuSans.ttf"],
                  "b": [_REPO_FONTS + "/DejaVuSans-Bold.ttf"]}
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
# 144, а не 72: по странице меряется ещё цвет краски, а на 72 сглаживание
# размывает строку мелкого кегля так, что чёрный читается серым.
SAMPLE_DPI = int(os.environ.get("LAYOUT_SAMPLE_DPI", "144"))
# Потолок одного снимка страницы, мегапикселей (≈8 байт на пиксель в пике).
SAMPLE_MAX_MPX = float(os.environ.get("LAYOUT_SAMPLE_MAX_MPX", "12"))
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
# Насколько краска строки может уйти за конец, посчитанный по метрикам
# шрифта (в кеглях): штрих скана шире метрики, но не на слово.
# Докуда уменьшать кегль надписи по дуге (у неё нет следующей строки).
CURVE_MIN_SHARE = float(os.environ.get("LAYOUT_CURVE_MIN_SIZE", "0.4"))
INK_EXACT_SLACK = float(os.environ.get("LAYOUT_INK_EXACT_SLACK", "0.6"))
INK_GAP_SHARE = float(os.environ.get("LAYOUT_INK_GAP", "0.9"))
# Докуда раздвигать ВЛЕВО, в кеглях (см. `_ink_box`).
INK_LEFT_PT = float(os.environ.get("LAYOUT_INK_LEFT", "1.5"))
INK_INNER_SHARE = float(os.environ.get("LAYOUT_INK_INNER", "0.75"))
# Насколько темнее бумаги считать краской.
INK_DARK = float(os.environ.get("LAYOUT_INK_DARK", "0.82"))
# Ниже этой яркости бумага считается тёмной, и перевод печатается светлым.
DARK_PAPER = float(os.environ.get("LAYOUT_DARK_PAPER", "0.45"))
# На сколько полос режется закраска ОДНОЙ строки (у строк своё место — см.
# `slots`): строка короткая, и десяти полос ей не нужно.
SLOT_STRIPS = 3
# Насколько можно СУЗИТЬ начертание по горизонтали, прежде чем уменьшать
# кегль. Наш шрифт (DejaVu) шире гарнитур оригинала (Helvetica, DIN
# Condensed), и без сужения почти каждый абзац уходил мельче оригинала —
# высота букв менялась там, где хватило бы ширины. Узкое начертание —
# обычный приём вёрстки; ниже 80% буквы читаются сплющенными.
HSCALE_MIN = float(os.environ.get("LAYOUT_HSCALE_MIN", "0.85"))
# Узкое начертание оригинала (Condensed): перевод сжат с самого начала.
HSCALE_COND = float(os.environ.get("LAYOUT_HSCALE_COND", "0.82"))


class NotAvailable(Exception):
    """Нечем собрать: нет библиотеки или шрифта. Не ошибка данных —
    отсутствие возможности, и отвечать на неё надо словами."""


_CMAPS: dict = {}


def _cmap(path: str) -> set:
    """Знаки, которые есть в файле шрифта (кэш по пути)."""
    if path not in _CMAPS:
        try:
            from reportlab.pdfbase.ttfonts import TTFontFile
            _CMAPS[path] = set(TTFontFile(path).charToGlyph)
        except Exception:
            _CMAPS[path] = set()
    return _CMAPS[path]


def _covers(path: str, chars) -> bool:
    """Знает ли шрифт буквы перевода (без `GLYPH_MISS_MAX` редких знаков)."""
    if not chars:
        return True
    have = _cmap(path)
    return sum(1 for ch in chars if ord(ch) not in have) <= GLYPH_MISS_MAX


def font_path(style: str = "", family: str = "", chars=None) -> str:
    """Файл шрифта под начертание. Нет своего файла — берём обычный:
    напечатать светлым вместо курсива честнее, чем не напечатать вовсе
    (на боевом сервере из DejaVu Serif есть обычный и полужирный).

    `family` — «sans» / «mono»: своё семейство; нет у него ни одного файла —
    пусто, и вызывающий берёт шрифт с засечками.

    `chars` — буквы перевода: берётся первый файл, который их ЗНАЕТ. Noto
    из репозитория стоит первым (уже DejaVu), но армянского и грузинского
    в нём нет — тогда выбирается запасной DejaVu, а не пустые квадраты."""
    table = FAMILY_CANDIDATES.get(family or "") if family else FONT_CANDIDATES
    if table is None:
        table = FONT_CANDIDATES
    for p in (table.get(style or "", []) + _REPO_FALLBACK.get(style or "", [])):
        if p and Path(p).exists() and _covers(p, chars):
            return p
    if style:
        return font_path("b" if style == "bi" else "", family, chars)
    if chars:
        # Букв перевода не знает НИ ОДИН файл — берём первый, как прежде:
        # отказ словами скажет сверка глифов (`_missing_glyphs`).
        return font_path(style, family, None)
    return ""


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


def _register_fonts(chars=None) -> dict:
    """{начертание: имя шрифта} — шрифт с засечками, и {«семейство|начертание»:
    имя} — рубленый и моноширинный. Одно и то же имя у двух начертаний
    законно: файла может не быть, и тогда начертание просто совпадает.
    `chars` — буквы перевода: файл выбирается тот, что их знает."""
    import hashlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    out = {}
    for fam in ("",) + tuple(FAMILY_CANDIDATES):
        for style in ("", "b", "i", "bi"):
            path = font_path(style, fam, chars)
            if not path:
                continue
            # Имя шрифта в reportlab — на весь процесс; один и тот же файл —
            # одно имя, другой файл (другие буквы перевода) — другое.
            name = (FONT_NAME + (fam.capitalize()) + (style or "R")
                    + hashlib.sha1(path.encode("utf-8")).hexdigest()[:6])
            if name not in pdfmetrics.getRegisteredFontNames():
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                except Exception:
                    if fam:
                        continue            # своего семейства нет — засечки
                    raise
            out[(fam + "|" + style) if fam else style] = name
            # Какое начертание файл даёт НА ДЕЛЕ: курсива у шрифта может
            # не быть, и тогда под именем курсива лежит прямой — наклон
            # дорисует печать (`_synth`).
            table = FAMILY_CANDIDATES.get(fam) or FONT_CANDIDATES
            real = next((st for st in (style, "b", "i", "")
                         if path in ((table.get(st) or []) + _REPO_FALLBACK.get(st, []))), "")
            out["@" + name] = real
    return out


def _synth(fonts: dict, name: str, style: str) -> str:
    """Чего из просимого начертания у файла шрифта нет («b», «i», «bi»):
    его печать дорисует — наклоном (курсив) и обводкой (полужирный).
    Так поступает любая программа вёрстки, когда начертания нет:
    прямой текст на месте курсива оригинала — это уже не 1в1."""
    real = fonts.get("@" + name, style)
    return "".join(ch for ch in "bi" if ch in (style or "") and ch not in real)


def _face_style(style: str) -> str:
    """Начертание для выбора ФАЙЛА шрифта: «b», «i», «bi». Флаг узкого
    начертания «c» — про сжатие (`HSCALE_COND`), а не про файл: с ним
    «bc» не находился и полужирный дорисовывался обводкой."""
    return "".join(ch for ch in "bi" if ch in (style or ""))


def _font_for(fonts: dict, box: dict) -> str:
    """Шрифт рамки: семейство оригинала и его начертание; чего нет — то
    ближайшее, что есть (то же семейство обычным, затем засечки)."""
    style = _face_style(box.get("style") or "")
    fam = box.get("fam") or ""
    if fam in FAMILY_CANDIDATES:
        name = fonts.get(fam + "|" + style) or fonts.get(fam + "|")
        if name:
            return name
    return fonts.get(style) or fonts[""]


def _slot_paper(sample, box: dict, pad: float, n: int, x0f=None, x1f=None) -> list:
    """Цвет бумаги под строкой полосами — САМЫЙ ЧАСТЫЙ тон полосы.

    Светлый процентиль (`_strip_colors`) верен для тёмного текста на светлой
    бумаге, и только для него: у белой надписи на цветной плашке схемы он
    брал сами буквы, и вместо плашки ложилась светлая заплатка. Самый
    частый тон — фон при любой полярности: буквы занимают меньшую часть
    строки, а их сглаженные края размазаны по многим тонам. Без numpy —
    прежний процентиль."""
    try:
        import numpy as np
    except ImportError:
        return _strip_colors(sample, box, pad, n, x0f, x1f)
    if not sample:
        return [(1.0, 1.0, 1.0)] * n
    im, scale, cb, gray = sample
    W, H = im.size
    bx0 = box["x0"] if x0f is None else x0f
    bx1 = box["x1"] if x1f is None else x1f
    x0, x1 = (bx0 - pad - cb[0]) * scale, (bx1 + pad - cb[0]) * scale
    y0 = int(max(0, H - (box["top"] + pad - cb[1]) * scale))
    y1 = int(min(H, H - (box["bottom"] - pad - cb[1]) * scale))
    gx0, gx1 = max(0, int(x0)), min(W, max(int(x0) + 1, int(x1) + 1))
    if gx1 - gx0 < 1 or y1 - y0 < 1:
        return _strip_colors(sample, box, pad, n, x0f, x1f)
    rgb = np.asarray(im.crop((gx0, y0, gx1, y1)), dtype=np.uint8)[:, :, :3]
    lum = np.asarray(gray.crop((gx0, y0, gx1, y1)), dtype=np.uint8)
    step = max(1.0, (x1 - x0) / n)
    out = []
    for k in range(n):
        a = max(0, int(x0 + k * step) - gx0)
        b = min(rgb.shape[1], max(a + 1, int(x0 + (k + 1) * step) + 1 - gx0))
        lu = lum[:, a:b].reshape(-1)
        if not len(lu):
            out.append(out[-1] if out else (1.0, 1.0, 1.0))
            continue
        bins = (lu // 16).astype(np.int16)
        # Тон фона — по КРАЯМ полосы (выше прописных и ниже базовой линии):
        # там букв почти нет. Жирная белая надпись на цветном кольце схемы
        # занимает больше половины своей клетки, и самый частый тон всей
        # полосы оказывался цветом букв — ложилась светлая заплатка.
        hh = lum.shape[0]
        e = max(1, hh // 4)
        if box.get("edge") == "cols" and b - a >= 4:
            # Буква стоит ВЕРТИКАЛЬНО (крутой участок дуги): над и под ней —
            # соседние буквы, а фон — слева и справа.
            ew = max(1, (b - a) // 4)
            edge = np.concatenate([lum[:, a:a + ew].reshape(-1), lum[:, b - ew:b].reshape(-1)])
        elif hh >= 4:
            edge = np.concatenate([lum[:e, a:b].reshape(-1), lum[hh - e:, a:b].reshape(-1)])
        else:
            edge = lu
        ebins = (edge // 16).astype(np.int16)
        ecount = np.bincount(ebins, minlength=16)
        mode = int(ecount.argmax())
        full = np.bincount(bins, minlength=16)
        # Тон краёв — фон, только если он и во всей полосе не редкость:
        # рамка ссылки (синий прямоугольник вокруг адреса) лежит ровно по
        # краям строки, и заливка выходила синей плашкой.
        if ecount[mode] < 0.15 * len(ebins) or full[max(0, mode - 1):mode + 2].sum() < 0.3 * len(bins):
            mode = int(full.argmax())
        sel = np.abs(bins - mode) <= 1
        col = np.median(rgb[:, a:b].reshape(-1, 3)[sel], axis=0) / 255.0
        out.append(tuple(float(v) for v in col))
    return out


def _ink_color(sample, box: dict, pad: float, paper: float, either: bool = False):
    """Цвет КРАСКИ оригинала под рамкой — (r, g, b) в долях, либо None.

    Заголовок, набранный синим, и подпись серым — это вёрстка не меньше,
    чем кегль: перевод чёрным поверх них читался бы чужим текстом. Берём
    пиксели темнее бумаги (порог `INK_DARK`, как у раздвижки по краске),
    из них — самую тёмную ЧЕТВЕРТЬ: края букв сглажены и тянут цвет
    к бумаге, а у мелкого кегля сглажен почти весь штрих (на половине
    чёрный текст читался серым). Медиана по каналам — сам цвет. Нечего
    мерить — None, и печать чёрным, как прежде.

    `either` — краска бывает и СВЕТЛЕЕ бумаги (белая надпись на цветной
    плашке схемы): берётся та сторона, где пикселей больше, и её крайняя
    четверть (самая светлая — у светлой краски).

    Полужирного по краске здесь НЕ ищем, и это замер, а не лень: толщина
    штриха на мелком кегле упирается в размер пикселя, и обычный текст
    в 4 пт выходил «жирнее» полужирного заголовка — вышел бы ложный жирный.
    Начертание даёт только имя шрифта."""
    if not sample:
        return None
    im, scale, cb, gray = sample
    W, H = im.size
    x0 = int(max(0, (box["x0"] - cb[0]) * scale))
    x1 = int(min(W, (box["x1"] - cb[0]) * scale + 1))
    y0 = int(max(0, H - (box["top"] - cb[1]) * scale))
    y1 = int(min(H, H - (box["bottom"] - cb[1]) * scale + 1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    dark = INK_DARK * paper * 255.0
    try:
        import numpy as np
        g = np.asarray(gray.crop((x0, y0, x1, y1)), dtype=np.float32)
        rgb = np.asarray(im.crop((x0, y0, x1, y1)), dtype=np.float32)
        mask = g < dark
        light = False
        if either:
            lmask = g > paper * 255.0 + 0.25 * 255.0
            if int(lmask.sum()) > int(mask.sum()):
                mask, light = lmask, True
        if int(mask.sum()) < 8:
            return None
        lum = g[mask]
        pix = rgb[mask][:, :3]
        # Оттенок — тот, которого в краске БОЛЬШЕ: синие рамки ссылок
        # и цветные значки темнее серого текста, и самая тёмная четверть
        # без этого выбора красила бы строку авторов синим. Серая краска
        # (без цвета) — своя группа; цветная — по корзинам оттенка.
        chroma = pix.max(axis=1) - pix.min(axis=1)
        neutral = chroma < 48
        if int(neutral.sum()) * 2 >= len(pix):
            sel = neutral
        else:
            r_, g_, b_ = pix[:, 0], pix[:, 1], pix[:, 2]
            hue = np.floor(((np.degrees(np.arctan2(np.sqrt(3.0) * (g_ - b_), 2 * r_ - g_ - b_))
                             + 360.0) % 360.0) / 30.0).astype(np.int16)
            hue[neutral] = -1
            vals, counts = np.unique(hue[~neutral], return_counts=True)
            sel = hue == vals[int(np.argmax(counts))]
        sub = lum[sel]
        # На мелком кегле штрих тоньше пикселя замера, и сглаживание
        # осветляет почти весь штрих: чёрная подпись в 4 пт на длинной
        # странице (замер там мельче — потолок мегапикселей) выходила
        # серой. Чем меньше пикселей на кегль, тем уже крайняя доля.
        px = float(box.get("size") or 10.0) * scale
        q = 25.0 if px >= 14 else (10.0 if px >= 8 else 5.0)
        keep = (sub >= np.percentile(sub, 100 - q)) if light else (sub <= np.percentile(sub, q))
        col = np.median(pix[sel][keep], axis=0) / 255.0
        return tuple(float(v) for v in col[:3])
    except ImportError:
        pass
    except Exception:
        return None
    try:
        gpx = list(gray.crop((x0, y0, x1, y1)).getdata())
        cpx = list(im.crop((x0, y0, x1, y1)).getdata())
    except Exception:
        return None
    ink = sorted((v, c) for v, c in zip(gpx, cpx) if v < dark)
    if len(ink) < 8:
        return None
    part = [c for _v, c in ink[:max(1, len(ink) // 4)]]
    return tuple(sorted(c[ch] for c in part)[len(part) // 2] / 255.0 for ch in range(3))


def _slot_boxes(b: dict) -> list:
    """Места строк абзаца на этой странице — рамками той же формы, что
    у абзаца: {x0, x1, top, bottom, size} плюс базовая линия, начало
    строки и её начертание. Пусто — у рамки мест нет (раскладка, записанная
    до них, надпись с картинки), и она идёт прежней дорогой — прямоугольником."""
    if b.get("image") or not b.get("slots"):
        return []
    out = []
    for sl in b["slots"]:
        try:
            x0, y, x1, sz = (float(v) for v in sl[:4])
        except Exception:
            return []
        sz = sz if sz > 0 else float(b.get("size") or 10.0)
        if len(sl) > 8 and isinstance(sl[8], dict) and sl[8].get("pts"):
            sd = _rot_slot(sl[8], sz)
            if sd:
                sd.update({"style": (sl[4] if len(sl) > 4 else "") or "", "page": b["page"],
                           "n": int(sl[6]) if len(sl) > 6 and sl[6] else 0,
                           "color": _color_of(sl[8].get("color"))})
                out.append(sd)
            continue
        xl = sl[5] if len(sl) > 5 else None
        out.append({"x0": x0, "x1": max(x1, x0 + 0.5 * sz), "top": y + 0.85 * sz,
                    "bottom": y - 0.25 * sz, "size": sz, "y": y, "x": x0,
                    "xl": float(xl) if xl is not None else None,
                    "n": int(sl[6]) if len(sl) > 6 and sl[6] else 0,
                    "exact": bool(sl[7]) if len(sl) > 7 else False,
                    "style": (sl[4] if len(sl) > 4 else "") or "", "page": b["page"],
                    "color": _color_of(sl[9] if len(sl) > 9 else None)})
    return out


def _color_of(v):
    """Цвет краски строки, записанный разбором из самого PDF, — (r, g, b)
    либо None («не знаем», тогда меряем по странице)."""
    try:
        if v is None or len(v) != 3:
            return None
        return tuple(min(1.0, max(0.0, float(t))) for t in v)
    except Exception:
        return None


def _rot_slot(rot: dict, size: float) -> "dict | None":
    """Место ПОВЁРНУТОЙ строки в своей системе координат: x — вдоль пути
    от его начала (0 … длина пути), y — от базовой линии. Прямая строка —
    начало и угол (`ox`, `oy`, `a`); дуга — узлы пути с накопленной длиной
    (`nodes`): перевод пойдёт по ним буква за буквой. `bbox` — прямоугольник
    на листе, по нему меряются бумага и краска."""
    import math
    pts = rot.get("pts") or []
    end = rot.get("end") or (pts[-1][:2] if pts else None)
    if not pts or not end:
        return None
    nodes = [(float(p[0]), float(p[1])) for p in pts] + [(float(end[0]), float(end[1]))]
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(nodes, nodes[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    length = max(cum[-1], 0.5 * size)
    xs, ys = [n[0] for n in nodes], [n[1] for n in nodes]
    m = 1.1 * size
    return {"rot": rot, "curved": bool(rot.get("curved")), "nodes": nodes, "cum": cum,
            "ox": nodes[0][0], "oy": nodes[0][1], "a": float(pts[0][2]),
            "x": 0.0, "x0": 0.0, "x1": length, "y": 0.0, "top": 0.85 * size,
            "bottom": -0.25 * size, "size": size, "xl": None, "exact": False,
            "bbox": {"x0": min(xs) - m, "x1": max(xs) + m, "top": max(ys) + m,
                     "bottom": min(ys) - m, "size": size}}


def _path_at(sd: dict, s: float) -> tuple:
    """(x, y, угол°) точки пути на расстоянии s от начала; за концом —
    продолжение последнего отрезка."""
    import math
    nodes, cum = sd["nodes"], sd["cum"]
    k = 0
    while k < len(cum) - 2 and cum[k + 1] < s:
        k += 1
    (x0, y0), (x1, y1) = nodes[k], nodes[k + 1]
    seg = (cum[k + 1] - cum[k]) or 1e-6
    t = (s - cum[k]) / seg
    ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) if seg > 1e-5 else sd["a"]
    return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, ang


def _arc_cells(sd: dict) -> list:
    """Клетки букв дуги на листе (рамки для замера бумаги и краски): квадрат
    вокруг СЕРЕДИНЫ буквы — от узла на полшага вдоль пути и на треть кегля
    вверх по нормали, — а не прямоугольник вправо-вверх от узла: на крутом
    участке кольца тот уходил за кольцо и мерил соседний цвет."""
    import math
    out = []
    size = sd["size"]
    nodes, cum = sd["nodes"], sd["cum"]
    for k in range(len(nodes) - 1):
        adv = max(cum[k + 1] - cum[k], 0.3 * size)
        _x, _y, ang = _path_at(sd, cum[k] + 1e-3)
        a = math.radians(ang)
        cx = nodes[k][0] + 0.5 * adv * math.cos(a) - 0.33 * size * math.sin(a)
        cy = nodes[k][1] + 0.5 * adv * math.sin(a) + 0.33 * size * math.cos(a)
        # Габарит буквы под её углом плюс поля в четверть кегля: края клетки
        # обязаны выйти за букву на фон.
        ca, sa = abs(math.cos(a)), abs(math.sin(a))
        adv_ = max(adv, 0.6 * size)
        hw = 0.5 * (ca * adv_ + sa * size) + 0.25 * size
        hh = 0.5 * (sa * adv_ + ca * size) + 0.25 * size
        out.append({"x0": cx - hw, "x1": cx + hw, "top": cy + hh,
                    "bottom": cy - hh, "size": size,
                    "edge": "cols" if abs(math.sin(a)) > 0.7 else "rows"})
    return out


def _fill_rot(c, sd: dict, colors: list, pad: float) -> None:
    """Закраска повёрнутой строки: прямой — одним повёрнутым прямоугольником,
    дуги — по букве (у каждой свой угол и свой цвет фона под ней)."""
    size = sd["size"]
    if not sd["curved"]:
        c.saveState()
        c.translate(sd["ox"], sd["oy"])
        c.rotate(sd["a"])
        c.setFillColorRGB(*(colors[0] if colors else (1, 1, 1)))
        c.rect(-pad, -0.25 * size - pad, sd["x1"] + 2 * pad, 1.1 * size + 2 * pad, stroke=0, fill=1)
        c.restoreState()
        return
    cols = sd.get("_cfill") or []
    nodes, cum = sd["nodes"], sd["cum"]
    for k in range(len(nodes) - 1):
        x, y, ang = _path_at(sd, cum[k] + 1e-3)
        adv = cum[k + 1] - cum[k]
        c.saveState()
        c.translate(nodes[k][0], nodes[k][1])
        c.rotate(ang)
        c.setFillColorRGB(*(cols[k] if k < len(cols) else (colors[0] if colors else (1, 1, 1))))
        c.rect(-pad, -0.25 * size - pad, adv + 2 * pad, 1.1 * size + 2 * pad, stroke=0, fill=1)
        c.restoreState()


def _draw_rot(c, sd: dict, lines: list, size: float, font: str, hsc: float, sw, align: str,
              raster=None, color=(0, 0, 0)) -> None:
    """Перевод повёрнутой строки: прямой — в повёрнутой системе координат,
    дуги — по букве вдоль пути (по центру своего участка: подпись на кольце
    схемы выключена по центру дуги)."""
    if not sd["curved"]:
        c.saveState()
        c.translate(sd["ox"], sd["oy"])
        c.rotate(sd["a"])
        for k, ln in enumerate(lines):
            if not ln:
                continue
            w = sw(ln, font, size) * hsc
            x = (sd["x1"] - w) / 2.0 if align == "center" else 0.0
            if raster is not None:
                raster.put(c, x, -k * 1.2 * size, ln, size, color, hsc, sd.get("style") or "",
                           sd.get("_rtl"))
                continue
            to = c.beginText(x, -k * 1.2 * size)
            to.setFont(font, size)
            if hsc < 0.999:
                to.setHorizScale(hsc * 100.0)
            to.textOut(ln)
            c.drawText(to)
        c.restoreState()
        return
    text = " ".join(x for x in lines if x)
    if not text:
        return
    if raster is not None and (_shaped_script({0: text}) or raster.rtl(text)):
        # Буква за буквой нельзя: арабица и иврит вышли бы задом наперёд
        # и несвязанными, огласовки индийских письменностей — отдельно от
        # своих букв. Такая надпись печатается целиком по ХОРДЕ дуги.
        import math
        (x0_, y0_), (x1_, y1_) = sd["nodes"][0], sd["nodes"][-1]
        chord = math.hypot(x1_ - x0_, y1_ - y0_) or sd["x1"]
        w = sw(text, font, size) * hsc
        sz = max(size * CURVE_MIN_SHARE, size * min(1.0, chord / w)) if w > 0 else size
        w = sw(text, font, sz) * hsc
        c.saveState()
        c.translate(x0_, y0_)
        c.rotate(math.degrees(math.atan2(y1_ - y0_, x1_ - x0_)))
        raster.put(c, max(0.0, (chord - w) / 2.0), 0, text, sz, color, hsc, sd.get("style") or "")
        c.restoreState()
        return
    total = sw(text, font, size) * hsc
    if total > sd["x1"] > 0:
        # У дуги нет «следующей строки»: что не влезло, ушло бы по
        # продолжению пути за конец кольца. Кегль уменьшается до длины
        # дуги, не ниже `CURVE_MIN_SHARE`.
        size = max(size * CURVE_MIN_SHARE, size * sd["x1"] / total)
        total = sw(text, font, size) * hsc
    s = max(0.0, (sd["x1"] - total) / 2.0)
    for ch in text:
        adv = sw(ch, font, size) * hsc
        x, y, ang = _path_at(sd, s + adv / 2.0)
        # Буква ставится началом, а угол — по середине её участка пути.
        bx, by, _a = _path_at(sd, s)
        c.saveState()
        c.translate(bx, by)
        c.rotate(ang)
        if raster is not None:
            raster.put(c, 0, 0, ch, size, color, hsc, sd.get("style") or "")
            c.restoreState()
            s += adv
            continue
        to = c.beginText(0, 0)
        to.setFont(font, size)
        if hsc < 0.999:
            to.setHorizScale(hsc * 100.0)
        to.textOut(ch)
        c.drawText(to)
        c.restoreState()
        s += adv


def _neighbour_limits(slots: list) -> None:
    """Правый рубеж каждой строки: начало БЛИЖАЙШЕЙ строки текстового слоя
    справа на той же высоте (`lim`). Конец строки — оценка, и у заголовка
    в одну строку-кусок она уезжала в соседнюю колонку (промежуток 14 пт
    при кегле 15 — меньше порога пробела у `_ink_end`): закраска стирала
    колонку авторов. Где начинается соседняя строка, PDF знает точно —
    дальше неё строка не тянется. Считается по ВСЕМ строкам страницы,
    в том числе без перевода: чужая колонка остаётся оригиналом, и стирать
    её нельзя тем более. Без numpy — рубежа нет, как прежде."""
    if len(slots) < 2:
        return
    try:
        import numpy as np
    except ImportError:
        return
    x0 = np.array([sl["x"] for sl in slots], dtype=np.float64)
    lo = np.array([sl["y"] - 0.2 * sl["size"] for sl in slots], dtype=np.float64)
    hi = np.array([sl["y"] + 0.7 * sl["size"] for sl in slots], dtype=np.float64)
    for k, sl in enumerate(slots):
        # Перекрытие по высоте — заметное, а не касание: у подписи с тесным
        # интерлиньяжем (межстрочный меньше кегля) полосы соседних строк
        # касаются, и строка ниже, выключенная по центру, «обрезала» верхнюю —
        # хвост оригинала оставался рядом с переводом.
        ov = np.minimum(hi, hi[k]) - np.maximum(lo, lo[k])
        m = (x0 > sl["x"] + 0.5 * sl["size"]) & (ov > 0.3 * sl["size"])
        if m.any():
            sl["lim"] = float(x0[m].min())


def _slot_align(slots: list) -> str:
    """«left» / «center» / «right» — как стояли строки оригинала. Подписи
    в схеме и заголовки бывают выключены по центру, и перевод, начатый
    от левого края, съезжал бы с места. Решают края САМИХ строк: левые
    края гуляют, а середины совпадают — центр; совпадают правые — вправо.
    Одна строка — влево: решать не по чему."""
    if len(slots) < 2:
        return "left"
    size = statistics.median(sl["size"] for sl in slots) or 1.0

    def spread(vals):
        return max(vals) - min(vals)
    lefts = spread([sl["x"] for sl in slots])
    if lefts <= 1.0 * size:
        return "left"
    # Отступ первой строки или висячий отступ выключенного по формату
    # абзаца: все строки, кроме первой, с одного края, первая — на несколько
    # кеглей правее или левее, правые края совпадают. Это «влево» с отступом,
    # а не «вправо»: иначе короткая последняя строка перевода уехала бы
    # к правому полю.
    xs = [sl["x"] for sl in slots]
    full = slots[:-1] if len(slots) >= 3 else slots
    if (spread(xs[1:]) <= 1.0 * size and abs(xs[0] - min(xs[1:])) <= 4.0 * size
            and spread([sl["x1"] for sl in full]) <= 1.0 * size):
        return "left"
    if spread([(sl["x"] + sl["x1"]) / 2.0 for sl in slots]) <= 0.5 * lefts:
        return "center"
    if spread([sl["x1"] for sl in slots]) <= 0.5 * lefts:
        return "right"
    return "left"


def _scattered(slots: list) -> bool:
    """Места абзаца — не колонка строк, а РАЗБРОС по странице: подписи
    в схеме, куски инфографики, склеенные разбором в один абзац. Признаки:
    кегль строк расходится больше чем на треть, строка уходит ВВЕРХ чаще
    одного раза (одна — законный переход в следующую колонку) или между
    соседними строками зазор в три строки и больше."""
    if len(slots) < 2:
        return False
    sizes = [sl["size"] for sl in slots]
    if max(sizes) > 1.35 * max(1.0, min(sizes)):
        return True
    ups = 0
    for a, b in zip(slots, slots[1:]):
        if a["page"] != b["page"]:
            continue
        lead = 1.2 * max(a["size"], b["size"])
        dy = a["y"] - b["y"]
        if dy < -0.3 * lead:
            ups += 1
        elif dy > 3.0 * lead:
            # Большой зазор в ТОЙ ЖЕ колонке (абзац, разорванный рисунком) —
            # не разброс: кегль у его строк обязан остаться одним.
            s_ = max(a["size"], b["size"])
            same_col = (abs(a["x"] - b["x"]) <= 1.0 * s_
                        and min(a["x1"], b["x1"]) - max(a["x"], b["x"])
                        >= 0.5 * min(a["x1"] - a["x"], b["x1"] - b["x"]))
            if not same_col:
                return True
    return ups > 1


def _graphemes(text: str) -> list:
    """Знаки письма без пробелов — с огласовками, вирамой и соединителями
    при своей букве (резать между ними нельзя, `_cut_point`)."""
    out: list = []
    for k, ch in enumerate(text):
        if out and k and _cut_point(text, k) != k:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _spread(text: str, slots: list, sw, font_of, nospace: bool = False) -> tuple:
    """([строка на место], [множитель кегля], [сужение]) для РАЗБРОСАННОГО
    абзаца (`_scattered`).

    Жадное заполнение по порядку уводило слова не в свои блоки: подпись
    «24 HOURS» получала середину чужого абзаца крупным кеглем. Здесь каждое
    место получает долю перевода ПО ДОЛЕ ОРИГИНАЛА в нём (знаков `n`), то
    есть подпись остаётся у своего блока, — и каждое место ужимается само:
    у подписей схемы кегли и так разные. Мест без счёта знаков — делим
    поровну."""
    words = (text or "").split()
    sep = " "
    if nospace and len(words) < len(slots):
        # Письмо без пробелов: слова не выделить — делим по знакам.
        words, sep = _graphemes("".join(words)), ""
    n = len(slots)
    weights = [max(1, sl.get("n") or 0) for sl in slots]
    total_w = float(sum(weights))
    total_t = float(sum(len(w) + 1 for w in words)) or 1.0
    lines = [[] for _ in range(n)]
    j, done, cum = 0, 0.0, weights[0] / total_w * total_t
    for w in words:
        # Слово уходит в следующее место, когда его СЕРЕДИНА перешла долю
        # текущего места (и места ещё есть).
        while j < n - 1 and done + (len(w) + 1) / 2.0 > cum:
            j += 1
            cum += weights[j] / total_w * total_t
        lines[j].append(w)
        done += len(w) + 1
    out, fs, hss = [], [], []
    for sl, ws in zip(slots, lines):
        line = sep.join(ws)
        out.append(line)
        width = max(1.0, sl["x1"] - sl["x0"])
        need = sw(line, font_of(sl), sl["size"]) if line else 0.0
        if need <= width:
            fs.append(1.0)
            hss.append(1.0)
        elif need * HSCALE_MIN <= width:
            fs.append(1.0)
            hss.append(width / need)
        else:
            hss.append(HSCALE_MIN)
            fs.append(max(MIN_SIZE_SHARE, width / (need * HSCALE_MIN)))
    return out, fs, hss


def _cut_point(word: str, n: int) -> int:
    """Граница разреза слова не посреди БУКВЫ: огласовка, знак ударения,
    вирама и соединитель остаются со своей буквой."""
    import unicodedata
    while 1 < n < len(word) and (unicodedata.category(word[n]).startswith("M")
                                 or word[n] in "\u200c\u200d"
                                 or "VIRAMA" in unicodedata.name(word[n - 1], "")):
        n -= 1
    return max(1, n)


def _slot_width(sl: dict, align: str, wide: bool) -> float:
    """Ширина места строки: своя — или с запасом свободной бумаги
    (`room0`/`room1`, `_free_room`) в сторону, куда строка растёт по выключке."""
    x0 = sl["x"] if align == "left" else sl["x0"]
    x1 = sl["x1"]
    if wide:
        r0, r1 = sl.get("room0", sl["x0"]), sl.get("room1", sl["x1"])
        if align == "left":
            x1 = max(x1, r1)
        elif align == "right":
            x0 = min(x0, r0)
        else:
            e = max(0.0, min(r1 - x1, x0 - r0))
            x0, x1 = x0 - e, x1 + e
    return x1 - x0


def _fit_slots(text: str, slots: list, sw, font_of, align: str, split_ok: bool = False,
               cap: float = 1.0, floor: "float | None" = None) -> tuple:
    """([строка на каждое место], множитель кегля, не влезшие слова,
    сужение по горизонтали).

    Перевод встаёт в МЕСТА строк оригинала по порядку: каждая строка — своей
    ширины, своего кегля и на своей базовой линии. Не влез — сперва строка
    получает СВОБОДНУЮ бумагу рядом (`room0`/`room1`: у подписи в схеме
    справа часто пусто, и ужимать её до двух пунктов незачем), потом
    сужается начертание (`HSCALE_MIN`), потом кегль всех строк абзаца
    уменьшается одним множителем (разный кегль у строк одного абзаца
    читается как брак), не ниже `floor` (`MIN_SIZE_SHARE`); что не влезло
    и тогда — печатается строками под последним местом, а не теряется.

    `cap` — кегль не крупнее этой доли: общий кегль КЛАССА надписей
    (`_harmonize`) — у соседних надписей одного стиля он один."""
    words0 = (text or "").split()
    # Узкое начертание оригинала («c», DIN Condensed и соседи) — перевод
    # сжат с самого начала, у всех таких строк одинаково.
    h0 = HSCALE_COND if any("c" in (sl.get("style") or "") for sl in slots) else 1.0
    hs = [h0]
    floor = MIN_SIZE_SHARE if floor is None else floor
    cap = max(floor, min(1.0, cap))

    def lay(f, split=False, wide=False):
        words = list(words0)
        out, k, ok = [], 0, True
        for sl in slots:
            font, size = font_of(sl), max(1.0, sl["size"] * f)
            width = _slot_width(sl, align, wide)
            cur = ""
            while k < len(words):
                probe = (cur + " " + words[k]) if cur else words[k]
                if sw(probe, font, size) * hs[0] <= width:
                    cur, k = probe, k + 1
                elif not cur:
                    w_ = words[k]
                    if split and len(w_) > 1:
                        # Слово длиннее строки и на самом мелком кегле (адрес,
                        # составное слово, текст без пробелов): режем по
                        # знакам, остаток — следующей строкой. Не влезший
                        # хвост хуже разрезанного слова.
                        n = len(w_) - 1
                        while n > 1 and sw(w_[:n], font, size) * hs[0] > width:
                            n -= 1
                        n = _cut_point(w_, n)
                        cur = w_[:n]
                        words[k] = w_[n:]
                        break
                    # Переносов по слогам мы не умеем — ставим как есть,
                    # но кегль ещё поищем.
                    cur, k, ok = w_, k + 1, False
                    break
                else:
                    break
            out.append(cur)
        return out, words[k:], ok and k >= len(words)

    # Письмо без пробелов (`split_ok`) режется по знакам на ЛЮБОМ кегле:
    # иначе вся строка вставала в первое место (не влезло ни одно «слово»),
    # остальные пустели, и кегль падал до самого мелкого.
    lines, rest, fits = lay(cap, split_ok)
    if fits:
        return lines, cap, [], h0
    # Запас бумаги — только подписи (короткий абзац узких строк): у колонки
    # текста книги справа ПОЛЕ страницы, и абзац, не влезший в строки, ушёл
    # бы на поля вместо того, чтобы сжаться.
    label = len(slots) <= FREE_MAX_LINES and all(
        (sl["x1"] - sl["x0"]) <= FREE_MAX_WIDTH * sl.get("_pw", 1e9) for sl in slots)
    wide = label and any(sl.get("room1", sl["x1"]) > sl["x1"] + 0.5
                         or sl.get("room0", sl["x0"]) < sl["x0"] - 0.5 for sl in slots)
    if wide:
        lines, rest, fits = lay(cap, split_ok, True)
        if fits:
            return lines, cap, [], h0
    # Сперва — сужение при прежнем кегле.
    hmin = h0 * HSCALE_MIN
    hs[0] = hmin
    got, _rest, ok = lay(cap, split_ok, wide)
    if ok:
        lo, hi, best = hmin, h0, got            # lo влезает, hi — нет
        for _ in range(6):
            mid = (lo + hi) / 2.0
            hs[0] = mid
            got, _rest, ok = lay(cap, split_ok, wide)
            if ok:
                lo, best = mid, got
            else:
                hi = mid
        return best, cap, [], lo
    # Сужения мало — уменьшаем и кегль, при самом узком начертании.
    hs[0] = hmin
    lo_lines, lo_rest, lo_fits = lay(floor, split_ok, wide)
    if not lo_fits:
        if split_ok or len(words0) < len(slots):
            # Слов меньше, чем строк, — текст без пробелов (или почти):
            # режем по знакам, иначе всё встало бы в первую строку, а
            # остальные остались бы пустыми. Подпись из одного слова не
            # режем: целое слово, вылезшее вправо, читается лучше обрубков.
            lo_lines, lo_rest, _ok = lay(floor, True, wide)
        return lo_lines, floor, lo_rest, hmin
    lo, hi = floor, cap                         # lo влезает, hi — нет
    best = (lo_lines, lo)
    for _ in range(8):
        mid = (lo + hi) / 2.0
        got, _rest, ok = lay(mid, split_ok, wide)
        if ok:
            lo, best = mid, (got, mid)
        else:
            hi = mid
    return best[0], best[1], [], hmin


# Общий кегль класса надписей (`_harmonize`): класс от стольких абзацев,
# кегль — такой квантиль нужных им множителей.
HARMONY_MIN = int(os.environ.get("LAYOUT_HARMONY_MIN", "3"))
HARMONY_Q = float(os.environ.get("LAYOUT_HARMONY_Q", "0.25"))
HARMONY_FLOOR = float(os.environ.get("LAYOUT_HARMONY_FLOOR", "0.6"))
HARMONY_Q_MIN = int(os.environ.get("LAYOUT_HARMONY_Q_MIN", "8"))
# Пол кегля, до которого ужимается абзац, налезший на чужой текст.
FLOOR_HARD = float(os.environ.get("LAYOUT_FLOOR_HARD", "0.4"))


def _refit(slot_plan: list, slot_meta: list, i: int, cap: float = 1.0,
           floor: "float | None" = None, wide: bool = True) -> None:
    sds, _lines, _fs, _rest, font_of, align, _hss = slot_plan[i]
    m = slot_meta[i]
    if not wide:
        for sd in sds:
            sd.pop("room0", None)
            sd.pop("room1", None)
    lines, f, rest, hsc = _fit_slots(m["text"], sds, m["sw"], font_of, align, m["nospace"],
                                     cap=cap, floor=floor)
    slot_plan[i] = (sds, lines, [f] * len(sds), rest, font_of, align, [hsc] * len(sds))


def _harmonize(slot_plan: list, slot_meta: list, stats: dict) -> None:
    """Один кегль у надписей ОДНОГО стиля на странице.

    Каждый абзац ужимался сам, и соседние надписи инфографики одного стиля
    выходили 4.2 и 2.3 пт, а абзац колонки — мельче соседних: на глаз это
    брак набора. Класс — гарнитура, начертание и кегль ОРИГИНАЛА; кегль
    класса — нижний квартиль того, что нужно его абзацам (`HARMONY_Q`):
    большинство влезает при нём, кто влезал крупнее — становится им, а кому
    нужно ещё мельче (выброс), ужимается сам и называется числом
    (`harmonyOutliers`)."""
    classes: dict = {}
    for i, (sds, _l, fs, _r, _fo, _a, _h) in enumerate(slot_plan):
        m = slot_meta[i]
        if m["scattered"] or any(sd.get("rot") for sd in sds):
            continue
        # Класс — В ПРЕДЕЛАХ СТРАНИЦЫ: подпись в таблице и подпись в схеме
        # соседней страницы одного кегля оригинала, но глазами их рядом не
        # сравнивают, а общий квартиль ужимал бы короткие ячейки таблицы
        # («Метформин») под тесноту чужой инфографики.
        key = (int(sds[0]["page"]), m["fam"], _face_style(sds[0].get("style") or ""),
               "c" in (sds[0].get("style") or ""), round(sds[0]["size"] * 2) / 2.0)
        classes.setdefault(key, []).append(i)
    changed = outliers = 0
    for idxs in classes.values():
        if len(idxs) < HARMONY_MIN:
            continue
        fv = sorted(slot_plan[i][2][0] for i in idxs)
        # Не мельче `HARMONY_FLOOR`: класс не тянется вниз за горсткой
        # абзацев, которым тесно, — они ужимаются сами и называются числом.
        # У маленького класса квартиль — это его минимум (один тесный абзац
        # ужал бы всю страницу), поэтому там — медиана.
        q = HARMONY_Q if len(fv) >= HARMONY_Q_MIN else 0.5
        target = max(fv[int(q * (len(fv) - 1))], HARMONY_FLOOR)
        for i in idxs:
            f = slot_plan[i][2][0]
            if f > target + 0.02:
                _refit(slot_plan, slot_meta, i, cap=target)
                changed += 1
            elif f < target - 0.02:
                outliers += 1
    stats["harmonized"] = changed
    stats["harmonyOutliers"] = outliers


def _entry_rects(entry: tuple, sw) -> list:
    """Прямоугольники НАПЕЧАТАННЫХ строк абзаца: [(стр., x0, y0, x1, y1, кегль,
    вылез ли за своё место)] — по тем же правилам, что печать."""
    sds, lines, fs, rest, font_of, align, hss = entry
    out = []
    for k, (sd, line) in enumerate(zip(sds, lines)):
        if sd.get("rot"):
            continue
        last = k == len(sds) - 1
        size = max(1.0, sd["size"] * fs[k])
        font = font_of(sd)
        more = list(_overflow_lines(rest, sd, size, sw, font, align, hss[k])) if last and rest else []
        for j, ln in enumerate([line] + more):
            if not ln:
                continue
            w = sw(ln, font, size) * hss[k]
            if align == "center":
                x = (sd["x0"] + sd["x1"]) / 2.0 - w / 2.0
            elif align == "right":
                x = sd["x1"] - w
            else:
                x = sd["x"]
            y = sd["y"] - j * 1.2 * size
            grown = j > 0 or x + w > sd["x1"] + 0.5 or x < sd["x0"] - 0.5
            out.append((int(sd["page"]), x, y - 0.25 * size, x + w, y + 0.85 * size, size, grown))
    return out


def _overlap(a: tuple, b: tuple) -> bool:
    s = min(a[5], b[5])
    ix = min(a[3], b[3]) - max(a[1], b[1])
    iy = min(a[4], b[4]) - max(a[2], b[2])
    return ix > 0.25 * s and iy > 0.3 * min(a[4] - a[2], b[4] - b[2])


def _resolve_collisions(slot_plan: list, slot_meta: list, jobs: list,
                        reader, skip: set, stats: dict) -> None:
    """Проверка наложений ДО печати — и починка.

    Строка перевода, вылезшая за своё место (на свободную бумагу или хвостом
    под последней строкой), не вправе лечь на чужой текст: на перевод соседа,
    на оставленный оригинал (абзац без перевода) или за край листа. Нашли —
    абзац теряет запас бумаги, потом ужимается до `FLOOR_HARD`; не помогло —
    наложение остаётся и НАЗЫВАЕТСЯ (`collisions`, страницы, абзацы): сборка
    не вправе отчитаться «готово», не сказав о нём. Наложения, которые были
    в самом оригинале (обе строки на своих местах), не наши и не считаются."""
    fixed: list = []                    # чужие прямоугольники: оставленный оригинал
    for key, text, boxes in jobs:
        if text:
            continue
        for b in boxes or []:
            if int(b["page"]) in skip:
                continue
            for sd in b.get("_slots") or []:
                if sd.get("rot"):
                    continue
                fixed.append(((int(sd["page"]), sd["x0"], sd["y"] - 0.25 * sd["size"], sd["x1"],
                               sd["y"] + 0.85 * sd["size"], sd["size"], False), ("o", key)))
    edges = {}
    for i, page in enumerate(reader.pages):
        try:
            mb = page.mediabox
            edges[i] = (float(mb.left), float(mb.bottom), float(mb.right), float(mb.top))
        except Exception:
            pass

    def find():
        rects = list(fixed)
        for i, entry in enumerate(slot_plan):
            rects.extend((r, ("s", i)) for r in _entry_rects(entry, slot_meta[i]["sw"]))
        by_page: dict = {}
        for r, who in rects:
            by_page.setdefault(r[0], []).append((r, who))
        hits = []
        for pg, items in by_page.items():
            items.sort(key=lambda t: t[0][2])
            e = edges.get(pg)
            for k, (a, wa) in enumerate(items):
                if e and a[6] and (a[1] < e[0] - 0.5 or a[3] > e[2] + 0.5 or a[2] < e[1] - 0.5):
                    hits.append((pg, wa, ("edge", pg)))
                for b, wb in items[k + 1:]:
                    if b[2] >= a[4]:
                        break
                    if wa == wb or not (a[6] or b[6]):
                        continue
                    if _overlap(a, b):
                        hits.append((pg, wa if a[6] else wb, wb if a[6] else wa))
        return hits

    fixed_n = 0
    for _round in range(3):
        hits = find()
        # Разбросанные подписи (`_spread`) раскладываются по ДОЛЕ оригинала
        # в каждом месте — последовательная укладка `_fit_slots` раздала бы
        # им чужой текст; их не переукладываем, а называем.
        todo = {who[1] for _pg, who, _other in hits
                if who[0] == "s" and not slot_meta[who[1]]["scattered"]}
        if not todo:
            break
        for i in todo:
            sds = slot_plan[i][0]
            f = slot_plan[i][2][0]
            if any("room0" in sd or "room1" in sd for sd in sds):
                _refit(slot_plan, slot_meta, i, cap=f, wide=False)
            elif slot_plan[i][3] or f > FLOOR_HARD:
                _refit(slot_plan, slot_meta, i, cap=f, floor=FLOOR_HARD, wide=False)
        fixed_n += len(todo)
    hits = find()
    paras = sorted({slot_meta[who[1]]["idx"] for _pg, who, _o in hits if who[0] == "s"},
                   key=lambda v: str(v))
    stats["collisionFixed"] = fixed_n
    stats["collisions"] = len(paras)
    stats["collisionPages"] = sorted({pg + 1 for pg, _w, _o in hits})[:50]
    stats["collisionParas"] = paras[:200]
    stats["grown"] = sum(1 for i, entry in enumerate(slot_plan)
                         if any(r[6] for r in _entry_rects(entry, slot_meta[i]["sw"])))


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
            with PDFIUM_LOCK:
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
        with PDFIUM_LOCK:
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
                # Потолок площади: MediaBox бывает до 14 400 пт, и при 144
                # точках на дюйм это сотни мегапикселей в памяти единственного
                # воркера. Масштаб — на страницу; читатели берут его из снимка.
                scale = self.scale
                try:
                    pw, ph = page.get_size()
                    px = (pw * scale) * (ph * scale)
                    if SAMPLE_MAX_MPX > 0 and px > SAMPLE_MAX_MPX * 1e6:
                        scale *= (SAMPLE_MAX_MPX * 1e6 / px) ** 0.5
                except Exception:
                    pass
                im = page.render(scale=max(0.05, scale)).to_pil().convert("RGB")
                sample = (im, max(0.05, scale), cb, im.convert("L"))
                page.close()
            except Exception:
                sample = None
        if sample is None:
            self.missed.add(i)
        self.cur = (i, sample)
        return sample

    def close(self):
        """Документ закрывается ЯВНО и сразу, а не сборщиком мусора.

        Брошенный документ pdfium прибирает финализатор — в произвольный
        момент и в произвольном потоке, в том числе посреди чужой отрисовки:
        на боевом сервере это роняло весь процесс через полминуты после
        последнего запроса. Повторный вызов безвреден: снимок и ссылка
        снимаются до закрытия."""
        doc, self.doc, self.cur = self.doc, None, (None, None)
        if doc is None:
            return
        with PDFIUM_LOCK:
            try:
                doc.close()
            except Exception:
                pass


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


LIGHT_INK = 60.0                 # светлее тёмной бумаги на столько — светлая краска
INV_PAPER = 0.7                  # бумага темнее этого — на ней бывает светлая краска


def _ink_cols(gray, x0, x1, y0, y1, paper: float) -> list:
    """Столбцы полосы для поиска КРАСКИ: самый тёмный пиксель, а на тёмной
    бумаге (`INV_PAPER`: цветная плашка) столбец со светлой краской (белый заголовок на
    красной плашке) считается краской тоже — ноль. Иначе конец светлой
    строки не находился, и хвост оригинала оставался рядом с переводом."""
    mins = _col_mins(gray, x0, x1, y0, y1)
    if paper >= INV_PAPER or not mins:
        return mins
    light = paper * 255.0 + LIGHT_INK
    maxs = _col_maxs(gray, x0, x1, y0, y1)
    return [0 if u > light else v for v, u in zip(mins, maxs)]


def _col_maxs(gray, x0: int, x1: int, y0: int, y1: int) -> list:
    """Самый светлый пиксель каждого столбца полосы — граница цветной плашки."""
    x0, x1 = max(0, int(x0)), min(gray.size[0], int(x1))
    y0, y1 = max(0, int(y0)), min(gray.size[1], int(y1))
    w, h = x1 - x0, y1 - y0
    if w < 1 or h < 1:
        return []
    data = gray.crop((x0, y0, x1, y1)).tobytes()
    try:
        import numpy as np
        return np.frombuffer(data, dtype=np.uint8).reshape(h, w).max(axis=0).tolist()
    except Exception:
        out = [0] * w
        for r in range(h):
            row = data[r * w:(r + 1) * w]
            for c in range(w):
                if row[c] > out[c]:
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
    mins = _ink_cols(gray, right, right + limit, y0, y1, paper)
    run, reach = 0, 0
    for k, v in enumerate(mins):
        if v < dark:
            run, reach = 0, k + 1
        else:
            run += 1
            if run >= gap:
                break
    x1 = x1 + reach / scale if reach else x1
    # Влево раздвигаем куда МЕНЬШЕ, чем вправо, и это не осторожность,
    # а устройство дефекта: ширина знака оценивается, и ошибка копится
    # к КОНЦУ строки — начало её текстовый слой знает точно. Зато слева
    # от заголовка в книге стоит рисованная виньетка (пчела в рамке),
    # и щедрая раздвижка закрашивала её половину. Хватает одного знака:
    # больше там взяться нечему.
    # У строки с началом и концом по метрикам шрифта (`exact`) начало
    # известно ТОЧНО: раздвижка влево там — только на погрешность штриха,
    # иначе заливка срезала значок, стоящий вплотную к подписи схемы.
    left_pt = (INK_EXACT_SLACK * 0.5 if box.get("exact") else INK_LEFT_PT) * size
    mins = _ink_cols(gray, left - min(limit, left_pt * scale), left, y0, y1, paper)
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


# Свободная бумага рядом со строкой: перевод может зайти на неё, если
# не влез в свою ширину (`_fit_slots`). Отступ от чужой краски — столько
# кеглей, запас не меньше столько кеглей, растём не больше чем на ширину
# самой строки.
FREE_MARGIN = float(os.environ.get("LAYOUT_FREE_MARGIN", "2.0"))
FREE_MIN = float(os.environ.get("LAYOUT_FREE_MIN", "1.5"))
FREE_MAX_SHARE = float(os.environ.get("LAYOUT_FREE_MAX_SHARE", "1.0"))
FREE_MAX_LINES = int(os.environ.get("LAYOUT_FREE_MAX_LINES", "3"))
FREE_MAX_WIDTH = float(os.environ.get("LAYOUT_FREE_MAX_WIDTH", "0.35"))
FREE_PAPER_DELTA = 12.0          # светлее бумаги на столько (из 255) — уже другой фон


def _free_room(sample, sd: dict, paper: float) -> None:
    """`room1` / `room0` у места строки — докуда справа и слева от неё
    ЧИСТАЯ бумага (ни краски, ни смены фона) в полосе строки, с отступом
    `FREE_MARGIN` кеглей от первой чужой краски.

    Зачем. Перевод длиннее оригинала, а место строки в инфографике — ровно
    длина английской подписи; прежде такая подпись ужималась до половины
    кегля, и соседние надписи одного стиля выходили разного размера. Рядом
    при этом обычно пусто. Колонку текста это не трогает: в межколоннике
    места меньше, чем `FREE_MARGIN` + `FREE_MIN` кеглей."""
    if not sample:
        return
    im, scale, cb, gray = sample
    W, H = im.size
    sd["_pw"] = max(1.0, cb[2] - cb[0])
    size = max(sd.get("size") or 10.0, 1.0)
    y0 = int(max(0, H - (sd["y"] + 1.0 * size - cb[1]) * scale))
    y1 = int(min(H, H - (sd["y"] - 0.35 * size - cb[1]) * scale + 1))
    if y1 - y0 < 2:
        return
    dark = INK_DARK * paper * 255.0
    margin = FREE_MARGIN * size
    grow = max(FREE_MAX_SHARE * (sd["x1"] - sd["x0"]), 4.0 * size)
    right_cap = cb[2] - margin
    if sd.get("lim") is not None:
        right_cap = min(right_cap, sd["lim"] - margin)
    right_cap = min(right_cap, sd["x1"] + grow + margin)
    light = min(255.0, paper * 255.0 + FREE_PAPER_DELTA)
    start = (sd["x1"] + 0.3 * size - cb[0]) * scale
    mins = _col_mins(gray, start, (right_cap + margin - cb[0]) * scale, y0, y1)
    maxs = _col_maxs(gray, start, (right_cap + margin - cb[0]) * scale, y0, y1)
    # Конец свободного места — краска ИЛИ смена фона: светлая надпись на
    # цветной плашке не вправе выйти за плашку на белую бумагу (её там не
    # видно), и тёмная — на чужую плашку.
    hit = next((k for k, (v, u) in enumerate(zip(mins, maxs)) if v < dark or u > light), None)
    free_to = sd["x1"] + 0.3 * size + (len(mins) if hit is None else hit) / scale - margin
    free_to = min(free_to, right_cap)
    if free_to - sd["x1"] >= FREE_MIN * size:
        sd["room1"] = free_to
    left_cap = max(cb[0] + margin, sd["x0"] - grow - margin)
    end = (sd["x0"] - 0.3 * size - cb[0]) * scale
    mins = _col_mins(gray, (left_cap - margin - cb[0]) * scale, end, y0, y1)
    maxs = _col_maxs(gray, (left_cap - margin - cb[0]) * scale, end, y0, y1)
    hit = next((k for k, (v, u) in enumerate(zip(reversed(mins), reversed(maxs)))
                if v < dark or u > light), None)
    free_from = sd["x0"] - 0.3 * size - (len(mins) if hit is None else hit) / scale + margin
    free_from = max(free_from, left_cap)
    if sd["x0"] - free_from >= FREE_MIN * size:
        sd["room0"] = free_from


def _ink_end(sample, box: dict, paper: float) -> "float | None":
    """Настоящий конец строки по КРАСКЕ — либо None (мерить нечем).

    Конец строки в текстовом слое — либо посчитан по метрикам шрифта
    (`exact`, недосчитывает выключку по формату), либо оценён по средней
    ширине знака (у крупного кегля уезжал за край колонки: заголовок
    «Management of Type 2 Diabetes,» закрашивал колонку авторов). Идём
    вправо по краске — от посчитанного конца либо от начала ПОСЛЕДНЕГО
    куска строки (`xl`, его PDF знает точно) — и останавливаемся на первом
    настоящем пробеле (`INK_GAP_SHARE` кегля). Строку целиком дальше оценки на потолок
    раздвижки не тянем: в схеме за подписью стоит рисунок, и краска
    рисунка — не текст."""
    xl = box.get("xl")
    if not sample or xl is None:
        return None
    im, scale, cb, gray = sample
    W, H = im.size
    size = max(box.get("size") or 10.0, 1.0)
    y0 = int(max(0, H - (box["top"] - cb[1]) * scale))
    y1 = int(min(H, H - (box["bottom"] - cb[1]) * scale + 1))
    if y1 - y0 < 2:
        return None
    est = box["x1"]
    cap = est + min(max(INK_EXPAND_SHARE * (est - box["x0"]), 4 * size), INK_EXPAND_MAX)
    if box.get("exact"):
        # Конец по метрикам шрифта считает и сдвиги TJ, и межбуквенный
        # интервал — дальше него краска строки не уходит больше чем на
        # знак (у отсканированного текста штрих бывает шире метрики).
        # Без потолка раздвижка шла по рамке плашки и стрелке схемы
        # за подписью — заливка цветом рамки выползала на рисунок.
        cap = min(cap, est + INK_EXACT_SLACK * size)
    if box.get("lim") is not None:
        cap = min(cap, box["lim"])
    # Конец, посчитанный по метрикам шрифта, недосчитывает выключку по
    # формату (сдвиги внутри TJ), но НЕ пересчитывает: идём от него и дальше
    # только по краске ВПЛОТНУЮ — хвост слова продолжается без разрыва,
    # а рамка блока или рисунок за подписью отделены пробелом.
    origin = est if box.get("exact") else xl
    start = (origin - cb[0]) * scale
    mins = _ink_cols(gray, start, (cap - cb[0]) * scale, y0, y1, paper)
    if not mins:
        return None
    dark = INK_DARK * paper * 255.0
    gap = max(1, int(round(INK_GAP_SHARE * size * scale)))
    run, reach = 0, 0
    # Широкий пробел ВНУТРИ строки («4  Consensus Report»: номер страницы
    # и колонтитул одним куском) — ещё не конец: от начала строки пробел
    # останавливает поиск, только когда пройдено больше `INK_INNER_SHARE`
    # оценки её длины. Иначе место строки кончалось на «4», и перевод шёл
    # хвостом под колонтитул, а сам колонтитул оставался незакрашенным.
    inner = 0 if box.get("exact") else int(INK_INNER_SHARE * max(0.0, est - origin) * scale)
    for k, v in enumerate(mins):
        if v < dark:
            run, reach = 0, k + 1
        else:
            run += 1
            # От точного конца: пробел сразу — хвоста нет, дальше не идём
            # (иначе дошли бы до рисунка за подписью).
            if run >= gap and (reach or box.get("exact")) and k >= inner:
                break
    if not reach:
        return est if box.get("exact") else None
    return max(box["x0"] + 0.5 * size, origin + reach / scale)


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
    try:
        import numpy as np
        gx0, gx1 = max(0, int(x0)), min(W, max(int(x0) + 1, int(x1) + 1))
        gy0, gy1 = max(0, int(y0)), min(H, max(int(y0) + 1, int(y1)))
        if gx1 - gx0 >= 1 and gy1 - gy0 >= 1:
            arr = np.asarray(im.crop((gx0, gy0, gx1, gy1)), dtype=np.uint8)[:, :, :3]
            out = []
            for k in range(n):
                a = max(0, int(x0 + k * step) - gx0)
                b = min(arr.shape[1], max(a + 1, int(x0 + (k + 1) * step) + 1 - gx0))
                px = arr[:, a:b].reshape(-1, 3)
                if not len(px):
                    out.append(out[-1] if out else (1.0, 1.0, 1.0))
                    continue
                srt = np.sort(px, axis=0)
                row = srt[min(len(srt) - 1, int(q * len(srt)))]
                out.append(tuple(float(v) / 255.0 for v in row))
            return out
    except ImportError:
        pass
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


def _overflow_lines(words: list, sd: dict, size: float, sw, font: str, align: str,
                    hsc: float = 1.0):
    """Не влезшие слова — строками той же ширины под последним местом:
    вылезший текст лучше потерянного (инвариант 4)."""
    width = max(1.0, sd["x1"] - (sd["x"] if align == "left" else sd["x0"]))
    cur = ""
    for w in words:
        probe = (cur + " " + w) if cur else w
        if cur and sw(probe, font, size) * hsc > width:
            yield cur
            cur = w
        else:
            cur = probe
    if cur:
        yield cur


def _fill_box(c, box: dict, pad: float, colors: list, x0f=None, x1f=None, top_pad=None):
    """Закраска рамки полосами. Полосы кладутся с нахлёстом внутрь, но
    НЕ ЗА правый край: вылезший кусок виден на поле прямоугольником.
    `x0f`/`x1f` — края, раздвинутые по краске (`_ink_box`): закрашиваем
    то, что на странице НАПЕЧАТАНО, а не то, что насчитал текстовый слой."""
    bx0 = box["x0"] if x0f is None else x0f
    bx1 = box["x1"] if x1f is None else x1f
    tp = pad if top_pad is None else top_pad
    x0, y0 = bx0 - pad, box["bottom"] - pad
    w, h = (bx1 - bx0) + 2 * pad, (box["top"] - box["bottom"]) + pad + tp
    n = max(1, len(colors))
    step = w / float(n)
    for k, col in enumerate(colors):
        left = x0 + k * step
        right = min(x0 + w, left + step * 1.6)
        c.setFillColorRGB(*col)
        c.rect(left, y0, right - left, h, stroke=0, fill=1)


def _shaped_script(texts: dict) -> str:
    """Письменность перевода, которой нужна СБОРКА букв (справа налево,
    лигатуры, огласовки), — либо «»."""
    import unicodedata
    for t in texts.values():
        for ch in (t or ""):
            o = ord(ch)
            if o < 0x0590 or unicodedata.category(ch) == "Cf":
                continue                # метки направления (RLM, ALM) — не письмо
            if unicodedata.bidirectional(ch) in ("R", "AL"):
                return "письмо справа налево"
            if (0x0900 <= o <= 0x0DFF or 0x0E00 <= o <= 0x0EFF or 0x0F00 <= o <= 0x0FFF
                    or 0x1000 <= o <= 0x109F or 0x1780 <= o <= 0x17FF):
                return "письмо со сборкой букв"
    return ""


def _nospace_script(texts: dict) -> bool:
    """В переводе письмо БЕЗ пробелов между словами (иероглифы, кана,
    тайское, лаосское, кхмерское, бирманское): строку режем по знакам."""
    for t in texts.values():
        for ch in (t or ""):
            o = ord(ch)
            if (0x0E00 <= o <= 0x0EFF or 0x1000 <= o <= 0x109F or 0x1780 <= o <= 0x17FF
                    or 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF
                    or 0xF900 <= o <= 0xFAFF):
                return True
    return False


class _Raster:
    """Печать строки КАРТИНКОЙ через Pillow (+ raqm — сборка букв, письмо
    справа налево) — для письменностей, которые reportlab не собирает
    (арабица, иврит, индийские, тайское, кхмерское, бирманское) и для
    шрифтов, которых у reportlab нет (иероглифы — только в OTF/CFF).

    Шрифт — из репозитория (те же Noto, что у субтитров видео), по буквам:
    у каждого знака свой файл (`runs`) — в шрифтах письменностей Noto нет
    латиницы и цифр, и «COVID-19» в арабской строке иначе стал бы квадратами.
    Строка справа налево — куски в обратном порядке, внутри куска порядок
    и сборку делает raqm."""

    SCALE = 4.0                         # пикселей на пункт (≈ 288 точек на дюйм)

    def __init__(self, chars: set):
        from PIL import features
        from fontTools.ttLib import TTFont
        self.raqm = bool(features.check("raqm"))
        self.cmaps: dict = {}
        files = sorted(p for p in Path(_REPO_FONTS).glob("*")
                       if p.suffix.lower() in (".ttf", ".otf") and "Bold" not in p.name)
        for p in files:
            try:
                self.cmaps[str(p)] = set(TTFont(str(p), lazy=True).getBestCmap() or {})
            except Exception:
                continue
        hard = [ord(ch) for ch in chars if ord(ch) > 0x2FF and not ch.isspace()]
        self.latin = next((p for p in self.cmaps if p.endswith("NotoSans-Regular.ttf")),
                          next(iter(self.cmaps), ""))
        # Основной — тот, что знает больше букв перевода; при равенстве —
        # шрифт САМОЙ письменности (Noto, у́же по набору знаков): он рисует её
        # лучше универсального DejaVu.
        def rank(item):
            p, cm = item
            return (sum(1 for o in hard if o in cm), "Noto" in p, -len(cm))
        self.primary = max(self.cmaps.items(), key=rank)[0] if self.cmaps else self.latin
        self.missing = sum(1 for o in set(hard) if o not in self.cmaps.get(self.primary, set())
                           and o not in self.cmaps.get(self.latin, set()))
        self._fonts: dict = {}

    def _font(self, path: str, size: float, bold: bool = False):
        from PIL import ImageFont
        px = max(1, int(round(size * self.SCALE)))
        bpath = path.replace("-Regular.", "-Bold.") if bold else path
        if bold and not Path(bpath).exists():
            bpath = path
        key = (bpath, px)
        if key not in self._fonts:
            eng = ImageFont.Layout.RAQM if self.raqm else ImageFont.Layout.BASIC
            self._fonts[key] = ImageFont.truetype(bpath, px, layout_engine=eng)
        return self._fonts[key], bpath != path

    def _path_of(self, ch: str, prev: str) -> str:
        import unicodedata
        o = ord(ch)
        if ch.isspace() or unicodedata.category(ch)[0] in "PZM" and prev:
            return prev
        if o in self.cmaps.get(self.primary, set()):
            return self.primary
        if o in self.cmaps.get(self.latin, set()):
            return self.latin
        return self.primary

    def runs(self, text: str, base_rtl: "bool | None" = None) -> list:
        """[(файл, кусок, справа-налево)] в ВИДИМОМ порядке слева направо.

        Уровни встраивания — упрощённый алгоритм Юникода (`_bidi_levels`):
        цифры внутри письма справа налево идут слева направо, нейтральные
        знаки берут сторону соседей. Строка режется на куски одного уровня
        и одного шрифта (у каждого знака шрифт, который его знает), куски
        переставляются по уровням, а внутри куска справа налево порядок
        и сборку букв делает raqm."""
        if not text:
            return []
        levels = _bidi_levels(text, base_rtl)
        logical: list = []
        prev = ""
        for ch, lv in zip(text, levels):
            path = self._path_of(ch, prev)
            prev = path
            if logical and logical[-1][0] == path and logical[-1][2] == lv:
                logical[-1][1] += ch
            else:
                logical.append([path, ch, lv])
        top = max(r[2] for r in logical)
        lo_odd = min((r[2] for r in logical if r[2] % 2), default=top + 1)
        for k in range(top, lo_odd - 1, -1):
            i = 0
            while i < len(logical):
                if logical[i][2] >= k:
                    j = i
                    while j < len(logical) and logical[j][2] >= k:
                        j += 1
                    logical[i:j] = logical[i:j][::-1]
                    i = j
                else:
                    i += 1
        return [(p_, t_, bool(lv % 2)) for p_, t_, lv in logical]

    @staticmethod
    def rtl(text: str) -> bool:
        import unicodedata
        for ch in text:
            b = unicodedata.bidirectional(ch)
            if b in ("R", "AL"):
                return True
            if b == "L":
                return False
        return False

    def _len(self, path, t, size, rtl, bold=False):
        f, _b = self._font(path, size, bold)
        kw = {"direction": "rtl" if rtl else "ltr"} if self.raqm else {}
        return f.getlength(t, **kw)

    def measure(self, text: str, _font=None, size: float = 10.0) -> float:
        """Ширина строки — ТЕМ ЖЕ файлом, каким она будет нарисована: у
        полужирного (по имени шрифта reportlab) — Bold-файлом; меряй
        обычным, а рисуй жирным — строка вылезала бы за своё место."""
        bold = _font_is_bold(_font)
        return sum(self._len(p, t, size, r, bold) for p, t, r in self.runs(text)) / self.SCALE

    def put(self, c, x: float, y: float, text: str, size: float, color, hsc: float = 1.0,
            style: str = "", base_rtl: "bool | None" = None) -> None:
        from PIL import Image, ImageDraw
        from reportlab.lib.utils import ImageReader
        bold = "b" in (style or "")
        runs = self.runs(text, base_rtl)
        rgba = tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in color[:3]) + (255,)
        cursor = x
        for path, t, r in runs:
            f, real_bold = self._font(path, size, bold)
            kw = {"direction": "rtl" if r else "ltr"} if self.raqm else {}
            w = f.getlength(t, **kw)
            asc, desc = f.getmetrics()
            pad = 2 + int(size * self.SCALE * 0.05)
            img = Image.new("RGBA", (int(w) + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))
            stroke = (max(1, int(round(size * self.SCALE * 0.03))) if bold and not real_bold else 0)
            ImageDraw.Draw(img).text((pad, pad + asc), t, font=f, fill=rgba, anchor="ls",
                                     stroke_width=stroke, stroke_fill=rgba, **kw)
            wpt, hpt = img.size[0] / self.SCALE * hsc, img.size[1] / self.SCALE
            ox, oy = -pad / self.SCALE * hsc, -(desc + pad) / self.SCALE
            c.saveState()
            c.translate(cursor, y)
            if "i" in (style or ""):
                c.transform(1, 0, 0.21, 1, 0, 0)
            c.drawImage(ImageReader(img), ox, oy, wpt, hpt, mask="auto")
            c.restoreState()
            cursor += w / self.SCALE * hsc


def _font_is_bold(name) -> bool:
    """Полужирное ли начертание просили у шрифта reportlab с этим именем:
    имя — FONT_NAME + семейство + начертание («R», «b», «i», «bi») + 6 знаков
    отпечатка файла (`_register_fonts`)."""
    if not name or not isinstance(name, str) or len(name) < 7:
        return False
    st = name[:-6]
    return st.endswith("b") or st.endswith("bi")


def _bidi_levels(text: str, base_rtl: "bool | None" = None) -> list:
    """Уровни встраивания по упрощённому двунаправленному алгоритму Юникода:
    сильные L/R(AL), цифры (EN/AN — слева направо внутри письма справа
    налево), нейтральные — сторона соседей, если она одна, иначе базовая;
    метки (NSM) — уровень своей буквы. Основа — первый сильный знак строки
    (либо `base_rtl`). Без встраиваний (LRE/RLO…): в переводе их нет."""
    import unicodedata
    cls = [unicodedata.bidirectional(ch) for ch in text]
    if base_rtl is None:
        base_rtl = False
        for c in cls:
            if c in ("R", "AL"):
                base_rtl = True
                break
            if c == "L":
                break
    base = 1 if base_rtl else 0
    n = len(text)
    kind = [None] * n                    # "L" | "R" | "N" | "D" (цифра)
    last_strong = "R" if base else "L"
    for i, c in enumerate(cls):
        if c == "L":
            kind[i] = last_strong = "L"
        elif c in ("R", "AL"):
            kind[i] = last_strong = "R"
        elif c in ("EN", "AN"):
            kind[i] = "D"
        elif c == "NSM" and i:
            kind[i] = kind[i - 1]
        else:
            kind[i] = "N"
    # Цифры: после R — уровень цифр в письме справа налево, иначе как L.
    strong_before = []
    s_ = "R" if base else "L"
    for i in range(n):
        if kind[i] in ("L", "R"):
            s_ = kind[i]
        strong_before.append(s_)
    lv = [base] * n
    for i in range(n):
        k = kind[i]
        if k == "L":
            lv[i] = 2 if base else 0
        elif k == "R":
            lv[i] = 1
        elif k == "D":
            lv[i] = 2 if (base or strong_before[i] == "R") else 0
    # Нейтральные — по соседям (цифры здесь считаются «R» в окружении R).
    i = 0
    while i < n:
        if kind[i] != "N":
            i += 1
            continue
        j = i
        while j < n and kind[j] == "N":
            j += 1

        def side(k_):
            if k_ is None:
                return "R" if base else "L"
            if kind[k_] == "D":
                return "R" if strong_before[k_] == "R" else "L"
            return kind[k_]
        a = side(i - 1 if i > 0 else None)
        b = side(j if j < n else None)
        v = (1 if a == "R" else (2 if base else 0)) if a == b else base
        for t in range(i, j):
            lv[t] = v
        i = j
    return lv


def _unsupported_script(texts: dict) -> str:
    """Письменность перевода, которую печать слоя честно НЕ умеет, — либо «».

    reportlab кладёт глифы по одному, слева направо и без сборки букв:
    арабица и иврит вышли бы задом наперёд и несвязанными, у индийских,
    тайского, кхмерского, бирманского и тибетского огласовки встали бы
    не на свои места. Лучше отказ словами, чем «перевод», который нельзя
    прочесть (а у формата «PDF» есть запасная дорога — печать Word)."""
    import unicodedata
    for t in texts.values():
        for ch in (t or ""):
            o = ord(ch)
            if o < 0x0590:
                continue
            if unicodedata.bidirectional(ch) in ("R", "AL"):
                return "письмо справа налево"
            if (0x0900 <= o <= 0x0DFF or 0x0E00 <= o <= 0x0EFF or 0x0F00 <= o <= 0x0FFF
                    or 0x1000 <= o <= 0x109F or 0x1780 <= o <= 0x17FF):
                return "письмо со сборкой букв (индийские, тайское, кхмерское, бирманское)"
    return ""


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
    all_texts = dict(texts)
    for k, it in enumerate(extra or []):
        all_texts["x%d" % k] = it.get("text") or ""
    chars = set()
    for t in all_texts.values():
        chars.update(ch for ch in (t or "") if not ch.isspace())
    fonts = _register_fonts(chars)
    sw = pdfmetrics.stringWidth
    miss = _missing_glyphs(fonts, all_texts)
    # Письмо со сборкой букв или знаки, которых нет в шрифтах reportlab
    # (иероглифы — только в OTF), печатаются картинкой строки (`_Raster`).
    raster = None
    shaped = _shaped_script(all_texts)
    if shaped or miss > GLYPH_MISS_MAX:
        try:
            raster = _Raster(chars)
        except Exception as e:
            raise NotAvailable("печать письменности перевода недоступна: %s" % e)
        if shaped and not raster.raqm:
            raise NotAvailable("%s — нужна сборка букв (raqm), а Pillow собран без неё" % shaped)
        if raster.missing > GLYPH_MISS_MAX:
            raise NotAvailable("ни один шрифт не знает %d знаков перевода" % raster.missing)
        miss = raster.missing
    sw_vec = sw
    # Картинкой — только АБЗАЦ, которому это нужно (своя письменность со
    # сборкой букв, справа налево или знаки, которых нет в шрифте
    # reportlab). Прежде один знак RLM в одной строке переводил в картинки
    # всю книгу — тяжелее, без выделения текста и чужой гарнитурой.
    try:
        _face = pdfmetrics.getFont(fonts.get("") or FONT_NAME).face
    except Exception:
        _face = None

    def needs_raster(t: str) -> bool:
        if raster is None:
            return False
        import unicodedata
        if _shaped_script({0: "".join(ch for ch in t if unicodedata.category(ch) != "Cf")}):
            return True
        if _face is None:
            return False
        try:
            return any(not ch.isspace() and unicodedata.category(ch) != "Cf"
                       and not _face.charToGlyph.get(ord(ch)) for ch in t)
        except Exception:
            return False
    nospace = _nospace_script(all_texts)
    if raster is None and miss > GLYPH_MISS_MAX:
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
             "glyphMiss": miss, "sans": 0, "serif": 0, "mono": 0, "inked": 0,
             "slotParagraphs": 0, "condensed": 0, "scattered": 0, "raster": 0}

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
    # Места строк — у ВСЕХ рамок страницы, и у тех, что без перевода: по ним
    # считается правый рубеж соседа (`_neighbour_limits`).
    page_slots: dict = {}
    for _idx, _t, boxes in jobs:
        for b in boxes:
            pg = int(b["page"])
            if pg in skip:
                continue
            b["_slots"] = _slot_boxes(b)
            # Строка не шире листа: конец — оценка, и за краем листа ей
            # делать нечего (там поле с чужим текстом).
            try:
                right = float(reader.pages[pg].mediabox.right)
                for sd in b["_slots"]:
                    if not sd.get("rot"):
                        sd["x1"] = max(sd["x"] + 0.5 * sd["size"], min(sd["x1"], right))
            except Exception:
                pass
            page_slots.setdefault(pg, []).extend(sd for sd in b["_slots"] if not sd.get("rot"))
    for sls in page_slots.values():
        _neighbour_limits(sls)

    sampler = _Sampler(pdf_bytes)
    live_boxes: dict = {}
    for idx, text, boxes in jobs:
        if not text or not boxes:
            continue
        for b in boxes:
            pg = int(b["page"])
            if pg not in skip:
                live_boxes.setdefault(pg, []).append(b)
    # Отрисовка идёт ПОД ЗАМКОМ и документ закрывается сразу, как только
    # бумага померена: дальше pdfium не нужен, а брошенный документ
    # прибирал бы сборщик мусора — в чужом потоке и посреди чужой
    # отрисовки (см. backend/pdfium_gate.py). `finally` обязателен:
    # сборка падает и на нашей логике, а документ пережил бы её.
    try:
        for pg in sorted(live_boxes):
            sample = sampler.page(pg)
            for b in live_boxes[pg]:
                sbs = b.get("_slots") or []
                if sbs:
                    # Строка за строкой: бумага, краска до настоящего пробела,
                    # цвет и плотность краски — у каждой своя.
                    for sd in sbs:
                        pad = PAD_SHARE * max(sd["size"], 1.0)
                        if sd.get("rot"):
                            bb = sd["bbox"]
                            colors = _slot_paper(sample, bb, 0.0, 1)
                            paper = (sum(colors[0]) / 3.0) if colors else 1.0
                            sd["_fill"] = (colors, paper, pad)
                            sd["_ink"] = _ink_color(sample, bb, 0.0, paper, either=True)
                            if sd.get("color") is not None:
                                sd["_ink"] = sd["color"]
                            if sd["curved"]:
                                # Под каждой буквой дуги — свой фон (кольцо
                                # схемы переливается цветом), и краска
                                # меряется В КЛЕТКЕ БУКВЫ, а не по рамке всей
                                # дуги: та накрывает само кольцо, и «краской»
                                # выходил цвет кольца — перевод его же цветом
                                # становился невидим. Клетка — вокруг середины
                                # буквы с учётом её угла, иначе на крутом
                                # участке она вылезала за кольцо.
                                cf, light, dark = [], [], []
                                for cell in _arc_cells(sd):
                                    pc = (_slot_paper(sample, cell, 0.0, 1) or [(1, 1, 1)])[0]
                                    cf.append(pc)
                                    ik = _ink_color(sample, cell, 0.0, sum(pc) / 3.0, either=True)
                                    if ik is not None:
                                        (light if sum(ik) > sum(pc) else dark).append(ik)
                                sd["_cfill"] = cf
                                # Краска дуги — одной полярности на всю надпись:
                                # берём ту сторону (светлее или темнее фона),
                                # за которую больше букв, и её середину.
                                inks = light if len(light) > len(dark) else dark
                                if inks and sd.get("color") is None:
                                    inks.sort(key=lambda c_: sum(c_))
                                    sd["_ink"] = inks[len(inks) // 2]
                            continue
                        lim = sd.get("lim")
                        if lim is not None and sd["x1"] > lim - 0.5 * pad:
                            sd["x1"] = max(sd["x"] + 0.5 * sd["size"], lim - 0.5 * pad)
                        colors = _slot_paper(sample, sd, pad, SLOT_STRIPS)
                        paper = (sum(sum(col) / 3.0 for col in colors) / len(colors)
                                 if colors else 1.0)
                        # Конец строки — по краске от начала её последнего
                        # куска (`_ink_end`); слева — прежняя раздвижка.
                        end = _ink_end(sample, sd, paper)
                        if end is not None:
                            sd["x1"] = end
                        ink = _ink_color(sample, sd, 0.0, paper, either=True)
                        x0, x1 = _ink_box(sample, sd, pad, paper)
                        if end is not None:
                            x1 = end
                        if lim is not None:
                            x1 = min(x1, max(sd["x"] + 0.5 * sd["size"], lim - pad))
                        if x1 - x0 > sd["x1"] - sd["x0"] + 0.5:
                            colors = _slot_paper(sample, sd, pad, SLOT_STRIPS, x0, x1)
                        sd["x0"], sd["x1"] = x0, x1
                        _free_room(sample, sd, paper)
                        # Цвет букв из самого PDF сильнее замера: на мелком
                        # кегле сглаживание делает чёрный серым.
                        if sd.get("color") is not None:
                            ink = sd["color"]
                        sd["_fill"], sd["_ink"] = (colors, paper, pad), ink
                    b["_slots"] = sbs
                    continue
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
                # Цвет краски меряется по ПРЕЖНЕЙ рамке, до раздвижки: в ней
                # заведомо стоит сам абзац, а за краем может стоять чужое.
                ink = None if b.get("image") else _ink_color(sample, b, pad, paper)
                b["x0"], b["x1"] = x0, x1
                b["_fill"] = (colors, paper, pad)
                b["_ink"] = ink
    finally:
        sampler.close()

    # Раскладка считается ПО АБЗАЦУ, один раз, а не на каждой его странице:
    # абзац бывает разорван концом страницы, и счёт «на страницу» удваивал
    # и работу в отчёте, и честное число не влезших.
    plan: list = []
    slot_plan: list = []
    slot_meta: list = []
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
        use_r = needs_raster(text)
        psw = raster.measure if use_r else sw_vec
        prtl = bool(use_r and raster.rtl(text))
        for b in live:
            b["_r"], b["_rtl"], b["_sw"] = use_r, prtl, psw
            for sd in (b.get("_slots") or []):
                sd["_r"], sd["_rtl"], sd["_sw"] = use_r, prtl, psw
        text0 = text
        for grp in groups:
            text = text0
            num = grp[0].get("num") if len(grp) == 1 else None
            if num and len(num) == 2:
                # Колонтитул с номером страницы: в общий перевод — номер ЭТОЙ
                # страницы (`pdftext._head_paragraphs`).
                import re as _re
                text = _re.sub(r"(?<!\d)%s(?!\d)" % _re.escape(str(num[0])), str(num[1]), text, count=1)
            sds = [sd for b in grp for sd in (b.get("_slots") or [])]
            if sds:
                fam = grp[0].get("fam") or ""

                def font_of(sd, fam=fam):
                    return _font_for(fonts, {"style": sd["style"], "fam": fam})
                scat = _scattered(sds)
                if scat:
                    # Разбросанные подписи — каждой своё, от начала своей
                    # строки: выключку одной строки по ней не узнать.
                    align = "left"
                    lines, fs, hss = _spread(text, sds, psw, font_of, nospace)
                    rest = []
                    stats["scattered"] += 1
                else:
                    align = _slot_align(sds)
                    lines, f, rest, hsc = _fit_slots(text, sds, psw, font_of, align, nospace)
                    fs, hss = [f] * len(sds), [hsc] * len(sds)
                font = font_of(sds[0])
                stats["sans" if font.startswith(FONT_NAME + "Sans") else
                      "mono" if font.startswith(FONT_NAME + "Mono") else "serif"] += 1
                shrunk = shrunk or min(fs) < 0.999
                over = over or bool(rest)
                stats["condensed"] += 1 if min(hss) < 0.999 else 0
                slot_plan.append((sds, lines, fs, rest, font_of, align, hss))
                slot_meta.append({"idx": idx, "text": text, "sw": psw, "nospace": nospace,
                                  "scattered": scat, "fam": fam})
                pages_used.update(int(sd["page"]) for sd in sds)
                continue
            font = _font_for(fonts, grp[0])
            # Какой гарнитурой напечатано на деле (а не что просили): нет
            # рубленого файла — абзац ушёл засечками, и отчёт это скажет.
            stats["sans" if font.startswith(FONT_NAME + "Sans") else
                  "mono" if font.startswith(FONT_NAME + "Mono") else "serif"] += 1
            size, lead, per_box, fits = _fit(text, grp, psw, font)
            shrunk = shrunk or size < max(b["size"] for b in grp) - 0.01
            over = over or not fits
            plan.append((idx, grp, per_box, size, lead, font))
            pages_used.update(int(b["page"]) for b in grp)
        stats["shrunk"] += 1 if shrunk else 0
        stats["overflow"] += 1 if over else 0

    # По готовой раскладке, ДО печати: общий кегль у надписей одного стиля
    # и проверка, не легла ли строка перевода на чужой текст.
    _harmonize(slot_plan, slot_meta, stats)
    _resolve_collisions(slot_plan, slot_meta, jobs, reader, skip, stats)


    # Слой на ВСЕ страницы — одним документом, а не по одному на страницу:
    # reportlab встраивает шрифт в каждый собранный файл, и на книге это
    # 378 копий шрифта, то есть десятки мегабайт из ничего.
    # Что печатать на странице — одним проходом заранее: перебор всех строк
    # документа на КАЖДОЙ странице квадратичен по длине книги.
    here_by: dict = {}
    for _idx, boxes, per_box, size, lead, font in plan:
        for n, (b, lines) in enumerate(zip(boxes, per_box)):
            here_by.setdefault(int(b["page"]), []).append((b, lines, size, lead, font, n))
    slots_by: dict = {}
    for sds, lines, fs, rest, font_of, align, hss in slot_plan:
        for k, (sd, line) in enumerate(zip(sds, lines)):
            slots_by.setdefault(int(sd["page"]), []).append(
                (sd, line, fs[k], font_of, align, (k == len(sds) - 1), rest, hss[k]))
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
        here = here_by.get(i, [])
        here_slots = slots_by.get(i, [])
        for sd, *_rest in here_slots:
            colors, _paper, pad = sd["_fill"]
            if sd.get("rot"):
                _fill_rot(c, sd, colors, pad)
                continue
            # Сверху — почти без поля: прописные кончаются на 0.75–0.8 кегля,
            # а выше лежат хвосты букв строки над этой (у непереведённого
            # абзаца при интерлиньяже 1.15 их срезало бы).
            _fill_box(c, sd, pad, colors, top_pad=min(pad, 0.05 * sd["size"]))
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
            ink = b.get("_ink")
            if paper < DARK_PAPER:
                c.setFillColorRGB(1, 1, 1)
            elif ink is not None:
                # Цвет краски оригинала (синий заголовок, серая подпись).
                c.setFillColorRGB(*ink)
                stats["inked"] += 1 if n == 0 else 0
            else:
                c.setFillColorRGB(0, 0, 0)
            c.setFont(font, size)
            y = b["top"] - 0.85 * size
            col = ((1, 1, 1) if paper < DARK_PAPER else (ink if ink is not None else (0, 0, 0)))
            for k, line in enumerate(lines):
                x_ = b["x0"] + (b["indent"] if (k == 0 and n == 0) else 0.0)
                if raster is not None and b.get("_r"):
                    if b.get("_rtl"):
                        x_ = b["x1"] - raster.measure(line, font, size)
                    raster.put(c, x_, y, line, size, col, 1.0, b.get("style") or "",
                               b.get("_rtl"))
                    stats["raster"] += 1
                else:
                    c.drawString(x_, y, line)
                y -= lead
        for sd, line, f, font_of, align, last, rest, hsc in here_slots:
            paper = sd["_fill"][1]
            ink = sd.get("_ink")
            size = max(1.0, sd["size"] * f)
            font = font_of(sd)
            sw = sd.get("_sw") or sw_vec
            if sd.get("rot"):
                c.setFillColorRGB(*(ink if ink is not None else
                                    ((1, 1, 1) if paper < DARK_PAPER else (0, 0, 0))))
                more = list(_overflow_lines(rest, sd, size, sw, font, align, hsc)) if last and rest else []
                _draw_rot(c, sd, [line] + more, size, font, hsc, sw,
                          "center" if sd["curved"] else align, raster if sd.get("_r") else None,
                          ink if ink is not None else ((1, 1, 1) if paper < DARK_PAPER else (0, 0, 0)))
                stats["rotatedSlots"] = stats.get("rotatedSlots", 0) + 1
                continue
            if ink is not None:
                # Цвет краски оригинала — и тёмной, и светлой (белая надпись
                # на плашке): он сильнее правила «тёмная бумага — белым».
                c.setFillColorRGB(*ink)
                stats["inked"] += 1
            elif paper < DARK_PAPER:
                c.setFillColorRGB(1, 1, 1)
            else:
                c.setFillColorRGB(0, 0, 0)
            y = sd["y"]
            for k, ln in enumerate([line] + (list(_overflow_lines(rest, sd, size, sw, font, align, hsc))
                                             if last and rest else [])):
                if not ln:
                    continue
                w = sw(ln, font, size) * hsc
                if align == "center":
                    x = (sd["x0"] + sd["x1"]) / 2.0 - w / 2.0
                elif align == "right":
                    x = sd["x1"] - w
                else:
                    x = sd["x"]
                if raster is not None and sd.get("_r"):
                    if sd.get("_rtl") and align == "left":
                        x = sd["x1"] - w        # справа налево — от правого края места
                    raster.put(c, x, y - k * 1.2 * size, ln, size,
                               ink if ink is not None else
                               ((1, 1, 1) if paper < DARK_PAPER else (0, 0, 0)),
                               hsc, sd["style"], sd.get("_rtl"))
                    stats["raster"] += 1
                    continue
                # Tz, Tr, цвет и толщина обводки — состояние, переживающее ET:
                # без q/Q сужение и «полужирный обводкой» одной строки
                # перешли бы на все следующие строки страницы.
                c.saveState()
                to = c.beginText(x, y - k * 1.2 * size)
                synth = _synth(fonts, font, sd["style"])
                if "i" in synth:
                    # Наклон в 12°: так рисуют курсив, когда его файла нет.
                    to.setTextTransform(1, 0, 0.21, 1, x, y - k * 1.2 * size)
                to.setFont(font, size)
                if hsc < 0.999:
                    to.setHorizScale(hsc * 100.0)
                if "b" in synth:
                    # Обводка тем же цветом — полужирный из прямого.
                    c.setStrokeColorRGB(*(ink if ink is not None else
                                          ((1, 1, 1) if paper < DARK_PAPER else (0, 0, 0))))
                    c.setLineWidth(0.04 * size)
                    to.setTextRenderMode(2)
                to.textOut(ln)
                c.drawText(to)
                c.restoreState()
        order.append(drawn)
        drawn += 1
        c.showPage()
    c.save()
    # Не измерена бумага ровно там, где её не отрисовали: закраска вышла
    # белой, и число сказано. Считать «всё или ничего» нельзя — часть
    # страниц может не отрисоваться, и отчёт тогда врал бы про остальные.
    stats["nocolor"] = len(sampler.missed & pages_used)
    stats["slotParagraphs"] = len(slot_plan)
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
