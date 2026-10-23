"""Предпечатная проверка (раздел Ы2): память взгляда модели по странице
и база правил, выученных моделью.

Зачем. У выгрузки одна попытка: первый файл, который получает человек,
обязан быть готовым. Поэтому сильная модель смотрит КАЖДУЮ страницу до
выдачи — а платить за одну и ту же страницу дважды незачем. Ответ модели
о странице берётся из памяти ТОЛЬКО если совпало всё сразу (решение
владельца 23.10.2026):

  1. тексты, напечатанные на странице (буква в букву);
  2. раскладка строк: место, кегль и перенос каждой строки;
  3. картинка страницы после сборки;
  4. версии: правила вёрстки, приёмки, модель и вопрос к ней, шрифты.

Не совпал хоть один — страница смотрится заново, и причина называется
(«перевод изменился», «сдвинулись строки», «другая картинка», «другие
версии»).

База выученных правил. Модель, исправив место действием из закрытого
списка, оставляет ПРАВИЛО ДАННЫМИ: признаки места (вид, выключка,
плашка, ячейка, письмо, во сколько раз перевод длиннее) → действие.
Действующим оно становится после `LEARN_MIN_OK` подтверждённых случаев
без единого провала и с этого момента применяется нашим кодом ДО вызова
модели — бесплатно и одинаково при повторе. Испортило страницу —
отзывается. Кода модель не пишет: правило — это строка данных, а сложные
случаи уходят в очередь, откуда их превращает в код и тест разработчик.

Модуль не зовёт модель и не пишет в STATE; файлы — рядом с исходником
(память страниц) и в каталоге данных (база правил), записью tmp + replace.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

# Версия ВОПРОСА к модели и списка действий: правишь промпт — поднимай,
# иначе память отдаст ответ на прежний вопрос.
PROMPT_VERSION = "pp3"
LEARN_MIN_OK = int(os.environ.get("PREPRESS_LEARN_MIN_OK", "2"))
LEARN_MAX = int(os.environ.get("PREPRESS_LEARN_MAX", "500"))

# Закрытый список действий модели → правка места у сборки (`layout_pdf.build(tune=…)`)
# либо особое действие, которое исполняет `main` (короче перевод, гарнитура, выключка).
ACTIONS = ("tight", "wide", "solo", "erase", "keep_rule", "lines2", "keep_breaks", "cond",
           "leave_orig", "shorter", "align_left", "align_right", "align_center", "justify",
           "no_justify", "serif", "sans", "mono", "color", "split_lines", "translate", "none")
TUNE_ACTIONS = {"tight", "wide", "solo", "erase", "keep_rule", "lines2", "keep_breaks", "cond",
                "align_left", "align_right", "align_center", "justify", "no_justify",
                "serif", "sans", "mono", "color"}
# Действия, которые исполняет `main` вызовом модели (текст меняется только в файле).
TEXT_ACTIONS = {"shorter", "split_lines", "translate", "leave_orig"}
MIN_CONF = float(os.environ.get("PREPRESS_MIN_CONF", "0.4"))
_LOCK = threading.RLock()


def _h(obj) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                   default=str).encode("utf-8")).hexdigest()[:16]


def page_keys(page_texts: list, placed: list, raster_png: bytes, versions: dict) -> dict:
    """Четыре отпечатка страницы. `page_texts` — тексты мест страницы
    в порядке документа, `placed` — [(x, y, кегль, строка)] из сборки,
    `raster_png` — картинка страницы, `versions` — версии."""
    return {"text": _h(list(page_texts)),
            "lines": _h([list(p) for p in placed]),
            "raster": hashlib.sha1(raster_png or b"").hexdigest()[:16],
            "ver": _h(versions)}


WHY = {"text": "translation", "lines": "lines", "raster": "image", "ver": "versions"}


def page_raster(pdf_bytes: bytes, page: int, scale: float = 1.0) -> bytes:
    """Картинка страницы для отпечатка (PNG) — через `export_qa._Doc`:
    pdfium только под общим замком (pdfium_gate)."""
    import io
    import export_qa
    from PIL import Image
    d = export_qa._Doc(pdf_bytes)
    try:
        arr = d.raster(page, scale)
    finally:
        d.close()
    buf = io.BytesIO()
    Image.fromarray(arr).convert("L").save(buf, "PNG")
    return buf.getvalue()


class PageMemory:
    """Память взгляда модели по страницам одного проекта — файл
    `{pid}.prepress.json` рядом с исходником."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"pages": {}}
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass

    def lookup(self, page: int, keys: dict) -> tuple:
        """(запись | None, причина) — запись берётся при совпадении ВСЕХ ключей."""
        rec = (self.data.get("pages") or {}).get(str(page))
        if not rec:
            return None, "new"
        old = rec.get("keys") or {}
        for k in ("ver", "text", "lines", "raster"):
            if old.get(k) != keys.get(k):
                return None, WHY[k]
        return rec, "same"

    def store(self, page: int, keys: dict, verdict: dict) -> None:
        self.data.setdefault("pages", {})[str(page)] = {"keys": keys, "verdict": verdict,
                                                       "at": time.strftime("%Y-%m-%d %H:%M")}

    def save(self) -> None:
        with _LOCK:
            tmp = self.path.with_suffix(".%d.tmp" % threading.get_ident())
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(self.path))


# ─── База выученных правил ─────────────────────────────────────────────

def place_signature(code: str, feat: dict) -> str:
    """Подпись места для правила: вид дефекта и признаки места — без текста
    клиента (правило общее на сервис)."""
    keys = ("kind", "lines", "align", "plate", "cell", "script", "ratio", "rot")
    return code + "|" + "|".join("%s=%s" % (k, feat.get(k, "")) for k in keys)


def place_features(box: dict, text: str, src: str) -> dict:
    """Признаки места из рамки раскладки (без текста): вид, строк, выключка,
    на плашке ли, в ячейке ли, письмо перевода, во сколько раз длиннее."""
    import unicodedata
    slots = box.get("slots") or []
    script = ""
    for ch in text or "":
        if ch.isalpha():
            try:
                script = unicodedata.name(ch).split(" ")[0]
            except ValueError:
                script = "?"
            break
    ratio = len(text or "") / max(1, len(src or ""))
    bucket = "<0.9" if ratio < 0.9 else "<1.2" if ratio < 1.2 else "<1.5" if ratio < 1.5 else ">=1.5"
    return {"kind": "image" if box.get("image") else ("slot" if slots else "box"),
            "lines": min(3, len(slots) or int(box.get("lines") or 1)),
            "align": box.get("align") or "",
            "plate": bool(box.get("onFig") or box.get("plate")),
            "cell": bool(box.get("cell")),
            "script": script, "ratio": bucket, "rot": bool(box.get("rot"))}


class LearnedRules:
    """Правила, выученные моделью: подпись места → действие, со счётом
    подтверждений и провалов. Файл общий на сервис."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rules = {}
        try:
            self.rules = json.loads(self.path.read_text(encoding="utf-8")).get("rules") or {}
        except Exception:
            pass

    def active(self, sig: str) -> "str | None":
        r = self.rules.get(sig)
        if r and r.get("state") == "active":
            return r.get("action")
        return None

    def note(self, sig: str, action: str, ok: bool, what: str = "", doc: str = "") -> None:
        """Исход действия на месте с этой подписью. В силу правило входит
        после `LEARN_MIN_OK` подтверждений из РАЗНЫХ документов (один файл
        с десятью одинаковыми ячейками — одно свидетельство); отзывается
        при двух провалах или доле провалов больше трети."""
        if action not in ACTIONS or action == "none":
            return
        r = self.rules.setdefault(sig, {"action": action, "ok": 0, "bad": 0, "state": "candidate",
                                        "what": (what or "")[:160], "since": time.strftime("%Y-%m-%d")})
        if r.get("action") != action:
            # Другое действие на ту же подпись — спор: кандидат заново.
            if r.get("state") == "active":
                r["state"] = "revoked"
            r.update({"action": action, "ok": 0, "bad": 0})
        if ok:
            r["ok"] = int(r.get("ok") or 0) + 1
            if doc:
                docs = list(r.get("docs") or [])
                if doc not in docs:
                    docs.append(doc)
                r["docs"] = docs[-20:]
        else:
            r["bad"] = int(r.get("bad") or 0) + 1
        bad, okc = int(r.get("bad") or 0), int(r.get("ok") or 0)
        evid = len(r.get("docs") or []) if r.get("docs") else okc
        if bad >= 2 or (bad and okc + bad >= 3 and bad / max(1, okc) > 0.34):
            r["state"] = "revoked"
        elif evid >= LEARN_MIN_OK and okc >= LEARN_MIN_OK and r.get("state") == "candidate":
            r["state"] = "active"
        r["at"] = time.strftime("%Y-%m-%d %H:%M")
        if len(self.rules) > LEARN_MAX:
            # Старейшие кандидаты уходят первыми; действующие и отозванные — нет.
            cands = sorted((k for k, v in self.rules.items() if v.get("state") == "candidate"),
                           key=lambda k: self.rules[k].get("at") or "")
            for k in cands[:len(self.rules) - LEARN_MAX]:
                self.rules.pop(k, None)

    def save(self) -> None:
        with _LOCK:
            tmp = self.path.with_suffix(".%d.tmp" % threading.get_ident())
            tmp.write_text(json.dumps({"rules": self.rules}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(str(tmp), str(self.path))


# ─── Вопрос модели и разбор ответа ────────────────────────────────────

def prompt(src: str, tgt: str, places: list) -> str:
    """Вопрос сильной модели о странице: оригинал слева, выгрузка справа
    (страница бывает разрезана на плитки — все плитки одной страницы в одном
    вопросе), места перевода пронумерованы. Ответ — коды и действия из
    закрытого списка; свободный текст исполняться не будет. Перечень «НЕ
    дефектов» обязателен (критик-верстальщик 23.10.2026): без него модель
    зовёт дефектом законный перенос и удлинение перевода."""
    lines = [
        "You are a meticulous typesetter doing the FINAL check of a translated page before it is "
        "delivered to the client. Each image shows the ORIGINAL on the left and the TRANSLATED "
        "export on the right (source %s, target %s); a page may come as several tiles. Numbered "
        "red boxes on the right mark the places where the translation was printed." % (src or "?", tgt or "?"),
        "The translated page must match the original: same position, size class, typeface class, "
        "weight, colour and alignment; nothing outside its box, cell, plate, frame or page; nothing "
        "overlapping; no source-language text left (except names, numbers, codes, formulas, URLs, "
        "e-mails, legal names); nothing lost; table rules, frames, stamps, signatures and logos "
        "intact; no leftovers of erased glyphs (dots, accents); no visible patch of a different "
        "colour; readable contrast.",
        "NOT defects (do not report): a different line break position or one more line inside the "
        "same box; the translation being longer or shorter than the original; condensed type when "
        "space is tight; type up to ~10% smaller than the original in tables and labels; untranslated "
        "names, codes, formulas, numbers; stamps, signatures and logos left in the original language; "
        "a different font FILE of the same class — the export is printed with Noto Sans / Noto Serif "
        "/ a monospace face, so report FONT only when the CLASS (serif, sans, mono), the weight or "
        "the style (italic) differs from the original.",
        "Look closely at small details: dots and accents above letters, thin table rules, frame "
        "lines, stamp rings, logo shapes, edges of coloured plates. Report EVERY visible defect, "
        "even subtle ones; confidence 0..1 says how sure you are that the defect is VISIBLE on the "
        "right page (not how sure the fix will help). Name one place and one action per defect. "
        "Place 0 is allowed only for OTHER and MISSING.",
        "Actions (closed list): tight — shrink to stay inside its place; wide — use free space "
        "beside it; solo — do not flow into neighbouring blocks; erase — erase the original more "
        "widely; keep_rule — do not paint over the line/stamp/frame next to it; lines2 — allow one "
        "more line inside the place; keep_breaks — keep the original line breaks (verse, menu, "
        "address); cond — use condensed type; leave_orig — leave this place in the original "
        "(stamp, signature, logo, code); shorter — the text cannot fit, give a shorter translation "
        "in 'text' with the same meaning, numbers, units and codes; align_left/align_right/"
        "align_center/justify/no_justify — alignment as in the original; serif/sans/mono — "
        "typeface class as in the original; color — print with the text colour of the original; "
        "split_lines — separate items of the original (dish name and its description, label and "
        "form field, two lines of different style) were merged into one block: print each original "
        "line separately in its own style; translate — this place still shows source-language text "
        "that must be translated; none — no automatic fix.",
        "Codes: UNTRANSLATED — source-language text left; OVERFLOW — text goes outside its box, "
        "cell, plate, logo, frame or page; OVERLAP — text overlaps other text or graphics; SMALL — "
        "text clearly smaller than the same kind of text in the original; SIZE — text clearly larger; "
        "FONT — typeface class/weight/style differs (e.g. monospace instead of sans); ALIGN — "
        "alignment differs; MERGED — separate items merged into one; FRAGMENT — one item split "
        "apart; RULE_CUT — a table rule or frame line is cut, broken, faded or missing; MARK_LOST — "
        "a stamp, signature or logo is erased or damaged; GHOST — remnants of the original glyphs "
        "(dots, accents, strokes) are left; PATCH — a visible patch or notch of a different colour "
        "or texture; CONTRAST — text hard to read on its background; MISSING — something of the "
        "original is lost (incl. form fields ____); COLOR — text colour differs from the original "
        "(e.g. black instead of blue); BLUR — blurred text; OTHER — anything else, "
        "describe the new kind of defect in 'what' (no client text).",
        'Answer ONLY JSON: {"ok": true|false, "defects": [{"place": 3, "code": "OVERFLOW", '
        '"action": "tight", "confidence": 0.8, "what": "short note", "text": ""}]}.',
    ]
    if places:
        lines.append("Places: " + "; ".join("%d: %s" % (p["n"], (p.get("label") or "")[:60])
                                             for p in places[:80]))
    return "\n".join(lines)


_CODE_WORDS = (("RULE_CUT", ("rule", "frame line", "border line", "gridline")),
               ("MARK_LOST", ("stamp", "signature mark", "logo", "seal")),
               ("GHOST", ("trace", "remnant", "leftover", "ghost", "dots above")),
               ("PATCH", ("patch", "notch", "smudge", "stain")),
               ("OVERFLOW", ("overflow", "outside", "beyond", "runs onto", "spills")),
               ("OVERLAP", ("overlap",)),
               ("COLOR", ("colour", "color")),
               ("SMALL", ("smaller", "tiny", "too small")),
               ("SIZE", ("larger", "bigger")),
               ("FONT", ("typeface", "font", "serif", "monospace", "condensed", "bold", "italic")),
               ("ALIGN", ("align", "centred", "centered")),
               ("MERGED", ("merged",)), ("MISSING", ("lost", "missing")),
               ("UNTRANSLATED", ("untranslated", "source language")))


def _code_from_words(what: str) -> "str | None":
    w = (what or "").lower()
    for code, words in _CODE_WORDS:
        if any(x in w for x in words):
            return code
    return None


def parse(text: str, places: list) -> dict:
    """Ответ модели → {ok, defects:[{place, key, code, action, what, text}]}; чужое отброшено."""
    t = (text or "").strip()
    a, b = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[a:b + 1]) if a >= 0 and b > a else {}
    except Exception:
        d = {}
    byn = {int(p["n"]): p for p in places}
    out = []
    for e in (d.get("defects") or [])[:20]:
        try:
            n = int(e.get("place") or 0)
        except (TypeError, ValueError):
            n = 0
        act = str(e.get("action") or "none").strip().lower()
        if act not in ACTIONS:
            act = "none"
        code = str(e.get("code") or "OTHER").strip().upper()[:20]
        if code == "OTHER":
            # Модель нередко кладёт верное описание под «прочее» (замер
            # 23.10.2026: весь узбекский счёт — OTHER с точными словами).
            code = _code_from_words(str(e.get("what") or "")) or "OTHER"
        p = byn.get(n)
        if p is None and code not in ("OTHER", "MISSING"):
            n = 0
        try:
            conf = max(0.0, min(1.0, float(e.get("confidence"))))
        except (TypeError, ValueError):
            conf = 0.5
        out.append({"place": n, "key": (p or {}).get("key"), "code": code, "action": act,
                    "confidence": round(conf, 2), "what": str(e.get("what") or "")[:200],
                    "text": str(e.get("text") or "")[:2000] if act == "shorter" else ""})
    # Дубли со швов плиток — одно место, один код.
    seen, uniq = set(), []
    for x in out:
        k = (x["place"], x["code"]) if x["place"] else (x["code"], x["what"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    ok = bool(d) and not [x for x in uniq if x["confidence"] >= MIN_CONF]
    return {"ok": ok, "defects": uniq, "parsed": bool(d)}


# ─── Картинка для модели ──────────────────────────────────────────────

TILE_W = int(os.environ.get("PREPRESS_TILE_W", "760"))     # ширина половины пары, точек
TILE_H = int(os.environ.get("PREPRESS_TILE_H", "720"))     # высота плитки, точек
TEXT_PX_MIN = float(os.environ.get("PREPRESS_TEXT_PX", "16"))  # мельчайшая строка — не мельче, точек
MAX_TILES = int(os.environ.get("PREPRESS_MAX_TILES", "12"))  # плиток на страницу (все — одним вызовом)


def page_places(items: list, page: int, pw: float, ph: float) -> list:
    """Места перевода страницы — [{n, key, box (доли листа), label, size}]
    из `export_qa.printed_items` (порядок документа)."""
    import export_qa
    out = []
    for it in items:
        if it["page"] != page or not (it.get("text") or "").strip():
            continue
        rects, sizes = [], []
        for b in it["boxes"]:
            rects += export_qa._line_rects(b, pw, ph)
            try:
                sizes.append(float(b.get("size") or 0) * (ph if b.get("frac") else 1.0))
            except (TypeError, ValueError):
                pass
        if not rects:
            continue
        box = [min(r[0] for r in rects), min(r[1] for r in rects),
               max(r[2] for r in rects), max(r[3] for r in rects)]
        out.append({"n": len(out) + 1, "key": it["key"], "box": box,
                    "label": " ".join((it.get("text") or "").split())[:60],
                    "size": min(sizes) if sizes else 10.0})
    return out


def pair_images(orig: bytes, out: bytes, page: int, places: list) -> list:
    """[(JPEG плитки «оригинал | перевод», места на ней)] — все плитки страницы
    уходят модели ОДНИМ вызовом. Масштаб — чтобы мельчайшая строка места была
    не мельче `TEXT_PX_MIN` точек; страница режется сеткой так, чтобы пара была
    не шире 2×`TILE_W`: Claude сам уменьшает картинки длиннее ~1568 точек,
    и на целой странице книги точки над «Ё» и тонкая линия таблицы пропадали бы."""
    import io
    import math
    import export_qa
    from PIL import Image, ImageDraw
    A, B = export_qa._Doc(orig), export_qa._Doc(out)
    try:
        w, h, _r = A.info(page)
        small = min([p["size"] for p in places] or [10.0])
        sc = max(TILE_W / max(1.0, w) * 0.999, TEXT_PX_MIN / max(1.0, small))
        sc = min(sc, 4.0)
        while sc > 0.5 and (math.ceil(w * sc / TILE_W) * math.ceil(h * sc / TILE_H)) > MAX_TILES:
            sc *= 0.9                   # потолок плиток: лента и плакат — мельче
        a = Image.fromarray(A.raster(page, sc))
        b = Image.fromarray(B.raster(page, sc)).resize(a.size)
    finally:
        A.close()
        B.close()
    W, H = a.size
    nc, nr = max(1, math.ceil(W / TILE_W)), max(1, math.ceil(H / TILE_H))
    tw, th = W / float(nc), H / float(nr)
    ov = 24 if (nc > 1 or nr > 1) else 0
    res = []
    for r_ in range(nr):
        for c_ in range(nc):
            x0, y0 = max(0, int(c_ * tw) - ov), max(0, int(r_ * th) - ov)
            x1, y1 = min(W, int((c_ + 1) * tw) + ov), min(H, int((r_ + 1) * th) + ov)
            ca, cb = a.crop((x0, y0, x1, y1)), b.crop((x0, y0, x1, y1))
            tw_ = x1 - x0
            pair = Image.new("RGB", (2 * tw_ + 12, y1 - y0), (230, 30, 80))
            pair.paste(ca, (0, 0))
            pair.paste(cb, (tw_ + 12, 0))
            d = ImageDraw.Draw(pair)
            mine = []
            for p in places:
                bx = p["box"]
                px0, py0, px1, py1 = bx[0] * W, bx[1] * H, bx[2] * W, bx[3] * H
                if px1 < x0 or px0 > x1 or py1 < y0 or py0 > y1:
                    continue
                mine.append(p)
                rr = (tw_ + 12 + px0 - x0 - 3, py0 - y0 - 3, tw_ + 12 + px1 - x0 + 3, py1 - y0 + 3)
                d.rectangle(rr, outline=(255, 0, 0), width=2)
                d.text((rr[0], max(0, rr[1] - 11)), str(p["n"]), fill=(255, 0, 0))
            buf = io.BytesIO()
            pair.save(buf, "JPEG", quality=88)
            res.append((buf.getvalue(), mine))
    return res


ZOOM_MAX = int(os.environ.get("PREPRESS_ZOOM_MAX", "6"))       # вырезок на страницу


def zoom_images(orig: bytes, out: bytes, page: int, suspects: list) -> list:
    """[(JPEG пары крупно, подпись)] — места, которые подозревают правила
    по пикселям (точки над «Ё», разрыв линии, стёртая печать, выщербина):
    на целой плитке модель их не видит (замер 23.10.2026), а увеличенная
    вдвое вырезка с полем — видит. `suspects` — [{box (доли листа), code}]."""
    import io
    import export_qa
    from PIL import Image
    if not suspects:
        return []
    A, B = export_qa._Doc(orig), export_qa._Doc(out)
    res = []
    try:
        w, h, _r = A.info(page)
        for s in suspects[:ZOOM_MAX]:
            bx = s.get("box")
            if not bx:
                continue
            bw, bh = max(0.02, bx[2] - bx[0]), max(0.02, bx[3] - bx[1])
            x0, y0 = max(0.0, bx[0] - bw), max(0.0, bx[1] - 1.5 * bh)
            x1, y1 = min(1.0, bx[2] + bw), min(1.0, bx[3] + 1.5 * bh)
            sc = min(6.0, 700.0 / max(1.0, (x1 - x0) * w), 700.0 / max(1.0, (y1 - y0) * h))
            a = Image.fromarray(A.raster(page, sc))
            b = Image.fromarray(B.raster(page, sc)).resize(a.size)
            W, H = a.size
            box = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
            ca, cb = a.crop(box), b.crop(box)
            pair = Image.new("RGB", (2 * ca.width + 12, ca.height), (230, 30, 80))
            pair.paste(ca, (0, 0))
            pair.paste(cb, (ca.width + 12, 0))
            buf = io.BytesIO()
            pair.save(buf, "JPEG", quality=90)
            res.append((buf.getvalue(), s.get("code") or "?"))
    finally:
        A.close()
        B.close()
    return res


# ─── Сравнение «до / после» одним вопросом (Ы5, этап 5) ─────────────
# Два независимых взгляда на страницу расходятся сами по себе на 1–2
# замечания (замер 23.10.2026), и «оценка после строго меньше» отвергала
# верные правки. Сравнение рядом устойчивее: модель видит оригинал и оба
# варианта одного места и говорит, какой ближе. Порядок вариантов на месте
# перемешан (`ab_swap`): модели склонны выбирать по позиции.
AB_MAX = int(os.environ.get("PREPRESS_AB_MAX", "8"))         # мест на страницу в одном вопросе
AB_CROP_W = int(os.environ.get("PREPRESS_AB_W", "500"))      # ширина одной вырезки, точек
AB_DIFF = float(os.environ.get("PREPRESS_AB_DIFF", "0.002"))  # доля точек, изменившихся > 32, — «место изменилось»
AB_REST = float(os.environ.get("PREPRESS_AB_REST", "0.0005"))  # доля изменившихся точек ВНЕ показанных мест — показать «остальное»


def ab_swap(key: str, rnd: int) -> bool:
    """Показывать ли «после» первым — детерминированно по месту и кругу."""
    return int(hashlib.sha1(("%s|%d" % (key, rnd)).encode()).hexdigest()[:2], 16) % 2 == 1


def _changed(a, b) -> float:
    """Доля точек, разошедшихся больше чем на 32 (тонкий разрыв линии на
    большой вырезке не тонет в среднем по бумаге)."""
    import numpy as np
    d = np.abs(np.asarray(a.convert("L"), dtype=np.int16) - np.asarray(b.convert("L"), dtype=np.int16))
    return float((d > 32).mean()) if d.size else 0.0


def page_triple(orig: bytes, a_pdf: bytes, b_pdf: bytes, page: int, width: int = 1500) -> bytes:
    """Вся страница «оригинал | 1 | 2» уменьшенной — первым кадром сравнения:
    сдвинутые соседи и задетое вне вырезок видно хотя бы общим планом."""
    import io
    import export_qa
    from PIL import Image
    O, A, B = export_qa._Doc(orig), export_qa._Doc(a_pdf), export_qa._Doc(b_pdf)
    try:
        w, h, _r = O.info(page)
        sc = min(2.0, (width / 3.0 - 8) / max(1.0, w))
        ims = [Image.fromarray(D.raster(page, sc)).convert("RGB") for D in (O, A, B)]
    finally:
        O.close()
        A.close()
        B.close()
    ims[1] = ims[1].resize(ims[0].size)
    ims[2] = ims[2].resize(ims[0].size)
    cw, ch = ims[0].size
    im = Image.new("RGB", (3 * cw + 16, ch), (230, 30, 80))
    for i, x in enumerate((0, cw + 8, 2 * cw + 16)):
        im.paste(ims[i], (x, 0))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def triple_images(orig: bytes, a_pdf: bytes, b_pdf: bytes, page: int, places: list, rnd: int = 0) -> list:
    """[(JPEG «оригинал | 1 | 2», место, swap)] — ВСЕ места, где вариант «до»
    и «после» различаются по точкам (сперва самые изменившиеся; вызывающий
    режет их на вопросы по `AB_MAX`), плюс место «_rest» — рамка изменений
    ВНЕ показанных мест (линии, плашки, сдвинутые соседи), если они есть.
    `places` — [{n, key, box (доли листа; объединение рамок обоих
    вариантов), size (пункты)}]."""
    import io
    import export_qa
    import numpy as np
    from PIL import Image, ImageDraw
    if not places:
        return []
    O, A, B = export_qa._Doc(orig), export_qa._Doc(a_pdf), export_qa._Doc(b_pdf)
    cands = []
    covered = []
    rest_box = None
    try:
        w, h, _r = O.info(page)
        # Изменения всей страницы — мелко: что останется вне вырезок мест.
        sc0 = min(1.5, 900.0 / max(1.0, w))
        fa = np.asarray(Image.fromarray(A.raster(page, sc0)).convert("L"), dtype=np.int16)
        fb = np.asarray(Image.fromarray(B.raster(page, sc0)).resize((fa.shape[1], fa.shape[0])).convert("L"),
                        dtype=np.int16)
        chg = np.abs(fa - fb) > 32
        for p in places:
            bx = p["box"]
            size = float(p.get("size") or 10.0)
            bw, bh = max(0.02, bx[2] - bx[0]), max(0.015, bx[3] - bx[1])
            # поле — и в долях места, и не меньше полутора кеглей: у узкой
            # подписи иначе не видно соседа, плашки и линии рядом
            mx, my = max(0.25 * bw, 1.5 * size / max(1.0, w)), max(0.6 * bh, 1.5 * size / max(1.0, h))
            x0, y0 = max(0.0, bx[0] - mx), max(0.0, bx[1] - my)
            x1, y1 = min(1.0, bx[2] + mx), min(1.0, bx[3] + my)
            sc = min(6.0, AB_CROP_W / max(1.0, (x1 - x0) * w), 600.0 / max(1.0, (y1 - y0) * h),
                     max(1.0, TEXT_PX_MIN / max(1.0, float(p.get("size") or 10.0))))
            ims = []
            for D in (O, A, B):
                im = Image.fromarray(D.raster(page, sc))
                W, H = im.size
                ims.append(im.crop((int(x0 * W), int(y0 * H), max(int(x0 * W) + 2, int(x1 * W)),
                                    max(int(y0 * H) + 2, int(y1 * H)))).convert("RGB"))
            ims[2] = ims[2].resize(ims[1].size)
            ims[0] = ims[0].resize(ims[1].size)
            diff = _changed(ims[1], ims[2])
            if diff < AB_DIFF:
                continue
            cands.append((diff, p, ims))
            covered.append((x0, y0, x1, y1))
        H0, W0 = chg.shape
        for (x0, y0, x1, y1) in covered:
            chg[int(y0 * H0):int(y1 * H0) + 1, int(x0 * W0):int(x1 * W0) + 1] = False
        if chg.mean() > AB_REST:
            ys, xs = np.nonzero(chg)
            rest_box = [float(xs.min()) / W0, float(ys.min()) / H0, float(xs.max() + 1) / W0, float(ys.max() + 1) / H0]
    finally:
        O.close()
        A.close()
        B.close()
    cands.sort(key=lambda t: -t[0])
    if rest_box is not None:
        # Изменения вне мест — отдельным «местом»: хуже там — круг не берётся.
        O, A, B = export_qa._Doc(orig), export_qa._Doc(a_pdf), export_qa._Doc(b_pdf)
        try:
            x0, y0, x1, y1 = rest_box
            x0, y0 = max(0.0, x0 - 0.02), max(0.0, y0 - 0.02)
            x1, y1 = min(1.0, x1 + 0.02), min(1.0, y1 + 0.02)
            sc = min(4.0, AB_CROP_W / max(1.0, (x1 - x0) * w), 600.0 / max(1.0, (y1 - y0) * h))
            ims = []
            for D in (O, A, B):
                im = Image.fromarray(D.raster(page, sc))
                W, H = im.size
                ims.append(im.crop((int(x0 * W), int(y0 * H), max(int(x0 * W) + 2, int(x1 * W)),
                                    max(int(y0 * H) + 2, int(y1 * H)))).convert("RGB"))
            ims[0], ims[2] = ims[0].resize(ims[1].size), ims[2].resize(ims[1].size)
            cands.insert(0, (1.0, {"n": 0, "key": "_rest", "box": rest_box}, ims))
        finally:
            O.close()
            A.close()
            B.close()
    res = []
    for diff, p, (io_, ia, ib) in cands:
        sw = ab_swap(p["key"], rnd)
        first, second = (ib, ia) if sw else (ia, ib)
        cw, ch = io_.size
        im = Image.new("RGB", (3 * cw + 24, ch + 16), (255, 255, 255))
        d = ImageDraw.Draw(im)
        for i, (lab, x) in enumerate((("ORIGINAL", 0), ("1", cw + 12), ("2", 2 * cw + 24))):
            im.paste((io_, first, second)[i], (x, 16))
            d.text((x + 2, 2), lab, fill=(200, 0, 0))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        res.append((buf.getvalue(), p, sw))
    return res


def ab_prompt(src: str, tgt: str) -> str:
    return "\n".join([
        "You compare two versions of the SAME translated places against the ORIGINAL (source %s, "
        "target %s). Each image is one place: ORIGINAL | version 1 | version 2." % (src or "?", tgt or "?"),
        "For each place decide which version is closer to the original as a typeset page: text inside "
        "its box/cell/plate, nothing overlapping or cut, no leftovers of the original glyphs, lines, "
        "frames, stamps intact, same style class, colour, alignment, readable size, items not merged. "
        "Do NOT judge the wording of the translation, but the text may differ on purpose (shortened "
        "or translated): if a version visibly drops words or a line that the other keeps, that is a "
        "MISSING defect of that version. The first image, if present, is the whole page "
        "ORIGINAL | 1 | 2 for overview (version order on the overview is always: 1 = before, "
        "2 = after; the places below may be shown in either order). If the difference does not "
        "matter, say same.",
        "In new1 name a visible defect that version 1 has and version 2 does not; in new2 — one "
        "that version 2 has and version 1 does not; empty if none (codes: OVERFLOW, OVERLAP, MISSING, "
        "UNTRANSLATED, RULE_CUT, MARK_LOST, GHOST, PATCH, CONTRAST, MERGED, FRAGMENT, COLOR).",
        'Answer ONLY JSON: {"places": [{"place": 1, "better": "1"|"2"|"same", "new1": "", "new2": "", '
        '"confidence": 0.8}]}.',
    ])


def ab_parse(text: str, shown: list) -> dict:
    """Ответ сравнения → {ключ места: {"better": "A"|"B"|"same", "newA": код|"",
    "newB": код|""}}; `shown` — [(место, swap)] в порядке картинок (place = номер
    картинки с 1). A — вариант «до», B — «после»."""
    t = (text or "").strip()
    a, b = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[a:b + 1]) if a >= 0 and b > a else {}
    except Exception:
        d = {}
    out = {}
    for e in d.get("places") or []:
        try:
            n = int(e.get("place") or 0)
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(shown)):
            continue
        p, sw = shown[n - 1]
        try:
            conf = float(e.get("confidence"))
        except (TypeError, ValueError):
            conf = 0.6
        bet = str(e.get("better") or "same").strip().lower()
        n1, n2 = str(e.get("new1") or "").strip().upper()[:20], str(e.get("new2") or "").strip().upper()[:20]
        if sw:                                   # 1 = «после», 2 = «до»
            bet = {"1": "B", "2": "A"}.get(bet, "same")
            newA, newB = n2, n1
        else:
            bet = {"1": "A", "2": "B"}.get(bet, "same")
            newA, newB = n1, n2
        if conf < MIN_CONF:
            bet = "same"
        out[p["key"]] = {"better": bet, "newA": newA if newA in USER_CODES else "",
                         "newB": newB if newB in USER_CODES else ""}
    return out


def ab_decide(res: dict) -> dict:
    """Итог сравнения по местам: B — лучше «после» и нового брака в нём нет;
    A — «до» лучше либо у «после» новый видимый брак; same — разницы нет."""
    good, bad, same = set(), set(), set()
    for k, r in (res or {}).items():
        if r.get("newB") and r.get("newB") != r.get("newA"):
            bad.add(k)
        elif r.get("better") == "B":
            good.add(k)
        elif r.get("better") == "A":
            bad.add(k)
        else:
            same.add(k)
    return {"good": good, "bad": bad, "same": same}


# Вес вида дефекта для решения «стало лучше» (критик-верстальщик 23.10.2026).
WEIGHT = {"OVERFLOW": 3, "OVERLAP": 3, "MISSING": 3, "UNTRANSLATED": 3, "RULE_CUT": 3,
          "MARK_LOST": 3, "GHOST": 2, "PATCH": 2, "CONTRAST": 2, "FONT": 2, "MERGED": 2,
          "FRAGMENT": 2, "SIZE": 1, "ALIGN": 1, "SMALL": 1, "BLUR": 1, "OTHER": 1}


# Что показывается человеку списком «посмотрите страницы»: видимый брак.
USER_CODES = {"OVERFLOW", "OVERLAP", "MISSING", "UNTRANSLATED", "RULE_CUT", "MARK_LOST",
              "GHOST", "PATCH", "CONTRAST", "MERGED", "FRAGMENT", "COLOR"}
WEIGHT.setdefault("COLOR", 2)


def page_score(verdict: dict) -> int:
    return sum(WEIGHT.get(d.get("code"), 1) for d in (verdict or {}).get("defects") or []
               if float(d.get("confidence") or 0) >= MIN_CONF)


# Лестница действий по виду дефекта: не помогло одно — пробуем следующее.
# Первым идёт правило (выученное), потом действие модели, потом лестница.
LADDER = {
    "OVERFLOW": ("tight", "cond", "wide", "shorter"),
    "OVERLAP": ("tight", "solo", "cond", "shorter"),
    "SMALL": ("wide", "solo"),
    "SIZE": ("tight",),
    "GHOST": ("erase",),
    "RULE_CUT": ("keep_rule",),
    "MARK_LOST": ("keep_rule", "leave_orig"),
    "PATCH": ("keep_rule",),
    "MERGED": ("split_lines", "solo", "keep_breaks"),
    "FRAGMENT": ("solo",),
    "COLOR": ("color",),
    "UNTRANSLATED": ("translate", "erase"),
}
# Взаимоисключающие правки: у места одна из группы. Не помогла прежняя —
# новая её ЗАМЕНЯЕТ (теснее не помогло → шире).
_GROUPS = [("wide", "tight"), ("align_left", "align_right", "align_center"),
           ("justify", "no_justify"), ("serif", "sans", "mono"), ("erase", "keep_rule")]
_EXCL = {a: [b for b in g if b != a] for g in _GROUPS for a in g}


def plan_round(verdicts: dict, base: dict, tried: "dict | None" = None, rules=None,
               feats: "dict | None" = None) -> dict:
    """План следующего круга правок по вердиктам: {tune, leave, short,
    applied: [(ключ, код, действие)]}. У места — одно новое действие за
    круг; уже испробованное на этом месте не повторяется."""
    tried = tried or {}
    feats = feats or {}
    out = {k: dict(v) for k, v in (base or {}).items()}
    leave, short, applied, busy = set(), set(), [], set()
    texts_: dict = {}
    for v in verdicts.values():
        for d in (v or {}).get("defects") or []:
            key = d.get("key")
            if float(d.get("confidence") or 0) < MIN_CONF or not key or key in busy:
                continue
            code = d.get("code") or "OTHER"
            cands = []
            if rules is not None and key in feats:
                ra = rules.active(place_signature(code, feats[key]))
                if ra:
                    cands.append(ra)
            cands.append(d.get("action") or "none")
            cands += list(LADDER.get(code, ()))
            done = tried.get(key) or set()
            pick = None
            for a in cands:
                a = "wide" if a == "lines2" else a
                if a in ("none", "") or a in done or (a not in TUNE_ACTIONS and a not in TEXT_ACTIONS):
                    continue
                if a in TUNE_ACTIONS and (out.get(key) or {}).get(a):
                    continue                     # уже стоит
                pick = a
                break
            if pick is None:
                continue
            busy.add(key)
            applied.append((key, code, pick))
            if pick == "leave_orig":
                leave.add(key)
            elif pick in ("shorter", "split_lines", "translate"):
                short.add(key)
                texts_.setdefault(pick, set()).add(key)
            else:
                cur = out.setdefault(key, {})
                for x in _EXCL.get(pick, []):
                    cur.pop(x, None)
                cur[pick] = 1
    return {"tune": {k: v for k, v in out.items() if v}, "leave": leave, "short": short,
            "text": texts_, "applied": applied}


def apply_tune(base: dict, applied: list) -> dict:
    """Правки сборки только из перечисленных действий (поверх `base`) —
    для приёмки по местам: полезное остаётся, вредное откатывается."""
    out = {k: dict(v) for k, v in (base or {}).items()}
    for key, _code, act in applied:
        if act in TUNE_ACTIONS:
            cur = out.setdefault(key, {})
            for x in _EXCL.get(act, []):
                cur.pop(x, None)
            cur[act] = 1
    return {k: v for k, v in out.items() if v}


def tune_from(verdicts: dict, base: dict) -> tuple:
    """Правки мест из вердиктов модели (поверх `base`) и места «оставить
    оригиналом». «Шире» и «теснее» у места взаимоисключающие; «ещё строка»
    исполняется как «шире» (запас бумаги и колонка до неё)."""
    out = {k: dict(v) for k, v in (base or {}).items()}
    leave = set()
    # Взаимоисключающие правки: у места берётся первая из группы.
    groups = [("wide", "tight"), ("align_left", "align_right", "align_center"),
              ("justify", "no_justify"), ("serif", "sans", "mono"), ("erase", "keep_rule")]
    excl = {a: [b for b in g if b != a] for g in groups for a in g}
    for v in verdicts.values():
        for d in (v or {}).get("defects") or []:
            if float(d.get("confidence") or 0) < MIN_CONF or not d.get("key"):
                continue
            act = d.get("action")
            if act == "lines2":
                act = "wide"
            if act == "shorter":
                act = "tight"           # короткий перевод — этап 3; пока — ужать на месте
            if act == "leave_orig":
                leave.add(d["key"])
                continue
            if act not in TUNE_ACTIONS:
                continue
            cur = out.setdefault(d["key"], {})
            if any(cur.get(x) for x in excl.get(act, [])):
                continue
            cur[act] = 1
    return {k: v for k, v in out.items() if v}, leave
