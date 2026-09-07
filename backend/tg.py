# -*- coding: utf-8 -*-
"""Telegram: ОТПРАВКА сообщений. Ровно половина работы с ботом, и вот почему
она отделена от второй.

Отправить сообщение — это один HTTPS-запрос: ни потока, ни состояния, ни
подписки. Поэтому уведомления шлёт САМ сервис (заполнена анкета, упал прогон,
кончился лимит) — из того места, где событие и произошло.

ПРИНИМАТЬ сообщения (кнопки, ответы, напоминание на третий день) — работа
совсем другого рода: постоянный опрос Telegram, свой цикл, своё состояние.
Она живёт ОТДЕЛЬНЫМ процессом (`backend/tgbot.py`), и это не стиль, а три
причины из устройства сервиса:

  1. `worker.py` импортирует `main.py`. Поднимись опрос при импорте — на одном
     токене оказалось бы ДВА опрашивающих: Telegram отвечает 409, а половина
     нажатий обрабатывается дважды.
  2. Организация запроса живёт в ContextVar (`CURRENT_SESSION`). В потоке бота
     её нет, и всё, что бот записал бы «от себя», уехало бы в организацию
     `default` — к чужому клиенту.
  3. STATE — глобальный словарь в памяти процесса, и `_sync_shared` подменяет
     разделяемые коллекции целиком из чужого потока. Писать в него из
     постороннего цикла значит воспроизвести ровно ту гонку, ради которой
     заведён `_SAVE_LOCK`.

Отсюда договор: этот модуль умеет только слать и ничего не хранит; бот-процесс
ходит в наш же API по HTTP служебным токеном, как обычный клиент.

Ошибка доставки НЕ роняет вызывающего: уведомление — это удобство, а не
работа сервиса. Молчание при этом видно в журнале, а не проглочено.
"""

import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot%s/%s"

# Токен и адресат — из окружения. В коде их нет и быть не может: токен даёт
# полный доступ к боту, а числовой id владельца — это его личка.
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_CHAT = os.environ.get("TELEGRAM_ADMIN_CHAT", "").strip()

# Публичный адрес сервиса — из него собираются ссылки в сообщениях. Без него
# ссылка была бы относительной, а в Telegram по такой не перейти.
SITE = (os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
        or "https://simpletranslate.me")

TIMEOUT = 12


def enabled() -> bool:
    return bool(BOT_TOKEN)


def _post(method: str, payload: dict, token: str = "", timeout: int = 0) -> dict:
    """Один запрос к Telegram. Возвращает разобранный ответ либо
    {"ok": False, "error": ...} — исключение наружу не выпускаем.

    Потолок по времени задаётся явно, потому что у ДЛИННОГО опроса
    (`getUpdates` с `timeout`) Telegram держит соединение молча до минуты:
    сокет, закрытый раньше, рвёт каждый заход, и журнал забивается
    «read operation timed out» при исправно работающем боте. Ждать надо
    дольше, чем ждёт сам Telegram."""
    tok = token or BOT_TOKEN
    if not tok:
        return {"ok": False, "error": "нет TELEGRAM_BOT_TOKEN"}
    wait = timeout or TIMEOUT
    if not timeout and isinstance(payload.get("timeout"), int):
        wait = payload["timeout"] + 10
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API % (tok, method), data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=wait) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return {"ok": False, "error": "HTTP %s %s" % (e.code, body)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send(chat_id, text: str, keyboard: list = None, token: str = "",
         preview: bool = False) -> dict:
    """Сообщение в чат. Текст режется по потолку Telegram (4096) — иначе
    длинная анкета не доставляется ВООБЩЕ, а молчание неотличимо от поломки.

    Разметку не включаем намеренно: в анкете лежит текст человека, и любая
    незакрытая звёздочка или подчёркивание в нём ломает всё сообщение.
    """
    if not chat_id:
        return {"ok": False, "error": "нет адресата"}
    body = {"chat_id": chat_id, "text": text[:4000],
            "disable_web_page_preview": not preview}
    if keyboard:
        body["reply_markup"] = {"inline_keyboard": keyboard}
    return _post("sendMessage", body, token)


def notify_admin(text: str, keyboard: list = None) -> dict:
    """Уведомление владельцу сервиса. Тихо не работает только в одном
    случае — когда не задан адресат; об этом говорим в журнал один раз."""
    if not ADMIN_CHAT:
        return {"ok": False, "error": "нет TELEGRAM_ADMIN_CHAT"}
    return send(ADMIN_CHAT, text, keyboard)


def notify_admin_async(text: str, keyboard: list = None) -> None:
    """То же, но не задерживая обработчик запроса.

    Отправка — это поход в сеть на секунды. Сделай её в теле запроса — и
    человек, заполнивший анкету, ждёт ответа страницы столько же, а при
    недоступном Telegram получает таймаут вместо «спасибо». Уведомление
    не работа сервиса, и держать ради него клиента нельзя.
    """
    if not (BOT_TOKEN and ADMIN_CHAT):
        return

    def run():
        r = notify_admin(text, keyboard)
        if not r.get("ok"):
            print("[tg] уведомление не доставлено: %s" % r.get("error"), file=sys.stderr)

    threading.Thread(target=run, name="tg-notify", daemon=True).start()


def link(path: str) -> str:
    """Полный адрес нашей страницы. Одно место на всех, чтобы ссылка
    в письме, в боте и в анкете была одной и той же."""
    return SITE + (path if path.startswith("/") else "/" + path)
