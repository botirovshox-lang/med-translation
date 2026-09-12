# -*- coding: utf-8 -*-
"""Проекты с файлами и именованные словари.

Зачем. Человеку нужен ПРОЕКТ с несколькими файлами (договор из пяти
приложений, учебник по главам), а «проект» бэкенда — это один файл, и весь
API адресует его по номеру. Контейнер заведён рядом: папка (`folders`),
у файла — поле `folder`. Файл БЕЗ поля — сам себе папка с тем же номером
(закон миграции: документы проектов не переписываются).

И второе: какой словарь использует проект. До этого действовало всё, что
попадало в область, — и словарь клиента, и массовый автоимпорт, и приказы,
доставшиеся записям по умолчанию миграции; отключить лишнее было нельзя.
Теперь у записи есть словарь (`dict`), у папки — список подключённых,
ПЕРВЫЙ — куда пишется новое знание. Запись без поля — в ОДНОМ старом
словаре организации («old»), папка без списка видит все словари.

Что сторожится:
  1. файл без папки — своя папка с тем же номером; папка видна в списке;
  2. записи без поля — в старом словаре; новая папка со СВОИМ словарём
     старого не видит ни промптом, ни требованием; подключила — видит;
  3. знание рождается в ПЕРВОМ словаре папки и с номером ПАПКИ, поэтому
     соседний файл проекта видит его;
  4. очерёдность одна на промпт и на поиск записи: порядок подключения;
  5. карточка очереди несёт словарь папки; одобрение пишет туда же;
  6. импорт файлом в НОВЫЙ словарь не считает термины старого повторами;
  7. вынос — по словарю; удаление непустого словаря — отказ;
  8. чужая организация — 404 на папках и словарях; seed отдаёт только своё;
  9. область меняется на всю папку; удаление папки с файлами — только force;
 10. правила проверок у своей области берутся по её шаблону (base).

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "folders-pass-1"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
import checks
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main.STATE["tm"] = []
main.STATE["termQueue"] = []
main.STATE["folders"] = []
main.STATE["dicts"] = []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
A = c.post("/api/auth/login", json={"login": "admin", "password": "folders-pass-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
B = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]

# Учебник первого клиента: файл без папки, знание без словаря — как в бою.
BOOK = {"id": 101, "tenant": "default", "title": "Учебник", "src": "RU", "tgt": "EN",
        "domain": "medical", "segments": []}
main.STATE["projects"] = [BOOK]


def term(src, tgt, project=None, tier="verified", **extra):
    g = {"src": src, "tgt": tgt, "lang": "RU→EN", "domain": "medical", "tenant": "default",
         "tier": tier, **extra}
    if project is not None:
        g["project"] = project
    main.STATE["glossary"].append(g)
    main._invalidate_gloss_index()
    return g


def hits(text, p):
    return [(h["src"], h["tgt"]) for h in main._get_context(text, False, p)[0]]


def req_hits(text, p):
    return [(h["src"], h["tgt"]) for h in main._verified_hits(text, p)]


print("=== 1. Файл без папки — своя папка с тем же номером ===")
check(main._fid(101) == 101, "_fid(файл без папки) == его номер")
f = main._folder_of(BOOK)
check(f and f["id"] == 101 and f.get("virtual"), "папка виртуальная, номер 101")
r = c.get("/api/folders", headers=H(A)).json()["folders"]
check([x["id"] for x in r] == [101] and r[0]["files"] == [101], "в списке одна папка с файлом 101")
check(c.get("/api/folders/101", headers=H(A)).status_code == 200, "GET /api/folders/101 — 200")

print("\n=== 2. Старое знание — в одном старом словаре; новая папка его не видит ===")
term("сторона", "party")
check(main._dict_of(main.STATE["glossary"][0]) == "old", "запись без поля → словарь «old»")
d = {x["id"]: x for x in c.get("/api/dicts", headers=H(A)).json()["dicts"]}
check("old" in d and d["old"]["count"] == 1 and d["old"].get("virtual"), "старый словарь виден, виртуальный, 1 запись")
check(hits("сторона договора", BOOK) == [("сторона", "party")], "учебник (папка без списка) видит старую запись")
r = c.post("/api/folders", headers=H(A), json={"title": "Договор", "src": "RU", "tgt": "EN",
                                              "domain": "medical", "newDict": "Словарь договора"})
check(r.status_code == 200, "папка «Договор» заведена")
FID = r.json()["id"]
check(FID == 102 and r.json()["dicts"] == ["d1"], "номер из общего ряда (102), свой словарь d1 первым")
r = c.post("/api/projects", headers=H(A), json={"title": "Приложение 1", "src": "DE", "tgt": "FR",
                                               "domain": "legal", "folder": FID})
P1 = r.json()
check(r.status_code == 200 and P1["folder"] == FID and (P1["src"], P1["tgt"], P1["domain"]) == ("RU", "EN", "medical"),
      "файл в папке наследует её пару и область, а не присланные")
check(main._fid(P1["id"]) == FID, "_fid(файл в папке) == номер папки")
check(hits("сторона договора", P1) == [], "новая папка старого словаря НЕ видит (промпт)")
check(req_hits("сторона договора", P1) == [], "…и не требует (ремонт/соответствие)")
r = c.post("/api/folders/%d" % FID, headers=H(A), json={"dicts": ["d1", "old"]})
check(r.json()["dicts"] == ["d1", "old"], "старый словарь подключён вторым")
check(hits("сторона договора", P1) == [("сторона", "party")], "подключили — видит")
check(req_hits("сторона договора", P1) == [("сторона", "party")], "…и требует")

print("\n=== 3. Знание рождается в первом словаре папки и видно соседнему файлу ===")
r = c.post("/api/glossary", headers=H(A), json={"src": "сторона", "tgt": "side", "cat": "Term",
                                               "lang": "RU→EN", "domain": "medical",
                                               "project": P1["id"], "isNew": True})
g = next(x for x in main.STATE["glossary"] if x.get("tgt") == "side")
check(g.get("dict") == "d1" and g.get("project") == FID, "запись: словарь d1, project = номер ПАПКИ")
P2 = c.post("/api/projects", headers=H(A), json={"title": "Приложение 2", "folder": FID}).json()
check(hits("сторона договора", P2) == [("сторона", "side")], "соседний файл проекта видит проектную запись")
check(hits("сторона договора", BOOK) == [("сторона", "party")], "учебник — нет: у него своя папка")
check(main._glossary_entry("сторона", ("RU→EN", "medical"), P2["id"]) is g, "_glossary_entry находит её по соседнему файлу")

print("\n=== 4. Очерёдность: порядок подключения, одна на промпт и на поиск ===")
main.STATE["glossary"] = [x for x in main.STATE["glossary"] if x is not g]
main._invalidate_gloss_index()
g_new = term("сторона", "side", dict="d1")           # общая запись в d1
check(hits("сторона договора", P1) == [("сторона", "side")], "d1 первым → его перевод")
check(main._glossary_entry("сторона", ("RU→EN", "medical"), P1["id"])["tgt"] == "side", "…и в поиске")
c.post("/api/folders/%d" % FID, headers=H(A), json={"dicts": ["old", "d1"]})
check(hits("сторона договора", P1) == [("сторона", "party")], "old первым → его перевод")
check(main._glossary_entry("сторона", ("RU→EN", "medical"), P1["id"])["tgt"] == "party", "…и в поиске")
check(main._glossary_entry("сторона", ("RU→EN", "medical"), P1["id"], did="d1")["tgt"] == "side",
      "писатель ищет только в своём словаре (did)")
c.post("/api/folders/%d" % FID, headers=H(A), json={"dicts": ["d1", "old"]})

print("\n=== 5. Карточка очереди и одобрение — в словаре папки ===")
main.STATE["termQueue"] = []
cand = main._queue_term("segment", "иск", "claim", project=P1["id"], segment=1,
                        lang="RU→EN", domain="medical", tenant="default", via="confirmed")
check(cand and cand.get("dict") == "d1", "карточка несёт словарь d1")
r = c.post("/api/term-queue/%d/approve" % cand["id"], headers=H(A), json={"confirm": True})
e = next((x for x in main.STATE["glossary"] if x.get("src") == "иск"), None)
check(e is not None and e.get("dict") == "d1" and e.get("project") == FID,
      "одобрение записало в d1 с номером папки: " + str(r.json().get("written")))
old_cand = {"id": 999, "kind": "segment", "src": "истец", "tgt": "plaintiff", "status": "pending",
            "lang": "RU→EN", "domain": "medical", "tenant": "default", "project": P1["id"]}
check(main._cand_dict(old_cand) == "d1", "старая карточка без поля → словарь папки её файла")

print("\n=== 6. Импорт файлом в новый словарь — старое не считается повтором ===")
TSV = b"src\ttgt\n\xd1\x81\xd1\x82\xd0\xbe\xd1\x80\xd0\xbe\xd0\xbd\xd0\xb0\tparty\n"
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("cl.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "medical", "tier": "auto", "dry_run": "true",
                 "new_dict": "Импорт клиента"})
check(r.json()["added"] == 1 and r.json()["newDict"] and not any(x["id"].startswith("d2") for x in c.get("/api/dicts", headers=H(A)).json()["dicts"]),
      "сухой прогон: добавится 1, словарь ещё не заведён")
r = c.post("/api/glossary/import", headers=H(A), files={"file": ("cl.tsv", TSV)},
           data={"lang": "RU→EN", "domain": "medical", "tier": "auto", "dry_run": "false",
                 "new_dict": "Импорт клиента"})
check(r.json()["added"] == 1 and r.json()["dict"] == "d2", "запись: добавлена в d2, «сторона» из old не повтор")
d = {x["id"]: x for x in c.get("/api/dicts", headers=H(A)).json()["dicts"]}
check(d["d2"]["count"] == 1 and d["d2"]["pairs"] == {"RU→EN": 1}, "d2: 1 запись, пара RU→EN")
r = c.get("/api/glossary?dictId=d2", headers=H(A)).json()
check(r["total"] == 1 and r["items"][0]["dict"] == "d2", "список по словарю и производное поле dict")

print("\n=== 7. Вынос по словарю; удаление непустого словаря — отказ ===")
r = c.post("/api/glossary/purge", headers=H(A), json={"tier": "auto", "dictId": "d2"}).json()
check(r["matched"] == 1 and r["dict"] == "d2", "вынос считает только d2")
check(c.delete("/api/dicts/d2", headers=H(A)).status_code == 409, "непустой словарь не удаляется")
r = c.post("/api/dicts/old", headers=H(A), json={"title": "Словарь учебника"})
check(r.status_code == 200 and r.json()["dict"]["title"] == "Словарь учебника"
      and not r.json()["dict"].get("virtual"), "старый словарь переименован и стал настоящим")

print("\n=== 8. Чужая организация — 404; seed только своё ===")
check(c.get("/api/folders/%d" % FID, headers=H(B)).status_code == 404, "папка чужому — 404")
check(c.post("/api/folders/%d" % FID, headers=H(B), json={"title": "x"}).status_code == 404, "правка чужому — 404")
check(c.delete("/api/folders/%d" % FID, headers=H(B)).status_code in (403, 404), "удаление чужому — не 200")
check(c.post("/api/dicts/d1", headers=H(B), json={"title": "x"}).status_code == 404, "словарь чужому — 404")
check(c.post("/api/projects", headers=H(B), json={"title": "x", "folder": FID}).status_code == 404,
      "файл в чужую папку — 404")
sb = c.get("/api/seed", headers=H(B)).json()
check(sb["folders"] == [] and sb["dicts"] == [], "seed у B: ни папок, ни словарей A")
sa = c.get("/api/seed", headers=H(A)).json()
check({x["id"] for x in sa["folders"]} == {101, FID} and all("dict" in g for g in sa["glossary"]),
      "seed у A: обе папки, записи с полем dict")

print("\n=== 9. Область — на всю папку; удаление папки с файлами — только force ===")
r = c.post("/api/projects/%d/domain" % P1["id"], headers=H(A), json={"domain": "legal"})
check(r.status_code == 200 and all(p["domain"] == "legal" for p in main._folder_files(FID))
      and main._folder_by_id(FID)["domain"] == "legal", "область сменилась у папки и у обоих файлов")
check(c.delete("/api/folders/%d" % FID, headers=H(A)).status_code == 409, "папка с файлами без force — 409")
r = c.delete("/api/folders/%d?force=true" % FID, headers=H(A))
check(r.status_code == 200 and r.json()["filesRemoved"] == 2
      and not any(p.get("folder") == FID for p in main.STATE["projects"]), "force удаляет папку и файлы")
r = c.post("/api/folders/101", headers=H(A), json={"title": "Фтизиатрия"})
check(r.status_code == 200 and main._folder_by_id(101) is not None and BOOK["title"] == "Фтизиатрия",
      "переименование виртуальной папки заводит запись и переименовывает файл-папку")

print("\n=== 10. Правила проверок у своей области — по её шаблону ===")
check(main._rules_domain({"id": "med-2", "base": "medical"}) == "medical", "своя область → base")
check(checks.rules_for(main._rules_domain({"id": "med-2", "base": "medical"}), "RU", "EN")["pairs"],
      "…и таблица правил непустая")
check(main._rules_domain({"id": "medical"}) == "medical", "встроенная — сама")

print()
print("FAILED: %d" % len(fail) if fail else "ВСЁ ПРОШЛО")
for f_ in fail:
    print("  - " + f_)
sys.exit(1 if fail else 0)
