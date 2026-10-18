"""Замеры точности: тот же ли вид у переведённой картинки, что у исходной.

Вопрос «вышел ли файл таким же» до сих пор отвечали глаза человека
(сверка первой выгрузки, `docs/rules/export-review.md`). Здесь — то, что
можно посчитать без глаз, на пикселях исходника и выгрузки, по каждой
надписи (рамке блока) и по картинке целиком:

  * `leftover` — доля краски оригинала, оставшейся НЕТРОНУТОЙ в рамке
    (пиксель буквы оригинала совпал с выгрузкой). У стёртой и переписанной
    надписи это доля случайных совпадений с новыми буквами — её база
    вычитается (`leftoverExcess`);
  * `xh` — высота строчных перевода против оригинала (Х10, Ф5);
  * `dens` — плотность набора (доля краски в полосе строчных, Х13);
  * `dInk` — расстояние цвета краски (RGB, евклид);
  * `icons` — цветные значки (Х18): сколько было в рамке и сколько стало
    рядом с ней;
  * `outside` — доля изменённых точек ВНЕ рамок надписей (поле —
    `FID_PAD` строки): рисунок должен остаться нетронутым.

Пороги — из окружения; ответ — числа и коды предупреждений, без русских
фраз (фразу собирает показ). Это ПРЕДУПРЕЖДЕНИЕ, а не запрет: замер
надписи может ошибиться так же, как раскраска, и решает человек.
Ни одной записи на диск и в STATE; вызывать вне потока запроса
(инструмент `tools/fidelity_report.py`, сверка выгрузки), потому что
воркер один.
"""
from __future__ import annotations

import io
import os

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

FID_XH_TOL = float(os.environ.get("FID_XH_TOL", "0.25"))        # |xh − 1|
FID_DENS_TOL = float(os.environ.get("FID_DENS_TOL", "0.35"))    # |dens − 1|
FID_INK = float(os.environ.get("FID_INK", "60"))                # расстояние цвета
FID_LEFT = float(os.environ.get("FID_LEFT", "0.15"))            # сверх базы совпадений
FID_OUTSIDE = float(os.environ.get("FID_OUTSIDE", "0.002"))     # доля точек вне рамок
FID_PAD = float(os.environ.get("FID_PAD", "0.6"))               # поле рамки, строк
FID_DIFF = int(os.environ.get("FID_DIFF", "24"))                # «точка изменена»


def _rgb(img) -> "np.ndarray | None":
    from PIL import Image
    if img is None:
        return None
    if isinstance(img, (bytes, bytearray)):
        img = Image.open(io.BytesIO(img))
    if hasattr(img, "convert"):
        img = np.asarray(img.convert("RGB"))
    return np.ascontiguousarray(img[..., :3]).astype(np.uint8)


def _box_of(it: dict) -> "list | None":
    b = it.get("box")
    if not b or len(b) < 4:
        return None
    return [int(b[0]), int(b[1]), int(b[2]), int(b[3])]


def _measure(tp, rgb, it: dict, box):
    x0, y0, x1, y1 = box
    rows = max(1, int(it.get("rows") or 1))
    m = tp.measure(rgb[y0:y1, x0:x1].copy(), it.get("src") or "", rows, float(it.get("lineH") or 0))
    return m if m.get("found") else None


def _lines(it: dict, box):
    x0, y0 = box[0], box[1]
    lbs = it.get("lineBoxes") or []
    if lbs:
        return [[lb[0] - x0, lb[1] - y0, lb[2] - x0, lb[3] - y0] for lb in lbs]
    return [[0, 0, box[2] - box[0], box[3] - box[1]]]


def block_metrics(tp, a, b, it: dict) -> "dict | None":
    """Замер одной надписи: `a` — исходник, `b` — выгрузка (RGB одного размера)."""
    box = _box_of(it)
    if box is None:
        return None
    H, W = a.shape[:2]
    lh = float(it.get("lineH") or max(1, (box[3] - box[1]) / max(1, int(it.get("rows") or 1))))
    pad = int(round(0.15 * lh))
    box = [max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(H, box[3] + pad)]
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return None
    ma = _measure(tp, a, it, box)
    if ma is None:
        return None
    x0, y0, x1, y1 = box
    ca, cb = a[y0:y1, x0:x1].astype(np.int16), b[y0:y1, x0:x1].astype(np.int16)
    ink_a = ma["mask"]
    same = np.abs(ca - cb).max(axis=2) <= 8
    out = {"box": box}
    n_ink = int(ink_a.sum())
    if n_ink:
        kept = float((same & ink_a).sum()) / n_ink
        mb = _measure(tp, b, it, box)
        base = float(mb["mask"].mean()) if mb is not None else 0.0
        out["leftover"] = round(kept, 3)
        out["leftoverExcess"] = round(max(0.0, kept - base), 3)
    else:
        mb = _measure(tp, b, it, box)
    if mb is not None:
        W_ = x1 - x0
        # Обе стороны — маской по цвету КРАСКИ оригинала, полосы — из неё же:
        # линии клетки и разлиновки другого цвета и в маску не попадают
        # (на конспекте в клетку маска выгрузки брала сетку, и высота
        # строчных выходила впятеро меньше настоящей).
        bg_c = ma.get("bg") or (255, 255, 255)
        ka, kb = _ink_mask(ca, ma["ink"], bg_c), _ink_mask(cb, ma["ink"], bg_c)
        la = [[0, p, W_, q + 1] for p, q in _bands_of(ka)] or _lines(it, [x0, y0])
        lb = [[0, p, W_, q + 1] for p, q in _bands_of(kb)] or [[0, 0, W_, y1 - y0]]
        if _cased(it.get("text") or ""):
            xa, xb = _main_xh(tp, ka, la), _main_xh(tp, kb, lb)
            if xa > 0 and xb > 0:
                out["xh"] = round(xb / xa, 3)
        else:
            # Письмо без строчных (иероглифы, арабица): высота строки краски.
            ha = float(np.median([q - p + 1 for p, q in ma["bands"]])) if ma["bands"] else 0.0
            hb = float(np.median([q - p + 1 for p, q in mb["bands"]])) if mb["bands"] else 0.0
            if ha > 0 and hb > 0:
                out["lineH"] = round(hb / ha, 3)
        bg = ma.get("bg") or (255, 255, 255)
        da = tp.band_density(ca.astype(np.uint8), la, bg, ma["ink"])
        db = tp.band_density(cb.astype(np.uint8), lb, bg, mb["ink"])
        if da and db and _cased(it.get("src") or "") == _cased(it.get("text") or ""):
            out["dens"] = round(db / da, 3)
        out["dInk"] = round(float(np.sqrt(sum((float(p) - float(q)) ** 2
                                                for p, q in zip(ma["ink"][:3], mb["ink"][:3])))), 1)
    try:
        icons_a = tp.find_icons(ca.astype(np.uint8), ma["mask"], ma["bands"], ma["ink"], ma.get("bg"))
    except Exception:
        icons_a = []
    ia = len(icons_a)
    if ia:
        # Значок — пятно не меньше трети площади исходного: обрезок
        # недостёртого значка значком не считается.
        amin = 0.33 * min(int((ic["sprite"][..., 3] > 0).sum()) for ic in icons_a)
        # Значок мог встать правее рамки (после перевода) — смотрим шире.
        wx1 = min(W, x1 + int(3 * lh))
        cw = b[y0:y1, x0:wx1]
        sat = cw.max(axis=2).astype(int) - cw.min(axis=2).astype(int)
        out["icons"] = [ia, int(_blobs(sat > tp.ICON_SAT, amin))]
    return out


def _ink_mask(c, ink, bg):
    """Точки цвета краски: ближе к краске, чем на треть пути к бумаге."""
    ink_a = np.array(ink[:3], dtype=np.int32)
    bg_a = np.array(bg[:3], dtype=np.int32)
    far = float(np.sqrt(((ink_a - bg_a) ** 2).sum())) or 1.0
    d = np.sqrt(((c.astype(np.int32)[..., :3] - ink_a) ** 2).sum(axis=2))
    return d < far / 3.0


def _bands_of(mask, share: float = 0.08) -> list:
    """Полосы строк по профилю маски: подряд идущие ряды с краской."""
    prof = mask.sum(axis=1)
    if not prof.max():
        return []
    on = prof >= share * prof.max()
    out, start = [], None
    for y, v in enumerate(on):
        if v and start is None:
            start = y
        elif not v and start is not None:
            out.append((start, y - 1))
            start = None
    if start is not None:
        out.append((start, len(on) - 1))
    return [b for b in out if b[1] - b[0] >= 2]


def _main_xh(tp, mask, boxes) -> float:
    """Высота строчных ОСНОВНОГО размера: строки не меньше `0.75` самой
    крупной. У блока «заголовок + мелкие авторы» (Х14) средняя смешала бы
    два размера, и сравнение врало бы на ровном месте."""
    v = [tp.x_height(mask, [b]) for b in boxes]
    v = [x for x in v if x > 0]
    if not v:
        return 0.0
    top = max(v)
    main = sorted(x for x in v if x >= 0.75 * top)
    return float(main[len(main) // 2])


def _cased(t: str) -> bool:
    """Есть ли у письма строчные: «высота строчных» мерится только у него."""
    letters = [ch for ch in t if ch.isalpha()]
    return bool(letters) and sum(ch.islower() for ch in letters) * 2 >= len(letters)


def _blobs(mask, amin: float = 12) -> int:
    try:
        import cv2
        n, _l, st, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        return int(sum(1 for i in range(1, n) if st[i][4] >= max(12, amin)))
    except Exception:
        return int(bool(mask.sum()))


def outside_share(a, b, items: list) -> float:
    """Доля изменённых точек вне рамок надписей (с полем)."""
    H, W = a.shape[:2]
    keep = np.ones((H, W), bool)
    for it in items:
        box = _box_of(it)
        if box is None:
            continue
        lh = float(it.get("lineH") or max(1, (box[3] - box[1]) / max(1, int(it.get("rows") or 1))))
        p = int(round(FID_PAD * lh))
        # Значок конца строки (Х18) встаёт правее рамки — его место тоже «своё».
        keep[max(0, box[1] - p):min(H, box[3] + p), max(0, box[0] - p):min(W, box[2] + int(3 * lh))] = False
    if not keep.any():
        return 0.0
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > FID_DIFF
    return round(float((diff & keep).sum()) / float(keep.sum()), 5)


def warnings_of(m: dict) -> list:
    """Коды предупреждений надписи по порогам."""
    w = []
    if m.get("leftoverExcess", 0.0) > FID_LEFT:
        w.append("leftover")
    if "xh" in m and abs(m["xh"] - 1.0) > FID_XH_TOL:
        w.append("xh")
    if "lineH" in m and abs(m["lineH"] - 1.0) > FID_XH_TOL:
        w.append("lineH")
    if "dens" in m and abs(m["dens"] - 1.0) > FID_DENS_TOL:
        w.append("dens")
    if m.get("dInk", 0.0) > FID_INK:
        w.append("ink")
    ic = m.get("icons")
    if ic and ic[1] < ic[0]:
        w.append("icons")
    return w


def compare(orig, out, items: list) -> dict:
    """Замер выгрузки против исходника: {blocks: [{i, ...метрики, warn}],
    outside, warn, summary}. `items` — те же, что ушли в `render_target`."""
    try:
        import text_paint as tp
    except Exception:
        tp = None
    if np is None or tp is None:
        return {"blocks": [], "outside": None, "warn": ["no_engine"], "summary": {}}
    try:
        a, b = _rgb(orig), _rgb(out)
    except Exception:
        return {"blocks": [], "outside": None, "warn": ["unreadable"], "summary": {}}
    if a is not None and b is not None and a.shape != b.shape:
        # Раскраска мелкой картинки рисует с увеличением (`render_target`,
        # k) и отдаёт её крупнее: те же пропорции — сводим к размеру оригинала.
        ha, wa = a.shape[:2]
        hb, wb = b.shape[:2]
        if hb and wb and abs(wa / float(ha) - wb / float(hb)) < 0.01:
            from PIL import Image
            b = np.asarray(Image.fromarray(b).resize((wa, ha), Image.LANCZOS))
    if a is None or b is None or a.shape != b.shape:
        return {"blocks": [], "outside": None, "warn": ["size"], "summary": {}}
    blocks = []
    for i, it in enumerate(items):
        try:
            m = block_metrics(tp, a, b, it)
        except Exception:
            m = None
        if m is None:
            continue
        m["i"] = i
        m["warn"] = warnings_of(m)
        blocks.append(m)
    outs = outside_share(a, b, items)
    warn = sorted({w for m in blocks for w in m["warn"]})
    if outs > FID_OUTSIDE:
        warn.append("outside")
    vals = {k: [m[k] for m in blocks if k in m] for k in ("xh", "lineH", "dens", "leftoverExcess", "dInk")}
    summary = {k: round(float(np.median(v)), 3) for k, v in vals.items() if v}
    summary["blocks"] = len(blocks)
    summary["warned"] = sum(1 for m in blocks if m["warn"])
    return {"blocks": blocks, "outside": outs, "warn": warn, "summary": summary}
