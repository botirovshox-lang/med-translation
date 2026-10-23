"""Корпус выгрузки ОФЛАЙН: импорт → псевдоперевод → PDF «как в оригинале» →
приёмка. Бесплатно и без сервера: проверка правил чтения и вёрстки текущим
кодом рабочей копии на файлах `tools/corpus_build.py`.

    python tools/corpus_offline.py CORPUS_DIR OUT_DIR [--only 01,05] [--json]

Перевод — местная подмена слов псевдословами той длины, какой бывает
перевод на язык цели (`backend/synth.py`, коэффициенты `expansion`), — то
есть проверяется МЕСТО и ВЁРСТКА, а не смысл. Для картинок и сканов нужен
разбор надписей зрячей моделью — их офлайн-корпус пропускает (их гоняет
`tools/corpus_run.py` через сервер).

Пишет OUT_DIR/<id>.pdf (выгрузка), OUT_DIR/<id>.qa.json и сводку
OUT_DIR/summary.json; код возврата 1 — есть находки тяжести ≥ 2.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("out")
    ap.add_argument("--only", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-detect", action="store_true")
    a = ap.parse_args()
    cdir, odir = Path(a.corpus).resolve(), Path(a.out).resolve()
    odir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("APP_PASSWORD", "offline")
    os.environ.setdefault("WARM_CACHES", "0")
    os.environ.setdefault("AUTO_RESEGMENT", "0")
    os.environ.setdefault("AUTO_READ_IMAGES", "0")
    os.environ["EXPORT_QA"] = "0"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    import main
    import export_qa
    import synth
    sdata = synth.load()
    work = Path(tempfile.mkdtemp(prefix="corpus_off_"))
    main.SOURCE_DIR = work / "src"
    main.SOURCE_DIR.mkdir()
    main.EXPORT_DIR = work / "exp"
    main.save_state = lambda *x, **k: None
    man = json.loads((cdir / "manifest.json").read_text(encoding="utf-8"))
    only = [x for x in a.only.split(",") if x]
    summary = []
    bad_any = False
    for k, m in enumerate(man):
        if only and not any(m["id"].startswith(o) for o in only):
            continue
        ext = m["file"].rsplit(".", 1)[-1].lower()
        if ext != "pdf" or m.get("hard"):
            continue
        blob = (cdir / m["file"]).read_bytes()
        parsed = main._parse_upload(m["file"], blob)
        if parsed["kind"] != "pdf":
            continue
        pid = 9000 + k
        units = parsed["units"]
        tgt = m["tgt"]
        lang = {"UZ-CYRL": "uz_cyrl"}.get(tgt, tgt.lower())
        fac = float((sdata.get("expansion") or {}).get(lang, 1.15))
        segs = main._new_segments([t for t, _ in units])
        for s in segs:
            s["target"] = synth.pseudo(s["source"], lang, fac, 0, True, sdata)
            s["status"] = "translated"
        project = {"id": pid, "title": m["id"], "src": m["src"], "tgt": tgt, "domain": "general",
                   "tenant": "default", "fileName": m["file"], "importKind": "pdf",
                   "segments": segs}
        paras = [t for t, _f in parsed["texts"]]
        pairs = [[i, u + 1] for u, (_t, idxs) in enumerate(units) for i in idxs]
        main._store_source_docx(project, parsed["docx"], m["file"], pairs, len(paras),
                                layout=parsed.get("layout"))
        main._store_original(pid, m["file"], blob)
        out = odir / (m["id"] + ".pdf")
        try:
            stats = main._export_pdf_layout(project, out)
        except Exception as e:
            summary.append({"id": m["id"], "error": "%s: %s" % (type(e).__name__, e)})
            print("%-18s ОШИБКА %s" % (m["id"], e))
            bad_any = True
            continue
        if stats is None:
            summary.append({"id": m["id"], "error": "нет раскладки"})
            continue
        inp = main._QA_INPUTS.pop(pid, None)
        det = None
        if not a.no_detect:
            try:
                import image_text
                if image_text.engine_ready()[0]:
                    det = image_text.detect_lines
            except Exception:
                det = None
        lng = export_qa.Lang([s["source"] for s in segs], [s["target"] for s in segs])
        rep = export_qa.inspect_pdf(inp["work"], out.read_bytes(), inp["layout"], inp["texts"],
                                    inp["extra"], lng, overlay=inp.get("overlay"),
                                    overlay_order=inp.get("order"), detect=det,
                                    sources=inp.get("sources"))
        (odir / (m["id"] + ".qa.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                                    encoding="utf-8")
        counts = rep.get("counts") or {}
        bad = {c: n for c, n in counts.items() if export_qa.SEVERITY.get(c, 1) >= 2}
        bad_any = bad_any or bool(bad)
        row = {"id": m["id"], "segments": len(segs), "counts": counts,
               "collisions": stats.get("collisions"), "overflow": stats.get("overflow")}
        summary.append(row)
        print("%-18s строк %3d  наложений %s  вылетов %s  приёмка %s" % (
            m["id"], len(segs), stats.get("collisions"), stats.get("overflow"),
            json.dumps(counts, ensure_ascii=False)))
    (odir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if bad_any else 0)


if __name__ == "__main__":
    main_()
