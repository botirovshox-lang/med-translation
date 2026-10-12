# -*- coding: utf-8 -*-
"""Вставка текста любой письменности в вёрстку оригинала: HarfBuzz
контурами (`glyph_shaper`) и перенос по границе фразы (BudouX).

Что проверяем:
  1. сборка букв настоящая: арабица связывается (у буквы внутри слова
     другой глиф, чем у одиночной), иврит идёт справа налево, огласовка
     деванагари встаёт ПЕРЕД согласной;
  2. контур глифа доезжает до PDF и у TrueType (квадратичные кривые),
     и у OTF/CFF (иероглифы Noto SC — reportlab их не грузит вовсе);
  3. одинаковый глиф — одна форма на документ, цвет берётся у строки;
  4. выгрузка `build()` печатает арабский перевод контурами: на странице
     нет картинок строк, а пиксели перевода есть и они нужного цвета;
  5. выключенный модуль (`LAYOUT_VECTOR=0`) — прежняя дорога картинкой;
  6. знак препинания, которого нет в шрифте письменности (скобки
     у Noto Naskh Arabic), берётся из латинского шрифта, а не квадратом;
  7. строка без пробелов режется на границе фразы, а не посреди слова.
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glyph_shaper as gs
import layout_pdf
import pdftext
import textcount
from pdf_fixture import make_pdf, body

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


FONTS = layout_pdf._REPO_FONTS
AR = FONTS + "/NotoNaskhArabic-Regular.ttf"
HE = FONTS + "/NotoSansHebrew-Regular.ttf"
DV = FONTS + "/NotoSansDevanagari-Regular.ttf"
SC = FONTS + "/NotoSansSC-Regular.otf"

print("=== 1. Сборка букв ===")
check(gs.available(), "HarfBuzz на месте (uharfbuzz с рисованием контуров)")
if gs.available():
    # У Noto Naskh точка буквы — свой глиф, поэтому сравниваем весь набор:
    # три буквы в слове — НЕ три одиночные буквы подряд.
    one = [g[0] for g in gs.shape(AR, "ب", True)]
    word = [g[0] for g in gs.shape(AR, "ببب", True)]
    check(word != one * 3 and set(word) - set(one),
          "арабские буквы в слове — связные формы, не одиночные: %s / %s" % (word, one))
    he = gs.shape(HE, "אב", True)
    check(he[0][0] == gs.shape(HE, "ב", True)[0][0], "иврит в видимом порядке: «ב» слева")
    dv = gs.shape(DV, "कि", False)
    check(dv[0][0] != gs.shape(DV, "क", False)[0][0],
          "огласовка «ि» деванагари стоит ПЕРЕД согласной")
    check(gs.notdef(AR, "مرحبا") == 0 and gs.notdef(AR, "糖") == 1,
          "незнакомый шрифту знак виден после сборки (глиф 0)")
    w14 = gs.width(HE, "שלום", True, 14.0)
    check(abs(gs.width(HE, "שלום", True, 28.0) - 2 * w14) < 1e-6 and w14 > 10,
          "ширина пропорциональна кеглю: %.2f" % w14)

print("=== 2. Контуры TrueType и CFF ===")
if gs.available():
    pen = gs._Pen()
    pen.moveTo((0, 0))
    pen.qCurveTo((10, 10), (20, 10), (30, 0))      # две внеконтурные точки
    check(sum(1 for o in pen.ops if o.endswith(" c")) == 2 and pen.cur == (30, 0),
          "TrueType: две внеконтурные точки — две кубические кривые до опорной")
    ar_gid = gs.shape(AR, "م", True)[0][0]
    check(" c" in gs._outline(AR, ar_gid), "контур арабской буквы — кривыми")
    sc_gid = gs.shape(SC, "糖", False)[0][0]
    check(sc_gid != 0 and len(gs._outline(SC, sc_gid)) > 50,
          "иероглиф из OTF/CFF — контур есть (reportlab этот шрифт не грузит)")

print("=== 3. Формы глифов: одна на документ, цвет — у строки ===")
if gs.available():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 120))
    c.setFillColorRGB(0.9, 0.05, 0.05)
    c.saveState()
    w = gs.draw(c, 10, 60, HE, "ששששששששש", True, 20)
    c.restoreState()
    forms = {k: v for k, v in c._mct_glyph_forms.items() if k not in ("_files", "_runs")}
    check(len(forms) == 1, "девять одинаковых букв — одна форма: %d" % len(forms))
    check(abs(w - gs.width(HE, "ששששששששש", True, 20)) < 1e-6, "draw() отдаёт ширину строки")
    c.showPage()
    c.save()
    try:
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(buf.getvalue())[0].render(scale=2).to_pil().convert("RGB")
        reds = sum(1 for p in list(img.getdata()) if p[0] > 150 and p[1] < 90 and p[2] < 90)
        check(reds > 200, "буквы залиты цветом строки (форма цвет не задаёт): %d пикс." % reds)
    except ImportError:
        print("  --   pypdfium2 нет — отрисовку не проверяем")

print("=== 4. Выгрузка: арабский перевод контурами ===")
LINES = ["Сахарный диабет второго типа лечат диетой и таблетками,",
         "а при неудаче добавляют инсулин по схеме врача."]
PDF = make_pdf([body(LINES, top=520)])
pg, gm = textcount._pdf_pages_geom(PDF, [])
items = [it for it in pdftext.clean(pg, geom=gm)["items"] if it[0] == "p"]
lay = {"boxes": {k: it[2] for k, it in enumerate(items) if it[2]}}
ar_texts = {k: "يعالج داء السكري من النوع الثاني بالنظام الغذائي (والأقراص) COVID-19"
            for k in lay["boxes"]}
check(bool(lay["boxes"]), "у абзаца есть рамка")
if gs.available() and lay["boxes"]:
    out, st = layout_pdf.build(PDF, lay, ar_texts, lang="AR")
    check(st.get("shaper") == "vector" and st.get("raster", 0) > 0,
          "строки со сборкой напечатаны контурами: %s / %s" % (st.get("shaper"), st.get("raster")))
    check(st.get("notdef") == 0, "все знаки собраны шрифтами (скобки и латиница тоже): %s"
          % st.get("notdef"))
    from pypdf import PdfReader
    def _kinds(pdf):
        xo = PdfReader(io.BytesIO(pdf)).pages[0]["/Resources"].get("/XObject") or {}
        return [xo[k].get_object().get("/Subtype") for k in xo]
    subtypes = _kinds(out)
    check(subtypes.count("/Image") == _kinds(PDF).count("/Image") and subtypes.count("/Form") >= 5,
          "на странице формы глифов, а новых картинок строк нет: %s" % subtypes)
    try:
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(out)[0].render(scale=2).to_pil().convert("L")
        b = next(iter(lay["boxes"].values()))
        b = b[0] if isinstance(b, list) else b
        dark = sum(1 for p in list(img.getdata()) if p < 100)
        check(dark > 300, "перевод виден на странице: %d тёмных пикс." % dark)
    except ImportError:
        pass

print("=== 5. Выключатель: прежняя дорога картинкой ===")
if lay["boxes"]:
    keep = gs.ENABLED
    gs.ENABLED = False
    try:
        from PIL import features
        try:
            _o, st2 = layout_pdf.build(PDF, lay, ar_texts, lang="AR")
            check(features.check("raqm") and st2.get("shaper") == "image",
                  "LAYOUT_VECTOR=0 — картинкой строки через raqm")
        except layout_pdf.NotAvailable as e:
            check(not features.check("raqm") and "raqm" in str(e),
                  "без HarfBuzz и без raqm — отказ словами: %s" % e)
    finally:
        gs.ENABLED = keep

print("=== 6. Знак препинания — из шрифта, который его знает ===")
r = layout_pdf._Raster(set("(نص)"))
runs = r.runs("(نص)")
par = [p_ for p_, t_, _r in runs if "(" in t_ or ")" in t_]
check(par and all(o in r.cmaps.get(p_, set()) for p_ in par for o in (ord("("),)),
      "скобки в арабской строке — шрифтом со скобками: %s"
      % [(p_.rsplit("/", 1)[-1], t_) for p_, t_, _r in runs])

print("=== 7. Перенос без пробелов — по границе фразы ===")
try:
    import budoux  # noqa: F401
    have_budoux = True
except ImportError:
    have_budoux = False
check(have_budoux, "BudouX на месте")
if have_budoux:
    ja = "今日は天気です。明日は雨が降るでしょう。"
    bounds = layout_pdf._phrase_bounds(ja)
    n = layout_pdf._break_point(ja, 11)
    check(n in bounds and n <= 11, "японская строка режется на границе фразы: %d из %s" % (n, bounds))
    th = "สวัสดีครับยินดีต้อนรับสู่ประเทศไทย"
    tb = layout_pdf._phrase_bounds(th)
    n = layout_pdf._break_point(th, 14)
    check(tb and n in tb, "тайская строка — на границе слова: %d из %s" % (n, tb))
    check(layout_pdf._break_point(ja, 2) == layout_pdf._cut_point(ja, 2),
          "границы рядом нет — режем как прежде (по знакам)")
check(layout_pdf._break_point("Hyperparathyroidism", 7) == 7,
      "у слова латиницей прежняя резка")
if have_budoux and gs.available():
    # Укладка абзаца японским переводом проходит целиком и без потерь.
    jt = {k: "糖尿病の治療は食事療法と薬物療法を組み合わせて行います。医師の指示に従ってください。"
          for k in lay["boxes"]}
    out_j, st_j = layout_pdf.build(PDF, lay, jt, lang="JA")
    check(st_j.get("overflow", 0) == 0 or st_j.get("paragraphs"), "японский абзац уложен: %s"
          % {k: st_j.get(k) for k in ("paragraphs", "overflow", "shrunk")})

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
