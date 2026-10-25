# -*- coding: utf-8 -*-
"""Проверка выгрузки офисных форматов перед выдачей (раздел Ы6): Word,
Excel, PowerPoint, HTML — и детерминированная сверка текстовых форматов
(txt, csv, md, srt, vtt).

Зачем. Предпечатная проверка (раздел Ы5, `prepress.py`) смотрела только
PDF «как в оригинале», сканы и картинки: у них есть наша раскладка и листы.
Офисный файл верстает НЕ наша программа, а Word/Excel/PowerPoint у клиента,
и узнать, как он «сел», можно только напечатав его. Поэтому:

  * оригинал и выгрузка печатаются ОДНИМ движком (LibreOffice, `topdf`) —
    сравнивается вид, напечатанный одинаково (мировая практика визуальной
    регрессии: один рендерер для эталона и результата). Печать оригинала
    кэшируется по его отпечатку;
  * места перевода ищутся по ТЕКСТУ в напечатанном листе (`locate`): ключ
    места — номер абзаца/слота из карты исходника (`p<idx>`), тот же, что
    у PDF, поэтому круги правок, сравнение «до/после», память взгляда и
    перенос правок в проект (`_prepress_writeback`) работают без изменений;
  * детерминированные находки (`inspect`) — до модели: перевод не найден
    на листе, хотя оригинал на своём листе есть (CLIPPED — спрятан или
    обрезан рамкой), листов стало заметно больше (PAGES), знаки-заглушки
    вместо букв (TOFU). Это ПОДОЗРЕНИЯ: они показываются модели увеличенной
    вырезкой, а исправлением становятся только через её вердикт;
  * действия — только ТЕКСТОВЫЕ (`DOC_ACTIONS`): рычагов вёрстки у нас
    нет, вёрстку делает чужая программа. Сжимать кегль ячейки по подозрению
    нельзя: рендер LibreOffice не равен Excel клиента, и правка «под
    LibreOffice» испортила бы файл у клиента (критик плана 25.10.2026).

Текстовые форматы листа не имеют: `text_issues` сверяет слоты (число,
непереведённое, чужое письмо, время реплик, скорость чтения) без модели.

Модуль не зовёт модель и не пишет в STATE.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

OFFICE_EXTS = (".docx", ".xlsx", ".pptx", ".html", ".htm")
TEXT_EXTS = (".txt", ".csv", ".md", ".srt", ".vtt")
DOC_ACTIONS = {"shorter", "translate"}
# Ключ иглы: столько нормализованных знаков начала текста места ищется на листе.
NEEDLE = int(os.environ.get("OFFICE_QA_NEEDLE", "40"))
PAGES_GROW = float(os.environ.get("OFFICE_QA_PAGES_GROW", "1.25"))
MAX_PAGES = int(os.environ.get("PREPRESS_OFFICE_MAX_PAGES", "40"))
# Версия правил этого модуля — часть отпечатка проверки (`_prepress_code_version`
# читает сам файл, так что правка кода и так её меняет).
RULES = "ы6.1"
_TOFU = ("�", "□", "▯")


def fmt_of(ext: str) -> "str | None":
    """Класс проверки по расширению: office | text | None."""
    e = (ext or "").lower()
    if e in OFFICE_EXTS:
        return "office"
    if e in TEXT_EXTS:
        return "text"
    return None


def _norm_chars(s: str) -> list:
    """[(нормализованный знак, номер исходного знака)] — только буквы и
    цифры, без регистра и диакритики сочетания: перенос, мягкий дефис,
    лигатуры и пробелы печати на поиск не влияют."""
    out = []
    for i, ch in enumerate(s or ""):
        for c2 in unicodedata.normalize("NFKC", ch).casefold():
            if c2.isalnum():
                out.append((c2, i))
    return out


def norm(s: str) -> str:
    return "".join(c for c, _i in _norm_chars(s))


def page_texts(pdf: bytes) -> list:
    """[(ширина, высота, текст, [рамка знака])] по листам — pypdfium2 под
    общим замком pdfium (`pdfium_gate`): библиотека не потокобезопасна."""
    import pypdfium2 as pdfium
    try:
        import pdfium_gate
        lock = pdfium_gate.LOCK
    except Exception:            # вне сервиса (тесты, инструменты)
        import threading
        lock = threading.RLock()
    out = []
    with lock:
        doc = pdfium.PdfDocument(pdf)
        try:
            for i in range(len(doc)):
                page = doc[i]
                try:
                    w, h = page.get_size()
                    tp = page.get_textpage()
                    try:
                        n = tp.count_chars()
                        txt = tp.get_text_range(0, n) if n else ""
                        if len(txt) != n:
                            txt = "".join(tp.get_text_range(k, 1) or " " for k in range(n))
                        boxes = [tp.get_charbox(k) for k in range(n)]
                    finally:
                        tp.close()
                finally:
                    page.close()
                out.append((float(w), float(h), txt, boxes))
        finally:
            doc.close()
    return out


def _flat(pages: list) -> tuple:
    """Все листы одной строкой нормализованных знаков: [знак], [(лист, номер знака)]."""
    chars, where = [], []
    for pg, (_w, _h, txt, _b) in enumerate(pages):
        for c, i in _norm_chars(txt):
            chars.append(c)
            where.append((pg, i))
    return "".join(chars), where


def _lines_of(boxes: list, w: float, h: float) -> list:
    """Рамки знаков → рамки строк долями листа (y вниз)."""
    rows: list = []
    for (l, b, r, t) in boxes:
        if r <= l or t <= b:
            continue
        mid = (t + b) / 2.0
        for row in rows:
            if abs(row["mid"] - mid) <= max(1.0, 0.5 * (row["t"] - row["b"])):
                row.update(l=min(row["l"], l), r=max(row["r"], r), b=min(row["b"], b), t=max(row["t"], t))
                break
        else:
            rows.append({"mid": mid, "l": l, "r": r, "b": b, "t": t})
    return [[row["l"] / w, (h - row["t"]) / h, row["r"] / w, (h - row["b"]) / h] for row in rows]


def locate(pages: list, texts: dict, sources: "dict | None" = None) -> tuple:
    """Места перевода на напечатанных листах: ([item], {ключ: найдено}).
    item — тот же вид, что у `export_qa.printed_items` (рамки долями листа,
    `frac`), поэтому `prepress.page_places` и вырезки работают как есть.
    Поиск идёт ПО ПОРЯДКУ документа от прошлой находки (повторы одного
    текста ложатся на свои места), не нашлось дальше — с начала."""
    hay, where = _flat(pages)
    items, found = [], {}
    cur = 0
    for idx in sorted(texts, key=lambda x: int(x)):
        t = texts.get(idx) or ""
        nt = norm(t)
        if len(nt) < 2:
            continue
        needle = nt[:NEEDLE]
        pos = hay.find(needle, cur)
        if pos < 0:
            pos = hay.find(needle)
        if pos < 0:
            found["p%d" % int(idx)] = False
            continue
        end = pos + len(nt)
        if hay[pos:end] != nt and len(nt) > NEEDLE:
            tail = nt[-min(20, len(nt)):]
            e2 = hay.find(tail, pos, pos + int(len(nt) * 1.6) + 40)
            end = e2 + len(tail) if e2 >= 0 else min(len(hay), end)
        end = min(end, len(where))
        cur = end
        found["p%d" % int(idx)] = True
        by_pg: dict = {}
        for k in range(pos, end):
            pg, ci = where[k]
            by_pg.setdefault(pg, []).append(ci)
        for pg, cis in by_pg.items():
            w, h, _txt, bx = pages[pg]
            lines = _lines_of([bx[ci] for ci in cis if ci < len(bx)], w, h)
            if not lines:
                continue
            hs = sorted(ln[3] - ln[1] for ln in lines)
            items.append({"key": "p%d" % int(idx), "page": pg, "known": True, "text": t,
                          "src": (sources or {}).get(idx) or "",
                          "boxes": [{"frac": True, "lines": lines, "size": hs[len(hs) // 2] * 0.8}]})
    return items, found


def inspect(orig_pages: list, out_pages: list, texts: dict, sources: dict, items: list,
            found: dict) -> dict:
    """Подозрения без модели: {"issues": [{key, code, page, box}]}, коды
    из `SEVERITY`/`DOC_SEVERITY`. Подозрение не исправление: правку даёт
    только вердикт модели (`plan_round` по её дефектам)."""
    issues = []
    hay_o, _w = _flat(orig_pages)
    for idx, src in (sources or {}).items():
        key = "p%d" % int(idx)
        ns = norm(src)
        if found.get(key) is False and len(ns) >= 8 and ns[:NEEDLE] in hay_o:
            issues.append({"key": key, "code": "CLIPPED", "page": None})
    no, nb = len(orig_pages), len(out_pages)
    if no and nb > max(no + 1, no * PAGES_GROW):
        issues.append({"key": None, "code": "PAGES", "page": None, "n": nb - no})
    # Заглушки печати: на листе выгрузки их больше, чем в оригинале и в САМИХ
    # переводах (заглушка, набранная в тексте, — забота проверки перевода).
    to = sum((p[2] or "").count(ch) for p in orig_pages for ch in _TOFU)
    tt = sum((t or "").count(ch) for t in (texts or {}).values() for ch in _TOFU)
    tb = sum((p[2] or "").count(ch) for p in out_pages for ch in _TOFU)
    if tb > to + tt:
        issues.append({"key": None, "code": "TOFU", "page": None, "n": tb - to})
    # Рамка места для увеличенной вырезки (`prepress.zoom_images`).
    box_of = {}
    for it in items:
        b = (it.get("boxes") or [{}])[0]
        if b.get("lines"):
            ls = b["lines"]
            box_of.setdefault(it["key"], (it["page"], [min(x[0] for x in ls), min(x[1] for x in ls),
                                                       max(x[2] for x in ls), max(x[3] for x in ls)]))
    for iss in issues:
        if iss.get("key") in box_of:
            iss["page"], iss["box"] = box_of[iss["key"]]
    return {"issues": issues, "pages": [no, nb]}


DOC_SEVERITY = {"CLIPPED": 2, "TOFU": 2}


# ─── Текстовые форматы ───────────────────────────────────────────────

_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)


def text_issues(texts: dict, sources: dict, keep: set, tgt_script: "str | None" = None,
                script_of=None, cues_a: "list | None" = None, cues_b: "list | None" = None,
                read_cps: "float | None" = None) -> list:
    """Сверка слотов текстового формата без модели: [{key, code, n?}].
    UNTRANSLATED — у слота с буквами перевод пуст, равен оригиналу или
    набран письмом оригинала (кроме законного «как в оригинале» — `keep`);
    TIMING — у субтитров время реплик разошлось с оригиналом; FAST —
    реплика читается быстрее нормы языка (совет, не брак)."""
    out = []
    for idx, src in (sources or {}).items():
        key = "p%d" % int(idx)
        if key in keep or len(_LETTERS.findall(src or "")) < 4:
            continue
        t = (texts or {}).get(idx)
        if t is None:
            continue                      # непереведённое считает выгрузка (NOT_TRANSLATED)
        if norm(t) == norm(src):
            out.append({"key": key, "code": "UNTRANSLATED"})
            continue
        if script_of and tgt_script:
            words = [w for w in re.findall(r"[^\W\d_]{3,}", t, re.UNICODE)]
            foreign = [w for w in words if script_of(w) not in (tgt_script, None)]
            if words and len(foreign) * 2 > len(words):
                out.append({"key": key, "code": "UNTRANSLATED"})
    if cues_a is not None and cues_b is not None:
        ta = [(c.get("start"), c.get("end")) for c in cues_a if c.get("start") is not None]
        tb = [(c.get("start"), c.get("end")) for c in cues_b if c.get("start") is not None]
        if ta != tb:
            out.append({"key": None, "code": "TIMING", "n": abs(len(ta) - len(tb)) or 1})
        if read_cps:
            fast = 0
            for c in cues_b:
                try:
                    dur = float(c["end"]) - float(c["start"])
                except (KeyError, TypeError, ValueError):
                    continue
                if dur > 0 and len(c.get("text") or "") / dur > read_cps * 1.3:
                    fast += 1
            if fast:
                out.append({"key": None, "code": "FAST", "n": fast})
    return out


def sha(b: bytes, ext: str) -> str:
    return hashlib.sha1((ext or "").encode() + b"\0" + (b or b"")).hexdigest()[:20]


def render_cached(data: bytes, ext: str, cache_dir: Path, profile_dir: Path, convert) -> bytes:
    """Печать документа (`convert` — `topdf.convert`) с кэшем по отпечатку:
    оригинал печатается один раз за жизнь файла, а не на каждый круг."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / ("%s.pdf" % sha(data, ext))
    if f.exists():
        return f.read_bytes()
    pdf = convert(data, profile_dir, ext=ext)
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(pdf)
    os.replace(str(tmp), str(f))
    return pdf
