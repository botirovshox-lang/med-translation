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


def page_title(template):
    return re.search(r"<title>(.*?)</title>", template).group(1)


def page_description(template):
    return re.search(r'<meta name="description" content="(.*?)">', template).group(1)


def jsonld(template, body):
    org_id = APP + "/#organization"
    app_id = APP + "/#software"
    site_id = SITE + "/#website"
    page_id = SITE + "/#webpage"
    offers = []
    for t in TIERS:
        if t["price"] is None:
            continue
        offers.append({
            "@type": "Offer", "name": t["name"], "url": SITE + "/#pricing",
            "price": t["price"], "priceCurrency": "USD", "availability": "https://schema.org/InStock",
            "description": t["for"],
            "priceSpecification": {"@type": "UnitPriceSpecification", "price": t["price"],
                                   "priceCurrency": "USD", "unitText": "страница (250 слов исходника)"},
        })
    graph = [
        {
            "@type": "Organization", "@id": org_id, "name": BRAND, "url": APP,
            "logo": {"@type": "ImageObject", "url": SITE + "/logo.png", "width": 512, "height": 512},
            "description": "Сервис перевода документов с автоматическими проверками: обратный перевод, "
                           "сверка чисел и единиц, глоссарий. Файл возвращается в исходном оформлении.",
            "areaServed": {"@type": "Country", "name": "Uzbekistan"},
            "knowsAbout": ["Перевод документов", "Перевод научных статей и учебников",
                           "Медицинский перевод", "Контроль качества перевода",
                           "Терминологические глоссарии и память переводов"],
            "contactPoint": {"@type": "ContactPoint", "contactType": "customer service",
                             "email": EMAIL, "availableLanguage": ["ru", "uz", "en"]},
        },
        {
            "@type": "WebSite", "@id": site_id, "url": SITE + "/", "name": BRAND,
            "inLanguage": "ru", "publisher": {"@id": org_id},
        },
        {
            "@type": "WebPage", "@id": page_id, "url": SITE + "/", "name": page_title(template),
            "description": page_description(template), "inLanguage": "ru",
            "isPartOf": {"@id": site_id}, "about": {"@id": app_id},
            "datePublished": PUBLISHED, "dateModified": UPDATED,
            "primaryImageOfPage": {"@type": "ImageObject", "url": SITE + "/og.png", "width": 1200, "height": 630},
            "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".hero-answer", ".key-answer"]},
        },
        {
            "@type": "SoftwareApplication", "@id": app_id, "name": BRAND, "url": APP,
            "description": "Перевод документов языковой моделью с проверкой каждой строки: обратный перевод, "
                           "сверка чисел и единиц, глоссарий. Word, PDF, Excel, PowerPoint и сканы "
                           "возвращаются в исходном оформлении. От $0.5 за страницу в 250 слов.",
            "applicationCategory": "BusinessApplication", "operatingSystem": "Web browser",
            "inLanguage": ["ru", "uz", "en"], "featureList": FEATURES,
            "screenshot": SITE + "/og.png", "provider": {"@id": org_id}, "offers": offers,
        },
        {
            "@type": "FAQPage", "@id": SITE + "/#faq",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq_items(body)],
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=1)


def build_index():
    template = (SRC / "template.html").read_text(encoding="utf-8")
    css = (SRC / "styles.css").read_text(encoding="utf-8").rstrip("\n")
    body = (SRC / "body.html").read_text(encoding="utf-8").rstrip("\n")
    body = body.replace("__DATE_ISO__", UPDATED).replace("__DATE_RU__", _date_ru(UPDATED))
    html = (template.replace("__JSONLD__", jsonld(template, body))
            .replace("__CSS__", css).replace("__BODY__", body))
    return html


def build_sitemap():
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
            f"  <url><loc>{SITE}/</loc><lastmod>{UPDATED}</lastmod><changefreq>monthly</changefreq><priority>1.0</priority></url>\n"
            f"  <url><loc>{SITE}/pricing.md</loc><lastmod>{UPDATED}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>\n"
            "</urlset>\n")


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


def main():
    (OUT / "index.html").write_text(build_index(), encoding="utf-8", newline="\n")
    (OUT / "sitemap.xml").write_text(build_sitemap(), encoding="utf-8", newline="\n")
    (OUT / "pricing.md").write_text(build_pricing_md(), encoding="utf-8", newline="\n")
    (OUT / "llms.txt").write_text(build_llms(), encoding="utf-8", newline="\n")
    print("landing: index.html, sitemap.xml, pricing.md, llms.txt")


if __name__ == "__main__":
    main()
