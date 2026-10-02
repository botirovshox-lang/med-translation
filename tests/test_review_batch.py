"""Ревизия пачкой у реплик субтитров: инструкция один раз на несколько строк.

Сторожится, по важности:
  • вердикт уходит СВОЕЙ строке (номер n → сегмент), даже когда модель
    отвечает не по порядку;
  • ответ принимается целиком или никак — сбой, обрезка, лишний/пропавший
    номер уводят строки на одиночные вызовы, а не теряют и не сдвигают их;
  • совет, похожий на чужую строку пачки, не берётся — строка спрашивается
    отдельно;
  • промпт одиночного вызова в пачке не тронут ни байтом (пачка дописывает
    формат в конец);
  • у обычного документа и при выключенном REVIEW_BATCH всё как было;
  • вердикт помнит, что вынесен пачкой.
Клиент OpenAI подменён, наш код отрабатывает по-настоящему (закон
test_prompt_build.py).
"""
import json, os, sys, types, tempfile, pathlib

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"

CALLS = []
MODE = {"batch": "ok"}


class FakeResp:
    def __init__(self, text, finish="stop"):
        self.choices = [types.SimpleNamespace(
            message=types.SimpleNamespace(content=text), finish_reason=finish)]
        self.usage = types.SimpleNamespace(prompt_tokens=1500, completion_tokens=300,
                                           total_tokens=1800)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        system, user = messages[0]["content"], messages[1]["content"]
        batch = "РЕЖИМ ПАЧКИ" in system
        CALLS.append({"batch": batch, "system": system, "user": user, "kw": kw})
        if not batch:
            return FakeResp(json.dumps({"score": 8}))
        items = json.loads(user)
        mode = MODE["batch"]
        if mode == "length":
            return FakeResp("{\"lines\": [", finish="length")
        if mode == "garbage":
            return FakeResp("не JSON")
        lines = []
        for it in reversed(items):              # не по порядку — нарочно
            n = it["n"]
            if it["target"].startswith("BAD"):
                lines.append({"n": n, "score": 3, "issues": ["плохо"],
                              "fixed": "Good " + it["target"][3:]})
            else:
                lines.append({"n": n, "score": 9})
        if mode == "missing":
            lines = lines[1:]
        if mode == "swap":
            # Совет строки 2 — буква в букву перевод строки 3.
            for ln in lines:
                if ln["n"] == 2:
                    ln.update(score=3, fixed=items[2]["target"])
        return FakeResp(json.dumps({"lines": lines}, ensure_ascii=False))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
main.PURGE_DIR = pathlib.Path(tempfile.mkdtemp(prefix="review-batch-test-"))

fail = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)))
    if not cond:
        fail.append(name)


def project(n, media=True, bad=()):
    segs = [{"id": i + 1, "source": f"Реплика номер {i + 1} про погоду",
             "target": (f"BADline {i + 1} weather" if i + 1 in bad
                        else f"Line number {i + 1} about weather"),
             "status": "translated"} for i in range(n)]
    p = {"id": 777, "src": "RU", "tgt": "EN", "domain": "general", "segments": segs,
         "fileName": "clip.srt"}
    if media:
        p["media"] = {"ext": ".mp4", "duration": 60}
    return p


def run(p):
    CALLS.clear()
    return main._review_ask_many(p["segments"], p, None)


main.REVIEW_BATCH = 6

# 1. 12 строк → две пачки по 6, вердикты по своим строкам.
MODE["batch"] = "ok"
p = project(12, bad=(4,))
res = run(p)
check("12 строк — два вызова", len(CALLS) == 2 and all(c["batch"] for c in CALLS),
      [c["batch"] for c in CALLS])
check("пачки поровну 6+6",
      [len(json.loads(c["user"])) for c in CALLS] == [6, 6])
check("вердикт каждой строке", len(res) == 12 and all(r for r in res))
check("номер → своя строка (ответ шёл задом наперёд)",
      res[3]["score"] == 3 and res[3]["fixed"] == "Good line 4 weather"
      and all(r["score"] == 9 for i, r in enumerate(res) if i != 3),
      [r["score"] for r in res])
check("пачка отмечена на вердикте", res[0].get("batch") == 6)
check("цена пачки делится поровну",
      abs(sum(r["cost"] for r in res) - 2 * main._usage_cost(
          main._resolve_model(main._dm("review"))["id"], 1500, 300)) < 1e-9)

# 2. Промпт одиночного вызова — префикс пачки байт в байт.
single_sys = main._review_system(main._resolve_domain("general"),
                                 main._lang_prompt("RU"), main._lang_prompt("EN"),
                                 main._prompt_style(p))
check("промпт одиночного не тронут",
      CALLS[0]["system"].startswith(single_sys)
      and CALLS[0]["system"][len(single_sys):] == main.REVIEW_BATCH_RULES)
it = json.loads(CALLS[0]["user"])[1]
check("у элемента своя обстановка",
      it["before"] == "Реплика номер 1 про погоду"
      and it["after"] == "Реплика номер 3 про погоду"
      and it.get("before_tgt") == "Line number 1 about weather", it)
check("потолок ответа растёт с пачкой",
      (CALLS[0]["kw"].get("max_completion_tokens") or 0) > 2048
      or (CALLS[0]["kw"].get("max_tokens") or 0) > 900, CALLS[0]["kw"])

# 3. Сбой пачки — строки по одной, ни одна не потеряна.
for mode in ("garbage", "length", "missing"):
    MODE["batch"] = mode
    res = run(project(6))
    check(f"«{mode}» → по одной", sum(1 for c in CALLS if c["batch"]) == 1
          and sum(1 for c in CALLS if not c["batch"]) == 6
          and all(r and r["score"] == 8 and not r.get("batch") for r in res),
          [(c["batch"]) for c in CALLS])

# 3а. Цена отвергнутой пачки не теряется: сумма по ответам = счёт.
MODE["batch"] = "garbage"
res = run(project(6))
unit = main._usage_cost(main._resolve_model(main._dm("review"))["id"], 1500, 300)
check("цена отвергнутой пачки в ответах",
      abs(sum(r["cost"] for r in res) - 7 * unit) < 1e-9,
      (sum(r["cost"] for r in res), 7 * unit))

# 4. Совет, похожий на чужую строку, не берётся — только эта строка отдельно.
MODE["batch"] = "swap"
res = run(project(6))
check("перепутанный совет → одна строка отдельно",
      sum(1 for c in CALLS if not c["batch"]) == 1
      and res[1]["score"] == 8 and not res[1].get("batch")
      and res[0].get("batch") == 6, [c["batch"] for c in CALLS])
check("правка своего перевода — своя, хоть соседи и похожи",
      main._review_fixed_mine("Line number 4 about the weather today",
                              "Line number 4 about weather",
                              ["Line number 5 about weather", "Line number 3 about weather"]))
check("копия чужого перевода — чужая",
      not main._review_fixed_mine("Mother said we should go home now",
                                  "Line number 4 about weather",
                                  ["Mother said we should go home"]))
check("полная переписка без сходства ни с кем — своя",
      main._review_fixed_mine("Zzz qqq", "Line about weather", ["Another line here"]))

# 5. Обычный документ и выключатель — по одной, как было.
MODE["batch"] = "ok"
run(project(6, media=False) | {"fileName": "book.docx"})
check("документ — по одной", len(CALLS) == 6 and not any(c["batch"] for c in CALLS))
main.REVIEW_BATCH = 0
run(project(6))
check("REVIEW_BATCH=0 — по одной", len(CALLS) == 6 and not any(c["batch"] for c in CALLS))
main.REVIEW_BATCH = 6

# 6. Разбор ответа: всё или ничего.
A = main._review_batch_answer
check("разбор: номера 1..N", A('{"lines":[{"n":2,"score":9},{"n":1,"score":"7"}]}', 2)
      == {1: {"score": 9.0, "issues": [], "fixed": "", "source_suspect": False},
          0: {"score": 7.0, "issues": [], "fixed": "", "source_suspect": False}})
check("разбор: повтор номера — нет", A('{"lines":[{"n":1,"score":9},{"n":1,"score":9}]}', 2) is None)
check("разбор: номер вне пачки — нет", A('{"lines":[{"n":1,"score":9},{"n":3,"score":9}]}', 2) is None)
check("разбор: оценка не число — нет", A('{"lines":[{"n":1,"score":"x"}]}', 1) is None)
check("разбор: без оценки — нет", A('{"lines":[{"n":1}]}', 1) is None)
check("разбор: обёртка ```json", A('```json\n{"lines":[{"n":1,"score":12}]}\n```', 1)
      == {0: {"score": 10.0, "issues": [], "fixed": "", "source_suspect": False}})

check("разбор: score true — нет", A('{"lines":[{"n":1,"score":true}]}', 1) is None)

# 6а. Резка по знакам: длинные строки — в разные пачки, одиночная — по одной.
MODE["batch"] = "ok"
old_cap = main.REVIEW_BATCH_CHARS
main.REVIEW_BATCH_CHARS = 120
p = project(4)
for sg in p["segments"][:2]:
    sg["source"] = "длинная " * 12
g = main._review_groups(p["segments"])
check("потолок знаков режет пачку", [len(x) for x in g] == [1, 1, 2], [len(x) for x in g])
run(p)
check("одиночные группы — обычным вызовом",
      sum(1 for c in CALLS if c["batch"]) == 1 and sum(1 for c in CALLS if not c["batch"]) == 2)
main.REVIEW_BATCH_CHARS = old_cap

# 7. Через эндпоинт: вердикт на сегменте помнит пачку.
p = project(4, bad=(2,))
p["id"] = 778
main.STATE.setdefault("projects", []).append(p)
main.get_project = lambda pid: p
main._guard_project_write = lambda pid: None
main._key_gate = lambda *a, **k: None
CALLS.clear()
out = main.review_project(778, main.ReviewRequest(dry_run=True))
check("эндпоинт: один вызов на 4 строки",
      len(CALLS) == 1 and CALLS[0]["batch"], len(CALLS))
check("эндпоинт: batch на записи", all((s.get("review") or {}).get("batch") == 4
                                       for s in p["segments"]))
check("эндпоинт: кандидат своей строке",
      p["segments"][1]["review"].get("candidate") == "Good line 2 weather"
      and not p["segments"][0]["review"].get("candidate"))

# 8. В данных — НАСТОЯЩИЙ id модели даже при сессии владельца (псевдоним
# ставит только выдача): иначе «проверял тот, кто писал» сломалось бы.
real = main._resolve_model(main._dm("review"))["id"]
tok = main.CURRENT_SESSION.set({"tenant": "default", "user": None, "role": "owner"})
try:
    CALLS.clear()
    one = main._review_ask_many(project(1)["segments"], project(1), None)
    MODE["batch"] = "ok"
    many = main._review_ask_many(project(3)["segments"], project(3), None)
finally:
    main.CURRENT_SESSION.reset(tok)
check("одиночный: в данных настоящий id", one[0]["model"] == real, one[0]["model"])
check("пачка: в данных настоящий id", all(r["model"] == real for r in many),
      [r["model"] for r in many])

print("ГОТОВО" if not fail else f"ПРОВАЛОВ: {len(fail)}")
sys.exit(1 if fail else 0)
