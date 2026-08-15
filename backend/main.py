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
import re
import sys
import json
import hashlib
import asyncio
import threading
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
sys.path.insert(0, str(ROOT / "backend"))
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

# Ключ, вернувший 401/403, помечается мёртвым до рестарта — не тратим
# лишний HTTP-запрос (и не льём ключ в логи) на каждый перевод.
_GOOGLE_KEY_DEAD = False

def _deep_translate(text: str, src: str, tgt: str) -> str:
    global _GOOGLE_KEY_DEAD
    src = src.lower()[:2]
    tgt = tgt.lower()[:2]
    api_key = os.environ.get("GOOGLE_TRANSLATE_API_KEY", "")
    if api_key and not _GOOGLE_KEY_DEAD:
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
            msg = str(_ge).replace(api_key, "***KEY***")  # не светим ключ в логах
            if "401" in msg or "403" in msg:
                _GOOGLE_KEY_DEAD = True
                print(f"[backend] Google API key невалиден ({msg}) — отключён до рестарта, "
                      f"используется бесплатный fallback", file=sys.stderr)
            else:
                print(f"[backend] Google API key failed ({msg}), falling back to free tier", file=sys.stderr)
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


# ─── Каталог моделей OpenAI ──────────────────────────────────────────
# Цены — USD за 1M токенов, сверено с developers.openai.com/api/docs/pricing 15.08.2026.
# ЕДИНСТВЕННОЕ место, где правятся модели и цены: добавили модель — добавили строку.
# "api": "modern" — семейство GPT-5.x: НЕ принимает max_tokens/temperature, нужен
# max_completion_tokens (проверено вызовами к API 15.08.2026). "classic" — GPT-4.x.
OPENAI_MODELS = [
    {"id": "gpt-5.6-sol",   "label": "GPT-5.6 Sol",   "in": 5.00, "out": 30.00, "api": "modern",  "note": "Флагман, максимальное качество"},
    {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "in": 2.00, "out": 12.00, "api": "modern",  "note": "Баланс качества и цены"},
    {"id": "gpt-5.6-luna",  "label": "GPT-5.6 Luna",  "in": 0.20, "out": 1.20,  "api": "modern",  "note": "Быстрая и недорогая"},
    {"id": "gpt-5.5",       "label": "GPT-5.5",       "in": 5.00, "out": 30.00, "api": "modern",  "note": "Предыдущий флагман"},
    {"id": "gpt-5.4",       "label": "GPT-5.4",       "in": 2.50, "out": 15.00, "api": "modern",  "note": ""},
    {"id": "gpt-5.4-mini",  "label": "GPT-5.4 mini",  "in": 0.75, "out": 4.50,  "api": "modern",  "note": ""},
    {"id": "gpt-4.1",       "label": "GPT-4.1",       "in": 2.00, "out": 8.00,  "api": "classic", "note": ""},
    {"id": "gpt-4o",        "label": "GPT-4o",        "in": 2.50, "out": 10.00, "api": "classic", "note": "По умолчанию"},
    {"id": "gpt-4o-mini",   "label": "GPT-4o mini",   "in": 0.15, "out": 0.60,  "api": "classic", "note": "Самая дешёвая"},
]
DEFAULT_OPENAI_MODEL = "gpt-4o"
_MODELS_BY_ID = {m["id"]: m for m in OPENAI_MODELS}

# seg["provider"] — чем сегмент переведён по факту: id модели OpenAI, либо эти константы.
# Поле проставляется в момент перевода; у сегментов, переведённых до его появления,
# его нет, и фронтенд показывает приблизительное значение по seg["route"].
PROVIDER_GOOGLE = "google"
PROVIDER_TM = "tm"

# Для обратного перевода нужна не лучшая модель, а самая буквальная и дешёвая:
# её задача — зеркалить текст, а не переводить его хорошо. Чем «умнее» модель,
# тем охотнее она чинит ошибки на лету и прячет их от проверки.
BACKCHECK_DEFAULT_MODEL = "gpt-5.6-luna"

# Семантическая близость оригинала и обратного перевода. Лексическая база не умеет
# в синонимы: «больному назначен» против «пациенту назначили» — это один смысл и
# разные основы. Эмбеддинги закрывают ровно этот разрыв.
EMBED_MODEL = "text-embedding-3-small"
# Судья вызывается только в средней зоне: наверху и внизу шкалы решение уже принято
# детерминированными проверками, и платить за подтверждение очевидного незачем.
JUDGE_ZONE = (50, 97)


def _openai_embed(texts: list) -> list:
    import openai
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=60, max_retries=2)
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return (dot / (na * nb)) if na and nb else 0.0


def _semantic_similarity(source_ru: str, back_ru: str):
    """Косинус между оригиналом и обратным переводом. None — если посчитать не вышло."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        vecs = _openai_embed([source_ru, back_ru])
        return _cosine(vecs[0], vecs[1])
    except Exception as e:
        print(f"[backend] embed failed: {e}", file=sys.stderr)
        return None


_JUDGE_SYSTEM = (
    "Ты — медицинский редактор. Тебе дают исходный текст на русском и его ОБРАТНЫЙ перевод "
    "(текст перевели на английский, затем обратно на русский). Твоя задача — понять, "
    "сохранился ли медицинский смысл.\n\n"
    "Считай расхождением: подмену понятия или термина на другое (например «лимфаденит» → "
    "«аденолимфит» — это разные вещи), изменение числа, дозировки, единицы, отрицания, "
    "стороны, анатомической локализации, степени уверенности диагноза.\n"
    "НЕ считай расхождением: синонимы, изменённый порядок слов, стилистические различия, "
    "разные падежи и формы, если медицинский смысл тот же.\n\n"
    "Верни ТОЛЬКО JSON без пояснений:\n"
    '{"same_meaning": true|false, "severity": "none"|"minor"|"major"|"critical", '
    '"divergences": ["короткое описание расхождения"], "comment": "одно предложение по-русски"}\n'
    "severity: none — смысл идентичен; minor — стилистика; major — заметное смысловое "
    "расхождение; critical — подмена понятия, числа, отрицания или стороны."
)


def _openai_judge(source_ru: str, back_ru: str, model: str = None) -> Optional[dict]:
    """Вердикт модели по паре «оригинал / обратный перевод»."""
    import json as _json
    import openai
    mdl = _resolve_model(model or DEFAULT_OPENAI_MODEL)
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=90, max_retries=1)
    extra = ({"max_completion_tokens": 2048} if mdl["api"] == "modern"
             else {"max_tokens": 500, "temperature": 0})
    try:
        resp = client.chat.completions.create(
            model=mdl["id"],
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": "ОРИГИНАЛ:\n" + source_ru + "\n\nОБРАТНЫЙ ПЕРЕВОД:\n" + back_ru},
            ],
            **extra,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Модель иногда оборачивает JSON в ```json ... ``` — вырезаем тело
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        verdict = _json.loads(m.group(0))
        verdict["model"] = mdl["id"]
        return verdict
    except Exception as e:
        print(f"[backend] judge failed: {e}", file=sys.stderr)
        return None


def _resolve_model(model_id: Optional[str]) -> dict:
    """Неизвестная/пустая модель → дефолт. Клиент не может подсунуть произвольную строку."""
    return _MODELS_BY_ID.get(model_id or "") or _MODELS_BY_ID[DEFAULT_OPENAI_MODEL]


# Direct OpenAI GPT translation
def _openai_translate(text: str, src: str, tgt: str,
                      gloss_hits: list = None, tm_context: dict = None,
                      model: str = None, literal: bool = False) -> str:
    """GPT-перевод с инъекцией глоссария (базовые формы — GPT знает склонения).

    literal=True — режим для обратного перевода. Обычный промпт тут вреден:
    сильная модель видит кривой английский, «чинит» его на лету и возвращает
    правильный русский, маскируя ровно ту ошибку, которую back-check ищет.
    Поэтому в этом режиме требуем дословности и запрещаем править термины,
    а глоссарий и TM не подсовываем вовсе — иначе модель подгонит ответ под них."""
    import openai
    mdl = _resolve_model(model)
    # timeout + retries: зависший вызов не должен блокировать поток бесконечно
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=90, max_retries=2)
    if literal:
        system = (
            f"Translate the following text from {src} to {tgt} as literally as possible. "
            "This is a back-translation used for quality control.\n\n"
            "STRICT RULES:\n"
            "1. Return ONLY the translation — no explanations, no comments, no quotes.\n"
            "2. Translate exactly what is written, word for word wherever the language allows.\n"
            "3. Do NOT correct, improve, normalize or standardise anything. If the text contains\n"
            "   an odd, wrong or non-existent term, translate it literally and preserve the oddity.\n"
            "   Your job is to mirror the text, NOT to make it sound correct.\n"
            "4. Preserve every number, unit and negation exactly.\n"
            "5. Keep the word order of the original as close as the target language permits.\n"
        )
        gloss_hits = None
        tm_context = None
    else:
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
        print(f"[backend] GPT+context: {len(gloss_hits or [])} gloss, TM={'yes' if tm_context else 'no'}"
              f", model={mdl['id']}", file=sys.stderr)
    # GPT-5.x отвергает max_tokens/temperature; лимит выставлен с запасом, потому что
    # у этого семейства в completion_tokens входят ещё и reasoning-токены.
    extra = ({"max_completion_tokens": 4096} if mdl["api"] == "modern"
             else {"max_tokens": 1024, "temperature": 0.1})
    resp = client.chat.completions.create(
        model=mdl["id"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        **extra,
    )
    return (resp.choices[0].message.content or "").strip()

# ─────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Medical CAT Translator API", version="5.6.0")

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


BACKUP_DIR = DATA_DIR / "backups"
_SAVE_LOCK = threading.Lock()          # сериализует записи state.json (эндпоинты идут в threadpool)
_BACKUP_KEEP = 48                      # почасовые бэкапы, ~2 суток


def _apply_migrations(state: dict) -> dict:
    # Migrate: if glossary is tiny seed, upgrade to full loaded glossary
    if len(state.get("glossary", [])) < 100 and len(SEED_GLOSSARY) >= 100:
        state["glossary"] = list(SEED_GLOSSARY)
    # Migrate: fix TM quality field (verified bool → quality string)
    for t in state.get("tm", []):
        if "quality" not in t:
            t["quality"] = "verified" if t.get("verified") else "draft"
    return state


def load_state() -> dict:
    """Загрузка состояния. Если state.json повреждён — НЕ теряем данные молча:
    битый файл сохраняется как state.corrupt-*, затем пробуем свежайший бэкап."""
    candidates = [STATE_FILE] + sorted(BACKUP_DIR.glob("state-*.json"), reverse=True)
    for path in candidates:
        if not path.exists():
            continue
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if path != STATE_FILE:
                print(f"[backend] CRITICAL: state.json повреждён — восстановлено из бэкапа {path.name}",
                      file=sys.stderr)
            return _apply_migrations(state)
        except Exception as e:
            print(f"[backend] ERROR: не удалось прочитать {path.name}: {e}", file=sys.stderr)
            if path == STATE_FILE:
                try:
                    corrupt = STATE_FILE.with_name(
                        f"state.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
                    STATE_FILE.rename(corrupt)
                    print(f"[backend] повреждённый файл сохранён как {corrupt.name} "
                          f"(для ручного восстановления)", file=sys.stderr)
                except Exception:
                    pass
    print("[backend] CRITICAL: рабочее состояние не найдено — старт с демо-данными (SEED)",
          file=sys.stderr)
    return {
        "projects": json.loads(json.dumps(SEED_PROJECTS)),
        "glossary": list(SEED_GLOSSARY),
        "tm": list(SEED_TM),
        "exportHistory": list(SEED_EXPORT_HISTORY),
        "team": list(SEED_TEAM),
    }


def _hourly_backup(payload: str):
    """Раз в час откладывает копию состояния в data/backups/ (хранится ~2 суток)."""
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        bak = BACKUP_DIR / f"state-{datetime.now().strftime('%Y%m%d-%H')}.json"
        if not bak.exists():
            bak.write_text(payload, encoding="utf-8")
            for old in sorted(BACKUP_DIR.glob("state-*.json"))[:-_BACKUP_KEEP]:
                old.unlink()
    except Exception as e:
        print(f"[backend] WARN: hourly backup failed: {e}", file=sys.stderr)


def save_state(state: dict):
    """Атомарная запись: tmp-файл + fsync + os.replace под глобальным локом.
    Раньше файл писался напрямую — параллельные запросы могли оставить битый JSON,
    а load_state() молча сбрасывал всё на демо-данные (потеря проектов)."""
    try:
        with _SAVE_LOCK:
            payload = json.dumps(state, ensure_ascii=False)
            tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, STATE_FILE)
            _hourly_backup(payload)
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


@app.get("/api/models")
def list_models():
    """Каталог GPT-моделей с ценами — для выпадающего списка и оценки стоимости пакета.
    Полосы back-check отдаются отсюда же, чтобы границы не дублировались на фронтенде."""
    return {
        "models": OPENAI_MODELS,
        "default": DEFAULT_OPENAI_MODEL,
        "backcheckDefault": BACKCHECK_DEFAULT_MODEL,
        "backcheckBands": getattr(medical_qa_mod, "BACKCHECK_BANDS", []) if medical_qa_mod else [],
        "available": bool(os.environ.get("OPENAI_API_KEY")),
        "pricesChecked": "2026-08-15",
    }


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
    model: Optional[str] = None  # id из OPENAI_MODELS; неизвестный → DEFAULT_OPENAI_MODEL

@app.post("/api/segments/{pid}/{sid}/translate")
def translate_segment(pid: int, sid: int, req: TranslateRequest):
    # обычный def, а не async: внутри блокирующие вызовы OpenAI/Google (см. batch_translate)
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
        seg["provider"] = PROVIDER_TM
        save_state(STATE)
        return {"ok": True, "segment": seg, "usedRealApi": False, "source": "TM"}

    translation = None
    used_real_api = False
    used_provider = None   # чем на самом деле переведено — с учётом всех fallback'ов
    try:
        if req.engine == "google" and _DEEP_TRANSLATE_OK:
            translation = _google_with_gloss(src_text, project["src"], project["tgt"], gloss_hits)
            used_real_api = True
            used_provider = PROVIDER_GOOGLE
        elif req.engine == "gpt" and os.environ.get("OPENAI_API_KEY"):
            translation = _openai_translate(src_text, project["src"], project["tgt"],
                                            gloss_hits=gloss_hits, tm_context=tm_hit,
                                            model=req.model)
            used_real_api = bool(translation)
            if translation:
                used_provider = _resolve_model(req.model)["id"]
        # GPT fallback: Google когда нет ключа OpenAI
        if not translation and req.engine == "gpt" and _DEEP_TRANSLATE_OK:
            translation = _google_with_gloss(src_text, project["src"], project["tgt"], gloss_hits)
            used_real_api = True
            used_provider = PROVIDER_GOOGLE
    except Exception as e:
        print(f"[backend] translate fallback ({req.engine}): {e}", file=sys.stderr)
        # Кросс-движковый fallback: google↑ → пробуем GPT, gpt↑ → пробуем Google
        try:
            if req.engine == "google" and os.environ.get("OPENAI_API_KEY"):
                translation = _openai_translate(src_text, project["src"], project["tgt"],
                                                gloss_hits=gloss_hits, tm_context=tm_hit,
                                                model=req.model)
                if translation:
                    used_provider = _resolve_model(req.model)["id"]
            elif _DEEP_TRANSLATE_OK:
                translation = _google_with_gloss(src_text, project["src"], project["tgt"], gloss_hits)
                if translation:
                    used_provider = PROVIDER_GOOGLE
            used_real_api = bool(translation)
        except Exception as e2:
            print(f"[backend] translate cross-fallback failed: {e2}", file=sys.stderr)

    if not translation:
        # Раньше сюда подставлялась заглушка "[GOOGLE demo translation...]" — в медицинском
        # переводе это недопустимо. Честно сообщаем об ошибке, сегмент не трогаем.
        raise HTTPException(502, "Перевод недоступен: оба движка вернули ошибку. "
                                 "Попробуйте ещё раз или проверьте API-ключи.")

    seg["target"] = translation
    seg["status"] = "translated"
    seg["route"] = "GPT_REQUIRED" if req.engine == "gpt" else "GOOGLE_SAFE"
    seg["provider"] = used_provider or (PROVIDER_GOOGLE if req.engine == "google" else _resolve_model(req.model)["id"])
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


def _text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _run_segment_backcheck(seg: dict, project: dict, model: Optional[str] = None,
                           use_judge: bool = False, judge_model: Optional[str] = None) -> dict:
    """Обратный перевод сегмента + оценка соответствия оригиналу.
    Результат кладётся в seg['backcheck'] вместе с хешем перевода — по нему
    повторный прогон понимает, что пересчитывать нечего."""
    target_text = (seg.get("target") or "").strip()
    if not target_text:
        return {"ok": False, "error": "Сегмент ещё не переведён"}

    mdl_id = _resolve_model(model or BACKCHECK_DEFAULT_MODEL)["id"]
    back = ""
    try:
        if os.environ.get("OPENAI_API_KEY"):
            back = _openai_translate(target_text, project["tgt"], project["src"],
                                     model=model or BACKCHECK_DEFAULT_MODEL, literal=True)
        elif _DEEP_TRANSLATE_OK:
            back = _deep_translate(target_text, project["tgt"], project["src"])
            mdl_id = PROVIDER_GOOGLE
    except Exception as e:
        print(f"[backend] backcheck seg#{seg.get('id')}: {e}", file=sys.stderr)
        try:
            back = _deep_translate(target_text, project["tgt"], project["src"])
            mdl_id = PROVIDER_GOOGLE
        except Exception as e2:
            return {"ok": False, "error": str(e2)}

    if not (back or "").strip():
        return {"ok": False, "error": "Обратный перевод не получен"}

    source_text = seg.get("source", "")
    gloss_hits, _tm = _get_context(source_text)
    semantic = _semantic_similarity(source_text, back)
    res = medical_qa_mod.run_backcheck(source_text, back, gloss_hits, semantic=semantic) if medical_qa_mod else {}

    # Судья — только для средней зоны: наверху и внизу шкалы вопрос уже решён
    judged = False
    if use_judge and medical_qa_mod and res.get("score") is not None:
        lo, hi = JUDGE_ZONE
        if lo <= res["score"] <= hi:
            verdict = _openai_judge(source_text, back, judge_model)
            if verdict:
                res = medical_qa_mod.apply_judge_verdict(res, verdict)
                judged = True

    seg["backtranslated_ru"] = back
    seg["backcheck"] = {
        "score": res.get("score"),
        "band": res.get("band"),
        "recall": res.get("recall"),
        "semantic": res.get("semantic"),
        "reasons": res.get("reasons", []),
        "terms_lost": res.get("terms_lost", []),
        "judge": res.get("judge"),
        "back": back,
        "model": mdl_id,
        "judged": judged,
        "target_hash": _text_hash(target_text),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return {"ok": True, "back": back, "backcheck": seg["backcheck"]}


class BackcheckRequest(BaseModel):
    model: Optional[str] = None
    use_judge: bool = False
    judge_model: Optional[str] = None


@app.post("/api/segments/{pid}/{sid}/backcheck")
def backcheck_segment(pid: int, sid: int, req: BackcheckRequest = BackcheckRequest()):
    """Обратный перевод target → язык оригинала + оценка соответствия.
    Обычный def: внутри блокирующий вызов модели (см. batch_translate)."""
    seg = get_segment(pid, sid)
    project = get_project(pid)
    result = _run_segment_backcheck(seg, project, req.model, req.use_judge, req.judge_model)
    if result.get("ok"):
        save_state(STATE)
        result["segment"] = seg
    return result


class BackcheckBatchRequest(BaseModel):
    segment_ids: Optional[list] = None
    limit: int = 10
    model: Optional[str] = None
    skip_cached: bool = True     # не пересчитывать сегменты с неизменившимся переводом
    use_judge: bool = False
    judge_model: Optional[str] = None


@app.post("/api/projects/{pid}/backcheck/batch")
def backcheck_batch(pid: int, req: BackcheckBatchRequest):
    """Пакетный back-check. Порционный, как и пакетный перевод: клиент гоняет
    порции по 10, поэтому один запрос не живёт дольше таймаута прокси."""
    project = get_project(pid)
    id_filter = set(req.segment_ids) if req.segment_ids is not None else None
    mdl_id = _resolve_model(req.model or BACKCHECK_DEFAULT_MODEL)["id"]

    candidates = []
    skipped_cached = 0
    for s in project["segments"]:
        if id_filter is not None and s["id"] not in id_filter:
            continue
        if not (s.get("target") or "").strip():
            continue
        if req.skip_cached:
            bc = s.get("backcheck") or {}
            # Включили судью после прогона без него — пересчитать надо
            if (bc.get("target_hash") == _text_hash(s["target"]) and bc.get("model") == mdl_id
                    and (not req.use_judge or bc.get("judged"))):
                skipped_cached += 1
                continue
        candidates.append(s)

    limit = max(1, min(req.limit, 100))
    remaining_after = max(0, len(candidates) - limit)
    targets = candidates[:limit]

    processed, errors = [], []
    for seg in targets:
        try:
            r = _run_segment_backcheck(seg, project, req.model, req.use_judge, req.judge_model)
            if r.get("ok"):
                processed.append(seg["id"])
            else:
                errors.append({"id": seg["id"], "error": r.get("error", "unknown")})
        except Exception as e:
            errors.append({"id": seg["id"], "error": str(e)})
            print(f"[backend] backcheck batch seg#{seg['id']}: {e}", file=sys.stderr)
    save_state(STATE)
    return {
        "ok": True,
        "processed": processed,
        "count": len(processed),
        "remaining": remaining_after,
        "skipped_cached": skipped_cached,
        "errors": errors,
        "model": mdl_id,
    }


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
    model: Optional[str] = None          # id из OPENAI_MODELS; неизвестный → DEFAULT_OPENAI_MODEL

@app.post("/api/projects/{pid}/batch")
def batch_translate(pid: int, req: BatchRequest):
    # ВАЖНО: обычный def, а не async def. Внутри блокирующие вызовы OpenAI/Google;
    # в async def они вешали единственный event loop uvicorn на всё время пакета —
    # сервер не отвечал даже на GET /api/projects/{pid} сразу после батча.
    project = get_project(pid)
    # is not None, а не truthy: пустой список — это «не выбрано ничего», и переводить
    # в этом случае надо ноль сегментов, а не весь проект.
    id_filter = set(req.segment_ids) if req.segment_ids is not None else None
    if req.force and id_filter is not None:
        # Явный выбор — переводим только указанные сегменты, кроме подтверждённых
        all_targets = [s for s in project["segments"] if s["id"] in id_filter and s["status"] != "confirmed"]
    else:
        all_targets = [s for s in project["segments"]
                       if s["status"] == "new" and
                       (s.get("risk", "medium") == "low" if req.engine == "google"
                        else s.get("risk", "medium") != "low") and
                       (id_filter is None or s["id"] in id_filter)]
    # Потолок на порцию: один HTTP-запрос не должен жить дольше proxy_read_timeout (1800s)
    # в nginx. При ~5-6 с на сегмент 100 штук — это ~10 минут, с большим запасом.
    limit = max(1, min(req.limit, 100))
    remaining_after = max(0, len(all_targets) - limit)
    targets = all_targets[:limit]
    translated = []
    tm_hits_count = 0
    errors = []
    for seg in targets:
        translation = None
        gloss_hits, tm_hit = _get_context(seg["source"])

        # TM точное совпадение → пропускаем API вызов.
        # При force (явный выбор пользователя: галочки или «перевести заново») шорткат
        # не применяем — иначе «перевести заново выбранной моделью» молча подставляло бы
        # старый текст из памяти. Так же ведёт себя одиночный перевод сегмента.
        if not req.force and tm_hit and tm_hit.get("tgt"):
            seg["target"] = tm_hit["tgt"]
            seg["status"] = "confirmed"
            seg["route"] = "EXACT_TM"
            seg["provider"] = PROVIDER_TM
            translated.append(seg["id"])
            tm_hits_count += 1
            continue

        used_provider = None   # чем на самом деле переведено — с учётом fallback на Google
        try:
            if req.engine == "google":
                translation = _google_with_gloss(seg["source"], project["src"], project["tgt"], gloss_hits)
                used_provider = PROVIDER_GOOGLE
            elif req.engine == "gpt" and os.environ.get("OPENAI_API_KEY"):
                translation = _openai_translate(seg["source"], project["src"], project["tgt"],
                                                gloss_hits=gloss_hits, tm_context=tm_hit,
                                                model=req.model)
                if translation:
                    used_provider = _resolve_model(req.model)["id"]
            if not translation and req.engine == "gpt":
                translation = _google_with_gloss(seg["source"], project["src"], project["tgt"], gloss_hits)
                if translation:
                    used_provider = PROVIDER_GOOGLE
        except Exception as e:
            errors.append(seg["id"])
            print(f"[backend] batch error seg#{seg['id']}: {e}", file=sys.stderr)
        if translation:
            seg["target"] = translation
            seg["status"] = "translated"
            seg["route"] = "GPT_REQUIRED" if req.engine == "gpt" else "GOOGLE_SAFE"
            seg["provider"] = used_provider or (PROVIDER_GOOGLE if req.engine == "google" else _resolve_model(req.model)["id"])
            translated.append(seg["id"])
    save_state(STATE)
    return {
        "ok": True,
        "translated": translated,
        "count": len(translated),
        "remaining": remaining_after,
        "errors": errors,
        "tm_hits": tm_hits_count,
        "model": _resolve_model(req.model)["id"] if req.engine == "gpt" else None,
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
    format: str          # "docx" | "xlsx" ("pdf" пока не поддерживается)
    source: bool = True  # включить колонку с оригиналом

EXPORT_DIR = DATA_DIR / "exports"   # внутри ReadWritePaths systemd-юнита

def _safe_filename(name: str) -> str:
    return _re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip() or "project"

def _generate_export(project: dict, fmt: str, include_source: bool = True) -> Path:
    """Собирает реальный файл экспорта. Раньше экспорт был фиктивным —
    файл не создавался вовсе, только запись в историю."""
    EXPORT_DIR.mkdir(exist_ok=True)
    out = EXPORT_DIR / f"{_safe_filename(project['title'])}.{fmt}"
    segs = project["segments"]
    if fmt == "docx":
        from docx import Document
        doc = Document()
        doc.add_heading(project["title"], level=1)
        doc.add_paragraph(f"{project.get('src','RU')} → {project.get('tgt','EN')} · "
                          f"сегментов: {len(segs)} · экспорт: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        if include_source:
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            hdr = table.rows[0].cells
            hdr[0].text, hdr[1].text, hdr[2].text = "#", "Источник", "Перевод"
            for s in segs:
                row = table.add_row().cells
                row[0].text = str(s["id"])
                row[1].text = s.get("source", "")
                row[2].text = s.get("target", "")
        else:
            for s in segs:
                if s.get("target"):
                    doc.add_paragraph(s["target"])
        doc.save(str(out))
    elif fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Segments"
        ws.append(["#", "Источник", "Перевод", "Статус", "Маршрут", "Риск"])
        for s in segs:
            ws.append([s["id"], s.get("source", ""), s.get("target", ""),
                       s.get("status", ""), s.get("route", ""), s.get("risk", "")])
        wb.save(str(out))
    else:
        raise HTTPException(400, f"Формат {fmt} не поддерживается")
    return out

@app.post("/api/projects/{pid}/export")
def export_project(pid: int, req: ExportRequest):
    project = get_project(pid)
    fmt = req.format.lower()
    if fmt not in {"docx", "xlsx"}:
        return {"ok": False,
                "error": f"Формат {fmt.upper()} пока не поддерживается — выберите DOCX или Excel."}
    try:
        path = _generate_export(project, fmt, include_source=req.source)
    except ImportError as e:
        return {"ok": False, "error": f"На сервере нет библиотеки для {fmt.upper()}: {e}"}
    size_kb = max(1, path.stat().st_size // 1024)
    STATE["exportHistory"].insert(0, {
        "file": path.name,
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "size": f"{size_kb} КБ",
    })
    STATE["exportHistory"] = STATE["exportHistory"][:50]
    save_state(STATE)
    return {"ok": True, "file": path.name, "size": f"{size_kb} КБ",
            "url": f"/api/projects/{pid}/export/download?format={fmt}&source={1 if req.source else 0}"}

@app.get("/api/projects/{pid}/export/download")
def download_export(pid: int, format: str = "docx", source: bool = True):
    project = get_project(pid)
    fmt = format.lower()
    if fmt not in {"docx", "xlsx"}:
        raise HTTPException(400, "Поддерживаются только docx и xlsx")
    path = _generate_export(project, fmt, include_source=source)
    media = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if fmt == "docx"
             else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return FileResponse(str(path), media_type=media, filename=path.name)


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
        "version": "5.6.0",
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
