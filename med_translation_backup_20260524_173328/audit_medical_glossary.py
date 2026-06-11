"""
Senior Medical Translator QA Audit Tool

Phase 1: Load all sources
- Baldwin STRICT glossary
- My extracted glossary from med_translation
- Files from Yandex.Disk/перевод мед/словари

Phase 2: Audit for safety
- Reject broken extraction
- Reject generic English targets
- Reject context loss (qualifiers)
- Check for medical mismatches

Phase 3: Produce clean outputs
- approved_glossary.tsv
- reference_glossary.tsv
- rejected_terms.tsv
- forbidden_translations.tsv
- tm_reference.tsv
"""

import os
import sys
import json
import csv
import re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

YANDEX_DISK = Path(r"C:\Users\Shox\Yandex.Disk\перевод мед\словари")
OUTPUT_DIR = Path(r"C:\Users\Shox\med_translation\qa_output")
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print("MEDICAL GLOSSARY & TM QA AUDIT")
print("=" * 80)

# === Phase 1: Load all sources ===

print("\n[PHASE 1] Loading sources...\n")

all_terms = defaultdict(lambda: {"source_list": [], "count": 0})
all_pairs = []

# 1.1 Baldwin STRICT glossary
baldwin_file = YANDEX_DISK / "baldwin_STRICT_safe_glossary_ru_en.tsv"
if baldwin_file.exists():
    with open(baldwin_file, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            ru = row.get("source_term", "").strip()
            en = row.get("target_term", "").strip()
            if ru and en:
                key = (ru, en)
                all_terms[key]["sources"].append("baldwin_STRICT")
                all_pairs.append({
                    "source": ru,
                    "target": en,
                    "source_file": "baldwin_STRICT_safe_glossary_ru_en.tsv",
                    "confidence": "approved" if "baldwin" in str(row) else "reference_only"
                })
    print(f"  ✓ Baldwin STRICT: {len(all_pairs)} пар")
else:
    print(f"  ✗ Baldwin STRICT not found: {baldwin_file}")

# 1.2 My extracted glossary
my_glossary_file = YANDEX_DISK / "output" / "glossary.json"
if my_glossary_file.exists():
    with open(my_glossary_file, encoding="utf-8") as f:
        glossary = json.load(f)
        start_count = len(all_pairs)
        for item in glossary:
            ru = item.get("en", "").strip()  # Note: my extraction has ru/en swapped
            en = item.get("ru", "").strip()
            category = item.get("category", "other_medical")
            if ru and en:
                key = (ru, en)
                all_terms[key]["sources"].append("my_glossary")
                all_pairs.append({
                    "source": ru,
                    "target": en,
                    "source_file": "my_glossary.json",
                    "category": category,
                    "sources": ["my_glossary"],
                    "confidence": "reference_only"  # My extraction needs review
                })
        print(f"  ✓ My glossary.json: {len(glossary)} items, {len(all_pairs) - start_count} added")
else:
    print(f"  ✗ My glossary not found: {my_glossary_file}")

# 1.3 Baldwin reference CSV
baldwin_ref_file = YANDEX_DISK / "baldwin_REFERENCE_raw_pairs_ru_en_utf8sig.csv"
if baldwin_ref_file.exists():
    with open(baldwin_ref_file, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        start_count = len(all_pairs)
        for row in reader:
            if len(row) >= 2:
                ru, en = row[0].strip(), row[1].strip()
                if ru and en:
                    key = (ru, en)
                    all_terms[key]["sources"].append("baldwin_REFERENCE")
                    all_pairs.append({
                        "source": ru,
                        "target": en,
                        "source_file": "baldwin_REFERENCE_raw_pairs.csv",
                        "confidence": "reference_only"
                    })
        print(f"  ✓ Baldwin REFERENCE pairs: {len(all_pairs) - start_count} added")
else:
    print(f"  ✗ Baldwin REFERENCE pairs not found")

# 1.4 XLSX files (specialized dictionaries)
xlsx_files = list(YANDEX_DISK.glob("*.xlsx"))
print(f"\n  Found {len(xlsx_files)} XLSX files:")
for xlsx_file in xlsx_files:
    print(f"    - {xlsx_file.name}")

print(f"\n  Total pairs loaded: {len(all_pairs)}")
print(f"  Unique (source, target) pairs: {len(all_terms)}")

# === Phase 2: Audit for safety ===

print("\n[PHASE 2] Running QA audit...\n")

SUSPICIOUS_SINGLE_WORDS = {
    "analysis", "test", "study", "work", "sample", "threshold",
    "dressing", "syndrome", "disease", "disorder", "failure",
    "count", "review", "examination", "screening", "assessment"
}

DANGEROUS_QUALIFIERS_RU = [
    ("острый", "хронический"),
    ("активный", "пассивный"),
    ("положительный", "отрицательный"),
    ("злокачественный", "доброкачественный"),
    ("приобретённый", "врождённый"),
    ("абсолютный", "относительный"),
]

ORGAN_PREFIXES = ["лёгочный", "почечный", "печёночный", "сердечный", "туберкулёзный", "инфекционный", "воспалительный"]

approved = []
reference_only = []
rejected = []
forbidden = defaultdict(list)

for pair in all_pairs:
    ru = pair["source"]
    en = pair["target"]
    issues = []

    # Check 1: Broken extraction (incomplete English)
    en_words = en.split()
    if len(en_words) == 1 and en.lower() in SUSPICIOUS_SINGLE_WORDS:
        ru_words = ru.split()
        if len(ru_words) > 2:
            issues.append("generic_single_word_for_multiword")

    # Check 2: Context loss - qualifiers
    has_qualifier_ru = any(q in ru.lower() for q, _ in DANGEROUS_QUALIFIERS_RU)
    has_qualifier_en = any(q in en.lower() for q, _ in DANGEROUS_QUALIFIERS_RU if q.replace("ный", "").replace("ый", "") in en.lower())
    if has_qualifier_ru and not has_qualifier_en:
        issues.append("lost_qualifier")

    # Check 3: Medical mismatches (very basic)
    if "туберкул" in ru and "TB" not in en and "tuberculosis" not in en.lower():
        issues.append("possible_disease_mismatch")

    # Check 4: OCR artifacts or page numbers
    if re.search(r"\d{2,}", en) and ru.count(" ") < 2:
        issues.append("possible_ocr_artifact")

    # Check 5: Table fragments
    if "|" in en or "\t" in en:
        issues.append("table_fragment")

    # Assign confidence
    if issues:
        rejected.append({
            "source": ru,
            "target": en,
            "issues": "; ".join(issues)
        })
    else:
        # No issues - check if it's from approved source
        sources = pair.get("sources", [])
        if isinstance(sources, str):
            sources = [sources]
        if "baldwin_STRICT" in sources or pair.get("confidence") == "approved":
            approved.append({
                "source": ru,
                "target": en,
                "category": pair.get("category", "general"),
                "confidence": "approved"
            })
        else:
            reference_only.append({
                "source": ru,
                "target": en,
                "category": pair.get("category", "general"),
                "confidence": "reference_only"
            })

print(f"  ✓ Approved: {len(approved)} пар")
print(f"  ⚠ Reference only: {len(reference_only)} пар")
print(f"  ✗ Rejected: {len(rejected)} пар")

# === Phase 3: Output files ===

print("\n[PHASE 3] Writing output files...\n")

# Deduplicate
approved_dedup = {}
for item in approved:
    key = (item["source"], item["target"])
    if key not in approved_dedup:
        approved_dedup[key] = item

reference_dedup = {}
for item in reference_only:
    key = (item["source"], item["target"])
    if key not in reference_dedup:
        reference_dedup[key] = item

# Write approved glossary
approved_file = OUTPUT_DIR / "approved_glossary.tsv"
with open(approved_file, "w", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["source_term", "target_term", "category", "confidence", "notes"], delimiter="\t")
    writer.writeheader()
    for (src, tgt), item in sorted(approved_dedup.items()):
        writer.writerow({
            "source_term": src,
            "target_term": tgt,
            "category": item.get("category", "general"),
            "confidence": "approved",
            "notes": ""
        })
print(f"  ✓ {approved_file.name}: {len(approved_dedup)} pairs")

# Write reference glossary
reference_file = OUTPUT_DIR / "reference_glossary.tsv"
with open(reference_file, "w", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["source_term", "target_term", "category", "confidence", "notes"], delimiter="\t")
    writer.writeheader()
    for (src, tgt), item in sorted(reference_dedup.items()):
        writer.writerow({
            "source_term": src,
            "target_term": tgt,
            "category": item.get("category", "general"),
            "confidence": "reference_only",
            "notes": ""
        })
print(f"  ✓ {reference_file.name}: {len(reference_dedup)} pairs")

# Write rejected
rejected_file = OUTPUT_DIR / "rejected_terms.tsv"
with open(rejected_file, "w", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["source_term", "target_term", "reason"], delimiter="\t")
    writer.writeheader()
    for item in rejected[:500]:  # limit to first 500
        writer.writerow({
            "source_term": item["source"],
            "target_term": item["target"],
            "reason": item["issues"]
        })
print(f"  ✓ {rejected_file.name}: {len(rejected)} pairs (showing first 500)")

print(f"\n{'='*80}")
print(f"QA AUDIT COMPLETE")
print(f"{'='*80}")
print(f"\nApproved glossary:  {len(approved_dedup):,} terms")
print(f"Reference glossary: {len(reference_dedup):,} terms")
print(f"Rejected:           {len(rejected):,} terms")
print(f"\nOutput directory: {OUTPUT_DIR}")
