# -*- coding: utf-8 -*-
"""Шрифты печати перевода, общие для ОБОИХ путей: выгрузки PDF «как
в оригинале» (`layout_pdf`) и перерисовки картинок (`image_text`).

16.10.2026 (проект 89, Ф1): рукописный шрифт для конспекта завели только
в путь PDF, и та же страница, выгруженная картинкой, печаталась рубленым
гротеском — два списка шрифтов разошлись в первый же день. Список
рукописных файлов живёт здесь, и оба пути берут его отсюда.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_FONTS = str(Path(__file__).resolve().parent.parent / "frontend" / "vendor" / "fonts" / "sub")

# Рукопись (страница помечена моделью чтения как написанная от руки,
# `main._hand_image`). Marck Script (OFL) знает латиницу и кириллицу;
# букв, которых в нём нет (узбекские ў қ ғ ҳ ʻ, иероглифы, арабица),
# вызывающий проверяет покрытием и берёт обычный шрифт письменности.
HAND_FONTS = [os.environ.get("LAYOUT_FONT_HAND", ""), REPO_FONTS + "/MarckScript-Regular.ttf"]


# Машинопись (Х1): Liberation Mono (OFL, метрика Courier — машинописный вид),
# латиница, кириллица, греческий, узбекские буквы.
MONO_FONTS = [os.environ.get("LAYOUT_FONT_MONO", ""), REPO_FONTS + "/LiberationMono-Regular.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/cour.ttf"]
MONO_BOLD = [REPO_FONTS + "/LiberationMono-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "C:/Windows/Fonts/courbd.ttf"]
# Засечки (Х6): заголовок статьи с засечками печатался гротеском.
SERIF_FONTS = [REPO_FONTS + "/NotoSerif-Regular.ttf"]
SERIF_BOLD = [REPO_FONTS + "/NotoSerif-Bold.ttf"]
# Дореформенная печать (Х10): Old Standard TT (OFL) — воспроизведение
# «обыкновенной» антиквы конца XIX — начала XX века, которой набирали
# книги в старой орфографии; латиница, кириллица, узбекские и казахские
# буквы. Книга Чехова 1886 г. печаталась современным Noto Serif.
OLD_FONTS = [REPO_FONTS + "/OldStandard-Regular.ttf"]
OLD_BOLD = [REPO_FONTS + "/OldStandard-Bold.ttf"]
# Буквы, которые реформа 1918 г. убрала (ять, фита, ижица): в живом
# языке их нет ни у кого. «і» сюда не входит — она жива в украинском,
# белорусском и казахском.
_OLD_LETTERS = set("ѣѢѳѲѵѴ")
_CYR_LO, _CYR_HI = chr(0x400), chr(0x4FF)
OLD_ER_SHARE = float(os.environ.get("PAINT_OLD_ER_SHARE", "0.1"))


def pre_reform(src: str) -> bool:
    """Текст в дореформенной орфографии: ять/фита/ижица либо ер на конце
    слов («вечеръ») — не меньше трёх слов и `OLD_ER_SHARE` кириллических."""
    s = src or ""
    if any(ch in _OLD_LETTERS for ch in s):
        return True
    words = [w for w in "".join(ch if ch.isalpha() else " " for ch in s).split()
             if any(_CYR_LO <= ch <= _CYR_HI for ch in w)]
    er = sum(1 for w in words if len(w) > 1 and w[-1] in "ъЪ")
    return er >= 3 and er >= OLD_ER_SHARE * len(words)


def _exist(lst) -> list:
    return [p for p in lst if p and Path(p).exists()]


def hand_font_files() -> list:
    """Существующие файлы рукописного семейства, по порядку предпочтения."""
    return _exist(HAND_FONTS)


def family_files(fam: str, bold: bool = False) -> list:
    """Файлы семейства надписи («hand», «type», «serif», «old») по порядку; пусто —
    семейство не своё (рубленый по умолчанию)."""
    if fam == "hand":
        return _exist(HAND_FONTS)
    if fam == "type":
        return _exist((MONO_BOLD if bold else []) + MONO_FONTS)
    if fam == "serif":
        return _exist((SERIF_BOLD if bold else []) + SERIF_FONTS)
    if fam == "old":
        return _exist((OLD_BOLD if bold else []) + OLD_FONTS)
    return []
