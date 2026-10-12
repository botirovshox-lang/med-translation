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
P = [("t", 145, 343.0, 4.3, "HEALTHY LIFESTYLE"), ("t", 204, 343.0, 4.3, "DIABETES SELF-"),
     ("t", 255, 343.0, 4.3, "ADDRESS SOCIAL DETERMINANTS"),
     ("t", 153, 337.8, 4.3, "BEHAVIORS"), ("t", 195, 337.8, 4.3, "MANAGEMENT EDUCATION"),
     ("t", 267, 337.8, 4.3, "OF HEALTH (SDOH)")]
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
pdftext.LABEL_JOIN = False
off = [it[1] for it in pdftext.clean(pg, geom=gm)["items"] if it[0] == "p"]
pdftext.LABEL_JOIN = True
check("HEALTHY LIFESTYLE BEHAVIORS" not in off, "PDF_LABEL_JOIN=0 выключает склейку")

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

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
