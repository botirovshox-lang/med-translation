"""Экспорт «как в оригинале»: перевод подставляется в исходный файл.

Собрать документ, похожий на исходник, из одних сегментов нельзя — в них нет
ни шрифта, ни картинок. Поэтому исходник хранится, а выгрузка подменяет текст
в НЁМ. Отсюда всё, что здесь проверяется:

  1. якорь сегмента — номер абзаца, и список абзацев обязан быть ПОЛНЫМ:
     выброси из него пустые строки, и переводы поедут по всему документу;
  2. соседние одинаковые абзацы — один сегмент, но ДВА якоря: иначе второй
     останется на языке оригинала;
  3. в поля (номер страницы в оглавлении) и в скрытый текст писать нельзя —
     номер считает Word, а скрытого не видит никто;
  4. непереведённый сегмент оставляет абзац как есть — подставить туда пусто
     значит стереть оригинал и выдать это за перевод;
  5. привязка исходника к готовому проекту идёт ПО ТЕКСТУ и не имеет права
     сажать перевод на чужой абзац: чужой файл отклоняется по числу совпадений;
  6. подменённый под картой файл отклоняется — номера абзацев уехали.

Ни одного вызова модели и ни одного обращения к сети: собирается настоящий
.docx (python-docx) в отдельном временном каталоге.
"""
import os, sys, shutil, tempfile
from pathlib import Path

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


TMP = Path(tempfile.mkdtemp(prefix="medcat-layout-"))
main.SOURCE_DIR = TMP / "sources"
main.EXPORT_DIR = TMP / "exports"
main.EXPORT_DIR.mkdir(parents=True)

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _run(p, text, bold=False):
    r = p.add_run(text)
    if bold:
        r.bold = True          # False писало бы <w:b w:val="0"/> — тоже отметку
    return r


def build_source() -> bytes:
    """Документ со всеми случаями сразу: обычный абзац, абзац из двух прогонов
    с разным оформлением, соседний повтор, чисто цифровая строка и строка
    оглавления с полем PAGEREF."""
    doc = Document()
    doc.add_paragraph("Первый абзац документа.")           # 0
    p = doc.add_paragraph()                                 # 1: два прогона
    _run(p, "Туберкулёз", bold=True)
    _run(p, " — инфекционное заболевание.")
    doc.add_paragraph("Повтор строки.")                     # 2
    doc.add_paragraph("Повтор строки.")                     # 3: тот же сегмент
    doc.add_paragraph("14")                                 # 4: только цифры
    doc.add_paragraph("Абзац без перевода.")                # 5

    toc = doc.add_paragraph()                               # 6: оглавление
    _run(toc, "ГЛАВА ПЕРВАЯ")
    tab = OxmlElement("w:r")
    tab.append(OxmlElement("w:tab"))
    toc._p.append(tab)
    for kind, payload in (("begin", None), (None, " PAGEREF _Toc1 \\h "),
                          ("separate", None), (None, "85"), ("end", None)):
        r = OxmlElement("w:r")
        if kind:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), kind)
            r.append(fld)
        elif payload.startswith(" PAGEREF"):
            instr = OxmlElement("w:instrText")
            instr.text = payload
            r.append(instr)
        else:
            t = OxmlElement("w:t")
            t.text = payload
            r.append(t)
        toc._p.append(r)

    path = TMP / "source.docx"
    doc.save(str(path))
    return path.read_bytes()


CONTENT = build_source()
paras = main._docx_paragraphs(CONTENT)
units = main._docx_units(paras)

check(len(paras) == 7, "разбор видит ВСЕ абзацы, включая цифровой (%d)" % len(paras))
check([t for t, _ in units] == [
    "Первый абзац документа.",
    "Туберкулёз — инфекционное заболевание.",
    "Повтор строки.",
    "Абзац без перевода.",
    "ГЛАВА ПЕРВАЯ85",
], "в сегменты идут не все абзацы: цифровая строка и соседний повтор отсеяны")
check(units[2][1] == [2, 3], "соседний повтор — один сегмент и ДВА якоря")

# ── проект как после импорта ────────────────────────────────────────
project = {"id": 1, "title": "Тест", "src": "RU", "tgt": "EN", "domain": "medical",
           "segments": [{"id": i + 1, "source": t, "target": "", "status": "new"}
                        for i, (t, _idx) in enumerate(units)]}
pairs = [[i, u + 1] for u, (_t, idxs) in enumerate(units) for i in idxs]
main._store_source_docx(project, CONTENT, "source.docx", pairs, len(paras))
check(project["sourceDocx"]["segments"] == 5 and project["sourceDocx"]["paras"] == 7,
      "отметка в проекте называет и абзацы, и сегменты")

docx_path, map_path = main._source_paths(1)
check(docx_path.exists() and map_path.exists(), "исходник и карта легли рядом")
check("pairs" not in project["sourceDocx"],
      "карта НЕ попала в проект: state.json переписывается на каждую правку")

TR = {1: "First paragraph of the document.",
      2: "Tuberculosis is an infectious disease.",
      3: "Repeated line.",
      5: "CHAPTER ONE85"}          # перевод несёт номер страницы, как и сегмент
for s in project["segments"]:
    s["target"] = TR.get(s["id"], "")

out, stats = main._generate_export(project, "docx_layout")
check(out.name.endswith(" 1в1.docx"),
      "имя файла отличает 1в1 от обычного docx: " + out.name)

res = Document(str(out))
all_p = res.element.body.findall(".//" + qn("w:p"))
text = [main._docx_clean("".join(t.text for t in p.iter(qn("w:t")) if t.text))
        for p in all_p]

check(len(all_p) == 7, "число абзацев не изменилось")
check(text[0] == "First paragraph of the document.", "обычный абзац переведён")
check(text[1] == "Tuberculosis is an infectious disease.",
      "абзац из двух прогонов переведён целиком: " + text[1])
check(text[2] == "Repeated line." and text[3] == "Repeated line.",
      "перевод встал в ОБА абзаца повтора")
check(text[4] == "14", "цифровая строка не тронута")
check(text[5] == "Абзац без перевода.",
      "непереведённый сегмент оставил оригинал, а не пустоту")
check(text[6] == "CHAPTER ONE85",
      "оглавление: переведён заголовок, номер страницы остался полем: " + text[6])
check(stats["trimmed"] == 1,
      "номер страницы снят с ПЕРЕВОДА, а не написан вторым: trimmed=%s" % stats["trimmed"])
check(stats["written"] == 5 and stats["untranslated"] == 1,
      "отчёт называет и написанное, и непереведённое: %s" % stats)
check(stats["merged"] == 1,
      "склейка разного оформления внутри абзаца посчитана: merged=%s" % stats["merged"])

# Перевод ушёл в самый длинный прогон, а не в первый (жирное «Туберкулёз»)
holders = [r for r in all_p[1].iter(qn("w:r"))
           if r.find(qn("w:t")) is not None and (r.find(qn("w:t")).text or "")]


def _is_bold(r):
    rpr = r.find(qn("w:rPr"))
    return rpr is not None and rpr.find(qn("w:b")) is not None


check(len(holders) == 1 and not _is_bold(holders[0]),
      "перевод ушёл в длинный обычный прогон, а не в жирный — "
      "абзац не стал жирным целиком")

# ── привязка исходника к готовому проекту ───────────────────────────
old = {"id": 2, "title": "Старый", "src": "RU", "tgt": "EN", "domain": "medical",
       "segments": [{"id": i + 1, "source": t, "target": "x", "status": "translated"}
                    for i, (t, _idx) in enumerate(units)]}
got, matched = main._map_source_to_segments(units, old["segments"])
check(matched == len(old["segments"]) and got == pairs,
      "тот же файл садится на существующий проект без потерь (%d из %d)"
      % (matched, len(old["segments"])))

alien = [{"id": i + 1, "source": "совсем другой текст %d" % i, "target": ""}
         for i in range(5)]
_p2, matched_alien = main._map_source_to_segments(units, alien)
check(matched_alien == 0, "чужой файл не садится ни на один сегмент")

# Сдвиг: сегмент в середине переписан — остальные обязаны сесть на свои места
shifted = [dict(s) for s in old["segments"]]
shifted[2]["source"] = "строка, которой в файле нет"
_p3, matched_shift = main._map_source_to_segments(units, shifted)
check(matched_shift == 4,
      "пропавшая строка не сдвигает остальные: %d из 5" % matched_shift)

# ── подменённый под картой файл ─────────────────────────────────────
doc2 = Document()
doc2.add_paragraph("Другой документ.")
doc2.save(str(docx_path))
try:
    main._generate_export(project, "docx_layout")
    check(False, "подменённый исходник обязан быть отвергнут")
except main.HTTPException as e:
    check("карт" in str(e.detail), "подменённый исходник отвергнут: " + str(e.detail))

# ── чужой файл под тем же номером ───────────────────────────────────
# Номера проектов переиспользуются (id = max + 1), поэтому файл удалённого
# проекта мог бы достаться новому с тем же номером. Отметка в проекте — часть
# опознания: нет её — нет и исходника, чей бы файл ни лежал на диске.
no_mark = dict(project)
no_mark.pop("sourceDocx")
try:
    main._generate_export(no_mark, "docx_layout")
    check(False, "проект без отметки не имеет права взять чужой файл с диска")
except main.HTTPException as e:
    check("не приложен" in str(e.detail),
          "проект без отметки исходника не берёт: " + str(e.detail))

# ── без исходника формата просто нет ────────────────────────────────
docx_path.unlink()
map_path.unlink()
check(main._load_source_map(1) is None, "карта без файла не читается")
try:
    main._generate_export(project, "docx_layout")
    check(False, "без исходника экспорт 1в1 обязан отказать")
except main.HTTPException as e:
    check("не приложен" in str(e.detail), "отказ назван словами: " + str(e.detail))

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
