"""Правила раздела «Ш» (корпус выгрузки, 23.10.2026) — картинки, стирание
и перевод. Модель не зовётся; LaMa и детектор — только если стоят.

  Ш7   строки чтения картинки ложатся на рамки строк, разрыв — по правилам
       (размер, заглавные подряд, конец предложения), части блока;
  Ш11  варианты через «/» без пробелов и пояснения в скобках сверх оригинала;
  Ш12  нормализация орфографии языка перевода данными (`normalize`);
  Ш16  перевод пробега html раскладывается по его текстовым узлам;
  Ш21  пропущенная строка колонки — по половинному перекрытию, у ближайшей
       сверху цепочки, и место, накрывающее найденную строку, занято;
  Ш22  LaMa получает дыру закрытой и в отражённом поле тоже;
  Ш23  наклон страницы — коротким строкам без своего замера.
"""
import os
import sys
import types

sys.stdout.reconfigure(encoding="utf-8")


class FakeClient:
    def __init__(self, *a, **k):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def create(self, **kw):
        raise RuntimeError("модель в этом наборе не зовётся")


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
os.environ.setdefault("APP_PASSWORD", "x")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
import main  # noqa: E402
import image_text  # noqa: E402
import importers  # noqa: E402

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("ок  " if cond else "ПРОВАЛ  ") + label)
    if not cond:
        fail.append(label)


# ── Ш7: строки чтения и части блока ──
lbs = [[10, 10, 300, 30], [10, 40, 120, 60], [10, 70, 300, 90]]
t, brk = image_text.read_lines("Balance\n12 450.00\nTotal paid today", lbs)
check("\n" in t, "Ш7: строки чтения по числу рамок сохраняют разрывы")
t2, brk2 = image_text.read_lines("one two\nthree", lbs)
check(brk2 == [] and "\n" not in t2, "Ш7: число строк разошлось — как прежде, пробелом")
item = {"box": [10, 10, 300, 90], "lineBoxes": lbs, "rows": 3, "lineH": 20,
        "text": "Balance\nPaid today, thanks", "src": "Баланс\nОплачено сегодня, спасибо",
        "breaks": [0]}
parts = image_text.split_parts(item)
check(len(parts) == 2 and parts[0]["text"] == "Balance" and parts[1]["rows"] == 2,
      "Ш7: блок с разрывом — две части в своих строках")
check(all(p.get("blkItem") is parts[0]["blkItem"] for p in parts),
      "Ш19: части несут один блок для общего замера вида печати")
check(image_text.split_parts(dict(item, text="Balance Paid today")) == [dict(item, text="Balance Paid today")],
      "Ш7: разрывов в переводе нет — блок одной частью")

# ── Ш11: склеенные варианты и пояснения в скобках ──
seg = {"source": "Чайхана у дороги", "target": "Chaikhana (Teahouse) by the road"}
check(main._paren_misses(seg) and main._paren_misses(seg)[0]["kind"] == "addon",
      "Ш11: пояснение в скобках сверх оригинала — находка")
check(main._paren_misses({"source": "уровень (HbA1c) высокий", "target": "high (HbA1c) level"}) == [],
      "Ш11: скобка оригинала — не находка")
check(main._paren_misses({"source": "Анализ", "target": "Analysis (2024)"}) == [],
      "Ш11: в скобке нет букв — не находка")
v = main._variant_misses({"source": "бригады", "target": "brigades/teams"})
check(bool(v), "Ш11: варианты через «/» без пробелов — находка")
check(main._variant_misses({"source": "и или", "target": "and/or"}) == [],
      "Ш11: короткое «and/or» — законное написание")
check(main._variant_misses({"source": "мг/кг", "target": "mg/kg"}) == [],
      "Ш11: черта в оригинале — не находка")
check("addon" in main.REVIEW_FREE_KEYS and "addon" in main.REVIEW_VETO_LABELS,
      "Ш11: пояснения — бесплатный счётчик ревизии с подписью вето")

# ── Ш30б: число строк ──
_img = {"origin": {"kind": "image"}}
check(main._lines_misses(dict(_img, source="Министерство\nУправление кадров", target="Ministry Personnel"))
      and main._lines_misses({"source": "Министерство\nУправление", "target": "Ministry"}) == []
      and main._lines_misses(dict(_img, source="А\nБ", target="A\nB")) == []
      and main._lines_misses({"source": "Одна строка", "target": "One\nline"}) == [],
      "Ш30б: строки оригинала слиты в переводе — находка; в одну строку — проверять нечего")
check("lines" in main.REVIEW_FREE_KEYS and "lines" in main.REVIEW_VETO_LABELS,
      "Ш30б: число строк — бесплатный счётчик ревизии с подписью вето")
_sys = main._translate_system("RU", "EN", [], {}, False, "general",
                              main._resolve_model(None))
_lit = main._translate_system("RU", "EN", [], {}, True, "general",
                              main._resolve_model(None))
check("TRANSLITERATED" in _sys and "kopecks stay kopecks" in _sys and "SAME number of lines" in _sys
      and "TRANSLITERATED" not in _lit,
      "Ш30: правила имён, валюты и строк — в прямом переводе, не в обратном")

# ── Ш29: «надпечатка» в колонке документа ──
bl = [{"box": [26, 102, 106, 128], "lineH": 26, "text": "Главная"},
      {"box": [27, 155, 96, 178], "lineH": 23, "text": "Заказы"},
      {"box": [27, 207, 110, 231], "lineH": 24, "text": "Платежи"},
      {"box": [26, 259, 129, 336], "rows": 2, "text": "Настройки Выход", "skip": "overlay"},
      {"box": [26, 360, 120, 384], "lineH": 24, "text": "Помощь"},
      {"box": [400, 420, 560, 444], "lineH": 24, "text": "KV 120 MA 283", "skip": "overlay"},
      {"box": [600, 20, 700, 40], "lineH": 20, "text": "KV 120", "skip": "overlay"},
      {"box": [400, 470, 480, 494], "lineH": 24, "text": "X", "skip": "overlay", "by": "human"}]
check(main._overlay_column_fix(bl) == 1 and not bl[3].get("skip") and bl[5]["skip"] == "overlay"
      and bl[6]["skip"] == "overlay" and bl[7]["skip"] == "overlay",
      "Ш29: пункты меню в колонке текста — документ; надпечатка в стороне и решение человека — как были")

# ── Ш31: рамки одной видимой строки — одна ──
rb = image_text.row_boxes([[100, 3, 656, 54], [662, 29, 735, 58], [107, 109, 660, 167]])
check(len(rb) == 2 and rb[0][2] == 735, "Ш31: кусок перекошенной строки («P.01») — та же строка")
check(len(image_text.row_boxes([[10, 10, 100, 30], [10, 40, 100, 60]])) == 2,
      "Ш31: строки одна под другой не сводятся")

# ── Ш28: кегль частей блока и однострочных одного класса ──
blk = {"x": 1}
pms_ = [{"em": 20.0, "m": {}}, {"em": 21.0, "m": {}}, {"em": 9.0, "m": {}}, {"em": 20.5, "m": {}}]
its_ = [{"rows": 1, "blkItem": blk} for _ in pms_]
image_text._single_even(pms_, its_, {})
check(pms_[2]["em"] >= 20.0, "Ш28: часть блока с кеглем вдвое меньше соседних — кегль соседних")

# ── Ш27: дуга — у всей надписи ──
try:
    import numpy as np
    import text_paint as tp
    from PIL import Image as _Im, ImageFont
    arr_ = np.asarray(_Im.new("RGB", (120, 40), "white"))
    from PIL import ImageDraw as _D
    im_ = _Im.new("RGB", (140, 40), "white")
    _D.Draw(im_).text((6, 8), "Лим В. О.", font=ImageFont.truetype(tp._ref_font_path(), 20), fill="black")
    m_ = tp.measure(np.asarray(im_), "Лим В. О.", 1, 28)
    check(not m_.get("arc"), "Ш27: прямая строка с инициалами — не дуга")
except Exception as e:
    print("—   Ш27: замер не вышел (%s), пропущено" % e)

# ── Ш12: нормализация узбекских апострофов ──
n = main._lang_normalize("bo‘tqa yoʻl g'isht ma'no", "UZ")
check("boʻtqa" in n and "gʻisht" in n and "maʼno" in n, "Ш12: oʻ/gʻ — ʻ, прочий апостроф — ʼ")
check(main._lang_normalize("don't", "EN") == "don't", "Ш12: язык без правила — текст как есть")

# ── Ш16: html пробег по узлам ──
raw = 'Read <a href="/x">the full report</a> today'
out = importers._html_inline_write(raw, "Прочтите полный отчёт сегодня", main._split_target)
check('<a href="/x">' in out and "</a>" in out and "Прочтите" in out and "сегодня" in out,
      "Ш16: ссылка внутри пробега остаётся на месте")
out1 = importers._html_inline_write("<b>Hello</b>", "Привет", main._split_target)
check(out1 == "<b>Привет</b>", "Ш16: один узел — перевод в нём, теги вокруг целы")

# ── Ш21: пропущенная строка колонки ──
boxes = [[117, 185, 267, 221], [214, 314, 947, 358], [105, 604, 460, 655],
         [287, 743, 990, 797], [164, 880, 972, 936], [117, 1026, 792, 1079]]
slots = image_text.gap_slots(boxes)
check(any(abs(s[1] - 460) < 20 for s in slots), "Ш21: строка между 314 и 604 — место найдено")
check(not any(s[1] < 300 for s in slots), "Ш21: место, накрывающее «Дорогая Анна!», занято")
check(image_text.gap_slots(boxes[:4]) == [], "Ш21: четыре строки — колонки нет")

# ── Ш22: LaMa видит дыру закрытой ──
try:
    import numpy as np
    import paint_lama as pl
    have_lama = pl.available()
except Exception:
    have_lama = False
if have_lama:
    rgb = np.full((40, 200, 3), 220, np.uint8)
    rgb[12:28, 20:180] = 30                      # тёмная полоса — «буквы»
    hole = np.zeros((40, 200), bool)
    hole[8:32, 15:185] = True
    res = pl.inpaint(rgb, hole)
    check(res is not None and float(res[hole].mean()) > 150,
          "Ш22: LaMa не дорисовывает буквы из дыры и из отражённого поля")
else:
    print("—   Ш22: LaMa не стоит, пропущено")

# ── Ш23: наклон страницы короткой строке ──
try:
    import text_paint as tp
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (220, 60), "white")
    f = ImageFont.truetype(tp._ref_font_path(), 28)
    ImageDraw.Draw(im).text((10, 10), "OK", font=f, fill="black")
    rgb = np.asarray(im)
    m0 = tp.measure(rgb, "OK", 1, 40)
    m1 = tp.measure(rgb, "OK", 1, 40, angle_hint=6.0)
    check(m1["angle"] == 6.0 and m1.get("angleFrom") == "page" and not m0.get("angleFrom"),
          "Ш23: строка без своего наклона берёт наклон страницы")
except Exception as e:
    print("—   Ш23: замер не вышел (%s), пропущено" % e)

print("\nВСЁ ПРОШЛО" if not fail else "\nПРОВАЛЫ: %d" % len(fail))
sys.exit(1 if fail else 0)
