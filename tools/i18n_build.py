"""Сборка словаря: frontend/i18n/uz.*.json → frontend/js/i18n_uz.js.

Почему источник — JSON, а на страницу уезжает .js: сборки у фронтенда нет,
файлы грузятся тегами `<script>`, а JSON тегом не подключить — пришлось бы
тянуть его fetch'ем ДО первого рендера, то есть завести асинхронный шаг там,
где сегодня его нет. Зато править и сравнивать удобнее JSON, поэтому он
и остаётся источником правды, а .js — собранный из него файл.

Части разложены по областям экрана (uz.core, uz.editor, …), а не одним
файлом: в одном файле на 1700 строк не видно, что именно поменялось.

    python tools/i18n_build.py
"""
import json, os, glob, sys

SRC = os.path.join("frontend", "i18n")
OUT = os.path.join("frontend", "js", "i18n_uz.js")
HEAD = """/* ============================================================
   Узбекский словарь интерфейса (латиница).

   СОБРАН из frontend/i18n/uz.*.json — правь ИХ и пересобирай:

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
     сегмент → segment            глоссарий → lug'at
     термин → atama               память переводов → tarjima xotirasi
     прогон → ishlov              ремонт → ta'mir
     находка → topilma            замечание → kamchilik
     приказ (verified) → buyruq   подсказка (auto) → maslahat
     обратный перевод → teskari tarjima
     судья → hakam                арбитр → arbitr
     организация → tashkilot      команда → jamoa
     владелец → egasi             переводчик → tarjimon
   ============================================================ */
"""


def main():
    parts = sorted(glob.glob(os.path.join(SRC, "uz.*.json")))
    if not parts:
        print("нет частей словаря в " + SRC, file=sys.stderr)
        return 1
    table, server, dupes = {}, {}, []
    for p in parts:
        data = json.load(open(p, encoding="utf-8"))
        # Куски сообщений СЕРВЕРА идут своей таблицей: из неё TRS() собирает
        # фразовую подстановку, и мешать их с надписями интерфейса нельзя.
        into = server if os.path.basename(p) == "uz.server.json" else table
        for k, v in data.items():
            if k == "_":                    # пояснение части, не перевод
                continue
            if k in into and into[k] != v:
                dupes.append((k, os.path.basename(p)))
            into[k] = v
    if dupes:
        print("ОДИН ключ переведён по-разному в разных частях:")
        for k, p in dupes:
            print("  %s  (%s)" % (k[:60], p))
        return 1
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write(HEAD)
        fh.write("window.I18N.register(\"uz\", ")
        fh.write(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True))
        fh.write(");\n\n")
        fh.write("window.I18N.registerServer(\"uz\", ")
        fh.write(json.dumps(server, ensure_ascii=False, indent=1, sort_keys=True))
        fh.write(");\n")
    print("собрано %d надписей + %d кусков сервера из %d частей → %s"
          % (len(table), len(server), len(parts), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
