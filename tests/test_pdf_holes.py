# -*- coding: utf-8 -*-
"""Дыры выгрузки PDF «как в оригинале», найденные десятью критиками
проекта 14 (12.10.2026), — правила раздела О в docs/rules/pdf-reading.md.

  1. одно место — один источник: кусок слоя ВНУТРИ прочитанной надписи
     картинки стирается, даже рваный («a!ect», «(e.g.,»); надпись, которая
     повторяет слой под ней («Eye»), не печатается — печатает слой;
  2. история страницы не переходит через НАРИСОВАННОЕ между абзацами
     (линия, строка картинки), не сцепляет ячейки таблицы и пункты
     с отступом под заголовком;
  3. разбор: строки КАПСОМ одной плашки, разорванные в потоке, — один
     абзац; две надписи разных строк, склеенные pypdf в одну, — разные;
  4. длинное слово-перечень рвётся после «/», дуги одной фигуры — близким
     кеглем;
  5. перевод с вариантами через « / » — бесплатная находка ремонта.
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_pdf
import pdftext
import textcount
from pdf_fixture import make_pdf

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 2. История страницы: нарисованное, ячейки, отступ ===")
from PIL import Image, ImageDraw

# Страница 200×200 пт, 2 пикселя на пункт. Колонка x 20..180: строка A
# на базовой 150, строка B на 120; между ними серая линия на y=135.
W = H = 400
im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
yl = H - 135 * 2
d.line([(40, yl), (360, yl)], fill=(120, 120, 120), width=3)
gray = im.convert("L")
sample = (im, 2.0, (0.0, 0.0), gray)
A = {"x": 20.0, "x0": 20.0, "x1": 180.0, "y": 150.0, "size": 6.0, "page": 0}
B = {"x": 20.0, "x0": 20.0, "x1": 180.0, "y": 120.0, "size": 6.0, "page": 0}
layout_pdf._drawn_below(sample, [A], 1.0, [A, B])
check(A.get("_drawn") is not None, "линия под строкой найдена: %s" % A.get("_drawn"))
check(layout_pdf._drawn_between(A, B), "между абзацами нарисовано — история не сцепляет")
# Та же пара без линии: буквы строки B вырезаны по её рамке, «нарисованным» не считаются.
im2 = Image.new("RGB", (W, H), "white")
d2 = ImageDraw.Draw(im2)
d2.rectangle([40, H - 126 * 2, 360, H - 119 * 2], fill="black")      # «буквы» строки B
A2 = {k: v for k, v in A.items() if k != "_drawn"}
layout_pdf._drawn_below((im2, 2.0, (0.0, 0.0), im2.convert("L")), [A2], 1.0, [A2, B])
check(not layout_pdf._drawn_between(A2, B), "буквы следующего абзаца — не «нарисованное»")
# Растровая строка (её нет в слое) между пунктами: текст поверх неё — то же нарисованное.
im3 = Image.new("RGB", (W, H), "white")
ImageDraw.Draw(im3).rectangle([40, H - 138 * 2, 200, H - 133 * 2], fill="black")
A3 = {k: v for k, v in A.items() if k != "_drawn"}
layout_pdf._drawn_below((im3, 2.0, (0.0, 0.0), im3.convert("L")), [A3], 1.0, [A3, B])
check(layout_pdf._drawn_between(A3, B), "строка только в картинке между пунктами — не сцепляет")

# Ячейки таблицы: две однострочные узкие ячейки друг под другом, у каждой
# сосед в ряду. Одинокая подпись из двух строк — сцепляется.
ra = {"x0": 100.0, "x1": 120.0}
rb = {"x0": 100.0, "x1": 120.0}
la = {"x": 100.0, "x1": 120.0, "y": 300.0, "size": 4.0, "page": 0}
fb = {"x": 100.0, "x1": 120.0, "y": 294.0, "size": 4.0, "page": 0}
mates = {0: [la, fb, {"x": 130.0, "x1": 150.0, "y": 300.0, "size": 4.0, "page": 0},
             {"x": 130.0, "x1": 150.0, "y": 294.0, "size": 4.0, "page": 0}]}
PA = {"nlines": 1, "msize": 4.0, "boxes": [ra], "runs": [[la]], "words": ["MACE"], "major": "r"}
PB = {"nlines": 1, "msize": 4.0, "boxes": [rb], "runs": [[fb]], "words": ["польза"], "major": "r"}
check(layout_pdf._cells(PA, PB, mates), "шапка и ячейка таблицы (соседи в ряду) — не история")
check(not layout_pdf._cells(PA, PB, {0: [la, fb]}), "одинокая подпись из двух строк — история")
check(layout_pdf.STORY_V_X0 <= 1.5, "пункты с отступом в два кегля под заголовком — не та колонка")
# Красная строка абзаца на допуск не влияет: левый край куска — самое левое
# начало его строк (`_run_box`), а не первая строка.
rb_ = layout_pdf._run_box([{"x": 30.0, "x1": 180.0, "y": 100.0, "size": 6.0, "page": 0},
                           {"x": 20.0, "x1": 180.0, "y": 92.0, "size": 6.0, "page": 0}])
check(rb_["x0"] == 20.0, "красная строка не сдвигает левый край абзаца")
# Тень у корешка (тёмная полоса у края колонки по всей высоте) — не «нарисованное».
im4 = Image.new("RGB", (W, H), "white")
ImageDraw.Draw(im4).rectangle([40, 0, 52, H], fill=(90, 90, 90))
A4 = {k: v for k, v in A.items() if k != "_drawn"}
layout_pdf._drawn_below((im4, 2.0, (0.0, 0.0), im4.convert("L")), [A4], 1.0, [A4, B])
check(not layout_pdf._drawn_between(A4, B), "тень у края колонки не запрещает историю: %s" % A4.get("_drawn"))
# Хвост строки за оценкой конца (`x1`) — буквы этой строки, не рисунок.
im5 = Image.new("RGB", (W, H), "white")
ImageDraw.Draw(im5).rectangle([300, H - 126 * 2, 370, H - 119 * 2], fill="black")
Bs = dict(B, x1=150.0)
A5 = {k: v for k, v in A.items() if k != "_drawn"}
layout_pdf._drawn_below((im5, 2.0, (0.0, 0.0), im5.convert("L")), [A5], 1.0, [A5, Bs])
check(not layout_pdf._drawn_between(A5, Bs), "хвост строки за оценкой конца — не рисунок")

print("=== 4. Перенос по «/», дуги одной фигуры ===")
w_of = lambda t: 5.0 * len(t)                                   # noqa: E731
got = layout_pdf._hyph_split("показатели/липиды/артериальное", None, 5.0 * 20, w_of)
check(got == ("показатели/липиды/", "артериальное"), "перечень рвётся после «/»: %s" % (got,))
for w in ("и/или", "mg/kg", "TB/HIV", "12/05/2026", "https://doi.org/x"):
    check(layout_pdf._hyph_split(w, None, 5.0, w_of) is None, "«%s» по «/» не рвётся" % w)

def arc_ent(cx, cy, r, em, f, page=0):
    return {"b": {"page": page, "_paint": {"em": em, "arc": {"cx": cx, "cy": cy, "r": r,
                                                            "t0": 0, "t1": 1, "up": 1}}},
            "f": f, "size": em * f, "step": em * f}
plan = [arc_ent(100, 100, 50, 8, 1.0), arc_ent(102, 99, 60, 8, 0.5), arc_ent(300, 300, 50, 8, 1.0)]
st = {}
layout_pdf._harmonize_arcs(plan, st)
check(abs(plan[0]["f"] - 0.85) < 1e-6 and plan[1]["f"] == 0.5,
      "дуги одного кольца — ближе по кеглю (не мельче 0.85 своей): %s" % [p["f"] for p in plan])
check(plan[2]["f"] == 1.0, "дуга другой фигуры не тронута")
plan2 = [arc_ent(102, 99, 60, 8, 0.5), arc_ent(100, 100, 50, 8, 1.0), arc_ent(101, 100, 55, 8, 0.9)]
layout_pdf._harmonize_arcs(plan2, {})
check([round(p["f"], 3) for p in plan2] == [0.5, 0.85, 0.765],
      "итог не зависит от порядка обхода (по снимку): %s" % [p["f"] for p in plan2])

print("=== 3. Разбор: строки плашки, две надписи в одной строке pypdf ===")
def _bt(x, y, sz, t):
    """Надпись отдельным текстовым блоком, как в боевом файле: pypdf до 6.18
    отдаёт у второго куска одного блока координаты нулями, и тест мерил бы
    версию pypdf, а не правило."""
    return ("raw", "BT /F1 %s Tf 1 0 0 1 %s %s Tm {HEX:%s:HEX} Tj ET" % (sz, x, y, t))


# Плашки — каждая в своём ряду: в боевом файле три плашки стоят в одном
# ряду, и pypdf до 6.18 склеивает такой ряд в одну строку с координатами
# второго куска нулями — тест мерил бы версию pypdf. Ряд из трёх плашек
# проверен на всей книге проекта 14 обеими версиями (5 изменений, все целевые).
# Строки одной плашки по-прежнему идут в потоке ВПЕРЕМЕШКУ с чужими.
P = [_bt(145, 343.0, 4.3, "HEALTHY LIFESTYLE"), _bt(204, 300.0, 4.3, "DIABETES SELF-"),
     _bt(255, 260.0, 4.3, "ADDRESS SOCIAL DETERMINANTS"),
     _bt(153, 337.8, 4.3, "BEHAVIORS"), _bt(195, 294.8, 4.3, "MANAGEMENT EDUCATION"),
     _bt(267, 254.8, 4.3, "OF HEALTH (SDOH)")]
pdf = make_pdf([P])
pg, gm = textcount._pdf_pages_geom(pdf, [])
paras = [it[1] for it in pdftext.clean(pg, geom=gm)["items"] if it[0] == "p"]
check("HEALTHY LIFESTYLE BEHAVIORS" in paras, "плашка «HEALTHY LIFESTYLE / BEHAVIORS» — один абзац: %s" % paras)
check(any(p.startswith("DIABETES SELF") and p.endswith("MANAGEMENT EDUCATION") for p in paras),
      "«DIABETES SELF- / MANAGEMENT EDUCATION» — один абзац")
check("ADDRESS SOCIAL DETERMINANTS OF HEALTH (SDOH)" in paras, "третья плашка — один абзац")
# Обычный абзац книги из двух строк капсом с точкой на конце первой — не склеивается.
P2 = [("t", 40, 300, 6, "FIRST SENTENCE."), ("t", 40, 293, 6, "SECOND ONE")]
p2 = make_pdf([P2 + [("t", 200, 300, 6, "SIDE")]])
pg2, gm2 = textcount._pdf_pages_geom(p2, [])
paras2 = [it[1] for it in pdftext.clean(pg2, geom=gm2)["items"] if it[0] == "p"]
check(not any("FIRST SENTENCE. SECOND ONE" == p for p in paras2), "строка с точкой — не плашка: %s" % paras2)
check(pdftext.RULES_VERSION >= 12, "правила разбора подняты — проекты пересоберутся")
# Столбец сокращений таблицы — не плашка.
P3 = [("t", 100, 300, 5, "HIV"), ("t", 100, 294, 5, "AIDS"), ("t", 160, 300, 5, "virus"),
      ("t", 160, 294, 5, "syndrome")]
p3 = make_pdf([P3])
pg3_, gm3_ = textcount._pdf_pages_geom(p3, [])
paras3_ = [it[1] for it in pdftext.clean(pg3_, geom=gm3_)["items"] if it[0] == "p"]
check("HIV AIDS" not in paras3_, "сокращения в столбик не склеиваются: %s" % paras3_)
from collections import Counter as _C
ea = {"geo": [0, 145.0, 343.0, 183.8, 4.3, ""], "t": "HEALTHY LIFESTYLE"}
eo = {"geo": [0, 204.0, 343.0, 235.5, 4.3, ""], "t": "DIABETES SELF-"}
eb = {"geo": [0, 153.3, 337.8, 175.4, 4.3, ""], "t": "BEHAVIORS"}
args = (["HEALTHY LIFESTYLE", "DIABETES SELF-", "BEHAVIORS"], [[ea], [eo], [eb]], [ea, eo, eb], _C())
on_p, _g = pdftext._merge_label_lines(*args, _C())
pdftext.LABEL_JOIN = False
off_p, _g = pdftext._merge_label_lines(*args, _C())
pdftext.LABEL_JOIN = True
check("HEALTHY LIFESTYLE BEHAVIORS" in on_p and "HEALTHY LIFESTYLE BEHAVIORS" not in off_p,
      "склейка строк плашки через поток; PDF_LABEL_JOIN=0 её выключает: %s / %s" % (on_p, off_p))

# Отдельными кусками потока, как в боевом файле (pypdf склеивает их в одну строку).
R = [("t", 172, 340.8, 5.5, "PROGRAMS THAT ADDRESS:"), ("t", 55.6, 336.6, 5.5, "24-H PHYSICAL")]
pdf3 = make_pdf([R])
pg3, gm3 = textcount._pdf_pages_geom(pdf3, [])
paras3 = [it[1] for it in pdftext.clean(pg3, geom=gm3)["items"] if it[0] == "p"]
check(not any("ADDRESS:24" in p or "ADDRESS: 24" in p for p in paras3),
      "надписи с разных концов и разных строк — разные абзацы: %s (строки pypdf: %s)" % (paras3, pg3))

print("=== 1 и 5. Один источник; варианты через « / » ===")
import contextlib
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import main
check(main._piece_in("a!ect", "factors that affect achievement"), "«a!ect» — кусок надписи (лигатура ff знаком «!»)")
check(main._piece_in("(e.g.,", "achievement of goals (e.g., secondary causes)"), "«(e.g.,» — кусок надписи")
check(not main._piece_in("insulin", "achievement of goals"), "чужое слово — не кусок")
check(main._same_text("Eye", "Eye") and not main._same_text("Eye", "Eyes"),
      "короткая надпись совпадает со слоем только буква в букву")
check(main._same_text("Reconsider DSMES to support self-efficacy",
                      "Reconsider DSMES to support self-eﬃcacy"), "лигатура «ﬃ» не мешает")
seg = {"source": "STEPPING", "target": "ШАГАНИЕ / ШАГОВЫЙ РЕФЛЕКС"}
check(len(main._variant_misses(seg)) == 1, "варианты через « / » — находка")
check(main._variant_misses({"source": "and/or 5 mg/kg", "target": "и/или 5 мг/кг"}) == [],
      "косая черта из оригинала — не находка")
check(main._variant_misses({"source": "A or B", "target": "А или Б"}) == [], "без черты — нет находки")
check(any(f["kind"] == "variants" for f in main._repair_findings(dict(seg, id=1))),
      "находка доезжает до ремонта (и разбора состава — тот же список)")
check(main._repair_scores(dict(seg, id=1)).get("variants") == 1, "счётчик приёмки ремонта")
check("variants" in main.REVIEW_FREE_KEYS and "variants" in main.REVIEW_VETO_LABELS,
      "ревизия сверяет варианты бесплатно и называет отказ")
sysp = main._repair_system(main.DOMAINS[0], "EN", "RU")
check("Never offer alternatives separated by a slash" in sysp, "правило «один перевод» в промпте ремонта")


print("=== П1. Разрыв строки слоя: надпись картинки в промежутке читается ===")
import pypdf
import pdfpages_worker as _pw
# Маркер «•» и хвост строки — слоем, между ними пусто (в картинке там текст).
# Разбор строк проверяется на готовой ГЕОМЕТРИИ, а не на самодельном PDF:
# pypdf до 6.18 отдаёт у второго куска такого файла координаты нулями
# (у боевых книг — нет: стр. 10 проекта 14 даёт тот же разрыв на 6.16 и 6.18).
geo_line = [100.0, 300.0, 5.5, 255.0, "", "sans", 150.0, None, False, None, [[103.0, 150.0]]]
plain = [40.0, 260.0, 5.5, 300.0, "", "sans", 40.0, None, False, None, None]
res_g = pdftext.clean([["• 1c, body weight loss", "Plain line of the same page without gaps"]],
                      [{"box": [0, 0, 400, 600], "lines": [geo_line, plain], "figs": [], "rects": [],
                        "rot": {}}])
slots_g = [sl for it in res_g["items"] if it[0] == "p" and it[2] for b in it[2] for sl in b["slots"]]
check(any(len(sl) > 10 and sl[10] == [[103.0, 150.0]] for sl in slots_g),
      "разрыв строки доезжает до места строки в карте (поле 10): %s" % [sl[10:] for sl in slots_g])
check(any(len(sl) > 10 and sl[10] is None for sl in slots_g), "строка без разрыва — поле пустое")

# Сверка со слоем: блок картинки на всю строку, слой — «•» и хвост; блок
# обрезается до куска на разрыве. Без разрыва в карте — прежнее «слой целиком».
import importers
from PIL import Image as _I
_buf = io.BytesIO(); _I.new("RGB", (400, 600), "white").save(_buf, format="PNG")
blob_p = importers.tag_figure(_buf.getvalue(), 0, [0.0, 0.0, 1.0, 1.0])
def _rec():
    # Строка на базовой 300 пт (лист 400×600, картинка 400×600 точек).
    return {"w": 400, "h": 600, "part": "pdfpage/0000.png",
            "blocks": [{"box": [101, 295, 260, 305], "rows": 1, "lineH": 10}]}
def _data(with_gaps):
    sl = [100.0, 300.0, 255.0, 5.5, "", None, 20, 0, None, None,
          [[103.0, 150.0]] if with_gaps else None]
    return {"layout": {"pages": [[0, 0, 400, 600]], "boxes": {"0": [{"page": 0, "slots": [sl]}]}}}
r1 = _rec(); main._mark_layer_blocks(r1, blob_p, _data(True))
b1 = r1["blocks"][0]
check(not b1.get("skip") and b1.get("trim") == "layer" and 103 <= b1["box"][0] and b1["box"][2] <= 150,
      "блок обрезан до куска на разрыве: %s" % b1)
r2 = _rec(); main._mark_layer_blocks(r2, blob_p, _data(False))
check(r2["blocks"][0].get("skip") == "layer", "без разрыва в карте — слой целиком, как прежде")
main.LAYER_GAPS = False
r3 = _rec(); main._mark_layer_blocks(r3, blob_p, _data(True))
main.LAYER_GAPS = True
check(r3["blocks"][0].get("skip") == "layer", "LAYER_GAPS=0 — прежняя сверка")
# Пересверка записи правила 2: только блоки на разрыве; без разрывов — ничего.
r4 = {"w": 400, "h": 600, "part": "pdfpage/0000.png", "layerRule": 2,
      "blocks": [{"box": [101, 295, 260, 305], "rows": 1, "skip": "layer"},
                 {"box": [10, 10, 90, 60], "rows": 4, "skip": "layer"}]}
check(main._relayer_todo(r4, _data(True)) == {0}, "правило 2 → 3: пересверяются только блоки на разрыве")
check(main._relayer_todo(r4, _data(False)) == set(), "карта без разрывов — пересверять нечего")

# Пороги разрыва: по точному концу куска — от 2.5 кегля, по оценке — от 4.
chunks_ = [("•", 100.0, 300.0, 5.0), ("text", 118.0, 300.0, 5.0)]
ends_ = {(100, 300): 103.0}
g_e = _pw._line_gaps([0, 1], chunks_, 5.0, 0.5, ends_)
g_n = _pw._line_gaps([0, 1], chunks_, 5.0, 0.5, {})
check(g_e and g_e[0][0] <= 103.0 and g_e[0][1] == 118.0 and g_n is None, "разрыв 3 кегля: по точному концу — да, по оценке — нет: %s / %s"
      % (g_e, g_n))
# Вырезанный на разрыве кусок — своим блоком, не склеиваясь с соседней строкой.
blk = main._split_uncovered({"conf": 1}, [[0, 0, 50, 10], [0, 12, 200, 22]], [False, False], 0, {0})
check(len(blk) == 2 and blk[0].get("gap") == 1 and not blk[1].get("gap"),
      "кусок на разрыве — отдельный блок с пометкой: %s" % [b_["box"] for b_ in blk])

print("=== П2. Повёрнутая таблица режется по столбцам, список и подпись — нет ===")
def _rg(cells, y0=100.0):
    return {"pts": [[50.0 + 0 * i, y0 + off, 90.0, 4.2, len(t), t] for i, (off, t) in enumerate(cells)],
            "end": [50.0, y0 + cells[-1][0] + 2.1 * len(cells[-1][1])], "curved": False}
rows = {str(k): _rg([(0, "Drug%d" % k), (40, "High"), (80, "Neutral"), (130, "•"), (133.5, "No dose")])
        for k in range(4)}
cols = pdftext._rot_columns(rows)
cells = pdftext._rot_cells("Drug0 High Neutral • No dose", rows["0"], cols)
check([c_[0].strip() for c_ in cells] == ["Drug0", "High", "Neutral", "• No dose"],
      "ряд таблицы — ячейки, маркер остаётся с текстом: %s" % [c_[0] for c_ in cells])
lone = {"0": _rg([(0, "Axis"), (30, "label")])}
check(len(pdftext._rot_cells("Axis label", lone["0"], pdftext._rot_columns(lone))) == 1,
      "одиночная повёрнутая подпись не режется")
lst = {str(k): _rg([(0, "•"), (3.5, "item %d" % k)]) for k in range(5)}
check(len(pdftext._rot_cells("• item 0", lst["0"], pdftext._rot_columns(lst))) == 1,
      "повёрнутый список с маркером не режется")

# Продолжение ячейки следующей повёрнутой строкой — в её же абзац.
row = _rg([(0, "Drug9"), (40, "High"), (80, "Neutral"), (130, "•"), (133.5, "No dose")])
cont = {"pts": [[57.0, 233.5, 90.0, 4.2, 8, "required"]], "end": [57.0, 250.0], "curved": False}
cr_ = pdftext._RotRun(); cr_.add("• No dose", {"pts": row["pts"][3:], "end": row["end"], "curved": False})
check(pdftext._rot_cell_host([cr_], cont) is cr_, "продолжение ячейки (по тексту после «•») — в ячейку")
far = {"pts": [[90.0, 233.5, 90.0, 4.2, 8, "other"]], "end": [90.0, 250.0], "curved": False}
check(pdftext._rot_cell_host([cr_], far) is None, "строка далеко поперёк пути — не продолжение")
nxt = {"pts": [[57.0, 233.5, 90.0, 4.2, 3, "Low"]], "end": [57.0, 240.0], "curved": False}
check(pdftext._rot_cell_host([cr_], nxt) is None, "значение следующего ряда (с заглавной) — не продолжение")

print("=== П3. Узкая ячейка растёт в свободную сторону ===")
from reportlab.pdfbase import pdfmetrics as _pm
fonts_ = layout_pdf._register_fonts(set("Эффективность"))
fnt = fonts_.get("") or layout_pdf.FONT_NAME
sl = {"x": 69.5, "x0": 69.5, "x1": 82.6, "y": 300.0, "size": 4.2, "page": 0, "style": "",
      "room0": 51.6, "_pw": 550.0}
lines_, f_, rest_, hs_ = layout_pdf._fit_slots("Эффективность", [sl], _pm.stringWidth,
                                               lambda s_: fnt, "left")
check(f_ >= 0.99 and sl.get("_span") == (51.6, 82.6), "кегль не падает, место — обе стороны: f=%s %s"
      % (f_, sl.get("_span")))
w_ = _pm.stringWidth("Эффективность", fnt, 4.2) * hs_
x_ = layout_pdf._span_x(sl, w_, sl["x"])
check(51.6 - 1e-6 <= x_ and x_ + w_ <= 82.6 + 1e-6, "строка в пределах свободной бумаги: %.1f..%.1f" % (x_, x_ + w_))
sl2 = {"x": 69.5, "x0": 69.5, "x1": 82.6, "y": 300.0, "size": 4.2, "page": 0, "style": "", "_pw": 550.0}
lines2, f2, _r2, _h2 = layout_pdf._fit_slots("Эффективность", [sl2], _pm.stringWidth, lambda s_: fnt, "left")
check(f2 < 0.99 and not sl2.get("_span"), "без свободной бумаги — прежнее ужатие")

print("=== П4. Надпись под краем кольца схемы — буквы найдены ===")
import numpy as np
import text_paint as tp
from PIL import ImageDraw as _D
from PIL import ImageFont as _F
_font = _F.truetype(os.path.join("frontend", "vendor", "fonts", "sub", "NotoSans-Bold.ttf"), 64)
ring = _I.new("RGB", (560, 180), "white"); dr = _D.Draw(ring)
# Край розового кольца схемы дугой вдоль верхнего края вырезки, под ним надпись.
dr.ellipse([-120, -744, 680, 56], outline=(233, 84, 98), width=40)
dr.text((16, 48), "STRENGTHENING", fill=(0, 0, 0), font=_font)
ring = np.asarray(ring.resize((140, 45), _I.LANCZOS))
check(tp.measure(ring, "STRENGTHENING", 1, 0.0)["found"], "край кольца у вырезки не делает фон «пёстрым»")
tp.TEXTURE_BIG_SHARE = 0
off_ring = tp.measure(ring, "STRENGTHENING", 1, 0.0)["found"]
tp.TEXTURE_BIG_SHARE = 2.5
check(not off_ring, "без правила (PAINT_TEXTURE_BIG=0) та же вырезка отбраковывалась — страж")
# Как зовёт печать: с рамкой надписи (`inner`) и высотой строки — кольцо
# выходит за рамку надписи, значит пришло снаружи.
check(tp.measure(ring, "STRENGTHENING", 1, 35.0, inner=(5.0, 5.0, 134.0, 40.0))["found"],
      "с рамкой надписи — то же: кольцо снаружи рамки в замер фона не идёт")
photo = _I.new("RGB", (200, 60), (230, 230, 230)); _D.Draw(photo).ellipse([60, 5, 140, 55], fill=(150, 60, 60))
_D.Draw(photo).text((20, 24), "LABEL OVER", fill=(0, 0, 0))
photo = (np.asarray(photo).astype(int) + np.random.default_rng(2).normal(0, 30, (60, 200, 3))).clip(0, 255).astype("uint8")
check(not tp.measure(photo, "LABEL OVER", 1, 20.0, inner=(4, 4, 196, 56))["found"],
      "фотография с предметом ВНУТРИ рамки надписи — по-прежнему отказ")
rng = np.random.default_rng(1)
noise = _I.fromarray(rng.normal(128, 40, (60, 200, 3)).clip(0, 255).astype("uint8"))
_D.Draw(noise).text((20, 20), "NOISY", fill=(0, 0, 0))
check(not tp.measure(np.asarray(noise), "NOISY", 1, 0.0)["found"], "шумная фотография — по-прежнему отказ")

print("=== П5. Капс — свой класс кегля ===")
check(layout_pdf._caps_text("ДИНАМИЧЕСКОЕ НАБЛЮДЕНИЕ") and not layout_pdf._caps_text("Почка")
      and not layout_pdf._caps_text("ССЗ"), "заголовок капсом — свой стиль; сокращение — нет")

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
