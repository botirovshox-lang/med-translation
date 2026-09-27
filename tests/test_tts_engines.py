"""Синтез речи для всех языков: маршрут по языку, Azure, письмо, ошибки.

Сеть не трогается: `urllib.request.urlopen` подменён, а сборщик SSML,
заголовки, разбор ошибок и маршрут — настоящим кодом (закон «промпты
проверяются настоящим кодом»: подменяется ТРАНСПОРТ, а не своя функция).
"""
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import tts_engines as t  # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


for k in ("OPENAI_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "VOICE_ENGINE_ORDER"):
    os.environ.pop(k, None)

print("=== 1. Каталог голосов покрывает каждый язык системы ===")
langs = [x["code"] for x in json.loads((ROOT / "backend" / "languages.json").read_text(encoding="utf-8"))["languages"]]
d = t.data()
az, oa = d.get("azure") or {}, set(d.get("openaiNative") or [])
for code, e in az.items():
    if not (e.get("locale") and (e.get("f") or e.get("m"))):
        check(False, "у %s есть локаль и хотя бы один голос" % code)
check(all(c in langs for c in list(az) + list(oa)), "в каталоге голосов нет языков, которых нет в системе")
no_native = sorted(c for c in langs if c not in az and c not in oa)
check("UZ" in az and "UZ-CYRL" in az and "UZ" not in oa, "узбекский — родной голос у Azure, у OpenAI его нет")
check(len(no_native) <= 8, "без родного голоса — единицы: %s" % no_native)
print("       без родного голоса: %s" % ", ".join(no_native))

print("=== 2. Маршрут: родной голос первым, иначе — «с акцентом», и это названо ===")
check(t.route("UZ")["quality"] == "none", "нет ни одного ключа — движка нет")
os.environ["OPENAI_API_KEY"] = "sk-test"
check(t.route("RU") == {"engine": "openai", "quality": "native", "why": ""}, "русский — OpenAI, родной")
r = t.route("UZ")
check(r["engine"] == "openai" and r["quality"] == "accent", "узбекский без Azure — OpenAI С АКЦЕНТОМ: %s" % r)
os.environ["AZURE_SPEECH_KEY"] = "az-key"
check(t.route("UZ")["quality"] == "accent", "ключ без региона — Azure не готов")
os.environ["AZURE_SPEECH_REGION"] = "westeurope"
check(t.route("UZ") == {"engine": "azure", "quality": "native", "why": ""}, "узбекский с Azure — родной голос")
check(t.route("RU")["engine"] == "openai", "у русского OpenAI остаётся первым (живее интонацией)")
os.environ["VOICE_ENGINE_ORDER"] = "azure,openai"
check(t.route("RU")["engine"] == "azure", "порядок движков — из окружения")
os.environ.pop("VOICE_ENGINE_ORDER")
r = t.route("TK")
check(r["engine"] == "openai" and r["quality"] == "accent", "туркменский — ни у кого нет голоса: с акцентом")
check(t.voice_for("azure", "UZ", "f2") == ("f0", "uz-UZ-MadinaNeural"),
      "ярлыка нет у движка — первый голос того же пола")
check(t.voice_for("azure", "UZ", "m1")[1] == "uz-UZ-SardorNeural", "мужской — мужской")
pv = t.public_voices("UZ")
check(pv["quality"] == "native" and all(set(v) == {"id", "gender", "n"} for v in pv["voices"]),
      "наружу — ярлыки и номер, без имён голосов поставщика: %s" % pv)

print("=== 3. Письмо: узбекская кириллица → латиница для голоса uz-UZ ===")
for a, b in [("Шаҳар маркази", "Shahar markazi"), ("ЯНГИ ЙИЛ", "YANGI YIL"), ("Ер юзи, еттинчи", "Yer yuzi, yettinchi"),
             ("соғлиқни сақлаш", "sogʻliqni saqlash"), ("Ўзбекистон", "Oʻzbekiston"), ("Эълон", "Eʼlon"),
             ("COVID-19 даволаш", "COVID-19 davolash")]:
    check(t.uz_cyr_to_lat(a) == b, "%s → %s (%s)" % (a, b, t.uz_cyr_to_lat(a)))

print("=== 4. Azure: запрос, SSML, ошибки ===")
CAP = {}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    CAP["url"], CAP["headers"], CAP["body"] = req.full_url, dict(req.header_items()), req.data.decode("utf-8")
    code = CAP.get("code")
    if code:
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(b"Quota exceeded"))
    return _Resp(b"\x01\x00" * 2400 + b"\x07")


urllib.request.urlopen = fake_urlopen
eng = t.ENGINES["azure"]
pcm = eng.synth("Шаҳар <марказ> & «x»\x01", "UZ-CYRL", "uz-UZ-MadinaNeural")
h = {k.lower(): v for k, v in CAP["headers"].items()}
check(CAP["url"] == "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1", "адрес региона")
check(h.get("x-microsoft-outputformat") == "raw-24khz-16bit-mono-pcm" and h.get("ocp-apim-subscription-key") == "az-key"
      and h.get("content-type") == "application/ssml+xml" and h.get("user-agent"), "заголовки: формат PCM 24 кГц, ключ, UA")
check("xml:lang='uz-UZ'" in CAP["body"] and "<voice name='uz-UZ-MadinaNeural'>" in CAP["body"]
      and "Shahar &lt;markaz&gt; &amp;" in CAP["body"] and "\x01" not in CAP["body"],
      "SSML: локаль, голос, латиница, экранирование, без управляющих символов: %s" % CAP["body"])
check(len(pcm) % 2 == 0 and len(pcm) == 4800, "PCM обрезан до целых отсчётов")
# Вид ошибки решает, что делать со сборкой: квота — стоп «кончились деньги»,
# ключ — стоп со своими словами, «часто» — ждать без траты попытки,
# 5xx — повтор, 400 — отказ ОДНОЙ строки (не тот голос в регионе).
for code, want in ((429, "throttle"), (403, "quota"), (401, "fatal"), (503, "retry"), (400, "line")):
    CAP["code"] = code
    try:
        eng.synth("salom", "UZ", "uz-UZ-SardorNeural")
        check(False, "HTTP %d — исключение" % code)
    except t.TtsError as e:
        got = ("throttle" if e.throttle else "quota" if e.quota else "fatal" if e.fatal
               else "retry" if e.retry else "line")
        check(got == want, "HTTP %d → %s (%s)" % (code, want, got))
CAP["code"] = None
os.environ["AZURE_SPEECH_REGION"] = "west europe/../x"
try:
    eng.synth("salom", "UZ", "uz-UZ-SardorNeural")
    check(False, "кривой регион — отказ")
except t.TtsError:
    check(True, "кривой регион в адрес не подставляется")
os.environ["AZURE_SPEECH_REGION"] = "westeurope"
check(t.billable_chars("ab中文") == 6, "иероглифы — по два знака, как считает поставщик")

print("\nПРОВАЛЕНО: %d" % len(fail) if fail else "\nВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
