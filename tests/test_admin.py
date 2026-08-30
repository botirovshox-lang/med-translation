"""Админка администратора сервиса (`/api/admin/overview`, `all=1` у пользователей
и журнала, прогоны всех организаций). Только суперпользователь; владелец
организации получает 403. Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
S = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "acme", "name": "ACME", "ownerLogin": "acme", "ownerPassword": "acme-pass-123"})
O = c.post("/api/auth/login", json={"login": "acme", "password": "acme-pass-123"}).json()["token"]

print("=== 1. Сводка — только super ===")
check(c.get("/api/admin/overview", headers=H(O)).status_code == 403, "владелец — 403")
r = c.get("/api/admin/overview", headers=H(S))
ov = r.json()
check(r.status_code == 200 and {t["id"] for t in ov["tenants"]} == {"default", "acme"}, "две организации в сводке")
acme = next(t for t in ov["tenants"] if t["id"] == "acme")
check(acme["users"] == 1 and "spend" in acme and "projects" in acme, "люди, проекты, расход по организации")
check("uptimeSec" in ov["process"] and "workerAlive" in ov["jobs"] and "usage" in ov["process"], "здоровье процесса")

print("=== 2. Аккаунты и журнал всех организаций ===")
check(c.get("/api/admin/users?all=1", headers=H(O)).status_code == 403, "владелец all=1 — 403")
r = c.get("/api/admin/users?all=1", headers=H(S))
check({u["tenant"] for u in r.json()["users"]} == {"default", "acme"}, "super видит аккаунты обеих")
r = c.post("/api/admin/users", headers=H(S), json={"login": "acme-tr", "password": "acme-tr-pass1", "tenant": "acme"})
check(r.status_code == 200 and r.json()["user"]["tenant"] == "acme", "super заводит пользователя в чужой организации")
r = c.post("/api/admin/users", headers=H(O), json={"login": "x1", "password": "x1-password", "tenant": "default"})
check(r.status_code == 403, "владелец в чужую — 403")
uid = r2 = [u for u in main.STATE["users"] if u["login"] == "acme-tr"][0]["id"]
check(c.post("/api/admin/users/%d" % uid, headers=H(S), json={"active": False}).status_code == 200, "super правит чужого")
check(c.get("/api/admin/audit?all=1", headers=H(O)).status_code == 403, "журнал всех — владельцу 403")
items = c.get("/api/admin/audit?all=1", headers=H(S)).json()["items"]
check({i["tenant"] for i in items} >= {"default", "acme"}, "super видит журнал обеих")

print("=== 3. Прогон чужой организации виден и останавливается super ===")
main._JOBS[9002] = {"id": 9002, "kind": "full", "project": 1, "status": "running", "tenant": "acme",
                    "total": 5, "done": 1, "counters": {}, "error": None, "params": {},
                    "created": "", "started": "", "finished": None, "ids": [1], "stop": False, "recent": []}
ov = c.get("/api/admin/overview", headers=H(S)).json()
check(any(j["id"] == 9002 and j["tenant"] == "acme" for j in ov["jobs"]["active"]), "в сводке — идущий прогон acme")
check(c.get("/api/jobs/9002", headers=H(S)).status_code == 200, "super читает чужой прогон")
r = c.post("/api/jobs/9002/stop", headers=H(S))
check(r.status_code == 200 and main._JOBS[9002]["stop"], "super остановил чужой прогон")
main._JOBS.pop(9002, None)

print("=== 4. Вход в админку — по нестандартному адресу ===")
check(not main.ADMIN_PATH.startswith("admin") and len(main.ADMIN_PATH) >= 12, "адрес не /admin: /" + main.ADMIN_PATH)
r = c.get("/" + main.ADMIN_PATH)
check(r.status_code == 200 and "window.ADMIN_ENTRY=true" in r.text, "служебный адрес отдаёт приложение с меткой входа")
check(c.get("/admin").status_code == 404 and "ADMIN_ENTRY" not in c.get("/").text, "/admin — 404, главная без метки")
check(c.get("/api/auth/me", headers=H(S)).json().get("adminPath") == "/" + main.ADMIN_PATH, "super видит адрес в /auth/me")
check("adminPath" not in c.get("/api/auth/me", headers=H(O)).json(), "владелец без super — не видит")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
