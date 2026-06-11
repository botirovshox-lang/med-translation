# Medical CAT Translator v5.5 Hybrid 🏥

**Hybrid medical translation CAT system** combining OpenAI's latest models (v5.5) with advanced Anthropic-based glossary management and risk assessment.

## Features

### 🔄 CAT Workflow
- **Import DOCX** → Project creation with automatic segment extraction
- **Translate** → OpenAI gpt-5.5 with glossary context and TM suggestions
- **QA** → Automated quality assessment (accuracy, terminology, completeness, numbers)
- **Back-check** → Semantic integrity verification via back-translation
- **Safety Review** → Risk-based approval workflow
- **Export DOCX** → Translation embedded back into original document

### 📚 Glossary Management
- Project-specific glossary (SQLite)
- Reference glossaries (70K+ approved medical terms)
- Forbidden translation detection and correction suggestions
- Glossary term review with AI assistance

### 🔁 Translation Memory
- **Persistent TM** (SQLite) → grows with each confirmed translation
- **MedlinePlus TM** (366 verified segments) → high-confidence reference
- Exact match detection and auto-insertion
- Fuzzy matching with relevance scoring

### 📊 Project Management
- Per-project tracking of translation progress
- Segment status workflow (new → translated → qa_done → back_checked → confirmed)
- QA and back-translation scoring
- Statistics dashboard

## Architecture

```
OpenAI gpt-5.5                           Our System (Anthropic + Local)
├─ translate_segment()          ←────→  terminology_engine (glossary lookup)
├─ qa_segment()                 ←────→  risk_engine (risk scoring)
├─ back_translate_check()       ←────→  workflow_engine (workflow routing)
├─ extract_terms_from_segment() ←────→  forbidden_checker (validation)
├─ safety_decision()            ←────→  tm_loader (MedlinePlus TM)
└─ glossary_term_review()       ←────→  terminology_loader (fast indexing)

SQLite TM (project-specific)    ←────→  TSV Glossaries (reference, 70K+ terms)
```

## Setup

### Prerequisites
- Python 3.12+
- pip

### Installation

```bash
# Clone/navigate to project
cd C:\Users\Shox\med_translation\med_translation

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env:
#   OPENAI_API_KEY=sk-proj-...
#   ANTHROPIC_API_KEY=sk-ant-...
#   DEFAULT_TRANSLATION_MODEL=gpt-5.5
#   DEFAULT_REVIEW_MODEL=gpt-5.5
```

### Launch

```bash
streamlit run app_v55.py
```

Browser opens to `http://localhost:8501`

## Usage

### 1. Create a Project
- **Tab**: Import DOCX
- **Action**: Upload DOCX file → specify source/target languages
- **Result**: Automatic segment extraction, project ID created

### 2. Translate Segments
- **Tab**: Segment Editor
- **Flow**:
  1. Select project and segment
  2. Click **Translate** (uses gpt-5.5 + glossary context)
  3. Review translation
  4. Save

### 3. Quality Assurance
- **Button**: QA
  - Runs automated quality checks (accuracy, terminology, completeness, numbers)
  - Returns scoring (0-100) and corrected version if needed
  - Status updates to `qa_done`, `needs_review`, or `failed`

### 4. Semantic Verification
- **Button**: Back-check
  - Back-translates English → Russian
  - Detects meaning drift, omissions, additions
  - Returns semantic score and verdict

### 5. Finalize
- **Button**: Confirm
  - Saves translation to persistent TM
  - Status → `confirmed`
  - Translation becomes available for future lookup

### 6. Export
- **Tab**: Export
- **Action**: Generate DOCX with translations
- **Download**: As `[ProjectTitle]_translated.docx`

## Data Storage

### Projects & Translations
```
data/cat_translator.db  (SQLite)
├── projects            (project metadata, source document path)
├── segments            (paragraphs/tables with source, translation, QA scores)
├── glossary            (project-specific terms)
└── translation_memory  (grows per confirmation)
```

### Glossaries
```
assets/glossary/
├── approved_glossary_FINAL.tsv       (10,022 approved medical terms)
├── reference_glossary_FINAL.tsv      (59,577 reference medical terms)
├── forbidden_translations_FINAL.tsv  (189 known bad translations + corrections)
└── tm_reference_FINAL.tsv            (366 MedlinePlus document pairs)
```

## API Integration

### OpenAI (gpt-5.5)
- **Translate**: `gpt-5.5` (fast, cost-effective)
- **QA & Back-check**: `gpt-5.5` (structured JSON responses via Pydantic)
- **Safety Review**: `gpt-5.5` (decision support)

### Anthropic (optional)
- **Glossary Enhancement**: Deep glossary analysis
- **Risk Scoring**: Medical risk classification
- **Workflow Routing**: Intelligent process recommendation

### Cost Optimization
- **Glossary injected as context** (not huge files)
- **TM lookups before API calls** (reuse exact matches)
- **Batch processing ready** (for bulk document translation)

## Glossaries Included

### 1. Approved Glossary (10K terms)
- Highest confidence medical terminology
- Used for strict terminology validation
- Example: `急性心肌梗塞 → acute myocardial infarction`

### 2. Reference Glossary (59K terms)
- Comprehensive medical dictionary
- Alternative translations included
- Used for lookups and suggestions

### 3. Forbidden Translations (189 pairs)
- Known bad translations → corrections
- Example: `порог → threshold` (bad) → `порог → sensory threshold` (correct)

### 4. MedlinePlus TM (366 segments)
- Extracted from MedlinePlus patient education docs
- Verified bilingual pairs (Russian ↔ English)
- High confidence, specialized medical context

## Workflow Defaults

### Suggested Process
1. **Translate** (OpenAI)
2. **QA** (structural & terminology check)
3. **Back-check** (semantic integrity)
4. **Safety Review** (risk assessment)
5. **Confirm** (save to TM if passing)

### Skipping Steps (Optimization)
- **Headings/Labels**: Translate → Confirm (skip QA)
- **100% TM Match**: Auto-insert → Confirm (skip translate)
- **Low-risk Text**: Translate → QA → Confirm (skip back-check)

## Troubleshooting

### "OPENAI_API_KEY not found"
- Set in `.env` file, restart `streamlit run app_v55.py`

### "No TM matches found"
- TM only shows ≥94% matches
- Fuzzy matching normalizes punctuation and whitespace

### "QA/Back-check failing"
- Check OPENAI_API_KEY has sufficient quota
- Try with shorter text (token limits)
- Check network connectivity

### "Project not created"
- Verify DOCX file is valid (try opening in Word first)
- Check disk space in `data/` directory

## File Structure

```
med_translation/
├── app_v55.py                      # Main Streamlit app
├── config_v55.py                   # Config (API keys, paths)
├── db.py                           # SQLite database
├── schemas.py                       # Pydantic models
├── prompts.py                       # OpenAI prompts
├── openai_client.py                # OpenAI API wrapper
├── pipeline.py                      # Translation pipeline
├── docx_cat.py                     # DOCX import/export
├── tm.py                           # TM bridge
├── terminology_*.py                # Our glossary system (reference)
├── risk_engine.py                  # Medical risk scoring (reference)
├── workflow_engine.py              # Workflow routing (reference)
├── forbidden_checker.py            # Forbidden term detection (reference)
├── .env.example                    # Config template
├── requirements.txt                # Python dependencies
├── assets/glossary/                # TSV glossary files
├── data/                           # SQLite database & temp files
└── exports/                        # Generated DOCX files
```

## Development Notes

### Adding Custom QA Rules
Edit `prompts.py` → `qa_segment_prompt()`:
```python
def qa_segment_prompt(source, target, glossary):
    return f"""
    ... existing checks ...
    NEW CHECK: Check for [your rule]
    """
```

### Integrating Risk-Based Routing
In `app_v55.py`, before QA:
```python
from risk_engine import score_risk
risk = score_risk(seg['source_text'])
if risk.level == 'HIGH':
    # Require back-check
    st.warning(f"High-risk segment: {risk.risk_reasons}")
```

### Extending Glossary
- UI: **Tab > Glossary > Add glossary term**
- Programmatic: `db.add_glossary_term(project_id, source, target, category)`

## Performance

- **Segment Editor**: <1s per segment (local SQLite)
- **Translate**: ~3-5s (OpenAI API call)
- **QA**: ~5-7s (OpenAI structured response)
- **Back-check**: ~4-6s (back-translation + analysis)
- **TM Lookup**: <100ms (local fuzzy matching)

## License & Attribution

- **v5.5 Architecture**: Based on medical_translator_cat_v5_5
- **Glossary Data**: MedlinePlus, Baldwin medical dictionary, user contributions
- **Anthropic Integration**: Custom risk & workflow engines

---

**Status**: Production Ready ✅  
**Last Updated**: 2026-05-24  
**Support**: See UPGRADE_NOTES.md and MERGE_SUMMARY.md
