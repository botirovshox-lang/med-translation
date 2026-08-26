"""Ранг модели, разбор прогона и место Medical QA в конвейере.

Проверяется то, из-за чего человек платил дважды и получал качество хуже:
  1. вердикт сильной модели не перезаписывается слабой;
  2. смена модели back-check не гонит проект заново;
  3. Medical QA заказывает обратный перевод моделью back-check, а не той,
     что стоит переводчиком по умолчанию;
  4. Medical QA не понижает статус review, поставленный ремонтом;
  5. разбор прогона (run-plan) обещает ровно ту работу, которую прогон сделает.

Ни одного платного вызова: и перевод, и termcheck подменены.
"""
import os, sys, json
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


def seg(sid, source, target="", status="translated"):
    return {"id": sid, "source": source, "target": target, "status": status, "risk": "medium"}


def build(segments):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


def tc_done(sg, model, findings=()):
    """Как будто termcheck этой моделью уже отработал по нынешнему тексту."""
    sg["termcheck"] = {"findings": list(findings), "severity": "none", "model": model,
                       "target_hash": main._text_hash(sg["target"].strip()),
                       "at": "2026-08-01 10:00"}


def bc_done(sg, model, score=95):
    sg["backcheck"] = {"score": score, "band": "green", "model": model, "back": sg["source"],
                       "reasons": [], "terms_lost": [], "judged": False, "judge_skipped": "zone",
                       "target_hash": main._text_hash(sg["target"].strip()),
                       "at": "2026-08-01 10:00"}


# ─────────────── 1. Ранг: слабая не перезаписывает сильную ───────────────
print("=== 1. Проверка терминов: вердикт сильной модели слабой не переписывается ===")
check(main.model_rank("gpt-5.6-sol") > main.model_rank("gpt-5.6-terra"),
      "справочник читается: Sol сильнее Terra")

proj = build([seg(1, "жалобы", "complaints")])
s1 = proj["segments"][0]
tc_done(s1, "gpt-5.6-sol")
check(main._termcheck_cached(s1, "gpt-5.6-terra"),
      "Sol-вердикт признан действительным для запроса Terra — перепроверки не будет")
check(main._termcheck_cached(s1, "gpt-5.6-luna"), "и для Luna тоже")
check(main._termcheck_cached(s1, "gpt-5.6-sol"), "и для самой Sol")

tc_done(s1, "gpt-5.6-terra")
check(not main._termcheck_cached(s1, "gpt-5.6-sol"),
      "а вот Terra-вердикт запросу Sol не годится — усилить проверку можно всегда")
check(main._termcheck_cached(s1, "gpt-5.6-terra"), "той же моделью — годится")

tc_done(s1, "gpt-3.5-turbo-legacy")
check(not main._termcheck_cached(s1, "gpt-5.6-luna"),
      "модель неизвестной силы действительной не считается — проверим заново")

tc_done(s1, "gpt-5.6-sol")
s1["target"] = "complaints CHANGED"
check(not main._termcheck_cached(s1, "gpt-5.6-luna"),
      "изменившийся перевод отменяет любой ранг")

# ─────────────── 2. Справочник живёт файлом ───────────────
print("\n=== 2. Справочник рангов правится без деплоя ===")
override = main.MODEL_RANK_FILES[1]
try:
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text(json.dumps({"ranks": {"gpt-3.5-turbo-legacy": 9}}), encoding="utf-8")
    main._MODEL_RANKS_STAMP = ()          # как будто процесс живёт дальше, а файл поменялся
    check(main.model_rank("gpt-3.5-turbo-legacy") == 9,
          "копия в data/ подхвачена и сильнее репозиторной")
    s2 = build([seg(1, "жалобы", "complaints")])["segments"][0]
    tc_done(s2, "gpt-3.5-turbo-legacy")
    check(main._termcheck_cached(s2, "gpt-5.6-sol"),
          "дописали ранг — перепроверка отменилась, кода не трогали")
finally:
    override.unlink()
    main._MODEL_RANKS_STAMP = ()
check(main.model_rank("gpt-3.5-turbo-legacy") is None, "справочник вернулся к репозиторному")

# ─────────────── 3. Back-check: ранга нет, но и повторов нет ───────────────
print("\n=== 3. Back-check: смена модели не гонит проект заново ===")
proj = build([seg(1, "жалобы", "complaints")])
s3 = proj["segments"][0]
bc_done(s3, "gpt-5.6-luna")
check(main._backcheck_cached(s3, "gpt-4o-mini", False),
      "свежий обратный перевод годится любой моделью: сильная здесь не лучше, а хуже")
s3["target"] = "other"
check(not main._backcheck_cached(s3, "gpt-5.6-luna", False),
      "но изменившийся перевод по-прежнему отменяет проверку")

proj = build([seg(1, "жалобы", "complaints")])
s3b = proj["segments"][0]
s3b["provider"] = "gpt-5.6-luna"          # этой же моделью текст и переведён
bc_done(s3b, "gpt-5.6-luna")
check(not main._backcheck_cached(s3b, "gpt-5.6-luna", False),
      "проверка своей же работой не кэшируется: раз модель больше не сравнивается, "
      "этот случай надо назвать явно")
plan = main.run_plan(1, main.RunPlanRequest(steps=["backcheck"], bc_model="gpt-5.6-luna"))
check(any("кто переводил" in r["reason"] for r in plan["steps"][0]["runs"]),
      "и в разборе прогона причина названа человеку")
s3b["provider"] = "gpt-5.5"
check(main._backcheck_cached(s3b, "gpt-5.6-luna", False),
      "а переведённый другой моделью — по-прежнему проверен")

# ─────────────── 4. Medical QA берёт модель back-check ───────────────
print("\n=== 4. Обратный перевод для Medical QA — моделью back-check ===")
seen = []
main._openai_translate = lambda text, s, t, **k: (seen.append(k.get("model")), "RU: " + text)[1]
build([seg(1, "жалобы", "complaints")])
main.batch_medical_qa(1, main.MedicalQABatchRequest(bc_model="gpt-5.6-luna"))
check(seen == ["gpt-5.6-luna"], "заказан моделью back-check, а не переводчиком по умолчанию")
seen.clear()
build([seg(1, "жалобы", "complaints")])
main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(seen == [main.BACKCHECK_DEFAULT_MODEL],
      "без явной модели — дефолт back-check, а не DEFAULT_OPENAI_MODEL")
check(main.DEFAULT_OPENAI_MODEL not in seen, "модель перевода к этому вызову отношения не имеет")

print("\n=== 5. Готовый обратный перевод из back-check по-прежнему не оплачивается ===")
seen.clear()
proj = build([seg(1, "жалобы", "complaints")])
bc_done(proj["segments"][0], "gpt-5.6-luna")
main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(seen == [], "вызова не было — обратный перевод взят у back-check")

# ─────────────── 6. Статус review не понижается ───────────────
print("\n=== 6. Medical QA не разжалует сегмент, который переписала машина ===")
proj = build([seg(1, "жалобы", "complaints", status="review")])
main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(proj["segments"][0]["status"] == "review",
      "review остался review: «машина переписала текст, посмотри» чистой QA не отменяется")
proj = build([seg(1, "жалобы", "complaints", status="translated")])
main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(proj["segments"][0]["status"] in ("qa", "review"),
      "translated по-прежнему получает статус проверки")
proj = build([seg(1, "жалобы", "complaints", status="confirmed")])
main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(proj["segments"][0]["status"] == "confirmed", "подтверждённый по-прежнему неприкосновенен")

# ─────────────── 7. Порядок шагов ───────────────
print("\n=== 7. Medical QA идёт ПОСЛЕ ремонта ===")
check(main.FULL_RUN_STEPS.index("medical_qa") > main.FULL_RUN_STEPS.index("repair"),
      "иначе она описывает текст, который через шаг перепишут, и устаревает сразу")
check(main.FULL_RUN_STEPS.index("backcheck") < main.FULL_RUN_STEPS.index("termcheck")
      < main.FULL_RUN_STEPS.index("repair"),
      "ремонт по-прежнему после обеих проверок — он чинит по их находкам")

# ─────────────── 8. Разбор обещает ровно то, что прогон сделает ───────────────
print("\n=== 8. Разбор прогона совпадает с работой прогона ===")
main._openai_termcheck = lambda src, tgt, sl, tl, dom, mdl: {"findings": [], "model": mdl or "gpt-5.6-terra"}
proj = build([seg(1, "жалобы", "complaints"),          # ещё не проверялся
              seg(2, "одышка", "dyspnea"),             # проверен Sol — сильнее
              seg(3, "кашель", "cough"),               # проверен Luna — слабее
              seg(4, "боль", "pain"),                  # проверен Terra — та же
              seg(5, "1500", "1500"),                  # нечего проверять
              seg(6, "новый текст", "", status="new")])  # переводится в этом же прогоне
tc_done(proj["segments"][1], "gpt-5.6-sol")
tc_done(proj["segments"][2], "gpt-5.6-luna")
tc_done(proj["segments"][3], "gpt-5.6-terra")
proj["segments"][4]["termcheck"] = {"findings": [], "severity": "none", "model": "skip",
                                    "target_hash": main._text_hash("1500"), "at": "2026-08-01 10:00"}

plan = main.run_plan(1, main.RunPlanRequest(steps=["translate", "termcheck"],
                                            tc_model="gpt-5.6-terra"))
tc = next(p for p in plan["steps"] if p["step"] == "termcheck")
check(sorted(tc["ids"]) == [1, 3, 6],
      "в работу: непроверенный, проверенный более слабой и тот, что переведут (%s)" % tc["ids"])
skips = {r["reason"] for r in tc["skips"]}
check(any("не слабее" in r for r in skips), "Sol назван причиной пропуска, а не молча выкинут")
check(any("этой моделью" in r for r in skips), "и повтор той же моделью назван")
check(any("нет слов" in r for r in skips), "и «нечего проверять» назван")
check(sum(r["count"] for r in tc["skips"]) == 3, "пропущено ровно 3 сегмента")
runs = {r["reason"] for r in tc["runs"]}
check(any("слабее выбранной" in r for r in runs), "и причина взять в работу тоже названа")

# ...а теперь то же самое, но по-настоящему
proj["segments"][5]["target"] = "new-en"              # как будто перевод отработал
proj["segments"][5]["status"] = "translated"
res = main.termcheck_batch(1, main.TermcheckBatchRequest(
    segment_ids=tc["ids"], limit=100, model="gpt-5.6-terra", skip_cached=True))
check(res["count"] == tc["count"],
      "прогон обработал столько же, сколько обещал разбор: %s против %s" % (res["count"], tc["count"]))
check(res.get("skipped_cached", 0) == 0,
      "и ни одного лишнего сегмента ему не прислали — отбор один на смету и на работу")

print("\n=== 9. Разбор ничего не меняет ===")
before = json.dumps(proj["segments"], sort_keys=True, ensure_ascii=False)
main.run_plan(1, main.RunPlanRequest())
check(json.dumps(proj["segments"], sort_keys=True, ensure_ascii=False) == before,
      "run-plan — чтение, а не работа")

# ─────────── 10. Ремонт: разбор считает глоссарий так же, как прогон ───────────
print("\n=== 10. Ремонт в разборе и в прогоне отбирает одно и то же ===")
# Разбор берёт расхождения с глоссарием из общего отчёта о соответствии
# (13 мс на сегмент превращали проект на 2670 строк в 34 секунды разбора),
# прогон — из _gloss_misses. Разойдись они — карточка снова начнёт врать.
GLOSS = [{"src": "увеит", "tgt": "uveitis", "tier": "verified", "cat": "Disease",
          "lang": "RU→EN", "domain": "medical"}]
proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
        "segments": [
            dict(seg(1, "увеит справа", "right uveal thing")),                    # термин потерян
            dict(seg(2, "увеит слева", "left uveal thing", status="confirmed")),  # то же, но заверен
            dict(seg(3, "увеит сверху", "upper uveitis")),                        # термин на месте
        ]}
main.STATE = {"projects": [proj], "glossary": [dict(g) for g in GLOSS], "tm": [],
              "termQueue": [], "exportHistory": [], "team": []}
main._invalidate_gloss_index()

plan = main.run_plan(1, main.RunPlanRequest(steps=["repair"]))
rp = plan["steps"][0]
real = [s["id"] for s in proj["segments"]
        if s.get("status") != "confirmed" and main._repairable(s, False, proj)]
check(sorted(rp["ids"]) == sorted(real),
      "разбор и полный расчёт согласны: %s против %s" % (rp["ids"], real))
check(rp["ids"] == [1], "чинится тот, где утверждённый термин потерян")
check(any("заверено" in r["reason"] for r in rp["skips"]),
      "заверенный человеком назван поимённо, а не посчитан как «нечего чинить»")

# ─────────── 11. Мелочи, на которых разбор врал бы молча ───────────
print("\n=== 11. Пустой список шагов и порядок объединения ===")
proj = build([seg(i, "текст %d" % i, "text %d" % i) for i in range(1, 8)])
check(main.run_plan(1, main.RunPlanRequest(steps=[]))["total"] == 0,
      "пустой список шагов — это «ничего не выбрано», а не «весь конвейер»")
plan = main.run_plan(1, main.RunPlanRequest(steps=["medical_qa", "termcheck"]))
check(plan["ids"] == sorted(plan["ids"]),
      "объединение идёт в порядке документа, а не в порядке шагов: "
      "порции берутся из этого списка, и прогон не должен прыгать по проекту")

# ─────────── 12. Разбивка по статусам: чем браузер ловит устаревшую копию ───────────
print("")
print("=== 12. Статусы проекта в ответе разбора ===")
proj = build([seg(1, "а", "", "new"), seg(2, "б", "b", "qa"), seg(3, "в", "c", "qa"),
              seg(4, "г", "d", "confirmed"), seg(5, "д", "e", "review")])
plan = main.run_plan(1, main.RunPlanRequest())
check(plan["projectStatus"] == {"new": 1, "qa": 2, "confirmed": 1, "review": 1},
      "разбивка по статусам посчитана: %s" % plan["projectStatus"])
check(sum(plan["projectStatus"].values()) == plan["projectSegments"],
      "сумма разбивки равна числу сегментов — иначе браузер сверял бы разное")

# Считается ВЕСЬ проект, а не выбранные сегменты: браузер сверяет свою копию
# целиком, и разбивка по выборке нашла бы расхождение на пустом месте.
plan = main.run_plan(1, main.RunPlanRequest(segment_ids=[2]))
check(plan["projectStatus"] == {"new": 1, "qa": 2, "confirmed": 1, "review": 1},
      "выборка на разбивку не влияет: она про проект, а не про состав прогона")

# Сегмент без статуса читается как «new» — ровно так же, как в браузере
# (statusCountsOf в tab_editor.jsx). Разойдись нормализации — сверка нашла бы
# расхождение там, где его нет, и тянула бы проект целиком каждым разбором.
for missing in (None, "", "__pop__"):
    if missing == "__pop__":
        proj["segments"][0].pop("status", None)
    else:
        proj["segments"][0]["status"] = missing
    got = main.run_plan(1, main.RunPlanRequest())["projectStatus"]
    # .get, а не [...]: расхождение обязано читаться как «ПРОВАЛЕНО»,
    # а не как KeyError посреди прогона — тогда из хвоста вывода видно,
    # что именно сломалось.
    check(got.get("new") == 1 and len(got) == 4,
          "статус %r читается как «new», а не отдельной корзиной: %s" % (missing, got))

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
