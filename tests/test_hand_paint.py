"""Раздел Ф: перевод, вписанный в фото рукописного конспекта (и любого
абзаца на картинке), — как в оригинале.

Сторожит (проект 89, конспект в клетку RU→EN, 16.10.2026):
  Ф1. строки абзаца — по рамкам строк: база, шаг, отступ; начало строки —
      по краске, а не по рамке (буквица, слово отдельной рамкой);
  Ф2. почерк не сжимается по ширине: кегль по ширине краски;
  Ф3. длинный перевод — в свободные строки ниже тем же шагом, потом мельче
      буквами при том же шаге, и только потом теснее; вышло за место —
      сказано (`over`);
  Ф4. один кегль, шаг и цвет у абзацев одного класса на странице;
  Ф5. плашка на неровном фоне — восстановленный фон, а не серый
      прямоугольник;
  Ф6. бумага с узором (клетка, линейка) стирается по модели, а не
      размыванием; ложный узор экзамен не сдаёт;
  Ф7. толщина пера рукописи;
  Ф1/общий шрифт: рукописный список один на оба пути печати;
  Х9. засечки определяются по буквам, когда чтение о них не сказало;
  Х10. дореформенная печать — старой антиквой, кегль — по строчным;
  Х11. полужирный от размытия снимается площадью краски;
  Х12. замер штриха — по середине тона;
  Х13. цвет краски — по оси штриха, обводка — до плотности набора; PDF — те же правила.
Без сети и без вызовов модели.
"""
import io
import os
import re
import sys

sys.path.insert(0, "backend")
import numpy as np                                            # noqa: E402
from PIL import Image, ImageDraw, ImageFont                   # noqa: E402
import text_paint as tp                                       # noqa: E402
import image_text as it                                       # noqa: E402
import print_fonts                                            # noqa: E402

fail = []


def check(ok, msg):
    print(("  OK   " if ok else "  FAIL ") + msg)
    if not ok:
        fail.append(msg)


print("\n── Ф1. геометрия абзаца по рамкам строк ──")
lbs = [[175, 16, 782, 54], [112, 66, 790, 116], [121, 123, 776, 167],
       [127, 179, 747, 220], [125, 239, 772, 274], [115, 292, 684, 330]]
g = tp.line_geometry(lbs, None, 42.0)
check(g is not None and g["regular"], "ровный ритм строк узнан")
check(g and 48 <= g["pitch"] <= 60, "шаг строк ≈ 55: %s" % (g and round(g["pitch"], 1)))
check(g and 50 <= g["indent"] <= 70, "красная строка ≈ 60: %s" % (g and g["indent"]))
check(g and 110 <= g["left"] <= 125, "левый край — медиана остальных строк: %s" % (g and g["left"]))
check(g and g["right"] < 790, "правый край — не самая длинная строка: %s" % (g and g["right"]))
# Рамка первой строки начинается с третьего слова (слово за буквицей отдано
# отдельно) — по рамке это отступ в девять кеглей; это не отступ.
far = [[351, 209, 1208, 269]] + [[63, 267 + k * 53, 1206, 321 + k * 53] for k in range(8)]
g2 = tp.line_geometry(far, None, 30.0)
check(g2 and g2["indent"] == 0.0, "сдвиг больше INDENT_MAX кеглей — не отступ: %s" % (g2 and g2["indent"]))
# Начало строки — по краске: маска знает буквы левее рамки.
mask = np.zeros((800, 1250), bool)
for k in range(9):
    y = 230 + k * 53
    x0 = 130 if k == 0 else 63
    mask[y:y + 25, x0:1200] = True
g3 = tp.line_geometry(far, mask, 30.0)
check(g3 and 55 <= g3["indent"] <= 80, "начало первой строки — по краске: отступ %s" % (g3 and g3["indent"]))
check(tp.line_geometry(lbs[:1], None, 40) is None, "одна строка — ритма нет")
irr = [[100, 0, 700, 30], [100, 40, 700, 70], [100, 200, 700, 230], [100, 240, 700, 270]]
gi = tp.line_geometry(irr, None, 25)
check(gi is not None and not gi["regular"], "неровный шаг (форма, таблица) — ритм не признан")

print("\n── Ф2. почерк не сжимается ──")
em, h0 = tp.calibrate(43.0, 500.0, 800.0, hand=True)
check(h0 == 1.0 and abs(em - 43.0 * 500 / 800) < 1e-6, "рукопись: кегль по ширине, сжатия нет")
em2, h02 = tp.calibrate(43.0, 500.0, 800.0, hand=False, hmin=0.74)
check(em2 == 43.0 and abs(h02 - 0.74) < 1e-9, "печать — как прежде (кегль по высоте, h0 ≥ пола)")
em3, h03 = tp.calibrate(43.0, 900.0, 800.0, hand=True)
check(em3 == 43.0 and h03 == 1.0, "почерк шире шрифта — кегль не растёт выше измеренного")

print("\n── Ф3. раскладка с ритмом ──")
mw = lambda t, s: len(t) * s * 0.5                            # noqa: E731
text = " ".join(["word"] * 40)
size, step, lines, over = tp.fit_rhythm(text, 400, 20.0, 50.0, 4, 0, mw)
check(not over and step == 50.0 and size < 20.0 and size >= 20.0 * tp.FIT_FLOOR,
      "мельче буквами, шаг тот же: кегль %.1f шаг %.1f" % (size, step))
size, step, lines, over = tp.fit_rhythm(text, 400, 20.0, 50.0, 4, 2, mw)
check(size == 20.0 and step == 50.0 and len(lines) <= 6 and not over,
      "свободные строки ниже берутся раньше уменьшения: %d строк" % len(lines))
size, step, lines, over = tp.fit_rhythm(" ".join(["word"] * 400), 400, 20.0, 50.0, 3, 0, mw)
check(over and size == 20.0 * tp.FIT_HARD, "не влезло и на полу — сказано (over)")
size, step, lines, over = tp.fit_rhythm("one two three", 400, 20.0, 50.0, 3, 0, mw, first_indent=380)
check(len(lines) >= 2 and lines[0] == "one", "первая строка короче на отступ: %s" % lines)
size, step, lines, over = tp.fit_rhythm(text, 400, 16.0, 50.0, 6, 0, mw, fixed=True)
check(size == 16.0 and step == 50.0, "кегль страницы — без ужатия")

print("\n── Ф4. классы страницы ──")
cls = tp.even_classes([{"em": 27, "fam": "hand"}, {"em": 29, "fam": "hand"}, {"em": 60, "fam": "hand"},
                       {"em": 28, "fam": ""}])
check(cls == [[0, 1]], "два абзаца близкого кегля одного семейства — класс: %s" % cls)
check(tp.even_step([55, 54, 56]) == 55 and tp.even_step([30, 55]) is None, "общий шаг — только у близких")

print("\n── Ф6. бумага в клетку стирается по модели ──")
H, W, P = 240, 420, 24
yy, xx = np.mgrid[0:H, 0:W]
light = 150 + 60 * (yy / H)                                  # перепад света фото
grid = ((xx % P) < 2) | ((yy % P) < 2)
clean = np.dstack([np.where(grid, light - 35, light)] * 3).clip(0, 255).astype(np.uint8)
hole = np.zeros((H, W), bool)
for r in range(3):
    hole[30 + r * 70:58 + r * 70, 40:380] = True               # полосы стёртых строк
dirty = clean.copy()
dirty[hole] = 20                                              # «чернила»
per = tp._paper_periodic(dirty, hole, 56.0, 40.0)
check(per is not None, "период клетки найден, модель сдала экзамен")
if per is not None:
    err = np.abs(per[hole].astype(int) - clean[hole].astype(int)).mean()
    import cv2
    tel = cv2.inpaint(dirty, hole.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)
    err_t = np.abs(tel[hole].astype(int) - clean[hole].astype(int)).mean()
    check(err < 6 and err < 0.5 * err_t, "клетка восстановлена: ошибка %.1f против %.1f у размытия" % (err, err_t))
flatimg = np.dstack([light] * 3).astype(np.uint8)
check(tp._paper_periodic(flatimg, hole, 56.0, 40.0) is None, "без узора — модели нет, прежнее стирание")
rng = np.random.RandomState(3)
noise = (np.dstack([light] * 3) + rng.randint(-25, 25, (H, W, 1))).clip(0, 255).astype(np.uint8)
check(tp._paper_periodic(noise, hole, 56.0, 40.0) is None, "шум (ложный узор) экзамен не сдаёт")

print("\n── Ф3. свободная строка: клетка — не буквы ──")
strip = clean[100:140, 40:380].copy()
check(not tp.has_letters(strip, 30.0), "в клетке без надписей букв нет")
im_ = Image.fromarray(strip.copy())
ImageDraw.Draw(im_).text((10, 2), "Hello world", font=ImageFont.truetype(it.font_path(), 30), fill=(10, 10, 10))
check(tp.has_letters(np.asarray(im_), 30.0), "строка с надписью — занята")

print("\n── Ф1. рукописный шрифт — один список на оба пути ──")
hf = print_fonts.hand_font_files()
check(hf and hf[0].endswith("MarckScript-Regular.ttf"), "рукописный файл есть: %s" % hf)
check(it._paint_font(False, "Bacterial cell", "hand") == hf[0], "картинка: рукопись — рукописным шрифтом")
check(it._paint_font(False, "Bacterial cell", "") != hf[0], "печать — рубленым")
uz = it._paint_font(False, "qoʻshimcha ўқ ғҳ", "hand")
check(uz and not uz.endswith("MarckScript-Regular.ttf"), "узбекских букв нет — запасной шрифт: %s" % uz)
lp = open("backend/layout_pdf.py", encoding="utf-8").read()
check('_print_fonts().HAND_FONTS' in lp, "путь PDF берёт тот же список")
src = open("backend/main.py", encoding="utf-8").read()
m_ = re.search(r"def _export_images\(.*?\n(?=def )", src, re.S)
body = m_.group(0) if m_ else ""
check('"lineBoxes": b.get("lineBoxes")' in body and '"fam": im_fam' in body and "_hand_image(im)" in body,
      "выгрузка картинки несёт рамки строк и семейство страницы")
check("obstacles=obstacles" in body, "и рамки всех надписей — для свободных строк")
check("Transcribe, do not edit" in src, "чтение картинки: переписывать, не править (Ф8)")

print("\n── сквозной: конспект в клетку из двух абзацев ──")
fpath = hf[0]
Wd, Hd, Pt = 900, 820, 27
yy, xx = np.mgrid[0:Hd, 0:Wd]
light = 160 + 50 * (yy / Hd)
grid = ((xx % Pt) < 2) | ((yy % Pt) < 2)
base_img = np.dstack([np.where(grid, light - 30, light)] * 3).clip(0, 255).astype(np.uint8)
page = Image.fromarray(base_img.copy())
dr = ImageDraw.Draw(page)
fnt = ImageFont.truetype(fpath, 40)
blocks, srcs = [], []
y = 40
for pi, n in enumerate((5, 7)):
    lbx = []
    for k in range(n):
        x0 = 140 if k == 0 else 80
        line = "Бактериальная клетка устроена проще" if k < n - 1 else "организмов."
        dr.text((x0, y), line, font=fnt, fill=(15, 15, 20), stroke_width=2, stroke_fill=(15, 15, 20))
        bb = dr.textbbox((x0, y), line, font=fnt, stroke_width=2)
        lbx.append(list(bb))
        y += 2 * Pt
    blocks.append(lbx)
    y += 2 * Pt
buf = io.BytesIO()
page.save(buf, "PNG")
items = []
en = ("The bacterial cell is usually much more simply structured than the cells of other "
      "living organisms, and it is often surrounded by a protective capsule.")
for lbx in blocks:
    box = [min(b[0] for b in lbx), min(b[1] for b in lbx), max(b[2] for b in lbx), max(b[3] for b in lbx)]
    items.append({"box": box, "text": en, "rows": len(lbx), "lineH": 40, "lineBoxes": lbx,
                  "src": "Бактериальная клетка устроена проще " * len(lbx), "fam": "hand", "align": "left"})
out, rep = it.render_target(buf.getvalue(), items, obstacles=[i_["box"] for i_ in items])
check(out is not None and all(r.get("ok") and r.get("paint") for r in rep),
      "оба абзаца вписаны по маске букв, плашки нет: %s" % rep)
check(len({r.get("size") for r in rep}) == 1 and all(r.get("even") for r in rep),
      "один кегль у обоих абзацев")
check(all(r.get("erase") == "periodic" for r in rep), "клетка стёрта по модели")
if out is not None:
    res = np.asarray(Image.open(io.BytesIO(out)).convert("L")).astype(int)
    # Строка между строками первого абзаца (бывшая пустая клетка) — бумага.
    gap_y = blocks[0][0][3] + 4
    stripe = res[gap_y:gap_y + 3, 300:700]
    check(stripe.min() > 60, "между строками перевода — бумага, а не краска")
    # Перевод стоит на базах оригинала: краска есть в полосе первой строки.
    b0 = blocks[0][0]
    check((res[b0[1]:b0[3], b0[0]:b0[2]] < 60).mean() > 0.01, "перевод на месте первой строки")

print("\n── ревью: края раскладки ──")
size, step, lines, over = tp.fit_rhythm("see https://example.org/very/long/path/without/breaks here",
                                        200, 20.0, 30.0, 3, 0, mw)
check(lines and over, "слово шире строки — строкой с выходом, а не пусто: %s" % lines)
size, step, lines, over = tp.fit_rhythm("https://example.org/very/long/path/without/breaks",
                                        200, 20.0, 30.0, 3, 0, mw, fixed=True)
check(lines and over, "и при кегле страницы")
check(tp._paper_periodic(np.zeros((2000, 1500, 3), np.uint8), np.ones((2000, 1500), bool), 40, 30) is None,
      "большая вырезка — прежнее стирание (память воркера)")
check(it._cjk_units("可是突然“。作者") == ["可", "是", "突", "然“。", "作", "者"],
      "закрывающая кавычка перед «。» строку не начинает: %s" % it._cjk_units("可是突然“。作者"))
check(it._cjk_units("“作者") == ["“作", "者"] or it._cjk_units("“作者")[0].startswith("“"),
      "открывающая кавычка остаётся с началом")
# Абзац с рамками строк, перевод не влезает и тесно, внизу соседний абзац:
# прежняя дорога (в рамке абзаца или плашка), а не строки поверх соседа.
page2 = Image.fromarray(base_img.copy())
d2 = ImageDraw.Draw(page2)
lb2 = []
for k_ in range(3):
    d2.text((80, 60 + k_ * 54), "Бактериальная клетка устроена", font=fnt, fill=(15, 15, 20),
            stroke_width=2, stroke_fill=(15, 15, 20))
    lb2.append(list(d2.textbbox((80, 60 + k_ * 54), "Бактериальная клетка устроена", font=fnt, stroke_width=2)))
d2.text((80, 60 + 3 * 54 + 10), "Next paragraph right below", font=fnt, fill=(15, 15, 20))
nb = list(d2.textbbox((80, 60 + 3 * 54 + 10), "Next paragraph right below", font=fnt))
b2 = io.BytesIO()
page2.save(b2, "PNG")
box2 = [min(b[0] for b in lb2), min(b[1] for b in lb2), max(b[2] for b in lb2), max(b[3] for b in lb2)]
long_en = " ".join(["bacterial membrane composition"] * 40)
out2, rep2 = it.render_target(b2.getvalue(), [{"box": box2, "text": long_en, "rows": 3, "lineH": 40,
                                                "lineBoxes": lb2, "src": "Бактериальная клетка " * 3,
                                                "fam": "hand", "align": "left"}], obstacles=[nb])
if out2 is not None:
    res2 = np.asarray(Image.open(io.BytesIO(out2)).convert("RGB")).astype(int)
    orig2 = np.asarray(page2.convert("RGB")).astype(int)
    below = np.abs(res2[nb[1]:nb[3], nb[0]:nb[2]] - orig2[nb[1]:nb[3], nb[0]:nb[2]]).max()
    check(below < 40, "соседний абзац ниже не тронут (разница %d)" % below)
check(all(not r.get("over") for r in rep2 if r.get("ok")), "не влезшее не печатается с выходом: %s" % rep2)
url_items = [dict(items[0], text="https://example.org/" + "x" * 200)]
try:
    out3, rep3 = it.render_target(buf.getvalue(), url_items, obstacles=[items[0]["box"]])
    check(True, "абзац из одного неразрывного слова не роняет выгрузку: %s" % rep3)
except Exception as e:
    check(False, "абзац из одного неразрывного слова роняет выгрузку: %r" % e)

print("\n── ревью: путь PDF ──")
import layout_pdf                                             # noqa: E402
fonts = layout_pdf._register_fonts("Bacterial cell")
hn = layout_pdf._font_for(fonts, {"style": "", "fam": "hand"})
check(layout_pdf._font_file(hn).endswith("MarckScript-Regular.ttf"),
      "толщина пера мерится по файлу шрифта: %s" % layout_pdf._font_file(hn))
check(tp.font_stem(layout_pdf._font_file(hn)) > 0, "штрих рукописного шрифта измерен")
check(not layout_pdf._font_has(hn, "ўқ漢"), "покрытие исходника проверяется")
lps = open("backend/layout_pdf.py", encoding="utf-8").read()
check('"b" if (pt["bold"] and not hand)' in lps, "рукопись с толстым пером — не жирный гротеск")

print("\n── Х1. машинопись узнаётся по шагу знака ──")
def typed_page(path, txt_lines, size=28):
    im_ = Image.new("RGB", (1000, 60 * len(txt_lines) + 40), (238, 238, 232))
    d_ = ImageDraw.Draw(im_)
    f_ = ImageFont.truetype(path, size)
    lbx = []
    for k_, t_ in enumerate(txt_lines):
        d_.text((40, 30 + k_ * 60), t_, font=f_, fill=(40, 40, 40))
        lbx.append(list(d_.textbbox((40, 30 + k_ * 60), t_, font=f_)))
    return im_, lbx
TL = ["The plan provided for the completion in all pavilions",
      "of plastering work and of painting work of asphalt and",
      "of crushed stone surfacing and the laying of the lines",
      "of water supply and sewerage networks of drains and of"]
mono_path = print_fonts.family_files("type")[0]
for path, want in ((mono_path, True), ("frontend/vendor/fonts/sub/NotoSerif-Regular.ttf", False),
                   ("frontend/vendor/fonts/sub/NotoSans-Regular.ttf", False)):
    im_, lbx = typed_page(path, TL)
    a_ = np.asarray(im_.convert("L")) < 150
    sc = tp.mono_score(a_, lbx, len(" ".join(TL)))
    check(sc is not None and ((sc >= tp.MONO_COH) == want),
          "%s: машинопись=%s (мера %.2f)" % (os.path.basename(path), want, sc or -1))
check(print_fonts.family_files("type") and print_fonts.family_files("type")[0].endswith("LiberationMono-Regular.ttf"),
      "машинописный шрифт лежит в репозитории")
check(it._paint_font(False, "Rejada barcha oʻz", "type").endswith("LiberationMono-Regular.ttf"),
      "машинописный шрифт знает узбекские буквы")
check(it._paint_font(False, "Sleep quality", "serif").endswith("NotoSerif-Regular.ttf"), "засечки — Noto Serif")
im_, lbx = typed_page(mono_path, TL + ["of other works."])
buf_t = io.BytesIO()
im_.save(buf_t, "PNG")
box_t = [min(b[0] for b in lbx), min(b[1] for b in lbx), max(b[2] for b in lbx), max(b[3] for b in lbx)]
_, rep_t = it.render_target(buf_t.getvalue(), [{"box": box_t, "text": " ".join(["Rejada barcha"] * 18),
                                                "rows": len(lbx), "lineH": 30, "lineBoxes": lbx,
                                                "src": " ".join(TL + ["of other works."]), "align": "center"}])
check(rep_t and rep_t[0].get("fam") == "type", "страница машинописи печатается машинописным шрифтом: %s" % rep_t)

print("\n── Х2. выключка по краям строк ──")
L = lambda x0, x1, n=5: [[x0, 10 + i * 40, x1, 40 + i * 40] for i in range(n)]       # noqa: E731
check(tp.geometry_align(L(100, 900), [], 30) == "justify", "оба края ровные — по ширине")
rag = [[100, 10 + i * 40, 900 - (i * 37) % 120, 40 + i * 40] for i in range(5)]
check(tp.geometry_align(rag, [], 30) == "left", "правый край рваный — влево")
hand_like = [[100, 10 + i * 40, 900 - [0, 8, -6, 14, 3][i], 40 + i * 40] for i in range(5)]
check(tp.geometry_align(hand_like, [], 40) == "left", "правый край «ровный на глаз» (почерк) — не по ширине")
right = [[100 + (i * 37) % 120, 10 + i * 40, 900, 40 + i * 40] for i in range(5)]
check(tp.geometry_align(right, [], 30) == "right", "левый край рваный, правый ровный — вправо")
ctr = [[100 + d, 10 + i * 40, 900 - d, 40 + i * 40] for i, d in enumerate((0, 60, 20, 90, 40))]
check(tp.geometry_align(ctr, [], 30) == "center", "ровные середины — по центру")

print("\n── Х3. абзац внутри блока ──")
blk = [[140, 0, 900, 30]] + [[80, 40 * i, 900, 40 * i + 30] for i in range(1, 6)] \
    + [[140, 240, 900, 270]] + [[80, 40 * i, 900, 40 * i + 30] for i in range(7, 10)]
g4 = tp.line_geometry(blk, None, 30)
check(g4 and g4["heads"] == [6], "строка с той же красной строкой — новый абзац: %s" % (g4 and g4["heads"]))
check(g4 and abs(g4["shares"][0] - 0.6) < 0.05, "доля исходника до абзаца: %s" % (g4 and g4["shares"]))
t2 = "First sentence here. Second one is longer here. Third sentence ends. Fourth closes it all."
br = tp.para_breaks(t2, [0.5])
check(br.count("\n") == 1 and br.split("\n")[0].endswith(".") , "разрыв — на конце предложения: %r" % br)
check(tp.para_breaks("no sentence end anywhere in this text at all", [0.5]) .count("\n") == 0,
      "конца предложения рядом нет — разрыва нет")
lines_ = tp.fit_rhythm("aaa bbb ccc\nddd eee fff", 200, 20.0, 30.0, 6, 0, mw, first_indent=60)[2]
hh = tp.rhythm_heads("aaa bbb ccc\nddd eee fff", 200, 20.0, mw, None, 60)
check(len(hh) == 2 and lines_[hh[1]].startswith("ddd"), "отступ у первой строки каждого абзаца: %s %s" % (lines_, hh))

print("\n── Х5. стирание без следа ──")
rng2 = np.random.RandomState(1)
paper = (238 + rng2.randint(-3, 4, (120, 600, 1))).repeat(3, 2).astype(np.uint8)
img5 = Image.fromarray(paper.copy())
ImageDraw.Draw(img5).text((20, 30), "СМЕРТЬ ЧИНОВНИКА", font=ImageFont.truetype(
    "frontend/vendor/fonts/sub/NotoSerif-Regular.ttf", 48), fill=(30, 30, 30))
rgb5 = np.asarray(img5)
m5 = tp.measure(rgb5, "СМЕРТЬ ЧИНОВНИКА", 1, 60.0)
er5, al5 = tp.erase(rgb5, m5)
blend = (er5.astype(float) * (al5[..., None] / 255.0) + rgb5.astype(float) * (1 - al5[..., None] / 255.0))
diff5 = np.abs(blend.mean(2) - paper.mean(2))
check(diff5.max() < 40 and np.percentile(diff5, 99.5) < 12,
      "буквы стёрты без серого контура: макс %.0f, 99.5%% %.1f" % (diff5.max(), np.percentile(diff5, 99.5)))
inside = al5 > 0
check(abs(er5[inside].mean() - paper[inside].mean()) < 3, "тон стёртого — как у бумаги вокруг")

print("\n── Х7. дефис рукописного шрифта ──")
check(it._short_hyphen(hf[0]), "у рукописного шрифта дефис короткий — печатается тире")
check(not it._short_hyphen("frontend/vendor/fonts/sub/NotoSans-Regular.ttf"), "у Noto Sans — дефис как есть")

print("\n── Х6. засечки от чтения, семейства в PDF ──")
check('"serif"   —' in src and '"serif": bool(item.get("serif"))' in src, "чтение отвечает «засечки»")
check('("serif" if b.get("serif") else "")' in src, "выгрузка картинки берёт засечки по признаку")
check("type" in layout_pdf.FAMILY_CANDIDATES and
      layout_pdf.FAMILY_CANDIDATES["type"][""][1].endswith("LiberationMono-Regular.ttf"),
      "путь PDF: машинопись — отдельное семейство, код («mono») не тронут")

print("\n── Х8. буква, разрезанная краем вырезки, — целиком ──")
pg = Image.new("RGB", (900, 420), (240, 240, 238))
dp = ImageDraw.Draw(pg)
fser = ImageFont.truetype("frontend/vendor/fonts/sub/NotoSerif-Regular.ttf", 34)
dp.text((520, 30), "Чужая строка", font=fser, fill=(30, 30, 30))       # другая надпись выше
fcap = ImageFont.truetype("frontend/vendor/fonts/sub/NotoSerif-Bold.ttf", 150)
dp.text((60, 60), "В", font=fcap, fill=(25, 25, 25))                   # буквица выше строк
cap_bb = dp.textbbox((60, 60), "В", font=fcap)
lbs8 = []
for k_ in range(4):
    x_ = 180 if k_ < 2 else 60
    t_ = "один прекрасный вечер, не менее" if k_ < 2 else "прекрасный экзекутор Иван Дмитрич"
    dp.text((x_, 170 + k_ * 50), t_, font=fser, fill=(25, 25, 25))
    lbs8.append(list(dp.textbbox((x_, 170 + k_ * 50), t_, font=fser)))
box8 = [min(b[0] for b in lbs8) - 0, min(b[1] for b in lbs8), max(b[2] for b in lbs8), max(b[3] for b in lbs8)]
box8[0] = cap_bb[0]                                                    # буквица — в рамке слева
other8 = list(dp.textbbox((520, 30), "Чужая строка", font=fser))
b8 = io.BytesIO()
pg.save(b8, "PNG")
out8, rep8 = it.render_target(b8.getvalue(), [{"box": box8, "text": "One fine evening " * 8, "rows": 4,
                                               "lineH": 40, "lineBoxes": lbs8, "align": "left",
                                               "src": "Вь один прекрасный вечер не менее " * 3}],
                              obstacles=[other8])
check(out8 is not None and rep8[0].get("ok"), "блок с буквицей вписан: %s" % rep8)
if out8 is not None:
    r8 = np.asarray(Image.open(io.BytesIO(out8)).convert("L")).astype(int)
    above = r8[cap_bb[1]:box8[1] - 12, cap_bb[0]:cap_bb[2]]            # часть буквицы выше рамки
    check(above.size and above.min() > 200, "верх буквицы над рамкой стёрт (мин. %d)" % (above.min() if above.size else -1))
    o8 = np.asarray(pg.convert("L")).astype(int)
    keep8 = np.abs(r8[other8[1]:other8[3], other8[0]:other8[2]] - o8[other8[1]:other8[3], other8[0]:other8[2]]).max()
    check(keep8 < 10, "чужая строка выше не тронута (разница %d)" % keep8)
sd0 = np.zeros((60, 60), bool)
sd0[20:40, 0:5] = True
check(tp.cut_sides(sd0) == (True, False, False, False), "край, задетый стёртым, узнан")
rgb0 = np.full((80, 80, 3), 240, np.uint8)
rgb0[5:75, 70:73] = 20                                                # длинная вертикальная линия-рамка
seed0 = np.zeros((80, 80), bool)
seed0[30:40, 60:70] = True
rgb0[30:40, 60:70] = 20
add0 = tp.continuation_mask(rgb0, seed0, (20, 20, 71, 60), 8.0)
check(add0 is None or not add0[5:15, 70:73].any(), "линия-рамка выше CUT_MAX строк не стирается")

print("\n── Х9. засечки — по буквам ──")
SUB = "frontend/vendor/fonts/sub/"
TX9 = ["Один прекрасный вечер, не менее прекрасный экзекутор",
       "Иван Дмитрич Червяков сидел во втором ряду кресел",
       "СМЕРТЬ ЧИНОВНИКА. THE DEATH OF A CIVIL SERVANT."]
for fn, size, want in (("NotoSerif-Regular.ttf", 40, "serif"), ("NotoSerif-Bold.ttf", 40, "serif"),
                       ("NotoSans-Regular.ttf", 40, ""), ("NotoSans-Bold.ttf", 60, ""),
                       ("NotoSerif-Regular.ttf", 60, "serif")):
    im9, lb9 = typed_page(SUB + fn, TX9, size)
    a9 = np.asarray(im9.convert("L")) < 150
    sc9 = tp.serif_score(a9, lb9)
    check(sc9 is not None and tp.serif_fam(a9, lb9, "") == want,
          "%s %dpx: засечки=%r (вынос %s)" % (fn, size, want, sc9))
    check(tp.serif_fam(a9, lb9, "sans", "sans") == ("" if want else "sans"), "%s: соглашение PDF" % fn)
im9, lb9 = typed_page(SUB + "NotoSerif-Regular.ttf", TX9[:1], 12)
a9 = np.asarray(im9.convert("L")) < 150
check(tp.serif_score(a9, lb9) is None and tp.serif_fam(a9, lb9, "serif") == "serif",
      "мелкий кегль — мерить нечем, решает модель")
check(tp.serif_fam(a9, lb9, "hand") == "hand" and tp.serif_fam(a9, lb9, "type") == "type",
      "рукопись и машинопись мера не трогает")
# Сквозной: книга без признака от чтения (прочитана до вопроса о засечках)
# печатается антиквой; рубленый с ложным «serif» — рубленым.
for fn, fam_in, want in (("NotoSerif-Regular.ttf", "", "serif"), ("NotoSans-Regular.ttf", "serif", None)):
    im9, lb9 = typed_page(SUB + fn, TX9[:2], 40)
    b9 = io.BytesIO()
    im9.save(b9, "PNG")
    bx9 = [min(b[0] for b in lb9), min(b[1] for b in lb9), max(b[2] for b in lb9), max(b[3] for b in lb9)]
    _, r9 = it.render_target(b9.getvalue(), [{"box": bx9, "text": "One fine evening, an equally fine clerk " * 2,
                                              "rows": 2, "lineH": 60, "lineBoxes": lb9, "fam": fam_in,
                                              "src": " ".join(TX9[:2]), "align": "left"}])
    check(r9 and r9[0].get("ok") and r9[0].get("fam") == want, "%s: печать %r — %s" % (fn, want, r9))

print("\n── Х10. старая антиква, кегль по строчным ──")
from PIL import ImageFilter                                   # noqa: E402
def scan9(fn, lines, size, blur=0.8):
    im_, lb_ = typed_page(SUB + fn, lines, size)
    im_ = im_.filter(ImageFilter.GaussianBlur(blur))
    bb_ = io.BytesIO()
    im_.save(bb_, "JPEG", quality=70)
    rgb_ = np.asarray(Image.open(bb_).convert("RGB")).copy()
    box_ = [min(b[0] for b in lb_), min(b[1] for b in lb_), max(b[2] for b in lb_), max(b[3] for b in lb_)]
    m_ = tp.measure(rgb_, " ".join(lines), len(lines), 60, inner=box_)
    return m_, lb_
check(print_fonts.family_files("old")[0].endswith("OldStandard-Regular.ttf")
      and os.path.exists(SUB + "OFL-OldStandard.txt"), "Old Standard — семейство «old», лицензия рядом")
check(print_fonts.pre_reform("Въ одинъ прекрасный вечеръ, не менѣе прекрасный экзекуторъ"),
      "дореформенная орфография узнана (ер на конце, ять)")
check(not print_fonts.pre_reform("Объём, съезд и подъезд — в один прекрасный вечер"),
      "современный ъ внутри слова — не старая орфография")
check(not print_fonts.pre_reform("Бір тамаша кеште Іван Дмитрич"), "казахская і — не старая орфография")
for lang_t, want in (("One fine evening, an equally fine clerk", "OldStandard-Regular.ttf"),
                     ("Bir goʻzal oqshomda, ekzekutor", "OldStandard-Regular.ttf"),
                     ("Бір тамаша кеште, екзекутор", "OldStandard-Regular.ttf")):
    check(it._paint_font(False, lang_t, "old").endswith(want), "старая антиква знает буквы: %s" % lang_t)
OLD_SRC = ["Въ одинъ прекрасный вечеръ, не менѣе прекрасный экзекуторъ,",
           "Иванъ Дмитричъ Червяковъ, сидѣлъ во второмъ ряду креселъ",
           "и глядѣлъ въ бинокль на Корневильскія колокола. Онъ глядѣлъ",
           "и чувствовалъ себя на верху блаженства. Но вдругъ... Въ"]
im10, lb10 = typed_page(SUB + "OldStandard-Regular.ttf", OLD_SRC, 30)
ti10, tl10 = typed_page(SUB + "OldStandard-Regular.ttf", ["СМЕРТЬ ЧИНОВНИКА."], 40)
pg10 = Image.new("RGB", (im10.width, im10.height + 240), (238, 238, 232))
pg10.paste(ti10.crop((0, 0, im10.width, 100)), (0, 0))
pg10.paste(im10, (0, 120))
lb10 = [[a, b + 120, c, d + 120] for a, b, c, d in lb10]
b10 = io.BytesIO()
pg10.save(b10, "PNG")
box10 = [min(b[0] for b in lb10), min(b[1] for b in lb10), max(b[2] for b in lb10), max(b[3] for b in lb10)]
_, r10 = it.render_target(b10.getvalue(), [
    {"box": list(tl10[0]), "text": "THE DEATH OF A CIVIL SERVANT.", "rows": 1, "lineH": 60,
     "lineBoxes": [list(tl10[0])], "fam": "serif", "src": "СМЕРТЬ ЧИНОВНИКА.", "align": "center"},
    {"box": box10, "text": "One fine evening, an equally fine clerk Ivan Dmitrich " * 4, "rows": 4,
     "lineH": 60, "lineBoxes": lb10, "fam": "serif", "src": " ".join(OLD_SRC), "align": "left"}])
check(r10 and all(x.get("fam") == "old" for x in r10),
      "страница в старой орфографии — вся антиква старая, и заголовок без ъ: %s" % r10)
check(tp.em_by_xheight(42.0, 21.0, SUB + "NotoSerif-Regular.ttf", "один прекрасный") < 42.0,
      "строчные ниже наших — кегль по ним")
check(tp.em_by_xheight(42.0, 30.0, SUB + "NotoSerif-Regular.ttf", "один прекрасный") == 42.0,
      "кегль по строчным крупнее — прежний")
check(tp.em_by_xheight(42.0, 21.0, SUB + "NotoSerif-Regular.ttf", "СМЕРТЬ ЧИНОВНИКА") == 42.0,
      "прописные — не строчные, кегль прежний")

print("\n── Х11. жирный снимается площадью краски ──")
for fn, want in (("NotoSans-Regular.ttf", False), ("NotoSans-Bold.ttf", True)):
    m11, lb11 = scan9(fn, TX9[:2], 28, 1.0)
    got11 = tp.bold_by_area(m11["mask"], lb11, " ".join(TX9[:2]), float(m11["em"]),
                            SUB + "NotoSans-Regular.ttf", SUB + "NotoSans-Bold.ttf")
    check(got11 == want, "%s: жирный=%s по площади" % (fn, got11))

print("\n── Х12. штрих по середине тона ──")
def page12(fn, lines, size, blur=0.0, stroke=0):
    f_ = ImageFont.truetype(SUB + fn, size)
    im_ = Image.new("RGB", (1300, int(size * 1.6) * len(lines) + 40), (238, 236, 230))
    d_ = ImageDraw.Draw(im_)
    lb_ = []
    for k_, t_ in enumerate(lines):
        y_ = 20 + k_ * int(size * 1.6)
        d_.text((30, y_), t_, font=f_, fill=(25, 25, 25), stroke_width=stroke, stroke_fill=(25, 25, 25))
        lb_.append(list(d_.textbbox((30, y_), t_, font=f_, stroke_width=stroke)))
    if blur:
        im_ = im_.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(im_).copy(), lb_
LW = ["one fine evening an equally fine government clerk", "was sitting in the second row of stalls and"]
st0 = tp.stem_mid(*page12("OldStandard-Regular.ttf", LW, 48), (238, 236, 230), (25, 25, 25))
st1 = tp.stem_mid(*page12("OldStandard-Regular.ttf", LW, 48, 1.5), (238, 236, 230), (25, 25, 25))
check(st0 > 0 and abs(st1 - st0) <= 0.2 * st0, "штрих по середине тона от размытия почти не зависит: %.2f / %.2f" % (st0, st1))
check(tp.stem_mid(*page12("OldStandard-Regular.ttf", LW, 48, 1.0, 1), (238, 236, 230), (25, 25, 25)) > st0 + 1.2,
      "штрих толще на точку с каждой стороны — замер это видит")

print("\n── Х13. цвет по оси штриха, плотность набора, путь PDF ──")
rgb13, lb13 = page12("OldStandard-Regular.ttf", LW, 48, 1.4, 1)
m13 = tp.measure(rgb13, " ".join(LW), 2, 77, inner=[min(b[0] for b in lb13), min(b[1] for b in lb13),
                                                    max(b[2] for b in lb13), max(b[3] for b in lb13)])
st13 = tp.stem_mid(rgb13, lb13, m13["bg"], m13["ink"])
ci13 = tp.core_ink(rgb13, m13["mask"], m13["bg"], m13["ink"], st13)
check(ci13 is not None and max(ci13) <= max(m13["ink"]) and max(ci13) <= 45,
      "цвет по оси штриха ближе к настоящей краске (25): ось %s, прежний %s" % (ci13, m13["ink"]))
check(tp.core_ink(rgb13, m13["mask"], m13["bg"], m13["ink"], 2.0) is None, "у тонкого штриха оси нет — прежний цвет")
d13 = tp.band_density(rgb13, lb13, m13["bg"], m13["ink"])
TR13 = "One fine evening an equally fine government clerk"
fp13 = SUB + "OldStandard-Regular.ttf"
s13 = tp.weight_by_density(d13, lambda sf: tp.sample_density(fp13, TR13, 48, 1.0, (25, 25, 25), (238, 236, 230), sf),
                           tp.STROKE_MAX * 48)
got13 = tp.sample_density(fp13, TR13, 48, 1.0, (25, 25, 25), (238, 236, 230), s13)
check(s13 > 0.3 and abs(got13 - d13) <= 0.1 * d13,
      "обводка доводит плотность перевода до оригинала: %.2f → %.3f / %.3f" % (s13, got13, d13))
d0_13 = tp.band_density(*page12("OldStandard-Regular.ttf", LW, 48, 1.4), (238, 236, 230), (25, 25, 25))
check(tp.weight_by_density(d0_13, lambda sf: tp.sample_density(fp13, TR13, 48, 1.0, (25, 25, 25),
                                                               (238, 236, 230), sf), tp.STROKE_MAX * 48) < 0.25,
      "оригинал тем же шрифтом — обводки (почти) нет")
check(tp.weight_by_density(0.1, lambda sf: tp.sample_density(fp13, TR13, 48, 0.8, (25, 25, 25),
                                                             (238, 236, 230), sf), tp.STROKE_MAX * 48) == 0.0,
      "перевод уже плотнее оригинала (сжат по ширине) — обводки нет")
check(all(k_ in lps for k_ in ("tp.core_ink(", "tp.band_density(", "tp.weight_by_density(", "tp.bold_by_area(")),
      "путь PDF зовёт те же правила Х11–Х13")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
