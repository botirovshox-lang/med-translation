"""Замер: сдвигает ли ревизия ПАЧКОЙ оценки против одиночной ревизии.

Зачем. Пачка (`REVIEW_BATCH`, `_review_ask_many`) снимает повторную
инструкцию с каждой строки, но оценки в пачке могут сместиться: модель
невольно сравнивает строки между собой. От шкалы зависят пороги
REVIEW_APPLY_MAX (≤ 7 — правка ставится сама) и REVIEW_VOUCH_SCORE (≥ 9 —
ревизия ручается за перевод).

Как решаем. Все три прохода идут СЕЙЧАС, по одним строкам и в одной
обстановке (соседи, их перевод, правила документа):
  • «одиночно А» и «одиночно Б» — два одиночных прохода: их расхождение и есть
    шум самой модели;
  • «пачкой» — сравнивается с «одиночно А» ТОЛЬКО по строкам, на которые
    ответила пачка (строки, ушедшие после сбоя на одиночный вызов, выводятся
    отдельно: иначе они размывали бы выборку в пользу пачки).
Сохранённые вердикты на сегментах эталоном НЕ служат: их выносили в другой
обстановке (сосед мог быть ещё не переведён или переписан ремонтом).
Включать пачку можно, если «пачка ↔ одиночно А» расходится по обоим порогам
не больше, чем «одиночно Б ↔ одиночно А».

Цена каждого прохода — по счётчику процесса (`_USAGE_TOTAL`), то есть с
отвергнутыми пачками и повторными вызовами, а не по принятым долям.

В проект НЕ пишет ничего — ни вердиктов, ни текста; расход учитывается как
обычно (это настоящие деньги). ПЛАТНО: на видео №12 (~150 строк) около $0.6
за каждый одиночный проход и $0.2–0.4 за пачку, всего ≈ $1.5. Запускать
только по решению человека.

    bash tools/prod_run.sh tools/review_batch_ab.py
    (проект, число строк, размер пачки — AB_PID, AB_LIMIT, AB_BATCH)
"""
import os
import sys
from pathlib import Path


def _root() -> Path:
    """Корень репозитория. `prod_run.sh` кладёт скрипт в /tmp и запускает
    его из каталога сервиса, поэтому по `__file__` его не найти."""
    for cand in (os.environ.get("MEDCAT_ROOT"), Path(__file__).resolve().parent.parent,
                 Path.cwd(), "/opt/med-translation"):
        if cand and (Path(cand) / "backend" / "main.py").exists():
            return Path(cand)
    raise SystemExit("Не найден каталог с backend/main.py: задайте MEDCAT_ROOT")


def _load_env(path="/etc/medcat/env"):
    """Ключи сервиса: prod_run.sh запускает python без окружения юнита."""
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def main_():
    _load_env()
    pid = int(os.environ.get("AB_PID", "12"))
    limit = int(os.environ.get("AB_LIMIT", "150"))
    os.environ["MEDCAT_ROLE"] = "worker"          # миграции старта не пишут
    sys.path.insert(0, str(_root() / "backend"))
    import main

    if getattr(main.STORE, "kind", "") == "pg":
        key = "projects:%d" % pid
        main._apply_doc(key, main.STORE.load_doc(key))
    project = next((p for p in main.STATE.get("projects") or [] if p.get("id") == pid), None)
    if not project:
        print("Проекта %d нет" % pid)
        return 1
    if not main._cue_project(project):
        print("Проект %d — не субтитры: пачка к нему не применяется, мерить нечего" % pid)
        return 1
    main.CURRENT_SESSION.set({"tenant": main._tenant_of(project), "user": None,
                              "role": "owner"})
    main._USAGE_PROJECT.set(pid)                  # расход — на этот проект
    main.REVIEW_BATCH = int(os.environ.get("AB_BATCH", "6"))
    base = [s for s in project["segments"]
            if (s.get("target") or "").strip() and not main._human_text(s)][:limit]
    if len(base) < 6:
        print("Мало строк для замера: %d" % len(base))
        return 1
    print("Проект %d: строк %d, пачка до %d" % (pid, len(base), main.REVIEW_BATCH))

    def spent(fn):
        c0 = main._USAGE_TOTAL["cost"]
        out = fn()
        return out, main._USAGE_TOTAL["cost"] - c0

    def singles():
        return main._run_parallel(base, lambda s: main._review_ask(s, project, None))

    a, cost_a = spent(singles)
    b, cost_b = spent(singles)
    batch, cost_batch = spent(lambda: main._review_ask_many(base, project, None))

    def cmp(name, ref, got, only_batch=False):
        pairs = [(float(r["score"]), float(g["score"])) for r, g in zip(ref, got)
                 if r and g and (not only_batch or g.get("batch"))]
        n = len(pairs)
        if not n:
            print("%-26s нет пар" % name)
            return
        mad = sum(abs(x - y) for x, y in pairs) / n
        shift = sum(y - x for x, y in pairs) / n
        fix = sum((x <= main.REVIEW_APPLY_MAX) != (y <= main.REVIEW_APPLY_MAX) for x, y in pairs)
        vouch = sum((x >= main.REVIEW_VOUCH_SCORE) != (y >= main.REVIEW_VOUCH_SCORE)
                    for x, y in pairs)
        print("%-26s пар %3d  |Δ| %.2f  сдвиг %+.2f  порог ≤%g: %2d (%.0f%%)  "
              "порог ≥%g: %2d (%.0f%%)"
              % (name, n, mad, shift, main.REVIEW_APPLY_MAX, fix, 100.0 * fix / n,
                 main.REVIEW_VOUCH_SCORE, vouch, 100.0 * vouch / n))

    def fixes(got):
        return sum(1 for g in got if g and g.get("fixed")
                   and float(g["score"]) <= main.REVIEW_APPLY_MAX)

    by_batch = sum(1 for g in batch if g and g.get("batch"))
    print("ответили: одиночно А %d, Б %d, пачкой %d (+%d по одной после сбоя)"
          % (sum(1 for g in a if g), sum(1 for g in b if g), by_batch,
             sum(1 for g in batch if g and not g.get("batch"))))
    print("правок (оценка ≤ %g с вариантом): А %d, Б %d, пачка %d"
          % (main.REVIEW_APPLY_MAX, fixes(a), fixes(b), fixes(batch)))
    cmp("шум: одиночно Б ↔ А", a, b)
    cmp("пачка ↔ одиночно А", a, batch, only_batch=True)
    cmp("пачка ↔ одиночно Б", b, batch, only_batch=True)
    print("цена: одиночно А $%.4f, Б $%.4f, пачкой $%.4f (экономия %.0f%%)"
          % (cost_a, cost_b, cost_batch,
             100.0 * (1 - cost_batch / cost_a) if cost_a else 0))
    print("Включать пачку можно, если её расхождения по порогам не больше шума.")
    main._metrics_flush(force=True)              # расход по дням — в базу
    return 0


if __name__ == "__main__":
    sys.exit(main_())
