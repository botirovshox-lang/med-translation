import sys, csv, openpyxl
sys.stdout.reconfigure(encoding="utf-8")

OUT = r"C:\Users\Shox\med_translation\master_output"
BASE = r"C:\Users\Shox\med_translation\словари"

print("=== APPROVED (первые 15) ===")
with open(OUT + r"\approved_glossary.tsv", encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f, delimiter="\t")):
        if i >= 15: break
        src = row["Sources"][:25]
        print(f"  {row['Russian'][:38]:38s} -> {row['English'][:35]:35s} [{src}]")

print()
print("=== REJECTED (первые 15) ===")
with open(OUT + r"\rejected_terms.tsv", encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f, delimiter="\t")):
        if i >= 15: break
        print(f"  {row['Russian'][:38]:38s} -> {row['English'][:20]:20s}  [{row['Issues']}]")

print()
print("=== FORBIDDEN (первые 10) ===")
with open(OUT + r"\forbidden_translations.tsv", encoding="utf-8-sig") as f:
    for i, row in enumerate(csv.DictReader(f, delimiter="\t")):
        if i >= 10: break
        print(f"  {row['Russian'][:38]:38s} -X> {row['Forbidden_English']}")

# ── Проверка XLSX которые дали 0 ──────────────────────────────────────
print()
print("=== XLSX ДИАГНОСТИКА ===")
for fname in ["koloproktologiya.xlsx","nejromyshechnye-zabolevaniya.xlsx",
              "opuholi-pochki.xlsx","respiratornaya-podderzhka.xlsx","uroandrologiya.xlsx"]:
    path = BASE + "\\" + fname
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sh in wb.sheetnames:
        ws = wb[sh]
        # Найдём первые 8 непустых строк
        non_empty = []
        for row in ws.iter_rows(values_only=True):
            vals = [v for v in row if v is not None]
            if vals:
                non_empty.append(vals)
            if len(non_empty) >= 6:
                break
        print(f"\n  {fname} / [{sh}]  max_row={ws.max_row}, max_col={ws.max_column}")
        for r in non_empty[:4]:
            print(f"    {[str(v)[:30] for v in r]}")
    wb.close()
