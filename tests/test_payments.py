# -*- coding: utf-8 -*-
"""Оплата страниц и минут, поминутный счёт видео, расход по проектам за период
(инвариант 39). Здесь считаются ДЕНЬГИ, поэтому сторожатся места, где их
можно получить даром или потерять:

  1. Payme: авторизация, сумма в тийинах, состояния транзакции, повтор
     Perform не зачисляет второй раз, отмена выполненной — -31007, выписка.
  2. Click: подпись, сумма, чужой prepare_id, отказ оплаты у Click (error<0)
     закрывает заказ, повтор Complete — -4 без второго зачисления.
  3. Зачисление = пополнение администратором: страницы, снятие `trial`,
     подъём денежного лимита; сверка дозачисляет потерянное ровно раз.
  4. Организация без потолка страниц страницы не покупает (иначе заперли бы).
  5. Права: заказ заводит владелец; чужой заказ — 404; колбэки без ключей —
     отказ протокола.
  6. Минуты: без кошелька видео идёт страницами; с кошельком — списание
     минутами до распознавания, фрагмент на остаток, 402 с кодом; пол
     по словам досписывает ускоренную речь.
  7. Расход по проектам за период: модель + проданные страницы/минуты по дням.
  8. /api/seed не отдаёт настроек оплат; /api/auth/me — внутренностей.
  5б. Octo (карта Visa/Mastercard): платёж заводим мы, телу уведомления
     не верим — зачисляет только ответ на наш запрос статуса; чужая сумма
     не зачисляется; повтор уведомления не зачисляет второй раз.

Ни одного вызова модели, файл состояния не пишется.
"""
import base64
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="mct-pay-"))
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["PAY_ORDERS_FILE"] = str(TMP / "pay_orders.json")
for k in ("CLICK_SERVICE_ID", "CLICK_MERCHANT_ID", "CLICK_SECRET_KEY", "PAYME_MERCHANT_ID", "PAYME_KEY",
          "PAY_CARD_LINK", "PAYME_IKPU", "OCTO_SHOP_ID", "OCTO_SECRET", "OCTO_CURRENCY", "OCTO_TEST",
          "OCTO_UNIQUE_KEY", "OCTO_SPIC", "OCTO_INN", "OCTO_PACKAGE_CODE"):
    os.environ.pop(k, None)
sys.path.insert(0, "backend")
import main                                              # noqa: E402
import payments                                          # noqa: E402
import media                                             # noqa: E402
from starlette.testclient import TestClient              # noqa: E402

main.save_state = lambda *a, **k: None
main._ensure_job_worker = lambda: None
main.MEDIA_DIR = TMP / "media"
main.MEDIA_UPLOAD_DIR = main.MEDIA_DIR / "uploads"
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main.STATE["spend"], main.STATE["projects"] = {}, []
main.STATE.pop("payConfig", None)
main._SESSIONS.clear()
main._LOGIN_FAILS.clear()
main.TENANT_MAX_PAGES = 0
main.tg_mod = None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}           # noqa: E731
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]


def mkorg(tid, **fields):
    c.post("/api/admin/tenants", headers=H(A),
           json={"id": tid, "name": tid.upper(), "ownerLogin": tid, "ownerPassword": tid + "-pass-123"})
    main._tenant_rec(tid).update(fields)
    return c.post("/api/auth/login", json={"login": tid, "password": tid + "-pass-123"}).json()["token"]


# Пробная организация: потолок страниц, пробный флаг, лимит расхода $0.30.
T = mkorg("trial", pagesCredit=1.0, pagesUsed=0.0, trial=True, limitUsd=0.30)
U = mkorg("unlim")                                # без потолка страниц — как `default`

print("=== 0. Протоколы: подписи и ссылки ===")
p = {"click_trans_id": "11", "service_id": "7", "merchant_trans_id": "1001", "amount": "1000.00",
     "action": "0", "sign_time": "2026-09-26 10:00:00"}
want = hashlib.md5(b"117SECRET10011000.0002026-09-26 10:00:00").hexdigest()
check(payments.click_sign(p, "SECRET") == want, "подпись Prepare Click — по документации")
pc = dict(p, action="1", merchant_prepare_id="1001")
want2 = hashlib.md5(b"117SECRET100110011000.0012026-09-26 10:00:00").hexdigest()
check(payments.click_sign(pc, "SECRET", "1001") == want2, "подпись Complete — prepare_id после merchant_trans_id")
check(payments.amount_matches("1000.00", 1000) and payments.amount_matches("1000", 1000)
      and not payments.amount_matches("999.99", 1000) and not payments.amount_matches("abc", 1000),
      "сумма сверяется как число до тийина")
link = payments.payme_link("MID", 1001, 12500, "https://x/?pay=1001")
raw = base64.b64decode(link[len("https://checkout.paycom.uz/"):]).decode()
check("m=MID" in raw and "ac.order_id=1001" in raw and "a=1250000" in raw, "ссылка Payme — тийины и номер заказа")
check(payments.to_local(payments.dec("0.5"), payments.dec("12700")) == 6350
      and payments.to_local(payments.dec("0.01"), payments.dec("12700.5")) == 128, "сумы — вверх до целого")
check(payments.payme_auth_ok("Basic " + base64.b64encode(b"Paycom:KEY").decode(), "KEY")
      and not payments.payme_auth_ok("Basic " + base64.b64encode(b"Paycom:BAD").decode(), "KEY")
      and not payments.payme_auth_ok("Basic ###", "KEY") and not payments.payme_auth_ok(None, "KEY"),
      "ключ Payme сверяется, мусор в заголовке — отказ")

print("=== 1. Экран оплаты и заказ ===")
r = c.get("/api/pay", headers=H(T))
d = r.json()
check(r.status_code == 200 and d["payable"] == {"pages": True, "minutes": True}, "пробная организация покупает страницы и минуты")
m = {x["id"]: x for x in d["methods"]}
check(set(m) == {"click", "payme", "card", "kaspi"}
      and m["card"]["currency"] == "USD" and m["kaspi"]["currency"] == "KZT",
      "валюта у каждого способа")
check(not any(k in x for x in m.values() for k in ("page", "minute")),
      "цены за страницу и минуту владельцу не отдаются — это прайс сервиса (22а)")
check(not m["payme"]["online"], "без ключей Payme онлайн выключен")
r = c.post("/api/pay/quote", headers=H(T), json={"pages": 10, "minutes": 10, "method": "payme"})
q = r.json()["quote"]
check(q["amount"] == "101600" and q["currency"] == "UZS", "10 стр. + 10 мин = 101 600 сум")
check(not any(k in q for k in ("usd", "rate", "prices")), "доллары, курс и цены за единицу владельцу не отдаются")
_sup = dict(next(s for s in main._SESSIONS.values() if s.get("super")), tenant="trial")
_tok = main.CURRENT_SESSION.set(_sup)
try:
    qa = main.pay_quote(main.PayOrderRequest(pages=10, minutes=10, method="payme"))["quote"]
finally:
    main.CURRENT_SESSION.reset(_tok)
check(qa.get("usd") == "8.00" and qa.get("prices"),
      "администратор сервиса видит расчёт в долларах: 10 стр. + 10 мин = $8")
for body, code, label in (({"pages": 0, "minutes": 0, "method": "payme"}, 400, "пустой заказ — 400"),
                          ({"pages": -5, "minutes": 0, "method": "payme"}, 400, "отрицательное — 400"),
                          ({"pages": 10 ** 7, "minutes": 0, "method": "payme"}, 400, "огромное — 400"),
                          ({"pages": 1, "minutes": 0, "method": "bitcoin"}, 400, "чужой способ — 400")):
    check(c.post("/api/pay/quote", headers=H(T), json=body).status_code == code, label)
r = c.post("/api/pay/quote", headers=H(U), json={"pages": 10, "minutes": 0, "method": "payme"})
check(r.status_code == 409, "организация без потолка страниц страницы не покупает (иначе заперли бы её)")
check(c.get("/api/pay", headers=H(U)).json()["payable"] == {"pages": False, "minutes": False},
      "и экран это знает")

# Переводчик пробной организации заказ не заводит.
c.post("/api/admin/users", headers=H(A), json={"login": "tr", "password": "tr-pass-1234", "role": "translator",
                                              "tenant": "trial"})
TR_ = c.post("/api/auth/login", json={"login": "tr", "password": "tr-pass-1234"}).json()["token"]
check(c.post("/api/pay/orders", headers=H(TR_), json={"pages": 5, "method": "card"}).status_code == 403,
      "переводчик заказ не заводит — 403")

print("=== 2. Payme ===")
os.environ["PAYME_MERCHANT_ID"] = "MID"
os.environ["PAYME_KEY"] = "KEY"
AUTH = {"Authorization": "Basic " + base64.b64encode(b"Paycom:KEY").decode()}
r = c.post("/api/pay/orders", headers=H(T), json={"pages": 20, "minutes": 0, "method": "payme"})
o = r.json()["order"]
oid = o["id"]
check(r.status_code == 200 and o["status"] == "new" and o["online"] and o["url"].startswith("https://checkout.paycom.uz/"),
      "заказ Payme заведён, ссылка на кассу")
amount = int(o["amount"]) * 100


def rpc(method, params, auth=AUTH, rid=1):
    return c.post("/api/pay/payme", headers=auth, json={"id": rid, "method": method, "params": params}).json()


check(rpc("CheckPerformTransaction", {"amount": amount, "account": {"order_id": str(oid)}}, auth={})["error"]["code"] == -32504,
      "без ключа — -32504")
check(rpc("CheckPerformTransaction", {"amount": amount + 100, "account": {"order_id": str(oid)}})["error"]["code"] == -31001,
      "не та сумма — -31001")
check(rpc("CheckPerformTransaction", {"amount": amount, "account": {"order_id": "999999"}})["error"]["code"] == -31050,
      "нет заказа — -31050")
check(rpc("CheckPerformTransaction", {"amount": amount, "account": {"order_id": str(oid)}})["result"]["allow"] is True,
      "CheckPerform — allow")
check("detail" not in rpc("CheckPerformTransaction", {"amount": amount, "account": {"order_id": str(oid)}})["result"],
      "без PAYME_IKPU чек не отдаётся")
os.environ["PAYME_IKPU"] = "10501001001000000"
det = rpc("CheckPerformTransaction", {"amount": amount, "account": {"order_id": str(oid)}})["result"].get("detail") or {}
it = (det.get("items") or [{}])[0]
check(it.get("code") == "10501001001000000" and it.get("price") == amount and it.get("count") == 1,
      "чек Payme: ИКПУ и вся сумма одной позицией")
check(it.get("title") == "Доступ к программе перевода: 20 стр.",
      "позиция чека — доступ к программе, без нулевых минут: %r" % it.get("title"))
check(main._pay_receipt_title({"pages": 0, "minutes": 7}) == "Доступ к программе перевода: 7 мин видео"
      and main._pay_receipt_title({"pages": 3, "minutes": 2}, "en")
      == "Access to translation software: 3 pages, 2 video minutes",
      "название позиции: только минуты; английское для Octo")
os.environ.pop("PAYME_IKPU")
r = c.post("/api/pay/payme", headers=AUTH, content=b"not json")
check(r.status_code == 200 and r.json()["error"]["code"] == -32700, "мусор в теле — -32700 с HTTP 200")
now = int(time.time() * 1000)
res = rpc("CreateTransaction", {"id": "tx-1", "time": now, "amount": amount, "account": {"order_id": str(oid)}})
check(res.get("result", {}).get("state") == 1 and res["result"]["transaction"] == str(oid), "CreateTransaction — state 1")
res2 = rpc("CreateTransaction", {"id": "tx-1", "time": now, "amount": amount, "account": {"order_id": str(oid)}})
check(res2.get("result", {}).get("create_time") == res["result"]["create_time"], "повтор Create той же транзакции — тот же ответ")
res3 = rpc("CreateTransaction", {"id": "tx-2", "time": now, "amount": amount, "account": {"order_id": str(oid)}})
check(res3.get("error", {}).get("code", 0) <= -31050, "вторая транзакция на тот же заказ — ошибка счёта")
check(c.post("/api/pay/orders/%d/cancel" % oid, headers=H(T)).status_code == 409,
      "владелец не отменяет заказ, по которому идёт транзакция")
rec = main._tenant_rec("trial")
before = float(rec["pagesCredit"])
res = rpc("PerformTransaction", {"id": "tx-1"})
check(res.get("result", {}).get("state") == 2, "PerformTransaction — state 2")
rec = main._tenant_rec("trial")
check(abs(float(rec["pagesCredit"]) - before - 20) < 1e-6, "зачислено 20 страниц")
check("trial" not in rec, "оплата снимает «пробность»")
check(abs(float(main._spend_status("trial")["limitUsd"]) - (0.30 + 10.0)) < 1e-6,
      "денежный лимит этого месяца поднят на сумму оплаты")
check(abs(float(rec["limitUsd"]) - 0.30) < 1e-6 and rec.get("payUsdMonth"),
      "а базовый лимит не тронут: прибавка — только на месяц оплаты")
check(any(e.get("note") == "pay:%d" % oid and e["kind"] == "credit" for e in rec["pagesLog"]),
      "строка журнала страниц с номером заказа")
res = rpc("PerformTransaction", {"id": "tx-1"})
rec = main._tenant_rec("trial")
check(res.get("result", {}).get("state") == 2 and abs(float(rec["pagesCredit"]) - before - 20) < 1e-6,
      "повтор Perform — тот же ответ, второго зачисления нет")
check(rpc("CancelTransaction", {"id": "tx-1", "reason": 5})["error"]["code"] == -31007,
      "отмена выполненной — -31007 (возврат руками)")
ct = rpc("CheckTransaction", {"id": "tx-1"})["result"]
check(ct["state"] == 2 and ct["perform_time"] > 0 and ct["cancel_time"] == 0 and ct["reason"] is None,
      "CheckTransaction — поля по протоколу")
check(rpc("CheckTransaction", {"id": "nope"})["error"]["code"] == -31003, "нет транзакции — -31003")
st = rpc("GetStatement", {"from": now - 1000, "to": now + 1000})["result"]["transactions"]
check(len(st) == 1 and st[0]["id"] == "tx-1" and st[0]["amount"] == amount, "выписка за период")
check(rpc("CheckPerformTransaction", {"amount": amount, "account": {"order_id": str(oid)}})["error"]["code"] == -31051,
      "оплаченный заказ второй раз не оплачивается")
check(rpc("ChangePassword", {"password": "x"})["error"]["code"] == -32601, "неизвестный метод — -32601")

# Отмена неоплаченной транзакции закрывает заказ.
o2 = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "payme"}).json()["order"]
a2 = int(o2["amount"]) * 100
rpc("CreateTransaction", {"id": "tx-3", "time": now, "amount": a2, "account": {"order_id": str(o2["id"])}})
res = rpc("CancelTransaction", {"id": "tx-3", "reason": 3})
check(res.get("result", {}).get("state") == -1, "отмена созданной — state -1")
check(rpc("PerformTransaction", {"id": "tx-3"})["error"]["code"] == -31008, "после отмены выполнить нельзя")
check(c.get("/api/pay/orders/%d" % o2["id"], headers=H(T)).json()["order"]["status"] == "cancelled",
      "заказ закрыт")
# Администратор не подтверждает заказ, по которому у Payme идёт транзакция.
o4 = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "payme"}).json()["order"]
rpc("CreateTransaction", {"id": "tx-5", "time": now, "amount": a2, "account": {"order_id": str(o4["id"])}})
check(c.post("/api/admin/payments/%d/confirm" % o4["id"], headers=H(A), json={}).status_code == 409,
      "подтвердить руками во время оплаты у Payme нельзя — страницы без денег")
rpc("CancelTransaction", {"id": "tx-5", "reason": 3})
# Просроченная транзакция (больше 12 ч).
o3 = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "payme"}).json()["order"]
old = now - payments.PAYME_TIMEOUT_MS - 1000
res = rpc("CreateTransaction", {"id": "tx-4", "time": old, "amount": a2, "account": {"order_id": str(o3["id"])}})
check(res.get("error", {}).get("code") == -31008, "транзакция старше 12 ч не создаётся")

print("=== 3. Click ===")
os.environ.update({"CLICK_SERVICE_ID": "7", "CLICK_MERCHANT_ID": "8", "CLICK_SECRET_KEY": "SECRET"})
oc = c.post("/api/pay/orders", headers=H(T), json={"pages": 0, "minutes": 10, "method": "click"}).json()["order"]
check(oc["url"].startswith("https://my.click.uz/services/pay?") and ("transaction_param=%d" % oc["id"]) in oc["url"],
      "ссылка Click с номером заказа")


def click(path, **kw):
    prm = {"click_trans_id": "555", "service_id": "7", "click_paydoc_id": "9", "merchant_trans_id": str(oc["id"]),
           "amount": "%s.00" % oc["amount"], "action": "0", "error": "0", "error_note": "Success",
           "sign_time": "2026-09-26 10:00:00"}
    prm.update(kw)
    comp = path == "complete"
    prm.setdefault("sign_string", payments.click_sign(prm, "SECRET", prm.get("merchant_prepare_id") if comp else None))
    return c.post("/api/pay/click/" + path, data=prm).json()


check(click("prepare", sign_string="bad")["error"] == -1, "чужая подпись — -1")
check(click("prepare", amount="1.00")["error"] == -2, "не та сумма — -2")
check(click("prepare", merchant_trans_id="999999")["error"] == -5, "нет заказа — -5")
check(click("prepare", merchant_trans_id=str(o2["id"]))["error"] == -5, "заказ Payme через Click не оплатить")
pr = click("prepare")
check(pr["error"] == 0 and pr["merchant_prepare_id"] == oc["id"], "Prepare — ок, prepare_id")
check(click("complete", action="1", merchant_prepare_id="1")["error"] == -6, "чужой prepare_id — -6")
rec = main._tenant_rec("trial")
m0 = main._tenant_minutes("trial")
cm = click("complete", action="1", merchant_prepare_id=str(oc["id"]))
m1 = main._tenant_minutes("trial")
check(cm["error"] == 0 and cm["merchant_confirm_id"] == oc["id"], "Complete — ок")
check(m0["wallet"] is False and m1["wallet"] is True and m1["credit"] == 10.0,
      "оплата минут заводит кошелёк: 10 мин")
cm2 = click("complete", action="1", merchant_prepare_id=str(oc["id"]))
check(cm2["error"] == -4 and main._tenant_minutes("trial")["credit"] == 10.0, "повтор Complete — -4, без второго зачисления")
oc2 = c.post("/api/pay/orders", headers=H(T), json={"minutes": 5, "method": "click"}).json()["order"]
oc = oc2
click("prepare", click_trans_id="556")
cf = click("complete", click_trans_id="556", action="1", merchant_prepare_id=str(oc2["id"]), error="-5017")
check(cf["error"] == -9 and c.get("/api/pay/orders/%d" % oc2["id"], headers=H(T)).json()["order"]["status"] == "cancelled",
      "оплата не прошла у Click — заказ закрыт, -9")
check(main._tenant_minutes("trial")["credit"] == 10.0, "и ничего не зачислено")

print("=== 4. «По счёту»: карта и Kaspi, подтверждение администратором ===")
ok_ = c.post("/api/pay/orders", headers=H(T), json={"pages": 30, "method": "kaspi"}).json()["order"]
check(ok_["currency"] == "KZT" and not ok_["online"] and ok_["url"] is None, "Kaspi — заявка без ссылки")
before = float(main._tenant_rec("trial")["pagesCredit"])
r = c.post("/api/admin/payments/%d/confirm" % ok_["id"], headers=H(A), json={"note": "пришло на счёт"})
check(r.status_code == 200 and r.json()["order"]["status"] == "paid" and r.json()["order"]["applied"],
      "администратор подтвердил — зачислено")
check(abs(float(main._tenant_rec("trial")["pagesCredit"]) - before - 30) < 1e-6, "+30 страниц")
r = c.post("/api/admin/payments/%d/confirm" % ok_["id"], headers=H(A), json={})
check(r.status_code == 200 and abs(float(main._tenant_rec("trial")["pagesCredit"]) - before - 30) < 1e-6,
      "повторное подтверждение не зачисляет второй раз")
check(c.post("/api/admin/payments/%d/cancel" % ok_["id"], headers=H(A), json={}).status_code == 409,
      "оплаченный не отменяется кнопкой — возврат руками")
check(c.post("/api/admin/payments/%d/confirm" % ok_["id"], headers=H(T), json={}).status_code == 403,
      "владелец организации сам себе не подтверждает")
check(c.get("/api/pay/orders/%d" % ok_["id"], headers=H(U)).status_code == 404, "чужой заказ — 404")

print("=== 5. Сверка: оплачено в таблице, но зачисление пропало ===")
ok2 = c.post("/api/pay/orders", headers=H(T), json={"pages": 7, "method": "card"}).json()["order"]
doc = main._pays().pay_get(ok2["id"])
doc["status"] = "paid"
main._pays().pay_put(doc)                       # как будто документ организации не записался
before = float(main._tenant_rec("trial")["pagesCredit"])
n = main._pay_reconcile()
check(n == 1 and abs(float(main._tenant_rec("trial")["pagesCredit"]) - before - 7) < 1e-6, "сверка дозачислила 7 стр.")
check(main._pay_reconcile() == 0 and abs(float(main._tenant_rec("trial")["pagesCredit"]) - before - 7) < 1e-6,
      "второй проход ничего не добавляет")
aud = [e for e in main.STATE["audit"] if e.get("action") == "pay.paid"]
check(aud and all(e.get("tenant") == "trial" for e in aud), "запись о платеже — в журнале СВОЕЙ организации")

print("=== 5б. Octo: карта Visa / Mastercard ===")
check(payments.octo_tx_id(12, 3) == "mct-12-3" and payments.octo_order_of("mct-12-3") == 12
      and payments.octo_order_of("mct-x-1") is None and payments.octo_order_of("12") is None,
      "номер транзакции Octo: заказ + попытка, чужой формат — нет заказа")
sig = hashlib.sha1(b"UKEY" + b"uuid-1" + b"succeeded").hexdigest().upper()
check(payments.octo_sign_ok("UKEY", "uuid-1", "succeeded", sig)
      and not payments.octo_sign_ok("UKEY", "uuid-1", "canceled", sig)
      and not payments.octo_sign_ok("", "uuid-1", "succeeded", sig), "подпись уведомления: sha1(key+uuid+status)")
check(payments.octo_data({"error": 2, "errMessage": "Wrong secret", "data": None}) == (None, "2: Wrong secret"),
      "ошибка Octo читается")
check(payments.octo_amount_ok(31750.0, "31750", "UZS") and not payments.octo_amount_ok(31749, "31750", "UZS")
      and payments.octo_amount_ok("2.5", "2.50", "USD"), "сумма Octo сверяется числом")

OCTO = {"calls": [], "tx": {}}


def fake_octo(path, body):
    OCTO["calls"].append((path, dict(body)))
    if body.get("octo_secret") != "SEC":
        return {"error": 2, "errMessage": "Wrong secret", "data": None}
    tx = body["shop_transaction_id"]
    if "total_sum" in body:                       # заведение платежа
        OCTO["tx"][tx] = {"status": "created", "total_sum": body["total_sum"], "currency": body["currency"],
                          "uuid": "uuid-" + tx}
        return {"error": 0, "data": {"shop_transaction_id": tx, "octo_payment_UUID": "uuid-" + tx,
                                     "status": "created", "octo_pay_url": "https://pay2.octo.uz/pay/uuid-" + tx}}
    t = OCTO["tx"].get(tx)
    if not t:
        return {"error": 5, "errMessage": "not found", "data": None}
    return {"error": 0, "data": {"shop_transaction_id": tx, "octo_payment_UUID": t["uuid"], "status": t["status"],
                                 "total_sum": t["total_sum"], "currency": t["currency"]}}


main._octo_post = fake_octo
check(not {x["id"]: x for x in c.get("/api/pay", headers=H(T)).json()["methods"]}["card"]["online"], "без ключей Octo карта — «по счёту»")
os.environ["OCTO_SHOP_ID"] = "123"
os.environ["OCTO_SECRET"] = "SEC"
os.environ["OCTO_TEST"] = "1"
m = {x["id"]: x for x in c.get("/api/pay", headers=H(T)).json()["methods"]}
check(m["card"]["online"] and m["card"]["currency"] == "UZS", "с ключами Octo карта онлайн, в сумах")
r = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "card"})
oc = r.json()["order"]
body = OCTO["calls"][-1][1]
check(r.status_code == 200 and oc["online"] and oc["url"].startswith("https://pay2.octo.uz/pay/"),
      "заказ картой: платёж заведён у Octo, ссылка на кассу")
check(body["test"] is True and body["auto_capture"] is True and body["total_sum"] == 31750
      and body["currency"] == "UZS" and body["payment_methods"] == [{"method": "bank_card"}]
      and body["notify_url"].endswith("/api/pay/octo") and body["shop_transaction_id"] == "mct-%d-1" % oc["id"],
      "запрос prepare_payment: тест, одностадийный, сумма в сумах, Visa/MC, адрес уведомлений")
tx = body["shop_transaction_id"]
before = float(main._tenant_rec("trial")["pagesCredit"])
# Поддельное уведомление «оплачено», а у Octo платёж не оплачен — не зачисляем.
r = c.post("/api/pay/octo", json={"shop_transaction_id": tx, "octo_payment_UUID": "uuid-" + tx,
                                  "status": "succeeded", "signature": "X", "total_sum": 31750})
check(r.status_code == 200 and main._pays().pay_get(oc["id"])["status"] == "new"
      and abs(float(main._tenant_rec("trial")["pagesCredit"]) - before) < 1e-6,
      "уведомление «оплачено» без подтверждения Octo не зачисляет")
OCTO["tx"][tx]["status"] = "wait_user_action"
c.get("/api/pay/orders/%d" % oc["id"], headers=H(T))
check(c.post("/api/pay/orders/%d/cancel" % oc["id"], headers=H(T)).status_code == 409
      and c.post("/api/admin/payments/%d/confirm" % oc["id"], headers=H(A), json={}).status_code == 409,
      "пока человек вводит код с карты, заказ не отменить и не подтвердить руками")
OCTO["tx"][tx]["status"] = "succeeded"
r = c.post("/api/pay/octo", json={"shop_transaction_id": tx, "octo_payment_UUID": "uuid-" + tx, "status": "succeeded"})
check(r.status_code == 200 and main._pays().pay_get(oc["id"])["status"] == "paid"
      and abs(float(main._tenant_rec("trial")["pagesCredit"]) - before - 5) < 1e-6,
      "Octo подтвердил оплату — заказ оплачен, 5 стр. зачислено")
c.post("/api/pay/octo", json={"shop_transaction_id": tx, "status": "succeeded"})
check(abs(float(main._tenant_rec("trial")["pagesCredit"]) - before - 5) < 1e-6,
      "повтор уведомления второй раз не зачисляет")
check(c.post("/api/pay/octo", json={"shop_transaction_id": "mct-999999-1", "status": "succeeded"}).status_code == 404
      and c.post("/api/pay/octo", content=b"not json").status_code == 400,
      "неизвестный заказ — 404, мусор — 400")
# Оплата не той суммой не зачисляется.
o3 = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "card"}).json()["order"]
tx3 = "mct-%d-1" % o3["id"]
OCTO["tx"][tx3].update(status="succeeded", total_sum=100)
before = float(main._tenant_rec("trial")["pagesCredit"])
r = c.get("/api/pay/orders/%d" % o3["id"], headers=H(T))
check(r.json()["order"]["status"] == "new" and abs(float(main._tenant_rec("trial")["pagesCredit"]) - before) < 1e-6,
      "Octo оплачен НЕ той суммой — не зачисляем")
# Возврат с кассы без уведомления: GET заказа спрашивает статус сам.
o4 = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "card"}).json()["order"]
OCTO["tx"]["mct-%d-1" % o4["id"]]["status"] = "succeeded"
check(c.get("/api/pay/orders/%d" % o4["id"], headers=H(T)).json()["order"]["status"] == "paid",
      "возврат с кассы: статус спрошен у Octo, заказ оплачен без уведомления")
# Сбой при заведении: ссылки нет, GET заказа заводит платёж заново.
main._octo_post = lambda path, body: {"error": 2, "errMessage": "Wrong secret", "data": None}
o5 = c.post("/api/pay/orders", headers=H(T), json={"pages": 5, "method": "card"}).json()["order"]
check(o5["online"] and not o5["url"], "Octo отказал — заказ есть, ссылки нет")
main._octo_post = fake_octo
o5 = c.get("/api/pay/orders/%d" % o5["id"], headers=H(T)).json()["order"]
check(o5["url"] and "mct-%d-2" % o5["id"] in o5["url"], "повторный заход заводит платёж новой попыткой")
ad = c.get("/api/admin/payments", headers=H(A)).json()
check(ad["providers"]["octo"] and ad["providers"]["octoTest"] and ad["callbacks"]["octo"].endswith("/api/pay/octo"),
      "админка знает про Octo и его адрес уведомлений")
for k in ("OCTO_SHOP_ID", "OCTO_SECRET", "OCTO_TEST"):
    os.environ.pop(k, None)

print("=== 6. Минуты видео ===")
media.available = lambda: (True, "")
PROBE = {"duration": 125.0, "container": "mov,mp4", "video": {"codec": "h264", "width": 1280, "height": 720},
         "audio": {"codec": "aac", "channels": 2}, "audioTracks": 1}
media.probe = lambda path: dict(PROBE)
main._media_disk_refusal = lambda need: None


def upload(tok, dur):
    PROBE["duration"] = dur
    d = os.urandom(300)
    t = c.post("/api/media/upload", headers=H(tok), json={"name": "v%d.mp4" % int(dur), "size": len(d),
                                                         "src": "RU", "tgt": "EN"}).json()["token"]
    c.post("/api/media/upload/%s/chunk?offset=0" % t, headers=H(tok), content=d)
    return c.post("/api/media/upload/%s/finish" % t, headers=H(tok))


# Без кошелька — страницами, как раньше.
V = mkorg("vid", pagesCredit=50.0, pagesUsed=0.0, limitUsd=5.0)
r = upload(V, 125.0)
check(r.status_code == 200 and r.json().get("mediaBill") is None, "без кошелька минут видео идёт страницами")
# С кошельком: 125 с = 3 минуты.
c.post("/api/admin/tenants/vid", headers=H(A), json={"addMinutes": 5})
r = upload(V, 125.0)
P = r.json()
check(r.status_code == 200 and P.get("mediaBill") == "min" and P.get("mediaMinBooked") == 3.0,
      "с кошельком: 125 с → 3 минуты, проект на минутах")
mm = main._tenant_minutes("vid")
check(mm["used"] == 3.0 and mm["left"] == 2.0, "списано 3 из 5")
r = upload(V, 600.0)
P2 = r.json()
check(r.status_code == 200 and P2.get("mediaExcerpt", {}).get("sec") == 120.0 and P2.get("mediaMinBooked") == 2.0,
      "10 минут при остатке 2 — распознаём начало на 2 минуты")
r = upload(V, 60.0)
check(r.status_code == 402 and r.json().get("code") == "minutes" and r.json().get("need") == 1,
      "остатка нет — 402 с кодом «minutes» и нехваткой")
check(c.post("/api/admin/tenants/vid", headers=H(A), json={"addMinutes": -100}).status_code == 400,
      "минут не может стать меньше нуля")
# Пол по словам: 3 оплаченные минуты, а слов на 5 страниц (1250 слов при 260 в минуту = 5 мин).
proj = main.get_project.__wrapped__(P["id"]) if hasattr(main.get_project, "__wrapped__") else next(
    x for x in main.STATE["projects"] if x["id"] == P["id"])
proj["mediaStatus"] = "ready"
proj["mediaPages"] = 5.0
main._book_media_minutes(proj)
check(proj["mediaMinBooked"] == 5.0 and main._tenant_minutes("vid")["used"] == 7.0,
      "ускоренная речь: досписано 2 минуты по словам")
main._book_media_minutes(proj)
check(main._tenant_minutes("vid")["used"] == 7.0, "второй раз не досписывает (высшая точка)")
u0 = main._tenant_usage("vid")
check(u0["mediaPages"] == 0.0, "речь минутного проекта в страницы не идёт")

print("=== 7. Расход по проектам за период ===")
tok = main.CURRENT_SESSION.set({"tenant": "vid", "user": 1, "role": "owner"})
ptok = main._USAGE_PROJECT.set(P["id"])
try:
    main._note_cost("translate", "gpt-x", 100, 0, 50, 0, 0.25)
    main._note_cost("backcheck", "gpt-x", 100, 0, 50, 0, 0.05)
finally:
    main._USAGE_PROJECT.reset(ptok)
    main.CURRENT_SESSION.reset(tok)
day = main._biz_day()
r = c.get("/api/admin/project-spend?from=%s&to=%s" % (day, day), headers=H(A))
d = r.json()
row = next((x for x in d["rows"] if x["tenant"] == "vid" and x["project"] == P["id"]), None)
check(r.status_code == 200 and row and abs(row["usd"] - 0.30) < 1e-9 and row["calls"] == 2,
      "расход проекта за сегодня: $0.30 за 2 вызова")
check(row and row["steps"].get("translate") == 0.25 and row["kind"] == "video", "разбивка по шагам и вид проекта")
check(row and abs(row["minutes"] - 5.0) < 1e-9, "продано минут за день: 3 + 2 по словам")
r = c.get("/api/admin/project-spend?from=2020-01-01&to=2020-01-02", headers=H(A))
check(r.json()["rows"] == [], "за другой период — пусто")
check(c.get("/api/admin/project-spend", headers=H(V)).status_code == 403, "владельцу — 403")
check(d.get("since") == day, "с какого дня ведётся учёт")

print("=== 8. Что не уезжает наружу ===")
seed = c.get("/api/seed", headers=H(T)).json()
check("payConfig" not in seed and "payOrders" not in seed, "/api/seed без настроек и заказов оплат")
me = c.get("/api/auth/me", headers=H(T)).json()
check("payApplied" not in (me.get("tenant") or {}) and "minutes" in me, "/api/auth/me: минуты есть, внутренностей нет")
check(c.post("/api/pay/payme", json={"id": 1, "method": "CheckPerformTransaction", "params": {}}).json()["error"]["code"]
      == -32504, "колбэк без входа — отказ протокола, а не 401")
os.environ.pop("PAYME_KEY")
check(rpc("CheckPerformTransaction", {"amount": 1, "account": {"order_id": "1"}})["error"]["code"] == -32504,
      "ключ Payme не задан — дверь закрыта")

print("=== 9. Фикстура рендер-теста — форма НАСТОЯЩИХ ответов ===")
# tests/test_pay_render.js рисует экраны этими ответами (заглушка, написанная
# вместе с экраном, повторяет его предположения и поломку формы не видит).
# Здесь сверяется, что форма ответов с фикстурой не разошлась.
import json                                              # noqa: E402
fx_path = Path("tests/fixtures/pay_payloads.json")
os.environ["PAYME_KEY"] = "KEY"
live = {"pay": c.get("/api/pay", headers=H(T)).json(),
        "adminPayments": c.get("/api/admin/payments", headers=H(A)).json(),
        "projectSpend": c.get("/api/admin/project-spend?from=%s&to=%s" % (day, day), headers=H(A)).json()}


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()} if len(v) < 40 else "dict"
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__


if os.environ.get("PAY_FIXTURE_WRITE") == "1" or not fx_path.exists():
    fx_path.write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
fx = json.loads(fx_path.read_text(encoding="utf-8"))
for k in live:
    a, b = shape(live[k]), shape(fx.get(k))
    check(a == b, "форма ответа «%s» совпадает с фикстурой рендер-теста" % k)

print()
print("ПРОШЛО" if not fail else "УПАЛО: %d" % len(fail))
sys.exit(1 if fail else 0)
