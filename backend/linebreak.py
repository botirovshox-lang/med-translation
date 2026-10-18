"""Х22. Кинсоку из данных (`backend/line_break.json`), одно место на всех.

Наборы знаков «строку не начинает» / «строку не кончает» жили тремя копиями:
у субтитров (`media._NO_START`, `_NO_END`), у надписей на картинках
(`image_text._NO_LINE_START`) — и разошлись (у картинок не было маленьких
кан и знаков повтора, у субтитров — процента), а у выгрузки PDF их не было
вовсе: японская строка в PDF начиналась с «。» или кончалась «「».
"""
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "line_break.json"
_D = json.loads(_PATH.read_text(encoding="utf-8"))

NO_START = frozenset(_D["no_start"])                    # JLREQ: не начинают строку
CLOSING_QUOTES = frozenset(_D["closing_quotes"])        # закрывающие кавычки
POSTFIX = frozenset(_D["postfix"])                      # знак после числа (UAX14 PO)
NO_END = frozenset(_D["no_end"])                        # не кончают строку
NO_START_ALL = NO_START | CLOSING_QUOTES | POSTFIX


def fix_break(word: str, n: int) -> int:
    """Разрез слова без пробелов перед знаком `n` с учётом кинсоку: строка не
    начинается знаком из `NO_START_ALL` и не кончается знаком из `NO_END`.
    Разрез сдвигается НАЗАД (знак уходит на следующую строку вместе
    с соседом); сдвигать некуда — прежний разрез."""
    m = n
    while 1 < m < len(word) and (word[m] in NO_START_ALL or word[m - 1] in NO_END):
        m -= 1
    return m if m > 1 else n
