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

print("=== 3b. Удаление аккаунтов и организаций ===")
uid2 = [u for u in main.STATE["users"] if u["login"] == "acme-tr"][0]["id"]
check(c.request("DELETE", "/api/admin/users/1", headers=H(S)).status_code == 400, "себя удалить нельзя")
check(c.request("DELETE", "/api/admin/users/%d" % uid2, headers=H(S)).status_code == 200, "super удалил чужого переводчика")
check(not any(u["id"] == uid2 for u in main.STATE["users"]), "запись исчезла")
owner_id = [u for u in main.STATE["users"] if u["login"] == "acme"][0]["id"]
check(c.request("DELETE", "/api/admin/users/%d" % owner_id, headers=H(S)).status_code == 409,
      "последнего владельца организации удалить нельзя")
check(c.request("DELETE", "/api/admin/tenants/acme", headers=H(O)).status_code == 403, "владелец организации не удаляет")
check(c.request("DELETE", "/api/admin/tenants/default", headers=H(S)).status_code == 400, "организацию по умолчанию — нельзя")
main.STATE["projects"].append({"id": 987654, "tenant": "acme", "title": "x", "segments": [],
                               "src": "RU", "tgt": "EN", "domain": "medical"})
check(c.request("DELETE", "/api/admin/tenants/acme", headers=H(S)).status_code == 409,
      "организация с проектами не удаляется — работа не пропадает молча")
main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] != 987654]
r = c.request("DELETE", "/api/admin/tenants/acme", headers=H(S))
check(r.status_code == 200 and r.json()["usersRemoved"] == 1, "пустая организация удалена вместе с владельцем")
check(not main._tenant_rec("acme") and not any(u.get("tenant") == "acme" for u in main.STATE["users"]),
      "ни организации, ни её людей не осталось")
check(c.get("/api/auth/me", headers=H(O)).status_code == 401, "его сессия закрыта")
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "acme", "name": "ACME", "ownerLogin": "acme", "ownerPassword": "acme-pass-123"})
O = c.post("/api/auth/login", json={"login": "acme", "password": "acme-pass-123"}).json()["token"]

print("=== 4. Вход в админку — по нестандартному адресу ===")
check(not main.ADMIN_PATH.startswith("admin") and len(main.ADMIN_PATH) >= 12, "адрес не /admin: /" + main.ADMIN_PATH)
r = c.get("/" + main.ADMIN_PATH)
check(r.status_code == 200 and "window.ADMIN_ENTRY=true" in r.text, "служебный адрес отдаёт приложение с меткой входа")
check(c.get("/admin").status_code == 404 and "ADMIN_ENTRY" not in c.get("/").text, "/admin — 404, главная без метки")
check(c.get("/api/auth/me", headers=H(S)).json().get("adminPath") == "/" + main.ADMIN_PATH, "super видит адрес в /auth/me")
check("adminPath" not in c.get("/api/auth/me", headers=H(O)).json(), "владелец без super — не видит")

print("\n=== 5. История входов ===")
# Журнал КОЛЬЦЕВОЙ, поэтому «когда человек заходил в последний раз» лежит
# на самой записи и вытесниться не может. А неудачная попытка пишется
# в организацию ТОГО, чью запись подбирают, — иначе владелец своего
# предупреждения не увидит.
check(c.get("/api/admin/logins", headers=H(O)).json().get("ok") is True, "владелец видит СВОЮ историю")
check(c.get("/api/admin/logins?all=1", headers=H(O)).status_code == 403,
      "историю всех организаций — только суперпользователю")
r = c.get("/api/admin/logins?all=1", headers=H(S)).json()
me = next(u for u in r["users"] if u["login"] == "acme")
check(me["lastLogin"] and me["loginCount"] >= 1, "последний вход записан на учётной записи")
check(any(e["action"] == "login" for e in r["events"]), "события входа в журнале")
c.post("/api/auth/login", json={"login": "acme", "password": "неверный"})
r2 = c.get("/api/admin/logins?all=1", headers=H(S)).json()
bad = [e for e in r2["events"] if e["action"] == "login.fail"]
check(bad and bad[0].get("triedLogin") == "acme", "неудачная попытка записана с логином")
check(bad[0].get("tenant") == "acme",
      "и записана в организацию того, чью запись подбирали: " + str(bad[0].get("tenant")))
check(c.get("/api/admin/logins", headers=H(O)).json()["users"][0]["tenant"] == "acme",
      "владелец видит только своих")
never = c.get("/api/admin/logins?all=1", headers=H(S)).json()["users"]
check(never[0]["lastLogin"] is None or never[0]["lastLogin"] <= (never[-1]["lastLogin"] or "я"),
      "не заходившие — первыми: список нужен, чтобы увидеть тех, кто НЕ пришёл")

print("\n=== 6. История прогонов с фактической суммой ===")
# Берётся из runCosts, а не из списка задач: те живут в памяти процесса
# и теряются при рестарте, а расход терять нельзя.
main.STATE["runCosts"] = [
    {"job": 1, "kind": "full", "project": 5, "tenant": "acme", "status": "done",
     "finished": "2026-09-07 10:00", "segments": 20, "est": 0.2, "cost": 0.1,
     "calls": 40, "unpriced": 0, "in": 1000, "cached_in": 0, "out": 500,
     "reasoning": 0, "steps": {}},
    {"job": 2, "kind": "full", "project": 6, "tenant": "default", "status": "done",
     "finished": "2026-09-07 11:00", "segments": 10, "est": None, "cost": 0.05,
     "calls": 10, "unpriced": 2, "in": 100, "cached_in": 0, "out": 50,
     "reasoning": 0, "steps": {}}]
check(c.get("/api/admin/runs?all=1", headers=H(O)).status_code == 403,
      "прогоны всех организаций — только суперпользователю")
own = c.get("/api/admin/runs", headers=H(O)).json()
check(len(own["runs"]) == 1 and own["runs"][0]["tenant"] == "acme", "владелец видит только свои прогоны")
allr = c.get("/api/admin/runs?all=1", headers=H(S)).json()
check(len(allr["runs"]) == 2, "суперпользователь видит все")
check(abs(allr["totalUsd"] - 0.15) < 1e-6, "сумма факта: " + str(allr["totalUsd"]))
check(allr["estRatio"] == 2.0, "поправка сметы считается только по прогонам, где есть ОБА числа")
check(allr["estRuns"] == 1, "и таких прогонов один")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
