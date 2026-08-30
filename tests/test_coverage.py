"""Покрытие проверок для пары и области проекта (`/api/projects/{pid}/coverage`).

Закон детерминированных проверок один: нет правил для пары — молчим.
Но молчание неотличимо от успеха, пока о нём не сказано, поэтому списки
«работает / молчит / через модель» считаются по ТЕМ ЖЕ таблицам, из которых
проверки берут правила. Здесь сверяется, что списки совпадают с тем, что
проверки на самом деле делают. Платных вызовов нет.
"""
import os, sys
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import main
import medical_qa as q

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


def keys(lst):
    return {i["key"] for i in lst}


print("=== 1. RU→EN / medical: бесплатные проверки работают все ===")
c = main._coverage({"src": "RU", "tgt": "EN", "domain": "medical"})
check(c["ok"] and not c["silent"], "список «молчит» пуст: %s" % [i["key"] for i in c["silent"]])
check({"morph", "domain_rules", "negation", "recall", "numbers", "glossary"} <= keys(c["works"]),
      "морфология, правила области, отрицание, балл — в «работает»")
check(len(c["model"]) >= 4, "платные проверки перечислены")

print("=== 2. ZH→AR / legal: молчит ровно то, что и правда молчит ===")
c = main._coverage({"src": "ZH", "tgt": "AR", "domain": "legal"})
s = keys(c["silent"])
check("morph" in s and "ZH" not in main._LANG_ENDINGS, "морфология молчит — таблицы окончаний нет")
check("negation" in s and not q.negation_markers("ZH"), "отрицание молчит — маркеров нет")
check("domain_rules" in s and q.rules_for("legal", "ZH", "AR") is q.EMPTY_RULES,
      "правила области молчат — записи для пары нет")
check("recall" in s, "балл по словам не измеряется — письмо без пробелов")
check(all(i.get("why") for i in c["silent"]), "у каждой молчащей проверки названа причина")
check({"numbers", "glossary", "case", "script", "dup"} <= keys(c["works"]),
      "языконезависимые работают и здесь")
check(keys(c["works"]).isdisjoint(s), "списки «работает» и «молчит» не пересекаются")

print("=== 3. DE→EN / technical: морфология есть, правил области нет ===")
c = main._coverage({"src": "DE", "tgt": "EN", "domain": "technical"})
check("morph" in keys(c["works"]) and "DE" in main._LANG_ENDINGS, "DE: таблица окончаний есть")
check("domain_rules" in keys(c["silent"]), "technical DE→EN: правил нет — сказано")
check("recall" in keys(c["works"]), "латиница с пробелами — балл измеряется")

print("=== 4. Эндпоинт ходит через get_project ===")
import inspect
check("get_project(" in inspect.getsource(main.project_coverage), "project_coverage → get_project")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
