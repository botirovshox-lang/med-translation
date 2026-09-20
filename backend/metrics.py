# -*- coding: utf-8 -*-
"""Счётчики событий: «где теряем деньги, где можно заработать, что чинить».

Зачем отдельный модуль, а не строки в `main.py`:

  1. Метрика НЕ ВПРАВЕ ронять вызов и не вправе замедлять запрос. Поэтому
     `ev()` — это один словарный инкремент под локом и НИ ОДНОГО обращения
     к диску или базе. Слив накопленного идёт пачкой, изредка и в стороне.
  2. `state.json` целиком лежит в памяти и переписывается при КАЖДОМ
     сохранении (инвариант 2). Событие на каждый HTTP-запрос, записанное
     в STATE, означало бы перезапись всего состояния на каждый запрос —
     то есть метрика, убивающая сервис, который меряет.
  3. Писателей ДВА процесса (API и `medcat-worker`), поэтому наружу событие
     уходит СЧЁТЧИКОМ С ИНКРЕМЕНТОМ (таблица `events`), как `spend`
     и `usage_daily`, а не снимком: снимок из двух процессов терял бы
     приращения друг друга.

Что в событии есть и чего в нём нет. Есть: день, организация, код, число,
сумма и максимум длительности, счёт «медленнее порога». Нет НИ ОДНОГО
байта текста клиента — ни оригинала, ни перевода, ни имени файла, ни
почты. Это правило, а не осторожность: журнал отдаётся владельцу сервиса
и уходит в суточную сводку, а тексты клиентов туда попадать не должны
никогда.

Кардинальность ограничена намеренно. Ключ — «день × организация × код»,
а код берётся из ЗАКРЫТЫХ наборов (шаблон маршрута Starlette, код отказа,
имя шага). Свободной строки в коде события быть не должно: первый же
идентификатор внутри кода превратил бы таблицу в лог по строке на запрос —
ровно то, от чего этот модуль уходит. На случай ошибки в вызывающем коде
стоит потолок `METRICS_KEYS_MAX`: переполнение сливает буфер досрочно,
а не растит его бесконечно.
"""
import os
import re
import threading
import time
from datetime import datetime
from typing import Optional

# Порог «медленно»: секунда — это граница, за которой человек замечает
# ожидание, а воркер у нас ОДИН, то есть его секунда — это секунда
# у всех остальных.
SLOW_MS = float(os.environ.get("METRICS_SLOW_MS", "1000"))
# Как часто буфер сливается в хранилище. Раз в минуту — это один запрос
# в базу на минуту жизни процесса, а не на запрос пользователя.
FLUSH_EVERY = float(os.environ.get("METRICS_FLUSH_EVERY", "60"))
# Потолок ключей в буфере. День × организация × код: при десятке организаций
# и двух сотнях кодов это пара тысяч; 20 000 — запас на порядок.
KEYS_MAX = int(os.environ.get("METRICS_KEYS_MAX", "20000"))
# Сколько дней держим в файловом хранилище (в базе чистка отдельной командой).
KEEP_DAYS = int(os.environ.get("METRICS_KEEP_DAYS", "90"))
# Выключатель на случай, если учёт начнёт мешать: METRICS=0 — и ни одного
# инкремента, ни одного слива.
ENABLED = os.environ.get("METRICS", "1") not in ("0", "no", "off")

# Код события: латиница, цифры, точка, двоеточие, дефис, подчёркивание,
# пробел и фигурные скобки (шаблон маршрута — «/api/projects/{pid}»).
# Всё остальное вырезается: код обязан оставаться перечислимым.
_CODE_BAD = re.compile(r"[^A-Za-z0-9 ._:/{}=-]+")
CODE_MAX = 80

_LOCK = threading.Lock()
# (день, организация, код) -> [n, ms_sum, ms_max, slow]
_BUF: dict = {}
# Отсчёт от ЗАПУСКА процесса, а не от нуля: с нулём первый же
# запрос считался бы просроченным и шёл в базу — лишняя запись
# ровно в ту секунду, когда сервис только поднялся.
_LAST_FLUSH = [time.time()]
# Сколько событий не поместилось из-за потолка — число в сводке, а не тишина.
_DROPPED = [0]


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def code_ok(code: str) -> str:
    """Привести код к перечислимому виду. Пустой — «?»: событие без кода
    всё равно считаем, потерять его хуже, чем записать безымянным."""
    c = _CODE_BAD.sub("", str(code or "")).strip()
    return (c[:CODE_MAX] or "?")


def ev(code: str, tenant: Optional[str] = None, n: int = 1,
       ms: Optional[float] = None, day: Optional[str] = None) -> None:
    """Приращение счётчика. Стоимость — один lookup и сложение.

    Исключений не бросает НИКОГДА: вызов модели, не состоявшийся из-за
    бухгалтерии, обошёлся бы дороже любой аналитики."""
    if not ENABLED:
        return
    try:
        key = (day or today(), tenant or "", code_ok(code))
        with _LOCK:
            row = _BUF.get(key)
            if row is None:
                if len(_BUF) >= KEYS_MAX:
                    _DROPPED[0] += 1
                    return
                row = _BUF[key] = [0, 0.0, 0.0, 0]
            row[0] += int(n)
            if ms is not None:
                row[1] += float(ms)
                if ms > row[2]:
                    row[2] = float(ms)
                if ms >= SLOW_MS:
                    row[3] += 1
    except Exception:
        pass


def due(now: float) -> bool:
    """Пора ли сливать. Дешёвая проверка для горячего пути: сравнение чисел,
    без лока. Переполнение буфера — повод слить немедленно."""
    if not ENABLED:
        return False
    if len(_BUF) >= KEYS_MAX:
        return True
    return bool(_BUF) and (now - _LAST_FLUSH[0] >= FLUSH_EVERY)


def take(now: Optional[float] = None) -> list:
    """Забрать накопленное и очистить буфер.

    Возвращает [{day, tenant, code, n, ms_sum, ms_max, slow}]. Забираем
    ПОД ЛОКОМ и коротко — сама запись в хранилище идёт уже снаружи лока,
    иначе рабочие потоки прогона ждали бы сетевой задержки базы."""
    with _LOCK:
        buf = _BUF.copy()
        _BUF.clear()
        dropped, _DROPPED[0] = _DROPPED[0], 0
    _LAST_FLUSH[0] = now if now is not None else time.time()
    rows = [{"day": d, "tenant": t, "code": c, "n": v[0],
             "ms_sum": round(v[1], 3), "ms_max": round(v[2], 3), "slow": v[3]}
            for (d, t, c), v in buf.items()]
    if dropped:
        rows.append({"day": today(), "tenant": "", "code": "metrics.dropped",
                     "n": dropped, "ms_sum": 0.0, "ms_max": 0.0, "slow": 0})
    return rows


def put_back(rows: list) -> None:
    """Вернуть в буфер то, что не удалось записать (база недоступна).

    Без этого сбой сети означал бы тихо потерянную минуту наблюдений.
    Если буфер уже у потолка — возвращённое считается потерянным и названо
    числом: расти бесконечно он не вправе."""
    if not rows:
        return
    try:
        with _LOCK:
            for r in rows:
                if r.get("code") == "metrics.dropped":
                    _DROPPED[0] += int(r.get("n") or 0)
                    continue
                key = (r["day"], r.get("tenant") or "", r["code"])
                row = _BUF.get(key)
                if row is None:
                    if len(_BUF) >= KEYS_MAX:
                        _DROPPED[0] += int(r.get("n") or 0)
                        continue
                    row = _BUF[key] = [0, 0.0, 0.0, 0]
                row[0] += int(r.get("n") or 0)
                row[1] += float(r.get("ms_sum") or 0)
                row[2] = max(row[2], float(r.get("ms_max") or 0))
                row[3] += int(r.get("slow") or 0)
    except Exception:
        pass


def pending() -> int:
    return len(_BUF)


def reset() -> None:
    """Только для тестов."""
    with _LOCK:
        _BUF.clear()
        _DROPPED[0] = 0
    _LAST_FLUSH[0] = time.time()
