# -*- coding: utf-8 -*-
"""Выгрузка PDF «как в оригинале»: единый набор (раздел Л в
docs/rules/pdf-reading.md).

Боевой случай — проект 14 (консенсус ADA/EASD, EN→RU, жалоба 12.10.2026):
кегль у каждого абзаца свой, строки колонки «по центру», заголовок в подбор
налезает на тело, строка со ссылкой печатается поверх строки, ячейка таблицы
уезжает в соседнюю, литература наполовину переведена транслитом, адрес
транслитерирован, метки схемы — то латиницей, то калькой.
"""
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")

import layout_pdf  # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


ok_lib, why = layout_pdf.available()
from reportlab.pdfbase import pdfmetrics  # noqa: E402

fonts = layout_pdf._register_fonts(set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
                                       "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ.,"))
SW = pdfmetrics.stringWidth
FONT = layout_pdf._font_for(fonts, {"style": "", "fam": "sans"})


def font_of(_sd):
    return FONT


def slot(x, y, x1, size=10.0, page=0, style="", paper=1.0):
    return {"x0": x, "x": x, "x1": x1, "y": y, "size": size, "page": page, "style": style,
            "n": 40, "exact": True, "top": y + 0.85 * size, "bottom": y - 0.25 * size,
            "_fill": ([(paper, paper, paper)] * 3, paper, 1.8)}


def column(n, x=40.0, y=700.0, w=200.0, size=10.0, pitch=12.0, page=0, paper=1.0):
    return [slot(x, y - k * pitch, x + w, size, page, paper=paper) for k in range(n)]


WORDS = ("Перевод длиннее оригинала примерно на треть и обязан встать в ту же "
         "колонку целиком без потерь слов и без вылезания за правый край места").split()


def plan_of(paras):
    """slot_plan/slot_meta как у `build` до историй: по абзацу [(слоты, текст)]."""
    sp, sm = [], []
    for k, (orig, text) in enumerate(paras):
        sp.append((orig, [""] * len(orig), [1.0] * len(orig), [], font_of, "left",
                   [1.0] * len(orig)))
        sm.append({"idx": k, "text": text, "sw": SW, "nospace": False, "scattered": False,
                   "fam": "sans", "hy": None, "orig": orig, "just": True})
    return sp, sm


print("=== 1. Выключка по видимым строкам: заголовок в подбор и разрезанная строка ===")
body = [slot(92, 700, 150)] + [slot(42, 700 - 8 * k, 150) for k in range(1, 6)] + [slot(42, 652, 110)]
check(layout_pdf._slot_align(body) == "left",
      "первая строка за заголовком в подбор (x 92 при 42) — «влево», а не «вправо»")
split = [slot(42, 700 - 12 * k, 250) for k in range(4)] + [slot(42, 652, 240), slot(243, 652, 250)]
check(layout_pdf._slot_align(split) == "left" and layout_pdf._justified(split),
      "строка из двух кусков одной базовой — одна строка: «влево», по ширине")
head = [slot(60, 700, 180), slot(80, 688, 160), slot(100, 676, 140)]
check(layout_pdf._slot_align(head) == "center", "центрированная подпись — по центру")
cells = [slot(40, 700, 90), slot(200, 700, 260)]
check(len(layout_pdf._vis_lines(cells)) == 2, "ячейки одной высоты с широким зазором — две строки")

print("=== 2. Кегль строки — большинства строк абзаца ===")
mixed = [slot(40, 700, 240, size=5.25)] + [slot(40, 700 - 8 * k, 240, size=6.65) for k in range(1, 4)]
runs = layout_pdf._runs(mixed)
vs = layout_pdf._regrid(mixed, [list(range(len(mixed)))], 0.9)
check(all(abs(v["size"] - 6.6) < 0.11 for v in vs),
      "строка, начатая заголовком 5.25, печатается кеглем тела 6.65")

print("=== 3. История: колонка → соседняя колонка, один кегль ===")
long_text = " ".join(WORDS * 2)
col1 = column(6, x=40, y=700)
col2 = column(6, x=260, y=700)
sp, sm = plan_of([(col1, long_text), (col2, " ".join(WORDS[:8]))])
st = {}
layout_pdf._stories(sp, sm, st, None)
fs = {round(sp[i][2][0], 3) for i in range(2)}
words_out = " ".join(" ".join(x for x in sp[i][1] if x) for i in range(2)).split()
check(st.get("stories") == 1 and len(fs) == 1,
      "два абзаца колонок — одна история одним кеглем (%s)" % sorted(fs))
check(len(words_out) == len(long_text.split()) + 8, "все слова на месте")
check(all(v["x"] >= 40 - 0.1 and v["x1"] <= 460.1 for i in range(2) for v in sp[i][0]),
      "строки в своих колонках")
check(all(f in layout_pdf.STORY_STEPS for f in fs), "кегль — ступень, а не своё число")

print("=== 4. Заголовок в подбор продолжает строку, не налезает ===")
hd = [slot(40, 700, 95, size=7.0, style="bi")]
bd = [slot(100, 700, 240)] + [slot(40, 700 - 12 * k, 240) for k in range(1, 6)]
sp, sm = plan_of([(hd, "Гиперкортицизм."), (bd, " ".join(WORDS))])
st = {}
layout_pdf._stories(sp, sm, st, None)
h0, b0 = sp[0][0][0], sp[1][0][0]
w_head = SW(sp[0][1][0], FONT, h0["size"] * sp[0][2][0]) * sp[0][6][0]
check(abs(h0["y"] - b0["y"]) < 0.01 and b0["x"] >= h0["x"] + w_head,
      "тело начинается на строке заголовка, правее напечатанного заголовка")

print("=== 5. История не переходит через смену фона ===")
band = column(1, y=700, w=300, paper=0.3)
cell = column(3, y=688, w=300, paper=1.0)
sp, sm = plan_of([(band, "ЗАГОЛОВОК ПОЛОСЫ ТАБЛИЦЫ"), (cell, " ".join(WORDS[:12]))])
st = {}
layout_pdf._stories(sp, sm, st, None)
check(sm[0].get("story") is None or sm[0].get("story") != sm[1].get("story"),
      "полоса таблицы и ячейка под ней — разные места")

print("=== 6. Свободная бумага вбок — до начала соседней колонки ===")
lab = slot(40, 700, 90)
other = slot(150, 712, 200)
layout_pdf._neighbour_limits([lab, other])
check(abs(lab.get("lim2", 0) - 150) < 0.01, "начало колонки строкой выше — рубеж запаса")
check("lim" not in lab, "рубеж конца строки (та же высота) не задет")

print("=== 7. Текст к печати: литература, адреса, метки-сокращения ===")
import contextlib  # noqa: E402
import io  # noqa: E402
with contextlib.redirect_stdout(io.StringIO()):
    import main  # noqa: E402
check(main._keep_verbatim("available at https://doi.org/10.17605/osf",
                          "доступны по адресу хттпс://дои.орг/10.17605/осф")
      .endswith("https://doi.org/10.17605/osf"), "транслит адреса — обратно буква в букву")
check(main._keep_verbatim("see 177.Out M, HbA1c/GLP-1 and e.g. 1.2.3",
                          "см. 177.Аут М, HbA1c/ГПП-1 и напр. 1.2.3")
      == "см. 177.Аут М, HbA1c/ГПП-1 и напр. 1.2.3", "не адреса не трогаются")
check(main._glue_urls("at https://doi.org/10.17605/osf .io/pu93h. Publications",
                      "по адресу https://doi.org/10.17605/osf .io/pu93h. Публикации")
      == "по адресу https://doi.org/10.17605/osf.io/pu93h. Публикации",
      "адрес, разорванный переносом строки, склеен")
proj = {"id": 991, "src": "EN", "tgt": "RU", "segments": [
    {"id": 1, "source": "Low-energy ketogenic diet (LEKD)", "target": "Низкоэнергетическая кетогенная диета (НЭКД)"},
    {"id": 2, "source": "Very-low-energy ketogenic diet (VLEKD)", "target": "Очень низкоэнергетическая кетогенная диета (ОНЭКД)"},
    {"id": 3, "source": "LEKD", "target": "LEKD"},
    {"id": 4, "source": "VLEKD", "target": "ВЛЕКД"},
    {"id": 5, "source": "TRE LEKD", "target": "TRE LEKD"},
    {"id": 6, "source": "LEKD is used", "target": "LEKD применяется"},
    {"id": 7, "source": "VLEKD", "target": "ОНЭКД-диета", "status": "confirmed"},
]}
pb = main._print_by_id(proj)
check(pb[3]["target"] == "НЭКД" and pb[4]["target"] == "ОНЭКД",
      "метка схемы — как документ определил сокращение")
check(pb[5]["target"] == "TRE LEKD" and pb[6]["target"] == "LEKD применяется",
      "две метки одной строкой и сокращение внутри фразы — не трогаются")
check(pb[7]["target"] == "ОНЭКД-диета", "работа человека не трогается")
check(proj["segments"][3]["target"] == "ВЛЕКД", "сам проект не меняется")
refs = [{"id": 100, "source": "References", "target": "Литература"},
        {"id": 101, "source": "1.Gattrell WT, Logullo P, van Zuuren EJ, et al.", "target": "1.Гатрелл У. Т., и др."},
        {"id": 102, "source": "ACCORD (ACcurate COnsensus Reporting Document):", "target": "АККОРД:"},
        {"id": 103, "source": "a reporting guideline for consensus methods.", "target": "руководство."}]
for k in range(2, 14):
    refs.append({"id": 100 + 2 * k, "source": "PLoS Med 2024;21:e10043%02d %d.Davies MJ, Aroda VR, et al." % (k, k),
                 "target": "PLoS Med 2024;21:e10043%02d %d.Дэвис М. Дж. и др." % (k, k)})
    refs.append({"id": 101 + 2 * k, "source": "Diabetes Care 2022;45:27%02d–2786" % k,
                 "target": "Diabetes Care 2022;45:27%02d–2786" % k})
pr = {"id": 992, "src": "EN", "tgt": "RU", "segments": refs}
z = main._refs_of(pr)
check({101, 102, 103} <= set(z["keep"]) and 100 not in z["keep"],
      "первая запись списка (разорванная на строки) — в зоне, заголовок — нет")
pb = main._print_by_id(pr)
check(pb[101]["target"] == refs[1]["source"] and pb[104]["target"] == refs[4]["source"],
      "литература печатается оригиналом, хотя машина её перевела")

print("=== 8. Вложенные надписи: родитель уступает строкам-наследникам ===")


def lab_(t, src, x0, top, x1, bot, rows=1):
    return {"text": t, "boxes": [{"page": 0, "x0": x0, "top": top, "x1": x1, "bottom": bot,
                                  "rows": rows, "src": src}]}


par = lab_("А Б В", "Consider medication Consider surgery", 0.1, 0.1, 0.5, 0.3, rows=2)
k1 = lab_("А", "Consider medication", 0.1, 0.1, 0.5, 0.2)
k2 = lab_("Б", "Consider surgery", 0.1, 0.2, 0.5, 0.3)
keep, n = main._drop_nested_labels([par, k1, k2])
check(n == 1 and par not in keep and k1 in keep and k2 in keep,
      "наследники покрывают родителя — печатаются они")
keep, n = main._drop_nested_labels([par, k1])
check(n == 1 and par in keep and k1 not in keep,
      "наследник покрывает часть — печатается родитель")

keep, n = main._drop_nested_labels([lab_("Все о медолечении России", "All about bee therapy Russia",
                                         0.1, 0.1, 0.5, 0.3, rows=2),
                                    lab_("о медолечении России", "about bee therapy Russia",
                                         0.15, 0.1, 0.5, 0.2)])
check(n == 1 and keep[0]["text"].startswith("Все"),
      "обложка: один вложенный повтор снимается, а не родитель")

print("=== 9. Находки критика: абзац через страницу, литература, запасной ход ===")
pg0 = column(3, y=700, page=0)
pg1 = column(3, y=700, page=1)
sp, sm = plan_of([(pg0 + pg1, " ".join(WORDS * 2))])
st = {}
layout_pdf._stories(sp, sm, st, None)
got_w = " ".join(x for x in sp[0][1] if x).split()
check(len(got_w) == len(WORDS) * 2 and {v["page"] for v in sp[0][0]} == {0, 1},
      "абзац, разорванный страницей, собран из обеих историй — все слова, обе страницы")
pr2 = {"id": 993, "src": "EN", "tgt": "RU", "segments": [
    {"id": 300 + k, "source": t, "target": "перевод %d" % k} for k, t in enumerate([
        "1. Measure BP, HR and ECG in all patients.",
        "Patients with resistant hypertension need review.",
        "References"])] + refs[4:]}
z2 = main._refs_of(pr2)
check(not ({300, 301, 302} & set(z2["keep"])), "нумерованный пункт текста перед списком — не литература")
hd = [slot(40, 700, 230, size=7.0, style="bi")]
bd = [slot(232, 700, 240)] + [slot(40, 700 - 12 * k, 240) for k in range(1, 6)]
sp, sm = plan_of([(hd, "Очень длинный заголовок в подбор, который занимает всю строку колонки."),
                  (bd, " ".join(WORDS))])
layout_pdf._stories(sp, sm, {}, None)
hl, b1 = sp[0][0][-1], sp[1][0][0]
hw = SW(sp[0][1][-1], FONT, hl["size"] * sp[0][2][-1]) * sp[0][6][-1]
check(b1["y"] <= hl["y"] - 5.0 or (abs(b1["y"] - hl["y"]) < 0.01 and b1["x"] >= hl["x"] + hw),
      "места за заголовком нет — тело со следующей строки, а не поверх")

print("=== 10. Проект 14, 12.10: маркер, заголовок за потоком, названия статей ===")
check(layout_pdf._with_bullet("Сахарный диабет", [{"bullet": "•"}]) == "• Сахарный диабет",
      "маркер пункта, снятый разбором, печатается перед переводом")
check(layout_pdf._with_bullet("• Уже с маркером", [{"bullet": "•"}]) == "• Уже с маркером"
      and layout_pdf._with_bullet("Без", [{}]) == "Без", "маркер не задваивается и не выдумывается")
bd = column(5, y=700)
hd = [slot(40, 634, 120, size=11.0, style="b")]       # вплотную под колонкой, как стр. 34
sp, sm = plan_of([(bd, " ".join(WORDS[:12])), (hd, "Литература")])
layout_pdf._stories(sp, sm, {}, None)
check(abs(sp[1][0][0]["y"] - 634) < 0.01,
      "заголовок в конце потока остаётся на своём месте, а не прилипает к ужатому тексту")
refs3 = list(refs[:6]) + [
    {"id": 400, "source": "FIDELIO-DKD and FIGARO-DKD Investigators.", "target": "Исследователи FIDELIO-DKD."},
    {"id": 401, "source": "Finerenone and clinical outcomes in CKD by frailty index: FIDELITY post hoc analysis.",
     "target": "Финеренон и клинические исходы."}] + list(refs[6:])
z3 = main._refs_of({"id": 994, "src": "EN", "tgt": "RU", "segments": refs3})
check({400, 401} <= set(z3["keep"]),
      "две строки без признаков ссылки, зажатые записями, — часть записи (печать оригиналом)")

print()
print("ИТОГ: %s" % ("всё в порядке" if not fail else "%d провал(ов)" % len(fail)))
sys.exit(1 if fail else 0)
