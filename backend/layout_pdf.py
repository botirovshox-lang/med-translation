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
import sys
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
# Ширина начертания оригинала, ИЗМЕРЕННАЯ по самим строкам (`_width_ratio`):
# ширина строк ÷ знаков ÷ кегль у оригинала против нашего шрифта на том же
# тексте. Calibri уже Noto Sans на 12%, DIN Condensed — на 25%: без этого
# перевод выходил жирнее и шире оригинала и ужимался кеглем. Не уже этого.
HSCALE_WIDTH_MIN = float(os.environ.get("LAYOUT_HSCALE_WIDTH_MIN", "0.74"))
# Сколько знаков оригинала нужно абзацу, чтобы мерить по нему ширину.
WIDTH_MIN_CHARS = 40
# Ниже этого суммарного сужения буквы читаются сплющенными.
HSCALE_FLOOR = 0.7


def _h0_of(slots: list) -> float:
    """Ширина начертания абзаца: измеренная (`_h0` у мест) — либо прежнее
    правило по имени («c» — Condensed)."""
    for sl in slots:
        if sl.get("_h0"):
            return float(sl["_h0"])
    return HSCALE_COND if any("c" in (sl.get("style") or "") for sl in slots) else 1.0


def _width_ratio(slots: list, src: str, sw, font_of) -> "tuple | None":
    """(ширина оригинала ÷ нашего шрифта, знаков) по строкам абзаца с ТОЧНЫМ
    концом (`exact`) — либо None. Оригинал: Σ(x1 − x) / Σ(знаков × кегль);
    наш шрифт: тот же исходный текст его метриками. Строки, выключенные по
    формату, чуть шире своего текста — сужение выходит чуть меньше нужного,
    и это безопасная сторона ошибки."""
    flat = [sl for sl in slots if not sl.get("rot") and sl.get("exact") and (sl.get("n") or 0) > 0]
    n = sum(sl["n"] for sl in flat)
    text = " ".join((src or "").split())
    if n < WIDTH_MIN_CHARS or len(text) < WIDTH_MIN_CHARS:
        return None
    orig = sum(sl["x1"] - sl["x"] for sl in flat) / max(1e-6, sum(sl["n"] * sl["size"] for sl in flat))
    try:
        ours = sw(text, font_of(flat[0]), 1.0) / len(text)
    except Exception:
        return None
    if ours <= 0 or orig <= 0:
        return None
    return orig / ours, n


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


def _vis_lines(slots: list) -> list:
    """ВИДИМЫЕ строки абзаца: места одной базовой линии (±0.3 кегля), стоящие
    вплотную (зазор не больше 1.5 кегля), — одна строка. pypdf режет строку
    на два места на ссылке, смене шрифта, широком пробеле выключки
    («…ратио» | «(377–384)»), и решать о выключке по кускам нельзя: кусок
    в конце строки выглядит «строкой, прижатой вправо». Зазор шире —
    две надписи (ячейки таблицы, колонки) и не сливаются (Л1)."""
    out: list = []
    for sl in slots:
        if sl.get("rot"):
            continue
        if out:
            ln = out[-1]
            s = max(ln["size"], sl["size"], 1.0)
            if (ln["page"] == sl["page"] and abs(ln["y"] - sl["y"]) <= 0.3 * s
                    and -0.5 * s <= sl["x"] - ln["x1"] <= 1.5 * s):
                ln["x1"] = max(ln["x1"], sl["x1"])
                continue
        out.append({"x": sl["x"], "x1": sl["x1"], "y": sl["y"],
                    "size": sl["size"], "page": sl["page"]})
    return out


def _merge_line_slots(slots: list) -> list:
    """Места одной ВИДИМОЙ строки (`_vis_lines`) — одним местом: копия
    первого куска с концом последнего. Для перевёрстки строка — это строка:
    кусок «osf.io/pu93h» на той же базовой, что и начало строки, `_runs`
    принимал за новую колонку, и её область начиналась с ТОЙ ЖЕ высоты —
    перевод печатался строкой поверх строки (проект 14, стр. 3)."""
    out: list = []
    for sl in slots:
        if out and not sl.get("rot") and not out[-1].get("rot"):
            pv = out[-1]
            s_ = max(pv["size"], sl["size"], 1.0)
            if (pv["page"] == sl["page"] and abs(pv["y"] - sl["y"]) <= 0.3 * s_
                    and -0.5 * s_ <= sl["x"] - pv["x1"] <= 1.5 * s_):
                pv["x1"] = max(pv["x1"], sl["x1"])
                pv["x0"] = min(pv["x0"], sl["x0"])
                continue
        out.append(dict(sl))
    return out


def _slot_align(slots: list) -> str:
    """«left» / «center» / «right» — как стояли строки оригинала. Подписи
    в схеме и заголовки бывают выключены по центру, и перевод, начатый
    от левого края, съезжал бы с места. Решают края ВИДИМЫХ строк
    (`_vis_lines`): левые края гуляют, а середины совпадают — центр;
    совпадают правые — вправо. Одна строка — влево: решать не по чему.

    Первая строка в решение о «вправо» не входит: отступ красной строки
    и ЗАГОЛОВОК В ПОДБОР («Hypercortisolism. Hypercortisolism may be…» —
    тело начинается за заголовком, на 50 пт правее остальных строк)
    делали выключенный по формату абзац «прижатым вправо», и строки
    колонки печатались рваным левым краем (проект 14, стр. 17)."""
    ls = _vis_lines(slots)
    if len(ls) < 2:
        return "left"
    size = statistics.median(ln["size"] for ln in ls) or 1.0

    def spread(vals):
        return max(vals) - min(vals)
    xs = [ln["x"] for ln in ls]
    lefts = spread(xs)
    if lefts <= 1.0 * size:
        return "left"
    # Середины всех строк совпадают, а последняя строка (короче прочих)
    # стоит не от общего левого края — центрированная подпись. Отступ
    # красной строки сюда не попадает: у него последняя строка от края.
    if (spread([(ln["x"] + ln["x1"]) / 2.0 for ln in ls]) <= 0.4 * size
            and (len(ls) == 2 or ls[-1]["x"] - min(xs[1:-1]) > 1.0 * size)):
        return "center"
    # Отступ первой строки, висячий отступ и заголовок в подбор: все строки,
    # кроме первой, с одного края — это «влево», какой бы ни была первая.
    if len(ls) >= 3 and spread(xs[1:]) <= 1.0 * size:
        return "left"
    full = ls[:-1] if len(ls) >= 3 else ls
    if (len(ls) == 2 and abs(xs[0] - xs[1]) <= 4.0 * size
            and spread([ln["x1"] for ln in full]) <= 1.0 * size):
        return "left"
    if spread([(ln["x"] + ln["x1"]) / 2.0 for ln in ls]) <= 0.5 * lefts:
        return "center"
    if spread([ln["x1"] for ln in ls]) <= 0.5 * lefts:
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


def _fit_prefix(word: str, width_of, width: float) -> int:
    """Самая длинная голова слова (≥ 1 знака, < всего слова), что входит
    в `width`, — двоичным поиском: у письма без пробелов «слово» — целая
    фраза, и перебор по знаку был квадратичным на каждой укладке."""
    lo, hi = 1, max(1, len(word) - 1)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if width_of(word[:mid]) <= width:
            lo = mid
        else:
            hi = mid - 1
    return lo


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
    h0 = _h0_of(slots)
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
                        n = _fit_prefix(w_, lambda t_: sw(t_, font, size) * hs[0], width)
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
    # Многострочный абзац вбок не растёт: ему есть перевёрстка в свою
    # область (`_fit_flow`), а пункт внутри плашки, выросший вправо, уходил
    # за плашку на поле листа (проект 14, стр. 12).
    label = len(slots) <= FREE_MAX_LINES and all(
        (sl["x1"] - sl["x0"]) <= FREE_MAX_WIDTH * sl.get("_pw", 1e9) for sl in slots)
    wide = label and any(sl.get("room1", sl["x1"]) > sl["x1"] + 0.5
                         or sl.get("room0", sl["x0"]) < sl["x0"] - 0.5 for sl in slots)
    if wide:
        lines, rest, fits = lay(cap, split_ok, True)
        if fits:
            return lines, cap, [], h0
    # Сперва — сужение при прежнем кегле.
    hmin = max(HSCALE_FLOOR, h0 * HSCALE_MIN)
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


# Перевёрстка абзаца в его область (`_fit_flow`). Русский длиннее английского
# на 20–30%, а `_fit_slots` кладёт в каждое место строки оригинала ровно одну
# строку перевода: число строк не растёт, и лишнее можно только ужать. Замер
# на проекте 14: 1142 абзаца из 1699 ушли мельче оригинала, медианно до 0.6.
# Наборщик делает иначе: уменьшает кегль ВМЕСТЕ с интерлиньяжем, и в ту же
# высоту встаёт больше строк — на 25% длиннее хватает кегля 0.89, а не 0.75.
# Насколько можно сузить начертание, прежде чем перевёрстывать: мягкий шаг.
HSCALE_SOFT = float(os.environ.get("LAYOUT_HSCALE_SOFT", "0.93"))
# Сколько строк вправе добавить СВОБОДНАЯ бумага под последней строкой
# колонки (ячейка таблицы, подпись в схеме с пустым местом под ней).
FREE_BELOW_LINES = float(os.environ.get("LAYOUT_FREE_BELOW_LINES", "2"))
# Сколько ШАГОВ строки чистой бумаги оставить до чужой краски снизу:
# интервал между абзацами (меньше строки) так не съедается никогда, а
# пустое место под подписью и в ячейке таблицы — съедается.
FREE_BELOW_GAP = float(os.environ.get("LAYOUT_FREE_BELOW_GAP", "1.2"))
# Перевёрстка берётся, только если она заметно крупнее строки-в-строку.
FLOW_GAIN_MIN = 0.02
# Насколько можно сжать интерлиньяж СВЕРХ кегля, прежде чем ужимать кегль:
# 1.19 кегля книги → 1.11 читается так же, а строк в колонке на 7% больше.
LEAD_SQUEEZE = float(os.environ.get("LAYOUT_LEAD_SQUEEZE", "0.93"))


def _fit_score(f: float, hs: float) -> float:
    """Чем крупнее и шире, тем лучше; сужение начертания весит вдвое
    меньше кегля (сплющенная буква заметна меньше мелкой)."""
    return f + 0.5 * hs


_HYPH: dict = {}


def _hyphenator(lang: "str | None"):
    """Переносы по слогам языка перевода — словарём (pyphen, словари hyph_*
    LibreOffice). Языка в словарях нет или пакета нет — None, и переносов
    нет: выдуманный перенос хуже его отсутствия. Код языка — ISO 639-1 из
    пары проекта («RU», «UZ-CYRL» → «ru», «uz»)."""
    code = (lang or "").split("-")[0].strip().lower()
    if not code:
        return None
    if code not in _HYPH:
        h = None
        try:
            import pyphen
            if pyphen.language_fallback(code):
                h = pyphen.Pyphen(lang=pyphen.language_fallback(code), left=2, right=3)
        except Exception:
            h = None
        _HYPH[code] = h
    return _HYPH[code]


_HYPH_TAIL = ".,;:!?)]}»”\"'"


def _hyph_split(word: str, hy, room: float, w_of) -> "tuple | None":
    """(часть с дефисом, остаток): самый длинный перенос слова, у которого
    часть с дефисом входит в `room`. Только слова из букв (цифры, адреса,
    формулы не переносятся) и не короче шести букв."""
    if len(word) < 6:
        return None
    # Составное слово через дефис («почечно-сердечно-сосудистого») рвётся
    # по СВОЕМУ дефису — словарь для этого не нужен, на любом языке.
    if "-" in word.strip("-"):
        cuts = [k + 1 for k, ch in enumerate(word) if ch == "-" and 2 <= k < len(word) - 3]
        for p in sorted(cuts, reverse=True):
            if w_of(word[:p]) <= room:
                return word[:p], word[p:]
    if hy is None:
        return None
    core = word.rstrip(_HYPH_TAIL)
    if len(core) < 6 or not core.isalpha():
        return None
    try:
        pos = sorted(hy.positions(core), reverse=True)
    except Exception:
        return None
    for p in pos:
        head = core[:p] + "-"
        if w_of(head) <= room:
            return head, word[p:]
    return None


def _runs(slots: list) -> list:
    """Места абзаца, разбитые на КОЛОНКИ строк: [[индексы мест]].

    Колонка — места подряд, каждое ниже прежнего на шаг строки (0.5–2.6
    кегля), с перекрытием по горизонтали и близким кеглем. Повёрнутое место
    и место на другой странице начинают свою колонку. Разброс подписей
    (`_scattered`) сюда не доходит."""
    runs: list = []
    for k, sl in enumerate(slots):
        if sl.get("rot"):
            runs.append([k])
            continue
        if runs and not slots[runs[-1][-1]].get("rot"):
            pv = slots[runs[-1][-1]]
            s = max(pv["size"], sl["size"], 1.0)
            dy = pv["y"] - sl["y"]
            ov = min(pv["x1"], sl["x1"]) - max(pv["x"], sl["x"])
            if (pv["page"] == sl["page"] and 0.5 * s <= dy <= 2.6 * s
                    and ov >= 0.5 * min(pv["x1"] - pv["x"], sl["x1"] - sl["x"])
                    and max(pv["size"], sl["size"]) <= 1.2 * max(1.0, min(pv["size"], sl["size"]))):
                runs[-1].append(k)
                continue
        runs.append([k])
    return runs


def _justified(slots: list) -> bool:
    """Абзац оригинала выключен ПО ФОРМАТУ: строки, кроме последней, упираются
    в общий правый край, левые (кроме отступа первой) — в общий левый.
    Без выключки перевод колонки книги выходит рваным справа рядом с ровными
    колонками оригинала — это видно с первого взгляда на разворот."""
    # По ВИДИМЫМ строкам и по каждой колонке абзаца отдельно: абзац,
    # перешедший в соседнюю колонку, имеет два правых края, и общая мерка
    # объявляла его «не по ширине» (Л1).
    runs: list = []
    for ln in _vis_lines(slots):
        if runs:
            pv = runs[-1][-1]
            s = max(pv["size"], ln["size"], 1.0)
            if pv["page"] == ln["page"] and 0.5 * s <= pv["y"] - ln["y"] <= 2.6 * s \
                    and abs(pv["x"] - ln["x"]) <= 12.0 * s:
                runs[-1].append(ln)
                continue
        runs.append([ln])
    verdicts = []
    for rs in runs:
        if len(rs) < 3:
            continue
        size = statistics.median(ln["size"] for ln in rs) or 1.0
        body = rs[:-1]
        rights = [ln["x1"] for ln in body]
        lefts = [ln["x"] for ln in body[1:]]
        verdicts.append(bool(max(rights) - min(rights) <= 0.6 * size and lefts
                             and max(lefts) - min(lefts) <= 0.6 * size
                             and (max(rights) - min(lefts)) >= 12.0 * size))
    return bool(verdicts) and all(verdicts)


def _regrid(slots: list, runs: list, f: float, ls: float = 1.0) -> list:
    """Места строк под кегль `f`: в каждой колонке абзаца строки идут с шагом
    оригинала × f от базовой линии первой строки до последней (плюс свободная
    бумага под ней, `below`). Колонка из одного места без бумаги под ним —
    как была: подпись в одну строку на дорисованную вторую строку права
    не имеет. Новые места — копии мест оригинала (бумага, краска, начертание,
    рубеж соседа), закраска у них своя не нужна: оригинал стирают места
    самого абзаца (`_v`)."""
    out: list = []
    for run in runs:
        rs = [slots[k] for k in run]
        last = rs[-1]
        if rs[0].get("rot"):
            out.extend(rs)
            continue
        size = max(sl["size"] for sl in rs)
        below = max(0.0, float(last.get("below") or 0.0))
        if len(rs) >= 2:
            pitch = statistics.median(a["y"] - b["y"] for a, b in zip(rs, rs[1:]))
        else:
            pitch = 1.2 * size
        if len(rs) == 1 and below < pitch * f * ls:
            out.extend(rs)
            continue
        y0 = rs[0]["y"]
        ybot = last["y"] - below
        n = max(len(rs) if f * ls >= 0.999 and below <= 0 else 1,
                int((y0 - ybot) / max(0.1, pitch * f * ls) + 1e-6) + 1)
        x_rest = rs[1]["x"] if len(rs) > 1 else rs[0]["x"]
        x0 = min(sl["x0"] for sl in rs)
        # Ширина колонки — медиана ПОЛНЫХ строк: последняя строка абзаца
        # короткая и мерой ширины не служит, а одна вылезшая строка
        # (раздвинутая по краске) не должна раздвигать все.
        full = rs[:-1] if len(rs) >= 3 else rs
        x1 = max(statistics.median(sl["x1"] for sl in full), rs[0]["x"] + 2.0 * size)
        # Начертание новых строк — большинства мест: жирное начало
        # («Self-efficacy:») не должно делать жирной всю вторую строку.
        styles = [sl.get("style") or "" for sl in rs]
        major = max(set(styles), key=styles.count)
        # Кегль новой строки — БОЛЬШИНСТВА строк колонки (Л2): строка,
        # начатая заголовком в подбор («Colchicine.» 5.2 пт при теле 6.7),
        # несёт кегль заголовка, и вся первая строка перевода выходила мелкой.
        sizes = [round(sl["size"], 1) for sl in rs]
        msize = max(set(sizes), key=lambda v_: (sizes.count(v_), v_))
        lims = [sl["lim"] for sl in rs if sl.get("lim") is not None]
        for k in range(n):
            t = rs[min(k, len(rs) - 1)]
            v = dict(t)
            if abs(v["size"] - msize) > 0.05 and len(rs) >= 2:
                v["size"] = msize
            if k >= len(rs) or (k > 0 and (t.get("style") or "") != major):
                v["style"] = major
            v["y"] = y0 - k * pitch * f * ls
            v["x"] = rs[0]["x"] if k == 0 else x_rest
            v["x0"] = min(x0, v["x"])
            v["x1"] = x1
            if lims:
                v["lim"] = min(lims)
            v["top"] = v["y"] + 0.85 * v["size"]
            v["bottom"] = v["y"] - 0.25 * v["size"]
            v["_v"] = True
            # Строка на свободной бумаге под колонкой — за пределами своего
            # абзаца: проверка наложений обязана её видеть.
            v["_grown"] = v["y"] < last["y"] - 0.2 * last["size"]
            v.pop("room0", None)
            v.pop("room1", None)
            out.append(v)
    return out


def _lay_flow(words0: list, slots: list, f: float, hs: float, font_of, sw, align: str,
              split: bool, wcache: dict, hy=None) -> tuple:
    """([строка на место], не влезшие слова): жадная укладка по местам при
    кегле `f` и сужении `hs`. Ширины слов — из кэша (на шрифт, при кегле
    1000): строка у reportlab без кернинга, и сумма слов равна строке."""
    words = list(words0)
    out, k = [], 0
    for sl in slots:
        font = font_of(sl)
        size = max(1.0, sl["size"] * f)
        width = _slot_width(sl, align, False) / max(hs, 0.01)
        cache = wcache.setdefault(font, {})

        def w_of(w):
            v = cache.get(w)
            if v is None:
                v = cache[w] = sw(w, font, 1000.0)
            return v * size / 1000.0
        sp = w_of(" ")
        cur, cw = "", 0.0
        while k < len(words):
            ww = w_of(words[k])
            nw = (cw + sp + ww) if cur else ww
            if nw <= width:
                cur = (cur + " " + words[k]) if cur else words[k]
                cw, k = nw, k + 1
            elif not cur:
                w_ = words[k]
                if split and len(w_) > 1:
                    n = _fit_prefix(w_, lambda t_: sw(t_, font, size), width)
                    n = _cut_point(w_, n)
                    cur = w_[:n]
                    words[k] = w_[n:]
                    break
                hp = _hyph_split(w_, hy, width, w_of)
                if hp:
                    cur, words[k] = hp
                    break
                return out + [w_], words[k + 1:] + ["\x00"]   # слово шире строки
            else:
                hp = _hyph_split(words[k], hy, width - cw - sp, w_of)
                if hp:
                    cur = cur + " " + hp[0]
                    words[k] = hp[1]
                break
        out.append(cur)
    return out, words[k:]


def _fit_flow(text: str, slots: list, sw, font_of, align: str, split_ok: bool = False,
              cap: float = 1.0, floor: "float | None" = None, hy=None) -> tuple:
    """(места для печати, [строка на место], кегль, не влезшие слова, сужение).

    Сперва — как прежде, строка в строку (`_fit_slots`): влезло без ужатия —
    так и печатаем, места — оригинала. Не влезло — абзац перевёрстывается
    в свою область (`_regrid`): кегль и интерлиньяж вместе, строк больше;
    из двух ответов берётся тот, где кегль крупнее. Сужение начертания —
    сперва мягкое (`HSCALE_SOFT`), потом до `HSCALE_MIN`, если оно даёт
    заметно больший кегль."""
    lines, f, rest, hs = _fit_slots(text, slots, sw, font_of, align, split_ok, cap, floor)
    if (not rest and f >= cap - 0.005) or any(sl.get("rot") for sl in slots):
        return slots, lines, f, rest, hs
    orig_slots = slots
    slots = _merge_line_slots(slots)
    runs = _runs(slots)
    if not any(len(r) >= 2 or (slots[r[-1]].get("below") or 0) > 0 for r in runs):
        return orig_slots, lines, f, rest, hs
    floor = MIN_SIZE_SHARE if floor is None else floor
    cap = max(floor, min(1.0, cap))
    h0 = _h0_of(slots)
    words = (text or "").split()
    wcache: dict = {}

    ls_ = [1.0]

    def ok_at(ff, hh):
        vs = _regrid(slots, runs, ff, ls_[0])
        got, left = _lay_flow(words, vs, ff, hh, font_of, sw, align, split_ok, wcache, hy)
        return (not left), vs, got

    best = None
    tries = [(max(HSCALE_FLOOR, h0 * HSCALE_SOFT), 1.0),
             (max(HSCALE_FLOOR, h0 * HSCALE_SOFT), LEAD_SQUEEZE),
             (max(HSCALE_FLOOR, h0 * HSCALE_MIN), LEAD_SQUEEZE)]
    for hmin, ls in tries:
        ls_[0] = ls
        fits, vs, got = ok_at(cap, hmin)
        if fits:
            cand = (cap, hmin, vs, got, ls)
        else:
            fits_lo, vs_lo, got_lo = ok_at(floor, hmin)
            if not fits_lo:
                continue
            lo, hi, cand = floor, cap, (floor, hmin, vs_lo, got_lo, ls)
            for _ in range(9):
                mid = (lo + hi) / 2.0
                fm, vm, gm = ok_at(mid, hmin)
                if fm:
                    lo, cand = mid, (mid, hmin, vm, gm, ls)
                else:
                    hi = mid
        # Сжатый интерлиньяж и сужение — только за заметный выигрыш кегля.
        if best is None or cand[0] > best[0] + 0.04:
            best = cand
        if best[0] >= cap - 0.005:
            break
    if best is None:
        return orig_slots, lines, f, rest, hs
    ff, hmin, vs, got, ls = best
    ls_[0] = ls
    # Сужение — наименьшее, при котором этот кегль ещё влезает.
    lo = hmin
    fits, v2, g2 = ok_at(ff, h0)
    if fits:
        lo, vs, got = h0, v2, g2
    else:
        hi = h0
        for _ in range(6):
            mid = (lo + hi) / 2.0
            fm, vm, gm = ok_at(ff, mid)
            if fm:
                lo, vs, got = mid, vm, gm
            else:
                hi = mid
    # Строка-в-строку побеждает, только если она заметно лучше: при том же
    # кегле перевёрстка держит интерлиньяж кегля, а не пустые полосы.
    if rest or _fit_score(ff, lo) + FLOW_GAIN_MIN >= _fit_score(f, hs):
        return vs, got, ff, [], lo
    return orig_slots, lines, f, rest, hs


# Текстовая рамка (`_flow_groups`): соседние абзацы ОДНОЙ колонки — пункты
# в ячейке таблицы, абзацы колонки книги, подпись из двух абзацев — делят
# место, как в программе вёрстки: длинному пункту тесно, а под коротким
# соседом пусто — сосед сдвигается вниз, и оба печатаются одним кеглем.
# Разрыв между абзацами (шаг строки и больше) — в шагах строки предыдущего.
FRAME_LINK_MAX = float(os.environ.get("LAYOUT_FRAME_LINK_MAX", "3.5"))


def _run_box(rs: list) -> dict:
    size = max(sl["size"] for sl in rs)
    pitch = (statistics.median(a["y"] - b["y"] for a, b in zip(rs, rs[1:]))
             if len(rs) >= 2 else 1.2 * size)
    full = rs[:-1] if len(rs) >= 3 else rs
    return {"page": rs[0]["page"], "top": rs[0]["y"], "bot": rs[-1]["y"], "size": size,
            "pitch": pitch, "x0": min(sl["x"] for sl in rs),
            "x1": statistics.median(sl["x1"] for sl in full),
            "below": float(rs[-1].get("below") or 0.0)}


def _linked(a: dict, b: dict) -> bool:
    """Колонка `b` продолжает колонку `a` следующим абзацем: та же страница,
    близкий кегль, перекрытие по горизонтали, `b` ниже `a` не дальше
    `FRAME_LINK_MAX` шагов строки."""
    if a["page"] != b["page"]:
        return False
    if max(a["size"], b["size"]) > 1.25 * max(1.0, min(a["size"], b["size"])):
        return False
    ov = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    if ov < 0.6 * min(a["x1"] - a["x0"], b["x1"] - b["x0"]):
        return False
    if abs(a["x0"] - b["x0"]) > 3.0 * a["size"]:
        return False
    dy = a["bot"] - b["top"]
    return 0.5 * a["pitch"] <= dy <= FRAME_LINK_MAX * a["pitch"]


def _blocked(a_rs: list, b_rs: list, page_slots: "dict | None") -> bool:
    """Между колонкой `a` и колонкой `b` (ниже) стоит ЧУЖАЯ строка — абзац
    без перевода, совпавший с оригиналом, подпись: рамка через неё не идёт,
    иначе поджатый верхний абзац поднял бы нижний поверх неё."""
    if not page_slots:
        return False
    a, b = _run_box(a_rs), _run_box(b_rs)
    own = {id(s) for s in a_rs} | {id(s) for s in b_rs}
    x0, x1 = min(a["x0"], b["x0"]), max(a["x1"], b["x1"])
    for s in page_slots.get(int(a["page"]), []):
        if id(s) in own:
            continue
        if b["top"] + 0.3 * b["size"] < s["y"] < a["bot"] - 0.3 * a["size"] \
                and min(x1, s["x1"]) - max(x0, s["x"]) > 0:
            return True
    return False


def _flow_groups(slot_plan: list, slot_meta: list, stats: dict, sw_default,
                 page_slots: "dict | None" = None) -> None:
    """Абзацы подряд, чьи колонки сцеплены (`_linked`), верстаются ОДНОЙ
    рамкой одним кеглем: текст течёт по их колонкам по порядку, каждый
    абзац — с новой строки, с отступом первой строки и разрывом оригинала
    (× кегль). Берётся, если общий кегль крупнее самого мелкого из абзацев
    группы; иначе — как было. Разброс, повёрнутые и печать картинкой
    (растр) в рамку не входят."""
    n = len(slot_plan)
    elig = []
    for i in range(n):
        m = slot_meta[i]
        orig = m.get("orig") or []
        ok = (orig and not m["scattered"] and m.get("story") is None
              and not any(sd.get("rot") for sd in orig)
              and not any(sd.get("_r") for sd in orig) and not slot_plan[i][3])
        elig.append(bool(ok))
    runs_of = [[[slot_meta[i]["orig"][k] for k in r] for r in _runs(slot_meta[i]["orig"])]
               if elig[i] else [] for i in range(n)]
    groups, cur = [], []
    for i in range(n):
        if not elig[i]:
            if len(cur) > 1:
                groups.append(cur)
            cur = []
            continue
        if cur and slot_plan[i][5] == slot_plan[cur[-1]][5] and _linked(
                _run_box(runs_of[cur[-1]][-1]), _run_box(runs_of[i][0])) \
                and not _blocked(runs_of[cur[-1]][-1], runs_of[i][0], page_slots):
            cur.append(i)
        else:
            if len(cur) > 1:
                groups.append(cur)
            cur = [i]
    if len(cur) > 1:
        groups.append(cur)
    took = 0
    for g in groups:
        took += 1 if _flow_group(g, slot_plan, slot_meta, runs_of) else 0
    stats["framed"] = took


def _flow_group(g: list, slot_plan: list, slot_meta: list, runs_of: dict) -> bool:
    # Области рамки: колонки абзацев по порядку, сцепленные — одной областью.
    regions: list = []                  # [{box, members: [(i, run, link_dy)]}]
    prev = None
    for i in g:
        for r_k, rs in enumerate(runs_of[i]):
            box = _run_box(rs)
            if regions and r_k == 0 and prev is not None and _linked(prev, box):
                reg = regions[-1]
                reg["members"].append((i, rs, prev["bot"] - box["top"], box))
                reg["bot"] = box["bot"]
                reg["below"] = box["below"]
            else:
                regions.append({"page": box["page"], "top": box["top"], "bot": box["bot"],
                                "below": box["below"], "x0": box["x0"], "x1": box["x1"],
                                "members": [(i, rs, 0.0, box)]})
            prev = box
    paras = []
    for i in g:
        m = slot_meta[i]
        rs_all = [sd for rs in runs_of[i] for sd in rs]
        styles = [sd.get("style") or "" for sd in rs_all]
        major = max(set(styles), key=styles.count)
        pitch = _run_box(runs_of[i][0])["pitch"]
        sizes = [round(sd["size"], 1) for sd in rs_all]
        paras.append({"msize": max(set(sizes), key=lambda v_: (sizes.count(v_), v_)),
                      "i": i, "words": (m["text"] or "").split(), "first": rs_all[0],
                      "rest_t": next((sd for sd in rs_all[1:] if (sd.get("style") or "") == major),
                                     rs_all[0]),
                      "pitch": pitch, "major": major, "font_of": slot_plan[i][4],
                      "sw": m["sw"], "hy": m.get("hy"), "align": slot_plan[i][5]})
    # Где абзац начинается в оригинале: (номер области, база первой строки),
    # и расстояние от прежнего абзаца (по сцепке) — разрыв между абзацами.
    start_gap = {}
    for reg in regions:
        for k, (i, rs, dy, _bx) in enumerate(reg["members"]):
            if k > 0 and i not in start_gap:
                start_gap[i] = dy
    own_y = {}
    for i in g:
        ys = [sd["y"] for rs in runs_of[i] for sd in rs]
        sz = max(sd["size"] for rs in runs_of[i] for sd in rs)
        own_y[i] = (min(ys) - 0.2 * sz, max(ys) + 0.2 * sz)

    def geo(reg, y):
        """Рамка участника, на чьём месте стоит строка: ширина строки —
        его, а не первого абзаца рамки (вложенная цитата уже)."""
        for _i, _rs, _dy, bx in reg["members"]:
            if y >= bx["bot"] - 0.6 * bx["pitch"]:
                return bx
        return reg["members"][-1][3]
    h0 = min(_h0_of(slot_meta[i]["orig"]) for i in g)

    def lay(f, hs):
        out = {p["i"]: ([], []) for p in paras}
        pi, wi = 0, 0                    # абзац и слово
        words = list(paras[0]["words"])
        line_no = 0                      # строка внутри абзаца
        for reg in regions:
            y = None
            last_pitch = None
            while pi < len(paras):
                p = paras[pi]
                if y is None:
                    y = reg["top"]
                elif line_no == 0:
                    y -= (start_gap.get(p["i"]) or (last_pitch or p["pitch"])) * f
                else:
                    y -= p["pitch"] * f
                if y < reg["bot"] - reg["below"] - 1e-6:
                    break
                t = p["first"] if line_no == 0 else p["rest_t"]
                v = dict(t)
                v["size"] = p["msize"]          # Л2: кегль большинства строк
                if line_no > 0:
                    v["style"] = p["major"]
                v.pop("room0", None)
                v.pop("room1", None)
                v["y"] = y
                bx = geo(reg, y)
                v["x"] = p["first"]["x"] if line_no == 0 else max(bx["x0"], p["rest_t"]["x"])
                v["x0"] = min(bx["x0"], v["x"])
                v["x1"] = bx["x1"]
                lo_y, hi_y = own_y[p["i"]]
                v["_grown"] = not (lo_y <= y <= hi_y)
                v["top"], v["bottom"] = y + 0.85 * v["size"], y - 0.25 * v["size"]
                v["page"] = reg["page"]
                v["_v"] = True
                font = p["font_of"](v)
                size = max(1.0, v["size"] * f)
                width = _slot_width(v, p["align"], False) / max(hs, 0.01)
                swf = p["sw"]
                cur, cw = "", 0.0
                spw = swf(" ", font, size)
                while words:
                    w = words[0]
                    ww = swf(w, font, size)
                    nw = (cw + spw + ww) if cur else ww
                    if nw <= width:
                        cur = (cur + " " + w) if cur else w
                        cw = nw
                        words.pop(0)
                        continue
                    hp = _hyph_split(w, p["hy"], width - (cw + spw if cur else 0.0),
                                     lambda s_, font=font, size=size, swf=swf: swf(s_, font, size))
                    if hp:
                        cur = (cur + " " + hp[0]) if cur else hp[0]
                        words[0] = hp[1]
                    elif not cur:
                        return None             # слово шире строки
                    break
                out[p["i"]][0].append(v)
                out[p["i"]][1].append(cur)
                last_pitch = p["pitch"]
                line_no += 1
                if not words:
                    pi += 1
                    line_no = 0
                    if pi < len(paras):
                        words = list(paras[pi]["words"])
        if pi < len(paras):
            return None
        return out

    old_min = min(slot_plan[i][2][0] if slot_plan[i][2] else 1.0 for i in g)
    # Не крупнее кегля класса (`_harmonize`): рамка не вправе сделать абзац
    # крупнее соседних надписей того же стиля.
    top_f = max(slot_plan[i][2][0] if slot_plan[i][2] else 1.0 for i in g)
    best = None
    for hmin in (max(HSCALE_FLOOR, h0 * HSCALE_SOFT), max(HSCALE_FLOOR, h0 * HSCALE_MIN)):
        lo, hi = MIN_SIZE_SHARE, min(1.0, top_f)
        got = lay(hi, hmin)
        if got is not None:
            cand = (hi, hmin, got)
        else:
            got = lay(lo, hmin)
            if got is None:
                continue
            cand = (lo, hmin, got)
            for _ in range(9):
                mid = (lo + hi) / 2.0
                gm = lay(mid, hmin)
                if gm is not None:
                    lo, cand = mid, (mid, hmin, gm)
                else:
                    hi = mid
        if best is None or cand[0] > best[0] + 0.06:
            best = cand
        if best[0] >= min(1.0, top_f) - 0.005:
            break
    if best is None or best[0] < old_min + FLOW_GAIN_MIN:
        return False
    f, hs, out = best
    lo, hi = hs, h0
    for _ in range(6):
        mid = (lo + hi) / 2.0
        gm = lay(f, mid)
        if gm is not None:
            lo, out = mid, gm
        else:
            hi = mid
    hs = lo
    for i in g:
        vs, lines = out[i]
        if not vs:
            # Весь абзац ушёл в соседа выше — места пусты, печатать нечего,
            # но запись остаётся (закраска его оригинала нужна).
            vs, lines = [dict(slot_meta[i]["orig"][0], _v=True)], [""]
        e = slot_plan[i]
        slot_plan[i] = (vs, lines, [f] * len(vs), [], e[4], e[5], [hs] * len(vs))
        slot_meta[i]["framed"] = list(g)
    return True


# ── История страницы (Л3–Л5 в docs/rules/pdf-reading.md) ────────────────
# Прежде каждый абзац колонки подбирался САМ: свой кегль (0.85–0.92),
# свой интерлиньяж, своя выключка, — и колонка книги выглядела набранной
# разными шрифтами (проект 14: у основного текста 77% знаков не тем кеглем,
# что у большинства). Наборщик делает иначе, и так делаем мы:
#  * абзацы СТРАНИЦЫ текут подряд по колонкам (связь «ниже в той же колонке»,
#    «переход наверх соседней колонки», «заголовок в подбор на той же строке»),
#    и тесноту одного абзаца забирает пустота под соседним;
#  * через страницу история не идёт: абзац, разорванный страницей, — два
#    куска, слова делятся по доле его строк на каждой странице;
#  * кегль — СТУПЕНЯМИ (`STORY_STEPS`), и у класса стиля документа (гарнитура,
#    начертание, кегль оригинала) потолок один — нижняя четверть того, что
#    нужно его историям: три четверти текста одним кеглем, остальные —
#    ступенью-двумя ниже, а не каждый своим числом.
STORY_STEPS = (1.0, 0.94, 0.88, 0.82, 0.76, 0.70, 0.64, 0.58, 0.52, 0.46)
STORY_HS = (1.0, 0.95, 0.9, 0.85)          # × ширина начертания класса (`_h0_of`)
STORY_Q = float(os.environ.get("LAYOUT_STORY_Q", "0.25"))
STORY_HEAD_MAX = 2.0                       # заголовок крупнее тела не больше чем в столько раз
STORY_COL_W = (0.85, 1.18)                 # колонка-продолжение той же ширины


def _story_piece_boxes(runs: list) -> list:
    return [dict(_run_box(rs), n=len(rs)) for rs in runs]


def _story_link(A: dict, B: dict, page_slots: "dict | None") -> "str | None":
    """Как кусок `B` продолжает кусок `A` той же страницы: «inline» —
    заголовок в подбор (B начинается на последней строке A, правее её конца,
    а вторая строка B возвращается к левому краю колонки A — у ячеек таблицы
    она возвращается под свою ячейку, и они не сцепятся); «v» — ниже в той
    же колонке; «c» — наверх соседней колонки той же ширины. Иначе None."""
    if A["page"] != B["page"]:
        return None
    ra, rb = A["boxes"][-1], B["boxes"][0]
    la, fb = A["runs"][-1][-1], B["runs"][0][0]
    s = max(la["size"], fb["size"], 1.0)
    if (abs(la["y"] - fb["y"]) <= 0.3 * s and -0.5 * s <= fb["x"] - la["x1"] <= 1.5 * s
            and len(B["runs"][0]) >= 2
            and abs(B["runs"][0][1]["x"] - ra["x0"]) <= 1.0 * s):
        return "inline"
    sa, sb = A["msize"], B["msize"]
    big, small = max(sa, sb), max(1.0, min(sa, sb))
    if big > 1.25 * small:
        # Разный кегль сцепляется только через ЗАГОЛОВОК (крупный и короткий);
        # мелкий абзац под телом — сноска, подпись, врезка: не история.
        # Заголовок — КОРОТКИЙ из двух: крупнее тела либо мельче, но
        # выделенный (полужирный/курсив: «Other Considerations» 5.2 при
        # теле 6.7). Короткий мелкий обычного начертания — сноска.
        head = A if A["nlines"] <= B["nlines"] else B
        if big > STORY_HEAD_MAX * small or head["nlines"] > 3:
            return None
        if head["msize"] < max(sa, sb) - 0.05 and not any(c in head["major"] for c in "bi"):
            return None
    ov = min(ra["x1"], rb["x1"]) - max(ra["x0"], rb["x0"])
    dy = ra["bot"] - rb["top"]
    if (ov >= 0.6 * min(ra["x1"] - ra["x0"], rb["x1"] - rb["x0"])
            and abs(ra["x0"] - rb["x0"]) <= 3.0 * s
            and 0.5 * min(ra["pitch"], rb["pitch"]) <= dy <= FRAME_LINK_MAX * ra["pitch"]
            and not _blocked(A["runs"][-1], B["runs"][0], page_slots)):
        return "v"
    wa, wb = ra["x1"] - ra["x0"], rb["x1"] - rb["x0"]
    if (big <= 1.25 * small and wa >= 8.0 * s and STORY_COL_W[0] <= wb / max(wa, 1.0) <= STORY_COL_W[1]
            and rb["top"] > ra["bot"] + ra["pitch"]
            and (rb["x0"] >= ra["x1"] - 0.5 * s or rb["x1"] <= ra["x0"] + 0.5 * s)):
        return "c"
    return None


def _story_join(A: dict, B: dict) -> bool:
    """`B` — та же фраза, что `A`, разорванная разбором на два абзаца
    («…антагонисты рецепторов (АМКР)» | «(спиронолактон и эплеренон)…»):
    последняя строка `A` в оригинале ПОЛНАЯ (до края колонки), текст `A`
    не кончается знаком конца фразы, у `B` нет отступа, кегль и начертание
    те же. Тогда `B` продолжает строку `A`, а не начинается с новой —
    иначе посреди фразы короткая строка и «новый абзац»."""
    if not A["words"] or not B["words"] or B.get("off0", 0.0) > 0.5 * B["msize"]:
        return False
    if abs(A["msize"] - B["msize"]) > 0.05 or A["major"] != B["major"]:
        return False
    if A["words"][-1][-1:] in ".!?:;…»”\"" or A["nlines"] < 2:
        return False
    la = A["runs"][-1][-1]
    col = A["boxes"][-1]
    return la["x1"] >= col["x1"] - 1.5 * A["msize"]


def _stories(slot_plan: list, slot_meta: list, stats: dict, page_slots: "dict | None") -> None:
    """Перевёрстка текста историями страниц (см. шапку раздела). Берёт
    абзацы-текст (колонка из двух строк и больше либо сцепленные с таким),
    не разброс, не повёрнутые, не растр. Абзац, у которого история не
    сложилась (слово шире строки, не влез и на нижней ступени), остаётся
    с прежней раскладкой."""
    n = len(slot_plan)
    info: dict = {}
    for i in range(n):
        m = slot_meta[i]
        orig = m.get("orig") or []
        if (not orig or m["scattered"] or any(sd.get("rot") for sd in orig)
                or any(sd.get("_r") for sd in orig) or m.get("nospace")):
            continue
        merged = _merge_line_slots(orig)
        sizes = [round(sd["size"], 1) for sd in orig]
        msize = max(set(sizes), key=lambda v_: (sizes.count(v_), v_))
        # Кегль строки pypdf — кегль ПЕРВОГО её куска: строка, начатая
        # заголовком в подбор («Colchicine.» 5.25 при теле 6.65), «мельче»
        # остальных, и колонка строк рвалась на ней (`_runs`), а шаг строки
        # считался по ней одной. Для перевёрстки строка абзаца — кегля абзаца.
        for sd in merged:
            if 0.7 * msize <= sd["size"] <= 1.43 * msize:
                sd["size"] = msize
        runs = [[merged[k] for k in r] for r in _runs(merged)]
        styles = [sd.get("style") or "" for sd in orig]
        info[i] = {"runs": runs, "msize": msize,
                   "major": max(set(styles), key=styles.count),
                   "text_like": any(len(r) >= 2 for r in runs),
                   "nlines": len(_vis_lines(orig))}
    # Куски по страницам: слова абзаца делятся по доле его строк (в знаках
    # ширины) на каждой странице.
    pieces: list = []
    for i in range(n):
        if i not in info:
            pieces.append(None)
            continue
        inf = info[i]
        by_pg: list = []
        for rs in inf["runs"]:
            if by_pg and by_pg[-1][0] == rs[0]["page"]:
                by_pg[-1][1].append(rs)
            else:
                by_pg.append((rs[0]["page"], [rs]))
        words = (slot_meta[i]["text"] or "").split()
        caps = [sum(max(0.0, sd["x1"] - sd["x"]) / max(sd["size"], 1.0) for rs in g for sd in rs)
                for _pg, g in by_pg]
        tot = sum(caps) or 1.0
        lens = [len(w) + 1 for w in words]
        tot_l = sum(lens) or 1
        cut, acc, k = [], 0.0, 0
        for c in caps[:-1]:
            acc += c / tot
            while k < len(words) and sum(lens[:k + 1]) <= acc * tot_l:
                k += 1
            cut.append(k)
        bounds = [0] + cut + [len(words)]
        bx0 = _run_box(inf["runs"][0])
        off0 = max(0.0, inf["runs"][0][0]["x"] - bx0["x0"])
        offs = [min(sd["x"] for sd in rs[1:]) - _run_box(rs)["x0"] for rs in inf["runs"] if len(rs) > 1]
        off1 = max(0.0, statistics.median(offs)) if offs else 0.0
        for j, (pg, g) in enumerate(by_pg):
            head = inf["nlines"] <= 3 and "b" in inf["major"]
            pieces.append({"off0": off0, "off1": off1, "head": head,
                           "i": i, "page": pg, "runs": g, "boxes": _story_piece_boxes(g),
                           "words": words[bounds[j]:bounds[j + 1]], "cont": j > 0,
                           "msize": inf["msize"], "major": inf["major"], "nlines": inf["nlines"],
                           "text_like": inf["text_like"], "first_piece": j == 0,
                           "last_piece": j == len(by_pg) - 1})
    # Цепочки: подряд идущие куски, сцепленные `_story_link`.
    chains: list = []
    cur: list = []
    links: list = []
    for pc in pieces:
        if pc is None:
            if cur:
                chains.append((cur, links))
            cur, links = [], []
            continue
        lk = _story_link(cur[-1], pc, page_slots) if cur else None
        if lk in ("v", "c") and _story_join(cur[-1], pc):
            lk = "inline"
        if cur and lk:
            cur.append(pc)
            links.append(lk)
            if lk == "inline":
                pc["inl"] = True
        else:
            if cur:
                chains.append((cur, links))
            cur, links = [pc], []
    if cur:
        chains.append((cur, links))
    # История — только там, где есть текст: одиночная надпись в одну строку
    # остаётся прежней дороге (`_fit_slots` с запасом бумаги вбок).
    chains = [(c, l) for c, l in chains if any(p["text_like"] for p in c)]
    # Абзац, все куски которого не в истории, — прежний; абзац, у которого
    # история взяла только часть кусков (вторая страница — надпись), тоже
    # прежний: разрезать его раскладку на две дороги нельзя.
    cnt: dict = {}
    for c, _l in chains:
        for p in c:
            cnt[p["i"]] = cnt.get(p["i"], 0) + 1
    total: dict = {}
    for p in pieces:
        if p is not None:
            total[p["i"]] = total.get(p["i"], 0) + 1
    partial = {i for i in cnt if cnt[i] != total[i]}
    if partial:
        keep_ch = []
        for c, l in chains:
            if any(p["i"] in partial for p in c):
                continue
            keep_ch.append((c, l))
        chains = keep_ch

    wcache: dict = {}

    def w_of(font, size, w, swf):
        d = wcache.setdefault((id(swf), font), {})
        v = d.get(w)
        if v is None:
            v = d[w] = swf(w, font, 1000.0)
        return v * size / 1000.0

    def lay(chain, f, hs_k):
        pcs, lks = chain
        # Области: колонки кусков по порядку; «v» и «inline» — та же область.
        regions: list = []
        for k, p in enumerate(pcs):
            for r_k, (rs, bx) in enumerate(zip(p["runs"], p["boxes"])):
                pv = regions[-1]["members"][-1][1] if regions else None
                same_col = (pv is not None and r_k > 0 and pv["page"] == bx["page"]
                            and abs(pv["x0"] - bx["x0"]) <= 1.5 * bx["size"]
                            and 0.0 <= pv["bot"] - bx["top"] <= FRAME_LINK_MAX * pv["pitch"])
                if regions and ((r_k == 0 and k > 0 and lks[k - 1] in ("v", "inline")) or same_col):
                    reg = regions[-1]
                    reg["members"].append((k, bx))
                    reg["bot"] = min(reg["bot"], bx["bot"])
                    reg["below"] = bx["below"]
                else:
                    regions.append({"page": bx["page"], "top": bx["top"], "bot": bx["bot"],
                                    "below": bx["below"], "members": [(k, bx)]})
        for reg in regions:
            full = [b_ for _k, b_ in reg["members"] if b_["n"] >= 2] or [b_ for _k, b_ in reg["members"]]
            reg["col"] = {"x0": min(b_["x0"] for b_ in full), "x1": max(b_["x1"] for b_ in full),
                          "page": reg["page"]}
        out = {k: ([], []) for k in range(len(pcs))}
        pi = 0
        words = list(pcs[0]["words"])
        line_no = 0
        prev_end = None                 # (y, x конца напечатанного, x1 строки, кегль)
        for reg in regions:
            y = None
            last_pitch = None
            while pi < len(pcs):
                p = pcs[pi]
                meta = slot_meta[p["i"]]
                inline = line_no == 0 and pi > 0 and lks[pi - 1] == "inline" and prev_end is not None
                pitch_p = p["boxes"][0]["pitch"]
                if inline:
                    y_ = prev_end[0]
                elif y is None:
                    y_ = reg["top"]
                elif line_no == 0:
                    gap = None
                    if pi > 0 and lks[pi - 1] == "v":
                        gap = pcs[pi - 1]["boxes"][-1]["bot"] - p["boxes"][0]["top"]
                    y_ = y - (gap or last_pitch or pitch_p) * f
                else:
                    y_ = y - pitch_p * f
                if y_ < reg["bot"] - reg["below"] - 1e-6:
                    break
                # Заголовок не остаётся последней строкой колонки: держится
                # со следующей строкой (короткий крупный абзац перед телом).
                if (line_no == 0 and not inline and pi + 1 < len(pcs) and p["nlines"] <= 2
                        and (p["msize"] > 1.1 * pcs[pi + 1]["msize"] or "b" in p["major"])
                        and "b" not in pcs[pi + 1]["major"]
                        and y_ - pcs[pi + 1]["boxes"][0]["pitch"] * f * 1.5
                        < reg["bot"] - reg["below"] - 1e-6
                        and reg is not regions[-1]):
                    break
                tmpl = p["runs"][0][0] if (line_no == 0 and not p["cont"]) else (
                    next((sd for rs in p["runs"] for sd in rs[1:]
                          if (sd.get("style") or "") == p["major"]), p["runs"][0][0]))
                v = dict(tmpl)
                v["size"] = p["msize"]
                # Строка — одним начертанием: первая строка абзаца, начатая
                # заголовком в подбор («Consensus recommendations» полужирным),
                # не печатается целиком полужирной (Л2).
                if line_no > 0 or p["cont"] or p["nlines"] >= 3:
                    v["style"] = p["major"]
                v.pop("room0", None)
                v.pop("room1", None)
                v["y"] = y_
                # Ширина строки — колонки области: своя рамка абзаца, если
                # он сам стоит в этой области строкой колонки (вложенная
                # цитата, пункт списка уже); иначе — полные строки области.
                # По высоте оригинала не выбираем: история сдвигает текст,
                # и строка попадала в рамку заголовка (ширина «Other
                # Considerations» — 50 пт) — перенос через слово.
                own = [b_ for k_, b_ in reg["members"] if k_ == pi and b_["n"] >= 2]
                bx = own[0] if own else reg["col"]
                if inline:
                    v["x"] = prev_end[1] + w_of(meta_font(pcs[pi - 1], v), v["size"] * f, " ",
                                                slot_meta[pcs[pi - 1]["i"]]["sw"]) * hs_k
                    v["x1"] = max(prev_end[2], bx["x1"])
                elif line_no == 0 and not p["cont"]:
                    # Отступ первой строки — от края колонки, где строка
                    # встала: абзац уезжает по истории в другую колонку.
                    v["x"] = bx["x0"] + (0.0 if p.get("inl") else p["off0"])
                    v["x1"] = bx["x1"]
                else:
                    v["x"] = bx["x0"] + p["off1"]
                    v["x1"] = bx["x1"]
                v["x0"] = min(bx["x0"], v["x"])
                ys = [sd["y"] for rs in p["runs"] for sd in rs]
                v["_grown"] = not (min(ys) - 0.2 * p["msize"] <= y_ <= max(ys) + 0.2 * p["msize"])
                v["top"], v["bottom"] = y_ + 0.85 * v["size"], y_ - 0.25 * v["size"]
                v["page"] = reg["page"]
                v["_v"] = True
                v["_story"] = True
                fo = slot_plan[p["i"]][4]
                font = fo(v)
                swf = meta["sw"]
                size = max(1.0, v["size"] * f)
                h0 = v.get("_h0", 1.0)
                hs = max(HSCALE_FLOOR, h0 * hs_k)
                align = slot_plan[p["i"]][5]
                width = (v["x1"] - v["x"]) / max(hs, 0.01)
                if inline and width < 3.0 * size:
                    # Места за заголовком не осталось — тело с новой строки.
                    lks = list(lks)
                    lks[pi - 1] = "v"
                    y = prev_end[0]
                    continue
                cur, cw = "", 0.0
                spw = w_of(font, size, " ", swf)
                while words:
                    w = words[0]
                    ww = w_of(font, size, w, swf)
                    nw = (cw + spw + ww) if cur else ww
                    if nw <= width:
                        cur = (cur + " " + w) if cur else w
                        cw = nw
                        words.pop(0)
                        continue
                    hp = _hyph_split(w, None if p["head"] else meta.get("hy"),
                                     width - (cw + spw if cur else 0.0),
                                     lambda s_, font=font, size=size, swf=swf: w_of(font, size, s_, swf))
                    if hp:
                        cur = (cur + " " + hp[0]) if cur else hp[0]
                        words[0] = hp[1]
                    elif not cur:
                        _why[:] = ["word", w, round(width, 1), p["i"]]
                        return None             # слово шире строки
                    break
                v["_hs"] = hs
                out[pi][0].append(v)
                out[pi][1].append(cur)
                prev_end = (y_, v["x"] + cw * hs, v["x1"], size)
                y = y_
                last_pitch = pitch_p
                line_no += 1
                if not words:
                    pi += 1
                    line_no = 0
                    if pi < len(pcs):
                        words = list(pcs[pi]["words"])
            if pi >= len(pcs):
                break
        if pi < len(pcs):
            _why[:] = ["left", pi, len(words), len(regions)]
            return None
        return out

    _why: list = []

    def meta_font(p, v):
        return slot_plan[p["i"]][4](dict(v, style=p["major"]))

    def best_at(chain, f):
        for hk in STORY_HS:
            got = lay(chain, f, hk)
            if got is not None:
                return hk, got
        return None

    def max_step(chain, cap_i=0):
        """Номер самой крупной ступени, на которой история укладывается."""
        lo, hi = cap_i, len(STORY_STEPS) - 1
        if best_at(chain, STORY_STEPS[hi]) is None:
            return None
        if best_at(chain, STORY_STEPS[lo]) is not None:
            return lo
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if best_at(chain, STORY_STEPS[mid]) is not None:
                hi = mid
            else:
                lo = mid
        return hi

    # Первый проход: предел каждой истории. Класс — по знакам: гарнитура,
    # начертание и кегль оригинала основной части истории.
    lims, klass, weight = [], [], []
    for ch in chains:
        lims.append(max_step(ch))
        if os.environ.get("LAYOUT_DEBUG"):
            print("[story]", [(slot_meta[p["i"]]["idx"], p["page"], len(p["words"])) for p in ch[0]],
                  ch[1], "lim", lims[-1], _why if lims[-1] is None else "", file=sys.stderr)
        cnt_c: dict = {}
        for p in ch[0]:
            key = (slot_meta[p["i"]]["fam"], _face_style(p["major"]), round(p["msize"] * 2) / 2.0)
            cnt_c[key] = cnt_c.get(key, 0) + sum(len(w) + 1 for w in p["words"])
        klass.append(max(cnt_c.items(), key=lambda t: t[1])[0] if cnt_c else None)
        weight.append(sum(cnt_c.values()))
    # Потолок класса — нижняя четверть пределов (взвешенно по знакам).
    caps: dict = {}
    for key in set(klass):
        vals = sorted((lims[c], weight[c]) for c in range(len(chains))
                      if klass[c] == key and lims[c] is not None)
        if not vals:
            continue
        tot = sum(w for _s, w in vals)
        acc, pick = 0, vals[-1][0]
        # Самая крупная ступень, которую держат (1 − Q) знаков класса.
        for s_i, w in vals:
            acc += w
            if acc >= (1.0 - STORY_Q) * tot:
                pick = s_i
                break
        caps[key] = pick
    took = outl = 0
    stories: list = []
    for c, ch in enumerate(chains):
        if lims[c] is None:
            continue
        s_i = max(lims[c], caps.get(klass[c], lims[c]))
        got = best_at(ch, STORY_STEPS[s_i])
        if got is None:
            continue
        if s_i > caps.get(klass[c], s_i):
            outl += 1
        _story_apply(ch, got, STORY_STEPS[s_i], slot_plan, slot_meta, len(stories))
        stories.append({"chain": ch, "step": s_i})
        took += 1
    stats["stories"] = took
    stats["storyOutliers"] = outl
    stats["storySteps"] = {"%s/%s/%.1f" % (k[0] or "-", k[1] or "r", k[2]): STORY_STEPS[v]
                           for k, v in sorted(caps.items(), key=lambda t: str(t[0]))[:12]}

    def relay(sid: int) -> bool:
        """Наложение у истории: вся история — ступенью ниже."""
        st_ = stories[sid]
        for s_i in range(st_["step"] + 1, len(STORY_STEPS)):
            got = best_at(st_["chain"], STORY_STEPS[s_i])
            if got is not None:
                st_["step"] = s_i
                _story_apply(st_["chain"], got, STORY_STEPS[s_i], slot_plan, slot_meta, sid)
                return True
        return False
    stats["_story_relay"] = relay


def _story_apply(chain, got, f, slot_plan, slot_meta, sid) -> None:
    pcs, _lks = chain
    hk, out = got
    per: dict = {}
    for k, p in enumerate(pcs):
        vs, lines = out[k]
        per.setdefault(p["i"], ([], []))
        per[p["i"]][0].extend(vs)
        per[p["i"]][1].extend(lines)
    for i, (vs, lines) in per.items():
        if not vs:
            vs, lines = [dict(slot_meta[i]["orig"][0], _v=True)], [""]
        e = slot_plan[i]
        slot_plan[i] = (vs, lines, [f] * len(vs), [], e[4], e[5],
                        [v.get("_hs", 1.0) for v in vs])
        slot_meta[i]["story"] = sid
        slot_meta[i].pop("framed", None)


# Общий кегль класса надписей (`_harmonize`): класс от стольких абзацев,
# кегль — такой квантиль нужных им множителей.
HARMONY_MIN = int(os.environ.get("LAYOUT_HARMONY_MIN", "3"))
HARMONY_Q = float(os.environ.get("LAYOUT_HARMONY_Q", "0.5"))
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
    orig = m.get("orig") or sds
    if not wide:
        for sd in orig:
            sd.pop("room0", None)
            sd.pop("room1", None)
    vs, lines, f, rest, hsc = _fit_flow(m["text"], orig, m["sw"], font_of, align, m["nospace"],
                                        cap=cap, floor=floor, hy=m.get("hy"))
    slot_plan[i] = (vs, lines, [f] * len(vs), rest, font_of, align, [hsc] * len(vs))


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
        if m["scattered"] or any(sd.get("rot") for sd in sds) or m.get("story") is not None:
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


# Мельче этой доли кегля оригинала перевод читается заметно мельче соседей —
# такие абзацы самопроверка называет.
SMALL_SHARE = float(os.environ.get("LAYOUT_SMALL_SHARE", "0.8"))


def _size_report(slot_plan: list, slot_meta: list, plan: list, stats: dict) -> None:
    """Самопроверка размера: какой доле ЗНАКОВ перевода достался кегль
    оригинала, медиана множителя, сколько знаков мельче `SMALL_SHARE`,
    и на каких страницах (`smallPages`, по знакам, худшие первыми).
    Считается по готовой раскладке, до печати — тот же расчёт, что печать."""
    tot = small = 0
    fs_w: list = []
    per_page: dict = {}
    for i, (sds, _l, fs, _r, _fo, _a, _h) in enumerate(slot_plan):
        if not sds or any(sd.get("rot") for sd in sds):
            continue
        n = len(slot_meta[i]["text"] or "")
        f = min(fs) if fs else 1.0
        tot += n
        fs_w.append((f, n))
        if f < SMALL_SHARE:
            small += n
            pg = int(sds[0]["page"]) + 1
            per_page[pg] = per_page.get(pg, 0) + n
    for _idx, grp, _pb, size, _lead, _font in plan:
        n = sum(len(x) for lines in _pb for x in lines)
        base = max((b["size"] for b in grp), default=size) or size
        f = size / base if base else 1.0
        tot += n
        fs_w.append((f, n))
        if f < SMALL_SHARE:
            small += n
            pg = int(grp[0]["page"]) + 1
            per_page[pg] = per_page.get(pg, 0) + n
    fs_w.sort()
    acc, med = 0, 1.0
    for f, n in fs_w:
        acc += n
        if acc >= tot / 2.0:
            med = f
            break
    # Разброс кегля ВНУТРИ класса стиля (Л11): «один стиль — один кегль»
    # меряется числом, а не глазом. Класс — гарнитура, начертание, кегль
    # оригинала; по каждому — доля знаков, напечатанных НЕ кеглем класса
    # (модой, шаг 0.02), и размах множителя.
    cls: dict = {}
    for i, (sds, _l, fs, _r, _fo, _a, _h) in enumerate(slot_plan):
        if not sds or any(sd.get("rot") for sd in sds) or slot_meta[i]["scattered"]:
            continue
        o = slot_meta[i].get("orig") or sds
        key = "%s/%s/%.1f" % (slot_meta[i]["fam"] or "-", _face_style(o[0].get("style") or "") or "r",
                              round(o[0]["size"] * 2) / 2.0)
        cls.setdefault(key, []).append((round((min(fs) if fs else 1.0) / 0.02) * 0.02,
                                        len(slot_meta[i]["text"] or "")))
    rep = []
    for key, vals in cls.items():
        n = sum(c for _f, c in vals)
        by: dict = {}
        for f_, c in vals:
            by[f_] = by.get(f_, 0) + c
        mode = max(by.items(), key=lambda t: t[1])[0]
        off = sum(c for f_, c in vals if abs(f_ - mode) > 0.011)
        rep.append((n, key, round(mode, 2), round(off / n, 3) if n else 0.0,
                    round(min(f_ for f_, _c in vals), 2), round(max(f_ for f_, _c in vals), 2)))
    rep.sort(reverse=True)
    stats["fClasses"] = [{"cls": k, "chars": n, "mode": m, "offShare": o, "min": lo, "max": hi}
                         for n, k, m, o, lo, hi in rep[:8]]
    tot_c = sum(r[0] for r in rep)
    stats["fOffShare"] = round(sum(r[0] * r[3] for r in rep) / tot_c, 3) if tot_c else 0.0
    stats["sizeMedian"] = round(med, 3)
    stats["smallShare"] = round(small / tot, 4) if tot else 0.0
    stats["smallPages"] = [p for p, _n in sorted(per_page.items(), key=lambda t: -t[1])][:20]


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
            grown = (j > 0 or x + w > sd["x1"] + 0.5 or x < sd["x0"] - 0.5
                     or bool(sd.get("_grown")))
            # Седьмое поле — «строка стоит не на месте оригинала»: вылезла
            # или перевёрстана (`_v`). Наложение двух строк, обе на своих
            # местах, было в самом оригинале и не наше; перевёрстанная
            # строка на чужом тексте — наше, даже в пределах своего абзаца
            # (Л11: прежде такие наложения не считались вовсе).
            moved = grown or bool(sd.get("_v"))
            out.append((int(sd["page"]), x, y - 0.25 * size, x + w, y + 0.85 * size, size, moved))
    return out


def _overlap(a: tuple, b: tuple) -> bool:
    s = min(a[5], b[5])
    ix = min(a[3], b[3]) - max(a[1], b[1])
    iy = min(a[4], b[4]) - max(a[2], b[2])
    return ix > 0.25 * s and iy > 0.3 * min(a[4] - a[2], b[4] - b[2])


def _resolve_collisions(slot_plan: list, slot_meta: list, jobs: list,
                        reader, skip: set, stats: dict, img_plan: "list | None" = None,
                        plan: "list | None" = None) -> None:
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

    # Надписи картинок (`img_plan`) и рамки без мест строк (`plan`) тоже
    # печатают текст: их прямоугольники участвуют в счёте наложений, хотя
    # переуложить их здесь нельзя — только назвать.
    others: list = []
    for k, ent in enumerate(img_plan or []):
        b = ent["b"]
        others.append(((int(b["page"]), b["x0"], b["bottom"], b["x1"], b["top"],
                        max(1.0, b.get("size") or 1.0), True), ("i", k)))
    for k, (_idx, grp, _pb, size, _lead, _font) in enumerate(plan or []):
        for b in grp:
            others.append(((int(b["page"]), b["x0"], b["bottom"], b["x1"], b["top"],
                            max(1.0, size), True), ("p", k)))

    def find():
        rects = list(fixed) + others
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
                    if wa[0] in "ip" and wb[0] in "ip":
                        continue        # надпись на надписи картинки — не наш счёт
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
        # Абзац рамки (`_flow_groups`) уложить отдельно нельзя: соседи остались
        # бы на сдвинутых местах. Рамка разбирается целиком.
        for i in list(todo):
            for j in slot_meta[i].get("framed") or []:
                todo.add(j)
        for i in todo:
            slot_meta[i].pop("framed", None)
        if not todo:
            break
        # История страницы (`_stories`) укладывается целиком: ступенью ниже.
        relay = stats.get("_story_relay")
        done_s: set = set()
        for i in list(todo):
            sid = slot_meta[i].get("story")
            if sid is None:
                continue
            todo.discard(i)
            if sid not in done_s and relay is not None:
                done_s.add(sid)
                relay(sid)
        for i in todo:
            sds = slot_plan[i][0]
            f = slot_plan[i][2][0]
            if any("room0" in sd or "room1" in sd for sd in sds):
                _refit(slot_plan, slot_meta, i, cap=f, wide=False)
            elif slot_plan[i][3] or f > FLOOR_HARD:
                _refit(slot_plan, slot_meta, i, cap=f, floor=FLOOR_HARD, wide=False)
        fixed_n += len(todo)
    hits = find()
    paras = sorted({slot_meta[who[1]]["idx"] for _pg, who, _o in hits if who[0] == "s"}
                   | {slot_meta[o[1]]["idx"] for _pg, _w, o in hits if o and o[0] == "s"},
                   key=lambda v: str(v))
    stats["collisionImages"] = len({who for _pg, who, _o in hits if who[0] in "ip"}
                                   | {o for _pg, _w, o in hits if o and o[0] in "ip"})
    stats["collisionFixed"] = fixed_n
    stats["collisions"] = len(paras) + stats["collisionImages"]
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


# Разрешение вырезки надписи с рисунка: кегль надписи — не меньше стольких
# точек снимка (мелкий текст при 144 dpi — 10 точек, стереть его чисто нельзя).
PAINT_EM_PX = float(os.environ.get("LAYOUT_PAINT_EM_PX", "28"))
PAINT_MAX_SCALE = 8.0
PAINT_MAX_MPX = 4.0


def _tp():
    try:
        from backend import text_paint as tp
    except ImportError:
        import text_paint as tp
    return tp


def _paint_measure(sampler, b: dict) -> bool:
    """Надпись с рисунка (`image`): вырезка участка при достаточном
    разрешении, замер (`text_paint.measure`), стирание и заплатка с
    прозрачностью вне букв. False — нечем (нет OpenCV, не отрисовалось,
    букв не нашлось): вызывающий идёт прежней дорогой, заливкой."""
    try:
        tp = _tp()
    except ImportError:
        return False
    if not tp.available():
        return False
    import math
    import numpy as np
    rows = max(1, int(b.get("rows") or 1))
    h_pt = max(0.5, b["top"] - b["bottom"])
    w_pt = max(0.5, b["x1"] - b["x0"])
    line_pt = h_pt / rows
    # Рамка однострочной надписи, НЕ вытянутой вширь, — дуга или повёрнутая
    # подпись: её высота не высота строки, буква — примерно четверть
    # меньшей стороны. По ней и разрешение вырезки.
    est = line_pt if (rows > 1 or w_pt >= 2.5 * h_pt) else min(w_pt, h_pt) / 4.0
    scale = min(PAINT_MAX_SCALE, max(2.0, PAINT_EM_PX / max(0.5, 0.8 * est)))
    if (w_pt * scale) * (h_pt * scale) > PAINT_MAX_MPX * 1e6:
        scale = (PAINT_MAX_MPX * 1e6 / (w_pt * h_pt)) ** 0.5
    pad = 0.15 * line_pt
    got = sampler.crop(int(b["page"]), b["x0"] - pad, b["bottom"] - pad, b["x1"] + pad,
                       b["top"] + pad, scale)
    if not got:
        return False
    im, (cx0, cy0, cx1, cy1) = got
    rgb = np.asarray(im)
    # Рамка самой надписи внутри вырезки (вырезка — с полем): область маски
    # у края вырезки, лежащая ВНЕ рамки, — соседняя надпись.
    inner = ((b["x0"] - cx0) * scale, (cy1 - b["top"]) * scale,
             (b["x1"] - cx0) * scale, (cy1 - b["bottom"]) * scale)
    try:
        m = tp.measure(rgb, b.get("src") or "", rows, line_pt * scale, inner=inner)
        if not m.get("found"):
            return False
        out, alpha = tp.erase(rgb, m)
    except Exception:
        return False
    if len(m["bands"]) > rows + 1:
        # «Строк» по маске больше, чем строк у надписи: в маску попала
        # графика схемы. Строки — по рамке детектора, а не по маске.
        m["bands"] = []
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.dstack([out, alpha]), "RGBA").save(buf, "PNG")
    bands = [((cy1 - a / scale), (cy1 - (bb + 1) / scale)) for a, bb in m["bands"]]
    areas = m.get("areas") or [[0, max(0, len(bands) - 1)]]
    area_ink = [float(m["mask"][m["bands"][a0][0]:m["bands"][a1][1] + 1].sum()) if m["bands"] else 1.0
                for a0, a1 in areas] if m["bands"] else [1.0]
    ink_w = 0.0
    for a, bb in m["bands"]:
        cols = np.nonzero(m["mask"][a:bb + 1].any(axis=0))[0]
        if len(cols):
            ink_w += (cols[-1] - cols[0] + 1) / scale
    # Цвет фона и букв — и для прежней дороги (письмо справа налево и со
    # сборкой букв печатается растром строки, а не этим путём).
    paper = sum(m["bg"]) / (3 * 255.0)
    b["_fill"] = ([tuple(v / 255.0 for v in m["bg"])] * FILL_STRIPS, paper, 0.0)
    b["_ink"] = tuple(v / 255.0 for v in m["ink"])
    b["_paint"] = {"png": buf.getvalue(), "rect": (cx0, cy0, cx1, cy1), "em": m["em"] / scale,
                   "pitch": m["pitch"] / scale, "ink": tuple(v / 255.0 for v in m["ink"]),
                   "bold": m["bold"], "angle": m["angle"], "bands": bands, "inkw": ink_w,
                   "areas": areas, "areaInk": area_ink,
                   "flat": m["flat"],
                   "len": (math.hypot(cx1 - cx0, cy1 - cy0) * 0.92) if m["angle"] else None}
    arc = m.get("arc")
    if arc:
        b["_paint"]["arc"] = {"cx": cx0 + arc["cx"] / scale, "cy": cy0 + arc["cy"] / scale,
                              "r": arc["r"] / scale, "t0": arc["t0"], "t1": arc["t1"],
                              "up": arc["up"]}
    return True


def _paint_plan(b: dict, text: str, fonts: dict, sw, hyph) -> "dict | None":
    """Раскладка перевода надписи с рисунка: кегль — измеренный кегль
    оригинала (не высота рамки детектора), строки — в ширину надписи и в
    высоту её строк (с переносами), ужатие — только если не влезает.
    Ширина начертания — как у оригинала (ширина краски ÷ знаков)."""
    pt = b["_paint"]
    font = _font_for(fonts, {"style": "b" if pt["bold"] else "", "fam": "sans"})
    em = max(2.0, pt["em"])
    src = " ".join((b.get("src") or "").split())
    h0 = 1.0
    if src and pt["inkw"] > 0 and not pt["angle"]:
        ours = sw(src, font, em)
        if ours > 0:
            h0 = min(1.0, max(HSCALE_WIDTH_MIN, pt["inkw"] / ours))
    if pt.get("arc"):
        a = pt["arc"]
        rb = max(1.0, a["r"] - a["up"] * 0.36 * em)
        width = abs(a["t1"] - a["t0"]) * rb * ARC_GROW + em
        height = 1.3 * em
        rows_min = 1
    elif pt["angle"]:
        width = pt["len"] or (b["x1"] - b["x0"])
        height = 1.3 * em
        rows_min = 1
    else:
        width = b["x1"] - b["x0"]
        bands = pt["bands"]
        top = bands[0][0] if bands else b["top"]
        bot = bands[-1][1] if bands else b["bottom"]
        height = max(top - bot, em)
        rows_min = max(1, len(bands))

    def mw(t_, s_):
        return sw(t_, font, s_) * h0
    split = None
    if hyph is not None and not pt.get("arc") and not pt["angle"]:
        def split(w_, room, s_):
            return _hyph_split(w_, hyph, room, lambda x_: mw(x_, s_))
    if pt.get("arc") or pt["angle"]:
        # Дуга — одна строка: кегль ужимается, пока перевод не ляжет на дугу.
        one = " ".join((text or "").split())
        size = em
        while size > 0.45 * em and mw(one, size) > width:
            size *= 0.96
        return {"b": b, "font": font, "size": size, "step": size, "lines": [one], "h0": h0,
                "f": size / em, "over": mw(one, size) > width, "align": "center"}
    tp = _tp()
    bands = pt["bands"]
    areas = pt.get("areas") or []
    if len(bands) >= 2 and len(areas) > 1:
        # Блок — столбец схемы из нескольких плашек: перевод — по участкам,
        # каждый в своей плашке (`text_paint._areas`, `split_text`).
        chunks = tp.split_text(text, pt.get("areaInk") or [1.0] * len(areas))
        areas_t = [(bands[a0][0], bands[a1][1], a1 - a0 + 1) for a0, a1 in areas]
    else:
        chunks = [text]
        areas_t = [(bands[0][0] if bands else b["top"], bands[-1][1] if bands else b["bottom"],
                    rows_min)]
    parts, over, fmin = [], False, 1.0
    for (top, bot, rows_k), chunk in zip(areas_t, chunks):
        h_k = max(top - bot, em)
        size, step, lines = tp.fit_lines(chunk, width, h_k + 0.3 * em, em,
                                         max(pt["pitch"], em * 1.05), mw, split, 0.45, rows_k)
        need = (len(lines) - 1) * step + 0.95 * size if lines else 0.0
        over = over or need > h_k + 0.5 * em
        fmin = min(fmin, size / em)
        parts.append({"top": top, "bot": bot, "lines": lines, "size": size, "step": step})
    first = parts[0] if parts else {"lines": [], "size": em, "step": em}
    return {"b": b, "font": font, "size": first["size"], "step": first["step"],
            "lines": [ln for p_ in parts for ln in p_["lines"]], "parts": parts, "h0": h0,
            "f": fmin, "over": over, "align": b.get("align") or "left"}


def _paint_fill(c, ent: dict) -> None:
    """Заплатка: стёртые буквы оригинала, прозрачная вне их маски."""
    from reportlab.lib.utils import ImageReader
    pt = ent["b"]["_paint"]
    x0, y0, x1, y1 = pt["rect"]
    c.drawImage(ImageReader(io.BytesIO(pt["png"])), x0, y0, x1 - x0, y1 - y0, mask="auto")


# На сколько перевод вправе выйти за длину дуги оригинала, прежде чем
# ужиматься: дуга кольца продолжается за последней буквой.
ARC_GROW = float(os.environ.get("LAYOUT_ARC_GROW", "1.25"))


def _paint_arc(c, arc: dict, text: str, font: str, size: float, h0: float,
               synth_b: bool) -> None:
    """Строка по дуге — буква за буквой, середина строки — в середине дуги
    оригинала, верх букв — туда же, куда у оригинала (`up`)."""
    import math
    up = arc["up"]
    rb = max(1.0, arc["r"] - up * 0.36 * size)
    s = 1.0 if arc["t1"] >= arc["t0"] else -1.0
    total = _sw_of(text, font, size) * h0
    tm = (arc["t0"] + arc["t1"]) / 2.0
    cur = tm - s * (total / 2.0) / rb
    for ch in text:
        a = _sw_of(ch, font, size) * h0
        th = cur + s * (a / 2.0) / rb
        px, py = arc["cx"] + rb * math.cos(th), arc["cy"] + rb * math.sin(th)
        tx, ty = -s * math.sin(th), s * math.cos(th)          # касательная по ходу
        phi = math.degrees(math.atan2(ty, tx))
        c.saveState()
        c.translate(px, py)
        c.rotate(phi)
        _paint_line(c, ch, -a / 2.0, 0.0, font, size, h0, synth_b)
        c.restoreState()
        cur += s * a / rb


def _sw_of(t: str, font: str, size: float) -> float:
    from reportlab.pdfbase import pdfmetrics
    return pdfmetrics.stringWidth(t, font, size)


def _paint_line(c, ln: str, x: float, y: float, font: str, size: float, h0: float,
                synth_b: bool) -> None:
    to = c.beginText(x, y)
    to.setFont(font, size)
    if h0 < 0.999:
        to.setHorizScale(h0 * 100.0)
    if synth_b:
        to.setTextRenderMode(2)
    to.textOut(ln)
    c.drawText(to)


def _paint_text(c, ent: dict, fonts: dict) -> None:
    """Перевод надписи: цвет оригинала, кегль замера, выключка блока,
    по вертикали — по центру строк оригинала; повёрнутая надпись — под её
    углом вокруг центра рамки."""
    b, pt = ent["b"], ent["b"]["_paint"]
    lines, size, step, font, h0 = ent["lines"], ent["size"], ent["step"], ent["font"], ent["h0"]
    if not lines:
        return
    c.saveState()
    c.setFillColorRGB(*pt["ink"])
    real = fonts.get("@" + font, "")
    synth_b = bool(pt["bold"]) and "b" not in real
    if synth_b:
        c.setStrokeColorRGB(*pt["ink"])
        c.setLineWidth(0.04 * size)
    widths = [_sw_of(ln, font, size) * h0 for ln in lines]
    block_h = (len(lines) - 1) * step + 0.72 * size
    if pt.get("arc"):
        _paint_arc(c, pt["arc"], lines[0], font, size, h0, synth_b)
        c.restoreState()
        return
    if pt["angle"]:
        cx, cy = (b["x0"] + b["x1"]) / 2.0, (b["top"] + b["bottom"]) / 2.0
        c.translate(cx, cy)
        c.rotate(pt["angle"])
        y = block_h / 2.0 - 0.72 * size
        for ln, w in zip(lines, widths):
            _paint_line(c, ln, -w / 2.0, y, font, size, h0, synth_b)
            y -= step
        c.restoreState()
        return
    for part in ent.get("parts") or []:
        size, step = part["size"], part["step"]
        if synth_b:
            c.setLineWidth(0.04 * size)
        p_lines = part["lines"]
        block_h = (len(p_lines) - 1) * step + 0.72 * size
        avail = part["top"] - part["bot"]
        y = part["top"] - 0.72 * size - max(0.0, (avail - block_h) / 2.0)
        for ln in p_lines:
            w = _sw_of(ln, font, size) * h0
            if ent["align"] == "center":
                x = (b["x0"] + b["x1"]) / 2.0 - w / 2.0
            elif ent["align"] == "right":
                x = b["x1"] - w
            else:
                x = b["x0"]
            _paint_line(c, ln, x, y, font, size, h0, synth_b)
            y -= step
    c.restoreState()


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

    def crop(self, i: int, x0: float, y0: float, x1: float, y1: float, scale: float):
        """Участок страницы (в точках PDF) картинкой RGB при `scale` — для
        надписи на рисунке: снимок всей страницы при 144 точках на дюйм
        мелковат, чтобы стереть буквы без следа. None — не вышло."""
        if self.doc is None:
            return None
        with PDFIUM_LOCK:
            try:
                page = self.doc[i]
                try:
                    cb = [float(v) for v in page.get_cropbox()]
                except Exception:
                    cb = [0.0, 0.0] + list(page.get_size())
                x0, x1 = max(cb[0], x0), min(cb[2], x1)
                y0, y1 = max(cb[1], y0), min(cb[3], y1)
                if x1 - x0 < 1 or y1 - y0 < 1:
                    page.close()
                    return None
                im = page.render(scale=scale, crop=(x0 - cb[0], y0 - cb[1], cb[2] - x1,
                                                    cb[3] - y1)).to_pil().convert("RGB")
                page.close()
                return im, (x0, y0, x1, y1)
            except Exception:
                return None

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
FREE_MAX_SHARE = float(os.environ.get("LAYOUT_FREE_MAX_SHARE", "0.6"))
FREE_MAX_LINES = int(os.environ.get("LAYOUT_FREE_MAX_LINES", "1"))
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


def _free_below(sample, rs: list, paper: float) -> None:
    """`below` у последнего места колонки — сколько пунктов ЧИСТОЙ бумаги
    под ней (ни краски, ни смены фона по всей ширине колонки), за вычетом
    зазора `FREE_BELOW_GAP` кеглей до того, что ниже, и не больше
    `FREE_BELOW_LINES` строк. Ячейка таблицы и подпись в схеме обычно
    стоят над пустым местом, и перевод, которому тесно, вправе спуститься
    туда, а не ужиматься; у колонки книги ниже — следующий абзац, и места
    там нет (зазор между абзацами меньше строки)."""
    if not sample or not rs:
        return
    im, scale, cb, gray = sample
    W, H = im.size
    last = rs[-1]
    size = max(max(sl["size"] for sl in rs), 1.0)
    pitch = (statistics.median(a["y"] - b["y"] for a, b in zip(rs, rs[1:]))
             if len(rs) >= 2 else 1.2 * size)
    x0 = min(sl["x0"] for sl in rs)
    x1 = max(sl["x1"] for sl in rs)
    top = last["y"] - 0.3 * size                     # под нижними выносными
    reach = (FREE_BELOW_LINES + FREE_BELOW_GAP) * pitch
    bot = max(cb[1], top - reach)
    px0, px1 = int((x0 - cb[0]) * scale), int((x1 - cb[0]) * scale) + 1
    py0 = int(max(0, H - (top - cb[1]) * scale))
    py1 = int(min(H, H - (bot - cb[1]) * scale))
    px0, px1 = max(0, px0), min(W, px1)
    if py1 - py0 < 2 or px1 - px0 < 2:
        return
    try:
        import numpy as np
        a = np.asarray(gray.crop((px0, py0, px1, py1)), dtype=np.uint8)
    except Exception:
        return
    dark = INK_DARK * paper * 255.0
    light = min(255.0, paper * 255.0 + FREE_PAPER_DELTA)
    rows = (a.min(axis=1) < dark) | (a.max(axis=1) > light)
    if not rows.any():
        # Ниже пусто до самого края досягаемости — это поле страницы, а не
        # ячейка или плашка: спускаться туда колонке книги нельзя.
        return
    hit = int(np.argmax(rows))
    free = hit / scale - FREE_BELOW_GAP * pitch
    if free >= 0.5 * pitch:
        last["below"] = round(min(free, FREE_BELOW_LINES * pitch), 2)


# Сплошная краска (доля высоты строки) шире стольких кеглей — графика.
SOLID_INK_COVER = 0.7
SOLID_INK_EM = 1.0


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
    # Сплошная заливка по всей высоте строки шире знака — это не буквы, а
    # графика: тень плашки, край рамки, полоса таблицы. Без этого правила
    # конец строки внутри плашки со скруглённой тенью уезжал до края листа,
    # и перевод печатался поверх соседней колонки.
    solid = None
    try:
        import numpy as np
        xa, xb = max(0, int(start)), min(W, int((cap - cb[0]) * scale))
        if xb > xa:
            a = np.asarray(gray.crop((xa, y0, xb, y1)), dtype=np.uint8)
            cover = (a < dark).mean(axis=0)
            solid_n = max(2, int(SOLID_INK_EM * size * scale))
            full = cover >= SOLID_INK_COVER
            k0 = 0
            while k0 < len(full):
                if full[k0]:
                    k1 = k0
                    while k1 < len(full) and full[k1]:
                        k1 += 1
                    if k1 - k0 >= solid_n:
                        solid = k0
                        break
                    k0 = k1
                else:
                    k0 += 1
    except Exception:
        solid = None
    if solid is not None:
        mins = mins[:solid]
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


# Шире этого (в кеглях) пробел выключки не делается: «реки» пробелов хуже
# рваного края — строка остаётся влево.
JUSTIFY_MAX_GAP = float(os.environ.get("LAYOUT_JUSTIFY_MAX_GAP", "0.75"))
# В истории страницы колонка выключена по ширине целиком: строка «рваная»
# посреди ровной колонки заметнее широкого пробела (слово-число «(220,222–225).»
# не переносится). Предел пробела там шире.
JUSTIFY_MAX_GAP_FLOW = float(os.environ.get("LAYOUT_JUSTIFY_MAX_GAP_FLOW", "1.6"))


def _justify_gaps(line: str, sd: dict, size: float, sw, font: str, hsc: float,
                  raster) -> "float | None":
    """Ширина пробела (без сужения) для выключки строки по ширине места,
    либо None — строка остаётся влево: растровая печать, одно слово, или
    пробел вышел бы шире `JUSTIFY_MAX_GAP` кегля."""
    if raster or not line or " " not in line.strip():
        return None
    words = line.split(" ")
    width = (sd["x1"] - sd["x"]) / max(hsc, 0.01)
    used = sum(sw(w, font, size) for w in words)
    gap = (width - used) / float(len(words) - 1)
    lim = JUSTIFY_MAX_GAP_FLOW if sd.get("_story") else JUSTIFY_MAX_GAP
    if gap <= sw(" ", font, size) * 1.001 or gap > lim * size:
        return None
    return gap


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


def build(pdf_bytes: bytes, layout: dict, texts: dict, extra: "list | None" = None,
          lang: "str | None" = None, sources: "dict | None" = None) -> tuple:
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
    hyph = _hyphenator(lang)
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
                    for run in _runs(sbs):
                        rs = [sbs[k] for k in run]
                        if not rs[-1].get("rot"):
                            _free_below(sample, rs, rs[-1]["_fill"][1])
                    b["_slots"] = sbs
                    continue
                if b.get("image") and _paint_measure(sampler, b):
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
    # Ширина начертания оригинала (`_width_ratio`) — по классу стиля во всём
    # документе (гарнитура, начертание, кегль): короткая подпись меряться
    # не может, но её класс измерен по длинным абзацам того же шрифта.
    if sources:
        meas: dict = {}
        members: dict = {}
        for idx, text, boxes in jobs:
            if not text or not boxes or boxes[0].get("image") or boxes[0].get("repeat"):
                continue
            sds = [sd for b in boxes if int(b["page"]) not in skip for sd in (b.get("_slots") or [])]
            flat = [sd for sd in sds if not sd.get("rot")]
            if not flat:
                continue
            fam = boxes[0].get("fam") or ""
            key = (fam, _face_style(flat[0].get("style") or ""),
                   "c" in (flat[0].get("style") or ""), round(flat[0]["size"] * 2) / 2.0)
            members.setdefault(key, []).append(flat)
            r = _width_ratio(flat, sources.get(idx) if isinstance(idx, int) else "", sw_vec,
                             lambda sd, fam=fam: _font_for(fonts, {"style": sd["style"], "fam": fam}))
            if r:
                meas.setdefault(key, []).append(r)
        nw = 0
        for key, rs in meas.items():
            rs.sort()
            tot, acc, med = sum(n for _r, n in rs), 0, rs[0][0]
            for r_, n in rs:
                acc += n
                if acc >= tot / 2.0:
                    med = r_
                    break
            h0 = min(1.0, max(HSCALE_WIDTH_MIN, med))
            for flat in members.get(key, []):
                for sd in flat:
                    sd["_h0"] = h0
                nw += 1
        stats["widthMeasured"] = nw
    plan: list = []
    img_plan: list = []
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
                    orig_sds = sds
                    sds, lines, f, rest, hsc = _fit_flow(text, orig_sds, psw, font_of, align, nospace,
                                                         hy=None if (nospace or use_r) else hyph)
                    fs, hss = [f] * len(sds), [hsc] * len(sds)
                    stats["reflowed"] = stats.get("reflowed", 0) + (1 if sds is not orig_sds else 0)
                font = font_of(sds[0])
                stats["sans" if font.startswith(FONT_NAME + "Sans") else
                      "mono" if font.startswith(FONT_NAME + "Mono") else "serif"] += 1
                shrunk = shrunk or min(fs) < 0.999
                over = over or bool(rest)
                stats["condensed"] += 1 if min(hss) < 0.999 else 0
                slot_plan.append((sds, lines, fs, rest, font_of, align, hss))
                slot_meta.append({"idx": idx, "text": text, "sw": psw, "nospace": nospace,
                                  "scattered": scat, "fam": fam,
                                  "hy": None if (nospace or use_r) else hyph,
                                  "orig": [sd for b in grp for sd in (b.get("_slots") or [])],
                                  "just": (not scat) and _justified(
                                      [sd for b in grp for sd in (b.get("_slots") or [])])})
                pages_used.update(int(sd["page"]) for sd in sds)
                continue
            if grp[0].get("_paint") and not use_r:
                ent = _paint_plan(grp[0], text, fonts, psw, hyph)
                if ent is not None:
                    img_plan.append(ent)
                    pages_used.add(int(grp[0]["page"]))
                    shrunk = shrunk or ent["f"] < 0.999
                    over = over or ent["over"]
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
    _stories(slot_plan, slot_meta, stats, page_slots)
    _harmonize(slot_plan, slot_meta, stats)
    _flow_groups(slot_plan, slot_meta, stats, sw_vec, page_slots)
    _resolve_collisions(slot_plan, slot_meta, jobs, reader, skip, stats, img_plan, plan)
    _size_report(slot_plan, slot_meta, plan, stats)
    stats.pop("_story_relay", None)


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
    for pi, (sds, lines, fs, rest, font_of, align, hss) in enumerate(slot_plan):
        # Выключка по ширине — у абзаца, выключенного так в оригинале
        # (`_justified`), у всех строк, кроме последней непустой (и кроме
        # строк, за которыми идёт хвост не влезшего — там уже не до вёрстки).
        just = bool(slot_meta[pi].get("just")) and align == "left" and not rest
        last_ne = max((k for k, ln in enumerate(lines) if ln), default=-1)
        for k, (sd, line) in enumerate(zip(sds, lines)):
            slots_by.setdefault(int(sd["page"]), []).append(
                (sd, line, fs[k], font_of, ("justify" if just and k < last_ne else align),
                 (k == len(sds) - 1), rest, hss[k]))
    img_by: dict = {}
    for ent in img_plan:
        img_by.setdefault(int(ent["b"]["page"]), []).append(ent)
    fill_by: dict = {}
    for m in slot_meta:
        for sd in m.get("orig") or []:
            fill_by.setdefault(int(sd["page"]), []).append(sd)
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
        # Стирается ОРИГИНАЛ — места самого абзаца, а не места перевода:
        # перевёрстанный абзац (`_regrid`) печатается в другие места.
        for sd in fill_by.get(i, []):
            colors, _paper, pad = sd["_fill"]
            if sd.get("rot"):
                _fill_rot(c, sd, colors, pad)
                continue
            # Сверху — почти без поля: прописные кончаются на 0.75–0.8 кегля,
            # а выше лежат хвосты букв строки над этой (у непереведённого
            # абзаца при интерлиньяже 1.15 их срезало бы).
            _fill_box(c, sd, pad, colors, top_pad=min(pad, 0.05 * sd["size"]))
        for ent in img_by.get(i, []):
            _paint_fill(c, ent)
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
        for ent in img_by.get(i, []):
            _paint_text(c, ent, fonts)
            stats["painted"] = stats.get("painted", 0) + 1
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
            jw = None
            if align == "justify":
                align = "left"
                jw = _justify_gaps(line, sd, size, sw, font, hsc, sd.get("_r"))
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
                if jw and k == 0:
                    # Выключка по ширине — слово за словом с расчётным
                    # пробелом: Tw у подмножеств TTF reportlab не действует
                    # (код пробела в подмножестве не 32).
                    xw = x
                    for wd in ln.split(" "):
                        if "i" in synth:
                            to.setTextTransform(1, 0, 0.21, 1, xw, y)
                        else:
                            to.setTextOrigin(xw, y)
                        to.textOut(wd)
                        xw += (sw(wd, font, size) + jw) * hsc
                else:
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
