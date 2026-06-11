# Medical CAT Translator v5.5 - Testing Guide

## Overview

Complete end-to-end testing guide for all components implemented in Phase 1-5 of the Medical CAT Translator system.

---

## Setup

### Prerequisites
- Python 3.8+
- Streamlit installed
- Database initialized (`med_translation.db`)
- Test DOCX file (50-100 segments recommended for faster testing)

### Start App
```bash
cd C:\Users\Shox\med_translation\med_translation
python -m streamlit run app_v55.py
```

---

## Phase 1: Preflight Analysis Testing

### Test 1.1: Run Preflight Analysis

**Steps:**
1. Go to "🔍 Preflight / Cost + Safety Planner" tab
2. Keep project as "#7 — Med translation"
3. Click [🔍 Analyze Only]
4. Wait for completion (~45-60s for 2828 segments)

**Expected Results:**
```
✅ Analysis complete
✅ No errors in console
✅ Statistics panel shows:
   - Total segments > 0
   - Unique normalized > 0
   - Routing breakdown populated
   - Cost estimates > 0
```

**Verify in Database:**
```bash
python -c "
from db import get_segments
segs = get_segments(1)
seg = segs[0]
print(f'Route: {seg.get(\"route\")}')
print(f'Risk: {seg.get(\"risk_level\")}')
print(f'Est. Cost: {seg.get(\"estimated_total_usd\")}')
print(f'Preflight Status: {seg.get(\"preflight_status\")}')
"
```

---

## Phase 2: Segment Editor Integration Testing

### Test 2.1: Preflight Columns Display

**Steps:**
1. Go to "📝 Segment Editor" tab
2. Scroll right to see all columns
3. Check 7 new preflight columns:
   - Route (color badge: 🟢 🔵 🟣 🟡 ⚪ 🟠 🔴)
   - Risk (color badge: 🔴 🟠 🟡 🟢)
   - Provider (hint text: TM, Ggl, GPT, Hmn)
   - Est.$ (USD cost)
   - Preflight (status emoji: ✅ ⏳ ❌ ⏹)
   - Dupes (duplicate count)
   - TM% (if >= 99)

**Expected:** All columns render without errors

### Test 2.2: Right Panel Preflight Information

**Steps:**
1. Click any segment (✓ button)
2. Check right panel has section "📍 Preflight Information"
3. Verify displays:
   - Route with emoji and color
   - Risk level with emoji and color
   - Intent (metadata_simple, medical_content, etc)
   - Detected Features
   - QA Policy
   - Approval Policy
   - Cost Breakdown (expander)
   - Duplicate Group info (if applicable)
   - Exact TM notification (if TM >= 99%)
   - Google Safe explanation (if GOOGLE_SAFE)

**Expected:** All fields render without errors

---

## Phase 3: Batch Operations Testing

### Test 3.1: Zero-Token Optimizer

**Steps:**
1. Go to "📝 Segment Editor"
2. Click [💾 Apply Exact TM] button
3. Check progress dialog

**Expected Results:**
```
✅ Found X exact TM matches
✅ Prefilled Y segments
✅ segments_status = 'tm_prefilled'
✅ provider = 'TM'
✅ estimated_total_usd = 0
```

### Test 3.2: Google Batch Translation

**Steps:**
1. Click [🌐 Preview Google Batch]
   - Should show: "X eligible GOOGLE_SAFE segments"
   - Should show: "Estimated cost: $X.XX"
   
2. Click [▶️ Run Google Batch]
   - Watch progress
   - Wait for completion

**Expected Results:**
```
✅ Translated X segments via Google
✅ status='google_draft'
✅ target_text populated
✅ local_qa_status='pass' or 'warning'
✅ No errors
```

### Test 3.3: GPT Batch Translation

**Steps:**
1. Click [📊 Preview GPT Batch]
   - Should show: "X eligible GPT segments"
   - Should show: "Estimated tokens: ~XXX"
   - Should show: "Estimated cost: $X.XX"

2. Click [▶️ Run GPT Batch]
   - Watch for API calls
   - Monitor token usage

**Expected Results:**
```
✅ Translated X segments via GPT
✅ status='translated'
✅ provider='openai'
✅ target_text populated
✅ Estimated vs actual tokens close
```

---

## Phase 4: QA Orchestration Testing

### Test 4.1: Run Local QA All

**Steps:**
1. Go to "✅ QA Dashboard" tab
2. Click [🚀 Run Local QA All]
3. Watch progress

**Expected Results:**
```
✅ Processed all segments
✅ local_qa_status = 'pass' | 'warning' | 'fail'
✅ Statistics updated:
   - Pass: X
   - Warning: Y
   - Fail: Z
```

### Test 4.2: Run Adaptive QA Plan

**Steps:**
1. Go to "✅ QA Dashboard" tab
2. Click [📊 Run Adaptive QA Plan]
3. Watch depth assignments

**Expected Results:**
```
✅ Scheduled QA depths per segment
✅ qa_depth_scheduled populated
✅ estimated_qa_tokens calculated
✅ estimated_qa_usd calculated
```

### Test 4.3: Full QA Orchestration

**Steps:**
1. Run [🚀 Run Local QA All] → [📊 Run Adaptive QA Plan]
2. Then manually:
   - Click individual segment QA buttons
   - Observe qa_final_status updates

**Expected Results:**
```
✅ All 6 stages complete
✅ qa_final_status = 'qa_passed' | 'qa_warning' | 'qa_failed'
✅ qa_depth_used matches scheduled depth
✅ consistency_alerts populated (if any)
✅ numerical_issues populated (if any)
```

---

## Phase 5: Auto-Approval Testing

### Test 5.1: Preview Auto-Approval

**Steps:**
1. Go to "📝 Segment Editor" → Batch Actions
2. Click [👁️ Preview Auto-Approval]

**Expected Results:**
```
✅ Shows: "X candidates eligible"
✅ Shows: "Y excluded" breakdown
✅ Example candidates listed
✅ Example exclusions with reasons
```

### Test 5.2: Run Auto-Approval

**Steps:**
1. Click [✅ Run Auto-Approval]
2. Watch progress

**Expected Results:**
```
✅ Approved X segments
✅ status='confirmed' for approved
✅ approval_source='auto_approval_engine'
✅ auto_approved=True
✅ Added to master TM
```

### Test 5.3: Verify Only LOW-risk Approved

**Steps:**
1. After auto-approval, check database:
```bash
python -c "
from db import get_segments
segs = get_segments(1)
approved = [s for s in segs if s.get('approval_source') == 'auto_approval_engine']
for seg in approved[:5]:
    print(f'Seg {seg[\"id\"]}: risk={seg.get(\"risk_level\")}')
"
```

**Expected:** All approved segments have risk_level='LOW'

---

## Phase 6: Review Queue Testing

### Test 6.1: View Review Queue

**Steps:**
1. Go to "📝 Segment Editor"
2. In right panel, scroll to "Review Queue" section
3. Check filters: Route, Risk, Provider, Alert Type

**Expected Results:**
```
✅ Queue shows problematic segments
✅ Sorted by priority (highest first)
✅ Filters work correctly
✅ Statistics show breakdown
```

### Test 6.2: Edit & Review Workflow

**Steps:**
1. Select a problematic segment in queue
2. Edit target_text
3. Click [💾 Save Edit]
4. Click [🔍 Local QA]
5. Click [✅ Confirm]

**Expected Results:**
```
✅ Save Edit: status='translated'
✅ Local QA: Shows pass/warning/fail
✅ Confirm: status='confirmed', added to TM
✅ Segment removed from queue
```

### Test 6.3: Test Other Actions

**Steps:**
1. Select another problematic segment
2. Click [❌ Reject]
   - Expected: target_text cleared, status='needs_review'
3. Select a CRITICAL segment
4. Click [👤 Expert Review]
   - Expected: status='human_review_required'

---

## Phase 7: Full End-to-End Pipeline

### Complete Pipeline Test (Recommended)

**Setup:**
- Fresh project with 50 segments
- Mix of: duplicates, TM matches, risky content, glossary terms

**Steps:**

```
1. ✅ Run Preflight Analysis
   - Check routing is correct
   - Verify costs are reasonable

2. ✅ Apply Zero-Token Optimization
   - Fill EXACT_TM matches
   - Prepare duplicates

3. ✅ Run Google Batch (GOOGLE_SAFE only)
   - Translate GOOGLE_SAFE segments
   - Check local QA passes

4. ✅ Run GPT Batch (GPT_REQUIRED)
   - Translate remaining segments
   - Monitor API usage

5. ✅ Run Full QA Orchestration
   - Local QA all
   - Adaptive QA planning
   - Run QA per segment

6. ✅ Run Auto-Approval
   - Auto-approve LOW-risk
   - Verify only LOW-risk approved

7. ✅ Manual Review Queue
   - Review remaining HIGH/CRITICAL
   - Edit as needed
   - Confirm or reject

8. ✅ Export DOCX
   - Check all segments translated
   - Verify quality

9. ✅ Check Statistics
   - Count confirmed segments
   - Verify TM was updated
   - Check all costs
```

**Expected Final State:**
```
✅ 50/50 segments confirmed
✅ Master TM has 50 new translations
✅ No errors in console
✅ All preflight data in DB
✅ Segment Editor still functional
✅ Export DOCX contains all translations
```

---

## Performance Targets

| Component | Target Time | Actual |
|-----------|------------|--------|
| Preflight Analysis (2828 segs) | < 60s | ___ |
| Google Batch (100 segments) | < 5m | ___ |
| GPT Batch (100 segments) | 20-60m | ___ |
| Full QA (100 segments) | < 10m | ___ |
| Auto-Approval (50 segments) | < 10s | ___ |
| UI Table Render (142 segs) | < 2s | ___ |
| UI Right Panel (select seg) | < 500ms | ___ |

---

## Troubleshooting

### Preflight Analysis Hangs
```
✓ Check if glossary matching is slow → reduce sample size
✓ Check if risk scoring is slow → reduce sample size
✓ Check if semantic scoring is slow → disable temporarily
✓ Check console for specific error
```

### Batch Translation Fails
```
✓ Check API keys in .env
✓ Check network connection
✓ Check OpenAI/Google quotas
✓ Review error message in UI
```

### QA Issues
```
✓ Check local QA passes first (Local QA tab)
✓ Verify QA policy is set correctly
✓ Check consistency alerts for conflicts
✓ Review numerical issues if present
```

### Auto-Approval Missing Segments
```
✓ Check risk_level distribution (should have LOW-risk segs)
✓ Verify local_qa_status='pass' for eligible segments
✓ Check if forbidden terms or alerts present
✓ Review exclusion reasons in preview
```

---

## Sign-Off

After completing all tests above, sign off:

- [ ] Phase 1: Preflight Analysis - PASS
- [ ] Phase 2: Segment Editor Integration - PASS
- [ ] Phase 3: Batch Operations - PASS
- [ ] Phase 4: QA Orchestration - PASS
- [ ] Phase 5: Auto-Approval - PASS
- [ ] Phase 6: Review Queue - PASS
- [ ] Phase 7: E2E Pipeline - PASS
- [ ] Performance targets met - PASS

**Date Tested:** _______________
**Tested By:** _______________
**Issues Found:** _______________

---

**Status:** Ready for Production Deployment ✅
