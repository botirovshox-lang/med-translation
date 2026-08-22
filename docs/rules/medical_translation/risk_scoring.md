# Risk Scoring Rules

Risk score is a segment-level aggregate used for routing. It must combine LLM QA findings and deterministic validator results.

## Severity Additions

| Severity | Score |
|---|---:|
| critical | 50 |
| major | 30 |
| medium | 15 |
| minor | 5 |

## Forced Red Conditions

- number mismatch
- unit mismatch
- dosage mismatch
- negation shift
- left/right mismatch
- upper/lower mismatch
- inner/outer mismatch
- anatomy shift
- diagnosis/symptom/finding changed
- uncertainty changed
- critical forbidden term

## Colors

Green:

- score 0-19
- no critical/major issue
- semantic equivalence true
- deterministic validators passed

Yellow:

- score 20-49
- only medium/minor style or terminology issues
- can auto-correct
- revision attempts < 2

Red:

- score >= 50
- any forced red condition
- any critical/major semantic issue

## Output

```json
{
  "risk_score": 30,
  "risk_color": "yellow",
  "routing_reason": "Major medical style terminology issue; semantics preserved.",
  "human_review_required": false,
  "auto_revision_allowed": true
}
```

## Example

`outer circuit` + `bay-like`:

- semantic comparator may add 0
- medical style QA adds 30 or 60 depending issue aggregation
- route yellow if semantics are preserved and auto-correction is safe

Changed negation:

- forced red regardless of score
