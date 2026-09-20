# -*- coding: utf-8 -*-
"""Правка САМОГО оригинала человеком: POST /api/segments/{pid}/{sid}/source.

Зачем дверь. Распознаватель теряет знаки: на боевой книге («Пчелиная аптека»,
стр. 161) текстовый слой отдал «и пить его теплым по */ стакана» вместо
«по ¹/₃ стакана» — надстрочная «1» прочитана как «*», подстрочная «3»
потеряна СОВСЕМ. Цифры в файле нет, выдумать её нельзя, а вписать её должен
человек, глядя в книгу. До этой двери `seg["source"]` после импорта не менял
НИКТО, кроме ручных границ строк.

Что сторожим:
  1) мера правки решает, поправка это или другая строка (SOURCE_EDIT_KEEP);
  2) поправка НЕ выбрасывает перевод, подпись и оплаченные вердикты —
     она объявляет их устаревшими (`srcStale` рядом с `target_hash`);
  3) другая строка сбрасывает вердикты, но НЕ счётчики перевода заново
     (инвариант 33: предел организации нельзя снять правкой одной буквы),
     а снятая подпись оставляет след (инвариант 14);
  4) правленую строку узнаёт тот же файл: повторный импорт не объявляет её
     исчезнувшей и не списывает за неё страницы;
  5) чужой проект — 404 (инвариант 11), сегмент картинки — 400;
  6) повреждённая формула названа сама (`checks.broken_math`) и уходит
     человеку — в ту же корзину, где «повреждён сам оригинал».
"""
import io, os, sys, tempfile
from pathlib import Path
os.environ.setdefault("APP_PASSWORD", "srcedit-pass-1")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, "backend")
import main
import checks
from docx import Document
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main._DICTIONARIES = []
main.STATE["users"], main.STATE["tenants"] = [], []
main.STATE["projects"] = []
main.STATE["glossary"] = []
main.STATE["folders"] = []
main.STATE["dicts"] = []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
TMP = Path(tempfile.mkdtemp(prefix="medcat-srcedit-"))
main.SOURCE_DIR = TMP / "sources"
main.REIMPORT_DIR = TMP / "backups"
main.BOUNDARY_DIR = main.REIMPORT_DIR
main.EXPORT_DIR = TMP / "exports"
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
main._ensure_users()
A = c.post("/api/auth/login", json={"login": "admin", "password": "srcedit-pass-1"}).json()["token"]

PARAS = ["Настойки прополиса пить по 1/3 стакана два раза в день за двадцать минут.",
         "На стакан настоя и пить его теплым по */ стакана 3-4 раза в день до еды.",
         "Прополис используется пчелами в качестве антисептического материала улья.",
         "Свежесобранный прополис липкий и клейкий, со временем он твердеет совсем."]


def docx_bytes(paras):
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def live(pid):
    return next(p for p in main.STATE["projects"] if p["id"] == pid)


r = c.post("/api/projects/upload", headers=H(A), files={"file": ("book.docx", docx_bytes(PARAS))},
           data={"title": "book", "src": "RU", "tgt": "UZ", "domain": "general"})
check(r.status_code == 200, "файл загружен: %s %s" % (r.status_code, r.text[:120]))
pid = r.json()["id"]
P = live(pid)
ids = [s["id"] for s in P["segments"]]
check(len(ids) == 4, "четыре строки: %d" % len(ids))


def prep(i, **extra):
    """Строка с переводом, оплаченными вердиктами и счётчиком перевода заново."""
    s = live(pid)["segments"][i]
    s["target"] = "tarjima %d" % i
    s["status"] = "translated"
    s["mtDone"] = True
    s["retranslations"] = 2
    h = main._text_hash(s["target"])
    s["backcheck"] = {"score": 91, "target_hash": h, "model": "m", "reasons": [], "terms_lost": []}
    s["termcheck"] = {"target_hash": h, "model": "m", "findings": []}
    s.update(extra)
    return s


print("=== 1. Повреждённая формула названа, а цифра не выдумана ===")
check(checks.broken_math("и пить его теплым по */ стакана") == ["*/"], "«*/» — повреждение")
check(checks.broken_math("пить по */ стакана 2 раза") == ["*/"], "знак-обломок на месте цифры — тоже")
# А голая «/» между словами находкой НЕ считается: «да / нет», «ФИО / должность»,
# «п. 5 / 2020 г.» — обычный разделитель, и сервис продаётся не только в медицину.
# Звать человека править исправный оригинал договора нельзя.
check(checks.broken_math("Формат: да / нет") == [], "разделитель между словами — не повреждение")
check(checks.broken_math("п. 5 / 2020 г.") == [], "и «5 / 2020» тоже")
check(checks.broken_math("по 1/3-1/2 стакана") == [], "целая дробь молчит")
check(checks.broken_math("доза мг/кг и/или режим км/ч") == [], "«и/или», «мг/кг» не трогаем — там есть что делить")
check(checks.broken_math("обычный текст про пчёл") == [], "текста без формул правило не касается")
seg1 = live(pid)["segments"][1]
row = main._segment_for_client(seg1, live(pid))
check(row.get("sourceBroken") == ["*/"], "сегмент несёт сам кусок: %s" % row.get("sourceBroken"))
check((row.get("attention") or {}).get("src") == ["*/"], "и он же — в «на что смотреть»")
check("sourceBroken" not in main._segment_for_client(live(pid)["segments"][2], live(pid)),
      "у целой строки поля нет вовсе — вес выдачи не растёт")
prep(1)
arow = main._analysis_row(live(pid)["segments"][1], False, 90, live(pid))
check(arow["sourceSuspect"] is True, "в разборе — та же корзина, что у «повреждён сам оригинал»")

print("")
print("=== 2. Поправка: перевод и оплаченные вердикты остаются ===")
s = prep(0, status="confirmed", confirmedBy=1, confirmedAt="2026-09-19 10:00")
fixed = PARAS[0].replace("1/3", "1/4")
r = c.post("/api/segments/%d/%d/source" % (pid, ids[0]), headers=H(A),
           json={"source": fixed, "dry_run": True})
check(r.status_code == 200 and r.json()["mode"] == "fix" and r.json()["applied"] is False,
      "сухой прогон: поправка, ничего не записано (%s)" % r.text[:120])
check(live(pid)["segments"][0]["source"] == PARAS[0], "и правда ничего не записал")
r = c.post("/api/segments/%d/%d/source" % (pid, ids[0]), headers=H(A), json={"source": fixed})
check(r.status_code == 200 and r.json()["mode"] == "fix", "правка принята: %s" % r.text[:120])
s = live(pid)["segments"][0]
check(s["source"] == fixed, "оригинал заменён")
check(s["target"] == "tarjima 0" and s["status"] == "confirmed", "перевод и подпись человека на месте")
check(s.get("retranslations") == 2 and s.get("mtDone") is True, "счётчик перевода заново не тронут")
check(s["backcheck"].get("score") == 91 and s["backcheck"].get("srcStale") is True,
      "оценка цела, но объявлена устаревшей: %s" % s["backcheck"])
check(main._check_stale(s["backcheck"], s["target"]) is True, "и это видит ОДИН предикат свежести")
check(main._backcheck_cached(s, None, False) is False, "значит ближайший прогон посчитает её заново")
out = main._segment_for_client(s, live(pid))
check(out["backcheck"]["stale"] is True and out["termcheck"]["stale"] is True,
      "браузеру она тоже приходит устаревшей")
check(s["sourceEdited"]["from"] == PARAS[0], "прежний текст запомнен — по нему строку узнает файл")

print("")
print("=== 3. Другая строка: вердикты сняты, счётчик и след — нет ===")
prep(2, status="confirmed", confirmedBy=1, confirmedAt="2026-09-19 10:00")
other = "Совсем другой текст про мёд, липу и гречиху; ни одного прежнего слова."
r = c.post("/api/segments/%d/%d/source" % (pid, ids[2]), headers=H(A),
           json={"source": other, "dry_run": True})
check(r.json()["mode"] == "new" and r.json()["wasConfirmed"] is True,
      "сухой прогон предупреждает: строка станет новой и подпись снимется")
r = c.post("/api/segments/%d/%d/source" % (pid, ids[2]), headers=H(A), json={"source": other})
s = live(pid)["segments"][2]
check(s["source"] == other and s["status"] == "new" and s["target"] == "", "строка заведена заново")
check(s.get("prevTarget") == "tarjima 2" and s.get("prevSource"), "прежний перевод — подсказкой, не в мусор")
check("backcheck" not in s and "termcheck" not in s, "вердикты о прежней паре сняты")
check(s.get("retranslations") == 2 and s.get("mtDone") is True,
      "а счётчик перевода заново НЕ сброшен: предел организации правкой буквы не снимается")
check((s.get("unconfirmed") or {}).get("how") == "srcEdit" and not s.get("confirmedBy"),
      "подпись снята СО СЛЕДОМ: %s" % s.get("unconfirmed"))

print("")
print("=== 4. Тот же файл узнаёт правленую строку ===")
units = [(t, [i]) for i, t in enumerate(PARAS)]
plan_, removed_ = main._diff_units(live(pid), units, PARAS)
kept = sum(1 for p in plan_ if p and p[0] in ("keep", "moved"))
check(kept == 4 and not removed_,
      "повторный импорт того же файла: все четыре строки на месте, исчезнувших нет (%d, %d)"
      % (kept, len(removed_)))
check(main._diff_possible(live(pid), units, PARAS), "и проба видит в нём ту же редакцию")
pairs, matched = main._map_source_to_segments(units, live(pid)["segments"], PARAS)
check(matched == 4, "привязка исходника тоже узнаёт все четыре: %d" % matched)
plan = main._resegment_plan(live(pid), {"units": units, "full": PARAS})
check(plan["counts"]["manualEdits"] == 2,
      "а пересборка честно называет правки человека числом: %d" % plan["counts"]["manualEdits"])

print("")
print("=== 4a. Повторный импорт того же файла правку НЕ отменяет ===")
# Боевой ход: человек вписал потерянную цифру, потом залил ту же редакцию
# заново. Прежде строка объявлялась «другой»: правка стиралась текстом файла,
# перевод уходил в prevTarget, подпись снималась БЕЗ следа, а за строку
# списывались страницы — то есть исправление опечатки стоило денег.
fixed_seg = live(pid)["segments"][0]
was_src, was_tgt = fixed_seg["source"], fixed_seg["target"]
fixed_seg["status"] = "confirmed"
fixed_seg["confirmedBy"] = 1
r = c.post("/api/projects/%d/reimport" % pid, headers=H(A),
           files={"file": ("book.docx", docx_bytes(PARAS))}, data={"dry_run": "false"})
check(r.status_code == 200, "тот же файл принят: %s %s" % (r.status_code, r.text[:160]))
body = r.json()
s0 = live(pid)["segments"][0]
check(s0["source"] == was_src, "правка человека на месте, а не текст файла: %r" % s0["source"][-40:])
check(s0["target"] == was_tgt and s0["status"] == "confirmed", "перевод и подпись целы")
check(not s0.get("prevTarget"), "перевод не уехал в подсказку")
check((body.get("counts") or {}).get("added", 0) == 0 and (body.get("pages") or 0) == 0,
      "и страницы за неё не списаны: %s" % {k: body.get(k) for k in ("pages",)})

print("=== 4b. Вердикт арбитра тоже про ОРИГИНАЛ ===")
# «Верно ли термин передан ИМЕННО ЗДЕСЬ» — вопрос про оригинал, а своего
# `source_hash` у записи нет. Оставь её свежей — вердикт «передан верно»
# по ПРЕЖНЕМУ оригиналу продолжал бы снимать претензию `term_lost`, гасить
# корзину `human.termContextWrong` и закрывать сегмент от шага сверки.
sg = live(pid)["segments"][3]
sg["target"] = "tarjima 3"
sg["status"] = "translated"
sg["termContext"] = {"target_hash": main._text_hash("tarjima 3"),
                     "version": main.TERM_CONTEXT_VERSION, "all_terms": True, "terms": []}
check(main._term_context_stale(sg) is False, "пока оригинал не трогали — вердикт свежий")
r = c.post("/api/segments/%d/%d/source" % (pid, ids[3]), headers=H(A),
           json={"source": PARAS[3].replace("твердеет", "твердеет и густеет")})
check(r.status_code == 200 and r.json()["mode"] == "fix", "оригинал поправлен: %s" % r.text[:90])
sg = live(pid)["segments"][3]
check(sg["termContext"].get("srcStale") is True, "вердикт арбитра помечен")
check(main._term_context_stale(sg) is True, "и это ВИДИТ предикат свежести, а не только поле")

print("")
print("=== 4c. Двойник правленой строки не уводится к ней ===")
# Если в книге есть ВТОРОЙ сегмент с тем же текстом, каким строка была
# до правки, подмена ключа увела бы его абзац к правленой строке, а сам он
# оказался бы «исчезнувшим» — с переводом в копии и списанными страницами.
twin = {"id": 9001, "source": PARAS[1], "target": "t", "status": "translated",
        "comments": [], "qa": [], "wordCount": 9, "risk": "low", "route": "GPT_REQUIRED", "tm": None}
fake = {"id": pid, "segments": [
    dict(twin, id=9001, source=PARAS[1]),
    dict(twin, id=9002, source="ДРУГОЙ текст, вписанный человеком вместо прежнего.",
         sourceEdited={"from": PARAS[1], "by": 1, "at": "2026-09-20 10:00", "mode": "new"}),
]}
u2 = [(PARAS[1], [0]), ("ДРУГОЙ текст, вписанный человеком вместо прежнего.", [1])]
plan2, removed2 = main._diff_units(fake, u2, [t for t, _ in u2])
check(not removed2 and all(p and p[0] in ("keep", "moved") for p in plan2),
      "обе строки на месте, исчезнувших нет: %s / %s"
      % ([p and p[0] for p in plan2], [x["id"] for x in removed2]))

print("=== 5. Двери закрыты ===")
r = c.post("/api/segments/%d/%d/source" % (pid, ids[3]), headers=H(A), json={"source": "   "})
check(r.status_code == 400, "пустой оригинал — 400: %s" % r.status_code)
live(pid)["segments"][3]["origin"] = {"kind": "image", "part": "word/media/i1.png", "block": 0}
r = c.post("/api/segments/%d/%d/source" % (pid, ids[3]), headers=H(A), json={"source": "надпись"})
check(r.status_code == 400, "надпись с картинки правится разбором картинок — 400: %s" % r.status_code)
live(pid)["segments"][3].pop("origin")
r = c.post("/api/segments/%d/%d/source" % (pid + 999, ids[3]), headers=H(A), json={"source": "текст"})
check(r.status_code == 404, "чужой (несуществующий) проект — 404, а не 403: %s" % r.status_code)
r = c.post("/api/segments/%d/%d/source" % (pid, 99999), headers=H(A), json={"source": "текст"})
check(r.status_code == 404, "чужой сегмент — 404: %s" % r.status_code)
r = c.post("/api/segments/%d/%d/source" % (pid, ids[3]), json={"source": "текст"})
check(r.status_code == 401, "без токена — 401: %s" % r.status_code)

print("")
print("=== 6. Мера правки ===")
check(main._source_similarity("абв", "абв") == 1.0, "тот же текст — единица")
check(main._source_similarity("короткий", "короткий текст вдвое длиннее ещё и ещё") == 0.0,
      "длины разошлись вдвое — считать нечего, дешёвые ворота")
check(main._source_similarity(PARAS[0], PARAS[0].replace("1/3", "1/4")) >= main.SOURCE_EDIT_KEEP,
      "правка цифры — поправка")
check(main._source_similarity(PARAS[0], PARAS[3]) < main.SOURCE_EDIT_KEEP, "другой абзац — другая строка")

print("")
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
