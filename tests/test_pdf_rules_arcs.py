# -*- coding: utf-8 -*-
"""Подписи ПО ДУГЕ в выгрузке PDF «как в оригинале» (проект 14, разбор 13.10.2026) —
правила Т19–Т26 в docs/rules/pdf-reading.md.

  Т19. заливка под кривой обрезкой не «накрывает» подпись, которая под неё не попадает;
  Т20. вершина дуги (буква под углом ровно 0°) не лишает строку пути;
  Т21. строка без пути не склеивается с соседними дугами в один абзац;
  Т22. дуга по пикселям: пологая дуга и обломок кромки; прямая под углом — не дуга;
       кегль повёрнутых букв не завышен; масштаб вырезки — по длине надписи;
  Т23. край плашки у первой буквы дуги;
  Т24. надстрочный знак («†») не входит в путь дуги;
  Т25. пробел между словами дуги — по зазору шире 0.12 кегля; пробел после «:» «;» в переводе дуги;
  Т26. дуги слоя одного кольца — близким кеглем.
Каждый раздел: позитивный случай и негативный (то, что правило трогать не вправе).
"""
import io, math, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import layout_pdf
import pdfpages_worker
import pdftext
import text_paint as tp
import textcount
from pdf_fixture import make_pdf
from PIL import Image, ImageDraw, ImageFont

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


FONT = os.path.join("frontend", "vendor", "fonts", "sub", "NotoSans-Bold.ttf")
BODY = ("t", 40, 540, 11, "Обычный абзац страницы, где рядом схема.")


def arc_ops(text, size=9.0, th0=24.0, th1=0.0, cx=200.0, cy=200.0, gap_em=0.226, track_em=0.0,
            per_bt=True, **_ignored):
    """Текст по дуге, как его пишут программы вёрстки: каждая буква — свой Tm и свой Tj,
    пробел — РАЗРЫВ (а не знак). th0..th1 — угол базовой линии первой и последней буквы,
    градусы (последняя при th1 == 0 стоит ровно под 0°); путь — по длине текста с поворотом
    линейно по длине, начало — (cx, cy). Слова — через пробел."""
    letters, pos, adv = [], 0.0, 0.5 * size
    for ch in text:
        if ch == " ":
            pos += gap_em * size
            continue
        letters.append((ch, pos))
        pos += adv + track_em * size
    total = max(pos - track_em * size, 1.0)

    def th_at(s_):
        return math.radians(th0 + (th1 - th0) * s_ / total)
    ops, x, y, s_prev = [], cx, cy, 0.0
    for k, (ch, s_) in enumerate(letters):
        steps = max(1, int((s_ - s_prev) / 0.05))
        for i in range(steps):                    # шаг по пути: направление — угол в середине шага
            sm = s_prev + (s_ - s_prev) * (i + 0.5) / steps
            x += math.cos(th_at(sm)) * (s_ - s_prev) / steps
            y += math.sin(th_at(sm)) * (s_ - s_prev) / steps
        s_prev = s_
        th = th_at(s_)
        ca, sa = math.cos(th), math.sin(th)
        if th1 == 0.0 and k == len(letters) - 1:
            ca, sa = 1.0, 0.0
        op = "%.4f %.4f %.4f %.4f %.3f %.3f Tm {HEX:%s:HEX} Tj" % (ca, sa, -sa, ca, x, y, ch)
        ops.append("BT /F1 %g Tf %s ET" % (size, op) if per_bt else op)
    return ops


def geom_of(pdf):
    """Строки и геометрия страниц; кэш разбора по содержимому сбрасывается — правила
    переключаются между вызовами, и ответ прошлого вызова был бы чужим."""
    cache = getattr(textcount, "_PAGES_CACHE", None)
    if hasattr(cache, "clear"):
        cache.clear()
    return textcount._pdf_pages_geom(pdf, [])


def clean_of(raw_ops):
    page = [("raw", " ".join(raw_ops))] if raw_ops and isinstance(raw_ops[0], str) else list(raw_ops)
    pdf = make_pdf([page + [BODY]])
    pgs, gms = geom_of(pdf)
    return pdftext.clean(pgs, geom=gms), gms


def arcs_of(res):
    out = []
    for it in res["items"]:
        if it[0] != "p" or "Обычный" in it[1]:
            continue
        path = any(len(sl) > 8 and isinstance(sl[8], dict) and sl[8].get("curved")
                   for b in (it[2] or []) for sl in (b.get("slots") or []))
        out.append((it[1], path))
    return out


print("=== Т20. Вершина дуги: последняя буква под углом ровно 0° ===")
res, gms = clean_of(arc_ops("MEDITERRANEAN DIET", th0=24.0, th1=0.0))
got = arcs_of(res)
check(len(got) == 1 and got[0][1] and not res.get("unplaced"),
      "дуга 24°→0° — один абзац с путём, строк без места нет: %s %s" % (got, res.get("unplaced")))
pdfpages_worker.ROT_APEX = False
res_o, _g = clean_of(arc_ops("MEDITERRANEAN DIET", th0=24.0, th1=0.0))
pdfpages_worker.ROT_APEX = True
check(bool(res_o.get("unplaced")) and not arcs_of(res_o)[0][1],
      "контроль: без правила путь теряется и строка уходит в «осталось на оригинале»")
res2, _g = clean_of(arc_ops("MEDITERRANEAN DIET", th0=-30.0, th1=-8.0))
check(len(arcs_of(res2)) == 1 and arcs_of(res2)[0][1] and not res2.get("unplaced"),
      "дуга без нулевых углов — как прежде")
# Негатив: строка таблицы боком (куски под 90°, один — под 0°) не становится повёрнутой целиком.


def ch(rot, ang):
    return ("x", 1.0, 2.0, 5.0, rot, "", "", False, 1, None, ang, 5.0, None)


row90 = [ch(True, 90.0)] * 6 + [ch(False, 0.0)]
check(not pdfpages_worker._rotated_line(list(range(7)), row90),
      "куски под 90° и один под 0° — не дуга: вершина обязана лежать в разбросе углов")
arc_row = [ch(True, a) for a in (24, 20, 16, 12, 8, 4)] + [ch(False, 0.0)]
check(pdfpages_worker._rotated_line(list(range(7)), arc_row), "углы 24…4° и 0° — повёрнута целиком")
check(not pdfpages_worker._rotated_line([0, 1, 2], [ch(True, 20.0), ch(True, 10.0), ch(False, 0.0)]),
      "из трёх кусков правило не работает")
horiz, _g = clean_of([("t", 60, 300, 9, "ГОРИЗОНТАЛЬНАЯ ПОДПИСЬ СХЕМЫ")])
check(not [a for a in arcs_of(horiz) if a[1]], "горизонтальная строка путём дуги не становится")

print("=== Т21. Строка без пути не склеивается с соседними дугами ===")
three = (arc_ops("LOW-ENERGY DIETS", th0=-49, th1=-69, r=90, cx=300, cy=300)
         + arc_ops("MEDITERRANEAN DIET", th0=24, th1=0, r=120, cx=150, cy=300)
         + arc_ops("KETOGENIC DIETS", th0=-54, th1=-35, r=90, cx=120, cy=120))
pdfpages_worker.ROT_APEX = False                        # средней дуге пути не будет
res3, _g = clean_of(three)
got3 = arcs_of(res3)
check(len(got3) == 3, "три дуги подряд, у средней нет пути — три абзаца: %s" % [g[0] for g in got3])
pdftext.ROT_NOPATH_SPLIT = False
res3o, _g = clean_of(three)
pdftext.ROT_NOPATH_SPLIT = True
check(len(arcs_of(res3o)) < 3, "контроль: прежнее правило склеивало: %s" % [g[0] for g in arcs_of(res3o)])
pdfpages_worker.ROT_APEX = True
res3n, _g = clean_of(three)
check(len(arcs_of(res3n)) == 3 and all(g[1] for g in arcs_of(res3n)) and not res3n.get("unplaced"),
      "с правилом Т20 все три дуги с путём")

print("=== Т25. Пробел между словами дуги ===")
for gap, nm in ((0.226, "Calibri 0.226"), (0.176, "DIN 0.176"), (0.30, "широкий 0.30")):
    r_, _g = clean_of(arc_ops("COMPLEX PATHO", th0=-20, th1=-70, r=60, gap_em=gap))
    a_ = arcs_of(r_)
    check(len(a_) == 1 and a_[0][0] == "COMPLEX PATHO", "зазор %s кегля — пробел восстановлен: %s" % (nm, a_))
r_, _g = clean_of(arc_ops("COMPLEXPATHO", th0=-20, th1=-70, r=60))
check(arcs_of(r_)[0][0] == "COMPLEXPATHO", "без зазора слово не рвётся: %s" % arcs_of(r_))
r_, _g = clean_of(arc_ops("COMPLEX PATHO", th0=-20, th1=-70, r=60, gap_em=0.34, track_em=0.12))
check(arcs_of(r_)[0][0] == "COMPLEX PATHO",
      "разрядка 0.12 кегля внутри слов — пробел только между словами: %s" % arcs_of(r_))
r_, _g = clean_of(arc_ops("COMPLEX PATHO", size=2.0, th0=-20, th1=-70, r=40, gap_em=0.2))
check(arcs_of(r_)[0][0] == "COMPLEXPATHO", "мелкая подпись (кегль меньше 3) — прежний порог 0.25")
check(pdftext._path_gap([0.01, 0.02, 0.01, 0.2, 0.02], 8.0) == 0.12, "порог: 0.12 кегля при гладком шаге")
check(abs(pdftext._path_gap([0.1, 0.1, 0.12, 0.1, 0.3], 8.0) - 0.22) < 1e-9, "порог: 2.2 медианных зазора при разрядке")
check(pdftext._path_gap([0.2, 0.2, 0.22, 0.2], 8.0) == 0.25, "порог не строже прежнего: не выше 0.25 кегля")
check(pdftext._path_gap([0.01, 0.02], 8.0, letters=False) == 0.25, "у строки из кусков-слов — прежний порог")
# Строка повёрнутой таблицы из кусков-слов («Increased risk» | «Neutral» | «•» | «No dose»): зазоры между
# словами, не между буквами. Правило не вправе съесть пробелы, а с ними и маркер пункта (стр. 9).
chunks_row = [[10.0, 0.0, 90.0, 5.0, 14, "Increased risk", [10.0, 14 * 2.5]],
              [10.0, 14 * 2.5 + 1.5, 90.0, 5.0, 7, "Neutral", [10.0, 14 * 2.5 + 1.5 + 7 * 2.5]],
              [10.0, 14 * 2.5 + 1.5 + 7 * 2.5 + 1.5, 90.0, 5.0, 1, "•", [10.0, 14 * 2.5 + 1.5 + 7 * 2.5 + 1.5 + 2.5]],
              [10.0, 14 * 2.5 + 1.5 + 7 * 2.5 + 1.5 + 2.5 + 1.5, 90.0, 5.0, 7, "No dose", [10.0, 120.0]]]
check(pdftext._path_text({"pts": chunks_row}) == "Increased risk Neutral • No dose",
      "повёрнутая таблица из кусков: пробелы и маркер на месте: %r" % pdftext._path_text({"pts": chunks_row}))
curved = [{"slots": [[0, 0, 10, 8, "", None, 5, 0, {"curved": True, "pts": []}]]}]
flat = [{"slots": [[0, 0, 10, 8]]}]
check(layout_pdf._arc_punct("Включая:национальную стратегию;национальную", curved)
      == "Включая: национальную стратегию; национальную", "перевод дуги: пробел после «:» и «;»")
check(layout_pdf._arc_punct("Включая:национальную", flat) == "Включая:национальную",
      "перевод обычного абзаца этим правилом не меняется")
check(layout_pdf._arc_punct("см. https://doi.org/10.1/x:y;z", curved) == "см. https://doi.org/10.1/x:y;z",
      "адрес не трогается")
check(layout_pdf._arc_punct("в 10:30 и 5,2", curved) == "в 10:30 и 5,2", "цифры не трогаются")

print("=== Т24. Надстрочный знак не входит в путь дуги ===")


def arc_pts(n=12, r=60.0, size=8.0, mark=True):
    pts, adv = [], 0.5 * size
    for k in range(n + (1 if mark else 0)):
        th = -math.radians(10 + k * (adv / r) * 57.3)
        x, y = 100 + r * math.cos(math.radians(90) + th), 100 + r * math.sin(math.radians(90) + th)
        ang = math.degrees(th)
        sz, off = size, 0.0
        if mark and k == n:
            sz, off = 0.56 * size, 0.45 * size                 # «†»: мельче и в стороне от линии
            x += off * -math.sin(th)                         # нормаль к касательной
            y += off * math.cos(th)
        ex = x + (adv if sz == size else 0.3 * size) * math.cos(th)
        ey = y + (adv if sz == size else 0.3 * size) * math.sin(th)
        pts.append([x, y, ang, sz, 1, "ABCDEFGHIJKL†"[k], [ex, ey]])
    return pts


pts_m = arc_pts()
sd = layout_pdf._rot_slot({"pts": pts_m, "end": pts_m[-1][6], "curved": True}, 8.0)
check(len(sd["marks"]) == 1 and len(sd["nodes"]) == 13, "«†» вынут из узлов, узлов 12 + конец: %d, знаков %d"
      % (len(sd["nodes"]), len(sd["marks"])))
a_tail = layout_pdf._path_at(sd, sd["x1"] - 0.3)[2]
check(abs(((a_tail - pts_m[11][2]) + 180) % 360 - 180) < 6.0,
      "угол у конца пути — собственный угол последней буквы: %.1f против %.1f" % (a_tail, pts_m[11][2]))
layout_pdf.ARC_MARKS = False
sd0 = layout_pdf._rot_slot({"pts": pts_m, "end": pts_m[-1][6], "curved": True}, 8.0)
layout_pdf.ARC_MARKS = True
a0 = layout_pdf._path_at(sd0, sd0["cum"][-2] - 0.2)[2]
check(abs(((a0 - pts_m[11][2]) + 180) % 360 - 180) > 25.0, "контроль: прежний путь на последней букве — угол врёт (%.1f)" % a0)


class Rec:
    def __init__(self):
        self.rects = 0

    def saveState(self): pass
    def restoreState(self): pass
    def translate(self, *a): pass
    def rotate(self, *a): pass
    def setFillColorRGB(self, *a): pass

    def rect(self, *a, **k):
        self.rects += 1


rc = Rec()
layout_pdf._fill_rot(rc, sd, [(1, 1, 1)], 0.4)
check(rc.rects == 12 + 1, "закрашены все буквы и сам знак: %d" % rc.rects)
pts_p = arc_pts(mark=False)
sd_p = layout_pdf._rot_slot({"pts": pts_p, "end": pts_p[-1][6], "curved": True}, 8.0)
check(not sd_p["marks"] and len(sd_p["nodes"]) == 13, "дуга без знаков — путь прежний")
tight = arc_pts(n=10, r=10.0, size=7.0, mark=False)
sd_t = layout_pdf._rot_slot({"pts": tight, "end": tight[-1][6], "curved": True}, 7.0)
check(not sd_t["marks"], "тугая дуга (R=10 при кегле 7) — буквы на линии знаками не считаются")

print("=== Т26. Дуги слоя одного кольца — близким кеглем ===")


def arc_slot(cx, cy, r, size, th_a, th_b, page=0, n=8):
    nodes = [(cx + r * math.cos(math.radians(th_a + (th_b - th_a) * k / n)),
              cy + r * math.sin(math.radians(th_a + (th_b - th_a) * k / n))) for k in range(n + 1)]
    return {"rot": {"pts": [1]}, "curved": True, "nodes": nodes, "x1": 25.0, "size": size, "page": page}


sw_t = lambda t, f, s: 0.5 * s * len(t)                         # noqa: E731
fo = lambda sd_: "F"                                            # noqa: E731
sd_a, sd_b, sd_c = arc_slot(100, 100, 60, 7.7, 100, 160), arc_slot(102, 98, 60, 7.7, 200, 260), \
    arc_slot(400, 400, 60, 7.7, 100, 160)
plan = [([sd_a], ["ПОТООТДЕЛЕНИЕ"], [0.55], [], fo, "center", [1.0]),
        ([sd_b], ["СОН"], [1.0], [], fo, "center", [1.0]),
        ([sd_c], ["СОН"], [1.0], [], fo, "center", [1.0])]
st = {}
layout_pdf._harmonize_layer_arcs(plan, sw_t, st)
check(abs(plan[1][2][0] - 0.85 * 1.0) < 1e-6 and plan[0][2][0] == 0.55,
      "«СОН» на одном кольце с «ПОТООТДЕЛЕНИЕ» — не мельче 0.85 своего: %s" % [p[2] for p in plan])
check(plan[2][2][0] == 1.0, "дуга другой фигуры не тронута")

print("=== Т22. Дуга по пикселям ===")


def label_img(text, span=25.0, size=20, w=330, h=130, straight=None, sliver=False):
    """Белые буквы по дуге с поворотом первой и последней буквы на `span` градусов (или по
    прямой под углом `straight`) на синей ленте; точки вырезки. Радиус — по длине надписи."""
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    n_ = len([c for c in text if c != " "])
    R = (n_ - 1) * size * 0.95 / math.radians(span)
    cx, cy = w / 2.0, h + R - 62
    if straight is None:
        d.ellipse([cx - R - 26, cy - R - 26, cx + R + 26, cy + R + 26], fill=(20, 90, 135))
        d.ellipse([cx - R + 26, cy - R + 26, cx + R - 26, cy + R - 26], fill="white")
    else:
        d.polygon([(0, h / 2 + 30 + w / 2 * math.tan(math.radians(straight))),
                   (w, h / 2 + 30 - w / 2 * math.tan(math.radians(straight))),
                   (w, h / 2 - 30 - w / 2 * math.tan(math.radians(straight))),
                   (0, h / 2 - 30 + w / 2 * math.tan(math.radians(straight)))], fill=(20, 90, 135))
    font = ImageFont.truetype(FONT, size)
    letters = [c for c in text if c != " "]
    n = len(letters)
    for k, c in enumerate(letters):
        tile = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((size // 2, size // 4), c, fill=(255, 255, 255, 255), font=font)
        if straight is None:
            phi = 90.0 + span / 2 - span * k / max(1, n - 1)
            rot = phi - 90.0
            px, py = cx + R * math.cos(math.radians(phi)), cy - R * math.sin(math.radians(phi))
        else:
            rot = straight
            t = (k - (n - 1) / 2.0) * size * 0.95
            px, py = w / 2 + t * math.cos(math.radians(rot)), h / 2 - t * math.sin(math.radians(rot))
        tile = tile.rotate(rot, resample=Image.BICUBIC)
        img.paste(tile, (int(px - size), int(py - size)), tile)
    if sliver:
        d.line([(3, 6), (3 + 28, 6)], fill="white", width=1)
    return np.asarray(img)


def meas(arr, text):
    h = arr.shape[0]
    return tp.measure(arr, text, 1, float(h) * 0.9, (4.0, 4.0, arr.shape[1] - 4.0, arr.shape[0] - 4.0))


for span in (18.0, 25.0, 40.0):
    m = meas(label_img("MEDITERRANEAN DIET", span=span), "MEDITERRANEAN DIET")
    check(bool(m.get("found")) and bool(m.get("arc")) and m["arc"]["up"] == 1,
          "дуга с поворотом букв %.0f° найдена, верх букв наружу" % span)
m = meas(label_img("MEDITERRANEAN DIET", span=25.0, sliver=True), "MEDITERRANEAN DIET")
check(bool(m.get("arc")), "обломок кромки кольца в вырезке дугу не ломает")
for tilt in (0.0, 10.0, 25.0, 40.0):
    m = meas(label_img("MEDITERRANEAN DIET", straight=tilt), "MEDITERRANEAN DIET")
    check(bool(m.get("found")) and not m.get("arc"), "прямая надпись под %.0f° — не дуга" % tilt)
up = meas(label_img("STANDING", straight=0.0, w=240, h=70), "STANDING")
tl = meas(label_img("STANDING", straight=30.0, w=240, h=120), "STANDING")
check(up["found"] and tl["found"] and tl["em"] <= 1.1 * up["em"],
      "кегль букв под 30° не завышен: %.1f против %.1f у прямой" % (tl["em"], up["em"]))
check(tl["bold"] == up["bold"] and up["bold"], "полужирный у наклонной надписи не теряется")
print("=== Т23. Край плашки у первой буквы ===")
img = Image.new("RGB", (240, 110), "white")
dd = ImageDraw.Draw(img)
# лента, расширяющаяся влево: у левого края шире окна размытия, у правого — уже
dd.polygon([(0, 20), (240, 14), (240, 60), (0, 104)], fill=(20, 90, 135))
lab = Image.new("RGBA", (230, 44), (0, 0, 0, 0))
ImageDraw.Draw(lab).text((2, 4), "MEDITERRANEAN DIET", fill=(255, 255, 255, 255),
                         font=ImageFont.truetype(FONT, 19))
def letter_px(ch_, shift):
    t_ = Image.new("RGBA", (230, 44), (0, 0, 0, 0))
    ImageDraw.Draw(t_).text((2 + shift, 4), ch_, fill=(255, 255, 255, 255), font=ImageFont.truetype(FONT, 19))
    t_ = t_.rotate(11.5, expand=True, resample=Image.BICUBIC)
    ys_, xs_ = np.nonzero(np.asarray(t_.split()[3]) > 128)
    return ys_, xs_


lab_r = lab.rotate(11.5, expand=True, resample=Image.BICUBIC)
img.paste(lab_r, (4, 22), lab_r)
arr = np.asarray(img.resize((120, 55), Image.LANCZOS))
mm = tp.measure(arr, "MEDITERRANEAN DIET", 1, 41.0)
check(mm["found"], "надпись найдена")


def coverage(mask_, ch_, shift):
    ys_, xs_ = letter_px(ch_, shift)
    fm_ = np.zeros(arr.shape[:2], dtype=bool)
    for yy, xx in zip(ys_, xs_):
        fm_[min(54, int((yy + 22) / 2)), min(119, int((xx + 4) / 2))] = True
    return float((mask_ & fm_).sum()) / max(1.0, float(fm_.sum()))


w_m = ImageFont.truetype(FONT, 19).getlength("M")
cov_first, cov_next = coverage(mm["mask"], "M", 0), coverage(mm["mask"], "E", w_m)
check(cov_first >= 0.9 * cov_next, "первая буква «M» в маске не хуже следующей: %.0f%% против %.0f%%"
      % (100 * cov_first, 100 * cov_next))
orig_ext = tp._plate_extend
tp._plate_extend = lambda *a, **k: None
mm0 = tp.measure(arr, "MEDITERRANEAN DIET", 1, 41.0)
tp._plate_extend = orig_ext
cov0 = coverage(mm0["mask"], "M", 0)
check(cov_first >= cov0, "пополнение региона маску не уменьшает (%.0f%% → %.0f%%)" % (100 * cov0, 100 * cov_first))
sky = Image.new("RGB", (240, 110), (150, 190, 225))
_sd = ImageDraw.Draw(sky)
for _k in range(40):
    _x, _y = (_k * 37) % 230, (_k * 53) % 100
    _sd.ellipse([_x, _y, _x + 3, _y + 3], fill=(165, 200, 230))
check(not tp.measure(np.asarray(sky.resize((120, 55))), "SKY", 1, 41.0)["found"],
      "небо фотографии с крапинами — по-прежнему не плашка")
# Настоящая вырезка (проект 14, стр. 10, 118×53 точки): лента шире окна размытия у левого
# края, левая ножка «M» лежала вне региона плашки и оставалась нестёртой.
# Вырезка из файла клиента в репозиторий не кладётся — проверка идёт, только
# если она лежит рядом на машине разработчика.
_real_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "arc_mediterranean_crop.png")
if os.path.exists(_real_p):
    real = np.asarray(Image.open(_real_p).convert("RGB"))
    inner = (6.148503, 6.148503, 112.02348386, 47.13852298)
    mr = tp.measure(real, "MEDITERRANEAN DIET", 1, 40.99, inner)
    check(mr["found"] and int(mr["mask"][:, :19].sum()) >= 35,
          "настоящая вырезка: у левого края маски больше точек «M»: %d (было 10)" % int(mr["mask"][:, :19].sum()))
    check(bool(mr.get("arc")) and mr["bold"], "настоящая вырезка: дуга найдена, начертание полужирное")
else:
    print("  (вырезки клиента нет — проверка на настоящей дуге пропущена)")

# Т19 (кривая обрезка) в эту сборку не внесено — см. pdfpages_worker.CURVE_CLIP.
check(pdfpages_worker.CURVE_CLIP is False, "Т19 выключено")

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
