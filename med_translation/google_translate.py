"""
google_translate.py — Google Cloud Translation API wrapper.

Credentials are picked up from:
  1) GOOGLE_APPLICATION_CREDENTIALS env var (recommended)
  2) GOOGLE_TRANSLATE_API_KEY env var (for API-key style auth)

Never hardcode the service-account JSON path here — keep it out of the repo.
"""
import os
import sys

try:
    from google.cloud import translate_v2
    client = translate_v2.Client()
    GOOGLE_TRANSLATE_AVAILABLE = True
except Exception as e:
    sys.stderr.write(f"[google_translate] not available: {e}\n")
    client = None
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
