import sys, csv
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

OUT = r"C:\Users\Shox\med_translation\master_output"

# ── Approved по источникам ────────────────────────────────────────────
src_count = Counter()
with open(OUT + r"\approved_glossary.tsv", encoding="utf-8-sig") as f:
    approved = list(csv.DictReader(f, delimiter="\t"))
for row in approved:
    for s in row["Sources"].split("|"):
        src_count[s.strip()] += 1

print("=== APPROVED по источникам ===")
for src, cnt in src_count.most_common():
    print(f"  {src:35s}: {cnt:,}")
print(f"\n  Всего approved: {len(approved):,}")

# ── Образцы Baldwin STRICT ─────────────────────────────────────────────
print("\n=== Образцы APPROVED — Baldwin STRICT (строки 100-115) ===")
bald = [r for r in approved if "baldwin_strict" in r["Sources"]]
for r in bald[100:115]:
    print(f"  {r['Russian'][:42]:42s} -> {r['English']}")

# ── Образцы XLSX ────────────────────────────────────────────────────────
xlsx = [r for r in approved if "xlsx" in r["Sources"]]
print(f"\n=== XLSX терминов в approved: {len(xlsx)} ===")
for r in xlsx[:12]:
    print(f"  {r['Russian'][:42]:42s} -> {r['English'][:35]}  [{r['Sources']}]")

# ── Образцы WHO vaccine ─────────────────────────────────────────────────
who = [r for r in approved if "vaccine_pdf" in r["Sources"]]
print(f"\n=== WHO vaccine в approved: {len(who)} ===")
for r in who[:8]:
    print(f"  {r['Russian'][:42]:42s} -> {r['English'][:35]}")

# ── Reference — сколько из каждого источника ──────────────────────────
print("\n=== REFERENCE — топ источники ===")
ref_count = Counter()
with open(OUT + r"\reference_glossary.tsv", encoding="utf-8-sig") as f:
    ref = list(csv.DictReader(f, delimiter="\t"))
for row in ref:
    for s in row["Sources"].split("|"):
        ref_count[s.strip()] += 1
for src, cnt in ref_count.most_common():
    print(f"  {src:35s}: {cnt:,}")
print(f"\n  Всего reference: {len(ref):,}")

# ── Forbidden ──────────────────────────────────────────────────────────
print("\n=== FORBIDDEN (первые 15) ===")
with open(OUT + r"\forbidden_translations.tsv", encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f, delimiter="\t")):
        if i >= 15: break
        print(f"  {row['Russian'][:42]:42s} -X-> {row['Forbidden_English']}")

# ── Rejected ────────────────────────────────────────────────────────────
print("\n=== REJECTED по причинам ===")
rej_count = Counter()
with open(OUT + r"\rejected_terms.tsv", encoding="utf-8-sig") as f:
    rej = list(csv.DictReader(f, delimiter="\t"))
for row in rej:
    for issue in row["Issues"].split(";"):
        rej_count[issue.strip()] += 1
for reason, cnt in rej_count.most_common():
    print(f"  {reason:35s}: {cnt}")
print(f"\n  Всего rejected: {len(rej):,}")

# ── TM ──────────────────────────────────────────────────────────────────
print("\n=== TM сегменты (первые 3) ===")
with open(OUT + r"\tm_reference.tsv", encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f, delimiter="\t")):
        if i >= 3: break
        print(f"  RU: {row['Source_RU'][:80]}")
        print(f"  EN: {row['Target_EN'][:80]}")
        print()
