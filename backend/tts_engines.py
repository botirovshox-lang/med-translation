"""Синтез речи для озвучки: реестр движков и маршрут по языку.

Почему не одна модель. «Все языки мира» одной моделью с коммерческой
лицензией сегодня не существует: у MMS (1100+ языков) и OmniVoice (646)
веса некоммерческие, у OpenAI в официальном списке синтеза ~57 языков
и НЕТ узбекского (узбекский она читает с акцентом — это и был «робот»),
у Azure нейроголоса есть для 64 языков системы, включая узбекский, но нет
киргизского, таджикского, туркменского. Поэтому универсальность здесь —
МАРШРУТ: для языка берётся первый готовый движок с РОДНЫМ голосом, иначе —
запасной «с акцентом», и это называется честно (`quality`).

Модуль не знает ни STATE, ни проектов, ни денег: учёт расхода и рубеж
лимита — у вызывающего (`main._tts_clip`). Имена движков и голосов наружу
не уходят (инвариант 24а): наружу — ярлыки f0/m0/f1… и `quality`.

Данные — `backend/voices.json` (правит человек): голоса Azure по языку,
список «родных» языков OpenAI, правила письма (`translit`).
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

RATE = 24000                        # все движки отдают PCM s16le 24 кГц моно

_VOICES_PATH = Path(__file__).resolve().parent / "voices.json"
_DATA: dict = {}
_DATA_MTIME = 0.0


def data() -> dict:
    """Каталог голосов; перечитывается при правке файла (как model_ranks)."""
    global _DATA, _DATA_MTIME
    try:
        mt = _VOICES_PATH.stat().st_mtime
    except OSError:
        return _DATA or {}
    if mt != _DATA_MTIME:
        try:
            _DATA = json.loads(_VOICES_PATH.read_text(encoding="utf-8"))
            _DATA_MTIME = mt
        except (OSError, ValueError):
            pass
    return _DATA or {}


class TtsError(RuntimeError):
    """Отказ движка — со словами и с ВИДОМ, от которого зависит, что делать:
    `quota` — кончились деньги/квота (стоп всей сборки, как пустой счёт);
    `fatal` — ключ отклонён (стоп, но это НЕ «кончились деньги»);
    `throttle` — слишком часто (подождать `after` секунд и повторить, попытку
    строки это не съедает); `retry` — сбой сети/5xx (обычный повтор);
    иначе — отказ ЭТОЙ строки (400: не тот голос в регионе, битый текст) —
    строка остаётся без озвучки и называется номером, сборка идёт дальше."""

    def __init__(self, msg: str, quota: bool = False, retry: bool = False, fatal: bool = False,
                 throttle: bool = False, after: float = 0.0):
        super().__init__(msg)
        self.quota = quota
        self.retry = retry
        self.fatal = fatal
        self.throttle = throttle
        self.after = after


# ─── Письмо ──────────────────────────────────────────────────────────
# Голос uz-UZ читает ЛАТИНИЦУ: кириллический текст он либо не прочтёт, либо
# прочтёт по-русски. Переписать письмо можно без модели и однозначно —
# это государственная таблица соответствия 1995 года.

_UZ_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "ʼ", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ў": "oʻ", "қ": "q",
    "ғ": "gʻ", "ҳ": "h",
}
_VOWELS = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ")


def uz_cyr_to_lat(text: str) -> str:
    """Узбекская кириллица → латиница. «е» — «ye» в начале слова и после
    гласной или ъ/ь, иначе «e». Регистр: заглавная буква даёт заглавную
    первую букву замены («Ш» → «Sh»), слово капсом — капс целиком («ШАҲАР» →
    «SHAHAR»). Латиница, цифры и знаки проходят как есть."""
    out = []
    words = re.split(r"(\W+)", text)
    for w in words:
        if not w or not re.match(r"\w", w):
            out.append(w)
            continue
        caps = len(w) > 1 and w.isupper()
        res = []
        for i, ch in enumerate(w):
            low = ch.lower()
            if low == "е":
                prev = w[i - 1] if i else ""
                r = "ye" if (i == 0 or prev in _VOWELS or prev.lower() in ("ъ", "ь")) else "e"
            elif low in _UZ_CYR:
                r = _UZ_CYR[low]
            else:
                res.append(ch)
                continue
            if ch != low and r:
                r = r.upper() if caps else r[0].upper() + r[1:]
            res.append(r)
        out.append("".join(res))
    return "".join(out)


_TRANSLIT = {"uz-cyrl-latn": uz_cyr_to_lat}


def prepare_text(text: str, rule: Optional[str]) -> str:
    fn = _TRANSLIT.get(rule or "")
    return fn(text) if fn else text


# ─── Движки ──────────────────────────────────────────────────────────

def _lang_key(lang: str) -> str:
    return (lang or "").upper()


class Engine:
    """Контракт движка. `synth` → PCM s16le 24 кГц моно."""
    id = ""
    paid = True

    def ready(self) -> tuple:
        return False, "no_engine"

    def native(self, lang: str) -> bool:
        return False

    def voices(self, lang: str) -> list:
        """[(ярлык, пол, имя голоса у движка)]."""
        return []

    def synth(self, text: str, lang: str, voice: str, style: str = "") -> bytes:
        raise NotImplementedError


# Голоса OpenAI: ярлыки прежние (они лежат в params проектов, смысл менять
# нельзя), f0/m0 — самые живые («for best quality: marin, cedar»).
OPENAI_VOICES = [("f0", "f", "marin"), ("m0", "m", "cedar"), ("f1", "f", "coral"), ("f2", "f", "nova"),
                 ("m1", "m", "onyx"), ("m2", "m", "ash")]


class OpenAIEngine(Engine):
    id = "openai"

    def __init__(self, model: str = ""):
        self.model = model or os.environ.get("TTS_MODEL", "gpt-4o-mini-tts")

    def ready(self) -> tuple:
        return (True, "") if os.environ.get("OPENAI_API_KEY") else (False, "no_key")

    def native(self, lang: str) -> bool:
        return _lang_key(lang) in set(data().get("openaiNative") or [])

    def voices(self, lang: str) -> list:
        return list(OPENAI_VOICES)

    def synth(self, text: str, lang: str, voice: str, style: str = "") -> bytes:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=120, max_retries=2)
        resp = client.audio.speech.create(model=self.model, voice=voice, input=text[:3900],
                                          response_format="pcm", instructions=style or None)
        return resp.read() if hasattr(resp, "read") else (resp.content if hasattr(resp, "content") else bytes(resp))


_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml(text: str) -> str:
    """Экранирование для SSML. Управляющие символы, оставленные
    распознаванием, XML 1.0 не допускает вовсе — Azure отвечал бы 400."""
    text = _XML_BAD.sub(" ", text)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


# Потолок одного запроса Azure — 10 минут звука; реплика субтитров короче
# на порядки, но текст режем с запасом, как у OpenAI.
AZURE_MAX_CHARS = 3000


def billable_chars(text: str) -> int:
    """Сколько знаков выставит Azure: текст без разметки, иероглифы и кана —
    по два (так считает поставщик)."""
    return sum(2 if 0x2E80 <= ord(ch) <= 0x9FFF or 0xAC00 <= ord(ch) <= 0xD7AF else 1 for ch in text)


class AzureEngine(Engine):
    """Azure Speech, нейроголоса: родной голос для 64 языков системы, в том
    числе узбекского. REST без SDK: один запрос — одна реплика."""
    id = "azure"

    def ready(self) -> tuple:
        if not os.environ.get("AZURE_SPEECH_KEY"):
            return False, "no_key"
        if not os.environ.get("AZURE_SPEECH_REGION"):
            return False, "no_region"
        return True, ""

    def entry(self, lang: str) -> Optional[dict]:
        return (data().get("azure") or {}).get(_lang_key(lang))

    def native(self, lang: str) -> bool:
        e = self.entry(lang)
        return bool(e and (e.get("f") or e.get("m")))

    def voices(self, lang: str) -> list:
        e = self.entry(lang) or {}
        out = []
        for g in ("f", "m"):
            for i, name in enumerate(e.get(g) or []):
                out.append(("%s%d" % (g, i), g, name))
        return out

    def ssml(self, text: str, lang: str, voice: str) -> str:
        e = self.entry(lang) or {}
        loc = e.get("locale") or "en-US"
        body = _xml(prepare_text(text, e.get("translit"))[:AZURE_MAX_CHARS])
        return ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='%s'>"
                "<voice name='%s'>%s</voice></speak>" % (loc, _xml(voice), body))

    def synth(self, text: str, lang: str, voice: str, style: str = "") -> bytes:
        import urllib.error
        import urllib.request
        region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
        if not re.fullmatch(r"[a-z0-9]+", region):
            raise TtsError("Неверный регион синтеза")
        req = urllib.request.Request(
            "https://%s.tts.speech.microsoft.com/cognitiveservices/v1" % region,
            data=self.ssml(text, lang, voice).encode("utf-8"), method="POST",
            headers={"Ocp-Apim-Subscription-Key": os.environ.get("AZURE_SPEECH_KEY", ""),
                     "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": "raw-24khz-16bit-mono-pcm",
                     "User-Agent": "medcat-dub"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                pcm = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    after = float((e.headers or {}).get("Retry-After") or 0)
                except (TypeError, ValueError):
                    after = 0.0
                raise TtsError("Синтез: слишком много запросов", throttle=True, after=min(60.0, max(1.0, after)))
            if e.code == 403:
                raise TtsError("Синтез: квота исчерпана", quota=True)
            if e.code == 401:
                raise TtsError("Синтез: ключ отклонён — сообщите администратору", fatal=True)
            raise TtsError("Синтез отказал: HTTP %d" % e.code, retry=e.code >= 500)
        except (urllib.error.URLError, OSError) as e:
            raise TtsError("Синтез недоступен: %s" % getattr(e, "reason", e), retry=True)
        if not pcm:
            raise TtsError("Синтез вернул пустой звук", retry=True)
        return pcm[:len(pcm) // 2 * 2]


ENGINES = {"openai": OpenAIEngine(), "azure": AzureEngine()}
# Кто первым получает язык, если родной голос есть у нескольких: OpenAI —
# живее интонацией (а ключ уже есть), Azure — родное произношение там, где
# OpenAI его не знает. Свой GPU-сервер с клонированием голоса (Navoiy,
# CosyVoice3, VoxCPM2) встанет третьим движком — план в BACKLOG.md.
DEFAULT_ORDER = ("openai", "azure")


def order() -> list:
    raw = os.environ.get("VOICE_ENGINE_ORDER", "")
    ids = [x.strip() for x in raw.split(",") if x.strip() in ENGINES] if raw else []
    return ids or list(DEFAULT_ORDER)


def route(lang: str) -> dict:
    """Движок для языка: {"engine", "quality": native|accent|none, "why"}.
    Первый ГОТОВЫЙ с родным голосом; иначе OpenAI «с акцентом» (читает
    любой текст, но с чужим произношением); нет и его — `none`."""
    for eid in order():
        e = ENGINES[eid]
        if e.ready()[0] and e.native(lang):
            return {"engine": eid, "quality": "native", "why": ""}
    oa = ENGINES["openai"]
    if oa.ready()[0]:
        return {"engine": "openai", "quality": "accent", "why": "no_native_voice"}
    return {"engine": None, "quality": "none", "why": "no_engine"}


def voice_for(engine_id: str, lang: str, label: str) -> tuple:
    """(ярлык, имя голоса у движка). Ярлыка нет у этого движка — первый
    голос того же пола, потом просто первый: у узбекского у Azure по одному
    голосу на пол, а человек мог выбрать «женский 3»."""
    vs = ENGINES[engine_id].voices(lang)
    if not vs:
        raise TtsError("У движка нет голосов для этого языка")
    hit = next((v for v in vs if v[0] == label), None)
    if hit is None:
        g = (label or "f")[:1]
        hit = next((v for v in vs if v[1] == g), vs[0])
    return hit[0], hit[2]


def public_voices(lang: str) -> dict:
    """Что показать человеку до сборки: голоса ярлыками и качество."""
    r = route(lang)
    vs = ENGINES[r["engine"]].voices(lang) if r["engine"] else []
    n = {"f": 0, "m": 0}
    out = []
    for vid, g, _name in vs:
        n[g] += 1
        out.append({"id": vid, "gender": g, "n": n[g]})
    return {"voices": out, "quality": r["quality"]}
