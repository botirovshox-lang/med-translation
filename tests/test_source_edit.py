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
# Не только дроби: степень и индекс без операнда, корень без подкоренного,
# знак, которому обязан быть операнд, — всё по ОДНОМУ списку знаков Юникода
# (интегралы, корни, суммы, сравнения), общему с чисткой текстового слоя.
check(checks.broken_math("настоять 2-3 час^, процедить") == ["час^"],
      "степень без операнда — повреждение (боевая строка книги)")
check(checks.broken_math("значение √") == ["√"], "корень без подкоренного — тоже")
check(checks.broken_math("таблица: — ± —") == ["±"], "знак, которому нечего складывать, — тоже")
check(checks.broken_math("2^3 равно 8") == [], "целая степень молчит")
check(checks.broken_math("5 ± 2 мм") == [] and checks.broken_math("a ≤ b всегда") == [],
      "знак с операндами молчит")
check(checks.broken_math("корень √ из числа") == [],
      "и там, где сказать нельзя, молчим: за знаком стоит слово")
check(checks.broken_math("∫ f(x) dx") == [] and checks.broken_math("стрелка → вправо") == [],
      "интеграл и стрелка законно стоят сами по себе")
check(checks.broken_math("температура 37±0,5 °С") == [], "«±0,5» и градус — не повреждение")
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
print("=== 7. Дописанное РУКАМИ — это страницы, и они списываются ===")
# Страница — мера ЗАКАЗА, и до этой правки она равнялась объёму ФАЙЛА. Правка
# оригинала объёма не добавляла вовсе, а потолок у неё — 20 000 знаков НА
# СТРОКУ: файл в одну страницу с десятью строками превращался в сотню страниц
# перевода по цене одной. Считаем приращением в момент правки — высшая точка
# ПРОЕКТА (как у картинок) здесь не годится, см. комментарий у `_hand_pages_quote`.
TID = main.DEFAULT_TENANT
rec = main._tenant_rec(TID)
check(rec is not None, "запись организации есть")
rec["pagesCredit"] = 1000.0
rec["pagesUsed"] = 0.0
rec["pagesLog"] = []
Q = live(pid)
Q["handPages"] = 0.0
Q["handPagesBooked"] = 0.0
Q["pages"] = 40.0                       # книга на 40 страниц: допуск = 2 стр.
CARD = main._pricing_of(TID)
main._PAGES_CACHE.clear()

WORD = "слово%d"
BIG = " ".join([WORD % i for i in range(1200)])        # ~4.8 страницы


def edit(i, text, dry=False, force=True):
    """`force` по умолчанию True: почти везде ниже мы ВПИСЫВАЕМ текст
    намеренно, а дверь роста строки проверяется своим разделом (7г)."""
    return c.post("/api/segments/%d/%d/source" % (pid, ids[i]), headers=H(A),
                  json={"source": text, "dry_run": dry, "force": force})


def used():
    return float(main._tenant_rec(TID).get("pagesUsed") or 0.0)


def grown(i, words):
    """Тот же оригинал плюс столько слов — проверяемый прирост объёма."""
    return (live(pid)["segments"][i]["source"] or "") + " " + " ".join(WORD % k for k in range(words))


check(abs(main._hand_free_pages(live(pid), CARD) - 2.0) < 0.01,
      "допуск на книге в 40 стр. — низ, а не доля: %s" % main._hand_free_pages(live(pid), CARD))
tiny = dict(live(pid), pages=1.0)
check(main._hand_free_pages(tiny, CARD) == 0.5,
      "на файле в одну страницу допуск не больше половины файла: %s" % main._hand_free_pages(tiny, CARD))

# Починка бесплатна — ради неё дверь и заведена (инвариант 26 прямо называет
# дефектом «исправление опечатки стоило бы денег»).
r = edit(1, PARAS[1].replace("*/", "1/3"), dry=True)
check(r.status_code == 200 and r.json()["pages"]["debit"] == 0,
      "сухой прогон: починка опечатки не стоит ничего: %s" % r.text[:150])
check(used() == 0.0 and float(live(pid).get("handPages") or 0) == 0.0,
      "сухой прогон не тронул ни организацию, ни счётчик проекта")
r = edit(1, PARAS[1].replace("*/", "1/3"))
check(r.status_code == 200 and r.json()["pages"]["debit"] == 0, "починка применена даром")
check(used() == 0.0, "страницы за починку не списаны")

# Дописанное В ПРЕДЕЛАХ допуска тоже даром — но уже КОПИТСЯ.
r = edit(1, grown(1, 200))          # +0.8 стр., допуск 2
check(r.status_code == 200 and r.json()["pages"]["add"] > 0.7, "дописано 200 слов")
check(r.json()["pages"]["debit"] == 0, "в пределах допуска — даром: %s" % r.json()["pages"])
check(used() == 0.0, "и ничего не списано")
check(float(live(pid)["handPages"]) > 0.7, "но счётчик дописанного растёт: %s" % live(pid)["handPages"])

# Дописанное СВЕРХ допуска — списывается, и ровно сверх него.
before, hand_before = used(), float(live(pid)["handPages"])
r = edit(0, BIG)
check(r.status_code == 200, "крупная правка применена: %s %s" % (r.status_code, r.text[:120]))
paid1 = r.json()["pages"]["debit"]
check(paid1 > 0, "за дописанное списано: %s" % paid1)
check(abs((used() - before) - paid1) < 0.01,
      "счётчик организации вырос ровно на списанное: %s → %s" % (before, used()))
check(abs(float(live(pid)["handPages"]) - float(live(pid)["handPagesBooked"]) - 2.0) < 0.05,
      "бесплатным осталось ровно допуск: дописано %s, погашено %s"
      % (live(pid)["handPages"], live(pid)["handPagesBooked"]))
log = [e for e in main._tenant_rec(TID)["pagesLog"] if e["kind"] == "edit"]
check(len(log) == 1 and log[0]["project"] == pid, "в журнале страниц строка `edit`: %s" % log[:1])

print("")
print("=== 7а. Туда-обратно платится ОДИН раз, а новая строка — снова ===")
# Высшая точка у КАЖДОЙ строки своя (`seg["handPeak"]`): «вставил абзац
# не туда → стёр → вставил верный» — типовая работа редактора, и платить
# за неё дважды нельзя.
before = used()
r = edit(0, PARAS[0])                                   # стёрли дописанное
check(r.status_code == 200 and r.json()["pages"]["add"] == 0, "сокращение ничего не дописало")
check(used() == before, "и ничего не вернуло — счётчики монотонны")
r = edit(0, BIG)                                        # вписали то же заново
check(r.status_code == 200 and r.json()["pages"]["debit"] == 0,
      "тот же объём в той же строке второй раз не оплачивается: %s" % r.json()["pages"])
check(used() == before, "счётчик организации не сдвинулся")

# А вот ДРУГАЯ строка — новый объём, и он платный, даже если след правки
# стёрт пересборкой (`_boundary_reset`, замена файла, `/resegment` снимают
# `sourceEdited`): счёт идёт приращением, а не пересчётом состояния.
for sg in live(pid)["segments"]:
    sg.pop("sourceEdited", None)
before = used()
r = edit(2, BIG)
check(r.status_code == 200 and r.json()["pages"]["debit"] > 4,
      "другая строка списана ЗАНОВО, а не прощена: %s" % r.json()["pages"])
check(used() - before > 4, "счётчик организации вырос второй раз")

print("")
print("=== 7б. Лимит режет деньги, а не работу ===")
# Исчерпанный лимит запирает КРУПНУЮ правку (это покупка объёма), но НЕ
# починку: вписать потерянную цифру человек обязан мочь всегда, иначе
# оплаченная книга остаётся с браком распознавания навсегда.
rec = main._tenant_rec(TID)
rec["pagesCredit"] = round(main._tenant_usage(TID)["pages"], 3)      # остатка нет
snap = (used(), float(live(pid)["handPages"]), float(live(pid)["handPagesBooked"]))
src3 = live(pid)["segments"][3]["source"]
r = edit(3, BIG)
check(r.status_code == 402, "крупная правка при исчерпанном лимите — 402: %s" % r.status_code)
check("пополните лимит у администратора" in r.text, "отказ называет, что делать: %s" % r.text[:160])
check(live(pid)["segments"][3]["source"] == src3, "и ничего не записал")
check((used(), float(live(pid)["handPages"]), float(live(pid)["handPagesBooked"])) == snap,
      "402 не сдвинул ни одного счётчика")
r = edit(3, grown(3, 3))
check(r.status_code == 200, "а мелкая правка при исчерпанном лимите проходит: %s %s"
      % (r.status_code, r.text[:120]))
check(r.json()["pages"]["debit"] > 0 and not r.json()["pages"]["ask"],
      "она уходит в минус молча: о долях страницы человека не спрашивают: %s" % r.json()["pages"])

# Рубеж отказа — РАЗМЕР правки, а не сам факт списания.
rec["pagesCredit"] = 100000.0
small = main._hand_pages_quote(live(pid), TID, CARD, live(pid)["segments"][3], grown(3, 100))
big = main._hand_pages_quote(live(pid), TID, CARD, live(pid)["segments"][3], grown(3, 200))
check(0 < small["debit"] < main.HAND_PAGES_REFUSE_MIN <= big["debit"],
      "100 слов ниже рубежа отказа, 200 — выше: %s / %s" % (small["debit"], big["debit"]))
check(big["ask"] and not main._hand_pages_quote(
          live(pid), TID, CARD, live(pid)["segments"][3], grown(3, 5))["ask"],
      "а разговаривают с человеком с `HAND_PAGES_ASK_MIN`, это другой порог")

print("")
print("=== 7в. Без действующего лимита списывать некуда — и долг не гасится ===")
# Организация без счётчика (`pagesUsed`) и без выданных страниц не ограничена
# ничем: там нечего списывать. Прежняя версия в этом случае растила
# `handPagesBooked` («долг погашен»), ничего не списав, — и взять его второй
# раз было уже нельзя. Рубеж 402, запись и отчёт обязаны стоять на ОДНОМ
# условии, иначе лимит режет работу, не беря денег (инвариант 15).
rec.pop("pagesCredit", None)
rec.pop("pagesUsed", None)
save_max, main.TENANT_MAX_PAGES = main.TENANT_MAX_PAGES, 0
free_pid = live(pid)
free_pid["handPages"], free_pid["handPagesBooked"] = 0.0, 0.0
for sg in free_pid["segments"]:
    sg.pop("handPeak", None)
r = edit(3, BIG + " ещё")
check(r.status_code == 200, "правка без лимита проходит: %s" % r.status_code)
check(r.json()["pages"]["debit"] == 0, "и суммы не называет — брать её некому: %s" % r.json()["pages"])
check(float(live(pid)["handPagesBooked"]) == 0.0,
      "долг не объявлен погашенным: %s" % live(pid)["handPagesBooked"])
check(float(live(pid)["handPages"]) > 4, "а сам объём записан — его видно владельцу")
main.TENANT_MAX_PAGES = save_max
rec["pagesCredit"] = 100000.0
rec["pagesUsed"] = 0.0
check(main._tenant_usage(TID)["handPages"] > 4,
      "дописанное руками видно отдельной строкой: %s" % main._tenant_usage(TID)["handPages"])

print("")
print("=== 7г. Строка, выросшая втрое, — новый текст, а не поправка ===")
# Дверь, а не стена: на странице скана разбор отдаёт огрызок вместо абзаца,
# и вписать туда текст можно только руками. Поэтому 409 с разрешением,
# а не запрет, и сухой прогон о нём ПРЕДУПРЕЖДАЕТ, а не падает.
# Строка к этому месту уже выросла прошлыми разделами — ставим короткий
# оригинал прямо в проект: мерка роста считается от НЕГО.
live(pid)["segments"][3]["source"] = "Показания к применению:"
short = live(pid)["segments"][3]["source"]
huge = short + " " + " ".join(WORD % k for k in range(300))
r = edit(3, huge, dry=True)
check(r.status_code == 200 and r.json()["tooBig"] is True,
      "сухой прогон называет рост заранее: %s" % r.text[:160])
check(r.json()["maxLen"] == main._source_growth_max(short),
      "и называет потолок тем же числом, каким его считает сервер")
r = edit(3, huge, force=False)
check(r.status_code == 409, "без разрешения — 409: %s" % r.status_code)
check(live(pid)["segments"][3]["source"] == short, "и ничего не записано")
r = edit(3, huge, force=True)
check(r.status_code == 200 and live(pid)["segments"][3]["source"] == huge,
      "с разрешением — записано: %s" % r.status_code)
# Запас в знаках: у короткой подписи «втрое» — это восемнадцать знаков,
# и без запаса дописать её было бы нельзя вовсе.
check(main._source_growth_max("Рис. 7") >= 300 + len("Рис. 7"),
      "у короткой строки потолок — запас в знаках, а не кратность: %s"
      % main._source_growth_max("Рис. 7"))

print("")
print("=== 7д. Работа человека: набранный и правленый перевод ===")
# Пощада была одна — подпись. Человек, написавший перевод в строке и не
# нажавший «Подтвердить», для ремонта, ревизии и остальных пакетов был
# неотличим от машины: прогон переписывал его текст, а прежний не сохранялся
# даже в `prevTarget`. Состояние заводим НАСТОЯЩИМ эндпоинтом: фабрикация
# полей руками прошла бы и на сломанном коде — см. «Промпты проверяются
# НАСТОЯЩИМ кодом» в CLAUDE.md.
hw = ids[2]


def set_target(sid, text, status=None):
    body = {"target": text}
    if status:
        body["status"] = status
    return c.post("/api/segments/%d/%d/update" % (pid, sid), headers=H(A), json=body)


def seg_of(sid):
    return next(x for x in live(pid)["segments"] if x["id"] == sid)


# 1) Перевод, НАБРАННЫЙ с нуля (строка была пустой) — самый частый вид
#    ручной работы, и он тоже под защитой.
live(pid)["segments"][2]["target"] = ""
live(pid)["segments"][2]["status"] = "new"
live(pid)["segments"][2].pop("editedBy", None)
live(pid)["segments"][2].pop("editedToHash", None)
r = set_target(hw, "qo'lda yozilgan tarjima")
check(r.status_code == 200, "перевод набран через /update: %s" % r.status_code)
check(main._hand_written(seg_of(hw)), "набранный с нуля — работа человека")
check(main._human_text(seg_of(hw)), "и рубеж пакетов его видит")

# 2) Машина написала поверх — защита снимается САМА, а текст не пропадает.
sg = seg_of(hw)
main._replace_target(sg, "машинный вариант", "m", "GPT_REQUIRED")
check(sg.get("prevTarget") == "qo'lda yozilgan tarjima",
      "набранное ушло в «Прежний перевод»: %s" % sg.get("prevTarget"))
check(sg.get("status") == "review", "и статус говорит «посмотри»: %s" % sg.get("status"))
check(not main._hand_written(sg), "защита снялась сама")
check(sg.get("editedBy") is None and sg.get("prevEditedBy") is not None,
      "след правки уехал вместе с текстом, а не врёт про машинный: %s / %s"
      % (sg.get("editedBy"), sg.get("prevEditedBy")))

# 3) Стёртый перевод работой человека НЕ считается — иначе «стёр, чтобы
#    перевести заново» получало бы отказ «это ваш текст» (инвариант 33).
r = set_target(hw, "")
check(r.status_code == 200 and not main._hand_written(seg_of(hw)),
      "пустая строка — не работа человека")
check(main._needs_translation(seg_of(hw)), "и она по-прежнему ждёт перевода")

# 4) Рубеж ПАКЕТА на настоящей находке: ремонт ручную строку без разрешения
#    не берёт и НАЗЫВАЕТ её, а не молчит.
r = set_target(hw, "Tuberkulez o'pka kasalligi")
check(r.status_code == 200, "текст набран заново")
sg = seg_of(hw)
th = main._text_hash((sg.get("target") or "").strip())
sg["termcheck"] = {"target_hash": th, "model": "m", "version": 1,
                   "findings": [{"severity": "major", "tgt_term": "Tuberkulez",
                                 "why": "калька", "use": "Sil"}]}
check(bool(main._repair_findings(sg)), "находка на строке есть — рубеж проверяем на работе")
# Рубеж читаем РАЗБОРОМ СОСТАВА: он считает тем же кодом, что прогон,
# и модель не зовёт — то есть проверка работает и без ключа.
r = c.post("/api/projects/%d/run-plan" % pid, headers=H(A),
           json={"segment_ids": [hw], "steps": ["repair"]})
check(r.status_code == 200, "разбор состава ответил: %s %s" % (r.status_code, r.text[:120]))
plan = next((x for x in (r.json().get("steps") or []) if x.get("step") == "repair"), {})
check(plan.get("count") == 0,
      "ремонт ручную строку БЕЗ разрешения не берёт: %s" % str(plan)[:200])
why = " ".join(str(x) for x in (plan.get("skips") or []))
check("ваша строка" in why or "мои строки" in why,
      "и причина названа человеческими словами, а не молчанием: %s" % why[:160])
# С разрешением — берёт, и это то же самое разрешение.
r = c.post("/api/projects/%d/run-plan" % pid, headers=H(A),
           json={"segment_ids": [hw], "steps": ["repair"], "include_confirmed": True})
plan2 = next((x for x in (r.json().get("steps") or []) if x.get("step") == "repair"), {})
check(plan2.get("count") == 1, "с разрешением ремонт её берёт: %s" % str(plan2)[:200])
check(seg_of(hw).get("target") == "Tuberkulez o'pka kasalligi", "текст на месте")

# 4а) Корзины: ручная строка с находкой — у ЧЕЛОВЕКА, а не у машины, и корзины
#     остаются исчерпывающими (иначе сегмент исчезает с экрана).
r = c.get("/api/projects/%d/analysis" % pid, headers=H(A))
check(r.status_code == 200, "разбор посчитан: %s" % r.status_code)
if r.status_code == 200:
    tk = r.json().get("turnkey") or {}
    ready, mach, hum = tk.get("ready") or [], tk.get("machine") or [], tk.get("human") or []
    check(hw in hum, "ручная строка с находкой — у ЧЕЛОВЕКА: %s" % hum)
    check(hw not in mach and hw not in ready,
          "и не обещана машине и не объявлена готовой: machine=%s ready=%s" % (mach, ready))
    check(hw not in (tk.get("confirmed") or []),
          "срез подписи её не считает — подписи нет: %s" % tk.get("confirmed"))
    # Корзины непересекающиеся и в сумме равны числу строк: сегмент, выпавший
    # из всех, исчезает с экрана, а это худшая из здешних ошибок.
    allb = ready + mach + hum
    check(len(allb) == len(set(allb)), "корзины не пересекаются: %s" % allb)
    check(len(allb) == len(live(pid)["segments"]),
          "и в сумме равны числу строк: %d из %d" % (len(allb), len(live(pid)["segments"])))
sg.pop("termcheck", None)

# 5) Признак для браузера считает СЕРВЕР: копия предиката в `.jsx`
#    разошлась бы (он стоит на хеше текста).
r = c.get("/api/projects/%d" % pid, headers=H(A))
row = next(x for x in r.json()["segments"] if x["id"] == hw)
check(row.get("handWritten") is True, "handWritten уезжает браузеру: %s" % row.get("handWritten"))

# 6) Снял подпись — текст остался твоим. `_harvest_edited_terms` снимает хеш
#    на подтверждении, и без отметки строка осталась бы беззащитной.
r = c.post("/api/segments/%d/%d/confirm" % (pid, hw), headers=H(A))
check(r.status_code == 200, "строка заверена: %s" % r.status_code)
check(main._human_text(seg_of(hw)), "заверенное — работа человека по статусу")
r = c.post("/api/segments/%d/%d/revert" % (pid, hw), headers=H(A))
check(r.status_code == 200 and seg_of(hw).get("status") != "confirmed", "подпись снята")
check(main._hand_written(seg_of(hw)),
      "и текст снова под защитой как ручной, а не остался голым")

print("")
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
