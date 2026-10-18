# -*- coding: utf-8 -*-
"""Яндекс Vision OCR — второй читатель надписей на картинках (Ш5 плана
`docs/plans/ocr-paint-tools.md`).

Зачем, если читает зрячая модель:
  * **запасной читатель** — модель не ответила (сбой поставщика, пустой
    счёт, обрыв): блок оставался нерешённым до следующего платного захода;
  * **рукопись** (Ф8): зрячая модель читает почерк правдоподобными
    заменами («наиболее просто» → «гораздо проще»), а у Vision есть
    отдельная модель распознавания рукописи. Брать ли её текст вместо
    текста модели, решает `YANDEX_VISION_HAND` — по замеру, а не на веру.

Законы:
  * ключ — `YANDEX_VISION_API_KEY` (ключ сервисного аккаунта с ролью
    `ai.vision.user`), каталог берётся из аккаунта, `YANDEX_VISION_FOLDER` —
    если ключ не привязан к каталогу. Нет ключа — модуля нет, отказа нет;
  * запрос идёт НАПРЯМУЮ, мимо `HTTPS_PROXY` окружения: прокси нужен
    зарубежным поставщикам, а гнать картинку клиента к российскому сервису
    через третью страну незачем;
  * признаков «надпись аппарата» (`overlay`), «засечки» Vision не даёт —
    они остаются False, и это сказано: отсев фамилий на снимках держит
    `image_text.is_noise` и решение человека;
  * текст ключа не уходит ни в журнал, ни в ответ: в ошибке только код HTTP;
  * деньги — поштучно (`perUnit` в `AUX_MODEL_PRICES` у вызывающего).
"""
from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request

# Адрес по нынешней документации (прежний ocr.api.cloud.yandex.net отвечает так же).
URL = os.environ.get("YANDEX_VISION_URL", "https://ai.api.cloud.yandex.net/ocr/v1/recognizeText")
KEY = os.environ.get("YANDEX_VISION_API_KEY", "").strip()
FOLDER = os.environ.get("YANDEX_VISION_FOLDER", "").strip()
TIMEOUT = float(os.environ.get("YANDEX_VISION_TIMEOUT", "40"))
# Языки, для которых у Vision есть модель рукописи (документация Yandex
# Cloud: «handwritten» — русский и английский); прочие идут моделью «page».
HAND_LANGS = {"ru", "en"}
# Сторона картинки Vision — не больше 20 Мп и 10 МБ; блок мы шлём
# вырезкой, но страницу скана — целиком.
MAX_BYTES = 10 * 1024 * 1024


class VisionError(Exception):
    """Отказ сервиса: `code` — HTTP, `stop` — повторять бессмысленно
    (ключ, права, квота), иначе — можно повторить позже."""

    def __init__(self, code: int, stop: bool):
        super().__init__("vision %s" % code)
        self.code = code
        self.stop = stop


def available() -> bool:
    return bool(KEY)


def can_hand(lang: str) -> bool:
    """Есть ли у Vision модель рукописи для языка."""
    return _lang(lang) in HAND_LANGS


def _lang(code: str) -> str:
    """ISO 639-1 в нижнем регистре: «UZ-CYRL» → «uz», «RU» → «ru»."""
    return (code or "").split("-")[0].strip().lower()


def _opener():
    # Пустой ProxyHandler — мимо HTTPS_PROXY окружения (см. шапку).
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _jpeg(img_bytes: bytes) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes))
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, "white")
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


def recognize(img_bytes: bytes, lang: str, hand: bool = False) -> dict:
    """Прочитать картинку целиком. {"text", "lines": [{"text", "box"}],
    "model"}; отказ — VisionError, сбой сети — OSError."""
    if not KEY:
        raise VisionError(0, True)
    data = _jpeg(img_bytes)
    if len(data) > MAX_BYTES:
        raise VisionError(413, False)
    lg = _lang(lang)
    if not lg:
        raise VisionError(400, False)        # язык не знаем — «*» у модели page не описан
    model = "handwritten" if hand and lg in HAND_LANGS else "page"
    body = {"mimeType": "JPEG", "languageCodes": [lg],
            "model": model, "content": base64.b64encode(data).decode()}
    head = {"Content-Type": "application/json", "Authorization": "Api-Key " + KEY}
    if FOLDER:
        head["x-folder-id"] = FOLDER
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=head)
    try:
        with _opener().open(req, timeout=TIMEOUT) as r:
            ans = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 401/403 — ключ или права: повторять бессмысленно. 400 — этот кроп,
        # 429 — частота: следующий запрос может пройти.
        raise VisionError(e.code, e.code in (401, 403))
    return parse(ans, model)


def parse(ans: dict, model: str = "") -> dict:
    """Ответ Vision → строки с рамками в точках картинки."""
    # Ответ бывает в обёртке `result` (прежняя версия API) и без неё.
    ans = ans or {}
    ta = (ans.get("result") or ans).get("textAnnotation") or {}
    lines = []
    for bl in ta.get("blocks") or []:
        for ln in bl.get("lines") or []:
            t = (ln.get("text") or "").strip()
            if not t:
                continue
            vs = ((ln.get("boundingBox") or {}).get("vertices")) or []
            xs = [int(float(v.get("x") or 0)) for v in vs]
            ys = [int(float(v.get("y") or 0)) for v in vs]
            box = [min(xs), min(ys), max(xs), max(ys)] if xs and ys else None
            lines.append({"text": t, "box": box})
    text = " ".join(l["text"] for l in lines)
    return {"text": (ta.get("fullText") or "").strip() or text, "lines": lines, "model": model}


def join_lines(lines: list) -> str:
    """Строки блока в одну, перенос по дефису склеивается (как у модели:
    «пере-» + «вод» → «перевод»)."""
    out = ""
    for ln in lines:
        t = (ln.get("text") if isinstance(ln, dict) else str(ln)).strip()
        if not t:
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and t[:1].islower():
            out = out[:-1] + t
        else:
            out = (out + " " + t).strip()
    return out
