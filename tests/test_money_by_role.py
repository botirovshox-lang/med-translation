# -*- coding: utf-8 -*-
"""Деньги и цены — ВЛАДЕЛЬЦУ, а не каждому вошедшему.

Правило одно и простое: **деньги видит только администратор сервиса**
(суперпользователь). Ни переводчик, ни редактор, ни владелец организации.

Сперва рубеж стоял на роли владельца («он платит — ему и число»), и это
оказалось неверно: за модели платит не агентство, а сервис, и наш расход
владельцу не нужен ни для одной задачи. Цена страницы — та, что агентство
берёт со своего клиента, — на экране сервиса тоже больше не живёт.

`simple` НА ОРГАНИЗАЦИИ (tests/test_simple_mode.py) остаётся и работает
ВНУТРИ этого правила — он прячет суммы и от самого супера.

Что сторожится и почему именно это:

  1. Рубеж стоит на СЕРВЕРЕ. Спрятанное только показом (`costHidden` в .jsx)
     уезжает в ответе и видно в любой вкладке «Сеть» — тот же закон, что
     у `needs_judge` и `repair.acceptable`.
  2. Роль читается из СЕССИИ (инвариант 18): владелец своей команды в чужой
     бывает переводчиком, и там сумм он видеть не должен.
  3. Объём РАБОТЫ остаётся: слова, знаки, страницы, норма, состав шага.
     Переводчику они нужны, и это не деньги.
  4. Суперпользователь исключён: деньги сервиса — его работа.
  5. Владельца правка не задевает ни в чём.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys, json
os.environ["APP_PASSWORD"] = "test-money-role-pw"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["runCosts"] = []
main.STATE["quotes"] = []
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
S = c.post("/api/auth/login", json={"login": "admin", "password": "test-money-role-pw"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "bureau", "name": "Бюро", "ownerLogin": "boss", "ownerPassword": "boss-pass-123"})
OWN = c.post("/api/auth/login", json={"login": "boss", "password": "boss-pass-123"}).json()["token"]
# Переводчик и редактор — в ТОЙ ЖЕ организации: рубеж по роли, а не по тенанту.
for login, role in (("tr", "translator"), ("ed", "editor")):
    c.post("/api/admin/users", headers=H(OWN),
           json={"login": login, "password": login + "-pass-123", "name": login, "role": role})
TR_ = c.post("/api/auth/login", json={"login": "tr", "password": "tr-pass-123"}).json()["token"]
ED = c.post("/api/auth/login", json={"login": "ed", "password": "ed-pass-123"}).json()["token"]

# Прайс организации ставит владелец — его и будем прятать от остальных.
c.post("/api/pricing", headers=H(OWN), json={"currency": "USD", "default": 12.5})

print("=== 1. Владелец организации денег НЕ видит ===")
me = c.get("/api/auth/me", headers=H(OWN)).json()
check(me["hideCost"] is True, "владелец: суммы не показываются")
check("spentUsd" not in me["spend"], "расхода в /auth/me нет")
check(me["spend"].get("over") is False,
      "но факт «лимит исчерпан» остаётся — иначе кнопки гаснут молча")
pr = c.get("/api/pricing", headers=H(OWN)).json()
check(pr.get("pricing") is None and pr.get("costHidden") is True,
      "цена страницы не показывается и владельцу")
check(bool(pr.get("norms")), "норма страницы остаётся: это объём работы, а не деньги")
# Править прайс владелец по-прежнему ВПРАВЕ (_OWNER_ONLY): скрыт ПОКАЗ,
# а не право.
check(c.post("/api/pricing", headers=H(OWN), json={"default": 13.0}).status_code == 200,
      "право править прайс у владельца осталось — скрыт показ, а не право")

print("\n=== 2. Переводчику и редактору — тем более ===")
for tok, who in ((TR_, "переводчик"), (ED, "редактор")):
    me = c.get("/api/auth/me", headers=H(tok)).json()
    check(me["hideCost"] is True, who + ": /auth/me велит прятать суммы")
    check("spentUsd" not in me["spend"], who + ": суммы расхода в ответе НЕТ")
    check(me["spend"].get("over") is False,
          who + ": но факт «лимит исчерпан» остаётся — иначе кнопки гаснут молча")
    check(c.get("/api/models", headers=H(tok)).json()["hideCost"] is True,
          who + ": каталог велит прятать суммы")
    u = c.get("/api/usage", headers=H(tok)).json()
    check(u.get("hidden") is True and not u["runs"], who + ": экран расхода скрыт")

print("\n=== 3. Цена за страницу — только администратору сервиса ===")
for tok, who in ((TR_, "переводчик"), (ED, "редактор")):
    r = c.get("/api/pricing", headers=H(tok)).json()
    check(r.get("pricing") is None and r.get("costHidden") is True,
          who + ": прайса в ответе нет: " + json.dumps(r.get("pricing"), ensure_ascii=False))
    check("12.5" not in json.dumps(r, ensure_ascii=False),
          who + ": цены нет нигде в теле ответа")
    # Норма страницы деньгами не является: по ней человек видит ОБЪЁМ работы.
    check(bool(r.get("norms") and r["norms"].get("rows")), who + ": норма страницы осталась")

print("\n=== 4. История смет — деньги целиком ===")
main.STATE["quotes"] = [{"id": 1, "tenant": "bureau", "file": "kniga.docx", "at": "2026-09-23",
                         "src": "RU", "tgt": "EN", "words": 1000, "pagesBilled": 4,
                         "pricePerPage": 12.5, "total": 50.0, "currency": "USD", "status": "new"}]
# Супер смотрит из СВОЕЙ организации (инвариант 11): чужие сметы ему
# по-прежнему не видны, и это правильно. Проверяем на смете его же
# организации — вопрос здесь про ДЕНЬГИ, а не про изоляцию.
main.STATE["quotes"].append({"id": 2, "tenant": "default", "file": "own.docx",
                             "at": "2026-09-23", "src": "RU", "tgt": "EN", "words": 100,
                             "pagesBilled": 1, "pricePerPage": 7.0, "total": 7.0,
                             "currency": "USD", "status": "new"})
q = c.get("/api/quotes", headers=H(S)).json()
check(len(q["quotes"]) == 1 and q["quotes"][0]["total"] == 7.0,
      "администратор сервиса историю смет видит: " + json.dumps(q["quotes"], ensure_ascii=False)[:90])
for tok, who in ((OWN, "владелец"), (TR_, "переводчик"), (ED, "редактор")):
    q = c.get("/api/quotes", headers=H(tok)).json()
    check(q["quotes"] == [] and q.get("costHidden") is True, who + ": истории смет нет")
    seed = c.get("/api/seed", headers=H(tok)).json()
    check(seed.get("quotes") == [], who + ": и в начальной выдаче её тоже нет")
    check("50.0" not in json.dumps(seed.get("quotes"), ensure_ascii=False),
          who + ": сумм в /seed не осталось")

print("\n=== 5. Объём работы остаётся, деньги уходят ===")
tok_ctx = main.CURRENT_SESSION.set(main._SESSIONS[TR_])
try:
    counts = {"words": 1000, "chars": 6000, "charsNoSpaces": 5000,
              "repeatBlocks": 0, "repeatChars": 0}
    q = main._quote_of(counts, "RU", "EN", main._pricing_of(), "file")
finally:
    main.CURRENT_SESSION.reset(tok_ctx)
check(q["counts"]["words"] == 1000, "слова в смете остались")
check(bool(q["pages"]["billed"]), "страницы остались: " + str(q["pages"]["billed"]))
check(bool(q["norm"]["perPage"]), "норма осталась")
check(q["total"] is None and q["rate"] is None and q["formula"] is None,
      "а цена, итог и формула — сняты")
check(q.get("costHidden") is True, "и экран знает, что это не «цена не задана», а «не показываем»")

print("\n=== 6. Роль берётся из СЕССИИ, а не с записи (инвариант 18) ===")
# Владелец «Бюро» — переводчик в чужой команде. Суммы там ему не показывают.
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "other", "name": "Чужие", "ownerLogin": "other-boss", "ownerPassword": "other-pass-123"})
u_boss = next(u for u in main.STATE["users"] if u["login"] == "boss")
u_boss.setdefault("memberships", []).append({"tenant": "other", "role": "translator", "since": "2026-09-23"})
r = c.post("/api/profile/team", headers=H(OWN), json={"tenant": "other"})
check(r.status_code == 200 and r.json()["activeRole"] == "translator",
      "переключился в чужую команду переводчиком")
check(c.get("/api/auth/me", headers=H(OWN)).json()["hideCost"] is True,
      "в чужой команде сумм не видит")
c.post("/api/profile/team", headers=H(OWN), json={"tenant": "bureau"})
check(c.get("/api/auth/me", headers=H(OWN)).json()["hideCost"] is True,
      "и дома тоже: деньги видит только администратор сервиса")

print("\n=== 7. Суперпользователю деньги сервиса нужны ===")
check(c.get("/api/auth/me", headers=H(S)).json()["hideCost"] is False, "супер видит суммы")

print("\n=== 8. Предикат отвечает «прятать» переводчику ===")
tok_ctx = main.CURRENT_SESSION.set(main._SESSIONS[TR_])
try:
    hidden = main._hide_cost()
finally:
    main.CURRENT_SESSION.reset(tok_ctx)
check(hidden is True, "_hide_cost() для переводчика — True")

print("\nВСЁ ПРОШЛО" if not fail else "\nПРОВАЛЕНО: %d\n  - %s" % (len(fail), "\n  - ".join(fail)))
sys.exit(1 if fail else 0)
