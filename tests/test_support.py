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
# Адресат запоминается вместе с текстом: вопрос обязан уходить в чат
# ПОДДЕРЖКИ, а не в личку владельца вперемешку с отчётами о прогонах.
main.tg_mod.notify_admin_async = (lambda text, kb=None, chat_id=None:
                                  sent.append({"text": text, "chat": chat_id}))


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
check(len(sent) == 1 and "не грузится PDF" in sent[0]["text"], "владельцу ушло уведомление")
check(re.search(r"#d\d+", sent[0]["text"]) is not None, "в уведомлении есть метка треда")
check("Ответьте на это сообщение" in sent[0]["text"], "владельцу сказано, как отвечать")
# Адресат — чат ПОДДЕРЖКИ: в личку владельца идут уведомления сервиса
# (прогоны, лимиты, сводка), и вопрос клиента утонул бы между ними.
check(sent[0]["chat"] == main.tg_mod.SUPPORT_CHAT, "вопрос ушёл в чат поддержки")

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
tag = re.search(r"#d(\d+)", sent[0]["text"]).group(0)
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

print("=== 6в. Группа поддержки: ответ уходит НУЖНОМУ человеку ===")
# Бот — отдельный процесс, поэтому проверяем его правила напрямую, подменив
# сеть. Вопрос ровно один: может ли ответ лечь в ЧУЖОЙ диалог.
import importlib                                          # noqa: E402
os.environ["TELEGRAM_SUPPORT_CHAT"] = "-1001234567890"     # группа
os.environ["TELEGRAM_ADMIN_CHAT"] = "777"                  # личка владельца
os.environ["TELEGRAM_BOT_TOKEN"] = "test:token"
import backend.tg as _tg                                   # noqa: E402
importlib.reload(_tg)
import backend.tgbot as bot                                # noqa: E402
importlib.reload(bot)

out, posted = [], []
bot.tg.send = lambda chat, text, kb=None, token="", preview=False, thread_id=None: (
    out.append({"chat": chat, "text": text, "thread": thread_id}) or {"ok": True})
bot.api = lambda m, path, body=None: (posted.append((path, body)) or
                                      {"ok": True, "thread": 7, "user": 1})

GROUP = -1001234567890
OWNER = {"id": 777, "first_name": "Владелец"}
STRANGER = {"id": 999, "first_name": "Коллега"}
BOT = {"id": 42, "is_bot": True, "first_name": "bot"}
Q = {"from": BOT,
     "text": "\U0001f4ac \u0412\u043e\u043f\u0440\u043e\u0441 \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443 #d7\n\n\u0410\u043d\u043d\u0430 (acme)\n\n\u043d\u0435 \u0433\u0440\u0443\u0437\u0438\u0442\u0441\u044f PDF"}

def call(msg, chat=GROUP):
    out.clear(); posted.clear()
    return bot.on_admin_reply(chat, msg)

# 1. Владелец отвечает в группе — ответ уходит, и по МЕТКЕ, а не по чату.
took = call({"from": OWNER, "text": "пришлите номер", "reply_to_message": Q})
check(took and len(posted) == 1 and posted[0][0] == "/api/tg/support/reply",
      "ответ владельца из ГРУППЫ доставлен")
check("#d7" in (posted[0][1] or {}).get("quoted", ""),
      "тред опознаётся по метке в цитате, а не по чату")

# 2. Чужой человек в той же группе НЕ отвечает от имени поддержки.
took = call({"from": STRANGER, "text": "а я думаю иначе", "reply_to_message": Q})
check(took and not posted, "посторонний в группе клиенту НЕ пишет")
check(out and "не в списке отвечающих" in out[0]["text"],
      "и ему об этом сказано, а не молчание")

# 3. Ответ на ПОДТВЕРЖДЕНИЕ бота не уходит клиенту.
ok_msg = {"from": BOT, "text": "✅ Ответ ушёл в приложение (диалог № 7)."}
check(not call({"from": OWNER, "text": "ага", "reply_to_message": ok_msg}),
      "ответ на галочку бота клиенту не уходит")
check("#d" not in ok_msg["text"], "в подтверждении нет метки — иначе оно само стало бы вопросом")

# 4. Подтверждение возвращается в ТУ ЖЕ ветку чата.
call({"from": OWNER, "text": "готово", "reply_to_message": Q, "message_thread_id": 42})
check(out and out[0]["thread"] == 42, "подтверждение легло в ту же ветку")

# 4б. Список отвечающих пуст, а ADMIN_CHAT — ГРУППА: в личку это правило
# не лезет, иначе владелец оказался бы заперт в своём же чате, а отвечать
# не смог бы никто.
check(bot._may_answer("777", OWNER), "владелец отвечает из своей лички без списка")
check(not bot._may_answer(GROUP, STRANGER), "в группе посторонний не отвечает")
check(bot._may_answer(GROUP, OWNER), "в группе владелец отвечает — он в списке")

# 5. Ветка тест-группы в группе молчит: там боевой пароль тестировщика.
check(not bot._tester_chat({"type": "supergroup"}), "в группе меню тестировщика не рисуется")
check(bot._tester_chat({"type": "private"}), "в личке — как раньше")

# 6. Правка своего сообщения вторым ответом не становится.
seen = []
_real_reply = bot.on_admin_reply            # подмена ТОЛЬКО на эту проверку
bot.on_admin_reply = lambda chat, msg: seen.append(msg) or True
bot.handle({"chats": {}}, {"edited_message": {"chat": {"id": GROUP, "type": "supergroup"},
                                              "from": OWNER, "text": "опечатка",
                                              "reply_to_message": Q}})
check(not seen, "правленое сообщение вторым ответом клиенту не уходит")
bot.on_admin_reply = _real_reply            # дальше проверяем настоящий код

print("=== 6\u0433. \u041a\u0423\u0414\u0410 \u043b\u044f\u0436\u0435\u0442 \u043e\u0442\u0432\u0435\u0442: \u043c\u0435\u0442\u043a\u0430 \u0441\u0447\u0438\u0442\u0430\u0435\u0442\u0441\u044f \u0422\u041e\u041b\u042c\u041a\u041e \u0432 \u043d\u0430\u0448\u0435\u043c \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u0435 ===")
# 6\u0432 \u0441\u0442\u043e\u0440\u043e\u0436\u0438\u0442, \u041a\u041e\u041c\u0423 \u043f\u043e\u0437\u0432\u043e\u043b\u0435\u043d\u043e \u043e\u0442\u0432\u0435\u0447\u0430\u0442\u044c. \u0417\u0434\u0435\u0441\u044c \u2014 \u041a\u0423\u0414\u0410 \u043e\u0442\u0432\u0435\u0442 \u043b\u044f\u0436\u0435\u0442, \u0438 \u044d\u0442\u043e
# \u0434\u0440\u0443\u0433\u043e\u0439 \u0440\u0443\u0431\u0435\u0436: \u043f\u0440\u043e\u043c\u0430\u0445 \u0437\u0434\u0435\u0441\u044c \u2014 \u044d\u0442\u043e \u0447\u0443\u0436\u043e\u0439 \u0447\u0435\u043b\u043e\u0432\u0435\u043a, \u0447\u0438\u0442\u0430\u044e\u0449\u0438\u0439 \u0447\u0443\u0436\u043e\u0439 \u043e\u0442\u0432\u0435\u0442.
st = {"support": [{"id": 3, "user": 111, "tenant": "a", "msgs": []},
                  {"id": 7, "user": 222, "tenant": "b", "msgs": []}]}
H7 = "\U0001f4ac \u0412\u043e\u043f\u0440\u043e\u0441 \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443 #d7"
H3 = "\U0001f4ac \u0412\u043e\u043f\u0440\u043e\u0441 \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443 #d3"

# 1. \u0412 \u0446\u0438\u0442\u0430\u0442\u0435 \u0414\u0412\u0410 \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043a\u0430 (\u0441\u043e\u0441\u0435\u0434\u043d\u0438\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u0441\u043a\u043b\u0435\u0438\u043b\u0438\u0441\u044c
# \u043b\u0438\u0431\u043e \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u0435 \u043f\u0440\u043e\u0446\u0438\u0442\u0438\u0440\u043e\u0432\u0430\u043b\u043e \u043f\u0440\u0435\u0436\u043d\u0435\u0435): \u043e\u0442\u0432\u0435\u0447\u0430\u044e\u0442 \u043d\u0430 \u041f\u041e\u0421\u041b\u0415\u0414\u041d\u0418\u0419.
t = main.support_mod.thread_for_reply(st, H3 + " \u0441\u0442\u0430\u0440\u043e\u0435\n\n" + H7 + " \u0410\u043d\u043d\u0430")
check(t is not None and t["id"] == 7,
      "\u0434\u0432\u0435 \u043c\u0435\u0442\u043a\u0438 \u0432 \u0446\u0438\u0442\u0430\u0442\u0435 \u2014 \u0431\u0435\u0440\u0451\u043c \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a \u0422\u041e\u0413\u041e \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f, \u043d\u0430 \u043a\u043e\u0442\u043e\u0440\u043e\u0435 \u043e\u0442\u0432\u0435\u0442\u0438\u043b\u0438")

# 2. \u041c\u0435\u0442\u043a\u0430 \u0432 \u0447\u0443\u0436\u043e\u043c \u0442\u0435\u043a\u0441\u0442\u0435 (\u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a \u0433\u0440\u0443\u043f\u043f\u044b \u043b\u0438\u0431\u043e \u0441\u0430\u043c \u043a\u043b\u0438\u0435\u043d\u0442
# \u043d\u0430\u043f\u0438\u0441\u0430\u043b "#d7") \u0440\u043e\u0443\u0442\u0435\u0440\u043e\u043c \u043d\u0435 \u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u0441\u044f: \u0442\u0430\u043a \u043f\u0438\u0448\u0435\u043c \u0442\u043e\u043b\u044c\u043a\u043e \u043c\u044b.
check(main.support_mod.thread_for_reply(st, "\u0441\u043c\u043e\u0442\u0440\u0438 \u0442\u0443\u0442 #d7 \u043d\u0435\u043f\u043e\u043d\u044f\u0442\u043d\u043e") is None,
      "\u043c\u0435\u0442\u043a\u0430 \u0432 \u0447\u0443\u0436\u043e\u043c \u0442\u0435\u043a\u0441\u0442\u0435 \u043d\u0438\u043a\u0443\u0434\u0430 \u043d\u0435 \u0432\u0435\u0434\u0451\u0442")
check(main.support_mod.thread_for_reply(st, "\u0443 \u043c\u0435\u043d\u044f \u043e\u0448\u0438\u0431\u043a\u0430 #d3, \u043f\u043e\u043c\u043e\u0433\u0438\u0442\u0435") is None,
      "\u0438 \u0432 \u0442\u0435\u043a\u0441\u0442\u0435 \u0441\u0430\u043c\u043e\u0433\u043e \u043a\u043b\u0438\u0435\u043d\u0442\u0430 \u0442\u043e\u0436\u0435")

# 3. \u041f\u0435\u0440\u0435\u0441\u043b\u0430\u043d\u043d\u043e\u0435 \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u0435 \u0438 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043d\u0435-\u0431\u043e\u0442\u0430 \u2014 \u043d\u0435 \u0440\u043e\u0443\u0442\u0435\u0440\u044b.
HUMAN = {"id": 999, "is_bot": False, "first_name": "\u041a\u043e\u043b\u043b\u0435\u0433\u0430"}
check(not call({"from": OWNER, "text": "\u043e\u0442\u0432\u0435\u0442",
                "reply_to_message": {"from": HUMAN, "text": H7 + " \u0410\u043d\u043d\u0430"}}),
      "\u0446\u0438\u0442\u0430\u0442\u0430 \u043d\u0435 \u043e\u0442 \u0431\u043e\u0442\u0430 \u2014 \u043d\u0435 \u043d\u0430\u0448 \u043c\u0430\u0440\u0448\u0440\u0443\u0442")
check(not call({"from": OWNER, "text": "\u043e\u0442\u0432\u0435\u0442",
                "reply_to_message": {"from": BOT, "forward_date": 1, "text": H7}}),
      "\u043f\u0435\u0440\u0435\u0441\u043b\u0430\u043d\u043d\u0430\u044f \u043a\u043e\u043f\u0438\u044f \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f \u2014 \u0442\u043e\u0436\u0435 \u043d\u0435\u0442")

# 4. \u0417\u043d\u0430\u0447\u043e\u043a \u0431\u0435\u0437 \u0432\u0430\u0440\u0438\u0430\u0446\u0438\u043e\u043d\u043d\u043e\u0433\u043e \u0441\u0435\u043b\u0435\u043a\u0442\u043e\u0440\u0430 \u2014 \u0442\u043e\u0442 \u0436\u0435 \u0437\u043d\u0430\u0447\u043e\u043a.
check(not call({"from": OWNER, "text": "\u0430\u0433\u0430",
                "reply_to_message": {"from": BOT, "text": "\u26a0 \u041d\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b\u043e\u0441\u044c: #d7"}}),
      "\u00ab\u26a0\u00bb \u0431\u0435\u0437 \u0441\u0435\u043b\u0435\u043a\u0442\u043e\u0440\u0430 \u043e\u0442\u0441\u0435\u043a\u0430\u0435\u0442\u0441\u044f \u0442\u0430\u043a \u0436\u0435, \u043a\u0430\u043a \u0441 \u043d\u0438\u043c")

# Заголовок пишется и узнаётся ОДНОЙ константой: разойдись они —
# кАЖДЫЙ ответ владельца получал бы 404 при исправном на вид сообщении.
_probe = main.support_mod.notify_text({"id": 7}, "А", "acme", "текст")
check(main.support_mod.thread_for_reply(st, _probe) is not None,
      "собственное уведомление узнаётся своим же разбором")

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

print("=== 14в. Вкладка «Обучение»: содержание с СЕРВЕРА ===")
# Источник один и тот же, что у страницы /tutorial: вторая копия в .jsx
# разошлась бы первой же правкой, а расхождение значит, что инструкция
# врёт про наш же интерфейс.
check(c.get("/api/tutorial").status_code == 401, "/api/tutorial за входом")
r = c.get("/api/tutorial", headers=H(anna_t))
j = r.json()
check(r.status_code == 200 and j["ok"], "вошедшему отдаётся")
check(len(j["steps"]) == len(main.tutorial_mod.STEPS), "шагов столько же, сколько у страницы")
check(all(s.get("svg") for s in j["steps"]), "у каждого шага приехал рисунок")
check(all("var(--" in s["svg"] for s in j["steps"]),
      "цвета в рисунке — переменными (иначе тёмная тема его не переживёт)")
check(len(j["faq"]) >= 5, "частые вопросы есть")
check(all(f.get("q") and f.get("a") for f in j["faq"]), "у каждого вопроса есть ответ")
for k in ("tour", "support", "print"):
    check(j["actions"].get(k), "действие «%s» названо" % k)
# Язык — ИЗ СЕССИИ, а не из умолчания кода: человек выбрал его в «Профиле».
c.post("/api/profile", headers=H(anna_t), json={"uiLang": "uz"})
check(c.get("/api/tutorial", headers=H(anna_t)).json()["lang"] == "uz",
      "язык берётся из сессии")
check(c.get("/api/tutorial?lang=en", headers=H(anna_t)).json()["lang"] == "en",
      "явный lang сильнее сессии")
c.post("/api/profile", headers=H(anna_t), json={"uiLang": main.DEFAULT_UI_LANG})
# Не платная: читать инструкцию человек обязан мочь и на исчерпанном лимите.
check(not any(re.search(p, "/api/tutorial") for p in paid),
      "/api/tutorial не в _PAID")
# Полнота перевода вкладки — тем же правилом, что у шагов.
miss = [(i, lang) for i, item in enumerate(main.tutorial_mod.FAQ)
        for lang in main.tutorial_mod.LANGS if lang not in item]
check(not miss, "у каждого вопроса есть все три языка: %s" % (miss or "—"))
tabkeys = {lang: set(main.tutorial_mod.TAB_UI[lang]) for lang in main.tutorial_mod.LANGS}
check(tabkeys["ru"] == tabkeys["uz"] == tabkeys["en"],
      "надписи вкладки совпадают по составу ключей во всех языках")

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
