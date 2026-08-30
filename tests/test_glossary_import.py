"""Импорт глоссария файлом (`POST /api/glossary/import`).

Стартовый глоссарий пуст, словарь клиента приходит TSV/CSV. Сторожится:
записи ложатся в область и организацию импортирующего; уровень по
умолчанию — подсказка, приказ — только владелец; повторы в пределах области
пропускаются; `dry_run` по умолчанию ничего не пишет. Ни одного вызова
модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"] = [], []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/users", headers=H(A), json={"login": "tr", "password": "translator-1"})
T = c.post("/api/auth/login", json={"login": "tr", "password": "translator-1"}).json()["token"]

TSV = "src\ttgt\tcat\nдоговор\tcontract\tContract\nсторона\tparty\t\n\tempty\t\nдоговор\tagreement\t\n".encode("utf-8")
before = len(main.STATE["glossary"])

print("=== 1. dry_run по умолчанию — ничего не пишет ===")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "legal"})
j = r.json()
check(r.status_code == 200 and j["dryRun"], "ответ 200, dryRun")
check(j["rows"] == 4 and j["added"] == 2 and j["skippedDup"] == 1 and j["skippedBad"] == 1 and j["header"],
      "разбор: 4 строки, 2 добавится, 1 повтор, 1 битая, заголовок распознан")
check(len(main.STATE["glossary"]) == before, "в глоссарий ничего не записано")

print("=== 2. Запись — в область и организацию ===")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "legal", "dry_run": "false"})
check(r.status_code == 200 and r.json()["added"] == 2, "записано 2")
g = [x for x in main.STATE["glossary"] if x.get("src") == "договор"]
check(g and g[0]["tenant"] == "default" and g[0]["lang"] == "RU→EN" and g[0]["domain"] == "legal",
      "организация, пара, тематика на записи")
check(g[0]["tier"] == "auto" and g[0]["origin"].startswith("import:"), "уровень — подсказка, след — import:")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "legal", "dry_run": "false"})
check(r.json()["added"] == 0 and r.json()["skippedDup"] == 3, "повторный импорт — всё повторы")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "technical"})
check(r.json()["added"] == 2, "та же пара в другой области — новые записи")

print("=== 3. Приказ — только владелец; пара — из каталога ===")
r = c.post("/api/glossary/import", headers=H(T), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "legal", "tier": "verified"})
check(r.status_code == 403, "переводчик приказом — 403")
r = c.post("/api/glossary/import", headers=H(T), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "legal"})
check(r.status_code == 200, "переводчик подсказкой — можно")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RU→XX", "domain": "legal"})
check(r.status_code == 400, "чужой код языка — 400")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("terms.tsv", TSV)},
           data={"lang": "RUEN", "domain": "legal"})
check(r.status_code == 400, "пара без стрелки — 400")

print("=== 4. CSV без заголовка ===")
CSV = "квазитермин-один;quasi-term-one\nквазитермин-два;quasi-term-two\n".encode("utf-8")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("t.csv", CSV)},
           data={"lang": "RU→EN", "domain": "medical"})
check(r.status_code == 200 and r.json()["added"] >= 1 and not r.json()["header"],
      "«;» распознан, заголовка нет — первые две колонки")

main.STATE["glossary"] = [x for x in main.STATE["glossary"] if not str(x.get("origin", "")).startswith("import:")]
main._invalidate_gloss_index()
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
