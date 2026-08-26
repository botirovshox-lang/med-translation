"""Критический аудит: доменная нейтральность и защита от вечной переплаты.

Проверяется то, что нашёл разбор механизмов:
  1. промпт перевода берёт слово области из проекта, а не зашитую «медицину»;
  2. обратный перевод не заказывается моделью-автором текста: раньше совпадение
     моделей давало вечный цикл — проверка выполнялась, признавалась
     недействительной (_backcheck_cached) и оплачивалась заново КАЖДЫМ прогоном;
  3. проверка отрицаний back-check берёт маркеры языка оригинала, а не жёсткий
     русский список; для языка без маркеров — молчит;
  4. скип-списки глоссарной проверки Medical QA берутся из области и пары
     языков проекта, а не всегда из медицинских RU→EN;
  5. кандидаты Medical QA получают область проекта, а не «medical» всем подряд.

Ни одного платного вызова: перевод и эмбеддинги подменены.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
import medical_qa

main.save_state = lambda *a, **k: None
main._semantic_similarity = lambda a, b: None      # эмбеддинги — сеть, в тесте её нет

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg(sid, source, target="", status="translated", provider=None):
    s = {"id": sid, "source": source, "target": target, "status": status, "risk": "medium"}
    if provider:
        s["provider"] = provider
    return s


def build(segments, domain="medical"):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": domain,
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


# ─────────────── 1. Промпт перевода: область из проекта ───────────────
print("=== 1. Промпт перевода называет область проекта, а не медицину ===")
# Проверяем ПРОМПТ ЦЕЛИКОМ, а не блок подсказок: сам блок из промпта убран
# (пользу доказать не удалось, вред — 15 медицинских ошибок на 11 414 вставок),
# а вопрос этого теста от него не зависел никогда: область берётся из проекта.
hints = [{"src": "договор", "tgt": "contract"}]        # без tier → подсказка
mdl = main._MODELS_BY_ID[main.DEFAULT_OPENAI_MODEL]
legal = main._translate_system("RU", "EN", hints, None, False, "legal", mdl)
check("medical" not in legal.lower(), "юридический промпт не упоминает медицину")
check("legal" in legal.lower(), "слово области — из проекта")
med = main._translate_system("RU", "EN", hints, None, False, "medical", mdl)
check("medical" in med.lower() and "legal" not in med.lower(),
      "медицинский проект остался медицинским")

# ─────────────── 2. Модель обратного перевода ≠ автор текста ───────────────
print("\n=== 2. Back-check не заказывается моделью-автором перевода ===")
check(main._backcheck_model({"provider": "gpt-4o"}, None) == main.BACKCHECK_DEFAULT_MODEL,
      "нет совпадения — дефолт back-check как и раньше")
check(main._backcheck_model({}, "gpt-4o") == "gpt-4o",
      "явно выбранная модель без совпадения не подменяется")
swapped = main._backcheck_model({"provider": main.BACKCHECK_DEFAULT_MODEL},
                                main.BACKCHECK_DEFAULT_MODEL)
check(swapped != main.BACKCHECK_DEFAULT_MODEL,
      "текст переведён дефолтной моделью back-check — берётся запасная")
check(swapped == main.BACKCHECK_FALLBACK_MODEL, "запасная — именно BACKCHECK_FALLBACK_MODEL")
check(main._backcheck_model({"provider": main.BACKCHECK_FALLBACK_MODEL},
                            main.BACKCHECK_FALLBACK_MODEL) == main.BACKCHECK_DEFAULT_MODEL,
      "а если автор — запасная, возвращаемся к дефолтной")

print("\n=== 3. Вечная переплата закрыта: второй прогон бесплатен ===")
main._openai_translate = lambda text, s, t, **k: "RU: " + text
proj = build([seg(1, "жалобы", "complaints", provider="gpt-5.6-luna")])
r1 = main.backcheck_batch(1, main.BackcheckBatchRequest(model="gpt-5.6-luna", skip_cached=True))
check(r1["count"] == 1, "первый прогон сегмент взял (проверка автором — не проверка)")
sg = proj["segments"][0]
check(sg["backcheck"]["model"] != "gpt-5.6-luna",
      "обратный перевод сделан ДРУГОЙ моделью: " + sg["backcheck"]["model"])
check(main._backcheck_cached(sg, "gpt-5.6-luna", False),
      "результат зачтён — раньше он был недействителен и оплачивался вечно")
r2 = main.backcheck_batch(1, main.BackcheckBatchRequest(model="gpt-5.6-luna", skip_cached=True))
check(r2["count"] == 0 and r2["skipped_cached"] == 1, "второй прогон не платит ничего")
plan = main.run_plan(1, main.RunPlanRequest(steps=["backcheck"], bc_model="gpt-5.6-luna"))
check(plan["steps"][0]["count"] == 0, "и разбор прогона больше не обещает работу")

print("\n=== 4. Medical QA заказывает обратный перевод с той же защитой ===")
seen = []
main._openai_translate = lambda text, s, t, **k: (seen.append(k.get("model")), "RU: " + text)[1]
build([seg(1, "жалобы", "complaints", provider=main.BACKCHECK_DEFAULT_MODEL)])
main.batch_medical_qa(1, main.MedicalQABatchRequest())
check(seen == [main.BACKCHECK_FALLBACK_MODEL],
      "модель обратного перевода QA не совпала с автором текста")

# ─────────────── 5. Отрицания back-check — по языку оригинала ───────────────
print("\n=== 5. Маркеры отрицания берутся из языка оригинала ===")
issues, _ = medical_qa.backcheck_issues("без опухоли", "опухоль есть", src_lang="RU")
check(any(i["type"] == "backcheck_negation_shift" for i in issues),
      "русский оригинал: потерянное «без» — находка, как и раньше")
issues, _ = medical_qa.backcheck_issues("no evidence of tumor", "evidence of tumor found",
                                        src_lang="EN")
check(any(i["type"] == "backcheck_negation_shift" for i in issues),
      "английский оригинал: потерянное «no» теперь тоже находка")
issues, _ = medical_qa.backcheck_issues("sin evidencia de tumor", "evidencia de tumor",
                                        src_lang="ES")
check(not any(i["type"] == "backcheck_negation_shift" for i in issues),
      "язык без маркеров: проверка молчит, а не срабатывает наугад")

# ─────────────── 6. Скип-списки — из области, а не из медицины ───────────────
print("\n=== 6. Скип-списки глоссарной проверки уважают область ===")
check(not medical_qa._should_validate_glossary_term("сахар", "sugar"),
      "legacy-вызов без области: медицинский скип работает как раньше")
check(medical_qa._should_validate_glossary_term("сахар", "sugar", set(), set()),
      "в области с пустыми списками «сахар» проверяется, а не пропускается")
check(not medical_qa._should_validate_glossary_term("оферта", "offer", {"оферта"}, set()),
      "скип своей области срабатывает")

print("\n=== 7. Кандидаты Medical QA несут область проекта ===")
res = medical_qa.run_medical_qa("договор аренды", "the deal",
                                glossary_matches=[{"src": "договор", "tgt": "contract"}],
                                domain="legal", src_lang="RU", tgt_lang="EN")
cands = res["term_candidates"]
check(bool(cands), "нарушение глоссария дало кандидата")
check(all(c["domain"] == "legal" for c in cands),
      "область кандидата — legal, а не «medical» по привычке")

print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
else:
    print("ВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
