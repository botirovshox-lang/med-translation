"""Картинки корпуса ЧЕРЕЗ CLAUDE, без API: настоящий конвейер разбора картинок
(детектор строк, блоки, промпт чтения, разбор ответа, сегменты, выгрузка),
а ответ «зрячей модели» и перевод пишет Claude (агент или человек) файлами.

    python tools/corpus_claude_images.py CORPUS_DIR WORK_DIR --only 26,27

Проход 1 (нет ответа): WORK/<id>/ask/ — обзор и вырезки блоков, ask.json —
номера блоков. Ответ кладётся в WORK/<id>/read.json —
{"blocks": [{"i": 0, "text": "...", "overlay": false, "hand": false, "serif": false}]}
(тот же формат, что у модели). Проход 2 (есть read.json): сегменты в
WORK/<id>/segments.json; перевод — WORK/<id>/tr.json {"<id сегмента>": "перевод"}.
Проход 3 (есть tr.json): выгрузка WORK/<id>/out.<ext> и пара out_pair.png.

Нужен, когда ключ поставщика недоступен, а проверить трудные картинки надо;
модель не зовётся ни разу.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


class _Ask(BaseException):
    pass


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("work")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    cdir, wdir = Path(a.corpus).resolve(), Path(a.work).resolve()
    wdir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("APP_PASSWORD", "offline")
    os.environ.setdefault("WARM_CACHES", "0")
    os.environ.setdefault("AUTO_RESEGMENT", "0")
    os.environ.setdefault("AUTO_READ_IMAGES", "0")
    os.environ.setdefault("ANTHROPIC_API_KEY", "offline")
    os.environ.setdefault("OPENAI_API_KEY", "offline")
    os.environ["EXPORT_QA"] = "0"
    os.environ.pop("DATABASE_URL", None)        # стенд не пишет ни в какую базу
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    import main
    tmp = Path(tempfile.mkdtemp(prefix="corpus_claude_"))
    main.SOURCE_DIR = tmp / "src"
    main.SOURCE_DIR.mkdir()
    main.EXPORT_DIR = tmp / "exp"
    main.save_state = lambda *x, **k: None
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
            d = cur["dir"]
            rf = d / "read.json"
            if rf.exists():
                return _Resp(rf.read_text(encoding="utf-8"))
            ask = d / "ask"
            ask.mkdir(exist_ok=True)
            blocks, n = [], 0
            label = "overview"
            for part in kw["messages"][1]["content"]:
                if part.get("type") == "text":
                    label = part["text"].rstrip(":").replace(" ", "_").lower()
                    continue
                url = part["image_url"]["url"]
                (ask / ("%02d_%s.png" % (n, label))).write_bytes(base64.b64decode(url.split(",", 1)[1]))
                if label.startswith("block_"):
                    blocks.append(int(label.split("_")[1]))
                n += 1
            (d / "ask.json").write_text(json.dumps({"blocks": blocks, "system": kw["messages"][0]["content"]},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
            raise _Ask()

    main._llm_client = lambda *x, **k: _Client()
    main._provider_ready = lambda *x, **k: True
    for k, m in enumerate(man):
        if only and not any(m["id"].startswith(o) for o in only):
            continue
        d = wdir / m["id"]
        d.mkdir(exist_ok=True)
        cur["dir"] = d
        blob = (cdir / m["file"]).read_bytes()
        parsed = main._parse_upload(m["file"], blob)
        pid = 9500 + k
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
        except _Ask:
            print(m["id"], "→ прочитать вырезки:", d / "ask")
            continue
        except Exception as e:
            print(m["id"], "сбой разбора:", repr(e))
            continue
        segs = [s for s in p["segments"]]
        (d / "segments.json").write_text(json.dumps(
            [{"id": s["id"], "source": s["source"]} for s in segs], ensure_ascii=False, indent=1),
            encoding="utf-8")
        tf = d / "tr.json"
        if not tf.exists():
            print(m["id"], "→ перевести сегменты:", d / "segments.json", len(segs))
            continue
        tr = json.loads(tf.read_text(encoding="utf-8"))
        for s in segs:
            t = tr.get(str(s["id"]))
            if t:
                s["target"], s["status"] = main._lang_normalize(t, m["tgt"], s["source"]), "translated"
        ext = Path(m["file"]).suffix.lower()
        out = d / ("out" + ext)
        st = main._export_images_file(p, out, d / "tmp.bin", ext if ext != ".pdf" else ".pdf")
        (d / "tmp.bin").replace(out)
        print(m["id"], "выгрузка:", out, {k_: v for k_, v in st.items() if k_.startswith("img_") and v})


if __name__ == "__main__":
    main_()
