# -*- coding: utf-8 -*-
"""Очередь прогонов: своя каждому при ОДНОМ исполнителе.

Исполнитель прогонов один (инвариант 2: второй писатель того же документа
молча теряет работу одного из них). Значит «своя очередь каждому» — это не
параллельность, а порядок, и порядок обязан быть честным: пять человек,
запустивших книги одновременно, не должны ждать друг друга целиком.

Отбор по номеру задачи этого не даёт: единица планирования там — ЗАДАЧА,
то есть книга на часы. Поэтому единицей сделана ПОРЦИЯ, и держится всё
на трёх вещах, каждую из которых и сторожит этот набор:

  1. БИЛЕТ (`qseq`) задаёт порядок, а уступка выдаёт НОВЫЙ билет. Оставь
     прежний — уступивший тут же заберёт исполнителя обратно (у него меньше
     номер), и уступка станет пустой тратой.
  2. Уступаем только ЧУЖОМУ. Своей же второй задаче уступать незачем:
     человек всё равно ждёт себя, а перекладывание порций растянет обе.
  3. Уступившая задача НЕ ЗАВЕРШЕНА: остаток при ней, счётчики и расход
     накапливаются дальше, а отчёт о расходе пишется РОВНО ОДИН раз.
     Иначе вышла бы запись на каждую порцию, и смета (одна на прогон)
     посчиталась бы столько же раз, испортив поправку estRatio.

Плюс: порядок отбора В ПАМЯТИ и В БАЗЕ обязан быть одним и тем же — два
правила «кто следующий» дали бы разное поведение в зависимости от хранилища.

Ни одного вызова модели: порция подменена.
"""
import os, sys
os.environ["APP_PASSWORD"] = "test-queue-password"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
main._job_persist = lambda job: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["runCosts"] = []
main._JOBS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def mkjob(jid, tenant, project, ids, qseq=None):
    j = {"id": jid, "kind": "full", "project": project, "status": "queued",
         "tenant": tenant, "user": 1, "lang": "ru", "total": len(ids), "done": 0,
         "counters": {}, "error": None, "params": {}, "created": "", "started": None,
         "finished": None, "qseq": qseq if qseq is not None else jid,
         "ids": list(ids), "stop": False, "recent": []}
    main._JOBS[jid] = j
    return j


print("=== 1. Порядок — по билету, а не по номеру задачи ===")
main._JOBS.clear()
a = mkjob(1, "aziz", 1, [1, 2, 3, 4], qseq=1)
b = mkjob(2, "bek", 2, [5, 6], qseq=2)
picked = main._pick_queued_local()
check(picked["id"] == 1, "первым идёт билет поменьше")
picked["status"] = "queued"          # вернули, чтобы проверить обратный случай
a["qseq"] = 99
check(main._pick_queued_local()["id"] == 2,
      "сменился билет — сменилась и очередь: номер задачи тут ни при чём")

print("\n=== 2. Занятый проект не берут ===")
main._JOBS.clear()
mkjob(1, "aziz", 7, [1], qseq=1)["status"] = "running"
mkjob(2, "aziz", 7, [2], qseq=2)          # тот же проект
mkjob(3, "bek", 8, [3], qseq=3)
got = main._pick_queued_local()
check(got and got["id"] == 3,
      "вторая задача ТОГО ЖЕ проекта пропущена: два писателя одного документа "
      "теряют работу одного из них")

print("\n=== 3. Уступаем чужому, своему — нет ===")
main._JOBS.clear()
mine = mkjob(1, "aziz", 1, [1, 2, 3, 4], qseq=1)
mine["status"] = "running"
mkjob(2, "aziz", 2, [9], qseq=2)          # своя же вторая задача
check(main._job_should_yield(mine) is False, "своей задаче не уступаем")
mkjob(3, "bek", 3, [7], qseq=3)
check(main._job_should_yield(mine) is True, "чужой — уступаем")

print("\n=== 4. Уступка: остаток при задаче, билет новый, задача в хвосте ===")
before = mine.get("qseq")
main._job_yield(mine, [3, 4])
check(mine["status"] == "queued", "задача вернулась в очередь")
check(mine["ids"] == [3, 4], "остаток при ней: сделанное не переделывается")
check(mine["qseq"] > before, "билет НОВЫЙ: иначе уступивший заберёт исполнителя обратно")
check(mine["total"] == 4 and mine["yields"] == 1,
      "исходный объём и число уступок сохранены — прогресс считается по ним")
nxt = main._pick_queued_local()
# Следующий — тот, чей билет МЕНЬШЕ, то есть кто дольше ждёт; уступивший
# ушёл в самый хвост. Здесь это своя же вторая задача (билет 2), а не чужая
# (билет 3), и это правильно: очередь честна по времени ожидания, а не
# по владельцу — иначе человек с двумя задачами всегда пропускал бы вперёд.
check(nxt["id"] == 2, "следующим идёт тот, кто дольше ждёт: " + str(nxt["id"]))
check(mine["qseq"] > max(j["qseq"] for j in main._JOBS.values() if j is not mine),
      "а уступивший встал в самый хвост")

print("\n=== 5. Круг: два прогона делят исполнителя по очереди ===")
main._JOBS.clear()
x = mkjob(1, "aziz", 1, [1, 2, 3, 4, 5, 6], qseq=1)
y = mkjob(2, "bek", 2, [7, 8, 9, 10], qseq=2)
main.JOB_CHUNKS["full"] = 2
served = []
calls = {"n": 0}


def fake_chunk(kind, pid, chunk, params):
    calls["n"] += 1
    served.append((pid, tuple(chunk)))
    return {"done": len(chunk), "errors": 0}


main._job_chunk = fake_chunk
for _ in range(6):
    j = main._pick_queued_local()
    if not j:
        break
    main._job_execute(j)
order = [pid for pid, _ in served]
check(order[:4] == [1, 2, 1, 2] or order[:4] == [1, 2, 2, 1],
      "исполнитель ходит между прогонами, а не доедает первый до конца: " + str(order))
check(x["done"] == 6 and y["done"] == 4, "оба доведены до конца: " + str((x["done"], y["done"])))
check(x["status"] == "done" and y["status"] == "done", "и оба завершились")
check(sorted(sum([list(c) for _, c in served], [])) == list(range(1, 11)),
      "каждый сегмент обработан РОВНО один раз: " + str(served))

print("\n=== 6. Отчёт о расходе — один на прогон, а не на порцию ===")
main._JOBS.clear()
main.STATE["runCosts"] = []
z = mkjob(1, "aziz", 1, [1, 2, 3, 4], qseq=1)
mkjob(2, "bek", 2, [5, 6], qseq=2)
main.JOB_CHUNKS["full"] = 2


def paying_chunk(kind, pid, chunk, params):
    # Порция «потратила» денег — ровно так их накапливает настоящий прогон.
    with main._USAGE_LOCK:
        sink = main._USAGE_SINK
    if sink is not None:
        sink["calls"] += 1
        sink["cost"] += 0.01
    return {"done": len(chunk), "errors": 0}


main._job_chunk = paying_chunk
for _ in range(6):
    j = main._pick_queued_local()
    if not j:
        break
    main._job_execute(j)
mine_costs = [r for r in main.STATE["runCosts"] if r["job"] == 1]
check(len(mine_costs) == 1,
      "у уступавшего прогона РОВНО одна запись расхода, а не по одной на порцию: "
      + str(len(mine_costs)))
check(abs(mine_costs[0]["cost"] - 0.02) < 1e-9,
      "и в ней ПОЛНАЯ сумма обеих порций: " + str(mine_costs[0]["cost"]))
check(mine_costs[0]["status"] == "done", "запись сделана на настоящем завершении")

print("\n=== 7. Место в очереди отдаётся числом и без чужих подробностей ===")
main._JOBS.clear()
q1 = mkjob(1, "aziz", 1, [1], qseq=1)
q2 = mkjob(2, "bek", 2, [2], qseq=2)
q3 = mkjob(3, "aziz", 3, [3], qseq=3)
tok = main.CURRENT_SESSION.set({"tenant": "aziz", "role": "owner", "user": 1})
try:
    pub = main._job_public(q3)
finally:
    main.CURRENT_SESSION.reset(tok)
check(pub["queuePos"] == 3 and pub["queueAhead"] == 2, "место и сколько впереди")
check(pub["queueOthers"] == 1, "и сколько из них чужих: " + str(pub.get("queueOthers")))
check(not any(k in str(pub) for k in ("bek",)), "чужая организация в ответе не названа")
q1["status"] = "running"
check(main._job_public(q1) .get("queuePos") is None, "у идущего прогона места в очереди нет")

print("\n=== 8. Правило отбора одно на память и на базу ===")
import inspect
src = inspect.getsource(main._pick_queued_local)
import io as _io
store_src = _io.open("backend/store.py", encoding="utf-8").read()
check("qseq" in src and "qseq" in store_src, "оба отбора идут по билету")
check("running" in src and "r.status = 'running'" in store_src,
      "оба пропускают проект, у которого прогон уже идёт")

print("\n" + ("ПРОВАЛЕНО: " + "; ".join(fail) if fail else "ВСЁ ПРОШЛО"))
sys.exit(1 if fail else 0)
