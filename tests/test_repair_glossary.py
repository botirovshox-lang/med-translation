"""Ремонт и соответствие глоссарию — одна работа, а не две конкурирующие.

Проверяем, что ремонт видит утверждённые термины: чинит по ним, не выбивает их,
пока чинит другое, и откатывается, если после правки нарушений стало больше.
STATE подменён, вызов модели подменён — платных прогонов тут нет.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


GLOSS = [
    {"src": "увеит", "tgt": "uveitis", "tier": "verified", "cat": "Disease",
     "lang": "RU→EN", "domain": "medical"},
    {"src": "жалобы", "tgt": "complaints", "tier": "verified", "cat": "Symptom",
     "lang": "RU→EN", "domain": "medical"},
    # Массовый автоимпорт: приказом не является, требовать соответствия нельзя.
    {"src": "задний", "tgt": "rear", "tier": "auto", "cat": "Anatomy",
     "lang": "RU→EN", "domain": "medical"},
]


def build(source, target, gloss=GLOSS, status="translated", bc=None, tc=None):
    seg = {"id": 1, "source": source, "target": target, "status": status}
    if bc is not None:
        seg["backcheck"] = {**bc, "target_hash": main._text_hash(target.strip())}
    if tc is not None:
        seg["termcheck"] = {**tc, "target_hash": main._text_hash(target.strip())}
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [seg]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj, seg


def repair_returns(text):
    """Подменяем вызов модели: ремонт не должен стоить денег в тестах."""
    main._openai_repair = lambda seg, project, findings, model: text


def termcheck_returns(findings=()):
    """Правка ради глоссария обязана перепроверяться termcheck'ом — значит
    и в тестах он должен отвечать, а не падать без ключа."""
    def fake(seg_, *a, **k):
        seg_["termcheck"] = {"findings": list(findings), "model": "test",
                             "target_hash": main._text_hash((seg_.get("target") or "").strip())}
        return {"ok": True}
    main._run_segment_termcheck = fake


termcheck_returns()


print("=== 1. Расхождение с глоссарием — повод чинить ===")
proj, seg = build("Жалобы на увеит.", "Complaints about eye inflammation.")
f = main._repair_findings(seg, proj)
check(len(f) == 1 and f[0]["kind"] == "gloss", "нарушенный утверждённый термин попал в находки")
check(f[0]["use"] == "uveitis", "в находке — утверждённый вариант перевода")
check(main._repairable(seg, project=proj), "сегмент стал кандидатом на ремонт")
check(not main._repairable(seg), "без проекта область неизвестна — находки нет")

print("\n=== 2. Автоимпорт приказом не считается ===")
proj, seg = build("Задний увеит.", "Posterior uveitis.")
check(not main._repair_findings(seg, proj),
      "запись tier=auto не делает сегмент сломанным")

print("\n=== 3. Ремонт подставляет утверждённый термин ===")
proj, seg = build("Жалобы на увеит.", "Complaints about eye inflammation.")
repair_returns("Complaints about uveitis.")
r = main._run_segment_repair(seg, proj)
check(r["ok"] and r["applied"], "правка принята")
check(seg["target"] == "Complaints about uveitis.", "новый текст с утверждённым термином")
check(seg["prevTarget"] == "Complaints about eye inflammation.", "прежний текст сохранён")
check(seg["status"] == "review", "статус «требует проверки»")
check(not main._gloss_misses(seg, proj), "расхождений с глоссарием не осталось")

print("\n=== 4. Правка, выбивающая утверждённый термин, откатывается ===")
proj, seg = build("Жалобы на увеит: 5 мг.", "Complaints about uveitis: 7 mg.",
                  bc={"score": 60, "reasons": ["расхождение чисел: 5 против 7"], "back": "..."})
before = main._repair_findings(seg, proj)
check([x["kind"] for x in before] == ["backcheck"], "чиним расхождение чисел, глоссарий цел")
# Модель чинит число, но заодно переписывает утверждённый термин.
repair_returns("Complaints about eye inflammation: 5 mg.")
main._run_segment_backcheck = lambda *a, **k: seg.__setitem__(
    "backcheck", {"score": 95, "reasons": [], "back": "...",
                  "target_hash": main._text_hash(seg["target"].strip())})
r = main._run_segment_repair(seg, proj)
check(r["ok"] and not r["applied"], "правка отвергнута, хотя back-check вырос")
check("утверждённых терминов" in r["repair"]["reason"], "причина названа: " + r["repair"]["reason"])
check(seg["target"] == "Complaints about uveitis: 7 mg.", "текст откачен целиком")
check(seg["backcheck"]["score"] == 60, "прежняя оценка back-check возвращена")

print("\n=== 5. Ремонт и отчёт о соответствии считают одинаково ===")
proj, seg = build("Жалобы на увеит.", "Complaints about eye inflammation.")
impact = main.glossary_impact(1)
mine = {f["src"] for f in main._gloss_misses(seg, proj)}
check(impact["segments"] == [1], "отчёт видит сегмент расходящимся")
check({t["src"] for t in impact["terms"]} == mine,
      "ремонт и отчёт называют одни и те же термины")
repair_returns("Complaints about uveitis.")
main._run_segment_repair(seg, proj)
check(main.glossary_impact(1, refresh=True)["segments"] == [],
      "после ремонта отчёту нечего переперевести — второй правки не будет")

print("\n=== 6. Сегмент без нарушений чинить нечего ===")
proj, seg = build("Жалобы на увеит.", "Complaints about uveitis.")
check(not main._repair_findings(seg, proj), "соответствующий глоссарию перевод не трогаем")
r = main._run_segment_repair(seg, proj)
check(not r["ok"] and "Нет находок" in r["error"], "ремонт честно отказывается работать")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
