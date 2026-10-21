# -*- coding: utf-8 -*-
"""Гостевой режим: первая страница без регистрации, регистрация — на выгрузке.

Сторожится то, где гость мог бы получить больше обещанного или навредить:

  1. Гость заводится только с СОГЛАСИЕМ (проверяет сервер), капчей (когда
     задан ключ) и в пределах потолков на сеть и на сервис за сутки.
  2. Гостю открыт БЕЛЫЙ список дверей: выгрузка, словари, прогоны кроме
     перевода — 403 с кодом `guest`.
  3. Бесплатная страница — НАЧАЛО файла: тот же файл у нового гостя даёт
     ту же страницу; вторая страница тем же гостем — 402.
  4. Почта → код превращают гостя в клиента НА МЕСТЕ: та же организация
     и файл, +1 страница подарка, сессия перестаёт быть гостевой; занятая
     почта — 409, и до кода почта на запись не пишется.
  5. Пароль после такой регистрации задаётся без «нынешнего» — один раз.
  6. Возобновление по ключу; просроченный гость снимается вместе с файлом,
     ставший клиентом — нет; номер пользователя не переиспользуется.
  7. PDF гостя режется до первой страницы с текстом.
Ни одного вызова модели, писем не уходит, файл состояния не пишется.
"""
import io
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["SIGNUP_ENABLED"] = "1"
os.environ.pop("TURNSTILE_SECRET", None)
os.environ.pop("TURNSTILE_SITE_KEY", None)
for k in ("SMTP_HOST", "MAIL_FROM", "SMTP_USER"):
    os.environ.pop(k, None)
sys.path.insert(0, "backend")
import main                                               # noqa: E402
from starlette.testclient import TestClient               # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="mct-guest-"))
main.SOURCE_DIR = TMP / "sources"
main.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
main.REIMPORT_DIR = TMP / "backups"
main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main.STATE["spend"], main.STATE["projects"] = {}, []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear(); main._SIGNUP_FAILS.clear()
main.TENANT_MAX_PAGES = 0
main.SIGNUP_TRIAL_USD = 0.3
main.GUEST_PER_NET_DAY = 3
main._auto_read_images = lambda *a, **k: None            # ни одного вызова модели
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


try:
    from docx import Document
except ImportError:
    print("python-docx не установлен — проверка пропущена")
    sys.exit(0)

c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}            # noqa: E731
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]


def docx_of(n, words=30, tag="абзац"):
    d = Document()
    for i in range(n):
        d.add_paragraph(("%s %d " % (tag, i)) + " ".join("слово%d" % (j % 7) for j in range(words - 2)) + ".")
    b = io.BytesIO(); d.save(b)
    return b.getvalue()


def start(**kw):
    body = {"accept": True}
    body.update(kw)
    return c.post("/api/guest/start", json=body)


def up(tok, raw, name="book.docx"):
    return c.post("/api/projects/upload", headers=H(tok), files={"file": (name, raw, MIME)},
                  data={"src": "RU", "tgt": "EN"})


def reset_limits():
    main._GUEST_SWEPT[0] = time.time()
    for t in main._tenants():
        g = t.get("guestFrom")
        if isinstance(g, dict):
            g["at"] = g["at"] - 86400 * 2 if t.get("guest") is None else g["at"]


print("=== 1. Экран гостя и согласие ===")
r = c.get("/api/guest/info")
j = r.json()
check(r.status_code == 200 and j["enabled"] and j["turnstile"] == "" and j["freePages"] == 1,
      "info публичен: режим включён, капчи нет (ключа нет), дарим 1 страницу")
check(any(l["code"] == "RU" for l in j["languages"]), "info отдаёт список языков")
r = c.post("/api/guest/start", json={"accept": False})
check(r.status_code == 400, "без согласия гостя нет (400)")
r = start(uiLang="ru", ref="ABCD2345", refAt=time.time() * 1000)
j = r.json()
check(r.status_code == 200 and j["token"] and j["key"] and j["me"]["guest"], "гость заведён: токен, ключ, me.guest")
g1, key1 = j["token"], j["key"]
gu = main._users()[-1]
gt = main._tenant_rec(gu["tenant"])
check(gt["guest"] and gt["trial"] and gt["pagesCredit"] == 1 and gt["limitUsd"] == main.GUEST_LIMIT_USD,
      "организация гостя: пробная, 1 страница, свой лимит расхода")
check(gu["acceptedTerms"]["version"] and gu["acceptedTerms"]["via"] == "guest" and gu["acceptedTerms"]["net"],
      "согласие записано: редакция, сеть, путь «гость»")
check(not gu.get("hash") and not gu.get("email"), "у гостя нет ни пароля, ни почты")
check(gt["guestFrom"]["ref"] == "ABCD2345", "метка приглашения сохранена до регистрации")

print("=== 2. Белый список дверей ===")
r = c.get("/api/seed", headers=H(g1))
check(r.status_code == 403 and r.json().get("code") == "guest", "/api/seed гостю — 403 guest")
check(c.get("/api/glossary", headers=H(g1)).status_code == 403, "словари гостю закрыты")
check(c.get("/api/auth/me", headers=H(g1)).status_code == 200, "/auth/me гостю открыт")
check(main.guest_mod.allowed("POST", "/api/projects/7/jobs")
      and not main.guest_mod.allowed("POST", "/api/projects/7/export")
      and not main.guest_mod.allowed("GET", "/api/projects/7/export/download")
      and not main.guest_mod.allowed("POST", "/api/projects/7/trial/rest"),
      "выгрузка и «остальное» — не в белом списке")

print("=== 3. Бесплатная страница — место по отпечатку файла ===")
book = docx_of(40)
r = up(g1, book)
p = r.json()
ex = p.get("trialExcerpt") or {}
check(r.status_code == 200 and ex.get("from") is not None and ex.get("pages", 9) <= 1.0,
      "фрагмент гостя — подряд идущие строки не больше страницы (с %s)" % ex.get("from"))
check(main._trial_excerpt_plan(gu["tenant"], 1, [], "RU", {}, []) is None,
      "пустой файл фрагмента не получает")
pid1 = p["id"]
r = up(g1, docx_of(30, tag="другой"), "other.docx")
check(r.status_code == 402, "вторая бесплатная страница тем же гостем — 402")
r = c.post("/api/projects/%d/jobs" % pid1, headers=H(g1), json={"kind": "full", "segment_ids": [1]})
check(r.status_code == 403, "прогон, кроме перевода, гостю закрыт")
r = c.post("/api/projects/%d/jobs" % pid1, headers=H(g1), json={"kind": "images", "segment_ids": []})
check(r.status_code in (403, 409), "чтение картинок гость не ставит сам")
_q = main.GUEST_QUEUE_MAX
main.GUEST_QUEUE_MAX = 0
r = c.post("/api/projects/%d/jobs" % pid1, headers=H(g1), json={"kind": "translate", "segment_ids": [1]})
check(r.status_code == 429, "гостевых прогонов в очереди больше потолка — 429")
main.GUEST_QUEUE_MAX = _q
r = c.post("/api/projects/%d/export" % pid1, headers=H(g1), json={"format": "docx"})
check(r.status_code == 403 and r.json().get("code") == "guest", "скачать гость не может — 403 guest")

r = start()
g2 = r.json()["token"]
r = up(g2, book)
ex2 = r.json().get("trialExcerpt") or {}
check(r.status_code == 200 and ex2.get("from") == ex.get("from") and ex2.get("to") == ex.get("to"),
      "тот же файл у нового гостя — та же страница (сто прогонов ничего не дают)")

print("=== 4. Потолки на сеть и капча ===")
check(start().status_code == 200, "третий гость с одной сети за сутки — ещё можно")
r = start()
check(r.status_code == 429, "четвёртый гость с одной сети за сутки — 429")
for t in main._tenants():
    if t.get("guestFrom"):
        t["guestFrom"]["net"] = "other-net"
_m = main.GUEST_MAX_PER_DAY
main.GUEST_MAX_PER_DAY = 3
r = start()
check(r.status_code == 429, "потолок гостей на сервис за сутки — 429")
main.GUEST_MAX_PER_DAY = _m
main.TURNSTILE_SECRET = "secret"
main.TURNSTILE_SITE_KEY = "site"
_ts = main.guest_mod.turnstile_ok
main.guest_mod.turnstile_ok = lambda secret, token, ip="", timeout=8.0: token == "human"
r = start(captcha="robot")
check(r.status_code == 400, "капча не пройдена — 400")
r = start(captcha="human")
check(r.status_code == 200, "капча пройдена — гость заведён")
main.TURNSTILE_SECRET = ""
main.TURNSTILE_SITE_KEY = ""
main.guest_mod.turnstile_ok = _ts

print("=== 5. Возобновление по ключу ===")
r = c.post("/api/guest/resume", json={"key": key1})
check(r.status_code == 200 and r.json()["me"]["guest"], "ключ возвращает гостя")
r = c.post("/api/guest/resume", json={"key": "nope"})
check(r.status_code == 401, "чужой ключ — 401")

print("=== 6. Почта → код: гость становится клиентом ===")
mkh, mks = main._hash_password("password-123")
main._users().append({"id": main._next_user_id(), "tenant": "acme", "login": "taken@ex.io",
                      "email": "taken@ex.io", "emailVerified": True, "hash": mkh, "salt": mks,
                      "role": "owner", "active": True, "name": "x", "created": "2026-01-01"})
main._tenants().append({"id": "acme", "name": "Acme", "active": True})
r = c.post("/api/guest/claim", headers=H(g1), json={"email": "taken@ex.io"})
check(r.status_code == 409, "занятая почта — 409")
r = c.post("/api/guest/verify", headers=H(g1), json={"code": "000000"})
check(r.status_code == 400, "код без почты — 400")
r = c.post("/api/guest/claim", headers=H(g1), json={"email": "new@ex.io"})
check(r.status_code == 200 and r.json()["email"] == "new@ex.io", "почта принята, код отправлен")
check(not gu.get("email") and gu["claim"]["email"] == "new@ex.io",
      "до кода почта на запись НЕ пишется (чужой адрес не занять)")
r = c.post("/api/guest/verify", headers=H(g1), json={"code": "000000"})
check(r.status_code == 400, "неверный код — 400")
code = main._issue_code(gu, "verify")
r = c.post("/api/guest/verify", headers=H(g1), json={"code": code})
j = r.json()
check(r.status_code == 200 and not j["me"]["guest"] and j["me"]["noPassword"] and j["me"]["email"] == "new@ex.io",
      "код принят: клиент без пароля, почта подтверждена")
check(not gt.get("guest") and gt["signup"] and gt["from"] == "guest" and gt["trial"],
      "та же организация стала обычной пробной (from: guest)")
check(gt["pagesCredit"] == 2, "подарок за регистрацию +1 страница (%s)" % gt.get("pagesCredit"))
check(gt.get("refBy") == "ABCD2345" and gt.get("refPaid") == 2,
      "метка приглашения переехала, процент — только с будущих оплат")
check(c.get("/api/seed", headers=H(g1)).status_code == 200, "та же сессия больше не гостевая")
check(any(p_["id"] == pid1 and p_["tenant"] == gt["id"] for p_ in main.STATE["projects"]), "файл на месте")
r = c.post("/api/projects/%d/export" % pid1, headers=H(g1), json={"format": "docx"})
check(r.status_code == 200 and r.json().get("ok"), "выгрузка открыта")
r = c.get("/api/projects/%d/rest-quote" % pid1, headers=H(g1))
j = r.json()
check(r.status_code == 200 and j["filePages"] > 1 and j["need"] >= 1,
      "сколько докупить на весь файл — считает сервер (%s)" % j)

print("=== 7. Пароль после регистрации гостем ===")
r = c.post("/api/profile", headers=H(g1), json={"password": "brand-new-pass"})
check(r.status_code == 200 and not r.json()["me"]["noPassword"], "пароль задан без «нынешнего»")
r = c.post("/api/profile", headers=H(g1), json={"password": "second-pass-1"})
check(r.status_code == 403, "второй раз — уже с нынешним паролем")
r = c.post("/api/auth/login", json={"login": "new@ex.io", "password": "brand-new-pass"})
check(r.status_code == 200, "вход по почте и паролю")

print("=== 8. Сроки и номера ===")
gid2 = next(t for t in main._tenants() if t.get("guest") and any(
    p_["tenant"] == t["id"] for p_ in main.STATE["projects"]))
uid2 = next(u["id"] for u in main._users() if u.get("tenant") == gid2["id"])
for t in main._tenants():
    if t.get("guestFrom"):
        t["guestFrom"]["at"] -= main.GUEST_TTL_H * 3600 + 10
n = main._guest_sweep(force=True)
check(n >= 1 and not main._tenant_rec(gid2["id"]), "просроченный гость снят")
check(not any(p_["tenant"] == gid2["id"] for p_ in main.STATE["projects"]), "вместе с файлом")
check(main._tenant_rec(gt["id"]) is not None, "ставший клиентом — не снят")
r = c.post("/api/guest/resume", json={"key": key1})
check(r.status_code == 401, "ставший клиентом по ключу гостя не входит")
nu = main._next_user_id()
check(nu > uid2, "номер снятого гостя не переиспользуется")

print("=== 9. Админка не засоряется гостями ===")
mkh, mks = main._hash_password("password-123")
main._users().append({"id": main._next_user_id(), "tenant": "sys", "login": "root",
                      "email": "root@ex.io", "emailVerified": True, "hash": mkh, "salt": mks,
                      "role": "owner", "super": True, "active": True, "name": "root",
                      "created": "2026-01-01"})
main._tenants().append({"id": "sys", "name": "Sys", "active": True})
main._GUEST_SWEPT[0] = 0
for t in main._tenants():
    if t.get("guestFrom"):
        t["guestFrom"]["net"] = "x"
rt = c.post("/api/auth/login", json={"login": "root", "password": "password-123"}).json()["token"]
start()
r = c.get("/api/admin/access", headers=H(rt))
j = r.json()
check(r.status_code == 200 and not any(u.get("guest") for u in j["users"])
      and not ({t["id"] for t in main._tenants() if t.get("guest")} & {t["id"] for t in j["tenants"]}),
      "«Роли и доступы» без гостей")

print("=== 10. Партнёр ведёт в гостевой режим ===")
url = main.partners_mod.target_url({"target": "guest", "lang": "uz"}, "https://app.example", "", "CODE", {})
check(url.startswith("https://app.example/app?") and "try=1" in url and "ref=CODE" in url and "lang=uz" in url,
      "ссылка партнёра «гость» — на экран бесплатного перевода (%s)" % url)

print("=== 11. PDF гостя — страница с текстом и вёрсткой, место по зерну ===")
try:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    cv = canvas.Canvas(buf)

    def page(tag, paras, start_y=760):
        """Абзацы как в книге: две длинные строки и короткая с точкой."""
        y = start_y
        for k in range(paras):
            for line in ("%s %d first line of the paragraph with many plain words" % (tag, k),
                         "and the second line continues the same thought here",
                         "and it ends."):
                cv.drawString(72, y, line)
                y -= 16
            y -= 10

    def column(x, tag, n, y=760):
        for k in range(n):
            cv.drawString(x, y, "%s %d short line of a column with words." % (tag, k))
            y -= 14

    from reportlab.lib.utils import ImageReader
    from PIL import Image as _PIL
    _ib = io.BytesIO()
    _PIL.effect_noise((120, 90), 60).convert("RGB").save(_ib, "PNG")
    cv.drawString(72, 700, "Title page")
    cv.showPage()
    page("Plain", 12)                          # 250 слов сплошного текста
    cv.showPage()
    column(72, "Left", 22)                     # колонки, картинка, заголовок
    column(330, "Right", 22)
    cv.setFont("Helvetica-Bold", 18)
    cv.drawString(72, 790, "Heading of the page")
    cv.setFont("Helvetica", 9)
    cv.drawString(72, 420, "Figure caption.")
    cv.drawImage(ImageReader(io.BytesIO(_ib.getvalue())), 72, 440, 120, 90)
    cv.showPage()
    page("Last", 2)
    cv.showPage()
    cv.save()
    one, total, pick = main.guest_mod.pdf_pick_page(buf.getvalue(), "seed-a")
    from pypdf import PdfReader
    check(total == 4 and pick == 2 and len(PdfReader(io.BytesIO(one)).pages) == 1,
          "из четырёх взята третья — от 200 слов и с вёрсткой, а не обложка и не сплошной текст (pick=%s)" % pick)
    picks = {main.guest_mod.pdf_pick_page(buf.getvalue(), "seed-a")[2] for _ in range(3)}
    check(picks == {pick}, "тот же файл — та же страница")
    # Две равные страницы: какую — решает зерно, и для одного зерна всегда одну.
    b2 = io.BytesIO()
    cv = canvas.Canvas(b2)
    for tg in ("A", "B", "C", "D"):
        page(tg, 12)
        cv.showPage()
    cv.save()
    seen = {main.guest_mod.pdf_pick_page(b2.getvalue(), "s%d" % i)[2] for i in range(12)}
    check(len(seen) > 1 and main.guest_mod.pdf_pick_page(b2.getvalue(), "s1")[2]
          == main.guest_mod.pdf_pick_page(b2.getvalue(), "s1")[2],
          "равные страницы — разные для разных файлов, одна для одного (%s)" % sorted(seen))
    print("=== 12. Весь документ после регистрации: страница гостя не теряет перевод ===")
    main._GUEST_SWEPT[0] = time.time()
    for t in main._tenants():
        if t.get("guestFrom"):
            t["guestFrom"]["net"] = "y"
    r = start()
    g9 = r.json()["token"]
    g9u = main._users()[-1]
    r = c.post("/api/projects/upload", headers=H(g9), files={"file": ("doc.pdf", buf.getvalue(), "application/pdf")},
               data={"src": "EN", "tgt": "RU"})
    pj = r.json()
    check(r.status_code == 200 and pj.get("guestCut", {}).get("pdfPages") == 4 and pj["guestCut"]["page"] == 3,
          "PDF гостя разобран одной страницей (3 из 4) — %s" % pj.get("guestCut"))
    pidg = pj["id"]
    proj = next(p_ for p_ in main.STATE["projects"] if p_["id"] == pidg)
    for s_ in proj["segments"]:
        s_["target"], s_["status"] = "ПЕРЕВОД " + s_["source"], "translated"
    kept_src = {s_["source"] for s_ in proj["segments"]}
    c.post("/api/guest/claim", headers=H(g9), json={"email": "pdf@ex.io"})
    code = main._issue_code(g9u, "verify")
    check(c.post("/api/guest/verify", headers=H(g9), json={"code": code}).status_code == 200, "гость стал клиентом")
    r = c.get("/api/projects/%d/rest-quote" % pidg, headers=H(g9))
    check(r.status_code == 200 and r.json()["filePages"] > 0, "сколько в целом PDF — посчитано (%s)" % r.json())
    main._pages_topup(g9u["tenant"], 50, "test", paid=True)
    r = c.post("/api/projects/%d/trial/rest" % pidg, headers=H(g9))
    proj = next(p_ for p_ in main.STATE["projects"] if p_["id"] == pidg)
    kept = [s_ for s_ in proj["segments"] if s_["source"] in kept_src and (s_.get("target") or "").startswith("ПЕРЕВОД")]
    # Абзац на СТЫКЕ страниц разбор целого файла вправе склеить с соседней
    # страницей — его перевод уходит в prevTarget (граница названа в CLAUDE.md,
    # инвариант 43). Внутренние абзацы страницы обязаны сохраниться.
    check(r.status_code == 200 and len(proj["segments"]) > len(kept_src)
          and len(kept) >= len(kept_src) - 1 and not proj.get("guestCut"),
          "дописан весь документ, перевод страницы гостя на месте (%d из %d), отметка снята"
          % (len(kept), len(kept_src)))
except ImportError:
    print("  (reportlab нет — проверка PDF пропущена)")

print()
print("ПРОШЛО" if not fail else "ПРОВАЛЫ: %d" % len(fail))
sys.exit(1 if fail else 0)
