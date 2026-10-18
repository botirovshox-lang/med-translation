"""Каталог «что бывает в документах и какие у набора правила» → страница покрытия.

Источник правды — данные `backend/doc_catalog/*.json` (виды элементов,
семейства правил, договор форматов). Статус записи НЕ пишется руками,
он выводится здесь:

  * covered  — запись в работе, у неё есть наши правила (`handled_by`)
               и хотя бы у одного правила в тексте назван тест;
  * partial  — правила есть, теста при них в справочнике не названо;
  * missing  — запись в работе, правил нет;
  * deferred / out — так решено (`scope`), с причиной в `why`.

Правила и их тесты читаются из `docs/rules/pdf-reading.md`: абзац правила
начинается с «- **Х14.» и идёт до следующего такого абзаца.

    python tools/catalog_report.py           # пишет docs/rules/catalog.md
    python tools/catalog_report.py --check   # код 1, если страница устарела
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAT = ROOT / "backend" / "doc_catalog"
RULES = ROOT / "docs" / "rules" / "pdf-reading.md"
OUT = ROOT / "docs" / "rules" / "catalog.md"

_ID_RE = re.compile(r"^\s*(?:-\s+|#+\s+)?\*\*([А-ЯЁA-Z]{1,2}\d+[a-zа-я]?)(?:[–-]([А-ЯЁA-Z]{1,2})?(\d+))?[.:\s*]")
_TEST_RE = re.compile(r"tests/test_[\w]+\.(?:py|js)")


def load():
    def rd(n):
        return json.loads((CAT / n).read_text(encoding="utf-8"))
    return rd("elements.json"), rd("rule_families.json"), rd("formats.json")


def rule_index(text: str = None) -> dict:
    """{id правила: {"tests": {...}}} из справочника. Тест, названный в абзаце
    правила, — его; тест, названный где угодно в разделе («## …»), сторожит
    все правила раздела («Сторожит tests/… » чаще стоит в конце раздела).
    Заголовок вида «Т27–Т28» даёт оба номера."""
    text = text if text is not None else RULES.read_text(encoding="utf-8")
    idx, cur, sec_ids, sec_tests = {}, [], [], set()

    def close():
        for i in sec_ids:
            idx[i]["tests"] |= sec_tests

    for ln in text.splitlines():
        if ln.startswith("## "):
            close()
            cur, sec_ids, sec_tests = [], [], set()
            continue
        m = _ID_RE.match(ln)
        if m:
            first = m.group(1)
            ids = [first]
            if m.group(3):
                pre = m.group(2) or re.match(r"[А-ЯЁA-Z]+", first).group(0)
                lo = int(re.search(r"\d+", first).group(0))
                ids = ["%s%d" % (pre, n) for n in range(lo, int(m.group(3)) + 1)]
            cur = ids
            for i in ids:
                idx.setdefault(i, {"tests": set()})
                sec_ids.append(i)
        elif ln.startswith("- **"):
            cur = []
        for t in _TEST_RE.findall(ln):
            sec_tests.add(t)
            for i in cur:
                idx[i]["tests"].add(t)
    close()
    return idx


def status(entry: dict, idx: dict) -> str:
    sc = entry.get("scope") or "in"
    if sc in ("deferred", "out"):
        return sc
    hb = [h for h in entry.get("handled_by") or [] if h in idx]
    if not hb:
        return "missing"
    return "covered" if any(idx[h]["tests"] for h in hb) else "partial"


def render(idx: dict) -> str:
    el, fam, fmt = load()
    lines = ["# Каталог: элементы документа, правила набора, форматы",
             "",
             "Страница собрана `tools/catalog_report.py` из `backend/doc_catalog/*.json` — правьте",
             "данные, а не её. Статус выводится: covered — есть наши правила и тест при них;",
             "partial — правила есть, теста не названо; missing — в работе, правил нет.",
             ""]
    lines += ["## Форматы: что значит «тот же файл»", "",
              "| Формат | Уровень | Что выходит | Потери |", "|---|---|---|---|"]
    for f in fmt["formats"]:
        lines.append("| %s (%s) | %s | %s | %s |" % (f["id"], " ".join(f["ext"]), f["tier"], f["output"],
                                                    "; ".join(f["losses"]) or "—"))
    for title, rows, key in (("Элементы страницы", el["elements"], "group"),
                             ("Семейства правил набора", fam["families"], "group")):
        counts = {}
        for r in rows:
            st = status(r, idx)
            counts[st] = counts.get(st, 0) + 1
        lines += ["", "## %s" % title, "",
                  "Итого: " + ", ".join("%s %d" % (k, counts[k]) for k in
                                        ("covered", "partial", "missing", "deferred", "out") if k in counts), ""]
        groups = {}
        for r in rows:
            groups.setdefault(r[key], []).append(r)
        for g in sorted(groups):
            lines += ["### %s" % g, "", "| id | статус | правила | что это / почему |", "|---|---|---|---|"]
            for r in sorted(groups[g], key=lambda x: x["id"]):
                lines.append("| %s | %s | %s | %s — %s |" % (
                    r["id"], status(r, idx), " ".join(r.get("handled_by") or []) or "—",
                    r["desc"], (r.get("why") or "").replace("|", "/")))
            lines.append("")
    used = {h for r in el["elements"] + fam["families"] for h in r.get("handled_by") or []}
    free = sorted(set(idx) - used)
    lines += ["## Правила справочника без записи в каталоге", "",
              (" ".join(free) or "нет"), ""]
    return "\n".join(lines)


def main():
    text = render(rule_index())
    if "--check" in sys.argv:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if cur != text:
            print("docs/rules/catalog.md устарела: python tools/catalog_report.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print("записано", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
