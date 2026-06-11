def translate_segment_prompt(source,glossary,tm=''):
    return f'You are a senior medical textbook translator. Translate into precise academic English. Preserve meaning, numbers, units. Use glossary. Output only translation.\nGlossary:\n{glossary}\nTM:\n{tm}\nSource:\n{source}'
def qa_segment_prompt(source,target,glossary):
    return f'You are a strict medical translation QA reviewer. Return structured QA. Check accuracy, terminology, completeness, numbers, hallucination, glossary.\nGlossary:\n{glossary}\nSource:\n{source}\nTranslation:\n{target}'
def back_translation_prompt(source,target,source_language):
    return f'Back-translate the English translation into {source_language}, compare with original, and report semantic drift, omissions, additions. Return structured report only.\nOriginal:\n{source}\nEnglish:\n{target}'
def extract_terms_prompt(source):
    return f'Extract important medical terms for glossary. Return structured data only.\nSource:\n{source}'


def safety_decision_prompt(source_text, target_text, qa_report, back_translation_report, glossary):
    return f"""
You are a medical translation safety controller.

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

Return structured report only.

Approved glossary:
{glossary}

Original source:
{source_text}

English translation:
{target_text}

QA report:
{qa_report}

Back-translation report:
{back_translation_report}
"""


def glossary_term_review_prompt(source_term, target_term, source_context, source_language):
    return f"""
You are a medical terminology reviewer.

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
{source_context}
"""
