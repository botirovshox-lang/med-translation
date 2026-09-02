"""Корзина «оценка ниже порога», зона судьи на коротком сегменте и ремонт по
мелким замечаниям.

Три правки, у которых одна общая причина: система показывала цифру там, где
измерения не было, и звала человека разбираться с благополучными строками.

  1. `_machine_clean` отвечает на вопрос «можно ли учить этим глоссарий», а
     корзина в /analysis подписана «оценка ниже порога». Переписанный ремонтом
     сегмент отказ получает по первому вопросу (система не заверяет собственную
     правку), а человек читает второй — и идёт смотреть текст, у которого
     back-check 100% и termcheck чист. На боевом проекте таких было 306 из 511.

  2. Доля выживших основ на сегменте из одного-двух слов бывает только 0 или 1.
     «Фтизиатрия → Phthisiology → Фтизиология» получает 0% при верном переводе,
     а ноль лежит НИЖЕ зоны судьи — значит спросить некого и приговор выносит
     обрезка слова до шести букв. Для таких сегментов низ зоны открыт.

  3. Находки termcheck уровня minor не брал никто: ремонт чинил только
     critical/major, а `_machine_clean` всё равно считал сегмент нечистым.
     168 сегментов висели между двумя политиками. Теперь их чинят — но заход,
     где кроме мелочи ничего не было, обязан снять хотя бы одно из ТЕХ САМЫХ
     замечаний, ради которых заходили. Поимённо, а не по количеству: termcheck
     на переписанном тексте почти всегда добавляет свою придирку, и счёт
     «1 → 1» выбросил бы верную правку, а сегмент заклеймил бы `tried` — то
     есть чинить его больше не пришли бы никогда.

  4. Список действующих уровней живёт на сервере и отдаётся браузеру
     (`/api/models` → `termcheckActionable`). Литерал в .jsx — это ровно то
     расхождение, из-за которого строка «Ремонт» обещала бы 168 сегментов,
     а кнопка под ней говорила «нечего запускать».

Платных вызовов нет: и правка, и обе перепроверки подменены.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
import checks as medical_qa

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg_of(sid, source, target, **kw):
    s = {"id": sid, "source": source, "target": target, "status": "translated"}
    h = main._text_hash(target.strip())
    if "bc" in kw:
        s["backcheck"] = dict(kw["bc"], target_hash=h)
    if "tc" in kw:
        s["termcheck"] = dict(kw["tc"], target_hash=h)
    if "repair" in kw:
        s["repair"] = dict(kw["repair"], source_hash=main._text_hash(target))
    return s


def project_of(segments, glossary=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in glossary],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    main._IMPACT_CACHE.clear()
    return proj


CLEAN_BC = {"score": 100, "model": "gpt-5.6-luna", "back": "ок", "reasons": []}
CLEAN_TC = {"model": "gpt-5.6-terra", "findings": []}


# ─────────── 1. Починенный ремонтом не идёт в «оценку ниже порога» ───────────
print("=== 1. Починенный ремонтом — не «оценка ниже порога» ===")
repaired = seg_of(1, "Жалобы на задний циклит.", "Complaints about posterior cyclitis.",
                  bc=CLEAN_BC, tc=CLEAN_TC,
                  repair={"applied": True, "from": "old", "issues": ["«rear cyclitis»"]})
low = seg_of(2, "Длинная строка про очаговый туберкулёз лёгких у взрослых пациентов.",
             "A long line about focal pulmonary tuberculosis in adult patients.",
             bc={"score": 61, "model": "gpt-5.6-luna", "back": "иначе", "reasons": ["не совпало"]},
             tc=CLEAN_TC)
project_of([repaired, low])
a = main.project_analysis(1)

check(main._machine_clean(repaired, 90) == main.CLEAN_REPAIRED,
      "сегмент с применённым ремонтом чистым не считается — глоссарий он не учит")
check(1 in a["repaired"], "но своя строка у него есть: «Исправила машина»")
check(1 not in a["todo"]["weak"],
      "и в «оценку ниже порога» он не попал — там ему нечего делать")
check(a["todo"]["weak"] == [2],
      "в корзине остался только тот, у кого балл действительно ниже порога")
check(all(w["reason"] != main.CLEAN_REPAIRED for w in a["todo"]["weakWhy"]),
      "разбор причин про ремонт тоже молчит")

# Исчерпаемость корзин — тот же закон, что и раньше: сегмент, не попавший
# никуда, исчезает с экрана, и картина выглядит благополучнее, чем есть.
seen = set(a["clean"]) | set(a["repaired"]) | set(a["todo"]["weak"]) \
    | set(a["todo"]["untranslated"]) | set(a["todo"]["unchecked"]) \
    | set(a["todo"]["findings"]) | set(a["human"]["confirmedFindings"])
check(seen == {1, 2}, "оба сегмента видны хотя бы в одной корзине")


# ─────────── 2. Короткий оригинал: лексика не мерит, зону открываем ───────────
print("\n=== 2. Короткий оригинал — вопрос к судье, а не приговор ===")
check(medical_qa.lexically_blind("Фтизиатрия"), "одно слово — мерить нечем")
check(medical_qa.lexically_blind("Современный этап"), "два слова — тоже")
check(not medical_qa.lexically_blind("Клиника очагового туберкулёза лёгких"),
      "четыре содержательных слова — мера уже работает")

res = medical_qa.run_backcheck("Фтизиатрия", "Фтизиология")
check(res["score"] == 0, "балл действительно ноль: основы «фтизиа» и «фтизио» разные")
check(any("содержательных слов" in r for r in res["reasons"]),
      "но причина названа честно, а не «часть текста не совпала дословно»")
check(not any("вопрос к судье" in r for r in res["reasons"]),
      "и разбирательства не обещано: звали судью или нет, run_backcheck не знает")
hardres = medical_qa.run_backcheck("Доза 5 мг", "Доза 15 мг")
check(hardres["reasons"] == ["расхождение чисел"],
      "при жёсткой находке про «нечем измерить» молчим — тут как раз измерили")
check(not any("не совпала дословно" in r for r in res["reasons"]),
      "и прежняя отговорка её не подменяет")

check(main._judge_zone("Фтизиатрия") == (0, main.JUDGE_ZONE[1]),
      "низ зоны судьи для короткого сегмента открыт")
check(main._judge_zone("Клиника очагового туберкулёза лёгких") == main.JUDGE_ZONE,
      "для обычного сегмента зона прежняя")

short = seg_of(1, "Фтизиатрия", "Phthisiology",
               bc={"score": 0, "model": "gpt-5.6-luna", "back": "Фтизиология",
                   "judged": False, "judge_skipped": "zone", "reasons": []})
long_lo = seg_of(2, "Длинная строка про очаговый туберкулёз лёгких у взрослых пациентов.",
                 "A long line about focal pulmonary tuberculosis in adult patients.",
                 bc={"score": 12, "model": "gpt-5.6-luna", "back": "про другое",
                     "judged": False, "judge_skipped": "zone", "reasons": []})
hard = seg_of(3, "Доза 5 мг", "Dose 15 mg",
              bc={"score": 30, "model": "gpt-5.6-luna", "back": "Доза 15 мг",
                  "judged": False, "judge_skipped": "hard", "reasons": ["расхождение чисел"]})
check(not main._backcheck_cached(short, "gpt-5.6-luna", True),
      "короткий сегмент, отброшенный ПРЕЖНЕЙ зоной, судью ещё ждёт")
check(main._backcheck_cached(long_lo, "gpt-5.6-luna", True),
      "длинный с тем же низким баллом судью не ждёт: там ноль что-то значит")
check(main._backcheck_cached(hard, "gpt-5.6-luna", True),
      "жёсткая находка судью отменяет при любой длине — отменить её он не вправе")
check(main._backcheck_cached(short, "gpt-5.6-luna", False),
      "без судьи проверка закончена и на коротком сегменте")

cli = main._segment_for_client(short)
check(cli["backcheck"]["needs_judge"] is True,
      "браузеру признак отдаёт сервер: свою зону в .jsx не повторяем")
check(main._segment_for_client(long_lo)["backcheck"]["needs_judge"] is False,
      "и он же говорит, что длинному сегменту судья не нужен")
check(main._segment_for_client(hard)["backcheck"]["needs_judge"] is False,
      "жёсткая находка — не пробел в проверке")


# ─────────── 3. Ремонт берёт minor ───────────
print("\n=== 3. Мелкие замечания чинятся, но обязаны убавляться ===")
MINOR = {"tgt_term": "EPT", "suggestion": "EPTB", "severity": "minor",
         "why": "стандартное сокращение — EPTB"}
OLD_T = "EPT is common."
NEW_T = "EPTB is common."


def build_minor(findings, **kw):
    s = seg_of(1, "ВЛТ встречается часто.", OLD_T, bc=CLEAN_BC,
               tc={"model": "gpt-5.6-terra", "findings": [dict(f) for f in findings]}, **kw)
    return project_of([s]), s


def termcheck_returns(findings):
    def fake(s, p, *a, **k):
        s["termcheck"] = {"model": "gpt-5.6-terra", "at": "2026-08-25 12:00",
                          "target_hash": main._text_hash((s["target"] or "").strip()),
                          "findings": [dict(f) for f in findings]}
        return {"ok": True}
    main._run_segment_termcheck = fake


proj, seg = build_minor([MINOR])
kinds = main._repair_findings(seg, proj)
check([f["kind"] for f in kinds] == ["term"], "мелкая находка стала поводом для ремонта")
check(kinds[0]["sev"] == "minor", "и тяжесть едет вместе с ней — по ней считают итог")

main._openai_repair = lambda *a, **k: NEW_T
termcheck_returns([])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True, "мелочь убавилась с 1 до 0 — правку приняли")
check(seg["target"] == NEW_T, "текст исправлен")
check(seg["status"] == "review", "и заверять его всё равно человеку")

# Заказанное снято, а termcheck нашёл на новом тексте СВОЮ придирку — это
# успех, а не ничья. Считать по количеству («1 → 1») значило бы выбросить
# верную правку EPT→EPTB и заклеймить сегмент tried, то есть больше к нему
# не прийти никогда.
proj, seg = build_minor([MINOR])
main._openai_repair = lambda *a, **k: NEW_T
termcheck_returns([{"tgt_term": "common", "suggestion": "frequent", "severity": "minor",
                    "why": "другое мелкое"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True,
      "заказанное замечание снято — правку приняли, хотя мелочи столько же")
check(seg["target"] == NEW_T, "исправление на месте")

# А вот когда то же самое замечание осталось — заход не дал ничего.
proj, seg = build_minor([MINOR])
main._openai_repair = lambda *a, **k: "EPT is frequent."
termcheck_returns([dict(MINOR)])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "заказанное замечание осталось — откат")
check(seg["target"] == OLD_T, "текст вернулся к прежнему")
check("не снято" in seg["repair"]["reason"],
      "и причина называет замечание, а не «не стало лучше»")

# Рост мелочи при снятом заказе — тоже откат: две новые придирки взамен одной
# старой это не работа.
proj, seg = build_minor([MINOR])
main._openai_repair = lambda *a, **k: NEW_T
termcheck_returns([{"tgt_term": "common", "suggestion": "frequent", "severity": "minor", "why": "раз"},
                   {"tgt_term": "is", "suggestion": "are", "severity": "minor", "why": "два"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "мелочи стало больше — откат даже при снятом заказе")

# Побочная мелочь не должна отменять правку ради серьёзной находки:
# иначе разрешение чинить мелочь ОТНИМАЕТ автоматизацию там, где она была.
GLOSS = [{"src": "ВЛТ", "tgt": "EPTB", "tier": "verified", "cat": "Disease",
          "lang": "RU→EN", "domain": "medical"}]
s = seg_of(1, "ВЛТ встречается часто.", OLD_T, bc=CLEAN_BC, tc=CLEAN_TC)
proj = project_of([s], GLOSS)
check(any(f["kind"] == "gloss" for f in main._repair_findings(s, proj)),
      "повод серьёзный: утверждённого термина в переводе нет")
main._openai_repair = lambda *a, **k: NEW_T
termcheck_returns([{"tgt_term": "common", "suggestion": "frequent", "severity": "minor",
                    "why": "побочная мелочь"}])
r = main._run_segment_repair(s, proj)
check(r.get("applied") is True,
      "правка ради глоссария принята, хотя появилось мелкое замечание")
check(s["target"] == NEW_T, "утверждённый термин встал на место")

# Смешанный заход мелочью не меряется вовсе: у него есть свои счётчики (балл,
# серьёзные находки, нарушенные приказные термины). Откатывать верную
# подстановку термина из-за придирки termcheck значит отнять автоматизацию там,
# где она работала.
s = seg_of(1, "ВЛТ встречается часто.", OLD_T, bc=CLEAN_BC,
           tc={"model": "gpt-5.6-terra", "findings": [dict(MINOR)]})
proj = project_of([s], GLOSS)
main._openai_repair = lambda *a, **k: NEW_T
termcheck_returns([{"tgt_term": "common", "suggestion": "frequent", "severity": "minor",
                    "why": "раз"},
                   {"tgt_term": "is", "suggestion": "are", "severity": "minor",
                    "why": "два"}])
r = main._run_segment_repair(s, proj)
check(r.get("applied") is True, "смешанный заход принят: его меряют другие оценки")
check(s["target"] == NEW_T, "утверждённый термин на месте")

# ─────────── 4. Короткий сегмент без судьи: своя причина, а не «ниже порога» ───────────
print("\n=== 4. Балл не измерен — так и сказано ===")
blind = seg_of(1, "Фтизиатрия", "Phthisiology",
               bc={"score": 0, "model": "gpt-5.6-luna", "back": "Фтизиология",
                   "judged": False, "reasons": []},
               tc=CLEAN_TC)
project_of([blind])
a = main.project_analysis(1)
check(a["todo"]["weak"] == [1], "сегмент в корзине — донором глоссария он не станет")
check([w["reason"] for w in a["todo"]["weakWhy"]] == [main.CLEAN_LEX_BLIND],
      "но причина своя: «балл не измерен», а не «оценка ниже порога»")

judged = seg_of(2, "Фтизиатрия", "Phthisiology",
                bc={"score": 45, "model": "gpt-5.6-luna", "back": "Фтизиология",
                    "judged": True, "reasons": ["судья: смысл расходится"]},
                tc=CLEAN_TC)
project_of([judged])
a = main.project_analysis(1)
check([w["reason"] for w in a["todo"]["weakWhy"]] != [main.CLEAN_LEX_BLIND],
      "судья ответил — балл измерен, и отговорки про длину больше нет")


# ─────────── 5. Обратный перевод не покупается второй раз ───────────
print("\n=== 5. Судье нужен судья, а не новый обратный перевод ===")
calls = []
main._openai_translate = lambda *a, **k: calls.append(k.get("model")) or "НОВЫЙ обратный"
main._openai_judge = lambda *a, **k: {"same_meaning": True, "severity": "none",
                                      "comment": "то же понятие", "model": "gpt-5.6-terra"}
s5 = seg_of(1, "Фтизиатрия", "Phthisiology",
            bc={"score": 0, "model": "gpt-5.6-luna", "back": "Фтизиология",
                "judged": False, "judge_skipped": "zone", "reasons": []})
proj = project_of([s5])
r = main._run_segment_backcheck(s5, proj, "gpt-5.6-luna", True, "gpt-5.6-terra", harvest=False)
check(calls == [], "за обратный перевод второй раз не заплатили — он лежал в сегменте")
check(s5["backcheck"]["back"] == "Фтизиология", "и взят именно прежний текст")
check(s5["backcheck"]["model"] == "gpt-5.6-luna",
      "модель названа та, что перевод и делала, а не выбранная в списке")
check(s5["backcheck"]["judged"] is True and s5["backcheck"]["score"] == 95,
      "судья ответил «то же понятие» и поднял балл")
check(main._backcheck_cached(s5, "gpt-5.6-luna", True), "теперь проверка закончена")

# Молчание судьи — «не знаю»: отметка есть, законченной проверка не считается.
main._openai_judge = lambda *a, **k: None
s6 = seg_of(2, "Фтизиатрия", "Phthisiology",
            bc={"score": 0, "model": "gpt-5.6-luna", "back": "Фтизиология",
                "judged": False, "judge_skipped": "zone", "reasons": []})
proj = project_of([s6])
main._run_segment_backcheck(s6, proj, "gpt-5.6-luna", True, "gpt-5.6-terra", harvest=False)
check(s6["backcheck"]["judge_skipped"] == "failed", "молчание судьи записано в сегмент")
check(not main._backcheck_cached(s6, "gpt-5.6-luna", True),
      "но за законченную проверку не сходит: спросить ещё раз правильно и теперь дёшево")

# Прогон ДРУГОЙ моделью готовое не переиспользует — там просят новый взгляд.
calls.clear()
s7 = seg_of(3, "Фтизиатрия", "Phthisiology",
            bc={"score": 0, "model": "gpt-5.6-luna", "back": "Фтизиология",
                "judged": False, "judge_skipped": "zone", "reasons": []})
s7["target"] = "Tuberculosis medicine"   # текст правили — проверка устарела
# (висящий пробел здесь НЕ годится: хеш считается по обрезанному тексту,
#  и «Phthisiology » — тот же текст, а не другой)
proj = project_of([s7])
main._openai_judge = lambda *a, **k: None
main._run_segment_backcheck(s7, proj, "gpt-5.6-luna", True, "gpt-5.6-terra", harvest=False)
check(calls == ["gpt-5.6-luna"], "проверка устарела — обратный перевод делается заново")


# ─────────── 5b. Судья добирается до коротких сегментов и вправе их поднять ───────────
print("\n=== 5b. Что мешало судье поднять короткий сегмент ===")
GL_F = [{"src": "Фтизиатрия", "tgt": "Phthisiology", "tier": "verified"}]
rb = medical_qa.run_backcheck("Фтизиатрия", "Фтизиология", GL_F)
check(rb["terms_lost"] == ["Фтизиатрия"], "термин по основам «не пережил круг» — находка есть")
check(rb["hard"] is False,
      "но жёсткой она на коротком оригинале не считается: это то же сравнение "
      "основ, что дало и сам ноль, а не независимая улика")
lifted = medical_qa.apply_judge_verdict(dict(rb),
    {"same_meaning": True, "severity": "none", "comment": "одна дисциплина", "model": "t"})
check(lifted["score"] == 95, "судья прочитал оба текста и поднял балл")
check(lifted["terms_lost"] == [],
      "и снял претензию про термин — иначе ремонт пошёл бы переписывать верный перевод")
check(any("снято судьёй" in r for r in lifted["reasons"]),
      "улику не выбросили молча: сказано, кто её отменил и почему")

rp = medical_qa.apply_judge_verdict(medical_qa.run_backcheck("плевры,", "плевра,"),
    {"same_meaning": True, "severity": "minor",
     "comment": "различается только грамматическая форма", "model": "t"})
check(rp["score"] == 95,
      "«minor + смысл тот же» на коротком сегменте тоже поднимает: судья там "
      "единственная мера, а ноль никто не измерял")

# На длинном сегменте теперь то же самое, и это правка, а не послабление:
# «пережила ли словоформа перефразировку» — то же сравнение основ, что дало
# и сам балл, и от длины оригинала это не зависит. Прежде находка считалась
# жёсткой на длинном сегменте и гасила судью у 303 сегментов боевого проекта,
# то есть отнимала апелляцию у претензии, которую апелляция и должна снимать.
LG = [{"src": "противотуберкулёзный", "tgt": "anti-tuberculosis", "tier": "verified"}]
rl = medical_qa.run_backcheck(
    "В 1920 году открыт первый противотуберкулёзный диспансер в городе.",
    "В 1920 году открыт первый туберкулёзный диспансер в городе.", LG)
check(rl["terms_lost"] == ["противотуберкулёзный"],
      "«противотуберкулёзный» против «туберкулёзного» — потеря настоящая, "
      "отвалившаяся приставка меняет понятие")
check(rl["hard"] is False,
      "но жёсткой находкой она не считается и на длинном оригинале: судья "
      "вправе её отменить, а числа и единицы — нет")
rl2 = medical_qa.apply_judge_verdict(dict(rl),
    {"same_meaning": True, "severity": "none", "comment": "ок", "model": "t"})
check(rl2["score"] == 95 and rl2["terms_lost"] == [],
      "судья, прочитавший оба текста, поднимает балл и снимает претензию "
      "при любой длине — соблюдение глоссария сторожит _gloss_misses по тексту "
      "перевода, и от вердикта судьи оно не зависит")
rl3 = medical_qa.apply_judge_verdict(
    medical_qa.run_backcheck("Длинная строка про очаговый туберкулёз лёгких у взрослых.",
                             "Совсем другая строка про погоду и настроение сегодня."),
    {"same_meaning": True, "severity": "minor", "comment": "мелочь", "model": "t"})
check(rl3["score"] < 90, "и minor на длинном сегменте по-прежнему ничего не поднимает")

# Запись «пропущен по жёсткой находке», сделанная ПРЕЖНИМ правилом, не запирает
# короткий сегмент: иначе открытая зона до него так и не дойдёт.
stale = seg_of(1, "Фтизиатрия", "Phthisiology",
               bc={"score": 0, "model": "gpt-5.6-luna", "back": "Фтизиология",
                   "judged": False, "judge_skipped": "hard",
                   "terms_lost": ["Фтизиатрия"],
                   "reasons": ["потерян термин: Фтизиатрия"]})
check(not main._backcheck_cached(stale, "gpt-5.6-luna", True),
      "старая отметка «hard» из-за потерянного термина сегмент не запирает")
real_hard = seg_of(2, "Доза 5 мг", "Dose 15 mg",
                   bc={"score": 30, "model": "gpt-5.6-luna", "back": "Доза 15 мг",
                       "judged": False, "judge_skipped": "hard",
                       "terms_lost": ["Доза"],
                       "reasons": ["расхождение чисел", "потерян термин: Доза"]})
check(main._backcheck_cached(real_hard, "gpt-5.6-luna", True),
      "а настоящая объективная находка запирает — числа от длины не зависят")


# ─────────── 6. Список действующих уровней браузер получает, а не выдумывает ───────────
print("\n=== 6. Уровни ремонта — один источник на сервер и браузер ===")
md = main.list_models()
check(md.get("termcheckActionable") == list(main.TERMCHECK_ACTIONABLE),
      "/api/models отдаёт тот же кортеж, по которому чинит ремонт")
check(md.get("backcheckMinStems") == medical_qa.BACKCHECK_MIN_STEMS,
      "и порог «короткого оригинала» тоже, чтобы подсказка не врала числом")
check(main.TERMCHECK_DISPUTING == ("critical", "major"),
      "а спор с приказом глоссария по-прежнему только по серьёзным находкам: "
      "стилистическая придирка не повод звать человека отменять своё решение")

BAD = 'f.severity === "critical" || f.severity === "major"'
for f in ("frontend/js/tab_editor.jsx", "frontend/js/tab_editor_detail.jsx",
          "frontend/js/tab_preflight.jsx"):
    src = open(f, encoding="utf-8").read()
    check(BAD not in src, f + ": состав ремонта не вбит литералом")
    check("tcActionable" in src, f + ": берёт уровни из серверного списка")


print()
if fail:
    print("ПРОВАЛЕНО: " + str(len(fail)))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
