# -*- coding: utf-8 -*-
"""Правила Т34–Т36 (разбор первой выгрузки статьи «Бюллетень сибирской
медицины», проект 105, 18.10.2026):

  Т34  линии таблицы, нарисованные обводкой (`m`/`l` + `S`), — границы:
       вертикальная режет строку по ячейкам (в том числе внутри ОДНОГО куска
       pypdf — по операторам показа текста), горизонтальная обрывает абзац
       (`pdfpages_worker._rules_of/_split_at_rules/_h_groups`,
       `pdftext._rule_parts`);
  Т35  на странице с расчерченной таблицей начала колонок (`_col_starts`)
       режут только строки внутри неё (`pdfpages_worker._in_ruled`);
  Т36  строка, начатая ключом легенды (сплошной квадрат), — подпись серии,
       к надписи выше не приклеивается (`image_text.legend_key`,
       `group_blocks`, `split_plan`, `main._split_keyed`).
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pdfpages_worker as pw
import pdftext
import textcount
import image_text
from pdf_fixture import make_pdf

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def chunk(text, x, y, size=8.5):
    return (text, x, y, size, False, "", "", False, 0, None, 0.0, size, None)


# ─── Т34. Линии листа ────────────────────────────────────────────────
print("=== Т34. Обведённые отрезки и полоски — линии листа ===")
v, h = [], []
pw._rules_of([((100.0, 400.0), (100.0, 430.0)), ((50.0, 430.0), (300.0, 430.0)),
              ((10.0, 10.0), (12.0, 12.0))], [[200.0, 380.0, 200.8, 420.0]], v, h)
check(len(v) == 2 and len(h) == 1, "вертикальный отрезок и тонкая полоска — вертикали, горизонталь — горизонталь")
check(not any(r[0] == 10.0 for r in v + h), "короткий косой отрезок линией не считается")

print("=== Т34. Линии таблицы — только сетка ===")
grid_v = [[118.0, 486.0, 118.0, 514.0], [165.0, 486.0, 165.0, 514.0]]
grid_h = [[55.0, 514.0, 290.0, 514.0], [55.0, 486.0, 290.0, 486.0]]
vs, hs = pw._grid_rules(grid_v + [[300.0, 400.0, 300.0, 420.0]], grid_h + [[320.0, 300.0, 380.0, 300.0]])
check(len(vs) == 2 and len(hs) == 2, "вертикали, упёртые в линии рядов, — сетка; одиночная стрелка и черта — нет")
check(pw._grid_rules(grid_v[:1], grid_h) == ([], []), "одна вертикаль (ни одной закрытой ячейки) — не таблица")
v, h = [], []
pw._rules_of([], [[150.0, 245.0 + 0.15 * k, 270.0, 245.12 + 0.15 * k] for k in range(20)], v, h)
check(not h, "полоски градиентной заливки по 0.1 пт линиями не считаются")

print("=== Т34. Линия между кусками строки режет её по ячейкам ===")
vr = [[118.0, 488.0, 118.0, 512.0]]
near = [chunk("SNP (ген) ", 60.0, 500.0), chunk("БА, ", 110.0, 499.0)]   # зазор ≈ 12 пт < трёх кеглей
g = pw._h_groups([0, 1], near, 0.5, (), None, [[105.0, 488.0, 105.0, 512.0]])
check(len(g) == 2, "«SNP (ген)» | «БА,» — две ячейки при зазоре меньше трёх кеглей")
g = pw._h_groups([0, 1], near, 0.5, (), None, ())
check(len(g) == 1, "без линии — как прежде, одна надпись")
g = pw._h_groups([0, 1], [chunk("тип ", 60.0, 495.0), chunk("БА, ", 125.0, 500.0)], 0.5, (), None, vr)
check(len(g) == 2, "ячейка на другой базовой линии с коротким словом — всё равно своя")

print("=== Т34. Один кусок pypdf режется по операторам у линии ===")
ops = [(60.0, 500.0, 0.0, 8.5, 8, None), (125.0, 504.0, 0.0, 8.5, 5, None)]
out = pw._split_at_rules([chunk("SNP (ген) Гено- \n", 60.0, 500.0)], ops, vr)
check([c[0] for c in out] == ["SNP (ген) ", "Гено- \n"], "кусок «SNP (ген) Гено- » делится по линии: %r" % [c[0] for c in out])
check(out[1][1] == 125.0 and out[1][2] == 504.0, "вторая половина — в точке своего оператора")
check("".join(c[0] for c in out) == "SNP (ген) Гено- \n", "текст строки не меняется")
out = pw._split_at_rules([chunk("SNP (ген) Гено- \n", 60.0, 500.0)], ops[:1], vr)
check(len(out) == 1, "знаки операторов не сошлись с куском — не режем")

print("=== Т34. Горизонтальная линия между строками обрывает абзац ===")
hr = [[50.0, 486.0, 300.0, 486.0]]
check(pdftext._rule_parts(hr, 60, 495, 110, 8.5, 60, 478, 110, 8.5), "линия ряда между строками — граница")
check(not pdftext._rule_parts([[50.0, 493.5, 300.0, 493.5]], 60, 495, 110, 8.5, 60, 478, 110, 8.5),
      "подчёркивание под самой строкой — не граница")
check(not pdftext._rule_parts([[200.0, 486.0, 300.0, 486.0]], 60, 495, 110, 8.5, 60, 478, 110, 8.5),
      "линия соседней колонки строки не разделяет")

print("=== Т34. Расчерченная шапка таблицы в синтетическом PDF ===")
cells = ("BT /F1 8 Tf 1 0 0 1 60 500 Tm {HEX:SNP (ген):HEX} Tj 1 0 0 1 124 504 Tm {HEX:Гено-:HEX} Tj "
         "1 0 0 1 124 494 Tm {HEX:тип:HEX} Tj 1 0 0 1 170 499 Tm {HEX:БА, n, %:HEX} Tj "
         "1 0 0 1 232 504 Tm {HEX:Контроль,:HEX} Tj 1 0 0 1 236 494 Tm {HEX:n, %:HEX} Tj ET\n"
         "BT /F1 8 Tf 1 0 0 1 60 476 Tm {HEX:rs10905277:HEX} Tj 1 0 0 1 128 476 Tm {HEX:AA:HEX} Tj "
         "1 0 0 1 172 476 Tm {HEX:23 (29,8):HEX} Tj 1 0 0 1 234 476 Tm {HEX:33 (28,2):HEX} Tj ET")
lines = ["0.5 w"]
for x in (55, 118, 165, 226, 290):
    lines.append("q 1 0 0 1 %d 486 cm 0 0 m 0 28 l S Q" % x)
    lines.append("q 1 0 0 1 %d 466 cm 0 0 m 0 20 l S Q" % x)
for y in (514, 486, 466):
    lines.append("q 1 0 0 1 55 %d cm 0 0 m 235 0 l S Q" % y)
pdf = make_pdf([[("raw", cells), ("raw", "\n".join(lines)),
                 ("t", 40, 560, 10, "Таблица 1 ниже.")]])
pages, geoms = textcount._pdf_pages_geom(pdf, [])
items = [t for _r, t, *_ in pdftext.clean(pages, geom=geoms)["items"]]
check(not any("SNP" in t and ("Гено" in t or "БА" in t) for t in items), "ячейки шапки не слиплись: %r" % items)
check(any(t.replace(" ", "") == "Генотип" for t in items), "двухстрочная ячейка «Гено-/тип» собралась в одну")
check(any(t.strip() == "Контроль, n, %" for t in items), "«Контроль, n, %» — своя ячейка")
check(not any("SNP" in t and "rs10905277" in t for t in items), "шапка не сливается с рядом данных под линией")

# ─── Т35. Колонки только внутри расчерченной таблицы ─────────────────
print("=== Т35. Ложное начало колонки вне таблицы строку не режет ===")
title = [chunk("Ассоциация варианта гена ", 50.0, 637.0), chunk("GATA3", 170.0, 637.0),
         chunk(" с развитием", 196.0, 637.0)]
table_rules = [[118.0, 480.0, 118.0, 520.0], [190.0, 480.0, 190.0, 520.0]]
g = pw._h_groups([0, 1, 2], title, 0.5, [170.5], None, table_rules)
check(len(g) == 1, "заголовок над расчерченной таблицей остаётся одной надписью")
g = pw._h_groups([0, 1, 2], title, 0.5, [170.5], None, ())
check(len(g) >= 2, "без линий на странице — прежнее правило колонок")
check(pw._in_ruled(table_rules, 500.0, 8.5) and not pw._in_ruled(table_rules, 637.0, 8.5),
      "строка внутри высоты линий — в таблице, над ней — нет")
check(not pw._in_ruled(table_rules, 500.0, 8.5, 400.0), "сбоку от расчерченной таблицы — не в ней")

# ─── Т36. Ключ легенды ───────────────────────────────────────────────
print("=== Т36. Ключ легенды — сплошной квадрат у левого края строки ===")
img = np.full((80, 320, 3), 255, np.uint8)
img[47:57, 20:30] = (30, 120, 220)                      # ключ серии
for x in range(40, 126, 9):
    img[44:58, x:x + 5] = (90, 90, 90)                   # «буквы» подписи серии
for x in (112, 121):
    img[10:24, x:x + 5] = (90, 90, 90)                   # подпись оси «AA» над ней
legend = [38, 42, 131, 60]                               # правый край — как у «AA»
axis = [108, 8, 128, 26]
check(image_text.legend_key(img, legend) is not None, "квадрат слева от подписи — ключ")
check(image_text.legend_key(img, axis) is None, "у подписи оси ключа нет")
round_ = np.full((80, 320, 3), 255, np.uint8)
yy, xx = np.ogrid[:80, :320]
round_[(yy - 52) ** 2 + (xx - 25) ** 2 <= 30] = (30, 30, 30)
for x in range(40, 150, 9):
    round_[44:58, x:x + 5] = (90, 90, 90)
check(image_text.legend_key(round_, legend) is None, "круглый маркер списка ключом не считается")
bar = np.full((80, 320, 3), 255, np.uint8)
bar[20:60, 18:30] = (120, 120, 120)                     # высокий столбик диаграммы слева
for x in range(40, 126, 9):
    bar[44:58, x:x + 5] = (90, 90, 90)
check(image_text.legend_key(bar, legend) is None, "столбик диаграммы слева (выше строки) — не ключ")
high = np.full((80, 320, 3), 255, np.uint8)
high[30:38, 22:30] = (30, 120, 220)                     # квадрат выше строки
for x in range(40, 126, 9):
    high[44:58, x:x + 5] = (90, 90, 90)
check(image_text.legend_key(high, legend) is None, "квадрат не на высоте строки — не ключ")

print("=== Т36. Строка с ключом начинает свой блок ===")
la = {"box": axis, "flat": 1.0}
lb = {"box": legend, "flat": 1.0}
check(len(image_text.group_blocks([dict(la), dict(lb)])) == 1, "без ключа подписи склеиваются (прежняя беда)")
lb["key"] = image_text.legend_key(img, legend)
check(len(image_text.group_blocks([dict(la), dict(lb)])) == 2, "с ключом — два блока: подпись оси и подпись серии")
plan = image_text.split_plan([{"box": [38, 8, 131, 60], "lineBoxes": [axis, legend]}], img)
check(plan == {0: [1]}, "сохранённый блок «AA + легенда» режется перед строкой с ключом: %r" % plan)

print("=== Т36. Разрез сохранённого блока в перегруппировке ===")
import main  # noqa: E402
from PIL import Image
buf = io.BytesIO()
Image.fromarray(img).save(buf, "PNG")
blob = buf.getvalue()


def rec_and_project(human=False):
    blk = {"box": [38, 8, 131, 60], "rows": 2, "lineH": 18, "lineBoxes": [axis, legend], "text": "AA Легкая", "seg": 7}
    rec = {"part": "word/media/image1.png", "blocks": [blk], "groupRule": 3}
    seg = {"id": 7, "source": "AA Легкая", "target": "AA Mild", "status": "translated",
           "origin": {"kind": "image", "part": "word/media/image1.png", "block": 0}}
    if human:
        seg["status"] = "confirmed"                  # подпись человека
    return rec, {"id": 1, "segments": [seg]}


rec, pr = rec_and_project()
n = main._regroup_rec(rec, pr, False, blob)
check(n >= 1 and len(rec["blocks"]) == 2, "блок разрезан на два: %d" % len(rec["blocks"]))
check(all("text" not in b for b in rec["blocks"]), "у частей нет текста — их дочитает шаг чтения")
check(not pr["segments"], "сегмент склеенного блока снят")
check(all(b.get("splitKey") for b in rec["blocks"]) and image_text.regroup_plan(rec["blocks"]) == [],
      "части разреза ритмовая склейка обратно не собирает")
rec, pr = rec_and_project(human=True)
main._regroup_rec(rec, pr, False, blob)
check(len(rec["blocks"]) == 1 and pr["segments"], "блок с работой человека не режется")
rec, pr = rec_and_project()
check(main._regroup_rec(rec, pr, True, blob) >= 1 and len(rec["blocks"]) == 1, "сухой прогон ничего не меняет")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
