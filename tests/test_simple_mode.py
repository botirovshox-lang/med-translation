# -*- coding: utf-8 -*-
"""Упрощённый режим организации: ни денег, ни имён моделей.

Флаг `simple` стоит НА ОРГАНИЗАЦИИ, а не на человеке: скрывать надо и от
того, кого владелец позовёт себе в помощь. Заведён он для тест-группы, но по
существу это «переводчику показывают перевод, а не бухгалтерию».

Две разные вещи, и путать их нельзя:
  ПОКАЗ  — суммы и имена моделей не отдаются;
  РАБОТА — модели шагов назначает ОРГАНИЗАЦИЯ, а не браузер: полей выбора
           на экране нет, но выбор, оставшийся в localStorage от прежнего
           входа, всё равно уехал бы в задачу.

Что сторожится и почему именно это:

  1. Смета продолжает СЧИТАТЬСЯ и уходить на сервер. На ней стоят отказ по
     смете на старте прогона и калибровка поправки `estRatio`; убери расчёт —
     тихо исчезли бы оба, а на экране ничего бы не изменилось. Поэтому цены
     в каталоге остаются, а прячется ПОКАЗ (флаг `hideCost`).
  2. Утечки денег перечислены поимённо, потому что их пять и они в разных
     местах: каталог моделей, статус задачи (браузер опрашивает его каждые
     несколько секунд, а `job["usage"]` несёт и сумму, и разбивку ПО МОДЕЛЯМ),
     начальная выдача (`runCosts`), экран расхода и тексты отказа 402.
  3. Разбор состава и постановка задачи подставляют ОДНИ И ТЕ ЖЕ модели.
     Разойдись они — смета под кнопкой перестала бы описывать работу, а это
     ровно та беда, ради которой состав вообще считает сервер.
  4. Отказ 402 в упрощённом режиме не называет сумм, но говорит, что лимит
     исчерпан: молчаливо погасшие кнопки выглядят поломкой сервиса.
  5. Обычную организацию режим не задевает ни в чём.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys, json
os.environ["APP_PASSWORD"] = "test-simple-password"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["runCosts"] = []
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
S = c.post("/api/auth/login", json={"login": "admin", "password": "test-simple-password"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "trial", "name": "Тест", "ownerLogin": "trial", "ownerPassword": "trial-pass-123"})
T = c.post("/api/auth/login", json={"login": "trial", "password": "trial-pass-123"}).json()["token"]

print("=== 1. Пока режим не включён — всё как было ===")
cat = c.get("/api/models", headers=H(T)).json()
check(cat["hideCost"] is False, "обычная организация: суммы показываются")
check(all("in" in m for m in cat["models"]), "цены в каталоге есть")

print("\n=== 2. Включает и настраивает СУПЕРПОЛЬЗОВАТЕЛЬ ===")
check(c.post("/api/admin/tenants/trial", headers=H(T), json={"simple": True}).status_code == 403,
      "владелец сам себе режим не ставит")
r = c.post("/api/admin/tenants/trial", headers=H(S),
           json={"simple": True, "models": {"backcheck": "gpt-4o-mini", "repair": "gpt-5.6-luna"}})
check(r.status_code == 200 and main._tenant_rec("trial")["simple"] is True, "режим включён")
bad = c.post("/api/admin/tenants/trial", headers=H(S), json={"models": {"repair": "выдуманная"}})
check(bad.status_code == 400, "несуществующая модель отвергнута ДО записи: " + bad.text[:70])
check(main._tenant_rec("trial")["models"]["repair"] == "gpt-5.6-luna", "и запись не тронута")
check(c.post("/api/admin/tenants/trial", headers=H(S),
             json={"models": {"выдуманный-шаг": "gpt-4o"}}).status_code == 400,
      "несуществующий шаг отвергнут")

print("\n=== 3. Суммы не отдаются ни одним путём ===")
cat = c.get("/api/models", headers=H(T)).json()
check(cat["hideCost"] is True, "каталог говорит браузеру прятать суммы")
check(all("in" in m for m in cat["models"]),
      "но ЦЕНЫ остаются: по ним считается смета, на которой стоит отказ 402 и estRatio")
me = c.get("/api/auth/me", headers=H(T)).json()
check(me["hideCost"] is True and "spentUsd" not in me["spend"],
      "в /auth/me сумм нет: " + json.dumps(me["spend"], ensure_ascii=False))
check(me["spend"]["over"] is False, "но факт «лимит исчерпан» остаётся — иначе кнопки гаснут молча")
usage = c.get("/api/usage", headers=H(T)).json()
check(usage.get("hidden") is True and not usage["runs"], "экран расхода скрыт целиком")
main.STATE["runCosts"] = [{"job": 1, "kind": "full", "tenant": "trial", "cost": 1.5, "est": 1.0,
                           "calls": 5, "finished": "2026-09-07 10:00"}]
check(c.get("/api/seed", headers=H(T)).json()["runCosts"] == [],
      "история расхода в начальной выдаче пуста")
job = {"id": 1, "kind": "full", "project": 1, "status": "running", "tenant": "trial",
       "usage": {"cost": 0.42, "calls": 7, "models": {"gpt-4o": 3}, "in": 10, "out": 5},
       "ids": [1], "stop": False}
tok = main.CURRENT_SESSION.set(main._SESSIONS[T])
try:
    pub = main._job_public(job)
finally:
    main.CURRENT_SESSION.reset(tok)
check("cost" not in pub["usage"] and "models" not in pub["usage"],
      "статус задачи не несёт ни суммы, ни разбивки по моделям: " + str(sorted(pub["usage"])))
check(pub["usage"]["calls"] == 7, "число вызовов при этом остаётся — это не деньги")

print("\n=== 4. Модели назначает организация, а не браузер ===")
tok = main.CURRENT_SESSION.set(main._SESSIONS[T])
try:
    got = main._forced_models({"bc_model": "gpt-5.6-sol", "rp_model": "gpt-5.6-sol",
                               "model": "gpt-5.6-sol", "use_judge": True})
finally:
    main.CURRENT_SESSION.reset(tok)
check(got["bc_model"] == "gpt-4o-mini", "выбор браузера заменён назначенным: " + str(got["bc_model"]))
check(got["rp_model"] == "gpt-5.6-luna", "и у ремонта тоже")
check(got["model"] is None, "шаг без назначения идёт моделью сервера по умолчанию, а не выбором браузера")
check(got["use_judge"] is True, "остальные параметры не тронуты")
check(set(got) >= set(main.FULL_STEP_MODEL.values()),
      "назначение накрывает КАЖДЫЙ шаг: пропущенный уехал бы с выбором браузера")

tok = main.CURRENT_SESSION.set(main._SESSIONS[S])
try:
    same = main._forced_models({"bc_model": "gpt-5.6-sol"})
finally:
    main.CURRENT_SESSION.reset(tok)
check(same["bc_model"] == "gpt-5.6-sol", "обычной организации выбор оставлен как есть")

print("\n=== 5. Отказ по лимиту говорит по существу, но без сумм ===")
main.STATE["tenants"] = [t for t in main.STATE["tenants"]]
main._tenant_rec("trial")["limitUsd"] = 0.0
main.STATE.setdefault("spend", {}).setdefault("trial", {})[main._month_key()] = {
    "usd": 5.0, "calls": 1, "unpriced": 0}
r = c.post("/api/projects/1/batch", headers=H(T), json={"segment_ids": [1]})
check(r.status_code == 402, "платный путь упирается в лимит: " + str(r.status_code))
msg = r.json().get("error", "")
check("$" not in msg, "в тексте отказа нет сумм: " + msg[:90])
check("лимит" in msg.lower(), "но лимит назван — молчаливо погасшая кнопка выглядит поломкой")
check(r.json()["spend"].get("hidden") is True and "spentUsd" not in r.json()["spend"],
      "и в теле отказа сумм тоже нет")

print("\n=== 6. Обычную организацию это не задевает ===")
main.STATE["spend"]["default"] = {main._month_key(): {"usd": 5.0, "calls": 1, "unpriced": 0}}
main._tenant_rec("default")["limitUsd"] = 0.0
r = c.post("/api/projects/1/batch", headers=H(S), json={"segment_ids": [1]})
check(r.status_code == 402 and "$" in r.json().get("error", ""),
      "у обычной организации отказ по-прежнему называет суммы")

print("\n" + ("ПРОВАЛЕНО: " + "; ".join(fail) if fail else "ВСЁ ПРОШЛО"))
sys.exit(1 if fail else 0)
