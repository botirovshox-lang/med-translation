"""Сегменты из «прочих» форматов: абзац не режется посреди фразы и слова.

Дефекты прежнего разбора, по одному на формат:
  * HTML — каждый инлайн-тег становился пробелом: «полн<b>ый</b>» → «полн ый»,
    «H<sub>2</sub>O» → «H 2 O», «<a>ссылка</a>.» → «ссылка .»; `&shy;`
    оставался невидимым знаком в сегменте;
  * PPTX — разрыв строки `<a:br/>` склеивал слова («ТашкентУзбекистан»);
  * SRT/VTT — реплика из двух строк давала два обрывка; строка времени
    с настройками VTT («align:start») и заголовок WEBVTT шли в текст;
  * RTF — абзацы делились по переводам строки ИСХОДНИКА (посреди фразы),
    кириллица `\\'e0` оставалась кодами, таблица шрифтов шла в текст;
  * PO — сегментом была строка файла вместе с `msgid "…"`, продолжения
    длинной строки — отдельными сегментами;
  * ODT/ODS/ODP — перевод строки на каждый тег: выделение внутри абзаца
    резало его на три сегмента.
TXT/MD не склеиваются намеренно: строка — слот обратной записи.
"""
import io, os, sys, zipfile
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import importers
import textcount

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== HTML: инлайн-теги не режут слова ===")
H = ("<html><body><p>Полн<b>ый</b> курс</p><p>Формула H<sub>2</sub>O и м<sup>2</sup>.</p>"
     "<p>См. <a href='#'>ссылку</a>. Насе&shy;комое и сверх<wbr>длинное</p>"
     "<p>Улица Ленина, 5<br>Ташкент</p><p>Абзац <b>жирный</b> текст.</p>"
     "<p>До<!-- комментарий --> после</p></body></html>")
got = [t for t, _r in importers.html_slots(H)]
check(got == ["Полный курс", "Формула H2O и м2.", "См. ссылку. Насекомое и сверхдлинное",
              "Улица Ленина, 5 Ташкент", "Абзац жирный текст.", "До после"], "слоты html: %s" % got)
tr = {i: "[%d]" % i for i in range(len(got))}
back = importers.write_back("x.html", H.encode("utf-8"), tr).decode("utf-8")
check("<p>[0]</p>" in back and "<p>[3]</p>" in back and back.count("[") == len(got),
      "обратная запись html кладёт перевод в каждый пробег")

print("=== PPTX: разрыв строки внутри абзаца — пробел ===")
SLIDE = ('<?xml version="1.0"?><p:sld xmlns:a="a" xmlns:p="p"><p:cSld><p:spTree><p:sp><p:txBody>'
         '<a:p><a:r><a:t>Ташкент</a:t></a:r><a:br/><a:r><a:t>Узбекистан</a:t></a:r></a:p>'
         '<a:p><a:r><a:t>насе­комое</a:t></a:r></a:p>'
         '</p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("ppt/slides/slide1.xml", SLIDE)
    z.writestr("[Content_Types].xml", "<Types/>")
PPTX = buf.getvalue()
got = [t for t, _a in importers.pptx_slots(PPTX)]
check(got == ["Ташкент Узбекистан", "насекомое"], "слоты pptx: %s" % got)
out = importers.write_back("s.pptx", PPTX, {0: "Toshkent O'zbekiston"})
with zipfile.ZipFile(io.BytesIO(out)) as z:
    xml = z.read("ppt/slides/slide1.xml").decode("utf-8")
check("<a:t>Toshkent O'zbekiston</a:t>" in xml and "<a:br/>" in xml and "Узбекистан" not in xml,
      "обратная запись pptx: перевод в первом прогоне, разрыв на месте, второй прогон пуст")

print("=== SRT / VTT: реплика — один кусок ===")
SRT = ("1\n00:00:01,000 --> 00:00:03,500\nМы ещё не знали, что\nвсё кончится иначе.\n\n"
       "2\n00:00:04,000 --> 00:00:05,000\n<i>Тишина.</i>\n\n")
check(textcount._blocks_from_plain(SRT, ".srt") == ["Мы ещё не знали, что всё кончится иначе.", "Тишина."],
      "srt: две строки реплики — одна фраза, номер и время сняты")
VTT = ("WEBVTT - Фильм\nKind: captions\n\nNOTE это заметка\nи её вторая строка\n\n"
       "intro\n00:01.000 --> 00:04.000 align:start position:10%\n<v Анна>Здравствуйте,\nколлеги!</v>\n\n"
       "00:05.000 --> 00:06.000\nДо встречи.\n")
check(textcount._blocks_from_plain(VTT, ".vtt") == ["Здравствуйте, коллеги!", "До встречи."],
      "vtt: шапка, NOTE, имя реплики, настройки и голос сняты: %s" % textcount._blocks_from_plain(VTT, ".vtt"))

print("=== RTF: абзацы по \\par, кириллица из кодов ===")
RTF = (r"{\rtf1\ansi\ansicpg1251\deff0{\fonttbl{\f0\fnil\fcharset204 Times New Roman;}}"
       r"{\colortbl;\red0\green0\blue0;}{\*\generator Riched20;}" "\n"
       r"\pard\f0\fs24 \'cf\'f0\'e8\'e2\'e5\'f2, \'ec\'e8\'f0! \'dd\'f2\'ee \'ee\'e4\'e8\'ed" "\n"
       r" \'e0\'e1\'e7\'e0\'f6 \'e8\'e7 \'e4\'e2\'f3\'f5 \'f1\'f2\'f0\'ee\'ea \'ea\'ee\'e4\'e0.\par" "\n"
       + "".join(chr(92) + "u%d?" % ord(c) for c in "Второй")      # ၂? — знак и замена
       + r" \'ed\'e0\'f1\'e5\-\'ea\'ee\'ec\'ee\'e5 {\b \'e6\'e8\'f0\'ed\'fb\'e9}"
       r" \'f2\'e5\'ea\'f1\'f2\par}")
got = textcount._blocks_from_plain(RTF, ".rtf")
check(got == ["Привет, мир! Это один абзац из двух строк кода.", "Второй насекомое жирный текст"],
      "rtf: %s" % got)
got = importers.extract_slots("a.rtf", RTF.encode("cp1251"))
check(got["slots"][:1] == ["Привет, мир! Это один абзац из двух строк кода."] and got["writeback"] is False,
      "rtf через импорт — те же абзацы, выгрузка Word-документом")

print("=== PO: переводятся исходные строки ===")
PO = ('# comment\nmsgid ""\nmsgstr ""\n"Project-Id-Version: x\\n"\n\n'
      '#: src/a.c:1\nmsgid "Hello"\nmsgstr "Привет"\n\n'
      'msgid ""\n"Long line that was "\n"split in two"\nmsgstr ""\n\n'
      'msgid "One file"\nmsgid_plural "%d files"\nmsgstr[0] ""\nmsgstr[1] ""\n')
got = textcount._blocks_from_plain(PO, ".po")
check(got == ["Hello", "Long line that was split in two", "One file", "%d files"], "po: %s" % got)

print("=== ODT/ODS: абзац по text:p, инлайн — часть абзаца ===")
CONTENT = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
           'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">'
           '<office:automatic-styles><style:style style:name="T1"/></office:automatic-styles>'
           '<office:body><office:text>'
           '<text:h>Заголовок</text:h>'
           '<text:p>Абзац <text:span>жирный</text:span> текст,<text:s text:c="2"/>и'
           '<text:line-break/>перенос строки.<text:note><text:note-citation>1</text:note-citation>'
           '<text:note-body><text:p>Сноска к абзацу.</text:p></text:note-body></text:note> Хвост.</text:p>'
           '<text:p>насе­комое</text:p>'
           '</office:text></office:body></office:document-content>')
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("content.xml", CONTENT)
    z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
ODT = buf.getvalue()
got = textcount.extract("a.odt", ODT)["blocks"]
check(got == ["Заголовок", "Абзац жирный текст, и перенос строки. Хвост.", "Сноска к абзацу.", "насекомое"],
      "odt: %s" % got)
check(importers.extract_slots("a.odt", ODT)["slots"] == got, "odt через импорт — те же куски")

print("=== TXT/MD: строка — слот, не склеивается ===")
TXT = "Первая строка абзаца, перенесённая\nвручную посреди фразы.\n"
got = importers.extract_slots("a.txt", TXT.encode("utf-8"))
check(got["slots"] == ["Первая строка абзаца, перенесённая", "вручную посреди фразы.", ""] and got["writeback"],
      "txt: две строки — два слота (обратная запись построчная)")

print()
if fail:
    print("FAILED: %d" % len(fail))
    for x in fail:
        print(" -", x)
    sys.exit(1)
print("ALL OK")
