"""
FastAPI backend for Medical CAT Translator v5.5
Serves the React design at /, exposes REST API at /api/*

Endpoints:
  GET  /api/seed                          → all initial data (projects, glossary, tm, etc.)
  POST /api/auth/login                    → password check
  GET  /api/projects                      → list projects
  POST /api/projects                      → create project (from DOCX or empty)
  GET  /api/projects/{pid}                → project detail
  POST /api/segments/{pid}/{sid}/translate → translate via Google or GPT
  POST /api/segments/{pid}/{sid}/qa       → run QA
  POST /api/segments/{pid}/{sid}/confirm  → confirm + add to TM
  POST /api/segments/{pid}/{sid}/revert   → revert confirmed/failed
  POST /api/segments/{pid}/{sid}/update   → update target/comment
  POST /api/projects/{pid}/batch          → batch translate (engine=google|gpt)
  POST /api/projects/{pid}/preflight      → run preflight analysis
  POST /api/projects/{pid}/export         → trigger export (docx|pdf|xlsx)
  POST /api/glossary                      → add/update term
  DELETE /api/glossary/{src}              → delete term
  DELETE /api/tm/{src}                    → delete TM entry

Run:
  cd backend
  uvicorn main:app --reload --port 8000
  → open http://localhost:8000
"""
import os
import sys
import json
import hashlib
import asyncio
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add med_translation to path so we can import existing modules
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "med_translation"))

# Try to import existing modules (graceful fallback if missing deps)
_BACKEND_MODULES = {}

def _safe_import(name: str):
    try:
        mod = __import__(name)
        _BACKEND_MODULES[name] = mod
        return mod
    except Exception as e:
        print(f"[backend] WARN: could not import {name}: {e}", file=sys.stderr)
        return None

db = _safe_import("db")
pipeline = _safe_import("pipeline")
google_translate = _safe_import("google_translate")
tm_mod = _safe_import("tm")
medical_qa_mod = _safe_import("medical_qa")

# Google Cloud Translation API v2 (с fallback на deep-translator)
import requests as _requests

def _deep_translate(text: str, src: str, tgt: str) -> str:
    src = src.lower()[:2]
    tgt = tgt.lower()[:2]
    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "")
    if api_key:
        try:
            resp = _requests.post(
                "https://translation.googleapis.com/language/translate/v2",
                params={"key": api_key},
                json={"q": text, "source": src, "target": tgt, "format": "text"},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()["data"]["translations"][0]["translatedText"]
        except Exception as _ge:
            print(f"[backend] Google API key failed ({_ge}), falling back to free tier", file=sys.stderr)
    # Fallback: deep-translator (без API ключа)
    from deep_translator import GoogleTranslator as _DTG
    return _DTG(source=src, target=tgt).translate(text) or ""

_DEEP_TRANSLATE_OK = True

import re as _re

def _term_match(term: str, text: str) -> str | None:
    """Ищет термин (в любой грамматической форме) в тексте.
    Возвращает фактически найденную подстроку или None.

    Алгоритм:
    1. Точное совпадение (быстро).
    2. Стеминг: первые 75% символов каждого слова термина (мин. 4) +
       любое кириллическое окончание.  Без внешних зависимостей.
       "лимфангит"     → стем "лимфанги"  → найдёт "лимфангита", "лимфангите"
       "первичный очаг" → стемы "первичн", "оча"
                        → найдёт "первичного очага", "первичному очагу"
    """
    lo = text.lower()
    tl = term.lower()
    # 1. Точное совпадение
    idx = lo.find(tl)
    if idx != -1:
        return text[idx:idx + len(term)]
    # 2. Стеминг по словам
    parts = tl.split()
    if not parts:
        return None
    stems = [_re.escape(w[:max(4, int(len(w) * 0.75))]) + r'[а-яёА-ЯЁ]*' for w in parts]
    full_pat = r'\s+'.join(stems)
    m = _re.search(r'(?<![а-яёА-ЯЁa-zA-Z])' + full_pat, text, _re.IGNORECASE)
    return m.group(0) if m else None


def _get_context(text: str):
    """Возвращает (gloss_hits, tm_hit) для исходного текста.

    gloss_hits — список dict {src, tgt, ..., _form} где _form — фактическая
                 форма термина найденная в тексте (нужна для замены).
    tm_hit     — точное совпадение в TM или None.
    """
    hits = []
    for g in STATE.get("glossary", []):
        src = g.get("src", "")
        if not src:
            continue
        form = _term_match(src, text)
        if form:
            hits.append({**g, "_form": form})
    # Длинные термины первыми: меньше риск перекрытия плейсхолдеров
    hits.sort(key=lambda x: len(x["src"]), reverse=True)
    hits = hits[:15]
    tm_hit = next(
        (t for t in STATE.get("tm", []) if t.get("src", "").strip().lower() == text.strip().lower()),
        None,
    )
    return hits, tm_hit


def _google_with_gloss(text: str, src: str, tgt: str, gloss_hits: list) -> str:
    """Google Translate с подстановкой глоссарных терминов через плейсхолдеры.

    Заменяем ФАКТИЧЕСКУЮ форму термина (h['_form'], напр. "лимфангита") →
    плейсхолдер → Google переводит остальное → восстанавливаем целевой термин.
    """
    if not gloss_hits:
        return _deep_translate(text, src, tgt)
    modified = text
    placeholders: dict[str, str] = {}
    for i, h in enumerate(gloss_hits):
        form = h.get("_form", h["src"])   # реальная форма в тексте
        ph = f"MCAT{i:03d}X"
        pattern = _re.compile(_re.escape(form), _re.IGNORECASE)
        if pattern.search(modified):
            modified = pattern.sub(ph, modified)
            placeholders[ph] = h["tgt"]
    result = _deep_translate(modified, src, tgt)
    for ph, target in placeholders.items():
        result = _re.sub(_re.escape(ph), target, result, flags=_re.IGNORECASE)
    if placeholders:
        print(f"[backend] Google+glossary: {len(placeholders)} forms replaced "
              f"{[h.get('_form', h['src']) for h in gloss_hits[:5]]}", file=sys.stderr)
    return result


# Direct OpenAI GPT translation
def _openai_translate(text: str, src: str, tgt: str,
                      gloss_hits: list = None, tm_context: dict = None) -> str:
    """GPT-перевод с инъекцией глоссария (базовые формы — GPT знает склонения)."""
    import openai
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    system = (
        f"You are a senior medical translator specializing in Russian-to-English biomedical texts. "
        f"Translate the following text from {src} to {tgt}.\n\n"
        "STRICT RULES:\n"
        "1. Return ONLY the translated text — no explanations, no comments, no quotes.\n"
        "2. Use standard English medical terminology. NEVER transliterate Russian or Latin word forms.\n"
        "   BAD: 'oxide nitrogena', 'leukocidin', 'cytocinesis' — these are NOT English words.\n"
        "   GOOD: 'nitric oxide', 'leukocytes', 'cytokines'.\n"
        "3. NEVER mix languages. Output must be 100% English.\n"
        "4. NEVER use parenthetical alternatives: NOT 'biologic(al)', NOT 'cell(s)'. Choose ONE correct form.\n"
        "5. NEVER list multiple synonyms separated by semicolons for the same concept.\n"
        "6. Preserve all numbers, abbreviations, and punctuation exactly as in the source.\n"
        "7. Medical abbreviations that are identical in English (e.g. IFN, IL, TNF) may be kept.\n"
    )
    if gloss_hits:
        terms = "\n".join(f"  {h['src']} → {h['tgt']}" for h in gloss_hits)
        system += f"\nApproved glossary — use these exact translations:\n{terms}\n"
    if tm_context:
        system += (
            f"\nTranslation Memory (similar segment, for reference):\n"
            f"  Source: {tm_context.get('src', '')}\n"
            f"  Translation: {tm_context.get('tgt', '')}\n"
        )
    if gloss_hits or tm_context:
        print(f"[backend] GPT+context: {len(gloss_hits or [])} gloss, TM={'yes' if tm_context else 'no'}",
              file=sys.stderr)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        max_tokens=1024,
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()

# ─────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Medical CAT Translator API", version="5.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = ROOT / "backend" / "data"
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"

PASSWORD_HASH = hashlib.sha256(
    os.environ.get("APP_PASSWORD", "medtranslator2026").encode()
).hexdigest()

def medical_qa_enabled() -> bool:
    if medical_qa_mod and hasattr(medical_qa_mod, "enabled_from_env"):
        return medical_qa_mod.enabled_from_env(os.environ.get("MEDICAL_TRANSLATION_QA_ENABLED", "1"))
    return os.environ.get("MEDICAL_TRANSLATION_QA_ENABLED", "1").lower() not in {"0", "false", "no", "off"}

# ─────────────────────────────────────────────────────────────────────
# In-memory store, persisted to JSON
# Starts from the design's SEED if no state.json exists, otherwise loads it
# ─────────────────────────────────────────────────────────────────────
SEED_PROJECTS = [
    {
        "id": 7,
        "title": "Эпикриз — кардиология 2026",
        "titleEn": "Discharge Summary — Cardiology 2026",
        "src": "RU", "tgt": "EN",
        "status": "in_progress",
        "created": "2026-05-28",
        "deadline": "2026-06-13",
        "segments": [
            {"id": 1, "source": "Выписной эпикриз пациента, находившегося на стационарном лечении в кардиологическом отделении.",
             "target": "Discharge summary of a patient who received inpatient treatment in the cardiology department.",
             "status": "confirmed", "route": "EXACT_TM", "risk": "low", "comments": [], "qa": [],
             "tm": {"score": 100, "source": "Выписной эпикриз пациента, находившегося на стационарном лечении в кардиологическом отделении.",
                    "target": "Discharge summary of a patient who received inpatient treatment in the cardiology department."}},
            {"id": 2, "source": "Жалобы при поступлении: давящие боли за грудиной, одышка при умеренной физической нагрузке, перебои в работе сердца.",
             "target": "Complaints on admission: pressing retrosternal pain, dyspnea on moderate exertion, and palpitations.",
             "status": "confirmed", "route": "GPT_REQUIRED", "risk": "medium", "comments": [], "qa": [], "tm": None},
            {"id": 3, "source": "Анамнез заболевания: считает себя больным в течение трёх лет, когда впервые появились ангинозные приступы.",
             "target": "History of present illness: the patient has considered himself ill for three years, when anginal attacks first appeared.",
             "status": "qa", "route": "GPT_REQUIRED", "risk": "medium", "comments": [],
             "qa": [{"sev": "medium", "type": "terminology", "msg": "Термин «ангинозные» — проверьте соответствие глоссарию (anginal vs. angina-type)."}], "tm": None},
            {"id": 4, "source": "Объективно: общее состояние удовлетворительное. Кожные покровы обычной окраски.",
             "target": "Objectively: general condition is satisfactory. Skin is of normal colour.",
             "status": "confirmed", "route": "DUPLICATE", "risk": "low", "comments": [], "qa": [], "tm": None},
            {"id": 5, "source": "Тоны сердца приглушены, ритм правильный. ЧСС 78 ударов в минуту. АД 140/90 мм рт. ст.",
             "target": "Heart sounds are muffled, rhythm is regular. Heart rate 78 bpm. Blood pressure 140/90 mmHg.",
             "status": "translated", "route": "GPT_REQUIRED", "risk": "high", "comments": [], "qa": [], "tm": None},
            {"id": 6, "source": "На ЭКГ: синусовый ритм, признаки гипертрофии левого желудочка, депрессия сегмента ST в отведениях V4–V6.",
             "target": "ECG: sinus rhythm, signs of left ventricular hypertrophy, ST-segment depression in leads V4–V6.",
             "status": "translated", "route": "GPT_REQUIRED", "risk": "high", "comments": [], "qa": [], "tm": None},
            {"id": 7, "source": "Эхокардиография выявила снижение фракции выброса левого желудочка до 48%.",
             "target": "Echocardiography revealed a reduction of the left ventricular ejection fraction to 48%.",
             "status": "qa", "route": "GPT_REQUIRED", "risk": "high", "comments": [],
             "qa": [{"sev": "high", "type": "numeric", "msg": "Проверьте число: 48% присутствует и в источнике, и в переводе. ОК."}], "tm": None},
            {"id": 8, "source": "Коронароангиография: стеноз передней межжелудочковой ветви левой коронарной артерии до 75%.",
             "target": "Coronary angiography: stenosis of the anterior interventricular branch of the left coronary artery up to 75%.",
             "status": "translated", "route": "GPT_REQUIRED", "risk": "critical", "comments": [], "qa": [], "tm": None},
            {"id": 9, "source": "Клинический диагноз: ИБС. Стабильная стенокардия напряжения, функциональный класс III.",
             "target": "Clinical diagnosis: coronary artery disease. Stable exertional angina, functional class III.",
             "status": "review", "route": "HUMAN_REVIEW", "risk": "critical", "comments": [],
             "qa": [{"sev": "high", "type": "terminology", "msg": "«ИБС» раскрыто как coronary artery disease — подтвердите предпочтительный вариант (CAD / IHD)."}], "tm": None},
            {"id": 10, "source": "Сопутствующие заболевания: гипертоническая болезнь II стадии, сахарный диабет 2 типа, компенсированный.",
             "target": "Comorbidities: stage II essential hypertension, compensated type 2 diabetes mellitus.",
             "status": "translated", "route": "GPT_REQUIRED", "risk": "medium", "comments": [], "qa": [], "tm": None},
            {"id": 11, "source": "Назначено лечение: бисопролол 5 мг утром, аторвастатин 20 мг вечером, ацетилсалициловая кислота 75 мг.",
             "target": "Treatment prescribed: bisoprolol 5 mg in the morning, atorvastatin 20 mg in the evening, acetylsalicylic acid 75 mg.",
             "status": "failed", "route": "GPT_REQUIRED", "risk": "high", "comments": [],
             "qa": [{"sev": "critical", "type": "numeric", "msg": "Несоответствие дозировки: проверьте «75 мг» — в черновике перевода указано 750 mg."}], "tm": None},
            {"id": 12, "source": "Рекомендовано: контроль артериального давления, соблюдение гиполипидемической диеты, дозированные физические нагрузки.",
             "target": "", "status": "new", "route": "GOOGLE_SAFE", "risk": "low", "comments": [], "qa": [], "tm": None},
            {"id": 13, "source": "Повторная консультация кардиолога через один месяц с результатами липидограммы.",
             "target": "", "status": "new", "route": "GOOGLE_SAFE", "risk": "low", "comments": [], "qa": [], "tm": None},
            {"id": 14, "source": "Прогноз для жизни благоприятный при условии соблюдения рекомендаций и регулярного приёма препаратов.",
             "target": "", "status": "new", "route": "GPT_REQUIRED", "risk": "medium", "comments": [], "qa": [], "tm": None},
            {"id": 15, "source": "Листок нетрудоспособности выдан с 14.05.2026 по 28.05.2026.",
             "target": "", "status": "new", "route": "GOOGLE_SAFE", "risk": "low", "comments": [], "qa": [], "tm": None},
        ],
    },
    {
        "id": 4,
        "title": "Инструкция по применению — Метформин",
        "titleEn": "Patient Information Leaflet — Metformin",
        "src": "RU", "tgt": "EN",
        "status": "review", "created": "2026-05-12", "deadline": "2026-06-09",
        "segments": [
            {"id": 1, "source": "Перед началом приёма препарата внимательно прочитайте инструкцию.",
             "target": "Read this leaflet carefully before you start taking the medicine.",
             "status": "confirmed", "route": "EXACT_TM", "risk": "low", "comments": [], "qa": [], "tm": None},
            {"id": 2, "source": "Показания к применению: сахарный диабет 2 типа у взрослых и детей старше 10 лет.",
             "target": "Indications: type 2 diabetes mellitus in adults and children over 10 years of age.",
             "status": "confirmed", "route": "GPT_REQUIRED", "risk": "medium", "comments": [], "qa": [], "tm": None},
            {"id": 3, "source": "Противопоказания: повышенная чувствительность к метформину, диабетический кетоацидоз.",
             "target": "Contraindications: hypersensitivity to metformin, diabetic ketoacidosis.",
             "status": "qa", "route": "GPT_REQUIRED", "risk": "high", "comments": [], "qa": [], "tm": None},
        ],
    },
]

def _load_glossary_from_tsv() -> list:
    """Load real medical glossary from TSV file; fall back to 10 hardcoded terms."""
    import csv
    _CAT_MAP = {
        "diagnosis": "Disease", "anatomy": "Anatomy", "symptom": "Symptom",
        "medication": "Dosage", "procedure": "Procedure", "other_medical": "Disease",
        "test": "Lab", "": "Disease",
    }
    tsv = ROOT / "med_translation" / "assets" / "glossary" / "approved_glossary_FINAL.tsv"
    if not tsv.exists():
        tsv = ROOT / "med_translation" / "data" / "approved_glossary_FINAL.tsv"
    if not tsv.exists():
        return []
    terms, seen = [], set()
    try:
        with open(tsv, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                ru = (row.get("Russian") or "").strip().strip('"')
                en = (row.get("English") or "").strip().strip('"')
                if not ru or not en or ru in seen:
                    continue
                if len(ru) < 3 or len(en) < 3:
                    continue
                # skip strings starting with special chars or digits
                if not ru[0].isalpha() or not en[0].isalpha():
                    continue
                seen.add(ru)
                cat_raw = (row.get("Category") or "").strip()
                terms.append({
                    "src": ru, "tgt": en,
                    "cat": _CAT_MAP.get(cat_raw, "Disease"),
                    "freq": 1, "conf": "high", "note": "",
                })
    except Exception as e:
        print(f"[backend] WARN: could not load glossary TSV: {e}", file=sys.stderr)
    return terms

SEED_GLOSSARY = _load_glossary_from_tsv() or [
    {"src": "стенокардия", "tgt": "angina", "cat": "Disease", "freq": 142, "conf": "high", "note": ""},
    {"src": "инфаркт миокарда", "tgt": "myocardial infarction", "cat": "Disease", "freq": 98, "conf": "high", "note": ""},
    {"src": "ишемическая болезнь сердца", "tgt": "coronary artery disease", "cat": "Disease", "freq": 76, "conf": "high", "note": ""},
    {"src": "ЭКГ", "tgt": "ECG", "cat": "Procedure", "freq": 210, "conf": "high", "note": ""},
    {"src": "артериальное давление", "tgt": "blood pressure", "cat": "Anatomy", "freq": 322, "conf": "high", "note": ""},
    {"src": "фракция выброса", "tgt": "ejection fraction", "cat": "Anatomy", "freq": 54, "conf": "high", "note": ""},
    {"src": "бисопролол", "tgt": "bisoprolol", "cat": "Dosage", "freq": 41, "conf": "high", "note": ""},
    {"src": "аторвастатин", "tgt": "atorvastatin", "cat": "Dosage", "freq": 33, "conf": "high", "note": ""},
    {"src": "сахарный диабет 2 типа", "tgt": "type 2 diabetes mellitus", "cat": "Disease", "freq": 58, "conf": "high", "note": ""},
    {"src": "одышка", "tgt": "dyspnea", "cat": "Symptom", "freq": 64, "conf": "medium", "note": ""},
]

SEED_TM = [
    {"src": "Выписной эпикриз пациента, находившегося на стационарном лечении в кардиологическом отделении.",
     "tgt": "Discharge summary of a patient who received inpatient treatment in the cardiology department.",
     "lang": "RU→EN", "score": 100, "quality": "verified", "used": 12, "created": "2026-04-12"},
    {"src": "Перед началом приёма препарата внимательно прочитайте инструкцию.",
     "tgt": "Read this leaflet carefully before you start taking the medicine.",
     "lang": "RU→EN", "score": 100, "quality": "verified", "used": 22, "created": "2026-03-01"},
    {"src": "Объективно: общее состояние удовлетворительное. Кожные покровы обычной окраски.",
     "tgt": "Objectively: general condition is satisfactory. Skin is of normal colour.",
     "lang": "RU→EN", "score": 100, "quality": "verified", "used": 8, "created": "2026-04-18"},
    {"src": "Артериальное давление 140/90 мм рт. ст., пульс ритмичный.",
     "tgt": "Blood pressure 140/90 mmHg, pulse is regular.",
     "lang": "RU→EN", "score": 95, "quality": "draft", "used": 3, "created": "2026-05-22"},
]

SEED_EXPORT_HISTORY = [
    {"file": "Эпикриз — кардиология 2026.docx", "when": "2026-06-10 14:21", "size": "84 КБ"},
    {"file": "Инструкция — Метформин.docx",      "when": "2026-06-04 11:05", "size": "62 КБ"},
]

SEED_TEAM = [
    {"name": "Анна Иванова",   "initials": "АИ", "color": "#2c7be5"},
    {"name": "Дмитрий Петров", "initials": "ДП", "color": "#22b07d"},
    {"name": "Олег Соколов",   "initials": "ОС", "color": "#f1a040"},
    {"name": "Мария Кравцова", "initials": "МК", "color": "#cc4a4a"},
]


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # Migrate: if glossary is tiny seed, upgrade to full loaded glossary
            if len(state.get("glossary", [])) < 100 and len(SEED_GLOSSARY) >= 100:
                state["glossary"] = list(SEED_GLOSSARY)
            # Migrate: fix TM quality field (verified bool → quality string)
            for t in state.get("tm", []):
                if "quality" not in t:
                    t["quality"] = "verified" if t.get("verified") else "draft"
            return state
        except Exception:
            pass
    return {
        "projects": json.loads(json.dumps(SEED_PROJECTS)),
        "glossary": list(SEED_GLOSSARY),
        "tm": list(SEED_TM),
        "exportHistory": list(SEED_EXPORT_HISTORY),
        "team": list(SEED_TEAM),
    }


def save_state(state: dict):
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[backend] WARN: could not save state: {e}", file=sys.stderr)


STATE = load_state()


def get_project(pid: int) -> dict:
    for p in STATE["projects"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, f"Project {pid} not found")


def get_segment(pid: int, sid: int) -> dict:
    project = get_project(pid)
    for s in project["segments"]:
        if s["id"] == sid:
            return s
    raise HTTPException(404, f"Segment {sid} not found in project {pid}")


# ─────────────────────────────────────────────────────────────────────
# API endpoints
# ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str

@app.post("/api/auth/login")
def login(req: LoginRequest):
    given = hashlib.sha256(req.password.encode()).hexdigest()
    if given == PASSWORD_HASH:
        return {"ok": True}
    raise HTTPException(401, "Invalid password")


@app.get("/api/seed")
def get_seed():
    """Initial data dump — glossary capped at 150 terms for performance; full list via /api/glossary."""
    return {**STATE, "glossary": STATE["glossary"][:150]}


@app.get("/api/glossary")
def list_glossary(q: str = "", cat: str = "", limit: int = 200, offset: int = 0):
    """Full glossary with optional search and pagination."""
    items = STATE["glossary"]
    if cat and cat != "all":
        items = [t for t in items if t.get("cat") == cat]
    if q:
        ql = q.lower()
        items = [t for t in items if ql in t.get("src", "").lower() or ql in t.get("tgt", "").lower()]
    total = len(items)
    return {"total": total, "items": items[offset:offset + limit]}


@app.get("/api/projects")
def list_projects():
    return [{k: v for k, v in p.items() if k != "segments"} | {"segmentCount": len(p["segments"])} for p in STATE["projects"]]


@app.get("/api/projects/{pid}")
def get_project_detail(pid: int):
    return get_project(pid)


class CreateProjectRequest(BaseModel):
    title: str
    src: str = "RU"
    tgt: str = "EN"
    fileName: Optional[str] = None

@app.post("/api/projects")
def create_project(req: CreateProjectRequest):
    new_id = max((p["id"] for p in STATE["projects"]), default=0) + 1
    sample = STATE["projects"][0]["segments"][:8] if STATE["projects"] else []
    new_project = {
        "id": new_id,
        "title": req.title or "Новый проект",
        "titleEn": req.title or "New Project",
        "src": req.src, "tgt": req.tgt,
        "status": "in_progress",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "deadline": "",
        "segments": [
            {**s, "id": i + 1, "target": "", "status": "new", "comments": [], "qa": []}
            for i, s in enumerate(sample)
        ],
    }
    STATE["projects"].insert(0, new_project)
    save_state(STATE)
    return new_project


@app.post("/api/projects/upload")
async def upload_project(
    file: UploadFile = File(...),
    title: str = Form(""),
    src: str = Form("RU"),
    tgt: str = Form("EN"),
):
    import io, re, html as _html
    try:
        from docx import Document
    except ImportError:
        raise HTTPException(500, "python-docx not installed")

    content = await file.read()
    try:
        from docx.oxml.ns import qn as _qn
    except ImportError:
        raise HTTPException(500, "python-docx not installed")

    doc = Document(io.BytesIO(content))

    def clean(text):
        text = _html.unescape(text)
        text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def para_text(p_elem):
        return clean("".join(t.text for t in p_elem.iter(_qn("w:t")) if t.text))

    # Walk ALL paragraphs in document XML order (catches nested tables, frames, etc.)
    all_p = doc.element.body.findall(".//" + _qn("w:p"))
    raw = [para_text(p) for p in all_p]

    # Filter: skip pure digits/spaces/punctuation or very short
    segments_text = [
        t for t in raw
        if len(t) >= 2
        and not re.fullmatch(r'[\d\s\-–—.,:;()\[\]/]+', t)
    ]

    # Deduplicate adjacent identical lines
    deduped = []
    prev = None
    for t in segments_text:
        if t != prev:
            deduped.append(t)
            prev = t

    new_id = max((p["id"] for p in STATE["projects"]), default=0) + 1
    proj_title = title or file.filename.rsplit(".", 1)[0]
    new_project = {
        "id": new_id,
        "title": proj_title,
        "titleEn": proj_title,
        "src": src, "tgt": tgt,
        "status": "in_progress",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "deadline": "",
        "fileName": file.filename,
        "segments": [
            {
                "id": i + 1,
                "source": text,
                "target": "",
                "status": "new",
                "comments": [],
                "qa": [],
                "tmScore": 0,
                "wordCount": len(text.split()),
                "risk": "high" if len(text.split()) > 30 else "medium" if len(text.split()) > 8 else "low",
                "route": "GPT_REQUIRED",
                "tm": None,
            }
            for i, text in enumerate(deduped)
        ],
    }
    STATE["projects"].insert(0, new_project)
    save_state(STATE)
    return new_project


# ─── Segment actions ────────────────────────────────────────────────
class TranslateRequest(BaseModel):
    engine: str  # "google" | "gpt"
    force: bool = False  # True = пропустить TM-шорткат (ручной перевод)

@app.post("/api/segments/{pid}/{sid}/translate")
async def translate_segment(pid: int, sid: int, req: TranslateRequest):
    seg = get_segment(pid, sid)
    project = get_project(pid)
    src_text = seg["source"]

    # Глоссарий + TM контекст
    gloss_hits, tm_hit = _get_context(src_text)

    # TM точное совпадение → 0 токенов (только для авто/пакетного, не для ручного force-перевода)
    if not req.force and tm_hit and tm_hit.get("tgt"):
        seg["target"] = tm_hit["tgt"]
        seg["status"] = "confirmed"
        seg["route"] = "EXACT_TM"
        save_state(STATE)
        return {"ok": True, "segment": seg, "usedRealApi": False, "source": "TM"}

    translation = None
    used_real_api = False
    try:
        if req.engine == "google" and _DEEP_TRANSLATE_OK:
            translation = _google_with_gloss(src_text, project["src"], project["tgt"], gloss_hits)
            used_real_api = True
        elif req.engine == "gpt" and os.environ.get("OPENAI_API_KEY"):
            translation = _openai_translate(src_text, project["src"], project["tgt"],
                                            gloss_hits=gloss_hits, tm_context=tm_hit)
            used_real_api = bool(translation)
        # GPT fallback: Google когда нет ключа OpenAI
        if not translation and req.engine == "gpt" and _DEEP_TRANSLATE_OK:
            translation = _google_with_gloss(src_text, project["src"], project["tgt"], gloss_hits)
            used_real_api = True
    except Exception as e:
        print(f"[backend] translate fallback ({req.engine}): {e}", file=sys.stderr)
        if _DEEP_TRANSLATE_OK:
            try:
                translation = _google_with_gloss(src_text, project["src"], project["tgt"], gloss_hits)
                used_real_api = True
            except Exception:
                pass

    if not translation:
        translation = seg.get("target") or f"[{req.engine.upper()} demo translation of segment #{sid}]"

    seg["target"] = translation
    seg["status"] = "translated"
    seg["route"] = "GPT_REQUIRED" if req.engine == "gpt" else "GOOGLE_SAFE"
    save_state(STATE)
    return {"ok": True, "segment": seg, "usedRealApi": used_real_api}


@app.post("/api/segments/{pid}/{sid}/qa")
def qa_segment(pid: int, sid: int):
    seg = get_segment(pid, sid)
    # Simple local QA checks
    qa_issues = []
    src, tgt = seg["source"], seg.get("target", "")
    # Check numbers preserved
    import re
    src_nums = re.findall(r"\d+(?:[.,]\d+)?", src)
    tgt_nums = re.findall(r"\d+(?:[.,]\d+)?", tgt)
    if sorted(src_nums) != sorted(tgt_nums) and src_nums:
        qa_issues.append({"sev": "high", "type": "numeric",
                          "msg": f"Числа не совпадают: source={src_nums}, target={tgt_nums}"})
    # Check length not crazy
    if tgt and len(tgt) > 3 * len(src):
        qa_issues.append({"sev": "medium", "type": "length",
                          "msg": "Перевод более чем в 3 раза длиннее оригинала."})

    seg["qa"] = qa_issues
    seg["status"] = "qa"
    save_state(STATE)
    return {"ok": True, "segment": seg, "issues": qa_issues}


@app.post("/api/segments/{pid}/{sid}/confirm")
def confirm_segment(pid: int, sid: int):
    seg = get_segment(pid, sid)
    seg["status"] = "confirmed"
    # Add to TM if not already there
    if seg.get("target") and not any(t["src"] == seg["source"] for t in STATE["tm"]):
        STATE["tm"].insert(0, {
            "src": seg["source"], "tgt": seg["target"],
            "lang": "RU→EN", "score": 100, "quality": "verified",
            "used": 1, "created": datetime.now().strftime("%Y-%m-%d"),
        })
    save_state(STATE)
    return {"ok": True, "segment": seg}


@app.post("/api/segments/{pid}/{sid}/backcheck")
async def backcheck_segment(pid: int, sid: int):
    """Обратный перевод: target (EN) → source lang (RU) через GPT.
    Fallback на Google если нет ключа OpenAI."""
    seg = get_segment(pid, sid)
    project = get_project(pid)
    target_text = seg.get("target", "").strip()
    if not target_text:
        return {"ok": False, "error": "Сегмент ещё не переведён"}
    try:
        if os.environ.get("OPENAI_API_KEY"):
            back = _openai_translate(target_text, project["tgt"], project["src"])
        else:
            back = _deep_translate(target_text, project["tgt"], project["src"])
        return {"ok": True, "back": back}
    except Exception as e:
        try:
            back = _deep_translate(target_text, project["tgt"], project["src"])
            return {"ok": True, "back": back}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


class MedicalQARequest(BaseModel):
    run_backcheck: bool = True


def _segment_medical_qa(pid: int, sid: int, run_backcheck: bool = True) -> dict:
    if not medical_qa_mod:
        raise HTTPException(500, "medical_qa module unavailable")

    seg = get_segment(pid, sid)
    project = get_project(pid)
    source_text = seg.get("source", "")
    target_text = seg.get("target", "").strip()
    if not target_text:
        return {"ok": False, "error": "Segment is not translated yet", "segment": seg}

    gloss_hits, tm_hit = _get_context(source_text)
    back = seg.get("backtranslated_ru", "")

    if run_backcheck and medical_qa_enabled():
        try:
            if os.environ.get("OPENAI_API_KEY"):
                back = _openai_translate(target_text, project["tgt"], project["src"])
            elif os.environ.get("GOOGLE_TRANSLATE_API_KEY"):
                back = _deep_translate(target_text, project["tgt"], project["src"])
        except Exception as e:
            print(f"[backend] medical QA backcheck skipped: {e}", file=sys.stderr)

    qa_result = medical_qa_mod.run_medical_qa(
        source_text,
        target_text,
        backtranslated_ru=back,
        glossary_matches=gloss_hits,
        tm_match=tm_hit,
        engine_qa="medical_qa_mvp",
    )

    seg["backtranslated_ru"] = qa_result["literal_backcheck"]["backtranslated_ru"]
    seg["qa_result"] = qa_result
    seg["qa_issues"] = qa_result["qa_issues"]
    seg["qa"] = qa_result["ui_issues"]
    seg["term_candidates"] = qa_result["term_candidates"]
    seg["risk_score"] = qa_result["risk_score"]
    seg["risk_color"] = qa_result["risk_color"]
    seg["engine_qa"] = qa_result["engine_qa"]
    seg["medical_qa_enabled"] = medical_qa_enabled()

    if qa_result["risk_color"] == "red":
        seg["status"] = "review"
        seg["risk"] = "critical"
    elif qa_result["risk_color"] == "yellow":
        seg["status"] = "qa"
        seg["risk"] = "medium"
    else:
        seg["status"] = "qa"
        seg["risk"] = "low"

    return {"ok": True, "segment": seg, "qa_result": qa_result, "issues": qa_result["qa_issues"]}


@app.post("/api/segments/{pid}/{sid}/medical-qa")
def medical_qa_segment(pid: int, sid: int, req: MedicalQARequest = MedicalQARequest()):
    result = _segment_medical_qa(pid, sid, run_backcheck=req.run_backcheck)
    save_state(STATE)
    return result


class MedicalQABatchRequest(BaseModel):
    limit: int = 50
    segment_ids: Optional[list] = None
    run_backcheck: bool = True


@app.post("/api/projects/{pid}/medical-qa/batch")
def batch_medical_qa(pid: int, req: MedicalQABatchRequest = MedicalQABatchRequest()):
    project = get_project(pid)
    id_filter = set(req.segment_ids) if req.segment_ids else None
    candidates = [
        s for s in project["segments"]
        if s.get("target", "").strip()
        and s.get("status") in {"translated", "qa", "review", "confirmed"}
        and (id_filter is None or s["id"] in id_filter)
    ]
    targets = candidates[:req.limit]
    processed = []
    errors = []
    for seg in targets:
        try:
            result = _segment_medical_qa(pid, seg["id"], run_backcheck=req.run_backcheck)
            if result.get("ok"):
                processed.append(seg["id"])
            else:
                errors.append({"id": seg["id"], "error": result.get("error", "unknown")})
        except Exception as e:
            errors.append({"id": seg["id"], "error": str(e)})
            print(f"[backend] medical QA batch error seg#{seg['id']}: {e}", file=sys.stderr)

    save_state(STATE)
    return {
        "ok": True,
        "processed": processed,
        "count": len(processed),
        "remaining": max(0, len(candidates) - len(targets)),
        "errors": errors,
        "featureEnabled": medical_qa_enabled(),
    }


@app.post("/api/segments/{pid}/{sid}/revert")
def revert_segment(pid: int, sid: int):
    seg = get_segment(pid, sid)
    if seg["status"] == "confirmed":
        seg["status"] = "translated"
    elif seg["status"] == "failed":
        seg["status"] = "new"
        seg["target"] = ""
    save_state(STATE)
    return {"ok": True, "segment": seg}


class UpdateSegmentRequest(BaseModel):
    target: Optional[str] = None
    status: Optional[str] = None
    comment: Optional[str] = None
    commentAuthor: Optional[dict] = None

@app.post("/api/segments/{pid}/{sid}/update")
def update_segment(pid: int, sid: int, req: UpdateSegmentRequest):
    seg = get_segment(pid, sid)
    if req.target is not None:
        seg["target"] = req.target
        if seg["status"] == "new" and req.target.strip():
            seg["status"] = "translated"
    if req.status:
        seg["status"] = req.status
    if req.comment:
        seg.setdefault("comments", []).append({
            "author": req.commentAuthor or {"name": "Вы", "initials": "ВЫ", "color": "#2c7be5"},
            "when": "только что",
            "text": req.comment,
        })
    save_state(STATE)
    return {"ok": True, "segment": seg}


class BatchRequest(BaseModel):
    engine: str                          # "google" | "gpt"
    limit: int = 50                      # максимум за один вызов
    segment_ids: Optional[list] = None  # если передан — обрабатывать только эти сегменты
    force: bool = False                  # True = явный выбор пользователя, пропустить фильтры статуса и риска

@app.post("/api/projects/{pid}/batch")
async def batch_translate(pid: int, req: BatchRequest):
    project = get_project(pid)
    id_filter = set(req.segment_ids) if req.segment_ids else None
    if req.force and id_filter:
        # Явный выбор — переводим только указанные сегменты, кроме подтверждённых
        all_targets = [s for s in project["segments"] if s["id"] in id_filter and s["status"] != "confirmed"]
    else:
        all_targets = [s for s in project["segments"]
                       if s["status"] == "new" and
                       (s["risk"] == "low" if req.engine == "google" else s["risk"] != "low") and
                       (id_filter is None or s["id"] in id_filter)]
    remaining_after = max(0, len(all_targets) - req.limit)
    targets = all_targets[:req.limit]
    translated = []
    tm_hits_count = 0
    errors = []
    for seg in targets:
        translation = None
        gloss_hits, tm_hit = _get_context(seg["source"])

        # TM точное совпадение → пропускаем API вызов
        if tm_hit and tm_hit.get("tgt"):
            seg["target"] = tm_hit["tgt"]
            seg["status"] = "confirmed"
            seg["route"] = "EXACT_TM"
            translated.append(seg["id"])
            tm_hits_count += 1
            continue

        try:
            if req.engine == "google":
                translation = _google_with_gloss(seg["source"], project["src"], project["tgt"], gloss_hits)
            elif req.engine == "gpt" and os.environ.get("OPENAI_API_KEY"):
                translation = _openai_translate(seg["source"], project["src"], project["tgt"],
                                                gloss_hits=gloss_hits, tm_context=tm_hit)
            if not translation and req.engine == "gpt":
                translation = _google_with_gloss(seg["source"], project["src"], project["tgt"], gloss_hits)
        except Exception as e:
            errors.append(seg["id"])
            print(f"[backend] batch error seg#{seg['id']}: {e}", file=sys.stderr)
        if translation:
            seg["target"] = translation
            seg["status"] = "translated"
            seg["route"] = "GPT_REQUIRED" if req.engine == "gpt" else "GOOGLE_SAFE"
            translated.append(seg["id"])
    save_state(STATE)
    return {
        "ok": True,
        "translated": translated,
        "count": len(translated),
        "remaining": remaining_after,
        "errors": errors,
        "tm_hits": tm_hits_count,
    }


@app.post("/api/projects/{pid}/preflight")
def run_preflight(pid: int):
    project = get_project(pid)
    segs = project["segments"]
    total = len(segs)

    # Assign risk + route to every segment that lacks them
    for s in segs:
        if not s.get("risk"):
            words = len(s["source"].split())
            s["risk"] = "high" if words > 30 else "medium" if words > 8 else "low"
        if not s.get("route"):
            s["route"] = "GOOGLE_SAFE" if s["risk"] == "low" else "GPT_REQUIRED"
        if s.get("tm") is None:
            s["tm"] = None

    save_state(STATE)

    routes: dict = {}
    for s in segs:
        r = s.get("route", "GPT_REQUIRED")
        routes[r] = routes.get(r, 0) + 1

    risks: dict = {}
    for s in segs:
        r = s.get("risk", "medium")
        risks[r] = risks.get(r, 0) + 1

    return {
        "ok": True,
        "totalSegments": total,
        "routes": routes,
        "risks": risks,
        "analysisTime": round(total * 0.045 + 0.6, 1),
    }


class ExportRequest(BaseModel):
    format: str  # "docx" | "pdf" | "xlsx"

@app.post("/api/projects/{pid}/export")
def export_project(pid: int, req: ExportRequest):
    project = get_project(pid)
    file_name = f"{project['title']}.{req.format}"
    STATE["exportHistory"].insert(0, {
        "file": file_name,
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "size": "≈ 80 КБ",
    })
    save_state(STATE)
    return {"ok": True, "file": file_name}


# ─── Glossary ───────────────────────────────────────────────────────
class TermRequest(BaseModel):
    src: str
    tgt: str
    cat: str = ""
    freq: int = 0
    conf: str = "Medium"
    isNew: bool = False

@app.post("/api/glossary")
def save_term(req: TermRequest):
    existing = next((t for t in STATE["glossary"] if t["src"] == req.src), None)
    if existing and not req.isNew:
        existing.update({"tgt": req.tgt, "cat": req.cat, "freq": req.freq, "conf": req.conf})
    else:
        STATE["glossary"].insert(0, req.dict(exclude={"isNew"}))
    save_state(STATE)
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    STATE["projects"] = [p for p in STATE["projects"] if p["id"] != pid]
    save_state(STATE)
    return {"ok": True}


@app.delete("/api/glossary")
def delete_term(src: str):
    STATE["glossary"] = [t for t in STATE["glossary"] if t["src"] != src]
    save_state(STATE)
    return {"ok": True}


# ─── TM ─────────────────────────────────────────────────────────────
@app.delete("/api/tm")
def delete_tm(src: str):
    STATE["tm"] = [t for t in STATE["tm"] if t["src"] != src]
    save_state(STATE)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": "5.5.0",
        "backendModules": list(_BACKEND_MODULES.keys()),
        "medicalQaEnabled": medical_qa_enabled(),
        "stateFile": str(STATE_FILE),
        "projects": len(STATE["projects"]),
    }


# ─────────────────────────────────────────────────────────────────────
# Static file serving (the React design)
# Mounted last so /api/* takes precedence.
# ─────────────────────────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
    app.mount("/screens", StaticFiles(directory=str(FRONTEND_DIR / "screens")), name="screens")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    @app.get("/", response_class=HTMLResponse)
    def index_fallback():
        return "<h1>Frontend directory not found</h1><p>Expected at: " + str(FRONTEND_DIR) + "</p>"


if __name__ == "__main__":
    import uvicorn
    print(f"[backend] Starting Medical CAT Translator API on http://localhost:8000")
    print(f"[backend] Frontend dir: {FRONTEND_DIR}")
    print(f"[backend] Loaded modules: {list(_BACKEND_MODULES.keys())}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
