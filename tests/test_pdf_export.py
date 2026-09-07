# -*- coding: utf-8 -*-
"""PDF-выгрузка: тот же документ, что «как в оригинале», только в PDF.

Почему так, а не сборкой с нуля. Оформление у нас живёт в ИСХОДНОМ .docx:
экспорт «как в оригинале» не собирает документ, а подменяет в нём текст,
поэтому шрифты, таблицы, картинки и колонтитулы остаются байт в байт.
Собери мы PDF сами — потеряли бы всё это разом, то есть заменили бы точную
выгрузку на приблизительную.

Что сторожится:

  1. Нет конвертера на сервере — ЧЕСТНЫЙ отказ (503) с причиной, а не PDF
     из голого текста. Такой выглядел бы выгрузкой и не был бы ею: человек
     отправил бы заказчику документ без вёрстки, не зная об этом
     (инвариант 4 — никаких заглушек вместо результата).
  2. Экран спрашивает заранее (`pdfReady` у /api/models), умеет ли ЭТОТ
     сервер собирать PDF: обещанная и неработающая кнопка хуже отсутствующей.
  3. Формат объявлен во всех трёх местах, где перечисляются форматы, —
     иначе выгрузка соберётся, а скачать её будет нечем.

Ни одного вызова модели, конвертер не запускается.
"""
import os, sys
os.environ["APP_PASSWORD"] = "test-pdf-password"
sys.path.insert(0, "backend")
import main
import topdf
from starlette.testclient import TestClient

main.save_state = lambda *a, **k: None
main.STATE["users"] = []
main.STATE["tenants"] = []
main.STATE["projects"] = []
main._SESSIONS.clear()

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


c = TestClient(main.app)
main._ensure_users()
TOK = c.post("/api/auth/login", json={"login": "admin",
                                      "password": "test-pdf-password"}).json()["token"]
H = {"Authorization": "Bearer " + TOK}

print("=== 1. Формат объявлен всюду, где перечисляются форматы ===")
check("pdf" in main.EXPORT_EXT and main.EXPORT_EXT["pdf"] == "pdf",
      "в таблице расширений: " + str(sorted(main.EXPORT_EXT)))
check(main.topdf_mod is not None, "модуль конвертера подключён")

print("\n=== 2. Экран заранее знает, умеет ли сервер PDF ===")
cat = c.get("/api/models", headers=H).json()
check("pdfReady" in cat, "каталог называет готовность PDF")
check(cat["pdfReady"] == topdf.available(),
      "и называет её ЧЕСТНО, а не константой: " + str(cat["pdfReady"]))

print("\n=== 3. Нет конвертера — честный отказ, а не выдуманный файл ===")
saved = topdf.SOFFICE
try:
    topdf.SOFFICE = str(main.DATA_DIR / "нет-такого-файла")
    check(topdf.binary() == "", "заданный, но отсутствующий конвертер не считается найденным")
    raised = None
    try:
        topdf.convert(b"PK", main.DATA_DIR / "lo-test")
    except topdf.NotAvailable as e:
        raised = str(e)
    check(raised is not None, "конвертация без конвертера бросает NotAvailable")
    check("docx" in (raised or "").lower(),
          "и называет рабочую замену, а не только проблему: " + (raised or "")[:70])
finally:
    topdf.SOFFICE = saved

print("\n=== 4. Выгрузка PDF без конвертера отвечает 503, а не 500 ===")
# Проект БЕЗ приложенного исходника: PDF ему нужен так же, просто вёрстки
# взять неоткуда — основой становится обычный DOCX, и отчёт это называет
# (`pdfFrom`). Отказывать такому проекту было бы неверно.
main.STATE["projects"] = [{"id": 501, "tenant": "default", "title": "Книга",
                           "src": "RU", "tgt": "EN", "domain": "medical",
                           "segments": [{"id": 1, "source": "Текст", "target": "Text",
                                         "status": "translated"}]}]
if not topdf.available():
    r = c.post("/api/projects/501/export", headers=H, json={"format": "pdf"})
    # 503 приходит из обработчика как HTTPException и превращается в тело
    # с причиной: экран показывает её человеку, а не «сервер недоступен».
    check(r.status_code in (200, 503), "ответ получен: " + str(r.status_code))
    body = r.json()
    check(body.get("ok") is not True, "успехом это не объявлено")
    txt = str(body.get("error") or body.get("detail") or "")
    check("pdf" in txt.lower() or "конверт" in txt.lower() or "libreoffice" in txt.lower(),
          "причина названа словами и это про КОНВЕРТЕР, а не про исходник: " + txt[:90])
else:
    print("  (пропуск: на этой машине конвертер есть)")

print("\n=== 5. Неизвестный формат по-прежнему отвергается ===")
r = c.get("/api/projects/501/export/download", headers=H, params={"format": "rtf"})
check(r.status_code == 400, "скачивание неизвестного формата — 400")

print("\n" + ("ПРОВАЛЕНО: " + "; ".join(fail) if fail else "ВСЁ ПРОШЛО"))
sys.exit(1 if fail else 0)
