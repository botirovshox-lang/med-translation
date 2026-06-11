"""
google_translate.py — Google Cloud Translation API обертка
"""
from google.cloud import translate_v2
import os
from pathlib import Path

# Инициализация Google Translate
credentials_path = Path(__file__).parent / "med-translation-497314-29baa963ef9b.json"
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(credentials_path)

try:
    client = translate_v2.Client()
    GOOGLE_TRANSLATE_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Google Translate недоступен: {e}")
    GOOGLE_TRANSLATE_AVAILABLE = False

def translate_google(text: str, source_lang: str = 'ru', target_lang: str = 'en') -> str:
    """Переводит текст через Google Cloud Translation API."""
    if not GOOGLE_TRANSLATE_AVAILABLE:
        raise ValueError("Google Translate API не инициализирован")

    try:
        result = client.translate(
            text,
            source_language=source_lang,
            target_language=target_lang
        )
        return result['translatedText']
    except Exception as e:
        raise ValueError(f"Google Translate ошибка: {e}")
