"""Верность автору: перевод и ревизия не «улучшают» факты оригинала.

Точность перевода и научная точность — разные задачи. Сомнительное
утверждение автора («пчела пролетает 65 км в час») переводится как есть,
а проверяет его редактор. Здесь проверяется, что правило стоит в настоящих
сборщиках промптов, а обратный перевод его не получает (у него своё,
более строгое). Платных вызовов нет.
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


mdl = main._resolve_model(None)

print("=== 1. Промпт перевода: правило в каждой области ===")
for dom in ("general", "medical", "legal"):
    s = main._translate_system("RU", "UZ", [], None, False, dom, mdl)
    check("do NOT correct facts, figures or claims" in s, dom + ": факты не исправлять")
    check("new meaning is not" in s, dom + ": естественный оборот разрешён, новый смысл — нет")
    # Стайл-шит «textbook: explanatory» и «expand_first» не должны читаться
    # как нарушение запрета «не объяснять»: это форма, а не смысл.
    check("form, not meaning" in s, dom + ": стиль и правила языка — форма, не спорят с правилом")

print("=== 2. Обратный перевод — своё правило, не это ===")
lit = main._translate_system("UZ", "RU", None, None, True, "general", mdl)
check("do NOT correct facts, figures or claims" not in lit,
      "literal-режим не получает правило перевода")
check("Do NOT correct, improve" in lit, "у literal-режима прежний запрет на месте")

print("=== 3. Ревизор ===")
rv = main._review_system(main._resolve_domain("general"), "RU", "UZ")
check("не исправляй факты" in rv, "ревизор не правит факты автора")
check("оценку НЕ снижай" in rv, "и не штрафует за верно переданное сомнительное")
check("«поправивший» автора, — ошибка" in rv, "а перевод, поправивший автора, считает ошибкой")

print()
print("FAIL: " + ", ".join(fail) if fail else "ALL OK")
sys.exit(1 if fail else 0)
