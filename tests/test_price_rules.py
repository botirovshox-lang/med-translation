# -*- coding: utf-8 -*-
"""Цены и лимиты по функциям — для всех, организации и человека (инвариант 40).

  1. Чистые правила: самое точное явное значение сильнее; лимиты уровней
     действуют одновременно; что где задаётся (`allowed`).
  2. Каждый шаг расхода из кода отнесён к функции или к «всё вместе» —
     список шагов выводится из САМОГО main.py; у каждого `_llm_client`
     назван шаг.
  3. Двери админки: только суперпользователь (владелец — 403), запись
     на уровень, снятие, 404 на чужое.
  4. Рубеж по пути: выключенная функция — 403, выбранный лимит — 402
     с кодом и без сумм для не-супера; супер не ограничен.
  5. Второй рубеж в вызове модели (`_llm_limit_gate(step)`), лимит человека
     «всё вместе».
  6. Страницы и минуты за месяц: счётчик, отказ до записи, возврат минут.
  7. Прогон: одиночный вид останавливается, составной — только когда
     закрыто всё; постановка отказывает по тем же правилам.
  8. Цена продажи организации попадает в сумму заказа.
  9. Правила уходят вместе с организацией; в /api/seed и /auth/me их нет.

Ни одного вызова модели, файл состояния не пишется.
"""
import io
import os
import re
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="mct-price-"))
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["PAY_ORDERS_FILE"] = str(TMP / "pay_orders.json")
sys.path.insert(0, "backend")
import main                                              # noqa: E402
import price_rules                                       # noqa: E402
from fastapi import HTTPException                        # noqa: E402
from starlette.testclient import TestClient              # noqa: E402

main.save_state = lambda *a, **k: None
main._ensure_job_worker = lambda: None
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main.STATE["spend"], main.STATE["projects"] = {}, []
main.STATE.pop("payConfig", None)
main.STATE.pop("priceRules", None)
main.STATE["usageDaily"] = {}
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


def uid_of(login):
    return next(u["id"] for u in main._users() if u.get("login") == login)


def rule(scope, ident, fn, **kw):
    return c.post("/api/admin/prices", headers=H(A),
                  json=dict(scope=scope, id=None if ident is None else str(ident), fn=fn, **kw))


print("=== 1. Чистые правила ===")
lv = [("user", {"review": {"off": False}}), ("tenant", {"review": {"off": True, "limit": 5}}),
      ("all", {"review": {"limit": 10}})]
e = price_rules.effective(lv, "review")
check(e["off"] is False and e["offFrom"] == "user", "явное «включено» человека сильнее выключения организации")
check(e["tenantLimit"] == 5 and e["tenantLimitFrom"] == "tenant", "лимит организации сильнее общего")
e = price_rules.effective([("user", {}), ("tenant", {}), ("all", {"review": {"limit": 10}})], "review")
check(e["tenantLimit"] == 10 and e["tenantLimitFrom"] == "all", "общее правило — умолчание для каждой организации")
check(not price_rules.allowed("all", "pages")["limit"], "общий лимит страниц не задаётся (запер бы первого клиента)")
check(not price_rules.allowed("user", "pages")["price"] and price_rules.allowed("tenant", "pages")["price"],
      "цена продажи — только у организации")
check(not price_rules.allowed("tenant", "all")["limit"] and price_rules.allowed("user", "all")["limit"],
      "«всё вместе» здесь — только у человека (у организации это limitUsd)")
try:
    price_rules.clean_rule("tenant", "pages", off=True)
    check(False, "перевод документов не выключается")
except ValueError:
    check(True, "перевод документов не выключается")
r = price_rules.clean_rule("tenant", "pages", price="0,40", limit="0")
check(r == {"price": "0.4", "limit": 0.0}, "цена с запятой, лимит ноль — законное «нельзя»: " + str(r))
check(price_rules.job_fns("full", {"steps": ["translate", "backcheck", "termcheck"]}) == ["translate", "checks"],
      "функции составного прогона — по шагам")
check(price_rules.job_fns("mediarender", {"what": "burn"}) == [] and
      price_rules.job_fns("mediarender", {"what": "dub"}) == ["speech"], "субтитры бесплатны, озвучка — речь")

print("=== 2. Шаги расхода и вызовы модели ===")
src = io.open("backend/main.py", encoding="utf-8").read()
steps = set(re.findall(r'_note_(?:usage|audio)\("([a-z_]+)"', src))
steps |= set(re.findall(r'step="([a-z_]+)"', src))
steps |= {"backcheck", "translate"}          # шаг переменной в `_openai_translate`
lost = sorted(s for s in steps if s not in price_rules.STEP_FN and s not in price_rules.ONLY_ALL)
check(len(steps) > 12 and not lost, "каждый шаг расхода отнесён к функции: " + str(lost))
calls = re.findall(r"_llm_client\(mdl[^\n]*", src)
check(len(calls) >= 17 and all("step=" in x for x in calls), "у каждого вызова модели назван шаг")
check(all(k in price_rules.FUNC_KEYS for k in set(price_rules.STEP_FN.values())), "шаги ведут в каталог")

print("=== 3. Двери админки ===")
T = mkorg("acme", pagesCredit=100.0, pagesUsed=0.0)
O = mkorg("other")
ACME = uid_of("acme")
r_ = c.get("/api/admin/prices", headers=H(T))
check(r_.status_code == 403, "владелец организации админку цен не видит: " + str(r_.status_code))
r_ = c.post("/api/admin/prices", headers=H(T), json={"scope": "tenant", "id": "acme", "fn": "review", "off": False})
check(r_.status_code == 403, "и лимит себе не ставит")
check(rule("tenant", "nope", "review", off=True).status_code == 404, "чужая/несуществующая организация — 404")
check(rule("user", 999999, "review", off=True).status_code == 404, "несуществующий человек — 404")
check(rule("all", None, "pages", price="0.3").status_code == 400, "цена «всем» — в настройках оплат, не здесь")
check(rule("tenant", "acme", "pages", price="0.25").status_code == 200, "своя цена страницы организации")
v = c.get("/api/admin/prices?scope=tenant&id=acme", headers=H(A)).json()
row = next(x for x in v["view"]["rows"] if x["fn"] == "pages")
check(row["price"] == "0.25" and row["priceFrom"] == "tenant", "вид уровня показывает свою цену и откуда она")
row = next(x for x in v["view"]["rows"] if x["fn"] == "minutes")
check(row["priceFrom"] == "config", "минута без своей цены — из настроек оплат")
check(any(x["scope"] == "tenant" and x["fn"] == "pages" for x in v["rules"]), "правило в списке особых условий")

print("=== 4. Рубеж по пути ===")
check(rule("tenant", "acme", "ocr", off=True).status_code == 200, "чтение сканов выключено организации")
r_ = c.post("/api/quote/scan", headers=H(T), json={})
check(r_.status_code == 403 and r_.json().get("code") == "fnoff" and r_.json().get("fn") == "ocr",
      "выключенная функция — 403 с кодом: " + str(r_.status_code))
r_ = c.post("/api/quote/scan", headers=H(O), json={})
check(r_.status_code not in (402, 403), "соседняя организация не задета")
r_ = c.post("/api/quote/scan", headers=H(A), json={})
check(r_.status_code not in (402, 403), "суперпользователь не ограничен")
rule("tenant", "acme", "ocr", clear=True)
day = main._month_key() + "-02"
main._ledger_write(day, "acme", str(ACME), "scanquote", "m", 1, 10, 0, 10, 0, 0.8, 0)
check(rule("tenant", "acme", "ocr", limit="0.5").status_code == 200, "лимит $0.5 на чтение сканов")
main._fn_spend(force=True)
r_ = c.post("/api/quote/scan", headers=H(T), json={})
b = r_.json()
check(r_.status_code == 402 and b.get("code") == "fnlimit", "выбранный лимит — 402: " + str(r_.status_code))
check("used" not in b and "limit" not in b and "$" not in b.get("error", ""), "не-суперу сумм не показываем (22а)")
rule("tenant", "acme", "ocr", clear=True)
r_ = c.post("/api/quote/scan", headers=H(T), json={})
check(r_.status_code not in (402, 403), "снятое правило больше не держит")

print("=== 5. Вызов модели и лимит человека ===")
tok_sess = main._SESSIONS[T]
t0 = main.CURRENT_SESSION.set(tok_sess)
try:
    rule("user", ACME, "all", limit="0.5")
    try:
        main._llm_limit_gate("translate")
        check(False, "лимит человека «всё вместе» закрыл вызов")
    except HTTPException as ex:
        check(ex.status_code == 402, "лимит человека «всё вместе» закрыл вызов")
    rule("user", ACME, "all", clear=True)
    rule("all", None, "review", off=True)
    try:
        main._llm_limit_gate("guide")
        check(False, "шаг «guide» принадлежит ревизии и закрыт общим правилом")
    except HTTPException as ex:
        check(ex.status_code == 403, "шаг «guide» принадлежит ревизии и закрыт общим правилом")
    rule("user", ACME, "review", off=False)
    try:
        main._llm_limit_gate("guide")
        check(True, "явное «включено» человеку открывает")
    except HTTPException:
        check(False, "явное «включено» человеку открывает")
    rule("all", None, "review", clear=True)
    rule("user", ACME, "review", clear=True)
finally:
    main.CURRENT_SESSION.reset(t0)

print("=== 6. Страницы и минуты за месяц ===")
t0 = main.CURRENT_SESSION.set(tok_sess)
try:
    rule("user", ACME, "pages", limit="10")
    main._pages_debit("acme", 6.0, "sha1:RU→EN", 1, "Книга")
    check(main._fn_used("pages", uid=ACME) == 6.0 and main._fn_used("pages", tid="acme") == 6.0,
          "списание легло в счёт человека и организации")
    try:
        main._pages_debit("acme", 6.0, "sha2:RU→EN", 2, "Вторая")
        check(False, "второй файл сверх лимита человека — отказ")
    except HTTPException as ex:
        check(ex.status_code == 402, "второй файл сверх лимита человека — отказ")
    check(main._tenant_rec("acme")["pagesUsed"] == 6.0, "отказ ничего не списал")
    rule("user", ACME, "pages", clear=True)
    rec = main._tenant_rec("acme")
    main._minutes_topup("acme", 30, "t")
    rule("tenant", "acme", "minutes", limit="5")
    main._minutes_debit("acme", 4, 3, "Видео")
    try:
        main._minutes_debit("acme", 2, 4, "Ещё")
        check(False, "минуты сверх месячного лимита — отказ")
    except HTTPException as ex:
        check(ex.status_code == 402, "минуты сверх месячного лимита — отказ")
    main._minutes_log(rec, "refund", 4, project=3)
    check(main._fn_used("minutes", tid="acme") == 0.0, "возврат минут уменьшает счёт месяца")
    main._minutes_debit("acme", 3, 5, "После возврата")
    check(main._fn_used("minutes", tid="acme") == 3.0, "после возврата снова можно")
    main._minutes_debit("acme", 9, 6, "Досписание", check=False)
    check(True, "досписание после работы лимитом не режется")
    rule("tenant", "acme", "minutes", clear=True)
finally:
    main.CURRENT_SESSION.reset(t0)

print("=== 7. Прогоны ===")
rule("tenant", "acme", "checks", off=True)
job = {"id": 1, "kind": "backcheck", "tenant": "acme", "user": ACME, "params": {}, "counters": {}}
check(main._job_fn_hit(job) and job["stopReason"] == "fnlimit", "одиночный вид с закрытой функцией остановлен")
job = {"id": 2, "kind": "full", "tenant": "acme", "user": ACME, "counters": {},
       "params": {"steps": ["translate", "backcheck"]}}
check(not main._job_fn_hit(job), "составной прогон с одним закрытым шагом идёт дальше")
rule("tenant", "acme", "translate", off=True)
check(main._job_fn_hit(job), "закрыто всё — составной прогон остановлен")
adm = next(u["id"] for u in main._users() if u.get("super"))
job = {"id": 3, "kind": "backcheck", "tenant": "acme", "user": adm, "params": {}, "counters": {}}
check(not main._job_fn_hit(job), "прогон суперпользователя не ограничен")
main.STATE["projects"].append({"id": 77, "title": "P", "tenant": "acme", "src": "RU", "tgt": "EN",
                               "segments": [{"id": 1, "source": "а", "target": "", "status": "new"}]})
r_ = c.post("/api/projects/77/jobs", headers=H(T), json={"kind": "backcheck", "segment_ids": [1]})
check(r_.status_code == 403, "постановка закрытого вида — отказ: " + str(r_.status_code))
rule("tenant", "acme", "translate", clear=True)
rule("tenant", "acme", "checks", clear=True)

print("=== 7а. Бесплатное не режется, ремонт знает про проверки ===")
check("checks" in price_rules.job_fns("repair"), "ремонт требует и проверок: без них правка откатится за деньги")
check(main._fn_paths("POST", "/api/media/upload") == () and
      main._fn_paths("POST", "/api/projects/5/media/render") == () and
      main._fn_paths("POST", "/api/media/upload/abc/finish") == (),
      "возврат исходника и субтитры по пути не режутся (рубеж в обработчиках)")
check("checks" in main._fn_paths("POST", "/api/segments/1/2/repair"), "одиночный ремонт проверяет и проверки")
rule("tenant", "acme", "terms", off=True)
seg = {"id": 1, "source": "Туберкулез лёгких", "target": "Pulmonary tuberculosis",
       "editedFrom": "Lung tuberculosis", "editedToHash": main._text_hash("Pulmonary tuberculosis")}
t0 = main.CURRENT_SESSION.set(tok_sess)
try:
    got = main._harvest_edited_terms(seg, {"id": 77, "src": "RU", "tgt": "EN", "tenant": "acme"})
    check(got.get("skipped") == "fn", "подтверждение при закрытых терминах — пропуск с кодом, не 403: " + str(got.get("skipped")))
except HTTPException as ex:
    check(False, "подтверждение при закрытых терминах — пропуск с кодом, не 403: " + str(ex.status_code))
finally:
    main.CURRENT_SESSION.reset(t0)
rule("tenant", "acme", "terms", clear=True)
rule("tenant", "acme", "minutes", off=True)
main.media_mod.available = lambda: (True, "")      # ffmpeg на машине теста может не стоять
r_ = c.post("/api/media/upload", headers=H(T), json={"name": "a.mp4", "size": 1000, "src": "RU", "tgt": "EN"})
check(r_.status_code == 403, "загрузка нового видео при выключенном видео — отказ до приёма: " + str(r_.status_code))
rule("tenant", "acme", "minutes", clear=True)

print("=== 8. Цена продажи организации в заказе ===")
cfg = main._pay_cfg()
q = main._pay_quote(10, 0, "card", cfg, "acme")
check(q["prices"]["page"] == "0.25" and q["usd"] in ("2.5", "2.50"), "своя цена в сумме заказа: " + str(q.get("usd")))
main._tenant_rec("other").update(pagesCredit=10.0, pagesUsed=0.0)
q = main._pay_quote(10, 0, "card", cfg, "other")
check(q["prices"]["page"] == str(main.payments_mod.dec(cfg["pricePage"])), "у других — общая цена")

print("=== 8а. Форма ответа для рендер-теста ===")
# Рендер-тест вкладки рисует ответами НАСТОЯЩЕЙ двери (закон фикстур
# оплат): заглушка, написанная вместе с экраном, поломку формы не видит.
import json                                              # noqa: E402
rule("tenant", "acme", "review", limit="2", off=True)
rule("user", ACME, "all", limit="7")
rule("all", None, "ocr", limit="1.5")
live = {"all": c.get("/api/admin/prices", headers=H(A)).json(),
        "tenant": c.get("/api/admin/prices?scope=tenant&id=acme", headers=H(A)).json(),
        "user": c.get("/api/admin/prices?scope=user&id=%d" % ACME, headers=H(A)).json()}
check(len(live["user"]["view"]["rows"]) == len(price_rules.FUNCS), "у человека все функции, включая «всё вместе»")
check(len(live["all"]["view"]["rows"]) == len(price_rules.FUNCS) - 1, "у «всем» — без «всё вместе»")
t_all = next(x for x in live["tenant"]["view"]["rows"] if x["fn"] == "all")
check(t_all["limitFrom"] == "tenantLimitUsd", "у организации «всё вместе» — её лимит расхода")
fx_path = Path("tests/fixtures/price_payloads.json")


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()} if len(v) < 40 else "dict"
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    return type(v).__name__


if os.environ.get("PRICE_FIXTURE_WRITE") == "1" or not fx_path.exists():
    fx_path.write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
fx = json.loads(fx_path.read_text(encoding="utf-8"))
for k in live:
    check(shape(live[k]["view"]["rows"][0]) == shape(fx[k]["view"]["rows"][0]) and
          sorted(live[k]) == sorted(fx[k]), "форма ответа «%s» совпадает с фикстурой рендер-теста" % k)
rule("tenant", "acme", "review", clear=True)
rule("user", ACME, "all", clear=True)
rule("all", None, "ocr", clear=True)

print("=== 9. Утечки и удаление ===")
rule("tenant", "other", "review", limit="3")
seed = c.get("/api/seed", headers=H(T)).json()
check("priceRules" not in seed, "/api/seed правил не отдаёт")
me = c.get("/api/auth/me", headers=H(T)).json()
check("fnRules" not in str(me) and "fnUsed" not in str(me), "/api/auth/me правил и счёта не отдаёт")
c.delete("/api/admin/tenants/other", headers=H(A))
main.STATE["tenants"].append({"id": "other", "name": "Новая", "active": True})
check(not (main._tenant_rec("other") or {}).get("fnRules"), "слаг заново — чужих правил нет")

print()
print("ПРОШЛО" if not fail else "УПАЛО: %d" % len(fail))
sys.exit(1 if fail else 0)
