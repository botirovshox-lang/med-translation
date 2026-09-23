# -*- coding: utf-8 -*-
"""Наглядная инструкция: `/tutorial` — что где нажимать, с рисунками экранов.

Отдельно от `/t/guide` (survey.py) намеренно: та — одна страница на один
экран, её присылает бот тестировщику вместе с доступом, и она отвечает
на вопрос «что это вообще такое». Здесь другой вопрос — «куда нажать»,
и ответ на него длиннее: шаг, рисунок нужного места, подпись под ним.

Три решения, которые стоит знать:

1. **Рисунки — НАШ SVG, а не скриншоты.** Скриншот устаревает молча: облик
   правят чаще, чем инструкцию, и через месяц страница показывает кнопку,
   которой нет, — а заметит это клиент, не разработчик. Схема рисует РОЛЬ
   элемента (большая кнопка внизу, полоса готовности сверху, три корзины),
   и она остаётся верной, пока роль не менялась. Плюс страница не требует
   ни прогона приложения, ни живой учётной записи, ни мегабайтов картинок.
   Цена названа честно: точного облика кнопки здесь нет, и когда понадобится
   именно он — место под настоящий скриншот размечено (`_shot`).

2. **Три языка, и ни один не «главный».** Тексты лежат ОДНИМ деревом
   (`STEPS`), по нему рисуется страница на любом из них; забытый перевод
   виден сразу — ключа не будет, и сборка упадёт на KeyError, а не покажет
   русскую строку на узбекском экране. Тот же закон, что у `tests/test_i18n.js`.

3. **Страница ПУБЛИЧНАЯ и статичная.** Ни одного вызова модели, ни одного
   обращения к STATE, ни одной сессии: на неё ведут ссылки из писем, из бота
   и из самого приложения, и открываться она обязана до входа. Это не `/api/`,
   поэтому в `PUBLIC_API_PATHS` ей места нет (тот же случай, что у `/terms`).
"""

import html

from backend.survey import BRAND, CSS, FONTS, _lang  # облик общий с анкетами

LANGS = ("ru", "uz", "en")


def _pick(lang: str) -> str:
    """Язык страницы. `survey._lang` знает ru/uz; английский добавляем здесь,
    чтобы не трогать чужой разбор и не менять поведение анкет."""
    v = (lang or "").strip().lower()[:2]
    return v if v in LANGS else _lang(lang)


# ─────────────────────────────────────────────────────────────────────
# Рисунки. Каждый — маленькая схема экрана: рамка окна, внутри роль
# элемента и стрелка к нему. Цвета берутся из переменных общего облика,
# поэтому рисунок живёт в светлой и тёмной теме одинаково.
# ─────────────────────────────────────────────────────────────────────

def _svg(body: str, w: int = 420, h: int = 200, label: str = "") -> str:
    return ('<svg class="shot" viewBox="0 0 %d %d" role="img" aria-label="%s">'
            '%s</svg>' % (w, h, html.escape(label), body))


def _win(x, y, w, h, title=""):
    """Рамка окна с полоской заголовка — «это экран приложения»."""
    s = ('<rect x="%d" y="%d" width="%d" height="%d" rx="10" fill="var(--panel-2)" '
         'stroke="var(--stroke)" stroke-width="2"/>'
         '<path d="M%d %dh%dv14a4 4 0 0 1-4 4H%d a4 4 0 0 1-4-4z" fill="var(--panel)"/>'
         % (x, y, w, h, x, y + h - 18, w, x + w))
    if title:
        s += ('<text x="%d" y="%d" class="cap">%s</text>'
              % (x + 12, y + 19, html.escape(title)))
    return s


def _btn(x, y, w, h, text, tone="mint"):
    ink = "var(--mint-ink)" if tone == "mint" else "var(--ink)"
    fill = "var(--%s)" % tone if tone == "mint" else "none"
    stroke = "var(--%s)" % ("mint" if tone == "mint" else "stroke")
    return ('<rect x="%d" y="%d" width="%d" height="%d" rx="9" fill="%s" stroke="%s" '
            'stroke-width="2"/><text x="%d" y="%d" class="btn-t" fill="%s" '
            'text-anchor="middle">%s</text>'
            % (x, y, w, h, fill, stroke, x + w // 2, y + h // 2 + 5, ink, html.escape(text)))


def _arrow(x1, y1, x2, y2):
    """Стрелка «сюда». Рисованная дуга, а не прямая: страница в одном
    облике с анкетами, а там всё от руки."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 18
    return ('<path d="M%.0f %.0f Q%.0f %.0f %.0f %.0f" fill="none" stroke="var(--tan)" '
            'stroke-width="2.5" stroke-linecap="round" marker-end="url(#ar)"/>'
            % (x1, y1, mx, my, x2, y2))


DEFS = ('<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto"><path d="M0 0 10 5 0 10z" fill="var(--tan)"/>'
        '</marker></defs>')


def _row(x, y, w, tone="stroke", h=7):
    return ('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="var(--%s)" opacity=".55"/>'
            % (x, y, w, h, tone))


def shot_upload(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_files"])
    b += ('<rect x="40" y="56" width="340" height="86" rx="12" fill="none" '
          'stroke="var(--mint)" stroke-width="2.5" stroke-dasharray="9 7"/>')
    b += ('<text x="210" y="94" class="mid" text-anchor="middle">%s</text>'
          % html.escape(t["drop"]))
    b += ('<text x="210" y="116" class="sub" text-anchor="middle">%s</text>'
          % html.escape(t["formats"]))
    b += _arrow(300, 166, 250, 146)
    return _svg(b, 420, 196, t["drop"])


def shot_quote(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_files"])
    b += _row(40, 52, 150) + _row(40, 68, 220)
    b += ('<rect x="40" y="92" width="340" height="56" rx="10" fill="var(--mint-soft)" '
          'stroke="var(--mint)" stroke-width="2"/>')
    b += ('<text x="56" y="116" class="sub">%s</text>' % html.escape(t["pages_l"]))
    b += ('<text x="56" y="138" class="big" fill="var(--mint)">%s</text>'
          % html.escape(t["pages_v"]))
    b += ('<text x="364" y="138" class="big" fill="var(--mint)" text-anchor="end">%s</text>'
          % html.escape(t["price_v"]))
    b += _arrow(300, 176, 330, 152)
    return _svg(b, 420, 196, t["pages_l"])


def shot_run(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_editor"])
    for i, wd in enumerate((300, 250, 330, 210)):
        b += _row(40, 50 + i * 15, wd)
    b += _btn(120, 122, 180, 38, t["run_btn"])
    b += _arrow(120, 190, 190, 164)
    return _svg(b, 420, 208, t["run_btn"])


def shot_check(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_check"])
    b += ('<rect x="40" y="48" width="340" height="30" rx="8" fill="var(--panel)" '
          'stroke="var(--stroke)" stroke-width="1.5"/>')
    b += '<rect x="42" y="50" width="258" height="26" rx="7" fill="var(--mint)" opacity=".75"/>'
    b += ('<text x="52" y="69" class="mid" fill="var(--mint-ink)">%s</text>'
          % html.escape(t["ready"]))
    cols = ("mint", "teal", "tan")
    for i, (c, k) in enumerate(zip(cols, ("b_ready", "b_machine", "b_you"))):
        x = 40 + i * 116
        b += ('<rect x="%d" y="92" width="104" height="52" rx="10" fill="var(--panel)" '
              'stroke="var(--%s)" stroke-width="2"/>' % (x, c))
        b += ('<text x="%d" y="115" class="sub" text-anchor="middle">%s</text>'
              % (x + 52, html.escape(t[k])))
        b += ('<text x="%d" y="135" class="big" fill="var(--%s)" text-anchor="middle">%s</text>'
              % (x + 52, c, t[k + "_n"]))
    b += _arrow(250, 176, 316, 150)
    return _svg(b, 420, 196, t["ready"])


def shot_download(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_dl"])
    b += _row(40, 52, 190) + _row(40, 68, 140)
    for i, k in enumerate(("fmt_same", "fmt_docx", "fmt_pdf")):
        x = 40 + i * 116
        tone = "mint" if i == 0 else "stroke"
        b += ('<rect x="%d" y="88" width="104" height="34" rx="9" fill="%s" stroke="var(--%s)" '
              'stroke-width="2"/>'
              % (x, "var(--mint-soft)" if i == 0 else "none", tone))
        b += ('<text x="%d" y="110" class="sub" text-anchor="middle">%s</text>'
              % (x + 52, html.escape(t[k])))
    b += _btn(130, 134, 160, 34, t["dl_btn"])
    b += _arrow(120, 190, 195, 170)
    return _svg(b, 420, 200, t["dl_btn"])


SHOTS = {"upload": shot_upload, "quote": shot_quote, "run": shot_run,
         "check": shot_check, "download": shot_download}


def _shot(key: str, t: dict) -> str:
    """Рисунок шага. Место под НАСТОЯЩИЙ скриншот размечено тут же: положите
    файл в `frontend/img/tutorial-<key>.png`, и он заменит схему — рисунок
    останется запасным, когда картинки нет."""
    fn = SHOTS.get(key)
    return ('<figure class="shot-wrap">%s</figure>' % fn(t)) if fn else ""


# ─────────────────────────────────────────────────────────────────────
# Тексты. Одно дерево на три языка: забытый перевод роняет сборку
# страницы, а не показывает русскую строку на узбекском экране.
# ─────────────────────────────────────────────────────────────────────

UI = {
    "ru": {
        "title": "Как пользоваться", "eyebrow": "Инструкция",
        "h1": "Как перевести документ: пять шагов",
        "lede": "Ниже — весь путь от файла до готового перевода. На каждом шаге "
                "нарисовано то место экрана, куда нужно нажать.",
        "facts": ["Пять шагов", "Без настройки", "Файл возвращается в своём формате"],
        "open": "Открыть сервис", "back": "На главную",
        "win_files": "Проекты", "win_editor": "Перевод", "win_check": "Проверка",
        "win_dl": "Скачать",
        "drop": "Перетащите файл сюда",
        "formats": "Word, PDF, Excel, PowerPoint, сканы",
        "pages_l": "В файле", "pages_v": "40 страниц", "price_v": "$20",
        "run_btn": "Перевести и проверить",
        "ready": "Готово 74%",
        "b_ready": "Готово", "b_ready_n": "612",
        "b_machine": "Доделаю сама", "b_machine_n": "173",
        "b_you": "Спрошу вас", "b_you_n": "42",
        "fmt_same": "Как в оригинале", "fmt_docx": "Word", "fmt_pdf": "PDF",
        "dl_btn": "Скачать перевод",
        "note": "Не получается — напишите в поддержку прямо из приложения: "
                "значок разговора в правом нижнем углу.",
    },
    "uz": {
        "title": "Qanday foydalanish", "eyebrow": "Qo‘llanma",
        "h1": "Hujjatni qanday tarjima qilish: besh qadam",
        "lede": "Quyida fayldan tayyor tarjimagacha bo‘lgan butun yo‘l. Har bir qadamda "
                "ekranning qaysi joyini bosish kerakligi chizilgan.",
        "facts": ["Besh qadam", "Sozlashsiz", "Fayl o‘z formatida qaytadi"],
        "open": "Xizmatni ochish", "back": "Bosh sahifaga",
        "win_files": "Loyihalar", "win_editor": "Tarjima", "win_check": "Tekshiruv",
        "win_dl": "Yuklab olish",
        "drop": "Faylni shu yerga tashlang",
        "formats": "Word, PDF, Excel, PowerPoint, skanlar",
        "pages_l": "Faylda", "pages_v": "40 bet", "price_v": "$20",
        "run_btn": "Tarjima qilish va tekshirish",
        "ready": "Tayyor 74%",
        "b_ready": "Tayyor", "b_ready_n": "612",
        "b_machine": "O‘zim tugataman", "b_machine_n": "173",
        "b_you": "Sizdan so‘rayman", "b_you_n": "42",
        "fmt_same": "Asl ko‘rinishda", "fmt_docx": "Word", "fmt_pdf": "PDF",
        "dl_btn": "Tarjimani yuklab olish",
        "note": "Qiyinchilik bo‘lsa — to‘g‘ridan-to‘g‘ri ilovadan yozing: "
                "pastki o‘ng burchakdagi suhbat belgisi.",
    },
    "en": {
        "title": "How to use it", "eyebrow": "Guide",
        "h1": "How to translate a document: five steps",
        "lede": "Below is the whole path from a file to a finished translation. Each step "
                "shows the part of the screen you need to click.",
        "facts": ["Five steps", "No setup", "The file comes back in its own format"],
        "open": "Open the service", "back": "Home",
        "win_files": "Projects", "win_editor": "Translation", "win_check": "Check",
        "win_dl": "Download",
        "drop": "Drop your file here",
        "formats": "Word, PDF, Excel, PowerPoint, scans",
        "pages_l": "In the file", "pages_v": "40 pages", "price_v": "$20",
        "run_btn": "Translate and check",
        "ready": "Ready 74%",
        "b_ready": "Ready", "b_ready_n": "612",
        "b_machine": "I will finish", "b_machine_n": "173",
        "b_you": "I will ask you", "b_you_n": "42",
        "fmt_same": "As in the original", "fmt_docx": "Word", "fmt_pdf": "PDF",
        "dl_btn": "Download translation",
        "note": "Stuck? Write to support right from the app: the chat icon "
                "in the bottom right corner.",
    },
}

# Шаги: (ключ рисунка, {язык: (заголовок, абзацы…)}). Абзацы — уже HTML,
# потому что в них есть <b>; всё, что приходит извне, здесь не бывает.
STEPS = [
    ("upload", {
        "ru": ("Принесите файл",
               ["Вкладка <b>«Проекты»</b> — перетащите документ в рамку или нажмите её. "
                "Word, PDF, Excel, PowerPoint, HTML, текст, картинки и сканы.",
                "Формат не важен: любой проходит через .docx и возвращается в своём. "
                "Файл читается сразу — видно, сколько в нём страниц."]),
        "uz": ("Faylni keltiring",
               ["<b>«Loyihalar»</b> bo‘limi — hujjatni ramkaga tashlang yoki ustiga bosing. "
                "Word, PDF, Excel, PowerPoint, HTML, matn, rasm va skanlar.",
                "Format muhim emas: har biri .docx orqali o‘tadi va o‘z formatida qaytadi. "
                "Fayl darhol o‘qiladi — unda nechta bet borligi ko‘rinadi."]),
        "en": ("Bring your file",
               ["The <b>Projects</b> tab — drag the document into the frame or click it. "
                "Word, PDF, Excel, PowerPoint, HTML, text, images and scans.",
                "The format does not matter: every one goes through .docx and comes back "
                "in its own. The file is read at once — you see how many pages it holds."]),
    }),
    ("quote", {
        "ru": ("Посмотрите смету",
               ["Цена считается <b>до</b> перевода и после него не меняется. "
                "Страница — это 250 слов оригинала, а не лист бумаги.",
                "Если цифра не подходит — на этом можно остановиться: пока вы не нажали "
                "перевод, ничего не списано."]),
        "uz": ("Hisob-kitobni ko‘ring",
               ["Narx tarjimadan <b>oldin</b> hisoblanadi va keyin o‘zgarmaydi. "
                "Bet — bu qog‘oz varag‘i emas, asl matnning 250 so‘zi.",
                "Raqam to‘g‘ri kelmasa — shu yerda to‘xtash mumkin: tarjimani bosmaguningizcha "
                "hech narsa yechilmaydi."]),
        "en": ("Look at the estimate",
               ["The price is calculated <b>before</b> the translation and does not change "
                "afterwards. A page is 250 words of the source, not a sheet of paper.",
                "If the number does not suit you, you can stop here: nothing is charged "
                "until you press translate."]),
    }),
    ("run", {
        "ru": ("Нажмите одну кнопку",
               ["Вкладка <b>«Перевод»</b>, большая кнопка внизу. Дальше без вас: перевод, "
                "обратный перевод каждой строки, сверка чисел и единиц, глоссарий.",
                "Вкладку можно закрыть — работа идёт на сервере. Вернётесь позже и увидите, "
                "сколько готово."]),
        "uz": ("Bitta tugmani bosing",
               ["<b>«Tarjima»</b> bo‘limi, pastdagi katta tugma. Keyingisi sizsiz: tarjima, "
                "har bir satrning teskari tarjimasi, son va birliklarni solishtirish, lug‘at.",
                "Bo‘limni yopsangiz ham bo‘ladi — ish serverda ketadi. Keyin qaytib, qancha "
                "tayyor bo‘lganini ko‘rasiz."]),
        "en": ("Press one button",
               ["The <b>Translation</b> tab, the big button at the bottom. The rest happens "
                "without you: translation, a back-translation of every line, a check of "
                "numbers and units, the glossary.",
                "You can close the tab — the work runs on the server. Come back later and "
                "see how much is done."]),
    }),
    ("check", {
        "ru": ("Прочитайте, что вышло",
               ["Вкладка <b>«Проверка»</b>: крупный процент готовности и три корзины. "
                "<b>Готово</b> — можно сдавать. <b>Доделаю сама</b> — закроется той же кнопкой. "
                "<b>Спрошу вас</b> — там, где решение за человеком.",
                "Вопросы к вам всегда на понятном вам языке: сравнивается то, что сказано "
                "в книге, и то, что читается обратно из перевода."]),
        "uz": ("Nima chiqqanini o‘qing",
               ["<b>«Tekshiruv»</b> bo‘limi: katta tayyorlik foizi va uchta savat. "
                "<b>Tayyor</b> — topshirsa bo‘ladi. <b>O‘zim tugataman</b> — o‘sha tugma bilan "
                "yopiladi. <b>Sizdan so‘rayman</b> — qaror odam zimmasida bo‘lgan joylar.",
                "Sizga beriladigan savollar doim siz tushunadigan tilda: kitobda aytilgan narsa "
                "va tarjimadan teskari o‘qilgan narsa solishtiriladi."]),
        "en": ("Read what came out",
               ["The <b>Check</b> tab: a large readiness percentage and three baskets. "
                "<b>Ready</b> — you can hand it in. <b>I will finish</b> — the same button "
                "closes it. <b>I will ask you</b> — where the decision belongs to a person.",
                "Questions to you are always in a language you know: what the book says is "
                "compared with what reads back out of the translation."]),
    }),
    ("download", {
        "ru": ("Заберите документ",
               ["Вкладка <b>«Скачать»</b>. <b>«Как в оригинале»</b> — тот же файл со своими "
                "стилями, таблицами, картинками и оглавлением, в нём подменён только текст.",
                "Надписи на картинках переводятся отдельно и возвращаются на свои места; "
                "номера страниц и оглавление пересчитывает сам Word."]),
        "uz": ("Hujjatni oling",
               ["<b>«Yuklab olish»</b> bo‘limi. <b>«Asl ko‘rinishda»</b> — o‘sha faylning o‘zi: "
                "uslublari, jadvallari, rasmlari va mundarijasi joyida, faqat matn almashtirilgan.",
                "Rasmlardagi yozuvlar alohida tarjima qilinib, o‘z joyiga qaytariladi; "
                "bet raqamlari va mundarijani Word o‘zi qayta hisoblaydi."]),
        "en": ("Take the document",
               ["The <b>Download</b> tab. <b>As in the original</b> — the same file with its "
                "own styles, tables, images and table of contents; only the text is replaced.",
                "Captions inside images are translated separately and put back in place; "
                "page numbers and the table of contents are recomputed by Word itself."]),
    }),
]

EXTRA_CSS = r"""
.shot-wrap{margin:14px 0 4px;padding:0}
svg.shot{display:block;width:100%;max-width:440px;height:auto}
svg.shot .cap{font-family:var(--body);font-size:11px;fill:var(--muted)}
svg.shot .sub{font-family:var(--body);font-size:12px;fill:var(--muted)}
svg.shot .mid{font-family:var(--hand);font-size:15px;font-weight:600;fill:var(--ink)}
svg.shot .big{font-family:var(--hand);font-size:17px;font-weight:700}
svg.shot .btn-t{font-family:var(--body);font-size:12.5px;font-weight:700}
.tut-langs{display:flex;gap:7px}
.tut-langs a{font-family:var(--hand);font-size:14px;color:var(--muted);text-decoration:none;
  padding:5px 12px;border:2px solid var(--stroke);border-radius:var(--r-chip)}
.tut-langs a[aria-current]{color:var(--mint-ink);background:var(--mint);border-color:var(--mint)}
.tut-cta{display:flex;flex-wrap:wrap;gap:10px;margin:26px 0 40px}
.tut-cta a{font-family:var(--body);font-weight:700;font-size:15px;text-decoration:none;
  padding:12px 22px;border-radius:var(--r-pill);border:2px solid var(--mint);
  background:var(--mint);color:var(--mint-ink)}
.tut-cta a.ghost{background:none;color:var(--ink);border-color:var(--stroke)}
"""


def page(lang: str = "", app_url: str = "") -> str:
    """Готовая страница. Ни STATE, ни сессии, ни вызовов модели."""
    lang = _pick(lang)
    t = UI[lang]
    segs = "".join('<a href="/tutorial?lang=%s"%s>%s</a>'
                   % (c, ' aria-current="page"' if c == lang else "", c.upper())
                   for c in LANGS)
    out = ['<header class="top"><div class="top-in">'
           '<div class="brand">%s<span>%s</span></div>'
           '<div class="right"><div class="tut-langs">%s</div></div>'
           '</div></header><div class="wrap"><main>' % (BRAND, html.escape(t["title"]), segs)]
    out.append('<section class="lede"><p class="eyebrow">%s</p><h1>%s</h1><p>%s</p>'
               '<ul class="facts">%s</ul></section>'
               % (html.escape(t["eyebrow"]), html.escape(t["h1"]), html.escape(t["lede"]),
                  "".join("<li>%s</li>" % html.escape(f) for f in t["facts"])))
    for i, (key, byl) in enumerate(STEPS):
        head, paras = byl[lang]
        out.append('<section class="step"><div class="q-n"><b class="c%d">%02d</b></div>'
                   '<div><h2>%s</h2>%s%s</div></section>'
                   % (i % 4, i + 1, html.escape(head),
                      "".join("<p>%s</p>" % p for p in paras), _shot(key, t)))
    out.append('<p class="note">%s</p>' % html.escape(t["note"]))
    app = app_url or "https://simpletranslate.me"
    out.append('<div class="tut-cta"><a href="%s">%s</a>'
               '<a class="ghost" href="%s">%s</a></div>'
               % (html.escape(app), html.escape(t["open"]),
                  html.escape(app), html.escape(t["back"])))
    out.append("</main></div>")
    return ("<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\">"
            "<title>%s — %s</title>%s<style>%s%s</style></head><body>%s</body></html>"
            % (lang, html.escape(t["h1"]), BRAND, FONTS, CSS, EXTRA_CSS, "".join(out)))
