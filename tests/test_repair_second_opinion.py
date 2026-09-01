"""Другая модель — другой заход ремонта (второе мнение).

Из-за чего написано. Клеймо «такой же заход уже делали» (`_repair_clamped`)
смотрело только на отпечаток (текст + претензии + версия правил) и не знало,
КТО ходил: на боевом проекте 133 сегмента с открытыми находками плюс 104
откаченных стояли в корзине «нужен человек», хотя комментарий у той же корзины
обещал «дальше только человек ИЛИ ДРУГАЯ МОДЕЛЬ» — а другую модель отпечаток
не пускал. Теперь запись помнит, какие модели ходили на этот отпечаток
(`triedModels`; у старых записей — их `model`), и выбор другой модели ремонта
в панели запуска открывает сегмент со вторым мнением.

Правила, которые здесь сторожатся:
  1. без модели (`model=None` — экран «Анализ», `_segment_for_client`)
     клеймо держит, как раньше: обещать «возьмёт прогон» про сегмент,
     который возьмёт только смена модели, нельзя;
  2. та же модель — клеймо держит; другая — открывает;
  3. запись БЕЗ модели (неизвестно чей заход) держит клеймо для любой;
  4. список НАКАПЛИВАЕТСЯ: обе побывавшие модели закрыты, третья открыта;
  5. смена отпечатка (новые претензии) обнуляет список;
  6. `_plan_step` и `_repairable` читают одно правило: смета и работа
     не расходятся.

Платных вызовов нет: проверяются только предикаты и разбор состава.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


SRC = "Прямые солнечные лучи убивают микобактерии за 5 минут."
TGT = "Erect solar rays kill mycobacteria within 5 minutes."
FIND = {"tgt_term": "Erect solar rays", "suggestion": "Direct sunlight",
        "severity": "major", "why": "калька"}

models = [m["id"] for m in main.OPENAI_MODELS]
assert len(models) >= 3, "нужно хотя бы три модели в каталоге"
M1, M2, M3 = models[:3]


def seg_of(sid=1, tried=None, rp_model=M1, with_key=True):
    s = {"id": sid, "source": SRC, "target": TGT, "status": "translated",
         "termcheck": {"model": "gpt-5.6-terra",
                       "target_hash": main._text_hash(TGT.strip()),
                       "findings": [dict(FIND)]}}
    rp = {"applied": False, "reason": "не стало лучше",
          "source_hash": main._text_hash(TGT),
          "issues": ["«Erect solar rays»"]}
    if rp_model is not None:
        rp["model"] = rp_model
    if tried is not None:
        rp["triedModels"] = list(tried)
    s["repair"] = rp
    if with_key:
        rp["attemptKey"] = main._repair_attempt_key(s)
    return s


def project_of(segments):
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": segments}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [],
                  "termQueue": [], "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    return proj


print("(1) model=None — клеймо держит, как раньше")
s = seg_of()
check(main._repair_clamped(s) is True, "без модели клеймо держит")

print("(2) та же модель закрыта, другая открыта")
check(main._repair_clamped(s, None, M1) is True, "модель записи закрыта")
check(main._repair_clamped(s, None, M2) is False, "другая модель открыта")

print("(3) запись без модели держит клеймо для любой")
anon = seg_of(rp_model=None)
check(main._repair_clamped(anon, None, M2) is True,
      "чей заход — неизвестно, клеймо держит")

print("(4) список накапливается")
both = seg_of(tried=[M1, M2])
check(main._repair_clamped(both, None, M1) and main._repair_clamped(both, None, M2),
      "обе побывавшие закрыты")
check(main._repair_clamped(both, None, M3) is False, "третья открыта")

print("(5) смена отпечатка обнуляет список")
moved = seg_of()
moved["termcheck"]["findings"].append(
    {"tgt_term": "mycobacteria", "suggestion": "MBT",
     "severity": "major", "why": "новая претензия"})
check(main._repair_clamped(moved, None, M1) is False,
      "новые претензии — прежний заход не в счёт")
check(main._models_tried(moved, main._repair_attempt_key(moved)) == [],
      "_models_tried с чужим отпечатком пуст")
check(main._models_tried(s, s["repair"]["attemptKey"]) == [M1],
      "_models_tried старой записи выводится из её model")

print("(6) _repairable и _plan_step читают то же правило")
proj = project_of([seg_of()])
check(main._repairable(proj["segments"][0], False, proj, M1) is False,
      "_repairable: та же модель — не берём")
check(main._repairable(proj["segments"][0], False, proj, M2) is True,
      "_repairable: другая модель — берём")

plan1 = main._plan_step(proj, "repair", {"rp_model": M1}, proj["segments"],
                        set(), set())
check(plan1["count"] == 0 and any("такой же заход" in r["reason"]
                                  for r in plan1["skips"]),
      "план с той же моделью: пропуск «такой же заход»")
plan2 = main._plan_step(proj, "repair", {"rp_model": M2}, proj["segments"],
                        set(), set())
check(plan2["count"] == 1 and any("втор" in r["reason"] for r in plan2["runs"]),
      "план с другой моделью: берёт со «вторым мнением»")

print()
print("FAIL: %d" % len(fail) if fail else "OK: второе мнение другой моделью")
sys.exit(1 if fail else 0)
