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
             "requirements.txt")
MAX_LINES = int(os.environ.get("AUTO_RULES_MAX_LINES", "1500"))
MAX_DEPLOYS_DAY = int(os.environ.get("AUTO_RULES_MAX_DEPLOYS_DAY", "2"))
# Строки main.py, которые трогать нельзя без человека: деньги, права, входы.
_HOT = re.compile(r"_PAID|_OWNER_ONLY|PUBLIC_API_PATHS|_hide_cost|_hide_models|limitUsd|pagesCredit|"
                  r"_pages_topup|_pages_debit|require_token|_llm_limit_gate|password|_SUPER")
_CHECK = re.compile(r"\bcheck\(|\bassert\b|assertEqual|expect\(")


def git(*a) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def fail(why: str) -> None:
    print("НЕЛЬЗЯ: " + why)
    sys.exit(1)


def cmd_diff(base: str, head: str) -> None:
    names = [ln.split("\t") for ln in git("diff", "--name-status", base, head).splitlines() if ln]
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
    for ln in git("diff", "--numstat", base, head).splitlines():
        a, d, _p = (ln.split("\t") + ["", ""])[:3]
        total += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    if total > MAX_LINES:
        fail("слишком большой дифф: %d строк > %d" % (total, MAX_LINES))
    # Горячие места main.py: изменённые строки не должны касаться денег и прав.
    patch = git("diff", "-U0", base, head, "--", "backend/main.py")
    for ln in patch.splitlines():
        if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---")):
            if _HOT.search(ln):
                fail("правка задевает деньги/права/вход: %s" % ln[:120])
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
    elif a[0] == "note" and len(a) >= 3:
        cmd_note(a[1], a[2], a[3] if len(a) > 3 else "", a[4] if len(a) > 4 else "deployed")
    else:
        fail("неизвестная команда")
