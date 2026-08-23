"""Память очереди кандидатов и переперевод подтверждённых сегментов.

Проверяем ровно то, из-за чего одобренный термин возвращался в очередь
неодобренным: одобрение переписывало src/tgt кандидата, дедупликация теряла
его след, и следующий сбор терминологии заводил кандидата заново.
STATE подменён, save_state замолчан — реальные данные не трогаем.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
# Тест не ходит в сеть: внешние корпуса отвечают по-разному в разные дни,
# а проверка обязана давать один и тот же ответ. Их поведение проверяется
# отдельно, на подменённом источнике.
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build(gloss=(), segments=(), domain="medical", src="RU", tgt="EN"):
    proj = {"id": 1, "title": "P", "src": src, "tgt": tgt, "domain": domain,
            "segments": [dict(s) for s in segments]}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in gloss],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


def seg(sid, source, target, status="confirmed"):
    return {"id": sid, "source": source, "target": target, "status": status}


def pending():
    return [c for c in main.STATE["termQueue"] if c.get("status", "pending") == "pending"]


AUTO_ENTRY = {"src": "задний увеит", "tgt": "rear uveitis", "cat": "Disease",
              "tier": "auto", "lang": "RU→EN", "domain": "medical"}


print("=== 1. Одобренный conflict не возвращается в очередь ===")
# Глоссарий предлагает кальку, переводчик написал своё — рождается conflict.
s = seg(5, "Диагноз: задний увеит правого глаза.", "Diagnosis: back uveitis of the right eye.")
proj = build(gloss=[AUTO_ENTRY], segments=[s])
s = proj["segments"][0]
born = main._harvest_terms(s, proj)
check(len(born) == 1 and born[0]["kind"] == "conflict", "подтверждение сегмента родило conflict")
main.approve_term_candidate(born[0]["id"], main.TermDecision(tgt="posterior uveitis"))
check(not pending(), "после одобрения нерешённых нет")
check(main.STATE["glossary"][0]["tgt"] == "posterior uveitis"
      and main.STATE["glossary"][0]["tier"] == "verified", "глоссарий получил решение человека")
# Тот же сегмент подтверждают снова: перевод по-прежнему расходится с глоссарием,
# но вопрос уже задан и отвечен — второй раз спрашивать нечего.
for _ in range(3):
    main._harvest_terms(s, proj)
check(not pending(), "повторные подтверждения не воскрешают одобренный термин")
check(len(main.STATE["termQueue"]) == 1, "и не плодят дублей в истории решений")

print("\n=== 2. Одобрение с исправленным переводом помнит исходную пару ===")
proj = build(gloss=[AUTO_ENTRY], segments=[seg(6, "задний увеит", "back uveitis")])
s = proj["segments"][0]
born = main._harvest_terms(s, proj)
kinds = sorted(c["kind"] for c in born)
check(kinds == ["conflict", "segment"], "короткий сегмент дал сразу две карточки про один термин")
seg_cand = [c for c in born if c["kind"] == "segment"][0]
res = main.approve_term_candidate(seg_cand["id"], main.TermDecision(tgt="posterior uveitis"))
check(res["closed"], "вторая карточка про тот же термин закрыта решением")
check(not pending(), "нерешённых по термину не осталось")
check(seg_cand.get("origTgt") == "back uveitis", "исходная пара сохранена для дедупликации")
for _ in range(3):
    main._harvest_terms(s, proj)
check(not pending(), "исправленный при одобрении термин не всплывает заново")

print("\n=== 3. Отклонение закрывает только свою пару ===")
proj = build(segments=[seg(7, "мазок", "smear")])
s = proj["segments"][0]
born = main._harvest_terms(s, proj)
main.reject_term_candidate(born[0]["id"])
check(not pending(), "отклонённый кандидат ушёл из очереди")
main._harvest_terms(s, proj)
check(not pending(), "и не вернулся")
# Другой перевод того же термина — это другой вопрос, его задать можно.
s2 = dict(s, id=8, target="swab")
proj["segments"].append(s2)
main._harvest_terms(s2, proj)
p = pending()
check(len(p) == 1 and p[0]["tgt"] == "swab", "второй вариант перевода спрашивается заново")

print("\n=== 4. Решение человека переживает подрезку очереди ===")
proj = build(gloss=[AUTO_ENTRY], segments=[seg(9, "задний увеит", "back uveitis")])
s = proj["segments"][0]
born = main._harvest_terms(s, proj)
main.approve_term_candidate([c for c in born if c["kind"] == "conflict"][0]["id"],
                            main.TermDecision(tgt="posterior uveitis"))
decided = [c["id"] for c in main.STATE["termQueue"]]
# Забиваем очередь машинными решениями сверх потолка — подрезка обязана снять их,
# а решения человека оставить: на них держится «этот вопрос уже задавали».
nxt = max(decided) + 1
for i in range(main.TERM_QUEUE_MAX + 50):
    main.STATE["termQueue"].insert(0, {
        "id": nxt + i, "kind": "extract", "src": "шум%d" % i, "tgt": "noise%d" % i,
        "status": "approved", "autoBatch": 999, "autoTier": "auto", "autoWrote": True,
        "lang": "RU→EN", "domain": "medical"})
main._trim_term_queue()
alive = {c["id"] for c in main.STATE["termQueue"]}
check(len(main.STATE["termQueue"]) <= main.TERM_QUEUE_MAX, "очередь подрезана до потолка")
check(all(i in alive for i in decided), "решения человека уцелели")
for _ in range(2):
    main._harvest_terms(s, proj)
check(not pending(), "после подрезки термин по-прежнему считается решённым")

print("\n=== 5. Переперевод подтверждённых — только по явной галочке ===")
proj = build(gloss=[{"src": "увеит", "tgt": "uveitis", "tier": "verified",
                     "lang": "RU→EN", "domain": "medical"}],
             segments=[seg(1, "увеит", "back uveitis", status="confirmed"),
                       seg(2, "увеит справа", "uveitis on the right", status="translated")])
for s in proj["segments"]:
    s["confirmedBy"] = "human" if s["status"] == "confirmed" else None
main._invalidate_gloss_index()

calls = []
main._openai_translate = lambda text, *a, **k: (calls.append(text), "uveitis")[1]
os.environ["OPENAI_API_KEY"] = "test-key"

r = main.batch_translate(1, main.BatchRequest(engine="gpt", segment_ids=[1, 2], force=True))
check(1 not in r["translated"], "без галочки подтверждённый сегмент не тронут")
check(r["skipped_confirmed"] == [1], "и назван в отчёте, а не выброшен молча")
check(proj["segments"][0]["target"] == "back uveitis", "заверенный текст на месте")

r = main.batch_translate(1, main.BatchRequest(engine="gpt", segment_ids=[1], force=True,
                                              include_confirmed=True))
s1 = proj["segments"][0]
check(1 in r["translated"], "с галочкой подтверждённый сегмент переведён заново")
check(s1["target"] == "uveitis", "новый термин глоссария подставлен")
check(s1["prevTarget"] == "back uveitis", "прежний текст сохранён для отката")
check(s1["status"] == "review", "статус «требует проверки», а не «подтверждено»")
check("confirmedBy" not in s1, "отметка «подтвердил человек» снята с чужого текста")

print("\n=== 6. Решённый термин не возвращается ДРУГИМ видом карточки ===")
# Из-за чего это написано: дедупликация сверяет пару «термин + перевод» И вид
# карточки. Следующий прогон предлагает СВОЙ перевод того же термина, а находка
# termcheck приходит другим видом — пара новая, и утверждённый человеком термин
# всплывал в очереди как нерешённый, каждым прогоном заново.
proj = build(segments=[seg(1, "инфильтрат", "infiltrate")])
born = main._harvest_terms(proj["segments"][0], proj)
main.approve_term_candidate(born[0]["id"], main.TermDecision(tgt="infiltrate"))
check(main._hit_tier(main.STATE["glossary"][0]) == "verified", "решение человека — приказ")

# а) другой сегмент, модель перевела иначе: и короткая пара, и conflict.
proj["segments"].append(seg(2, "Инфильтрат", "induration"))
main._harvest_terms(proj["segments"][1], proj)
check(not pending(), "свой вариант нового прогона не заводит карточку заново")

# б) находка termcheck и извлечение модели — другие виды карточек.
main._queue_term("audit", "инфильтрат", "infiltration", project=1, segment=3,
                 lang="RU→EN", domain="medical", via="auto")
main._queue_term("extract", "инфильтрат", "infiltrate", project=1, segment=4,
                 lang="RU→EN", domain="medical", via="auto")
check(not pending(), "другой вид карточки про решённый термин не спрашивается")

decided = [c for c in main.STATE["termQueue"] if c["status"] == "approved"][0]
check(sorted(decided.get("reasked", [])) == ["induration", "infiltration"],
      "но чужие варианты записаны в решение, а не проглочены молча")
check(decided["hits"] > 1, "и видно, сколько раз про термин спрашивали снова")

print("\n=== 7. Приказ без карточки тоже закрывает вопрос, подсказка — нет ===")
# Запись verified могла появиться мимо очереди: ручная правка глоссария или
# выверенный справочник. Это тот же ответ человека, только данный не карточкой.
proj = build(gloss=[{"src": "мокрота", "tgt": "sputum", "tier": "verified",
                     "lang": "RU→EN", "domain": "medical"}],
             segments=[seg(1, "мокрота", "phlegm")])
main._harvest_terms(proj["segments"][0], proj)
check(not pending(), "расхождение с приказом — находка ремонта, а не вопрос о термине")

# А массовый автоимпорт (подсказка) обязан ловиться по-прежнему: ради
# «задний → rear» conflict-кандидаты и заведены.
proj = build(gloss=[AUTO_ENTRY], segments=[seg(1, "задний увеит", "posterior uveitis")])
main._harvest_terms(proj["segments"][0], proj)
check(any(c["kind"] == "conflict" for c in pending()),
      "спор с подсказкой по-прежнему спрашивается")

print("\n=== 8. Отклонение вопрос не закрывает ===")
proj = build(segments=[seg(1, "мазок", "smear")])
born = main._harvest_terms(proj["segments"][0], proj)
main.reject_term_candidate(born[0]["id"])
main._queue_term("extract", "мазок", "swab", project=1, segment=2,
                 lang="RU→EN", domain="medical", via="auto")
check(len(pending()) == 1, "«эта пара неверна» — не «с термином разобрались»")

print("\n=== 9. Старое состояние: накопленные дубли снимаются миграцией ===")
# Очередь, набитая прежним кодом: три карточки про термин, который человек уже
# утвердил, и одна про термин с приказом в глоссарии мимо очереди.
st = {"projects": [], "tm": [],
      "glossary": [{"src": "мокрота", "tgt": "sputum", "tier": "verified",
                    "lang": "RU→EN", "domain": "medical"}],
      "termQueue": [
          {"id": 1, "kind": "segment", "src": "инфильтрат", "tgt": "infiltrate",
           "status": "approved", "decidedBy": "human", "lang": "RU→EN", "domain": "medical"},
          {"id": 2, "kind": "segment", "src": "инфильтрат", "tgt": "induration",
           "status": "pending", "lang": "RU→EN", "domain": "medical"},
          {"id": 3, "kind": "audit", "src": "инфильтрат", "tgt": "infiltration",
           "status": "pending", "lang": "RU→EN", "domain": "medical"},
          {"id": 4, "kind": "conflict", "src": "мокрота", "tgt": "",
           "status": "pending", "lang": "RU→EN", "domain": "medical"},
          # Чужая языковая пара: тот же термин, но вопрос там не задавали.
          {"id": 5, "kind": "segment", "src": "инфильтрат", "tgt": "Infiltrat",
           "status": "pending", "lang": "RU→DE", "domain": "medical"},
          # Неотвеченный термин — трогать нечего.
          {"id": 6, "kind": "segment", "src": "хрипы", "tgt": "rales",
           "status": "pending", "lang": "RU→EN", "domain": "medical"},
      ]}
closed = main._migrate_term_queue(st)
q = {c["id"]: c for c in st["termQueue"]}
check(closed == 3, "снято ровно три накопленных дубля")
check(q[2]["status"] == "approved" and q[2]["decidedWith"] == 1, "чужой вариант закрыт решением человека")
check(q[3]["status"] == "approved", "и находка другого вида тоже")
check(q[4]["status"] == "approved", "приказ глоссария закрывает вопрос без карточки")
check(q[5]["status"] == "pending", "чужая языковая пара не тронута")
check(q[6]["status"] == "pending", "неотвеченный термин остался в очереди")
check(not main._human_decision(q[2]), "закрытая миграцией карточка решением человека не становится")
check(main._migrate_term_queue(st) == 0, "повторный проход ничего не трогает")

print("\n=== 10. Старое состояние: одобренным конфликтам возвращают их пару ===")
st = main._apply_migrations({
    "projects": [], "glossary": [], "tm": [],
    "termQueue": [
        # Одобрен старым кодом: пустой перевод затёрт решением человека.
        {"id": 1, "kind": "conflict", "src": "задний увеит", "tgt": "posterior uveitis",
         "status": "approved", "lang": "RU→EN", "domain": "medical"},
        # Ещё не решён — трогать нечего.
        {"id": 2, "kind": "conflict", "src": "макула", "tgt": "", "status": "pending",
         "lang": "RU→EN", "domain": "medical"},
        # Другой вид: текущая пара и есть исходная, гадать не о чем.
        {"id": 3, "kind": "segment", "src": "мазок", "tgt": "smear", "status": "approved",
         "lang": "RU→EN", "domain": "medical"},
    ]})
q = {c["id"]: c for c in st["termQueue"]}
check(q[1].get("origTgt") == "", "одобренному конфликту вернули пустой перевод как ключ")
check("origTgt" not in q[2], "нерешённый конфликт не тронут")
check("origTgt" not in q[3], "кандидат другого вида не тронут")
check(main._cand_pair(q[1]) == ("задний увеит", ""), "дедупликация снова узнаёт эту карточку")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
