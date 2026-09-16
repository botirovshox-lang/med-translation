"""Дыры, найденные разбором «злоумышленник получил ссылку», и их заплатки.
Каждый раздел — одна дыра: что было видно снаружи и что теперь закрыто.
  1. карта API (/docs, /openapi.json, /redoc) не отдаётся;
  2. заголовки безопасности стоят на каждом ответе, CSP — на HTML, HSTS —
     только по HTTPS, ответы /api/* не кэшируются;
  3. каталог скриншотов макета наружу не отдаётся;
  4. регистрация: пробы «занята ли почта» считаются своим потолком и не
     запирают регистрацию новым адресам; verify/reset отвечают одним текстом
     на все отказы; forgot/resend не говорят, ушло ли письмо;
  5. zip-бомба отбивается ДО разбора .docx (объявленный объём, число частей,
     одна XML-часть, размер файла);
  6. экспорт лежит под организацией и номером проекта, удаление проекта
     уносит и его экспорты;
  7. откат пересчёта back-check не выходит за организацию;
  8. /api/seed — белый список ключей, память переводов и области — свои;
  9. приглашения в команду — с потолком на человека;
 10. /api/health без входа — без числа проектов;
 11. отключение пользователя и организации закрывает живые сессии; логин
     в отключённую домашнюю организацию сажает в живую команду.
Ни одного вызова модели, файл состояния не пишется.
"""
import io, json, os, re, sys, tempfile, zipfile
from pathlib import Path
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ.pop("SIGNUP_ENABLED", None)
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient
from fastapi import HTTPException

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["tm"], main.STATE["domains"] = [], []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear(); main._SIGNUP_FAILS.clear()
main._SIGNUP_PROBES.clear(); main._INVITE_HITS.clear(); main._CODE_REQS.clear()
TMP = Path(tempfile.mkdtemp(prefix="medcat-hardening-"))
main.EXPORT_DIR = TMP / "exports"
main.BACKCHECK_RESCORE_DIR = TMP / "backups"
main.BACKCHECK_RESCORE_DIR.mkdir(parents=True)

fail = []
def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)

c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
B = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]

print("=== 1. Карта API не отдаётся ===")
for p in ("/docs", "/openapi.json", "/redoc"):
    check(c.get(p).status_code == 404, "%s → 404" % p)

print("=== 2. Заголовки безопасности ===")
r = c.get("/")
h = r.headers
check(r.status_code == 200, "главная отдаётся")
check(h.get("x-content-type-options") == "nosniff", "nosniff")
check(h.get("x-frame-options") == "DENY", "X-Frame-Options DENY")
check("strict-origin" in (h.get("referrer-policy") or ""), "Referrer-Policy")
csp = h.get("content-security-policy") or ""
check("frame-ancestors 'none'" in csp and "connect-src 'self'" in csp and "object-src 'none'" in csp,
      "CSP на HTML: frame-ancestors/connect-src/object-src")
# Список хостов не перечисляется руками, а ВЫВОДИТСЯ из самой страницы:
# перечень в тесте разошёлся бы с правдой первой же правкой фронтенда — и либо
# запретил бы нужное (белый экран), либо молча оставил открытым ненужное.
_html = open("frontend/index.html", encoding="utf-8").read()
_page_hosts = set(re.findall(r'(?:src|href)="https?://([^/"]+)', _html))
_csp_hosts = set(re.findall(r"https?://([^\s;'\"]+)", csp))
check(_page_hosts <= _csp_hosts,
      "CSP разрешает все чужие хосты, что грузит index.html"
      + (": не хватает " + ", ".join(sorted(_page_hosts - _csp_hosts)) if _page_hosts - _csp_hosts else ""))
check(_csp_hosts <= _page_hosts,
      "CSP не разрешает лишних хостов"
      + (": лишние " + ", ".join(sorted(_csp_hosts - _page_hosts)) if _csp_hosts - _page_hosts else ""))
# React и шрифт переехали в frontend/vendor, Babel убран совсем: на критическом
# пути не осталось ни одного чужого DNS и TLS — ни ради скорости, ни ради того,
# что чужая авария больше не закрывает наш вход.
check(not _page_hosts, "чужих хостов на критическом пути нет вовсе")

print("=== 2б. Кэш статики ===")
# Вечный кэш законен только потому, что в адресе стоит ОТПЕЧАТОК файлов:
# правка меняет адрес. Адрес без отпечатка ничего не обещает — и не кэшируется.
_cc = c.get("/js/i18n.js?v=deadbeef").headers.get("cache-control") or ""
check("immutable" in _cc and "max-age=31536000" in _cc, "/js/*?v= — вечный кэш")
check("immutable" not in (c.get("/js/i18n.js").headers.get("cache-control") or ""),
      "тот же файл без ?v= навечно НЕ кэшируется")
check("no-cache" in (c.get("/").headers.get("cache-control") or ""),
      "сама страница сверяется всегда: в ней живёт отпечаток остальных")
check("__V__" not in r.text and re.search(r'styles\.css\?v=[0-9a-f]{6,}', r.text),
      "отпечаток подставлен в страницу")
check("strict-transport-security" not in h, "HSTS по http не ставится")
hs = c.get("/", headers={"X-Forwarded-Proto": "https"}).headers
check("max-age=" in (hs.get("strict-transport-security") or ""), "HSTS по https (X-Forwarded-Proto) стоит")
check("includeSubDomains" not in (hs.get("strict-transport-security") or ""),
      "HSTS без includeSubDomains: на хосте живут чужие поддомены")
rj = c.get("/api/health")
check("content-security-policy" not in rj.headers, "CSP на JSON не ставится")
check(rj.headers.get("cache-control") == "no-store", "ответы /api/* — no-store")
check(rj.headers.get("x-content-type-options") == "nosniff", "nosniff и на /api/*")
r401 = c.get("/api/projects")
check(r401.status_code == 401 and r401.headers.get("x-content-type-options") == "nosniff",
      "заголовки стоят и на 401 из require_token")
check("frame-ancestors 'none'" in (c.get("/terms").headers.get("content-security-policy") or ""),
      "CSP и на публичных страницах документов")

print("=== 3. Скриншоты макета наружу не уходят ===")
check(c.get("/screens/00-auth.png").status_code == 404, "/screens/* → 404")
check(c.get("/js/api.js").status_code == 200, "/js/* по-прежнему отдаётся")

print("=== 4. Регистрация и коды: без оракула существования ===")
reg = lambda e: c.post("/api/auth/register", json={"email": e, "password": "long-enough-1", "accept": True})
check(reg("probe@acme.io").status_code == 200, "первая регистрация — 200")
codes = [reg("probe@acme.io").status_code for _ in range(main.SIGNUP_PROBE_MAX_PER_HOUR + 3)]
check(codes[:main.SIGNUP_PROBE_MAX_PER_HOUR] == [409] * main.SIGNUP_PROBE_MAX_PER_HOUR
      and codes[main.SIGNUP_PROBE_MAX_PER_HOUR:] == [429] * 3,
      "пробы занятой почты: %d × 409, дальше 429" % main.SIGNUP_PROBE_MAX_PER_HOUR)
check(reg("fresh@acme.io").status_code == 200,
      "пробы НЕ запирают регистрацию новому адресу с того же IP")
check(len(main._SIGNUP_FAILS.get("testclient", [])) == 2, "в потолке регистраций — только регистрации (2)")
bad = main.AUTH_CODE_BAD
r = c.post("/api/auth/verify", json={"email": "nobody@acme.io", "code": "000000"})
check(r.status_code == 400 and r.json()["detail"] == bad, "verify по несуществующей почте — общий отказ")
r = c.post("/api/auth/verify", json={"email": "probe@acme.io", "code": "000000"})
check(r.status_code == 400 and r.json()["detail"] == bad, "verify с неверным кодом — тот же текст")
u = main._user_by_email("fresh@acme.io"); u["emailVerified"] = True; u.pop("authCode", None)
r = c.post("/api/auth/verify", json={"email": "fresh@acme.io", "code": "000000"})
check(r.status_code == 400 and r.json()["detail"] == bad and "already" not in r.json(),
      "verify по уже подтверждённой почте — тот же отказ, без already")
r = c.post("/api/auth/reset", json={"email": "nobody@acme.io", "code": "000000", "password": "long-enough-2"})
check(r.status_code == 400 and r.json()["detail"] == bad, "reset по несуществующей почте — тот же текст")
r = c.post("/api/auth/reset", json={"email": "fresh@acme.io", "code": "000000", "password": "long-enough-2"})
check(r.status_code == 400 and r.json()["detail"] == bad, "reset без выданного кода — тот же текст")
r1 = c.post("/api/auth/reset", json={"email": "fresh@acme.io", "code": "000000", "password": "x"})
r2 = c.post("/api/auth/reset", json={"email": "nobody@acme.io", "code": "000000", "password": "x"})
check(r1.json()["detail"] == r2.json()["detail"], "короткий пароль: отказ один и для существующей, и для чужой почты")
fails_before = main._LOGIN_FAILS.get("testclient", (0, 0))[0]
c.post("/api/auth/verify", json={"email": "fresh@acme.io", "code": "000000"})
check(main._LOGIN_FAILS.get("testclient", (0, 0))[0] == fails_before + 1,
      "отказ по СУЩЕСТВУЮЩЕЙ почте считается в тот же IP-потолок, что и по чужой")
main._LOGIN_FAILS.clear()
u["active"] = False; u.pop("authCode", None)
c.post("/api/auth/resend", json={"email": "fresh@acme.io"})
check("authCode" not in u, "отключённой учётке код не выдаётся")
u["active"] = True
before = len(main._CODE_REQS.get("testclient", []))
signups_before = len(main._SIGNUP_FAILS.get("testclient", []))
r1 = c.post("/api/auth/forgot", json={"email": "nobody@acme.io"})
r2 = c.post("/api/auth/forgot", json={"email": "fresh@acme.io"})
r3 = c.post("/api/auth/resend", json={"email": "nobody@acme.io"})
check(all(x.status_code == 200 and x.json() == {"ok": True} for x in (r1, r2, r3)),
      "forgot/resend отвечают одинаково и без mailSent")
check(len(main._CODE_REQS.get("testclient", [])) == before + 3
      and len(main._SIGNUP_FAILS.get("testclient", [])) == signups_before,
      "forgot/resend считаются на КАЖДЫЙ запрос — в своём бакете, не в бакете регистраций")
check(len(main._DUMMY_SALT) == 32, "холостая соль для pbkdf2 по несуществующему логину есть")
hh, ss = main._hash_password("pw-123456")
check(main._verify_password({"hash": hh, "salt": ss, "active": False}, "pw-123456") is False
      and main._verify_password({"hash": hh, "salt": ss}, "pw-123456") is True,
      "_verify_password: отключённая учётка по-прежнему не входит")
r = c.post("/api/auth/login", json={"login": "no-such-login", "password": "whatever-1"})
r2 = c.post("/api/auth/login", json={"login": "beta", "password": "wrong-pass-1"})
check(r.status_code == 401 and r2.status_code == 401 and r.json()["detail"] == r2.json()["detail"],
      "логин: «нет такого» и «не тот пароль» — один ответ")
main._LOGIN_FAILS.clear()

print("=== 5. Zip-бомба отбивается до разбора ===")
def zipbytes(parts, fake_size=None, fake_for=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            z.writestr(name, data)
        if fake_size is not None:
            for zi in z.filelist:
                if zi.filename == fake_for:
                    zi.file_size = fake_size
    return buf.getvalue()
def guard(data):
    try:
        main._zip_guard(data)
        return None
    except HTTPException as e:
        return e.status_code
check(guard(zipbytes([("word/document.xml", b"<w:document/>")])) is None, "обычный маленький пакет проходит")
check(guard(b"not a zip at all") is None, "не zip — не наша ошибка, разберёт читающий")
bomb = zipbytes([("word/media/a.bin", b"x")], fake_size=main.textcount.MAX_UNPACKED + 1, fake_for="word/media/a.bin")
check(guard(bomb) == 413, "объявленный распакованный объём выше потолка → 413")
xml = zipbytes([("word/document.xml", b"<w/>")], fake_size=main.textcount.MAX_XML_PART + 1, fake_for="word/document.xml")
check(guard(xml) == 413, "одна XML-часть выше потолка → 413")
many = zipbytes([("p/%d" % i, b"") for i in range(main.textcount.MAX_MEMBERS + 1)])
check(guard(many) == 413, "частей больше потолка → 413")
check(guard(b"x" * (main.textcount.MAX_BYTES + 1)) == 413, "файл больше MAX_BYTES → 413")
try:
    main._docx_paragraph_texts(bomb); bomb_hit = None
except HTTPException as e:
    bomb_hit = e.status_code
check(bomb_hit == 413, "_docx_paragraph_texts зовёт защиту ДО открытия документа")

print("=== 6. Экспорт: путь под организацией и проектом ===")
pa = c.post("/api/projects", headers=H(A), json={"title": "Договор", "src": "RU", "tgt": "EN"}).json()["id"]
pb = c.post("/api/projects", headers=H(B), json={"title": "Договор", "src": "RU", "tgt": "EN"}).json()["id"]
ra = next(p for p in main.STATE["projects"] if p["id"] == pa)
rb = next(p for p in main.STATE["projects"] if p["id"] == pb)
xa, xb = main._export_path(ra, "docx"), main._export_path(rb, "docx")
check(xa != xb and xa.name == xb.name == "Договор.docx", "одно название у двух организаций — разные файлы, имя прежнее")
check("beta" in xb.parts and str(pb) in xb.parts and "default" in xa.parts, "в пути — организация и номер проекта")
check(main._export_path(rb, "pdf").parent == xb.parent, "готовый PDF ищется в той же папке проекта")
xb.write_bytes(b"pdf")
main._delete_project_record(pb)
check(not xb.parent.exists(), "удаление проекта уносит его экспорты")
pb = c.post("/api/projects", headers=H(B), json={"title": "Договор", "src": "RU", "tgt": "EN"}).json()["id"]
rb = next(p for p in main.STATE["projects"] if p["id"] == pb)

print("=== 7. Откат пересчёта back-check — только свои проекты ===")
def seg(score):
    return {"id": 1, "source": "Исходник", "target": "Target", "status": "translated",
            "backcheck": {"score": score, "at": "2026-09-14 10:00", "back": "Исходник",
                          "target_hash": "h1", "model": "m"}}
ra["segments"], rb["segments"] = [seg(10)], [seg(10)]
saved = {str(pa): {"1": dict(seg(90)["backcheck"])}, str(pb): {"1": dict(seg(90)["backcheck"])}}
(main.BACKCHECK_RESCORE_DIR / "backcheck-20990101-000000.json").write_text(
    json.dumps({"projects": saved}), encoding="utf-8")
r = c.post("/api/backcheck/rescore/20990101-000000/undo", headers=H(B))
check(r.status_code == 200 and r.json()["restored"] == 1, "B откатывает ровно один (свой) сегмент")
check(rb["segments"][0]["backcheck"]["score"] == 90 and ra["segments"][0]["backcheck"]["score"] == 10,
      "оценка A не тронута, оценка B возвращена")
(main.BACKCHECK_RESCORE_DIR / "backcheck-20990101-000001.json").write_text(
    json.dumps({"projects": {str(pa): {"1": dict(seg(90)["backcheck"])}}}), encoding="utf-8")
check(c.post("/api/backcheck/rescore/20990101-000001/undo", headers=H(B)).status_code == 404,
      "копия без единого своего проекта для B не существует (404)")
check(c.post("/api/backcheck/rescore/../../x/undo", headers=H(B)).status_code in (400, 404),
      "метка с обходом пути не принимается")

print("=== 8. /api/seed — белый список, своё ===")
main.STATE["tm"] = [{"src": "a", "tgt": "b", "tenant": "default"}, {"src": "c", "tgt": "d", "tenant": "beta"},
                    {"src": "e", "tgt": "f"}]
main.STATE["domains"] = [{"id": "law-a", "tenant": "default", "label": "A"}, {"id": "law-b", "tenant": "beta", "label": "B"}]
sb = c.get("/api/seed", headers=H(B)).json()
check([t["src"] for t in sb["tm"]] == ["c"], "память переводов — только своя (запись без tenant — default)")
check([d["id"] for d in sb["domains"]] == ["law-b"], "области — только свои")
allowed = {"projects", "glossary", "tm", "termQueue", "autoBatches", "exportHistory", "runCosts",
           "quotes", "domains", "folders", "dicts"}
check(set(sb) <= allowed, "наружу уходят только названные ключи: лишние — %s" % sorted(set(sb) - allowed))
check({"projects", "glossary", "tm", "folders", "dicts", "exportHistory"} <= set(sb),
      "…а то, что читает app.jsx, на месте")
for k in ("users", "tenants", "audit", "spend", "invites", "surveys", "testBatches"):
    check(k not in sb, "ключа %s в seed нет" % k)

print("=== 9. Приглашения — с потолком на человека ===")
inv = lambda: c.post("/api/teams/beta/invite", headers=H(B), json={"email": "ghost@acme.io", "role": "translator"})
codes = [inv().status_code for _ in range(main.INVITE_MAX_PER_HOUR + 2)]
check(codes[:main.INVITE_MAX_PER_HOUR] == [404] * main.INVITE_MAX_PER_HOUR and codes[-2:] == [429, 429],
      "%d проб → 404, дальше 429" % main.INVITE_MAX_PER_HOUR)

print("=== 10. /api/health без входа — без числа проектов ===")
check("projects" not in c.get("/api/health").json(), "без токена числа проектов нет")
hb = c.get("/api/health", headers=H(B)).json()
check(hb.get("projects") == 1, "с токеном — число СВОИХ проектов (1)")

print("=== 11. Отключение закрывает живые сессии ===")
r = c.post("/api/admin/users", headers=H(B), json={"login": "eva", "password": "eva-pass-123", "role": "translator"})
uid = r.json()["user"]["id"] if r.status_code == 200 and "user" in r.json() else \
      next(u["id"] for u in main._users() if u["login"] == "eva")
E = c.post("/api/auth/login", json={"login": "eva", "password": "eva-pass-123"}).json()["token"]
check(c.get("/api/projects", headers=H(E)).status_code == 200, "Ева вошла")
c.post("/api/admin/users/%d" % uid, headers=H(B), json={"active": False})
check(c.get("/api/projects", headers=H(E)).status_code == 401, "отключённая учётка теряет сессию сразу")
c.post("/api/admin/users/%d" % uid, headers=H(B), json={"active": True})
r = c.post("/api/admin/tenants/beta", headers=H(A), json={"active": False})
check(r.status_code == 200, "суперпользователь отключил beta")
rb_ = c.get("/api/projects", headers=H(B))
check(rb_.status_code in (401, 403), "владелец отключённой организации теряет доступ сразу (%s)" % rb_.status_code)
r = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"})
check(r.status_code == 403, "вход в отключённую домашнюю организацию без других команд — 403")
ub = main._user_by_login("beta")
ub["memberships"] = [{"tenant": "default", "role": "translator", "since": "2026-09-14"}]
r = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"})
check(r.status_code == 200, "с живой второй командой вход есть")
if r.status_code == 200:
    B2 = r.json()["token"]
    check(main._SESSIONS[B2]["tenant"] == "default" and main._SESSIONS[B2]["role"] == "translator",
          "…и сессия посажена в живую команду с её ролью")
    check(c.get("/api/projects", headers=H(B2)).status_code == 200, "в живой команде работа идёт")
ub.pop("memberships", None)
c.post("/api/admin/tenants/beta", headers=H(A), json={"active": True})
check(c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).status_code == 200,
      "после включения организации вход снова есть")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
