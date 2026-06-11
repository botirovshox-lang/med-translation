"""
Интеграция новых источников в мастер-глоссарий:
  - 2_5_pairs.tsv   (Акжигитов: 75K EN→RU пар)
  - covid_pairs.tsv (COVID: 755 пар)

Стратегия:
  Акжигитов ЧИСТЫЕ (EN 1-3 слова, RU 1-4 слова, без артефактов) → reference_glossary_FINAL
  Акжигитов ВСЕ остальные + дубли                                → akzhigitov_lookup.tsv
  COVID пары                                                     → reference_glossary_FINAL
"""
import sys, csv, re, os
sys.stdout.reconfigure(encoding="utf-8")

PARSED  = r"C:\Users\Shox\med_translation\словари\parsed"
FINAL   = r"C:\Users\Shox\med_translation\final_output"

def has_cyrillic(s):
    return bool(re.search(r"[А-ЯЁа-яё]", s))

def has_ocr_artifact(s):
    """Эвристика: строка содержит явные OCR-артефакты."""
    # Слова с одиночными буквами (р е а к)
    words = s.split()
    if len(words) >= 3 and sum(1 for w in words if len(w) == 1) / len(words) > 0.3:
        return True
    # Повторяющиеся пробелы
    if "  " in s:
        return True
    # Скобка без закрытия
    if s.count("(") > s.count(")"):
        return True
    return False

def is_clean_short_pair(en, ru):
    """Критерий для reference: короткая, чистая пара."""
    en_words = en.split()
    ru_words = ru.split()
    # Длина
    if len(en_words) > 3 or len(ru_words) > 4:
        return False
    # Нет OCR артефактов
    if has_ocr_artifact(en) or has_ocr_artifact(ru):
        return False
    # Нет цифр в EN ключе (кроме числовых терминов как «5-HT»)
    if re.search(r"\s\d+\s", en):
        return False
    return True

# ── Читаем existing reference ─────────────────────────────────────────────
print("Читаем существующие файлы...")
with open(FINAL + r"\reference_glossary_FINAL.tsv", encoding="utf-8-sig") as f:
    ref_existing = list(csv.DictReader(f, delimiter="\t"))
print(f"  reference_glossary_FINAL: {len(ref_existing):,} записей")

# Ключи для дедупликации (ru.lower, en.lower)
ref_keys = set()
for r in ref_existing:
    ref_keys.add((r["Russian"].lower().strip(), r["English"].lower().strip()))

# Также загружаем approved — чтобы не дублировать
with open(FINAL + r"\approved_glossary_FINAL.tsv", encoding="utf-8-sig") as f:
    approved = list(csv.DictReader(f, delimiter="\t"))
approved_keys = set((r["Russian"].lower().strip(), r["English"].lower().strip())
                    for r in approved)
print(f"  approved_glossary_FINAL:  {len(approved):,} записей")

# ── Читаем COVID пары ─────────────────────────────────────────────────────
with open(PARSED + r"\covid_pairs.tsv", encoding="utf-8-sig") as f:
    covid_raw = list(csv.DictReader(f, delimiter="\t"))

covid_new = []
for r in covid_raw:
    ru = r["Russian"].strip()
    en = r["English"].strip()
    key = (ru.lower(), en.lower())
    if key in ref_keys or key in approved_keys:
        continue
    if not ru or not en:
        continue
    ref_keys.add(key)
    covid_new.append({
        "Russian": ru,
        "English": en,
        "Category": "",
        "Confidence": "reference_only",
        "Sources": "covid_dict",
        "Issues": ""
    })
print(f"\nCOVID новых пар: {len(covid_new):,}  (из {len(covid_raw):,})")

# ── Читаем Акжигитов пары ─────────────────────────────────────────────────
with open(PARSED + r"\2_5_pairs.tsv", encoding="utf-8-sig") as f:
    akzh_raw = list(csv.DictReader(f, delimiter="\t"))

akzh_for_ref   = []   # чистые короткие → reference
akzh_for_lookup = []  # остальные → отдельный файл

for r in akzh_raw:
    ru = r["Russian"].strip()
    en = r["English"].strip()
    key = (ru.lower(), en.lower())

    if key in ref_keys or key in approved_keys:
        continue
    if not ru or not en:
        continue

    entry = {
        "Russian": ru,
        "English": en,
        "Category": "",
        "Confidence": "needs_human_review",
        "Sources": "akzhigitov_2_5",
        "Issues": ""
    }

    if is_clean_short_pair(en, ru):
        ref_keys.add(key)
        akzh_for_ref.append(entry)
    else:
        akzh_for_lookup.append(entry)

print(f"Акжигитов → reference:  {len(akzh_for_ref):,}")
print(f"Акжигитов → lookup:     {len(akzh_for_lookup):,}")

# ── Пишем обновлённый reference ───────────────────────────────────────────
ref_fields = ["Russian", "English", "Category", "Confidence", "Sources", "Issues"]

combined_ref = ref_existing + covid_new + akzh_for_ref
combined_ref_sorted = sorted(combined_ref, key=lambda r: r.get("Russian", "").lower())

with open(FINAL + r"\reference_glossary_FINAL.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=ref_fields, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(combined_ref_sorted)
print(f"\n✓ reference_glossary_FINAL.tsv → {len(combined_ref_sorted):,} записей")

# ── Пишем Акжигитов lookup (все остальные пары) ───────────────────────────
akzh_lookup_fields = ["Russian", "English", "Confidence", "Sources"]
akzh_for_lookup_sorted = sorted(akzh_for_lookup, key=lambda r: r.get("English", "").lower())

with open(FINAL + r"\akzhigitov_lookup.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=akzh_lookup_fields, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(akzh_for_lookup_sorted)
print(f"✓ akzhigitov_lookup.tsv    → {len(akzh_for_lookup):,} записей")

# ── Итог ──────────────────────────────────────────────────────────────────
total_new = len(covid_new) + len(akzh_for_ref)
print(f"""
{'═'*65}
ИТОГ ИНТЕГРАЦИИ
{'═'*65}
  Было в reference:          {len(ref_existing):,}
  Добавлено COVID:           {len(covid_new):,}   (reference_only)
  Добавлено Акжигитов чист.: {len(akzh_for_ref):,} (needs_human_review)
  ─────────────────────────────────────────
  Новый reference total:     {len(combined_ref_sorted):,}

  akzhigitov_lookup.tsv:     {len(akzh_for_lookup):,}  пар (программный поиск)

Файлы: {FINAL}
  reference_glossary_FINAL.tsv  ← обновлён
  akzhigitov_lookup.tsv         ← новый (большой EN→RU словарь для поиска)
""")

# ── Образцы добавленных пар ───────────────────────────────────────────────
import random
random.seed(99)

print("=== 20 случайных новых пар из Акжигитова (reference) ===")
sample = random.sample(akzh_for_ref, min(20, len(akzh_for_ref)))
for p in sorted(sample, key=lambda r: r["English"].lower()):
    print(f"  {p['English'][:40]:40s} → {p['Russian'][:50]}")

print()
print("=== 15 COVID пар (sample) ===")
sample_c = random.sample(covid_new, min(15, len(covid_new)))
for p in sorted(sample_c, key=lambda r: r["English"].lower()):
    print(f"  {p['English'][:40]:40s} → {p['Russian'][:50]}")
