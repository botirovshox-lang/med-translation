# Medical CAT Translator v5.5 — backend container
# Works on: Render.com / Railway / Fly.io / any Docker-capable VPS

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Backend deps
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/backend/requirements.txt

# Copy backend + frontend (frontend served as static by FastAPI)
COPY backend /app/backend
COPY frontend /app/frontend

# Try to install existing med_translation modules too (best-effort; optional)
COPY med_translation /app/med_translation
RUN pip install python-docx openai google-cloud-translate anthropic 2>/dev/null || true

# Persistent data dir (Render mounts /var/data if disk attached)
RUN mkdir -p /app/backend/data

EXPOSE 8000

# Render/Fly inject $PORT — fall back to 8000 locally
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
