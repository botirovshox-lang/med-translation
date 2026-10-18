# -*- coding: utf-8 -*-
"""Стирание надписи на НЕРОВНОМ фоне нейросетью LaMa (Ш1, правило Ф9).

`cv2.inpaint` (Telea) — диффузия от края дыры: на фотографии, градиенте,
ткани и пятнах стёртое выходит серым размытым пятном в форме прежних слов.
LaMa (big-lama, Suvorov et al., 2021; Apache-2.0) дорисовывает фон по
окружению и держит повторяющуюся структуру. Используется ONNX-экспорт
Carve/LaMa-ONNX (`lama_fp32.onnx`, вход 512×512, sha256 сверяет
`tools/install_paint_models.sh`).

Законы:
  * модели нет, модуля нет, вырезка велика, сбой — None, и вызывающий
    стирает прежним способом. Отказа из-за модели не бывает;
  * масштаб 1:1 — дыра закрывается плитками 512×512 точек снимка, без
    уменьшения (уменьшение размывало бы линии бумаги). Плитки идут по
    порядку, и закрытое прежней плиткой следующей служит известным фоном;
  * в результат идут ТОЛЬКО точки дыры: всё остальное — байт в байт
    исходная вырезка;
  * сессия одна на процесс и одна работа разом (`_LOCK`): воркер один
    (инвариант 1), а две копии сети в памяти — сотни мегабайт.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
import types
from pathlib import Path

try:
    import numpy as np
except Exception:                                   # pragma: no cover
    np = None

ENABLED = os.environ.get("PAINT_LAMA", "1") != "0"
_DEFAULT = Path(__file__).resolve().parent / "data" / "models" / "lama_fp32.onnx"
MODEL = os.environ.get("PAINT_LAMA_MODEL", "") or str(_DEFAULT)
THREADS = int(os.environ.get("PAINT_LAMA_THREADS", "2"))
SIDE = 512                                          # вход сети
# Вырезка больше стольких мегапикселей и дыра больше стольких плиток —
# прежнее стирание: секунда на плитку, воркер один.
MAX_MPX = float(os.environ.get("PAINT_LAMA_MAX_MPX", "4"))
MAX_TILES = int(os.environ.get("PAINT_LAMA_MAX_TILES", "12"))
# Поле контекста плитки вокруг дыры, доля стороны плитки.
CTX = 0.25
# Время: на один вызов без бюджета и на одну перерисовку (`budget`). Плитка
# на сервере — 3–5 с в два потока; что не укладывается — прежнее стирание.
CALL_S = float(os.environ.get("PAINT_LAMA_CALL_S", "25"))
BUDGET_S = float(os.environ.get("PAINT_LAMA_BUDGET_S", "90"))

# Состояние — ОДНО на процесс, даже если модуль импортирован дважды
# (`backend.paint_lama` и `paint_lama` — две копии модуля): две сессии сети —
# это лишние сотни мегабайт у единственного воркера.
_ST = sys.modules.setdefault("_medcat_paint_lama_state", types.SimpleNamespace(
    lock=threading.Lock(), sess=None, key=None, failed=set(), tile_s=5.0))
_LOCK = _ST.lock
_TL = threading.local()
_LOG = logging.getLogger("paint_lama")


@contextlib.contextmanager
def budget(seconds: float = None):
    """Потолок времени LaMa на одну перерисовку (картинка, выгрузка PDF).
    Считается ТОЛЬКО время самой сети, а не вся сборка: иначе книга на
    сотни страниц получала бы LaMa на первых и Telea на остальных.
    Вложенный бюджет живёт внутри внешнего и его не продлевает."""
    if getattr(_TL, "limit", None) is not None:
        yield
        return
    _TL.limit = BUDGET_S if seconds is None else float(seconds)
    _TL.spent = 0.0
    _TL.used = _TL.refused = 0
    try:
        yield
    finally:
        _TL.limit = None


def stats() -> dict:
    """Счёт текущего бюджета: сколько стираний LaMa сделала и сколько
    отдала прежнему способу по времени."""
    return {"lama": getattr(_TL, "used", 0), "refused": getattr(_TL, "refused", 0)}


def _room() -> float:
    lim = getattr(_TL, "limit", None)
    return CALL_S if lim is None else min(CALL_S, lim - getattr(_TL, "spent", 0.0))


def _refuse():
    if getattr(_TL, "limit", None) is not None:
        _TL.refused = getattr(_TL, "refused", 0) + 1
    return None


def available() -> bool:
    if not (ENABLED and np is not None and MODEL not in _ST.failed and os.path.isfile(MODEL)):
        return False
    if _ST.__dict__.get("ort") is None:
        import importlib.util
        _ST.ort = importlib.util.find_spec("onnxruntime") is not None
    return _ST.ort


def _session():
    if _ST.sess is not None and _ST.key == MODEL:
        return _ST.sess
    try:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, THREADS)
        so.inter_op_num_threads = 1
        _ST.sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
        _ST.key = MODEL
    except Exception as e:
        # До рестарта процесса — прежнее стирание; причина — в журнал.
        _LOG.warning("LaMa не поднялась (%s): стираю прежним способом", e)
        _ST.failed.add(MODEL)
        _ST.sess = None
    return _ST.sess


def _starts(lo: int, hi: int, n: int, step: int) -> list:
    """Начала плиток длины `step` (не больше `n`), покрывающих [lo, hi)."""
    if n <= step:
        return [0]
    out, s = [], lo
    while True:
        s0 = max(0, min(s, n - step))
        if not out or s0 != out[-1]:
            out.append(s0)
        if s0 + step >= hi:
            break
        s = s0 + step - int(CTX * step)
    return out


def _tiles(hole) -> list:
    """Плитки (y0, x0): только там, где есть что стирать; рамка дыры
    раздувается на поле контекста."""
    H, W = hole.shape
    ys, xs = np.nonzero(hole)
    pad = int(CTX * SIDE)
    y0, y1 = max(0, ys.min() - pad), min(H, ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(W, xs.max() + 1 + pad)
    out = []
    for ty in _starts(y0, y1, H, SIDE):
        for tx in _starts(x0, x1, W, SIDE):
            if hole[ty:ty + SIDE, tx:tx + SIDE].any():
                out.append((ty, tx))
    return out


def _inner(t0: int, size: int, n: int) -> tuple:
    """Середина плитки по оси: у внутреннего края плитки контекст
    односторонний, и туда пишет соседняя плитка (перекрытие — `CTX`)."""
    edge = int(CTX * SIDE) // 2
    a = 0 if t0 == 0 else edge
    b = size if t0 + size >= n else size - edge
    return a, b


def inpaint(rgb, hole):
    """Стёртая вырезка (uint8 H×W×3) или None. `hole` — bool H×W, True —
    стереть."""
    if not available() or rgb is None or hole is None or not hole.any():
        return None
    H, W = hole.shape
    if H * W > MAX_MPX * 1e6 or rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    tiles = _tiles(hole)
    if not tiles or len(tiles) > MAX_TILES:
        return None
    if len(tiles) * _ST.tile_s > _room():
        return _refuse()
    # Ожидание чужой работы сети — тоже время: замок ждём не дольше остатка.
    if not _LOCK.acquire(timeout=max(0.0, _room())):
        return _refuse()
    start = None
    try:
        room = _room()
        if len(tiles) * _ST.tile_s > room:
            return _refuse()
        sess = _session()
        if sess is None:
            return None
        start = time.monotonic()
        out = np.ascontiguousarray(rgb[..., :3]).copy()
        left = hole.copy()
        for ty, tx in tiles:
            h, w = min(SIDE, H - ty), min(SIDE, W - tx)
            ya, yb = _inner(ty, h, H)
            xa, xb = _inner(tx, w, W)
            if not left[ty + ya:ty + yb, tx + xa:tx + xb].any():
                continue
            if time.monotonic() - start + _ST.tile_s > room:
                return _refuse()             # сделанное отбрасывается: `out` — копия
            img = out[ty:ty + h, tx:tx + w].astype(np.float32)
            if h < SIDE or w < SIDE:
                # Край вырезки — отражением, а не чёрным: сеть читает
                # чёрное поле как часть сцены.
                img = np.pad(img, ((0, SIDE - h), (0, SIDE - w), (0, 0)),
                             mode="reflect" if min(h, w) > 1 else "edge")
            mk = np.zeros((SIDE, SIDE), np.float32)
            mk[:h, :w] = left[ty:ty + h, tx:tx + w]
            t0 = time.monotonic()
            res = sess.run(None, {
                "image": np.ascontiguousarray((img / 255.0).transpose(2, 0, 1)[None], dtype=np.float32),
                "mask": np.ascontiguousarray(mk[None, None]),
            })[0][0].transpose(1, 2, 0)
            _ST.tile_s = 0.7 * _ST.tile_s + 0.3 * (time.monotonic() - t0)
            res = np.clip(res[ya:yb, xa:xb], 0, 255).astype(np.uint8)
            sel = left[ty + ya:ty + yb, tx + xa:tx + xb]
            out[ty + ya:ty + yb, tx + xa:tx + xb][sel] = res[sel]
            left[ty + ya:ty + yb, tx + xa:tx + xb] = False
        if left.any():
            _LOG.warning("LaMa: плитки не покрыли %d точек дыры", int(left.sum()))
            return None
        _TL.used = getattr(_TL, "used", 0) + 1
        return out
    except Exception as e:
        _LOG.warning("LaMa: сбой стирания (%s), прежний способ", e)
        return None
    finally:
        if getattr(_TL, "limit", None) is not None:
            _TL.spent = getattr(_TL, "spent", 0.0) + (time.monotonic() - start if start is not None else 0.0)
        _LOCK.release()
