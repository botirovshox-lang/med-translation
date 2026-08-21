"""Внешние источники приказов: справочники и корпус целевого языка.

Проверяем то, ради чего они появились: заверить термин теперь может не только
человек, и при этом ни один источник не имеет права подтверждать наугад.
Сеть здесь не используется — корпус подменён, справочники пишутся во временный
каталог. Реальный STATE не трогаем.
"""
import os, sys, tempfile, io, time
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"          # живой корпус в тестах не спрашиваем
sys.path.insert(0, "backend")
import main
import authorities as A

main.save_state = lambda *a, **k: None
# Настоящую attested сохраняем: ниже её подменяют, а в конце проверяют
# именно её поведение на нечитаемом и на упавшем источнике.
_real_attested = A.attested

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# ─────────────── Справочники ───────────────
TMP = tempfile.mkdtemp(prefix="authtest")


def write(name, body):
    io.open(os.path.join(TMP, name), "w", encoding="utf-8").write(body)


write("inn_ru_en.tsv", """# label: ВОЗ INN (проверка)
# lang: RU→EN
# domains: medical, pharma
аторвастатин\tatorvastatin
бисопролол\tbisoprolol
увеит\tuveitis
""")
write("iate_ru_de.tsv", """# label: IATE RU→DE (проверка)
# lang: RU→DE
# domains: *
договор\tVertrag
""")
write("broken.tsv", """аторвастатин\tatorvastatin
""")          # нет «# lang:» — применять не к чему

print("=== 1. Справочник читается файлом, без правки кода ===")
dicts = A.load_dictionaries(TMP)
by_id = {d.id: d for d in dicts}
check(set(by_id) == {"inn_ru_en", "iate_ru_de"}, "загружены оба валидных: " + str(sorted(by_id)))
check("broken" not in by_id, "файл без языковой пары пропущен, а не применён наугад")
check(by_id["inn_ru_en"].label.startswith("ВОЗ INN"), "заголовок прочитан")

print("\n=== 2. Чужая пара языков и чужая область не подходят никогда ===")
inn = by_id["inn_ru_en"]
check(inn.covers("RU→EN", "medical"), "своя пара и область — подходит")
check(not inn.covers("RU→DE", "medical"), "чужая пара языков — нет")
check(not inn.covers("RU→EN", "legal"), "чужая область — нет")
iate = by_id["iate_ru_de"]
check(iate.covers("RU→DE", "legal") and iate.covers("RU→DE", "finance"),
      "«domains: *» подходит любой области…")
check(not iate.covers("RU→EN", "legal"), "…но пара языков обязательна всегда")

print("\n=== 3. Совпадение со справочником — приказ даже там, где он запрещён ===")
main._DICTIONARIES = dicts
seg = {"id": 1, "source": "увеит", "target": "uveitis", "status": "translated"}
proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical", "segments": [seg]}
main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
              "exportHistory": [], "team": []}
main._invalidate_gloss_index()
q = main.STATE["termQueue"]
q.append({"id": 1, "kind": "segment", "src": "увеит", "tgt": "uveitis", "status": "pending",
          "hits": 1, "segments": ["1:1"], "lang": "RU→EN", "domain": "medical"})
r = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
item = next((i for i in r["items"] if i["id"] == 1), None)
check(item and item["tier"] == "verified",
      "медицина: без справочника был бы максимум auto, со справочником — приказ")
check(item and "справочник" in item["reason"], "и причина названа: " + (item or {}).get("reason", "—"))
check(r["policy"]["allow_verified"] is False,
      "при этом самоодобрение приказом в медицине по-прежнему запрещено")

print("\n=== 4. Справочник разрешает спор вариантов ===")
q.append({"id": 2, "kind": "extract", "src": "увеит", "tgt": "eye inflammation",
          "status": "pending", "hits": 1, "segments": ["1:1"],
          "lang": "RU→EN", "domain": "medical"})
r = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
got = {i["id"]: i for i in r["items"]}
check(got.get(1, {}).get("tier") == "verified", "вариант из справочника одобрен")
check(2 not in got, "второй вариант остался человеку")
check(main._authority_suggests("увеит", ("RU→EN", "medical")) == ["uveitis"],
      "человеку показываем, какую норму знает справочник")

print("\n=== 5. Нет источника для этой пары — молчим, а не выдумываем ===")
check(main._authority_match("увеит", "uveitis", ("RU→DE", "medical")) is None,
      "RU→DE не подтверждается английским справочником")
check(main._authority_sources(("RU→FR", "medical"))["dictionaries"] == [],
      "для пары, где источников нет вовсе, список честно пуст")
check(len(main._authority_sources(("RU→DE", "medical"))["dictionaries"]) == 1,
      "а RU→DE покрыт IATE: «domains: *» — это про области, не про языки")
srcs = main._authority_sources(("RU→EN", "medical"))
check(len(srcs["dictionaries"]) == 1 and srcs["dictionaries"][0]["terms"] == 3,
      "а для RU→EN источник назван с числом терминов")

# ─────────────── Корпус ───────────────
print("\n=== 6. Корпус: ноль вхождений — вето на кальку ===")
CORPUS = {"posterior uveitis": 2052, "rear cyclitis": 0, "rear uveitis": 1}


def fake_attested(term, tgt, domain):
    n = CORPUS.get((term or "").lower())
    if n is None:
        return None                                  # источник не знает — не ответ
    return {"hits": n, "source": "test", "label": "TestCorpus",
            "ok": n >= 5, "absent": n == 0}


main.authorities_mod.attested = fake_attested
main._DICTIONARIES = []


def one(src, tgt, donors=("1:1", "1:2", "1:3"), dom="general"):
    segs = [{"id": int(d.split(":")[1]), "source": src + " " + d, "target": tgt,
             "status": "translated",
             "backcheck": {"score": 95, "target_hash": main._text_hash(tgt), "back": "..."},
             "termcheck": {"findings": [], "target_hash": main._text_hash(tgt), "model": "t"}}
            for d in donors]
    p = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": dom, "segments": segs}
    main.STATE = {"projects": [p], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main.STATE["termQueue"].append(
        {"id": 1, "kind": "segment", "src": src, "tgt": tgt, "status": "pending",
         "hits": len(donors), "segments": list(donors), "lang": "RU→EN", "domain": dom})
    # corpus=True явно: в режиме «показать» корпус по умолчанию молчит,
    # чтобы открытие проекта не превращалось в минуту внешних запросов.
    return main.auto_approve_terms(
        main.AutoApproveRequest(dry_run=True, project=1, corpus=True))


r = one("задний циклит", "rear cyclitis")
check(not r["items"], "кальки с нулём вхождений не одобряются никаким согласием доноров")
why = " ".join(b["reason"] for b in r["skipped"])
check("нет в текстах целевого языка" in why, "причина названа: " + why)

print("\n=== 7. Редкий термин удерживается на подсказке ===")
r = one("задний увеит", "rear uveitis")
it = next((i for i in r["items"] if i["id"] == 1), None)
check(it and it["tier"] == "auto", "1 вхождение — только подсказка, не приказ")
check(it and "редок" in it["reason"], "и сказано почему: " + (it or {}).get("reason", "—"))

print("\n=== 8. Частотный термин получает приказ и говорит, чем подтверждён ===")
r = one("задний увеит", "posterior uveitis")
it = next((i for i in r["items"] if i["id"] == 1), None)
check(it and it["tier"] == "verified", "3 независимых сегмента + корпус → приказ")
check(it and "TestCorpus" in it["reason"], "источник подтверждения назван: "
      + (it or {}).get("reason", "—"))

print("\n=== 9. Молчащий корпус ничего не решает ===")
r = one("неизвестный термин", "unknown term")     # в CORPUS его нет → attested = None
it = next((i for i in r["items"] if i["id"] == 1), None)
check(it and it["tier"] == "verified",
      "источник не ответил — работают прежние правила, а не отказ")

print("\n=== 10. Корпус спрашивают только про претендентов ===")
asked = []
main.authorities_mod.attested = lambda t, l, d: (asked.append(t), fake_attested(t, l, d))[1]
segs = [{"id": 1, "source": "шов", "target": "suture", "status": "translated"}]
p = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "general", "segments": segs}
main.STATE = {"projects": [p], "glossary": [], "tm": [], "termQueue": [],
              "exportHistory": [], "team": []}
main._invalidate_gloss_index()
# Донор без проверок — кандидат отсеется до корпуса, и платить за запрос незачем.
main.STATE["termQueue"].append(
    {"id": 1, "kind": "segment", "src": "шов", "tgt": "suture", "status": "pending",
     "hits": 1, "segments": ["1:1"], "lang": "RU→EN", "domain": "general"})
main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
check(asked == [], "про заведомо отсеянного кандидата корпус не спрашивали")

print("\n=== 11. Разбор корпуса называет свои цифры ===")
r = one("задний увеит", "posterior uveitis")
check(r["corpusChecked"] == 1 and r["corpusSkipped"] == 0,
      "сколько терминов проверено и сколько не влезло в потолок")

print("\n=== 12. Справочники загружаются при импорте, а не по просьбе ===")
# Без вызова при старте весь путь «приказ от справочника» мёртв в бою:
# _DICTIONARIES остаётся пустым, и медицина навсегда без приказов, кроме
# человеческих. Тест ловит именно отсутствие вызова.
src = io.open(os.path.join("backend", "main.py"), encoding="utf-8").read()
check("\n_load_authorities()" in src, "_load_authorities() вызывается на уровне модуля")
check(len(main.AUTHORITY_DIRS) == 2, "читаются оба каталога: код и данные сервера")

print("\n=== 13. «Только подсказки» сильнее справочника ===")
main._DICTIONARIES = dicts
main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
              "exportHistory": [], "team": []}
main._invalidate_gloss_index()
main.STATE["termQueue"].append(
    {"id": 1, "kind": "segment", "src": "увеит", "tgt": "uveitis", "status": "pending",
     "hits": 1, "segments": ["1:1"], "lang": "RU→EN", "domain": "medical"})
r = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1, max_tier="auto"))
it = next((i for i in r["items"] if i["id"] == 1), None)
check(it and it["tier"] == "auto",
      "выбран режим «только подсказки» — справочник его не обходит")
check(it and "только подсказки" in it["reason"], "и сказано почему: "
      + (it or {}).get("reason", "—"))
r = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
it = next((i for i in r["items"] if i["id"] == 1), None)
check(it and it["tier"] == "verified", "без тумблера справочник по-прежнему даёт приказ")

print("\n=== 14. Нечитаемый ответ источника — «не знаю», а не «нуль» ===")
A.attested = _real_attested      # выше её подменяли — здесь проверяем настоящую
A._CACHE.clear()
A._DEAD_UNTIL.clear()
A.CORPUS_ENABLED = True
A._get_json = lambda url, source: {"esearchresult": {"error": "busy"}}
check(A.attested("posterior uveitis", "EN", "medical") is None,
      "ответ без поля count не превращается в вето")
check(not A._DEAD_UNTIL, "и не выключает источник на пять минут: он жив")
A._get_json = lambda url, source: {"esearchresult": {"count": "0"}}
res = A.attested("rear cyclitis", "EN", "medical")
check(res and res["absent"], "а настоящий ноль — это именно ноль")


def boom(url, source):
    raise OSError("сеть отвалилась")


A._get_json = boom
A._CACHE.clear()
check(A.attested("что-нибудь ещё", "EN", "medical") is None, "недоступный источник молчит")
check("pubmed" in A._DEAD_UNTIL, "и помечается мёртвым, чтобы не платить таймаутом за каждый термин")
A.CORPUS_ENABLED = False

print("\n=== 15. Запросы к источнику разрежены во времени ===")
A._LAST_CALL.clear()
t0 = time.time()
for _ in range(3):
    A._throttle("pubmed")
check(time.time() - t0 >= A._MIN_INTERVAL["pubmed"] * 2 - 0.05,
      "три запроса подряд не укладываются в лимит источника без паузы")

print("\n=== 16. Разбор «показать» не ходит в сеть, но и не врёт об этом ===")
A.CORPUS_ENABLED = True
asked2 = []
main.authorities_mod.attested = lambda t, l, d: (asked2.append(t), None)[1]
r = one("задний увеит", "posterior uveitis")           # helper просит corpus=True
check(asked2, "с явной просьбой корпус спрашивают")
asked2.clear()
segs = [{"id": i, "source": "увеит %d" % i, "target": "uveitis", "status": "translated",
         "backcheck": {"score": 95, "target_hash": main._text_hash("uveitis"), "back": "."},
         "termcheck": {"findings": [], "target_hash": main._text_hash("uveitis"), "model": "t"}}
        for i in (1, 2)]
p = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "general", "segments": segs}
main.STATE = {"projects": [p], "glossary": [], "tm": [], "termQueue": [],
              "exportHistory": [], "team": []}
main._invalidate_gloss_index()
main.STATE["termQueue"].append(
    {"id": 1, "kind": "segment", "src": "увеит", "tgt": "uveitis", "status": "pending",
     "hits": 2, "segments": ["1:1", "1:2"], "lang": "RU→EN", "domain": "general"})
r = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
check(asked2 == [], "разбор «показать» по умолчанию в сеть не ходит")
check(r["corpusPending"] is True, "и честно помечен как «до корпусной проверки»")
A.CORPUS_ENABLED = False

print("\n=== 17. Справочник с двумя нормами не решает спор за человека ===")
main.authorities_mod.attested = lambda t, l, d: None


class TwoNorms:
    id, label = "two", "Справочник с двумя нормами"
    pairs = {"шов": {"suture", "stitch"}}

    def covers(self, lang, domain):
        return lang == "RU→EN"

    def match(self, src, tgt):
        return tgt.strip().lower() in self.pairs.get(src.strip().lower(), set())

    def suggest(self, src):
        return sorted(self.pairs.get(src.strip().lower(), set()))


main._DICTIONARIES = [TwoNorms()]
segs = [{"id": i, "source": "шов %d" % i, "target": "suture", "status": "translated",
         "backcheck": {"score": 95, "target_hash": main._text_hash("suture"), "back": "."},
         "termcheck": {"findings": [], "target_hash": main._text_hash("suture"), "model": "t"}}
        for i in (1, 2, 3)]
p = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical", "segments": segs}
main.STATE = {"projects": [p], "glossary": [], "tm": [], "termQueue": [],
              "exportHistory": [], "team": []}
main._invalidate_gloss_index()
main.STATE["termQueue"] += [
    {"id": 1, "kind": "segment", "src": "шов", "tgt": "suture", "status": "pending",
     "hits": 3, "segments": ["1:1", "1:2", "1:3"], "lang": "RU→EN", "domain": "medical"},
    {"id": 2, "kind": "extract", "src": "шов", "tgt": "stitch", "status": "pending",
     "hits": 1, "segments": ["1:1"], "lang": "RU→EN", "domain": "medical"}]
r = main.auto_approve_terms(main.AutoApproveRequest(dry_run=True, project=1))
check(not r["items"], "оба варианта есть в справочнике — ни один не одобрен автоматически")
check("несколько вариантов" in " ".join(b["reason"] for b in r["skipped"]),
      "причина названа: " + " · ".join(b["reason"] for b in r["skipped"]))

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
