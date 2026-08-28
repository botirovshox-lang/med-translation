"""Балл back-check больше не отменяет правку, ПОЧИСТИВШУЮ ТЕРМИНЫ.

Из-за чего написано. На боевом учебнике фтизиатрии 545 сегментов несли свежие
находки termcheck, и ремонт побывал в каждом — «пропущенных» не было ни одного.
216 правок он отменил, и 176 из них отменил ТОЛЬКО упавший балл; у 111 при этом
терминология стала объективно чище. Выброшены были верные тексты: «medicine
physicians» → «pulmonologists», «sanguiferous bed» → «bloodstream», «an infected
animal» → «the patient».

Причина не в модели, а в мере. Балл back-check — доля основ ОРИГИНАЛА,
вернувшихся через обратный перевод (`_content_recall`), поэтому он вознаграждает
КАЛЬКУ: «Erect solar rays» возвращается как «прямые солнечные лучи» слово в
слово, а верное «direct sunlight» возвращается синонимом и балл роняет. Termcheck
заведён ровно против кальки — и его правку отменяла проверка, для которой калька
образцова. Это не эффект коротких сегментов: медиана длины 23 содержательных
слова.

Проверяется здесь четыре правки:
  1. падение балла не отменяет правку, если термины стали чище и жёстких
     находок на новом тексте нет;
  2. ЖЁСТКАЯ находка (числа, единицы, отрицание, сторона) остаётся вето при
     любом улучшении терминологии — размен числа на термин не работа;
  3. сбой перепроверки откатывает правку, но заход НЕ засчитывает: причина
     не в качестве правки, и клеймить за неё сегмент значит закрыть его
     от ремонта навсегда из-за чужой сетевой ошибки;
  4. судья с обеих сторон либо ни с одной: прежний балл мог сложиться с его
     участием, и сравнивать вердикт с сырым измерением нельзя.

Плюс `_repair_score_vetoed` — разбор НАСЛЕДСТВА: записи, сделанные прежним
правилом, никуда не делись, и готовый текст лежит в них в `repair.candidate`.

Платных вызовов нет: и правка, и обе перепроверки подменены.
"""
import os, sys
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


SRC = "Прямые солнечные лучи убивают микобактерии за 5 минут."
OLD_T = "Erect solar rays kill mycobacteria within 5 minutes."
NEW_T = "Direct sunlight kills mycobacteria within 5 minutes."


def seg_of(sid, source, target, **kw):
    s = {"id": sid, "source": source, "target": target, "status": "translated"}
    h = main._text_hash(target.strip())
    if "bc" in kw:
        s["backcheck"] = dict(kw["bc"], target_hash=h)
    if "tc" in kw:
        s["termcheck"] = dict(kw["tc"], target_hash=h)
    if "repair" in kw:
        s["repair"] = dict(kw["repair"])
        s["repair"].setdefault("source_hash", main._text_hash(target))
    return s


def project_of(segments, glossary=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in glossary],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    main._IMPACT_CACHE.clear()
    return proj


# Находка termcheck, ради которой и заходит ремонт: калька вместо термина.
FIND = {"tgt_term": "Erect solar rays", "suggestion": "Direct sunlight",
        "severity": "major", "why": "калька; принято direct sunlight"}


# Сегмент боевой формы: находка termcheck (калька) И претензия back-check
# (приказный термин не пережил круг). Обе нужны: сравнение баллов включается
# только при `had_bc` — то есть когда среди находок есть term_lost, backcheck
# или judge. Именно так выглядели все 111 выброшенных правок: чинили смешанный
# заход, а отменял его балл.
def build(findings=(FIND,), bc=None):
    s = seg_of(1, SRC, OLD_T,
               bc=bc or {"score": 57, "model": "gpt-5.6-luna", "back": OLD_T,
                         "reasons": [], "terms_lost": ["микобактерии"],
                         "judged": False},
               tc={"model": "gpt-5.6-terra", "findings": [dict(f) for f in findings]})
    return project_of([s]), s


def stub_checks(score_after, findings_after, hard=False, judged=False, seen=None):
    """Обе перепроверки подменены: платных вызовов в тестах не бывает.

    `seen` — куда сложить аргумент use_judge: на нём держится проверка 4.
    """
    def fake_bc(s, p, model=None, use_judge=False, judge_model=None, harvest=True):
        if seen is not None:
            seen.append(use_judge)
        s["backcheck"] = {"score": score_after, "model": "gpt-5.6-luna",
                          "back": "обратный", "reasons": [], "terms_lost": [],
                          "hard": hard, "judged": judged,
                          "target_hash": main._text_hash((s["target"] or "").strip())}
        return {"ok": True}

    def fake_tc(s, p, *a, **k):
        s["termcheck"] = {"model": "gpt-5.6-terra",
                          "target_hash": main._text_hash((s["target"] or "").strip()),
                          "findings": [dict(f) for f in findings_after]}
        return {"ok": True}

    main._run_segment_backcheck = fake_bc
    main._run_segment_termcheck = fake_tc


main._openai_repair = lambda *a, **k: NEW_T


# ─────────── 1. Балл упал, термины стали чище — правку оставляем ───────────
print("=== 1. Падение балла не отменяет правку, почистившую термины ===")
proj, seg = build()
kinds = {f["kind"] for f in main._repair_findings(seg, proj)}
check(kinds == {"term", "term_lost"},
      "заход смешанный: калька от termcheck и потерянный термин от back-check")

stub_checks(score_after=8, findings_after=[])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True,
      "балл рухнул 57 → 8, но серьёзных замечаний стало 0 — правку приняли")
check(seg["target"] == NEW_T, "в сегменте стоит исправленный текст")
check(seg["status"] == "review", "заверять его всё равно человеку")
check(any("отменой не считаем" in n for n in (seg["repair"].get("notes") or [])),
      "решение вопреки баллу записано — иначе принятую правку нечем объяснить")
check(main._repair_tried(seg) is True,
      "заход засчитан по НОВОМУ тексту: второй раз по нему не пойдём")

# А без улучшения терминологии балл по-прежнему вето: мера негодна для правки
# термина, но когда править было нечего, отменять её нечему.
proj, seg = build()
stub_checks(score_after=8, findings_after=[dict(FIND)])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False,
      "замечание осталось, балл упал — откат, как и прежде")
check(seg["target"] == OLD_T, "текст вернули")
check("балл back-check упал 57 → 8" in (seg["repair"].get("reason") or ""),
      "и причина названа прежней формулировкой")

# Балл ВЫРОС — вопроса вообще нет.
proj, seg = build()
stub_checks(score_after=91, findings_after=[])
check(main._run_segment_repair(seg, proj).get("applied") is True,
      "выросший балл правку не отменяет и подавно")


# ─────────── 2. Жёсткая находка — вето при любом улучшении ───────────
print("\n=== 2. Жёсткая находка отменяет правку всегда ===")
proj, seg = build()
stub_checks(score_after=8, findings_after=[], hard=True)
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False,
      "числа/единицы/отрицание не зависят ни от морфологии, ни от буквализма")
check(seg["target"] == OLD_T, "текст откачен")
check("балл back-check упал" in (seg["repair"].get("reason") or ""),
      "причина отката названа")

# Тот же случай без жёсткой находки — правка проходит. Отличие ровно в флаге.
proj, seg = build()
stub_checks(score_after=8, findings_after=[], hard=False)
check(main._run_segment_repair(seg, proj).get("applied") is True,
      "снят флаг hard — и та же правка принимается: решает именно он")


# ─────────── 3. Сбой перепроверки не клеймит сегмент ───────────
print("\n=== 3. Сбой вызова — не приговор правке ===")
proj, seg = build()


def dead_tc(s, p, *a, **k):
    """termcheck не ответил: записи нет, значит `terms` станет None."""
    s.pop("termcheck", None)
    return {"ok": False, "error": "сеть"}


stub_checks(score_after=91, findings_after=[])
main._run_segment_termcheck = dead_tc
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False,
      "подтвердить правку нечем — откат: система не заверяет сама себя")
check(seg["target"] == OLD_T, "текст вернули")
check(seg["repair"].get("retryable") is True, "но заход помечен несостоявшимся")
check("source_hash" not in seg["repair"],
      "клейма нет — иначе сегмент закрыт от ремонта навсегда из-за чужой сети")
check(main._repair_tried(seg) is False, "и `tried` его не считает")
check(main._repairable(seg, False, proj) is True,
      "сегмент снова доступен ремонту без всякого retry")

# А вот когда рядом со сбоем стоит претензия ПО СУЩЕСТВУ, заход засчитан:
# правку отвергли не из-за сети, вердикт вынесен, и повторять его — платный
# вызов с заранее известным исходом. Иначе одна оборванная перепроверка
# отпирала бы обратно любой сегмент, отвергнутый по делу.
proj, seg = build()
GLOSS_BAD = [{"src": "микобактерии", "tgt": "mycobacteria", "tier": "verified",
              "cat": "Term", "lang": "RU→EN", "domain": "medical"}]
proj = project_of([seg], GLOSS_BAD)
stub_checks(score_after=91, findings_after=[])
main._run_segment_termcheck = dead_tc
main._openai_repair = lambda *a, **k: "Direct sunlight kills bacteria within 5 minutes."
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "приказный термин выбит — правку отвергли")
why_txt = seg["repair"].get("reason") or ""
check("перепроверка терминов не выполнилась" in why_txt and "утверждённых терминов" in why_txt,
      "в причинах и сбой, и претензия по существу")
check(main._repair_tried(seg) is True,
      "заход засчитан: отвергли по делу, а не из-за оборванного вызова")
check(seg["repair"].get("retryable") is None, "несостоявшимся такой заход не считается")
main._openai_repair = lambda *a, **k: NEW_T

# А отмена ПО ОЦЕНКЕ заход засчитывает: тот же текст с теми же претензиями
# даст тот же ответ модели, и второй заход — платный вызов с известным исходом.
proj, seg = build()
stub_checks(score_after=8, findings_after=[dict(FIND)])
main._run_segment_repair(seg, proj)
check(main._repair_tried(seg) is True, "отказ оценки заход засчитывает")
check(seg["repair"].get("retryable") is None, "и несостоявшимся не помечен")


# ─────────── 4. Судья с обеих сторон либо ни с одной ───────────
print("\n=== 4. Симметрия сравнения: судья ===")
seen = []
proj, seg = build(bc={"score": 70, "model": "gpt-5.6-luna", "back": OLD_T,
                      "reasons": ["судья: смысл расходится"],
                      "terms_lost": ["микобактерии"], "judged": True,
                      "judge": {"severity": "major"}})
stub_checks(score_after=91, findings_after=[], seen=seen)
main._run_segment_repair(seg, proj)          # use_judge из прогона — False
check(seen == [True],
      "прежний балл сложился с судьёй — значит и перепроверка зовёт судью")

seen = []
proj, seg = build()                           # judged: False
stub_checks(score_after=91, findings_after=[], seen=seen)
main._run_segment_repair(seg, proj)
check(seen == [False],
      "судьи в прежней оценке не было — лишнего вызова не покупаем")

seen = []
proj, seg = build()
stub_checks(score_after=91, findings_after=[], seen=seen)
main._run_segment_repair(seg, proj, use_judge=True)
check(seen == [True], "явное разрешение прогона по-прежнему сильнее всего")


# ─────────── 5. Наследство: правка написана, оплачена и отменена ───────────
print("\n=== 5. `_repair_score_vetoed` — что можно принять без вызова модели ===")
GOOD = {"applied": False, "reason": "балл back-check упал 57 → 8",
        "candidate": NEW_T, "issues": ["«Erect solar rays»"],
        "before": {"score": 57, "terms": 1, "gloss": 0},
        "after": {"score": 8, "terms": 0, "gloss": 0}}

s = seg_of(1, SRC, OLD_T, repair=GOOD)
project_of([s])
check(main._repair_score_vetoed(s) is True,
      "отмену держал один балл, термины стали чище — кандидата можно принять")

# Причин было НЕСКОЛЬКО — значит были и законные. Не трогаем.
s = seg_of(1, SRC, OLD_T, repair=dict(
    GOOD, reason="балл back-check упал 57 → 8; нарушено утверждённых терминов больше 0 → 1"))
project_of([s])
check(main._repair_score_vetoed(s) is False,
      "к баллу добавилась вторая претензия — правку отменили по существу")

# Термины НЕ стали чище — балл был единственной мерой, и он сказал «хуже».
s = seg_of(1, SRC, OLD_T, repair=dict(
    GOOD, after={"score": 8, "terms": 1, "gloss": 0}))
project_of([s])
check(main._repair_score_vetoed(s) is False, "замечаний столько же — принимать нечего")

# Улучшение по глоссарию считается наравне с termcheck.
s = seg_of(1, SRC, OLD_T, repair=dict(
    GOOD, before={"score": 57, "terms": 1, "gloss": 2},
    after={"score": 8, "terms": 1, "gloss": 1}))
project_of([s])
check(main._repair_score_vetoed(s) is True,
      "нарушенных приказных терминов стало меньше — это тоже «стало чище»")

# Текст правили ПОСЛЕ отмены: кандидат относится к другому переводу.
s = seg_of(1, SRC, OLD_T, repair=GOOD)
s["target"] = "Someone edited this by hand."
project_of([s])
check(main._repair_score_vetoed(s) is False,
      "перевод меняли после отмены — подставить старого кандидата значит "
      "выбросить чужую работу")

# Пустого кандидата принимать нечем.
s = seg_of(1, SRC, OLD_T, repair=dict(GOOD, candidate=""))
project_of([s])
check(main._repair_score_vetoed(s) is False, "кандидата нет — и предлагать нечего")


# ─────────── 6. Принятие кандидата: без вызова модели ───────────
print("\n=== 6. Принять вариант — команда без модели ===")
s = seg_of(1, SRC, OLD_T, repair=GOOD)
s["status"] = "confirmed"
s["confirmedBy"] = "human"
proj = project_of([s])
out = main._segment_for_client(s)
check(out["repair"].get("acceptable") is True,
      "признак считает сервер и отдаёт браузеру — правило живёт в одном месте")

res = main.accept_repair_candidate(1, 1)
check(res["ok"] and s["target"] == NEW_T, "текст подставлен из repair.candidate")
check(s["prevTarget"] == OLD_T, "прежний перевод сохранён")
check(s["status"] == "review" and "confirmedBy" not in s,
      "отметка «подтвердил человек» снята: она относилась к другому тексту")
check(s["repair"]["applied"] is True and s["repair"]["from"] == OLD_T,
      "запись ремонта стала применённой, прежний текст в ней есть")
check(s["repair"].get("acceptedBy") == "human",
      "и след решения человека остался — иначе это неотличимо от машинной правки")
check(main._repair_tried(s) is True, "заход закрыт по новому тексту")
check(main._check_stale(s.get("backcheck"), s["target"]) is True
      or s.get("backcheck") is None,
      "проверки описывают отвергнутый текст и устарели сами")

# Второй раз принимать нечего.
try:
    main.accept_repair_candidate(1, 1)
    check(False, "повторное принятие обязано быть отказано")
except main.HTTPException as e:
    check(e.status_code == 400, "повторное принятие отклонено с 400")


# ─────────── 7. Корзина в /analysis ───────────
print("\n=== 7. Отдельная строка на экране «Анализ» ===")
vetoed = seg_of(1, SRC, OLD_T, repair=GOOD,
                tc={"model": "gpt-5.6-terra", "findings": [dict(FIND)]})
honest = seg_of(2, "Доза 5 мг в сутки.", "Dose 15 mg per day.",
                repair={"applied": False, "reason": "нарушено утверждённых терминов больше 0 → 1",
                        "candidate": "Dose 5 mg per day.",
                        "issues": ["«15 mg»"],
                        "before": {"score": 40, "terms": 1, "gloss": 0},
                        "after": {"score": 40, "terms": 1, "gloss": 1}},
                bc={"score": 40, "model": "gpt-5.6-luna", "back": "иначе",
                    "reasons": ["расхождение чисел"]},
                tc={"model": "gpt-5.6-terra", "findings": []})
project_of([vetoed, honest])
a = main.project_analysis(1)
check(a["human"]["revertedByScore"] == [1],
      "своя строка: правка была верной, отменил её негодный измеритель")
check(set(a["human"]["reverted"]) >= {1, 2},
      "и это ПОДМНОЖЕСТВО откачённых, а не отдельная корзина — иначе "
      "исчерпаемость держалась бы на совпадении двух предикатов")

print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
