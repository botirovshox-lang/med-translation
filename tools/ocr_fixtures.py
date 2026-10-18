#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Картинки-образцы для `tests/test_ocr_browser.js`: строки нарисованы
DejaVu Sans, и чтение у себя в браузере обязано вернуть их слово в слово.
Одна картинка на язык — проверяется распознавалка его группы (Ш4,
`docs/plans/ocr-paint-tools.md`). Тексты — те же, что ждёт тест (`CASES`).

    python tools/ocr_fixtures.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "frontend" / "vendor" / "fonts" / "sub" / "DejaVuSans.ttf"
OUT = ROOT / "tests" / "fixtures"

CASES = {
    "uzc": ["Ўпка сили касаллигини аниқлаш", "Қон таҳлили натижалари ҳақида",
            "Ғўза ва буғдой ҳосилдорлиги"],
    "kk": ["Өкпе ауруының белгілері және емі", "Әйелдер мен балаларға көмек"],
    "ky": ["Өпкө оорусу жана дарылоо", "Жаңы ыкмалар жөнүндө"],
    "mn": ["Эрүүл мэндийн яамны тушаал", "Өвчний шинж тэмдэг"],
    "sr": ["Ђачки дом и љекарска њега", "Министарство здравља Србије"],
}


def main():
    f = ImageFont.truetype(str(FONT), 21)
    for key, lines in CASES.items():
        im = Image.new("RGB", (760, 30 + 66 * len(lines)), "white")
        d = ImageDraw.Draw(im)
        for i, t in enumerate(lines):
            d.text((28, 26 + 66 * i), t, font=f, fill=(0, 0, 0))
        im.save(OUT / ("ocr_lines_%s.png" % key))
        print(key, len(lines))


if __name__ == "__main__":
    main()
