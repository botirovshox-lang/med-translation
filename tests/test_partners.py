# -*- coding: utf-8 -*-
"""Партнёры: внешний сайт приводит клиентов, ему причитается процент деньгами.

Сторожится то, где можно посчитать не тому или не столько:

  1. Ссылка `/r/КОД` — метка, а не дверь: ведёт на регистрацию или лендинг,
     ставит cookie, считает переход (повтор с той же сети за час — нет).
  2. Регистрация закрепляет клиента за партнёром и по cookie, и по `?ref=`;
     код из тела (последний переход в приложении) сильнее cookie.
  3. Комиссия — с ОПЛАЧЕННЫХ заказов, процентом, действовавшим в ДЕНЬ оплаты.
  4. Выплаты — руками: «выплачено» уменьшает долг, «к выплате» — нет.
  5. Только суперпользователю; ключ `partners` не уходит в `/api/seed`.
  6. Отключённому партнёру новых клиентов не засчитываем; удалить партнёра
     с клиентами нельзя; удалённая организация остаётся в отчёте.
Ни одного вызова модели, файл состояния не пишется.
"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="mct-partner-"))
os.environ["APP_PASSWORD"] = "test-partner-password"
os.environ["SIGNUP_ENABLED"] = "1"
os.environ["PAY_ORDERS_FILE"] = str(TMP / "pay_orders.json")
os.environ["PUBLIC_BASE_URL"] = "https://simpletranslate.me"
sys.path.insert(0, "backend")
sys.path.insert(0, ".")
import main                                              # noqa: E402
from starlette.testclient import TestClient              # noqa: E402

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["partners"] = []
main._SESSIONS.clear()
main._LOGIN_FAILS.clear()
main._SIGNUP_FAILS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app, base_url="https://simpletranslate.me")
H = lambda t: {"Authorization": "Bearer " + t}           # noqa: E731


def mkuser(login, tenant, role="owner", super=False):
    h, salt = main._hash_password("password-123")
    u = {"id": max((x["id"] for x in main._users()), default=0) + 1, "tenant": tenant,
         "login": login, "email": login + "@example.com", "emailVerified": True,
         "hash": h, "salt": salt, "role": role, "super": super, "name": login,
         "active": True, "uiLang": main.DEFAULT_UI_LANG, "created": "2026-01-01"}
    main._users().append(u)
    if not main._tenant_rec(tenant):
        main._tenants().append({"id": tenant, "name": tenant.upper(), "active": True,
                                "created": "2026-01-01"})
    return u


def login(name):
    r = c.post("/api/auth/login", json={"login": name, "password": "password-123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def paid_order(oid, tid, usd, day):
    main._pays().pay_put({"id": oid, "tenant": tid, "status": "paid", "usd": str(usd),
                          "paidAt": day + " 12:00:00", "pages": 10, "minutes": 0,
                          "amount": "1000", "currency": "UZS", "method": "click"})


mkuser("owner", "acme")
mkuser("root", "sys", super=True)
owner_t, root_t = login("owner"), login("root")

print("=== 1. Только суперпользователю ===")
check(c.get("/api/admin/partners", headers=H(owner_t)).status_code == 403, "владельцу — 403")
check(c.post("/api/admin/partners", json={"name": "x"}, headers=H(owner_t)).status_code == 403,
      "создать партнёра владелец не может")

print("=== 2. Заведение и ссылка ===")
r = c.post("/api/admin/partners", json={"name": "Сайт Ивана", "percent": 10, "target": "app"},
           headers=H(root_t))
check(r.status_code == 200, "партнёр заведён: " + r.text[:100])
P = r.json()
code, pid = P["code"], P["id"]
check(P["link"] == "https://simpletranslate.me/r/" + code, "ссылка вида /r/КОД: " + P["link"])
check(code not in {t.get("refCode") for t in main._tenants()}, "код не совпал с кодом приглашения")
check(c.post("/api/admin/partners", json={"name": "y", "percent": 150},
             headers=H(root_t)).status_code == 400, "процент больше 100 — 400")

print("=== 3. Переход по ссылке ===")
main._PARTNER_SEEN.clear()
r = c.get("/r/" + code + "?utm_source=blog&evil=1", follow_redirects=False)
check(r.status_code == 302, "ссылка — перенаправление")
loc = r.headers.get("location", "")
check(loc.startswith("/?ref=" + code), "ведёт на регистрацию с меткой: " + loc)
check("utm_source=blog" in loc and "evil" not in loc, "utm доезжают, чужие параметры — нет")
check(main.partners_mod.COOKIE + "=" + code in r.headers.get("set-cookie", ""), "cookie поставлена")
c.get("/r/" + code, follow_redirects=False)
main._metrics_flush(force=True)
clicks = main._partner_clicks("2000-01-01", "2100-01-01")
check(clicks.get(pid) == 1, "повтор с той же сети за час не считается: " + str(clicks))
r = c.get("/r/ZZZZZZZZ", follow_redirects=False)
check(r.status_code == 302 and r.headers["location"] == "/" and "set-cookie" not in r.headers,
      "неизвестный код — на главную без метки")
c.post("/api/admin/partners/%d" % pid, json={"target": "landing", "lang": "uz"}, headers=H(root_t))
r = c.get("/r/" + code, follow_redirects=False)
check(r.headers["location"].startswith(main.LANDING_ORIGINS[0] + "/uz/?ref=" + code),
      "на лендинг нужного языка: " + r.headers["location"])

print("=== 4. Регистрация закрепляет клиента ===")
c.cookies.clear()
c.cookies.set(main.partners_mod.COOKIE, code)
r = c.post("/api/auth/register", json={"email": "cl1@example.com", "password": "password-123",
                                       "org": "Клиент 1", "accept": True})
check(r.status_code == 200, "регистрация по cookie: " + r.text[:100])
t1 = r.json()["tenant"]
check(main._tenant_rec(t1).get("partner") == pid, "клиент закреплён за партнёром по cookie")
check(not main._tenant_rec(t1).get("refBy"), "меткой приглашения он не стал")
c.cookies.clear()
main._SIGNUP_FAILS.clear()
r = c.post("/api/auth/register", json={"email": "cl2@example.com", "password": "password-123",
                                       "org": "Клиент 2", "accept": True, "ref": code})
t2 = r.json()["tenant"]
check(main._tenant_rec(t2).get("partner") == pid, "клиент закреплён по ?ref= в теле")
# Тело сильнее cookie: последний переход — по ссылке-приглашению организации.
main._SIGNUP_FAILS.clear()
org_code = main._ref_code_of("acme")
c.cookies.set(main.partners_mod.COOKIE, code)
r = c.post("/api/auth/register", json={"email": "cl3@example.com", "password": "password-123",
                                       "org": "Клиент 3", "accept": True, "ref": org_code})
t3 = r.json()["tenant"]
check(main._tenant_rec(t3).get("partner") is None and main._tenant_rec(t3).get("refBy") == org_code,
      "последний переход (код в теле) сильнее cookie партнёра без времени")
c.cookies.clear()
# А свежий переход партнёра (ссылка вела на лендинг — localStorage приложения
# хранит СТАРЫЙ код) сильнее старого кода в теле: засчитывается последний.
import time as _t  # noqa: E402
main._SIGNUP_FAILS.clear()
c.cookies.set(main.partners_mod.COOKIE, "%s.%d" % (code, int(_t.time())))
r = c.post("/api/auth/register", json={"email": "cl5@example.com", "password": "password-123",
                                       "org": "Клиент 5", "accept": True, "ref": org_code,
                                       "refAt": (_t.time() - 86400) * 1000})
t5 = r.json()["tenant"]
check(main._tenant_rec(t5).get("partner") == pid and not main._tenant_rec(t5).get("refBy"),
      "свежая ссылка партнёра сильнее старого кода приглашения в теле")
check(main.partners_mod.COOKIE + '=""' in r.headers.get("set-cookie", "")
      or "Max-Age=0" in r.headers.get("set-cookie", ""), "метка снята после регистрации (общий компьютер)")
c.cookies.clear()
main._tenant_rec(t5).pop("partner")       # дальше считаем двоих клиентов, как прежде

print("=== 5. Комиссия с оплат, процент дня оплаты ===")
p = main._partner_by_id(pid)
p["percentLog"] = [{"from": "2026-01-01", "percent": 10.0}, {"from": "2026-06-01", "percent": 20.0}]
p["percent"] = 20.0
main._tenant_rec(t1)["partnerAt"] = "2026-01-01"
paid_order(5001, t1, "100", "2026-03-10")       # 10% → 10
paid_order(5002, t1, "50", "2026-07-01")        # 20% → 10
paid_order(5003, t2, "30", "2025-12-01")        # до того, как стал клиентом — не считается
main._pays().pay_put({"id": 5004, "tenant": t1, "status": "new", "usd": "999"})
main._tenant_rec(t2)["partnerAt"] = "2026-01-01"
r = c.get("/api/admin/partners", headers=H(root_t)).json()
row = next(x for x in r["partners"] if x["id"] == pid)
check(row["life"] == {"orders": 2, "usd": 150.0, "commission": 20.0},
      "считаются только оплаченные и процентом своего дня: " + str(row["life"]))
check(row["paying"] == 1 and row["clientsTotal"] == 2, "платящих 1 из 2 клиентов")
r = c.get("/api/admin/partners?from=2026-07-01&to=2026-07-31", headers=H(root_t)).json()
row = next(x for x in r["partners"] if x["id"] == pid)
check(row["period"] == {"orders": 1, "usd": 50.0, "commission": 10.0}, "период: " + str(row["period"]))
check(row["life"]["commission"] == 20.0, "вся жизнь видна и при выбранном периоде")

print("=== 6. Выплаты — руками ===")
r = c.post("/api/admin/partners/%d/payouts" % pid, json={"amount": 12.5, "paid": True, "note": "за март"},
           headers=H(root_t))
check(r.status_code == 200, "выплата записана")
xid = r.json()["payout"]["id"]
c.post("/api/admin/partners/%d/payouts" % pid, json={"amount": 5, "paid": False}, headers=H(root_t))
row = next(x for x in c.get("/api/admin/partners", headers=H(root_t)).json()["partners"] if x["id"] == pid)
check(row["paidOut"] == 12.5 and row["planned"] == 5.0 and row["owed"] == 7.5,
      "выплачено 12.5, к выплате 5, долг 7.5: " + str((row["paidOut"], row["planned"], row["owed"])))
check(c.post("/api/admin/partners/%d/payouts" % pid, json={"amount": 0},
             headers=H(root_t)).status_code == 400, "нулевая выплата — 400")
c.post("/api/admin/partners/%d/payouts/%d" % (pid, xid), json={"paid": False}, headers=H(root_t))
row = next(x for x in c.get("/api/admin/partners", headers=H(root_t)).json()["partners"] if x["id"] == pid)
check(row["paidOut"] == 0.0 and row["owed"] == 20.0, "снятая отметка «выплачено» возвращает долг")

print("=== 7. Отключение, удаление, ручная привязка ===")
check(c.delete("/api/admin/partners/%d" % pid, headers=H(root_t)).status_code == 409,
      "партнёра с клиентами не удалить")
c.post("/api/admin/partners/%d" % pid, json={"active": False}, headers=H(root_t))
main._SIGNUP_FAILS.clear()
r = c.post("/api/auth/register", json={"email": "cl4@example.com", "password": "password-123",
                                       "org": "Клиент 4", "accept": True, "ref": code})
t4 = r.json()["tenant"]
check(main._tenant_rec(t4).get("partner") is None, "отключённому новых клиентов не засчитываем")
paid_order(5005, t4, "40", "2026-02-01")      # до привязки руками
r = c.post("/api/admin/partners/%d/clients" % pid, json={"tenant": t4}, headers=H(root_t))
check(r.status_code == 200 and main._tenant_rec(t4).get("partnerVia") == "admin", "привязка руками")
row = next(x for x in c.get("/api/admin/partners", headers=H(root_t)).json()["partners"] if x["id"] == pid)
check(row["life"]["usd"] == 150.0, "привязка руками не задним числом: прошлые оплаты не считаются")
c.post("/api/admin/partners/%d/clients" % pid, json={"tenant": t4, "attach": False}, headers=H(root_t))
check(main._tenant_rec(t4).get("partner") is None, "отвязка")
check(any(g["tenant"] == t4 and g["why"] == "detached" for g in main._partner_by_id(pid)["gone"]),
      "отвязка оставляет у партнёра запись прошлого")

# Перенос клиента к другому партнёру — только явно, прошлое остаётся прежнему.
r2 = c.post("/api/admin/partners", json={"name": "Блог Б", "percent": 5}, headers=H(root_t)).json()
pid2 = r2["id"]
check(c.post("/api/admin/partners/%d/clients" % pid2, json={"tenant": t2},
             headers=H(root_t)).status_code == 409, "клиента другого партнёра без «перенести» не забрать")
paid_order(5006, t2, "20", "2026-08-01")      # оплата ещё у прежнего партнёра
r = c.post("/api/admin/partners/%d/clients" % pid2, json={"tenant": t2, "move": True}, headers=H(root_t))
check(r.status_code == 200 and main._tenant_rec(t2).get("partner") == pid2, "перенос с подтверждением")
paid_order(5007, t2, "10", "2099-01-01")      # оплата уже у нового
rows = {x["id"]: x for x in c.get("/api/admin/partners", headers=H(root_t)).json()["partners"]}
check(rows[pid]["life"]["usd"] == 170.0, "прошлая оплата осталась прежнему партнёру: " + str(rows[pid]["life"]))
check(rows[pid2]["life"]["usd"] == 10.0, "новому — только новая: " + str(rows[pid2]["life"]))

r = c.delete("/api/admin/tenants/" + t1, headers=H(root_t))
row = next(x for x in c.get("/api/admin/partners", headers=H(root_t)).json()["partners"] if x["id"] == pid)
check(row["life"]["usd"] == 170.0 and any(cl["gone"] and cl["why"] == "deleted" for cl in row["clients"]),
      "удалённая организация осталась в отчёте вместе с оплатами (удаление: %d)" % r.status_code)
# Номер организации переиспользуется: новая жизнь того же номера у того же
# партнёра в тот же день не удваивает прежние оплаты и не теряет новые.
main._tenants().append({"id": t1, "name": "Новая жизнь", "active": True, "created": "2026-10-19",
                        "partner": pid, "partnerAt": "2026-01-01", "partnerVia": "link"})
paid_order(5008, t1, "7", "2026-07-01")
row = next(x for x in c.get("/api/admin/partners", headers=H(root_t)).json()["partners"] if x["id"] == pid)
check(row["life"]["usd"] == 177.0, "водораздел делит жизни одного номера без двойного счёта: " + str(row["life"]))
main._tenants().remove(main._tenant_rec(t1))

# Настоящий ответ двери — образец для рендер-теста вкладки (test_admin_render.js):
# заглушка своей формы прятала бы поломки формы (урок «Роли и доступы»).
import json  # noqa: E402
snap = c.get("/api/admin/partners", headers=H(root_t)).json()
Path("tests/fixtures").mkdir(exist_ok=True)
# Код и сегодняшняя дата — случайные, в образце они постоянные: файл в git
# не должен меняться от каждого прогона.
_txt = json.dumps(snap, ensure_ascii=False, indent=1).replace(code, "PARTNER1")
_txt = _txt.replace(main._biz_day(), "2026-10-19")
import re  # noqa: E402
_txt = _txt.replace(r2["code"], "PARTNER2")
_txt = re.sub(r'"(\w+)": "\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"', lambda m: '"%s": "2026-10-19 12:00:00"' % m.group(1), _txt)
_txt = re.sub(r'"clicksFrom": "[^"]*"', '"clicksFrom": "2026-07-21"', _txt)
Path("tests/fixtures/partners_payload.json").write_text(_txt + chr(10), encoding="utf-8")

print("=== 8. Ключ не уходит наружу ===")
seed = c.get("/api/seed", headers=H(owner_t)).json()
check("partners" not in seed, "partners нет в /api/seed")
me = c.get("/api/auth/me", headers=H(owner_t)).text
check("partner" not in me, "поля партнёра не текут в /api/auth/me")

print()
if fail:
    print("НЕ ПРОШЛО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
