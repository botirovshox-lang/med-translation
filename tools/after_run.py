#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отчёт после прогона: что прогон сделал, что осталось и не стало ли хуже.

Зачем. После прогона человек смотрит на три разных экрана и держит прошлые
цифры в голове. Держать их в голове нельзя: «ошибок 40» плохо не само по себе,
а по сравнению с прошлым разом, и «слабых 970» — это рост или падение, только
если есть с чем сравнить.

Ни одного вызова модели здесь нет — только чтение готовых ответов сервера,
запускать можно свободно и сколько угодно раз:
  GET  /api/jobs?project=N          — счётчики последних прогонов;
  GET  /api/projects/N/analysis     — корзины по проекту (кэш по отпечатку);
  POST /api/projects/N/run-plan     — что осталось и почему.

Код возврата: 0 — придраться не к чему, 1 — есть к чему (годится для cron
и для git-хука), 2 — не удалось поговорить с сервером.

Запуск:
    APP_PASSWORD=... python3 tools/after_run.py            # все проекты
    APP_PASSWORD=... python3 tools/after_run.py -p 3 --save
    MEDCAT_URL=http://127.0.0.1:8000 python3 tools/after_run.py --json

Снимок (--save) кладётся в backend/data/reports/ — единственное место, куда
сервису разрешено писать (systemd ReadWritePaths). Следующий запуск сравнит
с ним и покажет дельту.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

BASE = os.environ.get("MEDCAT_URL", "http://127.0.0.1:8000").rstrip("/")
REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "backend", "data", "reports")
TIMEOUT = 30


class Fail(Exception):
    pass


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            pass
        raise Fail("%s %s → HTTP %s%s" % (method, path, e.code, (": " + str(detail)) if detail else ""))
    except urllib.error.URLError as e:
        raise Fail("%s %s → сервер не отвечает: %s" % (method, path, e.reason))


def login():
    pw = os.environ.get("APP_PASSWORD", "").strip()
    if not pw:
        raise Fail("APP_PASSWORD не задан. На сервере он лежит в /etc/medcat/env")
    return call("POST", "/api/auth/login", body={"password": pw})["token"]


# ─────────────────────────── сбор ───────────────────────────

def collect(token, pid):
    """Три ответа сервера про один проект. Ничего не считаем сами: любая своя
    арифметика поверх — это второй расчёт рядом с серверным, и они разойдутся."""
    analysis = call("GET", "/api/projects/%d/analysis" % pid, token)
    plan = call("POST", "/api/projects/%d/run-plan" % pid, token, body={})
    jobs = call("GET", "/api/jobs?project=%d&limit=10" % pid, token)
    mine = [j for j in jobs.get("jobs", []) if j.get("project") == pid]
    last = next((j for j in mine if j.get("status") in ("done", "error", "stopped")), None)
    return {"analysis": analysis, "plan": plan, "job": last,
            "active": [j for j in jobs.get("active", []) if j.get("project") == pid]}


def digest(pid, title, raw):
    """Плоский снимок для сравнения с прошлым разом."""
    a, plan, job = raw["analysis"], raw["plan"], raw["job"]
    todo, human = a.get("todo", {}), a.get("human", {})
    c = (job or {}).get("counters", {}) or {}
    return {
        "project": pid,
        "title": title,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": a.get("total", 0),
        "clean": len(a.get("clean", [])),
        "untranslated": len(todo.get("untranslated", [])),
        "unchecked": len(todo.get("unchecked", [])),
        "findings": len(todo.get("findings", [])),
        "weak": len(todo.get("weak", [])),
        "glossaryPending": len(todo.get("glossaryPending", [])),
        "glossaryConfirmed": len(human.get("glossaryConfirmed", [])),
        "confirmedFindings": len(human.get("confirmedFindings", [])),
        "termsForHuman": human.get("termsTotal", 0),
        "termsReady": a.get("proposed", {}).get("terms", 0),
        "planTotal": plan.get("total", 0),
        "planSteps": {p["step"]: p["count"] for p in plan.get("steps", [])},
        "job": {
            "id": (job or {}).get("id"),
            "kind": (job or {}).get("kind"),
            "status": (job or {}).get("status"),
            "finished": (job or {}).get("finished"),
            "errors": c.get("errors", 0),
            "applied": c.get("applied", 0),
            "reverted": c.get("reverted", 0),
            "duplicates": c.get("duplicates", 0),
            "tmHits": c.get("tm_hits", 0),
            "stepSkips": c.get("step_skips", 0),
            "skippedConfirmed": c.get("skipped_confirmed", 0),
            "why": (job or {}).get("error") or c.get("why") or "",
        },
    }


# ─────────────────────────── придирки ───────────────────────────
# Порог — не «плохо», а «на это стоит посмотреть». Молча вернуть ноль там, где
# прогон завершился с ошибками, значит повторить ту же беду, из-за которой
# мёртвый ключ выглядел как «выполнено».

def complaints(d, prev):
    out = []
    j = d["job"]
    if j["status"] == "error":
        out.append("прогон #%s (%s) упал%s" % (j["id"], j["kind"], (": " + j["why"]) if j["why"] else ""))
    elif j["status"] == "stopped":
        out.append("прогон #%s (%s) остановлен — работа не доведена" % (j["id"], j["kind"]))
    if j["errors"]:
        out.append("ошибок в последнем прогоне: %d%s" % (j["errors"], (" — " + j["why"]) if j["why"] else ""))
    if j["stepSkips"]:
        out.append("шаги пропускались %d раз (нет ключа или модуля)" % j["stepSkips"])
    if j["skippedConfirmed"]:
        out.append("прогон обошёл %d подтверждённых сегментов: включите «чинить подтверждённые»"
                   % j["skippedConfirmed"])
    if d["confirmedFindings"]:
        out.append("подтверждено человеком, но есть находки: %d — сами не починятся"
                   % d["confirmedFindings"])
    if d["glossaryConfirmed"]:
        out.append("подтверждено человеком, но спорит с глоссарием: %d" % d["glossaryConfirmed"])
    if prev:
        # Рост — единственное, что видно только в сравнении. Падение молчит:
        # отчёт нужен, чтобы заметить ухудшение, а не чтобы себя хвалить.
        for key, label in (("weak", "сегментов с оценкой ниже порога"),
                           ("findings", "сегментов с замечаниями"),
                           ("untranslated", "непереведённых")):
            was, now = prev.get(key, 0), d[key]
            if now > was:
                out.append("%s стало больше: %d → %d" % (label, was, now))
    return out


# ─────────────────────────── печать ───────────────────────────

def human_report(d, prev, raw, issues):
    def delta(key):
        if not prev or key not in prev:
            return ""
        diff = d[key] - prev[key]
        return "" if diff == 0 else ("  (%+d)" % diff)

    lines = []
    add = lines.append
    add("═" * 62)
    add("Проект #%d · %s · сегментов: %d" % (d["project"], d["title"], d["total"]))
    if prev:
        add("Сравнение с %s" % prev.get("at", "прошлым снимком"))
    add("═" * 62)

    j = d["job"]
    if raw["active"]:
        a = raw["active"][0]
        add("ПРОГОН ИДЁТ СЕЙЧАС: #%s %s — %s/%s. Цифры ниже устареют к его концу."
            % (a.get("id"), a.get("kind"), a.get("done"), a.get("total")))
    if j["id"]:
        add("Последний прогон: #%s %s — %s%s" % (j["id"], j["kind"], j["status"],
                                                 ("  завершён " + j["finished"]) if j["finished"] else ""))
        bits = [("ошибок", j["errors"]), ("починено", j["applied"]), ("откачено", j["reverted"]),
                ("повторов", j["duplicates"]), ("из памяти", j["tmHits"]),
                ("шагов пропущено", j["stepSkips"])]
        add("  " + " · ".join("%s: %d" % (k, v) for k, v in bits if v))
        if j["why"]:
            add("  причина: " + j["why"])
    else:
        add("Прогонов в памяти сервера нет (рестарт сервиса их теряет).")

    add("")
    add("СОСТОЯНИЕ ПРОЕКТА")
    for key, label in (("clean", "проверено начисто"),
                       ("untranslated", "ещё не переведено"),
                       ("unchecked", "переведено, но не проверено"),
                       ("findings", "с замечаниями проверок"),
                       ("weak", "оценка ниже порога"),
                       ("glossaryPending", "расходятся с глоссарием")):
        add("  %-32s %6d%s" % (label, d[key], delta(key)))

    add("")
    add("ЖДЁТ ЧЕЛОВЕКА")
    for key, label in (("confirmedFindings", "подтверждено, но есть находки"),
                       ("glossaryConfirmed", "подтверждено, но спорит с глоссарием"),
                       ("termsForHuman", "терминов машина решать не берётся"),
                       ("termsReady", "терминов готовы к автоодобрению")):
        add("  %-32s %6d%s" % (label, d[key], delta(key)))

    add("")
    add("ЧТО СДЕЛАЕТ СЛЕДУЮЩИЙ ОБЩИЙ ПРОГОН (сегментов на шаг)")
    for p in raw["plan"].get("steps", []):
        add("  %-32s %6d" % (p["label"], p["count"]))
        for r in p.get("skips", [])[:2]:
            add("      мимо: %s — %d" % (r["reason"], r["count"]))
    add("  %-32s %6d" % ("всего в работе", d["planTotal"]))

    add("")
    if issues:
        add("НА ЭТО СТОИТ ПОСМОТРЕТЬ")
        for c in issues:
            add("  • " + c)
    else:
        add("Придраться не к чему.")
    return "\n".join(lines)


# ─────────────────────────── снимки ───────────────────────────

def snapshot_path(pid):
    return os.path.join(REPORT_DIR, "project-%d.json" % pid)


def load_prev(pid):
    try:
        with open(snapshot_path(pid), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_snapshot(pid, d):
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        tmp = snapshot_path(pid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, snapshot_path(pid))    # как save_state: подменяем целиком
        return True
    except OSError as e:
        sys.stderr.write("снимок не сохранён (%s): %s\n" % (REPORT_DIR, e))
        return False


def main():
    ap = argparse.ArgumentParser(description="Отчёт по проекту после прогона (без вызовов модели)")
    ap.add_argument("-p", "--project", type=int, action="append",
                    help="id проекта; можно повторять. Без него — все проекты")
    ap.add_argument("--json", action="store_true", help="выдать снимок машине, а не человеку")
    ap.add_argument("--save", action="store_true",
                    help="сохранить снимок в backend/data/reports/ для сравнения в следующий раз")
    args = ap.parse_args()

    try:
        token = login()
        projects = call("GET", "/api/projects", token)
    except Fail as e:
        sys.stderr.write("Ошибка: %s\n" % e)
        return 2

    wanted = args.project or [p["id"] for p in projects]
    titles = {p["id"]: p.get("title") or "без названия" for p in projects}
    missing = [p for p in wanted if p not in titles]
    if missing:
        sys.stderr.write("Нет таких проектов: %s\n" % ", ".join(map(str, missing)))
        return 2

    out, dirty = [], False
    for pid in wanted:
        try:
            raw = collect(token, pid)
        except Fail as e:
            sys.stderr.write("Проект %d: %s\n" % (pid, e))
            return 2
        d = digest(pid, titles[pid], raw)
        prev = load_prev(pid)
        issues = complaints(d, prev)
        dirty = dirty or bool(issues)
        if args.json:
            out.append(dict(d, issues=issues))
        else:
            out.append(human_report(d, prev, raw, issues))
        if args.save:
            # Снимок пишем ПОСЛЕ сравнения — иначе сравнивали бы сами с собой.
            save_snapshot(pid, d)

    print(json.dumps(out, ensure_ascii=False, indent=1) if args.json else "\n\n".join(out))
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main())
