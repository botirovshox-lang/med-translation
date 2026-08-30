"""Хранилище состояния: файл (по умолчанию) или PostgreSQL (`DATABASE_URL`).

`STATE` остаётся МОДЕЛЬЮ в памяти процесса — вся логика main.py её и читает.
Меняется только то, куда она пишется и откуда поднимается:

  файл       — state.json целиком, атомарно (как было);
  postgres   — таблица документов `state_docs(key, doc jsonb)`: каждый проект —
               свой документ (`projects:{id}`), остальные верхние ключи
               (glossary, tm, users, …) — по документу. Пишутся ТОЛЬКО
               изменившиеся документы (сверка по отпечатку JSON), так что
               подтверждение одного сегмента больше не переписывает 12 МБ.
               Очередь прогонов лежит в `jobs` и переживает рестарт.

Инварианты CLAUDE.md не меняются: воркер один, все мутации заканчиваются
`save_state`, писать на диск можно только в data/. Драйвер — psycopg 3;
без него и без DATABASE_URL молча остаётся файл.
"""
import hashlib
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_PREFIX = "projects:"
ORDER_KEY = "projects_order"


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
        return {"written": 1, "bytes": len(payload)}

    # Очередь прогонов файл не хранит — как и раньше.
    def save_job(self, job: dict) -> None:
        pass

    def delete_job(self, jid: int) -> None:
        pass

    def load_jobs(self) -> list:
        return []


class PgStore:
    kind = "pg"

    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS state_docs ("
        " key TEXT PRIMARY KEY, doc JSONB NOT NULL,"
        " updated TIMESTAMPTZ NOT NULL DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS jobs ("
        " id INTEGER PRIMARY KEY, status TEXT NOT NULL, tenant TEXT,"
        " doc JSONB NOT NULL, updated TIMESTAMPTZ NOT NULL DEFAULT now())",
    )

    def __init__(self, url: str, connect=None):
        self.url = url
        self._lock = threading.Lock()
        self._hashes: dict = {}          # key -> отпечаток последнего записанного документа
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
            if k != "projects":
                docs[k] = v
        return docs

    def load(self) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT key, doc FROM state_docs")
            rows = cur.fetchall()
        if not rows:
            return None
        docs = {}
        for key, doc in rows:
            if isinstance(doc, str):
                doc = json.loads(doc)
            docs[key] = doc
            self._hashes[key] = _fp(_dumps(doc))
        projects_by_id = {int(k[len(PROJECT_PREFIX):]): v for k, v in docs.items() if k.startswith(PROJECT_PREFIX)}
        order = [i for i in (docs.get(ORDER_KEY) or []) if i in projects_by_id]
        order += [i for i in projects_by_id if i not in order]
        state = {k: v for k, v in docs.items() if not k.startswith(PROJECT_PREFIX) and k != ORDER_KEY}
        state["projects"] = [projects_by_id[i] for i in order]
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
        if not changed and not gone:
            return {"written": 0, "deleted": 0, "bytes": 0}
        with self._cursor() as cur:
            for key in changed:
                cur.execute(
                    "INSERT INTO state_docs (key, doc, updated) VALUES (%s, %s::jsonb, now()) "
                    "ON CONFLICT (key) DO UPDATE SET doc = EXCLUDED.doc, updated = now()",
                    (key, texts[key][0]))
            for key in gone:
                cur.execute("DELETE FROM state_docs WHERE key = %s", (key,))
        for key in changed:
            self._hashes[key] = texts[key][1]
        for key in gone:
            self._hashes.pop(key, None)
        return {"written": len(changed), "deleted": len(gone),
                "bytes": sum(len(texts[k][0]) for k in changed)}

    # ── прогоны ──
    def save_job(self, job: dict) -> None:
        doc = {k: v for k, v in job.items() if k != "usage_sink"}
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, status, tenant, doc, updated) VALUES (%s, %s, %s, %s::jsonb, now()) "
                "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, doc = EXCLUDED.doc, updated = now()",
                (job["id"], job.get("status"), job.get("tenant"), _dumps(doc)))

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
