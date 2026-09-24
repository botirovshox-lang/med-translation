# -*- coding: utf-8 -*-
"""Лендинг click.simpletranslate.me: собранное совпадает с исходниками, а SEO-разметка честна.

Что сторожится и почему именно это:

  1. СОБРАННОЕ В РЕПОЗИТОРИИ РАВНО СВЕЖЕЙ СБОРКЕ. Правка в landing/src/ без
     `python tools/landing_build.py` выкатила бы старую страницу — тот же
     закон, что у словаря интерфейса (tools/i18n_build.py).
  2. FAQ-разметка (FAQPage) равна ВИДИМЫМ вопросам и ответам: разметка
     невидимого текста — нарушение правил Google, а расхождение заметил бы
     не разработчик, а поисковик.
  3. Дата обновления ОДНА: видимый футер, dateModified схемы и lastmod
     sitemap. Три даты врозь — три разных ответа на «когда это правили».
  4. Цены ОДНИ: тарифы на странице, Offer в JSON-LD и pricing.md называют
     одну цену. Агент, который прочитал pricing.md, не должен назвать
     клиенту не ту цифру, что на странице.
  5. Лимиты метаданных из скиллов: title 30–60 знаков, description 120–160,
     ровно один H1, canonical и robots в самом HTML (краулеры JS не выполняют).
  6. Определение «SimpleTranslate — это …» стоит в первых 60 словах текста,
     а селекторы speakable существуют на странице.
  7. robots.txt и мета robots — ОДНО решение (`INDEXABLE` в сборщике):
     открыт — мета index, robots.txt с Allow, Sitemap и ИИ-краулерами поимённо;
     закрыт — noindex и Disallow: / для всех. Оба файла собираются из одной
     константы, и разойтись им нечем. llms.txt начинается с H1 и цитаты,
     длина в допуске 30–200 строк.
  8. Тела кнопок без «→» и эмодзи (правила craft floor), все якоря `#…`
     ведут на существующие id, цена «от $0.5» есть в тексте страницы.
 11. Форма перевода на первом экране: настоящая <form> в приложение (работает
     без скрипта), языки — из каталога сервиса, языка перевода по умолчанию
     нет, файл уходит только в фрейм приложения и только его источнику.
 12. Страница 404 (noindex, три языка), счётчик Метрики есть ровно тогда,
     когда задан номер, и nginx-конфиг пускает то, что страница зовёт.

Ни одного вызова модели, сеть не трогается.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import landing_build as lb  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def text_of(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


html = (ROOT / "landing" / "index.html").read_text(encoding="utf-8")
body = (ROOT / "landing" / "src" / "body.html").read_text(encoding="utf-8")

# 1. сборка свежая
check(html == lb.build_index(), "landing/index.html отстал от landing/src — запусти python tools/landing_build.py")
check((ROOT / "landing" / "sitemap.xml").read_text(encoding="utf-8") == lb.build_sitemap(), "sitemap.xml отстал от сборки")
check((ROOT / "landing" / "pricing.md").read_text(encoding="utf-8") == lb.build_pricing_md(), "pricing.md отстал от сборки")
check((ROOT / "landing" / "llms.txt").read_text(encoding="utf-8") == lb.build_llms(), "llms.txt отстал от сборки")

# 5. метаданные
title = re.search(r"<title>(.*?)</title>", html).group(1)
desc = re.search(r'<meta name="description" content="(.*?)">', html).group(1)
check(30 <= len(title) <= 60, f"title {len(title)} знаков, надо 30–60")
check(120 <= len(desc) <= 160, f"description {len(desc)} знаков, надо 120–160")
check(not desc.startswith(title), "description начинается с title слово в слово")
check(html.count("<h1") == 1, "H1 не ровно один")
check('<link rel="canonical" href="https://click.simpletranslate.me/">' in html, "canonical не самоссылающийся")
if lb.INDEXABLE:
    check('<meta name="robots" content="index, follow' in html, "robots meta не index, follow при INDEXABLE")
else:
    check('<meta name="robots" content="noindex' in html, "robots meta должен быть noindex — сайт закрыт")
check('<html lang="ru">' in html, "lang=ru нет")
for tag in ("og:title", "og:description", "og:image", "og:url", "og:site_name", "twitter:card"):
    check(f'"{tag}"' in html, f"нет {tag}")
check('name="viewport"' in html and "viewport-fit=cover" in html, "viewport без viewport-fit=cover")
check(html.index("</h2>") < html.index("<h3") if "<h3" in html else True, "H3 раньше первого H2")

# 2. JSON-LD
ld = json.loads(re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', html, re.S).group(1))
types = {g["@type"]: g for g in ld["@graph"]}
for t in ("Organization", "WebSite", "WebPage", "SoftwareApplication", "FAQPage"):
    check(t in types, f"в @graph нет {t}")
faq_visible = lb.faq_items(body)
faq_schema = [(q["name"], q["acceptedAnswer"]["text"]) for q in types["FAQPage"]["mainEntity"]]
check(faq_schema == faq_visible, "FAQPage расходится с видимыми вопросами")
check(len(faq_visible) >= 5, "меньше пяти вопросов в FAQ")
for q, a in faq_visible:
    check(q.endswith("?"), f"вопрос без знака вопроса: {q}")
    n = len(a.split())
    check(40 <= n <= 110, f"ответ на «{q}» — {n} слов, надо 40–110")
check(all(re.match(r"^https://", u) for u in re.findall(r'"url": "([^"]+)"', json.dumps(ld))), "в схеме есть не абсолютный url")
for sel in types["WebPage"]["speakable"]["cssSelector"]:
    check(f'class="{sel[1:]}' in html or f' {sel[1:]}"' in html or f' {sel[1:]} ' in html, f"speakable селектор {sel} не найден")

# 3. одна дата
check(types["WebPage"]["dateModified"] == lb.UPDATED, "dateModified ≠ UPDATED")
check(f'<time datetime="{lb.UPDATED}">' in html, "видимой даты обновления нет")
sm = ET.fromstring((ROOT / "landing" / "sitemap.xml").read_text(encoding="utf-8"))
ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
locs = [u.find("s:loc", ns).text for u in sm.findall("s:url", ns)]
want = [lb.SITE + "/" + lb.LANG_DIRS[c] for c in lb.langs()] + [lb.SITE + "/pricing.md"]
check(locs == want, f"sitemap: {locs}")
check(all(u.find("s:lastmod", ns).text == lb.UPDATED for u in sm.findall("s:url", ns)), "lastmod ≠ UPDATED")

# 4. одни цены
page_text = text_of(html)
offers = {o["name"]: o["price"] for o in types["SoftwareApplication"]["offers"]}
pricing_md = (ROOT / "landing" / "pricing.md").read_text(encoding="utf-8")
for t in lb.TIERS:
    if t["price"]:
        check(offers.get(t["name"]) == t["price"], f"Offer {t['name']} ≠ {t['price']}")
        check(f"${t['price']}" in page_text, f"цены ${t['price']} нет в тексте страницы")
        check(f"${t['price']} за страницу" in pricing_md, f"pricing.md без цены {t['name']}")
check("от $0.5" in page_text, "«от $0.5» не найдено в тексте")

# 6. определение в первых 60 словах основного текста
main_text = text_of(re.search(r"<main.*?</main>", html, re.S).group(0))
check("SimpleTranslate — это" in " ".join(main_text.split()[:60]), "определения «SimpleTranslate — это» нет в первых 60 словах")

# 7. robots / llms — одно решение с мета robots
robots = (ROOT / "landing" / "robots.txt").read_text(encoding="utf-8")
check(robots == lb.build_robots(), "robots.txt отстал от сборки")
if lb.INDEXABLE:
    check("Disallow: /\n" not in robots, "robots.txt закрывает сайт, а INDEXABLE = True")
    check(f"Sitemap: {lb.SITE}/sitemap.xml" in robots, "в robots.txt нет Sitemap")
    for bot in ("GPTBot", "ClaudeBot", "PerplexityBot", "Yandex"):
        check(f"User-agent: {bot}" in robots, f"robots.txt не называет {bot}")
    check("Clean-param: utm_source" in robots, "нет Clean-param для меток (Яндекс)")
else:
    check("User-agent: *" in robots and "Disallow: /" in robots, "robots.txt не закрывает сайт при INDEXABLE = False")
    check("Allow: /" not in robots, "robots.txt что-то разрешает при INDEXABLE = False")
llms = (ROOT / "landing" / "llms.txt").read_text(encoding="utf-8").splitlines()
check(llms[0].startswith("# "), "llms.txt не начинается с H1")
check(llms[2].startswith("> ") and len(llms[2]) < 260, "llms.txt: вторая строка не цитата")
check(30 <= len(llms) <= 200, f"llms.txt {len(llms)} строк, допуск 30–200")
check(all(re.match(r"^- \[[^\]]+\]\(https://[^)]+\)", l) for l in llms if l.startswith("- [")), "llms.txt: ссылка не абсолютная")

# 8. кнопки, якоря, эмодзи
buttons = re.findall(r'class="btn[^"]*"[^>]*>(.*?)</a>', html, re.S)
check(buttons and all("→" not in b for b in buttons), "в кнопке стрелка «→»")
check(not re.search("[\U0001F300-\U0001FAFF☀-➿]", html), "эмодзи в разметке")
ids = set(re.findall(r' id="([^"]+)"', html))
for a in set(re.findall(r'href="#([^"]+)"', html)):
    check(a in ids, f"якорь #{a} без цели")
check("Примеры отзывов для макета" in page_text or "примеры отзывов" in page_text.lower(), "отзывы-примеры не помечены как примеры")
check("click.simpletranslate.me" in (ROOT / "deploy" / "nginx-click.conf").read_text(encoding="utf-8"), "nginx-конфиг поддомена не про click")


# ─── 9. Языки: страница на каждом, и ни одной русской строки в переводе ───
# Забытый перевод на экране выглядит русской строкой среди узбекских,
# и заметит её клиент, а не разработчик, — тот же закон, что у словаря
# приложения (tests/test_i18n.js).
for code in lb.langs():
    path = ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")
    check(path.exists(), f"нет собранной страницы для «{code}»")
    if not path.exists():
        continue
    h = path.read_text(encoding="utf-8")
    check(h == lb.build_index(code), f"{path.name} ({code}) отстал от landing/src")
    check(f'<html lang="{code}">' in h, f"{code}: lang в <html> не {code}")
    canon = f'<link rel="canonical" href="{lb.SITE}/{lb.LANG_DIRS[code]}">'
    check(canon in h, f"{code}: canonical не самоссылающийся")
    # hreflang — связка переводов. Нет её — поисковик считает страницы
    # дублями, а человек не находит свой язык.
    for other in lb.langs():
        link = f'<link rel="alternate" hreflang="{other}" href="{lb.SITE}/{lb.LANG_DIRS[other]}">'
        check(link in h, f"{code}: нет hreflang на «{other}»")
    check('hreflang="x-default"' in h, f"{code}: нет x-default")
    # Мета в своих пределах на КАЖДОМ языке: узбекская фраза длиннее
    # русской на четверть, и предел 60 знаков она переживает не сама.
    t = re.search(r"<title>(.*?)</title>", h).group(1)
    d = re.search(r'<meta name="description" content="(.*?)">', h).group(1)
    check(30 <= len(t) <= 60, f"{code}: title {len(t)} знаков, надо 30–60")
    check(120 <= len(d) <= 160, f"{code}: description {len(d)} знаков, надо 120–160")
    check(h.count("<h1") == 1, f"{code}: H1 не ровно один")
    # Переключатель языка есть на каждой странице и ведёт на все остальные.
    check('class="lang-pick"' in h, f"{code}: нет переключателя языка")
    for other in lb.langs():
        check(f'href="{lb.SITE}/{lb.LANG_DIRS[other]}"' in h, f"{code}: переключатель не ведёт на «{other}»")
    # Название языка — НА НЁМ САМОМ: страницу ищет тот, кто нынешних
    # надписей не читает.
    for other, name in lb.LANG_NAMES.items():
        check(f">{name}</a>" in h, f"{code}: в переключателе нет «{name}» (название языка на нём самом)")
    # Флагов нет: флаг — это страна, а не язык (у английского их два десятка).
    check(not re.search("[\U0001F1E6-\U0001F1FF]", h), f"{code}: эмодзи-флаг в переключателе языка")

    if code == lb.KEY_LANG:
        continue
    # Русских строк в переводе не остаётся. Три исключения названы поимённо:
    # подпись переключателя (она трёхъязычная по построению), «Русский»
    # как название языка на нём самом и пример записи глоссария —
    # настоящая пара RU→EN, которая и должна остаться русской.
    # Список языков формы — названия НА НИХ САМИХ («Қазақша», «Русский»):
    # его читает и тот, кто языка страницы не знает, и кириллица там законна.
    vis = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->|<select.*?</select>", " ", h, flags=re.S)
    ALLOWED = ("Til · Язык · Language", "Русский", "бактериовыделение")
    left = []
    for piece in re.split(r"(<[^>]+>)", vis):
        if not re.search("[А-Яа-яЁё]", piece):
            continue
        if any(a in piece for a in ALLOWED):
            continue
        left.append(piece.strip()[:70])
    check(not left, f"{code}: русские строки в переводе: {left[:3]}")

# ─── 10. Линза: пары, цифры и метка кольца ───────────────────────────
# Линза — это обещание «покажу перевод ИМЕННО на ваш язык», и держится
# оно на трёх вещах: пары есть, в каждой стоят те самые числа, которые
# обещает подпись под ней, и метка на кольце берётся из данных.
check(len(lb.LENS_PAIRS) >= 3, "пар в линзе меньше трёх — выбирать нечего")
for pr in lb.LENS_PAIRS:
    for side in ("src", "tgt"):
        text = " ".join(pr[side])
        # Подпись под линзой обещает «120, 18–65 и 300 мг/сут сверены
        # с оригиналом». Пара без этих чисел сделала бы её враньём ровно
        # в том, что мы продаём.
        for num in ("120", "18", "65", "300"):
            check(num in text, f"пара {pr['label']}: в {side} нет числа {num}")
        check(len(pr[side]) == len(pr["src"]), f"пара {pr['label']}: стороны разной длины")
    check(pr["srcLang"] and pr["tgtLang"], f"пара {pr['label']} без кодов языка")
    check(pr["code"], f"пара {pr['label']} без метки кольца")
# Метка кольца рисуется ИЗ АТРИБУТА: зашитая в CSS `content: "EN"`
# писала бы «EN» на узбекской паре, и поменять её из скрипта нельзя.
css = (ROOT / "landing" / "src" / "styles.css").read_text(encoding="utf-8")
check("content: attr(data-code)" in css, "метка кольца зашита в CSS, а не берётся из data-code")
check('content: "EN"' not in css, "в CSS осталась зашитая метка «EN»")
for code in lb.langs():
    h = (ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")).read_text(encoding="utf-8")
    check("window.LENS_PAIRS" in h, f"{code}: пары линзы не уехали на страницу")
    check(h.count('"srcLang"') == len(lb.LENS_PAIRS), f"{code}: пар на странице не столько, сколько в сборщике")


# ─── 11. Форма перевода на первом экране ─────────────────────────────
# Форма — главное действие страницы. Она обязана работать и без скрипта
# (настоящая форма в приложение с парой языков), и языки в ней — ровно
# каталог сервиса: пара, которой приложение не знает, молча не подставилась
# бы после регистрации.
catalog = {x["code"] for x in lb._languages()}
for code in lb.langs():
    h = (ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")).read_text(encoding="utf-8")
    form = re.search(r'<form class="tr".*?</form>', h, re.S)
    check(form is not None, f"{code}: нет формы перевода")
    if not form:
        continue
    f = form.group(0)
    check(f'action="{lb.APP}/"' in f and 'method="get"' in f, f"{code}: форма не ведёт в приложение")
    check('name="start" value="translate"' in f, f"{code}: форма не несёт start=translate")
    check(f'name="lang" value="{code}"' in f, f"{code}: форма не передаёт язык страницы")
    check(h.index('<form class="tr"') < h.index('id="demo"'), f"{code}: форма не на первом экране")
    for side in ("src", "tgt"):
        sel = re.search(r'<select name="%s".*?</select>' % side, f, re.S).group(0)
        codes = set(re.findall(r'<option value="([^"]+)"', sel))
        check(codes and codes <= catalog, f"{code}: в списке {side} языки вне каталога: {sorted(codes - catalog)[:3]}")
        check(len(codes) == len(catalog), f"{code}: в списке {side} не все языки каталога")
    tgt_sel = re.search(r'<select name="tgt".*?</select>', f, re.S).group(0)
    # Языка ПЕРЕВОДА по умолчанию нет: неверная пара — оплаченный перевод
    # не на тот язык, а человек нажмёт «Перевести», не глядя в список.
    check(" selected" not in tgt_sel and '<option value="">' in tgt_sel, f"{code}: у языка перевода есть умолчание")
    src_sel = re.search(r'<select name="src".*?</select>', f, re.S).group(0)
    check(f'value="{lb.FORM_SRC[code]}" lang' in src_sel and " selected" in src_sel,
          f"{code}: язык оригинала не равен языку страницы")
    check('type="file"' in f and 'name=' not in re.search(r'<input type="file"[^>]*>', f).group(0),
          f"{code}: поле файла с name — имя файла уехало бы в адрес")
    for key in ("tgt", "same", "big", "busy"):
        check(f'data-{key}="' in f, f"{code}: нет надписи ошибки data-{key}")
    check(not lb.FREE_PAGES or "250" in f, f"{code}: форма не называет бесплатный объём")
    # Файл уходит ТОЛЬКО фрейму приложения и только его источнику: postMessage
    # со звёздочкой отдал бы документ человека любому, кто окажется во фрейме.
    js = re.search(r"<script>\n\(function \(\).*?</script>", h, re.S).group(0)
    check('postMessage({ type: "mct-handoff"' in js and "}, APP)" in js, f"{code}: файл уходит не только приложению")
    check('ev.origin !== APP' in js, f"{code}: ответ фрейма не сверяется по источнику")
    check('var APP = "%s"' % lb.APP in js, f"{code}: адрес приложения в скрипте разошёлся со сборщиком")
# Приложение принимает файл той же страницей, куда его шлёт форма, и
# отвечает только лендингу (frontend/handoff.html + LANDING_ORIGINS).
hand = (ROOT / "frontend" / "handoff.html").read_text(encoding="utf-8")
check("__ORIGINS__" in hand and "ALLOWED.indexOf(ev.origin) < 0" in hand, "handoff.html не сверяет источник сообщения")
main_py = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
check(lb.SITE in main_py and '"/handoff"' in main_py, "LANDING_ORIGINS по умолчанию не называет лендинг")

# ─── 12. 404, счётчик, конфиг nginx ──────────────────────────────────
nf = (ROOT / "landing" / "404.html").read_text(encoding="utf-8")
check(nf == lb.build_404(), "404.html отстал от сборки")
check('content="noindex' in nf, "404 не закрыта от индексации")
for code in lb.langs():
    check(f'lang="{code}"' in nf and f'href="{lb.SITE}/{lb.LANG_DIRS[code]}"' in nf, f"404 без блока «{code}»")
conf = (ROOT / "deploy" / "nginx-click.conf").read_text(encoding="utf-8")
check("error_page 404 /404.html" in conf, "nginx не отдаёт свою 404")
check("frame-src" in conf and lb.APP in conf, "CSP лендинга не пускает фрейм приложения")
check("form-action 'self' " + lb.APP in conf, "CSP лендинга не пускает форму в приложение")
check("https://mc.yandex.ru" in conf, "CSP лендинга не пускает Метрику")
for code in lb.langs():
    h = (ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")).read_text(encoding="utf-8")
    check(("mc.yandex.ru/metrika/tag.js" in h) == bool(lb.METRIKA_ID),
          f"{code}: счётчик Метрики стоит без номера или не стоит с номером")
check((ROOT / "landing" / (lb.INDEXNOW_KEY + ".txt")).read_text(encoding="utf-8") == lb.INDEXNOW_KEY,
      "файл ключа IndexNow не совпадает с ключом")


if FAILS:
    for f in FAILS:
        print("FAIL:", f)
    sys.exit(1)
print(f"OK: лендинг — {len(faq_visible)} вопросов FAQ, title {len(title)}, description {len(desc)}, схема из {len(types)} типов")
