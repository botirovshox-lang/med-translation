"""Правила документа: выводятся из первого перевода, правятся человеком.

Сборщик промпта и разбор ответа гоняются НАСТОЯЩИМ кодом — подменён только
клиент OpenAI (правило «Промпты проверяются настоящим кодом»). Сеть не
трогается, денег нет. Проверяется: выборка, промпт (форма, не термины;
действующие правила не повторять), блок в промптах перевода/ревизии/ремонта
и НЕ в обратном переводе, пересборка не трогает правил человека и не
возвращает удалённых, автосбор в прогоне — один раз и только с переводом,
правила языка организации — в `_lang_conventions`, право владельца.
"""
import json, os, sys, types

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"

SENT = {"n": 0}
ANSWER = [{"text": "Address the reader formally (siz), never sen.", "kind": "lang"},
          {"text": "Use «guillemets» for quotations.", "kind": "doc"},
          {"text": "Use «guillemets» for quotations.", "kind": "doc"},          # дубль
          {"text": "x" * 400, "kind": "doc"},                                   # слишком длинное
          {"text": "Write numbers with a space as thousands separator: 4 773.", "kind": "weird"}]


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=text))]
        self.usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        SENT["n"] += 1
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        if SENT.get("fail"):
            raise RuntimeError("нет связи")
        return FakeResp("Here:\n" + json.dumps(ANSWER, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build(n=25, tgt="UZ", domain="general", **extra):
    segs = [{"id": i, "source": "Исходное предложение номер %d." % i,
             "target": ("Tarjima %d." % i) if i <= n else "", "status": "review"} for i in range(1, 31)]
    segs[4]["status"] = "confirmed"
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": tgt, "domain": domain, "tenant": "default",
            "segments": segs, **extra}
    main.STATE = {"projects": [proj], "glossary": [], "termQueue": [], "tm": [],
                  "tenants": [{"id": "default", "name": "d"}]}
    main._invalidate_gloss_index()
    return proj


print("=== 1. выборка и промпт ===")
p = build()
smp = main._guide_sample(p)
check(len(smp) == 25 and [s["id"] for s in smp] == sorted(s["id"] for s in smp),
      "в выборке только переведённое, в порядке документа: %d" % len(smp))
p["segments"] = [{"id": i, "source": "С" * 1000, "target": "T" * 1000, "status": "review"} for i in range(1, 30)]
p["segments"][20]["status"] = "confirmed"
smp = main._guide_sample(p)
check(sum(len(s["source"]) + len(s["target"]) for s in smp) <= main.GUIDE_SAMPLE_CHARS
      and 21 in [s["id"] for s in smp], "потолок текста соблюдён, заверенное взято первым")
p = build()
r = main._guide_build(p, "auto")
sysm = SENT["system"]
check(r["ok"] and SENT["n"] == 1, "один вызов на документ")
check("FORM only. NEVER terminology" in sysm, "промпт: только форма, не термины")
check("Uzbek" in sysm and "general" in sysm.lower(), "промпт знает язык перевода и область")
check("oʻ and gʻ" in sysm, "действующие правила языка (lang_rules.json) названы — не повторять")
check("[1] SOURCE:" in SENT["user"] and "TRANSLATION: Tarjima 1." in SENT["user"], "пары ушли в запрос")

print("=== 2. разбор ответа ===")
rules = p["guide"]["rules"]
check(len(rules) == 3, "дубль и слишком длинное отброшены: %d" % len(rules))
check(rules[2]["kind"] == "doc", "неизвестный вид — doc")
check(all(x["on"] and x["by"] == "model" for x in rules), "машинные правила включены и подписаны машиной")
check(p["guide"]["builtBy"] == "auto" and p["guide"]["sample"] == 25, "след сбора на проекте")

print("=== 3. блок в промптах ===")
blk = main._style_block(p)
check("DOCUMENT CONVENTIONS" in blk and "siz" in blk, "правила в блоке стиля")
check("STYLE SHEET" not in blk, "стайл-шит не включён — его строк нет")
mdl = main._resolve_model(None)
dom = main._resolve_domain("general")
check("DOCUMENT CONVENTIONS" in main._translate_system("RU", "UZ", [], None, False, "general", mdl, style=blk),
      "перевод получает правила")
check("DOCUMENT CONVENTIONS" not in main._translate_system("UZ", "RU", None, None, True, "general", mdl, style=blk),
      "обратный перевод — никогда")
check("DOCUMENT CONVENTIONS" in main._review_system(dom, "RU", "UZ", blk)
      and "DOCUMENT CONVENTIONS" in main._repair_system(dom, "RU", "UZ", blk), "ревизия и ремонт — тоже")
q = build()
check(main._style_block(q) == "", "без правил и стайл-шита блок пуст — промпт прежний")
main.STATE["projects"] = [p]

print("=== 4. правка человеком ===")
seg = p["segments"][0]
h = main._text_hash(seg["target"])
seg["review"] = {"v": main.REVIEW_VERSION, "score": 9, "target_hash": h,
                 "source_hash": main._text_hash(seg["source"]), "applied": False}
cur = main.get_project_guide(1)["rules"]
cur[0]["on"] = False                                  # выключил машинное
cur[1]["text"] = "Use «guillemets», never \"straight\" quotes."   # поправил
del cur[2]                                            # удалил машинное
cur.append({"text": "Keep chapter numbers in Roman numerals.", "kind": "doc"})
r = main.set_project_guide(1, main.GuideBody(rules=cur))
rs = {x["text"]: x for x in r["rules"]}
check(r["changed"] and "reviewsStale" not in r and not main._review_stale(seg),
      "правка меняет блок, но ревизию НЕ устаревает — книга не перепокупается")
check(len(r["rules"]) == 3 and all(x["by"] == "human" for x in r["rules"]),
      "тронутое и новое — за человеком")
check("siz" not in r["block"] and "Roman" in r["block"], "выключенное не в блоке, новое — в блоке")
r2 = main.set_project_guide(1, main.GuideBody(rules=main.get_project_guide(1)["rules"]))
check(not r2["changed"], "то же самое ещё раз — ничего не меняется")
check(main._norm_key("Use «guillemets» for quotations.") in p["guide"]["dropped"],
      "исправленное машинное запомнено: пересборка не вернёт прежний текст")
try:
    main.set_project_guide(1, main.GuideBody(rules=[], base="2000-01-01 00:00"))
    check(False, "устаревшая карточка — 409")
except main.HTTPException as e:
    check(e.status_code == 409 and len(main.get_project_guide(1)["rules"]) == 3,
          "устаревшая карточка — 409, правила не тронуты")
try:
    main.set_project_guide(1, main.GuideBody(rules=[{"text": "y" * 500}]))
    check(False, "длинное правило отвергнуто")
except main.HTTPException as e:
    check(e.status_code == 400, "длинное правило отвергнуто: 400")

print("=== 5. пересборка ===")
n0 = SENT["n"]
r = main.build_project_guide(1)
texts = [x["text"] for x in r["rules"]]
check(SENT["n"] == n0 + 1, "пересборка — один вызов")
check("Use «guillemets», never \"straight\" quotes." in texts and "Keep chapter numbers in Roman numerals." in texts,
      "правила человека остались")
check(texts.count("Address the reader formally (siz), never sen.") == 1,
      "машинное, которое человек выключил, не задвоено")
check("Write numbers with a space as thousands separator: 4 773." not in texts,
      "удалённое человеком машинное не вернулось")
check("Use «guillemets» for quotations." not in texts,
      "машинное, которое человек исправил, прежним текстом не вернулось")
check("Keep chapter numbers in Roman numerals." in SENT["system"],
      "правила человека названы сборщику как уже действующие")
check("NO individual word, name or" in SENT["system"], "промпт запрещает подмену отдельных слов и имён")
check("never convert,\n   round or change a value" in SENT["system"], "и пересчёт чисел и единиц")
SENT["fail"] = True
try:
    main.build_project_guide(1)
    check(False, "сбой модели — 502")
except main.HTTPException as e:
    check(e.status_code == 502 and texts == [x["text"] for x in main.get_project_guide(1)["rules"]],
          "сбой модели — 502, прежние правила на месте")
SENT["fail"] = False
r = main.set_project_guide(1, main.GuideBody(off=True))
check(r["off"] and r["active"] == 0 and main._style_block(p) == "", "выключатель снимает блок целиком")
few = build(n=2)
try:
    main.build_project_guide(1)
    check(False, "мало строк — 400")
except main.HTTPException as e:
    check(e.status_code == 400, "мало строк — 400 без вызова модели")

print("=== 6. автосбор в прогоне ===")
p = build(n=5)
job = {"id": 7, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}}
main._job_persist = lambda j: None
n0 = SENT["n"]
main._guide_auto(job)
check(SENT["n"] == n0 and "guide" not in p, "до порога — ничего")
main._guide_auto(job, final=True)
check(SENT["n"] == n0 + 1 and p["guide"]["builtBy"] == "auto" and job["counters"]["guideRules"] == 3,
      "конец прогона: собрано из того, что есть")
main._guide_auto(job, final=True)
check(SENT["n"] == n0 + 1, "второй раз в той же задаче — нет")
p = build(n=25)
job = {"id": 8, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}}
main._guide_auto(job)
check(SENT["n"] == n0 + 2 and job["params"]["guideTried"], "порог достигнут — собрано, флаг в задаче")
job2 = {"id": 9, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}}
main._guide_auto(job2)
check(SENT["n"] == n0 + 2, "у проекта правила уже есть — новая задача их не пересобирает")
p = build(n=25)
for kind, params in (("backcheck", {}), ("review", {}), ("full", {"steps": ["backcheck", "review"]})):
    main._guide_auto({"id": 10, "kind": kind, "project": 1, "tenant": "default", "params": params, "counters": {}})
check(SENT["n"] == n0 + 2 and "guide" not in p, "прогоны без перевода правила не собирают")
main._guide_auto({"id": 11, "kind": "full", "project": 1, "tenant": "default",
                  "params": {"steps": ["translate", "review"]}, "counters": {}})
check(SENT["n"] == n0 + 3 and "guide" in p, "составной прогон с переводом — собирает")
p = build(n=25, guide={"off": True})
main._guide_auto({"id": 12, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(SENT["n"] == n0 + 3, "выключенные человеком правила автосбор не трогает")
p = build(n=5)
main.set_project_guide(1, main.GuideBody(off=True))
main.set_project_guide(1, main.GuideBody(off=False))
check("guide" not in p, "выключили и включили до первого сбора — автосбор не умер")
# Слабые правила с пробного прогона пересобираются один раз.
p = build(n=4)
main._guide_auto({"id": 13, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}}, final=True)
check(p["guide"]["sample"] == 4, "пробный прогон: правила из 4 строк")
for s in p["segments"][:25]:
    s["target"] = s["target"] or "Tarjima."
main._guide_auto({"id": 14, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(p["guide"]["sample"] == 25 and SENT["n"] == n0 + 5, "строк стало достаточно — пересобрано один раз")
main._guide_auto({"id": 15, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(SENT["n"] == n0 + 5, "дальше — нет")
p = build(n=4)
main._guide_auto({"id": 16, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}}, final=True)
p["guide"]["rules"][0]["by"] = "human"
for s in p["segments"][:25]:
    s["target"] = s["target"] or "Tarjima."
main._guide_auto({"id": 17, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(p["guide"]["sample"] == 4, "правила, которых касался человек, автосбор не пересобирает")
# Книга абзацами: выборку режет потолок текста (11 пар), а готовых строк
# сотни — это НЕ слабые правила, и прогоны их не пересобирают.
p = build(n=0)
p["segments"] = [{"id": i, "source": "С" * 600, "target": "T" * 650, "status": "review"} for i in range(1, 201)]
k0 = SENT["n"]
for jid in range(30, 35):
    main._guide_auto({"id": jid, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(SENT["n"] == k0 + 1 and p["guide"]["sample"] < 20 and p["guide"]["ready"] == 200,
      "длинные абзацы: пять прогонов — один сбор (выборка %d, готово %d)" % (p["guide"]["sample"], p["guide"]["ready"]))
# Пересборка слабых — ровно один раз, даже если выборка и после неё мала.
p = build(n=4)
main._guide_auto({"id": 40, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}}, final=True)
for s in p["segments"]:
    s["target"] = "T" * 650
    s["source"] = "С" * 600
k0 = SENT["n"]
for jid in range(41, 45):
    main._guide_auto({"id": jid, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(SENT["n"] == k0 + 1 and p["guide"].get("rebuilt"), "слабые правила пересобраны ровно один раз")
# Сбой внутри шага прогон не роняет.
p = build(n=25)
real = main._guide_build
main._guide_build = lambda *a, **k: 1 / 0
try:
    main._guide_auto({"id": 50, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
    check(True, "исключение внутри шага поймано — прогон не падает")
except Exception as e:
    check(False, "исключение внутри шага поймано — прогон не падает: %s" % e)
main._guide_build = real
# Потолок неудач.
p = build(n=25)
SENT["fail"] = True
k0 = SENT["n"]
for jid in (20, 21, 22):
    main._guide_auto({"id": jid, "kind": "translate", "project": 1, "tenant": "default", "params": {}, "counters": {}})
check(SENT["n"] == k0 + main.GUIDE_AUTO_FAILS and p.get("guideFails") == main.GUIDE_AUTO_FAILS,
      "неудачный автосбор — не больше %d попыток на проект" % main.GUIDE_AUTO_FAILS)
SENT["fail"] = False

print("=== 7. правила языка организации ===")
p = build()
check("Tarjima" not in main._lang_conventions("UZ"), "до сохранения — только правила файла")


class Req:
    pass


main._current_user = lambda request: {"id": "u1"}
r = main.set_org_lang_rules("uz", main.LangRulesBody(rules=["Address the reader formally (siz).", " ", "Address the reader formally (siz)."]), Req())
check(r["rules"] == ["Address the reader formally (siz)."], "пустое и дубль отброшены, код нормализован")
conv = main._lang_conventions("UZ")
check("oʻ and gʻ" in conv and "formally (siz)" in conv, "правило организации добавлено к правилам файла")
check("formally (siz)" not in main._lang_conventions("UZ-CYRL"), "другой язык — не затронут")
check(main._guide_state(p)["orgLang"] == ["Address the reader formally (siz)."], "видно в состоянии правил проекта")
main._guide_build(p, "auto")
p["guide"]["rules"].append({"id": 99, "text": "Address the reader formally (siz).", "kind": "lang", "on": True, "by": "human"})
check("formally (siz)." not in main._guide_block(p) and "formally (siz)." in main._lang_conventions("UZ"),
      "правило, перенесённое в организацию, не дублируется в блоке документа")
main.STATE["tenants"].append({"id": "other", "name": "o"})
check(main._org_lang_rules("UZ", "other") == [], "чужая организация правил не видит")
try:
    main.set_org_lang_rules("zz-bad", main.LangRulesBody(rules=["a"]), Req())
    check(False, "неизвестный язык — 400")
except main.HTTPException as e:
    check(e.status_code == 400, "неизвестный язык — 400")
main.set_org_lang_rules("UZ", main.LangRulesBody(rules=[]), Req())
check("formally (siz)" not in main._lang_conventions("UZ"), "пустой список снимает правила языка")
check(any(m == "POST" and rx.search("/api/lang-rules/UZ") for m, rx in main._OWNER_ONLY),
      "правила языка организации — право владельца")
check(main.USAGE_STEP_GROUP.get("guide") == "review", "расход сбора учтён по модели ревизии")

print("")
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail))
sys.exit(1 if fail else 0)
