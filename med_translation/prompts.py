"""
prompts.py — Промпты для OpenAI API-вызовов (v5.5)
"""

def translate_segment_prompt(source, glossary, tm=''):
    """Промпт для перевода сегмента."""
    return f"""You are a senior medical textbook translator. Translate into precise academic English. Preserve meaning, numbers, units. Use glossary. Output only translation.

Glossary:
{glossary}

TM:
{tm}

Source:
{source}"""


def qa_segment_prompt(source, target, glossary):
    """QA-проверка переводов: точность, терминология, полнота, числа."""
    return f"""You are a strict medical translation QA reviewer. Check:
1. Accuracy: is meaning preserved?
2. Terminology: are terms from glossary used?
3. Completeness: is anything omitted?
4. Numerical: are all numbers/units correct?
5. Hallucination: is anything added that wasn't in source?

Return structured JSON with scores (0-100) and issues.

Glossary:
{glossary}

Source:
{source}

Translation:
{target}"""


def back_translation_prompt(source, target, source_language):
    """Обратный перевод для проверки семантической целостности."""
    return f"""Back-translate the English translation into {source_language}.
Compare the back-translation with the original.
Report semantic drift (meaning changed), omissions (words lost), additions (words added).

Return structured report only.

Original ({source_language}):
{source}

English translation:
{target}"""


def extract_terms_prompt(source):
    """Извлечение новых медицинских терминов из сегмента."""
    return f"""Extract important medical terms from this text that should be added to glossary.
For each term, provide:
- source term
- suggested English translation
- category (diagnosis, treatment, anatomy, medication, lab, procedure, other)
- confidence (0-1)

Return structured data only.

Source:
{source}"""


def safety_decision_prompt(source_text, target_text, qa_report, back_translation_report, glossary):
    """Итоговое решение: безопасен ли сегмент для подтверждения."""
    return f"""You are a medical translation safety controller.

The user is not a native English medical translator, so your job is to decide whether the segment is safe to confirm based on:
- original source
- English translation
- QA report
- back-translation report
- approved glossary

Classify:
- safe_to_confirm: meaning is preserved, no critical risk
- needs_review: probably okay but user should check listed points
- high_risk: do not confirm without expert review

Explain in the source language where possible so the user can understand.

Return structured JSON report only.

Approved glossary:
{glossary}

Original source:
{source_text}

English translation:
{target_text}

QA report:
{qa_report}

Back-translation report:
{back_translation_report}"""


def glossary_term_review_prompt(source_term, target_term, source_context, source_language):
    """Проверка предлагаемого глоссарного термина."""
    return f"""You are a medical terminology reviewer.

The user is building a glossary but is not a native English medical translator.

Review whether the proposed English medical term is appropriate.

Return a concise explanation in {source_language}:
- whether the term is safe to approve
- what it means
- when it may be wrong
- safer standard alternative if needed

Source term:
{source_term}

Proposed English term:
{target_term}

Context:
{source_context}"""
