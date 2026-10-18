# -*- coding: utf-8 -*-
"""Ш5: Яндекс Vision — второй читатель надписей на картинках.

Что сторожится (сеть подменена, ни одного настоящего запроса):
  1. разбор ответа Vision: строки, рамки, склейка переноса по дефису;
  2. запрос идёт МИМО прокси окружения и несёт ключ только в заголовке;
     модель рукописи — только у языков, где она есть (ru, en);
  3. отказы: 401/403/429 — «не повторять», 5xx — можно повторить;
  4. в `main`: модель не ответила — блоки читает Vision; режим рукописи
     «prefer» берёт текст Vision только у блоков-рукописей, признаки —
     от модели; без ключа — прежнее поведение (None);
  5. политика называет Яндекс получателем, только когда ключ задан.
"""
import io
import json
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import yandex_ocr as yo                                       # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


ANSWER = {"result": {"textAnnotation": {"width": "300", "height": "80", "fullText": "Ўпка сили\nпере-\nвод",
          "blocks": [{"lines": [
              {"text": "Ўпка сили", "boundingBox": {"vertices": [{"x": "10", "y": "5"}, {"x": "10", "y": "30"},
                                                                {"x": "200", "y": "30"}, {"x": "200", "y": "5"}]}},
              {"text": "пере-", "boundingBox": {"vertices": [{"x": "10", "y": "35"}, {"x": "90", "y": "60"}]}},
              {"text": "вод", "boundingBox": {"vertices": [{"x": "100", "y": "35"}, {"x": "150", "y": "60"}]}},
          ]}]}}}

print("── 1. разбор ответа ──")
r = yo.parse(ANSWER, "page")
check([l["text"] for l in r["lines"]] == ["Ўпка сили", "пере-", "вод"], "строки по порядку")
check(r["lines"][0]["box"] == [10, 5, 200, 30], "рамка строки — в точках картинки")
check(yo.join_lines(r["lines"]) == "Ўпка сили перевод", "перенос по дефису склеен")
check(yo.join_lines([{"text": "COVID-"}, {"text": "19"}]) == "COVID- 19", "дефис перед цифрой — не перенос слова")
check(yo.parse({}, "page")["lines"] == [], "пустой ответ — пусто, а не сбой")
check(yo.parse(ANSWER["result"], "page")["lines"][0]["text"] == "Ўпка сили",
      "ответ без обёртки result (нынешняя версия API) — тоже разобран")

print("── 2. запрос ──")
from PIL import Image                                         # noqa: E402
buf = io.BytesIO()
Image.new("RGBA", (40, 20), (255, 255, 255, 0)).save(buf, "PNG")
PNG = buf.getvalue()
seen = {}


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, handlers):
        self.handlers = handlers

    def open(self, req, timeout=None):
        seen["req"] = req
        seen["body"] = json.loads(req.data.decode())
        if seen.get("fail"):
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, seen["fail"], "x", {}, io.BytesIO(b"{}"))
        return _Resp(json.dumps(ANSWER).encode())


import urllib.request                                         # noqa: E402
_build = urllib.request.build_opener


def _fake_build(*handlers):
    seen["handlers"] = handlers
    return _Opener(handlers)


urllib.request.build_opener = _fake_build
yo.KEY = "test-key"
os.environ["HTTPS_PROXY"] = "http://proxy.example:3128"
got = yo.recognize(PNG, "UZ-CYRL", hand=True)
ph = [h for h in seen["handlers"] if isinstance(h, urllib.request.ProxyHandler)]
check(ph and ph[0].proxies == {}, "запрос мимо прокси окружения")
check(seen["req"].get_header("Authorization") == "Api-Key test-key", "ключ — в заголовке")
check("test-key" not in json.dumps(seen["body"]), "ключа нет в теле")
check(seen["body"]["languageCodes"] == ["uz"] and seen["body"]["model"] == "page",
      "узбекский: код uz, модели рукописи для него нет — page")
yo.recognize(PNG, "RU", hand=True)
check(seen["body"]["model"] == "handwritten", "русская рукопись — модель handwritten")
check(seen["body"]["mimeType"] == "JPEG", "картинка уходит JPEG (прозрачность — на белом)")
check(got["lines"][0]["text"] == "Ўпка сили", "ответ разобран")

print("── 3. отказы ──")
for code, stop in ((403, True), (401, True), (429, False), (400, False), (503, False)):
    seen["fail"] = code
    try:
        yo.recognize(PNG, "RU")
        check(False, "HTTP %d — исключение" % code)
    except yo.VisionError as e:
        check(e.code == code and e.stop == stop and "test-key" not in str(e),
              "HTTP %d: %s, без ключа в тексте" % (code, "не повторять" if stop else "можно повторить"))
seen.pop("fail")
try:
    yo.recognize(PNG, "")
    check(False, "язык не знаем — отказ")
except yo.VisionError as e:
    check(e.code == 400 and not e.stop, "язык не знаем — отказ этого запроса, «*» не шлём")
yo.KEY = ""
try:
    yo.recognize(PNG, "RU")
    check(False, "без ключа — отказ")
except yo.VisionError as e:
    check(e.stop, "без ключа — отказ «не повторять»")
check(not yo.available(), "без ключа модуль недоступен")

print("── 4. в main: запасной читатель и рукопись ──")
import main                                                   # noqa: E402
import image_text                                             # noqa: E402
main.save_state = lambda *a, **k: None
blocks = [{"box": [0, 0, 30, 15]}, {"box": [5, 2, 35, 18]}]
img = PNG
check(main._vision_read_blocks(img, blocks, "RU") is None, "без ключа — None (прежнее поведение)")
main.yandex_ocr.KEY = "test-key"
calls = {"n": 0}


def _rec(b, lang, hand=False):
    calls["n"] += 1
    return {"text": "Vision %d" % calls["n"], "lines": [{"text": "Vision %d" % calls["n"], "box": None}],
            "model": "handwritten" if hand else "page"}


main.yandex_ocr.recognize = _rec
_orig_client = main._llm_client


class _Boom:
    class chat:
        class completions:
            @staticmethod
            def create(**k):
                raise RuntimeError("provider down")


main._llm_client = lambda *a, **k: _Boom()
res = main._openai_read_image(img, blocks, "RU")
check(res is not None and [r["text"] for r in res] == ["Vision 1", "Vision 2"],
      "модель не ответила — блоки прочитал Vision")
check(all(r["model"] == "vision" and r["overlay"] is False for r in res),
      "читатель назван «vision», признака надпечатки Vision не даёт")
calls["n"] = 0
check(main._openai_read_image(img, blocks, "RU", fallback=False) is None and calls["n"] == 0,
      "кадр видео (fallback=False) — Vision не читает: субтитры и логотип он не различает")


class _Quota:
    class chat:
        class completions:
            @staticmethod
            def create(**k):
                raise RuntimeError("Error code: 429 - insufficient_quota: You exceeded your current quota")


main._llm_client = lambda *a, **k: _Quota()
check(main._openai_read_image(img, blocks, "RU") is None and calls["n"] == 0,
      "пустой счёт поставщика — None (прогон встаёт и зовёт владельца), а не тихий переход к Vision")
main._llm_client = lambda *a, **k: _Boom()
main.yandex_ocr.recognize = lambda b, lang, hand=False: {"text": "", "lines": [], "model": "page"}
check(main._openai_read_image(img, blocks, "RU") is None, "пустой ответ Vision — «не прочитано», а не пустой текст")
main.yandex_ocr.recognize = _rec


class _Ok:
    class chat:
        class completions:
            @staticmethod
            def create(**k):
                class M:
                    content = json.dumps({"blocks": [
                        {"i": 0, "text": "гораздо проще", "overlay": False, "hand": True, "serif": False},
                        {"i": 1, "text": "печатный", "overlay": False, "hand": False, "serif": True}]})

                class C:
                    message = M()
                    finish_reason = "stop"

                class R:
                    choices = [C()]
                    usage = None
                return R()


main._llm_client = lambda *a, **k: _Ok()
calls["n"] = 0
res = main._openai_read_image(img, blocks, "RU")
check([r["text"] for r in res] == ["гораздо проще", "печатный"] and calls["n"] == 0,
      "режим «off»: текст модели, Vision не спрашивают")
main.YANDEX_VISION_HAND = "prefer"
res = main._openai_read_image(img, blocks, "RU")
check(res[0]["text"] == "Vision 1" and res[0]["textModel"] == "гораздо проще" and res[0]["hand"] is True,
      "«prefer»: рукопись — текстом Vision, прежний текст модели сохранён")
check(res[1]["text"] == "печатный" and res[1]["serif"] is True, "печатный блок — текстом модели")
calls["n"] = 0
res = main._openai_read_image(img, blocks, "UZ-CYRL")
check(res[0]["text"] == "гораздо проще" and calls["n"] == 0,
      "«prefer» у языка без модели рукописи (узбекский) — текст модели, Vision не спрашивают")
main.YANDEX_VISION_HAND = "off"
main._llm_client = _orig_client
main.yandex_ocr.KEY = ""

print("── 5. политика ──")
import legal                                                  # noqa: E402
os.environ.pop("YANDEX_VISION_API_KEY", None)
check("Яндекс" not in legal.model_providers("ru"), "без ключа Яндекс в политике не назван")
os.environ["YANDEX_VISION_API_KEY"] = "x"
check("Яндекс" in legal.model_providers("ru") and "Yandex" in legal.model_providers("en"),
      "с ключом — назван получателем изображений")
os.environ.pop("YANDEX_VISION_API_KEY", None)

urllib.request.build_opener = _build
print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
