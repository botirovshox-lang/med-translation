"""Синтетические страницы: оригинал по рецепту, «перевод» без модели, замеры.

Рецепты — данными (`backend/doc_catalog/synth_recipes.json`): строки (текст,
шрифт из репозитория, кегль, цвет), значок, печать, фон; целевой язык.
«Перевод» — местная подмена каждого слова псевдословом той же формы
(регистр, цифры, знаки сохраняются) длиной по коэффициенту языка
(`expansion`), буквами его алфавита; имена с номерами (`keep_names`)
остаются как есть — так переводчик переносит имена авторов. Модели нет.

Страница проходит ту же раскраску, что выгрузка (`image_text.render_target`),
и те же замеры (`fidelity.compare`). Синтетика ловит ОТКАТЫ правил, но
покрытием не является: она проверяет раскраску на её же представлении
о мире (оговорка критика), поэтому статус каталога от неё не зависит.
"""
from __future__ import annotations

import io
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECIPES = ROOT / "doc_catalog" / "synth_recipes.json"
FONTS = ROOT.parent / "frontend" / "vendor" / "fonts" / "sub"
def load() -> dict:
    return json.loads(RECIPES.read_text(encoding="utf-8"))


def _is_name(w: str) -> bool:
    core = w.strip(",.;:")
    return bool(core) and core[:1].isupper() and any(ch.isdigit() for ch in core)


def pseudo(text: str, lang: str, factor: float, seed: int = 0, keep_names: bool = False,
           data: dict = None) -> str:
    """Псевдоперевод: слово → слово того же вида длиной ×`factor` буквами
    алфавита языка (`alphabets`, `script_of` в рецептах)."""
    data = data or load()
    rnd = random.Random("%s|%s|%d" % (text, lang, seed))
    script = (data.get("script_of") or {}).get(lang, "latin")
    abc = data["alphabets"][script]
    cased = abc.lower() != abc.upper()
    out = []
    words = text.split(" ")
    names_from = len(words)
    if keep_names:
        for k, w in enumerate(words):
            if _is_name(w):
                names_from = max(0, k - 1)
                break
    for k, w in enumerate(words):
        if k >= names_from:
            out.append(w)
            continue
        letters = [ch for ch in w if ch.isalpha()]
        if not letters:
            out.append(w)
            continue
        n = max(1, int(round(len(letters) * factor)))
        nw = "".join(rnd.choice(abc) for _ in range(n))
        if letters[0].isupper() and cased:
            nw = nw[:1].upper() + nw[1:]
        tail = "".join(ch for ch in w[len(w.rstrip(",.;:!?")):])
        out.append(nw + tail)
    sep = "" if script in (data.get("spaceless") or []) else " "
    return sep.join(out)


def build(rec: dict):
    """(png оригинала, items для раскраски) по рецепту."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = rec["size"]
    im = Image.new("RGB", (W, H), tuple(rec.get("bg") or (250, 250, 250)))
    dr = ImageDraw.Draw(im)
    y, boxes, texts = 30, [], []
    for ln in rec["lines"]:
        f = ImageFont.truetype(str(FONTS / ln["font"]), int(ln["px"]))
        col = tuple(ln.get("colour") or (30, 30, 30))
        dr.text((40, y), ln["text"], font=f, fill=col)
        bb = list(dr.textbbox((40, y), ln["text"], font=f))
        if ln.get("icon") == "orcid":
            r = max(6, int(ln["px"] * 0.55))
            cy = (bb[1] + bb[3]) // 2
            dr.ellipse((bb[2] + 6, cy - r, bb[2] + 6 + 2 * r, cy + r), fill=(166, 206, 57))
            bb[2] += 8 + 2 * r
        boxes.append(bb)
        texts.append(ln["text"])
        y = bb[3] + int(ln["px"] * 0.5)
    st = rec.get("stamp")
    if st:
        cx, cy = st["center"]
        r = st["r"]
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), outline=tuple(st["colour"]), width=max(3, r // 10))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    src = " ".join(texts)
    return buf.getvalue(), box, boxes, src


def run(rec: dict, seed: int = 0, data: dict = None) -> dict:
    """Раскраска и замеры одного рецепта: {id, report, fidelity}."""
    import image_text
    import fidelity
    data = data or load()
    png, box, boxes, src = build(rec)
    lang = rec.get("target") or "uz"
    tr = pseudo(src, lang, float((data.get("expansion") or {}).get(lang, 1.0)), seed,
                bool(rec.get("keep_names")), data)
    import numpy as np
    item = {"box": box, "text": tr, "rows": len(boxes), "lineBoxes": boxes,
            "lineH": int(np.median([b[3] - b[1] for b in boxes])), "src": src, "align": "left"}
    out, rep = image_text.render_target(png, [item])
    fr = fidelity.compare(png, out, [item]) if out else {"warn": ["not_painted"], "summary": {}}
    return {"id": rec["id"], "lang": lang, "report": rep, "fidelity": fr, "out": out, "orig": png}
