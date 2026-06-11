# Intelligent Local Routing Engine — Implementation Summary

**Status:** ✅ COMPLETE & TESTED  
**Date:** 2026-05-25  
**Focus:** Structural classification + semantic signals + positive safety logic (NOT keyword blacklists)

---

## Changed Files

### NEW Files Created
1. **structural_classifier.py** (380 lines)
   - Pattern-based segment intent detection
   - No APIs, pure local heuristics
   - Detects: author lists, affiliations, institutions, titles, tables, metadata

2. **routing_engine.py** (240 lines)
   - Main orchestrator for routing decisions
   - Combines structural classification + semantic scores + risk signals
   - Implements positive safety logic: "How safe is it to NOT use GPT?"
   - Google allowed ONLY if google_safe_confidence >= 0.98

### MODIFIED Files
1. **semantic_scoring.py**
   - Enhanced medicality_score() with Russian morphology families
   - Replaced hardcoded suffixes with broad morphology roots (лог, терап, пат, генез, невро, кардио, etc.)
   - Improved clinical_criticality calculation

2. **preflight_analyzer.py**
   - Added import: `from routing_engine import RoutingEngine`
   - Added `self.routing_engine = RoutingEngine()` in __init__
   - Updated `_route_all_segments()` to use `routing_engine.route()` instead of old safety_policy logic
   - Simplified `_save_all_preflight_metadata()` to extract all data from routing result

3. **app_v55.py** (no changes needed yet)
   - Already displays all preflight columns
   - UI ready for routing_reason display

---

## Core Innovation

### Structural Classification (NOT Keywords)

**Pattern-Based Intent Detection:**
- Author lists: Detect initials + surnames + separators, disqualify if has degrees/titles
- Complex affiliations: Detect person initials + academic degrees + institutions + named-after markers
- Institutions: Detect long formal names + medical specialty keywords
- Tables: Detect numeric density + units (mg, ml, %) + ranges
- Simple metadata: Short text, no complex structure
- Titles/headings: Short length + title keywords

**Russian Academic Markers Detected:**
- Academic degrees: д.м.н., к.м.н., PhD, MD, профессор, доцент, ассистент
- Professional titles: заведующий, научный сотрудник, ведущий научный сотрудник
- Named-after: им., имени, nomidagi, named after
- Medical specialties: фтиз, пульмон, кардиолог, нефрол, etc.

### Semantic Scoring (Russian-Aware)

**6 Independent Scores (0.0-1.0):**

1. **semantic_density_score** — Medical terminology concentration
   - Russian roots: лог, терап, пат, генез, невро, кардио, эндокрин, пневм, фтиз, инфекц, гепат, нефр, уролог, гастро, онко, гинек, педиатр, псих, хирург, фармак, иммун, бактери, вирус, клиник, диагност, симптом, синдром
   - English suffixes: -itis, -osis, -emia, -ectomy, -lysis, etc.
   - Abbreviation patterns

2. **medicality_score** — "How medical is this?"
   - Russian morphology families
   - English medical suffixes
   - Scientific/clinical phrases (диагноз, симптом, синдром, клинический, лечение, терапия)

3. **entity_complexity_score** — Structural complexity
   - Person + title + institution patterns
   - Academic degrees + initials
   - Multiple named-after markers

4. **reversibility_risk_score** — Back-translation safety
   - Numeric density (ranges, percentages)
   - Abbreviations and acronyms
   - Nested structures

5. **clinical_criticality_score** — Medical severity
   - Dosage patterns
   - Lab values, diagnostic criteria
   - Clinical severity, staging

6. **google_safe_confidence** — Composite safety (POSITIVE LOGIC)
   - High score = SAFE for Google
   - >= 0.98 → GOOGLE_SAFE allowed
   - 0.85-0.97 → Route upward (GPT)
   - < 0.85 → Block (requires GPT/human)
   - Default: If uncertain → route away from Google

### Routing Rules (11 Priority Levels)

1. **EXACT_TM** (TM >= 99%)
2. **DUPLICATE_PROPAGATION_PENDING** (copy from representative)
3. **DUPLICATE_REPRESENTATIVE** (translate once)
4. **CRITICAL risk** → HUMAN_REVIEW_REQUIRED
5. **HIGH risk + glossary** → GPT_WITH_GLOSSARY_REQUIRED
6. **HIGH risk - glossary** → HUMAN_REVIEW_REQUIRED
7. **Simple metadata/author_list + google_safe_confidence >= 0.98** → GOOGLE_SAFE
8. **biography_or_affiliation or institution_complex** → GPT_REQUIRED
9. **table_or_numeric with clinical_criticality > 0.5** → HUMAN_REVIEW_REQUIRED
10. **table_or_numeric** → GPT_REQUIRED
11. **Glossary-heavy or medicality > 0.6** → GPT_WITH_GLOSSARY_REQUIRED
12. **Forbidden terms detected** → HUMAN_REVIEW_REQUIRED
13. **google_safe_confidence >= 0.98** → GOOGLE_SAFE
14. **DEFAULT** → GPT_REQUIRED

---

## How to Test

### 1. Unit Test: Structural Classifier

```python
from structural_classifier import classify_segment

# Test 1: Simple metadata
result = classify_segment("Ташкент-2026")
assert result['intent'] == 'metadata_simple'

# Test 2: Simple author list
result = classify_segment("Иванов И.И.; Петров П.П.")
assert result['intent'] == 'author_list'

# Test 3: Complex affiliation
result = classify_segment("Усманов И.Х.– д.м.н., профессор Центра фтизиатрии им. Алимова")
assert result['intent'] == 'biography_or_affiliation'
assert 'academic_degree' in result['detected_patterns']
assert 'named_after' in result['detected_patterns']

# Test 4: Dosage
result = classify_segment("0,5 мг/кг 2 раза в сутки")
assert result['intent'] == 'table_or_numeric'
assert result['detected_patterns']['measurements'] == 1
```

### 2. Unit Test: Routing Engine

```python
from routing_engine import RoutingEngine
from semantic_scoring import SemanticScorer

engine = RoutingEngine()
scorer = SemanticScorer()

# Test: Simple metadata should route to GOOGLE_SAFE if LOW risk and high confidence
text = "Ташкент"
semantic_scores = scorer.score_segment(text, 'LOW')

context = {
    'source_text': text,
    'tm_match_score': 0,
    'risk_result': {'level': 'LOW', 'risk_reasons': [], 'raw_matches': {}},
    'semantic_scores': semantic_scores,
    'glossary_matches': [],
    'forbidden_warnings': [],
    'duplicate_group_id': None,
}

result = engine.route({'id': 1, 'source_text': text}, context)
assert result['route'] == 'GOOGLE_SAFE'
assert result['google_safe_confidence'] >= 0.98
```

### 3. Integration Test: Full Preflight Analysis

1. Import or select existing project in Streamlit app
2. Click "🔍 Analyze Only" in Preflight tab
3. Check that routing results appear in database:
   ```sql
   SELECT id, segment_intent, route, risk_level, google_safe_confidence 
   FROM segments 
   WHERE project_id = ? 
   LIMIT 10
   ```
4. Verify segment_intent correctly identifies:
   - `author_list` for pure author segments
   - `biography_or_affiliation` for person + institution + degree
   - `table_or_numeric` for dosages and values
   - `metadata_simple` for short, simple content
5. Verify routes match expectations:
   - Low-risk simple metadata → GOOGLE_SAFE
   - HIGH/CRITICAL risk → GPT_WITH_GLOSSARY or HUMAN_REVIEW
   - Complex affiliations → GPT_REQUIRED

### 4. Visual Inspection in Segment Editor

1. Go to Segment Editor
2. Select various segments
3. Expand "🧠 Semantic Analysis Scores" expander
4. Verify google_safe_confidence is displayed with explanation:
   - >= 0.98: "✅ Safe to use Google Translate API"
   - 0.85-0.97: "⚠️ Uncertain — will route to GPT"
   - < 0.85: "❌ Blocked — requires GPT"

---

## Risks & Limitations

### ✓ Addressed

- **No keyword blacklists** ✓ Uses morphology families and structural patterns instead
- **No API calls during routing** ✓ Pure local computation (no OpenAI, Google, Anthropic)
- **No false positives on absence of risk** ✓ Positive safety logic: high confidence required for Google
- **No over-routing to Google** ✓ >= 0.98 threshold enforces caution

### ⚠ Limitations

1. **Russian morphology coverage**
   - Covers ~30 common medical roots
   - Rare specialties (гельминтолог, трихолог) not explicitly covered
   - Mitigation: Falls back to medicality < 0.6, routes to GPT if medical context unclear

2. **Structural classification edge cases**
   - Very short affiliations (< 3 words) may be misclassified as author lists
   - Mitigation: Academic degree check disqualifies from author_list

3. **Semantic score calibration**
   - Threshold 0.98 for Google may be conservative for some texts
   - Mitigation: Can be adjusted per project if desired; default is safe

4. **No context across segments**
   - Each segment analyzed independently
   - Project-wide glossary considered, but not segment interdependencies
   - Mitigation: Acceptable for CAT translator workflow

### 🎯 Quality Gates

1. **No GOOGLE_SAFE routing for:**
   - Any affiliation or institution complexity
   - Clinical criticality > 0.0
   - Medicality > 0.2
   - Entity complexity > 0.3
   - Reversibility risk > 0.3

2. **Automatic escalation to HUMAN_REVIEW if:**
   - CRITICAL risk
   - HIGH risk without glossary context
   - Dosage/numeric content with clinical relevance
   - Forbidden terms detected

3. **Default safety:** If google_safe_confidence < 0.98, route to GPT (not Google)

---

## Files Summary

| File | Type | Lines | Purpose |
|------|------|-------|---------|
| structural_classifier.py | NEW | 380 | Pattern-based intent classification |
| routing_engine.py | NEW | 240 | Routing orchestrator + decision logic |
| semantic_scoring.py | MODIFIED | +50 | Russian morphology + improved scoring |
| preflight_analyzer.py | MODIFIED | +10 | Integration with new routing engine |

**No changes to UI needed** — existing columns already display all routing results.

---

## Next Steps (NOT implemented yet)

1. ❌ Batch translation (use routing to optimize order)
2. ❌ Settings UI (adjust thresholds per project)
3. ❌ Export reports (cost breakdown by route)
4. ❌ A/B testing (validate routing accuracy against human translator)

---

**Core Principle Achieved:**
The question is NOT "Did we detect a risky word?"
The question IS "How safe is it to NOT use GPT?"

Default to GPT unless we are HIGHLY CONFIDENT (>= 0.98) it's safe for Google.
