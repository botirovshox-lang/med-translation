# -*- coding: utf-8 -*-
"""Правки по финальным критикам раздела Т (13.10.2026) и по сквозной
выгрузке проектов 8, 19, 20, 14:

  * фон из полос под строками — не значки списка (статья 19: каждая строка
    аннотации считалась пунктом, `pdftext.icon_backdrop`);
  * строчная буква пункта со значком — не запрет сама по себе;
  * шаблон с числом (Т16) не переставляет число («15-расм» ≠ «Расм 15»,
    книга 8) и не трогает счёт предметов («5 Cases»);
  * легенда сокращений со сдвигом записей не голосует (Т17);
  * остаток краски (Т32) не ищется на странице с оценёнными концами строк
    слоя (скан с невидимым слоем распознавания);
  * стирание внутренности букв (Т29) не съедает рамку того же цвета.
"""
import os
import sys

os.environ.setdefault("APP_PASSWORD", "test")
os.environ.setdefault("WARM_CACHES", "0")
os.environ.setdefault("DEMO_SEED", "0")
sys.path.insert(0, "backend")
import pdftext  # noqa: E402

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== Фон из полос — не значки ===")
stripes = [(35.4, 600.1, 48.3, 612.0), (35.4, 589.1, 48.3, 601.1), (35.4, 578.2, 48.3, 590.1),
           (35.4, 492.0, 48.3, 504.0)]      # последняя полоса — через отступ абзаца
bullets = [(30.0, 600.0, 36.0, 606.0), (30.0, 580.0, 36.0, 586.0), (30.0, 560.0, 36.0, 566.0)]
kept = pdftext.icon_backdrop(stripes + bullets)
check(all(b in kept for b in bullets), "маркеры через межстрочный зазор остаются")
check(not any(s in kept for s in stripes), "полосы столбиком вплотную — фон")
recs = [{"x0": 48.0, "x1": 300.0, "y": 602.0, "s": 9.0, "t": "Hotya mnogochislennye"},
        {"x0": 48.0, "x1": 300.0, "y": 591.0, "s": 9.0, "t": "dannye s ispolzovaniem"}]
pdftext._mark_icon_bullets(recs, [], stripes)
check(not any(r.get("bul") for r in recs), "строки аннотации на сером фоне — не пункты")

print("=== Строчный пункт со значком ===")
recs = [{"x0": 40.0, "x1": 200.0, "y": 600.0, "s": 8.0, "t": "первичный контакт"},
        {"x0": 40.0, "x1": 200.0, "y": 586.0, "s": 8.0, "t": "вторичный контакт"}]
icons = [(30.0, 599.0, 36.0, 605.0), (30.0, 585.0, 36.0, 591.0)]
pdftext._mark_icon_bullets(recs, [], icons)
check(recs[0].get("bul") and recs[1].get("bul"), "русские строчные пункты при значках — пункты")
recs = [{"x0": 40.0, "x1": 200.0, "y": 600.0, "s": 8.0, "t": "строка абзаца без конца"},
        {"x0": 40.0, "x1": 200.0, "y": 591.0, "s": 8.0, "t": "продолжение абзаца"}]
pdftext._mark_icon_bullets(recs, [], [(30.0, 590.0, 36.0, 596.0)])
check(not recs[1].get("bul"), "строчная строка вплотную под незаконченной — продолжение, не пункт")

print("=== Т33: точный конец строки идёт через надстрочную ссылку ===")
import pdfpages_worker  # noqa: E402
K = (34, 0)
line = [35.9, 398.2, 8.97, 283.9, "", "", 35.9, None, False, {K}]
ops = [(35.9, 398.2, 181.9, K, 398.2, True, 35.9),        # «…and memory.»
       (181.9, 402.1, 185.3, K, 402.1, True, 181.9),      # «7» надстрочно
       (185.3, 402.1, 190.1, K, 402.1, True, 185.3),      # «,8»
       (192.7, 398.2, 283.9, K, 398.2, True, 192.7)]      # «These effects have been»
pdfpages_worker._exact_ends([line], ops)
check(line[8] and abs(line[3] - 283.9) < 0.1, "конец строки — после текста за ссылкой: %s" % line[3])
far = [35.9, 398.2, 8.97, 120.0, "", "", 35.9, None, False, {K}]
ops2 = [(35.9, 398.2, 120.0, K, 398.2, True, 35.9), (260.0, 398.2, 300.0, K, 398.2, True, 260.0)]
pdfpages_worker._exact_ends([far], ops2)
check(abs(far[3] - 120.0) < 0.1, "чужой текст той же линии через зазор не цепляется: %s" % far[3])

import main  # noqa: E402


def seg(i, src, tgt, **kw):
    s = {"id": i, "source": src, "target": tgt, "status": "translated", "route": "GPT_REQUIRED",
         "provider": "gpt-x"}
    s.update(kw)
    return s


def proj(*segs, **kw):
    p = {"id": 9002, "src": "RU", "tgt": "UZ", "domain": "general", "segments": list(segs), "title": "t"}
    p.update(kw)
    return p


print("=== Т16: шаблон не переставляет число ===")
P = proj(seg(1, "текст", "матн"), seg(2, "Рис. 14", "Расм 14"), seg(3, "абзац", "хат"),
         seg(4, "Рис. 15", "15-Расм"), seg(5, "ещё", "яна"), seg(6, "Рис. 16", "Расм 16"),
         seg(7, "конец", "охир"))
texts, _g = main._twin_unify(P)
check(texts.get(4) is None, "«15-Расм» не стал «Расм 15»: %s" % texts)
check(main._tpl_side("\x01-Расм") == "S" and main._tpl_side("Расм \x01.") == "E", "место числа читается")
check(main._tpl_of("5 Cases") is None and main._tpl_of("8 Consensus Report") is not None,
      "«5 Cases» — счёт, «8 Consensus Report» — название")
P2 = proj(seg(1, "a", "а"), seg(2, "Davies and Associates 7", "Дэвис и соавт. 7"), seg(3, "b", "б"),
          seg(4, "Davies and Associates 9", "Дэвис и Ассошиэйтс 9"), seg(5, "c", "в"),
          seg(6, "Davies and Associates 11", "Дэвис и соавт. 11"), seg(7, "d", "г"))
texts, _g = main._twin_unify(P2)
check(texts.get(4) == "Дэвис и соавт. 9", "колонтитул с числом в конце по-прежнему един: %s" % texts)

print("=== Т17: сдвиг легенды не голосует ===")
LS = [seg(80, "TEE, total energy expenditure; T2D, type 2 diabetes.",
          "СД2, сахарный диабет 2 типа; СЭЗ, суммарные энергозатраты.")]
am = main._abbr_map(proj(*LS, src="EN", tgt="RU"))
check("TEE" not in am and "T2D" not in am, "пары не сошлись по цифре — легенда молчит: %s" % am)

print("=== Т32: оценённые концы — остатка нет ===")
import io  # noqa: E402
try:
    from PIL import Image
    im = Image.new("RGB", (200, 100), "white")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    blob = buf.getvalue()
    orig_tag = main.importers.figure_tag
    main.importers.figure_tag = lambda b: (0, 0.0, 0.0, 1.0, 1.0)
    orig_rects = main._layer_rects
    r1 = [10.0, 10.0, 50.0, 20.0]
    main._layer_rects = lambda lay, page: ([r1], [], [], [r1])
    rec = {"w": 200, "h": 100, "part": main.PDF_PAGE_PART + "1",
           "blocks": [{"box": [10, 10, 60, 30], "skip": "layer"}]}
    data = {"layout": {"pages": [[0, 0, 200, 100]]}}
    n = main._layer_residual_add(rec, blob, data)
    check(n == 0 and rec.get("residualSkipped") == "est", "страница из оценённых концов: %s" % rec.get("residualSkipped"))
    main.importers.figure_tag = orig_tag
    main._layer_rects = orig_rects
except ImportError:
    print("  (нет Pillow — пропуск)")

print("=== Т29: рамка того же цвета не стирается ===")
try:
    import numpy as np
    import text_paint
    rgb = np.full((40, 120, 3), 255, np.uint8)
    rgb[0:2, :] = 0                      # рамка у края вырезки — того же цвета, что буквы
    rgb[15:25, 30:34] = 0                # «буква» (штрих в 4 пикселя)
    mask = np.zeros((40, 120), bool)
    mask[15:25, 30:31] = True            # контур буквы
    mask[15:25, 33:34] = True
    em = text_paint._erase_mask(rgb, mask, np.array([0, 0, 0]), np.array([255, 255, 255]), 12.0)
    check(em[15:25, 31:33].all(), "внутренность буквы достроена")
    check(not em[0:2, :].any(), "рамка у края вырезки не стирается")
except ImportError:
    print("  (нет numpy/cv2 — пропуск)")

print()
print("ALL OK" if not fail else "FAILED: %d" % len(fail))
sys.exit(1 if fail else 0)
