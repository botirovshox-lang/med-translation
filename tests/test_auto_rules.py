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

h = head_with({"tests/test_b.py": "check(1)\n", "docs/rules/pdf-reading.md": "# r\n## Щ1\n"},
              delete=())
g("checkout", "-q", BASE)
g("checkout", "-q", "-B", "ren")
g("mv", "tests/test_a.py", "tests/test_moved.py")
w("docs/rules/pdf-reading.md", "# r\n## Щ1\n")
w("tests/test_moved.py", "check(1)\ncheck(2)\n")
g("add", "-A")
g("commit", "-qm", "rename")
rc, out = guard("diff", BASE, g("rev-parse", "HEAD").strip())
check("переименование теста видно как удаление — нельзя", rc == 1 and "удалён" in out, out)
h = head_with({"tools/fidelity_report.py": "print('ok')\n", "tests/test_b.py": "check(1)\n",
               "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("подмена инструмента эталонов — нельзя", rc == 1 and "запретный" in out, out)
h = head_with({"backend/main.py": "x = 2\n_PAID = []\n@app.get('/api/x')\ndef x(): pass\n",
               "tests/test_b.py": "check(1)\n", "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("новая дверь в API — нельзя", rc == 1 and "дверь" in out, out)

h = head_with({"backend/extra.py": "router = APIRouter()\n@router.get('/api/y')\ndef y(): pass\n",
               "tests/test_b.py": "check(1)\n", "docs/rules/pdf-reading.md": "# r\n## Щ1\n"})
rc, out = guard("diff", BASE, h)
check("дверь через APIRouter в другом модуле — тоже нельзя", rc == 1 and "дверь" in out, out)
check("пропавший эталон считается предупреждением",
      "not_painted" in Path("tools/fidelity_report.py").read_text(encoding="utf-8").split("if as_json:")[0]
      and "print(" in Path("tools/fidelity_report.py").read_text(encoding="utf-8").split("not_painted")[2])

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

print("=== потолок запусков и попыток ===")
st2 = repo / "state2"
for _i in range(4):
    guard("runs", str(st2))
rc, out = guard("runs", str(st2))
check("пятый запуск агента за сутки — нельзя", rc == 1 and "запусков" in out, out)
data = repo / "data"
(data / "cases").mkdir(parents=True)
(data / "cases" / "o_5_1.json").write_text(json.dumps({"_dir": "o", "project": 5, "n": 1}), encoding="utf-8")
tools_fake = repo / "tf"
(tools_fake / "tools").mkdir(parents=True)
marks = repo / "marks.txt"
(tools_fake / "tools" / "prepress_cases.py").write_text(
    "import sys\nopen(%r, 'a', encoding='utf-8').write(' '.join(sys.argv[1:]) + chr(10))\n" % str(marks),
    encoding="utf-8")
for _i in range(3):
    guard("attempts", str(st2), str(data), str(tools_fake))
    if not (data / "cases" / "o_5_1.json").exists():
        break
    (data / "cases" / "o_5_1.json").write_text(json.dumps({"_dir": "o", "project": 5, "n": 1}), encoding="utf-8")
txt = marks.read_text(encoding="utf-8") if marks.exists() else ""
check("после двух попыток случай — человеку (wont + held)", "wont o 5 1" in txt and "held" in txt, txt)

print("=== разбор вывода эталонов ===")


def fid(text):
    r = subprocess.run([sys.executable, GUARD, "fid"], input=text, capture_output=True, text=True,
                       encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode, r.stdout.strip()


check("предупреждения считаются штуками",
      fid("s1 uz {'a': 1} outside=0 warn=['x', 'y']\ns2 ru {} outside=1 warn=[]\n") == (0, "2"))
check("упавший замер — ERR, а не 0", fid("Traceback (most recent call last):\n") == (1, "ERR"))

print("=== замок ===")
BASH_ = "bash"
if os.name == "nt":
    BASH_ = next((b for b in ("C:/Program Files/Git/bin/bash.exe",) if Path(b).exists()), None)
if BASH_:
    lk = str(repo / "lk")
    L = str(Path("tools/auto_rules/lock.sh").resolve())
    a1 = subprocess.run([BASH_, L, "acquire", lk]).returncode
    a2 = subprocess.run([BASH_, L, "acquire", lk]).returncode
    subprocess.run([BASH_, L, "release", lk])
    a3 = subprocess.run([BASH_, L, "acquire", lk]).returncode
    check("свежий замок второму не даётся, после снятия — даётся", (a1, a2, a3) == (0, 1, 0), (a1, a2, a3))
    os.utime(lk, (time.time() - 9 * 3600, time.time() - 9 * 3600))
    check("брошенный замок старше 8 ч снимается", subprocess.run([BASH_, L, "acquire", lk]).returncode == 0)

print("=== раннер и выкат: устройство ===")
run_src = Path("tools/auto_rules/run.sh").read_text(encoding="utf-8")
check("проверяет и выкатывает доверенный код из origin/main, а не дерево агента",
      "AUTO_RULES_TRUSTED" in run_src and 'git -C "$REPO" archive' in run_src and '"$G/guard.py"' in run_src
      and '"$G/deploy.sh"' in run_src)
check("незакоммиченное в дереве агента — отказ", "git status --porcelain" in run_src)
check("агент не может пушить из своего дерева", "pushurl" in run_src)
check("любой непринятый выкат — revert main и выключение до человека",
      "stop_all" in run_src and run_src.count("git revert") == 1 and "$DRC -ne 0" in run_src)
dep_src = Path("tools/auto_rules/deploy.sh").read_text(encoding="utf-8")
check("на сервере сторож откатывает неподтверждённый выкат", "systemd-run" in dep_src and "--on-active" in dep_src)
check("сторож переживает всё окно проверки (окно + замер + запас)", "WATCH + FID_S" in dep_src
      and 'timeout "$FID_S"' in dep_src)
check("старые доверенные копии не стираются у идущего разбора", "-mtime +1" in run_src
      and 'rm -rf "$STATE"/trusted-*' not in run_src)
check("конфиг репозитория владельца не трогается", "worktreeConfig" not in run_src)
check("упавший замер эталонов ДО — выката нет, ПОСЛЕ — откат",
      "F0=$(fid) ||" in dep_src and "F1=$(fid) || rollback" in dep_src)
run_sh = Path("tools/auto_rules/run.sh").read_text(encoding="utf-8")
dep = Path("tools/auto_rules/deploy.sh").read_text(encoding="utf-8")
check("агенту запрещены push, ssh и reset", all(x in run_sh for x in ('"Bash(git push*)"', '"Bash(ssh *)"',
                                                                         '"Bash(git reset*)"')))
check("выключатель OFF и замки на машине и на сервере",
      "$STATE/OFF" in run_sh and 'lock.sh" acquire "$STATE/lock"' in run_sh and ".medcat-auto-rules.lock" in run_sh)
push_at = run_sh.index("git push -q \"$ORIGIN\"")
check("рубежи кода — до пуша", run_sh.index('guard.py" result') < push_at and run_sh.index('guard.py" diff') < push_at
      and run_sh.index("gates.sh") < push_at)
check("откат сервера ведёт к revert в main", "git revert" in run_sh and "failed$DRC" in run_sh)
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
