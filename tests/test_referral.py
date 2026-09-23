# -*- coding: utf-8 -*-
"""Приглашения: кто привёл клиента, тот получает страницы.

Здесь считаются ДЕНЬГИ, поэтому сторожится не «работает ли кнопка»,
а ровно те места, где страницы можно получить даром:

  1. ССЫЛКА — НЕ ДВЕРЬ. Она только метка происхождения: регистрация по ней
     идёт через ту же форму с почтой, паролем и согласием. Тот же закон,
     по которому у приглашения в команду нет ссылки из письма.
  2. ПЛАТИМ ПО ПОДТВЕРЖДЁННОЙ ПОЧТЕ. Организация заводится ДО письма,
     а `emailVerified` гейтит только вход: начисление в `register` раздавало
     бы страницы за POST с адресом, которого никто не открывал.
  3. ПРОЦЕНТ — С ВЫСШЕЙ ТОЧКИ. «+100 / −100 / +100» по сумме пополнений
     оплатилось бы дважды за одни и те же сто страниц.
  4. СТАРТОВЫЙ ЛИМИТ ИЗ ОКРУЖЕНИЯ ПРОЦЕНТОМ НЕ ОПЛАЧИВАЕТСЯ: это умолчание
     сервиса, а не оплата клиента.
  5. КОМАНДА РЕФЕРАЛОМ НЕ СЧИТАЕТСЯ: `POST /api/teams` — вторая фабрика
     арендаторов, без почты и без проверки.
  6. САМОПРИГЛАШЕНИЕ не платит, отключённый пригласивший не получает,
     выключенная программа не начисляет НИЧЕГО.
  7. Ключ `referral` не уходит в `/api/seed`, поля `ref*` не текут
     в `/api/auth/me` (там белый список из трёх полей).

Ни одного вызова модели, файл состояния не пишется.
"""
import os
import sys

os.environ["APP_PASSWORD"] = "test-referral-password"
os.environ["SIGNUP_ENABLED"] = "1"
os.environ["TENANT_MAX_PAGES"] = "200"          # стартовый лимит — см. закон 4
sys.path.insert(0, "backend")
sys.path.insert(0, ".")
import main                                              # noqa: E402
from starlette.testclient import TestClient              # noqa: E402

main.save_state = lambda *a, **k: None
main.TENANT_MAX_PAGES = 200.0
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main.STATE["referral"] = {}
main._SESSIONS.clear()
main._LOGIN_FAILS.clear()
main._SIGNUP_FAILS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}           # noqa: E731
ref = main.referral_mod


def mkuser(login, tenant, role="owner", super=False, verified=True):
    h, salt = main._hash_password("password-123")
    u = {"id": max((x["id"] for x in main._users()), default=0) + 1, "tenant": tenant,
         "login": login, "email": login + "@example.com", "emailVerified": verified,
         "hash": h, "salt": salt, "role": role, "super": super, "name": login,
         "active": True, "uiLang": main.DEFAULT_UI_LANG, "created": "2026-01-01"}
    main._users().append(u)
    if not main._tenant_rec(tenant):
        main._tenants().append({"id": tenant, "name": tenant.upper(), "active": True,
                                "created": "2026-01-01"})
    return u


def login(name):
    r = c.post("/api/auth/login", json={"login": name, "password": "password-123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def cfg(**kw):
    s = ref.settings(main.STATE)
    s.update(kw)
    return s


def credit(tid):
    return float((main._tenant_rec(tid) or {}).get("pagesCredit") or 0.0)


owner = mkuser("owner", "acme")
tr = mkuser("tr", "acme", role="translator")
root = mkuser("root", "sys", super=True)
owner_t, tr_t, root_t = login("owner"), login("tr"), login("root")

print("=== 1. Выключено — это ответ, а не ошибка ===")
cfg(enabled=False)
r = c.get("/api/referral", headers=H(owner_t))
check(r.status_code == 200 and r.json()["enabled"] is False,
      "выключенная программа отвечает enabled:false, а не 404")
check("code" not in r.json(), "кода выключенная программа не выдаёт")
check(c.get("/api/referral").status_code == 401, "без токена — 401")

print("=== 2. Ссылка — владельцу, и код выдаётся ЛЕНИВО ===")
cfg(enabled=True, signupPages=10, welcomePages=5, percent=10)
check(main._tenant_rec("acme").get("refCode") is None, "до запроса кода на записи нет")
r = c.get("/api/referral", headers=H(owner_t)).json()
code = r["code"]
check(ref.CODE_RE.match(code), "код имеет форму: " + code)
check(r["link"].endswith("/?ref=" + code), "ссылка собрана из PUBLIC_BASE_URL")
check(c.get("/api/referral", headers=H(owner_t)).json()["code"] == code,
      "второй запрос отдаёт ТОТ ЖЕ код, а не новый")
# Переводчик в той же организации ссылки не получает: это деньги организации.
check(c.get("/api/referral", headers=H(tr_t)).status_code == 403,
      "переводчику — 403 (проверка в обработчике, роль из сессии)")

print("=== 3. Ссылка не входит и не заводит запись ===")
before_u, before_t = len(main._users()), len(main._tenants())
r = c.get("/api/auth/signup-info")
check(r.status_code == 200, "экран входа отвечает как раньше")
check(len(main._users()) == before_u and len(main._tenants()) == before_t,
      "переход по ссылке сам по себе не создаёт ни человека, ни организации")

print("=== 4. Регистрация по коду: метка есть, денег ПОКА нет ===")
main._SIGNUP_FAILS.clear()
r = c.post("/api/auth/register", json={"email": "new@example.com", "password": "password-123",
                                       "org": "Новая", "accept": True, "ref": code})
check(r.status_code == 200, "регистрация прошла: " + r.text[:120])
newt = r.json()["tenant"]
check(main._tenant_rec(newt).get("refBy") == code, "метка происхождения записана")
check(credit("acme") == 0.0,
      "за НЕподтверждённую почту пригласившему не начислено ничего (закон 2)")

print("=== 5. Почта подтверждена — вот теперь платим ===")
u_new = main._user_by_email("new@example.com")
# Почта подтверждается ПО-НАСТОЯЩЕМУ: и бонус за регистрацию, и процент
# стоят на доказанной почте (закон 2), и обойти это в тесте значило бы
# проверять не ту систему, которая поедет на сервер.
u_new["emailVerified"] = True
main._referral_on_verified(u_new)
check(credit("acme") == 200.0 + 10.0,
      "пригласившему +10 сверх стартового лимита 200: " + str(credit("acme")))
check(credit(newt) == 200.0 + 5.0,
      "приглашённому приветственные +5: " + str(credit(newt)))
inv = main._tenant_rec(newt)
check(inv.get("refPaid") == 205.0,
      "высшая точка = стартовый лимит + приветственные (процентом они не платятся)")
# Повтор по той же записи ничего не добавляет.
main._referral_on_verified(u_new)
check(credit("acme") == 210.0, "второе подтверждение по той же записи не платит дважды")

print("=== 6. Процент — с ВЫСШЕЙ ТОЧКИ, а не с суммы пополнений ===")
# Сценарий из разбора: +100, +50, −30, +40 при проценте 10.
# Правильные начисления: 10, 5, 0, 1 — итого 16 = 10% от итоговых 160
# сверх базы 205. По сумме пополнений вышло бы 19: минус 30 «продался» дважды.
base = credit("acme")
seq = [(100, 10.0), (50, 5.0), (-30, 0.0), (40, 1.0)]
for add, want in seq:
    was = credit("acme")
    r = c.post("/api/admin/tenants/%s" % newt, headers=H(root_t), json={"addPages": add})
    check(r.status_code == 200, "пополнение %+d принято" % add)
    got = round(credit("acme") - was, 3)
    check(abs(got - want) < 0.001,
          "за %+d начислено %.1f (ожидалось %.1f)" % (add, got, want))
check(abs(credit("acme") - (base + 16.0)) < 0.001,
      "итог 16 = 10%% от 160 сверх базы, а не 19: " + str(credit("acme") - base))
check(abs(credit(newt) - (205.0 + 160.0)) < 0.001,
      "у приглашённого на счету ровно то, что ему выдали")

print("=== 7. Самоприглашение не платит ===")
me_rec = main._tenant_rec("acme")
me_rec["refBy"] = code            # сам себя
was = credit("acme")
main._referral_on_topup("acme")
check(credit("acme") == was, "код своей же организации ничего не начисляет")
me_rec.pop("refBy", None)

print("=== 8. Команда рефералом не считается (вторая фабрика арендаторов) ===")
team = {"id": "team-x", "name": "Команда", "active": True, "team": True,
        "created": "2026-01-01", "refBy": code, "pagesCredit": 0.0}
main._tenants().append(team)
was = credit("acme")
main._pages_topup("team-x", 500, None)
main._referral_on_topup("team-x")
check(credit("acme") == was, "за пополнение КОМАНДЫ процент не платится")

print("=== 9. Отключённый пригласивший не получает ===")
main._tenant_rec("acme")["active"] = False
was = credit("acme")
r = c.post("/api/admin/tenants/%s" % newt, headers=H(root_t), json={"addPages": 100})
check(credit("acme") == was, "отключённой организации не начисляем")
main._tenant_rec("acme")["active"] = True
main._tenant_rec(newt)["refPaid"] = round(credit(newt), 3)   # догнали высшую точку

print("=== 10. Потолки ===")
# Потолок на одного приглашённого: 10% от 1000 — это 100, но больше
# остатка потолка отдать нельзя. Считается он от УЖЕ выплаченного за эту
# организацию (`refPaidOut`), поэтому сначала обнуляем счёт, иначе проверка
# прошла бы просто потому, что потолок давно выбран.
inv_rec = main._tenant_rec(newt)
inv_rec["refPaidOut"] = 0.0
inv_rec["refPaid"] = round(credit(newt), 3)
cfg(maxPerInvitee=3, maxTotal=0, percent=10)
was = credit("acme")
c.post("/api/admin/tenants/%s" % newt, headers=H(root_t), json={"addPages": 1000})
got = round(credit("acme") - was, 3)
check(abs(got - 3.0) < 0.001,
      "потолок срезал 100 до 3: " + str(got))
# Высшая точка двигается ВСЕГДА, когда процент посчитан: иначе следующее
# пополнение пересчитало бы процент с того же роста и отдало бы срезанное
# по кусочкам, обойдя потолок.
check(abs(float(inv_rec["refPaid"]) - credit(newt)) < 0.001,
      "высшая точка догнала выданное, хотя выплату срезали")
was = credit("acme")
c.post("/api/admin/tenants/%s" % newt, headers=H(root_t), json={"addPages": 10})
check(abs(credit("acme") - was) < 0.001,
      "потолок выбран — следующее пополнение не доплачивает срезанное")
cfg(maxPerInvitee=0, maxTotal=0)

print("=== 11. Выключенная программа не начисляет ничего ===")
cfg(enabled=False)
was = credit("acme")
main._tenant_rec(newt)["refPaid"] = 0.0          # даже при «недоплаченной» базе
main._referral_on_topup(newt)
check(credit("acme") == was, "выключено — ноль начислений")
cfg(enabled=True)

print("=== 12. Неизвестный код регистрацию не роняет ===")
main._SIGNUP_FAILS.clear()
r = c.post("/api/auth/register", json={"email": "x2@example.com", "password": "password-123",
                                       "org": "X2", "accept": True, "ref": "ZZZZZZZZ"})
check(r.status_code == 200, "чужая ссылка не закрывает регистрацию")
u2 = main._user_by_email("x2@example.com")
main._referral_on_verified(u2)
check(True, "подтверждение с несуществующим кодом не упало")
# Мусор в коде до записи не доходит.
check(ref.norm_code("<script>") == "", "мусорный код отвергается формой")
check(ref.norm_code(" abcd-efgh ") == "ABCDEFGH", "код приводится к канону")

print("=== 13. Настройку правит только суперпользователь ===")
check(c.get("/api/admin/referral", headers=H(owner_t)).status_code == 403,
      "владельцу организации настройка закрыта (иначе он правил бы процент себе)")
check(c.post("/api/admin/referral", headers=H(owner_t), json={"percent": 99}).status_code == 403,
      "и на запись тоже")
r = c.post("/api/admin/referral", headers=H(root_t), json={"percent": 7, "signupPages": 2})
check(r.status_code == 200 and r.json()["referral"]["percent"] == 7, "суперпользователь правит")
check(c.post("/api/admin/referral", headers=H(root_t), json={"percent": -1}).status_code == 400,
      "отрицательный процент — 400")
check(c.post("/api/admin/referral", headers=H(root_t), json={"percent": 101}).status_code == 400,
      "процент больше 100 — 400 (мы бы доплачивали за оплату)")
# Опечатка на три нуля раздала бы книгу каждому пришедшему раньше,
# чем это заметят: страницы отсюда попадают прямо в `pagesCredit`.
check(c.post("/api/admin/referral", headers=H(root_t),
             json={"signupPages": main.REFERRAL_PAGES_MAX + 1}).status_code == 400,
      "страниц больше потолка за одно приглашение — 400, а не молча")
check(ref.settings(main.STATE)["percent"] == 7, "отклонённая команда настройку не испортила")

print("=== 14. Удаление организации снимает метку ===")
victim = main._tenant_rec(newt)
victim_code = main._ref_code_of(newt)
child = {"id": "child-x", "name": "Дочерняя", "active": True, "created": "2026-01-01",
         "refBy": victim_code, "refPaid": 10.0, "refPaidOut": 3.0}
main._tenants().append(child)
main.STATE["projects"] = [p for p in main.STATE["projects"] if main._tenant_of(p) != newt]
for u in list(main._users()):
    if u.get("tenant") == newt:
        main._users().remove(u)
r = c.request("DELETE", "/api/admin/tenants/%s" % newt, headers=H(root_t))
check(r.status_code == 200, "организация удалена: " + r.text[:120])
check(child.get("refBy") is None,
      "метка, указывавшая на удалённого, снята — номер переиспользуется")
check(child.get("refPaid") is None,
      "и высшая точка снята вместе с ней: иначе новая организация под тем же "
      "именем унаследовала бы чужую оплату")

print("=== 15. Наружу лишнего не уходит ===")
seed = c.get("/api/seed", headers=H(owner_t)).json()
check("referral" not in seed, "ключа referral в /api/seed нет (белый список инварианта 25)")
me = c.get("/api/auth/me", headers=H(owner_t)).json()
check(set(me["tenant"]) <= {"id", "name", "active"},
      "поля организации в /auth/me — прежний белый список: " + str(sorted(me["tenant"])))
check(not any(k.startswith("ref") for k in me["tenant"]), "ref* браузеру не текут")

print("=== 16. Бонус НЕ ДОЛЖЕН вредить ===")
# Самый дорогой урок задачи: `pagesCredit` — это «сколько ВЫДАНО», и поля
# НЕТ значит «без потолка». `_pages_topup` поле ЗАВОДИТ, начиная от
# TENANT_MAX_PAGES (по умолчанию НОЛЬ). Значит «бонус +10» организации
# без счётчика означал бы «было без потолка — стало десять», и книга
# на полсотни страниц тут же отвечала бы 402. Подарок, запирающий клиента,
# — худшее, что может сделать программа приглашений.
main.TENANT_MAX_PAGES = 0.0
free = {"id": "free-org", "name": "Без потолка", "active": True, "created": "2026-01-01",
        "refCode": "FREECODE"}
kid = {"id": "free-kid", "name": "Новичок", "active": True, "created": "2026-01-01",
       "refBy": "FREECODE"}
main._tenants().extend([free, kid])
main._users().append({"id": 900, "tenant": "free-kid", "login": "kid", "email": "kid@e.com",
                      "emailVerified": True, "hash": "x", "salt": "y", "role": "owner",
                      "active": True, "created": "2026-01-01"})
cfg(enabled=True, signupPages=10, welcomePages=5, percent=10)
check(not main._tenant_caps("free-org")["pagesLimited"], "до бонуса организация без потолка")
main._referral_on_verified(main._users()[-1])
check(not main._tenant_caps("free-org")["pagesLimited"],
      "и ПОСЛЕ бонуса тоже: начисление не превращает «без потолка» в потолок")
check(not main._tenant_caps("free-kid")["pagesLimited"],
      "приглашённого приветственные тоже не запирают")
main.TENANT_MAX_PAGES = 200.0

print("=== 16а. Процент — только по ПОДТВЕРЖДЁННОЙ почте ===")
# Закон 2 обязан стоять на ОБЕИХ дверях. У бонуса за регистрацию он держится
# на отметке `refPaidAt`, а процент её не ставит и не читает: организация
# заводится ДО письма, и пополнение, сделанное раньше подтверждения, платило
# бы за адрес, которого никто не открывал.
cfg(enabled=True, percent=10, signupPages=0, welcomePages=0,
    maxPerInvitee=0, maxTotal=0)
unv = {"id": "unv-org", "name": "Неподтверждённая", "active": True,
       "created": "2026-01-01", "refBy": code, "refPaid": 0.0,
       "pagesCredit": 0.0, "pagesUsed": 0.0}
main._tenants().append(unv)
main._users().append({"id": 901, "tenant": "unv-org", "login": "unv", "email": "unv@e.com",
                      "emailVerified": False, "hash": "x", "salt": "y", "role": "owner",
                      "active": True, "created": "2026-01-01"})
was = credit("acme")
main._pages_topup("unv-org", 1000, None)
main._referral_on_topup("unv-org")
check(credit("acme") == was, "за пополнение НЕподтверждённой организации процент не платится")
# Подтвердили — и процент идёт СО ВСЕГО, что организации выдали: страницы
# у неё на счету настоящие, и то, что суперпользователь выдал их авансом,
# до письма, ничего не отменяет. Рубеж закона 2 не в том, ЗА ЧТО платить,
# а в том, КОГДА: пока почта не доказана, не платим ничего.
main._users()[-1]["emailVerified"] = True
was2 = credit("acme")
main._pages_topup("unv-org", 100, None)
main._referral_on_topup("unv-org")
check(abs(round(credit("acme") - was2, 3) - 110.0) < 0.001,
      "после подтверждения заплачено 10%% от всех 1100 выданных: "
      + str(round(credit("acme") - was2, 3)))
was3 = credit("acme")
main._pages_topup("unv-org", 50, None)
main._referral_on_topup("unv-org")
check(abs(round(credit("acme") - was3, 3) - 5.0) < 0.001,
      "дальше — только за прирост, дважды за одно не платим")

print("=== 16б. Высшая точка не берётся из воздуха ===")
# Отметку `refBy` мог проставить перенос данных или поддержка руками, и на
# счету организации к этому моменту лежит сколько угодно. Seed одним
# TENANT_MAX_PAGES объявил бы весь остаток «только что оплаченным», и
# пополнение на одну страницу вернуло бы процент со ВСЕГО баланса.
cfg(enabled=True, percent=10, maxPerInvitee=0, maxTotal=0)
rich = {"id": "rich-org", "name": "Богатая", "active": True, "created": "2026-01-01",
        "refBy": code, "pagesCredit": 10000.0, "pagesUsed": 0.0}
main._tenants().append(rich)
main._users().append({"id": 902, "tenant": "rich-org", "login": "rich", "email": "rich@e.com",
                      "emailVerified": True, "hash": "x", "salt": "y", "role": "owner",
                      "active": True, "created": "2026-01-01"})
# Первый заход по такой записи только ЗАПОМИНАЕТ базу и не платит:
# накопленные 10000 оплатой по нашей ссылке не являются.
was = credit("acme")
main._pages_topup("rich-org", 100, None)
main._referral_on_topup("rich-org")
check(round(credit("acme") - was, 3) == 0.0,
      "за накопленный ДО метки баланс не платим ни страницы: "
      + str(round(credit("acme") - was, 3)))
check(main._tenant_rec("rich-org").get("refPaid") == 10100.0,
      "но база запомнена — по ней и пойдёт счёт")
# А вот следующее пополнение — настоящий прирост.
was = credit("acme")
main._pages_topup("rich-org", 100, None)
main._referral_on_topup("rich-org")
got = round(credit("acme") - was, 3)
check(abs(got - 10.0) < 0.001,
      "платим 10%% от ПРИРОСТА (10), а не от накопленного баланса: " + str(got))

print("=== 16в. Нулевые числа не сжигают право на бонус ===")
# Отметка «бонус израсходован» при нулевых числах означала бы: всех, кто
# пришёл ДО того, как владелец назначил цифры, платить уже некому.
cfg(enabled=True, signupPages=0, welcomePages=0, percent=0)
late = {"id": "late-org", "name": "Ранний гость", "active": True,
        "created": "2026-01-01", "refBy": code}
main._tenants().append(late)
main._users().append({"id": 903, "tenant": "late-org", "login": "late", "email": "late@e.com",
                      "emailVerified": True, "hash": "x", "salt": "y", "role": "owner",
                      "active": True, "created": "2026-01-01"})
main._referral_on_verified(main._users()[-1])
check(not late.get("refPaidAt"), "при нулях отметка не ставится")
cfg(signupPages=7)
was = credit("acme")
main._referral_on_verified(main._users()[-1])
check(round(credit("acme") - was, 3) == 7.0, "назначили числа — бонус заплачен, а не сожжён")

print("=== 16г. Команда не приглашает и не приглашается ===")
team_inv = {"id": "team-inv", "name": "Команда-пригласивший", "active": True,
            "team": True, "created": "2026-01-01", "refCode": "TEAMCODE",
            "pagesCredit": 0.0, "pagesUsed": 0.0}
kid2 = {"id": "team-kid", "name": "Гость команды", "active": True,
        "created": "2026-01-01", "refBy": "TEAMCODE"}
main._tenants().extend([team_inv, kid2])
main._users().append({"id": 904, "tenant": "team-kid", "login": "tk", "email": "tk@e.com",
                      "emailVerified": True, "hash": "x", "salt": "y", "role": "owner",
                      "active": True, "created": "2026-01-01"})
was = float(team_inv.get("pagesCredit") or 0)
main._referral_on_verified(main._users()[-1])
check(float(team_inv.get("pagesCredit") or 0) == was,
      "команда не получает и как ПРИГЛАСИВШИЙ (пять команд на человека — пять личностей)")

print("=== 16д. Ссылку читают часто, а пишем один раз ===")
saves = []
real_save = main.save_state
main.save_state = lambda *a, **k: saves.append(1)
for _ in range(4):
    c.get("/api/referral", headers=H(owner_t))
main.save_state = real_save
check(not saves, "код уже есть — повторные открытия экрана состояние НЕ пишут")

print()
print("ПРОВАЛЕНО: %d" % len(fail) if fail else "ВСЁ ПРОШЛО")
for f in fail:
    print("  - " + f)
sys.exit(1 if fail else 0)
