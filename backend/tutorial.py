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
    b = DEFS + _win(14, 14, 392, 178, t["win_files"])
    b += ('<rect x="40" y="46" width="340" height="62" rx="12" fill="none" '
          'stroke="var(--mint)" stroke-width="2.5" stroke-dasharray="9 7"/>')
    b += ('<text x="210" y="74" class="mid" text-anchor="middle">%s</text>'
          % html.escape(t["drop"]))
    b += ('<text x="210" y="94" class="sub" text-anchor="middle">%s</text>'
          % html.escape(t["formats"]))
    b += ('<rect x="40" y="122" width="170" height="34" rx="9" fill="var(--panel)" '
          'stroke="var(--stroke)" stroke-width="2"/>'
          '<text x="52" y="144" class="sub">%s</text>' % html.escape(t["lang_pick"]))
    b += _btn(226, 122, 154, 34, t["go_btn"])
    b += _arrow(330, 186, 310, 160)
    return _svg(b, 420, 206, t["drop"])


def shot_quote(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_files"])
    b += _row(40, 52, 150) + _row(40, 68, 220)
    b += ('<rect x="40" y="88" width="340" height="62" rx="10" fill="var(--mint-soft)" '
          'stroke="var(--mint)" stroke-width="2"/>')
    b += ('<text x="56" y="110" class="sub">%s</text>' % html.escape(t["pages_l"]))
    b += ('<text x="56" y="136" class="big" fill="var(--mint)">%s</text>'
          % html.escape(t["pages_v"]))
    b += _btn(262, 104, 104, 32, t["pay_btn"], tone="ink")
    b += _arrow(250, 176, 300, 140)
    return _svg(b, 420, 196, t["pages_l"])


def shot_run(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_editor"])
    for i, wd in enumerate((300, 250, 330)):
        b += _row(40, 50 + i * 15, wd)
    b += ('<rect x="40" y="104" width="340" height="16" rx="8" fill="var(--panel)" '
          'stroke="var(--stroke)" stroke-width="1.5"/>'
          '<rect x="41" y="105" width="196" height="14" rx="7" fill="var(--mint)" opacity=".8"/>')
    b += ('<text x="210" y="142" class="mid" text-anchor="middle">%s</text>'
          % html.escape(t["run_note"]))
    b += _arrow(372, 184, 330, 124)
    return _svg(b, 420, 196, t["run_note"])


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


def shot_media_upload(t):
    b = DEFS + _win(14, 14, 392, 178, t["win_files"])
    b += ('<rect x="40" y="46" width="340" height="62" rx="12" fill="none" '
          'stroke="var(--mint)" stroke-width="2.5" stroke-dasharray="9 7"/>')
    # Значок плёнки: рамка и два ряда перфорации.
    b += ('<rect x="58" y="60" width="44" height="34" rx="5" fill="none" stroke="var(--mint)" '
          'stroke-width="2"/>' + "".join('<rect x="%d" y="%d" width="5" height="4" fill="var(--mint)"/>'
                                         % (63 + i * 9, y) for i in range(4) for y in (63, 87)))
    b += ('<text x="230" y="74" class="mid" text-anchor="middle">%s</text>'
          % html.escape(t["vdrop"]))
    b += ('<text x="230" y="94" class="sub" text-anchor="middle">%s</text>'
          % html.escape(t["vformats"]))
    b += ('<rect x="40" y="122" width="170" height="34" rx="9" fill="var(--panel)" '
          'stroke="var(--stroke)" stroke-width="2"/>'
          '<text x="52" y="144" class="sub">%s</text>' % html.escape(t["lang_pick"]))
    b += _btn(226, 122, 154, 34, t["go_btn"])
    b += _arrow(330, 186, 310, 160)
    return _svg(b, 420, 206, t["vdrop"])


def shot_trim(t):
    b = DEFS + _win(14, 14, 392, 198, t["win_video"])
    b += ('<rect x="40" y="40" width="200" height="104" rx="8" fill="var(--panel)" '
          'stroke="var(--stroke)" stroke-width="2"/>')
    b += ('<rect x="62" y="118" width="156" height="18" rx="4" fill="var(--ink)" opacity=".75"/>'
          '<text x="140" y="131" class="cap" text-anchor="middle" fill="var(--panel-2)" '
          'style="fill:var(--panel-2)">%s</text>' % html.escape(t["sub_sample"]))
    b += ('<text x="256" y="58" class="sub">%s</text>' % html.escape(t["style_l"]))
    for i, wd in enumerate((110, 90, 120)):
        b += _row(256, 70 + i * 16, wd)
    b += ('<rect x="40" y="154" width="340" height="8" rx="4" fill="var(--panel)" '
          'stroke="var(--stroke)" stroke-width="1.5"/>'
          '<rect x="96" y="154" width="200" height="8" rx="4" fill="var(--mint)" opacity=".8"/>'
          '<rect x="92" y="148" width="8" height="20" rx="3" fill="var(--tan)"/>'
          '<rect x="292" y="148" width="8" height="20" rx="3" fill="var(--tan)"/>')
    b += ('<text x="40" y="186" class="sub">%s</text>' % html.escape(t["trim_l"]))
    b += _arrow(352, 210, 300, 172)
    return _svg(b, 420, 226, t["trim_l"])


def shot_cues(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_editor"])
    for i, (tm, wd) in enumerate((("00:02", 230), ("00:07", 260), ("00:12", 200), ("00:19", 240))):
        y = 48 + i * 20
        b += ('<text x="40" y="%d" class="cap">%s</text>' % (y + 7, tm))
        b += _row(86, y, wd)
    b += _btn(130, 132, 160, 34, t["tr_btn"])
    b += _arrow(70, 188, 136, 160)
    return _svg(b, 420, 202, t["tr_btn"])


def shot_video_dl(t):
    b = DEFS + _win(14, 14, 392, 168, t["win_dl"])
    b += _row(40, 52, 190) + _row(40, 68, 140)
    for i, k in enumerate(("fmt_srt", "fmt_vtt", "fmt_burn")):
        x = 40 + i * 116
        on = i == 2
        b += ('<rect x="%d" y="88" width="104" height="34" rx="9" fill="%s" stroke="var(--%s)" '
              'stroke-width="2"/>'
              % (x, "var(--mint-soft)" if on else "none", "mint" if on else "stroke"))
        b += ('<text x="%d" y="110" class="sub" text-anchor="middle">%s</text>'
              % (x + 52, html.escape(t[k])))
    b += _btn(130, 134, 160, 34, t["vdl_btn"])
    b += _arrow(320, 190, 286, 168)
    return _svg(b, 420, 200, t["vdl_btn"])


SHOTS = {"upload": shot_upload, "quote": shot_quote, "run": shot_run,
         "check": shot_check, "download": shot_download,
         "media": shot_media_upload, "trim": shot_trim, "cues": shot_cues,
         "vdownload": shot_video_dl}


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
        "h1": "Как перевести документ или видео",
        "lede": "Ниже — весь путь от файла до готового перевода: отдельно для документов "
                "и отдельно для видео. На каждом шаге нарисовано место экрана, куда нажать.",
        "facts": ["Одна кнопка «Перевести»", "Без настройки", "Файл возвращается в своём формате"],
        "open": "Открыть сервис", "back": "На главную",
        "win_files": "Проекты", "win_editor": "Перевод", "win_check": "Проверка",
        "win_dl": "Скачать",
        "drop": "Перетащите файл сюда",
        "formats": "Word, PDF, Excel, PowerPoint, фото и сканы",
        "lang_pick": "→ Английский", "go_btn": "Перевести", "pay_btn": "Оплатить",
        "run_note": "Переводим и проверяем… 58%",
        "vdrop": "Видео или звук сюда", "vformats": "MP4, MOV, MKV, MP3, WAV…",
        "win_video": "Видео перед переводом", "sub_sample": "Здесь будут субтитры",
        "style_l": "Шрифт, размер, где", "trim_l": "Обрезка: платите только за отрезок",
        "tr_btn": "Перевести", "fmt_srt": ".srt", "fmt_vtt": ".vtt", "fmt_burn": "В кадре",
        "vdl_btn": "Собрать видео",
        "track_doc": "Документы и фото", "track_video": "Видео и звук",
        # Цены на рисунке НЕТ намеренно: суммы в долларах пользователю не
        # показываются нигде (закон в шапке «Жёстких инвариантов», 22а),
        # и рисунок с «$20» врал бы про интерфейс.
        "pages_l": "В файле", "pages_v": "40 страниц",
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
        "h1": "Hujjat yoki videoni qanday tarjima qilish",
        "lede": "Quyida fayldan tayyor tarjimagacha bo‘lgan butun yo‘l: hujjatlar uchun alohida, "
                "video uchun alohida. Har bir qadamda ekranning qaysi joyini bosish chizilgan.",
        "facts": ["Bitta «Tarjima qilish» tugmasi", "Sozlashsiz", "Fayl o‘z formatida qaytadi"],
        "open": "Xizmatni ochish", "back": "Bosh sahifaga",
        "win_files": "Loyihalar", "win_editor": "Tarjima", "win_check": "Tekshiruv",
        "win_dl": "Yuklab olish",
        "drop": "Faylni shu yerga tashlang",
        "formats": "Word, PDF, Excel, PowerPoint, foto va skanlar",
        "lang_pick": "→ Ingliz tili", "go_btn": "Tarjima qilish", "pay_btn": "To‘lash",
        "run_note": "Tarjima va tekshiruv… 58%",
        "vdrop": "Video yoki ovozni shu yerga", "vformats": "MP4, MOV, MKV, MP3, WAV…",
        "win_video": "Tarjimadan oldin video", "sub_sample": "Bu yerda subtitr bo‘ladi",
        "style_l": "Shrift, o‘lcham, joy", "trim_l": "Kesish: faqat shu qism uchun to‘laysiz",
        "tr_btn": "Tarjima qilish", "fmt_srt": ".srt", "fmt_vtt": ".vtt", "fmt_burn": "Kadrga",
        "vdl_btn": "Videoni yig‘ish",
        "track_doc": "Hujjat va foto", "track_video": "Video va ovoz",
        "pages_l": "Faylda", "pages_v": "40 bet",
        "ready": "Tayyor 74%",
        "b_ready": "Tayyor", "b_ready_n": "612",
        "b_machine": "O‘zim tugataman", "b_machine_n": "173",
        "b_you": "Sizdan so‘rayman", "b_you_n": "42",
        "fmt_same": "Asl nusxadagidek", "fmt_docx": "Word", "fmt_pdf": "PDF",
        "dl_btn": "Tarjimani yuklab olish",
        "note": "Qiyinchilik bo‘lsa — to‘g‘ridan-to‘g‘ri ilovadan yozing: "
                "pastki o‘ng burchakdagi suhbat belgisi.",
    },
    "en": {
        "title": "How to use it", "eyebrow": "Guide",
        "h1": "How to translate a document or a video",
        "lede": "Below is the whole path from a file to a finished translation: one for "
                "documents and one for video. Each step shows the part of the screen to click.",
        "facts": ["One “Translate” button", "No setup", "The file comes back in its own format"],
        "open": "Open the service", "back": "Home",
        "win_files": "Projects", "win_editor": "Translation", "win_check": "Check",
        "win_dl": "Download",
        "drop": "Drop your file here",
        "formats": "Word, PDF, Excel, PowerPoint, photos and scans",
        "lang_pick": "→ English", "go_btn": "Translate", "pay_btn": "Pay",
        "run_note": "Translating and checking… 58%",
        "vdrop": "Video or audio here", "vformats": "MP4, MOV, MKV, MP3, WAV…",
        "win_video": "Video before translation", "sub_sample": "Subtitles go here",
        "style_l": "Font, size, position", "trim_l": "Trim: you pay only for this part",
        "tr_btn": "Translate", "fmt_srt": ".srt", "fmt_vtt": ".vtt", "fmt_burn": "Burned in",
        "vdl_btn": "Build the video",
        "track_doc": "Documents and photos", "track_video": "Video and audio",
        "pages_l": "In the file", "pages_v": "40 pages",
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
# Два пути — документы (`STEPS`) и видео (`VIDEO_STEPS`): у них разные
# экраны после загрузки, и один общий список заставлял бы читать про
# субтитры того, кто принёс договор.
STEPS = [
    ("upload", {
        "ru": ("Принесите файл и выберите язык",
               ["Вкладка <b>«Проекты»</b> — перетащите документ в рамку или нажмите её. "
                "Word, PDF, Excel, PowerPoint, HTML, текст, фото и сканы.",
                "Выберите, <b>на какой язык</b> переводим, и нажмите <b>«Перевести»</b>. "
                "Проект заведётся сам, и перевод начнётся сам — вторую кнопку искать не нужно."]),
        "uz": ("Faylni keltiring va tilni tanlang",
               ["<b>«Loyihalar»</b> bo‘limi — hujjatni ramkaga tashlang yoki ustiga bosing. "
                "Word, PDF, Excel, PowerPoint, HTML, matn, foto va skanlar.",
                "<b>Qaysi tilga</b> tarjima qilishni tanlang va <b>«Tarjima qilish»</b>ni bosing. "
                "Loyiha o‘zi ochiladi, tarjima ham o‘zi boshlanadi — ikkinchi tugmani qidirish shart emas."]),
        "en": ("Bring your file and pick the language",
               ["The <b>Projects</b> tab — drag the document into the frame or click it. "
                "Word, PDF, Excel, PowerPoint, HTML, text, photos and scans.",
                "Choose <b>which language</b> to translate into and press <b>Translate</b>. "
                "The project is created and the translation starts on its own — there is no "
                "second button to look for."]),
    }),
    ("quote", {
        "ru": ("Объём и баланс видны сразу",
               ["Файл читается при загрузке — видно, сколько в нём страниц. "
                "Страница — это 250 слов оригинала, а не лист бумаги.",
                "Если страниц на балансе не хватает, рядом будет кнопка <b>«Оплатить»</b>: "
                "пополнение — на вкладке <b>«Оплата»</b> (Click, Payme, карта). Пока перевод "
                "не начался, ничего не списано."]),
        "uz": ("Hajm va balans darhol ko‘rinadi",
               ["Fayl yuklanayotganda o‘qiladi — unda nechta bet borligi ko‘rinadi. "
                "Bet — bu qog‘oz varag‘i emas, asl matnning 250 so‘zi.",
                "Balansda bet yetmasa, yonida <b>«To‘lash»</b> tugmasi chiqadi: to‘ldirish — "
                "<b>«To‘lov»</b> bo‘limida (Click, Payme, karta). Tarjima boshlanmaguncha "
                "hech narsa yechilmaydi."]),
        "en": ("Size and balance are shown at once",
               ["The file is read as it uploads — you see how many pages it holds. "
                "A page is 250 words of the source, not a sheet of paper.",
                "If your balance is short of pages, a <b>Pay</b> button appears next to it: "
                "top-ups live on the <b>Payment</b> tab (Click, Payme, card). Nothing is "
                "charged until the translation starts."]),
    }),
    ("run", {
        "ru": ("Перевод идёт сам",
               ["Вкладка <b>«Перевод»</b> показывает ход: перевод, обратный перевод каждой строки, "
                "сверка чисел и единиц, глоссарий. Любую строку можно поправить прямо в таблице.",
                "Вкладку можно закрыть — работа идёт на сервере. Если перевод не начался "
                "(например, ждал оплаты), там же есть кнопка <b>«Перевести»</b>."]),
        "uz": ("Tarjima o‘zi ketadi",
               ["<b>«Tarjima»</b> bo‘limida jarayon ko‘rinadi: tarjima, har bir satrning teskari "
                "tarjimasi, son va birliklarni solishtirish, lug‘at. Istalgan satrni jadvalning "
                "o‘zida tuzatish mumkin.",
                "Bo‘limni yopsangiz ham bo‘ladi — ish serverda ketadi. Tarjima boshlanmagan bo‘lsa "
                "(masalan, to‘lovni kutgan bo‘lsa), o‘sha yerda <b>«Tarjima qilish»</b> tugmasi bor."]),
        "en": ("The translation runs on its own",
               ["The <b>Translation</b> tab shows the progress: translation, a back-translation "
                "of every line, a check of numbers and units, the glossary. Any line can be "
                "corrected right in the table.",
                "You can close the tab — the work runs on the server. If the translation did "
                "not start (say, it was waiting for payment), the <b>Translate</b> button is there too."]),
    }),
    ("check", {
        "ru": ("Прочитайте, что вышло",
               ["Вкладка <b>«Проверка»</b>: крупный процент готовности и три корзины. "
                "<b>Готово</b> — можно сдавать. <b>Доделаю сама</b> — закроется одной кнопкой. "
                "<b>Спрошу вас</b> — там, где решение за человеком.",
                "Вопросы к вам всегда на понятном вам языке: сравнивается то, что сказано "
                "в книге, и то, что читается обратно из перевода."]),
        "uz": ("Nima chiqqanini o‘qing",
               ["<b>«Tekshiruv»</b> bo‘limi: katta tayyorlik foizi va uchta savat. "
                "<b>Tayyor</b> — topshirsa bo‘ladi. <b>O‘zim tugataman</b> — bitta tugma bilan "
                "yopiladi. <b>Sizdan so‘rayman</b> — qaror odam zimmasida bo‘lgan joylar.",
                "Sizga beriladigan savollar doim siz tushunadigan tilda: kitobda aytilgan narsa "
                "va tarjimadan teskari o‘qilgan narsa solishtiriladi."]),
        "en": ("Read what came out",
               ["The <b>Check</b> tab: a large readiness percentage and three baskets. "
                "<b>Ready</b> — you can hand it in. <b>I will finish</b> — one button "
                "closes it. <b>I will ask you</b> — where the decision belongs to a person.",
                "Questions to you are always in a language you know: what the book says is "
                "compared with what reads back out of the translation."]),
    }),
    ("download", {
        "ru": ("Заберите документ",
               ["Вкладка <b>«Скачать»</b>. <b>«Как в оригинале»</b> — тот же файл со своими "
                "стилями, таблицами, картинками и оглавлением, в нём подменён только текст. "
                "У PDF, фото и сканов — те же страницы, перевод стоит на месте оригинала.",
                "Надписи на картинках переводятся сами и возвращаются на свои места; "
                "перед выдачей файл ещё раз сверяется с оригиналом."]),
        "uz": ("Hujjatni oling",
               ["<b>«Yuklab olish»</b> bo‘limi. <b>«Asl nusxadagidek»</b> — o‘sha faylning o‘zi: "
                "uslublari, jadvallari, rasmlari va mundarijasi joyida, faqat matn almashtirilgan. "
                "PDF, foto va skanlarda — o‘sha betlar, tarjima asl matn o‘rnida turadi.",
                "Rasmlardagi yozuvlar o‘zi tarjima qilinib, o‘z joyiga qaytariladi; "
                "berishdan oldin fayl yana bir bor asl nusxa bilan solishtiriladi."]),
        "en": ("Take the document",
               ["The <b>Download</b> tab. <b>As in the original</b> — the same file with its "
                "own styles, tables, images and table of contents; only the text is replaced. "
                "PDFs, photos and scans keep the same pages, with the translation in place "
                "of the original.",
                "Captions inside images are translated on their own and put back in place; "
                "before it is handed over, the file is checked against the original once more."]),
    }),
]

VIDEO_STEPS = [
    ("media", {
        "ru": ("Принесите видео или звук",
               ["Та же вкладка <b>«Проекты»</b>: перетащите ролик или запись — MP4, MOV, MKV, "
                "MP3, WAV и другие. Выберите язык перевода и нажмите <b>«Перевести»</b>.",
                "Видео считается <b>минутами</b>: неполная минута — минута. Сколько спишется "
                "и сколько на балансе, сказано до подтверждения; пополнить — вкладка <b>«Оплата»</b>."]),
        "uz": ("Video yoki ovozni keltiring",
               ["O‘sha <b>«Loyihalar»</b> bo‘limi: rolik yoki yozuvni tashlang — MP4, MOV, MKV, "
                "MP3, WAV va boshqalar. Tarjima tilini tanlang va <b>«Tarjima qilish»</b>ni bosing.",
                "Video <b>daqiqalar</b> bilan hisoblanadi: to‘liq bo‘lmagan daqiqa — daqiqa. Qancha "
                "yechilishi va balansda qancha borligi tasdiqlashdan oldin aytiladi; to‘ldirish — "
                "<b>«To‘lov»</b> bo‘limi."]),
        "en": ("Bring a video or audio file",
               ["The same <b>Projects</b> tab: drop the clip or recording — MP4, MOV, MKV, "
                "MP3, WAV and more. Choose the target language and press <b>Translate</b>.",
                "Video is counted in <b>minutes</b>: a partial minute counts as a minute. How much "
                "will be charged and what is on your balance is shown before you confirm; top-ups "
                "live on the <b>Payment</b> tab."]),
    }),
    ("trim", {
        "ru": ("Обрежьте лишнее и выберите вид субтитров",
               ["Откроется окно <b>«Видео перед переводом»</b>. Двигайте края полосы — речь "
                "распознаем только на выбранном отрезке, и платите вы только за него.",
                "Тут же — шрифт, размер и место субтитров. Галочка <b>«Прочитать и текст в кадре»</b> "
                "переведёт ещё и надписи, титры, таблички. Нажмите <b>«Подтвердить и распознать речь»</b>."]),
        "uz": ("Ortiqchasini kesing va subtitr ko‘rinishini tanlang",
               ["<b>«Tarjimadan oldin video»</b> oynasi ochiladi. Chiziq chetlarini suring — nutq "
                "faqat tanlangan qismda taniladi va faqat shu qism uchun to‘laysiz.",
                "Shu yerda subtitrning shrifti, o‘lchami va joyi. <b>«Kadrdagi matnni ham o‘qish»</b> "
                "belgisi yozuvlar, titrlar va lavhalarni ham tarjima qiladi. <b>«Tasdiqlash va nutqni "
                "tanish»</b>ni bosing."]),
        "en": ("Trim the extra and choose the subtitle look",
               ["The <b>Video before translation</b> window opens. Drag the ends of the bar — speech "
                "is recognised only on the chosen part, and you pay only for it.",
                "Font, size and position of the subtitles are right there. The <b>Also read on-screen "
                "text</b> box translates captions, titles and signs too. Press <b>Confirm and "
                "recognise speech</b>."]),
    }),
    ("cues", {
        "ru": ("Речь станет строками со временем",
               ["Когда речь распознана, на вкладке <b>«Перевод»</b> появятся строки-фразы с колонкой "
                "<b>«Время»</b>. Нажмите <b>«Перевести»</b> — перевод и проверки пойдут сами.",
                "Строку можно поправить, склеить с соседней или разрезать — тайминг пойдёт за ней. "
                "На экран фраза сама делится на части по правилам языка перевода."]),
        "uz": ("Nutq vaqtli satrlarga aylanadi",
               ["Nutq tanilgach, <b>«Tarjima»</b> bo‘limida <b>«Vaqt»</b> ustunli ibora-satrlar "
                "paydo bo‘ladi. <b>«Tarjima qilish»</b>ni bosing — tarjima va tekshiruvlar o‘zi ketadi.",
                "Satrni tuzatish, qo‘shnisi bilan birlashtirish yoki bo‘lish mumkin — vaqt unga "
                "ergashadi. Ekranda ibora tarjima tili qoidalariga ko‘ra o‘zi qismlarga bo‘linadi."]),
        "en": ("Speech becomes timed lines",
               ["Once the speech is recognised, the <b>Translation</b> tab shows phrase lines with a "
                "<b>Time</b> column. Press <b>Translate</b> — translation and checks run on their own.",
                "A line can be corrected, merged with its neighbour or split — the timing follows it. "
                "On screen a phrase is split into parts by the rules of the target language."]),
    }),
    ("vdownload", {
        "ru": ("Скачайте субтитры или готовое видео",
               ["Вкладка <b>«Скачать»</b>: субтитры <b>.srt</b> и <b>.vtt</b> — только перевод или "
                "оригинал с переводом в каждой реплике.",
                "<b>«Видео с субтитрами в кадре»</b> — для Telegram, соцсетей и браузера. "
                "<b>«Видео с субтитрами дорожкой»</b> — для плееров (VLC, телефон), там субтитры включаются и выключаются. "
                "Озвучка переводом — скоро."]),
        "uz": ("Subtitr yoki tayyor videoni yuklab oling",
               ["<b>«Yuklab olish»</b> bo‘limi: <b>.srt</b> va <b>.vtt</b> subtitrlar — faqat tarjima "
                "yoki har bir replikada asl matn bilan tarjima.",
                "<b>«Subtitrlar kadrga yozilgan video»</b> — Telegram, ijtimoiy tarmoqlar va brauzer uchun. "
                "<b>«Subtitrlar alohida yo‘lakda bo‘lgan video»</b> — pleyerlar uchun (VLC, telefon), u yerda subtitr yoqiladi va "
                "o‘chiriladi. Tarjima bilan ovozlash — tez orada."]),
        "en": ("Download the subtitles or the finished video",
               ["The <b>Download</b> tab: <b>.srt</b> and <b>.vtt</b> subtitles — translation only, or "
                "the original with the translation in every cue.",
                "<b>Video with burned-in subtitles</b> — for Telegram, social networks and the browser. "
                "<b>Video with a subtitle track</b> — for players (VLC, phone), where subtitles switch on and off. "
                "Voice-over in the translation is coming soon."]),
    }),
]

# Ролики к путям. Лежат у лендинга (`landing/media/`, их отдаёт nginx по
# `/media/…` на том же адресе, что и приложение) — второй копии файлов
# не заводим. Документы — запись экрана без монтажа; видео — пример
# результата: тот же ролик с субтитрами на выбранном языке.
VIDEOS = {
    "doc": {"src": "/media/one-click-real.mp4?v=20261018",
            "poster": "/media/one-click-poster.webp?v=20261018",
            "tracks": "/media/one-click-%s.vtt?v=20261018"},
    "video": {"src": "/media/vision-in-space.mp4",
              "poster": "/media/vision-poster.webp",
              "tracks": "/media/vision-in-space-%s.vtt?v=20261026"},
}
VIDEO_NOTE = {
    "ru": {"doc": "Запись экрана без монтажа: от файла до готового перевода за минуту. "
                  "Подписи к ролику — кнопкой CC.",
           "video": "Так выглядит результат: ролик с переведёнными субтитрами. "
                    "Язык субтитров — кнопкой CC."},
    "uz": {"doc": "Montajsiz ekran yozuvi: fayldan tayyor tarjimagacha bir daqiqada. "
                  "Rolik izohlari — CC tugmasi bilan.",
           "video": "Natija shunday ko‘rinadi: tarjima qilingan subtitrli rolik. "
                    "Subtitr tili — CC tugmasi bilan."},
    "en": {"doc": "An unedited screen recording: from a file to a finished translation in a minute. "
                  "Captions — the CC button.",
           "video": "This is what you get: the clip with translated subtitles. "
                    "Subtitle language — the CC button."},
}
LANG_LABEL = {"ru": "Русский", "uz": "Oʻzbekcha", "en": "English"}


def _video(track: str, lang: str) -> dict:
    """Ролик пути для вкладки и страницы: источник, обложка, дорожки
    подписей на трёх языках (по умолчанию — язык читателя) и подпись."""
    v = VIDEOS[track]
    return {"src": v["src"], "poster": v["poster"], "note": VIDEO_NOTE[lang][track],
            "tracks": [{"lang": c, "label": LANG_LABEL[c], "src": v["tracks"] % c,
                        "default": c == lang} for c in LANGS]}


def _video_html(track: str, lang: str) -> str:
    v = _video(track, lang)
    tr = "".join('<track kind="captions" srclang="%s" label="%s" src="%s"%s>'
                 % (t["lang"], html.escape(t["label"]), html.escape(t["src"]),
                    " default" if t["default"] else "") for t in v["tracks"])
    return ('<figure class="tut-video"><video controls muted playsinline preload="none" '
            'poster="%s"><source src="%s" type="video/mp4">%s</video>'
            '<figcaption>%s</figcaption></figure>'
            % (html.escape(v["poster"]), html.escape(v["src"]), tr, html.escape(v["note"])))


# ─────────────────────────────────────────────────────────────────────
# Частые вопросы. Тот же закон, что у шагов: одно дерево на три языка,
# забытый перевод роняет сборку, а не показывает русскую строку.
# Тексты сведены с лендинга намеренно — человек, прочитавший обещание
# на лендинге, обязан найти тот же ответ внутри сервиса; два разных
# ответа на один вопрос хуже одного.
# ─────────────────────────────────────────────────────────────────────

FAQ = [
    {
        "ru": ("Какие форматы можно перевести?",
               "Word (.docx), PDF, Excel, PowerPoint, HTML, текстовые файлы, картинки "
               "и сканы. Любой формат сначала превращается в .docx, переводится, "
               "а потом возвращается в своём. Что теряется при обратной сборке, "
               "названо на файле до оплаты."),
        "uz": ("Qaysi formatlarni tarjima qilish mumkin?",
               "Word (.docx), PDF, Excel, PowerPoint, HTML, matnli fayllar, rasm "
               "va skanlar. Har qanday format avval .docx ga aylantiriladi, tarjima "
               "qilinadi, so‘ng o‘z formatida qaytariladi. Teskari yig‘ishda nima "
               "yo‘qolishi to‘lovdan oldin fayl ustida aytiladi."),
        "en": ("Which formats can be translated?",
               "Word (.docx), PDF, Excel, PowerPoint, HTML, text files, images and "
               "scans. Every format is first converted to .docx, translated and then "
               "returned in its own. Whatever is lost on the way back is stated on "
               "the file before you pay."),
    },
    {
        "ru": ("Сохранится ли оформление?",
               "Да. Перевод пишется в исходный файл, а не собирается заново: стили, "
               "таблицы, рисунки и оглавление остаются на месте, номера страниц "
               "пересчитывает Word. Надписи на картинках переводятся отдельно "
               "и возвращаются на свои места."),
        "uz": ("Hujjat ko‘rinishi saqlanadimi?",
               "Ha. Tarjima qaytadan yig‘ilmaydi, asl faylga yoziladi: uslublar, "
               "jadvallar, rasmlar va mundarija o‘z o‘rnida qoladi, bet raqamlarini "
               "Word qayta hisoblaydi. Rasmlardagi yozuvlar alohida tarjima qilinib, "
               "o‘z joyiga qaytariladi."),
        "en": ("Will the layout be preserved?",
               "Yes. The translation is written into the original file rather than "
               "assembled from scratch: styles, tables, figures and the table of "
               "contents stay in place, and Word recomputes the page numbers. "
               "Captions inside images are translated separately and put back."),
    },
    {
        "ru": ("Нужно ли знать язык перевода?",
               "Нет. Вопросы к вам всегда стоят на вашем языке: сравнивается то, "
               "что сказано в книге, и то, что читается обратно из перевода. "
               "Оценивать сам перевод не требуется, а спорную строку можно отдать "
               "коллеге в команде, который язык знает."),
        "uz": ("Tarjima tilini bilish kerakmi?",
               "Yo‘q. Sizga beriladigan savollar doim siz tushunadigan tilda: "
               "kitobda aytilgan narsa va tarjimadan teskari o‘qilgan narsa "
               "solishtiriladi. Tarjimaning o‘zini baholash talab qilinmaydi, "
               "bahsli satrni esa tilni biladigan jamoadoshingizga berish mumkin."),
        "en": ("Do I need to know the target language?",
               "No. Questions to you are always in a language you know: what the "
               "book says is compared with what reads back out of the translation. "
               "You are not asked to judge the translation itself, and a disputed "
               "line can be handed to a teammate who does know the language."),
    },
    {
        "ru": ("Как считается страница и цена?",
               "Страница — 250 слов исходника, одна норма для всех языков; "
               "для письма без пробелов (китайский, японский) считаются знаки. "
               "Смета считается по файлу до загрузки и после не меняется. "
               "Повторная загрузка того же файла на ту же пару не списывается."),
        "uz": ("Bet va narx qanday hisoblanadi?",
               "Bet — asl matnning 250 so‘zi, barcha tillar uchun bitta me’yor; "
               "probelsiz yozuv (xitoy, yapon) uchun belgilar sanaladi. Hisob-kitob "
               "fayl bo‘yicha yuklashdan oldin qilinadi va keyin o‘zgarmaydi. "
               "O‘sha faylni o‘sha juftlikka qayta yuklash uchun hisobdan yechilmaydi."),
        "en": ("How are a page and the price calculated?",
               "A page is 250 words of the source, one standard for every language; "
               "for scripts without spaces (Chinese, Japanese) characters are counted. "
               "The estimate is calculated from the file before the upload and does "
               "not change. Uploading the same file again for the same pair is free."),
    },
    {
        "ru": ("Как пополнить баланс?",
               "Вкладка «Оплата»: сколько страниц и минут осталось, пополнение "
               "в три шага (сколько купить, как заплатить — Click, Payme или "
               "карта, — согласие с офертой) и кнопка «Оплатить». Ниже, отдельно, — "
               "история: ваши заказы и куда ушли страницы."),
        "uz": ("Balansni qanday to‘ldirish mumkin?",
               "«To‘lov» bo‘limi: qancha bet va daqiqa qolgani, uch qadamda "
               "to‘ldirish (qancha sotib olish, qanday to‘lash — Click, Payme yoki "
               "karta, — oferta bilan rozilik) va «To‘lash» tugmasi. Pastda, alohida, — "
               "tarix: buyurtmalaringiz va betlar qayerga ketgani."),
        "en": ("How do I top up my balance?",
               "The Payment tab: how many pages and minutes are left, a three-step "
               "top-up (how much to buy, how to pay — Click, Payme or card — and "
               "agreeing to the offer) and the Pay button. Below, separately, is "
               "the history: your orders and where the pages went."),
    },
    {
        "ru": ("Можно ли перевести видео?",
               "Да: видео и звук загружаются на той же вкладке «Проекты». Речь "
               "распознаётся в строки со временем, переводится, и вы скачиваете "
               "субтитры .srt/.vtt или готовое видео с субтитрами в кадре. Можно "
               "перевести и надписи в кадре. Считается минутами выбранного отрезка."),
        "uz": ("Videoni tarjima qilsa bo‘ladimi?",
               "Ha: video va ovoz o‘sha «Loyihalar» bo‘limida yuklanadi. Nutq vaqtli "
               "satrlarga aylantiriladi, tarjima qilinadi va siz .srt/.vtt "
               "subtitrlarni yoki subtitrlari kadrga yozilgan tayyor videoni yuklab "
               "olasiz. Kadrdagi yozuvlarni ham tarjima qilish mumkin. Tanlangan "
               "qismning daqiqalari bilan hisoblanadi."),
        "en": ("Can I translate a video?",
               "Yes: video and audio are uploaded on the same Projects tab. Speech "
               "becomes timed lines, gets translated, and you download .srt/.vtt "
               "subtitles or a finished video with burned-in subtitles. On-screen "
               "text can be translated too. Billing is by minutes of the chosen part."),
    },
    {
        "ru": ("Сколько ждать?",
               "Статья на 10 страниц готова за минуты, книга на 300 страниц — "
               "за часы, а не за недели. Вкладку можно закрыть: работа идёт "
               "на сервере, а результат будет ждать в проекте вместе со списком "
               "вопросов, если они появились."),
        "uz": ("Qancha kutish kerak?",
               "10 betlik maqola daqiqalarda, 300 betlik kitob esa haftalar emas, "
               "soatlarda tayyor bo‘ladi. Bo‘limni yopsangiz bo‘ladi: ish serverda "
               "ketadi, natija esa savollar ro‘yxati bilan birga loyihada kutib "
               "turadi."),
        "en": ("How long does it take?",
               "A 10-page article is ready in minutes, a 300-page book in hours "
               "rather than weeks. You can close the tab: the work runs on the "
               "server, and the result waits in the project together with a list "
               "of questions, if any came up."),
    },
    {
        "ru": ("Что происходит с моими документами?",
               "Текст документа уходит поставщику языковой модели для перевода "
               "и проверок; это прямо сказано в политике персональных данных. "
               "Файлы хранятся в вашей организации и недоступны другим клиентам. "
               "Проект можно удалить вместе с файлами в любой момент."),
        "uz": ("Hujjatlarim bilan nima bo‘ladi?",
               "Hujjat matni tarjima va tekshiruvlar uchun til modeli yetkazib "
               "beruvchisiga yuboriladi; bu shaxsiy ma’lumotlar siyosatida ochiq "
               "aytilgan. Fayllar sizning tashkilotingizda saqlanadi va boshqa "
               "mijozlarga ochiq emas. Loyihani fayllari bilan istalgan vaqtda "
               "o‘chirish mumkin."),
        "en": ("What happens to my documents?",
               "The text of the document is sent to the language model provider for "
               "translation and checks; this is stated plainly in the privacy policy. "
               "Files are stored inside your own organisation and are not available "
               "to other customers. A project can be deleted with its files at any time."),
    },
]

# Надписи вкладки «Обучение» — те, которых нет у страницы. Отдельно
# от UI намеренно: у страницы своя шапка и свои кнопки («Открыть сервис»,
# «На главную»), а внутри сервиса они бессмысленны — человек уже внутри.
TAB_UI = {
    "ru": {
        "h1": "Обучение",
        "lede": "Весь путь от файла до готового перевода — отдельно для документов "
                "и для видео. Короткий ролик, потом шаги с рисунком экрана.",
        "faqHead": "Частые вопросы",
        "tour": "Показать знакомство заново",
        "tourNote": "Короткий тур по интерфейсу: четыре шага с подсветкой кнопок.",
        "support": "Написать в поддержку",
        "supportNote": "Не получается — напишите, мы читаем каждое сообщение.",
        "print": "Открыть отдельной страницей",
        "printNote": "Версия для печати и для коллеги, у которого ещё нет доступа.",
        "step": "Шаг",
    },
    "uz": {
        "h1": "O‘rganish",
        "lede": "Fayldan tayyor tarjimagacha bo‘lgan butun yo‘l — hujjatlar va video "
                "uchun alohida. Avval qisqa rolik, so‘ng ekran rasmi bilan qadamlar.",
        "faqHead": "Ko‘p beriladigan savollar",
        "tour": "Tanishuvni qaytadan ko‘rsatish",
        "tourNote": "Interfeys bo‘ylab qisqa sayr: tugmalar yoritilgan to‘rt qadam.",
        "support": "Qo‘llab-quvvatlashga yozish",
        "supportNote": "Qiyinchilik bo‘lsa — yozing, biz har bir xabarni o‘qiymiz.",
        "print": "Alohida sahifada ochish",
        "printNote": "Chop etish uchun va hali ruxsati yo‘q hamkasb uchun versiya.",
        "step": "Qadam",
    },
    "en": {
        "h1": "Learn",
        "lede": "The whole path from a file to a finished translation — separately for "
                "documents and for video. A short clip first, then steps with a screen sketch.",
        "faqHead": "Common questions",
        "tour": "Show the intro again",
        "tourNote": "A short tour of the interface: four steps with the buttons highlighted.",
        "support": "Message support",
        "supportNote": "Stuck? Write to us — we read every message.",
        "print": "Open as a separate page",
        "printNote": "A version to print, or to send a colleague who has no access yet.",
        "step": "Step",
    },
}


def content(lang: str = "") -> dict:
    """Содержание инструкции для ВКЛАДКИ приложения.

    Источник один и тот же — `STEPS`, `UI`, `FAQ` этого модуля, — поэтому
    правка текста меняет и страницу `/tutorial`, и вкладку. Вторая копия
    в `.jsx` разошлась бы с первой же правкой, а расхождение здесь значит,
    что инструкция врёт про наш же интерфейс.

    Рисунки уходят ГОТОВЫМ SVG: их собирает тот же код, что и для страницы
    (`_shot`), и повторять построение рамок и стрелок в браузере значило бы
    держать два рисовальщика на одну схему. Браузеру остаётся вставить
    разметку и покрасить её своими переменными — цвета в SVG заданы через
    `var(--…)`, поэтому в светлой и тёмной теме он живёт сам.
    """
    lang = _pick(lang)
    t, tab = UI[lang], TAB_UI[lang]

    def steps(lst):
        return [{"key": key, "title": byl[lang][0], "paras": byl[lang][1], "svg": _shot(key, t)}
                for key, byl in lst]

    doc = steps(STEPS)
    return {
        "lang": lang,
        "h1": tab["h1"], "lede": tab["lede"],
        "facts": t["facts"],
        "stepWord": tab["step"],
        # `steps` — путь документа: его читают ассистент поддержки и прежняя
        # вкладка; оба пути целиком — в `tracks`.
        "steps": doc,
        "tracks": [
            {"key": "doc", "label": t["track_doc"], "video": _video("doc", lang), "steps": doc},
            {"key": "video", "label": t["track_video"], "video": _video("video", lang),
             "steps": steps(VIDEO_STEPS)},
        ],
        "faqHead": tab["faqHead"],
        "faq": [{"q": item[lang][0], "a": item[lang][1]} for item in FAQ],
        "actions": {
            "tour": tab["tour"], "tourNote": tab["tourNote"],
            "support": tab["support"], "supportNote": tab["supportNote"],
            "print": tab["print"], "printNote": tab["printNote"],
        },
    }


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
.tut-track{margin:34px 0 6px;font-family:var(--hand);font-size:26px}
.tut-video{margin:10px 0 18px}
.tut-video video{display:block;width:100%;max-width:720px;height:auto;border-radius:12px;
  border:2px solid var(--stroke);background:#000}
.tut-video figcaption{font-size:14px;color:var(--muted);margin-top:6px}
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
    for track, lst in (("doc", STEPS), ("video", VIDEO_STEPS)):
        out.append('<h2 class="tut-track">%s</h2>%s'
                   % (html.escape(t["track_" + track]), _video_html(track, lang)))
        for i, (key, byl) in enumerate(lst):
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
