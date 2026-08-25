"""Текст, впечатанный в картинку: поиск строк, сборка в блоки, перерисовка.

Что здесь сторожится:

  1. посмотреть не удалось — это «не знаю» (None), а не «надписей нет»
     (пустой список): молчаливый ноль означал бы, что в схеме нет подписей;
  2. строки собираются в БЛОКИ: подпись из четырёх строк с переносами —
     одно предложение, а не четыре обрубка, иначе и перевод, и глоссарий,
     и проверки работают по мусору. Разбиение не должно меняться от дрожания
     детектора на пиксель;
  3. на пёстром фоне не перерисовываем НИЧЕГО и байты картинки не трогаем:
     заплатка поверх рентгенограммы — порча документа;
  4. ПИКСЕЛИ результата: прежняя надпись стёрта, перевод лежит внутри своей
     рамки, краска тёмная на светлом фоне и светлая на тёмном. Без этих
     проверок тест проходил, даже если убрать заливку совсем, забыть масштаб
     или всегда писать белым;
  5. заливка соседнего блока не стирает уже написанный перевод: рамки блоков
     законно пересекаются;
  6. формат части пакета сохраняется вместе с EXIF, профилем цвета
     и разрешением: без EXIF фотография ляжет боком, а PNG вместо JPEG
     сделает .docx невалидным;
  7. прозрачность не теряется и не превращается в белый текст по прозрачному;
  8. рамка, вылезшая за край картинки, отклоняется, а не прижимается к углу;
  9. перевод, который не влезает читаемым кеглем, НЕ пишется: он уйдёт
     подписью под картинкой;
 10. шрифт лежит файлом в репозитории — без него перерисовка невозможна.

Ни одного вызова модели и ни одного обращения к сети.
"""
import io
import os
import sys

sys.path.insert(0, "backend")
import image_text as it                                       # noqa: E402
import numpy as np                                            # noqa: E402
from PIL import Image, ImageDraw, ImageFont                   # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def png(im) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def jpeg(im, **kw) -> bytes:
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=92, **kw)
    return b.getvalue()


def line(x0, y0, x1, y1, conf=0.9, flat=0.9) -> dict:
    return {"box": [x0, y0, x1, y1], "conf": conf, "flat": flat}


def ink_mask(data: bytes, box=None, dark=True):
    """Маска «здесь краска». Единственный способ проверить, что перевод
    действительно нарисован, а прежняя надпись действительно стёрта:
    по отчёту `ok` этого не видно."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    a = np.asarray(im).astype(int).mean(axis=2)
    m = a < 128 if dark else a > 200
    if box:
        keep = np.zeros_like(m)
        keep[box[1]:box[3], box[0]:box[2]] = True
        m = m & keep
    return m


print("\n── шрифт и отбор строк ──")
check(it.font_path() is not None, "шрифт для перерисовки найден")
check(it.is_noise("a") and it.is_noise("25.03.2008") and it.is_noise("  "),
      "метка, дата и пустая строка — не текст документа")
check(it.is_noise("250MA") and it.is_noise("kV 120"),
      "настройки аппарата отсеиваются: букв в них меньше трёх")
# «10mm/div» этим правилом не ловится и не должно: букв там пять. Надпечатку
# целиком отсеивает признак overlay, который ставит модель при чтении, —
# правило о буквах закрывает только то, что видно без всякой модели.
check(not it.is_noise("10mm/div"), "правило о буквах не притворяется умнее, чем оно есть")
check(not it.is_noise("Рис. 174") and not it.is_noise("МБТ"),
      "настоящая подпись и аббревиатура шумом не считаются")

print("\n── сборка строк в блоки ──")
cap = [line(20, 100, 400, 118), line(20, 120, 400, 138),
       line(20, 140, 400, 158), line(20, 160, 300, 178)]
blocks = it.group_blocks(cap)
check(len(blocks) == 1 and blocks[0]["rows"] == 4,
      "четыре строки подписи — один блок")
check(blocks[0]["box"] == [20, 100, 400, 178], "рамка блока накрывает все строки")
check(abs(blocks[0]["lineH"] - 18) <= 1,
      "у блока записана высота СТРОКИ (%s), а не блока" % blocks[0]["lineH"])

two = [line(10, 10, 100, 26), line(10, 30, 100, 46),
       line(300, 10, 390, 26), line(300, 30, 390, 46)]
check(len(it.group_blocks(two)) == 2, "две колонки — два блока")
check(len(it.group_blocks([line(10, 10, 200, 44), line(10, 50, 200, 64)])) == 2,
      "разный кегль — разные блоки")
check(len(it.group_blocks([line(10, 10, 200, 26), line(10, 300, 200, 316)])) == 2,
      "строки через полкартинки — разные блоки")

cen = [line(50, 10, 350, 26), line(100, 30, 300, 46), line(30, 50, 370, 66)]
check(it.group_blocks(cen)[0]["align"] == "center", "центрованный блок опознан")
check(it.group_blocks(cap)[0]["align"] == "left", "выключенный влево опознан")
right = [line(200, 10, 400, 26), line(120, 30, 400, 46), line(260, 50, 400, 66)]
check(it.group_blocks(right)[0]["align"] == "right", "выключенный вправо опознан")

# Заголовок во всю ширину над двумя колонками. Разбиение обязано быть
# устойчивым: детектор ставит рамки с точностью до пикселя, и от того, какая
# колонка оказалась выше на один, состав блоков меняться не имеет права —
# иначе модель получит склейку из заголовка и двух разных колонок.
def cols(shift):
    return [line(0, 0, 400, 20),
            line(0, 25, 180, 45), line(0, 50, 180, 70),
            line(220, 25 + shift, 400, 45 + shift),
            line(220, 50 + shift, 400, 70 + shift)]


shapes = [sorted(b["rows"] for b in it.group_blocks(cols(sh))) for sh in (0, -1, 1)]
check(shapes[0] == shapes[1] == shapes[2] == [2, 3],
      "сдвиг колонки на пиксель не меняет состав блоков: %s" % shapes)
# Заголовок во всю ширину законно прилипает к одной из колонок — это тот же
# текст. А вот блок из ДВУХ колонок сразу — склейка разных текстов, и видно
# её по ширине: колонка вдвое уже страницы.
for sh in (0, -1, 1):
    two_row = [b for b in it.group_blocks(cols(sh)) if b["rows"] == 2]
    check(all(b["box"][2] - b["box"][0] <= 200 for b in two_row),
          "колонки не склеены между собой (сдвиг %d): %s" % (sh, [b["box"] for b in two_row]))

mixed = [line(20, 100, 400, 118, conf=0.9, flat=0.9),
         line(20, 120, 400, 138, conf=0.4, flat=0.2)]
b = it.group_blocks(mixed)[0]
check(b["conf"] == 0.4 and b["flat"] == 0.2, "у блока берётся худшая строка")

print("\n── плоскость фона ──")
white = np.full((60, 400, 3), 255, dtype=np.uint8)
check(it.flatness(white, [0, 0, 400, 60]) > 0.99, "белый лист — плоский")
noise = (np.random.RandomState(7).rand(60, 400, 3) * 255).astype(np.uint8)
check(it.flatness(noise, [0, 0, 400, 60]) < 0.2, "шум — не плоский")
check(it.flatness(white, [0, 0, 0, 0]) == 0.0, "пустая рамка — ноль, а не срыв")

print("\n── цвет заливки и краски ──")
BOX = [14, 88, 392, 134]
big_font = ImageFont.truetype(it.font_path(), 26)


def with_text(bg, fg, mode="RGB"):
    im = Image.new(mode, (400, 200), bg)
    ImageDraw.Draw(im).text((20, 94), "Клиника туберкулёза", fill=fg, font=big_font)
    return im


light = np.asarray(with_text("white", (0, 0, 0)))
fill, ink = it._fill_and_ink(light, BOX)
check(sum(fill) > 700 and sum(ink) < 200,
      "на белом фоне заливка белая, краска тёмная: %s / %s" % (fill, ink))
dark = np.asarray(with_text("black", (255, 255, 255)))
fill2, ink2 = it._fill_and_ink(dark, BOX)
check(sum(fill2) < 60 and sum(ink2) > 700,
      "на чёрном фоне заливка чёрная, краска светлая: %s / %s" % (fill2, ink2))

# Прозрачный фон в PNG хранит ЧЁРНЫЙ цвет. Анализ по сырым каналам объявлял
# такой фон тёмным и выбирал белую краску — перевод получался белым
# по прозрачному, то есть невидимым, с отчётом «написано».
tr = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
ImageDraw.Draw(tr).text((20, 94), "Схема", fill=(0, 0, 0, 255), font=big_font)
fill3, ink3 = it._fill_and_ink(np.asarray(tr), BOX)
check(fill3[3] == 0 and sum(ink3[:3]) < 200,
      "прозрачный фон остаётся прозрачным, краска тёмная: %s / %s" % (fill3, ink3))

print("\n── перерисовка: пиксели, а не отчёт ──")
src = png(with_text("white", (0, 0, 0)))
before = ink_mask(src, BOX).sum()
new, rep = it.render_target(src, [{"box": BOX, "text": "Clinic", "lineH": 26}])
check(new is not None and rep[0]["ok"], "на белом фоне перевод пишется")
k = 2
# Рамка плюс поле: стираем и пишем чуть шире найденного, иначе от букв
# остаётся серая кайма сглаживания. Допуск здесь именно на поле, а не «на
# всякий случай»: забытый масштаб увёл бы текст в четверть картинки.
sbox = [(BOX[0] - 10) * k, (BOX[1] - 10) * k, (BOX[2] + 10) * k, (BOX[3] + 10) * k]
after_all = ink_mask(new).sum()
after_box = ink_mask(new, sbox).sum()
check(after_all == after_box,
      "вся краска перевода лежит внутри рамки: %d из %d" % (after_box, after_all))

# Прежняя надпись стёрта. Перевод берём заведомо коротким: если заливку убрать,
# под ним останутся буквы оригинала, и краски будет втрое больше.
dot, dot_rep = it.render_target(src, [{"box": BOX, "text": ".", "lineH": 26}])
dot_ink = ink_mask(dot, sbox).sum()
check(dot_rep[0]["ok"] and 0 < dot_ink < before * k * k * 0.25,
      "прежняя надпись стёрта, а не осталась под переводом: было %d, стало %d"
      % (before * k * k, dot_ink))
check(Image.open(io.BytesIO(new)).size == (800, 400),
      "мелкий текст увеличен вдвое — экранный размер задают extent'ы")

# Крупному тексту увеличение не нужно: файл растёт вчетверо просто так.
tall = png(with_text("white", (0, 0, 0)))
big_new, big_rep = it.render_target(tall, [{"box": [10, 40, 390, 160], "text": "Clinic",
                                            "lineH": 110}])
check(big_rep[0]["ok"] and Image.open(io.BytesIO(big_new)).size == (400, 200),
      "крупный текст не увеличивается")

# Краска на тёмном фоне обязана быть светлой, иначе перевод не виден.
dsrc = png(with_text("black", (255, 255, 255)))
dnew, drep = it.render_target(dsrc, [{"box": BOX, "text": "Clinic", "lineH": 26}])
check(drep[0]["ok"] and ink_mask(dnew, [v * 2 for v in BOX], dark=False).sum() > 200,
      "на чёрном фоне перевод написан светлым")

print("\n── соседние блоки ──")
# Рамки блоков законно пересекаются (заголовок над колонками). Заливка второго
# не имеет права стереть уже написанный перевод первого.
wide = [12, 40, 388, 150]
strip = [12, 80, 388, 110]
alone = it.render_target(src, [{"box": wide, "text": "Alpha beta gamma delta epsilon "
                                                     "zeta eta theta", "lineH": 22}])
pair = it.render_target(src, [{"box": wide, "text": "Alpha beta gamma delta epsilon "
                                                    "zeta eta theta", "lineH": 22},
                              {"box": strip, "text": "hi", "lineH": 26}])
alone_ink = ink_mask(alone[0], [v * 2 for v in wide]).sum()
pair_ink = ink_mask(pair[0], [v * 2 for v in wide]).sum()
check(pair[1][0]["ok"] and pair[1][1]["ok"], "оба блока отчитались как написанные")
check(pair_ink >= alone_ink,
      "перевод первого блока не стёрт заливкой второго: %d против %d"
      % (pair_ink, alone_ink))

print("\n── отказы ──")
ph = Image.fromarray(noise.repeat(4, axis=0)[:200, :400])
new2, rep2 = it.render_target(png(ph), [{"box": BOX, "text": "Anything"}])
check(new2 is None and rep2[0]["why"] == "flat",
      "на пёстром фоне не перерисовываем и причину называем")
new3, rep3 = it.render_target(src, [{"box": BOX, "text": "   "}])
check(new3 is None and rep3[0]["why"] == "empty",
      "пустой перевод оставляет оригинал на месте")
long_text = "Extensively drug-resistant pulmonary tuberculosis with cavitation " * 3
new4, rep4 = it.render_target(src, [{"box": [18, 96, 120, 106], "text": long_text}])
check(new4 is None and rep4[0]["why"] == "tiny_font",
      "нечитаемый кегль не пишется: " + str(rep4[0]))
# Рамка за краем картинки: _clip прижал бы её к углу, и перевод встал бы
# в случайном месте с отчётом «готово».
new5, rep5 = it.render_target(src, [{"box": [340, 160, 900, 700], "text": "Overflow"}])
check(new5 is None and rep5[0]["why"] == "outside",
      "рамка за краем картинки отклонена: " + str(rep5[0]))
webp = io.BytesIO()
with_text("white", (0, 0, 0)).save(webp, "WEBP")
new6, rep6 = it.render_target(webp.getvalue(), [{"box": BOX, "text": "x"}])
check(new6 is None and rep6[0]["why"].startswith("format:"),
      "незнакомый формат отклонён: " + rep6[0]["why"])
check(it.render_target(b"garbage", [{"box": BOX, "text": "x"}])[1][0]["why"].startswith("open:"),
      "битые байты отклонены с причиной")
check(it.render_target(src, []) == (None, []), "пустой список блоков — не срыв")

print("\n── формат и его потроха ──")
exif = Image.Exif()
exif[274] = 6                       # Orientation: Word покажет фото повёрнутым
jsrc = jpeg(with_text("white", (0, 0, 0)), exif=exif.tobytes(), dpi=(300, 300))
jnew, jrep = it.render_target(jsrc, [{"box": BOX, "text": "Clinic", "lineH": 26}])
out = Image.open(io.BytesIO(jnew))
check(jrep[0]["ok"] and out.format == "JPEG", "JPEG остаётся JPEG")
check(out.getexif().get(274) == 6, "EXIF-ориентация сохранена — иначе фото ляжет боком")
check(out.info.get("dpi", (0, 0))[0] == 300, "разрешение сохранено")
check(Image.open(io.BytesIO(new)).format == "PNG", "PNG остаётся PNG")

# Палитровая схема обязана остаться палитровой: RGB — это пятикратный вес
# на ровном месте, а в учебнике таких картинок семьдесят.
pal = with_text("white", (0, 0, 0)).quantize(colors=64)
psrc = png(pal)
pnew, prep = it.render_target(psrc, [{"box": BOX, "text": "Clinic", "lineH": 26}])
check(prep[0]["ok"] and Image.open(io.BytesIO(pnew)).mode == "P",
      "палитровый PNG остаётся палитровым")
check(len(pnew) < len(psrc) * 8,
      "вес палитровой картинки не взлетает: %d → %d" % (len(psrc), len(pnew)))

rgba_new, rgba_rep = it.render_target(png(tr), [{"box": BOX, "text": "Scheme", "lineH": 26}])
check(rgba_rep[0]["ok"] and Image.open(io.BytesIO(rgba_new)).mode == "RGBA",
      "альфа-канал переживает перерисовку")
check(ink_mask(rgba_new, [v * 2 for v in BOX]).sum() > 100,
      "на прозрачном фоне перевод написан ТЁМНЫМ, а не белым по пустому")

# Анимация и прозрачность в GIF: схлопнуть кадры и залить прозрачное чёрным —
# это порча картинки, поэтому такой блок уходит подписью.
gif = io.BytesIO()
pal.save(gif, "GIF", transparency=0)
gnew, grep = it.render_target(gif.getvalue(), [{"box": BOX, "text": "x"}])
check(gnew is None and grep[0]["why"] == "format:GIF-special",
      "GIF с прозрачностью отклонён: " + str(grep[0]["why"]))

print("\n── перенос строк ──")
dr = ImageDraw.Draw(Image.new("RGB", (10, 10)))
font = ImageFont.truetype(it.font_path(), 20)
rows = it._wrap(dr, "Mycobacterium tuberculosis complex резистентность", font, 200)
check(all(dr.textlength(r, font=font) <= 200 for r in rows),
      "ни одна строка не вылезает за рамку")
check(" ".join(rows).replace(" ", "") ==
      "Mycobacterium tuberculosis complex резистентность".replace(" ", ""),
      "при переносе не теряется и не задваивается ни буквы")
one = it._wrap(dr, "Pneumonoultramicroscopicsilicovolcanoconiosis", font, 60)
check(len(one) > 1 and all(dr.textlength(r, font=font) <= 60 for r in one),
      "слово длиннее рамки режется, а не вылезает")

print("\n── кроп для человека и для модели ──")
c = it.crop(src, BOX, line_h=26)
check(c is not None and Image.open(io.BytesIO(c)).format == "PNG", "кроп отдаётся PNG")
cw, ch = Image.open(io.BytesIO(c)).size
check(cw > BOX[2] - BOX[0] and ch > BOX[3] - BOX[1],
      "у кропа есть поля — иначе буквы обрезаны")
tall_block = [20, 40, 380, 160]      # шесть строк
c2 = Image.open(io.BytesIO(it.crop(src, tall_block, line_h=20))).size
c3 = Image.open(io.BytesIO(it.crop(src, tall_block))).size
check(c2[1] < c3[1],
      "поле кропа считается от строки, а не от блока: %s против %s" % (c2, c3))
check(it.crop(src, [0, 0, 0, 0]) is None, "вырожденная рамка кропа — None, а не срыв")
check(it.crop(b"not an image", [0, 0, 10, 10]) is None, "мусор вместо картинки — None")

print("\n── движок поиска строк ──")
ready, why = it.engine_ready()
if ready:
    found = it.detect_lines(src)
    check(found is not None and any(l["box"][1] < 130 for l in (found or [])),
          "надпись на картинке найдена: %s" % (found or []))
    check(it.detect_lines(b"not an image") is None,
          "нечитаемая картинка — «не знаю», а не «надписей нет»")
else:
    check(it.detect_lines(src) is None,
          "движка нет (%s) — detect_lines возвращает None, а не пустоту" % why)

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
