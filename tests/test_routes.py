"""Таблица маршрутов: то, что ни один тест логики не проверяет.

Написано после поломки, которую не заметил ни один из шестнадцати наборов:
хелпер вставили МЕЖДУ декоратором и функцией, `@app.get(...)` достался ему,
и `/api/projects/{pid}/glossary-impact` начал отвечать 422 на любой запрос.
Логика при этом осталась исправной — молчали и питоновские тесты, и рендер
фронтенда, а на экране просто пропала карточка.

Проверяется дешёвое и общее:

  1. приватная функция (`_имя`) маршрутом быть не может — так выглядит
     съехавший декоратор, и никак иначе;
  2. каждый маршрут принимает те параметры пути, что записаны в нём самом:
     обработчик от чужой функции этого не выдержит;
  3. эндпоинты, на которых держится редактор, существуют поимённо;
  4. публичны ровно PUBLIC_API_PATHS — расширение списка открывает
     эндпоинт всему интернету (инвариант 10);
  5. на путь и метод приходится один обработчик.

Сверки «имя функции перекликается с путём» здесь НЕТ намеренно: `save_term`
на `/api/glossary` и `get_project_detail` на `/api/projects/{pid}` — законные
имена, и такая проверка кричала бы на них при каждом запуске. Съехавший
декоратор ловят пункты 1 и 2, и ловят надёжно.

Ни одного вызова модели и ни одного обращения к сети.
"""
import os, re, sys, io

os.environ.setdefault("APP_PASSWORD", "test")
os.environ["AUTHORITY_CORPUS"] = "0"
sys.path.insert(0, "backend")
import main

main.save_state = lambda *a, **k: None

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


routes = [r for r in main.app.routes if hasattr(r, "endpoint") and hasattr(r, "path")]
api = [r for r in routes if r.path.startswith("/api/")]

print("=== 1. Приватных функций среди маршрутов нет ===")
private = [(r.path, r.endpoint.__name__) for r in routes if r.endpoint.__name__.startswith("_")]
check(not private, "приватная функция маршрутом не стала" + (" — " + str(private) if private else ""))

print("\n=== 2. Обработчик принимает параметры своего пути ===")
# Съехавший декоратор виден и отсюда: у чужой функции нет ни `pid`, ни `sid`,
# зато есть свои обязательные аргументы — FastAPI ждёт их из запроса и отдаёт
# 422 на любой вызов.
import inspect
bad_sig = []
for r in api:
    want = set(re.findall(r"\{(\w+)\}", r.path))
    have = set(inspect.signature(r.endpoint).parameters)
    missing = want - have
    if missing:
        bad_sig.append((r.path, r.endpoint.__name__, sorted(missing)))
check(not bad_sig, "все параметры пути объявлены в обработчике"
      + (" — " + str(bad_sig) if bad_sig else ""))

print("\n=== 3. Эндпоинты, на которых держится редактор ===")
paths = {r.path for r in api}
for p in ["/api/health", "/api/models", "/api/projects", "/api/projects/{pid}",
          "/api/projects/{pid}/glossary-impact", "/api/projects/{pid}/analysis",
          "/api/projects/{pid}/run-plan", "/api/projects/{pid}/jobs",
          "/api/term-queue", "/api/term-queue/auto-approve", "/api/glossary/audit",
          "/api/usage"]:
    check(p in paths, "маршрут на месте: " + p)

print("\n=== 4. Публичны ровно те пути, что объявлены публичными ===")
# Инвариант 10: всё под /api/ требует токен, кроме PUBLIC_API_PATHS.
# Расширение этого списка = эндпоинт, открытый всему интернету.
pub = set(getattr(main, "PUBLIC_API_PATHS", ()))
check(pub <= paths, "в списке публичных нет несуществующих: " + str(sorted(pub - paths)))
# Двери самостоятельной регистрации публичны по своей природе: их зовёт
# человек без токена. Каждая ограничена по IP и по числу попыток, «забыли
# пароль» отвечает одинаково при любом адресе. Список закрытый: новая
# публичная дверь обязана быть осознанным решением, а не опечаткой.
check(pub == {"/api/auth/login", "/api/auth/logout", "/api/health",
              "/api/auth/signup-info", "/api/auth/register", "/api/auth/verify",
              "/api/auth/resend", "/api/auth/forgot", "/api/auth/reset"},
      "публичны только вход, выход, здоровье и двери регистрации: " + str(sorted(pub)))

print("\n=== 4b. Обработчик с {pid} ходит через get_project ===")
# Изоляция организаций держится на одном горле: get_project отвечает 404
# на чужой проект. Обработчик, взявший проект в обход него (или через
# хелпер, который его обходит), — дыра, и ловится она здесь, а не
# внимательностью. get_segment и _seg_of сами зовут get_project.
GATES = ("get_project(", "get_segment(", "_segment_checks(")   # хелперы сами зовут get_project
no_gate = []
for r in api:
    if "{pid}" not in r.path:
        continue
    src_code = inspect.getsource(r.endpoint)
    if not any(g in src_code for g in GATES):
        no_gate.append((r.path, r.endpoint.__name__))
check(not no_gate, "каждый обработчик с {pid} берёт проект через get_project"
      + (" — " + str(no_gate) if no_gate else ""))

print("\n=== 5. Один путь — один обработчик на метод ===")
seen, dup = {}, []
for r in api:
    for m in (getattr(r, "methods", None) or set()):
        key = (m, r.path)
        if key in seen and seen[key] != r.endpoint.__name__:
            dup.append((m, r.path, seen[key], r.endpoint.__name__))
        seen[key] = r.endpoint.__name__
check(not dup, "дублей маршрута нет" + (" — " + str(dup) if dup else ""))

print("\n" + ("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: " + "; ".join(fail)))
sys.exit(1 if fail else 0)
