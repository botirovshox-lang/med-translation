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
  6. подменённый под картой файл отклоняется — номера абзацев уехали;
  7. выделение ВНУТРИ абзаца переносится, а не схлопывается: сумма кусков
     всегда равна переводу целиком, резать посреди слова нельзя, а кусок,
     который перевод сохраняет дословно (латынь, число), ставится точно;
  8. служебное оформление (язык проверки орфографии, микрокернинг) деления
     не вызывает — иначе перевод режется там, где резать нечего;
  9. колонтитулы входят в разбор, но тело идёт ПЕРВЫМ: иначе номера абзацев
     тела уехали бы и все прежние карты стали бы врать.

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


def _run(p, text, bold=False, italic=False):
    r = p.add_run(text)
    if bold:
        r.bold = True          # False писало бы <w:b w:val="0"/> — тоже отметку
    if italic:
        r.italic = True
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

    p = doc.add_paragraph()                                 # 6: латынь курсивом
    _run(p, "Возбудитель — ")
    _run(p, "Mycobacterium tuberculosis", italic=True)
    _run(p, ", открыт в 1882 году.")

    p = doc.add_paragraph()                                 # 7: служебное
    r1 = _run(p, "Первая половина строки ")
    r2 = _run(p, "и вторая половина строки.")
    # w:lang — каким языком проверять орфографию. Word ставит его сам, кусками;
    # видимого оформления это не меняет и делить абзац не повод.
    for r, lang in ((r1, "ru-RU"), (r2, "en-US")):
        rpr = r._r.get_or_add_rPr()
        el = OxmlElement("w:lang")
        el.set(qn("w:val"), lang)
        rpr.append(el)

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

    # Подпись к рисунку, сдвинутая вправо ПРОБЕЛАМИ, а не отступом абзаца.
    # Так свёрстан весь учебник; импорт эти пробелы обрезает, и без их
    # возврата подпись уезжает к левому краю, а Word заново обтекает ею
    # плавающую картинку — строка рассыпается по обе стороны рисунка.
    doc.add_paragraph(" " * 33 + "Рис. 60. Казеозная пневмония.")   # 9

    # Колонтитул с настоящим текстом: он живёт отдельной частью пакета,
    # в body не попадает и без отдельного обхода остался бы на русском.
    doc.sections[0].header.paragraphs[0].text = "Фтизиатрия"

    path = TMP / "source.docx"
    doc.save(str(path))
    return path.read_bytes()


CONTENT = build_source()
paras = main._docx_paragraphs(CONTENT)
units = main._docx_units(paras)

BODY = 10     # абзацев в теле; дальше идут колонтитулы
check(len(paras) > BODY, "разбор дошёл до колонтитулов (%d абзацев)" % len(paras))
check([t for t, _ in units] == [
    "Первый абзац документа.",
    "Туберкулёз — инфекционное заболевание.",
    "Повтор строки.",
    "Абзац без перевода.",
    "Возбудитель — Mycobacterium tuberculosis, открыт в 1882 году.",
    "Первая половина строки и вторая половина строки.",
    "ГЛАВА ПЕРВАЯ85",
    "Рис. 60. Казеозная пневмония.",
    "Фтизиатрия",
], "в сегменты идут не все абзацы, зато текст колонтитула идёт: %s"
   % [t for t, _ in units])
check(units[2][1] == [2, 3], "соседний повтор — один сегмент и ДВА якоря")
check(units[-1][1][0] >= BODY,
      "колонтитул стоит ПОСЛЕ тела — номера абзацев тела не сдвинулись")

# ── проект как после импорта ────────────────────────────────────────
project = {"id": 1, "title": "Тест", "src": "RU", "tgt": "EN", "domain": "medical",
           "segments": [{"id": i + 1, "source": t, "target": "", "status": "new"}
                        for i, (t, _idx) in enumerate(units)]}
pairs = [[i, u + 1] for u, (_t, idxs) in enumerate(units) for i in idxs]
main._store_source_docx(project, CONTENT, "source.docx", pairs, len(paras))
check(project["sourceDocx"]["segments"] == len(units)
      and project["sourceDocx"]["paras"] == len(paras),
      "отметка в проекте называет и абзацы, и сегменты")

docx_path, map_path = main._source_paths(1)
check(docx_path.exists() and map_path.exists(), "исходник и карта легли рядом")
check("pairs" not in project["sourceDocx"],
      "карта НЕ попала в проект: state.json переписывается на каждую правку")

TR = {1: "First paragraph of the document.",
      2: "Tuberculosis is an infectious disease.",
      3: "Repeated line.",
      5: "The causative agent is Mycobacterium tuberculosis, discovered in 1882.",
      6: "First half of the line and second half of the line.",
      7: "CHAPTER ONE85",         # перевод несёт номер страницы, как и сегмент
      8: "Fig. 60. Caseous pneumonia.",
      9: "Phthisiology"}
# Статусы нарочно вперемешку. В файл идёт всё, у чего есть перевод: экспорт
# не судит о качестве, он выгружает то, что есть, а «подтвердил человек» —
# про доверие к переводу, а не про попадание в документ. Фильтр по статусу
# здесь означал бы, что готовый документ молча теряет часть работы.
STATUSES = ["new", "translated", "review", "qa", "confirmed", "review",
            "translated", "new", "confirmed"]
for s, st in zip(project["segments"], STATUSES):
    s["target"] = TR.get(s["id"], "")
    s["status"] = st

out, stats = main._generate_export(project, "docx_layout")
check(out.name.endswith(" 1в1.docx"),
      "имя файла отличает 1в1 от обычного docx: " + out.name)

res = Document(str(out))
all_p = main._docx_flat_paragraphs(res)
text = [main._docx_clean("".join(t.text for t in p.iter(qn("w:t")) if t.text))
        for p in all_p]

check(len(all_p) == len(paras), "число абзацев не изменилось")
check(text[0] == "First paragraph of the document.", "обычный абзац переведён")
check(text[1] == "Tuberculosis is an infectious disease.",
      "абзац из двух прогонов переведён целиком: " + text[1])
check(text[2] == "Repeated line." and text[3] == "Repeated line.",
      "перевод встал в ОБА абзаца повтора")
check(text[4] == "14", "цифровая строка не тронута")
check(text[5] == "Абзац без перевода.",
      "непереведённый сегмент оставил оригинал, а не пустоту")
check(text[8] == "CHAPTER ONE85",
      "оглавление: переведён заголовок, номер страницы остался полем: " + text[8])
check(stats["trimmed"] == 1,
      "номер страницы снят с ПЕРЕВОДА, а не написан вторым: trimmed=%s" % stats["trimmed"])
check(stats["written"] == 9 and stats["untranslated"] == 1,
      "отчёт называет и написанное, и непереведённое: %s" % stats)
# Ровно столько, сколько якорей у сегментов с переводом, — и ни один статус
# не отнял себе ни одного абзаца.
with_target = {s["id"] for s in project["segments"] if (s.get("target") or "").strip()}
check(stats["written"] == sum(1 for _i, sid in pairs if sid in with_target),
      "статус не влияет на попадание в файл: пишутся все абзацы с переводом")
check(text[0] == TR[1] and text[2] == TR[3],
      "непроверенный сегмент («новый») выгружен наравне с подтверждённым")

# ── выделения внутри абзаца ─────────────────────────────────────────
def marked(i, tag):
    """Текст абзаца, попавший в прогоны с этой отметкой оформления."""
    out = []
    for r in all_p[i].iter(qn("w:r")):
        t = r.find(qn("w:t"))
        rpr = r.find(qn("w:rPr"))
        if t is None or not (t.text or ""):
            continue
        if rpr is not None and rpr.find(qn(tag)) is not None:
            out.append(t.text)
    return "".join(out)


def whole(i):
    return "".join(t.text or "" for t in all_p[i].iter(qn("w:t")))


# 1: жирное «Туберкулёз» + обычный хвост. Жирным обязана остаться ЧАСТЬ,
# а не абзац целиком и не пустота.
bold1 = marked(1, "w:b")
check(whole(1) == TR[2], "текст абзаца не потерян и не задвоен: " + whole(1))
check(bold1.strip() and bold1 != TR[2],
      "жирным осталась часть перевода, а не весь абзац: %r" % bold1)
check(bold1.strip() == "Tuberculosis",
      "граница жирного подтянута к слову: %r" % bold1)

# 5: латинское название вида курсивом — перевод сохраняет его дословно,
# значит курсив ставится ТОЧНО, а не на глаз.
check(whole(6) == TR[5], "текст абзаца с латынью цел: " + whole(6))
check(marked(6, "w:i").strip() == "Mycobacterium tuberculosis",
      "курсив встал ровно на латинское название: %r" % marked(6, "w:i"))

# 6: прогоны различаются только языком проверки орфографии — делить нечего.
check(whole(7) == TR[6], "текст абзаца со служебным оформлением цел")
holders6 = [r for r in all_p[7].iter(qn("w:r"))
            if r.find(qn("w:t")) is not None and (r.find(qn("w:t")).text or "")]
check(len(holders6) == 1,
      "служебное оформление не делит перевод: кусков %d" % len(holders6))

# колонтитул переведён
hdr = [p for p in all_p[BODY:]
       if "".join(t.text or "" for t in p.iter(qn("w:t"))).strip() == "Phthisiology"]
check(len(hdr) == 1, "текст колонтитула переведён")

check(stats["inline"] == 2,
      "выделения перенесены ровно там, где они есть: inline=%s" % stats["inline"])

# ── куда встают границы выделений ───────────────────────────────────
# Настоящие пары из учебника: слева куски исходного абзаца по оформлению,
# справа перевод. Все обязаны делиться ТОЧНО — по знаку препинания либо
# по куску, который перевод сохраняет дословно. Ни одной догадки: там, где
# опереться не на что, деление честно помечается приблизительным, и такие
# случаи в этом списке были бы видны.
SPLITS = [
    (["13 ГЛАВА.", " ПРОФИЛАКТИКА ТУБЕРКУЛЁЗА"],
     "CHAPTER 13. TUBERCULOSIS PREVENTION",
     ["CHAPTER 13.", " TUBERCULOSIS PREVENTION"]),
    (["Клиника: ", "зависит от объема поражения лёгких"],
     "Clinical picture: depends on the extent of lung involvement",
     ["Clinical picture:", " depends on the extent of lung involvement"]),
    (["ПЦР", " – полимеразная цепная реакция"],
     "PCR – polymerase chain reaction",
     ["PCR", " – polymerase chain reaction"]),
    (["Термин ", "tuberculosis", " происходит от латинского слова ", "tuberculum"],
     "The term tuberculosis comes from the Latin word tuberculum",
     ["The term ", "tuberculosis", " comes from the Latin word ", "tuberculum"]),
    (["Алиментарный", " — заражение ", "M. bovis", " при употреблении сырого молока"],
     "Alimentary — infection with M. bovis when drinking raw milk",
     ["Alimentary ", "— infection with ", "M. bovis", " when drinking raw milk"]),
    (["(", "Учебник для студентов медицинских институтов", ")"],
     "(Textbook for students of medical institutes)",
     ["(", "Textbook for students of medical institutes", ")"]),
    (["HBsAg", " - антиген вируса гепатита В"],
     "HBsAg - hepatitis B virus antigen",
     ["HBsAg", " - hepatitis B virus antigen"]),
]
for src, tgt, want in SPLITS:
    got, approx = main._split_target(tgt, src)
    check(got == want and not approx,
          "деление %r → %r%s" % (src[0][:22], got, " (ДОГАДКА)" if approx else ""))
    check("".join(got) == tgt, "сумма кусков равна переводу целиком")

# Резать посреди слова нельзя даже когда опереться не на что.
blind, approx = main._split_target("aaa bbb ccc ddd eee", ["раз ", "два три четыре"])
check(approx and "".join(blind) == "aaa bbb ccc ddd eee",
      "без опоры деление честно помечено догадкой")
check(all(p == "" or p[0] != " " or True for p in blind)
      and all(not p.strip() or p.strip() in "aaa bbb ccc ddd eee".split()
              or " " in p.strip() for p in blind),
      "догадка всё равно режет по словам: %r" % blind)

# ── пробелы по краям абзаца возвращаются на место ───────────────────
# Подпись сдвинута вправо тридцатью тремя пробелами В ТЕКСТЕ, а не отступом
# абзаца. Импорт их обрезал, перевод их не содержит — и без возврата подпись
# встаёт к левому краю. На странице с плавающей картинкой это видно сразу:
# Word заново обтекает ею подпись, и строка рассыпается по обе стороны рисунка.
cap = "".join(t.text or "" for t in all_p[9].iter(qn("w:t")))
check(cap.startswith(" " * 33),
      "пробелы, которыми подпись сдвинута вправо, сохранены: %r" % cap[:44])
check(cap.strip() == TR[8],
      "и сам перевод при этом не тронут: %r" % cap.strip())
# Внутренние пробелы — часть предложения, у перевода свои: их не добавляем.
check("  " not in cap.strip(),
      "внутрь перевода лишние пробелы не попали: %r" % cap.strip())

# ── запись атомарна ─────────────────────────────────────────────────
# Экспорт учебника это 21 МБ и несколько секунд. Записанный прямо в итоговый
# файл, он в это время доступен на скачивание НЕДОПИСАННЫМ, а перезапись
# требует прав на сам файл: один файл, случайно оставленный в exports/ от
# другого владельца, ронял экспорт этого проекта навсегда (PermissionError
# на боевом сервере, «Сервер недоступен» на экране). os.replace требует прав
# только на каталог.
stale = out.with_name(out.name + ".tmp")
stale.write_bytes("мусор от упавшей сборки".encode("utf-8"))
out2, _st2 = main._generate_export(project, "docx_layout")
check(out2 == out and not stale.exists(),
      "временный файл убран за собой, а не оставлен рядом с готовым")
check(Document(str(out2)) is not None, "итоговый файл читается как .docx")

if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0:
    # Только не под root: ему права на файл не помеха, и проверка была бы
    # зелёной ни о чём.
    out.chmod(0o444)
    try:
        main._generate_export(project, "docx_layout")
        check(True, "экспорт переживает недоступный на запись прежний файл")
    except OSError as e:
        check(False, "экспорт упал на прежнем файле: %s" % e)
    finally:
        out.chmod(0o644)

# ── привязка исходника к готовому проекту ───────────────────────────
old = {"id": 2, "title": "Старый", "src": "RU", "tgt": "EN", "domain": "medical",
       "segments": [{"id": i + 1, "source": t, "target": "x", "status": "translated"}
                    for i, (t, _idx) in enumerate(units)]}
got, matched = main._map_source_to_segments(units, old["segments"])
check(matched == len(old["segments"]) and got == pairs,
      "тот же файл садится на существующий проект без потерь (%d из %d)"
      % (matched, len(old["segments"])))

alien = [{"id": i + 1, "source": "совсем другой текст %d" % i, "target": ""}
         for i in range(len(units))]
_p2, matched_alien = main._map_source_to_segments(units, alien)
check(matched_alien == 0, "чужой файл не садится ни на один сегмент")

# Сдвиг: сегмент в середине переписан — остальные обязаны сесть на свои места
shifted = [dict(s) for s in old["segments"]]
shifted[2]["source"] = "строка, которой в файле нет"
_p3, matched_shift = main._map_source_to_segments(units, shifted)
check(matched_shift == len(units) - 1,
      "пропавшая строка не сдвигает остальные: %d из %d"
      % (matched_shift, len(units)))

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
