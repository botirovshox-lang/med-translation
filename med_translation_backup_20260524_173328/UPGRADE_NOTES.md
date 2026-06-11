# Upgrade to v5.5 Hybrid (Soft Merge)

## Что произошло

✅ **Сохранено**:
- Все файлы глоссариев в `assets/glossary/` (approved, reference, forbidden, tm)
- Все наши модули Anthropic (terminology_engine, risk_engine, workflow_engine, etc.)
- Все исторические скрипты (deep_clean, recover_fp, etc.) — для справки

✅ **Добавлено (v5.5)**:
- DOCX CAT workflow (import/export)
- SQLite база данных для управления проектами и сегментами
- OpenAI integration (QA, back-check, safety review)
- Структурированные ответы через Pydantic (schemas)
- Новый интегрированный UI (`app_v55.py`)

## Файлы версии 5.5

```
config_v55.py       ← конфиг (API keys, пути, пороги)
db.py              ← SQLite: projects, segments, glossary, TM
schemas.py         ← Pydantic модели (QAReport, BackTranslationReport, etc.)
prompts.py         ← промпты для OpenAI
openai_client.py   ← OpenAI API-вызовы
pipeline.py        ← функции: translate, QA, back-check, extract_terms, safety_decision
docx_cat.py        ← импорт/экспорт DOCX
tm.py              ← мост между нашим TM и v5.5 app
app_v55.py         ← основное веб-приложение Streamlit
.env.example       ← шаблон для OpenAI и Anthropic API keys
```

## Запуск

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

(Уже включены: streamlit, python-docx, openai, anthropic, python-dotenv)

### 2. Создать .env

```bash
cp .env.example .env
```

Заполнить:
```
OPENAI_API_KEY=sk-proj-...        # для QA, back-check, safety review
ANTHROPIC_API_KEY=sk-ant-...      # для нашей глоссарной системы
DEFAULT_TRANSLATION_MODEL=gpt-5.5
DEFAULT_REVIEW_MODEL=gpt-5.5
```

### 3. Запустить

```bash
streamlit run app_v55.py
```

## Архитектура (гибридная)

```
OpenAI (v5.5)                          Anthropic + Наша система
├─ Translate (gpt-5.5)        ←→      Glossary lookup (term_engine)
├─ QA scoring                  ←→      Risk scoring
├─ Back-check (semantic)       ←→      Workflow recommendation
├─ Safety review               ←→      Forbidden term check
└─ TM: SQLite DB (обучается)   ←→      TM: MedlinePlus (366 сегм.)
```

## Таблицы SQLite

```sql
projects                  -- проекты DOCX
segments                  -- сегменты с переводами, QA, back-check
glossary                  -- project-specific термины
translation_memory        -- пользовательское TM (растёт при подтверждении сегментов)
```

## Что сохранилось из старой версии

### Наши модули (для справки/расширения):

- `terminology_loader.py` — инвертированный индекс для быстрого поиска терминов
- `terminology_engine.py` — сопоставление терминов с сегментом  
- `risk_engine.py` — правил-основанная оценка риска (11 паттернов)
- `workflow_engine.py` — рекомендация рабочего процесса по риску
- `forbidden_checker.py` — проверка запрещённых переводов
- `tm_loader.py` — загрузчик TM из MedlinePlus (366 сегментов)

### Глоссарии (в assets/glossary/):

- `approved_glossary_FINAL.tsv` (10,022 термина) — утверждённые
- `reference_glossary_FINAL.tsv` (59,577) — справочные
- `forbidden_translations_FINAL.tsv` (189) — запрещённые переводы
- `tm_reference_FINAL.tsv` (366) — TM MedlinePlus

## Интеграция

Мост между v5.5 и нашей системой:

1. **TM поиск** (`tm.py`):
   - v5.5 вызывает `find_tm_suggestion(source_text)`
   - Ищет в нашем TM (366 MedlinePlus сегментов)
   - Возвращает 100% совпадение или None
   - На фоне работает SQLite TM (растёт по мере подтверждения)

2. **Глоссарий**:
   - v5.5 использует `glossary_prompt(project_id)` для инжекции в промпт OpenAI
   - Наша система может предоставить дополнительные проверки через Anthropic

3. **Расширяемость**:
   - В `pipeline.py` легко добавить вызовы нашего risk_engine, back_translation_check и т.д.
   - В `openai_client.py` можно добавить fallback на Anthropic если OpenAI недоступен

## Резервная копия

Старая версия сохранена в:
```
C:\Users\Shox\med_translation\med_translation_backup_20260524_173328/
```

## Следующие шаги

1. ✅ Запустить `app_v55.py`
2. ✅ Импортировать DOCX для тестирования
3. ✅ Проверить QA и back-check с OpenAI
4. 🔲 (Опционально) Интегрировать risk_engine для автоматической маршрутизации workflow
5. 🔲 (Опционально) Добавить в QA проверку нашей forbidden_checker

## Поддержка

- **Anthropic API**: используется нашей системой (glossary, risk scoring)
- **OpenAI API**: используется v5.5 (translate, QA, back-check, safety)
- **Оба API в .env** → система работает в full-hybrid режиме
- **Только OpenAI** → v5.5 функционирует, наша система ограничена (требует Anthropic для полноты)
