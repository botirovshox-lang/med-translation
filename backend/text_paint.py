# -*- coding: utf-8 -*-
"""Надпись на картинке: измерить, стереть, написать перевод КАК В ОРИГИНАЛЕ.

Один модуль на две дороги — выгрузку PDF «как в оригинале» (надписи схем
и страниц-картинок, `layout_pdf`) и перерисовку картинок .docx и скана
(`image_text.render_target`). Прежде у каждой дороги были свои правила, и обе
печатали перевод надписи не так, как она стояла: засечками вместо рубленого,
чёрным вместо цвета оригинала, кеглем, равным высоте рамки детектора (она
с запасом — буквы выходили крупнее), горизонтально поверх дуги и сплошной
заплаткой на фотографии. А на неровном фоне .docx отказывался и клал перевод
ПОДПИСЬЮ под картинкой — читатель этого не просил.

Что меряется — по ПИКСЕЛЯМ самой надписи, без модели и без языка:
  * фон под буквами — медианой окрестности шире штриха (`cv2.medianBlur`):
    у фотографии и градиента «цвета бумаги» нет, есть фон КАЖДОЙ точки;
  * маска букв — точки, отличные от своего фона больше `INK_DIFF`;
  * цвет букв — ядро маски, самая далёкая от фона треть (полутона края
    буквы увели бы цвет в серое);
  * строки — полосы по проекции маски; высота букв → кегль: заглавные —
    0.72 кегля, строчные с выносными — 0.95 (по исходному тексту надписи);
  * толщина штриха (медиана горизонтальных серий маски) / кегль →
    полужирный при `BOLD_STEM` и выше;
  * наклон — главная ось маски у ОДНОСТРОЧНОЙ надписи, вытянутой не меньше
    чем в `ANGLE_ELONG` раз: подпись вдоль оси, дуга кольца (по хорде),
    корешок книги. У многострочного блока ось — это ось блока, а не строки,
    и угол не меряется вовсе.

Стирание: ровный фон — заливка его цветом; неровный — `cv2.inpaint`
(Telea) по расширенной маске БУКВ: рисунок вокруг букв не трогается вовсе,
а заплатка на PDF кладётся с прозрачностью вне маски.
"""
from __future__ import annotations

import math
import os

try:
    import numpy as np
except Exception:                                   # pragma: no cover
    np = None
try:
    import cv2
except Exception:                                   # pragma: no cover
    cv2 = None

# На сколько (из 255, по самому далёкому каналу) точка отличается от своего
# фона, чтобы считаться буквой.
INK_DIFF = float(os.environ.get("PAINT_INK_DIFF", "48"))
# Ровный фон: разброс фона под рамкой не больше этого — заливка, а не inpaint.
FLAT_STD = float(os.environ.get("PAINT_FLAT_STD", "6"))
# Толщина штриха в долях кегля, с которой надпись считается полужирной
# (замер: DIN Bold Condensed — 0.15, Regular — 0.08).
BOLD_STEM = float(os.environ.get("PAINT_BOLD_STEM", "0.12"))
# Наклон меряется у надписи, вытянутой не меньше чем во столько раз,
# и учитывается от стольких градусов.
ANGLE_ELONG = float(os.environ.get("PAINT_ANGLE_ELONG", "3.0"))
ANGLE_MIN = float(os.environ.get("PAINT_ANGLE_MIN", "4.0"))
# Угол меряется только у рамки, которая НЕ вытянута по горизонтали больше
# чем во столько раз: горизонтальная строка — длинная и низкая, и её ось
# всегда около нуля; дуга и повёрнутая подпись дают рамку ближе к квадрату
# или вертикальную. Вытянутость маски у дуги — от `ANGLE_ELONG_ARC`.
ANGLE_BOX_WIDE = float(os.environ.get("PAINT_ANGLE_BOX_WIDE", "4.0"))
ANGLE_ELONG_ARC = float(os.environ.get("PAINT_ANGLE_ELONG_ARC", "1.8"))
# Радиус окружности дуги — не больше стольких хорд: дальше это прямая.
ARC_MAX_R = float(os.environ.get("PAINT_ARC_MAX_R", "3.0"))
# Радиус inpaint и расширение маски, точек снимка.
INPAINT_R = 3
# Участки блока (`_areas`): фон отличается больше этого (по каналу) или
# разрыв между строками больше стольких шагов строки.
AREA_BG_DIFF = float(os.environ.get("PAINT_AREA_BG_DIFF", "30"))
AREA_GAP = float(os.environ.get("PAINT_AREA_GAP", "1.6"))
# Какая доля точек маски обязана лежать в областях высотой с букву.
LETTER_SHARE_MIN = float(os.environ.get("PAINT_LETTER_SHARE_MIN", "0.5"))
# Буква не мельче этой доли рамки строки (у шума «буквы» — крошки).
LETTER_MIN_SHARE = float(os.environ.get("PAINT_LETTER_MIN_SHARE", "0.08"))
# И не мельче стольких точек: у шума «буква» — пара точек.
LETTER_MIN_PX = 5
# Остаток фона вокруг букв (75-й процентиль отличия от своей медианы),
# выше которого это текстура/шум, а не фон надписи.
TEXTURE_MAX = float(os.environ.get("PAINT_TEXTURE_MAX", "28"))
# Доля рамки под маской, выше которой это не буквы, а пёстрый фон.
MASK_MAX_COVER = float(os.environ.get("PAINT_MASK_MAX_COVER", "0.45"))
# Насколько (по самому далёкому каналу) точка буквы может отличаться от цвета
# краски надписи.
INK_NEAR = float(os.environ.get("PAINT_INK_NEAR", "90"))
MASK_GROW = 2

_DESC = set("gjpqyQ,;()[]{}/|рудзфщцДЦЩ")
# Строчные с выносным вверх (латиница, кириллица, греческий): по ним кегль
# меряется высотой заглавной, а не высотой строчной.
_TALL = set("bdfhklt\u0431\u0434\u0444\u03b2\u03b4\u03b8\u03bb\u03be")


def available() -> bool:
    return np is not None and cv2 is not None


def _odd(v: float, lo: int = 3, hi: int = 41) -> int:
    k = int(max(lo, min(hi, round(v))))
    return k if k % 2 else k + 1


def _bands(mask, min_h: int = 3) -> list:
    """[(верх, низ)] строк по проекции маски на вертикаль."""
    h, w = mask.shape
    prof = mask.sum(axis=1) > max(1, int(0.01 * w))
    out, top = [], None
    gap = 0
    for y in range(h):
        if prof[y]:
            if top is None:
                top = y
            gap = 0
            last = y
        elif top is not None:
            gap += 1
            if gap > 1:
                if last - top + 1 >= min_h:
                    out.append((top, last))
                top = None
    if top is not None and last - top + 1 >= min_h:
        out.append((top, last))
    return out


def _stem(mask) -> float:
    """Медиана длины горизонтальных серий маски — толщина вертикального
    штриха, в точках снимка."""
    runs = []
    for row in mask[:: max(1, mask.shape[0] // 40)]:
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        runs.extend((ends - starts).tolist())
    runs = [r for r in runs if r > 0]
    if len(runs) < 6:
        return 0.0
    runs.sort()
    return float(runs[len(runs) // 2])


def measure(rgb, src: str = "", rows: int = 1, line_h: float = 0.0, inner=None) -> dict:
    """Измерить надпись на вырезке `rgb` (H×W×3, uint8). Ответ:
    {mask, bg (цвет), ink (цвет), flat, bands, em (кегль в точках снимка),
    pitch, bold, angle (градусы, против часовой; 0 — горизонталь), elong,
    found (есть ли буквы)}."""
    h, w = rgb.shape[:2]
    lh = float(line_h or (h / max(1, rows)))
    k = _odd(0.6 * lh)
    bg_local = cv2.medianBlur(rgb, k) if min(h, w) > k else rgb.copy()
    diff = np.abs(rgb.astype(np.int16) - bg_local.astype(np.int16)).max(axis=2)
    mask = diff > INK_DIFF
    # Буквы надписи — ОДНОГО цвета: ядро самых далёких от фона точек даёт
    # цвет краски, и маска сужается до точек, близких к нему. Без этого в
    # маску шёл край цветной плашки и кольца схемы (там точка отличается
    # от размытого фона, но цветом она — плашка), и буквы сливались с ним.
    # Только у однострочной подписи: в многострочном блоке цветов законно
    # несколько (заголовок, полужирное начало пункта, рукописный подзаголовок),
    # и фильтр по одному цвету оставлял бы недостёртые буквы.
    if mask.sum() >= 8 and rows <= 1:
        far0 = diff[mask]
        core0 = rgb[mask][far0 >= np.percentile(far0, 66)].astype(np.int16)
        ink0 = np.median(core0, axis=0)
        near = np.abs(rgb.astype(np.int16) - ink0).max(axis=2) <= INK_NEAR
        mask = mask & (near | (diff > 2.5 * INK_DIFF) & (np.abs(rgb.astype(np.int16) - ink0).max(axis=2) <= 2 * INK_NEAR))
    # Мелочь (шум, сжатие JPEG) — не буквы; область, касающаяся края
    # вырезки, — чужая надпись (вырезка взята с полем вокруг своей).
    n, lab, st, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 3
    if n > 1:
        L_, T_ = st[1:, cv2.CC_STAT_LEFT], st[1:, cv2.CC_STAT_TOP]
        R_, B_ = L_ + st[1:, cv2.CC_STAT_WIDTH], T_ + st[1:, cv2.CC_STAT_HEIGHT]
        edge = (L_ <= 0) | (T_ <= 0) | (R_ >= w) | (B_ >= h)
        small = st[1:, cv2.CC_STAT_AREA] < 0.5 * mask.sum()
        if inner is not None:
            # Своя буква у края вырезки (надпись у края картинки, выносной
            # у поля) — не чужая: чужая та, чья середина ВНЕ рамки надписи.
            ix0, iy0, ix1, iy1 = inner
            cxs, cys = (L_ + R_) / 2.0, (T_ + B_) / 2.0
            outside = (cxs < ix0) | (cxs > ix1) | (cys < iy0) | (cys > iy1)
            edge = edge & outside
        keep[1:] &= ~(edge & small)
    mask = keep[lab]
    cover = float(mask.mean()) if mask.size else 0.0
    flat_line = rows > 1 or w >= 2.5 * h
    # База — высота строки у прямой надписи, меньшая сторона у дуги и
    # повёрнутой подписи (рамка близка к квадрату).
    base = (h / rows) if rows > 1 else (h if w >= 2.5 * h else min(h, w))
    # Буквы — связные области маски не крупнее строки (кольцо схемы, стрелка,
    # край плашки — крупнее). Их размер — мера кегля, не зависящая от того,
    # прямая строка или дуга.
    lim = 1.2 * base if flat_line else 0.6 * base
    comps = []
    for k in range(1, n):
        if not keep[k]:
            continue
        cw, ch = st[k, cv2.CC_STAT_WIDTH], st[k, cv2.CC_STAT_HEIGHT]
        if max(cw, ch) <= lim and st[k, cv2.CC_STAT_AREA] >= 6:
            comps.append((st[k, cv2.CC_STAT_LEFT] + cw / 2.0, st[k, cv2.CC_STAT_TOP] + ch / 2.0,
                          max(cw, ch), ch, st[k, cv2.CC_STAT_AREA]))
    letter = None
    if comps:
        # Высота буквы — верхний дециль: точки, запятые и дефисы мелкие,
        # а соседние буквы полужирного сливаются в одну область той же
        # высоты (ширина у неё — слово, поэтому у прямой строки берётся
        # ВЫСОТА области, у дуги — больший размер: буква там повёрнута).
        sz = sorted((c_[3] if flat_line else c_[2]) for c_ in comps)
        letter = float(sz[int(round(0.9 * (len(sz) - 1)))])
    # Надпись или пёстрый фон: буквы занимают малую часть рамки
    # (`MASK_MAX_COVER`), они не крошки относительно рамки
    # (`LETTER_MIN_SHARE`), и большая часть точек маски лежит в областях
    # размером с букву (`LETTER_SHARE_MIN`).
    lettery = 0.0
    if letter and mask.sum():
        tot = float(sum(c_[4] for c_ in comps)) + float(
            sum(st[k, cv2.CC_STAT_AREA] for k in range(1, n) if keep[k]) - sum(c_[4] for c_ in comps))
        ok_a = sum(c_[4] for c_ in comps
                   if 0.3 * letter <= (c_[3] if flat_line else c_[2]) <= 1.6 * letter)
        lettery = float(ok_a) / max(1.0, tot)
    # Фон вокруг букв гладкий относительно своей медианы (даже у фотографии);
    # у шума и мелкой текстуры остаток огромный — там надписи не разобрать,
    # и стирать «буквы» значило бы портить картинку.
    rest = diff[~mask] if (~mask).any() else diff.reshape(-1)
    texture = float(np.percentile(rest, 75)) if rest.size else 0.0
    out = {"mask": mask, "cover": round(cover, 3), "lettery": round(lettery, 2),
           "texture": round(texture, 1),
           "found": bool(mask.sum() >= 8 and letter and cover <= MASK_MAX_COVER
                         and texture <= TEXTURE_MAX
                         and letter >= max(LETTER_MIN_PX, LETTER_MIN_SHARE * base)
                         and lettery >= LETTER_SHARE_MIN)}
    bgp = bg_local[~mask] if (~mask).any() else bg_local.reshape(-1, 3)
    bg = np.median(bgp.reshape(-1, 3), axis=0)
    out["bg"] = tuple(int(v) for v in bg)
    out["flat"] = bool(float(bgp.reshape(-1, 3).astype(np.float32).std(axis=0).max()) <= FLAT_STD)
    if not out["found"]:
        out.update(ink=(0, 0, 0) if bg.mean() > 127 else (255, 255, 255), bands=[],
                   em=lh * 0.8, pitch=lh, bold=False, angle=0.0, elong=1.0)
        return out
    px = rgb[mask].astype(np.int16)
    loc = bg_local[mask].astype(np.int16)
    far = np.abs(px - loc).max(axis=1)
    order = np.argsort(-far)
    core = px[order[:max(1, len(order) // 3)]]
    out["ink"] = tuple(int(v) for v in np.median(core, axis=0))
    # Наклон — только у однострочной надписи, рамка которой не вытянута вширь.
    ys, xs = np.nonzero(mask)
    angle, elong = 0.0, 1.0
    if rows <= 1 and len(xs) >= 20 and w < ANGLE_BOX_WIDE * h:
        cx, cy = xs.mean(), ys.mean()
        cov = np.cov(np.vstack([xs - cx, ys - cy]))
        ev, evec = np.linalg.eigh(cov)
        l2, l1 = max(ev[0], 1e-6), max(ev[1], 1e-6)
        elong = math.sqrt(l1 / l2)
        vx, vy = evec[0, 1], evec[1, 1]
        a_ = math.degrees(math.atan2(-vy, vx))           # вверх — плюс
        if a_ > 90:
            a_ -= 180
        if a_ < -90:
            a_ += 180
        # Рамка у дуги и повёрнутой подписи — ближе к квадрату, и
        # вытянутость маски у короткого слова невелика: порог низкий.
        if elong >= ANGLE_ELONG_ARC and abs(a_) >= ANGLE_MIN:
            angle = a_
    arc = _arc_of(comps, letter, h) if rows <= 1 else None
    if arc:
        out["arc"] = arc
        angle = 0.0
    out["angle"], out["elong"] = round(angle, 1), round(elong, 2)
    bands = [] if (angle or arc) else _bands(mask)
    out["bands"] = bands
    # Кегль — по высоте буквы: заглавная и выносные строчных ≈ 0.72–0.76
    # кегля, строчные без выносных — 0.53 (по исходному тексту надписи).
    # Полосы строк для кегля не годятся: у строчных с одной «y» полоса
    # теряет выносной, и кегль выходил на четверть мельче (жирный — обычным).
    letters = [ch for ch in (src or "") if ch.isalpha()]
    tall = (not letters) or any(ch.isupper() or ch in _TALL for ch in (src or "")) \
        or any(ch.isdigit() for ch in (src or ""))
    em = letter / (0.73 if tall else 0.53)
    if flat_line:
        # Кегль не больше высоты строки рамки детектора.
        em = min(em, 1.05 * lh)
    out["em"] = float(em)
    if len(bands) >= 2:
        tops = [a for a, _b in bands]
        out["pitch"] = float(np.median(np.diff(tops)))
    else:
        out["pitch"] = float(max(em * 1.2, lh if rows > 1 else em * 1.2))
    out["bold"] = bool(em > 0 and _stem(mask) / em >= BOLD_STEM)
    out["areas"] = _areas(bands, mask, bg_local, out["pitch"])
    return out


def _areas(bands: list, mask, bg_local, pitch: float) -> list:
    """Участки многострочного блока: строки подряд на ОДНОМ фоне и без
    большого разрыва. Детектор собирает в блок столбец схемы целиком — белую
    ячейку, розовую шапку и следующую ячейку под стрелкой, — и перевод,
    уложенный одним абзацем, шёл бы поперёк рамок. [[первая, последняя]]
    по номерам полос; один участок — блок цельный."""
    if len(bands) < 2:
        return [[0, max(0, len(bands) - 1)]]
    cols = []
    for a, b in bands:
        rows = bg_local[a:b + 1]
        free = ~mask[a:b + 1]
        px = rows[free] if free.any() else rows.reshape(-1, 3)
        cols.append(np.median(px.reshape(-1, 3), axis=0))
    out, start = [], 0
    for k in range(1, len(bands)):
        gap = bands[k][0] - bands[k - 1][1]
        diff = float(np.abs(cols[k].astype(int) - cols[k - 1].astype(int)).max())
        if diff > AREA_BG_DIFF or gap > AREA_GAP * max(pitch, 1.0):
            out.append([start, k - 1])
            start = k
    out.append([start, len(bands) - 1])
    return out


def split_text(text: str, weights: list) -> list:
    """Перевод — по участкам: сперва по его собственным переносам строк
    (пункт, заголовок ячейки), иначе по словам; доля каждого участка — его
    вес (доля краски оригинала). Ни одно слово не теряется."""
    n = len(weights)
    if n <= 1:
        return [text]
    tot = float(sum(weights)) or 1.0
    paras = [p.strip() for p in (text or "").split("\n") if p.strip()]
    units, sep = (paras, "\n") if len(paras) >= n else ((text or "").split(), " ")
    lens = [len(u) + 1 for u in units]
    total_t = float(sum(lens)) or 1.0
    out = [[] for _ in range(n)]
    j, done, cum = 0, 0.0, weights[0] / tot * total_t
    left = len(units)
    for u, ln in zip(units, lens):
        # Участку — хотя бы одна единица, пока единиц хватает на оставшиеся.
        while j < n - 1 and (done + ln / 2.0 > cum and out[j]) and left > (n - 1 - j) - 1:
            j += 1
            cum += weights[j] / tot * total_t
        out[j].append(u)
        done += ln
        left -= 1
    return [sep.join(p) for p in out]


def _arc_of(comps: list, letter: float, H: int) -> "dict | None":
    """Дуга, по которой стоят буквы однострочной надписи: окружность через
    середины букв (наименьшие квадраты). Дуга — если букв не меньше четырёх,
    они лежат на окружности (разброс меньше пятой доли буквы), а радиус не
    больше `ARC_MAX_R` хорд (иначе это прямая — у неё своё правило, угол).
    Координаты — точки вырезки, ось y вверх; `up` — куда смотрит верх букв:
    +1 наружу (надпись над центром), −1 к центру (надпись под ним)."""
    if len(comps) < 4:
        return None
    pts = np.array([[c_[0], H - c_[1]] for c_ in comps], dtype=np.float64)
    x, y = pts[:, 0], pts[:, 1]
    A = np.column_stack([x, y, np.ones_like(x)])
    bb = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, bb, rcond=None)
    except Exception:
        return None
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r = math.sqrt(max(1e-9, sol[2] + cx * cx + cy * cy))
    res = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) - r
    chord = float(np.hypot(x.max() - x.min(), y.max() - y.min()))
    if chord <= 0 or float(np.sqrt((res ** 2).mean())) > 0.2 * letter:
        return None
    if r > ARC_MAX_R * chord or r < 0.4 * chord:
        return None
    # Прямая строка под углом: середины букв гуляют из-за формы букв, и
    # окружность через них подбирается всегда. Дуга — только если прямая
    # описывает середины заметно хуже окружности.
    mx, my = x.mean(), y.mean()
    cov = np.cov(np.vstack([x - mx, y - my]))
    ev = np.linalg.eigvalsh(cov)
    line_rms = math.sqrt(max(0.0, float(ev[0])))
    circ_rms = float(np.sqrt((res ** 2).mean()))
    if line_rms < 0.15 * letter or line_rms < 2.0 * circ_rms:
        return None
    th = np.arctan2(y - cy, x - cx)
    order = np.argsort(x)
    t = np.unwrap(th[order])
    t0, t1 = float(t[0]), float(t[-1])
    tm = (t0 + t1) / 2.0
    up = 1 if math.sin(tm) > 0 else -1
    # Наклон соседних букв: дуга, у которой середины букв почти на прямой
    # (стрелка дуги меньше трети буквы), — это прямая строка, не дуга.
    sag = r * (1 - math.cos(abs(t1 - t0) / 2.0))
    if sag < 0.33 * letter:
        return None
    return {"cx": float(cx), "cy": float(cy), "r": float(r), "t0": t0, "t1": t1, "up": up}


def erase(rgb, m: dict):
    """(стёртая вырезка, альфа-маска стирания): ровный фон — заливка цветом
    фона, неровный — inpaint по расширенной маске букв. Альфа — расширенная
    маска с мягким краем: вне её картинка не трогается."""
    mask = m["mask"].astype(np.uint8) * 255
    grow = cv2.dilate(mask, np.ones((2 * MASK_GROW + 1, 2 * MASK_GROW + 1), np.uint8))
    if m.get("flat"):
        out = rgb.copy()
        out[grow > 0] = np.array(m["bg"], dtype=np.uint8)
    else:
        out = cv2.inpaint(np.ascontiguousarray(rgb), grow, INPAINT_R, cv2.INPAINT_TELEA)
    alpha = cv2.GaussianBlur(grow, (3, 3), 0)
    return out, alpha


# Ниже этой доли кегля надпись не ужимается никогда.
FIT_HARD_FLOOR = 0.3


def fit_lines(text: str, width: float, height: float, em: float, pitch: float, measure_w,
              split_word=None, min_share: float = 0.45, rows_min: int = 1) -> tuple:
    """(кегль, шаг, [строки]) — самый крупный кегль ≤ `em`, при котором перевод
    целиком ложится в рамку `width`×`height` строками с шагом `pitch`×доля.
    `measure_w(text, size)` — ширина строки; `split_word(word, room, size)` —
    перенос (часть, остаток) или None. Не влезло и на полу — пол с тем, что
    есть: решение вызывающего, а не тихая потеря."""
    # Перенос строки в переводе — ПРИНУДИТЕЛЬНЫЙ: заголовок блока и пункты
    # списка («• …») стоят каждый с новой строки, как в оригинале.
    words = []
    for k, part in enumerate((text or "").split("\n")):
        if k and words and words[-1] != "\n":
            words.append("\n")
        words.extend(part.split())
    while words and words[-1] == "\n":
        words.pop()
    if not words:
        return em, pitch, []

    def lay(f):
        size = em * f
        step = pitch * f
        n_max = max(rows_min, int((height + 0.25 * step) // max(step, 1e-6))) if height > 0 else 10 ** 6
        lines, cur = [], ""
        ws = list(words)
        while ws:
            w = ws[0]
            if w == "\n":
                ws.pop(0)
                if cur:
                    lines.append(cur)
                    cur = ""
                continue
            probe = (cur + " " + w) if cur else w
            if measure_w(probe, size) <= width:
                cur = probe
                ws.pop(0)
                continue
            if split_word is not None:
                room = width - (measure_w(cur + " ", size) if cur else 0.0)
                sp = split_word(w, room, size)
                if sp:
                    lines.append((cur + " " + sp[0]) if cur else sp[0])
                    ws[0] = sp[1]
                    cur = ""
                    continue
            if not cur:
                return None                 # слово шире строки
            lines.append(cur)
            cur = ""
        if cur:
            lines.append(cur)
        if len(lines) > n_max:
            return None
        return size, step, lines

    got = lay(1.0)
    if got:
        return got
    lo, hi, best = min_share, 1.0, None
    b = lay(lo)
    f_ = lo
    while b is None and f_ > FIT_HARD_FLOOR:
        # Не влезло на полу — ещё мельче, но в рамку: строка, ушедшая ниже
        # рамки, ложится на рисунок.
        f_ *= 0.92
        b = lay(f_)
    if b is not None and f_ < lo:
        return b
    if b is None:
        # Не влезает и так: пол, строками сколько выйдет (вызывающий
        # видит, что строк больше, чем места, и называет это числом).
        size, step = em * lo, pitch * lo
        lines, cur = [], ""
        for w in words:
            if w == "\n":
                if cur:
                    lines.append(cur)
                cur = ""
                continue
            probe = (cur + " " + w) if cur else w
            if cur and measure_w(probe, size) > width:
                lines.append(cur)
                cur = w
            else:
                cur = probe
        if cur:
            lines.append(cur)
        return size, step, lines
    best = b
    for _ in range(9):
        mid = (lo + hi) / 2.0
        g = lay(mid)
        if g:
            lo, best = mid, g
        else:
            hi = mid
    return best
