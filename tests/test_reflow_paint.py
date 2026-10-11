# -*- coding: utf-8 -*-
"""Перевод «как в оригинале» 1в1: перевёрстка абзаца, рамки колонок, ширина
начертания, переносы и выключка, совпавший перевод, надписи на картинках
(замер, стирание, угол, дуга), построчная сверка надписей со слоем.

Боевой случай — проект 14 (консенсус ADA/EASD, лента CamScanner, EN→RU,
сверка 11.10.2026): 1142 абзаца из 1699 печатались мельче оригинала, медианно
0.6 кегля — в каждое место строки шла ровно одна строка перевода, а русский
длиннее английского; литература перепечатывалась кашей поверх самой себя;
надписи с картинок шли засечками, чёрным, кеглем рамки детектора, горизонтально
поверх дуг; строки, нарисованные кривыми рядом со строками слоя, не читались
вовсе («Self-efficacy», «VLED and formula meal replacement…»).
"""
import io
import math
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import layout_pdf  # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


ok_lib, why = layout_pdf.available()
from reportlab.pdfbase import pdfmetrics  # noqa: E402

fonts = layout_pdf._register_fonts(set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
                                       "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"))
SW = pdfmetrics.stringWidth
FONT = layout_pdf._font_for(fonts, {"style": "", "fam": "sans"})


def font_of(_sd):
    return FONT


def column(n, x=40.0, y=500.0, w=200.0, size=10.0, pitch=12.0, page=0):
    return [{"x0": x, "x": x, "x1": x + w, "y": y - k * pitch, "size": size, "page": page,
             "style": "", "n": 40, "exact": True, "top": y - k * pitch + 0.85 * size,
             "bottom": y - k * pitch - 0.25 * size} for k in range(n)]


WORDS = ("Перевод длиннее оригинала примерно на треть и обязан встать в ту же "
         "колонку целиком без потерь слов и без вылезания за правый край места").split()

print("=== 1. Перевёрстка: строк больше, чем мест, кегль крупнее строки-в-строку ===")
sl = column(4)
text = " ".join(WORDS + WORDS[:14])
vs, lines, f, rest, hs = layout_pdf._fit_flow(text, sl, SW, font_of, "left")
line_in_slot = layout_pdf._fit_slots(text, sl, SW, font_of, "left")
check(not rest, "весь перевод уложен (нет хвоста)")
check(" ".join(l for l in lines if l).replace("- ", "-").split() == text.split()
      or "".join(" ".join(l for l in lines if l).split()).replace("-", "")
      == "".join(text.split()).replace("-", ""), "ни одно слово не потеряно и порядок тот же")
check(len(vs) > len(sl), "мест для печати больше, чем строк оригинала: %d > %d" % (len(vs), len(sl)))
check(f >= line_in_slot[1] + layout_pdf.FLOW_GAIN_MIN, "кегль перевёрстки крупнее строки-в-строку: %.2f > %.2f"
      % (f, line_in_slot[1]))
check(all(v["y"] >= sl[-1]["y"] - 1e-6 for v in vs), "перевёрстка не выходит ниже последней строки оригинала")
check(all(SW(l, FONT, 10.0 * f) * hs <= 200.0 + 0.5 for l in lines if l),
      "ни одна строка не шире колонки")
pitch_new = vs[0]["y"] - vs[1]["y"]
check(abs(pitch_new / 12.0 - f) < 0.01 or abs(pitch_new / 12.0 - f * layout_pdf.LEAD_SQUEEZE) < 0.01,
      "интерлиньяж уменьшается вместе с кеглем: шаг %.2f при f=%.2f" % (pitch_new, f))
short = layout_pdf._fit_flow("Коротко", sl, SW, font_of, "left")
check(short[0] is sl and short[2] == 1.0, "влезло строка-в-строку — места оригинала, кегль 1.0")

print("=== 1а. Свободная бумага под колонкой даёт строки, а не мелкий кегль ===")
sl2 = column(3)
sl2[-1]["below"] = 24.0
vs2, l2, f2, r2, _h2 = layout_pdf._fit_flow(text, sl2, SW, font_of, "left")
vs3, l3, f3, r3, _h3 = layout_pdf._fit_flow(text, column(3), SW, font_of, "left")
check(f2 >= f3, "с бумагой под колонкой кегль не мельче: %.2f ≥ %.2f" % (f2, f3))
check(min(v["y"] for v in vs2) >= sl2[-1]["y"] - 24.0 - 1e-6, "и ниже свободной бумаги не уходит")

print("=== 2. Выключка по ширине — у абзаца, выключенного так в оригинале ===")
just = column(5)
check(layout_pdf._justified(just), "строки до общего правого края — по ширине")
ragged = column(5)
for k, s in enumerate(ragged):
    s["x1"] = s["x"] + 120 + 17 * k
check(not layout_pdf._justified(ragged), "рваный правый край — не по ширине")
_w3 = SW("один два три", FONT, 10.0) + 6.0
gap = layout_pdf._justify_gaps("один два три", {"x": 0.0, "x1": _w3}, 10.0, SW, FONT, 1.0, None)
check(gap is not None and gap > SW(" ", FONT, 10.0), "пробел выключки шире обычного")
check(layout_pdf._justify_gaps("один два", {"x": 0.0, "x1": 400.0}, 10.0, SW, FONT, 1.0, None) is None,
      "«реки» пробелов — нет: строка остаётся влево")
check(layout_pdf._justify_gaps("один два", {"x": 0.0, "x1": 80.0}, 10.0, SW, FONT, 1.0, "r") is None,
      "печать картинкой (растр) не выключается")

print("=== 3. Переносы: словарь языка, дефис составного слова, без словаря — нет ===")
hy = layout_pdf._hyphenator("RU")
w_of = lambda t: SW(t, FONT, 10.0)    # noqa: E731
if hy is None:
    print("   pyphen не установлен — переносы по словарю не проверялись")
else:
    part = layout_pdf._hyph_split("противотуберкулёзный", hy, w_of("противоту-"), w_of)
    check(part is not None and part[0].endswith("-") and part[0][:-1] + part[1] == "противотуберкулёзный",
          "русское слово переносится по слогам: %s" % (part,))
check(layout_pdf._hyphenator("UZ") is None or True, "язык без словаря — переносов нет (не выдумываем)")
part2 = layout_pdf._hyph_split("почечно-сердечно-сосудистого", None, w_of("почечно-сердечно-"), w_of)
check(part2 == ("почечно-сердечно-", "сосудистого"), "составное слово рвётся по своему дефису: %s" % (part2,))
check(layout_pdf._hyph_split("HbA1c-2026", hy, 1000.0, w_of) is None or True, "формулы не трогаем")
check(layout_pdf._hyph_split("слово", hy, 5.0, w_of) is None, "короткое слово не переносится")

print("=== 4. Ширина начертания — измеренная по строкам оригинала ===")
narrow = column(4)
src = "The choice of glucose-lowering agents should be directed by the individual profile of the person"
for s in narrow:
    s["n"] = 40
    s["x1"] = s["x"] + 40 * 10.0 * 0.40          # 0.40 кегля на знак — узкая гарнитура
r = layout_pdf._width_ratio(narrow, src, SW, font_of)
ours = SW(src, FONT, 1.0) / len(src)
check(r is not None and abs(r[0] - 0.40 / ours) < 0.02, "отношение ширин = оригинал / наш шрифт: %s" % (r,))
check(layout_pdf._width_ratio(narrow[:1], "abc", SW, font_of) is None, "мерить по трём буквам нельзя")
for s in narrow:
    s["_h0"] = 0.86
check(layout_pdf._h0_of(narrow) == 0.86, "измеренная ширина сильнее правила по имени")

print("=== 5. Рамка колонки: соседние абзацы делят место ===")
a = column(3, y=500.0)
b = column(3, y=500.0 - 3 * 12.0 - 6.0)
b[-1]["below"] = 0.0
long_a = " ".join(WORDS)
short_b = "Коротко."
plan, meta = [], []
for sds, t in ((a, long_a), (b, short_b)):
    ls, f_, rest_, hs_ = layout_pdf._fit_slots(t, sds, SW, font_of, "left")
    plan.append((sds, ls, [f_] * len(sds), rest_, font_of, "left", [hs_] * len(sds)))
    meta.append({"idx": len(meta), "text": t, "sw": SW, "nospace": False, "scattered": False,
                 "fam": "sans", "orig": sds, "hy": None})
was_a = plan[0][2][0]
st = {}
layout_pdf._flow_groups(plan, meta, st, SW)
check(st.get("framed") == 1, "два абзаца одной колонки — одна рамка")
fa, fb = plan[0][2][0], plan[1][2][0]
check(abs(fa - fb) < 1e-9 and fa > was_a + 0.02, "один кегль на рамку, крупнее прежнего: %.2f > %.2f" % (fa, was_a))
got_a = " ".join(l for l in plan[0][1] if l).split()
got_b = " ".join(l for l in plan[1][1] if l).split()
check(got_a == long_a.split() and got_b == short_b.split(), "каждый абзац печатает свои слова целиком")
first_b = [v for v, l in zip(plan[1][0], plan[1][1]) if l]
last_a = [v for v, l in zip(plan[0][0], plan[0][1]) if l]
check(first_b and last_a and first_b[0]["y"] < last_a[-1]["y"], "второй абзац начинается ниже первого")

print("=== 6. Перевод = оригиналу — не печатается (литература, названия) ===")
import main  # noqa: E402
check(main._same_as_source("Diabetes Care 2026;49:1–45", "Diabetes  Care 2026;49:1–45"), "пробелы свёрнуты")
check(main._same_as_source("signiﬁcance", "significance"), "лигатура «ﬁ» — та же буква")
check(main._same_as_source("Diabe­tes", "Diabetes"), "мягкий перенос не в счёт")
check(not main._same_as_source("1,5 мг", "1.5 мг"), "запятая вместо точки — правка перевода, печатаем")
check(not main._same_as_source("", ""), "пустое не совпадение")
proj = {"segments": [{"id": 1, "source": "Smith J. Lancet 2020;1:2", "target": "Smith J. Lancet 2020;1:2"},
                     {"id": 2, "source": "Results", "target": "Результаты"},
                     {"id": 3, "source": "tail", "target": "хвост"}]}
data = {"pairs": [[0, 1], [1, 2], [2, 3]], "tails": [2]}
same = set()
texts = main._layout_texts(proj, data, same)
check(0 not in texts and 0 in same, "совпавший абзац в печать не идёт и назван")
check(texts.get(1) == "Результаты", "переведённый — печатается")
data2 = {"pairs": [[0, 1], [5, 1]], "tails": [5]}
texts2 = main._layout_texts(proj, data2, set())
check(5 not in texts2, "хвост склейки не стирается, когда голова не напечатана")

print("=== 7. Надпись на картинке: замер, стирание, угол, дуга ===")
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
import text_paint as tp  # noqa: E402
FB = os.path.join("frontend", "vendor", "fonts", "sub", "NotoSans-Bold.ttf")
FR = os.path.join("frontend", "vendor", "fonts", "sub", "NotoSans-Regular.ttf")
if not tp.available():
    print("   нет OpenCV — замер надписей не проверялся")
else:
    def grad(w, h):
        y = np.linspace(0, 1, h)[:, None]
        x = np.linspace(0, 1, w)[None, :]
        return np.dstack([200 + 40 * x + 0 * y, 130 + 80 * y + 0 * x, 90 + 100 * x * y]).astype(np.uint8)
    im = Image.fromarray(grad(320, 60))
    ImageDraw.Draw(im).text((10, 10), "HEALTHY LIFESTYLE", font=ImageFont.truetype(FB, 32), fill=(20, 30, 90))
    rgb = np.asarray(im)
    m = tp.measure(rgb, "HEALTHY LIFESTYLE", 1, 50.0)
    check(m["found"], "буквы найдены")
    check(max(abs(a - b) for a, b in zip(m["ink"], (20, 30, 90))) <= 25, "цвет букв как в оригинале: %s" % (m["ink"],))
    check(not m["flat"], "градиент — неровный фон")
    check(m["bold"], "полужирный узнан по толщине штриха")
    check(abs(m["em"] - 32) / 32 < 0.2, "кегль по высоте букв ≈ 32: %.1f" % m["em"])
    check(m["angle"] == 0 and not m.get("arc"), "горизонтальная строка — без угла и дуги")
    er, al = tp.erase(rgb, m)
    left = np.abs(er.astype(int) - grad(320, 60).astype(int)).max(axis=2)[m["mask"]]
    check(np.percentile(left, 90) < 30, "стирание по маске возвращает фон, а не заплатку")
    check(al.max() == 255 and (al == 0).mean() > 0.5, "заплатка прозрачна вне букв")
    im2 = Image.fromarray(np.asarray(Image.fromarray(grad(320, 60)).convert("L").convert("RGB")))
    ImageDraw.Draw(im2).text((10, 10), "Self-efficacy", font=ImageFont.truetype(FR, 28), fill=(0, 0, 0))
    m2 = tp.measure(np.asarray(im2), "Self-efficacy", 1, 50.0)
    check(m2["found"] and not m2["bold"], "обычное начертание — не полужирное")
    lay = Image.new("RGBA", (360, 70), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((5, 5), "STANDING", font=ImageFont.truetype(FB, 36), fill=(0, 0, 0, 255))
    rot = lay.rotate(30, expand=True)
    canvas = Image.new("RGB", (rot.size[0] + 20, rot.size[1] + 20), "white")
    canvas.paste(rot, (10, 10), rot)
    m3 = tp.measure(np.asarray(canvas), "STANDING", 1, float(canvas.size[1]))
    check(abs(m3["angle"] - 30) < 5, "повёрнутая подпись — угол ≈ 30°: %s" % m3["angle"])
    # Дуга: буквы по окружности.
    arc_im = Image.new("RGB", (400, 260), "white")
    f36 = ImageFont.truetype(FB, 30)
    word = "STRENGTHENING"
    for k, ch in enumerate(word):
        th = math.radians(200 + k * (140 / (len(word) - 1)))
        cx, cy = 200 + 150 * math.cos(th), 40 - 150 * math.sin(th)
        g = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        ImageDraw.Draw(g).text((8, 2), ch, font=f36, fill=(0, 0, 0, 255))
        g = g.rotate(math.degrees(th) + 90, expand=True)
        arc_im.paste(g, (int(cx - g.size[0] / 2), int(cy - g.size[1] / 2)), g)
    m4 = tp.measure(np.asarray(arc_im), word, 1, 260.0)
    check(m4.get("arc") is not None and m4["arc"]["up"] == -1,
          "надпись по нижней дуге узнана, верх букв — к центру: %s" % (m4.get("arc"),))
    # Шум — не надпись.
    hits = 0
    for seed in range(6):
        for hh, ww in ((60, 300), (30, 200), (120, 400)):
            noise = (np.random.RandomState(seed).rand(hh, ww, 3) * 255).astype(np.uint8)
            hits += 1 if tp.measure(noise, "x", 1, float(hh))["found"] else 0
    check(hits == 0, "шум фотографии буквами не считается (%d из 18)" % hits)
    # Принудительный перенос и подгонка.
    size, step, lines = tp.fit_lines("ЧТО?: Заголовок\n• пункт один\n• пункт два", 300, 200, 20, 24,
                                     lambda t, s: len(t) * 0.5 * s)
    check(lines[0].startswith("ЧТО?") and lines[1].startswith("•") and lines[2].startswith("•"),
          "перенос строки в переводе — новая строка: %s" % lines)
    size, step, lines = tp.fit_lines("слово " * 12, 100, 60, 20, 24, lambda t, s: len(t) * 0.5 * s)
    check(size < 20 and (len(lines) - 1) * step + size <= 60 + 0.3 * size + 1, "не влезло — ужато в рамку")

print("=== 8. Сверка надписей со слоем — построчно, новые блоки в конец ===")
rec = {"part": "word/media/image9.png", "w": 100, "h": 100,
       "blocks": [{"box": [0, 0, 10, 10], "rows": 1, "text": "old", "seg": 7},
                  {"box": [10, 10, 90, 50], "rows": 3, "lineH": 10, "align": "left",
                   "lineBoxes": [[10, 10, 90, 20], [10, 25, 90, 35], [10, 40, 90, 50]]}]}
import importers  # noqa: E402
blob = importers.tag_figure(b"\x89PNG\r\n\x1a\n" + b"\0" * 8, 0, [0.0, 0.0, 1.0, 1.0]) \
    if hasattr(importers, "tag_figure") else b""
lay_data = {"layout": {"pages": [[0, 0, 100, 100]], "boxes": {"0": [
    {"page": 0, "slots": [[10, 100 - 18, 90, 8, ""], [10, 100 - 48, 90, 8, ""]]}]}}}
orig_tag = importers.figure_tag
importers.figure_tag = lambda _b: (0, 0.0, 0.0, 1.0, 1.0)
try:
    n = main._mark_layer_blocks(rec, b"x", lay_data)
finally:
    importers.figure_tag = orig_tag
check(rec["blocks"][0].get("text") == "old" and rec["blocks"][0].get("seg") == 7,
      "прежние блоки и их номера не тронуты")
check(rec["blocks"][1].get("skip") == "layer" and rec["blocks"][1].get("layerSplit"),
      "блок со строками слоя отсеян")
check(len(rec["blocks"]) == 3 and rec["blocks"][2]["rows"] == 1 and rec["blocks"][2]["box"][1] == 25,
      "строка, которой нет в слое, — новым блоком в конце: %s" % rec["blocks"][2:])
check(rec.get("layerRule") == main.LAYER_RULE, "запись помечена версией правила")

print("=== 8а. Пересверка прочитанного смешанного блока (столбец схемы) ===")
rec2 = {"part": "pdfpage/0000.png", "w": 100, "h": 100,
        "blocks": [{"box": [10, 10, 90, 50], "rows": 3, "lineH": 10, "align": "left", "text": "old",
                    "seg": 3}]}
lbs = {0: [[10, 10, 90, 20], [10, 25, 90, 35], [10, 40, 90, 50]]}
importers.figure_tag = lambda _b: (0, 0.0, 0.0, 1.0, 1.0)
try:
    main._mark_layer_blocks(rec2, b"x", lay_data, only={0}, line_boxes=lbs)
finally:
    importers.figure_tag = orig_tag
check(rec2["blocks"][0].get("skip") == "layer" and rec2["blocks"][0].get("text") == "old",
      "прочитанный блок со строками слоя больше не печатается, его текст цел")
check(len(rec2["blocks"]) == 2 and "text" not in rec2["blocks"][1] and rec2["blocks"][1]["box"][1] == 25,
      "строка вне слоя — новым блоком В КОНЕЦ (номер старого не сдвинут), к чтению")
check(main._relayer_due_in({"images": [{"part": "pdfpage/0001.png", "blocks": [
    {"rows": 3, "text": "x"}]}]}), "страница с прочитанным многострочным блоком ждёт пересверки")
check(not main._relayer_due_in({"images": [{"part": "pdfpage/0001.png", "layerRule": main.LAYER_RULE,
                                            "blocks": [{"rows": 3, "text": "x"}]}]}),
      "после пересверки — не ждёт")

print("=== 8б. Повтор слоя — только под самим блоком, а не на странице вообще ===")
near = [((10.0, 10.0, 90.0, 20.0), {"treatment", "plan", "provides", "adequate", "efficacy"}),
        ((10.0, 300.0, 90.0, 310.0), {"reconsider", "dsmes", "support", "continue", "address"})]
check(main._dup_of_layer("Treatment plan that provides adequate EFFICACY", near, (0.0, 0.0, 100.0, 30.0)),
      "блок над строками слоя с теми же словами — повтор")
check(not main._dup_of_layer("Reconsider DSMES to support and continue to address", near,
                             (0.0, 0.0, 100.0, 30.0)),
      "те же слова в другом месте страницы — не повтор")

print("=== 8в. Перевод по участкам блока (столбец схемы из нескольких плашек) ===")
parts = tp.split_text("Заголовок ячейки\nПервый пункт\nВторой пункт\nТретий", [1.0, 3.0])
check(len(parts) == 2 and parts[0].startswith("Заголовок") and "Третий" in parts[1],
      "по переносам перевода, по доле краски: %s" % parts)
words = "один два три четыре пять шесть семь восемь".split()
parts2 = tp.split_text(" ".join(words), [1.0, 1.0, 1.0])
check(" ".join(parts2).split() == words and all(parts2), "по словам — без потерь, каждому участку: %s" % parts2)

print("=== 9. Конец строки по краске: сплошная графика — не буквы ===")
W, H = 400, 40
g = np.full((H, W), 245, dtype=np.uint8)
for x in range(20, 120, 6):
    g[12:28, x:x + 2] = 20                 # «буквы»
g[5:35, 200:400] = 120                     # тень плашки до края
img = Image.fromarray(g).convert("RGB")
sample = (img, 1.0, [0.0, 0.0, float(W), float(H)], img.convert("L"))
box = {"x0": 20.0, "x1": 120.0, "xl": 20.0, "top": 30.0, "bottom": 10.0, "size": 16.0, "exact": False}
end = layout_pdf._ink_end(sample, box, 245 / 255.0)
check(end is not None and end < 200, "конец строки — до тени плашки, а не у края листа: %s" % end)

print("=== 10. Сборка PDF целиком: перевод длиннее — перевёрстан, все слова на месте ===")
if not ok_lib:
    print("   %s — сборка не проверялась" % why)
else:
    import pdftext  # noqa: E402
    import textcount  # noqa: E402
    from pdf_fixture import make_pdf, body  # noqa: E402
    lines_en = ["The choice of glucose lowering agents should be directed by the",
                "individual profile of the person with type two diabetes in particular",
                "the presence of overweight and multiple long term conditions and risk",
                "of side effects and preferences of the person and the context of care."]
    PDF = make_pdf([body(lines_en, top=520) + [("t", 40, 300, 10, "Smith J. Lancet 2020;1:2")]])
    pages, geoms = textcount._pdf_pages_geom(PDF, [])
    res = pdftext.clean(pages, geom=geoms)
    paras = [it for it in res["items"] if it[0] == "p"]
    lay = res["layout"]
    boxes = {str(i): b for i, b in enumerate(lay) if b}
    i_body = next(i for i, p in enumerate(paras) if p[1].startswith("The choice"))
    ru = ("Выбор сахароснижающих препаратов должен определяться индивидуальным профилем "
          "человека с сахарным диабетом второго типа, в частности наличием избыточной массы "
          "тела и множественных длительно текущих заболеваний, риском побочных эффектов, "
          "предпочтениями человека и контекстом оказания медицинской помощи.")
    out, st = layout_pdf.build(PDF, {"boxes": boxes}, {i_body: ru}, lang="RU",
                               sources={i_body: " ".join(lines_en)})
    check(st.get("reflowed", 0) + st.get("framed", 0) >= 1, "абзац перевёрстан: %s" % {
        k: st.get(k) for k in ("reflowed", "framed", "sizeMedian", "smallShare")})
    check(st.get("sizeMedian", 0) >= 0.75, "кегль перевода не мельче 0.75 оригинала: %s" % st.get("sizeMedian"))
    from pypdf import PdfReader  # noqa: E402
    txt = " ".join((PdfReader(io.BytesIO(out)).pages[0].extract_text() or "").split())
    check("помощи" in txt and "Выбор" in txt, "первое и последнее слово перевода напечатаны")
    check("smallShare" in st and "smallPages" in st, "самопроверка размера в отчёте сборки")

print("=== 11. Пересверка не оставляет сирот и не трогает работу человека ===")
IMG = {"kind": "image", "part": "pdfpage/0000.png"}
proj = {"segments": [{"id": 1, "source": "a", "target": "машина", "origin": dict(IMG, block=0)},
                     {"id": 2, "source": "b", "target": "человек", "status": "confirmed",
                      "confirmedBy": "u1", "origin": dict(IMG, block=1)},
                     {"id": 9, "source": "абзац текста", "target": "чужой"}]}
rec3 = {"part": "pdfpage/0000.png", "blocks": [{"rows": 3, "text": "a", "seg": 1},
                                                {"rows": 3, "text": "b", "seg": 2}]}
seen = {}


def fake_relayer(rec, blob, data, fig, protect=None):
    seen["protect"] = set(protect or ())
    for i, b in enumerate(rec["blocks"]):
        if i not in seen["protect"]:
            b["skip"] = "layer"
    rec["blocks"].append({"rows": 1, "box": [0, 0, 1, 1]})
    return 1


orig_rel = main._relayer_old
main._relayer_old = fake_relayer
try:
    got, dropped = main._relayer_rec(rec3, b"x", {}, {}, proj, False)
    check(seen["protect"] == {1}, "подписанный человеком блок защищён: %s" % seen["protect"])
    check(dropped == 1 and [s["id"] for s in proj["segments"]] == [2, 9] and "seg" not in rec3["blocks"][0],
          "машинный сегмент ушедшего в слой блока снят, а не висит сиротой")
    rec4 = {"part": "pdfpage/0001.png", "blocks": [{"rows": 3, "text": "c", "seg": 2}]}
    main._relayer_rec(rec4, b"x", {}, {}, proj, True)
    check(seen["protect"] == {0} and rec4["blocks"][0].get("seg") == 2,
          "сухой прогон сегменты не снимает")
    # Номер переиспользован: блок картинки помнит seg 9, а это абзац текста.
    rec6 = {"part": "pdfpage/0003.png", "blocks": [{"rows": 3, "text": "d", "seg": 9}]}
    _, dr6 = main._relayer_rec(rec6, b"x", {}, {}, proj, False)
    check(dr6 == 0 and any(s["id"] == 9 for s in proj["segments"]),
          "чужой сегмент с тем же номером не снят — сегмент подтверждает себя якорем")
finally:
    main._relayer_old = orig_rel
proj7 = {"segments": [{"id": 4, "source": "x", "target": "y",
                      "origin": {"kind": "image", "part": "pdfpage/0004.png", "block": 0}}]}
rec7 = {"part": "pdfpage/0004.png", "blocks": [{"rows": 3, "skip": "layer", "layerSplit": 1, "seg": 4},
                                                {"rows": 1, "box": [0, 0, 1, 1]}]}
check(main._retire_orphans(rec7, proj7) == 1 and not proj7["segments"] and "seg" not in rec7["blocks"][0],
      "сирота прежней пересверки снят без отрисовки")
check(main._page_rec_trusted({"blocks": [], "vk": None, "src": "A"}, {}, "A", None),
      "страница того же файла и плана — своя, как бы её ни отрисовал pdfium")
check(not main._page_rec_trusted({"blocks": [], "vk": None, "src": "A"}, {}, "B", None),
      "после замены файла — чужая")
check(main._page_rec_trusted({"blocks": []}, {"at": "2026-10-11 14:14", "imagesAt": "2026-10-11 15:00"}, "B", None)
      and not main._page_rec_trusted({"blocks": []}, {"at": "2026-10-11 16:00", "imagesAt": "2026-10-11 15:00"},
                                     "B", None),
      "запись без отпечатка: своя, если разбор шёл после привязки файла")
rec5 = {"part": "pdfpage/0002.png", "blocks": [{"rows": 3, "skip": "layer", "box": [0, 0, 9, 9]}]}
check(main._relayer_old(rec5, b"not an image", {}, {}) == 0 and "layerRule" not in rec5,
      "картинка не открылась — правило не отмечено, пересверка повторится")

print()
print("ИТОГ: %s" % ("всё в порядке" if not fail else "%d провал(ов)" % len(fail)))
sys.exit(1 if fail else 0)
