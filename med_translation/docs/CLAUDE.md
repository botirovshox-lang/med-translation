# CLAUDE.md — Medical Translation TM Builder

## Контекст проекта

**med_translation** — система для построения медицинского глоссария и translation memory (TM) из билингвальных PDF медлайна (EN↔RU).

Полная архитектура: **CONTEXT.md**
История: **CHANGELOG.md**
Приоритеты: **BACKLOG.md**

---

## Обязательные правила

### Код
- **Язык:** Python 3.14+
- **Зависимости:** requirements.txt (pdfplumber, anthropic, requests, beautifulsoup4)
- **UTF-8 везде:** `$env:PYTHONUTF8=1` перед запуском Python

### Директории
```
med_translation/
  download_pdfs.py      — скачиватель (356 ссылок → 210 PDF)
  extract_tm.py         — экстрактор TM из PDF (695 пар EN↔RU)
  build_glossary.py     — глоссарий из терминов (Claude API)
  
  pdfs/                 — 210 скачанных PDF (Google Cloud Storage)
  pdf_index.json        — метаданные всех ссылок
  
  output/
    tm.tsv              — 695 пар для CAT (Trados, OmegaT)
    tm.tmx              — TMX 1.4 формат
    tm.json             — JSON с EN/RU парами
    glossary.tsv        — термины EN / RU / категория
    glossary.json       — структурированный глоссарий
    stats.json          — статистика по файлам
```

### Переменные окружения
```powershell
$env:ANTHROPIC_API_KEY = 'sk-ant-...'    # для build_glossary.py
$env:PYTHONUTF8 = '1'                     # всегда UTF-8
```

### API / Сервисы
- **MedlinePlus** `https://medlineplus.gov/languages/russian.html` — источник 356 PDF
- **Google Cloud Storage** — хостинг всех PDF (healthinfotranslations-pdfdocs)
- **Claude API** (claude-haiku-4-5-20251001) — извлечение терминов
  - Батчинг: 8 пар за запрос (~87 запросов на 695 пар)
  - Prompt caching: экономия ~80% input-токенов
  - Стоимость: ~$0.05–0.10

### Форматы выходных данных
- **TSV:** EN\tRU\tCategory (или просто EN\tRU)
- **TMX 1.4:** XML для CAT-инструментов
- **JSON:** массив `{en, ru, category}` для программ

---

## Архитектурные решения

### Извлечение TM из PDF
1. **Автодетекция разделителя колонок:** анализируем распределение x-координат слов
   - находим наибольший gap между левой и правой половиной
   - точка разделения для двухколоночного макета
2. **Построчная обработка:** группируем слова по Y-координатам (строки)
   - Левая колонка → EN, правая → RU
   - Объединяем строки в сегменты (параграфы)
3. **Фильтрация шума:** удаляем номера страниц, URL, заголовки
4. **Дедупликация:** удаляем кириллицу из EN-текста (попала из заголовков)

### Извлечение глоссария (Claude API)
1. **Батчинг:** группируем по 8 пар, отправляем одним запросом
2. **Prompt caching:** системный промпт кэшируется → экономия токенов
3. **Категоризация:** diagnosis | symptom | procedure | anatomy | medication | test | other_medical
4. **Checkpoint:** сохраняем прогресс каждые 10 батчей (перезапуск после ошибки)
5. **Дедупликация:** финальная по (en, ru)

---

## Запуск

```bash
# 1. Скачать все 356 PDF → 210 файлов
python download_pdfs.py

# 2. Извлечь 695 билингвальных пар
python extract_tm.py

# 3. Построить глоссарий (требует ANTHROPIC_API_KEY)
$env:ANTHROPIC_API_KEY = 'sk-ant-...'
python build_glossary.py
```

---

## Что НЕ трогать

- `pdfs/` — скачанные файлы, очень большие
- `pdf_index.json` — метаданные, нужны для переdownload
- `output/tm.*` — исходные пары, основа для всего остального

---

## Переменные и конфиги

| Переменная | Значение | Тип |
|-----------|---------|-----|
| `BASE_URL` | `https://medlineplus.gov/languages/russian.html` | str |
| `MODEL` | `claude-haiku-4-5-20251001` | str |
| `BATCH_SIZE` | `8` | int |
| `DELAY` | `1.2` (между PDF), `0.5` (между API) | float |
| `BATCH_SIZE_GLOSSARY` | `8` пар на запрос | int |

Все в корне файлов (`download_pdfs.py`, `extract_tm.py`, `build_glossary.py`).

---

## Следующие итерации

- [ ] NER для выделения именованных сущностей (лекарства, болезни)
- [ ] Частотный анализ терминов (какие медицинские термины в TM самые частые)
- [ ] Интеграция с OmegaT / Trados (загрузка TM через API)
- [ ] REST API для запросов к глоссарию
- [ ] Веб-интерфейс поиска по TM/глоссарию
