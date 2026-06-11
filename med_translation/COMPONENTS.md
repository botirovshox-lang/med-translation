# Medical CAT Translator v5.5 - Components Reference

## Table of Contents

1. [Zero-Token Optimizer](#zero-token-optimizer)
2. [Google Batch Translator](#google-batch-translator)
3. [GPT Batch Translator](#gpt-batch-translator)
4. [QA Orchestrator](#qa-orchestrator)
5. [Auto-Approval Engine](#auto-approval-engine)
6. [Review Queue Engine](#review-queue-engine)

---

## Zero-Token Optimizer

**File:** `zero_token_optimizer.py`

**Purpose:** Optimize translation costs by reusing exact TM matches and propagating duplicate translations.

### When to Use
- Before running any batch translation
- To identify segments that don't need API calls
- To find duplicate groups for cost savings

### Key Concepts
- **EXACT_TM:** 100% TM matches, no translation needed ($0 cost)
- **DUPLICATE_REPRESENTATIVE:** First segment in duplicate group (translate once)
- **DUPLICATE_PROPAGATION:** Copy translation from representative ($0 cost)

### Methods

#### `prefill_exact_tm(segments)`
Fill target_text from 100% TM matches.

**Input:** List of segment dicts  
**Output:** Count of prefilled segments

**Example:**
```python
from zero_token_optimizer import prefill_exact_tm
count = prefill_exact_tm(segments)
print(f"Prefilled {count} exact TM matches")
```

#### `prepare_representatives(segments)`
Mark representatives for each duplicate group.

**Input:** List of segment dicts  
**Output:** Count of duplicate groups identified

**Example:**
```python
from zero_token_optimizer import prepare_representatives
count = prepare_representatives(segments)
print(f"Found {count} duplicate groups")
```

#### `propagate_duplicates(segments)`
Copy translations from representatives to duplicates.

**Input:** List of segment dicts  
**Output:** Count of propagated segments

**Example:**
```python
from zero_token_optimizer import propagate_duplicates
count = propagate_duplicates(segments)
print(f"Propagated {count} translations")
```

### Database Fields Updated
- `status` → 'tm_prefilled' (for EXACT_TM)
- `provider` → 'TM'
- `target_text` → filled from TM
- `estimated_total_usd` → 0.0

---

## Google Batch Translator

**File:** `google_batch.py`

**Purpose:** Translate GOOGLE_SAFE segments using Google Translate (free tier).

### When to Use
- For low-risk, non-medical metadata segments
- When cost savings are critical
- For simple content: author lists, institution names, simple headers

### Safety Constraints
- Only processes segments with route='GOOGLE_SAFE'
- Only processes segments with google_safe_confidence >= 0.98
- Requires local_qa_status='pass' before sending to Google
- Validates output with local QA after translation

### Methods

#### `get_preview(segments)`
Show what WOULD be translated without executing.

**Input:** List of segment dicts  
**Output:** Dict with candidates count, cost estimate, examples

**Example:**
```python
from google_batch import GoogleBatchTranslator
translator = GoogleBatchTranslator(1)
preview = translator.get_preview(segments)
print(f"Would translate {preview['eligible_count']} segments")
print(f"Estimated cost: ${preview['estimated_cost_usd']:.2f}")
```

#### `translate_batch(segments, batch_size=50)`
Execute Google Translate on eligible segments.

**Input:** List of segment dicts, batch size (default 50)  
**Output:** Dict with translated_count, cost_usd, errors

**Example:**
```python
result = translator.translate_batch(segments, batch_size=50)
print(f"Translated {result['translated_count']} segments")
print(f"Cost: ${result['cost_usd']:.2f}")
```

### Database Fields Updated
- `status` → 'google_draft' (initial) or 'google_needs_review' (if QA warning)
- `target_text` → Google translation
- `provider` → 'google'
- `local_qa_status` → 'pass' or 'warning'

---

## GPT Batch Translator

**File:** `gpt_batch.py`

**Purpose:** Translate GPT_REQUIRED and GPT_WITH_GLOSSARY_REQUIRED segments using OpenAI GPT.

### When to Use
- For segments requiring advanced translation
- For medical or complex content
- When full glossary context needed

### Optimization Features
- Minimal glossary injection (only matched approved terms, max 5)
- Minimal TM context (top 1-3 matches, 80%+ only)
- Groups segments by characteristics (route, risk, block_type, length)
- Estimates tokens before translation

### Methods

#### `get_minimal_glossary(source_text)`
Get only matched glossary terms (not all terms).

**Input:** Source text  
**Output:** Dict with matched terms

#### `get_minimal_tm(source_text)`
Get only top TM matches (1-3, 80%+ only).

**Input:** Source text  
**Output:** List of TM matches

#### `get_preview(segments)`
Preview translation batch without executing.

**Input:** List of segment dicts  
**Output:** Dict with eligible_count, estimated_tokens, estimated_cost_usd

**Example:**
```python
from gpt_batch import GPTBatchTranslator
translator = GPTBatchTranslator(1)
preview = translator.get_preview(segments)
print(f"Would translate {preview['eligible_count']} segments")
print(f"Estimated tokens: {preview['estimated_tokens']}")
print(f"Estimated cost: ${preview['estimated_cost_usd']:.2f}")
```

#### `translate_batch(segments, model='gpt-4o', batch_size=20)`
Execute GPT translation on eligible segments.

**Input:** Segment dicts, model name, batch size  
**Output:** Dict with translated_count, total_tokens, total_cost_usd

**Example:**
```python
result = translator.translate_batch(segments, model='gpt-4o', batch_size=20)
print(f"Translated {result['translated_count']} segments")
print(f"Tokens used: {result['total_tokens']}")
print(f"Cost: ${result['total_cost_usd']:.2f}")
```

### Database Fields Updated
- `status` → 'translated'
- `target_text` → GPT translation
- `provider` → 'openai'
- `estimated_total_tokens` → filled

---

## QA Orchestrator

**File:** `qa_orchestrator.py`

**Purpose:** Execute 6-stage QA pipeline: local → consistency → adaptive planning → numerical → back-check → final decision.

### 6 Stages

**Stage 1: Local QA All**
- 8 local validation checks (no API)
- Sets `local_qa_status` = 'pass' | 'warning' | 'fail'

**Stage 2: Consistency QA**
- Project-wide consistency checks
- Detects same source translated differently
- Sets `consistency_alerts` JSON

**Stage 3: Adaptive QA Plan**
- Determines optimal QA depth per segment
- Based on route, risk, provider
- Sets `qa_depth_scheduled` (local_only → critical_full_review)

**Stage 4: Numerical QA**
- Medical numerical validation
- Checks dosages, units, ranges
- Sets `numerical_qa_passed` and `numerical_qa_issues`

**Stage 5: Back-Check Scheduling**
- Determines which segments need back-translation
- Sets `back_check_needed` flag

**Stage 6: Final QA Decision**
- Combines all checks
- Sets final `qa_final_status` = 'qa_passed' | 'qa_warning' | 'qa_failed'
- Sets `qa_depth_used` (actual depth used)

### Methods

#### `orchestrate_full_qa(segments, progress_callback=None)`
Execute all 6 stages.

**Input:** List of segment dicts, optional progress function  
**Output:** Dict with stage results and summary

**Example:**
```python
from qa_orchestrator import QAOrchestrator
orchestrator = QAOrchestrator(1)

def progress(msg):
    print(f"[QA] {msg}")

result = orchestrator.orchestrate_full_qa(segments, progress_callback=progress)
print(f"Stage 1 passed: {result['stage_1_passed']} segments")
print(f"Stage 6 final: {result['stage_6_results']}")
```

### Database Fields Updated
- `local_qa_status` → 'pass' | 'warning' | 'fail'
- `consistency_alerts` → JSON
- `numerical_qa_passed` → True | False
- `numerical_qa_issues` → JSON
- `qa_depth_scheduled` → 'local_only', 'local_plus_light_gpt', etc
- `qa_depth_used` → actual depth used
- `qa_final_status` → 'qa_passed' | 'qa_warning' | 'qa_failed'

---

## Auto-Approval Engine

**File:** `auto_approval_engine.py`

**Purpose:** Automatically approve LOW-risk segments meeting strict safety criteria.

### Safety Constraints
- ❌ Never approves MEDIUM/HIGH/CRITICAL risk
- ❌ Never approves if local_qa_status != 'pass'
- ❌ Never approves dosages, protocols, definitions
- ❌ Never approves if forbidden terms present
- ✅ Only approves LOW-risk segments
- ✅ Only approves if no QA alerts
- ✅ Only approves if no consistency conflicts

### Eligible Routes
- **EXACT_TM:** TM match >= 99%
- **GOOGLE_SAFE:** No entity corruption, no complex affiliation
- **GPT:** If qa_final_status='qa_passed' and back-check passed

### Methods

#### `get_approval_preview(segments)`
Show what WOULD be approved without executing.

**Input:** List of segment dicts  
**Output:** Dict with candidates_count, excluded_count, exclusion_reasons, examples

**Example:**
```python
from auto_approval_engine import AutoApprovalEngine
engine = AutoApprovalEngine(1)
preview = engine.get_approval_preview(segments)
print(f"Would approve: {preview['candidates_count']}")
print(f"Exclusion breakdown: {preview['exclusion_reasons']}")
```

#### `execute_auto_approval(segments, progress_callback=None)`
Execute auto-approval on eligible segments.

**Input:** List of segment dicts, optional progress function  
**Output:** Dict with approved_count, failed_count, excluded_count

**Example:**
```python
result = engine.execute_auto_approval(segments)
print(f"Approved: {result['approved_count']} segments")
print(f"Excluded: {result['excluded_count']} segments")
```

### Database Fields Updated
- `status` → 'confirmed'
- `approval_source` → 'auto_approval_engine'
- `auto_approved` → True
- Segment added to master TM

---

## Review Queue Engine

**File:** `review_queue_engine.py`

**Purpose:** Identify and prioritize problematic segments requiring manual review.

### Problematic Segment Types
- QA failures (qa_warning, qa_failed)
- Consistency conflicts
- Glossary conflicts
- Forbidden terms detected
- Numerical mismatches
- Semantic alerts
- Back-check failures

### Prioritization
```
Priority = Risk Level Base + Alert Type Boost

Risk Level Base:
  CRITICAL: 100
  HIGH: 80
  MEDIUM: 50
  LOW: 20

Alert Type Boost:
  forbidden_detected: +95
  numeric_mismatch: +90
  semantic_drift: +85
  glossary_conflict: +70
  consistency_conflict: +65
  qa_warning/qa_failed: +60
```

### Methods

#### `get_review_queue(filters=None)`
Get prioritized queue with optional filters.

**Filters (all optional):**
- `route`: EXACT_TM, GOOGLE_SAFE, GPT_REQUIRED, etc
- `risk`: LOW, MEDIUM, HIGH, CRITICAL
- `provider`: tm, google, openai
- `alert_type`: qa_warning, consistency_conflict, forbidden_detected, etc

**Output:** List of segments sorted by priority (highest first)

**Example:**
```python
from review_queue_engine import ReviewQueueEngine
engine = ReviewQueueEngine(1)

# Get all high-risk problematic segments
filters = {'risk': 'HIGH', 'provider': 'openai'}
queue = engine.get_review_queue(filters=filters)

for seg in queue[:5]:
    print(f"ID {seg['id']}: priority={seg['priority']}, alert={seg['top_alert']}")
```

#### `get_segment_details(segment_id)`
Get full review information for a segment.

**Output:** Dict with all QA/alert data plus suggested action

**Example:**
```python
details = engine.get_segment_details(42)
print(f"Route: {details['route']}")
print(f"Risk: {details['risk_level']}")
print(f"Suggested Action: {details['suggested_action']}")
```

#### `get_statistics()`
Get queue statistics.

**Output:** Dict with breakdown by risk, alert type, status

**Example:**
```python
stats = engine.get_statistics()
print(f"Total in queue: {stats['total_in_queue']}")
print(f"By risk: {stats['by_risk']}")
print(f"By alert type: {stats['by_alert_type']}")
```

### Review Queue Actions (in UI)

**💾 Save Edit:** Update target_text, status='translated'  
**🔍 Local QA:** Run local QA on edited text  
**✅ Confirm:** Approve and add to TM, status='confirmed'  
**❌ Reject:** Clear translation for re-translation, status='needs_review'  
**👤 Expert Review:** Mark for human expert, status='human_review_required'

---

## Summary Table

| Component | Purpose | Cost | Speed | Risk |
|-----------|---------|------|-------|------|
| Zero-Token | Exact TM + duplicates | $0 | <10s | ⬜ None |
| Google Batch | Simple content via Google | $0.02/100 | <5m | 🟡 Low (non-medical) |
| GPT Batch | Complex content via GPT | $1-5/100 | 30-60m | 🟡 Medium (monitored) |
| QA Orchestrator | 6-stage QA validation | $0 | 5-10m/100 | ⬜ None (validation) |
| Auto-Approval | LOW-risk auto-confirm | $0 | <1s | ⬜ None (conservative) |
| Review Queue | Problematic segment triage | $0 | Realtime | ⬜ None (UI only) |

---

**Last Updated:** 2026-06-11  
**Status:** Production Ready ✅
