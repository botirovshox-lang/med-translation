# -*- coding: utf-8 -*-
"""Пересборка сегментов проекта из его исходника (`tools/resegment_project.py`).

Проект загружен СТАРЫМИ правилами разбора PDF (без геометрии и без правок
границы страницы): «кон- В продаже на рынках…» — один сегмент, «вы-» склеено
с «ди них». Пересборка по нынешним правилам:
  1. сухой прогон называет числа и ничего не пишет;
  2. с файлом state.json запись без --offline — отказ (второй пишущий
     процесс рядом с сервисом затёр бы его запись); идущий прогон — отказ;
  3. запись: неизменившиеся сегменты сохраняют перевод, статус и проверки;
     изменившиеся — новые, пустые, прежний перевод в `prevTarget`;
     страницы не списываются, объём проекта прежний;
  4. откат — штатный откат замены файла;
  5. нет сохранённого оригинала — отказ с подсказкой `--file`, с файлом — идёт.
Ни одного вызова модели; файлы — во временном каталоге.
"""
import io, os, sys, json, tempfile
from pathlib import Path
os.environ["APP_PASSWORD"] = "reseg-pass-1"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
sys.path.insert(0, "tools")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main
import pdftext
import resegment_project as rs
from pdf_fixture import PDF
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main.STATE["folders"] = []
main.STATE["dicts"] = []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
TMP = Path(tempfile.mkdtemp(prefix="medcat-reseg-"))
main.SOURCE_DIR = TMP / "sources"
main.REIMPORT_DIR = TMP / "backups"
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
A = c.post("/api/auth/login", json={"login": "admin", "password": "reseg-pass-1"}).json()["token"]


def live(pid):
    return next(p for p in main.STATE["projects"] if p["id"] == pid)


print("=== 0. Проект, загруженный старыми правилами ===")
orig_clean, orig_fix = pdftext.clean, pdftext._plain_page_fixes
pdftext.clean = lambda pages, geom=None: orig_clean(pages)
pdftext._plain_page_fixes = lambda *a, **k: None
r = c.post("/api/projects/upload", headers=H(A), files={"file": ("book.pdf", PDF)},
           data={"title": "book", "src": "RU", "tgt": "UZ", "domain": "general"})
pdftext.clean, pdftext._plain_page_fixes = orig_clean, orig_fix
check(r.status_code == 200, "PDF загружен: %s" % r.status_code)
pid = r.json()["id"]
proj = live(pid)
for s in proj["segments"]:
    s["target"] = "UZ:" + s["source"][:40]
    s["status"] = "confirmed"
    s["qa"] = [{"kind": "numbers", "ok": True}]
old = json.loads(json.dumps(proj["segments"]))
check(any("кон- " in s["source"] for s in old) and any("выди них" in s["source"] for s in old),
      "старые правила: врезка в абзаце и переставленные строки")
pages_before = proj.get("pages")

print("=== 1. Сухой прогон ===")
res = rs.resegment(main, pid)
print("   ", {k: res[k] for k in ("kept", "changed", "new", "removed", "oldSegments", "newUnits")})
check(res["dryRun"] and res["kept"] > 0 and res["changed"] > 0, "числа названы: остаётся и меняется")
check(json.dumps(live(pid)["segments"], sort_keys=True) == json.dumps(old, sort_keys=True), "сухой прогон ничего не записал")

print("=== 2. Отказы ===")
try:
    rs.resegment(main, pid, apply=True)
    check(False, "state.json без --offline — отказ")
except rs.Refuse as e:
    check("offline" in str(e), "state.json без --offline — отказ: %s" % e)
main._JOBS[999001] = {"id": 999001, "project": pid, "kind": "translate", "status": "running"}
try:
    rs.resegment(main, pid, apply=True, offline=True)
    check(False, "идущий прогон — отказ")
except rs.Refuse as e:
    check("прогон" in str(e), "идущий прогон — отказ: %s" % e)
finally:
    main._JOBS.pop(999001, None)
check(json.dumps(live(pid)["segments"], sort_keys=True) == json.dumps(old, sort_keys=True), "после отказов ничего не записано")

print("=== 3. Запись ===")
calls = []
spy = lambda *a, **k: calls.append(a) or 0.0
main._pages_debit = spy
res = rs.resegment(main, pid, apply=True, offline=True)
p = live(pid)
segs = p["segments"]
by_src = {s["source"]: s for s in old}
kept = [s for s in segs if s["source"] in by_src and s["id"] == by_src[s["source"]]["id"]]
check(kept and all(s["target"] == by_src[s["source"]]["target"] and s["status"] == "confirmed"
                   and s.get("qa") == by_src[s["source"]]["qa"] for s in kept),
      "неизменившиеся (%d) — с переводом, статусом и проверками" % len(kept))
chg = [s for s in segs if s.get("prevTarget")]
check(chg and all(s["status"] == "new" and not s["target"] and s["prevTarget"].startswith("UZ:") for s in chg),
      "изменившиеся (%d) — новые, пустые, прежний перевод в prevTarget" % len(chg))
check(any("ниже 20 °С консистенцию" in s["source"] for s in segs)
      and any("взято немало высокоэффективных" in s["source"] for s in segs)
      and not any("кон- " in s["source"] or "выди них" in s["source"] for s in segs),
      "сегменты — по новым правилам")
glued = next(s for s in chg if "консистенцию" in s["source"])
check("кон-" in glued.get("prevSource", ""), "prevSource показывает, из чего был собран прежний перевод")
# Подсказка лежит у СВОЕЙ строки (по индексу плана, а не склейкой списков):
# прежний оригинал перекрывается с новым по словам, как и отбирал план.
check(all(len(rs._words(s["source"]) & rs._words(s["prevSource"]))
          >= rs.PREV_OVERLAP * min(len(rs._words(s["source"])), len(rs._words(s["prevSource"])))
          for s in chg), "каждая подсказка — у той строки, с которой перекрывается")
check(not any("prev_target" in s or "prev_source" in s for s in segs),
      "полей prev_target/prev_source нет — только имена ядра и карточки")
check(not any(s.get("retranslations") or s.get("mtDone") for s in chg),
      "у пересобранной строки счётчик перевода заново чистый: оригинал другой")
check(calls == [] and p.get("pages") == pages_before, "страницы не списывались, объём проекта прежний")
check((p.get("resegment") or {}).get("stamp") == res["stamp"] and (p.get("reimport") or {}).get("stamp") == res["stamp"],
      "отметка пересборки и копия для отката на проекте")
mp = main._load_source_map(pid)
check(mp and len({x[1] for x in mp["pairs"]}) == len(segs), "карта абзацев исходника — под новые сегменты")

print("=== 4. Откат ===")
r = c.post("/api/projects/%d/reimport/%s/undo" % (pid, res["stamp"]), headers=H(A))
check(r.status_code == 200, "откат штатным откатом замены: %s %s" % (r.status_code, r.text[:200]))
check([s["source"] for s in live(pid)["segments"]] == [s["source"] for s in old]
      and all(s["target"].startswith("UZ:") for s in live(pid)["segments"]), "откат вернул прежние сегменты с переводом")

print("=== 5. Исходник ===")
for f in main.SOURCE_DIR.glob("%d.orig.*" % pid):
    f.unlink()
try:
    rs.resegment(main, pid)
    check(False, "без оригинала — отказ")
except rs.Refuse as e:
    check("--file" in str(e), "без оригинала — отказ с подсказкой: %s" % e)
path = TMP / "book.pdf"
path.write_bytes(PDF)
res = rs.resegment(main, pid, file_arg=str(path))
check(res["dryRun"] and res["changed"] > 0 and res["file"] == str(path), "с --file — сухой прогон по названному файлу")

print()
if fail:
    print("FAILED: %d" % len(fail))
    for x in fail:
        print(" -", x)
    sys.exit(1)
print("ALL OK")
