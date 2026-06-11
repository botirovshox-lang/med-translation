"""
config_v55.py — Обновленная конфигурация v5.5
Поддерживает Anthropic (наш) + OpenAI (v5.5)
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# ── Модели ────────────────────────────────────────────────────────────────────
# Основные модели: OpenAI (v5.5) или наши Anthropic-функции
DEFAULT_TRANSLATION_MODEL = os.getenv('DEFAULT_TRANSLATION_MODEL', 'gpt-5.5')
DEFAULT_REVIEW_MODEL = os.getenv('DEFAULT_REVIEW_MODEL', 'gpt-5.5')

AVAILABLE_MODELS = [
    'gpt-5.5',          # OpenAI (v5.5)
    'gpt-5.4-mini',     # OpenAI
    'gpt-5.4-nano',     # OpenAI
    'claude-haiku-4-5', # Anthropic (наш, если нужно)
]

# ── Пути ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
GLOSSARY_DIR = ASSETS_DIR / "glossary"
TM_DIR = ASSETS_DIR / "tm"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

APPROVED_TSV = GLOSSARY_DIR / "approved_glossary_FINAL.tsv"
REFERENCE_TSV = GLOSSARY_DIR / "reference_glossary_FINAL.tsv"
FORBIDDEN_TSV = GLOSSARY_DIR / "forbidden_translations_FINAL.tsv"
TM_TSV = GLOSSARY_DIR / "tm_reference_FINAL.tsv"

DB_PATH = DATA_DIR / "cat_translator.db"

# ── Пороги ────────────────────────────────────────────────────────────────────
TM_AUTO_INSERT = 99
TM_GREEN = 97
TM_YELLOW = 94
FUZZY_MIN_SCORE = 0.72

# ── Приложение ────────────────────────────────────────────────────────────────
APP_VERSION = "5.5-hybrid"
APP_NAME = "Medical CAT Translator v5.5 + Anthropic"
