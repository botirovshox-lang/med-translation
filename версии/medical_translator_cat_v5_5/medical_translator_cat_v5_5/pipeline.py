from openai_client import call_text,call_json
from schemas import SegmentQAReport,TermExtractionResult,BackTranslationReport
from prompts import translate_segment_prompt,qa_segment_prompt,back_translation_prompt,extract_terms_prompt
def translate_segment(source,glossary,model,tm=''): return call_text(model,translate_segment_prompt(source,glossary,tm))
def qa_segment(source,target,glossary,model): return call_json(model,qa_segment_prompt(source,target,glossary),SegmentQAReport)
def back_translate_check(source,target,source_language,model): return call_json(model,back_translation_prompt(source,target,source_language),BackTranslationReport)
def extract_terms_from_segment(source,model): return call_json(model,extract_terms_prompt(source),TermExtractionResult)


def safety_decision(source_text, target_text, qa_report, back_translation_report, glossary, model):
    return call_json(
        model,
        safety_decision_prompt(source_text, target_text, qa_report, back_translation_report, glossary),
        SafetyDecisionReport
    )


def glossary_term_review(source_term, target_term, source_context, source_language, model):
    return call_text(model, glossary_term_review_prompt(source_term, target_term, source_context, source_language))
