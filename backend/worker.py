"""medcat-worker — прогоны отдельным процессом.

API только ставит задачу в таблицу `jobs`; здесь она забирается `claim_job`
(FOR UPDATE SKIP LOCKED — два воркера не возьмут одну), перед исполнением
подтягиваются свежие разделяемые коллекции и СВЕЖИЙ документ проекта, после —
поднимается эпоха `doc:projects:N`, и API перечитывает готовый проект.
Стоп-флаг и прогресс ходят через ту же таблицу (см. `_job_should_stop`).

Запуск: MEDCAT_ROLE=worker обязателен ДО импорта main (он выключает у этого
процесса перечитку задач в зеркало и охрану 409 — воркер сам себе не чужой).
Работает ТОЛЬКО с базой: у файла второй процесс запрещён (инвариант 1).
"""
import os
import sys
import time

os.environ["MEDCAT_ROLE"] = "worker"

try:
    from backend import main
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import main

POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "2"))


def run() -> None:
    if main.STORE.kind != "pg":
        raise SystemExit("medcat-worker работает только с DATABASE_URL (PostgreSQL)")
    stale = main.STORE.reset_running_jobs()
    if stale:
        print(f"[worker] оборванные рестартом прогоны снова в очереди: {stale}", file=sys.stderr)
    print("[worker] запущен, жду задачи", file=sys.stderr)
    while True:
        try:
            job = main.STORE.claim_job()
        except Exception as e:
            print(f"[worker] очередь недоступна: {e}", file=sys.stderr)
            time.sleep(max(POLL_SECONDS, 5))
            continue
        if not job:
            time.sleep(POLL_SECONDS)
            continue
        job.setdefault("stop", False)
        job.setdefault("recent", [])
        job.setdefault("ids", [])
        job.setdefault("counters", {})
        # Свежий документ проекта: наша копия могла отстать от правок в API.
        key = "projects:%d" % job["project"]
        try:
            main._apply_doc(key, main.STORE.load_doc(key))
        except Exception as e:
            print(f"[worker] проект не перечитан: {e}", file=sys.stderr)
        main._JOBS[job["id"]] = job
        print(f"[worker] прогон №{job['id']} ({job.get('kind')}) по проекту {job['project']}",
              file=sys.stderr)
        main._job_execute(job)
        try:
            # Готовый проект — в API: он перечитает документ по этой эпохе.
            main.STORE.bump_epoch("doc:" + key)
        except Exception as e:
            print(f"[worker] эпоха проекта не поднята: {e}", file=sys.stderr)
        print(f"[worker] прогон №{job['id']} завершён: {job.get('status')}", file=sys.stderr)


if __name__ == "__main__":
    run()
