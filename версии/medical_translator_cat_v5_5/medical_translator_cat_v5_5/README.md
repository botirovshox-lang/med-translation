# Medical Translator CAT v5.1

Adds back-translation semantic check + backlog. Use gpt-5.5, not gpt-5.5-thinking.

Run:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```


## v5.2 token optimization

Added token policy and cheaper workflow logic:

- Back-check is optional and should be used only for suspicious/high-risk segments.
- Term extraction is optional; don't run it on every segment.
- Exact TM can be reused without translation call.
- QA is recommended for normal paragraphs, but can be skipped for headings/labels.
- Strict checks should be reserved for definitions, tables, numbers, dosage-heavy content.

See `TOKEN_POLICY.md`.


## v5.3 update

TM auto-apply is now restricted to 100% exact matches only.

Fuzzy matches such as 97–99% are shown as suggestions but are not applied automatically.


## v5.4 update

Added user-friendly approval layer:

- Safety status per segment:
  - safe_to_confirm
  - needs_review
  - high_risk
- Safety report explains in understandable source-language terms what to check.
- Confirm button blocks high_risk segments.
- Glossary tab now has AI term review so the user can check whether an English term is safe before approving it.

Recommended segment workflow:

1. Translate
2. QA
3. Back-check
4. Safety status
5. Confirm only if safe_to_confirm or manually acceptable


## v5.5 state

Current version includes:
- DOCX CAT workflow
- TM
- glossary
- QA
- back-check
- safety status
- glossary review
- token optimization
- TM safety rules

Backlog updated with:
- intelligent workflow routing
- risk analyzer
- batch processing
- numerical integrity
- hallucination detection
