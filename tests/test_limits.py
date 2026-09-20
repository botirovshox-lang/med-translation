"""Лимит расхода по организации: 402 на платное, бесплатное работает.

Факт расхода складывается по организации и месяцу (`_spend_add` из
`_note_usage`), лимит ставит суперпользователь. На исчерпанном лимите
платные команды отвечают 402 с остатком, а правка начертания, откаты,
пересчёт back-check, принятие кандидатов, разбор состава и экспорт —
работают: лимит режет деньги, а не доступ к оплаченному. Ни одного
вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["spend"] = [], [], {}
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
pid = c.post("/api/projects", headers=H(B), json={"title": "p", "src": "RU", "tgt": "EN"}).json()["id"]
proj = next(p for p in main.STATE["projects"] if p["id"] == pid)
proj["segments"].append({"id": 1, "source": "Тест.", "target": "", "status": "new",
                         "route": "GPT_REQUIRED", "risk": "low", "comments": [], "qa": []})


class _Resp:
    usage = {"prompt_tokens": 1000, "completion_tokens": 500}


print("=== 1. Расход складывается по организации и месяцу ===")
tok = main.CURRENT_SESSION.set({"tenant": "acme", "user": 2, "role": "owner"})
try:
    main._note_usage("translate", "gpt-4o", _Resp())
    main._note_usage("translate", "no-such-model", _Resp())
finally:
    main.CURRENT_SESSION.reset(tok)
st = main._spend_status("acme")
check(st["calls"] == 2 and st["unpriced"] == 1 and st["spentUsd"] > 0, "две записи, одна без цены, сумма > 0: %s" % st)
check(main._spend_status("default")["calls"] == 0, "у другой организации — ноль")
me = c.get("/api/auth/me", headers=H(B)).json()
check(me["spend"]["tenant"] == "acme" and me["spend"]["limitUsd"] is None and not me["spend"]["over"],
      "/auth/me показывает расход, лимита нет")

print("=== 2. Лимит ставит только super ===")
r = c.post("/api/admin/tenants/acme", headers=H(B), json={"limitUsd": 100})
check(r.status_code == 403, "владелец сам себе лимит не ставит")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"limitUsd": 0.001})
check(r.status_code == 200 and r.json()["spend"]["over"], "super поставил лимит ниже расхода — over")
r = c.get("/api/admin/tenants", headers=H(A))
check(r.status_code == 200 and any(t["id"] == "acme" and t["spend"]["over"] for t in r.json()["tenants"]),
      "список организаций с расходом")

print("=== 3. На исчерпанном лимите: платное — 402, бесплатное — работает ===")
paid = [("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "ids": [1]}),
        ("POST", "/api/segments/%d/1/translate" % pid, {}),
        ("POST", "/api/segments/%d/1/backcheck" % pid, {}),
        ("POST", "/api/projects/%d/batch" % pid, {}),
        # Ремонт и проверки пачкой зовут модель (ремонт; обратный перевод
        # проверок) — прежде `_PAID` их не знал, и лимит обходился ими.
        ("POST", "/api/projects/%d/repair/batch" % pid, {}),
        ("POST", "/api/glossary/audit", {})]
for m, path, body in paid:
    r = c.request(m, path, headers=H(B), json=body)
    check(r.status_code == 402 and "spend" in r.json(), "%s → 402" % path)
# Проверки пачкой платны ТОЛЬКО обратным переводом: 402 — когда порция его
# купит, а без покупки (нечего проверять / обратный перевод к тексту готов)
# они работают и на исчерпанном лимите.
for path in ("/api/projects/%d/checks/batch" % pid, "/api/projects/%d/medical-qa/batch" % pid):
    r = c.post(path, headers=H(B), json={})
    check(r.status_code != 402, "%s без переведённых строк — бесплатно, не 402 (%d)" % (path, r.status_code))
seg1 = proj["segments"][0]
seg1.update({"target": "Test.", "status": "translated"})
if main.checks_mod and main.checks_enabled() and main._checks_buy_back(proj):
    for path in ("/api/projects/%d/checks/batch" % pid, "/api/projects/%d/medical-qa/batch" % pid):
        r = c.post(path, headers=H(B), json={})
        check(r.status_code == 402 and "spend" in r.json(), "%s купит обратный перевод → 402" % path)
    seg1["backcheck"] = {"back": "Тест.", "target_hash": main._text_hash("Test.")}
    r = c.post("/api/projects/%d/checks/batch" % pid, headers=H(B), json={})
    check(r.status_code == 200, "обратный перевод к тексту готов — проверки идут на исчерпанном лимите: %d" % r.status_code)
seg1.update({"target": "", "status": "new"})
for k in ("backcheck", "qa_result", "qa_issues", "qa", "term_candidates", "risk_score", "risk_color",
          "engine_qa", "medical_qa_enabled", "backtranslated_ru"):
    seg1.pop(k, None)
seg1["qa"] = []
free = [("POST", "/api/projects/%d/run-plan" % pid, {"steps": ["translate"]}),
        ("POST", "/api/projects/%d/term-case" % pid, {}),
        ("POST", "/api/projects/%d/backcheck/rescore" % pid, {}),
        ("POST", "/api/projects/%d/repair/accept-batch" % pid, {}),
        ("POST", "/api/glossary/revert-repairs", {"src": "x", "tgt": "y"}),
        ("GET", "/api/projects/%d/analysis" % pid, None),
        ("GET", "/api/projects/%d/coverage" % pid, None),
        ("POST", "/api/projects/%d/export" % pid, {"format": "xlsx"})]
for m, path, body in free:
    r = c.request(m, path, headers=H(B), **({"json": body} if body is not None else {}))
    check(r.status_code != 402, "%s → не 402 (%d)" % (path, r.status_code))

# Судья у одобрения и автоодобрения: путь бесплатный (принятие кандидатов
# работает на исчерпанном лимите), платность — по телу. Одобрение идёт без
# сверки с пометкой, автоодобрение со сверкой — 402, без сверки — работает.
judge_calls = []
orig_meaning, orig_verdict = main._openai_meaning, main._auto_verdict
main._openai_meaning = lambda *a, **k: judge_calls.append(a) or {}
main._auto_verdict = lambda cand, ctx: ("auto", "тест")
_sc = main._project_scope(proj)
cand = {"id": 90001, "kind": "extract", "src": "лимит", "tgt": "limit", "status": "pending",
        "lang": _sc[0], "domain": _sc[1], "tenant": "acme", "project": pid}
main.STATE.setdefault("termQueue", []).append(cand)
try:
    r = c.post("/api/term-queue/auto-approve", headers=H(B),
               json={"dry_run": True, "meaning": True, "project": pid})
    check(r.status_code == 402 and "spend" in r.json() and not judge_calls,
          "автоодобрение со сверкой судьёй на исчерпанном лимите → 402, судья не звался: %d" % r.status_code)
    r = c.post("/api/term-queue/auto-approve", headers=H(B),
               json={"dry_run": True, "meaning": False, "project": pid})
    check(r.status_code == 200, "автоодобрение без сверки — работает: %d" % r.status_code)
    r = c.post("/api/term-queue/90001/approve", headers=H(B), json={})
    check(r.status_code == 200 and r.json().get("written") and r.json().get("meaningSkipped") == "limit"
          and not judge_calls, "одобрение человеком на исчерпанном лимите — без судьи, пропуск назван: %s" % r.text[:160])
finally:
    main._openai_meaning, main._auto_verdict = orig_meaning, orig_verdict
    main.STATE["termQueue"] = [c_ for c_ in main.STATE["termQueue"] if c_.get("id") != 90001]
    main.STATE["glossary"] = [g for g in main.STATE.get("glossary") or [] if g.get("src") != "лимит"]

print("=== 4. Снятие лимита ===")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"clearLimit": True})
check(r.status_code == 200 and not r.json()["spend"]["over"], "лимит снят")
r = c.post("/api/segments/%d/1/backcheck" % pid, headers=H(B), json={})
check(r.status_code != 402, "платное снова доступно")
seed = c.get("/api/seed", headers=H(B)).json()
check("spend" not in seed, "/api/seed расход по организациям не отдаёт")

print("=== 5. Смета больше остатка — 402 на старте (число клиентское, рубеж от случайности) ===")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"limitUsd": 1.0})
check(r.status_code == 200 and not r.json()["spend"]["over"], "лимит $1, расход меньше")
body = {"kind": "backcheck", "segment_ids": [1], "params": {"est_cost": 5.0}}
r = c.post("/api/projects/%d/jobs" % pid, headers=H(B), json=body)
check(r.status_code == 402 and "Смета прогона" in r.json().get("detail", ""),
      "смета $5 больше остатка → 402: %s" % r.text[:120])
ew = main.EXTERNAL_WORKER
main.EXTERNAL_WORKER = True                      # задачу никто не подхватит — без сети
body["params"]["est_cost"] = 0.01
r = c.post("/api/projects/%d/jobs" % pid, headers=H(B), json=body)
main.EXTERNAL_WORKER = ew
check(r.status_code == 200, "смета в остаток → задача принята: %s" % r.text[:120])
if r.status_code == 200:
    main._JOBS.pop(r.json()["job"]["id"], None)

print("=== 6. Лимит исчерпан — задача из очереди останавливается ДО первой порции ===")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"limitUsd": 0.001})
calls = []
orig_chunk = main._job_chunk
main._job_chunk = lambda *a, **k: calls.append(a) or {"done": len(a[2])}
mk = lambda ids: {"id": 999, "kind": "backcheck", "project": pid, "status": "queued", "tenant": "acme",
                  "total": len(ids), "done": 0, "counters": {}, "error": None, "params": {}, "ids": ids,
                  "stop": False, "recent": [], "created": "", "started": None, "finished": None}
job = mk([1])
try:
    main._job_execute(job)
finally:
    main._job_chunk = orig_chunk
check(job["status"] == "stopped" and job.get("stopReason") == "limit" and job.get("finished"),
      "stopped с кодом limit до старта: %s/%s" % (job["status"], job.get("stopReason")))
check(job["error"] == main.JOB_STOP_LIMIT and job["counters"].get("limitStop") == 1, "причина и счётчик записаны")
check(not calls, "ни одна порция не вызвана")

bumped = []
orig_bump = getattr(main.STORE, "bump_epoch", None)
main.STORE.bump_epoch = lambda name: bumped.append(name) or 0
try:
    c.post("/api/admin/tenants/acme", headers=H(A), json={"limitUsd": 0.5})
finally:
    if orig_bump is not None:
        main.STORE.bump_epoch = orig_bump
check("doc:tenants" in bumped, "правка лимита поднимает эпоху doc:tenants — внешний воркер увидит новый потолок")

print("=== 6a. Лимит кончился ПОСЛЕ первой порции — вторая не идёт, сделанное сохранено ===")
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"limitUsd": 1.0})
orig_ss, seen = main._spend_status, {"n": 0}
def _ss(tenant=None):
    st = orig_ss(tenant); st["over"] = seen["n"] >= 1; return st
def _chunk(*a, **k):
    seen["n"] += 1; calls.append(a); return {"done": len(a[2])}
main._spend_status, main._job_chunk = _ss, _chunk
job = mk(list(range(1, main.JOB_CHUNKS["backcheck"] + 2)))     # две порции
try:
    main._job_execute(job)
finally:
    main._spend_status, main._job_chunk = orig_ss, orig_chunk
check(len(calls) == 1 and job["status"] == "stopped" and job.get("stopReason") == "limit",
      "одна порция прошла, вторая остановлена лимитом: calls=%d %s" % (len(calls), job["status"]))
check(job["done"] == main.JOB_CHUNKS["backcheck"], "сделанное сохранено в done: %s" % job["done"])
r = c.post("/api/admin/tenants/acme", headers=H(A), json={"clearLimit": True})

print("=== 7. Потолки импорта: страницы на файл (413), проекты и страницы организации (402) ===")
try:
    from docx import Document
    HAVE_DOCX = True
except ImportError:
    HAVE_DOCX = False
if HAVE_DOCX:
    import io as _io
    d = Document()
    d.add_paragraph("Первый абзац про туберкулёз лёгких и его лечение в стационаре.")
    d.add_paragraph("Второй абзац про профилактику.")
    b = _io.BytesIO(); d.save(b); raw = b.getvalue()
    MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    up = lambda: c.post("/api/projects/upload", headers=H(B), files={"file": ("t.docx", raw, MIME)},
                        data={"src": "RU", "tgt": "EN"})
    caps = (main.IMPORT_MAX_PAGES, main.TENANT_MAX_PAGES, main.TENANT_MAX_PROJECTS)
    try:
        main.IMPORT_MAX_PAGES, main.TENANT_MAX_PAGES, main.TENANT_MAX_PROJECTS = 0.01, 0, 0
        r = up()
        check(r.status_code == 413 and "Файл на " in r.json().get("detail", ""),
              "потолок страниц на файл → 413: %s" % r.text[:110])
        main.IMPORT_MAX_PAGES, main.TENANT_MAX_PROJECTS = 0, 1          # у acme уже есть проект
        r = up()
        check(r.status_code == 402 and "файлов" in r.json().get("detail", ""), "потолок проектов → 402: %s" % r.text[:110])
        main.TENANT_MAX_PROJECTS, main.TENANT_MAX_PAGES = 0, 0.01
        r = up()
        check(r.status_code == 402 and " стр." in r.json().get("detail", ""),
              "потолок страниц организации → 402, старый проект без pages посчитан по сегментам: %s" % r.text[:110])
        main.TENANT_MAX_PAGES = 0
        # ── учёт в страницах: пополнение → списание → повтор → удаление ──
        me0 = c.get("/api/auth/me", headers=H(B)).json()
        check(me0["usage"]["counter"] is False and me0["usage"]["left"] is None, "до пополнения: объём по живым проектам, лимита нет")
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": -5})
        me1 = c.get("/api/auth/me", headers=H(B)).json()
        check(r.status_code == 400 and me1["usage"]["counter"] is False and not me1["pagesLog"],
              "отклонённое пополнение следа не оставляет: счётчика и журнала нет")
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": 1, "maxProjects": -1})
        me1 = c.get("/api/auth/me", headers=H(B)).json()
        check(r.status_code == 400 and me1["usage"]["counter"] is False, "потолок проектов ниже нуля → 400, пополнение не применено")
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": 0.01, "maxProjects": 50})
        j = r.json()
        check(r.status_code == 200 and j["caps"]["maxPages"] == 0.01 and j["caps"]["own"]["maxProjects"] == 50
              and j["usage"]["credit"] == 0.01 and j["usage"]["counter"] and "filesSeen" not in j["tenant"]
              and j["tenant"]["pagesLog"][0]["kind"] == "init", "первое пополнение заводит счётчик со строкой init: %s" % r.text[:200])
        r = up()
        check(r.status_code == 402 and " при лимите " in r.json().get("detail", ""), "лимит страниц не покрывает файл → 402")
        r = c.post("/api/admin/tenants/acme", headers=H(B), json={"addPages": 100})
        check(r.status_code == 403, "владелец сам себе лимит не пополняет")
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": -5})
        check(r.status_code == 400, "исправление ниже нуля → 400")
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": -0.01})
        r2 = up()
        check(r.json()["caps"]["maxPages"] == 0 and r.json()["caps"]["pagesLimited"] and r2.status_code == 402,
              "выдано 0 — исчерпано, а не «без потолка»: импорт → 402")
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": 1.01, "note": "тест"})
        check(r.status_code == 200 and abs(r.json()["caps"]["maxPages"] - 1.01) < 1e-9, "пополнения суммируются")
        used0 = c.get("/api/auth/me", headers=H(B)).json()["usage"]["used"]
        r = up()
        check(r.status_code == 200 and r.json().get("sourceSha"), "импорт прошёл, отпечаток файла записан")
        p2 = r.json()["id"]
        me = c.get("/api/auth/me", headers=H(B)).json()
        check(me["usage"]["used"] > used0 and me["usage"]["left"] is not None, "списано, остаток виден: %s" % me["usage"])
        used1 = me["usage"]["used"]
        r = up()
        me = c.get("/api/auth/me", headers=H(B)).json()
        # Тот же файл на ту же пару при ЖИВОМ проекте — 409 с адресом готового:
        # второй проект по нему был бы бесплатным переводом заново.
        # Номер и имя — ПОЛЯМИ ответа (экран предлагает «Открыть проект»),
        # а текст отказа постоянный: имя клиента внутри ключа перевода
        # сделало бы его непереводимым.
        j409 = r.json() if r.status_code == 409 else {}
        check(r.status_code == 409 and j409.get("code") == "duplicate"
              and (j409.get("project") or {}).get("id") == p2 and (j409.get("project") or {}).get("title") == "t"
              and j409.get("detail") == main.DUPLICATE_UPLOAD_MSG and me["usage"]["used"] == used1,
              "повтор того же файла при живом проекте → 409 с полями проекта, ничего не списано: %s" % r.text[:160])
        # Проба — той же меркой, по ВСЕЙ организации: дубль в соседней папке
        # ей виден, хотя «похожие» ищутся в пределах папки.
        fr = c.post("/api/folders", headers=H(B), json={"title": "Другая", "src": "RU", "tgt": "EN"})
        if fr.status_code == 200 and fr.json().get("id") is not None:
            pr = c.post("/api/projects/probe", headers=H(B), files={"file": ("t.docx", raw, MIME)},
                        data={"src": "RU", "tgt": "EN", "folder": str(fr.json()["id"])})
            check(pr.status_code == 200 and any(e["id"] == p2 for e in pr.json().get("exact") or []),
                  "проба в другой папке видит дубль организации: %s" % pr.text[:160])
        else:
            print("  (папка не создана — проба по папке пропущена: %s)" % fr.text[:100])
        r = c.post("/api/projects/upload", headers=H(B), files={"file": ("t.docx", raw, MIME)},
                   data={"src": "RU", "tgt": "UZ"})
        p3 = r.json()["id"] if r.status_code == 200 else None
        check(r.status_code == 200, "тот же файл на ДРУГУЮ пару — новый файл: %s" % r.text[:120])
        # Объём в ответе округлён до 0,1 стр., а файл — сотые доли: сверяем
        # точный счётчик записи и журнал.
        exact = lambda: next(t for t in main.STATE["tenants"] if t["id"] == "acme")["pagesUsed"]
        me = c.get("/api/auth/me", headers=H(B)).json()
        used2 = exact()
        check(me["pagesLog"][-1]["kind"] == "debit" and me["pagesLog"][-1]["pages"] > 0,
              "другая пара списана как новый перевод: %s" % me["pagesLog"][-1])
        c.request("DELETE", "/api/projects/%d" % p2, headers=H(B))
        check(exact() == used2, "удаление проекта счётчик не уменьшает")
        r = up()
        p4 = r.json()["id"] if r.status_code == 200 else None
        me = c.get("/api/auth/me", headers=H(B)).json()
        check(r.status_code == 200 and exact() > used2 and me["pagesLog"][-1]["kind"] == "debit",
              "файл удалённого проекта загружен снова — списан как новый: %s" % me["pagesLog"][-1])
        for p_ in (p3, p4):
            if p_:
                c.request("DELETE", "/api/projects/%d" % p_, headers=H(B))
        kinds = [e["kind"] for e in me["pagesLog"]]
        check(kinds[0] == "init" and kinds.count("credit") == 3 and "debit" in kinds, "журнал: init, три пополнения, списание: %s" % kinds)
        ov = c.get("/api/admin/overview", headers=H(A)).json()
        check("capDefaults" in ov and all("caps" in t and "usage" in t and "pagesLog" in t and "filesSeen" not in t
                                          for t in ov["tenants"]), "сводка несёт потолки, объём и хвост журнала без отпечатков")
        main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] not in (p2, p3)]
        # лимит только из окружения, пополнений не было: счётчик заводит первое списание
        c.post("/api/admin/tenants", headers=H(A),
               json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
        BT = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]
        main.TENANT_MAX_PAGES = 5
        r = c.post("/api/projects/upload", headers=H(BT), files={"file": ("t.docx", raw, MIME)}, data={"src": "RU", "tgt": "EN"})
        mb = c.get("/api/auth/me", headers=H(BT)).json()
        check(r.status_code == 200 and mb["usage"]["counter"] and mb["pagesLog"][0]["kind"] == "init"
              and mb["usage"]["left"] is not None, "лимит из окружения: первое списание заводит счётчик: %s" % mb["usage"])
        ub = mb["usage"]["used"]
        r = c.post("/api/projects/upload", headers=H(BT), files={"file": ("t.docx", raw, MIME)}, data={"src": "RU", "tgt": "EN"})
        mb = c.get("/api/auth/me", headers=H(BT)).json()
        check(r.status_code == 409 and mb["usage"]["used"] == ub,
              "повтор у организации на лимите из окружения: 409, объём не вырос")
        main.STATE["projects"] = [p for p in main.STATE["projects"] if main._tenant_of(p) != "beta"]
        main.TENANT_MAX_PAGES = 0
        r = c.post("/api/admin/tenants/acme", headers=H(A), json={"addPages": 500, "clearMaxProjects": True})
        check(r.status_code == 200 and r.json()["caps"]["own"]["maxProjects"] is None, "потолок проектов снят — снова по умолчанию")
        r = up()
        ok = r.status_code == 200 and (r.json().get("pages") or 0) > 0
        check(ok, "без потолков импорт проходит, pages записан: %s" % (r.json().get("pages") if r.status_code == 200 else r.text[:110]))
        if r.status_code == 200:
            main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] != r.json()["id"]]
    finally:
        main.IMPORT_MAX_PAGES, main.TENANT_MAX_PAGES, main.TENANT_MAX_PROJECTS = caps
else:
    print("python-docx нет — раздел 7 пропущен")

print("\n=== 8. Бюджет ПРОЕКТА: наши затраты против оплаченных страниц ===")
# `limitUsd` меряет деньги организации за МЕСЯЦ и вопроса «не работаем ли мы
# в минус вот на этой книге» не задаёт вовсе. Ставка «сколько мы готовы
# потратить на страницу заказа» связывает выручку (страницы) с затратами
# (доллары на модели). Умолчание — 0, то есть выключено; проверяем обе стороны.
bp = main.PROJECT_BUDGET_PER_PAGE
bt = main._tenant_rec("acme") or main._tenant_rec(main.DEFAULT_TENANT)
btid = bt["id"] if bt.get("id") else main.DEFAULT_TENANT
bproj = {"id": 90210, "title": "бюджетная книга", "tenant": btid, "pages": 10.0,
         "created": "2026-09-20", "src": "RU", "tgt": "EN", "segments": []}
main.STATE["projects"].append(bproj)
try:
    bt.pop("budgetPerPage", None)
    main.PROJECT_BUDGET_PER_PAGE = 0
    check(main._project_budget(btid, 90210) is None,
          "ставки нет — мерить нечем, и это НЕ «в порядке», а «не знаю»")
    job = {"id": 1, "tenant": btid, "project": 90210, "counters": {}}
    check(main._job_budget_hit(job) is False and "stopReason" not in job,
          "без ставки прогон не останавливается")

    main.PROJECT_BUDGET_PER_PAGE = 0.5          # $0.5 на страницу → потолок $5
    b = main._project_budget(btid, 90210)
    check(b and b["cap"] == 5.0 and b["pages"] == 10.0,
          "потолок считается от объёма проекта: %s" % b)
    check(b and not b["over"], "расхода ещё нет — потолок не выбран")
    check(main._job_budget_hit(job) is False, "и прогон идёт")

    main._proj_spend_add(btid, 90210, cost=6.0, calls=1)
    b = main._project_budget(btid, 90210)
    check(b and b["over"], "потрачено больше потолка: %s" % b)
    check(main._job_budget_hit(job) is True, "прогон остановлен")
    check(job.get("status") == "stopped" and job.get("stopReason") == "budget",
          "мягко и КОДОМ причины, а не текстом: %s / %s" % (job.get("status"), job.get("stopReason")))
    check(job["counters"].get("budgetStop") == 1, "счётчик остановки поставлен")
    # Рубеж в прогоне ОДИН на оба потолка: разойдись списки мест — один
    # держал бы шаги, которых не держит другой.
    job2 = {"id": 2, "tenant": btid, "project": 90210, "counters": {}}
    check(main._job_money_stop(job2) is True and job2.get("stopReason") == "budget",
          "общий рубеж `_job_money_stop` видит бюджет, а не только лимит: %s" % job2.get("stopReason"))
    # Граница «выбран» — по >=, и она названа числом, а не «примерно».
    main.STATE[main.PROJECT_SPEND_KEY] = {}
    main._proj_spend_add(btid, 90210, cost=4.99, calls=1)
    check(main._project_budget(btid, 90210)["over"] is False, "$4.99 при потолке $5 — ещё не выбран")
    main._proj_spend_add(btid, 90210, cost=0.01, calls=1)
    check(main._project_budget(btid, 90210)["over"] is True, "ровно $5.00 — уже выбран")
    # Объёма нет — мерить нечем, и это «не знаю», а не «в порядке».
    bproj["pages"] = 0.0
    check(main._project_budget(btid, 90210) is None, "нулевой объём — None, а не «потолок не выбран»")
    bproj["pages"] = 10.0
    # Изоляция: чужой организации проект не виден (инвариант 11).
    check(main._project_budget("чужая-организация", 90210) is None,
          "проект чужой организации в расчёт не идёт")
    # Отказ НА СТАРТЕ, а не «нажал — ничего не произошло»: на НАСТОЯЩЕМ
    # проекте организации, иначе 404 сделал бы проверку холостой.
    real = next((p for p in main.STATE["projects"] if p["id"] == pid), None)
    if real is not None:
        real_t = main._tenant_of(real)
        rate_rec = main._tenant_rec(real_t)
        main._proj_spend_add(real_t, pid, cost=999.0, calls=1)
        if rate_rec is not None:
            rate_rec["budgetPerPage"] = 0.001
        r = c.post("/api/projects/%d/jobs" % pid, headers=H(B),
                   json={"kind": "full", "segment_ids": [s["id"] for s in real["segments"][:1]]})
        check(r.status_code == 402,
              "постановка задачи при выбранном бюджете — 402, а не тихая остановка потом: %s %s"
              % (r.status_code, r.text[:140]))
        check("потолка" in r.text or "chegara" in r.text or "cap" in r.text,
              "и отказ называет причину: %s" % r.text[:140])
        if rate_rec is not None:
            rate_rec.pop("budgetPerPage", None)
        for k in [k for k in (main.STATE.get(main.PROJECT_SPEND_KEY) or {}) if k.endswith("|%d" % pid)]:
            main.STATE[main.PROJECT_SPEND_KEY].pop(k, None)

    # Ставка организации сильнее умолчания сервиса — её ставит суперпользователь.
    bt["budgetPerPage"] = 10.0
    check(main._project_budget(btid, 90210)["over"] is False,
          "поднятая ставка организации снимает потолок: %s" % main._project_budget(btid, 90210))
    r = c.post("/api/admin/tenants/%s" % btid, headers=H(A), json={"budgetPerPage": -1})
    check(r.status_code == 400, "отрицательная ставка — 400: %s" % r.status_code)
    r = c.post("/api/admin/tenants/%s" % btid, headers=H(A), json={"clearBudget": True})
    check(r.status_code == 200 and "budgetPerPage" not in (main._tenant_rec(btid) or {}),
          "clearBudget возвращает к умолчанию сервиса")
finally:
    main.PROJECT_BUDGET_PER_PAGE = bp
    bt.pop("budgetPerPage", None)
    main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] != 90210]
    # Строка расхода переживает удаление проекта (это деньги), но в тесте
    # она мусор: следующий набор считал бы по ней.
    for k in [k for k in (main.STATE.get(main.PROJECT_SPEND_KEY) or {}) if k.endswith("|90210")]:
        main.STATE[main.PROJECT_SPEND_KEY].pop(k, None)

main.STATE["projects"] = [p for p in main.STATE["projects"] if p["id"] != pid]
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
