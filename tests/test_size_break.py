"""Х19: строка другого размера в конце блока — разрыв строки при чтении.

Что сторожится:
  1. `image_text.size_break` видит последнюю строку, мельче остальных по
     высоте строчных (авторы под заголовком), и молчит на ровном абзаце,
     на одной строке и на тексте одного размера;
  2. чтение отправляет последнюю строку отдельной вырезкой под номером
     после всех блоков и склеивает текст через «\\n»; число блоков то же;
  3. перевод просит сохранить разрывы ТОЛЬКО когда они есть в оригинале
     (у остальных промпт байт в байт прежний);
  4. раскраска делит блок по последнему «\\n» (`tail_by_break`) прежде
     дословного хвоста и номеров — это и закрывает китайский без номеров.

Ни одного вызова модели: клиент подменён.
"""
import io
import json
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main                                                   # noqa: E402
import image_text                                             # noqa: E402
import text_paint as tp                                       # noqa: E402
import numpy as np                                            # noqa: E402
from PIL import Image, ImageDraw, ImageFont                   # noqa: E402

main.save_state = lambda *a, **k: None
SUB = "frontend/vendor/fonts/sub/"
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def page(lines):
    """[(текст, шрифт, кегль)] сверху вниз → (png, рамки строк)."""
    im = Image.new("RGB", (1500, 60 + 70 * len(lines)), (250, 250, 250))
    dr = ImageDraw.Draw(im)
    y, boxes = 20, []
    for t, f, s in lines:
        ft = ImageFont.truetype(SUB + f, s)
        dr.text((20, y), t, font=ft, fill=(30, 30, 30))
        boxes.append(list(dr.textbbox((20, y), t, font=ft)))
        y += int(s * 1.45)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), boxes


def block(boxes):
    return {"box": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                    max(b[3] for b in boxes)], "rows": len(boxes), "lineBoxes": boxes,
            "lineH": int(np.median([b[3] - b[1] for b in boxes]))}


def arr_of(png):
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


print("── 1. размер последней строки ──")
HEAD = ["Sleep quality, duration, and consistency are associated with",
        "better academic performance in college students"]
AUTH = "Kana Okano, Jakub R. Kaczmarzyk, Neha Dave, John D. E. Gabrieli and Jeffrey C. Grossman"
png, bx = page([(HEAD[0], "NotoSerif-Regular.ttf", 44), (HEAD[1], "NotoSerif-Regular.ttf", 44),
                (AUTH, "NotoSans-Regular.ttf", 22)])
check(image_text.size_break(arr_of(png), block(bx)), "заголовок + мелкие авторы — разрыв")
png2, bx2 = page([(HEAD[0], "NotoSerif-Regular.ttf", 30), (HEAD[1], "NotoSerif-Regular.ttf", 30),
                  ("in the third line of the same paragraph", "NotoSerif-Regular.ttf", 30)])
check(not image_text.size_break(arr_of(png2), block(bx2)), "ровный абзац — разрыва нет")
check(not image_text.size_break(arr_of(png2), block(bx2[:1])), "одна строка — разрыва нет")
png3, bx3 = page([(HEAD[0], "NotoSerif-Regular.ttf", 30), ("last line, slightly smaller", "NotoSerif-Regular.ttf", 26)])
check(not image_text.size_break(arr_of(png3), block(bx3)), "разница меньше порога — разрыва нет")
_old = image_text.IMG_READ_SIZE_BREAK
image_text.IMG_READ_SIZE_BREAK = False
check(not image_text.size_break(arr_of(png), block(bx)), "выключатель IMG_READ_SIZE_BREAK=0")
image_text.IMG_READ_SIZE_BREAK = _old

print("\n── 2. чтение: последняя строка отдельной вырезкой ──")
sent = []


class _Resp:
    def __init__(self, raw):
        m = type("M", (), {"content": raw})()
        self.choices = [type("C", (), {"message": m, "finish_reason": "stop"})()]
        self.usage = None


class _Client:
    def __init__(self, answer):
        self.answer = answer
        self.chat = type("Ch", (), {"completions": self})()

    def create(self, **kw):
        sent.append(kw)
        return _Resp(self.answer(kw))


def answer_read(kw):
    labels = [c["text"] for c in kw["messages"][1]["content"] if c.get("type") == "text"]
    nums = [int(t.split()[1].rstrip(":")) for t in labels if t.startswith("Block ")]
    texts = {0: " ".join(HEAD), 1: AUTH}
    out = [{"i": n, "text": texts.get(1 if n >= 1 else 0, ""), "overlay": False, "hand": False,
            "serif": True} for n in nums]
    return json.dumps({"blocks": out})


_lc = main._llm_client
main._llm_client = lambda *a, **k: _Client(answer_read)
main._note_usage = lambda *a, **k: None
try:
    got = main._openai_read_image(png, [block(bx)], "EN")
finally:
    main._llm_client = _lc
labels = [c["text"] for c in sent[-1]["messages"][1]["content"] if c.get("type") == "text"]
check("Block 0:" in labels and "Block 1:" in labels, "вырезки: блок и его последняя строка (%s)" % labels)
check(got and len(got) == 1 and got[0]["text"] == " ".join(HEAD) + "\n" + AUTH and got[0].get("sizeBreak"),
      "текст склеен через перевод строки: %r" % (got and got[0]["text"]))
sent.clear()
main._llm_client = lambda *a, **k: _Client(answer_read)
try:
    got2 = main._openai_read_image(png2, [block(bx2)], "EN")
finally:
    main._llm_client = _lc
labels2 = [c["text"] for c in sent[-1]["messages"][1]["content"] if c.get("type") == "text"]
check("Block 1:" not in labels2 and got2 and "\n" not in got2[0]["text"], "ровный абзац читается как прежде")

print("\n── 3. перевод держит разрывы ──")
seen = []


def answer_tr(kw):
    seen.append(kw["messages"][0]["content"])
    return "ok"


main._llm_client = lambda *a, **k: _Client(answer_tr)
try:
    main._openai_translate("Title\nAuthors", "EN", "ZH")
    main._openai_translate("Title Authors", "EN", "ZH")
    main._openai_translate("Title\nAuthors", "ZH", "EN", literal=True)
finally:
    main._llm_client = _lc
check("LINE BREAKS" in seen[0] and "1 line break" in seen[0], "в оригинале разрыв — промпт просит его сохранить")
check("LINE BREAKS" not in seen[1], "без разрыва промпт прежний")
check("LINE BREAKS" not in seen[2], "обратный перевод не трогаем")

print("\n── 4. раскраска режет по разрыву ──")
SRC = " ".join(HEAD) + "\n" + AUTH
ZH = "睡眠质量、时长和规律性与大学生更好的学业表现相关\n冈野加奈、雅各布·R.·卡奇马日克、内哈·戴夫、约翰·D.·E.·加布里埃利和杰弗里·C.·格罗斯曼"
c = tp.tail_by_break(ZH, SRC)
check(c and ZH[c[0]:].startswith("冈野") and SRC[c[1]:].startswith("Kana"), "китайский без номеров делится: %s" % (c,))
check(tp.tail_by_break(ZH.replace("\n", ""), SRC) is None, "перевод потерял разрыв — не делим")
check(tp.tail_by_break(ZH, SRC.replace("\n", " ")) is None, "в оригинале разрыва нет — не делим")
sp = tp.size_split([(0, 50), (60, 100), (110, 130)], ZH, SRC)
check(sp and sp[1][1].startswith("冈野") and "\n" not in sp[1][0], "участки по разрыву: %s" % (sp and sp[1]))
check(main._norm_key("A\nB") == main._norm_key("A B"), "ключ памяти переводов разрыва не различает")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    sys.exit(1)
print("ВСЁ ПРОШЛО")
