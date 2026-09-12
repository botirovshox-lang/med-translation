"""Очередь терминов сортируется по ОХВАТУ, а не по частоте.
Смысл проверяемого: человеку важно не то, сколько раз слово встретилось
(27 раз в одном абзаце), а сколько строк приведёт в порядок его ответ.
Охват считает сервер (`_cand_impacts`): термин в оригинале есть, а этого
перевода в переводе нет; у конфликта перевода ещё нет — считаются все строки
с термином; заверенные человеком не считаются (их без разрешения не трогают).
Вызовов модели нет.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, "backend")
import main
main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg(i, src, tgt, status="translated"):
    return {"id": i, "source": src, "target": tgt, "status": status}


proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical", "segments": [
    seg(1, "Каверна в лёгком", "A cavity in the lung"),      # перевод кандидата уже стоит
    seg(2, "Каверна закрылась", "The cavern closed"),        # расходится
    seg(3, "Каверны видны", "Caverns are visible", "confirmed"),  # заверено — не считается
    seg(4, "Шов снят", "", "new"),                           # не переведён
    seg(5, "Шов и каверна", "Suture and cavern"),            # шов верен, каверна расходится
    seg(6, "Шов наложен", "The stitch was placed"),          # шов расходится
]}


def cand(i, kind, src, tgt, hits):
    return {"id": i, "kind": kind, "src": src, "tgt": tgt, "status": "pending", "hits": hits,
            "segments": ["1:1"], "lang": "RU→EN", "domain": "medical"}


main.STATE = {"projects": [proj], "glossary": [], "tm": [], "exportHistory": [], "team": [],
              "termQueue": [cand(1, "segment", "каверна", "cavity", 9),
                            cand(2, "segment", "шов", "suture", 1),
                            cand(3, "conflict", "шов", "", 1)]}
main._invalidate_gloss_index()
main._CAND_IMPACT_CACHE.clear()

print("=== 1. Охват считается по строкам, а не по частоте ===")
imp = main._cand_impacts(proj, main.STATE["termQueue"])
check(imp == {1: 2, 2: 1, 3: 3}, "охват: каверна 2 (без заверённой и без совпавшей), шов 1, конфликт 3 — " + str(imp))

print("=== 2. Очередь отсортирована по охвату, частота — второй ключ ===")
r = main.list_term_queue(status="pending", limit=50, project=1)
order = [c["id"] for c in r["items"]]
check(order == [3, 1, 2], "порядок [3, 1, 2], а не по hits [1, 2, 3]: " + str(order))
check([c["impact"] for c in r["items"]] == [3, 2, 1], "impact уезжает в карточку")
r0 = main.list_term_queue(status="pending", limit=50)
check(all(c["impact"] is None for c in r0["items"]), "без проекта охват не считается (None, не ноль)")

print("=== 3. Кэш держится на содержимом и снимается правкой ===")
check(main._cand_impacts(proj, main.STATE["termQueue"]) is imp, "тот же проект и пары — ответ из кэша")
proj["segments"][5]["target"] = "The suture was placed"
imp2 = main._cand_impacts(proj, main.STATE["termQueue"])
check(imp2[2] == 0 and imp2 is not imp, "правка перевода снимает кэш: шов больше не расходится")

print("\n" + ("ПРОВАЛЕНО: " + "; ".join(fail) if fail else "ВСЁ ПРОШЛО"))
sys.exit(1 if fail else 0)
