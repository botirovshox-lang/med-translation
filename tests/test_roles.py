"""Роли и следы ответственного.

Роли три — владелец, редактор, переводчик. Право читается рангом
(«не ниже»): владельцу — всё, включая необратимое (`_OWNER_ONLY`);
редактор и переводчик в правах РАВНЫ — оба заверяют сегменты и решают
по терминам, а роль идёт в СЛЕД ответственного. `_EDITOR_ONLY` пуста
намеренно (решение владельца сервиса), проверка в `require_token` стоит
как место для прав на будущее.

След ответственного: на сегменте — `confirmedBy` (id) + `confirmedRole`
+ `confirmedAt`, имя приходит браузеру как `confirmedByName`; правка руками —
`editedBy`/`editedAt`; снятие заверения — `unconfirmed`. На записи глоссария —
`signedBy` {user, name, role, at, action}; на карточке очереди — `decidedBy`
(id) + `decidedName`/`decidedRole`; в TM — `by`. Прежние отметки "human"
законны навсегда. Роль берётся из СЕССИИ (роль в активной команде), а не
с записи пользователя. Ни одного вызова модели, файл состояния не пишется.
"""
import os, sys
os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ.pop("OPENAI_API_KEY", None)      # ни одного вызова модели: одобрение идёт с confirm=True
sys.path.insert(0, "backend")
import main
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"], main.STATE["glossary"], main.STATE["termQueue"] = [], [], []
main.STATE["tm"], main.STATE["audit"] = [], []
main._invalidate_gloss_index()
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
login = lambda l, p: c.post("/api/auth/login", json={"login": l, "password": p}).json()["token"]
A = login("admin", "boot-password-1")

print("=== 1. Три роли, и браузер знает свою ===")
check(main.ROLES == ("owner", "editor", "translator"), "ROLES: owner / editor / translator")
r = c.post("/api/admin/users", headers=H(A),
           json={"login": "eva", "password": "eva-pass-1234", "name": "Ева", "role": "editor"})
check(r.status_code == 200 and r.json()["user"]["role"] == "editor", "редактор заведён")
r = c.post("/api/admin/users", headers=H(A),
           json={"login": "tim", "password": "tim-pass-1234", "name": "Тим", "role": "translator"})
check(r.status_code == 200 and r.json()["user"]["role"] == "translator", "переводчик заведён")
r = c.post("/api/admin/users", headers=H(A),
           json={"login": "x", "password": "x-pass-123456", "role": "reviewer"})
check(r.status_code == 400, "неизвестная роль — 400")
eva = next(u for u in main._users() if u["login"] == "eva")
tim = next(u for u in main._users() if u["login"] == "tim")
E = login("eva", "eva-pass-1234")
T = login("tim", "tim-pass-1234")
me = c.get("/api/auth/me", headers=H(T)).json()
check(me["can"]["role"] == "translator" and me["can"]["owner"] is False, "/auth/me: can.role — роль в активной команде")
check(not hasattr(main, "_migrate_roles") and tim["role"] == "translator" and "roleSet" not in tim,
      "роли никто не мигрирует и не помечает: права редактора и переводчика равны")

print("=== 2. Права равны: переводчик заверяет, след — его ===")
check(main._EDITOR_ONLY == [], "_EDITOR_ONLY пуста намеренно")
pid = c.post("/api/projects", headers=H(A), json={"title": "Doc", "src": "RU", "tgt": "EN"}).json()["id"]
proj = next(p for p in main.STATE["projects"] if p["id"] == pid)
proj["segments"].append({"id": 1, "source": "Плевра", "target": "Pleura", "status": "translated",
                         "risk": "low", "provider": "gpt"})
proj["segments"].append({"id": 2, "source": "Лёгкое", "target": "Lung", "status": "translated",
                         "risk": "low", "provider": "gpt"})
r = c.post("/api/segments/%d/1/confirm" % pid, headers=H(T))
seg = proj["segments"][0]
check(r.status_code == 200 and seg["status"] == "confirmed", "переводчик заверил")
check(seg.get("confirmedBy") == tim["id"] and seg.get("confirmedRole") == "translator" and seg.get("confirmedAt"),
      "след: confirmedBy = id переводчика, confirmedRole = translator, confirmedAt")
check(main._confirmed_by_human(seg), "_confirmed_by_human читает id")
got = c.get("/api/projects/%d" % pid, headers=H(E)).json()
s1 = next(s for s in got["segments"] if s["id"] == 1)
check(s1.get("confirmedByName") == "Тим", "браузеру уходит имя заверившего (confirmedByName)")
rec = [a for a in main.STATE["audit"] if a.get("action") == "segment.confirm"][-1]
check(rec.get("user") == tim["id"] and rec.get("role") == "translator", "журнал действий несёт роль")
tm = [t for t in main.STATE["tm"] if t.get("src") == "Плевра"]
check(tm and tm[0].get("by") == tim["id"], "запись TM помнит, кто заверил")
r = c.post("/api/segments/%d/2/confirm" % pid, headers=H(E))
seg2 = proj["segments"][1]
check(r.status_code == 200 and seg2.get("confirmedRole") == "editor", "редактор заверил — роль в следе его")

print("=== 3. Снятие заверения и правка заверенного оставляют след ===")
r = c.post("/api/segments/%d/1/update" % pid, headers=H(E), json={"target": "Pleura", "status": "confirmed"})
check(r.status_code == 200 and seg["status"] == "confirmed" and seg.get("confirmedBy") == tim["id"],
      "тот же текст с тем же статусом (копия браузера) — подпись цела")
r = c.post("/api/segments/%d/1/update" % pid, headers=H(E), json={"target": "Pleura (fixed)", "status": "confirmed"})
check(r.status_code == 200 and seg["status"] == "translated" and "confirmedBy" not in seg,
      "правка заверенного текста снимает подпись: она относилась к прежнему тексту")
check(seg.get("prevTarget") == "Pleura" and seg.get("unconfirmed", {}).get("how") == "edit"
      and seg["unconfirmed"].get("by") == tim["id"] and seg["unconfirmed"].get("withdrawnBy") == eva["id"],
      "прежний текст в prevTarget; след: заверял Тим, снял правкой Ева")
check(seg.get("editedBy") == eva["id"] and seg.get("editedAt"), "правка руками помнит автора (editedBy)")
r = c.post("/api/segments/%d/1/update" % pid, headers=H(T), json={"status": "confirmed"})
check(r.status_code == 400 and seg["status"] != "confirmed", "статус confirmed через update — 400: заверение только командой")
r = c.post("/api/segments/%d/2/revert" % pid, headers=H(T))
check(r.status_code == 200 and seg2["status"] == "translated" and "confirmedBy" not in seg2
      and seg2["unconfirmed"].get("how") == "revert" and seg2["unconfirmed"].get("withdrawnBy") == tim["id"]
      and seg2["unconfirmed"].get("by") == eva["id"],
      "переводчик снял заверение редактора — отметка снята, след остался")
c.post("/api/segments/%d/2/confirm" % pid, headers=H(T))
check(seg2.get("confirmedRole") == "translator" and "unconfirmed" not in seg2,
      "новое заверение сменило подпись и убрало след снятия")

print("=== 4. Термины: решение, запись, понижение и вынос подписаны ===")
# Заверение в разделе 2 уже собрало свои карточки — очередь чистим, чтобы
# решать ровно по той карточке, которую заводим здесь.
main._term_queue().clear()
main._term_queue().append({"id": 1, "kind": "segment", "src": "плевра", "tgt": "pleura", "cat": "Anatomy",
                           "status": "pending", "tenant": "default", "lang": "RU→EN", "domain": "general",
                           "segment": 1, "project": pid, "hits": 1})
r = c.post("/api/term-queue/1/approve", headers=H(T), json={"confirm": True})
cand = main._term_queue()[0]
check(r.status_code == 200 and r.json().get("written") is True, "переводчик одобрил кандидата")
check(cand.get("decidedBy") == tim["id"] and cand.get("decidedName") == "Тим" and cand.get("decidedRole") == "translator",
      "карточка помнит, кто решил (id, имя, роль)")
check(main._human_decision(cand), "_human_decision читает id как решение человека")
g = next(x for x in main.STATE["glossary"] if x.get("src") == "плевра")
sb = g.get("signedBy") or {}
check(sb.get("user") == tim["id"] and sb.get("role") == "translator" and sb.get("action") == "approve" and sb.get("at"),
      "запись глоссария подписана: signedBy {user, role, action=approve, at}")
check(main._human_touched(g), "подпись — след решения человека для аудита")
r = c.post("/api/glossary", headers=H(T), json={"src": "каверна", "tgt": "cavity", "cat": "Term",
                                                "lang": "RU→EN", "domain": "general", "isNew": True})
g2 = next(x for x in main.STATE["glossary"] if x.get("src") == "каверна")
check(r.status_code == 200 and (g2.get("signedBy") or {}).get("action") == "add"
      and g2["signedBy"]["role"] == "translator", "переводчик добавил приказ — подпись add")
r = c.post("/api/glossary", headers=H(E), json={"src": "каверна", "tgt": "cavern", "cat": "Term",
                                                "lang": "RU→EN", "domain": "general"})
check(r.status_code == 200 and g2["tgt"] == "cavern" and g2["signedBy"]["action"] == "edit"
      and g2["signedBy"]["user"] == eva["id"] and g2["signedBy"]["role"] == "editor",
      "редактор поправил — подпись сменилась на его (edit, editor)")
r = c.post("/api/glossary/demote", headers=H(T), json={"src": "каверна", "lang": "RU→EN", "domain": "general"})
check(r.status_code == 200 and g2["tier"] == "auto" and g2["signedBy"]["action"] == "demote"
      and g2["signedBy"]["user"] == tim["id"] and g2["signedBy"]["role"] == "translator",
      "переводчик понизил приказ — подпись demote с его ролью")
check(not any(rx.pattern.endswith("demote$") or "purge" in rx.pattern for _, rx in main._OWNER_ONLY),
      "понижение и вынос не закрыты владельцем (у обоих есть откат)")
r = c.post("/api/glossary/purge", headers=H(E), json={"tier": "auto", "dry_run": True})
check(r.status_code == 200 and r.json().get("dryRun") is True, "вынос (сухой прогон) открыт редактору")
r = c.post("/api/term-queue/auto-approve", headers=H(T), json={"dry_run": True})
check(r.status_code == 200, "разбор автоодобрения открыт переводчику")

print("=== 5. Импорт приказом — владельцу, и роль из СЕССИИ ===")
files = {"file": ("g.csv", "src,tgt\nмокрота,sputum\n".encode("utf-8"), "text/csv")}
r = c.post("/api/glossary/import", headers=H(E), files=files,
           data={"lang": "RU→EN", "domain": "general", "tier": "verified", "dry_run": "false"})
check(r.status_code == 403, "редактор приказом не импортирует")
files = {"file": ("g.csv", "src,tgt\nмокрота,sputum\n".encode("utf-8"), "text/csv")}
r = c.post("/api/glossary/import", headers=H(A), files=files,
           data={"lang": "RU→EN", "domain": "general", "tier": "verified", "dry_run": "false"})
g3 = next((x for x in main.STATE["glossary"] if x.get("src") == "мокрота"), None)
check(r.status_code == 200 and g3 and (g3.get("signedBy") or {}).get("action") == "import"
      and g3["signedBy"]["user"] == 1, "владелец импортировал приказом — каждая запись подписана")
tok = main.CURRENT_SESSION.set({"tenant": "beta", "user": 1, "role": "translator"})
try:
    check(main._actor_role() == "translator", "_actor_role — роль в активной команде, а не домашняя")
    check(main._signed("edit")["role"] == "translator", "…и в подпись идёт она же")
finally:
    main.CURRENT_SESSION.reset(tok)

print("=== 6. Пачка автоодобрения возвращает подпись, которую переписала ===")
g4 = {"src": "очаг", "tgt": "focus", "cat": "Term", "tier": "auto", "conf": "medium", "note": "",
      "lang": "RU→EN", "domain": "general", "tenant": "default",
      "signedBy": {"user": eva["id"], "name": "Ева", "role": "editor", "at": "2026-09-01 10:00", "action": "demote"}}
main.STATE["glossary"].append(g4); main._invalidate_gloss_index()
cand2 = {"id": 2, "kind": "segment", "src": "очаг", "tgt": "lesion", "cat": "Term", "status": "pending",
         "tenant": "default", "lang": "RU→EN", "domain": "general", "hits": 3}
main._auto_write(cand2, "auto", 501, "2026-09-04")
check("signedBy" not in g4 and g4.get("prevSignedBy", {}).get("action") == "demote",
      "машинная запись сняла подпись человека и запомнила её")
main.STATE.setdefault("autoBatches", []).append({"id": 501, "tenant": "default", "kind": "auto"})
tok = main.CURRENT_SESSION.set({"tenant": "default", "user": 1, "role": "owner"})
try:
    main.undo_auto_approve(501)
finally:
    main.CURRENT_SESSION.reset(tok)
check(g4.get("tgt") == "focus" and (g4.get("signedBy") or {}).get("action") == "demote" and "prevSignedBy" not in g4,
      "откат пачки вернул перевод и подпись")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
