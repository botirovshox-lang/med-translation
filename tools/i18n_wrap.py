"""Обёртка русских строк фронтенда в `TR(...)` — механически и один раз.

Зачем скриптом, а не руками: строк 1682 в 600 КБ кода. Руками это не диff,
а лотерея, и пропущенная строка потом всплывает у клиента на экране.

Что скрипт НЕ трогает (и почему это важнее того, что трогает):

  * ключ объекта (`{ "новый": ... }`), операнд сравнения (`s === "новый"`),
    аргумент `includes/startsWith/indexOf/split/match`, `case "…":`,
    доступ по ключу (`x["новый"]`) — там строка работает ДАННЫМИ, а не
    надписью. Перевести её значит молча сломать фильтр, у которого нет
    ни одного видимого признака поломки;
  * шаблонную строку с подстановкой (``` `Найдено ${n}` ```) — ключом она
    быть не может, у неё нет постоянного текста. Такие места называются
    в отчёте и разбираются руками.

Отчёт печатается ВСЕГДА: и что обёрнуто, и что пропущено с причиной.
Список пропущенного — то, что человек обязан прочитать глазами.

    python tools/i18n_wrap.py --check     # только отчёт
    python tools/i18n_wrap.py --apply     # переписать файлы
"""
import re, sys, os, json, collections

CYR = re.compile(r"[А-Яа-яЁё]")
BS = chr(92)
FILES = ["api.js", "ui.jsx", "tab_import.jsx", "tab_editor_detail.jsx", "tab_editor.jsx",
         "tab_glossary_tm.jsx", "tab_export_preflight.jsx", "tab_preflight.jsx",
         "tab_org.jsx", "tab_profile.jsx", "tab_admin.jsx", "app.jsx"]
ROOT = os.path.join("frontend", "js")


def scan(src):
    """Разбор на куски: (вид, начало, конец). Вид — code | str | comment.

    Свой разборщик, а не регулярка по всему файлу: строка внутри
    комментария и комментарий внутри строки выглядят одинаково, и
    обёрнутый по ошибке комментарий — это синтаксическая ошибка, то есть
    белый экран."""
    out = []
    i, n, start = 0, len(src), 0
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(("code", start, i)); out.append(("comment", i, j))
            i = start = j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(("code", start, i)); out.append(("comment", i, j))
            i = start = j
        elif c in "\"'`":
            q, j = c, i + 1
            while j < n:
                if src[j] == BS:
                    j += 2; continue
                if src[j] == q:
                    j += 1; break
                if q == "`" and src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                    depth, j = 1, j + 2      # ${...} может содержать свои строки
                    while j < n and depth:
                        if src[j] == "{": depth += 1
                        elif src[j] == "}": depth -= 1
                        j += 1
                    continue
                j += 1
            out.append(("code", start, i)); out.append(("str", i, j))
            i = start = j
        else:
            i += 1
    out.append(("code", start, n))
    return [(k, a, b) for k, a, b in out if b > a]


SKIP_CALLS = ("includes(", "startsWith(", "endsWith(", "indexOf(", "lastIndexOf(",
              "match(", "search(", "split(", "getItem(", "setItem(", "removeItem(",
              "querySelector(", "getElementById(", "TR(", "TRS(")


def decide(src, a, b):
    """Обернуть или пропустить — и по какой причине."""
    text = src[a:b]
    if text[0] == "`" and "${" in text:
        return None, "шаблон с подстановкой — ключом быть не может"
    before = src[:a]
    pre = before.rstrip()
    after = src[b:]
    post = after.lstrip()
    if re.search(r"(TR|TRS)\($", pre):
        return None, "уже обёрнута"
    for call in SKIP_CALLS:
        if re.search(r"[.]?" + re.escape(call).replace(r"\(", r"\(") + "$", pre) and                 re.search(r"(^|[^A-Za-z0-9_$])" + re.escape(call[:-1]) + r"\($", pre):
            return None, "аргумент " + call
    # `x["ключ"]` — данные, а `["Логин", "Имя"]` — надписи. Отличаются тем,
    # что перед скобкой доступа стоит ИМЯ (или `)`/`]`), а перед литералом
    # массива — открывающая скобка, запятая, знак равенства или двоеточие.
    if pre.endswith("[") and re.search(r"[A-Za-z0-9_$)\]]\s*\[$", pre):
        return None, "доступ по ключу x[...]"
    if re.search(r"(===|!==|==|!=)\s*$", pre) or re.match(r"^(===|!==|==|!=)", post):
        return None, "операнд сравнения"
    if re.search(r"\bcase\s*$", pre):
        return None, "метка case"
    if post.startswith(":") and not post.startswith("::") and pre and pre[-1] in "{,":
        return None, "ключ объекта"
    return "TR(" + text + ")", None


def process(path):
    src = open(path, encoding="utf-8").read()
    pieces, wrapped, skipped = [], 0, []
    for kind, a, b in scan(src):
        chunk = src[a:b]
        if kind != "str" or not CYR.search(chunk):
            pieces.append(chunk)
            continue
        new, why = decide(src, a, b)
        if new is None:
            skipped.append((chunk, why))
            pieces.append(chunk)
        else:
            wrapped += 1
            pieces.append(new)
    return "".join(pieces), wrapped, skipped


def main():
    apply = "--apply" in sys.argv
    total, allskip = 0, []
    for f in FILES:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        out, wrapped, skipped = process(p)
        total += wrapped
        allskip += [(f, s, w) for s, w in skipped]
        print("%-26s обёрнуто %4d, пропущено %3d" % (f, wrapped, len(skipped)))
        if apply and wrapped:
            open(p, "w", encoding="utf-8", newline="").write(out)
    print("\nВСЕГО обёрнуто: %d" % total)
    print("ПРОПУЩЕНО (читать глазами):")
    by = collections.Counter(w for _, _, w in allskip)
    for why, n in by.most_common():
        print("  %-46s %d" % (why, n))
    for f, s, w in allskip:
        print("    [%s] %s  ← %s" % (f, s[:90].replace("\n", " "), w))


if __name__ == "__main__":
    main()
