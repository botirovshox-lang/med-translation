"""Узбекская кириллица как язык перевода: RU→UZ-CYRL честно на всех шагах.

Узбекский пишется двумя письменностями, а код языка один («UZ»). Модель,
спрошенная про «UZ», решает сама — и чаще отвечает латиницей, потому что
её больше в корпусе. Балл back-check на таком переводе честный, termcheck
доволен, глоссарий доволен, письмо ОРИГИНАЛА не сохранилось — всё чисто,
а документ клиенту не годится целиком. Отсюда три вещи, которые здесь
сторожатся:

1. Каталог: «UZ-CYRL» — своя запись со своим письмом и АЛФАВИТОМ (35 букв,
   1956 год: ў қ ғ ҳ есть, щ и ы нет) и именем для модели (`prompt`).
2. Промпты: везде, где язык называется модели, вместо кода уходит имя
   с письмом; для остальных пар строка байт в байт прежняя (промпты
   версионированы, переименование «EN» → «English» перекупило бы вердикты).
3. Проверка: перевод не тем письмом и буквы вне алфавита — находка
   (`_alphabet_misses`), счётчик приёмки ремонта и вето ревизии; в состав
   прогона и корзины разбора доезжает списком (`_alphabet_ids`).
Плюс класс кириллицы: ў қ ғ ҳ — буквы, а не граница слова.
Платных вызовов нет.
"""
import json, os, re, sys, types, unicodedata
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")


class FakeClient:
    def __init__(self, **kw):
        raise AssertionError("сеть в этом тесте не нужна")


sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeClient)

import main
import checks
import textcount

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


UZC = "UZ-CYRL"
ALPHABET = "абвгдеёжзийклмнопрстуфхцчшъьэюяўқғҳ"


def project_of(segments, tgt=UZC):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": tgt, "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


print("=== 1. Каталог: запись, письмо, алфавит ===")
info = main._LANG_BY_CODE.get(UZC)
check(bool(info), "UZ-CYRL есть в каталоге")
check(info and info.get("script") == "CYRILLIC", "письмо — кириллица")
letters = (info or {}).get("letters") or ""
check(letters == ALPHABET, "алфавит — 35 букв узбекской кириллицы в порядке алфавита")
check(len(set(letters)) == 35 and len(letters) == 35, "35 букв и без повторов (%d)" % len(letters))
check(all(unicodedata.name(c).startswith("CYRILLIC") for c in letters),
      "каждая буква алфавита — кириллическая по Юникоду")
check(all(c in letters for c in "ўқғҳ"), "ў қ ғ ҳ — в алфавите")
check(not any(c in letters for c in "щы"), "щ и ы — вне алфавита (их в узбекской кириллице нет)")
check(letters == letters.lower(), "алфавит задан строчными")
uz = main._LANG_BY_CODE.get("UZ")
check(uz and uz.get("script") == "LATIN" and "латиница" in uz["ru"] and "кириллица" in info["ru"],
      "латинский и кириллический узбекский различимы по имени")
check(info.get("native", "").startswith("Ўзбекча"), "название на самом языке — кириллицей")
check(UZC in [l["code"] for l in main.list_models()["languages"]], "/api/models отдаёт UZ-CYRL")
check(main._check_lang_pair("ru", "uz-cyrl") == ("RU", UZC), "пара RU→UZ-CYRL принимается (регистр не важен)")
try:
    main._check_lang_pair("uz-cyrl", "uz-cyrl")
    check(False, "вырожденная пара отклоняется")
except Exception as e:
    check(getattr(e, "status_code", 0) == 400, "вырожденная пара отклоняется (400)")
check(main._src_lang({"lang": "RU→UZ-CYRL"}) == "RU", "язык оригинала записи глоссария читается из пары с тегом")
norm = textcount.norm_for(UZC)
check(norm["unit"] == "words" and norm["source"] == "table", "норма страницы: слова, строка в таблице есть")

print("=== 2. Промпты называют письмо ===")
check("Cyrillic" in main._lang_prompt(UZC) and "Latin" in main._lang_prompt(UZC),
      "имя для модели говорит про кириллицу и запрещает латиницу: %r" % main._lang_prompt(UZC))
check("Latin" in main._lang_prompt("UZ"), "у латинского узбекского имя тоже с письмом")
check(main._lang_prompt("EN") == "EN" and main._lang_prompt("ru") == "ru",
      "у остальных языков код уходит как есть, байт в байт")
mdl = main._resolve_model(None)
tr = main._translate_system("RU", UZC, [], None, False, "medical", mdl)
check("Uzbek (Cyrillic script" in tr and "UZ-CYRL" not in tr, "промпт перевода: язык назван письмом, тег в промпт не уходит")
check("Output must be 100% Uzbek (Cyrillic script" in tr, "требование «100% на языке перевода» — с письмом")
tr_en = main._translate_system("RU", "EN", [], None, False, "medical", mdl)
check("from RU to EN" in tr_en, "промпт RU→EN не изменился: код как раньше")
lit = main._translate_system(UZC, "RU", None, None, True, "medical", mdl)
check("from Uzbek (Cyrillic script" in lit, "обратный перевод знает, с какого письма переводит")
dom = main._resolve_domain("medical")
for name, txt in (
    ("termcheck", main._termcheck_system(dom, "RU", UZC)),
    ("repair", main._repair_system(dom, "RU", UZC)),
    ("review", main._review_system(dom, "RU", UZC)),
    ("termsheet", main._termsheet_system(dom, "RU", UZC)),
    ("edit-harvest", main._edit_terms_prompt("RU", UZC, dom)),
):
    check("Uzbek (Cyrillic script" in txt and "UZ-CYRL" not in txt, "промпт %s называет письмо" % name)
check("Uzbek (Cyrillic script" in main._judge_system(dom, UZC), "судья знает язык оригинала с письмом")
check("Uzbek (Cyrillic script" in main._image_read_system(dom, UZC), "чтение картинок знает язык с письмом")
check("(язык: RU)" in main._judge_system(dom, "RU"), "судья на RU — прежняя строка")

print("=== 3. Проверка письма и алфавита ===")
GOOD = "Ўпка сили — сурункали юқумли касаллик; беморда ҳарорат 38,5 °C, йўтал ва MDR-TB."
LATIN = "O‘pka sili — surunkali yuqumli kasallik; bemorda harorat 38,5 °C."
seg_ok = {"id": 1, "source": "Туберкулёз лёгких — хроническое инфекционное заболевание.", "target": GOOD, "status": "translated"}
seg_lat = {"id": 2, "source": "Туберкулёз лёгких — хроническое инфекционное заболевание.", "target": LATIN, "status": "translated"}
seg_ru = {"id": 3, "source": "Выявлены очаги в верхней доле.", "target": "Юқори бўлакда очаги аниқланды, щётка.", "status": "translated"}
seg_name = {"id": 4, "source": "Метод Щукина и проба Ыбраева.", "target": "Щукин усули ва Ыбраев синамаси.", "status": "translated"}
seg_num = {"id": 5, "source": "38,5 °C", "target": "38,5 °C", "status": "translated"}
seg_copy = {"id": 6, "source": "Выявлены очаги.", "target": "Выявлены очаги.", "status": "translated"}
proj = project_of([seg_ok, seg_lat, seg_ru, seg_name, seg_num, seg_copy])

check(main._alphabet_misses(seg_ok, proj) == [], "верная узбекская кириллица с ў қ ғ ҳ — чисто")
f = main._alphabet_misses(seg_lat, proj)
check(len(f) == 1 and f[0]["kind"] == "script" and "не тем письмом" in f[0]["text"]
      and "латиница" in f[0]["text"] and "кириллица" in f[0]["text"],
      "латиница вместо кириллицы — находка с обоими письмами по-русски: %s" % (f and f[0]["text"]))
f = main._alphabet_misses(seg_ru, proj)
check(len(f) == 1 and "вне алфавита" in f[0]["text"] and "«аниқланды»" in f[0]["text"]
      and "«щётка»" in f[0]["text"] and "очаги" not in f[0]["text"],
      "буквы ы/щ вне алфавита названы поимённо, слово без них — нет: %s" % (f and f[0]["text"]))
check(main._alphabet_misses(seg_name, proj) == [],
      "фамилия из оригинала со «щ»/«ы» — перенесена, а не переведена: не находка")
check(main._alphabet_misses(seg_num, proj) == [], "числа без букв — молчим")
check(main._alphabet_misses(seg_copy, proj) == [],
      "оригинал, скопированный как есть, — не про алфавит (то ловит совпадение с оригиналом)")
check(main._alphabet_misses(seg_lat, None) == [], "без проекта — пусто (язык перевода лежит на проекте)")
proj_en = project_of([seg_lat], tgt="EN")
check(main._alphabet_misses(seg_lat, proj_en) == [], "у языка без алфавита в каталоге проверка молчит (EN)")
proj_uzl = project_of([seg_ok], tgt="UZ")
check(main._alphabet_misses(seg_ok, proj_uzl) == [], "латинский узбекский без алфавита — молчит, а не кричит на кириллицу")
proj = project_of([seg_ok, seg_lat, seg_ru, seg_name, seg_num, seg_copy])
check(main._script_misses(seg_ok) == [] and main._script_misses(seg_ru) == [],
      "буквы письма оригинала: кириллица общая — молчим (это не выдуманная претензия)")
check(main._translit_misses(seg_ok, proj) == [], "транслитерация сокращений: правило измерено только на EN — молчит")
check(checks.negation_markers(UZC) == [], "маркеров отрицания для узбекского нет: отрицание в нём суффиксом, список слов врал бы")
check(main._termcheck_trivial("Здоровье", "Соғлиқ") is None, "«Соғлиқ» — слово, проверять есть что")
check(main._termcheck_trivial("Выявлены очаги.", "Выявлены очаги.") is not None,
      "перевод, совпавший с оригиналом, — «переводить нечего»")

print("=== 4. Находка доезжает до ремонта, состава и разбора ===")
kinds = [x["kind"] for x in main._repair_findings(seg_lat, proj)]
check("script" in kinds, "с проектом — находка ремонта kind=script")
check("script" not in [x["kind"] for x in main._repair_findings(seg_lat, None)],
      "без проекта находки нет — за неё отвечает список id")
ids = main._alphabet_ids(proj)
check(ids == {2, 3}, "список id: латиница и русские буквы, остальные чисты: %s" % sorted(ids))
check(main._alphabet_ids(proj_en) == set() and main._alphabet_ids(None) == set(), "без алфавита список пуст")
sc = main._repair_scores(seg_lat, proj)
check(sc.get("alphabet") == 1 and main._repair_scores(seg_ok, proj).get("alphabet") == 0,
      "счётчик приёмки ремонта «alphabet» считается")
check("alphabet" in main.REVIEW_FREE_KEYS and "alphabet" in main.REVIEW_VETO_LABELS,
      "ревизия: бесплатная сверка и подпись вето")
src_main = open("backend/main.py", encoding="utf-8").read()
plan_body = src_main[src_main.index("def run_plan("):]
plan_body = plan_body[:plan_body.index("\ndef ", 10)]
check("_alphabet_ids(project)" in plan_body, "состав прогона берёт список id (иначе смета обещала бы меньше, чем сделает прогон)")
an_body = src_main[src_main.index("def project_analysis("):]
an_body = an_body[:an_body.index("\ndef ", 10)]
check("_alphabet_ids(project)" in an_body and "machine_set.update(_alpha_ids - _alpha_clamped)" in an_body
      and "_repair_clamped(_by_id[i]" in an_body,
      "разбор кладёт такие сегменты машине, а с совпавшим отпечатком захода и заверённые — человеку")
cov = main._coverage(proj)
check(any(w["key"] == "alphabet" for w in cov["works"]), "покрытие: письмо и алфавит — работает на RU→UZ-CYRL")
cov_en = main._coverage(proj_en)
check(not any(w["key"] == "alphabet" for w in cov_en["works"] + cov_en["silent"]),
      "покрытие: у языка с одним письмом строки нет — чужое письмо там ловит «script»")
check(any(w["key"] == "negation" for w in cov["works"]), "инверсия отрицания — по маркерам ОРИГИНАЛА (RU), работает")

print("=== 5. Класс кириллицы знает ў қ ғ ҳ ===")
check(all(c in main._LETTERS for c in "ўқғҳЎҚҒҲ"), "граница слова считает узбекские буквы буквами")
check("соғл" in main._text_keys("Соғлиқ сақлаш") and "со" in main._text_keys("Соғлиқ"),
      "ключи индекса глоссария режутся по целому слову, а не на «ғ»")
check(main._word_script("соғлиқ") == "cyr", "письмо слова с ғ и қ — кириллица")
check(main._word_script("туберкулёз") == "cyr" and main._word_script("tuberculosis") == "lat",
      "русское и английское слово — как прежде")
check(main._WORDS_RE.search("ҳақ") is not None and main._WORDS_RE.search("38 °C") is None,
      "«ҳақ» — слово, «38 °C» — нет")
check(main._dominant_script("Ўзбекча (кирилл)") == "CYRILLIC", "письменность текста с Ў — кириллица")

print("=== 6. Словари интерфейса знают новые строки сервера ===")
for lang in ("uz", "en"):
    d = json.load(open("frontend/i18n/%s.server.json" % lang, encoding="utf-8"))
    for k in ("перевод набран не тем письмом: ожидается ", ", а большинство слов — ", "кириллица", "латиница",
              "буквы вне алфавита языка перевода: ", "апостроф внутри слова, в этом письме так не пишут: ",
              "в переводе нет ни одной из букв ", " — похоже, набрано буквами соседнего языка",
              "в слове смешаны письменности: ",
              "букв вне письма языка перевода больше", "букв вне письма языка перевода стало больше "):
        check(k in d and k in src_main, "%s: «%s» переведено и есть в коде" % (lang, k.strip()))

print("=== 7. Письмо решается ПО СЛОВАМ, а не по буквам ===")
proj = project_of([seg_ok, seg_lat, seg_ru, seg_name, seg_num, seg_copy])
seg_mix = {"id": 7, "source": "Схема лечения МЛУ-ТБ и COVID-19, IFN-γ.",
           "target": "MDR-TB ва COVID-19 даволаш схемаси, IFN-γ, Mycobacterium tuberculosis.", "status": "translated"}
check(main._alphabet_misses(seg_mix, proj) == [],
      "аббревиатуры капсом, слова с цифрами и дефисом и латинское название вида письмо перевода не выдают")
seg_two = {"id": 8, "source": "Пчелиный яд.", "target": "Asalari zahari.", "status": "translated"}
f = main._alphabet_misses(seg_two, proj)
check(len(f) == 1 and "не тем письмом" in f[0]["text"], "два латинских слова из двух — уже не тем письмом")
seg_one = {"id": 9, "source": "Пчелиный яд.", "target": "Асалари zahari.", "status": "translated"}
check(main._alphabet_misses(seg_one, proj) == [], "одно латинское слово при одном кириллическом — ничья, молчим")
seg_suffix = {"id": 10, "source": "Метод Щукина.", "target": "Щукиннинг усули.", "status": "translated"}
check(main._alphabet_misses(seg_suffix, proj) == [], "фамилия с узбекским суффиксом — перенесена (общее начало), не находка")

print("=== 8. Правила языка из lang_rules.json ===")
r = main._lang_rule(UZC)
check(bool(r.get("conventions")) and r.get("apostrophe_in_word") is False and r.get("distinctive") == "ўқғҳ",
      "у узбекской кириллицы есть правила: орфография, апостроф, отличительные буквы")
check(main._lang_rule("EN") == {} and main._lang_conventions("EN") == "", "у английского правил нет — блока нет, промпт прежний")
conv = main._lang_conventions(UZC)
check(conv.startswith("TARGET LANGUAGE CONVENTIONS (Uzbek Cyrillic)") and "ъ" in conv and "ў, қ, ғ, ҳ" in conv,
      "блок правил называет письмо, ъ и ў қ ғ ҳ")
tr = main._translate_system("RU", UZC, [], None, False, "medical", mdl)
check("TARGET LANGUAGE CONVENTIONS (Uzbek Cyrillic)" in tr, "промпт перевода несёт правила языка")
check("TARGET LANGUAGE CONVENTIONS" not in main._translate_system(UZC, "RU", None, None, True, "medical", mdl),
      "в обратный перевод правила не идут")
check("TARGET LANGUAGE CONVENTIONS" not in main._translate_system("RU", "EN", [], None, False, "medical", mdl),
      "RU→EN: блока нет, промпт байт в байт прежний")
check("TARGET LANGUAGE CONVENTIONS (Uzbek Cyrillic)" in main._repair_system(dom, "RU", UZC)
      and "TARGET LANGUAGE CONVENTIONS (Uzbek Cyrillic)" in main._review_system(dom, "RU", UZC),
      "ремонт и ревизия несут те же правила")
check("TARGET LANGUAGE CONVENTIONS (Uzbek Latin)" in main._translate_system("RU", "UZ", [], None, False, "medical", mdl)
      and "U+02BB" in main._lang_conventions("UZ"), "латинский узбекский: правила про ʻ и ʼ")
seg_apos = {"id": 11, "source": "Значение и влияние.", "target": "Ma’no ва таʼсир катта.", "status": "translated"}
f = main._alphabet_misses(seg_apos, proj)
check(any("апостроф внутри слова" in x["text"] and "«таʼсир»" in x["text"] for x in f),
      "апостроф внутри кириллического слова — находка: %s" % [x["text"] for x in f])
RUSSIFIED = ("Асал ари махсулоти инсон учун жуда фойдали ва у куп касалликларни даволашда "
             "ишлатилади хамда узок вакт сакланади бу хакда куп маълумот бор")
seg_rus = {"id": 12, "source": "Мёд полезен.", "target": RUSSIFIED, "status": "translated"}
f = main._alphabet_misses(seg_rus, proj)
check(any("нет ни одной из букв ў қ ғ ҳ" in x["text"] for x in f),
      "длинный текст без ў қ ғ ҳ — набрано русской раскладкой: %s" % [x["text"] for x in f])
check(main._alphabet_misses({"id": 13, "source": "Мёд.", "target": "Асал жуда фойдали.", "status": "translated"}, proj) == [],
      "короткая фраза без ў қ ғ ҳ законна — порог по числу слов")
seg_homo = {"id": 14, "source": "Пациент.", "target": "Бемор пaциент ҳолати.", "status": "translated"}
f = main._alphabet_misses(seg_homo, proj)
check(any("смешаны письменности" in x["text"] and "«пaциент»" in x["text"] for x in f),
      "латинская «a» внутри кириллического слова — омоглиф, находка")
check(main._alphabet_misses({"id": 15, "source": "Т-клетки.", "target": "T-ҳужайралар кўп.", "status": "translated"}, proj) == [],
      "«T-ҳужайралар» через дефис — не смешение")
cov = main._coverage(proj)
check(any(w["key"] == "conventions" for w in cov["works"]), "покрытие называет правила языка в промптах")

print("=== 9. Замечания критика закрыты в коде ===")
free_line = [l for l in src_main.splitlines() if "_free = lambda d:" in l]
free_block = src_main[src_main.index("_free = lambda d:"):src_main.index("_free = lambda d:") + 200]
check('d.get("alphabet", 0)' in free_block, "приёмка ремонта: алфавит в сумме бесплатных находок (заход только по письму принимается)")
check("_repair_score_vetoed(seg, project)" in src_main and "_segment_for_client(s, project)" in src_main,
      "кандидат наследства сверяется по паре языков ПРОЕКТА, а не RU→EN")
_var = src_main[src_main.index("The user does NOT speak {tgt_lang}") - 400:src_main.index("The user does NOT speak {tgt_lang}")]
check("_lang_prompt(src_lang), _lang_prompt(tgt_lang)" in _var, "разбор вариантов очереди называет язык именем")
check("% _lang_prompt(src_lang))" in src_main, "чтение страницы скана называет язык именем")

print("=== 10. Обращение: титул после имени, с титулом — siz ===")
uzl = main._lang_conventions("UZ")
check("Yusuf aka" in uzl and "not aka Yusuf" in uzl and "never sen" in uzl,
      "UZ: «Yusuf aka», не «aka Yusuf»; с aka — только siz")
check("Юсуф ака" in main._lang_conventions(UZC) and "never сен" in main._lang_conventions(UZC),
      "UZ-CYRL: то же кириллицей")
check("never add a formula the source does not have" in uzl,
      "формула (s.a.v.) — только если она есть в оригинале (правило 9: не добавлять)")
check("TARGET LANGUAGE CONVENTIONS (Russian)" in main._lang_conventions("RU"), "у русского правила обращения есть")
check(not main._alphabet_active({"tgt": "RU"}) and not main._alphabet_active({"tgt": "AR"}),
      "одни правила промпта проверку письма НЕ включают (RU, AR)")
check(main._alphabet_active({"tgt": "UZ"}) and main._alphabet_active({"tgt": UZC})
      and main._alphabet_active({"tgt": "KK"}), "UZ (script_check), UZ-CYRL, KK — проверка письма как была")
for code, r in main._LANG_RULES.items():
    for line in r.get("conventions") or []:
        check("decimal comma" not in line.lower(),
              "%s: правило не меняет разделитель дробей — checks._extract_numbers сравнивает числа строками" % code)

print()
if fail:
    print("FAILED: %d" % len(fail))
    for x in fail:
        print(" -", x)
    sys.exit(1)
print("ALL OK")
