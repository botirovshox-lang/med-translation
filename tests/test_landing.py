# -*- coding: utf-8 -*-
"""Лендинг simpletranslate.me (корень сайта с 21.10.2026; прежде click.simpletranslate.me): собранное совпадает с исходниками, а SEO-разметка честна.

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
     без скрипта), заглушки макета нет, файл уходит только в фрейм приложения
     и только его источнику.
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
body = html

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
check('<link rel="canonical" href="https://simpletranslate.me/">' in html, "canonical не самоссылающийся")
if lb.INDEXABLE:
    check('<meta name="robots" content="index, follow' in html, "robots meta не index, follow при INDEXABLE")
else:
    check('<meta name="robots" content="noindex' in html, "robots meta должен быть noindex — сайт закрыт")
check('<html lang="ru"' in html, "lang=ru нет")
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
check("Образцы" in page_text, "отзывы-примеры не помечены как образцы")
click_conf = (ROOT / "deploy" / "nginx-click.conf").read_text(encoding="utf-8")
check("click.simpletranslate.me" in click_conf and "return 301 https://simpletranslate.me$request_uri" in click_conf,
      "прежний адрес click не переводит на simpletranslate.me постоянным переходом")


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
    check(f'<html lang="{code}"' in h, f"{code}: lang в <html> не {code}")
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
    # Переключатель языка — ССЫЛКИ на адреса языков (язык страницы — её адрес).
    sw = re.search(r'<div class="langs".*?</div>', h, re.S)
    check(bool(sw), f"{code}: нет переключателя языка")
    names = {"ru": "Русский", "uz": "O‘zbekcha", "en": "English"}
    for other in lb.langs():
        check(sw and f'href="/{lb.LANG_DIRS[other]}"' in sw.group(0), f"{code}: переключатель не ведёт на «{other}»")
        # Название языка — НА НЁМ САМОМ: страницу ищет тот, кто нынешних надписей не читает.
        check(sw and f">{names[other]}</a>" in sw.group(0), f"{code}: в переключателе нет «{names[other]}»")
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
    # Законная кириллица: название языка на нём самом, обложка оригинала
    # Чехова (пример «Книга») и строка-оригинал в примере проверки цифр.
    ALLOWED = ("Русский", "А. П. Чехов", "Толстый и тонкий", "Принимать по", "300 мг", "2 раза в день")
    left = []
    for piece in re.split(r"(<[^>]+>)", vis):
        if not re.search("[А-Яа-яЁё]", piece):
            continue
        if any(a in piece for a in ALLOWED):
            continue
        left.append(piece.strip()[:70])
    check(not left, f"{code}: русские строки в переводе: {left[:3]}")

# ─── 11. Форма перевода на первом экране ─────────────────────────────
# Форма — главное действие страницы. Она настоящая: без скрипта уводит
# в приложение с намерением и языком страницы, со скриптом отдаёт файл
# фрейму приложения (и только ему). Заглушки макета (MOCK) нет.
for code in lb.langs():
    h = (ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")).read_text(encoding="utf-8")
    form = re.search(r'<form class="tr[^"]*"[^>]*id="tr".*?</form>', h, re.S)
    check(form is not None, f"{code}: нет формы перевода")
    if not form:
        continue
    f = form.group(0)
    check(f'action="{lb.APP}/app"' in f and 'method="get"' in f, f"{code}: форма не ведёт в приложение")
    check('name="start" value="translate"' in f, f"{code}: форма не несёт start=translate")
    check(f'name="lang" value="{code}"' in f, f"{code}: форма не передаёт язык страницы")
    check(h.index('id="tr"') < h.index('id="what"'), f"{code}: форма не на первом экране")
    check('type="file"' in f and 'name=' not in re.search(r'<input[^>]*type="file"[^>]*>', f).group(0),
          f"{code}: поле файла с name — имя файла уехало бы в адрес")
    check('name="tgt"' in f and 'name="src"' in f, f"{code}: нет языков в форме")
    js = h[h.rindex("<script>"):]
    check("MOCK" not in js and "showMock" not in js, f"{code}: в скрипте осталась заглушка макета")
    check('postMessage({ type: "mct-handoff"' in js and "}, APP)" in js, f"{code}: файл уходит не только приложению")
    check('ev.origin !== APP' in js, f"{code}: ответ фрейма не сверяется по источнику")
    check('var APP = "%s"' % lb.APP in js, f"{code}: адрес приложения в скрипте разошёлся со сборщиком")
    check('q.set("from", lang === "ru" ? "index" : lang)' in js, f"{code}: источник регистрации не по странице")
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
# Лендинг и приложение на одном адресе: корень отдаёт nginx статикой,
# заголовки лендинга — одним файлом, включённым в КАЖДЫЙ его location.
app_conf = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
conf = (ROOT / "deploy" / "nginx-landing-headers.conf").read_text(encoding="utf-8")
check("root /opt/med-translation/landing;" in app_conf and "location = / { try_files /index.html" in app_conf,
      "корень сайта не отдаёт лендинг")
check(app_conf.count("include snippets/simpletranslate-landing.conf;") >= 6, "у места лендинга нет его заголовков")
loc_root = app_conf[app_conf.index("    location / {"):]
check('X-Robots-Tag "noindex' in loc_root.split("}")[0], "приложение не закрыто от индексации")
check('add_header X-Robots-Tag' not in app_conf[:app_conf.index("    location")], "noindex на всём сервере закрыл бы лендинг")
check("frame-src 'self'" in conf, "CSP лендинга не пускает фрейм приложения")
check("form-action 'self'" in conf, "CSP лендинга не пускает форму в приложение")
check("https://mc.yandex.ru" in conf, "CSP лендинга не пускает Метрику")
for code in lb.langs():
    h = (ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")).read_text(encoding="utf-8")
    m = h.find("mc.yandex.ru/metrika/tag.js")
    check(h.find('sessionStorage.getItem("mct-token")') != -1 and (m == -1 or h.find('sessionStorage.getItem("mct-token")') < m),
          f"{code}: вошедшего не уводит в приложение ДО Метрики")
for code in lb.langs():
    h = (ROOT / "landing" / (lb.LANG_DIRS[code] + "index.html")).read_text(encoding="utf-8")
    check(("mc.yandex.ru/metrika/tag.js" in h) == bool(lb.METRIKA_ID),
          f"{code}: счётчик Метрики стоит без номера или не стоит с номером")
check((ROOT / "landing" / (lb.INDEXNOW_KEY + ".txt")).read_text(encoding="utf-8") == lb.INDEXNOW_KEY,
      "файл ключа IndexNow не совпадает с ключом")


# ─── 13. Плитки и карусель — одна картинка на перевод ───────────────
# Плитки «Что переводим» и карусель «Фото» показывают переводы одних
# и тех же проектов. Своя копия у плитки собиралась отдельно и отставала
# от правил перерисовки: буквица Чехова с завитком (Х8) осталась на
# плитке, когда в карусели её уже стёрли. Плитка берёт картинки слайда
# (`data-img`), а копии в media/ быть не должно.
st = (ROOT / "landing" / "src" / "home.html").read_text(encoding="utf-8")
media = ROOT / "landing" / "media"
# Медиа — по абсолютному адресу /media/: страница лежит и в /, и в /uz/, /en/.
check('"media/' not in st, "в странице относительный адрес media/ — на /uz/ и /en/ он сломается")
for ref in set(re.findall(r'"/media/([\w.-]+)"', st)):
    check((media / ref).exists(), f"нет файла /media/{ref}")
tl_langs = re.search(r'var TL_LANGS = \[([^\]]*)\]', st)
check(bool(tl_langs), "главная: не нашёл TL_LANGS")
tl_codes = re.findall(r'"([A-Z]{2})"', tl_langs.group(1)) if tl_langs else []
slides = dict(re.findall(r'\{ k: "(\w+)", f: "([\w-]+)"', st))
borrowed = set()
for m in re.finditer(r'<article class="tile[^"]*" data-tile="(\w+)" data-src="(\w+)"([^>]*)>', st):
    k, src, rest = m.groups()
    if k == "video":
        continue
    img = re.search(r'data-img="([\w-]+)"', rest)
    pref = img.group(1) if img else "tile-%s-" % k
    if img:
        borrowed.add(k)
        check(pref in slides.values(), f"главная: плитка {k} ссылается на {pref}, а слайда с ним нет")
    for c in [src] + [c for c in tl_codes if c != src]:
        check((media / (pref + c.lower() + ".webp")).exists(), f"главная: нет картинки плитки {k}: {pref}{c.lower()}.webp")
for f in media.glob("tile-*.webp"):
    k = f.stem.split("-")[1]
    check(k not in slides and k not in borrowed,
          f"главная: {f.name} — копия картинки карусели, плитка обязана брать её (data-img)")


# ── Бренд: знак на сайте и в приложении — тот же, что в паке (tools/brand_build.py)
sys.path.insert(0, str(ROOT / "tools"))
import brand_build as bb  # noqa: E402
pack = ROOT / "brand" / "pack"
check((pack / "web" / "favicon.svg").read_bytes() == (ROOT / "landing" / "favicon.svg").read_bytes(),
      "landing/favicon.svg не совпадает с brand/pack — пересоберите: python tools/brand_build.py --apply")
app = (ROOT / "frontend" / "js" / "app.jsx").read_text(encoding="utf-8")
check(bb.LEG1_B in app and bb.LEG2_B in app,
      "BrandMark в app.jsx разошёлся с геометрией знака в tools/brand_build.py (key(bold=True))")
check('"aria-hidden": "true"' in app.split("function BrandMark", 1)[-1][:400], "BrandMark: знак декоративный, aria-hidden")
for page_ in ("index.html", "uz/index.html", "en/index.html"):
    h = (ROOT / "landing" / page_).read_text(encoding="utf-8")
    check(h.count('aria-label="SimpleTranslate"') >= 2, f"{page_}: у ссылки логотипа нет доступного имени")
    check(h.count('id="st-wm"') == 1 and '#st-wm' in h, f"{page_}: контур надписи на странице должен быть один (<use>)")
    check("#2EE6D0" not in h and "rgba(46,230,208" not in h, f"{page_}: неоновая бирюза вернулась")

if FAILS:
    for f in FAILS:
        print("FAIL:", f)
    sys.exit(1)
print(f"OK: лендинг — {len(faq_visible)} вопросов FAQ, title {len(title)}, description {len(desc)}, схема из {len(types)} типов")
