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

print("=== 4. Начертание — относительно основного в документе ===")
check(pdftext._rel_style("b", "b") == "" and pdftext._rel_style("bi", "b") == "i",
      "весь текст книги, помеченный Bold, остаётся обычным, а курсив в нём виден")
check(pdftext._rel_style("b", "") == "b", "а в обычном документе полужирный виден")

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

print("\n" + ("ALL OK" if not fail else "FAILED: %d" % len(fail)))
sys.exit(1 if fail else 0)
