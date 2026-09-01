"""Забракованное слово в тексте: арбитр даёт ВТОРОЙ голос внутри шага сверки.

Из-за чего написано. Карточка очереди помнит `wasTgt` — слово, которое termcheck
отверг, — и на боевом проекте 124 таких сегмента висели в «нужен человек»:
одно суждение termcheck переписывать не приказывает (закон двух голосов, как
у разнобоя), и претензия ничем не кончалась. Второй голос теперь даёт арбитр
внутри штатного шага «Сверка терминов»: «негодно» — находка ремонта в том же
прогоне, «годно» — претензия снята. Ни новой кнопки, ни нового шага.

Правила:
  1. один расчёт слов на три места (_stale_words_of): /analysis, _plan_step,
     сам шаг — смета и работа видят один список;
  2. слово, которое САМО есть утверждённый перевод, арбитру не задаётся —
     это спор с ЗАПИСЬЮ (human.termcheckDisputes), его решает человек;
  3. охват лежит на вердикте (staleAsked) и покрывает только ОТВЕЧЕННЫЕ
     слова: пропущенное моделью спрашивается снова;
  4. секция в промпте появляется ТОЛЬКО при забракованных словах — для
     остальных сегментов промпт байт в байт прежний, и TERM_CONTEXT_VERSION
     не поднимается (подъём перекупил бы сотни готовых вердиктов);
  5. вердикт «негодно» — находка kind term_ctx с заменой; «годно» убирает
     сегмент из human.staleFindings;
  6. свежий вердикт разбора СПОРА не закрывает сегмент от полной сверки
     в самом шаге (охват all_terms проверяет и эндпоинт, не только смета).

Сеть не трогается: подменён клиент OpenAI, как в test_prompt_build.py.
"""
import json, os, sys, types

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"

SENT = {}
ANSWER = {"terms": []}


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(
            message=types.SimpleNamespace(content=text))]
        self.usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                           total_tokens=15)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        return FakeResp(json.dumps(ANSWER, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
main._corpus_check = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


SRC = "Биоптат исследуют у больного при подозрении на туберкулёз."
TGT = "The bioptate is examined in the patient with suspected tuberculosis."
GLOSS = [{"src": "больной", "tgt": "patient", "tier": "verified", "cat": "Term",
          "lang": "RU→EN", "domain": "medical"}]


def project_of(queue=()):
    seg = {"id": 1, "source": SRC, "target": TGT, "status": "translated"}
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [seg]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in GLOSS],
                  "tm": [], "termQueue": [dict(c) for c in queue],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    main._IMPACT_CACHE.clear()
    return proj, seg


CARD = {"id": 7, "kind": "audit", "src": "биоптат", "tgt": "biopsy specimen",
        "wasTgt": "bioptate", "project": 1, "segment": 1, "status": "pending",
        "lang": "RU→EN", "domain": "medical"}
# Слово-приказ: спор с записью, арбитру не задаётся.
CARD_VS = {"id": 8, "kind": "audit", "src": "больной", "tgt": "sick person",
           "wasTgt": "patient", "project": 1, "segment": 1, "status": "pending",
           "lang": "RU→EN", "domain": "medical"}

print("(1) один расчёт слов, спор с записью отфильтрован")
proj, seg = project_of(queue=[CARD, CARD_VS])
words = main._stale_words_of(proj)
check(words == {1: ["bioptate", "patient"]}, "слова найдены по границам слов")
check(main._stale_unasked(seg, words[1]) == ["bioptate", "patient"],
      "без вердикта не спрошено ничего")

print("(2) промпт: секция появляется только при забракованных словах")
ANSWER["terms"] = [
    {"src": "больной", "ok": True, "use": "", "why": ""},
    {"src": "bioptate", "ok": False, "use": "biopsy specimen", "why": "калька"},
]
r = main._run_segment_term_context(seg, proj, "gpt-5.6-terra",
                                   disputes_only=False,
                                   stale_words=words[1])
check(r["ok"], "арбитр отработал")
check("Забракованные проверкой слова" in SENT["user"]
      and "- bioptate" in SENT["user"],
      "секция слов в теле запроса")
check("patient" not in SENT["user"].split("Забракованные")[1],
      "слово-приказный-перевод арбитру не задаётся")
tcx = seg["termContext"]
check(tcx.get("staleAsked") == ["bioptate"], "охват — только отвеченные слова")
stale_items = [t for t in tcx["terms"] if t.get("stale")]
check(len(stale_items) == 1 and stale_items[0]["ok"] is False
      and stale_items[0]["use"] == "biopsy specimen",
      "вердикт «негодно» с заменой записан")

print("(3) «негодно» — находка ремонта, из human уходит")
kinds = {f["kind"]: f for f in main._repair_findings(seg)}
check("term_ctx" in kinds and kinds["term_ctx"].get("replace") == ["bioptate", "biopsy specimen"],
      "находка с заменой для ремонта — без проекта, по самому сегменту")
a = main.project_analysis(1, refresh=True)
# «bioptate» снят вердиктом; «patient» — спор с ЗАПИСЬЮ, его арбитру не задают,
# и претензия остаётся человеку. Сегмент из human не уходит, но слово — одно.
sw = {w["id"]: w["words"] for w in a["human"]["staleFindingWords"]}
check(sw.get(1) == ["patient"],
      "отвеченное слово снято, спор с записью остался человеку")
check(1 in a["todo"]["findings"], "сегмент ушёл в находки — его возьмёт прогон")

print("(4) «годно» снимает претензию без находки")
proj, seg = project_of(queue=[CARD])
ANSWER["terms"] = [{"src": "bioptate", "ok": True, "use": "", "why": "уместно"}]
main._run_segment_term_context(seg, proj, "gpt-5.6-terra", disputes_only=False,
                               stale_words=["bioptate"])
check(not [f for f in main._repair_findings(seg) if f["kind"] == "term_ctx"],
      "находки нет")
a = main.project_analysis(1, refresh=True)
check(a["human"]["staleFindings"] == [], "и человека не зовут")
check([w["src"] for w in a["human"]["termContextWrong"]] == [],
      "вердикт по слову не путается со спором о записи глоссария")

print("(5) без забракованных слов промпт прежний — версия не поднимается")
proj, seg = project_of()
ANSWER["terms"] = [{"src": "больной", "ok": True, "use": "", "why": ""}]
main._run_segment_term_context(seg, proj, "gpt-5.6-terra", disputes_only=False)
check("Забракован" not in SENT["system"] and "Забракован" not in SENT["user"],
      "ни секции, ни инструкции — байт в байт прежний промпт")

print("(6) смета и шаг видят одно: неспрошенное слово берётся, спрошенное нет")
proj, seg = project_of(queue=[CARD])
plan = main._plan_step(proj, "termaudit", {}, proj["segments"], set(), set())
check(plan["count"] == 1, "шаг берёт сегмент")
ANSWER["terms"] = [{"src": "bioptate", "ok": True, "use": "", "why": ""}]
main._run_segment_term_context(seg, proj, "gpt-5.6-terra", disputes_only=False,
                               stale_words=["bioptate"])
plan2 = main._plan_step(proj, "termaudit", {}, proj["segments"], set(), set())
check(any("уже сверен" in s["reason"] for s in plan2["skips"]),
      "после ответа сегмент закрыт")
r = main.term_context(1, main.TermContextRequest(all_terms=True))
check(r["cachedSkipped"] == 1 and r["asked"] == 0,
      "эндпоинт согласен со сметой: сегмент покрыт")

print("(7) вердикт разбора СПОРА не закрывает сегмент от полной сверки")
proj, seg = project_of(queue=[CARD])
# Спор для точечного разбора: приказный термин не пережил обратный перевод.
seg["backcheck"] = {"score": 70, "model": "m", "back": "b", "reasons": [],
                    "terms_lost": ["больной"],
                    "target_hash": main._text_hash(TGT.strip())}
ANSWER["terms"] = [{"src": "больной", "ok": True, "use": "", "why": ""}]
main._run_segment_term_context(seg, proj, "gpt-5.6-terra", disputes_only=True)
check(seg["termContext"].get("all_terms") is False, "вердикт помнит охват")
r = main.term_context(1, main.TermContextRequest(all_terms=True))
check(r["asked"] == 1,
      "полная сверка сегмент берёт — прежде эндпоинт молча пропускал его")

print()
print("FAIL: %d" % len(fail) if fail else "ВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
