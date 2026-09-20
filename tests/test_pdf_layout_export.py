# -*- coding: utf-8 -*-
"""Выгрузка PDF «как в оригинале»: перевод НА МЕСТЕ оригинала.

Боевой случай (Лазебный, «Пчелиная аптека», RU→UZ-CYRL): книга снята
со сканера, каждая страница — фотография. Импорт брал из неё только
текстовый слой и собирал НОВЫЙ документ Word, а выгрузка печатала этот
документ в PDF — ровный поток абзацев без единого признака вёрстки
оригинала. Клиенту обещан перевод 1в1.

Что проверяем:
  1. место абзаца на странице доезжает от разбора до карты (`layout`)
     и считается по СТРОКАМ абзаца, а не выдумывается;
  2. абзац, разорванный концом страницы, получает рамку на КАЖДОЙ
     из них — иначе его вторая половина легла бы поверх первой;
  3. перевод, который не влезает в рамку (узбекский длиннее русского),
     уменьшается кеглем, а не обрезается;
  4. абзац БЕЗ перевода не трогается вовсе: закрасить его значило бы
     стереть текст книги;
  5. начертание считается ОТНОСИТЕЛЬНО основного в документе —
     распознаватель боевой книги пометил `Bold` весь её текст;
  6. нет библиотеки или шрифта — отказ словами, а не пустой файл.
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import pdftext
import textcount
import layout_pdf

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_fixture import make_pdf, body, folio

HEAD = "Апитерапия - медолечение"
LONG = ["Потогонный чай готовят из двух частей листьев мать-и-мачехи и ягод",
        "малины, одной части травы душицы и одной столовой ложки меда. Все",
        "это следует заварить, настоять и пить на ночь перед сном."]
TAIL = ["Отвар из меда и липовых цветков готовится из восьмидесяти граммов",
        "меда на литр воды. Приготовить так, чтобы у отвара был золотистый"]
CONT = ["цвет, а затем процедить его через марлю и добавить лимонную кислоту."]

P1 = [("t", 40, 560, 11, HEAD)] + body(LONG, top=520) + body(TAIL, top=460) + folio(120)
P2 = [("t", 40, 560, 11, HEAD)] + body(CONT, top=520) + folio(121)
PDF = make_pdf([P1, P2])
pages, geoms = textcount._pdf_pages_geom(PDF, [])
res = pdftext.clean(pages, geom=geoms)
paras = [it for it in res["items"] if it[0] == "p"]
lay = res["layout"]

print("=== 1. Рамка абзаца считается по его строкам ===")
check(len(lay) == len(paras), "рамка есть у каждого абзаца (%d/%d)" % (len(lay), len(paras)))
first = next((b for p, b in zip(paras, lay) if p[1].startswith("Потогонный")), None)
check(bool(first), "абзац найден в выдаче разбора")
if first:
    b = first[0]
    check(b["page"] == 0 and b["lines"] == 3, "рамка на своей странице и знает число строк")
    check(510 < b["top"] < 535 and 485 < b["bottom"] < 505,
          "рамка накрывает строки абзаца сверху донизу: %s" % [b["top"], b["bottom"]])
    check(b["indent"] > 5, "отступ первой строки запомнен: %s" % b["indent"])
    check(9.0 <= b["size"] <= 11.0 and 10.0 <= b["lead"] <= 14.0,
          "кегль и межстрочный взяты у оригинала: %s" % [b["size"], b["lead"]])

print("=== 2. Абзац, разорванный страницей, получает рамку на каждой ===")
split = next((b for p, b in zip(paras, lay) if p[1].startswith("Отвар")), None)
check(bool(split) and len(split) == 2 and {x["page"] for x in split} == {0, 1},
      "две рамки на двух страницах: %s" % ([x["page"] for x in split] if split else None))

print("=== 3. Перевод уменьшается кеглем, а не режется ===")
ok, why = layout_pdf.available()
if not ok:
    print("   %s — сборка слоя не проверялась" % why)
    check(True, "отказ назван словами, а не пустым файлом: %s" % why)
else:
    boxes = {str(i): b for i, (p, b) in enumerate(zip(paras, lay)) if b}
    idx = next(i for i, (p, _b) in enumerate(zip(paras, lay)) if p[1].startswith("Потогонный"))
    long_text = (paras[idx][1] + " ") * 3          # втрое длиннее оригинала
    out, stats = layout_pdf.build(PDF, {"boxes": boxes}, {idx: long_text})
    check(out[:5] == b"%PDF-", "собран PDF")
    check(stats["paragraphs"] == 1 and stats["shrunk"] == 1,
          "единственный переведённый абзац уменьшен кеглем: %s" % stats)
    from pypdf import PdfReader
    got = PdfReader(io.BytesIO(out))
    check(len(got.pages) == 2, "страницы все на месте, а не только правленые")
    text0 = got.pages[0].extract_text() or ""
    check("Потогонный чай готовят" in text0, "перевод попал на свою страницу")
    check(text0.count("Потогонный") >= 3, "длинный текст не обрезан, а помещён целиком")
    check(HEAD in text0, "колонтитул оригинала не тронут")
    check("Отвар из меда" in text0, "абзац без перевода остался оригиналом")

print("=== 3б. Хвост абзаца на второй странице закрашивается ===")
if ok:
    boxes = {str(i): b for i, (p, b) in enumerate(zip(paras, lay)) if b}
    j = next(i for i, (p, _b) in enumerate(zip(paras, lay)) if p[1].startswith("Отвар"))
    # Перевод КОРОЧЕ оригинала: он целиком влезает в первую рамку, и вторая
    # остаётся пустой — но оригинал из неё обязан быть стёрт, иначе рядом
    # с готовым переводом на следующей странице торчит русский хвост.
    out2, st2 = layout_pdf.build(PDF, {"boxes": boxes}, {j: "Коротко."})
    # Проверяем ГЛАЗАМИ страницы, а не выдачей extract_text: закраска
    # накрывает оригинал, но из содержимого страницы его не вынимает —
    # текстовый слой остаётся под ней (см. докстроку layout_pdf).
    try:
        import pypdfium2 as pdfium
        def ink(doc_bytes, box):
            d = pdfium.PdfDocument(io.BytesIO(doc_bytes))
            im = d[1].render(scale=1.0).to_pil().convert("L")
            w, h = im.size
            crop = im.crop((int(box["x0"]), int(h - box["top"]),
                            int(box["x1"]), int(h - box["bottom"])))
            px = list(crop.getdata())
            return sum(1 for v in px if v < 128) / float(len(px) or 1)
        tail = [b for b in lay[j] if b["page"] == 1][0]
        check(ink(PDF, tail) > 0.01 and ink(out2, tail) < 0.002,
              "хвост абзаца на второй странице закрашен: было %.3f, стало %.3f"
              % (ink(PDF, tail), ink(out2, tail)))
    except ImportError:
        print("   pypdfium2 не установлен — закраска не проверялась")
    check(st2["paragraphs"] == 1,
          "абзац на двух страницах посчитан ОДИН раз: %s" % st2["paragraphs"])
    check(st2["overflow"] == 0 and st2["shrunk"] == 0,
          "короткий перевод не считается ни вжатым, ни вылезшим: %s" % st2)

print("=== 4. Начертание — относительно основного в документе ===")
check(pdftext._rel_style("b", "b") == "" and pdftext._rel_style("bi", "b") == "i",
      "весь текст книги, помеченный Bold, остаётся обычным, а курсив в нём виден")
check(pdftext._rel_style("b", "") == "b", "а в обычном документе полужирный виден")

print("=== 4а. Шрифт без нужной письменности — отказ, а не квадраты ===")
if ok:
    try:
        layout_pdf.build(PDF, {"boxes": {"0": lay[0]}}, {0: "文書の翻訳です。" * 3})
        check(False, "письменность, которой нет в шрифте, обязана отказать")
    except layout_pdf.NotAvailable as e:
        check("знаков" in str(e), "отказ называет причину: %s" % str(e)[:80])

print("=== 5. Отказ без библиотеки — словами ===")
was = layout_pdf.FONT_CANDIDATES
try:
    layout_pdf.FONT_CANDIDATES = {"": [], "b": [], "i": [], "bi": []}
    ok2, why2 = layout_pdf.available()
    check(ok2 is False and "шрифт" in why2, "нет шрифта — сказано словами: %s" % why2)
    try:
        layout_pdf.build(PDF, {"boxes": {}}, {})
        check(False, "сборка без шрифта обязана отказать")
    except layout_pdf.NotAvailable:
        check(True, "сборка без шрифта отказывает исключением, а не пустым файлом")
finally:
    layout_pdf.FONT_CANDIDATES = was

print("=== 6. Сквозь сервис: загрузка PDF → перевод → выгрузка ===")
import tempfile, shutil
from pathlib import Path
os.environ["APP_PASSWORD"] = "layout-pass-1"
os.environ["AUTHORITY_CORPUS"] = "0"
import main
from starlette.testclient import TestClient
main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"], main.STATE["folders"], main.STATE["dicts"] = [], [], []
main.STATE["glossary"] = []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
TMP = Path(tempfile.mkdtemp(prefix="medcat-layout-"))
main.SOURCE_DIR = TMP / "sources"
main.EXPORT_DIR = TMP / "exports"
c = TestClient(main.app)
main._ensure_users()
tok = c.post("/api/auth/login", json={"login": "admin", "password": "layout-pass-1"}).json()["token"]
H = {"Authorization": "Bearer " + tok}
try:
    r = c.post("/api/projects/upload", headers=H, files={"file": ("kniga.pdf", PDF)},
               data={"title": "Книга", "src": "RU", "tgt": "UZ-CYRL", "domain": "general"})
    check(r.status_code == 200, "PDF принят сервисом: %s" % r.status_code)
    pid = r.json()["id"]
    data = main._load_source_map(pid)
    check(bool((data or {}).get("layout", {}).get("boxes")),
          "раскладка страниц сохранена рядом с исходником, а не в state.json")
    live = next(p for p in main.STATE["projects"] if p["id"] == pid)
    for seg in live["segments"]:
        seg["target"] = "Таржима: " + (seg.get("source") or "")[:40]
        seg["status"] = "translated"
    r = c.post("/api/projects/%d/export" % pid, headers=H, json={"format": "original"})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not ok:
        check(r.status_code in (200, 503), "без библиотеки выгрузка отвечает словами: %s" % r.status_code)
    else:
        check(r.status_code == 200 and body.get("ok"), "выгрузка собралась: %s" % str(body)[:140])
        st = body.get("stats") or {}
        check(st.get("layout") is True, "пошла дорогой «как в оригинале», а не печатью Word: %s" % st)
        check(st.get("paragraphs", 0) >= 2, "переводы встали на свои места: %s" % st.get("paragraphs"))
        got = c.get("/api/projects/%d/export/download" % pid, headers=H, params={"format": "original"})
        check(got.status_code == 200 and got.content[:5] == b"%PDF-", "файл скачивается и это PDF")
        from pypdf import PdfReader as PR2
        page0 = PR2(io.BytesIO(got.content)).pages[0].extract_text() or ""
        check("Таржима" in page0, "перевод виден в готовом файле")
finally:
    shutil.rmtree(str(TMP), ignore_errors=True)


print("=== 7. Закраска считается ПО КРАСКЕ, а не по рамке ===")
# Боевой дефект: конец строки в текстовом слое — ОЦЕНКА по средней ширине
# знака, и справа от перевода оставался хвост оригинала («…таҳлили еда»).
from PIL import Image, ImageDraw

def sample_with(bar):
    """Снимок страницы 200×100 (1 пиксель = 1 пункт): белая бумага и чёрная
    полоса `bar` = (x0, x1) на высоте рамки."""
    im = Image.new("RGB", (200, 100), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([bar[0], 40, bar[1], 60], fill=(10, 10, 10))
    return (im, 1.0, [0.0, 0.0, 0.0, 0.0], im.convert("L"))

BOX = {"page": 0, "x0": 20.0, "x1": 60.0, "top": 60.0, "bottom": 40.0,
       "size": 10.0, "lead": 12.0, "indent": 0.0, "style": ""}
x0, x1 = layout_pdf._ink_box(sample_with((20, 85)), dict(BOX), 1.8, 1.0)
check(x1 >= 84, "хвост оригинала, которого не увидел текстовый слой, накрыт: %.1f" % x1)
x0, x1 = layout_pdf._ink_box(sample_with((20, 60)), dict(BOX), 1.8, 1.0)
check(x1 < 70, "рамка без хвоста не раздувается: %.1f" % x1)
# Соседняя колонка стоит за настоящим пробелом (шире межсловного) — туда
# закраска не заезжает: там чужой текст, и стереть его нельзя.
im = Image.new("RGB", (200, 100), (255, 255, 255))
ImageDraw.Draw(im).rectangle([20, 40, 55, 60], fill=(10, 10, 10))
ImageDraw.Draw(im).rectangle([120, 40, 190, 60], fill=(10, 10, 10))
x0, x1 = layout_pdf._ink_box((im, 1.0, [0, 0, 0, 0], im.convert("L")), dict(BOX), 1.8, 1.0)
check(x1 < 100, "через межколонник закраска не переходит: %.1f" % x1)
x0, x1 = layout_pdf._ink_box(None, dict(BOX), 1.8, 1.0)
check((x0, x1) == (20.0, 60.0), "нет снимка страницы — рамка остаётся как есть")

print("=== 8. Колонтитул: один текст в КАЖДОЙ своей рамке ===")
head_boxes = [{"page": 0, "x0": 40.0, "x1": 200.0, "top": 575.0, "bottom": 563.0,
               "size": 9.0, "lead": 11.0, "indent": 0.0, "style": "", "repeat": 1},
              {"page": 1, "x0": 40.0, "x1": 200.0, "top": 575.0, "bottom": 563.0,
               "size": 9.0, "lead": 11.0, "indent": 0.0, "style": "", "repeat": 1}]
out, st = layout_pdf.build(PDF, {"boxes": {"0": head_boxes}}, {0: "Асалари дорихонаси"})
txt = [(p.extract_text() or "") for p in __import__("pypdf").PdfReader(io.BytesIO(out)).pages]
check(all("Асалари дорихонаси" in t for t in txt),
      "надпись напечатана на обеих своих страницах целиком, а не поделена между ними")
check(st["repeated"] == 1 and st["repeatBoxes"] == 2 and st["paragraphs"] == 1,
      "и посчитана ОДНИМ решением переводчика: %s" % {k: st[k] for k in ("repeated", "repeatBoxes", "paragraphs")})

print("=== 9. Надпись со страницы-картинки печатается наравне с абзацем ===")
extra = [{"text": "Асал билан даволаш", "boxes": [{
    "page": 1, "frac": 1, "image": 1, "style": "", "indent": 0.0,
    "x0": 0.1, "x1": 0.8, "top": 0.2, "bottom": 0.3, "size": 0.03, "lead": 0.035}]}]
out, st = layout_pdf.build(PDF, {"boxes": {}}, {}, extra=extra)
txt = [(p.extract_text() or "") for p in __import__("pypdf").PdfReader(io.BytesIO(out)).pages]
check("Асал билан даволаш" in txt[1] and "Асал билан даволаш" not in txt[0],
      "перевод встал на свою страницу — ту, где картинка")
check(st["imageBoxes"] == 1 and st["paragraphs"] == 1, "и назван числом: %s" % st["imageBoxes"])

print("=== 9а. Надпись с картинки ужимается по ШИРИНЕ рамки ===")
# Боевая обложка: «Священник Александр Лазебный» уезжало за край листа —
# слово длиннее рамки переносить нечем, а рамка обведена вокруг самих букв,
# и вылезшее слово ложится на сам рисунок, а не на поле страницы.
tight = [{"page": 0, "x0": 40.0, "x1": 120.0, "top": 500.0, "bottom": 470.0,
          "size": 22.0, "lead": 24.0, "indent": 0.0, "style": "", "image": 1}]
FONTS = layout_pdf._register_fonts()
from reportlab.pdfbase import pdfmetrics as _pm
size, lead, per_box, fits = layout_pdf._fit("Александр Лазебний", tight, _pm.stringWidth, FONTS[""])
check(fits and all(_pm.stringWidth(ln, FONTS[""], size) <= 80.0 for ln in per_box[0]),
      "кегль ужат, пока слово не влезло в рамку: %.1f, строки %s" % (size, per_box[0]))
wide = [dict(tight[0], image=0, top=540.0)]   # высоты хватает на две строки
size2, _l, per2, _f = layout_pdf._fit("Александр Лазебний", wide, _pm.stringWidth, FONTS[""])
check(size2 > size, "у текстовой рамки правило другое — там есть поля: %.1f против %.1f" % (size2, size))

print("=== 9б. Заливка идёт ДО текста, вся разом ===")
# Рамки надписей с картинки законно пересекаются (стилизованная обложка),
# и заливка второй стирала бы уже написанный перевод первой — с отчётом
# «обе написаны». Тот же закон, что в `image_text.render_target`.
over = [{"text": "Асалари", "boxes": [{"page": 0, "frac": 1, "image": 1, "style": "",
                                       "indent": 0.0, "x0": 0.1, "x1": 0.6, "top": 0.30,
                                       "bottom": 0.36, "size": 0.02, "lead": 0.025}]},
        {"text": "дорихонаси", "boxes": [{"page": 0, "frac": 1, "image": 1, "style": "",
                                          "indent": 0.0, "x0": 0.15, "x1": 0.7, "top": 0.33,
                                          "bottom": 0.40, "size": 0.02, "lead": 0.025}]}]
out, st = layout_pdf.build(PDF, {"boxes": {}}, {}, extra=over)
txt = __import__("pypdf").PdfReader(io.BytesIO(out)).pages[0].extract_text() or ""
check("Асалари" in txt and "дорихонаси" in txt,
      "обе надписи на месте: заливка соседней рамки не стёрла уже написанное")

print("=== 9в. Вложенный повтор надписи печатается один раз ===")
# Разбор надписей отдаёт один кусок дважды — рамкой целиком и её частью
# («Все о медолечении и пчелоужалении» и «о медолечении и пчелоужалении»
# на обложке боевой книги). В .docx это безобидно, а в PDF два перевода
# легли друг на друга поверх фотографии.
sys.path.insert(0, "backend")
import main as _main
_bx = lambda x0, x1, t, b: {"page": 0, "x0": x0, "x1": x1, "top": t, "bottom": b,
                            "size": 0.02, "lead": 0.02, "image": 1, "frac": 1,
                            "style": "", "indent": 0.0}
keep, dropped = _main._drop_nested_labels([
    {"text": "Все о медолечении и пчелоужалении", "boxes": [_bx(0.1, 0.8, 0.20, 0.30)]},
    {"text": "о медолечении и пчелоужалении", "boxes": [_bx(0.2, 0.7, 0.22, 0.28)]},
    {"text": "Другая подпись", "boxes": [_bx(0.2, 0.7, 0.22, 0.28)]}])
check(dropped == 1 and [i["text"] for i in keep][0].startswith("Все о"),
      "снят ровно вложенный повтор: %s" % [i["text"] for i in keep])
check(any(i["text"] == "Другая подпись" for i in keep),
      "вложенная рамка с ДРУГИМ текстом — законная подпись внутри схемы, её не трогаем")

print("=== 10. Рамка долями листа раскрывается в точки страницы ===")
class _MB:
    left, bottom, width, height = 0.0, 0.0, 400.0, 600.0
b = {"x0": 0.25, "x1": 0.75, "top": 0.1, "bottom": 0.2, "size": 0.02, "lead": 0.025, "frac": 1}
layout_pdf._unfrac(b, _MB())
check(b["x0"] == 100.0 and b["x1"] == 300.0, "доли ширины — в точки: %s" % [b["x0"], b["x1"]])
check(b["top"] == 540.0 and b["bottom"] == 480.0,
      "ось y у картинки смотрит вниз, у PDF — вверх: %s" % [b["top"], b["bottom"]])
check(b["size"] == 12.0 and b["lead"] == 15.0, "кегль и межстрочный — доли высоты листа")

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
