"""Самостоятельная регистрация и вход по почте.

Человек заводит организацию сам: почта + пароль → код в письме →
подтверждение → он владелец своей организации. Сторожится главное:
новая организация НЕ получает права тратить деньги (лимит SIGNUP_TRIAL_USD),
чужие данные ей не видны, «забыли пароль» не отвечает на вопрос
«есть ли такой клиент», код нельзя подобрать, а вход работает и по логину,
и по почте. Писем никуда не уходит: SMTP не настроен, mailer пишет в журнал.
Ни одного вызова модели.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["SIGNUP_ENABLED"] = "1"
os.environ["SIGNUP_TRIAL_USD"] = "0"
for k in ("SMTP_HOST", "MAIL_FROM", "SMTP_USER"):
    os.environ.pop(k, None)
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main.STATE["spend"] = {}
main._SESSIONS.clear(); main._LOGIN_FAILS.clear(); main._SIGNUP_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}


def code_of(email):
    """Код из письма — в тесте берём из записи пользователя: сам код нигде
    не хранится (только хэш), поэтому перевыпускаем и читаем возвращённый."""
    u = main._user_by_email(email)
    return main._issue_code(u, u["authCode"]["kind"])


print("=== 1. Регистрация: организация, владелец, код ===")
r = c.get("/api/auth/signup-info")
check(r.status_code == 200 and r.json()["signup"] and r.json()["mail"] is False,
      "экран входа знает: регистрация открыта, почта не настроена")
r = c.post("/api/auth/register", json={"email": "не-почта", "password": "long-enough-1", "accept": True})
check(r.status_code == 400, "кривой адрес — 400")
r = c.post("/api/auth/register", json={"email": "boss@acme.io", "password": "short", "accept": True})
check(r.status_code == 400, "короткий пароль — 400")
r = c.post("/api/auth/register", json={"email": "boss@acme.io", "password": "long-enough-1",
                                       "org": "ACME", "name": "Босс"})
check(r.status_code == 400, "без согласия с офертой регистрации нет")
r = c.post("/api/auth/register", json={"email": "boss@acme.io", "password": "long-enough-1",
                                       "org": "ACME", "name": "Босс", "accept": True})
j = r.json()
check(r.status_code == 200 and j["next"] == "verify" and j["mailSent"] is False,
      "регистрация принята, письмо честно не отправлено")
tid = j["tenant"]
u = main._user_by_email("boss@acme.io")
check(u and u["role"] == "owner" and not u.get("super") and not u["emailVerified"],
      "владелец своей организации, не super, почта не подтверждена")
acc = u.get("acceptedTerms") or {}
check(acc.get("version") and acc.get("at") and acc.get("ip"),
      "согласие зафиксировано: редакция, дата, адрес — %s" % acc)
t = main._tenant_rec(tid)
check(t and t["limitUsd"] == 0.0 and t.get("signup"), "новой организации выставлен лимит 0 — платное закрыто")
r = c.post("/api/auth/register", json={"email": "BOSS@acme.io", "password": "another-pass-1", "accept": True})
check(r.status_code == 409, "повтор почты (в другом регистре) — 409")

print("=== 2. Вход до подтверждения и код ===")
r = c.post("/api/auth/login", json={"login": "boss@acme.io", "password": "long-enough-1"})
check(r.status_code == 403 and "подтвержд" in r.json().get("detail", ""), "без подтверждения — 403 с объяснением")
r = c.post("/api/auth/verify", json={"email": "boss@acme.io", "code": "000000"})
check(r.status_code in (400, 429), "неверный код не пускает")
good = code_of("boss@acme.io")
r = c.post("/api/auth/verify", json={"email": "boss@acme.io", "code": good})
check(r.status_code == 200 and r.json().get("token"), "верный код: подтверждено и сразу вход")
B = r.json()["token"]
check(main._user_by_email("boss@acme.io").get("authCode") is None, "код погашен после использования")
r = c.post("/api/auth/login", json={"login": "boss@acme.io", "password": "long-enough-1"})
check(r.status_code == 200, "теперь вход по почте работает")

print("=== 3. Подбор кода закрыт потолком попыток ===")
u = main._user_by_email("boss@acme.io")
main._issue_code(u, "verify")
u["emailVerified"] = False
codes = [c.post("/api/auth/verify", json={"email": "boss@acme.io", "code": "111111"}).status_code
         for _ in range(main.CODE_MAX_TRIES + 1)]
check(codes[-1] == 429, "после %d попыток — 429, а не бесконечный перебор" % main.CODE_MAX_TRIES)
u["emailVerified"] = True
u.pop("authCode", None)

print("=== 4. Изоляция новой организации ===")
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
pid = c.post("/api/projects", headers=H(A), json={"title": "чужой", "src": "RU", "tgt": "EN"}).json()["id"]
check(c.get("/api/projects/%d" % pid, headers=H(B)).status_code == 404, "чужой проект новичку — 404")
check(c.get("/api/projects", headers=H(B)).json() == [], "своих проектов пока нет")
check(c.get("/api/admin/overview", headers=H(B)).status_code == 403, "админка сервиса ему закрыта")
check(c.get("/api/projects/%d/analysis" % pid, headers=H(B)).status_code == 404,
      "и бесплатная команда по чужому проекту — 404 (именно изоляция)")
r = c.post("/api/projects/%d/jobs" % pid, headers=H(B), json={"kind": "full", "ids": [1]})
# Лимит проверяется в мидлвари, то есть РАНЬШЕ обработчика: на платном пути
# новичок с лимитом 0 получит 402 прежде, чем дело дойдёт до чужого проекта.
# Про существование проекта это не говорит ничего — 402 одинаков и для
# несуществующего номера, — а прогон всё равно не ставится.
check(r.status_code in (402, 404), "прогон по чужому проекту не ставится (%d)" % r.status_code)
own = c.post("/api/projects", headers=H(B), json={"title": "свой", "src": "RU", "tgt": "EN"}).json()["id"]
r = c.post("/api/segments/%d/1/translate" % own, headers=H(B), json={})
check(r.status_code == 402 and "spend" in r.json(), "платное на лимите 0 — 402 с остатком, а не трата нашего ключа")
check(c.post("/api/projects/9999999/jobs", headers=H(B), json={"kind": "full", "ids": [1]}).status_code == 402,
      "тот же 402 на НЕсуществующем проекте — ответ не выдаёт, есть проект или нет")
r = c.get("/api/projects/%d/analysis" % own, headers=H(B))
check(r.status_code != 402, "бесплатное работает")
main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] not in (pid, own)]

print("=== 5. Восстановление пароля ===")
r = c.post("/api/auth/forgot", json={"email": "boss@acme.io"})
check(r.status_code == 200 and r.json()["ok"], "запрос принят")
r2 = c.post("/api/auth/forgot", json={"email": "nobody@nowhere.io"})
check(r2.status_code == 200 and r2.json() == r.json(),
      "ответ одинаков для существующей и несуществующей почты")
rc = code_of("boss@acme.io")
r = c.post("/api/auth/reset", json={"email": "boss@acme.io", "code": rc, "password": "brand-new-pass-9"})
check(r.status_code == 200 and r.json().get("token"), "пароль сменён, выдан токен")
check(c.get("/api/auth/me", headers=H(B)).status_code == 401, "прежние сессии закрыты")
check(c.post("/api/auth/login", json={"login": "boss@acme.io", "password": "brand-new-pass-9"}).status_code == 200,
      "вход новым паролем")
check(c.post("/api/auth/login", json={"login": "boss@acme.io", "password": "long-enough-1"}).status_code == 401,
      "старый пароль больше не годится")

print("=== 6. Регистрацию можно закрыть, IP ограничен ===")
main.SIGNUP_ENABLED = False
check(c.post("/api/auth/register", json={"email": "x@y.zz", "password": "long-enough-1", "accept": True}).status_code == 403,
      "SIGNUP_ENABLED=0 — 403")
main.SIGNUP_ENABLED = True
main._SIGNUP_FAILS.clear()
codes = [c.post("/api/auth/register", json={"email": "u%d@acme.io" % i, "password": "long-enough-1", "accept": True}).status_code
         for i in range(main.SIGNUP_MAX_PER_HOUR + 1)]
check(codes[-1] == 429, "потолок регистраций с одного адреса: %s" % codes)

print("=== 7. Владелец заводит переводчика с почтой ===")
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
r = c.post("/api/admin/users", headers=H(A), json={"login": "petrov", "password": "petrov-pass-1",
                                                   "email": "petrov@acme.io"})
check(r.status_code == 200 and r.json()["user"]["emailVerified"],
      "заведённому владельцем подтверждать почту не нужно")
check(c.post("/api/auth/login", json={"login": "petrov@acme.io", "password": "petrov-pass-1"}).status_code == 200,
      "он входит и по почте, и по логину")
r = c.post("/api/admin/users", headers=H(A), json={"login": "dup", "password": "dup-pass-12",
                                                   "email": "petrov@acme.io"})
check(r.status_code == 409, "занятая почта — 409")

print()
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail))
