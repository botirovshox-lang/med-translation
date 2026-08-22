#!/usr/bin/env python3
"""Сборка справочника RU→EN из Wikidata: болезни (ICD-10) и лекарства (ATC).

Зачем именно так
────────────────
Записи справочника становятся ПРИКАЗОМ для модели, поэтому источник должен
отвечать двум условиям: пары выверены людьми и понятие опознаётся не по
названию, а по коду в отраслевом классификаторе. Wikidata даёт и то, и другое:
метки правит сообщество, а якорем служит код ICD-10 (болезни), ATC (лекарства)
или MeSH (медицинские понятия) — то есть в выборку попадают только те понятия,
которые существуют в отраслевом классификаторе, а не любые статьи.

Чего этот источник НЕ делает: он не переводит. Совпадение со справочником
срабатывает, только если кандидат УЖЕ предложил ровно этот перевод, — то есть
модель и справочник должны сойтись независимо друг от друга.

Отсев неоднозначного
────────────────────
Если у русского термина в выгрузке оказалось два разных английских (или
наоборот), пара выбрасывается целиком. Именно так уходит мусор вида
«лимфатическая мальформация → vascular malformation»: у понятия там несколько
меток, и приказом такое быть не может. Неоднозначный термин — это то, что
решает человек, а не справочник.

Запуск (нужен интернет, ~2-3 минуты):
    python backend/authority_data/fetch_wikidata.py
Результат: wikidata_ru_en_medical.tsv рядом со скриптом.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "MedicalCATTranslator/1.0 (terminology import; contact via repository)"

# Три якоря — три класса понятий. Свойство в WHERE и есть гарантия, что
# понятие существует в классификаторе.
BLOCKS = [
    ("ICD-10", "wdt:P494"),     # болезни и состояния
    ("ATC",    "wdt:P267"),     # лекарственные средства (названия = МНН/INN)
]
# MeSH (wdt:P486) сюда НЕ входит намеренно. Это тезаурус широкого охвата:
# вместе с медициной он приносит «голосование → voting», «бухгалтерский учёт →
# accounting», названия стран и родов растений. Переводы там верные, но
# справочнику с пометкой «медицина, фарма» такие записи не место: источник
# должен отвечать за свою область, а не за всё подряд. ICD-10 и ATC дают ровно
# то, ради чего справочник и нужен, — болезни и лекарства.

QUERY = """
SELECT DISTINCT ?ru ?en WHERE {
  ?item %s ?code .
  ?item rdfs:label ?ru FILTER(lang(?ru)='ru') .
  ?item rdfs:label ?en FILTER(lang(?en)='en') .
}
ORDER BY ?ru ?en
LIMIT %d OFFSET %d
"""

PAGE = 5000


def fetch(where: str, offset: int) -> list:
    q = QUERY % (where, PAGE, offset)
    url = ENDPOINT + "?format=json&query=" + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))["results"]["bindings"]


def fetch_page(label: str, where: str, offset: int):
    """(строки, удалось ли). Отказ и «данные кончились» — РАЗНЫЕ вещи: приняв
    первое за второе, скрипт молча обрезает справочник и рапортует успех.
    Публичный эндпоинт временами режет до одного запроса в минуту — ждём."""
    for attempt in range(1, 6):
        try:
            return fetch(where, offset), True
        except Exception as e:
            msg = str(e)
            print(f"  {label} offset={offset}, попытка {attempt}: {msg[:90]}", file=sys.stderr)
            if attempt == 5:
                return [], False
            time.sleep(65 if "429" in msg else 10)
    return [], False


def norm(t: str) -> str:
    """Ключ сравнения. Нижний регистр обязателен: без него «Анемия» и «анемия»
    считаются разными смыслами, и верная пара выбрасывается как неоднозначная —
    ровно так из выгрузки пропадали сахарный диабет, инсульт и анемия."""
    return " ".join((t or "").lower().replace("ё", "е").split())


# Служебные узлы Wikidata: шаблоны, категории, сами коды классификаторов.
# Это строительные леса базы, а не термины.
SERVICE = re.compile(r"^(шаблон|template|категория|category|список|list|"
                     r"атх\s*код|анатомо|мкб-?\d+|icd-?\d+|q\d+)\b", re.I)
# Стереохимический префикс в английском без такого же в русском означает, что
# метка уточняет изомер, а исходный термин — нет. «молочная кислота» — это
# «lactic acid», а не «DL-lactic acid»: как приказ это прямая ошибка.
STEREO = re.compile(r"(^|[\s(])((DL|LD|[DLRS])|\([RS]\)|alpha|beta|cis|trans)[-‑]", re.I)


def acceptable(ru: str, en: str) -> bool:
    """Отсев того, что термином не является либо является НЕ ТЕМ термином.

    Каждое правило здесь — про приказ: попавшая сюда строка будет предъявлена
    модели как норма, и «почти правильно» тут хуже, чем «нет записи»."""
    if len(ru) < 3 or len(en) < 3:
        return False
    if len(ru.split()) > 4 or len(en.split()) > 5:
        return False           # описание, а не термин
    if SERVICE.match(ru) or SERVICE.match(en):
        return False
    if not re.search(r"[А-Яа-яЁё]", ru) or not re.search(r"[A-Za-z]", en):
        return False
    # Кириллица в английской метке или латиница в русской — либо метка не
    # переведена, либо в ней омоглифы («cиндром» с латинской c), и совпасть
    # с настоящим текстом такая запись не может никогда.
    if re.search(r"[А-Яа-яЁё]", en) or re.search(r"[A-Za-z]", ru):
        return False
    if STEREO.search(en) and not STEREO.search(ru):
        return False
    # «HIV/AIDS» на «синдром приобретённого иммунного дефицита» — это два
    # понятия через слэш, а не перевод одного.
    if "/" in en and "/" not in ru:
        return False
    return True


def main():
    ru2en, en2ru = {}, {}
    best_ru, best_en = {}, {}        # нормализованное → как писать в файл
    total = 0
    failed = []          # что не догрузилось — обязано быть названо
    for label, where in BLOCKS:
        offset, got = 0, PAGE
        while got == PAGE:
            rows, ok = fetch_page(label, where, offset)
            if not ok:
                failed.append(f"{label} начиная с offset={offset}")
                break
            got = len(rows)
            for r in rows:
                ru, en = r["ru"]["value"].strip(), r["en"]["value"].strip()
                if not acceptable(ru, en):
                    continue
                # Ключ И значение нормализованные: иначе «Анемия» и «анемия»
                # считаются разными смыслами, и верная пара выбрасывается как
                # неоднозначная. Ровно так из выгрузки пропали сахарный диабет,
                # инсульт, анемия и бронхиальная астма.
                ru2en.setdefault(norm(ru), set()).add(norm(en))
                en2ru.setdefault(norm(en), set()).add(norm(ru))
                best_ru.setdefault(norm(ru), ru)
                best_en.setdefault(norm(en), en)
                total += 1
            offset += got
            print(f"  {label}: {offset} строк получено, пар {len(ru2en)}", file=sys.stderr)
            time.sleep(2)       # вежливость к публичному эндпоинту

    # Однозначность в ОБЕ стороны: приказ не может быть двусмысленным.
    pairs = []
    dropped_ru = dropped_en = 0
    for ru, ens in sorted(ru2en.items()):
        if len(ens) != 1:
            dropped_ru += 1
            continue
        en = next(iter(ens))
        if len(en2ru.get(en, ())) != 1:
            dropped_en += 1
            continue
        pairs.append((best_ru.get(ru, ru), best_en.get(en, en)))

    out = Path(__file__).with_name("wikidata_ru_en_medical.tsv")
    if failed and out.exists():
        # Недогруженная выгрузка НЕ затирает полный справочник: молча заменить
        # три тысячи приказов на восемьсот — это дыра в проверке терминов,
        # которую никто не заметит. Пишем рядом, решение оставляем человеку.
        # Расширение НЕ .tsv: каталог глобится загрузчиком, и «.partial.tsv»
        # подхватился бы наравне с полным файлом — а в обрезанной выгрузке
        # термины выглядят однозначными только потому, что вторая половина
        # данных не доехала.
        out = out.with_name(out.name + ".partial")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# label: Wikidata — болезни (ICD-10) и лекарства (ATC)\n")
        f.write("# lang: RU→EN\n")
        f.write("# domains: medical, pharma\n")
        # tier: auto — метки Wikidata правит сообщество, и выборочная проверка
        # находит неверные нормы («Анизакидоз → Anisakis» — болезнь против рода
        # паразита). Такой источник не вправе приказывать модели в одиночку: он
        # идёт подсказкой и подтверждающим голосом рядом с согласием сегментов
        # и корпусом. Приказ (# tier: verified) — только у выверенного источника.
        f.write("# tier: auto\n")
        f.write("# Собрано backend/authority_data/fetch_wikidata.py.\n")
        f.write("# Только однозначные в обе стороны пары: если у термина нашлось\n")
        f.write("# несколько соответствий, он выброшен — приказ не может быть\n")
        f.write("# двусмысленным, такие термины решает человек.\n")
        for ru, en in pairs:
            f.write(f"{ru}\t{en}\n")

    if failed:
        # Молчаливых потолков не бывает: недогруженный справочник — дыра
        # в приказах, и знать о ней надо до того, как он поедет в продакшн.
        print("\nНЕ ДОГРУЖЕНО: " + "; ".join(failed))
        print("Справочник неполон — перезапустите скрипт позже.")
    print(f"\nстрок получено: {total}")
    print(f"выброшено неоднозначных: {dropped_ru} (RU→много EN) + {dropped_en} (EN→много RU)")
    print(f"записано пар: {len(pairs)} → {out.name}")


if __name__ == "__main__":
    main()
