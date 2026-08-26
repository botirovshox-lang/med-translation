"""Спорный термин: что решается бесплатно, а что — контекстным арбитром.

Проверки смотрят на сегмент в одиночку, и на этом ломались три разные вещи.

  1. Back-check требовал, чтобы обратный перевод сохранил ПОДСКАЗКИ
     автоимпорта. Модели их игнорировать разрешено прямо в промпте
     («use these exact translations» только для verified), и наказывать её
     за принятое разрешение нельзя. На боевом проекте так возникали 56 спорных
     сегментов из 67: балл держали «лёгких», «высокой», «оценка», «метод» —
     падежные формы обычных слов, которым сверка смысла УЖЕ проставила
     rule: false.

  2. «Пережил ли термин круг» считалось по обрезке слова до шести букв,
     а она режет русское слово ровно по окончанию: «высокой» → «высоко»,
     «высокую» → «высоку». Слово в тексте есть, а проверка объявляет термин
     потерянным. При этом «противотуберкулёзный» против «туберкулёзного» —
     потеря настоящая, и её нельзя проглядеть заодно.

  3. Что осталось, в одиночку не решается вовсе: «туберкулёз лёгких» обратный
     перевод возвращает как «лёгочный туберкулёз» — по словам потеря, по смыслу
     то же самое. Отвечает арбитр, единственный, кому дают соседей.

Платных вызовов нет: и перевод, и арбитр подменены.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
import medical_qa

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


GLOSS = [
    {"src": "туберкулёз лёгких", "tgt": "pulmonary tuberculosis", "tier": "verified",
     "cat": "Disease", "lang": "RU→EN", "domain": "medical"},
    # Мусор массового импорта: обычное слово в падежной форме, уровень «подсказка».
    {"src": "высокой", "tgt": "high", "tier": "auto",
     "cat": "Other", "lang": "RU→EN", "domain": "medical"},
]


def build(source, target, back, terms_lost=(), tc=None, glossary=GLOSS):
    h = main._text_hash(target.strip())
    seg = {"id": 2, "source": source, "target": target, "status": "translated",
           "backcheck": {"score": 60, "model": "gpt-5.6-luna", "back": back,
                         "judged": False, "reasons": [], "terms_lost": list(terms_lost),
                         "target_hash": h}}
    if tc is not None:
        seg["termcheck"] = {"model": "gpt-5.6-terra", "findings": tc, "target_hash": h}
    before = {"id": 1, "source": "1. Клинические формы туберкулёза", "target": "1. Clinical forms of tuberculosis", "status": "translated"}
    after = {"id": 3, "source": "Диагностика проводится следующим образом.", "target": "Diagnosis is performed as follows.", "status": "translated"}
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [before, seg, after]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in glossary],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    main._IMPACT_CACHE.clear()
    return proj, seg


# ─────────── 1. Подсказка не может уронить балл ───────────
print("=== 1. За проигнорированную ПОДСКАЗКУ back-check не наказывает ===")
proj, seg = build("Микобактерии обладают высокой устойчивостью.",
                  "Mycobacteria exhibit high resistance.",
                  "Микобактерии проявляют высокую устойчивость.")
hits = main._verified_hits(seg["source"], proj)
check(all(h.get("src") != "высокой" for h in hits),
      "подсказка автоимпорта в требования сегмента не входит")
res = medical_qa.run_backcheck(seg["source"], seg["backcheck"]["back"], hits)
check(res["terms_lost"] == [],
      "и потерянным термином не считается: модели её разрешено игнорировать")

# А приказная запись — считается, как и раньше.
proj2, seg2 = build("Очаговый туберкулёз лёгких у взрослых.",
                    "Focal pulmonary tuberculosis in adults.",
                    "Очаговый лёгочный туберкулёз у взрослых.")
hits2 = main._verified_hits(seg2["source"], proj2)
res2 = medical_qa.run_backcheck(seg2["source"], seg2["backcheck"]["back"], hits2)
check(res2["terms_lost"] == ["туберкулёз лёгких"],
      "приказная запись по-прежнему обязана пережить круг")


# ─────────── 2. Формы слова — не потеря, а приставка — потеря ───────────
print("\n=== 2. Обрезка основы больше не выносит приговор ===")
def survived(term, back):
    return medical_qa._term_survived(term, set(medical_qa._stems(back)),
                                     medical_qa._words_of(back))


for term, back, want, note in [
    ("высокой", "проявляют высокую устойчивость", True, "«высокой» / «высокую» — одно слово"),
    ("формам", "клинические формы туберкулёза", True, "«формам» / «формы» — одно слово"),
    ("метод", "применяется метода микроскопии", True, "«метод» / «метода» — одно слово"),
    ("противотуберкулёзный", "открыт первый туберкулёзный диспансер", False,
     "отвалившаяся приставка остаётся НАСТОЯЩЕЙ потерей"),
    ("микроскопия мокроты", "проведена микроскопию мокроты", True,
     "составной термин сходится по обеим частям"),
    ("туберкулёз лёгких", "очаговый лёгочный туберкулёз", False,
     "«лёгких» против «лёгочный» бесплатно не разрешить — это вопрос к арбитру"),
]:
    check(survived(term, back) is want, note)


# ─────────── 3. Арбитр: что он спрашивает и что делает с ответом ───────────
print("\n=== 3. Контекстный арбитр ===")
proj, seg = build("Очаговый туберкулёз лёгких у взрослых.",
                  "Focal pulmonary tuberculosis in adults.",
                  "Очаговый лёгочный туберкулёз у взрослых.",
                  terms_lost=["туберкулёз лёгких"])
d = main._term_disputes_of(seg, proj)
check([x["src"] for x in d] == ["туберкулёз лёгких"], "спор найден по приказной записи")
check(d[0]["forms"] == ["туберкулёз лёгких"],
      "и запомнена НАЙДЕННАЯ форма — по ней потом снимается претензия ремонта")

prev_src, next_src = main._neighbours(proj, seg)
check(prev_src.startswith("1. Клинические формы") and next_src.startswith("Диагностика"),
      "соседи берутся по порядку в документе, а не по номерам id")

asked = {}


def fake_arbiter(ok, use="", why=""):
    def f(sg, pj, disputes, prev, nxt, model):
        asked["prev"], asked["next"] = prev, nxt
        asked["disputes"] = [x["src"] for x in disputes]
        return {"model": "gpt-5.6-terra",
                "terms": [{"src": x["src"], "ok": ok, "use": use, "why": why} for x in disputes]}
    main._openai_term_context = f


# 3a. «Передан верно» — претензия снимается, ремонт по ней не идёт.
fake_arbiter(True)
main._corpus_check = lambda *a, **k: None
check([f["kind"] for f in main._repair_findings(seg, proj)] == ["term_lost"],
      "до арбитра претензия есть и ремонт по ней пойдёт")
r = main._run_segment_term_context(seg, proj, "gpt-5.6-terra")
check(r["ok"] and asked["disputes"] == ["туберкулёз лёгких"],
      "арбитр спрошен ровно про спорный термин")
check(asked["prev"].startswith("1. Клинические формы"),
      "и получил сегмент ДО — иначе вопрос «верно ли ЗДЕСЬ» не имеет смысла")
check(main._repair_findings(seg, proj) == [],
      "после «передан верно» претензия снята: ремонт не пойдёт переписывать верный перевод")

# 3b. «Передан неверно» — это вопрос к ЗАПИСИ, а не заход ремонта.
proj, seg = build("Очаговый туберкулёз лёгких у взрослых.",
                  "Focal pulmonary tuberculosis in adults.",
                  "Очаговый лёгочный туберкулёз у взрослых.",
                  terms_lost=["туберкулёз лёгких"])
fake_arbiter(False, "lung tuberculosis", "здесь речь о поражении органа")
main._corpus_check = lambda *a, **k: {"ok": True, "hits": 120, "source": "pubmed"}
main._run_segment_term_context(seg, proj, "gpt-5.6-terra")
kinds = [f["kind"] for f in main._repair_findings(seg, proj)]
check("term_ctx" not in kinds,
      "ремонту это НЕ отдаётся: подстановка чужого варианта нарушит приказ и будет откачена")
a = main.project_analysis(1)
check([w["src"] for w in a["human"]["termContextWrong"]] == ["туберкулёз лёгких"],
      "зато вердикт виден человеку в «Анализе» — там, где решают судьбу записи")
check(a["human"]["termContextWrong"][0]["use"] == "lung tuberculosis",
      "вместе с готовым вариантом")

# 3c. Корпус целевого языка накладывает вето БЕСПЛАТНО.
proj, seg = build("Очаговый туберкулёз лёгких у взрослых.",
                  "Focal pulmonary tuberculosis in adults.",
                  "Очаговый лёгочный туберкулёз у взрослых.",
                  terms_lost=["туберкулёз лёгких"])
fake_arbiter(False, "lungs tuberculose", "калька")
main._corpus_check = lambda *a, **k: {"ok": False, "hits": 0, "source": "pubmed"}
main._run_segment_term_context(seg, proj, "gpt-5.6-terra")
t = seg["termContext"]["terms"][0]
check(t["use"] == "", "варианта, которого нет в корпусе целевого языка, арбитр не предлагает")
check("не найден в корпусе" in t["why"], "и сказано, почему он снят")

# 3d. Молчание корпуса — «не знаю»: не одобряет и не блокирует.
proj, seg = build("Очаговый туберкулёз лёгких у взрослых.",
                  "Focal pulmonary tuberculosis in adults.",
                  "Очаговый лёгочный туберкулёз у взрослых.",
                  terms_lost=["туберкулёз лёгких"])
fake_arbiter(False, "lung tuberculosis", "")
main._corpus_check = lambda *a, **k: None
main._run_segment_term_context(seg, proj, "gpt-5.6-terra")
check(seg["termContext"]["terms"][0]["use"] == "lung tuberculosis",
      "корпус молчит — вариант остаётся: «не знаю» не должно ни одобрять, ни блокировать")

# 3e. Вердикт устаревает вместе с текстом — как back-check и termcheck.
check(not main._term_context_stale(seg), "свежий вердикт свежим и считается")
seg["target"] = "Focal lung tuberculosis in adults."
check(main._term_context_stale(seg),
      "перевод изменился — вердикт больше не про этот текст")
check(main._term_context_of(seg) == [],
      "и читать его нельзя: иначе претензия снималась бы с текста, которого нет")


# ─────────── 4. Соседи в промпте перевода ───────────
print("\n=== 4. Соседи доезжают до перевода и НЕ доезжают до обратного ===")
mdl = main._resolve_model(None)
p = main._translate_system("RU", "EN", [], None, False, "medical", mdl,
                           "1. Клинические формы", "Диагностика проводится так:")
check("Surrounding context" in p and "1. Клинические формы" in p,
      "обычный перевод видит обстановку")
check("do NOT translate it" in p and "Translate ONLY the user message" in p,
      "и дважды предупреждён, что переводить её не надо")
lit = main._translate_system("EN", "RU", [], None, True, "medical", mdl, "сосед до", "сосед после")
check("Surrounding context" not in lit,
      "обратный перевод обстановки не получает: он обязан ОТРАЖАТЬ текст, а не понимать его")
check(main._neighbours(proj, proj["segments"][0])[0] == "",
      "у первого сегмента соседа слева нет — и это пустая строка, а не ошибка")
check(main._neighbours(None, None) == ("", ""), "без проекта соседей тоже нет")

print()
print("")
print("=== Сверка терминов моделью как штатный шаг ===")
# Шаг спрашивает про ВСЕ приказные термины сегмента, а не только про спорные.
# Детерминированная проверка знает морфологию одного языка и знает её грубо;
# модель отвечает на тот же вопрос на любом языке — ради этого шаг и заведён.
proj, seg = build("Очаговый туберкулёз лёгких у взрослых.",
                  "Focal pulmonary tuberculosis in adults.",
                  "Очаговый лёгочный туберкулёз у взрослых.")
check([d["src"] for d in main._term_disputes_of(seg, proj)] == [],
      "спора нет: термин на месте, проверки молчат")
audit = main._term_terms_of(seg, proj, disputes_only=False)
check([d["src"] for d in audit] == ["туберкулёз лёгких"],
      "а сверка всё равно спрашивает про приказной термин сегмента")
check(audit[0]["why"] == "" and audit[0]["forms"] == ["туберкулёз лёгких"],
      "без причины (спора нет) и с формой из текста: %r" % (audit[0],))
check(all(_d["src"] != "высокой" for _d in audit),
      "подсказку автоимпорта не сверяем: модели разрешено её игнорировать")

# Промпт один на оба режима, поэтому вердикт, полученный шагом, закрывает
# и спор. Версия вопросов поднята — иначе новый вопрос не задавался бы никогда.
check(main.TERM_CONTEXT_VERSION >= 2, "версия вопросов поднята вместе с промптом")
asked = {}


def fake_ctx(seg_, project_, disputes, prev_src, next_src, model):
    asked["terms"] = [d["src"] for d in disputes]
    return {"terms": [{"src": "туберкулёз лёгких", "ok": True, "use": "", "why": "передан верно"}],
            "model": "gpt-5.6-terra"}


main._openai_term_context = fake_ctx
r = main._run_segment_term_context(seg, proj, None, disputes_only=False)
check(r.get("ok") is True and asked["terms"] == ["туберкулёз лёгких"],
      "шаг спросил про приказной термин")
check(main._term_context_stale(seg) is False, "вердикт записан и свеж")
check([t["ok"] for t in main._term_context_of(seg)] == [True], "и читается как «передан верно»")

# «Передан верно» СНИМАЕТ претензию: ремонт по ней больше не пойдёт.
seg["backcheck"]["terms_lost"] = ["туберкулёз лёгких"]
check(not any(f["kind"] == "term_lost" for f in main._repair_findings(seg, proj)),
      "снятая арбитром претензия в ремонт не идёт")

# Разбор шага и его исполнение считают ОДНО и то же: иначе под соседними
# кнопками стояли бы разные числа.
plan = main._plan_step(proj, "termaudit", {}, list(proj["segments"]), set(), set())
check(seg["id"] not in plan["ids"], "сверенный сегмент разбор второй раз не берёт")
seg["target"] = "Focal pulmonary TB in adults."
plan2 = main._plan_step(proj, "termaudit", {}, list(proj["segments"]), set(), set())
check(seg["id"] in plan2["ids"], "а после правки перевода — берёт: вердикт устарел")
check("termaudit" in main.FULL_RUN_STEPS
      and main.FULL_RUN_STEPS.index("termaudit") < main.FULL_RUN_STEPS.index("repair"),
      "шаг стоит ПЕРЕД ремонтом: его вердикт снимает претензию, и ремонт "
      "по снятой не идёт")
check(main.FULL_RUN_STEPS.index("termaudit") > main.FULL_RUN_STEPS.index("termcheck"),
      "и ПОСЛЕ проверки терминов: её находки — причина спора")
check(main.FULL_STEP_MODEL["termaudit"] == "tcx_model" and "termaudit" in main.JOB_CHUNKS,
      "у шага своя модель и своя порция")

if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
