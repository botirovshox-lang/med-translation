"""Собрать backend/voices.json — голоса синтеза по языкам системы.

    python tools/voices_build.py            # с ключом Azure: список ЕГО региона
    python tools/voices_build.py --public   # без ключа: публичный перечень (Edge)

Первый вариант верный: у Azure голоса бывают не во всех регионах, и голос из
общего перечня может не существовать в вашем (тогда строка не озвучится
и будет названа). Публичный перечень — подмножество Azure, годится для старта.
Список «родных» языков OpenAI — из официальной документации синтеза («как
у Whisper»), правится здесь руками.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "voices.json"
PUBLIC = ("https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/voices/list"
          "?trustedclienttoken=6A5AA1D4EAFF4E9FB37E23D68491D6F4")
OPENAI_NATIVE = ("AF AR HY AZ BE BS BG CA ZH HR CS DA NL EN ET FI FR GL DE EL HE HI HU IS ID IT JA KK KO LV "
                 "LT MK MS NE NO FA PL PT RO RU SR SK SL ES SW SV TA TH TR UK UR VI CY").split()
# Какую локаль брать у языка, где их несколько (иначе — локаль с наибольшим
# числом голосов).
PREFER = {"EN": "en-US", "ES": "es-ES", "PT": "pt-BR", "AR": "ar-SA", "ZH": "zh-CN", "FR": "fr-FR", "DE": "de-DE",
          "NL": "nl-NL", "IT": "it-IT", "KO": "ko-KR", "SW": "sw-KE", "UR": "ur-PK", "TA": "ta-IN", "BN": "bn-BD",
          "MS": "ms-MY", "SR": "sr-RS", "PS": "ps-AF", "FA": "fa-IR", "HI": "hi-IN", "TE": "te-IN", "GU": "gu-IN"}
TRANSLIT = {"UZ-CYRL": "uz-cyrl-latn"}


def fetch(public: bool) -> list:
    if public:
        req = urllib.request.Request(PUBLIC)
    else:
        key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
        if not (key and region):
            sys.exit("нет AZURE_SPEECH_KEY / AZURE_SPEECH_REGION — или запустите с --public")
        req = urllib.request.Request("https://%s.tts.speech.microsoft.com/cognitiveservices/voices/list" % region,
                                     headers={"Ocp-Apim-Subscription-Key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def build(voices: list) -> dict:
    langs = [x["code"] for x in json.loads((ROOT / "backend" / "languages.json").read_text(encoding="utf-8"))["languages"]]
    by = {}
    for v in voices:
        if v.get("Status") not in (None, "GA"):
            continue
        g = "f" if v.get("Gender") == "Female" else "m"
        by.setdefault(v["Locale"], {"f": [], "m": []})[g].append(v["ShortName"])
    az = {}
    for c in langs:
        base = c.split("-")[0].lower()
        locs = [loc for loc in by if loc.split("-")[0].lower() == base]
        if not locs:
            continue
        want = PREFER.get(c.split("-")[0])
        loc = want if want in locs else sorted(locs, key=lambda l_: (-(len(by[l_]["f"]) + len(by[l_]["m"])), l_))[0]
        ent = {"locale": loc, "f": by[loc]["f"], "m": by[loc]["m"]}
        if c in TRANSLIT:
            ent["translit"] = TRANSLIT[c]
        az[c] = ent
    return {"_comment": [
        "Голоса синтеза по языку системы (backend/languages.json). Собирает tools/voices_build.py.",
        "azure — нейроголоса Azure Speech: локаль и голоса по полу (первый — по умолчанию).",
        "openaiNative — языки из официального списка синтеза OpenAI: у остальных OpenAI читает с акцентом.",
        "translit — текст перед синтезом переводится в письмо, которое читает голос (узбекская кириллица → латиница)."],
        "openaiNative": [c for c in OPENAI_NATIVE if c in langs], "azure": az}


if __name__ == "__main__":
    d = build(fetch("--public" in sys.argv))
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("azure: %d языков, openai: %d → %s" % (len(d["azure"]), len(d["openaiNative"]), OUT))
