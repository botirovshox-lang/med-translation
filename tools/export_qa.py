"""Приёмка выгрузки ОФЛАЙН текущим кодом — инструмент агента-разработчика (Ч5).

Каталог DIR — то, что скачал `python tools/export_review.py fetch PID DIR`
(project.json, {pid}.docx, {pid}.json, {pid}.orig.*). Инструмент собирает
выгрузку PDF «как в оригинале» ТЕКУЩИМ кодом рабочей копии (а не берёт
файл с сервера — тот мог быть собран прежними правилами), прогоняет ту же
приёмку, что сервер (`backend/export_qa.py`), и печатает итог.

    python tools/export_qa.py DIR [--pages 1,4,6] [--no-detect] [--json]

Пишет DIR/new.pdf (выгрузка), DIR/qa.json (полный отчёт). Платного взгляда
здесь нет: он идёт на сервере (`POST /api/admin/export-qa/{pid}`), где
ключи и прокси. Данные клиента остаются в DIR — в репозиторий их не класть.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--pages", default="")
    ap.add_argument("--no-detect", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = Path(a.dir).resolve()
    os.environ.setdefault("APP_PASSWORD", "offline")
    os.environ.setdefault("WARM_CACHES", "0")
    os.environ.setdefault("AUTO_RESEGMENT", "0")
    os.environ["EXPORT_QA"] = "0"             # фоновый поток сервера здесь не нужен
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    import main
    import export_qa
    p = json.loads((d / "project.json").read_text(encoding="utf-8"))
    pid = int(p["id"])
    src = d / "_src"
    src.mkdir(exist_ok=True)
    for f in d.iterdir():
        if f.name.startswith("%d." % pid):
            shutil.copy(f, src / f.name)
    main.SOURCE_DIR = src
    main.EXPORT_DIR = d / "_exp"
    p.setdefault("tenant", "default")
    out = d / "new.pdf"
    stats = main._export_pdf_layout(p, out)
    if stats is None:
        sys.exit("у проекта нет раскладки PDF — приёмка по виду не применяется")
    inp = main._QA_INPUTS.pop(pid)
    segs = p.get("segments") or []
    lang = export_qa.Lang([s.get("source") or "" for s in segs], [s.get("target") or "" for s in segs])
    det = None
    if not a.no_detect and main.image_text is not None and main.image_text.engine_ready()[0]:
        det = main.image_text.detect_lines
    pages = [int(x) - 1 for x in a.pages.split(",") if x.strip()] or None
    rep = export_qa.inspect_pdf(inp["work"], out.read_bytes(), inp["layout"], inp["texts"], inp["extra"],
                                lang, overlay=inp.get("overlay"), overlay_order=inp.get("order"),
                                pages=pages, time_budget=3600, detect=det, sources=inp.get("sources"))
    p2s: dict = {}
    for pa, sid in inp.get("pairs") or []:
        p2s.setdefault(int(pa), []).append(sid)
    for it in rep.get("issues") or []:
        sids = main._qa_segs(it, p2s, inp.get("extra") or [])
        if sids:
            it["segs"] = sids[:50]
    (d / "qa.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.json:
        print(json.dumps(export_qa.summary(rep), ensure_ascii=False))
        return
    print("выгрузка: %s; проверено %s из %s стр. за %s с%s" % (
        out, rep.get("checked"), rep.get("pages"), rep.get("seconds"),
        " (не всё)" if rep.get("partial") else ""))
    print("сборка: наложений %s, вылетов %s, двойных печатей снято %s" % (
        stats.get("collisions"), stats.get("overflow"), stats.get("dupDropped", 0)))
    for code, n in sorted((rep.get("counts") or {}).items(), key=lambda kv: -kv[1]):
        pages_ = sorted({it["page"] + 1 for it in rep["issues"] if it["code"] == code
                         and it.get("page") is not None})
        print("  %-15s %4d   стр. %s" % (code, n, ", ".join(map(str, pages_[:20]))))
    print("полный отчёт: %s" % (d / "qa.json"))


if __name__ == "__main__":
    main_()
