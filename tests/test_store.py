"""Хранилище состояния (`backend/store.py`): файл и PostgreSQL по документам.

STATE остаётся моделью в памяти; здесь сторожится, что Postgres-бэкенд пишет
ТОЛЬКО изменившиеся документы (подтверждение одного сегмента не переписывает
все проекты), убирает документ удалённого проекта, восстанавливает порядок
проектов и хранит очередь прогонов. Postgres подменён записывающим
соединением — сети нет. Ни одного вызова модели.
"""
import os, sys, json, tempfile
from pathlib import Path
sys.path.insert(0, "backend")
import store

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. Файл: круг записи и чтения ===")
tmp = Path(tempfile.mkdtemp()) / "state.json"
fs = store.FileStore(tmp)
check(fs.load() is None, "пустого файла нет — None")
fs.save({"projects": [{"id": 1, "segments": []}], "glossary": [{"src": "a"}]})
check(fs.load()["glossary"][0]["src"] == "a" and not tmp.with_name("state.json.tmp").exists(),
      "записано атомарно и читается")


class FakeCur:
    def __init__(self, conn): self.conn = conn
    def execute(self, sql, params=None):
        self.conn.log.append((sql.split()[0], params))
        s = sql.strip()
        if s.startswith("INSERT INTO state_docs"):
            self.conn.docs[params[0]] = params[1]
        elif s.startswith("DELETE FROM state_docs"):
            self.conn.docs.pop(params[0], None)
        elif s.startswith("INSERT INTO jobs"):
            self.conn.jobs[params[0]] = params[3]
        elif s.startswith("DELETE FROM jobs"):
            self.conn.jobs.pop(params[0], None)
        elif s.startswith("SELECT key, doc"):
            self._rows = [(k, json.loads(v)) for k, v in self.conn.docs.items()]
        elif s.startswith("SELECT doc FROM jobs"):
            self._rows = [(json.loads(v),) for _, v in sorted(self.conn.jobs.items())]
    def fetchall(self): return self._rows
    def close(self): pass


class FakeConn:
    closed = False
    def __init__(self): self.log, self.docs, self.jobs, self.commits = [], {}, {}, 0
    def cursor(self): return FakeCur(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


print("=== 2. Postgres: пишутся только изменившиеся документы ===")
conn = FakeConn()
pg = store.PgStore("postgresql://x", connect=lambda url: conn)
check(sum(1 for op, _ in conn.log if op == "CREATE") == 2, "схема создана")
state = {"projects": [{"id": 2, "title": "B", "segments": [{"id": 1, "target": ""}]},
                      {"id": 1, "title": "A", "segments": []}],
         "glossary": [{"src": "x"}], "tm": [], "users": [{"id": 1}], "termQueue": []}
r = pg.save(state)
check(r["written"] == 7 and set(conn.docs) == {"projects:1", "projects:2", "projects_order", "glossary", "tm", "users", "termQueue"},
      "первое сохранение — все документы: %s" % r)
r = pg.save(state)
check(r["written"] == 0 and r["deleted"] == 0, "без изменений — ничего не пишется")
n0 = len(conn.log)
state["projects"][0]["segments"][0]["target"] = "done"
r = pg.save(state)
check(r["written"] == 1 and conn.log[-1][1][0] == "projects:2", "правка сегмента — один документ проекта")
state["projects"] = [p for p in state["projects"] if p["id"] != 1]
r = pg.save(state)
check(r["deleted"] == 1 and "projects:1" not in conn.docs and r["written"] == 1, "удалённый проект — DELETE, порядок обновлён")

print("=== 3. Postgres: чтение восстанавливает порядок и состав ===")
pg2 = store.PgStore("postgresql://x", connect=lambda url: conn)
st = pg2.load()
check([p["id"] for p in st["projects"]] == [2] and st["glossary"] == [{"src": "x"}] and "projects_order" not in st,
      "проекты в порядке документа, служебные ключи не протекают")
check(pg2.save(st)["written"] == 0, "после чтения отпечатки известны — повторная запись пуста")
check(store.PgStore("postgresql://x", connect=lambda url: FakeConn()).load() is None, "пустая база — None")

print("=== 4. Очередь прогонов ===")
pg.save_job({"id": 5, "kind": "full", "status": "running", "tenant": "t", "ids": [1, 2], "stop": False})
pg.save_job({"id": 6, "kind": "full", "status": "done", "tenant": "t", "ids": [], "stop": False})
jobs = pg.load_jobs()
check([j["id"] for j in jobs] == [5, 6] and jobs[0]["ids"] == [1, 2], "прогоны читаются с составом")
pg.delete_job(6)
check([j["id"] for j in pg.load_jobs()] == [5], "удаление")

print("=== 5. main.py: по умолчанию файл, очередь восстанавливается из хранилища ===")
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.pop("DATABASE_URL", None)
import main
check(main.STORE.kind == "file", "без DATABASE_URL — файл")
check(callable(getattr(main, "_restore_jobs", None)) and callable(getattr(main, "_job_persist", None)),
      "хуки очереди на месте")
src = open("backend/main.py", encoding="utf-8").read()
check("os.replace(tmp, STATE_FILE)" not in src, "save_state пишет через STORE, а не сам")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
