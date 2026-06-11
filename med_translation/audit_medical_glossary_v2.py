"""
Senior Medical Translator QA Audit Tool - v2
Simplified version focused on my extracted glossary

Phase 1: Load my glossary from med_translation/output
Phase 2: Audit for safety
Phase 3: Produce clean outputs
"""

import os
import sys
import json
import csv
import re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path(r"C:\Users\Shox\med_translation\qa_output")
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print("MEDICAL GLOSSARY QA AUDIT v2")
print("=" * 80)

# === Phase 1: Load glossary ===

print("\n[PHASE 1] Loading glossary...\n")

my_glossary_file = Path(r"C:\Users\Shox\Yandex.Disk\перевод мед\словари\output\glossary.json")
if not my_glossary_file.exists():
    my_glossary_file = Path(r"C:\Users\Shox\med_translation\output\glossary.json")

all_pairs = []
with open(my_glossary_file, encoding="utf-8") as f:
    glossary = json.load(f)
    for item in glossary:
        ru = item.get("en", "").strip()  # Note: swapped in my extraction
        en = item.get("ru", "").strip()
        category = item.get("category", "other_medical")
        if ru and en:
            all_pairs.append({
                "source": ru,
                "target": en,
                "category": category,
            })

print(f"  ✓ Loaded {len(all_pairs)} pairs from glossary.json\n")

# === Phase 2: Audit for safety ===

print("[PHASE 2] Running QA audit...\n")

SUSPICIOUS_SINGLE_WORDS = {
    "analysis", "test", "study", "work", "sample", "threshold",
    "dressing", "syndrome", "disease", "disorder", "failure",
    "count", "review", "examination", "screening", "assessment", "procedure"
}

approved = []
reference_only = []
rejected = []

for pair in all_pairs:
    ru = pair["source"]
    en = pair["target"]
    issues = []

    # Check 1: Broken extraction (incomplete English)
    en_words = en.lower().split()
    ru_words = ru.split()

    if len(en_words) == 1 and en.lower() in SUSPICIOUS_SINGLE_WORDS and len(ru_words) > 2:
        issues.append("generic_single_word_for_multiword")

    # Check 2: Broken extraction - English is much shorter than Russian
    if len(en) < len(ru) / 2 and len(ru_words) > 3:
        # Only flag if Russian is clearly a phrase and English is too short
        if len(en) < 10 and len(en_words) < 2:
            issues.append("incomplete_extraction")

    # Check 3: OCR artifacts (numbers in middle)
    if re.search(r"\d{2,}", en):
        issues.append("possible_ocr_number")

    # Check 4: Table fragments
    if "|" in en:
        issues.append("table_fragment")

    # Check 5: Bad characters
    if "©" in en or "™" in en or re.search(r"[^\x00-\x7F]", en):
        # Allow Cyrillic but flag non-ASCII non-Cyrillic
        if not re.search(r"[А-Яа-яЁё]", en):
            issues.append("non_ascii_chars")

    # Assign confidence
    if issues:
        rejected.append({
            "source": ru,
            "target": en,
            "category": pair["category"],
            "issues": "; ".join(issues)
        })
    else:
        # No issues - mark as approved
        approved.append({
            "source": ru,
            "target": en,
            "category": pair["category"],
            "confidence": "approved"
        })

print(f"  ✓ Approved:      {len(approved):,} pairs")
print(f"  ✗ Rejected:      {len(rejected):,} pairs")

if rejected:
    print(f"\n  Top rejection reasons:")
    reasons_count = defaultdict(int)
    for r in rejected:
        for issue in r["issues"].split("; "):
            reasons_count[issue] += 1
    for reason, count in sorted(reasons_count.items(), key=lambda x: -x[1])[:5]:
        print(f"    - {reason}: {count}")

# === Phase 3: Output files ===

print(f"\n[PHASE 3] Writing output files...\n")

# Deduplicate by (source, target)
approved_dedup = {}
for item in approved:
    key = (item["source"], item["target"])
    if key not in approved_dedup:
        approved_dedup[key] = item

rejected_dedup = {}
for item in rejected:
    key = (item["source"], item["target"])
    if key not in rejected_dedup:
        rejected_dedup[key] = item

# Write approved glossary
approved_file = OUTPUT_DIR / "approved_glossary.tsv"
with open(approved_file, "w", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["source_term", "target_term", "category", "confidence"], delimiter="\t")
    writer.writeheader()
    for (src, tgt), item in sorted(approved_dedup.items()):
        writer.writerow({
            "source_term": src,
            "target_term": tgt,
            "category": item.get("category", "general"),
            "confidence": "approved",
        })
print(f"  ✓ {approved_file.name}: {len(approved_dedup):,} approved terms")

# Write rejected
rejected_file = OUTPUT_DIR / "rejected_terms.tsv"
with open(rejected_file, "w", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["source_term", "target_term", "category", "reason"], delimiter="\t")
    writer.writeheader()
    for (src, tgt), item in sorted(rejected_dedup.items())[:1000]:  # limit to first 1000
        writer.writerow({
            "source_term": src,
            "target_term": tgt,
            "category": item.get("category", "general"),
            "reason": item.get("issues", "")
        })
print(f"  ✓ {rejected_file.name}: {len(rejected_dedup):,} rejected terms (showing first 1000)")

# Write combined for import
combined_file = OUTPUT_DIR / "medical_glossary_approved.tsv"
with open(combined_file, "w", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["RU", "EN", "Category"], delimiter="\t")
    writer.writeheader()
    for (src, tgt), item in sorted(approved_dedup.items()):
        writer.writerow({
            "RU": src,
            "EN": tgt,
            "Category": item.get("category", "general"),
        })
print(f"  ✓ {combined_file.name}: {len(approved_dedup):,} terms (for CAT import)")

print(f"\n{'='*80}")
print(f"QA AUDIT COMPLETE")
print(f"{'='*80}")
print(f"\nResults:")
print(f"  Approved:   {len(approved_dedup):,} terms → {approved_file}")
print(f"  Rejected:   {len(rejected_dedup):,} terms → {rejected_file}")
print(f"  Export:     {combined_file}")
print(f"\nQuality metrics:")
print(f"  Approval rate: {100 * len(approved_dedup) / len(all_pairs):.1f}%")
print(f"  Average Russian term: {sum(len(p['source'].split()) for p in approved) / max(1, len(approved)):.1f} words")
print(f"  Average English term: {sum(len(p['target'].split()) for p in approved) / max(1, len(approved)):.1f} words")
