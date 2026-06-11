"""
Извлекает билингвальные пары EN ↔ RU из PDF с двухколоночным макетом
(English слева, Русский справа) и сохраняет TM в форматах TSV, TMX, JSON.

Вывод:
  output/tm.tsv      — TSV для CAT-инструментов
  output/tm.tmx      — TMX 1.4 для Trados / OmegaT / Memsource
  output/glossary.json — структурированный JSON с метаданными
  output/stats.json  — статистика по файлам
"""

import re
import json
import unicodedata
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    raise SystemExit("Установи pdfplumber: pip install pdfplumber")

PDF_DIR = Path(__file__).parent / "pdfs"
OUTPUT_DIR = Path(__file__).parent / "output"


def detect_lang(text: str) -> str:
    """Определяет язык по доле кириллицы."""
    if not text.strip():
        return "unknown"
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    total = cyrillic + latin
    if total == 0:
        return "unknown"
    return "ru" if cyrillic / total > 0.25 else "en"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def find_column_split(page) -> float:
    """
    Автоматически определяет x-координату разделителя между колонками
    по наибольшему пробелу в распределении x0 слов.
    Fallback — 48% ширины страницы.
    """
    words = page.extract_words(x_tolerance=3)
    if not words:
        return page.width * 0.48

    xs = sorted(w["x0"] for w in words)
    width = page.width

    # Ищем наибольший gap в диапазоне 30%-70% ширины страницы
    center_xs = [x for x in xs if width * 0.30 < x < width * 0.70]
    if len(center_xs) < 2:
        return width * 0.48

    max_gap = 0
    split_x = width * 0.48
    for i in range(len(center_xs) - 1):
        gap = center_xs[i + 1] - center_xs[i]
        if gap > max_gap:
            max_gap = gap
            split_x = (center_xs[i] + center_xs[i + 1]) / 2

    return split_x if max_gap > 20 else width * 0.48


def is_noise(t: str) -> bool:
    return (
        len(t) < 15
        or bool(re.match(r"^\d+\s*$", t))
        or "healthinfotranslations" in t.lower()
        or bool(re.match(r"^page \d+", t, re.I))
    )


NOISE_RE = re.compile(
    r"^\d+\s*$"                        # одиночные номера страниц
    r"|healthinfotranslations"         # URL источника
    r"|medlineplus\.gov"
    r"|page \d+",
    re.I,
)


def lines_to_clean_text(lines: list[str]) -> str:
    """Объединяет строки, убирая noise-строки."""
    kept = []
    for line in lines:
        line = clean(line)
        if not line:
            continue
        if NOISE_RE.search(line):
            continue
        if len(line) < 3:
            continue
        kept.append(line)
    return " ".join(kept)


def extract_column_pairs(pdf_path: Path) -> list[tuple[str, str]]:
    """
    Разбивает каждую страницу на EN (левая) и RU (правую) колонки
    с помощью автодетекции разделителя по словам.
    Каждая страница = одна пара EN/RU сегментов.
    """
    pairs = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                width = page.width
                mid = find_column_split(page)

                # Извлекаем слова с координатами, делим по колонкам
                words = page.extract_words(x_tolerance=3, y_tolerance=3)
                left_lines: dict[int, list[str]] = {}
                right_lines: dict[int, list[str]] = {}

                for w in words:
                    # Округляем y до ближайших 5 пунктов — группировка строк
                    y_key = round(w["top"] / 5) * 5
                    if w["x0"] < mid:
                        left_lines.setdefault(y_key, []).append(w["text"])
                    else:
                        right_lines.setdefault(y_key, []).append(w["text"])

                left_text = lines_to_clean_text(
                    [" ".join(left_lines[y]) for y in sorted(left_lines)]
                )
                right_text = lines_to_clean_text(
                    [" ".join(right_lines[y]) for y in sorted(right_lines)]
                )

                if not left_text or not right_text:
                    continue

                el = detect_lang(left_text[:200])
                rl = detect_lang(right_text[:200])

                if el == "en" and rl == "ru" and len(left_text) > 40:
                    # Убираем кириллические слова, попавшие в EN-колонку
                    en_clean = re.sub(r"[А-ЯЁа-яё]+\s*", "", left_text).strip()
                    en_clean = clean(en_clean)
                    if len(en_clean) > 30:
                        pairs.append((en_clean, right_text))
                elif el == "ru" and rl == "en" and len(right_text) > 40:
                    en_clean = re.sub(r"[А-ЯЁа-яё]+\s*", "", right_text).strip()
                    en_clean = clean(en_clean)
                    if len(en_clean) > 30:
                        pairs.append((en_clean, left_text))

    except Exception as e:
        print(f"  [error] {pdf_path.name}: {e}")
    return pairs


def write_tsv(pairs: list[tuple[str, str]], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("EN\tRU\n")
        for en, ru in pairs:
            f.write(f"{en.replace(chr(9), ' ')}\t{ru.replace(chr(9), ' ')}\n")


def write_tmx(pairs: list[tuple[str, str]], path: Path):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tmx version="1.4">',
        '  <header creationtool="med_tm_extractor" srclang="en"',
        '          datatype="plaintext" segtype="paragraph"/>',
        '  <body>',
    ]
    for en, ru in pairs:
        def esc(t):
            return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines += [
            "    <tu>",
            f'      <tuv xml:lang="en"><seg>{esc(en)}</seg></tuv>',
            f'      <tuv xml:lang="ru"><seg>{esc(ru)}</seg></tuv>',
            "    </tu>",
        ]
    lines += ["  </body>", "</tmx>"]
    path.write_text("\n".join(lines), encoding="utf-8")


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"[!] Нет PDF в {PDF_DIR}. Сначала запусти download_pdfs.py")
        return

    all_pairs: list[tuple[str, str]] = []
    stats = []

    for i, pdf_path in enumerate(pdf_files, 1):
        topic = pdf_path.stem.replace("_RU", "").replace("_", " ")
        print(f"[{i:03}/{len(pdf_files)}] {pdf_path.name}")

        pairs = extract_column_pairs(pdf_path)
        all_pairs.extend(pairs)
        stats.append({"file": pdf_path.name, "topic": topic, "pairs": len(pairs)})
        print(f"    {len(pairs)} пар")

    tsv_path = OUTPUT_DIR / "tm.tsv"
    tmx_path = OUTPUT_DIR / "tm.tmx"
    json_path = OUTPUT_DIR / "tm.json"
    stats_path = OUTPUT_DIR / "stats.json"

    write_tsv(all_pairs, tsv_path)
    write_tmx(all_pairs, tmx_path)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([{"en": e, "ru": r} for e, r in all_pairs], f, ensure_ascii=False, indent=2)

    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\n=== Итого: {len(all_pairs)} пар из {len(pdf_files)} PDF ===")
    print(f"  TM TSV:  {tsv_path}")
    print(f"  TM TMX:  {tmx_path}")
    print(f"  JSON:    {json_path}")


if __name__ == "__main__":
    run()
