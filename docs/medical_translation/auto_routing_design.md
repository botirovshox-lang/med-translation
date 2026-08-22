# Auto Routing Design

## Goal

Route each segment after structured QA so humans review only risky segments.

## Inputs

- translator JSON
- literal back-check JSON
- comparator JSON
- medical style QA JSON
- deterministic validator issues
- existing segment risk and route
- revision attempt count

## Route Colors

Green:

- no critical or major issues
- no forbidden terms
- semantic equivalence is true
- deterministic validators passed
- risk score <= 19

Yellow:

- only medium/minor terminology or style issues
- semantic equivalence is true
- no numeric, negation, anatomy, diagnosis, or uncertainty failure
- risk score 20-49
- `revision_attempts < 2`

Red:

- any critical/major semantic issue
- number/unit/dosage mismatch
- negation shift
- anatomy or laterality shift
- inner/outer mismatch
- diagnosis/symptom/finding changed
- uncertainty changed
- forbidden term with high severity
- risk score >= 50

## Revision Attempts

Maximum automatic revision attempts: 2.

After each auto revision:

1. Save previous draft.
2. Run deterministic validators.
3. Run style QA again if the prior issue was style/terminology.
4. Run comparator again if semantic risk was changed.
5. If still yellow after 2 attempts, route to human review.

## MVP Behavior

- Do not auto-confirm by default.
- Show `risk_color`, `risk_score`, issue count, and suggested correction.
- Let human approve green/yellow/red until confidence is proven.

## Later Behavior

- Auto-confirm green segments with random audit sampling.
- Auto-revise yellow once or twice.
- Always route red to human review.
