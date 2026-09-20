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
import re
import statistics
import unicodedata
from collections import Counter

SOFT = "­"

# Версия правил разбора. Пишется на проект при импорте (`parseRules`),
# и проект, нарезанный правилами постарше, экран предлагает пересобрать
# из хранимого исходника (`/api/projects/{pid}/resegment`). Меняешь правила
# так, что меняются абзацы, — поднимай: 1 — построчный разбор, 2 — по
# геометрии, 3 — обрывки у края, «по-»/«лис», метки врезок, разворот,
# 4 — над- и подстрочные куски (дроби, степени, индексы) на своём месте
# и повреждённый знак математики, который больше не снимается орнаментом.
RULES_VERSION = 4

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
_BULLET_RE = re.compile(r"^(?:[♦•■▪●○◦✓✔–—-]|\d{1,3}[.)]|[a-zа-яё][.)])\s+\S")
# Конец абзаца по знаку — как у прежней склейки в importers.
_END_RE = re.compile(r"[.!?…:;»”\")\]]\s*$")
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
        return True
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


def _math_token(t: str) -> bool:
    return bool(_MATH_NEAR_RE.search(t)) and all(
        c in _MATH_MARKS or c not in _ORNAMENT_CHARS for c in t)


def _clean_line(line: str, report: dict):
    """Строка без мусора распознавания либо None, если она вся мусор."""
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
        if not core and all(c in _ORNAMENT_CHARS for c in t):
            if t.startswith(("•", "♦", "■", "●")) and len(t) == 1 and not toks:
                toks.append(t)         # маркер списка в начале строки
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
SCRIPT_GAP_SHARE = 1.5       # и рядом по горизонтали
SCRIPT_SPACE_SHARE = 0.25    # зазор, начиная с которого между кусками ПРОБЕЛ
_SCRIPT_CHAR_RE = re.compile(r"[0-9²³¹⁰-₟]")


def _script_piece(r: dict) -> bool:
    t = (r.get("t") or "").strip()
    return 0 < len(t) <= SCRIPT_MAX_CHARS and bool(_SCRIPT_CHAR_RE.search(t))


def _hgap(a: dict, b: dict) -> float:
    """Зазор между кусками по горизонтали; отрицательный — перекрываются.
    Над/подстрочник НИКОГДА не налезает на свою строку, поэтому перекрытие —
    это два разных места на странице, и сливать их нельзя."""
    if b["x0"] >= a["x1"]:
        return b["x0"] - a["x1"]
    if a["x0"] >= b["x1"]:
        return a["x0"] - b["x1"]
    return -1.0


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
        if f["s"] <= 0 or not _script_piece(f):
            continue
        best = None
        for j, b in enumerate(recs):
            if j == i or b["s"] <= 0 or f["s"] > SCRIPT_SIZE_SHARE * b["s"]:
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
        text = parts[0]["t"]
        prev = parts[0]
        for pc in parts[1:]:
            # Пробел — по зазору, и мерка берётся у КРУПНОГО куска: межсловный
            # пробел это примерно четверть его кегля. Мерка по мелкому объявила
            # бы пробелом стык «1» и «/3», то есть саму дробь.
            step = SCRIPT_SPACE_SHARE * max(prev["s"], pc["s"], 1.0)
            if (prev.get("rsp") or pc.get("lsp") or pc["x0"] - prev["x1"] >= step)                     and not text.endswith(" ") and not pc["t"].startswith(" "):
                text += " "
            text += pc["t"]
            prev = pc
        out.append({"t": text, "x0": parts[0]["x0"], "x1": max(p["x1"] for p in parts),
                    "y": base["y"], "s": base["s"],
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


def join_lines(lines: list, hyphenated: set = frozenset(), median_len: float = 0.0,
               report: dict = None) -> list:
    """Строки → абзацы. Конец абзаца — конец предложения, короткая строка
    перед заглавной, строка КАПСОМ, маркер списка, пустая строка, потолок.
    Перенос слова снимается: мягкий — всегда, дефисный — когда продолжение
    со строчной и такого составного слова в документе посреди строки нет."""
    report = report if report is not None else Counter()
    out, buf = [], ""
    buf_caps = False               # в буфере — заголовок КАПСОМ (склеивается со следующим таким же)
    n = len(lines)

    def flush():
        nonlocal buf, buf_caps
        if buf:
            out.append(buf)
            buf = ""
        buf_caps = False

    for i in range(n):
        line = (lines[i] or "").strip()
        if not line:
            flush()
            continue
        nxt = (lines[i + 1] or "").strip() if i + 1 < n else ""
        caps = _is_caps_heading(line)
        if buf and ((_BULLET_RE.match(line)) or (buf_caps != caps and not buf.endswith((SOFT, "-")))):
            flush()
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
        if _END_RE.search(buf) or len(buf) >= PARA_MAX:
            flush()
            continue
        if (median_len and len(line) < HEADING_LEN_SHARE * median_len
                and not line.endswith((",", "-", "—", "–", SOFT))
                and nxt[:1] and (nxt[:1].isupper() or nxt[:1].isdigit() or _BULLET_RE.match(nxt))):
            flush()
    flush()
    return out


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


def _geo_page(lines: list, g) -> "list | None":
    """Строки страницы с местом: [{t, x0, x1, y, s}] в порядке потока; None —
    у страницы нет полной геометрии (тогда она идёт прежней дорогой)."""
    if not isinstance(g, dict):
        return None
    gl = g.get("lines") or []
    if len(gl) != len(lines):
        return None
    recs = []
    for l, p in zip(lines, gl):
        t = _tidy(l or "")
        if not t:
            continue
        if not p or len(p) < 4:
            return None                 # строка без места — страница без геометрии
        raw = _TAB_RE.sub(" ", l or "")
        # Был ли у сырой строки пробел по краям: `_tidy` его снимает, а при
        # склейке разорванной строки он единственное ТОЧНОЕ свидетельство
        # («…площадь в м» + «2» + « измеряют так.»). Зазор по x — оценка:
        # у куска в один знак конец строки считается по ширине знака.
        recs.append({"t": t, "x0": float(p[0]), "y": float(p[1]), "s": float(p[2] or 0),
                     "x1": max(float(p[3]), float(p[0])),
                     "lsp": raw[:1] == " ", "rsp": raw[-1:] == " "})
    return recs


def _multi_column(recs: list) -> bool:
    """Две длинные строки на одной высоте далеко друг от друга — колонки.
    Тогда порядок потока оставляется: сортировка по высоте перемешала бы
    колонки построчно."""
    long_ = [r for r in recs if len(r["t"]) >= 15]
    for i, a in enumerate(long_):
        for b in long_[i + 1:]:
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


def _bands(recs: list, st: dict) -> tuple:
    """(верхняя полоса, нижняя полоса) — номера строк у края страницы,
    отделённых от текста пробелом больше обычного интервала: колонтитулы
    и номера. Сверху до трёх строк (двухстрочный колонтитул и номер),
    снизу — до двух."""
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
        if nxt is None or abs(recs[grp[-1]]["y"] - recs[nxt]["y"]) < GEO_BAND_GAP * st["lead"]:
            return []
        return grp
    idx = list(range(len(recs)))
    return band(idx, HEAD_WINDOW), band(idx[::-1], FOOT_WINDOW)


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


def _cluster_hit(cl: dict, text: str, size: float) -> bool:
    own = cl["exact"].get(text)             # строка уже в кластере — сравнивать незачем
    for c in [own] + [x for x in _cluster_near(cl, text) if x is not own]:
        if c is None or len(c["pages"]) < HEAD_MIN_PAGES:
            continue
        if c is own or c["rep"] == text or _similar_enough(c["rep"], text):
            med = statistics.median(c["sizes"])
            if not med or abs(size - med) <= 0.25 * med:
                return True
    return False


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

    # Рисунки: вложенная картинка заметного размера, не во всю страницу
    # (фон скана — тоже картинка). Метки вокруг — отдельными абзацами,
    # подпись под рисунком или над ним — тоже.
    figs = []
    for f in g.get("figs") or []:
        w, h = f[2] - f[0], f[3] - f[1]
        if not (w >= 0.12 * pw and h >= 0.08 * ph and w * h < 0.85 * pw * ph):
            continue
        # Картинка, по которой идут строки текста (подложка, рисунок
        # в обтекании), — не рисунок с метками: иначе каждая короткая
        # концевая строка абзаца над ней считалась бы меткой.
        over = sum(1 for r in recs if len(r["t"]) >= 30 and r["x0"] < f[2] and r["x1"] > f[0]
                   and f[1] <= r["y"] <= f[3])
        if over < 2:
            figs.append(f)
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


def _assemble(entries: list, median_len: float) -> list:
    """Поток строк с разметкой ролей → строки для `join_lines`: вставки
    и заголовки — отдельными абзацами (пустая строка вокруг), а вставка,
    разорвавшая абзац (строка перед ней открыта, а поток после неё
    продолжается строчной буквой), встаёт ПОСЛЕ конца этого абзаца."""
    out: list = []
    pending: list = []
    waited = [0]

    def emit(block):
        out.append("")
        out.extend(block)
        out.append("")

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
    while i < n:
        e = entries[i]
        role = e["role"]
        if role == "page":
            i += 1
            continue
        if role == "f":
            if pending and (para_ends(out[-1] if out else "", e["t"]) or waited[0] >= DEFER_MAX_LINES):
                release()
            out.append(e["t"])
            if pending:
                waited[0] += 1
            i += 1
            continue
        j = i
        while j < n and entries[j]["role"] == role and entries[j]["gid"] == e["gid"]:
            j += 1
        block = [x["t"] for x in entries[i:j]]
        if role == "a":
            k = j
            while k < n and entries[k]["role"] in ("a", "page"):
                k += 1
            cont = k < n and entries[k]["role"] == "f" and _starts_lower(entries[k]["t"])
            if out and out[-1] and _open_end(out[-1]) and cont:
                pending.append(block)
            else:
                emit(block)
        else:                                      # заголовок: абзац до него кончился
            release()
            emit(block)
        i = j
    release()
    return out


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


def clean(pages: list, geom: "list | None" = None) -> dict:
    """Страницы (список списков строк) → {items, report}.

    items — [("p", текст)] и [("img", номер страницы)] в порядке документа;
    страница с ненадёжным слоем уходит картинкой, её строки — в
    `fallback` (на случай, если картинку из PDF достать не удалось).

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
    for i, ls in enumerate(pages):
        if i in unreliable:
            continue
        recs = _geo_page(ls, geom[i])
        if recs is None:
            continue
        kept = []
        for r in recs:
            c = _clean_line(r["t"], report)
            if c:
                r["t"] = c
                kept.append(r)
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
            if _dropcap_join(d, kept, words):
                report["dropCaps"] += 1
            elif _big_short_kept(d["t"], words):
                continue                        # заголовок — дальше роли решат
            else:
                report["ornaments"] += 1
            deco.append(d)
        if deco:
            kept = [r for r in kept if not any(r is d for d in deco)]
        multi = _multi_column(kept)
        if not multi:
            kept = _reading_order(kept)
        st = _page_stats(kept)
        top, bottom = _bands(kept, st)
        laid[i] = {"recs": kept, "st": st, "top": top, "bottom": bottom, "multi": multi}

    _fix_labels(laid, words, report)

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
    geo_heads = _cluster_reps(hc)
    geo_feet = _cluster_reps(fc)
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

    gid_box = [0]

    def next_gid():
        gid_box[0] += 1
        return gid_box[0]

    items = []
    entries: list = []

    def flush_lines():
        if not entries:
            return
        _plain_page_fixes(entries, next_gid, hyphenated, words)
        buf_lines = _assemble(entries, median_len)
        entries.clear()
        if any(buf_lines):
            paras = join_lines(buf_lines, hyphenated, median_len, report)
            paras = restore_dropcaps(paras, words, report)
            items.extend(("p", p) for p in paras if p)

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
        for band, known, clusters in ((pg["top"], heads | geo_heads, hc), (pg["bottom"], feet | geo_feet, fc)):
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
                    drop.add(k)
        # Колонтитул и номер у самого края — и без пробела после них (плотная
        # вёрстка, мусор распознавания в полосе). Снизу — только номер
        # и нижний колонтитул, узнанный ПО МЕСТУ (`geo_feet`): последняя
        # строка текста, повторённая на нескольких страницах, по одному
        # счёту строк выглядит нижним колонтитулом, а она — текст.
        for order, known in ((range(len(recs)), heads | geo_heads),
                             (range(len(recs) - 1, -1, -1), geo_feet)):
            for n_, k in enumerate(order):
                if n_ >= HEAD_WINDOW:
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
                else:
                    break
                drop.add(k)
        body = [r for k, r in enumerate(recs) if k not in drop]
        roles = ([("f", None)] * len(body) if pg["multi"]
                 else _geo_roles(body, pg["st"], geom[i], next_gid))
        for r, (role, gid) in zip(body, roles):
            if role != "f":
                report["insetLines" if role == "a" else "headingLines"] += 1
            entries.append({"role": role, "gid": gid, "t": r["t"]})
    flush_lines()
    report["imagePages"] = len(unreliable)
    report["paragraphs"] = sum(1 for it in items if it[0] == "p")
    return {"items": items, "imagePages": sorted(unreliable), "report": dict(report),
            "heads": sorted(heads | feet | geo_heads | geo_feet)}
