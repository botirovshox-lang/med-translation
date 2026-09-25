"""Каталог шрифтов для субтитров в кадре: frontend/vendor/fonts/sub/fonts.json.

Шрифты лежат ОДНИМИ файлами на две работы: ffmpeg (libass) впечатывает ими
текст в видео, а браузер берёт те же файлы для предпросмотра в редакторе.
Поэтому показанное совпадает с полученным, а не «примерно похоже».

Что считается здесь, а не пишется руками:
  * какие ПИСЬМЕННОСТИ шрифт покрывает — по таблице символов самого файла.
    Письменность языка берётся из backend/languages.json (`script`), и экран
    говорит «в этом шрифте нет букв вашего языка» по этому списку. Список
    руками разошёлся бы с файлом при первой замене шрифта: PT Sans, например,
    не знает узбекского «ʻ», и на субтитрах вместо буквы стоял бы квадрат;
  * `emRatio` — во сколько раз кегль ASS больше CSS-кегля того же шрифта.
    libass берёт размер как высоту `usWinAscent + usWinDescent` (так делал
    VSFilter), а браузер — как em. Без поправки предпросмотр DejaVu был бы
    на треть крупнее впечатанного.

Запуск: python tools/sub_fonts.py   (нужен fontTools: pip install fonttools)
"""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "frontend" / "vendor" / "fonts" / "sub"

FONTS = [
    {"id": "noto-sans", "name": "Noto Sans", "regular": "NotoSans-Regular.ttf", "bold": "NotoSans-Bold.ttf",
     "license": "OFL-Noto.txt"},
    {"id": "dejavu-sans", "name": "DejaVu Sans", "regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf",
     "license": "LICENSE-DejaVu.txt"},
    {"id": "noto-serif", "name": "Noto Serif", "regular": "NotoSerif-Regular.ttf", "bold": "NotoSerif-Bold.ttf",
     "license": "OFL-Noto.txt"},
]


def _rng(a, b):
    return [chr(c) for c in range(a, b + 1)]


# Проба письменности: буквы, без которых язык этой письменности
# на экране ломается. У европейских — все буквы расширенных блоков
# (узбекское «ʻ», азербайджанское «ə», вьетнамские знаки), у прочих —
# горсть основных: ни один шрифт каталога их не покрывает, и ответ «нет»
# от этого не изменится.
PROBES = {
    "LATIN": _rng(0x41, 0x5A) + _rng(0x61, 0x7A) + [c for c in _rng(0xC0, 0xFF) if c not in "×÷"]
             + _rng(0x100, 0x17F) + list("ȘșȚțƏəƠơƯưʻʼ") + _rng(0x1EA0, 0x1EF9),
    "CYRILLIC": _rng(0x400, 0x45F) + list("ҐґҒғҚқҢңҮүҰұҲҳҺһӘәӨөӮӯӢӣҶҷ"),
    "GREEK": [c for c in _rng(0x391, 0x3A9) if c != "΢"] + _rng(0x3B1, 0x3C9) + list("ΆΈΉΊΌΎΏάέήίόύώ"),
    "ARMENIAN": _rng(0x531, 0x556) + _rng(0x561, 0x586),
    "GEORGIAN": _rng(0x10D0, 0x10F0),
    "HEBREW": _rng(0x5D0, 0x5EA),
    "ARABIC": _rng(0x621, 0x63A) + _rng(0x641, 0x64A) + list("پچژگکیٹڈڑںہھےۃ"),
    "DEVANAGARI": list("अआइकखगघचजटडतदनपबमयरलवसह"),
    "BENGALI": list("অআইকখগচজটডতদনপবমযরলসহ"),
    "GUJARATI": list("અઆઇકખગચજટડતદનપબમયરલસહ"),
    "GURMUKHI": list("ਅਆਇਕਖਗਚਜਟਡਤਦਨਪਬਮਯਰਲਸਹ"),
    "TAMIL": list("அஆஇகஙசஞடணதநபமயரலவ"),
    "TELUGU": list("అఆఇకఖగచజటడతదనపబమయరలవసహ"),
    "THAI": _rng(0xE01, 0xE2E),
    "KHMER": _rng(0x1780, 0x17A2),
    "MYANMAR": _rng(0x1000, 0x1020),
    "ETHIOPIC": _rng(0x1200, 0x1206),
    "HAN": list("的一是不了人我在有他这中大来上国个到说们为子和你地出道也时年得就那要下以生会自着去之过家学对可"),
    "HANGUL": list("가나다라마바사아자차카타파하한국어"),
}


def main():
    langs = json.loads((ROOT / "backend" / "languages.json").read_text(encoding="utf-8"))["languages"]
    need = sorted({l["script"] for l in langs})
    missing_probe = [s for s in need if s not in PROBES]
    if missing_probe:
        sys.exit("нет пробы для письменности: %s — допишите PROBES" % missing_probe)
    out = []
    for f in FONTS:
        entry = dict(f)
        scripts = None
        for key in ("regular", "bold"):
            t = TTFont(str(DIR / f[key]))
            cmap = t.getBestCmap()
            got = {s for s, chars in PROBES.items() if all(ord(c) in cmap for c in chars)}
            scripts = got if scripts is None else scripts & got        # и в жирном тоже
            if key == "regular":
                os2 = t["OS/2"]
                entry["emRatio"] = round(t["head"].unitsPerEm / float(os2.usWinAscent + os2.usWinDescent), 4)
                entry["family"] = t["name"].getBestFamilyName()
        entry["scripts"] = sorted(scripts)
        out.append(entry)
        print("%-12s %-12s em %.4f  %s" % (f["id"], entry["family"], entry["emRatio"], ", ".join(entry["scripts"])))
    doc = {"_comment": "Собрано tools/sub_fonts.py — руками не править: покрытие письменностей "
                       "и emRatio считаются по самим файлам шрифтов.",
           "fonts": out}
    (DIR / "fonts.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
