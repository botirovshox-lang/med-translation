# -*- coding: utf-8 -*-
"""Детерминированные рубежи автоматического разбора случаев (раздел Ы7).

Агент-разработчик (Claude Code без человека, `run.sh`) пишет правило, тест
и запись в справочнике, критики-субагенты его проверяют — но решение «можно
выкатывать» принимает НЕ модель, а этот файл: судья LLM шумит (мировой опыт:
Judging the Judges, 2406.07791), и последний рубеж обязан быть повторяемым.

    python tools/auto_rules/guard.py diff BASE HEAD       # пути, размер, ослабленные тесты
    python tools/auto_rules/guard.py result FILE          # отчёт агента: критики, статус
    python tools/auto_rules/guard.py quota STATE_DIR      # потолок выкатов в сутки
    python tools/auto_rules/guard.py note STATE_DIR SHA   # записать выкат
    python tools/auto_rules/guard.py runs STATE_DIR       # потолок запусков агента в сутки
    python tools/auto_rules/guard.py attempts STATE DATA TOOLS   # случай после N попыток — человеку
    python tools/auto_rules/guard.py mark RESULT TOOLS SHA all|wontonly
    python tools/auto_rules/guard.py fid < вывод fidelity_report  # число предупреждений или ERR

Код возврата 0 — можно, 1 — нельзя (причина в stdout одной строкой).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Куда агенту МОЖНО: правила чтения/вёрстки/проверки и их тесты.
ALLOWED = ("backend/", "tests/", "docs/rules/", "tools/", "frontend/i18n/", "frontend/js/",
           "frontend/css/", "CLAUDE.md")
# Куда НЕЛЬЗЯ никогда: сам раннер и его правила, выкат, деньги, права, сторожа
# изоляции и утечек — правило вёрстки им не нужно, а их ослабление незаметно.
FORBIDDEN = ("tools/auto_rules/", "docs/rules/auto-rules", "deploy/", ".github/",
             "backend/legal.py", "backend/payments.py", "backend/price_rules.py",
             "backend/store.py", "backend/referral.py", "backend/partners.py",
             "backend/support.py", "backend/support_bot.py", "backend/tg.py", "backend/tgbot.py",
             "tests/test_money_by_role.py", "tests/test_model_names_hidden.py",
             "tests/test_routes.py", "tests/test_tenant_isolation.py", "tests/test_hardening.py",
             "tests/test_money_attacks.py", "tests/test_roles.py", "tests/test_payments.py",
             "requirements.txt",
             # Инструменты, которыми раннер проверяет и выкатывает, и эталоны:
             # подмени их — и рубеж «эталоны не хуже» отвечал бы всегда «да».
             "tools/fidelity_report.py", "tools/prod_run.sh", "tools/prepress_cases.py",
             "tools/export_review.py", "tools/photo_bench.py", "tools/landing_photo.py",
             "tests/fixtures/", "backend/fidelity.py",
             # Процессы и тексты наружу — не правила вёрстки.
             "backend/worker.py", "backend/mail_texts.py", "backend/survey.py", "backend/metrics.py")
MAX_LINES = int(os.environ.get("AUTO_RULES_MAX_LINES", "1500"))
MAX_DEPLOYS_DAY = int(os.environ.get("AUTO_RULES_MAX_DEPLOYS_DAY", "2"))
# Строки main.py, которые трогать нельзя без человека: деньги, права, входы.
_HOT = re.compile(r"_PAID|_OWNER_ONLY|PUBLIC_API_PATHS|_hide_cost|_hide_models|limitUsd|pagesCredit|"
                  r"_pages_topup|_pages_debit|require_token|_llm_limit_gate|password|_SUPER")
_ROUTE = re.compile(r"@(app|router|\w+_router)\.(get|post|put|delete|patch|api_route|websocket)\(|"
                    r"PUBLIC_API_PATHS|add_middleware|include_router|add_api_route|APIRouter\(|\.mount\(")
_CHECK = re.compile(r"\bcheck\(|\bassert\b|assertEqual|expect\(")


def git(*a) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def fail(why: str) -> None:
    print("НЕЛЬЗЯ: " + why)
    sys.exit(1)


def cmd_diff(base: str, head: str) -> None:
    # --no-renames: переименование «унесло» бы защищённый файл под видом нового.
    names = [ln.split("\t") for ln in git("diff", "--no-renames", "--name-status", base, head).splitlines() if ln]
    if not names:
        fail("изменений нет")
    total = 0
    for row in names:
        st, path = row[0], row[-1]
        if st.startswith("D") and path.startswith("tests/"):
            fail("удалён тест %s" % path)
        if any(path.startswith(f) for f in FORBIDDEN):
            fail("запретный путь %s" % path)
        if not any(path.startswith(a) for a in ALLOWED):
            fail("путь вне белого списка %s" % path)
    for ln in git("diff", "--no-renames", "--numstat", base, head).splitlines():
        a, d, _p = (ln.split("\t") + ["", ""])[:3]
        total += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    if total > MAX_LINES:
        fail("слишком большой дифф: %d строк > %d" % (total, MAX_LINES))
    # Горячие места main.py: изменённые строки не должны касаться денег и прав.
    # Весь бэкенд, а не только main.py: дверь можно завести и APIRouter-ом в модуле.
    patch = git("diff", "--no-renames", "-U0", base, head, "--", "backend/")
    for ln in patch.splitlines():
        if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---")):
            if _HOT.search(ln):
                fail("правка задевает деньги/права/вход: %s" % ln[:120])
            if ln.startswith("+") and _ROUTE.search(ln):
                fail("новая дверь в API — только человеком: %s" % ln[:120])
    # Тесты не ослабляются: проверок в существующих тестах не меньше, чем было.
    for row in names:
        path = row[-1]
        if not path.startswith("tests/") or row[0].startswith("A"):
            continue
        try:
            before = len(_CHECK.findall(git("show", "%s:%s" % (base, path))))
            after = len(_CHECK.findall(git("show", "%s:%s" % (head, path))))
        except subprocess.CalledProcessError:
            continue
        if after < before:
            fail("в %s проверок стало меньше (%d → %d)" % (path, before, after))
    added_tests = [r[-1] for r in names if r[-1].startswith("tests/")]
    if not added_tests:
        fail("правило без теста")
    if not any(r[-1] == "docs/rules/pdf-reading.md" for r in names):
        fail("правило без записи в docs/rules/pdf-reading.md")
    print("можно: %d файлов, %d строк" % (len(names), total))


def cmd_result(path: str) -> None:
    try:
        r = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        fail("нет отчёта агента (%s)" % e)
    if r.get("status") != "ready":
        fail("агент не готов: %s" % r.get("status"))
    crit = r.get("critics") or {}
    for need in ("designer", "translator", "code"):
        v = (crit.get(need) or {}).get("verdict")
        if v != "ok":
            fail("критик %s: %s" % (need, v))
    if not r.get("rules"):
        fail("в отчёте нет правил")
    if not (r.get("regression") or {}).get("ok"):
        fail("регрессия на эталонах не подтверждена")
    print("можно: правил %d, случаев %d" % (len(r["rules"]), len(r.get("cases") or [])))


MAX_RUNS_DAY = int(os.environ.get("AUTO_RULES_MAX_RUNS_DAY", "4"))
CASE_TRIES = int(os.environ.get("AUTO_RULES_CASE_TRIES", "2"))


def _jload(f: Path, dflt):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return dflt


def _jsave(f: Path, obj) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(f))


def cmd_runs(d: str) -> None:
    """Потолок ЗАПУСКОВ агента в сутки — и неудачных тоже: отказ рубежа
    оставляет случаи в очереди, и без потолка агент жёг бы бюджет каждый час."""
    f = Path(d) / "runs.json"
    st = _jload(f, {})
    day = time.strftime("%Y-%m-%d")
    n = int(st.get(day) or 0)
    if n >= MAX_RUNS_DAY:
        fail("запусков сегодня уже %d из %d" % (n, MAX_RUNS_DAY))
    _jsave(f, {day: n + 1})
    print("можно: запуск %d из %d" % (n + 1, MAX_RUNS_DAY))


def cmd_attempts(d: str, data: str, tools_root: str) -> None:
    """Счётчик попыток на случай: случай, который агент разбирал уже
    CASE_TRIES раз, уходит человеку (`wont` с пометкой) и из каталога разбора."""
    f = Path(d) / "attempts.json"
    st = _jload(f, {})
    for cj in sorted(Path(data, "cases").glob("*.json")):
        r = _jload(cj, {})
        key = "%s/%s/%s" % (r.get("_dir"), r.get("project"), r.get("n"))
        st[key] = int(st.get(key) or 0) + 1
        if st[key] > CASE_TRIES:
            subprocess.run([sys.executable, str(Path(tools_root, "tools", "prepress_cases.py")), "wont",
                            str(r.get("_dir")), str(r.get("project")), str(r.get("n")),
                            "--note", "held: %d попыток автомата, нужен человек" % CASE_TRIES])
            cj.unlink()
            jp = cj.with_suffix(".jpg")
            if jp.exists():
                jp.unlink()
    _jsave(f, st)
    print("попытки учтены")


def cmd_mark(res: str, tools_root: str, sha: str, mode: str) -> None:
    """Отметки очереди по отчёту агента: `all` — после принятого выката,
    `wontonly` — когда выката нет (только «не наш брак» и «человеку»)."""
    r = _jload(Path(res), {})
    tool = str(Path(tools_root, "tools", "prepress_cases.py"))
    for c in r.get("cases") or []:
        v = c.get("verdict")
        if v not in ("done", "wont", "held") or (mode == "wontonly" and v == "done"):
            continue
        note = (c.get("note") or v)[:200] + ((" (%s)" % sha) if sha else "")
        cmd = [sys.executable, tool, "done" if v == "done" else "wont", str(c.get("tenant")), str(c.get("pid")),
               str(c.get("n")), "--note", ("held: " if v == "held" else "") + note]
        if v == "done":
            cmd += ["--rule", c.get("rule") or "?"]
        subprocess.run(cmd)
    if mode == "all":
        tool_r = str(Path(tools_root, "tools", "export_review.py"))
        for rv in r.get("reviews") or []:
            if rv.get("verdict") == "done":
                subprocess.run([sys.executable, tool_r, "done", str(rv.get("rid")), "--report",
                                (rv.get("report") or "auto-rules")[:200], "--note", (rv.get("note") or "")[:200]])
    print("отметки поставлены")


_FID_ROW = re.compile(r"outside=.*warn=(\[.*\])\s*$")


def cmd_fid() -> None:
    """Вывод `tools/fidelity_report.py` (stdin) → общее ЧИСЛО предупреждений.
    Ни одной строки эталона — прогон упал: «ERR» и код 1, а не «0»: упавший
    замер не вправе пропускать выкат (критик 25.10.2026)."""
    import ast
    rows, total = 0, 0
    for ln in sys.stdin.read().splitlines():
        m = _FID_ROW.search(ln.strip())
        if not m:
            continue
        rows += 1
        try:
            total += len(ast.literal_eval(m.group(1)) or [])
        except Exception:
            total += 1
    if not rows:
        print("ERR")
        sys.exit(1)
    print(total)


def _state(d: str) -> dict:
    f = Path(d) / "deploys.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"deploys": []}


def cmd_quota(d: str) -> None:
    st = _state(d)
    day = time.strftime("%Y-%m-%d")
    n = sum(1 for x in st.get("deploys") or [] if x.get("day") == day)
    if n >= MAX_DEPLOYS_DAY:
        fail("выкатов сегодня уже %d из %d" % (n, MAX_DEPLOYS_DAY))
    print("можно: выкатов сегодня %d из %d" % (n, MAX_DEPLOYS_DAY))


def cmd_note(d: str, sha: str, prev: str = "", status: str = "deployed") -> None:
    Path(d).mkdir(parents=True, exist_ok=True)
    st = _state(d)
    st.setdefault("deploys", []).append({"day": time.strftime("%Y-%m-%d"), "at": time.strftime("%H:%M"),
                                         "sha": sha, "prev": prev, "status": status})
    st["deploys"] = st["deploys"][-200:]
    f = Path(d) / "deploys.json"
    f.with_suffix(".tmp").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(f.with_suffix(".tmp")), str(f))
    print("записано")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    a = sys.argv[1:]
    if not a:
        fail("нет команды")
    if a[0] == "diff" and len(a) == 3:
        cmd_diff(a[1], a[2])
    elif a[0] == "result" and len(a) == 2:
        cmd_result(a[1])
    elif a[0] == "quota" and len(a) == 2:
        cmd_quota(a[1])
    elif a[0] == "runs" and len(a) == 2:
        cmd_runs(a[1])
    elif a[0] == "attempts" and len(a) == 4:
        cmd_attempts(a[1], a[2], a[3])
    elif a[0] == "mark" and len(a) == 5:
        cmd_mark(a[1], a[2], a[3], a[4])
    elif a[0] == "fid" and len(a) == 1:
        cmd_fid()
    elif a[0] == "note" and len(a) >= 3:
        cmd_note(a[1], a[2], a[3] if len(a) > 3 else "", a[4] if len(a) > 4 else "deployed")
    else:
        fail("неизвестная команда")
