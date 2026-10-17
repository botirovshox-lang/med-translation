"""Субтитры новых роликов /start/ — через боевую систему (лендинг, 17.10.2026).

Английские титры NASA (фраза на строку, время от начала обрезанного ролика)
→ проекты .srt EN→RU/UZ/ZH/KK/AR, плюс кофе EN→KK (казахских субтитров кофе
прежний прогон не делал). Полный прогон с параметрами, которые предлагает сам
сервер. ПЛАТНО (центы). Запуск: bash tools/prod_run.sh tools/landing_video_subs.py
Повторный запуск продолжает с места: /root/landing-media/state-vsub2.json.
Итог — /root/landing-media/out/vsub2.json и строка VSUB2= в выводе.
"""
import json, os, re, sys, time, urllib.request, urllib.parse, uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path("/root/landing-media")
IN, OUT = ROOT / "in", ROOT / "out"
OUT.mkdir(parents=True, exist_ok=True)
ST_PATH = ROOT / "state-vsub2.json"
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



CLIPS = {
 "vision-in-space": {
  "cues": [
   [
    0.2,
    6.7
   ],
   [
    6.8,
    11.85
   ],
   [
    11.95,
    19.3
   ],
   [
    19.4,
    25.8
   ]
  ],
  "en": [
   "Even during a trip as short as two weeks, vision changes occur for about a third of American astronauts.",
   "When the trip is longer — say, four to six months — that figure may double.",
   "But before potential solutions can be proposed, scientists first have to understand what's causing these changes.",
   "On Earth, gravity forces a body's natural blood volume downward, below the waist."
  ]
 },
 "tomatoes-in-orbit": {
  "cues": [
   [
    0.1,
    5.95
   ],
   [
    6.0,
    7.45
   ],
   [
    7.5,
    11.45
   ],
   [
    11.55,
    15.95
   ],
   [
    16.05,
    19.5
   ]
  ],
  "en": [
   "The very microgravity we're trying to study up there can make experiments really difficult, for a bunch of different reasons.",
   "First of all, stuff floats.",
   "So losing things on the ISS is a very real possibility.",
   "For example, there was a set of tomatoes harvested in 2022.",
   "We put it in a bag, it floated away, and we couldn't find it for eight months."
  ]
 }
}


SRT_ROW = "%d\n%s --> %s\n%s\n\n"


def ts(x):
    ms = int(round(float(x) * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def main():
    global TOKEN
    TOKEN = req("POST", "/api/auth/login", {"login": "admin", "password": env_pw()})["token"]
    P = ST.setdefault("p", {})
    jobs = []
    for name, c in CLIPS.items():
        fn = name + ".en.srt"
        (IN / fn).write_text("".join(SRT_ROW % (i + 1, ts(a), ts(b), t)
                                     for i, ((a, b), t) in enumerate(zip(c["cues"], c["en"]))), encoding="utf-8")
        jobs += [(name, fn, t) for t in ("RU", "UZ", "ZH", "KK", "AR")]
    jobs.append(("zero-gravity-coffee", "zero-gravity-coffee.en.srt", "KK"))
    for name, fn, t in jobs:
        k = "%s:%s" % (name, t)
        if k not in P:
            try:
                r = upload(fn, "EN", t, "Лендинг · NASA, субтитры (PD) · " + name)
            except RuntimeError as e:
                # Тот же файл на ту же пару уже переведён — берём готовый проект.
                m = re.search(r'"project":\{"id":(\d+)', str(e))
                if not m:
                    raise
                r = {"id": int(m.group(1))}
                ST["full:%d" % r["id"]] = True
            P[k] = r["id"]
            save()
            log("завели", k, r["id"])
    for k, pid in P.items():
        wait_idle(pid, k)
        run_full(pid, k)
    for k, pid in P.items():
        wait_idle(pid, k, limit=3600)
    res = {}
    for k, pid in P.items():
        pr = project(pid)
        ct = pr.get("cueTimes") or {}
        rows = [s for s in pr["segments"] if str(s["id"]) in ct]
        rows.sort(key=lambda s: ct[str(s["id"])][0])
        res[k] = {"pid": pid, "rows": [{"t": ct[str(s["id"])], "src": s.get("source"), "tgt": s.get("target"),
                                        "status": s.get("status")} for s in rows]}
    (OUT / "vsub2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("VSUB2=" + json.dumps(res, ensure_ascii=False), flush=True)
    log("готово")


main()
