# Medical Translation QA Pipeline

This folder documents the proposed RU -> EN medical translation QA pipeline for the current repository. It is intentionally documentation-only: no production code, migrations, `.env` changes, or credentials are modified here.

## AUDIT SUMMARY

The active web product is a FastAPI + static React app:

- `backend/main.py` is the production API surface. It serves the frontend, stores app state in `backend/data/state.json`, handles DOCX upload, Google/GPT translation, simple QA, back-check, batch translation, glossary, TM, and export stubs.
- `frontend/js/*.jsx` is the active browser UI. `frontend/js/tab_editor_detail.jsx` shows the segment editor, QA list, risk chip, and current back-check panel.
- `med_translation/` contains the richer CAT engine from v5.5: SQLite models, prompt builders, OpenAI pipeline functions, local QA, numerical QA, consistency QA, routing, auto approval, and glossary/TM assets. It is not the primary storage path for the current FastAPI UI, but it is the best source of reusable backend logic.
- There is no Prisma schema or SQL migration framework. The legacy engine uses SQLite via `med_translation/db.py`; the active web app uses JSON state.

## CURRENT ARCHITECTURE MAP

Translation:

- Google: `backend/main.py::_deep_translate`, `_google_with_gloss`, `/api/segments/{pid}/{sid}/translate`, `/api/projects/{pid}/batch`; legacy wrapper in `med_translation/google_translate.py`.
- GPT/OpenAI: `backend/main.py::_openai_translate`; richer prompt-driven path in `med_translation/pipeline.py` + `med_translation/prompts.py` + `med_translation/openai_client.py`.
- Context: `backend/main.py::_get_context` matches glossary terms and exact TM from active JSON state.

Back-check and QA:

- Current back-check endpoint: `backend/main.py::backcheck_segment` at `POST /api/segments/{pid}/{sid}/backcheck`; it returns only `{ ok, back }`.
- Current active QA endpoint: `backend/main.py::qa_segment` at `POST /api/segments/{pid}/{sid}/qa`; it checks numbers and translation length only.
- Legacy richer QA: `med_translation/qa_orchestrator.py`, `local_qa_engine.py`, `numerical_qa_engine.py`, `consistency_engine.py`, `qa_scheduler.py`, and `pipeline.py::back_translate_check`.

Prompts:

- Current active GPT prompt is inline in `backend/main.py::_openai_translate`.
- Legacy prompt functions live in `med_translation/prompts.py`.
- New prompt files are proposed in `docs/prompts/medical_translation/`.

Glossary, termbase, TM:

- Active UI state: `STATE["glossary"]`, `STATE["tm"]` in `backend/data/state.json`.
- Seed/mock UI data: `frontend/js/data.js`.
- Large glossary/TM assets: `med_translation/assets/glossary/*.tsv` and `backup/assets/glossary/*.tsv`.
- Legacy SQLite tables: `glossary`, `translation_memory` in `med_translation/db.py`.

File handling and segmentation:

- Active DOCX upload and segmentation: `backend/main.py::upload_project`, extracting all Word paragraphs in XML order and filtering/deduplicating adjacent text.
- Legacy DOCX roundtrip: `med_translation/docx_cat.py`.

Storage:

- Active app: JSON file at `backend/data/state.json`.
- Legacy engine: SQLite at `med_translation/data/cat_translator.db` configured in `med_translation/config_v55.py`.

UI:

- Segment detail/back-check: `frontend/js/tab_editor_detail.jsx`.
- QA dashboard/backlog: `frontend/js/tab_qa_backlog.jsx`.
- Glossary/TM UI: `frontend/js/tab_glossary_tm.jsx`.
- API client: `frontend/js/api.js`.

Tests and mocks:

- Backend smoke/button test: `backend/test_all_buttons.py`.
- Legacy tests: `med_translation/test_e2e_full.py`, `test_production_e2e.py`, `_baseline_test.py`.
- Mock/demo data: `frontend/js/data.js` and seed state in `backend/main.py`.

## GAPS

- Back-check is only a visible reverse translation, not a structured semantic comparator.
- Medical English style QA is not separated from semantic back-check.
- Active QA registry is only `seg["qa"]`; there are no first-class `qa_issues`, `term_candidates`, or `qa_rules` in the active state.
- Risk is mostly preflight/static metadata, not recalculated from QA issues.
- Active GPT translation returns plain text, not structured JSON.
- Deterministic validators exist partially in legacy modules but are not unified into the active FastAPI path.
- The active app has no feature flag for new medical QA.

## PROPOSED MEDICAL TRANSLATION PIPELINE

Stage 1, Context Builder:

- Build a context package near `backend/main.py::_get_context` first, then move it into a service module when implementation starts.
- Inputs: source segment, previous/next segment, domain, document type, glossary matches, TM matches, forbidden terms, and known error patterns.
- Output: JSON context package passed to translator and QA agents.

Stage 2, Medical Translator:

- Replace or wrap plain `_openai_translate` with a JSON-returning translator under a feature flag.
- Output fields: `translated_text`, `used_glossary_terms`, `uncertainty_flags`, `translator_notes`.

Stage 3, Back-check + Comparator + Medical Style QA + Validators:

- Literal back-check returns only `backtranslated_ru`.
- Comparator checks semantic equivalence between `source_ru` and `backtranslated_ru`; it must not judge English style.
- Medical Style QA checks the English target for calques, wrong collocations, forbidden terms, and weak medical terminology.
- Deterministic validators check numbers, units, dosage, laterality, inner/outer, negation, glossary obligations, and forbidden terms in code.

Stage 4, Auto-correct / Approve / Route:

- Green: no critical/major issues, no forbidden terms, semantics preserved.
- Yellow: only medium terminology/style issues; allow up to 2 revision attempts.
- Red: critical/major semantic, numeric, negation, anatomy, diagnosis, or uncertainty issue.

## FILES TO CREATE

- Documentation: files in `docs/medical_translation/`.
- API-ready prompts: files in `docs/prompts/medical_translation/`.
- Rule docs: files in `docs/rules/medical_translation/`.

## FILES TO MODIFY

No code files should be modified until explicitly approved. Proposed later targets:

- `backend/main.py`
- `frontend/js/api.js`
- `frontend/js/tab_editor_detail.jsx`
- `frontend/js/tab_qa_backlog.jsx`
- optional new backend modules under `backend/` or `med_translation/`
- optional state/SQLite migration after choosing storage strategy

## DB CHANGES PROPOSAL

See `pipeline_design.md` and `qa_registry_design.md`. Do not run migrations yet. For the active JSON app, prototype these as JSON arrays first; for durable production, add SQLite tables or migrate active storage to SQLite.

## API CHANGES PROPOSAL

- `POST /api/segments/{pid}/{sid}/medical-qa`
- `POST /api/projects/{pid}/medical-qa/batch`
- `GET /api/projects/{pid}/qa-issues`
- `GET /api/term-candidates`
- `POST /api/term-candidates/{id}/approve|reject`

## UI CHANGES PROPOSAL

- Segment editor: replace plain back-check block with structured QA result.
- QA dashboard: group issues by severity/type and show risk color/score.
- Glossary/TM tab: add pending term candidates with approve/reject/edit.

## TEST PLAN

- Unit tests for deterministic validators: numbers, units, dosage, negation, left/right, upper/lower, inner/outer, forbidden terms.
- Prompt contract tests using mocked LLM JSON responses.
- API tests for feature-flag disabled/enabled paths.
- UI smoke tests for risk chip, issue list, and term candidate review.
- Fixtures: `bay-like -> scalloped`, `outer circuit -> outer contour`, changed negation, changed number, inner/outer mismatch.

## RISKS

- Active app and legacy engine use different storage models.
- Adding JSON QA output can break UI assumptions if not feature-flagged.
- LLM output must be schema-validated before writing to state.
- Automatic glossary/forbidden-term updates must remain pending until human approval.

## Next Step

After reviewing these docs, approve implementation of the feature-flagged MVP: structured medical QA result for one segment while preserving existing Google/GPT translation.
