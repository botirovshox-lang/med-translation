"""
Очистка и извлечение пар из:
  1. 2_5.txt  — Акжигитов «Большой Англо-Русский Медицинский Словарь»
  2. covid.txt — COVID-19 Англо-Русский Медицинский Словарь
Выход:
  2_5_clean.txt       — очищенный текст (только словарная часть)
  covid_clean.txt     — очищенный текст
  2_5_pairs.tsv       — пары EN→RU
  covid_pairs.tsv     — пары EN→RU
"""
import sys, re, csv, os
sys.stdout.reconfigure(encoding="utf-8")

BASE   = r"C:\Users\Shox\med_translation\словари"
OUTDIR = r"C:\Users\Shox\med_translation\словари\parsed"
os.makedirs(OUTDIR, exist_ok=True)

SOFT_HYPHEN = "­"

# ─────────────────────────────── helpers ────────────────────────────────────

def has_cyrillic(s):
    return bool(re.search(r"[А-ЯЁа-яё]", s))

def has_latin(s):
    return bool(re.search(r"[A-Za-z]", s))

def cyrillic_ratio(s):
    letters = [c for c in s if c.isalpha()]
    if not letters: return 0
    return sum(1 for c in letters if "Ѐ" <= c <= "ӿ") / len(letters)

# Метки областей знаний (не часть перевода)
LABEL_RE = re.compile(
    r"^(лат|англ|амер|австр|нрк|уст|разг|жарг|фирм|аббр|"
    r"акуш|аллерг|анат|анест|бакт|биол|биохим|вет|вирус|гастр|"
    r"гемат|ген|гинек|гист|дерм|иммун|инф|кард|микол|микр|"
    r"невр|нефр|онк|офт|пат\.анат|пед|прокт|псих|психол|"
    r"пульм|рад|рентг|секс|стом|суд\.мед|токс|травм|трансп|"
    r"урол|хир|цитол|энд|ядерн|бтх|гиг|комп|мол\.биол|"
    r"физиол|фарм|эмбр|ото|ортоп|нейрохир)\.\s*",
    re.IGNORECASE,
)

def clean_ru_term(s):
    """Извлекает первый чистый русский термин из перевода."""
    s = s.strip()
    # Убираем метки области
    s = LABEL_RE.sub("", s)
    # Убираем ссылки «см.»
    s = re.sub(r"^см\..*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+см\.\s+.*", "", s).strip()
    # Обрезаем по нумерованным сенсам «2. текст» / «3. текст» (оставляем первый сенс)
    s = re.sub(r"\s+\d+\.\s+.*", "", s).strip()
    # Убираем скобочные пояснения  (...)
    s = re.sub(r"\(.*?\)", "", s).strip()
    # Убираем квадратные скобки-синонимы [...]
    s = re.sub(r"\[.*?\]", "", s).strip()
    # Берём первую часть до ; или |
    s = re.split(r"[;|]", s)[0]
    # Берём первый вариант до первой запятой
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if parts:
        first = parts[0].strip()
        # убираем «1.» «2.» в начале
        first = re.sub(r"^\d+\.\s*", "", first).strip()
        s = first
    # Финальная чистка
    s = re.sub(r"[\s;,\.]+$", "", s)
    s = re.sub(r"^[\s\d\.•\-«»]+", "", s)
    return s.strip()

def is_valid_pair(en, ru):
    if not en or not ru:
        return False
    if len(en) < 3 or len(ru) < 3:
        return False
    if len(en) > 100 or len(ru) > 120:
        return False
    if not has_latin(en):
        return False
    if not has_cyrillic(ru):
        return False
    # EN должен быть в основном латиница (≤10 % кириллицы)
    if cyrillic_ratio(en) > 0.10:
        return False
    # RU должен быть в основном кириллица
    if cyrillic_ratio(ru) < 0.55:
        return False
    # Не просто "см." ссылки
    if ru.lower().startswith("см.") or ru.lower().startswith("see "):
        return False
    # Не просто цифры или аббревиатуры
    if re.match(r"^[\d\W]+$", ru):
        return False
    # EN не должен содержать только стоп-слова
    en_lower = en.lower()
    if en_lower in {"see", "also", "cf", "note", "obs", "ibid"}:
        return False
    # Фильтр OCR: пробелы между отдельными буквами (р е а к)
    ru_words = ru.split()
    if len(ru_words) >= 3:
        single_letter_ratio = sum(1 for w in ru_words if len(w) == 1) / len(ru_words)
        if single_letter_ratio > 0.5:
            return False
    en_words = en.split()
    if len(en_words) >= 3:
        single_letter_ratio = sum(1 for w in en_words if len(w) == 1) / len(en_words)
        if single_letter_ratio > 0.4:
            return False
    # OCR-специфичный артефакт «finger-to-finger» в EN (навигационный элемент PDF)
    if "finger-to-finger" in en.lower():
        return False
    # EN не должен заканчиваться на «см» «see» «vide»
    if en_lower.endswith(("см", "see", "vide", "cf")):
        return False
    # RU не должен содержать тильду (незавершённое разворачивание или загрязнение)
    if "~" in ru:
        return False
    # RU не должен начинаться с открывающей скобки — это фрагмент пояснения
    if ru.startswith("("):
        return False
    # RU с незакрытой скобкой — усечённый текст
    if ru.count("(") > ru.count(")"):
        return False
    # RU оканчивается на предлог — фрагмент (перенос на следующую строку)
    RU_PREPS = {"в", "на", "с", "у", "к", "из", "для", "при", "по", "от", "за",
                "до", "о", "об", "над", "под", "через", "между", "без"}
    ru_last_word = ru.split()[-1].lower().rstrip(".,;")
    if ru_last_word in RU_PREPS:
        return False
    # RU из одного слова — прилагательное без существительного = усечение
    ru_words_list = ru.split()
    if len(ru_words_list) == 1:
        # Одиночное прилагательное (окончания -ый/-ая/-ое/-ие/-ых/-им) → пропустить
        # (оставляем substantivized: катарактный, гомолатеральный — это нормально)
        # Но усечения вроде «тотальная» без контекста опасны — разрешим однословные
        pass  # однословные пары ДОПУСТИМЫ
    # EN не должен начинаться с символов "-" "." "*"
    if en and en[0] in "-.*":
        return False
    return True

def normalize_en(s):
    """Нормализует английский термин."""
    s = re.sub(r"\s+", " ", s).strip()
    # Убираем trailing/leading спецсимволы
    s = re.sub(r'^["\'\[\](),\.\s]+', "", s)
    s = re.sub(r'["\'\[\](),\.\s]+$', "", s)
    # Убираем trailing dashes и слэши
    s = re.sub(r"[\s\-–—/]+$", "", s).strip()
    # Убираем trailing номера сенсов: «aggression 1» «aggression I» → «aggression»
    s = re.sub(r"\s+[IVX\d]+\.?\s*$", "", s).strip()
    # Убираем leading числа: «2. of behavior» → пустая строка
    if re.match(r"^\d+[\.\)]", s):
        return ""
    # Фильтр: термин с двоеточием — скорее всего название книги/заголовок
    if ":" in s and len(s) > 30:
        return ""
    # Убираем утекшую кириллицу в конце EN: «Emery - Dreifus ... Эмери» → «Emery - Dreifus ...»
    s = re.sub(r"\s+[А-ЯЁа-яё][\w\-]*\s*$", "", s).strip()
    # Убираем trailing " -" после имён
    s = re.sub(r"\s+[-–]\s*$", "", s).strip()
    return s.strip()


def clean_ru_term_covid(s):
    """Очистка RU-перевода из COVID-словаря (более мягкая, сохраняет многословные)."""
    s = s.strip()
    # Убираем leading «1–2.» «–2.» «1.» паттерны
    s = re.sub(r"^\d+[\-–—]\d*[\.\)]\s*", "", s).strip()
    s = re.sub(r"^[\-–—\s]+\d*[\.\)]\s*", "", s).strip()
    s = re.sub(r"^[\-–—]+\s*", "", s).strip()
    s = re.sub(r"^\d+[\.\)]\s*", "", s).strip()
    # Убираем ссылки «см.»
    s = re.sub(r"^см\..*", "", s, flags=re.IGNORECASE).strip()
    # Убираем скобочные пояснения (краткие, в одну скобку)
    s = re.sub(r"\(.*?\)", "", s).strip()
    # "/" в COVID-словаре означает «или» — заменяем на запятую-пробел
    s = re.sub(r"\s*/\s*", ", ", s)
    # Берём до ; или |
    s = re.split(r"[;|]", s)[0].strip()
    # В COVID-словаре сохраняем ПОЛНЫЙ перевод (несколько вариантов через запятую — полезно)
    # Нормализуем пробелы и запятые
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r"\s+", " ", s)
    # Убираем trailing запятые/точки
    s = re.sub(r"[\s;,\.]+$", "", s)
    return s.strip()

# ═══════════════════════════════════════════════════════════════════════════
#  БЛОК 1 — 2_5.txt (Акжигитов)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 60)
print("ОБРАБОТКА 2_5.txt")
print("═" * 60)

with open(BASE + r"\2_5.txt", encoding="utf-8") as f:
    raw_lines = f.readlines()

# ── Шаг 1: выделяем словарную часть ────────────────────────────────────
DICT_START = 638   # строка «A» перед «Ars longa»
DICT_END   = 141700  # строка «ПРИЛОЖЕНИЯ»

dict_lines = raw_lines[DICT_START:DICT_END]

# ── Шаг 2: фиксим мягкие переносы (U+00AD) ─────────────────────────────
merged = []
i = 0
while i < len(dict_lines):
    line = dict_lines[i].rstrip("\n\r")
    if line.endswith(SOFT_HYPHEN):
        # Склеиваем с началом следующей строки
        line = line[:-1]
        if i + 1 < len(dict_lines):
            next_line = dict_lines[i + 1].rstrip("\n\r").lstrip()
            line = line + next_line
            i += 2
        else:
            i += 1
    else:
        i += 1
    merged.append(line)

# ── Шаг 3: фильтруем мусорные строки ───────────────────────────────────
NOISE_PATTERNS = [
    re.compile(r"^\d+\s*$"),                        # только цифры (номер страницы)
    re.compile(r"^[A-Z]{2,6}-[A-Z]{2,6}\s*$"),     # ABD-ABI (колонтитул)
    re.compile(r"^[A-Z]{1,3}\s*$"),                 # одиночные буквы / короткий заголовок
    re.compile(r"^\*\s"),                           # сноски
    re.compile(r"^Ars longa"),                      # эпиграф
    re.compile(r"^Путь науки"),                     # перевод эпиграфа
    re.compile(r"^\*\s*В настоящее"),               # примечание к эпиграфу
    re.compile(r"^применительно"),
    re.compile(r"^как слова"),
]

clean_lines = []
for line in merged:
    stripped = line.strip()
    if not stripped:
        clean_lines.append("")
        continue
    skip = False
    for pat in NOISE_PATTERNS:
        if pat.match(stripped):
            skip = True
            break
    if not skip:
        clean_lines.append(line.rstrip())

# Записываем чистый текст
with open(OUTDIR + r"\2_5_clean.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(clean_lines))

total_clean = sum(1 for l in clean_lines if l.strip())
print(f"Очищено строк: {len(raw_lines):,} → {total_clean:,} непустых")

# ── Шаг 4: извлечение пар (state-machine) ──────────────────────────────

# Явный ASCII-класс для EN-части (НЕ включает кириллицу!)
_EN_CHAR = r"[A-Za-z0-9\-\.'\",\[\]()/*+_]"
_EN_WORD  = _EN_CHAR + r"+"         # одно «слово» EN
_EN_TERM  = (r"(?:[A-Za-z]" + _EN_CHAR + r"*)"   # первое слово начинается с буквы
             r"(?:\s+" + _EN_WORD + r"){0,7}")     # до 7 доп. слов

# Главная запись: EN-термин  пробел(ы)  Кириллица...
MAIN_ENTRY_RE = re.compile(
    r"^(" + _EN_TERM + r")\s{1,4}([А-ЯЁа-яё].{2,})",
    re.UNICODE
)
# Главная запись — только заголовок (оканчивается :)
HEADWORD_ONLY_RE = re.compile(
    r"^(" + _EN_TERM + r")\s*:\s*$",
    re.UNICODE
)
# Подзапись с тильдой:
#   «~ suffix кириллица», «prefix ~ кириллица», «prefix ~ suffix кириллица»
#   Тильда-группа — строго ASCII + пробелы + ~, БЕЗ кириллицы
TILDE_RE = re.compile(
    r"^([A-Za-z0-9\-\.'\",\[\]()/*+_\s]*~[A-Za-z0-9\-\.'\",\[\]()/*+_\s]*)"
    r"\s{1,4}([А-ЯЁа-яё].{2,})",
    re.UNICODE
)

pairs_2_5 = []
seen = set()
current_headword = ""
skipped_noise = 0

def add_pair(en, ru, source="akzhigitov_2_5"):
    en = normalize_en(en)
    ru = clean_ru_term(ru)
    if is_valid_pair(en, ru):
        key = (en.lower(), ru.lower())
        if key not in seen:
            seen.add(key)
            pairs_2_5.append({"English": en, "Russian": ru, "Source": source})

def resolve_tilde(tilde_expr, headword):
    """Разворачивает ~ в конкретное слово."""
    if not headword:
        return tilde_expr.replace("~", "").strip()
    # Тильда может быть: "~ suffix", "prefix ~", "prefix ~ suffix", "~s", "~ies"
    # Паттерн ~suffix (слитно) — добавляем к headword окончание
    tilde_expr = re.sub(r"~([a-z]+)", headword + r"\1", tilde_expr)
    tilde_expr = tilde_expr.replace("~", headword)
    return re.sub(r"\s+", " ", tilde_expr).strip()

for line in clean_lines:
    stripped = line.strip()
    if not stripped:
        continue

    # Пробуем HEADWORD_ONLY_RE (запись вида «abalienatio:»)
    m2 = HEADWORD_ONLY_RE.match(stripped)
    if m2 and "~" not in stripped:
        hw = m2.group(1).strip()
        # Убираем trailing цифры из headword
        hw_clean = re.sub(r"\s+\d+\.?\s*$", "", hw).strip()
        if 1 <= len(hw_clean.split()) <= 5:
            current_headword = hw_clean.lower()
        continue

    # Пробуем MAIN_ENTRY_RE
    m = MAIN_ENTRY_RE.match(stripped)
    if m and "~" not in m.group(1):
        en_part = m.group(1).strip()
        ru_part = m.group(2).strip()
        # Убираем trailing номера сенсов из EN
        en_part = re.sub(r"\s+[IVXivx\d]+\.?\s*$", "", en_part).strip()
        # Проверяем что EN-часть не начинается с цифры
        if re.match(r"^\d", en_part):
            continue
        en_words = en_part.split()
        if 1 <= len(en_words) <= 7:
            # Headword для разворачивания ~ = полный EN термин (последнее значимое слово)
            current_headword = en_part.lower().rstrip(":")
            add_pair(en_part, ru_part)
            continue

    # Пробуем TILDE_RE
    m3 = TILDE_RE.match(stripped)
    if m3 and current_headword:
        tilde_part = m3.group(1).strip()
        ru_part = m3.group(2).strip()
        en_resolved = resolve_tilde(tilde_part, current_headword)
        # Убираем leading числа после разворачивания
        en_resolved = re.sub(r"^\d+[\.\)]\s*", "", en_resolved).strip()
        add_pair(en_resolved, ru_part)
        continue

print(f"Пар извлечено из 2_5.txt: {len(pairs_2_5):,}")

# Пишем TSV
fields = ["English", "Russian", "Source"]
with open(OUTDIR + r"\2_5_pairs.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
    w.writeheader()
    w.writerows(sorted(pairs_2_5, key=lambda r: r["English"].lower()))
print(f"✓ 2_5_pairs.tsv")

# ═══════════════════════════════════════════════════════════════════════════
#  БЛОК 2 — covid.txt
# ═══════════════════════════════════════════════════════════════════════════

print()
print("═" * 60)
print("ОБРАБОТКА covid.txt")
print("═" * 60)

with open(BASE + r"\covid.txt", encoding="utf-8") as f:
    covid_raw = f.read()

# Убираем заголовок/источники
# Начало словаря — первая строка вида "Abdominal"
lines_covid = covid_raw.split("\n")
dict_start_c = 0
for i, l in enumerate(lines_covid):
    if re.match(r"^[A-Z][a-z]+\s*$", l.strip()) or re.match(r"^[A-Z][a-z]+\s+[A-Z]", l.strip()):
        dict_start_c = i
        break

# Конец — «Sources:»
dict_end_c = len(lines_covid)
for i, l in enumerate(lines_covid):
    if l.strip().startswith("Sources:") or l.strip().startswith("См. более 100"):
        dict_end_c = i
        break

covid_lines = lines_covid[dict_start_c:dict_end_c]

# Записываем чистый текст
with open(OUTDIR + r"\covid_clean.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(covid_lines))

print(f"COVID строк в словаре: {len(covid_lines):,}")

# ── Парсим covid по блокам (структура: EN-блок, RU-блок, definition-блок) ──
# Блоки чередуются: EN term → RU translation → EN definition → EN term → ...
# Начало словаря: блок 4 (Abdominal)

pairs_covid = []
seen_c = set()

def add_covid_pair(en, ru):
    en = normalize_en(en)
    ru = clean_ru_term_covid(ru)
    if is_valid_pair(en, ru):
        key = (en.lower(), ru.lower())
        if key not in seen_c:
            seen_c.add(key)
            pairs_covid.append({"English": en, "Russian": ru, "Source": "covid_dict"})

def is_en_term_block(block_text):
    """Блок является EN термином: нет кириллицы, ≤6 слов."""
    s = block_text.strip()
    if not s or has_cyrillic(s): return False
    if not has_latin(s): return False
    words = s.split()
    if len(words) > 8: return False
    # Первое слово с заглавной буквы (Title Case)
    first = words[0]
    if first and (first[0].isupper() or first.upper() == first):
        return True
    return False

def is_ru_block(block_text):
    """Блок является русским переводом: большинство символов кириллица."""
    s = block_text.strip()
    return bool(s and has_cyrillic(s) and cyrillic_ratio(s) > 0.45)

# Нормализуем текст и разбиваем на блоки
text_c = "\n".join(covid_lines)
text_c = re.sub(r"\n{3,}", "\n\n", text_c)
blocks = [b.strip() for b in text_c.split("\n\n") if b.strip()]

# Пропускаем вводные блоки (до первого «термин + перевод» паттерна)
# Ищем первый EN-блок за которым следует RU-блок
dict_block_start = 0
for bi in range(len(blocks) - 1):
    if is_en_term_block(blocks[bi]) and is_ru_block(blocks[bi + 1]):
        dict_block_start = bi
        break

bi = dict_block_start
while bi < len(blocks) - 1:
    if is_en_term_block(blocks[bi]):
        # Следующий блок — перевод?
        if bi + 1 < len(blocks) and is_ru_block(blocks[bi + 1]):
            en_term = " ".join(blocks[bi].split())   # нормализуем пробелы
            ru_term = " ".join(blocks[bi + 1].replace("\n", " ").split())
            add_covid_pair(en_term, ru_term)
            bi += 2  # пропускаем EN + RU (definition пропустим сами)
            # Пропускаем блок определения если он не EN термин
            if bi < len(blocks) and not is_en_term_block(blocks[bi]):
                bi += 1
        else:
            bi += 1
    else:
        bi += 1

print(f"Пар извлечено из covid.txt: {len(pairs_covid):,}")

# Пишем TSV
with open(OUTDIR + r"\covid_pairs.tsv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["English", "Russian", "Source"], delimiter="\t")
    w.writeheader()
    w.writerows(sorted(pairs_covid, key=lambda r: r["English"].lower()))
print(f"✓ covid_pairs.tsv")

# ═══════════════════════════════════════════════════════════════════════════
#  ПРОВЕРКА КАЧЕСТВА — образцы из обоих файлов
# ═══════════════════════════════════════════════════════════════════════════

print()
print("═" * 60)
print("ПРОВЕРКА КАЧЕСТВА — 2_5_pairs.tsv (случайные 30)")
print("═" * 60)
import random
random.seed(42)
sample_25 = random.sample(pairs_2_5, min(30, len(pairs_2_5)))
for p in sorted(sample_25, key=lambda r: r["English"].lower()):
    print(f"  {p['English'][:45]:45s} → {p['Russian'][:50]}")

print()
print("═" * 60)
print("ПРОВЕРКА КАЧЕСТВА — covid_pairs.tsv (первые 30)")
print("═" * 60)
for p in pairs_covid[:30]:
    print(f"  {p['English'][:45]:45s} → {p['Russian'][:50]}")

# ── Статистика длин ────────────────────────────────────────────────────
print()
print("═" * 60)
print("СТАТИСТИКА")
print("═" * 60)
en_lens_25 = [len(p["English"].split()) for p in pairs_2_5]
ru_lens_25 = [len(p["Russian"].split()) for p in pairs_2_5]
print(f"2_5:   {len(pairs_2_5):,} пар")
print(f"  EN слов: min={min(en_lens_25)} max={max(en_lens_25)} avg={sum(en_lens_25)/len(en_lens_25):.1f}")
print(f"  RU слов: min={min(ru_lens_25)} max={max(ru_lens_25)} avg={sum(ru_lens_25)/len(ru_lens_25):.1f}")

if pairs_covid:
    en_lens_c = [len(p["English"].split()) for p in pairs_covid]
    ru_lens_c = [len(p["Russian"].split()) for p in pairs_covid]
    print(f"COVID: {len(pairs_covid):,} пар")
    print(f"  EN слов: min={min(en_lens_c)} max={max(en_lens_c)} avg={sum(en_lens_c)/len(en_lens_c):.1f}")
    print(f"  RU слов: min={min(ru_lens_c)} max={max(ru_lens_c)} avg={sum(ru_lens_c)/len(ru_lens_c):.1f}")

print(f"\nФайлы в: {OUTDIR}")
print("  2_5_clean.txt    — очищенный текст словаря")
print("  covid_clean.txt  — очищенный текст COVID-словаря")
print("  2_5_pairs.tsv    — пары EN→RU (Акжигитов)")
print("  covid_pairs.tsv  — пары EN→RU (COVID)")
