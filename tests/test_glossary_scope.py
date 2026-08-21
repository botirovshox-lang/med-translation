"""Регрессии на 10 находок критика. Реальные данные не трогаем."""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
# Тест не ходит в сеть: внешние корпуса отвечают по-разному в разные дни,
# а проверка обязана давать один и тот же ответ. Их поведение проверяется
# отдельно, на подменённом источнике.
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
H = main._text_hash
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg(sid, source, target, status="translated", bc=95, findings=(), repair=None,
        tc_model="gpt-x", no_bc=False, no_tc=False):
    s = {"id": sid, "source": source, "target": target, "status": status}
    h = H(target)
    if not no_bc:
        s["backcheck"] = {"score": bc, "target_hash": h, "back": "..."}
    if not no_tc:
        s["termcheck"] = {"findings": list(findings), "target_hash": h, "model": tc_model}
    if repair:
        s["repair"] = repair
    return s


def base_state(**kw):
    st = {"projects": [], "glossary": [], "tm": [], "termQueue": [],
          "exportHistory": [], "team": []}
    st.update(kw)
    main.STATE = st
    main._invalidate_gloss_index()
    return st


P_EN = {"id": 1, "src": "RU", "tgt": "EN", "domain": "medical", "segments": []}
P_DE = {"id": 2, "src": "RU", "tgt": "DE", "domain": "legal", "segments": []}


print("\n=== 1. TM: подтверждение RU→DE не переписывает RU→EN ===")
base_state(tm=[{"src": "острый живот", "tgt": "acute abdomen", "lang": "RU→EN",
                "quality": "verified", "score": 100}])
main._tm_upsert("острый живот", "akutes Abdomen", P_DE)
rows = {(t["src"], t["lang"]): t["tgt"] for t in main.STATE["tm"]}
check(rows.get(("острый живот", "RU→EN")) == "acute abdomen", "английская запись цела")
check(rows.get(("острый живот", "RU→DE")) == "akutes Abdomen", "немецкая заведена отдельно")
check(len(main.STATE["tm"]) == 2, "записей стало две, а не одна перезаписанная")

print("\n=== 2. Ручная правка выводит запись из-под отката пачки ===")
base_state(
    projects=[dict(P_EN, segments=[seg(1, "спазм", "spasm"), seg(2, "спазм", "spasm")])],
    glossary=[],
    termQueue=[{"id": 1, "kind": "segment", "src": "спазм", "tgt": "spasm",
                "status": "pending", "hits": 2, "segments": ["1:1", "1:2"],
                "lang": "RU→EN", "domain": "medical", "via": "auto"}])
res = main.auto_approve_terms(main.AutoApproveRequest(dry_run=False, project=1))
batch = res["batch"]
main.save_term(main.TermRequest(src="спазм", tgt="cramp", cat="Term", conf="high"))
check(main.STATE["glossary"][0]["tgt"] == "cramp", "человек исправил перевод")
main.undo_auto_approve(batch)
left = {t["src"]: t for t in main.STATE["glossary"]}
check(left.get("спазм", {}).get("tgt") == "cramp", "откат НЕ стёр правку человека")

print("\n=== 3. Правка без области не плодит дубль ===")
base_state(glossary=[{"src": "договор", "tgt": "Vertrag", "tier": "verified",
                      "lang": "RU→DE", "domain": "legal"}])
main.save_term(main.TermRequest(src="договор", tgt="Vertragsurkunde", cat="Term", conf="high"))
check(len(main.STATE["glossary"]) == 1, "запись одна, дубля нет")
check(main.STATE["glossary"][0]["tgt"] == "Vertragsurkunde", "правка легла в существующую")
check(main.STATE["glossary"][0].get("lang") == "RU→DE", "область записи сохранена")

print("\n=== 4. Перепроверка внутри ремонта не собирает терминологию ===")
base_state(projects=[dict(P_EN, segments=[])])
proj = main.STATE["projects"][0]
s1 = seg(1, "стент", "stent")
proj["segments"].append(s1)
main._openai_termcheck = lambda *a, **k: {"findings": [], "model": "fake"}
main._run_segment_termcheck(s1, proj, harvest=False)
check(len(main.STATE["termQueue"]) == 0, "harvest=False — очередь пуста")
main._run_segment_termcheck(s1, proj, harvest=True)
check(len(main.STATE["termQueue"]) == 1, "harvest=True — пара собрана")
import re as _re
src_all = open("backend/main.py", encoding="utf-8").read()
check("_run_segment_backcheck(seg, project, bc_model, use_judge, judge_model, harvest=False)" in src_all,
      "ремонт зовёт back-check с harvest=False")
check("_run_segment_termcheck(seg, project, tc_model, harvest=False)" in src_all,
      "ремонт зовёт termcheck с harvest=False")

print("\n=== 5. Кандидаты извлечения получают область ===")
_extract_block = src_all[src_all.index('_queue_term("extract"'):][:400]
check("lang=_sc[0], domain=_sc[1]" in _extract_block,
      "extract помечается языковой парой и тематикой")
check("_glossary_entry(item.get(\"src\", \"\"), _sc)" in src_all,
      "«уже знаем эту пару» проверяется в своей области")

print("\n=== 6. Дубль пары внутри пачки пишется один раз и переживает откат ===")
base_state(
    projects=[dict(P_EN, segments=[seg(1, "шунт", "shunt"), seg(2, "шунт", "shunt")])],
    termQueue=[
        {"id": 1, "kind": "segment", "src": "шунт", "tgt": "shunt", "status": "pending",
         "hits": 2, "segments": ["1:1", "1:2"], "lang": "RU→EN", "domain": "medical", "via": "auto"},
        {"id": 2, "kind": "audit", "src": "шунт", "tgt": "shunt", "status": "pending",
         "hits": 2, "segments": ["1:1", "1:2"], "lang": "RU→EN", "domain": "medical", "via": "auto"},
    ])
res = main.auto_approve_terms(main.AutoApproveRequest(dry_run=False, project=1))
check(sum(1 for g in main.STATE["glossary"] if g["src"] == "шунт") == 1, "запись создана один раз")
main.undo_auto_approve(res["batch"])
check(not any(g["src"] == "шунт" for g in main.STATE["glossary"]), "откат снял её полностью")
check(all(c["status"] == "pending" for c in main.STATE["termQueue"]), "оба кандидата вернулись")

print("\n=== 7. Удаление термина не трогает чужую область ===")
base_state(glossary=[
    {"src": "договор", "tgt": "contract", "lang": "RU→EN", "domain": "legal"},
    {"src": "договор", "tgt": "Vertrag", "lang": "RU→DE", "domain": "legal"}])
main.delete_term("договор", lang="RU→EN", domain="legal")
left = [(g["tgt"], g["lang"]) for g in main.STATE["glossary"]]
check(left == [("Vertrag", "RU→DE")], "удалена только запрошенная пара")

# Без области: удаляем запись области по умолчанию, чужую не трогаем
base_state(glossary=[
    {"src": "спазм", "tgt": "spasm"},                                     # легаси = RU→EN/medical
    {"src": "спазм", "tgt": "Krampf", "lang": "RU→DE", "domain": "medical"}])
main.delete_term("спазм")
left = [(g["tgt"], g.get("lang")) for g in main.STATE["glossary"]]
check(left == [("Krampf", "RU→DE")], "без области снесена только запись области по умолчанию")

# Область не назвали, в области по умолчанию записи нет, претендент один
base_state(glossary=[{"src": "иск", "tgt": "Klage", "lang": "RU→DE", "domain": "legal"}])
main.delete_term("иск")
check(main.STATE["glossary"] == [], "единственную запись удаляем и без области")

# Претендентов несколько и область не назвали — не угадываем
base_state(glossary=[
    {"src": "иск", "tgt": "Klage", "lang": "RU→DE", "domain": "legal"},
    {"src": "иск", "tgt": "claim", "lang": "RU→EN", "domain": "legal"}])
try:
    main.delete_term("иск")
    check(False, "неоднозначное удаление должно отклоняться")
except main.HTTPException as e:
    check(e.status_code == 404 and len(main.STATE["glossary"]) == 2,
          "неоднозначное удаление отклонено, обе записи целы")

print("\n=== 8. Очередь не растёт бесконечно, но решения человека целы ===")
base_state()
q = main.STATE["termQueue"]
q.append({"id": 1, "kind": "conflict", "src": "важный", "tgt": "", "status": "pending",
          "hits": 1, "via": "confirmed"})
q.append({"id": 2, "kind": "segment", "src": "тоже важный", "tgt": "x", "status": "pending",
          "hits": 1, "via": "confirmed"})
for i in range(main.TERM_QUEUE_MAX + 50):
    q.append({"id": 100 + i, "kind": "segment", "src": "мусор%d" % i, "tgt": "junk%d" % i,
              "status": "pending", "hits": 1, "via": "auto"})
main._trim_term_queue()
ids = {c["id"] for c in main.STATE["termQueue"]}
check(len(main.STATE["termQueue"]) <= main.TERM_QUEUE_MAX, "очередь подрезана до потолка")
check(1 in ids, "кандидат-конфликт не выброшен")
check(2 in ids, "пришедший с подтверждённого сегмента не выброшен")

print("\n=== 9. Пропущенный termcheck не считается чистой проверкой ===")
base_state()
skipped = seg(1, "Метформин", "Метформин", tc_model="skip")
check(main._machine_clean(skipped, 90) is not None, "termcheck=skip → сегмент не чистый")
checked = seg(2, "спазм", "spasm")
check(main._machine_clean(checked, 90) is None, "нормально проверенный — чистый")

print("\n=== 10. «Где используется» берёт запись своей области ===")
base_state(
    projects=[dict(P_EN, segments=[seg(1, "договор подряда", "work contract")])],
    glossary=[{"src": "договор", "tgt": "Vertrag", "lang": "RU→DE", "domain": "legal"},
              {"src": "договор", "tgt": "contract", "lang": "RU→EN", "domain": "legal"}])
r = main.glossary_usage("договор", limit=6, lang="RU→EN", domain="legal")
check(r["tgt"] == "contract", "взят перевод нужной языковой пары")
viol = sum(len(p.get("violating", [])) for p in r["projects"])
check(viol == 0, "перевод соответствует — нарушений не найдено")

print("\n=== 11. Удаление TM не трогает чужую пару языков ===")
base_state(tm=[{"src": "острый живот", "tgt": "acute abdomen", "lang": "RU→EN"},
               {"src": "острый живот", "tgt": "akutes Abdomen", "lang": "RU→DE"}])
main.delete_tm("острый живот", lang="RU→EN")
check([t["lang"] for t in main.STATE["tm"]] == ["RU→DE"], "удалена только английская запись")
base_state(tm=[{"src": "x", "tgt": "a", "lang": "RU→EN"},
               {"src": "x", "tgt": "b", "lang": "RU→DE"}])
main.delete_tm("x")
check([t["lang"] for t in main.STATE["tm"]] == ["RU→DE"],
      "без параметра удаляется запись пары по умолчанию")
# Ни одной записи в паре по умолчанию, а претендентов двое — не угадываем
try:
    base_state(tm=[{"src": "y", "tgt": "b", "lang": "RU→DE"},
                   {"src": "y", "tgt": "c", "lang": "RU→UZ"}])
    main.delete_tm("y")
    check(False, "неоднозначное удаление TM должно отклоняться")
except main.HTTPException:
    check(len(main.STATE["tm"]) == 2, "неоднозначное удаление отклонено, обе записи целы")

print("\n=== 12. «Где используется»: чужая область не выигрывает ===")
base_state(
    projects=[{"id": 1, "src": "RU", "tgt": "EN", "domain": "medical",
               "segments": [seg(1, "спазм сосудов", "vascular spasm")]}],
    # Запись чужой пары лежит ПЕРВОЙ — раньше запасной поиск выбирал именно её
    glossary=[{"src": "спазм", "tgt": "Krampf", "lang": "RU→DE", "domain": "medical"},
              {"src": "спазм", "tgt": "spasm"}])
r = main.glossary_usage("спазм", limit=6)
check(r["tgt"] == "spasm", "без области взята запись области по умолчанию")
check(sum(len(p.get("violating", [])) for p in r["projects"]) == 0,
      "сегмент не помечен нарушением")

print("\n=== 13. Вторая пачка не наступает на запись первой ===")
base_state(
    projects=[dict(P_EN, segments=[seg(1, "спазм сосудов", "vascular spasm"),
                                   seg(2, "мышечный спазм", "muscle spasm")])],
    termQueue=[{"id": 1, "kind": "extract", "src": "спазм", "tgt": "spasm",
                "status": "pending", "hits": 2, "segments": ["1:1", "1:2"],
                "lang": "RU→EN", "domain": "medical", "via": "auto"}])
first = main.auto_approve_terms(main.AutoApproveRequest(dry_run=False, project=1))
main.STATE["termQueue"].append({"id": 2, "kind": "extract", "src": "спазм", "tgt": "cramp",
                                "status": "pending", "hits": 2, "segments": ["1:1", "1:2"],
                                "lang": "RU→EN", "domain": "medical", "via": "auto"})
second = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
reasons = " ".join(b["reason"] for b in second["skipped"])
check("занята пачкой" in reasons, "кандидат отложен: запись принадлежит прошлой пачке")
check(main.STATE["glossary"][0]["tgt"] == "spasm", "значение первой пачки не переписано")
main.undo_auto_approve(first["batch"])
check(not main.STATE["glossary"], "первая пачка по-прежнему откатывается")

print("\n=== 14. Откат возвращает запись целиком ===")
base_state(
    projects=[dict(P_EN, segments=[seg(1, "задний отдел", "posterior part"),
                                   seg(2, "задний свод", "posterior fornix")])],
    glossary=[{"src": "задний", "tgt": "rear", "tier": "auto", "cat": "Anatomy",
               "conf": "low", "note": "импорт", "origin": "baldwin_2019"}],
    termQueue=[{"id": 1, "kind": "extract", "src": "задний", "tgt": "posterior",
                "status": "pending", "hits": 2, "segments": ["1:1", "1:2"],
                "lang": "RU→EN", "domain": "medical", "via": "auto"}])
res = main.auto_approve_terms(main.AutoApproveRequest(dry_run=False, project=1))
main.undo_auto_approve(res["batch"])
g = main.STATE["glossary"][0]
check(g["tgt"] == "rear" and g["tier"] == "auto", "перевод и уровень доверия вернулись")
check(g["conf"] == "low", "достоверность вернулась")
check(g["origin"] == "baldwin_2019", "происхождение вернулось, а не стёрлось")
check("autoBatch" not in g and "prevConf" not in g, "служебные пометки убраны")

print("\n=== 15. Новый термин заводится в области открытого проекта ===")
ui = open("frontend/js/tab_glossary_tm.jsx", encoding="utf-8").read()
check("lang: term ? term.lang : (scope || {}).lang || null" in ui,
      "модалка берёт область у проекта для новой записи")
check("scope: store.activeProject" in ui, "область передаётся из активного проекта")
check("if (res.batch) setBatches" in ui, "пустая пачка не попадает в историю")

print("\n=== 16. Индекс по термину сбрасывается на любой правке ===")
base_state(glossary=[{"src": "спазм", "tgt": "spasm"}])
check(main._glossary_entry("спазм", ("RU→EN", "medical")) is not None, "запись найдена")
main.delete_term("спазм")
check(main._glossary_entry("спазм", ("RU→EN", "medical")) is None,
      "после удаления индекс не отдаёт призрак")
main.save_term(main.TermRequest(src="спазм", tgt="cramp", cat="Term", conf="high", isNew=True))
check((main._glossary_entry("спазм", ("RU→EN", "medical")) or {}).get("tgt") == "cramp",
      "после добавления индекс видит новую запись")

print("\n=== 17. Пачка, выпавшая из истории, освобождает записи ===")
base_state(glossary=[{"src": "спазм", "tgt": "spasm", "tier": "auto", "autoBatch": 5,
                      "autoCreated": True, "prevTgt": "cramp"}],
           termQueue=[{"id": 1, "src": "спазм", "tgt": "spasm", "status": "approved",
                       "autoBatch": 5}])
main.STATE["autoBatches"] = [{"id": 5}]
main._forget_auto_batch(5)
g = main.STATE["glossary"][0]
check("autoBatch" not in g and "prevTgt" not in g, "пометки сняты — запись больше не заперта")
check(main.STATE["termQueue"][0].get("autoBatch") is None, "у кандидата пометка тоже снята")

print("\n=== 18. Подрезка не съедает кандидатов живой пачки ===")
base_state()
main.STATE["autoBatches"] = [{"id": 7}]
q = main.STATE["termQueue"]
q.append({"id": 1, "src": "важный", "tgt": "x", "status": "approved", "autoBatch": 7})
for i in range(main.TERM_QUEUE_MAX + 50):
    q.append({"id": 100 + i, "src": "старьё%d" % i, "tgt": "y", "status": "approved"})
main._trim_term_queue()
check(any(c["id"] == 1 for c in main.STATE["termQueue"]),
      "кандидат откатываемой пачки уцелел")
check(len(main.STATE["termQueue"]) <= main.TERM_QUEUE_MAX, "очередь всё же подрезана")

print("\n=== 19. UI и движок одинаково видят устаревание проверки ===")
base_state()
s = {"id": 1, "source": "спазм", "target": "spasm ",   # хвостовой пробел
     "backcheck": {"score": 95, "target_hash": H("spasm")},
     "termcheck": {"findings": [], "target_hash": H("spasm"), "model": "gpt-x"}}
view = main._segment_for_client(s)
check(view["backcheck"]["stale"] is False, "UI не считает проверку устаревшей")
check(main._machine_clean(s, 90) is None, "движок считает сегмент чистым — оценки совпали")
s2 = dict(s, target="spasms")
view2 = main._segment_for_client(s2)
check(view2["backcheck"]["stale"] is True, "изменённый текстUI помечает устаревшим")
check(main._machine_clean(s2, 90) is not None, "и движок тоже")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
