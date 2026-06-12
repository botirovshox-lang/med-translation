# Backend — Medical CAT Translator v5.5 (FastAPI)

Single FastAPI app that:
- Serves the React frontend (from `../frontend/`) at `/`
- Exposes REST API at `/api/*`
- Persists state to `backend/data/state.json`
- Falls back to demo translations if `OPENAI_API_KEY` / `GOOGLE_TRANSLATE_API_KEY` are not set

## Run locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# open http://localhost:8000
```

Or on Windows: double-click `run.bat`.

## Environment variables

| Var | Purpose | Default |
|-----|---------|---------|
| `APP_PASSWORD` | Login password | `medtranslator2026` |
| `OPENAI_API_KEY` | Real GPT translation | (optional) |
| `GOOGLE_TRANSLATE_API_KEY` | Real Google translation | (optional) |

Without API keys the backend returns *demo* translations so all buttons remain testable.

## Endpoints

- `GET  /api/health` — diagnostics
- `GET  /api/seed` — full bootstrap data
- `POST /api/auth/login` — `{password}` → 200 or 401
- `GET  /api/projects`
- `POST /api/projects` — `{title, src, tgt, fileName?}`
- `GET  /api/projects/{pid}`
- `POST /api/segments/{pid}/{sid}/translate` — `{engine: "google"|"gpt"}`
- `POST /api/segments/{pid}/{sid}/qa`
- `POST /api/segments/{pid}/{sid}/confirm`
- `POST /api/segments/{pid}/{sid}/revert`
- `POST /api/segments/{pid}/{sid}/update` — `{target?, status?, comment?}`
- `POST /api/projects/{pid}/batch` — `{engine}`
- `POST /api/projects/{pid}/preflight`
- `POST /api/projects/{pid}/export` — `{format}`
- `POST /api/glossary` — `{src, tgt, cat, freq, conf, isNew}`
- `DELETE /api/glossary?src=...`
- `DELETE /api/tm?src=...`
