# -*- coding: utf-8 -*-
"""Ассистент поддержки (`backend/support_bot.py` + `_support_bot_run`).

Что сторожится:

  1. Ответ ассистента приходит в ТОТ ЖЕ диалог, от имени «Ассистент»,
     а Telegram владельцу на каждое сообщение НЕ уходит — только передача.
  2. Промпт собирает НАСТОЯЩИЙ код (подменён клиент Anthropic, а не наша
     функция): в нём инструкция сервиса, запрет называть модели и цены,
     история в форме user/assistant.
  3. `handoff: true` — диалог у человека, владельцу уходит уведомление
     с меткой треда (по ней бот Telegram доставит ответ), ассистент молчит.
  4. Сбой вызова — тоже передача, а не тишина: человек не остаётся
     с вопросом, на который никто не ответит.
  5. «Позвать человека» и ответ из админки забирают диалог; `/mode bot`
     возвращает; переключать может только суперпользователь.
  6. Расход ассистента ложится на служебную организацию, а не на клиента:
     на исчерпанном лимите клиента ассистент отвечает (инвариант 15).

Сеть не трогается: `sys.modules["anthropic"]` — заглушка.
"""
import json
import os
import sys
import time
import types

os.environ["APP_PASSWORD"] = "test-support-bot"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["SUPPORT_BOT"] = "1"
sys.path.insert(0, "backend")
sys.path.insert(0, ".")

CALLS = []
ANSWER = {"text": json.dumps({"reply": "Нажмите «Перевести» на вкладке «Перевод».",
                              "handoff": False, "reason": ""}, ensure_ascii=False),
          "fail": False}


class _Msgs:
    def create(self, **kw):
        CALLS.append(kw)
        if ANSWER["fail"]:
            raise RuntimeError("сеть упала")
        NS = types.SimpleNamespace
        return NS(id="x", stop_reason="end_turn",
                  content=[NS(type="text", text=ANSWER["text"])],
                  usage=NS(input_tokens=100, output_tokens=20,
                           cache_read_input_tokens=0, cache_creation_input_tokens=0))


class _Anthropic:
    def __init__(self, **kw):
        self.messages = _Msgs()


sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=_Anthropic)

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
main.tg_mod.notify_admin_async = (lambda text, kb=None, chat_id=None: sent.append(text))
main.tg_mod.enabled = lambda: True


def mkuser(login, tenant, super=False):
    h, salt = main._hash_password("password-123")
    u = {"id": max((x["id"] for x in main._users()), default=0) + 1, "tenant": tenant,
         "login": login, "email": login + "@example.com", "emailVerified": True,
         "hash": h, "salt": salt, "role": "owner", "super": super, "name": login,
         "active": True, "uiLang": "ru", "uiLangSet": True, "created": "2026-01-01"}
    main._users().append(u)
    if not main._tenant_rec(tenant):
        main._tenants().append({"id": tenant, "name": tenant, "active": True,
                                "created": "2026-01-01", "limitUsd": 0.0})
    return u


def login(name):
    r = c.post("/api/auth/login", json={"login": name, "password": "password-123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def settle(tok):
    for _ in range(100):
        th = c.get("/api/support", headers=H(tok)).json()["thread"]
        if not th["typing"]:
            return th
        time.sleep(0.05)
    return th


mkuser("anna", "acme")
mkuser("root", "acme", super=True)
anna_t, root_t = login("anna"), login("root")

print("=== 1. Ассистент отвечает в тот же диалог ===")
check(c.get("/api/support", headers=H(anna_t)).json().get("bot") is True,
      "ключ есть — виджет знает, что ассистент на месте")
r = c.post("/api/support", headers=H(anna_t), json={"text": "Как перевести файл?", "tab": "editor"})
check(r.status_code == 200 and r.json().get("bot"), "сообщение принято, ответит ассистент")
th = settle(anna_t)
check([m["by"] for m in th["msgs"]] == ["user", "bot"], "в диалоге: вопрос и ответ ассистента")
check("Перевести" in th["msgs"][-1]["text"] and th["msgs"][-1]["name"] == "Ассистент",
      "текст ответа из JSON, имя — «Ассистент», не id модели")
check(sent == [], "Telegram на обычный вопрос не дёргается")
check(th["mode"] == "bot" and th["unread"] == 1, "диалог у ассистента, ответ непрочитан")

print("=== 2. Промпт собирает настоящий код ===")
kw = CALLS[-1]
sysp = kw["system"][0]["text"]
check(kw["model"] == "claude-opus-5-5", "модель — Opus 5.5")
check("ЧАСТЫЕ ВОПРОСЫ" in sysp and "250" in sysp, "в промпте инструкция сервиса (tutorial.py)")
check("НИКОГДА не называй" in sysp, "запрет называть модели и поставщиков")
check("открытая вкладка: editor" in sysp, "контекст: вкладка человека")
check(kw["messages"] == [{"role": "user", "content": "Как перевести файл?"}],
      "история — user/assistant, без системных строк")

print("=== 3. Передача человеку по решению ассистента ===")
ANSWER["text"] = json.dumps({"reply": "Позвал специалиста.", "handoff": True,
                             "reason": "оплата не дошла"}, ensure_ascii=False)
c.post("/api/support", headers=H(anna_t), json={"text": "Оплатил, страницы не пришли"})
th = settle(anna_t)
check(th["mode"] == "human", "диалог передан человеку")
check(len(sent) == 1 and "#d%d" % th["id"] in sent[0] and "оплата не дошла" in sent[0],
      "владельцу ушло уведомление с меткой треда и причиной")
check(main.support_mod.thread_for_reply(main.STATE, sent[0])["id"] == th["id"],
      "ответ на уведомление из Telegram найдёт этот диалог")
n = len(CALLS)
c.post("/api/support", headers=H(anna_t), json={"text": "Ну что там?"})
time.sleep(0.2)
check(len(CALLS) == n, "после передачи ассистент молчит")
check(len(sent) == 2 and "Ну что там?" in sent[-1], "сообщения идут владельцу как раньше")

print("=== 4. Админка: список, режим, ответ ===")
r = c.get("/api/admin/support", headers=H(anna_t))
check(r.status_code == 403, "не-суперу список диалогов закрыт")
r = c.get("/api/admin/support", headers=H(root_t)).json()
row = r["threads"][0]
check(row["mode"] == "human" and row["escalated"]["reason"] == "оплата не дошла" and row["fresh"],
      "строка: у человека, причина передачи, есть новое")
c.get("/api/admin/support?thread=%d" % row["id"], headers=H(root_t))
row = c.get("/api/admin/support", headers=H(root_t)).json()["threads"][0]
check(not row["fresh"], "открыл диалог — «новое» снято")
check(c.post("/api/admin/support/mode", headers=H(anna_t),
             json={"thread": row["id"], "mode": "bot"}).status_code == 403,
      "переключать режим — только суперу")
r = c.post("/api/admin/support/mode", headers=H(root_t), json={"thread": row["id"], "mode": "bot"})
check(r.status_code == 200 and r.json()["thread"]["mode"] == "bot", "вернул ассистенту")
c.post("/api/admin/support/reply", headers=H(root_t), json={"thread": row["id"], "text": "Зачислил."})
th = c.get("/api/support", headers=H(anna_t)).json()["thread"]
check(th["mode"] == "human" and th["msgs"][-1]["by"] == "support",
      "ответ из админки забирает диалог у ассистента")

print("=== 5. Сбой вызова — передача, а не тишина ===")
c.post("/api/admin/support/mode", headers=H(root_t), json={"thread": row["id"], "mode": "bot"})
ANSWER["fail"] = True
k = len(sent)
c.post("/api/support", headers=H(anna_t), json={"text": "Ещё вопрос"})
th = settle(anna_t)
ANSWER["fail"] = False
check(th["msgs"][-1]["by"] == "bot" and "специалист" in th["msgs"][-1]["text"],
      "человеку сказано, что позвали специалиста")
check(th["mode"] == "human" and len(sent) == k + 1, "владелец позван")

print("=== 6. «Позвать человека» и лимит клиента ===")
c.post("/api/admin/support/mode", headers=H(root_t), json={"thread": row["id"], "mode": "bot"})
r = c.post("/api/support/human", headers=H(anna_t))
check(r.status_code == 200 and r.json()["thread"]["mode"] == "human", "кнопка передаёт диалог")
c.post("/api/admin/support/mode", headers=H(root_t), json={"thread": row["id"], "mode": "bot"})
main._spend_add("acme", 5.0)
check(main._spend_status("acme")["over"], "лимит клиента исчерпан")
ANSWER["text"] = json.dumps({"reply": "Пополнить можно на «Организации».", "handoff": False})
c.post("/api/support", headers=H(anna_t), json={"text": "Где пополнить?"})
th = settle(anna_t)
check("Организации" in th["msgs"][-1]["text"], "ассистент отвечает и на исчерпанном лимите")

print("=== 7. Разбор ответа и история ===")
sb = main.support_bot_mod
check(sb.parse("просто текст") == ("просто текст", False, ""), "без JSON — текст как есть")
check(sb.parse('```json\n{"reply":"a","handoff":true,"reason":"r"}\n```') == ("a", True, "r"),
      "JSON в обёртке разбирается")
h = sb.history({"msgs": [{"by": "bot", "text": "x"}, {"by": "user", "text": "a"},
                         {"by": "user", "text": "b"}, {"by": "support", "text": "c", "name": "Шох"}]})
check([m["role"] for m in h] == ["user", "assistant"] and "a\n\nb" == h[0]["content"]
      and "специалиста" in h[1]["content"], "склейка подряд, ответ специалиста помечен")

print("=== 8. Правки по критику ===")
check(main.support_bot_mod.defuse("a\n💬 x #d7", "💬") == "a\n[💬] x #d7"
      and main.support_mod.thread_for_reply(
          main.STATE, main.support_mod.notify_text({"id": 1}, "a", "t", "b\n💬 x #d999")
      )["id"] == 1, "знак заголовка в тексте клиента не уводит ответ в чужой диалог")
main._USAGE_SINK = sink = {}
c.post("/api/admin/support/mode", headers=H(root_t), json={"thread": row["id"], "mode": "bot"})
c.post("/api/support", headers=H(anna_t), json={"text": "Вопрос во время прогона"})
settle(anna_t)
main._USAGE_SINK = None
check(sink == {}, "расход ассистента не ложится в счётчик идущего прогона")
main.SUPPORT_BOT_PER_HOUR, n = 1, len(CALLS)
k = len(sent)
c.post("/api/support", headers=H(anna_t), json={"text": "Ещё и ещё"})
time.sleep(0.2)
check(len(CALLS) == n and len(sent) == k + 1, "сверх потолка в час — не ассистент, а владельцу")
main.SUPPORT_BOT_PER_HOUR = 12
main.tg_mod.enabled = lambda: False
check(c.get("/api/support", headers=H(anna_t)).json()["bot"] is False,
      "без Telegram ассистент не включается: передать было бы некому")

print()
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: %d" % len(fail))
sys.exit(1 if fail else 0)
