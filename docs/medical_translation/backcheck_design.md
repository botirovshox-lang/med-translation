# Back-check Design

## Principle

Back-check is not medical English QA. It only helps detect semantic drift by translating the English target back into Russian as literally as possible.

## Current State

`backend/main.py::backcheck_segment` returns only a plain reverse translation:

```json
{
  "ok": true,
  "back": "..."
}
```

The UI in `frontend/js/tab_editor_detail.jsx` displays this string in the segment detail panel.

## Proposed Split

### 1. Literal Back-check

Input:

```json
{
  "translated_en": "The outer circuit of the cavity wall is indistinct, the inner is uneven, bay-like."
}
```

Output:

```json
{
  "backtranslated_ru": "Наружная цепь/контур стенки полости нечеткий, внутренняя неровная, бухтообразная."
}
```

Rules:

- Preserve awkwardness.
- Do not repair English before translating.
- Do not infer the original Russian.

### 2. Semantic Comparator

Input:

```json
{
  "source_ru": "Наружный контур стенки полости нечеткий, внутренний — неровный, «бухтообразный».",
  "translated_en": "The outer circuit of the cavity wall is indistinct, the inner is uneven, bay-like.",
  "backtranslated_ru": "Наружный контур стенки полости нечеткий, внутренний неровный, бухтообразный."
}
```

Output:

```json
{
  "semantic_equivalence": true,
  "risk_score_addition": 0,
  "issues": []
}
```

The comparator may pass this example semantically. That is expected. The Medical Style QA stage must catch `outer circuit` and `bay-like`.

## Issue Types

- omission
- addition
- negation_shift
- anatomy_shift
- laterality_shift
- upper_lower_shift
- inner_outer_shift
- number_unit_dosage_mismatch
- diagnosis_symptom_finding_changed
- uncertainty_changed

## API Proposal

Keep existing endpoint:

- `POST /api/segments/{pid}/{sid}/backcheck`

Add structured endpoint:

- `POST /api/segments/{pid}/{sid}/medical-qa`

When stable, `/backcheck` may optionally include structured fields while retaining `back` for backward compatibility.
