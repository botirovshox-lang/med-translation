# -*- coding: utf-8 -*-
"""Тест-группа: анкеты, инструкция, лист ответов и выдача доступа ботом.

Что сторожится и почему именно это:

  1. НИКА ВЛАДЕЛЬЦА НЕТ НИ НА ОДНОЙ СТРАНИЦЕ. Ровно ради этого анкеты и
     переехали к нам из артефактов: там доставка была «скопируй и пришли
     в личку», и ник приходилось печатать в разметке. Вернётся он — вернётся
     и то, от чего уходили, а заметить это глазами нельзя: страница выглядит
     точно так же.
  2. Вопросы, текст для Telegram и лист ответов считаются ПО ОДНОМУ дереву.
     Разойдись они — владелец читал бы одни формулировки, а отвечавший видел
     другие, и спорить было бы не о чем.
  3. Лист ответов отмечает РОВНО выбранное. Он показывает и невыбранные
     варианты намеренно: ответ «Терпимо» без соседних вариантов не значит
     ничего — непонятно, из чего выбирали.
  4. Анкеты и наборы НЕ уходят в /api/seed. Это тот же закон, что у
     приглашений: в анкете лежат имя, Telegram и мнение постороннего
     человека, а `/api/seed` отдаёт каждому вошедшему всё, что не названо.
  5. Приём анкеты — единственная неаутентифицированная запись в состояние,
     значит у неё обязаны быть потолки: частота с адреса и размер тела.
  6. Тестировщик получает СВОЮ организацию (инвариант 11: организация и есть
     единица изоляции), роль `translator`, отметку `simple` и язык с
     признаком `uiLangSet` — иначе поздняя миграция вернёт ему русский
     экран (инвариант 19).
  7. Мест в наборе ровно столько, сколько назначил владелец: набор без
     свободных мест доступа не выдаёт.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys, json
os.environ["APP_PASSWORD"] = "test-survey-password"
os.environ["TG_SERVICE_TOKEN"] = "test-service-token"
sys.path.insert(0, "backend")
import main
import survey
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.TG_SERVICE_TOKEN = "test-service-token"
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["surveys"] = []
main.STATE["testBatches"] = []
main._SESSIONS.clear()
main._SURVEY_HITS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
main._ensure_users()
tok = c.post("/api/auth/login", json={"login": "admin",
                                      "password": "test-survey-password"}).json()["token"]
H = {"Authorization": "Bearer " + tok}
SVC = {"X-Service-Token": "test-service-token"}


print("=== 1. Ника владельца нет ни на одной странице ===")
# Строку ищем по существу, а не по конкретному нику: любая ссылка вида
# t.me/… и любая собачка с именем — это дверь в чужую личку.
pages = {}
for path in ("/t/apply", "/t/debrief", "/t/guide"):
    for lang in ("ru", "uz"):
        r = c.get(path + "?lang=" + lang)
        check(r.status_code == 200, "страница %s (%s) отдаётся" % (path, lang))
        pages[path + lang] = r.text
for key, html in pages.items():
    check("t.me/" not in html, "нет ссылки t.me на " + key)
    check("shox" not in html.lower(), "нет ника владельца на " + key)
    check("telegram.org" not in html, "нет прямой ссылки в Telegram на " + key)

print("\n=== 2. Опрос спрашивает то же, что уходит владельцу ===")
apply_ru = pages["/t/applyru"]
for q in survey.APPLY["questions"]:
    txt = (q.get("ru") or {}).get("q", "")
    check(json.dumps(txt, ensure_ascii=False)[1:-1] in apply_ru or txt in apply_ru,
          "вопрос на странице: " + txt[:40])

answers = {"contact.name": "Азиз", "contact.tg": "@aziz",
           "work.pairs": ["RU-UZ"], "work.topics": ["med", "law"],
           "years": "3-7", "cat": "word", "doc": "yes", "hours": "3-5",
           "pain": "Заказчик присылает PDF"}
rec = {"form": "apply", "lang": "ru", "at": "2026-09-07 10:00", "who": "",
       "answers": answers, "consent": {"data": True, "call": False}, "token": "tk"}
txt = survey.summary_text(rec, "https://example.test/t/a/tk")
check("Азиз" in txt and "@aziz" in txt, "в тексте для Telegram есть контакты")
check("Медицина" in txt and "Договоры и юр. документы" in txt,
      "выбранные варианты названы словами, а не кодами")
check("3–7 лет" in txt, "выбранный вариант списка попал в текст")
check("Нет, перевожу в Word" in txt, "и второй список тоже")
check("[x] " in txt and "[ ] " in txt, "согласия отмечены обе стороны")
check("https://example.test/t/a/tk" in txt, "ссылка на полный лист приложена")
check("Художественный" not in txt, "невыбранное в текст не попало")

print("\n=== 3. Лист ответов отмечает ровно выбранное ===")
page = survey.answers_page(rec, "ru")
import re as _re
chosen = _re.findall(r'class="opt (?:box )?on"[^>]*><span class="tick"></span><span>([^<]+)', page)
check("Медицина" in chosen and "Договоры и юр. документы" in chosen,
      "выбранные варианты отмечены: " + str(chosen[:4]))
check("Художественный" not in chosen, "невыбранное не отмечено")
check("Художественный" in page, "но невыбранное ПОКАЗАНО: иначе ответ не прочитать")
check("Заказчик присылает PDF" in page, "свободный текст на листе")

print("\n=== 4. Анкеты и наборы не уходят в /api/seed ===")
main.STATE["surveys"].append(dict(rec, id=1, ip="1.2.3.4"))
main.STATE["testBatches"].append({"id": "b1", "name": "Первый", "limit": 2, "issued": 0,
                                  "pages": 30, "limitUsd": 5, "active": True, "log": []})
seed = c.get("/api/seed", headers=H).json()
check("surveys" not in seed, "/api/seed не отдаёт анкеты")
check("testBatches" not in seed, "/api/seed не отдаёт наборы")
check("Азиз" not in json.dumps(seed, ensure_ascii=False), "имени из анкеты в выдаче нет")
main.STATE["surveys"] = []

print("\n=== 5. Приём анкеты: потолки на месте ===")
body = {"form": "apply", "lang": "ru", "answers": answers, "consent": {"data": True}}
r = c.post("/api/public/survey", json=body)
check(r.status_code == 200 and r.json().get("token"), "анкета принята без входа в систему")
token = r.json()["token"]
check(c.get("/t/a/" + token).status_code == 200, "лист по выданной ссылке открывается")
check(c.get("/t/a/нет-такого").status_code == 404, "чужая ссылка — 404")
big = dict(body, answers={"pain": "я" * 30000})
check(c.post("/api/public/survey", json=big).status_code == 413, "слишком длинное тело — 413")
check(c.post("/api/public/survey", json=dict(body, form="выдуманная")).status_code == 404,
      "выдуманная анкета — 404")
codes = [c.post("/api/public/survey", json=body).status_code for _ in range(8)]
check(429 in codes, "частые отправки с одного адреса упираются в потолок")
main._SURVEY_HITS.clear()

print("\n=== 6. Бот заводит тестировщика: своя организация, свой язык ===")
r = c.post("/api/tg/tester", json={"lang": "uz", "chat": 111, "username": "aziz",
                                   "name": "Азиз"}, headers=SVC)
check(r.status_code == 200 and r.json().get("ok"), "доступ выдан: " + r.text[:120])
got = r.json()
u = main._user_by_login(got["login"])
t = main._tenant_rec(got["tenant"])
check(u is not None and t is not None, "учётная запись и организация заведены")
check(u["role"] == "translator", "роль переводчика, а не владельца")
check(u.get("uiLang") == "uz" and u.get("uiLangSet") is True,
      "выбранный язык помечен решением человека (иначе миграция его вернёт)")
check(t.get("simple") is True and t.get("tester") is True, "организация помечена тестовой")
check(t.get("pagesCredit") == 30 and t.get("pagesUsed") == 0.0,
      "страницы выданы точным числом набора: " + str(t.get("pagesCredit")))
check(len(got["password"]) >= 12, "пароль не короче 12 знаков")
check(main._verify_password(u, got["password"]), "выданный пароль действительно подходит")
if main.legal_mod:
    check((u.get("acceptedTerms") or {}).get("via") == "telegram",
          "согласие с офертой оставило след")

r2 = c.post("/api/tg/tester", json={"lang": "ru", "chat": 222, "username": "b"}, headers=SVC)
check(r2.status_code == 200, "второй тестировщик тоже заведён")
check(r2.json()["tenant"] != got["tenant"], "у каждого СВОЯ организация")

print("\n=== 7. Мест ровно столько, сколько назначил владелец ===")
r3 = c.post("/api/tg/tester", json={"lang": "ru", "chat": 333}, headers=SVC)
check(r3.status_code == 409 and r3.json().get("code") == "full",
      "третьему в наборе на два места отказано: " + r3.text[:80])
check(len(main._users()) == 3, "лишней учётной записи не появилось (админ + двое)")
b = main._active_batch()
r4 = c.post("/api/admin/testing/batches/b1", json={"limit": 1}, headers=H)
check(r4.status_code == 200 and b["limit"] == 2,
      "лимит нельзя опустить ниже уже выданного: " + str(b["limit"]))
r5 = c.post("/api/admin/testing/batches/b1", json={"limit": 3}, headers=H)
check(r5.status_code == 200 and main._batch_free(b) == 1, "поднять лимит можно")
b["active"] = False
r6 = c.post("/api/tg/tester", json={"lang": "ru", "chat": 444}, headers=SVC)
check(r6.status_code == 409 and r6.json().get("code") == "closed",
      "при закрытом наборе доступ не выдаётся")
b["active"] = True

print("\n=== 8. Служебная дверь закрыта для всех, кроме бота ===")
check(c.post("/api/tg/tester", json={"lang": "ru"}).status_code == 401,
      "без служебного токена — 401")
check(c.post("/api/tg/tester", json={"lang": "ru"},
             headers={"X-Service-Token": "wrong-token"}).status_code == 401,
      "с чужим токеном — 401")
# Обход входа — это РАЗРЕШЕНИЕ для бота, а не право для всех вошедших:
# без явного отказа любой пользователь (в том числе сам тестировщик)
# заводил бы себе организации с выданными страницами, пока есть места,
# и получал бы логин с паролем прямо в ответе.
check(c.post("/api/tg/tester", json={"lang": "ru"}, headers=H).status_code == 401,
      "вошедшему владельцу служебная дверь тоже закрыта")
check(c.get("/api/tg/state", headers=H).status_code == 401,
      "и чтение состояния бота (там telegram-id людей) — тоже")
# Не-ASCII в служебном заголовке проверяется в tests/test_routes.py напрямую:
# httpx такой заголовок не отправляет вовсе, а сервер обязан отвечать 401,
# а не 500 (`compare_digest` бросает TypeError на строке с кириллицей).
check(c.get("/api/tg/state", headers=SVC).status_code == 200, "боту состояние отдаётся")
st = c.get("/api/tg/state", headers=SVC).json()
check(st["batch"]["free"] == 1, "бот видит свободные места")

print("\n=== 8b. Публичная страница не выпускает чужой скрипт ===")
# Значения who/ref приходят из АДРЕСА и вставляются внутрь тега script.
# json.dumps экранирует кавычки, но не последовательность, закрывающую сам
# тег: строка с закрывающим тегом выходила из скрипта в разметку. Страницу
# отдаёт ТОТ ЖЕ адрес, что и приложение, где в хранилище браузера лежит
# токен сессии, — то есть это была бы кража доступа по ссылке.
bad = "</" + "script><img src=x onerror=alert(1)>"
page = c.get("/t/apply", params={"lang": "ru", "who": bad, "ref": bad}).text
check(page.count("<script") == 1 and page.count("</" + "script>") == 1,
      "тег script в странице ровно один: из него не вышли")
check(bad not in page, "закрывающий тег из адреса в разметку не попал")
check("u003c" in page, "он экранирован именем, а не вырезан: значение доедет до страницы")
check("@aziz" in c.get("/t/apply", params={"lang": "ru", "who": "@aziz"}).text,
      "а обычное значение подставляется как было")

print("\n=== 9. Разбор снимает вопрос «вы уже протестировали?» ===")
main._SURVEY_HITS.clear()
c.post("/api/public/survey", json={"form": "debrief", "lang": "ru", "ref": "tg111",
                                   "who": "@aziz", "answers": {"overall": "4"}})
st = c.get("/api/tg/state", headers=SVC).json()
check("tg111" in st["submitted"], "заполнивший разбор назван боту")
check("tg222" not in st["submitted"], "не заполнивший — нет")

print("\n=== 10. Админка видит набор, тестировщиков и анкеты ===")
r = c.get("/api/admin/testing", headers=H)
check(r.status_code == 200, "сводка отдаётся владельцу-суперпользователю")
ov = r.json()
check(len(ov["testers"]) == 2, "оба тестировщика в списке")
check(all(x["tenant"] and x["usage"] for x in ov["testers"]), "у каждого видно организацию и объём")
check(len(ov["surveys"]) >= 2, "анкеты в списке")
check(all("answers" not in s for s in ov["surveys"]),
      "в списке только шапки анкет, ответы — по ссылке")

print("\n" + ("ПРОВАЛЕНО: " + "; ".join(fail) if fail else "ВСЁ ПРОШЛО"))
sys.exit(1 if fail else 0)
