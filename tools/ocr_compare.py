#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сравнение читателей надписей на картинках на ОДНИХ И ТЕХ ЖЕ блоках.

    bash tools/prod_run.sh tools/ocr_compare.py      # на сервере (ключи из /etc/medcat/env)
    OCR_CMP_PIDS=90,74,78,83,2 OCR_CMP_MAX=15 OCR_CMP_MODELS=gpt-4o,claude-sonnet-5

Читатели — ровно те, что работают в бою: зрячая модель через
`main._openai_read_image(model=…)` (тот же промпт и та же нарезка кропов)
и Яндекс Vision через `main._vision_read_blocks` (модель рукописи — у блоков,
помеченных рукописью). Блоки берутся из карты картинок проекта (sidecar
`data/sources/{pid}.json`), уже отсеянные (`skip`) не берутся.

Платно: по вызову на картинку у каждой модели и по запросу на блок у Vision —
запускать по решению владельца. Ничего не пишет ни в проекты, ни в карты.
Вырезки блоков кладёт в OCR_CMP_OUT (по умолчанию /tmp/ocrcmp) — по ним
человек (или сверяющий) решает, кто прав, где читатели разошлись; результат —
`results.json` там же. Каталог с вырезками удалить после разбора: в нём
кусок картинок проекта.
"""
import json
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "backend").is_dir():             # копия скрипта в /tmp (tools/prod_run.sh)
    ROOT = Path(os.environ.get("MEDCAT_ROOT", "/opt/med-translation"))


def load_env(path="/etc/medcat/env"):
    """Ключи сервиса — из файла окружения юнита (строки KEY=VALUE)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        k = k.strip()
        if k and k.replace("_", "").isalnum() and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


def main_():
    load_env()
    os.environ["MEDCAT_ROLE"] = "worker"          # миграции старта не пишут
    sys.path.insert(0, str(ROOT / "backend"))
    import main
    pids = [int(x) for x in os.environ.get("OCR_CMP_PIDS", "90,74,78,83,2").split(",") if x.strip()]
    per = int(os.environ.get("OCR_CMP_MAX", "15"))
    models = [m for m in os.environ.get("OCR_CMP_MODELS", "gpt-4o,claude-sonnet-5,claude-opus-5").split(",") if m]
    out_dir = Path(os.environ.get("OCR_CMP_OUT", "/tmp/ocrcmp"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for pid in pids:
        proj = next((p for p in main.STATE.get("projects") or [] if p.get("id") == pid), None)
        if not proj:
            print("нет проекта", pid)
            continue
        main.CURRENT_SESSION.set({"tenant": main._tenant_of(proj), "user": None, "role": "owner", "super": True})
        src = proj.get("src") or "RU"
        data = main._load_source_map(pid) or {}
        docx = main.SOURCE_DIR / ("%d.docx" % pid)
        if not docx.exists():
            print("нет исходника", pid)
            continue
        zf = zipfile.ZipFile(docx)
        taken = 0
        for rec in data.get("images") or []:
            if taken >= per:
                break
            try:
                blob = zf.read(rec["part"])
            except KeyError:
                continue
            idx = [i for i, b in enumerate(rec.get("blocks") or [])
                   if b.get("box") and not b.get("skip") and (b.get("text") or "").strip()][:per - taken]
            if not idx:
                continue
            blocks = [rec["blocks"][i] for i in idx]
            res = {}
            for m in models:
                t = time.time()
                got = main._openai_read_image(blob, blocks, src, model=m, fallback=False) or [None] * len(blocks)
                res[m] = ([(g or {}).get("text") for g in got], [(g or {}).get("hand") for g in got], time.time() - t)
            t = time.time()
            hand = [bool(b.get("hand")) or any((res[m][1][k] or False) for m in models) for k, b in enumerate(blocks)]
            vis = [None] * len(blocks)
            for k, b in enumerate(blocks):
                g = main._vision_read_blocks(blob, [b], src, hand=hand[k])
                vis[k] = (g or [None])[0]
            res["yandex"] = ([(g or {}).get("text") for g in vis], hand, time.time() - t)
            for k, i in enumerate(idx):
                b = rec["blocks"][i]
                crop = main.image_text.crop(blob, b["box"], line_h=b.get("lineH"), rows=b.get("rows"))
                name = "p%d_%s_%d.png" % (pid, Path(rec["part"]).stem, i)
                if crop:
                    (out_dir / name).write_bytes(crop)
                rows.append({"pid": pid, "part": rec["part"], "i": i, "crop": name, "hand": hand[k],
                             "stored": b.get("text"), "reader": b.get("reader"),
                             **{r: res[r][0][k] for r in res}})
            for r in res:
                print("p%d %s %s: %.1f с на %d блоков" % (pid, Path(rec["part"]).name, r, res[r][2], len(idx)))
            taken += len(idx)
    (out_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("блоков:", len(rows), "→", out_dir / "results.json")


if __name__ == "__main__":
    main_()
