# Optimization Notes

## What was changed in v5.2

1. Added `TOKEN_POLICY.md`.
2. Added sidebar token mode:
   - cheap
   - standard
   - strict
3. Added guidance in Segment Editor.
4. Added `Apply TM without API` button:
   - only if TM match score == 100, it fills translation without OpenAI call.
5. Added Token Policy tab.

## What still needs coding in v2

- true batch translation
- batch QA
- automatic routing by complexity
- skip QA for headings/short labels
- numeric check only for segments with numbers
- hallucination check only when QA/back-check warning
- dual review only when contradiction or low score


## v5.3 change

Changed TM auto-apply threshold:

- before: >= 95
- now: exactly 100

This is safer for medical textbooks.
