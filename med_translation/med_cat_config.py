"""
med_cat_config.py — Центральная конфигурация Medical CAT Translator.

Единственное место, откуда берутся все пути и константы.
Не добавляй ID / секреты сюда — используй переменные окружения.
"""
from pathlib import Path

# ── Корневая директория проекта ───────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# ── Ассеты (глоссарии, TM) ────────────────────────────────────────────────────
ASSETS_DIR        = BASE_DIR / "assets"
GLOSSARY_DIR      = ASSETS_DIR / "glossary"
TM_DIR            = ASSETS_DIR / "tm"
REJECTED_DIR      = ASSETS_DIR / "rejected"
BACKUPS_DIR       = ASSETS_DIR / "backups"

# Fallback: original final_output/ (если assets/glossary/ не заполнен)
FINAL_OUTPUT_DIR  = BASE_DIR / "final_output"

# ── Файлы глоссариев ──────────────────────────────────────────────────────────
APPROVED_TSV    = GLOSSARY_DIR / "approved_glossary_FINAL.tsv"
REFERENCE_TSV   = GLOSSARY_DIR / "reference_glossary_FINAL.tsv"
FORBIDDEN_TSV   = GLOSSARY_DIR / "forbidden_translations_FINAL.tsv"
TM_TSV          = GLOSSARY_DIR / "tm_reference_FINAL.tsv"

# ── Проекты ───────────────────────────────────────────────────────────────────
PROJECTS_DIR    = BASE_DIR / "projects"

# ── Данные / логи ─────────────────────────────────────────────────────────────
DATA_DIR        = BASE_DIR / "data"
LOGS_DIR        = BASE_DIR / "logs"
SEGMENTS_LOG    = DATA_DIR / "segments.jsonl"

# ── Константы движка ─────────────────────────────────────────────────────────

# Сколько терминов из глоссария инжектировать в промпт (оптимизация токенов)
MAX_GLOSSARY_TERMS_IN_PROMPT = 15

# Сколько TM-матчей показывать / инжектировать
MAX_TM_MATCHES_IN_PROMPT     = 3
MAX_TM_MATCHES_DISPLAY       = 10

# Пороги TM (в процентах)
TM_AUTO_INSERT   = 99    # ≥99 → вставить автоматически
TM_GREEN         = 97    # 97–98 → зелёное предложение
TM_YELLOW        = 94    # 94–96 → жёлтое предложение
TM_REFERENCE     = 0     # <94 → только справочно

# Минимальный score для fuzzy-матча терминов (0–1)
FUZZY_MIN_SCORE  = 0.72

# Версия приложения
APP_VERSION      = "0.3"
