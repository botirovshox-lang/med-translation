"""Сборщики промптов гоняются ЦЕЛИКОМ, с подменённым клиентом OpenAI.

Из-за чего написано. В `_openai_term_context` использовалась переменная `NL`,
которую никто не объявил. Функция падала с NameError на построении ТЕЛА
ЗАПРОСА — то есть до вызова модели, — и возвращала None. Наружу это выглядело
как «арбитр не ответил», и штатный шаг конвейера «сверка терминов» отчитался
отказом по всем 698 сегментам боевого проекта, ни разу не сходив в модель.
Денег это не стоило, но и работы не сделало, а на экране осталось «698 ещё
не сверялся» — то есть кнопка выглядела нажатой впустую.

Почему не поймали раньше: остальные тесты подменяют `_openai_term_context`
целиком (`tests/test_term_context.py`), поэтому настоящий сборщик промпта
не выполнялся НИ РАЗУ. Здесь подменён только клиент OpenAI — сеть не трогаем,
денег не тратим, а весь наш код отрабатывает по-настоящему.

Правило на будущее: у каждой функции, которая СТРОИТ запрос к модели, должен
быть заход через настоящий код. Подменять надо клиента, а не свою функцию.
"""
import json, os, sys, types

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"

SENT = {}
ANSWER = {"terms": [{"src": "больной", "ok": False, "use": "patient",
                     "why": "подменён животным"}]}


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(
            message=types.SimpleNamespace(content=text))]
        self.usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                           total_tokens=15)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        SENT["model"] = model
        return FakeResp(json.dumps(ANSWER, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


GLOSS = [{"src": "больной", "tgt": "patient", "tier": "verified", "cat": "Term",
          "lang": "RU→EN", "domain": "medical"}]
SRC = "Пробы у больного не всегда свидетельствуют об отсутствии интоксикации."
TGT = "Tests in an infected animal do not always indicate the absence of intoxication."


def project_of(segments):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in GLOSS],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


print("=== 1. Арбитр спорного термина: промпт собирается, ответ разбирается ===")
seg = {"id": 2, "source": SRC, "target": TGT, "status": "translated"}
prev = {"id": 1, "source": "Соседний сегмент до.", "target": "Before.",
        "status": "translated"}
nxt = {"id": 3, "source": "Соседний сегмент после.", "target": "After.",
       "status": "translated"}
proj = project_of([prev, seg, nxt])

disputes = main._term_terms_of(seg, proj, disputes_only=False)
check(bool(disputes), "приказный термин для сегмента найден — есть о чём спрашивать")

res = main._openai_term_context(seg, proj, disputes, "Соседний до.", "Соседний после.",
                                "gpt-5.6-sol")
check(res is not None,
      "сборщик промпта отработал и вернул разобранный ответ "
      "(NameError здесь и жил: 698 отказов «арбитр не ответил»)")
check(bool(res) and res.get("terms"), "вердикт по терминам на месте")

# Тело запроса собрано склейкой — проверяем, что оно РАЗБОРЧИВО, а не одна
# строка: соседи и термины обязаны стоять на своих строках.
body = SENT.get("user") or ""
check("[сегмент ДО]" in body and "[сегмент ПОСЛЕ]" in body,
      "соседи в теле запроса названы")
check(">>> [этот сегмент]" in body, "разбираемый сегмент помечен явно")
check(body.count(chr(10)) >= 5,
      "тело разбито на строки, а не склеено в одну — иначе модель читает кашу")
check("больной" in body and "patient" in body,
      "утверждённый термин и его перевод уехали в запрос")
check(TGT in body, "перевод разбираемого сегмента тоже")


print()
print("=== 2. Полный круг: вердикт садится на сегмент ===")
r = main._run_segment_term_context(seg, proj, model="gpt-5.6-sol", disputes_only=False)
check(r.get("ok") is True, "шаг отработал без ошибки")
terms = (seg.get("termContext") or {}).get("terms") or []
check(len(terms) == 1 and terms[0].get("ok") is False,
      "вердикт «передан неверно» лёг на сегмент")
check(terms[0].get("use") == "patient", "и готовый вариант вместе с ним")
check(not main._term_context_stale(seg),
      "вердикт описывает нынешний текст — повторно платить не за что")

# И он доходит до ремонта: совет согласен с приказной записью.
kinds = {f["kind"] for f in main._repair_findings(seg, proj)}
check("term_ctx" in kinds,
      "совет арбитра стал находкой ремонта — иначе проверка только "
      "подтверждает ошибку и оставляет её в тексте")

print()
print("=== 3. Язык объяснения — язык интерфейса, а вопрос неизменен ===")
# Модель пишет человеку `why` и `comment`. Пока пользователь был один, язык
# был зашит («одно предложение по-русски»), и в узбекском интерфейсе половина
# карточки сегмента оставалась русской. Меняется ТОЛЬКО язык объяснения:
# вопрос и разбор те же, поэтому версии вердиктов не поднимаются.
dom = main._resolve_domain("medical")


def prompts(lang):
    """Промпт арбитра собирается ВНУТРИ `_openai_term_context`, отдельной
    функции у него нет — поэтому берём его так же, как первый раздел этого
    файла: гоняем настоящий код и читаем, что ушло поддельному клиенту."""
    tok = main.CURRENT_SESSION.set({"tenant": "default", "user": 1,
                                    "role": "owner", "uiLang": lang})
    try:
        seg2 = dict(seg)
        seg2.pop("termContext", None)
        main._run_segment_term_context(seg2, proj, model="gpt-5.6-sol",
                                       disputes_only=False)
        return {
            "judge": main._judge_system(dom, "RU"),
            "termcheck": main._termcheck_system(dom, "RU", "EN"),
            "arbiter": SENT["system"],
        }
    finally:
        main.CURRENT_SESSION.reset(tok)


ru, uz = prompts("ru"), prompts("uz")
for name in ("judge", "termcheck", "arbiter"):
    check("Uzbek" in uz[name], name + ": у узбекского интерфейса объяснение просят по-узбекски")
    check("Uzbek" not in ru[name] and "Russian" in ru[name],
          name + ": у русского — по-русски")

# А вопрос обязан остаться тем же: если разойдётся и он, вердикты, купленные
# на одном языке, станут несравнимы с купленными на другом.
def question(t):
    """Промпт без названия языка: остальное обязано совпасть до буквы."""
    return t.replace("Uzbek (Latin script)", "«язык»").replace("Russian", "«язык»")


check(question(ru["arbiter"]) == question(uz["arbiter"]),
      "арбитр: кроме языка объяснения, промпт не изменился")
check(question(ru["judge"]) == question(uz["judge"]),
      "судья: тоже")
check(question(ru["termcheck"]) == question(uz["termcheck"]),
      "проверка терминов: тоже")

# Язык доезжает до потоков прогона: ContextVar туда не наследуется.
main._JOB_LANG.code = "uz"
tok = main.CURRENT_SESSION.set(None)
try:
    check(main._explain_lang() == "uz", "без сессии язык берётся у задачи прогона")
finally:
    main.CURRENT_SESSION.reset(tok)
    main._JOB_LANG.code = None
check(main._explain_lang() == main.DEFAULT_UI_LANG,
      "ни сессии, ни задачи — язык по умолчанию, а не пустота")

print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
