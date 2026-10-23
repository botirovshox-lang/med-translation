# -*- coding: utf-8 -*-
"""Ш52: на тёмной плашке со светлыми буквами линий ячейки не ищем — иначе
просветы плашки между белыми штрихами останавливают закраску строки.

    python tests/test_rule_dark_plate.py
"""
import os
import sys

sys.path.insert(0, "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from PIL import Image, ImageDraw  # noqa: E402
import layout_pdf as L  # noqa: E402

FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)[:300]))
    if not ok:
        FAILS.append(name)


def sample_of(bg, fg, rule=None):
    # лист 200×100 пт при масштабе 2: строка 8 пт — белые вертикальные штрихи букв
    im = Image.new("RGB", (400, 200), bg)
    d = ImageDraw.Draw(im)
    for x in range(40, 300, 9):
        d.rectangle((x, 80, x + 3, 100), fill=fg)
    if rule is not None:
        d.rectangle((rule, 0, rule + 1, 199), fill=(0, 0, 0))
    return (im, 2.0, (0.0, 0.0), im.convert("L"))


box = {"x0": 20.0, "x1": 150.0, "bottom": 50.0, "top": 60.0, "size": 8.0}
s_dark = sample_of((20, 60, 110), (255, 255, 255))
check("тёмная плашка, белые буквы — линий нет", L._rules_in(s_dark, box, 1.4) == [],
      L._rules_in(s_dark, box, 1.4))
s_light = sample_of((255, 255, 255), (20, 20, 20), rule=330)
got = L._rules_in(s_light, dict(box, x1=170.0), 1.4)
check("на светлой бумаге настоящая вертикаль линии ячейки находится",
      any(abs(r[0] - r[2]) < 0.01 and 160 < r[0] < 170 for r in got), got)
# Настоящая вырезка (инфографика CDC, общественное достояние): белые буквы
# на синей плашке — прежде находилось 5 «вертикалей», и закраска строки
# обрывалась на первой из них.
_png = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "dark_plate_lines.png")
im_r = Image.open(_png).convert("RGB")
s_real = (im_r, 2.0, (325.5, 304.5), im_r.convert("L"))
b_real = {"x0": 337.0, "x1": 407.9, "bottom": 315.7, "top": 324.5, "size": 8.0}
check("настоящая плашка: линий нет", L._rules_in(s_real, b_real, 1.44, 0.4) == [],
      L._rules_in(s_real, b_real, 1.44, 0.4))
_old = L.RULE_DARK_BG
L.RULE_DARK_BG = 1.0
check("без правила Ш52 поломка воспроизводится", len(L._rules_in(s_real, b_real, 1.44, 0.4)) > 0)
L.RULE_DARK_BG = _old

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
