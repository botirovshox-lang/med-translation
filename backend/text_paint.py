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
import re
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
# Х8: доля области у края вырезки внутри рамки надписи, с которой она своя.
OWN_SHARE = float(os.environ.get("PAINT_OWN_SHARE", "0.35"))
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
ARC_MAX_R = float(os.environ.get("PAINT_ARC_MAX_R", "5.0"))
# Дуга по ПОВОРОТУ букв (Т22): цепочка середин букв, подогнанная параболой в
# системе её главной оси, поворачивается от первой буквы к последней не
# меньше чем на `ARC_TURN_MIN` градусов, а парабола описывает середины заметно
# лучше прямой (`ARC_QUAD_RATIO`). Буквы дуги — области размером в
# `ARC_SIZE_BAND` медианной (обломок кромки кольца, 1-пиксельные полоски
# в подгонку не идут), сторона не меньше `ARC_MIN_SIDE` медианной.
ARC_TURN_MIN = float(os.environ.get("PAINT_ARC_TURN_MIN", "12"))
ARC_QUAD_RATIO = float(os.environ.get("PAINT_ARC_QUAD_RATIO", "0.7"))
ARC_SIZE_BAND = (0.55, 1.6)
ARC_MIN_SIDE = 0.3
ARC_OLD = os.environ.get("PAINT_ARC_OLD", "0") == "1"      # 1 — прежняя проверка дуги
# Радиус inpaint и расширение маски, точек снимка.
INPAINT_R = 3
WEAK_INK = float(os.environ.get("PAINT_WEAK_INK", "0.35"))
WEAK_REACH = int(os.environ.get("PAINT_WEAK_REACH", "4"))
HALO_FAR = float(os.environ.get("PAINT_HALO_FAR", "0.5"))
HALO_MIN = float(os.environ.get("PAINT_HALO_MIN", "4"))
HALO_K = float(os.environ.get("PAINT_HALO_K", "3"))
HALO_REACH = float(os.environ.get("PAINT_HALO_REACH", "0.25"))
# Х5: насколько местный тон бумаги вправе отойти от цвета фона (по каналу).
FLAT_LOCAL_MAX = float(os.environ.get("PAINT_FLAT_LOCAL_MAX", "18"))
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
# Область краски крупнее буквы во столько раз (по большей стороне) — графика
# рядом с надписью (край кольца, стрелка), в замер пестроты фона не идёт.
TEXTURE_BIG_SHARE = float(os.environ.get("PAINT_TEXTURE_BIG", "2.5"))   # 0 — выключить
TEXTURE_BIG_MAX = 0.35
TEXTURE_BIG_FLAT = 18.0      # разброс цвета области (по каналу) — не больше: заливка
# Доля рамки под маской, выше которой это не буквы, а пёстрый фон.
MASK_MAX_COVER = float(os.environ.get("PAINT_MASK_MAX_COVER", "0.45"))
# Насколько (по самому далёкому каналу) точка буквы может отличаться от цвета
# краски надписи.
INK_NEAR = float(os.environ.get("PAINT_INK_NEAR", "90"))
MASK_GROW = 2
# Т31: у прямой строки буква — по высоте области, а не по её большей стороне.
LETTER_BY_HEIGHT = os.environ.get("PAINT_LETTER_BY_HEIGHT", "1") != "0"
# Т29: внутренность толстых букв достраивается в маску стирания.
ERASE_FILL = os.environ.get("PAINT_ERASE_FILL", "1") != "0"
ERASE_FILL_HULL = 0.25           # на какую долю строки от краски ищется внутренность буквы

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


def measure(rgb, src: str = "", rows: int = 1, line_h: float = 0.0, inner=None,
            plate=None) -> dict:
    """Измерить надпись на вырезке `rgb` (H×W×3, uint8). Ответ:
    {mask, bg (цвет), ink (цвет), flat, bands, em (кегль в точках снимка),
    pitch, bold, angle (градусы, против часовой; 0 — горизонталь), elong,
    found (есть ли буквы)}. `plate` — (область, цвет) плашки, на которой
    стоят буквы (`_plate_of`): фон тогда — её цвет, а не размытая вырезка."""
    h, w = rgb.shape[:2]
    lh = float(line_h or (h / max(1, rows)))
    k = _odd(0.6 * lh)
    if plate is not None:
        region, pcol = plate
        bg_local = rgb.copy()
        bg_local[region] = np.array(pcol, dtype=np.uint8)
    else:
        region = None
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
            # Х8: своя и та, что заметной частью лежит в рамке (буквица,
            # выходящая выше строк блока): её продолжение за краем вырезки
            # стирает `continuation_mask`, а чужая строка в рамку не заходит.
            a0, b0 = max(0, int(iy0)), min(h, int(math.ceil(iy1)))
            c0, d0 = max(0, int(ix0)), min(w, int(math.ceil(ix1)))
            if b0 > a0 and d0 > c0:
                in_cnt = np.bincount(lab[a0:b0, c0:d0].ravel(), minlength=n)[1:]
                outside &= in_cnt < OWN_SHARE * st[1:, cv2.CC_STAT_AREA]
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
        # У прямой строки мера буквы — ВЫСОТА области (Т31): соседние жирные
        # буквы на мелком кропе слипаются в «слово» шириной больше строки,
        # и по ширине оно отбрасывалось, а доля «буквенной» краски падала
        # ниже порога («GOALS OF CARE» обложки: 0.35 при кропе 133 пикселя и
        # 0.73 при 132 — найдено или нет, решал один пиксель).
        # Высота — мера буквы, но линейка или подчёркивание во всю рамку
        # буквой не становится: ширина не больше 8 строк, высота — не тонкая
        # черта.
        if ((ch if (flat_line and LETTER_BY_HEIGHT and cw <= 8 * lim and ch >= 0.25 * lim)
             else max(cw, ch)) <= lim
                and st[k, cv2.CC_STAT_AREA] >= 6):
            comps.append((st[k, cv2.CC_STAT_LEFT] + cw / 2.0, st[k, cv2.CC_STAT_TOP] + ch / 2.0,
                          max(cw, ch), ch, st[k, cv2.CC_STAT_AREA], k))
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
    # Из замера вынуты КРУПНЫЕ области краски, не похожие на буквы (край
    # кольца схемы, стрелка, плашка рядом — с каймой): они не фон под
    # буквами, а соседняя графика, и «STRENGTHENING» под краем розового
    # кольца отбраковывалось как пёстрое (проект 14, стр. 12). Мелкие
    # крупинки шума фотографии остаются в замере — их и ловит порог.
    nonfg = ~mask
    if letter and TEXTURE_BIG_SHARE > 0:
        raw = (diff > INK_DIFF) & ~mask
        n2, lab2, st2, _c2 = cv2.connectedComponentsWithStats(raw.astype(np.uint8), 8)
        big = np.zeros(n2, dtype=bool)
        if n2 > 1:
            dims = np.maximum(st2[1:, cv2.CC_STAT_WIDTH], st2[1:, cv2.CC_STAT_HEIGHT])
            L2, T2 = st2[1:, cv2.CC_STAT_LEFT], st2[1:, cv2.CC_STAT_TOP]
            R2, B2 = L2 + st2[1:, cv2.CC_STAT_WIDTH], T2 + st2[1:, cv2.CC_STAT_HEIGHT]
            # Только ВХОДЯЩАЯ в вырезку снаружи графика — выходит за рамку
            # самой надписи (`inner`; без неё — подходит к краю вырезки):
            # предмет на фотографии ВНУТРИ рамки надписи — это фон под ней,
            # и вынуть его из замера значило бы закрасить фотографию.
            if inner is not None:
                ix0, iy0, ix1, iy1 = inner
                touch = (L2 < ix0) | (T2 < iy0) | (R2 > ix1) | (B2 > iy1)
            else:
                e_ = max(2, int(0.1 * min(h, w)))
                touch = (L2 <= e_) | (T2 <= e_) | (R2 >= w - e_) | (B2 >= h - e_)
            big[1:] = (dims >= TEXTURE_BIG_SHARE * letter) & touch
            # И только РОВНОГО цвета (кольцо, плашка, стрелка — заливка):
            # предмет фотографии, даже выходящий за рамку, пёстрый внутри.
            # Разброс — по ВНУТРЕННОСТИ области (кайма сглаживания — смесь
            # с фоном, её разброс велик и у ровной заливки).
            # В область попадает и бумага рядом (её отличие от размытого фона
            # велико у края заливки) — меряется только сама краска области.
            paper_ = np.median(rgb.reshape(-1, 3), axis=0).astype(np.int16)
            for i_ in np.nonzero(big)[0]:
                core_ = cv2.erode((lab2 == i_).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
                sel_ = core_ if core_.any() else (lab2 == i_)
                px_ = rgb[sel_].astype(np.int16)
                px_ = px_[np.abs(px_ - paper_).max(axis=1) > INK_DIFF]
                if len(px_) and float(px_.astype(np.float32).std(axis=0).max()) > TEXTURE_BIG_FLAT:
                    big[i_] = False
        if big.any():
            k_ = _odd(max(3.0, 0.3 * letter))
            grown = cv2.dilate(big[lab2].astype(np.uint8), np.ones((k_, k_), np.uint8)).astype(bool)
            # Вынуть можно не больше `TEXTURE_BIG_MAX` фона: иначе судили бы
            # по клочку, а не по фону.
            if (nonfg & grown).sum() <= TEXTURE_BIG_MAX * nonfg.sum():
                nonfg = nonfg & ~grown
    rest = diff[nonfg] if nonfg.any() else diff.reshape(-1)
    texture = float(np.percentile(rest, 75)) if rest.size else 0.0
    out = {"mask": mask, "cover": round(cover, 3), "lettery": round(lettery, 2),
           "texture": round(texture, 1),
           "found": bool(mask.sum() >= 8 and letter and cover <= MASK_MAX_COVER
                         and texture <= TEXTURE_MAX
                         and letter >= max(LETTER_MIN_PX, LETTER_MIN_SHARE * base)
                         and lettery >= LETTER_SHARE_MIN)}
    bgp = bg_local[~mask] if (~mask).any() else bg_local.reshape(-1, 3)
    if region is not None:
        # Фон букв на плашке — сама плашка, а не бумага вокруг неё.
        bgp = rgb[region & ~mask] if (region & ~mask).any() else bgp
    bg = np.median(bgp.reshape(-1, 3), axis=0)
    out["bg"] = tuple(int(v) for v in bg)
    out["flat"] = bool(float(bgp.reshape(-1, 3).astype(np.float32).std(axis=0).max()) <= FLAT_STD)
    if not out["found"] and plate is None and rows <= 1:
        # Светлые буквы на ПЛАШКЕ уже окна размытия (лента дуги, полоса
        # заголовка): размытый фон — смесь плашки и бумаги, и «краской»
        # оказывается сама плашка, а буквы — её дырками. Тогда плашка и есть
        # фон: буквы — точки внутри неё, отличные от её цвета
        # (проект 14, стр. 10: «MEDITERRANEAN DIET» белым по синей дуге).
        pl = _plate_of(rgb, lab, st, keep, lim, n)
        if pl is not None:
            alt = measure(rgb, src, rows, line_h, inner, plate=pl)
            # Буквы на плашке — КОНТРАСТНЫ ей (белое по синему); крапины
            # на ровном участке фотографии (небо, кожа) — нет.
            if alt.get("found") and max(abs(int(a_) - int(b_)) for a_, b_ in
                                        zip(alt.get("ink") or (0, 0, 0), pl[1])) >= PLATE_CONTRAST:
                ext = _plate_extend(rgb, pl, alt)
                if ext is not None:
                    alt2 = measure(rgb, src, rows, line_h, inner, plate=ext)
                    if alt2.get("found") and int(alt2["mask"].sum()) >= int(alt["mask"].sum()):
                        alt = alt2
                return alt
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
    letter_em = letter
    if (arc or angle) and not ARC_OLD:
        # Повёрнутая буква (дуга, подпись под углом): высота по ограничивающему
        # прямоугольнику завышена (Т22) — у букв под 30° на десятки процентов,
        # кегль выходил крупнее настоящего, а отношение толщины штриха к нему —
        # меньше порога «полужирный» (проект 14, стр. 12: «STANDING» — 0.118 при
        # настоящих 0.132). Мера, не зависящая от поворота, — длинная сторона
        # наименьшего повёрнутого прямоугольника области.
        lr = _letter_rot(lab, st, comps)
        if lr:
            letter_em = min(letter, lr)
    em = letter_em / (0.73 if tall else 0.53)
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
    out["rooms"] = _area_rooms(rgb, mask, bands, out["areas"])
    out["erase_mask"] = _erase_mask(rgb, mask, np.array(out["ink"], dtype=np.int16),
                                    np.array(out["bg"], dtype=np.int16), lh)
    return out


# Т30. Место перевода — по плашке, а не по рамке блока. Симптом: «ЦЕЛИ
# ЛЕЧЕНИЯ» в зелёном круге (стр. 4) выходило за круг: белые буквы на белом.
# Причина: ширину и середину перевода брали у рамки БЛОКА — а она по самой
# широкой строке («Prevent complications»), и верхней строке круга, где хорда
# уже, это не годилось. Правило: у каждого участка меряется «комната» —
# отрезок строки, на котором фон остаётся цветом плашки (отличие по каналу
# не больше `ROOM_BG_DIFF`), от краски наружу до края плашки; край не найден
# (фон идёт до края вырезки) — стороны нет. Комната только СУЖАЕТ место.
ROOM_BG_DIFF = float(os.environ.get("PAINT_ROOM_BG_DIFF", "30"))
ROOM_ROWS = (0.15, 0.85)         # где в полосе строки меряется комната: у верха и у низа


def _area_rooms(rgb, mask, bands: list, areas: list) -> list:
    """[(левый край | None, правый край | None)] по участкам, в точках вырезки."""
    if not bands or not areas or rgb.ndim != 3:
        return [(None, None)] * max(1, len(areas))
    h, w = mask.shape
    near = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    out = []
    for a0, a1 in areas:
        lo, hi = None, None
        for bi in range(a0, a1 + 1):
            top, bot = bands[bi]
            cols = np.nonzero(mask[top:bot + 1].any(axis=0))[0]
            if not len(cols):
                continue
            ix0, ix1 = int(cols.min()), int(cols.max())
            for fr in ROOM_ROWS:
                y = int(round(top + fr * (bot - top)))
                ys = slice(max(0, y - 1), min(h, y + 2))
                px = rgb[ys].astype(np.float32)
                free = ~near[ys]
                cnt = free.sum(axis=0)
                col = np.where(cnt[:, None] > 0,
                               (px * free[:, :, None]).sum(axis=0) / np.maximum(cnt, 1)[:, None],
                               np.nan)
                inside = col[ix0:ix1 + 1]
                inside = inside[~np.isnan(inside[:, 0])]
                if not len(inside):
                    continue
                ref = np.median(inside, axis=0)
                bad = np.nan_to_num(np.abs(col - ref).max(axis=1), nan=0.0) > ROOM_BG_DIFF
                xl = None
                for x in range(ix0 - 1, -1, -1):
                    if bad[x]:
                        xl = x + 1
                        break
                xr = None
                for x in range(ix1 + 1, w):
                    if bad[x]:
                        xr = x
                        break
                if xl is not None:
                    lo = xl if lo is None else max(lo, xl)
                if xr is not None:
                    hi = xr if hi is None else min(hi, xr)
        out.append((lo, hi))
    return out


def _erase_mask(rgb, mask, ink, bg, lh: float):
    """Маска СТИРАНИЯ: маска букв плюс их внутренность. Симптом: на крупных
    жирных буквах («GOALS OF CARE» в зелёном круге, стр. 4) в переводе
    оставались белые «облака» — нестёртая середина букв оригинала. Причина:
    фон — медиана окна 0.6 строки, а штрих жирной заглавной с ним сравним
    (8 пикселей при окне 23): внутри буквы медиана равна цвету буквы, отличие
    нулевое, маска — один контур, и inpaint замазывал контур, оставляя
    белую середину. Правило (Т29): к маске добавляются пиксели цвета краски
    (ближе к краске, чем к общему фону), лежащие около маски — не дальше
    `ERASE_FILL_HULL` строки. Только для стирания: замеры идут по `mask`."""
    if not ERASE_FILL or not mask.any():
        return mask
    near = np.abs(rgb.astype(np.int16) - ink).max(axis=2)
    far = np.abs(rgb.astype(np.int16) - bg).max(axis=2)
    k = _odd(ERASE_FILL_HULL * max(lh, 4.0), 3, 41)
    hull = cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    add = hull & (near <= INK_NEAR) & (near <= far) & ~mask
    if not add.any():
        return mask
    # Достраивается только ВНУТРЕННОСТЬ букв: часть добавки, касающаяся края
    # вырезки или длиннее полутора строк, — это кант, рамка плашки, кольцо
    # того же цвета рядом с буквами, и стирать её нельзя (Т27/Т28 бережут
    # ровно эту графику).
    n, _lab, st, _c = cv2.connectedComponentsWithStats(add.astype(np.uint8), 8)
    H, W = add.shape[:2]
    ok = np.zeros(n, dtype=bool)
    for i in range(1, n):
        x, y, w_, h_ = (int(v) for v in st[i, :4])
        if x > 0 and y > 0 and x + w_ < W and y + h_ < H and max(w_, h_) <= 1.5 * max(lh, 4.0):
            ok[i] = True
    return mask | ok[_lab]


# Плашка под буквами: крупная ровная область маски, занимающая не меньше
# этой доли вырезки, с разбросом цвета не больше `PLATE_FLAT`.
PLATE_MIN_SHARE = 0.12
PLATE_FLAT = 18.0
PLATE_CONTRAST = 90             # краска букв против плашки, по каналу из 255


def _plate_of(rgb, lab, st, keep, lim: float, n: int):
    """(область, цвет) ровной плашки, в которой буквы — дырки, либо None.
    Плашка — самая крупная область маски БОЛЬШЕ буквы (`lim`); область —
    она же, закрытая по размеру буквы (дырки-буквы залиты) и поджатая
    на кайму сглаживания; цвет — медиана её сердцевины."""
    h, w = rgb.shape[:2]
    best, area = 0, 0
    for k_ in range(1, n):
        if not keep[k_]:
            continue
        if max(st[k_, cv2.CC_STAT_WIDTH], st[k_, cv2.CC_STAT_HEIGHT]) <= lim:
            continue
        if st[k_, cv2.CC_STAT_AREA] > area:
            best, area = k_, int(st[k_, cv2.CC_STAT_AREA])
    if not best or area < PLATE_MIN_SHARE * h * w:
        return None
    comp = (lab == best).astype(np.uint8)
    core = cv2.erode(comp, np.ones((3, 3), np.uint8), iterations=2).astype(bool)
    px = rgb[core] if core.any() else rgb[comp.astype(bool)]
    if not len(px) or float(px.astype(np.float32).std(axis=0).max()) > PLATE_FLAT:
        return None
    kk = _odd(0.6 * lim)
    closed = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, np.ones((kk, kk), np.uint8))
    region = cv2.erode(closed, np.ones((3, 3), np.uint8), iterations=2).astype(bool)
    if not region.any():
        return None
    col = tuple(int(v) for v in np.median(px.reshape(-1, 3), axis=0))
    return region, col


# Край плашки у первой буквы (Т23). Симптом: «MEDITERRANEAN DIET» на синей дуге
# (проект 14, стр. 10) — перед «З» перевода белая черта: левая ножка «M»
# осталась нестёртой. Причина: плашка (`_plate_of`) — самая крупная область
# маски «отличается от размытого фона», а лента шире окна размытия только в
# своей узкой части; к левому краю она шире, середина ленты там совпадает с
# размытым фоном, и регион плашки начинался правее первой буквы. Правило: после
# первого замера регион пополняется точками ЦВЕТА плашки (допуск `PLATE_TOL`),
# замкнутыми по размеру буквы, но только в полосе в `PLATE_EXT_REACH` буквы
# от найденных букв — дальше лежит чужая бумага (белая линия под лентой).
PLATE_TOL = 60
PLATE_EXT_REACH = 1.0


def _plate_extend(rgb, plate, alt):
    """(регион, цвет) с пополнением у букв либо None, если пополнять нечем."""
    region, col = plate
    letter = max(3.0, 0.73 * float(alt.get("em") or 0.0))
    cls = (np.abs(rgb.astype(np.int16) - np.array(col, dtype=np.int16)).max(axis=2)
           <= PLATE_TOL).astype(np.uint8)
    kk = _odd(0.5 * letter)
    closed = cv2.morphologyEx(cls, cv2.MORPH_CLOSE, np.ones((kk, kk), np.uint8)).astype(bool)
    rk = _odd(PLATE_EXT_REACH * letter)
    near = cv2.dilate(alt["mask"].astype(np.uint8), np.ones((rk, rk), np.uint8)).astype(bool)
    add = closed & near & ~region
    if not add.any():
        return None
    return region | add, col


def _letter_rot(lab, st, comps) -> float:
    """Высота буквы (длинная сторона повёрнутого прямоугольника), верхний
    квартиль по областям-буквам (обломок буквы и слипшаяся пара длиннее —
    верхний дециль брал бы их); 0 — измерить нечем."""
    sizes = [c_[2] for c_ in comps]
    if len(comps) < 3:
        return 0.0
    med = float(np.median(sizes))
    out = []
    for c_ in comps:
        if not (ARC_SIZE_BAND[0] * med <= c_[2] <= ARC_SIZE_BAND[1] * med) or len(c_) < 6:
            continue
        k = c_[5]
        l_, t_ = int(st[k, cv2.CC_STAT_LEFT]), int(st[k, cv2.CC_STAT_TOP])
        w_, h_ = int(st[k, cv2.CC_STAT_WIDTH]), int(st[k, cv2.CC_STAT_HEIGHT])
        sub = (lab[t_:t_ + h_, l_:l_ + w_] == k)
        ys, xs = np.nonzero(sub)
        if len(xs) < 6:
            continue
        (_cx, _cy), (rw, rh), _a = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        out.append(max(rw, rh))
    if len(out) < 3:
        return 0.0
    out.sort()
    return float(out[int(round(0.75 * (len(out) - 1)))])


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


def ink_lines(rgb, rows: int = 1, line_h: float = 0.0) -> list:
    """Строки надписи по ПИКСЕЛЯМ, без детектора: полосы маски букв по
    вертикали, в полосе — куски, разделённые пробелом шире 1.2 высоты строки
    (две ячейки схемы рядом — два куска). [[x0, y0, x1, y1]] в точках вырезки.
    Детектор строк — полминуты на страницу у единственного воркера; здесь —
    доли секунды, а большего пересверке со слоем не нужно: что в блоке текст,
    уже известно."""
    if np is None or cv2 is None:
        return []
    try:
        m = measure(rgb, "", max(1, rows), line_h)
    except Exception:
        return []
    mask = m.get("mask")
    if mask is None or not mask.any():
        return []
    out = []
    for a, b in _bands(mask):
        band_h = b - a + 1
        cols = mask[a:b + 1].any(axis=0)
        xs = np.nonzero(cols)[0]
        if not len(xs):
            continue
        gap_max = max(3, int(1.2 * band_h))
        start = prev = int(xs[0])
        for x in xs[1:]:
            x = int(x)
            if x - prev > gap_max:
                out.append([start, a, prev + 1, b + 1])
                start = x
            prev = x
        out.append([start, a, prev + 1, b + 1])
    return out


# Х14. Строка другого размера в конце блока — свой участок. Чтение склеило
# две строки заголовка статьи (Times, полосы 50 и 40 точек) и строку
# авторов (мелкий гротеск, 27): перевод один на блок и укладывался одним
# кеглем — авторы размером заголовка, и всё сжималось до 0.78. Правило:
# последняя настоящая полоса (не обрывок выносных: не ниже `SPLIT_FRAG`
# высоты самой высокой) ниже медианы предыдущих в `SPLIT_SIZE` раз и больше —
# отдельный участок, ЕСЛИ в переводе нашёлся хвост, перенесённый из
# оригинала дословно (имена не переводятся), и он однозначен (`tail_anchor`).
# Делить по доле длины нельзя: разрез посреди имени хуже общего кегля.
# Порог по высоте — только для последней строки: буквица, индексы и
# прописные дают рамки в 1.3–1.5 раза разные посреди обычного абзаца.
SPLIT_SIZE = float(os.environ.get("PAINT_SPLIT_SIZE", "1.5"))
SPLIT_FRAG = float(os.environ.get("PAINT_SPLIT_FRAG", "0.3"))
TAIL_MIN = int(os.environ.get("PAINT_TAIL_MIN", "4"))
TAIL_FOREIGN = float(os.environ.get("PAINT_TAIL_FOREIGN", "0.25"))


def _tok_key(t: str) -> str:
    return "".join(ch for ch in t if ch.isalnum()).lower()


def tail_anchor(text: str, src: str) -> "tuple | None":
    """(позиция в `text`, позиция в `src`), с которых начинается хвост,
    перенесённый из `src` дословно (Х14), или None. Хвост: не меньше `TAIL_MIN` слов, чужих
    (нет в оригинале) — не больше `TAIL_FOREIGN` доли, первое слово — из
    оригинала, слово перед ним — нет; в оригинале слова хвоста идут в том
    же порядке и заканчивают его."""
    src_spans = [(mm.start(), mm.group()) for mm in re.finditer(r"\S+", src or "")]
    src_toks = [_tok_key(t) for _, t in src_spans]
    known = {t for t in src_toks if t}
    spans = [(mm.start(), mm.group()) for mm in re.finditer(r"\S+", text or "")]
    keys = [_tok_key(t) for _, t in spans]
    n = len(keys)
    best = None
    foreign = 0
    for i in range(n - 1, -1, -1):
        if keys[i] and keys[i] not in known:
            foreign += 1
        size_ = n - i
        if (size_ >= TAIL_MIN and keys[i] in known and foreign <= TAIL_FOREIGN * size_
                and (i == 0 or (keys[i - 1] and keys[i - 1] not in known))):
            best = i
    if best is None or best == 0:
        return None
    # Хвост из чисел и сокращений («Table 1 … 2020 2021») — не имена:
    # слов с буквами в нём не меньше половины.
    if sum(1 for k_ in keys[best:] if any(ch.isalpha() for ch in k_)) * 2 < n - best:
        return None
    tail = [k_ for k_ in keys[best:] if k_ in known]
    # Порядок в оригинале — подпоследовательность его хвоста.
    j, hits, first = len(src_toks) - 1, 0, None
    for k_ in reversed(tail):
        while j >= 0 and src_toks[j] != k_:
            j -= 1
        if j < 0:
            return None
        hits += 1
        first = j
        j -= 1
    if hits != len(tail) or first is None or first == 0:
        return None
    return spans[best][0], src_spans[first][0]


# Х16. Хвост по НОМЕРАМ, когда имена транслитерированы. Дословного хвоста
# нет у переводов на китайский, казахский, арабский: «Kana Okano1» стал
# «Кана Окано1», «冈野加奈1», «كانا أوكانو1». Номера аффилиаций при
# транслитерации не меняются, и по ним видно, где начинается список
# авторов. Номер — 1–2 цифры ВПЛОТНУЮ за буквой (надстрочные ¹²³,
# арабско-индийские и полноширинные цифры приводятся к обычным; «1,2» —
# два номера); годы, ссылки «[1]», «Table 1», «COVID-19» сюда не попадают.
# В оригинале: номеров от конца не меньше `NUM_MIN`, значения малые
# (наибольший не больше их числа), после последнего — только знаки,
# каждое имя между номерами — со словом с ЗАГЛАВНОЙ (сноски на строчных
# словах — не имена); разрез — назад от первого номера через слова
# с заглавной (и частицы de, van, von…), не больше `NAME_WORDS_MAX`, слово
# перед ними — со строчной. В переводе: последние номера совпадают по
# значению и порядку, после них — только знаки; разрез — у письма
# с пробелами на столько же слов назад, у письма без пробелов — на явной
# границе (пробел, «，», «、», «：») не дальше `NAME_CHARS_MAX` знаков перед
# первым номером. Любое сомнение — None: блок не делится. Работает только
# под физическим признаком (`size_split`: последняя строка мельче).
NUM_MIN = int(os.environ.get("PAINT_NUM_MIN", "3"))
NAME_WORDS_MAX = int(os.environ.get("PAINT_NAME_WORDS_MAX", "4"))
NAME_CHARS_MAX = int(os.environ.get("PAINT_NAME_CHARS_MAX", "12"))
_NAME_PARTICLES = {"de", "da", "di", "du", "del", "della", "der", "den", "van", "von", "la", "le",
                   "bin", "ibn", "al", "el", "dos", "das", "ten", "ter"}
_NUM_RE = re.compile(r"(?<=[^\W\d_])(\d{1,2}(?:[,،，、]\d{1,2})*)(?!\d)")
_SEP_CHARS = " \t\n\u3000，、：；:;,"


def _ascii_digits(s: str) -> str:
    import unicodedata
    out = []
    for ch in s or "":
        if ch.isdigit() and not ("0" <= ch <= "9"):
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except (TypeError, ValueError):
                pass
        out.append(ch)
    return "".join(out)


def _tail_nums(s: str) -> "list | None":
    """[(позиция начала номера, [значения])] хвоста номеров или None.
    Длина строки при замене цифр не меняется — позиции верны и в исходной."""
    t = _ascii_digits(s)
    ms = list(_NUM_RE.finditer(t))
    if not ms:
        return None
    after = t[ms[-1].end():]
    if any(ch.isalnum() for ch in after):
        return None                             # после последнего номера — текст
    return [(m_.start(), [int(v) for v in re.split(r"[,،，、]", m_.group(1))]) for m_ in ms]


def _name_words_back(s: str, end: int) -> "tuple | None":
    """(слов имени, позиция начала имени) — назад от `end` через слова
    с заглавной и частицы; перед именем обязано стоять слово со строчной
    (иначе это не конец фразы) — None."""
    words = [(m_.start(), m_.group()) for m_ in re.finditer(r"\S+", s[:end])]
    k_, i = 0, len(words) - 1
    while i >= 0 and k_ <= NAME_WORDS_MAX:
        core = "".join(ch for ch in words[i][1] if ch.isalpha())
        if not core:
            return None
        if core[:1].isupper() or core.lower() in _NAME_PARTICLES:
            k_ += 1
            i -= 1
            continue
        break
    if k_ == 0 or k_ > NAME_WORDS_MAX or i < 0:
        return None
    return k_, words[i + 1][0]


def _author_run(s: str, groups: list) -> "list | None":
    """Последняя СПЛОШНАЯ цепочка «имя+номер» с конца: между соседними
    номерами — короткий кусок с заглавным словом, слово перед номером —
    от двух букв. Номер в заголовке («IL6», «CO2») цепочку не продолжает."""
    run = [groups[-1]]
    for g_prev, g in zip(reversed(groups[:-1]), reversed(groups)):
        frag = _ascii_digits(s[g_prev[0]:g[0]]).lstrip("0123456789,،，、")
        ws = frag.split()
        if not ws or len(ws) > NAME_WORDS_MAX + 2 or not any(w[:1].isupper() for w in ws):
            break
        run.insert(0, g_prev)
    return run


def _affil_order(vals: list) -> bool:
    """Номера аффилиаций нумеруются по первому появлению: 1, потом не
    больше уже встреченного + 1 («1 1 2 1 3»); «2 2 2» — не авторы."""
    top = 0
    for v in vals:
        if v > top + 1:
            return False
        top = max(top, v)
    return vals[0] == 1 and len(set(vals)) >= 2


def tail_by_numbers(text: str, src: str) -> "tuple | None":
    """(позиция в `text`, позиция в `src`) начала списка авторов по номерам
    аффилиаций (Х16) или None."""
    ns, nt = _tail_nums(src), _tail_nums(text)
    if not ns or not nt:
        return None
    ns = _author_run(src, ns)
    vals = [v for _, vs in ns for v in vs]
    if len(vals) < NUM_MIN or max(vals) > len(vals) or not _affil_order(vals):
        return None
    groups = len(ns)
    if len(nt) < groups or [v for _, vs in nt[-groups:] for v in vs] != vals:
        return None
    # Оригинал: перед каждым номером — слово от двух букв, в куске — заглавное.
    prev = 0
    for pos, _vs in ns:
        frag = src[prev:pos]
        w_ = re.search(r"(\w+)$", _ascii_digits(frag))
        if not w_ or sum(ch.isalpha() for ch in w_.group(1)) < 2:
            return None
        if not any(w[:1].isupper() for w in frag.split()):
            return None
        prev = pos
    first_s = ns[0][0]
    nb = _name_words_back(src, first_s + 1)
    if nb is None:
        return None
    k_, cut_s = nb
    first_t = nt[-groups][0]
    left = text[:first_t]
    tail_word = re.search(r"\S+$", left + text[first_t:first_t + 1])
    tw = tail_word.group() if tail_word else ""
    spaced = bool(tw) and all(not _no_space_char(ch) for ch in tw)
    if spaced:
        # Имя в переводе — своим обходом, и слов в нём столько же: слово
        # заголовка с заглавной («Harvard») в переводе обычно строчное,
        # и несовпадение счёта — повод не делить.
        letters = [ch for ch in left if ch.isalpha()]
        cased = sum(ch.isupper() or ch.islower() for ch in letters) * 2 > len(letters)
        if cased:
            nb_t = _name_words_back(text, first_t + 1)
            if nb_t is None or nb_t[0] != k_:
                return None
            cut_t = nb_t[1]
        else:
            # Письмо без регистра (арабица, иврит, грузинский): заглавных
            # нет, имя — столько же слов, сколько в оригинале.
            wt = [(m_.start(), m_.group()) for m_ in re.finditer(r"\S+", text[:first_t + 1])]
            if len(wt) <= k_:
                return None
            cut_t = wt[len(wt) - k_][0]
    else:
        j = len(left)
        while j > 0 and left[j - 1] not in _SEP_CHARS:
            j -= 1
        if j == 0 or len(left) - j > NAME_CHARS_MAX:
            return None
        cut_t = j
    if not text[:cut_t].strip() or not src[:cut_s].strip():
        return None
    return cut_t, cut_s


def _no_space_char(ch: str) -> bool:
    """Буква письма без пробелов между словами (иероглифы, кана, тайский…)."""
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF
            or 0x0E00 <= o <= 0x0EFF or 0x1000 <= o <= 0x109F or 0x1780 <= o <= 0x17FF)


def size_split(bands: list, text: str, src: str):
    """(участки, куски перевода, куски оригинала, высоты полос участков)
    для строки другого размера в конце блока (Х14) или None."""
    if len(bands) < 2:
        return None
    hs = [b - a + 1 for a, b in bands]
    big = max(hs)
    real = [i for i, h_ in enumerate(hs) if h_ >= SPLIT_FRAG * big]
    if len(real) < 2:
        return None
    last = real[-1]
    prev = [hs[i] for i in real[:-1]]
    if hs[last] * SPLIT_SIZE > float(np.median(prev)):
        return None
    cut = tail_anchor(text, src) or tail_by_numbers(text, src)
    if cut is None:
        return None
    head, tail = text[:cut[0]].rstrip(), text[cut[0]:].strip()
    s_head, s_tail = src[:cut[1]].rstrip(), src[cut[1]:].strip()
    if not head or not tail or not s_head:
        return None
    return ([[0, last - 1], [last, len(bands) - 1]], [head, tail], [s_head, s_tail],
            [float(np.median(prev)), float(hs[last])])


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


def _chain_turn(P):
    """(поворот цепочки в градусах, rms прямой, rms параболы, число точек) —
    парабола по серединам букв в системе главной оси цепочки с отсевом
    выбросов (2.5 σ); None — точек меньше четырёх."""
    if len(P) < 4:
        return None
    m = P.mean(axis=0)
    Q = P - m
    _w, V = np.linalg.eigh(np.cov(Q.T))
    d = V[:, 1]
    u = Q @ d
    v = Q @ np.array([-d[1], d[0]])
    keep = np.ones(len(u), dtype=bool)
    for _ in range(3):
        a2 = np.polyfit(u[keep], v[keep], 2)
        r2 = v - np.polyval(a2, u)
        sg = max(float(np.sqrt((r2[keep] ** 2).mean())), 1e-6)
        k2 = np.abs(r2) <= 2.5 * sg + 1e-9
        if k2.sum() < 4 or (k2 == keep).all():
            break
        keep = k2
    a1 = np.polyfit(u[keep], v[keep], 1)
    a2 = np.polyfit(u[keep], v[keep], 2)
    r1 = v[keep] - np.polyval(a1, u[keep])
    r2 = v[keep] - np.polyval(a2, u[keep])

    def ang(uu):
        return math.degrees(math.atan(2.0 * a2[0] * uu + a2[1]))
    turn = abs(ang(float(u[keep].max())) - ang(float(u[keep].min())))
    return (turn, float(np.sqrt((r1 ** 2).mean())), float(np.sqrt((r2 ** 2).mean())),
            int(keep.sum()))


def _arc_of(comps: list, letter: float, H: int) -> "dict | None":
    """Дуга, по которой стоят буквы однострочной надписи (Т22): буквы дуги —
    области размером около медианной (`ARC_SIZE_BAND`), цепочка их середин
    поворачивается не меньше чем на `ARC_TURN_MIN` градусов и описывается
    параболой заметно лучше прямой (`ARC_QUAD_RATIO`); окружность — по тем же
    буквам с отсевом выбросов. Прежняя проверка (прямая «не хуже дуги», если
    она в пределах 0.15 буквы; стрелка дуги не меньше трети буквы) отвергала
    пологую дугу, у которой буквы повёрнуты на 24° (проект 14, стр. 10), а один
    обломок кромки кольца ломал подгонку у любой дуги (стр. 4, 10). Возвращает
    те же поля, что прежде: cx, cy, r, t0, t1, up. `PAINT_ARC_OLD=1` — прежнее."""
    if ARC_OLD:
        return _arc_of_old(comps, letter, H)
    if len(comps) < 4:
        return None
    med = float(np.median([c_[2] for c_ in comps]))
    cs = [c_ for c_ in comps if ARC_SIZE_BAND[0] * med <= c_[2] <= ARC_SIZE_BAND[1] * med
          and min(c_[2], c_[3]) >= ARC_MIN_SIDE * med]
    if len(cs) < 4:
        return None
    P = np.array([[c_[0], H - c_[1]] for c_ in cs], dtype=np.float64)
    try:
        ct = _chain_turn(P)
    except Exception:
        return None
    if ct is None or ct[0] < ARC_TURN_MIN or ct[2] > ARC_QUAD_RATIO * ct[1]:
        return None
    idx = np.arange(len(P))
    cx = cy = r = 0.0
    for _ in range(3):
        x, y = P[idx, 0], P[idx, 1]
        try:
            sol, *_ = np.linalg.lstsq(np.column_stack([x, y, np.ones_like(x)]), x * x + y * y, rcond=None)
        except Exception:
            return None
        cx, cy = sol[0] / 2.0, sol[1] / 2.0
        r = math.sqrt(max(1e-9, sol[2] + cx * cx + cy * cy))
        res_all = np.hypot(P[:, 0] - cx, P[:, 1] - cy) - r
        sg = float(np.sqrt((res_all[idx] ** 2).mean()))
        new = np.nonzero(np.abs(res_all) <= max(2.5 * sg, 1e-6))[0]
        if len(new) < 4 or len(new) == len(idx):
            break
        idx = new
    x, y = P[idx, 0], P[idx, 1]
    res = np.hypot(x - cx, y - cy) - r
    chord = float(np.hypot(x.max() - x.min(), y.max() - y.min()))
    if chord <= 0 or float(np.sqrt((res ** 2).mean())) > 0.25 * med:
        return None
    if r > ARC_MAX_R * chord or r < 0.4 * chord:
        return None
    th = np.arctan2(y - cy, x - cx)
    order = np.argsort(x)
    t = np.unwrap(th[order])
    t0, t1 = float(t[0]), float(t[-1])
    up = 1 if math.sin((t0 + t1) / 2.0) > 0 else -1
    return {"cx": float(cx), "cy": float(cy), "r": float(r), "t0": t0, "t1": t1, "up": up}


def _arc_of_old(comps: list, letter: float, H: int) -> "dict | None":
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
    """(стёртая вырезка, альфа-маска стирания): ровный фон — заливка местным
    тоном бумаги, бумага с узором — модель «освещение × узор» (Ф6), прочий
    неровный — inpaint по расширенной маске букв. Альфа — расширенная маска
    с мягким краем снаружи: вне её картинка не трогается."""
    mask = m.get("erase_mask", m["mask"]).astype(np.uint8) * 255
    grow = cv2.dilate(mask, np.ones((2 * MASK_GROW + 1, 2 * MASK_GROW + 1), np.uint8))
    lh = float(m.get("pitch") or 0) or 1.25 * float(m.get("em") or 0) or 20.0
    if not m.get("flat"):
        per = _paper_periodic(rgb, grow > 0, lh, float(m.get("em") or 0))
        if per is not None:
            m["eraseHow"] = "periodic"
            alpha = cv2.GaussianBlur(cv2.dilate(grow, np.ones((3, 3), np.uint8)), (3, 3), 0)
            return per, alpha
    if WEAK_INK > 0:
        # Х5а. Слабая краска у букв — волосяные штрихи, засечки, сглаживание:
        # отличие от фона ниже порога маски, и после стирания они оставались
        # серым контуром слова. Стирается то, что отличается от фона больше
        # `WEAK_INK` порога и лежит не дальше `WEAK_REACH` точек от маски.
        # У бумаги с узором не нужно (и вредно — захватило бы линии клетки):
        # там стёртое восстанавливает модель выше.
        k_ = _odd(0.6 * lh, 3, 61)
        if min(rgb.shape[:2]) > k_:
            bgl = cv2.medianBlur(np.ascontiguousarray(rgb), k_)
            weak = np.abs(rgb.astype(np.int16) - bgl.astype(np.int16)).max(axis=2) > WEAK_INK * INK_DIFF
            reach = cv2.dilate(mask, np.ones((2 * WEAK_REACH + 1, 2 * WEAK_REACH + 1), np.uint8)) > 0
            grow = np.where(weak & reach, 255, grow).astype(np.uint8)
            # Бледный ореол (Х5а): порог — от шума САМОЙ бумаги, а не доля
            # порога букв. Бумага — точки дальше `HALO_FAR` строки от маски;
            # её уровень и разброс (MAD); краска в сторону цвета букв темнее
            # (светлее) уровня больше max(`HALO_MIN`, `HALO_K` разбросов)
            # и не дальше `HALO_REACH` строки от маски — стирается. На шумном
            # фото порог поднимается сам; бледные края завитка буквицы
            # (на 6–12 единиц темнее бумаги) иначе оставались серым пятном.
            g = rgb.astype(np.float32).mean(axis=2)
            kf = _odd(HALO_FAR * lh, 3, 151)
            far = cv2.dilate(grow, np.ones((kf, kf), np.uint8)) == 0
            if far.sum() >= 50:
                lvl = float(np.median(g[far]))
                noise = 1.4826 * float(np.median(np.abs(g[far] - lvl)))
                thr = max(HALO_MIN, HALO_K * noise)
                inkg = float(np.mean(m.get("ink") or (0, 0, 0)))
                halo = (lvl - g > thr) if inkg < lvl else (g - lvl > thr)
                kr = _odd(2 * HALO_REACH * lh, 3, 61)
                near_ = cv2.dilate(grow, np.ones((kr, kr), np.uint8)) > 0
                grow = np.where(halo & near_, 255, grow).astype(np.uint8)
    if m.get("flat"):
        # Х5. «Ровный» фон заливается МЕСТНЫМ тоном бумаги (среднее известных
        # точек окрестности), а не одним цветом: у скана бумага зернистая
        # и пятнистая, и один цвет оставлял след в форме стёртых букв.
        # Где местный тон далёк от цвета фона (край плашки) — цвет фона.
        out = rgb.copy()
        bgc = np.array(m["bg"], dtype=np.float32)
        known = (grow == 0).astype(np.float32)
        kk = _odd(1.2 * lh, 9, 151)
        den = cv2.blur(known, (kk, kk))[..., None]
        loc = cv2.blur(rgb.astype(np.float32) * known[..., None], (kk, kk)) / np.maximum(den, 1e-3)
        far = (np.abs(loc - bgc).max(axis=2, keepdims=True) > FLAT_LOCAL_MAX) | (den < 0.05)
        fill = np.where(far, bgc, loc)
        sel = grow > 0
        out[sel] = np.clip(fill[sel], 0, 255).astype(np.uint8)
    else:
        out = cv2.inpaint(np.ascontiguousarray(rgb), grow, INPAINT_R, cv2.INPAINT_TELEA)
    out = _tone_match(out, rgb, grow > 0)
    # Х5. Мягкий край альфы — СНАРУЖИ маски, на нетронутых точках: размытие
    # по самой маске смешивало крайние пиксели стёртого с оригиналом, и по
    # контуру букв оставался серый ободок (след заголовка Чехова рядом
    # с узким переводом). Вне маски стёртая вырезка равна оригиналу.
    alpha = cv2.GaussianBlur(cv2.dilate(grow, np.ones((3, 3), np.uint8)), (3, 3), 0)
    return out, alpha


# Ф6. Бумага с повторяющимся узором — клетка, линейка, точечная сетка, бланк
# с линиями — стирается ПО МОДЕЛИ, а не размыванием. Симптом (проект 89,
# конспект в клетку): после `cv2.inpaint` по полосе букв линии клетки
# пропадали (60 % горизонтальных внутри стёртого), на пересечениях оставались
# серые пятна, а светлые и тёмные разводы повторяли контуры прежних слов.
# Причина: Telea — диффузия от края дыры; тонкую линию, идущую ВДОЛЬ дыры
# (линейка под строкой), он усредняет с бумагой, а тёмную точку края тянет
# внутрь. Правило: бумага = освещение × узор. Освещение — серое «закрытие»
# (снимает тонкие тёмные линии и буквы) и размытие по известным точкам;
# узор — отношение снимка к освещению; период узора — пик автокорреляции
# профиля по каждой оси. Точка дыры — медиана узора в ближайших точках с той
# же фазой (x ± i·Px, y ± j·Py), умноженная на освещение. Модель принимается,
# только если на кольце известных точек вокруг дыры она предсказывает бумагу
# заметно лучше ровного тона (`PERIOD_GAIN`): ложный период (таблица, ткань)
# этот экзамен не сдаёт, и стирание остаётся прежним.
# Х5. Тон стёртого — по бумаге вокруг. Восстановление тянет тон от самого
# края дыры, и стёртые буквы выходили на несколько единиц светлее (или темнее)
# бумаги: на увеличении силуэт заголовка читался. Каждая область дыры
# сдвигается на разницу средних: кольцо нетронутой бумаги (от 2 до 6 точек
# снаружи) против самой области; сдвиг больше `TONE_MAX` не делается — там
# дыра на границе разных фонов.
TONE_MAX = float(os.environ.get("PAINT_TONE_MAX", "12"))


def _tone_match(out, rgb, hole):
    if np is None or cv2 is None or not hole.any():
        return out
    h8 = hole.astype(np.uint8)
    n, lab = cv2.connectedComponents(cv2.dilate(h8, np.ones((3, 3), np.uint8)), connectivity=8)
    if n <= 1:
        return out
    near = cv2.dilate(h8, np.ones((5, 5), np.uint8)) > 0
    far = cv2.dilate(h8, np.ones((13, 13), np.uint8)) > 0
    ring = far & ~near
    # Номер области у кольца — от ближайшей области (кольцо касается её).
    lab_r = cv2.dilate(lab.astype(np.float32), np.ones((13, 13), np.uint8)).astype(np.int32)
    o = out.astype(np.float32)
    res = out.copy()
    for c in range(o.shape[2]):
        sum_h = np.bincount(lab[hole], weights=o[..., c][hole], minlength=n)
        cnt_h = np.bincount(lab[hole], minlength=n)
        sum_r = np.bincount(lab_r[ring], weights=rgb[..., c][ring].astype(np.float32), minlength=n)
        cnt_r = np.bincount(lab_r[ring], minlength=n)
        with np.errstate(all="ignore"):
            d = np.where((cnt_h > 0) & (cnt_r >= 8), sum_r / np.maximum(cnt_r, 1) - sum_h / np.maximum(cnt_h, 1), 0.0)
        d[np.abs(d) > TONE_MAX] = 0.0
        d[0] = 0.0
        ch = res[..., c].astype(np.float32)
        ch[hole] += d[lab[hole]]
        res[..., c] = np.clip(ch, 0, 255).astype(np.uint8)
    return res


PERIOD_PEAK = float(os.environ.get("PAINT_PERIOD_PEAK", "0.25"))
PERIOD_GAIN = float(os.environ.get("PAINT_PERIOD_GAIN", "0.75"))
PERIOD_K = 6                     # сколько точек той же фазы берётся в медиану
PERIOD_R = 4                     # дальше скольких периодов не ищем
PERIOD_DIV_MAX = int(os.environ.get("PAINT_PERIOD_DIV_MAX", "3"))  # делители периода-кандидата (Ф6а)
PERIOD_DIV_PROM = float(os.environ.get("PAINT_PERIOD_DIV_PROM", "0.04"))  # высота пика делителя над впадиной
PERIOD_MISS = 0.05               # доля точек дыры без соседей той же фазы, ещё терпимая
PERIODIC_ERASE = os.environ.get("PAINT_PERIODIC_ERASE", "1") != "0"
# Вырезка больше стольких мегапикселей стирается прежним способом: модель
# держит несколько копий вырезки в float32, а воркер один (инвариант 1).
PERIODIC_MAX_MPX = float(os.environ.get("PAINT_PERIODIC_MAX_MPX", "2.5"))


def _period_of(prof, lo: int, hi: int):
    """Период профиля (`prof` — среднее «темноты» по строкам/столбцам):
    пик автокорреляции в [lo, hi] не слабее `PERIOD_PEAK` нулевого сдвига."""
    c = _period_cands(prof, lo, hi)
    return c[0] if c else None


def _period_cands(prof, lo: int, hi: int) -> list:
    """Ф6а. Кандидаты периода: самый сильный пик автокорреляции и его
    ДЕЛИТЕЛИ (P/2, P/3), если на них стоит свой пик над впадиной вокруг.
    Симптом (конспект в клетку, вырезка до края листа): строки текста идут
    через клетку, их следы ложатся на тот же профиль, и сильнейший пик —
    вторая гармоника (54 вместо 27); с двойным периодом половина линий
    клетки «не в фазе», модель не сдавала экзамен, и стирание падало
    на Telea — клетки размазывались. Какой кандидат верен, решает экзамен
    (`_paper_periodic`), а не высота пика."""
    p = prof - prof.mean()
    n = len(p)
    hi = min(hi, n // 2)
    if hi <= lo + 1:
        return []
    ac = np.correlate(p, p, "full")[n - 1:]
    if ac[0] <= 1e-9:
        return []
    P = lo + int(np.argmax(ac[lo:hi]))
    if ac[P] < PERIOD_PEAK * ac[0]:
        return []
    # Пик на краю окна — это не период, а медленный наклон профиля.
    if P <= lo or P >= hi - 1:
        return []
    out = [P]
    for k in range(2, PERIOD_DIV_MAX + 1):
        d0 = P / k
        if d0 < max(lo, 3):
            break
        a, b = max(1, int(d0) - 1), min(n - 2, int(d0) + 2)
        if a >= b:
            continue
        d = a + int(np.argmax(ac[a:b + 1]))
        # Свой пик, а не склон: выше впадины вокруг себя (знак не важен —
        # следы строк сдвигают весь профиль, и пик клетки бывает ниже нуля).
        r = max(2, d // 4)
        trough = float(ac[max(1, d - r):min(n, d + r + 1)].min())
        if (ac[d] >= ac[d - 1] and ac[d] >= ac[d + 1]
                and ac[d] - trough >= PERIOD_DIV_PROM * ac[0] and d not in out):
            out.append(d)
    return out


def _phase_median(q, known, ys, xs, Px, Py):
    """Медиана узора в ближайших известных точках той же фазы для точек
    (ys, xs). (значения H×3 | NaN, сколько точек нашлось)."""
    H, W = known.shape
    offs = [(dx, dy) for dy in range(-PERIOD_R, PERIOD_R + 1)
            for dx in range(-PERIOD_R, PERIOD_R + 1)
            if (dx, dy) != (0, 0) and (Px or dx == 0) and (Py or dy == 0)]
    offs.sort(key=lambda t: (abs(t[0]) * (Px or 0) + abs(t[1]) * (Py or 0), t[1], t[0]))
    n = len(ys)
    vals = np.full((PERIOD_K, n, q.shape[2]), np.nan, dtype=np.float32)
    cnt = np.zeros(n, dtype=np.int32)
    for dx, dy in offs:
        yy = ys + dy * (Py or 0)
        xx = xs + dx * (Px or 0)
        ok = (yy >= 0) & (yy < H) & (xx >= 0) & (xx < W) & (cnt < PERIOD_K)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            continue
        idx = idx[known[yy[idx], xx[idx]]]
        if not len(idx):
            continue
        vals[cnt[idx], idx] = q[yy[idx], xx[idx]]
        cnt[idx] += 1
        if (cnt >= PERIOD_K).all():
            break
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(vals, axis=0)
    return med, cnt


def _paper_periodic(rgb, hole, lh: float, em: float):
    """Стёртая вырезка по модели «освещение × узор» (Ф6) или None —
    узора нет, модель не сдала экзамен, мерить нечем."""
    if not PERIODIC_ERASE or np is None or cv2 is None or not hole.any():
        return None
    H, W = hole.shape
    if H * W > PERIODIC_MAX_MPX * 1e6:
        return None                     # память воркера: большое фото — прежнее стирание
    lh = max(8.0, lh or 0.0)
    em = em or 0.8 * lh
    f = rgb.astype(np.float32)
    known = ~hole
    if known.sum() < 0.3 * H * W:
        return None
    kc = _odd(max(5.0, 0.16 * em), 5, 21)
    clo = cv2.morphologyEx(f, cv2.MORPH_CLOSE, np.ones((kc, kc), np.uint8))
    w = known.astype(np.float32)
    kb = _odd(1.4 * lh, 15, 151)
    clo *= w[..., None]
    den = np.maximum(cv2.blur(w, (kb, kb)), 1e-3)[..., None]
    ill = np.maximum(cv2.blur(clo, (kb, kb)) / den, 1.0)
    del clo, den
    q = f / ill
    dark = (1.0 - q.mean(axis=2)) * w
    lo, hi = max(5, int(0.25 * lh)), int(3.0 * lh) + 1
    cx = _period_cands(dark.sum(0) / np.maximum(w.sum(0), 1), lo, hi) or [None]
    cy = _period_cands(dark.sum(1) / np.maximum(w.sum(1), 1), lo, hi) or [None]
    if cx == [None] and cy == [None]:
        return None
    # Экзамен: кольцо известных точек вокруг дыры предсказывается узором
    # (без самой точки) и ровным тоном; узор обязан ошибаться заметно меньше.
    # Из кандидатов периода (Ф6а) берётся тот, что ошибается меньше всех.
    kr = _odd(0.5 * lh, 3, 61)
    ring = (cv2.dilate(hole.astype(np.uint8), np.ones((kr, kr), np.uint8)) > 0) & known
    ry, rx = np.nonzero(ring)
    if len(ry) < 50:
        return None
    step = max(1, len(ry) // 6000)
    ry, rx = ry[::step], rx[::step]
    qg = q.mean(axis=2)
    flat = float(np.median(qg[known]))
    passed = []
    for Px in cx:
        for Py in cy:
            if not Px and not Py:
                continue
            pred, c = _phase_median(q, known, ry, rx, Px, Py)
            okp = c > 0
            if okp.sum() < 30:
                continue
            truth = qg[ry[okp], rx[okp]]
            e_per = float(np.mean(np.abs(pred[okp].mean(axis=1) - truth)))
            e_flat = float(np.mean(np.abs(flat - truth)))
            if e_per < PERIOD_GAIN * e_flat:
                passed.append((e_per, Px, Py))
    if not passed:
        return None
    # Сдавший экзамен с наименьшей ошибкой, у которого точки дыры находят
    # соседей той же фазы: двойной период на кольце точнее, но через полосу
    # строк до известной бумаги не дотягивается.
    hy, hx = np.nonzero(hole)
    med = cnt = None
    for _, Px, Py in sorted(passed, key=lambda t: t[0]):
        med, cnt = _phase_median(q, known, hy, hx, Px, Py)
        if (cnt > 0).mean() >= 1.0 - PERIOD_MISS:
            break
    out = rgb.copy()
    got = cnt > 0
    val = np.clip(med[got] * ill[hy[got], hx[got]], 0, 255)
    out[hy[got], hx[got]] = val.astype(np.uint8)
    if not got.all():
        # У края вырезки соседей той же фазы может не быть: такие точки
        # добираются размытием по уже восстановленному окружению. Больше
        # `PERIOD_MISS` — модель не годится (буквы остались бы пятнами).
        if got.mean() < 1.0 - PERIOD_MISS:
            return None
        miss = np.zeros((H, W), np.uint8)
        miss[hy[~got], hx[~got]] = 255
        out = cv2.inpaint(out, miss, INPAINT_R, cv2.INPAINT_TELEA)
    return out


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


# ── Ритм строк абзаца: базовые линии, шаг, отступ (раздел Ф) ─────────────
#
# Ф1–Ф4 (проект 89, конспект от руки в клетку, 16.10.2026). Строки абзаца
# брались из полос маски, а у слитного почерка петли соседних строк сливают
# полосы, а обрывки выносных дают лишние: 12 «строк» на 11 настоящих, и
# раскладка, принятая `fit_lines`, отвергалась вызывающим — абзац уходил на
# серую плашку. Рамки строк детектора (`lineBoxes`) у блока уже есть, и они
# знают и число строк, и их место. Отсюда:
#   * база строки — низ её «тела» (ряды с массой краски от половины пика);
#   * шаг — медиана расстояний между базами; ритм ровный при разбросе не
#     больше `RHYTHM_MAD` шага — только тогда шаг держится при раскладке;
#   * левый край — медиана начал строк кроме первой, отступ первой строки —
#     разница с ней, когда остальные строки выровнены (`INDENT_ALIGN` кегля)
#     и сдвиг больше `INDENT_MIN` кегля.
RHYTHM_MAD = float(os.environ.get("PAINT_RHYTHM_MAD", "0.2"))
RHYTHM_MAX = float(os.environ.get("PAINT_RHYTHM_MAX", "0.45"))
INDENT_MIN = float(os.environ.get("PAINT_INDENT_MIN", "0.5"))
INDENT_ALIGN = float(os.environ.get("PAINT_INDENT_ALIGN", "0.4"))
# Сдвиг первой строки больше стольких кеглей — не абзацный отступ, а
# рамка, не захватившая начало строки (или буквица): отступа нет.
INDENT_MAX = float(os.environ.get("PAINT_INDENT_MAX", "4"))
# Ф3. Докуда ужимаются буквы при НЕИЗМЕННОМ шаге строк: ниже — шаг ужимается
# вместе с ними (строки уходят с линовки, и это последнее средство).
FIT_FLOOR = float(os.environ.get("PAINT_FIT_FLOOR", "0.7"))
RIGHT_Q = float(os.environ.get("PAINT_RIGHT_Q", "80"))
FIT_HARD = float(os.environ.get("PAINT_FIT_HARD", "0.45"))


def line_geometry(line_boxes, mask=None, em: float = 0.0) -> "dict | None":
    """Геометрия абзаца по рамкам строк (в координатах вырезки, y вниз).
    None — строк меньше двух или рамки негодны."""
    lbs = [tuple(float(v) for v in lb[:4]) for lb in (line_boxes or [])
           if lb and len(lb) >= 4 and lb[2] > lb[0] and lb[3] > lb[1]]
    if len(lbs) < 2:
        return None
    lbs.sort(key=lambda b: (b[1] + b[3]) / 2.0)
    bases = []
    # Начало строки — по КРАСКЕ её тела в пределах блока, а не по рамке
    # детектора: слово за буквицей детектор отдаёт отдельно (С2), и рамка
    # первой строки начиналась с третьего слова — «отступ» выходил в девять
    # кеглей (страница Чехова, 16.10.2026).
    bx0 = min(b[0] for b in lbs)
    bx1 = max(b[2] for b in lbs)
    starts = []
    for x0, y0, x1, y1 in lbs:
        base = y0 + 0.8 * (y1 - y0)
        st_ = x0
        if mask is not None:
            H, W = mask.shape[:2]
            a, b = max(0, int(y0)), min(H, int(math.ceil(y1)))
            c, d = max(0, int(x0)), min(W, int(math.ceil(x1)))
            if b - a >= 3 and d - c >= 3:
                prof = mask[a:b, c:d].sum(axis=1).astype(float)
                if prof.max() > 0:
                    body = np.nonzero(prof >= 0.5 * prof.max())[0]
                    base = a + float(body[-1]) + 1.0
                    rows_ = mask[a + int(body[0]):a + int(body[-1]) + 1,
                                 max(0, int(bx0)):min(W, int(math.ceil(bx1)))]
                    cols = np.nonzero(rows_.any(axis=0))[0]
                    if len(cols):
                        st_ = min(x0, max(0, int(bx0)) + float(cols[0]))
        bases.append(base)
        starts.append(st_)
    lbs = [(st_, b[1], b[2], b[3]) for st_, b in zip(starts, lbs)]
    gaps = np.diff(bases)
    if (gaps <= 0).any():
        return None
    pitch = float(np.median(gaps))
    mad = float(np.median(np.abs(gaps - pitch)))
    # Ровный — и по медиане разброса, и без выброса: строка вдвое дальше
    # соседних — это разрыв (форма, таблица), а не тот же шаг.
    regular = mad <= RHYTHM_MAD * pitch and float(np.max(np.abs(gaps - pitch))) <= RHYTHM_MAX * pitch
    # База первой строки — по всем строкам сразу (наименьшие квадраты):
    # отдельная база пляшет у почерка сильнее, чем линовка под ним.
    idx = np.arange(len(bases), dtype=float)
    base0 = float(np.mean(np.array(bases) - pitch * idx)) if regular else bases[0]
    rest = [b[0] for b in lbs[1:]]
    left = float(np.median(rest))
    # Правый край — не самая длинная строка (у рукописи это строка
    # с переносом, вылезшая к краю листа), а 80-й процентиль концов строк.
    right = float(np.percentile([b[2] for b in lbs], RIGHT_Q))
    spread = float(np.median(np.abs(np.array(rest) - left)))
    em = em or 0.8 * pitch
    indent = lbs[0][0] - left
    if indent < INDENT_MIN * em or indent > INDENT_MAX * em or spread > INDENT_ALIGN * em:
        # Отступа нет (или строки не выровнены): левый край — самый левый
        # из начал строк, чтобы ни одна строка не вышла за поле оригинала.
        indent = 0.0
        left = min(left, lbs[0][0])
    heads = para_heads(lbs, indent, left, em)
    return {"bases": bases, "base0": base0, "pitch": pitch, "regular": bool(regular),
            "left": left, "right": right, "indent": float(indent), "rows": len(lbs),
            "top": min(b[1] for b in lbs), "bottom": max(b[3] for b in lbs),
            # Х3: первые строки абзацев внутри блока и доля исходника до них.
            "heads": heads,
            "shares": [sum(b[2] - b[0] for b in lbs[:h]) / max(1e-6, sum(b[2] - b[0] for b in lbs))
                       for h in heads],
            # Х2: выключка по краям строк (None — решить нечем).
            "align": geometry_align(lbs, heads, em)}


# Ф2. Почерк не сжимается по ширине. Кегль надписи меряется по высоте
# связных областей, а у слитного почерка область — это СЛОВО с петлями:
# «буква» выходит от выносного до выносного, кегль — в 1.6 раза крупнее,
# и прежнее правило прятало ошибку, сжимая буквы до `HSCALE_WIDTH_MIN`
# (высокие сплющенные буквы шире краски оригинала). У рукописи высота —
# мера ненадёжная, а ширина надёжная: кегль берётся такой, при котором
# исходный текст тем же шрифтом занял бы ширину краски оригинала, и не
# крупнее измеренного. У печати — как прежде: кегль по высоте, ширина
# начертания по отношению краски (h0).
CALIB_FLOOR = float(os.environ.get("PAINT_CALIB_FLOOR", "0.5"))


def calibrate(em: float, inkw: float, ours: float, hand: bool = False,
              hmin: float = 0.74) -> tuple:
    """(кегль, сжатие по ширине)."""
    if not (inkw > 0 and ours > 0 and em > 0):
        return em, 1.0
    r = inkw / ours
    if hand:
        return em * max(CALIB_FLOOR, min(1.0, r)), 1.0
    return em, min(1.0, max(hmin, r))


def _wrap_rhythm(words: list, width: float, size: float, measure_w, split_word,
                 first_indent: float, force: bool = False,
                 heads_out: "list | None" = None) -> "list | None":
    """Строки перевода при кегле `size`; первая строка короче на отступ.
    Слово шире строки — None, а с `force` — своей строкой (выйдет за край,
    и это назовёт `over`): пустой ответ на непустой текст стёр бы оригинал
    и не написал ничего."""
    lines, cur, ws = [], "", list(words)
    heads = [0]
    while ws:
        w = ws[0]
        # Отступ — у первой строки КАЖДОГО абзаца (Х3), не только блока.
        head = len(lines) == heads[-1]
        room_w = width - (first_indent if head and first_indent > 0 else 0.0)
        if w == "\n":
            ws.pop(0)
            if cur:
                lines.append(cur)
                cur = ""
            if lines and heads[-1] != len(lines):
                heads.append(len(lines))
            continue
        probe = (cur + " " + w) if cur else w
        if measure_w(probe, size) <= room_w:
            cur = probe
            ws.pop(0)
            continue
        if split_word is not None:
            room = room_w - (measure_w(cur + " ", size) if cur else 0.0)
            sp = split_word(w, room, size)
            if sp:
                lines.append((cur + " " + sp[0]) if cur else sp[0])
                ws[0] = sp[1]
                cur = ""
                continue
        if not cur:
            if not force:
                return None                 # слово шире строки
            lines.append(w)
            ws.pop(0)
            continue
        lines.append(cur)
        cur = ""
    if cur:
        lines.append(cur)
    if heads_out is not None:
        heads_out[:] = [h for h in heads if h < len(lines)]
    return lines


def fit_rhythm(text: str, width: float, em: float, step: float, rows: int, extra: int,
               measure_w, split_word=None, first_indent: float = 0.0,
               fixed: bool = False) -> tuple:
    """(кегль, шаг, строки, вышло ли за место) — раскладка абзаца с ритмом.

    Порядок уступок (Ф3): полный кегль в строках оригинала; полный кегль
    и свободные строки ниже (`extra`, тем же шагом); буквы мельче при том
    же шаге до `FIT_FLOOR`; потом буквы и шаг вместе до `FIT_HARD`; не влезло
    и так — строки сколько выйдет, и это называется (`over`). `fixed` —
    кегль задан страницей (Ф4): не ужимать, только разложить."""
    words = []
    for k, part in enumerate((text or "").split("\n")):
        if k and words and words[-1] != "\n":
            words.append("\n")
        words.extend(part.split())
    while words and words[-1] == "\n":
        words.pop()
    if not words:
        return em, step, [], False
    rows = max(1, int(rows))
    n_all = rows + max(0, int(extra))

    def lay(size):
        return _wrap_rhythm(words, width, size, measure_w, split_word, first_indent)
    if fixed:
        got = lay(em)
        if got is None:
            got = _wrap_rhythm(words, width, em, measure_w, split_word, first_indent, True)
            return em, step, got, True
        return em, step, got, len(got) > n_all
    got = lay(em)
    if got is not None and len(got) <= n_all:
        return em, step, got, False
    got = lay(em * FIT_FLOOR)
    if got is not None and len(got) <= n_all:
        lo, hi, best = FIT_FLOOR, 1.0, (em * FIT_FLOOR, got)
        for _ in range(9):
            mid = (lo + hi) / 2.0
            g = lay(em * mid)
            if g is not None and len(g) <= n_all:
                lo, best = mid, (em * mid, g)
            else:
                hi = mid
        return best[0], step, best[1], False
    height = (n_all - 1) * step
    f = FIT_FLOOR
    while f > FIT_HARD:
        f = max(FIT_HARD, f * 0.94)
        st = step * f / FIT_FLOOR
        cap = int(height / st + 1e-6) + 1
        g = lay(em * f)
        if g is not None and len(g) <= cap:
            return em * f, st, g, False
    st = step * FIT_HARD / FIT_FLOOR
    g = _wrap_rhythm(words, width, em * FIT_HARD, measure_w, split_word, first_indent, True)
    return em * FIT_HARD, st, g, True


def rhythm_heads(text: str, width: float, size: float, measure_w, split_word=None,
                 first_indent: float = 0.0) -> list:
    """Номера первых строк абзацев в раскладке `fit_rhythm` при кегле `size`
    (та же раскладка — она детерминирована)."""
    words = []
    for k, part in enumerate((text or "").split("\n")):
        if k and words and words[-1] != "\n":
            words.append("\n")
        words.extend(part.split())
    while words and words[-1] == "\n":
        words.pop()
    heads: list = []
    _wrap_rhythm(words, width, size, measure_w, split_word, first_indent, True, heads)
    return heads or [0]


# Ф4. Один кегль и один шаг на страницу. Абзацы одного семейства с близким
# кеглем (в пределах `EVEN_SPREAD`) — один класс: кегль класса — меньший из
# подогнанных (иначе один абзац не влез бы), шаг — медиана, если шаги близки
# (`EVEN_STEP_SPREAD`). Двух абзацев хватает (`EVEN_MIN`): подписи схемы
# однострочные и в класс не входят вовсе.
EVEN_SPREAD = float(os.environ.get("PAINT_EVEN_SPREAD", "0.25"))
EVEN_STEP_SPREAD = float(os.environ.get("PAINT_EVEN_STEP_SPREAD", "0.15"))
EVEN_MIN = int(os.environ.get("PAINT_EVEN_MIN", "2"))


def even_classes(ents: list) -> list:
    """Классы абзацев страницы. `ents` — [{"em", "fam"}]; ответ — списки
    индексов (класс от `EVEN_MIN` абзацев)."""
    by: dict = {}
    for i, e in enumerate(ents):
        if e.get("em"):
            by.setdefault(e.get("fam") or "", []).append(i)
    out = []
    for idx in by.values():
        ems = sorted(ents[i]["em"] for i in idx)
        med = ems[len(ems) // 2]
        cls = [i for i in idx if abs(ents[i]["em"] - med) <= EVEN_SPREAD * med]
        if len(cls) >= EVEN_MIN:
            out.append(cls)
    return out


def even_step(steps: list) -> "float | None":
    """Общий шаг класса или None — шаги разные (разная линовка)."""
    st = sorted(s for s in steps if s)
    if not st:
        return None
    med = st[len(st) // 2]
    if all(abs(s - med) <= EVEN_STEP_SPREAD * med for s in st):
        return med
    return None


def has_letters(rgb, em: float) -> bool:
    """Есть ли в полосе краска размером с букву (Ф3: свободная ли строка под
    абзацем). Бумага — максимум окрестности (тонкие линии клетки и линейки
    им снимаются), краска — темнее бумаги больше `INK_DIFF`; длинная тонкая
    линия буквой не считается. Мерить нечем — «занято»: продолжать абзац
    поверх непрочитанного хуже, чем ужать буквы."""
    if np is None or cv2 is None or rgb is None or rgb.size == 0:
        return True
    g = rgb.astype(np.int16).mean(axis=2).astype(np.uint8) if rgb.ndim == 3 else rgb
    em = max(4.0, float(em or 0))
    kk = _odd(0.6 * em, 3, 61)
    paper = cv2.dilate(g, np.ones((kk, kk), np.uint8))
    dark = (paper.astype(np.int16) - g.astype(np.int16)) > INK_DIFF
    n, _lab, st, _c = cv2.connectedComponentsWithStats(dark.astype(np.uint8), 8)
    thin = max(2.0, 0.06 * em)
    hits = 0
    for i in range(1, n):
        w_, h_ = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if h_ >= 0.25 * em and w_ >= 0.08 * em and min(w_, h_) > thin:
            hits += 1
            if hits >= 2:
                return True
    return False


# Ф7. Толщина пера рукописи. Рукописный шрифт рисует тонкой линией, а
# конспект пишут ручкой или маркером, и перевод выходил бледнее оригинала.
# Толщина штриха оригинала (`_stem`) против толщины штриха шрифта при том же
# кегле: недостающее добирается обводкой, не больше `STROKE_MAX` кегля.
STROKE_MAX = float(os.environ.get("PAINT_STROKE_MAX", "0.04"))


def stroke_for(stem_src: float, stem_font_per_px: float, size: float, whole: bool = True):
    """Обводка с КАЖДОЙ стороны штриха до толщины пера оригинала (в единицах
    снимка или точках страницы). `whole` — целым числом (растр)."""
    if not (stem_src > 0 and stem_font_per_px > 0 and size > 0):
        return 0
    need = (stem_src - stem_font_per_px * size) / 2.0
    v = max(0.0, min(need, STROKE_MAX * size))
    return int(round(v)) if whole else v


_STEM_CACHE: dict = {}


def font_stem(path: str) -> float:
    """Толщина вертикального штриха шрифта на единицу кегля (Ф7)."""
    if not path:
        return 0.0
    if path not in _STEM_CACHE:
        v = 0.0
        try:
            from PIL import Image, ImageDraw, ImageFont
            f = ImageFont.truetype(path, 120)
            im = Image.new("L", (900, 200), 0)
            ImageDraw.Draw(im).text((10, 10), "nmuhl", font=f, fill=255)
            v = _stem(np.asarray(im) > 127) / 120.0
        except Exception:
            v = 0.0
        _STEM_CACHE[path] = v
    return _STEM_CACHE[path]


# Х10. Кегль и толщина печатного текста — по СТРОЧНЫМ оригинала и нашего
# шрифта. Кегль из высоты буквы считается постоянными долями (0.73 и 0.53
# кегля), а у старой книжной антиквы строчные ниже, чем у Noto: перевод
# книги 1886 г. выходил крупнее оригинала, и строку сжимали по ширине —
# узкие высокие буквы вместо широких низких. Правило: высота строчных
# оригинала (размах профиля строки, медиана по строкам) ÷ высота «x» нашего
# шрифта — кегль, если он меньше прежнего (прописные мерить так нельзя —
# их высота не строчная, поэтому нужна доля строчных `XH_LOWER`). Файл
# семейства — по ширине (`image_text._face_by_width`). Вес обводкой НЕ
# догоняется: штрих скана раздут размытием (книга 1886 г. по нему «жирнее»
# Noto на треть, а по отношению к строчным — 0.18 против 0.17), и обводка
# делала буквы тяжелее оригинала.
XH_LOWER = float(os.environ.get("PAINT_XH_LOWER", "0.6"))
XH_SHRINK_ONLY = os.environ.get("PAINT_XH_SHRINK_ONLY", "1") == "1"
_XH_CACHE: dict = {}


def x_height(mask, line_boxes) -> float:
    """Высота строчных оригинала в точках снимка (медиана по строкам) или 0."""
    if np is None or mask is None or not line_boxes:
        return 0.0
    H, W = mask.shape[:2]
    vals = []
    for lb in line_boxes:
        a, b = max(0, int(lb[1])), min(H, int(math.ceil(lb[3])))
        c, d = max(0, int(lb[0])), min(W, int(math.ceil(lb[2])))
        if b - a < 4 or d - c < 4:
            continue
        prof = mask[a:b, c:d].sum(axis=1)
        if not prof.max():
            continue
        core = np.nonzero(prof >= 0.5 * prof.max())[0]
        if len(core):
            vals.append(float(core[-1] - core[0] + 1))
    return float(np.median(vals)) if vals else 0.0


def font_xh(path: str) -> float:
    """Высота «x» шрифта на единицу кегля."""
    if not path:
        return 0.0
    if path not in _XH_CACHE:
        v = 0.0
        try:
            # Тем же замером, что у оригинала (`x_height` — размах профиля
            # строки): рамка «x» и профиль строки расходились на точку,
            # и кегль по строчным перелетал.
            from PIL import Image, ImageDraw, ImageFont
            f = ImageFont.truetype(path, 200)
            txt = "minimum examen ovum annex"
            im = Image.new("L", (int(f.getlength(txt)) + 40, 400), 0)
            dr = ImageDraw.Draw(im)
            dr.text((20, 60), txt, font=f, fill=255)
            v = x_height(np.asarray(im) > 127, [list(dr.textbbox((20, 60), txt, font=f))]) / 200.0
        except Exception:
            v = 0.0
        _XH_CACHE[path] = v
    return _XH_CACHE[path]


def lower_share(src: str) -> float:
    letters = [ch for ch in (src or "") if ch.isalpha()]
    return (sum(1 for ch in letters if ch.islower()) / float(len(letters))) if letters else 0.0


def em_by_xheight(em: float, xh_src: float, path: str, src: str) -> float:
    """Кегль по строчным (Х10): меньше прежнего — он, иначе прежний."""
    fx = font_xh(path)
    if not (em > 0 and xh_src > 0 and fx > 0) or lower_share(src) < XH_LOWER:
        return em
    return min(em, xh_src / fx) if XH_SHRINK_ONLY else xh_src / fx


# Х11. «Полужирный» снимается площадью краски. Полужирный решает толщина
# штриха к кеглю (`BOLD_STEM`), и у JPEG её решает размытие: аннотация
# статьи (обычный гротеск) мерилась 0.121 при пороге 0.12 и печаталась
# жирным. Площадь краски оригинала в рамках строк сравнивается с площадью
# букв исходного текста, набранного обычным и жирным файлом при том же
# кегле (лог-расстояние): ближе к обычному — не жирный. Размытие площадь
# только РАЗДУВАЕТ, то есть тянет к жирному, — снять жирный зря правило
# не может. Назначать жирный площадью нельзя: у контрастной антиквы
# размытие раздувает волосяные штрихи, и обычная выглядит жирной (замер на
# Old Standard: 0.94 к жирному при 1.38 к обычному). Ширину не правим:
# узкий шрифт оригинала не тоньше (аннотация: 1.09 к обычному, 0.69 к
# жирному).


def ink_area(mask, line_boxes) -> int:
    """Площадь краски внутри рамок строк."""
    H, W = mask.shape[:2]
    area = 0
    for lb in line_boxes or ():
        a, b = max(0, int(lb[1])), min(H, int(math.ceil(lb[3])))
        c, d = max(0, int(lb[0])), min(W, int(math.ceil(lb[2])))
        if b > a and d > c:
            area += int(mask[a:b, c:d].sum())
    return area


def _text_area(path: str, src: str, em: float) -> float:
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(path, max(4, int(round(em))))
    im = Image.new("L", (int(f.getlength(src)) + 20, int(em * 2.2) + 10), 0)
    ImageDraw.Draw(im).text((5, int(0.3 * em)), src, font=f, fill=255)
    return float((np.asarray(im) > 127).sum())


def bold_by_area(mask, line_boxes, src: str, em: float, reg_path: str, bold_path: str) -> bool:
    """False — краска ближе к обычному начертанию, чем к жирному (Х11)."""
    if np is None or not (src and line_boxes and em > 0 and reg_path and bold_path)             or reg_path == bold_path:
        return True
    area = ink_area(mask, line_boxes)
    try:
        ar, ab = _text_area(reg_path, src, em), _text_area(bold_path, src, em)
    except Exception:
        return True
    if area <= 0 or ar <= 0 or ab <= 0:
        return True
    return abs(math.log(area / ab)) <= abs(math.log(area / ar))


# Х12–Х13. Вес, цвет и плотность набора — по середине тона. Маска букв
# берёт всё, что заметно темнее бумаги, и размытие раздувает по ней штрих.
# На уровне посередине между бумагой и краской край штриха при симметричном
# размытии стоит на месте (`stem_mid`: Old Standard 48 px — 3.43 без
# размытия, 3.49 при 1.5 px). По этой маске: ось штриха — цвет краски
# (`core_ink`), доля краски в полосе строчных — плотность набора
# (`band_density`), а обводка перевода подбирается так, чтобы ЕГО плотность
# (тем же шрифтом, кеглем и сжатием, `sample_density`) сравнялась
# с оригиналом (`weight_by_density`). Не толщина штриха в точках: у перевода,
# сжатого по ширине, тот же штрих на узкой букве читается жирнее (заголовок
# статьи, Noto Serif сжат до 0.78). Книга 1886 г.: доля тёмного 0.141
# против 0.144 (было 0.097), краска 22 против 16 (было 29).
# Тоньше этого (в точках снимка) штрих сравним с размытием, и середина тона
# его не держит: аннотация статьи (штрих 2 точки) по ней «жирнее» шрифта,
# и обводка делала её темнее оригинала (доля тёмного 0.163 против 0.14).
WEIGHT_MIN_PX = float(os.environ.get("PAINT_WEIGHT_MIN_PX", "3"))
CORE_MIN = int(os.environ.get("PAINT_CORE_MIN", "40"))
DENS_TOL = float(os.environ.get("PAINT_DENS_TOL", "0.04"))


def stem_mid(rgb, line_boxes, bg, ink) -> float:
    """Толщина вертикального штриха на середине тона, в точках снимка, или 0.
    Край штриха — там, где тон пересекает середину, с интерполяцией между
    точками: у тонкого штриха (3–4 точки) счёт целыми точками давал шум
    в треть толщины."""
    if np is None or rgb is None or not line_boxes:
        return 0.0
    g = rgb[..., :3].astype(np.float32).mean(axis=2)
    pb, pi = float(np.mean(bg)), float(np.mean(ink))
    if abs(pb - pi) < 2 * INK_DIFF / 3:
        return 0.0
    thr = (pb + pi) / 2.0
    d_all = (thr - g) if pi < pb else (g - thr)          # > 0 — краска
    H, W = g.shape
    runs = []
    for lb in line_boxes:
        a, b = max(0, int(lb[1])), min(H, int(math.ceil(lb[3])))
        c, d = max(0, int(lb[0])), min(W, int(math.ceil(lb[2])))
        if b - a < 6 or d - c < 6:
            continue
        dd = d_all[a:b, c:d]
        mm = dd > 0
        prof = mm.sum(axis=1)
        if not prof.max():
            continue
        core = np.nonzero(prof >= 0.5 * prof.max())[0]
        top, bot = int(core[0]), int(core[-1])
        xh = bot - top + 1
        for y in range(top + xh // 4, bot - xh // 4 + 1):
            row = dd[y]
            sg = row > 0
            dif = np.diff(sg.astype(np.int8))
            ups, downs = np.nonzero(dif == 1)[0], np.nonzero(dif == -1)[0]
            for u in ups:
                nx = downs[downs > u]
                if not len(nx):
                    break
                v = int(nx[0])
                # Край: u→u+1 (вход в краску), v→v+1 (выход), линейно.
                xa = u + row[u] / (row[u] - row[u + 1]) if row[u] != row[u + 1] else u + 0.5
                xb = v + row[v] / (row[v] - row[v + 1]) if row[v] != row[v + 1] else v + 0.5
                w_ = xb - xa
                if 0 < w_ < 0.5 * xh:
                    runs.append(w_)
    if len(runs) < 20:
        return 0.0
    return float(np.median(runs))


def core_ink(rgb, mask, bg, ink, stem: float):
    """Цвет краски — по ОСИ штриха (Х13) или None.

    Прежний цвет — медиана самой тёмной трети точек маски; у штриха в 3–4
    точки половина её — края, размытые к бумаге, и перевод книги 1886 г.
    печатался краской 28 при самых тёмных точках оригинала 16. На оси
    штриха (точки маски середины тона не ближе половины толщины штриха
    к её краю) краска не смешана с бумагой при любом размытии. Штрих
    тоньше `WEIGHT_MIN_PX` оси не имеет — None, прежний цвет."""
    if cv2 is None or np is None or rgb is None or mask is None or stem < WEIGHT_MIN_PX:
        return None
    g = rgb[..., :3].astype(np.float32).mean(axis=2)
    pb, pi = float(np.mean(bg)), float(np.mean(ink))
    if abs(pb - pi) < 2 * INK_DIFF / 3:
        return None
    mid = ((g < (pb + pi) / 2.0) if pi < pb else (g > (pb + pi) / 2.0)) & mask.astype(bool)
    dt = cv2.distanceTransform(mid.astype(np.uint8), cv2.DIST_L2, 3)
    core = dt >= max(1.0, 0.5 * stem)
    if core.sum() < CORE_MIN:
        return None
    return tuple(int(v) for v in np.median(rgb[..., :3][core], axis=0))


def band_density(rgb, line_boxes, bg, ink) -> float:
    """Плотность набора (Х13): доля краски (середина тона) в полосе строчных
    между первой и последней краской строки; медиана по строкам, или 0."""
    if np is None or rgb is None or not line_boxes:
        return 0.0
    g = rgb[..., :3].astype(np.float32).mean(axis=2) if rgb.ndim == 3 else rgb.astype(np.float32)
    pb, pi = float(np.mean(bg)), float(np.mean(ink))
    if abs(pb - pi) < 2 * INK_DIFF / 3:
        return 0.0
    m = (g < (pb + pi) / 2.0) if pi < pb else (g > (pb + pi) / 2.0)
    H, W = m.shape
    vals = []
    for lb in line_boxes:
        a, b = max(0, int(lb[1])), min(H, int(math.ceil(lb[3])))
        c, d = max(0, int(lb[0])), min(W, int(math.ceil(lb[2])))
        if b - a < 6 or d - c < 6:
            continue
        mm = m[a:b, c:d]
        prof = mm.sum(axis=1)
        if not prof.max():
            continue
        core = np.nonzero(prof >= 0.5 * prof.max())[0]
        cols = np.nonzero(mm.any(axis=0))[0]
        band = mm[core[0]:core[-1] + 1, cols[0]:cols[-1] + 1]
        if band.size:
            vals.append(float(band.mean()))
    return float(np.median(vals)) if vals else 0.0


def sample_density(font_path: str, text: str, size_px: float, h0: float, ink, bg,
                   stroke_px: float = 0.0, sup: int = 4) -> float:
    """Плотность набора строки `text` шрифтом `font_path` (Х13): рисуется
    в `sup` раз крупнее с обводкой `stroke_px`, сжимается по ширине `h0`
    и мерится `band_density`. Один код у картинки и у PDF."""
    from PIL import Image, ImageDraw, ImageFont
    fb = ImageFont.truetype(font_path, max(4, int(round(size_px * sup))))
    swb = int(round(stroke_px * sup))
    bb = fb.getbbox(text, stroke_width=swb)
    wb = bb[2] - min(0, bb[0]) + 4 * sup + swb
    hb = int(size_px * 1.6 * sup) + 2 * swb
    ink = tuple(int(v) for v in ink)
    bg = tuple(int(v) for v in bg)
    im = Image.new("RGB", (max(sup, wb), max(sup, hb)), bg)
    ImageDraw.Draw(im).text((2 * sup, swb), text, font=fb, fill=ink, stroke_width=swb, stroke_fill=ink)
    im = im.resize((max(1, int(im.width / sup * h0)), max(1, int(im.height / sup))), Image.LANCZOS)
    return band_density(np.asarray(im), [[0, 0, im.width, im.height]], bg, ink)


def weight_by_density(target: float, render, smax: float) -> float:
    """Обводка (с каждой стороны), при которой плотность набора перевода
    равна `target` (Х13). `render(s)` — плотность строки при обводке s.
    Без обводки уже не светлее — 0: истончать шрифт нечем."""
    if not (target > 0 and smax > 0):
        return 0.0
    d0 = render(0.0)
    if d0 <= 0 or d0 >= target * (1.0 - DENS_TOL):
        return 0.0
    lo, hi = 0.0, smax
    if render(hi) < target:
        return hi
    for _ in range(7):
        mid = (lo + hi) / 2.0
        if render(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ── Раздел Х: машинопись, выключка, абзацы внутри блока (16.10.2026) ─────

# Х1. Машинопись — шаг знака постоянный: середины букв строки ложатся на
# сетку шага знака. Шаг — ширина строк ÷ число знаков исходника (кегль для
# этого не нужен, а он у машинописи и почерка меряется хуже всего); мера —
# лучшая по шагам около него фазовая согласованность середин «букв» (связных
# столбцов краски). Замер на плитках лендинга: машинопись 1940 г. 0.65,
# наборная книга 1886 г. 0.40, статья 0.24–0.30, случайный уровень ~0.15;
# у слитного почерка «букв» в строке мало — мерить нечем (None).
MONO_COH = float(os.environ.get("PAINT_MONO_COH", "0.55"))


def mono_score(mask, line_boxes, src_len: int) -> "float | None":
    """Похожесть на машинопись 0..1 или None — мерить нечем."""
    if np is None or mask is None or not line_boxes or not src_len:
        return None
    H, W = mask.shape[:2]
    lbs = [lb[:4] for lb in line_boxes]
    adv = sum(max(0.0, lb[2] - lb[0]) for lb in lbs) / float(src_len)
    if adv < 3:
        return None
    vals = []
    for x0, y0, x1, y1 in lbs:
        a, b = max(0, int(y0)), min(H, int(math.ceil(y1)))
        c, d = max(0, int(x0)), min(W, int(math.ceil(x1)))
        if b - a < 3 or d - c < 3:
            continue
        col = mask[a:b, c:d].any(axis=0).astype(np.int8)
        dif = np.diff(np.concatenate(([0], col, [0])))
        st, en = np.where(dif == 1)[0], np.where(dif == -1)[0]
        ctr = (st + en) / 2.0
        if len(ctr) < 12:
            continue
        best = 0.0
        for P in np.linspace(0.8 * adv, 1.25 * adv, 40):
            best = max(best, float(abs(np.exp(2j * np.pi * ctr / P).mean())))
        vals.append(best)
    if len(vals) < 2:
        return None
    return float(np.median(vals))


# Х9. Засечки — по буквам, а не только по слову модели. Признак «serif»
# ставит зрячая модель при чтении; блоки, прочитанные до вопроса о засечках
# (книга Чехова на лендинге, 1886 г.), его не несут, и перевод антиквы
# рисовался рубленым. Мера: вертикальный штрих, дошедший от середины
# строчной буквы до строки, и ширина его «ступни» в нижних строках; вынос
# засечки = (ступня − штрих − 1 точка дрожания) / высота строчной, медиана
# по штрихам. Замер: рубленые (Arial, Calibri, Verdana, Segoe, Tahoma,
# Trebuchet, Noto Sans, обычные и жирные) 0–0.10, антиква (Times, Georgia,
# Cambria, Noto Serif, обычные и жирные, от 24 px) 0.17–0.58; книга 1886 г.
# 0.43, заголовок статьи (Times) 0.21, её текст (рубленый) 0. Мерить нечем
# (строчная ниже `SERIF_XH` точек, штрихов меньше `SERIF_STEMS`) — None,
# решает модель. Между порогами — тоже решает модель.
SERIF_EXT = float(os.environ.get("PAINT_SERIF_EXT", "0.13"))
SANS_EXT = float(os.environ.get("PAINT_SANS_EXT", "0.05"))
SERIF_XH = int(os.environ.get("PAINT_SERIF_XH", "10"))
SERIF_STEMS = int(os.environ.get("PAINT_SERIF_STEMS", "10"))


def serif_score(mask, line_boxes) -> "float | None":
    """Вынос засечки в долях высоты строчной (медиана) или None."""
    if np is None or mask is None or not line_boxes:
        return None
    H, W = mask.shape[:2]
    vals = []
    for lb in line_boxes:
        x0, y0, x1, y1 = lb[:4]
        a, b = max(0, int(y0)), min(H, int(math.ceil(y1)))
        c, d = max(0, int(x0)), min(W, int(math.ceil(x1)))
        m = mask[a:b, c:d]
        if m.shape[0] < 8 or m.shape[1] < 8:
            continue
        stem = _stem(m)
        if stem < 1:
            continue
        prof = m.sum(axis=1)
        core = np.nonzero(prof >= 0.5 * prof.max())[0]
        if not len(core):
            continue
        # Размах, а не число строк: у прописных с засечками профиль — пики
        # сверху и снизу (сами засечки), середина тоньше половины пика.
        top, bot = int(core[0]), int(core[-1])
        if bot - top < SERIF_XH:
            continue
        xh = bot - top
        # Штрихи — на двух высотах буквы: у прописных середина занята
        # перекладинами (Е, Н, Ч) и стыками (Р, В, К); ниже — уже чаши
        # букв (а, б). Штрих считается раз.
        seen = []
        for share in (0.5, 0.3):
            mid = top + int(round(share * xh))
            dif = np.diff(np.concatenate(([0], m[mid].astype(np.int8), [0])))
            for s0, e0 in zip(np.nonzero(dif == 1)[0], np.nonzero(dif == -1)[0]):
                w = int(e0 - s0)
                if w > 1.8 * stem:
                    continue                    # не штрих: перекладина, дуга
                cx = int((s0 + e0) // 2)
                if any(abs(cx - q) <= stem for q in seen):
                    continue
                seen.append(cx)
                y = mid
                while y + 1 < m.shape[0] and m[y + 1, cx]:
                    y += 1
                if abs(y - bot) > max(2, 0.15 * xh):
                    continue                    # штрих не дошёл до строки (р, у)
                foot = 0
                for yy in range(max(mid, y - max(1, int(0.12 * xh))), y + 1):
                    r = m[yy]
                    l_ = cx
                    while l_ > 0 and r[l_ - 1]:
                        l_ -= 1
                    r_ = cx
                    while r_ + 1 < len(r) and r[r_ + 1]:
                        r_ += 1
                    foot = max(foot, r_ - l_ + 1)
                vals.append(max(0, foot - w - 1) / float(max(1, xh)))
    if len(vals) < SERIF_STEMS:
        return None
    return float(np.median(vals))


def serif_fam(mask, line_boxes, fam: str, plain: str = "") -> str:
    """Семейство по засечкам (Х9): `fam` — что сказала модель; `plain` —
    как вызывающий называет рубленый ("" у картинки, "sans" у PDF), а
    антиква — "serif" у картинки, "" у PDF (там она по умолчанию)."""
    if fam in ("hand", "type"):
        return fam
    sc = serif_score(mask, line_boxes)
    if sc is None:
        return fam
    serif = "serif" if plain == "" else ""
    if sc >= SERIF_EXT:
        return serif
    if sc <= SANS_EXT:
        return plain
    return fam


# Х2. Выключка — по краям строк оригинала, а не по слову модели о блоке:
# машинопись 1940 г. (левый край ровный, правый рваный) печаталась по центру.
# Левый край ровный (разброс начал ≤ `ALIGN_MAD` кегля, без первых строк
# абзацев) и правый ровный (без последних строк абзацев) — по ширине; только
# левый — влево; только правый — вправо; ровные середины — по центру.
ALIGN_MAD = float(os.environ.get("PAINT_ALIGN_MAD", "0.4"))
# По ширине — только при правом крае ровнее этого (доля кегля): у почерка
# правый край «ровный на глаз» (0.14 кегля у конспекта), у набранной книги —
# 0.05; выключать почерк по ширине — значит растянуть слова, как никто
# не пишет.
JUSTIFY_MAD = float(os.environ.get("PAINT_JUSTIFY_MAD", "0.1"))


def _mad(v):
    if not len(v):
        return float("inf")
    a = np.asarray(v, dtype=float)
    return float(np.median(np.abs(a - np.median(a))))


def geometry_align(lbs: list, heads: list, em: float) -> "str | None":
    """Выключка абзаца по рамкам строк (начало строки — уже по краске) или
    None — строк мало, решить нечем. `heads` — номера первых строк абзацев."""
    n = len(lbs)
    if n < 3 or not em:
        return None
    hs = set(heads) | {0}
    ends = {h - 1 for h in hs if h > 0} | {n - 1}
    lefts = [lbs[i][0] for i in range(n) if i not in hs]
    rights = [lbs[i][2] for i in range(n) if i not in ends]
    mids = [(lbs[i][0] + lbs[i][2]) / 2.0 for i in range(n) if i not in ends]
    tol = ALIGN_MAD * em
    l_ok = len(lefts) >= 2 and _mad(lefts) <= tol
    r_ok = len(rights) >= 2 and _mad(rights) <= tol
    if l_ok and r_ok and _mad(rights) <= JUSTIFY_MAD * em:
        return "justify"
    if l_ok and r_ok:
        return "left"
    if l_ok:
        return "left"
    if r_ok:
        return "right"
    if len(mids) >= 2 and _mad(mids) <= tol:
        return "center"
    return None


# Х3. Абзац внутри блока. Блок машинописи нёс два абзаца, и перевод вставал
# сплошным текстом: красной строки второго не было. Первая строка абзаца —
# строка (не первая), начатая с того же отступа, что и первая строка блока
# (или с отступом не меньше `INDENT_MIN`, если у первой его нет), при ровном
# левом крае остальных.
def para_heads(lbs: list, indent: float, left: float, em: float) -> list:
    """Номера строк (кроме первой), с которых начинаются абзацы."""
    if not em or len(lbs) < 3:
        return []
    out = []
    for i in range(1, len(lbs)):
        off = lbs[i][0] - left
        if indent > 0:
            if abs(off - indent) <= 0.6 * em and off >= INDENT_MIN * em:
                out.append(i)
        elif INDENT_MIN * em <= off <= INDENT_MAX * em:
            out.append(i)
    return out


_SENT_END = None


def para_breaks(text: str, shares: list) -> str:
    """Разрывы абзацев в переводе: на долях `shares` (0..1 — доля текста
    оригинала до начала абзаца) — у ближайшего конца предложения не дальше
    `PARA_BREAK_REACH` доли текста. Нет такого — разрыва нет: делить
    предложение пополам хуже, чем не разделить абзацы."""
    import re
    global _SENT_END
    if _SENT_END is None:
        _SENT_END = re.compile(r"[.!?…。！？؟]+[\"»”’)\]]*(?=\s)")
    if not text or "\n" in text or not shares:
        return text
    ends = [m_.end() for m_ in _SENT_END.finditer(text)]
    if not ends:
        return text
    n = len(text)
    cuts = []
    for sh in shares:
        want = sh * n
        best = min(ends, key=lambda e: abs(e - want))
        if abs(best - want) <= PARA_BREAK_REACH * n and best not in cuts and 0 < best < n:
            cuts.append(best)
    if not cuts:
        return text
    out, prev = [], 0
    for c in sorted(cuts):
        out.append(text[prev:c].strip())
        prev = c
    out.append(text[prev:].strip())
    return "\n".join(p for p in out if p)


PARA_BREAK_REACH = float(os.environ.get("PAINT_PARA_BREAK_REACH", "0.15"))


# Х8. Буква, разрезанная краем вырезки, стирается целиком. Симптом: у Чехова
# буквица «В» выходит вверх за рамку блока, и стирание резало её по краю
# вырезки — верхняя половина с завитком оставалась над переводом. Правило:
# если стёртое касается края вырезки, краска за краем, СВЯЗАННАЯ со стёртым
# (та же связная область), стирается тоже — не дальше `CUT_REACH` строк;
# мелкие области рядом с ней (завитки, точки орнамента, не крупнее
# `CUT_SAT` строки) — вместе с ней. Не стирается: область выше или шире
# `CUT_MAX` строк (рамка, линия таблицы, рисунок) и область, лежащая за
# краем больше чем на `CUT_FOREIGN` долю в рамке ЧУЖОЙ надписи.
CUT_REACH = float(os.environ.get("PAINT_CUT_REACH", "4"))
CUT_MAX = float(os.environ.get("PAINT_CUT_MAX", "4"))
CUT_SAT = float(os.environ.get("PAINT_CUT_SAT", "0.8"))
CUT_FOREIGN = float(os.environ.get("PAINT_CUT_FOREIGN", "0.3"))


def cut_sides(seed) -> tuple:
    """Какие края вырезки задевает стёртое: (лево, верх, право, низ)."""
    if seed is None or not seed.any():
        return (False, False, False, False)
    return (bool(seed[:, 0].any()), bool(seed[0, :].any()),
            bool(seed[:, -1].any()), bool(seed[-1, :].any()))


def continuation_mask(rgb, seed, inner, lh: float, foreign=()):
    """Продолжение разрезанных букв за краем прежней вырезки (Х8).
    `rgb` — расширенная вырезка; `seed` — стёртое в её координатах; `inner` —
    прежняя вырезка (x0, y0, x1, y1) в них же; `foreign` — рамки чужих
    надписей. Маска добавки (bool) или None — продолжать нечего."""
    if np is None or cv2 is None or seed is None or not seed.any():
        return None
    H, W = seed.shape
    lh = max(6.0, float(lh or 0))
    k_ = _odd(1.2 * lh, 3, 151)
    if min(H, W) <= k_:
        return None
    # Фон — максимум (у светлого текста на тёмном — минимум) окрестности шире
    # штриха: у толстой буквицы медиана окна внутри штриха сама тёмная, и
    # середина штриха краской не считалась — стирался только контур.
    g = rgb[..., :3].astype(np.float32).mean(axis=2)
    dark = float(g[seed].mean()) < float(np.median(g[~seed])) if (~seed).any() else True
    ker = np.ones((k_, k_), np.uint8)
    bg = cv2.dilate(g, ker) if dark else cv2.erode(g, ker)
    ink = ((bg - g) if dark else (g - bg)) > INK_DIFF
    n, lab, st, _c = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    if n <= 1:
        return None
    x0, y0, x1, y1 = [int(round(v)) for v in inner]
    inside = np.zeros((H, W), bool)
    inside[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    fr = np.zeros((H, W), bool)
    for f in foreign or ():
        a, b, c, d = [int(round(v)) for v in f[:4]]
        fr[max(0, b):max(0, d), max(0, a):max(0, c)] = True
    near = cv2.dilate(seed.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    keep = np.zeros((H, W), bool)

    def ok_comp(c_, big):
        h_, w_ = st[c_, cv2.CC_STAT_HEIGHT], st[c_, cv2.CC_STAT_WIDTH]
        lim = (CUT_MAX if big else CUT_SAT) * lh
        if h_ > lim or w_ > lim:
            return None
        comp = lab == c_
        out = comp & ~inside
        if not out.any():
            return None
        if (out & fr).sum() > CUT_FOREIGN * out.sum():
            return None
        return comp
    for c_ in np.unique(lab[near & ink]):
        if c_ == 0:
            continue
        comp = ok_comp(c_, True)
        if comp is not None:
            keep |= comp
    if not keep.any():
        return None
    r_ = max(3, int(0.15 * lh))
    ring = cv2.dilate(keep.astype(np.uint8), np.ones((2 * r_ + 1, 2 * r_ + 1), np.uint8)) > 0
    for c_ in np.unique(lab[ring & ink & ~keep]):
        if c_ == 0:
            continue
        comp = ok_comp(c_, False)
        if comp is not None:
            keep |= comp
    return keep
