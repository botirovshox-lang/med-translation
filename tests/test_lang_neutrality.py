"""Балл back-check на любой письменности — честный, а не выдуманный.

Прежний разбор слов (`[а-яёa-z0-9]+`) видел два алфавита. «über» становился
«ber», а арабский, греческий, иврит и хинди давали НОЛЬ слов — и
`_content_recall` при пустом оригинале отвечал 1.0: балл 100 любому
переводу, включая пустой. На этом числе стоят зона судьи, порог донора
глоссария, корзины «Анализа» и откат ремонта.

Здесь два сторожа. Первый: на RU и EN разбор слов и балл остались ПОБАЙТНО
теми же — иначе пришлось бы поднимать BACKCHECK_VERSION и пересчитывать
боевой проект. Второй: на чужой письменности пустой или посторонний обратный
перевод НЕ получает отличной оценки. Платных вызовов нет.
"""
import os, re, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import medical_qa as q

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


# Прежний разбор — дословно, как золотой образец для кириллицы и латиницы.
def _old_stems(text):
    words = re.findall(r"[а-яёa-z0-9]+", q._norm(text))
    return [w[:6] if len(w) > 6 else w for w in words
            if len(w) >= 3 and w not in q.RU_STOPWORDS]


def _old_words(text):
    return [w for w in re.findall(r"[а-яёa-z0-9]+", q._norm(text))
            if len(w) >= 3 and w not in q.RU_STOPWORDS]


print("=== 1. RU и EN: разбор слов не изменился ===")
SAMPLES = [
    "Инфильтративный туберкулёз лёгких у больного 45 лет, МБТ+ (2HRZE/4HR).",
    "Фиброзно-кавернозный туберкулёз: полость 3,5 см в S1-S2 правого лёгкого.",
    "The patient denies chest pain; no fever, not detected on CT scan.",
    "Mycobacterium bovis — бактериовыделение сохраняется, ТЛЧ: MDR-TB.",
    "13 ГЛАВА. Клиника, диагностика и лечение",
    "",
    "— 40% —",
]
for s in SAMPLES:
    check(q._stems(s) == _old_stems(s), "stems: " + (s[:40] or "<пусто>"))
    check(q._words_of(s) == _old_words(s), "words: " + (s[:40] or "<пусто>"))
pairs = [(SAMPLES[0], "Инфильтративный туберкулез легких у пациента 45 лет, МБТ+ (2HRZE/4HR)."),
         (SAMPLES[2], "The patient does not deny chest pain; fever present."),
         (SAMPLES[4], "Глава 13. Клиника")]
for src, back in pairs:
    a = q.run_backcheck(src, back)
    old_recall = (lambda s, b: (lambda S, B: sum(min(c, B.get(w, 0)) for w, c in S.items())
                                 / sum(S.values()) if S else 1.0)
                  (q._Counter(_old_stems(s)), q._Counter(_old_stems(b))))(src, back)
    check(round(a["recall"], 3) == round(old_recall, 3), "recall тот же: " + src[:30])

print("=== 2. Чужая письменность: слова находятся, пустота не хвалится ===")
check(q._stems("Über die Lungenentzündung") == ["über", "die", "lungen"],
      "немецкий: «über» целиком, «Lungenentzündung» режется как латиница")
check(q._words_of("التهاب الرئة الحاد") == ["التهاب", "الرئة", "الحاد"], "арабский: три слова")
check(q._stems("Πνευμονία και βρογχίτιδα")[0] == "πνευμονία",
      "греческий: слово целиком, без обрезки под русское окончание")
for lang, src, alien in [
    ("AR", "التهاب الرئة الحاد لدى مريض بعمر 45 عاما", "نص آخر تماما عن شيء مختلف"),
    ("EL", "Οξεία πνευμονία σε ασθενή 45 ετών", "Κάτι εντελώς διαφορετικό εδώ"),
    ("HE", "דלקת ריאות חריפה בחולה בן 45", "משהו אחר לגמרי כאן"),
    ("DE", "Akute Lungenentzündung bei einem 45-jährigen Patienten", "Etwas völlig anderes hier"),
]:
    r = q.run_backcheck(src, alien, src_lang=lang)
    check(r["score"] is not None and r["score"] < 50,
          lang + ": посторонний обратный перевод не получает высокий балл (%s)" % r["score"])
    r0 = q.run_backcheck(src, "", src_lang=lang)
    check(r0["score"] is None, lang + ": пустой обратный перевод — балл не измерен")
    same = q.run_backcheck(src, src, src_lang=lang)
    check(same["score"] == 100, lang + ": дословный возврат — 100")

print("=== 3. Письмо без пробелов: мерить нечем — говорим об этом ===")
for lang, src in [("ZH", "患者急性肺炎伴发热"), ("JA", "患者は急性肺炎で発熱している"),
                  ("TH", "ผู้ป่วยปอดอักเสบเฉียบพลันมีไข้")]:
    r = q.run_backcheck(src, "совсем другой текст", src_lang=lang)
    check(r["lex_blind"], lang + ": lexically_blind — судья открыт до нуля")
    check(any("поднять балл" in x for x in r["reasons"]),
          lang + ": причина названа, а не «часть текста не совпала»")
    check(r["score"] != 100, lang + ": чужой обратный перевод не получает 100")

print("=== 4. Граница термина — по любой букве ===")
check(q._has_exact_term("التهاب الرئة", "الرئة"), "арабский термин находится")
check(not q._has_exact_term("الرئةالحاد", "الرئة"),
      "…но не внутри слитного слова: соседняя арабская буква — граница")
check(q._has_exact_term("туберкулёз лёгких", "лёгких") and not q._has_exact_term("облёгких", "лёгких"),
      "кириллица работает как раньше")

print("=== 5. Пара проекта — из каталога языков ===")
import main
main.save_state = lambda *a, **k: None
from fastapi import HTTPException
check(len(main.LANGUAGES) >= 60 and all("code" in l and "ru" in l for l in main.LANGUAGES),
      "каталог загружен: %d языков" % len(main.LANGUAGES))
check(main._check_lang_pair("ru", "en") == ("RU", "EN"), "коды нормализуются к верхнему регистру")
for bad in [("RU", "RU"), ("Русский", "EN"), ("RU", "XX"), ("", "EN")]:
    try:
        main._check_lang_pair(*bad)
        check(False, "пара %r отвергнута" % (bad,))
    except HTTPException as e:
        check(e.status_code == 400, "пара %r отвергнута — 400" % (bad,))
check("languages" in main.list_models(), "/api/models отдаёт каталог")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
