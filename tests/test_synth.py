"""Синтетические страницы (backend/synth.py): рецепты из synth_recipes.json
проходят раскраску выгрузки и замеры fidelity. Ловит ОТКАТЫ правил раскраски;
покрытием каталога не является (оговорка — в докстроке synth.py).

Х23 сторожится здесь же: строка без нижних выносных («Results and
discussion») не красится мельче и жирнее оригинала.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import synth  # noqa: E402
import text_paint as tp  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# 1. Выносы — по шрифту, без списка букв.
check(not tp.has_descender("Results and discussion"), "без выносов: Results and discussion")
check(tp.has_descender("playing"), "выносы: playing")
check(tp.has_descender("Результаты"), "выносы: кириллица у, р")
check(not tp.has_descender("АБВ"), "без выносов: АБВ")
check(not tp.has_descender("2024"), "без букв — без выносов")

# 2. Псевдоперевод — детерминирован, имена с номерами остаются.
d = synth.load()
a = synth.pseudo("Kana Okano1 wrote this", "uz", 1.15, 0, True, d)
b = synth.pseudo("Kana Okano1 wrote this", "uz", 1.15, 0, True, d)
check(a == b, "псевдоперевод детерминирован")
check("Kana Okano1" in a, "имя с номером перенесено как есть")
check(" " not in synth.pseudo("one two", "zh", 0.6, 0, False, d), "иероглифы — без пробелов")

# 3. Рецепты: раскраска без предупреждений, кроме названных.
KNOWN = {}
for rec in d["recipes"]:
    r = synth.run(rec, 0, d)
    warn = set(r["fidelity"].get("warn") or [])
    extra = warn - KNOWN.get(rec["id"], set())
    check(r["out"] is not None, "%s: раскрашено" % rec["id"])
    check(not extra, "%s: предупреждений нет (%s)" % (rec["id"], sorted(warn)))
    if rec["id"] == "heading-colour":
        xh = r["fidelity"]["summary"].get("xh")
        check(xh is not None and xh >= 0.8, "Х23: заголовок без выносов не мельчает (xh=%s)" % xh)
    if rec["id"] == "caption-on-tint":
        xh = r["fidelity"]["summary"].get("xh")
        rows = [x for x in (r["report"] or []) if x and x.get("ok")]
        check(xh is not None and xh >= 0.9, "Х24: одна строка не мельчает, а уходит во вторую (xh=%s)" % xh)

# 4. Х24: под строкой рисунок (линии схемы) — вторая строка туда не ложится.
import copy  # noqa: E402
cap = copy.deepcopy(next(r for r in d["recipes"] if r["id"] == "caption-on-tint"))
cap["rules"] = [[40, 75 + 8 * k, 1060, 75 + 8 * k, 2] for k in range(8)]
r = synth.run(cap, 0, d)
xh = r["fidelity"]["summary"].get("xh")
check(xh is not None and xh < 0.9,
      "Х24: по линиям схемы под строкой вторая строка не ложится (xh=%s — ужата в одну)" % xh)

# 5. Х25: код и линия поля — не текст: остаются байт в байт, перевод — мимо них.
import io  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def _arr(png):
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)


for rid in ("qr-label", "signature-field"):
    rec = next(r_ for r_ in d["recipes"] if r_["id"] == rid)
    r = synth.run(rec, 0, d)
    o = _arr(r["orig"])
    t = np.asarray(Image.open(io.BytesIO(r["out"])).convert("RGB").resize((o.shape[1], o.shape[0]))).astype(int)
    om = tp.object_marks(o.astype(np.uint8), 30)
    check(om is not None and any(b_[4] == ("code" if rid == "qr-label" else "field") for b_ in om[1]),
          "%s: объект найден (%s)" % (rid, om and [b_[4] for b_ in om[1]]))
    if om is not None:
        x0, y0, x1, y1, _ = om[1][0]
        diff = np.abs(o[y0:y1, x0:x1] - t[y0:y1, x0:x1]).max(axis=-1)
        check(float((diff > 60).mean()) < 0.03, "%s: объект цел после перерисовки (%.3f)"
              % (rid, float((diff > 60).mean())))
    check(not (set(r["fidelity"].get("warn") or [])), "%s: замеры чисты" % rid)
    if rid == "qr-label":
        import cv2  # noqa: E402
        g = cv2.cvtColor(t.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        val, _p, _q = cv2.QRCodeDetector().detectAndDecode(cv2.copyMakeBorder(g, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=250))
        check(val == rec["lines"][0]["qr"], "Х25: QR после перерисовки читается (%r)" % val)

# Подчёркивание (буквы над линией) — не поле: стирается с текстом, как прежде.
im = Image.new("RGB", (900, 120), (250, 250, 250))
dr = ImageDraw.Draw(im)
f = ImageFont.truetype(str(synth.FONTS / "NotoSans-Regular.ttf"), 34)
dr.text((30, 30), "Important underlined notice here", font=f, fill=(20, 20, 20))
bb = dr.textbbox((30, 30), "Important underlined notice here", font=f)
dr.line((bb[0], bb[3] + 4, bb[2], bb[3] + 4), fill=(20, 20, 20), width=2)
om = tp.object_marks(np.asarray(im), 40)
check(om is None or not any(b_[4] == "field" for b_ in om[1]), "Х25: подчёркивание текста — не поле")

# Плавное фото (шум, растянутый в пятна) — не код: без проверки
# двухцветности детекторы находили тут три «кода» (замер критика).
import cv2  # noqa: E402
g = np.random.RandomState(2).rand(40, 40)
g = cv2.resize((g * 255).astype(np.uint8), (1500, 1500), interpolation=cv2.INTER_LINEAR)
om = tp.object_marks(np.stack([g] * 3, -1).copy(), 40)
check(om is None or not any(b_[4] == "code" for b_ in om[1]), "Х25: плавное фото — не код")
check(tp.typed_rule("Name: ________") and not tp.typed_rule("Name: John"),
      "Х25: набранные подчёркивания узнаются по оригиналу")
im = Image.new("RGB", (900, 120), (250, 250, 250))
dr = ImageDraw.Draw(im)
dr.text((30, 30), "Name:", font=f, fill=(20, 20, 20))
dr.line((160, 66, 700, 66), fill=(20, 20, 20), width=2)
om = tp.object_marks(np.asarray(im), 40, fields=not tp.typed_rule("Name: ________"))
check(om is None, "Х25: подчёркивания из оригинала — текст, а не поле (их повторит перевод)")

print("ВСЁ ПРОШЛО" if not FAILS else "ПРОВАЛЕНО: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
