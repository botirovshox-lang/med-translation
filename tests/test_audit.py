"""Журнал действий и авторство (`_audit`, `_confirmed_by_human`, `/api/admin/audit`).

Отметка «подтвердил человек» несёт идентификатор пользователя, прежнее
"human" остаётся действительным — читать поле можно только предикатом.
Каждое из перечисленных действий оставляет ровно одну запись журнала,
журнал виден владельцу и только своей организации. Ни одного вызова модели,
файл состояния не пишется.
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


def n(action):
    return sum(1 for r in main.STATE["audit"] if r["action"] == action)


print("=== 1. Предикат заверения читает и старое, и новое ===")
check(main._confirmed_by_human({"confirmedBy": "human"}), '"human" — заверено')
check(main._confirmed_by_human({"confirmedBy": 7}), "идентификатор пользователя — заверено")
check(not main._confirmed_by_human({"confirmedBy": None}) and not main._confirmed_by_human({}),
      "пусто — не заверено")
check(not main._confirmed_by_human({"confirmedBy": "machine"}), "чужая строка — не заверено")
src = open("backend/main.py", encoding="utf-8").read()
check('confirmedBy") == "human"' not in src, "буквального сравнения со строкой в коде нет")

print("=== 2. Действия оставляют след ===")
c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
r = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"})
A = r.json()["token"]
check(n("login") == 1 and main.STATE["audit"][-1]["login"] == "admin", "вход записан с логином")
c.post("/api/admin/users", headers=H(A), json={"login": "tr", "password": "translator-1", "name": "Т"})
check(n("user.create") == 1, "заведение пользователя")
T = c.post("/api/auth/login", json={"login": "tr", "password": "translator-1"}).json()["token"]
pid = c.post("/api/projects", headers=H(A), json={"title": "p", "src": "RU", "tgt": "EN"}).json()["id"]
proj = main.get_project(pid) if False else next(p for p in main.STATE["projects"] if p["id"] == pid)
proj["segments"].append({"id": 1, "source": "Тест.", "target": "Test.", "status": "translated",
                         "route": "GPT_REQUIRED", "risk": "low", "comments": [], "qa": []})
r = c.post("/api/segments/%d/1/confirm" % pid, headers=H(T))
check(r.status_code == 200, "переводчик подтвердил сегмент")
seg = proj["segments"][0]
uid = [u for u in main.STATE["users"] if u["login"] == "tr"][0]["id"]
check(seg["confirmedBy"] == uid and main._confirmed_by_human(seg), "в отметке — идентификатор переводчика")
check(n("segment.confirm") == 1 and main.STATE["audit"][-1]["login"] == "tr", "подтверждение записано на него")
c.post("/api/segments/%d/1/update" % pid, headers=H(T), json={"target": "Test!"})
c.post("/api/segments/%d/1/update" % pid, headers=H(T), json={"target": "Test!"})
check(n("segment.edit") == 1, "правка записана один раз — повтор того же текста не в счёт")
c.post("/api/glossary", headers=H(A), json={"src": "аудит-термин", "tgt": "audit term", "cat": "Term",
                                            "lang": "RU→EN", "domain": "legal", "isNew": True})
check(n("glossary.save") == 1, "правка глоссария")
TSV = "src\ttgt\nаудит-импорт\taudit import\n".encode("utf-8")
c.post("/api/glossary/import", headers=H(A), files={"file": ("t.tsv", TSV)}, data={"lang": "RU→EN", "domain": "legal"})
check(n("glossary.import") == 0, "сухой импорт не пишется")
c.post("/api/glossary/import", headers=H(A), files={"file": ("t.tsv", TSV)},
       data={"lang": "RU→EN", "domain": "legal", "dry_run": "false"})
check(n("glossary.import") == 1, "настоящий импорт пишется")
c.delete("/api/projects/%d" % pid, headers=H(A))
check(n("project.delete") == 1, "удаление проекта")

print("=== 3. Журнал — владельцу и только своей организации ===")
r = c.get("/api/admin/audit", headers=H(T))
check(r.status_code == 403, "переводчику журнал закрыт")
r = c.get("/api/admin/audit", headers=H(A))
check(r.status_code == 200 and r.json()["items"][0]["action"] == "project.delete", "владелец видит, свежее сверху")
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "zeta", "name": "Z", "ownerLogin": "zo", "ownerPassword": "zo-password-1"})
Z = c.post("/api/auth/login", json={"login": "zo", "password": "zo-password-1"}).json()["token"]
items = c.get("/api/admin/audit", headers=H(Z)).json()["items"]
check(all(i["tenant"] == "zeta" for i in items) and any(i["action"] == "login" for i in items),
      "другая организация видит только своё")
seed = c.get("/api/seed", headers=H(A)).json()
check("audit" not in seed, "/api/seed журнал не отдаёт")

main.STATE["glossary"] = [g for g in main.STATE["glossary"] if g.get("src") not in ("аудит-термин", "аудит-импорт")]
main._invalidate_gloss_index()
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
