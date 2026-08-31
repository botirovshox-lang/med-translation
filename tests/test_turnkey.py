"""Корзины «под ключ» в /analysis и разрешение judge_all.

Проверяется то, из-за чего экран «Анализ» врал бы пользователю под ключ:
  1. judge_all открывает судье ВЕРХ зоны (балл 98 без вердикта — работа),
     но не низ и не жёсткую отметку;
  2. без judge_all состав back-check такие сегменты не берёт, с ним — берёт
     (иначе корзина «возьмёт прогон» была бы недостижимым числом);
  3. три корзины turnkey не пересекаются и в сумме дают total: сегмент,
     не попавший ни в одну, исчез бы с экрана;
  4. раздача по корзинам: непереведённый и балл-98-без-судьи — машине;
     заверенное с обычной находкой, спор с приказом и критика Medical QA
     на подтверждённом — человеку; чистый и судимый — готов;
  5. подтверждённый с критикой Medical QA виден в human.qaCritical —
     раньше его показывала только вкладка «Замечания», которой больше нет;
  6. params корзины требуют judge_all=True: кнопка обязана слать их же.

Ни одного платного вызова: модель не трогается вовсе.
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


def seg(sid, source, target="", status="translated"):
    return {"id": sid, "source": source, "target": target,
            "status": status, "risk": "medium"}


def build(segments):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


def bc_done(sg, score=95, judged=False, reasons=(), skipped=None):
    sg["backcheck"] = {"score": score, "band": "green", "model": "gpt-4o-mini",
                      "back": sg["source"], "reasons": list(reasons),
                      "terms_lost": [], "judged": judged,
                      "judge_skipped": skipped,
                      "target_hash": main._text_hash(sg["target"].strip()),
                      "at": "2026-08-01 10:00"}


def tc_done(sg, findings=()):
    sg["termcheck"] = {"findings": list(findings), "severity": "none",
                       "model": "gpt-5.6-terra",
                       "target_hash": main._text_hash(sg["target"].strip()),
                       "at": "2026-08-01 10:00"}


LONG_RU = "Очаговый туберкулёз лёгких характеризуется ограниченным поражением верхних долей"
LONG_EN = "Focal pulmonary tuberculosis is characterized by limited involvement of upper lobes"

# ─────────────── 1. judge_all и предикат _judge_pending ───────────────
print("=== 1. judge_all открывает верх зоны, но не низ и не жёсткую отметку ===")
s98 = seg(1, LONG_RU, LONG_EN)
bc_done(s98, score=98)
check(not main._judge_pending(s98), "балл 98 без разрешения — судья не нужен (выше зоны)")
check(main._judge_pending(s98, above=True), "с judge_all балл 98 — работа судьи")

s98j = seg(2, LONG_RU, LONG_EN)
bc_done(s98j, score=98, judged=True)
check(not main._judge_pending(s98j, above=True), "судимый сегмент второй раз не судится")

shard = seg(3, LONG_RU, LONG_EN)
bc_done(shard, score=98, skipped="hard", reasons=["расхождение чисел: 5 против 50"])
shard["backcheck"]["v"] = main._bc_version()
check(not main._judge_pending(shard, above=True),
      "жёсткая отметка (числа) не обходится и с judge_all")

slow = seg(4, LONG_RU, LONG_EN)
bc_done(slow, score=20)
check(not main._judge_pending(slow, above=True),
      "низ зоны judge_all не открывает: там решение настоящее")

# ─────────────── 2. Состав back-check читает judge_all ───────────────
print("")
print("=== 2. _plan_step: без judge_all пропуск, с ним — работа ===")
proj = build([s98])
scope = proj["segments"]
p_no = main._plan_step(proj, "backcheck", {"use_judge": True}, scope, set(), set())
p_yes = main._plan_step(proj, "backcheck", {"use_judge": True, "judge_all": True},
                        scope, set(), set())
check(p_no["count"] == 0, "без разрешения сегмент 98 не берётся: " + str(p_no["count"]))
check(p_yes["count"] == 1, "с разрешением берётся: " + str(p_yes["count"]))
mdl = main._resolve_model(None)["id"]
check(main._backcheck_cached(scope[0], "gpt-4o-mini", True, False)
      and not main._backcheck_cached(scope[0], "gpt-4o-mini", True, True),
      "_backcheck_cached: закрыт без разрешения, открыт с ним")

# ─────────────── 3. Корзины turnkey: исчерпывающие и непересекающиеся ───────────────
print("")
print("=== 3. Три корзины дают total без пересечений ===")
sready = seg(11, LONG_RU, LONG_EN)          # чисто и судья смотрел
bc_done(sready, score=96, judged=True)
tc_done(sready)
snew = seg(12, "Новый сегмент про туберкулёз")               # не переведён
sjudge = seg(13, LONG_RU, LONG_EN)          # балл 98, судья не смотрел
bc_done(sjudge, score=98)
tc_done(sjudge)
sconf = seg(14, LONG_RU, LONG_EN, status="confirmed")   # заверен + находка
bc_done(sconf, score=96, judged=True)
tc_done(sconf, findings=[{"severity": "major", "tgt_term": "upper lobes",
                          "suggestion": "superior lobes"}])
sqa = seg(15, LONG_RU, LONG_EN, status="confirmed")     # заверен + критика QA
bc_done(sqa, score=96, judged=True)
tc_done(sqa)
sqa["qa_issues"] = [{"severity": "critical", "type": "numeric", "msg": "число"}]
sqa["qa_result"] = {"target_hash": main._text_hash(LONG_EN), "risk_color": "red"}
sqa["risk_color"] = "red"
sun = seg(16, LONG_RU, LONG_EN)             # переведён, не проверен
proj = build([sready, snew, sjudge, sconf, sqa, sun])
res = main.project_analysis(1, refresh=True)
tk = res.get("turnkey") or {}
r, m, h = set(tk.get("ready") or ()), set(tk.get("machine") or ()), set(tk.get("human") or ())
check(bool(tk), "блок turnkey в ответе есть")
check(len(r | m | h) == res["total"] and not (r & m) and not (r & h) and not (m & h),
      "корзины исчерпывающие и непересекающиеся: %s + %s + %s = %s"
      % (len(r), len(m), len(h), res["total"]))
check(11 in r, "чистый судимый сегмент — готов")
check(12 in m, "непереведённый — машине")
check(13 in m, "балл 98 без судьи — машине (judge_all)")
check(16 in m, "непроверенный — машине")
check(14 in h, "заверенный с обычной находкой — человеку")
check(15 in h, "заверенный с критикой Medical QA — человеку")
check(res["human"].get("qaCritical") == [15],
      "и виден в human.qaCritical: " + str(res["human"].get("qaCritical")))
prm = tk.get("params") or {}
check(prm.get("judge_all") is True and prm.get("use_judge") is True
      and prm.get("include_confirmed") is False,
      "params корзины: судья с разрешением, заверённые не трогаются")

# ─────────────── 3b. failed с пустым переводом осушается прогоном ───────────────
print("")
print("=== 3b. failed без текста: в корзине машины И в шаге перевода ===")
sfail = seg(21, "Не переведённый из-за сбоя", status="failed")
proj = build([sfail])
res2 = main.project_analysis(1, refresh=True)
tk2 = res2.get("turnkey") or {}
check(21 in set(tk2.get("machine") or ()), "корзина: машине")
pt = main._plan_step(proj, "translate", {}, proj["segments"], set(), set())
check(pt["count"] == 1, "шаг перевода его берёт: " + str(pt["count"]))
check(any("не удался" in r["reason"] for r in pt["runs"]),
      "и называет причину честно, а не «уже переведён»")
# failed с НЕПУСТЫМ переводом — не «не переведён»: там прежний текст,
# и его судьба решается проверками, а не молчаливым перепереводом.
skept = seg(22, "Есть перевод", "Has translation", status="failed")
check(not main._needs_translation(skept), "failed с текстом переводу не отдаётся")
check(main._needs_translation(seg(23, "Пусто", "", status="failed")),
      "а failed без текста — отдаётся")

# will_translate обязан читать ТОТ ЖЕ предикат: иначе проверки скажут
# «нет перевода» про сегменты, которые этот же прогон переведёт.
proj = build([sfail])
plan = main.run_plan(1, main.RunPlanRequest(steps=["translate", "backcheck"],
                                            use_judge=True, judge_all=True))
bc_plan = [p for p in plan["steps"] if p["step"] == "backcheck"][0]
check(bc_plan["count"] == 1,
      "back-check считает сегмент, который переведут в этом же прогоне: "
      + str(bc_plan["count"]))
check(any("появится после перевода" in r["reason"] for r in bc_plan["runs"]),
      "и причина названа именно так")

# ─────────────── 3c. Судья симметричен в ремонте ───────────────
print("")
print("=== 3c. judge_all доезжает до перепроверки внутри ремонта ===")
import inspect
src_rep = inspect.getsource(main._run_segment_repair)
check("judge_all=judge_all" in src_rep,
      "перепроверка ремонта получает judge_all — иначе вердикт сравнивался бы "
      "с сырым измерением")
check("judge_all" in inspect.signature(main.RepairBatchRequest).parameters
      or "judge_all" in main.RepairBatchRequest.__fields__,
      "и пакетный ремонт умеет его принять")
# Потолок разрешения живёт в ОДНОМ месте.
check(main._judge_zone(LONG_RU)[1] == main.JUDGE_ZONE[1]
      and main._judge_zone(LONG_RU, True)[1] == 100,
      "_judge_zone сам знает про разрешение: %s / %s"
      % (main._judge_zone(LONG_RU), main._judge_zone(LONG_RU, True)))
check(main._judge_zone(LONG_RU, True)[0] == main.JUDGE_ZONE[0],
      "низ зоны разрешение не трогает")

# ───────── 3d. Разнобой у ЗАВЕРЕННОГО сегмента — человеку, не машине ─────────
# Ловушка тонкая: `_consist_misses` без проекта возвращает пусто, а /analysis
# зовёт `_repair_findings` именно без проекта — значит в confirmed_findings
# такой сегмент не попадёт и сам в «человека» не уйдёт. Прогон же идёт
# с include_confirmed=False и его пропустит. Оставь его машине — и корзина
# «возьмёт прогон» будет держать число, которое не осушится никогда.
print("")
print("=== 3d. Разнобой на заверенном сегменте не обещают машине ===")
sc1 = seg(31, LONG_RU, LONG_EN, status="confirmed")
bc_done(sc1, score=96, judged=True)
tc_done(sc1)
proj = build([sc1])
_saved = main._consistency_of
main._consistency_of = lambda p: [{"was": "MBT", "want": "MTB", "why": "разнобой",
                                   "segments": [31], "already": 0}]
try:
    main._ANALYSIS_CACHE.clear()
    res3 = main.project_analysis(1, refresh=True)
finally:
    main._consistency_of = _saved
    main._ANALYSIS_CACHE.clear()
tk3 = res3.get("turnkey") or {}
check(31 in set(tk3.get("human") or ()), "заверенный с разнобоем — человеку")
check(31 not in set(tk3.get("machine") or ()),
      "и НЕ обещан прогону, который его не возьмёт")

# ─────────────── 4. Прежний контракт не сломан ───────────────
print("")
print("=== 4. Старые поля /analysis на месте ===")
check(isinstance(res.get("readyIds"), list), "readyIds остался")
check("clean" in res and "todo" in res and "machine" in res, "clean/todo/machine на месте")

# ─────────────── 5. Заверение человека видно корзинам ───────────────
# Раньше подтверждение не меняло на экране НИ ОДНОЙ цифры: заверенный сегмент
# без находок стоял в «возьмёт прогон» из-за недостающего back-check или
# несмотревшего судьи. Человек прочитал и заверил — открытых вопросов нет.
print("")
print("=== 5. Подтверждение вручную двигает корзины ===")
c_unchecked = seg(41, LONG_RU, LONG_EN, status="confirmed")   # заверен, проверок нет
c_judge = seg(42, LONG_RU, LONG_EN, status="confirmed")       # заверен, судья не смотрел
bc_done(c_judge, score=85)
tc_done(c_judge)
u_unchecked = seg(43, LONG_RU, LONG_EN)                       # НЕ заверен, проверок нет
c_find = seg(44, LONG_RU, LONG_EN, status="confirmed")        # заверен + находка
bc_done(c_find, score=96, judged=True)
tc_done(c_find, findings=[{"severity": "major", "tgt_term": "upper lobes",
                           "suggestion": "superior lobes"}])
build([c_unchecked, c_judge, u_unchecked, c_find])
res5 = main.project_analysis(1, refresh=True)
tk5 = res5["turnkey"]
r5, m5, h5 = set(tk5["ready"]), set(tk5["machine"]), set(tk5["human"])
check(41 in r5, "заверенный без проверок — готов (человек и есть проверка)")
check(42 in r5, "заверенный с баллом в зоне судьи — готов, а не «возьмёт прогон»")
check(43 in m5, "тот же сегмент БЕЗ заверения — по-прежнему машине")
check(44 in h5, "заверенный с находкой — по-прежнему человеку, заверение не пропуск")
check(tk5.get("confirmed") == [41, 42, 44],
      "срез «заверено вручную» отдаётся списком в порядке документа")
check(len(r5 | m5 | h5) == res5["total"] and not (r5 & m5) and not (m5 & h5),
      "корзины по-прежнему исчерпывающие и непересекающиеся")

print("")
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
