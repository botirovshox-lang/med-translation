"""Откат ремонта: что остаётся в сегменте, когда правку отвергли.

Ремонт переписывает текст, перепроверяет его теми же проверками и откатывает,
если оценка не выросла. Откат обязан вернуть сегмент ровно в то состояние,
в котором его застали, — иначе на восстановленном тексте остаются следы
выброшенного варианта:

  1. проверка отвергнутого текста, оставшаяся на сегменте, — это находка про
     слова, которых в сегменте нет. Её видит человек на экране, по ней ремонт
     заходит на сегмент второй раз, а Medical QA берёт обратный перевод текста,
     которого больше не существует. Случай не редкий: расхождение с глоссарием
     заказывает termcheck сегменту, который termcheck ни разу не видел, —
     и тогда «прежней проверки» просто нет;
  2. расхождение текста с записью о решении не должно проходить молча:
     по этим записям считается «откачено N» и решается, чинить ли сегмент
     заново.

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


GLOSS = [{"src": "задний циклит", "tgt": "posterior cyclitis", "tier": "verified",
          "cat": "Disease", "lang": "RU→EN", "domain": "medical"}]
OLD = "Complaints about rear cyclitis."
NEW = "Complaints about posterior cyclitis."


def build(target=OLD, bc=None, tc=None):
    seg = {"id": 1, "source": "Жалобы на задний циклит.", "target": target,
           "status": "translated"}
    if bc:
        seg["backcheck"] = dict(bc, target_hash=main._text_hash(target))
    if tc:
        seg["termcheck"] = dict(tc, target_hash=main._text_hash(target))
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [seg]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in GLOSS],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj, seg


def termcheck_returns(findings, at="2026-08-22 18:39"):
    """Подменяем перепроверку терминов: она решает судьбу правки."""
    def fake(s, p, *a, **k):
        s["termcheck"] = {"model": "gpt-5.6-terra", "at": at,
                          "target_hash": main._text_hash(s["target"] or ""),
                          "findings": [dict(f) for f in findings]}
        return {"ok": True}
    main._run_segment_termcheck = fake


# Забракованный подставленный термин — правку отвергают даже без прежней
# проверки: за то, что подставили сами, отвечаем мы.
REJECT = [{"tgt_term": "posterior cyclitis", "severity": "critical", "why": "забраковано"}]
CLEAN = []


# ─────────── 1. Откат снимает проверку, которой до ремонта не было ───────────
print("=== 1. Прежней проверки не было — свежая не остаётся ===")
proj, seg = build()
main._openai_repair = lambda *a, **k: NEW
termcheck_returns(REJECT)
check([f["kind"] for f in main._repair_findings(seg, proj)] == ["gloss"],
      "чинить есть что: перевод расходится с утверждённым термином")
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "правку отвергли: подставленный термин забракован")
check(seg["target"] == OLD, "текст вернулся к прежнему")
check(seg.get("termcheck") is None,
      "termcheck отвергнутого текста снят, а не оставлен на восстановленном")
check(not r.get("desync"), "текст и запись о решении сходятся")

# ─────────── 2. Прежняя проверка была — возвращается именно она ───────────
print("\n=== 2. Прежняя проверка была — возвращается она, а не свежая ===")
proj, seg = build(tc={"model": "gpt-5.6-terra", "at": "2026-08-22 10:00",
                      "findings": [{"tgt_term": "rear cyclitis", "severity": "major",
                                    "why": "калька"}]})
main._openai_repair = lambda *a, **k: NEW
# Замечаний стало больше, чем было (1 → 2) — только так правка отвергается:
# соответствие глоссарию она починила, и по одной этой оценке была бы принята.
termcheck_returns([{"tgt_term": "posterior cyclitis", "severity": "critical", "why": "хуже"},
                   {"tgt_term": "Complaints", "severity": "major", "why": "и ещё хуже"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "правку отвергли: замечаний по терминам стало больше")
check(seg["target"] == OLD, "текст вернулся к прежнему")
tc = seg.get("termcheck") or {}
check(tc.get("at") == "2026-08-22 10:00", "вернулась проверка прежнего текста")
check(tc.get("target_hash") == main._text_hash(seg["target"]),
      "и её хеш описывает тот текст, который лежит в сегменте")
check((tc.get("findings") or [{}])[0].get("tgt_term") == "rear cyclitis",
      "находка снова про слова, которые в сегменте действительно есть")

# ─────────── 3. То же правило для back-check ───────────
print("\n=== 3. Back-check отвергнутого текста тоже не остаётся ===")
proj, seg = build(bc={"score": 45, "model": "gpt-5.6-luna", "back": "Жалобы на задний циклит.",
                      "reasons": ["термин потерян"], "terms_lost": ["циклит"]})


def fake_bc_worse(s, p, *a, **k):
    s["backcheck"] = {"score": 20, "model": "gpt-5.6-luna", "back": "обратный перевод НОВОГО",
                      "target_hash": main._text_hash(s["target"] or ""), "reasons": []}
    return {"ok": True}


main._run_segment_backcheck = fake_bc_worse
termcheck_returns(CLEAN)
main._openai_repair = lambda *a, **k: NEW
main._run_segment_repair(seg, proj)
bc = seg.get("backcheck") or {}
check(seg["target"] == OLD, "текст вернулся")
check(bc.get("score") == 45, "балл вернулся к прежнему, а не остался от отвергнутого")
check(bc.get("back") == "Жалобы на задний циклит.",
      "обратный перевод описывает текущий текст: его переиспользует Medical QA")

# ─────────── 4. Применённая правка проверок не теряет ───────────
print("\n=== 4. Правку приняли — возврата нет ===")
proj, seg = build(bc={"score": 45, "model": "gpt-5.6-luna", "back": "плохо",
                      "reasons": ["термин потерян"], "terms_lost": ["циклит"]})


def fake_bc_better(s, p, *a, **k):
    s["backcheck"] = {"score": 90, "model": "gpt-5.6-luna", "back": "Жалобы на задний циклит.",
                      "target_hash": main._text_hash(s["target"] or ""), "reasons": []}
    return {"ok": True}


main._run_segment_backcheck = fake_bc_better
termcheck_returns(CLEAN)
main._openai_repair = lambda *a, **k: NEW
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True, "оценка выросла — правку приняли")
check(seg["target"] == NEW, "в сегменте новый текст")
check(seg.get("backcheck", {}).get("score") == 90, "и свежая проверка при нём")
check(seg["repair"]["source_hash"] == main._text_hash(seg["target"]),
      "запись о ремонте описывает тот текст, что лежит в сегменте")
check(seg.get("status") == "review", "автоправка себя не заверяет")
check(not r.get("desync"), "расхождения нет")

# ─────────── 5. Расхождение текста с записью не проходит молча ───────────
print("\n=== 5. Расхождение называется вслух ===")
proj, seg = build()
check(main._repair_desync(seg, OLD) is False, "совпало — молчим")
check(main._repair_desync(seg, NEW) is True,
      "разошлось — сказали (в журнале сегмент и оба текста)")

# ─────────── 6. Потолок очереди кандидатов считается, а не только пишется ───────────
print("\n=== 6. Выброшенные кандидаты пересчитаны ===")
main.STATE = {"projects": [], "glossary": [], "tm": [], "termQueue": [],
              "exportHistory": [], "team": [], "autoBatches": []}
before = main._TERM_DROPPED["total"]
# Очередь заполняем машинным урожаем: именно он и подрезается.
for i in range(main.TERM_QUEUE_MAX + 40):
    main._queue_term("segment", "термин %d" % i, "term %d" % i, via="auto",
                     lang="RU→EN", domain="medical")
dropped = main._TERM_DROPPED["total"] - before
check(len(main._term_queue()) <= main.TERM_QUEUE_MAX,
      "очередь не переросла потолок (%d)" % main.TERM_QUEUE_MAX)
check(dropped >= 40,
      "выброшенные посчитаны (%d), а не только упомянуты в журнале по одному" % dropped)

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
