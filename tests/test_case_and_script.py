"""Регистр букв и буквы чужого письма — две бесплатные находки ремонта.

Поломка одна и приходит она из глоссария: «use these exact translations»
модель понимает буквально и копирует НАЧЕРТАНИЕ записи. На боевом учебнике
это дало 36 испорченных сегментов в обе стороны — «6. Кавернозный туберкулёз»
→ «6. cavitary tuberculosis» и «туберкулёза органов дыхания» → «RESPIRATORY
TUBERCULOSIS» посреди фразы.

Здесь проверяется и лечение (промпт называет правило), и находка, по которой
уже написанный перевод попадёт в ремонт. Платных вызовов нет.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. Промпт перевода называет правило о регистре ===")
sysmsg = main._translate_system("RU", "EN", [
    {"src": "Туберкулема", "tgt": "Tuberculoma", "tier": "verified"},
    {"src": "эритема", "tgt": "erythema"},
], None, False, "medical", main._resolve_model(None))
check("capitalisation of the source" in sysmsg, "правило о регистре есть в промпте")
check("Not a single letter of the" in sysmsg,
      "и требование «ни одной буквы исходного письма» — тоже")
check("ALL-CAPS heading stays ALL-CAPS" in sysmsg, "КАПС-заголовок остаётся КАПСОМ")
order, hint = sysmsg.split("Unverified glossary hints")
check("Copy the right-hand side letter for letter" in order,
      "у приказных записей сказано: начертание уже подогнано, копируй как есть")
check("already matched to the source fragment" in hint,
      "и у подсказок тоже")

print("=== 2. Обратный перевод правило не получает ===")
lit = main._translate_system("EN", "RU", None, None, True, "medical",
                             main._resolve_model(None))
check("capitalisation of the source" not in lit,
      "в literal-режиме лишних правил нет: он обязан ОТРАЖАТЬ текст")

print("=== 3. Промпт ремонта тоже ===")
rep = main._repair_system(main._resolve_domain("medical"), "RU", "EN")
check("capitalisation of the SOURCE" in rep,
      "ремонт не вернёт строчную в заголовок следом за правкой термина")

print("=== 4. Находка: строчная в начале ===")
def miss(src, tgt):
    return main._case_misses({"source": src, "target": tgt})

got = miss("6. Кавернозный туберкулёз", "6. cavitary tuberculosis")
check(len(got) == 1 and got[0]["kind"] == "case",
      "«6. Кавернозный туберкулёз» → «6. cavitary tuberculosis» — находка")
check(not miss("6. Кавернозный туберкулёз", "6. Cavitary tuberculosis"),
      "исправленный вариант находкой не считается")
check(not miss("вирулентности и дозы МБТ,", "virulence and dose of MBT,"),
      "обрывок фразы со строчной в оригинале — не находка")
check(not miss("139-Рис. Эритема Базена", "Fig. 139. Erythema induratum of Bazin"),
      "подпись с номером впереди: регистр считается по первой БУКВЕ")

print("=== 5. Находка: КАПС-заголовок ===")
check(len(miss("ТУБЕРКУЛИНОВАЯ ДИАГНОСТИКА", "tuberculin testing")) == 2,
      "оба правила разом: и строчная в начале, и потерянный КАПС")
check(not miss("ПРЕДИСЛОВИЕ", "PREFACE"),
      "КАПС сохранён — молчим (в переводе букв меньше, и это не повод)")
check(not miss("МБТ", "M. tuberculosis"),
      "короткая аббревиатура заголовком не считается")
check(miss("3 ГЛАВА. ЭТИОЛОГИЯ ТУБЕРКУЛЁЗА", "CHAPTER 3. ETIOLOGY OF tuberculosis"),
      "слово из глоссария, оставшееся строчным внутри КАПС-заголовка")

print("=== 6. Находка: капс, которого в оригинале не было ===")
got = miss("Для лабораторной диагностики туберкулеза органов дыхания",
           "For laboratory diagnosis of RESPIRATORY TUBERCULOSIS")
check(len(got) == 1 and "RESPIRATORY TUBERCULOSIS" in got[0]["text"],
      "капс-цепочка посреди фразы — находка")
check(not miss("ИФА – иммуноферментный анализ", "ELISA – enzyme-linked immunosorbent assay"),
      "одиночная аббревиатура законна где угодно")
check(not miss("В 2009 году учреждение получило статус", "In 2009 the institution became RSNPMCFP"),
      "и придуманный в переводе акроним тоже")
check(not miss("ТУБЕРКУЛЕЗ ОРГАНОВ ДЫХАНИЯ", "RESPIRATORY TUBERCULOSIS"),
      "перенос КАПС-заголовка — не капс «из ниоткуда»")

print("=== 7. Письмо без регистра — молчим ===")
check(not miss("Туберкулёз лёгких", "肺结核"),
      "у иероглифов регистра нет: выдуманная находка хуже отсутствующей")

print("=== 8. Буквы чужого письма ===")
def alien(src, tgt):
    return main._script_misses({"source": src, "target": tgt})

got = alien("Основным источником инфекции является больной, выделяющий МБТ",
            "The main source of infection is a patient excreting (МБТ+)")
check(len(got) == 1 and got[0]["kind"] == "script" and "МБТ" in got[0]["text"],
      "кириллическая аббревиатура в английском тексте — находка, и она названа")
check(alien("Температура тела 38 градусов", "Body temperature 38°С"),
      "кириллическая «С» в «38°C» неотличима на глаз и потому ловится только так")
check(alien("Кроме синдрома интоксикации", "Besides intoxication syndrome, РО2 falls"),
      "кириллические буквы внутри формулы")
check(not alien("Основным источником инфекции является больной",
                "The main source of infection is a patient"),
      "чистый перевод находкой не считается")
check(not alien("Возбудитель Mycobacterium bovis вызывает болезнь",
                "Mycobacterium bovis causes the disease"),
      "латиница в русском оригинале переводу не мешает")
check(not alien("Туберкулёз лёгких", "Туберкульоз легень"),
      "одна письменность у обоих языков (RU→UK) — молчим, буквы там общие")
check(not alien("Туберкулёз лёгких", "肺结核"),
      "и наоборот: в переводе нет ни одной буквы оригинала")

print("=== 9. Находка доезжает до ремонта и до его оценки ===")
seg = {"id": 1, "source": "Серозный менингит", "target": "serous meningitis"}
check(any(f["kind"] == "case" for f in main._repair_findings(seg, None)),
      "_repair_findings отдаёт находку по регистру")
check(main._repair_scores(seg, None)["case"] == 1,
      "_repair_scores считает её — значит откат сработает")
seg2 = {"id": 2, "source": "Больной выделяет МБТ", "target": "The patient excretes МБТ"}
check(any(f["kind"] == "script" for f in main._repair_findings(seg2, None)),
      "_repair_findings отдаёт находку по чужому письму")
check(main._repair_scores(seg2, None)["script"] == 1,
      "_repair_scores считает и её")
check(main._repairable(seg, project=None),
      "сегмент попадает в состав ремонта")

print("=== 10. Правка одного регистра — это правка ===")
check(not main._same_words("Serous meningitis", "serous meningitis"),
      "_same_words различает регистр: иначе правка читалась бы как «нечего менять»")
check(main._same_words("serous  meningitis", " serous meningitis "),
      "а лишние пробелы — не правка")

print("=== 11. Регистр глоссарного термина — 1в1 по оригиналу ===")
cl = main._case_like
check(cl("ТУБЕРКУЛЕЗ ОРГАНОВ ДЫХАНИЯ", "respiratory tuberculosis",
         "ТУБЕРКУЛЕЗ ОРГАНОВ ДЫХАНИЯ") == "RESPIRATORY TUBERCULOSIS",
      "капс заголовка переносится на перевод")
check(cl("RW", "Wassermann reaction", "RW") == "Wassermann reaction",
      "короткая аббревиатура заголовком не считается — крика не будет")
check(cl("Туберкулема", "tuberculoma", "Туберкулема") == "Tuberculoma",
      "заглавная в оригинале — заглавная в переводе")
check(cl("туберкулемы", "Tuberculoma", "Туберкулема") == "tuberculoma",
      "строчная в оригинале — строчная в переводе")
check(cl("реакции Манту", "Mantoux reaction", "реакция Манту") == "Mantoux reaction",
      "имя собственное внутри термина регистр не отдаёт")
check(cl("вакцины БЦЖ", "BCG vaccine", "вакцина БЦЖ") == "BCG vaccine",
      "и аббревиатура тоже")
check(cl("очага Гона", "Ghon focus", "очаг Гона") == "Ghon focus",
      "«очаг Гона» не превращается в «ghon focus»")
check(cl("туберкулёз", "肺结核", "туберкулёз") == "肺结核",
      "у письма без регистра переносить нечего")

print("=== 12. Расхождение по начертанию доезжает до ремонта ===")
def build(source, target, entry=("Туберкулема", "Tuberculoma")):
    seg = {"id": 1, "source": source, "target": target, "status": "review"}
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [seg]}
    main.STATE = {"projects": [proj], "termQueue": [], "exportHistory": [], "team": [],
                  "tm": [],
                  "glossary": [{"src": entry[0], "tgt": entry[1], "tier": "verified",
                                "lang": "RU→EN", "domain": "medical"}]}
    main._invalidate_gloss_index()
    return proj, seg

proj, seg = build("В казеозной части туберкулемы сосуды отсутствуют.",
                  "In the caseous part of a Tuberculoma vessels are absent.")
got = main._term_case_misses(seg, proj)
check(len(got) == 1 and got[0]["use"] == "tuberculoma",
      "заглавная посреди фразы найдена, и назван нужный вариант: %s" % got)
check(any(f["kind"] == "term_case" for f in main._repair_findings(seg, proj)),
      "находка доезжает до ремонта")
check(main._repair_scores(seg, proj)["term_case"] == 1,
      "и до его оценки — значит откат сработает")
check(main._repair_scores(seg, None)["term_case"] == 0,
      "без проекта глоссария нет, и претензии тоже — как у gloss рядом")

proj, seg = build("В казеозной части туберкулемы сосуды отсутствуют.",
                  "In the caseous part of a tuberculoma vessels are absent.")
check(not main._term_case_misses(seg, proj), "исправленный вариант претензии не даёт")

proj, seg = build("Туберкулема — это инкапсулированный очаг.",
                  "Tuberculoma is an encapsulated focus.")
check(not main._term_case_misses(seg, proj),
      "заглавная в оригинале — заглавная в переводе, всё сходится")

proj, seg = build("туберкулемы бывают разной величины.",
                  "Tuberculomas vary in size.")
check(not main._term_case_misses(seg, proj),
      "начало предложения оправдывает заглавную при строчной в оригинале")

proj, seg = build("Диагностика туберкулеза органов дыхания сложна.",
                  "Diagnosis of RESPIRATORY TUBERCULOSIS is difficult.",
                  ("ТУБЕРКУЛЕЗ ОРГАНОВ ДЫХАНИЯ", "RESPIRATORY TUBERCULOSIS"))
got = main._term_case_misses(seg, proj)
check(len(got) == 1 and got[0]["use"] == "respiratory tuberculosis",
      "капс записи не приказывает: в оригинале строчная — и в переводе строчная: %s" % got)

proj, seg = build("Диагностика туберкулеза органов дыхания сложна.",
                  "Diagnosis of tuberculosis is difficult.",
                  ("ТУБЕРКУЛЕЗ ОРГАНОВ ДЫХАНИЯ", "RESPIRATORY TUBERCULOSIS"))
check(not main._term_case_misses(seg, proj),
      "термина в переводе нет вовсе — это забота _gloss_misses, а не наша")

print("=== 13. В промпт уходит уже подогнанное начертание ===")
msg = main._translate_system("RU", "EN", [
    {"src": "Туберкулема", "tgt": "Tuberculoma", "tier": "verified",
     "_form": "туберкулемы"},
], None, False, "medical", main._resolve_model(None))
check("туберкулемы → tuberculoma" in msg,
      "слева форма из сегмента, справа перевод в её начертании")
check("Tuberculoma" not in msg,
      "словарное начертание в промпт не уходит вовсе — копировать нечего")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
