# QA Registry Design

## Goal

Convert transient QA warnings into structured records that support review, risk scoring, term candidate generation, and future eval/fine-tuning datasets.

## Registration Flow

When any QA stage finds an issue:

1. Normalize it into the common `qa_issue` shape.
2. Save it to the segment's issue list in the MVP.
3. Later, write it to a durable `qa_issues` table.
4. If issue type is `literal_calque`, `terminology`, `forbidden_term`, or `weak_collocation`, upsert a `term_candidate`.
5. Increase candidate confidence at repeat counts >= 3.
6. Mark as high priority at repeat counts >= 10.
7. Never promote candidates into production glossary or forbidden terms without approval.

## Common QA Issue Shape

```json
{
  "id": "optional",
  "segment_id": 123,
  "file_id": "optional",
  "issue_type": "literal_calque",
  "severity": "major",
  "source_fragment": "бухтообразный",
  "target_fragment": "bay-like",
  "bad_fragment": "bay-like",
  "suggested_fragment": "scalloped",
  "explanation_ru": "В радиологическом английском 'bay-like' звучит как буквальная калька; лучше 'scalloped' или 'irregular with recesses'.",
  "detected_by": "medical_style_qa",
  "engine": "gpt-4o",
  "status": "open",
  "created_at": "ISO-8601"
}
```

## Term Candidate Shape

```json
{
  "source_phrase": "бухтообразный",
  "bad_en": "bay-like",
  "preferred_en": "scalloped",
  "allowed_en": ["scalloped", "irregular with recesses"],
  "forbidden_en": ["bay-like"],
  "domain": "radiology",
  "trigger_words": ["контур", "полость", "стенка"],
  "confidence": 0.4,
  "occurrences": 1,
  "status": "pending"
}
```

## UI Proposal

QA dashboard:

- show issue type, severity, segment id, explanation, and suggested correction.
- filter by semantic vs style vs deterministic.

Glossary/TM tab:

- add `Term Candidates` subview.
- show source phrase, bad EN, preferred EN, occurrence count, examples, approve/reject/edit.

## Storage Strategy

MVP:

- Extend active JSON state with segment fields: `qa_result`, `qa_issues`, `risk_score`, `risk_color`, `term_candidates`.

Production:

- Add durable SQLite tables or migrate the active app from JSON state to the existing `med_translation/db.py` SQLite model.
