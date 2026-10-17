"""Карусель «Фото» на click.simpletranslate.me/start/ — картинки от системы.

Каждый слайд — исходник и его переводы, перерисованные тем же
`image_text.render_target`, что и выгрузка «в исходном виде»: признаки
блоков (рамки строк, рукопись, засечки) и рамки всех надписей берутся из
карты исходника так же, как в `main._export_images`. В базу и в STATE
ничего не пишется — только читается; моделей не зовёт.

Запуск на сервере (там есть raqm — без него арабский и индийские письма
выходят несвязанными буквами):

    bash tools/prod_run.sh tools/landing_photo.py

Результат — /root/landing-media/out/photo/<слайд>-<язык>.webp; затем
скопировать в landing/start/media/ (scp) и закоммитить.
Плитки «Книги» и «Сканы» на той же странице берут эти же картинки
(`data-img` у плитки): своей копии у них нет — она отставала от правил.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

APP = Path("/opt/med-translation")
sys.path.insert(0, str(APP / "backend"))
import image_text  # noqa: E402
from PIL import Image  # noqa: E402

OUT = Path("/root/landing-media/out/photo")
OUT.mkdir(parents=True, exist_ok=True)
SRC = APP / "backend" / "data" / "sources"
WIDTH = 1000          # как у прочих картинок /start/
HAND_SHARE = 0.5      # = main.IMG_HAND_SHARE

# Слайд → {язык перевода: проект}. Исходник берётся у первого проекта.
SLIDES = {
    # Конспект — проект 90 (служебная организация, оригинал сверен по фото,
    # `tools/landing_note.py`); у владельца тот же файл — проект 89.
    "note": {"en": 90},
    "typed": {"en": 78, "uz": 79, "zh": 80, "kk": 81, "ar": 82},
    "book": {"en": 83, "uz": 84, "zh": 85, "kk": 86, "ar": 87},
    "paper": {"uz": 74, "zh": 75, "kk": 76, "ar": 77},
}


def doc(key):
    out = subprocess.run(["sudo", "-u", "postgres", "psql", "-p", "5433", "medcat", "-At", "-c",
                          "select doc from state_docs where key='%s'" % key],
                         capture_output=True, text=True, check=True).stdout.strip()
    return json.loads(out) if out else None


def hand_image(im):
    tot = hand = 0.0
    for b in im.get("blocks") or []:
        if b.get("skip") or not b.get("box"):
            continue
        x0, y0, x1, y1 = b["box"]
        a = max(0, x1 - x0) * max(0, y1 - y0)
        tot += a
        hand += a if b.get("hand") else 0.0
    return tot > 0 and hand >= HAND_SHARE * tot


def webp(img_bytes, path):
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if im.width > WIDTH:
        im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    im.save(path, "WEBP", quality=82, method=6)
    return im.size


def render(pid):
    proj = doc("projects:%d" % pid)
    data = json.loads((SRC / ("%d.json" % pid)).read_text(encoding="utf-8"))
    orig = sorted(SRC.glob("%d.orig.*" % pid))[0].read_bytes()
    by = {s["id"]: s for s in proj["segments"]}
    im = data["images"][0]
    fam = "hand" if hand_image(im) else ""
    items = []
    for i, b in enumerate(im.get("blocks") or []):
        if b.get("skip"):
            continue
        s = by.get(b.get("seg"))
        o = (s or {}).get("origin") or {}
        if not s or o.get("block") != i or not (s.get("target") or "").strip():
            continue
        items.append({"box": b["box"], "text": s["target"].strip(), "align": b.get("align"),
                      "lineH": b.get("lineH"), "rows": b.get("rows"),
                      "lineBoxes": b.get("lineBoxes"),
                      "fam": fam or ("serif" if b.get("serif") else ""),
                      "src": (s.get("source") or "").strip()})
    obst = [list(b["box"]) for b in im.get("blocks") or [] if b.get("box") and (b.get("text") or "").strip()]
    out, rep = image_text.render_target(orig, items, obstacles=obst)
    return orig, out, rep


for slide, langs in SLIDES.items():
    first = True
    for lang, pid in langs.items():
        orig, out, rep = render(pid)
        if first:
            src_lang = (doc("projects:%d" % pid) or {}).get("src", "src").lower()
            print(slide, "orig", src_lang, webp(orig, OUT / ("%s-%s.webp" % (slide, src_lang))))
            first = False
        if out is None:
            print("!", slide, lang, "не перерисовано", rep)
            continue
        print(slide, lang, pid, webp(out, OUT / ("%s-%s.webp" % (slide, lang))),
              [{k: r.get(k) for k in ("ok", "fam", "erase", "over", "why")} for r in rep])
print("готово", OUT)
