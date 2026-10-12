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
import hashlib, io, os, sys
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
        # Чероки — письменности нет ни в одном шрифте (японский теперь печатается
        # картинкой строки шрифтом Noto JP из репозитория).
        layout_pdf.build(PDF, {"boxes": {"0": lay[0]}}, {0: "ᏣᎳᎩ ᎦᏬᏂᎯᏍᏗ ᎠᏂᏴᏫ" * 3})
        check(False, "письменность, которой нет в шрифте, обязана отказать")
    except layout_pdf.NotAvailable as e:
        check("знаков" in str(e), "отказ называет причину: %s" % str(e)[:80])

print("=== 5. Отказ без библиотеки — словами ===")
was = layout_pdf.FONT_CANDIDATES
was_fb = layout_pdf._REPO_FALLBACK
try:
    layout_pdf.FONT_CANDIDATES = {"": [], "b": [], "i": [], "bi": []}
    layout_pdf._REPO_FALLBACK = {}         # и запасного DejaVu из репозитория нет
    ok2, why2 = layout_pdf.available()
    check(ok2 is False and "шрифт" in why2, "нет шрифта — сказано словами: %s" % why2)
    try:
        layout_pdf.build(PDF, {"boxes": {}}, {})
        check(False, "сборка без шрифта обязана отказать")
    except layout_pdf.NotAvailable:
        check(True, "сборка без шрифта отказывает исключением, а не пустым файлом")
finally:
    layout_pdf.FONT_CANDIDATES = was
    layout_pdf._REPO_FALLBACK = was_fb

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
        # Формат «PDF» у проекта из PDF — ТЕ ЖЕ страницы с переводом, а не
        # печать собранного Word-документа (боевой проект 14: «скачивается
        # как обычный текст»).
        r = c.post("/api/projects/%d/export" % pid, headers=H, json={"format": "pdf"})
        bp = r.json() if r.status_code == 200 else {}
        check(bp.get("ok") and (bp.get("stats") or {}).get("pdfFrom") == "original",
              "формат «PDF» собран поверх страниц оригинала: %s" % str(bp)[:160])
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
# Слева от заголовка в книге стоит рисованная виньетка: влево раздвигаем
# на один знак, не больше — ошибка ширины знака копится к КОНЦУ строки,
# а начало текстовый слой знает точно.
im = Image.new("RGB", (200, 100), (255, 255, 255))
ImageDraw.Draw(im).rectangle([2, 38, 18, 62], fill=(10, 10, 10))    # виньетка
ImageDraw.Draw(im).rectangle([40, 40, 80, 60], fill=(10, 10, 10))   # строка
VBOX = dict(BOX, x0=40.0, x1=80.0)
x0, x1 = layout_pdf._ink_box((im, 1.0, [0, 0, 0, 0], im.convert("L")), VBOX, 1.8, 1.0)
check(x0 > 20, "рисунок слева от заголовка не закрашен: %.1f" % x0)
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

print("=== 11. Каждый вызов pdfium — под общим замком ===")
# Падает не наш код, а нативная библиотека, и вместе с ней ВЕСЬ процесс:
# питоновского исключения тут не бывает, поймать нечем, на боевом сервере
# это дважды уносило сервис посреди выгрузки книги. Поэтому проверка
# механическая — забытое новое место ничем другим не видно. Список файлов
# выводится из САМОГО кода (кто импортирует pypdfium2), а не пишется руками:
# переписанный в тест перечень устаревает первым же новым модулем.
import ast as _ast, re as _re
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
_PDF_CALL = _re.compile(r"pdfium\.PdfDocument\(|(?:page|pdf|doc)\.close\(\)"
                        r"|\.render\(|\.get_cropbox\(\)|_box_shift\(")
_users = [f for f in sorted(_BACKEND.glob("*.py"))
          if "import pypdfium2" in f.read_text(encoding="utf-8")]
check(len(_users) >= 2, "файлы, зовущие pdfium, найдены по коду: %s" % [f.name for f in _users])
for _f in _users:
    _src = _f.read_text(encoding="utf-8")
    _tree = _ast.parse(_src)
    _safe = [(n.lineno, n.end_lineno) for n in _ast.walk(_tree)
             if isinstance(n, _ast.With)
             and any("PDFIUM_LOCK" in _ast.dump(it) for it in n.items)]
    _bad = []
    for _i, _line in enumerate(_src.splitlines(), 1):
        _code = _line.strip()
        if (not _code or _code.startswith("#") or _code.startswith("def ")
                or not _PDF_CALL.search(_code)):
            continue
        if not any(a <= _i <= b for a, b in _safe):
            _bad.append("%s:%d %s" % (_f.name, _i, _code[:60]))
    check(not _bad, "%s: вызовы pdfium вне замка — %s" % (_f.name, _bad or "нет"))

print("=== 12. Повёрнутая, отрезанная и накрытая строка не отнимают у страницы места ===")
# Боевой случай (проект 14, CamScanner): PDF склеен в две страницы-ленты
# по 14 400 пт, и одна повёрнутая подпись в схеме лишала геометрии ВСЮ
# страницу — то есть весь документ: выгрузка «как в оригинале» молча
# печатала поток абзацев. Там же: копия схемы за обрезкой (иные цифры,
# сдвиг 23 пт) и абзац под непрозрачной закраской печатались поверх.
GOOD = ["Сахарный диабет второго типа лечат по рекомендациям, которые",
        "обновляют каждые несколько лет по данным новых исследований."]
from pdf_fixture import body as _fx_body       # `body` выше занят ответом сервиса
LATIN = "Latin line where every letter is in the width table"
P12 = (_fx_body(GOOD, top=520) + [("t", 40, 420, 10, LATIN)]
       + [("raw", "BT /F1 9 Tf 0 1 -1 0 380 200 Tm {HEX:Повёрнутая подпись схемы:HEX} Tj ET"),
          # Отрезанная: обрезка 0..100 по x, текст стоит на x=250.
          ("raw", "q 0 0 100 600 re W n BT /F1 10 Tf 1 0 0 1 250 300 Tm "
                  "{HEX:Скрытая копия за обрезкой:HEX} Tj ET Q"),
          # Накрытая: текст, ПОТОМ белый прямоугольник поверх.
          ("raw", "BT /F1 10 Tf 1 0 0 1 40 200 Tm {HEX:Абзац под закраской:HEX} Tj ET "
                  "1 g 30 190 200 25 re f 0 g"),
          # Видимая: прямоугольник ПОД текстом (фон врезки) — текст виден.
          ("raw", "0.9 g 30 120 200 25 re f 0 g BT /F1 10 Tf 1 0 0 1 40 130 Tm "
                  "{HEX:Текст на плашке виден:HEX} Tj ET")])
PDF12 = make_pdf([P12])
pg12, gm12 = textcount._pdf_pages_geom(PDF12, [])
res12 = pdftext.clean(pg12, geom=gm12)
paras12 = [it for it in res12["items"] if it[0] == "p"]
place12 = {it[1]: it[2] for it in paras12}
good = next((b for t, b in place12.items() if t.startswith("Сахарный")), None)
check(bool(good), "у основного текста страницы рамка ЕСТЬ, несмотря на повёрнутую строку")
def _rot_slot_of(boxes):
    return [sl for b in (boxes or []) for sl in (b.get("slots") or [])
            if len(sl) > 8 and isinstance(sl[8], dict)]
rot_hit = [(t, b) for t, b in place12.items() if "Повёрнутая" in t]
check(len(rot_hit) == 1 and _rot_slot_of(rot_hit[0][1]),
      "повёрнутая строка — своим абзацем С ПУТЁМ (печатается повёрнутой): %s"
      % [(t[:30], bool(b)) for t, b in rot_hit])
for t_, label in (("Скрытая", "отрезанная обрезкой"), ("Абзац под", "накрытая закраской")):
    # Подряд идущие строки без места — одна вставка: проверяем, что фраза
    # в абзаце БЕЗ места и что её текст не потерян.
    hit = [(t, b) for t, b in place12.items() if t_ in t]
    check(len(hit) == 1 and not hit[0][1],
          "%s строка — абзацем БЕЗ места (переводится, не печатается): %s"
          % (label, [(t[:30], bool(b)) for t, b in hit]))
    check(not any(t_ in t for t, b in place12.items() if b), "%s строка не влита в текст с местом" % label)
vis = [(t, b) for t, b in place12.items() if t.startswith("Текст на плашке")]
check(len(vis) == 1 and bool(vis[0][1]), "текст ПОВЕРХ плашки остаётся видимым и получает место")
check(res12["report"].get("placelessLines", 0) >= 3,
      "строки без места названы числом: %s" % res12["report"].get("placelessLines"))

print("=== 12а. Места строк и точный конец строки ===")
slots12 = (good or [{}])[0].get("slots") or []
check(len(slots12) == 2, "у абзаца место КАЖДОЙ строки: %s" % len(slots12))
# Конец строки — по СЫРЫМ кодам оператора показа текста: буквы фикстуры
# приходят по карте ToUnicode, и по букве ширину не найти, а по коду — да.
check(all(len(s) > 7 and s[7] for s in slots12),
      "конец строки посчитан по кодам оператора, а не по буквам куска")
# Ширина знака у шрифта фикстуры — 500/1000 кегля: строка из N знаков
# кончается в x0 + N·5 при кегле 10.
if slots12:
    s0 = slots12[0]
    want = s0[0] + len(GOOD[0].rstrip()) * 5.0
    check(abs(s0[2] - want) < 1.0, "x1 = %s, по метрикам %s" % (s0[2], want))
lat = next((b for t, b in place12.items() if t.startswith("Latin")), None)
ls = ((lat or [{}])[0].get("slots") or [[0, 0, 0, 0, "", 0, 0, 0]])[0]
check(len(ls) > 7 and ls[7], "все буквы в таблице ширин — конец строки по метрикам шрифта")
check(abs(ls[2] - (40 + len(LATIN) * 5.0)) < 1.0, "x1 = %s, по метрикам %s" % (ls[2], 40 + len(LATIN) * 5.0))

print("=== 12б. Гарнитура — по имени шрифта ===")
import pdfpages_worker as _pw
for name, want in (("ABCDEF+MinionPro-Bold", "serif"), ("DINNextLTPro-Condensed", "sans"),
                   ("Calibri-Italic", "sans"), ("Palatino-Roman", "serif"),
                   ("ZapfDingbats", ""), ("CourierNewPSMT", "mono"),
                   ("MicrosoftSansSerif", "sans"), ("font0000000030790b66", "")):
    check(_pw._family(name) == want, "%s → %r" % (name, _pw._family(name)))

print("=== 12в. Перевод — в места строк; соседняя колонка не закрашивается ===")
# Заголовок в одну строку и колонка справа на той же высоте: конец заголовка
# (оценка) не вправе зайти за начало соседней строки.
sd = [{"x": 40.0, "x0": 40.0, "x1": 260.0, "y": 500.0, "size": 15.0, "page": 0},
      {"x": 200.0, "x0": 200.0, "x1": 300.0, "y": 498.0, "size": 6.0, "page": 0}]
layout_pdf._neighbour_limits(sd)
check(sd[0].get("lim") == 200.0, "рубеж строки — начало соседней справа: %s" % sd[0].get("lim"))
check("lim" not in sd[1], "у правой строки соседа справа нет")
_sl = [{"x": 40.0, "x0": 40.0, "x1": 140.0, "y": 500 - 12 * k, "size": 10.0, "page": 0,
        "style": "", "n": 30} for k in range(3)]
check(not layout_pdf._scattered(_sl), "колонка строк — не разброс")
_sc = [dict(_sl[0]), dict(_sl[1], y=560.0), dict(_sl[2], y=300.0, size=16.0)]
check(layout_pdf._scattered(_sc), "подписи схемы в разных местах и кеглях — разброс")
from reportlab.pdfbase import pdfmetrics as _pm
_fonts = layout_pdf._register_fonts() if ok else {}
if ok:
    _lines, _fs, _hs = layout_pdf._spread("один два три четыре пять шесть", [
        dict(_sl[0], n=10), dict(_sl[1], n=10), dict(_sl[2], n=10)], _pm.stringWidth,
        lambda s: _fonts[""])
    check(all(_lines), "разброс: перевод роздан ВСЕМ местам по доле оригинала: %s" % _lines)
    _w1 = _pm.stringWidth("слово", _fonts[""], 10.0)
    _sp = _pm.stringWidth(" ", _fonts[""], 10.0)
    # На строку в 100 пт помещается n слов при кегле 10; просим на одно больше
    # на каждую строку — сужения 85% не хватает, нужен и кегль.
    _n = int((100 + _sp) // (_w1 + _sp))
    _l2, _f2, _rest2, _h2 = layout_pdf._fit_slots(" ".join(["слово"] * (3 * (_n + 2))), _sl,
                                                 _pm.stringWidth, lambda s: _fonts[""], "left")
    check(not _rest2, "не влезло — уложено целиком: %s" % _rest2[:3])
    check(abs(_h2 - layout_pdf.HSCALE_MIN) < 1e-9 and _f2 < 1.0,
          "сперва сужение до порога, потом кегль: сужение %.2f, кегль %.2f" % (_h2, _f2))
    _l3, _f3, _r3, _h3 = layout_pdf._fit_slots(" ".join(["слово"] * (3 * _n)), _sl,
                                              _pm.stringWidth, lambda s: _fonts[""], "left")
    check(_f3 == 1.0 and _h3 == 1.0 and not _r3, "влезает как есть — кегль и ширина прежние")
    # Синтетический курсив: файла курсива нет — печать дорисует наклон.
    _name = _fonts.get("i") or _fonts[""]
    check(layout_pdf._synth(_fonts, _name, "i") in ("i", ""),
          "курсив без файла — наклоном: %r" % layout_pdf._synth(_fonts, _name, "i"))

if ok:
    lay12 = {"boxes": {k: v for k, v in enumerate(it[2] for it in paras12) if v}}
    texts12 = {k: "Перевод строки номер %d для проверки мест" % k for k in lay12["boxes"]}
    pdf12, st12 = layout_pdf.build(PDF12, lay12, texts12)
    from pypdf import PdfReader as _PR
    t12 = _PR(io.BytesIO(pdf12)).pages[0].extract_text() or ""
    check("Перевод строки" in t12, "перевод напечатан в местах строк")
    check(st12.get("slotParagraphs", 0) >= 1, "абзацы ушли дорогой мест строк: %s" % st12)

print("=== 12г. Находки критика: наклон, строка внутри абзаца, выключка, письмо ===")
# Наклон (синтетический курсив Word/Chrome, `Tm 1 0 0.21 1`) — не поворот:
# строка стоит ровно и остаётся в своём абзаце.
SK = (_fx_body(["Первая строка абзаца про лечение и наблюдение больного"], top=520)
      + [("raw", "BT /F1 10 Tf 1 0 0.21 1 40 508 Tm {HEX:наклонная строка того же абзаца:HEX} Tj ET")]
      + _fx_body(["и третья строка, которой абзац заканчивается."], top=496, first_indent=0))
pgs, gms = textcount._pdf_pages_geom(make_pdf([SK]), [])
check(all(x is not None for x in gms[0]["lines"]), "наклонная строка — с местом, а не повёрнутая")
# Повёрнутая строка ВНУТРИ абзаца (следующая продолжает со строчной) —
# остаётся в потоке на своём месте, а не уходит куском фразы в конец
# страницы; и страница не теряет раскладку (у PDF-«ленты» это весь документ).
IN = (_fx_body(["Начало абзаца, который продолжается после"], top=520)
      + [("raw", "BT /F1 10 Tf 0 1 -1 0 300 300 Tm {HEX:вертикальная вставка:HEX} Tj ET")]
      + _fx_body(["середины и кончается здесь."], top=508, first_indent=0))
pgs, gms = textcount._pdf_pages_geom(make_pdf([IN]), [])
r_in = pdftext.clean(pgs, geom=gms)
p_in = [it for it in r_in["items"] if it[0] == "p"]
check(any("продолжается после середины" in x[1] for x in p_in)
      and any(x[1] == "вертикальная вставка" and _rot_slot_of(x[2]) for x in p_in),
      "повёрнутая подпись между строками фразы — отдельной вставкой, фраза цела: %s"
      % [x[1] for x in p_in])
check(any(x[2] for x in p_in), "абзац сохранил рамку — страница не ушла на прежнюю дорогу")
# После ПЕРЕНОСА слова строка без места — часть слова, она остаётся в потоке.
HY = (_fx_body(["Начало абзаца про лече-"], top=520)
      + [("raw", "BT /F1 10 Tf 0 1 -1 0 300 300 Tm {HEX:ние:HEX} Tj ET")]
      + _fx_body(["больного в стационаре."], top=508, first_indent=0))
pgs, gms = textcount._pdf_pages_geom(make_pdf([HY]), [])
p_hy = [it for it in pdftext.clean(pgs, geom=gms)["items"] if it[0] == "p"]
check(len(p_hy) == 1 and "лечение больного" in p_hy[0][1],
      "после переноса строка без места — в потоке на своём месте: %s" % [x[1] for x in p_hy])

print("=== 12д. Форма без q/Q и большой невидимый слой не прячут видимый текст ===")
# Форма (Form XObject) с обрезкой, нарисованная без q/Q вокруг: по стандарту
# Do — это q…Q, и её обрезка не вправе спрятать текст страницы после неё.
_fm = make_pdf([_fx_body(["Строка до формы на странице книги."], top=540)
                + [("raw", "/Fm1 Do")]
                + _fx_body(["Первая строка текста после формы.", "Вторая строка текста после формы.",
                            "Третья строка текста после формы."], top=500)])
# Вписываем форму в ресурсы страницы руками: фикстура умеет только картинку.
from pypdf import PdfReader as _PRf, PdfWriter as _PWf
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject, ArrayObject, FloatObject
_r = _PRf(io.BytesIO(_fm)); _w = _PWf(); _w.append_pages_from_reader(_r)
_form = DecodedStreamObject(); _form.set_data(b"300 50 50 50 re W n 300 50 50 50 re f")
_form.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
              NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(400), FloatObject(600)]),
              NameObject("/Resources"): DictionaryObject({NameObject("/ProcSet"): ArrayObject([NameObject("/PDF")])})})
_pg = _w.pages[0]
_pg[NameObject("/Resources")][NameObject("/XObject")][NameObject("/Fm1")] = _w._add_object(_form)
_bf = io.BytesIO(); _w.write(_bf)
pgs, gms = textcount._pdf_pages_geom(_bf.getvalue(), [])
check(all(x for x in gms[0]["lines"]), "обрезка из формы не прячет текст после неё: %s"
      % [bool(x) for x in gms[0]["lines"]])
# Большой невидимый слой (копия за обрезкой больше видимого текста) не
# лишает видимый текст раскладки; его строки — одной вставкой.
HID = (_fx_body(["Видимая строка один про лечение.", "Видимая строка два про лечение.",
                 "Видимая строка три про лечение."], top=520)
       + [("raw", "q 0 0 100 600 re W n BT /F1 10 Tf 1 0 0 1 250 %d Tm {HEX:%s:HEX} Tj ET Q" % (300 - 12 * k, t))
          for k, t in enumerate(["Скрытая копия схемы доза", "в сутки для взрослых", "лечение в стационаре",
                                 "ещё одна строка копии"])])
pgs, gms = textcount._pdf_pages_geom(make_pdf([HID]), [])
pl = []
recs_h = pdftext._geo_page(pgs[0], gms[0], pl)
check(recs_h is not None, "невидимый слой больше видимого — раскладка видимого цела")
check(len(pl) == 1 and len(pl[0]) == 4, "невидимые строки — одной вставкой подряд: %s" % pl)
# Отступ первой строки выровненного абзаца — «влево», а не «вправо».
_ind = [{"x": 28.0, "x0": 28.0, "x1": 300.0, "y": 500.0, "size": 10.0, "page": 0},
        {"x": 10.0, "x0": 10.0, "x1": 300.0, "y": 488.0, "size": 10.0, "page": 0},
        {"x": 10.0, "x0": 10.0, "x1": 299.0, "y": 476.0, "size": 10.0, "page": 0}]
check(layout_pdf._slot_align(_ind) == "left", "отступ первой строки — выключка влево")
# Абзац, разорванный рисунком в той же колонке, — не разброс.
_wrap = [dict(_ind[1], y=500.0 - 12 * k) for k in range(3)] + \
        [dict(_ind[1], y=250.0 - 12 * k) for k in range(3)]
check(not layout_pdf._scattered(_wrap), "абзац над и под рисунком в одной колонке — не разброс")
# Письмо справа налево и со сборкой букв печать слоя честно не берёт;
# армянский и грузинский — берёт (запасной DejaVu их знает).
check(layout_pdf._unsupported_script({1: "مرحبا"}) != "", "арабица — отказ словами")
check(layout_pdf._unsupported_script({1: "नमस्ते"}) != "", "деванагари — отказ словами")
check(layout_pdf._unsupported_script({1: "Բարեւ ძველი Привет"}) == "", "армянский, грузинский — можно")
if ok:
    _p = layout_pdf.font_path("", "", set("Բարեւ"))
    check(bool(_p) and layout_pdf._covers(_p, set("Բարեւ")), "шрифт выбран по буквам перевода: %s" % _p)
# Скан выгружается листом того же размера, что оригинал.
from PIL import Image as _Img
import importers as _imp
_b = io.BytesIO(); _Img.new("L", (800, 1200), 255).save(_b, format="PNG")
_pdf = _imp.images_to_file([("p1.png", _b.getvalue())], ".pdf", page_w_pt=300.0)
from pypdf import PdfReader as _PR3
_mb = _PR3(io.BytesIO(_pdf)).pages[0].mediabox
check(abs(float(_mb.width) - 300.0) < 0.5 and abs(float(_mb.height) - 450.0) < 0.5,
      "лист скана — размера оригинала: %sx%s" % (float(_mb.width), float(_mb.height)))

print("=== 12е. Повёрнутая строка и текст по дуге печатаются по своему пути ===")
import math as _m
# Текст по дуге — как его пишут программы вёрстки: ОДИН BT, у каждой буквы
# своя матрица (Tm) с углом касательной к дуге.
_ops = []
_ang = 0.0
for k_, ch_ in enumerate("АРКА СХЕМЫ"):
    a_ = -30 - 6 * k_
    x_, y_ = 200 + 60 * _m.cos(_m.radians(a_ + 90)), 300 + 60 * _m.sin(_m.radians(a_ + 90))
    ca, sa = _m.cos(_m.radians(a_)), _m.sin(_m.radians(a_))
    _ops.append("%.4f %.4f %.4f %.4f %.2f %.2f Tm {HEX:%s:HEX} Tj" % (ca, sa, -sa, ca, x_, y_, ch_))
_arc = [("raw", "BT /F1 9 Tf " + " ".join(_ops) + " ET")]
RP = (_fx_body(["Обычный абзац страницы, где рядом схема с подписями."], top=540)
      + [("raw", "BT /F1 9 Tf 0 1 -1 0 360 150 Tm {HEX:Подпись вдоль оси:HEX} Tj ET")] + _arc)
pdf_rp = make_pdf([RP])
pgs, gms = textcount._pdf_pages_geom(pdf_rp, [])
r_rp = pdftext.clean(pgs, geom=gms)
p_rp = [it for it in r_rp["items"] if it[0] == "p"]
ax = [x for x in p_rp if "Подпись вдоль оси" in x[1]]
arc = [x for x in p_rp if "АРКА" in x[1]]
check(ax and _rot_slot_of(ax[0][2]) and not _rot_slot_of(ax[0][2])[0][8]["curved"],
      "подпись вдоль оси — прямой повёрнутый путь")
check(arc and _rot_slot_of(arc[0][2]) and _rot_slot_of(arc[0][2])[0][8]["curved"],
      "буквы по дуге — путь-дуга: %s" % [x[1] for x in arc])
check(arc and arc[0][1].startswith("АРКА СХЕМЫ"), "у текста по дуге восстановлен пробел: %r"
      % (arc[0][1] if arc else None))
check(not r_rp.get("unplaced"), "строк без места не осталось: %s" % r_rp.get("unplaced"))
if ok:
    lay_rp = {"boxes": {k: it[2] for k, it in enumerate(p_rp) if it[2]}}
    texts_rp = {k: "Перевод %d" % k for k in lay_rp["boxes"]}
    pdf_o, st_o = layout_pdf.build(pdf_rp, lay_rp, texts_rp)
    check(st_o.get("rotatedSlots", 0) >= 2, "повёрнутая строка и дуга напечатаны: %s" % st_o.get("rotatedSlots"))

print("=== 12ж. Иероглифы и письмо со сборкой букв — печать картинкой строки ===")
if ok:
    lay_c = {"boxes": {k: v for k, v in enumerate(it[2] for it in paras12) if v}}
    zh = {k: "糖尿病患者的治疗和血糖控制 COVID-19" for k in lay_c["boxes"]}
    try:
        pdf_c, st_c = layout_pdf.build(PDF12, lay_c, zh)
        check(st_c.get("raster", 0) > 0, "иероглифы напечатаны картинкой строки: %s" % st_c.get("raster"))
    except layout_pdf.NotAvailable as e:
        check(False, "иероглифы обязаны печататься (шрифт Noto SC в репозитории): %s" % e)
    from PIL import features as _ft
    he = {k: "טיפול בסוכרת ובקרת הסוכר 2026" for k in lay_c["boxes"]}
    try:
        pdf_h, st_h = layout_pdf.build(PDF12, lay_c, he)
        check((_ft.check("raqm") or st_h.get("shaper") == "vector") and st_h.get("raster", 0) > 0,
              "иврит напечатан сборкой букв (HarfBuzz контурами или raqm): %s" % st_h.get("shaper"))
    except layout_pdf.NotAvailable as e:
        check(not _ft.check("raqm") and "raqm" in str(e),
              "без raqm письмо справа налево — отказ словами, а не каша: %s" % e)
    _rs = layout_pdf._Raster(set("مرحبا COVID"))
    rr = _rs.runs("مرحبا COVID-19")
    check(len({r_[0] for r_ in rr}) >= 2 and any("Arabic" in r_[0] for r_ in rr),
          "арабская строка с латиницей — два шрифта по знакам: %s"
          % [(r_[0].rsplit("/", 1)[-1], r_[1]) for r_ in rr])
    check(layout_pdf._cut_point("नमस्ते", 3) in (1, 2), "резка не отрывает огласовку от буквы")

print("=== 12з. Надписи внутри растра рисунка: что в слое — не читаем, остальное — на место ===")
import main as _mn
_rec = {"w": 200, "h": 100, "blocks": [{"box": [10, 10, 90, 30]}, {"box": [110, 60, 190, 80]}]}
_data = {"layout": {"pages": [[0, 0, 400, 600]],
                    "boxes": {"0": [{"page": 0, "slots": [[20, 578, 90, 10, "", 20, 10, 1]]}]}}}
_b = io.BytesIO(); _Img.new("RGB", (200, 100), 255).save(_b, format="PNG")
_tagged = _imp.tag_figure(_b.getvalue(), 0, [0.0, 0.0, 0.5, 0.1667])
check(_mn._mark_layer_blocks(_rec, _tagged, _data) == 1 and _rec["blocks"][0].get("skip") == "layer"
      and not _rec["blocks"][1].get("skip"),
      "блок рисунка под строкой текстового слоя — не читается; блок только в растре — читается: %s"
      % [b_.get("skip") for b_ in _rec["blocks"]])
check(_imp.figure_tag(_tagged)[0] == 0, "вырезка рисунка помнит страницу и место")
# Строка наполовину слоем («Optimize» в слое), наполовину кривыми («quality
# of life»): блок обрезается до непокрытой части, а не отсеивается целиком.
_rec2 = {"w": 200, "h": 100, "blocks": [{"box": [10, 10, 190, 30]}]}
_data2 = {"layout": {"pages": [[0, 0, 400, 600]],
                     "boxes": {"0": [{"page": 0, "slots": [[2, 575, 90, 16, "", 2, 8, 1]]}]}}}
check(_mn._mark_layer_blocks(_rec2, _tagged, _data2) == 0 and _rec2["blocks"][0].get("trim") == "layer"
      and _rec2["blocks"][0]["box"][0] > 60 and _rec2["blocks"][0]["box"][2] == 190,
      "строка наполовину слоем — блок обрезан до кривой части: %s" % _rec2["blocks"][0])

print("=== 12з2. Надписи на картинках читаются САМИ при загрузке ===")
_calls = []
_saved = (_mn._job_enqueue, _mn._provider_ready, _mn._spend_status, _mn.image_text.engine_ready,
          _mn._docx_has_pictures)
try:
    _mn._job_enqueue = lambda pid, kind, ids, params: (_calls.append((pid, kind, params)) or {"id": 77})
    _mn._provider_ready = lambda m: True
    _mn._spend_status = lambda t: {"over": False}
    _mn.image_text.engine_ready = lambda: (True, "")
    _pr = {"id": 31, "tenant": "default"}
    check(_mn._auto_read_images(_pr, "pdf") == 77 and _calls[-1][1] == "images"
          and _calls[-1][2].get("pages") is True and _pr.get("imagesReading") == 77,
          "PDF с текстом — чтение ставится само, вместе со страницами (надписи кривыми)")
    _pr2 = {"id": 32, "tenant": "default", "trialExcerpt": {"pages": 1}}
    n0 = len(_calls)
    check(_mn._auto_read_images(_pr2, "pdf") is None and len(_calls) == n0,
          "пробный фрагмент — остаток файла даром не читаем")
    _mn._docx_has_pictures = lambda pid: False
    check(_mn._auto_read_images({"id": 33, "tenant": "default"}, "docx") is None,
          ".docx без картинок — задачи нет")
    _mn._docx_has_pictures = lambda pid: True
    _pr4 = {"id": 34, "tenant": "default"}
    check(_mn._auto_read_images(_pr4, "docx") == 77 and _calls[-1][2].get("pages") is False,
          ".docx с картинками — чтение ставится само")
    _mn.image_text.engine_ready = lambda: (False, "нет движка")
    _pr5 = {"id": 35, "tenant": "default"}
    check(_mn._auto_read_images(_pr5, "pdf") is None and _pr5.get("imagesSkipped") == "no_engine",
          "нет движка поиска строк — причина кодом, а не тишина")
finally:
    (_mn._job_enqueue, _mn._provider_ready, _mn._spend_status, _mn.image_text.engine_ready,
     _mn._docx_has_pictures) = _saved

print("=== 12и. Надписи кривыми на странице: страница — картинкой в разборе надписей ===")
import tempfile as _tf
_tmpd = Path(_tf.mkdtemp(prefix="medcat-pages-"))
_was_src = _mn.SOURCE_DIR
try:
    _mn.SOURCE_DIR = _tmpd
    (_tmpd / "777.orig.pdf").write_bytes(PDF12)
    _pr = {"id": 777, "importKind": "pdf"}
    _old = {"layout": {"pages": [[0, 0, 400, 600]], "boxes": {"3": [{"page": 0, "slots": []}]}}}
    check(_mn._pdf_page_parts(_pr, _old, {})[0] == [],
          "раскладка без мест строк (старые правила) — страниц не берём: слой не отсеять")
    _dt = {"layout": {"pages": [[0, 0, 400, 600]],
                      "boxes": {"3": [{"page": 0, "slots": [[40, 500, 200, 10, "", 40, 5, 1]]}]}}}
    _names, _anch = _mn._pdf_page_parts(_pr, _dt, {})
    check(_names == ["pdfpage/0000.png"] and _anch.get("pdfpage/0000.png") == [3],
          "страница PDF-проекта идёт в разбор надписей, якорь — её первый абзац: %s %s" % (_names, _anch))
    _png = _mn._pdf_page_png(777, 0)
    check(bool(_png) and _imp.figure_tag(_png)[1:] == (0.0, 0.0, 1.0, 1.0),
          "отрисованная страница помечена «рисунок во весь лист»")
    _rec2 = {"w": 100, "h": 100, "blocks": [{"box": [10, 10, 30, 20]}, {"box": [60, 60, 90, 70]}]}
    check(_mn._mark_figure_blocks(_rec2, _png, {0: [(0.05, 0.05, 0.4, 0.4)]}) == 1
          and _rec2["blocks"][0].get("skip") == "figure" and not _rec2["blocks"][1].get("skip"),
          "блок страницы внутри вырезанного рисунка не читается второй раз")
    _scan_raster = {"word/media/image1.png": _imp._png_with_index(_Img.new("L", (10, 10), 255), 0)}
    check(_mn._pdf_page_parts(_pr, _dt, _scan_raster)[0] == [],
          "страница, уже лежащая картинкой (скан), второй раз не берётся")
finally:
    _mn.SOURCE_DIR = _was_src
    shutil.rmtree(str(_tmpd), ignore_errors=True)

print("=== 12к. Две надписи одной строки pypdf и подписи с разных концов листа ===")
# Боевой случай (проект 14): pypdf склеил «making» из рамки посреди схемы
# и «DO NOT JUST FOCUS» у левого края в «makingDO NOT JUST FOCUS» (базовые
# линии разошлись на 1.8 пт), а заголовки схемы с разных концов листа
# текстовые правила склеили в один абзац.
P12K = (_fx_body(GOOD, top=560)
        + [("raw", "BT /F1 8 Tf 1 0 0 1 250 300 Tm {HEX:making:HEX} Tj ET "
                   "BT /F1 8 Tf 1 0 0 1 40 301.5 Tm {HEX:СЛЕВА ПОДПИСЬ:HEX} Tj ET"),
           ("t", 40, 420, 8, "ЦЕЛИ ЛЕЧЕНИЯ"),
           ("t", 260, 470, 8, "ТОЧНОСТЬ ДИАГНОСТИКИ"),
           ("t", 40, 380, 8, "РИСКИ ОСЛОЖНЕНИЙ")])
pg12k, gm12k = textcount._pdf_pages_geom(make_pdf([P12K]), [])
res12k = pdftext.clean(pg12k, geom=gm12k)
paras12k = [it[1] for it in res12k["items"] if it[0] == "p"]
place12k = {it[1]: it[2] for it in res12k["items"] if it[0] == "p"}
check(not any("makingСЛЕВА" in t or ("making" in t and "СЛЕВА" in t) for t in paras12k),
      "надписи одной строки pypdf с разных концов листа — разные абзацы: %s"
      % [t for t in paras12k if "making" in t or "СЛЕВА" in t])
lft = [b for t, b in place12k.items() if "СЛЕВА" in t]
check(bool(lft) and bool(lft[0]) and abs(lft[0][0]["slots"][0][0] - 40) < 1,
      "у левой надписи — своё место у левого края")
for lab in ("ЦЕЛИ ЛЕЧЕНИЯ", "ТОЧНОСТЬ ДИАГНОСТИКИ", "РИСКИ ОСЛОЖНЕНИЙ"):
    check(lab in paras12k, "подпись «%s» — своим абзацем: %s" % (lab, paras12k))
# Перенос абзаца наверх соседней колонки по-прежнему склеивается.
COL = ["Первая колонка текста кончается здесь, а предложение идёт",
       "дальше и продолжается наверху второй колонки этой страницы"]
_L = "Строка колонки текста с обычными словами для ширины"
P12K2 = ([("t", 40, 560 - 12 * k, 10, _L) for k in range(4)] + [("t", 40, 512, 10, COL[0])]
         + [("t", 330, 560, 10, COL[1])] + [("t", 330, 548 - 12 * k, 10, _L) for k in range(4)])
pgc, gmc = textcount._pdf_pages_geom(make_pdf([P12K2], size=(700, 600)), [])
parc = [it[1] for it in pdftext.clean(pgc, geom=gmc)["items"] if it[0] == "p"]
check(any(COL[0].split()[0] in t and "второй колонки" in t for t in parc),
      "переход абзаца наверх следующей колонки — один абзац: %s" % parc)

print("=== 12л. Цвет букв — из самого PDF, а не по картинке страницы ===")
# Замер по картинке на мелком кегле (4 пт на длинной странице) давал серый
# вместо чёрного: сглаживание. Оператор заливки знает цвет точно; у текста
# в режиме «невидимый» (Tr 3 — слой распознавания под снимком) цвета нет.
P12L = [("raw", "BT /F1 10 Tf 0.2 0.3 0.9 rg 1 0 0 1 40 500 Tm {HEX:Синяя подпись схемы:HEX} Tj ET"),
        ("raw", "q 0 0 0 1 k BT /F1 10 Tf 1 0 0 1 40 400 Tm {HEX:Чёрная по CMYK:HEX} Tj ET Q"),
        ("raw", "BT /F1 10 Tf 3 Tr 1 0 0 1 40 300 Tm {HEX:Невидимый слой:HEX} Tj ET")]
pgl, gml = textcount._pdf_pages_geom(make_pdf([P12L]), [])
resl = pdftext.clean(pgl, geom=gml)
col = {it[1]: ((it[2] or [{}])[0].get("slots") or [[None] * 10])[0] for it in resl["items"] if it[0] == "p"}
def _c(t):
    sl = next((v for k, v in col.items() if k.startswith(t)), None)
    return sl[9] if sl and len(sl) > 9 else "нет"
check(_c("Синяя") and all(abs(a - b) < 0.01 for a, b in zip(_c("Синяя"), (0.2, 0.3, 0.9))),
      "цвет заливки rg доехал до места строки: %s" % (_c("Синяя"),))
check(_c("Чёрная") and max(_c("Чёрная")) < 0.01, "CMYK k=1 — чёрный: %s" % (_c("Чёрная"),))
check(_c("Невидимый") is None, "у невидимого текста цвета нет: %s" % (_c("Невидимый"),))
check(layout_pdf._color_of([0.2, 0.3, 0.9]) == (0.2, 0.3, 0.9) and layout_pdf._color_of(None) is None,
      "выгрузка берёт цвет строки из разбора")

print("=== 12м. Находки критика: метка вырезки, порядок справа налево, Tj за Tj ===")
from PIL import Image as _PImg
_b = io.BytesIO(); _PImg.new("RGB", (4, 4), "red").save(_b, "PNG"); _raw = _b.getvalue()
_tg = _imp.tag_figure(_raw, 2, [0.1, 0.2, 0.3, 0.4])
check(_imp.untag_figure(_tg) == _raw and _mn._same_image(_tg, hashlib.sha1(_raw).hexdigest()),
      "картинка с меткой места — та же, что без неё (пересборка не теряет разбор надписей)")
_lv = layout_pdf._bidi_levels("שלום 2024.")
check(_lv[:4] == [1, 1, 1, 1] and _lv[5:9] == [2, 2, 2, 2],
      "цифры внутри письма справа налево идут слева направо: %s" % _lv)
check(layout_pdf._bidi_levels("COVID-19 מחלה", base_rtl=True)[0] == 2,
      "основа строки — от абзаца, а не от первой буквы строки")
check(not layout_pdf._shaped_script({0: "Обычный текст‏"}),
      "метка направления (RLM) — не повод печатать книгу картинками")
# Два Tj подряд в одном BT: конец строки — по ОБОИМ операторам.
P12M = [("raw", "BT /F1 10 Tf 1 0 0 1 40 500 Tm {HEX:Первая часть :HEX} Tj "
                "{HEX:вторая часть:HEX} Tj ET")]
pgm, gmm = textcount._pdf_pages_geom(make_pdf([P12M]), [])
_ln = [l for l in (gmm[0] or {}).get("lines", []) if l]
_want = 40 + len("Первая часть вторая часть") * 5.0
check(_ln and abs(_ln[0][3] - _want) < 1.0,
      "Tj вслед за Tj того же BT — конец строки по обоим: %s (по метрикам %s)"
      % (_ln[0][3] if _ln else None, _want))

P12M2 = (_fx_body(GOOD, top=560)
         + [("raw", "BT /F1 10 Tf 0 1 -1 0 300 100 Tm {HEX:Всего :HEX} Tj {HEX:случаев болезни:HEX} Tj ET")])
pgm2, gmm2 = textcount._pdf_pages_geom(make_pdf([P12M2]), [])
_rot = list(((gmm2[0] or {}).get("rot") or {}).values())
_end = _rot[0]["end"] if _rot else None
check(_end and abs(_end[0] - 300) < 1 and abs(_end[1] - (100 + len("Всего случаев болезни") * 5.0)) < 1.5,
      "повёрнутая строка из двух Tj — путь до конца второго: %s" % (_end,))

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
