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
3. **Бесплатная страница выбрана ЗЕРНОМ от отпечатка файла**: для человека
   место случайное (не обложка и не оглавление, а страница с текстом и
   вёрсткой), для файла — постоянное. Повторный прогон того же файла даёт
   ту же страницу, то есть «сто раз прогнать свой файл» ничего не приносит.
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


# Какую страницу PDF дарить. Первая страница почти всегда обложка, титул или
# оглавление — образцом перевода она не годится (решение владельца 19.10.2026:
# страница со случайного места, где не меньше `PDF_MIN_WORDS` слов и есть
# ХОТЬ НЕМНОГО вёрстки — картинка, колонки, таблица, заголовки разного кегля).
# Не «где вёрстки больше всего»: образцу хватает показать, что вёрстка
# сохраняется, а самая насыщенная страница — часто схема с тремя словами
# перевода. Нет такой страницы — любая из текстовых.
#
# «Случайно» — для человека, а не для файла: выбор зерном по ОТПЕЧАТКУ
# содержимого (`seed`). Тот же файл даёт ту же страницу при любом числе
# заходов (закон 3 модуля), а другой файл — другое место.
PDF_MIN_WORDS = 200
PDF_SOME_WORDS = 40
PDF_SAMPLE_PAGES = 24        # смотрим не больше стольких страниц: гость анонимен


def _page_stats(page) -> dict:
    """Слова, картинки, колонки, кегли и прямоугольники одной страницы.
    Всё — из слоя и ресурсов, без отрисовки: дёшево и без pdfium."""
    xs, sizes = [], set()

    def vis(text, cm, tm, font, size):
        try:
            if text and text.strip():
                xs.append(float(tm[4]) * float(cm[0]) + float(cm[4]))
                sizes.add(round(float(size or 0) * abs(float(tm[0] or 1)), 1))
        except Exception:
            pass
    try:
        text = page.extract_text(visitor_text=vis) or ""
    except Exception:
        text = ""
    words = len(text.split())
    images = img_bytes = 0
    try:
        xo = ((page.get("/Resources") or {}).get_object().get("/XObject") or {}).get_object()
        for k in list(xo.keys())[:50]:
            o = xo[k].get_object()
            if o.get("/Subtype") == "/Image":
                images += 1
                img_bytes += int(o.get("/Length") or 0)
    except Exception:
        pass
    rects = 0
    try:
        data = page.get_contents().get_data() if page.get_contents() is not None else b""
        rects = data.count(b" re") if len(data) < 4 * 1024 * 1024 else 0
    except Exception:
        pass
    # Колонки: начала строк кучкуются у двух и более левых краёв, далеко друг
    # от друга (межколонник шире ста пунктов).
    starts = {}
    for x in xs:
        b = int(x // 20)
        starts[b] = starts.get(b, 0) + 1
    edges = sorted(b * 20 for b, n in starts.items() if n >= 4)
    cols = 1 + sum(1 for a, b in zip(edges, edges[1:]) if b - a > 100)
    return {"words": words, "images": images, "imgBytes": img_bytes,
            "rects": rects, "cols": cols, "sizes": len(sizes)}


def _layout_score(st: dict) -> int:
    """Сколько признаков вёрстки на странице; больше нуля — «есть вёрстка».
    Число не ранжирует страницы — только отличает их от сплошного текста."""
    s = 0
    s += 3 * min(st["images"], 2)
    s += 2 if st["cols"] >= 2 else 0
    s += 1 if st["rects"] >= 4 else 0          # таблица, плашки
    s += 1 if st["sizes"] >= 3 else 0          # заголовки разного кегля
    return s


def pdf_pick_page(content: bytes, seed: str = "") -> Tuple[bytes, int, int]:
    """PDF → (PDF из одной страницы, всего страниц, номер выбранной с нуля).

    1) среди страниц, где не меньше `PDF_MIN_WORDS` слов и есть хоть
       немного вёрстки, — зерном; нет таких — зерном среди всех текстовых;
    2) таких нет — страница с наибольшим текстом (от `PDF_SOME_WORDS` слов);
    3) текста нет вовсе (скан) — зерном среди страниц с «тяжёлой» картинкой
       (не легче медианы: пустой оборот сжимается в килобайты), не обложка.
    Смотрится не больше `PDF_SAMPLE_PAGES` страниц, выбранных тем же зерном
    по всему файлу. Файл режется ДО разбора — защита единственного воркера
    от чужих 378 страниц. Бросает ValueError, если файл не читается."""
    import random
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
    rng = random.Random(seed or "medcat")
    idx = list(range(total))
    if total > PDF_SAMPLE_PAGES:
        idx = sorted(rng.sample(idx, PDF_SAMPLE_PAGES))
    stats = []
    for i in idx:
        try:
            st = _page_stats(reader.pages[i])
        except Exception:
            continue
        st["i"] = i
        stats.append(st)
    pick = 0
    rich = [s for s in stats if s["words"] >= PDF_MIN_WORDS]
    some = [s for s in stats if s["words"] >= PDF_SOME_WORDS]
    if rich:
        laid = [s["i"] for s in rich if _layout_score(s) > 0]
        pick = rng.choice(laid or [s["i"] for s in rich])
    elif some:
        pick = max(some, key=lambda s: (s["words"], -s["i"]))["i"]
    elif stats:
        pool = [s for s in stats if s["i"] > 0] or stats
        sizes = sorted(s["imgBytes"] for s in pool)
        med = sizes[len(sizes) // 2] if sizes else 0
        heavy = [s["i"] for s in pool if s["imgBytes"] >= med and s["imgBytes"] > 0]
        pick = rng.choice(heavy or [s["i"] for s in pool])
    writer = PdfWriter()
    writer.add_page(reader.pages[pick])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), total, pick
