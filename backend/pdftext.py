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

import re
import statistics
import unicodedata
from collections import Counter

SOFT = "­"

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
# Заголовок среди строк: короткая строка, после которой абзац начинается
# с заглавной, либо строка КАПСОМ.
HEADING_LEN_SHARE = 0.55
# Дефис на конце строки, который СВОЙ, даже если составное слово нигде
# больше не встретилось: частицы и приставки, которые в русском пишутся
# только через дефис. Список русский и короткий — для остальных языков
# решает словарь документа.
_HYPHEN_RIGHT = frozenset(("то", "либо", "нибудь", "ка", "таки", "де", "с"))
_HYPHEN_LEFT = frozenset(("по", "кое", "кой", "во", "в"))


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


def _is_noise_line(line: str) -> bool:
    """Строка без единого слова, зато со знаками мусора или из трёх и более
    обрывков: «Л ) . — 1 «■», «1 Ш», «ш ж т». Число («61»), маркер списка
    («1.») и одиночное слово сюда не попадают."""
    toks = line.split()
    if not toks:
        return False
    if any(_token_kind(t) == "word" for t in toks):
        return False
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


def _strip_page_frame(lines: list, heads: set, feet: set, report: dict) -> list:
    """Снять с краёв страницы колонтитулы и номер. Только с краёв: тот же
    номер посреди страницы — это текст."""
    ls = [_tidy(l) for l in lines]
    ls = [l for l in ls if l]
    # Сверху: до трёх строк колонтитула и номера подряд.
    cut = 0
    while cut < len(ls) and cut < HEAD_WINDOW:
        l = _norm_line(ls[cut])
        if l in heads:
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
        if l in feet:
            report["runningHeads"] += 1
        elif _NUM_LINE_RE.match(l):
            report["pageNumbers"] += 1
        else:
            break
        cut += 1
    if cut:
        ls = ls[:-cut]
    return ls


def _clean_line(line: str, report: dict):
    """Строка без мусора распознавания либо None, если она вся мусор."""
    if _is_ornament(line):
        report["ornaments"] += 1
        return None
    if _is_noise_line(line):
        report["junkLines"] += 1
        return None
    s = _UNDERSCORE_RE.sub(" ", line)
    if not any(c in _ORNAMENT_CHARS for c in s):
        return s.strip() or None       # нечего снимать — строка как есть (с двойными пробелами)
    # Одиночные знаки мусора между словами («^лучше», ««■») — снимаем
    # только те, что стоят отдельным токеном или на краю слова.
    toks = []
    for t in s.split():
        core = t.strip("".join(_ORNAMENT_CHARS))
        if not core and all(c in _ORNAMENT_CHARS for c in t):
            if t.startswith(("•", "♦", "■", "●")) and len(t) == 1 and not toks:
                toks.append(t)         # маркер списка в начале строки
            continue
        toks.append(core or t)          # «^лучше» → «лучше»
    out = " ".join(toks).strip()
    return out or None


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
            particle = bool(left and right and (right[0].lower() in _HYPHEN_RIGHT
                                                or left[0].lower() in _HYPHEN_LEFT))
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


def clean(pages: list) -> dict:
    """Страницы (список списков строк) → {items, report}.

    items — [("p", текст)] и [("img", номер страницы)] в порядке документа;
    страница с ненадёжным слоем уходит картинкой, её строки — в
    `fallback` (на случай, если картинку из PDF достать не удалось)."""
    report = Counter()
    unreliable = {i for i, ls in enumerate(pages) if page_unreliable(ls)}
    good_pages = [ls for i, ls in enumerate(pages) if i not in unreliable]
    heads, feet = running_heads(good_pages)
    words, hyphenated = _vocab(good_pages)
    lens = [len(_norm_line(l)) for ls in good_pages for l in ls if _norm_line(l)]
    median_len = statistics.median(lens) if lens else 0.0

    items = []
    buf_lines: list = []

    def flush_lines():
        if buf_lines:
            paras = join_lines(buf_lines, hyphenated, median_len, report)
            paras = restore_dropcaps(paras, words, report)
            items.extend(("p", p) for p in paras if p)
            buf_lines.clear()

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
        # Сначала мусор, потом рамка страницы: номер страницы, за которым
        # стоит строка-обрывок распознавания, иначе не был бы последним.
        cleaned = []
        for l in ls:
            c = _clean_line(_tidy(l), report)
            if c:
                cleaned.append(c)
        cleaned = _strip_page_frame(cleaned, heads, feet, report)
        # Между страницами абзац продолжается: слово, разрезанное концом
        # страницы («мар-» … «ганца»), склеивается, когда между его половинами
        # больше не стоят колонтитул и номер.
        buf_lines.extend(cleaned)
    flush_lines()
    report["imagePages"] = len(unreliable)
    report["paragraphs"] = sum(1 for it in items if it[0] == "p")
    return {"items": items, "imagePages": sorted(unreliable), "report": dict(report),
            "heads": sorted(heads | feet)}
