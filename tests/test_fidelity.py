"""Замеры точности выгрузки (`backend/fidelity.py`).

Сторожит: правильная перерисовка проходит без предупреждений, а каждая
подсунутая поломка ловится своим кодом — надпись не стёрта (leftover),
перевод мельче (xh), тронут рисунок вне рамок (outside), пропал значок
(icons). Ни одного вызова модели; картинки рисуются здесь же.
"""
import io
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import numpy as np                                            # noqa: E402
from PIL import Image, ImageDraw, ImageFont                   # noqa: E402
import fidelity                                               # noqa: E402
import image_text as it                                       # noqa: E402

SUB = "frontend/vendor/fonts/sub/"
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


SRC = "The quick brown fox jumps over the lazy dog and runs away"
TR = "Tez jigarrang tulki dangasa it ustidan sakrab qochib ketadi"
pg = Image.new("RGB", (1200, 400), (250, 250, 250))
dr = ImageDraw.Draw(pg)
dr.rectangle((40, 220, 1160, 380), fill=(90, 140, 200))           # «рисунок»
f = ImageFont.truetype(SUB + "NotoSans-Regular.ttf", 34)
dr.text((40, 40), SRC, font=f, fill=(30, 30, 30))
lb = list(dr.textbbox((40, 40), SRC, font=f))
x_end = lb[2]
dr.ellipse((x_end + 8, 44, x_end + 36, 72), fill=(166, 206, 57))   # значок конца строки
lb_i = [lb[0], lb[1], x_end + 40, lb[3]]
buf = io.BytesIO()
pg.save(buf, "PNG")
ORIG = buf.getvalue()
ITEMS = [{"box": lb_i, "text": TR, "rows": 1, "lineH": lb[3] - lb[1], "lineBoxes": [lb_i],
          "src": SRC, "align": "left"}]

print("── 1. правильная перерисовка ──")
out, rep = it.render_target(ORIG, ITEMS)
r = fidelity.compare(ORIG, out, ITEMS)
print("   ", r["summary"], r["outside"], [{k: v for k, v in m.items() if k != "box"} for m in r["blocks"]])
check(out and r["blocks"] and not r["warn"], "предупреждений нет: %s" % r["warn"])
check(r["outside"] is not None and r["outside"] <= fidelity.FID_OUTSIDE, "рисунок вне рамок не тронут")

print("\n── 2. поломки ловятся ──")
r0 = fidelity.compare(ORIG, ORIG, ITEMS)
check("leftover" in r0["warn"], "надпись не стёрта — leftover: %s" % r0["warn"])
bad = Image.open(io.BytesIO(out)).convert("RGB").resize(pg.size)
d2 = ImageDraw.Draw(bad)
d2.rectangle((40, 230, 300, 300), fill=(250, 250, 250))
bb = io.BytesIO()
bad.save(bb, "PNG")
r1 = fidelity.compare(ORIG, bb.getvalue(), ITEMS)
check("outside" in r1["warn"], "тронут рисунок вне рамок — outside: %s (%s)" % (r1["warn"], r1["outside"]))
small = Image.open(io.BytesIO(ORIG)).convert("RGB")
d3 = ImageDraw.Draw(small)
d3.rectangle((lb_i[0], 30, lb_i[2], lb_i[3]), fill=(250, 250, 250))
d3.text((40, 46), TR, font=ImageFont.truetype(SUB + "NotoSans-Regular.ttf", 20), fill=(30, 30, 30))
bs = io.BytesIO()
small.save(bs, "PNG")
r2 = fidelity.compare(ORIG, bs.getvalue(), ITEMS)
print("   ", [{k: v for k, v in m.items() if k != "box"} for m in r2["blocks"]])
check("xh" in r2["warn"] and "icons" in r2["warn"],
      "перевод мельче и значок пропал — xh, icons: %s" % r2["warn"])
check(fidelity.compare(ORIG, b"junk", ITEMS)["warn"] == ["unreadable"], "нечитаемый ответ не роняет замер")
r3 = fidelity.compare(ORIG, Image.new("RGB", (10, 10)), ITEMS)
check(r3["warn"] == ["size"], "разный размер картинок — size")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
