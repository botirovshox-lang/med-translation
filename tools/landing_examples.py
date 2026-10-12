"""Примеры работ для click.simpletranslate.me/start/ — через боевую систему.

Запуск: положить исходники в /root/landing-media/in на сервере
(chekhov.txt, okano-sleep-p1-2.pdf, museum-sign.jpg, zero-gravity-coffee.mp4 —
откуда они взяты и под какой лицензией, сказано в design/start/BACKLOG.md),
затем `bash tools/prod_run.sh tools/landing_examples.py`. Это ПЛАТНЫЕ прогоны
(центы), запускать по решению владельца.

Заводит проекты в организации администратора, ждёт разбора и перевода
(полный прогон, параметры — те, что предлагает сам сервер), выгружает
результат в /root/landing-media/out. Повторный запуск продолжает с места:
номера проектов лежат в /root/landing-media/state.json.
"""
import json, os, re, sys, time, urllib.request, urllib.parse, uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path("/root/landing-media")
IN, OUT = ROOT / "in", ROOT / "out"
OUT.mkdir(parents=True, exist_ok=True)
ST_PATH = ROOT / "state.json"
ST = json.loads(ST_PATH.read_text()) if ST_PATH.exists() else {}


def save():
    ST_PATH.write_text(json.dumps(ST, ensure_ascii=False, indent=1))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def env_pw():
    for line in Path("/etc/medcat/env").read_text().splitlines():
        if line.startswith("APP_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("нет APP_PASSWORD")


TOKEN = None


def req(method, path, body=None, raw=None, ctype=None, timeout=600):
    h = {}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw
        h["Content-Type"] = ctype or "application/octet-stream"
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read()
            ct = resp.headers.get("Content-Type", "")
            return json.loads(b) if "json" in ct else b
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s -> %s %s" % (method, path, e.code, e.read()[:500].decode("utf-8", "replace")))


def upload(fname, src, tgt, title):
    p = IN / fname
    bnd = uuid.uuid4().hex
    parts = []
    for k, v in (("src", src), ("tgt", tgt), ("title", title)):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bnd, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (bnd, p.name)).encode()
                 + p.read_bytes() + b"\r\n")
    parts.append(("--%s--\r\n" % bnd).encode())
    return req("POST", "/api/projects/upload", raw=b"".join(parts),
               ctype="multipart/form-data; boundary=" + bnd)


def project(pid):
    return req("GET", "/api/projects/%d" % pid)


def wait_idle(pid, label, limit=1800):
    t0 = time.time()
    while time.time() - t0 < limit:
        j = req("GET", "/api/jobs?project=%d&limit=10" % pid)
        if not j["active"]:
            bad = [x for x in j["jobs"][:3] if x.get("status") == "error"]
            for x in bad:
                log("  ! %s: задача %s %s: %s" % (label, x["id"], x.get("kind"), x.get("error")))
            return j["jobs"]
        a = j["active"][0]
        log("  … %s: %s %s %s/%s" % (label, a.get("kind"), a.get("status"), a.get("done"), a.get("total")))
        time.sleep(15)
    raise RuntimeError("не дождались: " + label)


def run_full(pid, label):
    key = "full:%d" % pid
    if ST.get(key):
        return
    pr = project(pid)
    ids = [s["id"] for s in pr["segments"]]
    if not ids:
        raise RuntimeError("%s: нет строк" % label)
    an = req("GET", "/api/projects/%d/analysis" % pid)
    params = dict(((an.get("turnkey") or {}).get("params")) or {})
    params["auto_terms"] = False
    log("%s: прогон по %d строкам, шаги %s" % (label, len(ids), params.get("steps")))
    r = req("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": ids, "params": params})
    log("  задача", (r.get("job") or r).get("id"))
    ST[key] = True
    save()


def segs_of(pid):
    pr = project(pid)
    return pr, [s for s in pr["segments"]]


def main():
    global TOKEN
    TOKEN = req("POST", "/api/auth/login", {"login": "admin", "password": env_pw()})["token"]
    P = ST.setdefault("p", {})

    # 1. Файлы: книга (RU→4), статья (EN→RU, UZ), табличка (RU→4).
    jobs = [("book", "chekhov.txt", "RU", t, "Лендинг · Чехов «Толстый и тонкий»") for t in ("EN", "UZ", "ZH", "AR")]
    jobs += [("paper", "okano-sleep-p1-2.pdf", "EN", t, "Лендинг · npj Sci Learn 2019 (CC BY)") for t in ("RU", "UZ")]
    jobs += [("sign", "museum-sign.jpg", "RU", t, "Лендинг · табличка ВАЗ-21059 (CC0)") for t in ("EN", "UZ", "ZH", "AR")]
    for kind, fn, s, t, title in jobs:
        k = "%s:%s" % (kind, t)
        if k in P:
            continue
        r = upload(fn, s, t, title)
        P[k] = r["id"]
        save()
        log("завели", k, r["id"])

    # 2. Видео EN→RU: загрузка кусками, распознавание.
    if "video:RU" not in P:
        f = IN / "zero-gravity-coffee.mp4"
        size = f.stat().st_size
        st = req("POST", "/api/media/upload", {"name": f.name, "size": size, "src": "EN", "tgt": "RU",
                                                "title": "Лендинг · NASA ScienceCasts (PD)"})
        tok = st["token"]
        data, off, ch = f.read_bytes(), int(st.get("received") or 0), 8 * 1024 * 1024 - 1024
        while off < size:
            r = req("POST", "/api/media/upload/%s/chunk?offset=%d" % (tok, off), raw=data[off:off + ch])
            off = r["received"]
        r = req("POST", "/api/media/upload/%s/finish" % tok, {})
        P["video:RU"] = r["id"]
        save()
        log("видео: проект", r["id"], "задача", r.get("jobId"))

    # 3. Разбор (картинки, распознавание речи) → полный прогон.
    for k, pid in list(P.items()):
        wait_idle(pid, k)
    for k, pid in list(P.items()):
        if k.startswith("vsub:"):
            continue
        run_full(pid, k)

    # 4. Субтитры видео EN→UZ/ZH/AR: те же строки-фразы и те же времена.
    vid = P["video:RU"]
    wait_idle(vid, "video:RU")
    pr = project(vid)
    ct = pr.get("cueTimes") or {}
    rows = [s for s in pr["segments"] if str(s["id"]) in ct]
    rows.sort(key=lambda s: ct[str(s["id"])][0])
    ST["videoRows"] = [{"id": s["id"], "t": ct[str(s["id"])], "src": s["source"]} for s in rows]
    save()

    def ts(x):
        ms = int(round(float(x) * 1000))
        return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
    srt = "".join("%d\n%s --> %s\n%s\n\n" % (i + 1, ts(r["t"][0]), ts(r["t"][1]), r["src"])
                  for i, r in enumerate(ST["videoRows"]))
    (IN / "zero-gravity-coffee.en.srt").write_text(srt, encoding="utf-8")
    for t in ("UZ", "ZH", "AR"):
        k = "vsub:" + t
        if k not in P:
            r = upload("zero-gravity-coffee.en.srt", "EN", t, "Лендинг · NASA ScienceCasts, субтитры (PD)")
            P[k] = r["id"]
            save()
            log("завели", k, r["id"])
        wait_idle(P[k], k)
        run_full(P[k], k)

    # 5. Ждём все прогоны.
    for k, pid in P.items():
        wait_idle(pid, k, limit=3600)

    # 6. Выгрузка.
    res = {"projects": P}
    for k, pid in P.items():
        pr = project(pid)
        res[k] = [{"id": s["id"], "src": s.get("source"), "tgt": s.get("target"), "status": s.get("status"),
                   "kind": s.get("kind"), "origin": s.get("origin")} for s in pr["segments"]]
        if pr.get("cueTimes"):
            res[k + ":cues"] = pr["cueTimes"]
    (OUT / "segments.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, pid in P.items():
        fmt = "pdf" if k.startswith("paper") else "original" if k.startswith("sign") else None
        if not fmt:
            continue
        e = req("POST", "/api/projects/%d/export" % pid, {"format": fmt, "source": False}, timeout=900)
        if not e.get("ok"):
            log("! выгрузка", k, e.get("error"))
            continue
        b = req("GET", e["url"], timeout=900)
        ext = e["file"].rsplit(".", 1)[-1]
        (OUT / ("%s.%s" % (k.replace(":", "-"), ext))).write_bytes(b)
        log("выгрузка", k, e["file"], len(b), e.get("stats"))
    log("готово", OUT)


main()
