# -*- coding: utf-8 -*-
"""Сборка видео: окно «Субтитры в кадре» запускается, сборку можно отменить.

Что сторожится:
  1. `voice: null` в запросе сборки — не 422 (окно «в кадре» голоса не
     выбирает; кнопка «Подтвердить и собрать» отвечала «ошибкой API»);
  2. «Отменить» прерывает САМ ffmpeg (`media.CANCEL` на тике `media.run`),
     а не ждёт конца куска: процесс убит, брошено `Cancelled`;
  3. задача после отмены — `stopped`, флаг потока снят;
  4. вне потока задачи (превью кадра в API) стоп-флаг чужой задачи
     ffmpeg не убивает.

Вместо ffmpeg — спящий python, моделей и сети нет.
"""
import os, sys, time, threading
os.environ.setdefault("APP_PASSWORD", "test")
sys.path.insert(0, "backend")
import main
import media

main.save_state = lambda *a, **k: None
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. voice: null принимается ===")
r = main.MediaRenderRequest(what="burn", voice=None, style={}, quality="src")
check(r.voice is None, "запрос сборки с пустым голосом валиден")
check(main._media_voice(r.voice or "")["id"], "голос по умолчанию подставляется")

print("\n=== 2–3. отмена убивает процесс, задача остановлена ===")
SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]
job = {"id": 5, "kind": "mediarender", "project": 1, "status": "running", "params": {"what": "subs"}}
main._ACTIVE_JOB["job"] = job


def fake_render(j):
    threading.Timer(1.2, lambda: j.__setitem__("stop", True)).start()
    media.run(SLEEP, timeout=60)


real = main._job_mediarender
main._job_mediarender = fake_render
t0 = time.time()
main._job_media(job)
main._job_mediarender = real
check(time.time() - t0 < 10, "ffmpeg убит сразу, а не через 30 с: %.1f с" % (time.time() - t0))
check(job["status"] == "stopped", "задача остановлена: " + job["status"])
check(getattr(main._MEDIA_TL, "job", None) is None, "флаг потока снят")

print("\n=== 4. превью вне задачи отмена не трогает ===")
job2 = {"id": 6, "stop": True, "status": "running"}
main._ACTIVE_JOB["job"] = job2          # чужая задача с поднятым стопом
check(main._media_cancel() is False, "в потоке без своей задачи отмены нет")
out = media.run([sys.executable, "-c", "print(1)"], timeout=30)
check(out.returncode == 0, "короткая команда отработала")
main._ACTIVE_JOB["job"] = None

print("\n=== 5. стоп-флаг не затирается записью воркера ===")
# Воркер пишет задачу ЦЕЛИКОМ после каждого куска; прочитай он флаг позже,
# чем API его поставил, — `stop: false` затёр бы отмену. Проверяем сам SQL:
# настоящей базы в тесте нет.
src = open("backend/store.py", encoding="utf-8").read()
i = src.index("def save_job", src.index("class PgStore"))
body = src[i:src.index("def claim_job", i)]
check("(jobs.doc->>'stop')::boolean IS TRUE" in body and "stop" in body.split("THEN", 1)[1][:60],
      "save_job сохраняет поднятый стоп-флаг")

print()
if fail:
    print("ПРОВАЛЕНО: %d" % len(fail))
    for f in fail:
        print("  - " + f)
    sys.exit(1)
print("ВСЁ ПРОШЛО")
