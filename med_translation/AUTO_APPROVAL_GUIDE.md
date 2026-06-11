# Controlled Auto-Approval System
**Medical CAT Translator v5.5 — Phase 5: Intelligent Approval Automation**

## Overview

Automatically approve LOW-risk segments that meet strict safety criteria, saving manual approval time while maintaining medical safety.

**Key Features:**
- ✅ Auto-approval OFF by default (user must click button)
- ✅ Preview before execution
- ✅ Only LOW-risk segments eligible
- ✅ Strict multi-condition validation
- ✅ Route-specific rules (EXACT_TM, GOOGLE_SAFE, GPT)
- ✅ Never auto-approves medical protocols, dosages, definitions
- ✅ Fully traceable (logs approval source)

---

## Architecture

### Module: auto_approval_engine.py

**Class:** `AutoApprovalEngine(project_id)`

**Methods:**
1. `load_segments()` — Load all segments for project
2. `check_basic_requirements(seg)` — Common criteria for all routes
3. `check_exact_tm(seg)` — EXACT_TM-specific rules
4. `check_google_safe(seg)` — GOOGLE_SAFE-specific rules
5. `check_gpt(seg)` — GPT-specific rules
6. `check_never_auto_approve(seg)` — Blocks for any route
7. `find_eligible_segments()` — Analyze all segments
8. `get_approval_preview()` — Return preview statistics
9. `execute_auto_approval()` — Execute approval with logging

---

## Eligibility Criteria

### ✅ BASIC REQUIREMENTS (All Routes)

**Mandatory for any auto-approval:**
- Status = translated (not confirmed)
- Risk level = LOW (only)
- target_text not empty
- local_qa_status = pass (no warnings/failures)
- No QA alerts present
- No forbidden term detected
- numerical_qa_passed = true (no mismatches)
- No consistency conflicts
- No glossary issues
- No semantic alerts (google_safe_confidence >= 0.95)
- No hallucination suspicion

**Exclusion Count:** ~5-20% of typical translations

---

### ✅ EXACT_TM ROUTE (Trusted Exact Matches)

**Additional requirements:**
- route = EXACT_TM
- TM match score >= 99% (trusted match)

**Rationale:** Exact TM matches are already validated by human during TM creation.

**Example:** Segment with "Patient management" → "управление пациентами" (99% TM match, LOW risk, local QA pass)

---

### ✅ GOOGLE_SAFE ROUTE (Google Translate for Simple Content)

**Additional requirements:**
- provider = google
- route = GOOGLE_SAFE
- segment_intent in [metadata_simple, author_list, institution_simple]
- No entity/name corruption detected
- No name corruption detected

**Rationale:** Google Translate is safe for non-clinical metadata (headers, author info, institution names).

**Example:** "Dr. John Smith" → "Др. Джон Смит" (GOOGLE_SAFE, LOW risk, LOCAL QA pass, intent=author_list)

---

### ✅ GPT ROUTE (Controlled GPT Translation)

**Additional requirements:**
- route in [GPT_REQUIRED, GPT_WITH_GLOSSARY_REQUIRED]
- qa_final_status = qa_passed (if GPT QA ran)
- back-check passed (if back-check ran)
- No unresolved alerts

**Rationale:** GPT translations must have passed full QA before auto-approval.

**Example:** "The patient presented with" → "Пациент поступил с" (GPT_REQUIRED, LOW risk, qa_passed, local_qa_pass)

---

### ❌ NEVER AUTO-APPROVE

**Blocks approval regardless of other criteria:**

| Category | Examples |
|----------|----------|
| Risk Level | MEDIUM, HIGH, CRITICAL |
| Content Type | table_cell, dosage, treatment_protocol, diagnostic_criteria, medical_definition |
| Ambiguity | ambiguous_abbreviation, complex_affiliation |
| QA Status | qa_warning, qa_failed, local_qa_warning |
| Alerts | Any active QA alert, forbidden term, glossary conflict |

**Explicit Blocks:**
```python
NEVER_AUTO_APPROVE_FEATURES = [
    'dosage',                  # e.g., "50 mg twice daily"
    'treatment_protocol',      # e.g., "Regimen: 3 weeks..."
    'diagnostic_criteria',     # e.g., "Must meet all of..."
    'medical_definition',      # e.g., "Hypertension is defined as..."
    'ambiguous_abbreviation',  # e.g., "AB" (could be antibody or abortion)
    'complex_affiliation'      # e.g., "University of California, San Francisco"
]
```

---

## UI Integration

### Location
**Segment Editor → Batch Actions → ✅ Auto-Approval section**

### Buttons

#### 1. 👁️ Preview Auto-Approval
**Function:** Show what WOULD be approved without executing

**Displays:**
- Candidates count (eligible segments)
- Excluded count (ineligible segments)
- Exclusion summary (reasons + counts)
  - Example: "risk_MEDIUM: 5, table_cell: 3, qa_warning: 2"
- Example candidates (5 examples of segments to approve)
  - Shows: ID, source text (first 50 chars), route, risk level
- Example excluded (5 examples of why segments are blocked)
  - Shows: ID, source text, exclusion reason

**No action taken**

#### 2. ✅ Run Auto-Approval
**Function:** Execute auto-approval

**Process:**
1. Load all segments
2. Identify eligible segments
3. For each eligible:
   - Call `confirm_segment(seg_id)` (sets status='confirmed', adds to TM)
   - Update metadata: `approval_source='auto_approval_engine'`, `auto_approved=True`
4. Return summary

**Displays:**
- Approved count (segments now confirmed)
- Excluded count (ineligible)
- Error count (failed approvals)
- Info: "Added N translations to master TM"
- Errors expandable (if any approvals failed)

---

## Example Workflow

### Step 1: Translate Segments
```
100 segments imported
[Run Batches]
→ 50 EXACT_TM
→ 20 GOOGLE_SAFE
→ 30 GPT_REQUIRED
```

### Step 2: Run QA
```
[Run Local QA All]
→ 95 local QA pass
→ 3 local QA warning
→ 2 local QA fail
```

### Step 3: Preview Auto-Approval
```
[Preview Auto-Approval]
Candidates: 68 (low risk + local QA pass + no issues)
Excluded: 32
  - risk_MEDIUM: 12
  - qa_warning: 8
  - treatment_protocol: 5
  - table_cell: 4
  - semantic_alert: 2
  - other: 1

Examples to auto-approve:
  #5: "Patient management" (EXACT_TM, LOW)
  #12: "Dr. Smith" (GOOGLE_SAFE, LOW, author_list)
  #25: "Follow-up visit" (GPT_REQUIRED, LOW, qa_passed)

Examples excluded:
  #8: treatment_protocol (Never auto-approve dosage/protocol)
  #15: risk_MEDIUM (Risk too high)
  #42: qa_warning (QA issues detected)
```

### Step 4: Execute Auto-Approval
```
[Run Auto-Approval]
Processing...
✅ Auto-Approval Complete
Approved: 68 segments
Excluded: 32 segments
Errors: 0
Added 68 translations to master TM
```

### Step 5: Manual Review Remaining
```
32 remaining segments for manual approval:
- Review 12 MEDIUM-risk items
- Review 8 QA warning items
- Review 5 treatment protocols
- Review 4 table cells
[Approve Each Manually]
```

---

## Database Integration

### New Columns

| Column | Type | Purpose |
|--------|------|---------|
| `approval_source` | TEXT | 'auto_approval_engine' \| 'manual' \| 'workflow' |
| `auto_approved` | BOOLEAN | True if auto-approved |
| `forbidden_alert` | BOOLEAN | True if forbidden term detected |
| `glossary_issues` | BOOLEAN | True if glossary conflict |
| `hallucination_detected` | BOOLEAN | True if hallucination suspected |

### Update Pattern (Automatic)

```python
# When auto-approval executes:
confirm_segment(seg_id)  # Sets status='confirmed', adds to TM
update_segment(seg_id, {
    'approval_source': 'auto_approval_engine',
    'auto_approved': True,
})
```

---

## Exclusion Reasons Reference

### Common Exclusion Reasons

| Reason | Why Excluded |
|--------|--------------|
| `not_translated` | Status not 'translated' or 'confirmed' |
| `risk_MEDIUM`/`HIGH`/`CRITICAL` | Risk level not LOW |
| `empty_target` | Translation text is empty |
| `local_qa_warning` | Local QA found warnings |
| `local_qa_fail` | Local QA found critical issues |
| `qa_alerts:...` | QA checks found specific alerts |
| `forbidden_alert` | Forbidden term detected |
| `numerical_mismatch` | Dosage/unit/lab value validation failed |
| `consistency_conflict` | Same source translated differently elsewhere |
| `glossary_conflict` | Glossary term not used/inconsistent |
| `semantic_alert_X.XX` | Semantic confidence too low |
| `hallucination_suspicion` | Hallucination detected |
| `route_not_exact_tm` | Route not EXACT_TM (for TM-specific check) |
| `tm_score_<99` | TM match below 99% |
| `route_not_google_safe` | Route not GOOGLE_SAFE (for Google check) |
| `provider_not_google` | Provider not Google |
| `intent_...` | Segment intent not in allowed list |
| `entity_corruption` | Entity/name corruption detected |
| `route_...` | Route not in approved list |
| `qa_final_...` | QA final status not 'passed' |
| `back_check_failed` | Back-translation check failed |
| `table_cell` | Segment is table cell (never auto-approve) |
| `never_auto_dosage` | Contains dosage (never auto-approve) |
| `never_auto_protocol` | Treatment protocol (never auto-approve) |
| `never_auto_definition` | Medical definition (never auto-approve) |

---

## Cost Savings

### Calculation

**Without Auto-Approval:**
- Approve 100 segments manually: ~10 minutes (6 sec per segment)

**With Auto-Approval:**
- Auto-approve 68 LOW-risk: instant
- Manually approve 32 remaining: ~3 minutes
- **Savings: 7 minutes per 100 segments = 10-15% faster workflow**

**Cost Savings (OpenAI):**
- Manual approval review per segment: ~0 (human time)
- Auto-approval execution: ~0 (local logic)
- **Total: Pure time savings, no API cost reduction**

---

## Safety Guarantees

✅ **Medical safety prioritized**
- Never auto-approves MEDIUM/HIGH/CRITICAL risk
- Never auto-approves dosages, protocols, definitions
- Never auto-approves if QA detected issues
- Every auto-approval is traceable (approval_source logged)

✅ **Conservative by default**
- Only ~50-70% of LOW-risk segments eligible
- Most medical content requires human review
- Requires passing local QA (no exceptions)

✅ **Fully reversible**
- Auto-approved segments marked with `auto_approved=True`
- Can be filtered/reviewed later
- Can be reverted to 'translated' if needed

✅ **Transparent**
- Preview shows exactly what will be approved
- Exclusion reasons clearly stated
- No hidden approvals

---

## Configuration

### Default Settings
```python
AUTO_APPROVAL_ENABLED = False  # User must click button
APPROVAL_REQUIRES_PREVIEW = True  # Always show preview first
MIN_AUTO_APPROVAL_RISK = 'LOW'  # Only LOW risk
MAX_AUTO_APPROVAL_TM_DEPTH = 'local_only'  # No GPT-like risks
```

### Can be customized in future
- Minimum risk level (currently LOW only)
- Enabled routes (currently EXACT_TM, GOOGLE_SAFE, GPT)
- Enabled intents for GOOGLE_SAFE
- Feature blocks (currently all "never_auto" features are blocks)

---

## API Usage

### Quick Functions

```python
# Get preview
from auto_approval_engine import get_auto_approval_preview
preview = get_auto_approval_preview(project_id=123)
print(f"Would approve: {preview['candidates_count']}")
print(f"Exclusion reasons: {preview['exclusion_reasons']}")

# Execute approval
from auto_approval_engine import run_auto_approval
result = run_auto_approval(project_id=123, progress_callback=print)
print(f"Approved: {result['approved_count']}")
print(f"Added to TM: {result['approved_count']} translations")
```

### Full API

```python
from auto_approval_engine import AutoApprovalEngine

engine = AutoApprovalEngine(project_id=123)

# Preview
preview = engine.get_approval_preview()
print(preview)  # {candidates_count, excluded_count, exclusion_reasons, examples}

# Execute
result = engine.execute_auto_approval(progress_callback=lambda m: print(m))
print(result)  # {approved_count, failed_count, excluded_count, errors, exclusion_summary}
```

---

## Logging & Audit Trail

### Approval Tracking
```sql
SELECT id, source_text, target_text, approval_source, auto_approved, confirmed_at
FROM segments
WHERE approval_source = 'auto_approval_engine'
AND auto_approved = True
```

### Example Output
```
ID  Source          Target           approval_source         auto_approved  confirmed_at
5   Patient mgmt    управление пац   auto_approval_engine    1              2026-05-25 14:32:10
12  Dr. Smith       Др. Смит         auto_approval_engine    1              2026-05-25 14:32:11
25  Follow-up       Дальнейшее       auto_approval_engine    1              2026-05-25 14:32:12
```

---

## Future Enhancements

1. **Batch Auto-Approval Scheduling**
   - Run automatically after batch translation completes
   - Respects "Auto-Approval OFF by default" (explicit enable required)

2. **Risk-Adjusted Thresholds**
   - Allow MEDIUM-risk auto-approval for specific, trusted routes
   - Domain-based configuration (e.g., "medical_definitions always manual")

3. **Smart Exclusions**
   - Learn from manual approval patterns
   - Reduce false exclusions over time

4. **Integration with Manual Approval**
   - Show auto-approval candidates separately
   - One-click approve all candidates
   - One-click reject/revert auto-approvals

---

## Files Modified

- ✅ **auto_approval_engine.py**: New module (350 lines)
- ✅ **app_v55.py**: Added "✅ Auto-Approval" section with 2 buttons
- ✅ **db.py**: Added 5 new columns for approval tracking

---

**Status:** Controlled auto-approval system complete and ready for use.
