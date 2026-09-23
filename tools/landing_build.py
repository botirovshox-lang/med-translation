# -*- coding: utf-8 -*-
"""Сборка лендинга click.simpletranslate.me из landing/src/ в landing/.

Зачем сборщик, а не один файл руками:
  * FAQ-разметка (FAQPage) выводится ИЗ ВИДИМЫХ вопросов и ответов тела
    страницы. Разметка, написанная отдельно, разошлась бы с текстом первой
    же правкой, а разметка невидимого текста — нарушение правил Google;
  * дата обновления — одна константа (UPDATED): она уходит и в видимый
    футер («Последнее обновление»), и в dateModified схемы, и в lastmod
    sitemap. Три места руками — три разные даты;
  * цены тарифов — одна таблица (TIERS): страница, JSON-LD Offer,
    pricing.md и llms.txt читают её одну. Цена в трёх файлах врозь —
    это агент, который называет клиенту не ту цену.

Запуск: python tools/landing_build.py   (пишет landing/index.html, sitemap.xml,
llms.txt, pricing.md). Сторожит tests/test_landing.py: собранное в репозитории
обязано совпадать со свежей сборкой.
"""
import json
import re
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "landing" / "src"
OUT = ROOT / "landing"

# ─── Языки страницы ──────────────────────────────────────────────────
# Русский — ЯЗЫК КЛЮЧЕЙ: словаря у него нет, его текст и есть body.html.
# Тот же закон, что у словаря приложения (frontend/i18n): ключ — сама
# русская строка, поэтому на русском сборка ничего не подменяет побитово,
# а забытый перевод виден сразу — он роняет сборку, а не показывает
# русскую строку среди узбекских.
#
# Языки ВЫВОДЯТСЯ из имён файлов в landing/src/i18n (en.json → en), а не
# пишутся списком: список пришлось бы править в сборщике, в sitemap и
# в тесте, и первый же забытый язык собирался бы наполовину русским.
KEY_LANG = "ru"
LANG_NAMES = {"ru": "Русский", "uz": "O‘zbekcha", "en": "English"}
# Адрес языка: русский лежит в корне (на него ведут все старые ссылки),
# остальные — в своей папке. Менять корень нельзя: это canonical.
LANG_DIRS = {"ru": "", "uz": "uz/", "en": "en/"}

SITE = "https://click.simpletranslate.me"
APP = "https://simpletranslate.me"
BRAND = "SimpleTranslate"
UPDATED = "2026-09-17"            # ISO; меняется вместе с правкой текста
PUBLISHED = "2026-09-17"
EMAIL = "hello@simpletranslate.me"

MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря"]

# Тарифы — источник правды для страницы, схемы, pricing.md и llms.txt.
TIERS = [
    {"name": "Старт", "price": "0.5", "for": "Разовые документы: статья, справка, договор",
     "includes": ["Перевод и полный набор автопроверок (обратный перевод, числа и единицы, глоссарий)",
                  "Выгрузка в исходном формате 1 в 1", "Оплата только за объём, без подписки",
                  "Один пользователь"]},
    {"name": "Профи", "price": "0.9", "for": "Авторы, кафедры, бюро переводов", "recommended": True,
     "includes": ["Всё из «Старта»", "Ревизия второй моделью: читает пару целиком",
                  "Свой глоссарий и память переводов", "Команда до 5 человек с ролями",
                  "Приоритетная очередь"]},
    {"name": "Издательство", "price": None, "for": "Книги, серии, учебники, регулярные объёмы",
     "includes": ["Всё из «Профи»", "Отдельные словари на каждый проект",
                  "Чтение и перевод текста на картинках и сканах",
                  "Счёт на организацию, закрывающие документы", "Персональный менеджер"]},
]

# ─── Мета страницы по языкам ─────────────────────────────────────────
# Title и description НЕ переводятся автоматически из тела: у них жёсткие
# пределы длины (30–60 и 120–160 знаков), а перевод их не соблюдает —
# узбекская фраза длиннее русской на четверть. Поэтому они написаны
# на каждом языке отдельно и сторожатся тестом по длине.
META = {
    "ru": {
        "title": "Перевод документов одним кликом — SimpleTranslate",
        "desc": "Загрузите Word, PDF или Excel и получите перевод уровня научной публикации "
                "в том же оформлении. Обратный перевод, сверка чисел, глоссарий. От $0.5 за страницу.",
        "locale": "ru_RU",
        "ogTitle": "Перевод документов одним кликом — SimpleTranslate",
        "ogDesc": "Перевод уровня научной публикации в том же оформлении: обратный перевод, "
                  "сверка чисел и глоссарий. От $0.5 за страницу.",
        "ogAlt": "SimpleTranslate: одним кликом — перевод уровня научной публикации, "
                 "от $0.5 за страницу",
        "ldDesc": "Перевод документов языковой моделью с проверкой каждой строки: обратный перевод, "
                  "сверка чисел и единиц, глоссарий. Word, PDF, Excel, PowerPoint и сканы "
                  "возвращаются в исходном оформлении. От $0.5 за страницу в 250 слов.",
        "orgDesc": "Сервис перевода документов с автоматическими проверками: обратный перевод, "
                   "сверка чисел и единиц, глоссарий. Файл возвращается в исходном оформлении.",
        "unit": "страница (250 слов исходника)",
    },
    "uz": {
        "title": "Hujjat tarjimasi bir bosishda — SimpleTranslate",
        "desc": "Word, PDF yoki Excel yuklang va ilmiy nashr darajasidagi tarjimani "
                "o‘sha ko‘rinishda oling. Teskari tarjima, sonlarni solishtirish, lug‘at. Bet $0.5 dan.",
        "locale": "uz_UZ",
        "ogTitle": "Hujjat tarjimasi bir bosishda — SimpleTranslate",
        "ogDesc": "Ilmiy nashr darajasidagi tarjima o‘sha ko‘rinishda: teskari tarjima, "
                  "sonlarni solishtirish va lug‘at. Bet uchun $0.5 dan.",
        "ogAlt": "SimpleTranslate: bir bosishda — ilmiy nashr darajasidagi tarjima, "
                 "bet uchun $0.5 dan",
        "ldDesc": "Hujjatlarni til modeli bilan tarjima qilish va har bir satrni tekshirish: "
                  "teskari tarjima, son va birliklarni solishtirish, lug‘at. Word, PDF, Excel, "
                  "PowerPoint va skanlar asl ko‘rinishida qaytariladi. 250 so‘zlik bet $0.5 dan.",
        "orgDesc": "Avtomatik tekshiruvli hujjat tarjimasi xizmati: teskari tarjima, son va "
                   "birliklarni solishtirish, lug‘at. Fayl asl ko‘rinishida qaytariladi.",
        "unit": "bet (asl matnning 250 so‘zi)",
    },
    "en": {
        "title": "One-click document translation — SimpleTranslate",
        "desc": "Upload a Word, PDF or Excel file and get a translation fit for a journal, "
                "in the same layout. Back-translation, number checks, glossary. From $0.5 a page.",
        "locale": "en_US",
        "ogTitle": "One-click document translation — SimpleTranslate",
        "ogDesc": "A translation fit for a scientific journal, in the same layout: back-translation, "
                  "number checks and a glossary. From $0.5 per page.",
        "ogAlt": "SimpleTranslate: one click — a translation fit for a scientific journal, "
                 "from $0.5 per page",
        "ldDesc": "Document translation by a language model with every line checked: back-translation, "
                  "comparison of numbers and units, a glossary. Word, PDF, Excel, PowerPoint and scans "
                  "come back in their original layout. From $0.5 per 250-word page.",
        "orgDesc": "A document translation service with automatic checks: back-translation, "
                   "comparison of numbers and units, a glossary. The file comes back in its original layout.",
        "unit": "page (250 words of the source)",
    },
}


FEATURES = [
    "Перевод Word, PDF, Excel, PowerPoint, HTML, текстовых файлов, картинок и сканов",
    "Возврат файла в исходном оформлении: стили, таблицы, рисунки, оглавление",
    "Обратный перевод каждой строки другой моделью и сравнение с оригиналом",
    "Детерминированная сверка чисел, единиц, диапазонов и отрицаний",
    "Глоссарий и память переводов: единый термин по всему документу",
    "Ревизия второй моделью",
    "Смета по страницам (250 слов) до загрузки файла",
    "Команды с ролями: владелец, редактор, переводчик",
]


def _date_ru(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {MONTHS_RU[m - 1]} {y}"


MONTHS = {
    "ru": MONTHS_RU,
    "uz": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul",
           "avgust", "sentabr", "oktabr", "noyabr", "dekabr"],
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
}


def _date_of(iso, lang):
    y, m, d = (int(x) for x in iso.split("-"))
    name = MONTHS.get(lang, MONTHS_RU)[m - 1]
    return f"{name} {d}, {y}" if lang == "en" else f"{d} {name} {y}"


def langs():
    """Языки страницы, выведенные из имён файлов словаря. Русский первым:
    он язык ключей и лежит в корне."""
    found = sorted(p.stem for p in (SRC / "i18n").glob("*.json"))
    return [KEY_LANG] + [c for c in found if c != KEY_LANG]


def dictionary(lang):
    """Словарь языка. У языка ключей его нет и быть не должно: его текст
    и есть body.html."""
    if lang == KEY_LANG:
        return {}
    data = json.loads((SRC / "i18n" / (lang + ".json")).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k != "_"}


# Строки, которые ПЕРЕВОДИТЬ НЕЛЬЗЯ: они работают данными, а не надписью.
# Тот же закон, что у `tools/i18n_wrap.py` в приложении: переведённый
# операнд сравнения молча ломает то, у чего нет ни одного видимого
# признака поломки.
NO_TRANSLATE = re.compile(r"^(?:[\s\d.,:%$—–-]+|[A-Za-z0-9_.&;+-]+)$")


def _tr(text, table, lang, missing):
    """Перевод одного видимого куска. Пустое значение в словаре означает
    «оставить как есть» (имя файла, формула); отсутствие ключа — забытый
    перевод, и о нём сборка кричит."""
    key = text.strip()
    if not key or lang == KEY_LANG:
        return text
    if not re.search("[А-Яа-яЁё]", key) or NO_TRANSLATE.match(key):
        return text
    if key not in table:
        missing.add(key)
        return text
    val = table[key]
    if not val:                     # «переводить не надо» — решение автора словаря
        return text
    # Пробелы по краям сохраняются: куски склеиваются с числами и тегами,
    # и съеденный пробел слепляет слова («Стоимость страницы —от $0.5»).
    lead = text[:len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()):]
    return lead + val + tail


def translate_body(body, lang):
    """Перевод ВИДИМОГО текста тела и атрибутов `__T:…__`.

    Разбор регуляркой, а не разбором HTML: тело своё, оно в репозитории
    и меняется вместе с этим файлом, а зависимость сборки лендинга
    от чужого парсера здесь ничего не окупает. Скрипт и его содержимое
    НЕ трогаются вовсе (там код), кроме списка LENS_PAIRS, который
    подставляется отдельно.
    """
    table, missing = dictionary(lang), set()

    # 1. Атрибуты и прочее, размеченное явно.
    body = re.sub(r"__T:(.+?)__",
                  lambda m: _tr(m.group(1), table, lang, missing), body)

    # 2. Видимый текст между тегами. Куски внутри <script> не трогаем:
    #    перевод строки кода — это сломанный скрипт.
    out, in_script = [], False
    for part in re.split(r"(<[^>]+>)", body):
        if part.startswith("<"):
            tag = part.lower()
            if tag.startswith("<script"):
                in_script = True
            elif tag.startswith("</script"):
                in_script = False
            out.append(part)
        else:
            out.append(part if in_script else _tr(part, table, lang, missing))
    body = "".join(out)

    if missing:
        raise SystemExit("нет перевода на «%s» для %d строк:\n  %s"
                         % (lang, len(missing),
                            "\n  ".join(sorted(missing)[:10])))
    return body


def _text(html):
    """Видимый текст из куска HTML: теги долой, сущности раскрыть, пробелы сжать."""
    t = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def faq_items(body):
    """Пары «вопрос — ответ» из видимого раздела FAQ."""
    sec = re.search(r'<section id="faq".*?</section>', body, re.S)
    if not sec:
        raise SystemExit("FAQ section not found")
    items = re.findall(r"<article class=\"faq\">\s*<h3>(.*?)</h3>\s*<p>(.*?)</p>", sec.group(0), re.S)
    if len(items) < 5:
        raise SystemExit("FAQ has fewer than 5 questions")
    return [(_text(q), _text(a)) for q, a in items]


def page_title(lang=KEY_LANG):
    """Заголовок берётся из META, а не из шаблона: в шаблоне теперь
    плейсхолдер, один на все языки."""
    return META[lang]["title"]


def page_description(lang=KEY_LANG):
    return META[lang]["desc"]


def jsonld(template, body, lang=KEY_LANG):
    m = META[lang]
    org_id = APP + "/#organization"
    app_id = APP + "/#software"
    site_id = SITE + "/#website"
    page_id = SITE + "/" + LANG_DIRS[lang] + "#webpage"
    offers = []
    for t in TIERS:
        if t["price"] is None:
            continue
        offers.append({
            "@type": "Offer", "name": t["name"], "url": SITE + "/#pricing",
            "price": t["price"], "priceCurrency": "USD", "availability": "https://schema.org/InStock",
            "description": t["for"],
            "priceSpecification": {"@type": "UnitPriceSpecification", "price": t["price"],
                                   "priceCurrency": "USD", "unitText": m["unit"]},
        })
    graph = [
        {
            "@type": "Organization", "@id": org_id, "name": BRAND, "url": APP,
            "logo": {"@type": "ImageObject", "url": SITE + "/logo.png", "width": 512, "height": 512},
            "description": m["orgDesc"],
            "areaServed": {"@type": "Country", "name": "Uzbekistan"},
            "knowsAbout": ["Перевод документов", "Перевод научных статей и учебников",
                           "Медицинский перевод", "Контроль качества перевода",
                           "Терминологические глоссарии и память переводов"],
            "contactPoint": {"@type": "ContactPoint", "contactType": "customer service",
                             "email": EMAIL, "availableLanguage": ["ru", "uz", "en"]},
        },
        {
            "@type": "WebSite", "@id": site_id, "url": SITE + "/", "name": BRAND,
            "inLanguage": lang, "publisher": {"@id": org_id},
        },
        {
            "@type": "WebPage", "@id": page_id, "url": SITE + "/" + LANG_DIRS[lang],
            "name": page_title(lang),
            "description": page_description(lang), "inLanguage": lang,
            "isPartOf": {"@id": site_id}, "about": {"@id": app_id},
            "datePublished": PUBLISHED, "dateModified": UPDATED,
            "primaryImageOfPage": {"@type": "ImageObject", "url": SITE + "/og.png", "width": 1200, "height": 630},
            "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".hero-answer", ".key-answer"]},
        },
        {
            "@type": "SoftwareApplication", "@id": app_id, "name": BRAND, "url": APP,
            "description": m["ldDesc"],
            "applicationCategory": "BusinessApplication", "operatingSystem": "Web browser",
            "inLanguage": ["ru", "uz", "en"], "featureList": FEATURES,
            "screenshot": SITE + "/og.png", "provider": {"@id": org_id}, "offers": offers,
        },
        {
            "@type": "FAQPage", "@id": SITE + "/" + LANG_DIRS[lang] + "#faq",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq_items(body)],
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=1)


# ─── Линза: пары языков в примере ────────────────────────────────────
# Один и тот же абзац на четырёх парах. Цифры ВО ВСЕХ парах одни и те же
# намеренно: подпись под линзой обещает «120, 18–65 и 300 мг/сут сверены
# с оригиналом», и пара без этих чисел была бы враньём ровно в том,
# что мы продаём.
#
# `code` — метка на кольце (её рисует CSS из data-code), `srcLang`/`tgtLang`
# уходят в атрибут lang куска документа: читалка обязана произнести
# узбекский абзац по-узбекски, а не по буквам языка страницы.
LENS_SRC_RU = [
    "Аннотация",
    "Цель исследования — оценить эффективность комбинированной терапии "
    "у пациентов с впервые выявленным заболеванием.",
    "В исследование включены 120 пациентов в возрасте 18–65 лет. "
    "Доза препарата составила 300 мг/сут.",
    "Различия между группами статистически значимы (p < 0,05).",
]
LENS_SRC_EN = [
    "Abstract",
    "The aim of the study was to evaluate the efficacy of combination therapy "
    "in patients with newly diagnosed disease.",
    "The study enrolled 120 patients aged 18–65 years. "
    "The drug dose was 300 mg/day.",
    "The differences between the groups were statistically significant (p < 0.05).",
]
LENS_PAIRS = [
    {"code": "EN", "label": "RU → EN", "srcLang": "ru", "tgtLang": "en",
     "src": LENS_SRC_RU, "tgt": LENS_SRC_EN},
    {"code": "UZ", "label": "RU → UZ", "srcLang": "ru", "tgtLang": "uz",
     "src": LENS_SRC_RU, "tgt": [
         "Annotatsiya",
         "Tadqiqot maqsadi — yangi aniqlangan kasallikka chalingan bemorlarda "
         "kombinatsiyalangan terapiya samaradorligini baholash.",
         "Tadqiqotga 18–65 yoshdagi 120 nafar bemor kiritildi. "
         "Dori dozasi 300 mg/kun ni tashkil etdi.",
         "Guruhlar orasidagi farqlar statistik jihatdan ahamiyatli (p < 0,05).",
     ]},
    # Узбекская КИРИЛЛИЦА — отдельная пара, а не та же «UZ»: это другой
    # алфавит, другой промпт и другая проверка (см. правило про UZ-CYRL
    # в CLAUDE.md). Показать их одной кнопкой значило бы пообещать выбор,
    # которого у человека нет.
    {"code": "UZ", "label": "RU → UZ (кирилл.)", "srcLang": "ru", "tgtLang": "uz-Cyrl",
     "src": LENS_SRC_RU, "tgt": [
         "Аннотация",
         "Тадқиқот мақсади — янги аниқланган касалликка чалинган беморларда "
         "комбинациялашган терапия самарадорлигини баҳолаш.",
         "Тадқиқотга 18–65 ёшдаги 120 нафар бемор киритилди. "
         "Дори дозаси 300 мг/кун ни ташкил этди.",
         "Гуруҳлар орасидаги фарқлар статистик жиҳатдан аҳамиятли (p < 0,05).",
     ]},
    {"code": "RU", "label": "EN → RU", "srcLang": "en", "tgtLang": "ru",
     "src": LENS_SRC_EN, "tgt": LENS_SRC_RU},
]
# Подпись пары («кирилл.») — единственное, что в ней переводится: коды
# языков языком страницы не меняются, это данные, а не надпись.
LENS_LABEL_TR = {"uz": {"RU → UZ (кирилл.)": "RU → UZ (kirill)"},
                 "en": {"RU → UZ (кирилл.)": "RU → UZ (Cyrillic)"}}


def lens_script(lang):
    pairs = []
    for pr in LENS_PAIRS:
        p = dict(pr)
        p["label"] = LENS_LABEL_TR.get(lang, {}).get(p["label"], p["label"])
        pairs.append(p)
    return ("<script>window.LENS_PAIRS=%s;</script>"
            % json.dumps(pairs, ensure_ascii=False, separators=(",", ":")))


def hreflang_links(lang):
    """Связка переводов. x-default ведёт на русскую: на неё ведут все
    прежние ссылки, и она же лежит в корне."""
    out = []
    for code in langs():
        out.append('<link rel="alternate" hreflang="%s" href="%s/%s">'
                   % (code, SITE, LANG_DIRS[code]))
    out.append('<link rel="alternate" hreflang="x-default" href="%s/">' % SITE)
    return "\n".join(out)


def lang_switch(lang):
    """Переключатель языка в шапке. Название языка — НА НЁМ САМОМ
    («O‘zbekcha», а не «Узбекский»): страницу на чужом языке ищет тот,
    кто нынешних надписей НЕ ЧИТАЕТ, — тот же закон, что у выбора языка
    на экране входа в приложение. И флагов тут нет по той же причине:
    флаг — это страна, а не язык."""
    out = ['<div class="lang-pick" role="group" aria-label="Til · Язык · Language">']
    for code in langs():
        here = ' aria-current="page"' if code == lang else ""
        out.append('<a href="%s/%s" hreflang="%s" lang="%s"%s>%s</a>'
                   % (SITE, LANG_DIRS[code], code, code, here, LANG_NAMES[code]))
    out.append("</div>")
    return "".join(out)


def build_index(lang=KEY_LANG):
    template = (SRC / "template.html").read_text(encoding="utf-8")
    css = (SRC / "styles.css").read_text(encoding="utf-8").rstrip("\n")
    body = (SRC / "body.html").read_text(encoding="utf-8").rstrip("\n")
    body = translate_body(body, lang)
    body = (body.replace("__DATE_ISO__", UPDATED)
                .replace("__DATE_RU__", _date_of(UPDATED, lang))
                .replace("__LANGS__", lang_switch(lang)))
    # Пары линзы уходят ПЕРЕД телом: скрипт тела читает window.LENS_PAIRS
    # при выполнении, а выполняется он в конце страницы.
    body = lens_script(lang) + "\n" + body
    meta = META[lang]
    html = (template.replace("__JSONLD__", jsonld(template, body, lang))
            .replace("__CSS__", css).replace("__BODY__", body)
            .replace("__LANG__", lang)
            .replace("__TITLE__", meta["title"])
            .replace("__DESC__", meta["desc"])
            .replace("__OGLOCALE__", meta["locale"])
            .replace("__OGTITLE__", meta["ogTitle"])
            .replace("__OGDESC__", meta["ogDesc"])
            .replace("__OGALT__", meta["ogAlt"])
            .replace("__CANON__", SITE + "/" + LANG_DIRS[lang])
            .replace("__HREFLANG__", hreflang_links(lang)))
    return html


def build_sitemap():
    """Карта сайта: страница на КАЖДОМ языке плюс pricing.md.

    У каждой записи свои `xhtml:link` на переводы — та же связка, что
    в hreflang самой страницы. Одна запись на три языка сказала бы
    поисковику, что переводов нет вовсе."""
    alts = "".join(
        '<xhtml:link rel="alternate" hreflang="%s" href="%s/%s"/>' % (c, SITE, LANG_DIRS[c])
        for c in langs())
    alts += '<xhtml:link rel="alternate" hreflang="x-default" href="%s/"/>' % SITE
    urls = []
    for code in langs():
        urls.append("  <url><loc>%s/%s</loc>%s<lastmod>%s</lastmod>"
                    "<changefreq>monthly</changefreq><priority>%s</priority></url>\n"
                    % (SITE, LANG_DIRS[code], alts, UPDATED,
                       "1.0" if code == KEY_LANG else "0.9"))
    urls.append("  <url><loc>%s/pricing.md</loc><lastmod>%s</lastmod>"
                "<changefreq>monthly</changefreq><priority>0.6</priority></url>\n"
                % (SITE, UPDATED))
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\" "
            "xmlns:xhtml=\"http://www.w3.org/1999/xhtml\">\n"
            + "".join(urls) + "</urlset>\n")


def build_pricing_md():
    lines = [f"# {BRAND}: тарифы", "",
             f"Обновлено: {UPDATED}. Валюта: доллар США. Единица: страница = 250 слов исходника "
             "(для письма без пробелов — китайский, японский — считаются знаки). Смета считается по файлу до "
             "загрузки и фиксируется. Подписки нет: оплата за объём. Повторная загрузка того же файла на ту же "
             "пару языков не списывается.", ""]
    for t in TIERS:
        price = f"${t['price']} за страницу" if t["price"] else "цена по договорённости"
        rec = " (рекомендуемый)" if t.get("recommended") else ""
        lines += [f"## {t['name']}{rec}", "", f"- Цена: {price}", f"- Для кого: {t['for']}", "- Включено:"]
        lines += [f"  - {x}" for x in t["includes"]]
        lines.append("")
    lines += ["## Примеры", "",
              "- Статья на 20 страниц по тарифу «Старт»: $10",
              "- Диссертация на 150 страниц по тарифу «Старт»: $75",
              "- Книга на 300 страниц по тарифу «Старт»: $150", "",
              f"Сервис: {APP} · Лендинг: {SITE}/ · Контакт: {EMAIL}", ""]
    return "\n".join(lines)


def build_llms():
    starter = next(t for t in TIERS if t["price"])
    lines = [
        f"# {BRAND}", "",
        f"> Сервис перевода документов (Word, PDF, Excel, PowerPoint, сканы) языковой моделью с проверкой каждой строки; файл возвращается в исходном оформлении, от ${starter['price']} за страницу.", "",
        "## Products", "",
        f"- [{BRAND}, лендинг]({SITE}/): что делает сервис, как проходит перевод, почему это не машинный перевод, тарифы, вопросы и ответы, контакты.",
        f"- [Тарифы]({SITE}/pricing.md): три тарифа со включёнными возможностями, цена за страницу в долларах, примеры расчёта на 20, 150 и 300 страниц.",
        f"- [Приложение]({APP}): вход и регистрация, загрузка файла, смета по страницам, перевод, проверки, выгрузка готового документа.",
        f"- [Оферта]({APP}/terms): условия использования сервиса, редакция документа фиксируется при регистрации.",
        f"- [Персональные данные]({APP}/privacy): какие данные обрабатываются, передача текста поставщику языковой модели, права пользователя.", "",
        "## Key Facts", "",
        f"- Цена: от ${starter['price']} за страницу; страница равна 250 словам исходника; подписки нет, оплата за объём.",
        "- Форматы: .docx, .pdf, .xlsx, .pptx, .html, .txt/.csv/.md, картинки и сканы; любой формат проходит через .docx и возвращается в своём формате, где это возможно.",
        "- Проверки на каждой строке: обратный перевод другой моделью, детерминированная сверка чисел, единиц, диапазонов и отрицаний, сверка с глоссарием, ревизия второй моделью на тарифе «Профи».",
        "- Оформление сохраняется: перевод пишется в исходный файл, оглавление и номера страниц пересчитывает Word, надписи на картинках переводятся отдельно.",
        "- Проверено на учебнике из 324 страниц: 2 711 строк, 162 рисунка, глоссарий из 1 307 терминов.",
        "- Языки: любая пара из каталога сервиса, интерфейс на русском, узбекском и английском.",
        "- Рынок: Узбекистан, офис в Ташкенте; работа с организациями по счёту.",
        "- Обработка данных: текст документов передаётся поставщику языковой модели (OpenAI, США), это названо в политике персональных данных.", "",
        "## Contact", "",
        f"- Сайт: {APP}",
        f"- Почта: {EMAIL}",
        "- Офис: Ташкент, Узбекистан", "",
        "## Optional", "",
        f"- [Изображение для превью]({SITE}/og.png): заголовок «Одним кликом — перевод уровня научной публикации» и цена от ${starter['price']} за страницу.", "",
    ]
    return "\n".join(lines)


def index_path(lang):
    """Куда лёг язык. Русский — в корень (на него ведут прежние ссылки
    и он же canonical), остальные — в свою папку."""
    return OUT / (LANG_DIRS[lang] + "index.html")


def main():
    made = []
    for code in langs():
        path = index_path(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_index(code), encoding="utf-8", newline="\n")
        made.append(str(path.relative_to(OUT)))
    (OUT / "sitemap.xml").write_text(build_sitemap(), encoding="utf-8", newline="\n")
    (OUT / "pricing.md").write_text(build_pricing_md(), encoding="utf-8", newline="\n")
    (OUT / "llms.txt").write_text(build_llms(), encoding="utf-8", newline="\n")
    print("landing: %s, sitemap.xml, pricing.md, llms.txt" % ", ".join(made))


if __name__ == "__main__":
    main()
