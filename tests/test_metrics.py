# -*- coding: utf-8 -*-
"""Счётчики событий и сводка «где теряем, где заработать, что чинить».

Что сторожится и почему (каждый пункт — разобранный способ сломать сервис,
а не проверка ради проверки):

  1. Событие НЕ живёт в STATE. Буфер — в памяти модуля, и `ev()` не трогает
     ни диск, ни базу, ни `save_state`: событие на каждый HTTP-запрос,
     записанное в состояние, означало бы перезапись всего `state.json`
     на каждый запрос (инвариант 2).
  2. Слив в файловое хранилище идёт ПОД `_SAVE_LOCK`. Без него правка
     вложенного словаря из потока запроса роняет `json.dumps(state)`
     в `FileStore.save` — то есть НЕСОХРАНЁННУЮ работу человека.
  3. Запрос, у которого нет шаблона маршрута (404, отказ входа до
     маршрутизации), считается и НЕ РОНЯЕТ мидлварь: `scope["route"]`
     кладёт только FastAPI и только при совпадении.
  4. Необработанное исключение обработчика попадает в счётчик `err:500`
     и пробрасывается дальше. Оно проходит мимо наших мидлварей ответом
     (его превращает в 500 `ServerErrorMiddleware` ВНЕ нашей цепочки),
     поэтому без явной ветки самая дорогая метрика не записалась бы.
  5. Организация берётся у запроса, а у прогона — из его потока
     (`_JOB_TENANT`): ContextVar в рабочие потоки не доезжает (инвариант 11),
     и без этого весь расход прогонов уехал бы в «default», то есть
     отчёт владельцу врал бы, а не «терял точность».
  6. Отказы по потолкам считаются В МЕСТЕ ОТКАЗА, а не по коду ответа:
     402 отдают и лимит расхода, и кончившиеся страницы, и потолок
     проектов — а это ТРИ РАЗНЫХ предложения клиенту.
  7. Сбой хранилища не роняет запрос и не теряет накопленное: строки
     возвращаются в буфер.
  8. `/api/seed` не отдаёт счётчики (белый список), сводка — только
     суперпользователю.
  9. Сводка выводит подсказки с ЧИСЛОМ и организацией, а суточный текст
     собирается по-русски на сервере (он уходит мимо браузера — в Telegram
     и ИИ-агенту, подставить перевод на границе показа там некому).
 10. Файловое хранилище подрезается по дням: `state.json` не вправе расти
     без границы.

Ни одного вызова модели, боевой файл состояния не пишется.
"""
import os
import sys
import json
import threading
import time

os.environ["APP_PASSWORD"] = "test-metrics-password"
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")
import main                                    # noqa: E402
from starlette.testclient import TestClient    # noqa: E402

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["quotes"] = []
main.STATE["runCosts"] = []
main.STATE[main.EVENTS_KEY] = {}
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}          # noqa: E731
main._ensure_users()
S = c.post("/api/auth/login",
           json={"login": "admin", "password": "test-metrics-password"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "acme", "name": "Акме", "ownerLogin": "acme",
             "ownerPassword": "acme-pass-123"})
O = c.post("/api/auth/login", json={"login": "acme", "password": "acme-pass-123"}).json()["token"]


print("=== 1. Событие не живёт в STATE и ничего не пишет ===")
main.metrics_mod.reset()
main.STATE[main.EVENTS_KEY] = {}
before = json.dumps(main.STATE, ensure_ascii=False, default=str)
main._ev("cap.filePages413", "acme", 3)
check(main.metrics_mod.pending() == 1, "событие легло в буфер модуля")
check(json.dumps(main.STATE, ensure_ascii=False, default=str) == before,
      "STATE не тронут: ни одного байта в state.json на событие")
main._metrics_flush(force=True)
check(main.metrics_mod.pending() == 0, "слив опустошил буфер")
check(any(k.endswith("|acme|cap.filePages413") for k in main.STATE[main.EVENTS_KEY]),
      "после слива счётчик виден в файловом хранилище")


print("=== 2. Слив не роняет сохранение состояния ===")
# Настоящая гонка: один поток сериализует состояние под `_SAVE_LOCK`
# (ровно то, что делает FileStore.save), другой сливает счётчики.
# Без лока это «dictionary changed size during iteration».
err = []


def _dumper():
    for _ in range(60):
        try:
            with main._SAVE_LOCK:
                json.dumps(main.STATE, ensure_ascii=False, default=str)
        except Exception as e:                  # noqa: BLE001
            err.append(repr(e))


def _writer():
    for i in range(60):
        main._ev("api:GET /t%d" % (i % 7), "acme", 1, 1.0)
        main._metrics_flush(force=True)


th = [threading.Thread(target=_dumper), threading.Thread(target=_writer)]
[t.start() for t in th]
[t.join() for t in th]
check(not err, "сериализация состояния и слив счётчиков не мешают друг другу: " + str(err[:1]))


print("=== 3. Запрос без шаблона маршрута ===")
main.metrics_mod.reset()
r404 = c.get("/api/no-such-thing-at-all", headers=H(S))
rows = {r["code"]: r for r in main.metrics_mod.take()}
check(r404.status_code == 404, "несуществующий адрес отвечает 404, а не 500")
check(any(k.startswith("api:") for k in rows), "запрос посчитан")
check(not any("no-such-thing" in k for k in rows),
      "адрес, придуманный посторонним, в ключ не попал")

print("=== 3б. Статика не меряется ===")
main.metrics_mod.reset()
c.get("/css/styles.css")
check(main.metrics_mod.pending() == 0,
      "статика счётчиков не заводит: её событий было бы больше всего остального")


print("=== 4. Пятисотка считается и пробрасывается ===")


@main.app.get("/api/__boom_for_test")
def _boom():
    raise RuntimeError("нарочно")


main.PUBLIC_API_PATHS.add("/api/__boom_for_test")
main.metrics_mod.reset()
c2 = TestClient(main.app, raise_server_exceptions=False)
rb = c2.get("/api/__boom_for_test")
codes = {r["code"] for r in main.metrics_mod.take()}
check(rb.status_code == 500, "исключение обработчика осталось пятисоткой")
check(any(k.startswith("err:500") for k in codes), "err:500 записан: " + str(sorted(codes)))


print("=== 5. Организация прогона, а не «default» ===")
main.metrics_mod.reset()
got = []


def _in_job():
    main._JOB_TENANT.id = "acme"
    try:
        main._ev("waste.repairReverted")
    finally:
        main._JOB_TENANT.id = None


t = threading.Thread(target=_in_job)
t.start()
t.join()
rows = main.metrics_mod.take()
check(any(r["tenant"] == "acme" and r["code"] == "waste.repairReverted" for r in rows),
      "событие из потока прогона легло на организацию задачи: " + str(rows))


print("=== 6. Потолки считаются в МЕСТЕ отказа, а не по коду ответа ===")
main.metrics_mod.reset()
rec = main._tenant_rec("acme")
rec["pagesCredit"] = 0                      # выдано ноль — значит исчерпано
try:
    main._pages_debit("acme", 5.0, "sha-test", 1, "файл")
except Exception:
    pass
codes = {r["code"] for r in main.metrics_mod.take()}
check("cap.pages402" in codes, "кончившиеся страницы названы своим кодом: " + str(sorted(codes)))
rec.pop("pagesCredit", None)

main.metrics_mod.reset()
st = {"spentUsd": 9.0, "limitUsd": 5.0, "over": True}
main._limit_402(st, "acme")
codes = {r["code"] for r in main.metrics_mod.take()}
check("cap.spend402" in codes, "исчерпанный лимит расхода — свой код, не общий 402")

main.metrics_mod.reset()
main._format_error(main.textcount.Unsupported("нет разбора"), "книга.epub")
main._format_error(main.textcount.Unsupported("нет разбора"), "файл.странное")
codes = {r["code"] for r in main.metrics_mod.take()}
check("cap.format415:other" in codes and len([k for k in codes if k.startswith("cap.format415")]) == 1,
      "расширение вне закрытого списка не плодит ключей: " + str(sorted(codes)))


print("=== 7. Сбой хранилища не теряет накопленное ===")
main.metrics_mod.reset()
main._ev("cap.duplicate409", "acme", 4)
orig = main._events_file_add
main._events_file_add = lambda rows: (_ for _ in ()).throw(RuntimeError("база упала"))
main._metrics_flush(force=True)
main._events_file_add = orig
rows = {r["code"]: r["n"] for r in main.metrics_mod.take()}
check(rows.get("cap.duplicate409") == 4, "не записанное вернулось в буфер, а не пропало")


print("=== 8. Права и /api/seed ===")
main.metrics_mod.reset()
check(c.get("/api/admin/metrics", headers=H(O)).status_code == 403,
      "владелец организации — 403 на сводку")
check(c.get("/api/admin/metrics/digest", headers=H(O)).status_code == 403,
      "владелец организации — 403 на суточный текст")
seed = c.get("/api/seed", headers=H(O)).json()
check(main.EVENTS_KEY not in seed, "/api/seed счётчики не отдаёт")


print("=== 9. Сводка отвечает числами и организациями ===")
main.STATE[main.EVENTS_KEY] = {}
main.metrics_mod.reset()
for code, n in (("cap.filePages413", 9), ("cap.pages402", 2), ("cap.format415:pdf", 4),
                ("waste.repairReverted", 31), ("provider.rate", 5)):
    main._ev(code, "acme", n)
main.STATE["quotes"] = [
    {"tenant": "acme", "status": "invoiced", "total": 420.0, "currency": "USD"},
    {"tenant": "acme", "status": "paid", "total": 300.0, "currency": "USD"},
]
m = c.get("/api/admin/metrics?days=7", headers=H(S)).json()
hints = {h["code"]: h for h in m["hints"]}
check(hints.get("bigFiles", {}).get("n") == 9, "«файл толще потолка» — с числом")
check([w["tenant"] for w in hints.get("bigFiles", {}).get("who", [])] == ["acme"],
      "подсказка называет организацию, иначе её нечем продать")
check(hints.get("pagesOut", {}).get("n") == 2, "«кончились страницы» — с числом")
check([i["ext"] for i in hints.get("formats", {}).get("items", [])] == ["pdf"],
      "формат, которого у нас нет, назван поимённо")
check(hints.get("waste:repairReverted", {}).get("n") == 31, "сожжённые правки названы")
check(hints.get("invoicedUnpaid", {}).get("n") == 1, "выставленные и неоплаченные сметы видны")
check(m["quotes"]["conversion"] == 0.5, "конверсия считается от ВЫСТАВЛЕННЫХ, а не от всех смет")
check(all(h.get("n") is not None for h in m["hints"]),
      "у каждой подсказки есть число: подсказка без числа — гадание")

print("=== 9б. Суточный текст собирается на сервере ===")
d = c.get("/api/admin/metrics/digest?days=1", headers=H(S)).json()
check(d["ok"] and "9" in d["text"] and "31" in d["text"], "числа доехали до текста")
check("ДЕНЬГИ НА СТОЛЕ" in d["text"] and "ТЕРЯЕМ" in d["text"],
      "разделы идут по деньгам: сначала где взять, потом где теряем")
check("None" not in d["text"] and "%(" not in d["text"],
      "ни одного невыполненного шаблона в тексте: " + d["text"][:120])


print("=== 10. Файловое хранилище подрезается ===")
main.STATE[main.EVENTS_KEY] = {}
old_day = (main.datetime.now() - main.timedelta(days=main.EVENTS_FILE_DAYS + 5)).strftime("%Y-%m-%d")
main._events_file_add([{"day": old_day, "tenant": "acme", "code": "api:GET /x",
                        "n": 1, "ms_sum": 1.0, "ms_max": 1.0, "slow": 0}])
main._events_file_add([{"day": main.metrics_mod.today(), "tenant": "acme", "code": "api:GET /y",
                        "n": 1, "ms_sum": 1.0, "ms_max": 1.0, "slow": 0}])
keys = list(main.STATE[main.EVENTS_KEY])
check(not any(k.startswith(old_day) for k in keys), "старые дни сняты")
check(any(k.startswith(main.metrics_mod.today()) for k in keys), "сегодняшний день на месте")

print("=== 10б. Потолок ключей буфера не роняет процесс ===")
main.metrics_mod.reset()
was = main.metrics_mod.KEYS_MAX
main.metrics_mod.KEYS_MAX = 5
for i in range(40):
    main._ev("api:GET /k%d" % i, "acme")
rows = main.metrics_mod.take()
main.metrics_mod.KEYS_MAX = was
dropped = next((r["n"] for r in rows if r["code"] == "metrics.dropped"), 0)
check(len(rows) <= 6 and dropped >= 30,
      "переполнение буфера названо числом, а не съедено молча: снято %s" % dropped)


print()
if fail:
    print("ПРОВАЛЕНО %d:" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("Всё сошлось")
