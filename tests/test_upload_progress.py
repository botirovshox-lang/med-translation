"""Разбор присланного файла: скорость, ход работы, остановка на пустом счёте.

1. PDF читается несколькими процессами (`pdfpages_worker.py`) — и строки
   страниц ТЕ ЖЕ, что при чтении одним процессом: правила `pdftext`
   подобраны на выдаче pypdf, и другой ответ поменял бы импорт.
2. Страницы кэшируются по содержимому: проба, смета и загрузка того же
   файла читают книгу один раз.
3. Ход разбора: браузер шлёт ключ, сервер пишет стадию и счёт страниц,
   `/api/upload-progress/{ключ}` отвечает; чужой организации — пустотой.
4. Проба не гоняет квадратичный диф по файлам, с которыми совпасть
   не может (`_diff_possible`).
5. Пустой счёт у поставщика моделей останавливает прогон сразу
   (`stopReason: provider_quota`), без трёх повторов порции.
Ни одного вызова модели; файл состояния не пишется."""
import os, sys, time
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
sys.path.insert(0, "backend")
import main
import textcount
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["spend"] = [], [], {}
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def text_pdf(n_pages: int) -> bytes:
    """PDF с текстовым слоем: по две строки на страницу, свой текст у каждой."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for i in range(n_pages):
        body = ("BT /F1 12 Tf 72 720 Td (Page %d first line of text) Tj 0 -16 Td "
                "(second line number %d here) Tj ET" % (i + 1, i + 1))
        kids.append(len(objs) + 1)
        objs.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                    "/Resources << /Font << /F1 3 0 R >> >> >>" % (len(objs) + 2))
        objs.append("<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body))
    objs[1] = "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), n_pages)
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, o)).encode("latin-1")
    xref = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    out += b"".join(("%010d 00000 n \n" % o).encode() for o in offs)
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)).encode()
    return out


try:
    import pypdf  # noqa: F401
    HAVE_PDF = True
except ImportError:
    HAVE_PDF = False

print("=== 1. Параллельное чтение PDF — те же строки, что и одним процессом ===")
if HAVE_PDF:
    pdf = text_pdf(30)
    textcount._PAGES_CACHE.clear()
    textcount.PDF_WORKERS = 1
    seq = textcount._pdf_read_pages(pdf)
    textcount.PDF_WORKERS, textcount.PDF_PARALLEL_MIN_PAGES = 3, 4
    events = []
    textcount.set_progress(lambda st, d, t: events.append((st, d, t)))
    par = textcount._pdf_read_pages(pdf)
    textcount.set_progress(None)
    check(seq[0] == "ok" and len(seq[1]) == 30 and "Page 7 first line" in " ".join(seq[1][6]),
          "одним процессом текст прочитан: %s" % (seq[1][6] if seq[0] == "ok" else seq))
    check(par == seq, "несколькими процессами — строки те же буква в букву")
    check(events and events[-1] == ("read", 30, 30) and all(e[0] == "read" for e in events),
          "ход: «прочитано N из 30» дошёл до конца: %s" % (events[-1:] or None))
    # Ребёнок не запустился — чтение не теряется, а идёт по-старому.
    real_exe = sys.executable
    sys.executable = os.path.join("нет", "такого", "python")
    try:
        fallback = textcount._pdf_read_pages(pdf)
    finally:
        sys.executable = real_exe
    check(fallback == seq, "дети не запустились — прочитано одним процессом, ответ тот же")
else:
    print("    пропущено: нет pypdf")

print("=== 2. Страницы кэшируются по содержимому ===")
if HAVE_PDF:
    textcount._PAGES_CACHE.clear()
    reads = []
    orig_read = textcount._pdf_read_pages
    textcount._pdf_read_pages = lambda c: reads.append(1) or orig_read(c)
    try:
        a = textcount._pdf_pages(pdf, [])
        m = textcount.measure("a.pdf", pdf, "EN")
        a[0].append("порча копии")
        b = textcount._pdf_pages(pdf, [])
    finally:
        textcount._pdf_read_pages = orig_read
    check(len(reads) == 1, "смета и повторный разбор того же файла книгу заново не читают: %d" % len(reads))
    check(m["counts"]["words"] > 0, "смета по кэшу посчитана: %d слов" % m["counts"]["words"])
    check("порча копии" not in b[0], "наружу уходит копия: правка ответа не портит кэш")

print("=== 3. Ход разбора по ключу; чужая организация его не видит ===")
c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "acme", "name": "ACME", "ownerLogin": "acme", "ownerPassword": "acme-pass-123"})
B = c.post("/api/auth/login", json={"login": "acme", "password": "acme-pass-123"}).json()["token"]
key = "k" * 20
if HAVE_PDF:
    textcount._PAGES_CACHE.clear()
    r = c.post("/api/quote", headers=H(B), data={"src": "EN", "tgt": "RU", "progress": key, "save": "false"},
               files={"file": ("book.pdf", pdf, "application/pdf")})
    check(r.status_code == 200 and r.json().get("counts"), "смета с ключом хода посчитана: %s" % r.status_code)
    p = c.get("/api/upload-progress/" + key, headers=H(B)).json()
    check(p["stage"] == "read" and p["done"] == 30 and p["total"] == 30,
          "по ключу виден ход: прочитано 30 из 30 (%s)" % p)
    p2 = c.get("/api/upload-progress/" + key, headers=H(A)).json()
    check(p2["stage"] is None, "чужой организации ход чужого файла не отдаётся")
p3 = c.get("/api/upload-progress/" + "z" * 20, headers=H(B)).json()
check(p3 == {"stage": None, "done": 0, "total": 0}, "неизвестный ключ — пустота, а не ошибка")
check(c.get("/api/upload-progress/" + key).status_code == 401, "без входа ход не отдаётся")
check(main._progress_cb("bad key!") is None and main._progress_cb("") is None,
      "ключ не по форме хода не заводит")

print("=== 4. Проба не гоняет диф там, где совпасть нечему ===")
proj = {"id": 1, "segments": [{"id": i + 1, "source": "Строка номер %d книги" % i, "status": "new"}
                              for i in range(40)]}
same_units = [("Строка номер %d книги" % i, [i]) for i in range(40)]
other_units = [("Совсем другой текст %d" % i, [i]) for i in range(40)]
check(main._diff_possible(proj, same_units), "тот же текст — диф нужен")
check(not main._diff_possible(proj, other_units), "чужой текст — диф не нужен, ответ «не похоже» тот же")
half = same_units[:25] + other_units[:15]
check(main._diff_possible(proj, half) == main._looks_like_new_version(main._diff_counts(proj, half)),
      "отсев не расходится с дифом там, где совпадений хватает")
few = same_units[:5] + other_units[:35]
check(not main._diff_possible(proj, few) and not main._looks_like_new_version(main._diff_counts(proj, few)),
      "совпадений меньше порога — и отсев, и диф говорят «не похоже»")

print("=== 5. Пустой счёт у поставщика — прогон стоп сразу, без повторов ===")
pid = c.post("/api/projects", headers=H(B), json={"title": "p", "src": "RU", "tgt": "EN"}).json()["id"]
calls = []
QUOTA = ("Error code: 429 - {'error': {'message': 'You exceeded your current quota, please check your "
         "plan and billing details.', 'type': 'insufficient_quota'}}")


def _chunk(kind, p, chunk, params):
    calls.append(list(chunk))
    if len(calls) == 1:
        return {"done": len(chunk)}
    return {"done": 0, "errors": len(chunk), "why": QUOTA}


orig_chunk, orig_sleep = main._job_chunk, main.time.sleep
main._job_chunk = _chunk
main.time.sleep = lambda s: None
n = main.JOB_CHUNKS["backcheck"]
ids = list(range(1, 3 * n + 1))
job = {"id": 991, "kind": "backcheck", "project": pid, "status": "queued", "tenant": "acme",
       "total": len(ids), "done": 0, "counters": {}, "error": None, "params": {}, "ids": ids,
       "stop": False, "recent": [], "created": "", "started": None, "finished": None}
try:
    main._job_execute(job)
finally:
    main._job_chunk, main.time.sleep = orig_chunk, orig_sleep
check(job["status"] == "stopped" and job.get("stopReason") == "provider_quota",
      "остановлен с кодом provider_quota: %s/%s" % (job["status"], job.get("stopReason")))
check(len(calls) == 2, "порция с пустым счётом не повторялась: вызовов %d" % len(calls))
check(job["done"] == n, "сделанное до этого сохранено: %d" % job["done"])
check(job["counters"].get("quotaStop") == 1 and job["error"] == main.JOB_STOP_PROVIDER_QUOTA,
      "причина и счётчик записаны")
check(main._is_quota_error(QUOTA) and not main._is_quota_error("Connection reset by peer")
      and not main._is_quota_error("Rate limit reached for requests"),
      "пустой счёт отличается от сбоя сети и обычного ограничения частоты")

# Ошибка номерами (перевод отдаёт в `errors` только id) — причина берётся
# из последней ошибки поставщика.
main._note_provider_error(Exception(QUOTA))
check(main._quota_recent(), "последняя ошибка поставщика помнится")
main._PROVIDER_ERR["at"] = 0.0
check(not main._quota_recent(), "старая ошибка поставщика не останавливает новые прогоны")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
