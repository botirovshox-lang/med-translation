"""
Патч: переочищаем TM с более строгими правилами и пересоздаём TMX.

Проблема: сегменты вида "мочи Test Суточный анализ мочи..." содержат
артефакты MedlinePlus — один сегмент захватил конец одной статьи +
английский заголовок следующей. Такие сегменты нельзя исправить,
только выбросить.
"""
import sys, csv, re, os
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding="utf-8")

FINAL = r"C:\Users\Shox\med_translation\final_output"
tm_path   = FINAL + r"\tm_reference_FINAL.tsv"
tmx_path  = FINAL + r"\tm_reference_FINAL.tmx"

# ─── Детекция артефактов ──────────────────────────────────────────────────────

# EN-слово с заглавной буквы (≥3 символов) окружённое кириллическим текстом
# Пример: "мочи Test Суточный" / "здоровье Pregnancy Ниже"
# Двоеточие тоже учитываем: "сидя Exercises: Sitting Выполняйте"
EMBEDDED_EN_HEADING = re.compile(
    r"[А-ЯЁа-яё]\w*\s+"            # кириллическое слово + пробел
    r"[A-Z][a-zA-Z]{2,}"           # EN-слово с заглавной
    r"(?:[:\s,]+[A-Za-z]{2,})*"    # опционально: двоеточие/пробел + ещё EN-слова
    r"\s+[А-ЯЁа-яё]"               # потом кириллица
)

# EN-слово с заглавной в самом начале перед кириллицей
EN_AT_START = re.compile(
    r"^(?:[A-Z][a-zA-Z]{2,}\s+){1,3}[А-ЯЁа-яё]"
)

# Слишком много EN-слов внутри RU-текста (>10% латиница)
def latin_ratio(s):
    letters = re.findall(r"[A-Za-zА-ЯЁа-яё]", s)
    if not letters:
        return 0.0
    lat = sum(1 for c in letters if re.match(r"[A-Za-z]", c))
    return lat / len(letters)

def cyrillic_ratio(s):
    letters = re.findall(r"[A-Za-zА-ЯЁа-яё]", s)
    if not letters:
        return 0.0
    cyr = sum(1 for c in letters if re.match(r"[А-ЯЁа-яё]", c))
    return cyr / len(letters)

def is_contaminated(ru):
    """Возвращает причину, если сегмент нельзя использовать, иначе None."""
    if EMBEDDED_EN_HEADING.search(ru):
        return "embedded_en_heading"
    if EN_AT_START.match(ru):
        return "en_at_start"
    if cyrillic_ratio(ru) < 0.80:
        return f"low_cyr_ratio={cyrillic_ratio(ru):.2f}"
    if latin_ratio(ru) > 0.12:
        return f"high_lat_ratio={latin_ratio(ru):.2f}"
    if len(ru) < 20:
        return "too_short"
    return None

# ─── Загружаем TM ─────────────────────────────────────────────────────────────
with open(tm_path, encoding="utf-8-sig") as f:
    tm_all = list(csv.DictReader(f, delimiter="\t"))

ru_field = "Source_RU"
en_field = "Target_EN"
fields   = list(tm_all[0].keys()) if tm_all else [ru_field, en_field]

print(f"Загружено: {len(tm_all):,} сегментов")

# ─── Фильтрация ───────────────────────────────────────────────────────────────
tm_good  = []
tm_bad   = []

for r in tm_all:
    ru = r.get(ru_field, "").strip()
    en = r.get(en_field, "").strip()
    if not ru or not en:
        tm_bad.append((r, "empty"))
        continue
    reason = is_contaminated(ru)
    if reason:
        tm_bad.append((r, reason))
    else:
        tm_good.append(r)

print(f"Прошли фильтр: {len(tm_good):,}")
print(f"Отфильтровано: {len(tm_bad):,}")

# Показываем что удалили (первые 10)
print("\n=== Удалённые сегменты (первые 10) ===")
for r, reason in tm_bad[:10]:
    print(f"  [{reason}]")
    print(f"    RU: {r.get(ru_field,'')[:100]}")
    print()

# Показываем что осталось (первые 5)
print("=== Чистые сегменты (первые 5) ===")
for r in tm_good[:5]:
    print(f"  RU: {r[ru_field][:95]}")
    print(f"  EN: {r[en_field][:95]}")
    print()

# ─── Сохраняем TSV ────────────────────────────────────────────────────────────
with open(tm_path, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(tm_good)
print(f"✓ tm_reference_FINAL.tsv → {len(tm_good):,} сегментов")

# ─── TMX 1.4 ──────────────────────────────────────────────────────────────────
def xml_escape(s):
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;"))

now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE tmx SYSTEM "tmx14.dtd">',
    '<tmx version="1.4">',
    '  <header creationtool="med_translation_pipeline"',
    '          creationtoolversion="1.0"',
    '          datatype="PlainText"',
    '          segtype="sentence"',
    '          adminlang="ru"',
    '          srclang="ru"',
    '          o-tmf="MedlinePlus_RU-EN"',
    f'          creationdate="{now_utc}"',
    '  />',
    '  <body>',
]

count_tmx = 0
for r in tm_good:
    ru_val = xml_escape(r.get(ru_field, "").strip())
    en_val = xml_escape(r.get(en_field, "").strip())
    if not ru_val or not en_val:
        continue
    lines += [
        '    <tu>',
        f'      <tuv xml:lang="ru"><seg>{ru_val}</seg></tuv>',
        f'      <tuv xml:lang="en"><seg>{en_val}</seg></tuv>',
        '    </tu>',
    ]
    count_tmx += 1

lines += ['  </body>', '</tmx>']

with open(tmx_path, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")

print(f"✓ tm_reference_FINAL.tmx → {count_tmx:,} TU-юнитов")
print(f"\nФайлы: {FINAL}")
