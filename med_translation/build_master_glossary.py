"""
MASTER GLOSSARY BUILD — все источники
Действует как: Senior Medical Translator + CAT/TM Engineer + QA Auditor
"""

import sys, csv, json, re, os
from pathlib import Path
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")

BASE    = Path(r"C:\Users\Shox\med_translation\словари")
BALDWIN = BASE / "baldwin_assets_STRICT_v2_bundle"
OUT     = Path(r"C:\Users\Shox\med_translation\master_output")
OUT.mkdir(exist_ok=True)

import pdfplumber, openpyxl

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def clean(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = re.sub(r"^[;,.\-\)\(]+", "", s).strip()   # leading junk
    s = re.sub(r"[;,.\-\)\(]+$", "", s).strip()   # trailing junk
    return s

def is_cyrillic(s: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", s))

def is_latin(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]", s))

def cyrillic_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters: return 0
    return sum(1 for c in letters if "А" <= c <= "я" or c in "ЁёÑñ") / len(letters)

NOISE_TERMS = {
    "analysis","test","study","work","sample","threshold","dressing","syndrome",
    "disease","disorder","failure","count","review","examination","screening",
    "assessment","procedure","condition","therapy","treatment","infection",
    "examination","management","evaluation","manifestation",
}
QUALIFIER_RU = {
    "острый":"acute","хронический":"chronic","злокачественный":"malignant",
    "доброкачественный":"benign","приобретённый":"acquired","врождённый":"congenital",
    "активный":"active","пассивный":"passive","положительный":"positive",
    "отрицательный":"negative","абсолютный":"absolute","относительный":"relative",
    "лёгочный":"pulmonary","почечный":"renal","печёночный":"hepatic",
    "сердечный":"cardiac","туберкулёзный":"tuberculous",
}

# Accumulated pairs: {(ru, en): {confidence, sources, category}}
GLOSSARY: dict[tuple[str,str], dict] = {}

def add(ru: str, en: str, source: str, confidence: str, category: str = ""):
    ru, en = clean(ru), clean(en)
    if not ru or not en or len(ru) < 2 or len(en) < 2:
        return
    # Confirm direction: ru должен быть кириллическим, en — латиницей
    # (некоторые источники могут быть перевёрнуты)
    if not is_cyrillic(ru) and is_cyrillic(en):
        ru, en = en, ru   # swap
    if not is_cyrillic(ru) or not is_latin(en):
        return
    key = (ru.lower(), en.lower())
    if key not in GLOSSARY:
        GLOSSARY[key] = {"ru": ru, "en": en, "confidence": confidence,
                          "sources": set(), "category": category}
    GLOSSARY[key]["sources"].add(source)
    # Upgrade confidence if higher
    ranks = {"approved": 3, "reference_only": 2, "needs_review": 1}
    if ranks.get(confidence, 0) > ranks.get(GLOSSARY[key]["confidence"], 0):
        GLOSSARY[key]["confidence"] = confidence
    if category and not GLOSSARY[key]["category"]:
        GLOSSARY[key]["category"] = category


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — Baldwin STRICT (10 106 строк, safe_candidate RU→EN)
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[1] Baldwin STRICT")
n = 0
with open(BALDWIN / "baldwin_STRICT_safe_glossary_ru_en.tsv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        ru = row["source_term"].strip()
        en = row["target_term"].strip()
        # Skip obvious junk rows (starts with punctuation)
        if re.match(r"^[)\(;,.\d]", ru):
            continue
        add(ru, en, "baldwin_strict", "approved", row.get("category",""))
        n += 1
print(f"   Загружено: {n:,} → добавлено уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — Baldwin REFERENCE (24 580 строк)
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[2] Baldwin REFERENCE raw pairs")
n = 0
with open(BALDWIN / "baldwin_REFERENCE_raw_pairs_ru_en_utf8sig.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        ru_raw = row["source_term"].strip()
        en     = row["target_term"].strip()
        # Some RU entries have semicolon-separated variants → split each
        for ru in re.split(r";\s*", ru_raw):
            ru = clean(ru)
            # Strip parenthetical explanations from Russian
            ru_clean = re.sub(r"\(.*?\)", "", ru).strip()
            if ru_clean:
                add(ru_clean, en, "baldwin_reference", "reference_only",
                    row.get("category",""))
                n += 1
print(f"   Загружено: {n:,} → уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — Мой output glossary (2 304 строки, EN/RU колонки — нужен swap)
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[3] Output glossary.tsv (мой extraction из MedlinePlus)")
n = 0
with open(BASE / "output/glossary.tsv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        # Колонки: EN, RU, Category  — нам нужно RU→EN
        ru = row.get("RU","").strip()
        en = row.get("EN","").strip()
        cat = row.get("Category","")
        if ru and en:
            add(ru, en, "my_medlineplus", "reference_only", cat)
            n += 1
print(f"   Загружено: {n:,} → уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 4 — vaccine.pdf (WHO, 110 стр.)
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[4] vaccine.pdf (WHO Vaccinology Glossary)")
n = 0
URL_RE = re.compile(r"https?://|www\.|\.org|\.int|\.gov|\.com")
with pdfplumber.open(BASE / "vaccine.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            if not line or URL_RE.search(line):          # пропуск URL-строк
                continue
            if re.match(r"^\d+[\.\)]\s", line):          # пропуск нумерованных списков/ссылок
                continue
            for sep in [" / ", " – "]:
                if sep in line:
                    parts = line.split(sep, 1)
                    if len(parts) == 2:
                        a, b = parts[0].strip(), parts[1].strip()
                        # Строгие фильтры: короткие термины, не предложения
                        if len(a) > 80 or len(b) > 80:
                            break
                        if a.endswith(".") or b.endswith("."):
                            break
                        if is_cyrillic(a) and is_latin(b) and len(a.split()) <= 8:
                            add(a, b, "vaccine_pdf_WHO", "reference_only")
                            n += 1
                        elif is_latin(a) and is_cyrillic(b) and len(a.split()) <= 8:
                            add(b, a, "vaccine_pdf_WHO", "reference_only")
                            n += 1
                        break
print(f"   Извлечено: {n:,} → уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 5 — covid.pdf (55 стр.)
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[5] covid.pdf (COVID-19 Medical Dictionary)")
n = 0
with pdfplumber.open(BASE / "covid.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text() or ""
        # Format: "EN term /\n RU term, RU term; def ..."
        # Also: "coronavirus disease (COVID-19) / коронавирусная инфекция (COVID-19)"
        for line in text.split("\n"):
            line = line.strip()
            for sep in [" / ", " – "]:
                if sep in line:
                    parts = line.split(sep, 1)
                    if len(parts) == 2:
                        a, b = parts[0].strip(), parts[1].strip()
                        # Strip trailing definitions (after period)
                        b = re.split(r"\.\s+[A-Z]", b)[0].strip()
                        if is_cyrillic(a) and is_latin(b):
                            add(a, b, "covid_pdf", "reference_only")
                            n += 1
                        elif is_latin(a) and is_cyrillic(b):
                            add(b, a, "covid_pdf", "reference_only")
                            n += 1
                        break
print(f"   Извлечено: {n:,} → уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 6 — XLSX специализированные словари
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[6] XLSX специализированные словари")

def extract_xlsx_pairs(path: Path, source_name: str):
    """
    Извлекает EN↔RU пары из XLSX.
    Структура файлов: EN в кол. 0, RU в кол. 1.
    Первые строки — заголовок/текст, пропускаем пока не найдём пару.
    """
    n = 0
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sh_name in wb.sheetnames:
        ws = wb[sh_name]
        for row in ws.iter_rows(values_only=True):
            # Берём первые два непустых значения
            vals = [v for v in row if v is not None and str(v).strip()]
            if len(vals) < 2:
                continue
            a = str(vals[0]).strip()
            b = str(vals[1]).strip()
            # Пропускаем заголовки и длинный текст (не термины)
            if len(a) > 120 or len(b) > 120:
                continue
            if a == "None" or b == "None":
                continue
            # Определяем направление
            if is_latin(a) and is_cyrillic(b):
                add(b, a, source_name, "approved")
                n += 1
            elif is_cyrillic(a) and is_latin(b):
                add(a, b, source_name, "approved")
                n += 1
    wb.close()
    return n

xlsx_map = {
    "koloproktologiya.xlsx":        "xlsx_koloproktologiya",
    "nejromyshechnye-zabolevaniya.xlsx": "xlsx_neuromuscular",
    "opuholi-pochki.xlsx":          "xlsx_kidney_tumors",
    "respiratornaya-podderzhka.xlsx": "xlsx_respiratory",
    "uroandrologiya.xlsx":          "xlsx_urology",
    "silikon.xlsx":                 "xlsx_silicone",
    "medconsult.xlsx":              "xlsx_medconsult",
}

for fname, src_name in xlsx_map.items():
    fpath = BASE / fname
    if fpath.exists():
        n = extract_xlsx_pairs(fpath, src_name)
        print(f"   {fname}: {n:,} пар → уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 7 — 2_5.pdf (1247 стр., ~100K терминов, Акжигитов EN→RU словарь)
# ══════════════════════════════════════════════════════════════════════════════
print("─" * 70)
print("[7] 2_5.pdf (Большой Англо-Русский Медицинский Словарь, ~100K терминов)")
print("    Пробуем страницы для определения структуры...")
n = 0
sample_lines = []
with pdfplumber.open(BASE / "2_5.pdf") as pdf:
    total = len(pdf.pages)
    # Пробуем средние страницы (начало и конец — титул/оглавление)
    for page_num in range(10, min(30, total)):
        text = pdf.pages[page_num].extract_text() or ""
        if text.strip():
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            sample_lines.extend(lines[:5])
            break

print(f"   Всего страниц: {total}")
print("   Образец текста:")
for l in sample_lines[:10]:
    print(f"     {repr(l[:100])}")

# 2_5.pdf: OCR зеркально перевёрнут — текст нечитаем.
# Пробуем только строки где Latin + Cyrillic чётко разделены.
# Добавляем с пометкой needs_review (не approved и не reference).
MIRROR_RE = re.compile(r"[а-яё]{2,}\s+[а-яё]{2,}")  # два кирилл. слова — признак зеркала

with pdfplumber.open(BASE / "2_5.pdf") as pdf:
    for page_num in range(8, min(total, 1200)):
        text = pdf.pages[page_num].extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            if not line or len(line) < 5 or len(line) > 200:
                continue
            # Пропускаем строки с явным зеркальным текстом (буквы в обратном порядке)
            # Признак: кириллические «слова» длиной 1-2 буквы вперемешку
            cyr_words = re.findall(r"[А-ЯЁа-яё]+", line)
            if not cyr_words:
                continue
            avg_cyr_len = sum(len(w) for w in cyr_words) / len(cyr_words)
            if avg_cyr_len < 2.5:          # зеркальный OCR — короткие «слова»
                continue
            # Попытка распознать пару
            m = re.match(r"^([A-Za-z][A-Za-z\s,\-\(\)\.]{1,60}?)\s{2,}([А-ЯЁа-яё].{3,})$", line)
            if m:
                en_raw, ru_raw = m.group(1).strip(), m.group(2).strip()
                ru_clean = re.split(r"\s{3,}[A-Z]", ru_raw)[0].strip()
                if len(en_raw) > 3 and len(ru_clean) > 3:
                    add(ru_clean, en_raw, "akzhigitov_dict", "needs_review")
                    n += 1
            else:
                for sep in [" — ", " – "]:
                    if sep in line:
                        parts = line.split(sep, 1)
                        if (len(parts) == 2
                                and is_latin(parts[0]) and is_cyrillic(parts[1])
                                and len(parts[0]) < 80 and len(parts[1]) < 80):
                            add(parts[1].strip(), parts[0].strip(), "akzhigitov_dict", "needs_review")
                            n += 1
                        break

print(f"   Извлечено (needs_review): {n:,} → уникальных: {len(GLOSSARY):,}")


# ══════════════════════════════════════════════════════════════════════════════
# QA AUDIT
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 70)
print("QA AUDIT")
print("═" * 70)

approved_out     = []
reference_out    = []
rejected_out     = []
forbidden_out    = []

for (ru_key, en_key), data in GLOSSARY.items():
    ru  = data["ru"]
    en  = data["en"]
    src = data["sources"]
    issues = []

    # ── QA 1: Broken — generic single word for multiword Russian ──────
    en_words = en.split()
    ru_words = ru.split()
    is_acronym = en.isupper() and 2 <= len(en) <= 7
    if (len(en_words) == 1
            and en_key in NOISE_TERMS
            and len(ru_words) > 2
            and not is_acronym):
        issues.append("generic_single_word")

    # ── QA 2: Lost qualifier ──────────────────────────────────────────
    for ru_q, en_q in QUALIFIER_RU.items():
        if ru_q in ru.lower() and en_q not in en.lower():
            issues.append(f"lost_qualifier:{ru_q}")
            break

    # ── QA 3: Clearly incomplete (en much shorter, not acronym) ───────
    if not is_acronym and len(en) < 4 and len(ru) > 15:
        issues.append("incomplete_target")

    # ── QA 4: Stray characters from OCR ──────────────────────────────
    if re.search(r"[©™®°]", en) or re.search(r"\d{3,}", en):
        issues.append("ocr_artifact")

    # ── QA 5: Dangerous mismatch signals ─────────────────────────────
    dangerous = [
        ("туберкулёз", "tuberculosis"), ("рак", "cancer"),
        ("инфаркт", "infarction"), ("инсульт", "stroke"),
    ]
    for ru_d, en_d in dangerous:
        if ru_d in ru.lower() and en_d not in en.lower() and "cancer" not in en.lower():
            pass  # Could flag, but too many false positives — skip

    # ── Assign ────────────────────────────────────────────────────────
    row = {
        "Russian":    ru,
        "English":    en,
        "Category":   data.get("category",""),
        "Confidence": data["confidence"],
        "Sources":    "|".join(sorted(src)),
    }

    if issues:
        row["Issues"] = "; ".join(issues)
        # Severe issues → rejected
        severe = [i for i in issues if i in ("generic_single_word","incomplete_target","ocr_artifact")]
        if severe:
            rejected_out.append(row)
            # If it's generic single word — add to forbidden
            if "generic_single_word" in issues:
                forbidden_out.append({
                    "Russian": ru, "Forbidden_English": en,
                    "Reason": "generic_single_word_target"
                })
        else:
            # Only qualifier loss → reference
            row["Confidence"] = "needs_human_review"
            reference_out.append(row)
    else:
        if data["confidence"] == "approved":
            approved_out.append(row)
        else:
            reference_out.append(row)

print(f"  Approved:           {len(approved_out):,}")
print(f"  Reference/review:   {len(reference_out):,}")
print(f"  Rejected:           {len(rejected_out):,}")
print(f"  Forbidden mappings: {len(forbidden_out):,}")


# ══════════════════════════════════════════════════════════════════════════════
# WRITE OUTPUT FILES
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 70)
print("WRITING OUTPUT FILES")
print("═" * 70)

def write_tsv(rows: list, path: Path, fields: list):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["Russian"].lower()))
    print(f"  ✓ {path.name}  ({len(rows):,} строк)")

# A. approved_glossary.tsv
write_tsv(approved_out,
          OUT / "approved_glossary.tsv",
          ["Russian","English","Category","Confidence","Sources"])

# B. reference_glossary.tsv
write_tsv(reference_out,
          OUT / "reference_glossary.tsv",
          ["Russian","English","Category","Confidence","Sources","Issues"])

# C. rejected_terms.tsv
write_tsv(rejected_out,
          OUT / "rejected_terms.tsv",
          ["Russian","English","Issues","Sources"])

# D. forbidden_translations.tsv
write_tsv(forbidden_out,
          OUT / "forbidden_translations.tsv",
          ["Russian","Forbidden_English","Reason"])

# E. tm_reference.tsv (из output TM)
print("\n  [TM] Копируем output tm.tsv с пометкой quality...")
tm_rows = []
with open(BASE / "output/tm.tsv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        en = row.get("EN","").strip()
        ru = row.get("RU","").strip()
        if en and ru and len(en) > 20 and len(ru) > 20:
            # Basic noise check: skip rows where EN and RU text is mixed
            if cyrillic_ratio(en) < 0.15 and cyrillic_ratio(ru) > 0.5:
                tm_rows.append({"Source_RU": ru, "Target_EN": en,
                                 "Confidence": "reference_only",
                                 "Notes": "extracted_from_medlineplus_pdf"})

with open(OUT / "tm_reference.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["Source_RU","Target_EN","Confidence","Notes"],
                       delimiter="\t")
    w.writeheader()
    w.writerows(tm_rows)
print(f"  ✓ tm_reference.tsv  ({len(tm_rows):,} сегментов)")

# F. Combined JSON
all_approved = [{"russian": r["Russian"], "english": r["English"],
                 "category": r["Category"], "confidence": r["Confidence"],
                 "sources": r["Sources"].split("|")} for r in approved_out]
with open(OUT / "approved_glossary.json", "w", encoding="utf-8") as f:
    json.dump(all_approved, f, ensure_ascii=False, indent=2)
print(f"  ✓ approved_glossary.json  ({len(all_approved):,} терминов)")

# G. Summary stats
total_in = len(GLOSSARY)
print(f"""
{'═'*70}
ИТОГ
{'═'*70}
  Всего загружено пар:  {total_in:,}
  Одобрено (approved):  {len(approved_out):,}
  Reference/review:     {len(reference_out):,}
  Отклонено:            {len(rejected_out):,}
  Запрещённые:          {len(forbidden_out):,}
  TM сегментов:         {len(tm_rows):,}

  Одобрение %:          {100*len(approved_out)/max(1,total_in):.1f}%

Файлы в {OUT}:
  A. approved_glossary.tsv     ← используй в CAT (Trados / OmegaT)
  B. reference_glossary.tsv    ← полезные, но требуют проверки
  C. rejected_terms.tsv        ← почему отклонены
  D. forbidden_translations.tsv← опасные несоответствия — не использовать
  E. tm_reference.tsv          ← фраз-уровень TM (RU→EN)
  F. approved_glossary.json    ← для API / программного использования
""")
