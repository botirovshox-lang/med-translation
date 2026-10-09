"""Список литературы, законная латиница, судья при ручательстве ревизии,
цена кэша промпта.

Четыре правила одной правки (09.10.2026, разбор расхода прогона EN→RU):
  1. список литературы находится ПО ФОРМЕ строк, без слов какого-либо
     языка; «как в оригинале» он остаётся, когда письмо строки совпадает
     с письмом перевода или законно в нём заимствуется (`scriptBorrows`
     в languages.json), иначе переводится; платные проверки его не берут;
  2. проверка письма не считает находкой имя, обозначение и сокращение,
     оставленные буква в букву, — только там, где письменность перевода
     такое заимствует; «МБТ» в английском тексте по-прежнему брак;
  3. судья не зовётся там, где ревизия поручилась за перевод и балл высок;
  4. цена кэша промпта — по долям каталога, поля не уезжают наружу.
"""
import os
import sys
import types

sys.stdout.reconfigure(encoding="utf-8")


class FakeClient:
    def __init__(self, *a, **k):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def create(self, **kw):
        raise RuntimeError("модель в этом наборе не зовётся")


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
os.environ.setdefault("APP_PASSWORD", "x")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
import main  # noqa: E402

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg(i, src, tgt="", status=None, **kw):
    d = {"id": i, "source": src, "target": tgt, "status": status or ("translated" if tgt else "new")}
    d.update(kw)
    return d


REFS_EN = [
    "1. Davies MJ, Aroda VR, Collins BS, et al. Management of hyperglycaemia in type 2 diabetes. Diabetologia 2022;65:1925–1966",
    "2. Khunti K, Chudasama YV, Gregg EW, et al. Diabetes in South Asians. Lancet 2023;401:1220–1231",
    "3. Sun X, Ioannidis JPA, Agoritsas T. How to use a subgroup analysis. JAMA 2014;311:405–411",
    "Atypical diabetes: what have we learned and what does the future hold?",
    "4. Andrews J, Guyatt G, Oxman AD, et al. GRADE guidelines. J Clin Epidemiol 2013;66:719–725",
    "5. Jing T, Zhang S, Bai M, et al. Effect of dietary approaches. JAMA Netw Open 2023;6:e2339337",
    "Funding statement",
    "This work received no external support from any organisation.",
    "6. Poon ET, Li HY, Kong APS, Little JP. Efficacy of exercise. Sports Med 2022;52:1919–1938",
    "7. Wu R, Xing B, Huang Y, et al. Effect of semaglutide. Diabetes Care 2024;47:731–754",
]

print("=== 1. Список литературы: зона по форме строк ===")
body = [seg(100 + i, "Glycemic targets should be individualised for every adult patient %d." % i)
        for i in range(12)]
body[3]["source"] = "As shown previously (Diabetes Care 2019;42:731), targets differ."
refs = [seg(200 + i, s) for i, s in enumerate(REFS_EN)]
proj_en_ru = {"id": 901, "title": "a", "src": "EN", "tgt": "RU", "domain": "medical",
              "segments": body + refs}
r = main._refs_of(proj_en_ru)
check(103 not in r["all"], "одиночная цитата посреди абзаца — не литература")
check(all(i not in r["all"] for i in range(100, 112)), "основной текст не задет")
check({200, 201, 202, 204, 205, 208, 209} <= r["keep"], "записи EN в русском переводе — как в оригинале")
check(203 in r["keep"], "обрывок названия, зажатый записями, — часть записи")
check(206 not in r["all"] and 207 not in r["all"], "строки без признака ссылки внутри зоны переводятся")
check(not r["translate"], "переводить из этой зоны нечего")

refs_ru = ["%d. Иванов И.И., Петров П.П. Туберкулёз лёгких // Пробл. туб. – 2019. – Т. %d, № 3. – С. 45–50."
           % (i, i + 10) for i in range(1, 8)]
proj_ru_en = {"id": 902, "title": "b", "src": "RU", "tgt": "EN", "domain": "medical",
              "segments": [seg(300 + i, s) for i, s in enumerate(refs_ru)]}
r2 = main._refs_of(proj_ru_en)
check(len(r2["translate"]) == 7 and not r2["keep"],
      "кириллические записи в английском переводе — переводятся, не оставляются")
proj_ru_uz = dict(proj_ru_en, id=903, tgt="UZ-CYRL")
check(len(main._refs_of(proj_ru_uz)["keep"]) == 7, "та же письменность у перевода — как в оригинале")
short = {"id": 904, "src": "EN", "tgt": "RU", "segments": [seg(1, REFS_EN[0]), seg(2, REFS_EN[1])]}
check(not main._refs_of(short)["all"], "две ссылки — ещё не список (порог зоны)")

print("\n=== 2. Перевод: литература «как в оригинале» без модели ===")
called = []
real_translate = main._openai_translate


def fake_translate(src, *a, **k):
    called.append(src)
    return "ПЕРЕВОД"


main._openai_translate = fake_translate
main.STATE.update({"projects": [proj_en_ru], "glossary": [], "tm": [], "termQueue": []})
main._invalidate_gloss_index()
out = main.batch_translate(901, main.BatchRequest(segment_ids=[200, 201, 206, 100], limit=10,
                                                  force=False, model=None))
by = {s["id"]: s for s in proj_en_ru["segments"]}
check(by[200]["target"] == by[200]["source"] and by[200]["route"] == main.ROUTE_KEEP_SOURCE,
      "запись встала буква в букву, маршрут KEEP_SOURCE")
check(REFS_EN[0] not in called and REFS_EN[1] not in called, "модель за литературу не звали")
check(by[206]["target"] == "ПЕРЕВОД" and by[100]["target"] == "ПЕРЕВОД", "остальное переведено как обычно")
check(out.get("kept_source") == 2, "отчёт называет число: %s" % out.get("kept_source"))
check(not main._mt_before(by[200]) and main._kept_source(by[200]),
      "строка «как в оригинале» — не перевод моделью (предел перевода заново не тратится)")
main._openai_translate = real_translate

print("\n=== 3. Разбор состава и порция задачи ===")
plan_tr = main._plan_step(proj_en_ru, "translate", {}, proj_en_ru["segments"], set(), set())
check(set(plan_tr["free"]) >= {202, 203, 204, 205, 208, 209} and 202 not in plan_tr["ids"],
      "непереведённая литература — в «бесплатное», не в смету")
plan_rv = main._plan_step(proj_en_ru, "review", {}, proj_en_ru["segments"], set(), set())
check(200 not in plan_rv["ids"] and any("литератур" in x["reason"] for x in plan_rv["skips"]),
      "ревизия литературу не берёт и говорит почему")
rp = main.run_plan(901, main.RunPlanRequest(steps=["translate", "review"]))
check(202 in rp["ids"], "бесплатная работа — в составе задачи (иначе не осушится)")
seen = []
real_bc = main.backcheck_batch
main.backcheck_batch = lambda pid, req: seen.append(list(req.segment_ids)) or {"count": 0}
main._job_chunk("backcheck", 901, [200, 201, 100], {})
check(seen and seen[-1] == [100], "порция проверки — без строк литературы: %s" % seen)
seen.clear()
res = main._job_chunk("backcheck", 901, [200, 201], {})
check(not seen and res == {"done": 0}, "порция из одной литературы — ничего не зовёт")
main.backcheck_batch = real_bc

print("\n=== 4. Законная латиница в проверке письма ===")
def sm(src, tgt):
    return main._script_misses({"source": src, "target": tgt})

check(not sm("What is the impact of vitamin D supplementation?", "Каково влияние приёма витамина D?"),
      "«витамин D» в русском тексте — не находка")
check(not sm("In the UKPDS trial HbA1c fell.", "В исследовании UKPDS HbA1c снизился."),
      "сокращения и обозначения из оригинала — не находка")
check(not sm("They are editors of Diabetes Care but not involved.",
             "Они редакторы журнала Diabetes Care, но не участвовали."),
      "название с заглавной посреди фразы оригинала — не находка")
check(bool(sm("Steps from ~6000 to ~10,000/day are linked to lower risk.",
              "Проверим: от ~6000 to ~10 000/day связано со снижением риска.")),
      "строчные слова («to», «day») — находка: так выглядит утечка рассуждений модели")
check(bool(sm("Metformin is first-line; use metformin daily.", "Препарат первой линии; metformin ежедневно.")),
      "непереведённое строчное слово — находка")
check(bool(sm("Vitamin C deficiency.", "Дефицит витамина C.")),
      "одиночная буква с двойником в кириллице (C) — находка")
check(bool(sm("Выявлены МБТ в мокроте.", "MBT were found: МБТ in sputum.")),
      "кириллица в английском тексте («МБТ») — по-прежнему находка")

print("\n=== 5. Судья не нужен при ручательстве ревизии ===")
s = seg(1, "Glycemic targets should be individualised for adults with diabetes.",
        "Целевые показатели гликемии следует подбирать индивидуально у взрослых с диабетом.")
s["review"] = {"v": main.REVIEW_VERSION, "score": 9.5, "code": "ok",
               "target_hash": main._text_hash(s["target"]), "source_hash": main._text_hash(s["source"])}
s["backcheck"] = {"score": 93, "target_hash": main._text_hash(s["target"]), "model": "m"}
check(main._review_vouches(s), "ревизия ручается (предусловие)")
check(main._judge_waived(s, 93) and not main._judge_pending(s, above=True),
      "балл 93 + ручательство — судья не нужен, и в расширенной зоне тоже")
s["backcheck"]["score"] = 80
check(not main._judge_waived(s, 80) and main._judge_pending(s), "балл ниже порога — судья нужен")
s["backcheck"]["score"] = 93
s["review"]["score"] = 7
check(main._judge_pending(s), "без ручательства — судья нужен")
s["review"]["score"] = 9.5
old = main.JUDGE_WAIVE_MIN
main.JUDGE_WAIVE_MIN = 0
check(main._judge_pending(s), "JUDGE_WAIVE_MIN=0 выключает правило")
main.JUDGE_WAIVE_MIN = old

print("\n=== 6. Цена кэша промпта и её показ ===")
p = main._model_price("claude-sonnet-5")
want = (1000 - 800 - 100) / 1e6 * 2 + 800 / 1e6 * 2 * 0.1 + 100 / 1e6 * 2 * 1.25 + 50 / 1e6 * 10
check(abs(main._usage_cost("claude-sonnet-5", 1000, 50, 800, 100) - want) < 1e-12,
      "чтение 0.1, запись 1.25 цены входа")
check(abs(main._usage_cost("gpt-4o", 1000, 50, 800, 0) - (1000 / 1e6 * 2.5 + 50 / 1e6 * 10)) < 1e-12,
      "у модели без долей кэша — полная цена входа, как прежде")
real_hm, real_hc = main._hide_models, main._hide_cost
main._hide_models, main._hide_cost = (lambda: True), (lambda: False)
rows = main._models_public()
check(all("cacheRead" not in r and "cacheWrite" not in r for r in rows),
      "доли кэша не уезжают тому, от кого прячут модели")
main._hide_models, main._hide_cost = (lambda: False), (lambda: True)
rows = main._models_public()
check(all("cacheRead" not in r for r in rows), "и тому, от кого прячут деньги")
main._hide_models, main._hide_cost = real_hm, real_hc

print("\n=== 6а. Кэш помечается только у повторяющегося системного текста ===")
main._ANTH_SYS_SEEN.clear()
check(not main._anthropic_cache_mark("claude-sonnet-5", "RULES A"), "первый раз — без пометки (записывать нечего)")
check(main._anthropic_cache_mark("claude-sonnet-5", "RULES A"), "тот же текст снова — пометка")
check(not main._anthropic_cache_mark("claude-sonnet-5", "RULES B: строка 2"),
      "уникальный текст (перевод: термины и соседи строки) — без пометки, надбавки нет")
check(not main._anthropic_cache_mark("claude-opus-5", "RULES A"), "кэш у каждой модели свой")

print("\n=== 6б. Капс и заголовки — не «имена» ===")
check(bool(sm("INTRODUCTION and scope.", "INTRODUCTION и область применения.")),
      "длинное слово капсом, оставленное как есть, — находка")
check(bool(sm("Diagnosis And Treatment Of Diabetes", "Diagnosis и лечение диабета")),
      "заглавная в заголовке Title Case — не признак имени")
check(not sm("Use of MASH criteria.", "Применение критериев MASH."), "короткое сокращение — по-прежнему законно")

print("\n=== 6в. «Как в оригинале» — не донор перевода и не образец ===")
k = {"id": 1, "source": "Diabetes Care 2026;49:S1.", "target": "Diabetes Care 2026;49:S1.",
     "status": "translated", "route": main.ROUTE_KEEP_SOURCE, "provider": "keep"}
check(not main._prev_ctx_usable(k), "строка литературы как в оригинале соседу образцом не идёт")
check("keep" in main._ALIAS_SKIP, "«keep» — не модель, псевдонимом не прячется")

print("\n=== 7. Корзины «Проверки»: исчерпывающие, литература не висит ===")
# Прежний прогон оставил на строке литературы находки (балл, латиница): они
# не должны держать её ни у машины, ни у человека.
by[201]["backcheck"] = {"score": 20, "target_hash": main._text_hash(by[201]["target"]), "model": "m"}
main._ANALYSIS_CACHE.pop(901, None)
main._IMPACT_CACHE.pop(901, None)
an = main.project_analysis(901, refresh=True)
tk = an["turnkey"]
allids = set(tk["ready"]) | set(tk["machine"]) | set(tk["human"])
check(len(allids) == len(proj_en_ru["segments"]) == len(tk["ready"]) + len(tk["machine"]) + len(tk["human"]),
      "корзины не пересекаются и покрывают проект")
check(200 in tk["ready"] and 201 in tk["ready"], "заполненная литература — «готово», а не «спрошу/доделаю»")
check(202 in tk["machine"], "незаполненная литература — работа прогона (её заполнит перевод)")

# Переведённая запись (кириллица → латиница) с разошедшимся годом — человеку.
segs_ru = proj_ru_en["segments"]
for k, sg in enumerate(segs_ru):
    sg["target"] = ("%d. Ivanov II, Petrov PP. Pulmonary tuberculosis. Probl Tub 2019;%d(3):45–50."
                    % (k + 1, k + 11))
    sg["status"] = "translated"
segs_ru[2]["target"] = segs_ru[2]["target"].replace("2019", "2091")
main.STATE["projects"].append(proj_ru_en)
an2 = main.project_analysis(902, refresh=True)
why = {w["id"]: [x["code"] for x in w["why"]] for w in an2["turnkey"].get("why") or []}
check(302 in an2["turnkey"]["human"] and "refNumbers" in why.get(302, []),
      "разошедшийся год в переведённой записи — вопрос человеку (refNumbers)")
check(301 in an2["turnkey"]["ready"], "запись без расхождений — «готово»")

print()
if fail:
    print("FAILED: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
