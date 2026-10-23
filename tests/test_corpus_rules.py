# -*- coding: utf-8 -*-
"""Правила раздела Ш (корпус выгрузки 23.10.2026) на файлах самого корпуса.

    python tests/test_corpus_rules.py

Файлы строит `tools/corpus_build.py` (те же рецепты, что гоняются через
боевой API), разбор — настоящий `importers.to_docx`. Проверяется ТЕКСТ
абзацев собранного документа: из него рождаются строки проекта, и ошибка
склейки — это перевод полуфраз.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
sys.path.insert(0, "tools")
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
    import reportlab  # noqa: F401
    import pypdf  # noqa: F401
    from docx import Document
except ImportError as e:            # pragma: no cover
    print("ПРОПУЩЕН: нет модуля (%s)" % e)
    sys.exit(0)

import corpus_build as C  # noqa: E402
import importers  # noqa: E402
import pdftext  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="corpus_rules_"))


def paras(fn, name):
    p = TMP / (name + ".pdf")
    fn(p)
    r = importers.to_docx(p.name, p.read_bytes())
    d = Document(io.BytesIO(r["docx"]))
    return [x.text for x in d.paragraphs if x.text.strip()]


def has_para(ps, start, end):
    return any(x.startswith(start) and x.rstrip().endswith(end) for x in ps)


print("=== 1. Ш1+Ш2: проза с выключкой, слово — оператор ===")
ps = paras(C.pdf_prose, "prose")
for k, para in enumerate(C.PROSE):
    first = para.split(". ")[0]
    check("абзац %d целиком одной строкой проекта" % (k + 1),
          any(x.startswith(first[:25]) and x.endswith(para[-20:]) for x in ps), ps)
check("абзацев прозы ровно 4 (+заголовок и колонтитулы)",
      sum(1 for x in ps if len(x) > 120) == 4, [len(x) for x in ps])

print("=== 2. Ш1: газета в три колонки, выключка узкой колонки ===")
ps = paras(C.pdf_newspaper, "news")
for col in C.NEWS_COLS[1:]:
    check("колонка «%s…» — один абзац" % col[:20], col in ps or any(col[:60] in x and col[-25:] in x for x in ps), ps)
check("первая колонка с буквицей — один абзац",
      any(x.startswith("Первые машины") and "четырёх часов" in x for x in ps), ps)
check("слова колонок не перемешаны", not any(len(x.split()) <= 2 and x[:1].islower() for x in ps), ps)

print("=== 3. Ш1: статья в две колонки ===")
ps = paras(C.pdf_article, "article")
check("«Введение…» — один абзац до «…препаратах.»",
      has_para(ps, "Введение.", "в препаратах."), ps)
check("«Методы…» — один абзац", any(x.startswith("Методы.") and "ммоль·ч/л" in x for x in ps), ps)

print("=== 4. Ш3/Ш3б: стихи строка в строку ===")
ps = paras(C.pdf_verse, "verse")
for st in C.POEM:
    for ln in st:
        check("строка стиха «%s» — своя строка" % ln[:20], ln in ps, ps)

print("=== 5. Ш4+Ш5: меню ===")
ps = paras(C.pdf_menu, "menu")
check("отточий в тексте нет", not any(set(x) <= set(". ") for x in ps), ps)
check("описание блюда не склеено со следующим названием",
      "с бараниной и нутом" in ps and "Лагман" in ps, ps)

print("=== 6. Ш4: имя в сертификате отдельно от текста ===")
ps = paras(C.pdf_cert, "cert")
check("имя — своя строка", C.CERT["name"] in ps, ps)
check("текст под именем — своя строка", any(x.startswith("успешно завершила") for x in ps), ps)

print("=== 7. Ш2: «8.» в начале строки после переноса — не пункт ===")
ps = paras(C.pdf_brochure, "brochure")
check("«…ул. Лесная, 8. Трансфер…» — один абзац",
      any("Лесная, 8. Трансфер" in x for x in ps), ps)

print("=== 8. Ш1 не склеивает ячейки таблицы и колонки ===")
ps = paras(C.pdf_invoice, "invoice")
check("ячейка «Доставка по городу» не слита с соседней", "Доставка по городу" in ps, ps)
check("число «7 000,00» — своя ячейка", "7 000,00" in ps, ps)
ps = paras(C.pdf_en_guide, "guide")
check("ячейки таблицы раздельно", "Heating" in ps and "5–30 °C" in ps, ps)

print("=== 9. Ш5: строка-отточие снимается, текст с точками — нет ===")
from collections import Counter  # noqa: E402
check("«..........» — не текст", pdftext._clean_line("..........", Counter()) is None)
check("«— — — —» — не текст", pdftext._clean_line("— — — —", Counter()) is None)
check("«Итого...» — текст", pdftext._clean_line("Итого...", Counter()) == "Итого...")

print("=== 10. выключатели ===")
check("RULES_VERSION поднят до 21+", pdftext.RULES_VERSION >= 21)

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
