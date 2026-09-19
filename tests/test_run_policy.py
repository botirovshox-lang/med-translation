"""Деньги и строки: что покупается, что нет, и кто пишет проект во время прогона.

Раздел за разделом — правки «анти-фрода» и учёта:
  1. стёртый перевод снова ждёт перевода (`_needs_translation`, `update_segment`,
     `/confirm`, `/qa`), а ответ правки несёт свежий `stale` проверок;
  2. перевод ЗАНОВО ограничен: счётчик строки, предел организации (409 у одной
     строки, пропуск поимённо у пакета), перевод заново всего файла — в квоте;
  3. проверки на паре без правил обратный перевод не покупают и помечают текст;
  4. факт расхода ложится на проект (запрос — из пути, потоки пула — из задачи),
     админка «Прогоны» отдаёт итог по проекту и живые прогоны;
  5. текст с картинок списывается один раз: снятие и удаление страниц не
     возвращают, повторный разбор не списывает второй раз;
  6. повторный импорт: тот же файл — ноль, изменённый — только добавленное,
     «A → B → снова A» платит за вернувшиеся строки;
  7. мутирующие команды проекта во время прогона внешнего воркера — 409;
  8. счёт карточек терминов на «Проверке» — только свой проект и общие.
Ни одного настоящего вызова модели: перевод и судья подменены.
"""
import io, os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["spend"] = [], [], {}
main.STATE["projects"] = []
main.STATE.pop(main.PROJECT_SPEND_KEY, None)
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "acme", "name": "ACME", "ownerLogin": "acme", "ownerPassword": "acme-pass-123"})
B = c.post("/api/auth/login", json={"login": "acme", "password": "acme-pass-123"}).json()["token"]


def new_project(src="RU", tgt="EN", n=0, translated=True, title="p"):
    pid = c.post("/api/projects", headers=H(B), json={"title": title, "src": src, "tgt": tgt}).json()["id"]
    p = next(p for p in main.STATE["projects"] if p["id"] == pid)
    for i in range(1, n + 1):
        p["segments"].append({"id": i, "source": "Строка номер %d про лечение." % i,
                              "target": ("Line %d about treatment." % i) if translated else "",
                              "status": "translated" if translated else "new",
                              "route": "GPT_REQUIRED", "risk": "low", "comments": [], "qa": []})
    return pid, p


calls = []
orig_translate = main._openai_translate


def fake_translate(text, *a, **k):
    calls.append((text, k.get("step")))
    return "EN: " + text


main._openai_translate = fake_translate

print("=== 1. Стёртый перевод снова ждёт перевода ===")
pid, p = new_project(n=3)
seg = p["segments"][0]
seg["backcheck"] = {"score": 90, "target_hash": main._text_hash(seg["target"].strip())}
r = c.post("/api/segments/%d/1/update" % pid, headers=H(B), json={"target": "", "status": "translated"})
check(r.status_code == 200 and seg["status"] == "new", "стёрли текст — статус new, как бы браузер его ни назвал")
check(r.json()["segment"]["backcheck"]["stale"] is True, "ответ правки несёт свежий stale проверки")
r = c.post("/api/segments/%d/2/update" % pid, headers=H(B), json={"target": "Line 2 about treatment."})
check(r.json()["segment"].get("backcheck") is None and r.json()["segment"]["status"] == "translated",
      "непустая правка статус не трогает")
legacy = {"status": "qa", "target": "  "}
check(main._needs_translation(legacy), "старые данные: пустой текст со статусом qa — ждёт перевода (без миграции)")
check(not main._needs_translation({"status": "confirmed", "target": ""}), "заверенный пустой машина не берёт")
check(not main._needs_translation({"status": "translated", "target": "x"}), "переведённый — не берёт")
r = c.post("/api/segments/%d/1/confirm" % pid, headers=H(B))
check(r.status_code == 400 and seg["status"] == "new", "заверить пустоту нельзя → 400")
r = c.post("/api/segments/%d/1/qa" % pid, headers=H(B))
check(r.status_code == 200 and r.json().get("skipped") == "empty" and seg["status"] == "new",
      "локальная проверка пустого текста статус qa не ставит")
p["segments"][2]["status"] = "confirmed"
r = c.post("/api/segments/%d/3/qa" % pid, headers=H(B))
check(p["segments"][2]["status"] == "confirmed", "проверка заверенное не понижает")
r = c.post("/api/projects/%d/batch" % pid, headers=H(B), json={"limit": 10})
check(r.status_code == 200 and 1 in r.json()["translated"], "пакет без force берёт стёртую строку")

print("=== 2. Перевод заново — в пределах организации ===")
calls.clear()
seg2 = p["segments"][1]
seg2.pop("retranslations", None)
for i in range(main.RETRANSLATE_LIMIT):
    r = c.post("/api/segments/%d/2/translate" % pid, headers=H(B), json={"force": True})
check(r.status_code == 200 and seg2.get("retranslations") == main.RETRANSLATE_LIMIT,
      "счётчик растёт на каждом переводе поверх текста: %s" % seg2.get("retranslations"))
n_calls = len(calls)
r = c.post("/api/segments/%d/2/translate" % pid, headers=H(B), json={"force": True})
check(r.status_code == 409 and "предел" in r.json().get("detail", "") and len(calls) == n_calls,
      "выше предела — 409 словами, модель не звалась: %s" % r.text[:120])
seg1 = p["segments"][0]
seg1.update({"target": "", "status": "new"}); seg1.pop("retranslations", None)
r = c.post("/api/segments/%d/1/translate" % pid, headers=H(B), json={"force": True})
check(r.status_code == 200 and not seg1.get("retranslations"), "первый перевод пустой строки — не «заново»")
r = c.post("/api/projects/%d/batch" % pid, headers=H(B), json={"segment_ids": [1, 2], "force": True})
check(r.status_code == 200 and r.json()["skipped_limit"] == [2] and 1 in r.json()["translated"],
      "пакет пропускает строку выше предела поимённо, остальные переводит: %s" % r.json().get("skipped_limit"))
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"retranslateLimit": 0})
check(r.status_code == 200 and r.json()["tenant"]["retranslateLimit"] == 0, "предел ставит суперпользователь")
r = c.post("/api/segments/%d/1/translate" % pid, headers=H(B), json={"force": True})
check(r.status_code == 409 and "выключен" in r.json().get("detail", ""), "0 — перевод заново запрещён")
r = c.post("/api/admin/tenants/acme", headers=H(B), json={"retranslateLimit": 99})
check(r.status_code == 403, "владелец себе предел не поднимает")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"retranslateLimit": -1})
check(r.status_code == 400, "отрицательный предел → 400")
tok = main.CURRENT_SESSION.set({"tenant": "acme", "user": 1, "super": True})
try:
    check(main._retranslate_limit() is None, "суперпользователь предела не имеет")
finally:
    main.CURRENT_SESSION.reset(tok)
main._JOB_USER.id = next(u["id"] for u in main._users() if u.get("login") == "acme")
check(main._retranslate_limit("acme") == 0, "прогон читает предел по тому, кто его ставил")
main._JOB_USER.id = None
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"clearRetranslate": True})
check("retranslateLimit" not in r.json()["tenant"], "снятие — снова умолчание сервиса")

print("=== 2b. Перевод заново всего файла — в квоте ===")
ew = main.EXTERNAL_WORKER
main.EXTERNAL_WORKER = True                     # задачу никто не подхватит
bpid, bp = new_project(n=30, title="bulk")
ids = list(range(1, 31))
r = c.post("/api/projects/%d/jobs" % bpid, headers=H(B), json={"kind": "translate", "segment_ids": ids, "params": {}})
check(r.status_code == 200, "первый перевод заново всего файла — в квоте: %s" % r.text[:120])
if r.status_code == 200:
    main._JOBS.pop(r.json()["job"]["id"], None)
r = c.post("/api/projects/%d/jobs" % bpid, headers=H(B), json={"kind": "translate", "segment_ids": ids, "params": {}})
check(r.status_code == 409 and "целиком" in r.json().get("detail", ""), "второй — 409: %s" % r.text[:120])
r = c.post("/api/projects/%d/jobs" % bpid, headers=H(B), json={"kind": "translate", "segment_ids": ids[:5], "params": {}})
check(r.status_code == 200, "несколько строк — не «весь файл», квоту не тратит")
if r.status_code == 200:
    main._JOBS.pop(r.json()["job"]["id"], None)
row = next(x for x in main._proj_spend_rows("acme") if x["project"] == bpid)
check(row["bulk"] == 1 and row["runs"] == 2, "счётчики файла в хранилище: весь файл 1, прогонов 2: %s" % row)
main.EXTERNAL_WORKER = ew

print("=== 3. Проверки на паре без правил обратный перевод не покупают ===")
upid, up_ = new_project("RU", "UZ", n=1, title="uz")
check(not main._checks_buy_back(up_), "RU→UZ: правил пары и маркеров отрицания цели нет")
check(main._checks_buy_back(p), "RU→EN: маркеры отрицания обеих сторон есть — покупаем")
calls.clear()
tok = main.CURRENT_SESSION.set({"tenant": "acme", "user": 2, "role": "owner"})
try:
    res = main._segment_checks(upid, 1)
finally:
    main.CURRENT_SESSION.reset(tok)
qa = up_["segments"][0]["qa_result"]
check(res["ok"] and not calls, "обратный перевод не куплен")
check(qa.get("target_hash") == main._text_hash(up_["segments"][0]["target"].strip())
      and qa.get("backcheckSkipped") == "pair", "отметка текста стоит — шаг не вернётся в следующий прогон")
tok = main.CURRENT_SESSION.set({"tenant": "acme", "user": 2, "role": "owner"})
try:
    plan = main._plan_step(up_, "medical_qa", {}, up_["segments"], set(), set())
finally:
    main.CURRENT_SESSION.reset(tok)
check(plan["model"] is None and plan["count"] == 0, "разбор состава: модели нет, строка не берётся: %s" % plan)

print("=== 4. Факт расхода — по проекту ===")


class _Resp:
    usage = {"prompt_tokens": 1000, "completion_tokens": 500}


def translate_paid(text, *a, **k):
    main._note_usage("translate", "gpt-4o", _Resp())
    return "EN: " + text


main._openai_translate = translate_paid
spid, sp = new_project(n=1, translated=False, title="Учебник")
r = c.post("/api/segments/%d/1/translate" % spid, headers=H(B), json={})
row = next((x for x in main._proj_spend_rows("acme") if x["project"] == spid), None)
check(r.status_code == 200 and row and row["calls"] == 1 and row["usd"] > 0,
      "одиночная кнопка: расход лёг на проект из пути запроса: %s" % row)
main._openai_translate = fake_translate
rw = main.RUN_WORKERS
main.RUN_WORKERS = 4
ptok = main._USAGE_PROJECT.set(spid)
try:
    got = main._run_parallel([1, 2, 3], lambda x: main._usage_project())
finally:
    main._USAGE_PROJECT.reset(ptok)
    main.RUN_WORKERS = rw
check(got == [spid] * 3, "потоки пула знают проект запроса: %s" % got)
main.STATE.setdefault("runCosts", []).append({"job": 5, "kind": "full", "project": spid, "tenant": "acme",
                                              "status": "done", "finished": "2026-09-19 10:00",
                                              "segments": 1, "est": 0.5, "cost": 0.25, "calls": 3})
main._JOBS[4242] = {"id": 4242, "kind": "full", "project": spid, "tenant": "acme", "status": "running",
                    "done": 1, "total": 5, "params": {"est_cost": 0.4}, "usage": {"cost": 0.1234, "calls": 2}}
try:
    j = c.get("/api/admin/runs?all=1", headers=H(A)).json()
finally:
    main._JOBS.pop(4242, None)
bp_ = next((x for x in j.get("byProject", []) if x["project"] == spid), None)
check(bp_ and bp_["projectName"] == "Учебник" and bp_["usd"] > 0, "итог по проекту с именем: %s" % bp_)
check(any(r_["job"] == 5 and r_["projectName"] == "Учебник" for r_ in j["runs"]), "строка прогона названа проектом")
check(any(l["job"] == 4242 and l["cost"] == 0.1234 for l in j.get("live", [])), "идущий прогон — живым счётчиком")
jb = c.get("/api/admin/runs", headers=H(B)).json()
check(all(x["tenant"] == "acme" for x in jb.get("byProject", [])), "владелец видит только свою организацию")

print("=== 5. Текст с картинок списывается один раз ===")
c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": 100})
rec = lambda: next(t for t in main.STATE["tenants"] if t["id"] == "acme")
ipid, ip = new_project(n=1, title="скан")
ip["pages"] = 1.0
words = " ".join(["слово"] * 250)
ip["segments"].append(main._image_new_segment(words, "word/media/image1.png", 0, 2))
u0 = main._tenant_usage("acme")
used0 = rec()["pagesUsed"]
check(u0["imagePages"] >= 0.9, "прочитанное, но не списанное — видно отдельно: %s" % u0)
c.get("/api/projects/%d" % ipid, headers=H(B))
u1 = main._tenant_usage("acme")
check(rec()["pagesUsed"] > used0 + 0.9 and u1["imagePages"] == 0 and abs(u1["pages"] - u0["pages"]) < 0.11,
      "показ проекта списал — и объём не задвоился: %s → %s" % (u0, u1))
used1 = rec()["pagesUsed"]
r = c.post("/api/projects/%d/images/forget" % ipid, headers=H(B), json={"force": True})
check(r.status_code == 200 and rec()["pagesUsed"] == used1 and main._tenant_usage("acme")["pages"] >= u1["pages"] - 0.11,
      "снятие строк картинок страниц не возвращает")
ip["segments"].append(main._image_new_segment(words, "word/media/image1.png", 0, 3))
c.get("/api/projects/%d" % ipid, headers=H(B))
check(rec()["pagesUsed"] == used1, "тот же текст заведён заново — второй раз не списан")
ip["segments"].append(main._image_new_segment(words + " ещё", "word/media/image2.png", 0, 4))
r = c.request("DELETE", "/api/projects/%d" % ipid, headers=H(B))
check(r.status_code == 200 and rec()["pagesUsed"] > used1 + 0.9,
      "непоказанное прочитанное списано ДО удаления, удаление ничего не вернуло")

print("=== 6. Повторный импорт: платим за добавленное к нынешнему файлу ===")
try:
    from docx import Document
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_of(paras):
    d = Document()
    for t in paras:
        d.add_paragraph(t)
    b = io.BytesIO(); d.save(b); return b.getvalue()


if HAVE_DOCX:
    base = ["Первый абзац про туберкулёз лёгких и его лечение в стационаре.",
            "Второй абзац про профилактику и вакцинацию детей в школах.",
            "Третий абзац про диагностику и рентгенографию грудной клетки.",
            "Четвёртый абзац про наблюдение после выписки из больницы."]
    fa = docx_of(base)
    fb = docx_of(base[:2] + ["Совсем новый третий абзац про другое лечение и режим."] + base[3:])
    r = c.post("/api/projects/upload", headers=H(B), files={"file": ("a.docx", fa, MIME)},
               data={"src": "RU", "tgt": "EN"})
    check(r.status_code == 200, "файл загружен: %s" % r.text[:100])
    rp = r.json()["id"]
    reimp = lambda raw: c.post("/api/projects/%d/reimport" % rp, headers=H(B),
                               files={"file": ("a.docx", raw, MIME)}, data={"dry_run": "false"})
    u_a = rec()["pagesUsed"]
    r = reimp(fa)
    check(r.status_code == 200 and rec()["pagesUsed"] == u_a, "тот же файл — ноль: %s" % r.text[:100])
    r = reimp(fb)
    u_b = rec()["pagesUsed"]
    check(r.status_code == 200 and u_a < u_b < u_a + 0.1, "изменённый — только за новую строку: +%.3f" % (u_b - u_a))
    r = reimp(fa)
    check(r.status_code == 200 and rec()["pagesUsed"] > u_b,
          "«A → B → снова A»: вернувшаяся строка оплачена, хотя sha A уже видели")
    rpj = next(x for x in main.STATE["projects"] if x["id"] == rp)
    kept = rpj["segments"][0]
    kept["target"] = "Translated first"
    tampered = dict(kept, source="Совсем другой текст под тем же номером")
    # Страж на будущие правки дифа: совпавший сегмент с иным текстом — другая строка.
    orig_diff = main._diff_units
    main._diff_units = lambda project, units, full=None: (
        [("keep", tampered)] + [("new", None)] * (len(units) - 1), [])
    rpj["segments"][0] = tampered
    try:
        r = reimp(fa)
    finally:
        main._diff_units = orig_diff
    check(r.status_code == 200 and tampered["target"] == "" and tampered["status"] == "new"
          and tampered.get("prevTarget") == "Translated first" and tampered["source"] == base[0],
          "совпавший по номеру, но иной текст — сброшен в new, прежний перевод в prevTarget")
    c.request("DELETE", "/api/projects/%d" % rp, headers=H(B))
else:
    print("python-docx нет — раздел 6 пропущен")

print("=== 7. Во время прогона внешнего воркера проект не правится ===")
gpid, gp = new_project(n=2, title="guard")
gp["segments"].append(main._image_new_segment("надпись", "word/media/image1.png", 0, 3))
main.EXTERNAL_WORKER = True
main._JOBS[9191] = {"id": 9191, "kind": "full", "project": gpid, "status": "running", "tenant": "acme"}
try:
    blocked = [
        ("/api/segments/%d/1/qa" % gpid, {}),
        ("/api/segments/%d/1/termcheck" % gpid, {}),
        ("/api/segments/%d/1/backcheck" % gpid, {}),
        ("/api/projects/%d/termcheck/batch" % gpid, {}),
        ("/api/projects/%d/backcheck/batch" % gpid, {}),
        ("/api/projects/%d/repair/batch" % gpid, {}),
        ("/api/projects/%d/checks/batch" % gpid, {}),
        ("/api/projects/%d/batch" % gpid, {}),
        ("/api/projects/%d/extract-terms" % gpid, {}),
        ("/api/projects/%d/term-context" % gpid, {}),
        ("/api/projects/%d/review/apply" % gpid, {}),
        ("/api/projects/%d/domain" % gpid, {"domain": "general"}),
        ("/api/projects/%d/images/restore" % gpid, {"part": "x", "block": 0}),
        ("/api/projects/%d/images/forget" % gpid, {}),
        ("/api/projects/%d/images/3/overlay" % gpid, {}),
    ]
    for path, body in blocked:
        r = c.post(path, headers=H(B), json=body)
        check(r.status_code == 409, "%s → 409 (%d)" % (path, r.status_code))
    r = c.request("DELETE", "/api/projects/%d" % gpid, headers=H(B))
    check(r.status_code == 409, "удаление файла во время прогона → 409")
    r = c.post("/api/projects/%d/source" % gpid, headers=H(B), files={"file": ("x.docx", b"x", MIME)})
    check(r.status_code == 409, "привязка исходника → 409")
    gp["segments"][0].pop("risk", None)
    r = c.post("/api/projects/%d/preflight" % gpid, headers=H(B))
    check(r.status_code == 200 and "risk" not in gp["segments"][0], "отчёт открывается, но документ не пишет")
finally:
    main._JOBS.pop(9191, None)
    main.EXTERNAL_WORKER = ew

print("=== 8. «Проверка» считает карточки своего проекта и общие ===")
p1, pp1 = new_project(n=1, title="one")
p2, pp2 = new_project(n=1, title="two")
sc = main._project_scope(pp1)
q = main.STATE.setdefault("termQueue", [])
mk = lambda cid, proj: {"id": cid, "kind": "extract", "src": "т%d" % cid, "tgt": "t%d" % cid,
                        "status": "pending", "lang": sc[0], "domain": sc[1], "tenant": "acme",
                        **({"project": proj} if proj is not None else {})}
q.extend([mk(70001, p1), mk(70002, p2), mk(70003, None)])
try:
    r = c.post("/api/term-queue/auto-approve", headers=H(B), json={"dry_run": True, "project": p1})
    check(r.status_code == 200 and r.json()["counts"]["queueTotal"] == 2,
          "кнопка с проектом раскладывает свой и общий, чужой проект мимо: %s" % r.json().get("counts"))
    tok = main.CURRENT_SESSION.set({"tenant": "acme", "user": 2, "role": "owner"})
    orig_v = main._auto_verdict
    seen = []
    main._auto_verdict = lambda cand, ctx: (seen.append(cand["id"]) or ("auto", "тест"))
    try:
        main.project_analysis(p1, refresh=True)
    finally:
        main._auto_verdict = orig_v
        main.CURRENT_SESSION.reset(tok)
    check(70002 not in seen and 70001 in seen and 70003 in seen,
          "разбор «Проверки» чужой проект не считает: %s" % sorted(i for i in seen if i >= 70000))
finally:
    main.STATE["termQueue"] = [x for x in q if x.get("id") not in (70001, 70002, 70003)]

main._openai_translate = orig_translate
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
