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
            "NOT_TRANSLATED": 1}
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
                          "known": True, "src": " ".join(b.get("src") or "" for b in bs)})
    return items


def duplicates(items: list, sizes: dict) -> list:
    """Две печати в одно место: строки двух мест (долями листа) перекрываются
    больше чем на `QA_DUP` меньшей. Сравниваются строки, а не рамки абзацев:
    рамка абзаца таблицы законно накрывает соседей, строки — нет."""
    out = []
    by_page: dict = {}
    for it in items:
        if (it["text"] or "").strip():
            by_page.setdefault(it["page"], []).append(it)
    for pg, its in by_page.items():
        pw, ph = sizes.get(pg, (612.0, 792.0))
        rects = []
        for it in its:
            for b in it["boxes"]:
                if b.get("repeat"):
                    continue
                for r in _line_rects(b, pw, ph):
                    if r[2] > r[0] and r[3] > r[1]:
                        rects.append((it["key"], r))
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
            rep["issues"].append({"code": code, "page": i, "box": _frac((x0, y0, x1, y1), W, H),
                                  "text": " ".join(txt.split())[:120]})
    # 2. Печать на рисунке, линии, плашке — вне своего места.
    if printed is not None and not dark:
        spill = printed & diff & nonpaper & ~own & ~words_zone & ~lost
        for x0, y0, x1, y1, area in _cc(spill, max(6, int(QA_SPILL_LINES * lh_med * lh_med))):
            rep["issues"].append({"code": "SPILL", "page": i, "box": _frac((x0, y0, x1, y1), W, H),
                                  "area": round(area / max(1.0, lh_med * lh_med), 2),
                                  "near": _nearest(item_px, (x0, y0, x1, y1))})
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
                "SIZE", "FONT", "ALIGN", "MERGED", "ERASE", "SYMBOL", "BLUR", "READ")


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
        marks.append({"n": n, "code": it["code"], "box": bx})
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
             "(except names, numbers, formulas, references), nothing lost, no erase stains, sharp."
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
