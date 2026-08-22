"""
FastAPI backend for Medical CAT Translator v5.5
Serves the React design at /, exposes REST API at /api/*

Авторизация: POST /api/auth/login отдаёт токен сессии; его нужно присылать
в заголовке `Authorization: Bearer <token>` во ВСЕ остальные /api/* запросы.
Публичны только /api/auth/login, /api/auth/logout и /api/health.

Endpoints:
  GET  /api/seed                          → all initial data (projects, glossary, tm, etc.)
  POST /api/auth/login                    → password check → token
  POST /api/auth/logout                   → invalidate token
  GET  /api/projects                      → list projects
  POST /api/projects                      → create project (from DOCX or empty)
  GET  /api/projects/{pid}                → project detail
  POST /api/segments/{pid}/{sid}/translate → translate via Google or GPT
  POST /api/segments/{pid}/{sid}/qa       → run QA
  POST /api/segments/{pid}/{sid}/confirm  → confirm + add to TM
  POST /api/segments/{pid}/{sid}/revert   → revert confirmed/failed
  POST /api/segments/{pid}/{sid}/update   → update target/comment
  POST /api/projects/{pid}/batch          → batch translate (выбранной моделью)
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
import time
import hmac
import hashlib
import secrets
import asyncio
import threading
from pathlib import Path
from typing import Optional, Any, List
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
tm_mod = _safe_import("tm")
medical_qa_mod = _safe_import("medical_qa")
# Внешние источники приказов: отраслевые справочники и корпуса целевого языка.
# Без них термин может заверить только человек — а он целевого языка может
# и не знать. См. шапку authorities.py.
authorities_mod = _safe_import("authorities")

# Google Translate убран из системы. Перевод делает ТОЛЬКО выбранная модель:
# бесплатный движок не знает предметной области, игнорирует глоссарий (кроме
# грубой подстановки плейсхолдерами) и давал текст, который потом всё равно
# приходилось чинить платными прогонами. Экономия была мнимой.
#
# Отсюда следует: нет ключа OpenAI — нет перевода. Не заглушка, не «черновик
# бесплатным движком», а честная ошибка. Исторические сегменты с
# provider="google" и route="GOOGLE_SAFE" остаются как есть: это факт о том,
# чем их перевели, и переписывать его нельзя.

import re as _re

def _term_match(term: str, text: str) -> str | None:
    """Ищет термин (в любой грамматической форме) в тексте.
    Возвращает фактически найденную подстроку или None.

    Алгоритм:
    1. Точное совпадение (быстро).
    2. Стеминг: первые 85% символов каждого слова термина (мин. 4) +
       любое кириллическое окончание.  Без внешних зависимостей.
       "лимфангит"     → стем "лимфанг"  → найдёт "лимфангита", "лимфангите"
       "первичный очаг" → стемы "первичн", "очаг"
                        → найдёт "первичного очага", "первичному очагу"

    Порог именно 85%, а не 75%: на 75% "циклоз" (стем "цикл") ловил "циклит"
    и подсовывал модели "cyclosis" вместо "cyclitis". Медицинские термины
    различаются как раз хвостом (-ит / -оз / -ома), срезать его нельзя.
    """
    exact, stem = _term_patterns(term)
    if exact is None:
        return None
    hit = exact.search(text)
    if hit:
        return hit.group(0)
    hit = stem.search(text) if stem is not None else None
    return hit.group(0) if hit else None


_PATTERN_CACHE: dict = {}
_PATTERN_CACHE_MAX = 20000


def _term_patterns(term: str):
    """Скомпилированные шаблоны термина: точный (по границам слова) и стем-поиск.

    Раньше обе регулярки собирались и компилировались на КАЖДОЕ сравнение.
    На словаре в 10 000 записей внутренний кэш re переполнялся и компилировал
    заново — отбор кандидатов для одного сегмента стоил 130 мс вместо единиц."""
    cached = _PATTERN_CACHE.get(term)
    if cached is not None:
        return cached
    tl = (term or "").lower()
    parts = tl.split()
    if not parts:
        pair = (None, None)
    else:
        # 1. Точное совпадение — обязательно по границам слова. Без этой проверки
        #    трёхбуквенные записи глоссария лезли внутрь чужих слов: «жалобы» →
        #    «лоб», «профилактика» → «лак», «диагностики» → «нос».
        exact = _re.compile(r'(?<![а-яёА-ЯЁa-zA-Z])' + _re.escape(tl) + r'(?![а-яёА-ЯЁa-zA-Z])',
                            _re.IGNORECASE)
        # 2. Стеминг по словам
        stems = [_re.escape(w[:max(4, int(len(w) * 0.85))]) + r'[а-яёА-ЯЁ]*' for w in parts]
        stem = _re.compile(r'(?<![а-яёА-ЯЁa-zA-Z])' + r'\s+'.join(stems), _re.IGNORECASE)
        pair = (exact, stem)
    if len(_PATTERN_CACHE) >= _PATTERN_CACHE_MAX:
        _PATTERN_CACHE.clear()
    _PATTERN_CACHE[term] = pair
    return pair


# ─── Уровни доверия глоссария ────────────────────────────────────────
# 9132 записи из 10022 пришли массовым автоимпортом (Sources=baldwin_*), и там
# лежит, например, «задний → rear». Такие записи модель получает как подсказку,
# а не как приказ: "use these exact translations" на них давало кальки вроде
# "rear cyclitis". Проверенные (отраслевые списки + одобренное человеком)
# остаются жёстким правилом. Записи не удаляем — понижаем в правах.
GLOSSARY_TIER_HARD = "verified"
GLOSSARY_TIER_SOFT = "auto"


def _tier_from_origin(origin: str) -> str:
    return GLOSSARY_TIER_SOFT if "baldwin" in (origin or "").lower() else GLOSSARY_TIER_HARD


# ─── Область действия записи: языковая пара + тематика ───────────────
# Глоссарий и TM одни на весь сервис, а проекты бывают разные. Запись,
# одобренная в RU→DE юридическом проекте, не должна лезть в промпт RU→EN
# медицинского: это ровно тот путь, которым «задний → rear» переезжает из
# одного текста в другой. У старых записей полей нет — они пришли из
# медицинского RU→EN импорта, поэтому ОТСУТСТВИЕ поля читается как этот
# дефолт, а не как «годится везде». Массовую миграцию не делаем: 10 022
# записи × два поля — лишние сотни килобайт в state.json на каждое сохранение.
DEFAULT_GLOSS_LANG = "RU→EN"
DEFAULT_GLOSS_DOMAIN = "medical"


def _lang_pair(project: Optional[dict]) -> str:
    return f"{(project or {}).get('src', 'RU')}→{(project or {}).get('tgt', 'EN')}"


def _scope_of(entry: dict) -> tuple:
    """(языковая пара, тематика) записи глоссария или кандидата."""
    return (entry.get("lang") or DEFAULT_GLOSS_LANG,
            entry.get("domain") or DEFAULT_GLOSS_DOMAIN)


def _project_scope(project: Optional[dict]) -> tuple:
    if project is None:
        return (DEFAULT_GLOSS_LANG, DEFAULT_GLOSS_DOMAIN)
    return (_lang_pair(project), _resolve_domain(project.get("domain"))["id"])


def _hit_tier(h: dict) -> str:
    """Уровень доверия записи. Отсутствие поля читается как ПОДСКАЗКА, а не
    приказ: запись неизвестного происхождения не должна принуждать модель и
    подставляться в перевод плейсхолдером мимо всех проверок. Исторические
    записи уровень получают миграцией при загрузке состояния."""
    return h.get("tier") or GLOSSARY_TIER_SOFT


def _hit_rank(h: dict) -> tuple:
    """Кого оставить, когда на одну форму претендуют несколько записей:
    сначала проверенные, потом более длинный (более специфичный) термин, при
    равенстве — с более коротким переводом. Последнее отсекает обрезанные
    записи вроде «периферическая → peripheral nervous system», которые тянут
    в перевод лишнее понятие."""
    return (1 if _hit_tier(h) == GLOSSARY_TIER_HARD else 0,
            len(h.get("src", "")), -len(h.get("tgt", "")))


# ─── Индекс глоссария ────────────────────────────────────────────────
# Без него _get_context гонял ~10 000 регулярок на КАЖДЫЙ сегмент: 10-17 секунд
# чистого CPU, которые прятались за временем ответа модели (и превращали пакет
# из 2000 сегментов в лишние часы). Теперь по тексту собираются 4-символьные
# ключи, и полную проверку проходят только записи из совпавших корзин.
_GLOSS_INDEX = None          # {ключ: [записи глоссария]}
_GLOSS_INDEX_LOCK = threading.Lock()


def _index_key(word: str) -> str:
    return word[:4]


def _entry_keys(src: str) -> set:
    """Ключи записи — по первому слову термина: именно с него начинается и
    точное совпадение, и стем-поиск."""
    first = (src or "").lower().split()
    if not first:
        return set()
    w = first[0]
    return {_index_key(w)} if len(w) >= 4 else {w}


def _text_keys(text: str) -> set:
    """Ключи текста — только НАЧАЛА слов. С тех пор как точное совпадение требует
    границы слова, термин не может начаться в середине чужого слова, и окна по
    всей длине слова давали лишь лишних кандидатов: на длинном сегменте отбор
    вырождался в перебор всего глоссария (134 мс против 2 мс на сегмент)."""
    keys = set()
    for w in _re.findall(r"[а-яёa-z0-9]+", (text or "").lower()):
        # Короткие записи («ЭКГ», «КТ») лежат в корзине целого слова
        keys.update(w[:n] for n in (1, 2, 3, 4) if len(w) >= n)
    return keys


def _gloss_index() -> dict:
    global _GLOSS_INDEX
    idx = _GLOSS_INDEX
    if idx is not None:
        return idx
    with _GLOSS_INDEX_LOCK:
        if _GLOSS_INDEX is None:
            idx = {}
            for g in STATE.get("glossary", []):
                for k in _entry_keys(g.get("src", "")):
                    idx.setdefault(k, []).append(g)
            _GLOSS_INDEX = idx
            print(f"[backend] glossary index: {len(idx)} keys / "
                  f"{len(STATE.get('glossary', []))} terms", file=sys.stderr)
        return _GLOSS_INDEX          # локальная ссылка: см. _gloss_by_src


_GLOSS_BY_SRC: Optional[dict] = None


def _invalidate_gloss_index():
    """Любая правка глоссария роняет индекс — соберётся заново при следующем поиске.
    Заодно двигает поколение: отчёт о расхождениях считается от глоссария."""
    global _GLOSS_INDEX, _GLOSS_BY_SRC
    _GLOSS_INDEX = None
    _GLOSS_BY_SRC = None
    _GLOSS_EPOCH[0] += 1


def _get_context(text: str, with_tm: bool = True, project: Optional[dict] = None):
    """Возвращает (gloss_hits, tm_hit) для исходного текста.

    gloss_hits — список dict {src, tgt, ..., _form} где _form — фактическая
                 форма термина найденная в тексте (нужна для замены).
    tm_hit     — точное совпадение в TM или None. with_tm=False пропускает поиск
                 по памяти переводов: отчёту о расхождениях он не нужен, а это
                 линейный проход по всей TM на каждый сегмент.
    """
    hits = []
    idx = _gloss_index()
    keys = _text_keys(text)
    seen_ids = set()
    candidates = []
    for k in keys:
        for g in idx.get(k, ()):
            if id(g) not in seen_ids:
                seen_ids.add(id(g))
                candidates.append(g)
    scope = _project_scope(project)
    for g in candidates:
        src = g.get("src", "")
        if not src:
            continue
        # Чужая языковая пара или тематика — мимо: в промпт уходят только
        # записи, заведённые для таких же проектов.
        if _scope_of(g) != scope:
            continue
        form = _term_match(src, text)
        if form:
            hits.append({**g, "_form": form})
    # Одна форма — один перевод. «периферические» ловило сразу три записи
    # (peripheral / periphery / peripheral nervous system), и модель выбирала
    # сама. Оставляем лучшую по _hit_rank, остальные отбрасываем.
    best: dict = {}
    for h in hits:
        key = h["_form"].lower()
        if key not in best or _hit_rank(h) > _hit_rank(best[key]):
            best[key] = h
    # Длинные термины первыми: меньше риск перекрытия плейсхолдеров
    hits = sorted(best.values(), key=lambda x: len(x["src"]), reverse=True)[:15]
    if not with_tm:
        return hits, None
    # TM хранит языковую пару с самого начала — и обязана её учитывать: без
    # этого RU→DE проект получил бы английский перевод как точное совпадение,
    # да ещё со статусом confirmed.
    tm_hit = next(
        (t for t in STATE.get("tm", [])
         if t.get("src", "").strip().lower() == text.strip().lower()
         and (t.get("lang") or DEFAULT_GLOSS_LANG) == scope[0]),
        None,
    )
    return hits, tm_hit


def _replace_target(seg: dict, text: str, provider: str, route: str):
    """Записать в сегмент новый перевод. Единственное место, где машина имеет
    право заменить текст, и правило тут одно на всех: если перевод заверял
    человек, прежний текст сохраняется в prevTarget, статус становится
    «требует проверки», а отметка «подтвердил человек» снимается — она
    относилась к тексту, которого больше нет."""
    if seg.get("status") == "confirmed":
        seg["prevTarget"] = seg.get("target", "")
        seg.pop("confirmedBy", None)
        seg.pop("confirmedAt", None)
        seg["status"] = "review"
    else:
        seg["status"] = "translated"
    seg["target"] = text
    seg["provider"] = provider
    seg["route"] = route


def _tm_trusted(t: Optional[dict]) -> bool:
    """Право подменить перевод МИМО модели есть только у записей, рождённых
    подтверждением человека в этой системе (`quality: verified`).

    Память переводов — единственное место, где чужая ошибка попадала в перевод,
    минуя и глоссарий, и все проверки: совпадение отдавалось как есть. Записи
    неизвестного происхождения (импорт, `draft`) остаются в промпте справкой,
    а перевод делает модель — и его есть чем проверить."""
    return bool(t) and (t.get("quality") or "draft") == GLOSSARY_TIER_HARD


# ─── Предметные области ──────────────────────────────────────────────
# Сервис не привязан к медицине: область — параметр проекта. Это ЕДИНСТВЕННОЕ
# место, где живёт доменная специфика промптов (перевод и проверка терминов).
# Добавили направление — добавили строку, больше править нечего.
#   expert      — кем модель себя считает при переводе;
#   terminology — что считать эталоном терминологии;
#   examples    — типичные кальки этой области (можно пусто).
DOMAINS = [
    {"id": "medical", "label": "Медицина", "en": "medical",
     "cats": ["Anatomy", "Cardiology", "Disease", "Dosage", "Symptom", "Lab", "Procedure", "Device", "Document"],
     "extract": "Domain terminology only: diseases, anatomy, procedures, drugs, lab tests, devices.",
     "expert": "medical translator specializing in biomedical and clinical texts",
     "terminology": "standard medical terminology as used in peer-reviewed clinical literature",
     "examples": "BAD: 'oxide nitrogena', 'leukocidin', 'rear cyclitis'. "
                 "GOOD: 'nitric oxide', 'leukocytes', 'posterior cyclitis'."},
    {"id": "pharma", "label": "Фармацевтика", "en": "pharmaceutical",
     "cats": ["Substance", "Dosage", "Form", "Route", "Regulatory", "Trial", "Document"],
     "extract": "Domain terminology only: substances, dosage forms, routes, regulatory and trial terms.",
     "expert": "pharmaceutical translator working on drug labels, SmPCs and clinical trial documents",
     "terminology": "standard pharmaceutical and regulatory terminology (INN names, dosage forms, routes)",
     "examples": ""},
    {"id": "legal", "label": "Юриспруденция", "en": "legal",
     "cats": ["Contract", "Court", "Corporate", "Property", "Obligation", "Party", "Document"],
     "extract": "Domain terminology only: legal concepts, instruments, procedural and corporate terms.",
     "expert": "legal translator working on contracts, court documents and corporate filings",
     "terminology": "standard legal terminology of the target language, keeping the legal effect intact",
     "examples": ""},
    {"id": "technical", "label": "Техника", "en": "technical",
     "cats": ["Part", "Material", "Process", "Measurement", "Safety", "Equipment", "Document"],
     "extract": "Domain terminology only: parts, materials, processes, measurements, equipment.",
     "expert": "technical translator working on engineering documentation and manuals",
     "terminology": "standard engineering terminology and unit conventions",
     "examples": ""},
    {"id": "finance", "label": "Финансы", "en": "financial",
     "cats": ["Accounting", "Reporting", "Tax", "Instrument", "Metric", "Audit", "Document"],
     "extract": "Domain terminology only: accounting, reporting, tax and instrument terms.",
     "expert": "financial translator working on reports, statements and audit documents",
     "terminology": "standard accounting and financial terminology",
     "examples": ""},
    {"id": "it", "label": "IT", "en": "software",
     "cats": ["UI", "API", "Data", "Security", "Infrastructure", "Process", "Document"],
     "extract": "Domain terminology only: interface, API, data, security and infrastructure terms.",
     "expert": "software localization specialist",
     "terminology": "established terminology of the platform and the target locale",
     "examples": ""},
    {"id": "general", "label": "Общая тематика", "en": "general-purpose",
     "cats": ["Term", "Name", "Document"],
     "extract": "Only stable multi-word terms and named entities; skip ordinary vocabulary.",
     "expert": "professional translator",
     "terminology": "standard contemporary usage",
     "examples": ""},
]
DEFAULT_DOMAIN = "medical"      # исторически сервис начинался с медицины
_DOMAINS_BY_ID = {d["id"]: d for d in DOMAINS}


def _resolve_domain(domain_id: Optional[str]) -> dict:
    """Неизвестная/пустая область → дефолт. У старых проектов поля нет вовсе."""
    return _DOMAINS_BY_ID.get(domain_id or "") or _DOMAINS_BY_ID[DEFAULT_DOMAIN]


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

# ── Справочник силы моделей ──────────────────────────────────────────────────
# Нужен для одного решения: вправе ли проверка одной моделью перезаписать
# готовую проверку, сделанную другой. Более слабая не вправе — иначе вердикт
# Sol на тысяче сегментов молча заменяется вердиктом Terra, и человек платит
# за понижение качества.
#
# Ранг лежит ФАЙЛОМ, а не в коде: список моделей меняется чаще, чем выходят
# релизы сервиса, и обновление ранга не должно требовать деплоя. Копия в
# data/ сильнее репозиторной: её правят на сервере, и git pull её не затрёт.
# Из цены ранг не выводится (GPT-5.5 стоит как Sol и слабее его), из даты
# тоже (у одного поколения три разных уровня) — только руками.
MODEL_RANK_FILES = [ROOT / "backend" / "model_ranks.json",
                    ROOT / "backend" / "data" / "model_ranks.json"]
_MODEL_RANKS: dict = {}
_MODEL_RANKS_STAMP: tuple = ()
_MODEL_RANKS_CHECKED: float = 0.0
# Как часто ходим на диск за временем правки. Ранг спрашивают на каждый сегмент
# каждого шага: на проекте в 2670 строк это 37 000 вызовов stat() на один разбор
# прогона — половина его времени уходила в файловую систему. Две секунды — это
# по-прежнему «правка подхватывается без рестарта», но уже не по разу на сегмент.
MODEL_RANKS_RECHECK_SEC = 2.0


def _model_ranks() -> dict:
    """Справочник с диска. Перечитывается, когда файл менялся: смысл выносить
    его из кода теряется, если для правки нужен рестарт сервиса."""
    global _MODEL_RANKS, _MODEL_RANKS_STAMP, _MODEL_RANKS_CHECKED
    now = time.monotonic()
    # Пустой _MODEL_RANKS_STAMP — просьба перечитать немедленно (так это делает
    # тест). Обычный путь: не чаще раза в MODEL_RANKS_RECHECK_SEC.
    if (_MODEL_RANKS and _MODEL_RANKS_STAMP
            and (now - _MODEL_RANKS_CHECKED) < MODEL_RANKS_RECHECK_SEC):
        return _MODEL_RANKS
    _MODEL_RANKS_CHECKED = now
    stamp = []
    for p in MODEL_RANK_FILES:
        try:
            stamp.append(p.stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    stamp = tuple(stamp)
    if stamp == _MODEL_RANKS_STAMP and _MODEL_RANKS:
        return _MODEL_RANKS
    ranks: dict = {}
    for p in MODEL_RANK_FILES:          # порядок важен: data/ идёт вторым и побеждает
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except Exception as e:
            # Битый справочник не роняет сервис и не подменяется пустым молча:
            # без рангов защита от понижения выключится, и об этом надо знать.
            print(f"[backend] справочник рангов {p} не прочитан: {e}", file=sys.stderr)
            continue
        for mid, rank in (data.get("ranks") or {}).items():
            if isinstance(rank, int) and not isinstance(rank, bool):
                ranks[str(mid)] = rank
    _MODEL_RANKS, _MODEL_RANKS_STAMP = ranks, stamp
    return ranks


def model_rank(mid: str) -> Optional[int]:
    """None — «не знаю», а не «слабая». Неизвестность не даёт права ни
    перезаписать чужую проверку, ни назвать её действительной."""
    return _model_ranks().get(mid or "")


def _rank_not_weaker(have: str, want: str) -> bool:
    """Проверка моделью have не слабее той, что дала бы want.

    Неизвестный ранг с любой стороны — False, то есть «проверить заново».
    Обратный выбор был бы хуже: сегмент остался бы с вердиктом модели, про
    которую мы ничего не знаем, а человек читал бы его как вердикт выбранной.
    Цена ошибки — один вызов и строка в разборе прогона, после которой модель
    дописывают в справочник."""
    if have and have == want:
        return True
    rh, rw = model_rank(have), model_rank(want)
    if rh is None or rw is None:
        return False
    return rh >= rw

# seg["provider"] — чем сегмент переведён по факту: id модели OpenAI, либо эти константы.
# Поле проставляется в момент перевода; у сегментов, переведённых до его появления,
# его нет, и фронтенд показывает приблизительное значение по seg["route"].
# Осталось только для чтения истории: старые сегменты помечены этим
# провайдером и маршрутом GOOGLE_SAFE. Новый перевод так не помечается
# никогда — движок один, выбранная модель.
PROVIDER_GOOGLE = "google"
PROVIDER_TM = "tm"

# Для обратного перевода нужна не лучшая модель, а самая буквальная и дешёвая:
# её задача — зеркалить текст, а не переводить его хорошо. Чем «умнее» модель,
# тем охотнее она чинит ошибки на лету и прячет их от проверки.
BACKCHECK_DEFAULT_MODEL = "gpt-5.6-luna"
# Запасная — когда запрошенная модель совпала с автором текста (см.
# _backcheck_model). Требования те же: буквальная и дешёвая.
BACKCHECK_FALLBACK_MODEL = "gpt-4o-mini"

# Семантическая близость оригинала и обратного перевода. Лексическая база не умеет
# в синонимы: «больному назначен» против «пациенту назначили» — это один смысл и
# разные основы. Эмбеддинги закрывают ровно этот разрыв.
EMBED_MODEL = "text-embedding-3-small"
# Судья вызывается только в средней зоне: наверху и внизу шкалы решение уже принято
# детерминированными проверками, и платить за подтверждение очевидного незачем.
JUDGE_ZONE = (50, 97)

# У судьи СВОЯ модель, отдельная от модели обратного перевода, и это намеренно:
# задачи прямо противоположные. Обратному переводу нужна максимально буквальная
# и тупая модель, которая не чинит ошибки; судье — наоборот, сильная, способная
# отличить подмену понятия от синонима. Одна модель на обе роли работала бы плохо
# в одной из них.
JUDGE_DEFAULT_MODEL = "gpt-5.6-terra"
# Проверке терминологии нужна сильная модель: слабая либо пропускает кальки,
# либо начинает придираться к нормальным синонимам. Дефолт перевода (gpt-4o)
# для этой роли слабоват, поэтому берём ту же модель, что и судья.
TERMCHECK_DEFAULT_MODEL = os.environ.get("TERMCHECK_MODEL", JUDGE_DEFAULT_MODEL)
# Ремонт переписывает текст по списку претензий — это работа для сильной модели.
REPAIR_DEFAULT_MODEL = os.environ.get("REPAIR_MODEL", JUDGE_DEFAULT_MODEL)


def _openai_embed(texts: list) -> list:
    import openai
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=60, max_retries=2)
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    _note_usage("embed", EMBED_MODEL, resp)
    return [d.embedding for d in resp.data]


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return (dot / (na * nb)) if na and nb else 0.0


# Тексты повторяются: один и тот же оригинал эмбеддится на каждом перепрогоне
# back-check и в каждом дубле сегмента. Кэш живёт в памяти процесса.
_EMBED_CACHE: dict = {}
_EMBED_CACHE_MAX = 4000


def _embed_cached(texts: list) -> list:
    keys = [_text_hash(t) for t in texts]
    missing = [t for t, k in zip(texts, keys) if k not in _EMBED_CACHE]
    if missing:
        uniq = list(dict.fromkeys(missing))
        for t, vec in zip(uniq, _openai_embed(uniq)):
            _EMBED_CACHE[_text_hash(t)] = vec
        if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
            for k in list(_EMBED_CACHE)[:len(_EMBED_CACHE) - _EMBED_CACHE_MAX]:
                _EMBED_CACHE.pop(k, None)
    return [_EMBED_CACHE[k] for k in keys]


def _semantic_similarity(source_ru: str, back_ru: str):
    """Косинус между оригиналом и обратным переводом. None — если посчитать не вышло."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        vecs = _embed_cached([source_ru, back_ru])
        return _cosine(vecs[0], vecs[1])
    except Exception as e:
        print(f"[backend] embed failed: {e}", file=sys.stderr)
        return None


def _judge_system(domain: dict, src_lang: str) -> str:
    """Промпт судьи. Раньше он был зашито медицинским и русским: «Ты —
    медицинский редактор», примеры про лимфаденит, «текст на русском».
    Для юридического проекта на немецкий это мешало, а не помогало."""
    return (
        "Ты — редактор перевода, специализация: " + domain["label"].lower() + ". "
        "Тебе дают исходный текст (язык: " + src_lang + ") и его ОБРАТНЫЙ перевод "
        "(текст перевели на другой язык, затем обратно). Твоя задача — понять, "
        "сохранился ли смысл.\n\n"
        "Считай расхождением: подмену понятия или термина на другое (даже похожее по "
        "звучанию — это разные вещи), изменение числа, количества, единицы, отрицания, "
        "стороны, направления, степени уверенности утверждения.\n"
        "НЕ считай расхождением: синонимы, изменённый порядок слов, стилистические "
        "различия, разные грамматические формы, если смысл тот же.\n\n"
        "Верни ТОЛЬКО JSON без пояснений:\n"
        '{"same_meaning": true|false, "severity": "none"|"minor"|"major"|"critical", '
        '"divergences": ["короткое описание расхождения"], "comment": "одно предложение по-русски"}\n'
        "severity: none — смысл идентичен; minor — стилистика; major — заметное смысловое "
        "расхождение; critical — подмена понятия, числа, отрицания или стороны."
    )


# ─── Проверка терминологии перевода ──────────────────────────────────
# Back-check спрашивает «пережил ли смысл круг» и на кальке всегда отвечает
# «да»: «rear cyclitis» дословно возвращается как «задний циклит» и совпадает
# с оригиналом. Здесь задан противоположный вопрос — «нормальный ли это термин
# целевого языка», и смотрим мы ТОЛЬКО на перевод, оригинал нужен лишь для
# привязки термина. Область берётся из проекта: медицина ничем не выделена.
TERMCHECK_SEVERITY = ["critical", "major", "minor"]


def _termcheck_system(domain: dict, src_lang: str, tgt_lang: str) -> str:
    return (
        "You are a terminology reviewer for " + domain["en"] + " translations from "
        + src_lang + " into " + tgt_lang + ".\n"
        "You get SOURCE and TRANSLATION. Judge ONLY the terminology of the TRANSLATION.\n\n"
        "Flag a term when it is:\n"
        "  - a calque or word-by-word rendering that is not a real term in " + tgt_lang + ";\n"
        "  - a transliteration of a source-language or Latin word instead of the accepted term;\n"
        "  - a different concept than the source term (substitution);\n"
        "  - garbled, truncated or fused with digits/other words;\n"
        "  - wrong register for " + domain["en"] + " documents (everyday word instead of the professional term).\n\n"
        "DO NOT flag: style preferences, synonyms that are both standard, "
        "British vs American spelling, sentence structure, punctuation, anything in the SOURCE.\n"
        "Be conservative: if unsure whether a term is standard, do NOT flag it.\n"
        "The suggestion must be a term actually used in " + tgt_lang + " " + domain["en"]
        + " literature, never your own invention.\n\n"
        'Return ONLY JSON, no prose:\n'
        '{"findings": [{"src_term": "<the matching fragment of SOURCE, or empty>", '
        '"tgt_term": "<the exact fragment of TRANSLATION that is wrong>", '
        '"suggestion": "<the correct term>", "severity": "critical|major|minor", '
        '"why": "<one short sentence in Russian>"}]}\n'
        "severity: critical — a different concept or an unreadable fragment; "
        "major — not a real term of the target language; minor — understandable but non-standard.\n"
        'If the terminology is fine, return {"findings": []}.'
    )


def _openai_termcheck(source: str, target: str, src_lang: str, tgt_lang: str,
                      domain_id: Optional[str] = None, model: str = None) -> Optional[dict]:
    """Разбор перевода моделью. None — вызов не удался (сегмент не трогаем)."""
    import json as _json
    import openai
    dom = _resolve_domain(domain_id)
    mdl = _resolve_model(model or TERMCHECK_DEFAULT_MODEL)
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=90, max_retries=1)
    extra = ({"max_completion_tokens": 2048} if mdl["api"] == "modern"
             else {"max_tokens": 700, "temperature": 0})
    try:
        resp = client.chat.completions.create(
            model=mdl["id"],
            messages=[
                {"role": "system", "content": _termcheck_system(dom, src_lang, tgt_lang)},
                {"role": "user", "content": "SOURCE:\n" + source + "\n\nTRANSLATION:\n" + target},
            ],
            **extra,
        )
        _note_usage("termcheck", mdl["id"], resp)
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        data = _json.loads(m.group(0))
        out = []
        for f in (data.get("findings") or []):
            if not isinstance(f, dict):
                continue
            tgt_term = (f.get("tgt_term") or "").strip()
            if not tgt_term:
                continue
            sev = (f.get("severity") or "major").lower()
            out.append({
                "src_term": (f.get("src_term") or "").strip(),
                "tgt_term": tgt_term,
                "suggestion": (f.get("suggestion") or "").strip(),
                "severity": sev if sev in TERMCHECK_SEVERITY else "major",
                "why": (f.get("why") or "").strip(),
            })
        return {"findings": out, "model": mdl["id"]}
    except Exception as e:
        print(f"[backend] termcheck failed: {e}", file=sys.stderr)
        return None


def _openai_judge(source_ru: str, back_ru: str, model: str = None,
                  domain_id: Optional[str] = None, src_lang: str = "RU") -> Optional[dict]:
    """Вердикт модели по паре «оригинал / обратный перевод»."""
    import json as _json
    import openai
    dom = _resolve_domain(domain_id)
    mdl = _resolve_model(model or JUDGE_DEFAULT_MODEL)
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=90, max_retries=1)
    extra = ({"max_completion_tokens": 2048} if mdl["api"] == "modern"
             else {"max_tokens": 500, "temperature": 0})
    try:
        resp = client.chat.completions.create(
            model=mdl["id"],
            messages=[
                {"role": "system", "content": _judge_system(dom, src_lang)},
                {"role": "user", "content": "ОРИГИНАЛ:\n" + source_ru + "\n\nОБРАТНЫЙ ПЕРЕВОД:\n" + back_ru},
            ],
            **extra,
        )
        _note_usage("judge", mdl["id"], resp)
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


# ─── Учёт фактического расхода ───────────────────────────────────────────────
# Смета до прогона считается по объёму текста и обязана ошибаться: сколько
# модель ответит, знает только сама модель. Беда была не в этом, а в том, что
# фактический расход НИГДЕ не записывался: поправить смету было не по чему —
# сравнивать не с чем. Так и жила ошибка termcheck: смета клала 450 выходных
# токенов на сегмент, а ответ занимал 37.
#
# Поэтому usage снимается с КАЖДОГО ответа модели. Это не оценка и не наш
# пересчёт объёма текста — это то, за что выставит счёт провайдер.
#
# Куда писать — одна переменная процесса, а не контекст вызова: прогон
# в системе один (тот же инвариант, что и один воркер uvicorn), а
# _run_parallel раздаёт работу в ThreadPoolExecutor, который contextvars
# не наследует, так что contextvars сюда просто не доедут.
#
# Учёт не имеет права ломать работу: всё, что он делает, обёрнуто в try.
# Перевод, не состоявшийся из-за бухгалтерии, — цена, несоизмеримая
# с точностью сметы.

# Модели, которые человек не выбирает, но которые стоят денег. В OPENAI_MODELS
# им не место: оттуда строится выпадающий список, и эмбеддингом никто не
# переводит. Цена — та же единица измерения, USD за 1M токенов.
AUX_MODEL_PRICES = {EMBED_MODEL: {"in": 0.02, "out": 0.0}}

RUN_COST_HISTORY = 100          # сколько прогонов помним в state.json

_USAGE_LOCK = threading.Lock()
_USAGE_SINK: Optional[dict] = None      # счётчик идущего прогона; None — вне прогона


def _usage_zero() -> dict:
    return {"calls": 0, "in": 0, "cached_in": 0, "out": 0, "reasoning": 0,
            "cost": 0.0, "unpriced": 0, "steps": {}, "models": {}}


def _usage_leaf() -> dict:
    return {"calls": 0, "in": 0, "cached_in": 0, "out": 0, "reasoning": 0,
            "cost": 0.0, "unpriced": 0}


# Расход процесса с момента старта. Прогоны живут в памяти и теряются при
# рестарте, а одиночные вызовы (перевод сегмента по кнопке) не принадлежат
# ни одному прогону — но деньги стоят.
_USAGE_TOTAL: dict = _usage_zero()


def _model_price(mid: Optional[str]) -> Optional[dict]:
    m = _MODELS_BY_ID.get(mid or "")
    return {"in": m["in"], "out": m["out"]} if m else AUX_MODEL_PRICES.get(mid or "")


def _usage_cost(mid: Optional[str], tin: int, tout: int) -> Optional[float]:
    """None — «цена неизвестна», а не ноль. Считать неизвестное нулём значит
    показать расход меньше настоящего — ровно то враньё, ради которого учёт
    и заводится. Такие вызовы считаются отдельно (unpriced).

    Скидка на кэшированный вход не применяется: её цены в каталоге нет,
    а выдумывать цену нельзя. Значит, цифра завышена ровно на неё — насколько,
    видно по cached_in рядом."""
    p = _model_price(mid)
    if not p:
        return None
    return tin / 1e6 * p["in"] + tout / 1e6 * p["out"]


def _usage_field(obj, name: str) -> int:
    """usage приходит объектом SDK, но в разных версиях бывает и словарём."""
    if obj is None:
        return 0
    v = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, 0)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _usage_part(obj, name: str):
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _usage_add(bucket: dict, step: str, mid: str, tin: int, cached: int,
               tout: int, think: int, cost: Optional[float]) -> None:
    for d in (bucket,
              bucket["steps"].setdefault(step or "?", _usage_leaf()),
              bucket["models"].setdefault(mid or "?", _usage_leaf())):
        d["calls"] += 1
        d["in"] += tin
        d["cached_in"] += cached
        d["out"] += tout
        d["reasoning"] += think
        if cost is None:
            d["unpriced"] += 1
        else:
            # Округление на каждом шаге, а не в конце: доли цента в сумме
            # из тысяч вызовов накапливают мусор в младших разрядах float,
            # и число перестаёт совпадать само с собой при пересчёте.
            d["cost"] = round(d["cost"] + cost, 6)


def _note_usage(step: str, model_id: str, resp) -> None:
    """Записать то, что посчитал провайдер, а не то, что мы предполагали."""
    try:
        u = getattr(resp, "usage", None) if not isinstance(resp, dict) else resp.get("usage")
        if u is None:
            return
        tin = _usage_field(u, "prompt_tokens")
        tout = _usage_field(u, "completion_tokens")
        cached = _usage_field(_usage_part(u, "prompt_tokens_details"), "cached_tokens")
        think = _usage_field(_usage_part(u, "completion_tokens_details"), "reasoning_tokens")
        if not (tin or tout):
            return
        cost = _usage_cost(model_id, tin, tout)
        with _USAGE_LOCK:
            for bucket in (_USAGE_TOTAL, _USAGE_SINK):
                if bucket is not None:
                    _usage_add(bucket, step, model_id, tin, cached, tout, think, cost)
    except Exception as e:
        print(f"[backend] учёт расхода не сработал ({step}/{model_id}): {e}", file=sys.stderr)


def _usage_begin(job: dict) -> None:
    global _USAGE_SINK
    with _USAGE_LOCK:
        _USAGE_SINK = job.setdefault("usage", _usage_zero())


def _usage_end(job: dict) -> None:
    """Закрыть счётчик прогона и оставить след, который переживёт рестарт.

    Сами прогоны живут в памяти процесса и теряются при рестарте — это давно
    так и осознанно. Но расход терять нельзя: смету калибруют по нему, а для
    этого нужны десятки прогонов, а не один. Запись компактная: цена по шагам,
    без списков сегментов."""
    global _USAGE_SINK
    with _USAGE_LOCK:
        _USAGE_SINK = None
        u = job.get("usage")
    if not u or not u.get("calls"):
        return
    try:
        rec = {"job": job.get("id"), "kind": job.get("kind"), "project": job.get("project"),
               "status": job.get("status"), "finished": job.get("finished"),
               "segments": job.get("done"),
               # Смету кладём рядом с фактом: врозь они не сравниваются, а
               # ради сравнения всё и затевалось. Прислал её тот, кто её
               # человеку и показал, — иначе рядом стояли бы два разных числа.
               "est": (job.get("params") or {}).get("est_cost"),
               "cost": u["cost"], "calls": u["calls"], "unpriced": u["unpriced"],
               "in": u["in"], "cached_in": u["cached_in"],
               "out": u["out"], "reasoning": u["reasoning"],
               "steps": {k: {"calls": v["calls"], "cost": v["cost"],
                             "in": v["in"], "out": v["out"], "reasoning": v["reasoning"]}
                         for k, v in u["steps"].items()}}
        hist = STATE.setdefault("runCosts", [])
        hist.append(rec)
        del hist[:-RUN_COST_HISTORY]
    except Exception as e:
        print(f"[backend] расход прогона не записан: {e}", file=sys.stderr)


# Direct OpenAI GPT translation
def _translate_system(src: str, tgt: str, gloss_hits: list, tm_context: dict,
                      literal: bool, domain, mdl: dict) -> str:
    """Системный промпт перевода. Вынесен отдельно, чтобы его можно было
    проверить тестом без обращения к модели: от того, каким уровнем уходит
    запись глоссария — приказом или подсказкой, — зависит, повторит ли модель
    чужую ошибку, а такое нельзя оставлять без проверки."""
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
        dom = _resolve_domain(domain)
        system = (
        f"You are a senior {dom['expert']}. "
        f"Translate the following text from {src} to {tgt}.\n\n"
        "STRICT RULES:\n"
        "1. Return ONLY the translated text — no explanations, no comments, no quotes.\n"
        f"2. Use {dom['terminology']}. NEVER transliterate source-language or Latin word forms,\n"
        f"   and never invent word-by-word calques that are not real terms in {tgt}.\n"
        + (f"   {dom['examples']}\n" if dom.get("examples") else "") +
        f"3. NEVER mix languages. Output must be 100% {tgt}.\n"
        "4. NEVER use parenthetical alternatives: NOT 'biologic(al)', NOT 'cell(s)'. Choose ONE correct form.\n"
        "5. NEVER list multiple synonyms separated by semicolons for the same concept.\n"
        "6. Preserve all numbers, abbreviations, and punctuation exactly as in the source.\n"
        f"7. Abbreviations that are identical in {tgt} may be kept as they are.\n"
        )
    hard = [h for h in (gloss_hits or []) if _hit_tier(h) == GLOSSARY_TIER_HARD]
    soft = [h for h in (gloss_hits or []) if _hit_tier(h) == GLOSSARY_TIER_SOFT]
    if hard:
        terms = "\n".join(f"  {h['src']} → {h['tgt']}" for h in hard)
        system += f"\nApproved glossary — use these exact translations:\n{terms}\n"
    if soft:
        # Автоимпорт — именно подсказка. Приказ "use these exact translations"
        # на этих записях и рождал "rear cyclitis": модель знает правильный
        # термин, но послушно берёт то, что ей назвали утверждённым.
        # Слово области — из проекта: «standard medical usage» в юридическом
        # промпте — та самая зашитая медицина, от которой сервис уходит.
        dom_word = _resolve_domain(domain)["en"]
        terms = "\n".join(f"  {h['src']} → {h['tgt']}" for h in soft)
        system += (
            "\nUnverified glossary hints (bulk-imported, NOT reviewed — some are wrong):\n"
            f"{terms}\n"
            "Use a hint ONLY if it is the standard term in the target language for this context. "
            f"If it is not standard {dom_word} usage, IGNORE the hint and use the correct standard term.\n"
        )
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
    return system


def _openai_translate(text: str, src: str, tgt: str,
                      gloss_hits: list = None, tm_context: dict = None,
                      model: str = None, literal: bool = False,
                      domain: Optional[str] = None, step: Optional[str] = None) -> str:
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
    system = _translate_system(src, tgt, gloss_hits, tm_context, literal, domain, mdl)
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
    # Шаг называет вызывающий: буквальный режим — это обратный перевод, но
    # заказывают его двое (back-check и Medical QA), и складывать их расход
    # в одну корзину значит потерять, кто из них сколько стоит.
    _note_usage(step or ("backcheck" if literal else "translate"), mdl["id"], resp)
    return (resp.choices[0].message.content or "").strip()

# ─────────────────────────────────────────────────────────────────────
# Аутентификация
#
# Пароль пока один на весь сервис (мультитенантности нет), но каждый вход
# выдаёт свой токен, и БЕЗ токена не работает ни один /api/* эндпоинт.
# Токены живут только в памяти процесса: рестарт = всем перелогиниться.
# ─────────────────────────────────────────────────────────────────────
_RAW_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
if not _RAW_PASSWORD:
    # Зашитого дефолта быть не должно: публичный сервис оказался бы открыт
    # каждому, кто читал репозиторий. Без пароля в env — одноразовый случайный.
    _RAW_PASSWORD = secrets.token_urlsafe(9)
    print(f"[backend] WARN: APP_PASSWORD не задан. Пароль на этот запуск: {_RAW_PASSWORD}",
          file=sys.stderr)
PASSWORD_HASH = hashlib.sha256(_RAW_PASSWORD.encode()).hexdigest()

SESSION_TTL = max(300, int(os.environ.get("SESSION_TTL_HOURS", "12")) * 3600)
LOGIN_MAX_FAILS = 10           # неудачных попыток с одного IP
LOGIN_FAIL_WINDOW = 15 * 60    # за это окно; потом счётчик обнуляется

_SESSIONS: dict = {}           # token -> expires_at (epoch)
_LOGIN_FAILS: dict = {}        # ip -> (fail_count, window_started_at)
_AUTH_LOCK = threading.Lock()

# Единственный список исключений. Всё прочее под /api/ требует токен.
PUBLIC_API_PATHS = {"/api/auth/login", "/api/auth/logout", "/api/health"}


def _new_session() -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _AUTH_LOCK:
        for dead in [t for t, exp in _SESSIONS.items() if exp <= now]:
            _SESSIONS.pop(dead, None)
        _SESSIONS[token] = now + SESSION_TTL
    return token


def _session_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    with _AUTH_LOCK:
        exp = _SESSIONS.get(token)
        if exp is None:
            return False
        if exp <= time.time():
            _SESSIONS.pop(token, None)
            return False
    return True


def _drop_session(token: Optional[str]) -> None:
    if token:
        with _AUTH_LOCK:
            _SESSIONS.pop(token, None)


def _client_ip(request: Request) -> str:
    # За nginx реальный адрес приходит в X-Forwarded-For (см. deploy/nginx.conf).
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _login_blocked(ip: str) -> bool:
    with _AUTH_LOCK:
        rec = _LOGIN_FAILS.get(ip)
        if not rec:
            return False
        count, started = rec
        if time.time() - started > LOGIN_FAIL_WINDOW:
            _LOGIN_FAILS.pop(ip, None)
            return False
        return count >= LOGIN_MAX_FAILS


def _note_login_fail(ip: str) -> None:
    now = time.time()
    with _AUTH_LOCK:
        count, started = _LOGIN_FAILS.get(ip, (0, now))
        if now - started > LOGIN_FAIL_WINDOW:
            count, started = 0, now
        _LOGIN_FAILS[ip] = (count + 1, started)


def _token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    header = request.headers.get("x-auth-token", "").strip()
    if header:
        return header
    # Скачивание файла идёт обычной ссылкой <a href>, заголовок туда не подставить,
    # поэтому только для этого одного пути токен допускается в query-строке.
    if request.url.path.endswith("/export/download"):
        return request.query_params.get("token")
    return None


# ─────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="Medical CAT Translator API", version="5.6.0")


@app.middleware("http")
async def require_token(request: Request, call_next):
    """Одна точка проверки: новый /api/* эндпоинт защищён автоматически."""
    path = request.url.path
    if (request.method != "OPTIONS"              # preflight обслуживает CORSMiddleware
            and path.startswith("/api/")
            and path not in PUBLIC_API_PATHS
            and not _session_valid(_token_from_request(request))):
        return JSONResponse({"ok": False, "error": "Требуется вход в систему"}, status_code=401)
    return await call_next(request)


# CORS добавляется ПОСЛЕ require_token: последняя добавленная мидлварь —
# внешняя, поэтому preflight и ответы 401 тоже получают CORS-заголовки.
# Список origin'ов вместо прежнего "*": со звёздочкой и allow_credentials
# любой сторонний сайт мог дёргать API из браузера пользователя.
_DEFAULT_ORIGINS = [
    "https://trasnlateuz.duckdns.org",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", ",".join(_DEFAULT_ORIGINS)).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Auth-Token"],
)

FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = ROOT / "backend" / "data"
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"

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
                origin = (row.get("Sources") or "").strip()
                terms.append({
                    "src": ru, "tgt": en,
                    "cat": _CAT_MAP.get(cat_raw, "Disease"),
                    "freq": 1, "conf": "high", "note": "",
                    # tier решает, приказ это для модели или подсказка (см. _tier_from_origin)
                    "tier": _tier_from_origin(origin), "origin": origin[:60],
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
    # Migrate: уровни доверия появились позже самого глоссария. Проставляем их
    # по эталонному TSV; чего в массовом импорте нет — добавлено руками, значит
    # проверено. Иначе весь автоимпорт так и остался бы приказом для модели.
    if any("tier" not in t for t in state.get("glossary", [])):
        tiers = {t["src"]: t.get("tier", GLOSSARY_TIER_HARD) for t in SEED_GLOSSARY}
        for t in state.get("glossary", []):
            if "tier" not in t:
                t["tier"] = tiers.get(t.get("src"), GLOSSARY_TIER_HARD)
    # Migrate: Medical QA раньше писала свою оценку в seg["risk"], где живёт
    # длина сегмента — а по ней выбирается движок перевода. Возвращаем длину
    # тем же расчётом, что при импорте: миграция идемпотентна и полей не
    # добавляет. Трогаем только сегменты, где проверка действительно была
    # (есть risk_color) или где остался её след — «critical» больше никто
    # не ставит.
    for _p in state.get("projects", []):
        for _s in _p.get("segments", []):
            if _s.get("risk_color") or _s.get("risk") == "critical":
                _w = len((_s.get("source") or "").split())
                _s["risk"] = "high" if _w > 30 else "medium" if _w > 8 else "low"
    state.setdefault("termQueue", [])
    # Migrate: до появления origTgt одобрение конфликта затирало пустой перевод
    # решением человека, и дедупликация теряла кандидата — термин возвращался
    # в очередь неодобренным. Конфликт всегда рождается с пустым tgt, поэтому
    # прежнюю пару восстанавливаем точно. Правленые пары других видов не
    # угадываем: там текущий tgt и есть исходный, если человек его не менял.
    for c in state["termQueue"]:
        if (c.get("kind") == "conflict" and c.get("status") == "approved"
                and c.get("tgt") and "origTgt" not in c):
            c["origTgt"] = ""
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
        "termQueue": [],
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
def login(req: LoginRequest, request: Request):
    ip = _client_ip(request)
    if _login_blocked(ip):
        raise HTTPException(429, "Слишком много попыток входа. Повторите через 15 минут.")
    given = hashlib.sha256(req.password.encode()).hexdigest()
    if not hmac.compare_digest(given, PASSWORD_HASH):
        _note_login_fail(ip)
        raise HTTPException(401, "Invalid password")
    return {"ok": True, "token": _new_session(), "expiresIn": SESSION_TTL}


@app.post("/api/auth/logout")
def logout(request: Request):
    _drop_session(_token_from_request(request))
    return {"ok": True}


@app.get("/api/seed")
def get_seed():
    """Initial data dump — glossary capped at 150 terms for performance; full list via /api/glossary."""
    return {**STATE, "projects": [_project_for_client(p) for p in STATE["projects"]],
            "glossary": STATE["glossary"][:150]}


@app.get("/api/glossary")
def list_glossary(q: str = "", cat: str = "", limit: int = 200, offset: int = 0,
                  lang: str = "", domain: str = ""):
    """Full glossary with optional search and pagination.
    lang/domain сужают выдачу до области проекта — той самой, что уходит
    в промпт. Без них отдаём всё: вкладка «Глоссарий» листает общий список."""
    items = STATE["glossary"]
    if lang or domain:
        items = [t for t in items
                 if (not lang or _scope_of(t)[0] == lang)
                 and (not domain or _scope_of(t)[1] == domain)]
    if cat and cat != "all":
        items = [t for t in items if t.get("cat") == cat]
    if q:
        ql = q.lower()
        items = [t for t in items if ql in t.get("src", "").lower() or ql in t.get("tgt", "").lower()]
    total = len(items)
    return {"total": total, "items": items[offset:offset + limit]}


@app.get("/api/glossary/usage")
def glossary_usage(src: str, limit: int = 6, lang: str = "", domain: str = ""):
    """Где термин реально встречается. Совпадение ищем тем же _term_match, что и
    инъекция в промпт: иначе список «затронутых сегментов» разошёлся бы с тем,
    на что глоссарий действительно влияет.

    В `violating` — сегменты, где термин есть в оригинале, перевод уже готов,
    а утверждённого варианта в нём нет. Именно их имеет смысл переперевести."""
    # Без области сюда попадала запись чужой языковой пары, и тогда «нарушением
    # глоссария» помечался каждый сегмент: искомого перевода там и не могло быть.
    # Пустые lang/domain читаем как область по умолчанию — так же, как их читает
    # _scope_of; запасной поиск по имени срабатывает, только если запись одна.
    want = (lang or DEFAULT_GLOSS_LANG, domain or DEFAULT_GLOSS_DOMAIN)
    entry = _glossary_entry(src, want)
    if entry is None and not (lang or domain):
        same = [g for g in STATE["glossary"] if _norm_key(g.get("src")) == _norm_key(src)]
        entry = same[0] if len(same) == 1 else None
        if entry is not None:
            want = _scope_of(entry)
    tgt = (entry or {}).get("tgt", "")
    projects, examples = [], []
    for p in STATE["projects"]:
        # Проект чужой области этой записью не управляется: помечать его
        # сегменты нарушением глоссария — то же враньё, только на уровне отчёта.
        if entry is not None and _project_scope(p) != want:
            continue
        ids, violating = [], []
        for seg in p["segments"]:
            if not _term_match(src, seg.get("source", "")):
                continue
            ids.append(seg["id"])
            target = (seg.get("target") or "").strip()
            if target and tgt and not _tgt_has_term(target, tgt):
                violating.append(seg["id"])
            if len(examples) < max(1, min(limit, 20)):
                examples.append({"project": p["id"], "projectTitle": p.get("title", ""),
                                 "id": seg["id"], "source": seg.get("source", "")[:400],
                                 "target": target[:400], "status": seg.get("status")})
        if ids:
            projects.append({"id": p["id"], "title": p.get("title", ""), "segments": ids,
                             "violating": violating})
    return {"ok": True, "term": src, "tgt": tgt, "prevTgt": (entry or {}).get("prevTgt", ""),
            "total": sum(len(x["segments"]) for x in projects),
            "violatingTotal": sum(len(x["violating"]) for x in projects),
            "projects": projects, "examples": examples}


_IMPACT_CACHE: dict = {}          # pid -> (отпечаток, отчёт)
_GLOSS_EPOCH = [0]                # растёт на каждой правке глоссария


def _impact_fingerprint(project: dict) -> str:
    """Отпечаток входных данных отчёта: переводы сегментов + поколение глоссария.

    Считаем по содержимому, а не по «версии состояния»: любой будущий код,
    поменявший перевод в обход save_state, иначе получал бы устаревший отчёт,
    а тихо устаревшая цифра «сколько переперевести» хуже её отсутствия."""
    parts = [str(s.get("id")) + "|" + (s.get("status") or "") + "|" + (s.get("target") or "")
             for s in project["segments"]]
    body = chr(10).join(parts)
    return str(_GLOSS_EPOCH[0]) + ":" + hashlib.sha1(body.encode("utf-8")).hexdigest()


class SegmentsFetchRequest(BaseModel):
    ids: List[int]


@app.post("/api/projects/{pid}/segments/fetch")
def fetch_segments(pid: int, req: SegmentsFetchRequest):
    """Отдать конкретные сегменты. Во время прогона клиенту нужны только те,
    что изменились: полный проект на 2670 сегментов весит 5 МБ, и тянуть его
    каждые несколько секунд — это мегабайты трафика и подвисающая таблица."""
    project = get_project(pid)
    wanted = set(req.ids[:1000])
    return {"ok": True, "segments": [_segment_for_client(s) for s in list(project["segments"])
                                     if s.get("id") in wanted]}


@app.get("/api/projects/{pid}/glossary-impact")
def glossary_impact(pid: int, refresh: bool = False):
    """Сегменты проекта, чей перевод не соответствует ПРОВЕРЕННЫМ записям глоссария.

    После одобрения термина старые переводы сами не меняются — это и есть список
    «что переперевести». Считаем только по verified: автоимпорт модель вправе
    игнорировать, требовать соответствия ему нельзя."""
    project = get_project(pid)
    # Полный проход по проекту — секунды на тысячах сегментов. Пока состояние
    # не менялось, отдаём посчитанное: клиент дёргает отчёт при каждом открытии
    # редактора и после каждого прогона.
    fp = _impact_fingerprint(project)
    cached = _IMPACT_CACHE.get(pid)
    if cached and cached[0] == fp and not refresh:
        return cached[1]
    by_term: dict = {}
    seg_ids, confirmed_ids = set(), set()
    for seg in project["segments"]:
        target = (seg.get("target") or "").strip()
        if not target:
            continue
        hits, _tm = _get_context(seg.get("source", ""), with_tm=False, project=project)
        for h in hits:
            if _hit_tier(h) != GLOSSARY_TIER_HARD or not h.get("tgt"):
                continue
            if _tgt_has_term(target, h["tgt"]):
                continue
            key = h["src"]
            e = by_term.setdefault(key, {"src": key, "tgt": h["tgt"], "cat": h.get("cat", ""),
                                         "updated": h.get("updated", ""), "prevTgt": h.get("prevTgt", ""),
                                         "segments": [], "confirmed": []})
            e["segments"].append(seg["id"])
            seg_ids.add(seg["id"])
            if seg.get("status") == "confirmed":
                e["confirmed"].append(seg["id"])
                confirmed_ids.add(seg["id"])
    terms = sorted(by_term.values(), key=lambda t: len(t["segments"]), reverse=True)
    result = {"ok": True, "terms": terms,
              "segments": sorted(seg_ids), "confirmed": sorted(confirmed_ids),
              "pending": sorted(seg_ids - confirmed_ids)}
    _IMPACT_CACHE[pid] = (fp, result)
    return result


_ANALYSIS_CACHE: dict = {}


@app.get("/api/projects/{pid}/analysis")
def project_analysis(pid: int, refresh: bool = False):
    """Итог работы по проекту одним экраном: что чисто, что исправила машина,
    что она предлагает одобрить и что осталось человеку.

    Считается по состоянию, а не по последнему прогону: прогонов может быть
    несколько, страницу могли перезагрузить, а вопрос у пользователя один —
    «что сейчас с проектом». Ни одного вызова модели здесь нет — но проход
    по проекту не бесплатен: на 2670 сегментах это секунды CPU единственного
    воркера, а экран открывают часто. Поэтому результат кэшируется по
    отпечатку тех же данных, из которых считается."""
    project = get_project(pid)
    q = _term_queue()
    # Отпечаток обязан включать сами проверки: отчёт о глоссарии считается по
    # тексту, а этот экран — ещё и по backcheck/termcheck/repair. Прогон
    # back-check не меняет ни статус, ни перевод, и на отпечатке импакта
    # экран навсегда показывал бы доперегонные цифры.
    # Не только хеши текста, но и САМИ оценки: повторный back-check по тому же
    # тексту другой моделью даёт тот же target_hash и другой балл, и по одним
    # хешам экран показал бы доперегонные цифры.
    checks = "".join(
        "%s:%s|%s:%s|%s:%s;" % (
            (s.get("backcheck") or {}).get("target_hash", ""),
            (s.get("backcheck") or {}).get("score", ""),
            (s.get("termcheck") or {}).get("target_hash", ""),
            len((s.get("termcheck") or {}).get("findings") or ()),
            (s.get("repair") or {}).get("source_hash", ""),
            (s.get("repair") or {}).get("applied", ""))
        for s in project["segments"])
    fp = (_impact_fingerprint(project) + "|" + str(len(q)) + "|"
          + str(sum(1 for c in q if c.get("status", "pending") == "pending"))
          + "|" + hashlib.sha1(checks.encode("utf-8")).hexdigest())
    cached = _ANALYSIS_CACHE.get(pid)
    if cached and cached[0] == fp and not refresh:
        return cached[1]
    pol = _auto_policy(project.get("domain"))
    scope = _project_scope(project)
    impact = glossary_impact(pid)

    clean, repaired, reverted, untranslated, unchecked = [], [], [], [], []
    findings, weak = [], []
    # Подтверждённые с находками — своя корзина. Раньше они растворялись
    # в «оценка ниже порога» вперемешку с машинными сегментами, и по экрану
    # нельзя было понять, что это ручные подтверждения, до которых ни один
    # прогон не дотянется без явного разрешения.
    confirmed_findings: list = []
    conf_set: set = set()
    # Расхождения с глоссарием берём из отчёта, а не считаем заново: там тот же
    # расчёт на весь проект и он кэширован. Вызов _repair_findings с project
    # гонял бы _get_context на каждый сегмент — 10 секунд CPU единственного
    # воркера на 2670 сегментах, и это при каждом открытии экрана.
    gloss_bad = set(impact["segments"])
    for s in project["segments"]:
        target = (s.get("target") or "").strip()
        if not target:
            untranslated.append(s["id"])
            continue
        rp = s.get("repair") or {}
        open_findings = _repair_findings(s) or (
            [{"kind": "gloss"}] if s["id"] in gloss_bad else [])
        if rp.get("applied") and _repair_tried(s):
            repaired.append(s["id"])
        elif (rp and not rp.get("applied") and open_findings
                and _repair_tried(s)):
            # Модель пробовала починить и не смогла — дальше только человек.
            # _repair_tried обязателен: запись о неудачной правке могла остаться
            # от прежнего текста, а к нынешнему уже не относится.
            reverted.append(s["id"])
        # Только неподтверждённые: подтверждённые с находками пакетный ремонт
        # без явного разрешения не трогает, и обещать «это починится само»
        # было бы неправдой. Они уходят в свою корзину — не потому, что с ними
        # нечего делать, а потому, что решение принимает человек.
        if open_findings and s.get("status") != "confirmed":
            findings.append(s["id"])
        elif open_findings:
            confirmed_findings.append(s["id"])
            conf_set.add(s["id"])
        # Корзины обязаны быть исчерпывающими: сегмент, не попавший ни в одну,
        # исчезает с экрана, и картина выглядит благополучнее, чем есть.
        why = _machine_clean(s, pol["backcheck_min"])
        if why is None:
            clean.append(s["id"])
        elif "не делался" in why or "пропущен" in why:
            unchecked.append(s["id"])
        elif s["id"] not in findings and s["id"] not in conf_set:
            weak.append({"id": s["id"], "why": why})

    # Что автоодобрение разложило бы прямо сейчас — тем же движком, что и кнопка,
    # иначе цифра на экране разошлась бы с тем, что произойдёт по нажатию.
    pending = [c for c in _term_queue() if c.get("status", "pending") == "pending"
               and _scope_of(c) == scope]
    ctx = _auto_context(pending, pol)
    ready, need_human = 0, {}
    for cand in pending:
        action, reason = _auto_verdict(cand, ctx)
        if action in (GLOSSARY_TIER_HARD, GLOSSARY_TIER_SOFT):
            ready += 1
        elif action != "close":
            need_human[reason] = need_human.get(reason, 0) + 1

    result = {
        "ok": True,
        "total": len(project["segments"]),
        "clean": clean,
        "repaired": repaired,
        "machine": {"repaired": len(repaired), "reverted": len(reverted)},
        "proposed": {"terms": ready},
        "human": {
            "terms": sorted(({"reason": k, "count": v} for k, v in need_human.items()),
                            key=lambda x: -x["count"]),
            "termsTotal": sum(need_human.values()),
            "reverted": reverted,
            "glossaryConfirmed": impact["confirmed"],
            "confirmedFindings": confirmed_findings,
        },
        "todo": {"untranslated": untranslated, "unchecked": unchecked,
                 "findings": findings, "glossaryPending": impact["pending"],
                 "weak": [w["id"] for w in weak],
                 "weakWhy": sorted(
                     ({"reason": r, "count": sum(1 for w in weak if w["why"] == r)}
                      for r in {w["why"] for w in weak}),
                     key=lambda x: -x["count"])},
    }
    _ANALYSIS_CACHE[pid] = (fp, result)
    return result


@app.get("/api/models")
def list_models():
    """Каталог GPT-моделей с ценами — для выпадающего списка и оценки стоимости пакета.
    Полосы back-check отдаются отсюда же, чтобы границы не дублировались на фронтенде."""
    return {
        # Ранг приклеивается здесь, а не хранится в OPENAI_MODELS: он живёт
        # в отдельном справочнике, который правят без деплоя (см. model_rank).
        "models": [dict(m, rank=model_rank(m["id"])) for m in OPENAI_MODELS],
        # Модели, которых нет в списке выбора, но которые стоят денег
        # (эмбеддинги back-check). Смета обязана брать их цену отсюда:
        # цифра в .jsx — это второй прайс-лист рядом с настоящим.
        "aux": AUX_MODEL_PRICES,
        "embedModel": EMBED_MODEL,
        "domains": [{"id": d["id"], "label": d["label"]} for d in DOMAINS],
        "domainDefault": DEFAULT_DOMAIN,
        "default": DEFAULT_OPENAI_MODEL,
        "backcheckDefault": BACKCHECK_DEFAULT_MODEL,
        "termcheckDefault": TERMCHECK_DEFAULT_MODEL,
        "repairDefault": REPAIR_DEFAULT_MODEL,
        "judgeDefault": JUDGE_DEFAULT_MODEL,
        "judgeZone": list(JUDGE_ZONE),
        "backcheckBands": getattr(medical_qa_mod, "BACKCHECK_BANDS", []) if medical_qa_mod else [],
        "available": bool(os.environ.get("OPENAI_API_KEY")),
        "pricesChecked": "2026-08-15",
    }


@app.get("/api/projects")
def list_projects():
    return [{k: v for k, v in p.items() if k != "segments"} | {"segmentCount": len(p["segments"])} for p in STATE["projects"]]


@app.get("/api/projects/{pid}")
def get_project_detail(pid: int):
    return _project_for_client(get_project(pid))


class CreateProjectRequest(BaseModel):
    title: str
    src: str = "RU"
    tgt: str = "EN"
    domain: str = DEFAULT_DOMAIN
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
        "domain": _resolve_domain(req.domain)["id"],
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
    domain: str = Form(DEFAULT_DOMAIN),
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
        "domain": _resolve_domain(domain)["id"],
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
    # engine больше нет: движок один — выбранная модель. Поле осталось бы
    # враньём про выбор, которого не существует.
    force: bool = False  # True = пропустить TM-шорткат (ручной перевод)
    model: Optional[str] = None  # id из OPENAI_MODELS; неизвестный → DEFAULT_OPENAI_MODEL

@app.post("/api/segments/{pid}/{sid}/translate")
def translate_segment(pid: int, sid: int, req: TranslateRequest):
    # обычный def, а не async: внутри блокирующий вызов модели (см. batch_translate)
    seg = get_segment(pid, sid)
    project = get_project(pid)
    src_text = seg["source"]

    # Глоссарий + TM контекст
    gloss_hits, tm_hit = _get_context(src_text, project=project)

    # TM точное совпадение → 0 токенов (только для авто/пакетного, не для ручного force-перевода)
    # и только для записей, которые завёл человек: см. _tm_trusted.
    if not req.force and _tm_trusted(tm_hit) and tm_hit.get("tgt"):
        # НЕ confirmed: одно подтверждение человека на одной строке не заверяет
        # все будущие строки с тем же исходником. Сегмент проходит проверки,
        # как всякий машинный перевод, и подтверждает его снова человек.
        _replace_target(seg, tm_hit["tgt"], PROVIDER_TM, "EXACT_TM")
        save_state(STATE)
        return {"ok": True, "segment": seg, "usedRealApi": False, "source": "TM"}

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Перевод требует ключ OpenAI: бесплатного движка "
                                 "в системе больше нет")
    try:
        translation = _openai_translate(src_text, project["src"], project["tgt"],
                                        gloss_hits=gloss_hits, tm_context=tm_hit,
                                        model=req.model, domain=project.get("domain"))
    except Exception as e:
        print(f"[backend] translate failed seg#{sid}: {e}", file=sys.stderr)
        translation = None
    if not translation:
        # Ни заглушек, ни «черновика бесплатным движком»: в медицинском переводе
        # подсунуть вместо ответа что попало хуже, чем не ответить. Сегмент
        # не трогаем, ошибку называем.
        raise HTTPException(502, "Модель не вернула перевод. Попробуйте ещё раз "
                                 "или выберите другую модель.")

    _replace_target(seg, translation, _resolve_model(req.model)["id"], "GPT_REQUIRED")
    save_state(STATE)
    return {"ok": True, "segment": seg, "usedRealApi": True}


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



# ─── Что система выучивает из подтверждённого сегмента ───────────────
# Подтверждение — единственная точка, где появляется достоверная пара
# «оригинал → перевод». Из неё берём три вещи: обновляем TM, складываем
# терминологические находки в очередь кандидатов и находим повторы того же
# исходника. В сам глоссарий автоматически не попадает НИЧЕГО: он инжектится
# в промпт как правило, и автопополнение закрепляло бы собственные ошибки.
TERM_QUEUE_MAX = 800


def _norm_key(text: str) -> str:
    return " ".join((text or "").lower().replace("ё", "е").split())


def _tm_upsert(source: str, target: str, project: dict = None) -> str:
    """Пара в TM: обновить существующую запись, а не пропустить её.
    Раньше дедуп находил старую пару и молча оставлял как есть — исправленный
    перевод в память не попадал, а прежний, неверный, продолжал автоматически
    подставляться в новые проекты как EXACT_TM."""
    key = _norm_key(source)
    today = datetime.now().strftime("%Y-%m-%d")
    lang = f"{(project or {}).get('src', 'RU')}→{(project or {}).get('tgt', 'EN')}"
    for t in STATE["tm"]:
        if _norm_key(t.get("src")) != key:
            continue
        # Пара языков — часть ключа. Без неё подтверждение RU→DE переписывало
        # tgt у RU→EN записи, оставляя ей прежний lang: следующий RU→EN проект
        # получал немецкий текст как EXACT_TM, да ещё со статусом confirmed.
        if (t.get("lang") or DEFAULT_GLOSS_LANG) != lang:
            continue
        if (t.get("tgt") or "").strip() == (target or "").strip():
            return "kept"
        t["prevTgt"] = t.get("tgt", "")
        t["tgt"] = target
        t["quality"] = "verified"
        t["score"] = 100
        t["updated"] = today
        return "updated"
    STATE["tm"].insert(0, {
        "src": source, "tgt": target, "lang": lang,
        "score": 100, "quality": "verified", "used": 1, "created": today,
    })
    return "added"


def _term_queue() -> list:
    return STATE.setdefault("termQueue", [])


def _trim_term_queue():
    """Очередь не должна расти бесконечно: state.json целиком лежит в памяти
    и переписывается при каждом сохранении."""
    q = _term_queue()
    if len(q) <= TERM_QUEUE_MAX:
        return
    # Сначала обработанные: своё они уже отыграли. Кроме тех, что принадлежат
    # ещё откатываемой пачке: без кандидата откат вернёт глоссарий, но потеряет
    # само решение, и человек его больше не увидит.
    live = {b.get("id") for b in STATE.get("autoBatches", [])}
    done = [c for c in q if c.get("status") != "pending" and c.get("autoBatch") not in live]
    # Решения человека снимаем последними: решённый кандидат — это память
    # «про этот термин уже спрашивали». Выбросив её, сбор терминологии заведёт
    # кандидата заново, и одобренный термин вернётся в очередь неодобренным.
    # Решения человека сортируем по ДАТЕ РЕШЕНИЯ, а не по месту в очереди:
    # порядок в очереди — это порядок появления кандидатов, и старый кандидат,
    # одобренный сегодня, лежит в самом низу. По позиции его выбросило бы
    # первым — то есть терялась бы память именно о свежих решениях.
    humans = [c for c in done if _human_decision(c)]
    machines = [c for c in done if not _human_decision(c)]
    humans.sort(key=lambda c: c.get("decidedAt") or "", reverse=True)
    for c in (humans + machines)[TERM_QUEUE_MAX // 4:]:
        q.remove(c)
    if len(q) <= TERM_QUEUE_MAX:
        return
    # Дальше — машинный урожай. На документе в 2670 сегментов коротких пар
    # тысячи, а pending раньше не подрезался вовсе. Решения, которые может
    # принять только человек (conflict и всё, что пришло с подтверждённых
    # сегментов), не трогаем никогда — их больше никто не примет.
    droppable = [c for c in q if c.get("status", "pending") == "pending"
                 and c.get("via") == "auto" and c.get("kind") != "conflict"]
    # Сортируем по возрасту, а не по числу доноров. Кандидат с одним донором —
    # это ровно тот, кто ждёт второго: выбрасывая их первыми, мы бы вычищали
    # именно ту популяцию, ради которой существует порог auto_min_segments.
    # Одиночки уходят раньше многодонорных, но внутри группы — самые старые:
    # у них было больше всего шансов набрать доноров и они их не набрали.
    droppable.sort(key=lambda c: (1 if c.get("hits", 1) >= 2 else 0, c.get("id", 0)))
    over = len(q) - TERM_QUEUE_MAX
    for c in droppable[:over]:
        q.remove(c)
    if over > 0:
        # Молчаливых потолков не бывает: подрезали — сказали, сколько и чего.
        print(f"[backend] очередь кандидатов подрезана: снято {min(over, len(droppable))} "
              f"машинных кандидатов (потолок {TERM_QUEUE_MAX})", file=sys.stderr)


_TERM_QUEUE_LOCK = threading.Lock()


def _queue_term(kind: str, src: str, tgt: str, **extra) -> Optional[dict]:
    """Кандидат в глоссарий. Повтор той же пары не плодит запись, а поднимает
    hits: по нему видно, какая проблема встречается чаще всего. Отклонённое
    второй раз не всплывает.

    Под локом: сегменты порции считаются параллельно, а очередь одна — без него
    два потока могли бы завести две записи об одном и том же."""
    src_n, tgt_n = _norm_key(src), _norm_key(tgt)
    if not src_n:
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _TERM_QUEUE_LOCK:
        return _queue_term_locked(kind, src, tgt, src_n, tgt_n, now, extra)


def _cand_pair(c: dict) -> tuple:
    """Пара, с которой кандидат ПОЯВИЛСЯ, — по ней и идёт дедупликация.
    Одобрение вписывает в src/tgt решение человека (у конфликта перевод вообще
    рождается пустым и заполняется только им), и без этой памяти следующий сбор
    терминологии не узнавал бы решённого кандидата: одобренный термин
    возвращался в очередь новым, будто его никто не подтверждал."""
    return (_norm_key(c["origSrc"] if "origSrc" in c else c.get("src")),
            _norm_key(c["origTgt"] if "origTgt" in c else c.get("tgt")))


def _queue_term_locked(kind, src, tgt, src_n, tgt_n, now, extra):
    # Область входит в ключ дедупликации: «договор → contract» в RU→EN и
    # «договор → Vertrag» в RU→DE — разные кандидаты, а не спор двух вариантов.
    scope = _scope_of(extra)
    donor = (f"{extra.get('project')}:{extra['segment']}"
             if extra.get("segment") and extra.get("project") else None)
    for c in _term_queue():
        if (c.get("kind") == kind and _cand_pair(c) == (src_n, tgt_n)
                and _scope_of(c) == scope):
            c["hits"] = c.get("hits", 1) + 1
            c["at"] = now
            # Список сегментов-доноров, а не только счётчик: автоодобрение
            # считает согласие НЕЗАВИСИМЫХ сегментов, а hits растёт и от
            # повторного подтверждения одного и того же — так одна строка
            # накрутила бы себе доказательства.
            segs = c.setdefault("segments", _donor_ids(c))
            if donor and donor not in segs:
                segs.append(donor)
            if extra.get("via") == "confirmed":
                c["via"] = "confirmed"      # подтверждение человеком не понижается
            return c if c.get("status") == "pending" else None
    cand = {"id": max((c.get("id", 0) for c in _term_queue()), default=0) + 1,
            "kind": kind, "src": (src or "").strip(), "tgt": (tgt or "").strip(),
            "status": "pending", "hits": 1, "at": now,
            "segments": [donor] if donor else []}
    cand.update(extra)
    return _queue_insert(cand)


def _queue_insert(cand: dict) -> dict:
    _term_queue().insert(0, cand)
    _trim_term_queue()
    return cand


def _tgt_has_term(target: str, term: str) -> bool:
    """Есть ли глоссарный перевод в готовом переводе. Терпимо к числу и
    артиклям: сверяем по началам слов, иначе «lymph nodes» не найдёт
    «lymph node» и очередь захлебнётся ложными конфликтами."""
    tn, mn = _norm_key(target), _norm_key(term)
    if not mn:
        return True
    if mn in tn:
        return True
    words = [w for w in mn.split() if len(w) > 3]
    if not words:
        return False
    tgt_words = tn.replace("(", " ").replace(")", " ").replace(",", " ").split()
    return all(any(x.startswith(w[:max(4, len(w) - 2)]) for x in tgt_words) for w in words)


def _gloss_by_src() -> dict:
    """(область, нормализованный термин) → запись. Отдельный индекс от
    _gloss_index: тот ищет вхождения в тексте, этот — точную запись по термину.
    Без него каждый короткий чистый сегмент внутри параллельного прогона гнал
    линейный проход по 10 000 записей."""
    global _GLOSS_BY_SRC
    idx = _GLOSS_BY_SRC
    if idx is not None:
        return idx
    with _GLOSS_INDEX_LOCK:
        if _GLOSS_BY_SRC is None:
            built: dict = {}
            for g in STATE.get("glossary", []):
                built.setdefault((_scope_of(g), _norm_key(g.get("src"))), g)
            _GLOSS_BY_SRC = built
        # Возвращаем локальную ссылку: параллельный _invalidate_gloss_index()
        # обнуляет глобал, и вызывающий получил бы None вместо словаря.
        return _GLOSS_BY_SRC


def _glossary_entry(src: str, scope: tuple) -> Optional[dict]:
    """Запись глоссария по термину В ПРЕДЕЛАХ области. Раньше поиск шёл по
    всему списку, и запись из чужой языковой пары выглядела как «уже есть»."""
    return _gloss_by_src().get((scope, _norm_key(src)))


def _harvest_terms(seg: dict, project: dict, via: str = "confirmed") -> list:
    """Терминологические находки сегмента:

    conflict — глоссарий предлагал перевод, а в тексте его нет. Значит либо
               запись глоссария врёт (наш случай «задний → rear»), либо
               переводчик отступил осознанно. Решает человек.
    segment  — короткий сегмент без финальной точки сам по себе является
               терминологической парой.

    via="confirmed" — сегмент подтвердил человек, это сильнейшее доказательство.
    via="auto"      — сегмент прошёл back-check и termcheck чисто. Отсюда берём
                      ТОЛЬКО готовые пары: расхождения с глоссарием всё равно
                      идут человеку, а на большом проекте их сотни, и очередь
                      (её pending никогда не подрезается) распухла бы зря.
    """
    out = []
    source = seg.get("source", "")
    target = (seg.get("target") or "").strip()
    if not target:
        return out
    scope = _project_scope(project)
    meta = {"project": project["id"], "segment": seg["id"],
            "lang": scope[0], "domain": scope[1], "via": via}
    if via == "confirmed":
        hits, _tm = _get_context(source, project=project)
        for h in hits:
            if _tgt_has_term(target, h["tgt"]):
                continue
            c = _queue_term("conflict", h["src"], "",
                            wasTgt=h["tgt"], tier=_hit_tier(h), cat=h.get("cat", ""),
                            sampleSrc=source[:240], sampleTgt=target[:240], **meta)
            if c:
                out.append(c)
    words = source.strip().split()
    if 1 <= len(words) <= 4 and not source.strip().endswith((".", "!", "?", ":")) \
            and len(target.split()) <= 8:
        term_src = source.strip().strip(" .,;:")
        term_tgt = target.strip().strip(" .,;:")
        # Числа и обозначения («38,5 °C», «IFN-γ») терминами не бывают: пара
        # без букв — это не словарная запись, а строка документа.
        if re.search(r"[A-Za-zА-Яа-яЁё]{3}", term_src) and re.search(r"[A-Za-zА-Яа-яЁё]{3}", term_tgt):
            known = _glossary_entry(term_src, scope)
            if not (known and _norm_key(known.get("tgt")) == _norm_key(term_tgt)):
                c = _queue_term("segment", term_src, term_tgt,
                                cat=(known or {}).get("cat", ""),
                                wasTgt=(known or {}).get("tgt", ""), **meta)
                if c:
                    out.append(c)
    return out


def _check_stale(check: Optional[dict], target: str) -> bool:
    """Та же производная, что уходит клиенту в _segment_for_client: проверка
    относится к другому тексту, значит её результат уже ничего не значит.

    Хеш ОБРЕЗАННОГО текста — ровно так его и записывают back-check, termcheck
    и Medical QA. Сравнивая с необрезанным, мы объявляли бы устаревшей свежую
    проверку любого перевода с висящим пробелом, и прогон платил бы за неё
    заново."""
    return (check or {}).get("target_hash") != _text_hash((target or "").strip())


def _machine_clean(seg: dict, min_score: int) -> Optional[str]:
    """None, если с сегмента можно собирать терминологию без человека.
    Иначе — причина отказа (её показываем в разборе автоодобрения).

    Смысл проверки: перевод оценивал не тот прогон, который его делал, и не
    та модель. Обратный перевод идёт в другую сторону, termcheck смотрит
    только на целевой текст. Совпали оба — пара заслуживает доверия.
    """
    target = (seg.get("target") or "").strip()
    if not target:
        return "нет перевода"
    bc, tc = seg.get("backcheck"), seg.get("termcheck")
    if not bc or _check_stale(bc, target):
        return "back-check не делался или устарел"
    if bc.get("score") is None or bc["score"] < min_score:
        return f"back-check ниже {min_score}%"
    if not tc or _check_stale(tc, target):
        return "termcheck не делался или устарел"
    if tc.get("model") == "skip":
        # «Нечего проверять» — это не «проверено и чисто». Иначе сегмент, где
        # перевод совпал с оригиналом, дарил глоссарию пару вида «X → X».
        return "termcheck пропущен — проверять было нечего"
    if tc.get("findings"):
        return "termcheck нашёл замечания"
    # Сверка хеша обязательна: сегмент, который однажды чинили, а потом
    # перевели заново, к ремонту уже не относится. Без неё он навсегда
    # оставался бы «переписанным» и никогда не стал бы донором для глоссария.
    if (seg.get("repair") or {}).get("applied") and _repair_tried(seg):
        return "текст переписан автоматическим ремонтом"
    return None


def _harvest_if_clean(seg: dict, project: dict) -> list:
    """Сбор терминологии с машинно-чистого сегмента. Вызывается в конце
    back-check и termcheck: какой из двух прогонов отработает вторым, тот и
    увидит обе оценки. Подтверждённые сегменты сюда не попадают — их
    терминологию собирает confirm_segment с пометкой «подтвердил человек»."""
    if seg.get("status") == "confirmed":
        return []
    pol = _auto_policy(project.get("domain"))
    if _machine_clean(seg, pol["backcheck_min"]) is not None:
        return []
    return _harvest_terms(seg, project, via="auto")


def _identical_source_segments(project: dict, seg: dict) -> dict:
    """Сегменты с тем же исходником и другим переводом. Ключ нормализован:
    лишний пробел или регистр не должны решать, повтор это или нет."""
    key = _norm_key(seg.get("source"))
    target = (seg.get("target") or "").strip()
    pending, confirmed = [], []
    for s in project["segments"]:
        if s["id"] == seg["id"] or _norm_key(s.get("source")) != key:
            continue
        if (s.get("target") or "").strip() == target:
            continue
        (confirmed if s.get("status") == "confirmed" else pending).append(s["id"])
    return {"pending": pending, "confirmed": confirmed}


@app.post("/api/segments/{pid}/{sid}/confirm")
def confirm_segment(pid: int, sid: int):
    """Подтверждение = момент обучения: пара уходит в TM, термины — в очередь
    кандидатов, повторы исходника возвращаются клиенту предложением.
    Ничего чужого сами не переписываем: распространение — отдельная команда."""
    seg = get_segment(pid, sid)
    project = get_project(pid)
    seg["status"] = "confirmed"
    # Отметка о человеке нужна именно здесь: `confirmed` в проекте есть и на
    # старых сегментах, которые так пометило точное совпадение с TM (сейчас
    # оно ставит `translated`, см. _replace_target). Автоодобрение опирается
    # на «подтвердил человек» — без отметки такая подстановка сходила бы
    # за подтверждение и накручивала бы доказательства сама себе.
    seg["confirmedBy"] = "human"
    seg["confirmedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    tm_action, candidates = None, []
    if (seg.get("target") or "").strip():
        tm_action = _tm_upsert(seg["source"], seg["target"], project)
        candidates = _harvest_terms(seg, project)
    same = _identical_source_segments(project, seg)
    save_state(STATE)
    return {"ok": True, "segment": seg, "tm": tm_action, "propagate": same,
            "termCandidates": [{"id": c["id"], "kind": c["kind"], "src": c["src"],
                                "tgt": c.get("tgt", ""), "wasTgt": c.get("wasTgt", "")}
                               for c in candidates]}


class PropagateRequest(BaseModel):
    ids: Optional[List[int]] = None
    include_confirmed: bool = False


@app.post("/api/segments/{pid}/{sid}/propagate")
def propagate_segment(pid: int, sid: int, req: PropagateRequest = PropagateRequest()):
    """Разослать подтверждённый перевод в сегменты с идентичным исходником.
    Только по явной команде и по умолчанию мимо подтверждённых: молча
    переписать чужую правку — худшее, что может сделать CAT-инструмент.
    Затронутые сегменты получают статус translated, а не confirmed: подтвердить
    перевод может только человек, иначе автоподстановка сама себя заверяет."""
    seg = get_segment(pid, sid)
    project = get_project(pid)
    target = (seg.get("target") or "").strip()
    if not target:
        raise HTTPException(400, "У сегмента нет перевода")
    same = _identical_source_segments(project, seg)
    allowed = set(same["pending"])
    if req.include_confirmed:
        allowed |= set(same["confirmed"])
    if req.ids is not None:
        allowed &= set(req.ids)
    changed = []
    for s in project["segments"]:
        if s["id"] not in allowed:
            continue
        # Через _replace_target: у подтверждённого сегмента снимается отметка
        # «подтвердил человек» и статус становится «требует проверки». Иначе
        # рассылка оставляла бы чужую подпись на подставленном ею тексте.
        s["prevTarget"] = s.get("target", "")      # ручной откат остаётся возможен
        _replace_target(s, target, PROVIDER_TM, "EXACT_TM")
        s["propagatedFrom"] = seg["id"]
        changed.append(s["id"])
    if changed:
        save_state(STATE)
    return {"ok": True, "changed": changed,
            "skippedConfirmed": [] if req.include_confirmed else same["confirmed"]}


# ─── Очередь кандидатов в глоссарий ──────────────────────────────────
@app.get("/api/term-queue")
def list_term_queue(status: str = "pending", limit: int = 200, offset: int = 0,
                    project: Optional[int] = None):
    """Кандидаты, отсортированные по частоте: сверху то, что мешает чаще всего.

    Вместе с карточками отдаём РАЗБОР: почему автоматика не берёт каждую и
    сколько таких же. Без него очередь на четыреста штук — стена одинаковых
    карточек, и человек не видит, что треть из них вообще не термины."""
    items = _term_queue()
    counts = {}
    for c in items:
        st = c.get("status", "pending")
        counts[st] = counts.get(st, 0) + 1
    if status and status != "all":
        items = [c for c in items if c.get("status", "pending") == status]
    items = sorted(items, key=lambda c: (-c.get("hits", 1), -c.get("id", 0)))

    groups, reason_of = [], {}
    if project:
        # Область применяем ко ВСЕМУ ответу, а не только к разбору: иначе
        # значок показывает одно число, сумма групп другое, а карточки чужой
        # языковой пары висят без причины и пропадают под любым фильтром.
        scope = _project_scope(get_project(project))
        items = [c for c in items if _scope_of(c) == scope]
    if status == "pending" and items and project:
        project_obj = get_project(project)
        pol = _auto_policy(project_obj.get("domain"))
        ctx = _auto_context(items, pol)
        ctx["corpus"] = {}          # без сети: это список, а не прогон
        buckets: dict = {}
        for c in items:
            action, why = _auto_verdict(c, ctx)
            if action in (GLOSSARY_TIER_HARD, GLOSSARY_TIER_SOFT):
                key = "ready"
            elif action == "close":
                key = "closed"      # уже в глоссарии — не «ждёт человека»
            else:
                key = why or "—"
            reason_of[c["id"]] = key
            b = buckets.setdefault(key, {"reason": key, "count": 0, "ids": [],
                                         # Отклонять пачкой можно не всё: см. bulk
                                         "bulk": key not in ("ready", "closed")})
            b["count"] += 1
            b["ids"].append(c["id"])
        # Конфликт нельзя отклонить пачкой: у него нет своего перевода, и
        # отказ по нему заблокировал бы вопрос навсегда — см. bulk_decide_terms.
        for b in buckets.values():
            if b["bulk"] and all(not (c.get("tgt") or "").strip()
                                 for c in items if c["id"] in set(b["ids"])):
                b["bulk"] = False
        groups = sorted(buckets.values(), key=lambda x: -x["count"])
    out = items[offset:offset + limit]
    return {"total": len(items), "counts": counts,
            "groups": groups,
            "items": [{**c, "why": reason_of.get(c["id"])} for c in out]}


class BulkDecision(BaseModel):
    ids: List[int]
    action: str = "reject"      # только отклонение: см. ниже


@app.post("/api/term-queue/bulk")
def bulk_decide_terms(req: BulkDecision):
    """Массовое ОТКЛОНЕНИЕ пачки кандидатов.

    Массового одобрения здесь нет намеренно. Одобрение пишет правило для всех
    будущих текстов, и «одобрить всё, что видно» — это подпись не глядя под
    четырьмястами правилами: ровно то, от чего защищает вся остальная система.
    Массовое одобрение уже есть в другом месте и с доказательствами —
    /term-queue/auto-approve, который берёт только то, за что может поручиться.

    Отклонение безопасно: оно ничего не пишет в глоссарий, а лишь убирает
    из очереди то, что термином не является. Ошиблись — кандидат вернётся,
    как только пара встретится снова с другим переводом."""
    if req.action != "reject":
        raise HTTPException(400, "Массовым может быть только отклонение. "
                                 "Одобрение пачкой — /term-queue/auto-approve, "
                                 "оно берёт лишь то, что подтверждено.")
    want = set(req.ids)
    done, kept = [], []
    # Под локом: очередь одна, а прогон на сервере пишет в неё из рабочего
    # потока — проход с мутацией без лока мог бы пропустить часть указанных.
    with _TERM_QUEUE_LOCK:
        for c in _term_queue():
            if c.get("id") not in want or c.get("status", "pending") != "pending":
                continue
            if not (c.get("tgt") or "").strip():
                # Кандидат без своего перевода (конфликт с глоссарием).
                # Дедупликация помнит его по паре «термин + пустой перевод»,
                # поэтому отказ закрыл бы этот вопрос НАВСЕГДА — а обещание
                # «встретится снова — спросим заново» тут выполнить нечем.
                # Такие решает человек по одному, вписав верный вариант.
                kept.append(c["id"])
                continue
            _mark_decided(c, "rejected", note="отклонён пачкой")
            done.append(c["id"])
    save_state(STATE)
    return {"ok": True, "rejected": done, "count": len(done),
            "kept": kept,
            "keptWhy": ("у этих кандидатов нет своего перевода — отказ закрыл бы "
                        "вопрос навсегда, их решают по одному") if kept else ""}


class TermDecision(BaseModel):
    src: Optional[str] = None
    tgt: Optional[str] = None
    cat: Optional[str] = None


def _mark_decided(cand: dict, status: str, src: str = None, tgt: str = None, **extra):
    """Решение по кандидату. Прежнюю пару запоминаем ДО правки: по ней работает
    дедупликация (см. _cand_pair). Примеры сегментов снимаем — решённый кандидат
    живёт дальше не как карточка, а как память «этот вопрос уже задавали»."""
    if src is not None and _norm_key(src) != _norm_key(cand.get("src")):
        cand.setdefault("origSrc", cand.get("src", ""))
        cand["src"] = src
    if tgt is not None and _norm_key(tgt) != _norm_key(cand.get("tgt")):
        cand.setdefault("origTgt", cand.get("tgt", ""))
        cand["tgt"] = tgt
    cand["status"] = status
    cand["decidedBy"] = "human"
    cand["decidedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    cand.update(extra)
    for k in ("sampleSrc", "sampleTgt"):
        cand.pop(k, None)
    return cand


def _human_decision(c: dict) -> bool:
    """Решение принял человек, а не автоодобрение. Такие живут в очереди дольше:
    именно они не дают спросить про уже решённый термин второй раз."""
    if c.get("decidedBy") == "human":
        return True
    return not (c.get("autoBatch") or c.get("autoTier") or "autoWrote" in c)


def _close_same_term(decided: dict, scope: tuple) -> list:
    """Закрыть остальные ОЖИДАЮЩИЕ карточки про тот же термин в той же области.
    Человек ответил не на карточку, а на вопрос «как переводить этот термин»:
    оставлять рядом второй вопрос про него же — значит показать после
    обновления страницы уже решённое как нерешённое."""
    key = _cand_pair(decided)[0]
    tgt = _norm_key(decided.get("tgt"))
    closed = []
    # Под локом: очередь одна, а прогон на сервере пишет в неё из рабочего
    # потока. Проход с мутацией без лока мог бы разойтись с _queue_term.
    with _TERM_QUEUE_LOCK:
        return _close_same_term_locked(decided, scope, key, tgt, closed)


def _close_same_term_locked(decided, scope, key, tgt, closed):
    for c in _term_queue():
        if c is decided or c.get("status", "pending") != "pending":
            continue
        if _cand_pair(c)[0] != key or _scope_of(c) != scope:
            continue
        rival = _norm_key(c.get("tgt"))
        if rival and rival != tgt:
            # Карточка с ДРУГИМ переводом — не повтор вопроса, а проигравший
            # вариант: в глоссарий она не попала, и помечать её «одобрено»
            # значило бы соврать. Пишем «отклонён» и называем победителя —
            # если выбор окажется неверным, запись глоссария правится руками.
            _mark_decided(c, "rejected", decidedWith=decided["id"],
                          note="не выбран: для термина одобрен вариант «%s»"
                               % decided.get("tgt", ""))
        else:
            _mark_decided(c, "approved", decidedWith=decided["id"],
                          note="решено вместе с кандидатом #%d" % decided["id"])
        closed.append(c["id"])
    return closed


@app.post("/api/term-queue/{cid}/approve")
def approve_term_candidate(cid: int, req: TermDecision = TermDecision()):
    """Одобренный кандидат становится проверенной записью глоссария — только
    такие уходят в промпт жёстким правилом."""
    cand = next((c for c in _term_queue() if c.get("id") == cid), None)
    if not cand:
        raise HTTPException(404, "Кандидат не найден")
    src = (req.src or cand.get("src") or "").strip()
    tgt = (req.tgt or cand.get("tgt") or "").strip()
    if not src or not tgt:
        raise HTTPException(400, "Нужен и термин, и перевод. У кандидата-конфликта "
                                 "перевод пуст: впишите верный вариант.")
    # Категорию берём от кандидата: жёсткий медицинский дефолт в юридическом
    # проекте помечал договоры как «Disease».
    cat = req.cat or cand.get("cat") or "Term"
    today = datetime.now().strftime("%Y-%m-%d")
    scope = _scope_of(cand)
    existing = _glossary_entry(src, scope)
    if existing:
        existing.update({"tgt": tgt, "cat": cat, "conf": "high", "tier": GLOSSARY_TIER_HARD,
                         "note": "уточнено вручную " + today, "updated": today,
                         "prevTgt": existing.get("tgt", "")})
        _clear_auto_marks(existing)
    else:
        STATE["glossary"].insert(0, {"src": src, "tgt": tgt, "cat": cat, "freq": 1,
                                     "conf": "high", "note": "", "tier": GLOSSARY_TIER_HARD,
                                     "lang": scope[0], "domain": scope[1],
                                     "updated": today,
                                     "origin": "confirmed:" + str(cand.get("segment", ""))})
    # Пара запоминается до правки, остальные карточки про этот же термин
    # закрываются: иначе одобренный термин всплывал бы снова — и как сосед
    # по очереди, и как заново созданный кандидат на следующем сборе.
    _mark_decided(cand, "approved", src=src, tgt=tgt)
    closed = _close_same_term(cand, scope)
    _invalidate_gloss_index()
    save_state(STATE)
    return {"ok": True, "candidate": cand, "replaced": bool(existing), "closed": closed}


class ExplainRequest(BaseModel):
    variants: Optional[List[str]] = None   # что сравниваем; по умолчанию — все из очереди
    # Вариант, который обязан попасть в сравнение: то, что человек напечатал
    # в поле карточки. Не список, а добавка — иначе черновик вытеснял бы
    # остальные варианты, и сравнивать стало бы не с чем.
    include: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/term-queue/{cid}/explain")
def explain_term_variants(cid: int, req: ExplainRequest = ExplainRequest()):
    """Объяснить варианты перевода НА ЯЗЫКЕ ОРИГИНАЛА.

    Ключевая мысль: пользователь может не знать целевого языка — и тогда
    вопрос «какой перевод верный» для него бессмыслен. Но вопрос «какое из
    двух значений вы имели в виду» он понимает, если оба значения написаны
    по-русски. Поэтому по каждому варианту спрашиваем у модели:
      обратный перевод — как этот вариант читается носителем целевого языка;
      определение     — что этот термин означает, одной строкой на языке оригинала;
      область         — где он употребляется.
    Человек сравнивает РУССКОЕ с РУССКИМ и выбирает смысл, а не строку.

    Вызов платный, поэтому только по кнопке и только на конкретную карточку."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Разбор вариантов требует ключ OpenAI")
    cand = next((c for c in _term_queue() if c.get("id") == cid), None)
    if not cand:
        raise HTTPException(404, "Кандидат не найден")
    scope = _scope_of(cand)
    src_lang, tgt_lang = (authorities_mod.source_lang(scope[0]),
                          authorities_mod.target_lang(scope[0])) if authorities_mod \
        else (scope[0].split("→")[0], scope[0].split("→")[-1])
    term = (cand.get("src") or "").strip()

    # Что сравниваем: присланные варианты, иначе всё, что предлагает очередь
    # и справочники по этому термину. Пустой перевод у конфликта не вариант.
    variants = [v.strip() for v in (req.variants or []) if v and v.strip()]
    if variants and (req.include or "").strip():
        # include — «этот вариант обязан участвовать». Игнорировать его при
        # заданном списке значило бы потерять именно то, что человек напечатал.
        if _norm_key(req.include) not in {_norm_key(v) for v in variants}:
            variants.insert(0, req.include.strip())
    if not variants:
        seen = set()
        # Первым идёт то, что человек напечатал (или, если не печатал, перевод
        # самой карточки): обрезая список до шести, нельзя выбросить именно тот
        # вариант, ради которого нажали кнопку.
        for first in ((req.include or "").strip(), (cand.get("tgt") or "").strip()):
            if first and _norm_key(first) not in seen:
                variants.append(first)
                seen.add(_norm_key(first))
        for c in _term_queue():
            if (c.get("status", "pending") == "pending" and _scope_of(c) == scope
                    and _norm_key(c.get("src")) == _norm_key(term) and (c.get("tgt") or "").strip()):
                if _norm_key(c["tgt"]) not in seen:
                    seen.add(_norm_key(c["tgt"]))
                    variants.append(c["tgt"].strip())
        # Запись глоссария — раньше очередных вариантов: её уже утверждали,
        # и вытеснять её потолком в шесть штук нельзя.
        known = _glossary_entry(term, scope)
        if known and known.get("tgt") and _norm_key(known["tgt"]) not in seen:
            seen.add(_norm_key(known["tgt"]))
            variants.insert(len(variants) and 1 or 0, known["tgt"])
        for v in _authority_suggests(term, scope):
            if _norm_key(v) not in seen:
                seen.add(_norm_key(v))
                variants.append(v)
    # Молчаливых потолков не бывает: сколько не влезло — скажем в ответе.
    dropped = max(0, len(variants) - 6)
    variants = variants[:6]
    if not variants:
        raise HTTPException(400, "Нечего сравнивать: у термина нет ни одного варианта перевода")

    dom = _resolve_domain(scope[1])
    system = (
        f"You are a {dom['expert']}. The user does NOT speak {tgt_lang} and must choose "
        f"between candidate {tgt_lang} translations of a {src_lang} term by MEANING.\n\n"
        f"For each candidate return, WRITTEN IN {src_lang} (this is essential — the user "
        f"reads only {src_lang}):\n"
        f"  back — how the candidate reads to a native {tgt_lang} speaker, translated back "
        f"literally into {src_lang};\n"
        f"  meaning — what the candidate actually denotes, one short sentence in {src_lang};\n"
        f"  usage — where this wording is used (register, field), a few words in {src_lang};\n"
        f"  same — true if it denotes exactly the same concept as the {src_lang} term.\n\n"
        'Return ONLY JSON: {"variants":[{"tgt":"...","back":"...","meaning":"...",'
        '"usage":"...","same":true}]}. No commentary.'
    )
    body = (f"{src_lang} term: {term}\n"
            + (f"Context sentence: {cand.get('sampleSrc')}\n" if cand.get("sampleSrc") else "")
            + f"Candidate {tgt_lang} translations:\n"
            + "\n".join("  - " + v for v in variants))
    try:
        import openai
        mdl = _resolve_model(req.model or JUDGE_DEFAULT_MODEL)
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=90, max_retries=1)
        extra = ({"max_completion_tokens": 2048} if mdl["api"] == "modern"
                 else {"max_tokens": 900, "temperature": 0})
        resp = client.chat.completions.create(
            model=mdl["id"], response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": body}], **extra)
        _note_usage("terms", mdl["id"], resp)
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            # Пустой ответ (модель израсходовала лимит на рассуждения) — это
            # отказ. Отдать его как «разобрано, но всё пусто» значит показать
            # человеку прочерки там, где он ждёт объяснения смысла.
            raise ValueError("модель вернула пустой ответ")
        data = json.loads(raw)
        by_tgt = {_norm_key(v.get("tgt")): v
                  for v in (data.get("variants") or []) if isinstance(v, dict)}
    except Exception as e:
        print(f"[backend] explain term #{cid}: {e}", file=sys.stderr)
        raise HTTPException(502, "Модель не разобрала варианты. Попробуйте ещё раз.")

    # Корпус по всем вариантам разом: шесть последовательных внешних запросов
    # с троттлингом под лимит источника — это ещё минута поверх уже оплаченного
    # вызова модели, и человек всё это время смотрит на «Разбираем…».
    att_by = dict(zip([_norm_key(v) for v in variants],
                      _run_parallel(variants, lambda v: _corpus_check(v, scope))))
    out = []
    for v in variants:
        got = by_tgt.get(_norm_key(v))
        # Модель про этот вариант ничего не сказала — так и передаём (None).
        # «Не знаю» нельзя показывать как «иное понятие»: человек, который по
        # условию не читает целевой язык, отвергнет верный перевод.
        answered = isinstance(got, dict)
        got = got if answered else {}
        # Корпус тут же: «сколько раз этот термин вообще встречается в языке» —
        # цифра, которую человек оценит без знания языка.
        att = att_by.get(_norm_key(v))
        out.append({
            "tgt": v,
            "back": got.get("back") or "",
            "meaning": got.get("meaning") or "",
            "usage": got.get("usage") or "",
            "same": (bool(got.get("same")) if answered and "same" in got else None),
            "corpus": ({"hits": att["hits"], "label": att["label"]} if att else None),
            "authority": _authority_match(term, v, scope),
        })
    return {"ok": True, "term": term, "variants": out, "dropped": dropped,
            "model": _resolve_model(req.model or JUDGE_DEFAULT_MODEL)["id"]}


@app.post("/api/term-queue/{cid}/reject")
def reject_term_candidate(cid: int):
    cand = next((c for c in _term_queue() if c.get("id") == cid), None)
    if not cand:
        raise HTTPException(404, "Кандидат не найден")
    # Соседей не трогаем: «эта пара неверна» — не то же самое, что «с термином
    # разобрались». Другой вариант перевода того же термина остаётся вопросом.
    _mark_decided(cand, "rejected")
    save_state(STATE)
    return {"ok": True, "candidate": cand}


# ─── Автоодобрение однозначных кандидатов ────────────────────────────
# Смысл: человеку, далёкому от переводов, не нужно щёлкать сотни карточек.
# Правила опираются ТОЛЬКО на сигналы, не зависящие от языка и тематики:
#   1. единственность варианта — у термина ровно один перевод в очереди;
#   2. согласие независимых сегментов — одна и та же пара пришла из разных мест;
#   3. оценки ЧУЖИХ прогонов — back-check идёт в обратную сторону, termcheck
#      смотрит только на целевой текст. Мнение того вызова, который сделал
#      перевод, доказательством не считается.
#
# Ключевое отличие от ручного одобрения: автоматика пишет в tier "auto" —
# подсказку, которую модель вправе игнорировать. Приказом ("verified") запись
# становится от человека либо от трёх независимых подтверждений, а в медицине,
# фарме и юриспруденции — только от человека: там цена приказа выше.
AUTO_POLICY_VERSION = "v2"          # v2: внешние справочники и корпус
AUTO_BATCH_HISTORY = 20
# Потолок корпусных запросов на один разбор очереди. Каждый — внешний HTTP;
# 200 штук по шесть секунд таймаута в шесть потоков — это минуты, а не часы.
AUTO_CORPUS_MAX = int(os.environ.get("AUTO_CORPUS_MAX", "200"))

AUTO_APPROVE_DEFAULT = {
    "auto_min_segments": 2,        # независимых машинно-чистых сегментов на подсказку
    "verified_min_segments": 3,    # ... на приказ
    "backcheck_min": 90,           # ниже этого сегмент-донор не считается чистым
    "allow_verified": True,
    "max_src_words": 3,
    "max_tgt_words": 6,
}

AUTO_APPROVE_BY_DOMAIN = {
    "medical": {"allow_verified": False},
    "pharma": {"allow_verified": False},
    "legal": {"allow_verified": False},
}


# ─── Внешние источники приказов ──────────────────────────────────────
# Справочники лежат файлами в data/authorities/*.tsv и подхватываются при
# старте: добавить источник — значит положить файл, а не править код.
# Два каталога, и это не дублирование:
#   authority_data/ — источники, едущие в git вместе с кодом (общие для всех);
#   data/authorities/ — то, что добавил владелец сервера (в git не хранится,
#                       как и все данные в data/).
AUTHORITY_DIRS = [ROOT / "backend" / "authority_data", DATA_DIR / "authorities"]
_DICTIONARIES: list = []


def _load_authorities():
    global _DICTIONARIES
    if not authorities_mod:
        return
    loaded = []
    for d in AUTHORITY_DIRS:
        try:
            loaded.extend(authorities_mod.load_dictionaries(d))
        except Exception as e:                               # pragma: no cover
            print(f"[backend] справочники из {d} не загружены: {e}", file=sys.stderr)
    _DICTIONARIES = loaded


_load_authorities()      # ОБЯЗАТЕЛЬНО при импорте: без этого вызова весь путь
                         # «приказ от справочника» мёртв, и медицина с фармой
                         # навсегда остаются без приказов, кроме человеческих.


def _authority_match(src: str, tgt: str, scope: tuple) -> Optional[dict]:
    """Совпадение пары с отраслевым справочником для ЭТОЙ области и пары языков.

    Это и есть приказ без человека: норму зафиксировал тот, кто в предметной
    области разбирается. Справочник чужой пары языков или чужой области не
    подходит никогда — выдуманное подтверждение хуже отсутствующего."""
    best = None
    for d in _DICTIONARIES:
        if d.covers(scope[0], scope[1]) and d.match(src, tgt):
            hit = {"id": d.id, "label": d.label, "tier": getattr(d, "tier", "verified")}
            if hit["tier"] == GLOSSARY_TIER_HARD:
                return hit          # выверенный источник — дальше искать нечего
            best = best or hit      # краудсорсный запоминаем, вдруг найдётся лучше
    return best


def _authority_suggests(src: str, scope: tuple) -> list:
    """Что справочники предлагают для термина — показываем человеку рядом
    с кандидатом: «не совпало» без «а как правильно» бесполезно."""
    out = []
    for d in _DICTIONARIES:
        if d.covers(scope[0], scope[1]):
            out.extend(d.suggest(src))
    return sorted(set(out))


def _corpus_check(tgt: str, scope: tuple) -> Optional[dict]:
    """Живёт ли перевод в целевом языке. None — «проверить нечем», и это
    НЕ отрицательный ответ: молчащий источник не должен ни одобрять, ни
    блокировать."""
    if not authorities_mod:
        return None
    try:
        return authorities_mod.attested(tgt, authorities_mod.target_lang(scope[0]), scope[1])
    except Exception as e:                                   # pragma: no cover
        print(f"[backend] корпусная проверка не удалась: {e}", file=sys.stderr)
        return None


def _authority_sources(scope: tuple) -> dict:
    """Чем в этой области и паре языков вообще есть чем проверять. Нужно
    интерфейсу: разница в качестве между парами языков должна быть названа,
    а не обнаружена пользователем на своих текстах."""
    dicts = [{"id": d.id, "label": d.label, "terms": len(d.pairs),
              "tier": getattr(d, "tier", "verified")}
             for d in _DICTIONARIES if d.covers(scope[0], scope[1])]
    corpus = None
    if authorities_mod:
        c = authorities_mod.corpus_for(authorities_mod.target_lang(scope[0]), scope[1])
        if c and authorities_mod.corpus_available(authorities_mod.target_lang(scope[0]), scope[1]):
            corpus = {"id": c["id"], "label": c["label"]}
    return {"dictionaries": dicts, "corpus": corpus}


def _auto_policy(domain_id: Optional[str]) -> dict:
    pol = dict(AUTO_APPROVE_DEFAULT)
    pol.update(AUTO_APPROVE_BY_DOMAIN.get(_resolve_domain(domain_id)["id"], {}))
    return pol


def _donor_ids(cand: dict) -> list:
    """Доноры кандидата как «проект:сегмент». Номера сегментов уникальны только
    внутри проекта — без префикса сегмент #12 из другого проекта сошёл бы за
    того же донора и накрутил бы доказательства."""
    ids = cand.get("segments")
    if ids:
        return list(dict.fromkeys(ids))
    if cand.get("segment") and cand.get("project"):
        return [f"{cand['project']}:{cand['segment']}"]
    return []


def _auto_context(pending: list, pol: dict) -> dict:
    """Индексы, собранные ОДИН раз на прогон. Без них разбор 2000 кандидатов
    гонял бы линейный поиск по 10 000 записей глоссария и по всем сегментам
    проекта на каждого — единственный воркер вставал бы на секунды."""
    segs = {(p["id"], s["id"]): s for p in STATE["projects"] for s in p["segments"]}
    gloss: dict = {}
    for g in STATE["glossary"]:
        gloss.setdefault((_scope_of(g), _norm_key(g.get("src"))), g)
    return {"variants": _auto_variants(pending), "segs": segs, "gloss": gloss, "pol": pol}


def _donor_quality(cand: dict, ctx: dict) -> tuple:
    """(годных доноров, был ли подтверждённый человеком, сколько среди них
    РАЗНЫХ исходников, причина отказа).

    Донор годится, если сегмент подтвердил человек либо он прошёл back-check и
    termcheck чисто. Копии чужого решения донорами не считаются вовсе, а число
    разных исходников отделяет «три независимых сегмента» от «один и тот же
    заголовок, переведённый трижды»: во втором случае согласие ничего не
    доказывает, это одна и та же строка."""
    good, confirmed, why = 0, False, None
    sources = set()
    for ref in _donor_ids(cand):
        try:
            pid, sid = (int(x) for x in str(ref).split(":", 1))
        except ValueError:
            continue
        seg = ctx["segs"].get((pid, sid))
        if seg is None:
            why = why or "сегмент-источник удалён"
            continue
        if seg.get("route") == "DUPLICATE" or seg.get("propagatedFrom"):
            why = why or "перевод скопирован с другого сегмента"
            continue
        if seg.get("status") == "confirmed" and seg.get("confirmedBy") == "human":
            good += 1
            confirmed = True
            sources.add(_norm_key(seg.get("source")))
            continue
        # Подтверждён, но не человеком (подстановка из TM) — обычный кандидат:
        # решают проверки, а не статус.
        reason = _machine_clean(seg, ctx["pol"]["backcheck_min"])
        if reason is None:
            good += 1
            sources.add(_norm_key(seg.get("source")))
        else:
            why = why or reason
    return good, confirmed, len(sources), why


def _auto_variants(pending: list) -> dict:
    """(область, термин) → множество различных переводов среди кандидатов.
    Два варианта — это и есть определение неоднозначности: такой термин
    автоматика не трогает вообще."""
    out: dict = {}
    for c in pending:
        tgt = (c.get("tgt") or "").strip()
        if not tgt:
            continue
        out.setdefault((_scope_of(c), _norm_key(c.get("src"))), set()).add(_norm_key(tgt))
    return out


def _auto_verdict(cand: dict, ctx: dict) -> tuple:
    """(действие, причина). Действие: "verified" | "auto" | "close" | None.
    "close" — пара уже есть в глоссарии слово в слово: кандидата закрываем,
    глоссарий не трогаем."""
    pol = ctx["pol"]
    src = (cand.get("src") or "").strip()
    tgt = (cand.get("tgt") or "").strip()
    if cand.get("kind") == "conflict" or not tgt:
        return None, "нет готового перевода — решает человек"
    if not src:
        return None, "пустой термин"
    if len(src.split()) > pol["max_src_words"]:
        return None, "длинный термин — похоже на фразу"
    if len(tgt.split()) > pol["max_tgt_words"]:
        return None, "длинный перевод — похоже на фразу"
    if src.rstrip().endswith((".", "!", "?", ":", ";")):
        return None, "похоже на предложение, а не термин"

    scope = _scope_of(cand)
    known = ctx["gloss"].get((scope, _norm_key(src)))
    if known:
        if _norm_key(known.get("tgt")) == _norm_key(tgt):
            return "close", "уже в глоссарии"
        if _hit_tier(known) == GLOSSARY_TIER_HARD:
            return None, "спорит с проверенной записью глоссария"
        if known.get("autoBatch"):
            # Записать поверх — значит затереть prevTgt прошлой пачки своим же
            # значением: та пачка перестанет откатываться, а откат этой вернёт
            # чужой машинный вариант вместо исходного.
            return None, "запись занята пачкой #%s — сначала откатите её" % known["autoBatch"]
        # Запись уровня "auto" (массовый импорт) — как раз то, что автоодобрение
        # и должно чинить: у нас есть доказательства, у неё их не было.

    # ── Внешний справочник: приказ без человека ──────────────────────
    # Совпадение с отраслевым справочником — не мнение системы о собственном
    # переводе, а зафиксированная норма. Это единственное, что даёт verified
    # там, где allow_verified выключен (медицина, фарма, юриспруденция):
    # запрет касается САМООДОБРЕНИЯ, а справочник находится вне контура.
    # Проверяется РАНЬШЕ спора вариантов: когда у термина два перевода,
    # справочник как раз и говорит, какой из них норма.
    auth = _authority_match(src, tgt, scope)
    if auth:
        # Справочник может держать несколько норм на один термин. Если под них
        # подходит сразу два кандидата из очереди — он не разрешает спор, а
        # участвует в нём: решает человек. Иначе первый по порядку очереди
        # получал бы приказ, а второй молча закрывался как решённый.
        rivals = [v for v in ctx["variants"].get((scope, _norm_key(src)), set())
                  if _authority_match(src, v, scope)]
        if len(rivals) > 1:
            return None, "справочник допускает несколько вариантов — решает человек"
        # Тумблер «только подсказки» — это про ЭТОТ запуск, а не про политику
        # области: человек попросил ничего не поднимать до приказа, и справочник
        # не повод его переспрашивать.
        if auth["tier"] == GLOSSARY_TIER_HARD and not pol.get("cap_soft"):
            return GLOSSARY_TIER_HARD, "совпадает со справочником: " + auth["label"]
        if auth["tier"] == GLOSSARY_TIER_HARD:
            return GLOSSARY_TIER_SOFT, ("совпадает со справочником (%s), "
                                        "но выбран режим «только подсказки»" % auth["label"])
        # Краудсорсный источник приказывать в одиночку не вправе: выборочная
        # проверка находит в таких неверные нормы. Он идёт ГОЛОСОМ — дальше по
        # коду его учитывают вместе с согласием сегментов и корпусом.

    if len(ctx["variants"].get((scope, _norm_key(src)), set())) > 1:
        return None, "у термина несколько вариантов перевода"

    # ── Корпус целевого языка: вето на кальки ────────────────────────
    # Корпус не подтверждает перевод, он отвечает на другой вопрос — есть ли
    # такой термин в языке. Ноль вхождений («rear cyclitis») означает, что мы
    # изобрели слово, и никакое согласие доноров этого не искупает: они все
    # сделаны одной и той же моделью с одной и той же кальки.
    corpus = ctx.get("corpus", {}).get((scope, _norm_key(tgt)))
    if corpus and corpus.get("absent"):
        return None, "перевода нет в текстах целевого языка (%s)" % corpus["label"]

    good, confirmed, distinct, why = _donor_quality(cand, ctx)
    if good == 0:
        return None, why or "сегмент-источник не проходил проверок"
    if cand.get("kind") == "audit" and good < 2:
        # Находка termcheck — это мнение модели о собственном переводе.
        # Одного такого мнения мало даже для подсказки.
        return None, "находка termcheck встретилась только раз"
    if not confirmed and good < pol["auto_min_segments"]:
        return None, "подтверждений: %d, нужно %d" % (good, pol["auto_min_segments"])

    # Краудсорсный справочник + корпус СНИЖАЮТ порог согласия сегментов на один,
    # но не отменяют запрет области. Почему только снижают: голоса независимы
    # не полностью — модель могла выучить те же ошибки справочника, а корпус
    # подтверждает лишь то, что строка в языке существует. «Анизакидоз →
    # Anisakis» (болезнь против рода паразита) прошёл бы все три проверки, и
    # в медицине цена такого приказа выше пользы от автоматизации: там приказ
    # по-прежнему даёт человек или ВЫВЕРЕННЫЙ справочник (см. выше по коду).
    corroborated = bool(auth) and bool(corpus) and corpus.get("ok")
    need = pol["verified_min_segments"]
    if corroborated:
        need = max(2, need - 1)
    if (pol["allow_verified"] and good >= need and distinct >= need
            and good == len(_donor_ids(cand))):
        if corroborated:
            return GLOSSARY_TIER_HARD, ("%d независимых сегмента + справочник %s + %s (%d)"
                                        % (distinct, auth["label"],
                                           corpus["label"], corpus["hits"]))
        # Корпус доступен, но термин в языке почти не встречается — согласия
        # доноров мало: приказ не даём, оставляем подсказкой. Обратное неверно —
        # частотность не делает перевод правильным, поэтому поднять до приказа
        # она не может, только удержать.
        if corpus and not corpus.get("ok"):
            return GLOSSARY_TIER_SOFT, ("%d независимых сегмента, но термин редок в %s (%d)"
                                        % (distinct, corpus["label"], corpus["hits"]))
        return GLOSSARY_TIER_HARD, ("%d независимых чистых сегмента" % distinct
                                    + (" · подтверждён в %s (%d)" % (corpus["label"], corpus["hits"])
                                       if corpus else ""))
    return GLOSSARY_TIER_SOFT, ("подтвердил человек" if confirmed
                                else "%d независимых чистых сегмента" % good)


def _forget_auto_batch(batch: int):
    """Пачка выпала из истории — откатить её уже нечем. Снимаем пометки, иначе
    записи навсегда застревали бы с отказом «сначала откатите пачку #N», а
    кнопки для этого в интерфейсе уже нет."""
    for g in STATE.get("glossary", []):
        if g.get("autoBatch") == batch:
            _clear_auto_marks(g)
            for k in ("prevTgt", "prevConf", "prevOrigin"):
                g.pop(k, None)
    for c in _term_queue():
        if c.get("autoBatch") == batch:
            c.pop("autoBatch", None)


def _clear_auto_marks(entry: dict):
    """Человек тронул запись — она больше не принадлежит пачке автоодобрения.
    Иначе откат пачки снёс бы или откатил именно то, что человек исправил."""
    for k in ("autoBatch", "autoCreated", "prevTier", "prevNote"):
        entry.pop(k, None)


def _auto_write(cand: dict, tier: str, batch: int, today: str) -> bool:
    """Записать пару в глоссарий. True, если существующая запись заменена.
    Прежние значения сохраняем — на них держится откат пачки."""
    scope = _scope_of(cand)
    src, tgt = cand["src"].strip(), cand["tgt"].strip()
    cat = cand.get("cat") or "Term"
    existing = _glossary_entry(src, scope)
    if existing:
        existing.update({
            "prevTgt": existing.get("tgt", ""), "prevTier": _hit_tier(existing),
            "prevNote": existing.get("note", ""), "prevConf": existing.get("conf", ""),
            "prevOrigin": existing.get("origin", ""),
            "tgt": tgt, "tier": tier, "cat": existing.get("cat") or cat,
            "conf": "high" if tier == GLOSSARY_TIER_HARD else "medium",
            "note": "автоодобрено " + today, "updated": today,
            "autoBatch": batch, "autoCreated": False,
            "origin": "auto:" + AUTO_POLICY_VERSION,
        })
        return True
    entry = {
        "src": src, "tgt": tgt, "cat": cat, "freq": 1,
        "conf": "high" if tier == GLOSSARY_TIER_HARD else "medium",
        "note": "автоодобрено " + today, "tier": tier,
        "lang": scope[0], "domain": scope[1], "updated": today,
        "autoBatch": batch, "autoCreated": True,
        "origin": "auto:" + AUTO_POLICY_VERSION,
    }
    STATE["glossary"].insert(0, entry)
    # Индекс по термину живёт всю пачку: без досыпки следующий кандидат той же
    # пары считал бы, что записи ещё нет. Полная инвалидация тут стоила бы
    # пересборки 10 000 записей на каждое одобрение.
    idx = _GLOSS_BY_SRC
    if idx is not None:
        idx.setdefault((scope, _norm_key(src)), entry)
    return False


class AutoApproveRequest(BaseModel):
    dry_run: bool = True
    # Корпусная проверка — это внешние HTTP-запросы с лимитом источника
    # (у PubMed 3 в секунду). В разборе «показать», который дёргается при каждом
    # открытии проекта, она превращала бы страницу в минутное ожидание. Поэтому
    # по умолчанию она идёт только при ПРИМЕНЕНИИ, а разбор честно помечается
    # как «до корпусной проверки». None = решить по dry_run.
    corpus: Optional[bool] = None
    project: Optional[int] = None      # смотреть только область этого проекта
    max_tier: Optional[str] = None     # "auto" — не поднимать до приказа
    limit: int = 2000


@app.post("/api/term-queue/auto-approve")
def auto_approve_terms(req: AutoApproveRequest = AutoApproveRequest()):
    """Разложить однозначных кандидатов по глоссарию без участия человека.

    dry_run=True (по умолчанию) НИЧЕГО не меняет — возвращает, что попадёт и
    что отсеяно с причинами. Смотреть до применения, а не после."""
    project = get_project(req.project) if req.project else None
    scope = _project_scope(project) if project else None
    pol = _auto_policy(project.get("domain") if project else None)
    if req.max_tier == GLOSSARY_TIER_SOFT:
        # cap_soft отдельно от allow_verified: первое — просьба пользователя
        # на этот запуск, второе — политика области. Их нельзя смешивать,
        # иначе справочник (который политику области обходит законно) обходил
        # бы и явно выбранный режим «только подсказки».
        pol = {**pol, "allow_verified": False, "cap_soft": True}

    pending = [c for c in _term_queue() if c.get("status", "pending") == "pending"
               and (scope is None or _scope_of(c) == scope)]
    ctx = _auto_context(pending, pol)

    considered = pending[:max(1, min(req.limit, 5000))]

    # Корпус спрашиваем ТОЛЬКО про тех, кто иначе прошёл бы: это внешний
    # HTTP-запрос, и гонять его на всю очередь из двух тысяч кандидатов —
    # значит потратить полчаса на термины, которые всё равно отсеются
    # по другим причинам. Сначала предварительный вердикт без корпуса,
    # потом проверка прошедших, потом окончательный вердикт.
    ctx["corpus"] = {}
    prelim = [c for c in considered
              if _auto_verdict(c, ctx)[0] in (GLOSSARY_TIER_HARD, GLOSSARY_TIER_SOFT)]
    # Корпус может ПОДНЯТЬ вердикт (справочник + корпус + сегменты), а не только
    # отсеять кальку. Значит разбор без него врёт в обе стороны, и молчать об
    # этом нельзя — см. corpusPending в ответе.
    corpus_asked, corpus_capped = 0, 0
    use_corpus = (not req.dry_run) if req.corpus is None else bool(req.corpus)
    if prelim and authorities_mod and use_corpus:
        # Ключ включает ОБЛАСТЬ: очередь общая на сервис, и без неё английский
        # корпус спрашивали бы про немецкие термины (и наоборот).
        by_key = {}
        for c in prelim:
            if (c.get("tgt") or "").strip():
                by_key.setdefault((_scope_of(c), _norm_key(c.get("tgt"))),
                                  (c.get("tgt") or "").strip())
        want = list(by_key)
        corpus_capped = max(0, len(want) - AUTO_CORPUS_MAX)
        want = want[:AUTO_CORPUS_MAX]
        results = _run_parallel(want, lambda k: (k, _corpus_check(by_key[k], k[0])))
        ctx["corpus"] = {k: v for k, v in results if v}
        corpus_asked = len(ctx["corpus"])
        if corpus_capped:
            # Молчаливых потолков не бывает: сказали, скольких не проверили.
            print(f"[backend] корпусная проверка: {corpus_asked} терминов, "
                  f"{corpus_capped} сверх потолка не проверены", file=sys.stderr)

    picked, closed, skipped = [], [], {}
    taken = set()
    for cand in considered:
        action, reason = _auto_verdict(cand, ctx)
        row = {"id": cand["id"], "kind": cand.get("kind"), "src": cand.get("src"),
               "tgt": cand.get("tgt"), "lang": _scope_of(cand)[0],
               "domain": _scope_of(cand)[1], "reason": reason,
               "hits": cand.get("hits", 1), "donors": len(_donor_ids(cand))}
        if action in (GLOSSARY_TIER_HARD, GLOSSARY_TIER_SOFT):
            # Один термин — одна запись за пачку. Иначе два кандидата разных
            # kind с одной и той же парой писали её дважды, и второй проход
            # затирал prevTgt собственным значением: запись пережила бы откат.
            key = (_scope_of(cand), _norm_key(cand.get("src")))
            if key in taken:
                closed.append((cand, {**row, "tier": None,
                                      "reason": "та же пара уже одобрена в этой пачке"}))
                continue
            taken.add(key)
            picked.append((cand, action, {**row, "tier": action}))
        elif action == "close":
            closed.append((cand, {**row, "tier": None}))
        else:
            bucket = skipped.setdefault(reason, {"reason": reason, "count": 0, "samples": []})
            bucket["count"] += 1
            if len(bucket["samples"]) < 3:
                bucket["samples"].append({"src": row["src"], "tgt": row["tgt"]})

    counts = {
        "verified": sum(1 for _, t, _ in picked if t == GLOSSARY_TIER_HARD),
        "auto": sum(1 for _, t, _ in picked if t == GLOSSARY_TIER_SOFT),
        "closed": len(closed),
        "skipped": sum(b["count"] for b in skipped.values()),
        # pending — по рассмотренному срезу: вердикты считаются только по limit,
        # иначе на большой очереди цифры в панели не сходились бы.
        "pending": len(considered),
        "queueTotal": len(pending),
    }
    result = {
        "ok": True, "dryRun": req.dry_run, "batch": None, "counts": counts,
        "policy": {**pol, "version": AUTO_POLICY_VERSION},
        "scope": list(scope) if scope else None,
        # Чем проверялись термины. Разница в покрытии между парами языков
        # огромна, и назвать её честнее, чем дать пользователю обнаружить
        # её на своих текстах.
        "sources": _authority_sources(scope) if scope else {"dictionaries": [], "corpus": None},
        "corpusChecked": corpus_asked,
        "corpusSkipped": corpus_capped,
        # Разбор без корпуса — это верхняя оценка: при применении часть
        # кандидатов может отсеяться как отсутствующие в целевом языке.
        # Названо явно, чтобы цифра на кнопке не обещала лишнего.
        "corpusPending": (not use_corpus) and bool(prelim),
        "items": [row for _, _, row in picked] + [row for _, row in closed],
        "skipped": sorted(skipped.values(), key=lambda b: -b["count"]),
    }
    if req.dry_run or not (picked or closed):
        return result

    today = datetime.now().strftime("%Y-%m-%d")
    batch = STATE.get("autoBatchSeq", 0) + 1
    STATE["autoBatchSeq"] = batch
    for cand, tier, row in picked:
        row["replaced"] = _auto_write(cand, tier, batch, today)
        cand.update({"status": "approved", "autoBatch": batch, "autoTier": tier,
                     "autoWrote": True, "autoNote": row["reason"], "decidedAt": today})
    for cand, row in closed:
        cand.update({"status": "approved", "autoBatch": batch, "autoWrote": False,
                     "autoNote": row["reason"], "decidedAt": today})
    batches = STATE.setdefault("autoBatches", [])
    batches.insert(0, {"id": batch, "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "counts": counts, "scope": list(scope) if scope else None})
    for gone in batches[AUTO_BATCH_HISTORY:]:
        _forget_auto_batch(gone["id"])
    del batches[AUTO_BATCH_HISTORY:]
    _invalidate_gloss_index()
    save_state(STATE)
    result["batch"] = batch
    return result


@app.post("/api/term-queue/auto-approve/{batch}/undo")
def undo_auto_approve(batch: int):
    """Откатить пачку целиком: созданные записи убрать, заменённые вернуть,
    кандидатов — обратно в очередь. Автоматике, которую нельзя отменить одной
    кнопкой, доверять нельзя."""
    removed, restored = 0, 0
    keep = []
    for g in STATE["glossary"]:
        if g.get("autoBatch") != batch:
            keep.append(g)
            continue
        if g.get("autoCreated"):
            removed += 1
            continue
        g["tgt"] = g.pop("prevTgt", g.get("tgt"))
        g["tier"] = g.pop("prevTier", GLOSSARY_TIER_SOFT)
        g["note"] = g.pop("prevNote", "")
        g["conf"] = g.pop("prevConf", "")
        prev_origin = g.pop("prevOrigin", "")
        if prev_origin:
            g["origin"] = prev_origin
        else:
            g.pop("origin", None)
        for k in ("autoBatch", "autoCreated"):
            g.pop(k, None)
        restored += 1
        keep.append(g)
    STATE["glossary"] = keep
    back = 0
    for c in _term_queue():
        if c.get("autoBatch") == batch:
            c["status"] = "pending"
            for k in ("autoBatch", "autoTier", "autoWrote", "autoNote", "decidedAt"):
                c.pop(k, None)
            back += 1
    STATE["autoBatches"] = [b for b in STATE.get("autoBatches", []) if b.get("id") != batch]
    _invalidate_gloss_index()
    save_state(STATE)
    return {"ok": True, "removed": removed, "restored": restored, "returned": back}


@app.get("/api/term-queue/auto-batches")
def list_auto_batches():
    return {"ok": True, "batches": STATE.get("autoBatches", [])}


# Извлечение терминов из подтверждённых сегментов. Платный прогон: вызывается
# только по кнопке и только по подтверждённым парам.
def _term_extract_system(domain: dict) -> str:
    """Промпт извлечения терминов. Категории и примеры берутся из области:
    список «Anatomy|Cardiology|Dosage» в юридическом проекте бессмыслен."""
    return (
        "You extract bilingual " + domain["en"] + " terminology pairs from confirmed\n"
        "translation segments. Return ONLY a JSON array, no prose.\n\n"
        'Each item: {"src": <term in the source language>, "tgt": <its translation, copied from the\n'
        'target segment>, "cat": <one of ' + "|".join(domain["cats"]) + '>}\n\n'
        "RULES:\n"
        "1. " + domain["extract"] + "\n"
        "2. Give the source term in dictionary form (nominative singular).\n"
        "3. The target side MUST be copied from the segment as written, never invented.\n"
        "4. Skip general vocabulary, numbers, whole sentences, anything longer than 5 words.\n"
        "5. At most 5 pairs per segment. Return [] if the segment has no terminology.\n"
    )


def _extract_terms_call(pairs: list, model: Optional[str] = None,
                        domain_id: Optional[str] = None) -> list:
    """Один вызов модели на пачку сегментов. Возвращает список пар или []."""
    import json as _json
    import openai
    dom = _resolve_domain(domain_id)
    mdl = _resolve_model(model or DEFAULT_OPENAI_MODEL)
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=90, max_retries=1)
    body = "\n\n".join(f"[{i + 1}] SRC: {p[0]}\n    TGT: {p[1]}" for i, p in enumerate(pairs))
    extra = ({"max_completion_tokens": 4096} if mdl["api"] == "modern"
             else {"max_tokens": 1500, "temperature": 0})
    try:
        resp = client.chat.completions.create(
            model=mdl["id"],
            messages=[{"role": "system", "content": _term_extract_system(dom)},
                      {"role": "user", "content": body}],
            **extra,
        )
        _note_usage("terms", mdl["id"], resp)
        raw = (resp.choices[0].message.content or "").strip()
        lo, hi = raw.find("["), raw.rfind("]")
        if lo == -1 or hi <= lo:
            return []
        data = _json.loads(raw[lo:hi + 1])
        return [d for d in data if isinstance(d, dict) and d.get("src") and d.get("tgt")]
    except Exception as e:
        print(f"[backend] term extraction failed: {e}", file=sys.stderr)
        return []


class ExtractTermsRequest(BaseModel):
    segment_ids: Optional[List[int]] = None
    limit: int = 30
    model: Optional[str] = None


@app.post("/api/projects/{pid}/extract-terms")
def extract_terms(pid: int, req: ExtractTermsRequest = ExtractTermsRequest()):
    """Достаёт терминологические пары из подтверждённых сегментов проекта.
    Кладёт их в очередь кандидатов, а не в глоссарий. Обычный def: внутри
    блокирующие вызовы модели (см. batch_translate)."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Извлечение терминов требует ключ OpenAI")
    project = get_project(pid)
    segs = [s for s in project["segments"]
            if s.get("status") == "confirmed" and (s.get("target") or "").strip()]
    if req.segment_ids:
        ids = set(req.segment_ids)
        segs = [s for s in segs if s["id"] in ids]
    # Пара «оригинал+перевод» не менялась с прошлого извлечения — читать нечего
    fresh = []
    skipped_cached = 0
    for sg in segs:
        h = _text_hash((sg.get("source") or "") + "||" + (sg.get("target") or ""))
        if sg.get("extracted_hash") == h:
            skipped_cached += 1
            continue
        sg["_extract_hash"] = h
        fresh.append(sg)
    segs = fresh[:max(1, min(req.limit, 100))]
    if not segs:
        return {"ok": True, "scanned": 0, "skipped_cached": skipped_cached, "candidates": []}
    found = []
    CHUNK = 10
    for i in range(0, len(segs), CHUNK):
        chunk = segs[i:i + CHUNK]
        for item in _extract_terms_call([(s["source"], s["target"]) for s in chunk],
                                        req.model, project.get("domain")):
            _sc = _project_scope(project)
            known = _glossary_entry(item.get("src", ""), _sc)
            if known and _norm_key(known.get("tgt")) == _norm_key(item.get("tgt")):
                continue      # уже знаем ровно эту пару
            c = _queue_term("extract", item.get("src", ""), item.get("tgt", ""),
                            cat=item.get("cat", ""), wasTgt=(known or {}).get("tgt", ""),
                            lang=_sc[0], domain=_sc[1], via="auto",
                            project=pid, model=_resolve_model(req.model or DEFAULT_OPENAI_MODEL)["id"])
            if c:
                found.append(c)
        for sg in chunk:
            sg["extracted_hash"] = sg.pop("_extract_hash", None)
    save_state(STATE)
    return {"ok": True, "scanned": len(segs), "skipped_cached": skipped_cached, "candidates": found}


# ─── Параллельные вызовы внутри порции ───────────────────────────────
# Сегменты порции независимы, а каждый вызов модели — это 3-6 секунд ожидания
# сети, а не работы процессора. Гнать их по одному значит держать паузу длиной
# в прогон: 2670 сегментов по 5 с — почти четыре часа. Считаем параллельно.
#
# Потолок скромный: слишком агрессивная параллельность упирается в rate limit
# провайдера, и вместо ускорения получаются 429 и повторы. RUN_WORKERS можно
# поднять переменной окружения, если лимиты аккаунта позволяют.
RUN_WORKERS = max(1, min(int(os.environ.get("RUN_WORKERS", "6")), 16))


def _run_parallel(items: list, fn):
    """Выполнить fn для каждого элемента, сохранив порядок результатов.
    fn обязана ловить свои исключения сама: одна упавшая пара не должна
    ронять всю порцию."""
    if RUN_WORKERS <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(RUN_WORKERS, len(items)),
                            thread_name_prefix="mcat-run") as pool:
        return list(pool.map(fn, items))


# Флаг «текущий прогон просят остановить». Пакетные циклы сверяются с ним
# после каждого сегмента: раньше остановка ждала конца порции, а это до минуты
# на переводе и несколько минут на ремонте — пользователь считал кнопку мёртвой.
# Прогон один (см. фоновые прогоны), поэтому хватает одной переменной.
_ACTIVE_JOB: dict = {}


def _job_should_stop() -> bool:
    job = _ACTIVE_JOB.get("job")
    return bool(job and job.get("stop"))


def _text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _backcheck_cached(seg: dict, mdl_id: str, use_judge: bool) -> bool:
    """Сегмент уже проверен ЭТИМ переводом — считать нечего.
    Судья вне своей зоны не вызывается, поэтому сегмент за её границами полный
    даже без judged: иначе включённый судья гнал бы весь проект заново.

    Модель здесь НЕ сравнивается, в отличие от termcheck, и это не упущение.
    У обратного перевода нет шкалы «сильнее — лучше»: ему нужна максимально
    буквальная модель, а сильная чинит кривой английский на лету и прячет
    ровно ту ошибку, которую проверка ищет. Значит «проверено другой моделью»
    здесь не хуже и не лучше — это просто проверено, и платить второй раз
    незачем. Кому нужен другой взгляд, тот запускает back-check отдельной
    кнопкой: она идёт со skip_cached=False и проверяет что попросили."""
    bc = seg.get("backcheck") or {}
    # Обрезанный текст: ровно так хеш и записывается. Сравнивая с необрезанным,
    # мы перезапускали бы платную проверку на каждом переводе с висящим пробелом,
    # а интерфейс при этом показывал бы её свежей.
    if bc.get("target_hash") != _text_hash((seg.get("target") or "").strip()):
        return False
    # ...но проверка СВОЕЙ ЖЕ работы проверкой не является. Раз модель здесь
    # больше не сравнивается, остаётся ровно один случай, когда готовый
    # обратный перевод переиспользовать нельзя: его делала та самая модель,
    # которая писала этот текст. Она вернёт свой же замысел, а не то, что
    # в тексте написано, — и на такой оценке стоит автоодобрение глоссария.
    # Раньше это лечилось сменой модели в списке; теперь смена модели ничего
    # не перезапускает, поэтому случай назван явно.
    if bc.get("model") and bc.get("model") == seg.get("provider"):
        return False
    if not use_judge or bc.get("judged"):
        return True
    # Судью не звали осознанно (вне зоны или уже есть объективная находка) —
    # это законченная проверка, а не недоделанная.
    if bc.get("judge_skipped"):
        return True
    lo, hi = JUDGE_ZONE
    score = bc.get("score")
    return score is not None and not (lo <= score <= hi)


def _segment_for_client(seg: dict) -> dict:
    """Сегмент с производными признаками stale/tried. Хеши считаются здесь:
    браузеру sha1 не пересчитать, а без них он не отличит устаревшую проверку
    от актуальной."""
    try:
        out = dict(seg)
    except RuntimeError:
        out = dict(seg)          # правка из фонового потока длится микросекунды
    cur = _text_hash(out.get("target") or "")
    # back-check и termcheck кладут хеш ОБРЕЗАННОГО текста, ремонт — сырого.
    # Сравнивать надо тем же способом, каким писали: иначе перевод с висящим
    # пробелом показывался бы в UI устаревшим, а _machine_clean считал бы его
    # свежим и пускал бы в глоссарий.
    cur_trimmed = _text_hash((out.get("target") or "").strip())
    bc, tc, rp = out.get("backcheck"), out.get("termcheck"), out.get("repair")
    qa = out.get("qa_result")
    if bc:
        out["backcheck"] = {**bc, "stale": bc.get("target_hash") != cur_trimmed}
    if tc:
        out["termcheck"] = {**tc, "stale": tc.get("target_hash") != cur_trimmed}
    if qa:
        # Тот же признак и у Medical QA: без него карточка прогона показывала
        # весь проект и после того, как всё уже проверено. Хеш sha1 браузеру
        # не посчитать, поэтому производную считаем здесь.
        out["qa_result"] = {**qa, "stale": qa.get("target_hash") != cur_trimmed}
    if rp:
        out["repair"] = {**rp, "tried": rp.get("source_hash") == cur}
    return out


def _project_for_client(project: dict) -> dict:
    """Копия проекта с производными признаками у каждого сегмента."""
    return {**project, "segments": [_segment_for_client(s) for s in list(project["segments"])]}


def _backcheck_model(seg: dict, requested: Optional[str]) -> str:
    """Модель обратного перевода для ЭТОГО сегмента.

    Обратный перевод моделью-автором текста — не проверка: она вернёт свой
    замысел, а не то, что в тексте написано, и _backcheck_cached такой
    результат действительным не признаёт. Раньше совпадение просто повторяло
    вызов той же моделью: прогон платил при каждом запуске, а зачётной
    проверки не получал никогда — вечная переплата за недействительный
    результат. Совпала — берём запасную, столь же буквальную и дешёвую."""
    mid = _resolve_model(requested or BACKCHECK_DEFAULT_MODEL)["id"]
    provider = seg.get("provider") or ""
    if mid != provider:
        return mid
    for alt in (BACKCHECK_DEFAULT_MODEL, BACKCHECK_FALLBACK_MODEL):
        if alt != provider:
            return alt
    return mid          # недостижимо: две запасных не совпадают между собой


def _run_segment_backcheck(seg: dict, project: dict, model: Optional[str] = None,
                           use_judge: bool = False, judge_model: Optional[str] = None,
                           harvest: bool = True) -> dict:
    """Обратный перевод сегмента + оценка соответствия оригиналу.
    Результат кладётся в seg['backcheck'] вместе с хешем перевода — по нему
    повторный прогон понимает, что пересчитывать нечего."""
    target_text = (seg.get("target") or "").strip()
    if not target_text:
        return {"ok": False, "error": "Сегмент ещё не переведён"}

    mdl_id = _backcheck_model(seg, model)
    back = ""
    try:
        # Обратный перевод делает ДРУГАЯ модель, а не бесплатный движок: на нём
        # весь смысл проверки. Движок переводил дословно и одинаково хорошо
        # возвращал и верный термин, и кальку — балл получался ни о чём.
        back = _openai_translate(target_text, project["tgt"], project["src"],
                                 model=mdl_id, literal=True)
    except Exception as e:
        print(f"[backend] backcheck seg#{seg.get('id')}: {e}", file=sys.stderr)
        return {"ok": False, "error": str(e)}

    if not (back or "").strip():
        return {"ok": False, "error": "Обратный перевод не получен"}

    source_text = seg.get("source", "")
    gloss_hits, _tm = _get_context(source_text, project=project)
    # semantic_fn, а не готовое число: косинус учитывается только при отсутствии
    # жёстких находок, и там, где он всё равно не повлияет, платить за эмбеддинги
    # незачем. Решение принимает medical_qa — он и знает состав находок.
    res = (medical_qa_mod.run_backcheck(
        source_text, back, gloss_hits,
        semantic_fn=lambda: _semantic_similarity(source_text, back),
        domain=project.get("domain"), src_lang=project.get("src", "RU")) if medical_qa_mod else {})

    # Судья — только для средней зоны: наверху и внизу шкалы вопрос уже решён.
    judged, judge_skipped = False, None
    if use_judge and medical_qa_mod and res.get("score") is not None:
        lo, hi = JUDGE_ZONE
        if not (lo <= res["score"] <= hi):
            judge_skipped = "zone"
        elif res.get("hard"):
            # Объективное расхождение (числа, единицы, отрицание, сторона) уже
            # найдено детерминированно. Судья такую находку отменить не может —
            # его вердикт ничего не изменит, а вызов стоит денег.
            judge_skipped = "hard"
        else:
            verdict = _openai_judge(source_text, back, judge_model,
                                    project.get("domain"), project.get("src", "RU"))
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
        "judge_skipped": judge_skipped,
        "target_hash": _text_hash(target_text),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # Обе оценки на месте — можно собрать терминологию без участия человека.
    # Порядок прогонов пользователь выбирает сам, поэтому сбор висит на обоих.
    harvested = _harvest_if_clean(seg, project) if harvest else []
    return {"ok": True, "back": back, "backcheck": seg["backcheck"],
            "queued": [c["id"] for c in harvested]}


def _termcheck_cached(seg: dict, mdl_id: str) -> bool:
    """Тот же перевод уже разобран моделью НЕ СЛАБЕЕ запрошенной — платить
    второй раз незачем.

    Сравнение по рангу, а не по равенству id: у проверки терминов шкала есть,
    и вердикт сильной модели слабой не перезаписывается. Иначе достаточно было
    сменить модель в выпадающем списке, чтобы тысяча уже проверенных Sol
    сегментов ушла на перепроверку Terra — оплаченную и худшую по качеству.
    Обратное направление разрешено: усилить проверку можно всегда."""
    tc = seg.get("termcheck") or {}
    if tc.get("target_hash") != _text_hash((seg.get("target") or "").strip()):
        return False
    # Пропущенный как «нечего проверять» не зависит от модели — пересчитывать нечего
    if tc.get("model") == "skip":
        return True
    return _rank_not_weaker(tc.get("model") or "", mdl_id)


def _termcheck_trivial(source: str, target: str) -> Optional[str]:
    """Сегменты, где проверять нечего, — без вызова модели.
    Терминов не бывает там, где нет слов; а совпадение перевода с оригиналом
    (числа, латинские обозначения, «IFN-γ») — это не терминологическая ошибка."""
    if not re.search(r"[A-Za-zА-Яа-яЁё]{3}", target or ""):
        return "в переводе нет слов — только числа или обозначения"
    if _norm_key(source) == _norm_key(target):
        return "перевод совпадает с оригиналом — переводить нечего"
    return None


def _run_segment_termcheck(seg: dict, project: dict, model: Optional[str] = None,
                           harvest: bool = True) -> dict:
    """Проверка терминологии перевода + кандидаты в глоссарий из находок.

    Находка с предложенной заменой — это готовая пара «термин оригинала →
    правильный термин», то есть ровно то, что нужно глоссарию. Кладём её в ту
    же очередь кандидатов, что и расхождения при подтверждении: одно место,
    где человек принимает терминологические решения."""
    target = (seg.get("target") or "").strip()
    if not target:
        return {"ok": False, "error": "Сегмент ещё не переведён"}
    trivial = _termcheck_trivial(seg.get("source", ""), target)
    if trivial:
        seg["termcheck"] = {"findings": [], "severity": "none", "model": "skip",
                            "note": trivial,
                            "domain": _resolve_domain(project.get("domain"))["id"],
                            "target_hash": _text_hash(target),
                            "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        return {"ok": True, "termcheck": seg["termcheck"], "queued": [], "skipped": trivial}
    res = _openai_termcheck(seg.get("source", ""), target,
                            project.get("src", "RU"), project.get("tgt", "EN"),
                            project.get("domain"), model)
    if res is None:
        return {"ok": False, "error": "Модель не ответила"}
    findings = res["findings"]
    worst = next((sev for sev in TERMCHECK_SEVERITY
                  if any(f["severity"] == sev for f in findings)), "none")
    queued = []
    for f in findings:
        # В глоссарий просятся только уверенные находки с обеими сторонами пары
        if f["severity"] in ("critical", "major") and f["src_term"] and f["suggestion"]:
            _sc = _project_scope(project)
            c = _queue_term("audit", f["src_term"], f["suggestion"],
                            wasTgt=f["tgt_term"], project=project["id"], segment=seg["id"],
                            lang=_sc[0], domain=_sc[1], via="auto",
                            note=f["why"], model=res["model"],
                            sampleSrc=seg.get("source", "")[:240], sampleTgt=target[:240])
            if c:
                queued.append(c["id"])
    seg["termcheck"] = {
        "findings": findings,
        "severity": worst,
        "model": res["model"],
        "domain": _resolve_domain(project.get("domain"))["id"],
        "target_hash": _text_hash(target),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if harvest:
        queued += [c["id"] for c in _harvest_if_clean(seg, project)]
    return {"ok": True, "termcheck": seg["termcheck"], "queued": queued}


class TermcheckRequest(BaseModel):
    model: Optional[str] = None


@app.post("/api/segments/{pid}/{sid}/termcheck")
def termcheck_segment(pid: int, sid: int, req: TermcheckRequest = TermcheckRequest()):
    """Обычный def: внутри блокирующий вызов модели (см. batch_translate)."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Проверка терминологии требует ключ OpenAI")
    seg = get_segment(pid, sid)
    project = get_project(pid)
    result = _run_segment_termcheck(seg, project, req.model)
    if result.get("ok"):
        save_state(STATE)
        return result
    raise HTTPException(502, result.get("error", "Проверка не удалась"))


class TermcheckBatchRequest(BaseModel):
    segment_ids: Optional[List[int]] = None
    limit: int = 10
    model: Optional[str] = None
    skip_cached: bool = True


@app.post("/api/projects/{pid}/termcheck/batch")
def termcheck_batch(pid: int, req: TermcheckBatchRequest):
    """Порционно, как back-check: клиент гоняет порции по 10, чтобы один
    запрос не жил дольше таймаута прокси."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Проверка терминологии требует ключ OpenAI")
    project = get_project(pid)
    id_filter = set(req.segment_ids) if req.segment_ids is not None else None
    mdl_id = _resolve_model(req.model or TERMCHECK_DEFAULT_MODEL)["id"]

    candidates, skipped_cached = [], 0
    for seg in project["segments"]:
        if id_filter is not None and seg["id"] not in id_filter:
            continue
        if not (seg.get("target") or "").strip():
            continue
        if req.skip_cached and _termcheck_cached(seg, mdl_id):
            skipped_cached += 1
            continue
        candidates.append(seg)

    limit = max(1, min(req.limit, 100))
    remaining_after = max(0, len(candidates) - limit)
    targets = candidates[:limit]

    processed, errors, flagged = [], [], 0
    groups: dict = {}
    order: list = []
    for seg in targets:
        pair = (_norm_key(seg.get("source")), _norm_key(seg.get("target")))
        if pair not in groups:
            groups[pair] = []
            order.append(pair)
        groups[pair].append(seg)
    duplicates, skipped_trivial = 0, 0

    def _tc_one(pair):
        seg = groups[pair][0]
        if _job_should_stop():
            return {"pair": pair, "skip": True}
        try:
            r = _run_segment_termcheck(seg, project, req.model)
            return {"pair": pair, "ok": bool(r.get("ok")), "error": r.get("error"),
                    "trivial": bool(r.get("skipped"))}
        except Exception as e:
            print(f"[backend] termcheck batch seg#{seg['id']}: {e}", file=sys.stderr)
            return {"pair": pair, "ok": False, "error": str(e)}

    for res in _run_parallel(order, _tc_one):
        segs = groups[res["pair"]]
        if res.get("skip"):
            continue
        if not res.get("ok"):
            errors.append({"id": segs[0]["id"], "error": res.get("error", "unknown")})
            continue
        lead = segs[0]
        processed.append(lead["id"])
        if res.get("trivial"):
            skipped_trivial += 1
        if lead["termcheck"]["findings"]:
            flagged += 1
        for sg in segs[1:]:
            sg["termcheck"] = json.loads(json.dumps(lead["termcheck"]))
            processed.append(sg["id"])
            duplicates += 1
            if sg["termcheck"]["findings"]:
                flagged += 1
    save_state(STATE)
    return {"ok": True, "processed": processed, "count": len(processed),
            "flagged": flagged, "remaining": remaining_after,
            "skipped_cached": skipped_cached, "duplicates": duplicates,
            "skipped_trivial": skipped_trivial, "errors": errors, "model": mdl_id}


# ─── Автоматический ремонт сегмента ──────────────────────────────────
# Чинит по КОНКРЕТНЫМ находкам, а не «переведи получше»: список претензий
# приходит из back-check (числа, единицы, отрицания, потерянные термины,
# вердикт судьи) и из проверки терминологии (кальки с предложенной заменой).
#
# Три предохранителя, без которых цикл начинает угождать метрике:
#   1. чиним только проверяемые претензии — «часть текста не совпала дословно»
#      это шум, по нему ремонтировать нечего;
#   2. после ремонта перепроверяем ТЕМИ ЖЕ проверками и оставляем новый текст,
#      только если стало лучше, иначе откат;
#   3. статус после ремонта — review, не confirmed: заверяет человек.
REPAIR_HARD_REASONS = ("расхождение чисел", "расхождение единиц", "инверсия отрицания",
                       "подмена на противоположное", "обратный перевод про другое",
                       "потерян термин")


def _gloss_misses(seg: dict, project: Optional[dict]) -> list:
    """Расхождения с ПРОВЕРЕННЫМИ записями глоссария: термин есть в оригинале,
    утверждённого варианта в переводе нет.

    Считается ровно так же, как в /glossary-impact, и по тем же `verified`:
    если ремонт и отчёт о соответствии разойдутся в том, что считать
    нарушением, они начнут переписывать сегменты друг за другом по кругу.
    Устаревать тут нечему — сверяется текущий текст с текущим глоссарием."""
    if project is None:
        return []
    target = (seg.get("target") or "").strip()
    if not target:
        return []
    out = []
    hits, _tm = _get_context(seg.get("source", ""), with_tm=False, project=project)
    for h in hits:
        if _hit_tier(h) != GLOSSARY_TIER_HARD or not h.get("tgt"):
            continue
        if _tgt_has_term(target, h["tgt"]):
            continue
        out.append({"kind": "gloss", "use": h["tgt"], "src": h["src"],
                    "text": "утверждённый перевод термина «" + h["src"] + "» — «"
                            + h["tgt"] + "», в переводе его нет"})
    return out


def _repair_findings(seg: dict, project: Optional[dict] = None) -> list:
    """Претензии к ТЕКУЩЕМУ переводу. Устаревшие проверки (перевод правили
    после них) игнорируем — чинить по ним нечего.

    Соответствие глоссарию входит сюда наравне с проверками: цель ремонта —
    привести перевод в порядок целиком, а не по одной подсистеме. Без этого
    ремонт и кнопка «Соответствие глоссарию» чинили сегмент по очереди, каждый
    затирая работу другого."""
    # По ОБРЕЗАННОМУ тексту: back-check и termcheck пишут хеш именно так
    # (см. _check_stale и соседей). Сравнение с необрезанным означало, что
    # у перевода с висящим пробелом находок «нет» — сегмент молча выпадал
    # из ремонта, из корзины «с замечаниями» и из отчёта, а на экране
    # проверки числились свежими. Хеш ремонта (repair.source_hash) остаётся
    # сырым: его так же сырым и пишут.
    cur = _text_hash((seg.get("target") or "").strip())
    items = _gloss_misses(seg, project)
    bc = seg.get("backcheck") or {}
    if bc and bc.get("target_hash") == cur:
        for t in (bc.get("terms_lost") or []):
            items.append({"kind": "term_lost", "must": t,
                          "text": "термин «" + t + "» не пережил обратный перевод"})
        for r in (bc.get("reasons") or []):
            if any(h in r for h in REPAIR_HARD_REASONS):
                items.append({"kind": "backcheck", "text": r})
        j = bc.get("judge") or {}
        if j.get("severity") in ("major", "critical"):
            for d in (j.get("divergences") or []):
                items.append({"kind": "judge", "text": str(d)})
            if j.get("comment"):
                items.append({"kind": "judge", "text": j["comment"]})
    tc = seg.get("termcheck") or {}
    if tc and tc.get("target_hash") == cur:
        for f in (tc.get("findings") or []):
            if f.get("severity") in ("critical", "major"):
                items.append({"kind": "term", "replace": [f.get("tgt_term", ""), f.get("suggestion", "")],
                              "text": "«" + f.get("tgt_term", "") + "»"
                                      + (" → «" + f["suggestion"] + "»" if f.get("suggestion") else "")
                                      + (" — " + f["why"] if f.get("why") else "")})
    seen, out = set(), []
    for i in items:
        if i["text"] not in seen:
            seen.add(i["text"])
            out.append(i)
    return out


def _repair_tried(seg: dict) -> bool:
    """Этот же текст уже пытались чинить — второй заход по тем же претензиям
    даёт то же самое и стоит тех же денег."""
    r = seg.get("repair") or {}
    return r.get("source_hash") == _text_hash(seg.get("target") or "")


def _repairable(seg: dict, allow_tried: bool = False, project: Optional[dict] = None) -> bool:
    """allow_tried — человек сам отметил галочкой уже чинившиеся сегменты.
    По умолчанию второй заход по тому же тексту не делаем: те же претензии
    дадут тот же результат за те же деньги."""
    if not (seg.get("target") or "").strip() or not _repair_findings(seg, project):
        return False
    return allow_tried or not _repair_tried(seg)


def _repair_system(dom: dict, src_lang: str, tgt_lang: str) -> str:
    return (
        "You are a senior " + dom["expert"] + ". You are given a SOURCE text in " + src_lang
        + ", its TRANSLATION into " + tgt_lang + ", and a list of ISSUES found by quality control.\n\n"
        "Fix ONLY the listed issues. This is a repair, not a retranslation.\n"
        "RULES:\n"
        "1. Return ONLY the corrected translation — no explanations, no comments, no quotes.\n"
        "2. Change as little as possible: keep every wording that is not part of an issue.\n"
        "3. Required replacements must be applied exactly as given.\n"
        "4. Terms reported as lost MUST be present in the corrected translation.\n"
        "5. Keep all numbers, units, negations and abbreviations exactly as in the SOURCE.\n"
        "6. Use " + dom["terminology"] + ". Output must be 100% " + tgt_lang + ".\n"
        "7. If an issue looks wrong to you, leave that part unchanged rather than inventing something new.\n"
    )


def _openai_repair(seg: dict, project: dict, findings: list, model: Optional[str]) -> Optional[str]:
    import openai
    dom = _resolve_domain(project.get("domain"))
    mdl = _resolve_model(model or REPAIR_DEFAULT_MODEL)
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=120, max_retries=1)
    lines = []
    for i, f in enumerate(findings, 1):
        lines.append(str(i) + ". " + f["text"])
        if f.get("replace") and f["replace"][1]:
            lines.append('   REQUIRED: replace "' + f["replace"][0] + '" with "' + f["replace"][1] + '"')
        if f.get("must"):
            lines.append('   REQUIRED: the translation must convey "' + f["must"] + '"')
        if f.get("use"):
            lines.append('   REQUIRED: use exactly this approved term: "' + f["use"] + '"')
    body = ("SOURCE:\n" + seg.get("source", "") + "\n\nTRANSLATION:\n" + (seg.get("target") or ""))
    # Проверенные записи глоссария кладём в промпт ЦЕЛИКОМ, а не только те, что
    # нарушены: чиня одно, модель свободно переписывала соседний утверждённый
    # термин — и сегмент возвращался в отчёт о соответствии уже по другой строке.
    approved = [h for h in _get_context(seg.get("source", ""), with_tm=False, project=project)[0]
                if _hit_tier(h) == GLOSSARY_TIER_HARD and h.get("tgt")]
    if approved:
        body += ("\n\nAPPROVED GLOSSARY for this segment — these exact translations must be "
                 "present in the corrected text:\n"
                 + "\n".join("  " + h["src"] + " → " + h["tgt"] for h in approved))
    back = ((seg.get("backcheck") or {}).get("back") or "").strip()
    if back:
        body += ("\n\nBACK-TRANSLATION of the current translation (for reference — it shows how the "
                 "translation reads to a reviewer):\n" + back)
    body += "\n\nISSUES:\n" + "\n".join(lines)
    extra = ({"max_completion_tokens": 4096} if mdl["api"] == "modern"
             else {"max_tokens": 1500, "temperature": 0})
    try:
        resp = client.chat.completions.create(
            model=mdl["id"],
            messages=[{"role": "system", "content": _repair_system(dom, project.get("src", "RU"), project.get("tgt", "EN"))},
                      {"role": "user", "content": body}],
            **extra,
        )
        _note_usage("repair", mdl["id"], resp)
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[backend] repair failed seg#{seg.get('id')}: {e}", file=sys.stderr)
        return None


def _repair_scores(seg: dict, project: Optional[dict] = None) -> dict:
    """Снимок качества сегмента: балл back-check, число серьёзных замечаний
    по терминам и число нарушенных утверждённых терминов. По нему решаем,
    стало ли лучше. Глоссарий считается всегда: это единственная из трёх
    оценок, которая не стоит ни одного вызова модели."""
    bc = seg.get("backcheck") or {}
    tc = seg.get("termcheck") or {}
    # terms = None, если проверка этого текста не видела: ноль замечаний
    # у непроверенного текста — не «чисто», а «неизвестно». Сравнение с таким
    # нулём откатывало бы верную правку из-за унаследованной проблемы.
    fresh_tc = bool(tc) and not _check_stale(tc, seg.get("target") or "")
    return {
        "score": bc.get("score"),
        "terms": (len([f for f in (tc.get("findings") or [])
                       if f.get("severity") in ("critical", "major")])
                  if fresh_tc else None),
        "gloss": len(_gloss_misses(seg, project)),
    }


def _run_segment_repair(seg: dict, project: dict, model: Optional[str] = None,
                        bc_model: Optional[str] = None, tc_model: Optional[str] = None,
                        use_judge: bool = False, judge_model: Optional[str] = None) -> dict:
    """Один заход ремонта с обязательной перепроверкой и откатом."""
    findings = _repair_findings(seg, project)
    if not findings:
        return {"ok": False, "error": "Нет находок, по которым можно чинить"}
    old_target = seg.get("target") or ""
    old_hash = _text_hash(old_target)
    had_bc = any(f["kind"] in ("term_lost", "backcheck", "judge") for f in findings)
    had_gloss = any(f["kind"] == "gloss" for f in findings)
    # Правка ради глоссария меняет формулировку, и проверить её обязан кто-то,
    # кроме самой правки. Termcheck смотрит только на целевой текст и стоит один
    # вызов — без него подстановка термина принималась бы на веру: сравнивать
    # было бы нечего, обе оценки остались бы от прежнего текста.
    had_tc = any(f["kind"] == "term" for f in findings) or had_gloss
    before = _repair_scores(seg, project)
    # Проверки старого текста сохраняем целиком: при откате их надо вернуть,
    # иначе сегмент окажется «непроверенным» и человек заплатит за прогон снова.
    bc_before = json.loads(json.dumps(seg.get("backcheck"))) if seg.get("backcheck") else None
    tc_before = json.loads(json.dumps(seg.get("termcheck"))) if seg.get("termcheck") else None

    new_target = _openai_repair(seg, project, findings, model)
    if not new_target:
        return {"ok": False, "error": "Модель не вернула исправленный текст"}
    if _norm_key(new_target) == _norm_key(old_target):
        seg["repair"] = {"applied": False, "reason": "Модель не нашла, что менять",
                         "source_hash": old_hash, "model": _resolve_model(model or REPAIR_DEFAULT_MODEL)["id"],
                         "issues": [f["text"] for f in findings],
                         "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        return {"ok": True, "applied": False, "repair": seg["repair"]}

    # Перепроверяем ровно теми проверками, которые ругались. Лишних не гоняем.
    seg["target"] = new_target
    # harvest=False: вердикт «лучше/хуже» ещё не вынесен, и repair.applied не
    # проставлен. Собирать терминологию с текста, который через две строки
    # может быть откачен, — значит закрепить в глоссарии отменённую правку.
    if had_bc:
        _run_segment_backcheck(seg, project, bc_model, use_judge, judge_model, harvest=False)
    if had_tc:
        _run_segment_termcheck(seg, project, tc_model, harvest=False)
    after = _repair_scores(seg, project)

    better = True
    why = []
    if had_bc and before["score"] is not None and after["score"] is not None:
        if after["score"] < before["score"]:
            better = False
            why.append("балл back-check упал " + str(before["score"]) + " → " + str(after["score"]))
    if had_tc and after["terms"] is None:
        # Перепроверка не состоялась (вызов упал) — подтвердить правку нечем.
        # Откат: автоправка не заверяет сама себя, и «проверка не ответила»
        # это не «проверка сказала, что всё хорошо».
        better = False
        why.append("перепроверка терминов не выполнилась")
    elif had_tc and before["terms"] is not None and after["terms"] > before["terms"]:
        better = False
        why.append("замечаний по терминам стало больше " + str(before["terms"]) + " → " + str(after["terms"]))
    elif had_tc and before["terms"] is None:
        # Сравнивать не с чем: до правки termcheck этого текста не видел.
        # Тогда отвечаем за то, что сделали сами, — откатываем, только если
        # замечание пришло НА ПОДСТАВЛЕННЫЙ термин. Чужая, унаследованная
        # проблема не повод выбрасывать верную правку вместе с оплаченной
        # проверкой; её увидит человек на экране итогов.
        inserted = {_norm_key(f["use"]) for f in findings if f.get("use")}
        hit = next((f for f in ((seg.get("termcheck") or {}).get("findings") or [])
                    if f.get("severity") in ("critical", "major")
                    and _norm_key(f.get("tgt_term")) in inserted), None)
        if hit:
            better = False
            why.append("подставленный термин «%s» забракован проверкой"
                       % hit.get("tgt_term", ""))
    # Глоссарий сверяем независимо от того, из-за него ли чинили: правка одного
    # места не должна выбивать утверждённый термин в другом. Проверка бесплатна,
    # поэтому идёт всегда.
    if after["gloss"] > before["gloss"]:
        better = False
        why.append("нарушено утверждённых терминов больше "
                   + str(before["gloss"]) + " → " + str(after["gloss"]))

    mdl_id = _resolve_model(model or REPAIR_DEFAULT_MODEL)["id"]
    if not better:
        # Откат вместе с проверками: они уже пересчитаны под отвергнутый текст,
        # возвращаем те, что относились к прежнему переводу
        seg["target"] = old_target
        if had_bc:
            seg["backcheck"] = bc_before if bc_before else seg.pop("backcheck", None)
        if had_tc:
            seg["termcheck"] = tc_before if tc_before else seg.pop("termcheck", None)
        for key in ("backcheck", "termcheck"):
            if seg.get(key) is None:
                seg.pop(key, None)
        seg["repair"] = {"applied": False, "reason": "; ".join(why) or "не стало лучше",
                         "source_hash": old_hash, "model": mdl_id, "candidate": new_target,
                         "issues": [f["text"] for f in findings], "before": before, "after": after,
                         "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        return {"ok": True, "applied": False, "repair": seg["repair"]}

    seg["prevTarget"] = old_target
    seg["status"] = "review"          # заверяет человек, автоправка себя не подтверждает
    # Чинили заверенный перевод — отметка «подтвердил человек» относилась к
    # прежнему тексту. Оставить её на новом значит соврать и себе (автоодобрение
    # считает такие сегменты доказательством), и пользователю.
    seg.pop("confirmedBy", None)
    seg.pop("confirmedAt", None)
    seg["provider"] = mdl_id
    seg["repair"] = {"applied": True, "from": old_target, "source_hash": _text_hash(new_target),
                     "model": mdl_id, "issues": [f["text"] for f in findings],
                     "before": before, "after": after,
                     "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    return {"ok": True, "applied": True, "repair": seg["repair"], "target": new_target}


class RepairRequest(BaseModel):
    model: Optional[str] = None
    bc_model: Optional[str] = None
    tc_model: Optional[str] = None
    use_judge: bool = False
    judge_model: Optional[str] = None


@app.post("/api/segments/{pid}/{sid}/repair")
def repair_segment(pid: int, sid: int, req: RepairRequest = RepairRequest()):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Ремонт требует ключ OpenAI")
    seg = get_segment(pid, sid)
    project = get_project(pid)
    result = _run_segment_repair(seg, project, req.model, req.bc_model, req.tc_model,
                                 req.use_judge, req.judge_model)
    if result.get("ok"):
        save_state(STATE)
        return result
    raise HTTPException(502, result.get("error", "Ремонт не удался"))


class RepairBatchRequest(BaseModel):
    segment_ids: Optional[List[int]] = None
    limit: int = 5
    retry: bool = False          # чинить и то, что уже пытались чинить
    # Подтверждённые сегменты пакетный ремонт не трогает: он переписывает текст,
    # а молча переписать заверенный человеком перевод нельзя — то же правило,
    # что у переперевода по глоссарию. Одиночный ремонт по кнопке на сегменте
    # остаётся явным выбором и разрешён.
    include_confirmed: bool = False
    model: Optional[str] = None
    bc_model: Optional[str] = None
    tc_model: Optional[str] = None
    use_judge: bool = False
    judge_model: Optional[str] = None


@app.post("/api/projects/{pid}/repair/batch")
def repair_batch(pid: int, req: RepairBatchRequest):
    """Порция маленькая (5): на сегмент уходит вызов ремонта плюс перепроверка,
    это самый дорогой прогон в системе."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(503, "Ремонт требует ключ OpenAI")
    project = get_project(pid)
    id_filter = set(req.segment_ids) if req.segment_ids is not None else None
    candidates = [s for s in project["segments"]
                  if (id_filter is None or s["id"] in id_filter)
                  and (req.include_confirmed or s.get("status") != "confirmed")
                  and _repairable(s, req.retry, project)]
    skipped_confirmed = ([s["id"] for s in project["segments"]
                          if (id_filter is None or s["id"] in id_filter)
                          and s.get("status") == "confirmed"
                          and _repairable(s, req.retry, project)]
                         if not req.include_confirmed else [])
    limit = max(1, min(req.limit, 30))
    remaining_after = max(0, len(candidates) - limit)
    targets = candidates[:limit]

    applied, skipped, errors = [], [], []

    def _repair_one(seg):
        if _job_should_stop():
            return {"seg": seg, "skip": True}
        try:
            r = _run_segment_repair(seg, project, req.model, req.bc_model, req.tc_model,
                                    req.use_judge, req.judge_model)
            return {"seg": seg, "res": r}
        except Exception as e:
            print(f"[backend] repair batch seg#{seg['id']}: {e}", file=sys.stderr)
            return {"seg": seg, "error": str(e)}

    for out in _run_parallel(targets, _repair_one):
        seg = out["seg"]
        if out.get("skip"):
            continue
        if out.get("error"):
            errors.append({"id": seg["id"], "error": out["error"]})
            continue
        r = out["res"]
        if not r.get("ok"):
            errors.append({"id": seg["id"], "error": r.get("error", "unknown")})
        elif r.get("applied"):
            applied.append(seg["id"])
        else:
            skipped.append({"id": seg["id"], "reason": (r.get("repair") or {}).get("reason", "")})
    save_state(STATE)
    return {"ok": True, "applied": applied, "count": len(applied), "skipped": skipped,
            "remaining": remaining_after, "errors": errors,
            # Молчаливых потолков не бывает: подтверждённые, которые есть что чинить,
            # называем поимённо, а не выбрасываем как будто их не было.
            "skipped_confirmed": skipped_confirmed,
            "model": _resolve_model(req.model or REPAIR_DEFAULT_MODEL)["id"]}


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
    if not os.environ.get("OPENAI_API_KEY"):
        # 503 отдаём до работы, как это делают termcheck и ремонт: иначе
        # обратный перевод вырождается в посегментные ошибки, и составной
        # прогон принимает их за «порция целиком провалилась».
        raise HTTPException(503, "Back-check требует ключ OpenAI")
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
        if req.skip_cached and _backcheck_cached(s, mdl_id, req.use_judge):
            skipped_cached += 1
            continue
        candidates.append(s)

    limit = max(1, min(req.limit, 100))
    remaining_after = max(0, len(candidates) - limit)
    targets = candidates[:limit]

    processed, errors = [], []
    # Одинаковая пара «оригинал + перевод» даёт одинаковый результат: считаем раз,
    # а сами уникальные пары проверяем параллельно.
    groups: dict = {}
    order: list = []
    for seg in targets:
        pair = (_norm_key(seg.get("source")), _norm_key(seg.get("target")))
        if pair not in groups:
            groups[pair] = []
            order.append(pair)
        groups[pair].append(seg)
    duplicates = 0

    def _bc_one(pair):
        seg = groups[pair][0]
        if _job_should_stop():
            return {"pair": pair, "skip": True}
        try:
            r = _run_segment_backcheck(seg, project, req.model, req.use_judge, req.judge_model)
            return {"pair": pair, "ok": bool(r.get("ok")), "error": r.get("error")}
        except Exception as e:
            print(f"[backend] backcheck batch seg#{seg['id']}: {e}", file=sys.stderr)
            return {"pair": pair, "ok": False, "error": str(e)}

    for res in _run_parallel(order, _bc_one):
        segs = groups[res["pair"]]
        if res.get("skip"):
            continue
        if not res.get("ok"):
            errors.append({"id": segs[0]["id"], "error": res.get("error", "unknown")})
            continue
        processed.append(segs[0]["id"])
        for sg in segs[1:]:
            sg["backtranslated_ru"] = segs[0].get("backtranslated_ru", "")
            sg["backcheck"] = json.loads(json.dumps(segs[0]["backcheck"]))
            processed.append(sg["id"])
            duplicates += 1
    save_state(STATE)
    return {
        "ok": True,
        "processed": processed,
        "count": len(processed),
        "remaining": remaining_after,
        "skipped_cached": skipped_cached,
        "duplicates": duplicates,
        "errors": errors,
        "model": mdl_id,
    }


class MedicalQARequest(BaseModel):
    run_backcheck: bool = True
    bc_model: Optional[str] = None


def _segment_medical_qa(pid: int, sid: int, run_backcheck: bool = True,
                        bc_model: Optional[str] = None) -> dict:
    if not medical_qa_mod:
        raise HTTPException(500, "medical_qa module unavailable")

    seg = get_segment(pid, sid)
    project = get_project(pid)
    source_text = seg.get("source", "")
    target_text = seg.get("target", "").strip()
    if not target_text:
        return {"ok": False, "error": "Segment is not translated yet", "segment": seg}

    gloss_hits, tm_hit = _get_context(source_text, project=project)
    back = seg.get("backtranslated_ru", "")

    if run_backcheck and medical_qa_enabled():
        fresh = seg.get("backcheck") or {}
        if fresh.get("back") and fresh.get("target_hash") == _text_hash(target_text):
            # Обратный перевод для этого же текста уже есть — второй раз не платим
            back = fresh["back"]
        else:
            try:
                # literal=True обязателен: обычный промпт «чинит» кривой
                # английский на лету и прячет ошибку, которую QA ищет.
                #
                # Модель — та же, что у back-check, и это не косметика. Без
                # явного указания сюда подставлялась модель перевода по
                # умолчанию: тот же самый вызов стоил впятеро дороже нужного
                # и делался моделью, которую для обратного перевода никто
                # не выбирал. У этой работы одна правильная модель — самая
                # буквальная и дешёвая, та же, что у back-check. Совпадение
                # с автором текста разрешается тем же _backcheck_model.
                back = _openai_translate(target_text, project["tgt"], project["src"],
                                         model=_backcheck_model(seg, bc_model),
                                         literal=True, step="medical_qa")
            except Exception as e:
                print(f"[backend] medical QA backcheck skipped: {e}", file=sys.stderr)

    qa_result = medical_qa_mod.run_medical_qa(
        source_text,
        target_text,
        backtranslated_ru=back,
        glossary_matches=gloss_hits,
        tm_match=tm_hit,
        engine_qa="medical_qa_mvp",
        domain=project.get("domain"),
        src_lang=project.get("src", "RU"),
        tgt_lang=project.get("tgt", "EN"),
    )

    seg["backtranslated_ru"] = qa_result["literal_backcheck"]["backtranslated_ru"]
    # Хеш текста — как у back-check и termcheck: по нему повторный прогон
    # понимает, что пересчитывать нечего. Без него Medical QA брала В КАЖДЫЙ
    # прогон все переведённые сегменты, и составная кнопка всегда показывала
    # полный проект, сколько бы раз её ни нажимали.
    #
    # Но ставим отметку ТОЛЬКО если проверка была полной: без обратного перевода
    # часть находок не считается вовсе, и закэшировать такой результат значит
    # закрыть сегмент от нормальной проверки навсегда.
    if (back or "").strip():
        qa_result["target_hash"] = _text_hash(target_text)
    seg["qa_result"] = qa_result
    seg["qa_issues"] = qa_result["qa_issues"]
    seg["qa"] = qa_result["ui_issues"]
    seg["term_candidates"] = qa_result["term_candidates"]
    seg["risk_score"] = qa_result["risk_score"]
    seg["risk_color"] = qa_result["risk_color"]
    seg["engine_qa"] = qa_result["engine_qa"]
    seg["medical_qa_enabled"] = medical_qa_enabled()

    # Статус проверка может только ПОВЫСИТЬ до review, но не понизить.
    #
    # Подтверждённый не трогаем: она не изменила ни буквы текста, а разжаловать
    # решение человека молча — то же самое, что переписать его перевод.
    # Находка видна по risk_color и qa_issues, подтверждённые с замечаниями
    # показывает вкладка QA.
    #
    # review не трогаем по той же причине с другой стороны: этот статус ставят
    # те, кто ПЕРЕПИСАЛ текст (ремонт, переперевод, правка поверх заверенного),
    # и значит он «на текст смотрела машина, посмотри человек». Medical QA
    # проверяет числа и отрицания, а не то, читал ли кто-то результат правки;
    # её «замечаний нет» — не ответ на этот вопрос. Понижая review до qa, она
    # уводила починенные сегменты из зоны внимания на доске и в фильтрах.
    if seg.get("status") in ("translated", "qa"):
        seg["status"] = "review" if qa_result["risk_color"] == "red" else "qa"
    # seg["risk"] не трогаем. Это длина сегмента, по ней выбирается движок
    # перевода (low → Google); медицинскую опасность несут risk_score и
    # risk_color. Раньше проверка перетирала одно другим, и сегмент, чисто
    # прошедший QA, при следующем переводе уезжал в Google вместо GPT.

    return {"ok": True, "segment": seg, "qa_result": qa_result, "issues": qa_result["qa_issues"]}


@app.post("/api/segments/{pid}/{sid}/medical-qa")
def medical_qa_segment(pid: int, sid: int, req: MedicalQARequest = MedicalQARequest()):
    result = _segment_medical_qa(pid, sid, run_backcheck=req.run_backcheck,
                                 bc_model=req.bc_model)
    save_state(STATE)
    return result


class MedicalQABatchRequest(BaseModel):
    limit: int = 50
    segment_ids: Optional[list] = None
    run_backcheck: bool = True
    # Модель обратного перевода — та же, что у back-check. Своей модели у
    # Medical QA нет: правила детерминированные, вызов нужен только чтобы
    # получить обратный перевод, когда готового от back-check не осталось.
    bc_model: Optional[str] = None
    # Пропускать сегменты, чей результат относится к нынешнему тексту.
    skip_cached: bool = True


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
    # Свежую проверку второй раз не считаем. Экономит не только процессор:
    # Medical QA заказывает обратный перевод, если back-check по этому тексту
    # устарел, — то есть повторный прогон по всему проекту мог стоить денег.
    skipped_cached = 0
    if req.skip_cached:
        before = len(candidates)
        candidates = [s for s in candidates
                      if _check_stale(s.get("qa_result"), s.get("target"))]
        skipped_cached = before - len(candidates)
    targets = candidates[:req.limit]
    processed = []
    errors = []
    def _qa_one(seg):
        if _job_should_stop():
            return {"seg": seg, "skip": True}
        try:
            return {"seg": seg, "res": _segment_medical_qa(pid, seg["id"], run_backcheck=req.run_backcheck,
                                                           bc_model=req.bc_model)}
        except Exception as e:
            print(f"[backend] medical QA batch error seg#{seg['id']}: {e}", file=sys.stderr)
            return {"seg": seg, "error": str(e)}

    for out in _run_parallel(targets, _qa_one):
        seg = out["seg"]
        if out.get("skip"):
            continue
        if out.get("error"):
            errors.append({"id": seg["id"], "error": out["error"]})
        elif out["res"].get("ok"):
            processed.append(seg["id"])
        else:
            errors.append({"id": seg["id"], "error": out["res"].get("error", "unknown")})

    save_state(STATE)
    return {
        "ok": True,
        "processed": processed,
        "count": len(processed),
        "remaining": max(0, len(candidates) - len(targets)),
        "errors": errors,
        "skipped_cached": skipped_cached,
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
    # Движок один — выбранная модель, поэтому engine и low_engine убраны.
    # Заодно исчез отбор по risk: он существовал только чтобы делить сегменты
    # между Google и моделью, и оставлял половину проекта непереведённой,
    # если запустить не ту кнопку.
    limit: int = 50                      # максимум за один вызов
    segment_ids: Optional[list] = None  # если передан — обрабатывать только эти сегменты
    force: bool = False                  # True = явный выбор пользователя, пропустить фильтры статуса и риска
    model: Optional[str] = None          # id из OPENAI_MODELS; неизвестный → DEFAULT_OPENAI_MODEL
    include_confirmed: bool = False      # переписывать и подтверждённые (только по явной галочке)

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
        # Явный выбор — переводим только указанные сегменты. Подтверждённые
        # мимо, пока человек не попросил отдельной галочкой: молча переписать
        # заверенный перевод нельзя. Попросил — переписываем, но с сохранением
        # прежнего текста и со статусом «требует проверки» (см. ниже).
        all_targets = [s for s in project["segments"] if s["id"] in id_filter
                       and (req.include_confirmed or s["status"] != "confirmed")]
        skipped_confirmed = ([s["id"] for s in project["segments"]
                              if s["id"] in id_filter and s["status"] == "confirmed"]
                             if not req.include_confirmed else [])
    else:
        all_targets = [s for s in project["segments"]
                       if s["status"] == "new" and
                       (id_filter is None or s["id"] in id_filter)]
        skipped_confirmed = []
    done_by_src: dict = {}
    if not req.force:
        for s0 in project["segments"]:
            t0 = (s0.get("target") or "").strip()
            # Тот же белый список, что и у остальных потребителей перевода:
            # сегмент со статусом failed не прошёл проверку, и копировать его
            # текст в близнецов — значит размножить брак.
            if not t0 or s0.get("status") not in ("translated", "qa", "review", "confirmed"):
                continue
            key0 = _norm_key(s0.get("source"))
            prev = done_by_src.get(key0)
            # Донором становится лучший, а не первый по порядку: заверенный
            # человеком перевод сильнее машинного, иначе старая ошибка
            # переехала бы в новые сегменты поверх уже исправленного близнеца.
            if prev is None or (s0.get("confirmedBy") == "human" and not prev[1]):
                done_by_src[key0] = (t0, s0.get("confirmedBy") == "human",
                                     s0.get("provider"))

    # Ключ нужен, только если хоть один сегмент придётся ПЕРЕВОДИТЬ. Порция из
    # одних совпадений с памятью или из повторов уже переведённого обходится
    # без вызовов модели — отказывать ей 503 значило бы запретить работу,
    # которая ничего не стоит. Проверка стоит здесь: до отбора состав неизвестен.
    def _free(sg):
        if _tm_trusted(_get_context(sg["source"], project=project)[1]):
            return True
        return _norm_key(sg["source"]) in done_by_src
    if (all_targets and not os.environ.get("OPENAI_API_KEY")
            and not all(_free(s) for s in all_targets)):
        # 503 до работы, как у termcheck, back-check и ремонта: иначе отсутствие
        # ключа вырождается в посегментные ошибки, и составной прогон принимает
        # их за «порция целиком провалилась» вместо «шаг недоступен».
        raise HTTPException(503, "Перевод требует ключ OpenAI")
    # Потолок на порцию: один HTTP-запрос не должен жить дольше proxy_read_timeout (1800s)
    # в nginx. При ~5-6 с на сегмент 100 штук — это ~10 минут, с большим запасом.
    limit = max(1, min(req.limit, 100))
    remaining_after = max(0, len(all_targets) - limit)
    targets = all_targets[:limit]
    translated = []
    tm_hits_count = 0
    dup_hits_count = 0
    errors = []
    # Повторы внутри порции переводим один раз: в документах один и тот же
    # заголовок встречается десятки раз, и каждый стоил отдельного вызова.
    # Группируем ДО вызовов, чтобы уникальные тексты можно было гнать разом.
    groups: dict = {}
    order: list = []
    for seg in targets:
        key = _norm_key(seg["source"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(seg)

    # Готовые переводы одинаковых исходников ПО ВСЕМУ проекту. Дедупликация
    # внутри порции ловит только соседей: один и тот же заголовок, встретившийся
    # в сегментах 12 и 500, попадает в разные порции и оплачивается дважды.
    # Проект уже переведён наполовину — брать оттуда бесплатно.

    def _translate_group(key):
        """Один вызов на группу одинаковых исходников. Возвращает результат,
        применяет его основной поток — так мутации STATE остаются в одном месте."""
        seg = groups[key][0]
        if _job_should_stop():
            return {"key": key, "skip": True}
        gloss_hits, tm_hit = _get_context(seg["source"], project=project)

        # TM точное совпадение → пропускаем API вызов.
        # При force (явный выбор пользователя: галочки или «перевести заново») шорткат
        # не применяем — иначе «перевести заново выбранной моделью» молча подставляло бы
        # старый текст из памяти. Так же ведёт себя одиночный перевод сегмента.
        # Память переводов идёт ПЕРЕД повтором внутри проекта: её записи человек
        # подтверждал, а близнец в проекте мог быть переведён машиной и с тех пор
        # исправлен только в памяти.
        if not req.force and _tm_trusted(tm_hit) and tm_hit.get("tgt"):
            return {"key": key, "tm": True, "text": tm_hit["tgt"]}

        # Такой текст в проекте уже переведён — платить за него второй раз
        # не за что. force не трогаем: «перевести заново» должно переводить.
        ready = done_by_src.get(key)
        if ready:
            return {"key": key, "reuse": True, "text": ready[0], "provider": ready[2]}

        try:
            translation = _openai_translate(seg["source"], project["src"], project["tgt"],
                                            domain=project.get("domain"),
                                            gloss_hits=gloss_hits, tm_context=tm_hit,
                                            model=req.model)
        except Exception as e:
            print(f"[backend] batch error seg#{seg['id']}: {e}", file=sys.stderr)
            return {"key": key, "error": str(e)}
        if not translation:
            return {"key": key, "error": "модель не вернула перевод"}
        return {"key": key, "text": translation, "provider": _resolve_model(req.model)["id"]}

    for res in _run_parallel(order, _translate_group):
        segs = groups[res["key"]]
        if res.get("skip"):
            continue
        if res.get("error"):
            errors.extend(sg["id"] for sg in segs)
            continue
        if res.get("tm") or res.get("reuse"):
            for sg in segs:
                # translated, а не confirmed — см. translate_segment
                sg["target"] = res["text"]
                sg["status"] = "translated"
                sg["route"] = "EXACT_TM" if res.get("tm") else "DUPLICATE"
                # Копия наследует провайдера донора: писать «tm» на тексте,
                # взятом у соседнего сегмента, значит соврать о происхождении.
                sg["provider"] = PROVIDER_TM if res.get("tm") else (res.get("provider") or "")
                translated.append(sg["id"])
            if res.get("tm"):
                tm_hits_count += len(segs)
            else:
                dup_hits_count += len(segs)
            continue
        for i, sg in enumerate(segs):
            # Переписываем заверенный человеком перевод — сохраняем прежний текст
            # и снимаем отметку о подтверждении: статус «требует проверки», а не
            # «подтверждено». Машина не заверяет сама себя, и «подтвердил человек»
            # не должно оставаться на строке, которой человек не видел.
            was_confirmed = sg.get("status") == "confirmed"
            if was_confirmed:
                sg["prevTarget"] = sg.get("target", "")
                sg.pop("confirmedBy", None)
                sg.pop("confirmedAt", None)
            sg["target"] = res["text"]
            sg["status"] = "review" if was_confirmed else "translated"
            sg["provider"] = res["provider"]
            sg["route"] = "GPT_REQUIRED" if i == 0 else "DUPLICATE"
            translated.append(sg["id"])
        dup_hits_count += len(segs) - 1
    save_state(STATE)
    return {
        "ok": True,
        "translated": translated,
        "count": len(translated),
        "remaining": remaining_after,
        "errors": errors,
        "tm_hits": tm_hits_count,
        "duplicates": dup_hits_count,
        # Молчаливых потолков не бывает: сегменты, отсеянные как подтверждённые,
        # называем поимённо — иначе прогон рапортует «готово» и ничего не делает.
        "skipped_confirmed": skipped_confirmed,
        "model": _resolve_model(req.model)["id"],
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
            s["route"] = "GPT_REQUIRED"
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
    lang: Optional[str] = None      # языковая пара записи; пусто — дефолтная область
    domain: Optional[str] = None

@app.post("/api/glossary")
def save_term(req: TermRequest):
    scope = (req.lang or DEFAULT_GLOSS_LANG, req.domain or DEFAULT_GLOSS_DOMAIN)
    existing = _glossary_entry(req.src, scope)
    if existing is None and not (req.lang or req.domain):
        # Клиент не прислал область (правка записи из общего списка) — правим ту
        # запись, что есть, а не заводим рядом дубль в области по умолчанию.
        existing = next((g for g in STATE["glossary"]
                         if _norm_key(g.get("src")) == _norm_key(req.src)), None)
    # Правка руками = проверенная запись: только такие идут в промпт приказом.
    if existing and not req.isNew:
        existing.update({"tgt": req.tgt, "cat": req.cat, "freq": req.freq, "conf": req.conf,
                         "tier": GLOSSARY_TIER_HARD})
        _clear_auto_marks(existing)
    else:
        STATE["glossary"].insert(0, {**req.dict(exclude={"isNew"}), "tier": GLOSSARY_TIER_HARD,
                                     "lang": scope[0], "domain": scope[1]})
    _invalidate_gloss_index()
    save_state(STATE)
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    STATE["projects"] = [p for p in STATE["projects"] if p["id"] != pid]
    save_state(STATE)
    return {"ok": True}


@app.delete("/api/glossary")
def delete_term(src: str, lang: str = "", domain: str = ""):
    """Удаление — операция без отмены, поэтому область здесь трактуется строго.
    Пустые lang/domain означают область по умолчанию (так же читаются записи
    без полей), а НЕ «любую»: иначе удаление RU→EN термина уносило бы и его
    RU→DE тёзку из чужого проекта."""
    want = (lang or DEFAULT_GLOSS_LANG, domain or DEFAULT_GLOSS_DOMAIN)
    victims = [t for t in STATE["glossary"] if t.get("src") == src and _scope_of(t) == want]
    if not victims and not (lang or domain):
        # Область не назвали и в области по умолчанию записи нет. Удаляем по
        # одному имени, только если претендент ровно один — иначе непонятно,
        # какой именно, а угадывать в необратимой операции нельзя.
        same = [t for t in STATE["glossary"] if t.get("src") == src]
        if len(same) == 1:
            victims = same
    if not victims:
        raise HTTPException(404, "Запись не найдена в этой области")
    doomed = {id(t) for t in victims}
    STATE["glossary"] = [t for t in STATE["glossary"] if id(t) not in doomed]
    _invalidate_gloss_index()
    save_state(STATE)
    return {"ok": True}


# ─── TM ─────────────────────────────────────────────────────────────
@app.delete("/api/tm")
def delete_tm(src: str, lang: str = ""):
    """Как и у глоссария: пустой lang — это пара по умолчанию, а не «любая».
    _tm_upsert теперь держит по записи на языковую пару, и удаление RU→EN
    иначе уносило бы RU→DE запись того же исходника."""
    want = lang or DEFAULT_GLOSS_LANG
    victims = [t for t in STATE["tm"]
               if t.get("src") == src and (t.get("lang") or DEFAULT_GLOSS_LANG) == want]
    if not victims and not lang:
        same = [t for t in STATE["tm"] if t.get("src") == src]
        if len(same) == 1:
            victims = same
    if not victims:
        raise HTTPException(404, "Запись памяти переводов не найдена в этой паре языков")
    doomed = {id(t) for t in victims}
    STATE["tm"] = [t for t in STATE["tm"] if id(t) not in doomed]
    save_state(STATE)
    return {"ok": True}


@app.get("/api/health")
def health(request: Request):
    # Эндпоинт публичный — на него опирается смоук-проверка деплоя.
    # Пути на диске и список модулей отдаём только вошедшим.
    info = {
        "ok": True,
        "version": "5.6.0",
        "medicalQaEnabled": medical_qa_enabled(),
        "projects": len(STATE["projects"]),
    }
    if _session_valid(_token_from_request(request)):
        info["backendModules"] = list(_BACKEND_MODULES.keys())
        info["stateFile"] = str(STATE_FILE)
    return info



# ─── Фоновые прогоны ─────────────────────────────────────────────────
# Раньше пакет гонял браузер: закрыл вкладку — прогон оборвался на середине,
# а оплаченные вызовы для оставшихся сегментов просто не случились. Теперь
# клиент только ставит задачу, а порции крутит сервер, и страница нужна лишь
# чтобы смотреть прогресс.
#
# Рабочий поток ОДИН и очередь одна: воркер uvicorn тоже один, STATE — общий
# словарь в памяти. Два параллельных прогона дрались бы за один state.json.
import queue as _queue

JOB_CHUNKS = {"translate": 10, "backcheck": 10, "termcheck": 10, "medical_qa": 10,
              "repair": 5, "full": 5, "apply_terms": 5}
JOB_KINDS = set(JOB_CHUNKS)

# Составной прогон: порция проходит все шаги подряд, порция за порцией. Порядок
# НЕ косметический и менять его нельзя:
#   перевод    — иначе проверять нечего;
#   back-check — Medical QA берёт из него готовый обратный перевод и не платит
#                за него второй раз;
#   термины    — вторая независимая проверка; та из двух, что отработала второй,
#                и собирает терминологию с чистых сегментов;
#   ремонт     — после обеих проверок: он чинит по ИХ находкам;
#   Medical QA — последней, и это её место, а не предпоследнее.
#
# Medical QA стояла перед ремонтом, пока считалось, что ремонту нужны её
# находки. Это неправда: _repair_findings читает back-check, termcheck и
# глоссарий, а qa_result не читает никто — числа, единицы и отрицания,
# которыми чинит ремонт, считает сам back-check через medical_qa.run_backcheck.
# Стоя перед ремонтом, проверка описывала текст, который через шаг переписывали,
# и оставалась устаревшей: следующий прогон забирал те же сегменты снова.
# Стоя после, она описывает окончательный текст и в следующий прогон
# не попадает.
FULL_RUN_STEPS = ["translate", "backcheck", "termcheck", "repair", "medical_qa"]
FULL_STEP_LABELS = {"translate": "перевод", "backcheck": "back-check",
                    "termcheck": "проверка терминов", "medical_qa": "Medical QA",
                    "repair": "ремонт"}
# Откуда шаг берёт свою модель. Подшаги читают её из params["model"], а моделей
# в составном прогоне несколько: смысл в том, что переводит одна, а проверяют
# другие — иначе проверка перестаёт быть независимой.
FULL_STEP_MODEL = {"translate": "model", "backcheck": "bc_model",
                   "termcheck": "tc_model", "repair": "rp_model"}


# ── Разбор прогона: что он сделает и чего делать не станет ───────────────────
# Состав и смету раньше считал браузер своими предикатами, а работу отбирал
# сервер своими — и разойтись они были обязаны. Список сегментов у составного
# прогона ОДИН, объединение целей всех шагов, и каждый шаг брал оттуда всё,
# что проходило ЕГО серверную проверку, а не то, что человек отметил галочками
# в карточке соседнего шага. Снятая галочка уменьшала смету, но не работу:
# показывали одно, списывалось другое.
#
# Теперь состав считает тот же код, который потом и работает, — предикаты
# _backcheck_cached / _termcheck_cached / _check_stale / _repairable. И разбор
# отвечает не только «сколько», но и «почему»: «пропущено 970» без причины —
# это не отчёт, а отговорка, после которой человек идёт кликать галочки
# наугад.
def _model_label(mid: str) -> str:
    m = _MODELS_BY_ID.get(mid or "")
    return m["label"] if m else (mid or "модель неизвестна")


def _plan_step(project: dict, step: str, params: dict, scope: list,
               will_translate: set, gloss_ids: set) -> dict:
    """Разбор одного шага: кого возьмёт, кого не возьмёт и почему.

    will_translate — сегменты, которые переведёт этот же прогон. Сейчас у них
    нет перевода и ни в одну проверку они не попадают, но к своему шагу уже
    будут переведены. Без них разбор непереведённого проекта показывал бы цену
    одного перевода, хотя платить придётся и за все проверки поверх него."""
    ids, runs, skips = [], {}, {}

    def run(reason, seg):
        ids.append(seg["id"])
        runs[reason] = runs.get(reason, 0) + 1

    def skip(reason):
        skips[reason] = skips.get(reason, 0) + 1

    mdl_id = None
    if step == "backcheck":
        mdl_id = _resolve_model(params.get("bc_model") or BACKCHECK_DEFAULT_MODEL)["id"]
    elif step == "termcheck":
        mdl_id = _resolve_model(params.get("tc_model") or TERMCHECK_DEFAULT_MODEL)["id"]
    elif step == "repair":
        mdl_id = _resolve_model(params.get("rp_model") or REPAIR_DEFAULT_MODEL)["id"]
    elif step == "translate":
        mdl_id = _resolve_model(params.get("model"))["id"]
    elif step == "medical_qa":
        # Своей модели у неё нет: правила детерминированные. Но обратный
        # перевод, если готового не осталось, она закажет — моделью back-check.
        # Показываем именно её: «без вызова модели» было полуправдой, из-за
        # которой шаг молча платил моделью перевода по умолчанию.
        mdl_id = _resolve_model(params.get("bc_model") or BACKCHECK_DEFAULT_MODEL)["id"]

    use_judge = bool(params.get("use_judge"))
    retry = bool(params.get("retry"))
    # Разрешение чинить заверенное человеком. Разбор ОБЯЗАН его читать: раньше
    # он отбрасывал подтверждённые безусловно, а прогон брал их по флагу —
    # смета обещала одно, работа делала другое. Флаг относится только к ремонту
    # (см. _job_chunk_full): он правит по конкретным находкам и точечно,
    # а перевод заново перегнал бы сегмент целиком и за полную цену.
    fix_confirmed = bool(params.get("include_confirmed"))
    note = None

    for seg in scope:
        target = (seg.get("target") or "").strip()
        pending = seg["id"] in will_translate and not target

        if step == "translate":
            if seg.get("status") == "new":
                run("ещё не переведён", seg)
            else:
                skip("уже переведён")
            continue

        # Переводится в этом же прогоне — к своему шагу текст появится.
        if pending:
            run("появится после перевода", seg)
            continue
        if not target:
            skip("нет перевода")
            continue

        if step == "backcheck":
            if _backcheck_cached(seg, mdl_id, use_judge):
                bm = (seg.get("backcheck") or {}).get("model")
                skip("уже проверен этим переводом: " + _model_label(bm))
            elif (seg.get("backcheck") or {}).get("score") is None:
                # is None, а не truthy: балл 0 — это проверенный сегмент
                # с провальной оценкой, а не непроверенный.
                run("ещё не проверялся", seg)
            elif _check_stale(seg.get("backcheck"), target):
                run("перевод изменился после проверки", seg)
            elif (seg.get("backcheck") or {}).get("model") == seg.get("provider"):
                run("проверял тот, кто переводил — это не проверка", seg)
            else:
                run("проверен без судьи, а судья включён", seg)

        elif step == "termcheck":
            tc = seg.get("termcheck") or {}
            if _termcheck_cached(seg, mdl_id):
                if tc.get("model") == "skip":
                    skip("нечего проверять — в переводе нет слов")
                elif tc.get("model") == mdl_id:
                    skip("уже проверен этой моделью")
                else:
                    skip("уже проверен моделью не слабее: " + _model_label(tc.get("model")))
            elif not tc:
                run("ещё не проверялся", seg)
            elif _check_stale(tc, target):
                run("перевод изменился после проверки", seg)
            elif model_rank(tc.get("model") or "") is None:
                # Ранга нет — утверждать «этого достаточно» не о чем. Называем
                # модель поимённо: строка в разборе и есть подсказка, что её
                # пора дописать в backend/model_ranks.json.
                run("прошлая проверка моделью неизвестной силы: "
                    + _model_label(tc.get("model")), seg)
            else:
                run("прошлая проверка слабее выбранной: " + _model_label(tc.get("model")), seg)

        elif step == "medical_qa":
            if seg.get("status") not in ("translated", "qa", "review", "confirmed"):
                skip("статус вне работы проверки")
            elif not _check_stale(seg.get("qa_result"), target):
                skip("результат относится к нынешнему тексту")
            else:
                run("нет свежего результата", seg)

        elif step == "repair":
            # Глоссарий берётся из готового отчёта о соответствии, а не считается
            # заново на каждый сегмент: расчёт тот же самый (это записано в
            # _gloss_misses как обязательство), но 13 мс на сегмент превращали
            # разбор проекта на 2670 строк в 34 секунды с заблокированным
            # воркером — при том, что смета пересчитывается на каждую смену
            # модели в списке. project=None тут и означает «без глоссария»:
            # остальные находки читаются из самого сегмента и бесплатны.
            if seg["id"] not in gloss_ids and not _repair_findings(seg, None):
                skip("чинить нечего — находок нет")
            elif seg.get("status") == "confirmed" and not fix_confirmed:
                skip("заверено человеком — включите «чинить подтверждённые»")
            elif not retry and _repair_tried(seg):
                skip("этот же текст уже чинили")
            elif seg.get("status") == "confirmed":
                # Причина названа отдельно намеренно: цена у этих сегментов та же,
                # а последствие другое — отметка «подтвердил человек» с них снимется.
                run("есть находки, подтверждение будет снято", seg)
            else:
                run("есть находки", seg)

    # Ремонт и Medical QA зависят от того, что найдут предыдущие шаги ЭТОГО же
    # прогона, а этого до запуска не знает никто. Молчать об этом нельзя:
    # смета, посчитанная по нынешним находкам, — нижняя граница, а не цена.
    if step == "repair":
        note = ("Считано по нынешним находкам. Проверки в этом же прогоне могут "
                "добавить ещё — такие сегменты будут починены, но в смету не вошли.")
    elif step == "medical_qa":
        note = ("Считано по нынешнему тексту. Сегменты, которые перепишет ремонт, "
                "проверка возьмёт тоже — они идут следом за ним.")

    fmt = lambda d: [{"reason": k, "count": v} for k, v in
                     sorted(d.items(), key=lambda kv: -kv[1])]
    return {"step": step, "label": FULL_STEP_LABELS[step], "model": mdl_id,
            "modelLabel": _model_label(mdl_id) if mdl_id else None,
            "ids": ids, "count": len(ids), "note": note,
            "runs": fmt(runs), "skips": fmt(skips)}


class RunPlanRequest(BaseModel):
    steps: Optional[list] = None
    segment_ids: Optional[list] = None   # None — весь проект; [] — ничего
    model: Optional[str] = None
    bc_model: Optional[str] = None
    tc_model: Optional[str] = None
    rp_model: Optional[str] = None
    use_judge: bool = False
    retry: bool = False
    include_confirmed: bool = False   # чинить и заверенное человеком (только ремонт)


@app.post("/api/projects/{pid}/run-plan")
def run_plan(pid: int, req: RunPlanRequest):
    """Что сделает составной прогон с этими настройками — до его запуска.

    Клиент не считает состав сам и не подбирает его галочками: и то и другое
    он делал по своим правилам, а деньги тратились по серверным."""
    project = get_project(pid)
    # is not None, а не truthy: пустой список — это «не выбрано ни одного шага»,
    # и разбирать надо ноль шагов, а не весь конвейер.
    want = set(req.steps if req.steps is not None else FULL_RUN_STEPS)
    steps = [s for s in FULL_RUN_STEPS if s in want]
    id_filter = set(req.segment_ids) if req.segment_ids is not None else None
    scope = [s for s in project["segments"]
             if id_filter is None or s["id"] in id_filter]
    params = req.dict()
    will_translate = ({s["id"] for s in scope if s.get("status") == "new"}
                      if "translate" in steps else set())
    # Один расчёт соответствия глоссарию на весь разбор, из общего кэша по
    # отпечатку проекта — тот же, которым живёт отчёт «Соответствие глоссарию».
    gloss_ids = (set(glossary_impact(pid)["segments"])
                 if "repair" in steps else set())
    plans = [_plan_step(project, st, params, scope, will_translate, gloss_ids)
             for st in steps]
    # Объединение — в порядке ДОКУМЕНТА, а не в порядке шагов: порции идут по
    # этому списку, и прогон должен двигаться по тексту сверху вниз, а не
    # прыгать по проекту в зависимости от того, какому шагу сегмент достался.
    seen: set = set()
    for p in plans:
        seen.update(p["ids"])
    ids = [s["id"] for s in scope if s["id"] in seen]
    return {"steps": plans, "ids": ids, "total": len(ids), "scope": len(scope)}


JOB_HISTORY = 30                # сколько завершённых прогонов помним
JOB_CHUNK_RETRIES = 2           # повтор порции при сбое: сеть моргнула — не всё потеряно
JOB_RETRY_PAUSE = 5             # секунд между попытками

_JOBS: dict = {}                # id -> job
_JOB_QUEUE = _queue.Queue()
_JOBS_LOCK = threading.Lock()
_JOB_WORKER = None


def _job_public(job: dict) -> dict:
    """Наружу отдаём без внутренних полей (список id и флаг остановки)."""
    return {k: v for k, v in job.items() if k not in ("ids", "stop")}


def _first_error(result: dict) -> str:
    """Текст первой ошибки порции. Пакетные эндпоинты глотают ошибку каждого
    сегмента по отдельности, и наружу шло только их число — а «ошибок: 10»
    не отличить от «кончились деньги на счёте» и «отозван ключ»."""
    for e in (result.get("errors") or []):
        txt = e.get("error") if isinstance(e, dict) else str(e)
        if txt:
            return str(txt)[:180]
    return ""


def _job_chunk_full(pid: int, chunk: list, params: dict) -> dict:
    """Порция составного прогона: все шаги подряд, в порядке FULL_RUN_STEPS.

    Шаг, для которого нет ключа или модуля, не роняет прогон — он записывается
    в blocked и работа идёт дальше: отсутствие ключа OpenAI не повод терять
    уже сделанный перевод. Но если НИ ОДИН шаг не отработал, порция считается
    провалившейся: молча рапортовать «выполнено», не сделав ничего, нельзя."""
    # Порядок берём из FULL_RUN_STEPS, а не из присланного списка: клиент выбирает
    # СОСТАВ шагов, но не их очерёдность — она несущая (см. комментарий там же).
    want = set(params.get("steps") or FULL_RUN_STEPS)
    steps = [s for s in FULL_RUN_STEPS if s in want]
    out = {"done": len(chunk)}
    ran, blocked = [], []
    for st in steps:
        if _job_should_stop():
            break
        # Medical QA сообщает о своей недоступности пятисоткой посегментно, а не
        # 503 на пакет: без этой проверки отсутствие модуля выглядело бы как
        # «порция целиком провалилась» и роняло весь прогон.
        if st == "medical_qa" and not (medical_qa_mod and medical_qa_enabled()):
            blocked.append("Medical QA: модуль недоступен")
            continue
        sub = dict(params)
        # У каждого шага своя модель: одна переводит, другие проверяют. Подшаги
        # читают её из params["model"], поэтому подставляем нужную перед вызовом —
        # иначе back-check пошёл бы той же моделью, что делала перевод, и перестал
        # быть независимой проверкой.
        mkey = FULL_STEP_MODEL.get(st)
        if mkey:
            # or None, а не «если задано»: незаполненная модель шага означает
            # «возьми свою по умолчанию», а не «возьми ту, что переводила».
            # Иначе back-check молча шёл бы моделью переводчика и переставал
            # быть независимой проверкой — а на ней стоит автоодобрение.
            sub["model"] = params.get(mkey) or None
        # Разрешение трогать заверенное человеком относится ТОЛЬКО к ремонту:
        # он меняет минимум слов по конкретным находкам и откатывается, если
        # стало хуже. Отдай тот же флаг переводу — и одна галочка «починить
        # подтверждённые» перегнала бы их заново целиком, по полной цене
        # и без единой находки в основании. Это и есть точечность: правим
        # найденное, а не переводим сегмент сначала.
        sub["include_confirmed"] = bool(params.get("include_confirmed")) if st == "repair" else False
        if st == "translate":
            # Уже переведённое не переводим заново: составной прогон гоняют
            # по всему проекту, и force затирал бы готовые переводы.
            sub["force"] = False
        if st in ("backcheck", "termcheck", "medical_qa"):
            # Свежую проверку второй раз не оплачиваем — за состав отвечает
            # отбор сегментов, а не повторный вызов модели.
            sub["skip_cached"] = True
        try:
            r = _job_chunk(st, pid, chunk, sub)
        except HTTPException as e:
            if e.status_code == 503:
                blocked.append("%s: %s" % (FULL_STEP_LABELS[st], e.detail))
                continue
            raise
        if r.get("done", 0) == 0 and r.get("errors", 0) >= len(chunk):
            # Называем ПРИЧИНУ, а не только симптом. «Порция завершилась
            # ошибкой» человек прочтёт как поломку программы и полезет
            # в настройки, тогда как на деле у аккаунта кончились деньги или
            # отозван ключ — и это видно только в журнале сервера.
            why = r.get("why") or ""
            raise RuntimeError("порция целиком завершилась ошибкой на шаге «%s»%s"
                               % (FULL_STEP_LABELS[st], (": " + why) if why else ""))
        ran.append(st)
        for k, v in r.items():
            key = st if k == "done" else k
            if isinstance(v, str):
                # Текстовые поля (причина ошибки) не складываются: берём первое
                # непустое. Складывать их с числом — TypeError посреди прогона.
                if v and not out.get(key):
                    out[key] = v
                continue
            out[key] = out.get(key, 0) + v
    if blocked and not ran:
        raise RuntimeError("ни один шаг не выполнен — " + "; ".join(blocked))
    if blocked:
        # Счётчики прогона суммируются по всем порциям, поэтому это число —
        # «сколько раз шаг пропускался», а не «сколько шагов». Называем его так
        # и на экране: три недоступных шага на 534 порциях дают 1602, и подпись
        # «пропущено шагов: 1602» была бы враньём.
        out["step_skips"] = len(blocked)
        print("[backend] составной прогон: пропущены шаги — " + "; ".join(blocked),
              file=sys.stderr)
    return out


def _job_chunk(kind: str, pid: int, chunk: list, params: dict) -> dict:
    """Одна порция. Возвращает счётчики, которые нарастают в прогрессе."""
    n = len(chunk)
    if kind == "full":
        return _job_chunk_full(pid, chunk, params)
    if kind == "apply_terms":
        # Ремонт по свежеодобренным терминам. Само одобрение пачки делает
        # первая порция (см. _job_run: ставится флаг), дальше идёт обычный
        # ремонт — расхождение с глоссарием у него такая же находка, как
        # потерянный термин. Отдельного «переперевода» тут нет намеренно:
        # ремонт меняет минимум слов и откатывается, если стало хуже.
        r = repair_batch(pid, RepairBatchRequest(
            segment_ids=chunk, limit=n, model=params.get("rp_model") or params.get("model"),
            bc_model=params.get("bc_model"), tc_model=params.get("tc_model"),
            use_judge=bool(params.get("use_judge")), judge_model=params.get("judge_model"),
            include_confirmed=bool(params.get("include_confirmed")), retry=True))
        # done = сделанное, а не размер порции: иначе проверка «порция целиком
        # завершилась ошибкой» никогда не сработает, и мёртвый ключ выглядел бы
        # как «выполнено, исправлено 0».
        return {"done": len(r.get("applied", [])) + len(r.get("skipped", [])),
                "applied": len(r.get("applied", [])), "why": _first_error(r),
                "reverted": len(r.get("skipped", [])), "errors": len(r.get("errors", [])),
                "skipped_confirmed": len(r.get("skipped_confirmed", []))}
    if kind == "translate":
        r = batch_translate(pid, BatchRequest(
            segment_ids=chunk, limit=n,
            force=bool(params.get("force", True)), model=params.get("model"),
            include_confirmed=bool(params.get("include_confirmed"))))
        return {"done": r["count"], "tm_hits": r.get("tm_hits", 0),
                "duplicates": r.get("duplicates", 0), "errors": len(r.get("errors", [])),
                "why": _first_error(r), "skipped_confirmed": len(r.get("skipped_confirmed", []))}
    if kind == "backcheck":
        r = backcheck_batch(pid, BackcheckBatchRequest(
            segment_ids=chunk, limit=n, model=params.get("model"),
            use_judge=bool(params.get("use_judge")), judge_model=params.get("judge_model"),
            skip_cached=bool(params.get("skip_cached", False))))
        return {"done": r["count"], "duplicates": r.get("duplicates", 0),
                "skipped_cached": r.get("skipped_cached", 0),
                "errors": len(r.get("errors", [])), "why": _first_error(r)}
    if kind == "termcheck":
        r = termcheck_batch(pid, TermcheckBatchRequest(
            segment_ids=chunk, limit=n, model=params.get("model"),
            skip_cached=bool(params.get("skip_cached", False))))
        return {"done": r["count"], "flagged": r.get("flagged", 0),
                "duplicates": r.get("duplicates", 0), "why": _first_error(r),
                "skipped_trivial": r.get("skipped_trivial", 0), "errors": len(r.get("errors", []))}
    if kind == "repair":
        r = repair_batch(pid, RepairBatchRequest(
            segment_ids=chunk, limit=n, model=params.get("model"),
            bc_model=params.get("bc_model"), tc_model=params.get("tc_model"),
            use_judge=bool(params.get("use_judge")), judge_model=params.get("judge_model"),
            include_confirmed=bool(params.get("include_confirmed")),
            retry=bool(params.get("retry"))))
        return {"done": len(r.get("applied", [])) + len(r.get("skipped", [])),
                "applied": len(r.get("applied", [])), "reverted": len(r.get("skipped", [])),
                "errors": len(r.get("errors", [])), "why": _first_error(r),
                "skipped_confirmed": len(r.get("skipped_confirmed", []))}
    if kind == "medical_qa":
        r = batch_medical_qa(pid, MedicalQABatchRequest(
            segment_ids=chunk, limit=n, bc_model=params.get("bc_model"),
            skip_cached=bool(params.get("skip_cached", False))))
        return {"done": r.get("count", 0), "errors": len(r.get("errors", [])),
                "why": _first_error(r), "skipped_cached": r.get("skipped_cached", 0)}
    raise ValueError("unknown job kind: " + kind)


def _job_run(job: dict):
    kind, pid = job["kind"], job["project"]
    chunk_size = JOB_CHUNKS[kind]
    if kind == "apply_terms":
        # Одобрение пачки — один шаг, а не порция: оно про глоссарий, а не про
        # сегменты. Состав сегментов пересчитываем ПОСЛЕ него: до одобрения
        # неизвестно, какие сегменты разойдутся с новыми терминами, и клиент
        # физически не может прислать правильный список.
        if job["stop"]:
            # Остановили до записи — значит ничего и не записываем. Проверка
            # обязана стоять ДО одобрения: глоссарий меняется одним куском,
            # и «остановлено» после него было бы неправдой.
            job["status"] = "stopped"
            job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return
        try:
            res = auto_approve_terms(AutoApproveRequest(
                dry_run=False, project=pid,
                max_tier=job["params"].get("max_tier"),
                limit=int(job["params"].get("term_limit", 2000))))
        except HTTPException as e:
            job["status"], job["error"] = "error", f"{e.status_code}: {e.detail}"
            job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return
        job["counters"]["termsApproved"] = res["counts"]["verified"] + res["counts"]["auto"]
        job["counters"]["termsVerified"] = res["counts"]["verified"]
        job["counters"]["termsClosed"] = res["counts"]["closed"]
        job["autoBatch"] = res.get("batch")
        # Чиним ТОЛЬКО то, что разошлось с утверждёнными терминами, а не всё,
        # где вообще есть находки: человек нажал «применить термины», а не
        # «перебрать весь проект». Список тот же, что показывает карточка
        # «Соответствие глоссарию», — расчёт один, чтобы цифры не расходились.
        imp = glossary_impact(pid, refresh=True)
        allow_conf = bool(job["params"].get("include_confirmed"))
        job["ids"] = list(imp["segments"] if allow_conf else imp["pending"])
        job["total"] = len(job["ids"])
        save_state(STATE)
    ids = job["ids"]
    for i in range(0, len(ids), chunk_size):
        if job["stop"]:
            job["status"] = "stopped"
            break
        chunk = ids[i:i + chunk_size]
        job["recent"] = chunk          # клиент подтянет только эти сегменты
        last_err = None
        for attempt in range(JOB_CHUNK_RETRIES + 1):
            try:
                counters = _job_chunk(kind, pid, chunk, job["params"])
                # Порция, где не прошло НИЧЕГО, — это не «выполнено»: так выглядит
                # мёртвый ключ или упавший провайдер. Пакетные эндпоинты глотают
                # ошибку каждого сегмента по отдельности, и без этой проверки
                # прогон рапортовал бы «готово» с нулевым результатом.
                if counters.get("done", 0) == 0 and counters.get("errors", 0) >= len(chunk):
                    # С причиной от провайдера: «проверьте ключи и связь» звучит
                    # одинаково и для кончившихся денег, и для отозванного ключа,
                    # и для оборванной сети — а действия у них разные.
                    raise RuntimeError("порция целиком завершилась ошибкой"
                                       + (": " + counters["why"] if counters.get("why")
                                          else " — проверьте ключи и связь"))
                for k, v in counters.items():
                    if k == "done":
                        job["done"] += v
                    elif isinstance(v, str):
                        # Причина ошибки — текст, а не счётчик. Складывать её
                        # с числом значит уронить TypeError посреди прогона,
                        # причём молча: общий обработчик повторит порцию
                        # трижды, оплатив её вызовы заново.
                        if v and not job["counters"].get(k):
                            job["counters"][k] = v
                    else:
                        job["counters"][k] = job["counters"].get(k, 0) + v
                last_err = None
                break
            except HTTPException as e:
                # 503 (нет ключа) или 404 — повторять бессмысленно
                last_err = f"{e.status_code}: {e.detail}"
                break
            except Exception as e:
                last_err = str(e)
                print(f"[backend] job#{job['id']} chunk failed ({attempt + 1}): {e}", file=sys.stderr)
                if attempt < JOB_CHUNK_RETRIES:
                    time.sleep(JOB_RETRY_PAUSE)
        if last_err:
            job["status"] = "error"
            job["error"] = last_err
            break
    if job["status"] == "running":
        job["status"] = "done"
    job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _job_loop():
    while True:
        job = _JOB_QUEUE.get()
        try:
            if job["stop"]:
                job["status"] = "stopped"
                job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                continue
            job["status"] = "running"
            job["started"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _ACTIVE_JOB["job"] = job
            _usage_begin(job)
            _job_run(job)
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[backend] job#{job.get('id')} crashed: {e}", file=sys.stderr)
        finally:
            _ACTIVE_JOB.pop("job", None)
            # До save_state: запись о расходе должна уехать на диск вместе
            # с остальным результатом прогона, а не ждать следующего сохранения.
            _usage_end(job)
            try:
                save_state(STATE)
            except Exception as e:
                print(f"[backend] job#{job.get('id')} save failed: {e}", file=sys.stderr)
            _JOB_QUEUE.task_done()


def _ensure_job_worker():
    global _JOB_WORKER
    if _JOB_WORKER is None or not _JOB_WORKER.is_alive():
        _JOB_WORKER = threading.Thread(target=_job_loop, name="mcat-jobs", daemon=True)
        _JOB_WORKER.start()


def _trim_jobs():
    finished = [j for j in _JOBS.values() if j["status"] in ("done", "stopped", "error")]
    for j in sorted(finished, key=lambda x: x["id"])[:-JOB_HISTORY]:
        _JOBS.pop(j["id"], None)


class JobRequest(BaseModel):
    kind: str
    segment_ids: List[int]
    params: dict = {}


@app.post("/api/projects/{pid}/jobs")
def create_job(pid: int, req: JobRequest):
    """Поставить прогон в очередь. Клиенту достаточно отдать список сегментов —
    дальше страница может быть закрыта, сервер доведёт работу до конца."""
    get_project(pid)                        # 404, если проекта нет
    if req.kind not in JOB_KINDS:
        raise HTTPException(400, "Неизвестный тип прогона: " + req.kind)
    ids = list(dict.fromkeys(req.segment_ids))
    # apply_terms сам считает состав после одобрения терминов — до него список
    # сегментов ещё неизвестен, и требовать его от клиента бессмысленно.
    if not ids and req.kind != "apply_terms":
        raise HTTPException(400, "Пустой список сегментов")
    with _JOBS_LOCK:
        job = {
            "id": max(_JOBS, default=0) + 1,
            "kind": req.kind, "project": pid, "status": "queued",
            "total": len(ids), "done": 0, "counters": {}, "error": None,
            "params": dict(req.params or {}),
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "started": None, "finished": None,
            "ids": ids, "stop": False, "recent": [],
        }
        _JOBS[job["id"]] = job
        _trim_jobs()
    _ensure_job_worker()
    _JOB_QUEUE.put(job)
    return {"ok": True, "job": _job_public(job)}


@app.get("/api/usage")
def usage_report(limit: int = 20):
    """Сколько прогоны стоили на самом деле — рядом с тем, во что их оценили.

    Ни одного вызова модели здесь нет: всё уже посчитано провайдером и снято
    с ответов. `process` — расход с момента старта сервиса, включая одиночные
    вызовы по кнопке, которые ни одному прогону не принадлежат."""
    runs = list(reversed(STATE.get("runCosts") or []))[:max(1, min(limit, 100))]
    priced = [r for r in runs if r.get("est") and r.get("cost")]
    return {
        "process": _USAGE_TOTAL,
        "runs": runs,
        # Во сколько раз смета в среднем расходится с фактом. Это и есть та
        # поправка, которой в системе не было: без неё «ориентировочно $15»
        # не с чем сравнить, и остаётся гадать, врёт она или прогон не отработал.
        "estRatio": (round(sum(r["est"] for r in priced) / sum(r["cost"] for r in priced), 2)
                     if priced and sum(r["cost"] for r in priced) else None),
        "estRuns": len(priced),
    }


@app.get("/api/jobs")
def list_jobs(project: Optional[int] = None, limit: int = 20):
    jobs = [j for j in _JOBS.values() if project is None or j["project"] == project]
    jobs.sort(key=lambda j: j["id"], reverse=True)
    active = [_job_public(j) for j in jobs if j["status"] in ("queued", "running")]
    return {"active": active, "jobs": [_job_public(j) for j in jobs[:max(1, min(limit, 100))]]}


@app.get("/api/jobs/{jid}")
def get_job(jid: int):
    job = _JOBS.get(jid)
    if not job:
        raise HTTPException(404, "Прогон не найден")
    return {"ok": True, "job": _job_public(job)}


@app.post("/api/jobs/{jid}/stop")
def stop_job(jid: int):
    """Остановка мягкая: текущая порция досчитывается и сохраняется, следующая
    не начинается. Обрывать порцию на середине значило бы заплатить за вызовы
    и выбросить их результат."""
    job = _JOBS.get(jid)
    if not job:
        raise HTTPException(404, "Прогон не найден")
    job["stop"] = True
    if job["status"] == "queued":
        job["status"] = "stopped"
        job["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elif job["status"] == "running":
        # Промежуточный статус: обработка текущего сегмента доигрывается, но
        # пользователю сразу видно, что кнопка сработала.
        job["stopping"] = True
    return {"ok": True, "job": _job_public(job)}


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
