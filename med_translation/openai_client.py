"""
openai_client.py — OpenAI API-вызовы для v5.5 функций (QA, back-check, etc.)
"""
from openai import OpenAI
from config_v55 import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def call_text(model, prompt):
    """Простой текстовый ответ от OpenAI."""
    if not client:
        raise ValueError("OPENAI_API_KEY не установлен в .env")
    # Примечание: OpenAI API синтаксис может отличаться в зависимости от версии SDK
    # Используем стандартный chat.completions.create() вместо responses API
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return r.choices[0].message.content

def call_json(model, prompt, schema_model):
    """Структурированный JSON-ответ от OpenAI."""
    if not client:
        raise ValueError("OPENAI_API_KEY не установлен в .env")
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    import json
    try:
        data = json.loads(r.choices[0].message.content)
        return data
    except (json.JSONDecodeError, ValueError) as e:
        # Fallback: вернуть пустой результат нужной структуры
        return schema_model().model_dump() if hasattr(schema_model, 'model_dump') else {}
