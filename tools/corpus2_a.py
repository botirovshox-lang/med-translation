import sys, random, math; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_build import F, _rl_fonts, _wrap, _para, _font, _np, _img, _paper, _stains, _ink, _skew, _perspective, _jpeg

"""Корпус, вторая партия (41–50): плотные векторные PDF, трудные для выгрузки
«как в оригинале» — инфографика годового отчёта, научный постер, обтекание
круглой картинки, договор со сносками, таблица с повёрнутыми заголовками,
блок-схема, этикетка, анализы, календарь, резюме с тёмной колонкой.

Все тексты, имена и организации выдуманы для корпуса. Шрифты — только из
frontend/vendor/fonts/sub (TTF: reportlab .otf не берёт).
"""

FONTS = Path(__file__).resolve().parent.parent / "frontend" / "vendor" / "fonts" / "sub"
_EXTRA = {
    "sanscb": FONTS / "NotoSans-CondensedBold.ttf",
    "sansxc": FONTS / "NotoSans-ExtraCondensed.ttf",
    "sansxcb": FONTS / "NotoSans-ExtraCondensedBold.ttf",
}


def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    _rl_fonts()
    for k, p in _EXTRA.items():
        try:
            pdfmetrics.getFont(k)
        except KeyError:
            pdfmetrics.registerFont(TTFont(k, str(p)))


def _canvas(path, size):
    from reportlab.pdfgen import canvas
    _fonts()
    c = canvas.Canvas(str(path), pagesize=size)
    c.setTitle(Path(path).stem)
    return c


def _sw(t, f, s):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return stringWidth(t, f, s)


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _fill(c, h):
    c.setFillColorRGB(*(_hex(h) if isinstance(h, str) else h))


def _stroke(c, h):
    c.setStrokeColorRGB(*(_hex(h) if isinstance(h, str) else h))


def _text(c, x, y, t, f="sans", s=9, col="#1a1a1a", align="left"):
    _fill(c, col)
    c.setFont(f, s)
    if align == "center":
        c.drawCentredString(x, y, t)
    elif align == "right":
        c.drawRightString(x, y, t)
    else:
        c.drawString(x, y, t)


def _lines(c, x, y, lines, f, s, lead, col="#1a1a1a", align="left", w=0):
    for ln in lines:
        _text(c, x + (w / 2 if align == "center" else w if align == "right" else 0), y, ln, f, s, col, align)
        y -= lead
    return y


# ─── богатый текст: **жирный**, ^1 надстрочный знак ──────────────────────

def _rich_tokens(text, reg, bold):
    """Слова как списки кусков (текст, шрифт, надстрочный?). Пунктуация после
    закрывающего ** и надстрочная сноска приклеиваются к слову без пробела."""
    words = []
    b = False
    parts = text.split("**")
    for k, part in enumerate(parts):
        f = bold if b else reg
        glue = k > 0 and part[:1] not in ("", " ") and parts[k - 1][-1:] not in ("", " ")
        for j, w in enumerate(part.split()):
            pieces = []
            if "^" in w:
                base, _, rest = w.partition("^")
                n = len(rest) - len(rest.lstrip("0123456789"))
                if base:
                    pieces.append((base, f, False))
                pieces.append((rest[:n], reg, True))
                if rest[n:]:
                    pieces.append((rest[n:], reg, False))
            else:
                pieces.append((w, f, False))
            if j == 0 and glue and words:
                words[-1] += pieces
            else:
                words.append(pieces)
        b = not b
    return words


def _rich(c, text, x, y, width, size=9.5, lead=None, reg="serif", bold="serifb", first=0.0,
          col="#1a1a1a", justify=True):
    """Абзац с жирными определёнными терминами и надстрочными сносками.
    first — сдвиг первой строки (висячий отступ задаётся x/first вызывающим)."""
    lead = lead or size * 1.32
    words = _rich_tokens(text, reg, bold)
    sp = _sw(" ", reg, size)

    def ww(word):
        return sum(_sw(t, f, size * (0.62 if s else 1)) for t, f, s in word)

    lines, cur, curw = [], [], 0.0
    for wd in words:
        avail = width - (first if not lines else 0)
        add = ww(wd) + (sp if cur else 0)
        if cur and curw + add > avail:
            lines.append((cur, curw))
            cur, curw = [wd], ww(wd)
        else:
            cur.append(wd)
            curw += add
    if cur:
        lines.append((cur, curw))
    _fill(c, col)
    for k, (ln, lw) in enumerate(lines):
        xx = x + (first if k == 0 else 0)
        avail = width - (first if k == 0 else 0)
        gap = sp
        if justify and k < len(lines) - 1 and len(ln) > 1:
            gap = sp + (avail - lw) / (len(ln) - 1)
        cx = xx
        for wd in ln:
            for t, f, s in wd:
                if s:
                    c.setFont(f, size * 0.62)
                    c.drawString(cx, y + size * 0.38, t)
                    cx += _sw(t, f, size * 0.62)
                else:
                    c.setFont(f, size)
                    c.drawString(cx, y, t)
                    cx += _sw(t, f, size)
            cx += gap
        y -= lead
    return y


# ═══ 41. Годовой отчёт: KPI, столбцы, круговая ═══════════════════════════

AR = {
    "company": "АО «Лазурная гавань»",
    "title": "Годовой отчёт 2025",
    "kpi": [("4,82", "млрд ₽", "Выручка", "+12,4 % к 2024 г."),
            ("1,07", "млрд ₽", "EBITDA", "рентабельность 22,2 %"),
            ("318", "тыс.", "Клиентов", "+41 тыс. за год"),
            ("1 940", "чел.", "Сотрудников", "в 7 регионах")],
    "intro": ("В 2025 году компания продолжила расширение сети терминалов и впервые "
              "превысила отметку в 4,8 млрд рублей выручки. Рост обеспечили новые "
              "контракты на перевалку контейнеров и запуск складского комплекса "
              "в Северной промзоне. Долговая нагрузка снизилась до 1,3× EBITDA."),
    "bars": [("2021", 2.91), ("2022", 3.24), ("2023", 3.88), ("2024", 4.29), ("2025", 4.82)],
    "quarters": [("I кв.", 1.02), ("II кв.", 1.17), ("III кв.", 1.29), ("IV кв.", 1.34)],
    "pie": [("Перевалка контейнеров", 46, "#1f4e79"), ("Складская логистика", 24, "#2e86ab"),
            ("Железнодорожные перевозки", 15, "#7fb7be"), ("Таможенное оформление", 9, "#f4a259"),
            ("Прочие услуги", 6, "#bc4b51")],
    "events": [("Февраль", "Подписан контракт с линией «Остров-Шиппинг» на 5 лет"),
               ("Апрель", "Открыт складской комплекс «Северный» на 42 тыс. м²"),
               ("Июнь", "Выпуск облигаций на 1,5 млрд руб. под 11,2 %"),
               ("Сентябрь", "Запущены контейнерные поезда до Кедровска"),
               ("Декабрь", "Рекордная перевалка: 612 тыс. TEU за год")],
    "regions": [("Центральный", "1 612", "+9 %"), ("Северо-Западный", "1 104", "+15 %"),
                ("Южный", "873", "+18 %"), ("Приволжский", "702", "+7 %"),
                ("Уральский", "529", "+11 %")],
}


def _ar_header(c, W, H, page):
    _fill(c, "#0f2d4a")
    c.rect(0, H - 64, W, 64, fill=1, stroke=0)
    _fill(c, "#f4a259")
    c.rect(0, H - 68, W, 4, fill=1, stroke=0)
    _text(c, 40, H - 32, AR["title"].upper(), "sansb", 18, "#ffffff")
    _text(c, 40, H - 50, AR["company"], "sans", 9.5, "#c9d6e3")
    _text(c, W - 40, H - 40, "Ключевые результаты", "sans", 9, "#c9d6e3", "right")
    c.setLineWidth(0.4)
    _stroke(c, "#b0b8c0")
    c.line(40, 38, W - 40, 38)
    _text(c, 40, 26, AR["company"] + " · " + AR["title"], "sans", 7, "#6b7580")
    _text(c, W - 40, 26, str(page), "sansb", 8, "#0f2d4a", "right")


def pdf_annual_report(path):
    from reportlab.lib.pagesizes import A4
    c = _canvas(path, A4)
    W, H = A4
    _ar_header(c, W, H, 1)
    # плитки KPI
    tw, th, gap = (W - 80 - 3 * 10) / 4, 88, 10
    y0 = H - 92 - th
    cols = ["#1f4e79", "#2e86ab", "#3c9d9b", "#bc4b51"]
    for i, (num, unit, cap, sub) in enumerate(AR["kpi"]):
        x = 40 + i * (tw + gap)
        _fill(c, "#f2f5f8")
        c.roundRect(x, y0, tw, th, 6, fill=1, stroke=0)
        _fill(c, cols[i])
        c.rect(x, y0 + th - 5, tw, 5, fill=1, stroke=0)
        _text(c, x + 10, y0 + th - 22, cap.upper(), "sansb", 7.5, "#5a6570")
        _text(c, x + 10, y0 + 32, num, "sansb", 26, cols[i])
        _text(c, x + 12 + _sw(num, "sansb", 26), y0 + 32, unit, "sans", 9, cols[i])
        _text(c, x + 10, y0 + 14, sub, "sans", 7, "#4a5560")
    y = _para(c, AR["intro"], 40, y0 - 24, W - 80, "serif", 10, 14, align="justify")
    # столбцы: выручка по годам
    _text(c, 40, y - 14, "Выручка, млрд руб.", "sansb", 11, "#0f2d4a")
    _text(c, 40, y - 27, "Консолидированные данные по МСФО¹", "sans", 7.5, "#6b7580")
    cx0, cy0, cw, ch = 74, y - 250, 260, 190
    _stroke(c, "#d5dbe0")
    c.setLineWidth(0.4)
    for k in range(6):
        yy = cy0 + ch * k / 5
        c.line(cx0, yy, cx0 + cw, yy)
        _text(c, cx0 - 6, yy - 3, f"{k:d},0", "sans", 7, "#5a6570", "right")
    c.saveState()
    c.translate(46, cy0 + ch / 2)
    c.rotate(90)
    _text(c, 0, 0, "млрд руб.", "sans", 7, "#5a6570", "center")
    c.restoreState()
    bw = cw / len(AR["bars"]) * 0.56
    for i, (yr, v) in enumerate(AR["bars"]):
        x = cx0 + cw / len(AR["bars"]) * (i + 0.22)
        h = ch * v / 5
        _fill(c, "#f4a259" if i == len(AR["bars"]) - 1 else "#2e86ab")
        c.rect(x, cy0, bw, h, fill=1, stroke=0)
        _text(c, x + bw / 2, cy0 + h + 4, f"{v:.2f}".replace(".", ","), "sansb", 8, "#1a1a1a", "center")
        _text(c, x + bw / 2, cy0 - 12, yr, "sans", 8, "#3a4550", "center")
    _stroke(c, "#3a4550")
    c.setLineWidth(0.8)
    c.line(cx0, cy0, cx0 + cw, cy0)
    # справа: поквартальная разбивка 2025 горизонтальными полосами
    rx = 370
    _text(c, rx, y - 14, "Выручка 2025 по кварталам", "sansb", 11, "#0f2d4a")
    _text(c, rx, y - 27, "млрд руб., без НДС", "sans", 7.5, "#6b7580")
    for i, (q, v) in enumerate(AR["quarters"]):
        yy = y - 62 - i * 34
        _text(c, rx, yy + 4, q, "sans", 8.5, "#3a4550")
        _fill(c, "#e3e8ec")
        c.rect(rx + 42, yy, 130, 14, fill=1, stroke=0)
        _fill(c, "#1f4e79")
        c.rect(rx + 42, yy, 130 * v / 1.6, 14, fill=1, stroke=0)
        _text(c, rx + 46 + 130 * v / 1.6, yy + 4, f"{v:.2f}".replace(".", ","), "sansb", 8, "#1a1a1a")
    yy = y - 62 - 4 * 34 + 6
    _fill(c, "#fff4e8")
    c.roundRect(rx, yy - 52, W - 40 - rx, 48, 4, fill=1, stroke=0)
    _para(c, "IV квартал стал рекордным: 1,34 млрд руб. благодаря сезонному росту импорта.",
          rx + 8, yy - 18, W - 56 - rx, "sans", 8, 10.5, color=(0.35, 0.22, 0.05))
    # легенда столбцов
    ly = cy0 - 34
    _fill(c, "#2e86ab")
    c.rect(cx0, ly, 9, 9, fill=1, stroke=0)
    _text(c, cx0 + 13, ly + 1.5, "Фактические данные", "sans", 7.5, "#3a4550")
    _fill(c, "#f4a259")
    c.rect(cx0 + 110, ly, 9, 9, fill=1, stroke=0)
    _text(c, cx0 + 123, ly + 1.5, "Отчётный год", "sans", 7.5, "#3a4550")
    # лента событий года
    ty = ly - 40
    _text(c, 40, ty, "Ключевые события 2025 года", "sansb", 11, "#0f2d4a")
    tl = ty - 92
    _stroke(c, "#0f2d4a")
    c.setLineWidth(2)
    c.line(50, tl, W - 50, tl)
    n = len(AR["events"])
    for i, (mon, txt) in enumerate(AR["events"]):
        x = 70 + i * (W - 140) / (n - 1)
        up = i % 2 == 0
        _fill(c, "#f4a259" if i == n - 1 else "#2e86ab")
        c.circle(x, tl, 6, fill=1, stroke=0)
        _fill(c, "#ffffff")
        c.circle(x, tl, 2.4, fill=1, stroke=0)
        _stroke(c, "#9aa5ae")
        c.setLineWidth(0.6)
        c.line(x, tl + (8 if up else -8), x, tl + (22 if up else -22))
        _text(c, x, tl + (28 if up else -34), mon, "sansb", 8.5, "#0f2d4a", "center")
        lines = _wrap(c, txt, "sans", 7.2, 104)
        yy = tl + (32 + 9 * len(lines) if up else -46)
        _lines(c, x, yy, lines, "sans", 7.2, 9, "#3a4550", "center")
    # сноска
    c.setLineWidth(0.4)
    _stroke(c, "#6b7580")
    c.line(40, 64, 140, 64)
    _para(c, "¹ Международные стандарты финансовой отчётности. Данные за 2021–2023 гг. пересчитаны "
             "с учётом присоединения ООО «Портовый склад».", 40, 54, W - 80, "sans", 6.5, 8,
          color=(0.35, 0.38, 0.42))
    c.showPage()

    # ── страница 2: круговая с выносками и таблица регионов ──
    _ar_header(c, W, H, 2)
    _text(c, 40, H - 100, "Структура выручки по сегментам", "sansb", 13, "#0f2d4a")
    _text(c, 40, H - 114, "доля в выручке 2025 г., %", "sans", 8, "#6b7580")
    pcx, pcy, r = W / 2, H - 270, 105
    ang = 90.0
    for name, pct, col in AR["pie"]:
        ext = -360 * pct / 100
        _fill(c, col)
        _stroke(c, "#ffffff")
        c.setLineWidth(1.5)
        c.wedge(pcx - r, pcy - r, pcx + r, pcy + r, ang, ext, fill=1, stroke=1)
        mid = math.radians(ang + ext / 2)
        if pct >= 9:
            _text(c, pcx + math.cos(mid) * r * 0.62, pcy + math.sin(mid) * r * 0.62 - 4,
                  f"{pct} %", "sansb", 10, "#ffffff", "center")
        # выноска
        p1 = (pcx + math.cos(mid) * (r + 2), pcy + math.sin(mid) * (r + 2))
        p2 = (pcx + math.cos(mid) * (r + 22), pcy + math.sin(mid) * (r + 22))
        right = math.cos(mid) >= 0
        p3 = (p2[0] + (18 if right else -18), p2[1])
        _stroke(c, "#5a6570")
        c.setLineWidth(0.6)
        c.line(*p1, *p2)
        c.line(*p2, *p3)
        _fill(c, "#5a6570")
        c.circle(*p1, 1.4, fill=1, stroke=0)
        tx = p3[0] + (4 if right else -4)
        _text(c, tx, p3[1] + 2, name, "sansb", 8, "#1a1a1a", "left" if right else "right")
        _text(c, tx, p3[1] - 8, f"{pct} % · {4.82 * pct / 100:.2f} млрд".replace(".", ","),
              "sans", 7, "#5a6570", "left" if right else "right")
        ang += ext
    _fill(c, "#ffffff")
    c.circle(pcx, pcy, 38, fill=1, stroke=0)
    _text(c, pcx, pcy + 2, "4,82", "sansb", 15, "#0f2d4a", "center")
    _text(c, pcx, pcy - 10, "млрд руб.", "sans", 7, "#5a6570", "center")
    # легенда
    ly = pcy - r - 52
    lx = 60
    for i, (name, pct, col) in enumerate(AR["pie"]):
        x = lx + (i % 3) * 165
        yy = ly - (i // 3) * 15
        _fill(c, col)
        c.rect(x, yy, 9, 9, fill=1, stroke=0)
        _text(c, x + 13, yy + 1.5, name, "sans", 7.5, "#3a4550")
    # таблица регионов
    ty = ly - 52
    _text(c, 40, ty, "Выручка по регионам присутствия", "sansb", 11, "#0f2d4a")
    ty -= 18
    heads = ["Регион", "Выручка, млн руб.", "Изменение", "Доля"]
    xs = [40, 250, 380, 470]
    _fill(c, "#0f2d4a")
    c.rect(40, ty - 5, W - 80, 17, fill=1, stroke=0)
    for h, x in zip(heads, xs):
        _text(c, x + 6, ty, h, "sansb", 8, "#ffffff")
    tot = sum(int(v.replace(" ", "")) for _, v, _ in AR["regions"])
    for i, (reg, v, d) in enumerate(AR["regions"]):
        ty -= 17
        if i % 2:
            _fill(c, "#f2f5f8")
            c.rect(40, ty - 5, W - 80, 17, fill=1, stroke=0)
        _text(c, xs[0] + 6, ty, reg + " федеральный округ" if i < 2 else reg, "sans", 8.5)
        _text(c, xs[2] - 20, ty, v, "sans", 8.5, align="right")
        _text(c, xs[3] - 20, ty, d, "sansb", 8.5, "#2a7a3a", "right")
        share = int(v.replace(" ", "")) / tot
        _fill(c, "#2e86ab")
        c.rect(xs[3] + 6, ty - 1, 60 * share * 2.5, 8, fill=1, stroke=0)
        _text(c, xs[3] + 10 + 60 * share * 2.5, ty, f"{share * 100:.0f} %", "sans", 7.5, "#3a4550")
    ty -= 6
    _stroke(c, "#0f2d4a")
    c.setLineWidth(0.8)
    c.line(40, ty - 4, W - 40, ty - 4)
    _text(c, xs[0] + 6, ty - 16, "Итого", "sansb", 8.5)
    _text(c, xs[2] - 20, ty - 16, f"{tot:,}".replace(",", " "), "sansb", 8.5, align="right")
    _para(c, "Прогноз на 2026 год предполагает рост выручки на 9–11 % при сохранении "
             "рентабельности EBITDA не ниже 21 %. Инвестиционная программа составит "
             "780 млн руб., из них 60 % — модернизация причального фронта²."
          , 40, ty - 44, W - 80, "serif", 9.5, 13, align="justify")
    fy = ty - 92
    _text(c, 40, fy, "Основные финансовые показатели, млн руб.", "sansb", 10, "#0f2d4a")
    fy -= 16
    fx = [40, 300, 380, 460]
    for k, h in enumerate(["Показатель", "2024", "2025", "Δ, %"]):
        _text(c, fx[k] + (0 if k == 0 else 60), fy, h, "sansb", 8, "#5a6570", "left" if k == 0 else "right")
    _stroke(c, "#0f2d4a")
    c.setLineWidth(0.6)
    c.line(40, fy - 4, 520, fy - 4)
    for row in [("Выручка", "4 290", "4 820", "+12,4"), ("Операционная прибыль", "712", "838", "+17,7"),
                ("Чистая прибыль", "402", "511", "+27,1"), ("Капитальные затраты", "655", "590", "−9,9")]:
        fy -= 12
        for k, t in enumerate(row):
            _text(c, fx[k] + (0 if k == 0 else 60), fy, t, "sans", 8.5,
                  ("#b03a3a" if t.startswith("−") else "#2a7a3a") if k == 3 else "#1a1a1a",
                  "left" if k == 0 else "right")
    c.setLineWidth(0.4)
    _stroke(c, "#6b7580")
    c.line(40, 64, 140, 64)
    _para(c, "² Решение об утверждении программы принято советом директоров 14 февраля 2026 г. "
             "(протокол № 3).", 40, 54, W - 80, "sans", 6.5, 8, color=(0.35, 0.38, 0.42))
    c.save()


# ═══ 42. Научный постер A3 альбомный, EN ════════════════════════════════

POSTER = {
    "title": "Seasonal Shifts in Juvenile Herring Feeding Grounds Along the Eastmere Coast",
    "authors": "Clara M. Ostrander¹, Tobias R. Wenning², Helga S. Varto¹, Priya N. Dalcourt³",
    "aff": ("¹ Northbrook Institute of Marine Biology, Harrowgate   ² Department of Ocean Sciences, "
            "University of Lennox Bay   ³ Coastal Fisheries Observatory, Port Aldwin"),
    "intro": ("Juvenile Atlantic herring depend on shallow coastal nurseries during their first two "
              "summers. Warming surface waters may push these nurseries northward, changing which "
              "bays support the next generation of the fishery. We combined eight years of trawl "
              "surveys with satellite sea-surface temperature to map how feeding grounds moved."),
    "aims": ["Quantify the northward displacement of nursery areas since 2016.",
             "Relate catch density to temperature and chlorophyll-a.",
             "Identify bays at risk of losing nursery function by 2035."],
    "methods": ("We sampled 46 fixed stations monthly from May to September (n = 1,812 hauls). "
                "Catch per unit effort (CPUE) was standardised to fish per 1,000 m³ filtered. "
                "Generalised additive models (GAM) tested the effects of SST, depth and "
                "chlorophyll-a, with station as a random effect."),
    "fig": "Figure 1. Centre of gravity of juvenile herring catches, 2016–2023. Each point is one "
           "survey season; the dashed line shows the linear trend (+6.8 km per year, R² = 0.81).",
    "results": ("Nursery centre of gravity moved 54 km north over eight seasons. CPUE peaked at "
                "11–13 °C and dropped sharply above 15 °C. Southern bays lost on average 38 % of "
                "their juvenile density, while two northern inlets became new hotspots."),
    "table": [("Region", "CPUE 2016", "CPUE 2023", "Change"),
              ("Southern bays", "412 ± 38", "255 ± 41", "−38 %"),
              ("Central shelf", "306 ± 27", "298 ± 30", "−3 %"),
              ("Northern inlets", "118 ± 19", "264 ± 33", "+124 %"),
              ("Outer islands", "87 ± 15", "131 ± 22", "+51 %")],
    "disc": ("The shift matches the 0.4 °C per decade warming of the coastal shelf. Gear and timing "
             "were unchanged, so sampling bias is unlikely to explain the trend."),
    "concl": ["Feeding grounds are shifting north at about 7 km per year.",
              "Temperature above 15 °C is the strongest predictor of nursery loss.",
              "Protection measures should follow the fish, not fixed boundaries."],
    "refs": ["1. Halvorsen K, Ibbet J. Thermal niches of clupeid larvae. Mar Ecol Prog Ser. 2019;612:45–58.",
             "2. Okonkwo A, et al. Satellite SST products for coastal ecology. Remote Sens Environ. 2021;256:112301.",
             "3. Brannigan L. Nursery habitat value in temperate estuaries. Fish Fish. 2018;19(4):702–719.",
             "4. Wood SN. Generalized Additive Models: An Introduction with R. 2nd ed. CRC Press; 2017."],
    "ack": "Acknowledgements: we thank the crews of RV Sandpiper and RV Gannet. Funded by the Eastmere "
           "Coastal Trust, grant ECT-2022-117.",
}


def _poster_head(c, x, y, w, t, col):
    _fill(c, col)
    c.roundRect(x, y - 6, w, 26, 4, fill=1, stroke=0)
    _text(c, x + 10, y + 2, t, "sansb", 15, "#ffffff")
    return y - 20


def _bullets(c, items, x, y, w, f="sans", s=11, lead=14.5, col="#1a1a1a", dot="#1f6f8b", gap=4):
    for it in items:
        _fill(c, dot)
        c.circle(x + 4, y + s * 0.33, s * 0.2, fill=1, stroke=0)
        y = _para(c, it, x + 14, y, w - 14, f, s, lead, color=_hex(col)) - gap
    return y


def pdf_poster_sci(path):
    from reportlab.lib.pagesizes import A3, landscape
    c = _canvas(path, landscape(A3))
    W, H = landscape(A3)
    _fill(c, "#eef3f6")
    c.rect(0, 0, W, H, fill=1, stroke=0)
    # полоса заголовка
    _fill(c, "#0b4f6c")
    c.rect(0, H - 130, W, 130, fill=1, stroke=0)
    _fill(c, "#20a39e")
    c.rect(0, H - 136, W, 6, fill=1, stroke=0)
    for i, (cx, lab) in enumerate([(70, "NIMB"), (W - 70, "CFO")]):
        _fill(c, "#ffffff")
        c.circle(cx, H - 65, 40, fill=1, stroke=0)
        _fill(c, "#0b4f6c")
        c.circle(cx, H - 65, 33, fill=0, stroke=0)
        _stroke(c, "#0b4f6c")
        c.setLineWidth(2)
        c.circle(cx, H - 65, 31, fill=0, stroke=1)
        _text(c, cx, H - 70, lab, "sansb", 12, "#0b4f6c", "center")
    lines = _wrap(c, POSTER["title"], "sansb", 30, W - 260)
    yy = H - 46 if len(lines) == 1 else H - 34
    for ln in lines:
        _text(c, W / 2, yy, ln, "sansb", 30, "#ffffff", "center")
        yy -= 34
    _text(c, W / 2, yy - 2, POSTER["authors"], "sans", 14, "#e2f1f4", "center")
    _text(c, W / 2, yy - 20, POSTER["aff"], "sans", 9.5, "#b8dbe3", "center")
    # 3 колонки
    m, g = 30, 24
    cw = (W - 2 * m - 2 * g) / 3
    top = H - 160
    xs = [m + i * (cw + g) for i in range(3)]
    for x in xs:
        _fill(c, "#ffffff")
        c.roundRect(x, 50, cw, top - 40, 8, fill=1, stroke=0)
    pad = 14
    # колонка 1
    x = xs[0] + pad
    w = cw - 2 * pad
    y = _poster_head(c, xs[0] + 8, top - 30, cw - 16, "Introduction", "#0b4f6c")
    y = _para(c, POSTER["intro"], x, y - 6, w, "sans", 11, 15, align="justify") - 10
    y = _poster_head(c, xs[0] + 8, y - 10, cw - 16, "Objectives", "#0b4f6c")
    y = _bullets(c, POSTER["aims"], x, y - 6, w) - 8
    y = _poster_head(c, xs[0] + 8, y - 10, cw - 16, "Methods", "#0b4f6c")
    y = _para(c, POSTER["methods"], x, y - 6, w, "sans", 11, 15, align="justify") - 8
    # карта станций — схема
    mh = y - 70
    _fill(c, "#d9ecf2")
    c.rect(x, 70, w, mh, fill=1, stroke=0)
    _fill(c, "#c8b98f")
    p = c.beginPath()
    p.moveTo(x + w, 70)
    pts = [(0.62, 0.0), (0.55, 0.2), (0.66, 0.38), (0.58, 0.55), (0.7, 0.72), (0.64, 1.0)]
    for fx, fy in pts:
        p.lineTo(x + w * fx, 70 + mh * fy)
    p.lineTo(x + w, 70 + mh)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    rng = random.Random(42)
    for k in range(46):
        sx = x + w * rng.uniform(0.08, 0.52)
        sy = 70 + mh * rng.uniform(0.1, 0.86)
        _fill(c, "#bc4b51")
        c.circle(sx, sy, 2.4, fill=1, stroke=0)
    _text(c, x + w * 0.8, 70 + mh * 0.5, "EASTMERE", "sansb", 9, "#6b5d3a", "center")
    _text(c, x + 8, 70 + mh - 14, "Survey stations (n = 46)", "sansb", 8.5, "#0b4f6c")
    _text(c, x + w * 0.3, 78, "North Sound", "sans", 8, "#0b4f6c", "center")
    # колонка 2: рисунок
    x = xs[1] + pad
    y = _poster_head(c, xs[1] + 8, top - 30, cw - 16, "Results", "#20a39e")
    y = _para(c, POSTER["results"], x, y - 6, w, "sans", 11, 15, align="justify") - 12
    fh = 215
    fy = y - fh
    _stroke(c, "#9aa7b0")
    c.setLineWidth(0.5)
    c.rect(x, fy, w, fh, fill=0, stroke=1)
    gx0, gy0, gw, gh = x + 50, fy + 40, w - 70, fh - 70
    for k in range(6):
        yy = gy0 + gh * k / 5
        c.setDash(2, 2)
        c.line(gx0, yy, gx0 + gw, yy)
        c.setDash()
        _text(c, gx0 - 6, yy - 3, f"{k * 12:.0f}", "sans", 8, "#4a5560", "right")
    yrs = list(range(2016, 2024))
    vals = [61, 66, 74, 80, 82, 95, 101, 114]
    for i, (yr, v) in enumerate(zip(yrs, vals)):
        px = gx0 + gw * (i + 0.5) / len(yrs)
        py = gy0 + gh * (v - 60) / 60
        _fill(c, "#0b4f6c")
        c.circle(px, py, 4.2, fill=1, stroke=0)
        _text(c, px, gy0 - 14, str(yr), "sans", 8, "#4a5560", "center")
    _stroke(c, "#bc4b51")
    c.setLineWidth(1.2)
    c.setDash(5, 3)
    c.line(gx0 + gw * 0.5 / 8, gy0 + gh * 0.0, gx0 + gw * 7.5 / 8, gy0 + gh * 0.89)
    c.setDash()
    c.saveState()
    c.translate(x + 14, gy0 + gh / 2)
    c.rotate(90)
    _text(c, 0, 0, "Latitude offset, km north of 2016 baseline", "sans", 8, "#4a5560", "center")
    c.restoreState()
    _text(c, gx0 + gw / 2, fy + 8, "Survey season", "sans", 8, "#4a5560", "center")
    _text(c, gx0 + 8, gy0 + gh - 10, "+6.8 km yr⁻¹", "sansb", 9, "#bc4b51")
    y = _para(c, POSTER["fig"], x, fy - 14, w, "sans", 9, 11.5, color=(0.3, 0.33, 0.36)) - 10
    # таблица
    _text(c, x, y - 4, "Table 1. Mean CPUE (fish per 1,000 m³) by region", "sansb", 10, "#0b4f6c")
    y -= 22
    cxs = [x, x + w * 0.42, x + w * 0.62, x + w * 0.84]
    for r, row in enumerate(POSTER["table"]):
        if r == 0:
            _fill(c, "#20a39e")
            c.rect(x, y - 5, w, 17, fill=1, stroke=0)
        elif r % 2 == 0:
            _fill(c, "#eef6f6")
            c.rect(x, y - 5, w, 17, fill=1, stroke=0)
        for k, (cx, t) in enumerate(zip(cxs, row)):
            f = "sansb" if r == 0 or k == 3 else "sans"
            col = "#ffffff" if r == 0 else ("#2a7a3a" if t.startswith("+") else "#b03a3a" if t.startswith("−") else "#1a1a1a")
            _text(c, cx + 4, y, t, f, 9, col)
        y -= 17
    _stroke(c, "#20a39e")
    c.setLineWidth(1)
    c.line(x, y + 12, x + w, y + 12)
    _text(c, x, y - 2, "Values are mean ± SE; change refers to 2023 vs 2016.", "sans", 7.5, "#5a6570")
    y = _poster_head(c, xs[1] + 8, y - 26, cw - 16, "Discussion", "#20a39e")
    _para(c, POSTER["disc"], x, y - 6, w, "sans", 11, 15, align="justify")
    # колонка 3
    x = xs[2] + pad
    y = _poster_head(c, xs[2] + 8, top - 30, cw - 16, "Temperature response", "#20a39e")
    # кривая отклика
    fh = 200
    fy = y - fh
    gx0, gy0, gw, gh = x + 34, fy + 28, w - 50, fh - 44
    _stroke(c, "#4a5560")
    c.setLineWidth(0.8)
    c.line(gx0, gy0, gx0 + gw, gy0)
    c.line(gx0, gy0, gx0, gy0 + gh)
    for k, t in enumerate(range(6, 20, 2)):
        px = gx0 + gw * k / 6
        _text(c, px, gy0 - 11, f"{t}", "sans", 8, "#4a5560", "center")
    _text(c, gx0 + gw / 2, fy + 2, "Sea-surface temperature, °C", "sans", 8, "#4a5560", "center")
    _fill(c, "#cfe9e8")
    p = c.beginPath()
    p2 = c.beginPath()
    pts = []
    for k in range(61):
        t = 6 + 12 * k / 60
        v = math.exp(-((t - 12) / 2.4) ** 2)
        pts.append((gx0 + gw * k / 60, gy0 + gh * v * 0.92))
    p.moveTo(gx0, gy0)
    for px, py in pts:
        p.lineTo(px, py)
    p.lineTo(gx0 + gw, gy0)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    p2.moveTo(*pts[0])
    for pt in pts[1:]:
        p2.lineTo(*pt)
    _stroke(c, "#0b4f6c")
    c.setLineWidth(1.6)
    c.drawPath(p2, fill=0, stroke=1)
    c.saveState()
    c.translate(x + 10, gy0 + gh / 2)
    c.rotate(90)
    _text(c, 0, 0, "Relative CPUE", "sans", 8, "#4a5560", "center")
    c.restoreState()
    _text(c, gx0 + gw * 0.5, gy0 + gh * 0.96, "optimum 11–13 °C", "sansb", 8.5, "#0b4f6c", "center")
    y = fy - 16
    y = _poster_head(c, xs[2] + 8, y - 6, cw - 16, "Conclusions", "#0b4f6c")
    y = _bullets(c, POSTER["concl"], x, y - 6, w, "sansb", 11.5, 15, dot="#20a39e") - 8
    # QR-заглушка
    q = 64
    qy = y - q - 6
    _fill(c, "#ffffff")
    c.rect(x, qy, q, q, fill=1, stroke=0)
    rng = random.Random(7)
    cell = q / 21
    for i in range(21):
        for j in range(21):
            fin = (i < 7 and j < 7) or (i < 7 and j > 13) or (i > 13 and j < 7)
            if fin:
                on = i in (0, 6, 14, 20) or j in (0, 6, 14, 20) or (2 <= i % 14 <= 4 and 2 <= j % 14 <= 4)
            else:
                on = rng.random() < 0.48
            if on:
                _fill(c, "#111111")
                c.rect(x + j * cell, qy + q - (i + 1) * cell, cell, cell, fill=1, stroke=0)
    _para(c, "Scan for the full dataset, model code and supplementary maps. Contact: "
             "c.ostrander@nimb.example.org", x + q + 10, qy + q - 10, w - q - 10, "sans", 9, 12)
    y = qy - 16
    _text(c, x, y, "References", "sansb", 9, "#0b4f6c")
    y -= 11
    for r in POSTER["refs"]:
        y = _para(c, r, x, y, w, "sans", 7, 8.6, color=(0.25, 0.27, 0.3)) - 1.5
    _para(c, POSTER["ack"], x, y - 6, w, "sans", 7, 8.6, color=(0.4, 0.42, 0.45))
    _text(c, W / 2, 22, "Eastmere Marine Science Symposium · 14–16 October 2026 · Poster P-27",
          "sans", 9, "#4a5560", "center")
    c.save()


# ═══ 43. Журнал: обтекание круга, буквица, вынос между колонками ════════

MAG = {
    "name": "СТРАННИК", "issue": "№ 10 · октябрь 2026",
    "rubric": "ПУТЕШЕСТВИЯ",
    "title": "Где зимуют облака",
    "lead": "Фотограф Варвара Леднёва провела месяц на высокогорном плато и вернулась с историей "
            "о людях, которые живут выше облаков.",
    "text": [
        "Дорога на плато начинается там, где кончается асфальт. Последние сорок километров "
        "водитель старенького внедорожника преодолевает почти шесть часов: колея петляет между "
        "валунами, переходит вброд ледяные ручьи и дважды теряется в каменистых осыпях. Когда "
        "машина наконец выезжает на ровную площадку, облака оказываются внизу, словно белое "
        "море, из которого торчат острова соседних вершин.",
        "В посёлке Верхний Брод живут двадцать три семьи. Зимой связь с долиной прерывается на "
        "несколько недель, и жители заранее запасают муку, соль, керосин и корм для скота. "
        "Электричество дают солнечные панели, установленные пять лет назад на средства "
        "районной программы. Школа одна, в ней учатся одиннадцать детей разного возраста, "
        "и уроки ведёт единственная учительница — Зоя Петровна Анчугова, приехавшая сюда "
        "по распределению тридцать лет назад и так и оставшаяся.",
        "Главное богатство плато — яки и овцы. Утром пастухи уводят стада на дальние пастбища "
        "и возвращаются только к закату. Шерсть здесь прядут вручную на деревянных прялках, "
        "которые передаются из поколения в поколение. Из неё вяжут носки, шарфы и тёплые "
        "жилеты; часть изделий раз в год увозят на ярмарку в районный центр, и вырученных "
        "денег хватает, чтобы купить новые инструменты и лекарства.",
        "Погода на высоте меняется за минуты. Ясное утро может обернуться снежным зарядом, "
        "а через час солнце снова печёт так, что приходится снимать куртку. Местные жители "
        "читают небо как книгу: по форме облаков над перевалом они знают, будет ли завтра "
        "ветер, и стоит ли выгонять скот. Метеостанция, закрытая в девяностые, недавно снова "
        "заработала — теперь данные с неё уходят в долину через спутник.",
        "Последним вечером хозяйка дома, где жила Варвара, накрыла стол: лепёшки из печи, "
        "густой суп с бараниной, солёный чай с маслом. Разговор шёл до глубокой ночи. "
        "«Внизу всё время спешат, — сказала она, разливая чай. — А здесь время течёт, как "
        "ледник: медленно, но никто не может его остановить». Утром облака снова поднялись "
        "к самому краю плато, и дорога вниз исчезла в молочной пелене.",
        "Весной на плато приходит короткое, но бурное лето. За несколько недель склоны "
        "покрываются эдельвейсами и горечавкой, по ручьям поднимается форель, а в небе "
        "кружат грифы, высматривая добычу. Дети целыми днями пропадают у реки, взрослые "
        "чинят изгороди и заготавливают сено: косить приходится вручную, потому что "
        "технике сюда не подняться. Сено сушат на крышах, иначе его растащит ветер.",
        "Медицинская помощь — отдельная история. Ближайшая больница находится в районном "
        "центре, в ста двадцати километрах. Раз в месяц на плато прилетает вертолёт "
        "санитарной авиации с врачом и фельдшером; в остальное время за здоровьем жителей "
        "следит медсестра Галина Ефимовна Сыромятова, которая принимает больных в "
        "небольшом медпункте рядом со школой. Самые частые жалобы — давление, простуда "
        "и боли в суставах от постоянной работы на холоде.",
        "Молодёжь всё чаще уезжает в долину учиться и работать. Но многие возвращаются: "
        "кто-то открывает гостевой дом для туристов, кто-то налаживает продажу шерсти "
        "через интернет. Двое выпускников местной школы в прошлом году вернулись "
        "ветеринарами и теперь лечат скот во всех окрестных посёлках.",
        "Сейчас Варвара готовит выставку снимков, которая откроется весной в городской "
        "галерее. Часть средств от продажи фотографий пойдёт на ремонт школы в Верхнем Броде "
        "и на покупку новых солнечных панелей для метеостанции.",
    ],
    "quote": "«Здесь время течёт, как ледник: медленно, но никто не может его остановить»",
    "cap": "Пастбища на высоте 3200 метров. Фото: Варвара Леднёва",
}


def _hyph(word):
    try:
        import pyphen
        return [int(i) for i in pyphen.Pyphen(lang="ru_RU").positions(word)]
    except Exception:            # без словаря переносов — без переносов
        return []


NL = chr(10)


def _flow(c, paras, cols, y_top, y_bot, lead, size, font, limits, drop=None, first_indent=12):
    """Течёт абзацы по колонкам с переносами; limits(col, y) → (x0, x1) свободного места строки."""
    toks = []
    for p in paras:
        toks += p.split()
        toks.append(NL)
    sp = _sw(" ", font, size)
    i, col, y = 0, 0, y_top
    para_start = True
    drop_lines = 0
    while i < len(toks) and col < len(cols):
        if y < y_bot:
            col += 1
            y = y_top
            continue
        x0, x1 = limits(col, y)
        if x1 - x0 < 48:
            y -= lead
            continue
        ind = 0
        if drop and i == 0 and para_start:
            dl, df, ds = drop
            _text(c, x0, y - lead * 2 + 2, dl, df, ds, "#9b2c2c")
            drop_lines = 3
            toks[0] = toks[0][len(dl):]
        if drop_lines:
            ind = _sw(drop[0], drop[1], drop[2]) + 4
            drop_lines -= 1
        elif para_start and i > 0:
            ind = first_indent
        avail = x1 - x0 - ind
        line, lw = [], 0.0
        while i < len(toks) and toks[i] != NL:
            w = toks[i]
            add = _sw(w, font, size) + (sp if line else 0)
            if line and lw + add > avail:
                # перенос по слогам, если строка иначе останется редкой
                if avail - lw > 0.06 * avail:
                    for pos in sorted(_hyph(w.strip("«»,.:;!?—")), reverse=True):
                        head = w[:pos] + "-"
                        if lw + sp + _sw(head, font, size) <= avail:
                            line.append(head)
                            lw += sp + _sw(head, font, size)
                            toks[i] = w[pos:]
                            break
                break
            line.append(w)
            lw += add
            i += 1
        end_para = i < len(toks) and toks[i] == NL
        if end_para:
            i += 1
        cx = x0 + ind
        gap = sp
        if not end_para and len(line) > 1:
            gap = sp + (avail - lw) / (len(line) - 1)
        c.setFont(font, size)
        _fill(c, "#1e1e1e")
        for w in line:
            c.drawString(cx, y, w)
            cx += _sw(w, font, size) + gap
        para_start = end_para
        y -= lead
    return i >= len(toks)


def pdf_magazine_wrap(path):
    from reportlab.lib.pagesizes import A4
    c = _canvas(path, A4)
    W, H = A4
    m = 46
    # колонтитул
    _text(c, m, H - 34, MAG["name"], "serifb", 11, "#9b2c2c")
    _text(c, W - m, H - 34, MAG["rubric"], "sansb", 8, "#6b6b6b", "right")
    c.setLineWidth(0.5)
    _stroke(c, "#9b2c2c")
    c.line(m, H - 40, W - m, H - 40)
    _text(c, m, H - 64, MAG["rubric"], "sansb", 8.5, "#9b2c2c")
    _text(c, m, H - 102, MAG["title"], "serifb", 34, "#1e1e1e")
    y = _para(c, MAG["lead"], m, H - 126, W - 2 * m - 60, "serif", 12.5, 16.5, color=(0.35, 0.35, 0.35))
    c.setLineWidth(0.3)
    _stroke(c, "#bbbbbb")
    c.line(m, y + 4, W - m, y + 4)
    top = y - 14
    bot = 70
    g = 20
    cw = (W - 2 * m - g) / 2
    cols = [(m, m + cw), (m + cw + g, W - m)]
    # круглая картинка по центру, между колонками
    cx, cy, r = W / 2, top - 205, 92
    R = r + 9
    # вынос — прямоугольник поперёк средника ниже
    qx0, qx1 = W / 2 - 95, W / 2 + 95
    qy1 = cy - r - 120
    qy0 = qy1 - 92

    capw = _sw(MAG["cap"], "sans", 6.8) / 2 + 4

    def blocked(yb0, yb1):
        """Занятые по горизонтали отрезки в полосе строки [yb0, yb1]."""
        out = []
        dyn = 0.0 if yb0 <= cy <= yb1 else min(abs(yb0 - cy), abs(yb1 - cy))
        if dyn < R:
            dx = math.sqrt(R * R - dyn * dyn)
            out.append((cx - dx, cx + dx))
        if yb1 > cy - r - 19 and yb0 < cy - r - 3:          # подпись под фото
            out.append((cx - capw, cx + capw))
        if yb1 > qy0 - 6 and yb0 < qy1 + 6:
            out.append((qx0 - 3, qx1 + 3))
        return out

    def limits(col, y):
        x0, x1 = cols[col]
        for a, b in blocked(y - 3, y + 9):
            if b < x0 or a > x1:
                continue
            if col == 0:
                x1 = min(x1, a - 9)
            else:
                x0 = max(x0, b + 9)
        return x0, x1

    _flow(c, MAG["text"], cols, top, bot, 12.6, 9.6, "serif", limits, drop=("Д", "serifb", 36))
    # картинка: пейзаж в круге
    c.saveState()
    p = c.beginPath()
    p.circle(cx, cy, r)
    c.clipPath(p, stroke=0)
    for k in range(30):
        t = k / 29
        _fill(c, (0.55 + 0.35 * t, 0.7 + 0.22 * t, 0.88 + 0.1 * t))
        c.rect(cx - r, cy + r - (k + 1) * (2 * r / 30) * 0.6, 2 * r, 2 * r / 30 * 0.6 + 1, fill=1, stroke=0)
    _fill(c, "#f7f7f9")
    for (ox, oy, rr) in [(-40, 10, 26), (-15, 14, 30), (15, 8, 24), (50, 18, 22), (70, 10, 18)]:
        c.circle(cx + ox, cy + oy, rr, fill=1, stroke=0)
    for col, pts in [("#6c7a89", [(-r, -10), (-55, 40), (-20, 5), (10, 52), (45, 0), (r, 30), (r, -r), (-r, -r)]),
                     ("#4d5c49", [(-r, -40), (-30, -15), (20, -45), (60, -20), (r, -35), (r, -r), (-r, -r)])]:
        _fill(c, col)
        pp = c.beginPath()
        pp.moveTo(cx + pts[0][0], cy + pts[0][1])
        for px, py in pts[1:]:
            pp.lineTo(cx + px, cy + py)
        pp.close()
        c.drawPath(pp, fill=1, stroke=0)
    _fill(c, "#ffffff")
    for (ox, oy) in [(-50, 12), (-5, 22), (30, 4)]:
        pp = c.beginPath()
        pp.moveTo(cx + ox, cy + oy + 26)
        pp.lineTo(cx + ox - 10, cy + oy + 10)
        pp.lineTo(cx + ox + 12, cy + oy + 10)
        pp.close()
        c.drawPath(pp, fill=1, stroke=0)
    c.restoreState()
    _stroke(c, "#ffffff")
    c.setLineWidth(3)
    c.circle(cx, cy, r, fill=0, stroke=1)
    _text(c, cx, cy - r - 13, MAG["cap"], "sans", 6.8, "#6b6b6b", "center")
    # вынос-цитата
    _fill(c, "#f6eeee")
    c.rect(qx0, qy0, qx1 - qx0, qy1 - qy0, fill=1, stroke=0)
    _fill(c, "#9b2c2c")
    c.rect(qx0, qy1 - 3, qx1 - qx0, 3, fill=1, stroke=0)
    c.rect(qx0, qy0, qx1 - qx0, 1.2, fill=1, stroke=0)
    _para(c, MAG["quote"], qx0 + 12, qy1 - 22, qx1 - qx0 - 24, "serifb", 11.5, 14.5,
          align="center", color=_hex("#9b2c2c"))
    # подвал
    _stroke(c, "#bbbbbb")
    c.setLineWidth(0.4)
    c.line(m, 50, W - m, 50)
    _text(c, m, 38, "42", "serifb", 10, "#1e1e1e")
    _text(c, m + 20, 38, MAG["name"] + " · " + MAG["issue"], "sans", 7.5, "#6b6b6b")
    _text(c, W - m, 38, "Продолжение на с. 46", "sans", 7.5, "#9b2c2c", "right")
    c.save()


# ═══ 44. Договор: пункты 1., 1.1., 1.1.1., сноски, подписи ══════════════

CONTRACT = {
    "title": "ДОГОВОР ВОЗМЕЗДНОГО ОКАЗАНИЯ УСЛУГ № 17/26-К",
    "city": "г. Новоречинск", "date": "«14» сентября 2026 г.",
    "pre": ("Общество с ограниченной ответственностью «Белый маяк», именуемое в дальнейшем "
            "**«Заказчик»**, в лице генерального директора Кравцова Ильи Геннадьевича, действующего "
            "на основании Устава, с одной стороны, и индивидуальный предприниматель Мирзоева Дилноза "
            "Акмаловна, именуемая в дальнейшем **«Исполнитель»**, действующая на основании свидетельства "
            "о государственной регистрации^1, с другой стороны, совместно именуемые **«Стороны»**, "
            "заключили настоящий договор (далее — **«Договор»**) о нижеследующем:"),
    "clauses": [
        ("1.", "ПРЕДМЕТ ДОГОВОРА", None),
        ("1.1.", None, "Исполнитель обязуется по заданию Заказчика оказать услуги по письменному переводу "
                       "технической документации (далее — **«Услуги»**), а Заказчик обязуется принять и "
                       "оплатить Услуги в порядке и на условиях Договора."),
        ("1.2.", None, "Объём, сроки и язык перевода определяются в заявках, которые являются неотъемлемой "
                       "частью Договора (далее — **«Заявка»**). Заявка считается согласованной с момента её "
                       "подписания обеими Сторонами."),
        ("1.2.1.", None, "Заявка направляется по электронной почте в формате PDF с подписью уполномоченного лица."),
        ("1.2.2.", None, "Исполнитель рассматривает Заявку в течение двух рабочих дней и сообщает о "
                         "возможности её выполнения либо о необходимости изменить сроки."),
        ("2.", "ПРАВА И ОБЯЗАННОСТИ СТОРОН", None),
        ("2.1.", None, "Исполнитель обязуется:"),
        ("2.1.1.", None, "оказывать Услуги лично либо с привлечением третьих лиц, оставаясь ответственным "
                         "за их действия перед Заказчиком;"),
        ("2.1.2.", None, "соблюдать терминологию, согласованную Сторонами в глоссарии^2;"),
        ("2.1.3.", None, "не разглашать сведения, полученные в ходе исполнения Договора, в течение трёх лет "
                         "после его прекращения (далее — **«Конфиденциальная информация»**)."),
        ("2.2.", None, "Заказчик обязуется своевременно передавать исходные материалы, отвечать на вопросы "
                       "Исполнителя по содержанию текста и принимать результат Услуг по акту."),
        ("3.", "СТОИМОСТЬ И ПОРЯДОК РАСЧЁТОВ", None),
        ("3.1.", None, "Стоимость Услуг рассчитывается из ставки 420 (четыреста двадцать) рублей за одну "
                       "условную страницу объёмом 1800 знаков с пробелами исходного текста^3."),
        ("3.2.", None, "Оплата производится в течение 10 (десяти) банковских дней с даты подписания акта "
                       "сдачи-приёмки Услуг путём перечисления денежных средств на расчётный счёт Исполнителя."),
        ("3.3.", None, "Срочный перевод (более 12 страниц в рабочий день) оплачивается с коэффициентом 1,5."),
        ("4.", "ОТВЕТСТВЕННОСТЬ СТОРОН", None),
        ("4.1.", None, "За нарушение сроков оказания Услуг Исполнитель уплачивает Заказчику пеню в размере "
                       "0,1 % от стоимости соответствующей Заявки за каждый день просрочки, но не более 10 % "
                       "её стоимости."),
        ("4.2.", None, "Стороны освобождаются от ответственности за неисполнение обязательств, если оно "
                       "вызвано обстоятельствами непреодолимой силы, подтверждёнными компетентным органом."),
        ("4.2.1.", None, "Сторона, для которой наступили такие обстоятельства, уведомляет другую Сторону "
                         "в течение пяти календарных дней с момента их наступления."),
        ("5.", "СРОК ДЕЙСТВИЯ И РАСТОРЖЕНИЕ", None),
        ("5.1.", None, "Договор вступает в силу с даты подписания и действует до 31 декабря 2027 г. "
                       "Если ни одна из Сторон не заявит о его прекращении за 30 дней до окончания срока, "
                       "Договор считается продлённым на каждый следующий календарный год."),
        ("5.2.", None, "Каждая из Сторон вправе отказаться от исполнения Договора, письменно уведомив "
                       "другую Сторону не менее чем за 30 (тридцать) календарных дней."),
        ("6.", "ПРОЧИЕ УСЛОВИЯ", None),
        ("6.1.", None, "Споры разрешаются путём переговоров, а при недостижении согласия — в арбитражном "
                       "суде по месту нахождения Заказчика."),
        ("6.2.", None, "Все уведомления по Договору направляются в письменной форме по адресам, указанным "
                       "в разделе 7, либо по электронной почте с последующей досылкой оригинала^4."),
        ("6.2.1.", None, "Уведомление считается полученным на пятый день после отправки заказным письмом, "
                         "даже если адресат не явился за его получением."),
        ("6.3.", None, "Приложения к Договору: Приложение № 1 «Форма Заявки», Приложение № 2 «Глоссарий»; "
                       "Приложение № 3 «Акт сдачи-приёмки Услуг (форма)»."),
        ("6.4.", None, "Договор составлен в двух экземплярах, имеющих равную юридическую силу, по одному "
                       "для каждой из Сторон."),
    ],
    "notes": {
        "1": "Свидетельство серии 66 № 004512378 выдано 3 марта 2021 г.",
        "2": "Глоссарий согласуется в первой Заявке и обновляется по письменному запросу любой из Сторон.",
        "4": "Адреса электронной почты: info@belymayak.example, d.mirzoeva@example.com.",
        "3": "Количество знаков определяется функцией «Статистика» текстового редактора по исходному тексту.",
    },
    "sides": [("ЗАКАЗЧИК", ["ООО «Белый маяк»", "ИНН 6658123407 / КПП 665801001",
                            "620075, г. Новоречинск, ул. Литейная, д. 12, оф. 304",
                            "р/с 40702810900000012345", "в АО «Банк Северный», БИК 046577999"],
               "И. Г. Кравцов", "Генеральный директор"),
              ("ИСПОЛНИТЕЛЬ", ["ИП Мирзоева Д. А.", "ИНН 665912345678",
                               "620142, г. Новоречинск, ул. Садовая, д. 5, кв. 18",
                               "р/с 40802810100000067890", "в ПАО «Уралпромкредит», БИК 046577888"],
               "Д. А. Мирзоева", "Индивидуальный предприниматель")],
}


def pdf_contract(path):
    from reportlab.lib.pagesizes import A4
    c = _canvas(path, A4)
    W, H = A4
    ml, mr = 62, 50
    tw = W - ml - mr
    size, lead = 9.6, 12.8
    state = {"page": 1, "notes": []}

    def footer():
        # сноски этой страницы
        if state["notes"]:
            ny = 52 + 10.5 * len(state["notes"])
            c.setLineWidth(0.5)
            _stroke(c, "#333333")
            c.line(ml, ny + 6, ml + 120, ny + 6)
            for k in state["notes"]:
                ny -= 10.5
                _text(c, ml, ny + 3, k, "serif", 5.5)
                _text(c, ml + 5, ny, CONTRACT["notes"][k], "serif", 7.5, "#222222")
        _text(c, W / 2, 30, f"Страница {state['page']} из 2", "serif", 7.5, "#555555", "center")
        _text(c, ml, 30, "Заказчик ________", "serif", 7.5, "#555555")
        _text(c, W - mr, 30, "Исполнитель ________", "serif", 7.5, "#555555", "right")

    def notes_of(t):
        return [k for k in CONTRACT["notes"] if "^" + k in t]

    def newpage():
        footer()
        c.showPage()
        state["page"] += 1
        state["notes"] = []
        return H - 60

    _text(c, W / 2, H - 62, CONTRACT["title"], "serifb", 12.5, align="center")
    _text(c, ml, H - 88, CONTRACT["city"], "serif", size)
    _text(c, W - mr, H - 88, CONTRACT["date"], "serif", size, align="right")
    state["notes"] += notes_of(CONTRACT["pre"])
    y = _rich(c, CONTRACT["pre"], ml, H - 112, tw, size, lead, first=24) - 6
    for num, head, body in CONTRACT["clauses"]:
        depth = num.count(".")
        need = 40 if head else 14 + lead * len(_wrap(c, body.replace("**", ""), "serif", size, tw - 40))
        bottom_reserve = 70 + 10.5 * (len(state["notes"]) + len(notes_of(body or "")))
        if y - need < bottom_reserve:
            y = newpage()
        if head:
            y -= 6
            _text(c, W / 2, y, f"{num} {head}", "serifb", size + 0.4, align="center")
            y -= lead + 4
            continue
        state["notes"] += notes_of(body)
        # висячий отступ: номер на x, текст на x + ширина номера
        x = ml + (0 if depth == 2 else 24)
        hang = 30 if depth == 2 else 40
        _text(c, x, y, num, "serifb" if depth == 2 else "serif", size)
        y = _rich(c, body, x + hang, y, tw - (x - ml) - hang, size, lead) - 4
    # блок подписей в 2 колонки
    if y < 290:
        y = newpage()
    y -= 10
    _text(c, W / 2, y, "7. АДРЕСА, РЕКВИЗИТЫ И ПОДПИСИ СТОРОН", "serifb", size + 0.4, align="center")
    y -= 22
    cw = (tw - 30) / 2
    for i, (role, req, who, pos) in enumerate(CONTRACT["sides"]):
        x = ml + i * (cw + 30)
        yy = y
        _text(c, x, yy, role, "serifb", size)
        yy -= 15
        for ln in req:
            yy = _para(c, ln, x, yy, cw, "serif", 8.6, 11)
        yy -= 14
        _text(c, x, yy, pos, "serif", 8.6)
        yy -= 30
        c.setLineWidth(0.6)
        _stroke(c, "#111111")
        c.line(x, yy, x + 110, yy)
        _text(c, x + 116, yy + 2, "/ " + who + " /", "serif", 9)
        _text(c, x + 30, yy - 10, "(подпись)", "serif", 6.5, "#555555")
        _text(c, x, yy - 30, "М.П.", "serifb", 9)
        yy -= 52
        c.line(x, yy, x + 110, yy)
        _text(c, x, yy - 10, "«____» ______________ 2026 г.", "serif", 7.5, "#555555")
    footer()
    c.save()


# ═══ 45. Расписание: альбомная таблица, повёрнутые заголовки ════════════

TT = {
    "title": "РАСПИСАНИЕ УЧЕБНЫХ ЗАНЯТИЙ",
    "sub": "Медицинский колледж «Зелёная долина» · осенний семестр 2026/2027 учебного года · неделя 7",
    "groups": [("1 курс", ["Лечебное дело, гр. 101", "Лечебное дело, гр. 102", "Сестринское дело, гр. 103"]),
               ("2 курс", ["Лечебное дело, гр. 201", "Фармация, гр. 202", "Сестринское дело, гр. 203"]),
               ("3 курс", ["Лаборат. диагностика, гр. 301", "Акушерское дело, гр. 302"])],
    "times": ["8:30–10:00", "10:10–11:40", "12:20–13:50", "14:00–15:30", "15:40–17:10", "17:20–18:50", "19:00–20:30"],
    "subjects": [("Анатомия человека", "Шилова Т. Р."), ("Латинский язык", "Гарипов Р. М."),
                 ("Фармакология", "Ершова А. В."), ("Основы сестринского дела", "Ким Л. С."),
                 ("Микробиология", "Носов П. А."), ("Пропедевтика", "Усманова Г. Х."),
                 ("Физическая культура", "Бойко Е. Н."), ("Иностранный язык", "Остапенко М. И."),
                 ("Биохимия", "Рахимов Ф. Б."), ("Гигиена и экология", "Тарасова В. Ю."),
                 ("Клиническая лаборатория", "Абдуллаев С. К."), ("Акушерство", "Зайцева О. П."),
                 ("Фармацевтическая химия", "Лим Д. В."), ("Психология общения", "Миронова А. А."),
                 ("Информатика", "Сабиров Т. Т."), ("Патология", "Орлова Н. Д.")],
}


def pdf_timetable(path):
    from reportlab.lib.pagesizes import A4, landscape
    c = _canvas(path, landscape(A4))
    W, H = landscape(A4)
    m = 26
    _text(c, m, H - 34, TT["title"], "sansb", 14, "#14213d")
    _text(c, m, H - 48, TT["sub"], "sans", 8, "#4a5560")
    _text(c, W - m, H - 34, "УТВЕРЖДАЮ", "sansb", 8, "#14213d", "right")
    _text(c, W - m, H - 45, "Зам. директора по УР ________ Ю. Л. Пак", "sans", 7.5, "#14213d", "right")
    groups = [g for _, gs in TT["groups"] for g in gs]
    x0 = m
    wday, wnum, wtime = 22, 18, 52
    gx = x0 + wday + wnum + wtime
    gw = (W - m - gx) / len(groups)
    top = H - 62
    h1, h2 = 14, 86            # объединённая шапка курса и повёрнутые названия групп
    rh = (top - h1 - h2 - 36) / 14
    c.setLineWidth(0.35)
    _stroke(c, "#7a8794")
    # шапка
    _fill(c, "#14213d")
    c.rect(x0, top - h1 - h2, gx - x0, h1 + h2, fill=1, stroke=1)
    for t, cx in [("День", x0 + wday / 2), ("№", x0 + wday + wnum / 2), ("Время", x0 + wday + wnum + wtime / 2)]:
        c.saveState()
        c.translate(cx + 3, top - h1 - h2 + 8)
        c.rotate(90)
        _text(c, 0, 0, t, "sansb", 7, "#ffffff")
        c.restoreState()
    gi = 0
    shades = ["#fca311", "#2a9d8f", "#e76f51"]
    for k, (course, gs) in enumerate(TT["groups"]):
        xx = gx + gi * gw
        _fill(c, shades[k])
        c.rect(xx, top - h1, gw * len(gs), h1, fill=1, stroke=1)
        _text(c, xx + gw * len(gs) / 2, top - h1 + 4, course.upper(), "sansb", 7.5, "#ffffff", "center")
        for g in gs:
            _fill(c, "#e5e5e5")
            c.rect(gx + gi * gw, top - h1 - h2, gw, h2, fill=1, stroke=1)
            c.saveState()
            c.translate(gx + gi * gw + gw / 2 + 2.5, top - h1 - h2 + 5)
            c.rotate(90)
            name, _, grp = g.partition(", ")
            _text(c, 0, 4, name, "sansb", 6.5, "#14213d")
            _text(c, 0, -4, grp, "sans", 6.5, "#14213d")
            c.restoreState()
            gi += 1
    # тело
    rng = random.Random(45)
    y = top - h1 - h2
    days = ["ПОНЕДЕЛЬНИК", "ВТОРНИК"]
    for d in range(2):
        dy = y
        for p in range(7):
            ry = y - rh
            zebra = p % 2 == 1
            for gi2 in range(len(groups) + 3):
                pass
            _fill(c, "#f4f6f8" if zebra else "#ffffff")
            c.rect(x0 + wday, ry, W - m - x0 - wday, rh, fill=1, stroke=0)
            _text(c, x0 + wday + wnum / 2, ry + rh / 2 - 2.5, str(p + 1), "sansb", 7, "#14213d", "center")
            t1, t2 = TT["times"][p].split("–")
            _text(c, x0 + wday + wnum + wtime / 2, ry + rh / 2 + 1.5, t1 + "–", "sans", 6.5, "#14213d", "center")
            _text(c, x0 + wday + wnum + wtime / 2, ry + rh / 2 - 6, t2, "sans", 6.5, "#14213d", "center")
            for gi2 in range(len(groups)):
                cx = gx + gi2 * gw
                empty = (p >= 5 and gi2 < 3) or (p == 6) or rng.random() < 0.08
                if empty and not (p == 6 and gi2 == 7):
                    continue
                subj, who = rng.choice(TT["subjects"])
                kind = rng.choice(["лек.", "пр.", "лаб.", "пр.", "сем."])
                room = rng.choice(["ауд.", "каб."]) + f" {rng.randint(1, 4)}{rng.randint(0, 2)}{rng.randint(1, 9)}"
                if subj == "Физическая культура":
                    room = "спортзал"
                if subj == "Физическая культура":
                    kind = "пр."
                half = rng.random() < 0.12
                lim = gw - 5 - (15 if half else 0)
                sf = "sansb" if _sw(subj, "sansb", 6.5) <= lim else "sanscb"
                lines = _wrap(c, subj, sf, 6.5, lim)
                yy = ry + rh - 8
                for k, ln in enumerate(lines[:2]):
                    _text(c, cx + 2.5, yy, ln, sf, 6.5, "#14213d")
                    yy -= 7.2
                if len(lines) > 1:
                    _text(c, cx + 2.5, yy, f"{kind} {room} · {who}", "sansc", 6.2, "#3a4a5a")
                else:
                    _text(c, cx + 2.5, yy, f"{kind} {room}", "sans", 6.2, "#3a4a5a")
                    _text(c, cx + 2.5, yy - 7, who, "sans", 6.2, "#5a6570")
                if half:
                    _fill(c, "#e76f51")
                    c.rect(cx + gw - 15, ry + rh - 9, 13, 7, fill=1, stroke=0)
                    _text(c, cx + gw - 8.5, ry + rh - 7.5, "1/2", "sansb", 4.8, "#ffffff", "center")
            # линии строки
            c.line(x0 + wday, ry, W - m, ry)
            y = ry
        # объединённая ячейка дня, повёрнутая
        _fill(c, "#dfe7ef")
        c.rect(x0, y, wday, dy - y, fill=1, stroke=1)
        c.saveState()
        c.translate(x0 + wday / 2 + 3, (y + dy) / 2)
        c.rotate(90)
        _text(c, 0, 0, days[d], "sansb", 8, "#14213d", "center")
        c.restoreState()
        c.setLineWidth(1.1)
        _stroke(c, "#14213d")
        c.line(x0, y, W - m, y)
        c.setLineWidth(0.35)
        _stroke(c, "#7a8794")
    # вертикальные линии
    xs = [x0, x0 + wday, x0 + wday + wnum, gx] + [gx + k * gw for k in range(1, len(groups) + 1)]
    for xx in xs:
        c.line(xx, y, xx, top - h1 - h2)
    c.setLineWidth(0.9)
    _stroke(c, "#14213d")
    c.rect(x0, y, W - m - x0, top - y, fill=0, stroke=1)
    _text(c, m, y - 13, "Обозначения: лек. — лекция; пр. — практическое занятие; лаб. — лабораторная работа; "
                        "сем. — семинар; 1/2 — занятие по подгруппам (чётные недели).", "sans", 6.5, "#4a5560")
    _text(c, W - m, y - 13, "Изменения в расписании публикуются на стенде у учебной части.", "sans", 6.5,
          "#4a5560", "right")
    c.save()


# ═══ 46. Блок-схема с дорожками ═════════════════════════════════════════

def _arrow(c, pts, col="#37474f", lw=1.1, label=None, lpos=None, lalign="left"):
    _stroke(c, col)
    c.setLineWidth(lw)
    p = c.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    c.drawPath(p, fill=0, stroke=1)
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    a = math.atan2(y2 - y1, x2 - x1)
    L = 7
    _fill(c, col)
    pp = c.beginPath()
    pp.moveTo(x2, y2)
    pp.lineTo(x2 - L * math.cos(a - 0.38), y2 - L * math.sin(a - 0.38))
    pp.lineTo(x2 - L * math.cos(a + 0.38), y2 - L * math.sin(a + 0.38))
    pp.close()
    c.drawPath(pp, fill=1, stroke=0)
    if label:
        lx, ly = lpos
        w = _sw(label, "sansb", 7.5) + 4
        _fill(c, "#ffffff")
        c.rect(lx - (w / 2 if lalign == "center" else 0) - (0 if lalign == "center" else 1), ly - 3, w, 11, fill=1, stroke=0)
        _text(c, lx + (0 if lalign == "center" else 2), ly, label, "sansb", 7.5,
              "#2e7d32" if label == "Yes" else "#c62828", lalign)


def _box(c, cx, cy, w, h, text, kind="rect", fill="#e3f2fd", edge="#1565c0", f="sans", s=8.2):
    _fill(c, fill)
    _stroke(c, edge)
    c.setLineWidth(1)
    if kind == "rect":
        c.rect(cx - w / 2, cy - h / 2, w, h, fill=1, stroke=1)
    elif kind == "round":
        c.roundRect(cx - w / 2, cy - h / 2, w, h, h / 2, fill=1, stroke=1)
    elif kind == "diamond":
        p = c.beginPath()
        p.moveTo(cx, cy + h / 2)
        p.lineTo(cx + w / 2, cy)
        p.lineTo(cx, cy - h / 2)
        p.lineTo(cx - w / 2, cy)
        p.close()
        c.drawPath(p, fill=1, stroke=1)
    elif kind == "doc":
        p = c.beginPath()
        p.moveTo(cx - w / 2, cy + h / 2)
        p.lineTo(cx + w / 2, cy + h / 2)
        p.lineTo(cx + w / 2, cy - h / 2 + 5)
        p.curveTo(cx + w / 4, cy - h / 2 - 5, cx - w / 4, cy - h / 2 + 12, cx - w / 2, cy - h / 2 + 2)
        p.close()
        c.drawPath(p, fill=1, stroke=1)
    tw = w * (0.62 if kind == "diamond" else 0.88)
    lines = _wrap(c, text, f, s, tw)
    lead = s * 1.2
    y = cy + (len(lines) - 1) * lead / 2 - s * 0.35
    for ln in lines:
        _text(c, cx, y, ln, f, s, "#102027", "center")
        y -= lead


def pdf_flowchart(path):
    from reportlab.lib.pagesizes import A4
    c = _canvas(path, A4)
    W, H = A4
    m = 32
    _text(c, m, H - 42, "Customer Support Ticket Workflow", "sansb", 17, "#102027")
    _text(c, m, H - 57, "Process map SP-04 · revision C · applies to all product lines from 1 November 2026",
          "sans", 8, "#546e7a")
    lanes = [("Customer", "#fff8e1"), ("Support Desk (Tier 1)", "#e8f5e9"),
             ("Engineering (Tier 2)", "#e3f2fd"), ("Quality Assurance", "#f3e5f5")]
    top, bot = H - 72, 92
    lh = (top - bot) / len(lanes)
    lw = 26
    c.setLineWidth(0.6)
    for i, (name, col) in enumerate(lanes):
        y1 = top - i * lh
        _fill(c, col)
        _stroke(c, "#90a4ae")
        c.rect(m, y1 - lh, W - 2 * m, lh, fill=1, stroke=1)
        _fill(c, "#37474f")
        c.rect(m, y1 - lh, lw, lh, fill=1, stroke=1)
        c.saveState()
        c.translate(m + lw / 2 + 3.5, y1 - lh / 2)
        c.rotate(90)
        _text(c, 0, 0, name, "sansb", 9, "#ffffff", "center")
        c.restoreState()
    L = [top - lh * (i + 0.5) for i in range(4)]
    x0 = m + lw
    X = [x0 + 54 + k * 100 for k in range(5)]
    bw, bh, dw, dh = 80, 40, 92, 62
    G = ("#c8e6c9", "#2e7d32")
    B_ = ("#bbdefb", "#1565c0")
    Q = ("#e1bee7", "#6a1b9a")
    D_ = ("#fffde7", "#f9a825")
    S = ("#ffe082", "#ef6c00")
    _box(c, X[0], L[0], bw, 30, "Customer reports a problem", "round", *S, "sansb", 7.8)
    _box(c, X[1] + 8, L[0], bw, bh + 4, "Auto-reply with ticket number", "doc", "#fff3e0", "#ef6c00", s=7.6)
    _box(c, X[2] + 16, L[0], dw, dh, "Customer confirms the fix works?", "diamond", *D_, s=7.2)
    _box(c, X[4], L[0], bw, 30, "Ticket closed", "round", *S, "sansb", 7.8)
    _box(c, X[0], L[1], bw, bh, "Log ticket and assign priority", "rect", *G)
    _box(c, X[1] + 8, L[1], dw, dh, "Known issue in knowledge base?", "diamond", *D_, s=7.2)
    _box(c, X[2] + 16, L[1], bw, bh, "Send documented solution", "rect", *G)
    _box(c, X[4], L[1], bw, bh, "Release patch and notify customer", "rect", *G)
    _box(c, X[1] + 8, L[2], bw, bh, "Reproduce the defect in test lab", "rect", *B_)
    _box(c, X[2] + 16, L[2], dw, dh, "Reproduced within 48 h?", "diamond", *D_, s=7.4)
    _box(c, X[3] + 8, L[2], bw, bh, "Develop and package patch", "rect", *B_)
    _box(c, X[2] + 16, L[3], bw + 4, bh + 6, "Request logs and environment details", "doc", "#f3e5f5", "#6a1b9a", s=7.4)
    _box(c, X[3] + 8, L[3], bw, bh, "Regression test on 3 platforms", "rect", *Q)
    _box(c, X[4] + 6, L[3], dw - 6, dh, "All tests passed?", "diamond", *D_, s=7.4)
    c1, c2, c3, c4 = X[1] + 8, X[2] + 16, X[3] + 8, X[4]
    # стрелки
    _arrow(c, [(X[0], L[0] - 15), (X[0], L[1] + bh / 2)])
    _arrow(c, [(X[0] + bw / 2, L[0]), (c1 - bw / 2, L[0])], col="#ef6c00", lw=0.8)
    _arrow(c, [(X[0] + bw / 2, L[1]), (c1 - dw / 2, L[1])])
    _arrow(c, [(c1 + dw / 2, L[1]), (c2 - bw / 2, L[1])], label="Yes", lpos=((c1 + dw / 2 + c2 - bw / 2) / 2, L[1] + 5), lalign="center")
    _arrow(c, [(c2, L[1] + bh / 2), (c2, L[0] - dh / 2)])
    _arrow(c, [(c2 + dw / 2, L[0]), (c4 - bw / 2, L[0])], label="Yes", lpos=(c2 + dw / 2 + 4, L[0] + 4))
    _arrow(c, [(c2, L[0] + dh / 2), (c2, L[0] + 50), (x0 + 9, L[0] + 50), (x0 + 9, L[1]),
               (X[0] - bw / 2, L[1])], label="No", lpos=(c2 + 4, L[0] + dh / 2 + 6))
    _text(c, x0 + 14, L[0] + 54, "issue persists — reopen ticket", "sans", 6.8, "#546e7a")
    _arrow(c, [(c1, L[1] - dh / 2), (c1, L[2] + bh / 2)], label="No", lpos=(c1 + 4, L[1] - dh / 2 - 14))
    _arrow(c, [(c1 + bw / 2, L[2]), (c2 - dw / 2, L[2])])
    _arrow(c, [(c2 + dw / 2, L[2]), (c3 - bw / 2, L[2])], label="Yes", lpos=((c2 + dw / 2 + c3 - bw / 2) / 2, L[2] + 5), lalign="center")
    _arrow(c, [(c2, L[2] - dh / 2), (c2, L[3] + (bh + 6) / 2)], label="No", lpos=(c2 + 4, L[2] - dh / 2 - 14))
    _arrow(c, [(c2 - (bw + 4) / 2, L[3]), (c1, L[3]), (c1, L[2] - bh / 2)], col="#7b8d97", lw=0.9)
    _text(c, c1 - 38, L[3] + 6, "customer replies", "sans", 6.8, "#546e7a")
    _arrow(c, [(c3, L[2] - bh / 2), (c3, L[3] + bh / 2)])
    _arrow(c, [(c3 + bw / 2, L[3]), (c4 + 6 - (dw - 6) / 2, L[3])])
    _arrow(c, [(c4 + 6, L[3] + dh / 2), (c4 + 6, L[1] - bh / 2)], label="Yes", lpos=(c4 + 10, L[3] + dh / 2 + 6))
    _arrow(c, [(c4 + 6, L[3] - dh / 2), (c4 + 6, L[3] - dh / 2 - 18), (c3, L[3] - dh / 2 - 18), (c3, L[3] - bh / 2)],
           label="No", lpos=(c4 - 30, L[3] - dh / 2 - 15))
    _arrow(c, [(c4, L[1] + bh / 2), (c4, L[0] - 15)])
    _text(c, c4 + 4, L[1] + bh / 2 + 30, "within 1 day", "sans", 6.8, "#546e7a")
    # легенда
    ly = 70
    items = [("round", "#ffe082", "#ef6c00", "Start / end"), ("rect", "#e0e0e0", "#455a64", "Process step"),
             ("diamond", "#fffde7", "#f9a825", "Decision"), ("doc", "#f3e5f5", "#6a1b9a", "Document / request")]
    for i, (k, f, e, t) in enumerate(items):
        x = m + 8 + i * 132
        _box(c, x + 14, ly, 24, 14, "", k, f, e)
        _text(c, x + 32, ly - 3, t, "sans", 7.5, "#37474f")
    _text(c, m, 46, "SLA targets: Tier 1 first response within 4 business hours; Tier 2 resolution within "
                    "5 business days for priority P2, 24 hours for P1.", "sans", 7.2, "#546e7a")
    _text(c, W - m, 30, "Owner: Service Operations · Page 1 of 1", "sans", 7, "#90a4ae", "right")
    c.save()


# ═══ 47. Этикетка упаковки (RU→KK) ══════════════════════════════════════

EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
EAN_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
EAN_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
EAN_P = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def _ean13(c, x, y, digits, mod=1.25, h=46):
    d = [int(ch) for ch in digits[:12]]
    chk = (10 - (sum(d[i] * (3 if i % 2 else 1) for i in range(12)) % 10)) % 10
    d.append(chk)
    bits = "101"
    par = EAN_P[d[0]]
    for i in range(1, 7):
        bits += (EAN_L if par[i - 1] == "L" else EAN_G)[d[i]]
    bits += "01010"
    for i in range(7, 13):
        bits += EAN_R[d[i]]
    bits += "101"
    _fill(c, "#ffffff")
    c.rect(x - 10, y - 12, len(bits) * mod + 18, h + 16, fill=1, stroke=0)
    _fill(c, "#000000")
    guard = set(list(range(0, 3)) + list(range(45, 50)) + list(range(92, 95)))
    for i, b in enumerate(bits):
        if b == "1":
            ext = 6 if i in guard else 0
            c.rect(x + i * mod, y - ext, mod, h + ext, fill=1, stroke=0)
    s = "".join(map(str, d))
    _text(c, x - 7, y - 8, s[0], "mono", 8, "#000000")
    for i, ch in enumerate(s[1:7]):
        _text(c, x + (3 + i * 7 + 3.5) * mod, y - 8, ch, "mono", 8, "#000000", "center")
    for i, ch in enumerate(s[7:]):
        _text(c, x + (50 + i * 7 + 3.5) * mod, y - 8, ch, "mono", 8, "#000000", "center")


def _icon(c, cx, cy, kind, col="#c62828"):
    c.setLineWidth(1.4)
    _stroke(c, col)
    _fill(c, "#ffffff")
    if kind == "tri":
        p = c.beginPath()
        p.moveTo(cx, cy + 12)
        p.lineTo(cx + 13, cy - 10)
        p.lineTo(cx - 13, cy - 10)
        p.close()
        c.drawPath(p, fill=1, stroke=1)
        _text(c, cx, cy - 7, "!", "sansb", 13, col, "center")
    elif kind == "temp":
        c.circle(cx, cy, 13, fill=1, stroke=1)
        c.roundRect(cx - 2.2, cy - 5, 4.4, 14, 2.2, fill=0, stroke=1)
        _fill(c, col)
        c.circle(cx, cy - 6, 3.6, fill=1, stroke=0)
        c.rect(cx - 0.9, cy - 5, 1.8, 8, fill=1, stroke=0)
    elif kind == "shake":
        c.circle(cx, cy, 13, fill=1, stroke=1)
        c.roundRect(cx - 4, cy - 8, 8, 14, 1.5, fill=0, stroke=1)
        c.rect(cx - 2, cy + 6, 4, 3, fill=0, stroke=1)
        c.arc(cx - 11, cy - 6, cx - 3, cy + 6, 120, 120)
        c.arc(cx + 3, cy - 6, cx + 11, cy + 6, -60, 120)
    elif kind == "nofreeze":
        c.circle(cx, cy, 13, fill=1, stroke=1)
        for a in range(0, 180, 60):
            r = math.radians(a)
            c.line(cx - 7 * math.cos(r), cy - 7 * math.sin(r), cx + 7 * math.cos(r), cy + 7 * math.sin(r))
        c.setLineWidth(2)
        c.line(cx - 9, cy - 9, cx + 9, cy + 9)


def pdf_label_pack(path):
    from reportlab.lib.units import mm
    size = (210 * mm, 140 * mm)
    c = _canvas(path, size)
    W, H = size
    _fill(c, "#fbf7f0")
    c.rect(0, 0, W, H, fill=1, stroke=0)
    # бренд на тёмной полосе
    _fill(c, "#3b1f2b")
    c.rect(0, H - 92, W, 92, fill=1, stroke=0)
    _fill(c, "#e63946")
    c.circle(W - 70, H - 46, 34, fill=1, stroke=0)
    _fill(c, "#ffffff")
    for (ox, oy, rr) in [(-6, 4, 10), (8, 2, 9), (1, -8, 9)]:
        c.circle(W - 70 + ox, H - 46 + oy, rr, fill=1, stroke=0)
    _fill(c, "#e63946")
    c.circle(W - 70, H - 46, 6, fill=1, stroke=0)
    _text(c, 24, H - 44, "ЛУГОВОЕ", "sansb", 34, "#ffffff")
    _text(c, 26, H - 62, "Йогурт питьевой клубника — земляника", "sansb", 11, "#ffd6da")
    _text(c, 26, H - 78, "м.д.ж. 2,5 %  ·  с живыми бифидобактериями", "sans", 9, "#f1e3e6")
    _fill(c, "#ffffff")
    c.roundRect(W - 150, H - 84, 46, 18, 4, fill=1, stroke=0)
    _text(c, W - 127, H - 79, "950 г", "sansb", 10, "#3b1f2b", "center")
    # таблица пищевой ценности
    x, y = 22, H - 112
    tw = 168
    _text(c, x, y, "Пищевая ценность", "sansb", 9.5, "#3b1f2b")
    _text(c, x, y - 11, "в 100 г продукта", "sans", 7, "#5a3a46")
    rows = [("Энергетическая ценность", "79 ккал / 332 кДж"), ("Белки", "2,8 г"), ("Жиры", "2,5 г"),
            ("в т. ч. насыщенные", "1,6 г"), ("Углеводы", "11,4 г"), ("в т. ч. сахара", "10,9 г"),
            ("Кальций", "120 мг (15 %*)")]
    yy = y - 24
    c.setLineWidth(1.6)
    _stroke(c, "#3b1f2b")
    c.line(x, yy + 9, x + tw, yy + 9)
    c.setLineWidth(0.4)
    for i, (k, v) in enumerate(rows):
        ind = 8 if k.startswith("в т. ч.") else 0
        _text(c, x + ind, yy, k, "sans" if ind else "sansb", 7.4, "#2a1a20")
        _text(c, x + tw, yy, v, "sans", 7.4, "#2a1a20", "right")
        c.line(x, yy - 3.5, x + tw, yy - 3.5)
        yy -= 11.5
    _text(c, x, yy - 1, "* от рекомендуемой суточной нормы потребления", "sans", 5.6, "#5a3a46")
    # состав мелко
    sx = x + tw + 16
    sw = W - sx - 22
    _text(c, sx, y, "Состав:", "sansb", 7.5, "#3b1f2b")
    comp = ("молоко нормализованное, сахар, наполнитель «Клубника — земляника» (сахар, вода, клубника, "
            "земляника, загуститель пектин, регулятор кислотности лимонная кислота, ароматизатор "
            "натуральный, краситель концентрат чёрной моркови), белок молочный, закваска (Streptococcus "
            "thermophilus, Lactobacillus bulgaricus), бифидобактерии (Bifidobacterium lactis). "
            "Содержание молочнокислых микроорганизмов в конце срока годности не менее 1×10⁷ КОЕ/г, "
            "бифидобактерий не менее 1×10⁶ КОЕ/г. Продукт может содержать следы орехов и злаков.")
    yy = _para(c, comp, sx, y - 10, sw, "sansc", 5, 6.1, color=_hex("#2a1a20"))
    yy = _para(c, "Условия хранения: при температуре от +2 до +6 °C. После вскрытия упаковки хранить "
                  "не более 48 часов. Срок годности — 21 сутки.", sx, yy - 3, sw, "sansc", 5, 6.1,
               color=_hex("#2a1a20"))
    yy = _para(c, "Изготовитель: ООО «Молочная долина», 456789, Россия, Тихоречная обл., с. Заречное, "
                  "ул. Луговая, д. 1. Тел. горячей линии: 8 800 000-00-00. ТУ 10.51.52-004-12345678-2024. "
                  "Дата изготовления и годен до: см. на крышке.", sx, yy - 3, sw, "sansc", 5, 6.1,
               color=_hex("#2a1a20"))
    # знаки соответствия
    _stroke(c, "#2a1a20")
    c.setLineWidth(0.8)
    c.rect(sx, yy - 22, 22, 18, fill=0, stroke=1)
    _text(c, sx + 11, yy - 16, "ЕАС", "sansb", 8, "#2a1a20", "center")
    c.circle(sx + 40, yy - 13, 9, fill=0, stroke=1)
    _text(c, sx + 40, yy - 15.5, "PP", "sansb", 6, "#2a1a20", "center")
    _text(c, sx + 40, yy - 29, "5", "sansb", 6, "#2a1a20", "center")
    _para(c, "Упаковку после использования сдайте в пункт приёма вторсырья.", sx + 56, yy - 9, sw - 56,
          "sansc", 5, 6.1, color=_hex("#2a1a20"))
    # значки-обещания
    for i, (big, small) in enumerate([("0 %", "консервантов"), ("2,8 г", "белка в 100 г"),
                                      ("15 %", "кальция*"), ("10⁷", "живых культур")]):
        bx = sx + 34 + i * 80
        by = 150
        _fill(c, "#e63946" if i % 2 == 0 else "#3b1f2b")
        c.circle(bx, by, 29, fill=1, stroke=0)
        _stroke(c, "#ffffff")
        c.setLineWidth(1)
        c.circle(bx, by, 25, fill=0, stroke=1)
        _text(c, bx, by + 1, big, "sansb", 12, "#ffffff", "center")
        _lines(c, bx, by - 10, _wrap(c, small, "sans", 5.6, 40), "sans", 5.6, 6.5, "#ffffff", "center")
    # дата и партия — печать принтером
    _stroke(c, "#3b1f2b")
    c.setLineWidth(0.6)
    c.setDash(2, 2)
    c.rect(x, 108, tw, 44, fill=0, stroke=1)
    c.setDash()
    _text(c, x + 6, 142, "Дата изготовления / годен до / партия:", "sans", 6, "#5a3a46")
    _text(c, x + 6, 127, "ИЗГ 15.10.26  ГОДЕН ДО 05.11.26", "monob", 7.6, "#1a1a1a")
    _text(c, x + 6, 116, "ПАРТ. 2810-Б  СМЕНА 2  08:41", "mono", 7.6, "#1a1a1a")
    # предупреждающие значки
    iy = 38
    ics = [("temp", "Хранить при +2…+6 °C"), ("shake", "Перед употреблением взболтать"),
           ("nofreeze", "Не замораживать"), ("tri", "Не для детей до 3 лет")]
    for i, (k, t) in enumerate(ics):
        cx = 44 + i * 74
        _icon(c, cx, iy + 16, k, "#c62828" if k in ("tri", "nofreeze") else "#1d3557")
        lines = _wrap(c, t, "sansb", 5.8, 70)
        _lines(c, cx, iy - 4, lines, "sansb", 5.8, 6.8, "#2a1a20", "center")
    # штрихкод
    _ean13(c, W - 146, 36, "460123456789", 1.15, 40)
    c.save()


# ═══ 48. Результаты анализов ════════════════════════════════════════════

LAB = {
    "lab": "Клинико-диагностическая лаборатория «Медлаб-Плюс»",
    "addr": "Лицензия № ЛО-77-01-000000 · г. Северогорск, пр. Строителей, 21 · тел. +7 (000) 123-45-67",
    "fields": [("Пациент:", "Сорокина Елена Викторовна"), ("Дата рождения:", "12.04.1979 (47 лет)"),
               ("Пол:", "женский"), ("№ образца:", "2610-118402"),
               ("Дата взятия:", "20.10.2026  08:15"), ("Дата выдачи:", "21.10.2026  14:40"),
               ("Направивший врач:", "Гусейнова А. Р."), ("Отделение:", "терапевтическое, амбулаторно")],
    "sections": [
        ("ОБЩИЙ (КЛИНИЧЕСКИЙ) АНАЛИЗ КРОВИ", [
            ("Гемоглобин (HGB)", "118", "г/л", "120–150", "L"),
            ("Эритроциты (RBC)", "4,02", "×10¹²/л", "3,80–5,10", ""),
            ("Гематокрит (HCT)", "35,4", "%", "35,0–45,0", ""),
            ("Лейкоциты (WBC)", "11,6", "×10⁹/л", "4,0–9,0", "H"),
            ("Нейтрофилы, %", "74,2", "%", "47,0–72,0", "H"),
            ("Лимфоциты, %", "18,1", "%", "19,0–37,0", "L"),
            ("Тромбоциты (PLT)", "264", "×10⁹/л", "150–400", ""),
            ("СОЭ (по Вестергрену)", "28", "мм/ч", "2–20", "H")]),
        ("БИОХИМИЧЕСКИЙ АНАЛИЗ КРОВИ", [
            ("Глюкоза", "6,4", "ммоль/л", "3,9–5,9", "H"),
            ("Гликированный гемоглобин HbA1c", "6,1", "%", "< 6,0", "H"),
            ("Холестерин общий", "5,62", "ммоль/л", "< 5,20", "H"),
            ("ЛПНП", "3,48", "ммоль/л", "< 3,00", "H"),
            ("ЛПВП", "1,31", "ммоль/л", "> 1,20", ""),
            ("Креатинин", "71", "мкмоль/л", "44–80", ""),
            ("АЛТ", "24", "Ед/л", "< 33", ""),
            ("Ферритин", "11,2", "мкг/л", "13,0–150,0", "L"),
            ("С-реактивный белок", "14,8", "мг/л", "< 5,0", "H"),
            ("ТТГ", "2,10", "мМЕ/л", "0,40–4,00", "")]),
    ],
    "note": ("Комментарий: выявлены признаки воспалительного процесса (лейкоцитоз с нейтрофильным "
             "сдвигом, повышение СОЭ и С-реактивного белка) и снижение запасов железа. "
             "Рекомендуется консультация лечащего врача; при необходимости — повторный анализ через "
             "7–10 дней. Результаты не являются диагнозом и интерпретируются врачом с учётом клинической картины."),
}


def pdf_lab_results(path):
    from reportlab.lib.pagesizes import A4
    c = _canvas(path, A4)
    W, H = A4
    m = 40
    # шапка
    _fill(c, "#00796b")
    c.roundRect(m, H - 82, 46, 46, 8, fill=1, stroke=0)
    _fill(c, "#ffffff")
    c.rect(m + 19, H - 76, 8, 34, fill=1, stroke=0)
    c.rect(m + 6, H - 63, 34, 8, fill=1, stroke=0)
    _text(c, m + 58, H - 52, LAB["lab"], "sansb", 12.5, "#004d40")
    _text(c, m + 58, H - 66, LAB["addr"], "sans", 7, "#4a5a58")
    _text(c, m + 58, H - 77, "Система менеджмента качества сертифицирована по ГОСТ Р ИСО 15189-2015", "sans",
          7, "#4a5a58")
    c.setLineWidth(1.2)
    _stroke(c, "#00796b")
    c.line(m, H - 92, W - m, H - 92)
    _text(c, W / 2, H - 114, "РЕЗУЛЬТАТЫ ЛАБОРАТОРНЫХ ИССЛЕДОВАНИЙ", "sansb", 12, "#1a1a1a", "center")
    # поля
    y = H - 140
    cw = (W - 2 * m) / 2
    c.setLineWidth(0.5)
    _stroke(c, "#555555")
    for i, (k, v) in enumerate(LAB["fields"]):
        x = m + (i % 2) * cw
        yy = y - (i // 2) * 17
        _text(c, x, yy, k, "sansb", 8.5, "#333333")
        kx = x + _sw(k, "sansb", 8.5) + 6
        c.line(kx, yy - 2.5, x + cw - 14, yy - 2.5)
        _text(c, kx + 3, yy, v, "sans", 8.5, "#111111")
    y -= 4 * 17 + 10
    # таблица
    xs = [m, m + 218, m + 288, m + 352, m + 450]
    heads = ["Показатель", "Результат", "Ед. изм.", "Референсные значения", "Флаг"]
    for title, rows in LAB["sections"]:
        _fill(c, "#e0f2f1")
        c.rect(m, y - 5, W - 2 * m, 16, fill=1, stroke=0)
        _text(c, m + 6, y, title, "sansb", 8.5, "#004d40")
        y -= 17
        for h, x in zip(heads, xs):
            _text(c, x + 6, y, h, "sansb", 7.4, "#4a5a58")
        c.setLineWidth(0.8)
        _stroke(c, "#00796b")
        c.line(m, y - 4, W - m, y - 4)
        y -= 15
        c.setLineWidth(0.3)
        _stroke(c, "#b9c7c5")
        for name, res, unit, ref, flag in rows:
            ab = bool(flag)
            _text(c, xs[0] + 6, y, name, "sans", 8.4, "#111111")
            _text(c, xs[1] + 48, y, res, "sansb" if ab else "sans", 8.6,
                  "#b71c1c" if flag == "H" else "#0d47a1" if flag == "L" else "#111111", "right")
            _text(c, xs[2] + 6, y, unit, "sans", 8.4, "#333333")
            _text(c, xs[3] + 6, y, ref, "sans", 8.4, "#333333")
            if flag:
                col = "#b71c1c" if flag == "H" else "#0d47a1"
                _text(c, xs[4] + 8, y, "↑" if flag == "H" else "↓", "dejavub", 10, col)
                _text(c, xs[4] + 20, y, "выше нормы" if flag == "H" else "ниже нормы", "sans", 7, col)
            c.line(m, y - 4.5, W - m, y - 4.5)
            y -= 14.5
        y -= 10
    _text(c, m, y, "Метод: гематологический анализатор (5-diff), фотометрия, иммунотурбидиметрия, ИХЛА. "
                   "Материал: венозная кровь (ЭДТА, сыворотка).", "sans", 6.8, "#4a5a58")
    y = _para(c, LAB["note"], m, y - 18, W - 2 * m, "sans", 8.2, 11, align="justify") - 14
    # подпись и печать
    _text(c, m, y, "Врач клинической лабораторной диагностики", "sans", 8.5)
    c.setLineWidth(0.6)
    _stroke(c, "#111111")
    c.line(m + 200, y - 2, m + 300, y - 2)
    _text(c, m + 306, y, "/ Белова Н. А. /", "sans", 8.5)
    _stroke(c, "#3949ab")
    c.setLineWidth(1.2)
    sy = y - 30
    c.circle(W - m - 52, sy, 34, fill=0, stroke=1)
    c.circle(W - m - 52, sy, 25, fill=0, stroke=1)
    _text(c, W - m - 52, sy + 3, "МЕДЛАБ-", "sansb", 6.5, "#3949ab", "center")
    _text(c, W - m - 52, sy - 5, "ПЛЮС", "sansb", 6.5, "#3949ab", "center")
    c.saveState()
    c.translate(W - m - 52, sy)
    for k, ch in enumerate("ДЛЯ ДОКУМЕНТОВ * ЛАБОРАТОРИЯ * "):
        a = 90 - k * 360 / 31
        c.saveState()
        c.rotate(a)
        _text(c, 0, 27, ch, "sansb", 5.2, "#3949ab", "center")
        c.restoreState()
    c.restoreState()
    _text(c, m, y - 26, "Исследование выполнено: 21.10.2026 13:52, лаборант Юсупова К. Р.", "sans", 8, "#333333")
    _text(c, m, y - 40, "Контроль качества: внутрилабораторный контроль пройден (серия 2610-QC-07).", "sans", 8,
          "#333333")
    # QR проверки подлинности
    q, qx, qy = 58, m, 62
    rng = random.Random(48)
    cell = q / 21
    for i in range(21):
        for j in range(21):
            fin = (i < 7 and j < 7) or (i < 7 and j > 13) or (i > 13 and j < 7)
            on = (i in (0, 6, 14, 20) or j in (0, 6, 14, 20) or (2 <= i % 14 <= 4 and 2 <= j % 14 <= 4)) if fin                 else rng.random() < 0.5
            if on:
                _fill(c, "#111111")
                c.rect(qx + j * cell, qy + q - (i + 1) * cell, cell, cell, fill=1, stroke=0)
    _para(c, "Проверить подлинность результатов: отсканируйте QR-код или введите номер образца "
             "и код 7F3K-29QD на сайте лаборатории.", qx + q + 10, qy + q - 10, 230, "sans", 7.4, 9.6,
          color=(0.29, 0.35, 0.35))
    _text(c, m, 46, "Флаги: ", "sans", 6.8, "#4a5a58")
    fx = m + _sw("Флаги: ", "sans", 6.8)
    for t, f in [("↑", "dejavu"), (" — выше референсного интервала, ", "sans"), ("↓", "dejavu"),
                 (" — ниже референсного интервала.", "sans")]:
        _text(c, fx, 46, t, f, 6.8, "#4a5a58")
        fx += _sw(t, f, 6.8)
    _text(c, m, 36, "Референсные значения указаны для взрослых женщин. Документ сформирован автоматически "
                    "и действителен без подписи.", "sans", 6.8, "#4a5a58")
    _text(c, W - m, 36, "Стр. 1 из 1", "sans", 6.8, "#4a5a58", "right")
    c.save()


# ═══ 49. Календарь на месяц ═════════════════════════════════════════════

CAL_EVENTS = {
    1: ["9:30 Планёрка отдела"], 2: ["Сдача квартального отчёта"], 4: ["14:00 Встреча с поставщиком", "Заказать канцтовары"],
    7: ["Корпоратив: бронь зала"], 8: ["Выходной (перенос)"], 9: ["9:30 Планёрка отдела", "Аудит склада"],
    11: ["Вебинар по охране труда 11:00"], 14: ["День рождения М. Сафиной"], 15: ["Командировка: Кедровск"],
    16: ["Командировка: Кедровск", "Вернуться к 19:00"], 17: ["Отчёт по командировке"],
    18: ["Закрытие заявок на премии"], 21: ["Инвентаризация (весь день)"], 23: ["9:30 Планёрка", "Бюджет на 2027"],
    24: ["Последний день подачи счетов"], 25: ["Ёлка для детей сотрудников 16:00"], 28: ["Сверка с бухгалтерией"],
    5: ["Дежурство: Носов П. А."], 13: ["Ярмарка у офиса 11:00"], 20: ["Дежурство: Ким Л. С."],
    27: ["Дежурство: Носов П. А.", "Проверка сигнализации"],
    29: ["Сокращённый рабочий день"], 30: ["Подведение итогов года"], 31: ["Новогодний вечер"],
}


def pdf_calendar(path):
    import calendar
    from reportlab.lib.pagesizes import A4, landscape
    c = _canvas(path, landscape(A4))
    W, H = landscape(A4)
    m = 28
    year, month = 2026, 12
    _fill(c, "#1b3a4b")
    c.rect(0, H - 80, W, 80, fill=1, stroke=0)
    _text(c, m, H - 50, "ДЕКАБРЬ", "sansb", 30, "#ffffff")
    _text(c, m + _sw("ДЕКАБРЬ", "sansb", 30) + 10, H - 50, "2026", "sans", 30, "#9cc5d9")
    _text(c, m, H - 68, "Рабочий календарь отдела закупок · ООО «Полярная звезда»", "sans", 8.5, "#cfe3ec")

    def mini(x, y, yy, mm, title):
        _text(c, x, y, title, "sansb", 7.5, "#ffffff")
        for k, d in enumerate("ПВСЧПСВ"):
            _text(c, x + k * 13 + 5, y - 10, d, "sansb", 5.5, "#9cc5d9", "center")
        for r, wk in enumerate(calendar.monthcalendar(yy, mm)):
            for k, d in enumerate(wk):
                if d:
                    _text(c, x + k * 13 + 5, y - 18 - r * 7, str(d), "sans", 5.5,
                          "#ffb4a2" if k >= 5 else "#ffffff", "center")

    mini(W - 220, H - 14, 2026, 11, "Ноябрь 2026")
    mini(W - 115, H - 14, 2027, 1, "Январь 2027")
    weeks = calendar.monthcalendar(year, month)
    top = H - 92
    hh = 18
    bot = 70
    cw = (W - 2 * m) / 7
    rh = (top - hh - bot) / len(weeks)
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    for k, d in enumerate(days):
        _fill(c, "#c0392b" if k >= 5 else "#2c5d73")
        c.rect(m + k * cw, top - hh, cw, hh, fill=1, stroke=0)
        _text(c, m + k * cw + cw / 2, top - hh + 5.5, d.upper(), "sansb", 8, "#ffffff", "center")
    holidays = {31: "Канун Нового года"}
    prev_last = calendar.monthrange(2026, 11)[1]
    c.setLineWidth(0.5)
    for r, wk in enumerate(weeks):
        for k, d in enumerate(wk):
            x = m + k * cw
            y = top - hh - (r + 1) * rh
            if d == 0:
                _fill(c, "#f1f3f4")
            elif d in holidays:
                _fill(c, "#fde2e0")
            elif k >= 5:
                _fill(c, "#fdf1ef")
            else:
                _fill(c, "#ffffff")
            _stroke(c, "#b8c4cc")
            c.rect(x, y, cw, rh, fill=1, stroke=1)
            if d == 0:
                dd = (prev_last - (wk.index(next(v for v in wk if v)) - k - 1)) if r == 0 else (k - wk.index(0) + 1 if 0 in wk else 0)
                if r == 0:
                    first = next(i for i, v in enumerate(wk) if v)
                    dd = prev_last - (first - k) + 1
                else:
                    last = max(i for i, v in enumerate(wk) if v)
                    dd = k - last
                _text(c, x + cw - 6, y + rh - 16, str(dd), "sansb", 12, "#c3c9ce", "right")
                continue
            _text(c, x + cw - 6, y + rh - 17, str(d), "sansb", 14,
                  "#c0392b" if (k >= 5 or d in holidays) else "#1b3a4b", "right")
            if d in holidays:
                _text(c, x + 5, y + rh - 12, holidays[d], "sansb", 6.5, "#c0392b")
            ev = CAL_EVENTS.get(d, [])
            yy = y + rh - 30
            for e in ev:
                lines = _wrap(c, e, "sans", 7, cw - 16)
                _fill(c, "#e67e22" if "Командировка" in e else "#8e44ad" if "Дежурство" in e
                      else "#2980b9" if e[:1].isdigit() else "#16a085")
                c.rect(x + 4, yy - 1.5 - (len(lines) - 1) * 8.2, 2, 8 + (len(lines) - 1) * 8.2, fill=1, stroke=0)
                for ln in lines:
                    _text(c, x + 9, yy, ln, "sans", 7, "#2b2b2b")
                    yy -= 8.2
                yy -= 2.5
    # легенда и заметки
    ly = 48
    for i, (col, t) in enumerate([("#2980b9", "Встречи и совещания"), ("#e67e22", "Командировки"),
                                  ("#16a085", "Сроки и задачи"), ("#8e44ad", "Дежурства"),
                                  ("#fde2e0", "Праздничные и предпраздничные дни")]):
        x = m + i * 140
        _fill(c, col)
        c.rect(x, ly, 10, 8, fill=1, stroke=0)
        _text(c, x + 14, ly + 1, t, "sans", 7.5, "#3a4a54")
    _text(c, m, 28, "Заметки: график отпусков на 2027 год согласовать до 18 декабря; пропуска на январские "
                    "праздники оформляет служба безопасности.", "sans", 7.5, "#3a4a54")
    c.save()


# ═══ 50. Резюме с тёмной боковой колонкой ═══════════════════════════════

CV = {
    "name": "Лебедева Анна Сергеевна",
    "role": "Ведущий аналитик данных",
    "contacts": [("Телефон", "+7 (900) 000-12-34"), ("E-mail", "a.lebedeva@example.com"),
                 ("Город", "Светлогорск, готова к переезду"), ("Telegram", "@a_lebedeva_data")],
    "skills": [("Python, pandas", 0.92), ("SQL / PostgreSQL", 0.88), ("Power BI, Tableau", 0.8),
               ("Статистика, A/B-тесты", 0.84), ("Машинное обучение", 0.66), ("Airflow, dbt", 0.58)],
    "langs": [("Русский", "родной", 5), ("Английский", "C1, свободный", 4), ("Немецкий", "B1, разговорный", 2)],
    "hobby": "Горные походы, настольные игры, волонтёрство в приюте для животных",
    "profile": ("Аналитик данных с 8-летним опытом в розничной торговле и финтехе. Строю отчётность "
                "с нуля, автоматизирую расчёт ключевых метрик и помогаю командам принимать решения "
                "на основе экспериментов. Руководила группой из четырёх аналитиков."),
    "jobs": [
        ("Ведущий аналитик данных", "ООО «Северный каскад», розничная сеть", "03.2022 — н. в.",
         ["Построила систему еженедельной отчётности для 140 магазинов, сократив ручной труд на 30 часов в неделю.",
          "Запустила платформу A/B-тестирования промоакций; рост выручки по пилотным категориям — 6,5 %.",
          "Наставник для двух младших аналитиков, провела внутренний курс по SQL для 25 сотрудников."]),
        ("Аналитик данных", "АО «Ладья Финанс», онлайн-кредитование", "06.2019 — 02.2022",
         ["Разработала модель оттока клиентов (ROC AUC 0,81), которая легла в основу программы удержания.",
          "Перевела 40 отчётов из Excel в Power BI с автоматическим обновлением.",
          "Совместно с рисками оптимизировала скоринговые правила: доля просрочки снизилась на 1,2 п. п."]),
        ("Младший аналитик", "ООО «Дельта Маркет»", "09.2017 — 05.2019",
         ["Подготовка ежемесячных отчётов по продажам и остаткам для коммерческой дирекции.",
          "Очистка и сверка данных из трёх учётных систем."]),
    ],
    "edu": [("Магистр, прикладная математика и информатика", "Светлогорский государственный университет", "2015 — 2017"),
            ("Бакалавр, экономика", "Светлогорский государственный университет", "2011 — 2015")],
    "tools": ["Jupyter", "Git", "Docker", "ClickHouse", "Metabase", "Excel", "Jira", "Confluence"],
    "projects": [("Прогноз спроса на 6 недель вперёд",
                  "Модель градиентного бустинга для 2 300 товаров; ошибка прогноза снижена с 24 до 15 %, "
                  "списания свежей продукции — на 9 %."),
                 ("Единая витрина данных о клиентах",
                  "Объединила данные кассы, программы лояльности и интернет-магазина; время подготовки "
                  "маркетинговых выборок сократилось с двух дней до часа.")],
    "certs": ["Сертификат «Анализ данных в Python», 2021", "Курс «Продуктовая аналитика», 120 ч, 2023"],
}


def pdf_cv_sidebar(path):
    from reportlab.lib.pagesizes import A4
    c = _canvas(path, A4)
    W, H = A4
    sbw = 186
    _fill(c, "#22313f")
    c.rect(0, 0, sbw, H, fill=1, stroke=0)
    # фото-заглушка
    pcx, pcy = sbw / 2, H - 92
    _fill(c, "#3d5568")
    c.circle(pcx, pcy, 52, fill=1, stroke=0)
    _fill(c, "#8fa9bd")
    c.circle(pcx, pcy + 12, 20, fill=1, stroke=0)
    c.saveState()
    p = c.beginPath()
    p.circle(pcx, pcy, 52)
    c.clipPath(p, stroke=0)
    c.ellipse(pcx - 36, pcy - 64, pcx + 36, pcy - 6, fill=1, stroke=0)
    c.restoreState()
    _stroke(c, "#f0a500")
    c.setLineWidth(3)
    c.circle(pcx, pcy, 54, fill=0, stroke=1)
    x = 20
    w = sbw - 40

    def side_head(y, t):
        _text(c, x, y, t, "sansb", 10, "#f0a500")
        c.setLineWidth(0.6)
        _stroke(c, "#4a6274")
        c.line(x, y - 5, x + w, y - 5)
        return y - 20

    y = side_head(H - 172, "КОНТАКТЫ")
    for k, v in CV["contacts"]:
        _text(c, x, y, k, "sansb", 7, "#9db3c4")
        y = _para(c, v, x, y - 10, w, "sans", 8.5, 10.5, color=(1, 1, 1)) - 5
    y = side_head(y - 8, "НАВЫКИ")
    for k, v in CV["skills"]:
        _text(c, x, y, k, "sans", 8.2, "#ffffff")
        _fill(c, "#3d5568")
        c.roundRect(x, y - 9, w, 4, 2, fill=1, stroke=0)
        _fill(c, "#f0a500")
        c.roundRect(x, y - 9, w * v, 4, 2, fill=1, stroke=0)
        y -= 22
    y = side_head(y - 4, "ЯЗЫКИ")
    for k, lvl, n in CV["langs"]:
        _text(c, x, y, k, "sansb", 8.2, "#ffffff")
        for i in range(5):
            _fill(c, "#f0a500" if i < n else "#3d5568")
            c.circle(x + w - 44 + i * 10, y + 3, 3.4, fill=1, stroke=0)
        _text(c, x, y - 10, lvl, "sans", 7.2, "#9db3c4")
        y -= 24
    y = side_head(y - 4, "ИНСТРУМЕНТЫ")
    cx_ = x
    for t in CV["tools"]:
        tw_ = _sw(t, "sans", 7.4) + 10
        if cx_ + tw_ > x + w:
            cx_ = x
            y -= 17
        _fill(c, "#34495e")
        c.roundRect(cx_, y - 4, tw_, 13, 6, fill=1, stroke=0)
        _text(c, cx_ + 5, y, t, "sans", 7.4, "#e6edf2")
        cx_ += tw_ + 4
    y = side_head(y - 26, "ИНТЕРЕСЫ")
    y = _para(c, CV["hobby"], x, y, w, "sans", 8, 10.5, color=(0.86, 0.9, 0.93))
    y = side_head(y - 10, "ДОПОЛНИТЕЛЬНО")
    _para(c, "Водительское удостоверение категории B. Готова к командировкам до 30 % времени.",
          x, y, w, "sans", 8, 10.5, color=(0.86, 0.9, 0.93))
    # правая колонка
    rx = sbw + 30
    rw = W - rx - 34
    _text(c, rx, H - 68, CV["name"].split()[0].upper(), "sansb", 26, "#22313f")
    _text(c, rx, H - 92, " ".join(CV["name"].split()[1:]), "sans", 17, "#22313f")
    _fill(c, "#f0a500")
    c.rect(rx, H - 112, 46, 3, fill=1, stroke=0)
    _text(c, rx, H - 128, CV["role"], "sansb", 11, "#c47f00")

    def head(y, t):
        _fill(c, "#22313f")
        c.circle(rx + 5, y + 4, 5, fill=1, stroke=0)
        _text(c, rx + 16, y, t, "sansb", 11, "#22313f")
        c.setLineWidth(0.5)
        _stroke(c, "#c9d3db")
        c.line(rx + 16 + _sw(t, "sansb", 11) + 8, y + 4, rx + rw, y + 4)
        return y - 18

    y = head(H - 160, "О СЕБЕ")
    y = _para(c, CV["profile"], rx, y, rw, "serif", 9.2, 12.6, align="justify") - 10
    y = head(y, "ОПЫТ РАБОТЫ")
    for title, comp, dates, items in CV["jobs"]:
        _text(c, rx, y, title, "sansb", 9.8, "#1a1a1a")
        dw = _sw(dates, "sansb", 8) + 12
        _fill(c, "#eef2f5")
        c.roundRect(rx + rw - dw, y - 3, dw, 13, 3, fill=1, stroke=0)
        _text(c, rx + rw - 6, y, dates, "sansb", 8, "#22313f", "right")
        _text(c, rx, y - 12, comp, "sans", 8.5, "#c47f00")
        y -= 26
        for it in items:
            _fill(c, "#22313f")
            c.rect(rx + 3, y + 2.5, 3, 3, fill=1, stroke=0)
            y = _para(c, it, rx + 12, y, rw - 12, "serif", 8.8, 11.4) - 2.5
        y -= 8
    y = head(y, "ОБРАЗОВАНИЕ")
    for deg, school, dates in CV["edu"]:
        _text(c, rx, y, deg, "sansb", 9, "#1a1a1a")
        _text(c, rx + rw, y, dates, "sansb", 8, "#22313f", "right")
        _text(c, rx, y - 11, school, "sans", 8.4, "#5a6570")
        y -= 26
    y = head(y - 4, "КЛЮЧЕВЫЕ ПРОЕКТЫ")
    for t, d in CV["projects"]:
        _text(c, rx, y, t, "sansb", 9, "#1a1a1a")
        y = _para(c, d, rx, y - 11.5, rw, "serif", 8.8, 11.4) - 6
    y = head(y - 4, "КУРСЫ И СЕРТИФИКАТЫ")
    for it in CV["certs"]:
        _fill(c, "#22313f")
        c.rect(rx + 3, y + 2.5, 3, 3, fill=1, stroke=0)
        y = _para(c, it, rx + 12, y, rw - 12, "serif", 8.8, 11.4) - 3
    c.save()


RECIPES = [
    ("41_annual_report", "pdf", pdf_annual_report, "RU", "EN", "pdf",
     "годовой отчёт 2 стр.: плитки KPI, столбчатая с подписями осей и значений, круговая с выносками, легенда, сноски"),
    ("42_poster_sci", "pdf", pdf_poster_sci, "EN", "RU", "pdf",
     "научный постер A3 альбомный: цветная полоса заголовка, 3 колонки, графики, таблица, литература 7 pt"),
    ("43_magazine_wrap", "pdf", pdf_magazine_wrap, "RU", "DE", "pdf",
     "журнал: 2 колонки обтекают круглое фото (ширина строк разная), буквица, вынос между колонками, колонтитулы"),
    ("44_contract", "pdf", pdf_contract, "RU", "EN", "pdf",
     "договор 2 стр.: пункты 1./1.1./1.1.1. с висячим отступом, жирные термины, надстрочные сноски, подписи в 2 колонки, М.П."),
    ("45_timetable", "pdf", pdf_timetable, "RU", "UZ", "pdf",
     "расписание A4 альбомное: 11×14, объединённые и повёрнутые на 90° заголовки, 6,5 pt, зебра, тонкие линии"),
    ("46_flowchart", "pdf", pdf_flowchart, "EN", "RU", "pdf",
     "блок-схема с дорожками: прямоугольники, скругления, ромбы, стрелки с Yes/No, повёрнутые подписи дорожек"),
    ("47_label_pack", "pdf", pdf_label_pack, "RU", "KK", "pdf",
     "этикетка: бренд белым на тёмной полосе, таблица пищевой ценности, состав 5 pt узким, штрихкод с цифрами, значки"),
    ("48_lab_results", "pdf", pdf_lab_results, "RU", "EN", "pdf",
     "анализы: поля с подчёркиванием, таблица Показатель/Результат/Ед./Референс/флаг ↑↓, ×10⁹/л, печать по кругу"),
    ("49_calendar", "pdf", pdf_calendar, "RU", "EN", "pdf",
     "календарь месяца 7×5 альбомный: шапка дней, числа, события 7 pt в клетках, выходные и праздник цветом"),
    ("50_cv_sidebar", "pdf", pdf_cv_sidebar, "RU", "EN", "pdf",
     "резюме: тёмная левая колонка с белым текстом и шкалами, разделы справа, даты по правому краю, списки"),
]
