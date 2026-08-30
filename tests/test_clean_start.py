"""Пустой старт: демо-данные и чужой глоссарий не приезжают к клиенту сами.

Раньше потеря файла состояния поднимала сервис с «Эпикризом — кардиология»
и «Анной Ивановой», стартовым глоссарием на 10 022 медицинские записи,
а новый проект рождался с восемью сегментами первого проекта в списке.
Теперь демо лежит файлом и включается только DEMO_SEED=1, стартовый
глоссарий пуст, новый проект — пустой. Ни одного вызова модели.
"""
import os, sys, json
os.environ.setdefault("APP_PASSWORD", "test")
os.environ.pop("DEMO_SEED", None)
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. Без DEMO_SEED старт пустой ===")
seed = main._demo_seed()
check(all(seed[k] == [] for k in ("projects", "glossary", "tm", "exportHistory", "team")),
      "все стартовые списки пусты")
check(not hasattr(main, "SEED_PROJECTS") and not hasattr(main, "SEED_GLOSSARY"),
      "констант SEED_* в коде больше нет")
src = open("backend/main.py", encoding="utf-8").read()
import re
check('"Анна Иванова"' not in src and '"Эпикриз — кардиология 2026"' not in src, "демо-данных в коде нет")
head = src.split("def _apply_migrations")[0]
check(not re.search(r"(?<!def )_load_glossary_from_tsv\(\)", head),
      "TSV при старте не читается (только лениво в миграции уровней)")

print("=== 2. С DEMO_SEED=1 демо приходит из файла ===")
main.DEMO_SEED = True
try:
    seed = main._demo_seed()
    check(len(seed["projects"]) >= 1 and seed["projects"][0]["title"].startswith("Эпикриз"),
          "demo_seed.json читается")
    check(seed["glossary"] == [], "демо не тащит медицинский глоссарий")
finally:
    main.DEMO_SEED = False

print("=== 3. Новый проект — пустой ===")
tok = main.CURRENT_SESSION.set({"tenant": "default", "user": 1, "role": "owner"})
try:
    p = main.create_project(main.CreateProjectRequest(title="t", src="RU", tgt="EN"))
    check(p["segments"] == [] and p["tenant"] == "default", "ноль сегментов, своя организация")
    main.STATE["projects"] = [x for x in main.STATE["projects"] if x["id"] != p["id"]]
finally:
    main.CURRENT_SESSION.reset(tok)

print("=== 4. Фронтенд без мока ===")
app = open("frontend/js/app.jsx", encoding="utf-8").read()
check("window.SEED" not in app, "app.jsx не читает window.SEED")
check("data.js" not in open("frontend/index.html", encoding="utf-8").read(), "data.js не подключён")
check(not os.path.exists("frontend/js/data.js"), "data.js удалён")

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
