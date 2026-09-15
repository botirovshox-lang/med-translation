# -*- coding: utf-8 -*-
"""Модели шагов на всю систему и виртуальный пересчёт расхода (админка).

Что сторожится и почему:

  1. Настройку правит ТОЛЬКО суперпользователь, и проверка на сервере:
     модели шагов меняют работу и деньги всех организаций сразу.
  2. Неизвестная модель или шаг — 400 ДО записи: молча положенное имя
     обернулось бы прогоном по умолчанию при уверенности, что назначено другое.
  3. Настройка действует через константы-умолчания — те, что читают все места
     выбора модели: `/api/models` (из него браузер заполняет выбор и считает
     смету) и сами шаги. Пустой шаг — снова умолчание кода.
  4. `/api/seed` не отдаёт ни настройку, ни журнал токенов: там имена моделей
     и расход всех организаций по людям.
  5. Журнал пишется на КАЖДОМ вызове с автором: из сессии, из потока прогона
     и из рабочих потоков порции (`_run_parallel`).
  6. Пересчёт считает те же токены по ценам выбранных моделей; фильтры по
     организации и человеку режут строки, группа без модели остаётся фактом.
  7. Пустой журнал один раз наполняется из истории прогонов, и об этом
     сказано числом (`historyRows`).

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "test-sysmodels-password"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["runCosts"] = []
main.STATE["systemModels"] = {}
main.STATE[main.USAGE_LEDGER_KEY] = {}
main._apply_system_models()
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
S = c.post("/api/auth/login", json={"login": "admin", "password": "test-sysmodels-password"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "trial", "name": "Тест", "ownerLogin": "trial", "ownerPassword": "trial-pass-123"})
O = c.post("/api/auth/login", json={"login": "trial", "password": "trial-pass-123"}).json()["token"]

print("=== 1. Право ===")
check(c.get("/api/admin/system-models", headers=H(O)).status_code == 403, "владелец организации — 403 на чтение")
check(c.post("/api/admin/system-models", headers=H(O), json={"models": {"translate": "gpt-4o-mini"}}).status_code == 403,
      "владелец организации — 403 на запись")
check(c.post("/api/admin/usage/simulate", headers=H(O),
             json={"dateFrom": "2026-01-01", "dateTo": "2026-12-31"}).status_code == 403, "пересчёт — 403")

print("=== 2. Проверка до записи ===")
code_bc = main._CODE_DEFAULT_MODELS["backcheck"]
r = c.post("/api/admin/system-models", headers=H(S), json={"models": {"backcheck": "no-such-model"}})
check(r.status_code == 400 and main.BACKCHECK_DEFAULT_MODEL == code_bc, "неизвестная модель — 400, ничего не поменялось")
r = c.post("/api/admin/system-models", headers=H(S), json={"models": {"nope": "gpt-4o"}})
check(r.status_code == 400 and not main.STATE["systemModels"], "неизвестный шаг — 400")

print("=== 3. Действует ===")
r = c.post("/api/admin/system-models", headers=H(S),
           json={"models": {"backcheck": "gpt-4o-mini", "translate": "gpt-4.1", "review": ""}})
check(r.status_code == 200, "запись принята")
check(main.STATE["systemModels"] == {"backcheck": "gpt-4o-mini", "translate": "gpt-4.1"}, "пустой шаг не хранится")
check(main.BACKCHECK_DEFAULT_MODEL == "gpt-4o-mini", "умолчание back-check подменено")
m = c.get("/api/models", headers=H(O)).json()
check(m["backcheckDefault"] == "gpt-4o-mini" and m["default"] == "gpt-4.1", "/api/models отдаёт системные модели")
check(main._backcheck_model({"provider": "gpt-4.1"}, None) == "gpt-4o-mini", "шаг без выбора берёт системную модель")
steps = {s["key"]: s for s in r.json()["steps"]}
check(steps["backcheck"]["effective"] == "gpt-4o-mini" and steps["review"]["value"] is None
      and steps["review"]["effective"] == main._CODE_DEFAULT_MODELS["review"], "ответ называет действующую модель")
c.post("/api/admin/system-models", headers=H(S), json={"models": {}})
check(main.BACKCHECK_DEFAULT_MODEL == code_bc and main.DEFAULT_OPENAI_MODEL == main._CODE_DEFAULT_MODELS["translate"],
      "очистка возвращает умолчания кода")

print("=== 4. /api/seed ===")
main.STATE["systemModels"] = {"translate": "gpt-4.1"}
seed = c.get("/api/seed", headers=H(O)).json()
check("systemModels" not in seed and main.USAGE_LEDGER_KEY not in seed, "seed без настройки и журнала")
main.STATE["systemModels"] = {}
main._apply_system_models()

print("=== 5. Журнал с автором ===")
main.STATE[main.USAGE_LEDGER_KEY] = {}
U = lambda tin, tout: {"usage": {"prompt_tokens": tin, "completion_tokens": tout}}
tok = main.CURRENT_SESSION.set({"tenant": "trial", "user": "u1"})
main._note_usage("translate", "gpt-4o", U(1_000_000, 1_000_000))          # 2.5 + 10 = 12.5
main.CURRENT_SESSION.reset(tok)
main._JOB_TENANT.id, main._JOB_USER.id = "default", "u2"
main._note_usage("backcheck", "gpt-5.6-luna", U(1_000_000, 1_000_000))    # 0.2 + 1.2 = 1.4
main.RUN_WORKERS = 4
main._JOB_USER.id = "u3"
seen = main._run_parallel([1, 2, 3], lambda x: main._current_uid())
check(seen == ["u3", "u3", "u3"], "рабочие потоки порции знают автора")
main._JOB_TENANT.id, main._JOB_USER.id = None, None
rows = main._ledger_rows("2000-01-01", "2999-12-31")
check(sorted((r["user"], r["tenant"], r["step"]) for r in rows)
      == [("u1", "trial", "translate"), ("u2", "default", "backcheck")], "строки несут автора и организацию")

print("=== 6. Пересчёт ===")
today = main.datetime.now().strftime("%Y-%m-%d")
body = {"dateFrom": today, "dateTo": today}
r = c.post("/api/admin/usage/simulate", headers=H(S), json=body).json()
check(abs(r["total"]["actual"] - 13.9) < 1e-6 and abs(r["total"]["sim"] - 13.9) < 1e-6, "без моделей пересчёт = факт")
r = c.post("/api/admin/usage/simulate", headers=H(S), json=dict(body, models={"translate": "gpt-4o-mini"})).json()
g = {x["group"]: x for x in r["groups"]}
check(abs(g["translate"]["sim"] - 0.75) < 1e-6 and abs(g["backcheck"]["sim"] - 1.4) < 1e-6, "группы по ценам выбранных моделей")
check(abs(r["total"]["sim"] - 2.15) < 1e-6, "итог пересчёта")
check(g["translate"]["actualModels"] == {"gpt-4o": 1}, "названа фактическая модель")
r = c.post("/api/admin/usage/simulate", headers=H(S), json=dict(body, user="u1")).json()
check(abs(r["total"]["actual"] - 12.5) < 1e-6 and len(r["byUser"]) == 1, "фильтр по человеку")
r = c.post("/api/admin/usage/simulate", headers=H(S), json=dict(body, tenant="default")).json()
check(abs(r["total"]["actual"] - 1.4) < 1e-6, "фильтр по организации")
check(c.post("/api/admin/usage/simulate", headers=H(S), json={"dateFrom": "2026-02-01", "dateTo": "2026-01-01"}).status_code == 400,
      "перевёрнутый период — 400")
check(c.post("/api/admin/usage/simulate", headers=H(S), json=dict(body, models={"translate": "x"})).status_code == 400,
      "неизвестная модель в пересчёте — 400")
check(c.post("/api/admin/usage/simulate", headers=H(S), json=dict(body, models={"embed": "gpt-4o"})).status_code == 400,
      "эмбеддинг не пересчитывается")

print("=== 7. Наполнение из истории ===")
main.STATE[main.USAGE_LEDGER_KEY] = {}
main.STATE["runCosts"] = [{"finished": "2026-08-01 10:00:00", "tenant": "trial",
                           "steps": {"translate": {"calls": 2, "in": 100, "out": 50, "reasoning": 0, "cost": 0.1}}}]
check(main._seed_usage_ledger() == 1, "перенесена строка истории")
check(main._seed_usage_ledger() == 0, "повторно не переносится")
r = c.post("/api/admin/usage/simulate", headers=H(S), json={"dateFrom": "2026-08-01", "dateTo": "2026-08-01"}).json()
check(r["historyRows"] == 1 and r["byUser"][0]["user"] is None and r["ledgerSince"] == "2026-08-01",
      "перенесённое названо и без автора")

print("\nПРОВАЛЕНО: %d" % len(fail) if fail else "\nВсё сошлось")
sys.exit(1 if fail else 0)
