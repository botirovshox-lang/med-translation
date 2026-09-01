"""Команды, приглашения и профиль пользователя (`/api/teams/*`, `/api/profile*`).

Что сторожится и почему именно это:

  1. Команда — это АРЕНДАТОР, и активная команда живёт в СЕССИИ. Значит
     переключение обязано менять и `tenant`, и РОЛЬ: владелец своей команды
     в чужой может быть переводчиком, и оставить ему права владельца значило
     бы отдать чужой глоссарий на вынос.
  2. Изоляция не ослабевает: чужой проект — 404 и после того, как у человека
     появилось второе рабочее пространство. Видит он ровно ту команду,
     которую выбрал.
  3. Приглашение — решение ПРИГЛАШЁННОГО. До «принять» членства нет,
     после «отклонить» — тоже.
  4. Исключённый теряет доступ СРАЗУ (сессия закрывается), а не через
     SESSION_TTL: до истечения токена он работал бы в чужих проектах.
  5. `/api/seed` не отдаёт `invites` — там почты людей из чужих организаций.
  6. Язык интерфейса меняет САМ человек (`POST /api/profile`), в том числе
     переводчик: `/api/admin/users` ему закрыт, а язык менять надо.

Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "test-teams-password"
os.environ["SIGNUP_ENABLED"] = "1"
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["invites"] = []
main.STATE["projects"] = []
main._SESSIONS.clear()
main._LOGIN_FAILS.clear()
main._SIGNUP_FAILS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}


def mkuser(login, email, tenant, role="owner", super=False):
    h, salt = main._hash_password("password-123")
    u = {"id": max((x["id"] for x in main._users()), default=0) + 1, "tenant": tenant,
         "login": login, "email": email, "emailVerified": True, "hash": h, "salt": salt,
         "role": role, "super": super, "name": login, "active": True,
         "uiLang": main.DEFAULT_UI_LANG, "created": "2026-01-01"}
    main._users().append(u)
    if not main._tenant_rec(tenant):
        main._tenants().append({"id": tenant, "name": tenant.upper(), "active": True,
                                "created": "2026-01-01"})
    return u


def login(login_name):
    r = c.post("/api/auth/login", json={"login": login_name, "password": "password-123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


anna = mkuser("anna", "anna@example.com", "acme")
bob = mkuser("bob", "bob@example.com", "bobco")
zed = mkuser("zed", "zed@example.com", "zedco")
anna_t, bob_t = login("anna"), login("bob")

print("=== 1. Профиль: домашняя организация читается членством ===")
r = c.get("/api/profile", headers=H(anna_t))
p = r.json()
check(r.status_code == 200 and len(p["teams"]) == 1 and p["teams"][0]["id"] == "acme",
      "у новичка ровно одна команда — домашняя")
check(p["teams"][0]["home"] is True and p["teams"][0]["role"] == "owner",
      "домашняя помечена home и несёт роль из записи пользователя")
check(p["activeTeam"] == "acme" and p["invites"] == [], "активная команда — домашняя, приглашений нет")
check(p["me"]["uiLang"] == main.DEFAULT_UI_LANG, "язык интерфейса по умолчанию — " + main.DEFAULT_UI_LANG)

print("=== 2. Своё имя, язык и пароль человек меняет сам ===")
r = c.post("/api/profile", headers=H(anna_t), json={"uiLang": "uz"})
check(r.status_code == 200 and r.json()["me"]["uiLang"] == "uz", "язык меняется")
r = c.post("/api/profile", headers=H(anna_t), json={"uiLang": "klingon"})
check(r.status_code == 400, "неизвестный язык — 400 (иначе надписи станут пустыми)")
r = c.post("/api/profile", headers=H(anna_t), json={"password": "new-password-1"})
check(r.status_code == 403, "смена пароля без нынешнего — 403")
r = c.post("/api/profile", headers=H(anna_t),
           json={"password": "new-password-1", "currentPassword": "password-123"})
check(r.status_code == 200, "с нынешним паролем — можно")
check(c.get("/api/profile", headers=H(anna_t)).status_code == 200, "своя сессия пережила смену пароля")
r = c.post("/api/profile", headers=H(anna_t),
           json={"password": "password-123", "currentPassword": "new-password-1"})
check(r.status_code == 200, "пароль возвращён обратно")

print("=== 3. Команда: создание и потолок ===")
r = c.post("/api/teams", headers=H(anna_t), json={"name": "Клиника Шифо"})
check(r.status_code == 200, "команда создана")
team = r.json()["team"]["id"]
check(main._tenant_rec(team).get("limitUsd") == main.SIGNUP_TRIAL_USD,
      "лимит новой команды — как при регистрации (иначе кран к ключу открывается кнопкой)")
check(len(r.json()["teams"]) == 2, "теперь две команды")
r = c.post("/api/teams", headers=H(anna_t), json={"name": "x"})
check(r.status_code == 400, "название короче двух символов — 400")

print("=== 4. Приглашение по почте: только зарегистрированного, только владельцем ===")
r = c.post("/api/teams/" + team + "/invite", headers=H(anna_t),
           json={"email": "nobody@example.com"})
check(r.status_code == 404, "незарегистрированной почты нет — 404, за человека учётку не заводим")
r = c.post("/api/teams/" + team + "/invite", headers=H(bob_t), json={"email": "zed@example.com"})
check(r.status_code == 403, "чужой команде приглашения не рассылает — 403")
r = c.post("/api/teams/" + team + "/invite", headers=H(anna_t), json={"email": "bob@example.com"})
check(r.status_code == 200, "владелец приглашает Боба")
inv = r.json()["invite"]["id"]
r = c.post("/api/teams/" + team + "/invite", headers=H(anna_t), json={"email": "BOB@example.com"})
check(r.status_code == 409, "повторное приглашение той же почте — 409")
check(main._member_role(bob, team) is None, "до решения человека членства НЕТ")

print("=== 5. Решение принимает приглашённый ===")
r = c.post("/api/profile/invites/" + inv, headers=H(anna_t), json={"action": "accept"})
check(r.status_code == 404, "чужое приглашение принять нельзя — 404")
r = c.get("/api/profile", headers=H(bob_t))
check(len(r.json()["invites"]) == 1 and r.json()["invites"][0]["teamName"] == "Клиника Шифо",
      "Боб видит приглашение в своём профиле, с названием команды")
r = c.post("/api/profile/invites/" + inv, headers=H(bob_t), json={"action": "decline"})
check(r.status_code == 200 and main._member_role(bob, team) is None,
      "отклонил — членства нет")
check(c.get("/api/profile", headers=H(bob_t)).json()["invites"] == [],
      "отклонённое приглашение из профиля ушло")
r = c.post("/api/profile/invites/" + inv, headers=H(bob_t), json={"action": "accept"})
check(r.status_code == 409, "решённое приглашение второй раз не решается — 409")

r = c.post("/api/teams/" + team + "/invite", headers=H(anna_t),
           json={"email": "bob@example.com", "role": "translator"})
inv2 = r.json()["invite"]["id"]
r = c.post("/api/profile/invites/" + inv2, headers=H(bob_t), json={"action": "accept"})
check(r.status_code == 200 and main._member_role(bob, team) == "translator",
      "принял — членство появилось с ролью из приглашения")

print("=== 6. Переключение команды меняет и роль, и видимость проектов ===")
main.STATE["projects"] = [
    {"id": 1, "title": "Проект Ани", "tenant": team, "segments": [], "src": "RU", "tgt": "EN"},
    {"id": 2, "title": "Проект Боба", "tenant": "bobco", "segments": [], "src": "RU", "tgt": "EN"},
]
r = c.get("/api/projects/1", headers=H(bob_t))
check(r.status_code == 404, "проект чужой команды не виден, пока она не выбрана — 404")
r = c.post("/api/profile/team", headers=H(bob_t), json={"tenant": team})
check(r.status_code == 200 and r.json()["activeRole"] == "translator",
      "переключился — роль стала ролью В ЭТОЙ команде")
check(r.json()["can"]["owner"] is False, "и права владельца сюда не переехали")
r = c.get("/api/projects/1", headers=H(bob_t))
check(r.status_code == 200, "теперь общий проект команды виден")
r = c.get("/api/projects/2", headers=H(bob_t))
check(r.status_code == 404, "а свой домашний — уже нет: у запроса РОВНО одна организация")
r = c.delete("/api/projects/1", headers=H(bob_t))
check(r.status_code == 403, "переводчик команды не удаляет проекты (роль из сессии)")
r = c.get("/api/auth/me", headers=H(bob_t))
check(r.json()["tenant"]["id"] == team and r.json()["can"]["owner"] is False,
      "/auth/me показывает АКТИВНУЮ команду, а не домашнюю запись")
r = c.post("/api/profile/team", headers=H(bob_t), json={"tenant": "zedco"})
check(r.status_code == 404, "в команду, где не состоишь, не переключиться")

print("=== 7. Состав команды и исключение ===")
r = c.get("/api/teams/" + team, headers=H(bob_t))
check(r.status_code == 200 and len(r.json()["members"]) == 2 and "invites" not in r.json(),
      "участник видит состав, но не список приглашённых почт")
check("invites" in c.get("/api/teams/" + team, headers=H(anna_t)).json(),
      "владелец видит и приглашения")
r = c.post("/api/teams/acme/members/%d" % bob["id"], headers=H(anna_t), json={"remove": True})
check(r.status_code == 404, "исключить можно только из той команды, где человек есть")
r = c.post("/api/teams/" + team + "/members/%d" % bob["id"], headers=H(anna_t), json={"remove": True})
check(r.status_code == 200 and main._member_role(bob, team) is None, "исключён")
check(c.get("/api/profile", headers=H(bob_t)).status_code == 401,
      "сессия исключённого закрыта СРАЗУ — иначе он работал бы в чужих проектах до конца токена")
bob_t = login("bob")
check(c.get("/api/projects/2", headers=H(bob_t)).status_code == 200,
      "после нового входа он снова в своей домашней организации")

print("=== 8. Домашнюю организацию не покидают и не правят отсюда ===")
r = c.post("/api/teams/bobco/leave", headers=H(bob_t))
check(r.status_code == 400, "домашнюю организацию покинуть нельзя — остался бы без места работы")
r = c.post("/api/teams/" + team + "/leave", headers=H(anna_t))
check(r.status_code == 400, "единственный владелец не уходит, бросив команду")

print("=== 9. Удалённая команда не оставляет висячих членств ===")
# Нашлось смоук-тестом на живом сервере: команду сносили, а членство
# оставалось на пользователе. В списке его команд появлялась строка без
# организации, а переключение на неё сажало человека в рабочее
# пространство, которого больше нет.
r = c.post("/api/teams", headers=H(anna_t), json={"name": "Временная"})
tmp = r.json()["team"]["id"]
r = c.post("/api/teams/" + tmp + "/invite", headers=H(anna_t), json={"email": "zed@example.com"})
tmp_inv = r.json()["invite"]["id"]
zed_t = login("zed")
c.post("/api/profile/invites/" + tmp_inv, headers=H(zed_t), json={"action": "accept"})
check(main._member_role(zed, tmp) == "translator", "Зед в этой команде")
c.post("/api/profile/team", headers=H(zed_t), json={"tenant": tmp})   # и работает В НЕЙ
main.STATE["users"][0]["super"] = True                      # Анна — суперпользователь
anna_t = login("anna")
r = c.delete("/api/admin/tenants/" + tmp, headers=H(anna_t))
check(r.status_code == 200, "команда удалена суперпользователем")
check(main._member_role(zed, tmp) is None, "членство удалённой команды снято с человека")
check([t["id"] for t in main._teams_of(zed)] == ["zedco"], "в его списке команд остался только дом")
check(not [i for i in main._invites() if i.get("tenant") == tmp],
      "и приглашения удалённой команды закрыты — иначе они ждали бы решения вечно")
check(c.get("/api/profile", headers=H(zed_t)).status_code == 401,
      "сессия человека, работавшего В удалённой команде, закрыта — иначе он "
      "остался бы в рабочем пространстве, которого больше нет")
zed_t = login("zed")
check(c.get("/api/profile", headers=H(zed_t)).json()["activeTeam"] == "zedco",
      "новый вход возвращает его домой")

print("=== 10. Приглашения не уезжают в общую выдачу ===")
r = c.get("/api/seed", headers=H(anna_t))
check("invites" not in r.json(), "/api/seed не отдаёт invites (там чужие почты)")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
