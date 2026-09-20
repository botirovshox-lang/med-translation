# -*- coding: utf-8 -*-
"""Рисунки книги доезжают до документа: PDF → .docx → выгрузка.

Боевой случай (Лазебный, «Пчелиная аптека», RU→UZ-CYRL): из 378 страниц
книги в собранный .docx попадали ДВЕ картинки — страницы с негодным
текстовым слоем, — а все рисунки (схемы точек «ВК21», иллюстрации) терялись
молча: подпись «Рис. 3» в переводе оставалась, а рисунка под ней не было.
Геометрия рисунков при этом уже вычислялась — по ней метки вокруг рисунка
становятся отдельными абзацами, — но сама картинка никуда не клалась.

Четыре правила, каждое выстрадано на этой книге:
  1. рисунок встаёт в поток НА СВОЁ МЕСТО (перед своей подписью), а не
     в конец документа;
  2. вырезается СВОБОДНАЯ ПОЛОСА между строками, а не рамка картинки:
     на скане подписи внутри рисунка в текстовый слой не попали и лежат
     за её краем;
  3. картинка, по которой ИДЁТ ТЕКСТ, в документ не переносится — иначе
     кусок книги уехал бы туда дважды, второй раз непереведённой картинкой
     (так ловятся орнаменты шапки и полосы колонтитулов);
  4. слои многослойного скана сливаются в ОДИН рисунок при выкладке,
     но НЕ при разметке ролей: слитая рамка накрывает текст между двумя
     картинками, и на боевой книге так разорвался абзац посреди слова
     («лимонную кис-» / «лоту по вкусу»).
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import pdftext
import textcount
import importers

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_fixture import make_pdf, body, folio

HEAD = "Апитоксинотерапия - лечение пчелоужалением"
TEXT_A = ["Точка расположена на складке локтевого сгиба, в середине",
          "расстояния между внутренним концом складки и внутренним",
          "надмыщелком плечевой кости, у края сухожилия мышцы."]
TEXT_B = ["Показания к возможному использованию пчелоужалений:",
          "боль в области сердца, головокружение, онемение кожи плеча."]

# Страница как в книге: колонтитул, рисунок с подписью, текст.
PAGE_FIG = ([("t", 40, 560, 11, HEAD)]
            + [("img", 110, 320, 175, 210)]
            + [("t", 180, 290, 10, "Рис. 3")]
            + body(TEXT_A, top=260)
            + body(TEXT_B, top=200)
            + folio(179))
# Полоса шапки: орнамент, по которому идёт сам колонтитул.
PAGE_BAND = ([("img", 60, 520, 240, 80)]
             + [("t", 40, 560, 11, HEAD)]
             + body(TEXT_A, top=500)
             + body(TEXT_B, top=440)
             + folio(180))
PDF = make_pdf([PAGE_FIG, PAGE_BAND])
pages, geoms = textcount._pdf_pages_geom(PDF, [])
res = pdftext.clean(pages, geom=geoms)
items = res["items"]

print("=== 1. Рисунок встаёт в поток на своё место ===")
kinds = [it[0] for it in items]
check(kinds.count("fig") == 1, "рисунок один: орнамент шапки не в счёт (fig=%d)" % kinds.count("fig"))
at = kinds.index("fig") if "fig" in kinds else -1
after = next((items[k][1] for k in range(at + 1, len(items)) if items[k][0] == "p"), "")
check(at >= 0 and after.startswith("Рис. 3"), "рисунок стоит ПЕРЕД своей подписью: %r" % after[:20])
check(res["report"].get("figures") == 1 and res["report"].get("figuresSkipped") == 1,
      "отчёт называет и перенесённые, и отсеянные рисунки")

print("=== 2. Рамка — доли листа, и она шире самой картинки ===")
pg, frac = items[at][1], items[at][2]
check(pg == 0, "рисунок отнесён к своей странице")
check(all(0.0 <= v <= 1.0 for v in frac) and frac[0] < frac[2] and frac[1] < frac[3],
      "рамка в долях листа и не вывернута: %s" % (frac,))
box = geoms[0]["box"]
pw, ph = box[2] - box[0], box[3] - box[1]
x0, y0, x1, y1 = frac[0] * pw, box[3] - frac[1] * ph, frac[2] * pw, box[3] - frac[3] * ph
check(x0 <= 110 and x1 >= 285, "вырезка шире рамки картинки: подписи по краям не отрезаны")
check(y1 < 320 and y0 > 530, "вырезка раздвинута до соседних строк, но не накрыла их")

print("=== 3. Картинка, по которой идёт текст, не переносится ===")
recs = pdftext._geo_page(pages[1], geoms[1])
figs = pdftext._fig_boxes(geoms[1], recs, merge=True)
check(len(figs) == 1, "полоса шапки по размеру за рисунок сходит")
crop = pdftext._fig_crop(figs[0], recs, figs, geoms[1]["box"])
check(pdftext._fig_printable(crop, recs) is False,
      "но в документ не идёт: внутри вырезки стоит строка колонтитула")
check(not any(it[0] == "fig" and it[1] == 1 for it in items), "со второй страницы рисунков нет")

print("=== 3а. Лоскут края листа и картинка вне колонки — не рисунки ===")
# Книга, снятая со сканера: край переплёта и стол лежат своими картинками.
EDGE = ([("t", 40, 560, 11, HEAD)] + [("img", 2, 5, 60, 590)]      # полоса во всю высоту у края
        + [("img", 320, 300, 75, 200)]                            # картинка вне колонки справа
        + body(TEXT_A, top=500) + body(TEXT_B, top=440) + folio(182))
pages3, geoms3 = textcount._pdf_pages_geom(make_pdf([EDGE]), [])
recs3 = pdftext._geo_page(pages3[0], geoms3[0])
kept3 = pdftext._fig_boxes(geoms3[0], recs3, merge=True)
check(kept3 == [], "обе отсеяны до всякой вырезки: %s" % [[round(v) for v in f] for f in kept3])

print("=== 4. Слияние слоёв — только при выкладке ===")
# Скан режет один рисунок на слои: две рамки вплотную.
LAYERS = ([("t", 40, 560, 11, HEAD)] + [("img", 110, 430, 175, 100)]
          + [("img", 110, 320, 175, 105)] + [("t", 180, 290, 10, "Рис. 4")]
          + body(TEXT_A, top=260) + folio(181))
pages2, geoms2 = textcount._pdf_pages_geom(make_pdf([LAYERS]), [])
recs2 = pdftext._geo_page(pages2[0], geoms2[0])
check(len(pdftext._fig_boxes(geoms2[0], recs2, merge=True)) == 1, "слои слиты в один рисунок")
check(len(pdftext._fig_boxes(geoms2[0], recs2)) == 2,
      "а разметка ролей видит их врозь: слитая рамка накрыла бы текст между ними")

print("=== 5. Сборка .docx: рисунок попал в документ картинкой ===")
out = importers.to_docx("book.pdf", PDF)
import zipfile
with zipfile.ZipFile(io.BytesIO(out["docx"])) as z:
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    xml = z.read("word/document.xml").decode("utf-8")
have_render = textcount.pdf_render_pages(PDF, [0]) is not None
if have_render:
    check(len(media) == 1, "в документе ровно одна картинка — рисунок (media=%d)" % len(media))
    check(xml.index("drawing") < xml.index("Рис. 3"), "картинка стоит перед подписью и в документе")
    check("Рисунков перенесено в документ: 1" in (out["note"] or ""), "примечание называет число рисунков")
else:
    check(len(media) == 0 and out["docx"][:2] == b"PK",
          "без рендера документ собирается без рисунков, а не падает")
    print("   pypdfium2 не установлен — вырезка не проверялась (на сервере ставится из requirements)")
check(all(t in xml for t in ("Рис. 3", TEXT_B[0][:20])), "текст страницы не потерян")

print("\n" + ("ALL OK" if not fail else "FAILED: %d" % len(fail)))
sys.exit(1 if fail else 0)
