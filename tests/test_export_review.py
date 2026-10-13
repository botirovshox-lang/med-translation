"""Очередь сверки первой выгрузки нового файла (docs/rules/export-review.md).

Решение владельца сервиса 13.10.2026: каждая ПЕРВАЯ выгрузка нового файла
сверяется с оригиналом «до/после», а найденное становится правилом для всех
проектов. Сервер только ставит файл в очередь (`STATE["exportReviews"]`)
и зовёт владельца; сторожится:
  1. первая выгрузка файла — одна строка очереди; повторная выгрузка того же
     файла — ни одной новой; замена файла другим (новый `sourceSha`) — новая;
  2. очередь видит и правит ТОЛЬКО суперпользователь (владельцу — 403);
  3. состояние — из закрытого списка (400), чужой номер — 404;
  4. `/api/seed` очередь не отдаёт (там названия файлов чужих организаций).
Ни одного вызова модели, файл состояния не пишется.
"""
import os
import sys
from pathlib import Path

os.environ["APP_PASSWORD"] = "test-export-review-pw"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["projects"] = [], [], []
main.STATE["exportReviews"] = []
main._SESSIONS.clear()
sent = []
if main.tg_mod is not None:
    main.tg_mod.notify_admin_async = lambda text, *a, **k: sent.append(text)
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
S = c.post("/api/auth/login", json={"login": "admin", "password": "test-export-review-pw"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "bureau", "name": "Бюро", "ownerLogin": "boss", "ownerPassword": "boss-pass-123"})
OWN = c.post("/api/auth/login", json={"login": "boss", "password": "boss-pass-123"}).json()["token"]

print("1. первая выгрузка — одна строка, повтор — ни одной, новый файл — новая")
proj = {"id": 77, "tenant": "bureau", "title": "Отчёт.pdf", "sourceSha": "aaa", "src": "EN", "tgt": "RU"}
main._export_review_note(proj, "pdf", Path("Отчёт RU.pdf"))
main._export_review_note(proj, "docx_layout", Path("Отчёт RU.docx"))
q = main.STATE["exportReviews"]
check(len(q) == 1 and q[0]["project"] == 77 and q[0]["status"] == "pending", "одна строка на файл")
check(q[0]["tenant"] == "bureau" and q[0]["tgt"] == "RU", "строка несёт организацию и пару")
proj2 = dict(proj, sourceSha="bbb")
main._export_review_note(proj2, "pdf", Path("Отчёт RU.pdf"))
check(len(q) == 2 and q[0]["sha"] == "bbb", "замена файла другим — новая строка")
if main.tg_mod is not None:
    check(len(sent) == 2 and "проект 77" in sent[0], "владельцу ушло сообщение на каждую новую строку")

print("2. только суперпользователь")
r = c.get("/api/admin/export-reviews", headers=H(OWN))
check(r.status_code == 403, "владельцу организации — 403")
r = c.get("/api/admin/export-reviews", headers=H(S))
check(r.status_code == 200 and r.json()["pending"] == 2, "суперпользователю — очередь")
rid = q[-1]["id"]
r = c.post("/api/admin/export-reviews/%d" % rid, headers=H(OWN), json={"status": "done"})
check(r.status_code == 403, "отметить сверку владелец не может")

print("3. отметка сверки")
r = c.post("/api/admin/export-reviews/%d" % rid, headers=H(S),
           json={"status": "done", "note": "виды A–G", "report": "https://claude.ai/artifact/x"})
check(r.status_code == 200 and r.json()["item"]["status"] == "done", "done записан")
check(c.get("/api/admin/export-reviews", headers=H(S)).json()["pending"] == 1, "в очереди осталась одна")
check(c.post("/api/admin/export-reviews/%d" % rid, headers=H(S), json={"status": "maybe"}).status_code == 400,
      "чужое состояние — 400")
check(c.post("/api/admin/export-reviews/9999", headers=H(S), json={"status": "done"}).status_code == 404,
      "чужой номер — 404")

print("4. /api/seed очередь не отдаёт")
seed = c.get("/api/seed", headers=H(S)).json()
check("exportReviews" not in seed, "ключа нет в выдаче")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
