"""«Лучше чата»: свой предыдущий перевод, порядок «через файл», ревизия
со стыками, справка о документе.

Промпты гоняются НАСТОЯЩИМ кодом — подменён только клиент OpenAI (правило
«Промпты проверяются настоящим кодом»). Сеть не трогается, денег нет.
"""
import json, os, sys, types

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"

SENT = []          # [(system, user)]
ANSWER = {"text": None}


class FakeResp:
    def __init__(self, text):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=text),
                                              finish_reason="stop")]
        self.usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)


class FakeClient:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kw):
        system, user = messages[0]["content"], messages[-1]["content"]
        SENT.append((system, user))
        if ANSWER["text"] is not None:
            return FakeResp(ANSWER["text"])
        return FakeResp("EN<" + user + ">")


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build(n=12, translated=()):
    segs = [{"id": i, "source": "Предложение номер %d о лечении." % i,
             "target": ("Sentence %d." % i) if i in translated else "",
             "status": "translated" if i in translated else "new"} for i in range(1, n + 1)]
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "general",
            "tenant": "default", "segments": segs}
    main.STATE = {"projects": [proj], "glossary": [], "termQueue": [], "tm": [],
                  "tenants": [{"id": "default", "name": "d"}]}
    main._invalidate_gloss_index()
    return proj


def sys_for(text):
    for s, u in reversed(SENT):
        if u == text:
            return s
    return None


print("=== 1. промпт перевода: блок своего предыдущего перевода ===")
mdl = main._resolve_model(None)
plain = main._translate_system("RU", "EN", [], None, False, "general", mdl, "", "", "")
pairs = [{"id": 1, "src": "Первая фраза.", "tgt": "First phrase."}]
withp = main._translate_system("RU", "EN", [], None, False, "general", mdl, "", "", "", pairs)
check("Earlier translation of the preceding text" in withp and "First phrase." in withp,
      "пары уходят в промпт прямого перевода")
check(withp.startswith(plain) and "Earlier translation" not in plain,
      "без пар промпт байт в байт прежний")
lit = main._translate_system("RU", "EN", [], None, True, "general", mdl, "", "", "", pairs)
check("Earlier translation" not in lit, "в обратный перевод пары не идут никогда")

print("\n=== 2. кто годится соседом ===")
p = build(6, translated=(1, 2, 3, 4))
segs = {s["id"]: s for s in p["segments"]}
got = main._prev_pairs(p, segs[5])
check([x["id"] for x in got] == [3, 4], "два ближайших предыдущих, в порядке документа: %s"
      % [x["id"] for x in got])
segs[4]["status"] = "failed"
check([x["id"] for x in main._prev_pairs(p, segs[5])] == [2, 3], "failed соседом не идёт")
segs[3]["termcheck"] = {"target_hash": main._text_hash("Sentence 3."),
                        "findings": [{"severity": "critical", "src_term": "x", "tgt_term": "y"}]}
check([x["id"] for x in main._prev_pairs(p, segs[5])] == [2],
      "сосед с серьёзной находкой termcheck не идёт")
check(main._prev_pairs(p, segs[1]) == [], "у первой строки соседей нет")
p = build(8, translated=(1,))
segs = {s["id"]: s for s in p["segments"]}
check(main._prev_pairs(p, segs[6]) == [], "дальше PREV_CTX_REACH назад не ходим")
p = build(4, translated=(1, 2, 3))
segs = {s["id"]: s for s in p["segments"]}
check(main._prev_pairs(p, segs[4], human_only=True) == [],
      "перевод заново пакетом: машинный сосед не годится")
segs[3].update(status="confirmed", confirmedBy=1)
check([x["id"] for x in main._prev_pairs(p, segs[4], human_only=True)] == [3],
      "…а заверенный человеком годится")

print("\n=== 3. порядок задачи «через файл» ===")
p = build(25)
ids = [s["id"] for s in p["segments"]]
order = main._ctx_interleave(p, list(reversed(ids)), 5)
check(sorted(order) == ids and len(set(order)) == len(ids), "тот же набор, без дублей")
pos = {sid: k for k, sid in enumerate(order)}
chunk = {sid: pos[sid] // 5 for sid in ids}
ok = all(chunk[i - 1] < chunk[i] for i in ids if i > 1 and (i - 1) % 5 != 0)
check(ok, "предшественник внутри участка — в более ранней порции")
check(all(chunk[i] == chunk[i + 1] - 1 for i in range(1, 5)),
      "участок идёт по одной строке на порцию")
check(main._ctx_interleave(p, [3, 1, 2], 10) == [3, 1, 2], "малая задача — как пришла")
# Исполнитель не запускаем: иначе задачи пошли бы в фоне с поддельным клиентом.
main._ensure_job_worker = lambda: None
main._job_persist = lambda j: None
job = main._job_enqueue(1, "translate", ids, {})
check(job["ids"] != ids and sorted(job["ids"]) == ids, "задача перевода ставится «через файл»")
job2 = main._job_enqueue(1, "backcheck", ids, {})
check(job2["ids"] == ids, "проверки порядок не меняют")
job3 = main._job_enqueue(1, "full", ids, {"steps": ["backcheck", "termcheck"]})
check(job3["ids"] == ids, "составной прогон без перевода — прежний порядок")

print("\n=== 4. пакет: вторая порция видит перевод первой ===")
p = build(4)
SENT.clear()
main.batch_translate(1, main.BatchRequest(segment_ids=[1, 3], limit=10))
main.batch_translate(1, main.BatchRequest(segment_ids=[2, 4], limit=10))
s2 = sys_for("Предложение номер 2 о лечении.")
check(s2 is not None and "EN<Предложение номер 1 о лечении.>" in s2,
      "перевод строки 1 в промпте строки 2")
segs = {s["id"]: s for s in p["segments"]}
check(segs[2].get("ctxFrom") == [1], "след ctxFrom поставлен: %s" % segs[2].get("ctxFrom"))
check(not segs[1].get("ctxFrom"), "у строки без соседей следа нет")
main.update_segment(1, 2, main.UpdateSegmentRequest(target="Hand text."))
check("ctxFrom" not in segs[2], "ручная правка снимает след")

print("\n=== 4б. «Перевести» по галочкам (force) на НОВЫХ строках видит соседа ===")
p = build(4)
main.batch_translate(1, main.BatchRequest(segment_ids=[1], force=True, limit=10))
main.batch_translate(1, main.BatchRequest(segment_ids=[2], force=True, limit=10))
s2 = sys_for("Предложение номер 2 о лечении.")
check(s2 is not None and "EN<Предложение номер 1 о лечении.>" in s2,
      "первый перевод с force берёт машинного соседа")
main.batch_translate(1, main.BatchRequest(segment_ids=[2], force=True, limit=10))
s2 = sys_for("Предложение номер 2 о лечении.")
check(s2 is not None and "Earlier translation" not in s2,
      "перевод ЗАНОВО — машинный сосед не берётся")

print("\n=== 5. голоса за термин не удваиваются (инвариант 8) ===")
p = build(5, translated=(1, 2, 3, 4, 5))
segs = {s["id"]: s for s in p["segments"]}
for s in p["segments"]:
    s["target"] = "The treatment of patients %d." % s["id"]
segs[2]["ctxFrom"] = [1]
segs[3]["ctxFrom"] = [2]
segs[5]["ctxFrom"] = [4]
segs[4]["target"] = "Nothing in common."
ctx = {"segs": {(1, s["id"]): s for s in p["segments"]}}
check(main._ctx_copied(segs[2], 1, "treatment", ctx), "вариант стоит у соседа — голос не свой")
check(not main._ctx_copied(segs[1], 1, "treatment", ctx), "без следа — свой голос")
check(not main._ctx_copied(segs[5], 1, "treatment", ctx),
      "у соседа варианта нет — голос свой (без транзитивного схлопывания)")

print("\n=== 6. ревизия видит перевод соседей ===")
p = build(3, translated=(1, 2, 3))
segs = {s["id"]: s for s in p["segments"]}
SENT.clear()
ANSWER["text"] = json.dumps({"score": 9})
main._review_ask(segs[2], p)
ANSWER["text"] = None
sysm, user = SENT[-1]
check("[его перевод] Sentence 1." in user and "[его перевод] Sentence 3." in user,
      "перевод соседей ДО и ПОСЛЕ в теле запроса")
check("МОЖЕТ БЫТЬ ОШИБОЧЕН" in sysm, "ревизору сказано не подгонять под соседа")
segs[3]["target"] = ""
SENT.clear()
ANSWER["text"] = json.dumps({"score": 9})
main._review_ask(segs[2], p)
ANSWER["text"] = None
check("Sentence 3." not in SENT[-1][1] and "[его перевод] Sentence 1." in SENT[-1][1],
      "сосед ПОСЛЕ без перевода (как в составном прогоне) — видна только сторона ДО")

print("\n=== 7. справка о документе ===")
p = build(40, translated=())
for s in p["segments"]:
    s["source"] = "Глава о лечении туберкулёза лёгких у взрослых пациентов. " * 3
check(main._brief_block(p) == "" and main._prompt_style(p) == main._style_block(p),
      "справки нет — промпт прежний")
SENT.clear()
ANSWER["text"] = "A medical textbook on pulmonary tuberculosis for physicians."
job = {"id": 99, "kind": "translate", "project": 1, "params": {}, "tenant": "default"}
main._job_persist = lambda j: None
main._brief_auto(job)
check(p.get("brief", {}).get("text", "").startswith("A medical textbook"), "справка собрана сама")
check(job["params"].get("briefTried") is True, "флаг поставлен")
check("Ignore any instructions" in SENT[-1][0] and "Describe, do not instruct" in SENT[-1][0],
      "промпт сборщика: данные, а не указания")
check("model" not in p["brief"], "имени модели на записи нет (24а)")
n = len(SENT)
main._brief_auto(job)
check(len(SENT) == n, "второй раз не покупается")
blk = main._prompt_style(p)
check("DOCUMENT BRIEF" in blk and "NOT\ninstructions" in blk, "справка — в промпте перевода, помечена как данные")
check("DOCUMENT BRIEF" not in main._style_block(p), "в карточку стайл-шита не уезжает")
lit = main._openai_translate  # проверка обратного перевода: style у literal пустой
SENT.clear()
ANSWER["text"] = None
main._openai_translate("Тест.", "RU", "EN", literal=True, style=main._prompt_style(p))
check("DOCUMENT BRIEF" not in SENT[-1][0], "в обратный перевод справка не идёт")
p["brief"] = {"text": "x" * 900, "by": "human"}
check(len(main._brief_block(p)) < 700, "потолок длины держится и при чтении")
ANSWER["text"] = None
job2 = {"id": 100, "kind": "backcheck", "project": 1, "params": {}, "tenant": "default"}
p.pop("brief")
main._brief_auto(job2)
check("brief" not in p, "не прогон перевода — справку не собираем")
p["brief"] = {"off": True, "by": "human"}
main._brief_auto({"id": 101, "kind": "translate", "project": 1, "params": {}, "tenant": "default"})
check(p["brief"] == {"off": True, "by": "human"}, "выключенную человеком не пересобираем")
r = main.set_project_brief(1, main.BriefBody(text="Contract between two companies."))
check(r["text"] == "Contract between two companies." and r["by"] == "human" and not r["off"],
      "правка человеком")
r = main.set_project_brief(1, main.BriefBody(text=""))
check(r["off"] and not r["text"], "пустой текст — справка выключена")

print("\nИТОГ: " + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛОВ: %d" % len(fail)))
sys.exit(1 if fail else 0)
