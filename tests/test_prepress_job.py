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


def run():
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

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f_ in FAILS:
        print("  - " + f_)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
