"""Уборка проектов плиток лендинга (разово, 19.10.2026).

`tools/landing_tiles.py` клал каждый язык в СВОЮ папку и каждым заходом
(ROUND) заводил новые проекты: на сервере лежало 34 проекта на три картинки.
Картинки лендинга давно в репозитории (`landing/media`), выгрузки — в
/root/landing-media/out, поэтому:

  1. проекты ПРЕЖНИХ заходов удаляются — только те, что названы в картах
     состояния заходов и чей заголовок начинается с «Лендинг · плитка»;
  2. проекты последнего захода раскладываются по папке на картинку
     (`POST /api/projects/{pid}/move`), первая по номеру — дом.

Запуск: `bash tools/prod_run.sh tools/landing_tiles_tidy.py` (копия базы до).
Повторный запуск безопасен: удалённых нет — 404 пропускается, разложенные
переносятся «в ту же папку» без изменений.
"""
import json, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path("/root/landing-media")
TITLE = "Лендинг · плитка"


def env_pw():
    for line in Path("/etc/medcat/env").read_text().splitlines():
        if line.startswith("APP_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("нет APP_PASSWORD")


TOKEN = None


def req(method, path, body=None):
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = "Bearer " + TOKEN
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                               headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=600) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read()[:300].decode("utf-8", "replace")}


def state(n):
    p = ROOT / ("tiles-state-%d.json" % n if n > 1 else "tiles-state.json")
    return json.loads(p.read_text()).get("p", {}) if p.exists() else {}


TOKEN = req("POST", "/api/auth/login", {"login": "admin", "password": env_pw()})[1]["token"]
rounds = {n: state(n) for n in (1, 2, 3)}
# Действующий проект на ключ «вид:язык» — из ПОСЛЕДНЕГО захода, где он есть.
live = {}
for n in sorted(rounds):
    live.update(rounds[n])
keep = set(live.values())
old = sorted({pid for p in rounds.values() for pid in p.values()} - keep)
print("действующие:", sorted(keep))
print("к удалению:", old)

for pid in old:
    code, pr = req("GET", "/api/projects/%d" % pid)
    if code == 404:
        print("  %d: уже нет" % pid)
        continue
    title = pr.get("title") or ""
    if not title.startswith(TITLE):
        print("  %d: заголовок «%s» — НЕ трогаю" % (pid, title))
        continue
    code, r = req("DELETE", "/api/projects/%d" % pid)
    print("  %d удалён: %s %s" % (pid, code, r.get("error") or ""))

for kind in ("book", "article", "scan"):
    pids = sorted(pid for k, pid in live.items() if k.split(":")[0] == kind)
    if len(pids) < 2:
        continue
    home = pids[0]
    for pid in pids[1:]:
        code, r = req("POST", "/api/projects/%d/move" % pid, {"folder": home})
        print("  %s: %d → папка %d: %s %s" % (kind, pid, home, code, r.get("error") or r))
print("готово")
