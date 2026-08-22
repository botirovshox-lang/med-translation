"""Проверка движка автоодобрения на синтетическом STATE.
Реальные данные не трогаем: STATE подменён, save_state замолчан."""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
# Тест не ходит в сеть: внешние корпуса отвечают по-разному в разные дни,
# а проверка обязана давать один и тот же ответ. Их поведение проверяется
# отдельно, на подменённом источнике.
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
# Проверяем ДВИЖОК автоодобрения, а не поставляемые справочники: иначе
# добавление любого источника в authority_data ломало бы эти тесты, хотя
# правила не менялись. Поведение самих справочников — в test_authorities.
main._DICTIONARIES = []

H = main._text_hash
CUR = {"dom": "medical"}


def seg(sid, source, target, status="translated", bc=95, tc_findings=(), repair=None,
        stale=False, no_bc=False, no_tc=False, route=None, by=None):
    s = {"id": sid, "source": source, "target": target, "status": status}
    if route:
        s["route"] = route
    if by:
        s["confirmedBy"] = by
    h = H(target) if not stale else H(target + "x")
    if not no_bc:
        s["backcheck"] = {"score": bc, "target_hash": h, "back": "..."}
    if not no_tc:
        s["termcheck"] = {"findings": list(tc_findings), "severity": "none", "target_hash": h}
    if repair:
        # Настоящий ремонт кладёт хеш текста, который он же и написал: по нему
        # видно, относится запись к нынешнему переводу или он давно заменён.
        # Без хеша сегмент навсегда считался бы «переписанным ремонтом».
        s["repair"] = {"source_hash": H(target), **repair}
    return s


def project(pid, domain, src="RU", tgt="EN", segments=()):
    return {"id": pid, "title": "P%d" % pid, "src": src, "tgt": tgt,
            "domain": domain, "segments": list(segments)}


def cand(cid, src, tgt, donors, kind="segment", lang="RU→EN", domain=None, **extra):
    c = {"id": cid, "kind": kind, "src": src, "tgt": tgt, "status": "pending",
         "hits": len(donors), "segments": list(donors), "lang": lang,
         "domain": domain or CUR["dom"]}
    c.update(extra)
    return c


def build(dom="medical"):
    segs = [seg(1, "спазм", "spasm"), seg(2, "спазм", "spasm"), seg(3, "спазм", "spasm"),
            seg(10, "отёк", "edema"), seg(11, "отёк", "edema"),
            seg(20, "проба", "assay", status="confirmed", no_bc=True, no_tc=True, by="human"),
            # Подтверждён машинно — точным совпадением с TM, а не человеком
            seg(21, "мазок", "smear", status="confirmed", route="EXACT_TM",
                no_bc=True, no_tc=True),
            seg(30, "шов", "suture", no_bc=True),
            seg(40, "задний", "posterior"), seg(41, "задний", "posterior"),
            seg(50, "жалобы", "complaints"), seg(51, "жалобы", "complaints"),
            seg(60, "лихорадка", "fever"), seg(61, "лихорадка", "fever"),
            seg(70, "кашель", "cough", bc=70), seg(71, "кашель", "cough", bc=70),
            seg(80, "стент", "stent", repair={"applied": True}),
            seg(81, "стент", "stent", repair={"applied": True}),
            # Три РАЗНЫХ исходника с одним термином — настоящая независимость
            seg(90, "спазм сосудов купирован", "vascular spasm resolved"),
            seg(91, "мышечный спазм в покое", "muscle spasm at rest"),
            seg(92, "спазм гортани не отмечен", "no laryngeal spasm"),
            # Один и тот же заголовок, размноженный копией внутри порции
            seg(95, "Заключение", "Conclusion"),
            seg(96, "Заключение", "Conclusion", route="DUPLICATE"),
            seg(97, "Заключение", "Conclusion", route="DUPLICATE")]
    CUR["dom"] = dom
    main.STATE = {
        "projects": [project(1, dom, segments=segs),
                     project(2, dom, segments=segs),
                     project(3, "legal", src="RU", tgt="DE", segments=[seg(1, "договор", "Vertrag")])],
        "glossary": [
            {"src": "лихорадка", "tgt": "pyrexia", "tier": "verified", "cat": "Symptom"},
            {"src": "задний", "tgt": "rear", "tier": "auto", "cat": "Anatomy"},
            {"src": "жалобы", "tgt": "complaints", "tier": "verified", "cat": "Symptom"},
        ],
        "tm": [], "termQueue": [], "exportHistory": [], "team": [],
    }
    q = main.STATE["termQueue"]
    q += [
        cand(1, "спазм", "spasm", ["1:1", "1:2", "1:3"]),
        cand(2, "отёк", "edema", ["1:10", "1:11"]),
        cand(3, "отёк", "oedema", ["1:10"]),                       # второй вариант → спор
        cand(4, "проба", "assay", ["1:20"]),                       # подтверждён человеком
        cand(5, "шов", "suture", ["1:30"]),                        # донор без back-check
        cand(6, "задний", "posterior", ["1:40", "1:41"]),          # чинит запись tier=auto
        cand(7, "жалобы", "complaints", ["1:50", "1:51"]),         # уже в глоссарии
        cand(8, "лихорадка", "fever", ["1:60", "1:61"]),           # спорит с verified
        cand(9, "кашель", "cough", ["1:70", "1:71"]),              # back-check ниже порога
        cand(10, "стент", "stent", ["1:80", "1:81"]),              # текст правил ремонт
        cand(11, "инфильтрат", "infiltrate", ["1:1"], kind="audit"),  # audit, один донор
        cand(12, "договор", "Vertrag", ["3:1"], lang="RU→DE", domain="legal"),
        cand(13, "перикардит", "", ["1:1"], kind="conflict"),
        cand(14, "спазм2", "spasm", ["1:90", "1:91", "1:92"], kind="extract"),
        cand(15, "заключение", "conclusion", ["1:95", "1:96", "1:97"], kind="extract"),
        cand(16, "мазок", "smear", ["1:21"]),   # confirmed, но подставлен из TM
    ]
    return q


def run(**kw):
    return main.auto_approve_terms(main.AutoApproveRequest(**kw))


def show(res):
    by_id = {r["id"]: r for r in res["items"]}
    print("  counts:", res["counts"])
    for r in sorted(res["items"], key=lambda x: x["id"]):
        print("   +#%-2d %-12s → %-12s tier=%-8s (%s)" % (r["id"], r["src"], r["tgt"],
                                                          r["tier"], r["reason"]))
    for b in res["skipped"]:
        print("   -%2d× %s" % (b["count"], b["reason"]))
    return by_id


fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("\n=== 1. Медицинский проект (verified запрещён политикой) ===")
build()
r = run(dry_run=True, project=1)
got = show(r)
check(1 in got and got[1]["tier"] == "auto", "3 чистых сегмента → auto (не verified) в медицине")
check(4 in got and got[4]["tier"] == "auto", "подтверждённый человеком сегмент → auto")
check(6 in got and got[6]["tier"] == "auto", "запись tier=auto («задний → rear») перекрывается")
check(7 in got and got[7]["tier"] is None, "уже в глоссарии → закрыть без записи")
check(2 not in got and 3 not in got, "два варианта перевода → оба к человеку")
check(5 not in got, "донор без back-check не годится")
check(8 not in got, "спор с verified → к человеку")
check(9 not in got, "back-check ниже порога → к человеку")
check(10 not in got, "текст после автоматического ремонта → к человеку")
check(11 not in got, "audit с одним донором → к человеку")
check(13 not in got, "conflict без перевода → к человеку")
check(12 not in got, "чужая языковая пара не попала в область проекта")
check(r["counts"]["pending"] == 15, "в области проекта 15 кандидатов из 16")
check(16 not in got, "подтверждение из TM не считается подтверждением человека")

print("\n=== 2. Тот же набор, но домен general (verified разрешён) ===")
build(dom="general")
r = run(dry_run=True, project=2)
got = show(r)
check(got.get(14, {}).get("tier") == "verified", "3 РАЗНЫХ чистых исходника → verified")
check(got.get(1, {}).get("tier") == "auto",
      "три повтора одной строки — только подсказка, это не независимость")
check(15 not in got,
      "копии внутри порции (route=DUPLICATE) не доноры — остаётся один, этого мало")
check(2 not in got, "неоднозначный по-прежнему к человеку")

print("\n=== 3. Потолок max_tier=auto ===")
build(dom="general")
r = run(dry_run=True, project=2, max_tier="auto")
got = show(r)
check(got.get(14, {}).get("tier") == "auto", "max_tier=auto опускает потолок до подсказки")

print("\n=== 4. dry_run ничего не меняет ===")
build()
before_g = len(main.STATE["glossary"])
before_p = sum(1 for c in main.STATE["termQueue"] if c["status"] == "pending")
run(dry_run=True, project=1)
check(len(main.STATE["glossary"]) == before_g, "глоссарий не изменился")
check(sum(1 for c in main.STATE["termQueue"] if c["status"] == "pending") == before_p,
      "очередь не изменилась")

print("\n=== 5. Применение и откат ===")
build()
res = run(dry_run=False, project=1)
batch = res["batch"]
g = {t["src"]: t for t in main.STATE["glossary"]}
check(batch is not None, "пачка получила номер")
check(g.get("спазм", {}).get("tgt") == "spasm", "новая запись появилась")
check(g.get("спазм", {}).get("lang") == "RU→EN" and g["спазм"].get("domain") == "medical",
      "у новой записи проставлена область")
check(g.get("задний", {}).get("tgt") == "posterior", "«задний → rear» заменено на posterior")
check(g.get("лихорадка", {}).get("tgt") == "pyrexia", "verified-запись не тронута")
pend = sum(1 for c in main.STATE["termQueue"] if c["status"] == "pending")
decided = res["counts"]["auto"] + res["counts"]["verified"] + res["counts"]["closed"]
check(pend == 16 - decided, "обработанные кандидаты ушли из очереди (%d из 16)" % decided)

undo = main.undo_auto_approve(batch)
g = {t["src"]: t for t in main.STATE["glossary"]}
print("  undo:", undo)
check(g.get("задний", {}).get("tgt") == "rear", "откат вернул прежний перевод")
check(g.get("задний", {}).get("tier") == "auto", "откат вернул прежний уровень доверия")
check("спазм" not in g, "созданная запись удалена")
check(sum(1 for c in main.STATE["termQueue"] if c["status"] == "pending") == 16,
      "кандидаты вернулись в очередь")

print("\n=== 6. Область: RU→DE юридический ===")
build(dom="legal")
r = run(dry_run=True, project=3)
got = show(r)
check(r["counts"]["pending"] == 1, "в области RU→DE ровно один кандидат")
check(12 not in got, "один донор при пороге 2 → к человеку")

print("\n=== 7. Изоляция глоссария по области ===")
build()
main.STATE["glossary"].append({"src": "договор", "tgt": "contract", "tier": "verified",
                               "lang": "RU→EN", "domain": "legal"})
main._invalidate_gloss_index()
hits, _ = main._get_context("договор подряда", project=main.STATE["projects"][2])
check(not hits, "RU→DE проект не видит RU→EN запись")
hits, _ = main._get_context("договор подряда",
                            project={"src": "RU", "tgt": "EN", "domain": "legal"})
check(len(hits) == 1 and hits[0]["tgt"] == "contract", "RU→EN юридический проект её видит")
hits, _ = main._get_context("договор подряда",
                            project={"src": "RU", "tgt": "EN", "domain": "medical"})
check(not hits, "медицинский RU→EN проект её не видит")

print("\n=== 8. TM тоже по языковой паре ===")
build()
main.STATE["tm"] = [{"src": "острый живот", "tgt": "acute abdomen", "lang": "RU→EN"}]
main._invalidate_gloss_index()
_, tm = main._get_context("острый живот", project=main.STATE["projects"][0])
check(tm is not None, "RU→EN проект находит совпадение в TM")
_, tm = main._get_context("острый живот", project=main.STATE["projects"][2])
check(tm is None, "RU→DE проект не подставляет английский перевод")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
