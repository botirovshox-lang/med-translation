# -*- coding: utf-8 -*-
"""Раздел Ы и правила Ш45–Ш50 (23.10.2026): «проверил — переверстал».

    python tests/test_layout_loop.py

Ш45 линия таблицы в поле заплатки не закрашивается, вертикаль ячейки
останавливает конец строки, промежуток между белыми буквами на плашке —
не линия; Ш46 точки «Ё» над строкой стираются; Ш47 одиночная строка,
прижатая вправо, растёт влево; Ш48 перевод справа налево — общим правым
краем; Ш49 подпись поля бланка — ряд, а не история; Ш50 буквица стирается
и печатается первой буквой перевода; Ы — новые коды приёмки без ложных
тревог, петля детерминирована и принимает только лучшее, подсказки модели
привязаны к тексту места; Ш45 у картинок — рамка и печать возвращаются.
Переводы — настоящие (`tests/fixtures/corpus_real_translations.json`),
сборка и приёмка — `tools/corpus_offline.py`, без сети и без модели."""
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "tools")
sys.path.insert(0, "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)[:300]))
    if not ok:
        FAILS.append(name)


try:
    import numpy as np
    import reportlab  # noqa: F401
    import pypdfium2  # noqa: F401
    from PIL import Image, ImageDraw
except ImportError as e:            # pragma: no cover
    print("ПРОПУЩЕН: нет модуля (%s)" % e)
    sys.exit(0)

import corpus_build as C  # noqa: E402
import export_qa  # noqa: E402
import image_text  # noqa: E402
import layout_pdf as L  # noqa: E402
import main  # noqa: E402

print("=== Ш47: строка, прижатая вправо, — «вправо» ===")
tot = {"x": 378.2, "x1": 545.3, "size": 11.0, "y": 540.0, "page": 0}
cells = [{"x": 505.6, "x1": 541.3, "size": 9.0, "y": 630.0 - 20 * k, "page": 0} for k in range(4)]
left = [{"x": 54.0, "x1": 160.0, "size": 9.0, "y": 630.0 - 20 * k, "page": 0} for k in range(4)]
sls = [tot] + cells + left
L._mark_column_edges(sls)
L._mark_right_edges(sls)
check("сумма под таблицей — правый край", tot.get("_rightEdge"), tot)
check("одна строка с правым краем — «right»", L._slot_align([tot]) == "right")
check("левая колонка — не правый край", not any(s.get("_rightEdge") for s in left))
sp = dict(tot, x0=378.2, _span=(300.0, 560.0))
check("свободная бумага: выключка вправо держит правый край",
      abs(L._span_x(sp, 200.0, 545.3 - 200.0, "right") - (545.3 - 200.0)) < 0.01)


def sample_of(arr, cb=(0.0, 0.0, 300.0, 200.0), scale=2.0):
    im = Image.fromarray(arr)
    return (im, scale, cb, im.convert("L"))


print("=== Ш46: точки «Ё» над строкой ===")
a = np.full((400, 600, 3), 255, np.uint8)
# строка: базовая линия y=100 пт, кегль 20 → рамка до 117 пт; точки — на 120 пт
H = 400
row = lambda ypt: int(H - ypt * 2)
a[row(115):row(100), 40:400] = 0                      # буквы
a[row(122):row(119), 100:106] = 0                     # точки
a[row(122):row(119), 112:118] = 0
sd = {"x0": 20.0, "x1": 200.0, "top": 100 + 0.85 * 20, "size": 20.0, "y": 100.0}
mu = L._marks_above(sample_of(a), sd, 1.0)
check("знаки над рамкой — поле закраски вверх", mu > 2.0, mu)
b = a.copy()
b[row(140):row(125), 40:400] = 0                      # строка выше вплотную
check("над «знаками» строка выше — не трогаем", L._marks_above(sample_of(b), sd, 1.0) == 0.0)

print("=== Ш45: линия в поле заплатки ===")


class Cv:
    def __init__(self):
        self.rects = []

    def setFillColorRGB(self, *a):
        pass

    def rect(self, x, y, w, h, stroke=0, fill=1):
        self.rects.append((x, y, w, h))


box = {"x0": 50.0, "x1": 150.0, "top": 120.0, "bottom": 97.0,
       "_rules": [(40.0, 95.8, 160.0, 95.8, 0.5, (0, 0, 0)), (152.0, 90.0, 152.0, 130.0, 0.5, (0, 0, 0))]}
cv = Cv()
L._fill_box(cv, box, 3.0, [(1, 1, 1)])
y0 = min(r[1] for r in cv.rects)
x1 = max(r[0] + r[2] for r in cv.rects)
check("заплатка кончается над линейкой под строкой", y0 >= 95.8 + 0.25, y0)
check("и перед вертикалью ячейки справа", x1 <= 152.0 - 0.25, x1)
check("обойдённые линии штрихом не возвращаются", box.get("_rulesLeft") == [])
dark = np.zeros((20, 30), bool)
dark[:, :] = True
dark[:, 10:12] = True
check("тёмный столбец на тёмной полосе — не линия",
      not L._thin_outside(dark, 5, 15, 10, 12, True))
dark2 = np.zeros((20, 30), bool)
dark2[:, 10:12] = True
check("тонкая линия на бумаге — линия", L._thin_outside(dark2, 5, 15, 10, 12, True))

print("=== Ш49: черта поля бланка справа ===")
f = np.full((400, 600, 3), 255, np.uint8)
f[row(104):row(100), 40:200] = 0                       # подпись
f[row(99):row(98), 260:590] = 0                        # черта поля на базовой линии
sdf = {"x0": 20.0, "x1": 100.0, "size": 10.0, "y": 100.0}
check("черта поля найдена", L._field_rule(sample_of(f), sdf, 1.0))
check("без черты — нет", not L._field_rule(sample_of(np.full((400, 600, 3), 255, np.uint8)), sdf, 1.0))
check("строка с чертой — ряд, не история", L._row_anchor({"_fieldRule": True, "size": 10.0}, {}))

print("=== Ш50: место буквицы по отступу ===")
b0 = {"size": 10.0, "slots": [[60.0, 700.0, 200.0, 10.0], [60.0, 688.0, 200.0, 10.0],
                              [30.0, 676.0, 200.0, 10.0]]}
pl = L._dropcap_place(b0)
check("буквица — отступ двух первых строк", pl and pl[0] == 30.0 and pl[2] < 60.0, pl)
check("без отступа — нет", L._dropcap_place({"slots": [[30, 700, 200, 10], [30, 688, 200, 10]]}) is None)

print("=== Ы: петля — правки места ===")
rep = {"issues": [{"code": "SMALL", "key": "p1"}, {"code": "SPILL", "near": "p2"},
                  {"code": "OVERPRINT", "near": "p2"}]}
t1 = main._loop_tune(rep, {})
check("SMALL → «шире», SPILL → «теснее»", t1 == {"p1": {"wide": 1}, "p2": {"tight": 1}}, t1)
t2 = main._loop_tune(rep, t1)
check("вторая попытка — «отдельно», «шире» после «теснее» не назначается",
      t2["p2"] == {"tight": 1, "solo": 1} and "wide" not in t2["p2"], t2)
check("оценка: невлезшие слова сборки — тяжёлые",
      main._loop_score({"issues": []}, {"overflow": 2}) == (2, 0))

print("=== Ы3: подсказки модели — к тексту места ===")
td = Path(tempfile.mkdtemp(prefix="tune_"))
main.SOURCE_DIR = td
inp = {"texts": {3: "Итого к оплате"}, "extra": [], "work": b"", "layout": {}}
n = main._tune_hints_save(77, inp, {"issues": [{"code": "OVERFLOW", "real": True, "page": 0,
                                                "key": "p3"}]})
check("подсказка записана", n == 1)
check("текст тот же — подсказка действует",
      main._tune_hints(77, {3: "Итого к оплате"}, []) == {"p3": {"tight": 1}})
check("текст поменялся — подсказка снята", main._tune_hints(77, {3: "Иное"}, []) == {})

print("=== Ш45 у картинок: рамка и кольцо печати возвращаются ===")
img = Image.new("RGB", (400, 200), (250, 250, 245))
d = ImageDraw.Draw(img)
d.rectangle((10, 10, 390, 190), outline=(200, 20, 20), width=4)        # рамка листа
d.ellipse((220, 60, 330, 170), outline=(200, 20, 20), width=3)          # печать
big = img.copy()
orig = img.copy()
ImageDraw.Draw(big).rectangle((180, 80, 395, 150), fill=(250, 250, 245))  # заплатка задела всё
n_back = image_text._restore_structures(big, orig, [((180, 80, 395, 150), [(200, 100, 300, 130)], 20.0)])
arr_b, arr_o = np.asarray(big).astype(int), np.asarray(orig).astype(int)
check("возвращено", n_back > 0, n_back)
check("рамка справа на месте", np.abs(arr_b[90:140, 386:390] - arr_o[90:140, 386:390]).max() < 10)
check("кольцо вне строки на месте",
      np.abs(arr_b[140:150, 240:310] - arr_o[140:150, 240:310]).max() < 10)

print("=== Ы: приёмка — новые коды на синтетике ===")


def pdf_page(draw):
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 200))
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def base(c):
    c.setFont("Helvetica", 12)
    c.drawString(40, 120, "Hello table cell")
    c.setLineWidth(1)
    c.line(30, 110, 270, 110)


def cut(c):
    base(c)
    c.setFillColorRGB(1, 1, 1)
    c.rect(35, 106, 120, 30, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(40, 120, "Privet")


o_pdf, x_pdf = pdf_page(base), pdf_page(cut)
lay = {"boxes": {"0": [{"page": 0, "x0": 40.0, "x1": 140.0, "top": 130.0, "bottom": 116.0,
                        "size": 12.0, "slots": [[40.0, 120.0, 140.0, 12.0]]}]}}
r = export_qa.inspect_pdf(o_pdf, x_pdf, lay, {0: "Privet"}, [], None, time_budget=1e9)
check("перерезанная линия — RULE_CUT", (r.get("counts") or {}).get("RULE_CUT"), r.get("counts"))
r2 = export_qa.inspect_pdf(o_pdf, o_pdf, lay, {0: "Privet"}, [], None, time_budget=1e9)
check("без правки — RULE_CUT нет", not (r2.get("counts") or {}).get("RULE_CUT"), r2.get("counts"))

print("=== сквозная выгрузка: настоящие переводы ===")
FIX = json.loads(Path("tests/fixtures/corpus_real_translations.json").read_text(encoding="utf-8"))
RECIPE = {"L04_infographic_ar": C.pdf_infographic, "L03_invoice_kk": C.pdf_invoice,
          "L31_de_notice_ru": C.pdf_de_notice, "07_form": C.pdf_form, "01_newspaper": C.pdf_newspaper,
          "10_en_guide_zh": C.pdf_en_guide}
TMP = Path(tempfile.mkdtemp(prefix="loop_"))
CORP, OUT, REAL = TMP / "c", TMP / "o", TMP / "r"
for dd in (CORP, OUT, REAL):
    dd.mkdir()
man = [m for m in FIX["_manifest"] if m["id"] in RECIPE]
for m in man:
    random.seed(m["id"][:3].lstrip("L"))
    RECIPE[m["id"]](CORP / m["file"])
    (REAL / m["id"]).mkdir()
    (REAL / m["id"] / "segments.json").write_text(json.dumps(FIX[m["id"]], ensure_ascii=False),
                                                   encoding="utf-8")
(CORP / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
p = subprocess.run([sys.executable, "tools/corpus_offline.py", str(CORP), str(OUT), "--real", str(REAL),
                    "--no-detect"], capture_output=True, text=True, encoding="utf-8",
                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
summ = {x["id"]: x for x in json.loads((OUT / "summary.json").read_text(encoding="utf-8"))}
bad = lambda c: {k: v for k, v in c.items() if export_qa.SEVERITY.get(k, 1) >= 2 and k != "SMALL"}
check("арабский: приёмка чистая (Ш48, без ложных линий на плашке)",
      not bad(summ["L04_infographic_ar"]["counts"]), summ["L04_infographic_ar"]["counts"])
check("бланк: подписи полей на своих местах (Ш49) — нет OVERFLOW и BLANK",
      not {"OVERFLOW", "BLANK"} & set(summ["07_form"]["counts"]), summ["07_form"]["counts"])
check("газета: буквица и рост в бумагу — без OVERFLOW", not summ["01_newspaper"]["counts"].get("OVERFLOW"),
      summ["01_newspaper"]["counts"])
check("немецкое уведомление: подпись справа не за полем", not bad(summ["L31_de_notice_ru"]["counts"]),
      summ["L31_de_notice_ru"]["counts"])
kk = summ["L03_invoice_kk"]["counts"]
check("счёт KK: без SPILL/OVERPRINT/GHOST", not {"SPILL", "OVERPRINT", "GHOST"} & set(kk), kk)
check("петля отчитывается у каждого файла", all("loop" in summ[k] for k in summ))
import pypdfium2 as P  # noqa: E402
doc = P.PdfDocument(str(OUT / "L03_invoice_kk.pdf"))
g = np.asarray(doc[0].render(scale=2).to_pil().convert("L")).astype(int)
doc.close()
rows = [y for y in range(g.shape[0]) if (g[y, 100:640] < 120).mean() > 0.9]
check("счёт KK: линейки таблицы целые (Ш45)", len(rows) >= 6, rows)

print("=== детерминизм: две сборки — одни решения ===")
p2 = subprocess.run([sys.executable, "tools/corpus_offline.py", str(CORP), str(TMP / "o2"), "--real",
                     str(REAL), "--no-detect", "--only", "L03_invoice_kk"], capture_output=True,
                    text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
s2 = {x["id"]: x for x in json.loads((TMP / "o2" / "summary.json").read_text(encoding="utf-8"))}
check("та же приёмка и тот же итог петли", s2["L03_invoice_kk"]["counts"] == kk
      and (s2["L03_invoice_kk"].get("loop") or {}).get("after") == (summ["L03_invoice_kk"].get("loop") or {}).get("after"))

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f_ in FAILS:
        print("  - " + f_)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
