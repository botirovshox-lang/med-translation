"""Вес back-check: долевой штраф, апелляция к судье и бесплатный пересчёт.

Разбор боевых данных (проект 2711 сегментов) показал три беды с одним корнем —
балл back-check отвечал сразу на два вопроса и оба плохо.

  1. Потеря термина штрафовалась плоскими -25 за термин. Слова термина нет
     в обратном переводе, значит recall УЖЕ упал на него, — штраф был вторым
     счётом за ту же потерю, одинаковым и для одного слова в сорокасловном
     абзаце, и для трёхсловной фразы в сегменте из восьми слов.

  2. «Потерян термин» считался ЖЁСТКОЙ находкой на длинном оригинале, то есть
     гасил судью. Претензия выведена той же грубой морфологией, что и сам балл
     (`_stems`, `_same_word_form`), и обжаловать её было некому: 303 сегмента
     боевого проекта остались с приговором, который вынесла обрезка слова.

  3. Правила подсчёта менялись 25.08 (потеря считается только по приказным
     записям, сравнение форм слова вместо обрезки основ), а `target_hash`
     сторожит ТЕКСТ, не правила. 798 сегментов остались с оценками по старым
     правилам, и пересчитать их не мог никто. Отсюда `BACKCHECK_VERSION`
     и бесплатный пересчёт из сохранённого обратного перевода.

Отдельно проверяется то, что этими правками чуть не сломали:
  • судья, снявший претензию, не заводит её заново строкой причины
    в `_repair_findings` (иначе — платный заход ремонта с известным исходом);
  • «судья ещё не смотрел» считает ОДИН предикат — и для состава прогона,
    и для признака, уезжающего браузеру, иначе под соседними кнопками встанут
    противоречащие числа;
  • у ремонта появился бесплатный счётчик потерянных приказных терминов:
    после долевого штрафа балл такую потерю почти не замечает;
  • полосы шкалы посажены на пороги, по которым принимаются решения;
  • отсев «это не словарная запись» не выносит «Гепатит С».

Платных вызовов нет: пересчёт по построению идёт из сохранённых данных,
а ремонт и его перепроверки подменены.
"""
import os, sys, json, shutil, tempfile
from pathlib import Path
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main
import checks as medical_qa

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def seg_of(sid, source, target, **kw):
    s = {"id": sid, "source": source, "target": target, "status": "translated"}
    h = main._text_hash(target.strip())
    if "bc" in kw:
        s["backcheck"] = dict(kw["bc"], target_hash=h)
    if "tc" in kw:
        s["termcheck"] = dict(kw["tc"], target_hash=h)
    return s


def project_of(segments, glossary=()):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [dict(g) for g in glossary],
                  "tm": [], "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main._ANALYSIS_CACHE.clear()
    main._IMPACT_CACHE.clear()
    return proj


VERIFIED = {"src": "туберкулёз лёгких", "tgt": "pulmonary tuberculosis", "tier": "verified"}
HINT = {"src": "больного", "tgt": "patient", "tier": "auto"}

LONG_SRC = ("Клиника очагового туберкулёз лёгких у взрослых пациентов при "
            "длительном течении болезни с постепенным нарастанием симптомов и "
            "медленным формированием остаточных изменений лёгочной ткани.")
LONG_BACK = ("Клиника очагового лёгочного поражения у взрослых пациентов при "
             "длительном течении болезни с постепенным нарастанием симптомов и "
             "медленным формированием остаточных изменений лёгочной ткани.")


# ─────────── 1. Штраф за термин — доля сегмента, а не плоское число ───────────
print("=== 1. Штраф долевой: одно слово из сорока не стоит четверти шкалы ===")
pen_long = medical_qa._term_lost_penalty(LONG_SRC, ["туберкулёз лёгких"])
check(0 < pen_long < 8,
      "два слова из двух десятков — штраф в пределах нескольких пунктов, "
      "а не четверть шкалы (было -25): %.1f" % pen_long)
pen_all = medical_qa._term_lost_penalty("туберкулёз лёгких", ["туберкулёз лёгких"])
check(round(pen_all) == medical_qa.BACKCHECK_PENALTY["term_lost_full"],
      "в предельном случае — когда потерянные термины и есть весь сегмент — "
      "штраф равен прежнему потолку 50")
check(medical_qa._term_lost_penalty(LONG_SRC, ["туберкулёз лёгких", "Туберкулёз лёгких"])
      == pen_long,
      "один и тот же термин, пришедший дважды, считается один раз: потеряна "
      "одна пара, а glossary_matches вправе отдать её обеими формами")
check(medical_qa._term_lost_penalty("", ["термин"])
      == medical_qa.BACKCHECK_PENALTY["term_lost_full"],
      "мерить нечем (в оригинале нет содержательных слов) — берём предельный "
      "случай, а не делим на ноль")

# Правка не только смягчает: на коротком сегменте доля велика, и штраф выше
# прежних 25. Называть её послаблением было бы неправдой.
pen_short = medical_qa._term_lost_penalty("острый туберкулёз лёгких",
                                          ["туберкулёз лёгких"])
check(pen_short > 25,
      "на коротком оригинале доля велика, и штраф СТРОЖЕ прежнего: %.0f" % pen_short)


# ─────────── 2. Потеря термина больше не гасит судью ───────────
print("\n=== 2. Потерянный термин — не жёсткая находка ни при какой длине ===")
res_long = medical_qa.run_backcheck(LONG_SRC, LONG_BACK, [VERIFIED])
check(res_long["terms_lost"] == ["туберкулёз лёгких"], "потеря найдена")
check(res_long["hard"] is False,
      "жёсткой она не считается: претензия выведена той же морфологией, что "
      "и сам балл, и отменить её судья вправе")
check(medical_qa.run_backcheck("Доза 5 мг", "Доза 15 мг")["hard"] is True,
      "а расхождение чисел жёсткое по-прежнему: от морфологии оно не зависит")
check(medical_qa._hard_issue([{"type": "backcheck_term_lost"}]) is False
      and medical_qa._hard_issue([{"type": "backcheck_number_mismatch"}]) is True,
      "и это записано в одном месте — _hard_issue")

lifted = medical_qa.apply_judge_verdict(
    json.loads(json.dumps(res_long)),
    {"same_meaning": True, "severity": "none", "comment": "то же понятие", "model": "t"})
check(lifted["score"] == medical_qa.JUDGE_FLOOR_NONE and lifted["terms_lost"] == [],
      "судья, прочитавший оба текста, поднимает балл и снимает претензию "
      "и на длинном сегменте — раньше он туда просто не приходил")
check(any("снято судьёй" in r for r in lifted["reasons"]),
      "улику не выбросили молча: сказано, кто её отменил")


# ─────────── 3. Снятая судьёй претензия не возвращается через ремонт ───────────
print("\n=== 3. Отречение судьи не становится поводом для ремонта ===")
# Строка отречения содержит подстроку «потерян термин», а _repair_findings
# разбирал причины подстрокой русской фразы. Сегмент попадал в состав прогона,
# ремонт получал претензию «почини то, что судья снял», правка откатывалась.
judged_seg = seg_of(1, LONG_SRC, "A long line about focal pulmonary tuberculosis.",
                    bc=dict(lifted, model="gpt-5.6-luna", back=LONG_BACK,
                            judged=True, v=main._bc_version()),
                    tc={"model": "gpt-5.6-terra", "findings": []})
proj = project_of([judged_seg], [VERIFIED])
finds = main._repair_findings(judged_seg, proj)
check(all("снято судьёй" not in f["text"] for f in finds),
      "отречение судьи поводом для ремонта не становится")
check(not any(f["kind"] == "term_lost" for f in finds),
      "и сама претензия про термин тоже: судья её снял")
check("потерян термин" not in main.BACKCHECK_OBJECTIVE_REASONS,
      "по причинам ремонт берёт только объективные находки — претензия про "
      "термин выставляется отдельной строкой, с учётом вердикта арбитра")

hard_seg = seg_of(2, "Доза 5 мг", "Dose 15 mg",
                  bc={"score": 30, "model": "gpt-5.6-luna", "back": "Доза 15 мг",
                      "reasons": ["расхождение чисел"], "terms_lost": [],
                      "judged": False, "judge_skipped": "hard", "v": main._bc_version()},
                  tc={"model": "gpt-5.6-terra", "findings": []})
proj2 = project_of([hard_seg])
check(any(f["kind"] == "backcheck" and "чисел" in f["text"]
          for f in main._repair_findings(hard_seg, proj2)),
      "расхождение чисел ремонт видит как и раньше")


# ─────────── 4. «Судья ещё не смотрел» — один предикат на всех ───────────
print("\n=== 4. Состав прогона и признак для браузера считает одна формула ===")
V = main._bc_version()
CASES = [
    ("свежая запись, судья погашен настоящей находкой",
     {"score": 30, "model": "gpt-5.6-luna", "back": "b", "reasons": ["расхождение чисел"],
      "terms_lost": [], "judged": False, "judge_skipped": "hard", "v": V}),
    ("старая запись, судья погашен потерянным термином",
     {"score": 54, "model": "gpt-5.6-luna", "back": "b", "reasons": ["потерян термин: X"],
      "terms_lost": ["X"], "judged": False, "judge_skipped": "hard"}),
    ("судья смолчал",
     {"score": 60, "model": "gpt-5.6-luna", "back": "b", "reasons": [],
      "terms_lost": [], "judged": False, "judge_skipped": "failed"}),
    ("пропущен прежней зоной",
     {"score": 55, "model": "gpt-5.6-luna", "back": "b", "reasons": [],
      "terms_lost": [], "judged": False, "judge_skipped": "zone"}),
    ("судья ответил",
     {"score": 95, "model": "gpt-5.6-luna", "back": "b", "reasons": [],
      "terms_lost": [], "judged": True, "judge_skipped": None,
      "judge": {"severity": "none"}, "v": V}),
    ("выше зоны — спорить не о чем",
     {"score": 99, "model": "gpt-5.6-luna", "back": "b", "reasons": [],
      "terms_lost": [], "judged": False, "judge_skipped": None, "v": V}),
]
ok = True
for label, bc in CASES:
    s = seg_of(9, "Длинная строка про очаговый туберкулёз лёгких у взрослых.",
               "A long line about focal tuberculosis in adults.", bc=bc)
    client = main._segment_for_client(s)["backcheck"]["needs_judge"]
    plan = (main._backcheck_cached(s, "gpt-5.6-luna", False)
            and not main._backcheck_cached(s, "gpt-5.6-luna", True))
    if client != plan:
        ok = False
        print("       расхождение (%s): браузеру %s, прогону %s" % (label, client, plan))
check(ok, "needs_judge и состав прогона отвечают одинаково во всех шести случаях")

stale_hard = seg_of(9, "Длинная строка про очаговый туберкулёз лёгких у взрослых.",
                    "A long line about focal tuberculosis in adults.", bc=CASES[1][1])
check(main._judge_pending(stale_hard) is True,
      "старая отметка «hard» из-за потерянного термина сегмент от судьи "
      "не запирает: она вынесена прежними правилами")
real_hard = seg_of(9, "Доза 5 мг", "Dose 15 mg", bc=CASES[0][1])
check(main._judge_pending(real_hard) is False,
      "а свежая отметка по расхождению чисел запирает")


# ─────────── 5. Ремонт видит потерю термина отдельным счётчиком ───────────
print("\n=== 5. После долевого штрафа балл потерю почти не замечает ===")
rs_seg = seg_of(1, LONG_SRC, "A long line about focal pulmonary tuberculosis.",
                bc={"score": 80, "model": "gpt-5.6-luna", "back": LONG_BACK,
                    "reasons": [], "terms_lost": ["туберкулёз лёгких"],
                    "judged": False, "judge_skipped": None, "v": V},
                tc={"model": "gpt-5.6-terra", "findings": []})
proj3 = project_of([rs_seg], [VERIFIED])
check(main._repair_scores(rs_seg, proj3)["terms_lost"] == 1,
      "счётчик потерянных приказных терминов есть в снимке качества")
rs_seg["target"] = "changed text"
check(main._repair_scores(rs_seg, proj3)["terms_lost"] is None,
      "и он None, когда back-check этого текста не видел: ноль у непроверенного "
      "текста означал бы «чисто», а это «неизвестно»")

rep_seg = seg_of(1, LONG_SRC, "A long line about focal pulmonary tuberculosis.",
                 bc={"score": 80, "model": "gpt-5.6-luna", "back": LONG_BACK,
                     "reasons": [], "terms_lost": ["туберкулёз лёгких"],
                     "judged": False, "judge_skipped": None, "v": V})
proj4 = project_of([rep_seg], [VERIFIED])
main._openai_repair = lambda *a, **k: "A rewritten line about focal lung disease."


def _fake_bc(seg, project, *a, **k):
    """Перепроверка, потерявшая ещё один приказной термин. Балл тот же,
    termcheck молчит — единственная измеримая потеря в новом счётчике."""
    seg["backcheck"] = {"score": 80, "model": "gpt-5.6-luna", "back": "b",
                        "reasons": [], "terms_lost": ["туберкулёз лёгких", "второй"],
                        "judged": False, "judge_skipped": None, "v": V,
                        "target_hash": main._text_hash((seg.get("target") or "").strip())}
    return {"ok": True}


def _fake_tc(seg, project, *a, **k):
    """Termcheck кандидата: ремонт спрашивает его на КАЖДОМ заходе, а не
    только когда чинил по его находкам, — иначе приёмка судейской правки
    держится на одном балле, а балл вознаграждает кальку (боевой #62).
    Подменён, потому что платных вызовов в тестах не бывает."""
    seg["termcheck"] = {"model": "gpt-5.6-terra", "findings": [],
                        "target_hash": main._text_hash((seg.get("target") or "").strip())}
    return {"ok": True}


main._run_segment_backcheck = _fake_bc
main._run_segment_termcheck = _fake_tc
out = main._run_segment_repair(rep_seg, proj4)
check(out.get("applied") is False,
      "правка, потерявшая ещё один приказной термин, откатывается")
check("приказных терминов" in (rep_seg["repair"].get("reason") or ""),
      # Стрелку из причины меняем на дефис: подпись печатается, а консоль
      # Windows по умолчанию cp1251 — тест обязан падать по существу,
      # а не по кодировке.
      "и причина названа: %s" % (rep_seg["repair"].get("reason") or "").replace(
          chr(0x2192), "->"))
check(rep_seg["target"] == "A long line about focal pulmonary tuberculosis.",
      "текст вернулся прежний")


# ─────────── 6. Бесплатный пересчёт сохранённых оценок ───────────
print("\n=== 6. Пересчёт из сохранённого обратного перевода ===")
tmp = Path(tempfile.mkdtemp())
main.BACKCHECK_RESCORE_DIR = tmp
OLD_SRC = "Проверьте правильность положения больного во время снимка по положению ключиц."
OLD_BACK = "Проверьте правильное положение пациента во время снимка по положению ключиц."
s1 = seg_of(1, OLD_SRC, "Check the correct positioning of the patient.",
            bc={"score": 53, "model": "gpt-5.6-luna", "back": OLD_BACK,
                "band": "b50", "recall": 0.607, "semantic": None,
                "reasons": ["потерян термин: больного"], "terms_lost": ["больного"],
                "judge": None, "judged": False, "judge_skipped": "hard"})
s2 = seg_of(2, LONG_SRC, "A long line about focal pulmonary tuberculosis.",
            bc={"score": 40, "model": "gpt-5.6-luna", "back": LONG_BACK,
                "reasons": [], "terms_lost": [], "semantic": None,
                "judge": {"same_meaning": True, "severity": "none",
                          "comment": "то же", "model": "t"},
                "judged": True, "judge_skipped": None})
project_of([s1, s2], [VERIFIED, HINT])

dry = main._rescore_backchecks(main.STATE, dry_run=True)
check(dry["rescored"] == 2 and dry["changed"] >= 1, "разбор считает обе записи")
check(dry["freed_judge"] == 1, "и называет, у скольких снята отметка «судья не нужен»")
check(s1["backcheck"]["score"] == 53 and "v" not in s1["backcheck"],
      "разбор ничего не меняет: dry_run по умолчанию")
check(dry["backup"] is None, "и копию не пишет — переписывать нечего")
check(dry["machine_clean"]["min_score"] == main.AUTO_APPROVE_DEFAULT["backcheck_min"],
      "порог донора в отчёте берётся из политики автоодобрения, а не пишется "
      "числом заново")

rep = main._rescore_backchecks(main.STATE)
check(s1["backcheck"]["terms_lost"] == [],
      "«больного» — подсказка, а не приказ: претензия снята")
check(s1["backcheck"]["score"] > 53,
      "балл поднялся до честного: %s" % s1["backcheck"]["score"])
check(s1["backcheck"]["v"] == main._bc_version(), "запись клеймится версией правил")
check(s1["backcheck"]["judge_skipped"] != "hard",
      "и отметка «судья не нужен» снята — она стояла из-за потерянного термина")
check(s1["backcheck"]["back"] == OLD_BACK and s1["backcheck"]["model"] == "gpt-5.6-luna",
      "оплаченный обратный перевод и его модель на месте: пересчёт не делает "
      "ни одного вызова")
check(s2["backcheck"]["score"] == medical_qa.JUDGE_FLOOR_NONE
      and s2["backcheck"]["judged"] is True,
      "вердикт судьи — оплаченная работа: он применён заново поверх свежего балла")
check(rep["backup"] and Path(rep["backup"]).exists(), "копия прежних записей записана")
check(main._rescore_backchecks(main.STATE)["rescored"] == 0,
      "повторный пересчёт не делает ничего: записи уже своей версии")
check(main._rescore_backchecks(main.STATE, dry_run=True, force=True)["rescored"] == 2,
      "а force пересчитывает и свои — этим чинят оценки после правки глоссария")

stamp = Path(rep["backup"]).stem.replace("backcheck-", "")
undone = main.rescore_backchecks_undo(stamp)
check(undone["restored"] == 2 and s1["backcheck"]["score"] == 53,
      "откат возвращает прежние оценки: массовая правка без отката недопустима")
try:
    main.rescore_backchecks_undo("../../etc/passwd")
    check(False, "откат обязан отклонять отметку времени не своего формата")
except Exception as e:
    check(getattr(e, "status_code", None) == 400,
          "имя файла склеивается из URL — что попало туда не подставляется")
shutil.rmtree(tmp, ignore_errors=True)


# ─────────── 7. Полосы шкалы посажены на пороги решений ───────────
print("\n=== 7. Полоса и порог не должны говорить разное ===")


def band(score):
    return next(b for b in medical_qa.BACKCHECK_BANDS if b["min"] <= score <= b["max"])


check(band(medical_qa.JUDGE_CAP["major"])["color"] == "red",
      "«судья: смысл расходится» (потолок 70) читается красным, а не "
      "предупреждением")
check(band(medical_qa.JUDGE_CAP["critical"])["color"] == "red",
      "и «смысл расходится грубо» (45) тоже")
check(band(int(medical_qa.BACKCHECK_SEM_ALIEN_CAP * 100))["color"] == "red",
      "и «обратный перевод про другое» (потолок 40)")
check(band(medical_qa.JUDGE_FLOOR_NONE)["min"] == medical_qa.JUDGE_FLOOR_NONE,
      "куда судья поднимает балл — там и начинается своя полоса")
check(band(main.AUTO_APPROVE_DEFAULT["backcheck_min"])["min"]
      == main.AUTO_APPROVE_DEFAULT["backcheck_min"],
      "порог донора глоссария — граница полосы, а не её середина: иначе "
      "половина полосы годится в доноры, половина нет, и это никак не видно")
check(band(main.JUDGE_ZONE[1])["max"] == main.JUDGE_ZONE[1],
      "верх зоны судьи — тоже граница: выше неё его не зовут")
prev = None
for b in sorted(medical_qa.BACKCHECK_BANDS, key=lambda x: x["min"]):
    check(prev is None or b["min"] == prev + 1, "полосы без дыр: " + b["key"])
    prev = b["max"]
check(all(medical_qa.band_of(i) for i in range(0, 101)), "и покрывают всю шкалу")

# Единственная копия списка на фронтенде обязана совпадать: до прихода
# /api/models красят по ней.
import re as _re
js = open("frontend/js/ui.jsx", encoding="utf-8").read()
lo = js.index("const BC_BANDS_FALLBACK")
# `label`/`note` обёрнуты в TR(...) — ключом словаря остаётся та же
# русская строка, поэтому сверяется она же, просто снаружи скобки.
rows = _re.findall(r'key:\s*"([^"]+)",\s*min:\s*(\d+),\s*max:\s*(\d+),'
                   r'\s*label:\s*(?:TR\()?"([^"]+)"\)?,'
                   r'\s*note:\s*(?:TR\()?"([^"]+)"\)?,\s*color:\s*"([^"]+)"',
                   js[lo:js.index("];", lo)])
py = [(b["key"], str(b["min"]), str(b["max"]), b["label"], b["note"], b["color"])
      for b in medical_qa.BACKCHECK_BANDS]
check(rows == py, "запасной список в ui.jsx совпадает с серверным до буквы")
for f in ("frontend/js/tab_editor.jsx", "frontend/js/tab_editor_detail.jsx"):
    src = open(f, encoding="utf-8").read()
    check("score >= 95" not in src and "score >= 80" not in src,
          f + ": лесенки из чисел нет — цвет берётся из полос")


# ─────────── 8. Отсев «это не словарная запись» ───────────
print("\n=== 8. Обрывок фразы в глоссарий не идёт, а «Гепатит С» идёт ===")
KEEP = [("Гепатит В", "Hepatitis B"), ("Гепатит С", "Hepatitis C"),
        ("Витамин С", "Vitamin C"), ("В-лимфоцит", "B-lymphocyte"),
        ("В лимфоциты", "B lymphocytes"), ("С реактивный белок", "C-reactive protein"),
        ("Т-хелперы", "T-helper cells"), ("боль в груди", "chest pain"),
        ("туберкулёз лёгких", "pulmonary tuberculosis"), ("in situ", "in situ"),
        ("— туберкулёз", "tuberculosis"), ("МБТ", "M. tuberculosis")]
DROP = [("в лёгких", "in the lungs"), ("у больного", "The patient"),
        ("и лечение", "and treatment"), ("при кашле", "in cough"), ("1.3", "1.3")]
for s, g in KEEP:
    check(main._looks_like_term(s, g) is True, "остаётся: %s -> %s" % (s, g))
for s, g in DROP:
    check(main._looks_like_term(s, g) is False, "отсеивается: %s -> %s" % (s, g))
# Стороны именно две. По одному оригиналу предлог от буквенной метки
# не отличить: «в лёгких» и «В лимфоциты» начинаются одинаково, а разводит
# их перевод — у обрывка фразы служебное слово стоит и там.
check(main._looks_like_term("в лёгких", "pulmonary") is True,
      "тот же оригинал с переводом БЕЗ служебного слова остаётся: это метка, "
      "а не предлог")

project_of([])
main.STATE["termQueue"] = []
c = main._queue_term("extract", "в лёгких", "in the lungs", lang="RU->EN",
                     domain="medical", project=1, segment=5)
check(c is None and not main.STATE["termQueue"], "обрывок фразы карточки не заводит")
check(main._queue_term("extract", "туберкулёз лёгких", "pulmonary tuberculosis",
                       lang="RU->EN", domain="medical", project=1, segment=5) is not None,
      "а термин заводит")
# Проверка стоит ПОСЛЕ дедупликации: иначе перестали бы расти hits у карточки,
# которая уже заведена, — то есть система молча глотала бы несогласие.
main.STATE["termQueue"].append({"id": 99, "kind": "extract", "src": "в лёгких",
                                "tgt": "in the lungs", "status": "pending", "hits": 1,
                                "lang": "RU->EN", "domain": "medical"})
again = main._queue_term("extract", "в лёгких", "in the lungs", lang="RU->EN",
                         domain="medical", project=1, segment=7)
check(again is not None and again["hits"] == 2,
      "у уже заведённой карточки счётчик растёт: отсев касается только новых")
check(main._looks_like_term("Hepatitis C", "Hepatitis C") is True,
      "для источника на другом алфавите проверка молчит — как молчат "
      "DOMAIN_RULES без правил для пары языков")

# --------- Ворота формы (_term_shape_reject): после дедупликации, conflict мимо ---------
# Прежние ворота стояли на ВХОДЕ в _queue_term и трём вещам вредили разом:
# резали conflict-карточки (которые _auto_verdict по построению отдаёт
# человеку раньше любых проверок формы), глушили рост hits/reasked у решённых
# терминов и крутили общий счётчик без лока из рабочих потоков.
print("")
print("=== Ворота формы очереди ===")
project_of([])
main.STATE["termQueue"] = []
LONG_SRC = "фиброзно-кавернозный туберкулёз лёгких у взрослых"   # 5 слов > лимита 3
# 1. conflict длиннее лимита ОБЯЗАН завестись: расхождение заверенного
# перевода с длинной записью глоссария иначе не всплывёт никогда.
c = main._queue_term("conflict", LONG_SRC, "", lang="RU->EN", domain="medical",
                     project=1, segment=5)
check(c is not None and main.STATE["termQueue"],
      "conflict длиннее лимита слов заводится — его решает человек")
# 2. Свободно предложенная пара той же длины — нет: её автоодобрение
# отвергнет всегда, у потолка ей делать нечего.
before = main._TERM_NOT_TERM[0]
check(main._queue_term("extract", LONG_SRC, "fibrocavitary pulmonary tuberculosis",
                       lang="RU->EN", domain="medical", project=1, segment=5) is None,
      "extract длиннее лимита карточки не заводит")
check(main._TERM_NOT_TERM[0] == before + 1, "и отсев посчитан (под локом)")
# 3. Ворота стоят ПОСЛЕ дедупликации: у УЖЕ заведённой длинной карточки hits
# растёт — иначе система молча глотала бы несогласие, что запрещено тем же
# правилом, что у _looks_like_term.
main.STATE["termQueue"].append({"id": 98, "kind": "extract", "src": LONG_SRC,
                                "tgt": "fibrocavitary pulmonary tuberculosis",
                                "status": "pending", "hits": 1,
                                "lang": "RU->EN", "domain": "medical"})
grown = main._queue_term("extract", LONG_SRC, "fibrocavitary pulmonary tuberculosis",
                         lang="RU->EN", domain="medical", project=1, segment=7)
check(grown is not None and grown["hits"] == 2,
      "у существующей длинной карточки hits растёт: ворота только для новых")
# 4. Предикат ОБЩИЙ: _auto_verdict больше не держит собственной копии условий.
import inspect as _insp
check("max_src_words" not in _insp.getsource(main._auto_verdict),
      "_auto_verdict читает форму через _term_shape_reject, а не копией")
check((main._auto_verdict({"kind": "extract", "src": LONG_SRC, "tgt": "x",
                           "lang": "RU->EN", "domain": "medical"},
                          {"pol": main._auto_policy("medical")})[1]
       or "").startswith("длинный термин"),
      "и отвечает той же причиной")


# --------- 9. Чего нельзя было сломать по дороге ---------
print("")
print("=== 9. Побочные последствия правок ===")
# 9.1 Проверка без балла законченной не считается. Без medical_qa run_backcheck
# не зовётся вовсе, а запись всё равно пишется — и сегмент замолкал навсегда.
noscore = seg_of(1, "Длинная строка про очаговый туберкулёз лёгких у взрослых.",
                 "A long line about focal tuberculosis in adults.",
                 bc={"score": None, "model": "gpt-5.6-luna", "back": "", "reasons": [],
                     "terms_lost": [], "judged": False, "judge_skipped": None})
check(main._backcheck_cached(noscore, "gpt-5.6-luna", False) is False
      and main._backcheck_cached(noscore, "gpt-5.6-luna", True) is False,
      "запись без балла — это «проверки не было», а не «проверено»")

# 9.2 Сегмент, который ремонт уже пробовал и откатил, не идёт на второй платный
# заход из-за того, что претензия перестала дублироваться строкой причины.
fut = seg_of(1, LONG_SRC, "A long line about focal pulmonary tuberculosis.",
             bc={"score": 80, "model": "gpt-5.6-luna", "back": LONG_BACK,
                 "reasons": ["потерян термин: туберкулёз лёгких"],
                 "terms_lost": ["туберкулёз лёгких"],
                 "judged": False, "judge_skipped": None, "v": V})
fut["repair"] = {"applied": False, "reason": "не стало лучше",
                 "source_hash": main._text_hash(fut["target"]),
                 "issues": ["термин «туберкулёз лёгких» не пережил обратный перевод",
                            "потерян термин: туберкулёз лёгких"]}
projf = project_of([fut], [VERIFIED])
check(main._repair_tried(fut) is True, "заход по этому тексту уже был")
check(main._repair_futile(fut, projf) is True,
      "и он признан бесполезным: старая запись несёт претензию дважды, "
      "а список находок теперь один — сравнение обязано это учесть")

# 9.3 Откат не выбрасывает свежую оплаченную проверку.
tmp2 = Path(tempfile.mkdtemp())
main.BACKCHECK_RESCORE_DIR = tmp2
BC_OLD = {"score": 53, "model": "gpt-5.6-luna", "back": OLD_BACK, "at": "2026-08-20 10:00",
          "reasons": ["потерян термин: больного"], "terms_lost": ["больного"],
          "semantic": None, "judged": False, "judge_skipped": "hard"}
u1 = seg_of(1, OLD_SRC, "Check the correct positioning of the patient.", bc=dict(BC_OLD))
u2 = seg_of(2, OLD_SRC, "Check the patient positioning.", bc=dict(BC_OLD))
project_of([u1, u2], [VERIFIED, HINT])
r2 = main._rescore_backchecks(main.STATE)
u2["backcheck"]["at"] = "2026-08-26 09:00"   # после пересчёта прошла НАСТОЯЩАЯ проверка
st = Path(r2["backup"]).stem.replace("backcheck-", "")
res = main.rescore_backchecks_undo(st)
check(res["restored"] == 1 and res["skipped"] == 1,
      "вернули только то, что до сих пор было результатом пересчёта")
check(u2["backcheck"]["at"] == "2026-08-26 09:00",
      "свежую оплаченную проверку откат не тронул и сказал об этом числом")

# 9.4 Пересчёт не лезет под идущий прогон: два писателя одного места.
main._JOBS[777] = {"id": 777, "project": 1, "kind": "full", "status": "running"}
try:
    main.rescore_backchecks(1, main.RescoreRequest(dry_run=False))
    check(False, "пересчёт обязан отказать, пока идёт прогон")
except Exception as e:
    check(getattr(e, "status_code", None) == 409,
          "пока идёт прогон — 409, как у /source и /images/forget")
check(main.rescore_backchecks(1, main.RescoreRequest(dry_run=True))["ok"] is True,
      "а посчитать и показать числа можно и во время прогона: разбор ничего "
      "не меняет")
main._JOBS.pop(777, None)
shutil.rmtree(tmp2, ignore_errors=True)


print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ЕСТЬ ПАДЕНИЯ: %d" % len(fail)))
sys.exit(1 if fail else 0)
