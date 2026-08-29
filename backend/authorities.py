"""Внешние источники приказов и корпусная проверка терминов.

Зачем это существует
────────────────────
Система не может заверять термины собственными переводами: если кандидат
приходит из машинного перевода, а подтверждают его оценки того же контура,
получается самоподтверждение — и ошибка закрепляется как правило. Раньше
единственным выходом из этого круга был человек. Но человек, не знающий
целевого языка (а именно для таких этот инструмент и делается), судить
о термине не может.

Значит, право сделать запись приказом должен давать источник ВНЕ контура:

  словарь  — отраслевой справочник, где пара «оригинал → перевод» уже
             зафиксирована кем-то, кто в этом разбирается. Совпадение с ним
             и есть приказ: это не мнение модели, это норма.
  корпус   — тексты целевого языка. Он не говорит «это верный перевод»,
             он отвечает на другой вопрос: «такой термин в языке вообще
             существует?». «rear cyclitis» не встречается нигде — и это
             ловится одним запросом, без всякой модели.

Закон тот же, что у DOMAIN_RULES в medical_qa: НЕТ источника для этой области
и этой пары языков — МОЛЧИМ. Никогда не «сойдёт английский справочник для
узбекского перевода»: выдуманное подтверждение хуже отсутствующего.

Сеть тут необязательна. Любая недоступность источника означает «сигнала нет»,
а не «сигнал отрицательный»: молчащий интернет не должен ни одобрять термины,
ни блокировать работу.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ─── Языки ───────────────────────────────────────────────────────────
# Коды нужны корпусам (у Википедии домен на язык). Пары в проекте хранятся
# строкой «RU→EN», отсюда и разбор.
LANG_CODES = {"RU": "ru", "EN": "en", "DE": "de", "FR": "fr", "ES": "es"}

USER_AGENT = "MedicalCATTranslator/1.0 (terminology verification)"
NET_TIMEOUT = float(os.environ.get("AUTHORITY_TIMEOUT", "6"))
# Ниже этого числа вхождений термин считается неподтверждённым, при нуле —
# отсутствующим в языке. Пороги намеренно низкие: задача корпуса — отсеять
# кальки, которых нет вовсе, а не ранжировать хорошие термины между собой.
MIN_ATTESTED = int(os.environ.get("AUTHORITY_MIN_HITS", "5"))

CORPUS_ENABLED = os.environ.get("AUTHORITY_CORPUS", "1").lower() not in {"0", "false", "no", "off"}


def target_lang(lang_pair: str) -> str:
    """«RU→EN» → «EN». Пара может прийти с любым разделителем-стрелкой."""
    parts = re.split(r"→|->|—>|>", lang_pair or "")
    return (parts[-1] if parts else "").strip().upper()


def source_lang(lang_pair: str) -> str:
    parts = re.split(r"→|->|—>|>", lang_pair or "")
    return (parts[0] if parts else "").strip().upper()


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("ё", "е").split())


# ─── Словари: офлайновые справочники ─────────────────────────────────
# Формат — TSV с заголовком в комментариях. Так справочник добавляется файлом,
# без правки кода:
#
#   # label: ВОЗ INN — международные непатентованные наименования
#   # lang: RU→EN
#   # domains: medical, pharma
#   аторвастатин	atorvastatin
#
# «domains: *» — источник годится для любой области (так устроены IATE и UNTERM),
# но пара языков обязательна всегда: справочник без указанной пары бесполезен
# и опасен.

class Dictionary:
    def __init__(self, ident, label, lang, domains, pairs, path, tier="verified"):
        self.id = ident
        self.label = label
        self.lang = lang              # «RU→EN»
        self.domains = domains        # set | "*"
        self.pairs = pairs            # {норм. оригинал: {норм. переводы}}
        self.path = path
        # verified — источник вправе приказывать модели сам по себе (выверенный
        # отраслевой справочник). auto — источник краудсорсный: его слово идёт
        # подтверждающим голосом рядом с другими сигналами, но приказом в
        # одиночку не становится. Разница не косметическая: приказ модель
        # обязана исполнить, и неверная норма в нём — это ошибка в переводе,
        # которую уже никто не поймает.
        # Непонятное значение — закрываемся в СЛАБУЮ сторону: опечатка
        # в заголовке не должна раздавать источнику право приказывать.
        self.tier = tier if tier in ("verified", "auto") else "auto"

    def covers(self, lang: str, domain: str) -> bool:
        if _norm(self.lang) != _norm(lang):
            return False
        return self.domains == "*" or domain in self.domains

    def match(self, src: str, tgt: str) -> bool:
        return _norm(tgt) in self.pairs.get(_norm(src), ())

    def suggest(self, src: str):
        """Что справочник предлагает для этого термина — чтобы показать человеку
        не только «не совпало», но и «а норма вот такая»."""
        return sorted(self.pairs.get(_norm(src), ()))


def _parse_header(line: str, meta: dict):
    m = re.match(r"#\s*(label|lang|domains|tier)\s*:\s*(.+)$", line.strip(), re.I)
    if not m:
        return
    key, val = m.group(1).lower(), m.group(2).strip()
    if key == "domains":
        meta["domains"] = "*" if val.strip() == "*" else {
            d.strip().lower() for d in val.split(",") if d.strip()}
    else:
        meta[key] = val


def load_dictionaries(root) -> list:
    """Прочитать все справочники из каталога. Битый файл пропускаем с шумом
    в журнал, а не роняем сервис: справочник — данные, а не код."""
    out = []
    root = Path(root)
    if not root.exists():
        return out
    for path in sorted(root.glob("*.tsv")):
        meta, pairs = {}, {}
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    if line.startswith("#"):
                        _parse_header(line, meta)
                        continue
                    if not line.strip():
                        continue
                    cols = line.rstrip("\n").split("\t")
                    if len(cols) < 2:
                        continue
                    src, tgt = _norm(cols[0]), _norm(cols[1])
                    if src and tgt:
                        pairs.setdefault(src, set()).add(tgt)
        except Exception as e:
            print(f"[authorities] справочник {path.name} не прочитан: {e}", file=sys.stderr)
            continue
        if not meta.get("lang"):
            print(f"[authorities] {path.name}: нет строки «# lang: RU→EN» — пропущен, "
                  f"справочник без языковой пары применять не к чему", file=sys.stderr)
            continue
        if not pairs:
            continue
        tier = (meta.get("tier") or "verified").strip().lower()
        out.append(Dictionary(path.stem, meta.get("label", path.stem), meta["lang"],
                              meta.get("domains", "*"), pairs, str(path), tier))
        d = out[-1]
        # В журнал пишем ПРИНЯТЫЙ уровень, а не то, что было в файле: иначе
        # «# tier: crowdsourced» логировался бы как crowdsourced, а работал бы
        # как что-то другое.
        print(f"[authorities] {path.stem}: {len(pairs)} терминов, {meta['lang']}, "
              f"области {meta.get('domains', '*')}, уровень {d.tier}"
              + (f" (в файле «{tier}» — не распознан)" if d.tier != tier else ""),
              file=sys.stderr)
    return out


# ─── Корпуса: живёт ли термин в целевом языке ────────────────────────
# Корпус НЕ подтверждает перевод. Он отвечает только на вопрос «такое слово
# в этом языке употребляют?» — и этого достаточно, чтобы поймать кальку.

CORPORA = [
    {"id": "pubmed", "label": "PubMed",
     "domains": {"medical", "pharma"}, "langs": {"EN"}},
    # Википедия есть на всех наших языках и не привязана к области. Слабее
    # PubMed, поэтому идёт второй: медицинский термин ищем там, где о медицине
    # и пишут.
    {"id": "wikipedia", "label": "Википедия",
     "domains": "*", "langs": set(LANG_CODES)},
]


def corpora_for(tgt: str, domain: str) -> list:
    """Все подходящие корпуса в порядке предпочтения. Список, а не один:
    источник может быть недоступен (у хостера сломан DNS, лимит, авария),
    и тогда работать должен следующий. Один жёстко выбранный корпус означал
    бы, что падение PubMed молча отключает проверку калек и для Википедии,
    которая при этом жива."""
    out = []
    for c in CORPORA:
        if tgt not in c["langs"]:
            continue
        if c["domains"] != "*" and domain not in c["domains"]:
            continue
        out.append(c)
    return out


def corpus_for(tgt: str, domain: str):
    """Корпус, который РЕАЛЬНО ответит: мёртвые пропускаем."""
    live = [c for c in corpora_for(tgt, domain) if _DEAD_UNTIL.get(c["id"], 0) <= time.time()]
    return live[0] if live else None


_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 20000
# Источник, который перестал отвечать, не спрашиваем ещё какое-то время:
# иначе каждый кандидат из пачки платит своим таймаутом, и разбор очереди
# из двухсот терминов встаёт на двадцать минут.
_DEAD_UNTIL: dict = {}
DEAD_FOR = 300


# Минимальный интервал между запросами к источнику. У NCBI без ключа это
# 3 запроса в секунду, и превышение отвечает 429 — то есть наша параллельность
# сама себе выключала бы корпусную проверку. Троттлинг дешевле ретраев.
_MIN_INTERVAL = {"pubmed": 0.34, "wikipedia": 0.1}
_LAST_CALL: dict = {}
_RATE_LOCK = threading.Lock()


def _throttle(source: str):
    """Держит частоту запросов к источнику в пределах его лимита.

    Слот занимаем ПОД локом, а спим уже без него: заснув с локом, поток
    останавливал бы и всех остальных, и параллельность превращалась бы
    в последовательность с общим ожиданием."""
    gap = _MIN_INTERVAL.get(source, 0.2)
    with _RATE_LOCK:
        slot = max(time.time(), _LAST_CALL.get(source, 0) + gap)
        _LAST_CALL[source] = slot
    wait = slot - time.time()
    if wait > 0:
        time.sleep(wait)


def _get_json(url: str, source: str):
    _throttle(source)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


class Unreadable(Exception):
    """Источник ответил, но не тем, что мы умеем читать. Это «не знаю»,
    а НЕ «ноль вхождений»: пустой ответ нельзя превращать в вето."""


def _pubmed_hits(term: str) -> int:
    url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
           "?db=pubmed&rettype=count&retmode=json&term="
           + urllib.parse.quote('"%s"' % term))
    data = _get_json(url, "pubmed").get("esearchresult", {})
    if "count" not in data:
        raise Unreadable("ответ без поля count: " + str(data)[:120])
    return int(data["count"])


def _wikipedia_hits(term: str, code: str) -> int:
    url = ("https://%s.wikipedia.org/w/api.php?action=query&list=search&format=json"
           "&srlimit=1&srinfo=totalhits&srsearch=" % code
           + urllib.parse.quote('"%s"' % term))
    info = _get_json(url, "wikipedia").get("query", {}).get("searchinfo", {})
    if "totalhits" not in info:
        raise Unreadable("ответ без поля totalhits: " + str(info)[:120])
    return int(info["totalhits"])


def attested(term: str, tgt: str, domain: str):
    """Встречается ли термин в целевом языке.

    Возвращает {"hits", "source", "label", "ok"} либо None, если проверить
    нечем: источника для этой пары нет, сеть молчит или проверка выключена.
    None — это «не знаю», и трактовать его как «плохо» нельзя.
    """
    term = (term or "").strip()
    if not CORPUS_ENABLED or not term or len(term) < 3:
        return None
    lang = (tgt or "").upper()
    for corpus in corpora_for(lang, domain):
        key = (corpus["id"], lang, _norm(term))
        with _CACHE_LOCK:
            if key in _CACHE:
                return _CACHE[key]
            if _DEAD_UNTIL.get(corpus["id"], 0) > time.time():
                continue                      # мёртвый — пробуем следующий
        try:
            if corpus["id"] == "pubmed":
                hits = _pubmed_hits(term)
            else:
                hits = _wikipedia_hits(term, LANG_CODES.get(lang, "en"))
        except Unreadable as e:
            # Один непонятный ответ — не повод отключать источник: он жив, просто
            # эта конкретная выдача нечитаема. По этому термину молчим совсем:
            # спрашивать следующий бессмысленно, вопрос был не в источнике.
            print(f"[authorities] {corpus['id']}: {e}", file=sys.stderr)
            return None
        except Exception as e:
            with _CACHE_LOCK:
                _DEAD_UNTIL[corpus["id"]] = time.time() + DEAD_FOR
            print(f"[authorities] {corpus['id']} недоступен ({e}) — отключён "
                  f"на {DEAD_FOR} c, пробуем следующий источник", file=sys.stderr)
            continue
        # ВЕТО имеет право накладывать только корпус, СВОЙ для этой области.
        # Ноль в Википедии для узкого медицинского термина не доказывает
        # кальку — он доказывает, что в Википедии нет статьи с таким
        # названием. На боевых данных «cavitary pulmonary tuberculosis»
        # (принятый английский термин) получил там 0 вхождений, а калька
        # «cavernous pulmonary tuberculosis» — 1: запрет сработал бы РОВНО
        # НАОБОРОТ. Так у пяти вердиктов арбитра молча срезали готовый совет,
        # пока PubMed был недоступен с сервера.
        # Подтверждать общий корпус по-прежнему вправе: наличие строки в языке
        # он показывает честно. Отсутствие — это «не знаю», и по закону
        # `attested()` такое не должно ни одобрять, ни блокировать.
        specific = corpus["domains"] != "*"
        fallback = (not specific) and any(
            c["domains"] != "*" and domain in c["domains"] and lang in c["langs"]
            for c in CORPORA)
        res = {"hits": hits, "source": corpus["id"], "label": corpus["label"],
               # `ok` остаётся ЧЕСТНЫМ: он значит «корпус нашёл строку», и на нём
               # стоит подтверждение в автоодобрении. Право ЗАПРЕЩАТЬ вынесено
               # отдельным полем — иначе ноль из запасного корпуса подтверждал
               # бы термин, которого он не видел.
               "ok": hits >= MIN_ATTESTED,
               "absent": hits == 0,
               # Чем отвечали и вправе ли этот источник запрещать. Нужно
               # интерфейсу: «не найдено в Википедии» и «не найдено в PubMed» —
               # разного веса ответы, и человек должен видеть разницу.
               "domainCorpus": specific,
               "vetoAllowed": specific or not fallback}
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[key] = res
        return res
    return None


def corpus_available(tgt: str, domain: str) -> bool:
    """Есть ли вообще чем проверять эту пару. Нужно интерфейсу: пользователь
    должен видеть, чем проверялись его термины, а не гадать."""
    return bool(CORPUS_ENABLED and corpus_for((tgt or "").upper(), domain))


def stats() -> dict:
    with _CACHE_LOCK:
        return {"cached": len(_CACHE),
                "dead": [k for k, v in _DEAD_UNTIL.items() if v > time.time()]}
