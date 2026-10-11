# -*- coding: utf-8 -*-
"""«Лента» → обычные страницы: виртуальные страницы PDF.

ЗАЧЕМ. Сканер-приложения (CamScanner и соседи) склеивают документ в два-три
«листа» высотой по 14 400 пт — максимум формата. Внутри листа подряд стоят
настоящие страницы, каждая своей группой содержимого `q X Y W H re W n … Q`
одного размера (у боевого файла — 46 страниц журнала по 417.5×550.4 пт
на двух листах, одна страница разрезана между листами: 347 + 203 пт).

Вся постраничная логика разбора считает страницей ЛИСТ: колонтитулы, колонки,
поля, роли, рисунки, снимок бумаги под закраской (потолок площади сжимал его
до ~50 точек на дюйм), картинка страницы под чтение надписей (880×28 800
пикселей — детектор строк такую не видит). А страница журнала, положенная
БОКОМ (таблица, широкий рисунок), разбиралась повёрнутыми строками: строка
таблицы шла одной «строкой» на всю ширину, и перевод печатался одной линией
через весь лист.

ЧТО ДЕЛАЕМ. Находим страницы внутри листов (`detect`) и собираем из них
обычный PDF (`compose`): каждая страница — форма (Form XObject) с той частью
содержимого листа, что лежит на этой странице, страница журнала, положенная
боком, ставится прямо. Дальше ВЕСЬ разбор и вся выгрузка идут по этому PDF,
как по обычному, — правил под ленту в них нет. Обратно в листы выгрузка
собирает `unsplit`, если человек выбрал «как в файле».

ЗАКОНЫ.
1. Обычный PDF не трогается НИКОГДА: нет панелей хотя бы на одном листе —
   `detect` отвечает None, и всё идёт по оригиналу байт в байт.
2. Ничего не теряется: краска листа вне найденных страниц — отказ (None),
   а не обрезка (`_ink_outside`).
3. Самопроверка рисунком: каждая собранная страница сравнивается с вырезкой
   листа; не сошлась — её кусок берёт содержимое листа ЦЕЛИКОМ (верно всегда,
   просто тяжелее). Фильтр содержимого — экономия, а не условие верности.
4. Детерминизм: тот же файл → те же страницы и те же координаты (на номера
   страниц и рамки ссылается раскладка проекта, а виртуальный PDF собирается
   заново на каждой выгрузке).
"""

import io
import re
import threading
from collections import Counter, OrderedDict

try:
    from backend.pdfium_gate import LOCK as PDFIUM_LOCK
except ImportError:                                  # pragma: no cover
    from pdfium_gate import LOCK as PDFIUM_LOCK

# Версия правил сборки: входит в раскладку (`virt.v`). Меняешь правила так,
# что меняются страницы или координаты, — поднимай: раскладка старой версии
# с новым PDF не совпала бы.
VERSION = 1

# Кандидат в страницу — клип группы шириной не меньше этой доли листа.
PANEL_MIN_W = 0.8
# Одна высота у полных страниц: допуск в долях высоты.
PANEL_H_TOL = 0.01
# Две неполные страницы у краёв соседних листов — одна страница журнала,
# если сумма их высот совпадает с полной в этом допуске.
STRADDLE_TOL = 0.02
# Пропорции страницы (высота к ширине): от квадрата до узкой книжной.
PANEL_RATIO = (1.0, 1.8)
# Страницы закрывают не меньше этой доли высоты листов.
PANEL_COVER = 0.9
# Страница журнала положена боком: доля знаков под ±90°.
ROT_SHARE = 0.6
# Самопроверка: масштаб отрисовки, порог разницы и доля несовпавших точек.
CHECK_SCALE = 1.0
CHECK_DIFF = 48
CHECK_SHARE = 0.01
CHECK_BLOCK = 8
# Краска вне страниц: доля «не белых» точек листа, после которой отказ.
OUTSIDE_INK_SHARE = 0.001

_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 2


# --- разбор содержимого на группы верхнего уровня ------------------------

_TOK = re.compile(
    rb"\((?:[^()\\]|\\.)*\)"            # строка без вложенных скобок
    rb"|\("                              # строка с вложенными — вручную
    rb"|<<|>>"
    rb"|<[0-9A-Fa-f\s]*>"                # шестнадцатеричная строка
    rb"|%[^\r\n]*"                       # комментарий
    rb"|(?<![^\s\]\)>}])BI(?=\s)"        # встроенная картинка
    rb"|(?<![^\s\]\)>}])[qQ](?![^\s\[\(</%])")
_CLIP = re.compile(
    rb"\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+re\s+W\*?\s+n(?![A-Za-z])")
_EI = re.compile(rb"\sEI(?=\s|$)")
_ID = re.compile(rb"\sID\s")


def _string_end(c: bytes, i: int) -> int:
    """Конец строки PDF «(…)» со вложенными скобками, начиная с «(» в i."""
    depth, n = 0, len(c)
    while i < n:
        ch = c[i]
        if ch == 0x5C:                  # обратная косая — экранирует знак
            i += 2
            continue
        if ch == 0x28:
            depth += 1
        elif ch == 0x29:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def groups(c: bytes) -> "list | None":
    """Содержимое страницы → [(начало, конец, клип | None | "loose")].

    Группа верхнего уровня `q … Q` получает клип, если начинается с
    `x y w h re W n` (прямоугольник в координатах листа), иначе None —
    «не знаем, где рисует». Содержимое МЕЖДУ группами верхнего уровня —
    кусками "loose" (его берут все страницы). None — разобрать не вышло
    (несбалансированные q/Q): содержимое берётся целиком."""
    out = []
    depth = 0
    start = None
    last = 0
    pos = 0
    n = len(c)
    while True:
        m = _TOK.search(c, pos)
        if m is None:
            break
        tok = m.group(0)
        if tok == b"(":
            pos = _string_end(c, m.start())
            continue
        if tok == b"BI":
            mi = _ID.search(c, m.end())
            if mi is None:
                return None
            me = _EI.search(c, mi.end())
            if me is None:
                return None
            pos = me.end()
            continue
        pos = m.end()
        if tok == b"q":
            if depth == 0:
                if c[last:m.start()].strip():
                    out.append((last, m.start(), "loose"))
                start = m.start()
            depth += 1
        elif tok == b"Q":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                clip = None
                mc = _CLIP.match(c, start + 1)
                if mc:
                    try:
                        x, y, w, h = (float(v) for v in mc.groups())
                        if w < 0:
                            x, w = x + w, -w
                        if h < 0:
                            y, h = y + h, -h
                        clip = (x, y, x + w, y + h)
                    except ValueError:
                        clip = None
                else:
                    clip = _path_clip(c, start + 1, m.end())
                out.append((start, m.end(), clip))
                last = m.end()
    if depth != 0:
        return None
    if c[last:].strip():
        out.append((last, n, "loose"))
    return out


_CM_RE = re.compile(rb"(?<![A-Za-z])cm(?![A-Za-z])")
_PATH_CLIP_END = re.compile(rb"W\*?\s+n(?![A-Za-z])")
_PATH_ONLY = re.compile(rb"[-+\d.\s mlcvyh]*")
_NUMS = re.compile(rb"[-+]?(?:\d+\.?\d*|\.\d+)")


def _path_clip(c: bytes, a: int, b: int):
    """Клип КОНТУРОМ в начале группы (`x y m … l … h W n`) — его рамка либо
    None. Рамка по всем точкам контура, включая управляющие точки кривых: она
    шире настоящей, и это безопасная сторона (кусок возьмёт лишнее, а не
    потеряет нужное). Любой другой оператор до `W n` — «не знаем»."""
    m = _PATH_CLIP_END.search(c, a, b)
    if m is None:
        return None
    body = c[a:m.start()]
    if not body.strip() or _PATH_ONLY.fullmatch(body) is None:
        return None
    nums = _NUMS.findall(body)
    if len(nums) < 4 or len(nums) % 2:
        return None
    try:
        xs = [float(v) for v in nums[0::2]]
        ys = [float(v) for v in nums[1::2]]
    except ValueError:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _filtered(c: bytes, grs: "list | None", rect: tuple) -> bytes:
    """Содержимое листа, которое может рисовать в прямоугольнике `rect`."""
    if grs is None:
        return c
    x0, y0, x1, y1 = rect
    parts = []
    for a, b, clip in grs:
        if isinstance(clip, tuple):
            cx0, cy0, cx1, cy1 = clip
            if cx1 - cx0 <= 0 or cy1 - cy0 <= 0:
                continue                # клип нулевой площади: не рисует ничего
            if cx1 <= x0 or cx0 >= x1 or cy1 <= y0 or cy0 >= y1:
                continue
        parts.append(c[a:b])
    return b"\n".join(parts)


# --- поиск страниц внутри листов ------------------------------------------

def _rects_of(grs: list) -> list:
    return [g[2] for g in grs if isinstance(g[2], tuple)]


def detect(reader, contents: "list | None" = None) -> "dict | None":
    """План виртуальных страниц или None (обычный PDF).

    {"v", "src": [[w, h] листов], "pages": [{"w", "h", "pieces": [{"src",
    "rect": [x0, y0, x1, y1], "dy"}], "rot": 0}]} — `dy` — где кусок стоит
    по высоте страницы (снизу), `rot` проставляет `compose`."""
    sizes, rects_by = [], []
    for i, page in enumerate(reader.pages):
        try:
            mb = page.mediabox
            box = (float(mb.left), float(mb.bottom), float(mb.right), float(mb.top))
        except Exception:
            return None
        sizes.append(box)
        try:
            if int(page.get("/Rotate") or 0) % 360:
                return None             # повёрнутый лист — не наш случай
        except Exception:
            pass
        c = contents[i] if contents is not None else _content(page)
        grs = groups(c) if c else None
        rects_by.append(_rects_of(grs) if grs else [])
    # Кандидаты: клипы почти во всю ширину листа.
    cand = []
    for i, rs in enumerate(rects_by):
        bx0, by0, bx1, by1 = sizes[i]
        pw = bx1 - bx0
        for r in rs:
            if r[2] - r[0] >= PANEL_MIN_W * pw and r[3] - r[1] > 1.0:
                cand.append((i, r))
    if not cand:
        return None
    key = Counter((round(r[0]), round(r[2] - r[0])) for _i, r in cand)
    kx, kw = key.most_common(1)[0][0]
    cand = [(i, r) for i, r in cand if round(r[0]) == kx and round(r[2] - r[0]) == kw]
    hs = Counter(round(r[3] - r[1], 1) for _i, r in cand)
    H = hs.most_common(1)[0][0]
    if H <= 0:
        return None
    full: dict = {}
    part: dict = {}
    for i, r in cand:
        h = r[3] - r[1]
        bx0, by0, bx1, by1 = sizes[i]
        r = (max(r[0], bx0), max(r[1], by0), min(r[2], bx1), min(r[3], by1))
        h = r[3] - r[1]
        if abs(h - H) <= PANEL_H_TOL * H:
            full.setdefault(i, {})[round(r[1])] = r
        elif h < H and (r[1] <= by0 + 1.0 or r[3] >= by1 - 1.0):
            part.setdefault(i, {})[round(r[1])] = r
    if not any(len(v) >= 2 for v in full.values()):
        return None
    # Это СТРАНИЦЫ, а не блоки вёрстки (шапка, тело, подвал во всю ширину):
    # пропорции листа бумаги, лист — не ниже двух таких страниц, и страницы
    # закрывают почти всю высоту листов.
    if not (PANEL_RATIO[0] <= H / max(float(kw), 1.0) <= PANEL_RATIO[1]):
        return None
    if not any((b[3] - b[1]) >= 2 * H - 1.0 for b in sizes):
        return None
    covered = sum(r[3] - r[1] for d in (full, part) for v in d.values() for r in v.values())
    if covered < PANEL_COVER * sum(b[3] - b[1] for b in sizes):
        return None
    pages = []
    carry = None                        # неполная страница внизу прошлого листа
    for i in range(len(sizes)):
        bx0, by0, bx1, by1 = sizes[i]
        rs = sorted(list((full.get(i) or {}).values()) + list((part.get(i) or {}).values()),
                    key=lambda r: -r[3])
        # Страницы не пересекаются: иначе это не страницы, а что-то другое.
        for a, b in zip(rs, rs[1:]):
            if b[3] > a[1] + 1.0:
                return None
        for k, r in enumerate(rs):
            h = r[3] - r[1]
            is_full = abs(h - H) <= PANEL_H_TOL * H
            if (not is_full and k == 0 and r[3] >= by1 - 1.0 and carry is not None
                    and abs(carry[1][3] - carry[1][1] + h - H) <= STRADDLE_TOL * H):
                ci, cr = carry
                ch = cr[3] - cr[1]
                tot = ch + h
                pages.append({"w": r[2] - r[0], "h": tot, "rot": 0, "pieces": [
                    {"src": ci, "rect": list(cr), "dy": tot - ch},
                    {"src": i, "rect": list(r), "dy": 0.0}]})
                carry = None
                continue
            if carry is not None:
                ci, cr = carry
                pages.append({"w": cr[2] - cr[0], "h": cr[3] - cr[1], "rot": 0,
                              "pieces": [{"src": ci, "rect": list(cr), "dy": 0.0}]})
                carry = None
            if not is_full and k == len(rs) - 1 and r[1] <= by0 + 1.0 and i + 1 < len(sizes):
                carry = (i, r)
                continue
            pages.append({"w": r[2] - r[0], "h": h, "rot": 0,
                          "pieces": [{"src": i, "rect": list(r), "dy": 0.0}]})
    if carry is not None:
        ci, cr = carry
        pages.append({"w": cr[2] - cr[0], "h": cr[3] - cr[1], "rot": 0,
                      "pieces": [{"src": ci, "rect": list(cr), "dy": 0.0}]})
    if len(pages) <= len(sizes):
        return None
    for pg in pages:
        pg["w"], pg["h"] = round(pg["w"], 3), round(pg["h"], 3)
        for pc in pg["pieces"]:
            pc["rect"] = [round(v, 3) for v in pc["rect"]]
            pc["dy"] = round(pc["dy"], 3)
    return {"v": VERSION, "src": [[round(b[2] - b[0], 3), round(b[3] - b[1], 3)] for b in sizes],
            "srcBox": [[round(v, 3) for v in b] for b in sizes], "pages": pages}


def _content(page) -> bytes:
    try:
        cs = page.get_contents()
        return cs.get_data() if cs is not None else b""
    except Exception:
        return b""


# --- матрицы ---------------------------------------------------------------

def piece_matrix(pg: dict, pc: dict) -> tuple:
    """Матрица «координаты листа → координаты страницы» для куска: сдвиг
    куска на его место, затем поворот страницы (`rot`), если она лежала боком."""
    x0, y0 = pc["rect"][0], pc["rect"][1]
    t = (1.0, 0.0, 0.0, 1.0, -x0, -y0 + pc["dy"])
    return _mul(t, rot_matrix(pg))


def rot_matrix(pg: dict) -> tuple:
    """Поворот страницы «без поворота» (w×h) в прямую. rot=90 — текст шёл
    снизу вверх (поворачиваем по часовой), 270 — сверху вниз."""
    w, h = pg["w"], pg["h"]
    if pg.get("rot") == 90:
        return (0.0, -1.0, 1.0, 0.0, 0.0, w)
    if pg.get("rot") == 270:
        return (0.0, 1.0, -1.0, 0.0, h, 0.0)
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def page_size(pg: dict) -> tuple:
    return (pg["h"], pg["w"]) if pg.get("rot") in (90, 270) else (pg["w"], pg["h"])


def _mul(m1: tuple, m2: tuple) -> tuple:
    """m1, затем m2 (порядок PDF: [x y 1]·m1·m2)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def inverse(m: tuple) -> tuple:
    a, b, c, d, e, f = m
    det = a * d - b * c
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


def apply(m: tuple, x: float, y: float) -> tuple:
    a, b, c, d, e, f = m
    return (x * a + y * c + e, x * b + y * d + f)


def _num(v: float) -> bytes:
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return (s if s not in ("", "-0") else "0").encode()


def _cm(m: tuple) -> bytes:
    return b" ".join(_num(v) for v in m) + b" cm"


# --- сборка ----------------------------------------------------------------

_RES_KEYS = ("/Font", "/XObject", "/ExtGState", "/ColorSpace", "/Pattern", "/Shading",
             "/Properties")


def _merge_res(dicts: list):
    """Ресурсы нескольких листов одним словарём — или None при конфликте
    имён (одно имя, разные объекты): тогда второй кусок идёт формой."""
    from pypdf.generic import DictionaryObject, NameObject
    out = DictionaryObject()
    for d in dicts:
        for k, v in d.items():
            vv = v.get_object() if hasattr(v, "get_object") else v
            if k in _RES_KEYS and isinstance(vv, dict):
                cur = out.get(NameObject(k))
                if cur is None:
                    cur = DictionaryObject()
                    out[NameObject(k)] = cur
                for nk, nv in vv.items():
                    if nk in cur:
                        a, b = cur[nk], nv
                        if a is b:
                            continue
                        ida = getattr(a, "idnum", None)
                        idb = getattr(b, "idnum", None)
                        if ida is None or ida != idb:
                            return None
                    else:
                        cur[NameObject(nk)] = nv
            elif k not in out:
                out[NameObject(k)] = v
    return out


def _compose(pdf_bytes: bytes, plan: dict, whole: frozenset = frozenset()) -> bytes:
    """Виртуальный PDF по плану. `whole` — номера страниц, чьи куски берут
    содержимое листа целиком (не прошли самопроверку фильтра).

    Операторы листа пишутся ПРЯМО в содержимое страницы, а не формой: разбор
    текстового слоя (`pdfpages_worker`) внутри формы не видит ни обрезки, ни
    закраски поверх текста, ни ресурсов шрифта для точного конца строки.
    Клип куска стоит перед ними — в координатах листа после `cm`."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               FloatObject, NameObject)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    contents, grs, res_objs, res_refs = {}, {}, {}, {}

    def src_of(i):
        if i not in contents:
            page = reader.pages[i]
            contents[i] = _content(page)
            grs[i] = groups(contents[i])
            # `cm` между группами верхнего уровня сдвигает систему координат
            # всех следующих групп, и их клипы перестают быть координатами
            # листа: фильтр тогда не применяется вовсе.
            if grs[i] is not None and any(
                    g[2] == "loose" and _CM_RE.search(contents[i], g[0], g[1]) for g in grs[i]):
                grs[i] = None
            res = page.get("/Resources")
            res = res.get_object() if res is not None else DictionaryObject()
            res_objs[i] = res.clone(writer)
        return contents[i], grs[i], res_objs[i]

    for n, pg in enumerate(plan["pages"]):
        w, h = page_size(pg)
        page = writer.add_blank_page(width=w, height=h)
        pieces = [(pc,) + src_of(pc["src"]) for pc in pg["pieces"]]
        srcs = []
        for pc, _c, _g, res in pieces:
            if pc["src"] not in [s_[0] for s_ in srcs]:
                srcs.append((pc["src"], res))
        merged = srcs[0][1] if len(srcs) == 1 else _merge_res([r for _i, r in srcs])
        if merged is None:
            merged = DictionaryObject(srcs[0][1])
        xobj = None
        body = []
        for k, (pc, c, g, res) in enumerate(pieces):
            r = tuple(pc["rect"])
            data = _filtered(c, None if n in whole else g, r)
            clip = (b" ".join(_num(v) for v in (r[0], r[1], r[2] - r[0], r[3] - r[1]))
                    + b" re W n")
            if res is merged or len(srcs) == 1 or _merge_res([merged, res]) is not None:
                body.append(b"q " + _cm(piece_matrix(pg, pc)) + b" " + clip + b"\n" + data + b"\nQ")
                continue
            # Конфликт имён ресурсов: кусок другого листа — формой, а клип
            # СНАРУЖИ неё, на странице (внутри формы обрезку разбор не видит).
            form = DecodedStreamObject()
            form.set_data(data)
            form.update({NameObject("/Type"): NameObject("/XObject"),
                         NameObject("/Subtype"): NameObject("/Form"),
                         NameObject("/BBox"): ArrayObject([FloatObject(v) for v in r]),
                         NameObject("/Resources"): writer._add_object(res)})
            if xobj is None:
                xo = merged.get("/XObject")
                xobj = DictionaryObject(xo.get_object()) if xo is not None else DictionaryObject()
                merged = DictionaryObject(merged)
                merged[NameObject("/XObject")] = xobj
            name = "/MctPiece%d" % k
            xobj[NameObject(name)] = writer._add_object(form)
            body.append(b"q " + _cm(piece_matrix(pg, pc)) + b" " + clip + b" " + name.encode()
                        + b" Do Q")
        cs = DecodedStreamObject()
        cs.set_data(b"\n".join(body))
        if len(srcs) == 1 and xobj is None:
            if srcs[0][0] not in res_refs:
                res_refs[srcs[0][0]] = writer._add_object(merged)
            page[NameObject("/Resources")] = res_refs[srcs[0][0]]
        else:
            page[NameObject("/Resources")] = writer._add_object(merged)
        page[NameObject("/Contents")] = writer._add_object(_flate(cs))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _flate(stream):
    """Поток, сжатый КАК ЕСТЬ. `compress_content_streams` у pypdf разбирает
    содержимое на операторы и собирает заново — на листе в 57 МБ это минуты
    чистого Python и лишний риск переписать чужие операторы."""
    try:
        return stream.flate_encode()
    except Exception:
        return stream


def _render_gray(doc, i: int, scale: float, crop=None):
    with PDFIUM_LOCK:
        page = doc[i]
        try:
            kw = {"scale": scale}
            if crop is not None:
                kw["crop"] = crop
            return page.render(**kw).to_pil().convert("L")
        finally:
            page.close()


def _ink_outside(doc_src, plan: dict) -> bool:
    """Есть ли на листах краска ВНЕ найденных страниц (тогда план неверен)."""
    from PIL import ImageChops  # noqa: F401
    for i, box in enumerate(plan["srcBox"]):
        im = _render_gray(doc_src, i, 0.25)
        W, H = im.size
        sx, sy = W / max(box[2] - box[0], 1e-6), H / max(box[3] - box[1], 1e-6)
        px = im.load()
        mask = bytearray(W * H)
        for pg in plan["pages"]:
            for pc in pg["pieces"]:
                if pc["src"] != i:
                    continue
                x0, y0, x1, y1 = pc["rect"]
                c0, c1 = int((x0 - box[0]) * sx) - 1, int((x1 - box[0]) * sx) + 1
                r0, r1 = int((box[3] - y1) * sy) - 1, int((box[3] - y0) * sy) + 1
                for rr in range(max(0, r0), min(H, r1)):
                    base = rr * W
                    for cc in range(max(0, c0), min(W, c1)):
                        mask[base + cc] = 1
        bad = 0
        for rr in range(H):
            base = rr * W
            for cc in range(W):
                if not mask[base + cc] and px[cc, rr] < 200:
                    bad += 1
        if bad > OUTSIDE_INK_SHARE * W * H:
            return True
    return False


def _check(doc_src, doc_v, plan: dict) -> set:
    """Номера страниц, чей отфильтрованный кусок рисуется не так, как лист.

    Лист рисуется С ОБРЕЗКОЙ ровно по куску: начало снимка листа и начало
    страницы — одна и та же точка, и сетки точек совпадают (иначе дробный
    сдвиг расходился бы сглаживанием по краю каждой буквы). Сравнение —
    по клеткам `CHECK_BLOCK` (среднее): потерянный рисунок или строка меняют
    его заметно, а краевая разница обрезки — нет."""
    from PIL import Image, ImageChops
    bad = set()
    k = CHECK_BLOCK
    pages = {}
    try:
        for n, pg in enumerate(plan["pages"]):
            v = _render_gray(doc_v, n, CHECK_SCALE)
            for pc in pg["pieces"]:
                i = pc["src"]
                if i not in pages:
                    pages[i] = doc_src[i]
                box = plan["srcBox"][i]
                x0, y0, x1, y1 = pc["rect"]
                with PDFIUM_LOCK:
                    sh = pages[i].render(scale=CHECK_SCALE, crop=(
                        x0 - box[0], y0 - box[1], box[2] - x1, box[3] - y1)).to_pil().convert("L")
                vr = int(round((pg["h"] - pc["dy"] - (y1 - y0)) * CHECK_SCALE))
                w, h = min(sh.width, v.width) - 2, min(sh.height, v.height - vr) - 2
                if w < 2 * k or h < 2 * k:
                    continue
                b_ = v.crop((1, vr + 1, 1 + w, vr + 1 + h)).resize((w // k, h // k), Image.BOX)
                best = None
                # Сдвиг на точку в любую сторону: обрезка листа и страница
                # округляются до точки снимка по-разному.
                for dx in (0, -1, 1):
                    for dy in (0, -1, 1):
                        a_ = sh.crop((1 + dx, 1 + dy, 1 + dx + w, 1 + dy + h)).resize(
                            (w // k, h // k), Image.BOX)
                        d = sum(ImageChops.difference(a_, b_).histogram()[CHECK_DIFF:])
                        best = d if best is None else min(best, d)
                        if best == 0:
                            break
                    if best == 0:
                        break
                if best > CHECK_SHARE * (w // k) * (h // k):
                    bad.add(n)
    finally:
        for p_ in pages.values():
            p_.close()
    return bad


def _orient(doc_v, plan: dict) -> None:
    """Страница журнала, положенная боком: большинство знаков под ±90°."""
    import math
    import pypdfium2.raw as raw
    for n, pg in enumerate(plan["pages"]):
        page = doc_v[n]
        try:
            tp = page.get_textpage()
            try:
                cnt = raw.FPDFText_CountChars(tp.raw)
                votes = Counter()
                for k in range(cnt):
                    if raw.FPDFText_GetUnicode(tp.raw, k) in (32, 10, 13):
                        continue
                    a = raw.FPDFText_GetCharAngle(tp.raw, k)
                    if a < 0:
                        continue
                    deg = math.degrees(a) % 360
                    for target in (0, 90, 180, 270):
                        if abs(((deg - target) + 180) % 360 - 180) <= 15:
                            votes[target] += 1
                            break
            finally:
                tp.close()
        finally:
            page.close()
        tot = sum(votes.values())
        if tot < 20:
            continue
        for target in (90, 270):
            if votes[target] >= ROT_SHARE * tot:
                # pdfium меряет угол ПО ЧАСОВОЙ от горизонтали (ось y вниз):
                # 90° у него — текст сверху вниз, то есть наш поворот 270.
                pg["rot"] = 270 if target == 90 else 90


def plan_key(plan: "dict | None") -> "str | None":
    """Короткий отпечаток плана: им помечаются разборы надписей страниц
    (`pdfpage/NNNN`) — номер страницы без плана ничего не значит, и разбор,
    сделанный по листу, не должен лечь на виртуальную страницу с тем же
    номером."""
    if not plan:
        return None
    import hashlib
    import json
    keep = {k: plan.get(k) for k in ("v", "srcBox", "pages", "whole")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]


def _cached(key):
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
        return hit


def _cache_put(key, val) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = val
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def virtualize(pdf_bytes: bytes) -> "tuple | None":
    """(виртуальный PDF, план) либо None — обычный PDF или сборка не удалась.

    Работа идёт ОТДЕЛЬНЫМ процессом: разбор содержимого листа в 57 МБ —
    это десятки секунд чистого Python, и в процессе API они держали бы
    единственный воркер (инвариант 1). Не вышло запустить процесс — тот же
    код здесь же. Кэш по sha: импорт, проба и смета зовут подряд."""
    import hashlib
    if not _maybe_ribbon(pdf_bytes):
        return None                     # обычные листы — ни процесса, ни разбора
    key = ("v", hashlib.sha1(pdf_bytes).hexdigest())
    hit = _cached(key)
    if hit is not None:
        return hit[0]
    if key[1] in _NOT_RIBBON:
        return None
    res = _run_child("virtualize", pdf_bytes, None)
    if res is _NO_CHILD:
        res = _virtualize(pdf_bytes)
    if res is None:
        with _CACHE_LOCK:
            _NOT_RIBBON.add(key[1])
            while len(_NOT_RIBBON) > 64:
                _NOT_RIBBON.pop()
        return None
    _cache_put(key, (res,))
    _cache_put(("c", key[1], plan_key(res[1])), (res[0],))
    return res


_NOT_RIBBON: set = set()


def _maybe_ribbon(pdf_bytes: bytes) -> bool:
    """Дешёвая проба ДО разбора содержимого: лента — это лист хотя бы вдвое
    выше страницы, а страница не уже квадрата, то есть лист выше
    `RIBBON_MIN_RATIO` своих ширин. Обычная книга сюда не проходит, и ей
    не за что платить дочерним процессом на каждой загрузке."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            mb = page.mediabox
            if float(mb.height) >= RIBBON_MIN_RATIO * max(float(mb.width), 1.0):
                return True
    except Exception:
        return False
    return False


RIBBON_MIN_RATIO = 1.9


def compose_plan(pdf_bytes: bytes, plan: dict) -> "bytes | None":
    """Виртуальный PDF по ГОТОВОМУ плану (из раскладки проекта) — без поиска
    страниц, поворотов и самопроверки: координаты раскладки заданы планом,
    и пересобранный файл обязан им совпадать при любой смене правил поиска."""
    import hashlib
    key = ("c", hashlib.sha1(pdf_bytes).hexdigest(), plan_key(plan))
    hit = _cached(key)
    if hit is not None:
        return hit[0]
    res = _run_child("compose", pdf_bytes, plan)
    if res is _NO_CHILD:
        try:
            res = _compose(pdf_bytes, plan, frozenset(plan.get("whole") or ()))
        except Exception:
            res = None
    if res is not None:
        _cache_put(key, (res,))
    return res


def _virtualize(pdf_bytes: bytes) -> "tuple | None":
    try:
        from pypdf import PdfReader
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        contents = [_content(p) for p in reader.pages]
        plan = detect(reader, contents)
    except Exception:
        return None
    if plan is None:
        return None
    try:
        draft = _compose(pdf_bytes, plan)
        with PDFIUM_LOCK:
            src = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
            v = pdfium.PdfDocument(io.BytesIO(draft))
            try:
                if _ink_outside(src, plan):
                    return None
                bad = _check(src, v, plan)
                _orient(v, plan)
            finally:
                v.close()
                src.close()
        plan["whole"] = sorted(bad)
        out = _compose(pdf_bytes, plan, frozenset(bad))
    except Exception:
        return None
    return out, plan


# --- отдельный процесс -------------------------------------------------------

CHILD_TIMEOUT = 900
_NO_CHILD = object()


def _run_child(cmd: str, pdf_bytes: bytes, plan) -> object:
    """Запуск этого же файла отдельным процессом. Ответ: результат команды,
    None (команда ответила «нет»), либо _NO_CHILD — процесс не запустился
    или упал (тогда вызывающий считает здесь же)."""
    import json
    import os
    import subprocess
    import sys
    if os.environ.get("PDF_PANELS_INPROC") == "1":
        return _NO_CHILD
    script = os.path.abspath(__file__)
    head = json.dumps({"cmd": cmd, "plan": plan}).encode()
    try:
        proc = subprocess.run([sys.executable, script], input=len(head).to_bytes(8, "big") + head
                              + pdf_bytes, capture_output=True, timeout=CHILD_TIMEOUT)
    except (OSError, ValueError):
        return _NO_CHILD                # процесс не запустился — считаем здесь
    except Exception:
        # Таймаут: тот же разбор здесь держал бы единственный воркер ещё
        # столько же. Ответ — «не вышло», файл идёт как обычный PDF.
        return None
    out = proc.stdout
    if proc.returncode != 0 or len(out) < 8:
        # Ребёнок упал (pdfium на битом файле роняет процесс целиком): здесь
        # он уронил бы сервис — «не вышло», а не повтор в своём процессе.
        return None
    n = int.from_bytes(out[:8], "big")
    try:
        meta = json.loads(out[8:8 + n])
    except Exception:
        return _NO_CHILD
    body = out[8 + n:]
    if not meta.get("ok"):
        return None
    if cmd == "virtualize":
        return body, meta["plan"]
    return body


def _child_main() -> int:
    import json
    import sys
    raw = sys.stdin.buffer.read()
    n = int.from_bytes(raw[:8], "big")
    head = json.loads(raw[8:8 + n])
    pdf = raw[8 + n:]
    meta, body = {"ok": False}, b""
    if head.get("cmd") == "virtualize":
        res = _virtualize(pdf)
        if res is not None:
            body, plan = res
            meta = {"ok": True, "plan": plan}
    elif head.get("cmd") == "compose":
        plan = head.get("plan") or {}
        try:
            body = _compose(pdf, plan, frozenset(plan.get("whole") or ()))
            meta = {"ok": True}
        except Exception:
            meta = {"ok": False}
    m = json.dumps(meta).encode()
    sys.stdout.buffer.write(len(m).to_bytes(8, "big") + m + body)
    sys.stdout.buffer.flush()
    return 0


# --- обратно в листы ---------------------------------------------------------

def unsplit(vpdf: bytes, plan: dict) -> bytes:
    """Выгрузка «как в файле»: виртуальные страницы (уже с переводом) —
    обратно в листы исходного размера, каждая на своё место и под своим
    углом, обрезанная своим куском."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               FloatObject, NameObject)
    reader = PdfReader(io.BytesIO(vpdf))
    writer = PdfWriter()
    sheets = []
    for box in plan["srcBox"]:
        p = writer.add_blank_page(width=box[2] - box[0], height=box[3] - box[1])
        if box[0] or box[1]:
            p.mediabox.lower_left = (box[0], box[1])
            p.mediabox.upper_right = (box[2], box[3])
        sheets.append((p, DictionaryObject(), []))
    for n, pg in enumerate(plan["pages"]):
        vp = reader.pages[n]
        w, h = page_size(pg)
        res = vp.get("/Resources")
        res = res.get_object() if res is not None else DictionaryObject()
        form = DecodedStreamObject()
        form.set_data(_content(vp))
        form.update({NameObject("/Type"): NameObject("/XObject"),
                     NameObject("/Subtype"): NameObject("/Form"),
                     NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0),
                                                       FloatObject(w), FloatObject(h)]),
                     NameObject("/Resources"): writer._add_object(res.clone(writer))})
        try:
            form = form.flate_encode()
        except Exception:
            pass
        ref = writer._add_object(form)
        for pc in pg["pieces"]:
            page, xobj, body = sheets[pc["src"]]
            name = "/V%d" % n
            xobj[NameObject(name)] = ref
            r = pc["rect"]
            body.append(b"q " + b" ".join(_num(v) for v in (r[0], r[1], r[2] - r[0], r[3] - r[1]))
                        + b" re W n " + _cm(inverse(piece_matrix(pg, pc))) + b" "
                        + name.encode() + b" Do Q")
    for page, xobj, body in sheets:
        cs = DecodedStreamObject()
        cs.set_data(b"\n".join(body))
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): xobj})
        page[NameObject("/Contents")] = writer._add_object(_flate(cs))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


if __name__ == "__main__":
    raise SystemExit(_child_main())
