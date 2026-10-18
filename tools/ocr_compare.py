#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сравнение читателей надписей на картинках на ОДНИХ И ТЕХ ЖЕ блоках.

    bash tools/prod_run.sh tools/ocr_compare.py      # на сервере (ключи из /etc/medcat/env)
    OCR_CMP_PIDS=90,74,78,83,2 OCR_CMP_MAX=15 OCR_CMP_MODELS=gpt-4o,claude-sonnet-5

Читатели — ровно те, что работают в бою: зрячая модель через
`main._openai_read_image(model=…)` (тот же промпт и та же нарезка кропов). Блоки берутся из карты картинок проекта (sidecar
`data/sources/{pid}.json`), уже отсеянные (`skip`) не берутся.

Платно: по вызову на картинку у каждой модели —
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


EXTRA_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "in": 4.00, "out": 20.00, "api": "anthropic",
     "effort": "low", "cacheRead": 0.05, "cacheWrite": 1.25},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "in": 2.00, "out": 10.00, "api": "anthropic",
     "effort": "low", "cacheRead": 0.1, "cacheWrite": 1.25},
]


def _cost(main, mid):
    """Потрачено на модель с начала процесса (учёт `_note_usage`)."""
    leaf = ((main._USAGE_TOTAL or {}).get("models") or {}).get(mid) or {}
    return float(leaf.get("cost") or 0.0), int(leaf.get("in") or 0), int(leaf.get("out") or 0)


def main_():
    load_env()
    os.environ["MEDCAT_ROLE"] = "worker"          # миграции старта не пишут
    sys.path.insert(0, str(ROOT / "backend"))
    import main
    # Модели, которых ещё нет в каталоге, — только на время замера (в каталог
    # их вносит правка кода с рангом в model_ranks.json, а не этот инструмент).
    for m in EXTRA_MODELS:
        if m["id"] not in main._MODELS_BY_ID:
            main.OPENAI_MODELS.append(m)
            main._MODELS_BY_ID[m["id"]] = m
    pids = [int(x) for x in os.environ.get("OCR_CMP_PIDS", "90,74,78,83,2,8").split(",") if x.strip()]
    per = int(os.environ.get("OCR_CMP_MAX", "15"))
    per_pid = {2: 60, 8: 30}
    models = [m for m in os.environ.get("OCR_CMP_MODELS", "claude-sonnet-5,claude-sonnet-5-5,claude-opus-5,claude-opus-5-5").split(",") if m]
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
        cap = per_pid.get(pid, per)
        for rec in data.get("images") or []:
            if taken >= cap:
                break
            try:
                blob = zf.read(rec["part"])
            except KeyError:
                continue
            idx = [i for i, b in enumerate(rec.get("blocks") or [])
                   if b.get("box") and not b.get("skip") and (b.get("text") or "").strip()][:cap - taken]
            if not idx:
                continue
            blocks = [rec["blocks"][i] for i in idx]
            res = {}
            for m in models:
                t = time.time()
                got = main._openai_read_image(blob, blocks, src, model=m) or [None] * len(blocks)
                res[m] = ([(g or {}).get("text") for g in got], [(g or {}).get("hand") for g in got], time.time() - t)
            hand = [bool(b.get("hand")) or any((res[m][1][k] or False) for m in models) for k, b in enumerate(blocks)]
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
    for m in models:
        c, ti, to = _cost(main, m)
        print("ЦЕНА %s: $%.4f (вход %d, выход %d токенов)" % (m, c, ti, to))
    (out_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("блоков:", len(rows), "→", out_dir / "results.json")


if __name__ == "__main__":
    main_()
