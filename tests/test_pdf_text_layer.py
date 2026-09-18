"""Текстовый слой PDF: из отпечатка строк — абзацы, без вызова модели.

Синтетические страницы повторяют дефекты боевой книги (Лазебный, «Пчелиная
аптека»): мягкий перенос U+00AD, перенос по дефису, двухстрочный колонтитул,
номер страницы, орнамент «к к к», мусор обложки, потерянная буквица, слово,
разрезанное концом страницы. Настоящий PDF здесь не нужен: `pdftext`
работает со строками, а pypdf их только достаёт. Если книга лежит рядом
(локально), в конце печатается отчёт по ней — без проверок, для глаз.
"""
import io, os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import pdftext
import importers
import textcount

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


SOFT = "­"
HEAD1, HEAD2 = "Апитоксинотерапия —", "лечение пчелоужалением"
BODY = ("В современной медицине неплохо разработана методика апитерапии и "
        "установлены основные показания для применения пчелиного яда.")


def page(n, lines, head=(HEAD1, HEAD2), number=True):
    out = list(head) + list(lines)
    if number:
        out.append(str(n))
    return out


pages = [
    # Обложка: мусор распознавания
    ["Священник Алексдкдр", "ЛлзсБкыа", "3  Z5X П(L) хX и", "У с■X <5С", "О т", "с", "о",
     "Бог СОЗДАЛ ПЧЕЛу во бллю", "ЧЕЛОВЕКУ, И ЭТО УДИВШЕЛЬНО!", "НАСЕКОМОЕ уЖЕ МНОЮ 1Ы< ЯЧ Л1 I",
     "9 789663 384337", "а", "25", "т", "д : и", "Ч й", "о  б"],
    page(5, ["ЗНАКОМЬТЕСЬ:", "НАТУРАЛЬНЫЙ МЕД",
             "Бог создал пчелу во благо человеку, и это удивительное насе" + SOFT,
             "комое уже много тысяч лет щедро дарит людям замечательные",
             "продукты — мед, воск, маточное молочко, прополис.",
             "На заметку",
             "Один русский пуд равен 16 кг.",
             "к к к",
             "Показания к возможному использованию пчелоужалений:",
             "ревматические заболевания, научно-", "обоснованные схемы и мар-"],
         head=()),
    page(6, ["ганца — 1,4 % общего количества золы. Обнаружены также",
             "барий, ванадий и другие элементы.",
             "Л ) . — 1 «■",
             "Показания к возможному использованию пчелоужалений:",
             "бронхит, плеврит; научно-обоснованные подходы описаны выше.",
             "стрый  ларингит чаще всего возникает при остром катаре",
             "верхних дыхательных путей.",
             "Острый бронхит лечат иначе.", "^лучше его заменить. ________________"]),
    page(7, ["Показания к возможному использованию пчелоужалений:",
             "боли в шее и затылке; и 39 %.",
             "♦ ревматические заболевания (ревматические полиартри" + SOFT,
             "ты, ревмокардит);",
             "♦ деформирующий спондилоартроз;",
             "Хронический ларингит развивается как следствие повторяющихся",
             "острых ларингитов."]),
    page(8, ["Показания к возможному использованию пчелоужалений:", BODY, "* * *", BODY]),
]

print("=== 1. Чистка страниц книги ===")
res = pdftext.clean(pages)
r = res["report"]
paras = [it[1] for it in res["items"] if it[0] == "p"]
imgs = [it for it in res["items"] if it[0] == "img"]
print("   report:", r)
check(res["imagePages"] == [0] and len(imgs) == 1 and imgs[0][1] == 0,
      "обложка с мусором — картинкой (текст с неё прочитает зрячая модель)")
check(imgs[0][2] and "Бог СОЗДАЛ ПЧЕЛу во бллю" in imgs[0][2], "у страницы-картинки есть строки на случай, если картинку не достать")
check(all(SOFT not in p for p in paras), "мягких переносов в абзацах не осталось")
check(any("удивительное насекомое уже много" in p for p in paras), "слово с мягким переносом склеено: «насекомое»")
check(any("схемы и марганца — 1,4 %" in p for p in paras),
      "слово, разрезанное концом страницы («мар-» … «ганца»), склеено через колонтитул и номер")
check(any("научно-обоснованные схемы" in p for p in paras),
      "составное слово с дефисом на конце строки сохранило дефис: оно встречается в книге посреди строки")
check(r.get("softHyphens") == 2 and r.get("hyphensJoined") == 1, "снятые переносы посчитаны: мягких 2, дефисных 1")
check(set(res["heads"]) == {HEAD1, HEAD2}, "двухстрочный колонтитул найден по позиции: %s" % res["heads"])
check(not any(p.startswith(HEAD1) or p == HEAD2 for p in paras), "колонтитул не попал в абзацы")
check(r.get("runningHeads") == 6 and r.get("pageNumbers") == 4, "снято 6 строк колонтитула (три страницы по две) и 4 номера")
check(sum(1 for p in paras if p.startswith("Показания к возможному")) == 4,
      "повторяющаяся строка ТЕКСТА (не первой строкой) колонтитулом не считается — все 4 на месте")
check(any(p == "На заметку" for p in paras) and any(p == "Один русский пуд равен 16 кг." for p in paras),
      "короткий заголовок врезки — свой абзац, а не хвост предыдущего")
check("ЗНАКОМЬТЕСЬ: НАТУРАЛЬНЫЙ МЕД" in paras, "заголовок главы из двух строк капсом — один абзац")
check(any(p.startswith("Острый ларингит чаще всего") for p in paras) and r.get("dropCaps") == 1,
      "потерянная буквица восстановлена по словарю документа («стрый» → «Острый»)")
check(not any("к к к" in p or "* * *" in p for p in paras) and r.get("ornaments") == 2, "орнамент «к к к» и «* * *» снят")
check(not any("«■" in p for p in paras) and r.get("junkLines") == 1, "строка-обрывок распознавания снята и посчитана")
check(any(p.startswith("лучше его заменить.") for p in paras) and not any("___" in p for p in paras),
      "знак мусора на краю слова и подчёркивания сняты, текст остался")
check(any(p == "боли в шее и затылке; и 39 %." for p in paras), "«и 39 %.» — хвост предложения, не мусор")
check(any(p.startswith("♦ ревматические заболевания (ревматические полиартриты, ревмокардит);") for p in paras)
      and any(p.startswith("♦ деформирующий") for p in paras), "пункты списка — отдельные абзацы, перенос внутри пункта склеен")
check(not any("  " in p for p in paras), "двойных пробелов в абзацах нет")
check(paras.count(BODY) == 2, "одинаковые абзацы по разные стороны орнамента не склеены")

print("=== 2. Частные правила ===")
check(pdftext.page_unreliable(pages[0]) and not pdftext.page_unreliable(pages[1]),
      "ненадёжной считается только обложка")
check(pdftext.page_unreliable(["а", "б", "в", "г", "д", "е", "ж", "з", "и", "к", "л", "м"]),
      "страница из одиночных букв (художественный титул) — ненадёжна")
check(not pdftext.page_unreliable(["Т5", "В6", "Т12", "точки ВК11 и НК1", "Т38 Т40 С1"] * 3),
      "индексы точек акупунктуры («Т5», «ВК11») — не мусор")
check(pdftext._token_kind("ПрОДуК1Ы") == "junk" and pdftext._token_kind("IIмедяная") == "junk"
      and pdftext._token_kind("Mycobacterium") == "word" and pdftext._token_kind("38,5") is None,
      "виды токенов: цифра в слове и смесь письменностей — мусор, латинское слово — слово")
check(pdftext._is_ornament("к к к") and pdftext._is_ornament("•к к *") and not pdftext._is_ornament("и т. д."),
      "орнамент — строка из одиночных знаков")
check(pdftext._is_noise_line("Л ) . — 1 «■") and pdftext._is_noise_line("ш ж т")
      and not pdftext._is_noise_line("61") and not pdftext._is_noise_line("1.") and not pdftext._is_noise_line("и 39 %."),
      "мусорная строка против номера, маркера и хвоста предложения")
check(pdftext._NUM_LINE_RE.match("61") and pdftext._NUM_LINE_RE.match("— 23 —") and pdftext._NUM_LINE_RE.match("xii")
      and not pdftext._NUM_LINE_RE.match("16 кг"), "номер страницы: число, с тире, римский; «16 кг» — нет")
joined = pdftext.join_lines(["Первая строка абзаца, которая продолжается на" + SOFT, "второй строке.", "Новый абзац."])
check(joined == ["Первая строка абзаца, которая продолжается навторой строке.", "Новый абзац."]
      or joined[0].startswith("Первая строка абзаца, которая продолжается на"),
      "join_lines: мягкий перенос склеивает без пробела")
check(importers.join_pdf_lines(["тубер-", "кулёз лёгких."]) == ["туберкулёз лёгких."],
      "прежний вход importers.join_pdf_lines работает через pdftext")
check(pdftext.join_lines(["ГЛАВА ПЕРВАЯ", "МЁД", "Текст главы начинается здесь."])[:2] == ["ГЛАВА ПЕРВАЯ МЁД", "Текст главы начинается здесь."],
      "две строки капсом — один заголовок, дальше текст")

print("=== 2b. Замечания критика: сокращения, «и т. д.», форма, частицы ===")
for tok in ("IgG", "pH", "HbA1c", "H1N1", "ЭхоКГ", "CD4+", "COVID-19", "МКБ-10", "S1-S2", "2HRZE/4HR", "мРНК", "Т5"):
    check(pdftext._token_kind(tok) in ("abbr", "word"), "«%s» — сокращение или слово, не мусор (%s)" % (tok, pdftext._token_kind(tok)))
lab = ["Схема 2HRZE/4HR при МЛУ-ТБ и COVID-19, HbA1c, IgG4, S1-S2"] + ["Обычный текст страницы про лечение больных в стационаре и дома."] * 12
check(not pdftext.page_unreliable(lab), "страница с одной строкой лабораторных обозначений — надёжна")
check(not pdftext._is_noise_line("и т. д.") and not pdftext._is_noise_line("т. е.") and not pdftext._is_noise_line("а) б) в)"),
      "«и т. д.», «т. е.», «а) б) в)» — не мусор")
check(not pdftext._is_ornament("А Б В") and not pdftext._is_ornament("x y z"), "«А Б В» — не орнамент (разные буквы)")
check(not pdftext._NUM_LINE_RE.match("mild") and not pdftext._NUM_LINE_RE.match("civil") and not pdftext._NUM_LINE_RE.match("1."),
      "«mild», «civil», «1.» — не номера страниц")
form = [["Пациент:", "Иванов И. И.", "Диагноз: бронхит.", "1"], ["Пациент:", "Петров П. П.", "Диагноз: плеврит.", "2"],
        ["Пациент:", "Сидоров С. С.", "Диагноз: ларингит.", "3"]]
check(pdftext.running_heads(form) == (set(), set()), "«Пациент:» — подпись поля формы, не колонтитул")
check(pdftext.join_lines(["Я думаю, что по-", "моему это верно."]) == ["Я думаю, что по-моему это верно."]
      and pdftext.join_lines(["Кто-", "то пришёл."]) == ["Кто-то пришёл."], "«по-моему», «кто-то» — дефис свой")
dc = pdftext.restore_dropcaps(["то  есть так."], __import__("collections").Counter({"то": 40, "это": 50, "есть": 10}), __import__("collections").Counter())
check(dc == ["то есть так."], "частое слово с двойным пробелом буквицей не считается")

print("=== 2c. Картинка страницы: рендер, а без него — только страничная вложенная ===")
import types
fake_pdf = types.SimpleNamespace(PdfReader=None)


class _Img:
    def __init__(self, w, h):
        self.image = types.SimpleNamespace(size=(w, h)); self.data = b"IMG%dx%d" % (w, h)


class _Box:
    width, height = 459.0, 595.0


class _Pg:
    def __init__(self, imgs): self.images = imgs; self.mediabox = _Box()


class _Rd:
    def __init__(self, *a, **k): self.pages = [_Pg([_Img(1174, 2439), _Img(956, 1240)]), _Pg([_Img(200, 80)])]


sys.modules["pypdf"] = types.SimpleNamespace(PdfReader=_Rd)
got = textcount.pdf_page_images(b"%PDF", [0, 1], full_page=True)
check(got == [(0, b"IMG956x1240"), (1, None)], "страничная — по пропорциям mediabox, логотип — None: %s" % got)
got = textcount.pdf_page_images(b"%PDF", [0, 1])
check(got[0][1] == b"IMG1174x2439" and got[1][1] == b"IMG200x80", "без full_page — крупнейшая, как у скана прежде")
_saved = sys.modules.get("pypdfium2")
sys.modules["pypdfium2"] = None          # «модуля нет»
check(textcount.pdf_render_pages(b"%PDF", [0]) is None, "нет pypdfium2 — рендер отвечает None, а не пустым списком")
check(textcount.pdf_page_pictures(b"%PDF", [0, 1], full_page=True) == [(0, b"IMG956x1240"), (1, None)],
      "без рендера pdf_page_pictures падает на вложенную страничную картинку")
if _saved is not None:
    sys.modules["pypdfium2"] = _saved
else:
    del sys.modules["pypdfium2"]
del sys.modules["pypdf"]
try:
    import pypdfium2  # noqa: F401
    have_pdfium = True
except ImportError:
    have_pdfium = False
if have_pdfium:
    from PIL import Image as _I
    _b = io.BytesIO(); _I.new("RGB", (30, 40), "white").save(_b, format="PDF")
    rend = textcount.pdf_render_pages(_b.getvalue(), [0])
    check(rend and rend[0][1] and rend[0][1][:4] == b"\x89PNG", "pypdfium2 есть: страница отрисована в PNG")
else:
    print("   pypdfium2 не установлен — рендер не проверялся (на сервере ставится из requirements)")

print("=== 3. Сборка .docx: абзацы и страницы-картинки вперемешку ===")
from PIL import Image
buf = io.BytesIO()
Image.new("RGB", (40, 60), "white").save(buf, format="PNG")
docx, n_img = importers.mixed_to_docx([("img", 0, ["мусор"]), ("p", "Первый абзац."), ("img", 3, ["резерв"]),
                                       ("p", "Второй абзац.")], {0: buf.getvalue()})
check(n_img == 1 and docx[:2] == b"PK", "картинка вставлена там, где она есть; .docx собран")
import zipfile
with zipfile.ZipFile(io.BytesIO(docx)) as z:
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    xml = z.read("word/document.xml").decode("utf-8")
check(len(media) == 1 and "резерв" in xml and "мусор" not in xml,
      "страница без картинки легла своими строками, страница с картинкой — картинкой")
check(xml.index("Первый абзац.") < xml.index("резерв") < xml.index("Второй абзац."), "порядок документа сохранён")

print("=== 4. Смета: мягкий перенос не удваивает слово ===")
blocks = ["насе" + SOFT, "комое дарит мед"]


class _P:
    def __init__(self, t): self._t = t
    def extract_text(self): return self._t


class _R:
    def __init__(self, texts): self.pages = [_P(t) for t in texts]


import types
fake = types.SimpleNamespace(PdfReader=lambda *_a, **_k: _R(["насе" + SOFT + "\nкомое дарит мед", "61"]))
sys.modules["pypdf"] = fake
got = textcount._pdf_blocks(b"%PDF", [])
check(got == ["насекомое дарит мед", "61"], "смета: «насекомое» — одно слово: %s" % got)
del sys.modules["pypdf"]

print("=== 5. Отчёт по боевой книге (если лежит рядом; без проверок) ===")
book = os.path.join(os.path.expanduser("~"), "Downloads", "Telegram Desktop",
                    "Лазебный_А_священник_Пчелиная_аптека.pdf")
if os.path.exists(book) and os.environ.get("PDFTEXT_BOOK"):
    try:
        pg = textcount._pdf_pages(open(book, "rb").read(), [])
        rep = pdftext.clean(pg)["report"]
        print("   ", rep)
    except Exception as e:                                       # pragma: no cover
        print("    книга не прочиталась:", e)
else:
    print("    пропущено (PDFTEXT_BOOK=1 и файл в Downloads включают)")

print()
if fail:
    print("FAILED: %d" % len(fail))
    for x in fail:
        print(" -", x)
    sys.exit(1)
print("ALL OK")
