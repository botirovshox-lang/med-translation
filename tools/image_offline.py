"""Картинка ОФЛАЙН: строки — локальным детектором, блоки — `group_blocks`
(как разбор надписей), перевод — из файла, перерисовка — настоящей
`image_text.render_target`. Без сервера, без модели и без денег: проверка
правил перерисовки (разделы Ф/Х/Ы справочника) на снимках корпуса.

    python tools/image_offline.py IMG                      # блоки и их рамки
    python tools/image_offline.py IMG OUT --tr TR.json     # перерисовать

TR.json — [[номер блока, «оригинал по строкам через \\n», «перевод»], …].
Разрывы блока считает `read_lines` по оригиналу (как после чтения моделью);
перевод — частями через \\n, сколько частей вышло у оригинала."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
NL = "\n"


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("img")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--tr", default="")
    a = ap.parse_args()
    os.environ.setdefault("APP_PASSWORD", "offline")
    sys.path.insert(0, str(ROOT / "backend"))
    import image_text
    blob = Path(a.img).read_bytes()
    lines = image_text.detect_lines(blob) or []
    blocks = image_text.group_blocks(lines)
    if not a.tr:
        for i, b in enumerate(blocks):
            print(i, [round(v) for v in b["box"]], b.get("rows"))
        return
    tr = json.loads(Path(a.tr).read_text(encoding="utf-8"))
    import numpy as np
    arr = np.asarray(image_text._open(blob).convert("RGB"))
    obstacles = [list(b["box"]) for b in blocks]
    items = []
    for i, b in enumerate(blocks):
        ent = next((e for e in tr if e[0] == i), None)
        if not ent:
            continue
        src, tgt = ent[1], ent[2]
        inks = image_text.line_inks(arr, b.get("lineBoxes"))
        stext, breaks = image_text.read_lines(src, b.get("lineBoxes"), image_text.block_align(b), inks)
        if tgt.count(NL) != len(breaks):
            tgt = " ".join(tgt.split())
        print("block", i, "breaks", breaks, "parts", stext.count(NL) + 1)
        items.extend(image_text.split_parts({
            "box": b["box"], "text": tgt, "align": image_text.block_align(b),
            "breaks": breaks, "lineH": b.get("lineH"), "rows": b.get("rows"),
            "lineBoxes": b.get("lineBoxes"), "fam": "", "src": stext}))
    new, report = image_text.render_target(blob, items, obstacles=obstacles)
    for r in report:
        print(r)
    if new and a.out:
        Path(a.out).write_bytes(new)


if __name__ == "__main__":
    main_()
