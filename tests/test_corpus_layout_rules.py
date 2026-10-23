# -*- coding: utf-8 -*-
"""Правила Ш40–Ш44 (матрица языков 23.10.2026): меню с отточием, счёт с
линиями таблицы — сквозной выгрузкой «как в оригинале» и приёмкой.

    python tests/test_corpus_layout_rules.py

Файлы строит `tools/corpus_build.py`, переводы — НАСТОЯЩИЕ, снятые с прогона
матрицы (`tests/fixtures/corpus_real_translations.json`), выгрузку и приёмку
делает `tools/corpus_offline.py` без сети и без вызовов модели.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "tools")
sys.path.insert(0, "backend")   # backend первым: в tools есть свой export_qa.py
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
    import numpy  # noqa: F401
    import pypdfium2  # noqa: F401
except ImportError as e:            # pragma: no cover
    print("ПРОПУЩЕН: нет модуля (%s)" % e)
    sys.exit(0)

import corpus_build as C  # noqa: E402
import export_qa  # noqa: E402
import importers  # noqa: E402
import layout_pdf as L  # noqa: E402

FIX = json.loads(Path("tests/fixtures/corpus_real_translations.json").read_text(encoding="utf-8"))
TMP = Path(tempfile.mkdtemp(prefix="corpus_layout_"))
CORP, OUT, REAL = TMP / "c", TMP / "o", TMP / "r"
for d in (CORP, OUT, REAL):
    d.mkdir()
RECIPE = {"L08": C.pdf_menu, "L03": C.pdf_invoice}
MAN = [m for m in FIX["_manifest"] if m["id"][:3] in RECIPE]   # свои файлы фикстуры
for m in MAN:
    random.seed(m["id"][1:3])
    RECIPE[m["id"][:3]](CORP / m["file"])
    (REAL / m["id"]).mkdir()
    (REAL / m["id"] / "segments.json").write_text(json.dumps(FIX[m["id"]], ensure_ascii=False),
                                                   encoding="utf-8")
(CORP / "manifest.json").write_text(json.dumps(MAN, ensure_ascii=False), encoding="utf-8")

print("=== 0. разбор: отточие (Ш40) и синтетический курсив (Ш42) ===")
r = importers.to_docx("menu.pdf", (CORP / "L08_menu_ky.pdf").read_bytes())
lay = r.get("layout") or {}
leaders = lay.get("leaders") or {}
check("места отточий записаны в раскладку", sum(len(v) for v in leaders.values()) >= 5, leaders)
styles = [b.get("style") for bl in (lay.get("boxes") or {}).values()
          for b in (bl if isinstance(bl, list) else [bl])]
check("подписи под блюдами — курсив (наклон Tm)", styles.count("i") >= 5, styles)

print("=== 1. Ш41: строка с отточием или ценой справа — ряд, не история ===")
row = {"x": 60.0, "x1": 140.0, "y": 500.0, "size": 11.5, "page": 0}
price = {"x": 506.0, "x1": 535.0, "y": 500.0, "size": 11.5, "page": 0}
check("цена далеко справа делает строку рядом", L._row_anchor(row, {0: [row, price]}))
check("без соседа — обычная строка", not L._row_anchor(dict(row), {0: [dict(row)]}))
check("отточие делает строку рядом", L._row_anchor(dict(row, _leader={"x0": 150}), {0: []}))
long_ = dict(price, x=300.0, x1=535.0)
check("длинная строка справа — колонка текста, не цена", not L._row_anchor(row, {0: [row, long_]}))

print("=== 2. Ш43: длина для меры кегля — иероглиф за два ===")
check("«茶» = 2, «ab» = 2", export_qa._vlen("茶") == 2.0 and export_qa._vlen("ab") == 2.0)

print("=== 3. сквозная выгрузка и приёмка ===")
p = subprocess.run([sys.executable, "tools/corpus_offline.py", str(CORP), str(OUT), "--real", str(REAL),
                    "--no-detect"], capture_output=True, text=True, encoding="utf-8",
                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
summ = {x["id"]: x for x in json.loads((OUT / "summary.json").read_text(encoding="utf-8"))}
ky = summ["L08_menu_ky"]["counts"]
check("меню KY: приёмка чистая (нет OVERPRINT от отточия, нет SMALL)", not ky, ky)
zh = summ["L08_menu_zh"]["counts"]
check("меню ZH: нет OVERPRINT и SMALL", not zh.get("OVERPRINT") and not zh.get("SMALL"), zh)
qa = json.loads((OUT / "L08_menu_zh.qa.json").read_text(encoding="utf-8"))
dishes = [k for _p, key, k in qa.get("scales", []) if key in ("p2", "p5", "p8")]
check("меню ZH: иероглифы не «крупнее» оригинала по мере (Ш43)",
      dishes and max(dishes) < 1.35, dishes)
inv = summ["L03_invoice_en"]
check("счёт EN: нет вылетов", not inv.get("overflow"), inv)
qa = json.loads((OUT / "L03_invoice_en.qa.json").read_text(encoding="utf-8"))
sc = {key: k for _p, key, k in qa.get("scales", [])}
units = [sc.get(k) for k in ("p12", "p17", "p22") if sc.get(k) is not None]
check("ячейки «Ед.» в рост: сосед за линией таблицы не делит зазор (Ш44)",
      units and min(units) >= 0.8, sc)
check("шапка «Цена» не ужата числом ниже в той же ячейке (Ш44)", sc.get("p8", 1) >= 0.85, sc)

print("=== 4. выключатели ===")
check("LAYOUT_LEADERS читается", hasattr(L, "LEADERS"))

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
