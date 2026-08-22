"""Четыре места, где машина молча портила данные человека.

1. Medical QA снимала подтверждение с сегмента, не изменив в нём ни буквы.
2. Она же перетирала seg["risk"] — длину сегмента, по которой выбирается движок.
3. _machine_clean считала «переписанным ремонтом» текст, давно заменённый заново.
4. Запись глоссария без уровня доверия читалась как приказ модели.

STATE подменён, save_state замолчан — платных вызовов здесь нет.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


LONG = " ".join("слово%d" % i for i in range(40))     # >30 слов → risk high
SHORT = "жалобы"                                       # 1 слово   → risk low


class FakeQA:
    """Заглушка медицинского QA: возвращает заданный вердикт без вызовов модели."""
    def __init__(self, color):
        self.color = color

    def run_medical_qa(self, source, target, **kw):
        return {"literal_backcheck": {"backtranslated_ru": ""}, "qa_issues": [],
                "ui_issues": [], "term_candidates": [], "risk_score": 42,
                "risk_color": self.color, "engine_qa": "test"}


def build(status, source=LONG, risk="high", color="red"):
    seg = {"id": 1, "source": source, "target": "Complaints.", "status": status, "risk": risk}
    proj = {"id": 1, "title": "P", "src": "RU", "tgt": "EN", "domain": "medical",
            "segments": [seg]}
    main.STATE = {"projects": [proj], "glossary": [], "tm": [], "termQueue": [],
                  "exportHistory": [], "team": []}
    main._invalidate_gloss_index()
    main.medical_qa_mod = FakeQA(color)
    main.medical_qa_enabled = lambda: True
    return proj, seg


print("=== 1. Medical QA не снимает подтверждение ===")
proj, seg = build("confirmed")
seg["confirmedBy"] = "human"
main._segment_medical_qa(1, 1, run_backcheck=False)
check(seg["status"] == "confirmed", "подтверждённый сегмент остался подтверждённым")
check(seg["confirmedBy"] == "human", "отметка человека на месте")
check(seg["risk_color"] == "red", "находка при этом записана, а не потеряна")

proj, seg = build("translated")
main._segment_medical_qa(1, 1, run_backcheck=False)
check(seg["status"] == "review", "неподтверждённый с красной оценкой уходит на проверку")
proj, seg = build("translated", color="green")
main._segment_medical_qa(1, 1, run_backcheck=False)
check(seg["status"] == "qa", "чистый неподтверждённый получает статус qa")

print("\n=== 2. Medical QA не трогает risk (длину сегмента) ===")
proj, seg = build("translated", source=LONG, risk="high", color="green")
main._segment_medical_qa(1, 1, run_backcheck=False)
check(seg["risk"] == "high", "длинный сегмент остался high, а не стал low")
check(seg["risk_score"] == 42 and seg["risk_color"] == "green",
      "медицинская оценка живёт в своих полях")
# Именно на этом строится выбор движка: low → Google, остальное → GPT.
check(seg["risk"] != "low", "чистый QA не отправляет длинный сегмент в Google")

print("\n=== 3. Миграция чинит перетёртый risk ===")
st = main._apply_migrations({"projects": [{"id": 1, "segments": [
    {"id": 1, "source": LONG, "risk": "low", "risk_color": "green"},      # перетёрт QA
    {"id": 2, "source": SHORT, "risk": "critical"},                        # след старой QA
    {"id": 3, "source": LONG, "risk": "high"},                             # QA не было
]}], "glossary": [], "tm": [], "termQueue": []})
segs = {s["id"]: s for s in st["projects"][0]["segments"]}
check(segs[1]["risk"] == "high", "длинному сегменту вернули high")
check(segs[2]["risk"] == "low", "короткому — low, а не «critical»")
check(segs[3]["risk"] == "high", "нетронутый сегмент остался как был")
again = main._apply_migrations(st)
check([s["risk"] for s in again["projects"][0]["segments"]] == ["high", "low", "high"],
      "повторный запуск ничего не меняет — миграция идемпотентна")

print("\n=== 4. Запись о ремонте устаревает вместе с текстом ===")
seg = {"id": 1, "source": "жалобы", "target": "complaints", "status": "translated"}
h = main._text_hash(seg["target"])
seg["backcheck"] = {"score": 95, "target_hash": h}
seg["termcheck"] = {"findings": [], "target_hash": h, "model": "test"}
seg["repair"] = {"applied": True, "source_hash": h}
check(main._machine_clean(seg, 90) == "текст переписан автоматическим ремонтом",
      "свежий ремонт закрывает сегмент от сбора терминологии")
# Текст перевели заново — запись о ремонте больше не про него.
seg["target"] = "complaints, revised"
h2 = main._text_hash(seg["target"])
seg["backcheck"] = {"score": 95, "target_hash": h2}
seg["termcheck"] = {"findings": [], "target_hash": h2, "model": "test"}
check(main._machine_clean(seg, 90) is None,
      "после переперевода сегмент снова годится в доноры")

print("\n=== 5. Запись глоссария без уровня — подсказка, а не приказ ===")
check(main._hit_tier({"src": "задний", "tgt": "rear"}) == main.GLOSSARY_TIER_SOFT,
      "уровень по умолчанию — подсказка")
check(main._hit_tier({"src": "увеит", "tgt": "uveitis", "tier": "verified"})
      == main.GLOSSARY_TIER_HARD, "явный verified читается как приказ")
# И главное — как это выглядит в промпте: приказ модель обязана исполнить,
# подсказку вправе проигнорировать. Запись без уровня не должна принуждать.
sysmsg = main._translate_system("RU", "EN", [
    {"src": "увеит", "tgt": "uveitis", "tier": "verified"},
    {"src": "задний", "tgt": "rear"},                 # уровня нет
], None, False, "medical", main._resolve_model(None))
order, hint = sysmsg.split("Unverified glossary hints")
check("uveitis" in order, "проверенная запись уходит приказом")
check("rear" in hint, "запись без уровня уходит подсказкой, а не приказом")
check("задний → rear" not in order, "и в приказ не попадает: именно так рождалось «rear cyclitis»")
check("задний → rear" in hint, "а в подсказках она есть — с оговоркой, что часть из них неверна")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
