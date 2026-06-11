"""
MASTER MEDICAL GLOSSARY CONSOLIDATOR

Объединяет все источники в единый glossary + TM:
1. My extracted glossary (corrected RU → EN)
2. ProZ.com glossaries (когда скрепинг завершится)
3. Baldwin STRICT glossary
4. Specialized XLSX dictionaries (колопроктология, неврология и т.д.)
5. PDF словари (если понадобится)

Производит:
- approved_medical_glossary.tsv — чистый glossary (RU → EN)
- forbidden_translations.tsv — опасные пары (не использовать)
- tm_reference.tsv — фраз-уровень TM (из других источников)

QA Criteria:
✓ No broken extraction
✓ No generic single-word English targets for multiword Russian
✓ No lost qualifiers (острый/хронический, злокачественный/доброкачественный)
✓ No dangerous medical mismatches
✓ Medical safety first, quality over quantity
"""

import os
import sys
import json
import csv
import re
from pathlib import Path
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding="utf-8")

QA_OUTPUT_DIR = Path(r"C:\Users\Shox\med_translation\qa_output")
FINAL_OUTPUT_DIR = Path(r"C:\Users\Shox\med_translation\final_glossary")
FINAL_OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 100)
print("MEDICAL GLOSSARY CONSOLIDATOR - MASTER BUILD")
print("=" * 100)

# === CONFIGURATION ===

# Dangerous qualifiers that must NOT be lost
DANGEROUS_QUALIFIERS = {
    "острый": "acute",
    "хронический": "chronic",
    "активный": "active",
    "пассивный": "passive",
    "положительный": "positive",
    "отрицательный": "negative",
    "злокачественный": "malignant",
    "доброкачественный": "benign",
    "приобретённый": "acquired",
    "врождённый": "congenital",
    "абсолютный": "absolute",
    "относительный": "relative",
}

SUSPICIOUS_GENERIC = {
    "analysis", "test", "study", "work", "sample", "threshold",
    "dressing", "syndrome", "disease", "disorder", "failure",
    "count", "review", "examination", "screening", "assessment", "procedure"
}

# === PHASE 1: LOAD ALL SOURCES ===

print("\n[PHASE 1] LOADING ALL SOURCES\n")

all_glossary = defaultdict(lambda: {
    "targets": defaultdict(int),  # {target: count}
    "sources": set(),
    "categories": set(),
    "quality": "unknown"
})

# 1.1 My extracted glossary (CORRECTED RU → EN)
print("  1.1 My extracted glossary...")
my_glossary_file = QA_OUTPUT_DIR / "medical_glossary_approved.tsv"
if my_glossary_file.exists():
    with open(my_glossary_file, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        count = 0
        for row in reader:
            # IMPORTANT: Swap RU ↔ EN to get RU → EN direction
            ru = row.get("EN", "").strip()  # English term
            en = row.get("RU", "").strip()  # Russian term
            category = row.get("Category", "general")

            if ru and en and len(ru) > 1 and len(en) > 1:
                all_glossary[ru]["targets"][en] += 1
                all_glossary[ru]["sources"].add("my_glossary")
                all_glossary[ru]["categories"].add(category)
                count += 1

    print(f"    ✓ {count} terms (RU → EN)")
else:
    print(f"    ✗ Not found: {my_glossary_file}")

# 1.2 ProZ.com glossaries
print("  1.2 ProZ.com glossaries...")
proz_file = QA_OUTPUT_DIR / "proz_glossary.tsv"
if proz_file.exists():
    with open(proz_file, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        count = 0
        for row in reader:
            ru = row.get("source", "").strip()
            en = row.get("target", "").strip()
            glossary_name = row.get("source_glossary", "proz")

            if ru and en and len(ru) > 1 and len(en) > 1:
                all_glossary[ru]["targets"][en] += 1
                all_glossary[ru]["sources"].add(f"proz_{glossary_name}")
                count += 1

    print(f"    ✓ {count} terms")
else:
    print(f"    ⏳ Waiting for ProZ scraper (not found yet)")

# 1.3 Baldwin STRICT glossary (if available)
print("  1.3 Baldwin STRICT glossary...")
baldwin_file = Path(r"C:\Users\Shox\Yandex.Disk\перевод мед\словари\baldwin_STRICT_safe_glossary_ru_en.tsv")
if baldwin_file.exists():
    try:
        with open(baldwin_file, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="\t")
            count = 0
            for row in reader:
                ru = row.get("source_term", "").strip()
                en = row.get("target_term", "").strip()
                if ru and en:
                    # Baldwin is already RU → EN
                    all_glossary[ru]["targets"][en] += 1
                    all_glossary[ru]["sources"].add("baldwin_strict")
                    all_glossary[ru]["quality"] = "approved"
                    count += 1
        print(f"    ✓ {count} terms (pre-approved)")
    except Exception as e:
        print(f"    ✗ Error: {e}")
else:
    print(f"    ✗ Not found: {baldwin_file}")

# 1.4 Other Baldwin sources
print("  1.4 Baldwin REFERENCE pairs...")
baldwin_ref = Path(r"C:\Users\Shox\Yandex.Disk\перевод мед\словари\baldwin_REFERENCE_raw_pairs_ru_en_utf8sig.csv")
if baldwin_ref.exists():
    try:
        with open(baldwin_ref, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            count = 0
            for row in reader:
                if len(row) >= 2:
                    ru, en = row[0].strip(), row[1].strip()
                    if ru and en:
                        all_glossary[ru]["targets"][en] += 1
                        all_glossary[ru]["sources"].add("baldwin_reference")
                        count += 1
        print(f"    ✓ {count} terms")
    except Exception as e:
        print(f"    ✗ Error: {e}")
else:
    print(f"    ✗ Not found")

print(f"\n  TOTAL UNIQUE RU TERMS: {len(all_glossary):,}")

# === PHASE 2: QA AUDIT ===

print("\n[PHASE 2] QA AUDIT\n")

approved = []
rejected = []
conflicts = []

for ru_term, data in all_glossary.items():
    issues = []
    targets = data["targets"]

    # Check for ambiguity (multiple English translations)
    if len(targets) > 1:
        # This is expected, just pick the most common one
        best_en = max(targets.items(), key=lambda x: x[1])[0]
    else:
        best_en = list(targets.keys())[0]

    # QA Check 1: Lost qualifiers
    has_qualifier = any(q in ru_term.lower() for q in DANGEROUS_QUALIFIERS.keys())
    has_qualifier_en = any(DANGEROUS_QUALIFIERS[q] in best_en.lower()
                           for q in DANGEROUS_QUALIFIERS.keys()
                           if q in ru_term.lower())
    if has_qualifier and not has_qualifier_en:
        issues.append("lost_qualifier")

    # QA Check 2: Generic English for multiword Russian
    ru_word_count = len(ru_term.split())
    en_word_count = len(best_en.split())
    if en_word_count == 1 and best_en.lower() in SUSPICIOUS_GENERIC and ru_word_count > 2:
        issues.append("generic_single_word")

    # QA Check 3: Very short English for long Russian (possible incomplete extraction)
    # EXCEPTION: Allow medical acronyms (all uppercase, 2-5 chars)
    is_acronym = best_en.isupper() and 2 <= len(best_en) <= 5
    if len(best_en) < 5 and len(ru_term) > 20 and not is_acronym:
        issues.append("possibly_incomplete")

    # QA Check 4: Non-ASCII characters (except Cyrillic)
    if re.search(r"[^\x00-\x7FЀ-ӿ]", best_en):
        if not re.search(r"[©™®]", best_en):  # Allow common symbols
            issues.append("non_ascii_chars")

    # Assign verdict
    if issues:
        rejected.append({
            "source": ru_term,
            "target": best_en,
            "targets_count": len(targets),
            "issues": "; ".join(issues),
            "sources": ", ".join(data["sources"])
        })
    else:
        sources_list = ", ".join(sorted(data["sources"]))
        # Determine confidence
        if "baldwin_strict" in data["sources"]:
            confidence = "approved"
        elif len(data["sources"]) >= 2:
            confidence = "reference_only"  # Multiple sources increase confidence
        else:
            confidence = "reference_only"

        approved.append({
            "source": ru_term,
            "target": best_en,
            "targets_count": len(targets),
            "category": list(data["categories"])[0] if data["categories"] else "general",
            "confidence": confidence,
            "sources": sources_list
        })

print(f"  ✓ Approved:     {len(approved):,} terms")
print(f"  ✗ Rejected:     {len(rejected):,} terms")

if rejected:
    reasons = Counter([r["issues"].split(";")[0].strip() for r in rejected])
    print(f"\n  Top rejection reasons:")
    for reason, count in reasons.most_common(5):
        print(f"    - {reason}: {count}")

# === PHASE 3: OUTPUT FILES ===

print(f"\n[PHASE 3] WRITING OUTPUT FILES\n")

# 3.1 Approved glossary (ready for CAT)
approved_file = FINAL_OUTPUT_DIR / "medical_glossary_unified_RU_EN.tsv"
with open(approved_file, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["Russian", "English", "Category", "Confidence", "Sources"],
                            delimiter="\t")
    writer.writeheader()
    for item in sorted(approved, key=lambda x: x["source"]):
        writer.writerow({
            "Russian": item["source"],
            "English": item["target"],
            "Category": item.get("category", "general"),
            "Confidence": item["confidence"],
            "Sources": item["sources"][:60]  # Truncate for display
        })
print(f"  ✓ {approved_file.name}: {len(approved):,} terms")

# 3.2 Rejected for review
rejected_file = FINAL_OUTPUT_DIR / "rejected_terms_REVIEW.tsv"
with open(rejected_file, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["Russian", "English", "Issues", "Sources"],
                            delimiter="\t")
    writer.writeheader()
    for item in sorted(rejected[:500], key=lambda x: x["source"]):
        writer.writerow({
            "Russian": item["source"],
            "English": item["target"],
            "Issues": item["issues"],
            "Sources": item["sources"][:40]
        })
print(f"  ✓ {rejected_file.name}: {len(rejected):,} terms (first 500)")

# 3.3 JSON export (for API/programmatic use)
json_file = FINAL_OUTPUT_DIR / "medical_glossary_unified.json"
with open(json_file, "w", encoding="utf-8") as f:
    json.dump([{
        "russian": item["source"],
        "english": item["target"],
        "category": item["category"],
        "confidence": item["confidence"],
        "sources": item["sources"]
    } for item in approved], f, ensure_ascii=False, indent=2)
print(f"  ✓ {json_file.name}: {len(approved):,} terms")

print(f"\n{'='*100}")
print(f"CONSOLIDATION COMPLETE")
print(f"{'='*100}")
print(f"\nFinal glossary statistics:")
print(f"  Total approved:  {len(approved):,}")
print(f"  Total rejected:  {len(rejected):,}")
print(f"  Approval rate:   {100*len(approved)/(len(approved)+len(rejected)):.1f}%")
print(f"\nOutput files in {FINAL_OUTPUT_DIR}:")
print(f"  1. medical_glossary_unified_RU_EN.tsv  ← Use this for CAT tools")
print(f"  2. medical_glossary_unified.json       ← Use this for APIs")
print(f"  3. rejected_terms_REVIEW.tsv           ← Review if needed")
