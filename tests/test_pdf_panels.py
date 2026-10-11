# -*- coding: utf-8 -*-
"""«Лента» сканер-приложения → обычные страницы (backend/pdf_panels.py),
таблицы на поставленной прямо странице (pdftext._table_streams), проверка
наложений и общий кегль в выгрузке (layout_pdf._resolve_collisions,
_harmonize). Разбор правил — docs/rules/pdf-reading.md, «Лента»."""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, HERE)
os.environ.setdefault("PDF_PANELS_INPROC", "1")    # без дочернего процесса — быстрее

import pdf_panels                                     # noqa: E402
import pdftext                                        # noqa: E402
from collections import Counter                       # noqa: E402
from pdf_fixture import make_pdf                      # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ─── Синтетическая лента ─────────────────────────────────────────────
# Два листа 300×1300. Страницы 280×400 с шагом 410 (зазор 10), как у
# CamScanner: на листе 0 — три полные и неполная внизу (60 пт), на листе 1
# — продолжение той же страницы вверху (340 пт) и две полные.
W, H = 300, 1300
PW, PH = 280, 400


def panel(y, n, rotated=False):
    ops = "q 10 %g %d %d re W n 1 1 1 rg 10 %g %d %d re f 0 0 0 rg " % (y, PW, PH, y, PW, PH)
    if rotated:
        # Страница журнала боком: строки идут снизу вверх.
        for k in range(6):
            ops += ("BT /F1 9 Tf 0 1 -1 0 %g %g Tm {HEX:Rotated table row %d of page %d:HEX} Tj ET "
                    % (40 + 14 * k, y + 30, k, n))
    else:
        for k in range(5):
            ops += ("BT /F1 10 Tf 1 0 0 1 30 %g Tm {HEX:Page %d line %d text:HEX} Tj ET "
                    % (y + PH - 30 - 14 * k, n, k))
    return ("raw", ops + "Q")


def ribbon_pdf():
    s0 = [("raw", "q 0 0 %d %d re W n 1 1 1 rg 0 0 %d %d re f Q" % (W, H, W, H)),
          panel(890, 1), panel(480, 2, rotated=True), panel(70, 3),
          ("raw", "q 10 0 %d 60 re W n BT /F1 10 Tf 1 0 0 1 30 30 Tm {HEX:Page 4 top part:HEX} Tj ET Q" % PW)]
    s1 = [("raw", "q 10 960 %d 340 re W n BT /F1 10 Tf 1 0 0 1 30 1200 Tm {HEX:Page 4 bottom part:HEX} Tj ET Q" % PW),
          panel(550, 5), panel(140, 6)]
    return make_pdf([s0, s1], size=(W, H))


print("== Лента: поиск страниц")
data = ribbon_pdf()
from pypdf import PdfReader                           # noqa: E402
plan = pdf_panels.detect(PdfReader(io.BytesIO(data)))
check(plan is not None, "лента найдена")
check(plan and len(plan["pages"]) == 6, "страниц шесть: %s" % (plan and len(plan["pages"])))
st = plan and [p for p in plan["pages"] if len(p["pieces"]) == 2]
check(st and len(st) == 1 and abs(st[0]["h"] - PH) < 0.5,
      "страница, разрезанная между листами, — одна, из двух кусков: %s" % st)
if st:
    a, b = st[0]["pieces"]
    check(a["src"] == 0 and b["src"] == 1 and abs(a["dy"] - 340) < 0.5 and b["dy"] == 0,
          "верхний кусок — низ листа 0 сверху страницы, нижний — верх листа 1: %s" % st[0]["pieces"])

print("== Лента: сборка, повороты, текст каждой страницы — свой")
res = pdf_panels.virtualize(data)
check(res is not None, "виртуальный PDF собран")
vpdf, vplan = res
r = PdfReader(io.BytesIO(vpdf))
check(len(r.pages) == 6, "в нём шесть страниц")
check(vplan["pages"][1]["rot"] in (90, 270), "страница, лежавшая боком, поставлена прямо: rot=%s"
      % vplan["pages"][1]["rot"])
w1, h1 = float(r.pages[1].mediabox.width), float(r.pages[1].mediabox.height)
check(abs(w1 - PH) < 0.5 and abs(h1 - PW) < 0.5, "у неё ширина и высота поменялись местами: %sx%s" % (w1, h1))
t0 = r.pages[0].extract_text() or ""
check("Page 1 line 0" in t0 and "Page 2" not in t0 and "Page 3" not in t0,
      "на первой странице только её текст: %r" % t0[:80])
t3 = r.pages[3].extract_text() or ""
check("top part" in t3 and "bottom part" in t3, "страница из двух кусков несёт текст обоих: %r" % t3)
check(not vplan.get("whole"), "фильтр содержимого прошёл самопроверку на всех страницах: %s" % vplan.get("whole"))

print("== Лента: пересборка по плану и обратно в листы")
again = pdf_panels.compose_plan(data, vplan)
r2 = PdfReader(io.BytesIO(again))
check(len(r2.pages) == 6 and (r2.pages[0].extract_text() or "") == t0,
      "по готовому плану собирается то же самое")
back = pdf_panels.unsplit(vpdf, vplan)
rb = PdfReader(io.BytesIO(back))
check(len(rb.pages) == 2 and abs(float(rb.pages[0].mediabox.height) - H) < 0.5,
      "«как в файле» — снова два листа исходного размера")
try:
    import pypdfium2 as pdfium
    from PIL import ImageChops
    a_ = pdfium.PdfDocument(data)[0].render(scale=0.5).to_pil().convert("L")
    b_ = pdfium.PdfDocument(back)[0].render(scale=0.5).to_pil().convert("L")
    diff = ImageChops.difference(a_, b_).histogram()
    check(sum(diff[64:]) < 0.002 * a_.size[0] * a_.size[1],
          "обратная сборка рисуется как оригинал (разных точек %d)" % sum(diff[64:]))
except ImportError:
    print("  пропущено (нет pypdfium2)")

print("== Обычный PDF не трогается")
from pdf_fixture import body, folio                    # noqa: E402
plain = make_pdf([[("t", 40, 500, 10, "Обычная страница книги")] + folio(1)])
check(pdf_panels.virtualize(plain) is None, "книга без ленты — None")
# Три клипа во всю ширину на ОДНОЙ странице (шапка, тело, подвал Word/Chrome)
# — не лента: страница не выше двух страниц.
hdr = make_pdf([[("raw", "q 10 500 280 90 re W n BT /F1 10 Tf 1 0 0 1 20 550 Tm {HEX:Head:HEX} Tj ET Q"),
                 ("raw", "q 10 100 280 390 re W n BT /F1 10 Tf 1 0 0 1 20 300 Tm {HEX:Body:HEX} Tj ET Q"),
                 ("raw", "q 10 10 280 80 re W n BT /F1 10 Tf 1 0 0 1 20 50 Tm {HEX:Foot:HEX} Tj ET Q")]])
check(pdf_panels.detect(PdfReader(io.BytesIO(hdr))) is None, "шапка/тело/подвал одной страницы — не лента")

print("== Разбор содержимого: строки и встроенные картинки")
g = pdf_panels.groups(b"q 1 1 5 5 re W n (a \\) Q ( b) Q) Tj Q q BI /W 1 /H 1 ID \x00Q\x00 EI Q")
check(g is not None and len(g) == 2 and g[0][2] == (1.0, 1.0, 6.0, 6.0),
      "Q внутри строки и внутри картинки — не оператор: %s" % g)
check(pdf_panels.groups(b"q q Q") is None, "несбалансированные q/Q — «не знаем»")
g = pdf_panels.groups(b"q 10 10 m 50 10 l 50 40 l h W n 0 0 1 rg 0 0 100 100 re f Q")
check(g and g[0][2] == (10.0, 10.0, 50.0, 40.0), "клип контуром — рамка по точкам: %s" % ((g and g[0][2]),))

print("== Таблица на странице: колонка за колонкой")


def rec(t, x0, y, w, s=4.0, li=0):
    return {"t": t, "x0": x0, "x1": x0 + w, "y": y, "s": s, "li": li}


cols_x = [20, 80, 140, 200, 260]
recs = []
li = 0
for row, y in enumerate((300, 270, 240)):
    for k, x in enumerate(cols_x):
        recs.append(rec("r%dc%d" % (row, k), x, y, 30, li=li))
    li += 1
    recs.append(rec("r%dc4 more" % row, 260, y - 6, 30, li=li))     # вторая строка длинной ячейки
    li += 1
rep = Counter()
out = pdftext._table_streams(recs, rep)
check(out is not None and rep["tables"] == 1, "таблица найдена")
if out:
    ts = [r["t"] for r in out]
    check(ts.index("r0c4 more") == ts.index("r0c4") + 1,
          "вторая строка ячейки идёт сразу за первой: %s" % ts[-6:])
    check(out[0]["tcol"][1] == 0 and out[-1]["tcol"][1] == len(cols_x) - 1,
          "сперва первая колонка, в конце — последняя")
three = [rec("col %d line %d with words" % (k, n), 20 + 130 * k, 400 - 10 * n, 120, li=n * 3 + k)
         for n in range(6) for k in range(3)]
check(pdftext._table_streams(three, Counter()) is None, "три колонки текста — не таблица")

print("== Выгрузка: наложения и общий кегль")
import layout_pdf                                      # noqa: E402
ok, why = layout_pdf.available()
if not ok:
    print("  пропущено:", why)
else:
    # Две строки подряд: первая получает длинный перевод, вторая остаётся
    # оригиналом. Хвост первой не вправе лечь на вторую.
    page = [("t", 40, 500, 10, "Short line"), ("t", 40, 488, 10, "Second paragraph stays")]
    src = make_pdf([page], size=(300, 600))
    lay = {"boxes": {
        "0": [{"page": 0, "x0": 40, "x1": 95, "top": 508.5, "bottom": 497.5, "size": 10, "lead": 12,
               "style": "", "fam": "sans", "indent": 0, "lines": 1,
               "slots": [[40, 500, 95, 10, "", 40, 10, 1, None, [0, 0, 0]]]}],
        "1": [{"page": 0, "x0": 40, "x1": 150, "top": 496.5, "bottom": 485.5, "size": 10, "lead": 12,
               "style": "", "fam": "sans", "indent": 0, "lines": 1,
               "slots": [[40, 488, 150, 10, "", 40, 22, 1, None, [0, 0, 0]]]}]}}
    long = "Очень длинный перевод короткой строки, который никак не помещается в своё место на листе"
    pdf, stats = layout_pdf.build(src, lay, {0: long})
    check("collisions" in stats and "collisionFixed" in stats, "сборка отчитывается о наложениях: %s"
          % {k: stats.get(k) for k in ("collisions", "collisionFixed", "collisionPages")})
    check(stats.get("collisionFixed", 0) >= 1, "наложение на оставленный оригинал найдено и чинилось")
    # Три подписи одного стиля: одна длинная — кегль у всех один (или
    # длинная названа выбросом).
    page = [("t", 40, 500 - 40 * k, 8, "Label %d" % k) for k in range(3)]
    src = make_pdf([page], size=(300, 600))
    boxes = {}
    for k in range(3):
        y = 500 - 40 * k
        boxes[str(k)] = [{"page": 0, "x0": 40, "x1": 70, "top": y + 7, "bottom": y - 2, "size": 8,
                          "lead": 9.6, "style": "", "fam": "sans", "indent": 0, "lines": 1,
                          "slots": [[40, y, 70, 8, "", 40, 7, 1, None, [0, 0, 0]]]}]
    texts = {0: "Метка", 1: "Метка два", 2: "Совсем длинная метка номер три"}
    pdf, stats = layout_pdf.build(src, {"boxes": boxes}, texts)
    check(stats.get("harmonized", 0) + stats.get("harmonyOutliers", 0) >= 1,
          "надписи одного стиля сведены к общему кеглю: %s"
          % {k: stats.get(k) for k in ("harmonized", "harmonyOutliers", "grown")})

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    for f in FAILS:
        print(" -", f)
    sys.exit(1)
print("ALL OK")
