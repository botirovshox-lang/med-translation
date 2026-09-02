# -*- coding: utf-8 -*-
"""Исправленный человеком термин извлекается на подтверждении сегмента.

Что здесь сторожится и почему это стоило заводить:
  1. база правки (`editedFrom`) живёт по ЦЕПОЧКЕ ХЕШЕЙ, а не по чистке во
     всех машинных путях записи: ремонт, пакетный перевод и undo пишут target
     мимо `_replace_target`, и забытая чистка приписала бы человеку правки
     машины;
  2. промпт строит НАСТОЯЩИЙ код (`_edit_terms_prompt`) — подменён только
     клиент OpenAI, по правилу из test_prompt_build.py;
  3. ответ модели — сырьё: src обязан найтись в оригинале (морфологией
     `_term_match` — модель отвечает словарной формой), tgt — в подтверждённом
     тексте; не нашлось — отсев со счётом, а не карточка с выдумкой;
  4. fail-open: нет ключа / исчерпан лимит / модель молчит — подтверждение
     работает, а причина уходит КОДОМ (`skipped`), не молча (инвариант 15;
     confirm в _PAID не входит намеренно);
  5. спор с ПРИКАЗНОЙ записью не глотается: пара уходит в `disputed`,
     карточка не заводится — приказ правится в самой записи;
  6. в глоссарий не пишется ничего (инвариант 8), карточка ждёт человека;
     повторное подтверждение той же пары растит hits, а не плодит карточки.

Ни одного платного вызова: клиент OpenAI подменён целиком.
"""
import json, os, sys, types

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"

SENT = {"calls": 0}
ANSWER = []


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
        SENT["calls"] += 1
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        SENT["model"] = model
        return FakeResp(json.dumps(ANSWER, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build():
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [
                {"id": 1, "source": "Туберкулемы часто выявляются случайно.",
                 "target": "", "status": "new", "risk": "medium"},
                # сосед, всё ещё несущий отвергнутый вариант — для wasTgtLeft
                {"id": 2, "source": "Другое предложение.",
                 "target": "The tuberculosis is visible on the film.",
                 "status": "translated", "risk": "medium"},
            ]}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": [], "audit": []}
    main._invalidate_gloss_index()
    return proj


def upd(sid, text):
    return main.update_segment(1, sid, main.UpdateSegmentRequest(target=text))


print("=== 1. База правки: цепочка хешей ===")
proj = build()
seg = proj["segments"][0]
seg["target"] = "The tuberculosis is dense."       # «машинный» текст
seg["status"] = "translated"
upd(1, "The tuberculoma is dense.")                # правка человека №1
check(seg.get("editedFrom") == "The tuberculosis is dense.",
      "база — текст до руки человека")
upd(1, "The tuberculoma is quite dense.")          # правка человека №2
check(seg.get("editedFrom") == "The tuberculosis is dense.",
      "вторая правка человека базу НЕ сдвигает")
seg["target"] = "Repair rewrote this."             # машина пишет мимо _replace_target
upd(1, "Repair rewrote this text.")                # человек правит снова
check(seg.get("editedFrom") == "Repair rewrote this.",
      "после машинной записи базой становится ЕЁ текст (цепочка хешей порвана)")
seg2 = build()["segments"][0]
upd(1, "Typed from scratch.")
check("editedFrom" not in seg2 or not seg2.get("editedFrom"),
      "перевод с нуля исправлением не считается")

print("=== 2. Подтверждение: настоящий промпт, валидация, карточка ===")
proj = build()
seg = proj["segments"][0]
seg["target"] = "The tuberculosis is dense."
seg["status"] = "translated"
upd(1, "The tuberculoma is dense.")
ANSWER[:] = [
    # законная пара: в оригинале «Туберкулемы» (косвенная форма!)
    {"src": "туберкулема", "tgt": "tuberculoma", "was": "tuberculosis"},
    # галлюцинация: термина нет в оригинале
    {"src": "печень", "tgt": "liver", "was": "kidney"},
    # перевода нет в подтверждённом тексте
    {"src": "туберкулема", "tgt": "granuloma", "was": "x"},
]
SENT["calls"] = 0
res = main.confirm_segment(1, 1)
eh = res["editHarvest"]
check(SENT["calls"] == 1, "ровно один вызов модели")
check("DRAFT" in SENT.get("system", "") and "FINAL" in SENT["system"],
      "промпт собран настоящим _edit_terms_prompt")
check("The tuberculosis is dense." in SENT.get("user", "")
      and "The tuberculoma is dense." in SENT["user"]
      and "Туберкулемы" in SENT["user"],
      "модели ушли база, итог и оригинал")
check([p["src"] for p in eh["pairs"]] == ["туберкулема"], "выучена одна пара")
check(eh["dropped"] == 2, "выдумка и несовпавший перевод отсеяны со счётом")
cards = [c for c in main.STATE["termQueue"] if c.get("kind") == "edit"]
check(len(cards) == 1, "в очереди одна edit-карточка")
c = cards[0] if cards else {}
check(c.get("via") == "confirmed" and c.get("wasTgt") == "tuberculosis",
      "карточка помнит, что решил человек и что стояло раньше")
check(c.get("tenant") and c.get("lang") and c.get("domain"),
      "область на карточке полная (инвариант 11)")
check((c.get("wasTgtLeft") or {}).get("count") == 1
      and (c.get("wasTgtLeft") or {}).get("ids") == [2],
      "охват: прежний вариант ещё в сегменте #2 этого проекта")
check(not main.STATE["glossary"], "в глоссарий не записано ничего (инвариант 8)")
check("editedFrom" not in seg and "editedToHash" not in seg,
      "база одноразовая: снята при подтверждении")

print("=== 3. Повтор растит hits, а не карточки ===")
seg["status"] = "translated"
seg["editedFrom"] = "The tuberculosis is dense."
seg["editedToHash"] = main._text_hash(seg["target"])
res2 = main.confirm_segment(1, 1)
cards = [c for c in main.STATE["termQueue"] if c.get("kind") == "edit"]
check(len(cards) == 1 and cards[0].get("hits", 1) == 2,
      "та же пара второй раз — hits 2, карточка одна")

print("=== 4. Мёртвая база: после правок человека писала машина ===")
proj = build()
seg = proj["segments"][0]
seg["target"] = "Machine one."
seg["status"] = "translated"
upd(1, "Human two.")
seg["target"] = "Machine three."     # машина перезаписала, editedToHash разошёлся
SENT["calls"] = 0
res = main.confirm_segment(1, 1)
check(SENT["calls"] == 0, "вызова модели нет — диф приписал бы человеку машину")
check(res["editHarvest"]["pairs"] == [] and res["editHarvest"]["skipped"] is None,
      "и это не «сбой», а честное «нечего разбирать»")

print("=== 5. Fail-open: ключ, лимит, сбой — подтверждение работает ===")
proj = build()
seg = proj["segments"][0]
seg["target"] = "Machine text one."
seg["status"] = "translated"
upd(1, "Human text one.")
key = os.environ.pop("OPENAI_API_KEY")
res = main.confirm_segment(1, 1)
os.environ["OPENAI_API_KEY"] = key
check(res["ok"] and res["editHarvest"]["skipped"] == "no_key",
      "нет ключа: подтверждено, причина кодом")
check("editedFrom" not in seg, "база снята и здесь — второй раз не покупаем")

proj = build()
seg = proj["segments"][0]
seg["target"] = "Machine text two."
seg["status"] = "translated"
upd(1, "Human text two.")
main.STATE["tenants"] = [{"id": main.DEFAULT_TENANT, "limitUsd": 1}]
main.STATE["spend"] = {main.DEFAULT_TENANT: {main._month_key(): {"usd": 2.0, "calls": 1, "unpriced": 0}}}
res = main.confirm_segment(1, 1)
check(res["ok"] and res["editHarvest"]["skipped"] == "limit",
      "исчерпан лимит: подтверждено, извлечение пропущено кодом (инвариант 15)")
main.STATE["tenants"] = []
main.STATE["spend"] = {}

proj = build()
seg = proj["segments"][0]
seg["target"] = "Machine text three."
seg["status"] = "translated"
upd(1, "Human text three.")
broken = main._openai_edit_terms
main._openai_edit_terms = lambda *a, **k: None
res = main.confirm_segment(1, 1)
main._openai_edit_terms = broken
check(res["ok"] and res["editHarvest"]["skipped"] == "error",
      "сбой вызова: подтверждено, причина кодом")

print("=== 6. Спор с приказной записью не глотается ===")
proj = build()
main.STATE["glossary"] = [{"src": "бактериовыделение", "tgt": "bacillary excretion",
                           "tier": "verified", "lang": "RU→EN", "domain": "medical"}]
main._invalidate_gloss_index()
seg = proj["segments"][0]
seg["source"] = "Бактериовыделение прекратилось."
seg["target"] = "Bacillary excretion stopped."
seg["status"] = "translated"
upd(1, "Bacteriological conversion stopped.")
ANSWER[:] = [{"src": "бактериовыделение", "tgt": "bacteriological conversion",
              "was": "bacillary excretion"}]
res = main.confirm_segment(1, 1)
eh = res["editHarvest"]
check(eh["disputed"] == [{"src": "бактериовыделение",
                          "tgt": "bacteriological conversion",
                          "gloss": "bacillary excretion"}],
      "расхождение с приказом названо вслух, а не съедено")
check(not [c for c in main.STATE["termQueue"] if c.get("kind") == "edit"],
      "карточка при этом не заводится: приказ правится в самой записи")

print("=== 7. Стилевая правка — не термин ===")
proj = build()
seg = proj["segments"][0]
seg["target"] = "The film shows a shadow."
seg["status"] = "translated"
upd(1, "A shadow is shown by the film.")
ANSWER[:] = []
res = main.confirm_segment(1, 1)
check(res["editHarvest"]["pairs"] == [] and not res["editHarvest"]["skipped"],
      "модель ответила []: пар нет, и это не сбой")

print("=== 8. Решение по карточке снимает срез охвата ===")
proj = build()
card = {"id": 1, "kind": "edit", "src": "а", "tgt": "b", "status": "pending",
        "wasTgtLeft": {"count": 3, "ids": [1, 2, 3]},
        "sampleSrc": "x", "sampleTgt": "y"}
main.STATE["termQueue"] = [card]
main._mark_decided(card, "approved")
check("wasTgtLeft" not in card and "sampleSrc" not in card,
      "решённая карточка легче ожидающей (потолок очереди — про state.json)")

print()
print("ПРОВАЛЕНО: %d" % len(fail) if fail else "ВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
