"""Гостевой режим: первая страница без регистрации, регистрация — на выгрузке.

Решение владельца сервиса 19.10.2026: человек приходит с лендинга или со
ссылки партнёра, приносит файл (текст, скан, PDF с картинками, видео) и
видит перевод первой страницы БЕЗ учётной записи. Учётная запись нужна
только чтобы СКАЧАТЬ файл: почта → код из письма, пароль — потом.

Здесь — то, что не знает STATE: перечень дверей, открытых гостю, проверка
Cloudflare Turnstile и выбор страницы PDF. Сами двери и записи — раздел
«Гостевой режим» в main.py (инвариант 43 в CLAUDE.md).

Законы, которые нельзя ослаблять:

1. **Гость — настоящая организация и настоящий пользователь с флагом
   `guest`**, а не второй конвейер: перевод, проверки, выгрузка идут той же
   дорогой, что у клиента. Иначе бесплатный образец показывал бы НЕ то,
   что мы продаём.
2. **Гостю открыт БЕЛЫЙ список дверей** (`allowed`). Новая дверь закрыта
   для гостя сама — забыть закрыть нельзя, можно только забыть открыть,
   а это видно сразу.
3. **Бесплатная страница — НАЧАЛО файла**, а не случайный кусок: повторный
   прогон того же файла даёт ту же страницу, то есть «сто раз прогнать
   свой файл» не приносит ничего нового.
4. **Согласие проверяет сервер**: без `accept` гостя нет, а редакция
   документа, время и адрес пишутся на запись — текст уходит поставщикам
   моделей за границу.
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.parse
import urllib.request
from typing import Optional, Tuple

# Двери, открытые гостю: (метод, шаблон пути). Всё остальное под /api/ —
# 403 с просьбой зарегистрироваться. Выгрузки (`/export`) здесь нет
# намеренно: скачать файл — ровно то, ради чего регистрация.
_ALLOWED = [
    ("GET", r"/api/auth/me"),
    ("GET", r"/api/guest/[a-z]+"),
    ("POST", r"/api/guest/[a-z]+"),
    ("GET", r"/api/models"),
    ("POST", r"/api/projects/upload"),
    ("GET", r"/api/upload-progress/[A-Za-z0-9_-]+"),
    ("GET", r"/api/projects/\d+"),
    ("POST", r"/api/projects/\d+/jobs"),
    ("GET", r"/api/jobs"),
    ("GET", r"/api/jobs/\d+"),
    ("POST", r"/api/media/upload"),
    ("GET", r"/api/media/upload/[A-Za-z0-9_-]+"),
    ("DELETE", r"/api/media/upload/[A-Za-z0-9_-]+"),
    ("GET", r"/api/media/upload/[A-Za-z0-9_-]+/probe"),
    ("POST", r"/api/media/upload/[A-Za-z0-9_-]+/(chunk|finish|preview)"),
]
_ALLOWED_RX = [(m, re.compile("^" + p + "$")) for m, p in _ALLOWED]


def allowed(method: str, path: str) -> bool:
    """Открыта ли эта дверь гостю."""
    method = (method or "").upper()
    if method == "HEAD":
        method = "GET"
    return any(m == method and rx.match(path or "") for m, rx in _ALLOWED_RX)


TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_ok(secret: str, token: str, ip: str = "", timeout: float = 8.0) -> Optional[bool]:
    """Проверка Cloudflare Turnstile. True — человек, False — отказ,
    None — проверить не удалось (сеть). Секрета нет — проверки нет (True):
    капча — один из рубежей, а не единственный (потолки по сети и на сутки
    стоят всегда)."""
    if not secret:
        return True
    if not token:
        return False
    data = {"secret": secret, "response": token[:2048]}
    if ip:
        data["remoteip"] = ip
    try:
        req = urllib.request.Request(TURNSTILE_URL, data=urllib.parse.urlencode(data).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8") or "{}")
        return bool(body.get("success"))
    except Exception as e:
        print("[guest] Turnstile не ответил: %s" % e, file=sys.stderr)
        return None


# Сколько слов в слое делают страницу «настоящей»: обложка с названием
# и одной строкой автора образцом перевода не годится — человек хотел
# увидеть, как переведётся ТЕКСТ.
PDF_CONTENT_WORDS = 40
PDF_LOOK_PAGES = 8


def pdf_first_page(content: bytes) -> Tuple[bytes, int, int]:
    """PDF → (PDF из одной страницы, всего страниц, номер выбранной с нуля).

    Берётся первая страница, где в текстовом слое не меньше
    `PDF_CONTENT_WORDS` слов, среди первых `PDF_LOOK_PAGES`; не нашлась
    (скан — слоя нет) — первая. Выбор ДЕТЕРМИНИРОВАННЫЙ: тот же файл
    даёт ту же страницу (закон 3 модуля).

    Заодно это защита сервера: разбор 378 страниц — полминуты единственного
    воркера, а гость анонимен. Бросает ValueError, если файл не читается."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("encrypted")
    total = len(reader.pages)
    if total < 1:
        raise ValueError("empty")
    pick = 0
    for i in range(min(total, PDF_LOOK_PAGES)):
        try:
            words = len((reader.pages[i].extract_text() or "").split())
        except Exception:
            words = 0
        if words >= PDF_CONTENT_WORDS:
            pick = i
            break
    writer = PdfWriter()
    writer.add_page(reader.pages[pick])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), total, pick
