"""
Финальная чистка и исправление approved_glossary:
1. Опасный маппинг: адренолейкодистрофия → ADL (ADL = activities of daily living!)
2. XLSX silicone/medconsult — нет медицинских терминов (слоганы, компании, ГОСТы)
3. TM сегменты — очистить от mixed-language строк
4. Дополнительный фильтр: маркетинговые слоганы, URL-фрагменты, номера стандартов
"""
import sys, csv, re
sys.stdout.reconfigure(encoding="utf-8")

OUT = r"C:\Users\Shox\med_translation\master_output"
FINAL = r"C:\Users\Shox\med_translation\final_output"
import os; os.makedirs(FINAL, exist_ok=True)

# ── Дополнительные опасные маппинги ──────────────────────────────────
# (помимо forbidden_translations.tsv уже сгенерированного)
KNOWN_DANGEROUS = {
    # Russian term (lower) → что НЕЛЬЗЯ переводить
    "адренолейкодистрофия": ["ADL"],          # ADL = activities of daily living!
    "острая дыхательная недостаточность": ["failure"],
    "инфаркт миокарда": ["attack", "disease"],
}

# Паттерны нежелательного в glossary
JUNK_PATTERNS = [
    re.compile(r"^\d+[\.\)]\s"),              # "2.2.28 Газовая..." — нумерация
    re.compile(r"www\.|https?://|\.ru|\.com|\.org"),  # URL фрагменты
    re.compile(r"^\d+\s*-\s+верхн"),          # "3 - верхний индекс"
    re.compile(r"девиз|слоган|завод средст|экспериментальн"),  # компании/слоганы
    re.compile(r"ГОСТ|ТУ \d|ISO \d|\d{4}-\d{4}"),             # стандарты/нормы
    re.compile(r"^\«|^\»"),                   # кавычки в начале — цитаты/названия компаний
]

# ── Читаем approved ──────────────────────────────────────────────────
with open(OUT + r"\approved_glossary.tsv", encoding="utf-8-sig") as f:
    approved = list(csv.DictReader(f, delimiter="\t"))

print(f"Загружено approved: {len(approved):,}")

clean_approved = []
extra_rejected = []
extra_forbidden = []

for row in approved:
    ru = row["Russian"]
    en = row["English"]
    src = row["Sources"]
    bad = False
    reason = ""

    # Проверка опасных маппингов
    for ru_key, bad_en_list in KNOWN_DANGEROUS.items():
        if ru_key in ru.lower():
            for bad_en in bad_en_list:
                if en.lower() == bad_en.lower():
                    bad = True
                    reason = f"dangerous_mismatch:{ru_key}->{bad_en}"
                    extra_forbidden.append({
                        "Russian": ru,
                        "Forbidden_English": en,
                        "Reason": reason
                    })
                    break

    # Junk паттерны в Russian или English
    if not bad:
        for pat in JUNK_PATTERNS:
            if pat.search(ru) or pat.search(en):
                bad = True
                reason = "junk_pattern"
                break

    # Неполные термины в скобках как весь русский термин
    if not bad and re.match(r"^\[.+\]$", ru.strip()):
        bad = True
        reason = "bracketed_only"

    # Слишком длинный для термина (> 12 слов)
    if not bad and len(ru.split()) > 12:
        bad = True
        reason = "too_long_for_glossary"

    if bad:
        extra_rejected.append({
            "Russian": ru,
            "English": en,
            "Issues": reason,
            "Sources": src
        })
    else:
        clean_approved.append(row)

print(f"После чистки approved: {len(clean_approved):,}  (убрано: {len(extra_rejected)})")
print(f"Новых forbidden: {len(extra_forbidden)}")

# ── Пишем финальный approved ─────────────────────────────────────────
fields = ["Russian", "English", "Category", "Confidence", "Sources"]
with open(FINAL + r"\approved_glossary_FINAL.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(sorted(clean_approved, key=lambda r: r["Russian"].lower()))
print(f"✓ approved_glossary_FINAL.tsv  ({len(clean_approved):,})")

# ── Reference — добавляем extra_rejected сюда ─────────────────────────
with open(OUT + r"\reference_glossary.tsv", encoding="utf-8-sig") as f:
    reference = list(csv.DictReader(f, delimiter="\t"))

# Дополняем reference полем Issues если его нет
ref_fields = ["Russian", "English", "Category", "Confidence", "Sources", "Issues"]
extra_for_ref = [{
    "Russian": r["Russian"], "English": r["English"],
    "Category": r.get("Category",""), "Confidence": "needs_human_review",
    "Sources": r["Sources"], "Issues": r["Issues"]
} for r in extra_rejected if r["Issues"] != "dangerous_mismatch"]

combined_ref = reference + extra_for_ref
with open(FINAL + r"\reference_glossary_FINAL.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=ref_fields, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(sorted(combined_ref, key=lambda r: r["Russian"].lower()))
print(f"✓ reference_glossary_FINAL.tsv  ({len(combined_ref):,})")

# ── Обновляем forbidden ───────────────────────────────────────────────
with open(OUT + r"\forbidden_translations.tsv", encoding="utf-8-sig") as f:
    forbidden = list(csv.DictReader(f, delimiter="\t"))
all_forbidden = forbidden + extra_forbidden

# Дедупликация
seen_forb = set()
forb_dedup = []
for row in all_forbidden:
    key = (row["Russian"].lower(), row["Forbidden_English"].lower())
    if key not in seen_forb:
        seen_forb.add(key)
        forb_dedup.append(row)

with open(FINAL + r"\forbidden_translations_FINAL.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["Russian","Forbidden_English","Reason"],
                       delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(sorted(forb_dedup, key=lambda r: r["Russian"].lower()))
print(f"✓ forbidden_translations_FINAL.tsv  ({len(forb_dedup):,})")

# ── Копируем rejected ─────────────────────────────────────────────────
with open(OUT + r"\rejected_terms.tsv", encoding="utf-8-sig") as f:
    rejected = list(csv.DictReader(f, delimiter="\t"))
all_rejected = rejected + [r for r in extra_rejected if r["Issues"] == "dangerous_mismatch"]
with open(FINAL + r"\rejected_terms_FINAL.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["Russian","English","Issues","Sources"],
                       delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(sorted(all_rejected, key=lambda r: r["Russian"].lower()))
print(f"✓ rejected_terms_FINAL.tsv  ({len(all_rejected):,})")

# ── TM — очистка mixed-language строк ────────────────────────────────
def cyrillic_ratio(s):
    letters = [c for c in s if c.isalpha()]
    if not letters: return 0
    return sum(1 for c in letters if "А" <= c <= "я" or c in "ЁёЪъЫыЬь") / len(letters)

with open(OUT + r"\tm_reference.tsv", encoding="utf-8-sig") as f:
    tm_raw = list(csv.DictReader(f, delimiter="\t"))

tm_clean = []
tm_rejected = []
for row in tm_raw:
    ru = row.get("Source_RU", "")
    en = row.get("Target_EN", "")
    # Должен быть: RU почти весь кириллица, EN почти весь латиница
    if cyrillic_ratio(ru) > 0.65 and cyrillic_ratio(en) < 0.10:
        # Минимальная длина для TM сегмента — настоящая фраза
        if len(ru.split()) >= 5 and len(en.split()) >= 5:
            tm_clean.append(row)
        else:
            tm_rejected.append(row)
    else:
        tm_rejected.append(row)

with open(FINAL + r"\tm_reference_FINAL.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["Source_RU","Target_EN","Confidence","Notes"],
                       delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(tm_clean)
print(f"✓ tm_reference_FINAL.tsv  ({len(tm_clean):,} чистых сегментов, убрано: {len(tm_rejected)})")

# ── Финальный JSON ────────────────────────────────────────────────────
import json
json_out = [{"russian": r["Russian"], "english": r["English"],
             "category": r.get("Category",""), "confidence": r["Confidence"],
             "sources": r["Sources"].split("|")} for r in clean_approved]
with open(FINAL + r"\approved_glossary_FINAL.json", "w", encoding="utf-8") as f:
    json.dump(json_out, f, ensure_ascii=False, indent=2)
print(f"✓ approved_glossary_FINAL.json  ({len(json_out):,})")

# ── Финальный отчёт ───────────────────────────────────────────────────
print(f"""
{'═'*65}
ФИНАЛЬНЫЙ ИТОГ
{'═'*65}
  Approved glossary:   {len(clean_approved):,}  терминов  (production-ready)
  Reference glossary:  {len(combined_ref):,}  терминов  (требует проверки)
  Forbidden:           {len(forb_dedup):,}  пар       (опасные маппинги — не использовать)
  Rejected:            {len(all_rejected):,}  пар       (объяснения причин)
  TM сегменты:         {len(tm_clean):,}  сегментов (чистые фразовые пары RU→EN)

Источники approved:
  Baldwin STRICT:      ~10,083  (Routledge Medical Dict, самый надёжный)
  Baldwin REFERENCE:   ~500     (дублей нет, остальные в reference)
  XLSX специалисты:    ~760     (респираторная, урология, онкология и др.)
  WHO vaccine:         ~47      (чистые, высокое качество)
  MedlinePlus:         ~136     (бытовая медицина EN→RU)

Особые замечания:
  ⚠ адренолейкодистрофия → ADL  вынесено в forbidden (ADL = activities of daily living)
  ⚠ 2_5.pdf (Акжигитов): OCR зеркальный, 113 пар → все в reference (needs_review)
  ⚠ XLSX silicone: рекламные/корпоративные строки убраны из approved → reference

Файлы: {FINAL}
  → approved_glossary_FINAL.tsv    ← импортируй в CAT
  → approved_glossary_FINAL.json   ← используй в API
  → reference_glossary_FINAL.tsv   ← review перед использованием
  → forbidden_translations_FINAL.tsv ← заблокировать в CAT
  → rejected_terms_FINAL.tsv       ← архив
  → tm_reference_FINAL.tsv         ← TM (фраз-уровень)
""")
