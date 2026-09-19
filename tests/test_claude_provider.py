"""Второй поставщик моделей — Anthropic (Claude) — и кросс-проверка терм-листа.

Что сторожится:
  1. Каталог: модели Claude живут в OPENAI_MODELS ("api": "anthropic"), у каждой
     есть ранг в model_ranks.json (иначе termcheck/back-check перепокупались бы
     на каждом прогоне), поставщик выводится из каталога.
  2. Шим `_AnthropicChat` под видом клиента OpenAI: system-сообщения уходят
     в верхний `system`, сэмплинг у Opus 5 / Sonnet 5 не шлётся (400), у Haiku
     temperature доезжает телом запроса; картинка data-URL → base64-блок;
     JSON из ```-обёртки; отказ модели — исключение, а не пустой перевод;
     usage → prompt_tokens = вход + чтение и запись кэша, цена — из каталога.
  3. Ключи по поставщику: без ANTHROPIC_API_KEY модели Claude недоступны
     (503 «Нет ключа Anthropic», в /api/models `ready: false`), а модели OpenAI
     работают; политика называет Anthropic, когда его ключ задан.
  4. termcross: вторая модель переводит только согласованные машиной термины
     одним вызовом; расхождение — спор (`_termlist_dispute`), решение человека
     не трогается и не переспрашивается; ответ кэшируется по (модель, термин):
     повторный сбор не покупает тот же термин; без ключа и «той же моделью» —
     пропуск с причиной, без вызова. Шаг встроен в сбор терм-листа.

Сети нет: модули openai и anthropic подменены.
"""
import os, sys, types, json
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("MODEL_PROVIDER_NAME", None)
sys.path.insert(0, "backend")
import main
import legal

main.save_state = lambda *a, **k: None
NS = types.SimpleNamespace

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# ── Подменённый SDK Anthropic ────────────────────────────────────────
CALLS, CLIENTS = [], []
REPLY = {"text": '{"findings": []}', "stop": "end_turn",
         "usage": dict(input_tokens=100, output_tokens=50,
                       cache_read_input_tokens=20, cache_creation_input_tokens=10)}
CROSS = {}          # термин → ответ второй модели


def _reply(kw):
    body = kw["messages"][0]["content"]
    if isinstance(body, str) and body.startswith("[1] "):
        # Кросс-проверка: отвечаем по списку терминов из тела запроса.
        out = []
        for line in body.split("\n"):
            num, rest = line[1:].split("] ", 1)
            term = rest.split(" — context: ")[0]
            out.append({"i": int(num), "tgt": CROSS.get(term, "")})
        return "```json\n" + json.dumps({"terms": out}, ensure_ascii=False) + "\n```"
    return REPLY["text"]


class FakeMessages:
    def create(self, **kw):
        CALLS.append(kw)
        u = REPLY["usage"]
        return NS(id="msg_1", stop_reason=REPLY["stop"],
                  content=[NS(type="thinking", thinking=""), NS(type="text", text=_reply(kw))],
                  usage=NS(**u))


class FakeAnthropic:
    def __init__(self, **kw):
        CLIENTS.append(kw)
        self.messages = FakeMessages()


fake = types.ModuleType("anthropic")
fake.Anthropic = FakeAnthropic
sys.modules["anthropic"] = fake

# OpenAI — только чтобы заметить, что к нему НЕ ходили.
OPENAI_CALLS = []


class FakeOpenAI:
    def __init__(self, **kw):
        self.chat = NS(completions=NS(create=lambda **k: OPENAI_CALLS.append(k) or NS(
            choices=[NS(message=NS(content="{}"), finish_reason="stop")], usage=None)))


fake_oa = types.ModuleType("openai")
fake_oa.OpenAI = FakeOpenAI
sys.modules["openai"] = fake_oa

CLAUDE = [m for m in main.OPENAI_MODELS if m.get("api") == "anthropic"]

print("(1) каталог")
ids = {m["id"] for m in CLAUDE}
check(ids == {"claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"}, "модели Claude в каталоге: %s" % sorted(ids))
check(all(m["in"] > 0 and m["out"] > 0 for m in CLAUDE), "у каждой цена")
check(all(main.model_rank(m["id"]) is not None for m in main.OPENAI_MODELS),
      "у КАЖДОЙ модели каталога есть ранг (иначе проверки перепокупаются)")
check(main._provider_of("claude-sonnet-5") == "anthropic" and main._provider_of("gpt-4o") == "openai"
      and main._provider_of("нет-такой") == "openai", "поставщик — из каталога")
check("anthropic" in open("backend/requirements.txt", encoding="utf-8").read(), "anthropic в requirements.txt")

print("(2) шим: Sonnet 5 в месте вызова termcheck")
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
main._USAGE_TOTAL = main._usage_zero()
REPLY["text"] = ('```json\n{"findings": [{"src_term": "лимфаденит", "tgt_term": "adenolymphitis", '
                 '"suggestion": "lymphadenitis", "severity": "critical", "why": "другое понятие"}]}\n```')
res = main._openai_termcheck("Лимфаденит шеи.", "Adenolymphitis of the neck.", "RU", "EN",
                             "medical", model="claude-sonnet-5")
kw = CALLS[-1]
check(CLIENTS[-1].get("api_key") == "sk-ant-test" and CLIENTS[-1].get("timeout") == 90
      and CLIENTS[-1].get("max_retries") == 1, "клиент: ключ Anthropic, таймаут и повторы места вызова")
check(kw["model"] == "claude-sonnet-5", "модель доехала")
check(isinstance(kw.get("system"), str) and "terminology reviewer" in kw["system"],
      "system-сообщение — в верхний system")
check([m["role"] for m in kw["messages"]] == ["user"], "в messages только user")
check(not ({"temperature", "top_p", "seed", "response_format", "max_completion_tokens"} & set(kw))
      and "temperature" not in (kw.get("extra_body") or {}), "сэмплинг и параметры OpenAI не шлются")
check(kw.get("output_config") == {"effort": "low"}, "effort из каталога")
check(kw["max_tokens"] >= main.ANTHROPIC_THINKING_MIN_TOKENS, "потолок с запасом на думание: %s" % kw["max_tokens"])
check(res and res["model"] == "claude-sonnet-5" and res["findings"][0]["suggestion"] == "lymphadenitis",
      "ответ разобран, несмотря на ```-обёртку")
st = main._USAGE_TOTAL["steps"].get("termcheck") or {}
check(st.get("in") == 130 and st.get("out") == 50 and st.get("cached_in") == 20,
      "usage: вход = 100 + чтение 20 + запись 10 кэша, выход 50: %s" % st)
want = 130 / 1e6 * 2.00 + 50 / 1e6 * 10.00
check(abs(st.get("cost", 0) - round(want, 6)) < 1e-9, "цена из каталога: %s ≈ %s" % (st.get("cost"), want))
check(not OPENAI_CALLS, "к OpenAI не ходили")

print("(3) шим: Haiku — temperature телом, картинка base64")
REPLY["text"] = "Текст страницы"
haiku = main._MODELS_BY_ID["claude-haiku-4-5"]
out = main._scan_read_page(b"\xff\xd8jpeg", haiku, "RU")
kw = CALLS[-1]
check(out == "Текст страницы", "чтение страницы вернуло текст")
check("output_config" not in kw and (kw.get("extra_body") or {}).get("temperature") == 0,
      "Haiku: без effort, temperature телом запроса")
part = kw["messages"][0]["content"][0]
check(part.get("type") == "image" and part["source"]["type"] == "base64"
      and part["source"]["media_type"] == "image/jpeg" and part["source"]["data"],
      "image_url data-URL → base64-блок Messages API")

print("(4) шим: JSON без флага, обрыв, отказ")
chat = main._llm_client("claude-opus-5")
REPLY["text"] = 'Вот ответ:\n```json\n{"variants": []}\n```'
r = chat.chat.completions.create(model="claude-opus-5", response_format={"type": "json_object"},
                                 messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                                 max_tokens=900, temperature=0)
check(json.loads(r.choices[0].message.content) == {"variants": []},
      "response_format json_object: тело JSON вырезано из прозы и обёртки")
REPLY["stop"] = "max_tokens"
r = chat.chat.completions.create(model="claude-opus-5", messages=[{"role": "user", "content": "u"}], max_tokens=10)
check(r.choices[0].finish_reason == "length", "max_tokens → finish_reason length")
REPLY["stop"] = "refusal"
check(main._openai_judge("а", "б", model="claude-opus-5") is None, "отказ модели — сбой вызова (None), не пустой вердикт")
REPLY["stop"] = "end_turn"

print("(5) ключи по поставщику")
os.environ.pop("ANTHROPIC_API_KEY", None)
check(not main._provider_ready("claude-sonnet-5") and main._provider_ready("gpt-4o"), "_provider_ready по модели")
lm = {m["id"]: m for m in main.list_models()["models"]}
check(lm["claude-opus-5"]["ready"] is False and lm["gpt-4o"]["ready"] is True
      and lm["claude-opus-5"]["provider"] == "anthropic", "/api/models: ready и provider")
try:
    main.termcheck_segment(1, 1, main.TermcheckRequest(model="claude-opus-5"))
    check(False, "без ключа Anthropic — 503")
except main.HTTPException as e:
    check(e.status_code == 503 and "Anthropic" in str(e.detail) and "OpenAI" not in str(e.detail),
          "503 называет Anthropic: " + str(e.detail))
check(main._no_key_text("gpt-4o", "Ремонт требует ключ OpenAI") == "Ремонт требует ключ OpenAI",
      "для OpenAI текст отказа прежний")
os.environ.pop("OPENAI_API_KEY", None)
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
try:
    main._key_gate("claude-opus-5", "x")
    check(True, "только ключ Anthropic — модель Claude проходит")
except main.HTTPException:
    check(False, "только ключ Anthropic — модель Claude проходит")
os.environ["OPENAI_API_KEY"] = "test-key"
check("Anthropic" in legal._model_provider() and "OpenAI" in legal._model_provider(),
      "политика: Anthropic назван при ключе — " + legal._model_provider())
os.environ.pop("ANTHROPIC_API_KEY", None)
check("Anthropic" not in legal._model_provider(), "без ключа Anthropic не назван")
os.environ["MODEL_PROVIDER_NAME"] = "Своя строка"
check(legal._model_provider() == "Своя строка", "MODEL_PROVIDER_NAME сильнее")
os.environ.pop("MODEL_PROVIDER_NAME", None)
check(main._is_quota_error("Your credit balance is too low to access the Anthropic API."),
      "пустой баланс Anthropic — остановка прогона, а не повторы")

print("(6) termcross: спор, человек, кэш")
check("termcross" in main.SYSTEM_MODEL_STEPS and main._dm("termcross") == "claude-sonnet-5"
      and main.USAGE_STEP_GROUP.get("termcross") == "termcross", "свой шаг в системных моделях")
check("termcross" not in (getattr(main, "FULL_RUN_STEPS", None) or []), "в составной прогон не встроен")


def entry(src, tgt, by="model", status="agreed"):
    return {"src": src, "tgt": tgt, "cat": "", "lang": "RU→UZ", "hits": 1, "variants": [],
            "status": status, "by": by, "gates": {}, "why": ""}


def project_of(entries):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "UZ", "domain": "general", "tenant": "default",
            "segments": [{"id": 1, "source": "Громкоговоритель стоит на столе, давление в норме.",
                          "target": "", "status": "new"}],
            "termlist": {"v": "1", "entries": entries}}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
CROSS.update({"громкоговоритель": "ovozkuchaytirgich", "давление": "bosim"})
proj = project_of([entry("громкоговоритель", "karnay"), entry("давление", "bosim"),
                   entry("микрофон", "mikrofon", by="human")])
main._USAGE_TOTAL = main._usage_zero()
n0 = len(CALLS)
got = main._termcross(proj, "gpt-5.6-terra")
e = {x["src"]: x for x in proj["termlist"]["entries"]}
check(len(CALLS) == n0 + 1, "один вызов на весь список")
body = CALLS[-1]["messages"][0]["content"]
check("громкоговоритель" in body and "давление" in body and "микрофон" not in body,
      "спрошены только согласованные машиной; решение человека не спрашивается")
check("context: Громкоговоритель стоит" in body, "термин идёт с куском оригинала")
check(e["громкоговоритель"]["status"] == "disputed" and "ovozkuchaytirgich" in e["громкоговоритель"]["why"],
      "расхождение — спор с вариантом второй модели: " + e["громкоговоритель"]["why"])
check(e["давление"]["status"] == "agreed" and e["давление"]["gates"]["cross"]["same"] is True,
      "совпадение — пара остаётся, след на воротах")
check(e["микрофон"]["status"] == "agreed" and "cross" not in e["микрофон"]["gates"], "человек не тронут")
check(got.get("crossAsked") == 2 and got.get("crossDisputed") == 1, "счётчики: %s" % got)
check((main._USAGE_TOTAL["steps"].get("termcross") or {}).get("calls") == 1, "расход записан шагом termcross")

n1 = len(CALLS)
e["громкоговоритель"]["status"] = "agreed"          # пересбор снова согласовал пару машиной
got = main._termcross(proj, "gpt-5.6-terra")
check(len(CALLS) == n1 and got.get("crossAsked") == 0 and got.get("crossCached") == 2,
      "повторно — из кэша, без вызова: %s" % got)

n2 = len(CALLS)
check(main._termcross(proj, "claude-sonnet-5").get("crossSkipped") == "same_model" and len(CALLS) == n2,
      "той же моделью, что составила лист, — пропуск")
os.environ.pop("ANTHROPIC_API_KEY", None)
proj2 = project_of([entry("давление", "bosim")])
check(main._termcross(proj2, "gpt-5.6-terra").get("crossSkipped") == "no_key" and len(CALLS) == n2,
      "без ключа — пропуск с причиной и без вызова")

print("(7) termcross встроен в сбор терм-листа")
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
proj = project_of([])
proj["termlist"] = {}
scope = main._project_scope(proj)
main._termsheet_call = lambda sources, model, dom, s, t: [{"src": "громкоговоритель", "tgt": "karnay"}]
main._corpus_check = lambda *a, **k: None
main._meaning_check = lambda cands, cap=0: ({(scope, main._norm_key(c["src"]), main._norm_key(c["tgt"])):
                                             {"same": True, "rule": True} for c in cands}, len(cands), 0)
job = {"id": 7, "project": 1, "kind": "termsheet", "params": {"model": "gpt-5.6-terra"},
       "counters": {}, "tenant": "default", "status": "running"}
n3 = len(CALLS)
main._job_termsheet(job)
ents = proj["termlist"]["entries"]
check(len(CALLS) == n3 + 1 and ents and ents[0]["status"] == "disputed",
      "после сбора вторая модель сверила лист и завела спор: %s" % [(x["src"], x["status"]) for x in ents])
check(job["counters"].get("crossDisputed") == 1 and "cross" in proj["termlist"], "счётчики задачи и кэш на листе")
main._job_termsheet(job)
check(len(CALLS) == n3 + 1, "пересбор листа кэш не теряет — термин не покупается дважды")

print()
if fail:
    print("FAILED: %d" % len(fail))
    sys.exit(1)
print("ALL OK")
