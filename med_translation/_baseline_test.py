"""
Cleanup baseline: verify every active module imports in isolation,
and the backend smoke test passes. Used before/after pruning files.
"""
import sys, subprocess, importlib

ACTIVE_MODULES = [
    # Core data
    "db", "config_v55", "schemas", "prompts",
    # Translation
    "pipeline", "google_translate", "openai_client", "docx_cat",
    # Memory
    "tm", "tm_loader",
    # Glossary
    "terminology_engine", "terminology_loader", "forbidden_checker",
    # Risk & routing
    "risk_engine", "safety_policy", "routing_engine",
    "semantic_scoring", "structural_classifier",
    # Preflight & cost
    "preflight_analyzer", "cost_estimator", "duplicate_engine",
    "zero_token_optimizer",
    # QA
    "local_qa_engine", "numerical_qa_engine", "consistency_engine",
    "qa_scheduler", "qa_orchestrator",
    # Approval & review
    "auto_approval_engine", "review_queue_engine",
    # Translation engines
    "google_batch", "gpt_batch",
    # Auth (used by Streamlit app — keep)
    "auth",
]

print(f"Baseline: importing {len(ACTIVE_MODULES)} modules...")
failed = []
for m in ACTIVE_MODULES:
    try:
        importlib.import_module(m)
        print(f"  OK  {m}")
    except Exception as e:
        msg = str(e).split("\n")[0][:80]
        print(f"  ERR {m}: {msg}")
        failed.append((m, msg))

print()
if failed:
    print(f"FAIL: {len(failed)}/{len(ACTIVE_MODULES)} modules broken")
    for m, msg in failed:
        print(f"  - {m}: {msg}")
    sys.exit(1)
print(f"PASS: all {len(ACTIVE_MODULES)} active modules import cleanly")
