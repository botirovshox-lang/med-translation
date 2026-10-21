"""Brand pack of SimpleTranslate: one source of geometry and colors, every file built from it.

    python tools/brand_build.py            # build brand/pack/*
    python tools/brand_build.py --apply    # also copy favicon, logo, OG into landing/

The mark is a keycap with 文 (top left) and A (bottom right) on a blue tile. The wordmark is
drawn from Unbounded outlines (brand/fonts), the i-dot replaced by a small key. Raster files
are rendered by headless Chrome from generated HTML, so text in templates uses the real fonts.
Nothing here calls a network service.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
B = ROOT / "brand"
FONTS = B / "fonts"
OUT = B / "pack"
TMP = Path(tempfile.gettempdir()) / "st-brand-build"   # вне репозитория: профиль Chrome и черновики HTML

# ---------------------------------------------------------------- tokens
C = {
    "blue": "#0A5CF0",      # tile, primary button, links on paper (large)
    "deep": "#0640A8",      # key thickness, pressed button
    "blue_ink": "#0848C2",  # blue text on paper and white
    "blue_dk": "#5B93FF",   # blue on ink backgrounds (key-dot, links)
    "ink": "#0B1324",       # text, dark panels
    "ink2": "#44516A",      # secondary text, source line
    "paper": "#F2F5FA",     # page background
    "line": "#DAE2EE",      # hairlines
    "teal": "#16C9B4",      # only "free" and "done"
    "teal_ink": "#06302A",  # text on teal
    "white": "#FFFFFF",
}

# ---------------------------------------------------------------- mark geometry (64-unit grid)
LEG1 = "M21.5 13.4 V16.4 M14.6 18.9 H28.4 M17.1 20.9 Q20.8 28.9 28.4 31.2 M25.9 20.9 Q22.2 28.9 14.6 31.2"
LEG2 = "M34.6 43.6 L42 25.2 L49.4 43.6 M37.3 37.4 H46.7"
LEG1_B = "M21 10.5 V12.5 M13 17.5 H29 M16 20 Q20.5 29 29 32 M26 20 Q21.5 29 13 32"
LEG2_B = "M34 46 L42.5 24 L51 46 M37.2 38.6 H47.8"
# Cyrillic option for the top-left legend (BRAND_LEGEND=ya): same stroke and zone as 文
if os.environ.get("BRAND_LEGEND") == "ya":
    LEG1 = "M27.4 14 V31 M27.4 14 H20 Q15 14 15 18.9 Q15 23.8 20 23.8 H27.4 M21.4 23.8 L15 31"
    LEG1_B = "M28.4 11 V32 M28.4 11 H19.6 Q13.6 11 13.6 16.6 Q13.6 22.2 19.6 22.2 H28.4 M21 22.2 L13.6 32"


def key(bold=False, l1=C["ink"], l2=C["blue"], skirt=C["deep"], top=C["white"]):
    """The keycap alone, on the 64 grid. bold = the cut for 16–31 px and avatars."""
    if bold:
        return (f'<rect x="6" y="10" width="52" height="48" rx="12" fill="{skirt}"/>'
                f'<rect x="6" y="6" width="52" height="45" rx="12" fill="{top}"/>'
                f'<path d="{LEG1_B}" fill="none" stroke="{l1}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
                f'<path d="{LEG2_B}" fill="none" stroke="{l2}" stroke-width="5.6" stroke-linecap="round" stroke-linejoin="round"/>')
    return (f'<rect x="8" y="11" width="48" height="45" rx="12" fill="{skirt}"/>'
            f'<rect x="8" y="8" width="48" height="41" rx="12" fill="{top}"/>'
            f'<path d="{LEG1}" fill="none" stroke="{l1}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="{LEG2}" fill="none" stroke="{l2}" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"/>')


def mark_body(bold=False):
    r = 14 if bold else 15
    return f'<rect width="64" height="64" rx="{r}" fill="{C["blue"]}"/>' + key(bold)


def mark_mono():
    """One ink, for one-colour print and stamps: tile and legends in ink, key cut out to paper."""
    ink = C["ink"]
    return (f'<rect width="64" height="64" rx="15" fill="{ink}"/>'
            f'<rect x="8" y="8" width="48" height="41" rx="12" fill="{C["white"]}"/>'
            f'<path d="{LEG1} {LEG2}" fill="none" stroke="{ink}" stroke-width="3.8" stroke-linecap="round" stroke-linejoin="round"/>')


AVATAR_KEY_SCALE = 0.9   # key spans 73% of the circle; the corner stays 5% inside the crop


def avatar_body(round_=False):
    """Square avatar (platforms crop it to a circle). Bold cut: avatars are seen at 32–48 px."""
    bg = (f'<circle cx="32" cy="32" r="32" fill="{C["blue"]}"/>' if round_
          else f'<rect width="64" height="64" fill="{C["blue"]}"/>')
    s = AVATAR_KEY_SCALE
    return bg + f'<g transform="translate(32 32) scale({s}) translate(-32 -32)">{key(bold=True)}</g>'


def svg(body, w=64, h=64, vb=None, title=None):
    t = f"<title>{title}</title>" if title else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb or f"0 0 {w} {h}"}" '
            f'width="{w}" height="{h}">{t}{body}</svg>\n')


# ---------------------------------------------------------------- wordmark from Unbounded outlines
WM_TEXT = "S\u0131mpleTranslate"     # dotless i: the dot becomes a key
WM_WGHT = 650
WM_TRACK = -0.012                    # of em per glyph


def wordmark_data():
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.recordingPen import RecordingPen, DecomposingRecordingPen
    import uharfbuzz as hb

    f = instancer.instantiateVariableFont(TTFont(FONTS / "Unbounded-Variable.ttf"), {"wght": WM_WGHT})
    buf = io.BytesIO(); f.save(buf); data = buf.getvalue()
    f = TTFont(io.BytesIO(data))
    upem, gs, cmap = f["head"].unitsPerEm, f.getGlyphSet(), f.getBestCmap()
    font = hb.Font(hb.Face(data))
    b = hb.Buffer(); b.add_str(WM_TEXT); b.guess_segment_properties()
    hb.shape(font, b, {"kern": True, "liga": False})
    pen, bounds, x, origins = SVGPathPen(gs), BoundsPen(gs), 0.0, []
    for info, pos in zip(b.glyph_infos, b.glyph_positions):
        g = f.getGlyphName(info.codepoint)
        origins.append((g, x))
        gs[g].draw(TransformPen(pen, (1, 0, 0, -1, x + pos.x_offset, 0)))
        gs[g].draw(TransformPen(bounds, (1, 0, 0, 1, x, 0)))
        x += pos.x_advance + WM_TRACK * upem
    xmin, ymin, xmax, ymax = bounds.bounds
    # the dot of a real i = its topmost contour
    rec = DecomposingRecordingPen(gs); gs[cmap[ord("i")]].draw(rec)
    contours, cur = [], []
    for op, args in rec.value:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(cur); cur = []
    dot = None
    for c in contours:
        p = RecordingPen(); p.value = c; bp = BoundsPen(gs); p.replay(bp)
        if bp.bounds and (dot is None or bp.bounds[1] > dot[1]):
            dot = bp.bounds
    g1, x1 = origins[1]
    bd = BoundsPen(gs); gs[g1].draw(bd)
    cx = x1 + (bd.bounds[0] + bd.bounds[2]) / 2
    side = max(dot[2] - dot[0], dot[3] - dot[1]) * 1.18
    sq = (cx - side / 2, -(dot[1] + side), side, side, side * 0.27)
    ytop = min(sq[1], -ymax)
    return {"d": pen.getCommands(), "dot": sq, "vb": (xmin, ytop, xmax - xmin, -ymin - ytop),
            "cap": f["OS/2"].sCapHeight}


def wm_group(wm, ink, dotc):
    x, y, w, h, r = wm["dot"]
    return (f'<path d="{wm["d"]}" fill="{ink}"/>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r:.1f}" fill="{dotc}"/>')


def wordmark_svg(wm, ink, dotc, height=100):
    vx, vy, vw, vh = wm["vb"]
    w = height * vw / vh
    return svg(wm_group(wm, ink, dotc), round(w), height, vb=f"{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}",
               title="SimpleTranslate")


def lockup(wm, kind="h", dark=False, m=64.0):
    """Horizontal or vertical lockup, mark size m. Cap height = m / 1.75, gap = cap * 0.55."""
    ink = C["white"] if dark else C["ink"]
    dotc = C["blue_dk"] if dark else C["blue"]
    vx, vy, vw, vh = wm["vb"]
    cap = m / 1.75
    k = cap / wm["cap"]
    g = wm_group(wm, ink, dotc)
    if kind == "h":
        gap = cap * 0.55
        base = m / 2 + cap / 2
        bottom = max(m, base + (vy + vh) * k)
        top = min(0.0, base + vy * k)
        W = m + gap + vw * k
        body = (mark_body() + f'<g transform="translate({m + gap - vx * k:.2f} {base:.2f}) scale({k:.5f})">{g}</g>')
        return svg(body, round(W * 4), round((bottom - top) * 4), vb=f"0 {top:.2f} {W:.2f} {bottom - top:.2f}",
                   title="SimpleTranslate")
    # vertical: mark centered above, wordmark below
    capv = m / 2.4
    k = capv / wm["cap"]
    W = max(m, vw * k)
    gap = capv * 0.9
    base = m + gap - vy * k
    H = base + (vy + vh) * k
    mx = (W - m) / 2
    body = (f'<g transform="translate({mx:.2f} 0)">{mark_body()}</g>'
            f'<g transform="translate({(W - vw * k) / 2 - vx * k:.2f} {base:.2f}) scale({k:.5f})">{g}</g>')
    return svg(body, round(W * 4), round(H * 4), vb=f"0 0 {W:.2f} {H:.2f}", title="SimpleTranslate")


# ---------------------------------------------------------------- rendering
def chrome():
    if os.environ.get("BRAND_CHROME"):
        return os.environ["BRAND_CHROME"]
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/usr/bin/google-chrome", "/usr/bin/chromium"):
        if os.path.exists(p):
            return p
    sys.exit("нужен Chrome или Edge для отрисовки PNG и PDF (или путь в BRAND_CHROME)")


FONT_CSS = """
@font-face{font-family:"Manrope";src:url("%(fonts)s/Manrope-Variable.ttf") format("truetype");font-weight:200 800}
@font-face{font-family:"Unbounded";src:url("%(fonts)s/Unbounded-Variable.ttf") format("truetype");font-weight:200 900}
"""


def page(body, css, w, h, transparent=False):
    bg = "transparent" if transparent else C["paper"]
    fonts = FONTS.resolve().as_uri()
    tok = ";".join(f"--{k.replace('_', '-')}:{v}" for k, v in C.items())
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{FONT_CSS % {'fonts': fonts}}"
            f":root{{{tok}}}*{{box-sizing:border-box}}html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg}}}"
            f"body{{font-family:Manrope,sans-serif;color:var(--ink);-webkit-font-smoothing:antialiased}}"
            f".h{{font-family:Unbounded,Manrope,sans-serif;font-weight:600;letter-spacing:-.015em;margin:0}}"
            f"{css}</style></head><body>{body}</body></html>")


_n = [0]


def render(html, w, h, out, transparent=False):
    TMP.mkdir(parents=True, exist_ok=True)
    _n[0] += 1
    src = TMP / f"p{_n[0]}.html"
    src.write_text(html, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            f"--user-data-dir={TMP / 'chrome'}", f"--window-size={w},{h}", "--virtual-time-budget=4000",
            "--force-device-scale-factor=1"]
    if out.suffix == ".pdf":
        args += [f"--print-to-pdf={out}", "--no-pdf-header-footer"]
    else:
        args += [f"--screenshot={out}"]
        if transparent:
            args += ["--default-background-color=00000000"]
    subprocess.run(args + [src.resolve().as_uri()], check=True, timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not out.exists():
        sys.exit(f"не отрисовался {out}")


def data_uri(svgtext):
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(svgtext.encode("utf-8")).decode()


def svg_png(svgtext, w, h, out):
    uri = data_uri(svgtext)
    render(page(f'<img src="{uri}" width="{w}" height="{h}" style="display:block">', "", w, h, True), w, h, out, True)


# ---------------------------------------------------------------- shared HTML parts
SIG_CSS = """
.sig{display:flex;gap:.7em;align-items:stretch}
.sig .n{font-weight:700;font-size:.8em;color:var(--blue-ink);font-variant-numeric:tabular-nums;padding-top:.15em;min-width:1.6em;text-align:right}
.sig .br{width:.42em;border:.12em solid var(--blue);border-right:0;border-radius:.18em 0 0 .18em;flex:none}
.sig .l{display:flex;flex-direction:column;gap:.28em}
.sig .s{color:var(--ink2);line-height:1.35}
.sig .t{color:var(--ink);font-weight:700;line-height:1.35;font-size:1.06em}
.sig u{text-decoration:underline .12em var(--blue);text-underline-offset:.2em;text-decoration-skip-ink:none}
.dark .sig .s{color:#AFC0DA}.dark .sig .t{color:#fff}.dark .sig .n{color:var(--blue-dk)}
.dark .sig .br{border-color:var(--blue-dk)}.dark .sig u{text-decoration-color:var(--blue-dk)}
.btn{display:inline-block;font-weight:700;background:var(--blue);color:#fff;border-radius:.55em;padding:.7em 1.1em;box-shadow:0 .18em 0 var(--deep)}
.chip{display:inline-block;font-weight:700;background:var(--teal);color:var(--teal-ink);border-radius:999px;padding:.45em .85em}
.lk{display:block}
"""

PAIRS = [
    ("12", "Принимать по <u>300&nbsp;мг/сут</u>, <u>не&nbsp;ранее</u> <u>18</u>&nbsp;лет.",
     "Take <u>300&nbsp;mg/day</u>, <u>not before</u> age&nbsp;<u>18</u>."),
    ("13", "Срок оплаты — <u>10</u>&nbsp;банковских дней.", "To‘lov muddati — <u>10</u>&nbsp;bank kuni."),
    ("14", "Store below <u>25&nbsp;°C</u>. <u>Do not</u> freeze.", "Хранить при температуре ниже <u>25&nbsp;°C</u>. <u>Не</u>&nbsp;замораживать."),
]


def sig(pairs):
    return "".join(f'<div class="sig"><span class="n">{n}</span><span class="br"></span>'
                   f'<div class="l"><div class="s">{s}</div><div class="t">{t}</div></div></div>' for n, s, t in pairs)


T = {
    "ru": {
        "tag": "Перевод документов на любой язык — в оформлении оригинала",
        "eyebrow": "ПРОВЕРКА КАЖДОЙ СТРОКИ",
        "post_h": "Цифры в переводе те же, что в оригинале",
        "offer_a": "Первые", "offer_b": "страниц бесплатно",
        "cta": "Перевести документ",
        "og_h1": "Переведём на любой язык.", "og_h2": "В один клик.",
        "og_p": "Word, PDF, Excel, PowerPoint и сканы. Таблицы, рисунки и сноски остаются на своих местах.",
        "free": "5 страниц бесплатно",
        "lines": "Сверяем каждую строку: числа, единицы и отрицания",
    },
    "uz": {
        "tag": "Hujjatlarni istalgan tilga tarjima qilamiz — asl ko‘rinishida",
        "eyebrow": "HAR BIR QATOR TEKSHIRILADI",
        "post_h": "Tarjimadagi raqamlar asl nusxadagidek",
        "offer_a": "Birinchi", "offer_b": "sahifa bepul",
        "cta": "Hujjatni tarjima qilish",
        "og_h1": "Istalgan tilga tarjima qilamiz.", "og_h2": "Bir bosishda.",
        "og_p": "Word, PDF, Excel, PowerPoint va skanlar. Jadvallar, rasmlar va izohlar o‘z joyida qoladi.",
        "free": "5 sahifa bepul",
        "lines": "Har bir qatorni tekshiramiz: raqamlar, birliklar va inkorlar",
    },
}


def ty(s):
    """Типографика заголовков: короткое слово (1–2 буквы) не висит в конце строки, тире не начинает строку."""
    import re
    s = re.sub(r"(?<![\w&])(\w{1,2}) (?=\S)", lambda m: m.group(1) + "\u00a0", s)
    return s.replace(" \u2014", "\u00a0\u2014")


def lk_img(svgtext, height):
    uri = data_uri(svgtext)
    return f'<img class="lk" src="{uri}" style="height:{height}px;width:auto">'


# ---------------------------------------------------------------- build
def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("logo", "avatar", "social", "templates", "print", "web"):
        (OUT / d).mkdir(parents=True)
    wm = wordmark_data()
    (B / "wordmark.json").write_text(json.dumps({"vb": wm["vb"], "cap": wm["cap"], "dot": wm["dot"]}), encoding="utf-8")

    # vectors
    files = {
        "logo/mark.svg": svg(mark_body(), 512, 512, vb="0 0 64 64", title="SimpleTranslate"),
        "logo/mark-small.svg": svg(mark_body(True), 64, 64, title="SimpleTranslate"),
        "logo/mark-mono.svg": svg(mark_mono(), 512, 512, vb="0 0 64 64", title="SimpleTranslate"),
        "logo/wordmark.svg": wordmark_svg(wm, C["ink"], C["blue"]),
        "logo/wordmark-white.svg": wordmark_svg(wm, C["white"], C["blue_dk"]),
        "logo/logo-horizontal.svg": lockup(wm, "h"),
        "logo/logo-horizontal-white.svg": lockup(wm, "h", dark=True),
        "logo/logo-vertical.svg": lockup(wm, "v"),
        "logo/logo-vertical-white.svg": lockup(wm, "v", dark=True),
        "avatar/avatar.svg": svg(avatar_body(), 1080, 1080, vb="0 0 64 64", title="SimpleTranslate"),
        "avatar/avatar-round-preview.svg": svg(avatar_body(True), 512, 512, vb="0 0 64 64", title="SimpleTranslate"),
    }
    for k, v in files.items():
        (OUT / k).write_text(v, encoding="utf-8")

    def wh(text):
        import re
        m = re.search(r'width="(\d+)" height="(\d+)"', text)
        return int(m.group(1)), int(m.group(2))

    # raster logos
    for name in ("logo-horizontal", "logo-horizontal-white", "logo-vertical", "logo-vertical-white",
                 "wordmark", "wordmark-white"):
        t = files[f"logo/{name}.svg"]
        w, h = wh(t)
        k = (1600 / w) if "horizontal" in name or "wordmark" in name else (1000 / h)
        svg_png(t, round(w * k), round(h * k), OUT / f"logo/{name}.png")
    svg_png(files["logo/mark.svg"], 1024, 1024, OUT / "logo/mark-1024.png")
    svg_png(files["logo/mark-mono.svg"], 1024, 1024, OUT / "logo/mark-mono-1024.png")

    # avatars: square, the platform crops to a circle
    for s in (1080, 400):
        svg_png(files["avatar/avatar.svg"], s, s, OUT / f"avatar/avatar-{s}.png")
    svg_png(files["avatar/avatar-round-preview.svg"], 512, 512, OUT / "avatar/avatar-round-preview.png")

    # web icons
    small = files["logo/mark-small.svg"]
    for s in (16, 32, 48):
        svg_png(small if s < 32 else files["logo/mark.svg"], s, s, TMP / f"fav{s}.png")
    shutil.copy(OUT / "logo/mark-small.svg", OUT / "web/favicon.svg")
    from PIL import Image
    ims = [Image.open(TMP / f"fav{s}.png").convert("RGBA") for s in (16, 32, 48)]
    ims[2].save(OUT / "web/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=ims[:2])
    ico = Image.open(OUT / "web/favicon.ico")
    got = sorted(ico.ico.sizes())
    assert got == [(16, 16), (32, 32), (48, 48)], got
    # 16 px обязан быть рисованным упрощённым знаком, а не ужатым 48-м
    ico.size = (16, 16); ico16 = ico.convert("RGBA")
    assert ico16.tobytes() == ims[0].tobytes(), "favicon.ico: 16 px пересчитан из 48, а не взят рисованным"
    svg_png(files["logo/mark.svg"], 96, 96, OUT / "web/favicon-96.png")
    # apple-touch and PWA icons are full-bleed squares: the system rounds the corners itself
    sq = svg(f'<rect width="64" height="64" fill="{C["blue"]}"/>' + key(), 512, 512, vb="0 0 64 64")
    for s in (180, 192, 512):
        svg_png(sq, s, s, OUT / f"web/{'apple-touch-icon' if s == 180 else f'icon-{s}'}.png")

    lh = files["logo/logo-horizontal.svg"]
    lhw = files["logo/logo-horizontal-white.svg"]

    for lang, t in T.items():
        sfx = "" if lang == "ru" else "-uz"
        pairs = PAIRS if lang == "ru" else [PAIRS[1], PAIRS[0], PAIRS[2]]
        # OG 1200x630
        body = (f'<div class="og"><div class="top">{lk_img(lh, 56)}</div>'
                f'<div class="mid"><h1 class="h">{ty(t["og_h1"])} <span>{ty(t["og_h2"])}</span></h1><p>{ty(t["og_p"])}</p></div>'
                f'<div class="bot"><span class="chip">{t["free"]}</span><b>simpletranslate.me</b></div></div>')
        css = SIG_CSS + """.og{width:1200px;height:630px;padding:64px 72px;display:flex;flex-direction:column;justify-content:space-between;background:var(--paper)}
.og h1{font-size:60px;line-height:1.08;max-width:15em}.og h1 span{color:var(--blue-ink)}
.og p{font-size:26px;line-height:1.4;color:var(--ink2);max-width:34em;margin:22px 0 0}
.og .bot{display:flex;align-items:center;justify-content:space-between;font-size:24px}.og .chip{font-size:24px}.og b{color:var(--ink2);font-weight:700}"""
        render(page(body, css, 1200, 630), 1200, 630, OUT / f"web/og-1200x630{sfx}.png")

        # social covers: content inside each platform's safe zone
        covers = [("youtube-2560x1440", 2560, 1440, (1546, 423)), ("linkedin-1584x396", 1584, 396, None),
                  ("facebook-1640x624", 1640, 624, None), ("x-1500x500", 1500, 500, None)]
        for name, W, H, safe in covers:
            if safe:
                sw, shh = safe
                inner = (f'<div class="safe" style="width:{sw}px;height:{shh}px">{lk_img(lh, 150)}'
                         f'<p>{ty(t["tag"])}</p></div>')
                css = SIG_CSS + f""".cv{{width:{W}px;height:{H}px;display:grid;place-items:center;background:var(--paper)}}
.safe{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px}}
.safe p{{font-size:40px;font-weight:600;color:var(--ink2);margin:0;text-align:center}}"""
            else:
                fs = round(min(H * 0.05, W * 0.0125))
                lkh = round(H * 0.16)
                inner = (f'<div class="row"><div class="a">{lk_img(lh, lkh)}<p>{ty(t["tag"])}</p></div>'
                         f'<div class="b" style="font-size:{fs}px">{sig(pairs[:2])}</div></div>')
                # LinkedIn and X put the profile photo bottom-left: keep that corner empty
                pad_l = round(W * 0.28) if name.startswith(("linkedin", "x-")) else round(W * 0.07)
                css = SIG_CSS + f""".cv{{width:{W}px;height:{H}px;background:var(--paper);display:flex;align-items:center;padding:0 {round(W*0.06)}px 0 {pad_l}px}}
.row{{display:flex;align-items:center;justify-content:space-between;gap:{round(W*0.05)}px;width:100%}}
.a{{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:{round(H*0.06)}px}}.a p{{margin:0;font-size:{round(H*0.056)}px;font-weight:600;color:var(--ink2);max-width:18em}}
.b{{flex:0 0 36%;min-width:0;display:flex;flex-direction:column;gap:.9em;background:#fff;border:1px solid var(--line);border-radius:14px;padding:1.1em 1.3em}}"""
            render(page(f'<div class="cv">{inner}</div>', css, W, H), W, H, OUT / f"social/{name}{sfx}.png")

        # post 1:1 — proof of the line check
        body = (f'<div class="post"><div class="k">{t["eyebrow"]}</div><h2 class="h">{ty(t["post_h"])}</h2>'
                f'<div class="pairs">{sig(pairs)}</div>'
                f'<div class="ft">{lk_img(lh, 46)}<span>simpletranslate.me</span></div></div>')
        css = SIG_CSS + """.post{width:1080px;height:1080px;padding:84px;display:flex;flex-direction:column;gap:44px;background:#fff}
.k{font-size:24px;font-weight:800;letter-spacing:.08em;color:var(--blue-ink)}
.post h2{font-size:64px;line-height:1.08;max-width:13em}
.pairs{display:flex;flex-direction:column;gap:30px;font-size:29px;flex:1;justify-content:center}
.ft{display:flex;align-items:center;justify-content:space-between;font-size:26px;font-weight:700;color:var(--ink2);border-top:2px solid var(--line);padding-top:30px}"""
        render(page(body, css, 1080, 1080), 1080, 1080, OUT / f"templates/post-1080x1080{sfx}.png")

        # post 4:5, story 9:16 and reel end frame — the offer
        for name, W, H, top, bot in (("post-1080x1350", 1080, 1350, 90, 90), ("story-1080x1920", 1080, 1920, 250, 340),
                                     ("reel-end-1080x1920", 1080, 1920, 230, 480)):
            body = (f'<div class="of dark"><div class="lg">{lk_img(lhw, 54)}</div>'
                    f'<div class="big"><span>{t["offer_a"]}</span><b class="h">5</b><span>{t["offer_b"]}</span></div>'
                    f'<div class="sg">{sig(pairs[:1])}</div>'
                    f'<div class="ct"><span class="btn">{t["cta"]}</span><i>simpletranslate.me</i></div></div>')
            css = SIG_CSS + f""".of{{width:{W}px;height:{H}px;padding:{top}px 90px {bot}px;background:var(--ink);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:space-between;text-align:center}}
.big{{display:flex;flex-direction:column;align-items:center}}.big span{{font-size:54px;font-weight:700}}
.big b{{font-size:{430 if H > 1500 else 360}px;line-height:.95;color:var(--teal);letter-spacing:-.04em;font-weight:600}}
.sg{{font-size:30px;text-align:left;background:#131E33;border-radius:16px;padding:28px 32px}}
.ct{{display:flex;flex-direction:column;align-items:center;gap:22px}}.ct .btn{{font-size:40px}}.ct i{{font-style:normal;font-size:28px;font-weight:700;color:#AFC0DA}}"""
            render(page(body, css, W, H), W, H, OUT / f"templates/{name}{sfx}.png")

    # print: business card 85x55 with 3 mm bleed, two pages
    mm = 3.7795275591
    cw, ch = 91, 61
    card = (f'<section class="cd f"><div class="k">{svg(key(), 64, 64).replace("<svg ", "<svg class=key ")}</div></section>'
            f'<section class="cd b"><div class="in">{lk_img(lh, 40)}'
            f'<div class="who"><b class="h">Имя Фамилия</b><span>должность</span></div>'
            f'<div class="ct">+998 __ ___ __ __<br>name@simpletranslate.me<br><strong>simpletranslate.me</strong></div></div></section>')
    css = f"""@page{{size:{cw}mm {ch}mm;margin:0}}html,body{{width:{cw}mm;height:auto;overflow:visible;background:#fff}}
.cd{{width:{cw}mm;height:{ch}mm;page-break-after:always;position:relative;overflow:hidden}}
.f{{background:var(--blue);display:grid;place-items:center}}.f .key{{width:24mm;height:24mm}}
.b .in{{position:absolute;inset:7mm 8mm;display:flex;flex-direction:column;justify-content:space-between}}
.who b{{display:block;font-size:13pt}}.who span{{font-size:8.5pt;color:var(--ink2)}}
.ct{{font-size:8pt;line-height:1.5;color:var(--ink2)}}.ct strong{{color:var(--blue-ink)}}"""
    render(page(card, css, round(cw * mm), round(ch * mm)), round(cw * mm), round(ch * mm), OUT / "print/business-card-85x55-bleed3.pdf")

    # print: A4 letterhead (requisites stay placeholders until LEGAL_* are filled)
    lh_body = (f'<div class="a4"><header>{lk_img(lh, 46)}<div class="rq">[название организации]<br>'
               f'ИНН [указать] · [адрес]<br>simpletranslate.me</div></header>'
               f'<main><p class="ph">Текст документа</p></main>'
               f'<footer><span>simpletranslate.me</span><span>Перевод документов на любой язык</span></footer></div>')
    css = """@page{size:A4;margin:0}html,body{width:210mm;height:297mm;background:#fff}
.a4{width:210mm;height:297mm;padding:16mm 18mm 14mm;display:flex;flex-direction:column}
header{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:.4mm solid var(--line);padding-bottom:7mm}
.rq{font-size:8pt;line-height:1.55;color:var(--ink2);text-align:right}
main{flex:1;padding-top:12mm}.ph{font-size:10.5pt;color:#9AA6BA}
footer{display:flex;justify-content:space-between;font-size:7.5pt;color:var(--ink2);border-top:.4mm solid var(--line);padding-top:4mm}"""
    render(page(lh_body, css, 794, 1123), 794, 1123, OUT / "print/letterhead-a4.pdf")

    # email signature: plain table HTML, logo by absolute URL (served by the landing)
    sig_html = f"""<table cellpadding="0" cellspacing="0" style="font-family:Arial,sans-serif;color:{C['ink']};font-size:13px;line-height:1.45">
<tr><td style="padding:0 0 8px"><b style="font-size:14px">Имя Фамилия</b><br><span style="color:{C['ink2']}">должность</span></td></tr>
<tr><td style="padding:8px 0 0;border-top:1px solid {C['line']}"><a href="https://simpletranslate.me/"><img src="https://simpletranslate.me/img/logo-email.png" width="180" height="{round(180 * wh(lh)[1] / wh(lh)[0])}" alt="SimpleTranslate" style="display:block;border:0"></a></td></tr>
<tr><td style="padding:6px 0 0;color:{C['ink2']}">Перевод документов на любой язык · <a href="https://simpletranslate.me/" style="color:{C['blue_ink']};text-decoration:none">simpletranslate.me</a></td></tr>
</table>
"""
    (OUT / "print/email-signature.html").write_text(sig_html, encoding="utf-8")
    w, h = wh(lh)
    svg_png(lh, 360, round(360 * h / w), OUT / "web/logo-email.png")

    brand_guide(wm, files)
    shutil.rmtree(TMP, ignore_errors=True)
    n = sum(1 for _ in OUT.rglob("*") if _.is_file())
    print(f"готово: {n} файлов в {OUT}")


def brand_guide(wm, files):
    lh = files["logo/logo-horizontal.svg"]
    sw = [("Синий", "blue", "знак, главная кнопка"), ("Глубокий синий", "deep", "толщина клавиши, нажатие"),
          ("Синий для текста", "blue_ink", "ссылки и акцент в тексте"), ("Синий на тёмном", "blue_dk", "акцент на чернилах"),
          ("Чернила", "ink", "текст, тёмные панели"), ("Графит", "ink2", "второй текст, строка оригинала"),
          ("Бумага", "paper", "фон"), ("Линия", "line", "разделители"), ("Бирюза", "teal", "только «бесплатно» и «готово»")]

    def rgb(hx):
        r, g, b = (int(hx[i:i + 2], 16) for i in (1, 3, 5))
        k = 1 - max(r, g, b) / 255
        cmy = [0 if k == 1 else round((1 - c / 255 - k) / (1 - k) * 100) for c in (r, g, b)]
        return f"RGB {r} {g} {b} · CMYK≈ {cmy[0]} {cmy[1]} {cmy[2]} {round(k * 100)}"

    sws = "".join(f'<div class="sw"><i style="background:{C[k]}"></i><b>{n}</b><span>{C[k]} · {rgb(C[k])}</span><em>{u}</em></div>'
                  for n, k, u in sw)
    uri = data_uri
    body = f"""<section class="pg">
<header>{lk_img(lh, 40)}<span>Книга бренда · 2026</span></header>
<h1 class="h">Знак и логотип</h1>
<div class="grid3">
 <figure><img src="{uri(files['logo/mark.svg'])}"><figcaption>Знак. От 32 px.</figcaption></figure>
 <figure><img src="{uri(files['logo/mark-small.svg'])}" style="image-rendering:auto"><figcaption>Упрощённый: 16–31 px, favicon.</figcaption></figure>
 <figure><img src="{uri(files['logo/mark-mono.svg'])}"><figcaption>Одноцветный: печать, штамп.</figcaption></figure>
</div>
<div class="lk2"><div class="cs"><img src="{uri(lh)}" style="height:56px"></div><div class="cs dk"><img src="{uri(files['logo/logo-horizontal-white.svg'])}" style="height:56px"></div></div>
<ul>
<li>Клавиша: 文 слева сверху, A справа снизу. Нажал одну клавишу — получил другой язык.</li>
<li>Свободное поле вокруг логотипа — не меньше высоты прописной буквы названия. Знак без названия — не меньше 16 px.</li>
<li>Название нарисовано (контуры Unbounded 650), не набирается шрифтом. Точка над «i» — маленькая синяя клавиша.</li>
<li>Аватарка — синий квадрат с крупной клавишей: площадки обрежут его в круг, клавиша останется целой.</li>
<li>Нельзя: менять 文 и A местами, красить название в два цвета, добавлять градиент, свечение, тень, обводку, наклон.</li>
</ul>
</section>
<section class="pg">
<header>{lk_img(lh, 40)}<span>Книга бренда · 2026</span></header>
<h1 class="h">Цвет, шрифт, приём</h1>
<div class="sws">{sws}</div>
<div class="ty">
 <div><span class="lab">Заголовки и крупные цифры</span><p class="h" style="font-size:30px">Unbounded 600</p><p class="s">Только заголовки, цифры от 40 px и название.</p></div>
 <div><span class="lab">Весь остальной текст</span><p style="font-size:26px;font-weight:700">Manrope 400 · 700 · 800</p><p class="s">В Manrope нет узбекской ʻ (U+02BB): в текстах на Manrope пишем ‘ (U+2018), как в «O‘zbekcha».</p></div>
</div>
<div class="sigbox"><span class="lab">Приём «строка к строке»</span>{sig(PAIRS[:2])}<p class="s">Оригинал графитом, перевод чернилами, синяя скобка и номер строки. Числа, единицы и отрицания подчёркнуты с обеих сторон. Заменяет иллюстрации и фоны: в постах только настоящие пары «оригинал — перевод».</p></div>
<ul>
<li>Пропорция на экране: бумага и белое 70%, чернила 20%, синий 10%. Бирюза — только на «бесплатно» и «готово».</li>
<li>Скругления: плитка знака 23%, кнопки и поля 10 px, карточки 12–14 px, бейджи — капсула.</li>
<li>Объём есть только у клавиши и кнопки: сплошная тень 3 px глубоким синим, без размытия.</li>
<li>Типографика документа: «ёлочки», неразрывный пробел перед единицей (300&nbsp;мг), цифры одной ширины в ценах.</li>
</ul>
</section>"""
    css = SIG_CSS + """@page{size:A4;margin:0}html,body{width:210mm;height:auto;overflow:visible;background:#fff}
.pg{width:210mm;height:297mm;padding:14mm 16mm;display:flex;flex-direction:column;gap:7mm;page-break-after:always;font-size:10pt;line-height:1.5}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:.3mm solid var(--line);padding-bottom:5mm;color:var(--ink2);font-size:8.5pt}
h1{font-size:24pt}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:6mm}figure{margin:0;display:flex;flex-direction:column;gap:3mm;align-items:flex-start}
figure img{width:34mm;height:34mm}figcaption{font-size:8.5pt;color:var(--ink2)}
.lk2{display:grid;grid-template-columns:1fr 1fr;gap:6mm}.cs{background:var(--paper);border-radius:4mm;padding:9mm;display:grid;place-items:center}.cs.dk{background:var(--ink)}
ul{margin:0;padding-left:5mm;display:flex;flex-direction:column;gap:1.6mm}
.sws{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm}.sw{display:flex;flex-direction:column;gap:.8mm;font-size:8pt}
.sw i{height:14mm;border-radius:2.5mm;border:.3mm solid var(--line)}.sw b{font-size:9pt}.sw span{color:var(--ink2);font-variant-numeric:tabular-nums}.sw em{font-style:normal;color:var(--ink2)}
.ty{display:grid;grid-template-columns:1fr 1fr;gap:6mm}.ty p{margin:1mm 0}.lab{font-size:7.5pt;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--blue-ink)}
.s{font-size:8.5pt;color:var(--ink2)}
.sigbox{background:var(--paper);border-radius:4mm;padding:6mm;display:flex;flex-direction:column;gap:3.5mm;font-size:10.5pt}"""
    render(page(body, css, 794, 1123), 794, 1123, OUT / "brand-guide.pdf")


APPLY = {
    "web/favicon.svg": ["landing/favicon.svg"],
    "web/favicon.ico": ["landing/favicon.ico"],
    "web/favicon-96.png": ["landing/favicon-96.png"],
    "web/apple-touch-icon.png": ["landing/apple-touch-icon.png"],
    "logo/mark-1024.png": ["landing/logo.png"],
    "web/og-1200x630.png": ["landing/og.png"],
    "web/logo-email.png": ["landing/img/logo-email.png"],
}


def apply():
    for src, dsts in APPLY.items():
        for d in dsts:
            p = ROOT / d
            if p.parent.exists():
                shutil.copy(OUT / src, p)
                print("→", d)


if __name__ == "__main__":
    build()
    if "--apply" in sys.argv:
        apply()
