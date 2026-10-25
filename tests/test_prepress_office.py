# -*- coding: utf-8 -*-
"""Проверка перед выдачей у офисных и текстовых форматов (раздел Ы6).

Наш код — настоящий: разбор xlsx, выгрузка обратной записью, поиск мест
по тексту, круги правок, сравнение «до/после», перенос в проект, кэш
и гейт выгрузки по формату. Подменены только печать LibreOffice (её нет
на машине разработчика: лист рисует reportlab из ячеек файла) и клиент
модели. Плюс замок LibreOffice между процессами и круги до «нет улучшения».

    python tests/test_prepress_office.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["WARM_CACHES"] = "0"
os.environ["EXPORT_QA"] = "0"
os.environ["PREPRESS"] = "fix"
os.environ["PREPRESS_TENANTS"] = "*"
sys.path.insert(0, "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)[:400]))
    if not ok:
        FAILS.append(name)


try:
    import reportlab  # noqa: F401
    import pypdfium2  # noqa: F401
    import openpyxl
except ImportError as e:            # pragma: no cover
    print("ПРОПУЩЕН: нет модуля (%s)" % e)
    sys.exit(0)

import office_qa  # noqa: E402
import topdf  # noqa: E402


def pdf_of(lines_by_page):
    """PDF из строк: [[(x, y, text), ...] на лист] — шрифт с кириллицей."""
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = "Helvetica"
    for cand in ("frontend/vendor/fonts/sub/NotoSans-Regular.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(cand).exists():
            try:
                pdfmetrics.registerFont(TTFont("T", cand))
                font = "T"
                break
            except Exception:
                pass
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    for lines in lines_by_page:
        c.setFont(font, 11)
        for x, y, t in lines:
            c.drawString(x, y, t)
        c.showPage()
    c.save()
    return buf.getvalue()


print("=== office_qa: места по тексту, подозрения, текстовые форматы ===")
pages = office_qa.page_texts(pdf_of([[(60, 780, "Первая строка отчёта"), (60, 760, "Вторая строка")],
                                     [(60, 780, "Третья строка на втором листе")]]))
check("листы прочитаны", len(pages) == 2 and "Первая" in pages[0][2], [p[2][:40] for p in pages])
items, found = office_qa.locate(pages, {0: "Первая строка отчёта", 1: "Вторая строка",
                                        2: "Третья строка на втором листе", 3: "Пропавший текст"})
check("три места найдены, одно нет", found == {"p0": True, "p1": True, "p2": True, "p3": False}, found)
it2 = [x for x in items if x["key"] == "p2"]
check("место на втором листе", it2 and it2[0]["page"] == 1, it2)
b = it2[0]["boxes"][0]["lines"][0] if it2 else [0, 0, 0, 0]
check("рамка — доли листа, y вниз", 0.05 < b[0] < 0.2 and 0.0 < b[1] < 0.1 and b[2] > b[0], b)
import prepress as PP  # noqa: E402
pl = PP.page_places(items, 0, 595, 842)
check("prepress.page_places понимает места офиса", len(pl) == 2 and pl[0]["key"] == "p0", pl)
opages = office_qa.page_texts(pdf_of([[(60, 780, "Lost text of the original")]]))
ins = office_qa.inspect(opages, pages, {3: "Пропавший текст"}, {3: "Lost text of the original"},
                        items, found)
check("перевод не напечатан, а оригинал на листе есть — CLIPPED",
      any(i["code"] == "CLIPPED" and i["key"] == "p3" for i in ins["issues"]), ins)
many = office_qa.page_texts(pdf_of([[(60, 780, "x")]] * 5))
ins2 = office_qa.inspect(opages, many, {}, {}, [], {})
check("листов стало втрое больше — PAGES", any(i["code"] == "PAGES" for i in ins2["issues"]), ins2)
ti = office_qa.text_issues({0: "Hello world", 1: "Привет мир строка"},
                           {0: "Привет мир", 1: "Привет мир строка"}, set())
check("перевод = оригинал — UNTRANSLATED", ti == [{"key": "p1", "code": "UNTRANSLATED"}], ti)
check("имя или бренд одним словом — не «непереведённое» (то же правило, что у правки)",
      office_qa.text_issues({0: "Сбербанк"}, {0: "Сбербанк"}, set()) == [])
ti2 = office_qa.text_issues({1: "Привет мир строка"}, {1: "Привет мир строка"}, {"p1"})
check("законное «как в оригинале» молчит", ti2 == [], ti2)
ca = [{"start": 0.0, "end": 2.0, "text": "a"}, {"start": 2.0, "end": 3.0, "text": "b"}]
cb = [{"start": 0.0, "end": 2.0, "text": "x" * 120}, {"start": 2.5, "end": 3.0, "text": "b"}]
ti3 = office_qa.text_issues({}, {}, set(), cues_a=ca, cues_b=cb, read_cps=17)
check("время реплик разошлось — TIMING, быстро — FAST",
      {i["code"] for i in ti3} == {"TIMING", "FAST"}, ti3)

print("=== topdf: замок LibreOffice между процессами ===")
td = Path(tempfile.mkdtemp(prefix="lo_"))
fake = td / ("fake.cmd" if os.name == "nt" else "fake.sh")
log = td / "log.txt"
py = td / "fake.py"
py.write_text(
    "import sys, time, pathlib\n"
    "out = sys.argv[sys.argv.index('--outdir') + 1]\n"
    "src = pathlib.Path(sys.argv[-1])\n"
    "open(r'%s', 'a').write('start %%f\\n' %% time.time())\n"
    "time.sleep(0.6)\n"
    "(pathlib.Path(out) / (src.stem + '.pdf')).write_bytes(b'%%PDF-1.4 fake')\n"
    "open(r'%s', 'a').write('end %%f\\n' %% time.time())\n" % (log, log), encoding="utf-8")
if os.name == "nt":
    fake.write_text('@"%s" "%s" %%*\n' % (sys.executable, py), encoding="utf-8")
else:
    fake.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, py), encoding="utf-8")
    fake.chmod(0o755)
prof = td / "lo"
child = subprocess.Popen([sys.executable, "-c",
                          "import sys; sys.path.insert(0, 'backend'); import topdf; "
                          "topdf.SOFFICE = r'%s'; topdf.convert(b'x', __import__('pathlib').Path(r'%s'), ext='.xlsx')"
                          % (fake, prof)])
time.sleep(0.15)
topdf.SOFFICE = str(fake)
res = []
th = threading.Thread(target=lambda: res.append(topdf.convert(b"y", prof, ext=".pptx")))
th.start()
res.append(topdf.convert(b"z", prof, ext=".docx"))
th.join()
child.wait(timeout=60)
ev = [ln.split() for ln in log.read_text().splitlines()]
spans = []
for kind, t in ev:
    if kind == "start":
        spans.append([float(t), None])
    else:
        spans[[i for i, s_ in enumerate(spans) if s_[1] is None][0]][1] = float(t)
spans.sort()
over = any(spans[i + 1][0] < spans[i][1] for i in range(len(spans) - 1))
check("три конвертации (процесс + два потока) — строго по очереди", len(spans) == 3 and not over, spans)
check("фильтр печати по формату", topdf.FILTERS[".xlsx"].startswith("pdf:calc")
      and topdf.FILTERS[".pptx"].startswith("pdf:impress"))
try:
    topdf.convert(b"x", prof, ext="../x")
    check("чужое расширение — отказ", False)
except topdf.Failed:
    check("чужое расширение — отказ", True)

print("=== xlsx-проект: задача проверки, круг, перенос в проект, гейт ===")
import main  # noqa: E402
work = Path(tempfile.mkdtemp(prefix="ppo_"))
main.SOURCE_DIR = work / "src"
main.SOURCE_DIR.mkdir()
main.EXPORT_DIR = work / "exp"
main.save_state = lambda *a, **k: None
main.topdf_mod.available = lambda: True

wb = openpyxl.Workbook()
ws = wb.active
ws["A1"] = "Отчёт о проверке качества"
ws["A2"] = "Срок поставки истекает завтра"
ws["A3"] = "Подпись ответственного лица"
buf = io.BytesIO()
wb.save(buf)
blob = buf.getvalue()
parsed = main._parse_upload("report.xlsx", blob)
units = parsed["units"]
segs = main._new_segments([t for t, _ in units])
TR = {"Отчёт о проверке качества": "Quality inspection report",
      "Срок поставки истекает завтра": "Срок поставки истекает завтра",       # модель отдала оригинал
      "Подпись ответственного лица": "Signature of the responsible person"}
for s_ in segs:
    s_["target"] = TR.get(s_["source"], s_["source"])
    s_["status"] = "translated"
    s_["provider"] = "gpt-5.6-terra"
    s_["mtDone"] = True
pid = 9401
project = {"id": pid, "title": "report", "src": "RU", "tgt": "EN", "domain": "general",
           "tenant": "default", "fileName": "report.xlsx", "importKind": "xlsx", "segments": segs}
paras = [t for t, _f in parsed["texts"]]
pairs = [[i, u + 1] for u, (_t, idxs) in enumerate(units) for i in idxs]
main._store_source_docx(project, parsed["docx"], "report.xlsx", pairs, len(paras))
main._store_original(pid, "report.xlsx", blob)
main._project_by_id = lambda x: project if int(x) == pid else None
main.STATE.setdefault("projects", []).append(project)

RENDERS = []


def fake_render(pid_, data, ext, cache=False):
    RENDERS.append((ext, cache))
    w = openpyxl.load_workbook(io.BytesIO(data))
    lines = [(60, 800 - 20 * i, str(c.value)) for i, c in enumerate(
        c for row in w.active.iter_rows() for c in row if c.value)]
    return pdf_of([lines])


main._office_render = fake_render
check("формат проверки — xlsx", main._doc_check_ext(project) == ".xlsx", main._doc_check_ext(project))
check("проект проверяемый (не только pdf/скан)", main._pp_checkable(project))
inp = main._office_prepress_inputs(project)
check("тексты по слотам", sorted(inp["texts"].values()) == sorted(TR.values()), inp["texts"])
check("оригинал напечатан с кэшем", ("office", None) and RENDERS[-1] == (".xlsx", True), RENDERS)

CALLS = []


class _U:
    prompt_tokens, completion_tokens = 1500, 100
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


LOOKS = [0]


class _Comp:
    def create(self, **kw):
        sysmsg = kw["messages"][0]["content"]
        CALLS.append(sysmsg[:60])
        if "compare two versions" in sysmsg:
            n_ = sum(1 for x in kw["messages"][1]["content"] if x.get("type") == "image_url")
            return _Resp(json.dumps({"places": [{"place": i + 1, "better": "2", "confidence": 0.9}
                                                for i in range(max(1, n_ - 1))]}))
        if sysmsg.startswith("Translate the text"):
            return _Resp("Delivery deadline expires tomorrow")
        if sysmsg.startswith("You check a"):
            return _Resp('{"same": true, "lost": ""}')
        assert "office program" in sysmsg, "в вопросе нет пометки офисного документа"
        LOOKS[0] += 1
        content = kw["messages"][1]["content"]
        assert any(x.get("type") == "image_url" for x in content), "нет картинок"
        if LOOKS[0] == 1:
            pl = [p for p in sysmsg.split("Places: ")[-1].split("; ") if "Срок" in p]
            n = int(pl[0].split(":")[0]) if pl else 2
            return _Resp(json.dumps({"ok": False, "defects": [
                {"place": n, "code": "UNTRANSLATED", "action": "translate", "confidence": 0.9, "what": "ru"}]}))
        return _Resp('{"ok": true, "defects": []}')


class _Client:
    def __init__(self):
        self.chat = type("C", (), {"completions": _Comp()})()


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: _Client()
main._provider_ready = lambda m: True
import prepress as _PPM  # noqa: E402
_PPM.ab_swap = lambda k, r: False

main._JOBS.clear()
_enq = main._job_enqueue
QUEUED = []
# Постановку подменяем записью: настоящая очередь сразу отдала бы задачу
# исполнителю этого процесса, и он забрал бы ответы модели у теста.
main._job_enqueue = lambda pid_, kind, ids, params, low=False: QUEUED.append((pid_, kind, low)) or {
    "id": 77, "low": low, "kind": kind}
job = main._prepress_kick(pid, "run")
check("после полного прогона проверка ставится и у xlsx", job is not None and QUEUED == [(pid, "prepress", True)],
      QUEUED)
main._JOBS.clear()
j = {"id": 3, "kind": "prepress", "project": pid, "status": "running", "params": {"mode": "fix"},
     "counters": {}, "tenant": "default", "low": True, "total": 0, "done": 0}
main._JOB_TENANT.id = "default"
main._job_prepress(j)
c = j["counters"]
check("модель смотрела лист с пометкой офиса", LOOKS[0] >= 1, (c, CALLS))
check("круг взят", any(r_["used"] for r_ in c.get("rounds") or []), c)
seg2 = [s_ for s_ in segs if s_["source"].startswith("Срок")][0]
check("перевод места перенесён в проект", seg2["target"] == "Delivery deadline expires tomorrow"
      and (seg2.get("printFit") or {}).get("kind") == "translate", seg2)
meta = main._prepress_cache(pid, ".xlsx")
check("кэш по формату", bool(meta) and meta.get("state") in ("checked", "partial"), meta)
check("старый кэш PDF не тронут", not main._prepress_cache_paths(pid)[1].exists())
inp2 = main._office_prepress_inputs(project, with_work=False)
check("отпечаток кэша — нынешний вход (после переноса)", meta and meta.get("fp") == main._prepress_fp(inp2),
      (meta or {}).get("fp"))
fb = meta["pdfPath"].read_bytes() if meta else b""
cells = [cl.value for row in openpyxl.load_workbook(io.BytesIO(fb)).active.iter_rows() for cl in row if cl.value]
check("в кэше — сам xlsx с исправленной ячейкой", "Delivery deadline expires tomorrow" in cells, cells)
g = main._office_gate(project)
check("гейт выгрузки отдаёт проверенный файл", g is not None and g.get("file") == fb, g and list(g))
st = main.prepress_status.__wrapped__(pid) if hasattr(main.prepress_status, "__wrapped__") else None
main.get_project = lambda x: project
st = main.prepress_status(pid)
check("экран «Скачать» видит проверку xlsx", st.get("state") == "ready", st)
check("в состоянии нет имён моделей и денег", "model" not in json.dumps(st) and "cost" not in json.dumps(st), st)
mem = json.loads(main._prepress_path(pid, ".xlsx").read_text(encoding="utf-8"))
check("расход жизни файла записан", float(mem.get("spentLife") or 0) > 0, mem.get("spentLife"))

print("=== выгрузка ждёт проверку, если вход новый ===")
seg2["target"] = "Delivery deadline is tomorrow"
seg2.pop("printFit", None)
main._JOBS.clear()
try:
    main._office_gate(project)
    check("новый вход — PrepressPending", False)
except main.PrepressPending:
    check("новый вход — PrepressPending", True)

print("=== потолок жизни файла ===")
mem["spentLife"] = 999.0
main._prepress_path(pid, ".xlsx").write_text(json.dumps(mem), encoding="utf-8")
j2 = {"id": 4, "kind": "prepress", "project": pid, "status": "running", "params": {"mode": "fix"},
      "counters": {}, "tenant": "default", "low": True, "total": 0, "done": 0}
main._job_prepress(j2)
check("потолок жизни исчерпан — модель не зовём", j2["counters"].get("skipped") == "lifecap", j2["counters"])

print("=== круги: потолок по срочности и остановка по терпению ===")
import inspect  # noqa: E402
src_fr = inspect.getsource(main._prepress_fix_rounds)
check("потолок кругов зависит от того, ждёт ли человек", "PREPRESS_ROUNDS_URGENT" in src_fr and 'job.get("low")' in src_fr)
check("остановка по терпению", "PREPRESS_PATIENCE" in src_fr and "idle" in src_fr)
check("проверка ставится и после задач, переписывающих текст",
      set(main._PREPRESS_AFTER_KINDS) >= {"translate", "full", "review", "repair", "apply_terms"})

print("=== Word: подмена текста кандидата и гейт внутри «как в оригинале» ===")
from docx import Document  # noqa: E402
d = Document()
d.add_paragraph("Первый абзац договора поставки")
d.add_paragraph("Второй абзац о сроках оплаты")
bd = io.BytesIO()
d.save(bd)
dblob = bd.getvalue()
dparsed = main._parse_upload("contract.docx", dblob)
dsegs = main._new_segments([t for t, _ in dparsed["units"]])
DTR = {"Первый абзац договора поставки": "First paragraph of the supply contract",
       "Второй абзац о сроках оплаты": "Second paragraph on payment terms"}
for s_ in dsegs:
    s_["target"], s_["status"], s_["provider"], s_["mtDone"] = DTR[s_["source"]], "translated", "m", True
dpid = 9402
dproj = {"id": dpid, "title": "contract", "src": "RU", "tgt": "EN", "domain": "general", "tenant": "default",
         "fileName": "contract.docx", "importKind": "docx", "segments": dsegs}
dpairs = [[i, u + 1] for u, (_t, idxs) in enumerate(dparsed["units"]) for i in idxs]
main._store_source_docx(dproj, dparsed["docx"], "contract.docx", dpairs,
                        len([t for t, _f in dparsed["texts"]]))
main._project_by_id = lambda x: {pid: project, dpid: dproj}.get(int(x))
check("формат проверки — docx", main._doc_check_ext(dproj) == ".docx", main._doc_check_ext(dproj))
dinp = main._office_prepress_inputs(dproj, with_work=False)
k0 = sorted(dinp["texts"])[0]
sid0 = dict(main._para_groups(dinp["data"]))[k0][0]
fb2, _st2 = main._office_build_file(dproj, ".docx", {int(sid0): "Short first paragraph"})
paras2 = [p.text for p in Document(io.BytesIO(fb2)).paragraphs if p.text]
check("кандидат: подменённый текст лёг в файл, проект не тронут",
      "Short first paragraph" in paras2 and dsegs[0]["target"] == DTR[dsegs[0]["source"]], paras2)
main._JOBS.clear()
try:
    main._export_docx_layout(dproj, work / "x.docx")
    check("выгрузка Word ждёт проверку (гейт внутри «как в оригинале»)", False)
except main.PrepressPending:
    check("выгрузка Word ждёт проверку (гейт внутри «как в оригинале»)", True)
main._PP_BUILDING.v = True
try:
    st_b = main._export_docx_layout(dproj, work / "y.docx")
    check("сборка-кандидат гейт не спрашивает", (work / "y.docx").exists() and "prepress" not in st_b, st_b)
finally:
    main._PP_BUILDING.v = False

print("=== txt: место на языке оригинала переводится фоном ===")
tblob = "Первая строка файла\nВторая строка файла\n".encode("utf-8")
tparsed = main._parse_upload("notes.txt", tblob)
tsegs = main._new_segments([t for t, _ in tparsed["units"]])
for s_ in tsegs:
    s_["status"], s_["provider"], s_["mtDone"] = "translated", "m", True
tsegs[0]["target"] = "First line of the file"
tsegs[1]["target"] = tsegs[1]["source"]            # модель отдала оригинал
tpid = 9403
tproj = {"id": tpid, "title": "notes", "src": "RU", "tgt": "EN", "domain": "general", "tenant": "default",
         "fileName": "notes.txt", "importKind": "txt", "segments": tsegs}
tpairs = [[i, u + 1] for u, (_t, idxs) in enumerate(tparsed["units"]) for i in idxs]
main._store_source_docx(tproj, tparsed["docx"], "notes.txt", tpairs, len([t for t, _f in tparsed["texts"]]))
main._store_original(tpid, "notes.txt", tblob)
main._project_by_id = lambda x: {pid: project, dpid: dproj, tpid: tproj}.get(int(x))
check("txt — текстовый класс проверки", main._doc_check_ext(tproj) == ".txt"
      and (main._office_prepress_inputs(tproj, with_work=False) or {}).get("textfmt") == ".txt")


class _CompT:
    def create(self, **kw):
        if kw["messages"][0]["content"].startswith("You check a"):
            return _Resp('{"same": true, "lost": ""}')      # сверка смысла перевода места
        return _Resp("Second line of the file")


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: type(
    "C", (), {"chat": type("X", (), {"completions": _CompT()})()})()
jt = {"id": 5, "kind": "prepress", "project": tpid, "status": "running", "params": {"mode": "fix"},
      "counters": {}, "tenant": "default", "low": True, "total": 0, "done": 0}
main._job_prepress(jt)
check("непереведённая строка переведена и перенесена в проект",
      tsegs[1]["target"] == "Second line of the file" and (tsegs[1].get("printFit") or {}).get("kind") == "translate",
      (tsegs[1], jt["counters"]))
check("строка, переведённая верно, не тронута", tsegs[0]["target"] == "First line of the file")
tm = main._prepress_cache(tpid, ".txt")
check("кэш текстовой проверки — «проверено»", bool(tm) and tm.get("state") == "checked", tm)
out_t = work / "out.txt"
st_t = main._export_original(tproj, out_t, work / "out.txt.tmp")
check("сверка при выгрузке txt — чисто после правки", not st_t.get("textQa"), st_t)

print("=== правки по критику: отпечаток, пометка, деньги, имена ===")
fp_a = main._prepress_fp(main._office_prepress_inputs(dproj, with_work=False))
dproj["segments"].append({"id": 99, "source": "Надпись на рисунке", "target": "Figure label",
                          "status": "translated", "origin": {"part": "word/media/image1.png", "block": 0}})
fp_b = main._prepress_fp(main._office_prepress_inputs(dproj, with_work=False))
dproj["segments"][-1]["target"] = "Figure caption"
fp_c = main._prepress_fp(main._office_prepress_inputs(dproj, with_work=False))
check("надпись картинки — часть отпечатка Word (старый файл не отдаётся как проверенный)",
      len({fp_a, fp_b, fp_c}) == 3, (fp_a, fp_b, fp_c))
dproj["segments"].pop()
check("версия кода офиса отдельна от PDF (правка печати офиса не протухает кэши PDF)",
      main._prepress_code_version(False) != main._prepress_code_version(True))
inp_d = main._office_prepress_inputs(dproj, with_work=False)
main._prepress_cache_write(dpid, main._prepress_fp(inp_d), None, "unchecked", {"why": "no_model"}, {}, fmt=".docx")
st_u = main._export_docx_layout(dproj, work / "u.docx")
check("файл без проверки помечен честно (пометка доходит до экрана)",
      (st_u.get("prepress") or {}).get("state") == "unchecked", st_u.get("prepress"))
import inspect as _insp  # noqa: E402
body_src = _insp.getsource(main._job_prepress_body)
check("расход жизни файла пишется при любом исходе (finally)",
      "finally:" in body_src and body_src.rfind("_life_save()") > body_src.rfind("finally:"))
for fn in (main._export_docx_layout, main._export_original, main._office_build_file, main._pp_build_office):
    check("сборка %s без рабочих потоков (подмена текстов — в потоке задачи)" % fn.__name__,
          "_run_parallel" not in _insp.getsource(fn))
tsegs[1]["target"] = tsegs[1]["source"] = "Сбербанк"
tsegs[1].pop("printFit", None)
main._prepress_cache_paths(tpid, ".txt")[1].unlink()
CALLS_T = []


class _CompN:
    def create(self, **kw):
        CALLS_T.append(1)
        return _Resp("Sberbank")


main._llm_client = lambda mdl, timeout=None, step=None, max_retries=None: type(
    "C", (), {"chat": type("X", (), {"completions": _CompN()})()})()
inp_t = main._office_prepress_inputs(tproj, with_work=False)
rep_t = main._pp_text_fix(tproj, inp_t, main._prepress_models(), {}, [0.0])
check("имя или бренд одним словом модель не переводит", not CALLS_T and not rep_t["shortened"], (CALLS_T, rep_t))

print("=== текстовый формат: сверка при выгрузке ===")
tq = {"textQa": {"UNTRANSLATED": 2}}
rep = main._qa_structural(tq)
check("сверка слотов попадает в отчёт приёмки", rep["counts"].get("UNTRANSLATED") == 2 and rep["ok"] is False, rep)

print()
if FAILS:
    print("ПРОВАЛЕНО: %d — %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
