"""Очередь терминов: разбор копившегося без решения.

Три правила, заведённые после боевых 684 карточек «ждут человека», из которых
человека ждали немногие:

  1. Обрывки фраз, накопленные ДО ворот формы, снимает `_migrate_term_queue`
     тем же предикатом `_term_shape_reject`, что ворота и `_auto_verdict`:
     политика не одобрит их никогда, а место у потолка TERM_QUEUE_MAX они
     занимают (боевые 115 карточек). conflict не трогается — он уходит
     человеку раньше проверок формы. Решением человека закрытая карточка
     не становится.
  2. «Не хватает данных» — вердикт "wait", а не «решает человек»: доноров
     приносят следующие чистые прогоны, и `/analysis` считает такие отдельно
     (termsWaiting), не пугая числом (боевые 412 из 684).
  3. Запись, занятую прошлой пачкой, автоодобрение пишет поверх С СОХРАНЕНИЕМ
     цепочки отката: prev* не затираются, откат НОВОЙ пачки возвращает
     состояние до СТАРОЙ, а откат старой такие записи не трогает и называет
     числом superseded. Прежний отказ «сначала откатите пачку #N» копил
     неразрешимые карточки (боевые 36 за шестью пачками).

Платных вызовов нет.
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


def state_of(queue=(), glossary=(), batches=()):
    main.STATE = {"projects": [], "glossary": [dict(g) for g in glossary],
                  "tm": [], "termQueue": [dict(c) for c in queue],
                  "exportHistory": [], "team": [],
                  "autoBatches": [dict(b) for b in batches]}
    main._invalidate_gloss_index()
    return main.STATE


print("(1) миграция снимает обрывки фраз, conflict не трогает")
st = state_of(queue=[
    {"id": 1, "src": "в лёгких у больного при осмотре", "tgt": "in the lungs",
     "kind": "extract", "status": "pending"},
    {"id": 2, "src": "очень длинный конфликтный термин из документа",
     "tgt": "some conflicting translation", "kind": "conflict", "status": "pending"},
    {"id": 3, "src": "туберкулема", "tgt": "tuberculoma",
     "kind": "extract", "status": "pending"},
])
n = main._migrate_term_queue(st)
q = {c["id"]: c for c in st["termQueue"]}
check(n == 1, "снята ровно одна карточка")
check(q[1]["status"] == "rejected" and "фразу" in q[1].get("note", ""),
      "длинный термин снят с причиной формы")
check(not main._human_decision(q[1]), "снятая карточка — не решение человека")
check(q[2]["status"] == "pending", "conflict остался человеку")
check(q[3]["status"] == "pending", "нормальный кандидат остался")

print("(2) нехватка данных — вердикт wait")
state_of()
pol = main._auto_policy("medical")
cand = {"id": 9, "src": "пневмоперитонеум", "tgt": "pneumoperitoneum",
        "kind": "extract", "status": "pending", "segments": ["1:1"]}
ctx = main._auto_context([cand], pol)
action, reason = main._auto_verdict(cand, ctx)
check(action == "wait", "нет годных доноров — wait, а не человек (%s)" % action)
conf = {"id": 10, "src": "каверна", "tgt": "", "kind": "conflict",
        "status": "pending"}
action2, _ = main._auto_verdict(conf, main._auto_context([conf], pol))
check(action2 is None, "conflict — по-прежнему человек")

print("(3) перезапись занятой записи сохраняет цепочку отката")
today = "2026-09-01"
state_of(glossary=[{"src": "туберкулема", "tgt": "ORIGINAL", "tier": "auto",
                    "note": "импорт", "conf": "low", "origin": "import",
                    "lang": "RU→EN", "domain": "medical", "tenant": "default"}],
         batches=[{"id": 17}])
c17 = {"id": 21, "src": "туберкулема", "tgt": "machine-17", "kind": "extract",
       "lang": "RU→EN", "domain": "medical", "tenant": "default"}
main._auto_write(c17, "auto", 17, today)
g = main._glossary_entry("туберкулема", main._scope_of(c17))
check(g["tgt"] == "machine-17" and g["autoBatch"] == 17 and g["prevTgt"] == "ORIGINAL",
      "первая пачка записала и запомнила исходное")

c22 = {"id": 22, "src": "туберкулема", "tgt": "machine-22", "kind": "extract",
       "lang": "RU→EN", "domain": "medical", "tenant": "default"}
main.STATE["autoBatches"].insert(0, {"id": 22})
main._auto_write(c22, "auto", 22, today)
check(g["tgt"] == "machine-22" and g["autoBatch"] == 22,
      "вторая пачка перехватила запись")
check(g["prevTgt"] == "ORIGINAL" and g.get("autoCreated") is False,
      "цепочка отката цела: prev* указывает на состояние ДО первой пачки")

print("(4) откат старой пачки перехваченное не трогает и называет")
main.STATE["termQueue"] = [
    {"id": 21, "src": "туберкулема", "tgt": "machine-17", "kind": "extract",
     "lang": "RU→EN", "domain": "medical", "tenant": "default",
     "status": "approved", "autoBatch": 17, "autoWrote": True},
    {"id": 22, "src": "туберкулема", "tgt": "machine-22", "kind": "extract",
     "lang": "RU→EN", "domain": "medical", "tenant": "default",
     "status": "approved", "autoBatch": 22, "autoWrote": True},
]
r17 = main.undo_auto_approve(17)
check(r17["superseded"] == 1, "откат №17 называет перехваченную запись")
check(g["tgt"] == "machine-22" and g["autoBatch"] == 22,
      "откат №17 позднее решение не затёр")
c21 = next(c for c in main.STATE["termQueue"] if c["id"] == 21)
# Вернись карточка в pending — следующее «Одобрить и применить» вписало бы
# machine-17 поверх решения пачки №22: глоссарий молча откатывался бы назад.
check(c21["status"] != "pending" and "перехвачена" in c21.get("note", ""),
      "перехваченная карточка в очередь не возвращается и названа")
check(r17["returned"] == 0, "в очередь не вернулось ничего — единственная карточка перехвачена")

print("(5) откат новой пачки возвращает состояние ДО старой")
r22 = main.undo_auto_approve(22)
g2 = main._glossary_entry("туберкулема", main._scope_of(c22))
check(g2 is not None and g2["tgt"] == "ORIGINAL" and not g2.get("autoBatch"),
      "запись вернулась к исходному, а не к машинному варианту №17")

print("(6) рождённая пачкой запись при перехвате остаётся autoCreated")
state_of(batches=[{"id": 31}, {"id": 32}])
cA = {"id": 31, "src": "плеврит", "tgt": "born-31", "kind": "extract",
      "lang": "RU→EN", "domain": "medical", "tenant": "default"}
main._auto_write(cA, "auto", 31, today)
cB = {"id": 32, "src": "плеврит", "tgt": "born-32", "kind": "extract",
      "lang": "RU→EN", "domain": "medical", "tenant": "default"}
main._auto_write(cB, "auto", 32, today)
gb = main._glossary_entry("плеврит", main._scope_of(cB))
check(gb["autoCreated"] is True and gb["autoBatch"] == 32,
      "autoCreated унаследован — откат №32 запись уберёт, а не «вернёт»")
main.undo_auto_approve(32)
check(main._glossary_entry("плеврит", main._scope_of(cB)) is None,
      "откат №32 убрал запись целиком: до пачек её не существовало")

print()
print("FAIL: %d" % len(fail) if fail else "ВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
