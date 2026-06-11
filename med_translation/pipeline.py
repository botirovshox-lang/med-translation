"""
pipeline.py — Функции обработки текста (translate, QA, back-check, extract terms)
Использует OpenAI для v5.5 функций.
"""
from openai_client import call_text, call_json
from schemas import SegmentQAReport, TermExtractionResult, BackTranslationReport, SafetyDecisionReport
from prompts import (
    translate_segment_prompt,
    qa_segment_prompt,
    back_translation_prompt,
    extract_terms_prompt,
    safety_decision_prompt,
    glossary_term_review_prompt,
)
from db import check_forbidden_translations
import json
import html
import re


def clean_text(text):
    """Очищает текст от HTML-сущностей и управляющих символов."""
    text = html.unescape(text)
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()


def translate_segment(source, glossary, model, tm=''):
    """Переводит сегмент, используя OpenAI."""
    # Очищаем текст от HTML-сущностей и управляющих символов
    source_clean = clean_text(source)
    prompt = translate_segment_prompt(source_clean, glossary, tm)
    return call_text(model, prompt)


def qa_segment(source, target, glossary, model):
    """QA-проверка переведённого сегмента."""
    # Очищаем текст от HTML-сущностей
    source_clean = clean_text(source)
    target_clean = clean_text(target)
    prompt = qa_segment_prompt(source_clean, target_clean, glossary)
    try:
        result = call_json(model, prompt, SegmentQAReport)
    except Exception as e:
        # Fallback: возвращаем минимальный результат
        result = {
            'accuracy_score': 50.0,
            'terminology_score': 50.0,
            'completeness_score': 50.0,
            'numerical_score': 50.0,
            'overall_score': 50.0,
            'critical_issues': [f'Error in QA: {str(e)}'],
            'minor_issues': [],
            'corrected_translation': target,
            'verdict': 'warning'
        }

    # Проверка запрещённых переводов
    forbidden = check_forbidden_translations(target)
    if forbidden:
        for item in forbidden:
            msg = f"⚠️ Forbidden term detected: '{item['term']}' ({item['reason']})"
            if 'critical_issues' not in result:
                result['critical_issues'] = []
            result['critical_issues'].append(msg)
            result['verdict'] = 'failed'
            result['overall_score'] = max(0, result.get('overall_score', 50) - 20)

    return result


def back_translate_check(source, target, source_language, model):
    """Обратный перевод и сравнение для проверки целостности."""
    # Очищаем текст от HTML-сущностей
    source_clean = clean_text(source)
    target_clean = clean_text(target)
    prompt = back_translation_prompt(source_clean, target_clean, source_language)
    try:
        return call_json(model, prompt, BackTranslationReport)
    except Exception as e:
        return {
            'back_translation': '',
            'semantic_score': 50.0,
            'meaning_drift': [f'Error: {str(e)}'],
            'omissions': [],
            'additions': [],
            'verdict': 'warning'
        }


def extract_terms_from_segment(source, model):
    """Извлечение новых медицинских терминов из сегмента."""
    prompt = extract_terms_prompt(source)
    try:
        return call_json(model, prompt, TermExtractionResult)
    except Exception as e:
        return {'terms': []}


def safety_decision(source_text, target_text, qa_report, back_translation_report, glossary, model):
    """Итоговое решение о безопасности сегмента."""
    qa_str = json.dumps(qa_report, ensure_ascii=False, indent=2) if isinstance(qa_report, dict) else qa_report
    bt_str = json.dumps(back_translation_report, ensure_ascii=False, indent=2) if isinstance(back_translation_report, dict) else back_translation_report

    prompt = safety_decision_prompt(source_text, target_text, qa_str, bt_str, glossary)
    try:
        return call_json(model, prompt, SafetyDecisionReport)
    except Exception as e:
        return {
            'safety_status': 'needs_review',
            'reason': f'Error in safety check: {str(e)}',
            'what_user_should_check': ['Review manually'],
            'source_meaning_summary': '',
            'back_translation_meaning_summary': '',
            'glossary_risks': [],
            'qa_risks': []
        }


def glossary_term_review(source_term, target_term, source_context, source_language, model):
    """Проверка предлагаемого глоссарного термина."""
    prompt = glossary_term_review_prompt(source_term, target_term, source_context, source_language)
    return call_text(model, prompt)
