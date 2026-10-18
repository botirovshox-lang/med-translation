"""Каталог документов и правил (`backend/doc_catalog`, `tools/catalog_report.py`).

Сторожит: данные целы (поля, уникальные id, допустимые группы и уровни),
каждое правило в `handled_by` есть в справочнике `docs/rules/pdf-reading.md`,
пути `data` и тесты договора форматов существуют, страница покрытия
`docs/rules/catalog.md` собрана из нынешних данных. Правила справочника без
записи в каталоге — не провал, а строка отчёта (иначе их привязали бы для
галочки).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "tools")
import catalog_report as cr                                   # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


el, fam, fmt = cr.load()
idx = cr.rule_index()
print("── 1. справочник правил ──")
check(len(idx) >= 160, "правил в справочнике: %d" % len(idx))
check("Х19" in idx and "Т28" in idx, "заголовок «Т27–Т28» даёт оба номера, свежие правила видны")
check(any(idx[i]["tests"] for i in idx), "у правил найдены тесты")

print("\n── 2. данные ──")
EL_G = {"text", "heading", "note", "running", "graphic", "table", "math", "form", "special", "genre"}
FA_G = {"encoding", "shaping", "fonts", "spacing", "breaking", "justification", "punctuation", "direction",
        "decoration", "annotation", "lists", "page", "measure", "image-paint", "pdf-layer"}
for name, rows, groups in (("elements", el["elements"], EL_G), ("families", fam["families"], FA_G)):
    ids = [r["id"] for r in rows]
    check(len(ids) == len(set(ids)), "%s: id уникальны (%d)" % (name, len(ids)))
    bad = [r["id"] for r in rows if r.get("group") not in groups]
    check(not bad, "%s: группы из списка %s" % (name, bad[:5]))
    bad = [r["id"] for r in rows if r.get("scope") not in ("in", "deferred", "out")]
    check(not bad, "%s: scope in/deferred/out %s" % (name, bad[:5]))
    bad = [(r["id"], h) for r in rows for h in r.get("handled_by") or [] if h not in idx]
    check(not bad, "%s: правила handled_by есть в справочнике %s" % (name, bad[:5]))
    bad = [r["id"] for r in rows if (r.get("scope") in ("deferred", "out")) and not (r.get("why") or "").strip()]
    check(not bad, "%s: у отложенного и чужого названа причина %s" % (name, bad[:5]))
    bad = [r["id"] for r in rows if not r.get("desc")]
    check(not bad, "%s: описание есть %s" % (name, bad[:5]))
bad = [r["id"] for r in fam["families"] if r.get("data") and not Path(r["data"]).exists()]
check(not bad, "families: файлы данных существуют %s" % bad)

print("\n── 3. договор форматов ──")
tiers = set(fmt["tiers"])
check(tiers == {"T1", "T2", "T3", "T4"}, "уровни T1–T4")
for f in fmt["formats"]:
    check(f["tier"] in tiers and f.get("identical") and isinstance(f.get("losses"), list),
          "%s: уровень, определение «тот же», потери" % f["id"])
    miss = [t for t in f.get("tests") or [] if not Path(t).exists()]
    check(not miss, "%s: тесты существуют %s" % (f["id"], miss))
    bad = [h for h in f.get("rules") or [] if h not in idx]
    check(not bad, "%s: правила существуют %s" % (f["id"], bad))
exts = [e for f in fmt["formats"] for e in f["ext"]]
sys.path.insert(0, "backend")
import importers                                              # noqa: E402
sup = set(getattr(importers, "SUPPORTED_EXT", []) or [])
gap = sorted(e for e in sup if e not in exts)
check(not gap, "каждый поддерживаемый формат есть в договоре: %s" % gap)

print("\n── 4. страница покрытия ──")
cur = cr.OUT.read_text(encoding="utf-8") if cr.OUT.exists() else ""
check(cur == cr.render(idx), "docs/rules/catalog.md собрана из нынешних данных (python tools/catalog_report.py)")
st = {}
for r in el["elements"] + fam["families"]:
    s = cr.status(r, idx)
    st[s] = st.get(s, 0) + 1
print("    статусы:", st)
used = {h for r in el["elements"] + fam["families"] for h in r.get("handled_by") or []}
print("    правила без записи в каталоге:", " ".join(sorted(set(idx) - used)) or "нет")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
