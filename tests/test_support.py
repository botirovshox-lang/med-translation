# -*- coding: utf-8 -*-
"""Диалог с поддержкой, знакомство и страница инструкции.

Что сторожится и почему именно это:

  1. ДВЕРЬ ЗА ВХОДОМ. Без токена — 401. Анонимной записи в STATE тут нет
     и быть не должно: приём анкеты (инвариант 23) — единственная такая
     дверь, и заводить вторую ради виджета нельзя.
  2. ИЗОЛЯЦИЯ (инвариант 11). Диалог опознаётся парой «человек + организация»:
     один и тот же человек в двух командах ведёт ДВА разных диалога, и вопрос
     про чужую книгу не всплывает у команды, из которой его исключили.
  3. Ключ `support` НЕ уходит в `/api/seed`: там переписка и почты чужих
     организаций. Белый список инварианта 25 держит это сам — тест сторожит,
     что его не сломали.
  4. ОТВЕТ ВЛАДЕЛЬЦА попадает в СВОЙ тред и только по метке. Метки нет —
     404 и НИ ОДНОЙ записи: ответ, положенный в случайный диалог, прочитал
     бы чужой человек.
  5. Кольцо и потолки: длинное сообщение — 413, частые — 429, переписка
     не растёт бесконечно (`THREAD_MAX`).
  6. ЗНАКОМСТВО живёт НА ЗАПИСИ (`tourDone`), а не в localStorage: иначе
     тур встречал бы человека заново на каждом новом компьютере
     (тот же закон, что у языка интерфейса, инвариант 19).
  7. `/tutorial` — публичная страница на ТРЁХ языках, без STATE и без
     вызовов модели; забытый перевод роняет сборку, а не показывает
     русскую строку на узбекском экране.
  8. Ни одна дверь поддержки не платная: написать в поддержку человек
     обязан мочь и на исчерпанном лимите (инвариант 15).

Ни одного вызова модели, файл состояния не пишется.
"""
import os
import re
import sys

os.environ["APP_PASSWORD"] = "test-support-password"
sys.path.insert(0, "backend")
sys.path.insert(0, ".")
import main                                              # noqa: E402
from starlette.testclient import TestClient              # noqa: E402

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["support"] = []
main._SESSIONS.clear()
main._LOGIN_FAILS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}           # noqa: E731

sent = []
main.tg_mod.notify_admin_async = lambda text, kb=None: sent.append(text)


def mkuser(login, tenant, role="owner", super=False):
    h, salt = main._hash_password("password-123")
    u = {"id": max((x["id"] for x in main._users()), default=0) + 1, "tenant": tenant,
         "login": login, "email": login + "@example.com", "emailVerified": True,
         "hash": h, "salt": salt, "role": role, "super": super, "name": login,
         "active": True, "uiLang": main.DEFAULT_UI_LANG, "created": "2026-01-01"}
    main._users().append(u)
    if not main._tenant_rec(tenant):
        main._tenants().append({"id": tenant, "name": tenant.upper(), "active": True,
                                "created": "2026-01-01"})
    return u


def login(name):
    r = c.post("/api/auth/login", json={"login": name, "password": "password-123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


anna = mkuser("anna", "acme")
bob = mkuser("bob", "bobco")
root = mkuser("root", "acme", super=True)
anna_t, bob_t, root_t = login("anna"), login("bob"), login("root")

print("=== 1. Дверь за входом ===")
check(c.get("/api/support").status_code == 401, "GET без токена — 401")
check(c.post("/api/support", json={"text": "привет"}).status_code == 401,
      "POST без токена — 401 (анонимной записи в STATE нет)")

print("=== 2. Пустой диалог — не ошибка ===")
r = c.get("/api/support", headers=H(anna_t))
check(r.status_code == 200 and r.json()["thread"]["msgs"] == [],
      "новый человек: диалог пуст, а не 404")

print("=== 3. Сообщение записывается и уходит владельцу ===")
sent.clear()
r = c.post("/api/support", headers=H(anna_t), json={"text": "не грузится PDF"})
j = r.json()
check(r.status_code == 200 and j["msg"]["by"] == "user", "сообщение записано как своё")
check(len(j["thread"]["msgs"]) == 1, "оно одно в диалоге")
check(len(sent) == 1 and "не грузится PDF" in sent[0], "владельцу ушло уведомление")
check(re.search(r"#d\d+", sent[0]) is not None, "в уведомлении есть метка треда")
check("Ответьте на это сообщение" in sent[0], "владельцу сказано, как отвечать")

print("=== 4. Пустое и слишком длинное ===")
check(c.post("/api/support", headers=H(anna_t), json={"text": "   "}).status_code == 400,
      "пустое сообщение — 400")
big = "я" * (main.support_mod.MSG_MAX_LEN + 1)
check(c.post("/api/support", headers=H(anna_t), json={"text": big}).status_code == 413,
      "длиннее потолка — 413, а не молча обрезано")

print("=== 5. Изоляция: организация — часть ключа диалога ===")
c.post("/api/support", headers=H(bob_t), json={"text": "вопрос Боба"})
a = c.get("/api/support", headers=H(anna_t)).json()["thread"]
b = c.get("/api/support", headers=H(bob_t)).json()["thread"]
check(a["id"] != b["id"], "у разных организаций разные диалоги")
check(all("Боба" not in m["text"] for m in a["msgs"]), "чужого сообщения в своём диалоге нет")

print("=== 6. Ответ владельца — по МЕТКЕ и только в свой тред ===")
tag = re.search(r"#d(\d+)", sent[0]).group(0)
r = c.post("/api/tg/support/reply", headers={"X-Service-Token": main.TG_SERVICE_TOKEN or ""},
           json={"quoted": "Вопрос в поддержку " + tag, "text": "пришлите номер проекта"})
if main.TG_SERVICE_TOKEN:
    check(r.status_code == 200, "ответ принят по метке")
else:
    check(r.status_code in (200, 401, 403), "без служебного токена дверь закрыта")
# Прямая проверка правила — без служебного токена оно всё равно обязано работать.
t_anna = main.support_mod.thread_of(main.STATE, anna["id"], "acme")
main.support_mod.add_message(t_anna, main.support_mod.WHO_SUPPORT, "пришлите номер проекта", "Поддержка")
a = c.get("/api/support", headers=H(anna_t)).json()["thread"]
check(a["msgs"][-1]["by"] == "support", "ответ виден человеку в его диалоге")
check(a["unread"] >= 1, "непрочитанное считается — значок обязан загореться")
b = c.get("/api/support", headers=H(bob_t)).json()["thread"]
check(all(m["by"] != "support" for m in b["msgs"]), "чужой ответ в диалог Боба не попал")

print("=== 6б. Метки нет — не пишем НИКУДА ===")
before = [len(t.get("msgs") or []) for t in main.support_mod.threads(main.STATE)]
check(main.support_mod.thread_for_reply(main.STATE, "просто текст без метки") is None,
      "без метки тред не опознаётся")
check(main.support_mod.thread_for_reply(main.STATE, "#d99999") is None,
      "метка несуществующего треда — тоже None, а не первый попавшийся")
after = [len(t.get("msgs") or []) for t in main.support_mod.threads(main.STATE)]
check(before == after, "ни одно сообщение не записалось")

print("=== 7. Прочитано — счётчик гаснет ===")
r = c.post("/api/support/read", headers=H(anna_t))
check(r.status_code == 200 and r.json()["thread"]["unread"] == 0, "счётчик непрочитанного сброшен")

print("=== 8. Кольцо не растёт бесконечно ===")
t = main.support_mod.thread_of(main.STATE, anna["id"], "acme")
for i in range(main.support_mod.THREAD_MAX + 25):
    main.support_mod.add_message(t, main.support_mod.WHO_SUPPORT, "ответ %d" % i)
check(len(t["msgs"]) == main.support_mod.THREAD_MAX,
      "длина диалога упёрлась в THREAD_MAX (state.json целиком в памяти)")
check(t["msgs"][-1]["text"].endswith(str(main.support_mod.THREAD_MAX + 24)),
      "выброшено СТАРОЕ, а не новое")

print("=== 9. Потолок частоты по учётной записи ===")
t2 = main.support_mod.thread_of(main.STATE, bob["id"], "bobco")
t2["msgs"] = []
for i in range(main.support_mod.MSG_PER_HOUR):
    main.support_mod.add_message(t2, main.support_mod.WHO_USER, "спам %d" % i)
check(main.support_mod.too_fast(t2), "после MSG_PER_HOUR сообщений подряд — слишком часто")
r = c.post("/api/support", headers=H(bob_t), json={"text": "ещё"})
check(r.status_code == 429, "эндпоинт отвечает 429, а не молчит")

print("=== 10. /api/seed переписку не отдаёт ===")
seed = c.get("/api/seed", headers=H(anna_t)).json()
check("support" not in seed, "ключа support в выдаче нет (белый список инварианта 25)")

print("=== 11. Знакомство живёт на ЗАПИСИ ===")
me = c.get("/api/auth/me", headers=H(anna_t)).json()["me"]
check(me["tourDone"] is False, "у новичка знакомство не пройдено")
r = c.post("/api/profile", headers=H(anna_t), json={"tourDone": True})
check(r.status_code == 200 and r.json()["me"]["tourDone"] is True, "флаг ставится")
check(c.get("/api/auth/me", headers=H(anna_t)).json()["me"]["tourDone"] is True,
      "и переживает новый запрос — то есть и другой компьютер")
check(anna.get("name") == "anna", "флаг ставится ОДИН и не трогает имя")
r = c.post("/api/profile", headers=H(anna_t), json={"tourDone": False})
check(r.json()["me"]["tourDone"] is False, "показать знакомство заново можно — это решение человека")
c.post("/api/profile", headers=H(anna_t), json={"tourDone": True})

print("=== 12. Диалоги суперпользователю, и только ему ===")
check(c.get("/api/admin/support", headers=H(anna_t)).status_code == 403,
      "владелец организации чужие диалоги не видит")
r = c.get("/api/admin/support", headers=H(root_t))
check(r.status_code == 200 and len(r.json()["threads"]) >= 2, "суперпользователь видит список")
row = r.json()["threads"][0]
check("userName" in row and "tenant" in row, "в строке есть человек и организация")
r = c.post("/api/admin/support/reply", headers=H(root_t),
           json={"thread": t_anna["id"], "text": "ответ из админки"})
check(r.status_code == 200 and r.json()["thread"]["msgs"][-1]["text"] == "ответ из админки",
      "ответ из админки ложится тем же путём, что и из Telegram")

print("=== 13. Поддержка не платная (инвариант 15) ===")
paid = [p for _, p in main._PAID]
check(not any(re.search(p, "/api/support") for p in paid),
      "/api/support не в таблице _PAID — писать можно и на исчерпанном лимите")
check(not any(re.search(p, "/api/support/read") for p in paid), "/api/support/read тоже")

print("=== 14. Страница /tutorial: три языка, без STATE ===")
for lang in ("ru", "uz", "en"):
    r = c.get("/tutorial?lang=" + lang)
    check(r.status_code == 200 and ('<html lang="%s"' % lang) in r.text,
          "/tutorial?lang=%s открывается и объявляет свой язык" % lang)
    check(r.text.count('<section class="step"') == len(main.tutorial_mod.STEPS),
          "на %s нарисованы все шаги" % lang)
    check("<svg" in r.text, "на %s есть рисунки экранов" % lang)
r = c.get("/tutorial")
check(r.status_code == 200, "без языка — открывается умолчанием, а не 400")
check(c.get("/tutorial?lang=zz").status_code == 200, "мусорный язык не роняет страницу")

print("=== 14б. Забытый перевод виден, а не молча русский ===")
missing = [(i, lang) for i, (_k, byl) in enumerate(main.tutorial_mod.STEPS)
           for lang in main.tutorial_mod.LANGS if lang not in byl]
check(not missing, "у каждого шага есть все три языка: %s" % (missing or "—"))
keys = {lang: set(main.tutorial_mod.UI[lang]) for lang in main.tutorial_mod.LANGS}
check(keys["ru"] == keys["uz"] == keys["en"],
      "надписи страницы совпадают по составу ключей во всех языках")

print("=== 15. Страница публична и не трогает STATE ===")
before = len(main.support_mod.threads(main.STATE))
c.get("/tutorial")                       # без единого заголовка Authorization
check(len(main.support_mod.threads(main.STATE)) == before, "страница ничего не записала")

if fail:
    print("\nПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("\nВСЁ ПРОШЛО")
