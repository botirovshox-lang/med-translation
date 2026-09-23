# -*- coding: utf-8 -*-
"""Бот тест-группы: приём сообщений, выдача доступа, напоминание на третий день.

ОТДЕЛЬНЫЙ ПРОЦЕСС, и это несущее решение — доводы перечислены в `backend/tg.py`.
Коротко: `worker.py` импортирует `main.py`, поэтому опрос, поднятый на импорте,
дал бы ДВА опрашивающих на один токен (Telegram отвечает 409, половина нажатий
обрабатывается дважды); организация запроса живёт в ContextVar, которого
в постороннем потоке нет; STATE — словарь в памяти процесса API.

Поэтому бот ходит в наш же API по HTTP служебным токеном, как обычный клиент,
и своё состояние (кто на каком языке, кому что выдано) держит СВОИМ файлом
в `backend/data/`. В STATE он не пишет ни байта.

Запуск: `python -m backend.tgbot` либо юнит `deploy/medcat-tg.service`.
Нужны `TELEGRAM_BOT_TOKEN`, `TG_SERVICE_TOKEN` (тот же, что у API),
`PUBLIC_BASE_URL`; `TELEGRAM_ADMIN_CHAT` — чтобы владелец видел заявки.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import tg                                    # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
STATE_FILE = DATA / "tg_state.json"

API_BASE = (os.environ.get("INTERNAL_API_URL", "").strip().rstrip("/")
            or "http://127.0.0.1:8000")
SERVICE_TOKEN = os.environ.get("TG_SERVICE_TOKEN", "").strip()

POLL_TIMEOUT = 50          # длинный опрос: Telegram держит соединение сам
TICK_SECONDS = 300         # как часто проверяем, кому пора напомнить
ASK_AFTER_DAYS = 3         # «вы уже протестировали?» — на третий день
ASK_MAX = 10               # сколько раз спрашивать, прежде чем отстать

# ─────────────────────────────────────────────────────────────────────
# Тексты. Оба языка равноправны, дружелюбный тон — просьба владельца.
# Русские и узбекские строки лежат рядом намеренно: правишь одну — видишь
# вторую, и они не расходятся по смыслу.
# ─────────────────────────────────────────────────────────────────────
T = {
    "ru": {
        "hello": "Здравствуйте! 👋\nSimpleTranslate — переводчик документов для переводчиков.\n\n"
                 "Выберите язык, и продолжим на нём.",
        "picked": "Отлично, говорим по-русски. 🙂",
        "menu": "Мы набираем небольшую тест-группу: две недели бесплатной работы на ваших "
                "настоящих текстах — и честный разговор в конце.\n\nЧто дальше?",
        "btnTest": "🚀 Хочу протестировать систему",
        "btnGuide": "📖 Как это работает",
        "btnLang": "🌐 Сменить язык",
        "intro": "SimpleTranslate переводит документ целиком, ведёт ваш глоссарий и возвращает "
                 "готовый .docx в том же оформлении — заголовки, таблицы и картинки остаются "
                 "на местах. Ниже ваш доступ: заполните короткую анкету, загляните в инструкцию "
                 "и приносите свой рабочий файл.",
        "creds": "Ваш доступ\nАдрес: %(site)s\nЛогин: %(login)s\nПароль: %(password)s\n\n"
                 "Пароль лучше сменить в «Профиле» после первого входа.",
        "links": "📋 Анкета (3 минуты): %(apply)s\n📖 Инструкция на одну страницу: %(guide)s",
        # Документы названы в САМОМ сообщении о выдаче доступа: отметку
        # о согласии сервис ставит по факту выдачи, и без этой строки она
        # была бы пустой формой — человек «согласился» с тем, чего не видел.
        "terms": "Пользуясь доступом, вы принимаете оферту %(terms)s и политику обработки "
                 "персональных данных %(privacy)s.\n\nКоротко о главном: текст ваших документов "
                 "уходит на обработку поставщику языковых моделей (OpenAI, США) — не загружайте "
                 "то, что нельзя туда отправлять.",
        "again": "Доступ у вас уже есть — вот он ещё раз. 🙂",
        "full": "Спасибо за интерес! 🙏 Места в этом наборе закончились. Я записал вас "
                "в лист ожидания и напишу первым, как только освободится место.",
        "closed": "Сейчас набор закрыт, но я обязательно напишу, когда откроем следующий. 🙂",
        "err": "Что-то у меня сломалось на ровном месте. 😔 Попробуйте ещё раз через минуту — "
               "если снова не выйдет, я разберусь и напишу сам.",
        "ask": "Здравствуйте! 🙂 Прошло несколько дней — вы уже успели протестировать систему?",
        "askYes": "Да, протестировал(а)",
        "askNo": "Ещё нет",
        "thanksYes": "Отлично, спасибо! 🎉 Тогда самое ценное — ваш разбор. Он короткий, "
                     "5–7 минут, и почти везде достаточно выбрать вариант:\n%(debrief)s\n\n"
                     "Ругаться можно и нужно: именно по этим ответам мы решаем, что чинить первым.",
        "thanksNo": "Понял, не тороплю. 🙂 Тогда я загляну к вам завтра.\n"
                    "Если что-то не получается — просто напишите сюда, помогу.",
        "enough": "Больше напоминать не буду, чтобы не надоедать. 🙂 Ссылка на разбор, "
                  "когда дойдут руки: %(debrief)s",
        "guide": "Инструкция на одну страницу: %(guide)s",
        "unknown": "Я умею немного: выдать доступ, показать инструкцию и позвать на разбор. "
                   "Выберите кнопку ниже 🙂",
    },
    "uz": {
        "hello": "Assalomu alaykum! 👋\nSimpleTranslate — tarjimonlar uchun hujjat tarjimoni.\n\n"
                 "Tilni tanlang, shu tilda davom etamiz.",
        "picked": "Zo'r, o'zbekchada gaplashamiz. 🙂",
        "menu": "Biz kichik sinov guruhi yig'yapmiz: ikki hafta o'z haqiqiy matnlaringiz ustida "
                "bepul ish — va oxirida halol suhbat.\n\nKeyingi qadam?",
        "btnTest": "🚀 Tizimni sinab ko'rmoqchiman",
        "btnGuide": "📖 Bu qanday ishlaydi",
        "btnLang": "🌐 Tilni almashtirish",
        "intro": "SimpleTranslate hujjatni butunlay tarjima qiladi, lug'atingizni yuritadi va "
                 "tayyor .docx faylni o'sha bezakda qaytaradi — sarlavhalar, jadvallar va rasmlar "
                 "joyida qoladi. Quyida kirish ma'lumotlaringiz: qisqa anketani to'ldiring, "
                 "yo'riqnomaga ko'z tashlang va o'z ish faylingizni olib keling.",
        "creds": "Kirish ma'lumotlaringiz\nManzil: %(site)s\nLogin: %(login)s\nParol: %(password)s\n\n"
                 "Birinchi kirgandan keyin parolni «Profil»da almashtirgan ma'qul.",
        "links": "📋 Anketa (3 daqiqa): %(apply)s\n📖 Bir sahifalik yo'riqnoma: %(guide)s",
        "terms": "Kirishdan foydalanib, siz ofertani %(terms)s va shaxsiy ma'lumotlarni qayta "
                 "ishlash siyosatini %(privacy)s qabul qilasiz.\n\nQisqacha eng muhimi: "
                 "hujjatlaringiz matni til modellari yetkazib beruvchisiga (OpenAI, AQSh) qayta "
                 "ishlashga ketadi — u yerga yuborib bo'lmaydigan narsani yuklamang.",
        "again": "Kirish ma'lumotlaringiz allaqachon bor — mana yana bir bor. 🙂",
        "full": "Qiziqishingiz uchun rahmat! 🙏 Bu to'plamda joylar tugadi. Sizni navbatga "
                "yozib qo'ydim va joy bo'shashi bilan birinchi bo'lib yozaman.",
        "closed": "Hozir tanlov yopiq, lekin keyingisini ochganimizda albatta yozaman. 🙂",
        "err": "Menda biror narsa buzildi. 😔 Bir daqiqadan keyin yana urinib ko'ring — "
               "yana chiqmasa, o'zim tekshirib, yozaman.",
        "ask": "Assalomu alaykum! 🙂 Bir necha kun o'tdi — tizimni sinab ko'rishga ulgurdingizmi?",
        "askYes": "Ha, sinab ko'rdim",
        "askNo": "Hali yo'q",
        "thanksYes": "Ajoyib, rahmat! 🎉 Unda eng qimmatlisi — sizning tahlilingiz. U qisqa, "
                     "5–7 daqiqa, deyarli hamma joyda variant tanlash kifoya:\n%(debrief)s\n\n"
                     "Tanqid qilish mumkin va kerak: aynan shu javoblarga qarab nimani birinchi "
                     "tuzatishni hal qilamiz.",
        "thanksNo": "Tushundim, shoshirmayman. 🙂 Unda ertaga yana bir bor so'rayman.\n"
                    "Biror narsa chiqmasa — shu yerga yozing, yordam beraman.",
        "enough": "Boshqa eslatmayman, bezor qilmay. 🙂 Qo'lingiz tekkanda tahlil havolasi: "
                  "%(debrief)s",
        "guide": "Bir sahifalik yo'riqnoma: %(guide)s",
        "unknown": "Men ko'p narsani uddalamayman: kirish berish, yo'riqnomani ko'rsatish va "
                   "tahlilga chaqirish. Quyidagi tugmani tanlang 🙂",
    },
}


def t(lang: str, key: str, **kw) -> str:
    s = T.get(lang, T["uz"]).get(key, "")
    return (s % kw) if kw else s


# ─────────────────────────────────────────────────────────────────────
# Своё состояние. Файлом, потому что процесс отдельный, а данных мало.
# ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        st = {}
    except Exception as e:
        print("[tgbot] состояние не прочитано (%s) — начинаю с чистого" % e, file=sys.stderr)
        st = {}
    st.setdefault("offset", 0)
    st.setdefault("chats", {})
    return st


def save_state(st: dict) -> None:
    """Атомарно: оборванная запись оставила бы бота без памяти о выданных
    доступах, и он выдал бы их второй раз."""
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


# ─────────────────────────────────────────────────────────────────────
# Разговор с нашим API
# ─────────────────────────────────────────────────────────────────────
def api(method: str, path: str, body: dict = None) -> dict:
    url = API_BASE + path
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", "X-Service-Token": SERVICE_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTP %s" % e.code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────
# Клавиатуры
# ─────────────────────────────────────────────────────────────────────
LANG_KB = [[{"text": "🇺🇿 O'zbekcha", "callback_data": "lang:uz"},
            {"text": "🇷🇺 Русский", "callback_data": "lang:ru"}]]


def menu_kb(lang: str) -> list:
    return [[{"text": t(lang, "btnTest"), "callback_data": "want"}],
            [{"text": t(lang, "btnGuide"), "callback_data": "guide"},
             {"text": t(lang, "btnLang"), "callback_data": "lang"}]]


def ask_kb(lang: str) -> list:
    return [[{"text": "✅ " + t(lang, "askYes"), "callback_data": "done:yes"},
             {"text": "🕓 " + t(lang, "askNo"), "callback_data": "done:no"}]]


def links(lang: str, chat_id) -> dict:
    ref = "tg%s" % chat_id
    return {"site": tg.SITE,
            "apply": tg.link("/t/apply?lang=%s&ref=%s" % (lang, ref)),
            "debrief": tg.link("/t/debrief?lang=%s&ref=%s" % (lang, ref)),
            "guide": tg.link("/t/guide?lang=%s" % lang),
            "terms": tg.link("/terms"), "privacy": tg.link("/privacy")}


# ─────────────────────────────────────────────────────────────────────
# Обработка
# ─────────────────────────────────────────────────────────────────────
def chat_rec(st: dict, chat_id) -> dict:
    return st["chats"].setdefault(str(chat_id), {"chat": chat_id, "lang": None})


def issue_access(st: dict, chat_id, rec: dict) -> None:
    """Выдать доступ. Повторное нажатие НЕ заводит вторую учётку — иначе
    человек, нажавший дважды, занял бы два места в наборе."""
    lang = rec.get("lang") or "uz"
    L = links(lang, chat_id)
    if rec.get("login"):
        tg.send(chat_id, t(lang, "again"))
        tg.send(chat_id, t(lang, "creds", site=tg.SITE, login=rec["login"],
                           password=rec.get("password") or "—"))
        tg.send(chat_id, t(lang, "links", **L), menu_kb(lang))
        return
    r = api("POST", "/api/tg/tester", {
        "lang": lang, "chat": chat_id,
        "username": rec.get("username") or "", "name": rec.get("name") or ""})
    if r.get("ok") and r.get("again") and not r.get("password"):
        # Сервер человека помнит, а мы — нет (файл состояния потерян). Пароль
        # у сервера только отпечатком, поэтому просим НОВЫЙ явно: сам он его
        # не сбрасывает — случайное второе нажатие иначе отнимало бы пароль,
        # который человек уже сменил в профиле.
        r = api("POST", "/api/tg/tester", {
            "lang": lang, "chat": chat_id, "reset": True,
            "username": rec.get("username") or "", "name": rec.get("name") or ""})
    if not r.get("ok"):
        why = (r.get("error") or "").lower()
        if r.get("code") == "full":
            rec["waiting"] = True
            tg.send(chat_id, t(lang, "full"))
        elif r.get("code") == "closed":
            rec["waiting"] = True
            tg.send(chat_id, t(lang, "closed"))
        else:
            print("[tgbot] доступ не выдан: %s" % (r.get("error") or why), file=sys.stderr)
            tg.send(chat_id, t(lang, "err"))
        return
    rec["login"] = r["login"]
    rec["password"] = r["password"]
    rec["tenant"] = r.get("tenant")
    rec["issuedAt"] = datetime.now().isoformat(timespec="seconds")
    rec["asks"] = 0
    tg.send(chat_id, t(lang, "intro"))
    tg.send(chat_id, t(lang, "creds", site=tg.SITE, login=rec["login"], password=rec["password"]))
    # Документы называются В САМОМ сообщении о выдаче доступа. Отметку
    # `acceptedTerms` сервис ставит по факту выдачи, и без этой строки она
    # была бы пустой формой: человек «согласился» с тем, чего не видел.
    tg.send(chat_id, t(lang, "terms", **L))
    tg.send(chat_id, t(lang, "links", **L), menu_kb(lang))


def on_start(st: dict, chat_id, user: dict) -> None:
    rec = chat_rec(st, chat_id)
    rec["username"] = user.get("username") or rec.get("username") or ""
    rec["name"] = (" ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
                   or rec.get("name") or "")
    # Язык — ПЕРВЫЙ вопрос и всегда: сервис продаётся в Узбекистане, и угадать
    # язык по настройкам Telegram нельзя — там у половины английский.
    tg.send(chat_id, T["uz"]["hello"] + "\n\n" + T["ru"]["hello"].split("\n\n")[-1], LANG_KB)


def on_callback(st: dict, chat_id, data: str, user: dict) -> None:
    rec = chat_rec(st, chat_id)
    if data == "lang" or data.startswith("lang:"):
        if data == "lang":
            tg.send(chat_id, T["uz"]["hello"], LANG_KB)
            return
        rec["lang"] = "ru" if data.endswith(":ru") else "uz"
        lang = rec["lang"]
        tg.send(chat_id, t(lang, "picked"))
        tg.send(chat_id, t(lang, "menu"), menu_kb(lang))
        return
    lang = rec.get("lang") or "uz"
    if data == "want":
        issue_access(st, chat_id, rec)
    elif data == "guide":
        tg.send(chat_id, t(lang, "guide", **links(lang, chat_id)), menu_kb(lang), preview=True)
    elif data == "done:yes":
        rec["done"] = True
        tg.send(chat_id, t(lang, "thanksYes", **links(lang, chat_id)), preview=True)
        tg.notify_admin("Тестировщик %s (%s) говорит, что протестировал — послана ссылка на разбор."
                        % (rec.get("login") or "?", rec.get("username") or chat_id))
    elif data == "done:no":
        # «Обращусь к вам ещё завтра» — ровно завтра, а не через три дня снова.
        rec["nextAsk"] = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
        tg.send(chat_id, t(lang, "thanksNo"))


def on_text(st: dict, chat_id, text: str, user: dict) -> None:
    rec = chat_rec(st, chat_id)
    if text.startswith("/start") or not rec.get("lang"):
        on_start(st, chat_id, user)
        return
    lang = rec["lang"]
    if text.startswith("/guide"):
        tg.send(chat_id, t(lang, "guide", **links(lang, chat_id)), menu_kb(lang), preview=True)
        return
    # Свободный текст пересылаем владельцу: человек пишет боту, когда что-то
    # не получилось, и потерять это письмо — потерять смысл теста.
    tg.notify_admin("💬 %s (%s):\n%s" % (rec.get("login") or "гость",
                                         rec.get("username") or chat_id, text[:900]))
    tg.send(chat_id, t(lang, "unknown"), menu_kb(lang))


ADMIN_CHAT = os.environ.get("TELEGRAM_ADMIN_CHAT", "").strip()
# Чат поддержки — тот же, что у сервиса (`tg.SUPPORT_CHAT`): один адрес
# на отправку и на приём, иначе ответы ждали бы там, куда вопросы не приходят.
SUPPORT_CHAT = (tg.SUPPORT_CHAT or ADMIN_CHAT or "").strip()
# Кому ПОЗВОЛЕНО отвечать от имени поддержки — числовые id через запятую.
# Пусто — только владелец (`TELEGRAM_ADMIN_CHAT`: в личке его id и есть
# id чата). Список нужен ровно потому, что чат поддержки может быть ГРУППОЙ:
# «чат наш» там больше НЕ значит «пишет владелец» — написать может любой
# участник, и его текст ушёл бы клиенту от имени поддержки.
SUPPORT_SENDERS = {s.strip() for s in
                   os.environ.get("TELEGRAM_SUPPORT_SENDERS", "").split(",") if s.strip()}
# Личка владельца даёт его id ДАРОМ: в приватном чате id чата и есть id
# человека. Но только личка — у группы id ОТРИЦАТЕЛЬНЫЙ и человеком
# не является, и положи мы его сюда, в списке отвечающих не оказалось бы
# ни одного живого человека: отвечать не смог бы НИКТО, включая владельца.
if ADMIN_CHAT.lstrip("-").isdigit() and not ADMIN_CHAT.startswith("-"):
    SUPPORT_SENDERS.add(ADMIN_CHAT)


def _support_chat(chat_id) -> bool:
    return bool(SUPPORT_CHAT) and str(chat_id) == SUPPORT_CHAT


def _may_answer(chat_id, user: dict) -> bool:
    """Вправе ли этот человек отвечать от имени поддержки.

    В ЛИЧКЕ проверка не нужна и стоять не должна: туда пишет тот, чья это
    личка, и список отвечающих там ничего не добавляет — зато пустой
    (никто не назван, а `TELEGRAM_ADMIN_CHAT` оказался группой) он запер бы
    владельца в его собственном чате.

    В ГРУППЕ «чат наш» больше НЕ значит «пишет владелец»: написать может
    любой участник, и его текст ушёл бы клиенту от имени поддержки. Там
    рубеж по ОТПРАВИТЕЛЮ и обязателен; не названного человека не пускаем.
    Список пуст — в группе не отвечает никто, и это честнее, чем пускать
    всех: имена отвечающих задаёт владелец, а не состав чата.
    """
    if ADMIN_CHAT and str(chat_id) == ADMIN_CHAT and not str(chat_id).startswith("-"):
        return True                     # личка владельца — как было до групп
    return bool(SUPPORT_SENDERS) and str((user or {}).get("id") or "") in SUPPORT_SENDERS


def on_admin_reply(chat_id, msg: dict) -> bool:
    """Ответ ВЛАДЕЛЬЦА на сообщение о вопросе в поддержку.

    Возвращает True, если сообщение забрала поддержка, — тогда обычный разбор
    текста его уже не трогает (иначе владелец получал бы в ответ на свой
    ответ меню «выберите язык»).

    Тред опознаётся по МЕТКЕ в цитируемом тексте, и решает это сервер
    (`support.thread_for_reply`): метка — единственная связь между перепиской
    в приложении и перепиской в мессенджере. Не нашлась — говорим об этом
    вслух: ответ, положенный в случайный диалог, прочитал бы чужой человек.

    Читается `reply_to_message`, а НЕ `msg["quote"]`. Это не мелочь:
    с Telegram 7.0 владелец вправе выделить КУСОК сообщения и ответить
    на него — тогда в `quote.text` лежит только выделенное, и метка из него
    пропадёт, хотя в самом сообщении она есть. Ответ уехал бы в никуда
    (404) на ровном месте.

    Рубежей ДВА, и оба нужны именно из-за группы:
      * чат — наш (личка владельца либо чат поддержки);
      * отправитель — из числа тех, кому позволено отвечать.
    """
    if not (_support_chat(chat_id) or (ADMIN_CHAT and str(chat_id) == ADMIN_CHAT)):
        return False
    reply = msg.get("reply_to_message") or {}
    quoted = (reply.get("text") or reply.get("caption") or "")
    if "#d" not in quoted:
        return False                       # это не ответ поддержки — пусть идёт своим путём
    # Цитируемое сообщение обязано быть НАШИМ И НЕ ПЕРЕСЛАННЫМ.
    #
    # В группе метку видят все, и текст с `#d7` может написать кто угодно:
    # участник пишет «смотри тут #d7 непонятно», владелец отвечает ЕМУ —
    # а ответ уходит клиенту седьмого диалога как официальный. Пересланная
    # копия старого уведомления — то же самое, только выглядит настоящей.
    # Поэтому спрашиваем у самого Telegram, кто автор цитируемого: бот ли
    # это и он ли его отправил здесь.
    src = reply.get("from") or {}
    if not src.get("is_bot"):
        return False
    if reply.get("forward_date") or reply.get("forward_origin") or reply.get("forward_from"):
        return False
    # Ответ на СВОЁ ЖЕ подтверждение боту не годится: раньше в нём стояла
    # метка, и «ответить на галочку» отправляло текст клиенту. Метку оттуда
    # убрали, но на старые сообщения в истории чата ответить всё ещё можно —
    # поэтому отсекаем их и по виду. Сравнение по ПЕРВОМУ знаку без
    # вариационного селектора: «⚠️» и «⚠» — один и тот же значок для глаза,
    # а для `startswith` разные строки.
    if quoted.lstrip()[:1] in ("✅", "⚠"):
        return False
    text = (msg.get("text") or "").strip()
    if not text:
        return True
    who = msg.get("from") or {}
    if not _may_answer(chat_id, who):
        # Молчать нельзя: человек думает, что ответил клиенту. Но и отправлять
        # нельзя — он не назван отвечающим.
        tg.send(chat_id, "⚠️ Вы не в списке отвечающих: сообщение клиенту НЕ ушло.\n"
                         "Добавьте свой id в TELEGRAM_SUPPORT_SENDERS.",
                thread_id=msg.get("message_thread_id"))
        return True
    r = api("POST", "/api/tg/support/reply", {
        "quoted": quoted, "text": text,
        "name": (who.get("first_name") or "").strip() or "Поддержка"})
    # Подтверждение идёт БЕЗ метки `#d`: ответ на него самого уходил бы
    # клиенту как новое сообщение поддержки (регулярка метки не отличает
    # цитату вопроса от цитаты подтверждения).
    if r.get("ok"):
        tg.send(chat_id, "✅ Ответ ушёл в приложение (диалог № %s)." % r.get("thread"),
                thread_id=msg.get("message_thread_id"))
    else:
        tg.send(chat_id, "⚠️ Не отправилось: %s\nОтветьте именно на сообщение о вопросе."
                % (r.get("error") or "неизвестная ошибка"),
                thread_id=msg.get("message_thread_id"))
    return True


def _tester_chat(msg_or_chat: dict) -> bool:
    """Годится ли этот чат для ветки ТЕСТ-ГРУППЫ (меню, выдача доступа,
    напоминания).

    Правило одно: только ЛИЧНАЯ переписка. Ветка выдаёт боевой логин
    и пароль (`issue_access` → `/api/tg/tester`) и потом сутками напоминает
    «вы уже протестировали?». В группе это значит, что пароль тестировщика
    прочитают все её участники, а напоминания пойдут в общий чат — поэтому
    вид чата проверяется ДО разбора, а не после.

    Вид берётся у самого Telegram (`chat.type`), а не сравнением id с нашими
    переменными: чат поддержки может быть не назван (`TELEGRAM_SUPPORT_CHAT`
    пуст), а бота могут добавить в любую другую группу — и ни одна из них
    тест-группой не является."""
    return (msg_or_chat.get("type") or "private") == "private"


def handle(st: dict, upd: dict) -> None:
    if "callback_query" in upd:
        cq = upd["callback_query"]
        chat = ((cq.get("message") or {}).get("chat") or {})
        chat_id = chat.get("id")
        tg._post("answerCallbackQuery", {"callback_query_id": cq.get("id")})
        if chat_id and _tester_chat(chat):
            on_callback(st, chat_id, cq.get("data") or "", cq.get("from") or {})
        return
    # Правка своего сообщения ответом НЕ считается: владелец поправил опечатку,
    # а человек получил бы ВТОРОЕ сообщение поддержки — отозвать уже отправленное
    # Telegram не даёт, и «исправил» превращалось бы в «написал дважды».
    edited = upd.get("edited_message")
    msg = upd.get("message") or edited
    if not msg:
        return
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return
    # Ответ владельца в поддержку — ПЕРВЫМ: он приходит обычным текстом,
    # и общий разбор ответил бы на него меню вместо доставки человеку.
    if not edited and on_admin_reply(chat_id, msg):
        return
    # Всё остальное — ветка тест-группы, и она только для лички (см. выше).
    if not _tester_chat(chat):
        return
    on_text(st, chat_id, (msg.get("text") or "").strip(), msg.get("from") or {})


def due_asks(st: dict, submitted: set) -> None:
    """Напоминание на третий день, потом раз в сутки — пока человек не скажет
    «да» либо не заполнит разбор.

    Заполненный разбор снимает вопрос сам: спрашивать «вы уже?» у того, кто
    уже ответил на 15 вопросов, — верный способ показаться назойливым."""
    now = datetime.now()
    for key, rec in list(st["chats"].items()):
        if not rec.get("issuedAt") or rec.get("done"):
            continue
        if ("tg%s" % rec.get("chat")) in submitted:
            rec["done"] = True
            continue
        if rec.get("asks", 0) >= ASK_MAX:
            continue
        try:
            issued = datetime.fromisoformat(rec["issuedAt"])
        except Exception:
            continue
        when = rec.get("nextAsk")
        due = (datetime.fromisoformat(when) if when
               else issued + timedelta(days=ASK_AFTER_DAYS))
        if now < due:
            continue
        lang = rec.get("lang") or "uz"
        rec["asks"] = rec.get("asks", 0) + 1
        if rec["asks"] >= ASK_MAX:
            tg.send(rec["chat"], t(lang, "enough", **links(lang, rec["chat"])), preview=True)
        else:
            tg.send(rec["chat"], t(lang, "ask"), ask_kb(lang))
        rec["nextAsk"] = (now + timedelta(days=1)).isoformat(timespec="seconds")


def main() -> int:
    if not tg.enabled():
        print("[tgbot] нет TELEGRAM_BOT_TOKEN — бот не нужен, выходим", file=sys.stderr)
        return 0
    if not SERVICE_TOKEN:
        print("[tgbot] нет TG_SERVICE_TOKEN — доступ выдавать нечем", file=sys.stderr)
        return 2
    st = load_state()
    print("[tgbot] запущен, чатов в памяти: %d" % len(st["chats"]), file=sys.stderr)
    last_tick = 0.0
    while True:
        r = tg._post("getUpdates", {"offset": st["offset"] + 1, "timeout": POLL_TIMEOUT,
                                    "allowed_updates": ["message", "callback_query"]})
        if r.get("ok"):
            for upd in r.get("result") or []:
                st["offset"] = max(st["offset"], upd.get("update_id", 0))
                try:
                    handle(st, upd)
                except Exception as e:
                    print("[tgbot] обновление %s не обработано: %s" % (upd.get("update_id"), e),
                          file=sys.stderr)
            if r.get("result"):
                save_state(st)
        else:
            print("[tgbot] getUpdates: %s" % r.get("error"), file=sys.stderr)
            time.sleep(5)
        if time.time() - last_tick > TICK_SECONDS:
            last_tick = time.time()
            state = api("GET", "/api/tg/state")
            submitted = set(state.get("submitted") or []) if state.get("ok") else set()
            try:
                due_asks(st, submitted)
            except Exception as e:
                print("[tgbot] напоминания: %s" % e, file=sys.stderr)
            save_state(st)


if __name__ == "__main__":
    sys.exit(main())
