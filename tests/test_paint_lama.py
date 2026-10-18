# -*- coding: utf-8 -*-
"""Ф9 / Ш1: стирание надписи на неровном фоне нейросетью LaMa.

Без модели проверяется устройство (плитки, бюджет, запасной путь — Telea);
с моделью (`backend/data/models/lama_fp32.onnx` или PAINT_LAMA_MODEL) —
что на градиенте с бликом LaMa не оставляет пятен там, где их оставляет
Telea. Нет модели — раздел с ней пропускается, а не падает.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import numpy as np  # noqa: E402
import cv2  # noqa: E402

import paint_lama as pl  # noqa: E402
import text_paint as tp  # noqa: E402

fail = []


def check(ok, msg):
    print(("  OK   " if ok else "  FAIL ") + msg)
    if not ok:
        fail.append(msg)


print("── 1. плитки покрывают дыру целиком ──")
for H, W in ((300, 400), (900, 1300), (520, 2000)):
    hole = np.zeros((H, W), bool)
    hole[H // 3:H // 3 + 40, 20:W - 20] = True
    hole[H - 30:H - 5, W // 2:W // 2 + 60] = True
    cov = np.zeros((H, W), bool)
    for ty, tx in pl._tiles(hole):
        cov[ty:ty + pl.SIDE, tx:tx + pl.SIDE] = True
    check(not (hole & ~cov).any(), "%d×%d: все точки дыры в плитках (%d плиток)" % (H, W, len(pl._tiles(hole))))
check(pl._starts(0, 100, 300, 512) == [0], "вырезка меньше плитки — одна плитка")

print("── 1а. середины плиток закрывают дыру (поддельная сеть) ──")


class _Fake:
    calls = 0

    def run(self, _o, feed):
        _Fake.calls += 1
        return [np.full((1, 3, pl.SIDE, pl.SIDE), 200.0, np.float32)]


_saved = (pl.MODEL, pl.ENABLED, pl._session, pl._ST.tile_s)
pl.MODEL, pl.ENABLED, pl._ST.tile_s = os.path.abspath(__file__), True, 0.0
pl._session = lambda: _Fake()
if pl.available():
    for H, W in ((300, 400), (900, 1300), (520, 2000)):
        hole = np.zeros((H, W), bool)
        hole[H // 3:H // 3 + 40, 20:W - 20] = True
        hole[H - 30:H - 5, W // 2:W // 2 + 60] = True
        hole[3:9, 3:W - 3] = True
        rgb = np.full((H, W, 3), 50, np.uint8)
        got = pl.inpaint(rgb, hole)
        check(got is not None and (got[hole] == 200).all() and (got[~hole] == 50).all(),
              "%d×%d: дыра закрыта целиком, вне её — без изменений" % (H, W))
    with pl.budget(100):
        pl.inpaint(np.full((300, 400, 3), 50, np.uint8), np.pad(np.ones((50, 50), bool), 100))
        check(pl.stats()["lama"] == 1, "счёт стираний в бюджете")
    # Ф9: бумага с текстом (тон ровный, шум) — Telea; перепад тона — LaMa.
    rng = np.random.RandomState(5)
    paper = (np.full((160, 420, 3), 225) + rng.randint(-6, 6, (160, 420, 1))).astype(np.uint8)
    mk = np.zeros((160, 420), bool)
    mk[60:90, 40:380] = True
    paper[mk] = 30
    m = {"mask": mk, "flat": False, "pitch": 50.0, "em": 36.0, "bg": (225, 225, 225), "ink": (30, 30, 30)}
    tp.erase(paper, m)
    check(m.get("eraseHow") != "lama", "бумага с ровным тоном — не LaMa (сеть дорисовала бы буквы)")
    xx3 = np.mgrid[0:160, 0:420][1]
    metal = np.dstack([40 + 200 * (xx3 % 140 < 70)] * 3).astype(np.uint8)
    metal[mk] = 30
    m = {"mask": mk, "flat": False, "pitch": 50.0, "em": 36.0, "bg": (140, 140, 140), "ink": (30, 30, 30)}
    tp.erase(metal, m)
    check(m.get("eraseHow") == "lama", "перепад тона фона — LaMa")
else:
    print("  SKIP нет onnxruntime")
pl.MODEL, pl.ENABLED, pl._session, pl._ST.tile_s = _saved

print("── 2. бюджет времени ──")
check(abs(pl._room() - pl.CALL_S) < 1e-6, "без бюджета — потолок вызова")
with pl.budget(5):
    check(pl._room() <= 5.0, "в бюджете — не больше бюджета")
    with pl.budget(100):
        check(pl._room() <= 5.0, "вложенный бюджет не продлевает внешний")
    pl._TL.spent = 4.5
    check(pl._room() <= 0.5 + 1e-6, "бюджет — по времени сети, а не по часам")
check(getattr(pl._TL, "limit", None) is None, "после бюджета — снят")

print("── 3. нет модели — прежнее стирание ──")
_model, _en = pl.MODEL, pl.ENABLED
pl.MODEL = os.path.join(ROOT, "нет-такой-модели.onnx")
check(not pl.available() and tp._lama() is None, "модели нет — модуль недоступен")
H, W = 160, 420
yy, xx = np.mgrid[0:H, 0:W]
grad = np.dstack([90 + 120 * xx / W + 30 * np.sin(yy / 9.0)] * 3).clip(0, 255).astype(np.uint8)
dirty = grad.copy()
mask = np.zeros((H, W), bool)
for y0 in (30, 90):
    for x0 in range(30, 390, 22):
        mask[y0:y0 + 26, x0:x0 + 4] = True
        mask[y0 + 11:y0 + 15, x0:x0 + 14] = True
dirty[mask] = 25
m = {"mask": mask, "flat": False, "pitch": 60.0, "em": 40.0, "bg": (150, 150, 150), "ink": (25, 25, 25)}
out, alpha = tp.erase(dirty, m)
check(m.get("eraseHow") != "lama" and out.shape == dirty.shape, "стёрто прежним способом")
pl.MODEL = _model

print("── 4. LaMa на градиенте с бликом ──")
if not pl.available():
    print("  SKIP модели нет (sh tools/install_paint_models.sh)")
else:
    blob = np.exp(-(((xx - 250) / 60.0) ** 2 + ((yy - 70) / 40.0) ** 2))
    clean = np.dstack([90 + 120 * xx / W + 80 * blob] * 3).clip(0, 255).astype(np.uint8)
    dirty = clean.copy()
    dirty[mask] = 25
    hole = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    t0 = time.time()
    got = pl.inpaint(dirty, hole)
    dt = time.time() - t0
    check(got is not None, "LaMa ответила (%.1f с)" % dt)
    if got is not None:
        check((got[~hole] == dirty[~hole]).all(), "вне дыры — байт в байт исходное")
        tel = cv2.inpaint(dirty, hole.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)
        # Пятна по форме букв: самое большое отклонение в дыре.
        e_l = np.percentile(np.abs(got[hole].astype(int) - clean[hole].astype(int)), 99)
        e_t = np.percentile(np.abs(tel[hole].astype(int) - clean[hole].astype(int)), 99)
        check(e_l <= e_t + 2, "LaMa не хуже Telea по худшим точкам: %.1f против %.1f" % (e_l, e_t))
        m = {"mask": mask, "flat": False, "pitch": 60.0, "em": 40.0, "bg": (150, 150, 150), "ink": (25, 25, 25)}
        tp.erase(dirty, m)
        check(m.get("eraseHow") == "lama", "erase берёт LaMa на неровном фоне без узора")
    with pl.budget(0.0):
        check(pl.inpaint(dirty, hole) is None, "бюджет исчерпан — None, прежнее стирание")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
