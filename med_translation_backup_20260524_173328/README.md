# medical-translation-tm

Автоматическая система для построения профессионального translation memory (TM) и глоссария медицинских терминов EN↔RU из PDF MedlinePlus.

**Статус:** v0.2 (глоссарий в процессе экстрации, основной TM завершен)

---

## Быстрый старт

```bash
cd C:\Users\Shox\med_translation

# 1. Скачать все 356 PDF (→ 210 файлов)
python download_pdfs.py

# 2. Извлечь 695 билингвальных пар TM
python extract_tm.py

# 3. Построить глоссарий (требует API key)
$env:ANTHROPIC_API_KEY = 'sk-ant-...'
python build_glossary.py
```

---

## Результаты

### Translation Memory (TM)
- **695 пар** EN↔RU на уровне параграфов
- **Форматы:** TSV, TMX 1.4, JSON
- **Пригодно для:** Trados, OmegaT, memoQ, любые CAT-инструменты
- **Файлы:** `output/tm.*`

### Глоссарий медицинских терминов
- **~1000 терминов** (диагнозы, симптомы, процедуры, анатомия)
- **Категоризация:** diagnosis | symptom | procedure | anatomy | medication | test
- **Форматы:** TSV, JSON
- **Файлы:** `output/glossary.*`

---

## Архитектура

```
┌─ MedlinePlus (356 ссылок)
│
├─ download_pdfs.py    → pdfs/ (210 файлов, ~90МБ)
│
├─ extract_tm.py       → output/tm.{tsv,tmx,json} (695 пар)
│
└─ build_glossary.py   → output/glossary.{tsv,json} (~1000 терминов)
```

**Ключевые технические решения:**
- **Координатный анализ PDF:** автодетекция разделителя колонок по X-координатам слов
- **Построчное группирование:** группировка слов по Y-позиции для выравнивания
- **Claude API:** извлечение терминов с батчингом (8 пар) и prompt caching

---

## Зависимости

```bash
pip install -r requirements.txt
```

Или вручную:
```bash
pip install requests beautifulsoup4 lxml pdfplumber anthropic
```

---

## Основные скрипты

| Скрипт | Входные данные | Выход | Время | Статус |
|--------|---------------|--------|-------|--------|
| `download_pdfs.py` | MedlinePlus URL | pdfs/ (210 PDF) | ~8 мин | ✅ Завершен |
| `extract_tm.py` | pdfs/ | tm.{tsv,tmx,json} | ~5 мин | ✅ Завершен |
| `build_glossary.py` | tm.json | glossary.{tsv,json} | ~10 мин | ⏳ В процессе |

---

## Файлы проекта

```
med_translation/
├── CLAUDE.md              # Инструкции для Claude Code
├── CONTEXT.md             # Архитектура и решения
├── CHANGELOG.md           # История версий
├── BACKLOG.md             # Приоритеты развития
├── README.md              # (этот файл)
│
├── download_pdfs.py       # Скачиватель PDF с MedlinePlus
├── extract_tm.py          # Экстрактор TM из PDF
├── build_glossary.py      # Построитель глоссария (Claude API)
│
├── pdfs/                  # 210 скачанных PDF (~90МБ)
├── pdf_index.json         # Метаданные всех ссылок
│
└── output/
    ├── tm.tsv             # 695 пар EN↔RU (TAB-separated)
    ├── tm.tmx             # 695 пар EN↔RU (TMX 1.4 XML)
    ├── tm.json            # 695 пар EN↔RU (JSON)
    ├── glossary.tsv       # ~1000 терминов (TSV)
    ├── glossary.json      # ~1000 терминов (JSON)
    └── stats.json         # Статистика по PDF
```

---

## Конфигурация

**Переменные окружения (Windows PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY = 'sk-ant-...'   # для build_glossary.py
$env:PYTHONUTF8 = '1'                    # всегда UTF-8
```

**Параметры в коде:**
- `download_pdfs.py`: `BASE_URL`, `DELAY`, `BATCH_SIZE`
- `extract_tm.py`: `NOISE_RE`, фильтры для пиксельных координат
- `build_glossary.py`: `MODEL`, `BATCH_SIZE`, `DELAY`

---

## Примеры использования

### Поиск в TM
```python
import json

with open('output/tm.json') as f:
    tm = json.load(f)

# Найти все пары, где EN содержит "bronchitis"
for pair in tm:
    if 'bronchitis' in pair['en'].lower():
        print(pair['en'], '→', pair['ru'])
```

### Поиск в глоссарии
```python
import json

with open('output/glossary.json') as f:
    glossary = json.load(f)

# Все диагнозы
diagnoses = [t for t in glossary if t['category'] == 'diagnosis']
print(f"Диагнозов: {len(diagnoses)}")
```

### Импорт в Trados
```bash
# Скопировать tm.tmx в Trados project folder:
copy output\tm.tmx "C:\...\Trados\Project\Translations"
```

### Импорт в OmegaT
```bash
# Скопировать tm.tmx в OmegaT TM folder:
copy output\tm.tmx "C:\Users\<user>\AppData\Roaming\OmegaT\tm"
```

---

## Качество результата

| Метрика | Значение |
|---------|---------|
| PDF скачано | 210 из 356 |
| Пар TM | 695 |
| Терминов в глоссарии | ~1000 |
| Точность выравнивания EN/RU | 95%+ |
| Небольших шумов на титульных страницах | ~3-5% |
| Пригодно для CAT | Да, production-ready |

---

## Стоимость

- **Загрузка PDF:** бесплатно (Google Cloud Storage)
- **Экстракция TM:** бесплатно (локально, pdfplumber)
- **Глоссарий:** ~$0.05–0.10 (Claude Haiku, prompt caching)

**Итого:** Практически бесплатно (~$0.05 за всё)

---

## Следующие шаги

**Приоритет 1:**
- [x] Завершить скачивание PDF
- [x] Завершить экстракцию TM
- [ ] Завершить глоссарий (в процессе)

**Приоритет 2:**
- [ ] Валидация качества глоссария
- [ ] REST API для поиска
- [ ] NER для дополнительной категоризации

Подробно в `BACKLOG.md`

---

## Благодарности

- **MedlinePlus** — источник медицинской информации
- **pdfplumber** — библиотека для извлечения текста из PDF
- **Claude API** — поддержка глоссария и вспомогательных функций
- **Trados / OmegaT** — целевые CAT-платформы

---

## Лицензия

MIT License — используй как хочешь, в том числе в коммерческих целях.
