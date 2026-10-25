# -*- coding: utf-8 -*-
"""Рубежи автоматического выката правил (раздел Ы7, tools/auto_rules/guard.py):
решение «можно выкатывать» принимает код, а не модель — его и проверяем на
временном git-репозитории.

    python tests/test_auto_rules.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
GUARD = str(Path("tools/auto_rules/guard.py").resolve())
FAILS = []


def check(name, ok, info=""):
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else "  " + str(info)[:300]))
    if not ok:
        FAILS.append(name)


repo = Path(tempfile.mkdtemp(prefix="ar_"))


def g(*a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def w(path, text):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def guard(*a):
    r = subprocess.run([sys.executable, GUARD, *a], cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode, (r.stdout + r.stderr).strip()


g("init", "-q")
g("config", "user.email", "t@t")
g("config", "user.name", "t")
w("backend/main.py", "x = 1\n_PAID = []\n")
w("tests/test_a.py", "check(1)\ncheck(2)\n")
w("docs/rules/pdf-reading.md", "# rules\n")
g("add", "-A")
g("commit", "-qm", "base")
BASE = g("rev-parse", "HEAD").strip()


def head_with(files, delete=()):
    g("checkout", "-q", BASE)
    g("checkout", "-q", "-B", "h%d" % int(time.time() * 1000))
    for p, t in files.items():
        w(p, t)
    for p in delete:
        (repo / p).unlink()
    g("add", "-A")
    g("commit", "-qm", "head")
    return g("rev-parse", "HEAD").strip()


print("=== дифф ===")
ok_head = head_with({"backend/main.py": "x = 2\n_PAID = []\n", "tests/test_b.py": "check(1)\n",
                     "docs/rules/pdf-reading.md": "# rules\n## Щ1\n"})
rc, out = guard("diff", BASE, ok_head)
check("правило + тест + справочник — можно", rc == 0, out)
h = head_with({"backend/main.py": "x = 2\n", "tests/test_b.py": "check(1)\n",
               "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("правка строки с деньгами (_PAID) — нельзя", rc == 1 and "деньги" in out, out)
h = head_with({"tools/auto_rules/guard.py": "pass\n", "tests/test_b.py": "check(1)\n",
               "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("правка самого раннера — нельзя", rc == 1 and "запретный" in out, out)
h = head_with({"tests/test_a.py": "check(1)\n", "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("проверок в тесте стало меньше — нельзя", rc == 1 and "меньше" in out, out)
h = head_with({"backend/x.py": "y = 1\n", "docs/rules/pdf-reading.md": "# r\n## Щ1\n"},
              delete=("tests/test_a.py",))
rc, out = guard("diff", BASE, h)
check("удалённый тест — нельзя", rc == 1 and "удалён" in out, out)
h = head_with({"backend/x.py": "y = 1\n", "tests/test_b.py": "check(1)\n"})
rc, out = guard("diff", BASE, h)
check("без записи в справочник — нельзя", rc == 1 and "pdf-reading" in out, out)
h = head_with({"deploy/medcat.service": "x\n", "tests/test_b.py": "check(1)\n",
               "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("правка выката — нельзя", rc == 1, out)
h = head_with({"backend/main.py": "x = 2\n_PAID = []\n" + "y = 1\n" * 1600, "tests/test_b.py": "check(1)\n",
               "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("слишком большой дифф — нельзя", rc == 1 and "большой" in out, out)
h = head_with({"secret.txt": "x\n", "tests/test_b.py": "check(1)\n", "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("путь вне белого списка — нельзя", rc == 1 and "белого" in out, out)

print("=== отчёт агента ===")
res = repo / "result.json"
good = {"status": "ready", "rules": [{"id": "Щ1"}], "cases": [],
        "critics": {k: {"verdict": "ok"} for k in ("designer", "translator", "code")},
        "regression": {"ok": True}}
res.write_text(json.dumps(good), encoding="utf-8")
check("три критика ok и регрессия — можно", guard("result", str(res))[0] == 0)
bad = dict(good, critics=dict(good["critics"], translator={"verdict": "fix: калька"}))
res.write_text(json.dumps(bad), encoding="utf-8")
rc, out = guard("result", str(res))
check("критик не согласен — нельзя", rc == 1 and "translator" in out, out)
res.write_text(json.dumps(dict(good, regression={"ok": False})), encoding="utf-8")
check("регрессия не подтверждена — нельзя", guard("result", str(res))[0] == 1)
res.write_text("{", encoding="utf-8")
check("битый отчёт — нельзя", guard("result", str(res))[0] == 1)

print("=== потолок выкатов в сутки ===")
st = repo / "state"
check("выкатов не было — можно", guard("quota", str(st))[0] == 0)
guard("note", str(st), "a1", "a0")
guard("note", str(st), "a2", "a1")
rc, out = guard("quota", str(st))
check("два выката сегодня — третий нельзя", rc == 1, out)

print("=== раннер и выкат: устройство ===")
run_sh = Path("tools/auto_rules/run.sh").read_text(encoding="utf-8")
dep = Path("tools/auto_rules/deploy.sh").read_text(encoding="utf-8")
check("агенту запрещены push, ssh и reset", all(x in run_sh for x in ('"Bash(git push*)"', '"Bash(ssh *)"',
                                                                         '"Bash(git reset*)"')))
check("выключатель OFF и замки на машине и на сервере",
      "$STATE/OFF" in run_sh and 'mkdir "$STATE/lock"' in run_sh and ".medcat-auto-rules.lock" in run_sh)
push_at = run_sh.index("git push -q origin")
check("рубежи кода — до пуша", run_sh.index("guard.py result") < push_at and run_sh.index("guard.py diff") < push_at
      and run_sh.index("gates.sh") < push_at)
check("откат сервера ведёт к revert в main", "git revert" in run_sh and "rolledback" in run_sh)
check("выкат: эталоны до и после, окно наблюдения, откат",
      "fidelity_report" in dep and "AUTO_RULES_WATCH_S" in dep and "rollback" in dep and "git reset -q --hard $PREV" in dep)
# На Windows «bash» из Python — это WSL; берём Git Bash, нет его — пропуск.
BASH = "bash"
if os.name == "nt":
    BASH = next((b for b in ("C:/Program Files/Git/bin/bash.exe", "C:/Program Files/Git/usr/bin/bash.exe")
                 if Path(b).exists()), None)
for f in ("run.sh", "deploy.sh", "gates.sh"):
    if BASH is None:
        print("  ПРОПУСК синтаксис %s: нет bash" % f)
        continue
    r = subprocess.run([BASH, "-n", "tools/auto_rules/" + f], capture_output=True)
    check("синтаксис %s" % f, r.returncode == 0, r.stderr)

print()
if FAILS:
    print("ПРОВАЛЕНО: %d — %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОШЛИ")
