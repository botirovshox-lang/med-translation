"""Заверенный человеком перевод с находками: кто его видит и кто вправе чинить.

Проверяется то, из-за чего неверные подтверждённые сегменты висели месяцами:
  1. разбор прогона и сам прогон расходились — разбор отбрасывал подтверждённые
     безусловно, а батч брал их по флагу;
  2. включение флага не должно добавлять работы никому, кроме ремонта:
     «починить подтверждённые» — это точечная правка по находкам, а не
     повторный прогон проекта за полную цену;
  3. в разборе проекта такие сегменты растворялись среди машинных.

Ни одного платного вызова: модель ремонта и termcheck подменены.
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


def seg(sid, source, target, status="translated"):
    return {"id": sid, "source": source, "target": target, "status": status, "risk": "medium",
            "provider": "gpt-5.5"}


def fresh_bc(sg, model="gpt-5.6-luna", score=95, reasons=(), terms_lost=()):
    sg["backcheck"] = {"score": score, "band": "green", "model": model, "back": sg["source"],
                       "reasons": list(reasons), "terms_lost": list(terms_lost),
                       "judged": False, "judge_skipped": "zone",
                       "target_hash": main._text_hash(sg["target"].strip()),
                       "at": "2026-08-01 10:00"}


def fresh_tc(sg, findings=(), model="gpt-5.6-sol"):
    sg["termcheck"] = {"findings": list(findings), "severity": "none", "model": model,
                       "target_hash": main._text_hash(sg["target"].strip()),
                       "at": "2026-08-01 10:00"}


BAD_TERM = {"severity": "major", "tgt_term": "rear cyclitis",
            "suggestion": "posterior cyclitis", "why": "калька"}


def build(segments, gloss=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss], "tm": [],
                  "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._IMPACT_CACHE.clear()
    main._ANALYSIS_CACHE.clear()
    return proj


def fixture():
    """Три сегмента: заверенный с находкой, машинный с находкой, заверенный чистый.

    У заверенного находка СВЕЖАЯ и back-check тоже свежий — иначе включение
    галочки добавило бы работы проверкам, и «точечность» проверить было бы не на чем.
    """
    proj = build([seg(1, "задний циклит", "rear cyclitis", status="confirmed"),
                  seg(2, "задний циклит справа", "rear cyclitis on the right"),
                  seg(3, "жалобы", "complaints", status="confirmed")])
    a, b, c = proj["segments"]
    a["confirmedBy"] = "human"
    c["confirmedBy"] = "human"
    for s in (a, b):
        fresh_bc(s)
        fresh_tc(s, [BAD_TERM])
    fresh_bc(c)
    fresh_tc(c)
    return proj


def step(plan, key):
    return next(p for p in plan["steps"] if p["step"] == key)


def reasons(block, kind):
    return " · ".join(r["reason"] for r in block[kind])


# ───────── 1. Разбор без разрешения: молчать нельзя, причина названа ─────────
print("=== 1. Без галочки подтверждённый не берётся, но и не исчезает ===")
proj = fixture()
plan = main.run_plan(1, main.RunPlanRequest(steps=["repair"]))
rp = step(plan, "repair")
check(rp["ids"] == [2], "в ремонт идёт только машинный сегмент: " + str(rp["ids"]))
check("заверено человеком" in reasons(rp, "skips"),
      "заверенный назван в пропусках с причиной: " + reasons(rp, "skips"))
check("включите" in reasons(rp, "skips"),
      "и человеку сказано, чем это включается, а не просто «нельзя»")

# ───────── 2. С разрешением берётся, и последствие названо ─────────
print("\n=== 2. С галочкой берётся, и сказано, чем это обернётся ===")
plan_on = main.run_plan(1, main.RunPlanRequest(steps=["repair"], include_confirmed=True))
rp_on = step(plan_on, "repair")
check(rp_on["ids"] == [1, 2], "в ремонт идут оба: " + str(rp_on["ids"]))
check("подтверждение будет снято" in reasons(rp_on, "runs"),
      "последствие названо прямо в разборе: " + reasons(rp_on, "runs"))

# ───────── 3. Точечность: платит только ремонт ─────────
print("\n=== 3. Галочка добавляет работы ТОЛЬКО ремонту ===")
# Ради этого всё и затевалось: человек просил починить найденное, а не оплатить
# повторный прогон проекта. Свежие проверки на подтверждённом сегменте есть,
# значит ни back-check, ни termcheck, ни Medical QA не должны его перевзять.
all_off = main.run_plan(1, main.RunPlanRequest())
all_on = main.run_plan(1, main.RunPlanRequest(include_confirmed=True))
for k in ("translate", "backcheck", "termcheck", "medical_qa"):
    a, b = step(all_off, k), step(all_on, k)
    check(a["count"] == b["count"],
          "шаг «%s» не подорожал: %d против %d" % (k, a["count"], b["count"]))
check(step(all_on, "repair")["count"] - step(all_off, "repair")["count"] == 1,
      "подорожал ровно ремонт и ровно на один сегмент")

# ───────── 4. Разбор обещает то, что прогон сделает ─────────
print("\n=== 4. Разбор и прогон берут один и тот же список ===")
main._openai_repair = lambda *a, **k: "posterior cyclitis"
main._run_segment_termcheck = lambda sg, *a, **k: sg.__setitem__(
    "termcheck", {"findings": [], "model": "test",
                  "target_hash": main._text_hash(sg["target"].strip())})
main._run_segment_backcheck = lambda sg, *a, **k: sg.__setitem__(
    "backcheck", dict(sg.get("backcheck") or {}, score=99,
                      target_hash=main._text_hash(sg["target"].strip())))

proj = fixture()
r = main.repair_batch(1, main.RepairBatchRequest(limit=10, include_confirmed=True))
took = sorted(r["applied"] + r["skipped"])
check(took == rp_on["ids"],
      "прогон взял ровно тех, кого обещал разбор: %s против %s" % (took, rp_on["ids"]))
check(proj["segments"][0]["status"] == "review", "заверенный ушёл на проверку человеком")
check("confirmedBy" not in proj["segments"][0],
      "и отметка «подтвердил человек» снята: она относилась к прежнему тексту")
check(proj["segments"][0].get("prevTarget") == "rear cyclitis",
      "прежний текст сохранён — откатывать есть к чему")
check(proj["segments"][2]["status"] == "confirmed",
      "заверенный БЕЗ находок не тронут: чиним найденное, а не всё подряд")

# ───────── 5. Составной прогон: флаг живёт только на шаге ремонта ─────────
print("\n=== 5. В составном прогоне разрешение не протекает в перевод ===")
proj = fixture()
seen = {}


def spy(name, res):
    def f(pid, req):
        seen[name] = getattr(req, "include_confirmed", None)
        return res
    return f


main.batch_translate = spy("translate", {"count": 0, "errors": [], "tm_hits": 0,
                                         "duplicates": 0, "skipped_confirmed": []})
main.repair_batch = spy("repair", {"applied": [1], "skipped": [], "errors": []})
main._job_chunk_full(1, [1, 2], {"steps": ["translate", "repair"], "include_confirmed": True})
check(seen.get("repair") is True, "ремонт разрешение получил")
check(seen.get("translate") is False,
      "перевод — нет: иначе одна галочка перегнала бы заверенное заново за полную цену")

seen.clear()
main._job_chunk_full(1, [1, 2], {"steps": ["repair"]})
check(seen.get("repair") is False, "без галочки разрешения нет ни у кого")

# ───────── 6. Отдельный прогон ремонта тоже несёт флаг ─────────
print("\n=== 6. Кнопка «только этот шаг» ведёт себя так же ===")
seen.clear()
main._job_chunk("repair", 1, [1, 2], {"include_confirmed": True})
check(seen.get("repair") is True,
      "отдельный прогон ремонта передаёт разрешение — иначе кнопка молча "
      "пропускала бы то, что посчитала")

# ───────── 7. Разбор проекта: своя корзина, а не «оценка ниже порога» ─────────
print("\n=== 7. На экране итогов такие сегменты названы своим именем ===")
# project_analysis не вызывает ни перевод, ни ремонт — заглушки выше ему не мешают.
proj = fixture()
res = main.project_analysis(1, refresh=True)
check(res["human"]["confirmedFindings"] == [1],
      "подтверждённый с находкой — в своей корзине: " + str(res["human"]["confirmedFindings"]))
check(1 not in res["todo"]["findings"],
      "и не в общей корзине замечаний: её чинит прогон сам, а этот сегмент — нет")
check(1 not in res["todo"]["weak"],
      "и не в «оценке ниже порога», где он выглядел машинным")
check(2 in res["todo"]["findings"], "машинный сегмент с находкой остался на своём месте")
check(3 in res["clean"], "заверенный чистый сегмент по-прежнему считается чистым")

ids = set(res["clean"]) | set(res["todo"]["findings"]) | set(res["todo"]["weak"]) \
    | set(res["todo"]["unchecked"]) | set(res["todo"]["untranslated"]) \
    | set(res["human"]["confirmedFindings"])
check(ids == {1, 2, 3},
      "корзины по-прежнему исчерпывающие — ни один сегмент не исчез с экрана")

# ───────── 8. Висящий пробел не прячет находки ─────────
print("\n=== 8. Пробел в конце перевода не отменяет находки ===")
# Проверки пишут хеш ОБРЕЗАННОГО текста. Пока ремонт сравнивал с необрезанным,
# у такого сегмента находок «не было»: он выпадал и из ремонта, и из корзин
# разбора — при том, что на экране проверки числились свежими.
proj = fixture()
sloppy = proj["segments"][0]
sloppy["target"] = sloppy["target"] + " "          # хеши проверок при этом не трогаем
check(len(main._repair_findings(sloppy)) > 0,
      "находки видны и у перевода с висящим пробелом")
res = main.project_analysis(1, refresh=True)
check(1 in res["human"]["confirmedFindings"],
      "и сегмент по-прежнему в своей корзине, а не пропал с экрана")
plan8 = main.run_plan(1, main.RunPlanRequest(steps=["repair"], include_confirmed=True))
check(1 in step(plan8, "repair")["ids"], "и ремонт его берёт")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
