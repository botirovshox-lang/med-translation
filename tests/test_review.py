"""Ревизия: единственная проверка, которая читает ПАРУ целиком.

Зачем шаг заведён. Все прежние проверки задают узкий вопрос и потому слепы
к целому классу дефектов: back-check меряет долю основ ОРИГИНАЛА, вернувшихся
через обратный перевод (то есть вознаграждает кальку и самого перевода
не видит — судье уходят оригинал и обратный перевод), а termcheck смотрит
ТОЛЬКО на терминологию и обязан молчать про синтаксис. Ошибку, которую нельзя
ткнуть пальцем в одно слово, записать было некуда.

Что здесь сторожится, по важности:
  • балл back-check НЕ участвует в решении — ради этого шаг и устроен так,
    что возвращает готовый текст и не заходит в `_run_segment_repair`, где
    живёт вето по баллу (оно выбросило 111 верных правок на боевом проекте);
  • вместо балла — бесплатные ОБЪЕКТИВНЫЕ сверки: числа, единицы, отрицание,
    приказные термины, регистр, чужое письмо, самоповтор;
  • промпт гоняется НАСТОЯЩИМ кодом (подменён клиент OpenAI, а не наша
    функция) — тот же закон, что в test_prompt_build.py: подменишь свою
    функцию, и сборщик промпта не выполнится ни разу.
"""
import json, os, sys, types, tempfile, pathlib

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"

SENT = {}
ANSWER = {"score": 4, "issues": ["фраза не по-английски"],
          "fixed": "Closed pneumothorax."}


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(
            message=types.SimpleNamespace(content=text))]
        self.usage = types.SimpleNamespace(prompt_tokens=700, completion_tokens=90,
                                           total_tokens=790)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        SENT["model"] = model
        SENT["calls"] = SENT.get("calls", 0) + 1
        return FakeResp(json.dumps(ANSWER, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
main.PURGE_DIR = pathlib.Path(tempfile.mkdtemp(prefix="review-test-"))

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


GLOSS = [{"src": "пневмоторакс", "tgt": "pneumothorax", "tier": "verified",
          "cat": "Term", "lang": "RU→EN", "domain": "medical"}]
SRC = "Закрытый пневмоторакс. Сообщение между полостью плевры и альвеолами временное."
TGT = "Artificial pneumothorax treatment is closed."


def seg_of(sid, src=SRC, tgt=TGT, **kw):
    seg = {"id": sid, "source": src, "target": tgt, "status": "translated"}
    seg.update(kw)
    return seg


def build(segments=None, **pkw):
    segs = segments if segments is not None else [seg_of(1)]
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": segs}
    proj.update(pkw)
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in GLOSS],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": [],
                  "audit": [], "tenants": [], "users": []}
    main._invalidate_gloss_index()
    main._HITS_CACHE.clear()
    return proj, segs[0]


# ────── 1. Промпт собирается НАСТОЯЩИМ кодом ──────
print("=== 1. Промпт: гоняется целиком, подменён только клиент ===")
proj, seg = build()
ANSWER = {"score": 9, "issues": [], "fixed": ""}
out = main._run_segment_review(seg, proj)
check(out.get("ok") is True, "вызов прошёл через настоящий сборщик промпта")
sysmsg = SENT["system"]
check(main.REVIEW_APPLY_LABEL in sysmsg, "порог применения назван в промпте")
check("7.0" not in sysmsg,
      "и назван целым: дробный хвост читается как точность, которой у оценки нет")
check("EN" in sysmsg and "RU" in sysmsg, "пара языков берётся у проекта, а не зашита")
check("менять НЕЛЬЗЯ" in sysmsg,
      "приказные термины трогать запрещено: они согласованы с заказчиком")
check("source_suspect" in sysmsg,
      "повреждённый оригинал — свой ответ, а не догадка вместо перевода")
check("обстановка" in SENT["system"] or "обстановк" in SENT["system"],
      "соседи даны как обстановка и оценке не подлежат")
check("pneumothorax" in SENT["user"],
      "приказный термин уехал в запрос: без списка модель его законно перепишет")
check(SENT["model"] == main.REVIEW_DEFAULT_MODEL == "gpt-5.6-terra",
      "модель по умолчанию — Terra")

# ────── 2. Оценка выше порога правку не даёт ──────
print()
print("=== 2. Оценка выше порога — текст не трогаем ===")
proj, seg = build()
ANSWER = {"score": 9, "issues": ["мелкая придирка"], "fixed": "Something else entirely."}
main._run_segment_review(seg, proj)
check(seg["target"] == TGT, "текст остался прежним при оценке 9")
check(seg["review"]["applied"] is False and seg["review"]["skipped"] == "оценка выше порога",
      "причина названа: улучшение — не дефект, и переписывать за деньги нечего")

# ────── 3. Ниже порога и сверки чисты — правка применяется ──────
print()
print("=== 3. Дефект: правка применяется без единого вызова модели сверх одного ===")
proj, seg = build()
ANSWER = {"score": 4, "issues": ["неестественный английский"],
          "fixed": "Closed pneumothorax. The communication between the pleural cavity "
                   "and the alveoli is temporary."}
SENT["calls"] = 0
out = main._run_segment_review(seg, proj)
check(out["applied"] is True, "правка применена")
check(seg["target"].startswith("Closed pneumothorax"), "в сегменте стоит текст ревизора")
check(seg["status"] == "review", "статус review: машина не заверяет сама себя")
check(seg["review"]["from"] == TGT, "прежний текст сохранён — есть что откатывать")
check(SENT["calls"] == 1, "ровно ОДИН вызов модели на сегмент: ремонта нет")
check(main._review_stale(seg) is False,
      "вердикт описывает НЫНЕШНИЙ текст — второй платный заход закрыт")

# ────── 4. Балл back-check в решении НЕ участвует ──────
print()
print("=== 4. Балл back-check не отменяет верную правку ===")
# Ровно тот случай, ради которого шаг заведён: калька набирает высокий балл,
# верный перевод возвращается синонимом и балл роняет. В `_run_segment_repair`
# такая правка откатывалась бы; здесь балла нет в расчёте вовсе.
BC = {"score": 100, "model": "m", "back": "тот же текст", "terms_lost": [],
      "reasons": [], "target_hash": main._text_hash(TGT)}
proj, seg = build([seg_of(1, bc=None)])
seg["backcheck"] = dict(BC)
ANSWER = {"score": 5, "issues": ["калька"], "fixed": "Closed pneumothorax is temporary."}
main._run_segment_review(seg, proj)
check(seg["target"] == "Closed pneumothorax is temporary.",
      "балл 100 правку не отменил — измеритель сменился, а не исчез")
check("score" not in main.REVIEW_FREE_KEYS,
      "балла нет среди сверок кандидата, и это несущее свойство шага")

# ────── 5. Объективные сверки вето накладывают ──────
print()
print("=== 5. Что вместо балла: бесплатные и объективные сверки ===")
NUM_SRC = "Курс лечения 6 месяцев, доза 300 мг."
NUM_TGT = "The course is 6 months, dose 300 mg."
proj, seg = build([seg_of(1, NUM_SRC, NUM_TGT)])
ANSWER = {"score": 4, "issues": ["стиль"], "fixed": "The course is 9 months, dose 300 mg."}
main._run_segment_review(seg, proj)
check(seg["target"] == NUM_TGT, "число подменено — правка не поставлена")
check("hard" in (seg["review"]["veto"] or []),
      "вето названо поимённо: расхождение чисел")

proj, seg = build()
ANSWER = {"score": 4, "issues": ["стиль"], "fixed": "Closed collapse of the lung."}
main._run_segment_review(seg, proj)
check(seg["target"] == TGT, "приказный термин выбит — правка не поставлена")
check("gloss" in (seg["review"]["veto"] or []), "вето: нарушено приказных терминов больше")

# Подмена СТОРОНЫ и потеря ЕДИНИЦ. Первая версия фильтровала находки по
# checks.BACKCHECK_HARD_TYPES — а те рождаются только в run_backcheck, и
# deterministic_issues не выдаёт из них ни одной: половина условия была
# мёртвым кодом, и «right lung» → «left lung» уходило в документ клиента.
SIDE_SRC, SIDE_TGT = "Поражено правое лёгкое.", "The right lung is affected."
proj, seg = build([seg_of(1, SIDE_SRC, SIDE_TGT)])
ANSWER = {"score": 4, "issues": ["стиль"], "fixed": "The left lung is affected."}
main._run_segment_review(seg, proj)
check(seg["target"] == SIDE_TGT and "hard" in (seg["review"]["veto"] or []),
      "подмена стороны поражения — вето (правое лёгкое не станет левым молча)")

UNIT_SRC, UNIT_TGT = "Доза 300 мг в сутки.", "Dose 300 mg per day."
proj, seg = build([seg_of(1, UNIT_SRC, UNIT_TGT)])
ANSWER = {"score": 4, "issues": ["стиль"], "fixed": "Dose 300 per day."}
main._run_segment_review(seg, proj)
check(seg["target"] == UNIT_TGT and "hard" in (seg["review"]["veto"] or []),
      "единицы выброшены из дозировки — вето")

# Жёсткая находка меряется АБСОЛЮТНО, а не «стало ли больше»: размен одной
# объективной ошибки на другую даёт счёт 1 → 1 и прошёл бы сравнением.
BAD2_SRC, BAD2_TGT = "Доза 5 мг, правое лёгкое.", "Dose 15 mg, the right lung."
proj, seg = build([seg_of(1, BAD2_SRC, BAD2_TGT)])
ANSWER = {"score": 4, "issues": ["стиль"], "fixed": "Dose 5 mg, the left lung."}
main._run_segment_review(seg, proj)
check(seg["target"] == BAD2_TGT and "hard" in (seg["review"]["veto"] or []),
      "размен числа на сторону — не работа: вето при любом счёте")

# Область и языки берутся у ПРОЕКТА, а не по умолчанию medical RU→EN.
import inspect as _insp
_src_veto = _insp.getsource(main._review_veto)
check("domain=dom" in _src_veto and "src_lang=src_lang" in _src_veto,
      "deterministic_issues зовётся с областью и парой языков проекта")
check("OBJECTIVE_ISSUE_TYPES" in _src_veto and "BACKCHECK_HARD_TYPES" not in _src_veto,
      "фильтр по типам находок ПАРЫ, а не по типам back-check")

proj, seg = build()
ANSWER = {"score": 4, "issues": ["стиль"],
          "fixed": "Closed pneumothorax (closed pneumothorax) is temporary."}
main._run_segment_review(seg, proj)
check("self_dup" in (seg["review"]["veto"] or []),
      "самоповтор кандидата — та же бесплатная сверка, что у ремонта")

# Унаследованная объективная ошибка тоже держит правку: цена строгости
# названа честно — такой сегмент чинит человек, и он же видит его в
# sourceSuspect. Бесплатные счётчики при этом сравниваются «до и после».
BAD_SRC, BAD_TGT = "Доза 5 мг.", "Dose 15 mg, artificial treatment is closed."
proj, seg = build([seg_of(1, BAD_SRC, BAD_TGT)])
ANSWER = {"score": 4, "issues": ["фраза"], "fixed": "Dose 15 mg, closed pneumothorax."}
main._run_segment_review(seg, proj)
check(seg["target"] == BAD_TGT and "hard" in (seg["review"]["veto"] or []),
      "число разошлось ещё в оригинале — молча в документ такое не пишем")

# ────── 6. Повреждённый оригинал — к человеку, а не догадкой ──────
print()
print("=== 6. Оригинал под подозрением ===")
proj, seg = build()
ANSWER = {"score": 3, "issues": ["исходник бессвязен"], "source_suspect": True,
          "fixed": "Some guess."}
main._run_segment_review(seg, proj)
check(seg["target"] == TGT, "перевод не чинится догадкой по битому оригиналу")
check(seg["review"]["sourceSuspect"] is True
      and seg["review"]["skipped"] == "оригинал под подозрением",
      "класс, которого в системе не было вовсе, теперь назван")

# ────── 7. Отказ модели сегмент не портит ──────
print()
print("=== 7. Молчание модели ===")
proj, seg = build()
ANSWER = {"issues": []}                      # нет score — ответ негоден
out = main._run_segment_review(seg, proj)
check(out.get("ok") is False and seg["target"] == TGT,
      "ответ без оценки — это «не знаю»: сегмент не трогаем")
check("review" not in seg, "и вердикта не пишем: писать нечего")

# ────── 8. Устаревание по тексту и по версии вопросов ──────
print()
print("=== 8. Кэш вердикта ===")
proj, seg = build()
ANSWER = {"score": 9, "issues": [], "fixed": ""}
main._run_segment_review(seg, proj)
check(main._review_stale(seg) is False, "свежий вердикт")
seg["target"] = "Another translation."
check(main._review_stale(seg) is True, "текст сменился — вердикт устарел")
seg["target"] = TGT
seg["review"]["v"] = "0"
check(main._review_stale(seg) is True,
      "версия вопросов сменилась — вердикт устарел (иначе новый вопрос не задаётся)")

# ────── 9. Пачка: выборка, заверенное, откат ──────
print()
print("=== 9. Пачка: правила массовых команд ===")
READY = {"score": 100, "model": "m", "back": "b", "terms_lost": [], "reasons": []}
segs = [seg_of(1), seg_of(2, tgt="Confirmed text about pneumothorax.", status="confirmed"),
        seg_of(3)]
proj, _ = build(segs)
ANSWER = {"score": 4, "issues": ["фраза"], "fixed": "Closed pneumothorax is temporary."}
r = main.review_project(1, main.ReviewRequest(limit=10, sample="all"))
check(r["dryRun"] is True and r["applied"] == 0,
      "dry_run по умолчанию: посчитали и показали, текст не тронули")
check(segs[0]["target"] == TGT, "в сухом прогоне текст на месте")
# Заверенное человеком не спрашивают ВОВСЕ: применить вердикт к нему нечем,
# а платный совет в никуда — тот же перерасход, от которого заведён
# _repair_futile. Разбор состава говорит об этом отдельной причиной.
check(r["proposed"] == 2 and r["wouldApply"] == 2 and r["asked"] == 2,
      "заверенный сегмент в ревизию не попал: %r" % ({k: r[k] for k in ("asked", "proposed", "wouldApply")},))

# ШТАТНЫЙ порядок массовой команды: посмотрел сухим прогоном → применил.
# Без apply_saved он не работал вовсе: сухой прогон закрывает сегменты от
# отбора, боевой запуск находил ноль, и обойти можно было только refresh —
# заплатив за те же вердикты второй раз.
calls_before = SENT.get("calls", 0)
# Сверки при применении СЧИТАЮТСЯ ЗАНОВО: вердикт мог быть вынесен прежними
# правилами или до правки глоссария. Проверяем на подложенном кандидате,
# который ломает число, — сохранённый вердикт его не спасает.
trap = seg_of(99, "Доза 5 мг.", "Dose 5 mg.")
trap["review"] = {"score": 4, "candidate": "Dose 50 mg.", "model": "m",
                  "v": main.REVIEW_VERSION, "applied": False,
                  "target_hash": main._text_hash("Dose 5 mg.")}
segs.append(trap)
r = main.review_project(1, main.ReviewRequest(dry_run=False, apply_saved=True))
check(trap["target"] == "Dose 5 mg." and "hard" in (trap["review"].get("veto") or []),
      "сохранённый вердикт не обходит сверку: правила могли смениться после него")
segs.remove(trap)
check(SENT.get("calls", 0) == calls_before,
      "применение сохранённого НЕ ходит в модель — оплачено один раз")
check(r["applied"] == 2 and r["stamp"], "правки применены, метка отката выдана")
check(segs[0]["review"]["from"] == TGT, "прежний текст сохранён при применении")
check(segs[1]["target"] == "Confirmed text about pneumothorax.",
      "заверенный человеком сегмент пачка не переписала")
check(segs[0]["provider"] == "gpt-5.6-terra",
      "провайдер — модель РЕВИЗОРА: иначе back-check пойдёт к автору текста за отзывом о нём же")
check(main._machine_clean(segs[0], 90) is not None,
      "переписанный ревизией сегмент не учит глоссарий — система не заверяет свою правку")

was = segs[0]["review"]["from"]
u = main.undo_review(1, r["stamp"])
check(u["restored"] == [1, 3] and segs[0]["target"] == was,
      "откат вернул прежние тексты")
# Откат ОКОНЧАТЕЛЕН: прежде вердикт стирался, сегмент снова считался
# неспрошенным, и следующий прогон платил ещё раз и ставил тот же текст
# обратно — машина переигрывала решение человека.
check(segs[0]["review"]["undone"] and segs[0]["review"]["applied"] is False,
      "откат оставил след, а не стёр вердикт")
calls_before = SENT.get("calls", 0)
r2 = main.review_project(1, main.ReviewRequest(limit=10, sample="all"))
check(r2["asked"] == 0 and SENT.get("calls", 0) == calls_before,
      "следующий прогон откачённый сегмент не переспрашивает")
r3 = main.review_project(1, main.ReviewRequest(dry_run=False, apply_saved=True))
check(r3["applied"] == 0 and segs[0]["target"] == was,
      "и applied_saved его не возвращает: человек уже ответил")

# Правленный после ревизии сегмент откат не трогает.
r = main.review_project(1, main.ReviewRequest(limit=10, sample="all", dry_run=False,
                                              refresh=True))
segs[0]["target"] = "Человек поправил руками."
u = main.undo_review(1, r["stamp"])
check(1 in u["changedSince"] and segs[0]["target"] == "Человек поправил руками.",
      "чужую работу откат не затирает — тот же закон, что у _repair_tried")

# Заверенное человеком защищено в САМОЙ подстановке, а не только в эндпоинте.
conf = seg_of(77, tgt="Confirmed by a human.", status="confirmed",
              confirmedBy="u1")
proj, _ = build([conf])
conf["review"] = {"score": 3, "candidate": "Rewritten by the machine.",
                  "model": "m", "v": main.REVIEW_VERSION, "applied": False,
                  "target_hash": main._text_hash("Confirmed by a human.")}
check(main._apply_review(conf) is False and conf["target"] == "Confirmed by a human.",
      "_apply_review сам не трогает заверенное — правило живёт рядом с _replace_target")
check(main._apply_review(conf, include_confirmed=True) is True
      and conf["target"] == "Rewritten by the machine.",
      "с явным разрешением — переписывает")

# Потолок и усечение.
proj, _ = build([seg_of(i) for i in range(1, 8)])
r = main.review_project(1, main.ReviewRequest(limit=3, sample="all"))
check(r["asked"] == 3 and r["capped"] == 4,
      "остаток назван числом: молчаливое усечение неотличимо от «работа кончилась»")
try:
    main.review_project(1, main.ReviewRequest(limit=10 ** 6))
    check(False, "потолок limit обязан отказывать")
except Exception as e:
    check(getattr(e, "status_code", None) == 400, "limit сверх потолка — 400, воркер один")
try:
    main.review_project(1, main.ReviewRequest(sample="mix"))
    check(False, "опечатка в sample обязана отказывать")
except Exception as e:
    check(getattr(e, "status_code", None) == 400,
          "опечатка в sample — 400, а не молчаливое «all»")

# ────── 10. Выборка mixed берёт и «готовые» ──────
print()
print("=== 10. Выборка: дефекты живут там, где все проверки довольны ===")
clean = seg_of(10, tgt="A clean pneumothorax translation.")
clean["backcheck"] = {"score": 98, "model": "m", "back": "b", "terms_lost": [],
                      "reasons": [], "target_hash": main._text_hash(clean["target"])}
noisy = seg_of(11, tgt="pneumothorax pneumothorax pneumothorax pneumothorax")
proj, _ = build([clean, noisy])
got, total = main._review_pick(proj, main.ReviewRequest(limit=1))
check([s["id"] for s in got] == [10],
      "первым идёт «готовый»: иначе замер не отвечает на вопрос, ради которого сделан")
check(total == 2, "общее число считается ОДНИМ проходом — второй прошёл бы книгу заново")

# ────── 11. Встраивание в конвейер: находки аудита ──────
print()
print("=== 11. Шаг в составном прогоне ===")
check(main.FULL_RUN_STEPS.index("review") == 1,
      "ревизия идёт ВТОРОЙ: переписывающее раньше описывающего")
check(main.FULL_STEP_MODEL.get("review") == "rv_model"
      and main.list_models().get("reviewDefault") in {m["id"] for m in main.list_models()["models"]},
      "каталог называет модель шага — иначе смета главной кнопки станет прочерком")
check("review" in main.JOB_CHUNKS and "review" in main.JOB_KINDS,
      "тип прогона зарегистрирован: иначе отдельный запуск отвечает 400")

# Мёртвый ключ обязан ронять порцию, а не выглядеть как «выполнено».
proj, _ = build([seg_of(1), seg_of(2)])
_real_rp = main.review_project
main.review_project = lambda pid, req: {"ok": True, "answered": 0, "failed": 2,
                                        "applied": 0, "proposed": 0,
                                        "sourceSuspect": [], "skippedConfirmed": [],
                                        "vetoed": {}}
r = main._job_chunk("review", 1, [1, 2], {})
check(r["done"] == 0 and r["errors"] >= 2,
      "порция, где не ответил НИ ОДИН сегмент, видна как ошибка: %r" % (r,))
main.review_project = _real_rp

# Разбор состава и отбор шага обязаны совпадать: разойдись они — план обещает
# одно, а прогон платит за другое.
def plan_vs_pick(segs, **params):
    proj, _ = build(segs)
    plan = main._plan_step(proj, "review", params, list(proj["segments"]), set(), set())
    got, _total = main._review_pick(proj, main.ReviewRequest(
        segment_ids=[s["id"] for s in proj["segments"]], limit=99,
        include_confirmed=bool(params.get("include_confirmed"))))
    return sorted(plan.get("ids") or []), sorted(s["id"] for s in got)

undone = seg_of(1, tgt="Правленный руками текст.")
undone["review"] = {"score": 4, "candidate": "X", "model": "m", "v": main.REVIEW_VERSION,
                    "applied": False, "undone": {"by": "u1", "at": "now"},
                    "target_hash": main._text_hash("другой текст")}
a, b = plan_vs_pick([undone, seg_of(2)])
check(a == b == [2],
      "откачённый человеком не попадает НИ в план, НИ в работу: %r против %r" % (a, b))

conf = seg_of(3, status="confirmed", confirmedBy="u1")
a, b = plan_vs_pick([conf, seg_of(4)])
check(a == b == [4], "заверенный не попадает ни в план, ни в работу: %r против %r" % (a, b))
# Разбор описывает ПРОГОН, а прогон ревизии `include_confirmed` не даёт вовсе
# (`_job_chunk_full` гасит флаг всем, кроме ремонта). Поэтому план пропускает
# заверенные БЕЗУСЛОВНО: прочитай он флаг — галочка в строке РЕМОНТА заставила
# бы строку ревизии обещать все заверенные сегменты проекта, а шаг их не взял
# бы. Прямой вызов API с явным разрешением — другой путь, и он их берёт.
proj, _ = build([conf, seg_of(4)])
plan = main._plan_step(proj, "review", {"include_confirmed": True},
                       list(proj["segments"]), set(), set())
got, _tot = main._review_pick(proj, main.ReviewRequest(limit=99, include_confirmed=True))
check(sorted(plan.get("ids") or []) == [4],
      "галочка ремонта не заставляет план обещать заверенные: %r" % (plan.get("ids"),))
check(sorted(s["id"] for s in got) == [3, 4],
      "прямой вызов с разрешением заверенные берёт")

# Вердикт устаревает и от правки ОРИГИНАЛА: иначе корзину «повреждён сам
# оригинал» нечем осушить — человек выправил исходник, а строка висит вечно.
proj, seg = build()
ANSWER = {"score": 3, "issues": ["исходник бессвязен"], "source_suspect": True, "fixed": ""}
main._run_segment_review(seg, proj)
check(main._review_stale(seg) is False, "вердикт свежий")
seg["source"] = "Исправленный человеком оригинал."
check(main._review_stale(seg) is True,
      "правка ОРИГИНАЛА делает вердикт устаревшим — корзина осушается")

# ────── 12. Откат ПРОГОНА — одной командой ──────
print()
print("=== 12. Одна метка на весь прогон, а не на каждую порцию ===")
# Прогон идёт порциями по пять сегментов. Своя копия на каждую означала бы
# на книге ~250 меток по одному-два сегмента: откат, которым нельзя
# воспользоваться.
segs = [seg_of(i, tgt="Artificial pneumothorax treatment is closed. #%d" % i)
        for i in range(1, 7)]
proj, _ = build(segs)
ANSWER = {"score": 4, "issues": ["фраза"], "fixed": "Closed pneumothorax is temporary."}
shared = main._backup_stamp("review")
stamps = set()
for chunk in ([1, 2], [3, 4], [5, 6]):          # три «порции» одного прогона
    r = main.review_project(1, main.ReviewRequest(
        segment_ids=chunk, limit=5, dry_run=False, stamp=shared, refresh=True))
    stamps.add(r["stamp"])
check(stamps == {shared}, "все порции пишут в ОДНУ метку: %r" % (stamps,))
data = main._read_backup("review", 1, shared)
check(sorted(s["id"] for s in data["segments"]) == [1, 2, 3, 4, 5, 6],
      "в копии лежит весь прогон, а не последняя порция: %r"
      % ([s["id"] for s in data["segments"]],))
u = main.undo_review(1, shared)
check(sorted(u["restored"]) == [1, 2, 3, 4, 5, 6],
      "и откатывается он ОДНОЙ командой: %r" % (u["restored"],))
check(all(s["target"].startswith("Artificial") for s in segs),
      "тексты вернулись все до одного")

# Повторно снятый сегмент: побеждает ПЕРВЫЙ снимок. Второй раз сегмент
# попадает сюда, когда порцию повторяют (JOB_CHUNK_RETRIES) или когда прогон
# начинают заново после рестарта, — и в нём уже стоит НАШ текст. Сохрани мы
# его, откат вернул бы машинную правку, а перевод человека пропал бы
# навсегда: prevTarget пишется только у заверенных, а review.from
# перезаписывается вторым применением.
def snap(sid, text):
    return {"id": sid, "target": text, "status": "translated", "provider": None,
            "route": None, "confirmedBy": None, "confirmedAt": None,
            "prevTarget": None, "repair": {}}

proj, _ = build([seg_of(1)])
st = main._backup_stamp("review")
main._backup_segments("review", 1, [snap(1, "текст человека")], st)
main._backup_segments("review", 1, [snap(1, "уже переписанный машиной")], st)
d2 = main._read_backup("review", 1, st)
check(len(d2["segments"]) == 1 and d2["segments"][0]["target"] == "текст человека",
      "в копии остаётся ПЕРВЫЙ снимок: %r" % (d2["segments"][0]["target"],))

# Метка резервируется файлом СРАЗУ: между её выдачей и первой правкой проходят
# минуты, и ручная пачка в ту же секунду заняла бы имя — прогон умер бы на
# первой правке с 500.
st2 = main._backup_stamp("review")
check(st2 != st and (main.PURGE_DIR / ("review-" + st2 + ".json")).exists(),
      "новая метка отличается и сразу занята файлом")
main._backup_drop_empty("review", st2)
check(not (main.PURGE_DIR / ("review-" + st2 + ".json")).exists(),
      "пустая копия убирается, каталог не зарастает")
main._backup_drop_empty("review", st)
check((main.PURGE_DIR / ("review-" + st + ".json")).exists(),
      "а НЕпустую не трогает — в ней лежит чужой откат")

# Метка приходит из публичного API: не проверь мы её при ЗАПИСИ, команда
# переписала бы тексты и сложила копию под именем, которое чтение не примет.
try:
    main._backup_segments("review", 1, [snap(2, "x")], "../abc")
    check(False, "негодная метка обязана отказывать")
except Exception as e:
    check(getattr(e, "status_code", None) == 400,
          "негодная метка — 400 ДО правки, а не копия, которую нечем прочитать")

print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
