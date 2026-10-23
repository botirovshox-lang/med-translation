"""Дочерний процесс: текстовый слой диапазона страниц PDF — построчно.

Зачем отдельным процессом, а не потоком: извлечение текста pypdf — чистый
Python, и потоки упираются в GIL. Книга на 378 страниц читалась 31 с одним
ядром; четыре процесса делят её на куски, и ответ приходит вчетверо быстрее.
Библиотека та же (pypdf), поэтому строки те же буква в букву: правила
`pdftext` подобраны именно на её выдаче, и смена извлекателя (pdfium быстрее
ещё вдесятеро) поменяла бы переносы, колонтитулы и страницы-картинки.

Геометрия строк (`page_lines`) берётся ТЕМ ЖЕ вызовом pypdf — через
`visitor_text`: он получает те же куски текста, из которых pypdf собирает
ответ, вместе с их положением на странице. Строки при этом не меняются ни
на букву (сверяется: склеенные куски обязаны дать тот же текст, иначе
геометрии у страницы нет). pdfium давал бы точные рамки букв, но строки
пришлось бы сопоставлять с выдачей pypdf по тексту — второе мнение о том,
где кончается строка, и однажды оно разошлось бы с первым.

Отдельным файлом, а не `multiprocessing`: тот при старте ребёнка импортирует
главный модуль родителя, а у воркера прогонов это `backend.worker` →
`main.py` — состояние, база, кэши. Здесь ребёнок знает только pypdf.

Протокол: байты PDF — на stdin; аргументы — start end; на stdout по строке
JSON на страницу: [номер, [строки], геометрия|null]. Ошибка — код возврата 1
и текст в stderr: родитель тогда читает сам, по-старому."""

import io
import json
import os
import statistics
from collections import Counter
import sys

# Операторы, которыми рисуется путь; «re» — прямоугольник. Закрашенный или
# обведённый прямоугольник — рамка врезки; тот же «re» перед «W» — обрезка,
# её на странице не видно, и рамкой она не считается.
_PAINT_OPS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
_CLIP_OPS = {b"W", b"W*"}
# Ширина знака в долях кегля, пока страница не дала замерить свою.
_CHAR_W = 0.5


def _xy(cm, x, y):
    return (cm[0] * x + cm[2] * y + cm[4], cm[1] * x + cm[3] * y + cm[5])


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


# Семейство шрифта — по ИМЕНИ: флаги в описании шрифта PDF (Serif, FixedPitch)
# на деле не ставят — у Minion Pro, у Calibri и у DIN в одном файле одно и то
# же «Nonsymbolic». Имя же называет гарнитуру, и выгрузка «как в оригинале»
# печатает перевод рубленым там, где оригинал набран рубленым, а не одной
# гарнитурой на всю книгу. Порядок проверки несущий: «sansserif» содержит
# «serif», «Palatino» — «lato», а «Dingbats» начинается с «din».
_FAM_MONO = ("mono", "courier", "consol", "menlo", "fixedsys", "typewriter",
             "inconsolata", "sourcecode", "firacode", "lucidaconsole", "nimbusmon",
             "cousine", "jetbrains", "ibmplexmono", "sfmono")
_FAM_SANS = ("sans", "arial", "helvetica", "verdana", "tahoma", "calibri", "segoe",
             "frutiger", "myriad", "univers", "futura", "gill", "lato", "roboto",
             "inter", "montserrat", "trebuchet", "franklin", "avenir", "gothic",
             "grotesk", "grotesque", "candara", "corbel", "ubuntu", "geneva",
             "proxima", "akzidenz", "nimbussan", "pragmatica", "raleway", "poppins",
             "nunito", "oswald", "rubik", "manrope", "officina", "ptsans",
             "dinpro", "dinnext", "dinot", "dincond", "dinround", "bahnschrift",
             "aptos", "carlito", "arimo", "gotham", "heros", "sfpro", "sfui", "segoeui",
             "helvetica", "neuehaas", "graphik", "circular", "worksans", "firasans",
             "ibmplexsans", "notosans", "opensans", "sourcesans", "ptsans")
_FAM_SERIF = ("serif", "times", "minion", "garamond", "georgia", "cambria", "palatino",
              "baskerville", "caslon", "bodoni", "century", "sentinel", "stix",
              "charter", "roman", "constantia", "didot", "utopia", "nimbusrom",
              "museo", "mercury", "tiempos", "merriweather", "lora", "playfair",
              "crimson", "warnock", "kepler", "sabon", "bembo", "plantin", "janson",
              "rockwell", "clarendon", "bookman", "bookantiqua", "literaturnaya",
              "newton", "academy", "schoolbook", "pt_serif", "ptserif", "cmr",
              "caladea", "tinos", "termes", "pagella", "charis", "gentium", "garamon")


def _descriptor(fd):
    """Описание шрифта (/FontDescriptor), у составного — у потомка."""
    try:
        desc = fd.get("/FontDescriptor")
        if desc is None and fd.get("/DescendantFonts"):
            kid = fd["/DescendantFonts"][0]
            kid = kid.get_object() if hasattr(kid, "get_object") else kid
            desc = kid.get("/FontDescriptor")
        return desc.get_object() if hasattr(desc, "get_object") else desc
    except Exception:
        return None


def _sfnt_info(data: bytes) -> dict:
    """Из встроенного TrueType/OpenType: {weight, italic, family, name}.

    OS/2: usWeightClass (вес), fsSelection (курсив, полужирный), PANOSE
    (с засечками / рубленый / моноширинный); name: настоящее имя гарнитуры.
    Нужно, когда имя шрифта в PDF пустое («font0000000030790b66»): вес и
    гарнитура лежат в самом шрифте. Сбой разбора — пустой ответ."""
    import struct
    out: dict = {}
    try:
        if len(data) < 12:
            return out
        n = struct.unpack(">H", data[4:6])[0]
        tables = {}
        for k in range(min(n, 64)):
            rec = data[12 + 16 * k: 28 + 16 * k]
            if len(rec) < 16:
                break
            tag = rec[:4].decode("latin-1")
            off, ln = struct.unpack(">II", rec[8:16])
            tables[tag] = (off, ln)
        if "OS/2" in tables:
            off, ln = tables["OS/2"]
            t = data[off:off + ln]
            if len(t) >= 64:
                out["weight"] = struct.unpack(">H", t[4:6])[0]
                fs = struct.unpack(">H", t[62:64])[0]
                out["italic"] = bool(fs & 1)
                if fs & 32:
                    out["weight"] = max(out["weight"], 700)
                fam_type, serif, prop = t[32], t[33], t[35]
                if prop == 9:
                    out["family"] = "mono"
                elif fam_type == 2 and 11 <= serif <= 13:
                    out["family"] = "sans"
                elif fam_type == 2 and 2 <= serif <= 10:
                    out["family"] = "serif"
        if "name" in tables:
            off, ln = tables["name"]
            t = data[off:off + ln]
            cnt, sto = struct.unpack(">HH", t[2:6])
            for k in range(min(cnt, 200)):
                pid, eid, lid, nid, l2, o2 = struct.unpack(">HHHHHH", t[6 + 12 * k: 18 + 12 * k])
                if nid not in (1, 4):
                    continue
                raw = t[sto + o2: sto + o2 + l2]
                name = raw.decode("utf-16-be", "ignore") if pid in (0, 3) else raw.decode("latin-1", "ignore")
                if name.strip():
                    out["name"] = name.strip()
                    if nid == 4:
                        break
    except Exception:
        return out
    return out


SLANT_MIN, SLANT_MAX = 0.1, 0.5   # Ш42: наклон буквы, читаемый как курсив (≈6°–30°)


def _program_info(fd) -> dict:
    """Вес, курсив, гарнитура — из описания шрифта и встроенной программы.
    Описание: FontWeight, ItalicAngle, флаги Italic/ForceBold, StemV
    (толщина основы: у обычного ~80–90, у полужирного ~130–150)."""
    out: dict = {}
    desc = _descriptor(fd) if not isinstance(fd, str) else None
    if desc is None:
        return out
    try:
        w = desc.get("/FontWeight")
        if w is not None:
            out["weight"] = float(w)
        ang = desc.get("/ItalicAngle")
        if ang is not None and abs(float(ang)) >= 3:
            out["italic"] = True
        flags = int(desc.get("/Flags") or 0)
        if flags & 64:
            out["italic"] = True
        if flags & 262144:
            out["weight"] = max(out.get("weight", 0), 700)
        stem = desc.get("/StemV")
        if stem is not None and "weight" not in out and float(stem) >= 120:
            out["weight"] = 700
    except Exception:
        pass
    for key in ("/FontFile2", "/FontFile3"):
        try:
            ff = desc.get(key)
            if ff is None:
                continue
            ff = ff.get_object() if hasattr(ff, "get_object") else ff
            if key == "/FontFile3" and str(ff.get("/Subtype") or "") != "/OpenType":
                continue
            info = _sfnt_info(ff.get_data())
            for k, v in info.items():
                out.setdefault(k, v) if k != "weight" else out.__setitem__(k, max(out.get(k, 0), v))
        except Exception:
            continue
    return out


def _family(fd) -> str:
    """«sans» / «serif» / «mono» / «» (не знаем: символьный шрифт, имя без
    гарнитуры). «Не знаем» не голосует — абзац берёт семейство документа."""
    try:
        if isinstance(fd, str):
            name, flags = fd, None
        else:
            fd = fd or {}
            name = str(fd.get("/BaseFont") or "")
            desc = fd.get("/FontDescriptor")
            if desc is None and fd.get("/DescendantFonts"):
                kid = fd["/DescendantFonts"][0]
                kid = kid.get_object() if hasattr(kid, "get_object") else kid
                desc = kid.get("/FontDescriptor")
            desc = desc.get_object() if hasattr(desc, "get_object") else desc
            flags = int(desc.get("/Flags") or 0) if desc is not None else None
    except Exception:
        return ""
    # Префикс подмножества «ABCDEF+» и разделители — не часть имени гарнитуры.
    n = name.split("+", 1)[-1].lower().lstrip("/")
    n = "".join(ch for ch in n if ch.isalnum() or ch == "_")
    if any(k in n for k in _FAM_MONO):
        return "mono"
    if "palatino" in n:             # «lato» внутри — гарнитура с засечками
        return "serif"
    # Явное «serif»/«slab» в имени сильнее списка рубленых: «RobotoSlab»,
    # «ITCOfficinaSerif» — с засечками, хотя «roboto»/«officina» рубленые.
    if ("serif" in n and "sansserif" not in n and "sans" not in n) or "slab" in n:
        return "serif"
    if any(k in n for k in _FAM_SANS) or (n.startswith("din") and "dingbat" not in n):
        return "sans"
    if any(k in n for k in _FAM_SERIF):
        return "serif"
    if flags:
        if flags & 1:
            return "mono"
        if flags & 2:
            return "serif"
    return ""


_COLOR_OPS = (b"g", b"rg", b"k", b"cs", b"sc", b"scn")


def _mmul(a, b):
    """Произведение матриц PDF [a b c d e f]: сперва a, потом b."""
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def _cmyk(c, m, y, k):
    return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))


def _cs_n(name, res_now) -> "int | None":
    """Число компонент пространства цвета заливки: 1/3/4 — серый, RGB, CMYK
    (у ICCBased — по /N); None — узор, плашечный и прочее, чего не знаем."""
    n = {"/DeviceGray": 1, "/G": 1, "/DeviceRGB": 3, "/RGB": 3, "/DeviceCMYK": 4, "/CMYK": 4}
    name = str(name)
    if name in n:
        return n[name]
    try:
        csd = (res_now().get("/ColorSpace", {}) or {})
        csd = csd.get_object() if hasattr(csd, "get_object") else csd
        o = csd.get(name)
        o = o.get_object() if hasattr(o, "get_object") else o
        if isinstance(o, list) and o and str(o[0]) == "/ICCBased":
            st = o[1].get_object()
            return int(st.get("/N", 0)) or None
        if isinstance(o, list) and o and str(o[0]) in n:
            return n[str(o[0])]
    except Exception:
        return None
    return None


def _set_fill(state: dict, op: bytes, args, res_now) -> None:
    """Цвет заливки по операторам g/rg/k/cs/sc/scn — сам цвет букв текста,
    точнее любого замера по картинке страницы (сглаживание мелкого кегля
    делает чёрный серым)."""
    if op == b"cs":
        state["cs"] = _cs_n(args[0], res_now) if args else None
        state["fill"] = (0.0, 0.0, 0.0) if state["cs"] in (1, 3, 4) else None
        return
    if op == b"g":
        state["cs"] = 1
    elif op == b"rg":
        state["cs"] = 3
    elif op == b"k":
        state["cs"] = 4
    n = state["cs"]
    vals = [_num(a) for a in args]
    if n not in (1, 3, 4) or len(vals) < n or any(v is None for v in vals[:n]):
        state["fill"] = None
        return
    v = [min(1.0, max(0.0, float(t))) for t in vals[:n]]
    state["fill"] = ((v[0],) * 3 if n == 1 else tuple(v) if n == 3 else _cmyk(*v))


def page_lines(page) -> tuple:
    """(строки, геометрия | None) одной страницы pypdf.

    Геометрия: {"box": [x0, y0, x1, y1] страницы, "lines": [[x0, y, кегль,
    x1, начертание, семейство, начало последнего куска, места визуальных
    строк, x1 по метрикам шрифта (да/нет)] | None на каждую строку], "figs": [[x0, y0, x1, y1]
    картинок], "rects": [[x0, y0, x1, y1] нарисованных прямоугольников]}.
    y — базовая линия, ось вверх, как в самом PDF. Начертание («», «b»,
    «i», «bi») — из имени шрифта: распознаватель отмечает им полужирный
    и курсив, и выгрузка «как в оригинале» иначе напечатала бы всю книгу
    одним светлым начертанием. x1 — конец строки: где его показал
    следующий кусок той же строки — точно, иначе оценкой по числу знаков
    и ширине знака, замеренной на этой же странице. Строка без буквенных
    кусков или повёрнутая — None: гадать её место незачем."""
    chunks: list = []           # (текст, x, y, кегль, повёрнут)
    figs: list = []
    rects: list = []
    pending: list = []
    # Т11: границы КОНТУРОВ (path) — значки-маркеры пунктов, нарисованные
    # линиями, а не картинкой; `ppts` — точки текущего контура на листе.
    icons: list = []
    ppts: list = []
    # Т34: линии таблицы. Отрезки текущего контура (`m`/`l`) и тонкие
    # прямоугольники; обведённые (или залитые, если это полоска) — линии
    # листа. Вертикальная линия между кусками одной строки — граница ячейки
    # (`_h_groups`), горизонтальная между строками — граница ряда
    # (`pdftext._geo_follows`). Прежде линии таблиц, нарисованные обводкой,
    # не попадали никуда: `rects` собирает только `re`.
    psegs: list = []
    vrules: list = []
    hrules: list = []
    # Обрезка (clip) — прямоугольник, вне которого на странице не видно
    # НИЧЕГО. Текст за ней есть в текстовом слое, но не на листе: у боевого
    # PDF схема лежала дважды — вторая копия, сдвинутая на 23 пт и с иными
    # цифрами («500–1000»), была отрезана обтравкой, а выгрузка печатала
    # её перевод поверх видимой. Следим за прямоугольной обрезкой со
    # стеком q/Q; обрезка кривой — «не знаем», и она ничего не прячет.
    state = {"clip": False, "box": None, "curve": False, "seq": 0, "alpha": 1.0,
             # Кривая обрезка (Т19): области, путь в разборе, точка пера,
             # правило заполнения последнего `W`.
             "clips": (), "subs": [], "cur": None, "eo": False, "npts": 0,
             "tc": 0.0, "tw": 0.0, "tz": 100.0,
             # Цвет заливки (r, g, b) в долях — из операторов g/rg/k/sc/scn;
             # None — пространство, которого мы не понимаем (узор, плашечный
             # цвет). Режим отрисовки текста Tr: 3 — невидимый (слой
             # распознавания под снимком страницы), его цвет ничего не значит.
             "fill": (0.0, 0.0, 0.0), "cs": 1, "tr": 0}
    cstack: list = []
    dos: list = []                      # на каждый Do: вошли ли в форму (для `va`)
    ftext: list = []                    # текст, выданный внутри формы (по вложенности)
    dups: set = set()                   # номера кусков-повторов текста формы
    fb_last: list = [None]              # Ц1: прошлый оператор показа текста (подпись, точка)
    fb_pairs: list = []                 # Ц1: (y, знаков) операторов-повторов в той же точке
    fmats: list = []                    # матрица формы на листе (Matrix × cm у Do)
    stack: list = []
    astack: list = []
    tstack: list = []
    fonts: dict = {}                    # метрики шрифта по словарю шрифта
    op_ends: list = []                  # концы операторов показа текста
    op_recs: list = []                  # (x, y, угол°, кегль, знаков) каждого Tj/TJ
    forms: list = []                    # снимки состояния на входе в форму
    res_stack: list = []                # ресурсы форм, в которых мы сейчас

    def res_now():
        if res_stack:
            return res_stack[-1] or {}
        r_ = page.get("/Resources", {}) or {}
        return r_.get_object() if hasattr(r_, "get_object") else r_

    def xobj_of(name):
        try:
            xo = res_now().get("/XObject", {}) or {}
            xo = xo.get_object() if hasattr(xo, "get_object") else xo
            obj = xo.get(name) if hasattr(xo, "get") else None
            if obj is None and hasattr(xobjs, "get"):
                obj = xobjs.get(name)
            return obj.get_object() if hasattr(obj, "get_object") else obj
        except Exception:
            return None
    # Что нарисовано ПОВЕРХ: закрашенные (непрозрачные) прямоугольники
    # с номером по порядку рисования. Текст, который целиком накрыло нарисованное
    # позже, на листе не виден (у боевого PDF под схемой лежал абзац
    # другого раздела, и его перевод печатался поверх схемы).
    covers: list = []
    ccstack: list = []
    try:
        xobjs = page.get("/Resources", {}).get("/XObject", {}) or {}
        xobjs = xobjs.get_object() if hasattr(xobjs, "get_object") else xobjs
    except Exception:
        xobjs = {}

    def _style(fd) -> str:
        """«b» / «i» / «bi» по имени шрифта. Имя — единственное, что о
        начертании известно: глифы нам не видны."""
        try:
            name = fd if isinstance(fd, str) else (fd or {}).get("/BaseFont") or ""
            name = str(name).lower()
        except Exception:
            return ""
        # «c» — узкое начертание (Condensed, Narrow, Compressed): перевод
        # печатается тоже сжатым, иначе рядом с узкими подписями оригинала
        # он выглядит другим шрифтом.
        return ("b" if "bold" in name or "black" in name or "heavy" in name else "") +                ("i" if "italic" in name or "oblique" in name else "") +                ("c" if any(w in name for w in ("cond", "narrow", "compress")) else "")

    meta: dict = {}                     # (начертание, гарнитура) по шрифту

    def font_key(fd):
        # Ключ — ссылка на объект шрифта в файле: pypdf отдаёт посетителю
        # НОВЫЙ словарь на каждый кусок, и ключ по id разбирал бы шрифт
        # заново на каждый кусок (разбор книги вдвое дольше).
        ref = getattr(fd, "indirect_reference", None)
        if ref is not None:
            return (ref.idnum, ref.generation)
        try:
            return (str(fd.get("/BaseFont")), id(fd))
        except Exception:
            return (str(fd), 0)

    def style_family(fd):
        key = font_key(fd)
        if key not in meta:
            st, fam = _style(fd), _family(fd)
            # Имя молчит — спрашиваем сам шрифт: описание (вес, наклон,
            # толщина основы) и встроенную программу (OS/2, PANOSE, name).
            if fd is not None and (not fam or "b" not in st or "i" not in st):
                info = _program_info(fd)
                if "b" not in st and info.get("weight", 0) >= 600:
                    st = "b" + st
                if "b" not in st and "weight" not in info:
                    # Веса нет нигде — меряем основу буквы в контурах глифа.
                    try:
                        import font_weight
                        r = font_weight.stem_ratio(_descriptor(fd), get_font(fd),
                                                   str(fd.get("/Subtype") or ""))
                        if r is not None and r >= font_weight.BOLD_STEM:
                            st = "b" + st
                    except Exception:
                        pass
                if "i" not in st and info.get("italic"):
                    st = st + "i"
                if not fam:
                    fam = info.get("family") or (_family(info["name"]) if info.get("name") else "")
            meta[key] = (st, fam)
        return meta[key]

    def get_font(fd):
        key = font_key(fd)
        if key not in fonts:
            try:
                from pypdf._font import Font
                fonts[key] = Font.from_font_resource(fd)
            except Exception:
                fonts[key] = None
        return fonts[key]

    def op_end(op, args, cm, tm):
        """(начало x, базовая y, конец краски x, ключ шрифта) оператора показа
        текста — либо None.

        Конец считается так, как его считает сам PDF: СЫРЫЕ коды строки →
        ширины шрифта (`Font.character_widths` ключуется кодом), числа внутри
        TJ (кернинг и межсловные сдвиги выключки по формату), Tc, Tw, Tz —
        и через матрицу текста и cm. Конец — у последнего НЕ пробела. Текст
        куска pypdf для этого не годится: в нём уже нет чисел TJ, зато есть
        вставленные им пробелы. Знака нет в таблице ширин, шрифт неизвестен
        (у формы свои ресурсы), CMap не Identity — None, и строка идёт
        оценкой по краске."""
        fd, fsz = state.get("fd"), state.get("fs")
        if fd is None or not fsz or not args:
            return None
        font = get_font(fd)
        if font is None:
            return None
        ws = font.character_widths or {}
        try:
            enc = str(fd.get("/Encoding") or "")
            sub = str(fd.get("/Subtype") or "")
        except Exception:
            return None
        if sub == "/Type3":
            return None                 # ширины в своей матрице шрифта, не в 1/1000
        two = sub == "/Type0"
        if two and enc not in ("/Identity-H", "/Identity-V"):
            return None
        items = args[0] if op == b"TJ" else [args[0]]
        tc, tw, tz = state["tc"], state["tw"], state["tz"] / 100.0
        adv, ink = 0.0, None
        for it in items:
            if isinstance(it, (int, float)) or type(it).__name__ in ("NumberObject", "FloatObject"):
                adv -= float(it) / 1000.0 * fsz
                continue
            raw = getattr(it, "original_bytes", None)
            if raw is None:
                if isinstance(it, (bytes, bytearray)):
                    raw = bytes(it)
                else:
                    return None
            codes = ([(raw[k] << 8) | raw[k + 1] for k in range(0, len(raw) - 1, 2)]
                     if two else list(raw))
            for code in codes:
                wv = ws.get(chr(code))
                space = (code == 32 and not two)
                if not wv and not space:
                    return None
                adv += float(wv or font.space_width or 0) / 1000.0 * fsz
                if not space:
                    ink = adv
                adv += tc + (tw if space else 0.0)
        # Перо: pypdf не всегда сдвигает матрицу текста между подряд идущими
        # Tj одного BT — тогда второй оператор начался бы там же, где первый,
        # и его конец вышел бы короче настоящего. Пока матрица та же,
        # продвижение копится само.
        key_tm = tuple(round(float(v), 4) for v in tm)
        off = state["pen"][1] if state.get("pen") and state["pen"][0] == key_tm else 0.0
        state["pen"] = (key_tm, off + adv)
        if ink is None:
            return None
        ink += off

        def at(u):
            return _xy(cm, tm[0] * u * tz + tm[4], tm[1] * u * tz + tm[5])
        x0, y0 = at(off)
        x1, y1 = at(ink)
        ox, _oy = at(0.0)
        # 6 — начало ЦЕПОЧКИ (матрица текста без пера): второй Tj того же BT
        # начинается дальше начала последнего куска строки, а строке
        # принадлежит — по нему и судим.
        # 7 — разрядка (Tc) на листе, в пунктах: межбуквенный интервал
        # оригинала (Ш14, заголовки и стихи «вразрядку»).
        tx, ty = at(tc)
        bx_, by_ = at(0.0)
        tc_pt = ((tx - bx_) ** 2 + (ty - by_) ** 2) ** 0.5 * (1 if tc >= 0 else -1)
        return (x0, y0, x1, font_key(fd), y1, abs(y1 - y0) < 0.5, ox, tc_pt)

    def op_rec(op, args, cm, tm, got=None):
        """Точка, угол базовой линии, кегль и число знаков оператора показа
        текста — для пути повёрнутой строки и дуги: pypdf склеивает буквы
        дуги в один кусок с матрицей ПЕРВОЙ буквы, а у каждого Tj она своя."""
        import math
        fd, fsz = state.get("fd"), float(state.get("fs") or 0)
        two = False
        try:
            two = str(fd.get("/Subtype") or "") == "/Type0" if fd is not None else False
        except Exception:
            pass
        items = args[0] if op == b"TJ" else [args[0]]
        cmap_ = {}
        if two:
            try:
                cmap_ = getattr(get_font(fd), "character_map", None) or {}
            except Exception:
                cmap_ = {}
        n = 0
        for it in items:
            raw = getattr(it, "original_bytes", None)
            if raw is None and isinstance(it, (bytes, bytearray)):
                raw = bytes(it)
            if raw is None:
                continue
            if two:
                # Знаки — без пробелов, как и текст пути (`_rot_path`):
                # иначе каждая буква после пробела съезжала на точку соседа.
                n += sum(1 for k in range(0, len(raw) - 1, 2)
                         if cmap_.get(chr((raw[k] << 8) | raw[k + 1])) != " ")
            else:
                n += sum(1 for b_ in raw if b_ != 32)
        # Точка — с пером: у второго Tj того же BT матрица текста та же,
        # а начинается он там, где кончился первый.
        if got:
            x, y = got[0], got[1]
        else:
            x, y = _xy(cm, tm[4], tm[5])
        ba = tm[0] * cm[0] + tm[1] * cm[2]
        bb = tm[0] * cm[1] + tm[1] * cm[3]
        vx = tm[2] * cm[0] + tm[3] * cm[2]
        vy = tm[2] * cm[1] + tm[3] * cm[3]
        end = (round(got[2], 2), round(got[4], 2)) if got and len(got) > 4 else None
        return (round(x, 2), round(y, 2), math.degrees(math.atan2(bb, ba)),
                fsz * math.hypot(vx, vy), n, end)

    def vt(text, cm, tm, fd, fs):
        if fmats:
            got = "".join((text or "").split())
            if got and got == "".join(ftext[-1].split()):
                # pypdf отдаёт текст формы ЕЩЁ РАЗ одним куском в её точке
                # (и в чужих координатах). Куски изнутри формы уже стоят на
                # своих местах — повтор помечаем, `page_lines` попробует
                # геометрию без него.
                dups.add(len(chunks))
            else:
                ftext[-1] += text or ""
            cm = _mmul([float(v) for v in cm], fmats[-1])
        try:
            x, y = _xy(cm, tm[4], tm[5])
            import math
            vx = tm[2] * cm[0] + tm[3] * cm[2]
            vy = tm[2] * cm[1] + tm[3] * cm[3]
            # Кегль — длина «вертикали» знака на листе. Прежняя формула
            # (диагональ матриц) у текста, повёрнутого ДВАЖДЫ (повёрнутая
            # таблица на странице, поставленной прямо `pdf_panels`), давала
            # ноль и запасной 1.0: строки таблицы рвались на абзацы-строки.
            # Где диагональ не ноль, ответ прежний буква в букву.
            sy = abs(tm[3] * cm[3]) or math.hypot(vx, vy) or abs(tm[0] * cm[0]) or 1.0
            # Повёрнута — по направлению БАЗОВОЙ ЛИНИИ (матрица текста × cm),
            # а не по наклону: наклон (`Tm 1 0 0.21 1`) — это синтетический
            # курсив Word/Chrome, строка стоит ровно, и вынимать её из абзаца
            # нельзя. Зеркальная — тоже «повёрнута».
            ba = tm[0] * cm[0] + tm[1] * cm[2]
            bb = tm[0] * cm[1] + tm[1] * cm[3]
            rot = abs(bb) > 1e-3 * abs(ba) or ba <= 0
            box = state["box"]
            hidden = box is not None and not (box[0] - 1 <= x <= box[2] + 1
                                              and box[1] - 1 <= y <= box[3] + 1)
            state["seq"] += 1
            st_, fam_ = style_family(fd)
            # Ш42: синтетический курсив — «вертикаль» буквы наклонена вправо
            # (`Tm 1 0 0.2 1`): шрифт прямой, а читатель видит курсив, и
            # перевод подписи под блюдом выходил прямым.
            if "i" not in (st_ or "") and not rot:
                nb, nv = math.hypot(ba, bb), math.hypot(vx, vy)
                if nb > 0 and nv > 0:
                    sh_ = (vx * ba + vy * bb) / (nb * nv)
                    if SLANT_MIN <= sh_ <= SLANT_MAX:
                        st_ = (st_ or "") + "i"
            tr = state["tr"] % 8
            chunks.append((text or "", x, y, float(fs or 0) * sy, rot, st_, fam_,
                           hidden, state["seq"], font_key(fd) if fd is not None else None,
                           math.degrees(math.atan2(bb, ba)),
                           float(fs or 0) * math.hypot(vx, vy),
                           # Цвет краски — только у ВИДИМОЙ заливки букв.
                           state["fill"] if tr in (0, 2, 4, 6) else None))
        except Exception:
            chunks.append((text or "", None, None, 0.0, True, "", "", False, 0, None, 0.0, 0.0, None))

    def vo(op, args, cm, _tm):
        if fmats:
            cm = _mmul([float(v) for v in cm], fmats[-1])
        try:
            if op == b"q":
                cstack.append((state["fill"], state["cs"], state["tr"]))
                stack.append((state["box"], state["clips"]))
                ccstack.append(state.get("cclip") or ())
                astack.append(state["alpha"])
                tstack.append((state["tc"], state["tw"], state["tz"],
                               state.get("fd"), state.get("fs")))
                return
            if op == b"Q":
                if cstack:
                    state["fill"], state["cs"], state["tr"] = cstack.pop()
                state["box"], state["clips"] = stack.pop() if stack else (None, ())
                state["cclip"] = ccstack.pop() if ccstack else ()
                state["alpha"] = astack.pop() if astack else 1.0
                (state["tc"], state["tw"], state["tz"],
                 state["fd"], state["fs"]) = (tstack.pop() if tstack
                                              else (0.0, 0.0, 100.0, None, None))
                return
            if op in (b"BT", b"Tm", b"Td", b"TD", b"T*", b"'", b'"'):
                state["pen"] = None     # перо начинается заново
            if op == b"Tf" and len(args) >= 2:
                try:
                    fdict = (res_now().get("/Font", {}) or {})
                    fdict = fdict.get_object() if hasattr(fdict, "get_object") else fdict
                    fobj = fdict.get(args[0])
                    state["fd"] = fobj.get_object() if hasattr(fobj, "get_object") else fobj
                    state["fs"] = _num(args[1])
                except Exception:
                    state["fd"], state["fs"] = None, None
                return
            if op in (b"Tj", b"TJ"):
                try:
                    got = op_end(op, args, cm, _tm)
                except Exception:
                    got = None
                try:
                    rec_ = op_rec(op, args, cm, _tm, got)
                    op_recs.append(rec_)
                    sig_ = (op, repr(args[0] if args else None), font_key(state.get("fd"))
                            if state.get("fd") is not None else None)
                    lst_ = fb_last[0]
                    s_ = max(float(rec_[3] or 0), 1.0)
                    if (lst_ is not None and lst_[0] == sig_ and rec_[4] > 0
                            and abs(lst_[1][0] - rec_[0]) <= FAUX_BOLD_TOL * s_
                            and abs(lst_[1][1] - rec_[1]) <= FAUX_BOLD_TOL * s_):
                        fb_pairs.append((rec_[1], rec_[4]))
                        fb_last[0] = None
                    else:
                        fb_last[0] = (sig_, rec_)
                except Exception:
                    pass
                box = state["box"]
                if got is not None and (box is None or (box[0] - 1 <= got[0] <= box[2] + 1
                                                        and box[1] - 1 <= got[1] <= box[3] + 1)):
                    op_ends.append(got)         # оператор за обрезкой не считается
                return
            if op in _COLOR_OPS:
                _set_fill(state, op, args, res_now)
                return
            if op == b"Tr" and args:
                v = _num(args[0])
                if v is not None:
                    state["tr"] = int(v)
                return
            if op in (b"Tc", b"Tw", b"Tz") and args:
                v = _num(args[0])
                if v is not None:
                    state[{b"Tc": "tc", b"Tw": "tw", b"Tz": "tz"}[op]] = v
                return
            if op == b'"' and len(args) >= 2:
                tw, tc = _num(args[0]), _num(args[1])
                if tw is not None:
                    state["tw"] = tw
                if tc is not None:
                    state["tc"] = tc
                return
            if op == b"gs" and args:
                # Прозрачная закраска текст не прячет. Состояние, которого
                # не нашли в ресурсах (оно у формы), — «не знаем»: такая
                # закраска не считается накрывшей (лучше напечатать лишнее).
                try:
                    eg = (res_now().get("/ExtGState", {}) or {})
                    eg = eg.get_object() if hasattr(eg, "get_object") else eg
                    gsd = eg.get(args[0])
                    gsd = gsd.get_object() if hasattr(gsd, "get_object") else gsd
                    if gsd is None:
                        state["alpha"] = 0.0
                    else:
                        bm = str(gsd.get("/BM") or "/Normal")
                        state["alpha"] = (float(gsd.get("/ca", 1.0))
                                          if bm in ("/Normal", "/Compatible") else 0.0)
                except Exception:
                    state["alpha"] = 0.0
                return
            if op in (b"m", b"l", b"c", b"v", b"y"):
                state["curve"] = True
                nums = [_num(a) for a in args]
                if None not in nums and len(nums) >= 2 and len(psegs) < _RULES_MAX:
                    pt = _xy(cm, nums[-2], nums[-1])
                    if op == b"l" and state.get("lpen") is not None:
                        psegs.append((state["lpen"], pt))
                    state["lpen"] = pt
                if len(ppts) < _PATH_PTS_MAX and None not in nums:
                    for k_ in range(0, len(nums) - 1, 2):
                        ppts.append(_xy(cm, nums[k_], nums[k_ + 1]))
                return
            if op == b"re" and len(args) >= 4:
                x, y, w, h = (_num(a) for a in args[:4])
                if None in (x, y, w, h):
                    return
                pts = [_xy(cm, x, y), _xy(cm, x + w, y + h)]
                pending.append([min(p[0] for p in pts), min(p[1] for p in pts),
                                max(p[0] for p in pts), max(p[1] for p in pts)])
                if len(ppts) < _PATH_PTS_MAX:
                    ppts.extend(pts)
            elif op in _CLIP_OPS:
                state["clip"] = True
            elif op in _PAINT_OPS or op == b"n":
                if op != b"n" and not state["clip"] and not forms:
                    _rules_of(psegs if op in _STROKE_OPS else (), pending, vrules, hrules)
                psegs.clear()
                state["lpen"] = None
                if op != b"n" and not state["clip"]:
                    rects.extend(pending)
                    if ppts and len(icons) < _ICONS_MAX:
                        ic = [min(p_[0] for p_ in ppts), min(p_[1] for p_ in ppts),
                              max(p_[0] for p_ in ppts), max(p_[1] for p_ in ppts)]
                        if (ICON_MIN <= ic[2] - ic[0] <= ICON_MAX_PT
                                and ICON_MIN <= ic[3] - ic[1] <= ICON_MAX_PT):
                            icons.append(ic)
                    if (op not in (b"S", b"s") and state["alpha"] >= 0.99   # обводка не закрывает
                            and not forms):     # у формы своя система координат — не знаем
                        state["seq"] += 1
                        covers.extend((state["seq"], r, state.get("cclip") or ()) for r in pending)
                if (CURVE_SOFT and state["clip"] and state["curve"] and ppts and not forms
                        and len(ppts) <= CLIP_POINTS_MAX):
                    # Э3: кривая обрезка (круглое фото) — запоминается областью
                    # для решения «накрыто ли слово» (`_mark_covered`).
                    state["cclip"] = tuple(state.get("cclip") or ()) + (([list(ppts)], False),)
                if state["clip"] and pending and not state["curve"] and not forms:
                    clip = [min(r[0] for r in pending), min(r[1] for r in pending),
                            max(r[2] for r in pending), max(r[3] for r in pending)]
                    box = state["box"]
                    if box is not None:
                        clip = [max(clip[0], box[0]), max(clip[1], box[1]),
                                min(clip[2], box[2]), min(clip[3], box[3])]
                    state["box"] = clip
                pending.clear()
                ppts.clear()
                state["clip"] = False
                state["curve"] = False
            elif op == b"Do" and args:
                obj = xobj_of(args[0])
                dos.append(obj is not None and obj.get("/Subtype") == "/Form")
                if obj is not None and obj.get("/Subtype") == "/Form":
                    # «Do» формы — это q…Q по стандарту: всё, что форма
                    # поменяет (обрезка, шрифт, интервалы), после неё
                    # отменяется (`va`). Без этого обрезка из формы-логотипа
                    # прятала весь текст страницы после неё.
                    forms.append((state["box"], state["alpha"], state["tc"], state["tw"],
                                  state["tz"], state.get("fd"), state.get("fs"),
                                  len(stack), len(astack), len(tstack),
                                  (state["fill"], state["cs"], state["tr"]), len(cstack),
                                  state["clips"], len(ccstack), state.get("cclip") or ()))
                    r_ = obj.get("/Resources")
                    r_ = r_.get_object() if hasattr(r_, "get_object") else r_
                    res_stack.append(r_ if r_ is not None else res_now())
                    # pypdf исполняет форму со своей cm: точки внутри неё —
                    # в координатах формы, а на лист их переводит Matrix
                    # формы × cm у Do (× матрица внешней формы).
                    try:
                        fm = [float(v) for v in (obj.get("/Matrix") or [1, 0, 0, 1, 0, 0])]
                    except Exception:
                        fm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                    # cm здесь уже на листе (переведена на входе в `vo`).
                    fmats.append(_mmul(fm, [float(v) for v in cm]))
                    ftext.append("")
                    return
                if obj is not None and obj.get("/Subtype") == "/Image":
                    pts = [_xy(cm, 0, 0), _xy(cm, 1, 1)]
                    fig = [min(p[0] for p in pts), min(p[1] for p in pts),
                           max(p[0] for p in pts), max(p[1] for p in pts)]
                    figs.append(fig)
                    # Картинка текст НЕ «накрывает»: у скана с распознаванием
                    # слой текста бывает ПОД снимком страницы, и снимок — это
                    # и есть тот самый текст.
        except Exception:
            pass

    def va(op, args, cm, _tm):
        try:
            if op != b"Do" or not args:
                return
            # Имя НЕ ищем заново: оно ищется уже в ресурсах формы, и у формы
            # своё «/X0» бывает картинкой — тогда мы навсегда остались бы
            # «внутри формы». Что было у этого Do, запомнил `vo`.
            if not dos or not dos.pop() or not forms:
                return
            if fmats:
                fmats.pop()
            if ftext:
                t_ = ftext.pop()
                if fmats:
                    ftext[-1] += t_
            (state["box"], state["alpha"], state["tc"], state["tw"], state["tz"],
             state["fd"], state["fs"], n1, n2, n3, col_, n4, clips_, n5, cc_) = forms.pop()
            del ccstack[n5:]
            state["cclip"] = cc_
            state["clips"] = clips_
            state["fill"], state["cs"], state["tr"] = col_
            del cstack[n4:]
            del stack[n1:]
            del astack[n2:]
            del tstack[n3:]
            if res_stack:
                res_stack.pop()
            state["clip"], state["curve"] = False, False
            pending.clear()
            ppts.clear()
        except Exception:
            pass

    try:
        out = page.extract_text(visitor_text=vt, visitor_operand_before=vo,
                                visitor_operand_after=va) or ""
    except TypeError:
        # Старый pypdf или подмена без посетителей — строки без геометрии.
        return (page.extract_text() or "").splitlines(), None
    if FAUX_BOLD_DEDUP and fb_pairs:
        # Ц1: текст, напечатанный дважды в одной точке («ложный полужирный»:
        # обводка `1 Tr` и заливка `0 Tr` поверх), — ОДИН текст. pypdf
        # склеивает обе копии в один кусок, поэтому повтор вырезается из
        # текста куска по длинам операторов-повторов, а кусок — полужирный.
        # Число и порядок кусков не меняются (номера `dups` остаются верны).
        lines_ = out.splitlines()
        for keep_ in (lambda k: True, lambda k: k not in dups):
            if "".join(c[0] for k, c in enumerate(chunks) if keep_(k)).splitlines() == lines_:
                chunks = _faux_bold_strip(chunks, fb_pairs)
                out = "".join(c[0] for k, c in enumerate(chunks) if keep_(k))
                break
    lines = out.splitlines()
    try:
        vrules, hrules = _grid_rules(vrules, hrules)
        marked = _mark_covered(chunks, covers)
        # Разрез по линиям таблицы (Т34) — ПОСЛЕ отбора повтора формы: `dups`
        # хранит номера кусков до разреза, и после него выбросил бы не тот.
        used = _split_at_rules(marked, op_recs, vrules)
        geom = _geometry(lines, out, used, figs, rects, page, op_ends, op_recs, icons, (vrules, hrules))
        if geom is None and dups:
            # Текст формы пришёл дважды: изнутри (точки на своих местах)
            # и повтором в точке формы. Без повтора куски сложатся в ответ.
            used = _split_at_rules([c for k, c in enumerate(marked) if k not in dups], op_recs, vrules)
            geom = _geometry(lines, out, used, figs, rects, page, op_ends, op_recs, icons, (vrules, hrules))
        if geom is not None:
            lines = _script_marks(lines, used)
    except Exception:
        geom = None
    return lines, geom


# Ц1. Текст, напечатанный ДВАЖДЫ в одной точке. Симптом (статья «Бюллетеня
# сибирской медицины», проекты 105/106/110): колонтитул на каждой странице
# читался «Бюллетень сибирской медицины. Бюллетень сибирской медицины. 2026;
# 25 (3)2026; 25 (3): : 34–4034–40», перевод задваивался, а сам колонтитул,
# не похожий на себя на соседних страницах, не узнавался колонтитулом и
# вклеивался в абзац текста. Причина: вёрстка рисует «ложный полужирный» —
# тот же кусок обводкой (`1 Tr`) и сразу заливкой (`0 Tr`) с `0 0 TD`, и
# pypdf отдаёт текст дважды. Правило: кусок с тем же текстом тем же кеглем
# в той же точке (не дальше `FAUX_BOLD_TOL` кегля), идущий в пределах трёх
# кусков после такого же, — повтор: он выбрасывается из кусков и из ответа,
# а оставшийся считается полужирным (так его и видит читатель).
# `PDF_FAUX_BOLD=0` — без отбора.
FAUX_BOLD_DEDUP = os.environ.get("PDF_FAUX_BOLD", "1") != "0"
FAUX_BOLD_TOL = 0.25


def _undouble(text: str, lens: list) -> "tuple[str, int]":
    """Текст куска без повторов: `lens` — числа знаков (без пробелов)
    операторов-повторов по порядку. Ответ — (текст, сколько повторов снято)."""
    out, pos, got = [], 0, 0
    for n in lens:
        found = None
        for s0 in range(pos, len(text)):
            if text[s0].isspace() and n:
                continue
            cnt, m = 0, 0
            while s0 + m < len(text) and cnt < n:
                if not text[s0 + m].isspace():
                    cnt += 1
                m += 1
            if cnt < n:
                break
            # Хвостовые пробелы — часть оператора («медицины. »).
            for m2 in range(m, min(len(text) - s0, m + 4) + 1):
                if m2 and text[s0:s0 + m2] == text[s0 + m2:s0 + 2 * m2]:
                    found = (s0, m2)
                    break
            if found:
                break
        if not found:
            continue
        s0, m = found
        out.append(text[pos:s0 + m])
        pos = s0 + 2 * m
        got += 1
    out.append(text[pos:])
    return "".join(out), got


def _faux_bold_strip(chunks: list, pairs: list) -> list:
    """Куски без повторов «ложного полужирного» (Ц1): повторы ищутся в кусках
    своей базовой линии; кусок, где что-то снято, — полужирный."""
    res = []
    left = list(pairs)
    for c in chunks:
        if c[2] is None or not left:
            res.append(c)
            continue
        s = max(float(c[3] or 0), 1.0)
        mine = [p for p in left if abs(p[0] - c[2]) <= FAUX_BOLD_TOL * s]
        if not mine:
            res.append(c)
            continue
        t, got = _undouble(c[0] or "", [p[1] for p in mine])
        if not got:
            res.append(c)
            continue
        for p in mine[:got]:
            left.remove(p)
        res.append(_bold_chunk((t,) + tuple(c[1:])))
    return res


def _bold_chunk(c: tuple) -> tuple:
    st = c[5] if len(c) > 5 else ""
    if len(c) <= 5 or "b" in (st or ""):
        return c
    return c[:5] + (("b" + (st or "")) if st != "i" else "bi",) + c[6:]


# Над- и подстрочные знаки куском МЕЛЬЧЕ и выше/ниже строки (Т9): сноска
# «MACEᵃ», степень «m²», индекс «B₁₂». pypdf склеивает такой кусок со словом
# без пометки, и «MACEa» модель читала буквой слова («событияа» кириллицей),
# а «1,73 м2» печаталось обычной цифрой. Замена один к одному — длина строки
# та же, смещения геометрии верны. Буквы — только одиночная сноска a–e
# в надстрочном: «HbA1c» с подстрочным «1c» (у «c» нет подстрочной формы)
# остаётся как есть.
_SUP = dict(zip("0123456789+-=()abcde", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉ"))
_SUB = dict(zip("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"))
SCRIPT_SIZE_MAX = 0.8                # кегль куска не больше этой доли соседа
SCRIPT_RISE = (0.1, 0.9)            # сдвиг базовой линии в долях кегля соседа
SCRIPT_GAP = 0.6                     # кусок вплотную: не дальше доли кегля


def _is_script(c, prev) -> bool:
    """Кусок `c` — над- или подстрочный знак при слове `prev`."""
    if prev is None or prev[1] is None or prev[4]:
        return False
    t, pt = c[0], prev[0]
    core = t.strip()
    if not (1 <= len(core) <= 3) or t != t.lstrip() or "\n" in t or pt != pt.rstrip():
        return False
    if not (pt[-1:].isalnum() or pt[-1:] in ")]"):
        return False
    ps, cs = float(prev[3] or 0.0), float(c[3] or 0.0)
    if ps <= 0 or not (0 < cs <= SCRIPT_SIZE_MAX * ps):
        return False
    dy = float(c[2]) - float(prev[2])
    if not (SCRIPT_RISE[0] * ps <= abs(dy) <= SCRIPT_RISE[1] * ps):
        return False
    est_end = float(prev[1]) + 0.55 * ps * len(pt)
    if float(c[1]) < float(prev[1]) or float(c[1]) - est_end > SCRIPT_GAP * ps:
        return False
    table = _SUP if dy > 0 else _SUB
    letters = [ch for ch in core if ch.isalpha()]
    return all(ch in table for ch in core) and (not letters or (dy > 0 and len(core) == 1))


def _script_marks(lines: list, chunks: list) -> list:
    text = "".join(c[0] for c in chunks)
    if text.splitlines() != lines:
        return lines
    chars = list(text)
    pos = 0
    prev = None                         # кусок-слово, к которому прижат знак
    changed = False
    for c in chunks:
        t = c[0]
        a = pos
        pos += len(t)
        if c[1] is None or c[4] or not t.strip():
            if "\n" in t:
                prev = None
            continue
        if _is_script(c, prev):
            table = _SUP if float(c[2]) > float(prev[2]) else _SUB
            for i in range(a, a + len(t)):
                if chars[i] in table:
                    chars[i] = table[chars[i]]
                    changed = True
            continue                    # сосед следующего куска — прежнее слово
        prev = c
        if "\n" in t:
            prev = None
    if not changed:
        return lines
    out = "".join(chars).splitlines()
    return out if len(out) == len(lines) else lines


def _mark_covered(chunks: list, covers: list) -> list:
    """Куски, которые накрыло нарисованное ПОЗЖЕ (`covers`), — со знаком
    «за обрезкой» (поле 7): места на листе у них нет. Точка куска — его
    начало; накрытым считается начало ВНУТРИ закраски с запасом в пункт.
    Без numpy — не проверяем: лучше напечатать лишнее, чем потерять."""
    if not covers or not chunks:
        return chunks
    try:
        import numpy as np
    except ImportError:
        return chunks
    idx = [i for i, c in enumerate(chunks) if len(c) >= 9 and c[1] is not None and not c[7]]
    if not idx:
        return chunks
    xs = np.array([chunks[i][1] for i in idx], dtype=np.float64)
    ys = np.array([chunks[i][2] for i in idx], dtype=np.float64)
    ss = np.array([chunks[i][8] for i in idx], dtype=np.int64)
    # Закраска, нарисованная ДО всего текста (фон страницы, заливка ячеек),
    # не накрывает ничего — её не считаем вовсе.
    first = int(ss.min())
    cv = [c for c in covers if c[0] > first]
    if not cv:
        return chunks
    hit = np.zeros(len(idx), dtype=bool)
    soft_: dict = {}
    hard_: dict = {}
    for k in range(0, len(cv), 256):            # блоками: память — не квадрат
        part = cv[k:k + 256]
        seq = np.array([c[0] for c in part], dtype=np.int64)[None, :]
        box = np.array([c[1] for c in part], dtype=np.float64)
        m = ((seq > ss[:, None])
             & (box[None, :, 0] + 1 <= xs[:, None]) & (xs[:, None] <= box[None, :, 2] - 1)
             & (box[None, :, 1] + 1 <= ys[:, None]) & (ys[:, None] <= box[None, :, 3] - 1))
        if CURVE_CLIP:
            # Заливка под кривой обрезкой (Т19) красит только то, что внутри
            # неё: начало куска вне области — кусок не накрыт.
            for j, c in enumerate(part):
                if len(c) > 2 and c[2]:
                    for r_ in np.nonzero(m[:, j])[0]:
                        if not _in_clips(float(xs[r_]), float(ys[r_]), c[2]):
                            m[r_, j] = False
        hit |= m.any(axis=1)
        if CURVE_SOFT:
            # Э3: попадание только в прямоугольник заливки под КРИВОЙ обрезкой,
            # но не в саму обрезку (угол рамки круглого фото) — «мягкое».
            for j, c in enumerate(part):
                if len(c) > 2 and c[2] and not CURVE_CLIP:
                    for r_ in np.nonzero(m[:, j])[0]:
                        if not _in_clips(float(xs[r_]), float(ys[r_]), c[2]):
                            soft_[r_] = soft_.get(r_, 0) + 1
                        else:
                            hard_[r_] = True
                elif not (len(c) > 2 and c[2]):
                    for r_ in np.nonzero(m[:, j])[0]:
                        hard_[r_] = True
    if CURVE_SOFT and soft_:
        # Мягко накрытое слово открывается, только если на его базовой линии
        # рядом стоит открытое слово (строка текста обтекает фото): целиком
        # «накрытые» строки (подписи-дуги под панелью схемы) остаются как были.
        szs = [max(float(chunks[i][3] or 1.0), 1.0) for i in idx]
        for r_ in soft_:
            if hard_.get(r_):
                continue
            near = any(not hit[q] and abs(ys[q] - ys[r_]) <= 0.3 * szs[r_]
                       and abs(xs[q] - xs[r_]) <= 25 * szs[r_] for q in range(len(idx)))
            if near:
                hit[r_] = False
    if not hit.any():
        return chunks
    out = list(chunks)
    for j, i in enumerate(idx):
        if hit[j]:
            c = out[i]
            out[i] = c[:7] + (True,) + c[8:]
    return out


EXACT_CHAIN_GAP = 0.6
# Над- и подстрочный знак стоит выше или ниже базовой до 0.6 кегля — цепочку
# он не рвёт (у статьи 19 ссылка «7,8» поднята на 0.43 кегля).
EXACT_CHAIN_RISE = 0.6


def _other_row_at(row_starts: dict, x: float, y: float, me: int) -> bool:
    """Ц4: с этой точки начинается ДРУГАЯ строка ответа — её оператор не
    продолжает нашу («1, 2» надстрочником у «Брагина Е.Ю.» — своя строка
    pypdf, и цепочка через неё растягивала конец «Брагина» на индекс)."""
    xi, yi = int(round(x)), int(round(y))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if any(r != me for r in row_starts.get((xi + dx, yi + dy), ())):
                return True
    return False


TRACK_MIN = 0.03          # разрядка от этой доли кегля — не кернинг, а оформление


def _exact_ends(geo_lines: list, op_ends, op_recs=()) -> None:
    """Точный конец строки — по концам ОПЕРАТОРОВ показа текста (`op_end`).

    Оператор принадлежит строке, если стоит на её базовой линии, начался
    не раньше её начала и не правее начала её последнего куска (и раньше
    соседней строки справа), и набран шрифтом одного из кусков строки:
    шрифт у формы ищется по чужим ресурсам, и совпадение ключа — сверка,
    что ширины взяты у того самого шрифта. Конец строки — самый дальний
    конец таких операторов, и только если он не короче начала последнего
    куска (`xl`): иначе какой-то оператор строки посчитать не удалось.
    Поле 8 строки — «точный», 9 (ключи шрифтов) после сверки снимается."""
    rows = [(k, g) for k, g in enumerate(geo_lines) if g]
    # Ц4: кегль оператора по его точке — чтобы надстрочник («¹» строки
    # авторов) не «продолжался» оператором ОСНОВНОГО текста ниже себя.
    op_sz: dict = {}
    for r_ in op_recs or ():
        try:
            op_sz[(int(round(r_[0])), int(round(r_[1])))] = float(r_[3] or 0)
        except (TypeError, ValueError, IndexError):
            continue
    row_starts = {}
    for _k, g_ in rows:
        row_starts.setdefault((int(round(g_[0])), int(round(g_[1]))), []).append(id(g_))
    for k, g in rows:
        keys = g[9] if len(g) > 9 else set()
        # 9 — цвет краски, 10 — разрывы строки (`_line_gaps`).
        g[:] = g[:9] + [g[10] if len(g) > 10 else None, g[11] if len(g) > 11 else None, None]
        if not op_ends or not keys:
            continue
        x0, y, size, xl = g[0], g[1], max(g[2], 1.0), g[6]
        lim = min((h[0] for _j, h in rows if h is not g and abs(h[1] - y) <= 0.3 * size
                   and h[0] > x0 + 0.5 * size), default=None)
        best = None
        for o in op_ends:
            sx, sy, ex, key = o[:4]
            if len(o) > 5 and not o[5]:
                continue                # повёрнутый оператор — не этой строки
            if len(o) > 6:
                sx = min(sx, o[6])      # начало цепочки: Tj вслед за Tj того же BT
            # Оператор строки начинается не правее начала её ПОСЛЕДНЕГО куска:
            # всё, что начато дальше, — чужой текст на той же линии (у боевого
            # PDF конец строки схемы уезжал на 145 пт вправо).
            if (abs(sy - y) <= 0.3 * size and x0 - 0.5 <= sx <= xl + 0.5
                    and (lim is None or sx < lim - 0.5) and key in keys):
                best = ex if best is None else max(best, ex)
                if len(o) > 7 and o[7] and o[7] > TRACK_MIN * size:
                    # Ш14: разрядка строки — у её операторов (поле 11).
                    g[11] = round(max(g[11] or 0.0, float(o[7])), 2)
        # Строка продолжается и ЗА началом последнего куска: надстрочная
        # ссылка посреди строки («…memory.⁷,⁸ These effects have been»,
        # статья 19) — свой оператор, и pypdf кладёт ссылку и текст после неё
        # в один кусок; текст после ссылки — следующий оператор правее `xl`,
        # и конец строки вставал на ссылке — хвост оригинала не закрашивался
        # и проступал сквозь перевод. Оператор той же базовой линии и того же
        # шрифта, начатый ВПЛОТНУЮ к уже принятому (зазор не больше
        # межсловного, `EXACT_CHAIN_GAP` кегля), — тоже эта строка; чужой текст
        # той же линии стоит дальше и не цепляется.
        if best is not None:
            grown = True
            while grown:
                grown = False
                for o in op_ends:
                    sx, sy, ex, key = o[:4]
                    if len(o) > 5 and not o[5]:
                        continue
                    if (ex > best and best - 0.5 <= sx <= best + EXACT_CHAIN_GAP * size
                            and abs(sy - y) <= EXACT_CHAIN_RISE * size and key in keys
                            and (lim is None or ex <= lim)
                            and not (abs(sy - y) > 0.3 * size
                                     and op_sz.get((int(round(o[0])), int(round(sy))), 0.0) > 0.85 * size)
                            and not _other_row_at(row_starts, sx, sy, id(g))):
                        # Ц4: на ДРУГОЙ базовой линии цепочка идёт только через
                        # оператор МЕЛЬЧЕ строки (надстрочная ссылка посреди
                        # строки, Т33), а не через основной текст под надстрочником.
                        best, grown = ex, True
        if best is not None and best >= xl and (lim is None or best <= lim):
            g[3] = round(best, 1)
            g[8] = True


# Кривая обрезка и заливка поверх текста (Т19). Симптом: подписи по дуге
# (проект 14: «ACROSS LIFE COURSE» стр. 4 и 1, «STANDING», «STEPPING»,
# «STRENGTHENING» стр. 12) стояли в слое ровно под видимой надписью, но
# числились скрытыми («за обрезкой, под закраской»): печатала их только
# дорога картинок. Причина: заливка `re f` ПОЗЖЕ текста считается накрывшей весь
# свой прямоугольник, а красится она под кривой обрезкой (`m l … h W n` —
# сегмент кольца схемы) и на метку не ложится. Правило: кривая обрезка
# запоминается как область (многоугольники пути с разложенными кривыми
# Безье, правило нулевого числа витков либо чёт-нечёт у `W*`), стек q/Q
# и формы её хранят, а заливка накрывает кусок текста, только если его
# начало лежит и в прямоугольнике, и во всех областях обрезки. Область
# длиннее `CLIP_POINTS_MAX` точек и обрезка внутри формы — «не знаем»,
# как прежде.
# ПО УМОЛЧАНИЮ ВЫКЛЮЧЕНО (`PDF_CURVE_CLIP=1` — включить): правило раскрывает слой,
# который прежний разбор считал скрытым, — на проекте 14 это 7 подписей-дуг и 36
# строк слоя (стр. 12: нижние панели, стр. 19: ячейки схемы), сегодня их
# печатает дорога картинок. Блок картинки, повторяющий слой, отсеивается
# (`main._dup_of_layer`), но только от трёх слов и только строки с местом без
# пути: у одно-двухсловной дуги («STANDING», «STEPPING») отсева нет, и подпись
# печаталась дважды — слоем и картинкой (замер: стр. 12 проекта 14). Включать
# вместе с отсевом дуг в `_dup_of_layer` / `_layer_paras_by_page`.
# Сбор пути обрезки (операторы m/l/c/v/y/re в `vo`) в эту сборку НЕ внесён:
# он пересёкся со сбором контуров-значков (Т11) и ждёт отдельной проверки на
# живой выгрузке (двойная печать слоя и надписи картинки). Флаг выключен
# жёстко, чтобы включение окружением не обещало того, чего код не делает.
CURVE_CLIP = False
# Э3: заливка под кривой обрезкой «накрывает» слово только внутри обрезки,
# и только если слово не продолжает видимую строку (см. `_mark_covered`).
CURVE_SOFT = os.environ.get("PDF_CURVE_SOFT", "1") != "0"
CLIP_POINTS_MAX = 6000
_BEZ_STEPS = 8


def _bezier(p0, p1, p2, p3, n: int = _BEZ_STEPS) -> list:
    """Точки кривой Безье без начальной."""
    out = []
    for i in range(1, n + 1):
        t = i / float(n)
        u = 1.0 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _in_region(x: float, y: float, region) -> bool:
    """Точка внутри области обрезки (многоугольники, чёт-нечёт или ненулевое
    число витков)."""
    polys, evenodd = region
    wn = 0
    cross = 0
    for poly in polys:
        n = len(poly)
        if n < 3:
            continue
        x0, y0 = poly[-1]
        for x1, y1 in poly:
            if (y0 <= y) != (y1 <= y):
                xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if xi > x:
                    cross += 1
                    wn += 1 if y1 > y0 else -1
            x0, y0 = x1, y1
    return (cross % 2 == 1) if evenodd else (wn != 0)


def _in_clips(x: float, y: float, clips) -> bool:
    return all(_in_region(x, y, r) for r in clips or ())


# Вершина дуги (Т20). Симптом: «MEDITERRANEAN DIET» на синей дуге стр. 10
# оставалась строкой БЕЗ ПУТИ («осталось на языке оригинала ×4») и склеивалась
# в один абзац с соседними дугами. Причина: у дуги, нарисованной по кольцу,
# последняя буква стоит на вершине под углом ровно 0° (у 23 соседних — от 23.8°
# до 1.4°), у неё `rot` ложь, и путь строился только «если повёрнуты ВСЕ куски».
# Правило: строка с четырьмя и более кусками, где повёрнуты не меньше
# `ROT_APEX_SHARE` из них, а неповёрнутые лежат в пределах разброса углов
# повёрнутых (± `ROT_APEX_TOL`°), — повёрнута целиком. Обычная горизонтальная
# строка (повёрнутых нет) и строка таблицы боком (угол неповёрнутого — 0°,
# повёрнутых — 90°) не задеваются. `PDF_ROT_APEX=0` — без правила.
ROT_APEX_SHARE = 0.7
ROT_APEX_TOL = 6.0
ROT_APEX = os.environ.get("PDF_ROT_APEX", "1") != "0"


def _rotated_line(body: list, chunks: list) -> bool:
    """Строка повёрнута целиком: повёрнуты все её куски либо (Т20) все, кроме
    вершины дуги — куска с углом внутри разброса углов остальных."""
    rot = [bool(chunks[k][4]) for k in body]
    if all(rot):
        return True
    if not ROT_APEX or len(body) < 4 or sum(rot) < ROT_APEX_SHARE * len(body):
        return False
    try:
        ref = float(chunks[next(k for k in body if chunks[k][4])][10])

        def rel(k):
            return ((float(chunks[k][10]) - ref + 180.0) % 360.0) - 180.0
        spread = [rel(k) for k in body if chunks[k][4]]
        lo, hi = min(spread) - ROT_APEX_TOL, max(spread) + ROT_APEX_TOL
        return all(lo <= rel(k) <= hi for k in body if not chunks[k][4])
    except Exception:
        return False


def _rot_path(body: list, chunks: list, cw: float, op_ends, op_recs=()) -> "dict | None":
    """Путь повёрнутой строки: {pts: [[x, y, угол°, кегль, знаков, текст]…], end: [x, y],
    curved, st, fam} — либо None.

    Прямая строка (углы кусков сходятся в 2°) — подпись вдоль оси, повёрнутая
    таблица, корешок: перевод печатается повёрнутым целиком. Дуга (у каждой
    буквы свой угол — «STANDING» по кольцу схемы) — буква за буквой вдоль
    того же пути. Конец — по оператору показа текста, начатому в последнем
    куске (`op_end`, точка), иначе оценка по ширине знака."""
    import math
    pts = []
    for k in body:
        c = chunks[k]
        if len(c) < 12 or c[1] is None:
            return None
        pts.append([round(c[1], 2), round(c[2], 2), round(c[10], 2), round(c[11] or c[3], 2),
                    len(c[0].strip()), c[0].strip()])
    if not pts:
        return None
    # Точнее кусков — операторы: цепочка Tj/TJ от начала строки, пока не
    # набрано столько знаков, сколько в строке (у дуги — по букве).
    chars = "".join(p[5] for p in pts).replace(" ", "")
    start = next((j for j, o in enumerate(op_recs or ())
                  if abs(o[0] - pts[0][0]) <= 0.6 and abs(o[1] - pts[0][1]) <= 0.6), None)
    if start is not None:
        chain, got = [], 0
        for o in op_recs[start:]:
            if got >= len(chars) or not o[4]:
                if got >= len(chars):
                    break
                continue
            piece = chars[got:got + o[4]]
            chain.append([o[0], o[1], round(o[2], 2), round(o[3] or pts[0][3], 2), len(piece), piece,
                          list(o[5]) if len(o) > 5 and o[5] else None])
            got += o[4]
        if len(chain) >= 2 and got >= len(chars):
            # Пробелы между словами стоят в кусках — переносим их на точки.
            spaced = "".join(p[5] for p in pts)
            k_ = 0
            for pt in chain:
                out_ = ""
                for ch in pt[5]:
                    while k_ < len(spaced) and spaced[k_] == " ":
                        out_ += " "
                        k_ += 1
                    out_ += ch
                    k_ += 1
                pt[5] = out_
            pts = chain
    angs = [p[2] for p in pts]
    spread = max(abs(((a - angs[0]) + 180) % 360 - 180) for a in angs)
    last = pts[-1]
    end = None
    for o in op_ends or ():
        if len(o) > 4 and abs(o[0] - last[0]) <= 0.6 and abs(o[1] - last[1]) <= 0.6:
            end = [round(o[2], 2), round(o[4], 2)]
    if end is None:
        ln = last[4] * cw * last[3]
        end = [round(last[0] + ln * math.cos(math.radians(last[2])), 2),
               round(last[1] + ln * math.sin(math.radians(last[2])), 2)]
    c0 = chunks[body[0]]
    return {"pts": pts, "end": end, "curved": spread > 2.0,
            "st": c0[5] or "", "fam": c0[6] or "", "color": _chunk_color(body, chunks)}


def _line_parts(body: list, chunks: list, size: float, cw: float):
    """Места ВИЗУАЛЬНЫХ строк внутри одной строки ответа pypdf — либо None.

    pypdf рвёт строку по сдвигу базовой линии, и надстрочная цифра между
    двумя строками сноски этот сдвиг «гасит»: «Leicester, U.K.» и
    «²NIHR Leicester Biomedical Research Centre,» приходят ОДНОЙ строкой.
    Текст строки менять нельзя (он сверяется буква в букву), а место —
    можно: куски группируются по базовой линии, и каждая группа становится
    своим местом [x0, базовая, кегль, x1-оценка, начало последнего куска,
    знаков в ней].
    Мелкий короткий кусок (надстрочник) своей группы не образует.
    Одна группа — тоже место, если строка числится по надстрочнику."""
    groups: list = []
    for k in body:
        c = chunks[k]
        t = c[0].strip()
        sz = c[3] or size
        if len(t) <= 3 and sz < 0.85 * size:
            continue                    # надстрочная цифра, знак сноски
        for g in groups:
            if abs(g["y"] - c[2]) <= 0.5 * max(size, 1.0):
                break
        else:
            g = {"y": c[2], "s": sz, "x0": c[1], "x1": c[1], "xl": c[1], "n": 0}
            groups.append(g)
        g["x0"] = min(g["x0"], c[1])
        g["xl"] = max(g["xl"], c[1])
        g["x1"] = max(g["x1"], c[1] + len(c[0].strip("\n").rstrip()) * cw * sz)
        g["n"] += len(t)
    if not groups:
        return None
    if len(groups) == 1:
        # Одна визуальная строка — место нужно, только если строка ответа
        # числится по надстрочнику (сноска «¹Diabetes Research Centre»:
        # высота и кегль строки — у цифры, и перевод вставал бы между
        # строками оригинала). Высоту строки для разбора не трогаем — на
        # ней стоит склейка дробей и индексов (`pdftext._join_scripts`).
        g = groups[0]
        if abs(g["y"] - chunks[body[0]][2]) <= 0.3 * max(size, 1.0) and g["s"] >= 0.85 * size:
            return None
    return [[round(g["x0"], 1), round(g["y"], 1), round(g["s"], 2), round(g["x1"], 1),
             round(g["xl"], 1), g["n"]] for g in groups]


def _geometry(lines, out, chunks, figs, rects, page, op_ends=(), op_recs=(), icons=(), rules=((), ())):
    text = "".join(c[0] for c in chunks)
    _set_chunk_starts(chunks)
    if text.splitlines() != lines:
        return None                      # куски не сложились в ответ — не гадаем
    owner = []                          # номер куска на каждый знак
    starts = []                         # смещение начала каждого куска
    for k, c in enumerate(chunks):
        starts.append(len(owner))
        owner.extend([k] * len(c[0]))
    # Ширина знака этой страницы: кусок, за которым на той же строке стоит
    # следующий, показывает свою настоящую длину.
    ratios = []
    for k in range(len(chunks) - 1):
        a, b = chunks[k], chunks[k + 1]
        if (a[1] is None or b[1] is None or a[4] or not a[0].strip() or "\n" in a[0]
                or a[3] <= 0 or abs(a[2] - b[2]) > 0.3 * a[3] or b[1] <= a[1]):
            continue
        ratios.append((b[1] - a[1]) / (len(a[0]) * a[3]))
    ratios = [r for r in ratios if 0.2 < r < 1.2]
    cw = statistics.median(ratios) if len(ratios) >= 3 else _CHAR_W
    ends = _ends_index(op_ends)
    cols = _col_starts(text, owner, starts, chunks, cw, ends)
    geo_lines = []
    rot_paths: dict = {}
    splits: dict = {}
    pos = 0
    for raw in text.splitlines(keepends=True):
        a, b = pos, pos + len(raw)
        pos = b
        ks = sorted(set(owner[a:b]))
        # Место строки — по кускам, которые на ней НАЧИНАЮТСЯ: у куска,
        # перетёкшего с прошлой строки («покупате\xad\nлю»), координаты
        # прошлой строки.
        body = [k for k in ks if starts[k] >= a and chunks[k][0].strip()
                and chunks[k][1] is not None]
        if body and all(len(chunks[k]) > 7 and chunks[k][7] for k in body):
            # Строка ЦЕЛИКОМ невидима (за обрезкой, под закраской) — пустое
            # место `[]`, а не None: повёрнутая строка бывает частью фразы
            # и остаётся в её потоке, невидимая — никогда (у боевого PDF
            # отрезанная копия схемы иначе вливалась в видимые абзацы).
            geo_lines.append([])
            continue
        if not body or any(chunks[k][4] for k in body):
            # Повёрнутая строка: у разбора абзацев места нет (None), но путь
            # её на листе известен — точки и углы кусков (`rot`): по нему
            # выгрузка печатает перевод повёрнутым или по дуге.
            geo_lines.append(None)
            if body and _rotated_line(body, chunks):
                rot_paths[len(geo_lines) - 1] = _rot_path(body, chunks, cw, op_ends, op_recs)
            continue
        groups = _h_groups(body, chunks, cw, cols, ends, rules[0])
        if len(groups) > 1:
            # pypdf склеил в одну строку ДВЕ надписи одной базовой линии
            # с разных концов листа («making» в рамке посреди схемы
            # и «DO NOT JUST FOCUS» у левого края). Текст строки менять
            # нельзя — режем МЕСТО: строка делится по смещениям кусков, и
            # каждая часть получает свою геометрию (`split`).
            subs = []
            for gi, grp in enumerate(groups):
                # Первая часть — с начала строки: ведущий пробельный кусок
                # (или перетёкший с прошлой строки) — её, иначе смещение
                # первой части не ноль и разбор отверг бы деление целиком.
                lo = a if gi == 0 else starts[grp[0]]
                hi = starts[groups[gi + 1][0]] if gi + 1 < len(groups) else b
                sub_ks = [k for k in ks if lo <= starts[k] < hi]
                subs.append([lo - a, _line_geo(sub_ks, grp, chunks, starts, lo, cw, ends)])
            geo_lines.append(subs[0][1])
            splits[len(geo_lines) - 1] = subs
            continue
        geo_lines.append(_line_geo(ks, body, chunks, starts, a, cw, ends))
    # Одна строка ответа — одна строка геометрии; иначе смысла в ней нет.
    if len(geo_lines) != len(lines):
        return None
    _exact_ends(geo_lines + [sg[1] for subs in splits.values() for sg in subs[1:]], op_ends, op_recs)
    try:
        mb = page.mediabox
        box = [float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)]
    except Exception:
        box = None
    r1 = lambda v: [round(float(t), 1) for t in v]   # noqa: E731
    out_ = {"box": r1(box) if box else None, "lines": geo_lines,
            "figs": [r1(f) for f in figs], "rects": [r1(r) for r in rects],
            "hrules": [r1(r) for r in rules[1]], "vrules": [r1(r) for r in rules[0]],
            "rot": {str(k): v for k, v in rot_paths.items() if v}}
    near = _icons_near(icons, geo_lines + [sg[1] for subs in splits.values() for sg in subs[1:]])
    if near:
        out_["icons"] = [r1(i_) for i_ in near]
    if splits:
        out_["split"] = {str(k): [[off, g_] for off, g_ in subs] for k, subs in splits.items()}
    return out_


# Т11. Значок-маркер пункта, нарисованный КОНТУРОМ (галочка, шприц, кружок
# в инфографике): не картинка, поэтому `figs` его не знал, и пункты, идущие
# подряд с обычным интервалом, склеивались в один абзац (стр. 4 и 31 проекта
# 14: «Psychological… depression Periodontal health»). Контур в 1.5–14 пт,
# закрашенный или обведённый, запоминается; в ответ идут только те, что
# стоят у начала какой-нибудь строки (слева, не дальше 2.6 кегля) — остальное
# на листе рисунок, и тысячи его мелких контуров отдавать незачем. Решает,
# маркер это или нет, `pdftext._mark_icon_bullets` (с защитами).
ICON_MIN = 1.5
ICON_MAX_PT = 14.0
_ICONS_MAX = 20000
_PATH_PTS_MAX = 4000


def _icons_near(icons, geo_lines) -> list:
    out: list = []
    starts = []
    for g in geo_lines:
        if g and len(g) >= 3:
            try:
                starts.append((float(g[0]), float(g[1]), max(float(g[2] or 0.0), 1.0)))
            except (TypeError, ValueError):
                continue
    if not starts or not icons:
        return out
    # Начала строк по высоте — кандидаты значка берутся бисекцией, а не
    # перебором всех строк: страница с тысячами контуров (карта, график)
    # иначе давала миллионы проверок на единственном воркере.
    import bisect
    starts.sort(key=lambda t: t[1])
    ys = [t[1] for t in starts]
    smax = max(t[2] for t in starts)
    smin = min(t[2] for t in starts)
    for ic in icons:
        w, h = ic[2] - ic[0], ic[3] - ic[1]
        if not (0.3 * smin <= w <= 2.5 * smax and 0.3 * smin <= h <= 2.5 * smax):
            continue
        lo = bisect.bisect_left(ys, ic[1] - 0.9 * smax)
        hi = bisect.bisect_right(ys, ic[3] + 0.3 * smax)
        for x0, y, s in starts[lo:hi]:
            if (x0 - 2.6 * s <= ic[2] <= x0 + 0.3 * s
                    and min(y + 0.9 * s, ic[3]) - max(y - 0.3 * s, ic[1]) > 0.3 * s):
                out.append(ic)
                break
    return out


# Зазор (в кеглях) между кусками ОДНОЙ базовой линии, после которого это
# уже другая надпись: межсловный пробел — четверть кегля, табуляция
# в таблице — пара кеглей, а подписи схемы разнесены на десятки.
SPLIT_GAP = 3.0
# Куски РАЗНЫХ базовых линий одной строки pypdf, разделённые по горизонтали
# хотя бы таким зазором (в кеглях), — разные надписи (`_h_groups`).
V_SPLIT_GAP = 1.0


# Начало колонки таблицы: зазор перед куском от этой доли кегля, и с того же
# места (в этом допуске, пт) начинаются куски ещё хотя бы одной строки.
COL_GAP = 0.5
COL_TOL = 1.5


def _ends_index(op_ends) -> dict:
    """{(x, y) начала оператора, округлённые: конец его краски} — у прямых
    операторов. Конец куска по ширине знака — оценка, и у узкой колонки
    таблицы она съедала зазор до соседней ячейки целиком."""
    out: dict = {}
    for o in op_ends or ():
        if len(o) > 5 and not o[5]:
            continue
        k = (int(round(o[0])), int(round(o[1])))
        out[k] = max(out.get(k, o[2]), o[2])
    return out


def _chunk_end_exact(c, ends: dict):
    """Точный конец краски куска (по оператору показа текста) либо None."""
    if ends and c[1] is not None:
        x, y = int(round(c[1])), int(round(c[2]))
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                e = ends.get((x + dx, y + dy))
                if e is not None and e > c[1]:
                    return e
    return None


def _chunk_end(c, cw: float, ends: dict) -> float:
    """Конец краски куска: по оператору, начатому в его точке, иначе оценка.

    Ц3: кусок pypdf бывает собран из НЕСКОЛЬКИХ операторов подряд («С»,
    «развитием … вариант», «rs10905277 гена»): конец первого — не конец
    куска, и оценка «конец = первый оператор» объявляла пропастью весь
    остаток строки (курсивное «GATA3» после неё становилось отдельной
    надписью). Операторы, начатые вплотную к концу предыдущего (не дальше
    `CHAIN_GAP` кегля) на той же базовой линии, идут цепочкой — до границы
    оценки куска с запасом."""
    size = max(c[3] or 1.0, 1.0)
    est = c[1] + len(c[0].strip()) * cw * size
    if ends:
        x, y = int(round(c[1])), int(round(c[2]))
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                e = ends.get((x + dx, y + dy))
                if e is not None and e > c[1]:
                    ch = (_chain_end(ends, e, c[2], size, est + 0.3 * max(0.0, est - c[1]) + 2 * size,
                                     _next_start(c))
                          if CHAIN_GAP > 0 else e)
                    if ch > e:
                        return ch
                    return min(est, e) if est > c[1] else e
    return est


CHAIN_GAP = float(os.environ.get("PDF_CHAIN_GAP", "0.6"))  # 0 — выключить (Ц3)


# Начала кусков страницы по высоте — чтобы цепочка операторов (Ц3) не
# заходила в СОСЕДНИЙ кусок той же строки («Loss (intermediate)» и ячейка
# «Beneﬁt:» вплотную справа в инфографике проекта 14). Ставит `_geometry`.
_CHUNK_STARTS: dict = {}


def _set_chunk_starts(chunks: list) -> None:
    _CHUNK_STARTS.clear()
    for c in chunks:
        if c[1] is not None and c[2] is not None and (c[0] or "").strip():
            _CHUNK_STARTS.setdefault(int(round(c[2])), []).append(float(c[1]))
    for v in _CHUNK_STARTS.values():
        v.sort()


def _next_start(c) -> "float | None":
    """Начало ближайшего куска правее `c` на той же базовой линии."""
    yy = int(round(c[2]))
    best = None
    for dy in (-1, 0, 1):
        for x in _CHUNK_STARTS.get(yy + dy, ()):
            if x > c[1] + 0.5 and (best is None or x < best):
                best = x
                break
    return best


def _chain_end(ends: dict, e: float, y: float, size: float, bound: float, stop: "float | None" = None) -> float:
    """Конец цепочки операторов, начатых вплотную один за другим (Ц3); оператор,
    начатый в начале СЛЕДУЮЩЕГО куска (`stop`) и дальше, — уже не наш. Есть
    такая граница — оценочный потолок `bound` не нужен: оценка по ширине знака
    бывает короче настоящего конца, и цепочка обрывалась посреди куска
    (ложный разрыв строки 165–373 пт, где оригинал не стирался)."""
    yy = int(round(y))
    if stop is not None:
        bound = max(bound, stop + 0.5)
    for _ in range(200):
        nxt = None
        for kx in range(int(e) - 1, int(e + CHAIN_GAP * size) + 2):
            for dy in (0, -1, 1):
                v = ends.get((kx, yy + dy))
                if (v is not None and v > e + 0.1 and kx >= e - 1.0 and v <= bound
                        and (stop is None or kx < stop - 0.5)):
                    nxt = v if nxt is None else max(nxt, v)
        if nxt is None:
            return e
        e = nxt
    return e


def _col_starts(text: str, owner: list, starts: list, chunks: list, cw: float,
                ends: "dict | None" = None) -> list:
    """Иксы, с которых начинаются куски после заметного зазора хотя бы
    в ДВУХ строках страницы, — начала колонок таблицы. Ячейки таблицы стоят
    теснее, чем `SPLIT_GAP` кеглей (у боевой таблицы 1.7–2.4 кегля), и без
    этого соседние ячейки одной строки сливались в одну надпись; совпадение
    начала с другой строкой отличает колонку от широкого пробела в тексте."""
    seen: list = []
    pos = 0
    # Конец уже пройденного — ПО БАЗОВОЙ ЛИНИИ и через границу строк pypdf:
    # строку таблицы он рвёт на несколько строк ответа (между ними — вторая
    # строка соседней ячейки), и первая ячейка такой строки иначе не
    # считалась бы стоящей после зазора.
    lines_end: list = []                # [[y, конец], …]
    for li, raw in enumerate(text.splitlines(keepends=True)):
        a, b = pos, pos + len(raw)
        pos = b
        ks = [k for k in sorted(set(owner[a:b])) if starts[k] >= a and chunks[k][0].strip()
              and chunks[k][1] is not None and not chunks[k][4]]
        for k in ks:
            c = chunks[k]
            sz = max(c[3] or 1.0, 1.0)
            row = next((r for r in lines_end if abs(r[0] - c[2]) <= 0.5 * sz), None)
            end = _chunk_end(c, cw, ends)
            if row is None:
                lines_end.append([c[2], end])
                continue
            if c[1] < row[1] - 0.5 * sz:
                row[1] = end                # поток вернулся влево — другая строка
                continue
            if c[1] - row[1] >= COL_GAP * sz:
                seen.append((c[1], id(row)))
            row[1] = max(row[1], end)
    # Строка таблицы — та, где таких начал хотя бы два (три ячейки и больше
    # на одной линии): одиночный широкий пробел в строке текста колонкой
    # не свидетельствует, сколько бы строк его ни повторили.
    per_row = Counter(r for _x, r in seen)
    seen = sorted(t for t in seen if per_row[t[1]] >= 2)
    out = []
    i = 0
    while i < len(seen):
        j = i
        while j + 1 < len(seen) and seen[j + 1][0] - seen[i][0] <= COL_TOL:
            j += 1
        if len({r for _x, r in seen[i:j + 1]}) >= 2:
            out.append(seen[i][0])
        i = j + 1
    return out


# Т34. Линия листа — отрезок не короче `RULE_MIN` пт и не толще `RULE_THIN`
# пт по другой оси; `_RULES_MAX` — потолок на страницу (сетки графиков
# бывают из тысяч отрезков, а нужны линии таблиц).
RULE_MIN = 4.0
RULE_THIN = 1.5
RULE_FILL_MIN = 0.25
_RULES_MAX = 4000
_STROKE_OPS = {b"S", b"s", b"B", b"B*", b"b", b"b*"}


def _rules_of(segs, pending, vrules: list, hrules: list) -> None:
    """Обведённые отрезки и тонкие прямоугольники → вертикальные и
    горизонтальные линии [x0, y0, x1, y1] (координаты листа)."""
    if len(vrules) + len(hrules) >= _RULES_MAX:
        return
    for (x0, y0), (x1, y1) in segs:
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        if dx <= RULE_THIN * 0.5 and dy >= RULE_MIN:
            vrules.append([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)])
        elif dy <= RULE_THIN * 0.5 and dx >= RULE_MIN:
            hrules.append([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)])
    for r in pending:
        w, h = r[2] - r[0], r[3] - r[1]
        # Полоска тоньше `RULE_FILL_MIN` — ступенька градиентной заливки
        # (стопка по 0.1 пт у инфографики проекта 14), а не линейка.
        if RULE_FILL_MIN <= w <= RULE_THIN and h >= RULE_MIN:
            vrules.append(list(r))
        elif RULE_FILL_MIN <= h <= RULE_THIN and w >= RULE_MIN:
            hrules.append(list(r))


GRID_TOL = 1.2           # пт: конец линии «упирается» в другую
GRID_END_TOL = 3.0       # пт: по высоте конца вертикали у горизонтали (выступ пера)
GRID_PAIRS_MAX = 400000  # вертикалей × горизонталей: дороже — это рисунок, и проверять его некогда


def _grid_rules(vrules: list, hrules: list) -> tuple:
    """Т34. Линии ТАБЛИЦЫ — только те, что складываются в сетку. Вертикаль
    считается, если оба её конца упираются в горизонтали; горизонталь —
    если касается такой вертикали концом или пересекает её. Таких вертикалей
    на странице хотя бы две (одна закрытая ячейка). Иначе это рисунок:
    стрелки, значки и подчёркивания инфографики (проект 14), принятые за
    границы ячеек, резали подписи по словам («Consider | specific |
    factors») и рвали абзацы под декоративной чертой."""
    t = GRID_TOL
    if len(vrules) * len(hrules) > GRID_PAIRS_MAX:
        return [], []                   # густая сетка штрихов — диаграмма, не таблица

    def touches(x, y):
        # Конец вертикали — у горизонтали с допуском GRID_END_TOL: линии
        # таблиц выступают за крайнюю горизонталь на толщину пера и неточность
        # генератора (корпус выгрузки, счёт: 2 пт), и при 1.2 пт вся сетка
        # пропадала — ячейки склеивались через линию.
        return any(abs((h[1] + h[3]) / 2.0 - y) <= GRID_END_TOL and h[0] - t <= x <= h[2] + t
                   for h in hrules)
    vs = [v for v in vrules if touches((v[0] + v[2]) / 2.0, v[1]) and touches((v[0] + v[2]) / 2.0, v[3])]
    if len(vs) < 2:
        return [], []
    hs = []
    for h in hrules:
        y = (h[1] + h[3]) / 2.0
        if any(v[1] - t <= y <= v[3] + t and h[0] - t <= (v[0] + v[2]) / 2.0 <= h[2] + t for v in vs):
            hs.append(h)
    return vs, hs


# Ц3. Две надписи одной базовой линии В ОДНОМ куске. Симптом (колонтитул
# журнала: слева «Мелентьева А.П., … и др.», справа «Ассоциация полиморфизма
# гена GATA3 (rs10905277)»): pypdf отдаёт обе надписи одним куском, и у строки
# одно начало и одна оценка конца — левой надписи. Правая оказывалась вне
# строки: курсивный «GATA3 (rs10905277)» становился отдельным абзацем, а
# прямой «Ассоциация полиморфизма гена» — «краской вне слоя», которую разбор
# картинок читал заново и печатал поверх. Правило: кусок режется по
# операторам показа текста и там, где следующий оператор начат дальше
# `OP_GAP_SPLIT` кегля от КОНЦА предыдущего (такого межсловного пробела
# не бывает и в разрядке): дальше разбор видит две надписи (`_h_groups`).
# `PDF_OP_GAP_SPLIT=0` — не резать.
OP_GAP_SPLIT = float(os.environ.get("PDF_OP_GAP_SPLIT", "3.0"))


def _op_gap(o1, o2, size: float) -> bool:
    if not OP_GAP_SPLIT or len(o1) < 6 or not o1[5]:
        return False
    return (abs(o2[1] - o1[1]) <= 0.3 * size
            and o2[0] - float(o1[5][0]) > OP_GAP_SPLIT * size)


def _split_at_rules(chunks: list, op_recs: list, vrules: list) -> list:
    """Т34. pypdf отдаёт строку ряда таблицы ОДНИМ куском («SNP (ген) Гено- »),
    хотя внутри она нарисована отдельными операторами в разных ячейках.
    Кусок режется по операторам показа текста: операторы куска — подряд по
    потоку, первый стоит в точке куска, их знаков (без пробелов) ровно
    столько, сколько в куске. Между соседними операторами стоит вертикальная
    линия, проходящая через строку, — здесь граница ячейки, и кусок делится
    на два с началом второго в точке его оператора. Текст строки от этого
    не меняется (половинки подряд дают тот же текст); не сошлось число
    знаков — кусок не трогаем: резать наугад нельзя."""
    if not op_recs or (not vrules and not OP_GAP_SPLIT):
        return chunks
    at: dict = {}
    for k_, o_ in enumerate(op_recs):
        at.setdefault(int(round(o_[0])), []).append(k_)
    out, pos = [], 0
    for c in chunks:
        if c[1] is None or c[4] or not c[0].strip() or len(c) < 8 or c[7]:
            out.append(c)
            continue
        size = max(c[3] or 1.0, 1.0)
        want = sum(1 for ch in c[0] if not ch.isspace())
        xi = int(round(c[1]))
        j = min((k for dx in (-1, 0, 1) for k in at.get(xi + dx, ())
                 if k >= pos and abs(op_recs[k][0] - c[1]) <= 0.6 and abs(op_recs[k][1] - c[2]) <= 0.3 * size),
                default=None)
        if j is None:
            out.append(c)
            continue
        ops, got = [], 0
        for k in range(j, len(op_recs)):
            o = op_recs[k]
            # pypdf сливает в одну строку и куски соседней базовой линии
            # (ячейки шапки выше и ниже соседних) — цепочкой: каждый
            # следующий с предыдущим, тот же допуск.
            if abs(o[1] - (ops[-1][1] if ops else c[2])) > 0.8 * size:
                break
            ops.append(o)
            got += o[4]
            if got >= want:
                break
        if got != want or len(ops) < 2:
            out.append(c)
            continue
        pos = j + len(ops)
        cuts = []                                   # (знаков до разреза, x второго)
        acc = 0
        for o1, o2 in zip(ops, ops[1:]):
            acc += o1[4]
            if _rule_between(vrules, o1[0], o2[0], (o1[1] + o2[1]) / 2.0, size) or _op_gap(o1, o2, size):
                cuts.append((acc, o2[0]))
        if not cuts:
            out.append(c)
            continue
        text, n, ci = c[0], 0, 0
        bounds, xs = [0], [c[1]]
        for i, ch in enumerate(text):
            if ci < len(cuts) and n == cuts[ci][0] and not ch.isspace():
                bounds.append(i)
                xs.append(cuts[ci][1])
                ci += 1
            if not ch.isspace():
                n += 1
        bounds.append(len(text))
        ys = [c[2]] + [next(o[1] for o in ops if o[0] == x_) for x_ in xs[1:]]
        for k in range(len(xs)):
            out.append((text[bounds[k]:bounds[k + 1]], xs[k], ys[k]) + tuple(c[3:]))
    return out


def _in_ruled(vrules, y, size, x=None) -> bool:
    """Т35. На странице с расчерченной таблицей (есть вертикальные линии)
    начала колонок (`_col_starts`) режут только строки ВНУТРИ таблицы — по
    высоте её вертикальных линий. Вне её колонок нет: широкий пробел
    выключенной по ширине строки перед курсивом («гена | GATA3») давал
    ложное «начало колонки», и оно резало заголовок таблицы над линиями
    на куски, а перевод собирался из них в русском порядке слов. Без линий
    на странице — как прежде (таблица без линейки держится на `_col_starts`)."""
    if not vrules:
        return True
    xs = [r[0] for r in vrules if r[1] - 0.5 * size <= y <= r[3] + 0.5 * size]
    if len(xs) < 2:
        return False
    # Колонки — только в пределах ширины таблицы на этой высоте: таблица без
    # линейки сбоку от расчерченной своё разбиение не теряет.
    return x is None or min(xs) - 2.0 * size <= x <= max(xs) + 2.0 * size


def _rule_between(vrules, xa, xb, y, size) -> bool:
    """Вертикальная линия строго между x началом прошлого куска `xa` и
    началом этого `xb`, и через базовую линию `y` она проходит."""
    if not vrules or xa is None or xb is None or xb <= xa:
        return False
    for r in vrules:
        xm = (r[0] + r[2]) / 2.0
        if xa + 0.5 < xm < xb - 0.2 and r[1] - 0.2 * size <= y <= r[3] + 0.6 * size:
            return True
    return False


_ENDS_BY_Y: list = [None, None]


def _ends_by_y(ends: dict) -> dict:
    """{y: [(x начала, конец)]} — индекс `ends` по высоте; последний помнится."""
    if _ENDS_BY_Y[0] is not ends:
        idx: dict = {}
        for (kx, ky), e in ends.items():
            idx.setdefault(ky, []).append((kx, e))
        _ENDS_BY_Y[0], _ENDS_BY_Y[1] = ends, idx
    return _ENDS_BY_Y[1]


def _abuts(ends, gx0: float, c) -> bool:
    """Кусок `c` начат в конце оператора, который начат не левее `gx0`
    (допуск — пробел, `ABUT_TOL` кегля: ячейки таблицы без линий стоят
    дальше)."""
    if not ends or c[1] is None or ABUT_TOL <= 0:
        return False
    yy = int(round(c[2]))
    tol = max(0.8, ABUT_TOL * max(c[3] or 1.0, 1.0))
    idx = _ends_by_y(ends)
    for dy in (-1, 0, 1):
        for kx, e in idx.get(yy + dy, ()):
            if abs(e - c[1]) <= tol and gx0 - 1.0 <= kx < c[1]:
                return True
    return False


ABUT_TOL = float(os.environ.get("PDF_ABUT_TOL", "0.3"))  # 0 — выключить (Ц3)


def _h_groups(body: list, chunks: list, cw: float, cols=(), ends=None, vrules=()) -> list:
    """Куски строки (номера по порядку потока), разбитые на РАЗНЫЕ надписи
    одной базовой линии: следующий кусок отделён от уже собранной части
    зазором больше `SPLIT_GAP` кеглей — справа от её конца или слева от её
    начала (поток вернулся назад через пол-листа), — либо стоит в начале
    колонки таблицы (`_col_starts`) после зазора больше `COL_GAP`. Куски
    другой базовой линии (надстрочник, вторая строка сноски) — дело
    `_line_parts`, здесь они остаются в своей части.

    Часть без единой буквы (маркер «•») отдельной не становится — но
    приклеивается к СЛЕДУЮЩЕЙ части, если стоит у неё вплотную, а не
    к предыдущей: маркер списка в ячейке таблицы начинает свою ячейку."""
    groups = [[body[0]]]
    c0 = chunks[body[0]]
    size = max(c0[3] or 1.0, 1.0)
    y = c0[2]
    gx0 = c0[1]
    gx1 = c0[1] + len(c0[0].strip()) * cw * size
    gx1c = _chunk_end(c0, cw, ends)
    weak = [not any(ch.isalpha() for ch in c0[0])]
    for k in body[1:]:
        c = chunks[k]
        sz = max(c[3] or size, 1.0)
        cx1 = c[1] + len(c[0].strip()) * cw * sz
        gap = SPLIT_GAP * max(size, sz)
        same = abs(c[2] - y) <= 0.5 * size
        far = c[1] > gx1c + gap or cx1 + gap < gx0
        abut = same and c[1] > gx0 and _abuts(ends, gx0, c)
        if abut:
            # Ц3: кусок начат РОВНО там, где кончился оператор, начатый в этой
            # части (курсивное «GATA3» после «…гена»), — продолжение надписи,
            # а не другая надпись: оценка конца по ширине знака тут врёт.
            far = False
        if _rule_between(vrules, chunks[groups[-1][-1]][1], c[1], (c[2] + y) / 2.0, max(size, sz)):
            # Т34: между началом прошлого куска и началом этого стоит линия
            # таблицы, проходящая через строку, — это другая ячейка, каким
            # бы маленьким ни был зазор и на какой бы базовой линии ни стоял
            # кусок (ячейки шапки выключены по центру, двухстрочные — выше
            # и ниже соседних). Часть за линией — полноценная ячейка, даже
            # без букв («0,001»): склеивать её обратно (Т10) нельзя.
            groups.append([k])
            weak.append(False)
            size, y = sz, c[2]
            gx0, gx1, gx1c = c[1], cx1, _chunk_end(c, cw, ends)
            continue
        # Колонка таблицы — по ТОЧНОМУ концу краски, где он известен.
        col = (c[1] > gx1c + COL_GAP * max(size, sz)
               and any(abs(c[1] - x) <= COL_TOL for x in cols)
               and _in_ruled(vrules, c[2], sz, c[1])) and not abut
        has_alpha = any(ch.isalpha() for ch in c[0])
        if (not same and has_alpha and len(c[0].strip()) > 3 and sz >= 0.85 * size
                and (c[1] > gx1c + V_SPLIT_GAP * sz or cx1 + V_SPLIT_GAP * sz < gx0)
                and any(ch.isalpha() for kk in groups[-1] for ch in chunks[kk][0])):
            # Другая базовая линия И по горизонтали не пересекается с уже
            # собранной частью: это ДРУГАЯ надпись, которую pypdf склеил
            # в одну строку («PROGRAMS THAT ADDRESS:» в рамке справа
            # и «24-H PHYSICAL» у левого края ниже, стр. 4). Надстрочник
            # (короткий мелкий кусок) и вторая строка сноски (она под первой,
            # то есть пересекается с ней) остаются делом `_line_parts`.
            groups.append([k])
            weak.append(False)
            size, y = sz, c[2]
            gx0, gx1, gx1c = c[1], cx1, _chunk_end(c, cw, ends)
            continue
        if same and (far or col):
            if not has_alpha:
                groups.append([k])
                weak.append(True)
                gx0, gx1, gx1c = c[1], cx1, _chunk_end(c, cw, ends)
                continue
            if any(ch.isalpha() for kk in groups[-1] for ch in chunks[kk][0]):
                groups.append([k])
                weak.append(False)
                gx0, gx1, gx1c = c[1], cx1, _chunk_end(c, cw, ends)
                continue
            if weak[-1] and len(groups) > 1:
                # Маркер без букв стоял далеко от СЛЕДУЮЩЕГО куска —
                # он принадлежит предыдущей части.
                groups[-2].extend(groups.pop())
                weak.pop()
                groups.append([k])
                weak.append(False)
                gx0, gx1, gx1c = c[1], cx1, _chunk_end(c, cw, ends)
                continue
        groups[-1].append(k)
        if has_alpha:
            weak[-1] = False
        gx0, gx1 = min(gx0, c[1]), max(gx1, cx1)
        gx1c = max(gx1c, _chunk_end(c, cw, ends))
    if len(groups) > 1 and weak[-1]:
        # Т10. Маркер без букв и цифр («•») в КОНЦЕ строки, далеко от конца
        # предыдущей части, — начало СВОЕЙ ячейки (текст которой растр или
        # в другом месте слоя), а не хвост левой ячейки. Прежде он
        # приклеивался к ней: слот левой ячейки «• Low-energy diet (LED) •»
        # тянулся через зазор на правую колонку таблицы, перевод левой
        # ячейки уезжал туда, а маркер правой стирался закраской (стр. 10
        # проекта 14, три строки на 46 страниц). Цифры («12» у оглавления)
        # и близкий знак — по-прежнему хвост строки.
        lastc = chunks[groups[-1][0]]
        txt = "".join(chunks[kk][0] for kk in groups[-1])
        # Конец предыдущей части — ТОЧНЫЙ (по оператору показа), а не оценка:
        # оценка по ширине знака у узкого шрифта занижена, и тире после
        # заголовка («Апитоксинотерапия —», кегль 11 и 4) выглядело бы
        # далёким. Точного конца нет — по-прежнему хвост строки.
        exact_ends = [_chunk_end_exact(chunks[kk], ends) for kk in groups[-2]]
        sz_ = max(lastc[3] or 1.0, 1.0)
        glue = (any(ch.isalnum() for ch in txt) or lastc[1] is None or None in exact_ends)
        if not glue:
            gap_ = lastc[1] - max(exact_ends)
            # Далеко (`SPLIT_GAP`) либо стоит в начале колонки таблицы
            # (`cols`) после зазора больше `COL_GAP` — так маркер правой
            # ячейки стоит и тогда, когда левый текст почти дотянул до неё
            # («Very-low-energy diet (VLED)» — 9 пт зазора при трёх кеглях).
            glue = not (gap_ >= SPLIT_GAP * sz_
                        or (gap_ > COL_GAP * sz_ and any(abs(lastc[1] - x) <= COL_TOL for x in cols)))
        if glue:
            groups[-2].extend(groups.pop())
            weak.pop()
    if len(groups) > 1 and weak[0]:
        groups[1][:0] = groups.pop(0)
    return groups


def _line_geo(ks: list, body: list, chunks: list, starts: list, a: int, cw: float,
              ends: "dict | None" = None) -> list:
    """Геометрия одной строки по её кускам (см. `page_lines`)."""
    first = chunks[body[0]]
    x0, y, size = first[1], first[2], first[3]
    # Начертание строки — то, каким набрана бОльшая часть её знаков.
    styles = Counter()
    for k in body:
        styles[chunks[k][5] if len(chunks[k]) > 5 else ""] += len(chunks[k][0].strip())
    style = styles.most_common(1)[0][0] if styles else ""
    # Семейство — так же, большинством знаков; «не знаем» не голосует.
    fams = Counter()
    for k in body:
        fam = chunks[k][6] if len(chunks[k]) > 6 else ""
        if fam:
            fams[fam] += len(chunks[k][0].strip())
    family = fams.most_common(1)[0][0] if fams else ""
    x1 = x0
    xl = x0                         # начало ПОСЛЕДНЕГО куска с текстом — точное
    keys = set()                    # шрифты кусков строки
    for k in ks:
        c = chunks[k]
        if c[1] is None or starts[k] < a or abs(c[2] - y) > 0.5 * max(size, 1.0):
            continue
        if c[0].strip():
            piece = c[0].strip("\n")
            x1 = max(x1, c[1] + len(piece.rstrip()) * cw * (c[3] or size))
            xl = max(xl, c[1])
            if len(c) > 9 and c[9] is not None:
                keys.add(c[9])
        elif c[1] > x0:
            x1 = max(x1, c[1])       # пробел после текста — точный конец строки
    # x1 — оценка по средней ширине знака и у крупного кегля уезжает
    # в соседнюю колонку; xl — где начался последний кусок, это PDF
    # знает точно. От него выгрузка ищет настоящий конец по краске.
    parts = _line_parts(body, chunks, size, cw)
    return [round(x0, 1), round(y, 1), round(size, 2), round(x1, 1), style, family,
            round(xl, 1), parts, False, keys,
            _chunk_color(body, chunks),
            None if parts else _line_gaps(body, chunks, size, cw, ends)]


# Разрыв ВНУТРИ строки слоя (кегли): между двумя кусками одной базовой линии
# пусто по слою, а в картинке там может стоять текст, которого слоя нет
# («• [Beneficial effect on HbA] 1c, body weight…», проект 14, стр. 10).
# По точному концу куска (оператор показа) — от `LINE_GAP_EXACT`, по оценке
# средней шириной знака — от `LINE_GAP_EST`: оценка ошибается, и выключка по
# ширине и табуляция дают законные широкие пробелы.
LINE_GAP_EXACT = 2.5
LINE_GAP_EST = 4.0


def _line_gaps(body: list, chunks: list, size: float, cw: float, ends) -> "list | None":
    """[[конец куска, начало следующего], …] — разрывы строки, либо None."""
    pcs = []
    for k in body:
        c = chunks[k]
        if c[1] is None or not c[0].strip() or abs(c[2] - chunks[body[0]][2]) > 0.5 * max(size, 1.0):
            continue
        exact = False
        if ends:
            x_, y_ = int(round(c[1])), int(round(c[2]))
            exact = any(ends.get((x_ + dx, y_ + dy)) is not None for dx in (0, -1, 1) for dy in (0, -1, 1))
        pcs.append((c[1], _chunk_end(c, cw, ends), exact))
    pcs.sort()
    out = []
    for (ax, ae, aex), (bx, _be, _bex) in zip(pcs, pcs[1:]):
        need = (LINE_GAP_EXACT if aex else LINE_GAP_EST) * max(size, 1.0)
        if bx - ae >= need:
            out.append([round(ae, 1), round(bx, 1)])
    return out or None


def _chunk_color(body: list, chunks: list):
    """Цвет краски строки — тот, которым набрано больше её знаков, либо None
    (у части знаков цвет неизвестен — тогда его меряет выгрузка)."""
    cols = Counter()
    for k in body:
        c = chunks[k]
        n = len(c[0].strip())
        if not n:
            continue
        col = c[12] if len(c) > 12 else None
        if col is None:
            return None
        cols[tuple(round(v, 3) for v in col)] += n
    return list(cols.most_common(1)[0][0]) if cols else None


def main() -> int:
    start, end = int(sys.argv[1]), int(sys.argv[2])
    data = sys.stdin.buffer.read()
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore
    reader = PdfReader(io.BytesIO(data))
    out = sys.stdout
    for i in range(start, min(end, len(reader.pages))):
        lines, geom = page_lines(reader.pages[i])
        out.write(json.dumps([i, lines, geom]) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                      # pragma: no cover
        sys.stderr.write("%s: %s\n" % (type(e).__name__, e))
        sys.exit(1)
