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


def _as_doc(v):
    return json.loads(v) if isinstance(v, str) else v


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

    def queued_summary(self) -> list:
        return []

    def reset_running_jobs(self) -> list:
        return []

    def get_job(self, jid: int):
        return None

    def active_job_for(self, pid: int):
        return None


class FilePayOrders:
    """Заказы файлового хранилища — СВОИМ файлом рядом с state.json, с атомарной
    записью и исключением при сбое: тот же закон, что у таблицы `pay_orders`
    (колбэк оплаты обязан узнать, что заказ не записан)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"seq": 1000, "orders": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def pay_put(self, doc: dict) -> None:
        with self._lock:
            data = self._load()
            data["orders"][str(int(doc["id"]))] = doc
            self._save(data)

    def pay_get(self, oid: int) -> Optional[dict]:
        with self._lock:
            got = self._load()["orders"].get(str(int(oid)))
        return json.loads(json.dumps(got)) if got else None

    def pay_list(self, tenant: Optional[str] = None, limit: int = 1000) -> list:
        with self._lock:
            orders = list(self._load()["orders"].values())
        orders = [o for o in orders if tenant is None or o.get("tenant") == tenant]
        orders.sort(key=lambda o: -int(o["id"]))
        return json.loads(json.dumps(orders[:int(limit)]))

    def pay_next_id(self) -> int:
        with self._lock:
            data = self._load()
            data["seq"] = int(data.get("seq") or 1000) + 1
            self._save(data)
            return data["seq"]


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
        # Журнал токенов по дням — для виртуального пересчёта в админке
        # («сколько стоило бы другими моделями»). Счётчик с инкрементом по той
        # же причине, что `spend`: пишут оба процесса. uid '' — автор неизвестен,
        # model '?' — строка перенесена из истории прогонов (там модели по шагам нет).
        "CREATE TABLE IF NOT EXISTS usage_daily ("
        " day TEXT NOT NULL, tenant TEXT NOT NULL, uid TEXT NOT NULL,"
        " step TEXT NOT NULL, model TEXT NOT NULL,"
        " calls BIGINT NOT NULL DEFAULT 0, tin BIGINT NOT NULL DEFAULT 0,"
        " cached BIGINT NOT NULL DEFAULT 0, tout BIGINT NOT NULL DEFAULT 0,"
        " think BIGINT NOT NULL DEFAULT 0, usd DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " unpriced BIGINT NOT NULL DEFAULT 0,"
        " PRIMARY KEY (day, tenant, uid, step, model))",
        # Факт расхода по ПРОЕКТУ (админка «Прогоны»): счётчик с инкрементом
        # по той же причине, что `spend`, — одиночные вызовы пишет API,
        # прогоны — воркер. В документ проекта его класть нельзя: во время
        # прогона документ принадлежит воркеру, и приращение API ушло бы
        # в DocConflict. Строка переживает удаление проекта — это деньги.
        "CREATE TABLE IF NOT EXISTS project_spend ("
        " tenant TEXT NOT NULL, project INTEGER NOT NULL,"
        " usd DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " calls BIGINT NOT NULL DEFAULT 0, unpriced BIGINT NOT NULL DEFAULT 0,"
        " runs BIGINT NOT NULL DEFAULT 0,"
        " est_usd DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " est_actual_usd DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " bulk BIGINT NOT NULL DEFAULT 0,"
        " PRIMARY KEY (tenant, project))",
        # Счётчики событий по дням («где теряем деньги, что чинить»):
        # тот же закон, что у `spend` и `usage_daily` — ИНКРЕМЕНТ, а не
        # снимок: пишут оба процесса (API и воркер), и снимок терял бы
        # приращения. Ключ перечислим по построению (день × организация ×
        # код из закрытого набора), поэтому таблица растёт десятками строк
        # в день, а не строкой на запрос.
        # Расход по ПРОЕКТУ и ДНЮ (админка «Расход по проектам» за период):
        # `project_spend` помнит только сумму за всё время, `usage_daily` —
        # день без проекта. Тот же закон инкремента: пишут оба процесса.
        # Проект 0 — вызов вне проекта (очередь терминов, смета скана).
        "CREATE TABLE IF NOT EXISTS project_daily ("
        " day TEXT NOT NULL, tenant TEXT NOT NULL, project INTEGER NOT NULL,"
        " step TEXT NOT NULL,"
        " usd DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " calls BIGINT NOT NULL DEFAULT 0, unpriced BIGINT NOT NULL DEFAULT 0,"
        " pages DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " minutes DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " PRIMARY KEY (day, tenant, project, step))",
        # Заказы на оплату — СВОЕЙ таблицей с прямой записью, а не документом
        # STATE: `save_state` глотает ошибки, и колбэк платёжной системы
        # услышал бы «зачислено» про заказ, которого в базе нет. Здесь сбой
        # записи — исключение, и поставщик получает отказ и повторяет.
        "CREATE TABLE IF NOT EXISTS pay_orders ("
        " id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, status TEXT NOT NULL,"
        " doc JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now(),"
        " updated TIMESTAMPTZ NOT NULL DEFAULT now())",
        "CREATE INDEX IF NOT EXISTS pay_orders_tenant ON pay_orders (tenant)",
        "CREATE INDEX IF NOT EXISTS project_daily_day ON project_daily (day)",
        "CREATE TABLE IF NOT EXISTS events ("
        " day TEXT NOT NULL, tenant TEXT NOT NULL, code TEXT NOT NULL,"
        " n BIGINT NOT NULL DEFAULT 0,"
        " ms_sum DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " ms_max DOUBLE PRECISION NOT NULL DEFAULT 0,"
        " slow BIGINT NOT NULL DEFAULT 0,"
        " PRIMARY KEY (day, tenant, code))",
        "CREATE INDEX IF NOT EXISTS events_day ON events (day)",
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
        self._base_keys: set = set()                # документы, чей текст помним (см. keep_base)
        self._base_text: dict = {}                  # ключ -> текст при последнем чтении/записи
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
            if key in self._base_keys:
                self._base_text[key] = texts[key][0]
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
        text = _dumps(doc)
        self._hashes[key] = _fp(text)
        self._vers[key] = got[1]
        if key in self._base_keys:
            self._base_text[key] = text
        return doc

    def keep_base(self, key: str, on: bool = True) -> None:
        """Помнить ТЕКСТ документа таким, каким мы его последний раз прочли
        или записали, — базу для трёхсторонней сверки при `DocConflict`.
        Только для названных ключей: воркер держит так документ проекта своего
        прогона, а копия всего состояния в памяти ему не нужна."""
        if on:
            self._base_keys.add(key)
        else:
            self._base_keys.discard(key)
            self._base_text.pop(key, None)

    def base_doc(self, key: str):
        text = self._base_text.get(key)
        return json.loads(text) if text is not None else None

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

    # ── расход по проекту: тот же счётчик с инкрементом ──
    def add_project_spend(self, tenant: str, project: int, usd: float, calls: int,
                          unpriced: int, runs: int, est_usd: float, est_actual_usd: float,
                          bulk: int = 0) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO project_spend (tenant, project, usd, calls, unpriced, runs,"
                " est_usd, est_actual_usd, bulk) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant, project) DO UPDATE SET "
                " usd = project_spend.usd + EXCLUDED.usd,"
                " calls = project_spend.calls + EXCLUDED.calls,"
                " unpriced = project_spend.unpriced + EXCLUDED.unpriced,"
                " runs = project_spend.runs + EXCLUDED.runs,"
                " est_usd = project_spend.est_usd + EXCLUDED.est_usd,"
                " est_actual_usd = project_spend.est_actual_usd + EXCLUDED.est_actual_usd,"
                " bulk = project_spend.bulk + EXCLUDED.bulk",
                (tenant, int(project), float(usd or 0), int(calls), int(unpriced), int(runs),
                 float(est_usd or 0), float(est_actual_usd or 0), int(bulk)))

    def project_spend_rows(self, tenant: Optional[str] = None) -> list:
        with self._cursor() as cur:
            q = ("SELECT tenant, project, usd, calls, unpriced, runs, est_usd, est_actual_usd, bulk "
                 "FROM project_spend")
            if tenant is None:
                cur.execute(q)
            else:
                cur.execute(q + " WHERE tenant = %s", (tenant,))
            got = cur.fetchall()
        return [{"tenant": r[0], "project": int(r[1]), "usd": float(r[2]), "calls": int(r[3]),
                 "unpriced": int(r[4]), "runs": int(r[5]), "estUsd": float(r[6]),
                 "estActualUsd": float(r[7]), "bulk": int(r[8])} for r in got]

    # ── журнал токенов по дням ──
    def add_usage(self, day: str, tenant: str, uid: str, step: str, model: str,
                  calls: int, tin: int, cached: int, tout: int, think: int,
                  usd: float, unpriced: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO usage_daily (day, tenant, uid, step, model, calls, tin, cached,"
                " tout, think, usd, unpriced) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (day, tenant, uid, step, model) DO UPDATE SET "
                " calls = usage_daily.calls + EXCLUDED.calls, tin = usage_daily.tin + EXCLUDED.tin,"
                " cached = usage_daily.cached + EXCLUDED.cached, tout = usage_daily.tout + EXCLUDED.tout,"
                " think = usage_daily.think + EXCLUDED.think, usd = usage_daily.usd + EXCLUDED.usd,"
                " unpriced = usage_daily.unpriced + EXCLUDED.unpriced",
                (day, tenant, uid, step, model, int(calls), int(tin), int(cached),
                 int(tout), int(think), float(usd or 0), int(unpriced)))

    def usage_rows(self, day_from: str, day_to: str) -> list:
        with self._cursor() as cur:
            cur.execute(
                "SELECT day, tenant, uid, step, model, calls, tin, cached, tout, think, usd, unpriced "
                "FROM usage_daily WHERE day >= %s AND day <= %s", (day_from, day_to))
            got = cur.fetchall()
        return [{"day": r[0], "tenant": r[1], "user": r[2], "step": r[3], "model": r[4],
                 "calls": int(r[5]), "in": int(r[6]), "cached_in": int(r[7]), "out": int(r[8]),
                 "reasoning": int(r[9]), "cost": float(r[10]), "unpriced": int(r[11])} for r in got]

    def usage_min_day(self) -> Optional[str]:
        with self._cursor() as cur:
            cur.execute("SELECT min(day) FROM usage_daily")
            got = cur.fetchone()
        return got[0] if got else None

    # ── расход по проекту и дню ──
    def add_project_daily(self, rows: list) -> None:
        """Пачка приращений ОДНИМ запросом (буфер сливается раз в минуту)."""
        if not rows:
            return
        vals, args = [], []
        for r in rows:
            vals.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s)")
            args.extend((r["day"], r["tenant"], int(r["project"]), r["step"], float(r.get("usd") or 0),
                         int(r.get("calls") or 0), int(r.get("unpriced") or 0),
                         float(r.get("pages") or 0), float(r.get("minutes") or 0)))
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO project_daily (day, tenant, project, step, usd, calls, unpriced,"
                " pages, minutes) VALUES " + ", ".join(vals) +
                " ON CONFLICT (day, tenant, project, step) DO UPDATE SET"
                " usd = project_daily.usd + EXCLUDED.usd,"
                " calls = project_daily.calls + EXCLUDED.calls,"
                " unpriced = project_daily.unpriced + EXCLUDED.unpriced,"
                " pages = project_daily.pages + EXCLUDED.pages,"
                " minutes = project_daily.minutes + EXCLUDED.minutes", args)

    def project_daily_rows(self, day_from: str, day_to: str) -> list:
        with self._cursor() as cur:
            cur.execute(
                "SELECT day, tenant, project, step, usd, calls, unpriced, pages, minutes"
                " FROM project_daily WHERE day >= %s AND day <= %s", (day_from, day_to))
            got = cur.fetchall()
        return [{"day": r[0], "tenant": r[1], "project": int(r[2]), "step": r[3],
                 "usd": float(r[4]), "calls": int(r[5]), "unpriced": int(r[6]),
                 "pages": float(r[7]), "minutes": float(r[8])} for r in got]

    def project_daily_min_day(self) -> Optional[str]:
        with self._cursor() as cur:
            cur.execute("SELECT min(day) FROM project_daily")
            got = cur.fetchone()
        return got[0] if got else None

    # ── заказы на оплату ──
    def pay_put(self, doc: dict) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO pay_orders (id, tenant, status, doc) VALUES (%s, %s, %s, %s::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, doc = EXCLUDED.doc,"
                " updated = now()",
                (int(doc["id"]), doc["tenant"], doc["status"], _dumps(doc)))

    def pay_get(self, oid: int) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT doc FROM pay_orders WHERE id = %s", (int(oid),))
            got = cur.fetchone()
        return _as_doc(got[0]) if got else None

    def pay_list(self, tenant: Optional[str] = None, limit: int = 1000) -> list:
        q = "SELECT doc FROM pay_orders"
        args: list = []
        if tenant is not None:
            q += " WHERE tenant = %s"
            args.append(tenant)
        q += " ORDER BY id DESC LIMIT %s"
        args.append(int(limit))
        with self._cursor() as cur:
            cur.execute(q, args)
            got = cur.fetchall()
        return [_as_doc(r[0]) for r in got]

    def pay_next_id(self) -> int:
        return self.next_counter("payOrder", 1000)

    # ── счётчики событий ──
    def add_events(self, rows: list) -> None:
        """Пачка приращений ОДНИМ запросом.

        Пачкой, а не по строке: слив идёт раз в минуту и несёт десятки
        ключей, и отдельный round-trip на каждый — это десятки задержек
        сети там, где хватает одной. Дубли внутри пачки исключены по
        построению (буфер — словарь по тому же ключу), иначе ON CONFLICT
        отказался бы править строку дважды."""
        if not rows:
            return
        vals, args = [], []
        for r in rows:
            vals.append("(%s, %s, %s, %s, %s, %s, %s)")
            args.extend((r["day"], r.get("tenant") or "", r["code"], int(r.get("n") or 0),
                         float(r.get("ms_sum") or 0), float(r.get("ms_max") or 0),
                         int(r.get("slow") or 0)))
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO events (day, tenant, code, n, ms_sum, ms_max, slow) VALUES "
                + ", ".join(vals) +
                " ON CONFLICT (day, tenant, code) DO UPDATE SET"
                " n = events.n + EXCLUDED.n, ms_sum = events.ms_sum + EXCLUDED.ms_sum,"
                " ms_max = GREATEST(events.ms_max, EXCLUDED.ms_max),"
                " slow = events.slow + EXCLUDED.slow", args)

    def events_rows(self, day_from: str, day_to: str, tenant: Optional[str] = None) -> list:
        q = ("SELECT day, tenant, code, n, ms_sum, ms_max, slow FROM events"
             " WHERE day >= %s AND day <= %s")
        args = [day_from, day_to]
        if tenant is not None:
            q += " AND tenant = %s"
            args.append(tenant)
        with self._cursor() as cur:
            cur.execute(q, args)
            got = cur.fetchall()
        return [{"day": r[0], "tenant": r[1], "code": r[2], "n": int(r[3]),
                 "ms_sum": float(r[4]), "ms_max": float(r[5]), "slow": int(r[6])} for r in got]

    def events_prune(self, before_day: str) -> int:
        with self._cursor() as cur:
            cur.execute("DELETE FROM events WHERE day < %s", (before_day,))
            return cur.rowcount or 0

    # ── прогоны ──
    def save_job(self, job: dict) -> None:
        doc = {k: v for k, v in job.items() if k != "usage_sink"}
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, status, tenant, project, doc, updated) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, now()) "
                "ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status,"
                " project = EXCLUDED.project,"
                # Стоп-флаг ЛИПКИЙ: его ставит API («Отменить»), а воркер
                # после каждого куска пишет свою копию задачи целиком — со
                # `stop: false`, если ещё не успел прочитать флаг из базы.
                # Без этого отмена молча пропадала. Флаг не снимает никто:
                # у задачи он рождается ложным и становится истинным один раз.
                " doc = CASE WHEN (jobs.doc->>'stop')::boolean IS TRUE"
                " THEN EXCLUDED.doc || '{\"stop\": true}'::jsonb ELSE EXCLUDED.doc END,"
                " updated = now()",
                (job["id"], job.get("status"), job.get("tenant"), job.get("project"), _dumps(doc)))

    def claim_job(self) -> Optional[dict]:
        """Забрать одну задачу из очереди — по БИЛЕТУ, а не по номеру.

        Порядок задаёт `doc->>'qseq'` (при отсутствии — номер задачи): его
        выдают при постановке в очередь и ОБНОВЛЯЮТ, когда задача уступает
        исполнителя между порциями. Отсюда и берётся «своя очередь каждому»:
        уступивший прогон получает новый, самый большой билет и встаёт в хвост,
        а следующий по кругу — чужой. Порядок по `id` этого не умеет: у книги
        номер меньше, и она забирала бы исполнителя обратно немедленно.

        Задача проекта, у которого УЖЕ идёт прогон, не берётся: два писателя
        одного документа — это молча потерянная работа одного из них
        (`DocConflict` выбрасывает правки). Сегодня исполнитель один и такого
        случиться не может; условие стоит, чтобы второй воркер перестал
        зависеть от честного слова.

        Отбор и захват — РАЗНЫЕ запросы, поэтому захват сверяет статус
        (`AND status = 'queued'`) и повторяется: между ними задачу успевает
        погасить `stop_job`, и без сверки воркер запустил бы остановленную.
        `doc` берётся из того же UPDATE — из отдельного SELECT он был бы
        снимком ДО остановки, то есть со старым стоп-флагом.
        """
        for _ in range(8):
            with self._cursor() as cur:
                cur.execute(
                    "SELECT id FROM jobs j WHERE status = 'queued'"
                    " AND NOT EXISTS (SELECT 1 FROM jobs r WHERE r.status = 'running'"
                    "                 AND r.project = j.project)"
                    " ORDER BY COALESCE((doc->>'qseq')::bigint, id), id LIMIT 1")
                row = cur.fetchone()
                if not row:
                    return None
                jid = row[0]
                cur.execute(
                    "UPDATE jobs SET status = 'running', updated = now()"
                    " WHERE id = %s AND status = 'queued' RETURNING doc", (jid,))
                got = cur.fetchone()
            if got:
                doc = json.loads(got[0]) if isinstance(got[0], str) else got[0]
                doc["status"] = "running"
                return doc
        return None

    def queued_summary(self) -> list:
        """Кто ждёт очереди: [{id, tenant, project, qseq}] по порядку билетов.

        Нужен исполнителю, чтобы решить, уступать ли между порциями, и API —
        чтобы честно назвать место в очереди. Без списка место пришлось бы
        выдумывать, а выдуманное число — то самое враньё, ради которого
        состав прогона вообще считает сервер."""
        with self._cursor() as cur:
            # Потолок обязателен: список зовут перед КАЖДОЙ порцией (решить,
            # уступать ли) и на каждый показ статуса задачи. Ответ нужен
            # только для «есть ли кто впереди», и первых двух сотен для
            # этого хватает с запасом.
            cur.execute(
                "SELECT id, tenant, project, COALESCE((doc->>'qseq')::bigint, id)"
                " FROM jobs WHERE status = 'queued'"
                " ORDER BY COALESCE((doc->>'qseq')::bigint, id), id LIMIT 200")
            return [{"id": r[0], "tenant": r[1], "project": r[2], "qseq": r[3]}
                    for r in cur.fetchall()]

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
