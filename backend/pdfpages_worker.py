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
    # Обрезка (clip) — прямоугольник, вне которого на странице не видно
    # НИЧЕГО. Текст за ней есть в текстовом слое, но не на листе: у боевого
    # PDF схема лежала дважды — вторая копия, сдвинутая на 23 пт и с иными
    # цифрами («500–1000»), была отрезана обтравкой, а выгрузка печатала
    # её перевод поверх видимой. Следим за прямоугольной обрезкой со
    # стеком q/Q; обрезка кривой — «не знаем», и она ничего не прячет.
    state = {"clip": False, "box": None, "curve": False, "seq": 0, "alpha": 1.0,
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
        return (x0, y0, x1, font_key(fd), y1, abs(y1 - y0) < 0.5, ox)

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
                stack.append(state["box"])
                astack.append(state["alpha"])
                tstack.append((state["tc"], state["tw"], state["tz"],
                               state.get("fd"), state.get("fs")))
                return
            if op == b"Q":
                if cstack:
                    state["fill"], state["cs"], state["tr"] = cstack.pop()
                state["box"] = stack.pop() if stack else None
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
                    op_recs.append(op_rec(op, args, cm, _tm, got))
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
                return
            if op == b"re" and len(args) >= 4:
                x, y, w, h = (_num(a) for a in args[:4])
                if None in (x, y, w, h):
                    return
                pts = [_xy(cm, x, y), _xy(cm, x + w, y + h)]
                pending.append([min(p[0] for p in pts), min(p[1] for p in pts),
                                max(p[0] for p in pts), max(p[1] for p in pts)])
            elif op in _CLIP_OPS:
                state["clip"] = True
            elif op in _PAINT_OPS or op == b"n":
                if op != b"n" and not state["clip"]:
                    rects.extend(pending)
                    if (op not in (b"S", b"s") and state["alpha"] >= 0.99   # обводка не закрывает
                            and not forms):     # у формы своя система координат — не знаем
                        state["seq"] += 1
                        covers.extend((state["seq"], r) for r in pending)
                if state["clip"] and pending and not state["curve"] and not forms:
                    clip = [min(r[0] for r in pending), min(r[1] for r in pending),
                            max(r[2] for r in pending), max(r[3] for r in pending)]
                    box = state["box"]
                    if box is not None:
                        clip = [max(clip[0], box[0]), max(clip[1], box[1]),
                                min(clip[2], box[2]), min(clip[3], box[3])]
                    state["box"] = clip
                pending.clear()
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
                                  (state["fill"], state["cs"], state["tr"]), len(cstack)))
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
             state["fd"], state["fs"], n1, n2, n3, col_, n4) = forms.pop()
            state["fill"], state["cs"], state["tr"] = col_
            del cstack[n4:]
            del stack[n1:]
            del astack[n2:]
            del tstack[n3:]
            if res_stack:
                res_stack.pop()
            state["clip"], state["curve"] = False, False
            pending.clear()
        except Exception:
            pass

    try:
        out = page.extract_text(visitor_text=vt, visitor_operand_before=vo,
                                visitor_operand_after=va) or ""
    except TypeError:
        # Старый pypdf или подмена без посетителей — строки без геометрии.
        return (page.extract_text() or "").splitlines(), None
    lines = out.splitlines()
    try:
        marked = _mark_covered(chunks, covers)
        geom = _geometry(lines, out, marked, figs, rects, page, op_ends, op_recs)
        if geom is None and dups:
            # Текст формы пришёл дважды: изнутри (точки на своих местах)
            # и повтором в точке формы. Без повтора куски сложатся в ответ.
            geom = _geometry(lines, out, [c for k, c in enumerate(marked) if k not in dups],
                             figs, rects, page, op_ends, op_recs)
    except Exception:
        geom = None
    return lines, geom


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
    for k in range(0, len(cv), 256):            # блоками: память — не квадрат
        part = cv[k:k + 256]
        seq = np.array([c[0] for c in part], dtype=np.int64)[None, :]
        box = np.array([c[1] for c in part], dtype=np.float64)
        m = ((seq > ss[:, None])
             & (box[None, :, 0] + 1 <= xs[:, None]) & (xs[:, None] <= box[None, :, 2] - 1)
             & (box[None, :, 1] + 1 <= ys[:, None]) & (ys[:, None] <= box[None, :, 3] - 1))
        hit |= m.any(axis=1)
    if not hit.any():
        return chunks
    out = list(chunks)
    for j, i in enumerate(idx):
        if hit[j]:
            c = out[i]
            out[i] = c[:7] + (True,) + c[8:]
    return out


def _exact_ends(geo_lines: list, op_ends) -> None:
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
    for k, g in rows:
        keys = g[9] if len(g) > 9 else set()
        g[:] = g[:9] + [g[10] if len(g) > 10 else None]      # 9 — цвет краски
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
        if best is not None and best >= xl and (lim is None or best <= lim):
            g[3] = round(best, 1)
            g[8] = True


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


def _geometry(lines, out, chunks, figs, rects, page, op_ends=(), op_recs=()):
    text = "".join(c[0] for c in chunks)
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
            if body and all(chunks[k][4] for k in body):
                rot_paths[len(geo_lines) - 1] = _rot_path(body, chunks, cw, op_ends, op_recs)
            continue
        groups = _h_groups(body, chunks, cw, cols, ends)
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
                subs.append([lo - a, _line_geo(sub_ks, grp, chunks, starts, lo, cw)])
            geo_lines.append(subs[0][1])
            splits[len(geo_lines) - 1] = subs
            continue
        geo_lines.append(_line_geo(ks, body, chunks, starts, a, cw))
    # Одна строка ответа — одна строка геометрии; иначе смысла в ней нет.
    if len(geo_lines) != len(lines):
        return None
    _exact_ends(geo_lines + [sg[1] for subs in splits.values() for sg in subs[1:]], op_ends)
    try:
        mb = page.mediabox
        box = [float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)]
    except Exception:
        box = None
    r1 = lambda v: [round(float(t), 1) for t in v]   # noqa: E731
    out_ = {"box": r1(box) if box else None, "lines": geo_lines,
            "figs": [r1(f) for f in figs], "rects": [r1(r) for r in rects],
            "rot": {str(k): v for k, v in rot_paths.items() if v}}
    if splits:
        out_["split"] = {str(k): [[off, g_] for off, g_ in subs] for k, subs in splits.items()}
    return out_


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


def _chunk_end(c, cw: float, ends: dict) -> float:
    """Конец краски куска: по оператору, начатому в его точке, иначе оценка."""
    est = c[1] + len(c[0].strip()) * cw * max(c[3] or 1.0, 1.0)
    if ends:
        x, y = int(round(c[1])), int(round(c[2]))
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                e = ends.get((x + dx, y + dy))
                if e is not None and e > c[1]:
                    return min(est, e) if est > c[1] else e
    return est


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


def _h_groups(body: list, chunks: list, cw: float, cols=(), ends=None) -> list:
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
        # Колонка таблицы — по ТОЧНОМУ концу краски, где он известен.
        col = (c[1] > gx1c + COL_GAP * max(size, sz)
               and any(abs(c[1] - x) <= COL_TOL for x in cols))
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
        groups[-2].extend(groups.pop())
        weak.pop()
    if len(groups) > 1 and weak[0]:
        groups[1][:0] = groups.pop(0)
    return groups


def _line_geo(ks: list, body: list, chunks: list, starts: list, a: int, cw: float) -> list:
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
    return [round(x0, 1), round(y, 1), round(size, 2), round(x1, 1), style, family,
            round(xl, 1), _line_parts(body, chunks, size, cw), False, keys,
            _chunk_color(body, chunks)]


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
