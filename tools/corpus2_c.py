import sys, random, math; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_build import F, _font, _np, _img, _paper, _stains, _ink, _skew, _perspective, _jpeg

"""Корпус-2, часть C: десять ТРУДНЫХ картинок (снимки и скриншоты).

Все тексты и имена выдуманы. Шрифты — только frontend/vendor/fonts/sub.
Каждая функция пишет одну картинку; случайность — от своего зерна.
"""


# ─── общие помощники ────────────────────────────────────────────────────

def _layer_text(text, font, fill, stroke=0, stroke_fill=None, pad=8):
    from PIL import Image, ImageDraw
    d0 = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    l, t, r, b = d0.textbbox((0, 0), text, font=font, stroke_width=stroke)
    lay = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((pad - l, pad - t), text, font=font, fill=fill,
                             stroke_width=stroke, stroke_fill=stroke_fill)
    return lay


def _rtext(im, center, text, font, fill, angle, stroke=0, stroke_fill=None):
    """Текст под углом (градусы против часовой), центр — в точке."""
    lay = _layer_text(text, font, fill, stroke, stroke_fill).rotate(angle, resample=3, expand=True)
    x, y = int(center[0] - lay.width / 2), int(center[1] - lay.height / 2)
    im.paste(lay, (x, y), lay)


def _ctext(d, cx, y, text, font, fill):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)


def _wrap(d, text, font, width):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def _wobble(d, pts, fill, width, rnd, amp=2.5, step=14):
    """Линия «от руки»: ломаная с дрожью."""
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        n = max(2, int(math.hypot(x2 - x1, y2 - y1) / step))
        prev = (x1, y1)
        for k in range(1, n + 1):
            t = k / n
            p = (x1 + (x2 - x1) * t + rnd.uniform(-amp, amp), y1 + (y2 - y1) * t + rnd.uniform(-amp, amp))
            if k == n:
                p = (x2, y2)
            d.line((prev, p), fill=fill, width=width)
            prev = p


def _arrowhead(d, p_from, p_to, fill, size=22, width=4):
    ang = math.atan2(p_to[1] - p_from[1], p_to[0] - p_from[0])
    for s in (-1, 1):
        a = ang + math.pi - s * 0.45
        d.line((p_to, (p_to[0] + size * math.cos(a), p_to[1] + size * math.sin(a))), fill=fill, width=width)


def _wood(W, H, seed, base=(92, 58, 34)):
    import numpy as np
    import cv2
    rnd = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    warp = cv2.resize(rnd.normal(0, 1, (H // 60 + 2, W // 60 + 2)).astype("float32"), (W, H),
                      interpolation=cv2.INTER_CUBIC)
    grain = np.sin((yy + warp * 25 + xx * 0.04) * 0.09) * 0.5 + np.sin((yy + warp * 60) * 0.023) * 0.5
    fine = cv2.GaussianBlur(rnd.normal(0, 1, (H, W)).astype("float32"), (0, 0), sigmaX=8, sigmaY=0.8)
    v = 1 + grain * 0.13 + fine * 0.6
    a = np.array(base, "float32")[None, None, :] * v[..., None]
    for k in range(1, 4):  # стыки досок
        y = int(H * k / 4 + rnd.uniform(-40, 40))
        a[y - 2:y + 2] *= 0.45
    return a


def _shadow_paste(base, card, xy, angle, blur=14, off=(14, 18), dark=0.55):
    """Предмет с мягкой тенью; base — float-массив, card — PIL RGB."""
    import numpy as np
    import cv2
    from PIL import Image
    cr = card.convert("RGBA").rotate(angle, resample=3, expand=True)
    alpha = np.asarray(cr)[..., 3].astype("float32") / 255
    rgb = np.asarray(cr)[..., :3].astype("float32")
    H, W = base.shape[:2]
    x0, y0 = xy
    h, w = alpha.shape
    sh = np.zeros((H, W), "float32")
    sx, sy = x0 + off[0], y0 + off[1]
    sh[max(sy, 0):sy + h, max(sx, 0):sx + w] = alpha[max(-sy, 0):H - sy, max(-sx, 0):W - sx][:min(h, H - sy), :min(w, W - sx)]
    sh = cv2.GaussianBlur(sh, (0, 0), blur)
    base = base * (1 - dark * sh[..., None])
    region = base[y0:y0 + h, x0:x0 + w]
    a = alpha[:region.shape[0], :region.shape[1], None]
    region[:] = region * (1 - a) + rgb[:region.shape[0], :region.shape[1]] * a
    return base


def _blur(im, r):
    from PIL import ImageFilter
    return im.filter(ImageFilter.GaussianBlur(r))


def _noise(a, sigma, seed):
    import numpy as np
    return a + np.random.default_rng(seed).normal(0, sigma, a.shape[:2])[..., None]


# ─── 61. комикс ────────────────────────────────────────────────────────

def _bubble(d, box, tail, lines, font, lead):
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    # хвост
    d.polygon([(cx - 22, (y1 + y2) / 2 + (y2 - y1) * 0.3), (cx + 22, (y1 + y2) / 2 + (y2 - y1) * 0.3), tail],
              fill=(255, 255, 255), outline=(0, 0, 0))
    d.line(((cx - 22, (y1 + y2) / 2 + (y2 - y1) * 0.36), tail), fill=(0, 0, 0), width=4)
    d.line(((cx + 22, (y1 + y2) / 2 + (y2 - y1) * 0.36), tail), fill=(0, 0, 0), width=4)
    d.ellipse(box, fill=(255, 255, 255), outline=(0, 0, 0), width=4)
    y = (y1 + y2) / 2 - lead * len(lines) / 2 + 2
    for ln in lines:
        _ctext(d, cx, y, ln, font, (15, 15, 15))
        y += lead


def _figure(d, x, y, s, shirt, hair, rnd, flip=False, arm_up=False):
    k = -1 if flip else 1
    d.line((x, y + 70 * s, x, y + 190 * s), fill=(20, 20, 20), width=int(6 * s))
    d.polygon([(x - 38 * s, y + 85 * s), (x + 38 * s, y + 85 * s), (x + 30 * s, y + 175 * s),
               (x - 30 * s, y + 175 * s)], fill=shirt, outline=(20, 20, 20))
    d.line((x - 10 * s, y + 175 * s, x - 22 * s, y + 280 * s), fill=(20, 20, 20), width=int(9 * s))
    d.line((x + 10 * s, y + 175 * s, x + 24 * s, y + 280 * s), fill=(20, 20, 20), width=int(9 * s))
    d.line((x - 30 * s * k, y + 95 * s, x - 60 * s * k, y + 160 * s), fill=(20, 20, 20), width=int(7 * s))
    if arm_up:
        d.line((x + 30 * s * k, y + 95 * s, x + 75 * s * k, y + 30 * s), fill=(20, 20, 20), width=int(7 * s))
    else:
        d.line((x + 30 * s * k, y + 95 * s, x + 62 * s * k, y + 160 * s), fill=(20, 20, 20), width=int(7 * s))
    d.ellipse((x - 40 * s, y - 10 * s, x + 40 * s, y + 72 * s), fill=(250, 214, 178), outline=(20, 20, 20), width=4)
    d.chord((x - 42 * s, y - 14 * s, x + 42 * s, y + 50 * s), 180, 360, fill=hair, outline=(20, 20, 20))
    d.ellipse((x + 6 * s * k - 5, y + 25 * s - 5, x + 6 * s * k + 5, y + 25 * s + 5), fill=(0, 0, 0))
    d.ellipse((x + 24 * s * k - 5, y + 25 * s - 5, x + 24 * s * k + 5, y + 25 * s + 5), fill=(0, 0, 0))
    mx = x + 15 * s * k
    d.arc((mx - 16 * s, y + 36 * s, mx + 16 * s, y + 58 * s), 20, 160, fill=(0, 0, 0), width=3)


def hard_comic(path):
    from PIL import Image, ImageDraw
    import numpy as np
    rnd = random.Random(61)
    W, H = 1560, 780
    im = Image.new("RGB", (W, H), (248, 244, 232))
    d = ImageDraw.Draw(im)
    pw, gap, top = 490, 25, 25
    bg = [(196, 226, 240), (250, 218, 170), (200, 232, 196)]
    panels = []
    for k in range(3):
        x1 = gap + k * (pw + gap) - 5
        box = (x1, top, x1 + pw, H - top)
        panels.append(box)
        d.rectangle(box, fill=bg[k])
        # полутон
        for yy in range(box[1] + 10, box[3], 18):
            for xx in range(box[0] + 10 + (yy // 18 % 2) * 9, box[2], 18):
                d.ellipse((xx - 2, yy - 2, xx + 2, yy + 2), fill=tuple(max(0, c - 22) for c in bg[k]))
        d.line((box[0], box[3] - 150, box[2], box[3] - 150), fill=(120, 90, 60), width=3)  # пол
    # полка на 1 и 2
    for k in (0, 1):
        x1 = panels[k][0]
        d.rectangle((x1 + 300, 330, x1 + 470, 344), fill=(140, 95, 55), outline=(30, 20, 10))
        d.rectangle((x1 + 400, 290, x1 + 430, 330), fill=(190, 110, 70), outline=(30, 20, 10))
        d.ellipse((x1 + 398, 255, x1 + 432, 296), fill=(80, 160, 80), outline=(20, 60, 20), width=2)
    fb = _font("dejavu", 24)
    fbb = _font("dejavub", 24)
    # панель 1
    p = panels[0]
    _figure(d, p[0] + 110, 400, 1.0, (220, 70, 60), (90, 60, 30), rnd)
    _figure(d, p[0] + 330, 410, 0.95, (90, 110, 210), (40, 30, 30), rnd, flip=True)
    d.rectangle((p[0] + 12, p[1] + 12, p[0] + 300, p[1] + 62), fill=(255, 236, 120), outline=(0, 0, 0), width=3)
    d.text((p[0] + 24, p[1] + 22), "Понедельник, 8:15.", font=_font("dejavub", 22), fill=(0, 0, 0))
    _bubble(d, (p[0] + 15, 90, p[0] + 255, 220), (p[0] + 120, 390), ["Ты не видела", "мои ключи?"], fb, 30)
    _bubble(d, (p[0] + 230, 210, p[0] + 482, 330), (p[0] + 320, 400), ["На полке, рядом", "с кактусом."], fb, 30)
    # панель 2
    p = panels[1]
    _figure(d, p[0] + 200, 400, 1.0, (220, 70, 60), (90, 60, 30), rnd, arm_up=True)
    cx, cy = p[0] + 160, 170
    for (dx, dy, r) in [(-95, 0, 55), (-40, -40, 60), (35, -40, 60), (95, 0, 55), (40, 35, 58), (-40, 35, 58), (0, 0, 70)]:
        d.ellipse((cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r), fill=(255, 255, 255), outline=(0, 0, 0), width=4)
    for (dx, dy, r) in [(-95, 0, 51), (-40, -40, 56), (35, -40, 56), (95, 0, 51), (40, 35, 54), (-40, 35, 54), (0, 0, 66)]:
        d.ellipse((cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r), fill=(255, 255, 255))
    for (dx, dy, r) in [(20, 120, 14), (30, 160, 9), (38, 190, 6)]:
        d.ellipse((cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r), fill=(255, 255, 255), outline=(0, 0, 0), width=3)
    _ctext(d, cx, cy - 32, "Какой ещё", _font("dejavu", 25), (15, 15, 15))
    _ctext(d, cx, cy + 2, "кактус?..", _font("dejavu", 25), (15, 15, 15))
    # звук — падение полки
    for k in range(12):
        a = k * math.pi / 6
        d.line((p[0] + 400, 360, p[0] + 400 + 70 * math.cos(a), 360 + 70 * math.sin(a)), fill=(240, 60, 30), width=5)
    _rtext(im, (p[0] + 300, 570), "ГРОХ!", _font("dejavub", 92), (255, 220, 40), -12, stroke=6, stroke_fill=(0, 0, 0))
    # панель 3
    p = panels[2]
    _figure(d, p[0] + 120, 400, 1.0, (220, 70, 60), (90, 60, 30), rnd)
    _figure(d, p[0] + 360, 410, 0.95, (90, 110, 210), (40, 30, 30), rnd, flip=True)
    d.rectangle((p[0] + 60, p[3] - 135, p[0] + 230, p[3] - 120), fill=(140, 95, 55), outline=(30, 20, 10))
    d.ellipse((p[0] + 250, p[3] - 150, p[0] + 285, p[3] - 118), fill=(80, 160, 80), outline=(20, 60, 20), width=2)
    _bubble(d, (p[0] + 230, 80, p[0] + 482, 210), (p[0] + 350, 400), ["Вот теперь", "ты их нашёл."], fb, 30)
    _bubble(d, (p[0] + 12, 210, p[0] + 232, 330), (p[0] + 110, 395), ["И кактус", "тоже..."], fb, 30)
    d.rectangle((p[2] - 240, p[3] - 62, p[2] - 12, p[3] - 12), fill=(255, 236, 120), outline=(0, 0, 0), width=3)
    d.text((p[2] - 226, p[3] - 52), "Конец выпуска.", font=_font("dejavub", 21), fill=(0, 0, 0))
    for p in panels:
        d.rectangle(p, outline=(0, 0, 0), width=6)
    d.text((W - 300, H - 22), "© Студия «Ёжик», 2026", font=_font("dejavu", 15), fill=(90, 80, 70))
    a = _noise(_np(im), 3, 61)
    _img(a).save(str(path))


# ─── 62. диаграмма ─────────────────────────────────────────────────────

def hard_chart(path):
    from PIL import Image, ImageDraw
    W, H = 1400, 980
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    _ctext(d, W / 2, 28, "Outpatient visits by district, 2025", _font("sansb", 34), (30, 30, 40))
    _ctext(d, W / 2, 78, "Thousands of visits per quarter (provisional data)", _font("sans", 20), (100, 100, 110))
    x0, y0, x1, y1 = 170, 140, 1150, 700  # область графика
    vmax = 60
    for v in range(0, vmax + 1, 10):
        y = y1 - (y1 - y0) * v / vmax
        d.line((x0, y, x1, y), fill=(225, 225, 230) if v else (60, 60, 60), width=1 if v else 2)
        t = str(v)
        d.text((x0 - 12 - d.textlength(t, font=_font("sans", 18)), y - 12), t, font=_font("sans", 18), fill=(70, 70, 80))
    d.line((x0, y0, x0, y1), fill=(60, 60, 60), width=2)
    _rtext(im, (95, (y0 + y1) / 2), "Visits (thousands)", _font("sans", 22), (50, 50, 60), 90)
    regions = ["North Valley", "Eastbrook Heights", "Old Harbour", "Pinecrest", "Riverside South", "Millford Plains"]
    q1 = [42.5, 31.0, 27.4, 18.9, 49.2, 22.6]
    q2 = [38.1, 35.7, 29.9, 21.3, 53.8, 19.4]
    cols = [(46, 104, 170), (231, 140, 52)]
    gw = (x1 - x0) / len(regions)
    fv = _font("sans", 15)
    for i, name in enumerate(regions):
        gx = x0 + gw * i + gw * 0.15
        bw = gw * 0.33
        for s, val in enumerate((q1[i], q2[i])):
            bx = gx + s * (bw + 4)
            by = y1 - (y1 - y0) * val / vmax
            d.rectangle((bx, by, bx + bw, y1 - 1), fill=cols[s])
            t = ("%.1f" % val)
            d.text((bx + bw / 2 - d.textlength(t, font=fv) / 2, by - 22), t, font=fv, fill=(40, 40, 50))
        # подпись под 45°
        lay = _layer_text(name, _font("sans", 19), (40, 40, 50)).rotate(45, resample=3, expand=True)
        cx = gx + bw + 2
        im.paste(lay, (int(cx - lay.width + 14), y1 + 4), lay)
    _ctext(d, (x0 + x1) / 2, 900, "District", _font("sans", 22), (50, 50, 60))
    # легенда
    d.rectangle((1180, 160, 1385, 270), fill=(250, 250, 252), outline=(160, 160, 170), width=1)
    d.text((1195, 168), "Quarter", font=_font("sansb", 18), fill=(40, 40, 50))
    for s, lab in enumerate(["Q1 (Jan–Mar)", "Q2 (Apr–Jun)"]):
        d.rectangle((1195, 202 + s * 32, 1217, 222 + s * 32), fill=cols[s])
        d.text((1226, 199 + s * 32), lab, font=_font("sans", 17), fill=(40, 40, 50))
    d.text((40, H - 40), "Source: Westmarch Regional Health Office, quarterly bulletin No. 7 (2026). Figures rounded.",
           font=_font("sans", 15), fill=(120, 120, 130))
    im = im.resize((int(W * 0.9), int(H * 0.9)), 1).resize((W, H), 1)
    im.save(str(path))


# ─── 63. маркерная доска ───────────────────────────────────────────────

def hard_whiteboard(path):
    from PIL import Image, ImageDraw
    import numpy as np
    import cv2
    rnd = random.Random(63)
    W, H = 1600, 1100
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    a = np.stack([228 - yy * 0.02 + xx * 0.005] * 3, -1)
    a[..., 2] += 4
    im = _img(_noise(a, 2.5, 63))
    d = ImageDraw.Draw(im)
    blue, red, green = (25, 55, 160), (190, 30, 35), (20, 120, 60)
    # следы стёртого
    ghost = (205, 207, 212)
    _ink(im, ["задача 4 — перенести", "звонок в пятницу"], "hand", 44, 980, 820, 60, ghost, jitter=0.1, seed=3)
    _ink(im, ["План запуска — март"], "hand", 78, 120, 70, 90, blue, jitter=0.06, seed=1)
    _wobble(d, [(120, 172), (760, 166)], blue, 5, rnd)
    boxes = [(110, 260, 470, 400, "Исследование", "рынка"), (600, 260, 960, 400, "Прототип", "(2 недели)"),
             (1060, 260, 1500, 400, "Тест", "с пользователями")]
    for (x1, y1, x2, y2, t1, t2) in boxes:
        _wobble(d, [(x1, y1), (x2, y1 + 4), (x2 - 3, y2), (x1 + 3, y2 - 2), (x1, y1)], blue, 5, rnd, 3)
        _ink(im, [t1, t2], "hand", 43, x1 + 24, y1 + 18, 56, blue, jitter=0.08, seed=x1)
    for (sx, ex) in [(475, 595), (965, 1055)]:
        _wobble(d, [(sx, 330), (ex, 334)], (30, 30, 35), 5, rnd)
        _arrowhead(d, (sx, 330), (ex, 334), (30, 30, 35), 26, 5)
    _ink(im, ["Срок: до 14.03 !!"], "hand", 58, 1040, 450, 60, red, jitter=0.1, seed=4)
    _wobble(d, [(1030, 530), (1400, 524)], red, 4, rnd)
    _wobble(d, [(1030, 542), (1380, 538)], red, 4, rnd)
    _ink(im, ["Кто что делает:", "— бюджет: 120 тыс.", "— Катя Лунина: дизайн", "— Олег Пастухов: сервер",
              "— созвон по вторникам, 10:00"], "hand", 46, 130, 500, 66, green, jitter=0.12, seed=5)
    _wobble(d, [(1460, 405), (1465, 600), (1330, 660)], red, 5, rnd)
    _arrowhead(d, (1465, 600), (1330, 660), red, 24, 5)
    _ink(im, ["риск: мало", "участников"], "hand", 42, 1100, 640, 52, red, jitter=0.12, seed=6)
    # магниты
    for (mx, my, mc) in [(60, 60, (230, 60, 60)), (1540, 70, (60, 120, 230))]:
        d.ellipse((mx - 18, my - 18, mx + 18, my + 18), fill=mc)
    # рама и стена
    big = Image.new("RGB", (W + 160, H + 160), (176, 160, 140))
    dd = ImageDraw.Draw(big)
    dd.rectangle((60, 60, W + 100, H + 100), fill=(170, 172, 176))
    dd.rectangle((66, 66, W + 94, H + 94), fill=(205, 207, 210))
    big.paste(im, (80, 80))
    dd.rectangle((200, H + 100, W - 100, H + 122), fill=(160, 162, 166))  # полочка
    dd.rectangle((420, H + 86, 520, H + 104), fill=(30, 60, 170))
    dd.rectangle((560, H + 88, 650, H + 104), fill=(190, 30, 35))
    a = _np(big.resize((W, H), 1))
    # блик
    g = np.exp(-(((xx - 1150) / 230) ** 2 + ((yy - 300) / 150) ** 2))
    a = a + g[..., None] * 70
    a = a * (1 - 0.18 * (xx / W))[..., None]  # свет слева
    a = _perspective(a, 0.11, 63)
    im = _blur(_img(_noise(a, 4, 64)), 1.3)
    _jpeg(im, 60).save(str(path), quality=72)


# ─── 64. скриншот мессенджера ──────────────────────────────────────────

def _ticks(d, x, y, col):
    d.line((x, y + 6, x + 4, y + 10, x + 11, y + 1), fill=col, width=2)
    d.line((x + 6, y + 9, x + 7, y + 10, x + 15, y + 1), fill=col, width=2)


def hard_chat(path):
    from PIL import Image, ImageDraw
    W, H = 900, 1600
    im = Image.new("RGB", (W, H), (228, 221, 210))
    d = ImageDraw.Draw(im)
    rnd = random.Random(64)
    for _ in range(140):  # узор фона
        x, y, r = rnd.uniform(0, W), rnd.uniform(140, H - 120), rnd.uniform(6, 16)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(216, 208, 196), width=2)
    # статус-бар и шапка
    d.rectangle((0, 0, W, 150), fill=(36, 112, 96))
    f_st = _font("sansb", 22)
    d.text((34, 10), "9:41", font=f_st, fill=(255, 255, 255))
    d.text((W - 210, 12), "LTE", font=_font("sansb", 18), fill=(255, 255, 255))
    for k in range(4):
        d.rectangle((W - 160 + k * 9, 30 - k * 5, W - 154 + k * 9, 32), fill=(255, 255, 255))
    d.rectangle((W - 100, 14, W - 50, 34), outline=(255, 255, 255), width=2)
    d.rectangle((W - 97, 17, W - 64, 31), fill=(255, 255, 255))
    d.rectangle((W - 48, 20, W - 44, 28), fill=(255, 255, 255))
    d.line((30, 95, 46, 80, 30, 95, 46, 110), fill=(255, 255, 255), width=4)
    d.ellipse((70, 62, 136, 128), fill=(232, 170, 120))
    _ctext(d, 103, 76, "АБ", _font("sansb", 26), (255, 255, 255))
    d.text((152, 64), "Анна Белова", font=_font("sansb", 30), fill=(255, 255, 255))
    d.text((152, 104), "была в сети в 9:38", font=_font("sans", 20), fill=(205, 232, 225))
    y = 175
    _ctext(d, W / 2, y, "Сегодня", _font("sans", 19), (110, 100, 90))
    y += 50
    msgs = [
        ("L", "Доброе утро! Ты уже отправил отчёт за сентябрь?", "9:02"),
        ("R", "Привет! Почти, осталось сверить таблицу с расходами.", "9:05"),
        ("L", "Не забудь приложить акты от «Зелёной долины», без них бухгалтерия не примет.", "9:06"),
        ("Q", ("Анна Белова", "Не забудь приложить акты от «Зелёной долины»…"),
         "Акты лежат в общей папке, я их уже подписал 👍".replace(" 👍", "."), "9:11"),
        ("L", "Отлично. Совещание перенесли на четверг, 15:30, кабинет 214.", "9:14"),
        ("R", "Понял, буду. Захвачу ноутбук с презентацией.", "9:15"),
        ("L", "И купи, пожалуйста, воды в офис — кулер пустой 🙂".replace(" 🙂", "!"), "9:20"),
        ("R", "Хорошо, после обеда.", "9:21"),
        ("L", "Кстати, Тимур Рашидович просил перезвонить ему до обеда, номер у тебя есть.", "9:34"),
        ("R", "Есть. Позвоню в 11:30.", "9:36"),
    ]
    fm = _font("sans", 25)
    fs = _font("sans", 16)
    for m in msgs:
        kind = m[0]
        text = m[2] if kind == "Q" else m[1]
        tm = m[3] if kind == "Q" else m[2]
        lines = _wrap(d, text, fm, 520)
        tw = max(d.textlength(l, font=fm) for l in lines)
        qh = 0
        if kind == "Q":
            qname, qtext = m[1]
            qlines = _wrap(d, qtext, _font("sans", 20), 480)
            qh = 32 + 26 * len(qlines) + 24
            tw = max(tw, max(d.textlength(l, font=_font("sans", 20)) for l in qlines) + 22)
        bw = tw + 40 + 70
        bh = qh + 34 * len(lines) + 30
        right = kind in ("R", "Q")
        x1 = W - 24 - bw if right else 24
        col = (220, 248, 198) if right else (255, 255, 255)
        d.rounded_rectangle((x1, y, x1 + bw, y + bh), 18, fill=col)
        d.rounded_rectangle((x1 + 2, y + bh - 2, x1 + bw - 2, y + bh + 2), 18, fill=(205, 198, 188))
        d.rounded_rectangle((x1, y, x1 + bw, y + bh), 18, fill=col)
        ty = y + 12
        if kind == "Q":
            d.rectangle((x1 + 12, y + 12, x1 + bw - 12, y + qh), fill=(204, 234, 186))
            d.rectangle((x1 + 12, y + 12, x1 + 17, y + qh), fill=(36, 140, 110))
            d.text((x1 + 26, y + 16), qname, font=_font("sansb", 19), fill=(36, 140, 110))
            qy = y + 44
            for ql in qlines:
                d.text((x1 + 26, qy), ql, font=_font("sans", 20), fill=(90, 100, 90))
                qy += 26
            ty = y + qh + 10
        for l in lines:
            d.text((x1 + 20, ty), l, font=fm, fill=(20, 20, 20))
            ty += 34
        d.text((x1 + bw - (78 if right else 58), y + bh - 26), tm, font=fs, fill=(120, 130, 120))
        if right:
            _ticks(d, x1 + bw - 34, y + bh - 24, (52, 150, 230))
        y += bh + 18
    # строка ввода
    d.rectangle((0, H - 110, W, H), fill=(240, 236, 230))
    d.rounded_rectangle((20, H - 92, W - 110, H - 22), 35, fill=(255, 255, 255))
    d.text((70, H - 72), "Сообщение", font=_font("sans", 26), fill=(160, 160, 160))
    d.ellipse((W - 94, H - 96, W - 20, H - 22), fill=(36, 112, 96))
    d.rectangle((W - 62, H - 78, W - 52, H - 52), fill=(255, 255, 255))
    d.ellipse((W - 66, H - 84, W - 48, H - 64), fill=(255, 255, 255))
    _jpeg(im, 80).save(str(path))


# ─── 65. разворот книги ────────────────────────────────────────────────

BOOK_L = ("Дом стоял у самой реки, и по утрам туман поднимался прямо к окнам. Матвей Ильич просыпался раньше всех, "
          "ставил чайник и долго смотрел, как над водой тянутся белые полосы. Ему нравилось это время: ни звонков, "
          "ни соседей, только редкий крик чайки да шорох камыша. Внучка приезжала по субботам, привозила свежий хлеб "
          "и газеты, которые он всё равно не читал. Они садились на крыльцо, и она рассказывала о городе, о своей "
          "работе в библиотеке, о том, что весной снова поднимут цены на проезд. Он слушал, кивал и думал, что жизнь "
          "в городе похожа на реку в половодье: всё куда-то несётся, и никто не знает куда.\n"
          "Вечерами он чинил сети, хотя рыбу давно не ловил. Соседка, Варвара Никитична, приносила ему пироги с капустой "
          "и каждый раз спрашивала, не собирается ли он продать дом. «Куда мне ехать? — отвечал он. — Здесь каждая доска "
          "моя». Она вздыхала и уходила, оставляя пироги на подоконнике.")
BOOK_R = ("В тот год лето выдалось сухим. Река обмелела, и у старой пристани показались почерневшие сваи, о которых "
          "давно никто не помнил. Мальчишки из соседней деревни бегали туда искать монеты, а однажды притащили "
          "ржавый колокольчик с надписью, которую никто не смог разобрать. Матвей Ильич долго вертел его в руках, "
          "потом отнёс в сарай и положил на верхнюю полку, рядом с банками гвоздей. «Пусть полежит, — сказал он "
          "внучке. — Вещи сами расскажут, когда придёт время». Она засмеялась, но вечером, уезжая, всё-таки "
          "оглянулась на сарай, будто ожидала услышать тихий звон.\n"
          "Осенью пошли дожди, и река вернулась к своим берегам. Сваи скрылись под водой, мальчишки разъехались по "
          "школам, и о колокольчике все забыли. Только однажды ночью Матвею Ильичу почудилось, что из сарая доносится "
          "лёгкий, едва различимый звук, похожий на чей-то далёкий смех.")


def _book_page(text, head, num, W, H, left):
    from PIL import Image, ImageDraw
    import numpy as np
    pa = _paper(W, H, (240, 232, 214), 65 + left, 3)
    im = _img(pa * 0.45 + np.array([240, 232, 214], 'float32') * 0.55)
    d = ImageDraw.Draw(im)
    fh = _font("serif", 20)
    fb = _font("serif", 23)
    mx_in, mx_out = 70, 90
    xl = mx_out if left else mx_in
    xr = W - (mx_in if left else mx_out)
    _ctext(d, (xl + xr) / 2, 60, head, fh, (90, 80, 70))
    d.line((xl, 92, xr, 92), fill=(150, 140, 120), width=1)
    y = 130
    for k, para in enumerate(text.split("\n")):
        lines = _wrap(d, " " + para, fb, xr - xl)
        for i, ln in enumerate(lines):
            if i < len(lines) - 1:  # выключка по ширине
                words = ln.split(" ")
                gaps = len(words) - 1
                tw = sum(d.textlength(w, font=fb) for w in words)
                sp = (xr - xl - tw) / max(gaps, 1)
                x = xl
                for w in words:
                    d.text((x, y), w, font=fb, fill=(35, 30, 28))
                    x += d.textlength(w, font=fb) + sp
            else:
                d.text((xl, y), ln, font=fb, fill=(35, 30, 28))
            y += 36
    _ctext(d, (xl + xr) / 2, H - 70, str(num), fh, (90, 80, 70))
    return _np(im)


def hard_book_curl(path):
    import numpy as np
    import cv2
    PW, PH = 760, 1080
    L = _book_page(BOOK_L, "Глава третья. Дом у реки", 48, PW, PH, 1)
    R = _book_page(BOOK_R, "Тихие берега", 49, PW, PH, 0)
    spread = np.concatenate([L, R], 1)
    W, H = spread.shape[1], spread.shape[0]
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    g = W / 2
    dist = np.abs(xx - g) / g  # 0 у корешка, 1 у края
    curl = np.exp(-dist / 0.18)
    # строки изгибаются к корешку: вертикальный сдвиг растёт к краям страницы по высоте
    map_y = yy + curl * 38 * ((yy - H / 2) / (H / 2)) - curl * 14 + (dist ** 2) * 10
    map_x = g + np.sign(xx - g) * (np.abs(xx - g) + curl * 40)
    warped = cv2.remap(spread, map_x.astype("float32"), map_y.astype("float32"), cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    shade = 1 - 0.55 * np.exp(-dist / 0.07) - 0.12 * np.exp(-dist / 0.25)
    warped = warped * shade[..., None]
    # стол и края страниц
    CW, CH = W + 240, H + 220
    canvas = _wood(CW, CH, 65, (70, 45, 28))
    pad = np.zeros((H + 16, W + 24, 3), "float32") + np.array([215, 205, 185], "float32")
    pad[8:8 + H, 12:12 + W] = warped
    mask = np.zeros((CH, CW), "float32")
    ox, oy = 108, 100
    mask[oy:oy + H + 16, ox:ox + W + 24] = 1
    sh = cv2.GaussianBlur(np.roll(np.roll(mask, 20, 0), 14, 1), (0, 0), 18)
    canvas = canvas * (1 - 0.6 * sh[..., None])
    region = canvas[oy:oy + H + 16, ox:ox + W + 24]
    m = (pad.sum(2) > 5).astype("float32")[..., None]
    region[:] = region * (1 - m) + pad * m
    # тёплый свет сверху справа
    yy2, xx2 = np.mgrid[0:CH, 0:CW].astype("float32")
    light = 0.72 + 0.4 * np.exp(-(((xx2 - CW * 0.7) / (CW * 0.6)) ** 2 + ((yy2 - CH * 0.1) / (CH * 0.8)) ** 2))
    canvas = canvas * light[..., None] * np.array([1.06, 0.98, 0.84], "float32")
    canvas = _perspective(canvas, 0.06, 65)
    im = _img(_noise(canvas, 5, 65)).resize((CW * 1400 // CW, CH * 1400 // CW), 1)
    _jpeg(_blur(im, 0.6), 62).save(str(path), quality=74)


# ─── 66. визитки ───────────────────────────────────────────────────────

def _card_front():
    from PIL import Image, ImageDraw
    W, H = 900, 520
    im = Image.new("RGB", (W, H), (250, 249, 245))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 26, H), fill=(18, 84, 120))
    d.polygon([(700, 40), (780, 40), (820, 110), (740, 110)], fill=(18, 84, 120))
    d.polygon([(760, 40), (840, 40), (880, 110), (800, 110)], fill=(230, 150, 40))
    d.text((70, 52), "ООО «Северный мост»", font=_font("sansb", 30), fill=(18, 84, 120))
    d.text((70, 92), "проектирование и надзор", font=_font("sans", 22), fill=(110, 110, 115))
    d.text((70, 190), "Игорь Самойлов", font=_font("serifb", 54), fill=(25, 25, 30))
    d.text((70, 262), "Ведущий инженер-сметчик", font=_font("sans", 28), fill=(80, 80, 85))
    d.line((70, 318, 830, 318), fill=(200, 200, 205), width=2)
    ys = 340
    for t in ["+7 (912) 405-18-77", "i.samoylov@sevmost-proekt.ru", "г. Пермь, ул. Лесная, 14, оф. 302"]:
        d.ellipse((72, ys + 10, 84, ys + 22), fill=(230, 150, 40))
        d.text((100, ys), t, font=_font("sans", 26), fill=(40, 40, 45))
        ys += 46
    return im


def _card_back():
    from PIL import Image, ImageDraw
    W, H = 900, 520
    im = Image.new("RGB", (W, H), (18, 84, 120))
    d = ImageDraw.Draw(im)
    d.text((60, 44), "Наши услуги", font=_font("sansb", 40), fill=(255, 255, 255))
    d.line((60, 104, 360, 104), fill=(230, 150, 40), width=5)
    items = ["Сметы на строительство и ремонт", "Технический надзор за объектами",
             "Обследование мостов и эстакад", "Экспертиза проектной документации",
             "Консультации по ценообразованию"]
    y = 134
    for t in items:
        d.rectangle((64, y + 12, 76, y + 24), fill=(230, 150, 40))
        d.text((96, y), t, font=_font("sans", 29), fill=(240, 244, 248))
        y += 52
    d.text((60, H - 62), "Работаем по всему Уралу · Пн–Пт 9:00–18:00", font=_font("sans", 22), fill=(170, 205, 225))
    return im


def hard_business_card(path):
    import numpy as np
    W, H = 1600, 1100
    a = _wood(W, H, 66, (60, 38, 24))
    s = 0.74
    f = _card_front().resize((int(900 * s), int(520 * s)), 1)
    b = _card_back().resize((int(900 * s), int(520 * s)), 1)
    a = _shadow_paste(a, f, (120, 140), 7)
    a = _shadow_paste(a, b, (760, 520), -11)
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    light = 0.62 + 0.5 * np.exp(-(((xx - 700) / 900) ** 2 + ((yy - 400) / 700) ** 2))
    a = a * light[..., None] * np.array([1.05, 0.99, 0.9], "float32")
    a = _perspective(a, 0.05, 66)
    im = _blur(_img(_noise(a, 6, 66)), 0.7)
    _jpeg(im, 58).save(str(path), quality=70)


# ─── 67. объявление в тени ─────────────────────────────────────────────

def hard_shadow_doc(path):
    from PIL import Image, ImageDraw
    import numpy as np
    import cv2
    DW, DH = 1100, 1520
    doc = Image.new("RGB", (DW, DH), (252, 252, 250))
    d = ImageDraw.Draw(doc)
    _ctext(d, DW / 2, 80, "ОБЪЯВЛЕНИЕ", _font("sansb", 64), (20, 20, 20))
    _ctext(d, DW / 2, 170, "для жителей домов № 12, 14 и 16 по ул. Садовой", _font("sans", 28), (40, 40, 40))
    body = ("Уважаемые жильцы! В связи с плановой заменой труб горячего водоснабжения подача воды будет "
            "временно прекращена по следующему графику. Просим заранее сделать запас воды и не оставлять "
            "открытыми краны. По всем вопросам обращайтесь в диспетчерскую управляющей компании.")
    y = 250
    for ln in _wrap(d, body, _font("serif", 30), DW - 180):
        d.text((90, y), ln, font=_font("serif", 30), fill=(30, 30, 30))
        y += 46
    y += 30
    cols = [90, 330, 640, DW - 90]
    rows = [("Дата", "Время", "Дома"), ("14 октября", "09:00 – 18:00", "№ 12"), ("15 октября", "09:00 – 20:00", "№ 14"),
            ("16 октября", "10:00 – 17:00", "№ 16"), ("17 октября", "09:00 – 13:00", "все дома")]
    for r, row in enumerate(rows):
        if r == 0:
            d.rectangle((cols[0], y, cols[-1], y + 60), fill=(225, 225, 225))
        for k, v in enumerate(row):
            d.text((cols[k] + 16, y + 12), v, font=_font("sansb" if r == 0 else "sans", 28), fill=(20, 20, 20))
        d.line((cols[0], y, cols[-1], y), fill=(40, 40, 40), width=2)
        y += 60
    d.line((cols[0], y, cols[-1], y), fill=(40, 40, 40), width=2)
    for x in cols:
        d.line((x, y - 60 * len(rows), x, y), fill=(40, 40, 40), width=2)
    y += 50
    more = ("Во время работ возможны кратковременные отключения холодной воды. Перед подачей горячей воды "
            "рекомендуем слить воду в течение 3–5 минут. Приносим извинения за временные неудобства.")
    for ln in _wrap(d, more, _font("serif", 30), DW - 180):
        d.text((90, y), ln, font=_font("serif", 30), fill=(30, 30, 30))
        y += 46
    y += 40
    for ln in ["Диспетчерская: 8 (843) 277-41-09 (круглосуточно)", "ООО «УК Уютный квартал»", "10.10.2026"]:
        d.text((90, y), ln, font=_font("sans", 28), fill=(30, 30, 30))
        y += 46
    # на доске: снимок с телефона
    W, H = 1300, 1700
    a = np.zeros((H, W, 3), "float32") + np.array([120, 100, 78], "float32")
    a = _noise(a, 8, 67)
    a[100:100 + DH, 100:100 + DW] = _np(doc)
    for (px, py) in [(130, 130), (DW + 70, 130)]:  # кнопки
        cv2.circle(a, (px, py), 14, (200, 40, 40), -1)
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    # диагональная тень от руки/телефона
    t = (xx * 0.62 + yy * 0.78 - 820) / 70
    shadow = 1 / (1 + np.exp(-t))
    blob = np.exp(-(((xx - 1000) / 420) ** 2 + ((yy - 1450) / 330) ** 2))
    k = np.clip(shadow * 0.62 + blob * 0.15, 0, 0.75)
    a = a * (1 - k[..., None])
    a = a * (0.72 + 0.15 * (1 - yy / H))[..., None] * np.array([1.0, 0.95, 0.82], "float32")
    a = _perspective(a, 0.09, 67)
    a = _noise(a, 11, 68)
    im = _blur(_img(a), 1.0).resize((1100, 1438), 1)
    _jpeg(im, 52).save(str(path), quality=64)


# ─── 68. уличный указатель KK/RU ───────────────────────────────────────

def hard_street_bilingual(path):
    from PIL import Image, ImageDraw
    import numpy as np
    W, H = 1500, 1050
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    sky = np.stack([120 + yy * 0.12, 165 + yy * 0.07, 225 - yy * 0.02], -1)
    a = sky.copy()
    rnd = np.random.default_rng(68)
    # облака
    import cv2
    cl = cv2.GaussianBlur(rnd.normal(0, 1, (H // 30 + 2, W // 30 + 2)).astype("float32"), (0, 0), 1.2)
    cl = cv2.resize(cl, (W, H), interpolation=cv2.INTER_CUBIC)
    a += np.clip(cl * 60, 0, 70)[..., None]
    im = _img(a)
    d = ImageDraw.Draw(im)
    # здание справа: кирпич и окна
    d.rectangle((980, 120, W, H), fill=(176, 104, 78))
    for yb in range(120, H, 22):
        off = 0 if (yb // 22) % 2 else 24
        for xb in range(980 - off, W, 48):
            d.rectangle((max(xb, 980), yb, xb + 46, yb + 20), outline=(150, 86, 64))
    for wy in (190, 470, 750):
        for wx in (1040, 1260):
            d.rectangle((wx, wy, wx + 150, wy + 200), fill=(60, 80, 100), outline=(235, 230, 220), width=10)
            d.line((wx + 75, wy, wx + 75, wy + 200), fill=(235, 230, 220), width=6)
    d.rectangle((0, 900, 980, H), fill=(110, 112, 110))  # тротуар/дорога вдали
    # столб
    d.rectangle((560, 200, 600, H), fill=(120, 124, 128))
    d.rectangle((566, 200, 576, H), fill=(165, 168, 172))
    # главная табличка
    d.rounded_rectangle((150, 230, 980, 520), 18, fill=(20, 82, 160), outline=(245, 245, 245), width=10)
    _ctext(d, 480, 268, "Көктерек көшесі", _font("sansb", 74), (255, 255, 255))
    d.line((230, 382, 810, 382), fill=(200, 215, 235), width=3)
    _ctext(d, 480, 398, "улица Коктерек", _font("sans", 62), (255, 255, 255))
    # стрелка
    d.polygon([(850, 330), (930, 380), (850, 430), (850, 400), (820, 400), (820, 360), (850, 360)], fill=(255, 255, 255))
    d.text((180, 470), "1–47", font=_font("sansb", 30), fill=(200, 215, 235))
    # малая табличка
    d.rectangle((260, 600, 900, 790), fill=(245, 245, 240), outline=(30, 120, 70), width=8)
    d.rectangle((268, 608, 360, 782), fill=(30, 120, 70))
    d.rectangle((300, 660, 328, 730), fill=(255, 255, 255))
    d.rectangle((279, 681, 349, 709), fill=(255, 255, 255))
    d.text((380, 622), "Қалалық емхана №4", font=_font("sansb", 40), fill=(20, 60, 40))
    d.text((380, 676), "Городская поликлиника №4", font=_font("sans", 34), fill=(20, 60, 40))
    d.polygon([(380, 748), (404, 732), (404, 742), (440, 742), (440, 754), (404, 754), (404, 764)], fill=(200, 40, 30))
    d.text((452, 726), "250 м", font=_font("sansb", 36), fill=(200, 40, 30))
    d.text((600, 742), "тәулік бойы / круглосуточно", font=_font("sans", 19), fill=(80, 90, 80))
    a = _np(im)
    # грязь и блики солнца на табличке
    sg = _stains(a[230:800, 150:990].copy(), 3, 68, col=(90, 90, 80), alpha=0.12)
    a[230:800, 150:990] = sg
    g = np.exp(-(((xx - 330) / 160) ** 2 + ((yy - 300) / 90) ** 2))
    a += g[..., None] * 60
    a = _perspective(a, 0.18, 68)
    im = _blur(_img(_noise(a, 7, 68)), 0.9)
    _jpeg(im, 55).save(str(path), quality=66)


# ─── 69. печать и подпись поверх строк ─────────────────────────────────

def _ring_text(lay, cx, cy, r, text, font, fill, start=-90):
    from PIL import ImageDraw
    d = ImageDraw.Draw(lay)
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths)
    ang = start - math.degrees(total / r) / 2 + 0
    ang = start
    step_total = 360.0
    scale = step_total / math.degrees(total / r)
    a = start
    for ch, w in zip(text, widths):
        da = math.degrees(w / r) * scale
        mid = a + da / 2
        x = cx + r * math.cos(math.radians(mid))
        y = cy + r * math.sin(math.radians(mid))
        g = _layer_text(ch, font, fill, pad=4).rotate(-(mid + 90), resample=3, expand=True)
        lay.paste(g, (int(x - g.width / 2), int(y - g.height / 2)), g)
        a += da


def hard_stamp_overlap(path):
    from PIL import Image, ImageDraw
    import numpy as np
    import cv2
    W, H = 1240, 1600
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    f = _font("serif", 27)
    _ctext(d, W / 2, 80, "КОМИТЕТ ПО ДЕЛАМ МОЛОДЁЖИ", _font("serifb", 34), (20, 20, 20))
    _ctext(d, W / 2, 128, "администрации города Северодольска", _font("serif", 26), (20, 20, 20))
    _ctext(d, W / 2, 168, "ул. Заречная, 3, г. Северодольск, 624110 · тел. (34396) 2-41-18", _font("serif", 20), (60, 60, 60))
    d.line((100, 210, W - 100, 210), fill=(20, 20, 20), width=3)
    d.text((100, 240), "Исх. № 214/07 от 12.09.2026", font=f, fill=(20, 20, 20))
    for i, t in enumerate(["Директору МБУ «Дом творчества»", "Л. Р. Огородниковой"]):
        d.text((660, 300 + i * 40), t, font=f, fill=(20, 20, 20))
    _ctext(d, W / 2, 430, "Уважаемая Лидия Романовна!", _font("serifb", 28), (20, 20, 20))
    body = [
        "Комитет по делам молодёжи сообщает, что городской фестиваль «Северное сияние» состоится "
        "26 сентября 2026 года на площади Победы с 11:00 до 19:00.",
        "Просим направить для участия в фестивале творческие коллективы учреждения и до 19 сентября "
        "представить заявку с указанием числа участников и необходимого оборудования.",
        "Контактное лицо: главный специалист комитета Вершинина Ольга Петровна, тел. 2-41-25.",
    ]
    y = 500
    for para in body:
        for k, ln in enumerate(_wrap(d, para, f, W - 260)):
            d.text((100 + (50 if k == 0 else 0), y), ln, font=f, fill=(20, 20, 20))
            y += 44
        y += 14
    y += 90
    sig_y = y
    d.text((100, sig_y), "Председатель комитета", font=f, fill=(20, 20, 20))
    d.line((520, sig_y + 34, 800, sig_y + 34), fill=(20, 20, 20), width=1)
    d.text((840, sig_y), "А. В. Кравцова", font=f, fill=(20, 20, 20))
    d.text((100, H - 120), "Исп.: Вершинина О. П., 2-41-25", font=_font("serif", 20), fill=(60, 60, 60))
    # печать
    S = 380
    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    blue = (30, 60, 170, 255)
    c = S // 2
    ld.ellipse((8, 8, S - 8, S - 8), outline=blue, width=7)
    ld.ellipse((60, 60, S - 60, S - 60), outline=blue, width=3)
    _ring_text(lay, c, c, 151, "КОМИТЕТ ПО ДЕЛАМ МОЛОДЁЖИ * Г. СЕВЕРОДОЛЬСК * ", _font("sansb", 26), blue)
    for i, t in enumerate(["ДЛЯ", "ДОКУМЕНТОВ"]):
        w = ld.textlength(t, font=_font("sansb", 30))
        ld.text((c - w / 2, c - 40 + i * 42), t, font=_font("sansb", 30), fill=blue)
    ld.line((c - 90, c - 50, c + 90, c - 50), fill=blue, width=2)
    ld.line((c - 90, c + 46, c + 90, c + 46), fill=blue, width=2)
    lay = lay.rotate(14, resample=3)
    al = np.asarray(lay)[..., 3].astype("float32") / 255
    rnd = np.random.default_rng(69)
    tex = cv2.GaussianBlur(rnd.uniform(0, 1, al.shape).astype("float32"), (0, 0), 3)
    al = al * np.clip(0.45 + tex * 0.9, 0, 0.88)
    a = _np(im)
    sx, sy = 640, sig_y - 230
    reg = a[sy:sy + S, sx:sx + S]
    ink = np.array([40, 70, 180], "float32")
    reg[:] = reg * (1 - al[..., None]) + np.minimum(reg, ink) * al[..., None]
    # подпись синей ручкой поверх фамилии
    sig = np.zeros((H, W), "float32")
    pts = []
    for t in np.linspace(0, 1, 420):
        ph = t * 2 * math.pi * 7.5
        amp = 34 * (1 - 0.55 * t) * (1.3 if t < 0.15 else 1.0)
        x = 600 + t * 470 + 22 * math.cos(ph)
        yv = sig_y + 20 - amp * math.sin(ph) - t * 26
        pts.append((x, yv))
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        cv2.line(sig, (int(x1), int(y1)), (int(x2), int(y2)), 1.0, 2, cv2.LINE_AA)
    cv2.line(sig, (600, sig_y + 50), (1100, sig_y - 5), 1.0, 2, cv2.LINE_AA)
    k = (cv2.GaussianBlur(sig, (0, 0), 0.7) * 0.85)[..., None]
    a = a * (1 - k) + np.array([20, 40, 140], "float32") * k
    a = _noise(a, 2, 69)
    _img(a).save(str(path))


# ─── 70. винная этикетка ───────────────────────────────────────────────

def _wine_label():
    from PIL import Image, ImageDraw
    W, H = 900, 1000
    import numpy as np
    a = np.zeros((H, W, 3), "float32") + np.array([92, 18, 32], "float32")
    a = _noise(a, 5, 70)
    im = _img(a)
    d = ImageDraw.Draw(im)
    gold = (214, 180, 96)
    gold2 = (180, 145, 70)
    d.rectangle((22, 22, W - 22, H - 22), outline=gold, width=5)
    d.rectangle((38, 38, W - 38, H - 38), outline=gold2, width=2)
    for (cx, cy) in [(38, 38), (W - 38, 38), (38, H - 38), (W - 38, H - 38)]:
        d.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline=gold, width=3)
    # герб
    cx = W / 2
    d.polygon([(cx - 60, 90), (cx + 60, 90), (cx + 60, 160), (cx, 210), (cx - 60, 160)], outline=gold, width=4)
    d.line((cx - 60, 135, cx + 60, 135), fill=gold, width=3)
    d.ellipse((cx - 14, 100, cx + 14, 128), fill=gold)
    for k in range(5):
        d.ellipse((cx - 30 + k * 13, 150 + (k % 2) * 8, cx - 20 + k * 13, 160 + (k % 2) * 8), fill=gold)
    _ctext(d, cx, 240, "GRAND VIN", _font("old", 34), gold)
    _ctext(d, cx, 300, "Château", _font("oldb", 96), gold)
    _ctext(d, cx, 410, "Morvelle", _font("oldb", 110), gold)
    d.line((200, 560, 700, 560), fill=gold2, width=2)
    _ctext(d, cx, 580, "Appellation Côtes de Lavrenne Contrôlée", _font("old", 32), gold)
    _ctext(d, cx, 640, "Cuvée « Les Vieilles Pierres »", _font("old", 36), gold)
    _ctext(d, cx, 710, "2019", _font("oldb", 84), (232, 202, 120))
    _ctext(d, cx, 820, "Mis en bouteille au château", _font("old", 28), gold2)
    f = _font("old", 19)
    _ctext(d, cx, 880, "SCEA Domaine de Morvelle · 33780 Lavrenne · Produit de France", f, gold2)
    _ctext(d, cx, 908, "75 cl     13,5 % vol.     Contient des sulfites", f, gold2)
    return _np(im)


def hard_wine_label(path):
    import numpy as np
    import cv2
    W, H = 1200, 1500
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    rnd = np.random.default_rng(70)
    a = np.zeros((H, W, 3), "float32") + np.array([28, 22, 20], "float32")
    for _ in range(18):  # боке
        cx, cy, r = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(40, 120)
        col = np.array(rnd.choice([[200, 150, 80], [150, 110, 70], [90, 70, 60]]), "float32")
        a += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (r * r))[..., None] * col * 0.35
    # бутылка: цилиндр
    bx0, bx1 = 300, 900
    bc, br = (bx0 + bx1) / 2, (bx1 - bx0) / 2
    u = np.clip((xx - bc) / br, -1, 1)
    inside = (np.abs(xx - bc) < br) & (yy > 120)
    neck = (np.abs(xx - bc) < 90) & (yy <= 120)
    sh = np.sqrt(np.clip(1 - u ** 2, 0, 1))
    bottle = np.stack([18 + 30 * sh, 34 + 40 * sh, 22 + 28 * sh], -1)
    hl = np.exp(-((u + 0.45) / 0.07) ** 2) * 120
    bottle += hl[..., None]
    m = (inside | neck)[..., None]
    a = np.where(m, bottle, a)
    # этикетка на цилиндре
    lab = _wine_label()
    LH, LW = lab.shape[:2]
    th = math.radians(80)
    ow = int(2 * br * math.sin(th))
    oh = LH + 60
    oy, oxx = np.mgrid[0:oh, 0:ow].astype("float32")
    uu = (oxx - ow / 2) / (br)
    phi = np.arcsin(np.clip(uu, -1, 1))
    srcx = (phi / th + 1) / 2 * LW
    srcy = oy - 55 * (1 - np.cos(phi))
    warped = cv2.remap(lab, srcx.astype("float32"), srcy.astype("float32"), cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    valid = ((srcx >= 0) & (srcx < LW) & (srcy >= 0) & (srcy < LH)).astype("float32")
    shade = (np.cos(phi) ** 0.9) * 0.9 + 0.1
    warped = warped * shade[..., None]
    warped += (np.exp(-((uu + 0.45) / 0.06) ** 2) * 55)[..., None]
    ly, lx = 360, int(bc - ow / 2)
    reg = a[ly:ly + oh, lx:lx + ow]
    reg[:] = reg * (1 - valid[..., None]) + warped * valid[..., None]
    a = a * (0.78 + 0.3 * np.exp(-(((xx - 500) / 700) ** 2)))[..., None]
    im = _blur(_img(_noise(a, 6, 71)), 0.8)
    _jpeg(im, 60).save(str(path), quality=70)


RECIPES = [
    ("61_comic", "png", hard_comic, "RU", "EN", "original",
     "ТРУДНО: комикс в три кадра — пузыри реплик, облако мыслей, звук под углом, плашки"),
    ("62_chart_png", "png", hard_chart, "EN", "RU", "original",
     "ТРУДНО: столбчатая диаграмма картинкой — ось Y повёрнута, подписи X под 45°, легенда, значения"),
    ("63_whiteboard", "jpg", hard_whiteboard, "RU", "EN", "original",
     "ТРУДНО: снимок маркерной доски — рука тремя цветами, рамки и стрелки, блик, перспектива"),
    ("64_chat_screenshot", "png", hard_chat, "RU", "UZ", "original",
     "ТРУДНО: скриншот мессенджера — пузыри, время, цитата внутри ответа, строка ввода"),
    ("65_book_curl", "jpg", hard_book_curl, "RU", "EN", "original",
     "ТРУДНО: снимок разворота книги — строки изогнуты к корешку, тень корешка, тёплый свет"),
    ("66_business_card", "jpg", hard_business_card, "RU", "EN", "original",
     "ТРУДНО: две визитки на деревянном столе под углом — мелкий текст, тени"),
    ("67_shadow_doc", "jpg", hard_shadow_doc, "RU", "EN", "original",
     "ТРУДНО: объявление снято телефоном — диагональная тень, мало света, шум, таблица"),
    ("68_street_bilingual", "jpg", hard_street_bilingual, "KK", "RU", "original",
     "ТРУДНО: уличный указатель KK/RU под углом — русская строка уже на языке перевода, стрелки"),
    ("69_stamp_overlap", "png", hard_stamp_overlap, "RU", "EN", "original",
     "ТРУДНО: письмо с синей печатью поверх строк (текст по кольцу) и подписью через фамилию"),
    ("70_wine_label", "jpg", hard_wine_label, "FR", "RU", "original",
     "ТРУДНО: этикетка вина на бутылке — изгиб цилиндра, золото на бордо, мелкий текст внизу"),
]
