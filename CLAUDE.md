# CLAUDE.md — Medical CAT Translator (корень репозитория)

Правила для AI-ассистентов и разработчиков. Прочти перед любыми изменениями.

## Что здесь актуально

- **`backend/main.py`** — весь продакшен-бэкенд (FastAPI, ~25 эндпоинтов). Одним файлом, это осознанно.
- **`backend/medical_qa.py`** — медицинский QA (структурные/числовые проверки, обратный перевод).
- **`frontend/`** — React 18 **без сборки**: UMD + Babel standalone, `.jsx` компилируются в браузере.
- **`deploy/medcat.service`** — источник истины для systemd-юнита (копируется в `/etc/systemd/system/`).
- **`med_translation/`** — legacy Streamlit-код; из него используются только модули
  (глоссарий TSV в `assets/glossary/`, `medical_qa`, `tm`, `db`, `pipeline`) через `sys.path` в `main.py`.
- **`med_translation/CLAUDE.md`** — правила отдельного legacy-подпроекта (TM-билдер из PDF), не про этот бэкенд.

## Жёсткие инварианты (нарушение = потеря данных)

1. **Ровно 1 uvicorn worker.** `STATE` — глобальный dict в памяти процесса,
   `state.json` — его снапшот. Два воркера затирают данные друг друга.
2. **Все мутации `STATE` заканчиваются `save_state(STATE)`.** Запись атомарна
   (tmp + `os.replace` под `_SAVE_LOCK`) — не заменяй на прямую запись.
3. **Писать на диск можно только в `backend/data/`** (systemd `ProtectSystem=full`,
   `ReadWritePaths`). Экспорты — в `data/exports/`, бэкапы — в `data/backups/`.
4. **Никаких демо-заглушек в target.** Ошибка перевода → HTTP 502 / `{"ok": false, "error": ...}`,
   сегмент не трогать. То же на фронтенде: не подставлять фейковый текст при недоступном сервере.
5. **Изменил `frontend/js/*` → бампни `?v=` во всех строках `frontend/index.html`.**
   Иначе пользователи получат старый кэш и «загадочные» баги.

## Деплой (VPS 31.129.100.106, домен trasnlateuz.duckdns.org)

```bash
cd /opt/med-translation && git pull
systemctl restart medcat          # ~3 сек простоя
curl -s http://127.0.0.1:8000/api/health   # должен вернуть ok:true и projects>=1
```
Секреты в `/etc/medcat/env` (не в git): `APP_PASSWORD`, `OPENAI_API_KEY`, `GOOGLE_TRANSLATE_API_KEY`.

## Проверка после изменений (минимум)

```bash
.venv/bin/python -m py_compile backend/main.py
curl -s http://127.0.0.1:8000/api/health
# смоук: создать проект → перевести сегмент (google) → preflight → export docx → удалить проект
```

## Что НЕ трогать

- `med_translation_backup_*/`, `версии/` — архивы.
- `backend/data/` в git не хранится (боевые данные пользователей!).
- Чужие проекты на VPS: `/opt/kamola`, `/opt/focus-os`, `/opt/tat-*`, `/opt/personal-finance` и пр.

## Известные особенности

- Google-ключ может быть невалиден (403) — код помечает его мёртвым до рестарта
  и работает через бесплатный `deep-translator` + GPT-fallback. Это деградация, не падение.
- `load_state()` при битом `state.json` сохраняет его как `state.corrupt-*` и
  поднимает свежайший бэкап из `data/backups/` (48 почасовых копий).
- PDF-экспорт не реализован; DOCX/XLSX собираются по-настоящему (python-docx / openpyxl).
