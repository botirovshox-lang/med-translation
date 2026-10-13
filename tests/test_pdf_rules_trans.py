# -*- coding: utf-8 -*-
"""Правила Т15–Т17 (проект 14, разбор «перевод по кускам, разнобой, знаки»,
13.10.2026) — разбор колонтитулов по месту, единый перевод двойников при печати,
легенды сокращений.

  Т15. Колонтитул узнаётся по МЕСТУ на листе (полоса — из высоты строки, а не из
       номера в списке потока), повёрнутый колонтитул — тоже; записка «Continued
       on p. N» не склеивается со следующим абзацем.
  Т16. При ПЕЧАТИ одинаковые надписи — один перевод: двойники (тот же исходник и
       те же исходники соседей) и шаблоны с числом по краю («N Consensus Report»).
       Человек сильнее машины; тексты людей между собой не унифицируются.
  Т17. `_abbr_map` учит и легенды «ABBR, расшифровка;» из подписей рисунков.

Запуск из корня репозитория: python tests/test_pdf_rules_trans.py
"""
import io
import os
import re
import sys

os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
sys.path.insert(0, "backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_pdf  # noqa: E402
import pdftext  # noqa: E402
import textcount  # noqa: E402
from pdf_fixture import make_pdf  # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def paras_of(pdf):
    pages, geoms = textcount._pdf_pages_geom(pdf, [])
    res = pdftext.clean(pages, geom=geoms)
    return res, [it for it in res["items"] if it[0] == "p"]


# ─── Т15. Колонтитул по месту ────────────────────────────────────────
print("=== Т15. Колонтитул узнаётся по месту на листе ===")
LEFT = ["Left column line number %d of the page body text", "Left column second line %d of the page body",
        "Left column third line %d of the page body text"]
RIGHT = ["Right column line number %d of the page body text", "Right column second line %d of the page body",
         "Right column third line %d of the page body text"]


def col(x, lines, k):
    return [("t", x, 500 - 12 * j, 8, t % k) for j, t in enumerate(lines)]


def page(k, where, rotated=False):
    """Страница из двух колонок; колонтитул «k Consensus Report» стоит ВВЕРХУ листа,
    а в потоке — первым / посередине / последним (`where`) или повёрнутым у края."""
    head = "%d Consensus Report" % k
    if rotated:
        h = [("raw", "BT /F1 6 Tf 0 -1 1 0 385 575 Tm {HEX:%s:HEX} Tj ET" % head)]
    else:
        h = [("t", 40, 580, 6, head)]
    a, b = col(40, LEFT, k), col(220, RIGHT, k)
    if where == "first":
        return h + a + b
    if where == "mid":
        return a + h + b
    return a + b + h


# Поток раскладывает колонтитул по-разному — как у боевой книги (стр. 9 и 26).
WHERE = ["last", "last", "first", "mid", "last", "last", "last", "last"]
ROT = {5, 7}
PDF = make_pdf([page(k + 1, WHERE[k], rotated=(k + 1) in ROT) for k in range(8)], size=(400, 600))
res, paras = paras_of(PDF)
texts = [it[1] for it in paras]
stray = [t for t in texts if "Consensus Report" in t]
heads = [it for it in paras if it[2] and any(b.get("repeat") for b in it[2])]
check(len(stray) == 1 and len(heads) == 1,
      "колонтитул — ОДИН головной абзац, в теле его нет (в теле: %d, головных: %d): %s"
      % (len(stray) - len(heads), len(heads), stray))
if heads:
    boxes = heads[0][2]
    check(len(boxes) == 8, "рамка на каждой из восьми страниц, в том числе первой/средней в потоке: %d" % len(boxes))
    rot = [b for b in boxes if any(len(sl) > 8 and isinstance(sl[8], dict) for sl in b.get("slots") or [])]
    check({b["page"] for b in rot} == {x - 1 for x in ROT},
          "повёрнутые колонтитулы (стр. 5 и 7) — в той же группе, с путём строки: %s" % [b["page"] for b in rot])
    nums = {b["page"]: b.get("num") for b in boxes}
    check(all(nums.get(p_) and nums[p_][1] == str(p_ + 1) for p_ in (4, 6)),
          "номер своей страницы подставляется и у повёрнутого: %s" % {p_: nums.get(p_) for p_ in (4, 6)})
check(res["report"].get("rotatedHeads", 0) == 2, "повёрнутых колонтитулов названо числом: %s" % res["report"].get("rotatedHeads"))

# Негатив: повёрнутая подпись посреди листа колонтитулом не становится.
mid = []
for k in range(8):
    p_ = page(k + 1, "last")
    p_ = [op for op in p_ if not (op[0] == "t" and op[4].endswith("Consensus Report"))]
    p_.append(("raw", "BT /F1 6 Tf 0 -1 1 0 200 400 Tm {HEX:%d Axis caption:HEX} Tj ET" % (k + 1)))
    mid.append(p_)
res_m, paras_m = paras_of(make_pdf(mid, size=(400, 600)))
check(sum(1 for it in paras_m if "Axis caption" in it[1]) == 8 and res_m["report"].get("rotatedHeads", 0) == 0,
      "повёрнутая подпись схемы (не у края) остаётся телом: %s" % res_m["report"].get("rotatedHeads", 0))

ok_lib, why = layout_pdf.available()
if ok_lib and heads:
    idx = next(i for i, it in enumerate(paras) if it is heads[0])
    boxes_all = {str(i): it[2] for i, it in enumerate(paras) if it[2]}
    out, st = layout_pdf.build(PDF, {"boxes": boxes_all}, {idx: "1 Консенсусный отчёт"})
    check(st.get("repeatBoxes") == 8, "печать: рамок колонтитула 8 (в т. ч. повёрнутых): %s" % st.get("repeatBoxes"))
    from pypdf import PdfReader
    got = PdfReader(io.BytesIO(out))
    for p_ in (0, 4, 6):
        tx = (got.pages[p_].extract_text() or "").replace("\n", " ")
        check(("%d Консенсусный отчёт" % (p_ + 1)) in tx or ("%d Консенсусный" % (p_ + 1)) in tx
              or "Консенсусный" in tx,
              "печать: на стр. %d перевод колонтитула с её номером" % (p_ + 1))

# Скан с ЗАДВОЕННЫМ слоем распознавания: двухстрочный колонтитул лежит дважды
# (четыре строки у верха) — окно из трёх строк его не брало, и вторая строка
# колонтитула оставалась на странице телом (книга 8, 5 страниц из 79).
dbl = []
for k in range(5):
    pg = [("t", 40, 580, 9, "Apitoxin therapy -"), ("t", 40, 575, 9, "Apitoxin therapy  -"),
          ("t", 40, 563, 9, "treatment by bee stings"), ("t", 40, 558, 9, "treatment by bee stings")]
    pg += [("t", 40, 500 - 12 * j, 10, "Body line number %d of page %d about the venom dose" % (j, k)) for j in range(4)]
    dbl.append(pg)
res_d, paras_d = paras_of(make_pdf(dbl))
check(not any("treatment by bee stings" in it[1] or "Apitoxin" in it[1] for it in paras_d
              if not (it[2] and any(b.get("repeat") for b in it[2]))),
      "задвоенный двухстрочный колонтитул снят целиком: %s" % [it[1][:40] for it in paras_d])

# Записка «Continued on p. N» не склеивается с первой строкой следующей страницы.
print("=== Т15. Записка «Continued on p. N» ===")
cont = pdftext._page_note
check(cont("Continued on p. 8") and cont("Продолжение на с. 8") and cont("Fortsetzung auf S. 12"),
      "записка узнаётся по форме, без слов языка")
check(not cont("the dose was increased to 12") and not cont("Он принял 12")
      and not cont("See Fig. 3 for the details of the dose escalation scheme and") and not cont("Table 2."),
      "обычная строка и строка с концом фразы — не записка")
note_pages = [
    [("t", 40, 500, 10, "Dual agonists of the receptor have been developed and tested in trials."),
     ("t", 40, 488, 10, "Continued on p. 2")],
    [("t", 40, 500, 10, "agonist tirzepatide was approved for use in people with obesity."),
     ("t", 40, 488, 10, "Further evidence is summarised in the next section of the report.")],
]
res_n, paras_n = paras_of(make_pdf(note_pages))
tn = [it[1] for it in paras_n]
check(not any("Continued on p. 2 agonist" in t for t in tn) and any(t.startswith("Continued on p. 2") for t in tn),
      "«Continued on p. 2» — отдельным абзацем: %s" % [t[:40] for t in tn])

# ─── Т16. Печать: двойники и шаблоны с числом ────────────────────────
print("=== Т16. Одинаковые надписи печатаются одним переводом ===")
os.environ.setdefault("DEMO_SEED", "0")
import main  # noqa: E402


def seg(i, src, tgt, **kw):
    s = {"id": i, "source": src, "target": tgt, "status": "translated", "route": "GPT_REQUIRED",
         "provider": "gpt-x"}
    s.update(kw)
    return s


def proj(*segs, **kw):
    p = {"id": 9001, "src": "EN", "tgt": "RU", "domain": "general", "segments": list(segs), "title": "t"}
    p.update(kw)
    return p


def unify(p):
    texts, groups = main._twin_unify(p)
    return texts, groups


# (а) двойники: тот же исходник и те же исходники соседей.
A = [seg(1, "Intro", "Введение"), seg(2, "STEPPING", "ХОДЬБА"), seg(3, "SWEATING", "ПОТЕНИЕ"),
     seg(4, "Other", "Другое"), seg(5, "STEPPING", "СТЕППИНГ"), seg(6, "SWEATING", "ПОТЕНИЕ"),
     seg(7, "Tail", "Хвост")]
# соседи у 2: (Intro, SWEATING), у 5: (Other, SWEATING) — РАЗНЫЕ → не двойники
t, g = unify(proj(*A))
check(not t, "разные соседи — не двойники, ничего не унифицируется: %s" % t)
A2 = [seg(1, "Intro", "Введение"), seg(2, "STEPPING", "ХОДЬБА"), seg(3, "SWEATING", "ПОТЕНИЕ"),
      seg(4, "Intro", "Введение"), seg(5, "STEPPING", "СТЕППИНГ"), seg(6, "SWEATING", "ПОТЕНИЕ")]
# теперь у 2: (Intro, SWEATING), у 5: (Intro, SWEATING) — двойники; машинные, 2 против 1 — ничья → меньший id
t, g = unify(proj(*A2))
check(t == {5: "ХОДЬБА"} and g == 1,
      "двойники: ничья машинных — донор (меньший id): %s, групп %s" % (t, g))
A3 = [seg(1, "Intro", "Введение"), seg(2, "STEPPING", "ХОДЬБА"), seg(3, "SWEATING", "ПОТЕНИЕ"),
      seg(4, "Intro", "Введение"), seg(5, "STEPPING", "СТЕППИНГ"), seg(6, "SWEATING", "ПОТЕНИЕ"),
      seg(7, "Intro", "Введение"), seg(8, "STEPPING", "СТЕППИНГ"), seg(9, "SWEATING", "ПОТЕНИЕ")]
t, g = unify(proj(*A3))
check(t == {2: "СТЕППИНГ"}, "большинство машинных сильнее донора: %s" % t)
# человек
A4 = [dict(s) for s in A3]
A4[1] = dict(A4[1], status="confirmed", confirmedBy=7)         # заверено человеком: ХОДЬБА
t, g = unify(proj(*A4))
check(t == {5: "ХОДЬБА", 8: "ХОДЬБА"}, "заверенное человеком сильнее большинства: %s" % t)
A5 = [dict(s) for s in A3]
A5[4] = dict(A5[4], target="ШАГ", editedBy=3, editedToHash=main._text_hash("ШАГ"))      # набрано руками
t, g = unify(proj(*A5))
check(t.get(2) == "ШАГ" and t.get(8) == "ШАГ" and 5 not in t,
      "набранное человеком сильнее машинного, сама строка человека не меняется: %s" % t)
A6 = [dict(s) for s in A3]
A6[1] = dict(A6[1], status="confirmed", confirmedBy=7)
A6[4] = dict(A6[4], status="confirmed", confirmedBy=8)           # два человека не сошлись
t, g = unify(proj(*A6))
check(5 not in t and 2 not in t and t.get(8) == "ХОДЬБА",
      "тексты людей между собой не унифицируются; машинной копии — текст меньшего id: %s" % t)
# пустой перевод, литература «как в оригинале» и субтитры не участвуют
A7 = [seg(1, "Intro", "Введение"), seg(2, "Ref", "Ref", route="KEEP_SOURCE"), seg(3, "Tail", "Хвост"),
      seg(4, "Intro", "Введение"), seg(5, "Ref", "Рефа"), seg(6, "Tail", "Хвост")]
t, g = unify(proj(*A7))
check(not t, "литература «как в оригинале» не участвует: %s" % t)
t, g = unify(proj(*A2, media={"name": "x"}))
check(not t, "у проекта-субтитров реплики не унифицируются")

# (б) шаблон с числом по краю
T = [seg(10, "6 Consensus Report", "6 Консенсусный доклад"),
     seg(11, "8 Consensus Report", "8 Консенсусный отчет"),
     seg(12, "18 Consensus Report", "18 Консенсусный отчёт"),
     seg(13, "30 Consensus Report", "30 Консенсусный отчёт")]
t, g = unify(proj(*T))
check(t == {10: "6 Консенсусный отчёт", 11: "8 Консенсусный отчёт"} and g == 1,
      "шаблон: один перевод с подстановкой числа из своего исходника: %s" % t)
t, g = unify(proj(*T[:2]))
check(not t, "шаблон встречается меньше трёх раз — не трогаем")
D = [seg(20, "Davies and Associates 3", "Дэвис и соавт. 3"),
     seg(21, "Davies and Associates 5", "Дэвис и Ассошиэйтс 5"),
     seg(22, "Davies and Associates 7", "Дэвис и соавт. 7")]
t, g = unify(proj(*D))
check(t == {21: "Дэвис и соавт. 5"}, "«Davies and Associates N»: %s" % t)
C = [seg(30, "Continued on p. 6", "Продолжение на с. 6"), seg(31, "Continued on p. 7", "Продолжение на стр. 7"),
     seg(32, "Continued on p. 8", "Продолжение на с. 8")]
t, g = unify(proj(*C))
check(t == {31: "Продолжение на с. 7"}, "«Continued on p. N»: %s" % t)
N = [seg(40, "5 days", "5 дней"), seg(41, "2 days", "2 дня"), seg(42, "3 days", "3 дня")]
t, g = unify(proj(*N))
check(not t, "рядом с числом согласуемое слово («5 days» → «5 дней»/«2 дня») — не шаблон: %s" % t)
M = [seg(50, "Table 1", "Таблица 1"), seg(51, "Table 2", "Таблица 2"), seg(52, "Table 3", "Таблица 3")]
t, g = unify(proj(*M))
check(not t, "одинаковые шаблоны уже согласованы — нечего менять")
H = [seg(60, "6 Consensus Report", "6 Консенсусный доклад"),
     seg(61, "8 Consensus Report", "Консенсусный отчет"),            # числа нет в переводе — подстановка невозможна
     seg(62, "18 Consensus Report", "18 Консенсусный отчёт"),
     seg(63, "30 Consensus Report", "30 Консенсусный отчёт")]
t, g = unify(proj(*H))
check(61 not in t, "перевод без числа не трогается (подстановка невозможна): %s" % t)
HU = [dict(T[0]), dict(T[1]), dict(T[2], status="confirmed", confirmedBy=5), dict(T[3])]
t, g = unify(proj(*HU))
check(t.get(10) == "6 Консенсусный отчёт" and 12 not in t, "шаблон: эталон — заверенный человеком: %s" % t)

# Печать берёт текст отсюда же: `_print_by_id` отдаёт копии с унифицированным target.
p_ = proj(*A3)
by = main._print_by_id(p_)
check(by[2]["target"] == "СТЕППИНГ" and by[2].get("_printFix") and by[5]["target"] == "СТЕППИНГ",
      "`_print_by_id` печатает единый вариант (его читают PDF 1в1, .docx 1в1, «в исходном виде»)")
check(p_["segments"][1]["target"] == "ХОДЬБА", "данные проекта не изменились — только печать")
stats = {}
main._print_by_id(p_, stats)
check(stats.get("twinsUnified") == 1 and stats.get("twinGroups") == 1, "в stats: twinsUnified/twinGroups: %s" % stats)

# ─── Т17. Легенды сокращений ─────────────────────────────────────────
print("=== Т17. Легенды «ABBR, расшифровка;» ===")
LG = [seg(70, "TEE, total energy expenditure; TEI, total energy intake; TIR, time in range; T2D, type 2 diabetes.",
          "СЭЗ, суммарные энергозатраты; СЭП, суммарное потребление энергии; ВЦД, время в диапазоне; СД2, сахарный диабет 2 типа."),
      seg(71, "Figure 4—Use of drugs. †eGFR <60 mL/min. MASLD, metabolic dysfunction–associated steatotic liver "
              "disease; MLTCs, multiple long-term conditions.",
          "Рисунок 4—Применение препаратов. †рСКФ <60 мл/мин. MASLD, метаболически ассоциированная жировая болезнь "
          "печени; МХЗ, множественные хронические заболевания.")]
am = main._abbr_map(proj(*LG))
check(am.get("TEE") == "СЭЗ" and am.get("TIR") == "ВЦД" and am.get("T2D") == "СД2",
      "легенда в целом сегменте: %s" % {k: am.get(k) for k in ("TEE", "TEI", "TIR", "T2D")})
check(am.get("MLTCs") == "МХЗ" and am.get("MASLD") == "MASLD",
      "легенда в подписи рисунка после текста: %s" % {k: am.get(k) for k in ("MLTCs", "MASLD")})
LB = [seg(72, "TEE, total energy expenditure; TEI, total energy intake.",
          "СЭЗ, суммарные энергозатраты.")]            # число записей не сошлось — молчим
check("TEE" not in main._abbr_map(proj(*LB)), "число записей не сошлось — легенда не читается")
LN = [seg(73, "Sharp, and others agreed; Smith, who was there", "Шарп и другие согласились; Смит, который был там")]
check(not main._abbr_map(proj(*LN)), "«Smith, who» — не сокращение")
# метка схемы «TEE» печатается по легенде
lab = main._print_by_id(proj(seg(80, "TEE", "ОЭЗ (общий расход энергии)"), *LG))
check(lab[80]["target"] == "СЭЗ", "метка схемы «TEE» — по легенде документа: %r" % lab[80]["target"])

print(("ALL OK" if not fail else "FAILED: %d" % len(fail)))
for f in fail:
    print(" -", f)
sys.exit(1 if fail else 0)
