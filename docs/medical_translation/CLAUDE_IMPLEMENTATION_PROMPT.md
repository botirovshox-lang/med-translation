# Claude Code Implementation Prompt

You are working in `C:\Users\Shox\med_translation` as a senior engineer. Implement a feature-flagged structured medical translation QA pipeline for the RU -> EN Medical CAT Translator.

## Project Summary

The active app is FastAPI + static React:

- Backend: `backend/main.py`
- Frontend: `frontend/js/*.jsx`
- Active persistence: JSON state at `backend/data/state.json`
- Legacy/reusable engine: `med_translation/` with SQLite, prompts, pipeline, local QA, numerical QA, consistency QA, routing, and glossary assets.

Do not modify `.env`, tokens, keys, or production credentials. Do not delete current Google/GPT translation behavior. New logic must be behind `MEDICAL_TRANSLATION_QA_ENABLED`.

## Current Architecture Found

- Google translation: `backend/main.py::_deep_translate`, `_google_with_gloss`, `/api/segments/{pid}/{sid}/translate`, `/api/projects/{pid}/batch`.
- GPT translation: `backend/main.py::_openai_translate`; legacy OpenAI pipeline in `med_translation/pipeline.py`.
- Back-check: `backend/main.py::backcheck_segment` returns only plain `{ ok, back }`.
- Active QA: `backend/main.py::qa_segment` checks only numbers and length.
- Context: `backend/main.py::_get_context` reads active `STATE["glossary"]` and `STATE["tm"]`.
- UI back-check: `frontend/js/tab_editor_detail.jsx::openBack`.
- UI QA display: `frontend/js/tab_editor_detail.jsx::QAPane` and `frontend/js/tab_qa_backlog.jsx`.
- Storage: active JSON state; legacy SQLite in `med_translation/db.py`.

## Files To Modify

- `backend/main.py`
- `frontend/js/api.js`
- `frontend/js/tab_editor_detail.jsx`
- `frontend/js/tab_qa_backlog.jsx`
- tests under `backend/` or `med_translation/`

## New Files To Create

Prefer small backend modules if the change grows:

- `backend/medical_qa.py`
- `backend/medical_validators.py`
- `backend/medical_risk.py`
- `backend/medical_registry.py`
- `backend/test_medical_qa.py`

Use docs/prompts as prompt source or copy their text into service constants if file loading is too risky.

## Desired Pipeline

1. Context builder: source, previous/next, domain, document type, glossary matches, TM matches, forbidden terms, known error patterns.
2. Medical translator: returns JSON with `translated_text`, `used_glossary_terms`, `uncertainty_flags`, `translator_notes`.
3. QA stack:
   - literal back-check EN -> RU
   - semantic comparator
   - medical style QA
   - deterministic validators
4. Routing:
   - green, yellow, red
   - max 2 revision attempts
   - do not auto-promote term candidates

## DB / Storage Changes

MVP: store structured QA on the existing segment dict:

```json
{
  "qa_result": {},
  "qa": [],
  "qa_issues": [],
  "risk_score": 0,
  "risk_color": "green",
  "backtranslated_ru": "",
  "term_candidates": []
}
```

Do not apply SQL migrations without explicit user approval. Later proposal: add durable `translation_segments`, `qa_issues`, `term_candidates`, and `qa_rules`.

## API Changes

Add without breaking existing endpoints:

- `POST /api/segments/{pid}/{sid}/medical-qa`
- optional `POST /api/projects/{pid}/medical-qa/batch`
- optional `GET /api/projects/{pid}/qa-issues`
- optional term candidate approval endpoints

Keep `/api/segments/{pid}/{sid}/backcheck` returning `{ ok, back }`.

## UI Changes

- Add `window.API.medicalQA(pid, sid)`.
- In segment detail, show structured QA result when present: risk color/score, semantic issues, style issues, deterministic issues, suggested correction.
- Keep current plain back-check panel as fallback.
- In QA dashboard, list normalized `qa_issues`.
- Add term candidates view only if time allows.

## Testing Plan

- Unit tests for validators:
  - `bay-like -> scalloped`
  - `outer circuit -> outer contour`
  - changed negation
  - changed number
  - inner/outer mismatch
- API tests for feature flag disabled/enabled.
- Mock LLM JSON responses; do not require real OpenAI in tests.
- Verify existing Google/GPT translation endpoints still work.

## Safety Constraints

- Do not touch `.env`.
- Do not remove existing functions.
- Do not make new QA mandatory unless `MEDICAL_TRANSLATION_QA_ENABLED=true`.
- Validate and sanitize all LLM JSON before writing to state.
- All generated glossary/forbidden candidates must remain `pending`.

## Acceptance Criteria

1. Back-check can create structured QA result, not only a reverse translation.
2. Medical Style QA catches literal calques and forbidden terms.
3. Issues are saved in a QA registry shape.
4. Repeating issues create pending term candidates.
5. Risk score is calculated automatically.
6. Green/yellow/red status is visible at segment level.
7. Existing Google/GPT translation continues to work.
8. New logic is controlled by `MEDICAL_TRANSLATION_QA_ENABLED`.
9. Test fixtures cover bay-like, outer circuit, negation, number, and inner/outer mismatch.
10. Documentation explains how to run batch QA.
