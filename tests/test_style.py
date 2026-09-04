"""Стайл-шит документа: слои, блок промпта (пусто = промпт байт в байт
прежний), орфографический вариант, аббревиатуры, устаревание ревизии.

Запуск: python tests/test_style.py
"""
import os, sys, types

os.environ.setdefault("APP_PASSWORD", "x")
sys.path.insert(0, "backend")
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=lambda *a, **k: None)
import main

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build(tgt="EN", style=None, org_style=None, domain="medical", segments=None):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": tgt, "domain": domain, "tenant": "default",
            "segments": segments or [{"id": 1, "source": "Опухоль.", "target": "The tumour.", "status": "review"}]}
    if style is not None:
        proj["style"] = style
    main.STATE = {"projects": [proj], "glossary": [], "termQueue": [], "tm": [],
                  "tenants": [{"id": "default", "name": "d", **({"style": org_style} if org_style else {})}]}
    main._invalidate_gloss_index()
    return proj


print("=== 1. слои и действующие поля ===")
p = build()
check(main._style_effective(p) is None and main._style_block(p) == "",
      "без стайл-шита блок пуст и действующих полей нет")
p = build(style={})
eff = main._style_effective(p)
check(eff["preset"] == "ama" and eff["spelling"] == "US" and eff["abbreviations"] == "expand_first",
      "медицина + EN: встроенный пресет AMA: %s" % eff)
p = build(style={}, org_style={"preset": "nature"})
check(main._style_effective(p)["spelling"] == "UK", "пресет организации сильнее встроенного")
p = build(style={"spelling": "US"}, org_style={"preset": "nature"})
check(main._style_effective(p)["spelling"] == "US" and main._style_effective(p)["preset"] == "nature",
      "явное поле проекта сильнее пресета организации")
p = build(tgt="DE", style={"spelling": "UK"})
check(main._style_effective(p)["spelling"] == "", "орфографический вариант есть только у EN")
check("STYLE SHEET" in main._style_block(build(style={})) and "American English" in main._style_block(build(style={})),
      "блок промпта назван и несёт орфографию")

print("=== 2. промпты: пусто = байт в байт прежний ===")
dom = main._resolve_domain("medical")
mdl = main._resolve_model(None)
base = main._translate_system("RU", "EN", [], {}, False, "medical", mdl)
check(base == main._translate_system("RU", "EN", [], {}, False, "medical", mdl, style=""),
      "перевод: без стайл-шита промпт не изменился")
blk = main._style_block(build(style={}))
check("STYLE SHEET" in main._translate_system("RU", "EN", [], {}, False, "medical", mdl, style=blk),
      "перевод: блок уезжает в промпт")
check("STYLE SHEET" not in main._translate_system("RU", "EN", [], {}, True, "medical", mdl, style=blk),
      "обратный перевод блока не получает НИКОГДА")
check(main._review_system(dom, "RU", "EN") == main._review_system(dom, "RU", "EN", ""),
      "ревизия: без стайл-шита промпт не изменился")
check("STYLE SHEET" in main._review_system(dom, "RU", "EN", blk), "ревизия: блок уезжает в промпт")
check(main._repair_system(dom, "RU", "EN") == main._repair_system(dom, "RU", "EN", ""),
      "ремонт: без стайл-шита промпт не изменился")
check("STYLE SHEET" in main._repair_system(dom, "RU", "EN", blk), "ремонт: блок уезжает в промпт")

print("=== 3. орфография ===")
new, ch = main._spelling_fix("The tumour was analysed; the organisation randomised patients with anaemia.", "US")
check(new == "The tumor was analyzed; the organization randomized patients with anemia.",
      "UK → US: %s" % new)
check(len(ch) == 5, "пять замен названы: %s" % ch)
same = "The organism in the literature; analysis of the parameter and programme."
check(main._spelling_fix(same, "US")[0] == same, "organism, literature, analysis, parameter не тронуты")
check(main._spelling_fix("Tumours and HAEMOGLOBIN levels", "US")[0] == "Tumors and HEMOGLOBIN levels",
      "начертание сохраняется: заглавная и капс")
check(main._spelling_fix("analyzing the color of the center", "UK")[0] == "analysing the colour of the centre",
      "US → UK работает в обратную сторону")
check(main._spelling_fix("centered", "UK")[0] == "centered", "«centered» не становится «centreed»: хвост закрыт")
check(main._spelling_fix("anything", "RU") == ("anything", []), "неизвестный вариант — ничего не делаем")

print("=== 4. аббревиатуры ===")
p = build(style={}, segments=[
    {"id": 1, "source": "a", "target": "CLINICAL FORMS OF TUBERCULOSIS", "status": "review"},
    {"id": 2, "source": "b", "target": "Multidrug-resistant tuberculosis (MDR-TB) is common.", "status": "review"},
    {"id": 3, "source": "c", "target": "XDR patients need DST results.", "status": "review"},
    {"id": 4, "source": "d", "target": "MDR and XDR cases; DNA tests.", "status": "review"}])
rep = main._abbr_report(p)
got = {r["abbr"]: r["id"] for r in rep}
check(got == {"XDR": 3, "DST": 3}, "расшифрованное и капс-заголовок не в отчёте, XDR/DST с первого места: %s" % got)

print("=== 5. находки и смена стайл-шита ===")
p = build(style={}, segments=[
    {"id": 1, "source": "a", "target": "The tumour.", "status": "review"},
    {"id": 2, "source": "b", "target": "The colour.", "status": "confirmed", "confirmedBy": 1},
    {"id": 3, "source": "c", "target": "The tumor.", "status": "review"}])
f = main._style_findings(p)
check([x["id"] for x in f["spelling"]] == [1, 2] and f["spelling"][0]["now"] == "The tumor.",
      "находки орфографии по действующему варианту: %s" % [x["id"] for x in f["spelling"]])
h = main._text_hash("The tumour.")
p["segments"][0]["review"] = {"v": main.REVIEW_VERSION, "score": 9, "target_hash": h,
                              "source_hash": main._text_hash("a"), "applied": False}
check(not main._review_stale(p["segments"][0]), "свежий вердикт ревизии")
r = main.set_project_style(1, main.StyleBody(fields={"spelling": "UK"}))
check(r["changed"] and r["reviewsStale"] == 1 and main._review_stale(p["segments"][0]),
      "смена действующего поля делает вердикт устаревшим и называет число: %s" % r["reviewsStale"])
r = main.set_project_style(1, main.StyleBody(fields={"spelling": "UK"}))
check(not r["changed"] and r["reviewsStale"] == 0, "то же значение — ничего не меняется")
try:
    main.set_project_style(1, main.StyleBody(fields={"spelling": "FR"}))
    check(False, "чужое значение отвергнуто")
except main.HTTPException as e:
    check(e.status_code == 400, "чужое значение отвергнуто: 400")
r = main.style_check(1, main.StyleCheckRequest())
check(r["dryRun"] and r["spelling"] == "UK" and r["ids"] == [3] and r["applied"] == 0,
      "сухой прогон: под UK меняется только #3, ничего не записано: %s" % r["ids"])
r = main.style_check(1, main.StyleCheckRequest(dry_run=False))
seg3 = p["segments"][2]
check(r["applied"] == 1 and seg3["target"] == "The tumour." and seg3["status"] == "review" and r["stamp"],
      "применено: текст заменён, статус review, метка отката есть")
u = main.undo_style_check(1, r["stamp"])
check(u["restored"] == 1 and seg3["target"] == "The tumor." and "styleApplied" not in seg3,
      "откат вернул текст и снял след")
r2 = main.set_project_style(1, main.StyleBody(enable=False))
check(not r2["enabled"] and main._style_block(p) == "", "выключение снимает стайл-шит целиком")

print("=== 6. критик: глоссарий, имена собственные, заверенное, донор ===")
p = build(style={}, segments=[
    {"id": 1, "source": "a", "target": "The haemoglobin and the tumour.", "status": "review"}])
main.STATE["glossary"] = [{"src": "Гемоглобин", "tgt": "haemoglobin", "tier": "verified",
                           "lang": "RU→EN", "domain": "medical", "tenant": "default"}]
main._invalidate_gloss_index()
f = main._style_findings(p)
check(f["spelling"][0]["now"] == "The haemoglobin and the tumor.",
      "приказной перевод глоссария орфография не трогает: %s" % f["spelling"][0]["now"])
check("glossary terms take precedence" in main._style_block(p), "блок говорит, что глоссарий сильнее стиля")
new, _ = main._spelling_fix("Data from the Centers for Disease Control. Centre staff analysed it.", "UK")
check(new == "Data from the Centers for Disease Control. Centre staff analysed it.",
      "имя собственное не трогается, а слово в начале предложения — правится: %s" % new)
new, _ = main._spelling_fix("Tumour cells; the Oesophagostomum genus.", "US")
check(new == "Tumor cells; the Oesophagostomum genus.", "латинский род с заглавной цел: %s" % new)
p = build(style={}, segments=[
    {"id": 1, "source": "a", "target": "The tumour.", "status": "confirmed", "confirmedBy": 7},
    {"id": 2, "source": "b", "target": "The colour.", "status": "review", "backcheck": {"target_hash": main._text_hash("The colour."), "score": 95}}])
r = main.style_check(1, main.StyleCheckRequest())
check(r["skippedConfirmed"] == [1] and r["ids"] == [2] and r["staleChecks"] == 1,
      "заверенное пропущено и названо, цена проверок названа: %s / %s" % (r["skippedConfirmed"], r["staleChecks"]))
r = main.style_check(1, main.StyleCheckRequest(dry_run=False, include_confirmed=True))
s1 = p["segments"][0]
check(r["applied"] == 2 and s1["target"] == "The tumor." and s1.get("confirmedBy") is None
      and s1.get("prevTarget") == "The tumour." and s1["status"] == "review",
      "с разрешением заверенное переписано по закону _replace_target")
p["segments"][1]["target"] = "The color of skin."       # правка после применения
u = main.undo_style_check(1, r["stamp"])
check(u["restored"] == 1 and u["changedSince"] == [2] and s1["target"] == "The tumour."
      and s1["status"] == "confirmed" and s1.get("confirmedBy") == 7,
      "откат вернул заверение, а правленый после — назван: %s" % u["changedSince"])
seg = {"id": 9, "source": "x", "target": "Written by review.", "status": "review", "route": "REVIEW",
       "backcheck": {"score": 99, "target_hash": main._text_hash("Written by review.")},
       "termcheck": {"findings": [], "target_hash": main._text_hash("Written by review.")},
       "review": {"v": main.REVIEW_VERSION, "score": 9.5, "applied": False,
                  "target_hash": main._text_hash("Written by review."), "source_hash": main._text_hash("x")}}
check(main._machine_clean(seg, 90) == main.CLEAN_REPAIRED,
      "после переревизии текст ревизии донором глоссария не становится (route REVIEW)")
p = build(style={}, segments=[{"id": 1, "source": "a", "target": "MAIN FORMS", "status": "review"},
                              {"id": 2, "source": "b", "target": "NOTE:", "status": "review"}])
check(main._abbr_report(p) == [], "короткий капс-заголовок — не аббревиатуры")

print("")
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail))
sys.exit(1 if fail else 0)
