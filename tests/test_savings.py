"""Экономия вызовов: что прогон обязан НЕ делать во второй раз.

Пользователь запускал составной прогон несколько раз и каждый раз видел полные
2670 сегментов. Причина была в Medical QA: она одна не помнила, к какому тексту
относится её результат, и потому забирала в работу весь проект. Здесь
проверяется, что второй прогон берёт только новое — и что одинаковые исходники
не оплачиваются дважды.

Вызовов модели нет: перевод подменён.
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


def seg(sid, source, target="", status="new"):
    return {"id": sid, "source": source, "target": target, "status": status, "risk": "medium"}


def build(segments):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


calls = []
main._openai_translate = lambda text, *a, **k: (calls.append(text), "EN: " + text)[1]


print("=== 1. Одинаковый исходник по всему проекту оплачивается один раз ===")
# Дедуп внутри порции ловит только соседей. Заголовок в сегментах 1 и 30
# попадает в РАЗНЫЕ порции — и раньше стоил двух вызовов.
proj = build([seg(1, "Заключение")] + [seg(i, "текст %d" % i) for i in range(2, 30)]
             + [seg(30, "Заключение")])
calls.clear()
main.batch_translate(1, main.BatchRequest(limit=10))      # порция 1: сегменты 1..10
first = list(calls)
check("Заключение" in first, "в первой порции заголовок переведён")
calls.clear()
main.batch_translate(1, main.BatchRequest(limit=100))     # остальные, включая 30-й
by = {s["id"]: s for s in proj["segments"]}
check("Заключение" not in calls, "во второй раз модель за него не вызывалась")
check(by[30]["target"] == by[1]["target"], "перевод взят у уже переведённого близнеца")
check(by[30]["route"] == "DUPLICATE", "и помечен как повтор: " + by[30]["route"])

print("\n=== 2. «Перевести заново» повторы не подставляет ===")
# force — это явная просьба перевести, и молча отдать старый текст нельзя.
calls.clear()
main.batch_translate(1, main.BatchRequest(segment_ids=[30], force=True, limit=10))
check("Заключение" in calls, "с force модель вызвана, а не подставлен близнец")

print("\n=== 3. Medical QA помнит, к какому тексту относится результат ===")


class FakeQA:
    def run_medical_qa(self, source, target, **kw):
        return {"literal_backcheck": {"backtranslated_ru": ""}, "qa_issues": [],
                "ui_issues": [], "term_candidates": [], "risk_score": 10,
                "risk_color": "green", "engine_qa": "test"}


main.medical_qa_mod = FakeQA()
main.medical_qa_enabled = lambda: True
proj = build([seg(1, "жалобы", "complaints", status="translated"),
              seg(2, "одышка", "dyspnea", status="translated")])
# Свежий back-check уже есть — так и бывает в составном прогоне, где он идёт
# раньше. Medical QA берёт из него обратный перевод и не платит за свой.
h = main._text_hash
for s0 in proj["segments"]:
    s0["backcheck"] = {"score": 95, "target_hash": h(s0["target"]), "back": "обратно"}
r = main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(r["count"] == 2, "первый прогон проверил оба сегмента")
r = main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(r["count"] == 0 and r["skipped_cached"] == 2,
      "второй прогон не делает ничего и говорит об этом: " + str(r["skipped_cached"]))

# Текст изменился — проверка снова нужна.
proj["segments"][0]["target"] = "complaints, revised"
proj["segments"][0]["backcheck"] = {"score": 95, "back": "обратно",
                                    "target_hash": h("complaints, revised")}
r = main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(r["count"] == 1, "изменённый сегмент проверяется заново")

print("\n=== 4. Именно из-за этого прогон брал весь проект ===")
# Состав составного прогона — объединение по шагам. Пока Medical QA забирала
# все переведённые сегменты, объединение равнялось проекту при любом числе
# прошлых прогонов.
proj = build([seg(i, "текст %d" % i, "EN %d" % i, status="translated")
              for i in range(1, 21)])
for s0 in proj["segments"]:
    s0["backcheck"] = {"score": 95, "target_hash": h(s0["target"]), "back": "обратно"}
    s0["termcheck"] = {"findings": [], "target_hash": h(s0["target"]), "model": "t"}
main.batch_medical_qa(1, main.MedicalQABatchRequest())
stale = [s for s in proj["segments"] if main._check_stale(s.get("qa_result"), s.get("target"))]
check(not stale, "после прогона к пересчёту не осталось ничего")

print("\n=== 5. Хеш сравнивается так же, как записывается ===")
# Перевод с висящим пробелом объявлялся устаревшим и оплачивался заново.
s5 = {"id": 1, "source": "жалобы", "target": "complaints  ", "status": "translated"}
s5["backcheck"] = {"score": 95, "target_hash": h("complaints"), "back": "..."}
check(not main._check_stale(s5["backcheck"], s5["target"]),
      "лишний пробел не делает свежую проверку устаревшей")

print("\n=== 6. Донором повтора не становится брак ===")
# failed — «не прошёл проверку, требует исправления». Копировать такой текст
# в близнецов значит размножить брак по всему документу.
proj = build([seg(1, "Заключение", "BAD", status="failed"), seg(2, "Заключение")])
calls.clear()
main.batch_translate(1, main.BatchRequest(limit=10))
check("Заключение" in calls, "модель вызвана — брак донором не стал")
check(proj["segments"][1]["target"] != "BAD", "и текст не скопирован")

print("\n=== 7. Донор — заверенный человеком, а не первый по порядку ===")
proj = build([seg(1, "Заключение", "МАШИННЫЙ", status="translated"),
              seg(2, "Заключение", "ЧЕЛОВЕЧЕСКИЙ", status="confirmed"),
              seg(3, "Заключение")])
proj["segments"][1]["confirmedBy"] = "human"
main.batch_translate(1, main.BatchRequest(limit=10))
check(proj["segments"][2]["target"] == "ЧЕЛОВЕЧЕСКИЙ",
      "взят заверенный, а не первый в документе: " + proj["segments"][2]["target"])

print("\n=== 8. Память переводов сильнее повтора внутри проекта ===")
# Запись памяти человек подтверждал; близнец в проекте мог быть переведён
# машиной и исправлен только в памяти.
proj = build([seg(1, "Заключение", "СТАРЫЙ", status="translated"), seg(2, "Заключение")])
main.STATE["tm"] = [{"src": "Заключение", "tgt": "ИЗ ПАМЯТИ",
                     "lang": "RU→EN", "quality": "verified"}]
main.batch_translate(1, main.BatchRequest(limit=10))
check(proj["segments"][1]["target"] == "ИЗ ПАМЯТИ", "подставлено из памяти")
check(proj["segments"][1]["route"] == "EXACT_TM", "и помечено как совпадение памяти")

print("\n=== 9. Порция из одних повторов работает без ключа модели ===")
key = os.environ.pop("OPENAI_API_KEY")
proj = build([seg(1, "Заключение", "ГОТОВО", status="translated"), seg(2, "Заключение")])
try:
    r = main.batch_translate(1, main.BatchRequest(limit=10))
    check(r["count"] == 1 and proj["segments"][1]["target"] == "ГОТОВО",
          "повтор подставлен, вызовов не потребовалось")
except main.HTTPException as e:
    check(False, "отказ там, где платить не за что: " + str(e.detail))
os.environ["OPENAI_API_KEY"] = key

print("\n=== 10. Неполная Medical QA не кэшируется ===")
# Без обратного перевода часть находок не считается вовсе. Закэшировать такой
# результат — закрыть сегмент от нормальной проверки навсегда.
proj = build([seg(1, "жалобы", "complaints", status="translated")])
main.batch_medical_qa(1, main.MedicalQABatchRequest(run_backcheck=False))
check(main._check_stale(proj["segments"][0].get("qa_result"), "complaints"),
      "результат без обратного перевода не помечен свежим")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
