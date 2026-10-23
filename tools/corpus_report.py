"""Сводка прогона корпуса: проходимость по стадиям и картинки «до | после».

    python tools/corpus_report.py CORPUS_DIR OUT_DIR REPORT_DIR

OUT_DIR — распакованный `out/` из `tools/corpus_run.py` (summary.json,
<id>/qa_*.json, <id>/out_*). Пишет REPORT_DIR/report.json и пары картинок
REPORT_DIR/<id>.jpg (слева оригинал, справа выгрузка, первая страница).

Проходимость считает ПРИЁМКА ПО ПИКСЕЛЯМ (`export_qa`), а не модель, которая
чинила (самооценка исключена). Три стадии у PDF «как в оригинале»:
  before — первая сборка по правилам (до петли Ы),
  loop   — после петли «проверил — переверстал»,
  final  — отданный файл (после проверки моделью перед выдачей).
Лист/файл проходит, когда на нём нет находок тяжести ≥ 2; находка
с `verify`, которую платный взгляд отклонил, не считается.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

try:
    import export_qa
    SEV = dict(export_qa.SEVERITY) if hasattr(export_qa, "SEVERITY") else {}
except Exception:                       # pragma: no cover
    SEV = {}
if not SEV:
    SEV = {"UNTRANSLATED": 2, "NOT_TRANSLATED": 1, "OVERPRINT": 2, "SPILL": 2, "SILENT": 2, "BLANK": 2,
           "RESIDUE": 2, "DUPLICATE": 2, "PAGES": 3, "SMALL": 2, "SIZE_MIX": 1, "OVERFLOW": 2,
           "RULE_CUT": 2, "MARK_LOST": 2, "GHOST": 2, "LOW_CONTRAST": 2}


def hard(counts: "dict | None") -> int:
    return sum(n for c, n in (counts or {}).items() if SEV.get(c, 2) >= 2)


def final_counts(qa: dict) -> dict:
    """Находки отданного файла без отклонённых платным взглядом."""
    counts = dict(qa.get("counts") or {})
    v = qa.get("vision") or {}
    for d in v.get("issues") or []:
        # Находку приёмки, которую платный взгляд назвал ложной (real: false),
        # не считаем; собственные находки взгляда (vision: true) — отдельно.
        if not isinstance(d, dict) or d.get("vision") or d.get("real") is not False:
            continue
        c = d.get("code")
        if c and counts.get(c):
            counts[c] -= 1
            if counts[c] <= 0:
                counts.pop(c)
    return counts


def vision_found(qa: dict) -> list:
    v = qa.get("vision") or {}
    return [{"code": d.get("code"), "what": d.get("what")} for d in v.get("issues") or []
            if isinstance(d, dict) and d.get("vision") and d.get("real")]


def first_page(path: Path):
    from PIL import Image
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pypdfium2 as P
        d = P.PdfDocument(str(path))
        try:
            return d[0].render(scale=1.4).to_pil().convert("RGB")
        finally:
            d.close()
    if ext in (".png", ".jpg", ".jpeg"):
        return Image.open(path).convert("RGB")
    return None


def pair(a, b, label: str):
    from PIL import Image, ImageDraw
    h = 900
    a = a.resize((max(1, int(a.width * h / a.height)), h))
    b = b.resize((max(1, int(b.width * h / b.height)), h))
    im = Image.new("RGB", (a.width + b.width + 12, h + 26), (60, 60, 60))
    im.paste(a, (0, 26))
    im.paste(b, (a.width + 12, 26))
    ImageDraw.Draw(im).text((6, 6), label, fill=(255, 255, 255))
    return im


def main(argv):
    cdir, odir, rdir = Path(argv[1]), Path(argv[2]), Path(argv[3])
    rdir.mkdir(parents=True, exist_ok=True)
    man = {m["id"]: m for m in json.loads((cdir / "manifest.json").read_text(encoding="utf-8"))}
    summ = json.loads((odir / "summary.json").read_text(encoding="utf-8"))
    rows = []
    for s in summ:
        rid = s["id"]
        m = man.get(rid, {})
        d = odir / rid
        row = {"id": rid, "pair": "%s→%s" % (s.get("src"), s.get("tgt")), "what": s.get("what"),
               "kind": s.get("importKind"), "segments": s.get("segments"), "empty": s.get("empty")}
        exps = s.get("exports") or {}
        main_fmt = m.get("export")
        pdf_fmt = "pdf" if "pdf" in exps else main_fmt
        st_ = ((exps.get(pdf_fmt) or {}).get("stats") or {})
        loop = st_.get("loop") or {}
        qa_p = d / ("qa_%s.json" % pdf_fmt)
        qa = json.loads(qa_p.read_text(encoding="utf-8")) if qa_p.exists() else {}
        # Приёмка не сравнивала (нет оригинала листами: Word, Excel, HTML…) —
        # «не проверено», а не «прошло».
        fin = final_counts(qa) if qa.get("pages") else None
        row["before"] = loop.get("before") if loop.get("before") is not None else None
        row["loop"] = loop.get("after") if loop.get("after") is not None else None
        row["final"] = fin
        row["visionFound"] = vision_found(qa)
        row["pages"] = qa.get("pages")
        pp = (s.get("prepress") or {}).get(pdf_fmt) or {}
        row["prepress"] = {k: pp.get(k) for k in ("state", "fixed", "left", "checked", "pages")}
        row["pass"] = (fin is not None and hard(fin) == 0)
        row["qaState"] = qa.get("state")
        # картинки «до | после»
        out_file = None
        for f in sorted(d.glob("out_*")):
            if f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
                if out_file is None or f.suffix.lower() != ".pdf":
                    out_file = f if (out_file is None or f.suffix.lower() in (".png", ".jpg", ".jpeg")) else out_file
        src_file = cdir / m.get("file", "")
        try:
            a = first_page(src_file) if src_file.exists() else None
            b = first_page(out_file) if out_file else None
            if a is not None and b is not None:
                pair(a, b, "%s  %s  (слева оригинал, справа выгрузка)" % (rid, row["pair"])).save(
                    rdir / ("%s.jpg" % rid), quality=82)
                row["image"] = "%s.jpg" % rid
        except Exception as e:
            row["imageError"] = repr(e)[:200]
        rows.append(row)
    pdfish = [r for r in rows if r["final"] is not None]
    agg = {"files": len(rows), "checked": len(pdfish),
           "pass_final": sum(1 for r in pdfish if r["pass"]),
           "pass_before": sum(1 for r in pdfish if r["before"] is not None and hard(r["before"]) == 0),
           "pass_loop": sum(1 for r in pdfish if r["loop"] is not None and hard(r["loop"]) == 0),
           "with_loop": sum(1 for r in pdfish if r["before"] is not None)}
    (rdir / "report.json").write_text(json.dumps({"agg": agg, "rows": rows}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    for r in rows:
        print("%-22s %-10s before=%s loop=%s final=%s pass=%s pp=%s" % (
            r["id"], r["pair"], hard(r["before"]) if r["before"] is not None else "-",
            hard(r["loop"]) if r["loop"] is not None else "-",
            json.dumps(r["final"], ensure_ascii=False) if r["final"] is not None else "-", r["pass"],
            (r["prepress"] or {}).get("fixed")))
    print(json.dumps(agg, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
