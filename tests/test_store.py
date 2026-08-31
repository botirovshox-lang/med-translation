"""Хранилище состояния (`backend/store.py`): документы + разделяемые коллекции строками.

STATE остаётся моделью в памяти; здесь сторожится, что Postgres-бэкенд пишет
ТОЛЬКО изменившееся: правка сегмента — один документ проекта, одобрение
термина — одна строка глоссария, а не десять тысяч. Глоссарий и очередь
кандидатов лежат по строке на запись с эпохой поколения — это фундамент
воркера отдельным процессом: чужую эпоху видно (`stale_collections`),
коллекция перечитывается (`load_rows`), и последующее сохранение не
затирает чужие строки. Postgres подменён записывающим соединением —
сети нет. Ни одного вызова модели.
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
check(fs.stale_collections() == [], "файл: чужих изменений не бывает")


class FakeCur:
    def __init__(self, conn): self.conn = conn; self._rows = []; self._one = None
    def execute(self, sql, params=None):
        self.conn.log.append((" ".join(sql.split()[:4]), params))
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO state_docs"):
            key = params[0]
            if key in self.conn.docs:
                self._one = None                     # ON CONFLICT DO NOTHING
            else:
                self.conn.docs[key] = params[1]
                self.conn.vers[key] = 1
                self._one = (1,)
        elif s.startswith("UPDATE state_docs SET doc"):
            text, key, ver = params
            if self.conn.vers.get(key, 0) == ver:
                self.conn.docs[key] = text
                self.conn.vers[key] = ver + 1
                self._one = (ver + 1,)
            else:
                self._one = None                     # конфликт версий
        elif s.startswith("DELETE FROM state_docs"):
            self.conn.docs.pop(params[0], None)
            self.conn.vers.pop(params[0], None)
        elif s.startswith("INSERT INTO state_rows"):
            coll, gid, tenant, seq, text = params
            self.conn.rows[(coll, gid)] = (seq, text)
        elif s.startswith("DELETE FROM state_rows"):
            self.conn.rows.pop((params[0], params[1]), None)
        elif s.startswith("INSERT INTO epochs") and "GREATEST" in s:
            name, floor, _f2 = params
            self.conn.epochs[name] = max(self.conn.epochs.get(name, 0), floor) + 1
            self._one = (self.conn.epochs[name],)
        elif s.startswith("INSERT INTO epochs"):
            self.conn.epochs[params[0]] = self.conn.epochs.get(params[0], 0) + 1
            self._one = (self.conn.epochs[params[0]],)
        elif s.startswith("SELECT coll, n FROM epochs"):
            self._rows = list(self.conn.epochs.items())
        elif s.startswith("SELECT n FROM epochs"):
            self._one = (self.conn.epochs.get(params[0], 0),)
        elif s.startswith("SELECT key, doc, ver FROM state_docs"):
            self._rows = [(k, json.loads(v), self.conn.vers.get(k, 0)) for k, v in self.conn.docs.items()]
        elif s.startswith("SELECT doc, ver FROM state_docs"):
            k = params[0]
            self._one = ((json.loads(self.conn.docs[k]), self.conn.vers.get(k, 0))
                         if k in self.conn.docs else None)
        elif s.startswith("SELECT coll, doc FROM state_rows"):
            self._rows = [(c, json.loads(t)) for (c, g), (q, t) in sorted(self.conn.rows.items(), key=lambda kv: kv[1][0])]
        elif s.startswith("SELECT doc FROM state_rows"):
            self._rows = [(json.loads(t),) for (c, g), (q, t) in sorted(self.conn.rows.items(), key=lambda kv: kv[1][0]) if c == params[0]]
        elif s.startswith("INSERT INTO spend"):
            if "DO NOTHING" in s:
                t, mo, usd, calls, unp = params
                self.conn.spend.setdefault((t, mo), (float(usd), int(calls), int(unp)))
            else:
                t, mo, usd, unp = params
                cur0 = self.conn.spend.get((t, mo), (0.0, 0, 0))
                self.conn.spend[(t, mo)] = (cur0[0] + float(usd), cur0[1] + 1, cur0[2] + int(unp))
        elif s.startswith("SELECT usd, calls, unpriced"):
            got = self.conn.spend.get((params[0], params[1]))
            self._one = got
        elif s.startswith("INSERT INTO jobs"):
            jid, status, tenant, project, text = params
            self.conn.jobs[jid] = (status, project, text)
        elif s.startswith("DELETE FROM jobs"):
            self.conn.jobs.pop(params[0], None)
        elif s.startswith("UPDATE jobs SET status = 'running'"):
            queued = [i for i, (st, _p, _t) in sorted(self.conn.jobs.items()) if st == "queued"]
            if queued:
                i = queued[0]
                st, pr, t = self.conn.jobs[i]
                self.conn.jobs[i] = ("running", pr, t)
                self._one = (json.loads(t),)
            else:
                self._one = None
        elif s.startswith("UPDATE jobs SET status = 'queued'"):
            out = []
            for i, (st, pr, t) in list(self.conn.jobs.items()):
                if st == "running":
                    self.conn.jobs[i] = ("queued", pr, t)
                    out.append((i,))
            self._rows = out
        elif s.startswith("SELECT id FROM jobs WHERE project"):
            got = [i for i, (st, pr, _t) in sorted(self.conn.jobs.items())
                   if pr == params[0] and st in ("queued", "running")]
            self._one = (got[0],) if got else None
        elif s.startswith("SELECT doc FROM jobs WHERE id"):
            got = self.conn.jobs.get(params[0])
            self._one = (json.loads(got[2]),) if got else None
        elif s.startswith("SELECT doc FROM jobs"):
            self._rows = [(json.loads(t),) for _, (st, pr, t) in sorted(self.conn.jobs.items())]
    def fetchall(self): return self._rows
    def fetchone(self): return self._one
    def close(self): pass


class FakeConn:
    closed = False
    def __init__(self):
        self.log, self.docs, self.rows, self.epochs, self.jobs, self.spend = [], {}, {}, {}, {}, {}
        self.vers = {}
    def cursor(self): return FakeCur(self)
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


print("=== 2. Postgres: пишутся только изменившиеся документы и строки ===")
conn = FakeConn()
pg = store.PgStore("postgresql://x", connect=lambda url: conn)
state = {"projects": [{"id": 2, "title": "B", "segments": [{"id": 1, "target": ""}]},
                      {"id": 1, "title": "A", "segments": []}],
         "glossary": [{"src": "new", "tenant": "default"}, {"src": "old", "tenant": "default"}],
         "tm": [], "users": [{"id": 1}],
         "termQueue": [{"kind": "extract", "src": "c1"}, {"kind": "extract", "src": "c2"}]}
r = pg.save(state)
check(r["written"] == 4 and set(conn.docs) == {"projects:1", "projects:2", "projects_order", "users"},
      "документы — без разделяемых коллекций: %s" % r)
check(r["rows"] == 4 and len(conn.rows) == 4, "глоссарий и очередь ушли строками")
check(all(g.get("gid") and g.get("seq") for g in state["glossary"]), "записи получили gid и seq")
check(state["glossary"][0]["seq"] > state["glossary"][1]["seq"], "глоссарий: голова списка — наибольший seq")
check(state["termQueue"][0]["seq"] < state["termQueue"][1]["seq"], "очередь: порядок добавления")
r = pg.save(state)
check(r["written"] == 0 and r["rows"] == 0, "без изменений — ничего не пишется")
state["glossary"][0]["tgt"] = "changed"
r = pg.save(state)
check(r["rows"] == 1 and r["written"] == 0, "правка одной записи — одна строка")
state["projects"][0]["segments"][0]["target"] = "done"
r = pg.save(state)
check(r["written"] == 1 and r["rows"] == 0, "правка сегмента — один документ проекта")
state["glossary"] = state["glossary"][:1]
r = pg.save(state)
check(r["rows"] == 1 and len([1 for (c, g) in conn.rows if c == "glossary"]) == 1, "удаление записи — DELETE строки")

print("=== 3. Чтение восстанавливает порядок; эпохи видят чужую руку ===")
pg2 = store.PgStore("postgresql://x", connect=lambda url: conn)
st = pg2.load()
check([p["id"] for p in st["projects"]] == [2, 1] and "projects_order" not in st, "проекты в порядке документа")
check([g["src"] for g in st["glossary"]] == ["new"], "глоссарий из строк, новые сверху")
check([c["src"] for c in st["termQueue"]] == ["c1", "c2"], "очередь из строк, в порядке добавления")
check(pg2.save(st)["rows"] == 0 and pg2.save(st)["written"] == 0, "после чтения отпечатки известны")
check(pg2.stale_collections() == [], "эпохи совпали — чужих изменений нет")
st["glossary"].insert(0, {"src": "from-pg2", "tenant": "default"})
pg2.save(st)
check(sorted(pg.stale_collections()) == ["glossary"], "первый процесс видит чужую эпоху глоссария")
items = pg.load_rows("glossary")
check([g["src"] for g in items] == ["from-pg2", "new"], "перечитал: чужая запись сверху")
state["glossary"] = items
check(pg.stale_collections() == [] and pg.save(state)["rows"] == 0,
      "после перечитывания — не затирает чужое и не перезаписывает")

print("=== 4. Миграция: коллекция-документ раскладывается по строкам ===")
conn2 = FakeConn()
conn2.docs["glossary"] = json.dumps([{"src": "стар1"}, {"src": "стар2"}])
conn2.docs["users"] = json.dumps([])
pg3 = store.PgStore("postgresql://x", connect=lambda url: conn2)
st3 = pg3.load()
check([g["src"] for g in st3["glossary"]] == ["стар1", "стар2"], "документ ещё читается")
pg3.save(st3)
check("glossary" not in conn2.docs and len(conn2.rows) == 2, "первое сохранение: строки записаны, документ удалён")
st4 = store.PgStore("postgresql://x", connect=lambda url: conn2).load()
check([g["src"] for g in st4["glossary"]] == ["стар1", "стар2"], "порядок пережил раскладку")

print("=== 4b. Расход — счётчик с прямым инкрементом ===")
pg.add_spend("acme", "2026-08", 0.5)
pg.add_spend("acme", "2026-08", None)
m = pg.get_spend("acme", "2026-08")
check(m["usd"] == 0.5 and m["calls"] == 2 and m["unpriced"] == 1, "инкременты сложились: %s" % m)
check(pg.get_spend("acme", "2026-09") == {"usd": 0.0, "calls": 0, "unpriced": 0}, "пустой месяц — нули")

print("=== 5. Очередь прогонов ===")
pg.save_job({"id": 5, "kind": "full", "status": "running", "tenant": "t", "ids": [1, 2], "stop": False})
pg.save_job({"id": 6, "kind": "full", "status": "done", "tenant": "t", "ids": [], "stop": False})
jobs = pg.load_jobs()
check([j["id"] for j in jobs] == [5, 6] and jobs[0]["ids"] == [1, 2], "прогоны читаются с составом")
pg.delete_job(6)
check([j["id"] for j in pg.load_jobs()] == [5], "удаление")
check(store.PgStore("postgresql://x", connect=lambda url: FakeConn()).load() is None, "пустая база — None")

print("=== 7. Очередь: claim, сброс, стоп, счётчики, эпоха документа ===")
cw = FakeConn()
w1 = store.PgStore("postgresql://x", connect=lambda url: cw)     # «API»
w2 = store.PgStore("postgresql://x", connect=lambda url: cw)     # «воркер»
w1.save_job({"id": 1, "kind": "full", "status": "queued", "tenant": "t", "project": 7, "stop": False})
w1.save_job({"id": 2, "kind": "full", "status": "queued", "tenant": "t", "project": 8, "stop": False})
j = w2.claim_job()
check(j and j["id"] == 1 and j["status"] == "running", "claim берёт первую из очереди и метит running")
check(w1.active_job_for(7) == 1 and w1.active_job_for(8) == 2 and w1.active_job_for(9) is None,
      "active_job_for видит идущую и ждущую")
j2 = w2.claim_job()
check(j2 and j2["id"] == 2, "вторая задача — второй claim, не та же")
check(w2.claim_job() is None, "очередь пуста — None")
check(w2.reset_running_jobs() == [1, 2], "рестарт воркера возвращает running в очередь")
got = w1.get_job(1)
got["stop"] = True
w1.save_job(got)
check(w2.get_job(1)["stop"] is True, "стоп-флаг доезжает через таблицу")
a = w1.next_counter("autoBatchSeq", 7)
b = w2.next_counter("autoBatchSeq", 0)
check(a == 8 and b == 9, "счётчик атомарен и не опускается ниже floor: %s, %s" % (a, b))

print("=== 7b. Эпоха документа: API перечитывает проект после прогона ===")
st_a = {"projects": [{"id": 7, "title": "A", "segments": []}], "glossary": [], "termQueue": [], "tm": []}
w1.save(st_a)
st_b = w2.load()
st_b["projects"][0]["segments"].append({"id": 1, "target": "готово"})
w2.save(st_b)
w2.bump_epoch("doc:projects:7")
stale = w1.stale_collections()
check("doc:projects:7" in stale, "API видит эпоху проекта: %s" % stale)
doc = w1.load_doc("projects:7")
check(doc["segments"][0]["target"] == "готово", "документ перечитан с работой прогона")
check("doc:projects:7" not in w1.stale_collections(), "после перечитывания эпоха усвоена")

print("=== 7c. Конфликт версий не затирает молча ===")
st_a["projects"][0] = doc                     # w1 в курсе свежей версии
w1.save(st_a)
st_b2 = w2.load_doc("projects:7")
st_a["projects"][0]["title"] = "A-api"
w1.save(st_a)                                  # w1 пишет поверх — версия уехала
st_b["projects"][0]["title"] = "A-worker"
try:
    w2.save(st_b)
    check(False, "чужая рука превращается в DocConflict")
except store.DocConflict as e:
    check(e.key == "projects:7", "чужая рука превращается в DocConflict")

print("=== 6. main.py: по умолчанию файл, синхронизация на месте ===")
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.pop("DATABASE_URL", None)
import main
check(main.STORE.kind == "file", "без DATABASE_URL — файл")
check(callable(getattr(main, "_restore_jobs", None)) and callable(getattr(main, "_sync_shared", None)),
      "хуки очереди и синхронизации на месте")
check(callable(getattr(main, "_job_execute", None)) and callable(getattr(main, "_guard_project_write", None))
      and not main.EXTERNAL_WORKER, "исполнение задачи вынесено, охрана есть, локально воркер выключен")
check(os.path.exists("backend/worker.py") and os.path.exists("deploy/medcat-worker.service"),
      "воркер и юнит на месте")
src = open("backend/main.py", encoding="utf-8").read()
check("os.replace(tmp, STATE_FILE)" not in src, "save_state пишет через STORE, а не сам")
check("run_in_threadpool(_sync_shared)" in src.split("def require_token")[1].split("def ")[0],
      "мидлварь подтягивает чужие изменения коллекций")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
