# -*- coding: utf-8 -*-
"""Правила раздела Т docs/rules/pdf-reading.md — разбор выгрузки (7) проекта 14
против оригинала (13.10.2026), часть, сделанная в главной ветке работы:

  Т1  узкая ячейка ищет свободную бумагу до первой краски ниже, ячейка строки
      таблицы — до низа своей строки (`_free_below`, `_row_bottom`);
  Т2  хвост слова, уже разрезанного переносом, второй раз не режется;
  Т3  рамка не сцепляет ячейки соседних строк таблицы и не идёт через
      нарисованное (`_frame_cut`);
  Т4  граница колонки — середина зазора до близкого соседа (`_free_room`);
  Т5  линейка в полосе строки — не краска соседа (`_trim_rule_rows`);
  Т6  строки таблицы: заголовок над шапкой и вторая строка ячейки первой
      колонки границу строки не ставят (`pdftext._table_streams`);
  Т7  знак сравнения, «&» и знак сноски не мусор (`pdftext._clean_line`);
  Т8  «MLTCs» — капс (`pdftext._caps_label`);
  Т9  над- и подстрочные знаки — знаками Юникода (`pdfpages_worker._script_marks`),
      проверка чисел их понимает (`checks._extract_numbers`);
  Т18 узкий оригинал — узким файлом шрифта (`layout_pdf._cond_family`).
"""
import os
import sys
from collections import Counter

os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_pdf
import pdftext
import pdfpages_worker
import textcount
import checks
from pdf_fixture import make_pdf

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def _sample(w_pt, h_pt, paint, scale=2.0, paper=(232, 232, 232)):
    """(картинка, масштаб, рамка, серая) — как `_Sampler` для страницы w×h пт;
    `paint(draw, px)` рисует, px(x, y) — пункты в пиксели (y снизу)."""
    from PIL import Image, ImageDraw
    W, H = int(w_pt * scale), int(h_pt * scale)
    im = Image.new("RGB", (W, H), paper)
    d = ImageDraw.Draw(im)
    paint(d, lambda x, y: (int(x * scale), int(H - y * scale)))
    return im, scale, (0.0, 0.0, w_pt, h_pt), im.convert("L")


def _slot(x0, x1, y, size=4.2, **kw):
    sd = {"x": x0, "x0": x0, "x1": x1, "y": y, "size": size, "page": 0, "style": ""}
    sd.update(kw)
    return sd


print("=== Т1. Ячейка таблицы спускается до низа своей строки ===")
# Серая таблица, строка от y=250 вниз до белой линии на y=150; у ячейки
# «SGLT2 inhibitors» (одна строка) под ней пусто до этой линии, у соседней
# ячейки той же строки — 12 строк текста.
def paint1(d, px):
    d.line([px(10, 150), px(390, 150)], fill=(255, 255, 255), width=2)
s1 = _sample(400, 300, paint1)
cell = _slot(23.4, 51.6, 249.0)
mates = [_slot(90, 150, 249.0)] + [_slot(90, 150, 249.0 - 5.0 * k) for k in range(1, 15)]
layout_pdf._chain_lows([cell] + mates)
layout_pdf._free_below(s1, [cell], 232 / 255.0, page_slots=[cell] + mates)
check((cell.get("below") or 0) > 40, "ячейка спустилась до низа строки: below=%s" % cell.get("below"))
cell2 = _slot(23.4, 51.6, 249.0)
layout_pdf._free_below(s1, [cell2], 232 / 255.0, page_slots=[cell2])
check(cell2.get("below") is None or cell2["below"] <= 13 * 5.04,
      "без соседей в ряду — не дальше %s строк: %s" % (layout_pdf.FREE_BELOW_CELL_LINES, cell2.get("below")))
wide = _slot(20, 380, 249.0, size=6.0)
layout_pdf._free_below(s1, [wide], 232 / 255.0, page_slots=[wide])
check(wide.get("below") is None or wide["below"] <= layout_pdf.FREE_BELOW_LINES * 7.2 + 0.01,
      "колонка книги (шире %d кеглей) живёт по-старому: %s" % (layout_pdf.FREE_BELOW_CELL_EM, wide.get("below")))
s1b = _sample(400, 300, lambda d, px: None)
lone = _slot(23.4, 51.6, 249.0)
layout_pdf._free_below(s1b, [lone], 232 / 255.0, page_slots=[lone])
check(lone.get("below") is None, "пусто до края досягаемости — поле, не растём")

print("=== Т2. Слово режется переносом не больше одного раза ===")
sw = lambda t, f, s: len(t) * 0.5 * s
hy = lambda w: [i for i in range(3, len(w) - 2, 3)]  # точки переноса через 3 знака
slots = [_slot(0, 12, 100 - 6 * k, size=4.0) for k in range(4)]
lines, rest = layout_pdf._lay_flow(["недостаточность"], slots, 1.0, 1.0, lambda sd: "F", sw,
                                    "left", False, {}, hy)
check(rest and rest[-1] == "\x00" or len([l for l in lines if l]) <= 2,
      "«недостаточность» не режется в столбик: %s / %s" % (lines, rest))


hyr = layout_pdf._hyphenator("RU")
if hyr is not None:
    sl2 = [_slot(0, 9, 100 - 6 * k, size=4.0) for k in range(6)]
    ln2, rs2 = layout_pdf._lay_flow(["недостаточность"], sl2, 1.0, 1.0, lambda sd: "F", sw,
                                    "left", False, {}, hyr)
    check(len([l for l in ln2 if l]) <= 2, "словарь переносов: слово режется не больше раза: %s / %s" % (ln2, rs2))
    sl3 = [_slot(0, 30, 100 - 6 * k, size=4.0) for k in range(6)]
    ln3, rs3 = layout_pdf._lay_flow(["почечно-сердечно-сосудистых", "исходов"], sl3, 1.0, 1.0,
                                    lambda sd: "F", sw, "left", False, {}, hyr)
    check(not rs3 and len([l for l in ln3 if l]) >= 3,
          "составное слово рвётся по своим дефисам сколько нужно: %s / %s" % (ln3, rs3))
else:
    print("  (нет словаря переносов — проверка Т2 со словарём пропущена)")

print("=== Т3. Рамка не сцепляет ячейки соседних строк таблицы ===")
hdr = _slot(190, 230, 330.0, page=0)
val = _slot(191, 204, 312.0, page=0)
row_h = [_slot(140, 175, 330.0), _slot(240, 280, 330.0)]
row_v = [_slot(140, 170, 312.0), _slot(240, 260, 312.0)]
ps = {0: [hdr, val] + row_h + row_v}
check(layout_pdf._frame_cut(hdr, val, ps), "шапка и ячейка под ней — разные рамки")
p1, p2 = _slot(40, 200, 300.0), _slot(40, 200, 290.0)
check(not layout_pdf._frame_cut(p1, p2, {0: [p1, p2]}), "абзацы одной колонки без соседей — сцепляются")

print("=== Т4. Граница колонки — середина зазора до близкого соседа ===")
s4 = _sample(400, 300, lambda d, px: None, paper=(255, 255, 255))
sd4 = _slot(191.5, 204.3, 200.0, lim2=223.8)
layout_pdf._free_room(s4, sd4, 1.0)
cap = 204.3 + layout_pdf.ROOM_TAKE * (223.8 - 204.3) - layout_pdf.ROOM_GUTTER * 4.2
check(sd4.get("room1") is None or sd4["room1"] <= cap + 0.01,
      "рост вправо не дальше середины зазора: room1=%s ≤ %.1f" % (sd4.get("room1"), cap))
far = _slot(20, 40, 200.0, lim2=300.0)
layout_pdf._free_room(s4, far, 1.0)
check((far.get("room1") or 0) > 60, "далёкий сосед — прежний запас: %s" % far.get("room1"))

print("=== Т5. Линейка под строкой — не краска соседа ===")
import numpy as np
from PIL import Image
a = np.full((30, 200), 230, dtype=np.uint8)
a[25:27, :] = 20                     # линейка у нижнего края полосы
a[8:20, 20:40] = 30                  # буквы самой строки
g = Image.fromarray(a)
y0, y1 = layout_pdf._trim_rule_rows(g, 0, 200, 0, 30, 150)
check(y1 <= 25 and y0 == 0, "полоса обрезана над линейкой: %s..%s" % (y0, y1))
b = np.full((30, 200), 230, dtype=np.uint8)
b[12:14, :] = 20                     # линия посреди полосы — зачёркнутое, не трогаем
y0b, y1b = layout_pdf._trim_rule_rows(Image.fromarray(b), 0, 200, 0, 30, 150)
check((y0b, y1b) == (0, 30), "линия посреди полосы не обрезает: %s..%s" % (y0b, y1b))

print("=== Т6. Строки таблицы: заголовок и вторая строка ячейки ===")
import pypdf as _pp
if tuple(int(x) for x in _pp.__version__.split(".")[:2]) < (6, 18):
    # pypdf до 6.18 отдаёт у второго куска одной строки координаты нулями,
    # и синтетическая таблица из отдельных BT не разбирается вовсе — тест
    # мерил бы версию pypdf. Настоящий файл проекта 14 на 6.16 проверен
    # замером (scratchpad cmp616.py): правило работает.
    print("  (pypdf %s < 6.18 — синтетическая таблица пропущена)" % _pp.__version__)
else:
    def _bt(x, y, sz, t):
        return ("raw", "BT /F1 %s Tf 1 0 0 1 %s %s Tm {HEX:%s:HEX} Tj ET" % (sz, x, y, t))
    T = [_bt(30, 520, 6, "Table 1-Continued")]
    cols = [30, 100, 170, 240, 310]
    T += [_bt(cols[3], 497, 4, "Dosing/use"), _bt(cols[4], 497, 4, "Route of")]
    T += [_bt(cols[0], 490, 4, "Medication"), _bt(cols[1], 490, 4, "Efficacy"),
          _bt(cols[2], 490, 4, "Cost"), _bt(cols[3], 490, 4, "considerations"),
          _bt(cols[4], 490, 4, "administration")]
    rows = [("Metformin", "High", "Low", "Neutral", "Oral"),
            ("Dual GLP-1/GIP", "Very high", "High", "Benefit for kidney end", "s.c."),
            ("agonists", "", "", "points in CVOTs:", ""),
            ("Insulin", "Highest", "Low", "Neutral", "s.c.")]
    y = 475
    for r in rows:
        for c, t in zip(cols, r):
            if t:
                T.append(_bt(c, y, 4, t))
        y -= 7 if r[0] == "Dual GLP-1/GIP" else 14
    pg6, gm6 = textcount._pdf_pages_geom(make_pdf([T]), [])
    par6 = [it[1] for it in pdftext.clean(pg6, geom=gm6)["items"] if it[0] == "p"]
    check("Dosing/use considerations" in par6, "ячейка шапки — один абзац: %s" % par6)
    check("Route of administration" in par6, "«Route of administration» — один абзац")
    check("Dual GLP-1/GIP agonists" in par6, "вторая строка ячейки первой колонки — та же ячейка")
    check("Benefit for kidney end points in CVOTs:" in par6, "ячейка соседней колонки не разрезана")
    check("Metformin" in par6 and "Insulin" in par6, "строки таблицы по-прежнему разные")


    # Контрпримеры (критик): строчный столбец с тесным шагом — строки таблицы;
    # редкая верхняя строка с соседями — строка таблицы.
    L = [_bt(30, 500, 4, "Medication"), _bt(120, 500, 4, "Dose"), _bt(200, 500, 4, "Route")]
    for k_, (a_, b_, c_) in enumerate([("metformin", "500 mg", "oral"), ("insulin", "10 U", "s.c."),
                                        ("aspirin", "75 mg", "oral"), ("warfarin", "5 mg", "oral")]):
        yy = 492 - 6 * k_
        L += [_bt(30, yy, 4, a_), _bt(120, yy, 4, b_), _bt(200, yy, 4, c_)]
    pgL, gmL = textcount._pdf_pages_geom(make_pdf([L]), [])
    parL = [it[1] for it in pdftext.clean(pgL, geom=gmL)["items"] if it[0] == "p"]
    check("metformin" in parL and "insulin" in parL and not any("metformin insulin" in x for x in parL),
          "строчный столбец с тесным шагом — разные строки таблицы: %s" % parL)

print("=== Т7. Знаки сравнения, «&», сноски ===")
cl = lambda t: pdftext._clean_line(t, Counter())
check(cl("and <TEE") == "and <TEE", "«<» перед словом остаётся")
check(cl("HbA1c <7%") == "HbA1c <7%", "строка «HbA1c <7%» не мусор")
check(cl("Merck Sharp & Dohme") == "Merck Sharp & Dohme", "«&» между словами остаётся")
check(cl("therapy§ early") == "therapy§ early" and cl("*Evidence specific") == "*Evidence specific",
      "знаки сноски остаются")
check(cl("<308>") == "308", "обёрнутое парой — разметка, снимается")
check(cl("p < 0.05") == "p < 0.05" and cl("BMI > 30") == "BMI > 30", "знак сравнения отдельным словом перед числом остаётся")
check(cl("живота* выпадение") == "живота выпадение", "«*» посреди фразы перед строчной — мусор скана")
check(cl("^лучше") == "лучше", "одиночный мусор снимается, как прежде")

print("=== Т8. Капс со строчной «s» множественного числа ===")
check(pdftext._caps_label("DEVELOP MLTCs"), "«DEVELOP MLTCs» — капс")
check(not pdftext._caps_label("Stops here now"), "обычный текст — не капс")

print("=== Т9. Над- и подстрочные знаки ===")
S9 = [("raw", "BT /F1 6 Tf 1 0 0 1 40 300 Tm {HEX:Heart failure:HEX} Tj ET "
              "BT /F1 4 Tf 1 0 0 1 77.5 302.6 Tm {HEX:a:HEX} Tj ET"),
      ("raw", "BT /F1 6 Tf 1 0 0 1 40 280 Tm {HEX:per 1.73 m:HEX} Tj ET "
              "BT /F1 4 Tf 1 0 0 1 66.0 282.6 Tm {HEX:2:HEX} Tj ET"),
      ("raw", "BT /F1 6 Tf 1 0 0 1 40 260 Tm {HEX:vitamin B:HEX} Tj ET "
              "BT /F1 4 Tf 1 0 0 1 63.4 258.6 Tm {HEX:12:HEX} Tj ET"),
      ("raw", "BT /F1 6 Tf 1 0 0 1 40 240 Tm {HEX:HbA:HEX} Tj ET "
              "BT /F1 4 Tf 1 0 0 1 47.8 238.6 Tm {HEX:1c:HEX} Tj ET")]
pg9, gm9 = textcount._pdf_pages_geom(make_pdf([S9]), [])
txt9 = " | ".join(pg9[0])
check("failureᵃ" in txt9, "сноска «a» — ᵃ: %s" % txt9)
check("m²" in txt9, "степень — ²")
check("B₁₂" in txt9, "индекс — ₁₂")
check("HbA1c" in txt9, "«1c» (у «c» нет подстрочной формы) — как было")
check(checks._extract_numbers("1,73 m²") == checks._extract_numbers("1,73 м2"),
      "проверка чисел: «m²» и «м2» — одно число")

print("=== Т18. Узкий оригинал — узким файлом ===")
fonts = layout_pdf._register_fonts("Препарат Medication")
c1 = layout_pdf._cond_family(fonts, "sans", "", 0.76)
c2 = layout_pdf._cond_family(fonts, "sans", "b", 0.66)
check(c1 is not None and c1[0] == "sansc" and 0.7 < c1[1] < 0.9, "0.76 — Condensed: %s" % (c1,))
check(c2 is not None and c2[0] == "sansx", "0.66 — ExtraCondensed: %s" % (c2,))
check(layout_pdf._cond_family(fonts, "sans", "", 0.82) is None,
      "0.82 — просто узковатая гуманистическая гарнитура (основной текст статьи) — обычный файл")
check(layout_pdf._cond_family(fonts, "", "", 0.7) is None, "засечки узким рубленым не заменяются")

print()
print("ALL OK" if not fail else "FAILED: %d" % len(fail))
sys.exit(1 if fail else 0)
