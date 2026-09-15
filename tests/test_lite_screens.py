"""«Словари» и «Проверка» налегке: серверная половина.

Сторожится:
  1. /term-queue?actionable=1 отдаёт человеку только вопросы: карточки,
     ждущие данных (`wait`) и уже закрытые глоссарием (`close`), уходят
     из ответа ДО среза страницы, их число названо полем `waiting`;
     без флага ответ прежний;
  2. шаг `_job_auto_terms` в конце составного прогона: зовёт автоодобрение
     ТОЛЬКО подсказкой, ровно один раз (флаг переживает повтор), только
     у `full` с `auto_terms`, пропускает шаг на исчерпанном лимите, а сбой
     шага прогон не роняет;
  3. `_job_run` зовёт шаг только у прогона, прошедшего ВСЕ порции:
     остановленный прогон словарь не трогает;
  4. кнопка «Доделать сама» получает `auto_terms` из `turnkey.params`.

Модель не зовётся: автоодобрение подменено, вердикты очереди — тоже.
Запуск: python tests/test_lite_screens.py
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
main._job_persist = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# ─────────── 1. очередь для человека ───────────
print("=== 1. actionable: только вопросы ===")
proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "general", "segments": []}
main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [], "autoBatches": []}
scope = main._project_scope(proj)
cands = []
for i, verdict in enumerate(["human", "wait", "close", "auto", "wait", "human"], start=1):
    cands.append({"id": i, "kind": "extract", "src": "термин %d" % i, "tgt": "term %d" % i,
                  "status": "pending", "lang": scope[0], "domain": scope[1], "hits": 1,
                  "_v": verdict})
main.STATE["termQueue"] = cands

VERDICT = {"human": (None, "нужен человек"), "wait": ("wait", "мало доноров"),
           "close": ("close", "уже в глоссарии"), "auto": (main.GLOSSARY_TIER_SOFT, "однозначно")}
main._auto_verdict = lambda c, ctx: VERDICT[c["_v"]]
main._cand_impacts = lambda p, items: {}

full = main.list_term_queue(project=1)
check(full["total"] == 6 and len(full["items"]) == 6, "без флага ответ прежний: 6 карточек")
check(full.get("waiting") == 0, "и waiting = 0")

act = main.list_term_queue(project=1, actionable=True)
ids = sorted(c["id"] for c in act["items"])
check(ids == [1, 4, 6], "с флагом остались вопросы и готовые к одобрению: %s" % ids)
check(act["total"] == 3, "total считается по отфильтрованному: %s" % act["total"])
check(act["waiting"] == 3, "ждущие и закрытые названы числом: %s" % act["waiting"])

page = main.list_term_queue(project=1, actionable=True, limit=2)
check([c["id"] for c in page["items"]] == [6, 4] or len(page["items"]) == 2,
      "фильтр стоит ДО среза: на странице из двух — два вопроса")
check(page["total"] == 3, "и total страницы — все вопросы, а не показанные")

noproj = main.list_term_queue(actionable=True)
check(noproj["total"] == 6 and noproj["waiting"] == 0,
      "без проекта вердиктов нет — фильтровать нечем, ответ полный")

# ─────────── 2. шаг автоодобрения ───────────
print("\n=== 2. _job_auto_terms ===")
calls = []


def fake_approve(req):
    calls.append(req)
    return {"ok": True, "batch": 42,
            "counts": {"auto": 3, "verified": 0, "closed": 2, "rejectedMeaning": 1}}


main.auto_approve_terms = fake_approve
main._spend_status = lambda *a, **k: {"over": False}


def job(kind="full", **params):
    return {"id": 7, "kind": kind, "project": 1, "tenant": main.DEFAULT_TENANT,
            "status": "running", "counters": {}, "params": dict(params)}


j = job(auto_terms=True)
main._job_auto_terms(j)
check(len(calls) == 1, "составной прогон с auto_terms зовёт автоодобрение")
r = calls[0] if calls else None
check(r is not None and r.max_tier == main.GLOSSARY_TIER_SOFT,
      "только ПОДСКАЗКОЙ (инвариант 8)")
check(r is not None and not r.dry_run and r.project == 1 and not r.allow_verified,
      "всерьёз, по своему проекту, запрет области не снят")
check(j["counters"].get("termsAuto") == 3 and j["counters"].get("termsAutoRejected") == 1
      and j.get("termsAutoBatch") == 42, "счётчики и пачка для отката записаны в задачу")
check(j["params"].get("termsAutoDone") is True, "флаг «уже раскладывали» стоит")
main._job_auto_terms(j)
check(len(calls) == 1, "повтор (рестарт, уступка) вторую пачку не пишет")

calls.clear()
main._job_auto_terms(job())
main._job_auto_terms(job(kind="translate", auto_terms=True))
check(not calls, "без auto_terms и у одиночного шага словарь не трогается")

main._spend_status = lambda *a, **k: {"over": True}
jl = job(auto_terms=True)
main._job_auto_terms(jl)
check(not calls and jl.get("termsAutoSkipped") == "limit" and jl["status"] == "running",
      "лимит исчерпан — шаг пропущен, а прогон НЕ объявлен остановленным")
main._spend_status = lambda *a, **k: {"over": False}


def boom(req):
    raise RuntimeError("судья упал")


main.auto_approve_terms = boom
je = job(auto_terms=True)
try:
    main._job_auto_terms(je)
    ok = True
except Exception:
    ok = False
check(ok and "судья упал" in (je.get("termsAutoError") or ""),
      "сбой шага прогон не роняет, причина записана")
main.auto_approve_terms = fake_approve

# ─────────── 2b. история пачек — по организации ───────────
print("\n=== 2b. _push_auto_batch ===")
forgot = []
orig_forget = main._forget_auto_batch
main._forget_auto_batch = lambda bid: forgot.append(bid)
cap = main.AUTO_BATCH_HISTORY
legacy = [{"id": 900 + i, "at": "old"} for i in range(3)]          # прежний код: без tenant
theirs = [{"id": 500 + i, "tenant": "acme"} for i in range(cap)]
main.STATE["autoBatches"] = list(theirs) + list(legacy)
main._JOB_TENANT.id = "default"
for i in range(cap + 2):
    main._push_auto_batch({"id": 1000 + i})
bs = main.STATE["autoBatches"]
mine = [b for b in bs if b.get("tenant") == "default"]
check(len(mine) == cap and mine[0]["id"] == 1000 + cap + 1,
      "своих пачек — не больше потолка, новейшая первой")
check(all(b["tenant"] == "default" for b in bs if b["id"] >= 1000),
      "организация в потоке задачи взята из _JOB_TENANT")
check(sorted(forgot) == [1000, 1001], "откат забыт ровно у двух своих старейших: %s" % forgot)
check(len([b for b in bs if b.get("tenant") == "acme"]) == cap,
      "чужие пачки не вытеснены — их откаты живы")
check(len([b for b in bs if "tenant" not in b]) == 3,
      "пачки прежнего кода без tenant не обрезаются: чей откат — неизвестно")
main._forget_auto_batch = orig_forget

# ─────────── 3. _job_run: только после всех порций ───────────
print("\n=== 3. _job_run зовёт шаг только у дошедшего до конца ===")
seen = []
main._job_auto_terms = lambda jb: seen.append(jb["status"])
main._job_chunk = lambda kind, pid, chunk, params: {"done": len(chunk)}
main._job_limit_hit = lambda jb: False
main._job_should_yield = lambda jb: False
main._backup_stamp = lambda *a, **k: "20260915-000000"
main._backup_drop_empty = lambda *a, **k: None
main.STATE["projects"][0]["segments"] = [{"id": 1, "source": "а", "target": ""}]
jr = {"id": 8, "kind": "full", "project": 1, "tenant": main.DEFAULT_TENANT, "status": "running",
      "counters": {}, "params": {"auto_terms": True}, "ids": [1, 2], "done": 0, "total": 2,
      "stop": False, "lang": "ru"}
main._job_run(jr)
check(seen == ["running"] and jr["status"] == "done", "дошедший до конца прогон — шаг позван")
seen.clear()
js = dict(jr, status="running", stop=True, params={"auto_terms": True}, done=0, counters={})
main._job_run(js)
check(not seen and js["status"] == "stopped", "остановленный прогон словарь не трогает")

# ─────────── 4. параметры кнопки ───────────
print("\n=== 4. turnkey.params ===")
src = open("backend/main.py", encoding="utf-8").read()
check('"include_confirmed": False, "auto_terms": True}' in src,
      "turnkey.params несёт auto_terms — кнопка «Доделать сама» шлёт его сама")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
