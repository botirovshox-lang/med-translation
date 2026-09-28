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
  * какие ЯЗЫКИ шрифт знает там, где письменности мало (`langs`): иероглифы
    общие у китайского, японского и корейского, а начертания и набор знаков
    разные;
  * какими знаками шрифт владеет (`fonts.cmap.json`, диапазонами): буквы,
    которых в выбранном шрифте нет, сборка пишет шрифтом, где они есть, —
    явной командой, а не на усмотрение системы (там у каждого сервера свой
    набор шрифтов, и мерка строк врала бы);
  * `emRatio` — во сколько раз кегль ASS больше CSS-кегля того же шрифта.
    libass берёт размер как высоту `usWinAscent + usWinDescent` (так делал
    VSFilter), а браузер — как em. Без поправки предпросмотр DejaVu был бы
    на треть крупнее впечатанного.

Файлы шрифтов письменностей — Noto (OFL) из notofonts.github.io
(fonts/<Имя>/hinted/ttf), иероглифические — noto-cjk, Sans/SubsetOTF.

Запуск: python tools/sub_fonts.py   (нужен fontTools: pip install fonttools)
"""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "frontend" / "vendor" / "fonts" / "sub"

# kind — облик (sans | serif): не покрытый выбором язык получает шрифт того
# же облика. pair — латинский шрифт в пару к шрифту письменности: в шрифтах
# Noto для арабского, деванагари, тайского и прочих НЕТ ни латиницы, ни цифр,
# ни «?!.,» — «COVID-19» в арабской строке иначе стал бы квадратами.
# prefer — языки, для которых шрифт — первый выбор.
# bold: None — жирного файла нет, libass и браузер дорисуют жирность сами
# (иероглифические шрифты весят по 5–8 МБ, и жирный удвоил бы это).
SANS = {"kind": "sans", "pair": "noto-sans", "license": "OFL-Noto.txt"}


def _script_font(fid, name, stem, **kw):
    return dict(SANS, id=fid, name=name, regular=stem + "-Regular.ttf", bold=stem + "-Bold.ttf", **kw)


FONTS = [
    {"id": "noto-sans", "name": "Noto Sans", "regular": "NotoSans-Regular.ttf", "bold": "NotoSans-Bold.ttf",
     "license": "OFL-Noto.txt", "kind": "sans"},
    {"id": "dejavu-sans", "name": "DejaVu Sans", "regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf",
     "license": "LICENSE-DejaVu.txt", "kind": "sans"},
    {"id": "noto-serif", "name": "Noto Serif", "regular": "NotoSerif-Regular.ttf", "bold": "NotoSerif-Bold.ttf",
     "license": "OFL-Noto.txt", "kind": "serif"},
    _script_font("noto-sans-arabic", "Noto Sans Arabic", "NotoSansArabic"),
    dict(_script_font("noto-naskh-arabic", "Noto Naskh Arabic", "NotoNaskhArabic"), kind="serif",
         pair="noto-serif"),
    _script_font("noto-sans-hebrew", "Noto Sans Hebrew", "NotoSansHebrew"),
    _script_font("noto-sans-armenian", "Noto Sans Armenian", "NotoSansArmenian"),
    _script_font("noto-sans-georgian", "Noto Sans Georgian", "NotoSansGeorgian"),
    _script_font("noto-sans-devanagari", "Noto Sans Devanagari", "NotoSansDevanagari"),
    _script_font("noto-sans-bengali", "Noto Sans Bengali", "NotoSansBengali"),
    _script_font("noto-sans-gujarati", "Noto Sans Gujarati", "NotoSansGujarati"),
    _script_font("noto-sans-gurmukhi", "Noto Sans Gurmukhi", "NotoSansGurmukhi"),
    _script_font("noto-sans-tamil", "Noto Sans Tamil", "NotoSansTamil"),
    _script_font("noto-sans-telugu", "Noto Sans Telugu", "NotoSansTelugu"),
    _script_font("noto-sans-thai", "Noto Sans Thai", "NotoSansThai"),
    _script_font("noto-sans-khmer", "Noto Sans Khmer", "NotoSansKhmer"),
    _script_font("noto-sans-myanmar", "Noto Sans Myanmar", "NotoSansMyanmar"),
    _script_font("noto-sans-ethiopic", "Noto Sans Ethiopic", "NotoSansEthiopic"),
    dict(SANS, id="noto-sans-sc", name="Noto Sans SC", regular="NotoSansSC-Regular.otf", bold=None,
         prefer=["ZH"]),
    dict(SANS, id="noto-sans-jp", name="Noto Sans JP", regular="NotoSansJP-Regular.otf", bold=None,
         prefer=["JA"]),
    dict(SANS, id="noto-sans-kr", name="Noto Sans KR", regular="NotoSansKR-Regular.otf", bold=None,
         prefer=["KO"]),
]


def _rng(a, b):
    return [chr(c) for c in range(a, b + 1)]


# Проба письменности: буквы, без которых язык этой письменности
# на экране ломается. У европейских — все буквы расширенных блоков
# (узбекское «ʻ», азербайджанское «ə», вьетнамские знаки), у прочих —
# горсть основных.
PROBES = {
    "LATIN": _rng(0x41, 0x5A) + _rng(0x61, 0x7A) + [c for c in _rng(0xC0, 0xFF) if c not in "×÷"]
             + _rng(0x100, 0x17F) + list("ȘșȚțƏəƠơƯưʻʼ") + _rng(0x1EA0, 0x1EF9),
    "CYRILLIC": _rng(0x400, 0x45F) + list("ҐґҒғҚқҢңҮүҰұҲҳҺһӘәӨөӮӯӢӣҶҷ"),
    "GREEK": [c for c in _rng(0x391, 0x3A9) if c != "΢"] + _rng(0x3B1, 0x3C9) + list("ΆΈΉΊΌΎΏάέήίόύώ"),
    "ARMENIAN": _rng(0x531, 0x556) + _rng(0x561, 0x586),
    "GEORGIAN": _rng(0x10D0, 0x10F0),
    "HEBREW": _rng(0x5D0, 0x5EA),
    "ARABIC": _rng(0x621, 0x63A) + _rng(0x641, 0x64A) + list("پچژگکیٹڈڑںہھےۃ،؟"),
    "DEVANAGARI": list("अआइकखगघचजटडतदनपबमयरलवसह।"),
    "BENGALI": list("অআইকখগচজটডতদনপবমযরলসহ"),
    "GUJARATI": list("અઆઇકખગચજટડતદનપબમયરલસહ"),
    "GURMUKHI": list("ਅਆਇਕਖਗਚਜਟਡਤਦਨਪਬਮਯਰਲਸਹ"),
    "TAMIL": list("அஆஇகஙசஞடணதநபமயரலவ"),
    "TELUGU": list("అఆఇకఖగచజటడతదనపబమయరలవసహ"),
    "THAI": _rng(0xE01, 0xE2E),
    "KHMER": _rng(0x1780, 0x17A2),
    "MYANMAR": _rng(0x1000, 0x1020),
    "ETHIOPIC": _rng(0x1200, 0x1206),
    # Иероглифы, одинаковые у китайского, японского и корейского (ханча):
    # письменность одна, а какой язык шрифт знает — решают пробы ниже.
    "HAN": list("一二三人大中日月年生子山川水火木金土上下小心手口目"),
    "HANGUL": list("가나다라마바사아자차카타파하한국어"),
}

# Пробы ЯЗЫКА там, где письменности мало: у японского — кана и его
# начертания («国», «学»), у китайского — упрощённые знаки, у корейского —
# хангыль. Иначе корейский шрифт с ханча числился бы «китайским».
LANG_PROBES = {
    "ZH": list("的是了我这们为个国说时过来对会学"),
    "JA": list("あいうえおかきくけこさしすせそアイウエオカキクケコンー日本語国学"),
    "KO": list("가나다라마바사아자차카타파하한국어"),
}


def _ranges(cps) -> list:
    """Таблица знаков шрифта → [[начало, конец], …]: сервер решает по ней,
    каким шрифтом писать каждый знак, и fontTools ему для этого не нужен."""
    out = []
    for c in sorted(cps):
        if out and c == out[-1][1] + 1:
            out[-1][1] = c
        else:
            out.append([c, c])
    return out


def main():
    langs = json.loads((ROOT / "backend" / "languages.json").read_text(encoding="utf-8"))["languages"]
    need = sorted({l["script"] for l in langs})
    missing_probe = [s for s in need if s not in PROBES]
    if missing_probe:
        sys.exit("нет пробы для письменности: %s — допишите PROBES" % missing_probe)
    out, cmaps = [], {}
    for f in FONTS:
        entry = dict(f)
        scripts = langs_ok = None
        for key in ("regular", "bold"):
            if not f.get(key):
                continue
            t = TTFont(str(DIR / f[key]))
            cmap = t.getBestCmap()
            got = {s for s, chars in PROBES.items() if all(ord(c) in cmap for c in chars)}
            gl = {l for l, chars in LANG_PROBES.items() if all(ord(c) in cmap for c in chars)}
            scripts = got if scripts is None else scripts & got        # и в жирном тоже
            langs_ok = gl if langs_ok is None else langs_ok & gl
            if key == "regular":
                os2 = t["OS/2"]
                entry["emRatio"] = round(t["head"].unitsPerEm / float(os2.usWinAscent + os2.usWinDescent), 4)
                entry["family"] = t["name"].getBestFamilyName()
                cmaps[f["id"]] = _ranges(cmap.keys())
        entry["scripts"] = sorted(scripts)
        entry["langs"] = sorted(langs_ok)
        out.append(entry)
        print("%-20s %-18s em %.4f  %s  %s" % (f["id"], entry["family"], entry["emRatio"],
                                               ", ".join(entry["scripts"]), ",".join(entry["langs"])))
    uncovered = [s for s in need if not any(s in e["scripts"] for e in out)]
    if uncovered:
        sys.exit("письменности каталога без шрифта: %s" % uncovered)
    doc = {"_comment": "Собрано tools/sub_fonts.py — руками не править: покрытие письменностей "
                       "и emRatio считаются по самим файлам шрифтов.",
           "langProbes": sorted(LANG_PROBES), "fonts": out}
    (DIR / "fonts.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # Таблица знаков — отдельным файлом: её читает только сервер, а браузеру
    # (каталог шрифтов в редакторе) лишние сотни килобайт ни к чему.
    (DIR / "fonts.cmap.json").write_text(json.dumps(cmaps, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
