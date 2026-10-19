"""Плитки «Что переводим» на click.simpletranslate.me/start/ — через боевую систему.

Каждая плитка показывает картинку и кнопки языков; по нажатию картинка
«сканируется» и встаёт ТА ЖЕ картинка с переведённым текстом. Эти картинки —
выгрузка «в исходном виде» самой системы (чтение надписей → перевод →
проверки → перерисовка текста на картинке), без правок руками.

Запуск: положить исходники в /root/landing-media/in/tiles на сервере
(book.png — кусок разворота «Пёстрых рассказов» 1886 г., article.png — шапка
первой страницы статьи npj 2019, scan.jpg — кусок справки о подготовке ВСХВ
1940 г., Главархив Москвы, CC BY 4.0), затем
`bash tools/prod_run.sh tools/landing_tiles.py`. Это ПЛАТНЫЕ прогоны (центы).

Повторный запуск продолжает с места: номера проектов лежат
в /root/landing-media/tiles-state-<ROUND>.json. Результат —
/root/landing-media/out/tiles-<ROUND>. Новый заход (правила чтения поменялись,
исходник обрезан иначе) — поднять ROUND: прежние проекты остаются как есть.
Субтитры видео (vsub:KK) — только в первом заходе.
"""
import json, time, urllib.request, uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path("/root/landing-media")
ROUND = 3
# Что перечитывать в этом заходе (None — всё). Третий заход — только книга:
# правило С3 стало снимать перенос и через разрыв строки.
ONLY = ("book",)
IN = ROOT / "in" / "tiles"
OUT = ROOT / "out" / ("tiles-%d" % ROUND if ROUND > 1 else "tiles")
OUT.mkdir(parents=True, exist_ok=True)
ST_PATH = ROOT / ("tiles-state-%d.json" % ROUND if ROUND > 1 else "tiles-state.json")
ST = json.loads(ST_PATH.read_text()) if ST_PATH.exists() else {}
SRT = ROOT / "in" / "zero-gravity-coffee.en.srt"


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


def upload(p, src, tgt, title, folder=None):
    """Один документ на несколько языков — файлы ОДНОЙ папки: первый язык
    заводит папку, остальные кладутся в неё (`folder`). Разложенные по своим
    папкам, они выглядели кучей одинаковых проектов, а надписи с картинок
    читались бы каждым файлом заново (`_image_borrow` берёт их у соседа)."""
    bnd = uuid.uuid4().hex
    parts = []
    fields = [("src", src), ("tgt", tgt), ("title", title)]
    if folder is not None:
        fields.append(("folder", str(folder)))
    for k, v in fields:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bnd, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (bnd, p.name)).encode()
                 + p.read_bytes() + b"\r\n")
    parts.append(("--%s--\r\n" % bnd).encode())
    return req("POST", "/api/projects/upload", raw=b"".join(parts),
               ctype="multipart/form-data; boundary=" + bnd)


def project(pid):
    return req("GET", "/api/projects/%d" % pid)


def wait_idle(pid, label, limit=2400):
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
    log("%s: прогон по %d строкам, шаги %s" % (label, len(ids), params.get("steps")))
    r = req("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": ids, "params": params})
    log("  задача", (r.get("job") or r).get("id"))
    ST[key] = True
    save()


def main():
    global TOKEN
    TOKEN = req("POST", "/api/auth/login", {"login": "admin", "password": env_pw()})["token"]
    P = ST.setdefault("p", {})

    jobs = [("book", "book.png", "RU", t, "Лендинг · плитка: Чехов, «Пёстрые рассказы» 1886")
            for t in ("EN", "UZ", "ZH", "KK", "AR")]
    jobs += [("article", "article.png", "EN", t, "Лендинг · плитка: npj Sci Learn 2019 (CC BY)")
             for t in ("UZ", "ZH", "KK", "AR")]
    jobs += [("scan", "scan.jpg", "RU", t, "Лендинг · плитка: справка ВСХВ 1940 (CC BY, Главархив)")
             for t in ("EN", "UZ", "ZH", "KK", "AR")]
    for kind, fn, s, t, title in jobs:
        if ONLY and kind not in ONLY:
            continue
        k = "%s:%s" % (kind, t)
        if k in P:
            continue
        home = next((P[x] for x in P if x.split(":")[0] == kind), None)
        r = upload(IN / fn, s, t, title, folder=home)
        P[k] = r["id"]
        save()
        log("завели", k, r["id"], r.get("imagesSkipped") or "")
    if ROUND == 1 and "vsub:KK" not in P:
        r = upload(SRT, "EN", "KK", "Лендинг · NASA ScienceCasts, субтитры (PD)")
        P["vsub:KK"] = r["id"]
        save()
        log("завели vsub:KK", r["id"])

    # Чтение надписей идёт задачей воркера само; ждём его и запускаем полный прогон.
    for k, pid in P.items():
        wait_idle(pid, k)
    for k, pid in P.items():
        run_full(pid, k)
    cost = 0.0
    for k, pid in P.items():
        for x in wait_idle(pid, k, limit=3600)[:4]:
            c = ((x.get("usage") or {}).get("cost")) or 0
            cost += c
            log("  %s: задача %s %s %s $%.4f" % (k, x["id"], x.get("kind"), x.get("status"), c))
    log("расход по задачам: $%.3f" % cost)

    res = {"projects": P}
    for k, pid in P.items():
        pr = project(pid)
        res[k] = [{"id": s["id"], "src": s.get("source"), "tgt": s.get("target"), "status": s.get("status"),
                   "kind": s.get("kind")} for s in pr["segments"]]
    (OUT / "segments.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, pid in P.items():
        if k.startswith("vsub:"):
            continue
        e = req("POST", "/api/projects/%d/export" % pid, {"format": "original", "source": False}, timeout=900)
        if not e.get("ok"):
            log("! выгрузка", k, e.get("error"))
            continue
        b = req("GET", e["url"], timeout=900)
        ext = e["file"].rsplit(".", 1)[-1]
        (OUT / ("%s.%s" % (k.replace(":", "-"), ext))).write_bytes(b)
        log("выгрузка", k, e["file"], len(b), e.get("stats"))
    log("готово", OUT)


main()
