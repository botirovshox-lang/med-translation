"""Текст, впечатанный в картинку: найти строки, стереть их и написать перевод.

Зачем отдельный модуль. В `main.py` этот код был бы четвёртой сотней строк
про растр посреди веб-сервиса, и проверить его можно было бы только целиком
поднятым приложением. Здесь нет ни FastAPI, ни сети, ни вызовов модели:
на вход байты картинки, на выход байты картинки и отчёт о том, что удалось.
Чтение текста живёт в `main.py` — оно платное и требует ключа, а всё
остальное детерминированно и проверяется тестом.

Правила, которые нельзя ослаблять:

1. **Посмотреть не удалось — это «не знаю», а не «текста нет».**
   `detect_lines` возвращает None и когда движка нет, и когда картинка
   не читается (битый JPEG, векторный метафайл): пустой список означал бы
   «надписей в этой схеме нет» — враньё ровно там, где на ответ полагаются.

2. **На пёстром фоне не перерисовываем.** Стереть строку можно, только если
   под ней однородный фон: заливка прямоугольником поверх рентгенограммы —
   это порча документа, а не перевод. Мера — `flatness`, порог
   `IMG_FLAT_MIN`. Что не прошло, уходит подписью под картинкой, и число
   таких случаев называется человеку.

3. **Ни один блок не пропадает молча.** На каждый переданный блок в отчёте
   есть строка: написали либо не написали и почему. Молча пропущенная
   надпись остаётся на языке оригинала, и человек узнает об этом, только
   пролистав готовый файл до конца.

4. **Заливка идёт ДО текста, вся разом.** Рамки соседних блоков законно
   пересекаются (заголовок во всю ширину над двумя колонками), и заливка
   второго блока стирала бы уже написанный перевод первого — с отчётом
   «оба написаны».

5. **Формат файла сохраняется вместе со своими потрохами.** Тип части пакета
   .docx объявлен в [Content_Types].xml по РАСШИРЕНИЮ: подмени байты .jpeg
   картинкой PNG — и документ станет невалидным. Вместе с форматом
   сохраняются EXIF, профиль цвета и разрешение: без EXIF фотография,
   которую Word показывал повёрнутой, ляжет боком.
"""
import io
import os
import re
import sys
import threading
from pathlib import Path
from typing import Optional

try:                       # numpy приходит зависимостью движка распознавания,
    import numpy as _np    # но модуль обязан импортироваться и без него —
except ImportError:        # иначе бэкенд не поднимется вовсе
    _np = None
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

ROOT = Path(__file__).resolve().parent

# ── Пороги ───────────────────────────────────────────────────────────
# Ниже этой уверенности детектора строку не считаем найденной.
IMG_MIN_CONF = float(os.environ.get("IMG_MIN_CONF", "0.6"))
# Короче этого переводить нечего.
IMG_MIN_CHARS = 3
# Меньше этого числа БУКВ — надпись аппарата, а не текст документа: «250MA»,
# «kV 120», «10mm/div», «а», «R». Считаются именно буквы, а не символы: правило
# должно работать в любой паре языков, а не только там, где мы знаем алфавит.
IMG_MIN_LETTERS = 3
# Доля пикселей рамки, совпавших с фоновым цветом, при которой стирание
# незаметно. На учебнике фтизиатрии медиана по всем найденным строкам 0.74,
# а по строкам на светлом фоне (подписи, схемы) — 0.79; аппаратная надпечатка
# поверх снимка и текст на фотографии сюда не проходят.
IMG_FLAT_MIN = float(os.environ.get("IMG_FLAT_MIN", "0.55"))
# Кегль в ИСХОДНЫХ пикселях, ниже которого перевод нечитаем. Английский
# длиннее русского, и подгонка «лишь бы влезло» кончается строкой в три
# пикселя высотой: это не перевод, а вид перевода.
IMG_FONT_MIN_PX = float(os.environ.get("IMG_FONT_MIN_PX", "7"))
# Во сколько раз увеличиваем картинку перед рисованием: экранный размер
# в .docx задают extent'ы разметки, а не пиксели файла, поэтому увеличение
# даёт чёткий текст даром. Но не даром по весу — файл растёт вчетверо, —
# поэтому увеличиваем ТОЛЬКО мелкий текст, которому это нужно.
IMG_SCALE = 2
IMG_SCALE_UNDER_PX = float(os.environ.get("IMG_SCALE_UNDER_PX", "40"))
# Потолок ПО РЕЗУЛЬТАТУ. Отсканированная страница 1186×2121 — это 2.5 Мпкс,
# и вчетверо больше даёт десятимегапиксельный JPEG на несколько мегабайт;
# на учебнике такие страницы раздували выгрузку с 21.8 МБ до 37. Крупной
# картинке разрешения хватает и без увеличения — оно нужно мелким рисункам.
IMG_SCALE_MAX_MPX = float(os.environ.get("IMG_SCALE_MAX_MPX", "4"))
# Насколько рамка может вылезти за край картинки, прежде чем считать её
# чужой. `_clip` молча прижимает координаты к краю, и перевод, посчитанный
# для рамки 400×300, оказался бы написан в углу 145×113 с отчётом «готово».
IMG_BOX_KEEP = 0.8

# Формат части пакета менять нельзя (см. шапку модуля).
_SAVE = {"JPEG": {"quality": 90, "subsampling": 0},
         "PNG": {"optimize": True},
         "GIF": {},
         "BMP": {},
         "TIFF": {}}
# Что тащим из исходного файла в новый: без этого фотография ляжет боком,
# цвета уедут, а вставленная в Word картинка сменит физический размер.
_KEEP_INFO = ("exif", "icc_profile", "dpi")

_NOISE_RE = re.compile(r"^[\W\d_]+$", re.UNICODE)


def is_noise(text: str) -> bool:
    """Строка, которую незачем переводить.

    Три случая, и все три — не текст документа: слишком короткая («а», «б»),
    совсем без букв («25.03.2008», «10mm/div») и почти без букв («250MA»,
    «kV 120») — так выглядят настройки аппарата на снимке. Надпечатку целиком
    это правило не ловит и не должно: «KARIMOV SH.» отсеивает признак
    `overlay`, который ставит модель при чтении."""
    t = (text or "").strip()
    if len(t) < IMG_MIN_CHARS or _NOISE_RE.fullmatch(t):
        return True
    return sum(1 for c in t if c.isalpha()) < IMG_MIN_LETTERS


# ── Движок поиска строк ──────────────────────────────────────────────
# RapidOCR берётся ТОЛЬКО как детектор: его распознавалка идёт с моделью
# «китайский + английский» и кириллицы не знает вовсе — «сторонний тотальный
# пиопневмоторакс» она вернула как «CTOpOHHMiTOTabHbIИWONHeBMOTOpaKC».
# Боксы при этом ставит точно, и это ровно то, чего не умеет зрячая модель:
# координаты она выдумывает. Поэтому геометрия отсюда, текст — от модели.
_ENGINE = None
_ENGINE_ERR = ""
# Модели занимают сотни мегабайт. Без лока два потока подняли бы два движка —
# то же правило, что у `_queue_term` в main.py: пишешь в общее, бери лок.
_ENGINE_LOCK = threading.Lock()


def engine_ready() -> tuple:
    """(готов ли движок, причина отказа словами)."""
    if Image is None:
        return False, "не установлен Pillow"
    if _np is None:
        return False, "не установлен numpy"
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception as e:
        return False, "не установлен движок распознавания (rapidocr): %s" % e
    return True, ""


def _engine():
    global _ENGINE, _ENGINE_ERR
    with _ENGINE_LOCK:
        if _ENGINE is None and not _ENGINE_ERR:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _ENGINE = RapidOCR()
            except Exception as e:
                _ENGINE_ERR = str(e)
                print("[image_text] движок не поднялся: %s" % e, file=sys.stderr)
        return _ENGINE


def release_engine() -> None:
    """Отпустить модели детектора. onnxruntime держит сотни мегабайт, а разбор
    картинок бывает раз в жизни проекта; воркер uvicorn один, и эта память
    отнимается у самого сервиса."""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def _clip(box, w: int, h: int) -> tuple:
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, min(x0, w)), max(0, min(y0, h))
    x1, y1 = max(x0, min(x1, w)), max(y0, min(y1, h))
    return x0, y0, x1, y1


def _visible(reg):
    """RGB, как область БУДЕТ ВЫГЛЯДЕТЬ на белой странице документа.

    Прозрачные пиксели в PNG обычно хранят чёрный цвет, и анализ по сырым
    каналам объявлял бы прозрачный фон чёрным: краска выбиралась белая,
    а перевод получался белым по прозрачному — невидимым, с отчётом
    «написано»."""
    if reg.shape[-1] == 4:
        a = reg[:, :, 3:4].astype(float) / 255.0
        return (reg[:, :, :3].astype(float) * a + 255.0 * (1.0 - a)).astype(_np.uint8)
    return reg[:, :, :3]


def flatness(arr, box) -> float:
    """Доля пикселей рамки, совпавших с самым частым цветом.

    Это и есть ответ на вопрос «можно ли стереть строку незаметно»: под
    подписью в книге фон белый и доля близка к единице, под надписью
    на рентгенограмме — градиент, и доля мала."""
    x0, y0, x1, y1 = _clip(box, arr.shape[1], arr.shape[0])
    reg = arr[y0:y1, x0:x1]
    if reg.size == 0:
        return 0.0
    q = (_visible(reg) // 32).reshape(-1, 3)
    vals, cnt = _np.unique(q, axis=0, return_counts=True)
    mode = vals[cnt.argmax()]
    return float((_np.abs(q.astype(int) - mode.astype(int)).max(axis=1) <= 1).mean())


def detect_lines(img_bytes: bytes) -> Optional[list]:
    """[{box, conf, flat}] или None, если посмотреть не удалось.

    None — это «не знаю»: движка нет либо картинка не читается (битый файл,
    векторный метафайл, незнакомый формат). Пустой список означал бы «надписей
    нет», а такое утверждение делать не из чего."""
    ok, _why = engine_ready()
    if not ok:
        return None
    eng = _engine()
    if eng is None:
        return None
    try:
        im = Image.open(io.BytesIO(img_bytes))
        arr = _np.asarray(im.convert("RGB"))
    except Exception as e:
        print("[image_text] картинка не читается: %s" % e, file=sys.stderr)
        return None
    res, _elapse = eng(arr)
    out = []
    for item in (res or []):
        pts, _text, score = item[0], item[1], float(item[2])
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        box = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
        if score < IMG_MIN_CONF or box[2] - box[0] < 4 or box[3] - box[1] < 4:
            continue
        out.append({"box": box, "conf": round(score, 3),
                    "flat": round(flatness(arr, box), 3)})
    out.sort(key=lambda l: (l["box"][1], l["box"][0]))
    return out


# ── Сборка строк в блоки ─────────────────────────────────────────────
# Детектор находит СТРОКИ, а переводить надо предложения. Подпись под
# рисунком 174 разбита на четыре строки с переносами («сооб-щения»,
# «воздухо-носных»); отдай их модели по отдельности — получишь четыре обрубка
# вместо фразы, а глоссарий и проверки будут работать по мусору. Поэтому
# соседние строки одной колонки собираются в блок, и сегментом становится он.


def _spread(vals: list) -> float:
    m = sum(vals) / len(vals)
    return (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5


def _align_of(lines: list) -> str:
    """Как выключены строки блока: влево, по центру или вправо.

    Подпись под рисунком часто отцентрована, а колонка чисел выключена вправо;
    написать перевод от левого края значит сдвинуть его относительно картинки.
    Смотрим, какой из трёх краёв держится ровнее остальных."""
    if len(lines) < 2:
        return "left"
    lefts = _spread([l["box"][0] for l in lines])
    rights = _spread([l["box"][2] for l in lines])
    mids = _spread([(l["box"][0] + l["box"][2]) / 2 for l in lines])
    best = min(lefts, rights, mids)
    if best == lefts:
        return "left"
    return "right" if best == rights else "center"


def group_blocks(lines: list) -> list:
    """Строки → блоки. Блок — это то, что человек прочитал бы как один текст:
    та же колонка, тот же кегль, строки идут подряд И ВЫРОВНЕНЫ ПО ОДНОМУ КРАЮ.

    Последнее условие не украшение. Без него заголовок во всю ширину над двумя
    колонками цеплял к себе первую строку той колонки, что оказалась выше
    на пиксель, — и разбиение менялось целиком от дрожания детектора: в один
    блок попадали заголовок, строка правой колонки и строка левой, а модель
    получала склейку трёх разных текстов."""
    blocks: list = []
    for ln in sorted(lines, key=lambda l: (l["box"][1], l["box"][0])):
        x0, y0, x1, y1 = ln["box"]
        h = max(1, y1 - y0)
        placed = False
        for b in blocks:
            bx0, by0, bx1, by1 = b["box"]
            over = min(x1, bx1) - max(x0, bx0)          # та же колонка
            narrow = max(1, min(x1 - x0, bx1 - bx0))
            same_size = 0.6 <= (h / max(1, b["lineH"])) <= 1.7   # тот же кегль
            gap = y0 - by1                              # идут подряд
            tol = max(4.0, max(h, b["lineH"]))          # выключены по одному краю
            aligned = (abs(x0 - bx0) <= tol
                       or abs(x1 - bx1) <= tol
                       or abs((x0 + x1) / 2 - (bx0 + bx1) / 2) <= tol)
            if (over > 0.35 * narrow and same_size and aligned
                    and -0.4 * h <= gap <= 1.0 * max(h, b["lineH"])):
                b["box"] = [min(bx0, x0), min(by0, y0), max(bx1, x1), max(by1, y1)]
                b["lines"].append(ln)
                b["lineH"] = (b["lineH"] * (len(b["lines"]) - 1) + h) / len(b["lines"])
                placed = True
                break
        if not placed:
            blocks.append({"box": [x0, y0, x1, y1], "lines": [ln], "lineH": h})
    out = []
    for b in blocks:
        out.append({"box": [int(v) for v in b["box"]], "rows": len(b["lines"]),
                    # Высота СТРОКИ, а не блока. По ней считаются поля рамки
                    # и кропа: посчитанные от высоты блока, они у подписи
                    # из пяти строк заезжали на снимок сверху и на соседний
                    # абзац снизу — с отчётом «написано».
                    "lineH": int(round(b["lineH"])),
                    "conf": round(min(l["conf"] for l in b["lines"]), 3),
                    "flat": round(min(l["flat"] for l in b["lines"]), 3),
                    "align": _align_of(b["lines"])})
    out.sort(key=lambda b: (b["box"][1], b["box"][0]))
    return out


# ── Кроп блока ───────────────────────────────────────────────────────


def _has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)


def _pad_for(box, line_h=None, rows=None, ratio: float = 0.14) -> int:
    """Поле вокруг рамки — доля СТРОКИ, а не блока.

    Детектор ставит рамку впритык, и сглаживание букв остаётся снаружи серой
    каймой; чтобы её убрать, нужно поле в долю строки. Посчитанное от высоты
    блока, оно у подписи из пяти строк выходит впятеро больше — и заливка
    съедает низ снимка сверху и верх соседнего абзаца снизу."""
    h = max(1, box[3] - box[1])
    base = line_h or (h / max(1, rows or 1))
    return max(1, int(round(min(base, h) * ratio)))


def crop(img_bytes: bytes, box: list, pad: float = 0.25,
         line_h=None, rows=None) -> Optional[bytes]:
    """PNG с одним блоком. Нужен двоим: модели — чтобы прочитать текст
    без соседних надписей, человеку — чтобы увидеть в карточке сегмента,
    что было на картинке. Без второго проверить распознанное нечем.

    Поле считается от строки: у подписи из шести строк поле «четверть блока»
    захватывает полторы чужие строки, и модель добросовестно перепишет
    в этот сегмент соседний абзац."""
    if Image is None:
        return None
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return None                # вырожденная рамка: показывать нечего
    try:
        im = Image.open(io.BytesIO(img_bytes))
        im = im.convert("RGBA") if _has_alpha(im) else im.convert("RGB")
    except Exception:
        return None
    p = max(2, _pad_for(box, line_h, rows, pad))
    x0, y0, x1, y1 = _clip((x0 - p, y0 - p, x1 + p, y1 + p), im.size[0], im.size[1])
    if x1 <= x0 or y1 <= y0:
        return None
    out = io.BytesIO()
    im.crop((x0, y0, x1, y1)).save(out, "PNG")
    return out.getvalue()


# ── Перерисовка ──────────────────────────────────────────────────────


def font_path(bold: bool = False) -> Optional[str]:
    """Шрифт лежит ФАЙЛОМ в репозитории. На системный полагаться нельзя:
    у юнита ProtectSystem=full, состав шрифтов сервера меняется без нас,
    а отсутствие шрифта дало бы молча кривой экспорт вместо честного отказа."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    p = ROOT / "assets" / name
    if p.exists():
        return str(p)
    for cand in ("/usr/share/fonts/truetype/dejavu/" + name,
                 "C:\\Windows\\Fonts\\arial.ttf"):
        if Path(cand).exists():
            return cand
    return None


def _fill_and_ink(arr, box) -> tuple:
    """(цвет фона, цвет текста) по самой строке. Брать белый «по умолчанию»
    нельзя: подписи в схемах лежат на цветных плашках, и белая заплатка
    на голубом фоне видна за версту.

    Считаем по ВИДИМОМУ цвету (`_visible`), а заливку берём из сырых каналов:
    так прозрачный фон остаётся прозрачным, а краска для него выбирается
    по тому, как область выглядит на белой странице."""
    x0, y0, x1, y1 = _clip(box, arr.shape[1], arr.shape[0])
    reg = arr[y0:y1, x0:x1]
    vis = _visible(reg).reshape(-1, 3)
    raw = reg.reshape(-1, arr.shape[-1])
    q = vis // 32
    vals, cnt = _np.unique(q, axis=0, return_counts=True)
    mode = vals[cnt.argmax()]
    near = _np.abs(q.astype(int) - mode.astype(int)).max(axis=1) <= 1
    # Медиана, а не среднее: в «похожие на фон» попадает и кайма сглаживания
    # букв, и среднее уводит заливку в серое — заплатка становится видна.
    fill = _np.median(raw[near], axis=0)
    base = _np.median(vis[near], axis=0)
    far = _np.abs(vis.astype(int) - base.astype(int)).max(axis=1) > 60
    if far.sum() >= max(4, 0.005 * len(vis)):
        # Цвет краски берём по ЯДРУ, а не по среднему: половина «непохожих»
        # пикселей — это полутона на границе буквы, и среднее по ним даёт
        # серый текст вместо чёрного. Берём треть, самую далёкую от фона.
        lum = vis[far].astype(int).mean(axis=1)
        order = _np.argsort(lum if base.mean() > 127 else -lum)
        ink = vis[far][order[:max(1, len(order) // 3)]].mean(axis=0)
    else:                                   # строка почти без контраста —
        ink = _np.array([0, 0, 0])          # чёрный честнее выдуманного цвета
    if _np.abs(ink.astype(int) - base.astype(int)).max() < 40:
        ink = _np.array([0, 0, 0]) if base.mean() > 127 else _np.array([255, 255, 255])
    return (tuple(int(round(v)) for v in fill),
            tuple(int(round(v)) for v in ink))


def _wrap(draw, text: str, font, width: float) -> list:
    """Перевод по строкам рамки. Слово длиннее строки (длинный термин, ссылка)
    режется посимвольно: иначе оно молча вылезет за рамку."""
    lines, cur = [], ""
    for word in (text or "").split():
        probe = (cur + " " + word).strip()
        if draw.textlength(probe, font=font) <= width or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = word
        while draw.textlength(cur, font=font) > width and len(cur) > 1:
            keep = len(cur)
            while keep > 1 and draw.textlength(cur[:keep], font=font) > width:
                keep -= 1
            lines.append(cur[:keep])
            cur = cur[keep:]
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text: str, fpath: str, w: float, h: float, hi: int) -> tuple:
    """Самый крупный кегль, при котором перевод целиком влезает в рамку.
    Двоичным поиском: перебор по одному кеглю — это сотни раскладок текста
    на каждую картинку."""
    best = (None, [], 0, 0)
    lo = 4
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(fpath, mid)
        rows = _wrap(draw, text, font, w)
        step = mid * 1.22
        if step * len(rows) <= h and all(draw.textlength(r, font=font) <= w for r in rows):
            best = (font, rows, step, mid)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _scale_for(im, items: list) -> int:
    """Во сколько раз увеличивать. Мелкий текст без увеличения выходит рваным,
    а крупному оно не даёт ничего — только вчетверо больший файл: палитровая
    схема на 1.5 КБ превращалась в 7.5 КБ, фотография на 25 КБ — в 135."""
    w, h = im.size
    if w * h * IMG_SCALE * IMG_SCALE > IMG_SCALE_MAX_MPX * 1e6:
        return 1
    small = min((it.get("lineH")
                 or (it["box"][3] - it["box"][1]) / max(1, it.get("rows") or 1)
                 for it in items if it.get("box")), default=0)
    return IMG_SCALE if small and small < IMG_SCALE_UNDER_PX else 1


def _save(img, fmt: str, info: dict, orig_mode: str) -> Optional[bytes]:
    """Сохранить в том же формате и с тем же содержимым служебных полей.

    Палитровый PNG возвращаем в палитру: перевод рисуется плоскими цветами,
    а RGB на схеме — это пятикратный рост файла на ровном месте."""
    out = io.BytesIO()
    kw = dict(_SAVE[fmt])
    for k in _KEEP_INFO:
        if info.get(k):
            kw[k] = info[k]
    if fmt == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")
    if fmt == "PNG" and orig_mode == "P":
        # Палитровая схема обязана вернуться в палитру: на учебнике картинка
        # 149 КБ выходила из перерисовки на 1891 КБ — в тринадцать раз тяжелее
        # без единого нового пикселя смысла. FASTOCTREE берёт и RGBA (палитра
        # с прозрачностью — обычное дело у схем) и сохраняет tRNS; обычный
        # MEDIANCUT прозрачность теряет и весит втрое больше.
        img = img.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
    if fmt == "GIF":
        img = img.convert("RGB").quantize(colors=256)
    img.save(out, fmt, **kw)
    return out.getvalue()


def _refuse(items: list, why: str) -> tuple:
    return None, [{"i": i, "ok": False, "why": why} for i in range(len(items))]


def render_target(img_bytes: bytes, items: list) -> tuple:
    """Стереть исходные надписи и написать перевод. (новые байты | None, отчёт).

    Отчёт по каждому блоку обязателен: перерисовать удаётся не всё, а молча
    пропущенный блок остаётся на языке оригинала — человек узнает об этом,
    только открыв готовый файл."""
    if Image is None or _np is None:
        return _refuse(items, "no_pillow")
    if not items:
        return None, []
    fpath = font_path()
    if fpath is None:
        return _refuse(items, "no_font")
    try:
        im = Image.open(io.BytesIO(img_bytes))
        fmt = (im.format or "").upper()
        info = dict(im.info or {})
        orig_mode = im.mode
        if fmt not in _SAVE:
            return _refuse(items, "format:" + (fmt or "?"))
        if fmt == "GIF" and (getattr(im, "n_frames", 1) > 1 or "transparency" in info):
            # Анимация схлопнулась бы в один кадр, а прозрачность стала бы
            # чёрным прямоугольником посреди страницы. Такой текст уходит
            # подписью — это честнее испорченной картинки.
            return _refuse(items, "format:GIF-special")
        alpha = _has_alpha(im)
        im = im.convert("RGBA" if alpha else "RGB")
    except Exception as e:
        return _refuse(items, "open:%s" % e)

    w, h = im.size
    arr = _np.asarray(im)
    k = _scale_for(im, items)
    big = im.resize((w * k, h * k), Image.LANCZOS) if k > 1 else im.copy()
    draw = ImageDraw.Draw(big)
    report, plan = [], []
    for i, it in enumerate(items):
        text = (it.get("text") or "").strip()
        box = it.get("box") or [0, 0, 0, 0]
        if not text:
            report.append({"i": i, "ok": False, "why": "empty"})
            continue
        pad_y = _pad_for(box, it.get("lineH"), it.get("rows"), 0.14)
        pad_x = _pad_for(box, it.get("lineH"), it.get("rows"), 0.10)
        want = (box[0] - pad_x, box[1] - pad_y, box[2] + pad_x, box[3] + pad_y)
        pbox = _clip(want, w, h)
        want_area = max(1, (want[2] - want[0]) * (want[3] - want[1]))
        if (pbox[2] - pbox[0]) * (pbox[3] - pbox[1]) < IMG_BOX_KEEP * want_area:
            # Рамка не помещается в картинку: координаты посчитаны не для неё.
            # `_clip` прижал бы их к краю, и перевод встал бы в угол.
            report.append({"i": i, "ok": False, "why": "outside"})
            continue
        if pbox[2] - pbox[0] < 4 or pbox[3] - pbox[1] < 4:
            report.append({"i": i, "ok": False, "why": "tiny_box"})
            continue
        flat = flatness(arr, pbox)
        if flat < IMG_FLAT_MIN:
            # Пёстрый фон: заливка была бы заплаткой поверх снимка.
            report.append({"i": i, "ok": False, "why": "flat", "flat": round(flat, 3)})
            continue
        fill, ink = _fill_and_ink(arr, pbox)
        sbox = [v * k for v in pbox]
        bw, bh = sbox[2] - sbox[0], sbox[3] - sbox[1]
        font, rows, step, size = _fit(draw, text, fpath, bw, bh, max(6, int(bh)))
        if font is None or size < IMG_FONT_MIN_PX * k:
            # Влезть-то влезет, но читать будет нечего. Такой блок уходит
            # подписью под картинкой — это честнее нечитаемой строки.
            report.append({"i": i, "ok": False, "why": "tiny_font",
                           "size": round(size / k, 1)})
            continue
        plan.append({"i": i, "sbox": sbox, "font": font, "rows": rows, "step": step,
                     "fill": fill, "ink": ink, "align": it.get("align") or "left"})
        report.append({"i": i, "ok": True, "size": round(size / k, 1), "rows": len(rows)})
    if not plan:
        return None, report

    # Сперва ВСЕ заливки, потом ВСЕ надписи. Рамки соседних блоков законно
    # пересекаются, и заливка второго стирала бы уже написанный перевод
    # первого — с отчётом «оба написаны».
    for p in plan:
        draw.rectangle(p["sbox"], fill=p["fill"])
    for p in plan:
        sbox, bw = p["sbox"], p["sbox"][2] - p["sbox"][0]
        ink = p["ink"] + (255,) if big.mode == "RGBA" else p["ink"]
        y = sbox[1] + max(0, ((sbox[3] - sbox[1]) - p["step"] * len(p["rows"])) / 2)
        for row in p["rows"]:
            x = sbox[0]
            if p["align"] in ("center", "right"):
                free = max(0, bw - draw.textlength(row, font=p["font"]))
                x = sbox[0] + (free / 2 if p["align"] == "center" else free)
            draw.text((x, y), row, font=p["font"], fill=ink)
            y += p["step"]
    try:
        return _save(big, fmt, info, orig_mode), report
    except Exception as e:
        # Отчёт не должен пропасть вместе со сборкой: без него вызывающий
        # не узнает, что перерисовки не было, и не поставит подписи.
        print("[image_text] картинка не сохранилась: %s" % e, file=sys.stderr)
        return None, [{**r, "ok": False, "why": r.get("why") or "save:%s" % e}
                      for r in report]
