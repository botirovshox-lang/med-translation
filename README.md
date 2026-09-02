# Medical CAT Translator v5.6

Система перевода медицинских документов (RU→EN) в стиле CAT-инструмента:
импорт DOCX → сегментация → перевод (Google / GPT + глоссарий + TM) → QA и back-check
→ подтверждение → экспорт DOCX/XLSX.

**Продакшен:** https://simpletranslate.me (VPS, systemd-сервис `medcat`).
Прежний адрес https://trasnlateuz.duckdns.org продолжает работать — на него
ведут закладки и старые ссылки.

---

## Актуальная архитектура

> ⚠️ Историческая справка: до июня 2026 проект был Streamlit-приложением с SQLite
> (код лежит в `med_translation/` и используется только как библиотека модулей).
> Актуальный стек описан ниже; старые разделы README/доков про Streamlit/Railway/SQLite устарели.

```
Браузер (React 18 + Babel standalone, без сборки)
   │  frontend/index.html + frontend/js/*.jsx
   ▼
nginx (443, Let's Encrypt) ──► uvicorn 127.0.0.1:8000 (1 worker!)
                                  │  backend/main.py  (FastAPI, ~25 эндпоинтов)
                                  │  backend/medical_qa.py (медицинский QA)
                                  ▼
                    backend/data/state.json  ← ЕДИНСТВЕННОЕ хранилище
                    backend/data/backups/    ← почасовые бэкапы (48 шт.)
                    backend/data/exports/    ← сгенерированные DOCX/XLSX
```

| Слой        | Технология |
|-------------|-----------|
| Backend     | FastAPI + uvicorn, systemd-юнит `medcat.service` (user `medcat`) |
| Frontend    | React 18 UMD + Babel standalone из CDN, `.jsx` компилируются в браузере |
| Хранилище   | `backend/data/state.json` — in-memory + атомарная запись на каждое изменение |
| Переводчики | Google Cloud Translation v2 (по ключу) → fallback `deep-translator` (бесплатный); OpenAI с инъекцией глоссария и TM — модель выбирается в UI из каталога `OPENAI_MODELS` |
| Глоссарий   | ~500 терминов из `med_translation/assets/glossary/approved_glossary_FINAL.tsv` |
| Секреты     | `/etc/medcat/env` (`APP_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_TRANSLATE_API_KEY`) |

### Ключевые инварианты

1. **Строго 1 uvicorn worker.** Состояние живёт в памяти процесса и сбрасывается
   в `state.json`. Несколько воркеров = несколько копий состояния, затирающих друг друга.
2. **Запись state.json атомарна** (tmp + `os.replace` под локом) и делает почасовой
   бэкап в `backups/`. При повреждении файла загрузчик восстановит свежайший бэкап,
   а битый файл сохранит как `state.corrupt-*` — данные не теряются молча.
3. **Никаких демо-заглушек в переводах.** Если оба движка упали — API возвращает 502,
   фронтенд показывает ошибку, сегмент не меняется.
4. **systemd:** `ProtectSystem=full`, писать можно только в `backend/data`
   (поэтому экспорты и бэкапы живут там). `ExecStartPre` создаёт каталог данных,
   иначе mount namespacing не даст сервису стартовать.
5. **Кэш фронтенда:** при каждом изменении `frontend/js/*` бампайте `?v=` в
   `frontend/index.html` (браузеры кэшируют .jsx намертво).
6. **Модели и цены правятся только в `OPENAI_MODELS`** (`backend/main.py`).
   Фронтенд берёт каталог через `/api/models` и ничего не хардкодит.

---

## Контроль качества

**Локальный QA** (`/qa`) — числа, длина, без вызовов модели.

**Медицинский QA** (`/medical-qa`) — `backend/medical_qa.py`: структурные и числовые
проверки, обратный перевод, term candidates.

**Back-check** (`/backcheck`) — переводит готовый target обратно на язык оригинала и
сравнивает с исходником: числа, единицы, отрицания, лево-право, сохранность терминов.

- Для обратного перевода нужна **буквальная** модель: умная незаметно чинит ошибки
  перевода и прячет ровно то, что проверка ищет.
- Балл 0-100 + полоса; границы полос отдаёт бэкенд (`/api/models` → `backcheckBands`),
  чтобы не разъезжались с фронтендом.
- **LLM-судья** разбирает только среднюю зону (`JUDGE_ZONE`, сейчас 50-97%): по краям
  шкалы вопрос уже решён детерминированными проверками. У судьи своя модель — сильная,
  в отличие от буквальной модели обратного перевода.
- Эмбеддинги (`text-embedding-3-small`) работают только по краям шкалы. В середине они
  вредны: подмена «левое/правое лёгкое» даёт косинус выше, чем безобидная перефразировка.
- Результат лежит в `seg["backcheck"]` вместе с `target_hash` и id модели. Повторный
  прогон по ним понимает, что пересчитывать нечего; в выдаче проекта добавляется
  производный `stale` — перевод изменился после проверки. В UI это блок
  «Что проверять» с галочками по группам.

---

## Запуск локально

```bash
pip install -r backend/requirements.txt python-docx openpyxl deep-translator openai requests
uvicorn backend.main:app --reload --port 8000
# открыть http://localhost:8000  (пароль по умолчанию: medtranslator2026)
```

## Деплой на VPS

```bash
ssh root@31.129.100.106
cd /opt/med-translation && git pull
# при изменении frontend/js/* — бампнуть ?v= в frontend/index.html ДО пуша
systemctl restart medcat
# сервис поднимается ~15 с (грузит state.json и глоссарий) — не проверяйте сразу
for i in $(seq 1 15); do sleep 2; curl -s --max-time 5 http://127.0.0.1:8000/api/health && break; done
```

- Репозиторий на VPS принадлежит пользователю `medcat`, а деплой идёт от root, поэтому
  `/opt/med-translation` добавлен в `git config --global safe.directory` root'а.
  Часть объектов в `.git` уже принадлежит root — пул от `medcat` теперь не пройдёт.
- `git pull | tail` съедает код возврата пула: сбой останется незамеченным, а рестарт
  всё равно случится и поднимет старый код. Проверяйте `git log -1` после пула.

Полный сетап нового сервера: `deploy/setup_vps.sh`, `BEGET_VPS_DEPLOY.md`.

---

## API (основное)

| Метод | Путь | Что делает |
|-------|------|-----------|
| POST | `/api/auth/login` | Проверка пароля (SHA256 от `APP_PASSWORD`) |
| GET  | `/api/seed` | Все данные для старта UI (глоссарий обрезан до 150) |
| GET  | `/api/models` | Каталог моделей с ценами, дефолты, зона судьи, полосы back-check |
| GET  | `/api/projects/{pid}` | Проект с сегментами (у `backcheck` добавляется `stale`) |
| POST | `/api/projects/upload` | Импорт DOCX → сегменты |
| POST | `/api/segments/{pid}/{sid}/translate` | Перевод: `{engine: "google"\|"gpt", model, force}` |
| POST | `/api/projects/{pid}/batch` | Пакетный перевод порциями |
| POST | `/api/segments/{pid}/{sid}/qa` | Локальный QA (числа, длина) |
| POST | `/api/segments/{pid}/{sid}/medical-qa` | Медицинский QA + обратный перевод |
| POST | `/api/segments/{pid}/{sid}/backcheck` | Back-check одного сегмента |
| POST | `/api/projects/{pid}/backcheck/batch` | Пакетный back-check: `{segment_ids, model, use_judge, judge_model, skip_cached}` |
| POST | `/api/projects/{pid}/preflight` | Маршруты/сложность по сегментам |
| POST | `/api/projects/{pid}/export` | Сборка файла: `{format: "docx"\|"xlsx", source}` |
| GET  | `/api/projects/{pid}/export/download` | Скачивание собранного файла |
| GET  | `/api/health` | Статус, версия, загруженные модули |

Маршруты сегментов: `EXACT_TM` (из TM, $0) → `DUPLICATE` → `GOOGLE_SAFE` (низкий риск)
→ `GPT_REQUIRED` → `HUMAN_REVIEW`.

⚠️ `seg["risk"]` — это **длина сегмента**, а не медицинская опасность: `words > 30 → high`,
`words > 8 → medium`, иначе `low`. Содержание не разбирается. Настоящий `risk_score`
даёт только медицинский QA, и он есть далеко не у всех сегментов.

---

## Обслуживание

```bash
journalctl -u medcat -f                        # логи
ls backend/data/backups/                       # почасовые бэкапы состояния
python3 -c "import json; json.load(open('backend/data/state.json'))"  # проверка целостности
```

**Восстановление после сбоя:** свежайший `backups/state-*.json` → скопировать в
`backend/data/state.json` → `systemctl restart medcat`.

**Известные ограничения:**
- Google Translate API-ключ в `/etc/medcat/env` невалиден (403) — переводы идут через
  бесплатный fallback и GPT. Новый ключ: Google Cloud Console → включить Cloud
  Translation API → пересоздать ключ → `systemctl restart medcat`.
- Экспорт в PDF пока не реализован (UI честно сообщает об этом).
- Авторизация — общий пароль без сессий; CORS `*`. Для внутреннего инструмента ок.

---

## Структура репозитория

```
backend/            ← АКТУАЛЬНЫЙ бэкенд (FastAPI)
frontend/           ← АКТУАЛЬНЫЙ фронтенд (React без сборки)
deploy/             ← systemd-юнит, nginx-конфиг, setup-скрипт
docs/               ← CHANGELOG, ARCHITECTURE (частично устарел), решения
med_translation/    ← legacy Streamlit-приложение; используется как библиотека
                      (глоссарий TSV, medical_qa, tm и пр.)
med_translation_backup_*/  ← архив, не трогать
CLAUDE.md           ← правила работы с репо для AI-ассистентов
```

**Последнее обновление:** 2026-08-17
