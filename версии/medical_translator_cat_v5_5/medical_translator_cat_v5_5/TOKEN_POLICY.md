# Token Optimization Policy v5.2

## Main idea

Do not run every agent on every segment.

The expensive checks should be conditional.

## Recommended workflow

### Cheap path
Use for headings, short labels, repeated segments, simple paragraphs.

1. Find TM
2. Translate
3. Confirm manually if obvious

No QA / no back-check unless suspicious.

### Standard path
Use for normal textbook paragraphs.

1. Translate
2. Medical QA
3. Confirm if QA pass

Back-check only if:
- QA score < threshold
- source is complex
- you personally feel unsure

### Strict path
Use for definitions, tables, dosage-heavy text, diagnostic criteria.

1. Translate
2. Medical QA
3. Back-check
4. Confirm manually

### Very strict path, planned for v2
Use only for high-risk segments.

1. Translate
2. Medical QA
3. Numerical Integrity
4. Hallucination Check
5. Dual Review only if conflict/low score

## Token-saving rules

- Do not extract glossary terms from every segment. Use it only for first pages/chapter starts or new terminology-heavy paragraphs.
- Do not run back-check on every segment.
- Do not run dual review on every segment.
- Do not QA headings, figure labels, very short segments unless needed.
- Only 100% exact TM matches should be auto-filled without OpenAI call.
- Confirmed segments should never be reprocessed unless manually unlocked.


## v5.3 TM safety update

For medical translation:

- 100% exact match: can be applied without API call.
- 97–99% fuzzy match: suggestion only, no auto-apply.
- Below 97%: suggestion only and treat with caution.

Reason:
High fuzzy score can hide medically critical differences:
- acute vs chronic
- with vs without
- increase vs decrease
- negative vs positive
- stage I vs stage II
- mg vs mcg


## v5.4 safety status cost rule

Safety status is another API call. Do not run it for every tiny heading.

Use it for:
- medical definitions
- table cells with numbers
- long paragraphs
- segments where QA or back-check gave warning
- terms you personally do not understand

Skip it for:
- obvious headings
- figure labels
- repeated exact TM matches
