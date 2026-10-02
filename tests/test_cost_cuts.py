"""Экономия вызовов без потери качества (28.09.2026):

  • `reasoning_effort` шага у OpenAI «modern» добавляет ОДИН шим (`_OpenAIChat`),
    только по таблице `STEP_REASONING`/окружению, только у «modern»; отказ
    поставщика (400 с именем параметра) — повтор без него, пара запоминается;
    отметка `effort` ложится в запись termcheck;
  • ревизия по терм-листу перекупается ТОЧЕЧНО — только строки с изменившимся
    термином, своей меткой `termlistStale`;
  • одинаковая пара «оригинал + перевод» у termcheck и back-check копируется
    ПО ВСЕМУ проекту, с условиями: донор годен тем же предикатом, что закрывает
    строку от прогона; у back-check — модель донора не равна переводчику
    получателя и ни у кого нет свежего вердикта арбитра.
"""
import json
import os
import sys
import types

SENT = []
FAIL_ON = {"n": 0}          # сколько первых вызовов с reasoning_effort отвергнуть


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=text),
                                              finish_reason="stop")]
        self.usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        SENT.append({"model": model, "kw": dict(kw)})
        if "reasoning_effort" in kw and FAIL_ON["n"] > 0:
            FAIL_ON["n"] -= 1
            raise RuntimeError("Error code: 400 - Unsupported value: 'reasoning_effort' does not support 'none'")
        return FakeResp(json.dumps({"findings": []}))


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


def call(step, model):
    SENT.clear()
    c = main._llm_client(model, timeout=10, step=step, max_retries=0)
    c.chat.completions.create(model=model, messages=[{"role": "user", "content": "x"}],
                              max_completion_tokens=100)
    return c


print("=== 1. reasoning_effort — только по таблице и только у modern ===")
main._REASONING_REJECTED.clear()
c = call("termcheck", "gpt-5.6-terra")
check(SENT[-1]["kw"].get("reasoning_effort") == "none" and c.effort_sent == "none",
      "termcheck на gpt-5.6: reasoning_effort=none")
call("review", "gpt-5.6-terra")
check("reasoning_effort" not in SENT[-1]["kw"], "ревизия — параметра нет (не в таблице)")
call("termcheck", "gpt-4o")
check("reasoning_effort" not in SENT[-1]["kw"], "classic-модель — параметра нет")
os.environ["REASONING_TERMCHECK"] = "low"
call("termcheck", "gpt-5.6-terra")
check(SENT[-1]["kw"].get("reasoning_effort") == "low", "окружение перекрывает таблицу")
os.environ["REASONING_TERMCHECK"] = "default"
call("termcheck", "gpt-5.6-terra")
check("reasoning_effort" not in SENT[-1]["kw"], "«default» в окружении — не слать")
del os.environ["REASONING_TERMCHECK"]
check(main._step_reasoning("termcheck") == "none" and main._step_reasoning(None) is None,
      "чтение таблицы: termcheck → none, без шага → нет")

print("\n=== 2. Отказ поставщика — повтор без параметра, пара запомнена ===")
main._REASONING_REJECTED.clear()
FAIL_ON["n"] = 1
c = call("termcheck", "gpt-5.6-terra")
check(len(SENT) == 2 and "reasoning_effort" in SENT[0]["kw"] and "reasoning_effort" not in SENT[1]["kw"],
      "400 с именем параметра → второй вызов без него")
check(c.effort_sent is None, "effort_sent пуст: параметр не доехал")
call("termcheck", "gpt-5.6-terra")
check(len(SENT) == 1 and "reasoning_effort" not in SENT[0]["kw"], "дальше — сразу без параметра")
main._REASONING_REJECTED.clear()
FAIL_ON["n"] = 1
SENT.clear()
try:
    c = main._llm_client("gpt-5.6-terra", timeout=10, step="termcheck", max_retries=0)
    c.chat.completions.create(model="gpt-5.6-terra", messages=[{"role": "user", "content": "x"}])
    raised = False
except RuntimeError:
    raised = True
check(not raised, "ошибка про reasoning_effort не всплывает наружу")
FAIL_ON["n"] = 0

print("\n=== 3. Отметка effort в записи termcheck ===")
main._REASONING_REJECTED.clear()
main.STATE.update({"projects": [{"id": 1, "title": "t", "src": "RU", "tgt": "EN", "domain": "medical",
                                "segments": [{"id": 1, "source": "Кашель.", "target": "Cough.", "status": "translated"}]}],
                   "glossary": [], "tm": [], "termQueue": []})
proj = main.STATE["projects"][0]
main._invalidate_gloss_index()
r = main._run_segment_termcheck(proj["segments"][0], proj, "gpt-5.6-terra")
check(r["ok"] and proj["segments"][0]["termcheck"].get("effort") == "none",
      "запись termcheck несёт effort=none")
check(main._termcheck_cached(proj["segments"][0], "gpt-5.6-terra"), "и по рангу она свежая, как прежде")

print("\n=== 4. Ревизия по терм-листу устаревает точечно ===")
segs = [{"id": i, "source": s, "target": "t%d" % i, "status": "translated"} for i, s in enumerate(
    ["Фтизиатрия изучает туберкулёз.", "Плевра воспалена.", "Обычная фраза без терминов."], 1)]
for sg in segs:
    sg["review"] = {"v": main.REVIEW_VERSION, "score": 9, "target_hash": main._text_hash(sg["target"]),
                    "source_hash": main._text_hash(sg["source"]), "applied": False}
proj2 = {"id": 2, "title": "b", "src": "RU", "tgt": "EN", "domain": "general", "fileName": "b.docx",
         "segments": segs,
         "termlist": {"use": True, "entries": [
             {"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "agreed", "by": "human"},
             {"src": "Плевра", "tgt": "Pleura", "status": "agreed", "by": "human"}]}}
main.STATE["projects"].append(proj2)
main._TERMLIST_INDEX.pop(2, None)
n = main._reviews_mark_stale(proj2, ["Плевра"])
check(n == 1 and segs[1]["review"].get("termlistStale") and not segs[0]["review"].get("termlistStale")
      and not segs[2]["review"].get("termlistStale"), "помечена только строка с этим термином (%s)" % n)
check(main._review_stale(segs[1]) and not main._review_stale(segs[0]), "и только она устарела")
check(main._reviews_mark_stale(proj2, []) == 0, "пустой список терминов — ничего")
n = main._reviews_mark_stale(proj2)
check(n == 2 and segs[0]["review"].get("styleStale") and segs[2]["review"].get("styleStale"),
      "без списка — весь файл, своей меткой (стайл-шит)")
for sg in segs:
    sg["review"].pop("styleStale", None); sg["review"].pop("termlistStale", None)
main.CURRENT_SESSION.set({"tenant": "default", "user": 1, "role": "owner", "super": True})
r = main.set_termlist(2, main.TermlistBody(decisions=[{"src": "Плевра", "tgt": "Pleura", "status": "rejected"}]))
check(r["reviewsStale"] == 1 and segs[1]["review"].get("termlistStale") and not segs[0]["review"].get("termlistStale"),
      "отклонение пары устаревает ревизию только её строк (%s)" % r["reviewsStale"])
plan_reason = None
for sg in segs:
    sg["review"].pop("termlistStale", None)
r = main.set_termlist(2, main.TermlistBody(use=False))
check(r["reviewsStale"] == 1 and segs[0]["review"].get("termlistStale"),
      "выключение листа — устаревают строки с оставшимися парами, не третья (%s)" % r["reviewsStale"])
check(not segs[2]["review"].get("termlistStale") and not segs[2]["review"].get("styleStale"),
      "строка без терминов не перекупается")

print("\n=== 5. Дедуп по проекту ===")
h = main._text_hash
segs3 = [{"id": 1, "source": "Глава 1", "target": "Chapter 1", "status": "translated", "provider": "gpt-4o",
          "termcheck": {"findings": [], "severity": "none", "model": "gpt-5.6-terra", "target_hash": h("Chapter 1")},
          "backcheck": {"score": 95, "model": "gpt-5.6-luna", "target_hash": h("Chapter 1"), "back": "Глава 1"}},
         {"id": 2, "source": "Текст.", "target": "Text.", "status": "translated", "provider": "gpt-4o"},
         {"id": 3, "source": "Глава 1", "target": "Chapter 1", "status": "translated", "provider": "gpt-4o"},
         {"id": 4, "source": "Глава 1", "target": "Chapter 1", "status": "translated", "provider": "gpt-5.6-luna"},
         {"id": 5, "source": "Глава 1", "target": "Chapter 1", "status": "translated", "provider": "gpt-4o",
          "termContext": {"target_hash": h("Chapter 1"), "version": main.TERM_CONTEXT_VERSION, "all_terms": True}}]
proj3 = {"id": 3, "title": "c", "src": "RU", "tgt": "EN", "domain": "general", "segments": segs3}
main.STATE["projects"].append(proj3)
CALLS = []
main._openai_termcheck = lambda src, tgt, sl, tl, dom, mdl: CALLS.append(src) or {"findings": [], "model": "gpt-5.6-terra"}
res = main.termcheck_batch(3, main.TermcheckBatchRequest(limit=100, model="gpt-5.6-terra"))
check(res["duplicates"] == 3 and CALLS == ["Текст."],
      "termcheck: три повтора «Глава 1» скопированы от донора, вызов — один на «Текст.» (%s)" % CALLS)
check(res["count"] == 4 and all(segs3[i]["termcheck"]["model"] == "gpt-5.6-terra" for i in (2, 3, 4)),
      "count — все четыре, копии несут настоящий id модели")
BC = []
main._run_segment_backcheck = lambda seg, project, *a, **k: BC.append(seg["id"]) or (
    seg.__setitem__("backcheck", {"score": 90, "model": "gpt-5.6-luna", "target_hash": h(seg["target"]), "back": "x"})
    or {"ok": True})
res = main.backcheck_batch(3, main.BackcheckBatchRequest(limit=100, model="gpt-5.6-luna"))
check(3 not in BC and segs3[2]["backcheck"]["score"] == 95,
      "back-check: повтор с другим переводчиком скопирован от донора")
check(4 in BC, "получатель, чей переводчик — модель донора, зовёт свой вызов")
check(5 in BC, "получатель со свежим вердиктом арбитра — свой вызов")
check(2 in BC and res["duplicates"] == 1, "остальное — как было (дублей: %s)" % res["duplicates"])

print("\n=== 6. skip_cached=False — «перепроверить всё», копий нет ===")
CALLS.clear()
res = main.termcheck_batch(3, main.TermcheckBatchRequest(limit=100, model="gpt-5.6-terra", skip_cached=False))
check(res["duplicates"] == 3 and sorted(CALLS) == ["Глава 1", "Текст."],
      "termcheck без skip_cached: по проекту не копирует, повторы только внутри порции (%s)" % CALLS)
BC.clear()
for sg in segs3:
    sg.pop("termContext", None)
res = main.backcheck_batch(3, main.BackcheckBatchRequest(limit=100, model="gpt-5.6-luna", skip_cached=False))
check(res["duplicates"] >= 1 and all(i in BC for i in (1, 2)) and 3 not in BC,
      "back-check без skip_cached: донор не ищется, близнецы делят вызов ведущего (%s, дублей %s)"
      % (BC, res["duplicates"]))
check(4 in BC, "близнец, чей переводчик — модель проверки ведущего, идёт своим вызовом (запасной моделью)")

print("\n=== 7. effort — маркер поставщика, наружу не уходит ===")
main.CURRENT_SESSION.set({"tenant": "default", "user": 2, "role": "owner", "super": False})
tc_out = main._segment_for_client(proj["segments"][0], proj).get("termcheck") or {}
check("effort" not in tc_out and "effort" in proj["segments"][0]["termcheck"],
      "владельцу effort не отдаётся, в данных остаётся")
check("effort" not in main._verdict_public(proj["segments"][0]["termcheck"]), "и одиночная выдача его режет")
main.CURRENT_SESSION.set({"tenant": "default", "user": 1, "role": "owner", "super": True})
check(main._segment_for_client(proj["segments"][0], proj)["termcheck"].get("effort") == "none",
      "суперпользователю — виден")

print("\n=== 8. Точечная пометка у проекта без src/tgt ===")
proj4 = {"id": 4, "title": "d", "domain": "general", "fileName": "d.docx",
         "segments": [{"id": 1, "source": "Формы туберкулёза лёгких.", "target": "x", "status": "translated",
                       "review": {"v": main.REVIEW_VERSION, "score": 9, "target_hash": h("x"),
                                  "source_hash": h("Формы туберкулёза лёгких."), "applied": False}}],
         "termlist": {"use": True, "entries": [{"src": "туберкулёз", "tgt": "tuberculosis",
                                                "status": "agreed", "by": "human"}]}}
check(main._reviews_mark_stale(proj4, ["туберкулёз"]) == 1,
      "у проекта без src термин в косвенном падеже находится (язык — как у записей листа)")

print("\n" + ("ВСЕ ПРОВЕРКИ ПРОШЛИ" if not fail else "ПРОВАЛЕНО: %d" % len(fail)))
sys.exit(1 if fail else 0)
