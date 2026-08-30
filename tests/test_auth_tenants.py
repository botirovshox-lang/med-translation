"""Пользователи, организации, две роли (`/api/auth/*`, `/api/admin/*`).

Что сторожится: bootstrap на пустой базе заводит владельца с паролем
APP_PASSWORD; прежний формат входа `{password}` без логина ещё работает;
хеш — pbkdf2 с солью; переводчик на владельческом эндпоинте получает 403
(право сделать проверяет СЕРВЕР, а не погашенная кнопка); `/api/seed`
не отдаёт хеши паролей. Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "test-boot-password"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
# Чистая база пользователей — что бы ни лежало в локальном state.json.
main.STATE["users"] = []
main.STATE["tenants"] = []
main._SESSIONS.clear()
main._LOGIN_FAILS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)

print("=== 1. Bootstrap и прежний формат входа ===")
r = c.post("/api/auth/login", json={"password": "wrong"})
check(r.status_code == 401, "неверный пароль — 401")
check(len(main.STATE["users"]) == 1 and main.STATE["users"][0]["login"] == "admin",
      "первый вход завёл владельца admin")
u = main.STATE["users"][0]
check(u["role"] == "owner" and u.get("super") and u["tenant"] == "default", "он owner + super в default")
check(len(u["hash"]) == 64 and len(u["salt"]) == 32 and "test-boot" not in u["hash"], "pbkdf2 с солью")
r = c.post("/api/auth/login", json={"password": "test-boot-password"})
check(r.status_code == 200 and r.json().get("token"), "вход прежним форматом (без логина) работает")
owner_tok = r.json()["token"]
check(r.json()["me"]["role"] == "owner", "ответ входа несёт me")
r = c.post("/api/auth/login", json={"login": "ADMIN", "password": "test-boot-password"})
check(r.status_code == 200, "логин регистронезависим")

H = lambda t: {"Authorization": "Bearer " + t}
print("=== 2. /auth/me и /api/seed ===")
r = c.get("/api/auth/me", headers=H(owner_tok))
check(r.status_code == 200 and r.json()["me"]["login"] == "admin" and r.json()["can"]["owner"],
      "/auth/me: владелец")
r = c.get("/api/auth/me")
check(r.status_code == 401, "без токена — 401")
r = c.get("/api/seed", headers=H(owner_tok))
check(r.status_code == 200 and "users" not in r.json() and "tenants" not in r.json(),
      "/api/seed не отдаёт пользователей (там хеши)")

print("=== 3. Владелец заводит переводчика, переводчик упирается в 403 ===")
r = c.post("/api/admin/users", headers=H(owner_tok),
           json={"login": "petrov", "password": "short"})
check(r.status_code == 400, "короткий пароль — 400")
r = c.post("/api/admin/users", headers=H(owner_tok),
           json={"login": "petrov", "password": "long-enough-1", "name": "Пётр Петров"})
check(r.status_code == 200 and r.json()["user"]["role"] == "translator", "переводчик заведён")
check(r.json()["user"]["initials"] == "ПП", "инициалы из имени")
r = c.post("/api/admin/users", headers=H(owner_tok),
           json={"login": "petrov", "password": "long-enough-1"})
check(r.status_code == 409, "повтор логина — 409")
r = c.post("/api/auth/login", json={"login": "petrov", "password": "long-enough-1"})
tr_tok = r.json()["token"]
check(r.status_code == 200 and r.json()["me"]["role"] == "translator", "переводчик вошёл")
for method, path in [("DELETE", "/api/tm"), ("DELETE", "/api/projects/1"),
                     ("POST", "/api/glossary/purge"), ("GET", "/api/admin/users"),
                     ("POST", "/api/glossary/demote")]:
    r = c.request(method, path, headers=H(tr_tok), json={})
    check(r.status_code == 403, "%s %s переводчику — 403" % (method, path))
r = c.get("/api/models", headers=H(tr_tok))
check(r.status_code == 200, "обычный эндпоинт переводчику открыт")
r = c.get("/api/admin/users", headers=H(owner_tok))
check(r.status_code == 200 and len(r.json()["users"]) == 2, "владелец видит двоих")

print("=== 4. Правка пользователя ===")
uid = [x for x in main.STATE["users"] if x["login"] == "petrov"][0]["id"]
r = c.post("/api/admin/users/%d" % uid, headers=H(owner_tok), json={"password": "another-pass-9"})
check(r.status_code == 200, "пароль сменён")
r = c.get("/api/auth/me", headers=H(tr_tok))
check(r.status_code == 401, "прежняя сессия переводчика закрыта")
r = c.post("/api/auth/login", json={"login": "petrov", "password": "another-pass-9"})
check(r.status_code == 200, "вход новым паролем")
r = c.post("/api/admin/users/1", headers=H(owner_tok), json={"role": "translator"})
check(r.status_code == 400, "владелец не снимает роль с себя")
r = c.post("/api/admin/users/%d" % uid, headers=H(owner_tok), json={"active": False})
r = c.post("/api/auth/login", json={"login": "petrov", "password": "another-pass-9"})
check(r.status_code == 401, "отключённый пользователь не входит")

print("=== 5. Организации заводит только super ===")
r = c.post("/api/admin/tenants", headers=H(owner_tok),
           json={"id": "acme", "name": "ACME", "ownerLogin": "acme-owner", "ownerPassword": "acme-pass-123"})
check(r.status_code == 200 and r.json()["owner"]["tenant"] == "acme", "организация и владелец заведены")
r = c.post("/api/auth/login", json={"login": "acme-owner", "password": "acme-pass-123"})
acme_tok = r.json()["token"]
r = c.post("/api/admin/tenants", headers=H(acme_tok),
           json={"id": "beta", "name": "B", "ownerLogin": "b", "ownerPassword": "b-pass-12345"})
check(r.status_code == 403, "владелец без super организаций не заводит")
r = c.get("/api/admin/users", headers=H(acme_tok))
check([x["login"] for x in r.json()["users"]] == ["acme-owner"], "владелец acme видит только своих")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
