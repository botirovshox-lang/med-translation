# -*- coding: utf-8 -*-
"""Правила раздела Ц (разбор выгрузок статьи «Бюллетень сибирской медицины»
RU→EN/DE/ZH, проекты 105/106/110, 18.10.2026). Каждое правило — на
синтетических данных; сама статья в репозиторий не кладётся (файл клиента):
сквозная проверка разбора идёт, только если задан ARTICLE_PDF.

  Ц1   текст, напечатанный дважды в одной точке («ложный полужирный»), — один;
  Ц2   колонтитул по месту, когда пробела под ним мало;
  Ц3   две надписи в одном куске pypdf; цепочка операторов — конец куска;
  Ц4   надстрочник не продолжается основным текстом под собой;
  Ц5   «1, 2» надстрочником — «¹,²»; строка с надстрочного номера — абзац;
  Ц6   сноска внизу страницы не продолжается на следующей;
  Ц7   таблица в одной колонке страницы не забирает строки соседней;
  Ц8   блок картинки страницы — эхо слоя: не заводится и не печатается;
  Ц9   красная строка после короткой — абзац; разрез адреса; «v. 2.050»;
  Ц10  десятичная запятая и точка — одно число; разделитель языка в промпте;
  Ц11  символ гена/кода из оригинала — буква в букву (находка `ident`);
  Ц12  Markdown, которого нет в оригинале, снимается;
  Ц13  знак журнала и надпись, не меняющаяся от перевода, — как были.
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
os.environ.setdefault("MEDCAT_ROLE", "worker")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pypdf
import pdfpages_worker as pw
import pdftext
import checks
from pdf_fixture import make_pdf

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def page_lines_of(pdf: bytes, n: int = 0):
    return pw.page_lines(pypdf.PdfReader(io.BytesIO(pdf)).pages[n])


print("=== Ц1. Ложный полужирный: обводка и заливка в одной точке ===")
foot = "Бюллетень медицины. 2026; 25 (3): 34–40"
pdf = make_pdf([[("t", 40, 500, 10, "Обычная строка текста страницы."),
                 ("raw", "BT /F1 10 Tf 1 0 0 1 60 40 Tm 1 Tr {HEX:%s:HEX} Tj 0 Tr 0 0 Td {HEX:%s:HEX} Tj ET"
                  % (foot, foot))]])
lines, geo = page_lines_of(pdf)
got = [l for l in lines if "Бюллетень" in l]
check(got == [foot], "колонтитул одной копией: %r" % got)
k = lines.index(foot) if foot in lines else -1
check(k >= 0 and geo and geo["lines"][k] and "b" in (geo["lines"][k][4] or ""),
      "оставшаяся копия — полужирная")
t, n = pw._undouble("A. A. 2026; 25 (3)2026; 25 (3): : 34–4034–40", [2, 9, 1, 5])
check((t, n) == ("A. 2026; 25 (3): 34–40", 4), "повторы вырезаны по длинам операторов: %r" % t)
check(pw._undouble("сс", [1])[1] == 1 and pw._undouble("ab", [1])[1] == 0,
      "без повтора ничего не режется")

print("=== Ц2. Колонтитул по месту ===")


def rec(t, y, x0=40.0, x1=300.0, s=10.0):
    return {"t": t, "y": y, "x0": x0, "x1": x1, "s": s}


def page(gap, foot_y=40.0):
    """Страница: тело шагом 12 пт, последняя строка тела на `gap` интервалов
    выше колонтитула."""
    low = foot_y + gap * 12.0
    recs = [rec("Строка %d текста" % k, low + 12 * (39 - k)) for k in range(40)]
    recs.append(rec("Журнал. 2026; 25 (3): 34–40", foot_y, 120, 400))
    return {"recs": recs, "st": {"lead": 12.0}, "top": [], "bottom": []}


laid = {}
for i, gp in enumerate((3.0, 3.0, 3.0, 1.55)):   # у последней тело опущено к колонтитулу
    pg = page(gp)
    pg["top"], pg["bottom"] = pdftext._bands(pg["recs"], pg["st"])
    laid[i] = pg
check(not laid[3]["bottom"], "обычным порогом полоса не нашлась (1.55 интервала)")
rep = {}
pdftext._bands_by_place(laid, rep)
check(bool(laid[3]["bottom"]) and rep.get("bandsByPlace") == 1,
      "по месту колонтитула других страниц — нашлась")
laid2 = {i: page(3.0, foot_y=40 + 9 * i) for i in range(3)}
for i, pg in laid2.items():
    pg["top"], pg["bottom"] = pdftext._bands(pg["recs"], pg["st"])
odd = page(1.55, foot_y=63)
laid2[3] = odd
pdftext._bands_by_place(laid2, {})
check(not odd["bottom"], "строка не на высоте чужих колонтитулов — не колонтитул")

print("=== Ц3. Две надписи в одном куске; цепочка операторов ===")
o1 = (48.2, 768.9, 0.0, 8.0, 20, (253.1, 768.9))
o2 = (343.7, 768.9, 0.0, 8.0, 25, (468.2, 768.9))
check(pw._op_gap(o1, o2, 8.0), "пропасть 90 пт между операторами — разрез")
o3 = (255.0, 768.9, 0.0, 8.0, 5, (280.0, 768.9))
check(not pw._op_gap(o1, o3, 8.0), "межсловный пробел — не разрез")
ends = {(141, 359): 143.0, (145, 359): 312.7, (315, 359): 412.6, (413, 359): 414.8, (417, 359): 443.9}
check(abs(pw._chain_end(ends, 143.0, 358.5, 9.0, 430.0) - 414.8) < 0.01,
      "цепочка вплотную идущих операторов — до конца куска, не дальше оценки")
check(abs(pw._chain_end(ends, 143.0, 358.5, 9.0, 200.0, stop=416.9) - 414.8) < 0.01,
      "с границей следующего куска оценочный потолок не обрывает цепочку")
check(abs(pw._chain_end(ends, 143.0, 358.5, 9.0, 900.0, stop=413.0) - 312.7) < 0.01 or
      abs(pw._chain_end(ends, 143.0, 358.5, 9.0, 900.0, stop=413.0) - 412.6) < 0.01,
      "оператор, начатый в начале следующего куска, — не наш")
c_it = ("GATA3", 416.9, 358.5, 9.0, False, "i", "", False, 0, None, 0.0, 9.0, None)
check(pw._abuts(ends, 140.8, c_it), "курсив, начатый в конце оператора своей части, — продолжение")
check(not pw._abuts({(141, 359): 143.0}, 140.8, c_it), "без такого оператора — нет")

print("=== Ц4. Надстрочник не тянется основным текстом ===")
g_sup = [144.5, 599.7, 7.3, 148.5, "b", "sans", 144.5, None, None, {"F"}, None, None]
g_base = [148.5, 595.6, 12.5, 249.3, "b", "sans", 148.5, None, None, {"F"}, None, None]
op_ends = [(144.5, 599.7, 148.5, "F", 599.7, True, 144.5), (148.5, 595.6, 249.3, "F", 595.6, True, 148.5)]
op_recs = [(144.5, 599.7, 0.0, 7.29, 1, None), (148.5, 595.6, 0.0, 12.5, 15, None)]
pw._exact_ends([g_sup, g_base], op_ends, op_recs)
check(g_sup[3] == 148.5, "конец надстрочника — его оператор: %s" % g_sup[3])
g_b2 = [253.3, 595.6, 12.5, 334.4, "b", "sans", 253.3, None, None, {"F"}, None, None]
g_s2 = [334.4, 599.7, 7.3, 345.9, "b", "sans", 334.4, None, None, {"F"}, None, None]
op_ends2 = [(253.3, 595.6, 334.4, "F", 595.6, True, 253.3), (334.4, 599.7, 345.9, "F", 599.7, True, 334.4)]
op_recs2 = [(253.3, 595.6, 0.0, 12.5, 12, None), (334.4, 599.7, 0.0, 7.29, 3, None)]
pw._exact_ends([g_b2, g_s2], op_ends2, op_recs2)
check(g_b2[3] == 334.4, "основная строка не тянется на надстрочник, начатый своей строкой: %s" % g_b2[3])

print("=== Ц5. Надстрочные номера ===")
base = {"t": ", Брагина Е.Ю.", "s": 12.5, "y": 595.6, "x0": 253.3, "x1": 334.4}
sup = {"t": "1, 2", "s": 7.3, "y": 599.7, "x0": 334.4, "x1": 345.9}
check(pdftext._script_text(sup, base, ", Брагина Е.Ю.", "") == "¹,²", "«1, 2» → «¹,²»")
a = {"t": "Россия, 634050, г. Томск, Московский тракт, 2", "geo": (0, 48.2, 561.6, 260.4, 10.5)}
b18 = {"t": "¹⁸F-ФДГ накапливается в очаге", "geo": (0, 48.2, 549.0, 371.2, 10.5)}
check(pdftext._geo_follows(a, b18), "«¹⁸F-ФДГ» в начале строки — не номер, абзац продолжается")
b = {"t": "² Научно-исследовательский институт", "geo": (0, 48.2, 549.0, 371.2, 10.5)}
check(not pdftext._geo_follows(a, b), "строка с надстрочного номера — новый абзац")

print("=== Ц6. Сноска не продолжается на следующей странице ===")
fa = {"t": "✉ Мелентьева Анастасия Павловна, anastasia@gmail.com", "geo": (0, 60.0, 82.9, 287.0, 8.0)}
fb = {"t": "Для цитирования: Мелентьева А.П.", "geo": (1, 93.5, 745.8, 506.0, 9.0)}
check(pdftext._page_size_break(fa, fb, 10.5), "строка кончилась адресом почты — абзац кончился")
ta = {"t": "меда на литр воды. Приготовить", "geo": (0, 40.0, 448.0, 365.0, 10.0)}
tb = {"t": "Апитерапия - медолечение", "geo": (1, 40.0, 560.0, 172.0, 11.0)}
check(not pdftext._page_size_break(ta, tb, 10.0), "обычный абзац через страницу — продолжается")
sa = {"t": "мелкая сноска без адреса", "geo": (0, 40.0, 60.0, 300.0, 7.0)}
sb = {"t": "Основной текст страницы", "geo": (1, 40.0, 700.0, 300.0, 10.0)}
check(pdftext._page_size_break(sa, sb, 10.0), "строка мельче основного текста — сноска")

print("=== Ц7. Таблица в своей колонке ===")


def r(t, x0, x1, y, s=8.5):
    return {"t": t, "x0": x0, "x1": x1, "y": y, "s": s, "geo": (3, x0, y, x1, s)}


recs = []
for k in range(16):                         # левая колонка — сплошной текст, свой шаг строк
    recs.append(r("строка левой колонки номер %d текста" % k, 48.0, 285.0, 703 - 12.7 * k, 10.5))
recs.append(r("в течение 1 мин.", 48.0, 130.0, 499.8, 10.5))  # короткая строка левой колонки
for k in range(10):                         # правая колонка — текст выше таблицы
    recs.append(r("строка правой колонки номер %d текста" % k, 307.0, 547.0, 760 - 12 * k, 10.5))
rows = [("GATA3", "AG", "50 (64,9)", "61 (52,1)", "0,51"), ("аддитивная", "GG", "4 (5,3)", "23 (19,7)", "(0,34)"),
        ("rs10905277", "AA", "73 (94,8)", "94 (80,3)", "1,0"), ("GATA3", "GG", "4 (5,2)", "23 (19,7)", "0,22")]
for k, row in enumerate(rows):
    for x, t in zip((312, 372, 399, 439, 491), row):
        recs.append(r(t, x, x + 22, 580 - 12 * k))
out = pdftext._table_streams(recs, {"tables": 0, "tableCells": 0})
check(out is not None, "таблица найдена")
tab = [x for x in (out or []) if x.get("tcol")]
check(tab and all(x["x0"] >= 300 for x in tab), "в таблицу не попала ни одна строка левой колонки")
if out:
    idx_tab = [i for i, x in enumerate(out) if x.get("tcol")]
    above = [i for i, x in enumerate(out) if x["x0"] >= 300 and not x.get("tcol") and x["y"] > 590]
    check(above and min(idx_tab) > max(above), "таблица встала в поток своей колонки, после строки над ней")

print("=== Ц8. Эхо слоя ===")
import main  # noqa: E402
paras = [(15, (90.0, 440.0, 504.0, 480.0), [], "супрессора цитокиновых сигналов 5-го типа (SOCS5), транскрипционного фактора")]
check(main._layer_echo("SOCS5),", paras, (470.0, 462.0, 500.0, 472.0)), "«SOCS5),» поверх своей строки — эхо")
check(not main._layer_echo("SOCS5),", paras, (470.0, 300.0, 500.0, 310.0)), "в другом месте — не эхо")
check(not main._layer_echo("Optimize quality of life", [(1, (0, 0, 100, 100), [], "Optimize")], (0, 0, 90, 20)),
      "надпись шире куска слоя — не эхо (Т32)")
check(not main._layer_echo("ab", paras, (470.0, 462.0, 500.0, 472.0)), "короче трёх знаков — не судим")
line_par = [(9, (300.0, 495.0, 546.0, 520.0), [], "проявления бронхиальной астмы. Вятский медицинский вестник",
             [(300.0, 495.0, 507.0, 505.0)])]
check(main._layer_echo("СТМЫ.", line_par, (444.0, 494.0, 461.0, 505.0)), "хвост слова «астмы.» на своей строке — эхо")
check(main._layer_echo("варианта", [(5, (300.0, 720.0, 546.0, 740.0), [], "Впервые установлена ассоциация варианта rs10905277",
                                     [(300.0, 722.0, 505.0, 732.0)])], (507.0, 724.0, 547.0, 735.0)),
      "курсивный хвост за оценённым концом строки — эхо")
_dd = {"layout": {"boxes": {"5": [{"page": 5, "x1": 505.0, "slots": [[300.0, 724.0, 505.0, 10.5, "", 300.0, 40, 0]]}]}}}
check(main._echo_extend_slot(_dd, 5, (507.0, 722.0, 547.0, 735.0))
      and _dd["layout"]["boxes"]["5"][0]["slots"][0][2] == 547.0,
      "Ц8в: строка слоя продлена до конца эха — её закраска накроет хвост оригинала")
# Записи абзацев слоя — с пятым полем (рамки строк): все, кто их разбирает, обязаны его пережить.
five = [(1, (0.0, 0.0, 100.0, 20.0), ["where"], "WHERE?:", [(0.0, 0.0, 100.0, 20.0)])]
try:
    main._holds_layer_pieces("WHERE?: Everyday settings", five, (0.0, 0.0, 300.0, 20.0))
    ok5 = True
except ValueError:
    ok5 = False
check(ok5, "записи абзацев слоя с рамками строк разбираются без ошибки")
wrap = [(2, (48.0, 300.0, 545.0, 700.0), [], "the late stage of the disease and other words of this paragraph",
         [(48.0, 690.0, 545.0, 700.0), (48.0, 300.0, 545.0, 310.0)])]
check(not main._layer_echo("Age", wrap, (200.0, 500.0, 230.0, 510.0)),
      "«Age» на рисунке внутри рамки обтекающего абзаца — не эхо (не на его строке, не слово)")

print("=== Ц3. Пересборка «same» снимает устаревший разрыв строки ===")
_store = {"layout": {"boxes": {"13": [{"page": 0, "slots": [
    [90.7, 395.2, 504.0, 9.0, "", 455.8, 102, 1, None, [0, 0, 0], [[164.8, 373.2]]]]}]}}}
_saved = {}
_lsm, _ssm = main._load_source_map, main._save_source_map
main._load_source_map = lambda pid: _store
main._save_source_map = lambda pid, d: _saved.setdefault("d", d)
try:
    n_ = main._merge_layout_fields(1, {"boxes": {"13": [{"page": 0, "slots": [
        [90.7, 395.2, 504.0, 9.0, "", 455.8, 102, 1, None, [0, 0, 0], None]]}]}})
finally:
    main._load_source_map, main._save_source_map = _lsm, _ssm
check(n_ == 1 and _store["layout"]["boxes"]["13"][0]["slots"][0][10] is None and "d" in _saved,
      "ложный разрыв, которого новые правила не видят, снят из карты")

print("=== Ц9. Красная строка, разрез адреса, «v. 2.050» ===")
a = {"t": "СибГМУ, г. Томск, elena.bragina@medgenetics.ru, https://orcid.org/0000-0002-2962-1076",
     "geo": (6, 48.2, 266.1, 383.7, 9.0)}
b = {"t": "Огородова Людмила Михайловна – д-р мед. наук, профессор", "geo": (6, 62.4, 255.3, 544.2, 9.0)}
check(not pdftext._geo_follows(a, b), "короткая строка + красная строка — новый абзац")
c = {"t": "продолжение абзаца во всю ширину колонки текста", "geo": (6, 48.2, 255.3, 544.2, 9.0)}
check(pdftext._geo_follows(a, c), "без отступа — продолжение")
check(pdftext._addr_cut("olga.fedorova@gmail.", "com, https://orcid.org/1"), "«…@gmail.» + «com» — разрез адреса")
check(not pdftext._addr_cut("Конец фразы.", "дальше"), "обычная точка — конец фразы")
got = pdftext.join_lines(["Статистически значимым считали уровень p < 0,05. Расчеты выполнены в программе PLINK",
                          "v. 2.050 (http://zzz.bwh.harvard.edu/plink)."])
check(len(got) == 1, "«v. 2.050» после «…PLINK» — та же фраза: %r" % got)
got = pdftext.join_lines(["Варианты ответа:", "a) первый вариант;", "b) второй вариант."])
check(len(got) == 3, "пункты «a)», «b)» после двоеточия — пункты: %r" % got)
got = pdftext.join_lines(["Критерии включения", "a) возраст от 6 до 17 лет", "b) подписанное согласие"])
check(len(got) == 3, "пункт после заголовка без точки — пункт: %r" % got)

print("=== Ц10. Десятичный разделитель ===")
check(checks._extract_numbers("10,1 ± 8") == checks._extract_numbers("10.1 ± 8"), "«10,1» и «10.1» — одно число")
iss = checks.deterministic_issues("возраст 10,1 года", "age 10.1 years", src_lang="RU", tgt_lang="EN") \
    if hasattr(checks, "deterministic_issues") else []
check(not any(i.get("type") == "number_unit_dosage_mismatch" for i in iss), "перевод с точкой — не расхождение чисел")
en = main._lang_conventions("EN")
check("Decimal separator is a point" in en, "английскому промпт велит точку")
check("Decimal separator is a comma" in main._lang_conventions("DE"), "немецкому — запятую")
check(main._decimal_fix("возраст 10,1 ± 8 лет, 95% CI 0,34–0,77", "age 10,1 ± 8 years, CI 0,34–0,77; 1,000 cells",
                        "RU", "EN") == "age 10.1 ± 8 years, CI 0.34–0.77; 1,000 cells",
      "Ц10б: дроби оригинала — точкой, чужое число не тронуто")
check(main._decimal_fix("10,1", "10,1 Jahre", "RU", "DE") == "10,1 Jahre", "немецкому запятая остаётся")
check(main._decimal_fix("1,000 cells", "1,000 个细胞", "EN", "ZH") == "1,000 个细胞", "из английского — не трогаем")

print("=== Ц11. Символы генов и коды ===")
seg = {"source": "вариант rs10905277 гена GATA3 и STAT5B (IL10)", "target": "GATA结合蛋白3基因的rs10905277变异与STAT5B（IL10）"}
f = main._ident_misses(seg)
check(f and "GATA3" in f[0]["text"] and "STAT5B" not in f[0]["text"], "«GATA3» не дожил — находка: %s" % f)
check(not main._ident_misses({"source": "БА и OR, 95% CI", "target": "BA and OR, 95% CI"}), "аббревиатуры без цифр не трогаем")
check(not main._ident_misses({"source": "HIV-1, IL-6, CO2, T2DM", "target": "ВИЧ-1, ИЛ-6, CO₂, СД2"}),
      "«HIV-1», «IL-6», «CO2», «T2DM» — законный перевод сокращения, не находка")
check(any(x["kind"] == "ident" for x in main._repair_findings(seg)), "находка идёт в ремонт")
exp = main._ident_misses({"source": "Ассоциация полиморфизма гена GATA3 (rs10905277)",
                          "target": "GATA3（鸟嘌呤—腺嘌呤结合蛋白3）基因多态性（rs10905277）的关联"})
check(exp and "GATA3" in exp[0]["text"] and "rs10905277" not in exp[0]["text"],
      "Ц11б: своя расшифровка в скобках — находка; скобка из оригинала — нет: %s" % exp)
sysp = main._translate_system("RU", "ZH", [], {}, False, "medical", {"id": "x", "label": "x"})
check("GATA3, STAT5B, IL10, rs10905277" in sysp, "промпт перевода велит переносить символы как есть")

print("=== Ц12. Markdown ===")
check(main._strip_markdown("Материалы и методы.", "**材料与方法** 研究") == "材料与方法 研究", "«**…**» снят")
check(main._strip_markdown("a **b** c", "x **y** z") == "x **y** z", "в оригинале есть — оставлен")

print("=== Т36. Запись, помеченная прежней версией без разреза по ключу легенды ===")
rec4 = {"groupRule": 4, "blocks": [{"box": [153, 213, 310, 258], "rows": 2, "text": "AA Легкая степень БА"},
                                   {"box": [765, 214, 795, 233], "rows": 1, "skip": "noise"}]}
check(main._regroup_wants(rec4), "многострочный блок записи правила 4 — перегруппировка нужна (разрез виден по пикселям)")
check(not main._regroup_wants({"groupRule": main.image_text.IMG_GROUP_RULE, "blocks": rec4["blocks"]}),
      "записи нынешнего правила — не нужна")
import numpy as _np
img = _np.full((60, 300, 3), 255, dtype=_np.uint8)
img[22:42, 5:12] = 60            # буква «A» соседней подписи оси слева
img[26:38, 30:42] = (240, 130, 30)   # оранжевый квадрат ключа
for x in range(50, 220, 14):
    img[24:40, x:x + 9] = 90         # буквы подписи серии
check(main.image_text.legend_key(img, [28, 20, 220, 44]) is not None,
      "Ц14: ключ находится, даже когда левее в зоне поиска стоит буква соседней подписи")

print("=== Ц13. Знак журнала ===")
check(main._same_look("ЕСМ", "ECM") and not main._same_look("ЕСМ", "ESM"), "«ЕСМ» и «ECM» — одно на вид")
data = {"layout": {"pages": [[0.0, 0.0, 595.3, 841.9]],
                   "boxes": {"0": [{"page": 0, "slots": [[48.0, 700.0, 500.0, 10.5]]}],
                             "1": [{"page": 0, "slots": [[48.0, 680.0, 500.0, 15.0]]}]}}}
rec_ = {"part": "pdfpage/0000.png", "w": 1191, "h": 1684}
check(main._logo_block(data, rec_, {"box": [98, 130, 242, 221], "rows": 1}, "ЕСМ"), "крупное слово капсом — знак")
check(not main._logo_block(data, rec_, {"box": [98, 130, 242, 160], "rows": 1}, "ЕСМ"), "кеглем текста — не знак")
check(not main._logo_block(data, rec_, {"box": [98, 130, 242, 221], "rows": 1}, "Рис"), "не капсом — не знак")

art = os.environ.get("ARTICLE_PDF")
if art and os.path.exists(art):
    print("=== Сквозная проверка: статья ===")
    import textcount
    pages, geoms = textcount._pdf_pages_geom(open(art, "rb").read(), [])
    items = [p if isinstance(p, str) else (p[1] if len(p) > 1 and isinstance(p[1], str) else "")
             for p in pdftext.clean(pages, geom=geoms)["items"]]
    check(any(t.startswith("Мелентьева А.П.¹, Покотилова А.С.¹, Брагина Е.Ю.¹,²") for t in items), "авторы — одной строкой")
    check(not any("34–4034–40" in t for t in items), "колонтитул без задвоения")
    check(not any(t.startswith("Бюллетень сибирской медицины") and len(t) > 60 for t in items),
          "колонтитул не склеен с текстом")
    res_ = pdftext.clean(pages, geom=geoms)
    gaps = [sl for bl in res_["layout"] for b in (bl or []) for sl in b.get("slots") or [] if len(sl) > 10 and sl[10]]
    check(len(gaps) <= 1, "в раскладке статьи нет ложных разрывов строк (цепочка операторов Ц3): %d" % len(gaps))
else:
    print("   (ARTICLE_PDF не задан — сквозная проверка на статье пропущена)")

print()
print("ALL OK" if not fail else "FAIL: %d" % len(fail))
sys.exit(1 if fail else 0)
