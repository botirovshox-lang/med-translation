"""
Smoke test: hits every endpoint that the React UI calls.
Each test corresponds to a button/action in the design.
Run while `uvicorn main:app` is up on port 8000.
"""
import json
import sys
import urllib.request
import urllib.error
import urllib.parse

BASE = "http://127.0.0.1:8000/api"

def call(method, path, body=None, expect=200):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, (json.loads(e.read().decode() or "null") if e.code != 204 else None)

results = []
def check(name, ok, info=""):
    mark = "PASS" if ok else "FAIL"
    results.append((name, ok, info))
    print(f"  [{mark}] {name}" + (f"  — {info}" if info else ""))

print("=" * 60)
print("Smoke test: Medical CAT Translator v5.5 API")
print("=" * 60)

# 1. Health
s, d = call("GET", "/health")
check("GET /api/health", s == 200 and d.get("ok"), f"modules={d.get('backendModules')}")

# 2. Auth — wrong password
s, _ = call("POST", "/auth/login", {"password": "wrong-password-xxx"})
check("Login screen → wrong password rejected", s == 401)

# 3. Auth — correct password
s, _ = call("POST", "/auth/login", {"password": "medtranslator2026"})
check("Login screen → correct password accepted", s == 200)

# 4. Seed (hydrate frontend)
s, seed = call("GET", "/seed")
check("Bootstrap /api/seed", s == 200 and "projects" in seed and "glossary" in seed,
      f"projects={len(seed['projects'])}, glossary={len(seed['glossary'])}, tm={len(seed['tm'])}")

# 5. List projects
s, projects = call("GET", "/projects")
check("Tab Import → project list", s == 200 and isinstance(projects, list), f"{len(projects)} projects")
pid = projects[0]["id"]

# 6. Project detail (selecting project in editor)
s, project = call("GET", f"/projects/{pid}")
check(f"Editor → open project #{pid}", s == 200 and "segments" in project, f"{len(project['segments'])} segments")

# 7. Translate a "new" segment via Google
new_seg = next((s for s in project["segments"] if s["status"] == "new"), None)
if new_seg:
    s, d = call("POST", f"/segments/{pid}/{new_seg['id']}/translate", {"engine": "google"})
    check("Editor → Google Translate button",
          s == 200 and d["ok"] and d["segment"]["status"] == "translated",
          f"target='{d['segment']['target'][:50]}...'")

# 8. Translate via GPT
new_seg2 = next((s for s in project["segments"] if s["status"] == "new"), None)
if new_seg2:
    s, d = call("POST", f"/segments/{pid}/{new_seg2['id']}/translate", {"engine": "gpt"})
    check("Editor → GPT Translate button", s == 200 and d["ok"])

# 9. QA
translated = next((s for s in project["segments"] if s["status"] == "translated"), None)
if translated:
    s, d = call("POST", f"/segments/{pid}/{translated['id']}/qa")
    check("Editor → QA button", s == 200 and d["ok"], f"issues={len(d.get('issues', []))}")

# 10. Confirm
qa_done = None
s2, p2 = call("GET", f"/projects/{pid}")
qa_done = next((x for x in p2["segments"] if x["status"] in ("qa", "translated", "back_checked")), None)
if qa_done:
    s, d = call("POST", f"/segments/{pid}/{qa_done['id']}/confirm")
    check("Editor → Confirm button (✓)", s == 200 and d["segment"]["status"] == "confirmed")

# 11. Revert (click on green ✓ to undo)
if qa_done:
    s, d = call("POST", f"/segments/{pid}/{qa_done['id']}/revert")
    check("Editor → click on ✓ to revert", s == 200 and d["segment"]["status"] != "confirmed",
          f"status: confirmed→{d['segment']['status']}")

# 12. Update target (manual edit + save)
any_seg = project["segments"][0]
s, d = call("POST", f"/segments/{pid}/{any_seg['id']}/update", {"target": "Manually edited translation"})
check("Editor → manual edit + save", s == 200 and d["segment"]["target"] == "Manually edited translation")

# 13. Add comment
s, d = call("POST", f"/segments/{pid}/{any_seg['id']}/update", {"comment": "Smoke test comment"})
check("Editor detail → add comment", s == 200)

# 14. Batch translate Google (low-risk)
s, d = call("POST", f"/projects/{pid}/batch", {"engine": "google"})
check("Editor → batch Google translate", s == 200 and d.get("ok"), f"translated={d.get('count', 0)}")

# 15. Batch translate GPT (non-low risk)
s, d = call("POST", f"/projects/{pid}/batch", {"engine": "gpt"})
check("Editor → batch GPT translate", s == 200 and d.get("ok"), f"translated={d.get('count', 0)}")

# 16. Preflight analyze
s, d = call("POST", f"/projects/{pid}/preflight")
check("Preflight → Запустить анализ",
      s == 200 and d.get("ok") and "routes" in d and "risks" in d,
      f"routes={list(d['routes'].keys())}, time={d.get('analysisTime')}s")

# 17. Create project (Import tab → upload)
s, d = call("POST", "/projects", {"title": "Smoke test project", "src": "RU", "tgt": "EN"})
check("Tab Import → create project",
      s == 200 and d.get("id") and len(d["segments"]) > 0,
      f"new project id={d.get('id')}")
new_pid = d["id"]

# 18. Export
s, d = call("POST", f"/projects/{pid}/export", {"format": "docx"})
check("Tab Export → Скачать DOCX", s == 200 and d.get("ok"), f"file={d.get('file')}")

s, d = call("POST", f"/projects/{pid}/export", {"format": "pdf"})
check("Tab Export → Скачать PDF", s == 200 and d.get("ok"))

# 19. Glossary — add term
s, d = call("POST", "/glossary", {
    "src": "тест-термин", "tgt": "test term", "cat": "Test", "freq": 1, "conf": "Medium", "isNew": True,
})
check("Tab Glossary → add term", s == 200 and d.get("ok"))

# 20. Glossary — update existing
s, d = call("POST", "/glossary", {
    "src": "тест-термин", "tgt": "test term updated", "cat": "Test", "freq": 2, "conf": "High", "isNew": False,
})
check("Tab Glossary → edit term", s == 200)

# 21. Glossary — delete
s, d = call("DELETE", "/glossary?src=" + urllib.parse.quote("тест-термин"))
check("Tab Glossary → delete term", s == 200 and d.get("ok"))

# 22. TM — delete entry
s, seed2 = call("GET", "/seed")
tm_first = seed2["tm"][0]["src"] if seed2["tm"] else None
if tm_first:
    s, d = call("DELETE", "/tm?src=" + urllib.parse.quote(tm_first))
    check("Tab TM → delete entry", s == 200 and d.get("ok"))

# 23. State persists (re-fetch and compare project count)
s, seed3 = call("GET", "/seed")
check("State persisted to disk (reload seed)",
      s == 200 and any(p["id"] == new_pid for p in seed3["projects"]),
      f"smoke-test project still present after multiple writes")

# Summary
print("=" * 60)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"Total: {len(results)} | Pass: {passed} | Fail: {failed}")
if failed:
    print("\nFailed tests:")
    for name, ok, info in results:
        if not ok:
            print(f"  - {name}  {info}")
    sys.exit(1)
else:
    print("ALL BUTTONS OK")
