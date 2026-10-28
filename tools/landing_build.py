# -*- coding: utf-8 -*-
"""Сборка лендинга click.simpletranslate.me из landing/src/home.html в landing/.

Страница одна (бывшая /start/, с 18.10.2026 — главная), языков три: /, /uz/, /en/.
Текст каждой версии ПРЕДВАРИТЕЛЬНО переведён сборщиком по словарю самой
страницы (`var UI = {…}` в её скрипте, ключи `data-t`/`data-th`/`data-ta`):
поисковик и человек без скрипта видят ту же страницу, что и человек со
скриптом, а не русскую, которую скрипт перекрашивает. Скрипт страницы потом
делает то же самое — значения совпадают, мигания нет.

Зачем сборщик, а не один файл руками:
  * FAQ-разметка (FAQPage) выводится ИЗ ВИДИМЫХ вопросов и ответов страницы.
    Разметка, написанная отдельно, разошлась бы с текстом первой же правкой,
    а разметка невидимого текста — нарушение правил Google;
  * дата обновления — одна константа (UPDATED): видимый подвал, dateModified
    схемы и lastmod sitemap;
  * цены тарифов — одна таблица (TIERS): JSON-LD Offer, pricing.md и llms.txt
    читают её; видимые цены страницы сверяет с ней тест.

Запуск: python tools/landing_build.py. Сторожит tests/test_landing.py:
собранное в репозитории обязано совпадать со свежей сборкой.
"""
import json
import re
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "landing" / "src"
OUT = ROOT / "landing"

# ─── Языки страницы ──────────────────────────────────────────────────
# Русский — язык исходника: его текст и есть home.html. Языки ВЫВОДЯТСЯ
# из словаря страницы (блоки `ru: {`, `uz: {` … в `var UI`), а не пишутся
# списком: забытый язык иначе собирался бы наполовину русским. Ключ без
# перевода роняет сборку, а не показывает русскую строку среди узбекских.
KEY_LANG = "ru"
# Адрес языка: русский лежит в корне (на него ведут все старые ссылки),
# остальные — в своей папке. Менять корень нельзя: это canonical.
LANG_DIRS = {"ru": "", "uz": "uz/", "en": "en/"}

# С 21.10.2026 лендинг — корень simpletranslate.me, приложение — /app, вход —
# /login и /register (click.simpletranslate.me отвечает 301 сюда же).
SITE = "https://simpletranslate.me"
APP = "https://simpletranslate.me"
BRAND = "SimpleTranslate"
UPDATED = "2026-10-28"            # ISO; меняется вместе с правкой текста
PUBLISHED = "2026-09-17"
# Почты на домене нет (MX не заведён) — связь через бота поддержки.
TELEGRAM = "https://t.me/simpletranslateme_bot"
TG_HANDLE = "@simpletranslateme_bot"

# ─── Индексация, счётчик, подтверждение прав ─────────────────────────
# INDEXABLE — ОДНО место решения «видна ли страница поисковикам и ИИ».
# Из него собираются и мета robots, и robots.txt: два места врозь уже
# расходились (сайт закрыли 19.09 правкой трёх файлов). 24.09 открыт снова:
# владелец заказал метатеги, ключевые слова и Метрику, а для закрытой
# страницы всё это не значит ничего.
INDEXABLE = True
# Номер счётчика Яндекс Метрики. Пусто — счётчика на странице нет вовсе
# (а не «счётчик с нулём»): выдуманный номер слал бы визиты в чужой счётчик.
METRIKA_ID = "113660224"
# Коды подтверждения прав в Яндекс Вебмастере и Google Search Console.
# Пусто — тега нет. Берутся из кабинетов при добавлении сайта.
YANDEX_VERIFICATION = ""
GOOGLE_VERIFICATION = ""
# Ключ IndexNow (Яндекс, Bing): файл `<ключ>.txt` с самим ключом лежит
# в корне лендинга, пинг — `python tools/landing_build.py --ping`. Ключ
# публичный по устройству протокола: он доказывает только то, что пинг
# шлёт хозяин сайта, и для этого должен лежать на сайте открыто.
INDEXNOW_KEY = "5f0c9b7e2a4d4e8f9c1b6a3d7e2f4c80"
# Бесплатный объём формы («5 страниц бесплатно», с 21.10.2026). Обещание
# держит СЕРВЕР: SIGNUP_FREE_PAGES и SIGNUP_TRIAL_USD > 0 в /etc/medcat/env.
# Выкатывать страницу с этим текстом без них — обещать то, чего нет.
FREE_PAGES = 5
# Язык оригинала в форме по умолчанию — язык страницы: его человек знает
# (инвариант 32), и чаще всего переводит именно с него. Языка ПЕРЕВОДА
# по умолчанию нет намеренно (см. форму в body.html).
# Частые языки — первыми в списке, в том же порядке, что у приложения
# (IMP_POPULAR_LANGS в tab_import.jsx): семьдесят языков по алфавиту
# прячут русский и узбекский в середине.


MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря"]

# Тарифы — источник правды для страницы, схемы, pricing.md и llms.txt.
TIERS = [
    {"name": "Документы", "price": "0.9", "unit": "page", "recommended": True,
     "for": "Статьи, книги, договоры, сканы — любой объём",
     "includes": ["Перевод и полный набор автопроверок (обратный перевод, числа и единицы, глоссарий)",
                  "Ревизия второй моделью: читает пару целиком",
                  "Выгрузка в исходном формате 1 в 1",
                  "Чтение и перевод текста на картинках и сканах",
                  "Свой глоссарий и память переводов", "Команда до 5 человек с ролями",
                  "Оплата только за объём, без подписки; первые 5 страниц бесплатно"]},
    {"name": "Видео", "price": "1", "unit": "minute",
     "for": "Ролики, лекции, интервью — с субтитрами",
     "includes": ["Распознавание речи и субтитры с таймингом", "Перевод субтитров с теми же проверками",
                  "Субтитры в кадре или файлом .srt / .vtt", "Перевод надписей и титров в кадре",
                  "Неполная минута считается минутой"]},
    {"name": "Издательство", "price": None, "for": "Книги, серии, учебники, регулярные объёмы",
     "includes": ["Всё из «Документов» и «Видео»", "Отдельные словари на каждый проект",
                  "Счёт на организацию, закрывающие документы", "Персональный менеджер"]},
]
UNIT_RU = {"page": "за страницу", "minute": "за минуту"}

# ─── Мета страницы по языкам ─────────────────────────────────────────
# Title и description НЕ переводятся автоматически из тела: у них жёсткие
# пределы длины (30–60 и 120–160 знаков), а перевод их не соблюдает —
# узбекская фраза длиннее русской на четверть. Поэтому они написаны
# на каждом языке отдельно и сторожатся тестом по длине.
META = {
    "ru": {
        "title": "Перевод документов онлайн: Word, PDF | SimpleTranslate",
        "desc": "Переведите Word, PDF, Excel и PowerPoint онлайн с сохранением форматирования. "
                "Первые 5 страниц бесплатно, дальше $0.9 за страницу. Сверка каждой строки.",
        "keywords": "перевод документов онлайн, перевести документ, перевод pdf, перевод word, "
                    "перевод с сохранением форматирования, перевод excel, перевод презентации, "
                    "перевод научной статьи, перевод медицинских документов, перевод на узбекский",
        "locale": "ru_RU",
        "ogTitle": "Перевод документов онлайн в один клик — SimpleTranslate",
        "ogDesc": "Word, PDF, Excel и PowerPoint в том же оформлении: обратный перевод, "
                  "сверка чисел и глоссарий. Первые 5 страниц бесплатно.",
        "ogAlt": "SimpleTranslate: перевод документов онлайн в один клик, "
                 "$0.9 за страницу",
        "ldDesc": "Перевод документов языковой моделью с проверкой каждой строки: обратный перевод, "
                  "сверка чисел и единиц, глоссарий. Word, PDF, Excel, PowerPoint и сканы "
                  "возвращаются в исходном оформлении. $0.9 за страницу в 250 слов, видео — $1 за минуту.",
        "orgDesc": "Сервис перевода документов с автоматическими проверками: обратный перевод, "
                   "сверка чисел и единиц, глоссарий. Файл возвращается в исходном оформлении.",
        "unit": "страница (250 слов исходника)", "unitMin": "минута видео",
    },
    "uz": {
        "title": "Hujjatlarni onlayn tarjima qilish | SimpleTranslate",
        "desc": "Word, PDF, Excel va PowerPoint fayllarini formatini saqlagan holda onlayn tarjima "
                "qiling. Birinchi 5 bet bepul, keyin bet uchun $0.9. Har bir satr tekshiriladi.",
        "keywords": "hujjat tarjimasi, hujjatlarni tarjima qilish, onlayn tarjima, pdf tarjima, "
                    "word faylni tarjima qilish, rus tilidan oʻzbek tiliga tarjima, "
                    "ingliz tiliga tarjima, ilmiy maqola tarjimasi",
        "locale": "uz_UZ",
        "ogTitle": "Hujjatlarni onlayn tarjima qilish bir bosishda — SimpleTranslate",
        "ogDesc": "Word, PDF, Excel va PowerPoint oʻsha koʻrinishda: teskari tarjima, "
                  "sonlarni solishtirish va lugʻat. Birinchi 5 bet bepul.",
        "ogAlt": "SimpleTranslate: hujjatlarni bir bosishda onlayn tarjima qilish, "
                 "bet uchun $0.9",
        "ldDesc": "Hujjatlarni til modeli bilan tarjima qilish va har bir satrni tekshirish: "
                  "teskari tarjima, son va birliklarni solishtirish, lugʻat. Word, PDF, Excel, "
                  "PowerPoint va skanlar asl koʻrinishida qaytariladi. 250 soʻzlik bet $0.9, video daqiqasiga $1.",
        "orgDesc": "Avtomatik tekshiruvli hujjat tarjimasi xizmati: teskari tarjima, son va "
                   "birliklarni solishtirish, lugʻat. Fayl asl koʻrinishida qaytariladi.",
        "unit": "bet (asl matnning 250 soʻzi)", "unitMin": "video daqiqasi",
    },
    "en": {
        "title": "Document Translation Online, Same Layout | SimpleTranslate",
        "desc": "Translate Word, PDF, Excel and PowerPoint files online and keep the formatting. "
                "First 5 pages free, then $0.9 per page. Every line is checked.",
        "keywords": "document translation online, translate pdf keep formatting, translate word document, "
                    "translate docx, translate excel file, russian to uzbek translation, "
                    "scientific paper translation",
        "locale": "en_US",
        "ogTitle": "One-click document translation — SimpleTranslate",
        "ogDesc": "Word, PDF, Excel and PowerPoint in the same layout: back-translation, "
                  "number checks and a glossary. The first 5 pages are free.",
        "ogAlt": "SimpleTranslate: one-click document translation online, "
                 "$0.9 per page",
        "ldDesc": "Document translation by a language model with every line checked: back-translation, "
                  "comparison of numbers and units, a glossary. Word, PDF, Excel, PowerPoint and scans "
                  "come back in their original layout. $0.9 per 250-word page, video $1 per minute.",
        "orgDesc": "A document translation service with automatic checks: back-translation, "
                   "comparison of numbers and units, a glossary. The file comes back in its original layout.",
        "unit": "page (250 words of the source)", "unitMin": "minute of video",
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


def _home():
    return (SRC / "home.html").read_text(encoding="utf-8")


def ui_dict(src=None):
    """Словарь страницы {язык: {ключ: строка}} из `var UI = {…}` её скрипта.
    Значения — строки JS в двойных кавычках; это подмножество JSON."""
    src = src if src is not None else _home()
    i = src.index("var UI = {")
    j = src.index("\n  };", i)
    block = src[i:j]
    out = {}
    for m in re.finditer(r"\n    ([a-z]{2}): \{(.*?)\n    \}", block, re.S):
        out[m.group(1)] = {k: json.loads(v) for k, v in
                           re.findall(r'(\w+): ("(?:[^"\\]|\\.)*")', m.group(2))}
    if KEY_LANG not in out:
        raise SystemExit("в home.html нет словаря языка ключей")
    return out


def langs():
    """Языки страницы — по словарю. Русский первым: он лежит в корне."""
    return [KEY_LANG] + sorted(c for c in ui_dict() if c != KEY_LANG)


def _esc_text(v):
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(v):
    return _esc_text(v).replace('"', "&quot;")


def prerender(html, lang):
    """Текст страницы на языке `lang` — тем же словарём, что у её скрипта.
    Ключа нет на этом языке — сборка падает (скрипт показал бы русский)."""
    table, base = ui_dict(html)[lang], ui_dict(html)[KEY_LANG]
    missing = set()
    def val(k):
        if k not in base:
            missing.add(k)
            return ""
        if k not in table:
            missing.add(k)
            return base[k]
        return table[k]
    # data-t: текст элемента целиком (у таких элементов детей нет)
    def sub_t(m):
        return m.group(1) + _esc_text(val(m.group(3))) + m.group(5)
    html = re.sub(r'(<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?\sdata-t="(\w+)"[^>]*>)([^<]*)(</\2>)', sub_t, html)
    # data-th: HTML-содержимое (подпись источников со ссылками)
    def sub_th(m):
        return m.group(1) + val(m.group(3)) + m.group(5)
    html = re.sub(r'(<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?\sdata-th="(\w+)"[^>]*>)(.*?)(</\2>)', sub_th, html, flags=re.S)
    # data-ta="атрибут:ключ"
    def sub_ta(m):
        tag = m.group(0)
        for spec in re.findall(r'data-ta="([^"]+)"', tag):
            attr, key = spec.split(":", 1)
            v = _esc_attr(val(key))
            if re.search(r'\s%s="[^"]*"' % re.escape(attr), tag):
                tag = re.sub(r'(\s%s=")[^"]*(")' % re.escape(attr), lambda x: x.group(1) + v + x.group(2), tag, count=1)
            else:
                tag = tag[:-1] + ' %s="%s">' % (attr, v)
        return tag
    html = re.sub(r'<[a-zA-Z][^>]*\sdata-ta="[^"]+"[^>]*>', sub_ta, html)
    if missing:
        raise SystemExit("нет перевода на «%s» для ключей: %s" % (lang, ", ".join(sorted(missing)[:20])))
    return html


def _text(html):
    """Видимый текст из куска HTML: теги долой, сущности раскрыть, пробелы сжать."""
    t = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def faq_items(body):
    """Пары «вопрос — ответ» из видимого раздела FAQ."""
    sec = re.search(r'<section id="faq".*?</section>', body, re.S)
    if not sec:
        raise SystemExit("FAQ section not found")
    items = re.findall(r'<article class="faq[^"]*">\s*<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>', sec.group(0), re.S)
    if len(items) < 5:
        raise SystemExit("FAQ has fewer than 5 questions")
    return [(_text(q), _text(a)) for q, a in items]


def page_title(lang=KEY_LANG):
    return META[lang]["title"]


def page_description(lang=KEY_LANG):
    return META[lang]["desc"]


def jsonld(body, lang=KEY_LANG):
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
            "@type": "Offer", "name": t["name"], "url": SITE + "/" + LANG_DIRS[lang] + "#pricing",
            "price": t["price"], "priceCurrency": "USD", "availability": "https://schema.org/InStock",
            "description": t["for"],
            "priceSpecification": {"@type": "UnitPriceSpecification", "price": t["price"],
                                   "priceCurrency": "USD", "unitText": m["unitMin"] if t.get("unit") == "minute" else m["unit"]},
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
                             "url": TELEGRAM, "availableLanguage": ["ru", "uz", "en"]},
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
            "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".hero-answer", ".faq p"]},
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


def hreflang_links(lang):
    """Связка переводов. x-default ведёт на русскую: на неё ведут все
    прежние ссылки, и она же лежит в корне."""
    out = []
    for code in langs():
        out.append('<link rel="alternate" hreflang="%s" href="%s/%s">'
                   % (code, SITE, LANG_DIRS[code]))
    out.append('<link rel="alternate" hreflang="x-default" href="%s/">' % SITE)
    return "\n".join(out)


def head_meta(lang):
    """Мета, которые зависят от решений выше: индексация, подтверждение прав,
    ключевые слова. Ключевые слова Google не читает, Яндекс учитывает слабо —
    но тег ничего не стоит, а список совпадает с ядром из docs."""
    out = ['<meta name="robots" content="%s">'
           % ("index, follow, max-image-preview:large, max-snippet:-1" if INDEXABLE else "noindex, nofollow")]
    if META[lang].get("keywords"):
        out.append('<meta name="keywords" content="%s">' % META[lang]["keywords"])
    if YANDEX_VERIFICATION:
        out.append('<meta name="yandex-verification" content="%s">' % YANDEX_VERIFICATION)
    if GOOGLE_VERIFICATION:
        out.append('<meta name="google-site-verification" content="%s">' % GOOGLE_VERIFICATION)
    return "\n".join(out)


def metrika():
    """Счётчик Яндекс Метрики — стандартный код кабинета, асинхронно
    (первому кадру он не мешает). Номера нет — нет и кода. Цели формы
    (tr_file, tr_submit, tr_handoff_ok/fail) ставит скрипт страницы через
    window.METRIKA_ID: их надо завести в кабинете как «JavaScript-событие»."""
    if not METRIKA_ID:
        return ""
    return ('<script>window.METRIKA_ID=%(id)s;'
            '(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};'
            'm[i].l=1*new Date();for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}'
            'k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})'
            '(window,document,"script","https://mc.yandex.ru/metrika/tag.js?id=%(id)s","ym");'
            # Параметры — как в коде кабинета (17.10.2026): ssr, ecommerce
            # через dataLayer, явные referrer и url.
            'ym(%(id)s,"init",{ssr:true,webvisor:true,clickmap:true,ecommerce:"dataLayer",'
            'referrer:document.referrer,url:location.href,accurateTrackBounce:true,trackLinks:true});</script>\n'
            '<noscript><div><img src="https://mc.yandex.ru/watch/%(id)s" style="position:absolute;left:-9999px" alt=""></div></noscript>'
            % {"id": int(METRIKA_ID)})


HEAD_SEO = """<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<link rel="canonical" href="__CANON__">
__HREFLANG__
__HEADMETA__
<meta name="theme-color" content="#F2F5FA">
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-96.png" type="image/png" sizes="96x96">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="SimpleTranslate">
<meta property="og:locale" content="__OGLOCALE__">
<meta property="og:url" content="__CANON__">
<meta property="og:title" content="__OGTITLE__">
<meta property="og:description" content="__OGDESC__">
<meta property="og:image" content="__SITE__/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="__OGALT__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="__OGTITLE__">
<meta name="twitter:description" content="__OGDESC__">
<meta name="twitter:image" content="__SITE__/og.png">
<script type="application/ld+json">
__JSONLD__
</script>"""


def build_index(lang=KEY_LANG):
    html = _home()
    body = prerender(html, lang)
    body = (body.replace("__LANG__", lang)
                .replace("__DATE_ISO__", UPDATED)
                .replace("__DATE_YEAR__", UPDATED[:4])
                .replace("__METRIKA__", metrika()))
    m = META[lang]
    head = (HEAD_SEO.replace("__TITLE__", m["title"]).replace("__DESC__", m["desc"])
            .replace("__CANON__", SITE + "/" + LANG_DIRS[lang]).replace("__SITE__", SITE)
            .replace("__HREFLANG__", hreflang_links(lang))
            .replace("__HEADMETA__", head_meta(lang))
            .replace("__OGLOCALE__", m["locale"]).replace("__OGTITLE__", m["ogTitle"])
            .replace("__OGDESC__", m["ogDesc"]).replace("__OGALT__", m["ogAlt"]))
    head = head.replace("__JSONLD__", jsonld(body, lang))
    out = body.replace("__HEADSEO__", head)
    # Заметки разработчика — в исходнике, не в публичной странице.
    out = re.sub(r"<!--(?!\[if).*?-->\n?", "", out, flags=re.S)
    out = re.sub(r"(<style>)(.*?)(</style>)",
                 lambda m: m.group(1) + re.sub(r"/\*.*?\*/\n?", "", m.group(2), flags=re.S) + m.group(3),
                 out, flags=re.S)
    return out


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
        price = f"${t['price']} {UNIT_RU[t.get('unit', 'page')]}" if t["price"] else "цена по договорённости"
        rec = " (рекомендуемый)" if t.get("recommended") else ""
        lines += [f"## {t['name']}{rec}", "", f"- Цена: {price}", f"- Для кого: {t['for']}", "- Включено:"]
        lines += [f"  - {x}" for x in t["includes"]]
        lines.append("")
    lines += ["## Примеры", "",
              "- Статья на 20 страниц: $18 (первые 5 страниц бесплатно — к оплате $13.5)",
              "- Диссертация на 150 страниц: $135",
              "- Книга на 300 страниц: $270",
              "- Видео на 10 минут: $10", "",
              f"Сервис: {APP} · Лендинг: {SITE}/ · Поддержка в Telegram: {TELEGRAM}", ""]
    return "\n".join(lines)


def build_llms():
    starter = next(t for t in TIERS if t.get("unit") == "page")
    video = next(t for t in TIERS if t.get("unit") == "minute")
    lines = [
        f"# {BRAND}", "",
        f"> Сервис перевода документов (Word, PDF, Excel, PowerPoint, сканы) языковой моделью с проверкой каждой строки; файл возвращается в исходном оформлении, ${starter['price']} за страницу и ${video['price']} за минуту видео.", "",
        "## Products", "",
        f"- [{BRAND}, лендинг]({SITE}/): что переводим (книги, статьи, видео, сканы), примеры настоящих переводов, перевод в один клик и запись экрана, тарифы, вопросы и ответы, контакты.",
        f"- [Тарифы]({SITE}/pricing.md): цена за страницу документа, за минуту видео и договорная для издательств; что включено, примеры расчёта.",
        f"- [Приложение]({APP}): вход и регистрация, загрузка файла, смета по страницам, перевод, проверки, выгрузка готового документа.",
        f"- [Оферта]({APP}/terms): условия использования сервиса, редакция документа фиксируется при регистрации.",
        f"- [Персональные данные]({APP}/privacy): какие данные обрабатываются, передача текста поставщикам языковых моделей, права пользователя.", "",
        "## Key Facts", "",
        f"- Цена: ${starter['price']} за страницу документа (250 слов исходника), ${video['price']} за минуту видео; первые 5 страниц бесплатно; подписки нет, оплата за объём.",
        "- Форматы: .docx, .pdf, .xlsx, .pptx, .html, .txt/.csv/.md, картинки и сканы; любой формат проходит через .docx и возвращается в своём формате, где это возможно.",
        "- Проверки на каждой строке: обратный перевод другой моделью, детерминированная сверка чисел, единиц, диапазонов и отрицаний, сверка с глоссарием, ревизия второй моделью.",
        "- Оформление сохраняется: перевод пишется в исходный файл, оглавление и номера страниц пересчитывает Word, надписи на картинках переводятся отдельно.",
        "- Проверено на учебнике из 324 страниц: 2 711 строк, 162 рисунка, глоссарий из 1 307 терминов.",
        "- Языки: любая пара из каталога сервиса, интерфейс на русском, узбекском и английском.",
        "- Рынок: Узбекистан и соседние страны; работа с организациями по счёту; поддержка 24/7.",
        "- Обработка данных: текст документов передаётся поставщикам языковых моделей (OpenAI и Anthropic, США), это названо в политике персональных данных.", "",
        "## Contact", "",
        f"- Сайт: {APP}",
        f"- Поддержка в Telegram: {TELEGRAM} ({TG_HANDLE}) — отвечает человек", "",
        "## Optional", "",
        f"- [Изображение для превью]({SITE}/og.png): заголовок «Одним кликом — перевод уровня научной публикации» и цена ${starter['price']} за страницу.", "",
    ]
    return "\n".join(lines)


# ─── Страница 404 ────────────────────────────────────────────────────
# Одна на все языки: nginx отдаёт её на любой неизвестный адрес
# (`error_page 404 /404.html`), и по адресу язык не угадать — «/uz/foo»
# и «/foo» приходят одинаково. Поэтому три коротких блока, каждый на своём
# языке и со своим `lang`, и ссылки на три главные страницы.
# noindex обязателен: заглушка в выдаче — мусор в индексе. Код ответа —
# настоящий 404 (его ставит nginx), а не 200: «мягкий 404» поисковик
# считает дублем главной.
NOT_FOUND = [
    ("ru", "Такой страницы нет", "Возможно, ссылка устарела или в адресе опечатка.",
     "На главную", "Перевести документ"),
    ("uz", "Bunday sahifa yoʻq", "Havola eskirgan yoki manzilda xato boʻlishi mumkin.",
     "Bosh sahifaga", "Hujjatni tarjima qilish"),
    ("en", "Page not found", "The link may be outdated, or there is a typo in the address.",
     "Home page", "Translate a document"),
]


def _fonts_link():
    """Те же шрифты, что у главной: строки берутся ИЗ home.html."""
    return "".join(l + "\n" for l in _home().splitlines()
                   if "fonts.g" in l and l.startswith("<link"))


NF_CSS = """  :root { --canvas: #F2F5FA; --panel: #FBFCFE; --line: #DAE2EE; --ink: #0B1324; --ink-2: #44516A; --accent: #0A5CF0; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--canvas); color: var(--ink); font: 400 17px/1.55 "Manrope", "Segoe UI", system-ui, sans-serif; }
  .logo { display: inline-flex; gap: 10px; align-items: center; color: var(--ink); text-decoration: none; font-weight: 800; }
  .logo-mark { width: 28px; height: 28px; border-radius: 8px; background: var(--accent); }
  .nf-page { min-height: 100vh; display: grid; place-content: center; gap: 44px; padding: 48px 20px; }
  .nf { display: grid; gap: 12px; max-width: 34rem; }
  .nf h1, .nf h2 { margin: 0; font: 600 clamp(1.4rem, 3vw, 2rem)/1.2 "Unbounded", "Segoe UI", sans-serif; }
  .nf p { margin: 0; color: var(--ink-2); }
  .nf-links { display: flex; flex-wrap: wrap; gap: 10px; }
  .btn { display: inline-flex; align-items: center; min-height: 46px; padding: 0 20px; border-radius: 999px; font-weight: 700; text-decoration: none; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-ghost { border: 1.5px solid var(--line); color: var(--ink); background: var(--panel); }"""


def build_404():
    blocks = []
    for code, h, p, home, go in NOT_FOUND:
        lvl = 1 if code == KEY_LANG else 2
        blocks.append(
            '<section class="nf" lang="%s"><h%d>%s</h%d><p>%s</p>'
            '<p class="nf-links"><a class="btn btn-primary" href="%s/%s#tr">%s</a>'
            '<a class="btn btn-ghost" href="%s/%s">%s</a></p></section>'
            % (code, lvl, h, lvl, p, SITE, LANG_DIRS[code], go, SITE, LANG_DIRS[code], home))
    return ("<!doctype html>\n<html lang=\"ru\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>404 — SimpleTranslate</title>\n"
            "<meta name=\"robots\" content=\"noindex, follow\">\n"
            "<link rel=\"icon\" href=\"/favicon.ico\" sizes=\"48x48\">\n"
            "<link rel=\"icon\" href=\"/favicon.svg\" type=\"image/svg+xml\">\n"
            + _fonts_link() +
            "<style>\n" + NF_CSS + "\n</style>\n" + metrika() + "\n</head>\n<body>\n<main class=\"nf-page\">\n"
            + '<a class="logo" href="%s/"><span class="logo-mark" aria-hidden="true"></span>'
              '<span class="logo-t">%s</span></a>\n' % (SITE, BRAND)
            + "\n".join(blocks) + "\n</main>\n</body>\n</html>\n")


# ─── robots.txt ──────────────────────────────────────────────────────
# Собирается из INDEXABLE, а не лежит руками: мета robots и robots.txt —
# одно решение, и в двух файлах врозь оно однажды разошлось бы.
# ИИ-краулеры названы поимённо (GEO): «User-agent: *» их тоже пускает, но
# явная строка — ответ на вопрос «разрешили ли нас», который они задают.
# Clean-param — правило ЯНДЕКСА: метки рекламы и приглашений не плодят
# дубли страницы в индексе.
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
           "PerplexityBot", "Google-Extended", "Applebot-Extended"]


def build_robots():
    if not INDEXABLE:
        return ("# Закрыт от индексации и обхода (INDEXABLE = False в tools/landing_build.py).\n"
                "User-agent: *\nDisallow: /\n\n"
                "Content-Signal: search=no, ai-retrieval=no, ai-train=no\n")
    # Приложение живёт на том же адресе (с 21.10.2026). Его страницы (/app,
    # /login, /register) НЕ закрыты здесь намеренно: закрытую в robots.txt
    # страницу поисковик не скачивает и заголовка noindex (его ставит nginx
    # приложению) не видит, а ссылки «Войти» с лендинга попадают в индекс
    # голым адресом — «заблокировано в robots.txt». Закрыты только служебные
    # двери. Запреты — в КАЖДОЙ группе: робот читает только свою.
    deny = ["Disallow: " + p for p in ("/api/", "/handoff", "/media-dl/", "/t/a/")]
    lines = ["# simpletranslate.me — собирается tools/landing_build.py (INDEXABLE).",
             "User-agent: *", "Allow: /"] + deny + ["",
             "User-agent: Yandex", "Allow: /"] + deny + [
             "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid&ref /", ""]
    for bot in AI_BOTS:
        lines += ["User-agent: " + bot, "Allow: /"] + deny + [""]
    lines += ["Sitemap: %s/sitemap.xml" % SITE, ""]
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
    (OUT / "404.html").write_text(build_404(), encoding="utf-8", newline="\n")
    (OUT / "robots.txt").write_text(build_robots(), encoding="utf-8", newline="\n")
    (OUT / (INDEXNOW_KEY + ".txt")).write_text(INDEXNOW_KEY, encoding="utf-8", newline="\n")
    print("landing: %s, sitemap.xml, pricing.md, llms.txt, 404.html, robots.txt" % ", ".join(made))


def ping_indexnow():
    """Сообщить Яндексу (а через IndexNow — и Bing) о свежей версии страниц.
    Зовётся руками ПОСЛЕ выката: до выката поисковик пришёл бы за старой."""
    import urllib.request
    urls = [SITE + "/" + LANG_DIRS[c] for c in langs()]
    body = json.dumps({"host": SITE.split("//")[1], "key": INDEXNOW_KEY,
                       "keyLocation": "%s/%s.txt" % (SITE, INDEXNOW_KEY), "urlList": urls}).encode()
    rq = urllib.request.Request("https://yandex.com/indexnow", data=body,
                                headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(rq, timeout=15) as r:
        print("IndexNow:", r.status, ", ".join(urls))


if __name__ == "__main__":
    import sys
    if "--ping" in sys.argv:
        ping_indexnow()
    else:
        main()
