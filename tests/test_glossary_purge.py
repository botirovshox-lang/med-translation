"""Массовый вынос автоимпорта из глоссария.

`DELETE /api/glossary` работает по ОДНОЙ записи, а импорт — десять тысяч:
поштучно их не выносят. Значит операция либо есть осознанной, с предпросмотром
и откатом, либо делается руками по файлу состояния — что хуже во всех
отношениях. Проверяется ровно то, без чего она опасна:

  1. `dry_run` считает и НЕ трогает;
  2. приказы не выносятся вместе с подсказками;
  3. запись со следом решения человека не выносится никогда, и сказано,
     скольких пощадили;
  4. область фильтра соблюдается: чужая языковая пара не страдает;
  5. `unused_only` считает применимость тем же `_term_match`, что и инъекция
     в промпт;
  6. вынесенное лежит файлом и возвращается откатом, а запись, появившаяся
     после выноса, откатом не затирается;
  7. на расчёт расхождений вынос подсказок не влияет — он идёт по приказам.

Ни одного вызова модели и ни одного обращения к сети.
"""
import os, sys, json, shutil, tempfile

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
# Бэкапы выноса пишем во временный каталог: боевой data/backups не трогаем.
TMP = tempfile.mkdtemp(prefix="mcat-purge-")
main.PURGE_DIR = __import__("pathlib").Path(TMP)

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def entry(src, tgt, tier="auto", **extra):
    e = {"src": src, "tgt": tgt, "tier": tier, "lang": "RU→EN",
         "domain": "medical", "conf": "medium", "note": ""}
    e.update(extra)
    return e


def build(gloss, segments=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": [],
                  "autoBatches": [], "autoBatchSeq": 0}
    main._invalidate_gloss_index()
    main._IMPACT_CACHE.clear()
    return proj


GLOSS = [
    entry("задний увеит", "rear uveitis"),                       # автоимпорт
    entry("мокрота", "phlegm"),                                  # автоимпорт
    entry("инфильтрат", "infiltrate", tier="verified"),          # приказ
    entry("бациллы", "bacilli", origin="confirmed:12"),          # правил человек
    entry("хрипы", "rales", note="уточнено вручную 2026-08-01"),  # правил человек
    entry("вертрag", "Vertrag", lang="RU→DE"),                   # чужая пара
]
SEGS = [{"id": 1, "source": "Мокрота с примесью крови.", "target": "Sputum with blood.",
         "status": "translated"}]

print("=== 1. Разбор ничего не меняет и называет пощажённых ===")
build(GLOSS, SEGS)
r = main.purge_glossary(main.GlossaryPurgeRequest(dry_run=True))
check(len(main.STATE["glossary"]) == 6, "в режиме показа глоссарий не тронут")
check(r["matched"] == 3, "к выносу отобраны три подсказки (включая чужую пару)")
check(r["keptHuman"] == 2, "две записи со следом человека пощажены и посчитаны")
check(r["stamp"] is None, "метки отката нет — ничего и не выносили")

print("\n=== 2. Приказ подсказкой не выносится ===")
srcs = {x["src"] for x in r["samples"]}
check("инфильтрат" not in srcs, "запись уровня «приказ» в список не попала")

print("\n=== 3. Область фильтра соблюдается ===")
r = main.purge_glossary(main.GlossaryPurgeRequest(project=1, dry_run=True))
srcs = {x["src"] for x in r["samples"]}
check(r["matched"] == 2 and "вертрag" not in srcs,
      "с областью проекта чужая языковая пара не выносится")

print("\n=== 4. unused_only считает применимость к тексту ===")
r = main.purge_glossary(main.GlossaryPurgeRequest(project=1, unused_only=True, dry_run=True))
srcs = {x["src"] for x in r["samples"]}
check(r["matched"] == 1 and "мокрота" not in srcs,
      "встречающийся в тексте термин не выносится как неиспользуемый")
check("задний увеит" in srcs, "а не встречающийся — выносится")

print("\n=== 5. Вынос сохраняет копию и снимает записи ===")
r = main.purge_glossary(main.GlossaryPurgeRequest(project=1, dry_run=False))
left = {g["src"] for g in main.STATE["glossary"]}
check(r["removed"] == 2 and len(main.STATE["glossary"]) == 4, "вынесены две подсказки")
check("инфильтрат" in left and "бациллы" in left and "хрипы" in left,
      "приказ и правленое человеком на месте")
check("вертрag" in left, "чужая языковая пара не затронута")
check(bool(r["stamp"]), "метка отката выдана")
saved = json.loads((main.PURGE_DIR / ("glossary-purge-" + r["stamp"] + ".json")).read_text(encoding="utf-8"))
check(len(saved) == 2, "копия для отката записана на диск")

print("\n=== 6. Вынос подсказок не меняет расчёт расхождений ===")
# Расхождения считаются ТОЛЬКО по приказам, поэтому подсказками они не двигаются.
build(GLOSS, [{"id": 1, "source": "Инфильтрат в лёгком.", "target": "Induration in the lung.",
               "status": "translated"}])
before = main.glossary_impact(1, refresh=True)["segments"]
main.purge_glossary(main.GlossaryPurgeRequest(project=1, dry_run=False))
after = main.glossary_impact(1, refresh=True)["segments"]
check(before == after == [1], "сегмент расходится с приказом и до, и после выноса")

print("\n=== 7. Откат возвращает вынесенное и не плодит дублей ===")
build(GLOSS, SEGS)
r = main.purge_glossary(main.GlossaryPurgeRequest(project=1, dry_run=False))
# Пока копия лежала, человек завёл запись про тот же термин — её не трогаем.
main.STATE["glossary"].append(entry("задний увеит", "posterior uveitis", tier="verified"))
main._invalidate_gloss_index()
u = main.undo_glossary_purge(r["stamp"])
check(u["restored"] == 1 and u["skipped"] == 1, "вернулась одна, вторая пропущена")
back = [g for g in main.STATE["glossary"] if g["src"] == "задний увеит"]
check(len(back) == 1 and back[0]["tgt"] == "posterior uveitis",
      "новая запись человека уцелела, дубля не появилось")
check(any(g["src"] == "мокрота" for g in main.STATE["glossary"]), "остальное вернулось")

print("\n=== 8. Откат несуществующей копии — отказ, а не тишина ===")
try:
    main.undo_glossary_purge("20200101-000000")
    check(False, "откат без копии обязан отказать")
except main.HTTPException as e:
    check(e.status_code == 404, "отказ 404 с внятной причиной")
try:
    main.undo_glossary_purge("../../etc/passwd")
    check(False, "метка обязана проверяться")
except main.HTTPException as e:
    check(e.status_code == 400, "чужой путь в метке отвергнут")

print("\n=== 9. Приказ без следа человека выносится, с следом — нет ===")
# Уровень «приказ» запись могла получить не от человека, а от миграции:
# «её нет в массовом импорте — значит добавлена руками». Своё предположение
# машина вправе пересмотреть, чужое решение — нет.
build([
    entry("бухтообразный", "scalloped", tier="verified"),            # импорт
    entry("Клинику", "clinical practice", tier="verified",
          origin="confirmed:2670"),                                  # одобрил человек
    entry("хрипы", "rales", tier="verified",
          note="уточнено вручную 2026-08-01"),                       # правил руками
    entry("мокрота", "phlegm"),                                      # подсказка
])
r = main.purge_glossary(main.GlossaryPurgeRequest(project=1, tier="verified", dry_run=True))
srcs = {x["src"] for x in r["samples"]}
check(r["matched"] == 1 and srcs == {"бухтообразный"},
      "к выносу только приказ без следа решения человека")
check(r["keptHuman"] == 2, "одобренное и правленное руками пощажено")

r = main.purge_glossary(main.GlossaryPurgeRequest(project=1, tier="verified", dry_run=False))
left = {g["src"] for g in main.STATE["glossary"]}
check(left == {"Клинику", "хрипы", "мокрота"}, "вынесен ровно один приказ")
check("мокрота" in left, "подсказки при выносе приказов не трогаются")
u = main.undo_glossary_purge(r["stamp"])
check(u["restored"] == 1 and any(g["src"] == "бухтообразный" for g in main.STATE["glossary"]),
      "и возвращается откатом")

print("\n=== 10. Человек понижает запись, которую машина не вправе ===")
# Сверка находит неверный приказ, но со следом решения человека не трогает.
# Значит человеку нужен способ согласиться — иначе находка ничем не кончается.
build([entry("Клинику", "clinical practice", tier="verified", origin="confirmed:2670",
             meaningKept=True)])
g = main.STATE["glossary"][0]
r = main.demote_term(main.TermScopeRequest(src="Клинику", lang="RU→EN", domain="medical"))
check(r["ok"] and r["already"] is False, "понижение выполнено")
check(main._hit_tier(g) == "auto", "запись стала подсказкой")
check(g["tgt"] == "clinical practice", "перевод не тронут — сменился только уровень")
check(g.get("prevTier") == "verified", "прежний уровень сохранён")
check("meaningKept" not in g,
      "пометка «человек решил оставить приказ» снята: он решил обратное")
check(main._hard_answer(g) is False, "подсказка ответом на вопрос о термине не считается")

r = main.demote_term(main.TermScopeRequest(src="Клинику", lang="RU→EN", domain="medical"))
check(r["already"] is True, "повторное понижение не ломается и говорит правду")

try:
    main.demote_term(main.TermScopeRequest(src="нет такого", lang="RU→EN", domain="medical"))
    check(False, "несуществующая запись обязана дать отказ")
except main.HTTPException as e:
    check(e.status_code == 404, "отказ 404")

print("\n=== 11. Понижение убирает запись из расчёта расхождений ===")
build([entry("Клинику", "clinical practice", tier="verified", origin="confirmed:1")],
      [{"id": 1, "source": "Направлен в Клинику на дообследование.",
        "target": "Referred to the clinic for further tests.", "status": "translated"}])
before = main.glossary_impact(1, refresh=True)["segments"]
check(before == [1], "пока это приказ — сегмент считается нарушением")
main.demote_term(main.TermScopeRequest(src="Клинику", lang="RU→EN", domain="medical"))
after = main.glossary_impact(1, refresh=True)["segments"]
check(after == [], "после понижения требовать соответствия нечему")

print("\n=== 12. Понижение говорит, что ремонт уже успел вписать ===")
# Понижение снимает ПОВОД чинить дальше, но уже переписанное так и осталось.
# Человек уверен, что отменил правило целиком, — и это надо разрушить сразу.
seg_ok = {"id": 1, "source": "Направлен в Клинику.", "target": "Referred to clinical practice.",
          "status": "review",
          "repair": {"applied": True, "from": "Referred to the clinic.",
                     "issues": ["утверждённый перевод термина «Клинику» — «clinical practice»,"
                                " в переводе его нет"]}}
seg_other = {"id": 2, "source": "Мокрота.", "target": "Sputum.", "status": "translated",
             "repair": {"applied": True, "issues": ["«мокрота» — «sputum»"]}}
seg_reverted = {"id": 3, "source": "В Клинику направлен.", "target": "Referred to the clinic.",
                "status": "translated",
                "repair": {"applied": False,
                           "issues": ["утверждённый перевод термина «Клинику» — «clinical practice»,"
                                      " в переводе его нет"]}}
build([entry("Клинику", "clinical practice", tier="verified", origin="confirmed:1")],
      [seg_ok, seg_other, seg_reverted])
r = main.demote_term(main.TermScopeRequest(src="Клинику", lang="RU→EN", domain="medical"))
check(r["repairedCount"] == 1, "посчитан ровно один переписанный сегмент")
check(r["repaired"][0]["id"] == 1, "и назван поимённо")
check(main.STATE["projects"][0]["segments"][0]["target"] == "Referred to clinical practice.",
      "текст НЕ откатывается: понижение — про правило, а не про готовый перевод")

print("\n=== 13. Понижение не трогает то, что ремонт откатил ===")
# Сегмент 3: ремонт пробовал и не применил — переписанным он не считается.
check(all(x["id"] != 3 for x in r["repaired"]),
      "откаченная правка в список не попала")
check(all(x["id"] != 2 for x in r["repaired"]),
      "чужая претензия в список не попала")

print("\n=== 14. Правки по понижённой записи откатываются автоматом ===")
# Единственная операция, меняющая текст без вызова модели. Так можно потому,
# что она ничего не сочиняет: подставляется repair.from — то, что стояло
# в сегменте до правки и у чего были свои проверки.
CLAIM = "утверждённый перевод термина «Клинику» — «clinical practice», в переводе его нет"
only = {"id": 1, "source": "Направлен в Клинику.", "target": "Referred to clinical practice.",
        "status": "review",
        "backcheck": {"score": 40, "target_hash": main._text_hash("Referred to clinical practice.")},
        "repair": {"applied": True, "from": "Referred to the clinic.",
                   "candidate": "Referred to clinical practice.",
                   "source_hash": main._text_hash("Referred to clinical practice."),
                   "model": "gpt-5.6-sol", "issues": [CLAIM]}}
mixed = {"id": 2, "source": "В Клинику, 5 мг.", "target": "To clinical practice, 5 mg.",
         "status": "review",
         "repair": {"applied": True, "from": "To the clinic, 50 mg.",
                    "source_hash": main._text_hash("To clinical practice, 5 mg."),
                    "issues": [CLAIM, "расхождение чисел"]}}
lost = {"id": 3, "source": "Клинику осмотрел.", "target": "Inspected clinical practice.",
        "status": "review",
        "repair": {"applied": True, "from": "", "issues": [CLAIM]}}
alien = {"id": 4, "source": "Мокрота.", "target": "Sputum.", "status": "translated",
         "repair": {"applied": True, "from": "Phlegm.", "issues": ["«мокрота» — «sputum»"]}}
build([entry("Клинику", "clinical practice", tier="verified", origin="confirmed:1")],
      [only, mixed, lost, alien])
r = main.revert_repairs_by_term(main.RevertRepairsRequest(src="Клинику", lang="RU→EN", domain="medical"))
segs = {x["id"]: x for x in main.STATE["projects"][0]["segments"]}
check(r["revertedCount"] == 1 and r["reverted"][0]["id"] == 1, "возвращён сегмент с одной причиной")
check(segs[1]["target"] == "Referred to the clinic.", "текст восстановлен из repair.from")
check(segs[1]["status"] == "review", "статус «требует проверки» — текст менял не человек")
check(main._check_stale(segs[1].get("backcheck"), segs[1]["target"]),
      "проверка отвергнутого текста сама стала устаревшей")
check(not (segs[1].get("repair") or {}).get("applied"), "запись о правке снята")

check(r["requeuedCount"] == 1 and r["requeued"][0]["id"] == 2,
      "сегмент с несколькими причинами отдан ремонту заново, а не откачен")
check(segs[2]["target"] == "To clinical practice, 5 mg.",
      "его текст не тронут: откат унёс бы и верное исправление чисел")
check("source_hash" not in segs[2]["repair"], "и ремонт снова к нему пойдёт")

check(r["skippedCount"] == 1 and r["skipped"][0]["id"] == 3,
      "сегмент без сохранённого текста назван, а не пропущен молча")
check(segs[3]["target"] == "Inspected clinical practice.", "и не тронут")
check(segs[4]["target"] == "Sputum.", "чужая правка не задета")

print("\n=== 15. Понижение и откат вместе снимают расхождение ===")
build([entry("Клинику", "clinical practice", tier="verified", origin="confirmed:1")],
      [dict(only)])
main.demote_term(main.TermScopeRequest(src="Клинику", lang="RU→EN", domain="medical"))
main.revert_repairs_by_term(main.RevertRepairsRequest(src="Клинику", lang="RU→EN", domain="medical"))
seg = main.STATE["projects"][0]["segments"][0]
check(seg["target"] == "Referred to the clinic.", "верный перевод вернулся")
check(main.glossary_impact(1, refresh=True)["segments"] == [],
      "и нарушением он больше не числится: правило понижено")

print("\n=== 16. Понижение пачкой берёт одобрения человека только по разрешению ===")
# Машина чужое решение не отменяет сама. Но человек вправе разрешить это
# пачкой — с предпросмотром, откатом и возвратом переписанных сегментов.
# Ведёт список вердикт судьи, а не перечень слов в коде.
CLAIM2 = "утверждённый перевод термина «Клинику» — «clinical practice», в переводе его нет"
seg1 = {"id": 1, "source": "Направлен в Клинику.", "target": "Referred to clinical practice.",
        "status": "review",
        "repair": {"applied": True, "from": "Referred to the clinic.",
                   "candidate": "Referred to clinical practice.",
                   "source_hash": main._text_hash("Referred to clinical practice."),
                   "issues": [CLAIM2]}}
build([
    entry("Клинику", "clinical practice", tier="verified", origin="confirmed:1"),
    entry("бухтообразный", "scalloped", tier="verified"),
    entry("хрипы", "rales", tier="verified", origin="confirmed:2", meaningKept=True),
], [seg1])
os.environ["OPENAI_API_KEY"] = "test-key"
main._openai_meaning = lambda pairs, scope: {
    (main._norm_key(a), main._norm_key(b)):
        {"same": True, "back": "клиника", "rule": False, "why": "падежная форма"}
    for a, b in pairs}

r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True))
check(len(r["bad"]) == 3, "судья забраковал все три")
check(r["downgradable"] == 1, "сама машина понизит только запись без следа человека")
check(r["downgradableHuman"] == 1, "с разрешением добавится ещё одна")
check(r["keptByHuman"] == 1, "возвращённая человеком не считается ни там, ни там")

r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=False,
                                                  include_human=True))
by = {g["src"]: g for g in main.STATE["glossary"]}
check(main._hit_tier(by["Клинику"]) == "auto", "одобрение человека понижено по разрешению")
check(main._hit_tier(by["бухтообразный"]) == "auto", "и запись импорта тоже")
check(main._hit_tier(by["хрипы"]) == "verified",
      "а возвращённая человеком из понижения не тронута даже с разрешением")
check("падежная форма" in by["Клинику"]["note"],
      "в примечании причина той проверки, что забраковала")
check(r["reverted"]["reverted"] == 1, "переписанный сегмент возвращён тем же нажатием")
check(main.STATE["projects"][0]["segments"][0]["target"] == "Referred to the clinic.",
      "текст восстановлен из repair.from")

print("\n=== 17. Пачка понижения откатывается целиком ===")
u = main.undo_auto_approve(r["batch"])
by = {g["src"]: g for g in main.STATE["glossary"]}
check(u["restored"] == 2, "обе понижённые записи вернулись")
check(main._hit_tier(by["Клинику"]) == "verified", "уровень восстановлен")
check(by["Клинику"].get("meaningKept") is True,
      "и помечено, что человек решил оставить приказ")

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
