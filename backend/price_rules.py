# -*- coding: utf-8 -*-
"""Цены и лимиты по ФУНКЦИЯМ — для всех, для организации и для человека.

Чистые правила без STATE и без сети: каталог функций, какой шаг расхода
к какой функции относится, чистка правила из запроса и разрешение
«что действует здесь». Хранение, счёт и рубежи — в `main.py`
(раздел «Цены и лимиты по функциям», инвариант 40).

Законы, которые нельзя ослаблять:

1. **Функция — то, что покупает или тратит КЛИЕНТ, а не шаг конвейера.**
   Шагов расхода почти два десятка (`translate`, `backcheck`, `judge`,
   `term_context`…), и правило на каждый было бы таблицей, в которой
   владелец сервиса не разберётся. Шаги сведены в группы (`STEP_FN`),
   а шаг без группы (`embed`, `refusal`) ложится только в «всё вместе».
   Новый шаг расхода ОБЯЗАН получить строку в `STEP_FN` или в `ONLY_ALL` —
   тест выводит список шагов из самого `main.py`.

2. **Цена и «выключено» — самое ТОЧНОЕ явное значение** (человек сильнее
   организации, организация сильнее общего правила). А ЛИМИТЫ у каждого
   уровня свои и действуют ОДНОВРЕМЕННО: лимит организации меряет расход
   всей организации, лимит человека — расход этого человека. Подменять
   одно другим нельзя: «Еве $5 в месяц» не значит «организации Евы $5».

3. **Общее правило (`all`) — УМОЛЧАНИЕ ДЛЯ КАЖДОЙ организации, а не потолок
   на весь сервис.** «Ревизия — не больше $10 в месяц» у всех значит
   «у каждой организации свои $10»: общий на сервис потолок одна организация
   выбирала бы за всех.

4. **Цена продажи на уровне «всем» здесь НЕ хранится** — она в настройках
   оплат (`payConfig.pricePage` / `priceMinute`). Два места для одного
   числа разошлись бы первой же правкой.
"""

from decimal import Decimal, InvalidOperation

# Каталог. `unit`: pages | minutes | usd — в чём лимит; `price` — есть ли
# у функции цена продажи; `off` — можно ли её выключить. Порядок — порядок
# строк на экране.
FUNCS = [
    {"key": "pages", "label": "Перевод документов", "unit": "pages", "price": True, "off": False},
    {"key": "minutes", "label": "Видео и звук", "unit": "minutes", "price": True, "off": True},
    {"key": "translate", "label": "Перевод моделью", "unit": "usd", "price": False, "off": True},
    {"key": "review", "label": "Ревизия и справка о документе", "unit": "usd", "price": False, "off": True},
    {"key": "checks", "label": "Проверки перевода", "unit": "usd", "price": False, "off": True},
    {"key": "repair", "label": "Ремонт перевода", "unit": "usd", "price": False, "off": True},
    {"key": "terms", "label": "Термины и глоссарий", "unit": "usd", "price": False, "off": True},
    {"key": "ocr", "label": "Чтение картинок и сканов", "unit": "usd", "price": False, "off": True},
    {"key": "speech", "label": "Распознавание речи и озвучка", "unit": "usd", "price": False, "off": True},
    {"key": "all", "label": "Всё вместе на модели", "unit": "usd", "price": False, "off": False},
]
FUNC_KEYS = [f["key"] for f in FUNCS]
_BY_KEY = {f["key"]: f for f in FUNCS}

# Шаг расхода (первый аргумент `_note_usage` / `_note_audio`) → функция.
STEP_FN = {
    "translate": "translate",
    "review": "review", "guide": "review", "brief": "review",
    "backcheck": "checks", "judge": "checks", "termcheck": "checks",
    "term_context": "checks", "termcross": "checks",
    "repair": "repair",
    "terms": "terms", "edit_terms": "terms",
    "medical_qa": "checks",
    "ocr": "ocr", "scanquote": "ocr",
    "asr": "speech", "tts": "speech",
}
# Шаги, у которых своей функции нет: их деньги ложатся только в «всё вместе».
ONLY_ALL = {"embed", "refusal"}

# Вид задачи (и шаг составного прогона) → функции, которые она тратит.
# `mediarender` тратит деньги только на озвучке: субтитры дорожкой и в кадр
# моделей не зовут (см. `job_fns`).
JOB_FN = {
    "translate": ["translate"], "review": ["review"],
    "backcheck": ["checks"], "termcheck": ["checks"], "termaudit": ["checks"],
    "medical_qa": ["checks"],
    # Ремонт перепроверяет правку back-check и termcheck: с закрытыми
    # проверками он платил бы за правку, которую тут же откатит.
    "repair": ["repair", "checks"], "apply_terms": ["repair", "checks", "terms"],
    "termsheet": ["terms", "checks"],
    "images": ["ocr"],
    "asr": ["speech"], "mediarender": ["speech"],
}

MAX_LIMIT = 1e9


def fn_of_step(step: str):
    return STEP_FN.get(step or "")


def job_fns(kind: str, params=None) -> list:
    """Функции задачи; у составного прогона — по его шагам."""
    params = params or {}
    if kind == "mediarender":
        return ["speech"] if params.get("what") == "dub" else []
    if kind == "full":
        out = []
        for s in params.get("steps") or []:
            for f in JOB_FN.get(s, []):
                if f not in out:
                    out.append(f)
        return out
    return list(JOB_FN.get(kind, []))


def func(key: str):
    return _BY_KEY.get(key)


def dec(v):
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return d


def clean_rule(scope: str, fn: str, price=None, limit=None, off=None) -> dict:
    """Правило из запроса → то, что ляжет в хранилище. ValueError — отказ
    с причиной. Пустое (None) поле означает «не задано здесь», то есть
    «наследовать» — а НЕ ноль: ноль у лимита значит «нельзя вовсе»."""
    f = func(fn)
    if f is None:
        raise ValueError("Неизвестная функция: %s" % fn)
    out = {}
    ok = allowed(scope, fn)
    if price is not None and price != "":
        if not ok["price"]:
            raise ValueError("Цену продажи здесь не задать: она у организации или в настройках оплат")
        d = dec(price)
        if d is None or d < 0 or d > Decimal("100000"):
            raise ValueError("Цена — число от 0")
        out["price"] = str(d.quantize(Decimal("0.0001")).normalize())
    if limit is not None and limit != "":
        if not ok["limit"]:
            raise ValueError("Этот лимит здесь не задаётся")
        try:
            n = float(str(limit).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError("Лимит — число от 0")
        if n != n or n < 0 or n > MAX_LIMIT:
            raise ValueError("Лимит — число от 0")
        out["limit"] = round(n, 4)
    if off is not None:
        if not ok["off"]:
            raise ValueError("Эту функцию нельзя выключить")
        if off:
            out["off"] = True
        else:
            # Явное «включено» — законное правило: оно перекрывает
            # выключение уровнем выше (организация выключила — человеку можно).
            out["off"] = False
    return out


# На каком уровне что можно задать. Цена продажи — только у ОРГАНИЗАЦИИ:
# платит организация (заказ зачисляется ей), а «всем» цена живёт в настройках
# оплат (закон 4). Лимит страниц и минут «всем» не задаётся: у организаций
# свой предоплаченный остаток, и общий месячный потолок сверху запер бы
# первого клиента с книгами одной строкой. «Всё вместе» у организации —
# это её `limitUsd` (прежняя дверь `/api/admin/tenants/{tid}`), здесь —
# только у человека.
def allowed(scope: str, fn: str) -> dict:
    f = func(fn) or {}
    return {"price": bool(f.get("price")) and scope == "tenant",
            "limit": not (scope == "all" and f.get("unit") in ("pages", "minutes"))
                     and not (fn == "all" and scope != "user"),
            "off": bool(f.get("off"))}


def effective(levels: list, fn: str) -> dict:
    """Что действует для функции. `levels` — [(уровень, {функция: правило})]
    от самого ТОЧНОГО к общему: ("user", …), ("tenant", …), ("all", …).
    {price, priceFrom, off, offFrom, tenantLimit, tenantLimitFrom, userLimit}.
    `price` None — правила нет, действует цена из настроек оплат."""
    out = {"price": None, "priceFrom": None, "off": False, "offFrom": None,
           "tenantLimit": None, "tenantLimitFrom": None, "userLimit": None}
    for level, bag in levels:
        r = (bag or {}).get(fn) or {}
        ok = allowed(level, fn)
        if out["priceFrom"] is None and r.get("price") is not None and ok["price"]:
            out["price"], out["priceFrom"] = r["price"], level
        if out["offFrom"] is None and r.get("off") is not None and ok["off"]:
            out["off"], out["offFrom"] = bool(r["off"]), level
        if r.get("limit") is not None and ok["limit"]:
            if level == "user":
                out["userLimit"] = float(r["limit"])
            elif out["tenantLimitFrom"] is None:
                out["tenantLimit"], out["tenantLimitFrom"] = float(r["limit"]), level
    return out


def scope_key(scope: str, ident) -> str:
    if scope == "all":
        return "all"
    if scope == "tenant":
        return "t:%s" % ident
    if scope == "user":
        return "u:%s" % int(ident)
    raise ValueError("Неизвестный уровень: %s" % scope)
