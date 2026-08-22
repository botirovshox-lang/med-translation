"""Составной прогон, уровни доверия TM и экран итогов.

Ни одного платного вызова: подменены и перевод, и обратный перевод, и termcheck.
STATE синтетический, save_state замолчан — боевые данные не трогаем.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
# В сеть не ходим: внешний корпус отвечает по-разному в разные дни.
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg(sid, source, target="", status="new", risk="medium"):
    return {"id": sid, "source": source, "target": target, "status": status, "risk": risk}


def build(segments, tm=(), gloss=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss],
                  "tm": [dict(t) for t in tm], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


# ───────────────────────── 1. TM ─────────────────────────
print("=== 1. Подменять перевод мимо модели может только своя запись TM ===")
calls = []
main._openai_translate = lambda text, s, t, **k: (calls.append(text), "MODEL: " + text)[1]

proj = build([seg(1, "жалобы"), seg(2, "одышка")],
             tm=[{"src": "жалобы", "tgt": "TM-complaints", "lang": "RU→EN", "quality": "verified"},
                 {"src": "одышка", "tgt": "TM-dyspnea", "lang": "RU→EN", "quality": "draft"}])
main.batch_translate(1, main.BatchRequest(engine="gpt", segment_ids=[1, 2], limit=10))
s1, s2 = proj["segments"]
check(s1["target"] == "TM-complaints", "своя запись подставлена без вызова модели")
check("жалобы" not in calls, "и модель для неё не вызывалась")
check(s2["target"].startswith("MODEL:"), "импортированная запись перевод не подменила")
check("одышка" in calls, "по ней модель вызвана")

print("\n=== 2. Совпадение с TM больше не заверяет сегмент ===")
check(s1["status"] == "translated", "статус translated, а не confirmed")
check(s1["route"] == "EXACT_TM", "маршрут при этом виден как EXACT_TM")
check("confirmedBy" not in s1, "отметки человека нет — он этот сегмент не видел")

# ─────────────── 3. Google убран, движок один ───────────────
print("\n=== 3. Перевод берёт все сегменты, а не половину ===")
# Раньше отбор делил сегменты по risk между Google и моделью, и запуск «не той»
# кнопки молча оставлял половину проекта непереведённой. Движок теперь один.
proj = build([seg(1, "короткий", risk="low"), seg(2, "длинный сегмент про многое", risk="high")])
r = main.batch_translate(1, main.BatchRequest(limit=10))
check(r["count"] == 2, "оба сегмента переведены независимо от длины")
check(all(s["target"].startswith("MODEL:") for s in proj["segments"]),
      "и оба — выбранной моделью")
check(all(s["route"] == "GPT_REQUIRED" or s["route"] == "DUPLICATE"
          for s in proj["segments"]), "маршрут GOOGLE_SAFE больше не появляется")

print("\n=== 3b. Без ключа модели — честная ошибка, а не бесплатный черновик ===")
key = os.environ.pop("OPENAI_API_KEY")
proj = build([seg(1, "жалобы")])
try:
    main.translate_segment(1, 1, main.TranslateRequest())
    check(False, "должно было отказать")
except main.HTTPException as e:
    check(e.status_code == 503 and "ключ" in e.detail, "503 с внятной причиной: " + e.detail)
check(proj["segments"][0]["target"] == "", "сегмент не тронут")
# Пакет обязан отдать ту же 503 ДО работы: иначе составной прогон примет
# посегментные ошибки за «порция целиком провалилась» и уронит весь прогон
# вместо того, чтобы пометить недоступный шаг пропущенным.
try:
    main.batch_translate(1, main.BatchRequest(limit=10))
    check(False, "пакет тоже должен был отказать")
except main.HTTPException as e:
    check(e.status_code == 503, "пакетный перевод отвечает 503, а не сыплет ошибками")
# Но порция из одних совпадений с памятью вызовов не делает — запрещать её
# из-за отсутствия ключа значило бы запретить бесплатную работу.
proj = build([seg(1, "жалобы")],
             tm=[{"src": "жалобы", "tgt": "complaints", "lang": "RU→EN", "quality": "verified"}])
r = main.batch_translate(1, main.BatchRequest(limit=10))
check(r["count"] == 1 and proj["segments"][0]["target"] == "complaints",
      "совпадение с памятью подставляется и без ключа модели")
proj = build([seg(1, "жалобы")])          # без памяти — переводить придётся моделью
try:
    main._job_chunk_full(1, [1], {"steps": ["translate"]})
    check(False, "порция из одного недоступного шага должна падать")
except RuntimeError as e:
    check("ни один шаг не выполнен" in str(e), "порция без единой работы честно падает")
# А если хоть один шаг отработал — недоступный лишь помечается пропущенным.
_bc = main.backcheck_batch
main.backcheck_batch = lambda pid, req: {"count": 1, "errors": []}
out = main._job_chunk_full(1, [1], {"steps": ["translate", "backcheck"]})
check(out.get("step_skips") == 1 and out.get("backcheck") == 1,
      "недоступный перевод пропущен, back-check отработал")
main.backcheck_batch = _bc
os.environ["OPENAI_API_KEY"] = key

# ─────────────────── 4. Составной прогон ───────────────────
print("\n=== 4. Составной прогон проходит шаги по порядку ===")
order = []


def fake_step(name, ret):
    def inner(pid, req):
        order.append(name)
        return ret
    return inner


proj = build([seg(1, "жалобы"), seg(2, "одышка")])
# Настоящие функции сохраняем: ниже они снова понадобятся живыми.
_real_repair, _real_tc = main.repair_batch, main._run_segment_termcheck
main.backcheck_batch = fake_step("backcheck", {"count": 2, "errors": []})
main.termcheck_batch = fake_step("termcheck", {"count": 2, "flagged": 1, "errors": []})
main.batch_medical_qa = fake_step("medical_qa", {"count": 2, "errors": []})
main.repair_batch = fake_step("repair", {"applied": [1], "skipped": [], "errors": []})
_real_translate = main.batch_translate
main.batch_translate = fake_step("translate", {"count": 2, "errors": [], "tm_hits": 0,
                                               "duplicates": 0, "skipped_confirmed": []})

out = main._job_chunk_full(1, [1, 2], {})
check(order == main.FULL_RUN_STEPS, "порядок шагов: " + " → ".join(order))
check(out["done"] == 2, "прогресс считается сегментами порции, а не суммой шагов")
check(out.get("translate") == 2 and out.get("applied") == 1,
      "счётчики шагов не сливаются в один")

print("\n=== 5. Выбор шагов и отбор внутри ===")
order.clear()
main._job_chunk_full(1, [1, 2], {"steps": ["backcheck", "repair"]})
check(order == ["backcheck", "repair"], "выключенные шаги не вызываются")

captured = {}
main.batch_translate = lambda pid, req: captured.update({"force": req.force}) or {
    "count": 1, "errors": [], "tm_hits": 0, "duplicates": 0, "skipped_confirmed": []}
order.clear()
main._job_chunk_full(1, [1, 2], {"steps": ["translate"]})
check(captured.get("force") is False,
      "перевод внутри составного прогона не затирает готовые переводы")

print("\n=== 6. Модель у каждого шага своя ===")
seen = {}
main.backcheck_batch = lambda pid, req: seen.update({"bc": req.model}) or {"count": 2, "errors": []}
main.termcheck_batch = lambda pid, req: seen.update({"tc": req.model}) or {"count": 2, "errors": []}
main.repair_batch = lambda pid, req: seen.update({"rp": req.model}) or {"applied": [], "skipped": [], "errors": []}
main._job_chunk_full(1, [1, 2], {"steps": ["backcheck", "termcheck", "repair"],
                                 "model": "T", "bc_model": "B", "tc_model": "C", "rp_model": "R"})
check(seen == {"bc": "B", "tc": "C", "rp": "R"},
      "back-check не идёт той же моделью, что переводила: " + str(seen))

print("\n=== 7. Недоступный шаг не роняет прогон, но молча не пропадает ===")
main.medical_qa_mod = None
order.clear()
main.backcheck_batch = fake_step("backcheck", {"count": 2, "errors": []})
out = main._job_chunk_full(1, [1, 2], {"steps": ["backcheck", "medical_qa"]})
check(order == ["backcheck"], "недоступный Medical QA пропущен")
check(out.get("step_skips") == 1, "и назван в счётчиках, а не потерян")

main.backcheck_batch = lambda pid, req: (_ for _ in ()).throw(
    main.HTTPException(503, "Back-check требует ключ OpenAI"))
try:
    main._job_chunk_full(1, [1, 2], {"steps": ["backcheck", "medical_qa"]})
    check(False, "порция без единого выполненного шага должна падать")
except RuntimeError as e:
    check("ни один шаг не выполнен" in str(e), "порция без работы честно падает")

print("\n=== 8. Порция, где всё сломалось, роняет прогон ===")
main.medical_qa_mod = object()
main.medical_qa_enabled = lambda: True
main.backcheck_batch = lambda pid, req: {"count": 0, "errors": [1, 2]}
try:
    main._job_chunk_full(1, [1, 2], {"steps": ["backcheck"]})
    check(False, "должно было упасть")
except RuntimeError as e:
    check("back-check" in str(e), "шаг назван в ошибке: " + str(e))

print("\n=== 9. Экран итогов считает тем же движком, что и кнопки ===")
proj = build([
    seg(1, "жалобы", "complaints", status="translated"),
    seg(2, "увеит", "eye inflammation", status="confirmed"),
    seg(3, "одышка", "", status="new"),
], gloss=[{"src": "увеит", "tgt": "uveitis", "tier": "verified",
           "lang": "RU→EN", "domain": "medical"}])
h = main._text_hash("complaints")
proj["segments"][0]["backcheck"] = {"score": 95, "target_hash": h, "back": "..."}
proj["segments"][0]["termcheck"] = {"findings": [], "target_hash": h, "model": "test"}
a = main.project_analysis(1)
check(a["clean"] == [1], "чистым считается сегмент, прошедший обе проверки")
check(a["todo"]["untranslated"] == [3], "непереведённый виден отдельно")
check(a["human"]["glossaryConfirmed"] == [2],
      "подтверждённый сегмент, спорящий с глоссарием, попал к человеку")
check(a["total"] == 3, "итог считает все сегменты проекта")
check(2 in a["todo"]["glossaryPending"] or 2 in a["human"]["glossaryConfirmed"],
      "расхождение не потеряно ни в одном списке")

print("\n=== 10. Пакетный ремонт не переписывает подтверждённое ===")
main.batch_translate, main.repair_batch = _real_translate, _real_repair
gl = [{"src": "увеит", "tgt": "uveitis", "tier": "verified", "lang": "RU→EN", "domain": "medical"}]
proj = build([seg(1, "увеит", "eye inflammation", status="confirmed"),
              seg(2, "увеит справа", "eye inflammation on the right", status="translated")],
             gloss=gl)
proj["segments"][0]["confirmedBy"] = "human"
main._openai_repair = lambda seg_, project_, findings_, model_: "uveitis"
main._run_segment_termcheck = lambda seg_, *a, **k: seg_.__setitem__(
    "termcheck", {"findings": [], "target_hash": main._text_hash(seg_["target"].strip()),
                  "model": "test"})
r = main.repair_batch(1, main.RepairBatchRequest(limit=10))
check(1 not in r["applied"], "подтверждённый сегмент не тронут")
check(r["skipped_confirmed"] == [1], "и назван в отчёте, а не выброшен молча")
check(proj["segments"][0]["target"] == "eye inflammation", "заверенный текст на месте")
check(proj["segments"][0]["confirmedBy"] == "human", "отметка человека на месте")
check(2 in r["applied"], "неподтверждённый при этом починен")

r = main.repair_batch(1, main.RepairBatchRequest(limit=10, include_confirmed=True, retry=True))
check(1 in r["applied"], "с явной галочкой подтверждённый чинится")
check(proj["segments"][0]["status"] == "review", "и уходит на проверку человеком")

print("\n=== 11. Правка ради глоссария перепроверяется, а не берётся на веру ===")
checked_by = []
main._run_segment_termcheck = lambda seg_, *a, **k: (
    checked_by.append(seg_["id"]),
    seg_.__setitem__("termcheck", {"findings": [], "model": "test",
                                   "target_hash": main._text_hash(seg_["target"].strip())}))[0]
proj = build([seg(1, "увеит", "eye inflammation", status="translated")], gloss=gl)
main._run_segment_repair(proj["segments"][0], proj)
check(checked_by == [1], "termcheck перепроверил подставленный термин")

# Правка, которая ставит термин, но ломает целевой текст, должна откатываться.
proj = build([seg(1, "увеит", "eye inflammation", status="translated")], gloss=gl)
main._run_segment_termcheck = lambda seg_, *a, **k: seg_.__setitem__(
    "termcheck", {"findings": [{"severity": "critical", "tgt_term": "uveitis"}],
                  "model": "test", "target_hash": main._text_hash(seg_["target"].strip())})
r = main._run_segment_repair(proj["segments"][0], proj)
check(not r["applied"], "правка с новым замечанием отвергнута")
check(proj["segments"][0]["target"] == "eye inflammation", "текст откачен")

print("\n=== 12. Шаг с незаполненной моделью берёт свою, а не модель переводчика ===")
seen = {}
main.backcheck_batch = lambda pid, req: seen.update({"bc": req.model}) or {"count": 1, "errors": []}
main._job_chunk_full(1, [1], {"steps": ["backcheck"], "model": "ПЕРЕВОДЧИК", "bc_model": ""})
check(seen["bc"] is None, "пустая модель шага не подменяется моделью перевода")

print("\n=== 13. Порядок шагов задаёт сервер, а не клиент ===")
order.clear()
main.backcheck_batch = fake_step("backcheck", {"count": 1, "errors": []})
main.repair_batch = fake_step("repair", {"applied": [], "skipped": [], "errors": []})
main._job_chunk_full(1, [1], {"steps": ["repair", "backcheck"]})
check(order == ["backcheck", "repair"], "присланный задом наперёд список выправлен: " + str(order))

print("\n=== 14. Несостоявшаяся перепроверка — это откат, а не молчаливое «ок» ===")
proj = build([seg(1, "увеит", "eye inflammation", status="translated")], gloss=gl)
main._openai_repair = lambda *a, **k: "uveitis"
main._run_segment_termcheck = lambda *a, **k: None      # вызов «упал», свежей оценки нет
r = main._run_segment_repair(proj["segments"][0], proj)
check(r["ok"] and not r["applied"], "правка без перепроверки отвергнута")
check("перепроверка" in r["repair"]["reason"], "причина названа: " + r["repair"]["reason"])
check(proj["segments"][0]["target"] == "eye inflammation", "текст на месте")

print("\n=== 15. Подрезка очереди помнит СВЕЖИЕ решения, а не позиции ===")
main.STATE = {"projects": [], "glossary": [], "tm": [], "termQueue": [], "team": []}
q = main.STATE["termQueue"]
# Старый кандидат, решённый сегодня, лежит в самом низу очереди по дате создания.
for i in range(main.TERM_QUEUE_MAX + 100):
    q.append({"id": i, "kind": "extract", "src": "ш%d" % i, "tgt": "n%d" % i,
              "status": "approved", "autoBatch": 7, "autoWrote": True})
q.append({"id": 99999, "kind": "segment", "src": "важный", "tgt": "important",
          "status": "approved", "decidedBy": "human", "decidedAt": "2026-08-21 10:00"})
main._trim_term_queue()
check(any(c["id"] == 99999 for c in q), "свежее решение человека уцелело, хотя лежало последним")

print("\n=== 16. Корзины экрана итогов исчерпывающие ===")
proj = build([seg(1, "жалобы", "complaints", status="translated")])
h = main._text_hash("complaints")
# Проверки сделаны, но back-check ниже порога: ни «чисто», ни «не проверено».
proj["segments"][0]["backcheck"] = {"score": 55, "target_hash": h, "back": "..."}
proj["segments"][0]["termcheck"] = {"findings": [], "target_hash": h, "model": "test"}
a = main.project_analysis(1, refresh=True)
buckets = (set(a["clean"]) | set(a["todo"]["untranslated"]) | set(a["todo"]["unchecked"])
           | set(a["todo"]["findings"]) | set(a["todo"]["weak"]))
check(buckets == {1}, "сегмент попал хотя бы в одну корзину, а не исчез")
check(a["todo"]["weak"] == [1] and a["todo"]["weakWhy"], "и назван с причиной: "
      + str(a["todo"]["weakWhy"]))

print("\n=== 17. Отчёт видит проверки, а не только текст ===")
before = main.project_analysis(1)
proj["segments"][0]["backcheck"] = {"score": 95, "target_hash": h, "back": "..."}
after = main.project_analysis(1)
check(after["clean"] == [1] and before["clean"] == [],
      "прогон back-check меняет отчёт, хотя ни статус, ни перевод не тронуты")

print("\n=== 18. Второй клик: одобрить термины и применить их ===")
main.repair_batch, main._run_segment_termcheck = _real_repair, _real_tc
main._openai_repair = lambda *a, **k: "uveitis on the right"
main._run_segment_termcheck = lambda seg_, *a, **k: seg_.__setitem__(
    "termcheck", {"findings": [], "model": "t",
                  "target_hash": main._text_hash((seg_.get("target") or "").strip())})
proj = build([
    seg(1, "увеит", "uveitis", status="translated"),
    seg(2, "увеит", "uveitis", status="translated"),
    seg(3, "увеит", "uveitis", status="translated"),
    seg(10, "увеит справа", "eye inflammation on the right", status="translated"),
], gloss=[])
for s in proj["segments"][:3]:
    h = main._text_hash("uveitis")
    s["source"] = "увеит " + str(s["id"])      # разные исходники → независимость
    s["backcheck"] = {"score": 95, "target_hash": h, "back": "..."}
    s["termcheck"] = {"findings": [], "target_hash": h, "model": "t"}
main.STATE["termQueue"].append(
    {"id": 1, "kind": "segment", "src": "увеит", "tgt": "uveitis", "status": "pending",
     "hits": 3, "segments": ["1:1", "1:2", "1:3"], "lang": "RU→EN", "domain": "medical"})


# Справочник обязателен для этой проверки, и это не подпорка, а суть механики:
# в медицине согласие сегментов даёт только ПОДСКАЗКУ, а подсказку модель вправе
# игнорировать — переписывать по ней готовые переводы нельзя. Приказом термин
# делает внешний источник, и только после этого ремонт вправе его подставлять.
class FakeDict:
    id, label = "test_inn", "Тестовый справочник"
    pairs = {"увеит": {"uveitis"}}

    def covers(self, lang, domain):
        return lang == "RU→EN" and domain == "medical"

    def match(self, src, tgt):
        return (src.strip().lower(), tgt.strip().lower()) == ("увеит", "uveitis")

    def suggest(self, src):
        return ["uveitis"] if src.strip().lower() == "увеит" else []


main._DICTIONARIES = [FakeDict()]

job = {"id": 1, "kind": "apply_terms", "project": 1, "status": "running", "total": 0,
       "done": 0, "counters": {}, "error": None, "params": {}, "ids": [], "stop": False,
       "recent": [], "created": "", "started": None, "finished": None}
main._job_run(job)
check(job["status"] == "done", "прогон завершился: " + str(job.get("error")))
check(job["counters"].get("termsApproved") == 1, "термин одобрен и записан в глоссарий")
check(any(g["src"] == "увеит" for g in main.STATE["glossary"]), "запись появилась")
check(job["total"] == 1 and job["ids"] == [10],
      "состав сегментов посчитан ПОСЛЕ одобрения: только разошедшийся, " + str(job["ids"]))
check(main.STATE["projects"][0]["segments"][3]["target"] == "uveitis on the right",
      "сегмент починен новым термином")
check(job["counters"].get("applied") == 1, "и это отражено в счётчиках")

print("\n=== 19. Одобрять нечего — прогон не падает и ничего не чинит ===")
job2 = dict(job, id=2, status="running", done=0, counters={}, ids=[], total=0)
main._job_run(job2)
check(job2["status"] == "done" and job2["counters"].get("termsApproved") == 0,
      "пустое одобрение — это не ошибка")
check(job2["total"] == 0, "и чинить после него нечего")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
