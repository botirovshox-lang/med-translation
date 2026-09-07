# -*- coding: utf-8 -*-
"""Знание рождается В ПРОЕКТЕ, а на всю организацию его переводит человек.

Зачем. Единый на организацию глоссарий верен ровно до второго клиента:
у медицинского учебника и у договора поставки «сторона», «заключение»
и «показание» значат разное, а переводчики держат свои устоявшиеся варианты.
Общий словарь превращает это в спор, которого никто не заказывал: термин,
одобренный в одном проекте, начинает ПРИКАЗЫВАТЬ в другом.

Устройство. У записи глоссария, у пары в памяти переводов и у карточки
в очереди терминов появляется необязательное поле `project`:

    поля нет  →  знание всей организации (закон миграции lang/domain:
                 боевые данные не переписываются, а читаются по-старому);
    число     →  знание живёт только в этом проекте.

Новое знание рождается ПРОЕКТНЫМ, потому что иначе первая же находка одного
переводчика становится правилом для всех. Расширить его до организации —
отдельное решение человека («по желанию клиента»), и оно обратимо.

Что сторожится и почему именно это:

  1. Запись БЕЗ поля видна всем — иначе выкат обнулил бы весь работающий
     глоссарий боевого клиента.
  2. Проектная запись не видна соседу НИ ОДНИМ путём: ни промптом
     (`_get_context`), ни требованием (`_verified_hits`). Второй путь
     отдельно, потому что по нему считаются нарушения и ходит ремонт:
     невидимая в промпте, но требуемая проверкой запись — это вечное
     «расходится с глоссарием», которое нечем закрыть.
  3. Два проекта держат РАЗНЫЕ переводы одного термина ОДНОВРЕМЕННО. Ради
     этого проект и входит в КЛЮЧ, а не в фильтр: с фильтром вторая запись
     просто не завелась бы — «такая уже есть».
  4. Очередь терминов у каждого проекта своя, и решение в одном проекте
     не закрывает вопрос в другом: ответ «да» про договор ничего не говорит
     про учебник.
  5. Память переводов — то же самое: подтверждение в соседнем проекте
     не переписывает чужую пару. Это единственное место, где чужой текст
     попадал в перевод мимо глоссария и мимо всех проверок.
  6. Продвижение и возврат — обратимые решения человека, и они не выходят
     за организацию.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "test-gproject-password"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main.STATE["tm"] = []
main.STATE["termQueue"] = []
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
TOK = c.post("/api/auth/login", json={"login": "admin",
                                      "password": "test-gproject-password"}).json()["token"]
A = {"id": 101, "tenant": "default", "title": "Учебник", "src": "RU", "tgt": "EN",
     "domain": "medical", "segments": []}
B = {"id": 102, "tenant": "default", "title": "Договор", "src": "RU", "tgt": "EN",
     "domain": "medical", "segments": []}
main.STATE["projects"] = [A, B]


def term(src, tgt, project=None, tier="verified"):
    g = {"id": len(main.STATE["glossary"]) + 1, "src": src, "tgt": tgt,
         "lang": "RU→EN", "domain": "medical", "tenant": "default", "tier": tier}
    if project is not None:
        g["project"] = project
    main.STATE["glossary"].append(g)
    main._invalidate_gloss_index()
    return g


print("=== 1. Запись без поля — знание всей организации ===")
term("сторона", "party")
hits_a = [h["src"] for h in main._get_context("сторона договора", False, A)[0]]
hits_b = [h["src"] for h in main._get_context("сторона договора", False, B)[0]]
check("сторона" in hits_a and "сторона" in hits_b,
      "старая запись без поля видна ОБОИМ проектам — иначе выкат обнулил бы "
      "работающий глоссарий боевого клиента")

print("\n=== 2. Проектная запись не видна соседу ни одним путём ===")
term("заключение", "conclusion", project=101)
a_ctx = [h["src"] for h in main._get_context("заключение комиссии", False, A)[0]]
b_ctx = [h["src"] for h in main._get_context("заключение комиссии", False, B)[0]]
check("заключение" in a_ctx, "в своём проекте запись работает")
check("заключение" not in b_ctx, "в соседнем — нет (промпт)")
a_req = [h["src"] for h in main._verified_hits("заключение комиссии", A)]
b_req = [h["src"] for h in main._verified_hits("заключение комиссии", B)]
check("заключение" in a_req, "и требуется в своём проекте")
check("заключение" not in b_req,
      "и НЕ требуется в соседнем: иначе там навсегда «расходится с глоссарием»")

print("\n=== 3. Два проекта держат разные переводы одного термина ===")
term("показание", "indication", project=101)
term("показание", "testimony", project=102)
a_tgt = [h["tgt"] for h in main._verified_hits("показание к операции", A)]
b_tgt = [h["tgt"] for h in main._verified_hits("показание к операции", B)]
check(a_tgt == ["indication"], "в учебнике — медицинское значение: " + str(a_tgt))
check(b_tgt == ["testimony"], "в договоре — юридическое: " + str(b_tgt))
check(len([g for g in main.STATE["glossary"] if g["src"] == "показание"]) == 2,
      "обе записи существуют ОДНОВРЕМЕННО: проект входит в КЛЮЧ, а не в фильтр")

print("\n=== 4. Проектная запись СИЛЬНЕЕ общей в своём проекте ===")
term("сторона", "side", project=102)
b_side = [h["tgt"] for h in main._verified_hits("сторона договора", B)]
a_side = [h["tgt"] for h in main._verified_hits("сторона договора", A)]
check(b_side == ["side"], "проект переопределил общую запись: " + str(b_side))
check(a_side == ["party"], "у соседа осталась общая: " + str(a_side))

print("\n=== 5. Очередь терминов у каждого проекта своя ===")
main.STATE["termQueue"] = []
for pid in (101, 102):
    main._queue_term("extract", "иск", "claim", lang="RU→EN", domain="medical",
                     tenant="default", project=pid, segment=1, via="auto")
cards = main._term_queue()
check(len(cards) == 2, "два проекта — две карточки, а не одна на двоих: " + str(len(cards)))
check({x.get("project") for x in cards} == {101, 102}, "и каждая знает свой проект")
main._queue_term("extract", "иск", "claim", lang="RU→EN", domain="medical",
                 tenant="default", project=101, segment=2, via="auto")
check(len(main._term_queue()) == 2, "повтор в СВОЁМ проекте карточку не плодит")
own = [x for x in main._term_queue() if x.get("project") == 101][0]
check(own.get("hits", 1) == 2, "он только растит счётчик своей карточки")

print("\n=== 6. Решение в одном проекте не закрывает вопрос в другом ===")
main.STATE["glossary"] = [g for g in main.STATE["glossary"] if g["src"] != "иск"]
main._invalidate_gloss_index()
decided = [x for x in main._term_queue() if x.get("project") == 101][0]
decided["status"], decided["decidedBy"] = "approved", 1
term("иск", "claim", project=101)
other = [x for x in main._term_queue() if x.get("project") == 102][0]
check(other.get("status", "pending") == "pending",
      "карточка соседнего проекта осталась открытой: ответ про договор ничего "
      "не говорит про учебник")

print("\n=== 7. Память переводов: чужой проект не переписывает пару ===")
main.STATE["tm"] = []
main._tm_upsert("Стороны согласовали", "The parties agreed", A)
main._tm_upsert("Стороны согласовали", "The sides have agreed", B)
check(len(main.STATE["tm"]) == 2, "две записи, а не одна переписанная: " + str(len(main.STATE["tm"])))
hit_a = main._get_context("Стороны согласовали", True, A)[1]
hit_b = main._get_context("Стороны согласовали", True, B)[1]
check(hit_a and hit_a["tgt"] == "The parties agreed", "каждый проект видит свою: " + str(hit_a and hit_a["tgt"]))
check(hit_b and hit_b["tgt"] == "The sides have agreed", "и второй тоже: " + str(hit_b and hit_b["tgt"]))
main._tm_upsert("Стороны согласовали", "The parties have agreed", A)
check(len(main.STATE["tm"]) == 2, "правка в своём проекте новой записи не плодит")
check(main._get_context("Стороны согласовали", True, B)[1]["tgt"] == "The sides have agreed",
      "и не трогает соседнюю")

print("\n=== 8. Продвижение и возврат — решения человека ===")
r = c.post("/api/glossary/promote", headers=H(TOK),
           json={"src": "заключение", "lang": "RU→EN", "domain": "medical", "project": 101})
check(r.status_code == 200 and r.json().get("ok"), "продвижение прошло: " + r.text[:90])
b_ctx = [h["src"] for h in main._verified_hits("заключение комиссии", B)]
check("заключение" in b_ctx, "запись стала видна всей организации")
check(main._glossary_entry("заключение", ("RU→EN", "medical", "default")).get("project") is None,
      "поле снято, а не переписано на другой проект")
r = c.post("/api/glossary/restrict", headers=H(TOK),
           json={"src": "заключение", "lang": "RU→EN", "domain": "medical", "project": 101})
check(r.status_code == 200, "возврат в проект прошёл")
check("заключение" not in [h["src"] for h in main._verified_hits("заключение комиссии", B)],
      "и сосед снова её не видит")
check(c.post("/api/glossary/restrict", headers=H(TOK),
             json={"src": "заключение", "lang": "RU→EN", "domain": "medical",
                   "project": 999}).status_code == 404,
      "чужой проект — 404, а не молчаливая привязка")

print("\n=== 9. Что стоит продвинуть, предлагает система, а решает человек ===")
# Одна и та же пара, независимо утверждённая в РАЗНЫХ проектах, — это уже
# не мнение одного переводчика. Предложение, а не приказ: машина сама себе
# приказа не даёт (инвариант 8).
term("акт", "statement of work", project=101)
term("акт", "statement of work", project=102)
term("накладная", "waybill", project=101)
r = c.get("/api/glossary/promotions", headers=H(TOK)).json()
srcs = {x["src"] for x in r["items"]}
check("акт" in srcs, "пара из двух разных проектов предложена к продвижению")
check("накладная" not in srcs, "пара из одного проекта — нет: это мнение одного проекта")
check(all(x["projects"] and len(x["projects"]) >= 2 for x in r["items"]),
      "и у каждого предложения названы проекты, где пара сошлась")
check(all("tier" in x for x in r["items"]), "и уровень доверия — продвигают приказ, а не догадку")

print("\n=== 10. Продвижение не выходит за организацию ===")
main.STATE["tenants"].append({"id": "acme", "name": "ACME", "active": True})
g = term("реестр", "register", project=101)
g["tenant"] = "acme"
main._invalidate_gloss_index()
r = c.post("/api/glossary/promote", headers=H(TOK),
           json={"src": "реестр", "lang": "RU→EN", "domain": "medical", "project": 101})
check(r.status_code == 404, "чужую запись не продвинуть: " + str(r.status_code))
check(g.get("project") == 101, "и она не тронута")

print("\n" + ("ПРОВАЛЕНО: " + "; ".join(fail) if fail else "ВСЁ ПРОШЛО"))
sys.exit(1 if fail else 0)
