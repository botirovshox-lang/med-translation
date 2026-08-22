# Medical Translation Pipeline Design

## Goal

Build a safe, staged RU -> EN medical translation pipeline that reduces manual back-check reading by producing structured QA, risk scores, and pending terminology candidates.

## Current Places To Integrate

- Context builder: start near `backend/main.py::_get_context`, because it already finds glossary hits and exact TM matches for the active web app.
- Translator: wrap `backend/main.py::_openai_translate` under `MEDICAL_TRANSLATION_QA_ENABLED`.
- Back-check endpoint: evolve `backend/main.py::backcheck_segment` or add a new endpoint so existing UI behavior remains intact.
- Validators: reuse ideas from `med_translation/local_qa_engine.py`, `numerical_qa_engine.py`, and `db.py::check_forbidden_translations`.
- Storage: prototype in active JSON state first; propose SQLite tables before production migration.

## Stage 1: Context Builder

Input:

```json
{
  "source_ru": "...",
  "previous_segment_ru": "...",
  "next_segment_ru": "...",
  "document_domain": "radiology",
  "document_type": "clinical_report",
  "glossary_matches": [],
  "tm_matches": [],
  "forbidden_terms": [],
  "known_error_patterns": []
}
```

Output:

```json
{
  "source_ru": "...",
  "context_before": "...",
  "context_after": "...",
  "domain": "radiology",
  "document_type": "clinical_report",
  "approved_terms": [],
  "forbidden_terms": [],
  "similar_approved_segments": [],
  "style_rules": [],
  "known_risks": []
}
```

## Stage 2: Medical Translator

Translator receives the context package, not only a raw string. It returns JSON:

```json
{
  "translated_text": "The outer contour of the cavity wall is indistinct, while the inner contour is irregular and scalloped.",
  "used_glossary_terms": ["contour"],
  "uncertainty_flags": [],
  "translator_notes": []
}
```

## Stage 3: QA Stack

1. Literal Back-check Agent: EN -> RU, intentionally literal.
2. Back-check Comparator Agent: semantic equivalence only.
3. Medical Style QA Agent: English medical style and terminology only.
4. Deterministic Validators: code checks for numbers, units, laterality, negation, forbidden terms, and glossary requirements.

## Stage 4: Routing

Risk score starts at 0 and accumulates additions:

- critical: +50
- major: +30
- medium: +15
- minor: +5
- deterministic numeric/negation/anatomy failure: force red

Colors:

- green: score 0-19 and no critical/major issues
- yellow: score 20-49 with auto-correctable medium/minor issues only
- red: score >= 50 or any critical/major semantic or deterministic safety issue

## Minimal Data Model Proposal

`translation_segments`:

```text
id
file_id
source_ru
draft_en
corrected_en
final_en
backtranslated_ru
status
risk_color
risk_score
engine_translator
engine_backcheck
engine_qa
revision_attempts
created_at
updated_at
```

`qa_issues`:

```text
id
segment_id
file_id
issue_type
severity
source_fragment
target_fragment
bad_fragment
suggested_fragment
explanation_ru
detected_by
engine
status
created_at
```

`term_candidates`:

```text
id
source_pattern
source_phrase
bad_en
preferred_en
allowed_en
forbidden_en
domain
trigger_words
confidence
source_segment_id
source_issue_id
status
created_at
updated_at
```

`qa_rules`:

```text
id
rule_name
source_pattern
target_pattern
trigger_words
issue_type
severity
suggestion
is_active
created_at
updated_at
```

## Implementation Plan

1. Add `MEDICAL_TRANSLATION_QA_ENABLED=false` default behavior.
2. Add backend service functions for context package, LLM JSON calls, deterministic validators, risk scoring, and issue registration.
3. Add a non-breaking `/medical-qa` endpoint before replacing `/backcheck`.
4. Store QA result in segment-level JSON fields in active state for MVP.
5. Add optional SQLite tables only after approving storage strategy.
6. Update UI to render structured QA when present, falling back to plain back-check.
7. Add tests with mocked LLM responses and deterministic validator fixtures.
8. Rollback by disabling the feature flag and leaving existing `/translate`, `/qa`, and `/backcheck` behavior intact.
