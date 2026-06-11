# BACKLOG - Medical CAT Translator v5.5

Prioritized feature requests, improvements, and bug fixes for future releases.

---

## Current Status: v5.5.0 (Production)

**Last Updated:** 2026-06-11  
**Total Items:** 25  
**Priority Distribution:** 🔴 5 Critical | 🟠 8 High | 🟡 10 Medium | 🟢 2 Low

---

## 🔴 CRITICAL (v5.6.0 - Q3 2026)

### 1. Design System Implementation
**Status:** 🚀 Ready  
**Effort:** 40 hours  
**Blocker:** No  

- [ ] Claude Design creates Figma mockups (all 9 tabs)
- [ ] Light theme implementation
- [ ] Dark theme implementation
- [ ] Component library (buttons, inputs, cards, etc.)
- [ ] CSS/Tailwind configuration
- [ ] Responsive mobile layouts
- [ ] Accessibility audit (WCAG AAA)

**Notes:** Design brief fully prepared in `DESIGN_BRIEF_FOR_CLAUDE_DESIGN.md`

---

### 2. Multi-User Authentication System
**Status:** ⏳ Planned  
**Effort:** 30 hours  

- [ ] User registration/login with email
- [ ] User roles (admin, translator, reviewer)
- [ ] Permission system (read, write, approve)
- [ ] Session management
- [ ] Password reset flow
- [ ] 2FA support (optional)
- [ ] User profile management

---

### 3. Database Migration: SQLite → PostgreSQL
**Status:** ⏳ Planned  
**Effort:** 25 hours  

- [ ] PostgreSQL schema design
- [ ] Migration script
- [ ] Connection pooling
- [ ] Backup procedures
- [ ] Performance testing
- [ ] Rollback plan

**Rationale:** Support 10,000+ segments without performance degradation

---

### 4. Re-enable Optimized Glossary Matching
**Status:** ⏳ Planned  
**Effort:** 8 hours  

- [ ] Implement sampling strategy (top 500 segments)
- [ ] Cache results in memory
- [ ] Optimize for large projects
- [ ] Performance testing
- [ ] Update preflight_analyzer.py

**Current State:** Disabled at line 131 (returns empty dict)  
**Target Performance:** <10 seconds for 2828 segments

---

### 5. Enhanced Risk Scoring with ML
**Status:** 📋 Research  
**Effort:** 40 hours  

- [ ] Collect training data from QA results
- [ ] Train risk prediction model
- [ ] Integrate into preflight analysis
- [ ] Validation and testing
- [ ] Performance benchmarks

**Current State:** Simplified to MEDIUM default (line 136)  
**Target:** Dynamic scoring based on segment complexity

---

## 🟠 HIGH (v5.7.0 - Q3 2026)

### 6. Advanced Analytics Dashboard
**Status:** 📋 Design  
**Effort:** 35 hours  

- [ ] User activity heatmap
- [ ] Translation velocity trends
- [ ] Quality metrics over time
- [ ] Cost analysis by segment/user
- [ ] Comparative analysis (prev. projects)
- [ ] Export reports (PDF, Excel)

---

### 7. Semantic Scoring Upgrade
**Status:** ⏳ Planned  
**Effort:** 20 hours  

- [ ] `semantic_scoring.py` - 6 independent scorers
- [ ] Integrate with routing logic
- [ ] Update safety_policy.py
- [ ] Google Translate safety confidence ≥ 0.98
- [ ] Testing and validation

---

### 8. Distributed Batch Processing
**Status:** 📋 Research  
**Effort:** 25 hours  

- [ ] Celery task queue integration
- [ ] Redis for caching
- [ ] Parallel segment processing
- [ ] Job monitoring dashboard
- [ ] Retry logic for failures

---

### 9. API Integration Layer
**Status:** ⏳ Planned  
**Effort:** 30 hours  

- [ ] REST API (FastAPI)
- [ ] Authentication endpoints
- [ ] Project CRUD operations
- [ ] Translation endpoints
- [ ] QA endpoints
- [ ] Export endpoints
- [ ] OpenAPI documentation

---

### 10. Advanced Glossary Features
**Status:** 📋 Design  
**Effort:** 15 hours  

- [ ] Glossary versioning
- [ ] Import from external sources
- [ ] Glossary categories/tags
- [ ] Term frequency analysis
- [ ] Suggestion system for new terms
- [ ] Glossary comparison between projects

---

### 11. Collaborative Review System
**Status:** 📋 Design  
**Effort:** 20 hours  

- [ ] Real-time comments (WebSocket)
- [ ] Mention notifications (@user)
- [ ] Comment threads
- [ ] Resolved/unresolved status
- [ ] Comment history/audit log

---

### 12. Translation Suggestions Engine
**Status:** 📋 Research  
**Effort:** 25 hours  

- [ ] Context-aware suggestions
- [ ] Similar segment lookup
- [ ] Previous translation suggestions
- [ ] Confidence scoring
- [ ] User training feedback

---

### 13. Automated QA Rule Engine
**Status:** ⏳ Planned  
**Effort:** 15 hours  

- [ ] Custom rule definition
- [ ] Rule templates
- [ ] Severity levels per rule
- [ ] Bulk rule application
- [ ] Rule versioning

---

## 🟡 MEDIUM (v5.8.0 - Q4 2026)

### 14. Project Templates
**Status:** 📋 Design  

- [ ] Medical report template
- [ ] Clinical trial template
- [ ] Pharmaceutical documentation template
- [ ] Custom template builder

---

### 15. Batch Operations Enhancement
**Status:** ⏳ Planned  

- [ ] Batch segment editing
- [ ] Bulk tagging
- [ ] Bulk status updates
- [ ] Undo/redo for batch operations

---

### 16. Email Notifications
**Status:** ⏳ Planned  

- [ ] Project completion notification
- [ ] QA issues alert
- [ ] Translator mention notification
- [ ] Daily summary digest

---

### 17. Audit Logging
**Status:** ⏳ Planned  

- [ ] User action logging
- [ ] Change history per segment
- [ ] Compliance reporting
- [ ] Access logs

---

### 18. Performance Monitoring
**Status:** ⏳ Planned  

- [ ] Request latency tracking
- [ ] Database query profiling
- [ ] Error rate monitoring
- [ ] Alert system for anomalies

---

### 19. Advanced Filtering
**Status:** ⏳ Planned  

- [ ] Filter by risk level + TM score
- [ ] Complex boolean filters
- [ ] Saved filter profiles
- [ ] Filter templates

---

### 20. Mobile App (React Native)
**Status:** 📋 Research  
**Effort:** 100+ hours  

- [ ] iOS version
- [ ] Android version
- [ ] Offline support
- [ ] Sync when online

---

### 21. Browser Extension
**Status:** 📋 Research  
**Effort:** 40 hours  

- [ ] Quick translate popup
- [ ] Glossary lookup in browser
- [ ] One-click submission to projects

---

### 22. Voice-to-Text Input
**Status:** 📋 Research  

- [ ] Speech recognition API integration
- [ ] Transcription accuracy improvement
- [ ] Multiple language support
- [ ] Pronunciation guide

---

### 23. CAT Engine Improvement
**Status:** ⏳ Planned  

- [ ] Leverage all TM matches (not just 100%)
- [ ] Fuzzy match weighting
- [ ] Context-aware fuzzy matching

---

### 24. Terminology Extraction
**Status:** ⏳ Planned  

- [ ] Auto-extract medical terms from source
- [ ] Term frequency analysis
- [ ] Suggest glossary additions
- [ ] Auto-glossary generation

---

### 25. Version Control for Translations
**Status:** 📋 Research  

- [ ] Branch-based translation workflow
- [ ] Merge strategies
- [ ] Conflict resolution
- [ ] Translation comparison

---

## 🟢 LOW (Future Releases)

### Future Ideas (Backlog)
- [ ] Plugin system for custom processors
- [ ] Integration with other CAT tools (SDL, Smartcat, etc.)
- [ ] Blockchain for translation verification
- [ ] AI-powered terminology suggestion
- [ ] Predictive typing for translators
- [ ] Gesture-based shortcuts (mobile)

---

## Completed Features (v5.5.0) ✅

- ✅ Password protection
- ✅ Design brief (700+ lines)
- ✅ Streamlit Cloud deployment
- ✅ GitHub repository setup
- ✅ Preflight analysis
- ✅ Zero-token optimization
- ✅ Batch translation (Google & GPT)
- ✅ QA orchestration (6-stage)
- ✅ Auto-approval engine
- ✅ Review queue system
- ✅ Segment editor
- ✅ Glossary management
- ✅ TM integration
- ✅ DOCX import/export
- ✅ Statistics dashboard

---

## Priority Matrix

```
          HIGH EFFORT         LOW EFFORT
HIGH ───────────────────────────────
      5. ML Risk            4. Glossary
         Scoring            Optimization
      
      6. Analytics          14. Templates
      7. Semantic           15. Batch Ops
         Scoring            19. Filtering
      
      8. Distributed        16. Email
         Processing         Notifications
LOW  ───────────────────────────────
```

---

## Release Planning

### v5.6.0 (Q3 2026 - Target: 2026-07-15)
1. Design System Implementation (40h)
2. Multi-User Authentication (30h)
3. DB Migration: SQLite→PostgreSQL (25h)
4. Glossary Optimization (8h)
5. Testing & QA (20h)

**Estimated:** 123 hours (~3 weeks)

### v5.7.0 (Q3 2026 - Target: 2026-08-15)
1. Analytics Dashboard (35h)
2. Semantic Scoring (20h)
3. Distributed Processing (25h)
4. Advanced Glossary (15h)
5. Testing & QA (15h)

**Estimated:** 110 hours (~3 weeks)

### v6.0.0 (Q4 2026+)
Major features: API, Mobile App, Advanced features

---

## Notes

- All estimates are rough and subject to change
- Priorities can shift based on user feedback
- Community contributions welcome
- Performance targets (preflight <120s) must be maintained
- WCAG AAA accessibility required for all new features

---

**Last Updated:** 2026-06-11  
**Next Review:** 2026-06-25  
**Owner:** Development Team
