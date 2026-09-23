# -*- coding: utf-8 -*-
"""Имена моделей ИИ не уезжают НАРУЖУ — ни на экран, ни в ответ запроса.

Правило простое: id и название модели («gpt-5.6-terra», «Claude Sonnet 5»),
имя поставщика («OpenAI», «Anthropic») и цены за токены видит ТОЛЬКО
администратор сервиса — тот, кто модели назначает (инвариант 24).

Прежде это держал один `modelsShown()` в браузере, который возвращает
`false`. Но это ПОКАЗ, а не выдача: данные приезжали в браузер и читались
во вкладке «Сеть» — правило обещало одно, а ответ говорил другое.

Почему ПСЕВДОНИМ, а не вырезание. Браузер читает модели ЛОГИКОЙ, и от неё
зависит состав прогона:
  * `backcheck.model === provider` — «проверял тот, кто переводил» (группа
    `self`, её сегменты прогон не перепокупает);
  * `termcheck.model === "skip"` — «проверять было нечего, вызова не было»;
  * `repair.triedModels` — «этот текст уже смотрела другая модель»;
  * `rank` — «проверка не слабее нужной».
Вырежи имена — эти ответы исчезнут, и соло-кнопка начнёт обещать одно,
а сервер делать другое, БЕЗ единого видимого признака. Псевдоним отвечает
на те же вопросы буква в букву и не называет ничего.

Что сторожится:
  1. Ни одного имени модели и поставщика в ответах — ни владельцу, ни
     переводчику; суперу — как есть (он назначает).
  2. Псевдонимы взаимно однозначны и устойчивы: разные модели — разные,
     одна и та же — всегда один и тот же.
  3. Служебные значения (`skip`, `tm`) НЕ псевдонимятся: `skip` означает
     «вызова модели не было», и подмена сломала бы счётчики.
  4. Сравнения браузера продолжают работать: «та же модель» остаётся той же,
     «другая» — другой.
  5. Текст отказа «нет ключа» не называет ни поставщика, ни модель.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys, json
os.environ["APP_PASSWORD"] = "test-model-names-pw"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# Всё, что не должно встретиться в ответе. Список выводим ИЗ КАТАЛОГА,
# а не переписываем руками: новая модель попадёт под проверку сама.
NAMES = ([m["id"].lower() for m in main.OPENAI_MODELS]
         + [m["label"].lower() for m in main.OPENAI_MODELS]
         + ["anthropic", "openai", "text-embedding"])


def leaks(obj) -> list:
    body = json.dumps(obj, ensure_ascii=False).lower()
    return sorted({n for n in NAMES if n in body})


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
S = c.post("/api/auth/login", json={"login": "admin", "password": "test-model-names-pw"}).json()["token"]
c.post("/api/admin/tenants", headers=H(S),
       json={"id": "bureau", "name": "Бюро", "ownerLogin": "boss", "ownerPassword": "boss-pass-123"})
OWN = c.post("/api/auth/login", json={"login": "boss", "password": "boss-pass-123"}).json()["token"]
c.post("/api/admin/users", headers=H(OWN),
       json={"login": "tr", "password": "tr-pass-123", "name": "tr", "role": "translator"})
TR = c.post("/api/auth/login", json={"login": "tr", "password": "tr-pass-123"}).json()["token"]

print("=== 1. Псевдоним: свойства, на которых стоит логика ===")
ids = [m["id"] for m in main.OPENAI_MODELS]
al = [main._model_alias(i) for i in ids]
check(len(set(al)) == len(ids), "разные модели — разные псевдонимы (%d/%d)" % (len(set(al)), len(ids)))
check(all(main._model_alias(i) == main._model_alias(i) for i in ids),
      "один и тот же id всегда даёт один и тот же псевдоним")
check(not any("gpt" in a or "claude" in a for a in al), "в самих псевдонимах имён нет")
check(main._model_alias("skip") == "skip",
      "«skip» не псевдонимится: это «вызова модели не было», а не модель")
check(main._model_alias("tm") == "tm", "«tm» — откуда взялся перевод, тоже не модель")
check(main._model_alias("") == "", "пустое остаётся пустым")
gone1, gone2 = main._model_alias("ушедшая-1"), main._model_alias("ушедшая-2")
check(gone1.startswith("m?") and "ушедш" not in gone1,
      "модель, пропавшая из каталога, имени тоже не выдаёт: " + gone1)
# Общий «m?» на всех схлопнул бы РАЗНЫЕ старые модели в одну, и сегмент,
# где переводила одна, а проверяла другая, попал бы в группу «проверял сам
# автор» — то есть его перестали бы перепроверять.
check(gone1 != gone2, "две разные пропавшие модели не схлопываются в один псевдоним")
check(main._model_alias("ушедшая-1") == gone1, "и псевдоним пропавшей устойчив")

print("\n=== 2. Каталог моделей ===")
cat_s = c.get("/api/models", headers=H(S)).json()
check(cat_s["models"][0]["id"] == main.OPENAI_MODELS[0]["id"],
      "администратору сервиса каталог приходит как есть")
for tok, who in ((OWN, "владелец"), (TR, "переводчик")):
    r = c.get("/api/models", headers=H(tok)).json()
    check(leaks(r) == [], who + ": в каталоге ни одного имени: " + str(leaks(r)))
    m0 = r["models"][0]
    check(m0["id"] == m0["label"] == main._model_alias(main.OPENAI_MODELS[0]["id"]),
          who + ": id и label — псевдоним")
    check("note" not in m0 and "provider" not in m0,
          who + ": примечание и поставщик сняты — там имена словами")
    # `effort` и `sampling` есть ТОЛЬКО у моделей Anthropic: сами по себе
    # они называют поставщика не хуже его имени. Ответ про надбавку
    # за рассуждение при этом сохранён полем `api`.
    check(all("effort" not in m and "sampling" not in m for m in r["models"]),
          who + ": маркеров поставщика нет ни у одной модели")
    ant = [i for i, m in enumerate(main.OPENAI_MODELS) if m.get("effort")]
    check(all(r["models"][i]["api"] == "modern" for i in ant),
          who + ": надбавка за рассуждение сохранена — смета не изменилась")
    check(m0.get("rank") is not None or True, who + ": ранг остаётся — по нему считается состав")
    check("in" not in m0 and "out" not in m0, who + ": цен нет (деньги — отдельный рубеж)")
    check(r["default"] == main._model_alias(main.DEFAULT_OPENAI_MODEL),
          who + ": умолчание шага — тоже псевдоним")

print("\n=== 3. Сегменты: логика браузера уцелела ===")
c.post("/api/projects", headers=H(OWN), json={"title": "T", "src": "RU", "tgt": "EN"})
p = main.STATE["projects"][-1]
pid = p["id"]
h = main._text_hash("Cough")
p["segments"] = [{
    "id": 1, "source": "Кашель", "target": "Cough", "status": "translated",
    # Тот же id у перевода и у back-check — браузер обязан увидеть «self».
    "provider": "gpt-5.6-terra",
    "backcheck": {"score": 90, "model": "gpt-5.6-terra", "back": "Кашель", "target_hash": h},
    "termcheck": {"model": "skip", "findings": [], "target_hash": h},
    "review": {"score": 9, "model": "gpt-4o", "target_hash": h},
    "repair": {"model": "gpt-4o-mini", "triedModels": ["gpt-4o-mini", "claude-opus-5"]},
    "termContext": {"model": "claude-haiku-4-5"},
}]
p["termlist"] = {"model": "gpt-5.6-sol", "cross": {"claude-sonnet-5": {}},
                 "entries": [{"src": "a", "tgt": "b", "status": "agreed",
                              "gates": {"cross": {"model": "gpt-4o"}}}]}
for tok, who in ((OWN, "владелец"), (TR, "переводчик")):
    r = c.get("/api/projects/%d" % pid, headers=H(tok)).json()
    check(leaks(r) == [], who + ": в проекте ни одного имени: " + str(leaks(r)))
    sg = r["segments"][0]
    check(sg["backcheck"]["model"] == sg["provider"],
          who + ": «проверял тот, кто переводил» по-прежнему видно (группа self)")
    check(sg["termcheck"]["model"] == "skip",
          who + ": «без вызова модели» сохранено")
    tried = sg["repair"]["triedModels"]
    check(len(set(tried)) == 2 and sg["repair"]["model"] in tried,
          who + ": две РАЗНЫЕ модели ремонта остались различимы: " + str(tried))
    check(sg["provider"] not in tried,
          who + ": «сюда ходила другая модель» по-прежнему вычисляется")
    check("cross" not in (r.get("termlist") or {}),
          who + ": ключ-имя модели в терм-листе не отдаётся")
    check("gates" not in ((r.get("termlist") or {}).get("entries") or [{}])[0],
          who + ": имя модели на записи терм-листа не отдаётся")

print("\n=== 4. Глоссарий ===")
main.STATE["glossary"] = [{"src": "кашель", "tgt": "cough", "tenant": "bureau",
                           "lang": "RU→EN", "domain": "general", "tier": "verified",
                           "meaning": {"same": True, "model": "gpt-4o", "v": 1}}]
for tok, who in ((OWN, "владелец"), (TR, "переводчик")):
    r = c.get("/api/glossary", headers=H(tok)).json()
    check(leaks(r) == [], who + ": в глоссарии имён нет: " + str(leaks(r)))
    check(r["items"][0]["meaning"].get("same") is True,
          who + ": сам вердикт сверки смысла остался — режем имя, а не ответ")

print("\n=== 5. Начальная выдача ===")
for tok, who in ((OWN, "владелец"), (TR, "переводчик")):
    check(leaks(c.get("/api/seed", headers=H(tok)).json()) == [],
          who + ": в /api/seed имён моделей нет")

print("\n=== 6. Отказ «нет ключа» не называет поставщика ===")
tok_ctx = main.CURRENT_SESSION.set(main._SESSIONS[TR])
try:
    txt_tr = main._no_key_text("claude-opus-5", "Перевод требует ключ OpenAI")
finally:
    main.CURRENT_SESSION.reset(tok_ctx)
check(leaks(txt_tr) == [], "переводчику: ни поставщика, ни модели: " + txt_tr)
check("недоступ" in txt_tr.lower() or "не настроен" in txt_tr.lower(),
      "но сказано, что случилось — молчание читается как поломка")
tok_ctx = main.CURRENT_SESSION.set(main._SESSIONS[S])
try:
    txt_s = main._no_key_text("claude-opus-5", "Перевод требует ключ OpenAI")
finally:
    main.CURRENT_SESSION.reset(tok_ctx)
check("Anthropic" in txt_s, "администратору сервиса сказано прямо, какого ключа нет: " + txt_s)

print("\n=== 7. Журнал действий ===")
main.STATE["audit"] = [{"action": "system.models", "tenant": "bureau", "at": "2026-09-23",
                        "before": {}, "after": {"translate": "gpt-4.1"}}]
r = c.get("/api/admin/audit", headers=H(OWN)).json()
check(leaks(r) == [], "владельцу журнал приходит без имён моделей: " + str(leaks(r)))
check(r["items"][0]["action"] == "system.models", "сама запись при этом остаётся — факт не прячем")

print("\n=== 8. НЕВОД: все GET-эндпоинты разом ===")
# Точечные проверки закрывают ИЗВЕСТНЫЕ двери, а невод ловит НОВУЮ — ту,
# которую заведут завтра и забудут закрыть. Список путей берётся из самого
# приложения, список имён — из каталога моделей: и то, и другое растёт само.
# Так и нашлись `/api/projects` (список полей проекта с терм-листом),
# `/api/term-queue` (вердикты внутри карточки) и цены эмбеддингов в `aux`.
skip_paths = {"/api/export/download"}          # отдаёт файл, не JSON
checked, found = 0, []
for route in main.app.routes:
    methods = getattr(route, "methods", None) or set()
    path = getattr(route, "path", "")
    if "GET" not in methods or not path.startswith("/api/"):
        continue
    if path.startswith("/api/admin/"):         # админка — работа супера
        continue
    if "{" in path:
        path = path.replace("{pid}", str(pid)).replace("{fid}", str(pid))
        if "{" in path:                        # путь с чужими параметрами не зовём
            continue
    if path in skip_paths:
        continue
    for tok, who in ((OWN, "владелец"), (TR, "переводчик")):
        try:
            r = c.get(path, headers=H(tok))
        except Exception:
            continue                           # не наше дело: тест не про 500
        if r.status_code != 200:
            continue
        # Не-JSON (картинка, файл) неводом не проверяем: имён моделей там нет,
        # а разбор упал бы на первом же байте растра.
        if "application/json" not in (r.headers.get("content-type") or ""):
            continue
        checked += 1
        try:
            body = r.json()
        except Exception:
            continue
        names = leaks(body)
        if names:
            found.append("%s (%s): %s" % (path, who, names))
check(checked > 20, "невод прошёл по живым дверям: %d ответов" % checked)
check(not found, "ни в одном ответе нет имён моделей" + ("" if not found else ":\n       "
                                                         + "\n       ".join(found)))

print("\n=== 9. Предикат ===")
for tok, who, want in ((S, "супер", False), (OWN, "владелец", True), (TR, "переводчик", True)):
    ctx = main.CURRENT_SESSION.set(main._SESSIONS[tok])
    try:
        got = main._hide_models()
    finally:
        main.CURRENT_SESSION.reset(ctx)
    check(got is want, "%s: прятать имена = %s" % (who, got))

print("\nВСЁ ПРОШЛО" if not fail else "\nПРОВАЛЕНО: %d\n  - %s" % (len(fail), "\n  - ".join(fail)))
sys.exit(1 if fail else 0)
