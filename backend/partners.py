# -*- coding: utf-8 -*-
"""Партнёры: внешние сайты, которые приводят клиентов, и их комиссия.

Отличие от приглашений (`referral.py`) — в том, КТО приводит и ЧЕМ ему
платят. Там приводит клиент-организация, и платят ей страницами, сами.
Здесь приводит посторонний сайт (партнёр — не учётная запись системы),
и платят ему ДЕНЬГАМИ, руками: система только считает, сколько клиенты
партнёра оплатили и сколько из этого его процент. Решение о выплате и сама
выплата — за администратором (решение владельца 19.10.2026).

Законы, которые нельзя ослаблять:

1. **Ссылка — метка происхождения, а не дверь** (тот же закон, что у
   приглашений): `/r/КОД` ничего не открывает, человек регистрируется
   обычной формой с почтой, паролем и согласием.

2. **Засчитывается ПОСЛЕДНИЙ переход до регистрации, окно — WINDOW_DAYS
   (90).** Мировая практика партнёрских программ (last click, cookie
   window). Новый переход по чужой ссылке перекрывает прежний; после
   регистрации клиент закреплён за партнёром НАВСЕГДА, и процент идёт со
   всех его оплат (решение владельца).

3. **Процент берётся тот, что действовал в ДЕНЬ ОПЛАТЫ** (`percent_at`).
   Комиссия по продаже замораживается в момент продажи — так считают все
   партнёрские сети; иначе смена процента задним числом переписала бы уже
   отправленные партнёру отчёты.

4. **Комиссия — только с оплаченных ЗАКАЗОВ** (Click, Payme, карта, «по
   счёту», подтверждённое администратором). Пополнение страниц руками
   в карточке организации — не оплата через систему, и процента с него
   система не считает: сумму такой сделки знает только администратор.

5. **Деньги — Decimal**, наружу строками и числами с двумя знаками:
   отчёт уходит партнёру, и он обязан сходиться до цента.
"""

import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

KEY = "partners"                       # верхний ключ STATE (в /api/seed белый список)
WINDOW_DAYS = max(1, int(os.environ.get("PARTNER_WINDOW_DAYS", "90") or 90))
COOKIE = "mct_ref"
# guest — бесплатный перевод первой страницы БЕЗ регистрации (инвариант 43):
# человек с чужого сайта сразу переводит свой файл, а регистрируется на выгрузке.
TARGETS = ("app", "landing", "guest")
LANGS = ("", "ru", "uz", "en")
UTM_RE = re.compile(r"^utm_(source|medium|campaign|content|term)$")


def dec(v, default="0") -> Decimal:
    try:
        d = Decimal(str(v if v is not None and v != "" else default))
    except (InvalidOperation, ValueError):
        d = Decimal(default)
    return d if d.is_finite() else Decimal(default)


def money(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def percent_at(partner: dict, day: str) -> Decimal:
    """Процент, действовавший в момент `day` — время оплаты «ГГГГ-ММ-ДД
    ЧЧ:ММ:СС» по часам сервера (тем же, что пишут `paidAt`). Журнал
    `percentLog` — [{from, percent}], `from` в тех же часах (у старых
    записей только дата — строки сравниваются верно и так). Момент раньше
    первой записи получает первую. Правка процента в тот же день оплаты,
    сделанную раньше, не переписывает: это и есть «заморожено в момент
    продажи»."""
    log = sorted((partner.get("percentLog") or []), key=lambda x: str(x.get("from") or ""))
    if not log:
        return dec(partner.get("percent"))
    cur = dec(log[0].get("percent"))
    for x in log:
        if str(x.get("from") or "") <= (day or ""):
            cur = dec(x.get("percent"))
    return cur


def commission(usd, pct: Decimal) -> Decimal:
    return (dec(usd) * pct / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def target_url(partner: dict, app_base: str, landing_base: str, code: str, utm: dict) -> str:
    """Куда ведёт ссылка партнёра. `app_base` — пустая строка для того же
    хоста (ссылка обслуживается самим приложением)."""
    from urllib.parse import urlencode
    lang = partner.get("lang") or ""
    q = {"ref": code}
    if partner.get("target") == "landing" and landing_base:
        path = "/" + (lang + "/" if lang in ("uz", "en") else "")
        base = landing_base.rstrip("/") + path
    elif partner.get("target") == "guest":
        base = (app_base or "").rstrip("/") + "/"
        q = {"try": "1", "ref": code}
        if lang:
            q["lang"] = lang
    else:
        base = (app_base or "").rstrip("/") + "/"
        if lang:
            q["lang"] = lang
    for k, v in (utm or {}).items():
        if UTM_RE.match(k) and v:
            q[k] = str(v)[:100]
    return base + "?" + urlencode(q)


def in_period(day: str, d_from: str, d_to: str) -> bool:
    day = (day or "")[:10]
    if d_from and day < d_from:
        return False
    if d_to and day > d_to:
        return False
    return True
