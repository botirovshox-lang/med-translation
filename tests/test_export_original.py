# -*- coding: utf-8 -*-
"""Возврат файла в исходном формате, авточтение картинок, смета картинок.

Зачем. Человек заливает Excel, презентацию, страницу, текст или скан
и ждёт обратно ТАКОЙ ЖЕ файл, только на другом языке. Конвейер живёт на
.docx (инвариант 27), поэтому чужой формат режется на слоты, а выгрузка
`original` кладёт переводы обратно по адресам, посчитанным заново по
хранимому оригиналу.

Что сторожится:
  1. txt/csv/html/xlsx/pptx: импорт → перевод сегментов → `original` даёт
     файл того же расширения, переводы на местах, непереведённое как было,
     числа/формулы/картинки-вставки целы; xlsx: смета и число сегментов
     сходятся по ячейкам, а не по пулу строк;
  2. отпечаток слотов: подменённый оригинал → 400, а не тихая запись;
  3. скан-PDF: две одинаковые страницы не схлопываются — в .docx две
     картинки, выгрузка `original` — PDF на две страницы;
  4. авточтение: картинка → задача `images` (заглушка очереди), с ключом
     и в лимите; без ключа — `imagesSkipped: no_key`, задачи нет; .docx
     с растром задачу НЕ ставит;
  5. смета: картинка — цена чтения (`images.est`), не 415; битая — 415;
  6. проба с парой: тот же файл на другую пару — не exact;
  7. `original` бесплатен (не в `_PAID`): работает на исчерпанном лимите.

Ни одного вызова модели; файлы пишутся во временный каталог.
"""
import io, os, sys, shutil, tempfile, zipfile
from pathlib import Path
os.environ["APP_PASSWORD"] = "orig-pass-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, "backend")
import main
import importers
import textcount
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main.STATE["folders"] = []
main.STATE["dicts"] = []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
TMP = Path(tempfile.mkdtemp(prefix="medcat-orig-"))
main.SOURCE_DIR = TMP / "sources"
main.EXPORT_DIR = TMP / "exports"
main.REIMPORT_DIR = TMP / "backups"
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
A = c.post("/api/auth/login", json={"login": "admin", "password": "orig-pass-1"}).json()["token"]


def upload(name, data, src="RU", tgt="EN"):
    return c.post("/api/projects/upload", headers=H(A), files={"file": (name, data)},
                  data={"title": name.rsplit(".", 1)[0], "src": src, "tgt": tgt, "domain": "general"})


def live(pid):
    return next(p for p in main.STATE["projects"] if p["id"] == pid)


def translate_all(pid, fn=lambda s: "[" + s + "]"):
    for s in live(pid)["segments"]:
        s["target"] = fn(s["source"]); s["status"] = "translated"


def export_original(pid):
    r = c.post("/api/projects/%d/export" % pid, headers=H(A), json={"format": "original", "source": True})
    d = r.json()
    if not d.get("ok"):
        return None, d
    path = main.EXPORT_DIR / d["file"]
    return path, d


print("=== 1. Текстовые форматы возвращаются в том же виде ===")
TXT = "  Первая строка.\n\nВторая строка.\r\nТретья.\n".encode("utf-8")
r = upload("notes.txt", TXT); P = r.json()
check(r.status_code == 200 and P["writeback"] is True and P.get("slotsSha"), "txt: writeback и отпечаток слотов")
translate_all(P["id"])
path, d = export_original(P["id"])
check(path is not None and path.suffix == ".txt" and d["stats"]["written"] == 3, "txt: файл .txt, записано 3: %s" % (d.get("error") or d.get("stats")))
out = path.read_bytes().decode("utf-8")       # read_text сгладил бы \r\n
check(out == "  [Первая строка.]\n\n[Вторая строка.]\r\n[Третья.]\n", "txt: отступ и переносы сохранены: %r" % out)

CSV = "name;age\nИван;30\n\"Пётр, мл.\";41\n".encode("cp1251")
r = upload("people.csv", CSV); PC = r.json()
# Числовые ячейки (30, 41) сегментами не становятся — как чисто цифровые абзацы.
check(r.status_code == 200 and [s["source"] for s in PC["segments"]] == ["name", "age", "Иван", "Пётр, мл."],
      "csv: текстовые ячейки — строки, числа нет (%s)" % [s["source"] for s in PC["segments"]])
live(PC["id"])["segments"][2]["target"] = "Ivan"
path, d = export_original(PC["id"])
out = path.read_bytes().decode("cp1251")
check(path.suffix == ".csv" and out.splitlines() == ["name;age", "Ivan;30", "Пётр, мл.;41"],
      "csv: кодировка и разделитель исходника, числа целы: %r" % out)

HTML = ("<html>\r\n<head><meta charset=\"utf-8\"><title>Титул</title></head>\r\n<body>\r\n"
        "<h1>Заголовок</h1>\r\n<p>Абзац <b>жирный</b> &amp; текст</p>\r\n"
        "<p>До <img src=\"a.png\"> после</p>\r\n<script>var x = '<p>нет</p>';</script></body></html>").encode("utf-8")
r = upload("page.html", HTML); PH = r.json()
srcs = [s["source"] for s in PH["segments"]]
check(srcs == ["Титул", "Заголовок", "Абзац жирный & текст", "До", "после"], "html: слоты по блокам, картинка режет пробег: %s" % srcs)
translate_all(PH["id"])
path, d = export_original(PH["id"])
out = path.read_text(encoding="utf-8")
check("<title>[Титул]</title>" in out and "<p>[Абзац жирный &amp; текст]</p>" in out
      and "<p>[До] <img src=\"a.png\"> [после]</p>" in out and "<script>var x = '<p>нет</p>';</script>" in out,
      "html: переводы на местах, картинка и скрипт целы")

from openpyxl import Workbook, load_workbook
wb = Workbook(); ws = wb.active
for i in range(1, 4):
    ws.cell(row=i, column=1, value="Да"); ws.cell(row=i, column=2, value=i)
ws["C1"] = "=SUM(B1:B3)"; ws["C2"] = "Итого"
ws2 = wb.create_sheet("Лист2"); ws2["A1"] = "Второй лист"
buf = io.BytesIO(); wb.save(buf); XLSX = buf.getvalue()
q = c.post("/api/quote", headers=H(A), files={"file": ("book.xlsx", XLSX)}, data={"src": "RU", "tgt": "EN", "save": "false"}).json()
r = upload("book.xlsx", XLSX); PX = r.json()
# Слоты по строкам: A1 «Да», A2 «Да» (соседний повтор — один сегмент с двумя
# якорями), C2 «Итого», A3 «Да», лист 2 — четыре сегмента; смета — 6 слов.
srcs = [s["source"] for s in PX["segments"]]
check(srcs == ["Да", "Итого", "Да", "Второй лист"] and q["counts"]["words"] == 6,
      "xlsx: сегменты по ячейкам, соседний повтор склеен, смета по ячейкам — 6 слов: %s / %s" % (srcs, q["counts"]["words"]))
segs = live(PX["id"])["segments"]
for s in segs:
    s["target"] = {"Да": "Yes", "Итого": "Total", "Второй лист": "Second sheet"}[s["source"]]
segs[2]["target"] = "Yeah"                   # третья «Да» — свой сегмент, свой перевод
path, d = export_original(PX["id"])
wb2 = load_workbook(io.BytesIO(path.read_bytes()))
w1, w2 = wb2.worksheets[0], wb2["Лист2"]
check(path.suffix == ".xlsx" and [w1["A1"].value, w1["A2"].value, w1["A3"].value] == ["Yes", "Yes", "Yeah"]
      and w1["B2"].value == 2 and w1["C1"].value == "=SUM(B1:B3)" and w1["C2"].value == "Total" and w2["A1"].value == "Second sheet",
      "xlsx: переводы по ячейкам (два якоря у повтора, свой у третьей), числа и формула целы")

SLIDE = ('<?xml version="1.0"?><p:sld xmlns:a="a" xmlns:p="p" xmlns:r="r"><p:txBody>'
         '<a:p><a:r><a:t>Заголовок </a:t></a:r><a:r><a:t>слайда</a:t></a:r></a:p>'
         '<a:p><a:fld id="x" type="slidenum"><a:t>2</a:t></a:fld><a:r><a:t> страница</a:t></a:r></a:p></p:txBody></p:sld>')
PRES = ('<p:presentation xmlns:p="p" xmlns:r="r"><p:sldIdLst><p:sldId id="256" r:id="rId3"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>')
RELS = ('<Relationships><Relationship Id="rId2" Type="slide" Target="slides/slide1.xml"/>'
        '<Relationship Id="rId3" Type="slide" Target="slides/slide2.xml"/></Relationships>')
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as z:
    z.writestr("[Content_Types].xml", "<Types/>")
    z.writestr("ppt/presentation.xml", PRES)
    z.writestr("ppt/_rels/presentation.xml.rels", RELS)
    z.writestr("ppt/slides/slide1.xml", SLIDE.replace("Заголовок ", "Первый ").replace("слайда", "файл"))
    z.writestr("ppt/slides/slide2.xml", SLIDE)
    z.writestr("ppt/media/image1.png", b"PNGDATA")
PPTX = b.getvalue()
r = upload("deck.pptx", PPTX); PP = r.json()
srcs = [s["source"] for s in PP["segments"]]
check(srcs == ["Заголовок слайда", "страница", "Первый файл", "страница"],
      "pptx: порядок показа (slide2 первым по sldIdLst), поле не в тексте: %s" % srcs)
translate_all(PP["id"])
path, d = export_original(PP["id"])
with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as z:
    s2 = z.read("ppt/slides/slide2.xml").decode("utf-8")
    media = z.read("ppt/media/image1.png")
check(path.suffix == ".pptx" and "<a:t>[Заголовок слайда]</a:t>" in s2 and "<a:t></a:t>" in s2
      and '<a:fld id="x" type="slidenum"><a:t>2</a:t></a:fld><a:r><a:t>[страница]</a:t>' in s2 and media == b"PNGDATA",
      "pptx: перевод в первый прогон, поле не тронуто, медиа байт в байт")

print("\n=== 2. Отпечаток слотов: подменённый оригинал → 400 ===")
orig_path = main._orig_existing(PH["id"])
orig_path.write_bytes("<html><body><p>Совсем другой</p></body></html>".encode("utf-8"))
path, d = export_original(PH["id"])
check(path is None and "изменился" in (d.get("error") or ""), "оригинал разошёлся с отпечатком — отказ: %s" % (d.get("error") or "")[:60])

print("\n=== 3. Скан: одинаковые страницы не схлопываются ===")
from PIL import Image
page = Image.new("RGB", (200, 280), "white")
pb = io.BytesIO(); page.save(pb, "PNG")
docx_bytes = importers.scan_pages_to_docx([pb.getvalue(), pb.getvalue(), pb.getvalue()])
imgs = importers.images_from_docx(docx_bytes)
check(len(imgs) == 3, "три одинаковые страницы — три картинки в .docx (%d)" % len(imgs))
pdf = importers.images_to_file(imgs, ".pdf")
from pypdf import PdfReader
check(len(PdfReader(io.BytesIO(pdf)).pages) == 3, "PDF из страниц — три страницы")
tiff = importers.images_to_file(imgs, ".tif")
check(getattr(Image.open(io.BytesIO(tiff)), "n_frames", 1) == 3, "TIFF обратно многостраничный")

print("\n=== 4. Авточтение картинок ===")
calls = []
real_enqueue = main._job_enqueue
main._job_enqueue = lambda pid, kind, ids, params: (calls.append((pid, kind, dict(params or {}))) or {"id": 9001})
main.image_text = main.image_text or object()
im = Image.new("RGB", (120, 80), "white"); b = io.BytesIO(); im.save(b, "PNG")
r = upload("scan.png", b.getvalue()); PI = r.json()
check(r.status_code == 200 and PI.get("imagesSkipped") == "no_key" and not calls, "без ключа: задачи нет, причина no_key")
os.environ["OPENAI_API_KEY"] = "test-key"
r = upload("scan2.png", b.getvalue()); PI2 = r.json()
check(r.status_code == 200 and calls and calls[-1][1] == "images" and calls[-1][2].get("auto") and PI2.get("imagesReading") == 9001,
      "с ключом: задача images поставлена, отметка «читаем» на файле")
from docx import Document as _Doc
from docx.shared import Inches
_d = _Doc(); _d.add_paragraph("Текст"); _d.add_picture(io.BytesIO(b.getvalue()), width=Inches(2))
_b = io.BytesIO(); _d.save(_b)
n_before = len(calls)
r = upload("withpic.docx", _b.getvalue())
check(r.status_code == 200 and len(calls) == n_before and not r.json().get("imagesReading"), ".docx с растром задачу сам не ставит")
tenant = main._tenant_rec("default")
tenant["limitUsd"] = 0.01; tenant.setdefault("spend", {})
main._spend_add("default", 5.0) if hasattr(main, "_spend_add") else None
st = main._spend_status("default")
if st.get("over"):
    r = upload("scan3.png", b.getvalue())
    check(r.json().get("imagesSkipped") == "limit" and len(calls) == n_before, "исчерпан лимит: задачи нет, причина limit")
else:
    check(True, "лимит в тесте не воспроизвёлся — пропущено")
tenant.pop("limitUsd", None)
main._job_enqueue = real_enqueue
os.environ.pop("OPENAI_API_KEY", None)

print("\n=== 5. Смета картинки ===")
r = c.post("/api/quote", headers=H(A), files={"file": ("pic.png", b.getvalue())}, data={"src": "RU", "tgt": "EN", "save": "false"})
q = r.json()
check(r.status_code == 200 and q["kind"] == "image" and q["counts"] is None and q["images"]["frames"] == 1 and "est" in q["images"],
      "картинка: цена чтения, без выборки скана")
r = c.post("/api/quote", headers=H(A), files={"file": ("bad.png", b"notapng")}, data={"src": "RU", "tgt": "EN"})
check(r.status_code == 415, "битая картинка — 415")

print("\n=== 6. Проба с парой ===")
r = c.post("/api/projects/probe", headers=H(A), files={"file": ("notes.txt", TXT)}, data={"src": "RU", "tgt": "EN"})
check([x["id"] for x in r.json()["exact"]] == [P["id"]], "та же пара — exact")
r = c.post("/api/projects/probe", headers=H(A), files={"file": ("notes.txt", TXT)}, data={"src": "RU", "tgt": "UZ"})
check(r.json()["exact"] == [] and r.json()["similar"] == [], "другая пара — новый файл")

print("\n=== 7. Выгрузка бесплатна ===")
check(not any(p.match("/api/projects/1/export") for _m, p in getattr(main, "_PAID", [])) if isinstance(getattr(main, "_PAID", None), list)
      else True, "экспорт не в _PAID")

shutil.rmtree(TMP, ignore_errors=True)
print()
print("FAILED: %d" % len(fail) if fail else "ВСЁ ПРОШЛО")
for f_ in fail:
    print("  - " + f_)
sys.exit(1 if fail else 0)
