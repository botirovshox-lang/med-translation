# 📦 Medical CAT Translator v5.5 — Release Notes

## Current Status: ✅ PRODUCTION READY

**Version**: 5.5-update  
**Release Date**: 2026-05-24  
**Python**: 3.14+  
**Framework**: Streamlit 1.57.0+

---

## 🎯 What's New

### Confirm & Clear Buttons Implementation

The Segment Editor now features fully functional **Confirm (✅)** and **Clear (❌)** buttons for managing translations.

#### ✅ Confirm Button
- **Location**: Last column in each segment row
- **Function**: Saves translation and adds to Translation Memory (TM)
- **Action**: Changes status to `confirmed` and creates TM entry
- **When to use**: After translation is complete and QA approved

#### ❌ Clear Button  
- **Location**: Last column in each segment row
- **Function**: Removes translation and resets segment
- **Action**: Clears Target field and sets status to `new`
- **When to use**: If translation needs to be redone

---

## ✨ Key Features (Complete List)

### 1. **Segment Editor** (Two-column layout)

**Left Column (70%)**:
- Pagination: 20 segments per page
- Interactive table with 14 columns:
  - Select button (✓)
  - Segment ID
  - Source text (expandable)
  - Target text (editable, auto-save)
  - TM match % and search button (🔍)
  - Translation buttons: GPT (▶️), Google (🌐)
  - QA check (✓)
  - Back-check (⤴️)
  - Status display
  - QA score
  - **Confirm button (✅)** ← NEW
  - **Clear button (❌)** ← NEW

**Right Column (30%)**:
- Selected segment details
- Source text (expandable)
- Three tabs:
  - 🔍 TM: Translation Memory matches
  - ✓ QA: Quality assessment results
  - ⤴️ Back: Back-translation verification

### 2. **Translation APIs**

- **OpenAI GPT-5.5**: Primary translator with glossary injection
- **Google Cloud Translation**: Alternative translator (API v2)
- Both inject medical glossary terms into prompts

### 3. **Translation Memory (TM)**

- **Source**: MedlinePlus medical documents (~695 pairs)
- **100% Match Auto-insert**: Automatic insertion when perfect match found
- **TM Management**: 
  - Search via 🔍 button
  - Import custom TM via tab
  - Auto-update when confirming translations (✅)

### 4. **Glossary System**

- **Source**: 500+ approved medical terms
- **Scope**: Russian ↔ English
- **Usage**: Injected into all translation prompts
- **Management**: Add/edit via Glossary tab

### 5. **Quality Assurance (QA)**

- **Checks**: Accuracy, terminology, completeness, numerical values
- **Metrics**: 0-100 score with detailed issue reporting
- **Statuses**: `qa_done` (pass) or `needs_review` (fail)
- **Storage**: Full report in database (JSON)

### 6. **Back-translation Check**

- **Purpose**: Verify semantic meaning preservation
- **Method**: Translate target back to source and compare
- **Metrics**: Semantic score, meaning drift, omissions, additions
- **Statuses**: `back_checked` (pass) or `needs_review` (fail)

### 7. **Export & Reports**

- **DOCX Export**: Confirmed translations exported to original DOCX
- **Metrics**: Total segments, translated count
- **Tracking**: All changes logged with timestamps

---

## 🗂️ File Structure

```
med_translation/
├── app_v55.py                    # Main Streamlit application
├── db.py                         # Database functions
├── config_v55.py                 # Configuration & constants
├── docx_cat.py                   # DOCX import/export
├── pipeline.py                   # Translation + QA pipeline
├── tm.py                         # Translation Memory search
├── google_translate.py            # Google Cloud API wrapper
├── openai_client.py              # OpenAI API wrapper
├── requirements.txt              # Python dependencies
├── med_translation_db.sqlite3    # SQLite database (auto-created)
│
├── docs/
│   ├── INDEX.md                  # Documentation index
│   ├── CONTEXT.md                # Architecture overview
│   ├── CHANGELOG.md              # Version history
│   ├── BUTTONS_GUIDE.md          # User guide for buttons
│   ├── BUTTONS_IMPLEMENTATION.md # Technical documentation
│   └── ... (other docs)
│
└── data/
    ├── approved_glossary.tsv     # Medical glossary
    ├── forbidden_terms.tsv       # Terms to avoid
    ├── medlineplus_tm.tsv        # Translation Memory
    └── med-translation-*.json    # Google Cloud credentials
```

---

## 🚀 Quick Start

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Setup Google Cloud

1. Create project in Google Cloud Console
2. Enable Cloud Translation API v2
3. Create service account with translation permissions
4. Download JSON credentials file
5. Place in project directory as `med-translation-*.json`

### 3. Run Application

```bash
streamlit run app_v55.py
```

Application opens at `http://localhost:8501`

### 4. Workflow

```
1. Create/open project via "📥 Import DOCX" tab
2. Go to "✏️ Segment Editor" tab
3. For each segment:
   a. Click ✓ to select it
   b. Click 🔍 to find TM matches
   c. Click ▶️ (GPT) or 🌐 (Google) to translate
   d. Click ✓ to run QA check
   e. Fix issues if QA shows `needs_review`
   f. Click ✅ to confirm & save
4. Export as DOCX via "📤 Export Project" tab
```

---

## 🧪 Testing

All components have been tested:

- ✅ Database operations (CRUD for segments, projects, glossary, TM)
- ✅ Confirm function (status change + TM insertion)
- ✅ Clear function (text removal + status reset)
- ✅ Translation workflows (OpenAI and Google)
- ✅ Session state management (caching)
- ✅ UI rendering (14-column table structure)
- ✅ Import/export operations

### Run Tests

```bash
# Test database functions
python test_buttons.py

# Test full workflow
python test_full_workflow.py
```

---

## 📊 Database Schema

### segments table
```
- id (int, PK)
- project_id (int, FK)
- source_text (text)
- target_text (text) ← edited in UI
- status (text): 'new', 'translated', 'qa_done', 'needs_review', 'confirmed', 'back_checked'
- qa_report (text, JSON)
- qa_score (real)
- back_translation (text)
- back_translation_report (text, JSON)
- tm_match_score (real)
- tm_suggestion (text)
- created_at, updated_at (text, ISO)
```

### translation_memory table
```
- id (int, PK)
- source_hash (text, UNIQUE)
- source_text (text)
- target_text (text)
- domain (text): always 'medical'
- created_at, updated_at (text, ISO)
```

---

## 🔧 Configuration

### Required Files

1. **med-translation-*.json** — Google Cloud service account credentials
2. **approved_glossary.tsv** — Medical terms (source | target)
3. **medlineplus_tm.tsv** — Translation Memory (source | target)
4. **forbidden_terms.tsv** — Terms to flag during QA

### Optional

- `config_v55.py` — Model names, API keys, paths
- `stage_map.json` — Runtime configuration (if needed)

---

## 🐛 Known Issues & Limitations

### Google Cloud API
- Initial setup requires billing account to be active
- API activation takes 5-10 minutes to propagate
- Rate limits apply to free tier (500K chars/month)

### UI
- Segment table is limited to 20 items per page for performance
- Right panel updates only when segment is selected
- Button styling follows Streamlit defaults

### Translation
- OpenAI requires active API credits
- Large documents may take time to process
- Glossary injection limited to ~500 top terms for token efficiency

---

## 📚 Documentation

See `docs/INDEX.md` for complete documentation index:

- **CONTEXT.md** — Full architecture and design decisions
- **BUTTONS_GUIDE.md** — User manual for buttons
- **BUTTONS_IMPLEMENTATION.md** — Technical implementation details
- **CHANGELOG.md** — Version history
- **BACKLOG.md** — Upcoming features

---

## 💡 Tips & Best Practices

### Optimal Translation Workflow

1. **Use TM First**: Click 🔍 before translating
   - If match is 100%, auto-fills correctly
   - Saves API calls and money

2. **Combine Translators**: Try both GPT and Google
   - Compare quality and pick better option
   - Use as fallback if one fails

3. **Always Run QA**: Click ✓ QA after each translation
   - Catches terminology errors early
   - Prevents bad translations from being confirmed

4. **Fix Issues Promptly**: When status is `needs_review`
   - Edit Target and run QA again
   - Don't accumulate unfixed segments

5. **Confirm Only When Ready**: Click ✅ only after:
   - Translation is complete
   - QA passed (status `qa_done`)
   - Manual review done

6. **Use Clear Sparingly**: Click ❌ only when:
   - Translation is objectively wrong
   - Starting over makes sense
   - You're certain about resetting

### Performance Tips

- Work on one page at a time (20 segments)
- Close browser tabs with heavy JavaScript
- Restart Streamlit if UI becomes sluggish
- Clear browser cache if buttons don't respond

---

## 🔐 Security Notes

- Google Cloud credentials stored locally (never committed to git)
- SQLite database contains all translations (back up regularly)
- OpenAI API key should be in `.env` file (not in code)
- All API calls go through official clients, no raw requests

---

## 📝 Release Checklist

- [x] Confirm button implemented and tested
- [x] Clear button implemented and tested
- [x] Table header fixed (14 columns)
- [x] Database functions verified
- [x] UI rendering correct
- [x] Documentation complete
- [x] Import validation passed
- [x] Full workflow test passed
- [x] Google Cloud API working

---

## 🎉 What's Next?

Potential future enhancements:

1. Batch operations (confirm/QA multiple segments)
2. Segment history/undo
3. User roles and permissions
4. Advanced TM search (fuzzy matching)
5. Terminology suggestions from context
6. Auto-detect language from source
7. Multi-document support
8. Web API for external integrations

---

## 📞 Support

### Getting Help

1. Check `docs/BUTTONS_GUIDE.md` for button usage
2. Review `docs/CONTEXT.md` for architecture
3. Check `CHANGELOG.md` for recent changes
4. Run test scripts to verify setup

### Common Issues

**Q: Google Translate says "API not found"**
- A: Enable Cloud Translation API in Google Cloud Console, wait 5-10 min

**Q: Buttons don't appear in table**
- A: Clear browser cache, refresh page (Ctrl+F5 in Chrome)

**Q: Translations not saving**
- A: Check database is writable, check target field has text

**Q: QA shows error instead of results**
- A: Check OpenAI credits, ensure model is `gpt-5.5`

---

## 📈 Version History

- **v5.5-update** (2026-05-24) — Confirm & Clear buttons, fixes
- **v5.5** (2026-05-22) — Initial Streamlit version with hybrid pipeline
- **v0.2** (2026-05-22) — Glossary extraction
- **v0.1** (2026-05-22) — PDF download + TM extraction

---

**Status**: ✅ Production Ready  
**Last Updated**: 2026-05-24  
**Maintained By**: Claude Code Team
