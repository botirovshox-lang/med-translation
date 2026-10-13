# -*- coding: utf-8 -*-
"""Заплатки и надписи на картинках: правила Т27–Т32 (проект 14, выгрузка PDF
«как в оригинале», 13.10.2026). Синтетика (PIL/numpy) — боевой файл не нужен.

  Т27. Хвост краски строки слоя — только СВОЕГО цвета и не линейка
       (`layout_pdf._ink_end/_ink_box`): серая заплатка «24 HOURS» не выходит
       за круг на дугу, закраска не съедает рамку плашки.
  Т28. Поле закраски не наезжает на тонкую линию (`_pad_guard`, `_fill_box`).
  Т29. Маска стирания достраивает внутренность толстых букв
       (`text_paint._erase_mask`): белых «облаков» от нестёртых букв нет.
  Т30. Перевод надписи — в комнату плашки, а не в рамку блока
       (`text_paint._area_rooms`, `layout_pdf._paint_plan`).
  Т31. Буква прямой строки — по высоте области, слипшиеся жирные буквы не
       срывают замер (`text_paint.measure`).
  Т32. Сверка со слоем: рамки дуговой строки — по глифам; хвост за точным
       концом строки слоя — надпись; остаток краски вне слоя — новые блоки
       (`main._layer_rects`, `_mark_layer_blocks`, `_residual_groups`,
       `_layer_residual_add`).
Негативные проверки (тире, пунктир, маркеры, значки, шум) — рядом с позитивными.
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import layout_pdf
import text_paint as tp

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


FB = os.path.join("frontend", "vendor", "fonts", "sub", "NotoSans-Bold.ttf")
FR = os.path.join("frontend", "vendor", "fonts", "sub", "NotoSans-Regular.ttf")

# ─── Т27. Хвост краски — только своего цвета ─────────────────────────────
print("=== Т27. Хвост краски: чужая графика и линейка хвостом не считаются ===")
PAPER = (198, 196, 200)
INK = (47, 72, 100)
PURPLE = (135, 81, 160)


def page27(extra):
    """Страница 200×200 пт, 2 пикселя на пункт: серая бумага, «буквы» слота
    x 40..80, y 98..107 (слот exact), плюс `extra(draw)`."""
    im = Image.new("RGB", (400, 400), PAPER)
    d = ImageDraw.Draw(im)
    for k in range(5):                                   # «буквы»: стойки в слоте (до x=72)
        x = 40 + 8 * k
        d.rectangle([2 * x, 400 - 2 * 105, 2 * x + 2, 400 - 2 * 100], fill=INK)
    extra(d)
    return (im, 2.0, (0.0, 0.0), im.convert("L"))


def slot27():
    return {"x0": 40.0, "x1": 80.0, "top": 106.8, "bottom": 98.0, "size": 8.0, "y": 100.0, "x": 40.0,
            "xl": 40.0, "exact": True, "n": 10, "style": "", "page": 0, "color": (47 / 255, 72 / 255, 100 / 255)}


def purple(d):                                           # дуга: через 1.5 пт после конца строки
    d.rectangle([2 * 81.5, 400 - 2 * 110, 2 * 95, 400 - 2 * 90], fill=PURPLE)


s_ = page27(purple)
sd = slot27()
end_new = layout_pdf._ink_end(s_, sd, 0.78)
layout_pdf.INK_OWN_TOL = 0.0
end_old = layout_pdf._ink_end(s_, slot27(), 0.78)
layout_pdf.INK_OWN_TOL = 28.0
check(end_new is not None and end_new <= 81.0, "фиолетовая дуга за концом строки — не хвост: %s" % end_new)
check(end_old is not None and end_old >= 83.0, "страж: прежняя раздвижка цеплялась за дугу: %s" % end_old)
bx = layout_pdf._ink_box(s_, slot27(), 1.44, 0.78)
check(bx[1] <= 81.0 + 1.5, "и `_ink_box` не раздвигается на дугу: %s" % (bx,))


def tail(d):                                             # своя краска: хвост ещё на 2 пт
    d.rectangle([2 * 80, 400 - 2 * 105, 2 * 81, 400 - 2 * 100], fill=INK)
    d.rectangle([2 * 82.3, 400 - 2 * 105, 2 * 82.8, 400 - 2 * 100], fill=INK)


s_ = page27(tail)
end_t = layout_pdf._ink_end(s_, slot27(), 0.78)
check(end_t is not None and end_t >= 82.5, "хвост той же краски (выключка) — по-прежнему хвост: %s" % end_t)


def rule(d):                                             # рамка плашки (линейка) по нижнему ряду полосы
    d.rectangle([2 * 80, 400 - 2 * 98 - 1, 2 * 95, 400 - 2 * 98], fill=INK)


s_ = page27(rule)
end_r = layout_pdf._ink_end(s_, slot27(), 0.78)
layout_pdf.INK_OWN_RULE = 2.0                            # выключить фильтр линеек
end_r0 = layout_pdf._ink_end(page27(rule), slot27(), 0.78)
layout_pdf.INK_OWN_RULE = 0.85
check(end_r is not None and end_r <= 81.0, "линейка того же цвета в нижнем ряду полосы — не буква: %s" % end_r)
check(end_r0 is not None and end_r0 >= 83.0, "страж: без фильтра линейка тянула хвост: %s" % end_r0)
sd_none = slot27()
sd_none["_own"] = None                                   # мерить нечем — прежняя дорога
end_n = layout_pdf._ink_end(page27(purple), sd_none, 0.78)
check(end_n is not None and end_n >= 83.0, "краска строки не измерена — прежнее поведение (серый тон)")

# ─── Т28. Поле закраски и линия ──────────────────────────────────────────
print("=== Т28. Поле закраски не наезжает на линию рядом ===")
imw = Image.new("RGB", (400, 400), (255, 255, 255))
dw = ImageDraw.Draw(imw)
dw.rectangle([2 * 30, 400 - 2 * 97.6 - 1, 2 * 120, 400 - 2 * 97.6], fill=(181, 223, 213))   # рамка плашки 0.5 пт
smp = (imw, 2.0, (0.0, 0.0), imw.convert("L"))
sdw = {"x0": 40.0, "x1": 80.0, "top": 106.8, "bottom": 98.0, "size": 8.0, "y": 100.0, "x": 40.0}
pad28 = layout_pdf.PAD_SHARE * 8.0
g = layout_pdf._pad_guard(smp, sdw, pad28, [(1.0, 1.0, 1.0)] * 3, min(pad28, 0.4))
check(g is not None and g[3] < 0.6 * pad28 and g[0] == pad28 and g[1] == pad28,
      "поле снизу кончается перед рамкой, по бокам прежнее: %s" % (g,))
check(layout_pdf._pad_guard((Image.new("RGB", (400, 400), "white"), 2.0, (0.0, 0.0),
                             Image.new("L", (400, 400), 255)), sdw, pad28, [(1.0, 1.0, 1.0)] * 3, 0.4) is None,
      "чистая бумага — поле прежнее")


class _Rects:
    def __init__(self):
        self.r = []

    def setFillColorRGB(self, *a):
        pass

    def rect(self, x, y, w, h, **k):
        self.r.append((x, y, w, h))


c1, c2 = _Rects(), _Rects()
sdw["_pads"] = g
layout_pdf._fill_box(c1, sdw, pad28, [(1.0, 1.0, 1.0)] * 3, top_pad=0.4)
sdw2 = dict(sdw)
sdw2.pop("_pads")
layout_pdf._fill_box(c2, sdw2, pad28, [(1.0, 1.0, 1.0)] * 3, top_pad=0.4)
check(min(r[1] for r in c1.r) > 97.6 + 0.2, "закраска не заходит на линию: низ %.2f" % min(r[1] for r in c1.r))
check(min(r[1] for r in c2.r) < 97.0, "страж: без предохранителя закраска её накрывала: %.2f" % min(r[1] for r in c2.r))
# Вертикальная рамка сбоку.
imv = Image.new("RGB", (400, 400), (255, 255, 255))
ImageDraw.Draw(imv).rectangle([2 * 81.1 - 1, 400 - 2 * 110, 2 * 81.1, 400 - 2 * 90], fill=(36, 118, 166))
gv = layout_pdf._pad_guard((imv, 2.0, (0.0, 0.0), imv.convert("L")), sdw2, pad28, [(1.0, 1.0, 1.0)] * 3, 0.4)
check(gv is not None and gv[1] < 0.8 * pad28 and gv[3] == pad28, "рамка справа в поле — поле справа короче: %s" % (gv,))

# ─── Т29. Внутренность толстых букв в маске стирания ─────────────────────
print("=== Т29. Стирание: внутренность толстых букв ===")
if not tp.available():
    print("   нет OpenCV — замер надписей не проверялся")
else:
    def grad29(w, h):
        y = np.linspace(0, 1, h)[:, None]
        return np.dstack([180 - 120 * y + np.zeros((1, w)), 190 - 20 * y + np.zeros((1, w)),
                          45 + 30 * y + np.zeros((1, w))]).astype(np.uint8)
    im29 = Image.fromarray(grad29(200, 70))
    ImageDraw.Draw(im29).text((8, 6), "OF CARE", font=ImageFont.truetype(FB, 44), fill=(255, 255, 255))
    rgb29 = np.asarray(im29)
    letters = rgb29.astype(int).min(axis=2) > 235

    def unerased(fill_on):
        tp.ERASE_FILL = fill_on
        m = tp.measure(rgb29, "OF CARE", 1, 30.0)
        er, _al = tp.erase(rgb29, m)
        res = np.abs(er.astype(int) - grad29(200, 70).astype(int)).max(axis=2)
        return m["found"], float((res[letters] > 60).mean())
    f1, u1 = unerased(True)
    f0, u0 = unerased(False)
    tp.ERASE_FILL = True
    check(f1 and u1 < 0.01, "середина жирных букв стёрта: нестёртых %.3f" % u1)
    check(f0 and u0 > 0.03, "страж: без правила оставалась белая середина: %.3f" % u0)
    # Белая плашка вдали от букв: её середина в маску стирания не идёт (в маску
    # букв попадает только её край, и добавка — не дальше полутолщины штриха).
    im_bg = Image.fromarray(grad29(200, 70))
    ImageDraw.Draw(im_bg).text((8, 6), "OF", font=ImageFont.truetype(FB, 44), fill=(255, 255, 255))
    ImageDraw.Draw(im_bg).rectangle([140, 8, 195, 62], fill=(255, 255, 255))
    mb = tp.measure(np.asarray(im_bg), "OF", 1, 30.0)
    em_ = mb.get("erase_mask", mb["mask"])
    check(not em_[26:44, 156:180].any(), "середина белой плашки вдали от букв в маску стирания не попала")

# ─── Т30. Комната плашки ─────────────────────────────────────────────────
print("=== Т30. Место перевода — по плашке ===")
if tp.available():
    import cv2
    circ = Image.new("RGB", (200, 160), "white")
    dc = ImageDraw.Draw(circ)
    dc.ellipse([10, 10, 190, 150], fill=(60, 170, 70))
    fcr = ImageFont.truetype(FB, 16)
    dc.text((62, 28), "GOALS OF", font=fcr, fill=(255, 255, 255))         # верхняя строка — узкая
    dc.text((24, 78), "PREVENT COMPLICATIONS", font=fcr, fill=(255, 255, 255))   # средняя — широкая
    rgbc = np.asarray(circ)
    letters = rgbc.min(axis=2) > 200
    maskc = np.zeros(rgbc.shape[:2], bool)
    maskc[28:48, 40:160] = letters[28:48, 40:160]
    maskc[76:100, 14:190] = letters[76:100, 14:190]
    r0 = np.nonzero(maskc[28:48].any(axis=0))[0]
    r1 = np.nonzero(maskc[76:100].any(axis=0))[0]
    ys0 = np.nonzero(maskc[:90].any(axis=1))[0]
    ys1 = np.nonzero(maskc[70:].any(axis=1))[0] + 70
    rooms = tp._area_rooms(rgbc, maskc, [(int(ys0.min()), int(ys0.max())), (int(ys1.min()), int(ys1.max()))],
                           [[0, 0], [1, 1]])
    check(rooms[0][0] is not None and rooms[0][1] is not None and rooms[0][0] < r0.min() + 40 and rooms[0][1] > r0.max() + 40,
          "верх круга: края плашки найдены снаружи краски: %s, краска %d..%d" % (rooms[0], r0.min() + 40, r0.max() + 40))
    w0 = rooms[0][1] - rooms[0][0] if None not in rooms[0] else 0
    w1 = (rooms[1][1] - rooms[1][0]) if None not in rooms[1] else 10 ** 6
    check(w0 and w0 < w1, "хорда у верха уже, чем в середине: %s %s" % (rooms[0], rooms[1]))
    white = Image.new("RGB", (200, 80), "white")
    ImageDraw.Draw(white).rectangle([60, 30, 140, 44], fill=(0, 0, 0))
    mw = np.zeros((80, 200), bool)
    mw[30:45:2, 60:141:3] = True
    rw = tp._area_rooms(np.asarray(white), mw, [(30, 44)], [[0, 0]])
    check(rw[0] == (None, None), "ровная бумага до края вырезки — края плашки нет: %s" % (rw[0],))

    from reportlab.pdfbase import pdfmetrics
    fonts = layout_pdf._register_fonts(set("ЦЕЛИ ЛЕЧЕНИЯАБВГ"))
    font = layout_pdf._font_for(fonts, {"style": "b", "fam": "sans"})

    w_free = pdfmetrics.stringWidth("ЦЕЛИ ЛЕЧЕНИЯ", font, 6.8)          # перевод одной строкой при кегле 6.8
    BX0, BX1 = 100.0, 100.0 + 0.95 * w_free

    def plan(rooms_):
        b = {"x0": BX0, "x1": BX1, "top": 100.0, "bottom": 90.0, "src": "GOALS OF CARE", "image": 1,
             "_paint": {"em": 6.8, "bands": [(100.0, 93.0)], "areas": [[0, 0]], "areaInk": [1.0], "pitch": 8.0,
                        "bold": True, "inkw": 0.0, "angle": 0.0, "rooms": rooms_}, "align": "center"}
        return layout_pdf._paint_plan(b, "ЦЕЛИ ЛЕЧЕНИЯ", fonts, pdfmetrics.stringWidth, None)
    p0 = plan([(None, None)])
    mid = (BX0 + BX1) / 2.0
    p1 = plan([(mid - 0.3 * w_free, mid + 0.3 * w_free)])
    room_w = 0.6 * w_free - 2 * 0.3 * 6.8
    pw = max(pdfmetrics.stringWidth(ln, font, p1["size"]) * p1["h0"] for ln in p1["lines"])
    check(p0["f"] > 0.9, "без комнаты перевод в рамку блока — крупно: f=%.2f" % p0["f"])
    check(pw <= room_w + 0.5 and p1["size"] < p0["size"],
          "комната уже блока — перевод в неё: ширина %.1f из %.1f, кегль %.2f → %.2f" % (pw, room_w, p0["size"], p1["size"]))
    check(abs((p1["parts"][0]["L"] + p1["parts"][0]["R"]) / 2.0 - mid) < 0.5, "середина — середина комнаты")
    p2 = plan([(BX0 - 10.0, BX1 + 10.0)])
    check(abs(p2["parts"][0]["L"] - BX0) < 1e-6 and abs(p2["parts"][0]["R"] - BX1) < 1e-6,
          "комната шире блока блок НЕ растит: %s" % ((p2["parts"][0]["L"], p2["parts"][0]["R"]),))
    p3 = plan([(mid - 0.45 * w_free + 0.0, None)])
    check(p3["parts"][0]["R"] == BX1 and p3["parts"][0]["L"] >= BX0, "край плашки с одной стороны — другая сторона блока")

# ─── Т31. Буква по высоте ────────────────────────────────────────────────
print("=== Т31. Слипшиеся жирные буквы не срывают замер ===")
if tp.available():
    import cv2

    def merged(fs=28, dil=2):
        im = Image.fromarray(np.dstack([160 - 60 * np.linspace(0, 1, 86)[:, None] + np.zeros((1, 150)),
                                        190 - 20 * np.linspace(0, 1, 86)[:, None] + np.zeros((1, 150)),
                                        60 + 20 * np.linspace(0, 1, 86)[:, None] + np.zeros((1, 150))]).astype(np.uint8))
        d = ImageDraw.Draw(im)
        d.text((5, 3), "GOALS", font=ImageFont.truetype(FB, fs), fill=(255, 255, 255))
        d.text((5, 42), "OF CARE", font=ImageFont.truetype(FB, fs), fill=(255, 255, 255))
        rgb = np.asarray(im).copy()
        wh = cv2.dilate((rgb.min(axis=2) > 200).astype(np.uint8), np.ones((2 * dil + 1, 2 * dil + 1), np.uint8))
        rgb[wh > 0] = 255
        return rgb
    rgb31 = merged()
    tp.LETTER_BY_HEIGHT = True
    m_new = tp.measure(rgb31, "GOALS OF CARE", 2, 38.0, inner=(5, 5, 145, 81))
    tp.LETTER_BY_HEIGHT = False
    m_old = tp.measure(rgb31, "GOALS OF CARE", 2, 38.0, inner=(5, 5, 145, 81))
    tp.LETTER_BY_HEIGHT = True
    check(m_new["found"] and m_new["lettery"] > 0.8, "слипшиеся буквы строки — найдены: %s %.2f" % (m_new["found"], m_new["lettery"]))
    check(not m_old["found"], "страж: без правила то же «не надпись»: %.2f" % m_old["lettery"])
    # Отрицательная: сплошная полоса плашки по ширине кропа — по-прежнему не надпись.
    bar = np.asarray(Image.fromarray(np.full((80, 150, 3), 120, np.uint8)))
    bar = bar.copy()
    bar[20:60, :] = 250
    check(not tp.measure(bar, "X", 2, 38.0)["found"], "сплошная полоса — не буквы")
    noise = np.random.default_rng(3).normal(128, 45, (80, 150, 3)).clip(0, 255).astype("uint8")
    check(not tp.measure(noise, "NOISE", 2, 38.0)["found"], "шум — не буквы")

# ─── Т32. Слой и кривые ──────────────────────────────────────────────────
print("=== Т32. Сверка со слоем: глифы дуги, хвост за точным концом, остаток краски ===")
import importers  # noqa: E402
import main  # noqa: E402

PW, PH = 400, 600


def tagged(im):
    b = io.BytesIO()
    im.save(b, format="PNG")
    return importers.tag_figure(b.getvalue(), 0, [0.0, 0.0, 1.0, 1.0])


def lay_with(slots):
    return {"pages": [[0.0, 0.0, float(PW), float(PH)]],
            "boxes": {"1": [{"page": 0, "x0": 0, "x1": 1, "top": 1, "bottom": 0, "size": 8, "slots": slots}]}}


# 1. Рамки дуговой строки — по глифам.
arc_pts = []
import math as _m  # noqa: E402
for k in range(14):
    a = _m.radians(200 + k * 10)
    arc_pts.append([200 + 100 * _m.cos(a), 440 + 100 * _m.sin(a), -80 + k * 10, 8.0, 1, "A",
                    [200 + 100 * _m.cos(a) + 3, 440 + 100 * _m.sin(a) + 1]])
arc_slot = [0, 0, 0, 8.0, "", None, 14, 1, {"pts": arc_pts, "end": arc_pts[-1][6], "curved": True}]
lay_arc = lay_with([arc_slot])
rects_g, _g, _e, _s = main._layer_rects(lay_arc, 0)
main.LAYER_ARC_GLYPHS = False
rects_b, _g, _e, _s = main._layer_rects(lay_arc, 0)
main.LAYER_ARC_GLYPHS = True
check(len(rects_g) == 14 and len(rects_b) == 1, "дуга: рамка на каждый глиф, а не одна на всю дугу: %d / %d" % (len(rects_g), len(rects_b)))
im32 = Image.new("RGB", (PW, PH), "white")
d32 = ImageDraw.Draw(im32)
d32.text((170, PH - 385), "Prevent complications", font=ImageFont.truetype(FR, 10), fill=(0, 0, 0))
d32.text((170, PH - 370), "Optimize quality", font=ImageFont.truetype(FR, 10), fill=(0, 0, 0))
lbs = [[168, PH - 386, 270, PH - 372], [168, PH - 371, 270, PH - 357]]
blob32 = tagged(im32)


def fresh(layout, lboxes):
    rec = {"w": PW, "h": PH, "part": "pdfpage/0000.png",
           "blocks": [{"box": [168, min(l[1] for l in lboxes), 270, max(l[3] for l in lboxes)],
                       "rows": len(lboxes), "lineH": 14, "conf": 0.9, "flat": 0.6, "lineBoxes": lboxes}]}
    main._mark_layer_blocks(rec, blob32, {"layout": layout})
    return rec


main.LAYER_RESIDUAL = False
rec_g = fresh(lay_arc, lbs)
main.LAYER_ARC_GLYPHS = False
rec_b = fresh(lay_arc, lbs)
main.LAYER_ARC_GLYPHS = True
main.LAYER_RESIDUAL = True
check(not any(b.get("skip") for b in rec_g["blocks"]), "середина дуги глифами не накрыта — строки читаются")
check(rec_b["blocks"][0].get("skip") == "layer", "страж: прежняя рамка всей дуги объявляла середину слоем")

# 2. Хвост за точным концом строки слоя («Optimize» слоем, «quality of life» кривыми).
im_t = Image.new("RGB", (PW, PH), "white")
dt = ImageDraw.Draw(im_t)
f10 = ImageFont.truetype(FR, 10)
dt.text((100, 100), "Intro line of text", font=f10, fill=(0, 0, 0))
dt.text((100, 130), "Optimize quality of life", font=f10, fill=(0, 0, 0))
blob_t = tagged(im_t)
base_y = PH - (130 + f10.getmetrics()[0])
w_opt = f10.getlength("Optimize")
lay_t = lay_with([[100.0, PH - (100 + f10.getmetrics()[0]), 100.0 + f10.getlength("Intro line of text"), 10.0, "", 100.0, 17, 1, None, None],
                  [100.0, base_y, 100.0 + w_opt + f10.getlength(" "), 10.0, "", 100.0, 8, 1, None, None]])


def tail_rec(layout):
    rec = {"w": PW, "h": PH, "part": "pdfpage/0000.png",
           "blocks": [{"box": [100, 98, 260, 145], "rows": 2, "lineH": 14, "conf": 0.9, "flat": 0.6,
                       "lineBoxes": [[100, 100, int(100 + f10.getlength("Intro line of text")) + 1, 113],
                                     [100, 130, 190, 143]]}]}
    main._mark_layer_blocks(rec, blob_t, {"layout": layout})
    return rec
main.LAYER_RESIDUAL = False
rt = tail_rec(lay_t)
main.LAYER_EXACT_TAIL = False
rt0 = tail_rec(lay_t)
main.LAYER_EXACT_TAIL = True
main.LAYER_RESIDUAL = True
new_tail = [b for b in rt["blocks"] if not b.get("skip")]
check(any(b["box"][0] >= 100 + w_opt - 2 and b["box"][2] >= 180 for b in new_tail),
      "за точным концом «Optimize» — своя надпись: %s" % [b["box"] for b in new_tail])
check(not any(b["box"][0] >= 100 + w_opt - 2 for b in rt0["blocks"] if not b.get("skip")),
      "страж: без правила хвост оставался «слоем»: %s" % [(b["box"], b.get("skip")) for b in rt0["blocks"]])

# 3. Остаток краски: «Office –» кривыми в строке слоя.
im_o = Image.new("RGB", (PW, PH), "white")
do = ImageDraw.Draw(im_o)
fb10 = ImageFont.truetype(FB, 10)
do.text((60, 200), "Planning –", font=fb10, fill=(0, 0, 0))                    # «кривыми»: слоя там нет
do.text((126, 200), "Walking meetings, standing breaks", font=f10, fill=(0, 0, 0))   # слой
asc = f10.getmetrics()[0]
slot_o = [[56.0, PH - (200 + asc), 126.0 + f10.getlength("Walking meetings, standing breaks"), 10.0, "", 126.0, 40, 1, None, None,
           [[58.0, 124.0]]]]
lay_o = lay_with(slot_o)
blob_o = tagged(im_o)


def resid(layout, blob, blocks=None, w=PW, h=PH):
    rec = {"w": w, "h": h, "part": "pdfpage/0000.png", "layerRule": 4,
           "blocks": blocks if blocks is not None else [
               {"box": [56, 197, 330, 215], "rows": 1, "lineH": 13, "conf": 0.9, "flat": 0.6, "skip": "layer"}]}
    n = main._layer_residual_add(rec, blob, {"layout": layout})
    return n, rec


n_o, rec_o = resid(lay_o, blob_o)
new_o = rec_o["blocks"][1:]
check(n_o == 1 and new_o and new_o[0]["box"][0] <= 70 and new_o[0]["box"][2] <= 126 + 4 and new_o[0].get("residual"),
      "метка кривыми в разрыве строки слоя — новый блок только на ней: %s" % [b["box"] for b in new_o])
# Той же строки без метки — остатка нет.
im_o2 = Image.new("RGB", (PW, PH), "white")
ImageDraw.Draw(im_o2).text((126, 200), "Walking meetings, standing breaks", font=f10, fill=(0, 0, 0))
n_o2, _r = resid(lay_o, tagged(im_o2))
check(n_o2 == 0, "строка слоя целиком в слое — остатка нет")

# 4. Ряд над и под строками слоя (круг стр. 19): над и под — две группы.
im_c = Image.new("RGB", (PW, PH), (20, 90, 140))
dc2 = ImageDraw.Draw(im_c)
fw = ImageFont.truetype(FB, 9)
dc2.text((150, 300), "To avoid", font=fw, fill=(255, 255, 255))
dc2.text((140, 314), "therapeutic inertia,", font=fw, fill=(255, 255, 255))
dc2.text((150, 328), "3-6 months)", font=fw, fill=(255, 255, 255))
asc9 = fw.getmetrics()[0]
slot_c = [[140.0, PH - (314 + asc9), 140.0 + fw.getlength("therapeutic inertia,"), 9.0, "", 140.0, 20, 1, None, None]]
n_c, rec_c = resid(lay_with(slot_c), tagged(im_c), blocks=[
    {"box": [138, 312, 250, 327], "rows": 1, "lineH": 14, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
rows_c = sorted(b["box"][1] for b in rec_c["blocks"][1:])
check(n_c == 2 and rows_c[0] < 312 < rows_c[1], "строка над и строка под слоем — два блока: %s" % [b["box"] for b in rec_c["blocks"][1:]])

# 5. Слово слоем рядом с кривой фразой: рамка охватывает обе части.
im_q = Image.new("RGB", (PW, PH), (60, 170, 70))
dq = ImageDraw.Draw(im_q)
dq.text((100, 200), "Optimize", font=fw, fill=(255, 255, 255))
dq.text((100 + fw.getlength("Optimize "), 200), "quality of life today", font=fw, fill=(255, 255, 255))
slot_q = [[100.0, PH - (200 + asc9), 100.0 + fw.getlength("Optimize "), 9.0, "", 100.0, 8, 1, None, None]]
n_q, rec_q = resid(lay_with(slot_q), tagged(im_q), blocks=[
    {"box": [98, 198, 200, 212], "rows": 1, "lineH": 13, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
nb = rec_q["blocks"][1:]
check(n_q == 1 and nb[0]["box"][0] <= 101, "слово слоя и фраза кривыми рядом — рамка с обеими частями: %s" % [b["box"] for b in nb])

# 6. Отрицательные: тире, пунктир, маркеры, значок, шум не группы.
im_n = Image.new("RGB", (PW, PH), "white")
dn = ImageDraw.Draw(im_n)
dn.text((126, 200), "Walking meetings, standing breaks", font=f10, fill=(0, 0, 0))      # слой
for k in range(14):                                       # пунктир под строкой
    dn.rectangle([60 + 9 * k, 216, 65 + 9 * k, 217], fill=(0, 0, 0))
for k in range(5):                                        # маркеры «•» над строкой
    dn.ellipse([60 + 14 * k, 188, 63 + 14 * k, 191], fill=(0, 0, 0))
dn.ellipse([20, 196, 34, 210], fill=(0, 0, 0))            # значок слева
dn.rectangle([300, 204, 330, 205], fill=(0, 0, 0))        # тире справа
n_n, _r = resid(lay_o, tagged(im_n), blocks=[
    {"box": [56, 190, 340, 220], "rows": 2, "lineH": 13, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
check(n_n == 0, "пунктир, маркеры, значок и тире остатком не становятся: %d" % n_n)
# QR-подобная россыпь одинаковых квадратиков вплотную к строке слоя.
im_qr = Image.new("RGB", (PW, PH), "white")
dq2 = ImageDraw.Draw(im_qr)
dq2.text((126, 200), "Walking meetings, standing breaks", font=f10, fill=(0, 0, 0))
rng_q = np.random.default_rng(11)
for gy in range(0, 5):
    for gx in range(0, 14):
        if rng_q.random() < 0.55:
            dq2.rectangle([60 + 3 * gx, 185 + 3 * gy, 61 + 3 * gx, 186 + 3 * gy], fill=(0, 0, 0))
n_q2, _r = resid(lay_o, tagged(im_qr), blocks=[
    {"box": [56, 180, 340, 215], "rows": 2, "lineH": 13, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
check(n_q2 == 0, "россыпь одинаковых квадратиков (QR) остатком не становится: %d" % n_q2)
rng = np.random.default_rng(7)
nz = Image.fromarray((255 - rng.integers(0, 60, (PH, PW, 3))).astype("uint8"))
n_z, _r = resid(lay_o, tagged(nz))
check(n_z == 0, "шум скана остатком не становится")
# Серый штамп вплотную за концом чёрной строки слоя — не продолжение строки.
im_st = Image.new("RGB", (PW, PH), "white")
dst = ImageDraw.Draw(im_st)
dst.text((126, 200), "Walking meetings, standing breaks", font=f10, fill=(0, 0, 0))
w_line = f10.getlength("Walking meetings, standing breaks")
dst.text((126 + w_line + 3, 198), "Scanned with", font=ImageFont.truetype(FB, 12), fill=(165, 165, 165))
slot_st = [[126.0, PH - (200 + asc), 126.0 + w_line, 10.0, "", 126.0, 33, 1, None, None]]
n_st, _r = resid(lay_with(slot_st), tagged(im_st), blocks=[
    {"box": [124, 196, 330, 216], "rows": 1, "lineH": 13, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
check(n_st == 0, "бледный штамп за концом чёрной строки слоя остатком не становится: %d" % n_st)
im_st2 = Image.new("RGB", (PW, PH), "white")
dst2 = ImageDraw.Draw(im_st2)
dst2.text((126, 200), "Walking meetings, standing breaks", font=f10, fill=(0, 0, 0))
dst2.text((126 + w_line + 3, 200), "quality of life", font=f10, fill=(0, 0, 0))
n_st2, _r = resid(lay_with(slot_st), tagged(im_st2), blocks=[
    {"box": [124, 196, 330, 216], "rows": 1, "lineH": 13, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
check(n_st2 == 1, "та же чёрная краска за концом строки — остаток: %d" % n_st2)

# Потолок: «остатка» на странице больше потолка — шумная схема, ни одного блока.
main.RESIDUAL_MAX_PAGE = 1
n_m, rec_m = resid(lay_with(slot_c), tagged(im_c), blocks=[
    {"box": [138, 312, 250, 327], "rows": 1, "lineH": 14, "conf": 0.9, "flat": 0.6, "skip": "layer"}])
main.RESIDUAL_MAX_PAGE = 6
check(n_m == 0 and rec_m.get("residualSkipped") == 2, "два «остатка» при потолке 1 — ни одного блока, число названо: %s" % rec_m.get("residualSkipped"))
# Записи без слоя в карте остатка не ищут (иначе всё — «остаток»).
n_e, _r = resid({"pages": [[0.0, 0.0, float(PW), float(PH)]], "boxes": {}}, blob_o)
check(n_e == 0, "карта без строк слоя — остатка нет")
# Версия правила: старые записи пересверяются, новые — нет.
check(main.LAYER_RULE == 5, "версия правила сверки — 5")
check(main._residual_due({"part": "pdfpage/0003.png", "layerRule": 4, "blocks": [{"skip": "layer", "box": [1, 1, 2, 2]}]}),
      "запись правила 4 с блоком слоя — к пересверке")
check(not main._residual_due({"part": "pdfpage/0003.png", "layerRule": 5, "blocks": [{"skip": "layer", "box": [1, 1, 2, 2]}]})
      and not main._residual_due({"part": "word/media/image1.png", "layerRule": 4, "blocks": [{"skip": "layer"}]}),
      "запись правила 5 и картинка документа — нет")

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
