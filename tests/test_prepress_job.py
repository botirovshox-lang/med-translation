# -*- coding: utf-8 -*-
"""Предпечатная проверка задачей (раздел Ы2): сборка → страницы → взгляд
модели (подменён КЛИЕНТ, наш код — настоящий) → память; повтор берёт
память, пока тексты, строки, картинка и версии те же; низкий приоритет
очереди; расход — служебной организации.

    python tests/test_prepress_job.py
"""
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["WARM_CACHES"] = "0"
os.environ["EXPORT_QA"] = "0"
os.environ["PREPRESS"] = "observe"
os.environ["PREPRESS_TENANTS"] = "*"
sys.path.insert(0, "tools")
sys.path.insert(0, "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)[:300]))
    if not ok:
        FAILS.append(name)


try:
    import reportlab  # noqa: F401
    import pypdfium2  # noqa: F401
except ImportError as e:            # pragma: no cover
    print("ПРОПУЩЕН: нет модуля (%s)" % e)
    sys.exit(0)

import corpus_build as C  # noqa: E402
import main  # noqa: E402
import synth  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="ppj_"))
main.SOURCE_DIR = work / "src"
main.SOURCE_DIR.mkdir()
main.EXPORT_DIR = work / "exp"
main.save_state = lambda *a, **k: None

CALLS = []


class _U:
    prompt_tokens, completion_tokens = 2000, 120
    prompt_tokens_details = completion_tokens_details = None
    cache_read_input_tokens = cache_creation_input_tokens = 0


class _Msg:
    def __init__(self, t):
        self.content = t


class _Ch:
    def __init__(self, t):
        self.message = _Msg(t)
        self.finish_reason = "stop"


class _Resp:
    def __init__(self, t):
        self.choices = [_Ch(t)]
        self.usage = _U()


class _Comp:
    def create(self, **kw):
        CALLS.append(kw)
        sysmsg = kw["messages"][0]["content"]
        imgs = [x for x in kw["messages"][1]["content"] if x.get("type") == "image_url"]
        assert imgs, "нет картинок"
        assert "closed list" in sysmsg and "NOT defects" in sysmsg
        return _Resp('{"ok": false, "defects": [{"place": 1, "code": "OVERFLOW", '
                     '"action": "tight", "confidence": 0.9, "what": "x"}]}')


class _Client:
    def __init__(self):
        self.chat = type("C", (), {"completions": _Comp()})()


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: _Client()
main._provider_ready = lambda m: True
TENANTS_SEEN = []
_orig_note = main._note_usage


def _note(step, mid, resp):
    TENANTS_SEEN.append((step, main._current_tenant(), getattr(main._JOB_PROJECT, "id", "?")))
main._note_usage = _note

random.seed(3)
f = work / "inv.pdf"
C.pdf_invoice(f)
blob = f.read_bytes()
parsed = main._parse_upload(f.name, blob)
units = parsed["units"]
segs = main._new_segments([t for t, _ in units])
sd = synth.load()
for s_ in segs:
    s_["target"] = synth.pseudo(s_["source"], "en", 1.15, 0, True, sd)
    s_["status"] = "translated"
pid = 9301
project = {"id": pid, "title": "inv", "src": "RU", "tgt": "EN", "domain": "general",
           "tenant": "default", "fileName": f.name, "importKind": "pdf", "segments": segs}
paras = [t for t, _f in parsed["texts"]]
pairs = [[i, u + 1] for u, (_t, idxs) in enumerate(units) for i in idxs]
main._store_source_docx(project, parsed["docx"], f.name, pairs, len(paras), layout=parsed.get("layout"))
main._store_original(pid, f.name, blob)
main._project_by_id = lambda x: project if int(x) == pid else None


def run(keep_cache=False):
    if not keep_cache:
        for f_ in main._prepress_cache_paths(pid):
            if f_.exists():
                f_.unlink()
    job = {"id": 1, "kind": "prepress", "project": pid, "status": "running", "params": {},
           "counters": {}, "tenant": "default", "low": True, "total": 0, "done": 0}
    main._JOB_TENANT.id = "default"
    main._job_prepress(job)
    return job


print("=== первый проход: модель смотрит каждую страницу ===")
j1 = run()
c1 = j1["counters"]
check("страницы посчитаны", c1.get("pages", 0) >= 1, c1)
check("модель смотрела все страницы", c1.get("looked") == c1.get("pages"), c1)
check("вызовов модели — по странице", len(CALLS) == c1.get("pages"), len(CALLS))
check("дефект модели учтён", (c1.get("byCode") or {}).get("OVERFLOW") == c1.get("pages"), c1)
check("расход — служебной организации, не в себестоимость файла",
      all(t == main.QA_SERVICE_TENANT and p_ is None for _s, t, p_ in TENANTS_SEEN), TENANTS_SEEN)
mem = json.loads(main._prepress_path(pid).read_text(encoding="utf-8"))
check("память страниц записана", len(mem.get("pages") or {}) == c1.get("pages"))

print("=== повтор: тот же перевод — из памяти, модель не зовём ===")
n_calls = len(CALLS)
j2 = run()
check("все страницы из памяти", j2["counters"].get("fromMemory") == c1.get("pages"), j2["counters"])
check("новых вызовов нет", len(CALLS) == n_calls)

print("=== тот же вход и готовый файл — задача не работает второй раз ===")
run()
j2b = run(keep_cache=True)
check("свежий кэш — пропуск", j2b["counters"].get("skipped") == "fresh", j2b["counters"])

print("=== перевод поменялся — страница смотрится заново ===")
segs[0]["target"] = segs[0]["target"] + " Extra"
j3 = run()
check("причина — перевод", (j3["counters"].get("reasons") or {}).get("translation", 0) >= 1, j3["counters"])
check("модель позвана снова", len(CALLS) > n_calls)

print("=== нет модели — честный пропуск ===")
main._provider_ready = lambda m: False
j4 = run()
check("без ключа — пропуск с причиной", j4["counters"].get("skipped") == "no_model", j4["counters"])
main._provider_ready = lambda m: True

print("=== очередь: низкий приоритет ===")
main._JOBS.clear()
q1 = main._next_qseq()
main._JOBS[99] = {"id": 99, "qseq": main.PREPRESS_QBASE + 5, "status": "queued"}
q2 = main._next_qseq()
check("билеты низкого приоритета не поднимают обычный счётчик", q2 < main.PREPRESS_QBASE, (q1, q2))
main._queued_jobs = lambda: [{"id": 7, "tenant": "default", "project": 1, "qseq": 50}]
check("проверка уступает любой обычной задаче, даже своей",
      main._job_should_yield({"id": 8, "tenant": "default", "low": True}))
main._queued_jobs = lambda: [{"id": 7, "tenant": "other", "project": 1, "qseq": main.PREPRESS_QBASE + 1}]
check("обычная задача проверке не уступает",
      not main._job_should_yield({"id": 8, "tenant": "default"}))
import inspect
check("клиент задачу проверки поставить не может (create_job отказывает)",
      'req.kind == "prepress"' in inspect.getsource(main.create_job))

print("=== режим «чинить»: правка, второй взгляд, файл в кэш ===")
main.PREPRESS = "fix"
main._queued_jobs = lambda: []
main._prepress_path(pid).unlink()
STEP = [0]


class _Comp2:
    def create(self, **kw):
        CALLS.append(kw)
        if "compare two versions" in kw["messages"][0]["content"]:
            n_ = sum(1 for x in kw["messages"][1]["content"] if x.get("type") == "image_url")
            return _Resp(json.dumps({"places": [{"place": i + 1, "better": "2", "confidence": 0.9}
                                                for i in range(n_)]}))
        STEP[0] += 1
        # первый взгляд — дефект с действием, второй (после правки) — чисто
        if STEP[0] <= j1["counters"].get("pages", 1):
            return _Resp('{"ok": false, "defects": [{"place": 1, "code": "OVERFLOW", '
                         '"action": "tight", "confidence": 0.9, "what": "x"}]}')
        return _Resp('{"ok": true, "defects": []}')


class _Client2:
    def __init__(self):
        self.chat = type("C", (), {"completions": _Comp2()})()


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: _Client2()
import prepress as _PPM
_PPM.ab_swap = lambda k, r: False        # в тесте «2» — всегда «после»
j5 = {"id": 2, "kind": "prepress", "project": pid, "status": "running", "params": {"mode": "fix"},
      "counters": {}, "tenant": "default", "low": True, "total": 0, "done": 0}
main._JOB_TENANT.id = "default"
main._job_prepress(j5)
c5 = j5["counters"]
check("круги правок были", bool(c5.get("rounds")), c5)
check("круг взят, раз стало чище", any(r_["used"] for r_ in c5.get("rounds") or []), c5.get("rounds"))
meta = main._prepress_cache(pid)
inp = main._layout_inputs(project)
check("файл в кэше, отпечаток совпал", bool(meta) and meta.get("fp") == main._prepress_fp(inp), meta)
check("кэш помечен проверенным", (meta or {}).get("state") in ("checked", "partial"), meta)
check("pdf проверки лежит", (meta or {}).get("pdfPath") and meta["pdfPath"].exists())
if any(r_["used"] for r_ in c5.get("rounds") or []):
    check("исправлено считается местами", (c5.get("report") or {}).get("fixed", 0) >= 1, c5.get("report"))

print("=== короткий перевод только в файл: бесплатные проверки ===")
ANS = ["Total 12 kg paid"]


MEANING = ['{"same": true, "lost": ""}']


class _Comp3:
    def create(self, **kw):
        if kw["messages"][0]["content"].startswith("You check a"):
            return _Resp(MEANING[0])
        return _Resp(ANS[0])


class _Client3:
    def __init__(self):
        self.chat = type("C", (), {"completions": _Comp3()})()


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: _Client3()
cc, sp = {}, [0.0]
mdls = main._prepress_models()
got = main._prepress_shorten(project, "Итого 12 кг оплачено полностью", "Total of 12 kg has been paid in full",
                             mdls, cc, sp)
check("короче и числа те же — берём", got == "Total 12 kg paid", got)
ANS[0] = "Total 13 kg paid"
got = main._prepress_shorten(project, "Итого 12 кг оплачено полностью", "Total of 12 kg has been paid in full",
                             mdls, cc, sp)
check("число поменялось — не берём", got is None, got)
ANS[0] = "Total of 12 kg has been paid in full!"
got = main._prepress_shorten(project, "Итого 12 кг оплачено полностью", "Total of 12 kg has been paid in full",
                             mdls, cc, sp)
check("не короче — не берём", got is None, got)
ANS[0] = "Payment of 12 kg done"
got = main._prepress_shorten(project, "Оплата 12 кг не принята банком", "Payment of 12 kg was not accepted by the bank",
                             mdls, cc, sp)
check("отрицание потеряно — не берём", got is None, got)
ANS[0] = "Here is it: Total 12 kg paid"
got = main._prepress_shorten(project, "Итого 12 кг оплачено полностью", "Total of 12 kg has been paid in full",
                             mdls, cc, sp)
check("пояснение модели — не берём", got is None, got)
ANS[0] = "范围"
got = main._prepress_shorten(project, "Range", "范围(温度范围)", mdls, cc, sp)
check("иероглифы: короткое место тоже сокращается", got == "范围", got)

print("=== разложить перевод по строкам оригинала ===")
fm = work / "menu.pdf"
C.pdf_menu(fm)
blob_m = fm.read_bytes()
pm = main._parse_upload(fm.name, blob_m)
segs_m = main._new_segments([t for t, _ in pm["units"]])
for s_ in segs_m:
    s_["target"] = synth.pseudo(s_["source"], "en", 1.1, 0, True, sd)
    s_["status"] = "translated"
pid_m = 9302
project_m = {"id": pid_m, "title": "menu", "src": "RU", "tgt": "EN", "domain": "general",
             "tenant": "default", "fileName": fm.name, "importKind": "pdf", "segments": segs_m}
pairs_m = [[i, u + 1] for u, (_t, idxs) in enumerate(pm["units"]) for i in idxs]
main._store_source_docx(project_m, pm["docx"], fm.name, pairs_m, len(pm["texts"]), layout=pm.get("layout"))
main._store_original(pid_m, fm.name, blob_m)
inp_s = main._layout_inputs(project_m)
# Склеиваем две строки в один абзац, как это делал прежний разбор меню.
_bx = inp_s["layout"]["boxes"]
if "4" in _bx and "5" in _bx:
    _bx["4"][0]["slots"] = list(_bx["4"][0]["slots"]) + list(_bx["5"][0]["slots"])
    _bx.pop("5")
    inp_s["texts"].pop(5, None)
idx2 = next((int(k) for k, bl in (inp_s["layout"].get("boxes") or {}).items()
             if sum(len(b.get("slots") or []) for b in bl) == 2), None)
if idx2 is not None:
    cur_t = "alpha beta gamma delta"
    ANS[0] = '["gamma delta", "alpha beta"]'
    got = main._prepress_split(project_m, inp_s, idx2, cur_t, mdls, cc, sp)
    check("части — те же слова, порядок строк оригинала", got == ["gamma delta", "alpha beta"], got)
    ANS[0] = '["alpha beta", "gamma epsilon"]'
    got = main._prepress_split(project_m, inp_s, idx2, cur_t, mdls, cc, sp)
    check("модель поменяла слово — не берём", got is None, got)
    ANS[0] = '["alpha beta gamma delta"]'
    got = main._prepress_split(project_m, inp_s, idx2, cur_t, mdls, cc, sp)
    check("частей не столько, сколько строк — не берём", got is None, got)
    import copy as _cp, hashlib as _hl
    _tx = inp_s["texts"].get(idx2) or ""
    t_ = {"p%d" % idx2: {"parts": ["X1 first", "X2 second"],
                         "partsFor": _hl.sha1(_tx.encode("utf-8")).hexdigest()[:12]}}
    pdf_a, st_a = main.layout_pdf_mod.build(inp_s["work"], _cp.deepcopy(inp_s["layout"]), inp_s["texts"],
                                            extra=_cp.deepcopy(inp_s["extra"]), lang="EN",
                                            sources=inp_s["sources"], keep_overlay=True, tune=t_)
    check("сборка печатает части по строкам", st_a.get("splitParts") == 1, st_a.get("splitParts"))
    t_["p%d" % idx2]["partsFor"] = "другой текст"
    _p, st_b = main.layout_pdf_mod.build(inp_s["work"], _cp.deepcopy(inp_s["layout"]), inp_s["texts"],
                                         extra=_cp.deepcopy(inp_s["extra"]), lang="EN",
                                         sources=inp_s["sources"], keep_overlay=True, tune=t_)
    check("части к другому тексту не печатаются", not st_b.get("splitParts") and st_b.get("splitMismatch") == 1,
          (st_b.get("splitParts"), st_b.get("splitMismatch")))
else:
    print("  (нет абзаца из двух строк — проверка частей пропущена)")

print("=== перевести место, оставшееся на языке оригинала ===")
ANS[0] = "Total 12 kg"
got = main._prepress_translate_place(project, "Итого 12 кг", mdls, cc, sp)
check("перевод места с теми же числами — берём", got == "Total 12 kg", got)
ANS[0] = "Total 13 kg"
got = main._prepress_translate_place(project, "Итого 12 кг", mdls, cc, sp)
check("число другое — не берём", got is None, got)
MEANING[0] = '{"same": false, "lost": "only"}'
ANS[0] = "Total 12 kg paid"
got = main._prepress_shorten(project, "Итого 12 кг оплачено полностью", "Total of 12 kg has been paid in full",
                             mdls, cc, sp)
check("смысловая сверка сказала «потеряно» — не берём", got is None, got)
MEANING[0] = '{"same": true, "lost": ""}'
check("части — куски перевода подряд", main._pp_runs_of(["c d", "a b"], "a b c d"))
check("слова внутри части переставлены — нельзя", not main._pp_runs_of(["d c", "a b"], "a b c d"))
check("слово потеряно — нельзя", not main._pp_runs_of(["c", "a b"], "a b c d"))
check("в проекте перевод не тронут", all("Total 12 kg paid" != s_.get("target") for s_ in segs))
main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: _Client2()

print("=== выгрузка ждёт проверку ===")
g = main._prepress_gate(project, inp)
check("тот же перевод — выгрузка отдаёт проверенный файл", g and g.get("pdf") is not None, g)
check("отчёт для человека без моделей и денег",
      g and not any(k in json.dumps(g.get("public"), ensure_ascii=False) for k in ("claude", "gpt", "cost", "usd")),
      g and g.get("public"))
KICKS = []
main._prepress_kick = lambda p_, why, urgent=False: KICKS.append((p_, why, urgent)) or {"id": 77}
segs[1]["target"] = segs[1]["target"] + " More"
inp2 = main._layout_inputs(project)
try:
    main._prepress_gate(project, inp2)
    check("перевод поменялся — выгрузка ждёт новую проверку", False, "без PrepressPending")
except main.PrepressPending as e:
    check("перевод поменялся — выгрузка ждёт новую проверку", e.job_id == 77)
check("проверка поставлена срочной", KICKS and KICKS[-1][2] is True, KICKS)
main._prepress_cache_write(pid, main._prepress_fp(inp2), None, "failed", {"why": "error"})
g2 = main._prepress_gate(project, inp2)
check("сбой проверки — выгрузка не встаёт (сборка как раньше)", g2 is not None and g2.get("pdf") is None, g2)
main.PREPRESS = "observe"
check("в режиме наблюдения выгрузка не ждёт", main._prepress_gate(project, inp2) is None)
main.PREPRESS = "fix"
import inspect as _insp
src_exp = _insp.getsource(main.export_project)
check("экспорт отвечает pending, а не ошибкой", '"pending": True' in src_exp)
check("скачивание непроверенного — 409", "PrepressPending" in _insp.getsource(main.download_export))
src_st = _insp.getsource(main.prepress_status)
check("статус для клиента без моделей и денег",
      "model" not in src_st.split('"""')[2].replace("_prepress_models", "") and "cost" not in src_st)

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f_ in FAILS:
        print("  - " + f_)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
