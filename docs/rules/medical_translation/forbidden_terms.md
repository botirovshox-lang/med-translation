# Forbidden Terms Rules

Forbidden terms must be checked deterministically before or after LLM QA. They may also be provided to the LLM as context, but code is the source of enforcement.

## Bootstrap Examples

| Bad English | Preferred English | Domain | Issue Type | Severity | Notes |
|---|---|---|---|---|---|
| outer circuit | outer contour | radiology | terminology | major | `контур` in medical/radiology context is usually `contour`. |
| bay-like | scalloped; irregular with recesses | radiology | literal_calque | major | Literal calque for `бухтообразный`. |
| lung root | hilar region; hilum | radiology | terminology | major | Choose based on context. |
| enlightenment | radiolucency; lucency | radiology | terminology | major | Common literal mistranslation. |
| decay | cavitation; breakdown; destruction | radiology/pathology | terminology | major | Context decides preferred term. |
| hearth | focus; lesion; opacity | radiology | terminology | major | Common literal mistranslation of `очаг`. |

## Deterministic Matching

- Normalize case and whitespace.
- Match phrase boundaries where possible.
- Record `bad_fragment`, `suggested_fragment`, and source rule id.
- Do not silently auto-replace in final text without QA record.

## Candidate Promotion

- Newly discovered bad terms go to `term_candidates.status = pending`.
- Repeat count >= 3 increases confidence.
- Repeat count >= 10 marks high priority.
- Human approval is required before production enforcement.
