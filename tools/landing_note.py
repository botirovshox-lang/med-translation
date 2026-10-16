"""Слайд «Конспект от руки» карусели «Фото» на /start/ — заново через систему.

Исходник — фото конспекта (у владельца сервиса проект 89, его организация).
Чужую организацию служебный вход не видит, и обходить изоляцию нельзя,
поэтому тот же файл заводится ОТДЕЛЬНЫМ проектом «Лендинг · …» в служебной
организации — как плитки лендинга (`tools/landing_tiles.py`). Чтение надписей
идёт само (промпт «переписывай, не правь», правило Ф8), затем полный прогон.
Это ПЛАТНЫЕ вызовы (центы).

    bash tools/prod_run.sh tools/landing_note.py

Повторный запуск продолжает с места (/root/landing-media/note-state.json).
Номер проекта потом вписать в `SLIDES["note"]` у `tools/landing_photo.py`.
"""
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SRC = Path("/opt/med-translation/backend/data/sources/89.orig.jpg")
ST_PATH = Path("/root/landing-media/note-state.json")
ST = json.loads(ST_PATH.read_text()) if ST_PATH.exists() else {}
TOKEN = None


def save():
    ST_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        data, h["Content-Type"] = raw, ctype
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read()
            return json.loads(b) if "json" in resp.headers.get("Content-Type", "") else b
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s -> %s %s" % (method, path, e.code, e.read()[:500].decode("utf-8", "replace")))


def upload(p, src, tgt, title):
    bnd = uuid.uuid4().hex
    parts = [("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bnd, k, v)).encode()
             for k, v in (("src", src), ("tgt", tgt), ("title", title))]
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"note.jpg\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % bnd).encode() + p.read_bytes() + b"\r\n")
    parts.append(("--%s--\r\n" % bnd).encode())
    return req("POST", "/api/projects/upload", raw=b"".join(parts),
               ctype="multipart/form-data; boundary=" + bnd)


def wait_idle(pid, label, limit=3600):
    t0 = time.time()
    while time.time() - t0 < limit:
        j = req("GET", "/api/jobs?project=%d&limit=10" % pid)
        if not j["active"]:
            return j["jobs"]
        a = j["active"][0]
        log("  … %s: %s %s %s/%s" % (label, a.get("kind"), a.get("status"), a.get("done"), a.get("total")))
        time.sleep(15)
    raise RuntimeError("не дождались: " + label)


TOKEN = req("POST", "/api/auth/login", {"login": "admin", "password": env_pw()})["token"]
if "pid" not in ST:
    r = upload(SRC, "RU", "EN", "Лендинг · Фото: конспект от руки (RU→EN)")
    ST["pid"] = r["id"]
    save()
    log("завели проект", r["id"], r.get("imagesSkipped") or "")
pid = ST["pid"]
for x in wait_idle(pid, "чтение")[:3]:
    log("  задача", x["id"], x.get("kind"), x.get("status"), x.get("error") or "", x.get("counters") or "")
pr = req("GET", "/api/projects/%d" % pid)
ids = [s["id"] for s in pr["segments"]]
log("строк после чтения:", len(ids))
for s in pr["segments"]:
    log("  SRC:", s.get("source"))
if not ids:
    raise SystemExit("надписи не прочитаны — прогон не запускаю")
if not ST.get("full"):
    an = req("GET", "/api/projects/%d/analysis" % pid)
    params = dict(((an.get("turnkey") or {}).get("params")) or {})
    params["auto_terms"] = False
    r = req("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": ids, "params": params})
    log("прогон", (r.get("job") or r).get("id"), "шаги", params.get("steps"))
    ST["full"] = True
    save()
cost = 0.0
for x in wait_idle(pid, "прогон")[:4]:
    c = ((x.get("usage") or {}).get("cost")) or 0
    cost += c
    log("  задача", x["id"], x.get("kind"), x.get("status"), "$%.4f" % c, x.get("error") or "")
log("расход: $%.4f" % cost)
pr = req("GET", "/api/projects/%d" % pid)
for s in pr["segments"]:
    log("  [%s] %s" % (s.get("status"), s.get("source")))
    log("     → %s" % s.get("target"))

# Оригинал, сверенный человеком по фото (правка оригинала строки с картинки,
# правило У5). Модель чтения и с промптом «переписывай, не правь» прочла
# три места правдоподобной заменой («гораздо проще», «особые секреции»,
# «в других организмах») и потеряла точку — для витрины так нельзя.
FIX = [
    "Бактериальная клетка обычно устроена наиболее просто по сравнению с клетками "
    "других живых организмов. Бактериальные клетки часто окружает капсула, которая "
    "служит защитой от внешней среды. Для многих свободноживущих бактерий характерно "
    "наличие жгутиков для передвижения, а также ворсинок.",
    "Для выведения веществ, в том числе факторов патогенности, в окружающую среду "
    "используются системы секреции. Клеточная стенка бактерий обычно содержит "
    "пептидогликан. По химическому составу клеточные мембраны бактерий гораздо "
    "разнообразнее мембран эукариотических клеток. В отличие от эукариот, бактерии "
    "не имеют ограниченного оболочкой ядра и, в большинстве случаев, каких-либо "
    "мембранных органелл. Вместе с тем у ряда бактерий имеются клеточные структуры, "
    "не имеющие аналогов в двух других доменах.",
]
if not ST.get("fixed"):
    segs = sorted(pr["segments"], key=lambda s: ((s.get("origin") or {}).get("block") or 0))
    for s, text in zip(segs, FIX):
        if (s.get("source") or "").strip() == text:
            continue
        r = req("POST", "/api/segments/%d/%d/source" % (pid, s["id"]), {"source": text, "force": True})
        log("  оригинал строки", s["id"], "исправлен:", (r.get("mode") or r.get("how") or r.get("ok")))
        # Перевод — заново: поправка оригинала прежний перевод оставляет.
        req("POST", "/api/segments/%d/%d/update" % (pid, s["id"]), {"target": "", "status": "new"})
    ST["fixed"] = True
    save()
    ids = [s["id"] for s in segs]
    an = req("GET", "/api/projects/%d/analysis" % pid)
    params = dict(((an.get("turnkey") or {}).get("params")) or {})
    params["auto_terms"] = False
    r = req("POST", "/api/projects/%d/jobs" % pid, {"kind": "full", "segment_ids": ids, "params": params})
    log("прогон по исправленному оригиналу", (r.get("job") or r).get("id"))
    for x in wait_idle(pid, "прогон 2")[:2]:
        log("  задача", x["id"], x.get("kind"), x.get("status"),
            "$%.4f" % (((x.get("usage") or {}).get("cost")) or 0), x.get("error") or "")
    pr = req("GET", "/api/projects/%d" % pid)
    for s in pr["segments"]:
        log("  [%s] %s" % (s.get("status"), s.get("source")))
        log("     → %s" % s.get("target"))
log("готово, проект", pid)
