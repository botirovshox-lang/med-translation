# Glossary Validator Rules

The glossary validator checks whether approved mandatory terms are used when their source terms appear in a segment.

## Inputs

```json
{
  "source_ru": "",
  "translated_en": "",
  "glossary_matches": [
    {
      "source": "",
      "preferred": "",
      "allowed": [],
      "mandatory": true,
      "domain": ""
    }
  ]
}
```

## Checks

- If `mandatory=true`, at least one preferred/allowed target term must appear.
- If an approved term has allowed variants, do not flag the allowed variants.
- If a forbidden target appears, emit a `forbidden_term` issue.
- If source phrase appears in inflected Russian form, use the matched `_form` from context builder when available.

## Output Issue Shape

```json
{
  "type": "glossary_violation",
  "severity": "major",
  "source_fragment": "",
  "target_fragment": "",
  "bad_fragment": "",
  "suggested_fragment": "",
  "explanation_ru": "",
  "detected_by": "deterministic_glossary_validator"
}
```

## Example

Source contains `контур`; translation contains `outer circuit`.

Issue:

```json
{
  "type": "glossary_violation",
  "severity": "major",
  "source_fragment": "контур",
  "bad_fragment": "circuit",
  "suggested_fragment": "contour",
  "explanation_ru": "Для медицинского описания контура следует использовать 'contour', а не 'circuit'.",
  "detected_by": "deterministic_glossary_validator"
}
```
