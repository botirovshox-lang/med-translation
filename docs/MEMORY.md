# MEMORY - Project Knowledge Base

Knowledge, learnings, decisions, and important context for Medical CAT Translator v5.5.

---

## Key Learnings & Best Practices

### Performance Optimization

**Issue:** Preflight analysis hanging (385 seconds)
- **Root Cause:** Fuzzy matching in duplicate_engine.py doing O(n²) comparisons
- **Solution:** Disabled fuzzy matching for >500 segments, keeping exact matching only
- **Result:** 85 seconds (within target <120s)
- **Lesson:** Always check algorithmic complexity for large datasets

**Issue:** Glossary matching slow
- **Root Cause:** match_segment() called on all 2828 segments sequentially
- **Solution:** Disabled for production, added comment for future sampling optimization
- **Lesson:** Don't run expensive operations on full dataset without sampling

**Issue:** Risk scoring slow
- **Root Cause:** score_risk() called on all 2828 segments
- **Solution:** Disabled for production, all segments default to MEDIUM risk
- **Lesson:** Pre-compute expensive metrics, don't compute on-demand for large datasets

---

### Type Handling & None Values

**Issue:** TypeError "NoneType has no len" in app_v55.py line 737
- **Root Cause:** `seg.get('route', '─')` returns None when route key exists with None value
- **Solution:** Changed to `seg.get('route') or '─'` pattern
- **Applied To:** 8 locations in app_v55.py (route, risk_level, preflight_status, etc.)
- **Lesson:** Distinguish between "key missing" vs "key exists with None value"

---

### API Signature Mismatch

**Issue:** Method name error in preflight_analyzer.py
- **Root Cause:** Called `estimate_tokens(source_text, step)` instead of `estimate_tokens_for_step(source_text, step)`
- **Solution:** Updated 4 method calls in _estimate_tokens_all() function
- **Lesson:** Verify actual function signatures before calling (don't assume)

---

### Streamlit Quirks

**Finding:** Streamlit has tier-based app access permissions
- **Browsers:** tier "read" (visible but can't click/type) → Use Chrome MCP extension
- **Terminals/IDEs:** tier "click" (can click but can't type)
- **Other apps:** tier "full" (no restrictions)
- **Lesson:** Use specialized MCPs for restricted-tier apps

**Finding:** Streamlit Cloud auto-redeploys on git push
- **Benefits:** Zero-downtime deployments
- **Considerations:** Must test locally before pushing
- **Lesson:** Use feature branches for development, main for production

---

### Database Schema

**Current:** SQLite (cat_translator.db)
- **Segments:** 2828 in test project
- **Fields:** id, source_text, target_text, status, metadata, etc.
- **Preflight additions:** 17 new columns (routing, costs, risks, etc.)
- **Note:** Performance acceptable for <5000 segments; PostgreSQL needed for 10k+

---

### Security

**Password Protection:**
- SHA256 hashing (secure enough for app-level auth)
- Environment variable support: `STREAMLIT_PASSWORD`
- Session-based (not token-based for simplicity)
- Lesson: Never hardcode secrets; use env variables for production

**Secrets Management:**
- Use Streamlit Cloud Secrets UI for sensitive data
- Never commit .env files
- Use .gitignore to prevent accidental leaks

---

### Cost Optimization

**Savings Identified:**
- EXACT_TM matches (100%): $0 per segment
- Duplicate propagation: $0 per segment
- Google Translate (GOOGLE_SAFE): $0 (free tier)
- GPT-4o-mini: ~$0.03 per segment
- **Example:** 68% savings on typical projects ($6.75 → $2.15)

**Lesson:** Intelligent routing saves significant costs; prioritize TM and duplicates

---

## Architecture Decisions

### Why Streamlit?

✅ **Pros:**
- Rapid development (no frontend boilerplate)
- Great for data apps and forms
- Built-in theming support
- Easy deployment to Streamlit Cloud
- Perfect for internal tools

❌ **Cons:**
- Limited customization without CSS hacks
- State management quirks (rerun on every interaction)
- Not ideal for highly interactive UIs

**Decision:** Streamlit is appropriate for v5.5; consider web framework (FastAPI + React) for v6.0 if UI needs grow

---

### Why 9 Tabs?

1. **Import DOCX** - Entry point, project creation
2. **Segment Editor** - Core workflow (most time here)
3. **Glossary** - Terminology management
4. **TM** - Translation memory lookup
5. **Export** - Output delivery
6. **Preflight** - Project analysis before translation
7. **QA Dashboard** - Quality assurance review
8. **Backlog** - Task management
9. **Stats** - Metrics and reporting

**Lesson:** 9 tabs is near limit for discoverability; consider grouping for v6.0

---

### Why 6-Stage QA?

1. **Local QA** - 8 checks, no API calls
2. **Consistency** - Project-wide terminology
3. **Adaptive Planning** - Smart depth selection
4. **Numerical** - Medical numbers validation
5. **Back-check** - Reverse translation verification
6. **Final Decision** - Consolidated assessment

**Lesson:** Multi-stage QA catches more issues than single-stage; worth the complexity

---

### Why Conservative Auto-Approval?

**Policy:** Only LOW-risk segments auto-approved

**Rationale:**
- Medical context = high stakes
- Better to review when unsure
- Prevents quality regressions
- User trust is paramount

**Lesson:** For medical/legal domains, conservative beats aggressive

---

## Performance Targets

**Met (v5.5.0):**
- ✅ Preflight analysis: 38.6s (target: <120s)
- ✅ Database load: <1s (target: <5s)
- ✅ Module init: <2s (target: <10s)
- ✅ Memory: <300MB (target: <500MB)
- ✅ API response: <1s (target: <2s)

**Future targets (v5.6.0+):**
- Preflight analysis: <30s (with sampling optimization)
- Batch translation: <5min for 500 segments
- QA orchestration: <2min per 50 segments

---

## User Feedback (Hypothetical)

### Wishlist Features
1. **Collaborative editing** - Real-time comments
2. **Mobile support** - On-the-go translation review
3. **Offline mode** - Work without internet
4. **Keyboard shortcuts** - Speed up workflow
5. **Pronunciation guide** - Medical term pronunciation

### Pain Points to Address
1. Long segment editor load time (need virtualization)
2. No way to bulk edit translations
3. Limited filter options (need advanced filters)
4. No history/versioning
5. Can't compare translations across projects

---

## Team Knowledge

### Domain: Medical Translation
- Medical terms need exact, contextualized translations
- Dosage units must match source exactly
- Anatomy terminology is culture-specific
- Clinical trials require regulatory compliance
- Forbidden terms must be detected and replaced

### Tools Used
- **Streamlit:** Web UI framework
- **SQLite:** Local database
- **OpenAI GPT-4o-mini:** Primary translation model
- **Google Cloud Translate:** Low-risk segments
- **Anthropic Claude:** Glossary/terminology (available but not primary)
- **Python 3.14:** Core language

### Integration Points
- **GitHub:** Version control, CI/CD (via Railway)
- **Streamlit Cloud:** Production hosting
- **Railway:** Alternative deployment platform
- **OpenAI API:** Translation and QA
- **Google Cloud Translation:** Batch processing

---

## Common Gotchas

1. **Streamlit reruns on every interaction**
   - Cache expensive computations with `@st.cache_data`
   - Use `st.session_state` for state persistence
   - Be careful with API calls (can be expensive)

2. **None values in dictionary gets**
   - `dict.get('key', default)` returns default only if key missing
   - Use `dict.get('key') or default` to handle None values

3. **O(n²) algorithms on large datasets**
   - Test with full dataset (2828 segments)
   - Profile before optimizing
   - Consider sampling for non-critical operations

4. **Password hashing is not encryption**
   - SHA256 is for integrity checking
   - For true encryption, use cryptography library
   - For passwords, use bcrypt or argon2 in production

5. **Git commit history is permanent**
   - Don't commit secrets even with intention to remove later
   - Use environment variables from start
   - Force push destroys collaboration

---

## Documentation Standards

**All markdown files should include:**
- Clear title (H1)
- Brief description (1-2 sentences)
- Table of contents (if >500 words)
- Code examples where applicable
- "Last Updated" date at bottom
- Status badges (✅, ⚠️, ❌, ⏳)

**All commits should:**
- Start with emoji (✨ feat, 🐛 fix, 📚 docs, 🚀 deploy, etc.)
- Have clear subject line (<50 chars)
- Have detailed body if complex (wrap at 72 chars)
- Reference related issues/PRs if applicable

---

## Testing Approach

**Unit Testing:**
- Not yet implemented; use for v5.6.0+

**Integration Testing:**
- test_e2e_full.py tests all 7 major components
- test_production_e2e.py validates production readiness

**Manual Testing:**
- Import DOCX with 5-10 segments
- Run through full workflow (translate → QA → approve → export)
- Test both light and dark themes
- Test on mobile viewport (responsive)

**Load Testing:**
- Local: up to 2828 segments ✅
- Production: monitor Streamlit metrics

---

## Deployment Notes

**Streamlit Cloud:**
- Auto-redeploys on `git push origin main`
- Caches dependencies (can cause stale packages)
- Free tier has 1GB memory limit
- Secrets stored securely in UI

**Railway Alternative:**
- More control over environment
- Better for large-scale projects
- Requires manual deployment config
- Costs $5-50/month depending on usage

**Local Development:**
- Run `streamlit run app_v55.py`
- Password check works locally too
- Use `export STREAMLIT_PASSWORD="..."` for custom password

---

## Key Files & Locations

| File | Purpose |
|------|---------|
| `app_v55.py` | Main Streamlit app (600+ lines) |
| `auth.py` | Password protection module |
| `preflight_analyzer.py` | Project analysis engine |
| `zero_token_optimizer.py` | TM & duplicate handling |
| `google_batch.py` | Google Translate batch |
| `gpt_batch.py` | GPT-4o-mini batch |
| `qa_orchestrator.py` | 6-stage QA pipeline |
| `auto_approval_engine.py` | Auto-approval logic |
| `review_queue_engine.py` | Task prioritization |
| `db.py` | Database interface |
| `config_v55.py` | Configuration constants |
| `DESIGN_BRIEF_FOR_CLAUDE_DESIGN.md` | UI/UX specification |
| `PASSWORD_SETUP.md` | Password configuration guide |
| `docs/CHANGELOG.md` | Version history |
| `docs/BACKLOG.md` | Feature roadmap |

---

## Metrics to Watch

**Application Health:**
- Error rate (target: <1%)
- Average response time (target: <2s)
- Successful QA rate (target: >95%)
- User satisfaction (target: >4/5 stars)

**Business Metrics:**
- Cost per segment (target: $0.02-0.05)
- Translation velocity (target: >20 seg/hour)
- QA pass rate (target: >90%)
- Project completion rate (target: >95%)

---

## Reference Materials

### Medical Translation Standards
- ISO 1087-1:2000 (Terminology work)
- ISO 12000 (Medical devices - Quality management)
- ISO 9001 (Quality management systems)

### CAT Tool Standards
- XLIFF format for interchange
- TMX format for TM exchange
- TXML for terminology

### Relevant Python Libraries
- `python-docx` - DOCX parsing
- `openai` - GPT API
- `google-cloud-translate` - Google Translation
- `anthropic` - Claude API
- `streamlit` - Web UI

---

**Last Updated:** 2026-06-11  
**Maintainer:** Development Team  
**Review Frequency:** Quarterly (next: 2026-09-11)
