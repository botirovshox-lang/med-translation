"""Выбор термина по смыслу и честный счётчик очереди.

Смысл проверяемого: пользователь может не знать целевого языка. Вопрос «какой
перевод верный» для него бессмыслен, а «какое из двух значений вы имели в виду»
— понятен, если оба значения написаны на языке оригинала. Здесь проверяется,
что разбор действительно собирает все варианты и требует ответа на языке
оригинала, а очередь не врёт о своём размере.

Вызовов модели нет: клиент OpenAI подменён.
"""
import os, sys, json, types
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# ── Подменяем клиент OpenAI: запоминаем промпт, отдаём заготовленный ответ ──
SENT = {}
ANSWER = {"variants": [
    {"tgt": "uveitis", "back": "увеит", "same": True,
     "meaning": "воспаление сосудистой оболочки глаза",
     "usage": "офтальмология, клинические тексты"},
    {"tgt": "eye inflammation", "back": "воспаление глаза", "same": False,
     "meaning": "любое воспаление глаза, а не конкретное заболевание",
     "usage": "общая лексика"},
]}


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=text))]


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        SENT["model"] = model
        # ANSWER = None — модель вернула пустую строку (израсходовала лимит
        # на рассуждения). Это отказ, и обработан он должен быть как отказ.
        return FakeResp("" if ANSWER is None else json.dumps(ANSWER, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)


def build(cands, gloss=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical", "segments": []}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss], "tm": [],
                  "termQueue": [dict(c) for c in cands], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return main.STATE["termQueue"]


CAND = {"id": 1, "kind": "segment", "src": "увеит", "tgt": "uveitis", "status": "pending",
        "hits": 1, "segments": ["1:1"], "lang": "RU→EN", "domain": "medical",
        "sampleSrc": "Диагноз: увеит правого глаза."}
RIVAL = {"id": 2, "kind": "extract", "src": "увеит", "tgt": "eye inflammation",
         "status": "pending", "hits": 1, "segments": ["1:2"],
         "lang": "RU→EN", "domain": "medical"}

print("=== 1. Разбор собирает ВСЕ варианты термина, а не только свой ===")
build([CAND, RIVAL])
r = main.explain_term_variants(1, main.ExplainRequest())
got = [v["tgt"] for v in r["variants"]]
check(got == ["uveitis", "eye inflammation"], "оба варианта из очереди: " + str(got))
check(all(v["meaning"] and v["back"] for v in r["variants"]),
      "у каждого есть обратный перевод и значение")

print("\n=== 2. Вопрос задан на языке ОРИГИНАЛА ===")
# Это и есть суть: человек, не знающий английского, читает русское описание.
check("WRITTEN IN RU" in SENT["system"], "модели велено отвечать на языке оригинала")
check("does NOT speak EN" in SENT["system"], "и сказано, почему: пользователь не знает целевого языка")
check("увеит" in SENT["user"] and "uveitis" in SENT["user"], "термин и варианты переданы")
check("Диагноз: увеит правого глаза." in SENT["user"], "контекстное предложение тоже — смысл без него угадывать нельзя")

print("\n=== 3. Модель отмечает, что вариант про ДРУГОЕ понятие ===")
by = {v["tgt"]: v for v in r["variants"]}
check(by["uveitis"]["same"] is True, "точный термин помечен как то же понятие")
check(by["eye inflammation"]["same"] is False, "более общий — как иное понятие")

print("\n=== 4. В разбор попадает и то, что предлагает справочник ===")


class Dict1:
    id, label = "d1", "Тестовый справочник"
    pairs = {"увеит": {"uveitis", "uveal inflammation"}}

    def covers(self, lang, domain):
        return lang == "RU→EN"

    def match(self, src, tgt):
        return tgt.strip().lower() in self.pairs.get(src.strip().lower(), set())

    def suggest(self, src):
        return sorted(self.pairs.get(src.strip().lower(), set()))


main._DICTIONARIES = [Dict1()]
build([CAND])
r = main.explain_term_variants(1, main.ExplainRequest())
got = [v["tgt"] for v in r["variants"]]
check("uveal inflammation" in got, "вариант из справочника добавлен к сравнению: " + str(got))
check(any(v["authority"] for v in r["variants"]), "и помечено, какой из них знает справочник")
main._DICTIONARIES = []

print("\n=== 5. Сравнивать нечего — честный отказ, а не пустой экран ===")
build([{"id": 1, "kind": "conflict", "src": "макула", "tgt": "", "status": "pending",
        "hits": 1, "segments": [], "lang": "RU→EN", "domain": "medical"}])
try:
    main.explain_term_variants(1, main.ExplainRequest())
    check(False, "должно было отказать")
except main.HTTPException as e:
    check(e.status_code == 400 and "Нечего сравнивать" in e.detail, "400 с внятной причиной")

print("\n=== 6. Явно переданные варианты имеют приоритет ===")
build([CAND, RIVAL])
r = main.explain_term_variants(1, main.ExplainRequest(variants=["uveitis"]))
check([v["tgt"] for v in r["variants"]] == ["uveitis"], "разобран только запрошенный")

print("\n=== 7. Очередь не врёт о своём размере ===")
# Тот самый случай: 260 кандидатов, лимит 200 — на экране всегда стояло 200,
# и разобранные двадцать штук ничего не меняли.
many = [{"id": i, "kind": "segment", "src": "т%d" % i, "tgt": "t%d" % i, "status": "pending",
         "hits": 1, "segments": ["1:%d" % i], "lang": "RU→EN", "domain": "medical"}
        for i in range(1, 261)]
build(many)
res = main.list_term_queue(status="pending", limit=200)
check(res["total"] == 260, "total — сколько ЕСТЬ: " + str(res["total"]))
check(len(res["items"]) == 200, "items — сколько показано: " + str(len(res["items"])))
main.reject_term_candidate(1)
res = main.list_term_queue(status="pending", limit=200)
check(res["total"] == 259, "решённый кандидат уменьшает именно total")
check(len(res["items"]) == 200, "а показанная страница остаётся полной — цифру берут не из неё")

print("\n=== 8. «Не знаю» не выдаётся за «иное понятие» ===")
# Пользователь по условию не читает целевой язык и поверит значку буквально.
# Молчание модели про вариант обязано остаться молчанием.
ANSWER = {"variants": [{"tgt": "uveitis", "back": "увеит", "same": True,
                        "meaning": "воспаление сосудистой оболочки", "usage": "офтальмология"}]}
build([CAND, RIVAL])
r = main.explain_term_variants(1, main.ExplainRequest())
by = {v["tgt"]: v for v in r["variants"]}
check(by["uveitis"]["same"] is True, "про который ответили — ответ сохранён")
check(by["eye inflammation"]["same"] is None,
      "про который смолчали — None, а не False: " + str(by["eye inflammation"]["same"]))
check(by["eye inflammation"]["meaning"] == "", "и объяснения нет, а не выдуманное")

print("\n=== 9. Пустой ответ модели — отказ, а не пустой разбор ===")
ANSWER = None                      # см. FakeClient: вернёт пустую строку
build([CAND])
try:
    main.explain_term_variants(1, main.ExplainRequest())
    check(False, "должно было отказать")
except main.HTTPException as e:
    check(e.status_code == 502, "502, а не 200 с прочерками во всех полях")

print("\n=== 10. Свой перевод карточки не выбрасывается потолком ===")
ANSWER = {"variants": []}
many = [dict(CAND, id=1, tgt="uveitis")] + [
    {"id": i, "kind": "extract", "src": "увеит", "tgt": "variant%d" % i, "status": "pending",
     "hits": 1, "segments": ["1:%d" % i], "lang": "RU→EN", "domain": "medical"}
    for i in range(2, 12)]
build(many)
r = main.explain_term_variants(1, main.ExplainRequest())
check(r["variants"][0]["tgt"] == "uveitis", "перевод самой карточки идёт первым")
check(len(r["variants"]) == 6 and r["dropped"] == 5,
      "потолок назван вслух: разобрано 6, не влезло " + str(r["dropped"]))

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
