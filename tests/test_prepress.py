# -*- coding: utf-8 -*-
"""Предпечатная проверка (раздел Ы2): отпечаток страницы, память взгляда
модели, база выученных правил, вопрос модели и разбор ответа, плитки.

    python tests/test_prepress.py
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
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


import prepress as P  # noqa: E402

print("=== отпечаток и память: четыре условия ===")
ver = {"layout": "x", "qa": "y", "model": "m", "prompt": P.PROMPT_VERSION}
k1 = P.page_keys(["Итого"], [(10, 20, 9.0, "Итого")], b"png1", ver)
td = Path(tempfile.mkdtemp(prefix="pp_"))
mem = P.PageMemory(td / "1.prepress.json")
check("новая страница — смотреть", mem.lookup(0, k1) == (None, "new"))
mem.store(0, k1, {"ok": True, "defects": []})
mem.save()
mem2 = P.PageMemory(td / "1.prepress.json")
rec, why = mem2.lookup(0, k1)
check("всё совпало — ответ из памяти", rec is not None and why == "same", why)
k_text = P.page_keys(["Итого!"], [(10, 20, 9.0, "Итого")], b"png1", ver)
check("перевод изменился — заново", mem2.lookup(0, k_text) == (None, "translation"))
k_lines = P.page_keys(["Итого"], [(10, 21, 9.0, "Итого")], b"png1", ver)
check("строка сдвинулась — заново", mem2.lookup(0, k_lines) == (None, "lines"))
k_img = P.page_keys(["Итого"], [(10, 20, 9.0, "Итого")], b"png2", ver)
check("картинка другая — заново", mem2.lookup(0, k_img) == (None, "image"))
k_ver = P.page_keys(["Итого"], [(10, 20, 9.0, "Итого")], b"png1", dict(ver, prompt="pp-other"))
check("другой вопрос модели — заново", mem2.lookup(0, k_ver) == (None, "versions"))

print("=== база выученных правил ===")
lr = P.LearnedRules(td / "rules.json")
sig = P.place_signature("OVERFLOW", {"kind": "slot", "lines": 1, "align": "right"})
check("новое правило не действует", lr.active(sig) is None)
lr.note(sig, "tight", True)
check("одно подтверждение — ещё кандидат", lr.active(sig) is None)
lr.note(sig, "tight", True)
check("два подтверждения — действует", lr.active(sig) == "tight")
lr.save()
check("сохраняется и читается", P.LearnedRules(td / "rules.json").active(sig) == "tight")
lr.note(sig, "tight", False)
check("провал — правило отозвано", lr.active(sig) is None and lr.rules[sig]["state"] == "revoked")
sig2 = P.place_signature("SMALL", {"kind": "slot"})
lr.note(sig2, "rm -rf", True)
check("действие не из списка не записывается", sig2 not in lr.rules)
f = P.place_features({"slots": [[1, 2, 3, 4]], "align": "left"}, "Итого к оплате", "Итого")
check("признаки места — без текста клиента", "Итого" not in json.dumps(f, ensure_ascii=False), f)

print("=== правило — из РАЗНЫХ документов ===")
lr3 = P.LearnedRules(td / "rules3.json")
sg = P.place_signature("OVERLAP", {"kind": "slot", "lines": 2})
lr3.note(sg, "cond", True, doc="a")
lr3.note(sg, "cond", True, doc="a")
check("два раза в одном файле — ещё кандидат", lr3.active(sg) is None)
lr3.note(sg, "cond", True, doc="b")
check("второй документ — действует", lr3.active(sg) == "cond")
lr3.note(sg, "cond", True, doc="c")
lr3.note(sg, "cond", False, doc="d")
check("один провал на три успеха — в силе", lr3.active(sg) == "cond")
lr3.note(sg, "cond", False, doc="e")
check("два провала — отозвано", lr3.active(sg) is None)

print("=== лестница действий ===")
V = {0: {"defects": [{"key": "p1", "code": "OVERFLOW", "action": "tight", "confidence": 0.9}]}}
r1 = P.plan_round(V, {}, {})
check("первый круг — действие модели", r1["applied"] == [("p1", "OVERFLOW", "tight")] and r1["tune"]["p1"] == {"tight": 1}, r1)
r2 = P.plan_round(V, r1["tune"], {"p1": {"tight"}})
check("не помогло — следующее по лестнице (уже)", r2["applied"][0][2] == "cond", r2)
r3 = P.plan_round(V, r2["tune"], {"p1": {"tight", "cond"}})
check("потом шире, и «теснее» снято", r3["applied"][0][2] == "wide" and "tight" not in r3["tune"]["p1"], r3)
r4 = P.plan_round(V, r3["tune"], {"p1": {"tight", "cond", "wide"}})
check("в конце — короче перевод", r4["short"] == {"p1"}, r4)
r5 = P.plan_round(V, r4["tune"], {"p1": {"tight", "cond", "wide", "shorter"}})
check("лестница кончилась — нечего пробовать", not r5["applied"], r5)
lr4 = P.LearnedRules(td / "rules4.json")
f4 = {"kind": "slot", "lines": 1}
s4 = P.place_signature("OVERFLOW", f4)
for d_ in ("a", "b"):
    lr4.note(s4, "cond", True, doc=d_)
r6 = P.plan_round(V, {}, {}, lr4, {"p1": f4})
check("выученное правило — раньше модели", r6["applied"][0][2] == "cond", r6)
check("в вопросе — чем печатаем (без ложного FONT)", "Noto Sans" in P.prompt("RU", "EN", []))

print("=== вопрос и разбор ответа ===")
places = [{"n": 1, "key": "p3", "label": "Итого"}, {"n": 2, "key": "x0", "label": "Подпись"}]
pr = P.prompt("RU", "EN", places)
check("в вопросе — закрытый список действий", "tight" in pr and "keep_rule" in pr and "OTHER" in pr)
ans = ('Вот: {"ok": false, "defects": [{"place": 1, "code": "OVERFLOW", "action": "tight"},'
       '{"place": 2, "code": "SIZE", "action": "format_disk"},'
       '{"place": 7, "code": "OTHER", "action": "shorter", "text": "Total", "what": "new kind"}]}')
got = P.parse(ans, places)
check("место → ключ", got["defects"][0]["key"] == "p3")
check("чужое действие → none", got["defects"][1]["action"] == "none")
check("несуществующее место — без ключа", got["defects"][2]["key"] is None)
check("короче — текст сохранён", got["defects"][2]["text"] == "Total")
check("битый ответ — не «всё хорошо»", P.parse("garbage", places)["ok"] is False)
check("пустой список дефектов — хорошо", P.parse('{"ok": true, "defects": []}', places)["ok"] is True)
g2 = P.parse('{"defects": [{"place": 1, "code": "OTHER", "what": "table bottom rule broken", "confidence": 0.5}]}', places)
check("«прочее» с понятным описанием — свой код", g2["defects"][0]["code"] == "RULE_CUT", g2)
g3 = P.parse('{"defects": [{"place": 1, "code": "SMALL", "confidence": 0.3}]}', places)
check("неуверенная находка (ниже порога) не делает страницу плохой", g3["ok"] is True, g3)

print("=== плитки: мелкий текст не теряется ===")
try:
    from reportlab.pdfgen import canvas

    def pdf(txt):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(595, 842))
        c.setFont("Helvetica", 6)
        c.drawString(50, 400, txt)
        c.showPage()
        c.save()
        return buf.getvalue()
    a, b = pdf("Original footnote"), pdf("Translated footnote")
    pl = [{"n": 1, "key": "p0", "box": [50 / 595, (842 - 406) / 842, 200 / 595, (842 - 398) / 842],
           "label": "x", "size": 6.0}]
    tiles = P.pair_images(a, b, 0, pl)
    from PIL import Image
    ims = [Image.open(io.BytesIO(t[0])) for t in tiles]
    check("несколько плиток при мелком тексте", len(tiles) >= 2, len(tiles))
    check("каждая пара не шире 1568 точек (не уменьшится у модели)",
          all(im.width <= 1568 for im in ims), [im.size for im in ims])
    check("место попало ровно в свою плитку", sum(1 for t in tiles if t[1]) >= 1)
    check("отпечаток картинки устойчив", P.page_raster(b, 0) == P.page_raster(b, 0))
except ImportError:
    print("  (нет reportlab — плитки пропущены)")

print()
if FAILS:
    print("ПРОВАЛЕНО: %d" % len(FAILS))
    for f_ in FAILS:
        print("  - " + f_)
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
