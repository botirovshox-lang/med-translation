"""Приёмка выгрузки: готовый файл против оригинала, ДО того как его получит человек (Ч5).

Зачем отдельный модуль. Сборка «как в оригинале» сама отчитывается о том,
что сделала: наложения, вылеты, «слова исходного языка». Но отчитывается она
по СВОИМ данным — по раскладке, которую сама и строила. Чего раскладка
не знает, того отчёт не видит: у скана 1903 года (проект 111) слой
распознавания не совпадал с видимыми буквами, половина строк страницы
в раскладку не попала вовсе, и отчёт сказал «осталось на языке оригинала:
0» — а на листе стояли десятки русских строк. Проверка, которая верит тому,
кого проверяет, ничего не проверяет.

Поэтому здесь сравниваются ПИКСЕЛИ готового листа и листа оригинала, а от
сборки берутся только два факта: где она печатала на самом деле (её слой
до наложения, `layout_pdf.build(keep_overlay=True)`) и что она собиралась
печатать (раскладка и тексты).

Коды (наружу — коды и числа, фразы собирает показ, инвариант 17):
  * UNTRANSLATED — текст оригинала остался на листе нетронутым, и это текст
    исходного языка. Из слоя исходника — уверенно; найденный детектором
    строк в растре (скан, надпись кривыми) — `verify`: без чтения не знаем,
    чья это строка (номер, имя, латынь), подтверждает платный взгляд;
  * NOT_TRANSLATED — то же, но у этого места в проекте НЕТ перевода:
    это не дефект сборки, а непереведённые строки (число для человека);
  * OVERPRINT — печать легла на чужой текст оригинала (слово изменилось,
    а своего места печати у него нет);
  * SPILL — печать легла на рисунок, линию, плашку вне своего места;
  * SILENT — у места есть перевод, а сборка не напечатала там ничего;
  * BLANK — место закрашено, а перевода на нём не видно (стёрто и пусто);
  * RESIDUE — строка оригинала стёрта наполовину: печать накрыла кусок
    строки, остальное осталось;
  * DUPLICATE — два перевода в одно место (строка слоя и надпись
    с картинки про один и тот же текст);
  * PAGES — число листов разошлось с оригиналом (дальше не сравниваем).
  Раздел Ы (петля «проверил — переверстал», 23.10.2026):
  * OVERFLOW — краска перевода на чистой бумаге ВЫШЕ или НИЖЕ ряда своего
    места (за рамку листа, ячейки, плашки); рост вбок по своей строке —
    законный (`_free_room`) и сюда не идёт;
  * RULE_CUT — прямая линия оригинала (таблица, рамка) в выгрузке прервана;
  * MARK_LOST — цветная краска оригинала вне строк текста (печать, подпись,
    логотип) исчезла под закраской;
  * GHOST — над/под стёртой строкой осталась её краска (точки «Ё»,
    ударения, хвосты букв);
  * LOW_CONTRAST — перевод почти не отличается от фона под ним, а оригинал
    отличался (белое на светлом, серое на сером).

Модуль не пишет ни в STATE, ни на диск и не зовёт модель. Всё, что трогает
pdfium, — под общим замком (`pdfium_gate`), страницы закрываются явно.
"""
from __future__ import annotations

import io
import math
import os
import re
import time
import unicodedata

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from pdfium_gate import LOCK as PDFIUM_LOCK
except Exception:  # pragma: no cover
    import threading
    PDFIUM_LOCK = threading.RLock()

QA_DPI = float(os.environ.get("EXPORT_QA_DPI", "72"))
QA_MAX_MPX = float(os.environ.get("EXPORT_QA_MAX_MPX", "4"))     # потолок площади листа
QA_DIFF = int(os.environ.get("EXPORT_QA_DIFF", "48"))            # «точка изменена»
QA_INK = int(os.environ.get("EXPORT_QA_INK", "60"))              # «краска»: темнее бумаги на
QA_UNCHANGED = float(os.environ.get("EXPORT_QA_UNCHANGED", "0.12"))  # доля изменённой краски
QA_DUP = float(os.environ.get("EXPORT_QA_DUP", "0.5"))           # пересечение строк, доля меньшей
QA_SPILL_LINES = float(os.environ.get("EXPORT_QA_SPILL_LINES", "0.25"))  # пятно, строк²
QA_TIME = float(os.environ.get("EXPORT_QA_TIME", "45"))          # секунд на файл
QA_MAX_ISSUES = int(os.environ.get("EXPORT_QA_MAX_ISSUES", "300"))
QA_DETECT_PAGES = int(os.environ.get("EXPORT_QA_DETECT_PAGES", "4"))   # листов детектору строк
QA_DETECT_INK = float(os.environ.get("EXPORT_QA_DETECT_INK", "0.004"))  # необъяснённой краски
QA_TEXT_PX = float(os.environ.get("EXPORT_QA_TEXT_PX", "10"))   # строка текста — не мельче, точек
QA_SMALL = float(os.environ.get("EXPORT_QA_SMALL", "0.62"))     # кегль перевода / оригинала
QA_MIX = float(os.environ.get("EXPORT_QA_MIX", "0.2"))          # отклонение от кегля своего класса

# Тяжесть: 3 — человек получит не перевод (оригинал, пустота, два текста
# друг на друге); 2 — видно с первого взгляда; 1 — заметит верстальщик.
SEVERITY = {"UNTRANSLATED": 3, "SILENT": 3, "BLANK": 2, "DUPLICATE": 3, "PAGES": 3,
            "OVERPRINT": 2, "SPILL": 2, "RESIDUE": 2, "SMALL": 2, "SIZE_MIX": 1,
            "NOT_TRANSLATED": 1, "OVERFLOW": 2, "RULE_CUT": 2, "MARK_LOST": 2,
            "GHOST": 2, "LOW_CONTRAST": 2}
QA_RULE_LEN = float(os.environ.get("EXPORT_QA_RULE_LEN", "4"))     # линия — от стольких строк длиной
QA_CHROMA = int(os.environ.get("EXPORT_QA_CHROMA", "70"))          # «цветная краска»: разброс каналов
QA_CONTRAST = float(os.environ.get("EXPORT_QA_CONTRAST", "45"))    # перевод против фона, из 255
QA_NEW_CHECKS = os.environ.get("EXPORT_QA_NEW", "1") != "0"        # раздел Ы — выключатель
CODES = tuple(SEVERITY)

_WORD_RE = re.compile(r"[^\W\d_][\w'’\-]*[^\W\d_]|[^\W\d_]", re.UNICODE)


def script_of(word: str) -> str:
    """Письменность слова по большинству его букв ('' — букв нет). Кана
    и иероглифы — одна письменность: японский текст пишется обеими."""
    cnt: dict = {}
    for ch in word:
        if not ch.isalpha():
            continue
        try:
            s = unicodedata.name(ch).split(" ")[0]
        except ValueError:
            continue
        if s in ("HIRAGANA", "KATAKANA", "CJK"):
            s = "CJK"
        cnt[s] = cnt.get(s, 0) + 1
    return max(cnt, key=cnt.get) if cnt else ""


def dominant_script(texts) -> str:
    cnt: dict = {}
    for t in texts:
        for w in _WORD_RE.findall(t or ""):
            s = script_of(w)
            if s:
                cnt[s] = cnt.get(s, 0) + len(w)
    return max(cnt, key=cnt.get) if cnt else ""


class Lang:
    """Чей язык у слова: исходного документа или перевода.

    Письменности разные (RU→EN) — решает письменность слова. Одинаковые
    (RU→UZ-CYRL, EN→DE) — словарь: слово есть в оригиналах и нет в переводах.
    Оставленное переводчиком (имя, латынь, марка) стоит в переводах — молчит.
    Слово, которого нет ни там, ни там (поле, колонтитул вне проекта), при
    одной письменности не судится: без словаря сказать нечего."""

    def __init__(self, sources, targets, keep=None):
        sources, targets = list(sources), list(targets)
        self.src = dominant_script(sources)
        self.tgt = dominant_script(targets)
        self.tgt_words = {w.lower() for t in targets for w in _WORD_RE.findall(t or "")}
        self.src_words = {w.lower() for t in sources for w in _WORD_RE.findall(t or "")}
        self.keep = {w.lower() for w in (keep or ())}

    def is_source(self, word: str) -> bool:
        w = word.strip()
        if len(w) < 2 or not any(ch.isalpha() for ch in w):
            return False
        lw = w.lower()
        if lw in self.tgt_words or lw in self.keep:
            return False
        s = script_of(w)
        if not s:
            return False
        if self.src and self.tgt and self.src != self.tgt:
            return s == self.src
        return lw in self.src_words and len(lw) >= 3

    def source_share(self, text: str) -> float:
        ws = _WORD_RE.findall(text or "")
        if not ws:
            return 0.0
        return sum(1 for w in ws if self.is_source(w)) / float(len(ws))


# ─── pdfium ─────────────────────────────────────────────────────────────

class _Doc:
    """Документ pdfium, открытый под замком и закрытый явно (pdfium_gate)."""

    def __init__(self, data: bytes):
        import pypdfium2 as pdfium
        with PDFIUM_LOCK:
            self.pdf = pdfium.PdfDocument(io.BytesIO(data))
            self.n = len(self.pdf)

    def info(self, i: int) -> tuple:
        """(ширина, высота, поворот) в пунктах."""
        with PDFIUM_LOCK:
            page = self.pdf[i]
            try:
                w, h = page.get_size()
                rot = int(page.get_rotation() or 0)
            finally:
                page.close()
        return float(w), float(h), rot

    def raster(self, i: int, scale: float, alpha: bool = False):
        with PDFIUM_LOCK:
            page = self.pdf[i]
            try:
                kw = {"fill_color": (0, 0, 0, 0)} if alpha else {}
                bm = page.render(scale=scale, **kw)
                im = bm.to_pil()
                im.load()
                arr = np.array(im.convert("RGBA" if alpha else "RGB"))
                del im
                bm.close()
            finally:
                page.close()
        return arr

    def runs(self, i: int) -> list:
        """[(текст, x0, y0, x1, y1)] — куски текстового слоя (pdfium сам
        режет текст на прямоугольники строк), пункты, y вверх. Пачкой, а не
        по знаку: замок общий на сервис."""
        out = []
        with PDFIUM_LOCK:
            page = self.pdf[i]
            tp = page.get_textpage()
            try:
                n = tp.count_rects()
                for k in range(min(n, 6000)):
                    l, b, r, t = tp.get_rect(k)
                    txt = tp.get_text_bounded(left=l, bottom=b, right=r, top=t) or ""
                    if txt.strip():
                        out.append((txt, l, b, r, t))
            finally:
                tp.close()
                page.close()
        return out

    def close(self):
        with PDFIUM_LOCK:
            try:
                self.pdf.close()
            except Exception:
                pass


def _cc(mask, min_area: int) -> list:
    """Связные пятна маски: [(x0, y0, x1, y1, площадь)]."""
    import cv2
    if not mask.any():
        return []
    m = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    for j in range(1, n):
        x, y, w, h, _a = st[j]
        real = int(mask[y:y + h, x:x + w].sum())
        if real >= min_area:
            out.append((int(x), int(y), int(x + w), int(y + h), real))
    return out


def _frac(box, W: int, H: int) -> list:
    return [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)]


def _rect_px(b: dict, W: int, H: int, sc: float, ph: float) -> "tuple | None":
    """Рамка из раскладки → точки рисунка (y вниз). Абзацы слоя — пункты
    (y вверх, top > bottom); надписи с картинок — доли листа (`frac`)."""
    try:
        if b.get("frac"):
            x0, x1 = float(b["x0"]) * W, float(b["x1"]) * W
            y0, y1 = float(b["top"]) * H, float(b["bottom"]) * H
        else:
            x0, x1 = float(b["x0"]) * sc, float(b["x1"]) * sc
            top, bot = float(b["top"]), float(b["bottom"])
            y0, y1 = (ph - max(top, bot)) * sc, (ph - min(top, bot)) * sc
            if x1 - x0 < 1.0:
                # Э7: повёрнутая строка — у рамки нет ширины (x0 == x1), место
                # задаёт путь строки (`pts` → `end`) с запасом в кегль во все
                # стороны. Без этого печать повёрнутого перевода считалась
                # «легшей на чужой текст» (OVERPRINT в шапке расписания).
                pts = []
                for sl in b.get("slots") or ():
                    rp = sl[8] if len(sl) > 8 and isinstance(sl[8], dict) else None
                    if rp:
                        pts += [(float(q[0]), float(q[1])) for q in rp.get("pts") or ()]
                        if rp.get("end"):
                            pts.append((float(rp["end"][0]), float(rp["end"][1])))
                if pts:
                    s_ = float(b.get("size") or 0.0)
                    x0 = (min(q[0] for q in pts) - s_) * sc
                    x1 = (max(q[0] for q in pts) + s_) * sc
                    y0 = (ph - max(q[1] for q in pts) - s_) * sc
                    y1 = (ph - min(q[1] for q in pts) + s_) * sc
    except (KeyError, TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (max(0, int(x0)), max(0, int(y0)), min(W, int(round(x1)) + 1), min(H, int(round(y1)) + 1))


def _line_rects(b: dict, pw: float, ph: float) -> list:
    """Строки места долями листа (y вниз): у абзаца слоя — места строк
    (`slots`: x0, базовая, x1, кегль), у надписи с картинки — `lines`."""
    out = []
    if b.get("frac"):
        for ln in b.get("lines") or [[b.get("x0"), b.get("top"), b.get("x1"), b.get("bottom")]]:
            try:
                out.append(tuple(float(v) for v in ln[:4]))
            except (TypeError, ValueError):
                pass
        return out
    for s in b.get("slots") or []:
        try:
            x0, base, x1, size = float(s[0]), float(s[1]), float(s[2]), float(s[3])
        except (TypeError, ValueError, IndexError):
            continue
        out.append((x0 / pw, (ph - base - 0.75 * size) / ph, x1 / pw, (ph - base + 0.2 * size) / ph))
    if not out:
        try:
            out.append((float(b["x0"]) / pw, (ph - max(b["top"], b["bottom"])) / ph,
                        float(b["x1"]) / pw, (ph - min(b["top"], b["bottom"])) / ph))
        except (KeyError, TypeError, ValueError):
            pass
    return out


def printed_items(layout: dict, texts: dict, extra: "list | None",
                  sources: "dict | None" = None) -> list:
    """Что выгрузка ДОЛЖНА была напечатать: [{key, page, boxes, text}]
    и отдельно места БЕЗ перевода (`text` пуст) — их строки на листе
    остаются оригиналом законно для сборки, но это непереведённое."""
    items = []
    for key, boxes in ((layout or {}).get("boxes") or {}).items():
        try:
            t = (texts or {}).get(int(key))
        except (TypeError, ValueError):
            t = (texts or {}).get(key)
        by_page: dict = {}
        for b in boxes or []:
            by_page.setdefault(int(b.get("page", 0)), []).append(b)
        for pg, bs in by_page.items():
            try:
                src = (sources or {}).get(int(key)) or ""
            except (TypeError, ValueError):
                src = ""
            items.append({"key": "p%s" % key, "page": pg, "boxes": bs, "text": t or "",
                          "known": t is not None, "src": src})
    for k, it in enumerate(extra or []):
        by_page = {}
        for b in it.get("boxes") or []:
            by_page.setdefault(int(b.get("page", 0)), []).append(b)
        for pg, bs in by_page.items():
            items.append({"key": "x%d" % k, "page": pg, "boxes": bs, "text": it.get("text") or "",
                          "known": True, "src": " ".join(b.get("src") or "" for b in bs),
                          "keep": bool(it.get("keep"))})
    return items


def _poly_area(p: list) -> float:
    return abs(sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1] for i in range(len(p)))) / 2.0


def _poly_clip(subj: list, clip: list) -> list:
    """Пересечение выпуклых многоугольников (Сазерленд — Ходжмен)."""
    def inside(pt, a, b, sgn):
        return sgn * ((b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])) >= 0

    def cross(p1, p2, a, b):
        x1, y1, x2, y2 = p1[0], p1[1], p2[0], p2[1]
        x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-12:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    # Обход клиппера — по знаку площади (точки детектора идут по часовой в y вниз).
    sa = sum(clip[i][0] * clip[i - 1][1] - clip[i - 1][0] * clip[i][1] for i in range(len(clip)))
    sgn = -1.0 if sa > 0 else 1.0
    out = list(subj)
    for i in range(len(clip)):
        a, b = clip[i - 1], clip[i]
        inp, out = out, []
        if not inp:
            break
        for j in range(len(inp)):
            cur, prev = inp[j], inp[j - 1]
            if inside(cur, a, b, sgn):
                if not inside(prev, a, b, sgn):
                    out.append(cross(prev, cur, a, b))
                out.append(cur)
            elif inside(prev, a, b, sgn):
                out.append(cross(prev, cur, a, b))
    return out


def duplicates(items: list, sizes: dict) -> list:
    """Две печати в одно место: строки двух мест (долями листа) перекрываются
    больше чем на `QA_DUP` меньшей. Сравниваются строки, а не рамки абзацев:
    рамка абзаца таблицы законно накрывает соседей, строки — нет."""
    out = []
    by_page: dict = {}
    for it in items:
        if (it["text"] or "").strip() and not it.get("keep"):
            by_page.setdefault(it["page"], []).append(it)
    for pg, its in by_page.items():
        pw, ph = sizes.get(pg, (612.0, 792.0))
        rects = []
        polys: dict = {}
        for it in its:
            for b in it["boxes"]:
                if b.get("repeat"):
                    continue
                lr = _line_rects(b, pw, ph)
                pl = b.get("polys") if b.get("frac") else None
                for n_, r in enumerate(lr):
                    if r[2] > r[0] and r[3] > r[1]:
                        rects.append((it["key"], r))
                        # Р2: у наклонной строки (Э14) — её четырёхугольник:
                        # ось-параллельные рамки соседних наклонных строк
                        # перекрываются ВСЕГДА (визитка 66: шесть «двойников»).
                        if pl and len(pl) == len(lr) and pl[n_] and len(pl[n_]) == 4:
                            polys[(it["key"], r)] = [tuple(float(v) for v in pt[:2]) for pt in pl[n_]]
        rects.sort(key=lambda kr: kr[1][1])
        hit: set = set()
        for a in range(len(rects)):
            ka, ra = rects[a]
            for c in range(a + 1, len(rects)):
                kc, rc = rects[c]
                if rc[1] > ra[3]:
                    break
                if ka == kc:
                    continue
                ix = min(ra[2], rc[2]) - max(ra[0], rc[0])
                iy = min(ra[3], rc[3]) - max(ra[1], rc[1])
                if ix <= 0 or iy <= 0:
                    continue
                pa_, pc_ = polys.get((ka, ra)), polys.get((kc, rc))
                if pa_ and pc_:
                    small = min(_poly_area(pa_), _poly_area(pc_))
                    inter = _poly_area(_poly_clip(pa_, pc_)) if small > 0 else 0.0
                    if not (small > 0 and inter >= QA_DUP * small):
                        continue
                    small, ix, iy = 1.0, 1.0, 1.0      # совпали многоугольники — двойник
                else:
                    small = min((ra[2] - ra[0]) * (ra[3] - ra[1]), (rc[2] - rc[0]) * (rc[3] - rc[1]))
                if small > 0 and ix * iy >= QA_DUP * small:
                    k = tuple(sorted((ka, kc)))
                    if k not in hit:
                        hit.add(k)
                        out.append({"code": "DUPLICATE", "page": pg, "keys": list(k),
                                    "box": [round(max(ra[0], rc[0]), 4), round(max(ra[1], rc[1]), 4),
                                            round(min(ra[2], rc[2]), 4), round(min(ra[3], rc[3]), 4)]})
    return out


_LEADER_RUN = re.compile(r"^[\s.·…‥]{4,}$")


QA_PLATE_OWN = os.environ.get("EXPORT_QA_PLATE_OWN", "1") != "0"
QA_PLATE_ITEM_X = 60.0          # плашка не больше стольких площадей места
QA_PLATE_MAX = 0.45             # доля листа: больше — фон страницы, а не плашка (панель буклета — треть листа)


def _own_plates(ai, item_px: list, H: int, W: int):
    """Э11: плашка, на которой стоит место печати (закрашенный блок схемы,
    кнопка, ячейка с заливкой), — тоже своё место: перевод, выросший на
    вторую строку внутри своей плашки, на чужой рисунок не лёг. Плашка —
    связная область цвета фона места в ОРИГИНАЛЕ (заливка от края рамки
    места); больше `QA_PLATE_MAX` листа — фон страницы, не считаем."""
    out = np.zeros((H, W), bool)
    try:
        import cv2
    except Exception:
        return out
    img = np.ascontiguousarray(ai[..., :3].astype(np.uint8))
    lim = QA_PLATE_MAX * H * W
    done = set()
    for _it, rects in item_px:
        for r in rects:
            x0, y0, x1, y1 = r
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            # Затравка — у левого края рамки на средней линии (между буквами
            # вероятнее фон, чем у самой середины слова).
            sx, sy = min(W - 1, max(0, x0 + 1)), min(H - 1, max(0, (y0 + y1) // 2))
            key = (sx // 4, sy // 4)
            if key in done:
                continue
            done.add(key)
            seed = img[sy, sx].astype(int)
            if int(seed.max()) - int(seed.min()) < 12 and int(seed.mean()) > 235:
                continue                # белая бумага — не плашка
            mask = np.zeros((H + 2, W + 2), np.uint8)
            n_, _im, _m, rect = cv2.floodFill(img, mask, (int(sx), int(sy)), (0, 0, 0),
                                               (8, 8, 8), (8, 8, 8),
                                               4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
                                               | (255 << 8))
            if n_ <= 0 or n_ > lim:
                continue
            # Плашка — почти прямоугольная (заливка на фото и градиенте
            # расползается кляксой) и не больше места во много раз.
            rx, ry, rw, rh = rect
            if n_ < 0.75 * max(1, rw * rh) or rw * rh > QA_PLATE_ITEM_X * max(1, (x1 - x0) * (y1 - y0)):
                continue
            # Сама область (с затянутыми дырами от букв), а не её рамка:
            # значок или рисунок НА плашке своим местом не становится.
            m = cv2.morphologyEx(mask[1:-1, 1:-1], cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
            out |= m
    return out


def inspect_pdf(orig: bytes, out: bytes, layout: "dict | None" = None, texts: "dict | None" = None,
                extra: "list | None" = None, lang: "Lang | None" = None,
                overlay: "bytes | None" = None, overlay_order: "list | None" = None,
                pages: "list | None" = None, dpi: float = 0, time_budget: float = 0,
                detect=None, sources: "dict | None" = None) -> dict:
    """Приёмка PDF «как в оригинале» (и PDF скана): лист выгрузки против
    листа оригинала. `orig` — те же страницы, что печатались (у «ленты» —
    виртуальные: `main._pdf_work_bytes`). `overlay` — слой сборки до
    наложения (где печатали на самом деле); без него место печати берётся
    из раскладки, и SPILL/OVERPRINT не считаются (нечем отличить своё)."""
    if np is None:
        return {"ok": None, "why": "no_numpy", "issues": []}
    t0 = time.time()
    budget = float(time_budget or QA_TIME)
    rep = {"ok": True, "pages": 0, "checked": 0, "issues": [], "partial": False,
           "runs": 0, "printed": 0, "detected": 0, "skipped": {}}
    docs = []
    try:
        A, B = _Doc(orig), _Doc(out)
        docs += [A, B]
        O = _Doc(overlay) if overlay else None
        if O is not None:
            docs.append(O)
    except Exception as e:
        for d in docs:
            d.close()
        return {"ok": None, "why": "open:%s" % type(e).__name__, "issues": []}
    try:
        rep["pages"] = A.n
        if A.n != B.n:
            rep["issues"].append({"code": "PAGES", "page": None, "n": [A.n, B.n]})
            rep["ok"] = False
            return rep
        infos = {}
        for i in range(A.n):
            try:
                infos[i] = A.info(i)
            except Exception:
                pass
        items = printed_items(layout or {}, texts or {}, extra, sources)
        rep["printed"] = sum(1 for it in items if (it["text"] or "").strip())
        rep["issues"] += duplicates(items, {i: (w, h) for i, (w, h, _r) in infos.items()})
        by_page: dict = {}
        for it in items:
            by_page.setdefault(it["page"], []).append(it)
        want = range(A.n) if pages is None else [p for p in pages if 0 <= p < A.n]
        state = {"detect": detect, "detected": 0}
        for i in want:
            if time.time() - t0 > budget or len(rep["issues"]) >= QA_MAX_ISSUES:
                rep["partial"] = True
                break
            w, h, rot = infos.get(i, (0.0, 0.0, 0))
            if not w or not h:
                continue
            if rot % 360:
                # Повёрнутую страницу сборка не трогает вовсе (`/Rotate`),
                # и координаты слоя у неё в другом пространстве.
                rep["skipped"]["rotated"] = rep["skipped"].get("rotated", 0) + 1
                rep["checked"] += 1
                continue
            oi = None
            if O is not None and overlay_order is not None and i < len(overlay_order):
                oi = overlay_order[i]
            _inspect_page(A, B, O, oi, i, w, h, by_page.get(i, []), lang, rep, state)
            rep["checked"] += 1
        rep["detected"] = state["detected"]
        _size_mix(items, rep)
    finally:
        for d in docs:
            d.close()
    rep["counts"] = {}
    for it in rep["issues"]:
        rep["counts"][it["code"]] = rep["counts"].get(it["code"], 0) + 1
    bad = any(SEVERITY.get(it["code"], 1) >= 2 and not it.get("verify") for it in rep["issues"])
    rep["ok"] = False if bad else (None if rep["partial"] else True)
    rep["seconds"] = round(time.time() - t0, 1)
    return rep


def _inspect_page(A, B, O, oi, i: int, pw: float, ph: float, items: list, lang, rep: dict,
                  state: dict) -> None:
    runs = A.runs(i)
    rep["runs"] += len(runs)
    sc = float(QA_DPI) / 72.0
    hs = sorted(r[4] - r[2] for r in runs if r[4] > r[2])
    if hs:
        # Мелкий текст (виртуальные страницы «ленты», сноски) — крупнее:
        # строка в три точки не отличает «напечатано» от «осталось».
        sc = max(sc, QA_TEXT_PX / max(0.5, hs[len(hs) // 2]))
    if pw * ph * sc * sc > QA_MAX_MPX * 1e6:
        sc = (QA_MAX_MPX * 1e6 / (pw * ph)) ** 0.5     # «лента» и гиганты — мельче
    a = A.raster(i, sc)
    b = B.raster(i, sc)
    if a.shape != b.shape:
        rep["skipped"]["size"] = rep["skipped"].get("size", 0) + 1
        return
    H, W = a.shape[:2]
    ai, bi = a.astype(np.int16), b.astype(np.int16)
    ga, gb = ai.mean(axis=2), bi.mean(axis=2)
    diff = np.abs(ai - bi).max(axis=2) > QA_DIFF
    paper = float(np.percentile(ga, 90))
    dark = paper < 150                     # обложка, фото: «бумаги» нет
    ink_a = ga < paper - QA_INK
    nonpaper = ink_a | ((ai.max(axis=2) - ai.min(axis=2)) > 40) | (np.abs(ga - paper) > 25)
    # Где сборка печатала на самом деле: непрозрачное в её слое.
    printed = None
    if O is not None and oi is not None:
        try:
            ov = O.raster(oi, sc, alpha=True)
            if ov.shape[:2] == (H, W):
                printed = ov[..., 3] > 16
        except Exception:
            printed = None
    # Свои места: рамки мест печати (с переводом) + поле в долю строки.
    own = np.zeros((H, W), bool)
    lost = np.zeros((H, W), bool)          # места БЕЗ перевода
    item_px = []
    lhs = []
    for it in items:
        rects = []
        for bx in it["boxes"]:
            r = _rect_px(bx, W, H, sc, ph)
            if not r:
                continue
            lh = float(bx.get("size") or 0) * (H if bx.get("frac") else sc) or (r[3] - r[1])
            lh = max(2.0, min(lh, r[3] - r[1] + 2.0))
            pad = int(0.4 * lh)
            if it.get("keep"):
                # Ю1: место оставлено оригиналом НАМЕРЕННО (перевод равен
                # оригиналу) — его строки объяснены, печати тут не ждём.
                own[max(0, r[1] - pad):r[3] + pad, max(0, r[0] - pad):r[2] + pad] = True
                continue
            tgt = own if (it["text"] or "").strip() else lost
            tgt[max(0, r[1] - pad):r[3] + pad, max(0, r[0] - pad):r[2] + pad] = True
            rects.append(r)
            if (it["text"] or "").strip():
                lhs.append(lh)
        if rects and (it["text"] or "").strip():
            item_px.append((it, rects))
    lh_med = float(np.median(lhs)) if lhs else 10.0 * sc
    # 1. Текст слоя оригинала.
    words_zone = np.zeros((H, W), bool)
    left: list = []
    nt: list = []
    over: list = []
    for txt, x0, y0, x1, y1 in runs:
        bx = (max(0, int(x0 * sc)), max(0, int((ph - y1) * sc)),
              min(W, int(x1 * sc) + 1), min(H, int((ph - y0) * sc) + 1))
        if bx[2] - bx[0] < 2 or bx[3] - bx[1] < 2:
            continue
        if _LEADER_RUN.match(txt or ""):
            # Ш40: отточие стирается и рисуется заново от конца перевода —
            # сменившаяся краска на нём своя, не чужой текст.
            words_zone[bx[1]:bx[3], bx[0]:bx[2]] = True
            continue
        words_zone[bx[1]:bx[3], bx[0]:bx[2]] = True
        p_ = max(1, (bx[3] - bx[1]) // 3)
        ry0, ry1, rx0, rx1 = max(0, bx[1] - p_), min(H, bx[3] + p_), max(0, bx[0] - p_), min(W, bx[2] + p_)
        ink = _local_ink(a[bx[1]:bx[3], bx[0]:bx[2]], a[ry0:ry1, rx0:rx1])
        n_ink = int(ink.sum())
        if n_ink < 4:
            continue                    # невидимый слой без краски под ним
        ch = float((diff[bx[1]:bx[3], bx[0]:bx[2]] & ink).sum()) / n_ink
        cy, cx = (bx[1] + bx[3]) // 2, (bx[0] + bx[2]) // 2
        if ch < QA_UNCHANGED:
            if lang is not None and lang.source_share(txt) >= 0.5:
                (nt if lost[cy, cx] and not own[cy, cx] else left).append((txt, bx))
        elif printed is not None and not own[cy, cx] and not lost[cy, cx] and ch > 0.5:
            over.append((txt, bx))
        elif printed is not None and lost[cy, cx] and not own[cy, cx] and ch > 0.5:
            over.append((txt, bx))      # чужой перевод лёг на непереведённое
    for code, group in (("UNTRANSLATED", left), ("NOT_TRANSLATED", nt), ("OVERPRINT", over)):
        for x0, y0, x1, y1, _a in _cc(_mask_of([g[1] for g in group], H, W), 1):
            txt = " ".join(g[0].strip() for g in group
                           if g[1][0] >= x0 - 3 and g[1][2] <= x1 + 3
                           and g[1][1] >= y0 - 3 and g[1][3] <= y1 + 3)
            row = {"code": code, "page": i, "box": _frac((x0, y0, x1, y1), W, H),
                   "text": " ".join(txt.split())[:120]}
            if code == "OVERPRINT":
                # Чья печать легла на чужой текст — ближайшее место с переводом:
                # по нему петля (`main._layout_loop`) правит вёрстку.
                row["near"] = _nearest(item_px, (x0, y0, x1, y1))
            rep["issues"].append(row)
    # 2. Печать на рисунке, линии, плашке — вне своего места.
    if printed is not None and not dark:
        spill = printed & diff & nonpaper & ~own & ~words_zone & ~lost
        if QA_PLATE_OWN and spill.any():
            spill &= ~_own_plates(ai, item_px, H, W)
        for x0, y0, x1, y1, area in _cc(spill, max(6, int(QA_SPILL_LINES * lh_med * lh_med))):
            rep["issues"].append({"code": "SPILL", "page": i, "box": _frac((x0, y0, x1, y1), W, H),
                                  "area": round(area / max(1.0, lh_med * lh_med), 2),
                                  "near": _nearest(item_px, (x0, y0, x1, y1))})
    if QA_NEW_CHECKS and not dark:
        try:
            _new_checks(a, b, diff, ink_a, printed, own, lost, words_zone, runs, item_px,
                        lh_med, i, W, H, ph, sc, paper, rep)
        except Exception as e:          # проверка не роняет приёмку
            rep.setdefault("skipped", {})["newChecks:%s" % type(e).__name__] = 1
    # 2б. Растровый текст: строки, которых нет в слое (скан, надпись кривыми).
    det = state.get("detect")
    if det is not None and state["detected"] < QA_DETECT_PAGES and not dark:
        unexplained = ink_a & ~own & ~words_zone & ~lost
        if float(unexplained.sum()) / max(1, H * W) >= QA_DETECT_INK:
            state["detected"] += 1
            _raster_lines(a, diff, ink_a, own, lost, words_zone, det, i, W, H, rep)
    # 3. У места есть перевод, а сборка там ничего не напечатала / стёрла и пусто.
    for it, rects in item_px:
        tot = chg = ink_out = ink_in = 0
        for r in rects:
            d = diff[r[1]:r[3], r[0]:r[2]]
            tot += d.size
            chg += int(d.sum())
            ink_out += int(_local_ink(b[r[1]:r[3], r[0]:r[2]]).sum())
            ink_in += int(_local_ink(a[r[1]:r[3], r[0]:r[2]]).sum())
        if tot <= 0:
            continue
        pr = None
        if printed is not None:
            pr = sum(int(printed[r[1]:r[3], r[0]:r[2]].sum()) for r in rects)
        if (pr == 0) if pr is not None else (chg == 0):
            rep["issues"].append({"code": "SILENT", "page": i, "key": it["key"],
                                  "box": _frac(_union(rects), W, H), "text": (it["text"] or "")[:120]})
        elif chg > 0 and ink_out < max(4, 0.002 * tot):
            rep["issues"].append({"code": "BLANK", "page": i, "key": it["key"],
                                  "box": _frac(_union(rects), W, H), "text": (it["text"] or "")[:120]})
        elif ink_in >= 40 and (it.get("src") or "").strip():
            # Кегль: краска растёт как квадрат кегля и линейно с длиной
            # текста. Перевод вдвое длиннее при том же кегле — вдвое больше
            # краски; меньше ожидаемого втрое — кегль упал больше чем на 40%.
            ln = max(0.3, min(3.0, _vlen(it["text"]) / max(1.0, _vlen(it["src"]))))
            k = (ink_out / float(ink_in) / ln) ** 0.5
            it["_scale"] = k
            it["_box"] = _frac(_union(rects), W, H)
            rep.setdefault("scales", []).append([i, it["key"], round(k, 2)])
            if k < QA_SMALL:
                rep["issues"].append({"code": "SMALL", "page": i, "key": it["key"],
                                      "box": _frac(_union(rects), W, H), "scale": round(k, 2),
                                      "text": (it["text"] or "")[:80]})


def _raster_lines(a, diff, ink_a, own, lost, words_zone, det, i: int, W: int, H: int,
                  rep: dict) -> None:
    """Строки оригинала, найденные детектором, против выгрузки.

    Не изменилась строка вне мест печати — осталась на языке оригинала,
    но чья это строка, без чтения не сказать (номер, имя, латынь):
    находка НЕПРОВЕРЕННАЯ (`verify`), её подтверждает или снимает платный
    взгляд. Изменилась наполовину и выходит за место печати — печать
    накрыла кусок строки, остальное осталось (RESIDUE): видно без чтения."""
    import cv2
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, "PNG")
    try:
        lines = det(buf.getvalue()) or []
    except Exception:
        return
    for ln in lines:
        bx = ln.get("box") if isinstance(ln, dict) else ln
        if not bx or len(bx) < 4:
            continue
        x0, y0, x1, y1 = [int(v) for v in bx[:4]]
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        h, w = y1 - y0, x1 - x0
        if h < 3 or w < 2.5 * h:
            continue                    # номер страницы, буквица, знак
        ink = _local_ink(a[y0:y1, x0:x1])
        n = int(ink.sum())
        if n < 12:
            continue
        if float((ink & words_zone[y0:y1, x0:x1]).sum()) / n > 0.3:
            continue                    # строка слоя — её судит проверка слоя
        if float(lost[y0:y1, x0:x1].mean()) > 0.5:
            continue                    # место без перевода — уже названо
        # Текст — это много отдельных знаков; линия, рамка, узор — одно-два пятна.
        k, _lab, st, _c = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
        if k - 1 < 3 or (k - 1 < 6 and float(np.median(st[1:, 2])) > 2.0 * h):
            continue
        ch = float((diff[y0:y1, x0:x1] & ink).sum()) / n
        inz = float(own[y0:y1, x0:x1].mean())
        if ch < QA_UNCHANGED and inz < 0.5:
            rep["issues"].append({"code": "UNTRANSLATED", "page": i, "raster": True, "verify": True,
                                  "box": _frac((x0, y0, x1, y1), W, H)})
        elif QA_UNCHANGED <= ch < 0.7 and inz < 0.85:
            cols = (diff[y0:y1, x0:x1] & ink).any(axis=0)
            still = ink.any(axis=0) & ~cols & ~own[y0:y1, x0:x1].any(axis=0)
            if int(still.sum()) >= 2 * h:
                rep["issues"].append({"code": "RESIDUE", "page": i, "raster": True,
                                      "box": _frac((x0, y0, x1, y1), W, H), "share": round(1 - ch, 2)})


def _new_checks(a, b, diff, ink_a, printed, own, lost, words_zone, runs, item_px,
                lh_med: float, i: int, W: int, H: int, ph: float, sc: float, paper: float,
                rep: dict) -> None:
    """Раздел Ы: виды, которых прежняя приёмка не видела — перерезанная
    линия, стёртая печать, остаток знаков над стёртой строкой, текст
    за рамкой, перевод цветом фона. Каждая находка — с ключом места
    (`key`), ближайшего к ней: по ключу петля (`main._layout_loop`) правит
    вёрстку именно этого места."""
    import cv2
    ga = a.astype(np.int16).mean(axis=2)
    gb = b.astype(np.int16).mean(axis=2)
    lh = max(2.0, lh_med)
    area_min = max(6, int(0.15 * lh * lh))
    # Ядро строк текста оригинала — рамки слов слоя и рамки мест (без поля).
    core = words_zone.copy()
    for _it, rects in item_px:
        for r in rects:
            core[r[1]:r[3], r[0]:r[2]] = True

    def add(code, mask, min_area, extra=None):
        for x0, y0, x1, y1, area in _cc(mask, min_area):
            row = {"code": code, "page": i, "box": _frac((x0, y0, x1, y1), W, H),
                   "key": _nearest(item_px, (x0, y0, x1, y1))}
            if extra:
                row.update(extra)
            rep["issues"].append(row)

    # RULE_CUT: длинная прямая оригинала, прерванная в выгрузке.
    L = max(9, int(QA_RULE_LEN * lh))
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1))
    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, L))
    ink_b = gb < paper - QA_INK
    la = cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, k_h) | \
        cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, k_v)
    # Линия — ТОНКИЙ штрих: сплошная плашка (белый текст на цветном) тоже
    # «краска», и её края открытием длинным ядром читались линиями, а белые
    # буквы перевода — разрывами в ней (36 ложных находок на инфографике).
    t = max(3, int(0.4 * lh)) | 1
    fat = cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (t, t)))
    fat = cv2.dilate(fat, np.ones((3, 3), np.uint8))
    la = la & (1 - fat)
    # И по обе стороны от линии — БУМАГА (не меньше 70% вдоль неё): полоска
    # плашки между двумя строками белого текста тонкая и длинная, но рядом
    # с ней буквы, а не бумага (ложные разрывы в заголовке на плашке).
    pap = (~ink_a).astype(np.float32)
    d = max(2, t)
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)).astype(np.float32) / L
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)).astype(np.float32) / L
    ph_ = cv2.filter2D(pap, -1, kh)
    pv_ = cv2.filter2D(pap, -1, kv)
    side_h = (np.roll(ph_, d, axis=0) >= 0.7) & (np.roll(ph_, -d, axis=0) >= 0.7)
    side_v = (np.roll(pv_, d, axis=1) >= 0.7) & (np.roll(pv_, -d, axis=1) >= 0.7)
    lh_ = cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, k_h) > 0
    lv_ = cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, k_v) > 0
    la = (la > 0) & ((lh_ & side_h) | (lv_ & side_v))
    # Э19: ряд подчёркиваний в ТЕКСТЕ оригинала («Дата «___» ______ 20__ г.»)
    # — поле бланка, а не линия таблицы: перевод несёт свои поля (Ш38) своей
    # длины, и «разрыв» там законен (4 ложных RULE_CUT у подписей договора).
    for txt, x0, y0, x1, y1 in runs:
        if "___" in (txt or ""):
            r0, r1 = max(0, int((ph - y1) * sc) - 3), min(H, int((ph - y0) * sc) + 4)
            c0, c1 = max(0, int(x0 * sc) - 3), min(W, int(x1 * sc) + 4)
            la[r0:r1, c0:c1] = False
    # Линия «на месте», если в выгрузке рядом (±1 точка) есть краска.
    near_b = cv2.dilate(ink_b.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    cut = la & ~near_b & diff
    if printed is not None:
        cut &= cv2.dilate(printed.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    add("RULE_CUT", cut, max(4, int(0.5 * lh)))
    # MARK_LOST: цветная краска вне строк текста исчезла.
    ai, bi = a.astype(np.int16), b.astype(np.int16)
    chroma_a = ai.max(axis=2) - ai.min(axis=2)
    chroma_b = bi.max(axis=2) - bi.min(axis=2)
    core_g = cv2.dilate(core.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    # Печать и подпись — ШТРИХИ; сплошная цветная плашка (жёлтая полоса
    # предупреждения, синяя шапка таблицы) под напечатанным переводом теряет
    # цвет законно — это буквы перевода, а не стёртая печать.
    col_a = (chroma_a > QA_CHROMA).astype(np.uint8)
    fat_c = cv2.dilate(cv2.morphologyEx(col_a, cv2.MORPH_OPEN,
                                        cv2.getStructuringElement(cv2.MORPH_RECT, (t, t))),
                       np.ones((3, 3), np.uint8)) > 0
    lost_mark = (col_a > 0) & ~fat_c & (chroma_b < QA_CHROMA // 3) & diff & ~core_g
    if printed is not None:
        lost_mark &= printed
    # Пороги не замерены на боевых выгрузках — находка «требует
    # подтверждения» (`verify`): видна в отчёте и платному взгляду, но петлю
    # и итог приёмки не решает.
    add("MARK_LOST", lost_mark, area_min, {"verify": True})
    # OVERFLOW: печать ЗА ПРЕДЕЛАМИ занятого на листе — за рамкой, за полем.
    # Рост в свободную бумагу внутри листа законен (строка вбок, `_free_room`;
    # абзац третьей строкой вниз, `below`), а перечёркнутую рамку или линию
    # называет RULE_CUT. Занятое — рамка всей краски оригинала с запасом
    # в полстроки (крошки шума — не краска: от площади в четверть строки).
    if printed is not None:
        cont = cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        ys, xs = np.nonzero(cont)
        if len(ys):
            pad = int(0.5 * lh)
            inside = np.zeros((H, W), bool)
            inside[max(0, ys.min() - pad):ys.max() + pad + 1, max(0, xs.min() - pad):xs.max() + pad + 1] = True
            paper_a = np.abs(ga - paper) < 20
            spill = printed & diff & paper_a & (np.abs(gb - paper) > QA_INK) & ~inside
            add("OVERFLOW", spill, max(area_min, int(0.3 * lh * lh)))
    # GHOST: над/под стёртой строкой осталась её краска.
    la_any = cv2.dilate((cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, k_h)
                         | cv2.morphologyEx(ink_a.astype(np.uint8), cv2.MORPH_OPEN, k_v)),
                        np.ones((3, 3), np.uint8)) > 0
    g_rows: list = []
    for txt, x0, y0, x1, y1 in runs:
        bx = (max(0, int(x0 * sc)), max(0, int((ph - y1) * sc)),
              min(W, int(x1 * sc) + 1), min(H, int((ph - y0) * sc) + 1))
        h = bx[3] - bx[1]
        if h < 3 or bx[2] - bx[0] < 3:
            continue
        inner = diff[bx[1]:bx[3], bx[0]:bx[2]] & ink_a[bx[1]:bx[3], bx[0]:bx[2]]
        n_ink = int(ink_a[bx[1]:bx[3], bx[0]:bx[2]].sum())
        if n_ink < 6 or float(inner.sum()) / n_ink < 0.5:
            continue                    # строку не стирали — её знаки на месте законно
        reach = max(2, int(0.4 * h))
        for ya, yb, ca, cb in ((max(0, bx[1] - reach), bx[1], max(0, bx[1] - 2 * reach), max(0, bx[1] - reach)),
                               (bx[3], min(H, bx[3] + reach), min(H, bx[3] + reach), min(H, bx[3] + 2 * reach))):
            if yb - ya < 1:
                continue
            band_a = ink_a[ya:yb, bx[0]:bx[2]]
            # Линия таблицы под строкой — не остаток буквы.
            same = (band_a & ~diff[ya:yb, bx[0]:bx[2]] & ink_b[ya:yb, bx[0]:bx[2]]
                    & ~(la_any[ya:yb, bx[0]:bx[2]]))
            if int(same.sum()) < 3 or float(band_a.mean()) > 0.2:
                continue
            if cb > ca and ink_a[ca:cb, bx[0]:bx[2]].any():
                continue                # над «знаками» ещё краска — это соседняя строка
            # Своя печать перевода в полосе — не остаток.
            if printed is not None and float(printed[ya:yb, bx[0]:bx[2]][same].mean()) > 0.5:
                continue
            g_rows.append((bx[0], ya, bx[2], yb))
    for x0, y0, x1, y1 in g_rows:
        rep["issues"].append({"code": "GHOST", "page": i, "box": _frac((x0, y0, x1, y1), W, H),
                              "key": _nearest(item_px, (x0, y0, x1, y1)), "verify": True})
    # LOW_CONTRAST: перевод цветом фона.
    for it, rects in item_px:
        r = _union(rects)
        if (r[2] - r[0]) * (r[3] - r[1]) < 20:
            continue
        def contrast(px):
            # По самой краске, а не по процентилям рамки: у короткой строки
            # в крупной рамке краски меньше 5% площади.
            med = float(np.median(px))
            far = np.abs(px - med)
            ink = far[far > 12]
            # Э6: высокий процентиль, а не медиана краски: мелкий сжатый
            # шрифт (6 пт, сужение начертания) при разрешении приёмки — это
            # серые края штрихов, и медиана объявляла «бледным» перевод,
            # напечатанный той же тёмной краской (расписание, корпус 2).
            # У настоящего «белого на светлом» бледна и самая тёмная краска.
            return float(np.percentile(ink, 90)) if ink.size >= 8 else None
        ca = contrast(ga[r[1]:r[3], r[0]:r[2]])
        cb_ = contrast(gb[r[1]:r[3], r[0]:r[2]])
        if (ca is not None and cb_ is not None and ca >= 2 * QA_CONTRAST and cb_ < QA_CONTRAST
                and int(diff[r[1]:r[3], r[0]:r[2]].sum()) > 0):
            rep["issues"].append({"code": "LOW_CONTRAST", "page": i, "key": it["key"],
                                  "box": _frac(r, W, H), "contrast": round(cb_, 1), "verify": True})


def _vlen(text: str) -> float:
    """Ш43: длина текста в «узких знаках»: полноширинный знак (иероглиф,
    кана, хангыль) — два. Мера кегля делит краску на длину, и китайский
    перевод меню выходил «крупнее» оригинала в 1.7 раза при том же кегле
    (SIZE_MIX 9 на ровной странице)."""
    n = 0.0
    for ch in (text or "").strip():
        n += 2.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 1.0
    return n


def _size_mix(items: list, rep: dict) -> None:
    """Разный кегль у однотипного текста (вид B разборов): места одного
    кегля в оригинале должны выйти одним кеглем и в переводе. Медиана
    отношения «кегль перевода / кегль оригинала» по классу кегля документа;
    место дальше медианы на `QA_MIX` — выброс. Мера шумит на ±8% (буквы
    другого языка другой ширины), поэтому порог вдвое выше шума."""
    cls: dict = {}
    for it in items:
        k = it.get("_scale")
        if k is None:
            continue
        sz = [float(b.get("size") or 0) for b in it["boxes"] if not b.get("frac")]
        sz = [v for v in sz if v > 0]
        if not sz:
            continue
        key = round(math.log(sorted(sz)[len(sz) // 2]) / math.log(1.08))   # класс ±4%
        cls.setdefault(key, []).append((it, k))
    for key, lst in cls.items():
        if len(lst) < 4:
            continue
        med = sorted(k for _it, k in lst)[len(lst) // 2]
        for it, k in lst:
            dev = k / med - 1.0
            if abs(dev) > QA_MIX and k >= QA_SMALL:     # SMALL уже назван
                rep["issues"].append({"code": "SIZE_MIX", "page": it["page"], "key": it["key"],
                                      "box": it.get("_box"), "dev": round(dev, 2),
                                      "text": (it["text"] or "")[:80]})


def _local_ink(rgb_region, pad_region=None):
    """Краска места против ЕГО фона, а не бумаги листа: белые буквы на
    красной плашке — тоже краска, а сама плашка — нет. Фон — медиана рамки
    вокруг места (цвет), краска — точки дальше фона на `QA_INK` по любому
    каналу."""
    ref = pad_region if pad_region is not None else rgb_region
    if ref.shape[0] < 3 or ref.shape[1] < 3:
        bg = np.median(ref.reshape(-1, 3), axis=0)
    else:
        frame = np.concatenate([ref[0], ref[-1], ref[:, 0], ref[:, -1]])
        bg = np.median(frame, axis=0)
    return np.abs(rgb_region.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > QA_INK


def _mask_of(boxes, H, W):
    m = np.zeros((H, W), bool)
    for x0, y0, x1, y1 in boxes:
        m[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = True
    return m


def _union(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def _nearest(item_px, box) -> "str | None":
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    best, bd = None, None
    for it, rects in item_px:
        for r in rects:
            dx = max(r[0] - cx, 0, cx - r[2])
            dy = max(r[1] - cy, 0, cy - r[3])
            d = dx * dx + dy * dy
            if bd is None or d < bd:
                best, bd = it["key"], d
    return best


def summary(rep: dict) -> dict:
    """Сводка для показа и очереди сверки: только коды, числа, страницы
    (без текста документа — он уходит лишь суперу в полном отчёте)."""
    pages_by: dict = {}
    for it in rep.get("issues") or []:
        if it.get("page") is not None:
            pages_by.setdefault(it["code"], set()).add(int(it["page"]) + 1)
    return {"ok": rep.get("ok"), "pages": rep.get("pages"), "checked": rep.get("checked"),
            "partial": bool(rep.get("partial")), "counts": dict(rep.get("counts") or {}),
            "where": {k: sorted(v)[:20] for k, v in pages_by.items()},
            "verify": sum(1 for it in rep.get("issues") or [] if it.get("verify"))}


# ─── Платный взгляд (зрячая модель) ─────────────────────────────────────
# Правила видят то, что мерится: осталось/стёрто/налезло/мельче. Не видят
# того, что требует глаз верстальщика: начертание и цвет не те, выключка,
# перевод кусками, смысл надписи на картинке. И не уверены в растровых
# строках (`verify`): номер это, имя или непереведённая строка. Сюда идут
# только листы с находками (или, если правила не нашли ничего, — самые
# насыщенные печатью), не больше `QA_VISION_PAGES`, пара «оригинал |
# выгрузка» одной картинкой с пронумерованными отметками находок правил.

QA_VISION_PAGES = int(os.environ.get("EXPORT_QA_VISION_PAGES", "6"))
QA_VISION_PX = int(os.environ.get("EXPORT_QA_VISION_PX", "1600"))    # длинная сторона пары
VISION_CODES = ("UNTRANSLATED", "MISSING", "FRAGMENT", "DUPLICATE", "OVERLAP", "OVERFLOW",
                "SIZE", "FONT", "ALIGN", "MERGED", "ERASE", "SYMBOL", "BLUR", "READ",
                # Раздел Ы: то, что правила видят не всегда, — модели словами.
                "RULE_CUT", "MARK_LOST", "GHOST", "PATCH", "CONTRAST")
# Код модели → правка места для следующей сборки (`main._layout_loop`):
# модель ПОДСКАЗЫВАЕТ, а решает пиксельная приёмка — сборка с подсказками
# берётся, только если она не хуже сборки без них.
VISION_TUNE = {"OVERFLOW": "tight", "OVERLAP": "tight", "MERGED": "solo",
               "FRAGMENT": "solo", "ERASE": "erase", "GHOST": "erase"}


def vision_pages(rep: dict, limit: int = 0) -> list:
    """Какие листы показывать модели: с находками правил, по весу."""
    w: dict = {}
    for it in rep.get("issues") or []:
        if it.get("page") is None:
            continue
        w[int(it["page"])] = w.get(int(it["page"]), 0) + SEVERITY.get(it["code"], 1) + (2 if it.get("verify") else 0)
    pages = sorted(w, key=lambda p: (-w[p], p))
    return pages[:limit or QA_VISION_PAGES]


def vision_pair(orig: bytes, out: bytes, page: int, issues: list) -> "tuple | None":
    """(JPEG пары «оригинал | выгрузка», [{n, code, box}]) — отметки находок
    правил на ОБЕИХ половинах, номера в рамках."""
    from PIL import Image, ImageDraw
    try:
        A, B = _Doc(orig), _Doc(out)
    except Exception:
        return None
    try:
        w, h, _r = A.info(page)
        sc = min(3.0, QA_VISION_PX / 2.0 / max(1.0, w), QA_VISION_PX / max(1.0, h))
        a = Image.fromarray(A.raster(page, sc))
        b = Image.fromarray(B.raster(page, sc)).resize(a.size)
    except Exception:
        return None
    finally:
        A.close()
        B.close()
    W, H = a.size
    pair = Image.new("RGB", (2 * W + 12, H), (230, 30, 80))
    pair.paste(a, (0, 0))
    pair.paste(b, (W + 12, 0))
    d = ImageDraw.Draw(pair)
    marks = []
    for it in issues:
        bx = it.get("box")
        if it.get("page") != page or not bx:
            continue
        n = len(marks) + 1
        marks.append({"n": n, "code": it["code"], "box": bx, "key": it.get("key") or it.get("near")})
        for off in (0, W + 12):
            r = (off + bx[0] * W - 3, bx[1] * H - 3, off + bx[2] * W + 3, bx[3] * H + 3)
            d.rectangle(r, outline=(255, 0, 0), width=2)
            d.text((r[0], max(0, r[1] - 11)), str(n), fill=(255, 0, 0))
        if len(marks) >= 40:
            break
    buf = io.BytesIO()
    pair.save(buf, "JPEG", quality=85)
    return buf.getvalue(), marks


def vision_prompt(src: str, tgt: str, marks: list) -> str:
    lines = ["You are a meticulous typesetter checking a translated document page.",
             "The image shows the ORIGINAL page on the left and the TRANSLATED export on the right "
             "(source language %s, target language %s). The translation must replace the original "
             "text 1:1: same place, size, typeface, weight, colour, alignment, nothing outside its "
             "box, plate or page, nothing overlapping, nothing left in the source language "
             "(except names, numbers, formulas, references), nothing lost, no erase stains, sharp. "
             "Lines, frames, table rules, stamps, signatures and logos of the original must stay "
             "intact (RULE_CUT, MARK_LOST); no leftovers of the original glyphs such as dots or "
             "accents (GHOST); no visible background patch of a different colour (PATCH); the "
             "translation must contrast with its background like the original (CONTRAST)."
             % (src or "?", tgt or "?")]
    if marks:
        lines.append("Red numbered boxes mark places that automatic checks flagged:")
        for m in marks:
            lines.append("  %d: %s" % (m["n"], m["code"]))
        lines.append("For EVERY mark decide if it is a real visible defect in the export.")
    lines.append("Then list other clearly visible defects of the export (at most 12, the worst first). "
                 "Codes: " + ", ".join(VISION_CODES) + ".")
    lines.append('Answer ONLY JSON: {"marks": [{"n": 1, "real": true, "code": "UNTRANSLATED"}], '
                 '"extra": [{"code": "SIZE", "box": [x0, y0, x1, y1], "what": "short note"}]} '
                 "where box is in fractions (0..1) of the RIGHT half page. No other text.")
    return "\n".join(lines)


def nearest_key(orig: bytes, layout: dict, texts: dict, extra: "list | None",
                sources: "dict | None", page: int, box: list) -> "str | None":
    """Ключ места с переводом, ближайшего к рамке (доли листа) — у находок
    модели ключа нет, а правке нужно место."""
    if not box:
        return None
    try:
        A = _Doc(orig)
        try:
            pw, ph, _r = A.info(page)
        finally:
            A.close()
    except Exception:
        return None
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    best, bd = None, None
    for it in printed_items(layout or {}, texts or {}, extra, sources):
        if it["page"] != page or not (it["text"] or "").strip():
            continue
        for b in it["boxes"]:
            for r in _line_rects(b, pw, ph):
                dx = max(r[0] - cx, 0, cx - r[2])
                dy = max(r[1] - cy, 0, cy - r[3])
                d = dx * dx + dy * dy
                if bd is None or d < bd:
                    best, bd = it["key"], d
    return best


def vision_parse(text: str, marks: list) -> dict:
    """Ответ модели → {confirmed, dismissed, extra}. Чужое и битое отбрасывается."""
    import json as _json
    t = (text or "").strip()
    a, b = t.find("{"), t.rfind("}")
    try:
        d = _json.loads(t[a:b + 1]) if a >= 0 and b > a else {}
    except Exception:
        d = {}
    known = {m["n"]: m for m in marks}
    conf, dism = [], []
    for m in d.get("marks") or []:
        try:
            n = int(m.get("n"))
        except (TypeError, ValueError):
            continue
        if n not in known:
            continue
        (conf if m.get("real") else dism).append(n)
    extra = []
    for e in (d.get("extra") or [])[:12]:
        code = str(e.get("code") or "").upper()
        if code not in VISION_CODES:
            continue
        bx = e.get("box")
        try:
            bx = [max(0.0, min(1.0, float(v))) for v in bx[:4]] if bx and len(bx) >= 4 else None
        except (TypeError, ValueError):
            bx = None
        extra.append({"code": code, "box": bx, "what": str(e.get("what") or "")[:200]})
    return {"confirmed": conf, "dismissed": dism, "extra": extra}
