"""Векторная печать строки любой письменности: сборка букв HarfBuzz
(`uharfbuzz`, Apache-2.0) и контуры глифов в PDF слоя выгрузки.

Зачем. reportlab кладёт глифы по одному, слева направо и без сборки букв:
арабица и иврит вышли бы задом наперёд и несвязанными, у индийских,
тайского, кхмерского и бирманского огласовки встали бы не на свои места,
а иероглифы (шрифты только OTF/CFF) он не грузит вовсе. До этого модуля
такие строки печатались КАРТИНКОЙ (Pillow + raqm, 4 пикселя на пункт):
мыло при увеличении, тяжёлый файл и ширина, округлённая до пикселя.
Здесь та же сборка (raqm внутри — тот же HarfBuzz), но буквы уходят
в PDF контурами: чёткие на любом масштабе, ширина — точная.

Устройство:
* `shape()` — глифы и сдвиги в единицах шрифта (кэш по файлу, тексту,
  направлению): укладка меряет одну и ту же строку десятки раз;
* `draw()` — каждый РАЗНЫЙ глиф один раз становится формой (Form XObject)
  документа, кусок строки — формой из ссылок на глифы, а на странице
  стоит одна ссылка на кусок: книга из тысяч одинаковых букв не повторяет
  их контуры, а поток страницы не растёт от числа букв. Кэш форм живёт НА ХОЛСТЕ — форма другого
  документа в этом не существует. В теле формы нет цвета: цвет, ширина
  обводки и сдвиги — у вызывающего;
* полужирного файла нет — обводка контура (вторая форма с «B», ширина
  линии задаётся вызывающим в единицах шрифта).

Чего НЕ делает, и это названо: текст контурами не копируется и не ищется
(как и картинка до него) — для этого нужен вшитый CID-шрифт с ToUnicode,
reportlab глифы по номеру не адресует. Порядок кусков справа налево
(двунаправленный алгоритм) считает вызывающий (`layout_pdf._bidi_levels`),
внутри куска порядок и сборку делает HarfBuzz. Цветные глифы (эмодзи,
COLR) рисуются одним цветом.

`LAYOUT_VECTOR=0` выключает модуль без выката — печать вернётся картинкой.
"""
from __future__ import annotations

import os
import threading
from functools import lru_cache

try:                                   # необязательная зависимость
    import uharfbuzz as hb
except Exception:                      # нет модуля — печать картинкой
    hb = None

ENABLED = os.environ.get("LAYOUT_VECTOR", "1") != "0"
# Рамка формы глифа в долях кегля: контур не выходит за неё ни у одного
# шрифта (огласовки арабицы и тибетского — до ~1.5 em вверх и вниз).
FORM_BOX = 3.0

_LOCK = threading.Lock()
_FONTS: dict = {}


def available() -> bool:
    """Есть ли векторная печать: модуль на месте, рисование контуров
    поддержано (uharfbuzz ≥ 0.45) и её не выключили окружением."""
    return bool(ENABLED and hb is not None and hasattr(getattr(hb, "Font", None),
                                                       "draw_glyph_with_pen"))


def _font(path: str):
    f = _FONTS.get(path)
    if f is None:
        with _LOCK:
            f = _FONTS.get(path)
            if f is None:
                face = hb.Face(hb.Blob.from_file_path(path))
                f = _FONTS[path] = (hb.Font(face), int(face.upem) or 1000)
    return f


def upem(path: str) -> int:
    return _font(path)[1]


@lru_cache(maxsize=50000)
def shape(path: str, text: str, rtl: bool) -> tuple:
    """((глиф, ширина, сдвиг x, сдвиг y), …) в единицах шрифта, в ВИДИМОМ
    порядке слева направо (у куска справа налево HarfBuzz сам отдаёт так).
    Направление задаём явно: угадывание у куска из одних знаков препинания
    ошибается, а сторону куска уже решил двунаправленный алгоритм."""
    if not text:
        return ()
    font, _u = _font(path)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    buf.direction = "rtl" if rtl else "ltr"
    hb.shape(font, buf, {})
    return tuple((i.codepoint, p.x_advance, p.x_offset, p.y_offset)
                 for i, p in zip(buf.glyph_infos, buf.glyph_positions))


def notdef(path: str, text: str, rtl: bool = False) -> int:
    """Сколько знаков строки шрифт не знает (глиф 0 после сборки):
    проверка по таблице знаков не видит знаков, которые шрифт «знает»,
    а собрать не может."""
    return sum(1 for g in shape(path, text, rtl) if g[0] == 0)


def width(path: str, text: str, rtl: bool, size: float) -> float:
    """Ширина куска в пунктах при кегле `size`."""
    if not text:
        return 0.0
    return sum(g[1] for g in shape(path, text, rtl)) * size / float(upem(path))


class _Pen:
    """Контур глифа — операторами пути PDF (единицы шрифта). Квадратичные
    кривые TrueType переводятся в кубические: в PDF других нет."""

    def __init__(self):
        self.ops: list = []
        self.cur = (0.0, 0.0)

    @staticmethod
    def _n(v: float) -> str:
        r = round(v, 1)
        return ("%d" % r) if r == int(r) else ("%.1f" % r)

    def moveTo(self, p):
        self.ops.append("%s %s m" % (self._n(p[0]), self._n(p[1])))
        self.cur = p

    def lineTo(self, p):
        self.ops.append("%s %s l" % (self._n(p[0]), self._n(p[1])))
        self.cur = p

    def curveTo(self, *pts):
        # Несколько точек подряд — цепочка кубических кривых по три.
        for k in range(0, len(pts) - 2, 3):
            a, b, e = pts[k], pts[k + 1], pts[k + 2]
            self.ops.append(" ".join(self._n(v) for v in (*a, *b, *e)) + " c")
            self.cur = e

    def qCurveTo(self, *pts):
        # TrueType: подряд идущие внеконтурные точки, между ними — неявные
        # опорные (середины); последняя точка — опорная.
        offs, end = list(pts[:-1]), pts[-1]
        for k, q in enumerate(offs):
            nxt = end if k == len(offs) - 1 else (
                (q[0] + offs[k + 1][0]) / 2.0, (q[1] + offs[k + 1][1]) / 2.0)
            p0 = self.cur
            c1 = (p0[0] + 2.0 / 3.0 * (q[0] - p0[0]), p0[1] + 2.0 / 3.0 * (q[1] - p0[1]))
            c2 = (nxt[0] + 2.0 / 3.0 * (q[0] - nxt[0]), nxt[1] + 2.0 / 3.0 * (q[1] - nxt[1]))
            self.ops.append(" ".join(self._n(v) for v in (*c1, *c2, *nxt)) + " c")
            self.cur = nxt
        if not offs:
            self.lineTo(end)

    def closePath(self):
        self.ops.append("h")

    def endPath(self):
        pass


@lru_cache(maxsize=20000)
def _outline(path: str, gid: int) -> str:
    pen = _Pen()
    _font(path)[0].draw_glyph_with_pen(gid, pen)
    return "\n".join(pen.ops)


def _form_name(c, path: str, gid: int, bold: bool) -> "str | None":
    """Имя формы глифа В ЭТОМ документе (заводит при первом обращении);
    пустой контур (пробел) — None: рисовать нечего."""
    forms = getattr(c, "_mct_glyph_forms", None)
    if forms is None:
        forms = c._mct_glyph_forms = {"_files": {}}
    key = (path, gid, bold)
    if key in forms:
        return forms[key]
    body = _outline(path, gid)
    if not body:
        forms[key] = None
        return None
    files = forms["_files"]
    fi = files.setdefault(path, len(files))
    name = "mctg%d_%d%s" % (fi, gid, "b" if bold else "")
    u = upem(path) * FORM_BOX
    c.beginForm(name, -u, -u, u, u)
    # Тело — только путь: цвет заливки, обводки и ширину линии форма берёт
    # у того, кто её ставит.
    c._code.append(body + ("\nB" if bold else "\nf"))
    c.endForm()
    forms[key] = name
    return name


def _run_form(c, path: str, text: str, rtl: bool, bold: bool) -> "tuple | None":
    """(имя формы КУСКА, ширина в единицах шрифта): буквы куска стоят внутри
    формы своими формами глифов. На странице остаётся ОДНА ссылка на кусок,
    а не «q cm Do Q» на каждую букву: pypdf при наложении слоя разбирает
    весь поток страницы, и пять операторов на букву стоили ~2.5 с на
    страницу (книга в 378 страниц — четверть часа)."""
    forms = getattr(c, "_mct_glyph_forms", None)
    if forms is None:
        forms = c._mct_glyph_forms = {"_files": {}}
    runs = forms.setdefault("_runs", {})
    key = (path, text, rtl, bold)
    if key in runs:
        return runs[key]
    glyphs = shape(path, text, rtl)
    if not glyphs:
        runs[key] = None
        return None
    # Формы глифов — ДО формы куска: вложенный beginForm не нужен.
    names = [_form_name(c, path, g[0], bold) for g in glyphs]
    total = sum(g[1] for g in glyphs)
    u = upem(path) * FORM_BOX
    name = "mctr%d" % len(runs)
    c.beginForm(name, -u, -u, total + u, u)
    pen_x = 0.0
    for (gid, adv, dx, dy), nm in zip(glyphs, names):
        if nm:
            c._code.append("q 1 0 0 1 %s %s cm" % (_Pen._n(pen_x + dx), _Pen._n(dy)))
            c.doForm(nm)
            c._code.append("Q")
        pen_x += adv
    c.endForm()
    runs[key] = (name, total)
    return runs[key]


def draw(c, x: float, y: float, path: str, text: str, rtl: bool, size: float,
         hsc: float = 1.0, bold_stroke: float = 0.0) -> float:
    """Кусок текста одним файлом шрифта — контурами, базовая линия в (x, y)
    текущей системы координат. Цвет заливки (и обводки — у полужирного без
    своего файла, `bold_stroke` — толщина в пунктах) ставит вызывающий.
    Возвращает ширину в пунктах (с учётом сужения `hsc`)."""
    bold = bold_stroke > 0
    got = _run_form(c, path, text, rtl, bold)
    if not got:
        return 0.0
    name, total = got
    k = size / float(upem(path))
    c.saveState()
    if bold:
        # Ширина линии читается в системе координат ФОРМЫ (единицы шрифта).
        c.setLineWidth(bold_stroke / k)
        c.setLineJoin(1)
    c.transform(k * hsc, 0, 0, k, x, y)
    c.doForm(name)
    c.restoreState()
    return total * k * hsc
