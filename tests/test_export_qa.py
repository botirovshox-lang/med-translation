# -*- coding: utf-8 -*-
"""Приёмка выгрузки (Ч5) и правила Ч1–Ч3 разбора сверки 22.10.2026.

    python tests/test_export_qa.py

Синтетические PDF собирает reportlab: «оригинал» и «выгрузка» — те же листы
с нужной порчей, «слой» — то, что сборка напечатала поверх (прозрачный фон).
Платный взгляд проверяется НАСТОЯЩИМ сборщиком промпта с подменённым
клиентом модели (см. «Промпты проверяются настоящим кодом» в CLAUDE.md).
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
os.environ.setdefault("AUTO_RESEGMENT", "0")
sys.path.insert(0, "backend")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)))
    if not ok:
        FAILS.append(name)


try:
    import numpy  # noqa: F401
    import pypdfium2  # noqa: F401
    import cv2  # noqa: F401
    from reportlab.pdfgen import canvas
except ImportError as e:            # pragma: no cover
    print("ПРОПУЩЕН: нет модуля (%s) — приёмка без него не работает и тест её не проверяет" % e)
    sys.exit(0)

import export_qa as Q  # noqa: E402

W, H = 400.0, 300.0
LINE = "Hello world sample line"
TARGETS = ["Привет мир образец строки"]


def pdf(draw) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def orig_page(c):
    c.setFont("Helvetica", 14)
    c.drawString(40, 200, LINE)           # абзац 0 — переводится
    c.drawString(40, 150, "Second paragraph here")   # абзац 1 — чужой
    c.setFillColorRGB(0.1, 0.4, 0.8)
    c.rect(250, 30, 100, 80, stroke=0, fill=1)      # рисунок


def erase(c, y):
    c.setFillColorRGB(1, 1, 1)
    c.rect(36, y - 5, 250, 20, stroke=0, fill=1)


LAYOUT = {"boxes": {"0": [{"page": 0, "x0": 40, "x1": 230, "top": 215, "bottom": 198, "size": 14,
                           "slots": [[40, 200, 230, 14]]}],
                    "1": [{"page": 0, "x0": 40, "x1": 200, "top": 165, "bottom": 148, "size": 14,
                           "slots": [[40, 150, 200, 14]]}]},
          "pages": [[0, 0, W, H]]}
TEXTS = {0: TARGETS[0], 1: "Второй абзац тут"}
SOURCES = {0: LINE, 1: "Second paragraph here"}
LANG = Q.Lang([LINE, "Second paragraph here"], TARGETS + ["Второй абзац тут"])


def good_print(c):
    orig_page(c)
    erase(c, 200)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 14)
    c.drawString(40, 200, "Privet mir obrazets")
    erase(c, 150)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(40, 150, "Vtoroi abzac tut x")


def overlay_good(c):
    erase(c, 200)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 14)
    c.drawString(40, 200, "Privet mir obrazets")
    erase(c, 150)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(40, 150, "Vtoroi abzac tut x")


def run(out_draw, ov_draw=None, **kw):
    o = pdf(orig_page)
    r = pdf(out_draw)
    ov = pdf(ov_draw) if ov_draw else None
    return Q.inspect_pdf(o, r, LAYOUT, kw.get("texts", TEXTS), kw.get("extra"), LANG,
                         overlay=ov, overlay_order=[0] if ov else None, sources=SOURCES,
                         time_budget=60)


print("=== 1. Чистая выгрузка — находок нет ===")
rep = run(good_print, overlay_good)
check("ok и ни одной находки тяжести ≥2", rep["ok"] is True
      and not [i for i in rep["issues"] if Q.SEVERITY.get(i["code"], 1) >= 2], rep["issues"])
check("проверено 1 из 1", rep["checked"] == 1 and rep["pages"] == 1)

print("=== 2. Ничего не напечатано — оригинал остался ===")
rep = run(orig_page)
codes = [i["code"] for i in rep["issues"]]
check("строка исходного языка — UNTRANSLATED", "UNTRANSLATED" in codes, codes)
check("без слоя «молча не напечатано» — SILENT", "SILENT" in codes, codes)
check("находка несёт текст строки", any("Hello" in (i.get("text") or "") for i in rep["issues"]), rep["issues"])

print("=== 3. Стёрто и пусто — BLANK ===")


def erased_only(c):
    orig_page(c)
    erase(c, 200)
    erase(c, 150)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 14)
    c.drawString(40, 150, "Vtoroi abzac tut x")


def ov_erased(c):
    erase(c, 200)
    erase(c, 150)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 14)
    c.drawString(40, 150, "Vtoroi abzac tut x")


rep = run(erased_only, ov_erased)
check("стёртое место без перевода — BLANK", any(i["code"] == "BLANK" and i.get("key") == "p0"
                                               for i in rep["issues"]), rep["issues"])

print("=== 4. Печать на рисунке — SPILL ===")


def on_figure(c):
    good_print(c)
    c.setFillColorRGB(1, 1, 1)
    c.rect(260, 60, 60, 20, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(262, 64, "xx")


def ov_on_figure(c):
    overlay_good(c)
    c.setFillColorRGB(1, 1, 1)
    c.rect(260, 60, 60, 20, stroke=0, fill=1)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(262, 64, "xx")


rep = run(on_figure, ov_on_figure)
check("закраска на рисунке вне своего места — SPILL", any(i["code"] == "SPILL" for i in rep["issues"]),
      rep["issues"])

print("=== 5. Чужой абзац накрыт печатью соседа — OVERPRINT ===")
rep = run(on_figure, ov_on_figure, texts={0: TARGETS[0], 1: ""})
# у абзаца 1 перевода нет (не печатается), но выгрузка его стёрла — это
# не «не переведено», а налезшая печать.
check("стёртый абзац без своего перевода — OVERPRINT", any(i["code"] == "OVERPRINT" for i in rep["issues"]),
      rep["issues"])

print("=== 6. Кегль: перевод втрое мельче — SMALL ===")


def tiny(c):
    orig_page(c)
    erase(c, 200)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 4)
    c.drawString(40, 202, "Privet mir obrazets stroki")
    erase(c, 150)
    c.setFont("Helvetica", 14)
    c.drawString(40, 150, "Vtoroi abzac tut x")


def ov_tiny(c):
    erase(c, 200)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 4)
    c.drawString(40, 202, "Privet mir obrazets stroki")
    erase(c, 150)
    c.setFont("Helvetica", 14)
    c.drawString(40, 150, "Vtoroi abzac tut x")


rep = run(tiny, ov_tiny)
check("перевод кеглем 4 вместо 14 — SMALL", any(i["code"] == "SMALL" and i.get("key") == "p0"
                                               for i in rep["issues"]), rep["issues"])

print("=== 7. Двойная печать — DUPLICATE и правило Ч3 ===")
extra = [{"text": "Привет", "sid": 7, "boxes": [{"page": 0, "frac": 1, "x0": 0.1, "x1": 0.55,
                                                 "top": (H - 214) / H, "bottom": (H - 199) / H,
                                                 "lines": [[0.1, (H - 214) / H, 0.55, (H - 199) / H]]}]},
         {"text": "Далеко", "sid": 8, "boxes": [{"page": 0, "frac": 1, "x0": 0.7, "x1": 0.9,
                                                 "top": 0.05, "bottom": 0.1}]}]
items = Q.printed_items(LAYOUT, TEXTS, extra)
d = Q.duplicates(items, {0: (W, H)})
check("абзац слоя и надпись с картинки в одном месте — пара найдена",
      any(set(x["keys"]) == {"p0", "x0"} for x in d), d)
check("надпись в другом месте — не дубль", not any("x1" in x["keys"] for x in d), d)
check("рамки абзацев таблицы, перекрытые рамкой, но не строками, — не дубль",
      not Q.duplicates(Q.printed_items({"boxes": {
          "0": [{"page": 0, "x0": 10, "x1": 390, "top": 290, "bottom": 10, "size": 10,
                 "slots": [[10, 280, 390, 10]]}],
          "1": [{"page": 0, "x0": 20, "x1": 200, "top": 120, "bottom": 100, "size": 10,
                 "slots": [[20, 105, 200, 10]]}]}}, {0: "a", 1: "b"}, None), {0: (W, H)}))

print("=== 8. Язык слова ===")
check("латиница при RU→EN... исходник EN — слово исходника", LANG.is_source("Hello"))
check("слово перевода — не исходник", not LANG.is_source("Привет"))
check("число — не исходник", not LANG.is_source("2026"))
same = Q.Lang(["Мама мыла раму"], ["Онам ромни ювди"])
check("одна письменность: слово только из оригинала — исходник", same.is_source("мыла"))
check("одна письменность: слово, оставленное в переводе, — нет", not Q.Lang(["Мама Ташкент"], ["Ташкент"]).is_source("Ташкент"))

print("=== 9. Платный взгляд: промпт и разбор ответа ===")
pt = Q.vision_prompt("RU", "EN", [{"n": 1, "code": "UNTRANSLATED"}, {"n": 2, "code": "SPILL"}])
check("промпт называет отметки и коды", "1: UNTRANSLATED" in pt and "2: SPILL" in pt and "FRAGMENT" in pt)
check("промпт требует только JSON", "ONLY JSON" in pt)
got = Q.vision_parse('шум {"marks":[{"n":1,"real":true,"code":"UNTRANSLATED"},{"n":2,"real":false},'
                     '{"n":9,"real":true}],"extra":[{"code":"SIZE","box":[0.1,0.2,0.3,2],"what":"x"},'
                     '{"code":"НЕЧТО","box":[0,0,1,1]}]} хвост', [{"n": 1}, {"n": 2}])
check("подтверждённые и снятые — по номерам отметок", got["confirmed"] == [1] and got["dismissed"] == [2], got)
check("чужой номер отметки отброшен", 9 not in got["confirmed"])
check("неизвестный код отброшен, рамка прижата к 0..1",
      len(got["extra"]) == 1 and got["extra"][0]["box"][3] == 1.0, got["extra"])
check("битый ответ — пусто, без исключения", Q.vision_parse("не json", [])["extra"] == [])
o, r = pdf(orig_page), pdf(orig_page)
vp = Q.vision_pair(o, r, 0, [{"code": "UNTRANSLATED", "page": 0, "box": [0.1, 0.2, 0.5, 0.3]}])
check("пара для модели — JPEG и отметка №1", vp is not None and vp[0][:2] == b"\xff\xd8" and vp[1][0]["n"] == 1)
check("листы для модели — по весу находок",
      Q.vision_pages({"issues": [{"code": "SMALL", "page": 3}, {"code": "UNTRANSLATED", "page": 1, "verify": True}]})[0] == 1)

print("=== 10. Ч2: свой дефис кода не место переноса ===")
import layout_pdf  # noqa: E402
for w, ok in (("COVID-19-га", False), ("SARS-CoV-2", False), ("IL-6", False), ("ГПП-1", False)):
    check("«%s» не рвётся по дефису" % w,
          not any(layout_pdf._hyphen_cut_ok(w, k) for k, ch in enumerate(w) if ch == "-") == (not ok))
w = "почечно-сердечно-сосудистых"
check("составное слово рвётся по своим дефисам",
      [k for k, ch in enumerate(w) if ch == "-" and layout_pdf._hyphen_cut_ok(w, k)] == [7, 16])
sp = layout_pdf._hyph_split("COVID-19-га", None, 10 ** 6, len)
check("_hyph_split не режет «COVID-19-га»", sp is None, sp)

print("=== 11. Ч1: строки слоя — обрывки видимых строк ===")
import textcount  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


def scan_pdf():
    im = Image.new("RGB", (800, 600), (250, 248, 240))
    dr = ImageDraw.Draw(im)
    for k in range(8):
        y = 60 + k * 60
        x = 80
        while x < 700:                      # «слова» строки — пятна с пробелами
            dr.rectangle([x, y, x + 40, y + 24], fill=(30, 30, 30))
            x += 52
    buf = io.BytesIO()
    im.save(buf, "PNG")
    from reportlab.lib.utils import ImageReader
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=(400, 300))
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 0, 0, 400, 300)
    c.showPage()
    c.save()
    return b.getvalue()


content = scan_pdf()


def geom(x1s):
    lines = []
    for k, x1 in enumerate(x1s):
        y_img = 60 + k * 60 + 24                    # низ строки в точках картинки
        base = 300 - y_img / 2.0                     # картинка 800×600 → лист 400×300
        lines.append([40.0, base + 1.5, 12.0, x1])
    return [{"box": [0, 0, 400, 300], "lines": lines, "figs": [[0, 0, 400, 300]]}]


check("слой покрывает свои строки — страница остаётся текстом",
      textcount.layer_fragment_pages(content, geom([352.0] * 8)) == set())
check("строки слоя — обрывки (10% строки) — страница картинкой",
      textcount.layer_fragment_pages(content, geom([70.0] * 8)) == {0})
dig = geom([70.0] * 8)
dig[0]["figs"] = [[0, 0, 100, 100]]
check("цифровая страница (нет картинки во весь лист) не рисуется и не судится",
      textcount.layer_fragment_pages(content, dig) == set())
import pdftext  # noqa: E402
res = pdftext.clean([["строка один текст", "строка два текст"]], force_images={0})
check("clean: принудительная страница уходит картинкой", res["imagePages"] == [0]
      and res["report"].get("layerFragments") == 1, res["report"])

print("=== 11б. Ч1 сквозь разбор: скан с невидимым слоем-обрывками ===")


def scan_with_layer(frag: bool) -> bytes:
    im = Image.new("RGB", (800, 600), (250, 248, 240))
    dr = ImageDraw.Draw(im)
    for k in range(8):
        y = 60 + k * 60
        x = 80
        while x < 700:
            dr.rectangle([x, y, x + 40, y + 24], fill=(30, 30, 30))
            x += 52
    buf = io.BytesIO()
    im.save(buf, "PNG")
    from reportlab.lib.utils import ImageReader
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=(400, 300))
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 0, 0, 400, 300)
    for k in range(8):
        base = 300 - (60 + k * 60 + 24) / 2.0 + 1.5
        t = c.beginText(40, base)
        t.setTextRenderMode(3)                  # невидимый слой распознавания
        t.setFont("Helvetica", 12)
        t.textOut("ab" if frag else "word word word word word word word word")
        c.drawText(t)
    c.showPage()
    c.save()
    return b.getvalue()


import importers  # noqa: E402
for frag in (True, False):
    try:
        _d, kind, note, n_img, lay = importers.pdf_to_docx(scan_with_layer(frag))
    except Exception as e:
        check("разбор скана со слоем (%s)" % frag, False, e)
        continue
    if frag:
        check("слой-обрывки: страница ушла картинкой", n_img == 1, (n_img, note))
        check("слой-обрывки: раскладка листов сохранена, выгрузка — «тот же PDF»",
              bool(lay and lay.get("pages")) and "тот же PDF" in note, (lay, note))
    else:
        check("полный слой: страница осталась текстом", n_img == 0, (n_img, note))

print("=== 12. Сервер: Ч3, сводка форматов без вида, привязка отчёта к файлу ===")
import main  # noqa: E402
ext = [dict(e, boxes=[dict(b) for b in e["boxes"]]) for e in extra]
n = main._drop_duplicate_extras(LAYOUT, dict(TEXTS), ext)
check("Ч3: надпись поверх абзаца слоя снята, далёкая — нет",
      n == 1 and ext[0]["text"] == "" and ext[1]["text"] == "Далеко", (n, ext))
st = main._qa_structural({"written": 10, "untranslated": 2, "mismatch": 1})
check("Word: не записанное — MISSING, непереведённое — NOT_TRANSLATED",
      st["counts"] == {"MISSING": 1, "NOT_TRANSLATED": 2} and st["ok"] is False, st)
check("Word без потерь — ok", main._qa_structural({"written": 3})["ok"] is True)
with tempfile.TemporaryDirectory() as tdir:
    f = Path(tdir) / "x.docx"
    f.write_bytes(b"abc")
    main._export_qa_kick({"id": 99999, "segments": []}, "docx_layout", f, {"written": 1, "untranslated": 1})
    rep = main._qa_read(f)
    check("отчёт рядом с файлом и привязан к нему", rep and rep["state"] == "done"
          and rep["file"] == main._qa_file_sig(f), rep)
    f.write_bytes(b"abcdef")
    check("перевыгрузка делает прежний отчёт чужим", main._qa_read(f)["file"] != main._qa_file_sig(f))
p2s = {3: [30, 31]}
check("находка ведёт к строкам проекта: абзац и надпись",
      main._qa_segs({"keys": ["p3", "x0"]}, p2s, [{"sid": 7}]) == [7, 30, 31])

print("=== 13. Платный взгляд в main: настоящий промпт, подменённый клиент, служебная организация ===")
seen = {}


class _Msg:
    content = '{"marks":[{"n":1,"real":true,"code":"UNTRANSLATED"}],"extra":[{"code":"FONT","box":[0,0,0.5,0.5],"what":"bold lost"}]}'


class _Resp:
    choices = [type("C", (), {"message": _Msg()})()]
    usage = None


class _Comp:
    def create(self, **kw):
        seen["kw"] = kw
        seen["tenant"] = getattr(main._JOB_TENANT, "id", None)
        return _Resp()


class _Client:
    chat = type("Ch", (), {"completions": _Comp()})()


old = (main._llm_client, main._provider_ready, main._note_usage, main._resp_cost)
main._llm_client = lambda *a, **k: _Client()
main._provider_ready = lambda *a, **k: True
main._note_usage = lambda *a, **k: None
main._resp_cost = lambda *a, **k: 0.01
try:
    with tempfile.TemporaryDirectory() as tdir:
        f = Path(tdir) / "o.pdf"
        o = pdf(orig_page)
        f.write_bytes(o)
        main._qa_write(f, {"state": "done", "mode": "pixels", "file": main._qa_file_sig(f),
                           "issues": [{"code": "UNTRANSLATED", "page": 0, "box": [0.1, 0.2, 0.6, 0.3],
                                       "verify": True}]})
        vis = main._export_qa_vision(1, "pdf", f, o, "EN", "RU")
        sysmsg = seen["kw"]["messages"][0]["content"]
        check("промпт собран настоящим кодом: отметки и языки", "1: UNTRANSLATED" in sysmsg and "EN" in sysmsg)
        check("картинка ушла JPEG-ом", seen["kw"]["messages"][1]["content"][0]["image_url"]["url"]
              .startswith("data:image/jpeg;base64,"))
        check("расход — на служебную организацию `_qa`", seen["tenant"] == "_qa")
        check("после вызова организация потока возвращена", getattr(main._JOB_TENANT, "id", None) != "_qa")
        check("подтверждено 1, найдено сверх правил 1",
              vis["confirmed"] == 1 and any(i.get("vision") and i["code"] == "FONT" for i in vis["issues"]), vis)
        check("раздел `vision` записан в отчёт", (main._qa_read(f) or {}).get("vision", {}).get("calls") == 1)
finally:
    main._llm_client, main._provider_ready, main._note_usage, main._resp_cost = old

import price_rules  # noqa: E402
check("шаг расхода `exportqa` известен правилам цен", "exportqa" in price_rules.ONLY_ALL)

print("=== 14. Наружу: ни заметки модели, ни потолка, ни внутренних ключей не-суперу ===")
with tempfile.TemporaryDirectory() as tdir:
    f = Path(tdir) / "o.pdf"
    f.write_bytes(b"%PDF-1.4 x")
    main._qa_write(f, {"state": "done", "mode": "pixels", "file": main._qa_file_sig(f), "ok": False,
                       "issues": [{"code": "SPILL", "page": 0, "key": "p1", "near": "p2", "box": [0, 0, 1, 1]}],
                       "vision": {"state": "budget", "cost": 0.3, "calls": 4, "confirmed": 1,
                                  "issues": [{"code": "FONT", "page": 0, "what": "Claude says bold", "real": True,
                                              "vision": True}]}})
    old = (main.get_project, main._export_path, main._hide_cost)
    main.get_project = lambda pid: {"id": pid}
    main._export_path = lambda project, fmt: f
    try:
        main._hide_cost = lambda: True
        r = main.export_qa_report(1, "pdf")
        check("не-супер: нет `what`, нет суммы и числа вызовов", "what" not in json.dumps(r)
              and "cost" not in r["vision"] and "calls" not in r["vision"], r)
        check("не-супер: «budget» показан как «done»", r["vision"]["state"] == "done")
        check("внутренние ключи мест (pN/xK) наружу не уходят", "key" not in r["issues"][0]
              and "near" not in r["issues"][0])
        main._hide_cost = lambda: False
        r = main.export_qa_report(1, "pdf")
        check("суперу — сумма и заметка модели", r["vision"].get("cost") == 0.3
              and r["vision"]["issues"][0].get("what"))
        main._qa_write(f, {"state": "running", "file": main._qa_file_sig(f)})
        os.utime(f, (1, 1))
        main._qa_write(f, {"state": "running", "file": main._qa_file_sig(f)})
        check("«проверяем» без живого потока долго — честное «не проверено»",
              main.export_qa_report(1, "pdf")["state"] == "error")
    finally:
        main.get_project, main._export_path, main._hide_cost = old

print("=== 15. Ч2 не трогает «ТБ-диспансер» ===")
w = "ТБ-диспансер"
check("«ТБ-диспансер» рвётся по дефису, как раньше", layout_pdf._hyphen_cut_ok(w, 2))

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
