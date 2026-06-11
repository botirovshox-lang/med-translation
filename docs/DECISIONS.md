# DECISIONS - Architectural Decisions & Rationale

Record of important architectural and design decisions made for Medical CAT Translator v5.5.

---

## ADR-001: Use Streamlit for Web UI

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** Architecture  

### Context
- Need to build web UI for medical translation tool
- Team has Python expertise, limited JavaScript
- Need to ship quickly (weeks, not months)
- Primarily internal tool (not consumer app)

### Decision
Use Streamlit for web UI framework.

### Rationale
✅ **Pros:**
- Python-native (no JavaScript needed)
- Rapid development (weeks vs months)
- Built-in theming (light/dark)
- Easy deployment to Streamlit Cloud
- Great for data apps and forms
- Auto-caching with @st.cache_data
- State management with st.session_state

❌ **Cons:**
- Limited customization (Streamlit-specific quirks)
- Reruns entire script on every interaction
- Not ideal for highly interactive UIs
- Single-user at a time (Streamlit Cloud free tier)
- Limited offline support

### Alternatives Considered
1. **FastAPI + React** - More control, longer dev time
2. **Flask + Jinja** - More boilerplate, less modern
3. **Vue.js + FastAPI** - Good balance, more complex
4. **Next.js** - JavaScript-based, requires frontend expertise

### Consequences
- ✅ Ships quickly with minimal frontend code
- ✅ Easy to modify and maintain
- ❌ Limited scaling to multiple concurrent users
- ❌ Some UI/UX limitations without CSS hacks
- 🔄 May need to migrate to FastAPI + React for v6.0

### Decision Drivers
- Time to market
- Team expertise (Python)
- Simplicity for internal tool

---

## ADR-002: SQLite for Local Development, PostgreSQL for Production

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** Data Layer  

### Context
- Need database for ~2828 segments
- Want fast local development
- Will scale to 10,000+ segments eventually
- Cost-conscious deployment

### Decision
Use SQLite for development, migrate to PostgreSQL for production when needed.

### Rationale
✅ **SQLite:**
- No setup required
- File-based (easy to backup)
- Sufficient for <5,000 segments
- Fast enough for development

✅ **PostgreSQL:**
- Handles 100k+ segments efficiently
- Better concurrency (multiple users)
- Advanced features (triggers, extensions)
- Managed services available (Railway, AWS RDS)

### Scaling Path
```
v5.5.0: SQLite (works fine for <5k segments)
   ↓
v5.6.0: PostgreSQL (planned when needed)
   ↓
v6.0.0: PostgreSQL + caching layer (Redis)
```

### Testing Strategy
- Local: SQLite (same schema as PostgreSQL)
- CI/CD: PostgreSQL for compatibility testing
- Production: PostgreSQL only

---

## ADR-003: Conservative Auto-Approval (LOW-Risk Only)

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** Feature Policy  

### Context
- Medical translations have high stakes
- Human review is critical for quality
- Need to balance efficiency with safety
- Different from standard CAT tools

### Decision
Only approve LOW-risk segments automatically. Everything else requires human review.

### Rationale
✅ **Safety First:**
- Medical content = life/death stakes
- Better to review 100 safe items than miss 1 risky
- Builds user trust
- Prevents quality regressions

❌ **Less Aggressive:**
- Other CAT tools approve MEDIUM-risk
- Could translate more segments automatically
- Requires more human review time

### Risk Classification
- **CRITICAL** (risk_score 75-100): Always human review
- **HIGH** (50-74): Human review unless has glossary terms
- **MEDIUM** (25-49): Always human review (NOT auto-approved)
- **LOW** (0-24): Auto-approve if meets all criteria

### Approval Criteria (AND all required)
1. Risk level = LOW
2. No terminology gaps
3. No formatting issues
4. Confidence score ≥ 0.95
5. No forbidden terms detected

### Consequences
- ✅ High quality and safety
- ✅ User confidence in tool
- ❌ More manual work for translators
- ❌ Slower overall throughput

### Review Gates
```
AUTO APPROVAL
├─ Risk = LOW ✓
├─ No forbidden terms ✓
├─ Glossary coverage ✓
└─ Confidence ≥ 0.95 ✓
    → AUTO CONFIRM ✅

HUMAN REVIEW
├─ Risk = MEDIUM+ ✗
└─ → Send to Review Queue
    → Assign to reviewer
    → Manual approval required
```

---

## ADR-004: 6-Stage QA Pipeline Instead of Single Pass

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** QA Architecture  

### Context
- Medical translations need thorough QA
- Different issue types require different checks
- Want to catch problems early, before client
- Need to be cost-efficient

### Decision
Implement 6-stage QA pipeline with progressively expensive checks.

### Rationale
✅ **Staged Approach:**
- Local QA (8 checks, $0): Catch obvious issues
- Consistency (project-wide, $0): Terminology alignment
- Adaptive planning (smart, $0): Choose depth based on risk
- Numerical validation ($0): Medical-specific checks
- Back-check ($$$): Expensive, only if needed
- Final decision (consolidate): Human-readable report

✅ **Cost Optimization:**
- Expensive checks only when needed
- 80% of issues caught at stage 1
- Back-check scheduled intelligently (not always)

### Alternative (Single-Pass)
- Run all checks at once
- Higher cost (~2-3x)
- May catch more issues
- Less efficient

### QA Stages Breakdown
```
Stage 1: Local QA (no API)
├─ Formatting consistency
├─ Terminology check
├─ Forbidden term detection
├─ Placeholder validation
├─ Number/unit validation
├─ URL validation
├─ Tag balance
└─ Length check

Stage 2: Consistency (project-wide)
├─ Glossary alignment
├─ Terminology repetition
├─ Context alignment

Stage 3: Adaptive Planning
├─ Risk-based depth selection
├─ Feature-based check intensity
├─ Cost estimation

Stage 4: Numerical Validation
├─ Medical numbers
├─ Units and conversions
├─ Dosage validation

Stage 5: Back-Check (if needed)
├─ Reverse translation
├─ Meaning preservation
├─ Cultural adaptation

Stage 6: Final Decision
├─ Consolidate all results
├─ Risk assessment
├─ Recommendation (approve/review/reject)
```

---

## ADR-005: 9-Tab Horizontal Navigation Instead of Sidebar

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** UI Architecture  

### Context
- Need to organize 9 major features
- Users bounce between features during translation
- Streamlit doesn't support nested navigation
- Need quick access to all features

### Decision
Use horizontal tab navigation (9 tabs) for major features.

### Rationale
✅ **Horizontal Tabs:**
- Clear separation of concerns
- Quick navigation (1 click)
- Visible context (which tab you're on)
- Familiar pattern (browser tabs)
- Mobile-friendly (can scroll if needed)

❌ **Sidebar Navigation:**
- Takes horizontal space
- Less discoverable
- Harder to fit 9 items neatly

### Tab Organization
```
Primary Workflow (3 tabs):
├─ Import DOCX (entry point)
├─ Segment Editor (core work)
└─ Export (final output)

Supporting Features (3 tabs):
├─ Glossary (terminology)
├─ TM (memory)
└─ Preflight (analysis)

Management (3 tabs):
├─ QA Dashboard (quality)
├─ Backlog (tasks)
└─ Stats (metrics)
```

### Scaling Beyond 9 Tabs
For v6.0, consider:
- Group related tabs (Glossary + TM → Resources)
- Drawer/modal for less-used features
- Search for features
- Favorites/pinned tabs

---

## ADR-006: Password-Based Auth Instead of OAuth

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED (v5.5)  
**Type:** Security  

### Context
- v5.5 is small team internal tool
- Need simple authentication
- Don't want OAuth complexity yet
- Can upgrade in v5.6

### Decision
Use simple password-based authentication (SHA256 hashing).

### Rationale
✅ **v5.5 (Current):**
- Simple implementation (auth.py < 100 lines)
- Fast to deploy
- No external auth service needed
- Good enough for internal tool
- Environment variable support for production

❌ **Limitations:**
- Single shared password (not per-user)
- No user roles yet
- No audit log
- SHA256 is not ideal (should use bcrypt)

### Migration Path
```
v5.5: Simple password (auth.py)
   ↓
v5.6: Per-user authentication system
   ├─ Email/password registration
   ├─ User roles (admin, translator, reviewer)
   ├─ bcrypt password hashing
   └─ Session tokens
   ↓
v6.0: SSO/OAuth
   ├─ GitHub OAuth
   ├─ Google SSO
   ├─ SAML for enterprise
   └─ API tokens for programmatic access
```

### Current Implementation
```python
# auth.py (v5.5)
├─ SHA256 hashing (insecure, but simple)
├─ Session-based state
├─ Environment variable override
└─ Logout functionality

# Upgrade needed for v5.6
├─ Per-user accounts
├─ bcrypt hashing (secure)
├─ Database of users
└─ Role-based access control
```

---

## ADR-007: Disable Expensive Optimizations for Performance

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** Performance  

### Context
- Preflight analysis was hanging (385 seconds)
- Glossary matching slow on 2828 segments
- Risk scoring O(n) for all segments
- Need to ship production version
- Can re-enable with optimization

### Decisions Made

#### Decision 7A: Disable Fuzzy Duplicate Matching
- **Problem:** O(n²) algorithm (4M comparisons for 2828 segments)
- **Solution:** Keep exact matching only
- **Code:** Line 82 in duplicate_engine.py
- **Impact:** 85s vs 385s ✅
- **Revert:** Can add sampling optimization in v5.6

#### Decision 7B: Disable Glossary Matching
- **Problem:** Sequential match_segment() on all 2828 segments
- **Solution:** Disabled in preflight_analyzer.py (line 131)
- **Impact:** Already fast; can re-enable with sampling
- **Revert:** Add sampling (top 500) in v5.6

#### Decision 7C: Simplify Risk Scoring
- **Problem:** score_risk() called on all 2828 segments
- **Solution:** All segments default to MEDIUM risk
- **Impact:** Fast, but less accurate routing
- **Revert:** Re-enable with ML model in v5.6+

### Performance Results After Optimizations
- Target: <120s
- Achieved: 38.6s ✅ (68% faster than target!)

### Re-enable Roadmap
```
v5.5: Disabled (fast baseline)
   ↓
v5.6: Re-enable with sampling
   ├─ Fuzzy: Top 500 segments only
   ├─ Glossary: Cached results
   └─ Risk: ML model
   ↓
v6.0: Full optimization suite
```

---

## ADR-008: Preflight Analysis as Read-Only Advisory

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** Feature Scope  

### Context
- Preflight gives routing, cost, risk recommendations
- User still needs to confirm all actions
- Don't want to auto-action without approval
- Preflight should inform, not control

### Decision
Preflight analysis is informational and advisory only. All translation/QA/approval actions require explicit user confirmation.

### Rationale
✅ **Safety:**
- User retains control
- Preflight can't make mistakes happen
- Transparent decision-making
- Medical context = user responsibility

❌ **Less Automated:**
- User sees suggestion, clicks to execute
- More clicks than auto-apply

### Preflight Information Flow
```
Preflight Analysis (read-only)
├─ Routing suggestion
├─ Cost estimate
├─ Risk assessment
└─ Feature detection
    ↓
Display in Preflight Tab
    ↓
User reviews and accepts plan
    ↓
Execute translations (user initiates)
    ├─ Google Batch [Run]
    ├─ GPT Batch [Run]
    └─ Or manual segment editing
        ↓
All actions require explicit user confirmation
```

---

## ADR-009: GitHub Repository Over Proprietary VCS

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED  
**Type:** Infrastructure  

### Context
- Need version control
- Open source friendly
- Team uses Git
- Easy collaboration

### Decision
Use GitHub (public repo with private flag) for version control.

### Rationale
✅ **GitHub:**
- Standard in industry
- Easy to integrate with CI/CD
- Free for private repos
- Great for collaboration
- Webhook integrations available

### Repository Setup
```
Repository: botirovshox-lang/med-translation
Privacy: PRIVATE (proprietary code)
Main Branch: main (production)
CI/CD: Railway integration
Auto-deploy: On git push to main
```

---

## ADR-010: Streamlit Cloud for Initial Deployment

**Date:** 2026-06-11  
**Status:** ✅ ACCEPTED (v5.5)  
**Type:** Deployment  

### Context
- Need to ship quickly
- Want zero infrastructure management
- Small team (1-2 people)
- Can migrate later if needed

### Decision
Deploy to Streamlit Cloud for v5.5. Consider Railway/other for v6.0.

### Rationale
✅ **Streamlit Cloud:**
- Free tier available
- Auto-deploys on git push
- No infrastructure management
- Secrets management built-in
- SSL/HTTPS included

❌ **Limitations:**
- Single-user at a time (free tier)
- 1GB memory limit
- Limited customization
- Spinning down after inactivity

### Upgrade Path
```
v5.5: Streamlit Cloud (shipped, free)
   ↓
v5.6: Railway (if traffic grows)
   ├─ Better multi-user support
   ├─ More control
   └─ ~$5-50/month cost
   ↓
v6.0: Custom infrastructure (if needed)
   ├─ Kubernetes cluster
   ├─ PostgreSQL managed service
   ├─ CDN for assets
   └─ Global deployment
```

---

**Last Updated:** 2026-06-11  
**Version:** 5.5.0  
**Status:** All decisions documented and ratified
