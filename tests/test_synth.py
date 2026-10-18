"""Синтетические страницы (backend/synth.py): рецепты из synth_recipes.json
проходят раскраску выгрузки и замеры fidelity. Ловит ОТКАТЫ правил раскраски;
покрытием каталога не является (оговорка — в докстроке synth.py).

Х23 сторожится здесь же: строка без нижних выносных («Results and
discussion») не красится мельче и жирнее оригинала.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import synth  # noqa: E402
import text_paint as tp  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# 1. Выносы — по шрифту, без списка букв.
check(not tp.has_descender("Results and discussion"), "без выносов: Results and discussion")
check(tp.has_descender("playing"), "выносы: playing")
check(tp.has_descender("Результаты"), "выносы: кириллица у, р")
check(not tp.has_descender("АБВ"), "без выносов: АБВ")
check(not tp.has_descender("2024"), "без букв — без выносов")

# 2. Псевдоперевод — детерминирован, имена с номерами остаются.
d = synth.load()
a = synth.pseudo("Kana Okano1 wrote this", "uz", 1.15, 0, True, d)
b = synth.pseudo("Kana Okano1 wrote this", "uz", 1.15, 0, True, d)
check(a == b, "псевдоперевод детерминирован")
check("Kana Okano1" in a, "имя с номером перенесено как есть")
check(" " not in synth.pseudo("one two", "zh", 0.6, 0, False, d), "иероглифы — без пробелов")

# 3. Рецепты: раскраска без предупреждений, кроме названных.
KNOWN = {"caption-on-tint": {"xh"}}   # однострочная подпись мельчает — кандидат в правило
for rec in d["recipes"]:
    r = synth.run(rec, 0, d)
    warn = set(r["fidelity"].get("warn") or [])
    extra = warn - KNOWN.get(rec["id"], set())
    check(r["out"] is not None, "%s: раскрашено" % rec["id"])
    check(not extra, "%s: предупреждений нет (%s)" % (rec["id"], sorted(warn)))
    if rec["id"] == "heading-colour":
        xh = r["fidelity"]["summary"].get("xh")
        check(xh is not None and xh >= 0.8, "Х23: заголовок без выносов не мельчает (xh=%s)" % xh)

print("ВСЁ ПРОШЛО" if not FAILS else "ПРОВАЛЕНО: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
