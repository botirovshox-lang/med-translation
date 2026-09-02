"""Свои предметные области организации (`/api/admin/domains`, `_resolve_domain`).

Область — параметр проекта, из неё строятся все промпты. Своя область —
копия встроенного шаблона с правками; ищется первой и только в своей
организации; для неё автоодобрение по умолчанию строгое (приказ только
от человека). Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["domains"] = [], [], []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/users", headers=H(A), json={"login": "tr", "password": "translator-1"})
T = c.post("/api/auth/login", json={"login": "tr", "password": "translator-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
B = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]

print("=== 1. Создание из шаблона ===")
r = c.post("/api/admin/domains", headers=H(T), json={"label": "Патенты", "base": "legal"})
check(r.status_code == 403, "переводчик области не заводит")
r = c.post("/api/admin/domains", headers=H(A),
           json={"label": "Патенты", "base": "legal", "expert": "patent translator",
                 "cats": ["Claim", "Prior art", ""]})
d = r.json().get("domain", {})
check(r.status_code == 200 and d.get("id", "").startswith("area-"), "область заведена: %s" % d.get("id"))
did = d["id"]
check(d["expert"] == "patent translator" and d["terminology"].startswith("standard legal"),
      "своё поле взято, остальное — из шаблона legal")
check(d["cats"] == ["Claim", "Prior art"] and d["strict"] is True, "категории почищены, строгость по умолчанию")
r = c.post("/api/admin/domains", headers=H(A), json={"id": "medical", "label": "x"})
check(r.status_code == 409, "встроенный идентификатор занят")
r = c.post("/api/admin/domains", headers=H(A), json={"id": did, "label": "x"})
check(r.status_code == 409, "повтор своего — 409")

print("=== 2. Разрешение и промпты ===")
tok = main.CURRENT_SESSION.set({"tenant": "default", "user": 1, "role": "owner"})
try:
    dom = main._resolve_domain(did)
    check(dom.get("custom") and dom["expert"] == "patent translator", "_resolve_domain находит свою область")
    check(main._auto_policy(did)["allow_verified"] is False, "политика автоодобрения строгая")
    sysmsg = main._translate_system("RU", "EN", [], None, False, did, main._resolve_model(None))
    check("patent translator" in sysmsg, "промпт перевода берёт expert своей области")
    models = main.list_models()
    check(any(x["id"] == did and x.get("custom") for x in models["domains"]), "/api/models перечисляет свою область")
finally:
    main.CURRENT_SESSION.reset(tok)
tok = main.CURRENT_SESSION.set({"tenant": "beta", "user": 3, "role": "owner"})
try:
    check(main._resolve_domain(did)["id"] == main.LEGACY_DOMAIN, "другая организация её не видит — дефолт")
finally:
    main.CURRENT_SESSION.reset(tok)
r = c.get("/api/admin/domains", headers=H(B))
check(r.status_code == 200 and r.json()["domains"] == [], "у beta своих областей нет")

print("=== 3. Правка, смена области проекта, удаление ===")
r = c.post("/api/admin/domains/%s" % did, headers=H(A), json={"strict": False, "terminology": "USPTO usage"})
check(r.status_code == 200 and r.json()["domain"]["strict"] is False, "правка полей")
pid = c.post("/api/projects", headers=H(A), json={"title": "p", "src": "RU", "tgt": "EN", "domain": did}).json()["id"]
proj = next(p for p in main.STATE["projects"] if p["id"] == pid)
check(proj["domain"] == did, "проект создан в своей области")
r = c.delete("/api/admin/domains/%s" % did, headers=H(A))
check(r.status_code == 409, "область с проектами не удаляется")
r = c.post("/api/projects/%d/domain" % pid, headers=H(A), json={"domain": "technical"})
check(r.status_code == 200 and r.json()["prev"] == did and "rescore" in r.json()["note"], "смена области проекта, совет пересчитать")
r = c.post("/api/projects/%d/domain" % pid, headers=H(A), json={"domain": "nope"})
check(r.status_code == 400, "неизвестная область — 400")
r = c.delete("/api/admin/domains/%s" % did, headers=H(A))
check(r.status_code == 200 and not main._tenant_domains("default"), "теперь удаляется")

main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] != pid]
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
