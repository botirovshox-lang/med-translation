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
  7. robots.txt закрывает сайт целиком (Disallow: / для всех, ни одного Allow):
     лендинг снят с индексации и обхода по решению владельца; sitemap всё ещё
     валиден и содержит страницу и pricing.md (генерится сборкой, но перекрыт
     robots); llms.txt начинается с H1 и цитаты, длина в допуске 30–200 строк.
  8. Тела кнопок без «→» и эмодзи (правила craft floor), все якоря `#…`
     ведут на существующие id, цена «от $0.5» есть в тексте страницы.

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
check('<meta name="robots" content="noindex' in html, "robots meta должен быть noindex — сайт закрыт от индексации")
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
check(locs == [lb.SITE + "/", lb.SITE + "/pricing.md"], f"sitemap: {locs}")
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

# 7. robots / llms — сайт закрыт целиком
robots = (ROOT / "landing" / "robots.txt").read_text(encoding="utf-8")
check("User-agent: *" in robots and "Disallow: /" in robots, "robots.txt не закрывает сайт целиком (нужно User-agent: * + Disallow: /)")
check("Allow: /" not in robots, "robots.txt всё ещё что-то разрешает — сайт должен быть закрыт от ботов")
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

if FAILS:
    for f in FAILS:
        print("FAIL:", f)
    sys.exit(1)
print(f"OK: лендинг — {len(faq_visible)} вопросов FAQ, title {len(title)}, description {len(desc)}, схема из {len(types)} типов")
