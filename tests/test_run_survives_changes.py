# -*- coding: utf-8 -*-
"""Идущий прогон переживает смену моделей и выкат без потери работы.

Что сторожится и почему:

  1. Модели шагов по умолчанию ЗАМОРОЖЕНЫ на постановке задачи (`sysModels`,
     `_dm`). Правка системной настройки посреди прогона не меняет модель
     следующей порции — ни в потоке прогона, ни в рабочих потоках порции.
  2. Модель, пропавшая из каталога после выката, заменяется умолчанием СВОЕГО
     шага (а не переводчиком — так сделал бы `_resolve_model`), и замена
     названа (`modelsReplaced`).
  3. Курсор порций: поднятая заново задача продолжает с несделанной порции,
     а не с первой — `done` не уезжает за 100%, готовое не переделывается.
  4. Остановка сервиса откладывает задачу после ТЕКУЩЕЙ порции: статус
     `queued`, прежние курсор и билет, расход не закрыт; исполнитель новых
     задач не берёт.
  5. Конфликт документа проекта у воркера сливается трёхсторонне: порция
     прогона не выбрасывается, чужие правки (миграция на выкате) не теряются,
     ссылки на объекты сегментов живы.
  6. Постановка задачи через API кладёт снимок; упрощённый режим его не показывает.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys, threading
os.environ["APP_PASSWORD"] = "test-survive-password"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["runCosts"] = []
main.STATE["systemModels"] = {}
main._apply_system_models()
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def set_sys(models):
    main.STATE["systemModels"] = dict(models)
    main._apply_system_models()


def new_job(kind="backcheck", ids=None, **extra):
    job = {"id": 900 + len(main._JOBS), "kind": kind, "project": 1, "status": "running",
           "tenant": "default", "user": None, "lang": "ru", "total": len(ids or []), "done": 0,
           "counters": {}, "error": None, "params": {}, "created": "x", "started": None,
           "finished": None, "qseq": 5, "ids": list(ids or []), "stop": False, "recent": [],
           "sysModels": main._system_models_snapshot()}
    job.update(extra)
    main._JOBS[job["id"]] = job
    return job


print("=== 1. Смена системной модели посреди прогона ===")
set_sys({"backcheck": "gpt-4o-mini"})
job = new_job(ids=list(range(1, 21)))            # две порции по 10
set_sys({"backcheck": "gpt-4.1"})                # суперпользователь поправил ПОСЛЕ постановки
seen = []
real_chunk = main._job_chunk


def chunk_models(kind, pid, chunk, params):
    seen.append((main._dm("backcheck"), main._backcheck_model({"provider": "x"}, None),
                 tuple(main._run_parallel([1, 2, 3], lambda _x: main._dm("backcheck")))))
    set_sys({"backcheck": "gpt-4o"})             # и ещё раз — посреди прогона
    return {"done": len(chunk)}


main.RUN_WORKERS = 4
main._job_chunk = chunk_models
main._job_execute(job)
check(job["status"] == "done" and len(seen) == 2, "прогон дошёл до конца: %s" % job["status"])
check(all(s[0] == "gpt-4o-mini" and s[1] == "gpt-4o-mini" for s in seen),
      "обе порции — модель с постановки: %s" % [s[:2] for s in seen])
check(all(set(s[2]) == {"gpt-4o-mini"} for s in seen), "рабочие потоки порции видят тот же снимок")
check(main._dm("backcheck") == "gpt-4o", "вне прогона действует нынешняя настройка")
check(getattr(main._JOB_MODELS, "m", None) is None, "снимок снят с потока после задачи")

print("=== 2. Модели нет в каталоге после выката ===")
set_sys({})
job = new_job(ids=[1], sysModels={"backcheck": "gone-model", "translate": "gpt-4.1"},
              params={"bc_model": "also-gone", "model": "gpt-4.1"})
main._job_chunk = lambda *a: {"done": 1}
main._job_execute(job)
check(job["sysModels"]["backcheck"] == main._CODE_DEFAULT_MODELS["backcheck"]
      and job["sysModels"]["translate"] == "gpt-4.1", "пропавшее умолчание — умолчание кода своего шага")
check(job["params"]["bc_model"] is None and job["params"]["model"] == "gpt-4.1",
      "пропавший явный выбор — умолчание шага, живой выбор не тронут")
check(len(job.get("modelsReplaced") or []) == 2, "замена названа: %s" % job.get("modelsReplaced"))
old = new_job(ids=[1])
old.pop("sysModels")
main._job_execute(old)
check(isinstance(old.get("sysModels"), dict), "задача прежнего кода получает снимок на старте")

print("=== 3. Курсор: продолжение с несделанной порции ===")
calls = []


def chunk_fail_second(kind, pid, chunk, params):
    calls.append(chunk[0])
    if chunk[0] == 11:
        raise main.HTTPException(503, "нет ключа")
    return {"done": len(chunk)}


job = new_job(ids=list(range(1, 26)))
main._job_chunk = chunk_fail_second
main._job_execute(job)
check(job["status"] == "error" and job["cursor"] == 10 and job["done"] == 10,
      "упала вторая порция: курсор на ней, сделано 10 (%s, %s)" % (job.get("cursor"), job["done"]))
calls.clear()
job["status"], job["error"] = "running", None
main._job_chunk = lambda kind, pid, chunk, params: (calls.append(chunk[0]) or {"done": len(chunk)})
main._job_execute(job)
check(calls == [11, 21] and job["done"] == 25 and job["status"] == "done",
      "продолжение — с 11, без повтора сделанного: %s, done=%s" % (calls, job["done"]))

print("=== 4. Остановка сервиса откладывает, а не обрывает ===")
main.STATE["runCosts"] = []
job = new_job(ids=list(range(1, 31)), qseq=42)
calls.clear()


def chunk_then_shutdown(kind, pid, chunk, params):
    calls.append(chunk[0])
    main._note_usage("backcheck", "gpt-4o-mini", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    main._SHUTDOWN.set()                          # SIGTERM пришёл посреди порции
    return {"done": len(chunk)}


main._job_chunk = chunk_then_shutdown
main._job_execute(job)
check(calls == [1], "порция, начатая до сигнала, доделана, следующая не начата")
check(job["status"] == "queued" and job["cursor"] == 10 and job["qseq"] == 42 and not job.get("finished"),
      "отложена: queued, курсор 10, билет прежний (%s, %s, %s)" % (job["status"], job.get("cursor"), job["qseq"]))
check(not main.STATE["runCosts"] and (job.get("usage") or {}).get("calls") == 1,
      "расход не закрыт — продолжение досчитает тот же счётчик")
t = threading.Thread(target=main._job_loop, daemon=True)
t.start()
t.join(3)
check(not t.is_alive(), "исполнитель при остановке новых задач не берёт и выходит")
main._SHUTDOWN.clear()
job["status"] = "running"
main._job_chunk = lambda kind, pid, chunk, params: (calls.append(chunk[0]) or {"done": len(chunk)})
main._job_execute(job)
check(calls == [1, 11, 21] and job["done"] == 30 and job["status"] == "done",
      "после рестарта — дальше с 11: %s" % calls)
check(len(main.STATE["runCosts"]) == 1, "отчёт о расходе — ровно один на прогон")
main._job_chunk = real_chunk

print("=== 5. Конфликт документа у воркера: трёхсторонняя сверка ===")
import copy
base = {"id": 7, "name": "Книга", "pages": 10, "segments": [
    {"id": 1, "target": "a"}, {"id": 2, "target": "b"}, {"id": 3, "target": "c"}, {"id": 4, "target": "d"}]}
local = copy.deepcopy(base)
fresh = copy.deepcopy(base)
local["segments"][0]["target"] = "A-run"          # сделал прогон
local["segments"][2]["target"] = "C-run"          # обе стороны — побеждает прогон
local["segments"].append({"id": 5, "target": "new-from-run"})
local["runNote"] = "x"                            # поле проекта, заведённое прогоном
fresh["segments"][1]["migrated"] = True           # миграция API
fresh["segments"][2]["migrated"] = True
fresh["pages"] = 12
fresh["pagesUnit"] = "words"
seg1_obj = local["segments"][1]


class FakeStore:
    kind = "pg"

    def base_doc(self, key):
        return copy.deepcopy(base)


main.STATE["projects"] = [local]
saved_store, saved_worker = main.STORE, main.IS_WORKER
main.STORE, main.IS_WORKER = FakeStore(), True
main._ACTIVE_JOB["job"] = {"id": 77, "project": 7}
ok = main._merge_run_conflict("projects:7", fresh)
by = {s["id"]: s for s in local["segments"]}
check(ok, "слито, а не выброшено")
check(by[1]["target"] == "A-run" and by[5]["target"] == "new-from-run", "работа прогона на месте")
check(by[2].get("migrated") is True and by[2] is seg1_obj, "чужая правка принята НА МЕСТЕ (ссылка жива)")
check(by[3]["target"] == "C-run", "спорный сегмент остаётся за прогоном")
check(local["pages"] == 12 and local["pagesUnit"] == "words" and local["runNote"] == "x",
      "поля проекта: чужие приняты, свои сохранены")
check(not main._merge_run_conflict("projects:8", fresh), "чужой проект — прежнее правило")
main.IS_WORKER = False
check(not main._merge_run_conflict("projects:7", fresh), "в процессе API — прежнее правило")
main.STORE, main.IS_WORKER = saved_store, saved_worker
main._ACTIVE_JOB.pop("job", None)

print("=== 6. Постановка через API ===")
main.STATE["projects"] = [{"id": 1, "name": "p", "tenant": "default", "src": "RU", "tgt": "EN",
                           "segments": [{"id": 1, "source": "текст", "target": ""}]}]
main._ensure_job_worker = lambda: None
set_sys({"repair": "gpt-4o-mini"})
c = TestClient(main.app)
main._ensure_users()
tok = c.post("/api/auth/login", json={"login": "admin", "password": "test-survive-password"}).json()["token"]
r = c.post("/api/projects/1/jobs", headers={"Authorization": "Bearer " + tok},
           json={"kind": "repair", "segment_ids": [1], "params": {}})
j = (r.json() or {}).get("job") or {}
check(r.status_code == 200 and (j.get("sysModels") or {}).get("repair") == "gpt-4o-mini",
      "задача несёт снимок: %s %s" % (r.status_code, j.get("sysModels")))
real_hide = main._hide_cost
main._hide_cost = lambda *a, **k: True
pub = main._job_public(dict(main._JOBS[j["id"]], modelsReplaced=["x"]))
check("sysModels" not in pub and "modelsReplaced" not in pub, "упрощённый режим имён моделей задачи не видит")
main._hide_cost = real_hide
set_sys({})

print("\nПРОВАЛЕНО: %d" % len(fail) if fail else "\nВсё сошлось")
sys.exit(1 if fail else 0)
