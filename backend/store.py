"""Хранилище состояния: файл (по умолчанию) или PostgreSQL (`DATABASE_URL`).

`STATE` остаётся МОДЕЛЬЮ в памяти процесса — вся логика main.py её и читает.
Меняется только то, куда она пишется и откуда поднимается:

  файл       — state.json целиком, атомарно (как было);
  postgres   — три вида записей:
    state_docs  каждый проект — свой документ (`projects:{id}`), остальные
                верхние ключи — по документу; пишутся ТОЛЬКО изменившиеся
                (сверка по отпечатку JSON);
    state_rows  РАЗДЕЛЯЕМЫЕ коллекции (глоссарий, очередь кандидатов) —
                по СТРОКЕ на запись. Это подготовка к воркеру отдельным
                процессом: два процесса, пишущие один документ, затирали бы
                друг друга целиком, а по строкам каждый трогает только то,
                что менял сам. Запись получает `gid` (случайный ключ) и `seq`
                (порядок: глоссарий живёт «новые сверху», очередь — «в конец»);
    epochs      счётчик поколения каждой коллекции. Процесс, изменивший
                строки, поднимает эпоху; остальные видят чужую эпоху и
                перечитывают коллекцию (`stale_collections` → `load_rows`).

Очередь прогонов лежит в `jobs` и переживает рестарт. Инварианты CLAUDE.md
не меняются: все мутации заканчиваются `save_state`; соединение с базой
не держится между транзакциями (сеанс с разобранными JSONB весил сотни
мегабайт в простое, а база локальная). Без DATABASE_URL — файл, и коллекции
живут внутри state.json, как раньше.
"""
import hashlib
import json
import os
import secrets
import sys
import threading
from pathlib import Path
from typing import Optional

class DocConflict(Exception):
    """Документ изменил кто-то другой между нашим чтением и записью.

    Ловится в save_state: конфликтный документ перечитывается, ЛОКАЛЬНЫЕ
    правки этого документа теряются (об этом кричит журнал), остальное
    сохраняется повтором. Это сеть безопасности: штатно конфликтов нет —
    ручные правки проекта закрыты 409, пока по нему идёт внешний прогон,
    а пакетные команды такие проекты пропускают поимённо."""
    def __init__(self, key):
        super().__init__(key)
        self.key = key


PROJECT_PREFIX = "projects:"
ORDER_KEY = "projects_order"

# Коллекции, разложенные по строкам, и закон их порядка:
#   desc — новые записи идут В НАЧАЛО списка (glossary, tm: insert(0));
#   asc  — новые идут В КОНЕЦ (termQueue, audit, runCosts: append).
ROW_COLLECTIONS = {"glossary": "desc", "termQueue": "asc", "tm": "desc",
                   "audit": "asc", "runCosts": "asc", "autoBatches": "asc"}


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fp(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class FileStore:
    kind = "file"

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> dict:
        payload = json.dumps(state, ensure_ascii=False)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        return {"written": 1, "rows": 0, "deleted": 0, "bytes": len(payload)}

    # Один процесс, один файл: чужих изменений не бывает.
    def stale_collections(self) -> list:
        return []

    def load_rows(self, coll: str) -> list:
        raise RuntimeError("файловое хранилище не хранит коллекции строками")

    def load_doc(self, key: str):
        return None

    def bump_epoch(self, name: str) -> int:
        return 0

    def next_counter(self, name: str, floor: int = 0) -> int:
        raise RuntimeError("счётчик — только в базе; файл считает в STATE")

    # Очередь прогонов файл не хранит — как и раньше.
    def save_job(self, job: dict) -> None:
        pass

    def delete_job(self, jid: int) -> None:
        pass

    def load_jobs(self) -> list:
        return []

    def claim_job(self):
        return None

    def reset_running_jobs(self) -> list:
        return []

    def get_job(self, jid: int):
        return None

    def active_job_for(self, pid: int):
        return None


class PgStore:
    kind = "pg"

    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS state_docs ("
        " key TEXT PRIMARY KEY, doc JSONB NOT NULL,"
        " updated TIMESTAMPTZ NOT NULL DEFAULT now())",
        # ver — оптимистическая блокировка документов: запись сверяет версию,
        # с которой читала, и чужая рука превращается в DocConflict, а не
        # в молча затёртый документ.
        "ALTER TABLE state_docs ADD COLUMN IF NOT EXISTS ver BIGINT NOT NULL DEFAULT 0",
        "CREATE TABLE IF NOT EXISTS state_rows ("
        " coll TEXT NOT NULL, gid TEXT NOT NULL, tenant TEXT, seq BIGINT NOT NULL,"
        " doc JSONB NOT NULL, updated TIMESTAMPTZ NOT NULL DEFAULT now(),"
        " PRIMARY KEY (coll, gid))",
        "CREATE INDEX IF NOT EXISTS state_rows_coll_seq ON state_rows (coll, seq)",
        "CREATE TABLE IF NOT EXISTS epochs ("
        " coll TEXT PRIMARY KEY, n BIGINT NOT NULL DEFAULT 0)",
        # Расход — НЕ документ и не строка-снимок, а СЧЁТЧИК с прямым
        # инкрементом: два процесса, пишущие снимок счётчика, теряли бы
        # приращения друг друга, а UPDATE ... SET usd = usd + delta — нет.
        "CREATE TABLE IF NOT EXISTS spend ("
        " tenant TEXT NOT NULL, month TEXT NOT NULL,"
        " usd DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " calls BIGINT NOT NULL DEFAULT 0, unpriced BIGINT NOT NULL DEFAULT 0,"
        " PRIMARY KEY (tenant, month))",
        "CREATE TABLE IF NOT EXISTS jobs ("
        " id INTEGER PRIMARY KEY, status TEXT NOT NULL, tenant TEXT,"
        " doc JSONB NOT NULL, updated TIMESTAMPTZ NOT NULL DEFAULT now())",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS project INTEGER",
    )

    def __init__(self, url: str, connect=None):
        self.url = url
        self._lock = threading.Lock()
        self._hashes: dict = {}                     # ключ документа -> отпечаток
        self._vers: dict = {}                       # ключ документа -> версия при чтении
        self._row_hashes = {c: {} for c in ROW_COLLECTIONS}   # coll -> {gid: отпечаток}
        self._row_seq = {c: 0 for c in ROW_COLLECTIONS}       # наибольший выданный seq
        self._epochs = {c: 0 for c in ROW_COLLECTIONS}        # поколение, которое мы видели
        self._connect = connect or self._default_connect
        self._conn = None
        with self._cursor() as cur:
            for stmt in self.SCHEMA:
                cur.execute(stmt)

    @staticmethod
    def _default_connect(url):
        import psycopg
        return psycopg.connect(url, autocommit=False)

    def _get(self):
        if self._conn is None or getattr(self._conn, "closed", False):
            self._conn = self._connect(self.url)
        return self._conn

    class _Tx:
        """Курсор с фиксацией; на ошибке — откат и сброс соединения,
        чтобы следующий вызов переподключился, а не упирался в мёртвый сокет."""
        def __init__(self, store):
            self.store = store

        def __enter__(self):
            self.store._lock.acquire()
            try:
                self.conn = self.store._get()
                self.cur = self.conn.cursor()
                return self.cur
            except Exception:
                self.store._lock.release()
                raise

        def __exit__(self, et, ev, tb):
            try:
                if et is None:
                    self.conn.commit()
                else:
                    try:
                        self.conn.rollback()
                    except Exception:
                        pass
                    self.store._conn = None
                try:
                    self.cur.close()
                except Exception:
                    pass
                # Соединение не держим между транзакциями: серверный процесс
                # Postgres с разобранными JSONB-документами весит сотни
                # мегабайт в простое, а база локальная — переподключение
                # стоит миллисекунды. Память дороже.
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.store._conn = None
            finally:
                self.store._lock.release()
            return False

    def _cursor(self):
        return PgStore._Tx(self)

    # ── документы ──
    @staticmethod
    def _docs_of(state: dict) -> dict:
        docs = {}
        order = []
        for p in state.get("projects") or []:
            docs[PROJECT_PREFIX + str(p["id"])] = p
            order.append(p["id"])
        docs[ORDER_KEY] = order
        for k, v in state.items():
            if k != "projects" and k != "spend" and k not in ROW_COLLECTIONS:
                docs[k] = v
        return docs

    def _ensure_ids(self, coll: str, items: list) -> None:
        """gid и seq — свойства ХРАНИЛИЩА, но живут в самой записи: она ходит
        между процессами и сессиями, и внешний реестр однажды разошёлся бы
        с данными. Запись без gid — новая: глоссарь растёт «в голову» (новый
        получает НАИБОЛЬШИЙ seq), очередь — «в хвост» (наименьший из новых
        идёт первым). Уже пронумерованное не перенумеровывается никогда —
        иначе каждое сохранение переписывало бы все строки."""
        for it in items:
            if it.get("seq") is not None:
                self._row_seq[coll] = max(self._row_seq[coll], int(it["seq"]))
        fresh = [it for it in items if not it.get("gid")]
        if not fresh:
            return
        if ROW_COLLECTIONS[coll] == "desc":
            fresh = list(reversed(fresh))       # головной элемент получит наибольший seq
        for it in fresh:
            self._row_seq[coll] += 1
            it["gid"] = secrets.token_hex(12)
            it["seq"] = self._row_seq[coll]

    def load(self) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT key, doc, ver FROM state_docs")
            doc_rows = cur.fetchall()
            cur.execute("SELECT coll, doc FROM state_rows ORDER BY seq")
            row_rows = cur.fetchall()
            cur.execute("SELECT coll, n FROM epochs")
            for coll, n in cur.fetchall():
                if coll in ROW_COLLECTIONS or coll.startswith("doc:"):
                    self._epochs[coll] = n
        if not doc_rows and not row_rows:
            return None
        docs = {}
        for key, doc, ver in doc_rows:
            if isinstance(doc, str):
                doc = json.loads(doc)
            docs[key] = doc
            self._hashes[key] = _fp(_dumps(doc))
            self._vers[key] = ver
        by_coll = {c: [] for c in ROW_COLLECTIONS}
        for coll, doc in row_rows:
            if isinstance(doc, str):
                doc = json.loads(doc)
            if coll in by_coll:
                by_coll[coll].append(doc)
        # Расход, приехавший прежним документом, — в таблицу-счётчик.
        spend_doc = docs.pop("spend", None)
        if spend_doc:
            with self._cursor() as cur:
                for tenant, months in spend_doc.items():
                    for month, m in (months or {}).items():
                        cur.execute(
                            "INSERT INTO spend (tenant, month, usd, calls, unpriced) "
                            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant, month) DO NOTHING",
                            (tenant, month, float(m.get("usd") or 0),
                             int(m.get("calls") or 0), int(m.get("unpriced") or 0)))
                cur.execute("DELETE FROM state_docs WHERE key = %s", ("spend",))
            self._hashes.pop("spend", None)
        projects_by_id = {int(k[len(PROJECT_PREFIX):]): v for k, v in docs.items()
                          if k.startswith(PROJECT_PREFIX)}
        order = [i for i in (docs.get(ORDER_KEY) or []) if i in projects_by_id]
        order += [i for i in projects_by_id if i not in order]
        state = {k: v for k, v in docs.items()
                 if not k.startswith(PROJECT_PREFIX) and k != ORDER_KEY}
        state["projects"] = [projects_by_id[i] for i in order]
        for coll, direction in ROW_COLLECTIONS.items():
            if by_coll[coll]:
                items = by_coll[coll]
                if direction == "desc":
                    items = list(reversed(items))
                state[coll] = items
                self._row_hashes[coll] = {it["gid"]: _fp(_dumps(it)) for it in items}
                self._row_seq[coll] = max(int(it.get("seq") or 0) for it in items)
            # Строк нет, а документ есть — состояние ещё в прежнем виде
            # (до раскладки): отдаём документ, первое сохранение разложит.
        return state

    def save(self, state: dict) -> dict:
        docs = self._docs_of(state)
        changed, texts = [], {}
        for key, doc in docs.items():
            text = _dumps(doc)
            fp = _fp(text)
            if self._hashes.get(key) != fp:
                changed.append(key)
                texts[key] = (text, fp)
        gone = [k for k in self._hashes if k.startswith(PROJECT_PREFIX) and k not in docs]

        row_ops = {}          # coll -> (upserts:[(gid, tenant, seq, text, fp)], deletes:[gid])
        for coll in ROW_COLLECTIONS:
            items = state.get(coll)
            if items is None:
                continue
            self._ensure_ids(coll, items)
            known = self._row_hashes[coll]
            ups, seen = [], set()
            for it in items:
                gid = it["gid"]
                seen.add(gid)
                text = _dumps(it)
                fp = _fp(text)
                if known.get(gid) != fp:
                    ups.append((gid, it.get("tenant"), int(it.get("seq") or 0), text, fp))
            dels = [gid for gid in known if gid not in seen]
            if ups or dels or (coll in self._hashes):
                row_ops[coll] = (ups, dels)

        if not changed and not gone and not row_ops:
            return {"written": 0, "rows": 0, "deleted": 0, "bytes": 0}

        bumped, newver = {}, {}
        with self._cursor() as cur:
            for key in changed:
                if key in self._vers:
                    cur.execute(
                        "UPDATE state_docs SET doc = %s::jsonb, updated = now(), ver = ver + 1 "
                        "WHERE key = %s AND ver = %s RETURNING ver",
                        (texts[key][0], key, self._vers[key]))
                    got = cur.fetchone()
                    if not got:
                        raise DocConflict(key)
                    newver[key] = got[0]
                else:
                    cur.execute(
                        "INSERT INTO state_docs (key, doc, updated, ver) "
                        "VALUES (%s, %s::jsonb, now(), 1) ON CONFLICT (key) DO NOTHING RETURNING ver",
                        (key, texts[key][0]))
                    got = cur.fetchone()
                    if not got:
                        raise DocConflict(key)
                    newver[key] = got[0]
            for key in gone:
                cur.execute("DELETE FROM state_docs WHERE key = %s", (key,))
            for coll, (ups, dels) in row_ops.items():
                for gid, tenant, seq, text, _f in ups:
                    cur.execute(
                        "INSERT INTO state_rows (coll, gid, tenant, seq, doc, updated) "
                        "VALUES (%s, %s, %s, %s, %s::jsonb, now()) "
                        "ON CONFLICT (coll, gid) DO UPDATE SET doc = EXCLUDED.doc, "
                        " tenant = EXCLUDED.tenant, seq = EXCLUDED.seq, updated = now()",
                        (coll, gid, tenant, seq, text))
                for gid in dels:
                    cur.execute("DELETE FROM state_rows WHERE coll = %s AND gid = %s", (coll, gid))
                if ups or dels:
                    cur.execute(
                        "INSERT INTO epochs (coll, n) VALUES (%s, 1) "
                        "ON CONFLICT (coll) DO UPDATE SET n = epochs.n + 1 RETURNING n",
                        (coll,))
                    bumped[coll] = cur.fetchone()[0]
                if coll in self._hashes:
                    # Прежний документ-целиком этой коллекции больше не нужен:
                    # источник правды теперь строки.
                    cur.execute("DELETE FROM state_docs WHERE key = %s", (coll,))

        for key in changed:
            self._hashes[key] = texts[key][1]
            self._vers[key] = newver[key]
        for key in gone:
            self._hashes.pop(key, None)
            self._vers.pop(key, None)
        rows_written = 0
        for coll, (ups, dels) in row_ops.items():
            for gid, _t, _s, _txt, fp in ups:
                self._row_hashes[coll][gid] = fp
            for gid in dels:
                self._row_hashes[coll].pop(gid, None)
            rows_written += len(ups) + len(dels)
            self._hashes.pop(coll, None)
            if coll in bumped:
                self._epochs[coll] = bumped[coll]
        return {"written": len(changed), "rows": rows_written, "deleted": len(gone),
                "bytes": sum(len(texts[k][0]) for k in changed)}

    # ── синхронизация между процессами ──
    def stale_collections(self) -> list:
        """Коллекции, чью эпоху поднял КТО-ТО ДРУГОЙ: наша запись обновляет
        локальную эпоху сама, поэтому расхождение означает чужую руку."""
        with self._cursor() as cur:
            cur.execute("SELECT coll, n FROM epochs")
            rows = cur.fetchall()
        out = []
        for coll, n in rows:
            if coll in ROW_COLLECTIONS:
                if n != self._epochs.get(coll, 0):
                    out.append(coll)
            elif coll.startswith("doc:"):
                if self._epochs.get(coll) != n:
                    out.append(coll)
        return out

    def load_rows(self, coll: str) -> list:
        """Перечитать коллекцию строк (после чужой эпохи) и запомнить её
        отпечатки — иначе следующее сохранение перезаписало бы всё заново."""
        assert coll in ROW_COLLECTIONS, coll
        with self._cursor() as cur:
            cur.execute("SELECT doc FROM state_rows WHERE coll = %s ORDER BY seq", (coll,))
            rows = cur.fetchall()
            cur.execute("SELECT n FROM epochs WHERE coll = %s", (coll,))
            got = cur.fetchone()
        items = [json.loads(d) if isinstance(d, str) else d for (d,) in rows]
        if ROW_COLLECTIONS[coll] == "desc":
            items = list(reversed(items))
        self._row_hashes[coll] = {it["gid"]: _fp(_dumps(it)) for it in items}
        self._row_seq[coll] = max([int(it.get("seq") or 0) for it in items], default=self._row_seq[coll])
        if got:
            self._epochs[coll] = got[0]
        return items

    def load_doc(self, key: str):
        """Перечитать один документ (после чужой эпохи doc:<key>).
        None — документа больше нет."""
        with self._cursor() as cur:
            cur.execute("SELECT doc, ver FROM state_docs WHERE key = %s", (key,))
            got = cur.fetchone()
            cur.execute("SELECT n FROM epochs WHERE coll = %s", ("doc:" + key,))
            ep = cur.fetchone()
        if ep:
            self._epochs["doc:" + key] = ep[0]
        if not got:
            self._hashes.pop(key, None)
            self._vers.pop(key, None)
            return None
        doc = json.loads(got[0]) if isinstance(got[0], str) else got[0]
        self._hashes[key] = _fp(_dumps(doc))
        self._vers[key] = got[1]
        return doc

    def bump_epoch(self, name: str) -> int:
        """Поднять эпоху вручную — воркер зовёт после прогона для doc:projects:N,
        чтобы API перечитал готовый проект."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO epochs (coll, n) VALUES (%s, 1) "
                "ON CONFLICT (coll) DO UPDATE SET n = epochs.n + 1 RETURNING n", (name,))
            n = cur.fetchone()[0]
        self._epochs[name] = n
        return n

    def next_counter(self, name: str, floor: int = 0) -> int:
        """Атомарный счётчик (номера пачек): два процесса не выдадут один номер.
        floor — прежнее значение из state.json, ниже него не опускаемся."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO epochs (coll, n) VALUES (%s, %s + 1) "
                "ON CONFLICT (coll) DO UPDATE SET n = GREATEST(epochs.n, %s) + 1 RETURNING n",
                ("ctr:" + name, floor, floor))
            return cur.fetchone()[0]

    # ── расход: счётчик с прямым инкрементом ──
    def add_spend(self, tenant: str, month: str, cost) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO spend (tenant, month, usd, calls, unpriced) "
                "VALUES (%s, %s, %s, 1, %s) "
                "ON CONFLICT (tenant, month) DO UPDATE SET "
                " usd = spend.usd + EXCLUDED.usd, calls = spend.calls + 1,"
                " unpriced = spend.unpriced + EXCLUDED.unpriced",
                (tenant, month, float(cost or 0), 0 if cost is not None else 1))

    def get_spend(self, tenant: str, month: str) -> dict:
        with self._cursor() as cur:
            cur.execute("SELECT usd, calls, unpriced FROM spend WHERE tenant = %s AND month = %s",
                        (tenant, month))
            got = cur.fetchone()
        if not got:
            return {"usd": 0.0, "calls": 0, "unpriced": 0}
        return {"usd": float(got[0]), "calls": int(got[1]), "unpriced": int(got[2])}

    # ── прогоны ──
    def save_job(self, job: dict) -> None:
        doc = {k: v for k, v in job.items() if k != "usage_sink"}
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, status, tenant, project, doc, updated) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, now()) "
                "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status,"
                " project = EXCLUDED.project, doc = EXCLUDED.doc, updated = now()",
                (job["id"], job.get("status"), job.get("tenant"), job.get("project"), _dumps(doc)))

    def claim_job(self) -> Optional[dict]:
        """Забрать одну задачу из очереди. SKIP LOCKED: два воркера не возьмут
        одну и ту же, взятая помечается running в той же транзакции."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'running', updated = now() WHERE id = ("
                " SELECT id FROM jobs WHERE status = 'queued' ORDER BY id"
                " LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING doc")
            got = cur.fetchone()
        if not got:
            return None
        doc = json.loads(got[0]) if isinstance(got[0], str) else got[0]
        doc["status"] = "running"
        return doc

    def reset_running_jobs(self) -> list:
        """running после рестарта воркера — оборванные: назад в очередь."""
        with self._cursor() as cur:
            cur.execute("UPDATE jobs SET status = 'queued', updated = now() "
                        "WHERE status = 'running' RETURNING id")
            rows = cur.fetchall()
        return [r[0] for r in rows]

    def get_job(self, jid: int) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT doc FROM jobs WHERE id = %s", (jid,))
            got = cur.fetchone()
        if not got:
            return None
        return json.loads(got[0]) if isinstance(got[0], str) else got[0]

    def active_job_for(self, pid: int) -> Optional[int]:
        with self._cursor() as cur:
            cur.execute("SELECT id FROM jobs WHERE project = %s AND status IN ('queued','running') "
                        "ORDER BY id LIMIT 1", (pid,))
            got = cur.fetchone()
        return got[0] if got else None

    def delete_job(self, jid: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = %s", (jid,))

    def load_jobs(self) -> list:
        with self._cursor() as cur:
            cur.execute("SELECT doc FROM jobs ORDER BY id")
            rows = cur.fetchall()
        out = []
        for (doc,) in rows:
            out.append(json.loads(doc) if isinstance(doc, str) else doc)
        return out


def open_store(database_url: Optional[str], state_file: Path):
    """Postgres при DATABASE_URL и рабочем драйвере, иначе файл. Отказ
    соединения — громкий: молча упасть на файл значит однажды писать
    в две стороны и не знать, где правда."""
    url = (database_url or "").strip()
    if not url:
        return FileStore(state_file)
    try:
        st = PgStore(url)
        print(f"[backend] хранилище: PostgreSQL ({url.split('@')[-1]})", file=sys.stderr)
        return st
    except Exception as e:
        raise RuntimeError(f"DATABASE_URL задан, но подключиться не удалось: {e}") from e
