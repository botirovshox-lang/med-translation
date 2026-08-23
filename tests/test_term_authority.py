"""Спор проверки с утверждённым термином и приказ по разрешению человека.

Проверяется ровно то, из-за чего это написано:

  1. termcheck, забраковавший УТВЕРЖДЁННЫЙ термин, виден отдельной корзиной —
     в общей куче «с замечаниями» этот спор не видно ни с одной стороны;
  2. ремонт по такой находке ВСЕГДА откатывается: приказ глоссария сильнее
     проверки, и вызов модели уходит впустую — это цена, о которой надо знать;
  3. запрет области на приказ снимается ТОЛЬКО явным разрешением, разрешение
     видно в ответе, в записи глоссария и в истории пачек;
  4. «только подсказки» сильнее разрешения: это просьба человека на запуск;
  5. порог сегментов и требование РАЗНЫХ исходников разрешением не снимаются.

Ни одного вызова модели: termcheck и ремонт подменены.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build(gloss=(), segments=(), domain="medical"):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": domain,
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": [],
                  "autoBatches": [], "autoBatchSeq": 0}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    return proj


VERIFIED = {"src": "инфильтрат", "tgt": "infiltrate", "cat": "Term",
            "tier": "verified", "lang": "RU→EN", "domain": "medical"}


def flagged(sid, source, target, status="translated"):
    """Сегмент, где termcheck забраковал утверждённый термин."""
    h = main._text_hash(target)
    return {"id": sid, "source": source, "target": target, "status": status,
            "backcheck": {"score": 96, "target_hash": h, "model": "gpt-5.6-luna"},
            "termcheck": {"target_hash": h, "model": "gpt-5.6-terra", "severity": "major",
                          "findings": [{"tgt_term": "infiltrate", "suggestion": "induration",
                                        "severity": "major", "why": "not idiomatic"}]}}


print("=== 1. Спор проверки с приказом виден отдельной корзиной ===")
proj = build(gloss=[VERIFIED],
             segments=[flagged(1, "Инфильтрат в лёгком.", "Infiltrate in the lung."),
                       flagged(2, "Инфильтрат рассосался.", "The infiltrate resolved.")])
a = main.project_analysis(1, refresh=True)
d = a["human"]["termcheckDisputes"]
check(len(d) == 1, "спор сведён к ОДНОЙ записи глоссария, а не к двум сегментам")
check(d[0]["src"] == "инфильтрат" and d[0]["tgt"] == "infiltrate", "названа спорная запись")
check(d[0]["suggests"] == ["induration"], "и что проверка предлагает взамен")
check(sorted(a["human"]["termcheckDisputesSegments"]) == [1, 2], "сегменты названы поимённо")

print("\n=== 2. Находка на НЕутверждённом термине сюда не попадает ===")
proj = build(gloss=[dict(VERIFIED, tier="auto")],
             segments=[flagged(1, "Инфильтрат в лёгком.", "Infiltrate in the lung.")])
a = main.project_analysis(1, refresh=True)
check(not a["human"]["termcheckDisputes"],
      "подсказка приказом не является — спорить не с чем, это обычная находка")
check(1 in a["todo"]["findings"], "и сегмент остался в обычной корзине замечаний")

print("\n=== 3. Устаревшая проверка в спор не идёт ===")
proj = build(gloss=[VERIFIED],
             segments=[flagged(1, "Инфильтрат в лёгком.", "Infiltrate in the lung.")])
proj["segments"][0]["target"] = "Infiltrate in the left lung."   # текст правили после проверки
a = main.project_analysis(1, refresh=True)
check(not a["human"]["termcheckDisputes"],
      "проверка относится к другому тексту — её находка ничего не значит")

print("\n=== 4. Ремонт по такой находке всегда откатывается ===")
proj = build(gloss=[VERIFIED],
             segments=[flagged(1, "Инфильтрат в лёгком.", "Infiltrate in the lung.")])
os.environ["OPENAI_API_KEY"] = "test-key"
seg = proj["segments"][0]
finds = main._repair_findings(seg, proj)
check(any(f["kind"] == "term" for f in finds), "находка termcheck попала в претензии ремонта")
check(not any(f["kind"] == "gloss" for f in finds),
      "а расхождения с глоссарием нет: утверждённый термин в тексте присутствует")

# Модель послушалась проверки и выбила утверждённый термин.
main._openai_repair = lambda *a, **k: "Induration in the lung."
# Перепроверки после правки не делаем — это вызовы модели; ремонт обязан
# откатиться на бесплатной сверке глоссария ещё до них.
main._run_segment_backcheck = lambda *a, **k: {"ok": True}
main._run_segment_termcheck = lambda *a, **k: {"ok": True}
r = main.repair_segment(1, 1)
check(r["ok"] and not r["applied"], "правка не применена")
check("утверждённых терминов" in (r["repair"]["reason"] or ""),
      "и причина названа: нарушенных утверждённых терминов стало больше")
check(seg["target"] == "Infiltrate in the lung.", "текст вернулся на место")
check(main._repair_tried(seg), "второй раз на тот же текст ремонт не пойдёт")

print("\n=== 5. Запрет области на приказ снимается только явным разрешением ===")


def donors(n, source_prefix="мокрота "):
    """n независимых чистых сегментов; исходники по умолчанию РАЗНЫЕ."""
    out = []
    for i in range(n):
        t = "sputum"
        h = main._text_hash(t)
        out.append({"id": i + 1, "source": source_prefix + str(i), "target": t,
                    "status": "translated",
                    "backcheck": {"score": 98, "target_hash": h, "model": "gpt-5.6-luna"},
                    "termcheck": {"target_hash": h, "model": "gpt-5.6-terra",
                                  "findings": [], "severity": "none"}})
    return out


def queue_cand(seg_ids):
    return {"id": 1, "kind": "segment", "src": "мокрота", "tgt": "sputum",
            "status": "pending", "hits": len(seg_ids), "lang": "RU→EN",
            "domain": "medical", "segments": ["1:%d" % i for i in seg_ids]}


proj = build(segments=donors(3))
main.STATE["termQueue"] = [queue_cand([1, 2, 3])]
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True))
check(r["counts"]["verified"] == 0 and r["counts"]["auto"] == 1,
      "по умолчанию три чистых сегмента дают подсказку, а не приказ")

r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True,
                                                    allow_verified=True))
check(r["counts"]["verified"] == 1, "с разрешением те же три сегмента дают приказ")
check(r["policy"]["humanOverride"] is True, "разрешение видно в ответе")

print("\n=== 6. «Только подсказки» сильнее разрешения ===")
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True,
                                                    allow_verified=True, max_tier="auto"))
check(r["counts"]["verified"] == 0, "просьба ничего не поднимать перевешивает")

print("\n=== 7. Разрешение записано в глоссарии и в истории пачек ===")
# Применение идёт с ключом — сеть подменяем: судья подтверждает смысл.
main._openai_meaning = lambda pairs, scope: {
    (main._norm_key(a), main._norm_key(b)): {"same": True, "back": "то же"}
    for a, b in pairs}
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=False,
                                                    allow_verified=True))
g = main._glossary_entry("мокрота", ("RU→EN", "medical"))
check(main._hit_tier(g) == "verified", "запись ушла приказом")
check(g.get("byOverride") is True, "на записи стоит пометка «по разрешению человека»")
check("разрешению человека" in g.get("note", ""), "и она читаема в примечании")
check(main.STATE["autoBatches"][0]["override"] is True, "история пачки помнит разрешение")

print("\n=== 8. Порог сегментов разрешение не отменяет ===")
proj = build(segments=donors(2))
main.STATE["termQueue"] = [queue_cand([1, 2])]
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True,
                                                    allow_verified=True))
check(r["counts"]["verified"] == 0 and r["counts"]["auto"] == 1,
      "двух доноров мало и с разрешением: снимается запрет, а не порог")

print("\n=== 9. Одинаковый исходник тремя копиями приказа не даёт ===")
proj = build(segments=donors(3, source_prefix="мокрота"))
for s in proj["segments"]:
    s["source"] = "мокрота"          # один и тот же текст, переведённый трижды
main.STATE["termQueue"] = [queue_cand([1, 2, 3])]
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True,
                                                    allow_verified=True))
check(r["counts"]["verified"] == 0,
      "требование РАЗНЫХ исходников разрешением не снимается")

print("\n=== 10. Смысловая сверка отклоняет ложного друга ===")
# «Анизакидоз → Anisakis»: строка в языке есть, согласие сегментов есть,
# а понятие другое — болезнь против рода паразита. Единственный вопрос,
# который это ловит, задаёт судья при применении.
proj = build(segments=donors(3, source_prefix="анизакидоз у пациента "))
for sg in proj["segments"]:
    sg["target"] = "anisakis"
    h = main._text_hash("anisakis")
    sg["backcheck"]["target_hash"] = h
    sg["termcheck"]["target_hash"] = h
main.STATE["termQueue"] = [{"id": 1, "kind": "segment", "src": "анизакидоз",
                            "tgt": "anisakis", "status": "pending", "hits": 3,
                            "lang": "RU→EN", "domain": "medical",
                            "segments": ["1:1", "1:2", "1:3"]}]
main._openai_meaning = lambda pairs, scope: {
    (main._norm_key(a), main._norm_key(b)):
        {"same": False, "back": "род паразита, а не болезнь"} for a, b in pairs}
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=False,
                                                    allow_verified=True))
check(r["counts"]["verified"] == 0 and r["counts"]["auto"] == 0,
      "ложный друг не записан ни приказом, ни подсказкой")
check(r["counts"]["rejectedMeaning"] == 1, "и посчитан отклонённым по смыслу")
check(main._glossary_entry("анизакидоз", ("RU→EN", "medical")) is None,
      "в глоссарии его нет")
cand = main.STATE["termQueue"][0]
check(cand["status"] == "rejected", "кандидат отклонён")
check("род паразита" in cand.get("autoNote", ""),
      "причина — обратный смысл по-русски: видно, ЧТО отвела машина")
check(not main._human_decision(cand), "отклонение машиной решением человека не считается")
batch = r["batch"]
check(bool(batch), "пачка создана и для одних отклонений — иначе их не откатить")
u = main.undo_auto_approve(batch)
check(u["ok"] and cand["status"] == "pending", "откат вернул кандидата в очередь")

print("\n=== 11. «Не знаю» судьи не одобряет и не блокирует ===")
proj = build(segments=donors(3))
main.STATE["termQueue"] = [queue_cand([1, 2, 3])]
main._openai_meaning = lambda pairs, scope: {}      # ответил, но не про эти пары
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=False,
                                                    allow_verified=True))
check(r["counts"]["verified"] == 1,
      "сбой сверки не блокирует одобрение — тот же закон, что у attested()")

print("\n=== 12. По умолчанию разбор сверку не зовёт и говорит об этом ===")
proj = build(segments=donors(3))
main.STATE["termQueue"] = [queue_cand([1, 2, 3])]
called = []
main._openai_meaning = lambda pairs, scope: (called.append(1), {})[1]
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True,
                                                    allow_verified=True))
check(not called, "dry_run не тратит вызовы судьи")
check(r["meaningPending"] is True, "и честно помечает разбор как «до сверки»")

print("\n=== 13. Запись без перевода вопрос не закрывает ===")
# Приказ с пустым переводом не требует ничего и ответом не является. Правило
# должно быть ОДНО у дедупликации и у миграции — раньше они расходились.
blank = {"src": "хрипы", "tgt": "", "tier": "verified",
         "lang": "RU→EN", "domain": "medical"}
proj = build(gloss=[blank], segments=[])
c = main._queue_term("segment", "хрипы", "rales", project=1, segment=1,
                     lang="RU→EN", domain="medical", via="auto")
check(c is not None, "пустая приказная запись не мешает задать вопрос")
check(main._hard_answer(blank) is False, "и ответом не считается")
check(main._hard_answer(VERIFIED) is True, "а заполненная — считается")

st = {"projects": [], "tm": [], "glossary": [dict(blank)],
      "termQueue": [{"id": 1, "kind": "segment", "src": "хрипы", "tgt": "rales",
                     "status": "pending", "lang": "RU→EN", "domain": "medical"}]}
check(main._migrate_term_queue(st) == 0,
      "миграция судит тем же правилом: карточку не снимает")

print("\n=== 14. Запрет области приходит отдельным полем ===")
proj = build(segments=donors(3))
main.STATE["termQueue"] = [queue_cand([1, 2, 3])]
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True))
check(r["policy"]["domainBanned"] is True, "в медицине запрет назван прямо")
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True,
                                                    allow_verified=True))
check(r["policy"]["domainBanned"] is True,
      "и не пропадает от включённого разрешения — иначе тумблер исчезал бы сам")
proj = build(segments=donors(3), domain="general")
main.STATE["termQueue"] = [queue_cand([1, 2, 3])]
r = main.auto_approve_terms(main.AutoApproveRequest(project=1, dry_run=True))
check(r["policy"]["domainBanned"] is False, "там, где запрета нет, поле честно ложно")

print("\n=== 15. Аудит глоссария понижает свою ошибку, но не чужое решение ===")
# Три приказных записи. Первая — предположение миграции (следа человека нет),
# вторая — решение человека, третья — верная. Судья бракует первые две.
mine = {"src": "анизакидоз", "tgt": "anisakis", "tier": "verified",
        "lang": "RU→EN", "domain": "medical", "conf": "high", "note": ""}
human = {"src": "больного", "tgt": "an infected animal", "tier": "verified",
         "lang": "RU→EN", "domain": "medical", "conf": "high",
         "origin": "confirmed:12", "note": ""}
good = {"src": "мокрота", "tgt": "sputum", "tier": "verified", "conf": "high",
        "lang": "RU→EN", "domain": "medical", "note": "", "origin": "seed"}
proj = build(gloss=[mine, human, good], segments=[])
os.environ["OPENAI_API_KEY"] = "test-key"
BAD = {"anisakis": "род паразита, а не болезнь",
       "an infected animal": "заражённое животное, а не пациент"}
main._openai_meaning = lambda pairs, scope: {
    (main._norm_key(a), main._norm_key(b)):
        ({"same": False, "back": BAD[b]} if b in BAD else {"same": True, "back": "то же"})
    for a, b in pairs}

r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True))
check(r["total"] == 3 and r["checked"] == 3, "проверены все приказные записи")
check(len(r["bad"]) == 2, "найдены обе неверные")
check(r["downgradable"] == 1, "понизить можно только ту, где следа человека нет")
check(main._hit_tier(main.STATE["glossary"][0]) == "verified", "разбор ничего не изменил")

r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=False))
by = {g["src"]: g for g in main.STATE["glossary"]}
check(main._hit_tier(by["анизакидоз"]) == "auto",
      "своё предположение машина пересмотрела — запись стала подсказкой")
check(by["анизакидоз"]["tgt"] == "anisakis", "перевод не тронут: понижен только уровень")
check("род паразита" in by["анизакидоз"]["note"], "и сказано почему, по-русски")
check(main._hit_tier(by["больного"]) == "verified",
      "решение человека не отменено — только помечено в отчёте")
check(main._hit_tier(by["мокрота"]) == "verified", "верная запись не тронута")
check(r["downgraded"] == 1, "понижена ровно одна")

print("\n=== 16. Понижение откатывается тем же механизмом, что и пачки ===")
u = main.undo_auto_approve(r["batch"])
by = {g["src"]: g for g in main.STATE["glossary"]}
check(u["ok"] and u["restored"] == 1, "откат вернул запись")
check(main._hit_tier(by["анизакидоз"]) == "verified", "уровень восстановлен")
check(by["анизакидоз"].get("origin") is None, "происхождения не было — не выдумано")
check(main._hit_tier(by["мокрота"]) == "verified" and by["мокрота"]["origin"] == "seed",
      "чужие записи откат не задел")

print("\n=== 17. «Не знаю» судьи запись не понижает ===")
proj = build(gloss=[dict(mine)], segments=[])
main._openai_meaning = lambda pairs, scope: {}
r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=False))
check(not r["bad"] and main._hit_tier(main.STATE["glossary"][0]) == "verified",
      "молчание судьи — не приговор")

print("\n=== 18. Повторная сверка не переспрашивает и не плодит находок ===")
# Из-за чего это написано: вердикт нигде не хранился, аудит спрашивал ВСЕ
# записи каждым запуском, а судья на границе отвечает неустойчиво — список
# на понижение каждый раз получался новый, и конца этому не было.
good = {"src": "мокрота", "tgt": "sputum", "tier": "verified", "conf": "high",
        "lang": "RU→EN", "domain": "medical", "note": "", "origin": "seed"}
proj = build(gloss=[good], segments=[])
os.environ["OPENAI_API_KEY"] = "test-key"
asked = []


def judge(verdict):
    def f(pairs, scope):
        asked.append(len(pairs))
        return {(main._norm_key(a), main._norm_key(b)): dict(verdict) for a, b in pairs}
    return f


main._openai_meaning = judge({"same": True, "back": "то же"})
r1 = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True))
check(r1["checked"] == 1 and not r1["bad"], "первый проход спросил и признал верной")

# Судья передумал — но спрашивать его больше не о чем.
main._openai_meaning = judge({"same": False, "back": "иное понятие"})
r2 = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True))
check(r2["checked"] == 0 and r2["cached"] == 1, "второй проход не потратил ни вызова")
check(not r2["bad"], "и не принёс новой находки на пустом месте")

r3 = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True, force=True))
check(r3["checked"] == 1 and len(r3["bad"]) == 1,
      "переспросить можно, но только явной просьбой")

print("\n=== 19. Правка перевода делает вердикт недействительным ===")
main.STATE["glossary"][0]["tgt"] = "phlegm"
main._openai_meaning = judge({"same": True, "back": "то же"})
r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True))
check(r["checked"] == 1, "вердикт был про другую пару — спрашиваем заново")

print("\n=== 20. Проверка терминов номинирует, но не понижает ===")
proj = build(gloss=[VERIFIED],
             segments=[flagged(1, "Инфильтрат в лёгком.", "Infiltrate in the lung.")])
g = main.STATE["glossary"][0]
n = main._note_term_disputes(proj["segments"][0], proj)
check(n == 1 and g.get("disputed") == 1, "жалоба на приказной термин посчитана")
check(main._hit_tier(g) == "verified", "но сама по себе запись не понижена")
check(g.get("disputedSuggest") == "induration", "и что предлагают взамен — записано")

# Запись уже сверялась и была признана верной — жалоба возвращает её на сверку.
g["meaning"] = {"same": True, "back": "то же", "pair": main._meaning_pair(g),
                "disputed": 0, "model": "x", "at": "2026-08-01"}
check(main._meaning_stale(g), "новая жалоба делает прошлый вердикт устаревшим")
g["meaning"]["disputed"] = 1
check(not main._meaning_stale(g), "а учтённая жалоба — нет")

# Находка на НЕприказном термине никого не номинирует.
proj = build(gloss=[dict(VERIFIED, tier="auto")],
             segments=[flagged(1, "Инфильтрат в лёгком.", "Infiltrate in the lung.")])
check(main._note_term_disputes(proj["segments"][0], proj) == 0,
      "подсказку оспаривать не надо — она и так необязательна")

print("\n=== 21. Откат понижения закрывает вопрос навсегда ===")
mine = {"src": "анизакидоз", "tgt": "anisakis", "tier": "verified", "conf": "high",
        "lang": "RU→EN", "domain": "medical", "note": ""}
proj = build(gloss=[mine], segments=[])
main._openai_meaning = judge({"same": False, "back": "род паразита"})
r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=False))
check(r["downgraded"] == 1, "понижено")
main.undo_auto_approve(r["batch"])
g = main.STATE["glossary"][0]
check(main._hit_tier(g) == "verified" and g.get("meaningKept") is True,
      "откат вернул приказ и пометил решение человека")
r = main.audit_glossary(main.GlossaryAuditRequest(project=1, dry_run=True))
check(len(r["bad"]) == 1 and r["downgradable"] == 0,
      "находка видна, но понижать её больше не предлагают")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
