# -*- coding: utf-8 -*-
"""Правила Т10–Т15b выгрузки PDF «как в оригинале» (проект 14, стр. 1, 4, 10,
12, 19, 31; разбор слипшихся кусков 13.10.2026):

  Т10  одинокий маркер «•» в конце строки — своя ячейка, а не хвост левой
       (`pdfpages_worker._h_groups`);
  Т11  значок-контур (галочка, кружок) начинает пункт списка — с тремя
       защитами от ложных срабатываний (`pdfpages_worker`, `pdftext`);
  Т12  пункт со значком слева — якорь: не продолжает историю и рамку выше,
       пункт из одной строки сохраняет СВОЙ левый край (`layout_pdf`);
  Т13  хвост перевода, ложащийся на соседний пункт, — сужение вместо хвоста;
  Т14  блоки надписей картинки: фон мелкой строки, линия-разделитель,
       пересборка непокрытых строк (`image_text`, `main._split_uncovered`);
  Т15b абзац со слотом-разрывом в историю страницы не входит.
"""
import io, os, sys, contextlib
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_pdf
import pdfpages_worker
import pdftext
import textcount
from pdf_fixture import make_pdf

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# ─── Т10 ─────────────────────────────────────────────────────────────
print("=== Т10. Одинокий маркер в конце строки — своя ячейка ===")
cw = 0.5
left = ("• Low-energy diet (LED)", 50.0, 300.0, 6.0)        # конец ≈ 50 + 23·0.5·6 = 119
far = ("•", 160.0, 300.0, 6.0)                              # правая ячейка, зазор 41 пт
near = ("•", 122.0, 300.0, 6.0)                             # вплотную (3 пт < 3 кеглей)
digits = ("12", 160.0, 300.0, 6.0)                          # номер страницы у оглавления
ends = {(50, 300): 119.0}                                   # точный конец краски левой части
g = pdfpages_worker._h_groups([0, 1], [left, far], cw, (), ends)
check(len(g) == 2 and g[1] == [1], "маркер далеко от конца левой части — отдельная группа: %s" % g)
g = pdfpages_worker._h_groups([0, 1], [left, near], cw, (), ends)
check(len(g) == 1, "маркер вплотную — по-прежнему хвост строки: %s" % g)
g = pdfpages_worker._h_groups([0, 1], [left, digits], cw, (), ends)
check(len(g) == 1, "цифры в конце строки (оглавление) — по-прежнему хвост: %s" % g)
vled = ("• Very-low-energy diet (VLED)", 47.8, 191.1, 5.48)       # конец 105.5, зазор до маркера 9 пт
mark = ("•", 114.6, 191.1, 5.48)
e2 = {(48, 191): 105.5}
g = pdfpages_worker._h_groups([0, 1], [vled, mark], cw, (114.6,), e2)
check(len(g) == 2, "маркер в начале колонки таблицы (`cols`), зазор меньше трёх кеглей — своя ячейка: %s" % g)
g = pdfpages_worker._h_groups([0, 1], [vled, mark], cw, (), e2)
check(len(g) == 1, "тот же зазор вне колонки таблицы — хвост строки: %s" % g)
g = pdfpages_worker._h_groups([0, 1], [left, far], cw)
check(len(g) == 1, "точного конца левой части нет (оценка занижена у узкого шрифта) — хвост, как раньше: %s" % g)

# ─── Т11 ─────────────────────────────────────────────────────────────
print("=== Т11. Значок-контур начинает пункт ===")


def rec(t, x0, y, s=6.0, x1=None):
    return {"t": t, "x0": x0, "x1": x1 if x1 is not None else x0 + 100.0, "y": y, "s": s}


icon = lambda x, y: [x, y - 0.5, x + 4.6, y + 4.1]       # noqa: E731  кружок 4.6 пт
recs = [rec("Item one with a long description", 50.0, 500.0),
        rec("Item two with a long description", 50.0, 492.8),
        rec("Item three with a long description", 50.0, 485.6)]
pdftext._mark_icon_bullets(recs, [], [icon(41.5, 500.0), icon(41.5, 492.8), icon(41.5, 485.6)])
check([bool(r.get("bul")) for r in recs] == [True, True, True], "три значка — три пункта")
# защита 3: строка продолжает фразу (строчная) — абзац не начинает
recs = [rec("Obesity-related", 50.0, 500.0), rec("complications including:", 50.0, 493.0)]
pdftext._mark_icon_bullets(recs, [], [icon(41.5, 493.0)])
check(not recs[1].get("bul"), "значок у строки со строчной буквы — не начало абзаца")
# защита 1: значок дальше полутора кеглей (цифра ссылки соседней колонки)
recs = [rec("Of 42 trials", 158.7, 237.0)]
pdftext._mark_icon_bullets(recs, [], [[138.3, 234.6, 146.3, 242.6]])
check(not recs[0].get("bul"), "значок в двух кеглях от строки — не маркер (ссылка соседней колонки)")
# защита 2: значок у конца чужой строки на той же базовой
recs = [rec("Left column text ends here", 20.0, 237.0, x1=140.0), rec("Right column", 150.0, 237.0)]
pdftext._mark_icon_bullets(recs, [], [[141.5, 235.0, 146.1, 239.6]])
check(not recs[1].get("bul"), "значок вплотную к концу чужой строки — не маркер")
# картинка-значок — прежнее правило (до 2.5 кегля), защит нет
recs = [rec("lowercase after picture", 50.0, 500.0)]
pdftext._mark_icon_bullets(recs, [[38.0, 499.5, 42.6, 504.1]], [])
check(recs[0].get("bul"), "картинка слева — маркер, как раньше")

# Через настоящий разбор: контуры в потоке страницы → три абзаца, не один.


def circle(cx, cy, r):
    k = 0.5523 * r
    return ("%.2f %.2f m %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c "
            "%.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c f" % (
                cx + r, cy, cx + r, cy + k, cx + k, cy + r, cx, cy + r, cx - k, cy + r,
                cx - r, cy + k, cx - r, cy, cx - r, cy - k, cx - k, cy - r, cx, cy - r,
                cx + k, cy - r, cx + r, cy - k, cx + r, cy))


def page_with_items(icons_on=True):
    ops = []
    for k, t in enumerate(["Item one with a rather long description of the first point here",
                           "Item two with a rather long description of the second point here",
                           "Item three with a rather long description of the third point here"]):
        y = 500 - k * 7.2
        if icons_on:
            ops.append(("raw", "0.2 0.6 0.3 rg " + circle(44, y + 2, 2.3)))
            ops.append(("raw", "0 g"))
        ops.append(("t", 50, y, 6.0, t))
    for k in range(12):
        ops.append(("t", 50, 400 - k * 8, 7.0,
                    "Ordinary body text line number %d that is long enough to set the median length" % k))
    return ops


def paragraphs(ops):
    pdf = make_pdf([ops], size=(400, 600))
    pages, geoms = textcount._pdf_pages_geom(pdf, [])
    with contextlib.redirect_stdout(io.StringIO()):
        res = pdftext.clean(pages, geom=geoms)
    return [it[1] for it in res["items"] if it[0] == "p"], geoms


paras, geoms = paragraphs(page_with_items(True))
check(bool(geoms[0].get("icons")), "worker отдал значки-контуры у начала строк: %s" % (geoms[0].get("icons") or [])[:1])
check(sum(1 for p in paras if p.startswith("Item")) == 3, "три пункта со значками — три абзаца: %s" % [p[:12] for p in paras])
paras, _g = paragraphs(page_with_items(False))
check(sum(1 for p in paras if p.startswith("Item")) == 1, "те же строки без значков — один абзац (как и было)")
check(pdftext.RULES_VERSION >= 15, "правила разбора подняты до 15: %s" % pdftext.RULES_VERSION)

# ─── Т12 и Т15b: история страницы ────────────────────────────────────
print("=== Т12. Пункт со значком — якорь; свой левый край ===")


def slot(x, y, size=5.5, x1=None, mark=False, **kw):
    d = {"x": x, "x0": x, "x1": x1 if x1 is not None else x + 30.0, "y": y, "size": size,
         "page": 0, "style": "", "below": 0.0}
    if mark:
        d["_mark"] = True
    d.update(kw)
    return d


sw = lambda t, font, size: len(t) * 0.5 * size           # noqa: E731
font_of = lambda sd: "F"                                  # noqa: E731


def make_story(items_mark=False, gap_second=False):
    """Заголовок из двух строк (левый край 25.7) и четыре пункта (33.5)."""
    metas, plans = [], []

    def add(idx, text, orig, hs=1.0):
        metas.append({"idx": idx, "text": text, "sw": sw, "nospace": False, "scattered": False,
                      "fam": "", "hy": None, "orig": orig})
        plans.append((list(orig), [""] * len(orig), [1.0] * len(orig), [], font_of, "left",
                      [1.0] * len(orig)))
    add(0, "MEASUREMENT AND FEEDBACK", [slot(25.7, 236.4, 6.0, 85.0), slot(28.4, 230.3, 6.0, 83.0)])
    for k, t in enumerate(["Clinical outcomes", "Biomedical data", "PROMs", "Self reported"]):
        extra = {}
        if gap_second and k == 1:
            extra = {"_gapR": 40.0}
        add(1 + k, t, [slot(33.5, 222.0 - 6.6 * k, 5.5, 64.0, mark=items_mark, **extra)])
    _ = layout_pdf._stories(plans, metas, {}, None)
    return plans, metas


plans, metas = make_story(items_mark=False)
xs = [plans[k][0][0]["x"] for k in range(1, 5)]
check(all(abs(x - 33.5) < 0.6 for x in xs),
      "пункт из одной строки сохраняет свой левый край, а не заголовка (25.7): %s" % [round(x, 1) for x in xs])
check(all(plans[k][0][0].get("_story") for k in range(1, 5)), "без значков история по-прежнему собирается")
plans, metas = make_story(items_mark=True)
check(not any(plans[k][0][0].get("_story") for k in range(1, 5)),
      "пункты со значками из истории выше не берутся")
check(all(plans[k][0][0]["x"] == 33.5 and plans[k][0][0]["y"] == 222.0 - 6.6 * (k - 1) for k in range(1, 5)),
      "и остаются на своих местах (якорь)")
# отметка слотов по значкам страницы
a = slot(50.0, 500.0)
b2 = slot(50.0, 492.8)
n_ = layout_pdf._icon_marks([a, b2], [[41.5, 499.5, 46.1, 504.1]])
check(n_ == 1 and a.get("_mark") and not b2.get("_mark"), "значок у первой строки отмечает только её")
a = slot(150.0, 237.0)
o_ = slot(20.0, 237.0, x1=140.0)
layout_pdf._icon_marks([a, o_], [[141.5, 235.0, 146.1, 239.6]])
check(not a.get("_mark"), "значок у конца чужой строки не отмечает соседа")
a = slot(158.7, 237.0, 6.65)
layout_pdf._icon_marks([a], [[138.3, 234.6, 146.3, 242.6]])
check(not a.get("_mark"), "значок дальше полутора кеглей не отмечает")

print("=== Т15b. Слот с разрывом в историю не входит ===")
plans, metas = make_story(items_mark=False, gap_second=True)
check(not plans[2][0][0].get("_story") and plans[2][0][0]["x"] == 33.5,
      "второй пункт со слотом-разрывом печатается на своём месте (x=%.1f), не историей" % plans[2][0][0]["x"])
check(not metas[2].get("story"), "и в истории не числится")

# ─── Т13 ─────────────────────────────────────────────────────────────
print("=== Т13. Хвост ложится на соседа — сужение вместо хвоста ===")
sl_ = [slot(402.2, 167.2, 5.49, 424.3)]
txt = "Сердечная недостаточность"
lines, f, rest, hs = layout_pdf._fit_slots(txt, sl_, sw, font_of, "left", False, 0.55, layout_pdf.FLOOR_HARD)
check(bool(rest), "без последнего хода слово остаётся хвостом (%s, кегль %.2f)" % (rest, f))
lines2, f2, rest2, hs2 = layout_pdf._fit_slots(txt, [slot(402.2, 167.2, 5.49, 424.3)], sw, font_of, "left",
                                               False, 0.55, layout_pdf.FLOOR_HARD,
                                               tail_hs=layout_pdf.TAIL_HS_FLOOR)
check(not rest2 and lines2 == [txt] and hs2 >= layout_pdf.TAIL_HS_FLOOR - 1e-6,
      "с ним — одна строка без хвоста: кегль %.2f, сужение %.2f" % (f2, hs2))
long_ = "Печень (метаболически ассоциированная стеатозная болезнь печени)"
_l, _f, rest3, _h = layout_pdf._fit_slots(long_, [slot(402.2, 161.2, 5.49, 426.2)], sw, font_of, "left",
                                          False, 0.55, layout_pdf.FLOOR_HARD,
                                          tail_hs=layout_pdf.TAIL_HS_FLOOR)
check(bool(rest3), "не влезает и суженным — хвост остаётся (и называется наложением), текст не теряется")

# ─── Т14 ─────────────────────────────────────────────────────────────
print("=== Т14. Блоки надписей картинки ===")
try:
    import numpy as np
    from PIL import Image, ImageDraw
    import image_text
except Exception as e:                                    # нет numpy — нет и этих проверок
    np = None
    print("  --   пропущено: %s" % e)
if np is not None:
    W, H = 500, 300
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 240, 100], fill=(233, 198, 188))       # левая плашка
    d.rectangle([260, 20, 480, 100], fill=(233, 198, 188))      # правая плашка
    d.rectangle([20, 130, 480, 190], fill=(250, 184, 161))      # полоса High
    d.line([(20, 191), (480, 191)], fill=(254, 244, 240), width=2)   # белая линия
    d.rectangle([20, 193, 480, 250], fill=(251, 210, 193))      # полоса Intermediate
    arr = np.asarray(im)
    small = [30, 40, 120, 48]                                   # строка высотой 8 пикселей
    check(image_text._bg_of(arr, small) is not None,
          "фон строки ниже 14 пикселей измеряется (был None): %s" % (image_text._bg_of(arr, small),))
    two_plates = [[30, 30, 120, 38], [270, 30, 360, 38], [40, 42, 110, 50], [280, 42, 350, 50]]
    g = image_text.regroup_boxes(two_plates, arr)
    check(sorted(len(x) for x in g) == [2, 2], "две плашки рядом — два блока по две строки: %s" % [len(x) for x in g])
    l1, l2, l3 = [30, 140, 470, 150], [30, 152, 470, 162], [30, 198, 470, 208]
    g = image_text.regroup_boxes([l1, l2, l3], arr)
    check(sorted(len(x) for x in g) == [1, 2], "полосы High и Intermediate делит белая линия: %s" % [len(x) for x in g])
    check(image_text.divider_between(arr, l2, l3) and not image_text.divider_between(arr, l1, l2),
          "линия найдена между полосами и не найдена внутри полосы")
    g = image_text.regroup_boxes([[30, 30, 200, 38], [30, 40, 200, 48]], arr)
    check(len(g) == 1, "две строки одной плашки — один блок")
    # настоящая функция сверки со слоем
    try:
        import main
        bl = {"conf": 0.9, "flat": 0.5, "align": "center"}
        res = main._split_uncovered(bl, two_plates, [False] * 4, 7, None, arr)
        check(len(res) == 2 and all(r["from"] == 7 and r["rows"] == 2 for r in res),
              "`_split_uncovered` дробит четыре непокрытые строки на два блока: %s" % [r["rows"] for r in res])
        res = main._split_uncovered(bl, [[30, 30, 200, 38], [30, 40, 200, 48]], [False, False], 7, None, arr)
        check(len(res) == 1 and res[0]["rows"] == 2, "строки одной плашки остаются одним блоком")
    except Exception as e:
        check(False, "main._split_uncovered: %r" % (e,))

print()
if fail:
    print("FAIL: %d" % len(fail))
    for f_ in fail:
        print(" -", f_)
    sys.exit(1)
print("OK: правила Т10–Т15b")
