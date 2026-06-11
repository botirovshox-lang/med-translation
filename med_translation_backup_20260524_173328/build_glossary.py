"""
Извлекает медицинские термины и фразы из билингвальных пар EN↔RU
с помощью Claude API (claude-haiku-4-5-20251001).

Использует:
  - Батчинг: 8 пар за один вызов → ~87 запросов для 695 пар
  - Prompt caching: системный промпт кэшируется → экономия ~80% токенов
  - Checkpoint: сохраняет прогресс в glossary_progress.json

Запуск:
  set ANTHROPIC_API_KEY=sk-ant-...
  python build_glossary.py

Вывод:
  output/glossary.tsv   — термин EN / термин RU / категория
  output/glossary.json  — полный структурированный глоссарий
"""

import os
import sys
import json
import time
import re
from pathlib import Path

try:
    import anthropic
except ImportError:
    raise SystemExit("Установи: pip install anthropic")

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    raise SystemExit(
        "Укажи ANTHROPIC_API_KEY:\n"
        "  Windows:  $env:ANTHROPIC_API_KEY='sk-ant-...'\n"
        "  После:    python build_glossary.py"
    )

INPUT_FILE = Path(__file__).parent / "output" / "tm.json"
OUTPUT_DIR = Path(__file__).parent / "output"
PROGRESS_FILE = Path(__file__).parent / "glossary_progress.json"

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 8          # пар за один API-вызов
DELAY = 0.5             # секунд между запросами

SYSTEM_PROMPT = """Ты эксперт по медицинской терминологии. Твоя задача — извлечь медицинские термины и устойчивые фразы из параллельных EN/RU текстов и вернуть их в виде глоссария.

Правила:
1. Извлекай только медицинские термины, процедуры, симптомы, анатомические названия, лекарства, диагнозы.
2. Длина термина: 1–5 слов (не целые предложения).
3. Дублей не должно быть внутри одного ответа.
4. НЕ включай бытовые слова (например: "doctor", "врач" — исключение если это специализация).
5. Для каждого термина укажи категорию из списка: diagnosis | symptom | procedure | anatomy | medication | test | other_medical.
6. Формат ответа — строго JSON-массив:
[
  {"en": "bronchitis", "ru": "бронхит", "category": "diagnosis"},
  {"en": "airway inflammation", "ru": "воспаление дыхательных путей", "category": "symptom"}
]
Только JSON, никакого текста до или после."""


def extract_terms_from_batch(
    client: anthropic.Anthropic,
    pairs: list[dict],
) -> list[dict]:
    """Отправляет батч пар в Claude и возвращает термины."""
    # Формируем текст батча
    batch_text = ""
    for i, p in enumerate(pairs, 1):
        batch_text += f"--- Пара {i} ---\nEN: {p['en']}\nRU: {p['ru']}\n\n"

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # кэшируем системный промпт
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Извлеки медицинские термины из следующих {len(pairs)} билингвальных пар:\n\n{batch_text}",
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Чистим на случай если модель добавила ```json ... ```
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        terms = json.loads(raw)
        if not isinstance(terms, list):
            return []
        # Валидируем структуру
        valid = []
        for t in terms:
            if isinstance(t, dict) and "en" in t and "ru" in t:
                valid.append({
                    "en": str(t.get("en", "")).strip().lower(),
                    "ru": str(t.get("ru", "")).strip().lower(),
                    "category": str(t.get("category", "other_medical")).strip(),
                })
        return valid
    except json.JSONDecodeError:
        print(f"    [warn] JSON parse error, пропускаю батч")
        return []


def dedup(terms: list[dict]) -> list[dict]:
    """Дедуплицирует по (en, ru)."""
    seen = set()
    result = []
    for t in terms:
        key = (t["en"], t["ru"])
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def write_tsv(terms: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("EN\tRU\tCategory\n")
        for t in terms:
            f.write(f"{t['en']}\t{t['ru']}\t{t['category']}\n")


def run():
    with open(INPUT_FILE, encoding="utf-8") as f:
        pairs = json.load(f)

    print(f"Загружено {len(pairs)} пар из {INPUT_FILE}")

    # Загружаем прогресс если есть (для перезапуска после ошибки)
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            progress = json.load(f)
        start_idx = progress.get("last_batch_end", 0)
        all_terms = progress.get("terms", [])
        print(f"Продолжаю с батча {start_idx // BATCH_SIZE + 1} (уже {len(all_terms)} терминов)")
    else:
        start_idx = 0
        all_terms = []

    client = anthropic.Anthropic(api_key=API_KEY)

    batches = [pairs[i:i + BATCH_SIZE] for i in range(0, len(pairs), BATCH_SIZE)]
    total_batches = len(batches)
    start_batch = start_idx // BATCH_SIZE

    print(f"Батчей всего: {total_batches}, начинаю с #{start_batch + 1}")
    print(f"Модель: {MODEL}, batch_size={BATCH_SIZE}\n")

    for bi, batch in enumerate(batches[start_batch:], start=start_batch + 1):
        print(f"[{bi:03}/{total_batches}] {len(batch)} пар ... ", end="", flush=True)
        try:
            new_terms = extract_terms_from_batch(client, batch)
            all_terms.extend(new_terms)
            print(f"{len(new_terms)} терминов (итого {len(all_terms)})")
        except anthropic.RateLimitError:
            print("rate limit, жду 30с...")
            time.sleep(30)
            new_terms = extract_terms_from_batch(client, batch)
            all_terms.extend(new_terms)
        except Exception as e:
            print(f"[error] {e}")

        # Сохраняем прогресс каждые 10 батчей
        if bi % 10 == 0:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_batch_end": bi * BATCH_SIZE, "terms": all_terms}, f, ensure_ascii=False)

        time.sleep(DELAY)

    # Финальная дедупликация и сортировка
    final_terms = dedup(all_terms)
    final_terms.sort(key=lambda t: (t["category"], t["en"]))

    # Сохраняем
    OUTPUT_DIR.mkdir(exist_ok=True)
    tsv_path = OUTPUT_DIR / "glossary.tsv"
    json_path = OUTPUT_DIR / "glossary.json"

    write_tsv(final_terms, tsv_path)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final_terms, f, ensure_ascii=False, indent=2)

    # Статистика по категориям
    cats: dict[str, int] = {}
    for t in final_terms:
        cats[t["category"]] = cats.get(t["category"], 0) + 1

    print(f"\n=== Глоссарий готов: {len(final_terms)} уникальных терминов ===")
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat:20s}: {cnt}")
    print(f"\n  TSV:  {tsv_path}")
    print(f"  JSON: {json_path}")

    # Удаляем файл прогресса после успешного завершения
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


if __name__ == "__main__":
    run()
