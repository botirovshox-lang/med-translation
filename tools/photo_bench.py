"""Фото-бенч: снимки корпуса через НАСТОЯЩИЙ конвейер с ЗАМОРОЖЕННЫМИ чтением
и переводом — мерка «до/после» правил печати надписей без единого вызова
модели (ТЗ docs/plans/photo-first-export.md, шаг Б1).

    python tools/photo_bench.py CORPUS_DIR OUT_DIR [--only 65,66] [--fixtures DIR]
                                [--baseline FILE] [--write-baseline] [--check]

CORPUS_DIR — снимки и manifest.json (`tools/corpus_build.py OUT --set2`, фото
19–30 и 61–70). Замороженные ответы — `tests/fixtures/photo_bench/<id>/`:
`read.json` (ответ «зрячей модели» на разбор, формат модели) и `tr.json`
({оригинал блока: перевод}). Конвейер: разбор картинок (`_job_images`) →
перевод из файла → выгрузка (`_export_images_file`) → приёмка по пикселям
(`_export_qa_run`) — те же функции, что на сервере. Итог — OUT/<id>.<ext>,
OUT/summary.json: находки приёмки по видам, их вес, счётчики выгрузки.

Перевод заморожен, поэтому разница с базой — это разница ВЁРСТКИ, а не
другого перевода. Детектор строк кэшируется на диск по отпечатку картинки
(OUT/../det_cache): у оригиналов он считается один раз, у выгрузки — заново.
`--check` — код возврата 1, если у файла вес находок вырос больше допуска
(`PHOTO_BENCH_TOL`, 1) против базы."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "photo_bench"
BASE = ROOT / "tests" / "fixtures" / "photo_bench_baseline.json"
TOL = int(os.environ.get("PHOTO_BENCH_TOL", "1"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
# Счётчики выгрузки, которые называют исход блока (перерисовано, оставлено,
# подписью, отказ) — их и сравниваем с базой рядом с находками приёмки.
STAT_KEYS = ("img_repainted", "img_same", "img_small_kept", "img_collide", "img_captioned",
             "img_flat", "img_font", "img_vertical", "img_failed", "img_overflow", "img_untranslated")


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def _engine_version() -> str:
    """Версия движка поиска строк — часть ключа кэша: рамки 1.2.3 и 1.4.4
    различаются (у 1.2.3 на развороте 65 пропадали первые строки страниц),
    и кэш от другой версии мерил бы не ту геометрию, что на сервере."""
    try:
        from importlib.metadata import version
        return version("rapidocr-onnxruntime")
    except Exception:
        return "?"


def _cached_detect(fn, cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    ver = _engine_version()

    def det(blob, *a, **k):
        key = hashlib.sha1(bytes(blob) + repr((ver, a, sorted(k.items()))).encode()).hexdigest()
        f = cache / (key + ".json")
        if f.exists():
            got = json.loads(f.read_text(encoding="utf-8"))
            return None if got == "none" else got
        got = fn(blob, *a, **k)
        f.write_text(json.dumps("none" if got is None else got), encoding="utf-8")
        return got
    return det


def weight(rep: dict, sev: dict) -> int:
    return sum(int(sev.get(i.get("code"), 1)) for i in (rep.get("issues") or []))


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("out")
    ap.add_argument("--only", default="")
    ap.add_argument("--fixtures", default=str(FIX))
    ap.add_argument("--baseline", default=str(BASE))
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    cdir, odir, fdir = Path(a.corpus).resolve(), Path(a.out).resolve(), Path(a.fixtures).resolve()
    odir.mkdir(parents=True, exist_ok=True)
    for k, v in (("APP_PASSWORD", "offline"), ("WARM_CACHES", "0"), ("AUTO_RESEGMENT", "0"),
                 ("AUTO_READ_IMAGES", "0"), ("ANTHROPIC_API_KEY", "offline"),
                 ("OPENAI_API_KEY", "offline"), ("PREPRESS", "off"), ("METRICS", "0")):
        os.environ.setdefault(k, v)
    os.environ["EXPORT_QA"] = "1"
    os.environ["EXPORT_QA_VISION"] = "off"
    os.environ.pop("DATABASE_URL", None)        # стенд не пишет ни в какую базу
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    import main
    import image_text
    image_text.detect_lines = _cached_detect(image_text.detect_lines, odir.parent / "det_cache")
    main.image_text.detect_lines = image_text.detect_lines
    tmp = Path(tempfile.mkdtemp(prefix="photo_bench_"))
    main.SOURCE_DIR = tmp / "src"
    main.SOURCE_DIR.mkdir()
    main.EXPORT_DIR = tmp / "exp"
    main.save_state = lambda *x, **k: None
    main._export_qa_tell = lambda *x, **k: None
    got_qa = {}
    main._qa_write = lambda path, rep: got_qa.__setitem__(str(path), rep)
    man = json.loads((cdir / "manifest.json").read_text(encoding="utf-8"))
    only = [x for x in a.only.split(",") if x]
    cur = {}

    class _Resp:
        def __init__(self, text):
            msg = type("M", (), {"content": text})()
            self.choices = [type("C", (), {"message": msg, "finish_reason": "stop"})()]
            self.usage = None

    class _Client:
        def __init__(self):
            self.chat = type("Ch", (), {})()
            self.chat.completions = type("Co", (), {"create": self._create})()

        def _create(self, **kw):
            return _Resp(cur["read"])

    # Одна порция чтения на картинку: заглушка отвечает за ВСЕ блоки сразу
    # (порции по IMAGE_READ_MAX_BLOCKS нумеруют блоки заново с нуля).
    main.IMAGE_READ_MAX_BLOCKS = 10 ** 6
    main._llm_client = lambda *x, **k: _Client()
    main._provider_ready = lambda *x, **k: True
    sev = getattr(main.export_qa_mod, "SEVERITY", {}) or {}
    summary = {}
    print("движок строк:", _engine_version(), "(на сервере — версия из requirements.txt)")
    for k, m in enumerate(man):
        if only and not any(m["id"].startswith(o) for o in only):
            continue
        fx = fdir / m["id"]
        if not (fx / "read.json").exists() or not (fx / "tr.json").exists():
            print(m["id"], "— нет замороженных ответов в", fx)
            continue
        cur["read"] = (fx / "read.json").read_text(encoding="utf-8")
        tr = {_norm(s): t for s, t in json.loads((fx / "tr.json").read_text(encoding="utf-8")).items()}
        blob = (cdir / m["file"]).read_bytes()
        parsed = main._parse_upload(m["file"], blob)
        pid = 9600 + k
        p = {"id": pid, "title": m["id"], "fileName": m["file"], "src": m["src"], "tgt": m["tgt"],
             "domain": "general", "tenant": "default", "segments": [], "importKind": parsed["kind"]}
        units = parsed.get("units") or []
        p["segments"] = main._new_segments([t for t, _ in units]) if units else []
        paras = [t for t, _f in (parsed.get("texts") or [])]
        pairs = [[i, u + 1] for u, (_t, idxs) in enumerate(units) for i in idxs]
        main._store_source_docx(p, parsed["docx"], m["file"], pairs, len(paras),
                                layout=parsed.get("layout"))
        main._store_original(pid, m["file"], blob)
        main.STATE.setdefault("projects", []).append(p)
        job = {"id": pid, "project": pid, "kind": "images", "tenant": "default", "status": "running",
               "params": {"dry_run": False}, "counters": {}, "done": 0, "total": 0, "stop": False,
               "createdAt": 0, "recent": []}
        try:
            main._job_images(job)
        except Exception as e:
            print(m["id"], "сбой разбора:", repr(e))
            continue
        # Эталон обязан отвечать за КАЖДЫЙ найденный блок: блок без ответа —
        # неполный эталон (так было с порциями чтения по 8 блоков), и мерить
        # по нему вёрстку нельзя.
        smap = main._load_source_map(pid) or {}
        unread = sum(1 for im in (smap.get("images") or []) for b in (im.get("blocks") or [])
                     if "text" not in b and b.get("skip") not in ("layer", "figure"))
        if unread:
            print(m["id"], "— эталон неполный: блоков без ответа", unread)
        miss = 0
        for s in p["segments"]:
            t = tr.get(_norm(s.get("source")))
            if t:
                s["target"], s["status"] = main._lang_normalize(t, m["tgt"], s["source"]), "translated"
            elif (s.get("source") or "").strip():
                miss += 1
        ext = Path(m["file"]).suffix.lower()
        out = odir / (m["id"] + ext)
        st = main._export_images_file(p, out, odir / "tmp.bin", ext)
        (odir / "tmp.bin").replace(out)
        rep = {}
        inp = main._QA_INPUTS.pop(pid, None)
        if inp is not None:
            segs = p["segments"]
            lang = main.export_qa_mod.Lang([s_.get("source") or "" for s_ in segs],
                                           [s_.get("target") or "" for s_ in segs])
            sig = main._qa_file_sig(out)
            main._export_qa_run(pid, "original", out, sig, inp, lang, "default", m["id"], m["src"], m["tgt"])
            rep = got_qa.get(str(out)) or {}
        counts = {}
        for i in rep.get("issues") or []:
            counts[i.get("code")] = counts.get(i.get("code"), 0) + 1
        summary[m["id"]] = {"weight": weight(rep, sev), "counts": counts, "noTr": miss, "unread": unread,
                            "segments": len(p["segments"]),
                            "stats": {k_: st.get(k_) for k_ in STAT_KEYS if st.get(k_)}}
        print("%-20s вес %3d  %s  %s" % (m["id"], summary[m["id"]]["weight"], counts,
                                          summary[m["id"]]["stats"]))
    (odir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.write_baseline:
        Path(a.baseline).write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True),
                                    encoding="utf-8")
        print("база записана:", a.baseline)
    base = json.loads(Path(a.baseline).read_text(encoding="utf-8")) if Path(a.baseline).exists() else {}
    worse = []
    if base:
        print("\n%-20s %6s %6s" % ("файл", "было", "стало"))
        for id_, r in summary.items():
            b = base.get(id_)
            if not b:
                continue
            mark = ""
            if r["weight"] > b["weight"] + TOL:
                mark = "  ХУЖЕ"
                worse.append(id_)
            elif r["weight"] < b["weight"]:
                mark = "  лучше"
            print("%-20s %6d %6d%s" % (id_, b["weight"], r["weight"], mark))
        print("сумма: было %d, стало %d" % (sum(base[i]["weight"] for i in summary if i in base),
                                             sum(r["weight"] for i, r in summary.items() if i in base)))
    if a.check and worse:
        print("ХУЖЕ базы:", ", ".join(worse))
        sys.exit(1)


if __name__ == "__main__":
    main_()
