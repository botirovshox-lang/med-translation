#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Замер детектора строк: поиск С ЧТЕНИЕМ против поиска БЕЗ чтения.

Зачем. Распознавалку движка (`rapidocr`) мы выбрасываем целиком — текст
в рамках читает зрячая модель, а движок берётся ТОЛЬКО как детектор
(см. шапку `backend/image_text.py`). Но платим мы за неё временем: чтение
идёт на каждой найденной строке и дважды — проходом как есть и увеличенным.
`RapidOCR` умеет искать без чтения (`use_rec=False`), и это ровно та работа,
которая нам нужна.

Почему нельзя просто включить. Нынешний порог `IMG_MIN_CONF` — это
уверенность ЧТЕНИЯ, и без чтения её нет вовсе; её место занимает
`IMG_BOX_THRESH` у самого детектора, а числа у них разные. Значит меняется
СОСТАВ найденного, а закон модуля — «найденное прежним разбором обязано
остаться найденным»: потерянная строка это потерянный кусок книги, а лишняя
это лишний кроп в платном вызове. Проверяется такое замером на боевых
картинках, а не рассуждением, — этим и занят инструмент.

Что печатает по каждой картинке и в итоге:
  * сколько строк нашёл каждый режим и сколько секунд на это ушло;
  * ПОТЕРЯНО — рамки старого режима, которых в новом нет (это и есть цена);
  * ПРИБЫЛО — рамки нового режима, которых не было в старом;
  * блоков — во сколько кропов это сложится, то есть за сколько картинок
    платить зрячей модели (`group_blocks`, `IMG_MIN_CHARS` тут ни при чём:
    блоки считаются до чтения).

Откуда брать картинки:
    python tools/ocr_bench.py backend/data/sources/12.docx
    python tools/ocr_bench.py path/to/pictures/      # .png/.jpg/.jpeg/...
    python tools/ocr_bench.py file.docx --thresh 0.4 --limit 20

Вызовов модели нет, сеть не трогается, ни один файл не меняется. Движок
(`rapidocr-onnxruntime`) нужен: без него мерить нечего, и инструмент так
и говорит, а не печатает нули.
"""
import argparse
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Совпадение рамок, при котором это одна и та же строка. Проходы режут
# строку по-разному, поэтому сравнивать координаты в лоб нельзя: мерим
# пересечение к объединению, как принято у детекторов.
IOU_SAME = 0.5

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")


def pictures(src: Path, limit: int) -> list:
    """[(имя, байты)] — из .docx берём части пакета, из папки — файлы."""
    out = []
    if src.is_dir():
        for p in sorted(src.iterdir()):
            if p.suffix.lower() in IMAGE_EXT:
                out.append((p.name, p.read_bytes()))
    elif src.suffix.lower() in IMAGE_EXT:
        out.append((src.name, src.read_bytes()))
    else:
        with zipfile.ZipFile(src) as zf:
            for n in sorted(zf.namelist()):
                if n.startswith("word/media/") and Path(n).suffix.lower() in IMAGE_EXT:
                    out.append((Path(n).name, zf.read(n)))
    return out[:limit] if limit else out


def iou(a: list, b: list) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    over = (max(0, min(ax1, bx1) - max(ax0, bx0))
            * max(0, min(ay1, by1) - max(ay0, by0)))
    if over <= 0:
        return 0.0
    both = ((ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - over)
    return over / both if both > 0 else 0.0


def missing(was: list, now: list) -> list:
    """Рамки из `was`, которым в `now` не нашлось пары."""
    return [l for l in was
            if max((iou(l["box"], n["box"]) for n in now), default=0.0) < IOU_SAME]


def run(mode: str, thresh: str, pics: list, it) -> dict:
    """Один режим по всем картинкам. Модуль перечитывается: пороги и режим
    он берёт из окружения ОДИН раз, при импорте, — как в бою."""
    os.environ["IMG_DET_ONLY"] = "1" if mode == "det" else ""
    if thresh:
        os.environ["IMG_BOX_THRESH"] = thresh
    import importlib
    it = importlib.reload(it)
    ok, why = it.engine_ready()
    if not ok:
        print("движка нет: %s" % why)
        sys.exit(2)
    res = {"lines": {}, "blocks": {}, "secs": 0.0, "none": []}
    for name, blob in pics:
        t = time.time()
        lines = it.detect_lines(blob)
        res["secs"] += time.time() - t
        if lines is None:
            # «Не знаю» — не то же, что «надписей нет»: такую картинку
            # в сравнение брать нельзя, её называем отдельно.
            res["none"].append(name)
            continue
        res["lines"][name] = lines
        res["blocks"][name] = it.group_blocks(lines)
    it.release_engine()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help=".docx, папка с картинками или одна картинка")
    ap.add_argument("--thresh", default="",
                    help="IMG_BOX_THRESH для режима без чтения (по умолчанию — своё у движка)")
    ap.add_argument("--limit", type=int, default=0, help="сколько картинок брать")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.exists():
        print("нет такого файла: %s" % src)
        return 2
    pics = pictures(src, a.limit)
    if not pics:
        print("картинок не нашлось")
        return 2
    print("картинок: %d" % len(pics))

    import image_text as it
    old = run("full", "", pics, it)
    new = run("det", a.thresh, pics, it)

    print("\n%-28s %7s %7s %7s %7s %7s" %
          ("картинка", "было", "стало", "потер.", "приб.", "блоки"))
    lost_all = gained_all = 0
    for name, _blob in pics:
        was, now = old["lines"].get(name), new["lines"].get(name)
        if was is None or now is None:
            print("%-28s %s" % (name[:28], "посмотреть не удалось"))
            continue
        lost, gained = missing(was, now), missing(now, was)
        lost_all += len(lost)
        gained_all += len(gained)
        print("%-28s %7d %7d %7d %7d %4d/%-4d" %
              (name[:28], len(was), len(now), len(lost), len(gained),
               len(old["blocks"][name]), len(new["blocks"][name])))

    def total(r, key):
        return sum(len(v) for v in r[key].values())

    print("\nстрок:  %d было, %d стало (потеряно %d, прибыло %d)"
          % (total(old, "lines"), total(new, "lines"), lost_all, gained_all))
    print("блоков: %d было, %d стало — столько кропов уходит в платный вызов"
          % (total(old, "blocks"), total(new, "blocks")))
    print("время:  %.1f с было, %.1f с стало (%.2fx)"
          % (old["secs"], new["secs"],
             (old["secs"] / new["secs"]) if new["secs"] else 0.0))
    if old["none"] or new["none"]:
        print("посмотреть не удалось: было %d, стало %d"
              % (len(old["none"]), len(new["none"])))
    print("\nВключать `IMG_DET_ONLY=1` можно, когда потеряно 0. Потеряно больше —"
          "\nподберите `--thresh` (ниже порог — больше рамок) и померьте снова.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
