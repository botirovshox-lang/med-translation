"""Х20 (чужая краска в рамке не стирается) и Х21 (неразрывный пробел не рвёт строку).

Ни одного вызова модели; картинки рисуются здесь же.
"""
import io
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import numpy as np                                            # noqa: E402
from PIL import Image, ImageDraw, ImageFont                   # noqa: E402
import image_text as it                                       # noqa: E402
import text_paint as tp                                       # noqa: E402
import layout_pdf                                             # noqa: E402
import fidelity                                               # noqa: E402

SUB = "frontend/vendor/fonts/sub/"
NB = chr(0xA0)
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("── Х20. печать поверх строки не стирается ──")
SRC = "The parties have signed this agreement on the date below"
TR = "Tomonlar ushbu shartnomani quyidagi sanada imzoladilar"
pg = Image.new("RGB", (1300, 260), (250, 250, 250))
dr = ImageDraw.Draw(pg)
f = ImageFont.truetype(SUB + "NotoSans-Regular.ttf", 34)
dr.text((40, 90), SRC, font=f, fill=(30, 30, 30))
lb = list(dr.textbbox((40, 90), SRC, font=f))
dr.ellipse((700, 50, 830, 180), outline=(40, 70, 190), width=6)            # синяя печать поверх строки
dr.text((735, 100), "SEAL", font=ImageFont.truetype(SUB + "NotoSans-Regular.ttf", 22), fill=(40, 70, 190))
buf = io.BytesIO()
pg.save(buf, "PNG")
ORIG = buf.getvalue()
items = [{"box": lb, "text": TR, "rows": 1, "lineH": lb[3] - lb[1], "lineBoxes": [lb], "src": SRC}]
a = np.asarray(pg).astype(int)
blue = (a[..., 2] - a[..., 0] > 80)
out, rep = it.render_target(ORIG, items)
o = np.asarray(Image.open(io.BytesIO(out)).convert("RGB").resize(pg.size)).astype(int)
inbox = np.zeros(blue.shape, bool)
inbox[lb[1]:lb[3], lb[0]:lb[2]] = True
kept = ((o[..., 2] - o[..., 0] > 80) & blue & inbox).sum() / max(1, (blue & inbox).sum())
check(rep and rep[0].get("ok") and kept > 0.6, "синяя печать в рамке строки сохранилась: %.0f%%" % (100 * kept))
fm = tp.foreign_marks(np.asarray(pg)[lb[1]:lb[3], lb[0]:lb[2]].copy(),
                      np.ones((lb[3] - lb[1], lb[2] - lb[0]), bool), [(0, lb[3] - lb[1] - 1)],
                      (30, 30, 30), (250, 250, 250))
check(fm is not None and fm.any(), "крупная цветная краска найдена как чужая")
plate = np.full((60, 600, 3), 250, np.uint8)
plate[:, 300:] = (220, 120, 40)                                           # цветная плашка под текстом
pm_ = np.zeros((60, 600), bool)
pm_[20:40, 320:560] = True
check(tp.foreign_marks(plate, pm_, [(10, 50)], (30, 30, 30), (250, 250, 250)) is None,
      "сплошная цветная плашка — фон, а не печать")
pgc = Image.new("RGB", (1300, 260), (250, 250, 250))
ImageDraw.Draw(pgc).text((40, 90), SRC, font=f, fill=(200, 30, 30))
ac = np.asarray(pgc)[lb[1]:lb[3], lb[0]:lb[2]].copy()
check(tp.foreign_marks(ac, np.ones(ac.shape[:2], bool), [(0, ac.shape[0] - 1)], (200, 30, 30),
                       (250, 250, 250)) is None, "цветной текст чужой краской не считается")
r = fidelity.compare(ORIG, out, items)
check("outside" not in r["warn"] and "leftover" not in r["warn"], "замер выгрузки чистый: %s" % r["warn"])

print("\n── Х21. неразрывный пробел ──")
check(tp.words("5" + NB + "мг и 12" + chr(0x202F) + "%  тест") == ["5" + NB + "мг", "и", "12" + NB + "%", "тест"],
      "слова режутся только по разрешённым пробелам; узкий неразрывный печатается обычным")
check(tp.words("а" + chr(0x2060) + "б " + NB + "в" + NB) == ["аб", "в"], "соединитель снят, неразрывный на краю слова снят")
check(tp.words("") == [] and tp.words(" a\tb\nc ") == ["a", "b", "c"], "обычные пробелы — как прежде")
from reportlab.pdfbase import pdfmetrics                      # noqa: E402
fonts = layout_pdf._register_fonts(set("доза 5 мг в сутки"))
fn = layout_pdf._font_for(fonts, {"style": "", "fam": "sans"})
txt = "доза составляет 5" + NB + "мг в сутки"
w = pdfmetrics.stringWidth("доза составляет 5", fn, 10) + 2
lines = layout_pdf._wrap(txt, w, 10, 0.0, pdfmetrics.stringWidth, fn)
check(not any(ln.endswith("5") for ln in lines) and any("5" + NB + "мг" in ln for ln in lines),
      "PDF: «5 мг» не разорваны переносом: %s" % lines)
img = Image.new("RGB", (10, 10))
d = ImageDraw.Draw(img)
fi = ImageFont.truetype(SUB + "NotoSans-Regular.ttf", 20)
lines2 = it._wrap(d, txt, fi, d.textlength("доза составляет 5", font=fi) + 2, split=False)
check(not any(ln.endswith("5") for ln in lines2), "картинка: «5 мг» не разорваны: %s" % lines2)

print("\n── Х22. кинсоку из данных ──")
import linebreak                                              # noqa: E402
import media                                                  # noqa: E402
check(linebreak.fix_break("今日は。です", 3) == 2, "строка не начинается «。»")
check(linebreak.fix_break("今日は「晴れ」", 4) == 3, "строка не кончается «「»")
check(linebreak.fix_break("abc", 2) == 2, "без запрещённых знаков разрез прежний")
check(media._NO_START is linebreak.NO_START and media._NO_END is linebreak.NO_END,
      "субтитры берут наборы из того же файла")
check(set("。、，．・：；？！）」』】〕〉》ーぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々ゝゞ,.!?;:)") == set(linebreak.NO_START)
      and set("「『（【〔〈《([“‘") == set(linebreak.NO_END), "у субтитров наборы прежние (вывод не меняется)")
u = it._cjk_units("説明「重要」です")
check(not any(x.endswith("「") for x in u) and not any(x.startswith("」") for x in u),
      "картинка: «「» держится со следующим знаком, «」» — с предыдущим: %s" % u)
check(layout_pdf._break_point("今日は。です", 3) == 2, "PDF: разрез строки без пробелов с кинсоку")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
