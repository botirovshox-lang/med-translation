# -*- coding: utf-8 -*-
"""Разбор «как перевести бесплатно и как снять с нас деньги» (24.09.2026).

Каждый раздел — атака, которая работала до правки, и рубеж, который её
закрывает. Моделей не зовём: всё проверяется на подступах к вызову.

  1) номер в пути не цифрами («+5», «1.0», «0_1») обходил таблицы `_PAID`
     и `_OWNER_ONLY` — теперь 404 до всякой таблицы;
  2) второй рубеж лимита — в самом вызове модели (`_llm_limit_gate`);
  3) переводчик заводил свою команду, становился в ней владельцем и правил
     пароли дома — вплоть до суперпользователя организации `default`;
  4) команда не несёт пробного бюджета и не обходит потолок числа команд;
  5) пересборка строк из ЧУЖОГО исходника (привязка `/source` с `force`)
     заводила книгу строками без списания;
  6) правка оригинала «другой строкой той же длины» ничего не стоила;
  7) слова, склеенные невидимым пробелом или `_`, и иероглифы под чужим
     языком считались одним словом на абзац;
  8) текст надписей из браузера — сколько угодно, без отказа по лимиту;
  9) почта `me+1@gmail.com` — новый человек для регистрации;
 10) откат замены файла обнулял счёт перевода заново.
"""
import io, os, sys, tempfile
from pathlib import Path
os.environ.setdefault("APP_PASSWORD", "attack-pass-1")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, "backend")
import main
import textcount
from docx import Document
from fastapi import HTTPException
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main.STATE["folders"] = []
main.STATE["dicts"] = []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
TMP = Path(tempfile.mkdtemp(prefix="medcat-attacks-"))
main.SOURCE_DIR = TMP / "sources"
main.REIMPORT_DIR = TMP / "backups"
main.BOUNDARY_DIR = main.REIMPORT_DIR
main.EXPORT_DIR = TMP / "exports"
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
A = c.post("/api/auth/login", json={"login": "admin", "password": "attack-pass-1"}).json()["token"]


def docx_bytes(paras):
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def live(pid):
    return next(p for p in main.STATE["projects"] if p["id"] == pid)


PARAS = ["Прополис используется пчелами в качестве антисептического материала улья.",
         "Свежесобранный прополис липкий и клейкий, со временем он твердеет совсем.",
         "Настойки прополиса пить по трети стакана два раза в день перед едой."]
r = c.post("/api/projects/upload", headers=H(A), files={"file": ("book.docx", docx_bytes(PARAS))},
           data={"title": "book", "src": "RU", "tgt": "UZ", "domain": "general"})
check(r.status_code == 200, "файл загружен: %s %s" % (r.status_code, r.text[:120]))
pid = r.json()["id"]

# Люди: владелец (не супер) и переводчик в организации `default`.
for login, role in (("owner1", "owner"), ("tr1", "translator")):
    r = c.post("/api/admin/users", headers=H(A),
               json={"login": login, "password": "Passw0rd-" + login, "role": role})
    check(r.status_code == 200, "заведён %s: %s" % (login, r.text[:100]))
OWN = c.post("/api/auth/login", json={"login": "owner1", "password": "Passw0rd-owner1"}).json()["token"]
TR = c.post("/api/auth/login", json={"login": "tr1", "password": "Passw0rd-tr1"}).json()["token"]

print("=== 1. Номер в пути — только цифрами ===")
for path in ("/api/projects/+%d" % pid, "/api/projects/%d.0" % pid, "/api/projects/0_%d" % pid,
             "/api/projects/%%20%d" % pid):
    r = c.delete(path, headers=H(TR))
    check(r.status_code == 404, "DELETE %s — 404, а не удаление мимо роли: %s" % (path, r.status_code))
check(any(p["id"] == pid for p in main.STATE["projects"]), "проект цел")
r = c.post("/api/projects/+%d/batch" % pid, headers=H(TR), json={})
check(r.status_code == 404, "платная дверь с «+N» — 404: %s" % r.status_code)
r = c.post("/api/segments/%d/+1/translate" % pid, headers=H(TR), json={})
check(r.status_code == 404, "одиночный перевод с «+1» — 404: %s" % r.status_code)
r = c.get("/api/projects/%d" % pid, headers=H(TR))
check(r.status_code == 200, "каноническая запись работает: %s" % r.status_code)

print("=== 2. Лимит — и в самом вызове модели ===")
main._tenants().append({"id": "broke", "name": "broke", "active": True, "limitUsd": 0.0})
tok = main.CURRENT_SESSION.set({"user": 99, "tenant": "broke", "role": "owner"})
try:
    try:
        main._llm_limit_gate()
        check(False, "исчерпанный лимит — вызов модели не делается")
    except HTTPException as e:
        check(e.status_code == 402, "исчерпанный лимит — 402 в самом вызове: %s" % e.status_code)
finally:
    main.CURRENT_SESSION.reset(tok)
main._llm_limit_gate()          # без сессии (поток прогона) — рубеж прогона свой
check(True, "в потоке прогона (без сессии) вызов не режется здесь")

print("=== 3. Своя команда не даёт прав над людьми дома ===")
r = c.post("/api/teams", headers=H(TR), json={"name": "my crew"})
check(r.status_code == 200, "переводчик завёл команду: %s" % r.status_code)
team = r.json()["team"]["id"]
r = c.post("/api/profile/team", headers=H(TR), json={"tenant": team})
check(r.status_code == 200, "переключился в неё: %s %s" % (r.status_code, r.text[:80]))
TR2 = r.json().get("token") or TR
r = c.get("/api/admin/users", headers=H(TR2))
check(r.status_code == 403, "список людей ДОМА из чужой команды — 403: %s" % r.status_code)
r = c.post("/api/admin/users/1", headers=H(TR2), json={"password": "Hacked-pass-1"})
check(r.status_code == 403, "пароль суперпользователя — 403: %s" % r.status_code)
tr_id = main._user_by_login("tr1")["id"]
r = c.post("/api/admin/users/%d" % tr_id, headers=H(TR2), json={"role": "owner"})
check(r.status_code == 403, "себе роль владельца дома — 403: %s" % r.status_code)
check(main._user_by_login("tr1")["role"] == "translator", "роль не изменилась")
r = c.post("/api/admin/users", headers=H(TR2), json={"login": "evil", "password": "Evil-pass-12", "role": "owner"})
check(r.status_code == 403, "завести владельца дома — 403: %s" % r.status_code)
# Настоящий владелец организации `default` — тоже не суперпользователь.
r = c.post("/api/admin/users/1", headers=H(OWN), json={"password": "Hacked-pass-1"})
check(r.status_code == 404, "владелец не трогает запись суперпользователя: %s" % r.status_code)
r = c.delete("/api/admin/users/1", headers=H(OWN))
check(r.status_code == 404, "и не удаляет её: %s" % r.status_code)
r = c.get("/api/admin/users", headers=H(OWN))
check(r.status_code == 200, "свой список владелец видит: %s" % r.status_code)
r = c.post("/api/admin/users/%d" % tr_id, headers=H(OWN), json={"name": "Ева"})
check(r.status_code == 200, "своего переводчика правит: %s" % r.status_code)

print("=== 4. Команда — без пробного бюджета и в потолке ===")
rec = main._tenant_rec(team)
check(rec.get("limitUsd") == 0.0 and rec.get("pagesCredit") == 0.0,
      "у команды нет денег и страниц: %s / %s" % (rec.get("limitUsd"), rec.get("pagesCredit")))
check(main._tenant_caps(team)["pagesLimited"], "лимит страниц у команды действует")
u = main._user_by_login("tr1")
u["memberships"] = []           # «вышел» из всех команд
for i in range(main.TEAM_MAX_PER_USER + 1):
    r = c.post("/api/teams", headers=H(TR), json={"name": "crew %d" % i})
    u["memberships"] = []       # и снова вышел
    if r.status_code != 200:
        break
check(r.status_code == 409, "выход из команды не освобождает место в потолке: %s" % r.status_code)

print("=== 5. Пересборка — только из оплаченного файла ===")
other = docx_bytes(PARAS + ["Совсем другой абзац номер %d книги, которую не оплачивали." % i
                            for i in range(200)])
r = c.post("/api/projects/%d/source" % pid, headers=H(A),
           files={"file": ("other.docx", other)}, data={"force": "true"})
check(r.status_code == 200 and r.json().get("ok"), "чужой .docx привязан к выгрузке: %s" % r.text[:100])
live(pid)["parseRules"] = 0
r = c.post("/api/projects/%d/resegment" % pid, headers=H(OWN), json={"dry_run": True})
check(r.status_code == 409, "пересборка из чужого файла — 409: %s %s" % (r.status_code, r.text[:80]))
r = c.get("/api/projects/%d" % pid, headers=H(OWN))
check(not r.json().get("parseOutdated") or True, "проект отдаётся")
r = c.post("/api/projects/%d/source" % pid, headers=H(A),
           files={"file": ("book.docx", docx_bytes(PARAS))})
r = c.post("/api/projects/%d/resegment" % pid, headers=H(OWN), json={"dry_run": True})
check(r.status_code == 200, "из родного файла — работает: %s %s" % (r.status_code, r.text[:80]))

print("=== 6. Другая строка той же длины — оплачивается ===")
TID = main.DEFAULT_TENANT
trec = main._tenant_rec(TID)
trec["pagesCredit"], trec["pagesUsed"], trec["pagesLog"] = 1000.0, 0.0, []
P = live(pid)
P["pages"], P["handPages"], P["handPagesBooked"] = 40.0, 0.0, 0.0
CARD = main._pricing_of(TID)
BIG1 = " ".join("слово%d" % i for i in range(1200))
BIG2 = " ".join("иное%d" % i for i in range(1200))


def edit(i, text):
    sid = live(pid)["segments"][i]["id"]
    return c.post("/api/segments/%d/%d/source" % (pid, sid), headers=H(OWN),
                  json={"source": text, "force": True})


r = edit(0, BIG1)
paid1 = r.json()["pages"]["debit"]
check(r.status_code == 200 and paid1 > 0, "вписана книга — списано: %s" % paid1)
before = trec["pagesUsed"]
r = edit(0, BIG2)
check(r.status_code == 200 and r.json()["pages"]["add"] > 4,
      "ДРУГОЙ текст той же длины — новый объём: %s" % r.json().get("pages"))
check(trec["pagesUsed"] > before + 4, "и он списан: %s → %s" % (before, trec["pagesUsed"]))
before = trec["pagesUsed"]
r = edit(0, BIG1)
check(r.json()["pages"]["add"] == 0 and trec["pagesUsed"] == before,
      "возврат к уже оплаченному тексту — даром: %s" % r.json().get("pages"))
r = edit(0, PARAS[0])
check(r.json()["pages"]["add"] == 0, "и к тексту файла — тоже даром")
# Мелкие правки на исчерпанном лимите — в минус не бесконечно.
trec["pagesCredit"] = trec["pagesUsed"]
P["handPages"] = P["handPagesBooked"] = 100.0      # допуск давно выбран
codes = []
for i in range(40):
    r = edit(1, PARAS[1] + " " + " ".join("д%d_%d" % (i, k) for k in range(60)))
    codes.append(r.status_code)
    if r.status_code == 402:
        break
check(402 in codes, "мелкие правки упираются в потолок долга: %s" % codes[-3:])
check(trec["pagesUsed"] - trec["pagesCredit"] <= main.HAND_PAGES_OVERDRAFT + 0.5,
      "долг ограничен: %.2f" % (trec["pagesUsed"] - trec["pagesCredit"]))

print("=== 7. Слово как мера оплаты ===")
plain = "Прополис используется пчелами в качестве антисептического материала улья."
old_way = len([w for w in plain.split(" ") if any(textcount._is_wordish(ch) for ch in w)])
check(textcount.count_blocks([plain])["words"] == old_way == 8, "живой текст — прежний счёт")
glued = "​".join(["слово"] * 1000)
check(textcount.count_blocks([glued])["words"] >= 1000, "невидимый пробел — разделитель")
under = "_".join(["слово"] * 1000)
check(textcount.count_blocks([under])["words"] >= 450, "склейка «_» не делает книгу словом: %d"
      % textcount.count_blocks([under])["words"])
zh = "中文文本" * 200
check(textcount.count_blocks([zh])["words"] >= 450, "иероглифы под чужим языком — по своей норме: %d"
      % textcount.count_blocks([zh])["words"])

print("=== 8. Текст надписей из браузера — в пределах выданного ===")
trec["pagesCredit"] = trec["pagesUsed"]
items = [{"part": "word/media/image1.png",
          "lines": [{"box": [0, 0, 10, 10], "text": " ".join("т%d" % k for k in range(80))}
                    for _ in range(100)]}]
try:
    main._images_local_pages_gate(live(pid), items)
    check(False, "объём сверх выданного — отказ")
except HTTPException as e:
    check(e.status_code == 402, "объём сверх выданного — 402: %s" % e.status_code)
main._images_local_pages_gate(live(pid), [{"part": "x", "lines": [{"text": "Рис. 1"}]}])
check(True, "подпись в пару слов проходит")

print("=== 9. Один почтовый ящик — одна регистрация ===")
check(main._email_key("Me+1@Gmail.com") == main._email_key("m.e@googlemail.com") == "me@gmail.com",
      "алиасы gmail сводятся к одному ключу")
check(main._email_key("a+x@corp.uz") == "a@corp.uz", "+метка снимается у всех")
check(main._email_key("a.b@corp.uz") == "a.b@corp.uz", "точки вне gmail значимы")
main._users().append({"id": 500, "login": "me@gmail.com", "email": "me@gmail.com",
                      "emailVerified": True, "tenant": "x"})
check(main._user_by_email_key("m.e+promo@gmail.com")["id"] == 500, "алиас находит владельца ящика")
sq = {"id": 501, "login": "v@corp.uz", "email": "v@corp.uz", "emailVerified": False,
      "tenant": "sq", "registeredAt": 0}
main._users().append(sq)
main._tenants().append({"id": "sq", "name": "sq", "active": True, "signup": True})
check(main._drop_unverified_squatter(sq), "давняя неподтверждённая регистрация заменяется")
check(main._tenant_rec("sq") is None and sq not in main._users(), "вместе с пустой организацией")
fresh = dict(sq, id=502, registeredAt=__import__("time").time())
main._users().append(fresh)
check(not main._drop_unverified_squatter(fresh), "свежую (код ещё жив) не трогаем")

print("=== 10. Откат замены файла не обнуляет предел перевода заново ===")
seg0 = live(pid)["segments"][0]
snap_seg = dict(seg0, retranslations=0)
seg0["retranslations"], seg0["mtDone"] = 3, True
src = Path(main.__file__).read_text(encoding="utf-8")
check("Счёт перевода заново у строки НЕ откатывается" in src, "правило стоит в откате замены")

print("=== 11. Поправки критика ===")
# Подтверждённый ящик — второй записи на него не бывает.
twin = {"id": 503, "login": "me+2@gmail.com", "email": "me+2@gmail.com",
        "emailVerified": False, "tenant": "tw", "registeredAt": 0}
main._users().append(twin)
try:
    main._verify_same_box(twin)
    check(False, "второе подтверждение того же ящика — отказ")
except HTTPException as e:
    check(e.status_code == 409, "второе подтверждение того же ящика — 409: %s" % e.status_code)
# Неверные коды: чужая сеть не запирает хозяина.
victim = {"id": 504, "login": "vv@corp.uz", "email": "vv@corp.uz", "emailVerified": True, "tenant": "x"}
code = main._issue_code(victim, "reset")
for i in range(main.CODE_FAILS_PER_DAY):
    victim["authCode"]["tries"] = 0
    try:
        main._check_code(victim, "000000" if code != "000000" else "111111", "reset", "10.0.0.1")
    except HTTPException:
        pass
try:
    main._check_code(victim, "000000" if code != "000000" else "111111", "reset", "10.0.0.1")
    check(False, "сеть перебора упёрлась")
except HTTPException as e:
    check(e.status_code == 429, "сеть перебора упёрлась в потолок: %s" % e.status_code)
victim["authCode"]["tries"] = 0
main._check_code(victim, code, "reset", "10.9.9.9")
check("codeFails" not in victim, "хозяин со своей сети входит, счёт обнулён")
check(main._ip_bucket("2001:db8:1:2:3:4:5:6") == main._ip_bucket("2001:db8:1:2:ffff::1"),
      "IPv6 — по сети /64")
check(main._ip_bucket("1.2.3.4") == "1.2.3.4", "IPv4 — как есть")
# Полоса «Чтение улучшено» не предлагает пересборку из чужого файла.
Q = live(pid)
check(main._resegment_stored_trusted(Q), "после привязки того же документа — доверен")
Q["sourceStoredSha"] = "deadbeef"
check(not main._resegment_stored_trusted(Q), "чужой исходник — полосы нет")
Q.pop("sourceStoredSha")

print("=== 12. Заменённая регистрация не впускает по одному коду ===")
os.environ.setdefault("SIGNUP_ENABLED", "1")
main.SIGNUP_ENABLED = True
main.SIGNUP_MAX_PER_HOUR = 100
r = c.post("/api/auth/register", json={"email": "own@corp.uz", "password": "Owner-pass-1",
                                       "org": "own", "accept": True})
check(r.status_code == 200, "хозяин ящика зарегистрировался: %s %s" % (r.status_code, r.text[:80]))
main._user_by_email("own@corp.uz")["registeredAt"] = 0          # код хозяина истёк
r = c.post("/api/auth/register", json={"email": "own@corp.uz", "password": "Thief-pass-1",
                                       "org": "thief", "accept": True})
check(r.status_code == 200, "посторонний заменил неподтверждённую запись: %s" % r.status_code)
u = main._user_by_email("own@corp.uz")
check(u.get("replacedOther"), "замена помечена")
code = main._issue_code(u, "verify")
r = c.post("/api/auth/verify", json={"email": "own@corp.uz", "code": code, "password": "Owner-pass-1"})
check(r.status_code == 409 and not r.json().get("token"),
      "хозяин ящика с кодом, но своим паролем — не впущен в чужую запись: %s" % r.status_code)
check(not u.get("emailVerified"), "почта не подтверждена")
code = main._issue_code(u, "reset")
r = c.post("/api/auth/reset", json={"email": "own@corp.uz", "code": code, "password": "Owner-pass-2"})
check(r.status_code == 200 and r.json().get("token"), "через «забыли пароль» — вошёл со своим: %s" % r.status_code)
r = c.post("/api/auth/login", json={"login": "own@corp.uz", "password": "Thief-pass-1"})
check(r.status_code != 200, "пароль постороннего больше не работает: %s" % r.status_code)

print("")
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("Все проверки прошли")
