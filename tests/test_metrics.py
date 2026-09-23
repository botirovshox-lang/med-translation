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
  9а. ТУПИК считается в месте отказа и обязан иметь вид (деньги/потеря/
     поломка) и фразу — в суточном тексте и на экране. Новая точка отказа
     без них — это код на экране владельца и молчание в сводке, поэтому
     список берётся из самого `main.py`, а не переписывается в тест.
  9б. Парето отмечает меньшинство ВКЛЮЧИТЕЛЬНО: сумма отмеченного обязана
     дотягивать до обещанных 80%, иначе полоса обещает одно, а показывает
     другое.
 10. Файловое хранилище подрезается по дням: `state.json` не вправе расти
     без границы.

Ни одного вызова модели, боевой файл состояния не пишется.
"""
import io
import os
import re
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


print("=== 11. Тупик считается В МЕСТЕ отказа ===")
# Формат выгрузки, которого у нас нет, — это не шум, а план разработки.
# Считаем его там же, где отказываем: по коду ответа (200 с ok: false)
# отличить его от успеха нельзя.
main.metrics_mod.reset()
main.STATE["projects"] = [{"id": 1, "title": "Книга", "tenant": "acme",
                           "src": "RU", "tgt": "EN", "segments": []}]
rx = c.post("/api/projects/1/export", headers=H(O), json={"format": "srt"})
codes = {r["code"]: r for r in main.metrics_mod.take()}
check(rx.status_code == 200 and rx.json().get("ok") is False, "формата нет — отказ словами")
check("dead.exportFormat:srt" in codes, "спрос на формат посчитан: " + str(sorted(codes)))
check(codes.get("dead.exportFormat:srt", {}).get("tenant") == "acme",
      "тупик несёт организацию: без неё его некому продать")
check("funnel.export" in codes, "шаг воронки посчитан там же")

print("=== 11б. Каждый тупик из кода имеет вид и фразу ===")
# Новая точка отказа без вида и без фразы — это код на экране владельца
# и молчание в суточной сводке. Список берётся из САМОГО main.py, а не
# переписывается сюда руками: переписанный разошёлся бы с кодом.
src_main = io.open("backend/main.py", encoding="utf-8").read()
emitted = set(re.findall(r'_ev\("((?:cap|dead)\.[A-Za-z0-9]+)', src_main))
check(emitted, "коды тупиков найдены в исходнике: " + str(len(emitted)))
no_kind = sorted(c0 for c0 in emitted if c0 not in main.BLOCK_KIND)
check(not no_kind, "у каждого тупика есть вид (money/loss/fix): " + str(no_kind))
no_word = sorted(c0 for c0 in main.BLOCK_KIND if c0 not in main.METRICS_BLOCK_TEXT)
check(not no_word, "у каждого тупика есть фраза для суточной сводки: " + str(no_word))
jsx = io.open("frontend/js/tab_admin.jsx", encoding="utf-8").read()
no_ui = sorted(c0 for c0 in main.BLOCK_KIND if ('case "%s":' % c0) not in jsx)
check(not no_ui, "у каждого тупика есть фраза на экране: " + str(no_ui))
check(set(main.BLOCK_KIND.values()) <= {"money", "loss", "fix"},
      "вид тупика — из закрытого набора")

print("=== 11б2. Каждая ПОДСКАЗКА из кода имеет фразу — обе ===")
# У тупиков (`BLOCK_KIND`) сторож был, у подсказок — нет, а дыра там та же:
# забытая строка показывает владельцу голый код на экране и в Telegram.
# Список берётся из САМОГО main.py регуляркой, а не переписывается руками.
hint_codes = set(re.findall(r'\{"kind": "(?:money|loss|fix)", "code": "([A-Za-z0-9]+)"', src_main))
check(hint_codes, "коды подсказок найдены в исходнике: " + str(len(hint_codes)))
no_srv = sorted(c0 for c0 in hint_codes if c0 not in main.METRICS_HINT_TEXT)
check(not no_srv, "у каждой подсказки есть фраза для суточной сводки: " + str(no_srv))
no_jsx = sorted(c0 for c0 in hint_codes if ('case "%s":' % c0) not in jsx)
check(not no_jsx, "у каждой подсказки есть фраза на экране: " + str(no_jsx))

print("=== 11б3. Затраты на РАЗБОР принесённых файлов ===")
# Шаг сметы скана отделён от чтения картинок: это деньги ДО заказа,
# за файл, который могут и не принести.
check(main.USAGE_STEP_GROUP.get("scanquote") == "ocr",
      "смета скана пересчитывается вместе с ocr, а не выпадает из пересчёта")
check('_note_usage("scanquote"' in src_main, "смета скана пишется своим шагом")
check('case "scanquote":' in jsx or "scanquote:" in jsx, "у шага есть подпись на экране")

# Удаление файла — шаг воронки ВНИЗ, и считается в общей точке обеих дорог
# (удаление файла и удаление папки), иначе половина удалений пропала бы.
import inspect                                                # noqa: E402
check('_ev("funnel.deleted"' in inspect.getsource(main._delete_project_record),
      "удаление считается в _delete_project_record — общей точке обеих дорог")

# Организация у шага воронки: без неё подсказка не называет клиента.
def _r(code, n, tenant="acme"):
    return {"day": main.metrics_mod.today(), "tenant": tenant, "code": code,
            "n": n, "ms_sum": 0.0, "ms_max": 0.0, "slow": 0}


ev2 = main._metrics_events([
    _r("funnel.upload:pdf", 4, "acme"), _r("funnel.deleted", 4, "acme"),
    _r("funnel.upload:pdf", 9, "bobco"), _r("funnel.run:full", 3, "bobco")])
check(ev2.get("funnelByTenant", {}).get("acme", {}).get("upload:pdf") == 4,
      "шаг воронки несёт организацию")
check(ev2["funnel"]["deleted"] == 4 if "funnel" in ev2 else
      ev2["funnelRaw"]["deleted"] == 4, "удаления сосчитаны")
hints = main._metrics_hints(7, [{"id": "acme", "name": "ACME", "spendUsd": 0, "runs": 0},
                                {"id": "bobco", "name": "BOBCO", "spendUsd": 0, "runs": 0}],
                            ev2, {})
by_code = {(h["code"], h.get("tenant")) for h in hints}
check(("uploadChurn", "acme") in by_code, "принёс и удалил — названо с организацией")
# Две строки об одном клиенте в одном столбце `loss` читаются как две
# разные беды, а «принёс и не запустил» + «принёс и удалил» — самый
# частый расклад одного и того же. Отток говорит больше (в нём и
# принесённое, и удалённое), поэтому вторая строка не ставится.
check(("uploadNoRun", "acme") not in by_code,
      "при оттоке вторая строка про того же клиента не дублируется")
check(("uploadNoRun", "bobco") not in by_code, "кто запускал прогоны — не в списке")
# А без оттока «принёс и не запустил» обязано быть названо.
ev4 = main._metrics_events([_r("funnel.upload:pdf", 5, "quiet")])
h4 = {(h["code"], h.get("tenant")) for h in
      main._metrics_hints(7, [{"id": "quiet", "name": "Q", "spendUsd": 0, "runs": 0}], ev4, {})}
check(("uploadNoRun", "quiet") in h4, "принёс и не запустил — названо, когда оттока нет")
# Один файл без прогона — норма первого дня, а не схема.
ev3 = main._metrics_events([_r("funnel.upload:pdf", 1, "solo")])
check(not [h for h in main._metrics_hints(7, [{"id": "solo", "name": "S", "spendUsd": 0, "runs": 0}], ev3, {})
           if h["code"] == "uploadNoRun"], "один файл без прогона подсказки не рождает")

print("=== 11в. Парето: доли, накопленная и «жизненно важное меньшинство» ===")
day = main.metrics_mod.today()


def row(code, n, tenant="acme"):
    return {"day": day, "tenant": tenant, "code": code, "n": n,
            "ms_sum": 0.0, "ms_max": 0.0, "slow": 0}


ev = main._metrics_events([
    row("cap.filePages413", 80), row("cap.format415:pdf", 12),
    row("cap.format415:epub", 3), row("dead.writeback:odt", 4, "beta"),
    row("dead.scan", 1),
    row("funnel.upload:pdf", 10), row("funnel.upload:docx", 5),
    row("funnel.run:full", 9), row("funnel.export", 4),
    row("err:413 POST /projects/upload", 5),
    row("err:404 GET /projects/{pid}", 1),
])
blocked = main._blocked_rows(ev)
by = {b["code"]: b for b in blocked}
check(by["cap.format415"]["n"] == 15,
      "улики собраны в ОДНУ работу: формат — это одна строка, а pdf и epub — доводы к ней")
check([i["name"] for i in by["cap.format415"]["items"]] == ["pdf", "epub"],
      "улики названы поимённо и по убыванию")
check(by["dead.writeback"]["who"][0]["tenant"] == "beta", "тупик знает, кто в него упёрся")
check(abs(sum(b["share"] for b in blocked) - 1.0) < 1e-6, "доли складываются в единицу")
check(blocked[-1]["cum"] == 1.0, "накопленная доля доходит до единицы")
check(sum(b["share"] for b in blocked if b["vital"]) >= main.PARETO_SHARE,
      "отмеченное меньшинство ДЕЙСТВИТЕЛЬНО даёт обещанные 80%: "
      "строка, пересёкшая порог, входит в него")
check([b["code"] for b in blocked] == sorted(
      [b["code"] for b in blocked], key=lambda k: (-by[k]["n"], k)),
      "порядок устойчив: при равных числах строки не прыгают между обновлениями")
check(by["cap.filePages413"]["kind"] == "money" and by["dead.scan"]["kind"] == "money",
      "спрос помечен деньгами, а не поломкой")

print("=== 11г. Отказ разобран на «что делал» и «почему не вышло» ===")
errs = {e["route"]: e for e in main._metrics_errors(ev)}
check(errs["POST /projects/upload"]["act"] == "upload" and
      errs["POST /projects/upload"]["status"] == 413,
      "маршрут переведён в действие человека: " + str(errs["POST /projects/upload"]))
check(errs["GET /projects/{pid}"]["act"] == "project", "общее правило маршрута работает")
check(main._act_of("POST /projects/{pid}/images/read") == "images",
      "частное правило сильнее общего: иначе всё стало бы «проектом»")

print("=== 11д. Воронка: не когорта, но вопрос денежный ===")
f = main._funnel_view(ev.get("funnelRaw") or {})
steps = {s["code"]: s["n"] for s in f["steps"]}
check(steps == {"upload": 15, "run": 9, "export": 4}, "шаги сложены: " + str(steps))
check(f["dropRun"] == 6 and f["dropExport"] == 5, "потери между шагами названы числом")
check(f["conv"] == round(4 / 15, 3), "доля дошедших до выгрузки посчитана")
check([x["name"] for x in f["byExt"]] == ["pdf", "docx"], "видно, какой формат нам несут")
check(main._funnel_view({})["conv"] is None,
      "нет загрузок — доля НЕ НОЛЬ, а «не знаю»: ноль читался бы как «никто не дошёл»")

print("=== 11е. Дверь «Возможности» ===")
r403 = c.get("/api/admin/opportunities", headers=H(O))
check(r403.status_code == 403, "клиенту метрики не отдаются")
main.metrics_mod.reset()
main.STATE[main.EVENTS_KEY] = {}
main._events_file_add([row("cap.filePages413", 9), row("funnel.upload:pdf", 3)])
full = c.get("/api/admin/opportunities?days=7", headers=H(S)).json()
lite = c.get("/api/admin/opportunities?days=7&live=1", headers=H(S)).json()
check(full["ok"] and full["blocked"] and full["blocked"][0]["n"] == 9,
      "тупики доехали до двери")
check(full["money"] is not None and lite["money"] is None,
      "лёгкая дверь организации НЕ обходит: воркер один, а экран опрашивается")
check(lite["blocked"] == full["blocked"], "счётчики у обеих дверей одни и те же")
check(full["at"] and full["live"] is False and lite["live"] is True,
      "ответ говорит, живой он или полный, и когда посчитан")
check(all("|" not in json.dumps(b, ensure_ascii=False) for b in full["blocked"]),
      "наружу уходят разобранные коды, а не ключи хранилища")

print("=== 11ж. Тупики и воронка попали в суточный текст ===")
d2 = c.get("/api/admin/metrics/digest?days=1", headers=H(S)).json()
check("ТУПИКИ" in d2["text"], "раздел тупиков есть: " + d2["text"][:80])
check("Воронка за период" in d2["text"], "воронка названа словами")
check("cap.filePages413" not in d2["text"], "в тексте фраза, а не код события")
check("None" not in d2["text"] and "%(" not in d2["text"],
      "ни одного невыполненного шаблона: " + d2["text"][:160])


print()
if fail:
    print("ПРОВАЛЕНО %d:" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("Всё сошлось")
