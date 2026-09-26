"""Приём оплат: протоколы Click (SHOP API) и Payme (Merchant API), ссылки
на оплату и арифметика сумм. Здесь ТОЛЬКО чистые функции — без STATE, без
сети и без чтения окружения в момент импорта: состояние заказов и зачисление
страниц живут в `main.py` (там `_SAVE_LOCK` и единственная дверь пополнения
`_pages_topup`), а протокол проверяется тестами на подписях и ответах.

Почему своё, а не SDK: у обоих поставщиков нет официального SDK на Python,
а сторонние тащат свой веб-фреймворк. Протоколы короткие и описаны
поставщиками; ошибка в них — это деньги, поэтому каждое правило ниже названо
и проверяется `tests/test_payments.py`.

Деньги — `Decimal`, суммы в сумах ЦЕЛЫЕ (Click принимает «1000.00», Payme —
тийины = сумы × 100). Округление к оплате — ВВЕРХ до целого сума: заказ,
округлённый вниз, недоплачивал бы на каждой транзакции.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, InvalidOperation
from typing import Optional
from urllib.parse import urlencode

# ─── Click SHOP API ─────────────────────────────────────────────────
# Коды ошибок из документации Click (docs.click.uz, «SHOP API»).
CLICK_OK = 0
CLICK_SIGN = -1            # SIGN CHECK FAILED
CLICK_AMOUNT = -2          # Incorrect parameter amount
CLICK_ACTION = -3          # Action not found
CLICK_PAID = -4            # Already paid
CLICK_NO_ORDER = -5        # User does not exist (заказ не найден)
CLICK_NO_TRANS = -6        # Transaction does not exist
CLICK_UPDATE = -7          # Failed to update user
CLICK_REQUEST = -8         # Error in request from click
CLICK_CANCELLED = -9       # Transaction cancelled

CLICK_NOTES = {
    CLICK_OK: "Success", CLICK_SIGN: "SIGN CHECK FAILED!", CLICK_AMOUNT: "Incorrect parameter amount",
    CLICK_ACTION: "Action not found", CLICK_PAID: "Already paid", CLICK_NO_ORDER: "User does not exist",
    CLICK_NO_TRANS: "Transaction does not exist", CLICK_UPDATE: "Failed to update user",
    CLICK_REQUEST: "Error in request from click", CLICK_CANCELLED: "Transaction cancelled",
}


def click_sign(params: dict, secret: str, prepare_id: Optional[str] = None) -> str:
    """md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id
    [+ merchant_prepare_id у Complete] + amount + action + sign_time).
    Сумма берётся СТРОКОЙ, как пришла: «1000.00» и «1000» дают разные
    подписи, и приведение к числу сломало бы сверку."""
    parts = [str(params.get("click_trans_id", "")), str(params.get("service_id", "")), secret,
             str(params.get("merchant_trans_id", ""))]
    if prepare_id is not None:
        parts.append(str(prepare_id))
    parts += [str(params.get("amount", "")), str(params.get("action", "")), str(params.get("sign_time", ""))]
    return hashlib.md5("".join(parts).encode("utf-8")).hexdigest()


def click_sign_ok(params: dict, secret: str, complete: bool) -> bool:
    if not secret:
        return False
    got = str(params.get("sign_string") or "").lower()
    want = click_sign(params, secret, str(params.get("merchant_prepare_id", "")) if complete else None)
    return bool(got) and hmac.compare_digest(got.encode(), want.encode())


def click_answer(params: dict, error: int, **extra) -> dict:
    out = {"click_trans_id": params.get("click_trans_id"),
           "merchant_trans_id": params.get("merchant_trans_id"),
           "error": int(error), "error_note": CLICK_NOTES.get(int(error), "Error")}
    out.update(extra)
    return out


def click_link(service_id: str, merchant_id: str, amount_uzs: int, order_id: int,
               return_url: str = "", merchant_user_id: str = "") -> str:
    q = {"service_id": service_id, "merchant_id": merchant_id,
         "amount": "%d.00" % int(amount_uzs), "transaction_param": str(order_id)}
    if merchant_user_id:
        q["merchant_user_id"] = merchant_user_id
    if return_url:
        q["return_url"] = return_url
    return "https://my.click.uz/services/pay?" + urlencode(q)


def amount_matches(got, want_uzs: int) -> bool:
    """Сумма из колбэка против заказа — Decimal, до тийина: «1000.00» == 1000."""
    try:
        return Decimal(str(got)).quantize(Decimal("0.01")) == Decimal(int(want_uzs)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return False


# ─── Payme Merchant API (JSON-RPC 2.0) ──────────────────────────────
PAYME_AUTH = -32504          # Недостаточно привилегий
PAYME_PARSE = -32700
PAYME_METHOD = -32601
PAYME_REQUEST = -32600
PAYME_AMOUNT = -31001        # Неверная сумма
PAYME_NO_TRANS = -31003      # Транзакция не найдена
PAYME_CANT_CANCEL = -31007   # Услуга оказана — отменить нельзя
PAYME_CANT_PERFORM = -31008  # Невозможно выполнить операцию
PAYME_NO_ORDER = -31050      # Заказ не найден (диапазон -31050…-31099 — ошибки счёта)
PAYME_ORDER_STATE = -31051   # Заказ не ждёт оплаты (оплачен, отменён, просрочен)
PAYME_ORDER_BUSY = -31052    # По заказу уже идёт другая транзакция

PAYME_TIMEOUT_MS = 43_200_000   # 12 часов: неоплаченная транзакция отменяется
PAYME_REASON_TIMEOUT = 4

_PAYME_TEXT = {
    PAYME_AUTH: ("Недостаточно привилегий", "Ruxsat yetarli emas", "Insufficient privileges"),
    PAYME_PARSE: ("Ошибка разбора запроса", "So‘rovni o‘qib bo‘lmadi", "Parse error"),
    PAYME_METHOD: ("Метод не найден", "Metod topilmadi", "Method not found"),
    PAYME_REQUEST: ("Неверный запрос", "Noto‘g‘ri so‘rov", "Invalid request"),
    PAYME_AMOUNT: ("Неверная сумма", "Noto‘g‘ri summa", "Incorrect amount"),
    PAYME_NO_TRANS: ("Транзакция не найдена", "Tranzaksiya topilmadi", "Transaction not found"),
    PAYME_CANT_CANCEL: ("Услуга оказана, отменить нельзя", "Xizmat ko‘rsatilgan, bekor qilib bo‘lmaydi",
                        "Service delivered, cannot cancel"),
    PAYME_CANT_PERFORM: ("Невозможно выполнить операцию", "Amalni bajarib bo‘lmaydi", "Unable to perform operation"),
    PAYME_NO_ORDER: ("Заказ не найден", "Buyurtma topilmadi", "Order not found"),
    PAYME_ORDER_STATE: ("Заказ не ждёт оплаты", "Buyurtma to‘lovni kutmayapti", "Order is not awaiting payment"),
    PAYME_ORDER_BUSY: ("Заказ уже оплачивается", "Buyurtma allaqachon to‘lanmoqda", "Order is being paid"),
}


def payme_error(req_id, code: int, data: Optional[str] = None) -> dict:
    ru, uz, en = _PAYME_TEXT.get(code, ("Ошибка", "Xato", "Error"))
    err = {"code": int(code), "message": {"ru": ru, "uz": uz, "en": en}}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def payme_result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def payme_auth_ok(header: Optional[str], key: str) -> bool:
    """Basic base64("Paycom:<KEY>"). Сравнение постоянного времени, байтами."""
    if not key or not header or not header.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True)
    except Exception:
        return False
    want = ("Paycom:" + key).encode("utf-8")
    return hmac.compare_digest(raw, want)


def payme_link(merchant_id: str, order_id: int, amount_uzs: int, return_url: str = "",
               test: bool = False, lang: str = "ru") -> str:
    parts = ["m=%s" % merchant_id, "ac.order_id=%d" % int(order_id), "a=%d" % (int(amount_uzs) * 100)]
    if lang in ("ru", "uz", "en"):
        parts.append("l=%s" % lang)
    if return_url:
        parts.append("c=%s" % return_url)
    token = base64.b64encode(";".join(parts).encode("utf-8")).decode("ascii")
    return ("https://checkout.test.paycom.uz/" if test else "https://checkout.paycom.uz/") + token


def payme_tx_view(tx: dict) -> dict:
    """Ответ CheckTransaction: времена — миллисекунды, 0 если события не было."""
    return {"create_time": int(tx.get("create_time") or 0), "perform_time": int(tx.get("perform_time") or 0),
            "cancel_time": int(tx.get("cancel_time") or 0), "transaction": str(tx.get("our_id")),
            "state": int(tx.get("state") or 0), "reason": tx.get("reason")}


# ─── суммы ───────────────────────────────────────────────────────────
def price_total(pages: float, minutes: float, price_page: Decimal, price_min: Decimal) -> Decimal:
    """Сумма в долларах, до цента, округление к ближайшему."""
    t = Decimal(str(pages)) * price_page + Decimal(str(minutes)) * price_min
    return t.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_local(usd: Decimal, rate: Decimal) -> int:
    """Доллары в сумах (тенге) по курсу — ВВЕРХ до целого."""
    return int((usd * rate).quantize(Decimal("1"), rounding=ROUND_CEILING))


def dec(v, default: str = "0") -> Decimal:
    try:
        d = Decimal(str(v))
        return d if d.is_finite() else Decimal(default)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)
