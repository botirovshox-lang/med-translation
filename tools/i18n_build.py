"""Сборка словарей: frontend/i18n/<код>.*.json → frontend/js/i18n_<код>.js.

Почему источник — JSON, а на страницу уезжает .js: сборки у фронтенда нет,
файлы грузятся тегами `<script>`, а JSON тегом не подключить — пришлось бы
тянуть его fetch'ем ДО первого рендера, то есть завести асинхронный шаг там,
где сегодня его нет. Зато править и сравнивать удобнее JSON, поэтому он
и остаётся источником правды, а .js — собранный из него файл.

Части разложены по областям экрана (uz.core, uz.editor, …), а не одним
файлом: в одном файле на 1700 строк не видно, что именно поменялось.

Языки НЕ перечислены здесь списком намеренно: они выводятся из имён файлов
(`en.core.json` → язык `en`). Список в коде пришлось бы править при каждом
новом языке — и первый же забытый язык собирался бы молча пустым.
Русского словаря нет и не будет: ключ и есть русская строка.

    python tools/i18n_build.py
"""
import json, os, glob, sys, re

SRC = os.path.join("frontend", "i18n")
OUT = os.path.join("frontend", "js", "i18n_%s.js")

# Терминология по языкам — держать её единой по всему интерфейсу.
# Лежит в ШАПКЕ собранного файла, потому что читают её там же, где правят
# перевод, а не в документации, до которой не дойдут.
TERMS = {
    "uz": """     сегмент → segment            глоссарий → lug'at
     термин → atama               память переводов → tarjima xotirasi
     прогон → ishlov              ремонт → ta'mir
     находка → topilma            замечание → kamchilik
     приказ (verified) → buyruq   подсказка (auto) → maslahat
     обратный перевод → teskari tarjima
     судья → hakam                арбитр → arbitr
     организация → tashkilot      команда → jamoa
     владелец → egasi             переводчик → tarjimon""",
    "en": """     сегмент → segment            глоссарий → glossary
     термин → term                память переводов → translation memory
     прогон → run                 ремонт → repair
     находка → finding            замечание → issue
     приказ (verified) → verified подсказка (auto) → hint
     обратный перевод → back-translation
     судья → judge                арбитр → arbiter
     организация → organization   команда → team
     владелец → owner             переводчик → translator""",
}

HEAD = """/* ============================================================
   Словарь интерфейса: %(name)s.

   СОБРАН из frontend/i18n/%(code)s.*.json — правь ИХ и пересобирай:

       python tools/i18n_build.py

   Ключ словаря — сама русская строка из кода. Отсюда два свойства,
   на которых всё держится:

     * нет перевода — на экране остаётся русский оригинал, а не пустота
       (см. i18n.js): непереведённая надпись хотя бы честна;
     * на русском языке TR(s) === s побитово, то есть включённый перевод
       НИЧЕГО не меняет в поведении экранов.

   Пробелы по краям ключа значимы: строки склеиваются с числами и именами
   («Повторов: » + n). Перевод обязан их сохранять — иначе слипнется.

   Терминология (держать единой по всему интерфейсу):
%(terms)s
   ============================================================ */
"""

NAMES = {"uz": "узбекский (латиница)", "en": "английский"}


def languages():
    """Языки — по именам частей словаря, а не списком в коде."""
    codes = set()
    for p in glob.glob(os.path.join(SRC, "*.*.json")):
        m = re.match(r"^([a-z]{2})\.", os.path.basename(p))
        if m:
            codes.add(m.group(1))
    return sorted(codes)


def build(code):
    parts = sorted(glob.glob(os.path.join(SRC, code + ".*.json")))
    if not parts:
        print("нет частей словаря для «%s» в %s" % (code, SRC), file=sys.stderr)
        return 1
    table, server, dupes = {}, {}, []
    for p in parts:
        data = json.load(open(p, encoding="utf-8"))
        # Куски сообщений СЕРВЕРА идут своей таблицей: из неё TRS() собирает
        # фразовую подстановку, и мешать их с надписями интерфейса нельзя.
        into = server if os.path.basename(p) == code + ".server.json" else table
        for k, v in data.items():
            if k == "_":                    # пояснение части, не перевод
                continue
            if k in into and into[k] != v:
                dupes.append((k, os.path.basename(p)))
            into[k] = v
    if dupes:
        print("ОДИН ключ переведён по-разному в разных частях (%s):" % code)
        for k, p in dupes:
            print("  %s  (%s)" % (k[:60], p))
        return 1
    out = OUT % code
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(HEAD % {"code": code, "name": NAMES.get(code, code),
                         "terms": TERMS.get(code, "     —")})
        fh.write("window.I18N.register(\"%s\", " % code)
        fh.write(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True))
        fh.write(");\n\n")
        fh.write("window.I18N.registerServer(\"%s\", " % code)
        fh.write(json.dumps(server, ensure_ascii=False, indent=1, sort_keys=True))
        fh.write(");\n")
    print("%s: %d надписей + %d кусков сервера из %d частей → %s"
          % (code, len(table), len(server), len(parts), out))
    return 0


def main():
    codes = languages()
    if not codes:
        print("нет частей словаря в " + SRC, file=sys.stderr)
        return 1
    rc = 0
    for code in codes:
        rc |= build(code)
    return rc


if __name__ == "__main__":
    sys.exit(main())
