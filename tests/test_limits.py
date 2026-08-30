"""Лимит расхода по организации: 402 на платное, бесплатное работает.

Факт расхода складывается по организации и месяцу (`_spend_add` из
`_note_usage`), лимит ставит суперпользователь. На исчерпанном лимите
платные команды отвечают 402 с остатком, а правка начертания, откаты,
пересчёт back-check, принятие кандидатов, разбор состава и экспорт —
работают: лимит режет деньги, а не доступ к оплаченному. Ни одного
вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["spend"] = [], [], {}
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "acme", "name": "ACME", "ownerLogin": "acme", "ownerPassword": "acme-pass-123"})
B = c.post("/api/auth/login", json={"login": "acme", "password": "acme-pass-123"}).json()["token"]
pid = c.post("/api/projects", headers=H(B), json={"title": "p", "src": "RU", "tgt": "EN"}).json()["id"]
proj = next(p for p in main.STATE["projects"] if p["id"] == pid)
proj["segments"].append({"id": 1, "source": "Тест.", "target": "", "status": "new",
                         "route": "GPT_REQUIRED", "risk": "low", "comments": [], "qa": []})


class _Resp:
    usage = {"prompt_tokens": 1000, "completion_tokens": 500}


print("=== 1. Расход складывается по организации и месяцу ===")
tok = main.CURRENT_SESSION.set({"tenant": "acme", "user": 2, "role": "owner"})
try:
    main._note_usage("translate", "gpt-4o", _Resp())
    main._note_usage("translate", "no-such-model", _Resp())
finally:
    main.CURRENT_SESSION.reset(tok)
st = main._spend_status("acme")
check(st["calls"] == 2 and st["unpriced"] == 1 and st["spentUsd"] > 0, "две записи, одна без цены, сумма > 0: %s" % st)
check(main._spend_status("default")["calls"] == 0, "у другой организации — ноль")
me = c.get("/api/auth/me", headers=H(B)).json()
check(me["spend"]["tenant"] == "acme" and me["spend"]["limitUsd"] is None and not me["spend"]["over"],
      "/auth/me показывает расход, лимита нет")

print("=== 2. Лимит ставит только super ===")
r = c.post("/api/admin/tenants/acme", headers=H(B), json={"limitUsd": 100})
check(r.status_code == 403, "владелец сам себе лимит не ставит")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"limitUsd": 0.001})
check(r.status_code == 200 and r.json()["spend"]["over"], "super поставил лимит ниже расхода — over")
r = c.get("/api/admin/tenants", headers=H(A))
check(r.status_code == 200 and any(t["id"] == "acme" and t["spend"]["over"] for t in r.json()["tenants"]),
      "список организаций с расходом")

print("=== 3. На исчерпанном лимите: платное — 402, бесплатное — работает ===")
paid = [("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "ids": [1]}),
        ("POST", "/api/segments/%d/1/translate" % pid, {}),
        ("POST", "/api/segments/%d/1/backcheck" % pid, {}),
        ("POST", "/api/projects/%d/batch" % pid, {}),
        ("POST", "/api/glossary/audit", {})]
for m, path, body in paid:
    r = c.request(m, path, headers=H(B), json=body)
    check(r.status_code == 402 and "spend" in r.json(), "%s → 402" % path)
free = [("POST", "/api/projects/%d/run-plan" % pid, {"steps": ["translate"]}),
        ("POST", "/api/projects/%d/term-case" % pid, {}),
        ("POST", "/api/projects/%d/backcheck/rescore" % pid, {}),
        ("POST", "/api/projects/%d/repair/accept-batch" % pid, {}),
        ("POST", "/api/glossary/revert-repairs", {"src": "x", "tgt": "y"}),
        ("GET", "/api/projects/%d/analysis" % pid, None),
        ("GET", "/api/projects/%d/coverage" % pid, None),
        ("POST", "/api/projects/%d/export" % pid, {"format": "xlsx"})]
for m, path, body in free:
    r = c.request(m, path, headers=H(B), **({"json": body} if body is not None else {}))
    check(r.status_code != 402, "%s → не 402 (%d)" % (path, r.status_code))

print("=== 4. Снятие лимита ===")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"clearLimit": True})
check(r.status_code == 200 and not r.json()["spend"]["over"], "лимит снят")
r = c.post("/api/segments/%d/1/backcheck" % pid, headers=H(B), json={})
check(r.status_code != 402, "платное снова доступно")
seed = c.get("/api/seed", headers=H(B)).json()
check("spend" not in seed, "/api/seed расход по организациям не отдаёт")

main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] != pid]
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
