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
# Во сколько раз увеличиваем картинку ПЕРЕД поиском строк и с какой стороны
# это нужно. Детектор ищет строки по своей сетке, и мелкая картинка кладётся
# в неё целиком: серый текст учебника высотой в 19 пикселей на странице
# 877x542 он просто не находит. Замер на боевой image161.png: в исходном
# размере 8 строк, при увеличении вдвое — 10, и найденные две — это ровно
# начало абзаца («пиопневмоторакса не удается, то необходимые» и «достоверные
# данные могут быть получены при»), без которого остальные строки не
# складываются в предложение. Втрое — 12 строк, но лишние две это РАЗРЕЗАННЫЕ
# надвое прежние: чем крупнее сетка, тем охотнее детектор рвёт строку, а
# склеивать обратно приходится нам (см. `_join_pieces`). Поэтому ровно вдвое
# и только мелким.
IMG_DETECT_SCALE = int(os.environ.get("IMG_DETECT_SCALE", "2"))
IMG_DETECT_UNDER_PX = float(os.environ.get("IMG_DETECT_UNDER_PX", "1400"))
# Потолок по результату: увеличение стоит вчетверо больше памяти и времени,
# а воркер один. Крупной картинке оно и не нужно — у неё разрешения хватает.
IMG_DETECT_MAX_MPX = float(os.environ.get("IMG_DETECT_MAX_MPX", "6"))
# Насколько рамка должна утонуть в чужой, чтобы считаться той же строкой,
# найденной вторым проходом.
IMG_DUP_COVER = float(os.environ.get("IMG_DUP_COVER", "0.7"))
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


_READY = None


def engine_ready() -> tuple:
    """(готов ли движок, причина отказа словами).

    Ответ кэшируется: внутри `import rapidocr_onnxruntime`, который тянет
    в процесс onnxruntime на сотни мегабайт, а спрашивают об этом на каждом
    открытии экрана экспорта — даже в проекте без исходника. Состав пакетов
    без рестарта не меняется, так что второй раз спрашивать не о чем."""
    global _READY
    if _READY is not None:
        return _READY
    if Image is None:
        _READY = (False, "не установлен Pillow")
    elif _np is None:
        _READY = (False, "не установлен numpy")
    else:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            _READY = (True, "")
        except Exception as e:
            _READY = (False, "не установлен движок распознавания (rapidocr): %s" % e)
    return _READY


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
    # Смотрим ДВАЖДЫ: как есть и увеличенной. Увеличение находит то, что
    # детектор проглядел в мелком масштабе, но само по себе не бесплатно —
    # у пограничных рамок падает уверенность, и они уходят под порог: на
    # боевой image100.png две рамки с 0.62 и 0.64 пропали совсем. Значит
    # заменять один взгляд другим нельзя, можно только сложить: найденное
    # прежним разбором обязано остаться найденным.
    found = _detect_boxes(eng, arr, 1)
    k = _detect_scale(im.width, im.height)
    if k > 1:
        try:
            big = _np.asarray(im.convert("RGB").resize(
                (im.width * k, im.height * k), Image.LANCZOS))
            found += _detect_boxes(eng, big, k)
        except Exception as e:
            # Не нашлось памяти или картинка с сюрпризом — остаётся первый
            # взгляд. Меньше найденных строк лучше, чем разбор, упавший целиком.
            print("[image_text] увеличить не вышло (%s), смотрим как есть" % e,
                  file=sys.stderr)
    # Склейка кусков идёт ДО замера плоскости: рамка склеенной строки накрывает
    # и зазор между кусками, а по этому числу решают, можно ли писать перевод
    # поверх картинки. Померив куски порознь, мы поручились бы за место,
    # которого не смотрели, — и заливка стёрла бы попавшую в зазор графику.
    out = _join_pieces(_dedupe_boxes(found))
    for l in out:
        # Плоскость фона считаем по ИСХОДНОЙ картинке: увеличение сглаживает
        # пиксели, и снимок сошёл бы за ровный фон, на который можно писать.
        l["flat"] = round(flatness(arr, l["box"]), 3)
    out.sort(key=lambda l: (l["box"][1], l["box"][0]))
    return out


def _detect_boxes(eng, arr, k: int) -> list:
    """Рамки одного прохода, ВСЕГДА в исходных пикселях: по рамке потом стирают,
    пишут и режут кроп — в увеличенных координатах она попала бы мимо."""
    res, _elapse = eng(arr)
    out = []
    for item in (res or []):
        pts, _text, score = item[0], item[1], float(item[2])
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        box = [int(min(xs) / k), int(min(ys) / k),
               int(max(xs) / k), int(max(ys) / k)]
        if score < IMG_MIN_CONF or box[2] - box[0] < 4 or box[3] - box[1] < 4:
            continue
        out.append({"box": box, "conf": round(score, 3), "flat": 0.0})
    return out


def _dedupe_boxes(lines: list) -> list:
    """Одна и та же строка, найденная обоими проходами, — одна строка.

    Крупная рамка побеждает: увеличенный проход дробит строку чаще мелкого,
    и кусок, целиком лежащий внутри уже взятой рамки, — это она же. Обратный
    случай тоже закрыт: если целую строку нашёл только второй проход, она
    больше по площади, берётся первой и проглатывает найденный прежде кусок."""
    out: list = []
    for l in sorted(lines, key=lambda x: -((x["box"][2] - x["box"][0])
                                           * (x["box"][3] - x["box"][1]))):
        x0, y0, x1, y1 = l["box"]
        area = max(1, (x1 - x0) * (y1 - y0))
        dup = False
        for k in out:
            kx0, ky0, kx1, ky1 = k["box"]
            over = (max(0, min(x1, kx1) - max(x0, kx0))
                    * max(0, min(y1, ky1) - max(y0, ky0)))
            if over >= IMG_DUP_COVER * area:
                # Уверенность берём лучшую: строку видели дважды.
                k["conf"] = round(max(k["conf"], l["conf"]), 3)
                dup = True
                break
            # Проходы режут строку по-разному, и рамки расходятся не вложением,
            # а внахлёст: «до пятого слова» у одного и «с третьего» у другого.
            # Оставить обе — значит завести два сегмента с общим куском текста:
            # он будет прочитан дважды, переведён дважды и дважды написан
            # поверх картинки при выгрузке. Это одна строка, и рамка у неё одна.
            if over > 0 and _same_line(k, l):
                k["box"] = [min(kx0, x0), min(ky0, y0), max(kx1, x1), max(ky1, y1)]
                k["conf"] = round(min(k["conf"], l["conf"]), 3)
                dup = True
                break
        if not dup:
            out.append(l)
    return out


def _detect_scale(w: int, h: int) -> int:
    """Во сколько раз увеличить картинку перед поиском строк."""
    if max(w, h) >= IMG_DETECT_UNDER_PX:
        return 1
    if w * h * IMG_DETECT_SCALE ** 2 > IMG_DETECT_MAX_MPX * 1e6:
        return 1
    return IMG_DETECT_SCALE


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


# ── Куски одной строки ───────────────────────────────────────────────
# Детектор режет строку по широкому пробелу. В выключенном по формату абзаце
# пробелы растянуты, а в разрядке они шире буквы — и на боевой странице
# учебника (image161.png) одна строка «рентгенологическим исследовании с»
# пришла ТРЕМЯ рамками. Дальше каждый обрывок уходил в модель отдельно
# и становился отдельным сегментом: «рентгенологическим», «исследовании»,
# «ании с При этом» — три строки, которые нечего переводить и по которым
# нечего проверять.
#
# Склеивать по одному лишь расстоянию НЕЛЬЗЯ, и это не осторожность, а замер:
# на той же странице до соседней КОЛОНКИ зазор 21 пиксель, а между словами
# внутри строки — 20 и 22. Правило по ширине склеило бы текст левой колонки
# с подписью правой, то есть два разных текста в один сегмент.
#
# Колонку выдаёт не зазор, а ПОВТОР края: строки колонки начинаются (или
# кончаются) на одном x, а обрывок слова стоит сам по себе. Второй признак —
# по зазору никто не пишет: если ни одна другая строка картинки не
# перечёркивает это место, значит там межколонник, а не пробел.
# Пороги — из окружения, как и все соседние: правило подбирается на боевых
# картинках, и крутить его без выката должно быть можно.
# Известный предел: край колонки считается по ВСЕМ строкам, включая сами куски,
# поэтому абзац, разорванный на нескольких строках примерно на одном x, сам
# себе создаёт «край» и остаётся несклеенным. Отличить такое от настоящей
# колонки нечем, а ошибаться дешевле в эту сторону: несклеенная строка — лишний
# сегмент, склеенная чужая — два текста в одном переводе.
IMG_JOIN_GAP = float(os.environ.get("IMG_JOIN_GAP", "1.6"))      # предел зазора в высотах строки
IMG_JOIN_TIGHT = float(os.environ.get("IMG_JOIN_TIGHT", "0.6"))  # ближе — пробел при любых признаках
IMG_JOIN_EDGE = int(os.environ.get("IMG_JOIN_EDGE", "2"))        # столько строк на одном x — край колонки
IMG_JOIN_NEAR = float(os.environ.get("IMG_JOIN_NEAR", "3"))      # свидетель ищется в стольких межстрочиях
IMG_JOIN_VOUCH = float(os.environ.get("IMG_JOIN_VOUCH", "0.5"))  # и накрывает столько от КАЖДОГО куска


def _same_line(a: dict, b: dict) -> bool:
    """Две рамки стоят на ОДНОЙ строке: тот же кегль, тот же уровень.

    Окно по высоте шире, чем у сборки блоков (там 0.6-1.7), и это не небрежность:
    кусок строки бывает в одну букву, а у буквы без выносных элементов рамка
    вдвое ниже, чем у строки с «р» и «б». Боевая image161.png: «с» в конце
    строки — 11 пикселей против 19 у «рентгенологическим», отношение 1.73, и
    прежнее окно оставляло эту букву отдельной строкой. Уровень при этом
    сходится точь-в-точь, и держат склейку именно середина и перекрытие."""
    ah = max(1, a["box"][3] - a["box"][1])
    bh = max(1, b["box"][3] - b["box"][1])
    if not (0.5 <= ah / bh <= 2.0):
        return False
    small = min(ah, bh)
    over = min(a["box"][3], b["box"][3]) - max(a["box"][1], b["box"][1])
    mid_a = (a["box"][1] + a["box"][3]) / 2
    mid_b = (b["box"][1] + b["box"][3]) / 2
    return abs(mid_a - mid_b) <= 0.5 * small and over >= 0.5 * small


def _edge_xs(lines: list, side: int, tol: float) -> list:
    """x, на которых начинается (side=0) или кончается (side=2) не меньше
    IMG_JOIN_EDGE строк, — край колонки."""
    xs = sorted(l["box"][side] for l in lines)
    out, i = [], 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] - xs[i] <= tol:
            j += 1
        if j - i + 1 >= IMG_JOIN_EDGE:
            out.append(sum(xs[i:j + 1]) / (j - i + 1))
        i = j + 1
    return out


def _written_across(lines: list, a: dict, b: dict, h: float) -> bool:
    """По зазору между `a` и `b` пишет кто-то ЕЩЁ — значит это пробел внутри
    строки, а не межколонник.

    Три требования к свидетелю, и каждое куплено разбором ошибки:
    1) он из ДРУГОЙ полосы — сосед по своей полосе это кусок той же разорванной
       строки, он стоит по краю зазора и о нём ничего не говорит;
    2) он РЯДОМ по вертикали (`IMG_JOIN_NEAR` межстрочий). Иначе заголовок
       страницы или подпись под рисунком объявляют пробелом любой зазор, какой
       пересекают, — по всей высоте картинки, через любую колонку;
    3) он накрывает ОБА куска, а не только сам зазор. Строка своей же колонки,
       которая чуть длиннее соседних и заходит за межколонник, иначе ручается
       за пропасть, о которой ничего не знает: «левый текст + правая подпись»
       склеивались в один сегмент."""
    ax0, ax1 = a["box"][0], a["box"][2]
    bx0, bx1 = b["box"][0], b["box"][2]
    mid = (a["box"][1] + a["box"][3]) / 2
    need_a = IMG_JOIN_VOUCH * max(1, ax1 - ax0)
    need_b = IMG_JOIN_VOUCH * max(1, bx1 - bx0)
    for l in lines:
        lm = (l["box"][1] + l["box"][3]) / 2
        far = abs(lm - mid)
        if far <= 0.5 * h or far > IMG_JOIN_NEAR * h:
            continue
        lx0, lx1 = l["box"][0], l["box"][2]
        if (min(ax1, lx1) - max(ax0, lx0) >= need_a
                and min(bx1, lx1) - max(bx0, lx0) >= need_b):
            return True
    return False


def _join_pieces(lines: list) -> list:
    """Куски одной строки — в одну строку. Правила см. выше."""
    if len(lines) < 2:
        # Копии и здесь: вызывающий вправе править полученное, а разнобой
        # «иногда те же объекты, иногда копии» однажды кусает.
        return [dict(l) for l in lines]
    hs = sorted(max(1, l["box"][3] - l["box"][1]) for l in lines)
    tol = max(4.0, 0.4 * hs[len(hs) // 2])
    lefts = _edge_xs(lines, 0, tol)
    rights = _edge_xs(lines, 2, tol)
    out: list = []
    for ln in sorted(lines, key=lambda l: (l["box"][1], l["box"][0])):
        joined = False
        for cur in out:
            if cur["box"][0] > ln["box"][0] or not _same_line(cur, ln):
                continue
            gap = ln["box"][0] - cur["box"][2]
            h = max(1, max(cur["box"][3] - cur["box"][1],
                           ln["box"][3] - ln["box"][1]))
            if not (-0.5 * h <= gap <= IMG_JOIN_GAP * h):
                continue
            lo, hi = cur["box"][2], ln["box"][0]
            # Край колонки, попавший в зазор, склейку запрещает ВСЕГДА, включая
            # тесный и отрицательный зазор: рамки детектора идут с запасом, и
            # рамка соседней колонки, налезшая на пару пикселей, склеивалась
            # безусловно — мимо найденного края.
            if any(lo - tol <= e <= hi + tol for e in lefts + rights):
                continue
            # Свидетеля спрашиваем только про широкий зазор: пробел уже
            # IMG_JOIN_TIGHT высоты межколонником не бывает.
            if gap > IMG_JOIN_TIGHT * h and not _written_across(lines, cur, ln, h):
                continue
            cur["box"] = [min(cur["box"][0], ln["box"][0]),
                          min(cur["box"][1], ln["box"][1]),
                          max(cur["box"][2], ln["box"][2]),
                          max(cur["box"][3], ln["box"][3])]
            # Худшее из двух — как у блока: склеенная строка не может быть
            # надёжнее самого сомнительного своего куска.
            cur["conf"] = min(cur["conf"], ln["conf"])
            cur["flat"] = min(cur["flat"], ln["flat"])
            joined = True
            break
        if not joined:
            out.append(dict(ln))
    out.sort(key=lambda l: (l["box"][1], l["box"][0]))
    return out


def group_blocks(lines: list) -> list:
    """Строки → блоки. Блок — это то, что человек прочитал бы как один текст:
    та же колонка, тот же кегль, строки идут подряд И ВЫРОВНЕНЫ ПО ОДНОМУ КРАЮ.

    Последнее условие не украшение. Без него заголовок во всю ширину над двумя
    колонками цеплял к себе первую строку той колонки, что оказалась выше
    на пиксель, — и разбиение менялось целиком от дрожания детектора: в один
    блок попадали заголовок, строка правой колонки и строка левой, а модель
    получала склейку трёх разных текстов.

    Перед сборкой строка собирается из своих КУСКОВ (`_join_pieces`): детектор
    режет её по широкому пробелу, и до склейки «рентгенологическим»,
    «исследовании» и «с» — три разные строки, которые ни по одному краю
    не выровнены и потому в один блок не попадут никогда. Склейка живёт
    в `detect_lines` — там есть сама картинка, и плоскость фона считается уже
    по склеенной рамке."""
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


def preview(img_bytes: bytes, max_side: int = 768) -> Optional[bytes]:
    """Уменьшенный PNG всей картинки — обзорный кадр для модели.

    Сырые байты туда отдавать нельзя по двум причинам. Во-первых, тип: они
    уходят объявленные как image/png, а в пакете лежат и jpeg, и gif, и tiff —
    BMP и TIFF зрячий API не принимает вовсе, и весь вызов падает, оставляя
    блоки непрочитанными навсегда. Во-вторых, вес: обзорный кадр нужен ради
    контекста, а не ради букв — их модель читает по кропам."""
    if Image is None:
        return None
    try:
        im = Image.open(io.BytesIO(img_bytes))
        im = im.convert("RGBA") if _has_alpha(im) else im.convert("RGB")
    except Exception:
        return None
    w, h = im.size
    if max(w, h) > max_side:
        k = max_side / float(max(w, h))
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG")
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
