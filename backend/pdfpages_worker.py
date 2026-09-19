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


def page_lines(page) -> tuple:
    """(строки, геометрия | None) одной страницы pypdf.

    Геометрия: {"box": [x0, y0, x1, y1] страницы, "lines": [[x0, y, кегль,
    x1] | None на каждую строку], "figs": [[x0, y0, x1, y1] картинок],
    "rects": [[x0, y0, x1, y1] нарисованных прямоугольников]}. y — базовая
    линия, ось вверх, как в самом PDF. x1 — конец строки: где его показал
    следующий кусок той же строки — точно, иначе оценкой по числу знаков
    и ширине знака, замеренной на этой же странице. Строка без буквенных
    кусков или повёрнутая — None: гадать её место незачем."""
    chunks: list = []           # (текст, x, y, кегль, повёрнут)
    figs: list = []
    rects: list = []
    pending: list = []
    state = {"clip": False}
    try:
        xobjs = page.get("/Resources", {}).get("/XObject", {}) or {}
        xobjs = xobjs.get_object() if hasattr(xobjs, "get_object") else xobjs
    except Exception:
        xobjs = {}

    def vt(text, cm, tm, _fd, fs):
        try:
            x, y = _xy(cm, tm[4], tm[5])
            sy = abs(tm[3] * cm[3]) or abs(tm[0] * cm[0]) or 1.0
            rot = abs(tm[1]) + abs(tm[2]) > 1e-3 * (abs(tm[0]) + abs(tm[3])) or abs(cm[1]) + abs(cm[2]) > 1e-3
            chunks.append((text or "", x, y, float(fs or 0) * sy, rot))
        except Exception:
            chunks.append((text or "", None, None, 0.0, True))

    def vo(op, args, cm, _tm):
        try:
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
                pending.clear()
                state["clip"] = False
            elif op == b"Do" and args:
                obj = xobjs.get(args[0]) if hasattr(xobjs, "get") else None
                obj = obj.get_object() if hasattr(obj, "get_object") else obj
                if obj is not None and obj.get("/Subtype") == "/Image":
                    pts = [_xy(cm, 0, 0), _xy(cm, 1, 1)]
                    figs.append([min(p[0] for p in pts), min(p[1] for p in pts),
                                 max(p[0] for p in pts), max(p[1] for p in pts)])
        except Exception:
            pass

    try:
        out = page.extract_text(visitor_text=vt, visitor_operand_before=vo) or ""
    except TypeError:
        # Старый pypdf или подмена без посетителей — строки без геометрии.
        return (page.extract_text() or "").splitlines(), None
    lines = out.splitlines()
    try:
        geom = _geometry(lines, out, chunks, figs, rects, page)
    except Exception:
        geom = None
    return lines, geom


def _geometry(lines, out, chunks, figs, rects, page):
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
    geo_lines = []
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
        if not body or any(chunks[k][4] for k in body):
            geo_lines.append(None)
            continue
        first = chunks[body[0]]
        x0, y, size = first[1], first[2], first[3]
        x1 = x0
        for k in ks:
            c = chunks[k]
            if c[1] is None or starts[k] < a or abs(c[2] - y) > 0.5 * max(size, 1.0):
                continue
            if c[0].strip():
                piece = c[0].strip("\n")
                x1 = max(x1, c[1] + len(piece.rstrip()) * cw * (c[3] or size))
            elif c[1] > x0:
                x1 = max(x1, c[1])       # пробел после текста — точный конец строки
        geo_lines.append([round(x0, 1), round(y, 1), round(size, 2), round(x1, 1)])
    # Одна строка ответа — одна строка геометрии; иначе смысла в ней нет.
    if len(geo_lines) != len(lines):
        return None
    try:
        mb = page.mediabox
        box = [float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)]
    except Exception:
        box = None
    r1 = lambda v: [round(float(t), 1) for t in v]   # noqa: E731
    return {"box": r1(box) if box else None, "lines": geo_lines,
            "figs": [r1(f) for f in figs], "rects": [r1(r) for r in rects]}


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
