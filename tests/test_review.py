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
check(str(main.REVIEW_APPLY_MAX) in sysmsg, "порог применения назван в промпте")
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

proj, seg = build()
ANSWER = {"score": 4, "issues": ["стиль"],
          "fixed": "Closed pneumothorax (closed pneumothorax) is temporary."}
main._run_segment_review(seg, proj)
check("self_dup" in (seg["review"]["veto"] or []),
      "самоповтор кандидата — та же бесплатная сверка, что у ремонта")

# Унаследованная проблема правку НЕ отменяет: сравниваем «до и после».
BAD_SRC, BAD_TGT = "Доза 5 мг.", "Dose 15 mg, artificial treatment is closed."
proj, seg = build([seg_of(1, BAD_SRC, BAD_TGT)])
ANSWER = {"score": 4, "issues": ["фраза"], "fixed": "Dose 15 mg, closed pneumothorax."}
main._run_segment_review(seg, proj)
check(seg["target"] == "Dose 15 mg, closed pneumothorax.",
      "число разошлось ещё в прежнем тексте — не наша вина и не повод отменять правку")

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
check(r["proposed"] == 3 and r["wouldApply"] == 2 and r["skippedConfirmed"] == [2],
      "заверенное человеком названо числом и в правку не пойдёт")

r = main.review_project(1, main.ReviewRequest(limit=10, sample="all", dry_run=False,
                                              refresh=True))
check(r["applied"] == 2 and r["stamp"], "правки применены, метка отката выдана")
check(segs[1]["target"] == "Confirmed text about pneumothorax.",
      "заверенный человеком сегмент пачка не переписала")
was = segs[0]["review"]["from"]
u = main.undo_review(1, r["stamp"])
check(u["restored"] == [1, 3] and segs[0]["target"] == was,
      "откат вернул прежние тексты")
check("review" not in segs[0], "и снял вердикт: он описывал текст, которого больше нет")

# Правленный после ревизии сегмент откат не трогает.
r = main.review_project(1, main.ReviewRequest(limit=10, sample="all", dry_run=False,
                                              refresh=True))
segs[0]["target"] = "Человек поправил руками."
u = main.undo_review(1, r["stamp"])
check(1 in u["changedSince"] and segs[0]["target"] == "Человек поправил руками.",
      "чужую работу откат не затирает — тот же закон, что у _repair_tried")

# ────── 10. Выборка mixed берёт и «готовые» ──────
print()
print("=== 10. Выборка: дефекты живут там, где все проверки довольны ===")
clean = seg_of(10, tgt="A clean pneumothorax translation.")
clean["backcheck"] = {"score": 98, "model": "m", "back": "b", "terms_lost": [],
                      "reasons": [], "target_hash": main._text_hash(clean["target"])}
noisy = seg_of(11, tgt="pneumothorax pneumothorax pneumothorax pneumothorax")
proj, _ = build([clean, noisy])
picked = [s["id"] for s in main._review_pick(proj, main.ReviewRequest(limit=1))]
check(picked == [10],
      "первым идёт «готовый»: иначе замер не отвечает на вопрос, ради которого сделан")

print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
