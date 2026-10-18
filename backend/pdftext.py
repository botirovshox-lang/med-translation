"""Текстовый слой PDF → абзацы документа. Без единого вызова модели.

Текстовый слой книги, отсканированной и распознанной издателем или
сканером, — это не текст, а его ОТПЕЧАТОК на строках: слова разрезаны
переносами, на каждой странице стоят колонтитул и номер, буквица
потеряна, орнамент между главами распознан как «к к к», а обложка —
как «Священник Алексдкдр ЛлзсБкыа». Отдать такое переводу значит
оплатить перевод мусора и получить назад мусор.

Замер на боевой книге (Лазебный, «Пчелиная аптека», 378 страниц,
590 тыс. знаков): 3576 мягких переносов U+00AD внутри слов, 286
переносов по дефису на конце строки (после них строчная буква в 3716
случаях против 14 заглавных), двухстрочный колонтитул на 86 страницах
и однострочный на 149, 292 строки-номера страницы, 37 строк орнамента,
7 потерянных буквиц («стрый  ларингит» → «Острый ларингит»), две
страницы обложки с 21 % и 7 % мусорных слов при медиане 0 % по книге.

Правила НЕ знают языка: слово — это буквы по Юникоду, буквица
восстанавливается по СЛОВАРЮ САМОГО ДОКУМЕНТА, перенос по дефису
сверяется с ним же (составное слово с дефисом встречается в книге
и посреди строки, разрезанное переносом — нет). Колонтитул — строка,
стоящая в ВЕРХНИХ строках многих страниц, и ТОЛЬКО там: строка
«Показания к возможному использованию пчелоужалений:» повторяется
80 раз, но это структура текста, а не колонтитул, — её выдаёт доля
попаданий в верхнее окно. Страница с ненадёжным слоем (обложка,
художественный титул) НЕ вычищается построчно — она кладётся
КАРТИНКОЙ, и текст с неё читает зрячая модель тем же путём, что
у скана: вычищенная обложка — это половина слов, которых не было.

Что НЕ делается намеренно: не исправляются буквы внутри слов
(«неспе.цифические», «сеой») — угадывать слово по словарю значит
однажды подменить одно слово другим; такое остаётся переводу, он
читает по контексту. Число всего снятого называется в отчёте.
"""
from __future__ import annotations

import bisect
import difflib
import functools
import math
import os
import re
import statistics
import unicodedata
from collections import Counter

SOFT = "­"

# ─── Знаки математики: ОДИН список на систему ────────────────────────
# Берётся не рукописным перечнем, а РАЗДЕЛАМИ Юникода: «Mathematical
# Operators» (U+2200–U+22FF) целиком — там и интеграл ∫, и корень √, и
# сумма ∑, и произведение ∏, и бесконечность ∞, и знаки сравнения ≤ ≥ ≠ ≈;
# плюс «Supplemental Mathematical Operators» (U+2A00–U+2AFF), «Miscellaneous
# Mathematical Symbols» (U+27C0–U+27EF), стрелки (U+2190–U+21FF), дробная
# черта U+2044 и одиночные ASCII/Latin-1 знаки, которые Юникод относит к тому
# же классу Sm (+ < = > ~ | ± × ÷), плюс градус, штрих и промилле.
# Перечислять знаки руками нельзя: первый же забытый («∛», «⨌», «≢») вёл бы
# себя не как знак, а как украшение — и снимался бы молча.
#
# Этот список читает и `checks.broken_math` (повреждённая формула): две
# таблицы разошлись бы первой же правкой, а тогда чистка снимала бы знак,
# про который проверка думает, что он на месте.
MATH_CHAR_RE = re.compile(
    "[+<=>~|"
    "\u00b1\u00d7\u00f7"                    # ± × ÷
    "\u00b0\u2030\u2031\u2032\u2033\u2034"   # ° ‰ ‱ ′ ″ ‴
    "\u2044"                                  # ⁄ дробная черта
    "\u2190-\u21ff"                          # стрелки
    "\u2200-\u22ff"                          # операторы: ∫ √ ∑ ∏ ∞ ≤ ≥ ≠ ≈ ∂ ∇ ∈
    "\u27c0-\u27ef"
    "\u2a00-\u2aff]")
# Операторы, у которых предел пишется НАД и ПОД знаком: их пределы бывают
# буквами («∫ₐᵇ», «∑ₙ₌₁»), а короткий буквенный кусок сам по себе — это
# обрывок рисунка у края страницы (`_edge_scrap`), и забирать его нельзя.
MATH_LIMIT_OPS = frozenset("\u222b\u222c\u222d\u222e\u222f\u2230"
                           "\u2211\u220f\u2210\u2a0b\u2a0c")

# Версия правил разбора. Пишется на проект при импорте (`parseRules`),
# и проект, нарезанный правилами постарше, экран предлагает пересобрать
# из хранимого исходника (`/api/projects/{pid}/resegment`). Меняешь правила
# так, что меняются абзацы, — поднимай: 1 — построчный разбор, 2 — по
# геометрии, 3 — обрывки у края, «по-»/«лис», метки врезок, разворот,
# 4 — над- и подстрочные куски (дроби, степени, индексы) на своём месте
# и повреждённый знак математики, который больше не снимается орнаментом,
# 5 — знаки математики по списку Юникода: интеграл, корень, сумма, знаки
# сравнения; их пределы-буквы, крупный знак не считается украшением,
# а знак у числа («±0,5», «<5») не снимается с края токена,
# 6 — рисунки внутри страницы переносятся в документ вырезкой из неё:
# абзацев это не меняет, но состав документа меняет, и пересобрать
# прежние проекты надо кнопкой «Чтение файла улучшено»,
# 7 — колонтитулы переводимыми абзацами,
# 8 — повёрнутая строка (подпись в схеме, повёрнутая таблица) больше
# не лишает геометрии ВСЮ страницу: она встаёт отдельной вставкой, а
# остальное идёт по местам; у рамки абзаца — гарнитура (sans/serif/mono),
# 9 — абзац рвётся там, где следующая строка геометрически его не
# продолжает (подписи схемы с разных концов листа), строка pypdf с двумя
# надписями одной базовой линии делится по местам (`split`), невидимый
# и повёрнутый текст — своими пачками. Дальше версии — в разделах
# docs/rules/pdf-reading.md; 15 — раздел С: строки таблицы (Т6), знаки
# сравнения и сноски (Т7), капс «MLTCs» (Т8), над- и подстрочные знаки
# Юникодом (Т9), колонтитул по месту на листе, в том числе повёрнутый (Т15),
# и правила того же раздела, сделанные следом; 16 — Т34: линии таблицы,
# нарисованные обводкой, режут строку по ячейкам и абзац по рядам;
# 17 — раздел Ц: «ложный полужирный» одной копией (Ц1), колонтитул по месту
# (Ц2), две надписи в одном куске и цепочка операторов (Ц3), надстрочники
# авторов и аффилиаций (Ц4, Ц5), сноска не продолжается на следующей
# странице (Ц6), таблица в своей колонке (Ц7), красная строка и разрез
# адреса (Ц9).
RULES_VERSION = 17

# Перенос строки внутри слова: мягкий перенос ВСЕГДА (для того и стоит),
# дефис — когда продолжение начинается со строчной буквы.
# Номер страницы: число либо НАСТОЯЩЕЕ римское число (не «mild», «civil»,
# «dim» — те тоже из букв i v x l c d m); точки на конце нет намеренно:
# «1.» — маркер списка, а не номер.
_NUM_LINE_RE = re.compile(
    r"^[\-–—\s]*(?:\d{1,4}|(?=[ivxlcdm])m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))[\-–—\s]*$",
    re.IGNORECASE)
# Орнамент и мусор распознавания: «* * *», «к к к», «■ ■», «•к к *», «Л ) . — 1 «■».
_ORNAMENT_CHARS = set("*■□▪▫♦◆●○•◦✦✧✶✷※~^|<>#$&@\\{}¥±§©®")
_UNDERSCORE_RE = re.compile(r"_{3,}")
_WS_RE = re.compile(r"[ \t ]+")
# Имя глифа вместо буквы: у шрифта без таблицы ToUnicode pypdf отдаёт
# «/uni0056/uni0069…» — «Vi…». Боевой проект 14: «View Online Article»
# стоял в строке именами глифов, а «BMI /uni226530 kg/m2» терял знак «≥»
# — то есть менялся СМЫСЛ, а не только вид. Только форма `uniXXXX` (Adobe
# Glyph List) и никогда внутри адреса: «…/uni1234/…» в ссылке — путь,
# а не глиф.
_GLYPH_NAME_RE = re.compile(r"/uni([0-9A-Fa-f]{4})")
_URLISH_RE = re.compile(r"://|^www\.", re.IGNORECASE)


def _glyph_names(line: str) -> str:
    if "/uni" not in line:
        return line

    def one(m):
        ch = chr(int(m.group(1), 16))
        if ch.isspace():
            return " "
        return ch if ch.isprintable() else m.group(0)

    def tok(m):
        t = m.group(0)
        return t if _URLISH_RE.search(t) else _GLYPH_NAME_RE.sub(one, t)
    return re.sub(r"\S+", tok, line)


# Текст ВРАЗРЯДКУ (межбуквенный интервал Tc: заголовок инфографики,
# выключенная по ширине строка): pypdf ставит пробел между КАЖДОЙ буквой.
# Граница слов при этом видна: внутри слова пробел одиночный, между
# словами — двойной («s e r v e s  o r  h a s»), а у прописных стык слов
# бывает и вовсе без пробела — две буквы токеном («AH O L I S T I C» =
# «A» + «HOLISTIC»). Серия из LETTERSPACE_MIN токенов, почти сплошь
# одиночных знаков, собирается обратно по этим двум признакам. Проект 14:
# «P.T. s e r v e s o r h a s …» шло в сегмент и перевод вразрядку,
# а таблица редактора распиралась строкой без единого места переноса.
LETTERSPACE_MIN = 8
LETTERSPACE_SINGLES = 0.75
_LS_TOK_RE = re.compile(r"\S+")


def _unspace(line: str) -> str:
    if line.count(" ") < LETTERSPACE_MIN:
        return line
    toks = [(m.start(), m.end(), m.group(0)) for m in _LS_TOK_RE.finditer(line)]
    if len(toks) < LETTERSPACE_MIN:
        return line
    out = []                      # (начало, конец, текст) готовых кусков
    k = 0
    while k < len(toks):
        j = k
        while j < len(toks) and len(toks[j][2]) <= 2:
            j += 1
        run = toks[k:j]
        # Буквы, а не цифры: «1 2 3 4 5 6 7 8 9» — шапка таблицы, шкала,
        # и склеить её значит испортить числа. И признак слов обязан БЫТЬ
        # (двойной пробел либо стык двух прописных): «A B C D E F G H» —
        # перечень, а не разрядка. Цифра внутри серии («TYPE 2») — её часть.
        singles = sum(1 for t in run if len(t[2]) == 1 and t[2].isalpha())
        alpha = sum(1 for t in run if any(c.isalpha() for c in t[2]))
        marks = any(b[0] - a[1] >= 2 for a, b in zip(run, run[1:])) or any(
            len(t[2]) == 2 and t[2].isalpha() and t[2].isupper() for t in run)
        if (len(run) >= LETTERSPACE_MIN and singles >= LETTERSPACE_SINGLES * len(run)
                and alpha >= 0.9 * len(run) and marks):
            word = run[0][2]
            if len(word) == 2 and word.isalpha() and word.isupper():
                word = word[0] + " " + word[1]
            for (s0, e0, t0), (s1, e1, t1) in zip(run, run[1:]):
                gap = s1 - e0
                piece = t1
                if len(t1) == 2 and t1.isalpha() and t1.isupper():
                    piece = t1[0] + " " + t1[1]      # стык слов без пробела
                word += (" " if gap >= 2 else "") + piece
            out.append((run[0][0], run[-1][1], word))
            k = j
        else:
            out.append(toks[k])
            k += 1
    res, pos = "", 0
    for s0, e0, t0 in out:
        res += line[pos:s0] + t0
        pos = e0
    return res + line[pos:]


# Маркер пункта списка, прилипший к первому слову («•Early-onset»): чистка
# мусора снимает его вместе со всеми украшениями, и пункт печатался без
# маркера. Знак запоминается на абзаце (`bulch` → рамка `bullet`), а текст
# сегмента остаётся прежним — перевод заново не нужен.
_TEXT_BULLET_RE = re.compile(r"^\s*([•▪◦●■♦])\s*(?=\S)")
_BULLET_RE = re.compile(r"^(?:[♦•■▪●○◦✓✔–—-]|\d{1,3}[.)]|[a-zа-яё][.)])\s+\S")
# Конец абзаца по знаку — как у прежней склейки в importers.
_END_RE = re.compile(r"[.!?…:;»”\")\]]\s*$")
# Вторая строка ячейки первой колонки таблицы — не дальше стольких кеглей
# от первой (`_table_streams`, Т6).
TABLE_CONT_LEAD = 2.5
PARA_MAX = 1200

# Пороги ненадёжного слоя. Медиана мусора по боевой книге — 0 %, 95-й
# процентиль — 0,8 %; обложки дали 21 % и 7 %. Отдельно — доля ОДИНОЧНЫХ
# букв: художественный титул рассыпается на «а», «т», «д» (36 % и 33 %
# на обложках против единиц процентов в тексте).
PAGE_JUNK_SHARE = 0.05
PAGE_SINGLE_SHARE = 0.30
PAGE_MIN_TOKENS = 10
# …и не меньше стольких штук в абсолюте: одна строка «HbA1c, IgG4, S1-S2»
# на странице в сто слов не делает страницу обложкой.
PAGE_JUNK_MIN = 6
# Колонтитул: строка стоит в верхнем окне не меньше чем на трёх страницах,
# и не меньше половины всех её появлений — именно там.
HEAD_WINDOW = 3
FOOT_WINDOW = 2
HEAD_MIN_PAGES = 3
HEAD_TOP_SHARE = 0.5
HEAD_MAX_LEN = 80
HEAD_MIN_LEN = 3
# Нечёткое узнавание колонтитула: доля совпавших букв и минимум букв
# в строке (на боевой книге ошибки распознавания колонтитула — одна-две
# буквы на двадцать: «Апцтоксинотерапия», «Апитоксинвтерапия»).
HEAD_FUZZY = 0.8
HEAD_FUZZY_MIN = 8
# Заголовок среди строк: короткая строка, после которой абзац начинается
# с заглавной, либо строка КАПСОМ.
HEADING_LEN_SHARE = 0.55
# Дефис на конце строки, который СВОЙ, даже если составное слово нигде
# больше не встретилось: частицы и приставки, которые в русском пишутся
# только через дефис. Список русский и короткий — для остальных языков
# решает словарь документа.
_HYPHEN_RIGHT = frozenset(("то", "либо", "нибудь", "ка", "таки", "де", "с"))
_HYPHEN_LEFT = frozenset(("по", "кое", "кой", "во", "в"))
# «по-» и «во-/в-» держат дефис только перед НАРЕЧНОЙ формой: «по-моему»,
# «по-русски», «по-лисьи», «во-первых», «в-третьих». Иначе это перенос
# слова: «по-» / «лис» на стыке страниц (боевая стр. 67–68) — «полис»,
# а не «по-лис».
_HYPHEN_LEFT_FORM = {"по": re.compile(r"(?:ому|ему|ски|цки|ьи)$"),
                     "во": re.compile(r"(?:ых|их)$"), "в": re.compile(r"(?:ых|их)$")}


def _letters(tok: str) -> list:
    return [c for c in tok if c.isalpha()]


def _script(ch: str) -> str:
    return unicodedata.name(ch, "?").split(" ")[0]


_CASE_FLIP_RE = re.compile(r"[^\W\d_A-ZА-ЯЁ][A-ZА-ЯЁ]")
_PART_SPLIT_RE = re.compile(r"[-/+·]")
# Сокращения с цифрами и переменным регистром — не мусор: «HbA1c», «IgG»,
# «pH», «ЭхоКГ», «мРНК», «COVID-19», «2HRZE/4HR», «S1-S2», «CD4+». Мусор
# распознавания отличается ДЛИНОЙ: «ЛлзсБкыа», «пчепоуЖдпении», «ПрОДуК1Ы»
# — длинные слова с прыгающим регистром или цифрой посреди.
ABBR_MAX_LETTERS = 5


def _part_kind(part: str):
    letters = _letters(part)
    if not letters:
        return None
    has_digit = any(c.isdigit() for c in part)
    if len(letters) == 1 and len(part) <= 2 and not has_digit:
        return "single"                    # «Т5», «В6» — сокращение, не одиночная буква
    flips = len(_CASE_FLIP_RE.findall(part))
    if len(letters) <= ABBR_MAX_LETTERS and (has_digit or flips):
        return "abbr"                      # «HbA1c», «pH», «мРНК», «ЭхоКГ»
    if has_digit:
        return "junk"                      # «ПрОДуК1Ы», «ТУБЕРКУЛЕЗА16» — цифра в длинном слове
    if flips >= 2 or (flips == 1 and len(letters) >= 6):
        return "junk"                      # «ЛлзсБкыа», «пчепоуЖдпении», «НАуЧИО»
    if len({_script(c) for c in letters}) > 1:
        return "junk"                      # «IIмедяная», «кулинарииjMk»
    return "word"


def _token_kind(tok: str):
    """None — не буквы вовсе; 'single' — одна буква; 'abbr' — сокращение
    с цифрой или переменным регистром (нейтрально); 'junk' — похоже на мусор
    распознавания; 'word' — слово. Токен режется по дефису, косой и плюсу:
    «COVID-19», «2HRZE/4HR», «β-лактам» оцениваются по частям."""
    s = tok.strip(".,;:!?()«»\"'—–…[]")
    parts = [x for x in _PART_SPLIT_RE.split(s) if x] or [s]
    kinds = [_part_kind(x) for x in parts]
    kinds = [k for k in kinds if k]
    if not kinds:
        return None
    if "junk" in kinds:
        return "junk"
    if "word" in kinds:
        return "word"
    if "abbr" in kinds:
        return "abbr"
    return "single" if len(kinds) == 1 else "abbr"


def _is_ornament(line: str) -> bool:
    """«* * *», «к к к», «•к к *»: строка из одиночных знаков — не больше
    ОДНОЙ разной буквы («к к к» — распознанные звёздочки), либо строка
    со знаком орнамента, где ни в одном токене больше одной буквы.
    «и т. д.», «А Б В» — не орнамент: разные буквы, точки, нет знаков."""
    toks = line.split()
    if len(toks) < 2 or len(toks) > 8 or any(c.isdigit() for c in line):
        return False
    distinct = {c.lower() for c in line if c.isalpha()}
    if len(distinct) > 1:
        return False
    if all(len(t) == 1 for t in toks):
        return True
    return (any(c in _ORNAMENT_CHARS for c in line)
            and all(len(t) <= 2 and sum(c.isalnum() for c in t) <= 1 for t in toks))


_RULE_CHARS = set("-‐‑‒–—―_=~·.…•*+")
_RULE_RUN_RE = re.compile(r"[-‐‑‒–—―_=~]{3,}")


def _is_border_line(line: str) -> bool:
    """Рамка врезки, распознанная как текст: «---— хххх», «————», «=====»,
    «- - - - -». В строке есть черта из трёх и больше знаков (или три и больше
    токенов-черточек), а остальные токены — такие же черты либо одна буква,
    повторённая несколько раз («хххх» — распознанный узор рамки). Слова
    здесь нет ни одного: «— 23 —» — номер страницы, «— Да» — реплика."""
    toks = line.split()
    if not toks:
        return False
    dashy = [t for t in toks if all(c in _RULE_CHARS for c in t)]
    if not (any(_RULE_RUN_RE.search(t) for t in toks) or len(dashy) >= 3):
        return False
    for t in toks:
        if all(c in _RULE_CHARS for c in t):
            continue
        core = "".join(c for c in t if c not in _RULE_CHARS)
        if len(core) <= 2 and len(t) - len(core) >= 5:
            continue                    # «V-----------» — угол рамки и черта
        if len(core) >= 2 and len({c.lower() for c in core}) == 1 and core.isalpha():
            continue                    # «хххх», «xxxx», «оооо» — узор, не слово
        if all(c in _ORNAMENT_CHARS for c in core):
            continue
        return False
    return True


def _strip_border_edges(line: str, report: dict) -> str:
    """Кусок рамки, приклеенный распознавателем к строке текста на той же
    высоте: «На заметку ---— хххх» → «На заметку». Снимается только с краёв
    и только черта из трёх и больше знаков вместе с узором за ней."""
    toks = line.split(" ")
    if len(toks) < 2:
        return line

    def rule(t):
        return bool(t) and all(c in _RULE_CHARS for c in t) and bool(_RULE_RUN_RE.search(t))

    def pattern(t):
        core = "".join(c for c in t if c not in _RULE_CHARS)
        return len(core) >= 3 and core.isalpha() and len({c.lower() for c in core}) == 1

    cut = False
    for side in (-1, 0):
        while len(toks) >= 2:
            t = toks[side]
            nb = toks[side - 1] if side == -1 else toks[1]
            if not t:
                toks.pop(side)
            elif rule(t) or (pattern(t) and rule(nb)):
                toks.pop(side)
                cut = True
            else:
                break
    if cut:
        report["borderLines"] += 1
    return " ".join(toks).strip() or line


def _is_noise_line(line: str) -> bool:
    """Строка без единого слова, зато со знаками мусора или из трёх и более
    обрывков: «Л ) . — 1 «■», «1 Ш», «ш ж т». Число («61»), маркер списка
    («1.») и одиночное слово сюда не попадают."""
    toks = line.split()
    if not toks:
        return False
    if any(_token_kind(t) == "word" for t in toks):
        return False
    if _PARAGRAPH_NO_RE.match(line.strip()):
        return False                    # «§ 5» — номер параграфа, а не знак мусора
    if any(c in _ORNAMENT_CHARS for c in line):
        # Знак сравнения при числе («<7%», «≥ 150») — условие, а не мусор (Т7).
        return not (any(c.isdigit() for c in line) and re.search(r"[<>±~]\s?\d", line))
    if any(c.isdigit() for c in line) and _NUM_LINE_RE.match(line):
        return False
    kinds = [_token_kind(t) for t in toks]
    # «и 39 %.» — хвост предложения, не мусор; «и т. д.», «т. е.», «а) б)» —
    # одиночные буквы с точкой или скобкой, это сокращения и метки, не
    # обрывки. Без знака орнамента нужен мусорный токен либо две и больше
    # ГОЛЫХ одиночных букв («ш ж т»).
    bare_single = sum(1 for t, k in zip(toks, kinds)
                      if k == "single" and not t.endswith((".", ")")))
    return len(toks) >= 3 and ("junk" in kinds or bare_single >= 2)


def page_quality(lines: list) -> dict:
    """Доли мусорных и одиночных букв среди буквенных токенов страницы."""
    toks = [t for l in lines for t in l.split()]
    kinds = [_token_kind(t) for t in toks]
    alpha = [k for k in kinds if k]
    n = len(alpha)
    junk = sum(1 for k in alpha if k == "junk")
    single = sum(1 for k in alpha if k == "single")
    return {"tokens": n, "junk": junk, "single": single,
            "junkShare": (junk / n) if n else 0.0,
            "singleShare": (single / n) if n else 0.0}


def page_unreliable(lines: list) -> bool:
    q = page_quality(lines)
    if q["tokens"] < PAGE_MIN_TOKENS:
        return False
    return ((q["junkShare"] >= PAGE_JUNK_SHARE and q["junk"] >= PAGE_JUNK_MIN)
            or (q["singleShare"] >= PAGE_SINGLE_SHARE and q["single"] >= PAGE_JUNK_MIN))


_TAB_RE = re.compile(r"[	 ]")


def _tidy(line: str) -> str:
    """Строка без табуляций и неразрывных пробелов, обрезанная по краям.
    Мягкий перенос на конце ОСТАЁТСЯ — по нему склейка узнаёт разрезанное
    слово; ДВОЙНОЙ пробел остаётся тоже — по нему узнаётся потерянная
    буквица. Пробелы сводятся к одному в самом конце (`restore_dropcaps`)."""
    return _TAB_RE.sub(" ", line).strip()


def _norm_line(line: str) -> str:
    """Строка для СРАВНЕНИЯ (колонтитулы, номера): без мягких переносов
    и с одиночными пробелами — «Апитоксинотерапия  —» и «Апитоксинотерапия —»
    один и тот же колонтитул."""
    return _WS_RE.sub(" ", _tidy(line.replace(SOFT, "")))


def running_heads(pages: list) -> tuple:
    """(верхние, нижние) — строки колонтитула.

    Колонтитул стоит ПЕРВОЙ строкой страницы (после номера, если он сверху)
    не меньше чем на HEAD_MIN_PAGES страницах, и не реже, чем в половине
    своих появлений — именно первой. Вторая строка двухстрочного колонтитула
    («Апитоксинотерапия —» / «лечение пчелоужалением») — та, что стоит
    сразу ЗА первой на стольких же страницах. Позиция, а не окно из трёх
    строк: заголовок врезки «На заметку» попадает в верхние три строки
    одиннадцати страниц, но первой строкой — почти никогда. Сравнение
    с учётом регистра: заголовок главы КАПСОМ на её первой странице
    и колонтитул строчными — разные строки, и заголовок остаётся."""
    total: Counter = Counter()
    first: Counter = Counter()
    second: Counter = Counter()      # (первая, вторая)
    last: Counter = Counter()
    for lines in pages:
        ls = [_norm_line(l) for l in lines]
        ls = [l for l in ls if l]
        for l in set(ls):
            total[l] += 1
        head = [l for l in ls[:HEAD_WINDOW] if not _NUM_LINE_RE.match(l)]
        if head:
            first[head[0]] += 1
            if len(head) > 1:
                second[(head[0], head[1])] += 1
        foot = [l for l in ls[-FOOT_WINDOW:] if not _NUM_LINE_RE.match(l)]
        if foot:
            last[foot[-1]] += 1

    def ok(l: str, c: int) -> bool:
        # Строка с двоеточием на конце («Пациент:») — подпись поля формы,
        # колонтитул так не кончается никогда.
        return (c >= HEAD_MIN_PAGES and HEAD_MIN_LEN <= len(l) <= HEAD_MAX_LEN
                and not l.endswith(":")
                and not _NUM_LINE_RE.match(l) and c / max(1, total[l]) >= HEAD_TOP_SHARE)

    heads = {l for l, c in first.items() if ok(l, c)}
    for (h1, h2), c in second.items():
        if h1 in heads and ok(h2, c):
            heads.add(h2)
    feet = {l for l, c in last.items() if ok(l, c)}
    return heads, feet


def _fold(s: str) -> str:
    """Строка для НЕЧЁТКОГО сравнения: строчными, только буквы и цифры."""
    return "".join(c for c in s.lower() if c.isalnum())


@functools.lru_cache(maxsize=65536)
def _sig(s: str) -> tuple:
    """(КАПСОМ ли, сложенная строка, её буквы счётом) — одна строка
    сравнивается со многими, считать это заново на каждую пару незачем."""
    f = _fold(s)
    return _is_caps_heading(s), f, Counter(f)


def _similar_enough(a: str, b: str, thr: float = HEAD_FUZZY) -> bool:
    """Строки похожи не меньше чем на `thr` (доля совпавших букв и цифр).
    Регистр — часть строки и здесь: заголовок раздела КАПСОМ на его
    титульной странице — не колонтитул строчными (см. `running_heads`).
    Строки, чья длина разнится больше чем на четверть, не сравниваются.
    Дешёвая оценка сверху (общий набор букв) идёт вперёд: полный
    SequenceMatcher нужен только парам, которые могут дотянуть."""
    ca, fa, na = _sig(a)
    cb, fb, nb = _sig(b)
    if ca != cb or not fa or not fb or abs(len(fa) - len(fb)) > 0.25 * max(len(fa), len(fb)):
        return False
    if 2.0 * sum((na & nb).values()) / (len(fa) + len(fb)) < thr:
        return False
    return difflib.SequenceMatcher(None, fa, fb, autojunk=False).ratio() >= thr


def _in_frame(l: str, known: set) -> bool:
    """Строка — известный колонтитул: точно или с ошибкой распознавания.
    Колонтитул сканированной книги распознаётся на каждой странице заново,
    и «Апитоксинотерапия —» встречается как «Апцтоксинотерапия —»
    и «Апитоксинвтерапия —»: точное сравнение пропускало такие в текст,
    и они вклеивались посреди абзаца. Нечётко — только строки подлиннее:
    у коротких одна буква уже меняет слово."""
    if l in known:
        return True
    if len(_fold(l)) < HEAD_FUZZY_MIN:
        return False
    return any(_similar_enough(l, h) for h in known) or _heads_spread(l, known)


def _heads_spread(l: str, known: set) -> bool:
    """Строка — колонтитулы РАЗВОРОТА: две страницы отсканированы одним
    листом, и распознаватель прочёл оба колонтитула одной строкой
    («% Лекарство из. улья Лекарство из улья», боевая стр. 52). Нечёткое
    сравнение такое не узнаёт — строка вдвое длиннее. Узнаём по вхождению:
    известный колонтитул стоит в строке целиком, а остаток — обрывок
    (не больше четырёх букв) либо его же искажённая копия."""
    f = _fold(l)
    caps = _is_caps_heading(l)
    for h in known:
        fh = _fold(h)
        # Регистр — часть строки, как у `_similar_enough`: заголовок главы
        # «АПИТОКСИНОТЕРАПИЯ» колонтитулом «Апитоксинотерапия —» не бывает.
        if (len(fh) < HEAD_FUZZY_MIN or fh not in f or len(f) > 2.5 * len(fh)
                or caps != _is_caps_heading(h)):
            continue
        rest = f.replace(fh, "", 1)
        if sum(1 for c in rest if c.isalpha()) <= 4:
            return True
        if difflib.SequenceMatcher(None, rest, fh, autojunk=False).ratio() >= 0.7:
            return True
    return False


def _strip_page_frame(lines: list, heads: set, feet: set, report: dict) -> list:
    """Снять с краёв страницы колонтитулы и номер. Только с краёв: тот же
    номер посреди страницы — это текст."""
    ls = [_tidy(l) for l in lines]
    ls = [l for l in ls if l]
    # Сверху: до трёх строк колонтитула и номера подряд.
    cut = 0
    while cut < len(ls) and cut < HEAD_WINDOW:
        l = _norm_line(ls[cut])
        if _in_frame(l, heads):
            report["runningHeads"] += 1
        elif _NUM_LINE_RE.match(l):
            report["pageNumbers"] += 1
        else:
            break
        cut += 1
    ls = ls[cut:]
    cut = 0
    while cut < len(ls) and cut < FOOT_WINDOW:
        l = _norm_line(ls[-1 - cut])
        if _in_frame(l, feet):
            report["runningHeads"] += 1
        elif _NUM_LINE_RE.match(l):
            report["pageNumbers"] += 1
        else:
            break
        cut += 1
    if cut:
        ls = ls[:-cut]
    return ls


_HYPHEN_DUP_RE = re.compile(r"([^\W\d_][-‐‑])\s+[-‐‑]\s*$")


# Знак, приклеенный к МАТЕМАТИКЕ, — не украшение, а повреждённый глиф.
# Боевая книга (стр. 161): распознаватель прочёл надстрочную «1» дроби как
# «*», и токен «*/» терялся целиком — `strip(_ORNAMENT_CHARS)` оставлял «/»,
# то есть «и пить его теплым по / стакана». Снятое повреждение неотличимо
# от исправного текста, а по нему ещё и решают, звать ли человека.
# Класс УЗКИЙ намеренно: только «*» и «^» (их распознаватель и ставит на
# месте над- и подстрочника) и только вплотную к цифре или дробной черте.
# «#12», «<308>», «|1» чистятся, как чистились: там знак не работает знаком.
_MATH_MARKS = frozenset("*^")
_MATH_NEAR_RE = re.compile(r"[*^](?=[0-9/])|(?<=[0-9/])[*^]")
_ORN_STR = "".join(_ORNAMENT_CHARS)
# Знаки, которые на КРАЮ слова не снимаются (`_clean_line`, Т7): сравнение
# перед словом или числом и знаки сноски.
_CMP_KEEP = "<>±~"
_CMP_TOKENS = frozenset(("<", ">", "±", "~", "<=", ">=", "≤", "≥"))
_NOTE_KEEP = "*§"
# Знак, который Юникод считает математическим, а книга — почти никогда:
# «|» в отсканированной книге это граница таблицы, а не модуль числа.
# Замер на боевой книге: «|» встречается 4 раза, и все четыре — обрывки.
_MATH_NOT = frozenset("|")
# Обёртка парой — разметка или мусор распознавания («<308>»), а не
# «меньше 308»: у сравнения второй скобки не бывает.
_WRAP_PAIRS = (("<", ">"), ("{", "}"))


def _math_token(t: str) -> bool:
    """Токен работает ЗНАКОМ, а не украшением, — чистить его нельзя.

    Два случая. Первый — повреждённый над/подстрочник: распознаватель ставит
    «*» или «^» на месте числителя дроби и степени («*/», «2*»).
    Второй — знак при ЧИСЛЕ: «±0,5», «<5», «>100», «~50», «≤37». Все они
    стоят в `_ORNAMENT_CHARS`, а `strip` снимает знак с края токена — то есть
    «±0,5» превращалось в «0,5», а «<5» в «5». Это не мусор, а смысл, и
    меняется он на противоположный.

    Что НЕ защищаем и почему: токен без цифры (там знак чаще украшение —
    сноска «режима*», обрывок «■ЧР’»), «|» (граница таблицы) и токен,
    обёрнутый парой скобок («<308>» — разметка, а не сравнение)."""
    if _MATH_NEAR_RE.search(t) and all(c in _MATH_MARKS or c not in _ORNAMENT_CHARS for c in t):
        return True
    if not any(c.isdigit() for c in t):
        return False
    for a, b in _WRAP_PAIRS:
        if t.startswith(a) and t.endswith(b):
            return False
    edge = t[:len(t) - len(t.lstrip(_ORN_STR))] + t[len(t.rstrip(_ORN_STR)):]
    return bool(edge) and all(
        c in _MATH_MARKS or (bool(MATH_CHAR_RE.search(c)) and c not in _MATH_NOT)
        for c in edge)


def _clean_line(line: str, report: dict):
    """Строка без мусора распознавания либо None, если она вся мусор."""
    # Имена глифов и разрядка — ЗДЕСЬ, после раскладки: части строки
    # (`split`) режутся по смещениям в сыром тексте ответа pypdf.
    line = _unspace(_glyph_names(line))
    if _is_ornament(line):
        report["ornaments"] += 1
        return None
    if _is_noise_line(line):
        report["junkLines"] += 1
        return None
    if _is_border_line(line):
        report["borderLines"] += 1
        return None
    line = _strip_border_edges(line, report)
    # «межребер- -»: за переносом слова распознаватель поставил лишнюю
    # черточку, и перенос не склеивался («межребер- ная»).
    line = _HYPHEN_DUP_RE.sub(r"\1", line)
    s = _UNDERSCORE_RE.sub(" ", line)
    if not any(c in _ORNAMENT_CHARS for c in s):
        return s.strip() or None       # нечего снимать — строка как есть (с двойными пробелами)
    # Одиночные знаки мусора между словами («^лучше», ««■») — снимаем
    # только те, что стоят отдельным токеном или на краю слова.
    toks = []
    split = s.split()
    for k, t in enumerate(split):
        core = t.strip("".join(_ORNAMENT_CHARS))
        if ((t in ("§", "§§") and k + 1 < len(split) and split[k + 1][:1].isdigit())
                or re.match(r"§+\d", t)):
            toks.append(t)             # «§ 5» — знак параграфа перед номером, не мусор
            continue
        if _math_token(t):
            toks.append(t)             # «*/», «2*» — повреждённый знак, а не украшение
            continue
        if t == "&" and toks and k + 1 < len(split):
            toks.append(t)             # «Merck Sharp & Dohme» — союз, не мусор (Т7)
            continue
        if t in _CMP_TOKENS and k + 1 < len(split) and re.match(r"[\d.,]", split[k + 1]):
            toks.append(t)             # «p < 0.05», «BMI > 30» — условие (Т7)
            continue
        if not core and all(c in _ORNAMENT_CHARS for c in t):
            if t.startswith(("•", "♦", "■", "●")) and len(t) == 1 and not toks:
                toks.append(t)         # маркер списка в начале строки
            continue
        if core and core != t:
            # Т7: знак сравнения ПЕРЕД словом или числом («and <TEE», «>65
            # лет») — смысл, а не украшение: снятый, он молча переворачивал
            # условие («и ОРЭ» вместо «и <ОРЭ», стр. 10). Обёрнутое парой
            # («<308>») — разметка, её снимаем, как прежде. Знак сноски
            # («therapy§», «§Includes», «risk*») — ссылка на подстрочное
            # примечание, и без него связь текста с легендой рисунка пропадала.
            lead = t[:len(t) - len(t.lstrip(_ORN_STR))]
            tail = t[len(t.rstrip(_ORN_STR)):]
            wrapped = (lead[:1], tail[-1:]) in (("<", ">"), ("{", "}"))
            keep_l = "" if wrapped else "".join(
                c for c in lead if (c in _CMP_KEEP and len(core) >= 2) or c in _NOTE_KEEP)
            keep_t = "" if wrapped else "".join(c for c in tail if c in _NOTE_KEEP)
            if "*" in keep_t and k + 1 < len(split) and split[k + 1][:1].islower():
                # «живота* выпадение» — посреди фразы перед строчной это
                # неверно прочитанная запятая скана, а не сноска (книга 8).
                keep_t = keep_t.replace("*", "")
            toks.append(keep_l + core + keep_t)
            continue
        toks.append(core or t)          # «^лучше» → «лучше»
    out = " ".join(toks).strip()
    return out or None


# ─── Над- и подстрочные куски: дроби, степени, индексы ───────────────
# Типограф ставит числитель дроби, степень и химический индекс ВЫШЕ или НИЖЕ
# базовой линии строки, и pypdf при сдвиге примерно от 0.65 em РВЁТ на этом
# месте строку: кусок становится отдельной «строкой» со своей базовой линией.
# Дальше порядок чтения (сверху вниз) уносит его прочь: на синтетическом PDF
# «и пить по ¹/₃ стакана» превращалось в «1 и пить по /3 стакана».
# Правило одно на все предметы — математику, химию, биологию: «m²», «H₂O»,
# «¹⁴C», «CD4⁺», «x₁» ломаются ровно так же.
#
# Кандидат УЗКИЙ намеренно: короткий кусок, в котором есть цифра или юникодный
# над/подстрочный знак. Без цифры это не индекс, а обрывок рисунка у края
# страницы (`_edge_scrap`), и забирать его в строку нельзя.
SCRIPT_MAX_CHARS = 6
SCRIPT_SIZE_SHARE = 0.85     # кусок мельче строки, к которой его приклеивают
SCRIPT_DY_SHARE = 0.9        # и ближе к ней, чем межстрочный (тот от 1.15 em)
SCRIPT_BASE_DY = 0.15        # «та же базовая линия»
SCRIPT_MATH_SIZE_MAX = 2.5   # знак математики бывает крупнее строки
SCRIPT_GAP_SHARE = 1.5       # и рядом по горизонтали
SCRIPT_SPACE_SHARE = 0.25    # зазор, начиная с которого между кусками ПРОБЕЛ
_SCRIPT_CHAR_RE = re.compile(r"[0-9²³¹⁰-₟]")


def _short_piece(r: dict) -> bool:
    t = (r.get("t") or "").strip()
    return 0 < len(t) <= SCRIPT_MAX_CHARS


def _math_piece(r: dict) -> bool:
    """Кусок со ЗНАКОМ математики: интеграл, корень, сумма, ±, ≤, стрелка.
    Такой знак бывает КРУПНЕЕ строки (высокий ∫, широкий √), поэтому мерку
    «мельче строки» к нему не прикладывают."""
    return _short_piece(r) and bool(MATH_CHAR_RE.search(r.get("t") or ""))


def _script_piece(r: dict) -> bool:
    return _short_piece(r) and bool(_SCRIPT_CHAR_RE.search(r.get("t") or "")
                                    or MATH_CHAR_RE.search(r.get("t") or ""))


def _limit_base(b: dict) -> bool:
    """Строка с оператором, у которого предел пишется над и под знаком."""
    return any(c in MATH_LIMIT_OPS for c in (b.get("t") or ""))


def _hgap(a: dict, b: dict) -> float:
    """Зазор между кусками по горизонтали; отрицательный — перекрываются.
    Над/подстрочник НИКОГДА не налезает на свою строку, поэтому перекрытие —
    это два разных места на странице, и сливать их нельзя."""
    if b["x0"] >= a["x1"]:
        return b["x0"] - a["x1"]
    if a["x0"] >= b["x1"]:
        return a["x0"] - b["x1"]
    return -1.0


# Над- и подстрочный кусок, притянутый к строке, пишется знаками Юникода
# (Т9, как `pdfpages_worker._script_marks` для кусков одной строки pypdf):
# «м²», «H₂O». Дробь («1/3» — числитель и знаменатель у косой черты) остаётся
# цифрами: «¹/₃» читается хуже и иначе ищется. Буква — только одиночная
# надстрочная (сноска «ᵃ»).
_SUP_MAP = dict(zip("0123456789+-=()abcde", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉ"))
_SUP_LEAD_RE = re.compile(r"^\s*[¹²³⁴⁵⁶⁷⁸⁹⁰]+[,⁰¹²³⁴⁵⁶⁷⁸⁹]*\s+\S")
_SCRIPT_LIST_RE = re.compile(r"^\d{1,3}(?:(?:,\s+|\s*[–-]\s*)\d{1,3}){1,4}$")
_SUB_MAP = dict(zip("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"))


def _script_text(pc: dict, base: dict, before: str, after: str) -> str:
    t = pc["t"]
    if pc is base or pc["s"] > SCRIPT_SIZE_SHARE * base["s"] or not t.strip():
        return t
    if before.rstrip().endswith("/") or after.lstrip().startswith("/"):
        return t                        # дробь
    core = t.strip()
    table = _SUP_MAP if pc["y"] > base["y"] else _SUB_MAP
    if _SCRIPT_LIST_RE.match(core) and len(core) > 3:
        # Ц5: список ссылок надстрочником («1, 2», «1–3» у автора) — цифры
        # знаками надстрочника, разделитель как есть, без пробелов: «¹,²».
        return "".join(table.get(ch, ch) for ch in core if not ch.isspace())
    letters = [ch for ch in core if ch.isalpha()]
    if len(core) > 3 or not all(ch in table for ch in core) or (
            letters and (table is _SUB_MAP or len(core) > 1)):
        return t
    return "".join(table.get(ch, ch) for ch in t)


def _join_scripts(recs: list, report: dict) -> list:
    """Куски, разорванные по базовой линии, — обратно в одну строку.

    Сливается ТОЛЬКО то, что притянул над/подстрочник: он сам и куски его
    строки, между которыми он стоял («и пить по » + «1» + «/3 стакана»).
    Слияния «двух кусков на одной базовой линии» само по себе тут нет
    намеренно: порядок чтения и сборка абзаца с ними и так справляются,
    а x0/x1 слитой записи поехали бы — по ним считаются поля страницы,
    колонки и роль врезки."""
    n = len(recs)
    if n < 2:
        return recs
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[max(a, b)] = min(a, b)

    joined = 0
    for i, f in enumerate(recs):
        if f["s"] <= 0:
            continue
        sure = _script_piece(f)
        # Предел интеграла или суммы бывает БУКВОЙ («∫ₐᵇ», «∑ₙ»), и цифры
        # в таком куске нет. Пускаем его только к строке с таким оператором:
        # без этой оговорки в строку уезжал бы обрывок рисунка у края
        # страницы, ради которого заведён `_edge_scrap`.
        limit = not sure and _short_piece(f)
        if not sure and not limit:
            continue
        math = _math_piece(f)
        best = None
        for j, b in enumerate(recs):
            if j == i or b["s"] <= 0:
                continue
            if limit and not _limit_base(b):
                continue
            # Знак математики вправе быть КРУПНЕЕ строки (высокий интеграл);
            # остальным куском может быть только над/подстрочник — мельче.
            if f["s"] > (SCRIPT_MATH_SIZE_MAX if math else SCRIPT_SIZE_SHARE) * b["s"]:
                continue
            dy = abs(f["y"] - b["y"])
            if not 0 < dy <= SCRIPT_DY_SHARE * b["s"]:
                continue
            gap = _hgap(f, b)
            if gap < 0 or gap > SCRIPT_GAP_SHARE * min(f["s"], b["s"]):
                continue
            # Ближе по ВЕРТИКАЛИ сильнее, чем ближе по горизонтали: своя
            # строка у над/подстрочника одна, а коротких соседних строк
            # с маленьким зазором рядом бывает несколько.
            if best is None or (dy, gap) < best[0]:
                best = ((dy, gap), j)
        if best is None:
            continue
        j = best[1]
        union(i, j)
        joined += 1
        # Кусок той же строки по ДРУГУЮ сторону от над/подстрочника: строку
        # разорвало надвое именно им, и без этого шага «и пить по » и
        # «/3 стакана» остались бы двумя строками, а между ними встал бы
        # перенос абзаца.
        b = recs[j]
        b_right = b["x0"] >= f["x1"]
        for k, c in enumerate(recs):
            if k in (i, j) or c["s"] <= 0:
                continue
            if abs(c["y"] - b["y"]) > SCRIPT_BASE_DY * b["s"]:
                continue
            if (c["x0"] >= f["x1"]) == b_right:
                continue                 # та же сторона, что база, — другой кусок строки
            gap = _hgap(f, c)
            if 0 <= gap <= SCRIPT_GAP_SHARE * min(f["s"], c["s"]):
                union(i, k)
    if not joined:
        return recs
    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for i in range(n):
        g = groups.get(i)
        if not g:
            continue
        if len(g) == 1:
            out.append(recs[i])
            continue
        parts = sorted((recs[k] for k in g), key=lambda r: r["x0"])
        base = max(parts, key=lambda r: r["s"])
        # Ц5: надстрочник В НАЧАЛЕ строки («¹ Сибирский…», знак аффилиации или
        # сноски) — тоже знаком надстрочника, а не обычной цифрой.
        text = _script_text(parts[0], base, "", parts[1]["t"] if len(parts) > 1 else "")
        prev = parts[0]
        for k_, pc in enumerate(parts[1:], 1):
            # Пробел — по зазору, и мерка берётся у КРУПНОГО куска: межсловный
            # пробел это примерно четверть его кегля. Мерка по мелкому объявила
            # бы пробелом стык «1» и «/3», то есть саму дробь.
            step = SCRIPT_SPACE_SHARE * max(prev["s"], pc["s"], 1.0)
            if (prev.get("rsp") or pc.get("lsp") or pc["x0"] - prev["x1"] >= step)                     and not text.endswith(" ") and not pc["t"].startswith(" "):
                text += " "
            nxt = parts[k_ + 1]["t"] if k_ + 1 < len(parts) else ""
            text += _script_text(pc, base, text, nxt)
            prev = pc
        out.append({"t": text, "x0": parts[0]["x0"], "x1": max(p["x1"] for p in parts),
                    "y": base["y"], "s": base["s"],
                    # Начертание и гарнитура — у основного куска строки: без
                    # них склеенная строка печаталась бы обычным по умолчанию.
                    "st": base.get("st") or "", "fam": base.get("fam") or "",
                    "color": base.get("color"),
                    "after": [t for p in parts for t in (p.get("after") or [])],
                    "xl": max((p.get("xl") if p.get("xl") is not None else p["x0"]) for p in parts),
                    "lsp": parts[0].get("lsp", False), "rsp": parts[-1].get("rsp", False)})
    report["scripts"] += joined
    return out


def _vocab(pages: list) -> tuple:
    """(слова строчными → число, составные с дефисом посреди строки)."""
    words: Counter = Counter()
    hyphenated: set = set()
    for lines in pages:
        for l in lines:
            l = l.replace(SOFT, "")
            for m in re.finditer(r"[^\W\d_]+(?:-[^\W\d_]+)+", l):
                if not l.rstrip().endswith(m.group(0)):
                    hyphenated.add(m.group(0).lower())
            for w in re.findall(r"[^\W\d_]+", l):
                words[w.lower()] += 1
    return words, hyphenated


def _is_caps_heading(line: str) -> bool:
    letters = _letters(line)
    return len(letters) >= 3 and all(c.isupper() for c in letters)


_LETTER_MARK_RE = re.compile(r"^[a-zа-яё][.)]\s")
LETTER_MARK_HEAD = 60


def _letter_mark_midphrase(buf: str, line: str, nxt: str = "") -> bool:
    """Ц9г: «v. 2.050 (http://…)» после «…в программе PLINK» — продолжение
    фразы, а не пункт «v.» списка: буквенный маркер начинает пункт, только
    когда предыдущая строка закончила фразу (точка, двоеточие, точка
    с запятой) или сама начата таким же маркером."""
    if not _LETTER_MARK_RE.match(line) or _LETTER_MARK_RE.match(nxt or ""):
        return False                    # за ним следующий пункт — это список
    b = buf.rstrip()
    if len(b) < LETTER_MARK_HEAD:
        return False                    # короткая строка перед ним — заголовок списка
    return not (b.endswith((".", ":", ";", "!", "?")) or _LETTER_MARK_RE.match(buf))


def join_lines(lines: list, hyphenated: set = frozenset(), median_len: float = 0.0,
               report: dict = None, spans: list = None) -> list:
    """Строки → абзацы. Конец абзаца — конец предложения, короткая строка
    перед заглавной, строка КАПСОМ, маркер списка, пустая строка, потолок.
    Перенос слова снимается: мягкий — всегда, дефисный — когда продолжение
    со строчной и такого составного слова в документе посреди строки нет.

    `spans` — если передать список, в него ляжет по паре (первая, последняя)
    строка на каждый абзац. Нужно выгрузке «как в оригинале»: место абзаца
    на странице — это рамка его СТРОК, и восстановить её после склейки
    нечем. Ответ от этого не меняется ни на знак."""
    report = report if report is not None else Counter()
    out, buf = [], ""
    buf_caps = False               # в буфере — заголовок КАПСОМ (склеивается со следующим таким же)
    n = len(lines)
    first = [None]                 # первая строка, попавшая в буфер

    def flush():
        nonlocal buf, buf_caps
        if buf:
            out.append(buf)
            if spans is not None:
                spans.append((first[0], last[0]))
            buf = ""
        first[0] = None
        buf_caps = False

    last = [None]                  # и последняя
    for i in range(n):
        line = (lines[i] or "").strip()
        if not line:
            flush()
            continue
        nxt = (lines[i + 1] or "").strip() if i + 1 < n else ""
        caps = _is_caps_heading(line)
        if buf and ((_BULLET_RE.match(line) and not _letter_mark_midphrase(buf, line, nxt))
                    or (buf_caps != caps and not buf.endswith((SOFT, "-")))):
            flush()
        # Строку записываем в отпечаток ПОСЛЕ возможного сброса: иначе
        # первой строкой прежнего абзаца оказалась бы эта, уже следующая.
        if first[0] is None:
            first[0] = i
        last[0] = i
        if buf.endswith(SOFT):
            buf = buf[:-1] + line
            report["softHyphens"] += 1
        elif buf.endswith("-") and line[:1].islower():
            left = re.findall(r"[^\W\d_]+$", buf[:-1])
            right = re.findall(r"^[^\W\d_]+", line)
            compound = (left[0] + "-" + right[0]).lower() if left and right else ""
            lw = left[0].lower() if left else ""
            particle = bool(left and right and (
                right[0].lower() in _HYPHEN_RIGHT
                or (lw in _HYPHEN_LEFT and (lw not in _HYPHEN_LEFT_FORM
                                            or _HYPHEN_LEFT_FORM[lw].search(right[0].lower())))))
            if compound and (compound in hyphenated or particle):
                buf = buf + line            # «научно-обоснованный», «кто-то» — дефис свой
            else:
                buf = buf[:-1] + line
                report["hyphensJoined"] += 1
        else:
            buf = (buf + " " + line) if buf else line
        if SOFT in buf and not buf.endswith(SOFT):
            report["softHyphens"] += buf.count(SOFT)
            buf = buf.replace(SOFT, "")
        if buf.endswith(SOFT):
            continue
        if caps:
            buf_caps = True
            # Многострочный заголовок главы («ЗНАКОМЬТЕСЬ:» / «НАТУРАЛЬНЫЙ МЕД»):
            # следующая строка капсом — тот же заголовок, знак на конце
            # не разрывает.
            if _is_caps_heading(nxt):
                continue
            flush()
            continue
        if (_END_RE.search(buf) and not _addr_cut(buf, nxt)) or len(buf) >= PARA_MAX:
            flush()
            continue
        if (median_len and len(line) < HEADING_LEN_SHARE * median_len
                and not line.endswith((",", "-", "—", "–", SOFT))
                and nxt[:1] and (nxt[:1].isupper() or nxt[:1].isdigit() or _BULLET_RE.match(nxt))):
            flush()
    flush()
    return out


def _addr_cut(buf: str, nxt: str) -> bool:
    """Ц9б: точка в конце строки — не конец фразы, а разрез АДРЕСА
    («olga.sergeevna.fedorova@gmail.» / «com, https://orcid…»,
    «https://doi.» / «org/10.20538/…»): последнее слово — почта или
    ссылка, а следующая строка начата строчной буквой или цифрой."""
    tail = buf.rsplit(None, 1)[-1] if buf.strip() else ""
    if not tail.endswith(".") or not nxt[:1] or not (nxt[:1].islower() or nxt[:1].isdigit()):
        return False
    return "@" in tail or "://" in tail or tail.lower().startswith("www.")


_DROPCAP_RE = re.compile(r"^([^\W\d_]{2,})  (\S)")


def restore_dropcaps(paras: list, words: Counter, report: dict) -> list:
    """«стрый  ларингит» → «Острый ларингит»: буквица потеряна, на её месте
    двойной пробел. Буква берётся из словаря документа: слово с одной
    заглавной впереди должно в нём встречаться, а обрубок — нет."""
    out = []
    for p in paras:
        m = _DROPCAP_RE.match(p)
        if m:
            stub = m.group(1)
            # Без буквицы остаток слова строчный, и сам по себе он редок:
            # «то  есть» → «Это есть» было бы подменой частого слова.
            if stub[0].islower() and words.get(stub.lower(), 0) <= 2:
                cands = Counter()
                for w, c in words.items():
                    if len(w) == len(stub) + 1 and w.endswith(stub.lower()):
                        cands[w[0]] += c
                # Обрубок сам в словаре есть (со своей же строки), поэтому
                # мерило — не «нет в словаре», а «слово с буквой впереди
                # встречается не реже обрубка».
                if cands and cands.most_common(1)[0][1] >= words.get(stub.lower(), 0):
                    ch = cands.most_common(1)[0][0].upper()
                    p = ch + stub + " " + p[m.end(1) + 2:]
                    report["dropCaps"] += 1
        out.append(_WS_RE.sub(" ", p).strip())
    return out


# ─── Раскладка страницы по геометрии ─────────────────────────────────
#
# Строки pypdf идут в порядке ПОТОКА СОДЕРЖИМОГО, а не чтения. У книги,
# распознанной сканером, поток — это порядок, в каком распознаватель
# складывал блоки: на боевой странице 78 эпиграф, его подпись «Авиценна»
# и строка «сокоэффективных … Сре-» стоят ПОСЛЕ всего текста страницы,
# а заголовок «Заготовка и хранение прополиса» на странице 77 — после
# врезки в конце. Текст не терялся — он переставлялся: «вы-» склеивалось
# с «ди них» («выди них»), а «сокоэффективных» — с подписью эпиграфа.
# Геометрия (`pdfpages_worker.page_lines`) возвращает строкам их место,
# и по нему же видно, что строка — колонтитул, врезка, подпись к рисунку
# или подпись эпиграфа, а не продолжение абзаца.

# Заголовок — кегль заметно крупнее основного.
GEO_HEADING = 1.25
# Врезка/эпиграф/цитата: две строки подряд и больше, отодвинутые от левого
# поля колонки больше чем на столько кеглей, и либо не доходящие до правого
# поля, либо набранные мельче основного.
GEO_INDENT = 1.2
GEO_SMALL = 0.9
# Колонтитул и номер отделены от текста пробелом больше обычного интервала.
GEO_BAND_GAP = 1.6
# Абзац, разорванный врезкой, ждёт своего продолжения не дольше стольких строк.
DEFER_MAX_LINES = 60
# Подпись у рисунка: метка («НК21», «А») — не длиннее стольких знаков.
LABEL_MAX_LEN = 24
# Рисунок: вложенная картинка заметного размера, но не во всю страницу
# (фон скана — тоже картинка).
FIG_MIN_W = 0.12
FIG_MIN_H = 0.08
FIG_MAX_AREA = 0.85
# Многослойный скан (MRC) режет ОДИН рисунок на несколько картинок: фон,
# маска, цветной слой. Рамки, которые пересекаются или стоят вплотную, —
# один рисунок: иначе он лёг бы в документ несколько раз.
FIG_MERGE_GAP = 6.0
# Место рисунка на странице — это СВОБОДНАЯ ПОЛОСА между строками текста,
# а не рамка самой картинки: на скане подписи внутри рисунка («ВК21»)
# в текстовый слой не попали и лежат ЗА её краем — обрезав по рамке, мы
# отрезали бы их. Полосу ограничивают строки и другие картинки страницы.
FIG_PAD = 0.3                # зазор до строки сверху, в кеглях этой строки
FIG_PAD_BELOW = 1.15         # и снизу: там у строки ещё и выносные элементы
FIG_EDGE = 0.02              # нет строки с этой стороны — отступ от края листа
FIG_SIDE_GAP = 4.0           # зазор до строки, стоящей СБОКУ от рисунка
FIG_EDGE_TOUCH = 0.05        # «у самого края листа», в долях стороны
FIG_SLIVER_THIN = 0.2        # лоскут: узок по одной стороне…
FIG_SLIVER_LONG = 0.8        # …и тянется почти во весь лист по другой
FIG_COL_SHARE = 0.3          # какой долей ширины рисунок стоит в текстовой колонке


# Метка рисунка в потоке строк: собирать абзацы и раскладывать вставки
# умеет только `_assemble`/`join_lines`, а они работают со СТРОКАМИ.
# Поэтому рисунок едет по ним меткой из области частного использования
# Юникода (в тексте книги таких знаков не бывает) и превращается
# в картинку последним шагом, когда абзацы уже собраны.
_FIG_MARK_OPEN, _FIG_MARK_CLOSE = "", ""
_FIG_MARK_RE = re.compile(_FIG_MARK_OPEN + r"(\d+)" + _FIG_MARK_CLOSE)


def _fig_mark(n: int) -> str:
    return "%s%d%s" % (_FIG_MARK_OPEN, n, _FIG_MARK_CLOSE)


def _fig_frac(crop: list, box: list) -> list:
    """Рамка в ДОЛЯХ страницы от левого верхнего угла. Долями, а не точками,
    чтобы тот, кто рисует страницу, не сверял систему координат с нашей."""
    pw, ph = max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1])
    v = [(crop[0] - box[0]) / pw, (box[3] - crop[3]) / ph,
         (crop[2] - box[0]) / pw, (box[3] - crop[1]) / ph]
    return [round(min(1.0, max(0.0, t)), 4) for t in v]


def _fig_boxes(g, recs: list, merge: bool = False) -> list:
    """Рисунки страницы: [x0, y0, x1, y1] в порядке сверху вниз.

    ОДИН расчёт на две работы: по нему метки и подписи вокруг рисунка
    становятся отдельными абзацами (`_geo_roles`), и по нему же рисунок
    попадает в документ (`clean`). Разойдись они — подпись стояла бы
    у рисунка, которого рядом нет.

    `merge` — слить рамки, стоящие вплотную, в одну. Нужно ТОЛЬКО при
    выкладке: многослойный скан режет один рисунок на слои, и без слияния
    он лёг бы в документ несколько раз. Разметке ролей слияние ВРЕДИТ:
    метка ищется у КРАЯ рисунка, а слитая рамка накрывает и текст между
    двумя картинками — на боевой книге так разорвался абзац посреди слова
    («лимонную кис-» / «лоту по вкусу»)."""
    box = g.get("box") or [0, 0, 0, 0]
    pw, ph = max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1])
    col = (min(r["x0"] for r in recs), max(r["x1"] for r in recs)) if recs else None
    raw = []
    for f in g.get("figs") or []:
        w, h = f[2] - f[0], f[3] - f[1]
        if not (w >= FIG_MIN_W * pw and h >= FIG_MIN_H * ph and w * h < FIG_MAX_AREA * pw * ph):
            continue
        # Полоса У КРАЯ ЛИСТА во всю его высоту (или ширину) — не рисунок,
        # а слой самой страницы: у книги, снятой со сканера, край переплёта
        # и стол лежат отдельной картинкой. В документ такая полоса едет
        # тёмным лоскутом. Рисунок так не стоит: у книги есть поля.
        edge = (f[0] - box[0] <= FIG_EDGE_TOUCH * pw or box[2] - f[2] <= FIG_EDGE_TOUCH * pw
                or f[1] - box[1] <= FIG_EDGE_TOUCH * ph or box[3] - f[3] <= FIG_EDGE_TOUCH * ph)
        if edge and min(w / pw, h / ph) < FIG_SLIVER_THIN and max(w / pw, h / ph) > FIG_SLIVER_LONG:
            continue
        # Картинка ВНЕ текстовой колонки — тоже слой страницы, а не рисунок:
        # у книги, снятой со сканера, край переплёта и стол лежат своими
        # картинками рядом с полем. Рисунок в книге стоит в колонке: так
        # устроена вёрстка.
        if col and (min(f[2], col[1]) - max(f[0], col[0])) < FIG_COL_SHARE * w:
            continue
        # Картинка, по которой идут строки текста (подложка, рисунок
        # в обтекании), — не рисунок с метками: иначе каждая короткая
        # концевая строка абзаца над ней считалась бы меткой.
        over = sum(1 for r in recs if len(r["t"]) >= 30 and r["x0"] < f[2] and r["x1"] > f[0]
                   and f[1] <= r["y"] <= f[3])
        if over < 2:
            raw.append(list(f))
    if not merge:
        return sorted(raw, key=lambda b: -b[3])
    merged: list = []
    for f in sorted(raw, key=lambda b: (-b[3], b[0])):
        for m in merged:
            if (f[0] <= m[2] + FIG_MERGE_GAP and m[0] <= f[2] + FIG_MERGE_GAP
                    and f[1] <= m[3] + FIG_MERGE_GAP and m[1] <= f[3] + FIG_MERGE_GAP):
                m[0], m[1] = min(m[0], f[0]), min(m[1], f[1])
                m[2], m[3] = max(m[2], f[2]), max(m[3], f[3])
                break
        else:
            merged.append(list(f))
    return sorted(merged, key=lambda b: -b[3])


def _fig_printable(crop: list, recs: list) -> bool:
    """Годится ли вырезка в документ. Одно правило: внутри неё НЕТ строки
    текста. Иначе в документ уехал бы кусок книги картинкой — а он уже едет
    туда текстом, и читатель увидит его дважды, причём непереведённым.
    Так отсеиваются орнаменты шапки: они проходят по размеру, но полоса
    вокруг них накрывает сам колонтитул."""
    return not any(crop[1] < r["y"] < crop[3] and r["x0"] < crop[2] and r["x1"] > crop[0]
                   for r in recs)


def _fig_crop(f: list, recs: list, figs: list, box: list) -> list:
    """Что вырезать из отрисованной страницы: рамка рисунка, раздвинутая
    до ближайших строк сверху и снизу и до краёв текстовой колонки.

    Два правила, и второе выстрадано: ВВЕРХ И ВНИЗ полосу ограничивают
    строки, стоящие НАД и ПОД рисунком, а ВШИРЬ — строки, стоящие СБОКУ
    от него. У рисунка в половину полосы текст обтекает его справа, и
    расширение на всю колонку накрывало текст — такой рисунок отсеивался
    целиком (на боевой книге так пропали пять нумерованных «Рис.»).
    Ограничивают полосу и ДРУГИЕ картинки страницы: иначе в рисунок
    попадал орнамент шапки."""
    ph = max(1.0, box[3] - box[1])
    # Сначала высота: по строкам, которые стоят НАД рисунком и ПОД ним,
    # то есть перекрываются с ним по горизонтали.
    over_x = [r for r in recs if r["x1"] > f[0] and r["x0"] < f[2]]
    above = [r["y"] - FIG_PAD * max(r["s"], 1.0) for r in over_x if r["y"] > f[3]]
    above += [o[1] - FIG_MERGE_GAP for o in figs if o is not f and o[1] > f[3]
              and o[2] > f[0] and o[0] < f[2]]
    top = min(box[3], max(f[3], min(above))) if above else min(box[3], f[3] + FIG_EDGE * ph)
    below = [r["y"] + FIG_PAD_BELOW * max(r["s"], 1.0) for r in over_x if r["y"] < f[1]]
    below += [o[3] + FIG_MERGE_GAP for o in figs if o is not f and o[3] < f[1]
              and o[2] > f[0] and o[0] < f[2]]
    bot = max(box[1], min(f[1], max(below))) if below else max(box[1], f[1] - FIG_EDGE * ph)
    # Теперь ширина: до края колонки, но не дальше строки, стоящей СБОКУ
    # в этой же полосе, и не дальше чужой картинки.
    side = [r for r in recs if bot < r["y"] < top and (r["x1"] <= f[0] or r["x0"] >= f[2])]
    xs0 = [r["x0"] for r in recs] or [f[0]]
    xs1 = [r["x1"] for r in recs] or [f[2]]
    left = max([r["x1"] + FIG_SIDE_GAP for r in side if r["x1"] <= f[0]]
               + [o[2] + FIG_SIDE_GAP for o in figs if o is not f and o[2] <= f[0]
                  and o[1] < top and o[3] > bot]
               + [min(f[0], min(xs0))])
    right = min([r["x0"] - FIG_SIDE_GAP for r in side if r["x0"] >= f[2]]
                + [o[0] - FIG_SIDE_GAP for o in figs if o is not f and o[0] >= f[2]
                   and o[1] < top and o[3] > bot]
                + [max(f[2], max(xs1))])
    return [max(box[0], min(left, f[0])), bot, min(box[2], max(right, f[2])), top]


# Какая доля строк страницы может быть БЕЗ места, чтобы страница всё равно
# шла по геометрии. Место теряет повёрнутая строка: подпись вдоль оси схемы,
# повёрнутая таблица, корешок. Прежде одна такая строка лишала геометрии
# ВСЮ страницу — а у PDF, склеенного в одну длинную ленту (CamScanner:
# две страницы по 14 400 пунктов), это весь документ, и выгрузка «как
# в оригинале» молча становилась потоком абзацев. Больше половины без
# места — страница повёрнута целиком, и прежняя дорога по строкам честнее.
GEO_PLACELESS_MAX = 0.5


class _RotRun(list):
    """Пачка повёрнутых строк; `geo` — путь каждой (или None), как `rot`
    у геометрии страницы (`pdfpages_worker._rot_path`)."""

    def __init__(self, *a):
        super().__init__(*a)
        self.geo: list = [None] * len(self)

    def add(self, line: str, geo) -> None:
        self.append(line)
        self.geo.append(geo)


# Повёрнутая ТАБЛИЦА: ряд таблицы боком pypdf отдаёт одной строкой
# («Increased risk Neutral • No dose adjustment», проект 14, стр. 9), и
# перевод склеивал значения разных столбцов. Граница ячейки — кусок, начало
# которого вдоль пути совпадает с началами кусков в `ROT_COL_LINES` других
# повёрнутых строк того же угла (столбец; в строке таких кусков от трёх),
# у предыдущего куска начало тоже
# на столбце, и зазор между ними — от `ROT_COL_GAP` кегля. Маркер списка
# с висячим отступом («•» и текст) зазора не даёт — не режется.
ROT_COL_LINES = 3            # строк (включая свою) с тем же началом
ROT_COL_MIN_CELLS = 3        # кусков строки на столбцах — ряд таблицы
ROT_COL_GAP = 0.5
ROT_COL_TOL = 1.0
ROT_COL_SPLIT = os.environ.get("PDF_ROT_COLS", "1") != "0"
# Повёрнутая прямая строка, путь которой идёт НАЗАД или рвётся пропуском
# шире `ROT_GAP_SPLIT` кеглей, — это несколько надписей одной базовой
# линии: pypdf склеивает ячейки шапки повёрнутой таблицы из разных её мест
# («administration | Cost | Clinical considerations | MACE | Heart failure»,
# проект 14, стр. 9), и перевод печатался одной строкой за край таблицы.
ROT_GAP_SPLIT = float(os.environ.get("PDF_ROT_GAP", "3.0"))


# Строка без пути не склеивается с соседними дугами (Т21). Симптом: три дуги
# кольца — «LOW-ENERGYDIETS», «MEDITERRANEANDIET» (без пути, см. Т20) и
# «KETOGENICDIETS» — вышли ОДНИМ абзацем, и перевод всего абзаца раздавался по
# двум местам: на дуге «KETOGENIC DIETS» стояло «Средиземноморская ди…»
# (проект 14, стр. 10, 1, 4, 19). Причина: проверка `_rot_follows` требует путь
# у обеих строк и молча пропускалась, когда пути не было у одной. Правило:
# строка с путём и строка без пути — разные пачки; подряд идущие строки
# без пути остаются вместе, как прежде. `PDF_ROT_NOPATH_SPLIT=0` — прежнее.
ROT_NOPATH_SPLIT = os.environ.get("PDF_ROT_NOPATH_SPLIT", "1") != "0"


def _along(p: list) -> float:
    a = math.radians(float(p[2] or 0.0))
    return float(p[0]) * math.cos(a) + float(p[1]) * math.sin(a)


def _rot_piece_end(p: list) -> float:
    """Конец куска повёрнутой строки вдоль пути: записанный разбором
    (седьмое поле — точка конца), иначе оценка по числу знаков."""
    if len(p) > 6 and p[6]:
        try:
            return _along([p[6][0], p[6][1], p[2]])
        except Exception:
            pass
    return _along(p) + 0.5 * max(float(p[3] or 1.0), 1.0) * len(str(p[5] or ""))


def _rot_columns(rot: dict) -> dict:
    """{угол (до 5°): [начала столбцов вдоль пути]} по прямым повёрнутым
    строкам страницы: начало, встреченное в `ROT_COL_LINES`+ строках."""
    per: dict = {}
    for rg in rot.values():
        if not rg or rg.get("curved") or len(rg.get("pts") or []) < 1:
            continue
        ang = int(round(float(rg["pts"][0][2] or 0) / 5.0)) * 5
        per.setdefault(ang, []).append([_along(p_) for p_ in rg["pts"]])
    out = {}
    for ang, lines in per.items():
        cands = sorted({round(v) for ln in lines for v in ln})
        out[ang] = [c_ for c_ in cands
                    if sum(1 for ln in lines if any(abs(v - c_) <= ROT_COL_TOL for v in ln))
                    >= ROT_COL_LINES]
    return out


def _rot_cells(line: str, rg: dict, cols: dict) -> list:
    """[(кусок строки, путь)] — повёрнутая строка, разрезанная по столбцам
    таблицы; одна часть — строка как есть."""
    pts = rg.get("pts") or []
    if not ROT_COL_SPLIT or rg.get("curved") or len(pts) < 2:
        return [(line, rg)]
    ang = int(round(float(pts[0][2] or 0) / 5.0)) * 5
    starts = cols.get(ang) or []
    on_col = lambda v: any(abs(v - c_) <= ROT_COL_TOL for c_ in starts)  # noqa: E731
    table = sum(1 for p_ in pts if on_col(_along(p_))) >= ROT_COL_MIN_CELLS
    # Письмо справа налево идёт по пути назад законно — шаг назад там
    # не граница надписей.
    rtl = any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in line)
    cut = []
    for k in range(1, len(pts)):
        a_, b_ = pts[k - 1], pts[k]
        size = max(float(a_[3] or 1.0), 1.0)
        size2 = max(size, float(b_[3] or 1.0))
        end_a = _rot_piece_end(a_)
        if (table and on_col(_along(b_)) and on_col(_along(a_))
                and _along(b_) - end_a >= ROT_COL_GAP * size
                and any(ch.isalnum() for ch in str(a_[5] or ""))):
            cut.append(k)
        elif ROT_GAP_SPLIT > 0 and ((not rtl and _along(b_) < _along(a_) - 0.5 * size2)
                                    or (len(a_) > 6 and a_[6]
                                        and _along(b_) - end_a >= ROT_GAP_SPLIT * size2)):
            # Пропуск — только по ЗАПИСАННОМУ концу куска: оценка по числу
            # знаков у узкого и широкого шрифта врёт на кегли.
            cut.append(k)
    if not cut:
        return [(line, rg)]
    # Смещения кусков в строке: текст строки не меняется, режутся места.
    offs, pos = [], 0
    for p_ in pts:
        t_ = str(p_[5] or "")
        j = line.find(t_, pos) if t_ else pos
        if j < 0:
            return [(line, rg)]
        offs.append(j)
        pos = j + len(t_)
    out = []
    bounds = [0] + cut + [len(pts)]
    for a, b in zip(bounds, bounds[1:]):
        lo = 0 if a == 0 else offs[a]
        hi = len(line) if b == len(pts) else offs[b]
        sub = dict(rg)
        sub["pts"] = pts[a:b]
        if b < len(pts):
            last = pts[b - 1]
            if len(last) > 6 and last[6]:
                sub["end"] = [round(float(last[6][0]), 2), round(float(last[6][1]), 2)]
            else:
                ang_r = math.radians(float(last[2] or 0.0))
                ln_ = 0.5 * max(float(last[3] or 1.0), 1.0) * len(str(last[5] or ""))
                sub["end"] = [round(float(last[0]) + ln_ * math.cos(ang_r), 2),
                              round(float(last[1]) + ln_ * math.sin(ang_r), 2)]
        out.append((line[lo:hi], sub))
    return out


def _rot_cell_host(cell_runs: list, rg: dict):
    """Ячейка последнего ряда повёрнутой таблицы, которую продолжает строка
    `rg`: строка начата строчной или скобкой, тот же угол, начало строки —
    на начале куска первой строки ячейки (±`ROT_COL_TOL`),
    и строка стоит рядом с последней строкой ячейки (не дальше 2.5 кегля
    поперёк пути). Иначе None."""
    pts = rg.get("pts") or []
    if not pts or rg.get("curved"):
        return None
    # Продолжение фразы начинается строчной или скобкой («required»,
    # «(pioglitazone…»); строка с заглавной — уже ДРУГОЕ значение того же
    # столбца в следующем ряду (ряд из одной ячейки в ячейки не режется).
    head = str(pts[0][5] or "").lstrip()
    if not head or not (head[0].islower() or head[0] in "([{"):
        return None
    a0 = float(pts[0][2] or 0.0)
    pos = _along(pts[0])
    ar = math.radians(a0)
    across = lambda p_: -float(p_[0]) * math.sin(ar) + float(p_[1]) * math.cos(ar)  # noqa: E731
    size = max(float(pts[0][3] or 1.0), 1.0)
    for run_ in cell_runs:
        g_ = run_.geo[-1] if run_.geo else None
        if not g_ or not g_.get("pts"):
            continue
        last = g_["pts"][0]
        if abs(float(last[2] or 0.0) - a0) > 5.0:
            continue
        # Начало любого куска первой строки ячейки: у пункта с маркером
        # продолжение выровнено по тексту после «•» (висячий отступ).
        starts = [_along(p_) for p_ in run_.geo[0]["pts"]]
        if (any(abs(v - pos) <= ROT_COL_TOL for v in starts)
                and 0 < abs(across(last) - across(pts[0])) <= 2.5 * size):
            return run_
    return None


def _rot_centered_host(cands: list, rg: dict, cols: "dict | None" = None):
    """Пачка, которую продолжает повёрнутая надпись `rg`: та начата строчной
    или скобкой, стоит на соседней строке (не дальше 2.5 кегля поперёк пути),
    под тем же углом, и её отрезок вдоль пути и отрезок последней строки пачки
    перекрываются на половину меньшего — ячейка, выключенная по центру,
    чьи строки начинаются в разных местах. Иначе None."""
    pts = rg.get("pts") if rg else None
    if not pts or rg.get("curved"):
        return None
    head = str(pts[0][5] or "").lstrip()
    if not head or not (head[0].islower() or head[0] in "([{"):
        return None
    a0 = float(pts[0][2] or 0.0)
    ar = math.radians(a0)
    across = lambda p_: -float(p_[0]) * math.sin(ar) + float(p_[1]) * math.cos(ar)  # noqa: E731
    size = max(float(pts[0][3] or 1.0), 1.0)
    lo, hi = _along(pts[0]), _rot_piece_end(pts[-1])
    # Значение столбца ДАННЫХ («(95% CI)» под «0.8») — не продолжение
    # ячейки: оно стоит на начале столбца (`_rot_columns`).
    starts = (cols or {}).get(int(round(a0 / 5.0)) * 5) or []
    if any(abs(lo - c_) <= ROT_COL_TOL for c_ in starts):
        return None
    for run_ in cands:
        g_ = run_.geo[-1] if run_.geo else None
        gp = (g_ or {}).get("pts") if isinstance(g_, dict) else None
        if not gp or g_.get("curved") or abs(float(gp[0][2] or 0.0) - a0) > 5.0:
            continue
        glo, ghi = _along(gp[0]), _rot_piece_end(gp[-1])
        if abs(glo - lo) <= ROT_COL_TOL:
            continue                    # одно начало — это `_rot_cell_host`, не центр
        ov = min(hi, ghi) - max(lo, glo)
        if (ov >= 0.5 * max(1e-6, min(hi - lo, ghi - glo))
                and 0 < abs(across(gp[0]) - across(pts[0])) <= 2.5 * size):
            return run_
    return None


# Пробел в тексте дуги (Т25). Симптом: «Including:nationaldiabetesstrategy;
# nationalreimbursementpolicy» (стр. 31), «COMPLEXPATHOPHYSIOLOGY» — перевод
# получал текст без пробелов и копировал «:» и «;» вплотную к слову
# («Включая:национальную»). Причина: пробел ставился при зазоре шире ЧЕТВЕРТИ
# кегля, а между словами дуги стоит обычный пробел шрифта — 0.17–0.24 кегля
# (Calibri 0.226, DIN Condensed 0.176), внутри слова зазор 0.01–0.03: порог
# был недостижим. Правило: пробел — зазор шире `PATH_GAP_EM` кегля и шире
# `PATH_GAP_MEDIAN` медианных зазоров этой же строки (букворазрядка: пробел
# заметно шире межбуквенного зазора); у мелкой подписи (кегль меньше
# `PATH_GAP_MIN_SIZE` — миниатюра рисунка на обложке, координаты округлены
# до сотых пункта) — прежний порог. `PDF_PATH_GAP=0` — прежнее правило.
PATH_GAP_EM = 0.12
PATH_GAP_MEDIAN = 2.2
PATH_GAP_MIN_SIZE = 3.0
PATH_GAP_OLD = 0.25
PATH_GAP_ON = os.environ.get("PDF_PATH_GAP", "1") != "0"
_PATH_OPEN = "([{«“‘<"
_PATH_CLOSE = ")]}»”’.,;:!?%"


def _path_gap(gaps: list, size: float, letters: bool = True) -> float:
    """Порог зазора (в кеглях), от которого между буквами дуги стоит пробел.
    Никогда не строже прежнего (`PATH_GAP_OLD`): правило только ДОБАВЛЯЕТ пробелы
    там, где зазор уже слова, но уже четверти кегля. У строки из КУСКОВ-слов
    (повёрнутая таблица: «Increased risk» | «Neutral» | «•») зазоры — между
    словами, их медиана — не межбуквенный шаг, и правило не действует: на
    таблице стр. 9 проекта 14 пробелы пропали бы, а с ними и маркер пункта."""
    if not PATH_GAP_ON or not letters or size < PATH_GAP_MIN_SIZE or not gaps:
        return PATH_GAP_OLD
    med = sorted(gaps)[len(gaps) // 2]
    return min(PATH_GAP_OLD, max(PATH_GAP_EM, PATH_GAP_MEDIAN * med))


def _path_text(geo: dict) -> str:
    """Текст повёрнутой строки по её пути — С ПРОБЕЛАМИ.

    У текста по дуге каждая буква — свой кусок, и pypdf склеивает их без
    пробелов («COMPLEXPATHOPHYSIOLOGY»): переводить такое нельзя. Пробел
    стоит там, где зазор между соседними буквами пути заметно больше
    обычного шага (медиана шага на знак)."""
    pts = geo.get("pts") or []
    if not pts or any(len(p) < 6 for p in pts):
        return ""
    # Точнее всего — по КОНЦУ предыдущей буквы (оператор знает его по
    # метрикам): зазор до начала следующей шире порога — пробел (`_path_gap`).
    if all(len(p) > 6 and p[6] for p in pts[:-1]):
        gaps = [math.hypot(b[0] - a[6][0], b[1] - a[6][1]) / max(a[3], 1.0)
                for a, b in zip(pts, pts[1:])]
        thr = _path_gap(gaps, statistics.median([p[3] for p in pts]),
                        statistics.median([len((p[5] or "").strip()) for p in pts]) <= 1.5)
        out = pts[0][5]
        for gap, b in zip(gaps, pts[1:]):
            first = (b[5] or " ").lstrip()[:1]
            if (gap > thr and not out.endswith(" ") and out[-1:] not in _PATH_OPEN
                    and first not in _PATH_CLOSE):
                out += " "
            out += b[5]
        return out
    steps = []
    for a, b in zip(pts, pts[1:]):
        steps.append(math.hypot(b[0] - a[0], b[1] - a[1]) / max(1, a[4]))
    med = sorted(steps)[len(steps) // 2] if steps else 0.0
    out = pts[0][5]
    for k, b in enumerate(pts[1:]):
        if med and steps[k] > 1.6 * med and not out.endswith(" "):
            out += " "
        out += b[5]
    return out


def _rot_follows(a: dict, b: dict) -> bool:
    """Повёрнутая строка b продолжает надпись a: начинается рядом с её концом
    либо под ней (следующая строка той же повёрнутой таблицы) и под тем же
    углом."""
    pa, pb = a.get("pts") or [], b.get("pts") or []
    if not pa or not pb:
        return False
    s = max(pa[0][3], pb[0][3], 1.0)
    if abs(((pa[-1][2] - pb[0][2]) + 180) % 360 - 180) > 25:
        return False
    end = a.get("end") or pa[-1][:2]
    near_end = math.hypot(pb[0][0] - end[0], pb[0][1] - end[1]) <= 3 * s
    near_start = math.hypot(pb[0][0] - pa[0][0], pb[0][1] - pa[0][1]) <= 2.5 * s
    return near_end or near_start


class _HiddenRun(list):
    """Пачка НЕВИДИМЫХ строк (за обрезкой, под закраской): на листе её нет,
    и в отчёт «осталось на языке оригинала» она не идёт."""
# Перенос слова в конце строки: дефис, мягкий перенос, «ДЕФИС» Юникода.
_WORD_BREAK = ("-", SOFT, "‐")


def _geo_page(lines: list, g, placeless: "list | None" = None) -> "list | None":
    """Строки страницы с местом: [{t, x0, x1, y, s}] в порядке потока; None —
    у страницы нет полной геометрии (тогда она идёт прежней дорогой).

    `placeless` — куда сложить строки БЕЗ места (повёрнутые), подряд идущие —
    одной пачкой: [[строка, …], …]. Не передан — как прежде: одна такая
    строка, и у страницы геометрии нет."""
    if not isinstance(g, dict):
        return None
    gl = g.get("lines") or []
    if len(gl) != len(lines):
        return None
    recs = []
    runs: list = []
    run = _RotRun()
    rot = g.get("rot") or {}
    rot_cols = _rot_columns(rot) if rot else {}
    cell_runs: list = []                # ячейки последнего ряда повёрнутой таблицы
    hrun: list = []                     # подряд идущие НЕВИДИМЫЕ строки
    hidden_runs: list = []
    total = 0
    # Строка ответа, в которой pypdf склеил РАЗНЫЕ надписи одной базовой
    # линии (`split` геометрии: [смещение, место] на каждую), — несколько
    # строк, каждая со своим местом: иначе подпись у левого края вставала
    # в абзац рамки посреди схемы.
    split = g.get("split") or {}
    pairs = []
    for li, (l, p) in enumerate(zip(lines, gl)):
        subs = split.get(str(li))
        if subs and l:
            offs = [int(sg[0]) for sg in subs] + [len(l)]
            if all(0 <= offs[k] < offs[k + 1] <= len(l) for k in range(len(subs))) and offs[0] == 0:
                for k, sg in enumerate(subs):
                    pairs.append((li, l[offs[k]:offs[k + 1]], sg[1]))
                continue
        pairs.append((li, l, p))
    for li, l, p in pairs:
        t = _tidy(l or "")
        if not t:
            continue
        if isinstance(p, list) and not p:
            # Невидимая (за обрезкой, под закраской) — своей пачкой подряд
            # идущих, в чужой абзац её не вливаем, и в порог «половина без
            # места» она не входит: порог про повёрнутую страницу, а большой
            # невидимый слой лишал раскладки видимый текст.
            if placeless is None:
                return None
            if run:
                runs.append(run)
                run = _RotRun()
            hrun.append(l or "")
            continue
        if hrun:
            hidden_runs.append(_HiddenRun(hrun))
            hrun = []
        total += 1
        if not p or len(p) < 4:
            if placeless is None:
                return None             # строка без места — страница без геометрии
            rg = rot.get(str(li))
            cells = _rot_cells(l or "", rg, rot_cols) if rg else [(l or "", rg)]
            if len(cells) > 1:
                # Ряд повёрнутой таблицы: каждая ячейка — своя пачка (свой абзац).
                # Ячейка, продолжающая надпись строки выше (двухстрочная
                # ячейка шапки, выключенная по центру: «Route of» /
                # «administration»), — в её абзац (`_rot_centered_host`).
                prev = ([run] if run else []) + list(cell_runs)
                if run:
                    runs.append(run)
                cell_runs = []
                for t_, g_ in cells:
                    host_ = _rot_centered_host(prev, g_, rot_cols)
                    if host_ is not None:
                        host_.add(t_, g_)
                        continue
                    run = _RotRun()
                    run.add(t_, g_)
                    runs.append(run)
                    cell_runs.append(run)
                run = _RotRun()
                continue
            host = _rot_cell_host(cell_runs, rg) if (rg and cell_runs) else None
            if host is not None:
                # Продолжение текста ячейки следующей повёрнутой строкой
                # («Generally not» / «recommended in…»): в её же абзац.
                host.add(l or "", rg)
                continue
            if rg and not rg.get("curved"):
                cell_runs = []
            if run and run.geo and (
                    (rg and run.geo[-1] and not _rot_follows(run.geo[-1], rg))
                    # Строка без пути (Т21): проверить, продолжает ли она
                    # соседнюю, нечем, и склеивать её с ней нельзя.
                    or (ROT_NOPATH_SPLIT and bool(run.geo[-1]) != bool(rg))):
                # Другая надпись (дуга кольца и вертикальная подпись рядом
                # в потоке) — своей пачкой, а не одним абзацем на двоих.
                runs.append(run)
                run = _RotRun()
            run.add(l or "", rg)
            continue
        if run:
            # Пачка без места ВНУТРИ абзаца (перед ней перенос слова или
            # следующая строка продолжает со строчной) остаётся В ПОТОКЕ —
            # сразу за предыдущей строкой, в том же абзаце, без рамки.
            # Вынутая в конец страницы, она разорвала бы фразу на два
            # перевода (повёрнутое слово посреди фразы); а страницу целиком
            # на прежнюю дорогу не уводим: у PDF-«ленты» это весь документ.
            # Только после ПЕРЕНОСА слова: строчная в начале следующей строки —
            # слабый признак (подпись оси схемы между строками фразы вливалась
            # бы в саму фразу).
            if recs and recs[-1]["t"].rstrip().endswith(_WORD_BREAK):
                recs[-1].setdefault("after", []).extend(run)
            else:
                runs.append(run)
            run = _RotRun()
        raw = _TAB_RE.sub(" ", l or "")
        # Был ли у сырой строки пробел по краям: `_tidy` его снимает, а при
        # склейке разорванной строки он единственное ТОЧНОЕ свидетельство
        # («…площадь в м» + «2» + « измеряют так.»). Зазор по x — оценка:
        # у куска в один знак конец строки считается по ширине знака.
        recs.append({"t": t, "x0": float(p[0]), "y": float(p[1]), "s": float(p[2] or 0),
                     "x1": max(float(p[3]), float(p[0])),
                     # Начертание строки: распознаватель отмечает полужирный
                     # и курсив именем шрифта. Нет поля (геометрия записана
                     # прежним кодом) — «обычное», и это не ложь: мы просто
                     # не знаем.
                     "st": (p[4] if len(p) > 4 else "") or "",
                     # Гарнитура (sans / serif / mono): нет поля — «не знаем»,
                     # и абзац возьмёт гарнитуру документа.
                     "fam": (p[5] if len(p) > 5 else "") or "",
                     # Начало последнего куска строки — точное (x1 — оценка).
                     "xl": float(p[6]) if len(p) > 6 and p[6] is not None else None,
                     # Строка ответа pypdf, в которой на деле ДВЕ визуальные
                     # строки (сноска с надстрочной цифрой): места каждой.
                     "parts": (p[7] if len(p) > 7 else None) or None,
                     # Конец строки посчитан по метрикам шрифта, а не оценён.
                     "exact": bool(p[8]) if len(p) > 8 else False,
                     # Цвет краски строки из самого PDF (оператор заливки),
                     # None — не знаем, выгрузка мерит по странице.
                     "color": p[9] if len(p) > 9 else None,
                     # Разрывы строки: [[конец куска, начало следующего]] —
                     # там, где по слою пусто (в картинке там бывает текст).
                     "gaps": p[10] if len(p) > 10 else None,
                     "lsp": raw[:1] == " ", "rsp": raw[-1:] == " ",
                     # Номер строки ответа pypdf: части одной строки (`split`)
                     # колонками друг другу не свидетельствуют.
                     "li": li})
    if run:
        if recs and recs[-1]["t"].rstrip().endswith(_WORD_BREAK):
            recs[-1].setdefault("after", []).extend(run)
        else:
            runs.append(run)
    if hrun:
        hidden_runs.append(_HiddenRun(hrun))
    # В порог идут только строки, которым НЕКУДА встать: повёрнутая строка
    # с путём печатается по нему и раскладку страницы не портит.
    lost = (sum(sum(1 for g_ in (getattr(r, "geo", None) or [None] * len(r)) if not g_) for r in runs)
            + sum(len(r.get("after") or []) for r in recs))
    if placeless is not None and (lost or runs or hidden_runs):
        if not recs or lost > GEO_PLACELESS_MAX * max(total, 1):
            return None
        placeless.extend(runs + hidden_runs)
    return recs


def _multi_column(recs: list) -> bool:
    """Две длинные строки на одной высоте далеко друг от друга — колонки.
    Тогда порядок потока оставляется: сортировка по высоте перемешала бы
    колонки построчно."""
    long_ = [r for r in recs if len(r["t"]) >= 15]
    for i, a in enumerate(long_):
        for b in long_[i + 1:]:
            if a.get("li") is not None and a.get("li") == b.get("li"):
                continue                # две надписи одной строки pypdf — не колонки
            s = max(a["s"], b["s"], 1.0)
            if abs(a["y"] - b["y"]) < 0.5 * s and abs(a["x0"] - b["x0"]) > 5 * s:
                return True
    # Колонки с разным интерлиньяжем (или сдвинутые на полстроки) на одной
    # высоте не встречаются. Тогда — по краям: начала длинных строк делятся
    # на две группы с разрывом больше пяти кеглей, в каждой не меньше трёх
    # строк, группы идут на одной высоте, и левая КОНЧАЕТСЯ до начала
    # правой. Последнее отличает колонки от эпиграфа и врезки справа: строки
    # тела над ними доходят до правого поля, то есть заходят на их место.
    if len(long_) < 6:
        return False
    xs = sorted(long_, key=lambda r: r["x0"])
    s = statistics.median(r["s"] for r in long_) or 1.0
    gap, k = max((xs[i + 1]["x0"] - xs[i]["x0"], i + 1) for i in range(len(xs) - 1))
    if gap <= 5 * s:
        return False
    left, right = xs[:k], xs[k:]
    if len(left) < 3 or len(right) < 3:
        return False
    r_x0 = min(r["x0"] for r in right)
    if sum(1 for r in left if r["x1"] > r_x0 - 0.5 * s) > 0.1 * len(left):
        return False
    lo = max(min(r["y"] for r in left), min(r["y"] for r in right))
    hi = min(max(r["y"] for r in left), max(r["y"] for r in right))
    span = min(max(r["y"] for r in g) - min(r["y"] for r in g) for g in (left, right))
    return hi - lo >= 0.5 * span > 0


# Таблица: строк, в которых не меньше стольких ячеек, и не меньше стольких
# таких строк. Три колонки бывают у обычного текста (колонки страницы), четыре
# и больше на одной высоте — у таблицы.
TABLE_MIN_CELLS = 4
TABLE_MIN_ROWS = 3
TABLE_CELL_SHARE = 0.35      # ячейка уже такой доли ширины текста страницы
TABLE_COL_TOL = 4.0          # начала ячеек одной колонки — в этом допуске, пт
TABLE_COL_MERGE = 2.5        # начала ближе стольких кеглей — одна колонка
TABLE_CELL_MEDIAN = 0.2      # средняя (медиана) ячейка строки таблицы — уже такой доли


TABLE_IN_COLUMN = 0.8        # Ц7: такая доля ячеек — в одной колонке страницы


def _crosses_cols(r: dict, cols: list, pool: list) -> bool:
    """Строка одна на своей высоте и перекрывает начало колонки таблицы."""
    s_ = max(r["s"], 1.0)
    if any(o is not r and abs(o["y"] - r["y"]) <= 0.3 * s_ for o in pool):
        return False
    return any(r["x0"] + TABLE_COL_TOL < c < r["x1"] - TABLE_COL_TOL for c in cols)


def _table_page_column(recs: list, table_rows: list, width: float, s: float) -> "tuple | None":
    """(x0, x1) колонки страницы, в которой стоит таблица, — или None, если
    страница в одну колонку или таблица шире колонки. Колонки страницы —
    по длинным строкам (шире `TABLE_CELL_SHARE` ширины текста), разделённым
    по началу зазором больше пяти кеглей, как у `_multi_column`."""
    long_ = sorted((r for r in recs if r["x1"] - r["x0"] > TABLE_CELL_SHARE * width),
                   key=lambda r: r["x0"])
    if len(long_) < 6:
        return None
    groups: list = [[long_[0]]]
    for r in long_[1:]:
        if r["x0"] - groups[-1][-1]["x0"] > 5 * s:
            groups.append([r])
        else:
            groups[-1].append(r)
    groups = [g for g in groups if len(g) >= 3]
    if len(groups) < 2:
        return None
    cells = [c for row in table_rows for c in row]
    for g in groups:
        # Края колонки — по МЕДИАНЕ: строка во всю ширину (подпись рисунка,
        # заголовок) начата там же, где левая колонка, и растянула бы её край.
        gx0 = statistics.median(r["x0"] for r in g)
        gx1 = statistics.median(r["x1"] for r in g)
        inside = sum(1 for c in cells if c["x0"] >= gx0 - TABLE_COL_TOL and c["x1"] <= gx1 + s)
        if inside >= TABLE_IN_COLUMN * len(cells):
            return gx0, gx1
    return None


def _table_streams(recs: list, report: Counter) -> "list | None":
    """Записи страницы, где есть ТАБЛИЦА, — в порядке «колонка за колонкой».

    pypdf отдаёт таблицу построчно: строка таблицы — это ячейки всех колонок
    подряд, а вторая строка многострочной ячейки идёт после ячеек соседей.
    Абзацы же собираются по соседству в потоке (`_geo_follows`), и ячейка
    «Neutral (potential / for modest loss)» склеивалась с соседней колонкой,
    а длинная ячейка «Clinical considerations» рвалась на абзацы по строке.
    Колонкой за колонкой строки одной ячейки идут подряд, а ячейки разных
    строк таблицы разделяет межстрочный зазор — абзацы складываются сами.

    None — таблицы нет (порядок не трогаем). Таблицей считается не меньше
    `TABLE_MIN_ROWS` строк по `TABLE_MIN_CELLS` узких ячеек на одной высоте."""
    if len(recs) < TABLE_MIN_CELLS * TABLE_MIN_ROWS:
        return None
    x_lo = min(r["x0"] for r in recs)
    x_hi = max(r["x1"] for r in recs)
    width = max(1.0, x_hi - x_lo)
    rows: list = []
    for r in sorted(recs, key=lambda r: -r["y"]):
        if rows and abs(rows[-1][0]["y"] - r["y"]) < 0.3 * max(r["s"], 1.0):
            rows[-1].append(r)
        else:
            rows.append([r])
    table_rows = []
    for row in rows:
        cells = sorted(row, key=lambda r: r["x0"])
        if len(cells) < TABLE_MIN_CELLS:
            continue
        if any(c["x1"] - c["x0"] > TABLE_CELL_SHARE * width for c in cells):
            continue
        # Колонки текста страницы — тоже «ячейки на одной высоте», но широкие
        # (треть листа); у таблицы ячейка типичной строки узкая.
        if statistics.median(c["x1"] - c["x0"] for c in cells) > TABLE_CELL_MEDIAN * width:
            continue
        if any(b["x0"] < a["x1"] for a, b in zip(cells, cells[1:])):
            continue                    # ячейки строки не налезают друг на друга
        table_rows.append(cells)
    if len(table_rows) < TABLE_MIN_ROWS:
        return None
    # Начала колонок — начала ячеек, повторённые хотя бы в двух строках.
    # Начала ближе `TABLE_COL_MERGE` кеглей — одна колонка: маркер «•»
    # и текст после него, висячий отступ второй строки ячейки, шапка,
    # выключенная по центру. Ячейка уже двух с половиной кеглей не бывает.
    body_s = max(1.0, statistics.median(c["s"] for row in table_rows for c in row))
    xs = sorted(c["x0"] for row in table_rows for c in row)
    groups_x: list = []
    for x in xs:
        if groups_x and x - groups_x[-1][-1] <= TABLE_COL_MERGE * body_s:
            groups_x[-1].append(x)
        else:
            groups_x.append([x])
    cols = [g[0] for g in groups_x if len(g) >= 2]
    if len(cols) < TABLE_MIN_CELLS:
        return None
    # Ц7: таблица стоит в ОДНОЙ колонке страницы — строки соседней колонки
    # на той же высоте ей не принадлежат. Симптом (статья «Бюллетеня
    # сибирской медицины», стр. 4): строки левой колонки («…этапы: начальная
    # денатурация в течение 10 мин при») шли вперемешку с ячейками таблицы
    # правой колонки («аддитивная», «rs10905277», «AG»), а расширение таблицы
    # вверх упиралось в длинную строку левой колонки, и шапка с заголовком
    # отрывались от тела таблицы.
    span = _table_page_column(recs, table_rows, width, body_s)
    pool = recs
    if span is not None:
        cols = [x for x in cols if span[0] - TABLE_COL_TOL <= x <= span[1]] or cols
        pool = [r for r in recs if r["x0"] >= span[0] - TABLE_COL_TOL and r["x1"] <= span[1] + body_s]
        width = max(1.0, span[1] - span[0])

    def col_of(r):
        k = 0
        for i, x in enumerate(cols):
            if x <= r["x0"] + TABLE_COL_TOL:
                k = i
        return k
    top = max(c["y"] for c in table_rows[0])
    low = min(c["y"] for c in table_rows[-1])
    lead = 3.0 * max(1.0, statistics.median(c["s"] for row in table_rows for c in row))

    def in_col(r):
        k = col_of(r)
        return -TABLE_COL_TOL <= r["x0"] - cols[k] <= TABLE_COL_MERGE * body_s
    # Таблица продолжается ниже последней строки, пока под ней идут строки,
    # начатые в одной из колонок, без зазора больше трёх кеглей (длинная
    # ячейка последней строки); строка не с начала колонки («Продолжение
    # на с. 6» у правого края) — уже не таблица.
    prev = low
    for r in sorted((r for r in pool if r["y"] < low), key=lambda r: -r["y"]):
        if prev - r["y"] > lead or not in_col(r):
            break
        low = prev = r["y"]
    # И выше первой: шапка из нескольких строк («Effects on / cardiovascular
    # outcomes») — узкие строки с зазором не больше трёх кеглей.
    prev = top
    for r in sorted((r for r in pool if r["y"] > top), key=lambda r: r["y"]):
        if r["y"] - prev > lead or r["x1"] - r["x0"] > TABLE_CELL_SHARE * width:
            break
        if span is not None and _crosses_cols(r, cols, pool):
            # Ц7: строка без соседей по ряду, перекрывающая начало колонки
            # таблицы, — заголовок над таблицей («бронхиальной астмы», вторая
            # строка названия по центру), а не ячейка шапки.
            break
        top = prev = r["y"]
    top += 0.1
    ids = {id(r) for r in pool if low - 0.1 <= r["y"] <= top}
    block = [r for r in recs if id(r) in ids]
    if len(block) < TABLE_MIN_CELLS * TABLE_MIN_ROWS:
        return None
    tid = report["tables"] = report.get("tables", 0) + 1
    # Строки таблицы — по ПЕРВОЙ колонке: где в ней начата ячейка, там
    # начата строка таблицы. Ячейка одной колонки из другой строки таблицы —
    # другой абзац, даже если стоит вплотную (шапка «Heart failure» над
    # «Neutral» первой строки).
    # Границы — только от строк первой колонки, начинающих ЯЧЕЙКУ (Т6):
    # а) не выше первой строки таблицы: узкий заголовок «Table 1—Continued»
    #    над шапкой попадал в блок, «съедал» первую границу, и граница
    #    вставала по «Medication» — шапка «Dosing/use | considerations»
    #    резалась на два абзаца и переводилась кусками («Дозирование-
    #    применение соображения», «Путь введение», стр. 7–8);
    # б) вторая строка ячейки первой колонки («Dual GLP-1/GIP | agonists»:
    #    строчная, шаг до `TABLE_CONT_LEAD` кеглей, выше нет конца фразы) —
    #    продолжение, а не новая строка таблицы: иначе граница по ней резала
    #    ячейки ВСЕХ колонок («Benefit for kidney end | points in CVOTs»).
    first_y = max(c["y"] for c in table_rows[0]) + 0.5

    def cont_of(o):
        """Строка `o` продолжает ячейку своей колонки: строчная, близко под
        предыдущей строкой той же колонки, у которой нет конца фразы."""
        if not o["t"][:1].islower():
            return False
        k = col_of(o)
        up = [u for u in block if u is not o and col_of(u) == k and u["y"] > o["y"]
              and u["y"] - o["y"] <= TABLE_CONT_LEAD * max(o["s"], 1.0)]
        return bool(up) and not _END_RE.search(min(up, key=lambda u: u["y"])["t"])

    def mates(r):
        """Сколько других колонок НАЧИНАЮТ ячейку на высоте строки `r`
        (продолжение чужой ячейки — не начало)."""
        s_ = max(r["s"], 1.0)
        return sum(1 for o in block if o is not r and col_of(o) != 0
                   and abs(o["y"] - r["y"]) <= 0.3 * s_ and not cont_of(o))
    row_tops: list = []
    prev_c0 = None
    # Выше первой строки таблицы отбрасывается только ОДИНОКАЯ строка первой
    # колонки (заголовок «Table 1—Continued»): строка с соседями по ряду —
    # строка таблицы, пусть и редкая (прайс: «Решётка радиатора | 650 000»).
    c0 = [r for r in block if col_of(r) == 0 and (r["y"] <= first_y or mates(r) > 0)]
    for r in sorted(c0, key=lambda r: -r["y"]):
        # Продолжение ячейки — только если на этой высоте ни одна другая
        # колонка не начинает ячейку: строчный столбец с тесным шагом
        # («metformin / insulin / aspirin») — это строки таблицы.
        cont = (prev_c0 is not None and 0 < prev_c0["y"] - r["y"] <= TABLE_CONT_LEAD * max(r["s"], 1.0)
                and r["t"][:1].islower() and not _END_RE.search(prev_c0["t"]) and mates(r) == 0)
        if not cont and (not row_tops or round(r["y"], 1) != row_tops[-1]):
            row_tops.append(round(r["y"], 1))
        prev_c0 = r
    # Первую границу не ставим: у шапки ячейка первой колонки прижата к НИЗУ
    # («Medication» на одной линии с «of CKD»), и граница по ней разрезала бы
    # многострочные ячейки шапки. Строки данных прижаты к верху.
    row_tops = row_tops[1:]
    for r in block:
        band = sum(1 for y in row_tops if y >= r["y"] - 0.3 * max(r["s"], 1.0))
        r["tcol"] = (tid, col_of(r), band)
    order = sorted(block, key=lambda r: (r["tcol"][1], -r["y"], r["x0"]))
    rest = [r for r in recs if id(r) not in ids]
    # Остальное на странице (заголовок таблицы, колонтитул, текст под ней) —
    # обычным порядком чтения, если это не колонки; таблица встаёт по высоте.
    if not _multi_column(rest):
        rest = _reading_order(rest)
    first = next((i for i, r in enumerate(rest) if r["y"] < top - 0.1), len(rest))
    if span is not None:
        # Ц7: таблица встаёт в поток СВОЕЙ колонки — после строки этой колонки
        # над ней (иначе — перед строкой этой колонки под ней), а не перед
        # первой строкой страницы ниже её верха: у таблицы правой колонки это
        # была бы левая колонка, и абзац, перешедший со страницы, рвался.
        incol = [i for i, r in enumerate(rest)
                 if r["x0"] >= span[0] - TABLE_COL_TOL and r["x1"] <= span[1] + body_s]
        above = [i for i in incol if rest[i]["y"] > top]
        below = [i for i in incol if rest[i]["y"] < low]
        if above:
            first = max(above) + 1
        elif below:
            first = min(below)
    report["tableCells"] += len(block)
    return rest[:first] + order + rest[first:]


# Т11. Значок-КОНТУР (path: галочка, шприц, кружок в инфографике) — тот же
# маркер пункта, что и картинка, но менее надёжный: на листе мелких контуров
# тысячи (цифры ссылок «(51)» синим, стрелки-коннекторы, буквы кривыми), и
# без защит абзацы текстовых страниц рвались посреди фразы (замер на книге
# в 46 страниц: 37 абзацев → 81, 44 ложных на стр. 11–30). Три защиты:
#  1) значок вплотную к строке — не дальше `ICON_REACH` кегля (у картинки
#     прежние 2.5): значок пункта стоит в одном шаге от текста, а цифра
#     ссылки соседней колонки — в полутора-двух;
#  2) значок не стоит у конца ЧУЖОЙ строки на той же базовой линии (это
#     кривые знаки её текста, а не маркер);
#  3) пункт начинается не со строчной буквы: строка, продолжающая фразу
#     («complications including:»), абзац не начинает, что бы ни стояло слева.
ICON_REACH = 1.5


def icon_backdrop(boxes: list) -> list:
    """Значки без ФОНА: прямоугольники одной ширины и одного x, стоящие
    столбиком ВПЛОТНУЮ (зазор меньше 5% высоты, либо внахлёст), — это
    полосы заливки под строками (серый фон аннотации статьи нарисован
    полосой на каждую строку), а не маркеры списка. Маркеры пунктов
    отделены друг от друга межстрочным зазором. Без этого каждая строка
    аннотации считалась пунктом (статья 19, сверка выгрузки 13.10)."""
    cols: dict = {}
    for k, b in enumerate(boxes):
        x0, y0, x1, y1 = (float(v) for v in b[:4])
        cols.setdefault((round(x0), round(x1)), []).append((y0, y1, k))
    stacked = set()
    for (cx0, cx1), items in cols.items():
        # Соседние ключи (округление разрезало колонку) — тот же столбик.
        for dx0 in (-1, 0, 1):
            for dx1 in (-1, 0, 1):
                if (dx0 or dx1) and (cx0 + dx0, cx1 + dx1) in cols:
                    items = items + cols[(cx0 + dx0, cx1 + dx1)]
        items = sorted(items)
        if any(ka != kb and b0 - a1 < 0.05 * max(min(a1 - a0, b1 - b0), 1e-6)
               for (a0, a1, ka), (b0, b1, kb) in zip(items, items[1:])):
            # Хоть две полосы колонки вплотную — фон вся колонка: последняя
            # полоса аннотации стоит через отступ абзаца (строка цитаты под
            # аннотацией статьи 19) и в одиночку неотличима от маркера.
            stacked.update(k for _a, _b, k in items)
    return [b for k, b in enumerate(boxes) if k not in stacked]


def _mark_icon_bullets(recs: list, figs: list, icons: "list | None" = None) -> None:
    """Строка, перед которой слева стоит МАЛЕНЬКАЯ картинка на её высоте
    (галочка, восклицательный знак списка в инфографике), — пункт списка:
    `bul`, с неё начинается абзац (`_geo_follows`). Без этого пункты,
    идущие подряд с обычным интервалом, склеивались в один абзац, и перевод
    второго вставал в место первого. То же — значок-контур (`icons`,
    `pdfpages_worker`, Т11), но с защитами (см. `ICON_REACH`)."""
    small = []
    for f in figs or []:
        try:
            x0, y0, x1, y1 = (float(v) for v in f[:4])
        except (TypeError, ValueError):
            continue
        small.append((x0, y0, x1, y1, False))
    for f in icon_backdrop([f for f in (icons or []) if len(f) >= 4]):
        try:
            x0, y0, x1, y1 = (float(v) for v in f[:4])
        except (TypeError, ValueError):
            continue
        small.append((x0, y0, x1, y1, True))
    if not small:
        return
    for r in recs:
        s = max(r.get("s") or 1.0, 1.0)
        lo, hi = r["y"] - 0.3 * s, r["y"] + 0.9 * s
        for x0, y0, x1, y1, vec in small:
            if not (0.3 * s <= x1 - x0 <= 2.5 * s and 0.3 * s <= y1 - y0 <= 2.5 * s):
                continue
            reach = ICON_REACH if vec else 2.5
            if not (r["x0"] - reach * s <= x1 <= r["x0"] + 0.3 * s and min(hi, y1) - max(lo, y0) > 0.3 * s):
                continue
            if vec:
                t_ = (r.get("t") or "").lstrip()
                if not t_:
                    continue
                # Строчная в начале — не запрет сама по себе (пункты на
                # русском и немецком часто строчные): запрет, только когда
                # строка выше в той же колонке вплотную и не кончила фразу —
                # тогда это продолжение, а контур рядом чужой.
                if t_[0].islower():
                    up = [o for o in recs if o is not r and 0 < o["y"] - r["y"] <= 1.6 * s
                          and min(o["x1"], r["x1"]) - max(o["x0"], r["x0"]) > 0]
                    if up and not _END_RE.search(max(up, key=lambda o: -o["y"]).get("t") or ""):
                        continue
                if any(o is not r and abs(o["y"] - r["y"]) <= 0.4 * s and o["x0"] < x0
                       and o["x1"] >= x0 - 1.0 * s for o in recs):
                    continue
            r["bul"] = True
            break


def _size_leads(recs: list) -> dict:
    """{кегль, округлённый до 0.5: обычный межстрочный строк этого кегля} —
    медиана зазора между соседними строками одной колонки."""
    by: dict = {}
    srt = sorted(recs, key=lambda r: (round(r["x0"]), -r["y"]))
    for a, b in zip(srt, srt[1:]):
        s = max(a["s"], 1.0)
        if abs(a["s"] - b["s"]) > 0.15 * s or abs(a["x0"] - b["x0"]) > 1.0 * s:
            continue
        dy = a["y"] - b["y"]
        if 0.8 * s <= dy <= 3.0 * s:
            by.setdefault(round(a["s"] * 2) / 2.0, []).append(dy)
    return {k: statistics.median(v) for k, v in by.items() if len(v) >= 3}


def _lead_for(pg: dict, size: float) -> "float | None":
    """Межстрочный строк этого кегля на странице; не набралось замеров —
    межстрочный страницы, но не меньше 1.25 кегля: у заголовка в две строки
    своего замера нет, а межстрочный страницы с мелкими подписями схемы
    рвал бы его на абзацы-строки."""
    leads = pg.get("leads") or {}
    got = leads.get(round(size * 2) / 2.0)
    if got is not None:
        return got
    st_lead = (pg.get("st") or {}).get("lead") or 0.0
    return max(st_lead, 1.25 * size)


def _reading_order(recs: list) -> list:
    """Сверху вниз, в строке одной высоты — слева направо."""
    out = sorted(recs, key=lambda r: -r["y"])
    i = 0
    while i < len(out):
        j = i + 1
        while j < len(out) and out[i]["y"] - out[j]["y"] < 0.3 * max(out[i]["s"], 1.0):
            j += 1
        out[i:j] = sorted(out[i:j], key=lambda r: r["x0"])
        i = j
    return out


def _page_stats(recs: list) -> dict:
    """Основной кегль, левое и правое поле колонки, межстрочный интервал."""
    by = Counter()
    for r in recs:
        by[round(r["s"] * 2) / 2] += len(r["t"])
    body_s = by.most_common(1)[0][0] if by else 0.0
    body = [r for r in recs if body_s and abs(r["s"] - body_s) <= 0.1 * body_s + 0.25]
    # Левое поле — САМОЕ ЛЕВОЕ начало строк, у которого набирается опора
    # (три строки и не меньше доли тела), а не самое частое: на странице,
    # где врезка занимает больше половины (боевые стр. 36, 188), самым
    # частым началом было поле врезки, и вся врезка считалась телом.
    xs = sorted(r["x0"] for r in body)
    need = max(3, int(0.15 * len(xs)))
    left = xs[0] if xs else 0.0
    for v in xs:
        near = [x for x in xs if abs(x - v) <= 2.0]
        if len(near) >= need:
            left = statistics.median(near)
            break
    # Правое поле — по строкам, начатым от левого поля (строки врезки
    # короче и сдвинули бы его внутрь).
    x1s = sorted(r["x1"] for r in body if r["x0"] <= left + 2 * body_s) or sorted(r["x1"] for r in body)
    right = x1s[int(0.75 * (len(x1s) - 1))] if x1s else 0.0
    dys = [a["y"] - b["y"] for a, b in zip(body, body[1:])
           if 0 < a["y"] - b["y"] < 2.5 * body_s]
    lead = statistics.median(dys) if dys else 1.2 * (body_s or 10.0)
    return {"body_s": body_s or 10.0, "left": left, "right": right, "lead": lead,
            "n_body": len(body)}


def _bands(recs: list, st: dict, gap_k: float = None) -> tuple:
    """(верхняя полоса, нижняя полоса) — номера строк у края страницы,
    отделённых от текста пробелом больше обычного интервала: колонтитулы
    и номера. Сверху до трёх строк (двухстрочный колонтитул и номер),
    снизу — до двух. `gap_k` — свой порог пробела в интервалах (Ц2)."""
    gk = GEO_BAND_GAP if gap_k is None else gap_k

    def band(order: list, limit: int) -> list:
        if len(order) < 2:
            return []
        grp = [order[0]]
        for k in order[1:]:
            if len(grp) >= limit + 1:
                break
            if abs(recs[grp[-1]]["y"] - recs[k]["y"]) <= GEO_BAND_GAP * st["lead"] * 0.95:
                grp.append(k)
            else:
                break
        if len(grp) > limit:
            return []
        nxt = order[len(grp)] if len(grp) < len(order) else None
        if nxt is None or abs(recs[grp[-1]]["y"] - recs[nxt]["y"]) < gk * st["lead"]:
            return []
        return grp
    # Т15. Полоса — это МЕСТО на листе, а не номер строки в потоке pypdf.
    # Прежде `idx` шёл в порядке списка: на двухколонной странице поток клал
    # колонтитул В КОНЕЦ (и он становился «нижней» полосой, ключ ('b', …)),
    # на странице с таблицей порядок шёл по высоте (он становился «верхней»,
    # ключ ('t', …) с одной страницей — меньше HEAD_MIN_PAGES), а на странице,
    # где колонтитул лежал посреди потока (проект 14, стр. 26), он не попадал
    # ни в одну полосу и оставался ТЕЛОМ — отдельным абзацем с отдельным
    # переводом («8 Consensus Report» → «отчет», «18 …» → «отчёт»). Порядок
    # по высоте (при равной — слева направо) не зависит от того, как
    # распознаватель выложил поток.
    idx = sorted(range(len(recs)), key=lambda k: (-recs[k]["y"], recs[k]["x0"]))
    top, bottom = band(idx, HEAD_WINDOW), band(idx[::-1], FOOT_WINDOW)
    # Прежний счёт — по порядку потока — остаётся запасным ТАМ, где высота
    # полосы не дала: скан с задвоенным слоем распознавания (одна и та же
    # строка колонтитула дважды с разницей в пять пунктов, книга 8) складывает
    # у верха четыре строки, а окно — три; поток же ставил две нужные первыми.
    # Строки, уже попавшие в другую полосу по высоте, запасным ходом не берутся:
    # иначе колонтитул оказался бы и сверху, и снизу.
    if not top or not bottom:
        lin = list(range(len(recs)))
        if not top:
            top = [k for k in band(lin, HEAD_WINDOW) if k not in bottom]
        if not bottom:
            bottom = [k for k in band(lin[::-1], FOOT_WINDOW) if k not in top]
    return top, bottom


# Ц2. Колонтитул по МЕСТУ, когда пробела мало. Симптом (статья «Бюллетеня
# сибирской медицины»): на страницах 3, 5, 6 нижний колонтитул «Бюллетень
# сибирской медицины. 2026; 25 (3): 34–40» не попадал в полосу и вклеивался
# в последний абзац колонки («…другого иссле- Бюллетень сибирской медицины…»),
# а на странице 1 — в начало следующей страницы («…34–40 Для цитирования»).
# Причина: полоса требует пробела не меньше `GEO_BAND_GAP` интервалов, а здесь
# между колонтитулом и последней строкой колонки — 1.54 интервала (тело
# опущено до края, на страницах 1, 2, 4, 7 оно выше, и там полоса находится).
# Правило: на странице, где полоса не нашлась, она берётся с порогом
# `BAND_GAP_PLACED` — но только если ВСЕ её строки стоят на высоте полос,
# найденных обычным порогом на других страницах (не меньше двух, по
# `BAND_PLACE_TOL` пункта). Высота колонтитула — свойство вёрстки журнала,
# и случайная строка тела на ней же не окажется.
BAND_GAP_PLACED = float(os.environ.get("PDF_BAND_GAP_PLACED", "1.2"))
BAND_PLACE_TOL = 1.5


def _bands_by_place(laid: dict, report: dict) -> None:
    if BAND_GAP_PLACED >= GEO_BAND_GAP:
        return
    for side in ("top", "bottom"):
        seen: list = []                      # (страница, высота) строк найденных полос
        for i, pg in laid.items():
            seen += [(i, pg["recs"][k]["y"]) for k in pg[side]]
        if not seen:
            continue
        for i, pg in laid.items():
            if pg[side] or len(pg["recs"]) < 4:
                continue
            t2, b2 = _bands(pg["recs"], pg["st"], BAND_GAP_PLACED)
            got = t2 if side == "top" else b2
            if not got:
                continue
            ok = all(len({j for j, y in seen if j != i and abs(y - pg["recs"][k]["y"]) <= BAND_PLACE_TOL}) >= 2
                     for k in got)
            other = pg["bottom"] if side == "top" else pg["top"]
            if ok and not set(got) & set(other):
                pg[side] = got
                report["bandsByPlace"] = report.get("bandsByPlace", 0) + 1


# Кандидатов в колонтитул, встреченных пока по разу, нечётко сравниваем
# только с последними столькими: у книги, где на каждой странице своя
# строка в полосе (заголовок раздела, подпись), каждый новый кандидат
# сравнивался со всеми прежними — 1000 страниц разбирались больше минуты.
# Колонтитул повторяется на соседних страницах и из одиночек уходит сразу.
CLUSTER_SINGLES_MAX = 50


def _clusters() -> dict:
    """Кластеры строк полос: список, точный индекс по тексту и индекс
    по длине сложенной строки (`_similar_enough` не сравнивает строки, чья длина
    разнится больше чем на четверть, — их и не перебираем)."""
    return {"list": [], "exact": {}, "bylen": {}}


def _cluster_near(cl: dict, text: str) -> list:
    n = len(_fold(text))
    out = []
    for m in range(int(0.75 * n), int(n / 0.75) + 2):
        out.extend(cl["bylen"].get(m, ()))
    return out


def _cluster_add(cl: dict, text: str, page: int, size: float) -> None:
    c = cl["exact"].get(text)
    if c is None:
        near = _cluster_near(cl, text)
        many = sorted((x for x in near if len(x["pages"]) > 1), key=lambda x: -len(x["pages"]))
        singles = sorted((x for x in near if len(x["pages"]) == 1), key=lambda x: -x["n"])
        c = next((x for x in many[:CLUSTER_SINGLES_MAX] + singles[:CLUSTER_SINGLES_MAX]
                  if _similar_enough(x["rep"], text)), None)
        if c is None:
            c = {"rep": text, "pages": set(), "sizes": [], "n": len(cl["list"])}
            cl["list"].append(c)
            cl["bylen"].setdefault(len(_fold(text)), []).append(c)
        cl["exact"][text] = c
    c["pages"].add(page)
    c["sizes"].append(size)


def _cluster_reps(cl: dict) -> set:
    return {c["rep"] for c in cl["list"] if len(c["pages"]) >= HEAD_MIN_PAGES}


def _cluster_find(cl: dict, text: str, size: float) -> "dict | None":
    """Кластер колонтитула, к которому относится строка, — или None.
    Нужен и тому, кто спрашивает «да/нет» (`_cluster_hit`), и тому, кому нужен
    КЛЮЧ группы (представитель кластера): повёрнутый колонтитул встаёт в ту же
    группу, что и прямые (Т15)."""
    own = cl["exact"].get(text)             # строка уже в кластере — сравнивать незачем
    for c in [own] + [x for x in _cluster_near(cl, text) if x is not own]:
        if c is None or len(c["pages"]) < HEAD_MIN_PAGES:
            continue
        if c is own or c["rep"] == text or _similar_enough(c["rep"], text):
            med = statistics.median(c["sizes"])
            if not med or abs(size - med) <= 0.25 * med:
                return c
    return None


def _cluster_hit(cl: dict, text: str, size: float) -> bool:
    return _cluster_find(cl, text, size) is not None


# Т15. Повёрнутый колонтитул. Страница журнала, снятая боком (таблица на весь
# лист), хранит колонтитул вертикальной строкой у ПРАВОГО края; она идёт
# «бесхозной» повёрнутой строкой (`loose`) и сверок колонтитулов не проходила:
# «6 Consensus Report» на стр. 7, «18 …» на стр. 19, «30 …» на стр. 31
# становились телом — три отдельных сегмента, три отдельных перевода
# («доклад» / «отчёт»). Теперь такая строка у края листа сверяется с теми же
# кластерами (и с кластером повёрнутых строк — книга, где боком ВСЕ страницы)
# и уходит в тот же головной абзац, что прямые. Край — доля короткой стороны
# листа: подпись схемы посреди листа колонтитулом не бывает.
HEAD_ROT_EDGE = 0.08


def _rot_on_edge(rg: dict, box) -> bool:
    pts = (rg or {}).get("pts") or []
    if not pts or not box or len(box) < 4 or rg.get("curved"):
        return False
    xs = [p_[0] for p_ in pts] + [rg["end"][0]]
    ys = [p_[1] for p_ in pts] + [rg["end"][1]]
    m = HEAD_ROT_EDGE * min(box[2] - box[0], box[3] - box[1])
    return (min(xs) - box[0] <= m or box[2] - max(xs) <= m
            or min(ys) - box[1] <= m or box[3] - max(ys) <= m)


# Т15. Записка «Продолжение на с. 8» в конце страницы-таблицы — не начало
# абзаца и не конец чужого: после снятия колонтитула следующей страницы она
# оказывалась РЯДОМ с её первой строкой (строчной) и склеивалась с ней
# («Continued on p. 8 agonist tirzepatide…»). Узнаётся по форме, без слов
# языка: короткая строка с заглавной, без знака конца, оканчивающаяся
# сокращением со страницей («p. 8», «с. 8», «S. 8», «стр. 8»).
_PAGE_REF_RE = re.compile(r"(?:^|\s)\w{1,5}\.\s?\d{1,4}\s*$")
PAGE_NOTE_WORDS = 6


def _page_note(line: str, median_len: float = 0.0) -> bool:
    t = (line or "").strip()
    if not t or not (t[0].isupper() or t[0].isdigit()):
        return False
    if _END_RE.search(t) or t.endswith(("-", SOFT, "‐")):
        return False
    if len(t.split()) > PAGE_NOTE_WORDS:
        return False
    if median_len and len(t) >= HEADING_LEN_SHARE * median_len:
        return False
    return bool(_PAGE_REF_RE.search(t))


def _frame_candidate(t: str) -> bool:
    return (HEAD_MIN_LEN <= len(t) <= HEAD_MAX_LEN and not t.endswith(":")
            and not _NUM_LINE_RE.match(t))


def _geo_roles(recs: list, st: dict, g: dict, next_gid) -> list:
    """Роль каждой строки тела страницы: ("f", None) — поток текста,
    ("h", gid) — заголовок (строки одного заголовка — один gid),
    ("a", gid) — вставка: врезка, эпиграф, подпись эпиграфа, метка
    и подпись рисунка, сноска. Вставка — отдельный абзац, и абзац,
    который она разорвала, ждёт своего продолжения мимо неё."""
    n = len(recs)
    roles: list = [("f", None)] * n
    if not n:
        return roles
    bs, left, right, lead = st["body_s"], st["left"], st["right"], st["lead"]
    box = g.get("box") or [0, 0, 0, 0]
    pw, ph = max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1])
    few = st["n_body"] < 4

    # Заголовки: крупный кегль; соседние строки того же кегля — один заголовок.
    prev_h = None
    for i, r in enumerate(recs):
        if r["s"] >= GEO_HEADING * bs and len(r["t"]) <= 200:
            if (prev_h is not None and prev_h == i - 1
                    and abs(recs[prev_h]["s"] - r["s"]) <= 0.15 * r["s"]
                    and recs[prev_h]["y"] - r["y"] <= 2.2 * r["s"]):
                roles[i] = ("h", roles[prev_h][1])
            elif _starts_lower(r["t"]) and i > 0 and _open_end(recs[i - 1]["t"]):
                continue                # «дуру-» кеглем 13 — хвост абзаца, кегль распознан криво
            else:
                roles[i] = ("h", next_gid())
            prev_h = i

    def free(i):
        return roles[i][0] == "f"

    def short(t):
        return len(t) <= LABEL_MAX_LEN and len(t.split()) <= 3

    # Рисунки: метки вокруг — отдельными абзацами, подпись под рисунком
    # или над ним — тоже. Сам список — общим расчётом (`_fig_boxes`).
    figs = _fig_boxes(g, recs)
    m = 1.5 * bs
    for i, r in enumerate(recs):
        if not free(i):
            continue
        cx, cy = (r["x0"] + r["x1"]) / 2, r["y"] + 0.3 * r["s"]
        for f in figs:
            if short(r["t"]) and f[0] - m <= cx <= f[2] + m and f[1] - m <= cy <= f[3] + m:
                roles[i] = ("a", next_gid())
                break
    for f in figs:
        # Подпись — БЛИЖАЙШАЯ к рисунку строка снизу (или сверху), короткая
        # и отодвинутая от левого поля: «Рис. 7». Дальше — уже текст.
        for below in (True, False):
            best = None
            for i, r in enumerate(recs):
                if not (r["x0"] < f[2] and r["x1"] > f[0]):
                    continue
                gap = (f[1] - r["y"]) if below else (r["y"] - f[3])
                if 0 <= gap <= 3 * lead and (best is None or gap < best[0]):
                    best = (gap, i)
            if best is not None:
                i = best[1]
                t = recs[i]["t"]
                if free(i) and len(t) <= 40 and recs[i]["x0"] > left + 0.5 * bs:
                    roles[i] = ("a", next_gid())

    # Рамки: нарисованный прямоугольник, в который помещается строка текста,
    # не во всю страницу и не вокруг всего текста (рамка страницы).
    boxes = []
    for b in g.get("rects") or []:
        w, h = b[2] - b[0], b[3] - b[1]
        if w < 3 * bs or h < 1.5 * bs or w * h >= 0.8 * pw * ph:
            continue
        inside = sum(1 for r in recs if b[0] <= (r["x0"] + r["x1"]) / 2 <= b[2]
                     and b[1] <= r["y"] + 0.3 * r["s"] <= b[3])
        if inside and inside < 0.6 * n:
            boxes.append((w * h, b, next_gid()))
    boxes.sort(key=lambda x: x[0])
    for i, r in enumerate(recs):
        if roles[i][0] == "h":
            continue
        cx, cy = (r["x0"] + r["x1"]) / 2, r["y"] + 0.3 * r["s"]
        for _a, b, gid in boxes:
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                roles[i] = ("a", gid)
                break

    if not few and right > left:
        # Подпись эпиграфа, дата, город у правого края: короткая строка,
        # одна на своей высоте, начинается правее середины колонки — и
        # правее строки над ней, а строка под ней уже не справа. Строки
        # самого эпиграфа тоже короткие и справа, но идут стопкой.
        mid = left + 0.45 * (right - left)
        for i, r in enumerate(recs):
            if not free(i) or len(r["t"]) > 40 or len(r["t"].split()) > 5 or _NUM_LINE_RE.match(r["t"]):
                continue
            alone = not any(j != i and abs(recs[j]["y"] - r["y"]) < 0.5 * r["s"] for j in range(n))
            above = recs[i - 1] if i > 0 else None
            below = recs[i + 1] if i + 1 < n else None
            stacked_below = (below is not None and below["x0"] >= mid
                             and r["y"] - below["y"] <= 1.5 * lead)
            if (alone and r["x0"] >= mid and not stacked_below
                    and (above is None or above["x0"] < r["x0"] - 2 * bs)):
                roles[i] = ("a", next_gid())
        # Врезка, эпиграф, цитата: две и больше строк подряд с отступом слева,
        # и большинство их не доходит до правого поля (или набрано мельче
        # основного кегля). Первая строка абзаца отодвинута тоже, но она
        # доходит до правого поля — и она одна. Большинство, а не каждая:
        # конец строки с мягким переносом известен только оценкой.
        cand = [free(i) and r["x0"] >= left + GEO_INDENT * bs for i, r in enumerate(recs)]
        narrow = [r["x1"] <= right - GEO_INDENT * bs or r["s"] <= GEO_SMALL * bs for r in recs]
        i = 0
        while i < n:
            if not cand[i]:
                i += 1
                continue
            j = i
            while j < n and cand[j]:
                j += 1
            start, end_ = i, j
            # Первая строка абзаца сразу за врезкой (или перед ней) тоже
            # отодвинута и примыкает к серии, но доходит до правого поля
            # и отделена от врезки пробелом или стоит не по её левому краю:
            # её отрезаем, иначе абзац рвался бы посередине слова.
            lefts = Counter(round(recs[k]["x0"] / 2) for k in range(i, j))
            run_left = lefts.most_common(1)[0][0] * 2 if lefts else 0

            def stray(k, nb):
                gap = abs(recs[k]["y"] - recs[nb]["y"]) if 0 <= nb < n else 0
                return not narrow[k] and (gap > 1.4 * lead or abs(recs[k]["x0"] - run_left) > bs)
            while end_ - start >= 2 and stray(end_ - 1, end_ - 2):
                end_ -= 1
            while end_ - start >= 2 and stray(start, start + 1):
                start += 1
            # Абзац, начатый последней строкой серии и продолженный строчной
            # буквой за ней (или начатый до серии и продолженный её первой
            # строкой), — это текст, а не край врезки: иначе врезка унесла
            # бы половину слова («первую группу то-» / «чек, в третий…»).
            while (end_ - start >= 2 and end_ < n and free(end_)
                   and _open_end(recs[end_ - 1]["t"]) and _starts_lower(recs[end_]["t"])):
                end_ -= 1
            while (end_ - start >= 2 and start > 0 and free(start - 1)
                   and _open_end(recs[start - 1]["t"]) and _starts_lower(recs[start]["t"])):
                start += 1
            i, j = start, end_
            # Строки врезки кончаются у ОДНОГО правого края (своего поля),
            # а подряд идущие однострочные абзацы («ВК 28», «Расположена…»,
            # «Показания…:») — где придётся.
            ends = sorted(recs[k]["x1"] for k in range(i, j)
                          if narrow[k] and recs[k]["s"] > GEO_SMALL * bs)
            small = sum(1 for k in range(i, j) if recs[k]["s"] <= GEO_SMALL * bs)
            edge = any(b - a <= GEO_INDENT * bs for a, b in zip(ends, ends[1:]))
            if (j - i >= 2 and sum(narrow[i:j]) >= 0.6 * (j - i)
                    and (edge or small >= 0.6 * (j - i))):
                gid = next_gid()
                for k in range(i, j):
                    roles[k] = ("a", gid)
            i = j
        # Сноски: хвост страницы мельче основного кегля, ниже всего текста.
        last_body = max((i for i, r in enumerate(recs)
                         if free(i) and abs(r["s"] - bs) <= 0.1 * bs + 0.25), default=-1)
        tail = [i for i in range(last_body + 1, n) if free(i) and recs[i]["s"] <= 0.85 * bs]
        if tail and tail == list(range(last_body + 1, n)):
            gid = next_gid()
            for k in tail:
                roles[k] = ("a", gid)
    return roles


def _starts_lower(t: str) -> bool:
    return t[:1].islower()


def _open_end(t: str) -> bool:
    """Абзац на этой строке не кончился: перенос или нет знака конца."""
    t = t.rstrip()
    return bool(t) and (t.endswith(("-", SOFT)) or not _END_RE.search(t))


_WORD_BREAK_RE = re.compile(r"[^\W\d_](?:-|" + SOFT + r")$")


def _label_like(t: str) -> bool:
    return len(t) <= 12 or (len(t) <= LABEL_MAX_LEN and len(t.split()) <= 2)


def _joins_to_word(left_line: str, right_line: str, words, stems=()) -> bool:
    """Строка `right_line` — продолжение слова, перенесённого в конце
    `left_line`: половинки дают слово, которое документ знает целиком
    («одно-» / «го курса» — «одного»), либо вторая половина нигде в
    документе словом не стоит, кроме этого места, а начало склейки —
    основа знакомого слова («под-» / «вергается»: «подвергаться» в книге
    есть, «подвергается» — нет). `stems` — слова документа по алфавиту.
    Частое слово («под-» / «что…») и чужая основа («под-» / «места»)
    продолжением не считаются."""
    if not words:
        return False
    left = re.findall(r"[^\W\d_]+$", left_line.rstrip().rstrip("-" + SOFT))
    right = re.findall(r"^[^\W\d_]+", right_line)
    if not (left and right):
        return False
    joined = (left[0] + right[0]).lower()
    if words.get(joined, 0) >= 1:
        return True
    if len(right[0]) < 3 or words.get(right[0].lower(), 0) > 1:
        return False
    stem = joined[:len(left[0]) + 3]
    k = bisect.bisect_left(stems, stem)
    return k < len(stems) and stems[k].startswith(stem)


def _plain_page_fixes(entries: list, next_gid, hyphenated: set = frozenset(), words=None) -> None:
    """Вставки у границы страницы узнаются по переносу. Слово, разрезанное
    дефисом на конце страницы, продолжается строчной буквой; если между
    половинами стоит что-то, начатое с заглавной (врезка внизу страницы:
    «кон-» / «В продаже на рынках…» / «систенцию»; врезка вверху следующей:
    «под-» / «Важно не количество…» / «вергается»), или короткие метки
    в начале следующей (метки рисунка «НК4», «Рис. 7»), это вставка, а не
    продолжение. Только перенос по дефису: у открытого конца без дефиса
    строка с заглавной бывает и продолжением («по методу» / «Иванова»),
    и переставлять её было бы порчей.

    На странице С ГЕОМЕТРИЕЙ врезка обычно узнаётся по месту, и сюда
    доходят только строки, которые геометрия врезкой не признала (врезка
    без рамки с рваным правым краем, боевая стр. 303). Там тот же разбор
    идёт с подтверждением словарём (`words`): половинки через врезку
    должны дать слово, которое в документе есть."""
    pages: list = []                  # [(номер страницы, [индексы потока]), …]
    for k, e in enumerate(entries):
        if e["role"] == "page":
            pages.append((e["pg"], [], e["geo"]))
        elif pages and e["role"] == "f":
            pages[-1][1].append(k)
    stems = sorted(words) if words else []
    for (_p, cur, cur_geo), (_q, nxt, _ng) in zip(pages, pages[1:]):
        if not cur or not nxt:
            continue
        texts = [entries[k]["t"] for k in cur]
        cont = entries[nxt[0]]["t"]

        # Перенос СЛОВА: буква перед дефисом («кон-»), а не диапазон
        # («на 2-» / «3 см»), и за ним строка с заглавной БУКВЫ. Переносы
        # внутри самой врезки («покупате-» / «лю») продолжаются строчной
        # и точкой разрыва не считаются; составное слово документа
        # («Санкт-» / «Петербург») — тоже.
        def breaks_here(j):
            t, nx = texts[j].rstrip(), texts[j + 1]
            if not (_WORD_BREAK_RE.search(t) and nx[:1].isupper()):
                return False
            left = re.findall(r"[^\W\d_]+$", t.rstrip("-" + SOFT))
            right = re.findall(r"^[^\W\d_]+", nx)
            return not (left and right and (left[0] + "-" + right[0]).lower() in hyphenated)
        h = max((j for j in range(max(0, len(texts) - 12), len(texts) - 1) if breaks_here(j)),
                default=None)
        if (h is not None and _starts_lower(cont)
                and (not cur_geo or _joins_to_word(texts[h], cont, words, stems))):
            gid = next_gid()
            for j in range(h + 1, len(texts)):
                entries[cur[j]]["role"], entries[cur[j]]["gid"] = "a", gid
            texts = texts[:h + 1]
        if not (texts and _WORD_BREAK_RE.search(texts[-1].rstrip())):
            continue
        lead_ = [entries[k]["t"] for k in nxt[:7]]
        j = next((j for j, t in enumerate(lead_) if _starts_lower(t)), None)
        if not j:
            continue
        # Метки в начале следующей страницы перед продолжением слова.
        if all(_label_like(t) for t in lead_[:j]):
            for k in nxt[:j]:
                entries[k]["role"], entries[k]["gid"] = "a", next_gid()
            continue
        # Врезка вверху следующей страницы: начата заглавной, а за ней —
        # вторая половина слова. Строки врезки длинные и сами бывают начаты
        # строчной («места, куда…»), поэтому продолжение ищется словарём.
        # Строка перед продолжением должна быть закончена: если она сама
        # кончается переносом, строчная за ней — ЕЁ продолжение.
        if lead_[0][:1].isupper():
            j = next((j for j in range(1, len(lead_)) if _starts_lower(lead_[j])
                      and not lead_[j - 1].rstrip().endswith(("-", SOFT))
                      and _joins_to_word(texts[-1], lead_[j], words, stems)), None)
            if j:
                gid = next_gid()
                for k in nxt[:j]:
                    entries[k]["role"], entries[k]["gid"] = "a", gid


# Как далеко вниз (в кеглях) может стоять следующая строка того же абзаца:
# межстрочный — 1.1–1.6 кегля, двойной интервал — до 2.4, дальше — уже
# не продолжение (отбивку между абзацами решают текстовые правила).
CONT_DY = 3.0
# Зазор больше стольких «обычных межстрочных» перед строкой с заглавной —
# пропущенная строка, то есть новый абзац (`_geo_follows`).
GAP_BREAK = 1.6
# Строка, после которой абзац может перейти наверх СОСЕДНЕЙ колонки, —
# строка колонки текста (не короче стольких кеглей), а не подпись схемы.
COLUMN_LINE_MIN = 8.0


_URL_LINE_RE = re.compile(r"^(?:https?://|doi:|www\.)\S+$", re.IGNORECASE)
# Подзаголовок кончается там, где строка ВЫДЕЛЕННОГО начертания (полужирный,
# курсив) другого кегля сменяется обычным текстом. Проект 14: «Consensus
# Recommendations» (b, 5.95) и «Age: Older People With Diabetes» (bi, 5.25)
# над текстом кеглем 6.65 склеивались с первой строкой абзаца — заголовок
# печатался внутри фразы. Кегль обязателен: строка тела, начатая курсивным
# словом, того же кегля, и рвать её нельзя. Вводный заголовок в строке
# текста («Hypercortisolism.Hypercortisolism may …») — не конец: после
# точки в той же строке продолжается фраза.
HEAD_SIZE_DIFF = 0.05
HEAD_MAX_CHARS = 120         # строка заголовка не длиннее строки колонки


def _heading_ends(a: dict, b: dict) -> bool:
    ga, gb = a.get("geo"), b.get("geo")
    if not ga or not gb or len(ga) < 6 or len(gb) < 6:
        return False
    sa, sb = (ga[5] or ""), (gb[5] or "")
    if not sa or sb or not set(sa) & set("bi"):
        return False
    za, zb = ga[4] or 0.0, gb[4] or 0.0
    if not za or not zb or abs(za - zb) <= HEAD_SIZE_DIFF * max(za, zb):
        return False
    ta = (a.get("t") or "").strip()
    if not ta or len(ta) > HEAD_MAX_CHARS or ta.endswith(("-", SOFT, ",", "‐")):
        return False
    # «Age: Older People With Diabetes» — двоеточие ВНУТРИ заголовка; вводный
    # заголовок отличает точка, за которой в строке идёт текст
    # («Thiazolidinediones.Thiazolidinediones»). Следующая строка со строчной
    # буквы или скобки — продолжение фразы, а не новый абзац.
    if re.search(r"[.!?]\s*[^\W\d_]", ta):
        return False
    tb = (b.get("t") or "").lstrip()
    if tb[:1] and (tb[:1].islower() or tb[:1] in "([{"):
        return False
    return True


def _cell_of(r: dict, vr: list, hr: list):
    """Ячейка расчерченной таблицы, в которой стоит строка: (левая линия,
    правая, верхняя, нижняя) или None — строка не между двумя вертикалями."""
    s = max(r.get("s") or 1.0, 1.0)
    y, x0, x1 = r["y"], r["x0"], r["x1"]
    xs = [((v[0] + v[2]) / 2.0) for v in vr if v[1] - 0.5 * s <= y <= v[3] + 0.5 * s]
    left = max((x for x in xs if x <= x0 + 0.5), default=None)
    right = min((x for x in xs if x >= x1 - 0.5), default=None)
    if left is None or right is None:
        return None
    xm = (x0 + x1) / 2.0
    ys = [((h[1] + h[3]) / 2.0) for h in hr if h[0] - 0.5 <= xm <= h[2] + 0.5]
    top = min((v for v in ys if v > y), default=None)
    bot = max((v for v in ys if v < y), default=None)
    return (round(left, 1), round(right, 1), top and round(top, 1), bot and round(bot, 1))


def _cell_order(body: list, g) -> list:
    """Т34б. Строки расчерченной таблицы — по ЯЧЕЙКАМ: pypdf выдаёт шапку по
    высоте (верхние строки всех ячеек, потом нижние), и строки одной
    ячейки («Гено-» … «тип», «Контроль,» … «n, %») стояли в потоке не
    подряд — абзац их не собирал, и двухстрочная ячейка переводилась
    кусками. Внутри каждой подряд идущей пачки строк, стоящих в ячейках,
    строки одной ячейки собираются вместе (сверху вниз), ячейки — по месту
    (ряд сверху вниз, в ряду слева направо). Строки вне ячеек пачку обрывают и не двигаются."""
    vr = (g or {}).get("vrules") if isinstance(g, dict) else None
    if not vr or not body:
        return body
    hr = g.get("hrules") or []
    keys = [_cell_of(r, vr, hr) for r in body]
    out, k = [], 0
    while k < len(body):
        if keys[k] is None:
            out.append(body[k])
            k += 1
            continue
        j = k
        while j < len(body) and keys[j] is not None:
            j += 1
        order, groups = [], {}
        for t in range(k, j):
            if keys[t] not in groups:
                groups[keys[t]] = []
                order.append(keys[t])
            groups[keys[t]].append(body[t])
        # Ячейки — по месту: ряд (верхняя линия ячейки, без неё — верх её
        # строк) сверху вниз, в ряду — слева направо.
        order.sort(key=lambda kk: (-(kk[2] if kk[2] is not None else max(r["y"] for r in groups[kk])), kk[0]))
        for key in order:
            out.extend(sorted(groups[key], key=lambda r: -r["y"]))
        k = j
    return out


def _rule_parts(hrules, ax0, ay, ax1, asz, bx0, by, bx1, bsz) -> bool:
    """Т34. Горизонтальная линия листа проходит МЕЖДУ строкой a (выше) и
    строкой b (ниже) и накрывает по ширине обе — это граница ряда таблицы
    (или рамки), и абзац через неё не переходит. Подчёркивание (линия под
    самой строкой, ближе 0.3 кегля к базовой) границей не считается."""
    if not hrules or ay is None or by is None or ay <= by:
        return False
    asz, bsz = max(asz or 1.0, 1.0), max(bsz or 1.0, 1.0)
    lo, hi = by + 0.75 * bsz, ay - 0.3 * asz
    if hi <= lo:
        return False
    for r in hrules:
        ym = (r[1] + r[3]) / 2.0
        if lo < ym < hi and r[0] <= max(ax0, bx0) + 0.5 * asz and r[2] >= min(ax1, bx1) - 0.5 * asz:
            return True
    return False


# Ц9: красная строка после короткой строки — новый абзац. Отступ — от
# `INDENT_MIN` до `INDENT_MAX` кеглей, предыдущая строка короче следующей
# больше чем на `INDENT_SHORT` кеглей. `PDF_INDENT_BREAK=0` — выключить.
INDENT_BREAK = os.environ.get("PDF_INDENT_BREAK", "1") != "0"
INDENT_MIN = 0.8
INDENT_MAX = 4.0
INDENT_SHORT = 3.0


def _geo_follows(a: dict, b: dict) -> bool:
    """Строка b геометрически продолжает строку a (оба с местом `geo`):
    стоит ниже не дальше `CONT_DY` кеглей и пересекается по горизонтали,
    либо абзац ушёл наверх колонки правее (a — строка колонки текста),
    либо это другая страница (о ней геометрия не судит)."""
    ga, gb = a.get("geo"), b.get("geo")
    if not ga or not gb or ga[0] != gb[0]:
        return True
    if (a.get("tcol") or b.get("tcol")) and a.get("tcol") != b.get("tcol"):
        return False                    # другая колонка таблицы — другая ячейка
    if b.get("bul"):
        return False                    # значок пункта списка — новый абзац
    if _SUP_LEAD_RE.match(b.get("t") or ""):
        # Ц5: строка, начатая надстрочным номером («² Научно-исследовательский
        # институт…» — аффилиация, сноска), — новый абзац.
        return False
    _p, ax0, ay, ax1, asz = ga[:5]
    _p, bx0, by, bx1, bsz = gb[:5]
    if _rule_parts(a.get("hr") or b.get("hr"), ax0, ay, ax1, asz, bx0, by, bx1, bsz):
        return False                    # Т34: между строками линия ряда таблицы
    size = max(asz or 0.0, bsz or 0.0, 1.0)
    dy = ay - by
    if _heading_ends(a, b):
        return False
    if _URL_LINE_RE.match((a.get("t") or "").strip()) and by > ay + 1.0 * size:
        # Строка-адрес («https://doi.org/…» под заголовком статьи) колонкой
        # не продолжается: иначе в неё вклеивалась колонка авторов справа,
        # и имя первого автора печаталось после DOI (проект 14, стр. 1).
        return False
    overlap = min(ax1, bx1) - max(ax0, bx0)
    if 0 < dy <= CONT_DY * size and overlap > -0.5 * size:
        # Пропуск строки перед строкой с заглавной — новый пункт, а не
        # продолжение: в инфографике между пунктами списка стоит строка,
        # набранная кривыми (в текстовом слое её нет), и два пункта
        # склеивались в один абзац, а перевод второго вставал в место первого.
        # Мерка — обычный межстрочный ЭТОГО кегля на странице (`_size_leads`):
        # у подписей инфографики он свой, у текста с двойным интервалом —
        # свой, и разрыва по одной заглавной там не будет.
        plead = b.get("plead") or a.get("plead") or 0.0
        base = plead if plead > 0 else 1.3 * size
        tb = (b.get("t") or "").lstrip()
        ta = (a.get("t") or "").rstrip()
        if (dy > GAP_BREAK * base and tb[:1] and (tb[:1].isupper() or tb[:1].isdigit()
                                                  or tb[:1] in "•▪●◦–—-")
                and not ta.endswith(("-", SOFT, ",", "‐"))):
            return False
        if (INDENT_BREAK and dy > 0.5 * size and INDENT_MIN * size <= bx0 - ax0 <= INDENT_MAX * size
                and ax1 < bx1 - INDENT_SHORT * size and tb[:1] and (tb[:1].isupper() or tb[:1].isdigit())
                and _ADDR_END_RE.search(ta)):
            # Ц9: короткая строка, а следующая — с КРАСНОЙ СТРОКИ (отступ
            # от левого края предыдущей) и во всю ширину: новый абзац, даже
            # если строка кончилась без точки (ORCID, адрес почты: «…https://
            # orcid.org/0000-0002-2962-1076» и «Федорова Ольга Сергеевна –»
            # склеивались в один абзац «Информации об авторах»).
            return False
        return True
    if abs(dy) <= 0.3 * size and -0.5 * size <= bx0 - ax1 <= 2.0 * size:
        return True                     # продолжение той же строки (разорванной)
    wa = ax1 - ax0
    # Наверх соседней колонки — ЗАМЕТНО выше (на строку и больше): две
    # надписи одной высоты («IMPROVING DETECTION…» и «MEDICAL NUTRITION
    # THERAPY» с разных концов схемы) колонкой друг другу не служат.
    if by > ay + 1.0 * size and wa >= COLUMN_LINE_MIN * size and (
            bx0 >= ax0 + 0.5 * wa or bx1 <= ax1 - 0.5 * wa):
        # Переход наверх следующей колонки — правее, а у письма справа
        # налево (и у вёрстки с колонками в обратном порядке) — левее.
        return True
    return False


# Подпись плашки КАПСОМ из двух строк, разорванная в потоке строками
# соседних плашек («HEALTHY LIFESTYLE» … «BEHAVIORS», «DIABETES SELF-» …
# «MANAGEMENT EDUCATION», стр. 19): строки одной оси, одного кегля и
# начертания, вплотную друг под другом, между ними на листе ничего нет.
# Переведённые порознь, они давали «ЗДОРОВЫЙ ОБРАЗ ЖИЗНИ ПОВЕДЕНИЕ»
# и висячий дефис «ДИАБЕТА-».
LABEL_JOIN_DY = 1.6          # шаг строк, в кеглях
LABEL_JOIN_AXIS = 0.6        # центр или левый край расходятся не больше, в кеглях
LABEL_JOIN_LOOK = 6          # на сколько абзацев вперёд искать продолжение
LABEL_JOIN_MAX_LINES = 2     # у каждой части строк не больше
LABEL_JOIN_MIN_LETTERS = 6   # у каждой части букв не меньше
# `PDF_LABEL_JOIN=0` — без склейки (откат без выката; RULES_VERSION то же).
LABEL_JOIN = os.environ.get("PDF_LABEL_JOIN", "1") != "0"


def _label_geo(group: "list | None") -> "list | None":
    if not group:
        return None
    gs = [e.get("geo") for e in group if e]
    if not gs or any(not g or len(g) < 6 for g in gs):
        return None
    if len({g[0] for g in gs}) != 1 or len(gs) > LABEL_JOIN_MAX_LINES:
        return None
    return gs


def _caps_label(text: str) -> bool:
    """Часть подписи плашки: капсом и не короче `LABEL_JOIN_MIN_LETTERS`
    букв — столбец сокращений таблицы («ВИЧ» / «СПИД») не склеивается."""
    # Строчная «s» множественного числа после прописной — всё ещё капс
    # (Т8): «DEVELOP MLTCs», «RCTs», «RAs». Без этого подпись плашки
    # «PEOPLE WITH T2D OFTEN LIVE WITH OR | DEVELOP MLTCs» рвалась на два
    # сегмента, и перевод кусками выходил бессмыслицей (стр. 4).
    text = re.sub(r"(?<=[A-Z])s(?![A-Za-z])", "", text)
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= LABEL_JOIN_MIN_LETTERS and all(ch.isupper() for ch in letters)


def _merge_label_lines(paras: list, groups: list, all_entries: list, words, report) -> tuple:
    if not LABEL_JOIN:
        return paras, groups
    paras, groups = list(paras), list(groups)
    i = 0
    while i < len(paras):
        ga = _label_geo(groups[i])
        if ga is None or not paras[i] or not _caps_label(paras[i]) or (
                paras[i].rstrip()[-1:] in ".!?:;"):
            i += 1
            continue
        la = min(ga, key=lambda g: g[2])                      # нижняя строка A
        size = max(la[4] or 0.0, 1.0)
        hit = None
        for j in range(i + 1, min(len(paras), i + 1 + LABEL_JOIN_LOOK)):
            gb = _label_geo(groups[j])
            if gb is None or not paras[j] or not _caps_label(paras[j]):
                continue
            fb = max(gb, key=lambda g: g[2])                  # верхняя строка B
            if fb[0] != la[0] or (fb[5] or "") != (la[5] or ""):
                continue
            if abs((fb[4] or 0) - (la[4] or 0)) > 0.05 * size:
                continue
            dy = la[2] - fb[2]
            if not (0 < dy <= LABEL_JOIN_DY * size):
                continue
            ca, cb = (la[1] + la[3]) / 2.0, (fb[1] + fb[3]) / 2.0
            if not (abs(ca - cb) <= LABEL_JOIN_AXIS * size or abs(la[1] - fb[1]) <= LABEL_JOIN_AXIS * size):
                continue
            ov = min(la[3], fb[3]) - max(la[1], fb[1])
            if ov < 0.5 * min(la[3] - la[1], fb[3] - fb[1]):
                continue
            x0, x1 = min(la[1], fb[1]), max(la[3], fb[3])
            mine = {id(e) for e in groups[i] + groups[j] if e}
            between = any(
                e.get("geo") and id(e) not in mine and e["geo"][0] == la[0]
                and fb[2] - 0.2 * size < e["geo"][2] < la[2] + 0.2 * size
                and min(x1, e["geo"][3]) - max(x0, e["geo"][1]) > 0
                for e in all_entries)
            if between:
                continue
            hit = j
            break
        if hit is None:
            i += 1
            continue
        a, b = paras[i].rstrip(), paras[hit].lstrip()
        if a.endswith(("-", SOFT, "‐")) and b[:1].isalpha():
            # Перенос слова снимается, составное слово («SELF-MANAGEMENT»)
            # сохраняет свой дефис; пробела на стыке нет в обоих случаях.
            joined = (a.rstrip("-" + SOFT + "‐") if _joins_to_word(a, b, words) else a) + b
        else:
            joined = a + " " + b
        paras[i] = joined
        groups[i] = groups[i] + groups[hit]
        del paras[hit], groups[hit]
        report["labelJoined"] += 1
    return paras, groups


def _assemble(entries: list, median_len: float, src: list = None) -> list:
    """Поток строк с разметкой ролей → строки для `join_lines`: вставки
    и заголовки — отдельными абзацами (пустая строка вокруг), а вставка,
    разорвавшая абзац (строка перед ней открыта, а поток после неё
    продолжается строчной буквой), встаёт ПОСЛЕ конца этого абзаца.

    `src` — если передать список, в него ляжет запись-источник каждой
    выданной строки (None у пустых разделителей). Нужно выгрузке
    «как в оригинале»: по ней абзац находит своё место на странице."""
    out: list = []
    pending: list = []
    waited = [0]

    def put(text, entry):
        out.append(text)
        if src is not None:
            src.append(entry)

    def emit(block):
        put("", None)
        prev = None
        for e in block:
            if prev is not None and _apart(prev, e):
                # Две строки вставки или заголовка, которые по горизонтали
                # не пересекаются и стоят не на одной линии, — разные надписи
                # («PROGRAMS THAT ADDRESS:» и «24-H PHYSICAL» с разных концов
                # схемы, стр. 4): блоком одной роли их склеивал поток.
                put("", None)
            put(e["t"], e)
            prev = e
        put("", None)

    def release():
        for b in pending:
            emit(b)
        pending.clear()
        waited[0] = 0

    def para_ends(prev: str, nxt: str) -> bool:
        if not prev:
            return True
        if prev.rstrip().endswith(("-", SOFT)):
            return False
        if _END_RE.search(prev):
            return True
        return bool(median_len and len(prev) < HEADING_LEN_SHARE * median_len
                    and nxt[:1] and (nxt[:1].isupper() or nxt[:1].isdigit()))

    n = len(entries)
    i = 0
    last_f = [None]
    last_tail = [None]                 # Ц6: последняя строка текста (с местом или без)
    sizes_ = [e["geo"][4] for e in entries if e.get("role") == "f" and e.get("geo") and e["geo"][4]]
    body_s = statistics.median(sizes_) if sizes_ else 0.0
    boundary = [False]                 # только что прошли границу страницы
    while i < n:
        e = entries[i]
        role = e["role"]
        if role == "page":
            boundary[0] = True
            i += 1
            continue
        if (role == "f" and boundary[0] and out and out[-1] and not pending
                and _page_note(out[-1], median_len)):
            put("", None)              # Т15: записка «Continued on p. N» абзац не продолжает
        if (role == "f" and boundary[0] and out and out[-1] and not pending
                and _page_size_break(last_tail[0], e, body_s)):
            # Ц6: абзац через границу страницы продолжается только ТЕМ ЖЕ
            # кеглем: сноска внизу листа («✉ Мелентьева…, …@gmail.com», 8 пт)
            # не продолжается в «Для цитирования» (9 пт) следующей страницы.
            put("", None)
        if role == "f":
            boundary[0] = False
            # Пока вставка ждёт конца абзаца (`pending`), абзац продолжается
            # ЗА ней — геометрией его не рвём: строка после вставки и не
            # обязана стоять под строкой перед ней.
            if (out and out[-1] and not pending and last_f[0] is not None
                    and not _geo_follows(last_f[0], e)):
                # Строка стоит НЕ там, где продолжилась бы предыдущая (под
                # ней на межстрочный, либо наверху соседней колонки): это
                # другая надпись, хоть поток pypdf и ставит её следом.
                # У схемы так склеивались подписи с разных концов листа.
                put("", None)
            if pending and (para_ends(out[-1] if out else "", e["t"]) or waited[0] >= DEFER_MAX_LINES):
                release()
            put(e["t"], e)
            prev_f = last_f[0]
            last_f[0] = e if e.get("geo") else None
            if prev_f is not None and last_f[0] is not None and _same_baseline(prev_f, e):
                # Ц9в: часть строки (курсивное название статьи и прямой хвост
                # «. Bulletin of Siberian Medicine…») судит о продолжении
                # по ВСЕЙ строке: следующая строка начата у её левого края,
                # а не под второй частью («org/10.20538/…» после «https://doi.»).
                g0, g1 = prev_f["geo"], e["geo"]
                last_f[0] = dict(e, geo=(g1[0], min(g0[1], g1[1]), g1[2], max(g0[3], g1[3])) + tuple(g1[4:]))
            last_tail[0] = e
            if pending:
                waited[0] += 1
            i += 1
            continue
        j = i
        while j < n and entries[j]["role"] == role and entries[j]["gid"] == e["gid"]:
            j += 1
        block = entries[i:j]
        if role != "f":
            last_f[0] = None            # заголовок/вставка: судить не по чему
        if role == "a":
            k = j
            while k < n and entries[k]["role"] in ("a", "page"):
                k += 1
            cont = k < n and entries[k]["role"] == "f" and _starts_lower(entries[k]["t"])
            if (out and out[-1] and _open_end(out[-1]) and cont
                    and not _page_note(out[-1], median_len)):
                pending.append(block)      # (Т15: записка «Continued on p. N» абзац не держит открытым)
            else:
                emit(block)
        else:                                      # заголовок: абзац до него кончился
            release()
            emit(block)
        i = j
    release()
    return out


def _same_baseline(a: dict, b: dict) -> bool:
    ga, gb = a.get("geo"), b.get("geo")
    if not ga or not gb or ga[0] != gb[0]:
        return False
    size = max(ga[4] or 0.0, gb[4] or 0.0, 1.0)
    return abs(ga[2] - gb[2]) <= 0.3 * size and -0.5 * size <= gb[1] - ga[3] <= 2.0 * size


PAGE_SIZE_BREAK = float(os.environ.get("PDF_PAGE_SIZE_BREAK", "0.08"))  # 0 — выключить
_ADDR_END_RE = re.compile(r"(?:[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|www\.\S+)[.)]?\s*$")


def _page_size_break(a: "dict | None", b: dict, body: float = 0.0) -> bool:
    """Ц6: абзац НЕ продолжается через границу страницы, если последняя
    строка страницы — сноска: кончается адресом почты или ссылкой
    («✉ Мелентьева …, …@gmail.com»), либо набрана мельче основного текста
    документа (`body`) и мельче первой строки следующей страницы больше
    чем на `PAGE_SIZE_BREAK`."""
    if PAGE_SIZE_BREAK <= 0 or not a:
        return False
    ga, gb = a.get("geo"), (b or {}).get("geo")
    if not ga or not gb or body <= 0:
        return False
    sa, sb = float(ga[4] or 0), float(gb[4] or 0)
    if _ADDR_END_RE.search(a.get("t") or "") and 0 < sa < (1 - PAGE_SIZE_BREAK) * body:
        return True                     # мелкая строка с адресом — сноска
    return (sa > 0 and sb > 0 and sa < (1 - PAGE_SIZE_BREAK) * sb
            and sa < (1 - PAGE_SIZE_BREAK) * body and abs(sb - body) <= PAGE_SIZE_BREAK * body)


def _apart(a: dict, b: dict) -> bool:
    ga, gb = a.get("geo"), b.get("geo")
    if not ga or not gb or ga[0] != gb[0]:
        return False
    size = max(ga[4] or 0.0, gb[4] or 0.0, 1.0)
    if abs(ga[2] - gb[2]) <= 0.3 * size:
        return False                     # та же строка, разорванная
    return min(ga[3], gb[3]) - max(ga[1], gb[1]) < -0.5 * size


_PARAGRAPH_NO_RE = re.compile(r"^§+\s*\d{1,4}[.)]?$")


def _big_short_kept(t: str, words: Counter) -> bool:
    """Крупная короткая строка — заголовок, а не украшение: номер (арабский
    или римский: «IV», «I»), параграф («§ 5») либо слово, которое документ
    знает и помимо этой строки («Яд», «Мёд»). «ЧР’», «ш», «!Ч 1» — ни то,
    ни другое: это распознанный узор."""
    t = t.strip()
    if _NUM_LINE_RE.match(t) or _PARAGRAPH_NO_RE.match(t):
        return True
    w = t.strip(".,:;!?«»\"'()")
    return len(w) >= 2 and w.isalpha() and words.get(w.lower(), 0) >= 2


def _dropcap_join(d: dict, recs: list, words: Counter) -> bool:
    """Буквица, сохранившаяся в слое: ОДНА заглавная буква слева от строк,
    которые она начинает, встаёт в начало первой из них, если та начата
    строчной. Слитно или через пробел — решает словарь документа, как
    у `restore_dropcaps`: «О» + «стрый» — «Острый» (обрубок редок, слово
    есть), а «В» + «начале» — «В начале» (обрубок — частое слово, слитного
    «вначале» столько нет, а «в» — слово). True — буква пристроена."""
    t = d["t"].strip()
    if not (len(t) == 1 and t.isalpha() and t.isupper()):
        return False
    right_of = [r for r in recs if r is not d and r["x0"] >= d["x0"]
                and d["y"] - 0.2 * d["s"] <= r["y"] <= d["y"] + 1.2 * d["s"]]
    if not right_of:
        return False
    first = max(right_of, key=lambda r: r["y"])
    if not _starts_lower(first["t"]):
        return False
    m = re.match(r"[^\W\d_]+", first["t"])
    stub = m.group(0).lower() if m else ""
    n_stub, n_join = words.get(stub, 0), words.get(t.lower() + stub, 0)
    if stub and not (n_join and n_join >= n_stub) and n_stub > 2 and words.get(t.lower(), 0):
        first["t"] = t + " " + first["t"]
    else:
        first["t"] = t + first["t"]
    return True


def _edge_scrap(t: str, words: Counter) -> bool:
    """Обрывок у края страницы: строка в один-два знака без цифр, не слово
    документа. Это распознанный кусок рисунка или виньетки («Ш» под номером
    страницы на боевой стр. 67, «Ш» под колонтитулом на стр. 79): оставленный,
    он вставал посреди абзаца, разорванного страницей («быстро Ш
    затвердевает»), а номер страницы за ним переставал быть крайним и
    вклеивался в текст («по- 68 лис»). Спрашивается только у края — среди
    колонтитула, номера и первой/последней строки."""
    t = t.strip()
    if not t or len(t) > 2 or any(c.isdigit() for c in t):
        return False
    if len(t) == 1:
        return True
    w = t.strip(".,:;!?«»\"'()").lower()
    return not (len(w) == 2 and w.isalpha() and words.get(w, 0) >= 3)


# Метка врезки («На заметку») повторяется по книге, и распознаватель
# обкладывает её обрывками значка: «* Usj На заметку», «На заметку $ ууфф»,
# «jl|? На заметку». ЯДРО короткой строки — она сама без мусорных токенов
# по краям; ядро, встреченное не меньше чем на LABEL_CORE_MIN строках, —
# метка, и строка заменяется ядром.
LABEL_CORE_MIN = 3
LABEL_MAX_TOKENS = 6


def _junk_token(tok: str, words: Counter) -> bool:
    """Мусорный токен края метки: одиночный знак, знаки узора внутри
    («jl|?»), короткое «слово», которого документ почти не знает («Usj»,
    «ууфф»). Числа мусором не считаются никогда."""
    if len(tok) == 1:
        return True
    if any(c.isdigit() for c in tok):
        return False
    core = tok.strip(".,:;!?«»\"'()")
    if not core:
        return any(c in _ORNAMENT_CHARS for c in tok)     # «(!).» — знаки текста, не мусор
    if any(c in _ORNAMENT_CHARS for c in core):
        return True
    if not core.isalpha():
        return False
    return len(core) <= 4 and words.get(core.lower(), 0) <= 2


def _label_core(t: str, words: Counter) -> str:
    toks = t.split()
    if not toks or len(toks) > LABEL_MAX_TOKENS or len(t) > 48:
        return t
    a, b = 0, len(toks)
    while a < b and _junk_token(toks[a], words):
        a += 1
    while b > a and _junk_token(toks[b - 1], words):
        b -= 1
    core = " ".join(toks[a:b])
    return core if len(_letters(core)) >= 4 else t


def _label_shape(core: str) -> bool:
    """Метка — фраза из двух-шести слов с заглавной, без цифр: «На заметку»,
    «Лекарство из улья». Одно слово («меда.», «печени.») меткой не бывает —
    это конец строки текста, и срезать перед ним «шего» или «и» значило бы
    испортить фразу («хорошего меда» → «хоромеда»)."""
    toks = core.split()
    return (2 <= len(toks) <= LABEL_MAX_TOKENS and core[:1].isupper()
            and not any(c.isdigit() for c in core))


def _fix_labels(laid: dict, words: Counter, report: Counter) -> None:
    """Метки врезок — без мусора по краям и без двойника рядом
    (значок и подпись распознаны дважды: «* Usj На заметку» и «На заметку $»
    на одной высоте боевой стр. 9 давали два абзаца). Меткой считается
    фраза, которая сама по себе, без мусора, стоит отдельной строкой
    не меньше чем LABEL_CORE_MIN раз."""
    alone: Counter = Counter()
    for pg in laid.values():
        for r in pg["recs"]:
            if _label_shape(r["t"]):
                alone[r["t"]] += 1
    labels = {c for c, n in alone.items() if n >= LABEL_CORE_MIN}
    if not labels:
        return
    for pg in laid.values():
        recs = pg["recs"]
        for r in recs:
            c = _label_core(r["t"], words)
            if c != r["t"] and c in labels:
                r["t"] = c
                report["labelJunk"] += 1
        out = []
        for r in recs:
            s = max(r["s"], 1.0)
            if r["t"] in labels and any(
                    o["t"] == r["t"] and abs(o["y"] - r["y"]) < 0.5 * s
                    and o["x0"] <= r["x1"] + 2 * s and r["x0"] <= o["x1"] + 2 * s for o in out):
                report["labelJunk"] += 1
                continue
            out.append(r)
        if len(out) != len(recs):
            pg["recs"] = out
            pg["st"] = _page_stats(out)
            pg["top"], pg["bottom"] = _bands(out, pg["st"])


def _rel_style(style: str, base: str) -> str:
    """Начертание строки против основного: выделением считается только то,
    чего в основном нет. Светлее основного текста не бывает — «обычное»."""
    return ("b" if "b" in style and "b" not in base else "") +            ("i" if "i" in style and "i" not in base else "") +            ("c" if "c" in style else "")


def _base_style(laid: dict) -> str:
    """Начертание, которым набран САМ документ.

    Считать полужирным всё, что распознаватель назвал Bold, нельзя: у боевой
    книги (старая печать, жирная краска) распознаватель пометил `Bold` весь
    основной текст — 11 710 строк из 13 347, — и выгрузка напечатала бы книгу
    целиком полужирной. Начертание имеет смысл только ОТНОСИТЕЛЬНО основного:
    выделено то, что от него отличается."""
    tally = Counter()
    for pg in laid.values():
        for r in pg.get("recs") or []:
            tally[r.get("st") or ""] += max(1, len((r.get("t") or "").strip()))
    return tally.most_common(1)[0][0] if tally else ""


def _base_family(laid: dict) -> str:
    """Гарнитура, которой набран сам документ: ею печатается абзац, у строк
    которого гарнитура не узнана (символьный шрифт, имя без гарнитуры)."""
    tally = Counter()
    for pg in laid.values():
        for r in pg.get("recs") or []:
            if r.get("fam"):
                tally[r["fam"]] += max(1, len((r.get("t") or "").strip()))
    return tally.most_common(1)[0][0] if tally else ""


def _para_boxes(entries: list, base: str = "", base_fam: str = "") -> "list | None":
    """Рамки абзаца на страницах: [{page, x0, y0, x1, y1, size, lead, indent}].

    Абзац бывает разорван концом страницы, поэтому рамок несколько — по одной
    на страницу. `size` — кегль (медиана строк), `lead` — межстрочный интервал
    этого абзаца, `indent` — отступ первой строки от левого края рамки.
    None — у абзаца нет геометрии (страница разбиралась по строкам): выгрузка
    «как в оригинале» такой абзац не трогает, а не гадает его место."""
    by_page: dict = {}
    # Маркер пункта, снятый чисткой с первой строки (`bulch`), — на рамку
    # её страницы: выгрузка печатает его перед переводом (`layout_pdf`).
    first = next((e for e in entries if (e or {}).get("geo") or (e or {}).get("rgeo")), None)
    bullet = (first or {}).get("bulch") if (first or {}).get("geo") else None
    bullet_pg = first["geo"][0] if bullet else None
    for e in entries:
        rg_ = (e or {}).get("rgeo")
        if rg_ and not (e or {}).get("geo"):
            # Повёрнутая строка: рамка — по её пути, место — с путём (поле 8),
            # печать ставит перевод повёрнутым или вдоль дуги.
            pg, rgeo = rg_
            pts = rgeo.get("pts") or []
            if not pts:
                continue
            xs = [p_[0] for p_ in pts] + [rgeo["end"][0]]
            ys = [p_[1] for p_ in pts] + [rgeo["end"][1]]
            sz = statistics.median([p_[3] for p_ in pts]) or 1.0
            b = by_page.setdefault(pg, {"page": pg, "x0": min(xs), "y0": min(ys), "x1": max(xs),
                                        "y1": max(ys), "sizes": [], "ys": [], "first": min(xs),
                                        "st": Counter(), "fam": Counter()})
            n_ = max(1, len((e.get("t") or "").strip()))
            b["st"][rgeo.get("st") or ""] += n_
            if rgeo.get("fam"):
                b["fam"][rgeo["fam"]] += n_
            b["x0"], b["x1"] = min(b["x0"], min(xs)), max(b["x1"], max(xs))
            b["y0"], b["y1"] = min(b["y0"], min(ys)), max(b["y1"], max(ys))
            b["sizes"].append(sz)
            b.setdefault("slots", []).append([round(min(xs), 1), round(pts[0][1], 1),
                                              round(max(xs), 1), round(sz, 2),
                                              _rel_style(rgeo.get("st") or "", base), None,
                                              n_, 0, rgeo])
            continue
        g = (e or {}).get("geo")
        if not g or len(g) < 6:
            continue
        pg, x0, y, x1, sz, st = g[:6]
        fam = g[6] if len(g) > 6 else ""
        xl = g[7] if len(g) > 7 else None
        parts = g[8] if len(g) > 8 else None
        exact = 1 if (len(g) > 9 and g[9]) else 0
        color = g[10] if len(g) > 10 else None
        gaps = g[11] if len(g) > 11 else None
        b = by_page.setdefault(pg, {"page": pg, "x0": x0, "y0": y, "x1": x1, "y1": y,
                                    "sizes": [], "ys": [], "first": x0, "st": Counter(),
                                    "fam": Counter()})
        b["st"][st or ""] += max(1, len((e.get("t") or "").strip()))
        if fam:
            b["fam"][fam] += max(1, len((e.get("t") or "").strip()))
        b["x0"], b["x1"] = min(b["x0"], x0), max(b["x1"], x1)
        b["y0"], b["y1"] = min(b["y0"], y), max(b["y1"], y)
        b["sizes"].append(sz or 0.0)
        b["ys"].append(y)
        # Место САМОЙ строки: [x0, базовая, x1, кегль, начертание]. Рамка
        # вокруг всех строк абзаца — прямоугольник, и у подписей схемы,
        # разнесённых по рисунку, он накрывал сам рисунок: выгрузка
        # закрашивала инфографику целиком. Строки — ровно та площадь,
        # где стоял текст; по ним закрашивается и печатается перевод.
        rel = _rel_style(st or "", base)
        # Последнее поле места — сколько знаков ОРИГИНАЛА в нём стояло:
        # по нему перевод раздаётся подписям схемы (`layout_pdf._spread`).
        if parts:
            for part in parts:
                px0, py, psz, px1, pxl = part[:5]
                b.setdefault("slots", []).append([px0, py, max(px1, px0), psz, rel, pxl,
                                                  part[5] if len(part) > 5 else 0, 0, None, color,
                                                  None])
        else:
            b.setdefault("slots", []).append([round(x0, 1), round(y, 1), round(max(x1, x0), 1),
                                              round(sz or 0.0, 2), rel,
                                              round(xl, 1) if xl is not None else None,
                                              len((e.get("t") or "").strip()), exact,
                                              # 8 — путь повёрнутой строки, 9 — цвет краски,
                                              # 10 — разрывы строки (сверка надписей со слоем)
                                              None, color, gaps])
    if not by_page:
        return None
    out = []
    for pg in sorted(by_page, reverse=False):
        b = by_page[pg]
        sizes = [v for v in b["sizes"] if v > 0]
        size = statistics.median(sizes) if sizes else 10.0
        ys = sorted(set(b["ys"]), reverse=True)
        gaps = [ys[k] - ys[k + 1] for k in range(len(ys) - 1)]
        lead = statistics.median(gaps) if gaps else size * 1.2
        # Рамка по БАЗОВЫМ линиям; вниз добавляем выносные элементы,
        # вверх — высоту прописной: иначе верх строки оказался бы срезан.
        out.append({"page": pg, "x0": round(b["x0"], 1), "x1": round(b["x1"], 1),
                    "top": round(b["y1"] + 0.85 * size, 1),
                    "bottom": round(b["y0"] - 0.25 * size, 1),
                    "size": round(size, 2), "lead": round(lead, 2),
                    "style": _rel_style(b["st"].most_common(1)[0][0] if b["st"] else "", base),
                    "fam": (b["fam"].most_common(1)[0][0] if b["fam"] else base_fam) or "",
                    "indent": round(b["first"] - b["x0"], 1), "lines": len(b["ys"]),
                    "slots": b.get("slots") or []})
        if bullet and pg == bullet_pg:
            out[-1]["bullet"] = bullet
    return out


def _head_hit(hits: list, band: str, clusters: dict, text: str, rec: dict, page: int) -> None:
    """Снятая строка колонтитула — в копилку, с местом и ключом.

    Ключ — представитель КЛАСТЕРА, а не сама строка: распознаватель читает
    колонтитул заново на каждой странице и врёт по-разному
    («Апитоксинотерапия —», «Лпитоксииотератш —»), и по букве они были бы
    двумя сотнями разных надписей. Полоса (верх/низ) входит в ключ: одна
    и та же надпись сверху и снизу — два разных места на листе."""
    c = clusters["exact"].get(text) if clusters else None
    hits.append(((band, c["rep"] if c else text), text,
                 (page, rec["x0"], rec["y"], rec["x1"], rec["s"], rec.get("st") or "",
                  rec.get("fam") or "", rec.get("xl"))))


def _head_paragraphs(hits: list, base: str = "", base_fam: str = "") -> list:
    """Колонтитулы книги — [(текст, рамки)], по одной записи на РАЗНУЮ надпись.

    ЗАЧЕМ. Бегущий заголовок снимается со страницы правилами полосы и в текст
    не попадает — значит сегментом не становится, значит не переводится,
    значит на готовой книге остаётся русская строка НА КАЖДОЙ странице.
    В выгрузке .docx его и не было (мы собираем документ заново), а в PDF
    «как в оригинале» страница остаётся своя — и колонтитул вместе с ней.

    ОДНА надпись на всю книгу, а не по одной на страницу: это одно решение
    переводчика, и спрашивать его двести раз значит не спрашивать вовсе.
    Поэтому рамки помечены `repeat` — выгрузка печатает В КАЖДУЮ один и тот
    же текст, а не раскладывает абзац по страницам.

    Что НЕ становится абзацем: номера страниц (переводить нечего), мусор
    распознавания и надпись, встреченная реже `HEAD_MIN_PAGES` страниц, —
    со страницы она снимается, как и снималась, просто не переводится.
    Иначе в книгу поехали бы обрывки, за которые человеку платить."""
    groups: dict = {}
    for key, text, geo in hits:
        g = groups.setdefault(key, {"texts": Counter(), "geo": {}, "own": {}})
        g["texts"][text] += 1
        # По одной рамке на страницу: тот же колонтитул сверху и снизу одной
        # страницы слился бы в рамку во весь лист, и закраска съела бы текст.
        g["geo"].setdefault(geo[0], geo)
        g["own"].setdefault(geo[0], text)
    out = []
    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]))):
        g = groups[key]
        if len(g["geo"]) < HEAD_MIN_PAGES:
            continue
        text = g["texts"].most_common(1)[0][0]
        if not _frame_candidate(text):
            continue
        # Т15: у повёрнутого колонтитула место — путь строки (`rgeo`), а не
        # прямая рамка: перевод встаёт по тому же пути, вдоль правого края.
        boxes = _para_boxes([({"rgeo": (x[0], x[2]), "t": text} if len(x) == 3 and x[1] == "ROT"
                              else {"geo": x, "t": text}) for x in g["geo"].values()],
                            base, base_fam)
        if not boxes:
            continue
        rep_num = _head_number(text)
        for b in boxes:
            b["repeat"] = 1
            # Номер страницы в колонтитуле («4 Consensus Report», «Davies and
            # Associates 5») у каждой страницы СВОЙ, а перевод надписи один:
            # выгрузка подставит в него номер своей страницы (`num`).
            own = _head_number(g["own"].get(b["page"], ""))
            if rep_num and own and own != rep_num:
                b["num"] = [rep_num, own]
        out.append((text, boxes))
    return out


_HEAD_NUM_RE = re.compile(r"^\s*(\d{1,4})\s+\S|\S\s+(\d{1,4})\s*$")


def _head_number(text: str) -> str:
    """Номер страницы в начале или конце колонтитула — или пусто."""
    m = _HEAD_NUM_RE.search(text or "")
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def clean(pages: list, geom: "list | None" = None) -> dict:
    """Страницы (список списков строк) → {items, report}.

    items — [("p", текст)], [("img", номер страницы)] и [("fig", номер
    страницы, рамка в долях листа)] в порядке документа; страница
    с ненадёжным слоем уходит картинкой, её строки — в `fallback`
    (на случай, если картинку из PDF достать не удалось), а рисунок
    внутри страницы — вырезкой из неё (`_fig_crop`).

    `geom` — геометрия страниц (`pdfpages_worker.page_lines`), по одной на
    страницу, либо None: без неё страница идёт по строкам, как раньше."""
    report = Counter()
    unreliable = {i for i, ls in enumerate(pages) if page_unreliable(ls)}
    good_pages = [ls for i, ls in enumerate(pages) if i not in unreliable]
    heads, feet = running_heads(good_pages)
    words, hyphenated = _vocab(good_pages)
    lens = [len(_norm_line(l)) for ls in good_pages for l in ls if _norm_line(l)]
    median_len = statistics.median(lens) if lens else 0.0
    geom = geom if isinstance(geom, (list, tuple)) and len(geom) == len(pages) else [None] * len(pages)

    # Проход 1: страницы с геометрией — строки на своих местах, без мусора.
    laid: dict = {}
    unplaced: list = []         # видимые строки без места: {page, text}
    for i, ls in enumerate(pages):
        if i in unreliable:
            continue
        placeless: list = []
        recs = _geo_page(ls, geom[i], placeless)
        if recs is None:
            continue
        kept = []
        for r in recs:
            mb = _TEXT_BULLET_RE.match(r["t"] or "")
            c = _clean_line(r["t"], report)
            if c:
                if mb and not c.startswith(mb.group(1)):
                    r["bul"], r["bulch"] = True, mb.group(1)
                r["t"] = c
                kept.append(r)
            elif r.get("after"):
                # Строка ушла в мусор — её «хвост без места» к предыдущей.
                if kept:
                    kept[-1].setdefault("after", []).extend(r["after"])
                else:
                    placeless.append(list(r["after"]))
        _mark_icon_bullets(kept, (geom[i] or {}).get("figs") or [],
                           (geom[i] or {}).get("icons") or [])
        # Дробь, степень и химический индекс — обратно в свою строку, ДО
        # всего остального: по местам строк считаются поля, колонки, роли
        # и украшения, и разорванная надвое строка врала бы им всем.
        kept = _join_scripts(kept, report)
        # Украшение, распознанное буквами: одна-три буквы кеглем вдвое больше
        # основного («ЧР’» кеглем 30, «ш» кеглем 46 над первой строкой
        # страницы). Вставкой оно разрывает слово. Но крупная короткая
        # строка бывает и заголовком — «IV», «I», «§ 5», «Яд», «Мёд»: номер
        # и слово, которое документ знает, остаются (`_big_short_kept`).
        st = _page_stats(kept)
        deco = []
        for d in kept:
            if d["s"] < 2 * st["body_s"] or len(_letters(d["t"])) > 3:
                continue
            if MATH_CHAR_RE.search(d["t"]):
                continue            # крупный ∫ или √ — знак, а не украшение
            if _dropcap_join(d, kept, words):
                report["dropCaps"] += 1
            elif _big_short_kept(d["t"], words):
                continue                        # заголовок — дальше роли решат
            else:
                report["ornaments"] += 1
            deco.append(d)
        if deco:
            for d in deco:
                if d.get("after"):
                    placeless.append(d["after"])
            kept = [r for r in kept if not any(r is d for d in deco)]
        tabled = _table_streams(kept, report)
        if tabled is not None:
            kept = tabled
        multi = tabled is not None or _multi_column(kept)
        if not multi:
            kept = _reading_order(kept)
        st = _page_stats(kept)
        top, bottom = _bands(kept, st)
        # Строки без места (повёрнутые) — через ту же чистку мусора, что
        # и остальные; их пачки встают вставками в конце страницы (ниже).
        loose = []
        for run in placeless:
            geos = getattr(run, "geo", None) or [None] * len(run)
            got = _RotRun()
            for l, rg in zip(run, geos):
                # Повёрнутая строка с путём — текст по пути, с пробелами.
                c = _clean_line(_tidy((_path_text(rg) if rg else "") or l), report)
                if c:
                    got.add(c, rg)
            if got:
                loose.append(got)
                report["placelessLines"] += len(got)
                if not isinstance(run, _HiddenRun):
                    # Видимая строка без пути: её оригинал на листе ОСТАНЕТСЯ —
                    # это пишется, и выгрузка называет такие строки (проверка
                    # «осталось на языке оригинала»). Строка с путём печатается
                    # повёрнутой или по дуге.
                    left = [t for t, rg in zip(got, got.geo) if not rg]
                    if left:
                        unplaced.append({"page": i, "text": " ".join(left)})
                    report["rotatedLines"] += sum(1 for rg in got.geo if rg)
        laid[i] = {"recs": kept, "st": st, "top": top, "bottom": bottom, "multi": multi,
                   "loose": loose, "leads": _size_leads(kept)}

    _fix_labels(laid, words, report)
    _bands_by_place(laid, report)
    # Начертание документа — до разбора страниц: по нему считается, что
    # в книге выделено, а что просто её основной текст.
    base_style = _base_style(laid)
    base_fam = _base_family(laid)

    # Проход 2: колонтитулы по месту и повтору — нечётко, потому что
    # распознаватель читает их на каждой странице заново.
    hc = _clusters()
    fc = _clusters()
    for i, pg in laid.items():
        for k in pg["top"]:
            t = _norm_line(pg["recs"][k]["t"])
            if _frame_candidate(t):
                _cluster_add(hc, t, i, pg["recs"][k]["s"])
        for k in pg["bottom"]:
            t = _norm_line(pg["recs"][k]["t"])
            if _frame_candidate(t):
                _cluster_add(fc, t, i, pg["recs"][k]["s"])
    # Т15: повёрнутые строки у края листа — свой кластер: книга, где боком
    # лежат ВСЕ страницы, прямых колонтитулов не имеет вовсе.
    rc = _clusters()
    for i, pg in laid.items():
        box_i = (geom[i] or {}).get("box") if isinstance(geom[i], dict) else None
        for run in pg.get("loose") or []:
            for t_, rg in zip(run, getattr(run, "geo", None) or [None] * len(run)):
                t_n = _norm_line(t_)
                if rg and _frame_candidate(t_n) and _rot_on_edge(rg, box_i):
                    _cluster_add(rc, t_n, i, rg["pts"][0][3])
    geo_heads = _cluster_reps(hc)
    geo_feet = _cluster_reps(fc)
    geo_rot = _cluster_reps(rc)
    # Высота, на которой в нижней полосе стоят номера страниц: одинокая
    # короткая строка там же — номер, распознанный с ошибкой («зов» вместо
    # «308» кеглем 15 на боевой стр. 303): иначе крупный кегль делал его
    # заголовком посреди абзаца, разорванного переносом.
    num_ys = sorted(pg["recs"][k]["y"] for pg in laid.values() for k in pg["bottom"]
                    if _NUM_LINE_RE.match(_norm_line(pg["recs"][k]["t"])))
    num_band = None
    if len(num_ys) >= HEAD_MIN_PAGES:
        leads = sorted(pg["st"]["lead"] for pg in laid.values())
        tol = 0.5 * leads[len(leads) // 2]
        num_band = (num_ys[int(0.1 * (len(num_ys) - 1))] - tol, num_ys[int(0.9 * (len(num_ys) - 1))] + tol)

    def big_number(r: dict, st: dict) -> bool:
        # Номер кеглем вдвое больше тела — номер ГЛАВЫ («IV»), а не страницы:
        # прежде его снимало правило украшений, теперь он заголовок.
        return r["s"] >= 2 * st["body_s"] and bool(_NUM_LINE_RE.match(_norm_line(r["t"])))

    def garbled_number(r: dict) -> bool:
        t = _norm_line(r["t"])
        return (num_band is not None and 2 <= len(t) <= 4 and len(t.split()) == 1
                and num_band[0] <= r["y"] <= num_band[1])

    def head_find(t: str, size: float):
        """Т15: (полоса, представитель) известного колонтитула — для повёрнутой
        строки: сверка с кластерами верха, низа и повёрнутых строк; ключ группы —
        представитель кластера, как у прямых (одна надпись на всю книгу)."""
        for nm, cl in (("t", hc), ("b", fc), ("t", rc)):
            c = _cluster_find(cl, t, size)
            if c is not None:
                return nm, c["rep"]
        if _in_frame(t, heads | geo_heads | feet | geo_feet | geo_rot):
            return "t", t
        return None

    gid_box = [0]

    def next_gid():
        gid_box[0] += 1
        return gid_box[0]

    items = []
    head_hits: list = []        # (ключ, текст, место) снятых колонтитулов
    entries: list = []
    figs_seen: list = []        # (номер страницы, рамка в долях) по номеру метки
    layout: list = []           # рамки абзаца на страницах — по одной записи на «p»

    def flush_lines():
        if not entries:
            return
        _plain_page_fixes(entries, next_gid, hyphenated, words)
        src: list = []
        buf_lines = _assemble(entries, median_len, src)
        entries.clear()
        if any(buf_lines):
            spans: list = []
            paras = join_lines(buf_lines, hyphenated, median_len, report, spans=spans)
            paras = restore_dropcaps(paras, words, report)
            groups = [src[a:b + 1] if a is not None else None for a, b in spans]
            paras, groups = _merge_label_lines(paras, groups, [e for e in src if e], words, report)
            boxes = [_para_boxes(g_, base_style, base_fam) if g_ is not None else None
                     for g_ in groups]
            for para, place in zip(paras, boxes):
                if not para:
                    continue
                if _FIG_MARK_OPEN not in para:
                    items.append(("p", para, place))
                    layout.append(place)
                    continue
                # Метка рисунка дожила до готового абзаца — разворачиваем её
                # обратно в картинку. Текст рядом с меткой сохраняем: строка,
                # прилипшая к ней, — это текст книги, и терять его нельзя.
                pos = 0
                for m in _FIG_MARK_RE.finditer(para):
                    head = para[pos:m.start()].strip()
                    if head:
                        items.append(("p", head, place))
                        layout.append(place)
                    n = int(m.group(1))
                    if 0 <= n < len(figs_seen):
                        items.append(("fig",) + figs_seen[n])
                    pos = m.end()
                tail = para[pos:].strip()
                if tail:
                    items.append(("p", tail, place))
                    layout.append(place)

    for i, ls in enumerate(pages):
        if i in unreliable:
            flush_lines()
            # Запасной текст на случай, если картинки страницы нет: тот же
            # мусор, рамка и склейка, что у остальных, — иначе колонтитул
            # и номер обложки ушли бы в перевод.
            fb = [c for c in (_clean_line(_tidy(l), Counter()) for l in ls) if c]
            fb = _strip_page_frame(fb, heads, feet, Counter())
            fallback = [_WS_RE.sub(" ", x) for x in join_lines(fb, hyphenated, median_len, Counter())]
            items.append(("img", i, fallback))
            continue
        pg = laid.get(i)
        entries.append({"role": "page", "pg": i, "geo": pg is not None, "t": "", "gid": None})
        if pg is None:
            # Сначала мусор, потом рамка страницы: номер страницы, за которым
            # стоит строка-обрывок распознавания, иначе не был бы последним.
            cleaned = []
            for l in ls:
                c = _clean_line(_tidy(l), report)
                if c:
                    cleaned.append(c)
            cleaned = _strip_page_frame(cleaned, heads, feet, report)
            # Между страницами абзац продолжается: слово, разрезанное концом
            # страницы («мар-» … «ганца»), склеивается, когда между его
            # половинами больше не стоят колонтитул и номер.
            entries.extend({"role": "f", "gid": None, "t": c} for c in cleaned)
            continue
        recs = pg["recs"]
        drop = set()

        def alone(k, recs=recs):
            # Обрывок — один на своей высоте: «а» рядом с «3» в адресе
            # «ул. Довженко, 3 а» — часть строки, а не кусок рисунка.
            s = max(recs[k]["s"], 1.0)
            return not any(j != k and abs(recs[j]["y"] - recs[k]["y"]) < 0.5 * s
                           for j in range(len(recs)))
        for bname, band, known, clusters in (("t", pg["top"], heads | geo_heads, hc),
                                             ("b", pg["bottom"], feet | geo_feet, fc)):
            hit = [k for k in band if _frame_candidate(_norm_line(recs[k]["t"]))
                   and (_in_frame(_norm_line(recs[k]["t"]), known)
                        or _cluster_hit(clusters, _norm_line(recs[k]["t"]), recs[k]["s"]))]
            for k in band:
                t = _norm_line(recs[k]["t"])
                if big_number(recs[k], pg["st"]):
                    continue
                if _edge_scrap(t, words) and alone(k):
                    report["ornaments"] += 1
                    drop.add(k)
                elif _NUM_LINE_RE.match(t) or (band is pg["bottom"] and len(band) == 1
                                             and garbled_number(recs[k])):
                    report["pageNumbers"] += 1
                    drop.add(k)
                elif k in hit or (hit and _frame_candidate(t)):
                    # Полоса, где узнана хоть одна строка колонтитула, —
                    # колонтитул целиком: вторую его строку распознаватель
                    # иногда искажает до неузнаваемости («Лпитоксииотератш —»).
                    report["runningHeads"] += 1
                    _head_hit(head_hits, bname, clusters, t, recs[k], i)
                    drop.add(k)
        # Колонтитул и номер у самого края — и без пробела после них (плотная
        # вёрстка, мусор распознавания в полосе). Снизу — только номер
        # и нижний колонтитул, узнанный ПО МЕСТУ (`geo_feet`): последняя
        # строка текста, повторённая на нескольких страницах, по одному
        # счёту строк выглядит нижним колонтитулом, а она — текст.
        # Т15: порядок — по высоте на листе, а не по номеру в потоке.
        by_y = sorted(range(len(recs)), key=lambda k: (-recs[k]["y"], recs[k]["x0"]))
        for bname, order, known, clusters in (("t", by_y, heads | geo_heads, hc),
                                              ("b", by_y[::-1], geo_feet, fc)):
            seen_f = set()
            n_ = 0
            for k in order:
                # Т15: окно — три РАЗНЫЕ строки. Скан с задвоенным слоем
                # распознавания даёт колонтитул дважды («Апитоксинотерапия —»,
                # «Апитоксинотерапия  —», «лечение …», «лечение …»), и повтор
                # окна не занимает — иначе вторая строка колонтитула оставалась
                # на странице телом.
                f_ = _fold(_norm_line(recs[k]["t"]))
                if f_ not in seen_f:
                    seen_f.add(f_)
                    n_ += 1
                if n_ > HEAD_WINDOW:
                    break
                if k in drop:
                    continue
                t = _norm_line(recs[k]["t"])
                if big_number(recs[k], pg["st"]):
                    break
                if _edge_scrap(t, words) and alone(k):
                    report["ornaments"] += 1
                elif _NUM_LINE_RE.match(t):
                    report["pageNumbers"] += 1
                elif _frame_candidate(t) and _in_frame(t, known):
                    report["runningHeads"] += 1
                    _head_hit(head_hits, bname, clusters, t, recs[k], i)
                else:
                    break
                drop.add(k)
        body = _cell_order([r for k, r in enumerate(recs) if k not in drop], geom[i])
        lost_after = [c_ for k, r in enumerate(recs) if k in drop for t in (r.get("after") or [])
                      for c_ in [_clean_line(_tidy(t), report)] if c_]
        unplaced.extend({"page": i, "text": t} for t in lost_after)
        roles = ([("f", None)] * len(body) if pg["multi"]
                 else _geo_roles(body, pg["st"], geom[i], next_gid))
        # Рисунок встаёт в поток на своё место — перед первой строкой, что
        # стоит НИЖЕ него. Вставкой (роль «a»), а не обычной строкой: абзац,
        # который рисунок разорвал, продолжается мимо него (`_assemble`).
        box = (geom[i] or {}).get("box") or [0, 0, 0, 0]
        figs = _fig_boxes(geom[i] or {}, body, merge=True)
        spots: dict = {}
        for f in figs:
            # Место — перед БЛИЖАЙШЕЙ строкой под рисунком, а не перед первой
            # по списку: на странице, где текст обтекает рисунок, порядок
            # строк не совпадает с порядком чтения (`multi`), и «первая
            # по списку» унесла бы рисунок в чужое место.
            below = [(r["y"], k) for k, r in enumerate(body) if r["y"] < f[1]]
            at = max(below)[1] if below else len(body)
            spots.setdefault(at, []).append(f)
        for k in range(len(body) + 1):
            for f in spots.get(k, []):
                crop = _fig_crop(f, recs, figs, box)
                if not _fig_printable(crop, recs):
                    report["figuresSkipped"] += 1
                    continue
                entries.append({"role": "a", "gid": next_gid(), "t": _fig_mark(len(figs_seen))})
                figs_seen.append((i, _fig_frac(crop, box)))
                report["figures"] += 1
            if k >= len(body):
                break
            r, (role, gid) = body[k], roles[k]
            if role != "f":
                report["insetLines" if role == "a" else "headingLines"] += 1
            entries.append({"role": role, "gid": gid, "t": r["t"],
                            # Место строки — для выгрузки «как в оригинале».
                            "geo": (i, r["x0"], r["y"], r["x1"], r["s"], r.get("st") or "",
                                    r.get("fam") or "", r.get("xl"), r.get("parts"),
                                    r.get("exact"), r.get("color"), r.get("gaps")),
                            # Колонка таблицы (`_table_streams`): абзац из одной
                            # колонки в другую не переходит.
                            "tcol": r.get("tcol"),
                            # Т34: горизонтальные линии листа (граница ряда
                            # таблицы) — абзац через них не переходит.
                            "hr": (geom[i] or {}).get("hrules") if isinstance(geom[i], dict) else None,
                            # Обычный межстрочный страницы — мерка «пропуска
                            # строки» между пунктами списка (`_geo_follows`).
                            "plead": _lead_for(pg, r["s"]),
                            # Пункт списка со значком-картинкой — начало абзаца.
                            "bul": bool(r.get("bul")),
                            "bulch": r.get("bulch")})
            for t_ in r.get("after") or []:
                c_ = _clean_line(_tidy(t_), report)
                if c_:
                    report["placelessLines"] += 1
                    unplaced.append({"page": i, "text": c_})
                    entries.append({"role": role, "gid": gid, "t": c_})
        # Строки без места — пачками, вставками в конце страницы: гадать
        # их место нечем, а терять их текст нельзя. Рамки у них нет, и
        # выгрузка «как в оригинале» их не трогает — на странице они
        # остаются оригиналом, как и были.
        loose_keep = []
        box_p = (geom[i] or {}).get("box") if isinstance(geom[i], dict) else None
        for run in (pg.get("loose") or []):
            keep_run = _RotRun()
            for t_, rg in zip(run, getattr(run, "geo", None) or [None] * len(run)):
                t_n = _norm_line(t_)
                found = (head_find(t_n, rg["pts"][0][3])
                         if rg and _frame_candidate(t_n) and _rot_on_edge(rg, box_p) else None)
                if found:
                    # Т15: повёрнутый колонтитул — в ту же группу, что прямые.
                    report["runningHeads"] += 1
                    report["rotatedHeads"] += 1
                    head_hits.append(((found[0], found[1]), t_n, (i, "ROT", rg)))
                else:
                    keep_run.add(t_, rg)
            if keep_run:
                loose_keep.append(keep_run)
        for run in loose_keep + ([lost_after] if lost_after else []):
            g_ = next_gid()
            for t_, rg in zip(run, getattr(run, "geo", None) or [None] * len(run)):
                e_ = {"role": "a", "gid": g_, "t": t_}
                if rg:
                    e_["rgeo"] = (i, rg)    # путь повёрнутой строки — для печати
                entries.append(e_)
    flush_lines()
    # Колонтитулы — ПОСЛЕ текста: они относятся ко всей книге, а не к месту
    # в ней, и вставленные в поток разорвали бы абзац на своей странице.
    for text, boxes in _head_paragraphs(head_hits, base_style, base_fam):
        items.append(("p", text, boxes))
        layout.append(boxes)
        report["headParagraphs"] += 1
    report["imagePages"] = len(unreliable)
    report["paragraphs"] = sum(1 for it in items if it[0] == "p")
    return {"items": items, "imagePages": sorted(unreliable), "report": dict(report),
            "layout": layout, "unplaced": unplaced, "pageBoxes": [((g or {}).get("box") if isinstance(g, dict) else None)
                                            for g in geom],
            "heads": sorted(heads | feet | geo_heads | geo_feet)}
