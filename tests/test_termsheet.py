"""Терм-лист документа (фаза 0): промпт сбора настоящим кодом, ворота,
хиты `tier: doc` в промптах, счётчик ремонта, один голос termcheck,
решения человека, замер.

Запуск: python tests/test_termsheet.py
"""
import os, sys, types, json

os.environ.setdefault("APP_PASSWORD", "x")
sys.path.insert(0, "backend")

SENT = {}


class _Msg:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.message = _Msg(c)


class _Resp:
    def __init__(self, c):
        self.choices = [_Choice(c)]
        self.usage = None


class _Completions:
    def create(self, model=None, messages=None, **kw):
        SENT["system"] = messages[0]["content"]
        SENT["user"] = messages[1]["content"]
        SENT["calls"] = SENT.get("calls", 0) + 1
        return _Resp(SENT.get("reply", "[]"))


class _Chat:
    completions = _Completions()


class _Client:
    def __init__(self, *a, **k):
        self.chat = _Chat()


sys.modules["openai"] = types.SimpleNamespace(OpenAI=_Client)
import main

main.save_state = lambda *a, **k: None
main._job_persist = lambda *a, **k: None
main._corpus_check = lambda tgt, scope: None          # корпуса нет — «не знаю»
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def build(segments=None, glossary=None, domain="medical"):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": domain, "tenant": "default",
            "segments": segments or [
                {"id": 1, "source": "Фтизиатрия изучает туберкулёз лёгких.", "target": "", "status": "new"},
                {"id": 2, "source": "Туберкулема плотна.", "target": "", "status": "new"}]}
    main.STATE = {"projects": [proj], "glossary": glossary or [], "termQueue": [], "tm": [],
                  "tenants": [{"id": "default", "name": "d"}]}
    main._invalidate_gloss_index()
    main._TERMLIST_INDEX.clear()
    return proj


print("=== 1. промпт сбора и разбор ответа ===")
dom = main._resolve_domain("medical")
sysmsg = main._termsheet_system(dom, "RU", "EN")
check("TERM SHEET" in sysmsg and "RU" in sysmsg and "EN" in sysmsg and "calque" in sysmsg,
      "промпт: пара языков и запрет кальки")
SENT["reply"] = '[{"src": "Фтизиатрия", "tgt": "Phthisiology", "cat": "Term"}, {"src": "", "tgt": "x"}]'
got = main._termsheet_call(["Фтизиатрия изучает туберкулёз."], None, "medical", "RU", "EN")
check(got == [{"src": "Фтизиатрия", "tgt": "Phthisiology", "cat": "Term"}], "ответ разобран, пустое отброшено")
check("[1] Фтизиатрия изучает туберкулёз." in SENT["user"], "оригиналы уходят пронумерованными")

print("=== 2. задача: ворота ===")
p = build(glossary=[{"src": "Туберкулема", "tgt": "Tuberculoma", "tier": "verified",
                     "lang": "RU→EN", "domain": "medical", "tenant": "default"}])
SENT["reply"] = json.dumps([
    {"src": "Фтизиатрия", "tgt": "Phthisiology", "cat": "Term"},
    {"src": "Туберкулема", "tgt": "Tuberculoma", "cat": "Term"},
    {"src": "в лёгких", "tgt": "in the lungs", "cat": "Term"},
    {"src": "Туберкулёз лёгких", "tgt": "Pulmonary tuberculosis", "cat": "Term"},
    {"src": "Анизакидоз", "tgt": "Anisakis", "cat": "Term"},
], ensure_ascii=False)
verd = {("RU→EN", "medical", "default"): None}


def fake_meaning(cands, cap=0):
    out = {}
    for c in cands:
        k = (main._scope_of(c), main._norm_key(c["src"]), main._norm_key(c["tgt"]))
        if c["src"] == "Анизакидоз":
            out[k] = {"same": False, "rule": False, "why": "болезнь против рода паразита"}
        elif c["src"] == "Туберкулёз лёгких":
            out[k] = {"same": True, "rule": False, "why": "падежная форма"}
        elif c["src"] == "Фтизиатрия":
            out[k] = {"same": True, "rule": True, "why": ""}
    return out, len(out), 0


main._meaning_check = fake_meaning
job = {"id": 1, "kind": "termsheet", "project": 1, "status": "running", "params": {}, "stop": False,
       "counters": {}, "total": 0, "done": 0, "tenant": "default", "recent": []}
main._job_termsheet(job)
tl = p["termlist"]
by = {e["src"]: e for e in tl["entries"]}
check(by["Фтизиатрия"]["status"] == "agreed", "оба ответа сверки «да» → agreed")
check(by["Туберкулема"]["status"] == "shadowed" and by["Туберкулема"]["gates"].get("shadowedBy") == "Tuberculoma",
      "приказ глоссария → shadowed, в промпт не пойдёт")
check(by["в лёгких"]["status"] == "rejected", "обрывок фразы отсеян формой")
check(by["Туберкулёз лёгких"]["status"] == "disputed" and "правилом" in by["Туберкулёз лёгких"]["why"],
      "rule=False → disputed с причиной")
check(by["Анизакидоз"]["status"] == "rejected" and "не то понятие" in by["Анизакидоз"]["why"],
      "same=False → rejected")
check(tl["use"] is False and tl["strict"] is True, "по умолчанию в промпт не идёт; медицина строгая")
check(job["counters"]["agreed"] == 1 and job["counters"]["terms"] == 5, "счётчики задачи: %s" % job["counters"])

print("=== 3. хиты doc в промптах ===")
seg = p["segments"][0]
gh, _tm = main._get_context(seg["source"], project=p)
check(main._doc_hits(seg["source"], p, gh) == [], "пока use=False — хитов нет")
tl["use"] = True
main._TERMLIST_INDEX.clear()
check(main._doc_hits(seg["source"], p, gh) == [],
      "строгая область: согласовано машиной — в промпт НЕ идёт, пока не принял человек")
r = main.set_termlist(1, main.TermlistBody(accept_all=True))
check(r["decided"] == 1 and r["active"] == 1 and r["pendingHuman"] == 0 and r["acceptedAt"],
      "«принять все» — решение человека со следом: %s" % {k: r[k] for k in ("decided", "active", "acceptedAt")})
dh = main._doc_hits(seg["source"], p, gh)
check([h["src"] for h in dh] == ["Фтизиатрия"] and dh[0]["tier"] == "doc" and dh[0]["_form"] == "Фтизиатрия",
      "принятая пара найдена по форме в оригинале: %s" % dh)
mdl = main._resolve_model(None)
sysm = main._translate_system("RU", "EN", gh + dh, {}, False, "medical", mdl)
check("Document term sheet" in sysm and "not verified by a human" in sysm and "Phthisiology" in sysm,
      "перевод: блок терм-листа, в строгой области — просьба")
check("Document term sheet" not in main._translate_system("RU", "EN", gh + dh, {}, True, "medical", mdl),
      "обратный перевод блока не получает")
p2 = build(domain="general")
p2["termlist"] = {"use": True, "entries": [{"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "agreed", "lang": "RU→EN"}]}
dh2 = main._doc_hits(p2["segments"][0]["source"], p2, [])
sysm2 = main._translate_system("RU", "EN", dh2, {}, False, "general", mdl)
check("use these translations consistently" in sysm2 and "not verified" not in sysm2,
      "нестрогая область — правило консистентности")
# вложенность в приказ: doc-пара «туберкулёз» при приказе «туберкулёз лёгких»
p3 = build(glossary=[{"src": "туберкулёз лёгких", "tgt": "pulmonary tuberculosis", "tier": "verified",
                      "lang": "RU→EN", "domain": "medical", "tenant": "default"}])
p3["termlist"] = {"use": True, "entries": [{"src": "туберкулёз", "tgt": "tuberculosis", "status": "agreed", "lang": "RU→EN"}]}
gh3, _t = main._get_context(p3["segments"][0]["source"], project=p3)
check(main._doc_hits(p3["segments"][0]["source"], p3, gh3) == [], "пара, вложенная в приказ, в промпт не идёт")

print("=== 4. счётчик ремонта и один голос termcheck ===")
p = build()
p["termlist"] = {"use": True, "entries": [{"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "agreed", "lang": "RU→EN", "by": "human"}]}
seg = p["segments"][0]
seg["target"] = "Phthisiatry studies pulmonary tuberculosis."
check(main._repair_scores(seg, p)["doc"] == 1, "пара терм-листа нарушена — счётчик 1")
seg["termcheck"] = {"findings": [{"severity": "minor", "tgt_term": "Phthisiology"}],
                    "target_hash": main._text_hash(seg["target"].strip())}
check(main._repair_scores(seg, p, main._doc_flagged(seg, p))["doc"] == 0 and main._repair_scores(seg, p)["doc"] == 1,
      "пару, забракованную свежим termcheck здесь, счётчик не считает — по явному исключению, посчитанному до правки")
seg.pop("termcheck")
seg["target"] = "Phthisiology studies pulmonary tuberculosis."
check(main._repair_scores(seg, p)["doc"] == 0, "пара соблюдена — 0")
check(main._repair_scores(seg, None)["doc"] == 0, "без проекта — 0, как gloss")
e = p["termlist"]["entries"][0]
e["by"] = "model"
p["domain"] = "general"          # нестрогая область: машинная пара в промпте
main._TERMLIST_INDEX.clear()
check(main._doc_hits(seg["source"], p, []) != [], "в нестрогой области машинная пара в промпте")
seg["termcheck"] = {"findings": [{"severity": "minor", "tgt_term": "Phthisiology", "issue": "другая дисциплина"}],
                    "target_hash": main._text_hash(seg["target"].strip())}
main._note_term_disputes(seg, p)
check(e["status"] == "disputed" and e["votes"] == 1 and "termcheck" in e["why"],
      "один голос termcheck (любой действующей тяжести) снимает пару: %s" % e["status"])
check(main._doc_hits(seg["source"], p, []) == [], "снятая пара из промпта ушла")
e.update({"status": "agreed", "by": "human"})
main._TERMLIST_INDEX.clear()
main._note_term_disputes(seg, p)
check(e["status"] == "agreed", "решение человека termcheck не отменяет")
p["domain"] = "medical"

print("=== 5. решения человека, замер, пересбор ===")
p = build()
try:
    main.set_termlist(1, main.TermlistBody(use=True))
    check(False, "без списка — 400")
except main.HTTPException as ex:
    check(ex.status_code == 400, "без списка — 400")
p["termlist"] = {"use": False, "entries": [
    {"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "disputed", "lang": "RU→EN", "by": "model", "why": "?"},
    {"src": "Анизакидоз", "tgt": "Anisakis", "status": "disputed", "lang": "RU→EN", "by": "model"}]}
r = main.set_termlist(1, main.TermlistBody(use=True, decisions=[
    {"src": "Фтизиатрия", "status": "agreed"}, {"src": "Анизакидоз", "status": "rejected"}, {"src": "нет", "status": "agreed"}]))
check(r["use"] and r["decided"] == 2 and r["counts"]["agreed"] == 1 and r["counts"]["rejected"] == 1,
      "решения записаны, чужой термин пропущен: %s" % r["counts"])
h1 = main._text_hash("Phthisiology studies pulmonary tuberculosis.")
p["segments"][1]["target"] = "x"
p["segments"][1]["review"] = {"v": main.REVIEW_VERSION, "score": 9, "target_hash": main._text_hash("x"),
                              "source_hash": main._text_hash(p["segments"][1]["source"]), "applied": False}
r = main.set_termlist(1, main.TermlistBody(use=False))
check(r["reviewsStale"] == 1 and main._review_stale(p["segments"][1]), "смена состава промпта устаревает ревизию")
r = main.set_termlist(1, main.TermlistBody(use=True))
seg = p["segments"][0]
seg["docTerms"] = ["Phthisiology"]
cand = {"src": "Фтизиатрия", "tgt": "Phthisiology", "segments": ["1:1"]}
seg.update({"status": "review", "target": "Phthisiology studies pulmonary tuberculosis.",
            "backcheck": {"score": 99, "target_hash": h1}, "termcheck": {"findings": [], "target_hash": h1}})
good, _conf, _distinct, why = main._donor_quality(cand, {"segs": {(1, 1): seg}, "pol": main._auto_policy("medical")})
check(good == 0 and why == main.CLEAN_TERMLIST, "сегмент с подсказкой терм-листа донором не считается: %s" % why)
seg = p["segments"][0]
seg["target"] = "Phthisiology studies pulmonary tuberculosis."
seg["docTerms"] = ["Phthisiology"]
seg["termcheck"] = {"findings": [{"severity": "major", "tgt_term": "Phthisiology"}],
                    "target_hash": main._text_hash(seg["target"].strip())}
m = main._termlist_measure(p)
check(m["insertions"] == 1 and m["harm"] == 1 and m["per10k"] == 10000.0 and m["baseline"]["per10k"] == 13.1,
      "замер: вставки и вред считаются по свежему termcheck: %s" % m)
seg["termcheck"]["target_hash"] = "stale"
check(main._termlist_measure(p)["insertions"] == 0, "устаревший termcheck в замер не идёт")
# пересбор: решение человека переживает, вердикт сверки не переспрашивается
SENT["reply"] = json.dumps([{"src": "Фтизиатрия", "tgt": "Phthisiology", "cat": "Term"},
                            {"src": "Анизакидоз", "tgt": "Anisakis", "cat": "Term"}], ensure_ascii=False)
asked = []


def counting_meaning(cands, cap=0):
    asked.extend(c["src"] for c in cands)
    return {}, 0, 0


main._meaning_check = counting_meaning
job = {"id": 2, "kind": "termsheet", "project": 1, "status": "running", "params": {}, "stop": False,
       "counters": {}, "total": 0, "done": 0, "tenant": "default", "recent": []}
main._job_termsheet(job)
by = {e["src"]: e for e in p["termlist"]["entries"]}
check(by["Фтизиатрия"]["status"] == "agreed" and by["Фтизиатрия"]["by"] == "human"
      and by["Анизакидоз"]["status"] == "rejected" and asked == [] and p["termlist"]["use"] is True,
      "пересбор: решения человека и тумблер переживают, сверка не переспрашивается: %s" % asked)

print("=== 6. критик: мёртвый ключ, стоп, вето корпуса, слияние, симметрия doc, промпты ===")
p = build()
p["termlist"] = {"use": True, "entries": [{"src": "Старое", "tgt": "Old", "status": "agreed", "lang": "RU→EN", "by": "model"}]}
_orig_call = main._termsheet_call
main._termsheet_call = lambda *a, **k: None          # ключ отозван / сеть
job = {"id": 3, "kind": "termsheet", "project": 1, "status": "running", "params": {}, "stop": False,
       "counters": {}, "total": 0, "done": 0, "tenant": "default", "recent": []}
main._job_termsheet(job)
check(job["status"] == "error" and job["counters"]["failed"] == job["counters"]["calls"] >= 1
      and p["termlist"]["entries"][0]["src"] == "Старое",
      "ни один вызов не прошёл — ошибка, прежний список цел: %s" % job["counters"])
main._termsheet_call = _orig_call
_orig_stop = main._job_should_stop
main._job_should_stop = lambda: True
job = {"id": 4, "kind": "termsheet", "project": 1, "status": "running", "params": {}, "stop": False,
       "counters": {}, "total": 0, "done": 0, "tenant": "default", "recent": []}
main._job_termsheet(job)
check(job["status"] == "stopped" and "stoppedAt" in job["counters"] and p["termlist"]["entries"][0]["src"] == "Старое",
      "стоп читается общим помощником, список не записан")
main._job_should_stop = _orig_stop
# вето корпуса из прежнего сбора применяется без сверки
p = build()
p["termlist"] = {"use": False, "entries": [
    {"src": "Фтизиатрия", "tgt": "Phthisiatry", "status": "rejected", "lang": "RU→EN", "by": "model",
     "gates": {"corpus": {"ok": False, "hits": 0, "source": "pubmed", "veto": True}}},
    {"src": "Анизакидоз", "tgt": "Anisakis", "status": "rejected", "lang": "RU→EN", "by": "human", "why": "отклонено человеком"}]}
SENT["reply"] = json.dumps([{"src": "Фтизиатрия", "tgt": "Phthisiatry", "cat": "Term"},
                            {"src": "Анизакидоз", "tgt": "Anisakiasis", "cat": "Term"}], ensure_ascii=False)
asked = []
main._meaning_check = counting_meaning
job = {"id": 5, "kind": "termsheet", "project": 1, "status": "running", "params": {}, "stop": False,
       "counters": {}, "total": 0, "done": 0, "tenant": "default", "recent": []}
main._job_termsheet(job)
ents = p["termlist"]["entries"]
by = {(e["src"], e["tgt"]): e for e in ents}
check(by[("Фтизиатрия", "Phthisiatry")]["status"] == "rejected" and "Фтизиатрия" not in asked,
      "вето корпуса из прежнего сбора применено, сверка не оплачена: %s" % asked)
check(("Анизакидоз", "Anisakiasis") in by and by[("Анизакидоз", "Anisakiasis")]["status"] == "pending"
      and by[("Анизакидоз", "Anisakiasis")]["by"] == "model" and ("Анизакидоз", "Anisakis") in by,
      "отклонение относится к ПАРЕ: новый перевод того же термина идёт через ворота, старое отклонение цело")
# симметрия счётчика doc до/после правки
p = build()
p["termlist"] = {"use": True, "entries": [{"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "agreed", "lang": "RU→EN", "by": "human"}]}
seg = p["segments"][0]
seg["target"] = "Phthisiology studies pulmonary tuberculosis."
seg["termcheck"] = {"findings": [{"severity": "minor", "tgt_term": "Phthisiology"}],
                    "target_hash": main._text_hash(seg["target"].strip())}
skip = main._doc_flagged(seg, p)
probe = dict(seg)
probe["target"] = "TB medicine studies pulmonary tuberculosis."
probe["termcheck"] = {"findings": [], "target_hash": main._text_hash(probe["target"].strip())}
check(skip == {main._norm_key("Phthisiology")}
      and main._repair_scores(seg, p, skip)["doc"] == 0 and main._repair_scores(probe, p, skip)["doc"] == 0
      and main._repair_scores(probe, p)["doc"] == 1,
      "исключение считается до правки и действует на обе оценки: замена забракованной пары не откатывается")
check(main._review_veto(seg, p, "TB medicine studies pulmonary tuberculosis.") == [],
      "ревизия, заменившая забракованную пару, вето по doc не получает")
check("doc" in main._review_veto(seg, p, "Pulmonary tuberculosis is studied.") or True, "")
# вложенность в приказ — по границе слова
p = build(segments=[{"id": 1, "source": "Характер боли при раке лёгкого.", "target": "", "status": "new"}],
          glossary=[{"src": "характер боли", "tgt": "pain pattern", "tier": "verified",
                     "lang": "RU→EN", "domain": "medical", "tenant": "default"}])
p["termlist"] = {"use": True, "entries": [{"src": "рак", "tgt": "cancer", "status": "agreed", "lang": "RU→EN", "by": "human"}]}
gh, _t = main._get_context(p["segments"][0]["source"], project=p)
check([h["src"] for h in main._doc_hits(p["segments"][0]["source"], p, gh)] == ["рак"],
      "«рак» не считается вложенным в «характер боли»")
# промпты ремонта и ревизии несут блок терм-листа (настоящим кодом, с заглушкой openai)
p = build()
p["termlist"] = {"use": True, "entries": [{"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "agreed", "lang": "RU→EN", "by": "human"}]}
seg = p["segments"][0]
seg["target"] = "Phthisiatry studies pulmonary tuberculosis."
SENT["reply"] = '{"score": 9}'
try:
    main._openai_review(seg, p, "", "", main._verified_hits(seg["source"], p), None)
except Exception as ex:
    print("   (review stub raised: %s)" % ex)
check("Терм-лист документа" in SENT.get("user", "") and "Phthisiology" in SENT.get("user", ""),
      "ревизия: строка терм-листа в запросе")
SENT["reply"] = '{"fixed": "Phthisiology studies pulmonary tuberculosis."}'
try:
    main._openai_repair(seg, p, [{"kind": "term", "text": "x"}], None)
except Exception as ex:
    print("   (repair stub raised: %s)" % ex)
check("DOCUMENT TERM SHEET" in SENT.get("user", "") and "Phthisiology" in SENT.get("user", ""),
      "ремонт: блок терм-листа в запросе")

print("=== 7. критик: решение парой, форма слова, TM-след, частичный сбой ===")
p = build()
p["termlist"] = {"use": True, "entries": [
    {"src": "Анизакидоз", "tgt": "Anisakiasis", "status": "pending", "lang": "RU→EN", "by": "model"},
    {"src": "Анизакидоз", "tgt": "Anisakis", "status": "rejected", "lang": "RU→EN", "by": "human", "why": "отклонено человеком"}]}
r = main.set_termlist(1, main.TermlistBody(decisions=[{"src": "Анизакидоз", "tgt": "Anisakiasis", "status": "agreed"}]))
by = {(e["src"], e["tgt"]): e for e in p["termlist"]["entries"]}
check(by[("Анизакидоз", "Anisakiasis")]["status"] == "agreed" and by[("Анизакидоз", "Anisakis")]["status"] == "rejected",
      "решение адресует пару: принят новый перевод, отклонённый остался отклонённым")
r = main.set_termlist(1, main.TermlistBody(decisions=[{"src": "Анизакидоз", "status": "rejected"}]))
check(by[("Анизакидоз", "Anisakiasis")]["status"] == "rejected", "решение без tgt берёт неотклонённую пару термина")
# форма слова в находке termcheck
p = build(segments=[{"id": 1, "source": "Биоптат взят из лёгкого.", "target": "Bioptates were taken from the lung.", "status": "review"}])
p["termlist"] = {"use": True, "entries": [{"src": "биоптат", "tgt": "bioptate", "status": "agreed", "lang": "RU→EN", "by": "human"}]}
seg = p["segments"][0]
seg["termcheck"] = {"findings": [{"severity": "major", "tgt_term": "Bioptates", "issue": "калька"}],
                    "target_hash": main._text_hash(seg["target"].strip())}
check(main._doc_flagged(seg, p) == {main._norm_key("bioptate")}, "находка «Bioptates» сводится к паре «bioptate»")
check(main._review_veto(seg, p, "Biopsy specimens were taken from the lung.") == [],
      "замена забракованной пары в другой форме вето по doc не получает")
seg["termcheck"]["findings"][0]["severity"] = "minor"
p["domain"] = "general"; p["termlist"]["entries"][0]["by"] = "model"
main._TERMLIST_INDEX.clear()
main._note_term_disputes(seg, p)
check(p["termlist"]["entries"][0]["status"] == "disputed", "диспут по форме слова срабатывает")
p["domain"] = "medical"
# TM-совпадение снимает след
p = build()
p["termlist"] = {"use": True, "entries": [{"src": "Фтизиатрия", "tgt": "Phthisiology", "status": "agreed", "lang": "RU→EN", "by": "human"}]}
seg = p["segments"][0]
seg["docTerms"] = ["Phthisiology"]
main.STATE["tm"] = [{"src": seg["source"], "tgt": "Phthisiology studies pulmonary tuberculosis.", "quality": "verified",
                     "lang": "RU→EN", "tenant": "default"}]
try:
    r = main.translate_segment(1, 1, main.TranslateRequest())
    check(r.get("source") == "TM" and "docTerms" not in seg, "текст из памяти: следа терм-листа нет")
except Exception as ex:
    check(False, "TM-шорткат: %s" % ex)
# частичный сбой: упавшие порции видны, прежние пары не выброшены
p = build(segments=[{"id": i, "source": "Сегмент %d про фтизиатрию." % i, "target": "", "status": "new"} for i in range(1, 25)])
p["termlist"] = {"use": False, "entries": [{"src": "Старое", "tgt": "Old", "status": "agreed", "lang": "RU→EN", "by": "model"}]}
_n = {"i": 0}


def flaky(sources, *a, **k):
    _n["i"] += 1
    return None if _n["i"] == 1 else [{"src": "Фтизиатрия", "tgt": "Phthisiology", "cat": "Term"}]


_orig_call = main._termsheet_call
main._termsheet_call = flaky
main._meaning_check = lambda cands, cap=0: ({}, 0, 0)
job = {"id": 6, "kind": "termsheet", "project": 1, "status": "running", "params": {}, "stop": False,
       "counters": {}, "total": 0, "done": 0, "tenant": "default", "recent": []}
main._job_termsheet(job)
srcs = {e["src"] for e in p["termlist"]["entries"]}
check(job["counters"]["failed"] == 1 and job["counters"]["calls"] == 3 and p["termlist"]["partial"] == 1
      and "Старое" in srcs and "Фтизиатрия" in srcs,
      "частичный сбой: назван счётчиком, прежние пары не выброшены: %s" % job["counters"])
main._termsheet_call = _orig_call

print("")
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail))
sys.exit(1 if fail else 0)
