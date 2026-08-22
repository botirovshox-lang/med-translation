"""Отчёт после прогона (tools/after_run.py): считает по ответам сервера и молчит,
только когда придраться не к чему.

Сеть не трогаем — HTTP-слой подменён. Проверяется то, ради чего скрипт написан:
не «печатает ли он что-нибудь», а замечает ли он ухудшение и правильно ли
возвращает код возврата (на нём будет висеть cron).
"""
import io, json, os, sys, tempfile

sys.path.insert(0, "tools")
import after_run

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# ── Ответы сервера той же формы, что отдают эндпоинты ───────────────────
def analysis(clean=90, findings=(), weak=(), untranslated=(),
             confirmed_findings=(), gloss_confirmed=()):
    return {"ok": True, "total": 100,
            "clean": list(range(1, clean + 1)),
            "repaired": [], "machine": {"repaired": 0, "reverted": 0},
            "proposed": {"terms": 4},
            "human": {"terms": [], "termsTotal": 7, "reverted": [],
                      "glossaryConfirmed": list(gloss_confirmed),
                      "confirmedFindings": list(confirmed_findings)},
            "todo": {"untranslated": list(untranslated), "unchecked": [],
                     "findings": list(findings), "glossaryPending": [],
                     "weak": list(weak), "weakWhy": []}}


PLAN = {"steps": [
    {"step": "translate", "label": "Перевод", "count": 0, "ids": [], "runs": [], "skips": [
        {"reason": "уже переведён", "count": 100}]},
    {"step": "repair", "label": "Ремонт", "count": 2, "ids": [4, 5], "runs": [
        {"reason": "есть находки", "count": 2}], "skips": [
        {"reason": "заверено человеком — включите «чинить подтверждённые»", "count": 3}]},
], "ids": [4, 5], "total": 2, "scope": 100}


def job(status="done", counters=None, jid=7, kind="full", error=None):
    return {"id": jid, "kind": kind, "project": 1, "status": status, "total": 100,
            "done": 100, "counters": counters or {}, "error": error,
            "created": "2026-08-22 10:00", "started": "2026-08-22 10:00",
            "finished": "2026-08-22 11:30", "params": {}, "recent": []}


def raw(a=None, j=None, active=()):
    return {"analysis": a or analysis(), "plan": PLAN, "job": j, "active": list(active)}


# ── 1. Снимок собирается из ответов, а не из собственной арифметики ──────
print("=== 1. Снимок берёт цифры сервера как есть ===")
d = after_run.digest(1, "Выписка", raw(
    a=analysis(clean=88, findings=[4, 5], weak=[9], confirmed_findings=[11, 12],
               gloss_confirmed=[11]),
    j=job(counters={"errors": 3, "applied": 12, "duplicates": 40, "why": "insufficient_quota"})))
check(d["clean"] == 88 and d["total"] == 100, "корзины перенесены без пересчёта")
check(d["confirmedFindings"] == 2, "подтверждённые с находками видны отдельной цифрой")
check(d["planSteps"]["repair"] == 2, "состав следующего прогона взят из разбора сервера")
check(d["job"]["errors"] == 3 and d["job"]["why"] == "insufficient_quota",
      "ошибки прогона названы вместе с причиной, а не одним числом")

# ── 2. Придирки: ровно то, на что стоит смотреть ─────────────────────────
print("\n=== 2. Что скрипт считает поводом придраться ===")
clean_d = after_run.digest(1, "Ч", raw(j=job()))
check(after_run.complaints(clean_d, None) == [],
      "на здоровом проекте молчит — иначе отчёт перестанут читать")

d_err = after_run.digest(1, "Ч", raw(j=job(counters={"errors": 40, "why": "rate limit"})))
check(any("ошибок" in c for c in after_run.complaints(d_err, None)),
      "ошибки прогона — повод: скорость могла быть куплена за 429-е")

d_fall = after_run.digest(1, "Ч", raw(j=job(status="error", error="ключ отозван")))
check(any("упал" in c and "ключ отозван" in c for c in after_run.complaints(d_fall, None)),
      "упавший прогон назван вместе с причиной")

d_conf = after_run.digest(1, "Ч", raw(a=analysis(confirmed_findings=[1, 2, 3]), j=job()))
issues = after_run.complaints(d_conf, None)
check(any("сами не починятся" in c for c in issues),
      "подтверждённые с находками названы прямо: их не возьмёт ни один прогон")

d_skip = after_run.digest(1, "Ч", raw(j=job(counters={"skipped_confirmed": 5})))
check(any("чинить подтверждённые" in c for c in after_run.complaints(d_skip, None)),
      "если прогон обошёл заверенное — сказано, какой галочкой это включается")

d_blocked = after_run.digest(1, "Ч", raw(j=job(counters={"step_skips": 3})))
check(any("шаги пропускались" in c for c in after_run.complaints(d_blocked, None)),
      "пропущенные шаги не теряются: без ключа шаг молча ничего не делает")

# ── 3. Сравнение с прошлым разом ─────────────────────────────────────────
print("\n=== 3. Рост виден только в сравнении ===")
prev = after_run.digest(1, "Ч", raw(a=analysis(weak=[1, 2]), j=job()))
now_worse = after_run.digest(1, "Ч", raw(a=analysis(weak=[1, 2, 3, 4]), j=job()))
now_better = after_run.digest(1, "Ч", raw(a=analysis(weak=[1]), j=job()))
check(any("2 → 4" in c for c in after_run.complaints(now_worse, prev)),
      "рост слабых сегментов замечен и показан дельтой")
check(after_run.complaints(now_better, prev) == [],
      "падение молчит: отчёт нужен, чтобы заметить ухудшение, а не хвалить себя")
check(after_run.complaints(now_worse, None) == [],
      "без прошлого снимка про рост не выдумываем")

# ── 4. Печать не падает на пустых местах ─────────────────────────────────
print("\n=== 4. Человеческий отчёт ===")
r = raw(a=analysis(confirmed_findings=[11], weak=[9]), j=job(counters={"errors": 2}))
d4 = after_run.digest(1, "Выписка", r)
text = after_run.human_report(d4, prev, r, after_run.complaints(d4, prev))
for must in ("Проект #1", "подтверждено, но есть находки", "ЧТО СДЕЛАЕТ СЛЕДУЮЩИЙ ОБЩИЙ ПРОГОН",
             "заверено человеком", "НА ЭТО СТОИТ ПОСМОТРЕТЬ"):
    check(must in text, "в отчёте есть: " + must)
check("(+" in text or "(-" in text, "дельта к прошлому снимку показана")

no_job = raw(j=None)
d5 = after_run.digest(1, "Ч", no_job)
txt5 = after_run.human_report(d5, None, no_job, [])
check("Прогонов в памяти сервера нет" in txt5,
      "рестарт сервиса теряет историю задач — это сказано, а не показано нулями")

busy = raw(j=job(), active=[{"id": 9, "kind": "full", "done": 12, "total": 100}])
d6 = after_run.digest(1, "Ч", busy)
check("ПРОГОН ИДЁТ СЕЙЧАС" in after_run.human_report(d6, None, busy, []),
      "во время прогона отчёт честно предупреждает, что цифры устареют")

# ── 5. Снимок: пишем после сравнения, читаем в следующий раз ─────────────
print("\n=== 5. Снимок на диске ===")
tmp = tempfile.mkdtemp()
after_run.REPORT_DIR = tmp
check(after_run.load_prev(1) is None, "нет снимка — нет и сравнения (не падаем)")
check(after_run.save_snapshot(1, d4) is True, "снимок сохранён")
back = after_run.load_prev(1)
check(back and back["confirmedFindings"] == d4["confirmedFindings"],
      "и прочитан обратно тем же")
check(os.path.exists(os.path.join(tmp, "project-1.json")) and
      not os.path.exists(os.path.join(tmp, "project-1.json.tmp")),
      "запись атомарная: временный файл не остаётся")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
