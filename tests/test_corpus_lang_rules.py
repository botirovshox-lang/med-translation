# -*- coding: utf-8 -*-
"""Правила Ш34–Ш39 (матрица языков 23.10.2026) — без сети и без модели.

    python tests/test_corpus_lang_rules.py

Ш34 цвет строки — разрыв в надписи картинки; Ш35 линия ячейки — не
свободная бумага, иероглифы — не моноширинный; Ш36 названия, коды
и знаки валюты оригинала — неприкосновенны, двойники букв чинятся без
модели, ремонт не вносит вариантов и пояснений; Ш37 вторая строка
за счёт плашки над строкой; Ш38 поле бланка «______» переживает перевод;
Ш39 пункт колонки не растёт влево; вязь не разрядкой.
"""
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
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
except ImportError:                 # pragma: no cover
    print("ПРОПУЩЕН: нет numpy")
    sys.exit(0)

import image_text  # noqa: E402
import layout_pdf as L  # noqa: E402
import pdftext  # noqa: E402
import main  # noqa: E402

print("=== Ш34: строка другого цвета — разрыв надписи ===")
arr = np.full((60, 200, 3), 255, np.uint8)
arr[5:15, 10:150] = (20, 20, 20)        # чёрная строка
arr[25:35, 10:150] = (200, 30, 30)      # красная строка
boxes = [(10, 5, 150, 15), (10, 25, 150, 35)]
inks = image_text.line_inks(arr, boxes)
check("цвет каждой строки измерен", len(inks) == 2 and all(inks), inks)
_t, br = image_text.read_lines("Осторожно\nвысокое напряжение", boxes, inks=inks)
check("смена цвета — разрыв после первой строки", br == [0], br)
_t, br = image_text.read_lines("Осторожно\nвысокое напряжение", boxes, inks=[inks[0], inks[0]])
check("тот же цвет — одна фраза", br == [], br)

print("=== Ш35: линия ячейки и иероглифы ===")
reg = np.full((20, 40, 3), 255, np.uint8)
check("пустая бумага — без линии", not image_text._hline_in(reg))
reg[10, :] = 0
check("горизонтальная линия найдена", image_text._hline_in(reg))
check("китайский текст — CJK", image_text._cjk_share("银行通知") == 1.0)

print("=== Ш36: названия, коды, валюта, двойники ===")


def miss(src, tgt):
    return main._ident_misses({"source": src, "target": tgt})


check("название латиницей в русском — в переводе как есть",
      miss("Приложение BANK·ONE", "Ilova БАНК·УАН") != [])
check("код модели «T200» сохранён — находки нет", miss("Модель T200", "Model T200") == [])
check("знак ₽ заменён словом — находка", miss("Цена 420 ₽", "Narxi 420 som") != [])
check("знак ₽ на месте — чисто", miss("Цена 420 ₽", "Narxi 420 ₽") == [])
check("двойник «Т200» с кириллической Т — назад латиницей",
      main._homoglyph_fix("Модель T200", "Модель Т200") == "Модель T200")
check("слово, не код, не трогается", main._homoglyph_fix("Модель T200", "Тема") == "Тема")

print("=== Ш38: поле бланка ===")
check("«______» потеряно в переводе — находка",
      any("______" in f["text"] for f in miss("Подпись ______", "Imzo")))
check("строка с полем бланка не снимается как отточие",
      "______" in (pdftext._clean_line("Подпись _______________", __import__("collections").Counter()) or ""))

_C = __import__("collections").Counter()
check("после конца фразы черта — мусор скана, не поле (книга 8)",
      "_" not in (pdftext._clean_line("Сытая пчела не ужалит яд. ______", _C) or ""))
check("после одиночной буквы — мусор", "_" not in (pdftext._clean_line("умаления.Ч ______ У", _C) or ""))

print("=== Ш37 / Ш39: плашка сверху, край колонки, вязь ===")
sls = [{"x": 60.0}, {"x": 60.2}, {"x": 59.9}, {"x": 200.0}]
L._mark_column_edges(sls)
check("три строки с одним краем — колонка", all(sd.get("_colEdge") for sd in sls[:3]))
check("одиночная строка — не колонка", not sls[3].get("_colEdge"))
check("арабский — связное письмо (без разрядки)", L._connected_script("مرحبا"))
check("латиница — не связное", not L._connected_script("Hello"))
check("выключатель плашки сверху есть", hasattr(L, "FREE_ABOVE"))

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
