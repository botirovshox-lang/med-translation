# -*- coding: utf-8 -*-
"""Переводчик по языку перевода (backend/lang_bench.py + main._lang_bench_*)
и две бесплатные находки у перевода на любой язык (`_output_misses`):
заметка модели в тексте и слово чужим письмом. Клиент модели подменён,
сборка промптов, судья и правило выбора — настоящие.

    python tests/test_lang_bench.py
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["WARM_CACHES"] = "0"
os.environ["MODEL_AUTO"] = "0"
sys.path.insert(0, "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)[:300]))
    if not ok:
        FAILS.append(name)


import lang_bench as LB  # noqa: E402
import main  # noqa: E402
main.save_state = lambda *a, **k: None
main.STATE.setdefault("projects", [])

print("=== правило выбора ===")
pr = {"s": 1.0, "o": 2.0, "x": 3.0}
check("равны — самая дешёвая", LB.decide({"s": 1, "o": 1}, pr) == ("s", "cheapest"))
check("разница в одну строку — шум, самая дешёвая", LB.decide({"s": 2, "o": 1}, pr)[0] == "s")
check("дешёвая хуже на три строки — сильная", LB.decide({"s": 5, "o": 2, "x": 2}, pr) == ("o", "quality"))
check("нет данных — None", LB.decide({"s": None}, pr) == (None, "nodata"))

print("=== ответ судьи ===")
check("каждая буква — разбор", LB.parse_judge('{"A": [], "B": [{"sev": "major"}]}', 2) == {"A": [], "B": [{"sev": "major"}]})
check("пропущена буква — не ответ", LB.parse_judge('{"A": []}', 2) is None)
check("мусор — не ответ", LB.parse_judge("no", 2) is None)
check("серьёзная — critical/major", LB.serious([{"sev": "Major"}]) and not LB.serious([{"sev": "minor"}]))
check("оригинал для перевода на русский — английский", LB.source_lang("RU") == "EN" and LB.source_lang("UZ") == "RU")
check("набор фраз на оба оригинала", all(s.get("RU") and s.get("EN") for s in LB.SENTENCES))

print("=== заметка модели ===")
src = "Клинически выражается увеличением слюнных желез."
check("второй вариант после пустой строки — заметка",
      LB.leak(src, "Клиник жиҳатдан kattalashuvi.\n\nLet me provide the final answer in correct Cyrillic only:\n\nКлиник жиҳатдан."))
check("«Note:» отдельной строкой — заметка", LB.leak(src, "Клиник жиҳатдан.\nNote: I kept the term."))
check("обычный перевод — не заметка", not LB.leak(src, "Клиник жиҳатдан катталашуви билан намоён бўлади."))
check("«Note:» в одну строку с переводом и в оригинале — не заметка",
      not LB.leak("Примечание: см. выше.", "Note: see above."))

print("=== чужое письмо в слове ===")
P_UZ = {"tgt": "UZ-CYRL", "src": "RU"}


def om(s, t, p=P_UZ):
    return main._output_misses({"source": s, "target": t}, p)


got = om("Механизм действия яда при ревматизме", "Заҳарнинг revматизмдаги таъсир механизми")
check("смешение внутри слова — находка", got and "revматизмдаги" in got[0]["text"], got)
got = om("Клинически выражается увеличением", "Клиник жиҳатдан kattalashuvi билан намоён бўлади")
check("целое слово латиницей в кириллице — находка", got and "kattalashuvi" in got[0]["text"], got)
check("латинское название из оригинала — не находка",
      not om("Люцерна (Medicagosativa) цветёт", "Беда (Medicagosativa) гуллайди"))
check("аббревиатура и слово с цифрой — не находка", not om("при COVID-19 и ВИЧ", "COVID-19 ва HIV да"))
check("единица с заглавной — не находка", not om("давление 120 мм рт. ст.", "босим 120 mmHg"))
check("узбекская латиница с ʻ — не находка", not om("Город", "Shaharning oʻrtasi", {"tgt": "UZ", "src": "RU"}))
check("японский: кандзи и азбуки — не находка",
      not om("Принимать три раза в день", "1日3回服用してください", {"tgt": "JA", "src": "RU"}))
check("корейский: хангыль — не находка", not om("Принимать", "복용하십시오", {"tgt": "KO", "src": "RU"}))
got = om("Принимать после еды", "食後に take してください", {"tgt": "JA", "src": "RU"})
check("английское слово в японском — находка", got and "take" in got[0]["text"], got)
check("китайский: mRNA внутри фразы — не находка",
      not om("Как работают вакцины на основе мРНК", "基于mRNA的新冠肺炎疫苗如何发挥作用", {"tgt": "ZH", "src": "RU"}))
check("китайский: адрес сайта — не находка",
      not om("Посетите сайт", "请访问网站：cdc.gov/coronavirus/vaccines", {"tgt": "ZH", "src": "RU"}))
check("китайский: «min» и фамилия — не находка",
      not om("10 мин", "初始变性10 min，Melenteva", {"tgt": "ZH", "src": "RU"}))
check("видовое название без пары в оригинале — не находка",
      not om("моркови", "сабзининг (Daucus carota L.) гуллари"))
check("аббревиатура с родным окончанием — не находка", not om("на ИФН", "IFNга таъсир"))
check("буква-сноска — не находка", not om("применению", "қўлланишиb", ))
check("фармакопейная латынь — не находка", not om("донник", "қашқарбеда ўти — herba Meliloti"))
check("ген с цифрой в китайском — не находка", not om("у мышей с делецией", "在stat6基因缺失的小鼠", {"tgt": "ZH", "src": "RU"}))
check("сербская латиница — не находка", not om("Принимать после еды", "Uzimati posle jela", {"tgt": "SR", "src": "RU"}))
check("CRLF в оригинале — пустая строка перевода не заметка", not LB.leak("Абзац один.\r\n\r\nАбзац два.", "Bir.\n\nIkki."))
HT = "Бир.\n\nИкки."
check("пустая строка в тексте человека — не заметка", not main._output_misses({"source": "Один.", "target": HT, "editedToHash": main._text_hash(HT), "editedBy": 1}, P_UZ))
check("английский перевод — молчим", not om("Принимать после еды", "Take after meals", {"tgt": "EN", "src": "RU"}))
check("находка идёт через _alphabet_misses (ремонт, приёмка правки, ревизия)",
      main._alphabet_misses({"source": "Клинически выражается", "target": "Клиник kattalashuvi"}, P_UZ))

print("=== переводчик по языку ===")
main._provider_ready = lambda m: True
main.STATE["modelAuto"] = {"on": True, "health": {"anthropic": {"ok": True}, "openai": {"ok": True}}}
ids = [m["id"] for m in main.OPENAI_MODELS]
strong = max(ids, key=lambda i: main.model_rank(i) or 0)
base = main._effective_model("translate")
main.STATE["langModels"] = {"by": {"UZ-CYRL": strong, "EN": base}, "base": base}
snap = {k: main._effective_model(k) for k in main.SYSTEM_MODEL_STEPS}
snap["translate"] = base
check("язык с выбором — сильная модель", main._lang_translate_model("UZ-CYRL", snap) == strong)
check("язык без выбора — None (общий)", main._lang_translate_model("DE", snap) is None)
snap2 = dict(snap, review=strong)
check("совпала с моделью проверки — не берём", main._lang_translate_model("UZ-CYRL", snap2) is None)
main.STATE["modelAuto"]["pinned"] = {"translate": base}
check("переводчик закреплён человеком — не берём", main._lang_translate_model("UZ-CYRL", snap) is None)
main.STATE["modelAuto"]["pinned"] = {}
prov = main._provider_of(main._MODELS_BY_ID[strong])
main.STATE["modelAuto"]["health"][prov] = {"ok": False}
check("у поставщика нет счёта — не берём", main._lang_translate_model("UZ-CYRL", snap) is None)
main.STATE["modelAuto"]["health"][prov] = {"ok": True}
check("вне прогона — по языку проекта", main._lang_dm({"tgt": "UZ-CYRL"}) in (strong, main._dm("translate")))
proj = {"id": 77001, "tgt": "UZ-CYRL", "src": "RU", "segments": [], "tenant": "default"}
main.STATE["projects"].append(proj)
main._project_by_id = (lambda f: (lambda x: proj if int(x) == 77001 else f(x)))(main._project_by_id)
job = {"id": 5, "project": 77001, "params": {}, "sysModels": dict(snap)}
fx = main._job_freeze_models(job)
ok_pick = main._lang_translate_model("UZ-CYRL", snap)
check("прогон замораживает выбор по языку", fx["translate"] == (ok_pick or base) and job["langTr"] == (ok_pick or ""), (fx, job.get("langTr")))
main.STATE["langModels"]["by"]["UZ-CYRL"] = base
fx2 = main._job_freeze_models(job)
check("повторная заморозка не меняет модель посреди книги", fx2["translate"] == fx["translate"])
main.STATE["langModels"]["by"]["UZ-CYRL"] = strong
import inspect as _insp
check("одиночная кнопка перевода — по языку", "req.model or _lang_dm(project)" in _insp.getsource(main.translate_segment)
      if hasattr(main, "translate_segment") else "_lang_dm(project)" in open("backend/main.py", encoding="utf-8").read())
check("пакет и разбор состава — по языку", "req.model = _lang_dm(project)" in _insp.getsource(main.batch_translate)
      and "_lang_dm(project)" in _insp.getsource(main._plan_step))

main.STATE["langModels"]["base"] = "other-model"
check("общий переводчик сменили — выбор по языку не действует", main._lang_translate_model("UZ-CYRL", snap) is None)
main.STATE["langModels"]["base"] = base
check("имя модели в задаче — не наружу не-суперу", '"langTr"' in _insp.getsource(main._job_public))
print("=== план замера ===")
plan = main._lang_bench_plan({"anthropic": {"ok": True}, "openai": {"ok": True}})
check("план есть: базовый и сильнее", plan and plan["candidates"][0] == plan["base"] and len(plan["candidates"]) >= 2, plan)
check("все языки каталога", plan and len(plan["langs"]) == len(main.LANGUAGES))
check("судьи — двое", plan and len(plan["judges"]) == 2)
plan_b = main._lang_bench_plan({"anthropic": {"ok": True}, "openai": {"ok": True}})
check("отпечаток стабилен", plan["fp"] == plan_b["fp"])

print("=== замер одного языка (клиент подменён) ===")
GOOD = {"uz": "Беморга суткасига 600 мг дан ортиқ бўлмаган доза буюрилади."}
CALLS = []


class _U:
    prompt_tokens, completion_tokens = 900, 60
    cache_read_input_tokens = cache_creation_input_tokens = 0


class _R:
    def __init__(self, t):
        self.choices = [type("C", (), {"message": type("M", (), {"content": t})(), "finish_reason": "stop"})()]
        self.usage = _U()


cheap, best = plan["candidates"][0], plan["candidates"][1]


class _Comp:
    def __init__(self, mid):
        self.mid = mid

    def create(self, **kw):
        sysm = kw["messages"][0]["content"]
        CALLS.append((self.mid, sysm[:40]))
        if "Several candidate translations" in sysm:
            body = kw["messages"][1]["content"]
            # судья: кандидат с латиницей в слове — major
            d = {}
            for lab in LB.labels(8):
                if ("\n" + lab + ":\n") in ("\n" + body):
                    seg = body.split("\n" + lab + ":\n", 1)[1].split("\n\n", 1)[0] if ("\n" + lab + ":\n") in body \
                        else body.split(lab + ":\n", 1)[1].split("\n\n", 1)[0]
                    d[lab] = [{"sev": "major", "what": "latin"}] if "kattalashuvi" in seg else []
            return _R(json.dumps(d))
        if self.mid == cheap:
            return _R("Клиник жиҳатдан kattalashuvi билан.")
        return _R("Клиник жиҳатдан катталашуви билан.")


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: \
    type("Cl", (), {"chat": type("Ch", (), {"completions": _Comp(mdl["id"])})()})()
c = main._lang_bench_conf()
c["sentences"] = 3
plan3 = dict(plan, n=3, candidates=[cheap, best])
res = main._lang_bench_one("UZ-CYRL", plan3, c, main._lang_bench_spent())
check("замер дал счёт по моделям", res and set(res["table"]) == {cheap, best}, res)
check("дешёвая с латиницей в словах — хуже", res and res["table"][cheap] > res["table"][best], res)
check("выбрана сильная, раз дешёвая хуже на все строки", res and res["pick"] == best and res["why"] == "quality", res)
check("расход шага langbench — служебной организации",
      "langbench" in main.price_rules_mod.ONLY_ALL if hasattr(main, "price_rules_mod") else True)

print("=== протечка заметки при переводе: повтор, потом отказ ===")
ANS = ["Перевод.\n\nLet me provide the final answer:\n\nПеревод.", "Чистый перевод."]


class _Comp2:
    def create(self, **kw):
        return _R(ANS.pop(0) if ANS else "Перевод.\n\nNote: x")


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: \
    type("Cl", (), {"chat": type("Ch", (), {"completions": _Comp2()})()})()
out = main._openai_translate("Клинически выражается.", "RU", "UZ-CYRL", model=cheap)
check("заметка — повтор, берём чистый ответ", out == "Чистый перевод.", out)
ANS[:] = ["A.\n\nLet me fix:\n\nA.", "B.\n\nNote: again\n\nB."]
out = main._openai_translate("Клинически выражается.", "RU", "UZ-CYRL", model=cheap)
check("снова заметка — перевода нет (строка не трогается)", out == "", out)

print("=== фоновый запуск: только при смене набора моделей ===")
started = []
main.threading.Thread = (lambda T: (lambda *a, **k: type("Tt", (), {"start": lambda self: started.append(k.get("name"))})()))(main.threading.Thread)
main.STATE["langModels"] = {}
check("нет замера — запускается", main._lang_bench_maybe() and started, started)
main._LANG_BENCH_RUN["on"] = False
main.STATE["langModels"] = {"fp": plan["fp"], "partial": False, "tried": 0}
started.clear()
check("тот же набор моделей — не запускается", not main._lang_bench_maybe() and not started)
main.STATE["langModels"] = {"fp": "other", "tried": __import__("time").time()}
check("набор сменился, но недавно пробовали — ждём", not main._lang_bench_maybe())
main.STATE["langModels"] = {"fp": "other", "tried": 0}
check("набор сменился — запускается", main._lang_bench_maybe())
main._LANG_BENCH_RUN["on"] = False
pub = main._lang_models_public()
check("публичный ответ — только суперу (дверь админки)", "langModels" in _insp.getsource(main._model_auto_public))
check("в /api/seed не уходит (белый список)", "langModels" not in json.dumps(main.SEED_KEYS if hasattr(main, "SEED_KEYS") else []))

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f_ in FAILS:
        print("  - " + f_)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
