"""Прогон тестового корпуса (`tools/corpus_build.py`) через боевой API.

Запускается НА СЕРВЕРЕ (рядом с API), стадиями и с памятью: состояние —
`state.json` в рабочем каталоге, повторный запуск продолжает с того места,
где остановился. Платно: полный конвейер по каждому файлу + платный взгляд
приёмки (правило очереди сверки — до $1 на файл).

  python corpus_run.py WORKDIR [stage ...]     stages: upload translate export qa collect

WORKDIR содержит файлы корпуса и `manifest.json`. Итог — `WORKDIR/out/<id>/`:
выгрузки, отчёт приёмки, строки проекта (оригинал/перевод/вердикты) и
сводка `WORKDIR/out/summary.json`; архив — `WORKDIR/out.tgz`.
"""
from __future__ import annotations

import json
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("CORPUS_API", "http://127.0.0.1:8000/api")
WD = Path(sys.argv[1])
STAGES = sys.argv[2:] or ["upload", "translate", "export", "qa", "collect"]
STATE = WD / "state.json"
OUT = WD / "out"
LOG = WD / "run.log"


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def env():
    return dict(l.strip().split("=", 1) for l in open("/etc/medcat/env", encoding="utf-8")
                if "=" in l and not l.lstrip().startswith("#"))


_TOK = {}


def tok():
    if "t" not in _TOK:
        r = call("POST", "/auth/login", {"login": "admin", "password": env()["APP_PASSWORD"]}, auth=False)
        _TOK["t"] = r["token"]
    return _TOK["t"]


def call(method, path, body=None, auth=True, timeout=900, raw=False, data=None, ctype=None):
    hdr = {}
    if auth:
        hdr["Authorization"] = "Bearer " + tok()
    if data is None and body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    if ctype:
        hdr["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=hdr)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                return b if raw else json.loads(b.decode() or "null")
        except urllib.error.HTTPError as e:
            if e.code == 401 and auth and attempt == 0:
                _TOK.clear()
                req.headers["Authorization"] = "Bearer " + tok()
                continue
            return {"_http": e.code, "_body": e.read().decode(errors="replace")[:400]}
        except Exception as e:  # сервис перезапускался — подождать
            if attempt == 2:
                return {"_err": repr(e)}
            time.sleep(20)


def multipart(fields: dict, fname: str, blob: bytes):
    b = "----corpus" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (b, fname)).encode() + blob + b"\r\n")
    parts.append(("--%s--\r\n" % b).encode())
    return b"".join(parts), "multipart/form-data; boundary=" + b


def load():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"items": {}}


def save(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, STATE)


def busy(pid):
    j = call("GET", "/jobs?project=%d&limit=5" % pid)
    act = (j or {}).get("active") or []
    if act:
        return True
    p = call("GET", "/projects/%d" % pid)
    return bool(p.get("autoResegRunning") or p.get("imagesReading"))


def wait_idle(pids, what, limit_s=5400):
    t0 = time.time()
    left = list(pids)
    while left and time.time() - t0 < limit_s:
        left = [p for p in left if busy(p)]
        if left:
            log("ждём", what, "проекты:", left)
            time.sleep(30)
    return left


def stage_upload(st, man):
    fid = st.get("folder")
    if not fid:
        f = call("POST", "/folders", {"title": "Корпус приёмки " + time.strftime("%d.%m %H:%M"),
                                      "src": "RU", "tgt": "EN", "domain": "general"})
        fid = st["folder"] = f.get("id")
        save(st)
        log("папка", fid, f if not fid else "")
    for m in man:
        it = st["items"].setdefault(m["id"], {})
        if it.get("pid"):
            continue
        blob = (WD / m["file"]).read_bytes()
        data, ct = multipart({"title": m["id"], "src": m["src"], "tgt": m["tgt"], "domain": "general",
                              "folder": str(fid)}, m["file"], blob)
        r = call("POST", "/projects/upload", data=data, ctype=ct, timeout=1800)
        if not isinstance(r, dict) or not r.get("id"):
            log("ЗАГРУЗКА НЕ ВЫШЛА", m["id"], r)
            it["uploadError"] = r
        else:
            it["pid"] = r["id"]
            it["kind"] = r.get("importKind")
            log("загружен", m["id"], "pid", r["id"], r.get("importKind"), "строк", len(r.get("segments") or []))
        save(st)


def stage_translate(st, man):
    pids = [st["items"][m["id"]]["pid"] for m in man if st["items"].get(m["id"], {}).get("pid")]
    wait_idle(pids, "чтения надписей/пересборки")
    for m in man:
        it = st["items"].get(m["id"]) or {}
        pid = it.get("pid")
        if not pid or it.get("fullJob"):
            continue
        p = call("GET", "/projects/%d" % pid)
        ids = [s["id"] for s in p.get("segments") or []]
        it["segments"] = len(ids)
        if not ids:
            log("нет строк", m["id"], "pid", pid, (p.get("imagesSkipped") or ""), (p.get("importNote") or "")[:200])
            it["fullJob"] = -1
            save(st)
            continue
        r = call("POST", "/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": ids, "params": {}})
        job = (r or {}).get("job") or r
        it["fullJob"] = (job or {}).get("id") or -1
        log("прогон", m["id"], "pid", pid, "строк", len(ids), "задача", it["fullJob"], r if "_http" in (r or {}) else "")
        save(st)
    left = wait_idle(pids, "прогонов", limit_s=4 * 3600)
    # строки, появившиеся после постановки (надписи дочитаны позже), — перевести
    for m in man:
        pid = (st["items"].get(m["id"]) or {}).get("pid")
        if not pid:
            continue
        p = call("GET", "/projects/%d" % pid)
        empty = [s["id"] for s in p.get("segments") or []
                 if not (s.get("target") or "").strip() and s.get("status") != "confirmed"]
        if empty:
            log("допереводим", m["id"], len(empty))
            call("POST", "/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": empty, "params": {}})
    wait_idle(pids, "допереводов", limit_s=3600)


def _formats(m):
    f = [m["export"]]
    if m["export"] == "original" and m["file"].rsplit(".", 1)[-1].lower() in ("png", "jpg", "jpeg"):
        f.append("pdf")
    if m["export"] == "docx_layout":
        f.append("pdf")
    return f


def stage_export(st, man):
    for m in man:
        it = st["items"].get(m["id"]) or {}
        pid = it.get("pid")
        if not pid:
            continue
        it.setdefault("exports", {})
        for fmt in _formats(m):
            r = call("POST", "/projects/%d/export" % pid, {"format": fmt, "source": True}, timeout=1800)
            t0 = time.time()
            while (r or {}).get("pending") and time.time() - t0 < 3600:
                # Ы5: файл проверяется моделью перед выдачей — ждём и спрашиваем снова
                pp = call("GET", "/projects/%d/prepress" % pid)
                log("проверка перед выдачей", m["id"], fmt, (pp or {}).get("state"), (pp or {}).get("done"),
                    "/", (pp or {}).get("total"))
                if (pp or {}).get("state") == "running":
                    time.sleep(20)
                    continue
                r = call("POST", "/projects/%d/export" % pid, {"format": fmt, "source": True}, timeout=1800)
                if (r or {}).get("pending"):
                    time.sleep(20)
            pp = call("GET", "/projects/%d/prepress" % pid)
            it.setdefault("prepress", {})[fmt] = pp
            st_ = (r or {}).get("stats") or {}
            it["exports"][fmt] = {"ok": r.get("ok"), "file": r.get("file"), "error": r.get("error"),
                                  "stats": {k: st_.get(k) for k in (
                                      "pdfFrom", "collisions", "overflow", "dupDropped", "imageBoxes",
                                      "leftover", "img_repainted", "written", "missing", "layoutWhy", "loop",
                                      "prepress", "paintPlate", "img_vertical")}}
            log("выгрузка", m["id"], fmt, r.get("ok"), r.get("file") or r.get("error"))
            save(st)


def stage_qa(st, man):
    for m in man:
        it = st["items"].get(m["id"]) or {}
        pid = it.get("pid")
        if not pid:
            continue
        for fmt in (it.get("exports") or {}):
            for k in range(60):
                q = call("GET", "/projects/%d/export/qa?format=%s" % (pid, fmt))
                if (q or {}).get("state") not in ("running", None, "none"):
                    break
                time.sleep(10)
            it.setdefault("qa", {})[fmt] = {k: q.get(k) for k in ("state", "ok", "pages", "checked", "counts", "det")}
            if fmt == "pdf" and q.get("state") == "done" and not (q.get("vision") or {}).get("state") == "done":
                v = call("POST", "/admin/export-qa/%d?format=pdf" % pid, timeout=900)
                it["qa"][fmt]["visionCall"] = {k: (v or {}).get(k) for k in ("ok", "state", "_http", "_body")}
            log("приёмка", m["id"], fmt, json.dumps(it["qa"][fmt], ensure_ascii=False)[:300])
            save(st)


def stage_collect(st, man):
    OUT.mkdir(exist_ok=True)
    summary = []
    for m in man:
        it = st["items"].get(m["id"]) or {}
        pid = it.get("pid")
        d = OUT / m["id"]
        d.mkdir(exist_ok=True)
        row = {"id": m["id"], "pid": pid, "what": m["what"], "hard": m["hard"], "src": m["src"], "tgt": m["tgt"]}
        if not pid:
            row["error"] = it.get("uploadError")
            summary.append(row)
            continue
        p = call("GET", "/projects/%d" % pid)
        segs = [{"id": s["id"], "src": s.get("source"), "tgt": s.get("target"), "status": s.get("status"),
                 "kind": (s.get("origin") or {}).get("part") and "image" or "text",
                 "review": {k: (s.get("review") or {}).get(k) for k in ("score", "code", "applied")},
                 "bc": (s.get("backcheck") or {}).get("score"),
                 "tc": len((s.get("termcheck") or {}).get("findings") or [])}
                for s in p.get("segments") or []]
        (d / "segments.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
        row["segments"] = len(segs)
        row["empty"] = sum(1 for s in segs if not (s["tgt"] or "").strip())
        row["importKind"] = p.get("importKind")
        row["importNote"] = (p.get("importNote") or "")[:400]
        row["imagesSkipped"] = p.get("imagesSkipped")
        row["exports"] = it.get("exports")
        row["prepress"] = it.get("prepress")
        for fmt, ex in (it.get("exports") or {}).items():
            if not ex.get("ok"):
                continue
            b = call("GET", "/projects/%d/export/download?format=%s&source=1" % (pid, fmt), raw=True, timeout=900)
            if isinstance(b, bytes):
                (d / ("out_%s_%s" % (fmt, ex.get("file") or "file"))).write_bytes(b)
            q = call("GET", "/projects/%d/export/qa?format=%s" % (pid, fmt))
            (d / ("qa_%s.json" % fmt)).write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
            row.setdefault("qa", {})[fmt] = {k: q.get(k) for k in ("state", "ok", "counts")}
            v = q.get("vision") or {}
            if v:
                row["qa"][fmt]["vision"] = {k: v.get(k) for k in ("state", "confirmed", "dismissed", "cost")}
        summary.append(row)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    with tarfile.open(WD / "out.tgz", "w:gz") as tf:
        tf.add(OUT, arcname="out")
    log("собрано", WD / "out.tgz")


def main():
    man = json.loads((WD / "manifest.json").read_text(encoding="utf-8"))
    only = os.environ.get("CORPUS_ONLY")
    if only:
        man = [m for m in man if m["id"] in only.split(",")]
    st = load()
    for s in STAGES:
        log("=== стадия", s)
        globals()["stage_" + s](st, man)
        save(st)
    log("ГОТОВО")


if __name__ == "__main__":
    main()
