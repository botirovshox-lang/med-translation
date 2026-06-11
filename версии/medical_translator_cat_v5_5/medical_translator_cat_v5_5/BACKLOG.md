# Backlog — CAT Translator v2

## Priority 1
- Batch translate selected segments
- Batch QA selected segments
- Batch back-translation check
- Auto-confirm safe segments

## Priority 2
- Numerical Integrity Check
- Hallucination Check
- Dual Review for complex/failed segments

## Priority 3
- Glossary CSV/XLSX import/export
- Term highlighting
- Glossary violation detector

## Priority 4
- TMX import
- Better fuzzy TM
- Auto-apply exact TM

## Priority 5
- Better DOCX run-level formatting preservation
- Segment map validation
- Bilingual review DOCX



# v6 — Intelligent Workflow System (NEW PRIORITY)

## Goal
Reduce manual decisions and unnecessary API/token usage.

## 6.1 Risk Analyzer
Assign:
- low
- medium
- high
- critical

Factors:
- segment length
- numbers / units
- mg/ml/%
- negations
- medical density
- glossary density
- tables
- definitions
- diagnostic criteria
- classifications
- repeated TM content

## 6.2 Suggested Workflow
Low:
- Translate only

Medium:
- Translate + QA

High:
- Translate + QA + Back-check

Critical:
- Translate + QA + Back-check + Numerical Integrity

## 6.3 Run Suggested Workflow
One-click execution with automatic routing.

## 6.4 Token Estimator
Show:
- estimated token count
- estimated API cost
- estimated runtime

## 6.5 Smart QA Skipping
Skip:
- headings
- figure labels
- exact TM segments

# v7 — Batch Processing (NEW PRIORITY)

## 7.1 Batch Translate
Modes:
- all untranslated
- selected
- low-risk only
- medium-risk only

## 7.2 Batch QA
Run only for:
- medium/high/critical

## 7.3 Batch Back-check
Run only for:
- high/critical

## 7.4 Queue System
Need:
- retries
- pause/resume
- stop queue
- progress tracking

## 7.5 Progress Dashboard
Metrics:
- translated
- qa_done
- confirmed
- failed
- high_risk
- estimated remaining cost

# v8 — Medical Safety Layer (NEW PRIORITY)

## 8.1 Numerical Integrity Agent
Check:
- mg
- mcg
- %
- dosages
- ranges
- stages
- classifications
- lab values

## 8.2 Hallucination Agent
Detect:
- additions
- omissions
- invented claims
- unsupported interpretations

## 8.3 Contradiction Detector
Examples:
- acute vs chronic
- positive vs negative
- increase vs decrease

## 8.4 Glossary Enforcement
Warn when approved glossary terms are ignored.

# Recommended implementation order NOW

1. Risk Analyzer
2. Suggested Workflow
3. Run Suggested Workflow
4. Batch Translate
5. Batch QA
6. Numerical Integrity
7. Batch Back-check
8. Progress Dashboard
9. Diff Viewer
10. Hallucination Agent
11. Dual Review
12. Ollama/local provider mode
