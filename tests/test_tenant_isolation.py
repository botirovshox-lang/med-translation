"""Изоляция организаций: чужое не видно, не читается и не становится донором.

Организация — третье измерение области `(пара, тематика, организация)`,
а единственное горло к проекту по номеру — `get_project` (чужой → 404,
не 403: 403 подтверждал бы, что проект существует). Здесь две организации
живут в одном STATE, и проверяется, что ни один список, ни один эндпоинт
с {pid}, ни повторы исходника, ни индекс автоодобрения не пересекают
границу. Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"   # чтобы 503 «нет ключа» не стоял раньше get_project
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"] = [], []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
r = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"})
A = r.json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
B = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]

print("=== 1. Проект одной организации не виден другой ===")
r = c.post("/api/projects", headers=H(A), json={"title": "A-doc", "src": "RU", "tgt": "EN"})
pa = r.json()["id"]
check(r.status_code == 200 and r.json()["tenant"] == "default" and r.json()["segments"] == [],
      "проект A заведён в default и ПУСТЫМ")
r = c.post("/api/projects", headers=H(B), json={"title": "B-doc", "src": "DE", "tgt": "EN"})
pb = r.json()["id"]
check(r.json()["tenant"] == "beta", "проект B заведён в beta")
ids_a = {p["id"] for p in c.get("/api/projects", headers=H(A)).json()}
ids_b = {p["id"] for p in c.get("/api/projects", headers=H(B)).json()}
check(pb not in ids_a and pa not in ids_b and pb in ids_b, "списки проектов не пересекаются")
seed_b = c.get("/api/seed", headers=H(B)).json()
check([p["id"] for p in seed_b["projects"]] == [pb], "/api/seed у B — только его проект")

print("=== 2. Каждый эндпоинт с {pid} чужому отвечает 404 ===")
routes = [r for r in main.app.routes if hasattr(r, "path") and "{pid}" in r.path]
bad = []
for rt in routes:
    path = rt.path.replace("{pid}", str(pa)).replace("{sid}", "1").replace("{stamp}", "x").replace("{jid}", "1")
    for m in (getattr(rt, "methods", None) or {"GET"}):
        if m == "HEAD":
            continue
        kw = {"json": {}} if m in ("POST", "PUT") else {}
        resp = c.request(m, path, headers=H(B), **kw)
        # 422 — проверка тела запроса FastAPI ДО обработчика: о проекте
        # она ничего не говорит, значит и не выдаёт.
        if resp.status_code not in (404, 422):
            bad.append((m, rt.path, resp.status_code))
check(not bad, "чужой токен → 404 на всех %d маршрутах" % len(routes)
      + (" — " + str(bad[:6]) if bad else ""))
r = c.get("/api/projects/%d" % pa, headers=H(A))
check(r.status_code == 200, "свой проект — 200")

print("=== 3. Глоссарий, TM, очередь терминов — по организациям ===")
r = c.post("/api/glossary", headers=H(A), json={"src": "договор", "tgt": "contract", "cat": "Term",
                                                "lang": "RU→EN", "domain": "legal", "isNew": True})
check(r.status_code == 200, "A записал термин")
g_a = [g for g in main.STATE["glossary"] if g.get("src") == "договор"]
check(g_a and g_a[-1].get("tenant") == "default", "запись несёт организацию")
lst_b = c.get("/api/glossary?q=договор", headers=H(B)).json()
items_b = lst_b.get("items", lst_b) if isinstance(lst_b, dict) else lst_b
check(not any(g.get("src") == "договор" for g in items_b), "B не видит термин A в списке")
with_sess = lambda t, f: (main.CURRENT_SESSION.set(t), f())[1]
tok = main.CURRENT_SESSION.set({"tenant": "beta", "user": 2, "role": "owner"})
try:
    check(main._glossary_entry("договор", ("RU→EN", "legal")) is None, "…и в индексе области")
    check(main._project_scope({"src": "RU", "tgt": "EN", "domain": "legal", "tenant": "beta"})[2] == "beta",
          "область проекта несёт организацию")
    main._tm_upsert("исходник", "перевод", {"src": "RU", "tgt": "EN", "tenant": "beta"})
finally:
    main.CURRENT_SESSION.reset(tok)
tm_b = [t for t in main.STATE["tm"] if t.get("src") == "исходник"]
check(tm_b and tm_b[0].get("tenant") == "beta", "запись TM несёт организацию")
hits, tm_hit = main._get_context("исходник", project={"src": "RU", "tgt": "EN", "domain": "legal",
                                                     "tenant": "default"}, with_tm=True)
check(tm_hit is None, "TM другой организации не подставляется")
hits, tm_hit = main._get_context("исходник", project={"src": "RU", "tgt": "EN", "domain": "legal",
                                                     "tenant": "beta"}, with_tm=True)
check(tm_hit is not None, "…а своя — подставляется")

print("=== 4. Индекс автоодобрения и обходы — только своя организация ===")
tok = main.CURRENT_SESSION.set({"tenant": "beta", "user": 2, "role": "owner"})
try:
    check({p["id"] for p in main._tenant_projects()} == {pb}, "_tenant_projects: только beta")
    try:
        main.get_project(pa)
        check(False, "get_project чужого → 404")
    except main.HTTPException as e:
        check(e.status_code == 404, "get_project чужого → 404")
finally:
    main.CURRENT_SESSION.reset(tok)
import inspect
src = inspect.getsource(main._auto_context)
check("_tenant_projects()" in src and 'STATE["projects"]' not in src,
      "_auto_context строит индекс по своей организации")

print("=== 5. Прогоны: список и доступ по номеру ===")
main._JOBS[9001] = {"id": 9001, "kind": "full", "project": pa, "status": "done", "tenant": "default",
                    "total": 0, "done": 0, "counters": {}, "error": None, "params": {},
                    "created": "", "started": None, "finished": None, "ids": [], "stop": False, "recent": []}
check(c.get("/api/jobs/9001", headers=H(B)).status_code == 404, "чужой прогон по номеру — 404")
check(c.get("/api/jobs/9001", headers=H(A)).status_code == 200, "свой — 200")
check(all(j["id"] != 9001 for j in c.get("/api/jobs", headers=H(B)).json()["jobs"]), "в списке B его нет")
main._JOBS.pop(9001, None)

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
