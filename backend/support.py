# -*- coding: utf-8 -*-
"""Диалог с поддержкой: человек пишет в приложении, владелец отвечает из Telegram.

Зачем отдельный модуль, а не двадцать строк в `main.py`: у переписки есть
СВОИ правила хранения, и они расходятся с правилами всего остального
в STATE. Здесь они собраны в одном месте, чтобы их было видно.

Законы, которые нельзя ослаблять:

1. **Диалог ЗА ВХОДОМ.** Анонимной двери наружу нет вовсе: приём анкеты
   (инвариант 23) — единственная неаутентифицированная запись в STATE,
   и заводить вторую ради виджета нельзя. Человек известен, организация
   известна (инвариант 11), потолков частоты по IP не нужно — нужен потолок
   по учётной записи, и он есть (`MSG_PER_HOUR`).

2. **Ключ `support` — ВНЕ `/api/seed`.** Там белый список (инвариант 25),
   поэтому новый верхний ключ туда не уедет сам; но переписка — это ещё
   и почты с текстами чужих организаций, и запись об этом стоит здесь.

3. **Кольцо, а не архив.** Диалог — это `STATE["support"]`: список тредов,
   у треда кольцо сообщений (`THREAD_MAX`), у списка потолок тредов
   (`THREADS_MAX`). `state.json` целиком лежит в памяти и переписывается
   при КАЖДОМ сохранении (инвариант 2), поэтому неограниченная переписка
   означала бы мегабайты записи на каждую правку сегмента.

4. **Ответ владельца приходит В ТОТ ЖЕ тред.** Опознаётся тред по
   `replyTo` в Telegram (бот шлёт сообщение с номером треда в тексте) —
   `thread_for_reply`. Не нашли тред — это не ошибка, а «ответ не в тему»:
   бот скажет об этом человеку, а не запишет ответ в случайный диалог.

5. **Текста клиента в уведомлении ровно столько, сколько он написал сам.**
   Мы не подкладываем в Telegram ни куска его документа: виджет шлёт только
   то, что человек набрал руками.

Отправку в Telegram делает `backend/tg.py` (`notify_admin_async`): это один
запрос, ни потока, ни состояния. Недоступный Telegram диалог не роняет —
сообщение уже записано, владелец увидит его в админке.
"""

import time

# Потолки. Числа не из воздуха: тред на 200 сообщений — это переписка
# на неделю, а 500 тредов — год работы небольшого агентства; выше начинает
# дорожать КАЖДОЕ сохранение состояния, а не только сама переписка.
THREAD_MAX = 200          # сообщений в одном диалоге
THREADS_MAX = 500         # диалогов всего
MSG_MAX_LEN = 4000        # знаков в одном сообщении (Telegram режет на 4096)
MSG_PER_HOUR = 30         # сообщений в час с одной учётной записи

# Кто написал. Строкой, а не булевым флагом: завтра появится ответ
# автоматикой, и `by: "bot"` не потребует миграции боевых данных.
WHO_USER = "user"
WHO_SUPPORT = "support"


def threads(state) -> list:
    return state.setdefault("support", [])


def _now() -> float:
    return time.time()


def thread_of(state, user_id: int, tenant: str) -> dict:
    """Диалог этого человека в ЭТОЙ организации. Пара, а не один id:
    человек состоит в нескольких командах (инвариант 18), и вопрос про
    чужую книгу не должен всплывать у команды, из которой его исключили."""
    for t in threads(state):
        if t.get("user") == user_id and t.get("tenant") == tenant:
            return t
    t = {"id": _next_id(state), "user": user_id, "tenant": tenant,
         "created": _now(), "updated": _now(), "msgs": [], "unread": 0,
         "open": True}
    lst = threads(state)
    lst.append(t)
    # Подрезка по ПОСЛЕДНЕЙ правке, а не по номеру: старый, но живой диалог
    # ценнее заведённого вчера и брошенного.
    if len(lst) > THREADS_MAX:
        lst.sort(key=lambda x: x.get("updated") or 0, reverse=True)
        del lst[THREADS_MAX:]
    return t


def _next_id(state) -> int:
    return max([t.get("id") or 0 for t in threads(state)] or [0]) + 1


def thread_by_id(state, tid: int):
    return next((t for t in threads(state) if t.get("id") == tid), None)


def add_message(thread: dict, who: str, text: str, name: str = "") -> dict:
    """Сообщение в кольцо треда. Возвращает саму запись — её показывают
    в ответе, чтобы браузер нарисовал отправленное без второго запроса."""
    m = {"by": who, "text": text[:MSG_MAX_LEN], "at": _now(), "name": name}
    msgs = thread.setdefault("msgs", [])
    msgs.append(m)
    if len(msgs) > THREAD_MAX:
        del msgs[:len(msgs) - THREAD_MAX]
    thread["updated"] = m["at"]
    if who == WHO_SUPPORT:
        thread["unread"] = (thread.get("unread") or 0) + 1
        thread["open"] = True
    return m


def too_fast(thread: dict) -> bool:
    """Потолок частоты по УЧЁТНОЙ ЗАПИСИ. Считается по самому кольцу —
    отдельный счётчик разошёлся бы с ним при подрезке."""
    edge = _now() - 3600
    mine = [m for m in (thread.get("msgs") or [])
            if m.get("by") == WHO_USER and (m.get("at") or 0) > edge]
    return len(mine) >= MSG_PER_HOUR


def public(thread: dict) -> dict:
    """То, что видит браузер. Имя организации и id человека здесь не нужны:
    он и так знает, кто он."""
    return {"id": thread.get("id"), "open": bool(thread.get("open", True)),
            "unread": thread.get("unread") or 0,
            "msgs": [{"by": m.get("by"), "text": m.get("text") or "",
                      "at": m.get("at"), "name": m.get("name") or ""}
                     for m in (thread.get("msgs") or [])]}


def admin_row(thread: dict, user_name: str = "") -> dict:
    """Строка списка диалогов для владельца сервиса."""
    msgs = thread.get("msgs") or []
    last = msgs[-1] if msgs else {}
    return {"id": thread.get("id"), "user": thread.get("user"),
            "userName": user_name, "tenant": thread.get("tenant"),
            "updated": thread.get("updated"), "open": bool(thread.get("open", True)),
            "count": len(msgs), "last": (last.get("text") or "")[:160],
            "lastBy": last.get("by") or ""}


# Метка треда в тексте сообщения Telegram. По ней `thread_for_reply`
# опознаёт, на что отвечает владелец: это ЕДИНСТВЕННАЯ связь между
# перепиской в STATE и перепиской в мессенджере, и она обязана быть
# устойчивой к переносу строк и к цитированию клиентом.
TAG = "#d"


def tag(thread: dict) -> str:
    return TAG + str(thread.get("id"))


def thread_for_reply(state, quoted_text: str):
    """Тред по тексту сообщения, на которое ответил владелец.

    Ищем метку `#d12` в ЦИТИРУЕМОМ тексте, а не в ответе: владелец пишет
    ответ словами и метку не набирает. Метки нет — возвращаем None,
    и бот скажет «ответьте на сообщение о заявке», а не запишет ответ
    в случайный диалог: чужой человек прочитал бы чужую переписку.
    """
    import re
    m = re.search(re.escape(TAG) + r"(\d+)", quoted_text or "")
    if not m:
        return None
    return thread_by_id(state, int(m.group(1)))


def notify_text(thread: dict, user_name: str, tenant: str, text: str) -> str:
    """Сообщение владельцу. По-русски и СОБРАННОЕ НА СЕРВЕРЕ — оно уходит
    мимо браузера (тот же закон, что у `backend/mail_texts.py` и суточной
    сводки метрик): подставить перевод на границе показа некому."""
    return ("💬 Вопрос в поддержку %s\n\n%s (%s)\n\n%s\n\n"
            "Ответьте на это сообщение — ответ уйдёт человеку в приложение."
            % (tag(thread), user_name or "—", tenant or "—", text))
