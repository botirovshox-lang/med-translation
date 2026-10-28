"""Слайд «Меню закусочной» в карусели «Фото» на главной — через боевую систему.

Заменил «Табличку в музее» (28.10.2026, просьба владельца: пример сложнее
вёрсткой и с китайского). Исходник — настенное меню шанхайской закусочной
鲜得来: пять колонок, плашки-заголовки, строки-плашки с количеством и ценой.
Фото: Shwangtianyuan, CC BY-SA 4.0,
https://commons.wikimedia.org/wiki/File:Menu_of_Xiandelai_South_Yunnan_Road-20240106.jpg
(обрезано по доске меню). Изменённая картинка идёт под той же лицензией —
подпись об этом стоит на самой странице.

Запуск: положить вырезку в /root/landing-media/in/menu-zh.jpg, затем
`bash tools/prod_run.sh tools/landing_menu_zh.py`. Платные прогоны (центы):
чтение надписей зрячей моделью, перевод и проверки на EN, RU, UZ.
Повторный запуск продолжает с места (/root/landing-media/menu-state.json).
Результат — /root/landing-media/out/menu/menu-<язык>.<ext>; в webp 1000 px
его переводит локально тот же приём, что у прочих слайдов.
"""
import json, time, urllib.request, urllib.error, uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path("/root/landing-media")
SRC_FILE = ROOT / "in" / "menu-zh.jpg"
OUT = ROOT / "out" / "menu"
OUT.mkdir(parents=True, exist_ok=True)
ST_PATH = ROOT / "menu-state.json"
ST = json.loads(ST_PATH.read_text()) if ST_PATH.exists() else {}
TITLE = "Лендинг · фото: меню закусочной 鲜得来 (CC BY-SA 4.0)"
TARGETS = ("EN", "RU", "UZ")
TOKEN = None


def save():
    ST_PATH.write_text(json.dumps(ST, ensure_ascii=False, indent=1))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def env_pw():
    for line in Path("/etc/medcat/env").read_text().splitlines():
        if line.startswith("APP_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("нет APP_PASSWORD")


def req(method, path, body=None, raw=None, ctype=None, timeout=600):
    h = {"Authorization": "Bearer " + TOKEN} if TOKEN else {}
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
            return json.loads(b) if "json" in resp.headers.get("Content-Type", "") else b
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s -> %s %s" % (method, path, e.code, e.read()[:500].decode("utf-8", "replace")))


def upload(src, tgt, folder=None):
    bnd = uuid.uuid4().hex
    fields = [("src", src), ("tgt", tgt), ("title", TITLE)]
    if folder is not None:
        fields.append(("folder", str(folder)))
    parts = [("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bnd, k, v)).encode()
             for k, v in fields]
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: image/jpeg\r\n\r\n" % (bnd, SRC_FILE.name)).encode()
                 + SRC_FILE.read_bytes() + b"\r\n")
    parts.append(("--%s--\r\n" % bnd).encode())
    return req("POST", "/api/projects/upload", raw=b"".join(parts),
               ctype="multipart/form-data; boundary=" + bnd)


def project(pid):
    return req("GET", "/api/projects/%d" % pid)


def wait_idle(pid, label, limit=3600):
    t0 = time.time()
    while time.time() - t0 < limit:
        j = req("GET", "/api/jobs?project=%d&limit=10" % pid)
        if not j["active"]:
            for x in j["jobs"][:3]:
                if x.get("status") == "error":
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
    ids = [s["id"] for s in project(pid)["segments"]]
    if not ids:
        log("! %s: нет строк — надписи не прочитаны" % label)
        return
    an = req("GET", "/api/projects/%d/analysis" % pid)
    params = dict(((an.get("turnkey") or {}).get("params")) or {})
    params["auto_terms"] = False
    log("%s: прогон по %d строкам" % (label, len(ids)))
    r = req("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": ids, "params": params})
    log("  задача", (r.get("job") or r).get("id"))
    ST[key] = True
    save()


def main():
    global TOKEN
    TOKEN = req("POST", "/api/auth/login", {"login": "admin", "password": env_pw()})["token"]
    P = ST.setdefault("p", {})
    for t in TARGETS:
        if t in P:
            continue
        home = next(iter(P.values()), None)
        r = upload("ZH", t, folder=home)
        P[t] = r["id"]
        save()
        log("завели", t, r["id"], r.get("imagesSkipped") or "")
        # Первый файл читает надписи сам; остальные берут прочитанное у соседа
        # (`_image_borrow`), поэтому ждём чтения ДО следующей загрузки.
        wait_idle(r["id"], t)
    for t, pid in P.items():
        wait_idle(pid, t)
    for t, pid in P.items():
        run_full(pid, t)
    cost = 0.0
    for t, pid in P.items():
        for x in wait_idle(pid, t)[:4]:
            c = ((x.get("usage") or {}).get("cost")) or 0
            cost += c
            log("  %s: задача %s %s %s $%.4f" % (t, x["id"], x.get("kind"), x.get("status"), c))
    log("расход по задачам: $%.3f" % cost)
    res = {"projects": P}
    for t, pid in P.items():
        pr = project(pid)
        res[t] = [{"id": s["id"], "src": s.get("source"), "tgt": s.get("target"),
                   "status": s.get("status")} for s in pr["segments"]]
    (OUT / "segments.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for t, pid in P.items():
        e = req("POST", "/api/projects/%d/export" % pid, {"format": "original", "source": False}, timeout=900)
        if e.get("pending"):
            log("  … %s: выгрузка ждёт проверки" % t)
            for _ in range(80):
                time.sleep(15)
                e = req("POST", "/api/projects/%d/export" % pid, {"format": "original", "source": False}, timeout=900)
                if not e.get("pending"):
                    break
        if not e.get("ok"):
            log("! выгрузка", t, e.get("error"))
            continue
        b = req("GET", e["url"], timeout=900)
        ext = e["file"].rsplit(".", 1)[-1]
        (OUT / ("menu-%s.%s" % (t.lower(), ext))).write_bytes(b)
        log("выгрузка", t, e["file"], len(b), e.get("stats"))
    log("готово", OUT)


main()
