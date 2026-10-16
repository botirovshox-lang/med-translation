"""Перегруппировка сохранённых блоков картинки по нынешним правилам
(`image_text.regroup_plan`, `main._regroup_rec`, правило «У» в
docs/rules/pdf-reading.md).

Сторожится:
  1. блоки, собранные прежними правилами, склеиваются без детектора и без
     второго чтения: текст склеивается из прочитанного, перенос снимается;
  2. якоря уцелевших сегментов (`origin.block`) идут за новыми номерами —
     иначе перевод отвязался бы и молча выпал из выгрузки;
  3. сегменты склеенных обрывков снимаются, а работа человека не трогается
     вовсе: картинка помечается `groupHeld` и остаётся как была;
  4. отметка `groupRule` ставится, второй заход ничего не делает.

Ни одного вызова модели.
"""
import os
import sys

sys.path.insert(0, "backend")
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
import main                                                   # noqa: E402
import image_text                                             # noqa: E402

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def blk(y, x0=40, x1=760, text=None):
    b = {"box": [x0, y, x1, y + 30], "rows": 1, "lineH": 30, "flat": 0.9,
         "align": "left", "lineBoxes": [[x0, y, x1, y + 30]]}
    if text is not None:
        b["text"] = text
    return b


def page(texts):
    """Заголовок сверху (отдельный блок), под ним абзац рукописи через строку."""
    blocks = [blk(10, 300, 500, "Заголовок")]
    for k, t in enumerate(texts):
        blocks.append(blk(80 + k * 70, 40 + (60 if k == 0 else (k * 7) % 13),
                          160 if k == len(texts) - 1 else 760 - (k * 11) % 25, t))
    return {"part": "word/media/image1.jpeg", "blocks": blocks}


TEXTS = ["Бактериальная клетка устроена", "просто по сравнению с клетками", "других живых организ-",
         "мов. Клетки часто окружает", "капсула, которая служит доме-", "нах."]


def project_for(rec, human=False):
    segs = []
    for i, b in enumerate(rec["blocks"]):
        sid = 100 + i
        b["seg"] = sid
        s = {"id": sid, "source": b.get("text", ""), "target": "t%d" % i, "status": "translated",
             "origin": {"kind": "image", "part": rec["part"], "block": i}}
        if human and i == 3:
            s["status"] = "confirmed"
            s["confirmedBy"] = 1
        segs.append(s)
    return {"id": 1, "segments": segs}


print("\n── план перегруппировки ──")
rec = page(TEXTS)
plan = image_text.regroup_plan(rec["blocks"])
check(plan == [[1, 2, 3, 4, 5, 6]], "шесть строк абзаца — одна группа, заголовок отдельно: %s" % plan)
check(image_text.regroup_plan(page(TEXTS[:3])["blocks"]) == [], "три строки — ритм не доказан")
skipped = page(TEXTS)
skipped["blocks"][3]["skip"] = "overlay"
check(all(3 not in g for g in image_text.regroup_plan(skipped["blocks"])),
      "отсеянный блок в склейку не идёт")

print("\n── перегруппировка записи ──")
rec = page(TEXTS)
proj = project_for(rec)
n = main._regroup_rec(rec, proj, dry=False)
check(n == 1 and len(rec["blocks"]) == 2, "склеен один абзац, блоков стало два: %d" % len(rec["blocks"]))
para = rec["blocks"][1]
check(para["rows"] == 6 and para.get("regrouped") == 6, "у абзаца шесть строк")
check("организмов." in para.get("text", "") and "доменах." in para.get("text", ""),
      "текст склеен из прочитанного, переносы сняты: %r" % para.get("text"))
check(rec.get("groupRule") == image_text.IMG_GROUP_RULE, "отметка правила поставлена")
ids = [s["id"] for s in proj["segments"]]
check(ids == [100], "сегменты обрывков сняты, заголовок остался: %s" % ids)
check(proj["segments"][0]["origin"]["block"] == 0 and rec["blocks"][0].get("seg") == 100,
      "якорь заголовка совпадает с его новым номером")
check(main._regroup_rec(rec, proj, dry=False) == 0, "второй заход ничего не делает")

print("\n── якорь уцелевшего сегмента после склейки ниже ──")
rec2 = page(TEXTS)
rec2["blocks"].append(blk(80 + 6 * 70 + 200, 40, 300, "Подпись"))
proj2 = project_for(rec2)
main._regroup_rec(rec2, proj2, dry=False)
cap = next(s for s in proj2["segments"] if s["id"] == 107)
j = cap["origin"]["block"]
check(rec2["blocks"][j].get("text") == "Подпись",
      "сегмент блока ниже склейки указывает на свой блок (номер %d)" % j)
check(main._image_seg_of({s["id"]: s for s in proj2["segments"]}, rec2["blocks"][j],
                         rec2["part"], j) is cap, "_image_seg_of находит его по новому номеру")

print("\n── работа человека не трогается ──")
rec3 = page(TEXTS)
proj3 = project_for(rec3, human=True)
before = [dict(b) for b in rec3["blocks"]]
check(main._regroup_rec(rec3, proj3, dry=False) == 0 and rec3.get("groupHeld") == 1,
      "заверенный обрывок — картинка оставлена, причина названа")
check(rec3["blocks"] == before and len(proj3["segments"]) == 7, "ни блоки, ни сегменты не тронуты")

print("\n── строка, пропущенная детектором ──")
# Синтетическая тетрадь: светлая клетка, тёмные строки через одну позицию,
# одна строка абзаца нарисована, но детектор её «не видел», и одна позиция
# пустая (граница абзацев).
import numpy as np                                            # noqa: E402
from PIL import Image, ImageDraw                              # noqa: E402
import io as _io                                              # noqa: E402
W, Hh = 800, 1000
img = Image.new("RGB", (W, Hh), (238, 238, 240))
dr = ImageDraw.Draw(img)
for x in range(0, W, 25):
    dr.line([(x, 0), (x, Hh)], fill=(200, 205, 215))
for y in range(0, Hh, 25):
    dr.line([(0, y), (W, y)], fill=(200, 205, 215))
tops = [40 + k * 60 for k in range(12)]
empty = 6                                     # пустая позиция между абзацами
missed = 9                                    # строка с краской, которую «не нашли»
for k, t in enumerate(tops):
    if k == empty:
        continue
    for x in range(60, 740, 14):
        dr.rectangle([x, t + 8, x + 9, t + 30], fill=(40, 40, 50))
found = [[60, t, 740, t + 36] for k, t in enumerate(tops) if k not in (empty, missed)]
gaps = image_text.rhythm_gaps(np.asarray(img), found)
check(len(gaps) == 1 and abs(gaps[0][1] - tops[missed]) <= 6,
      "строка с краской найдена на своём месте, пустая позиция — нет: %s" % gaps)
check(image_text.rhythm_gaps(np.asarray(img), found[:4]) == [], "мало строк — правило молчит")

buf = _io.BytesIO()
img.save(buf, "PNG")
rec5 = {"part": "word/media/image9.png",
        "blocks": [dict(blk(t, 60, 740, "строка %d" % k), lineBoxes=[[60, t, 740, t + 36]],
                        box=[60, t, 740, t + 36], lineH=36, hand=True)
                   for k, t in enumerate(tops) if k not in (empty, missed)]}
proj5 = {"id": 5, "segments": []}
main._regroup_rec(rec5, proj5, dry=False, blob=buf.getvalue())
rows = sorted(b["rows"] for b in rec5["blocks"])
check(rows == [5, 6], "абзацы собраны вместе с найденной строкой: %s" % rows)
second = max(rec5["blocks"], key=lambda b: b["box"][1])
check("text" not in second, "абзац с непрочитанной строкой ждёт чтения целиком")
printed = {"part": "p", "blocks": [dict(b, hand=False) for b in rec5["blocks"]]}
check(not main._gaps_allowed(printed), "печатная страница — пропуски не ищутся")
layer = {"part": "p", "blocks": [dict(b) for b in rec5["blocks"]] + [{"box": [0, 0, 5, 5], "skip": "layer"}]}
check(not main._gaps_allowed(layer), "страница PDF со слоем — пропуски не ищутся")

print("\n── текст, исправленный человеком, — в блок картинки ──")
src_dir = main.SOURCE_DIR
import tempfile, pathlib                                      # noqa: E402
main.SOURCE_DIR = pathlib.Path(tempfile.mkdtemp())
(main.SOURCE_DIR / "77.docx").write_bytes(b"x")
pj = {"id": 77, "sourceDocx": {"at": "x"}, "segments": [
    {"id": 3, "source": "ры не имеют", "origin": {"kind": "image", "part": "p", "block": 0}}]}
main._save_source_map(77, {"images": [{"part": "p", "blocks": [{"box": [0, 0, 9, 9], "seg": 3, "text": "ры не имеют"}]}]})
check(main._image_block_text(pj, pj["segments"][0], "рии не имеют"), "блок найден по якорю")
b0 = main._load_source_map(77)["images"][0]["blocks"][0]
check(b0["text"] == "рии не имеют" and b0["textBy"] == "human", "текст и след человека в карте")
main.SOURCE_DIR = src_dir

print("\n── сухой заход ничего не пишет ──")
rec4 = page(TEXTS)
proj4 = project_for(rec4)
check(main._regroup_rec(rec4, proj4, dry=True) == 1 and len(rec4["blocks"]) == 7
      and "groupRule" not in rec4, "сухой заход только считает")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
