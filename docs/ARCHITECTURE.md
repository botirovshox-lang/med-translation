# ARCHITECTURE - Medical CAT Translator v5.5

System architecture, design patterns, and component interactions.

---

## Overview

```
┌────────────────────────────────────────────────────────────────┐
│                     User Interface (Streamlit)                  │
│                                                                  │
│  [Auth] → [Import] [Editor] [Glossary] [TM] [Export] ...       │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                    Application Layer (Python)                   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Workflow Orchestration                                  │   │
│  │ ├─ app_v55.py (main UI logic)                          │   │
│  │ ├─ daily_run.py (batch orchestration)                  │   │
│  │ └─ pipeline.py (translate → QA → approve)              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Analysis & Optimization                                 │   │
│  │ ├─ preflight_analyzer.py (routing, costs, risks)       │   │
│  │ ├─ duplicate_engine.py (detect & group duplicates)     │   │
│  │ ├─ zero_token_optimizer.py (TM + duplicate optim.)     │   │
│  │ ├─ cost_estimator.py (token & USD estimation)          │   │
│  │ ├─ risk_engine.py (risk scoring)                       │   │
│  │ └─ safety_policy.py (routing rules)                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Translation & QA Engines                                │   │
│  │ ├─ google_batch.py (Google Cloud Translation)           │   │
│  │ ├─ gpt_batch.py (OpenAI GPT-4o-mini)                    │   │
│  │ ├─ qa_orchestrator.py (6-stage QA pipeline)             │   │
│  │ │  ├─ Local QA (consistency_engine, forbidden_checker)  │   │
│  │ │  ├─ Consistency checks                                │   │
│  │ │  ├─ Adaptive QA planning                              │   │
│  │ │  ├─ Numerical validation                              │   │
│  │ │  ├─ Back-check scheduling                             │   │
│  │ │  └─ Final decision                                    │   │
│  │ ├─ auto_approval_engine.py (LOW-risk auto-confirm)      │   │
│  │ └─ review_queue_engine.py (prioritize human review)     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Data & Integration                                      │   │
│  │ ├─ db.py (SQLite interface)                             │   │
│  │ ├─ tm.py (Translation Memory)                           │   │
│  │ ├─ terminology_engine.py (Glossary matching)            │   │
│  │ ├─ docx_cat.py (DOCX import/export)                     │   │
│  │ ├─ google_translate.py (Google API wrapper)             │   │
│  │ ├─ auth.py (password protection)                        │   │
│  │ └─ config_v55.py (constants & configuration)            │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                      Data Layer (SQLite)                        │
│                                                                  │
│  Database Tables:                                               │
│  ├─ projects (id, title, source_lang, target_lang, ...)       │
│  ├─ segments (id, project_id, source_text, target_text, ...)  │
│  │  └─ Preflight fields: route, risk_level, cost, etc.        │
│  ├─ glossary (id, source, target, category, ...)              │
│  ├─ tm (id, source, target, metadata, ...)                    │
│  └─ user_roles (id, name, role, pbx_ext, ...)                 │
│                                                                  │
│  File Storage:                                                  │
│  └─ /data/ directory for DOCX uploads & exports                │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                     External APIs                               │
│                                                                  │
│  ├─ OpenAI API (GPT-4o-mini for translation & QA)              │
│  ├─ Google Cloud Translation API (low-risk segments)            │
│  ├─ Anthropic API (glossary, available but not primary)        │
│  └─ Streamlit Cloud (hosting & deployment)                     │
└────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Authentication Layer (`auth.py`)

**Purpose:** Protect app access with password-based authentication

**Key Functions:**
- `check_password()` - Show login form, return auth status
- `get_password_hash(password)` - Generate SHA256 hash
- `show_logout_button()` - Render logout in sidebar
- `logout()` - Clear session and redirect to login

**Security:**
- SHA256 hashing (not encryption)
- Session-based (not token-based)
- Environment variable support for production passwords

---

### 2. Preflight Analysis (`preflight_analyzer.py`)

**Purpose:** Analyze projects before translation to identify routing, costs, and risks

**Key Classes:**
- `PreflightAnalyzer` - Main orchestrator
- `AnalysisResult` - Container for analysis output

**Key Methods:**
- `analyze_all()` - Run complete analysis on all segments
- Returns: Routing decisions, cost estimates, risk assessments

**Performance:**
- Target: <120 seconds for 2828 segments
- Actual: 38.6 seconds ✅

**Inputs:** Segments from database  
**Outputs:** Routing metadata, cost estimates, risk levels

---

### 3. Zero-Token Optimizer (`zero_token_optimizer.py`)

**Purpose:** Maximize cost savings by identifying segments that need no API calls

**Zero-Cost Routes:**
- EXACT_TM: 100% translation memory matches ($0)
- DUPLICATE_PROPAGATION: Copy from existing translation ($0)

**Methods:**
- `optimize_project()` - Apply TM matches and duplicate propagation
- `detect_duplicates()` - Find similar segments
- `match_exact_tm()` - Find 100% TM matches

**Savings Impact:**
- Example: $6.75 → $2.15 per 100 segments (68% savings)

---

### 4. Translation Engines

#### Google Batch Translator (`google_batch.py`)
- **Use Case:** Low-risk, simple segments
- **Cost:** Free tier (up to 500k chars/month)
- **Quality:** Good for straightforward text
- **Route:** GOOGLE_SAFE segments

#### GPT Batch Translator (`gpt_batch.py`)
- **Use Case:** Complex medical content
- **Cost:** ~$0.03/segment (gpt-4o-mini)
- **Quality:** Excellent for medical terminology
- **Route:** GPT_REQUIRED, GPT_WITH_GLOSSARY_REQUIRED

---

### 5. QA Orchestrator (`qa_orchestrator.py`)

**Purpose:** Multi-stage quality assurance pipeline

**6-Stage Pipeline:**
1. **Local QA** - 8 checks (no API)
   - Formatting consistency
   - Terminology validation
   - Forbidden term detection
   - etc.

2. **Consistency Checks** - Project-wide terminology
3. **Adaptive QA Planning** - Smart depth selection based on risk
4. **Numerical Validation** - Medical numbers and units
5. **Back-Check Scheduling** - Reverse translation verification
6. **Final QA Decision** - Consolidated assessment

**Key Methods:**
- `run_qa_orchestration()` - Execute full pipeline
- Returns: QA results, recommendations, failure reasons

---

### 6. Auto-Approval Engine (`auto_approval_engine.py`)

**Purpose:** Conservative automatic approval of low-risk segments

**Policy:** Only LOW-risk segments are auto-approved

**Validation:**
- Risk level = LOW
- No terminology gaps
- No formatting issues
- Confidence score ≥ 0.95

**Safety First:** Better to review when unsure

---

### 7. Review Queue Engine (`review_queue_engine.py`)

**Purpose:** Intelligent prioritization of segments needing human review

**Prioritization Factors (Highest to Lowest):**
1. CRITICAL risk level
2. Numerical issues
3. Semantic complexity
4. Glossary gaps
5. Consistency warnings

**Features:**
- In-place editing
- Batch operations
- Status tracking
- Comment history

---

### 8. Database Layer (`db.py`)

**Purpose:** Abstract database operations

**Key Tables:**
```
projects:
  └─ id, title, source_lang, target_lang, created, status

segments:
  └─ id, project_id, source_text, target_text, status
     word_count, char_count, language_pair
     + 17 preflight fields (route, risk, cost, etc.)

glossary:
  └─ id, project_id, source, target, category, frequency

tm:
  └─ id, source, target, language_pair, created, frequency

user_roles:
  └─ id, name, role, pbx_ext, tg_chat_id, active
```

**Key Functions:**
- CRUD operations for all tables
- Batch operations for performance
- Preflight data persistence

---

## Data Flow Diagrams

### Import → Translate → QA → Approve

```
User Uploads DOCX
         ↓
Import via docx_cat.py
         ↓
Split into Segments (create in DB)
         ↓
Preflight Analysis (compute metadata)
         ↓
Display in Segment Editor
         ↓
User selects translation method:
  ├─ Manual edit
  ├─ Google Batch (low-risk)
  └─ GPT Batch (complex)
         ↓
Update segment with translation
         ↓
Run QA Orchestrator (6 stages)
         ↓
QA Results:
  ├─ PASS → Show for approval
  └─ FAIL → Show issues in Review Queue
         ↓
User approves (Confirm button)
         ↓
Add to Translation Memory
         ↓
Mark as Confirmed in DB
         ↓
Export to DOCX (download)
```

### Preflight Analysis Flow

```
Segments from DB
         ↓
Duplicate Detection (exact + fuzzy)
         ↓
TM Matching (100% matches)
         ↓
Glossary Coverage (terminology check)
         ↓
Risk Scoring (ADHD, medical complexity)
         ↓
Routing Decision (which API/path)
         ↓
Cost Estimation (tokens × rate)
         ↓
Store Metadata in DB
         ↓
Display in Preflight Tab
         ↓
Recommendations for user
```

---

## Design Patterns

### 1. Orchestrator Pattern
- `PreflightAnalyzer`, `QAOrchestrator`, `daily_run.py`
- Coordinate multiple subsystems
- Central point for business logic
- Easy to test and modify

### 2. Strategy Pattern
- `GoogleBatchTranslator`, `GPTBatchTranslator`
- Different translation strategies
- Same interface (get_preview, translate_batch)
- User selects strategy based on segment type

### 3. Factory Pattern
- Routing logic selects appropriate handler
- GOOGLE_SAFE → Google API
- GPT_REQUIRED → OpenAI API
- HUMAN_REVIEW_REQUIRED → Manual

### 4. Repository Pattern
- `db.py` abstracts database
- Easy to switch backends (SQLite → PostgreSQL)
- Testable without real DB

### 5. Event-Based Processing
- Streamlit reruns on user interaction
- Event → Update DB → Rerun UI
- Stateless UI (all state in DB or session)

---

## Scalability Considerations

### Current Limits (v5.5.0)
- **Segments:** <5,000 (SQLite)
- **Glossary:** <10,000 terms
- **Concurrent Users:** 1 (Streamlit limitation)
- **File Size:** <100MB DOCX

### Scaling for v5.6.0+

#### Horizontal Scaling
- FastAPI instead of Streamlit (for APIs)
- Multiple Streamlit instances behind load balancer
- Session state in Redis
- Database: PostgreSQL + read replicas

#### Database Optimization
- Indexing on frequently filtered columns
- Partition large tables by project_id
- Archive old projects to cold storage

#### Batch Processing
- Celery task queue for large translations
- Redis caching for expensive computations
- Rate limiting on external APIs

---

## Deployment Architecture

### Local Development
```
Developer Machine
    ↓
Streamlit dev server (localhost:8501)
    ↓
SQLite database (local file)
    ↓
API keys from .env (NOT version controlled)
```

### Streamlit Cloud (Current)
```
GitHub Repository (main branch)
    ↓
Git push trigger
    ↓
Streamlit Cloud rebuilds & deploys
    ↓
PostgreSQL database (managed by Streamlit)
    ↓
Secrets from Streamlit UI
    ↓
Production URL live
```

### Railway Alternative
```
GitHub Repository
    ↓
Railway detects Dockerfile
    ↓
Builds Docker image
    ↓
Deploys container
    ↓
PostgreSQL database
    ↓
Environment variables from Railway
    ↓
Production URL live
```

---

## API Integration

### OpenAI (GPT-4o-mini)
- **Endpoint:** https://api.openai.com/v1/chat/completions
- **Auth:** Bearer token via OPENAI_API_KEY
- **Rate Limit:** 3,500 req/min (usage tier dependent)
- **Cost:** Input $0.00015/token, Output $0.0006/token
- **Timeout:** 30 seconds recommended

### Google Cloud Translation
- **Endpoint:** translate.googleapis.com
- **Auth:** Service account key
- **Rate Limit:** 500 req/sec
- **Cost:** Free tier (500k chars/month), then $20/1M chars
- **Timeout:** 10 seconds recommended

### Anthropic Claude
- **Endpoint:** https://api.anthropic.com/v1/
- **Auth:** Bearer token via ANTHROPIC_API_KEY
- **Rate Limit:** 50 requests/minute (free tier)
- **Cost:** Input $0.003/1k tokens, Output $0.015/1k tokens
- **Use Case:** Glossary/terminology (not primary in v5.5)

---

## Error Handling

### API Errors
- Timeout (>30s): Retry with exponential backoff
- Rate limit (429): Retry after delay
- Auth error (401): Check API key
- Invalid request (400): Log and skip segment

### Database Errors
- Connection lost: Reconnect automatically
- Constraint violation: Validate before insert
- Concurrency issue: Retry transaction

### User Errors
- Invalid DOCX: Show error message
- Oversized document: Split into multiple imports
- Missing glossary: Warn but allow proceed

---

## Performance Targets

| Operation | Target | Actual | Status |
|-----------|--------|--------|--------|
| Preflight (2828 seg) | <120s | 38.6s | ✅ |
| DB load | <5s | <1s | ✅ |
| Module init | <10s | <2s | ✅ |
| Memory | <500MB | <300MB | ✅ |
| API response | <2s | <1s | ✅ |
| Batch 100 seg (GPT) | <10m | ~8m | ✅ |

---

## Security Architecture

```
User
   ↓
[Password Check] ← auth.py
   ↓ (authenticated)
Session State
   ↓
Database (SQLite/PostgreSQL)
   ↓
[API Keys from Environment]
   ↓
External APIs (OpenAI, Google, Anthropic)
```

**Key Principles:**
- Never hardcode secrets
- Use environment variables
- Hash passwords with salt (future: bcrypt)
- Validate all inputs
- Log security events

---

**Last Updated:** 2026-06-11  
**Version:** 5.5.0  
**Next Review:** When adding major features (v5.6.0+)
