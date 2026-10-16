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


def hand_font_files() -> list:
    """Существующие файлы рукописного семейства, по порядку предпочтения."""
    return [p for p in HAND_FONTS if p and Path(p).exists()]
