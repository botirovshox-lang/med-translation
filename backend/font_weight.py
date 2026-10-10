"""Толщина основы буквы — по КОНТУРАМ встроенного шрифта.

Зачем. Полужирный у шрифта без имени («font0000000030790b66») не узнать ни
по имени, ни по описанию: урезанный TrueType несёт только cmap/glyf/hmtx,
таблиц OS/2 и name в нём нет, а /StemV в описании — 0. Замер по картинке
страницы не годится: на мелком кегле штрих упирается в пиксель, и обычный
текст в 4 пт выходил «жирнее» заголовка. Контур глифа от разрешения
не зависит: толщина вертикальной основы в долях кегля у обычного начертания
≈ 0.07–0.10, у полужирного ≈ 0.12–0.17 — у любой гарнитуры и языка.

Как. Берём буквы с вертикальной основой, которые есть в шрифте («l», «i»,
«n», «h», «I», «H», «T», кириллические «н», «п», «т», «І»…), рисуем глиф
в многоугольник (кривые дробятся на отрезки) и проводим горизонталь на 35%
высоты строчной: самый узкий закрашенный отрезок — основа. Медиана по
нескольким буквам — толщина шрифта.

Глиф ищется по КОДУ: буква → код по карте ToUnicode шрифта PDF (pypdf
`Font.character_map`), код → глиф (CID = номер глифа у Identity, имя «cidNNNNN»
у CFF с CID, cmap самого шрифта у простого). Нет fontTools, программы шрифта
или ни одной буквы с основой — None («не знаю»), и начертание остаётся тем,
что сказало имя."""

import io

# Буквы с вертикальной основой на высоте трети строчной.
STEM_CHARS = "lihnmuIHTLEнпитшНПТ"
BOLD_STEM = 0.115            # доля кегля: от неё основа — полужирная


class _PolyPen:
    """Перо fontTools → многоугольники (кривые — отрезками)."""

    def __init__(self):
        self.polys: list = []
        self.cur: list = []

    def moveTo(self, p):
        self._close()
        self.cur = [p]

    def lineTo(self, p):
        self.cur.append(p)

    def qCurveTo(self, *pts):
        start = self.cur[-1] if self.cur else pts[0]
        # Неявные точки между «вне кривой» — как у TrueType.
        ctrl = list(pts[:-1])
        end = pts[-1]
        seq = []
        for k, c in enumerate(ctrl):
            nxt = end if k == len(ctrl) - 1 else ((c[0] + ctrl[k + 1][0]) / 2.0, (c[1] + ctrl[k + 1][1]) / 2.0)
            seq.append((c, nxt))
        p0 = start
        for c, p2 in seq:
            for t in (0.25, 0.5, 0.75, 1.0):
                u = 1 - t
                self.cur.append((u * u * p0[0] + 2 * u * t * c[0] + t * t * p2[0],
                                 u * u * p0[1] + 2 * u * t * c[1] + t * t * p2[1]))
            p0 = p2
        if not ctrl:
            self.cur.append(end)

    def curveTo(self, *pts):
        p0 = self.cur[-1] if self.cur else pts[0]
        for k in range(0, len(pts) - 2, 3):
            c1, c2, p3 = pts[k], pts[k + 1], pts[k + 2]
            for t in (0.25, 0.5, 0.75, 1.0):
                u = 1 - t
                self.cur.append((u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p3[0],
                                 u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p3[1]))
            p0 = p3

    def closePath(self):
        self._close()

    endPath = closePath

    def addComponent(self, *a, **k):
        pass

    def _close(self):
        if len(self.cur) >= 3:
            self.polys.append(self.cur)
        self.cur = []


def _stem_at(polys: list, y: float):
    """Самый узкий закрашенный отрезок горизонтали y (правило чётности)."""
    xs = []
    for poly in polys:
        n = len(poly)
        for k in range(n):
            (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    runs = [xs[k + 1] - xs[k] for k in range(0, len(xs) - 1, 2)]
    runs = [r for r in runs if r > 0]
    return min(runs) if runs else None


def stem_ratio(desc, pdf_font, subtype: str = ""):
    """Толщина основы в долях кегля — либо None («не знаю»)."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    if desc is None:
        return None
    rev: dict = {}
    for code, u in ((getattr(pdf_font, "character_map", None) or {}).items()):
        if isinstance(u, str) and len(u) == 1:
            rev.setdefault(u, code)
    enc = getattr(pdf_font, "encoding", None)
    if isinstance(enc, dict):
        for code, u in enc.items():
            if isinstance(u, str) and len(u) == 1 and isinstance(code, int):
                rev.setdefault(u, chr(code))
    try:
        for key in ("/FontFile2", "/FontFile3"):
            ff = desc.get(key)
            if ff is None:
                continue
            ff = ff.get_object() if hasattr(ff, "get_object") else ff
            data = ff.get_data()
            sub = str(ff.get("/Subtype") or "")
            if key == "/FontFile2" or sub == "/OpenType":
                return _stem_sfnt(TTFont(io.BytesIO(data), lazy=True), rev, subtype)
            return _stem_cff(data, rev)
    except Exception:
        return None
    return None


def _measure(glyphs, upem: float, xh: float):
    vals = []
    for g in glyphs:
        pen = _PolyPen()
        try:
            g(pen)
        except Exception:
            continue
        pen._close()
        if not pen.polys:
            continue
        w = _stem_at(pen.polys, 0.35 * xh)
        if w:
            vals.append(w / upem)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def _stem_sfnt(tt, rev: dict, subtype: str):
    upem = float(tt["head"].unitsPerEm or 1000)
    gs = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    cmap = {}
    try:
        cmap = dict(tt.getBestCmap() or {})
    except Exception:
        cmap = {}
    # getBestCmap не берёт символьную (3,0) и маковскую (1,0) таблицы, а
    # урезанный шрифт без имени часто несёт ТОЛЬКО их — дописываем.
    try:
        for pid, eid in ((3, 0), (1, 0)):
            st = tt["cmap"].getcmap(pid, eid)
            if st is not None:
                for k, v in st.cmap.items():
                    cmap.setdefault(k, v)
    except Exception:
        pass
    names = []
    for ch in STEM_CHARS:
        name = cmap.get(ord(ch))
        if name is None and ch in rev:
            code = rev[ch]
            code = ord(code) if isinstance(code, str) else int(code)
            if subtype == "/Type0" and 0 <= code < len(order):
                name = order[code]                 # Identity: CID = номер глифа
            elif code in cmap:
                name = cmap[code]
            elif (0xF000 + code) in cmap:          # символьный cmap (3,0)
                name = cmap[0xF000 + code]
        if name and name in gs:
            names.append(name)
    xh = 0.5 * upem
    try:
        os2 = tt["OS/2"]
        if getattr(os2, "sxHeight", 0):
            xh = float(os2.sxHeight)
    except Exception:
        pass
    return _measure([gs[n].draw for n in names[:6]], upem, xh)


def _stem_cff(data: bytes, rev: dict):
    from fontTools.cffLib import CFFFontSet
    cff = CFFFontSet()
    cff.decompile(io.BytesIO(data), None)
    top = cff[cff.fontNames[0]]
    cs = top.CharStrings
    upem = 1000.0
    try:
        upem = 1.0 / float(top.FontMatrix[0])
    except Exception:
        pass
    names = []
    for ch in STEM_CHARS:
        if ch not in rev:
            continue
        code = rev[ch]
        code = ord(code) if isinstance(code, str) else int(code)
        for name in ("cid%05d" % code, ch):
            if name in cs:
                names.append(name)
                break
    return _measure([cs[n].draw for n in names[:6]], upem, 0.5 * upem)
