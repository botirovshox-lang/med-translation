"""Учёт фактического расхода: то, за что выставят счёт, а не наша оценка.

Смета до прогона считается по объёму текста и обязана ошибаться — сколько
модель ответит, знает только модель. Беда была не в этом: фактический расход
нигде не записывался, и поправить смету было НЕ ПО ЧЕМУ. Проверяется ровно то,
без чего учёт бесполезен или вреден:

  1. usage снимается с ответа и превращается в деньги по каталогу;
  2. неизвестная модель даёт «цена неизвестна», а не ноль — иначе расход
     показывался бы меньше настоящего;
  3. reasoning-токены видны отдельно: из-за них смета и промахивалась;
  4. счёт идёт по шагам и моделям — иначе не видно, какой шаг врёт;
  5. параллельные вызовы ничего не теряют (порция идёт в шесть потоков);
  6. сломанный usage не роняет работу: перевод дороже бухгалтерии;
  7. смета человека доезжает до записи о прогоне и лежит рядом с фактом;
  8. вне прогона расход всё равно считается — в счётчик процесса.

Ни одного вызова модели: usage подсовывается вручную.
"""
import os, sys, threading
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


class Details:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class Resp:
    """Ответ SDK ровно в той части, которая нас касается."""
    def __init__(self, tin, tout, cached=0, reasoning=0):
        self.usage = Details(
            prompt_tokens=tin, completion_tokens=tout,
            prompt_tokens_details=Details(cached_tokens=cached),
            completion_tokens_details=Details(reasoning_tokens=reasoning))


def reset():
    main._USAGE_TOTAL.clear()
    main._USAGE_TOTAL.update(main._usage_zero())
    main._USAGE_SINK = None


# ─────────── 1. Цена берётся из каталога, а не выдумывается ───────────
print("=== 1. Токены превращаются в деньги по каталогу ===")
terra = main._MODELS_BY_ID["gpt-5.6-terra"]
cost = main._usage_cost("gpt-5.6-terra", 1_000_000, 1_000_000)
check(abs(cost - (terra["in"] + terra["out"])) < 1e-9,
      "миллион входных и миллион выходных = in + out из каталога (%.2f)" % cost)
check(main._usage_cost("gpt-5.6-terra", 0, 0) == 0, "ноль токенов — ноль денег")
check(main._model_price(main.EMBED_MODEL) is not None,
      "эмбеддинги стоят денег и цена у них есть, хотя в списке выбора их нет")

# ─────────── 2. Неизвестная модель — «не знаю», а не ноль ───────────
print("\n=== 2. Модель без цены не превращается в бесплатную ===")
check(main._usage_cost("модель-которой-нет", 10_000, 10_000) is None,
      "цена неизвестной модели — None, а не 0")
reset()
main._note_usage("translate", "модель-которой-нет", Resp(10_000, 5_000))
check(main._USAGE_TOTAL["cost"] == 0 and main._USAGE_TOTAL["unpriced"] == 1,
      "такой вызов посчитан отдельно (unpriced), а к сумме не приписан")
check(main._USAGE_TOTAL["in"] == 10_000,
      "токены при этом записаны: неизвестна цена, а не расход")

# ─────────── 3. Рассуждения видны отдельно ───────────
print("\n=== 3. Reasoning-токены — отдельной строкой ===")
reset()
main._note_usage("termcheck", "gpt-5.6-terra", Resp(500, 300, cached=128, reasoning=250))
t = main._USAGE_TOTAL
check(t["out"] == 300 and t["reasoning"] == 250,
      "выходных 300, из них 250 на рассуждения — именно они ломали смету")
check(t["cached_in"] == 128, "кэшированный вход виден: на него цифра завышена")
check(abs(t["cost"] - main._usage_cost("gpt-5.6-terra", 500, 300)) < 1e-9,
      "в деньги идут ВСЕ выходные токены, включая рассуждения: за них платят")

# ─────────── 4. Разбивка по шагам и моделям ───────────
print("\n=== 4. Видно, какой шаг сколько стоил ===")
reset()
main._note_usage("termcheck", "gpt-5.6-terra", Resp(1000, 100))
main._note_usage("termcheck", "gpt-5.6-terra", Resp(1000, 100))
main._note_usage("backcheck", "gpt-5.6-luna", Resp(1000, 100))
t = main._USAGE_TOTAL
check(t["calls"] == 3 and t["steps"]["termcheck"]["calls"] == 2,
      "три вызова, из них два termcheck")
check(t["steps"]["termcheck"]["cost"] > t["steps"]["backcheck"]["cost"],
      "дорогая модель на termcheck видна в разбивке, а не растворяется в сумме")
check(abs(sum(v["cost"] for v in t["steps"].values()) - t["cost"]) < 1e-6,
      "сумма по шагам сходится с общей")
check(abs(sum(v["cost"] for v in t["models"].values()) - t["cost"]) < 1e-6,
      "сумма по моделям сходится с общей")

# ─────────── 5. Порция идёт в шесть потоков — ничего не теряется ───────────
print("\n=== 5. Параллельные вызовы не теряются ===")
reset()
threads = [threading.Thread(target=main._note_usage,
                            args=("repair", "gpt-5.6-terra", Resp(100, 10)))
           for _ in range(200)]
for th in threads:
    th.start()
for th in threads:
    th.join()
check(main._USAGE_TOTAL["calls"] == 200 and main._USAGE_TOTAL["in"] == 20_000,
      "200 одновременных вызовов из разных потоков посчитаны все")

# ─────────── 6. Бухгалтерия не роняет работу ───────────
print("\n=== 6. Сломанный usage не мешает переводить ===")
reset()
for bad in (None, object(), Details(usage=None), Details(usage="мусор"),
            Details(usage={"prompt_tokens": "не число", "completion_tokens": None})):
    try:
        main._note_usage("translate", "gpt-5.6-terra", bad)
    except Exception as e:
        fail.append("учёт упал на %r: %s" % (bad, e))
check(main._USAGE_TOTAL["calls"] == 0,
      "мусорный ответ не роняет вызов и не добавляет выдуманных цифр")
check(not fail or all("учёт упал" not in f for f in fail), "исключений не было")

# ─────────── 7. Смета человека доезжает до записи о прогоне ───────────
print("\n=== 7. Смета и факт лежат рядом ===")
reset()
main.STATE = {"projects": [], "glossary": [], "tm": [], "termQueue": [], "runCosts": []}
job = {"id": 7, "kind": "full", "project": 1, "status": "done", "done": 42,
       "finished": "2026-08-23 10:00:00", "params": {"est_cost": 14.71}, "counters": {}}
main._usage_begin(job)
main._note_usage("termcheck", "gpt-5.6-terra", Resp(1_000_000, 100_000, reasoning=60_000))
main._note_usage("repair", "gpt-5.6-terra", Resp(500_000, 50_000))
main._usage_end(job)
rec = main.STATE["runCosts"][-1]
check(rec["est"] == 14.71, "смета, показанная человеку, сохранена вместе с прогоном")
check(rec["cost"] == job["usage"]["cost"] > 0, "факт сохранён и не ноль")
check(rec["steps"]["termcheck"]["reasoning"] == 60_000,
      "разбивка по шагам пережила запись: по ней и правят смету")
check("ids" not in rec and "segments" in rec,
      "запись компактная: сколько сегментов — да, список id — нет")
check(main._USAGE_SINK is None, "после прогона сток закрыт")

# ─────────── 8. Вне прогона расход тоже считается ───────────
print("\n=== 8. Одиночный вызов по кнопке не теряется ===")
before = main._USAGE_TOTAL["calls"]
main._note_usage("translate", "gpt-5.6-luna", Resp(100, 20))
check(main._USAGE_TOTAL["calls"] == before + 1,
      "вызов вне прогона попал в счётчик процесса")
check(len(main.STATE["runCosts"]) == 1,
      "и при этом не превратился в лишнюю запись о прогоне")

# ─────────── 9. История прогонов не растёт бесконечно ───────────
print("\n=== 9. История ограничена ===")
main.STATE["runCosts"] = []
for i in range(main.RUN_COST_HISTORY + 20):
    j = {"id": i, "kind": "full", "project": 1, "status": "done", "done": 1,
         "finished": "", "params": {}, "counters": {}}
    main._usage_begin(j)
    main._note_usage("translate", "gpt-5.6-luna", Resp(10, 5))
    main._usage_end(j)
check(len(main.STATE["runCosts"]) == main.RUN_COST_HISTORY,
      "в state.json остаются последние %d прогонов, а не все" % main.RUN_COST_HISTORY)
check(main.STATE["runCosts"][-1]["job"] == main.RUN_COST_HISTORY + 19,
      "последним лежит последний, а не первый")

# ─────────── 10. Пустой прогон следа не оставляет ───────────
print("\n=== 10. Прогон без единого вызова ===")
n = len(main.STATE["runCosts"])
j = {"id": 999, "kind": "full", "project": 1, "status": "done", "done": 0,
     "finished": "", "params": {}, "counters": {}}
main._usage_begin(j)
main._usage_end(j)
check(len(main.STATE["runCosts"]) == n,
      "прогон, где модель не вызывали ни разу, в историю расходов не пишется")

# ─────────── 11. Отчёт наружу ───────────
print("\n=== 11. /api/usage ===")
main.STATE["runCosts"] = [
    {"job": 1, "kind": "full", "project": 1, "status": "done", "finished": "",
     "segments": 10, "est": 15.0, "cost": 3.0, "calls": 100, "unpriced": 0,
     "in": 1, "cached_in": 0, "out": 1, "reasoning": 0, "steps": {}},
    {"job": 2, "kind": "full", "project": 1, "status": "done", "finished": "",
     "segments": 10, "est": 5.0, "cost": 1.0, "calls": 100, "unpriced": 0,
     "in": 1, "cached_in": 0, "out": 1, "reasoning": 0, "steps": {}},
]
rep = main.usage_report()
check(rep["runs"][0]["job"] == 2, "свежий прогон идёт первым")
check(rep["estRatio"] == 5.0,
      "во сколько раз смета в среднем выше факта: (15+5)/(3+1) = 5.0, а не среднее отношений")
main.STATE["runCosts"] = []
check(main.usage_report()["estRatio"] is None,
      "без прогонов поправки нет, и выдумывать её не из чего")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
