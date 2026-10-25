"""Случаи проверки перед выдачей — инструмент агента-разработчика (ТЗ, этап 4).

Сервер пишет случай на каждое место, которое проверка после кругов правок
не решила (`main._prepress_cases_write`): файл с кодом дефекта, признаками
места и версией кода плюс вырезка «оригинал | итог». Порядок разбора —
docs/rules/export-review.md, раздел «Случаи проверки»: свести в виды →
правило в код + тест → фото-бенч, corpus_offline и эталоны не хуже → выкат.

    python tools/prepress_cases.py list [--all]
    python tools/prepress_cases.py pull DIR            # json и вырезки неразобранных — в DIR
    python tools/prepress_cases.py done TENANT PID N --rule Ю8 [--note ТЕКСТ]
    python tools/prepress_cases.py wont TENANT PID N [--note ТЕКСТ]

Сервер — ssh-алиас `beget` (MEDCAT_SSH). Вырезки — данные клиента (срок
30 суток, политика п. 6.2.3): DIR держать вне репозитория и удалить после
разбора.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HOST = os.environ.get("MEDCAT_SSH", "beget")
ROOT = os.environ.get("MEDCAT_CASES", "/opt/med-translation/backend/data/sources/prepress_cases")
SLUG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def ssh(cmd: str, data: "bytes | None" = None) -> bytes:
    return subprocess.run(["ssh", HOST, cmd], input=data, capture_output=True, check=True).stdout


def cases(all_: bool = False) -> list:
    py = ("import json,glob\n"
          "out=[]\n"
          "for f in sorted(glob.glob(%r+'/*/*/*.json')):\n"
          "    try: r=json.load(open(f,encoding='utf-8'))\n"
          "    except Exception: continue\n"
          "    r['_dir']=f.rsplit('/',3)[1]; out.append(r)\n"
          "print(json.dumps(out,ensure_ascii=False))\n") % ROOT
    got = json.loads(ssh("python3 -c %s" % shlex.quote(py)) or b"[]")
    return got if all_ else [r for r in got if r.get("status", "open") == "open"]


def mark(tenant: str, pid: int, n: int, status: str, rule: str, note: str) -> None:
    if not SLUG.match(tenant):
        sys.exit("неверная организация")
    f = "%s/%s/%d/%d.json" % (ROOT, tenant, int(pid), int(n))
    py = ("import json,os,datetime\n"
          "f=%r\nr=json.load(open(f,encoding='utf-8'))\n"
          "r.update(status=%r,rule=%r,note=%r,doneAt=datetime.datetime.now().strftime('%%Y-%%m-%%d %%H:%%M'))\n"
          "open(f+'.tmp','w',encoding='utf-8').write(json.dumps(r,ensure_ascii=False)); os.replace(f+'.tmp',f)\n"
          "print('ok')\n") % (f, status, rule[:40], note[:2000])
    print(ssh("python3 -c %s" % shlex.quote(py)).decode().strip())


def main_():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("list")
    a.add_argument("--all", action="store_true")
    a.add_argument("--count", action="store_true", help="только число неразобранных (для раннера)")
    a = sub.add_parser("pull")
    a.add_argument("dir")
    for c in ("done", "wont"):
        a = sub.add_parser(c)
        a.add_argument("tenant")
        a.add_argument("pid", type=int)
        a.add_argument("n", type=int)
        a.add_argument("--rule", default="")
        a.add_argument("--note", default="")
    a = ap.parse_args()
    if a.cmd == "list" and a.count:
        print(len(cases(a.all)))
    elif a.cmd == "list":
        rows = cases(a.all)
        by = {}
        for r in rows:
            by[r.get("code")] = by.get(r.get("code"), 0) + 1
            print("%-10s #%-5s %-3s стр.%-3s %-10s %-6s %s %s" % (r["_dir"], r.get("project"), r.get("n"),
                  r.get("page"), r.get("code"), r.get("kind"), r.get("pair"), r.get("status", "open")))
        print("всего:", len(rows), by)
    elif a.cmd == "pull":
        d = Path(a.dir)
        d.mkdir(parents=True, exist_ok=True)
        for r in cases():
            stem = "%s_%s_%s" % (r["_dir"], r.get("project"), r.get("n"))
            (d / (stem + ".json")).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            img = ssh("cat %s" % shlex.quote("%s/%s/%d/%d.jpg" % (ROOT, r["_dir"], int(r["project"]), int(r["n"]))))
            (d / (stem + ".jpg")).write_bytes(img)
        print("в", d)
    else:
        mark(a.tenant, a.pid, a.n, a.cmd, a.rule, a.note)


if __name__ == "__main__":
    main_()
