# -*- coding: utf-8 -*-
"""Замер переводчиков ПО ЯЗЫКУ ПЕРЕВОДА (решение владельца 24.10.2026).

Зачем. Замер 24.10.2026 на 150 трудных медицинских строках: на RU→EN
Sonnet 5.5 и Opus 5.5 почти равны, а на узбекской кириллице у Sonnet
серьёзная ошибка в 21–30 строках из 60, у Opus — в 5 (латиница внутри
слов, протечка рассуждения в перевод, неверный термин гладким языком).
Одна модель на все языки либо переплачивает на английском, либо портит
узбекский. Поэтому переводчик выбирается для каждого языка каталога
по замеру, а замер повторяется сам, когда меняется набор моделей.

Устройство. Здесь только данные и чистые функции (без сети и STATE):
набор фраз, вопрос слепому судье, разбор ответа и правило выбора.
Сеть, деньги и запись — в `main._lang_bench_*`.

Набор фраз — трудные места, где гладкая ошибка опасна: доза и единица,
отрицание, сторона тела, узкий термин («бактериовыделение», «задний
увеит» — калька даёт правдоподобную бессмыслицу), неустойка в договоре,
порядок действий в инструкции. Оригинал — русский (основной язык
клиентов); для перевода НА русский — та же фраза по-английски.
Меняешь фразы или вопрос — поднимай VERSION: прежние замеры перестанут
быть действующими, и замер пройдёт заново."""
import json
import random
import re

VERSION = 1

SENTENCES = [
    {"domain": "medical",
     "RU": "Рифампицин назначают по 10 мг/кг массы тела в сутки, но не более 600 мг.",
     "EN": "Rifampicin is given at 10 mg/kg body weight per day, but no more than 600 mg."},
    {"domain": "medical",
     "RU": "В правом лёгком очагов не выявлено, слева — инфильтрат в S6.",
     "EN": "No foci were found in the right lung; on the left there is an infiltrate in S6."},
    {"domain": "medical",
     "RU": "Препарат не рекомендуется детям до 12 лет и беременным.",
     "EN": "The drug is not recommended for children under 12 or for pregnant women."},
    {"domain": "medical",
     "RU": "При бактериовыделении больного изолируют до конверсии мазка мокроты.",
     "EN": "A patient with bacillary excretion is isolated until sputum smear conversion."},
    {"domain": "medical",
     "RU": "Задний увеит сопровождался снижением остроты зрения до 0,3.",
     "EN": "Posterior uveitis was accompanied by a decrease in visual acuity to 0.3."},
    {"domain": "medical",
     "RU": "Пробу Манту ставят внутрикожно однограммовым туберкулиновым шприцем.",
     "EN": "The Mantoux test is given intradermally with a one-gram tuberculin syringe."},
    {"domain": "medical",
     "RU": "Если температура выше 38,5 °C держится более трёх суток, повторите анализ крови.",
     "EN": "If a temperature above 38.5 °C persists for more than three days, repeat the blood test."},
    {"domain": "medical",
     "RU": "Принимать по одной таблетке три раза в день после еды; курс — 14 дней.",
     "EN": "Take one tablet three times a day after meals; the course is 14 days."},
    {"domain": "legal",
     "RU": "Арендатор не вправе передавать помещение в субаренду без письменного согласия арендодателя.",
     "EN": "The tenant may not sublet the premises without the landlord's written consent."},
    {"domain": "legal",
     "RU": "Неустойка составляет 0,1 % от суммы долга за каждый день просрочки, но не более 10 %.",
     "EN": "The penalty is 0.1% of the debt for each day of delay, but no more than 10%."},
    {"domain": "general",
     "RU": "Перед заменой фильтра отключите насос и закройте кран подачи воды.",
     "EN": "Before replacing the filter, switch off the pump and close the water supply valve."},
    {"domain": "general",
     "RU": "Он сделал это не нарочно, хотя все решили обратное.",
     "EN": "He did not do it on purpose, although everyone concluded the opposite."},
]

JUDGE_SYSTEM = (
    "You are a senior translator and reviewer for medical, legal and technical texts. "
    "Several candidate translations of the SOURCE from {src} into {tgt} are given, labelled with "
    "letters. For EACH candidate list the errors that change or distort the meaning: a wrong term "
    "or concept (even if it reads fluently), a wrong number, unit or dose, a lost or added negation, "
    "a wrong side, omitted or added content, grammar that changes the meaning, text that is not in "
    "{tgt} or not in its normal script, comments or notes that are not part of the translation. "
    "Do NOT count style preferences. Severity: critical — could mislead a doctor, patient, lawyer "
    "or user; major — meaning distorted; minor — wording. Answer ONLY JSON: "
    "{{\"A\": [{{\"sev\": \"critical|major|minor\", \"what\": \"...\"}}], \"B\": [...], ...}} "
    "with every label present (an empty list when there are no errors).")

# Признаки служебной заметки модели в начале строки ответа («Let me…»,
# «Here is…», «Note:»). Модели пишут их по-английски на любом языке перевода.
LEAK_RE = re.compile(r"(?im)^\s*(let me\b|here is\b|here's\b|i need to\b|i'll\b|i will\b|wait\b|"
                     r"actually,|okay,|note:|final answer|corrected (translation|version)|"
                     r"translation:|the translation\b)")


def source_lang(tgt: str) -> str:
    """Язык оригинала замера: русский, а для перевода на русский — английский."""
    return "EN" if (tgt or "").upper() == "RU" else "RU"


def items(tgt: str, n: int = 0) -> list:
    """Фразы замера для языка перевода: [(оригинал, область)]."""
    src = source_lang(tgt)
    out = [(s[src], s["domain"]) for s in SENTENCES]
    return out[:n] if n else out


def labels(k: int) -> list:
    return [chr(ord("A") + i) for i in range(k)]


def shuffle_for(key: str, models: list) -> list:
    """Порядок кандидатов для судьи — свой у каждой фразы и стабильный
    (повтор замера на тех же данных даёт тот же порядок)."""
    order = list(models)
    random.Random(key).shuffle(order)
    return order


def judge_body(source: str, outs: list) -> str:
    """Тело вопроса судье: оригинал и кандидаты по буквам (без имён моделей)."""
    lines = ["SOURCE:", source, ""]
    for lab, txt in zip(labels(len(outs)), outs):
        lines += [lab + ":", txt or "(empty)", ""]
    return "\n".join(lines).strip()


def parse_judge(text: str, k: int):
    """{буква: [ошибки]} или None, если ответ неполный: судья обязан
    назвать КАЖДУЮ букву, иначе молчание читалось бы как «ошибок нет»."""
    try:
        m = re.search(r"\{.*\}", text or "", re.S)
        d = json.loads(m.group(0)) if m else None
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    out = {}
    for lab in labels(k):
        v = d.get(lab)
        if not isinstance(v, list):
            return None
        out[lab] = [e for e in v if isinstance(e, dict)]
    return out


def serious(errs: list) -> bool:
    return any((e.get("sev") or "").lower() in ("critical", "major") for e in errs or [])


def leak(source: str, out: str) -> bool:
    """Служебная заметка в ответе: пустая строка-разделитель, которой нет
    в оригинале, или строка, начатая признаком заметки, при оригинале
    в одну строку."""
    out = (out or "").replace("\r\n", "\n")
    source = (source or "").replace("\r\n", "\n")
    gap = re.compile(r"\n[ \t]*\n")
    if gap.search(out) and not gap.search(source or ""):
        return True
    return bool(LEAK_RE.search(out)) and not LEAK_RE.search(source or "") and \
        out.count("\n") > (source or "").count("\n")


def decide(table: dict, prices: dict, margin: float = 1.0) -> tuple:
    """Правило выбора: {модель: строк с серьёзной ошибкой} → (модель, почему).
    Берётся САМАЯ ДЕШЁВАЯ, чей счёт не хуже лучшего больше чем на `margin`
    строк: разница в одну строку из дюжины — шум судьи, платить за неё
    вдвое незачем. Нет данных — None."""
    have = {m: v for m, v in table.items() if v is not None}
    if not have:
        return None, "nodata"
    best = min(have.values())
    ok = [m for m, v in have.items() if v <= best + margin]
    ok.sort(key=lambda m: (prices.get(m, 1e9), have[m], m))
    pick = ok[0]
    cheapest = min(have, key=lambda m: (prices.get(m, 1e9), m))
    return pick, ("cheapest" if pick == cheapest else "quality")
