"""Приёмка ремонта: за слово, которое вписали МЫ, отвечаем мы.

Из-за чего написано. Боевой сегмент #62: оригинал «ЛЧ – лекарственная
чувствительность», в переводе стояло верное «DS – drug susceptibility».
Судья на обратном переводе объявил расхождение («Аббревиатура «ЛЧ» заменена
на «DS»»), балл срезался до 70 (JUDGE_CAP["major"]), ремонт пошёл по этой
претензии и транслитерировал сокращение — «LCh». Приёмка правку ПРИНЯЛА:
  • балл пересчитали, и он ВЫРОС 70 → 100 — калька возвращается обратным
    переводом дословно, а балл считает именно долю вернувшихся основ;
  • termcheck кандидата не считался вовсе (`had_tc` False — чинили-то
    по судейской претензии), и в записи так и лежит `after.terms: null`;
  • глоссарию угодила стоящая рядом расшифровка «drug susceptibility».
Termcheck высказался («LCh не принятая аббревиатура, нужно DS») уже ПОСЛЕ
приёмки — блоком освежения недостающей проверки, то есть поверх записанного
в документ текста.

Замер на боевом учебнике: 444 правки приняты этой слепой приёмкой, шесть
несут серьёзную находку termcheck, и каждое забракованное слово внесла сама
правка — «bacterial excretion» вместо верного «bacillary», «Conglomerative
tuberculoma» вместо «Conglomerate», «cavities of destruction» вместо
«cavitary lesions», «rheumatism», «"stamped" cavities», «LCh».

Проверяется здесь пять правил:
  1. termcheck кандидата считается на ЛЮБОМ заходе, и серьёзная находка
     на слове, которого в прежнем тексте НЕ БЫЛО, откатывает правку;
  2. унаследованная находка (слово стояло и до правки) её НЕ топит — чужая
     проблема не повод выбрасывать оплаченную работу;
  3. сорванный вызов termcheck на заходе БЕЗ термо-заказа ничего не ломает
     и ничего не откатывает: было «не знаю» — осталось «не знаю»;
  4. транслитерация сокращения — бесплатный счётчик, сверяемый ВСЕГДА:
     правка, внёсшая её, откатывается даже при молчащем termcheck;
  5. детектор транслитерации молчит там, где правило не измерено.

Платных вызовов нет: и правка, и обе перепроверки подменены.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def project_of(segments, src="RU", tgt="EN"):
    proj = {"id": 1, "title": "P", "src": src, "tgt": tgt, "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    main._IMPACT_CACHE.clear()
    return proj


def seg_of(source, target, tc_findings=(), judge_sev="major"):
    """Сегмент боевой формы: судья недоволен, termcheck прежнего текста чист.

    Именно так выглядели все 444 слепые приёмки — заход идёт по претензии
    судьи, то есть `had_tc` False, и мерить правку было нечем, кроме балла.
    """
    h = main._text_hash(target.strip())
    return {"id": 1, "source": source, "target": target, "status": "translated",
            "backcheck": {"score": 70, "model": "gpt-5.6-luna", "back": "обратный",
                          "reasons": [], "terms_lost": [], "judged": True,
                          "judge": {"severity": judge_sev, "same_meaning": False,
                                    "comment": "Аббревиатура «ЛЧ» заменена на «DS».",
                                    "divergences": ["сокращение изменено"]},
                          "target_hash": h},
            "termcheck": {"model": "gpt-5.6-terra", "target_hash": h,
                          "findings": [dict(f) for f in tc_findings]}}


tc_calls = []


def stub(new_text, findings_after, score_after=100, tc_raises=False):
    del tc_calls[:]
    def fake_bc(s, p, model=None, use_judge=False, judge_model=None, harvest=True, **kw):
        s["backcheck"] = {"score": score_after, "model": "gpt-5.6-luna",
                          "back": "обратный", "reasons": [], "terms_lost": [],
                          "hard": False, "judged": False,
                          "target_hash": main._text_hash((s["target"] or "").strip())}
        return {"ok": True}

    def fake_tc(s, p, *a, **k):
        tc_calls.append(s.get("target"))
        if tc_raises:
            raise RuntimeError("сеть отвалилась")
        s["termcheck"] = {"model": "gpt-5.6-terra",
                          "target_hash": main._text_hash((s["target"] or "").strip()),
                          "findings": [dict(f) for f in findings_after]}
        return {"ok": True}

    main._run_segment_backcheck = fake_bc
    main._run_segment_termcheck = fake_tc
    main._openai_repair = lambda *a, **k: new_text


# ─────────── 1. Внесённое правкой слово, забракованное проверкой ───────────
print("=== 1. За своё слово отвечаем мы ===")

# Боевой #62 дословно: заход по судейской претензии, правка транслитерирует
# сокращение, балл от этого РАСТЁТ.
SRC62 = "ЛЧ – лекарственная чувствительность"
seg = seg_of(SRC62, "DS – drug susceptibility")
proj = project_of([seg])
kinds = {f["kind"] for f in main._repair_findings(seg, proj)}
check(kinds == {"judge"}, "заход идёт по претензии судьи, термо-заказа в нём нет")

stub("LCh – drug susceptibility",
     [{"tgt_term": "LCh", "suggestion": "DS", "severity": "major",
       "why": "LCh не принятая аббревиатура"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False,
      "балл вырос 70 → 100, но термин, который вписала правка, забракован — откат")
check(seg["target"] == "DS – drug susceptibility", "в сегменте прежний верный текст")
reason = seg["repair"].get("reason") or ""
check("LCh" in reason, "и причина названа поимённо: %s" % reason)
check(seg["termcheck"]["findings"] == [],
      "termcheck отвергнутого текста не оставлен: он описывал бы слова, "
      "которых в сегменте нет")

# Тот же механизм на не-аббревиатуре: боевой #168, «bacillary» → «bacterial».
seg = seg_of("Позднее выявление больных с бактериовыделением;",
             "delayed identification of patients with bacillary excretion;")
proj = project_of([seg])
stub("delayed identification of patients with bacterial excretion;",
     [{"tgt_term": "bacterial excretion", "suggestion": "bacterial shedding",
       "severity": "major", "why": "не стандартный термин"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False,
      "«bacterial excretion» вписала правка — откат, хотя балл вырос")
check(main._translit_misses(seg, proj) == [],
      "и транслитерация тут ни при чём: сработало правило про внесённое слово")


# Прежней проверки не было вовсе — свежую снимаем СОВСЕМ, а не оставляем.
# Ветка новая: termcheck теперь считается и там, где раньше не считался,
# и оставленная запись описывала бы ОТВЕРГНУТЫЙ текст — находку про слова,
# которых в сегменте нет (по ней потом чинят ещё раз и покупают обратный
# перевод выброшенного варианта).
seg = seg_of(SRC62, "DS – drug susceptibility")
del seg["termcheck"]
proj = project_of([seg])
stub("LCh – drug susceptibility",
     [{"tgt_term": "LCh", "suggestion": "DS", "severity": "major", "why": "калька"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False, "правка откачена")
check("termcheck" not in seg,
      "termcheck снят совсем: прежнего не было, а свежий описывает выброшенный текст")

# ─────────── 2. Унаследованная находка правку не топит ───────────
print("\n=== 2. Чужая проблема — не повод выбрасывать оплаченную работу ===")
seg = seg_of("Очаговый туберкулёз лёгких протекает скрыто.",
             "Focal pulmonary tuberculosis is asymptomatic.")
proj = project_of([seg])
# Находка про слово, которое стояло в тексте И ДО правки: правка его
# не трогала, а termcheck на переписанном тексте почти всегда добавляет
# свою придирку — откатывать по ней значит терять верную работу.
stub("Focal pulmonary tuberculosis is latent.",
     [{"tgt_term": "Focal pulmonary tuberculosis", "suggestion": "Focal TB",
       "severity": "major", "why": "придирка к тому, что правка не трогала"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True,
      "замечание на слове из ПРЕЖНЕГО текста правку не отменяет")
check(seg["target"] == "Focal pulmonary tuberculosis is latent.",
      "правка осталась в сегменте")


# ─────────── 3. Сорванный вызов на заходе без термо-заказа ───────────
print("\n=== 3. «Не знаю» осталось «не знаю» ===")
seg = seg_of(SRC62, "DS – drug susceptibility")
proj = project_of([seg])
stub("DS – drug sensitivity", [], tc_raises=True)
r = main._run_segment_repair(seg, proj)
check(r.get("ok") is True, "оборванный termcheck не роняет ремонт с ошибкой")
check(r.get("applied") is True,
      "и не откатывает правку: заход шёл не по термо-находкам, "
      "мерить ими было нечего и до правки")
check((seg.get("repair") or {}).get("after", {}).get("terms") is None,
      "в записи честное «неизвестно», а не выдуманный ноль")


# ─────────── 4. Транслитерация: бесплатный счётчик ───────────
print("\n=== 4. Транслитерация откатывает и при молчащем termcheck ===")
seg = seg_of(SRC62, "DS – drug susceptibility")
proj = project_of([seg])
before = main._repair_scores(seg, proj)
check(before["translit"] == 0, "у верного текста побуквенных передач нет")
stub("LCh – drug susceptibility", [])          # termcheck МОЛЧИТ
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is False,
      "правка, внёсшая побуквенную передачу, откатывается сама — "
      "без единого вызова модели сверх обычных")
check("побуквенно" in (seg["repair"].get("reason") or ""),
      "и причина названа: %s" % (seg["repair"].get("reason") or ""))

# А НАХОДКОЙ она не становится, и это не забывчивость: `_plan_step`
# и «Анализ» зовут `_repair_findings` БЕЗ проекта (ради скорости), правило
# же привязано к паре языков — смета показывала бы «чинить нечего», а
# `repair_batch` сегмент забирал бы. Тот же приём, что у начертания
# приказных терминов: счётчик есть, находки нет.
seg = {"id": 1, "source": SRC62, "target": "LCh – drug susceptibility",
       "status": "translated"}
proj = project_of([seg])
check(main._repair_findings(seg, proj) == [],
      "находкой транслитерация не становится — иначе смета разошлась бы с работой")
check(main._repair_scores(seg, proj)["translit"] == 1,
      "но счётчик её видит: сломать сокращение правкой по другой претензии нельзя")
check(main._repair_scores(seg, None)["translit"] == 0,
      "без проекта — ноль, как и у глоссария рядом")


# ─────────── 1b. Вызов ровно один, и он не потерян ───────────
print("\n=== 1b. Termcheck кандидата: один вызов, не два и не ноль ===")
seg = seg_of("Очаговый туберкулёз протекает скрыто.", "Focal tuberculosis is hidden.")
proj = project_of([seg])
stub("Focal tuberculosis is asymptomatic.", [])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True, "правка принята")
check(tc_calls == ["Focal tuberculosis is asymptomatic."],
      "termcheck позван РОВНО раз и по НОВОМУ тексту: прежде он звался после "
      "приёмки, а два вызова — это двойная плата (получено: %r)" % (tc_calls,))
check(not main._check_stale(seg.get("termcheck") or {}, seg["target"]),
      "и запись termcheck описывает текст, который остался в сегменте")


# ─────────── 1c. Заход С термо-заказом правило не трогает ───────────
print("\n=== 1c. У захода по находкам termcheck мера прежняя — ПОИМЁННАЯ ===")
h = main._text_hash("Patient with rear cyclitis.")
seg = {"id": 1, "source": "Больной с задним циклитом.", "status": "translated",
       "target": "Patient with rear cyclitis.",
       "termcheck": {"model": "gpt-5.6-terra", "target_hash": h,
                     "findings": [{"tgt_term": "rear cyclitis",
                                   "suggestion": "posterior cyclitis",
                                   "severity": "major", "why": "калька"}]}}
proj = project_of([seg])
check({f["kind"] for f in main._repair_findings(seg, proj)} == {"term"},
      "заход идёт по находке termcheck")
# Заказанное снято, а новая придирка — к тому, что модель переписала попутно.
# Правило «подставленной фразы» сюда не заходит: у захода с заказом мера
# ПОИМЁННАЯ, и снимут этот гейт — тест покраснеет.
stub("Patient with posterior cyclitis and marked oedema.",
     [{"tgt_term": "marked oedema", "severity": "major", "why": "придирка"}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True,
      "заказанное снято — правка принята, хотя termcheck добавил свою придирку")


# ─────────── 1d. Спор с приказом глоссария — в пользу глоссария ───────────
print("\n=== 1d. Находка ПРОТИВ приказной записи правку не откатывает ===")
seg = seg_of("Туберкулема плотная.", "The lesion is dense.")
proj = project_of([seg])
stub("Tuberculoma is dense.",
     [{"tgt_term": "Tuberculoma", "suggestion": "tuberculous granuloma",
       "severity": "major", "why": "termcheck спорит с приказной записью",
       "vsVerified": True}])
r = main._run_segment_repair(seg, proj)
check(r.get("applied") is True,
      "правка, ВОССТАНОВИВШАЯ приказный термин, не откатывается мнением "
      "termcheck об этом термине")

# ─────────── 4b. Ревизия сверяет тот же счётчик ───────────
print("\n=== 4b. Ревизия переписывает пару целиком — и тоже под этим счётчиком ===")
seg = {"id": 1, "source": SRC62, "target": "DS - drug susceptibility",
       "status": "translated"}
proj = project_of([seg])
veto = main._review_veto(seg, proj, "LCh - drug susceptibility")
check("translit" in veto,
      "кандидат ревизии с побуквенной передачей не проходит вето")
check(main.REVIEW_VETO_LABELS.get("translit"),
      "и у вето есть подпись для человека, а не голый ключ")
check(main._review_veto(seg, proj, "DS - drug sensitivity") == [],
      "верный кандидат проходит")

# ─────────── 5. Где правило не измерено — молчим ───────────
print("\n=== 5. Узость правила ===")
CASES = [
    ("ЛЧ – лекарственная чувствительность", "LCh – drug susceptibility", True),
    ("Больной ТБ выявлен вовремя.", "The TB patient was identified in time.", False),
    ("Метод ПЦР подтвердил диагноз.", "PCR confirmed the diagnosis.", False),
    ("Поражение ЦНС встречается редко.", "CNS involvement is rare.", False),
    ("Уровень АЛТ повышен.", "ALT level is elevated.", False),
    ("Схема ДОТС применяется широко.", "The DOTS strategy is widely used.", False),
    ("МБТ обнаружены в мокроте.", "MBT were found in sputum.", False),
    ("ВИЧ-инфекция сопутствует.", "VICh infection is concomitant.", True),
    ("ВИЧ-инфекция сопутствует.", "HIV infection is concomitant.", False),
    ("Город Ташкент, клиника.", "The city of Tashkent, a clinic.", False),
    ("Процесс идёт быстро.", "The process is fast.", False),
    ("Назначен рифампицин.", "Rifampicin was prescribed.", False),
]
p_en = project_of([], src="RU", tgt="EN")
bad = [t for s, t, want in CASES
       if bool(main._translit_misses({"source": s, "target": t}, p_en)) != want]
check(not bad, "12 боевых пар разобраны верно (ТБ→TB, ПЦР→PCR, Ташкент — не находки)")

p_uz = project_of([], src="RU", tgt="UZ")
check(main._translit_misses({"source": SRC62, "target": "LCh – dori sezuvchanligi"}, p_uz) == [],
      "на RU→UZ молчим: «ch», «sh», «yo» — родные буквы узбекской латиницы, "
      "и правило там не измерено")
check(main._translit_misses({"source": SRC62, "target": "LCh – drug susceptibility"}) == [],
      "без проекта молчим: пары языков там нет (так же ведёт себя _gloss_misses)")


# ─────────── 5b. Ревизия сверяет ВСЕ бесплатные счётчики ───────────
print("\n=== 5b. Забытый ключ в REVIEW_FREE_KEYS ловится тестом, а не глазами ===")
keys = set(main._repair_scores({"id": 1, "source": "а", "target": "b"}, None))
paid = {"score", "terms", "terms_minor", "terms_lost"}
check((keys - paid) <= set(main.REVIEW_FREE_KEYS),
      "каждый бесплатный счётчик `_repair_scores` сверяется и ревизией: "
      "не хватает %s" % sorted((keys - paid) - set(main.REVIEW_FREE_KEYS)))

# ─────────── 6. Промпты говорят то же самое словами ───────────
print("\n=== 6. Предотвращение: промпт больше не требует буквализма ===")
dom = main._resolve_domain("medical")
rp = main._repair_system(dom, "RU", "EN")
check("not transliterated" in rp, "ремонт: аббревиатура переводится, а не переписывается")
check("abbreviations exactly as in the SOURCE" not in rp,
      "и прежнего «keep abbreviations exactly as in the SOURCE» больше нет — "
      "вместе с запретом букв исходного письма это и был приказ транслитерировать")
tr = main._translate_system("RU", "EN", [], {}, False, "medical",
                            main._resolve_model(main.DEFAULT_OPENAI_MODEL))
check("not transliterated" in tr, "перевод: то же правило и на самом раннем шаге")
check("abbreviations, and punctuation exactly as in the source" not in tr,
      "и та же ловушка убрана из промпта перевода")


print()
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail))
sys.exit(1 if fail else 0)
