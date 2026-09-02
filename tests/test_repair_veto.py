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
    def fake_bc(s, p, model=None, use_judge=False, judge_model=None, harvest=True, **kw):
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


# ─────────── 6b. Миграция: снять клеймо, поставленное прежним кодом ───────────
print()
print("=== 6b. Клеймо прежнего кода снимается миграцией ===")
STAMPED = {"applied": False, "reason": main.REPAIR_RECHECK_FAILED,
           "candidate": NEW_T, "issues": ["«Erect solar rays»"],
           "source_hash": main._text_hash(OLD_T)}
MIXED = {"applied": False,
         "reason": main.REPAIR_RECHECK_FAILED + "; нарушено утверждённых терминов больше 0 → 1",
         "candidate": NEW_T, "issues": ["«Erect solar rays»"],
         "source_hash": main._text_hash(OLD_T)}
st = {"projects": [{"id": 1, "segments": [
        dict(seg_of(1, SRC, OLD_T), repair=dict(STAMPED)),
        dict(seg_of(2, SRC, OLD_T), repair=dict(MIXED))]}],
      "glossary": [], "tm": [], "termQueue": []}
main._apply_migrations(st)
a, b = st["projects"][0]["segments"]
check("source_hash" not in a["repair"] and a["repair"].get("retryable") is True,
      "сбой был единственной причиной — клеймо снято, сегмент снова доступен")
check(a["repair"].get("reason") == main.REPAIR_RECHECK_FAILED,
      "причина отказа сохранена: теряется только запись о попытке")
check(b["repair"].get("source_hash") == main._text_hash(OLD_T),
      "рядом стояла претензия по существу — вердикт вынесен, клеймо остаётся")

main._apply_migrations(st)                      # второй проход
check("source_hash" not in a["repair"], "миграция идемпотентна: снимать второй раз нечего")


# ─────────── 6c. Пачкой: разбор, бэкап, откат ───────────
print()
print("=== 6c. Принять пачкой ===")
import tempfile, pathlib
main.PURGE_DIR = pathlib.Path(tempfile.mkdtemp())

# С открытыми находками: пачка берёт ровно то, что показывает корзина
# в /analysis, а та требует, чтобы к сегменту были претензии.
TCF = {"model": "gpt-5.6-terra", "findings": [dict(FIND)]}
a1 = seg_of(1, SRC, OLD_T, repair=dict(GOOD), tc=TCF)
a2 = seg_of(2, SRC, OLD_T, repair=dict(GOOD), tc=TCF)
conf = seg_of(3, SRC, OLD_T, repair=dict(GOOD), tc=TCF)
conf["status"] = "confirmed"
conf["confirmedBy"] = "human"
other = seg_of(4, SRC, OLD_T, tc=TCF, repair=dict(
    GOOD, reason="балл back-check упал 57 → 8; замечаний по терминам стало больше 1 → 2"))
project_of([a1, a2, conf, other])

dry = main.accept_repair_candidates(1)
check(dry["dryRun"] is True and dry["matched"] == 2,
      "разбор по умолчанию: считает и показывает, ничего не меняя")
check(a1["target"] == OLD_T, "текст при разборе не тронут")
check(dry["skippedConfirmed"] == [3],
      "заверенное человеком пачкой не трогаем и говорим, сколько таких")
check(4 not in dry["ids"], "правку с претензией по существу не принимаем")
check(dry["samples"] and dry["samples"][0]["now"] == NEW_T,
      "в разборе показано, что именно встанет в перевод")

res = main.accept_repair_candidates(1, main.RepairAcceptBatchRequest(dry_run=False))
check(res["accepted"] == 2 and res["stamp"], "применение состоялось и назвало метку отката")
check(a1["target"] == NEW_T and a2["target"] == NEW_T, "оба текста подставлены")
check(conf["target"] == OLD_T and conf.get("confirmedBy") == "human",
      "заверенный человеком не тронут — отметка на месте")
check((main.PURGE_DIR / ("repair-accept-" + res["stamp"] + ".json")).exists(),
      "копия для отката записана: массовой правки текста без отката не бывает")

# Разрешение на заверенные — отдельным полем, а не правкой правила.
res2 = main.accept_repair_candidates(1, main.RepairAcceptBatchRequest(
    dry_run=False, include_confirmed=True))
check(res2["accepted"] == 1 and conf["target"] == NEW_T,
      "с явным разрешением берётся и заверенный")
# Две пачки укладываются в одну секунду, и метка обязана быть РАЗНОЙ: иначе
# вторая затирает копию первой, и откат первой возвращает чужие сегменты.
check(res2["stamp"] != res["stamp"], "метки двух пачек подряд не совпадают")
check((main.PURGE_DIR / ("repair-accept-" + res["stamp"] + ".json")).exists()
      and (main.PURGE_DIR / ("repair-accept-" + res2["stamp"] + ".json")).exists(),
      "обе копии на месте — затирания нет")
check(conf["status"] == "review" and "confirmedBy" not in conf,
      "и отметка с него снимается: он заверял другой текст")

# Откат возвращает всё, кроме того, что правили после.
a2["target"] = "Кто-то поправил это руками."
undo = main.undo_accept_repair_candidates(1, res["stamp"])
check(undo["restored"] == [1], "вернули только сегмент 1")
check(a1["target"] == OLD_T, "и текст у него прежний")
check(undo["changedSince"] == [2],
      "сегмент 2 правили после принятия — откат его не трогает и называет")
check(a2["target"] == "Кто-то поправил это руками.", "чужая работа цела")
check(main._repair_score_vetoed(a1) is True,
      "откат вернул и запись ремонта: кандидат снова на месте")

# Метка из URL подставляется в путь, поэтому сначала проверяется её ФОРМА —
# то же правило, что у откатов пересчёта баллов и выноса глоссария.
try:
    main.undo_accept_repair_candidates(1, "../../etc/passwd")
    check(False, "кривая метка обязана быть отклонена")
except main.HTTPException as e:
    check(e.status_code == 400, "метка неверной формы — 400, в путь она не попадает")
try:
    main.undo_accept_repair_candidates(1, "20200101-000000")
    check(False, "откат по несуществующей метке обязан быть отказан")
except main.HTTPException as e:
    check(e.status_code == 404, "метка верной формы, но копии нет — 404")
# Копия помнит свой проект: метку от чужого проекта в откат не принимаем.
main.STATE["projects"].append({"id": 7, "src": "RU", "tgt": "EN",
                               "domain": "medical", "segments": []})
try:
    main.undo_accept_repair_candidates(7, res["stamp"])
    check(False, "чужая метка обязана быть отклонена")
except main.HTTPException as e:
    check(e.status_code == 400, "копия от другого проекта — 400")


# ────── 6d. Находки внешнего ревью: чего нельзя предлагать к принятию ──────
print()
print("=== 6d. Жёсткая находка и сбой — разбор ревью ===")

# (1) Правку отменила ЖЁСТКАЯ находка на кандидате. Строка причины у неё почти
# та же, что у «просто упал балл», поэтому решает поле записи. Без него система
# предлагала человеку принять текст с испорченным ЧИСЛОМ.
proj, seg = build()
stub_checks(score_after=8, findings_after=[], hard=True)
main._openai_repair = lambda *a, **k: "Direct sunlight kills mycobacteria within 50 minutes."
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "жёсткая находка правку отменила")
check(seg["repair"].get("hardAfter") is True, "исход вето записан отдельным полем")
check("жёсткая находка" in (seg["repair"].get("reason") or ""),
      "и человеку сказано словами, а не только полем")
check(main._repair_score_vetoed(seg) is False,
      "принимать такое нельзя: размен числа на термин — не работа")
check(main._segment_for_client(seg)["repair"].get("acceptable") is False,
      "и кнопки «Принять» у него нет")
main._openai_repair = lambda *a, **k: NEW_T

# (2) У записей ПРЕЖНЕГО кода поля нет, а отменить их могла та же жёсткая
# находка. Кандидата поэтому сверяем с оригиналом заново — бесплатно.
OLDREC = {"applied": False, "reason": "балл back-check упал 57 → 8",
          "issues": ["x"], "before": {"score": 57, "terms": 1, "gloss": 0},
          "after": {"score": 8, "terms": 0, "gloss": 0}}
s_ok = seg_of(1, SRC, OLD_T, repair=dict(OLDREC, candidate=NEW_T))
s_bad = seg_of(2, SRC, OLD_T, repair=dict(
    OLDREC, candidate="Direct sunlight kills mycobacteria within 50 minutes."))
project_of([s_ok, s_bad])
check(main._repair_score_vetoed(s_ok) is True, "старая запись с целыми числами принимается")
check(main._repair_score_vetoed(s_bad) is False,
      "старая запись с испорченным числом — нет, хотя поля hardAfter у неё нет")

# (3) Сбой перепроверки ВМЕСТЕ с упавшим баллом. Это самая частая форма отказа,
# и заход по ней засчитывать нельзя: балл — та самая негодная мера, а взвесить
# её было нечем именно потому, что termcheck не ответил.
proj, seg = build()
stub_checks(score_after=8, findings_after=[])
main._run_segment_termcheck = dead_tc
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "правку откатили")
w = seg["repair"].get("reason") or ""
check("балл back-check упал" in w and main.REPAIR_RECHECK_FAILED in w,
      "в причинах и балл, и сбой")
check("source_hash" not in seg["repair"] and seg["repair"].get("retryable") is True,
      "заход НЕ засчитан: по существу сказано не было ничего")
check(main._repair_tried(seg) is False, "сегмент остаётся доступен ремонту")

# (4) Миграция разжимает и смешанные записи прежнего кода, но НЕ трогает те,
# где рядом стояла жёсткая находка.
MIX = {"applied": False, "source_hash": main._text_hash(OLD_T),
       "reason": "балл back-check упал 57 → 8; " + main.REPAIR_RECHECK_FAILED}
HARDMIX = {"applied": False, "source_hash": main._text_hash(OLD_T),
           "reason": "балл back-check упал 57 → 8, жёсткая находка на новом тексте; "
                     + main.REPAIR_RECHECK_FAILED}
st2 = {"projects": [{"id": 1, "segments": [
        dict(seg_of(1, SRC, OLD_T), repair=dict(MIX)),
        dict(seg_of(2, SRC, OLD_T), repair=dict(HARDMIX))]}],
       "glossary": [], "tm": [], "termQueue": []}
main._apply_migrations(st2)
m1, m2 = st2["projects"][0]["segments"]
check("source_hash" not in m1["repair"] and m1["repair"].get("attemptHash"),
      "смешанная запись разжата, клеймящий хеш стал информационным")
check(m2["repair"].get("source_hash"), "запись с жёсткой находкой не тронута")

# Правило отмены изменилось — прежние вердикты по нему больше не держат сегмент.
RULE = {"applied": False, "source_hash": main._text_hash(OLD_T),
        "reason": "замечаний по терминам стало больше 1 → 2"}
st3 = {"projects": [{"id": 1, "segments": [dict(seg_of(1, SRC, OLD_T), repair=dict(RULE))]}],
       "glossary": [], "tm": [], "termQueue": []}
main._apply_migrations(st3)
m3 = st3["projects"][0]["segments"][0]
check("source_hash" not in m3["repair"] and m3["repair"].get("retryReason") == "rules",
      "вердикт прежнего правила снят и помечен своей причиной")
check(m3["repair"].get("attemptHash"), "хеш попытки сохранён информационным")
main._apply_migrations(st3)
check("source_hash" not in m3["repair"], "и эта миграция идемпотентна")

# Тот же случай у вето по баллу: счётчик не изменился («1 → 1»), значит заказ
# мог быть снят, а прежнее правило этого не умело видеть.
SAME = {"applied": False, "source_hash": main._text_hash(OLD_T),
        "reason": "балл back-check упал 63 → 37",
        "before": {"score": 63, "terms": 1, "gloss": 0},
        "after": {"score": 37, "terms": 1, "gloss": 0}}
GREW = dict(SAME, reason="балл back-check упал 63 → 37",
            after={"score": 37, "terms": 3, "gloss": 0})
st4 = {"projects": [{"id": 1, "segments": [
        dict(seg_of(1, SRC, OLD_T), repair=dict(SAME)),
        dict(seg_of(2, SRC, OLD_T), repair=dict(GREW))]}],
       "glossary": [], "tm": [], "termQueue": []}
main._apply_migrations(st4)
n1, n2 = st4["projects"][0]["segments"]
check("source_hash" not in n1["repair"], "счётчик не менялся — вердикт снят")
check(n2["repair"].get("source_hash"),
      "счётчик вырос — прежний вердикт нынешним правилам не противоречит")

# (5) Пачка берёт ровно то, что показывает корзина: без открытых находок
# кандидат чинит то, чего больше нет.
noop = seg_of(9, SRC, OLD_T, repair=dict(OLDREC, candidate=NEW_T),
              bc={"score": 99, "model": "m", "back": "b", "reasons": [], "terms_lost": []},
              tc={"model": "t", "findings": []})
project_of([noop])
a2 = main.project_analysis(1)
check(a2["human"]["revertedByScore"] == [],
      "находок нет — корзина сегмент не показывает")
check(main.accept_repair_candidates(1)["matched"] == 0,
      "и пачка его не берёт: под одной строкой не может стоять двух чисел")


# ────── 6e. Заказанное сняли — правку не отменяют по счёту ──────
print()
print("=== 6e. Серьёзные замечания сверяются ПОИМЁННО ===")

# Боевой случай #2083: правка сняла заказанное «an infected animal» → «a patient»,
# а termcheck на переписанном тексте назвал две ДРУГИЕ придирки. Счёт «1 → 2»
# откатывал верную правку и клеймил сегмент навсегда.
proj, seg = build()
stub_checks(score_after=91, findings_after=[
    {"tgt_term": "tuberculous intoxication", "suggestion": "constitutional symptoms",
     "severity": "critical", "why": "чужая, уже стоявшая в тексте проблема"},
    {"tgt_term": "Mantoux reaction tests", "suggestion": "Mantoux tests",
     "severity": "major", "why": "и вторая такая же"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True,
      "заказанное снято — правку приняли, хотя серьёзных замечаний стало больше")
check(seg["target"] == NEW_T, "исправленный текст на месте")
check(any("заказанные сняты" in n for n in (seg["repair"].get("notes") or [])),
      "и решение записано: по чему судили")

# А если заказанное НЕ снято — откат, как и прежде.
proj, seg = build()
stub_checks(score_after=91, findings_after=[dict(FIND),
    {"tgt_term": "other", "suggestion": "another", "severity": "major", "why": "ещё"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "заказанное осталось — правку отвергли")
check("ни одно из заказанных" in (seg["repair"].get("reason") or ""),
      "и причина названа по существу, а не счётом")

# Замечание на СВОЁМ, подставленном слове откатывает всегда: за то, что
# вписали мы, отвечаем мы целиком.
proj, seg = build()
seg["termContext"] = {"version": main.TERM_CONTEXT_VERSION,
                      "target_hash": main._text_hash(OLD_T.strip()),
                      "terms": [{"src": "микобактерии", "tgt": "mycobacteria",
                                 "forms": ["микобактерии"], "ok": False,
                                 "use": "mycobacteria", "why": "передан неверно"}]}
stub_checks(score_after=91, findings_after=[
    {"tgt_term": "mycobacteria", "suggestion": "Mycobacterium tuberculosis",
     "severity": "major", "why": "забраковано на подставленном"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "забракован подставленный термин — откат")
check("подставленный термин" in (seg["repair"].get("reason") or ""),
      "и причина именно про него")

# Отвергнутые находки лежат в записи: иначе шум от регрессии не отличить.
check([f["tgt_term"] for f in (seg["repair"].get("afterFindings") or [])] == ["mycobacteria"],
      "находки отвергнутого текста сохранены, а не выброшены")


# ────── 6f. Совет арбитра доходит до ремонта, когда согласен с записью ──────
print()
print("=== 6f. «Передан неверно» становится работой, а не заметкой ===")
GL = [{"src": "больной", "tgt": "patient", "tier": "verified", "cat": "Term",
       "lang": "RU→EN", "domain": "medical"}]
def with_ctx(use):
    t = "Tests in an infected animal do not always indicate the absence."
    sg = {"id": 1, "source": "Пробы у больного не всегда свидетельствуют об отсутствии.",
          "target": t, "status": "translated",
          "termContext": {"version": main.TERM_CONTEXT_VERSION,
                          "target_hash": main._text_hash(t.strip()),
                          "terms": [{"src": "больной", "tgt": "patient",
                                     "forms": ["больного"], "ok": False,
                                     "use": use, "why": "подменён животным"}]}}
    return project_of([sg], GL), sg

# Совет СОГЛАСЕН с приказной записью — подстановка счётчик глоссария опустит,
# карусели нет, и ремонту это законная работа.
proj, sg = with_ctx("in a patient")
kinds = {f["kind"] for f in main._repair_findings(sg, proj)}
check("term_ctx" in kinds, "совет арбитра стал находкой ремонта")
f = next(f for f in main._repair_findings(sg, proj) if f["kind"] == "term_ctx")
check(f.get("use") == "in a patient", "и готовый вариант едет вместе с ней")

# Совет ПРОТИВОРЕЧИТ записи — это спор про запись, машина его не решает.
proj, sg = with_ctx("in a sick individual")
check("term_ctx" not in {f["kind"] for f in main._repair_findings(sg, proj)},
      "совет против приказной записи ремонту не отдаётся: подстановка "
      "подняла бы счётчик нарушенных терминов и правка откатилась бы")

# «Передан верно» работой не становится и претензию снимает (как и прежде).
proj, sg = with_ctx("in a patient")
sg["termContext"]["terms"][0]["ok"] = True
check("term_ctx" not in {f["kind"] for f in main._repair_findings(sg, proj)},
      "«передан верно» поводом для правки не бывает")


# ────── 6g. Ремонт обязан ЗАМЕНЯТЬ термин, а не дописывать его рядом ──────
print()
print("=== 6g. Дописанный термин — это повтор, и он откатывает ===")
check(main._dup_count("Check bone defects, areas of increased bone density, "
                      "areas of increased bone density, signs of rickets.") == 3,
      "повтор трёхсловных сочетаний считается")
check(main._dup_count("The test result is assessed after 72 hours.") == 0,
      "у обычного текста повторов нет")
check(main._dup_count("") == 0 and main._dup_count("два слова") == 0,
      "короткий текст не ломает счётчик")

# Боевой случай #813: ремонту сказали «термин потерян», он дописал соседний
# кусок ещё раз. Не видит этого никто: back-check считает долю слов ОРИГИНАЛА
# в обратном переводе и от лишних слов только растёт.
DUPED = ("Check osseous tissues for fractures, bone defects, areas of increased "
         "bone density, areas of increased bone density, signs of rickets.")
proj, seg = build()
main._openai_repair = lambda *a, **k: DUPED
stub_checks(score_after=99, findings_after=[])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "правка, добавившая повтор, откачена")
check("повторов в тексте стало больше" in (seg["repair"].get("reason") or ""),
      "и причина названа прямо: термин дописан вместо замены")
check(seg["target"] == OLD_T, "текст вернули")
main._openai_repair = lambda *a, **k: NEW_T

# Сверка бесплатная и БЕЗУСЛОВНАЯ: работает и там, где чинили не из-за терминов.
proj, seg = build()
main._openai_repair = lambda *a, **k: DUPED
stub_checks(score_after=99, findings_after=[])
check(main._run_segment_repair(seg, proj).get("applied") is False,
      "проверка не зависит от того, ради чего заходили — она ничего не стоит")
main._openai_repair = lambda *a, **k: NEW_T


# ────── 6h. Текст, повторяющий сам себя, — находка ремонта ──────
print()
print("=== 6h. Самоповтор: балл 100, termcheck молчит, дефект налицо ===")
d = lambda src, tgt: [f["text"] for f in main._dup_misses({"source": src, "target": tgt})]
check(len(d("4. Инфильтративный туберкулёз лёгких",
            "4. Infiltrative pulmonary tuberculosis Infiltrative pulmonary tuberculosis")) == 1,
      "подряд идущий повтор из трёх слов найден")
check(len(d("Распространённость (болезненность)", "Prevalence (prevalence)")) == 1,
      "слово, поясняющее само себя, найдено — два разных термина схлопнулись в одно")
check(d("ТБ (туберкулёз)", "TB (tuberculosis)") == [],
      "законная расшифровка находкой не считается: в скобке ДРУГОЕ слово")
# Дыра ровно в один шаг: скобку ловило одно слово, повтор подряд — от трёх.
# Двусловное между ними не ловилось ничем и уходило в готовый перевод.
check(len(d("...характерно для болезни Илза.",
            "... is characteristic of Eales disease (Eales disease).")) == 1,
      "двусловный самоповтор в скобке найден — между двумя правилами была дыра")
check(len(d("Туберкулёз органов дыхания",
            "Respiratory tuberculosis (respiratory tuberculosis)")) == 1,
      "регистр повтору не помеха")
check(d("Микобактерия туберкулёза (M. tuberculosis)",
        "Mycobacterium tuberculosis (M. tuberculosis)") == [],
      "сокращённая форма в скобке — не самоповтор")
# Авторский повтор ПОДРЯД гасит свою находку, но не скобку: улики разные.
check(len(d("Сторона А и Сторона Б, Сторона А и Сторона Б",
            "Prevalence (prevalence)")) == 1,
      "повтор в оригинале гасит только свою находку, скобку — не гасит")
check(d("Распространённость (распространённость)", "Prevalence (prevalence)") == [],
      "скобку гасит такая же скобка в оригинале — так написал автор")
check(d("Обычный текст", "A normal sentence about the number of patients here") == [],
      "обычный текст чист")
check(d("x", "") == [] and d("x", "one two") == [],
      "пустой и короткий текст счётчик не ломают")

# Находка идёт тем же путём, что регистр и чужое письмо: бесплатно, в ремонт.
seg_dup = seg_of(1, SRC, "Infiltrative pulmonary tuberculosis Infiltrative pulmonary tuberculosis")
proj = project_of([seg_dup])
kinds = {f["kind"] for f in main._repair_findings(seg_dup, proj)}
check("dup" in kinds, "повтор стал поводом для ремонта")


# ────── 6i. Объективная находка сильнее заверения человеком ──────
print()
print("=== 6i. Заверение снимается только неоспоримым — и громко ===")
HARDBC = {"score": 40, "model": "m", "back": "иначе", "terms_lost": [],
          "reasons": ["расхождение чисел"]}
SOFTBC = {"score": 40, "model": "m", "back": "иначе", "terms_lost": [],
          "reasons": ["часть текста не совпала дословно", "обратный перевод про другое"]}

hard = seg_of(1, "Доза 5 мг в сутки.", "Dose 15 mg per day.", bc=HARDBC,
              tc={"model": "t", "findings": [dict(FIND)]})
hard["status"] = "confirmed"; hard["confirmedBy"] = "human"; hard["confirmedAt"] = "2026-08-01 10:00"
soft = seg_of(2, SRC, OLD_T, bc=SOFTBC, tc={"model": "t", "findings": [dict(FIND)]})
soft["status"] = "confirmed"; soft["confirmedBy"] = "human"
proj = project_of([hard, soft])

check(main._confirm_override(hard) == ["расхождение чисел"],
      "расхождение чисел — доказательство, которое сильнее заверения")
check(main._confirm_override(soft) == [],
      "«про другое» и «не совпало дословно» заверение НЕ отменяют: "
      "на коротком сегменте косинус врёт")

# Нарушенный приказный термин заверение тоже НЕ отменяет: посылка «запись
# верна» недоказана, а редактор, исправивший кальку руками, иначе получил бы
# бесконечную борьбу с глоссарием.
GL2 = [{"src": "доза", "tgt": "dosage", "tier": "verified", "cat": "Term",
        "lang": "RU→EN", "domain": "medical"}]
gl_seg = seg_of(3, "Доза препарата.", "Drug dose.", bc=SOFTBC, tc={"model": "t", "findings": []})
gl_seg["status"] = "confirmed"; gl_seg["confirmedBy"] = "human"
proj2 = project_of([gl_seg], GL2)
check(any(f["kind"] == "gloss" for f in main._repair_findings(gl_seg, proj2)),
      "нарушение приказного термина находкой остаётся")
check(main._confirm_override(gl_seg) == [],
      "но заверение оно не снимает — это спор про ЗАПИСЬ, а не про строку")

# Заверение снимается со следом: что нашли, кто заверял, какой текст был.
proj = project_of([hard])
stub_checks(score_after=95, findings_after=[])
main._openai_repair = lambda *a, **k: "Dose 5 mg per day."
r = main._run_segment_repair(hard, proj)
check(r.get("applied") is True, "правка принята")
cw = hard.get("confirmWithdrawn") or {}
check(cw.get("evidence") == ["расхождение чисел"], "доказательство записано на сегмент")
check(cw.get("by") == "human" and cw.get("at") == "2026-08-01 10:00",
      "кто и когда заверял — сохранено")
check(cw.get("was") == "Dose 15 mg per day.", "заверенный текст сохранён целиком")
check(hard.get("status") == "review" and "confirmedBy" not in hard,
      "отметка снята, сегмент ждёт человека")
a = main.project_analysis(1)
check(a["human"]["confirmWithdrawn"] == [1],
      "и своя строка на экране: молча снятое заверение недопустимо")
main._openai_repair = lambda *a, **k: NEW_T


# ────── 6j. Второй заход разрешён, когда он ДРУГОЙ ──────
print()
print("=== 6j. Отпечаток захода: повтор без перерасхода ===")
proj, seg = build()
k1 = main._repair_attempt_key(seg)
check(bool(k1), "отпечаток считается")
check(main._repair_attempt_key(seg) == k1, "и он устойчив: те же данные — тот же ключ")

# Записали заход — повтор запрещён.
seg["repair"] = {"applied": False, "reason": "балл back-check упал 57 → 8",
                 "attemptKey": k1, "issues": ["x"]}
check(main._repair_tried(seg) is True, "тот же текст, те же находки, те же правила — не пускаем")

# Появилась НОВАЯ находка — заход другой, и запрещать его незачем.
seg["termcheck"]["findings"].append(
    {"tgt_term": "mycobacteria", "suggestion": "Mycobacterium tuberculosis",
     "severity": "major", "why": "новая находка"})
check(main._repair_tried(seg) is False,
      "список претензий изменился — промпт будет другим, заход осмыслен")

# Изменились ПРАВИЛА — прежний вердикт их не описывает.
seg["termcheck"]["findings"].pop()
check(main._repair_tried(seg) is True, "вернули как было — снова не пускаем")
_was = main.REPAIR_RULES_VERSION
try:
    main.REPAIR_RULES_VERSION = _was + "-next"
    check(main._repair_tried(seg) is False,
          "правила отмены изменились — вердикт по ним больше не держит сегмент")
finally:
    main.REPAIR_RULES_VERSION = _was

# Записи прежних версий отпечатка не имеют — работает старое сравнение.
seg["repair"] = {"applied": False, "reason": "x", "source_hash": main._text_hash(OLD_T)}
check(main._repair_tried(seg) is True,
      "«этот текст проходил через ремонт» — да, и это по-прежнему видно")
# А вот ЗАКРЫВАТЬ по такому вердикту нельзя: правила с тех пор менялись
# не раз, и вердикт по ним больше ничего не описывает. На боевом проекте
# так стояли 79 сегментов с находками при пустом составе ремонта.
check(main._repair_clamped(seg) is False,
      "но не пускать по вердикту прежних правил — значит отказывать "
      "в починке по решению, которого больше нет")
check(main._repairable(seg, False, proj) is True, "сегмент доступен ремонту")
seg["repair"]["attemptKey"] = main._repair_attempt_key(seg)
check(main._repair_clamped(seg) is True,
      "а с отпечатком нынешних правил — закрыт, как и должно быть")


# ────── 6k. Проверка смотрит ДАЛЬШЕ своего сегмента ──────
print()
print("=== 6k. Разнобой по документу ===")
hh = lambda t: main._text_hash((t or "").strip())
flagged = {"id": 1, "source": "МБТ обнаружены.", "target": "MBT detected.",
           "status": "translated",
           "termcheck": {"model": "t", "target_hash": hh("MBT detected."),
                         "findings": [{"tgt_term": "MBT", "suggestion": "MTB",
                                       "severity": "major", "why": "транслитерация"}]}}
silent = {"id": 2, "source": "МБТ в мокроте.", "target": "MBT in sputum.",
          "status": "translated",
          "termcheck": {"model": "t", "target_hash": hh("MBT in sputum."), "findings": []}}
right = {"id": 3, "source": "МБТ выделены.", "target": "MTB isolated.",
         "status": "translated",
         "termcheck": {"model": "t", "target_hash": hh("MTB isolated."), "findings": []}}
# Порог голосов — 2: одна находка termcheck это мнение о СТРОКЕ, а не
# о документе. Здесь пару называют дважды, поэтому она проходит.
flagged2 = {"id": 4, "source": "МБТ в мазке.", "target": "MBT in smear.",
            "status": "translated",
            "termcheck": {"model": "t", "target_hash": hh("MBT in smear."),
                          "findings": [{"tgt_term": "MBT", "suggestion": "MTB",
                                        "severity": "major", "why": "транслитерация"}]}}
proj = project_of([flagged, silent, right, flagged2])
main._CONSIST_CACHE.clear()
pairs = main._consistency_of(proj)
check(len(pairs) == 1 and pairs[0]["was"] == "MBT" and pairs[0]["want"] == "MTB",
      "пара «было → надо» взята из находки termcheck, а не из зашитого списка")
check(pairs[0]["segments"] == [1, 2, 4], "найдены ВСЕ места, включая непомеченное")

# Пара, названная ОДИН раз, документом не считается: на боевых данных так
# держались «Bronchoscopy → sputum smear microscopy» (другая процедура)
# и «bacillary excretion → bacteriological conversion» (обратный смысл).
lone = {"id": 5, "source": "Бронхоскопия.", "target": "Bronchoscopy.",
        "status": "translated",
        "termcheck": {"model": "t", "target_hash": hh("Bronchoscopy."),
                      "findings": [{"tgt_term": "Bronchoscopy",
                                    "suggestion": "sputum smear microscopy",
                                    "severity": "major", "why": "одиночное мнение"}]}}
proj_l = project_of([lone])
main._CONSIST_CACHE.clear()
check(main._consistency_of(proj_l) == [],
      "один голос — мнение о строке, а не о документе; по всему тексту "
      "такое применять нельзя")
project_of([flagged, silent, right, flagged2])
main._CONSIST_CACHE.clear()
check(pairs[0]["already"] == 1, "и сказано, сколько мест уже пишут верно")

kinds = {f["kind"] for f in main._repair_findings(silent, proj)}
check("consist" in kinds,
      "сегмент, которого termcheck не касался, получил находку из другого места")
own = {f["kind"] for f in main._repair_findings(flagged, proj)}
check("consist" not in own,
      "а тому, где находка уже есть, второй раз о том же не говорим")

# Спор с приказной записью в разнобой не идёт: правка откатилась бы сама.
GLV = [{"src": "МБТ", "tgt": "MBT", "tier": "verified", "cat": "Term",
        "lang": "RU→EN", "domain": "medical"}]
proj2 = project_of([dict(flagged), dict(silent), dict(right)], GLV)
main._CONSIST_CACHE.clear()
sg = proj2["segments"][1]
check("consist" not in {f["kind"] for f in main._repair_findings(sg, proj2)},
      "вариант требует приказная запись — молчим, иначе платный вызов "
      "с заранее известным исходом")


# ────── 6l. «Никто не проверял» — своя корзина ──────
print()
print("=== 6l. Не «плохо», а «никто не смотрел» ===")
# Длинный оригинал: балл измерим, он высок, и судья туда не ходит по правилу
# зоны. Ровно там и живёт «беглое неверное слово».
clean_hi = seg_of(1, "Полное рассасывание бугорка наблюдается у части больных.",
                  "Complete resorption of the cusps is observed in some patients.",
                  bc={"score": 100, "model": "m", "back": "b", "reasons": [],
                      "terms_lost": [], "judged": False},
                  tc={"model": "t", "findings": []})
blind = seg_of(2, "Моноустойчивый,", "monostable,",
               bc={"score": 0, "model": "m", "back": "b", "reasons": [],
                   "terms_lost": [], "judged": False},
               tc={"model": "t", "findings": []})
project_of([clean_hi, blind])
main._CONSIST_CACHE.clear()
a = main.project_analysis(1)
check(a["todo"]["unverified"] == [1],
      "балл выше зоны судьи и никто не смотрел — тут и прячется «беглое слово»")
check(a["todo"]["unjudgedBlind"] == [2],
      "балл не измерить и судья не смотрел — своя причина, а не «оценка ниже порога»")
# Пересечение с «проверено начисто» НАМЕРЕННОЕ: та корзина отвечает на вопрос
# «можно ли этим учить глоссарий», а эта — «читал ли кто-нибудь смысл».
# Вопросы разные, и сегмент законно попадает в обе (тот же случай, что
# у соответствия глоссарию: «начисто» не означает «глоссарий соблюдён»).
check(1 in a["clean"],
      "«начисто» отвечает на другой вопрос — пересечение здесь законно")


# ────── 6m. Три причины отката, которые были нашими, а не модели ──────
print()
print("=== 6m. Регистр, спор с записью и частичный успех ===")

# A. Модель дала верный термин не в том начертании. Правим сами, бесплатно.
check(main._case_fit("ИНСТРУМЕНТАЛЬНЫЕ ИССЛЕДОВАНИЯ", "Diagnostic investigations")
      == "DIAGNOSTIC INVESTIGATIONS",
      "КАПС заголовка оригинала переносится на перевод")
check(main._case_fit("Прямые лучи убивают.", "direct sunlight kills.")
      == "Direct sunlight kills.", "заглавная в начале поднимается")
check(main._case_fit("прямые лучи", "Direct sunlight") == "Direct sunlight",
      "опускать регистр нельзя: в переводе заглавная бывает законной")
check(main._case_fit("Обычный текст", "Normal text") == "Normal text",
      "там, где всё сходится, ничего не трогаем")

CAPS = "ИНСТРУМЕНТАЛЬНЫЕ ИССЛЕДОВАНИЯ"
seg_c = seg_of(1, CAPS, "INSTRUMENTAL INVESTIGATIONS",
               bc={"score": 100, "model": "m", "back": "b", "reasons": [],
                   "terms_lost": []},
               tc={"model": "t", "findings": [
                   {"tgt_term": "INSTRUMENTAL INVESTIGATIONS",
                    "suggestion": "Diagnostic investigations",
                    "severity": "major", "why": "калька"}]})
proj = project_of([seg_c])
main._openai_repair = lambda *a, **k: "Diagnostic investigations"
stub_checks(score_after=100, findings_after=[])
r = main._run_segment_repair(seg_c, proj)
check(r.get("applied") is True,
      "правка принята: начертание поправили сами, а не откатили весь заход")
check(seg_c["target"] == "DIAGNOSTIC INVESTIGATIONS",
      "и в сегменте стоит верный термин в верном регистре")
main._openai_repair = lambda *a, **k: NEW_T

# A2. Заход ТОЛЬКО по самоповтору меряется самой находкой, а не триграммами.
# Боевой #128: «Распространённость (болезненность)» → «Prevalence (prevalence)»,
# правка «Prevalence (morbidity)» откатывалась с «0 → 0» — триграмм в двух
# словах нет, а находка скобки в меру не входила.
seg_d = seg_of(3, "Распространённость (болезненность)", "Prevalence (prevalence)",
               bc={"score": 100, "model": "m", "back": "b", "reasons": [], "terms_lost": []},
               tc={"model": "t", "findings": []})
proj = project_of([seg_d])
check([f["kind"] for f in main._repair_findings(seg_d, proj)] == ["dup"],
      "единственная находка — самоповтор в скобке")
main._openai_repair = lambda *a, **k: "Prevalence (morbidity)"
stub_checks(score_after=100, findings_after=[])
r = main._run_segment_repair(seg_d, proj)
check(r.get("applied") is True and seg_d["target"] == "Prevalence (morbidity)",
      "правка, снявшая самоповтор, принята — заход мерился находкой, а не триграммами")
main._openai_repair = lambda *a, **k: NEW_T

# B. Находка ПРОТИВ приказной записи ремонту не отдаётся: исход известен.
GLB = [{"src": "бактериовыделитель", "tgt": "bacillary excretor", "tier": "verified",
        "cat": "Term", "lang": "RU→EN", "domain": "medical"}]
seg_v = seg_of(2, "Контакт с больным бактериовыделителем.",
               "Contact with a patient who is a bacillary excretor.",
               tc={"model": "t", "findings": [
                   {"tgt_term": "bacillary excretor", "suggestion": "bacterial shedder",
                    "severity": "major", "why": "калька"}]})
proj_v = project_of([seg_v], GLB)
main._note_term_disputes(seg_v, proj_v)
check(seg_v["termcheck"]["findings"][0].get("vsVerified") is True,
      "находка помечена как спор с приказной записью — при обнаружении, "
      "где проект есть")
check("term" not in {f["kind"] for f in main._repair_findings(seg_v, proj_v)},
      "ремонту она не отдаётся: подстановка подняла бы счётчик нарушенных "
      "терминов и правка откатилась бы сама")
check("term" not in {f["kind"] for f in main._repair_findings(seg_v, None)},
      "и БЕЗ проекта тоже — метка на находке, а не в расчёте: иначе смета "
      "обещала бы одно, а прогон делал другое")

# C. Сняли одно заказанное из двух — это движение вперёд, а не провал.
seg_p = seg_of(3, "Асцитическая жидкость и определение теста.",
               "ascites and determination of the test.",
               bc={"score": 60, "model": "m", "back": "b", "reasons": [],
                   "terms_lost": []},
               tc={"model": "t", "findings": [
                   {"tgt_term": "ascites", "suggestion": "ascitic fluid",
                    "severity": "major", "why": "это состояние, а не жидкость"},
                   {"tgt_term": "determination of the test",
                    "suggestion": "drug susceptibility testing",
                    "severity": "minor", "why": "принято иначе"}]})
proj_p = project_of([seg_p])
main._openai_repair = lambda *a, **k: "ascites and drug susceptibility testing."
stub_checks(score_after=60, findings_after=[
    {"tgt_term": "ascites", "suggestion": "ascitic fluid", "severity": "major",
     "why": "осталось"},
    {"tgt_term": "and", "suggestion": "plus", "severity": "major", "why": "новая придирка"}])
r = main._run_segment_repair(seg_p, proj_p)
check(r.get("applied") is True,
      "одно из двух заказанных снято — правку приняли, оплаченную работу "
      "не выбрасываем")
check("drug susceptibility testing" in seg_p["target"], "снятое замечание исправлено")
main._openai_repair = lambda *a, **k: NEW_T


# ────── 6n. Балл не держится на претензии, снятой арбитром ──────
print()
print("=== 6n. Оплаченный вердикт арбитра доходит до балла ===")
GLX = [{"src": "туберкулёз органов дыхания", "tgt": "respiratory tuberculosis",
        "tier": "verified", "cat": "Disease", "lang": "RU→EN", "domain": "medical"}]
sx = seg_of(1, "Туберкулёз органов дыхания", "Respiratory tuberculosis")
sx["termContext"] = {"version": main.TERM_CONTEXT_VERSION,
                     "target_hash": main._text_hash("Respiratory tuberculosis"),
                     "terms": [{"src": "туберкулёз органов дыхания",
                                "tgt": "respiratory tuberculosis",
                                "forms": ["Туберкулёз органов дыхания"],
                                "ok": True, "use": "", "why": ""}]}
projx = project_of([sx], GLX)
hits = main._verified_hits(sx["source"], projx)
check(len(hits) == 1, "требование глоссария к сегменту есть")
check(main._hits_for_score(sx, hits) == [],
      "но в БАЛЛ оно не идёт: арбитр уже сказал «передан верно», "
      "и наказывать за потерю значит спорить с собственным вердиктом")
check(main._arbiter_settled(sx), "снятые термины собраны из свежего вердикта")

# Устаревший вердикт не снимает ничего: он описывает другой текст.
sx["termContext"]["target_hash"] = main._text_hash("другой текст")
check(main._hits_for_score(sx, hits) == hits,
      "устаревший вердикт претензию не снимает")
# «Передан неверно» тоже не снимает.
sx["termContext"]["target_hash"] = main._text_hash("Respiratory tuberculosis")
sx["termContext"]["terms"][0]["ok"] = False
check(main._hits_for_score(sx, hits) == hits, "«передан неверно» не снимает претензию")


# ────── 6o. «Нечего проверять» — не «не проверено» ──────
print()
print("=== 6o. Корзина, из которой нельзя выйти, не должна звать к работе ===")
num = seg_of(1, "40%", "40%",
             bc={"score": 100, "model": "m", "back": "40%", "reasons": [], "terms_lost": []},
             tc={"model": "skip", "findings": []})
project_of([num])
main._CONSIST_CACHE.clear()
a = main.project_analysis(1)
check(a["todo"]["nothingToCheck"] == [1],
      "«40%» — проверять нечего, и это своя причина")
check(1 not in a["todo"]["unchecked"],
      "в «не проверено» его больше нет: оттуда он не ушёл бы никогда")
check("readyIds" in a, "готовность считается без двойного счёта на сервере")


# ────── 6p. Забракованное слово осталось в тексте ──────
print()
print("=== 6p. Очередь помнит, а сегмент забыл ===")
bad = seg_of(1, "Исследуют биоптат.", "The bioptate is examined.",
             bc={"score": 100, "model": "m", "back": "b", "reasons": [], "terms_lost": []},
             tc={"model": "t", "findings": []})
good = seg_of(2, "Исследуют мокроту.", "The sputum is examined.",
              bc={"score": 100, "model": "m", "back": "b", "reasons": [], "terms_lost": []},
              tc={"model": "t", "findings": []})
project_of([bad, good])
main.STATE["termQueue"] = [
    {"id": "c1", "kind": "audit", "status": "pending", "src": "биоптат",
     "wasTgt": "bioptate", "project": 1, "segment": 1},
    {"id": "c2", "kind": "audit", "status": "pending", "src": "мокрота",
     "wasTgt": "expectorate", "project": 1, "segment": 2}]
main._CONSIST_CACHE.clear()
a = main.project_analysis(1)
check(a["human"]["staleFindings"] == [1],
      "слово, которое termcheck забраковал, всё ещё в тексте — своя строка")
check(2 not in a["human"]["staleFindings"],
      "а там, где его убрали, претензии нет")
check(any(w["id"] == 1 and "bioptate" in w["words"]
          for w in a["human"]["staleFindingWords"]),
      "и слово названо — иначе претензию нечем исполнить")
check("term" not in {f["kind"] for f in main._repair_findings(bad, None)},
      "ремонту это НЕ отдаётся: одно суждение о строке не приказ переписывать, "
      "тем более что проверка себе противоречит")


# ────── 6q. Очередь не копит то, что политика отвергнет всегда ──────
print()
print("=== 6q. Неодобряемое не заводится ===")
main.STATE["termQueue"] = []
long_src = "Искусственное лечение пневмоторакса закрыто совсем"
c = main._queue_term("audit", long_src, "closed artificial pneumothorax",
                     project=1, segment=1, domain="medical", lang="RU→EN")
check(c is None, "термин длиннее лимита политики в очередь не идёт")
c2 = main._queue_term("audit", "биоптат", "biopsy specimen",
                      project=1, segment=1, domain="medical", lang="RU→EN")
check(c2 is not None, "нормальный кандидат заводится как раньше")
c3 = main._queue_term("audit", "Это предложение, а не термин.", "A sentence.",
                      project=1, segment=1, domain="medical", lang="RU→EN")
check(c3 is None, "предложение с точкой на конце — тоже нет")


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

# ─────────── 8. Принятая правка выходит из прогона со СВЕЖИМИ проверками ───────────
# Ремонт — последний платный шаг, back-check идёт до него: правка по терминам
# (had_tc без had_bc) оставляла back-check от прежнего текста, сегмент тут же
# возвращался в «переведено, но не проверено», и следующий прогон покупал
# обратный перевод заново. После каждого прогона оставался хвост.
print("\n=== 8. Освежение недостающей проверки после принятой правки ===")

# Заход ТОЛЬКО по termcheck: bc без претензий (had_bc False).
def build_term_only():
    s = seg_of(1, SRC, OLD_T,
               bc={"score": 95, "model": "gpt-5.6-luna", "back": OLD_T,
                   "reasons": [], "terms_lost": [], "judged": False},
               tc={"model": "gpt-5.6-terra", "findings": [dict(FIND)]})
    return project_of([s]), s

proj, seg = build_term_only()
check({f["kind"] for f in main._repair_findings(seg, proj)} == {"term"},
      "заход только по termcheck — back-check перепроверять было не за что")
bc_calls = []
stub_checks(score_after=95, findings_after=[], seen=bc_calls)
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True, "правка принята")
check(seg["backcheck"]["target_hash"] == main._text_hash(NEW_T),
      "back-check освежён под НОВЫЙ текст — сегмент не вернётся в «не проверено»")
check(len(bc_calls) == 1, "и это ровно один вызов, а не перепроверка на каждый чих")
check(main._repair_tried(seg) is True,
      "attemptKey посчитан ПОСЛЕ освежения — свежие проверки в отпечатке")

# Откат (замечаний стало больше): платить за выброшенного кандидата незачем.
proj, seg = build_term_only()
bc_calls = []
stub_checks(score_after=95, seen=bc_calls,
            findings_after=[dict(FIND),
                            dict(FIND, tgt_term="second", suggestion="other")])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "правка откачена — замечаний стало больше")
check(len(bc_calls) == 0,
      "back-check у откачённой правки НЕ покупается: прежняя запись верна")
check(seg["backcheck"]["target_hash"] == main._text_hash(OLD_T),
      "и относится к восстановленному тексту")

# Зеркальный случай: заход только по back-check (term_lost) — освежается termcheck.
proj, seg = build(findings=())
check({f["kind"] for f in main._repair_findings(seg, proj)} == {"term_lost"},
      "заход только по back-check")
stub_checks(score_after=95, findings_after=[])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True, "правка принята")
check(seg["termcheck"]["target_hash"] == main._text_hash(NEW_T),
      "termcheck освежён под новый текст")

print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
