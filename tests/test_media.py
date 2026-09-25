"""Видео и звук: речь → субтитры с таймингом → перевод → озвучка (инвариант 38).

Сторожится:
  1. субтитры SRT/VTT: реплика — слот, текст тот же, что у сметы
     (`textcount._cue_blocks`); обратная запись не трогает ни номера,
     ни строки времени, ни шапку VTT, ни конец строки и BOM;
  2. сборка реплик из ответа распознавания: длинная фраза делится по словам
     с их временем, выдумка модели на тишине отсеивается, нахлёстов нет;
  3. загрузка кусками: докачка (409 с принятым), потолки размера и формата,
     место на диске, число одновременных загрузок, чужой — 404;
  4. «готово»: пустой проект-субтитры + задача распознавания; нет звука — 415,
     длинное — 413, страниц не хватает — распознаётся начало, совсем мало — 402;
  5. задача распознавания НАСТОЯЩИМ кодом с подменённым клиентом OpenAI:
     сегменты, .srt-оригинал, страницы, деньги поминутно, кэш кусков
     (второй заход не платит);
  6. страницы речи списывает API высшей точкой (`_book_image_pages`);
  7. выгрузка .srt и .vtt с переводом и прежним таймингом;
  8. сборка видео и озвучки (ffmpeg подменён): укладка в тайминг,
     подписанная ссылка на скачивание, подделанная и чужая ссылка — 404;
  9. удаление проекта уносит видео; видео-задачи не ставятся общей дверью;
 10. с НАСТОЯЩИМ ffmpeg (если он есть): заголовки, звук, паузы, дорожка
     субтитров и озвучки на сгенерированном ролике.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
sys.path.insert(0, "backend")
import main
import importers
import textcount
import media
from starlette.testclient import TestClient

TMP = Path(tempfile.mkdtemp(prefix="mct-media-"))
main.SOURCE_DIR = TMP / "sources"
main.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
main.EXPORT_DIR = TMP / "exports"
main.MEDIA_DIR = TMP / "media"
main.MEDIA_UPLOAD_DIR = main.MEDIA_DIR / "uploads"
main.save_state = lambda *a, **k: None
main._ensure_job_worker = lambda: None          # задачи зовём руками, без потока
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main.STATE["spend"], main.STATE["projects"] = {}, []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
main.TENANT_MAX_PAGES = 0
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. Субтитры: реплика — слот, время неприкосновенно ===")
SRT = ("﻿1\r\n00:00:01,000 --> 00:00:03,500\r\nПривет, мир.\r\nВторая строка\r\n\r\n"
       "2\r\n00:00:04,000 --> 00:00:06,000\r\n<i>Курсив</i>\r\n\r\n")
VTT = ("WEBVTT\n\nNOTE заметка\nтут\n\nintro\n00:01.000 --> 00:03.000 align:start\n<v Анна>Здравствуйте\n"
       "00:03.500 --> 00:04.000\nбез пустой строки\n")
for name, t in (("a.srt", SRT.lstrip("﻿")), ("a.vtt", VTT)):
    cl = importers.cue_list(t)
    check([c["text"] for c in cl] == textcount._cue_blocks(t), name + ": текст реплик = текст сметы")
cl = importers.cue_list(SRT)
check(cl[0]["start"] == 1.0 and cl[0]["end"] == 3.5 and cl[1]["start"] == 4.0, "время реплик разобрано")
b = SRT.encode("utf-8")
sl = importers.extract_slots("a.srt", b)
check(sl["writeback"] and sl["slots"] == ["Привет, мир. Вторая строка", "Курсив"], "srt — слоты с обратной записью")
out = importers.write_back("a.srt", b, {0: "Hello world. This is a rather long translated line that needs wrapping"})
check(out.startswith(b"\xef\xbb\xbf"), "BOM сохранён")
txt = out.decode("utf-8-sig")
check("00:00:01,000 --> 00:00:03,500\r\n" in txt and "00:00:04,000 --> 00:00:06,000\r\n" in txt,
      "строки времени и CRLF байт в байт")
check("Hello world. This is a rather long\r\ntranslated line that needs wrapping\r\n" in txt,
      "перевод — две равные строки")
check("<i>Курсив</i>" in txt, "непереведённая реплика осталась как была")
vout = importers.write_back("a.vtt", VTT.encode("utf-8"), {0: "Hello", 1: "no blank"}).decode()
check(vout.startswith("WEBVTT\n\nNOTE заметка\nтут\n\nintro\n00:01.000 --> 00:03.000 align:start\nHello\n"),
      "vtt: шапка, заметка, имя реплики и настройки на месте")
check("00:03.500 --> 00:04.000\nno blank" in vout, "реплика без пустой строки переведена на своём месте")
check(importers.wrap_cue("短い文です日本語の字幕") == ["短い文です日本語の字幕"], "письмо без пробелов не режется")
r = importers.render_cues([{"start": 1, "end": 2.5, "text": "Hi"}, {"start": 3723.4, "end": 3725, "text": "Bye"},
                           {"start": None, "end": None, "text": "x"}], ".srt")
check(r.startswith("1\n00:00:01,000 --> 00:00:02,500\nHi\n\n2\n01:02:03,400 --> 01:02:05,000\nBye"),
      "сборка .srt: номера, время часами, реплика без времени пропущена")
check(importers.render_cues([{"start": 1, "end": 2, "text": "Hi"}], ".vtt").startswith("WEBVTT\n\n00:00:01.000 -->"),
      "сборка .vtt: шапка и точка в миллисекундах")

print("=== 2. Реплики из ответа распознавания ===")
segs = [{"start": 0.0, "end": 12.0, "text": " Первая фраза очень длинная, она тянется долго. А вот и вторая часть, тоже немалая.",
         "no_speech_prob": 0.01, "avg_logprob": -0.2, "compression_ratio": 1.2},
        {"start": 12.5, "end": 14.0, "text": "Субтитры сделал кто-то", "no_speech_prob": 0.9, "avg_logprob": -1.2},
        {"start": 14.2, "end": 14.5, "text": "Да.", "no_speech_prob": 0.05, "avg_logprob": -0.3}]
words = [{"word": w, "start": i * 0.8, "end": i * 0.8 + 0.7} for i, w in enumerate(
    "Первая фраза очень длинная она тянется долго А вот и вторая часть тоже немалая".split())]
cues = media.tidy_cues(media.build_cues(segs, words, offset=600.0))
check(len(cues) >= 3 and all(c["end"] > c["start"] for c in cues), "длинная фраза поделена, время растёт")
check(all(c["end"] - c["start"] <= 6.5 for c in cues[:-1]), "реплика не длиннее ~6 с")
check(not any("Субтитры сделал" in c["text"] for c in cues), "выдумка на тишине отсеяна")
check(cues[0]["start"] == 600.0, "смещение куска прибавлено")
check(all(cues[i]["end"] <= cues[i + 1]["start"] for i in range(len(cues) - 1)), "нахлёстов нет")
check(cues[-1]["text"] == "Да." and cues[-1]["end"] - cues[-1]["start"] >= 1.0, "короткая реплика растянута до секунды")
check(media.cut_points(1300, [(590, 600), (1195, 1205)]) == [595.0, 1200.0], "граница куска — в середине паузы")
check(media.cut_points(700, []) == [600], "паузы нет — ровная отметка")
check(media.fit_tempo(3.0, 3.0) == (1.0, "ok") and media.fit_tempo(3.6, 3.0)[1] == "ok"
      and media.fit_tempo(4.2, 3.0)[1] == "fast" and media.fit_tempo(6.0, 3.0)[1] == "over", "укладка в тайминг")
check(media.output_ext({"video": {"codec": "h264"}}) == ".mp4" and media.output_ext({"video": {"codec": "vp9"}}) == ".mkv"
      and media.output_ext({"video": None}) == ".m4a", "контейнер результата по кодеку, без перекодирования")

print("=== 3. Загрузка кусками ===")
c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
A = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(A),
       json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
B = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]
media.available = lambda: (True, "")
PROBE = {"duration": 125.0, "container": "mov,mp4", "video": {"codec": "h264", "width": 1920, "height": 1080},
         "audio": {"codec": "aac", "channels": 2, "rate": 48000}, "audioTracks": 1}
media.probe = lambda path: dict(PROBE)
main._media_disk_refusal = lambda need: None
MAXB = main.MEDIA_MAX_BYTES
r = c.post("/api/media/upload", headers=H(B), json={"name": "clip.exe", "size": 10})
check(r.status_code == 415, "чужое расширение — 415")
r = c.post("/api/media/upload", headers=H(B), json={"name": "big.mp4", "size": MAXB + 1})
check(r.status_code == 413, "больше потолка — 413")
main._media_disk_refusal = lambda need: "места нет"
r = c.post("/api/media/upload", headers=H(B), json={"name": "clip.mp4", "size": 100})
check(r.status_code == 507, "места нет — 507")
main._media_disk_refusal = lambda need: None
DATA = os.urandom(3000)
main.MEDIA_CHUNK = 1024
r = c.post("/api/media/upload", headers=H(B), json={"name": "clip.mp4", "size": len(DATA), "src": "RU", "tgt": "EN"})
check(r.status_code == 200 and r.json()["chunk"] == 1024, "загрузка начата, размер куска от сервера")
tok = r.json()["token"]
r = c.post("/api/media/upload/%s/chunk?offset=0" % tok, headers=H(B), content=DATA[:1024])
check(r.status_code == 200 and r.json()["received"] == 1024, "первый кусок принят")
r = c.post("/api/media/upload/%s/chunk?offset=0" % tok, headers=H(B), content=DATA[:1024])
check(r.status_code == 409 and r.json()["received"] == 1024, "повтор не с того места — 409 и сколько принято")
r = c.post("/api/media/upload/%s/chunk?offset=1024" % tok, headers=H(B), content=os.urandom(2048))
check(r.status_code == 413, "кусок больше заявленного — 413")
r = c.get("/api/media/upload/" + tok, headers=H(A))
check(r.status_code == 404, "чужая загрузка — 404")
r = c.post("/api/media/upload", headers=H(B), json={"name": "clip.mp4", "size": len(DATA), "src": "RU", "tgt": "EN"})
check(r.status_code == 200 and r.json()["token"] == tok and r.json()["received"] == 1024,
      "докачка: тот же файл — та же загрузка, продолжаем с принятого")
r = c.post("/api/media/upload/%s/finish" % tok, headers=H(B))
check(r.status_code == 409, "«готово» до конца файла — 409")
r = c.post("/api/media/upload/%s/chunk?offset=1024" % tok, headers=H(B), content=DATA[1024:2048])
r = c.post("/api/media/upload/%s/chunk?offset=2048" % tok, headers=H(B), content=DATA[2048:] + b"x")
check(r.status_code == 400, "за объявленный размер — 400")
r = c.post("/api/media/upload/%s/chunk?offset=2048" % tok, headers=H(B), content=DATA[2048:])
check(r.json()["received"] == len(DATA), "файл принят целиком")
part = main.MEDIA_UPLOAD_DIR / (tok + ".part")
check(part.read_bytes() == DATA, "на диске ровно присланное")
r2 = c.post("/api/media/upload", headers=H(B), json={"name": "b.mp4", "size": 10})
r3 = c.post("/api/media/upload", headers=H(B), json={"name": "c.mp4", "size": 10})
check(r2.status_code == 200 and r3.status_code == 429, "третья одновременная загрузка — 429")
c.delete("/api/media/upload/" + r2.json()["token"], headers=H(B))
check(not (main.MEDIA_UPLOAD_DIR / (r2.json()["token"] + ".part")).exists(), "отмена удаляет файл загрузки")
check(not main._is_paid("POST", "/api/media/upload/%s/finish" % tok),
      "«готово» не в таблице: возврат видео бесплатен, лимит проверяет обработчик")

print("=== 4. «Готово»: проект и задача ===")
PROBE["audio"] = None
r = c.post("/api/media/upload/%s/finish" % tok, headers=H(B))
check(r.status_code == 415 and part.exists(), "без звука — 415, файл загрузки цел")
PROBE["audio"] = {"codec": "aac", "channels": 2}
PROBE["duration"] = main.MEDIA_MAX_MINUTES * 60 + 5
r = c.post("/api/media/upload/%s/finish" % tok, headers=H(B))
check(r.status_code == 413, "длиннее потолка — 413")
PROBE["duration"] = 125.0
r = c.post("/api/media/upload/%s/finish" % tok, headers=H(B))
check(r.status_code == 200, "«готово» — 200")
P = r.json()
pid = P["id"]
check(P["fileName"] == "clip.srt" and P["segments"] == [] and P["mediaStatus"] == "transcribing",
      "проект — пустой файл субтитров, идёт распознавание")
check(P["media"]["video"]["width"] == 1920 and P["media"]["duration"] == 125.0 and P["tenant"] == "beta",
      "сведения о видео и организация")
check((main.MEDIA_DIR / str(pid) / "source.mp4").read_bytes() == DATA and not part.exists(),
      "видео переехало к проекту, файл загрузки убран")
job = main._JOBS[P["jobId"]]
check(job["kind"] == "asr" and job["tenant"] == "beta" and job["params"].get("limitSec") is None,
      "задача распознавания всего видео")
r = c.post("/api/projects/%d/jobs" % pid, headers=H(B), json={"kind": "asr", "segment_ids": [1]})
check(r.status_code == 400, "видео-задачу общей дверью не поставить")


def upload(tok_user, name="x.mp4"):
    d = os.urandom(500)
    t = c.post("/api/media/upload", headers=H(tok_user), json={"name": name, "size": len(d), "src": "RU", "tgt": "EN"}).json()["token"]
    c.post("/api/media/upload/%s/chunk?offset=0" % t, headers=H(tok_user), content=d)
    return c.post("/api/media/upload/%s/finish" % t, headers=H(tok_user))


main.STATE["tenants"].append({"id": "gamma", "name": "G", "pagesCredit": 1.2, "pagesUsed": 0.0})
c.post("/api/admin/users", headers=H(A), json={"login": "gam", "password": "gam-pass-123", "role": "owner", "tenant": "gamma"})
G = c.post("/api/auth/login", json={"login": "gam", "password": "gam-pass-123"}).json().get("token")
if G:
    PROBE["duration"] = 600.0                  # ≈ 6 стр. при остатке 1.2
    r = upload(G)
    check(r.status_code == 200 and r.json().get("mediaExcerpt", {}).get("sec") == 96.0,
          "страниц мало — распознаётся начало (96 с на 1.2 стр.): %s" % r.json().get("mediaExcerpt"))
    main._tenant_rec("gamma")["pagesUsed"] = 1.0
    r = upload(G)
    check(r.status_code == 402, "остатка меньше чем на минуту — 402")
    PROBE["duration"] = 125.0
else:
    check(False, "организация gamma не завелась")

print("=== 5. Распознавание НАСТОЯЩИМ кодом, клиент подменён ===")
CALLS = {"asr": 0, "tts": 0}


class _Tr:
    def create(self, file=None, **kw):
        CALLS["asr"] += 1
        CALLS["kw"] = kw
        name = Path(getattr(file, "name", "")).name
        if name != "chunk000.mp3":
            if name == "chunk002.mp3" and not CALLS.get("failed2"):
                CALLS["failed2"] = True
                raise RuntimeError("Rate limit reached for whisper-1")
            n = int(name[5:8])
            return {"duration": 30.0, "segments": [{"start": 1.0, "end": 3.0, "text": " Кусок %d." % n,
                                                     "no_speech_prob": 0.01, "avg_logprob": -0.2,
                                                     "compression_ratio": 1.1}], "words": []}
        return {"duration": 125.0, "language": "russian",
                "segments": [{"start": 0.5, "end": 3.0, "text": " Добрый день, коллеги.", "no_speech_prob": 0.01,
                              "avg_logprob": -0.2, "compression_ratio": 1.1},
                             {"start": 3.4, "end": 6.0, "text": " Сегодня говорим о туберкулёзе.", "no_speech_prob": 0.01,
                              "avg_logprob": -0.2, "compression_ratio": 1.1}],
                "words": []}


class _Sp:
    def create(self, **kw):
        CALLS["tts"] += 1
        CALLS["voice"] = kw.get("voice")
        n = int(media.TTS_RATE * (1.0 if len(kw["input"]) < 20 else 6.0))    # 1 с или 6 с речи
        return types.SimpleNamespace(read=lambda: b"\x01\x00" * n)


class _OpenAI:
    def __init__(self, **kw):
        self.audio = types.SimpleNamespace(transcriptions=_Tr(), speech=_Sp())


sys.modules["openai"] = types.SimpleNamespace(OpenAI=_OpenAI)


def fake_extract(src, dst, duration, limit_sec=None):
    Path(dst).write_bytes(b"ID3fake")


media.extract_audio = fake_extract
media.silences = lambda audio, duration: []


def fake_split(audio, points, out_dir, duration):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for i in range(4):                        # четыре куска: две пачки по ASR_PARALLEL=3
        p = out_dir / ("chunk%03d.mp3" % i)
        p.write_bytes(b"x")
        res.append((p, 600.0 * i))
    return res


media.split_audio = fake_split
main.MEDIA_RETRY_PAUSE = 0
spent0 = main._spend_status("beta")["spentUsd"]
# Чужая задача в очереди (gamma из раздела 4) — повод уступить исполнителя
# между пачками: так и должно быть. Уступившая задача продолжает с кэша.
main._job_execute(job)
check(job["status"] == "queued" and job.get("yields") == 1, "между пачками уступила чужой задаче")
for j in list(main._JOBS.values()):
    if j["tenant"] == "gamma":
        j["status"] = "stopped"
main._job_execute(job)
proj = main._project_by_id(pid)
check(job["status"] == "done", "задача завершена: %s %s" % (job["status"], job.get("error")))
check([s["source"] for s in proj["segments"]] == ["Добрый день, коллеги.", "Сегодня говорим о туберкулёзе.",
                                                  "Кусок 1.", "Кусок 2.", "Кусок 3."],
      "реплики всех кусков стали сегментами, по порядку: %s" % [s["source"] for s in proj["segments"]])
check(CALLS["asr"] == 5 and job["counters"].get("asrFailed") == 1,
      "две пачки, упавший кусок повторён: вызовов %s" % CALLS["asr"])
check(proj["mediaStatus"] == "ready" and proj["writeback"] and proj["slotsSha"], "проект готов, выгрузка в .srt")
check(CALLS["kw"].get("language") == "ru" and CALLS["kw"].get("timestamp_granularities") == ["word", "segment"],
      "язык и отметки слов — в запросе")
check(proj["mediaPages"] > 0 and proj["pages"] == proj["mediaPages"], "страницы по словам расшифровки")
spent = main._spend_status("beta")["spentUsd"] - spent0
check(abs(spent - (125.0 + 3 * 30.0) / 60 * 0.006) < 1e-6,
      "деньги — поминутно, по длительности распознанных кусков ($%.5f)" % spent)
orig = main._orig_existing(pid)
check(orig is not None and orig.suffix == ".srt" and "00:00:00,500 --> 00:00:03,000" in orig.read_text(encoding="utf-8"),
      "оригинал — .srt с таймингом")
check(not (main.MEDIA_DIR / str(pid) / "asr").exists(), "звук и куски убраны после распознавания")

print("=== 5б. Остановка, «распознать снова», кэш кусков ===")
proj["mediaStatus"] = "transcribing"
proj["segments"] = []
fake_split(None, [], main.MEDIA_DIR / str(pid) / "asr" / "chunks", 0)
for i in range(4):                            # как будто два куска уже распознаны
    if i < 2:
        (main.MEDIA_DIR / str(pid) / "asr" / "chunks" / ("chunk%03d.mp3.json" % i)).write_text(
            json.dumps(_Tr().create(file=types.SimpleNamespace(name="chunk%03d.mp3" % i))), encoding="utf-8")
n = CALLS["asr"]
js = main._job_enqueue(pid, "asr", [], {})
js["stop"] = True
main._job_execute(js)
check(js["status"] == "stopped" and main._project_by_id(pid)["mediaStatus"] == "transcribing",
      "остановлена до старта: наш каркас не вызывался")
r = c.get("/api/projects/%d" % pid, headers=H(B))
check(r.json()["mediaStatus"] == "failed" and "остановлено" in r.json().get("mediaError", ""),
      "показ проекта снимает вечное «распознаём»")
r = c.post("/api/projects/%d/media/transcribe" % pid, headers=H(B))
check(r.status_code == 200 and r.json()["project"]["mediaStatus"] == "transcribing", "«распознать снова» поставлено")
check(main._is_paid("POST", "/api/projects/%d/media/transcribe" % pid), "«распознать снова» — платная дверь")
main._job_execute(main._JOBS[r.json()["job"]["id"]])
n2 = CALLS["asr"] - n
check(n2 == 2 and len(main._project_by_id(pid)["segments"]) == 5,
      "готовые куски не перепокупаются: новых вызовов %d" % n2)
check(c.post("/api/projects/%d/media/transcribe" % pid, headers=H(B)).status_code == 409, "у готового — 409")
proj = main._project_by_id(pid)

print("=== 6. Страницы речи списывает API высшей точкой ===")
rec_b = main._tenant_rec("beta")
rec_b.pop("pagesUsed", None); rec_b.pop("pagesCredit", None); rec_b.pop("pagesLog", None)
proj.pop("mediaPagesBooked", None)
main._pages_init(rec_b, "beta")
init = rec_b["pagesUsed"]
main._book_image_pages(proj)
check(init >= proj["mediaPages"] - 0.01 and rec_b["pagesUsed"] == init,
      "счётчик, заведённый после распознавания, речь второй раз не списывает")
proj.pop("mediaPagesBooked", None)
rec_b["pagesUsed"] = 0.0
main._book_image_pages(proj)
got = rec_b["pagesUsed"]
check(abs(got - proj["mediaPages"]) < 0.01 and rec_b["pagesLog"][-1]["kind"] == "media", "списано ровно по речи")
main._book_image_pages(proj)
check(rec_b["pagesUsed"] == got, "повторный показ второй раз не списывает")
u = main._tenant_usage("beta")
check(u["mediaPages"] == 0.0 and abs(u["pages"] - got) < 0.1, "в объёме организации учтено один раз")

print("=== 7. Выгрузка .srt и .vtt ===")
proj = main._project_by_id(pid)
proj["segments"][0]["target"] = "Good afternoon, colleagues."
r = c.post("/api/projects/%d/export" % pid, headers=H(B), json={"format": "original", "source": False})
check(r.json().get("ok"), "выгрузка в исходном виде")
d = c.get(r.json()["url"], headers=H(B))
body = d.content.decode("utf-8")
check("00:00:00,500 --> 00:00:03,000\nGood afternoon, colleagues." in body and "Сегодня говорим" in body,
      "перевод на месте реплики, непереведённое — оригиналом")
r = c.post("/api/projects/%d/export" % pid, headers=H(B), json={"format": "vtt", "source": False})
d = c.get(r.json()["url"], headers=H(B))
check(r.json().get("ok") and d.content.decode().startswith("WEBVTT") and "00:00:00.500 --> 00:00:03.000\nGood afternoon" in d.content.decode(),
      "субтитры .vtt")

for fmt, head, sep in (("srt_bi", "1\n00:00:00,500", ","), ("vtt_bi", "WEBVTT", ".")):
    r = c.post("/api/projects/%d/export" % pid, headers=H(B), json={"format": fmt, "source": False})
    d = c.get(r.json()["url"], headers=H(B)) if r.json().get("ok") else None
    body = d.content.decode("utf-8") if d is not None else ""
    check(r.json().get("ok") and body.startswith(head)
          and ("00:00:00%s500 --> 00:00:03%s000\nДобрый день, коллеги.\nGood afternoon, colleagues.\n" % (sep, sep)) in body
          and ("00:00:03%s400 --> 00:00:06%s000\nСегодня говорим о туберкулёзе.\n\n" % (sep, sep)) in body,
          fmt + ": в реплике оригинал, под ним перевод; непереведённая — одним оригиналом")
check("оригинал+перевод" in r.json()["file"], "имя файла говорит, что внутри")

print("=== 8. Сборка видео и озвучки ===")
r = c.post("/api/projects/%d/media/render" % pid, headers=H(A), json={"what": "dub"})
check(r.status_code == 404, "чужому — 404")


def fake_mux(src, srt_or_track, dst, info, *a, **k):
    Path(dst).write_bytes(b"VIDEO" + Path(srt_or_track).read_bytes()[:40])


media.mux_subtitles = fake_mux
media.mux_dub = fake_mux
media.atempo_pcm = lambda pcm, tempo: pcm[:int(len(pcm) / tempo) // 2 * 2]
r = c.post("/api/projects/%d/media/render" % pid, headers=H(B), json={"what": "subs"})
check(r.status_code == 200 and r.json()["job"]["kind"] == "mediarender", "сборка поставлена")
mj = main._JOBS[r.json()["job"]["id"]]
main._job_execute(mj)
proj = main._project_by_id(pid)
check(mj["status"] == "done" and proj["mediaRender"]["subs"]["file"] == "subs.mp4", "видео с субтитрами собрано")
r = c.get("/api/projects/%d/media/link?what=subs" % pid, headers=H(B))
url = r.json()["url"]
d = c.get(url)
check(d.status_code == 200 and d.content.startswith(b"VIDEO") and "attachment" in d.headers.get("content-disposition", ""),
      "ссылка без сессии отдаёт файл")
bad = url[:-3] + ("aaa" if not url.endswith("aaa") else "bbb")
check(c.get(bad).status_code == 404, "подделанная подпись — 404")
check(c.get("/api/projects/%d/media/link?what=subs" % pid, headers=H(A)).status_code == 404, "чужому ссылку не дают")
exp_url = "/media-dl/" + main._media_sign(pid, "subs", "beta", int(time.time()) - 5)
check(c.get(exp_url).status_code == 404, "просроченная ссылка — 404")
main.MEDIA_ACCEL_PREFIX = "/_media/"
d = c.get(url)
check(d.headers.get("x-accel-redirect") == "/_media/%d/out/subs.mp4" % pid, "за nginx — X-Accel-Redirect, без чтения файла")
main.MEDIA_ACCEL_PREFIX = ""
proj["segments"][1]["target"] = "Today we talk about tuberculosis and a lot of other important things in medicine."
main.TTS_BATCH = 1                            # по реплике на пачку: проверки между пачками идут
r = c.post("/api/projects/%d/media/render" % pid, headers=H(B), json={"what": "dub", "voice": "m1"})
dj = main._JOBS[r.json()["job"]["id"]]
main._job_execute(dj)
rr = main._project_by_id(pid)["mediaRender"].get("dub") or {}
check(dj["status"] == "done" and rr.get("voiced") == 2, "озвучка собрана: %s %s" % (dj["status"], dj.get("error")))
check(CALLS["voice"] == "onyx" and rr.get("voice") == "m1", "голос по ярлыку, имя поставщика наружу не уходит")
check(rr.get("over") == 1 and rr.get("overIds") == [1] and rr.get("fast") == 0 and rr.get("silent") == 0,
      "не влезшая реплика названа по номеру строки: %s" % rr)
n = CALLS["tts"]
dj2 = main._JOBS[c.post("/api/projects/%d/media/render" % pid, headers=H(B), json={"what": "dub", "voice": "m1"}).json()["job"]["id"]]
main._job_execute(dj2)
check(CALLS["tts"] == n, "повторная озвучка берёт реплики из кэша")
check("onyx" not in main._media_err_text(RuntimeError("voice onyx failed on gpt-4o-mini-tts")) and
      "gpt-4o-mini-tts" not in main._media_err_text(RuntimeError("gpt-4o-mini-tts down")), "текст ошибки без имён поставщика")

print("=== 8б. Расход на видео по людям — администратору ===")
r = c.get("/api/admin/media-usage?days=30", headers=H(B))
check(r.status_code == 403, "владельцу организации — 403: деньги видит администратор сервиса")
r = c.get("/api/admin/media-usage?days=30", headers=H(A))
d = r.json()
row = next((x for x in d.get("rows") or [] if x["tenant"] == "beta"), None)
check(r.status_code == 200 and row is not None and row["login"] == "beta", "строка человека из beta")
check(row and abs(row["asrMin"] - (215 + 60) / 60) < 0.1 and row["asrUsd"] > 0, "минуты распознавания выведены из суммы: %s" % row)
check(row and row["ttsMin"] > 0 and abs(row["usd"] - row["asrUsd"] - row["ttsUsd"]) < 1e-6, "озвучка и итог")
check(d["videos"]["beta"]["files"] == 1 and d["keep"]["sourceDays"] == 14 and d["keep"]["renderHours"] == 48,
      "видео организации и сроки хранения")

print("=== 8в. Сроки: исходник — 14 дней после работы, сборки — 2 дня ===")
src = main._media_source(proj)
out = main.MEDIA_DIR / str(pid) / "out"
os.utime(str(src), (time.time() - 10 * 86400,) * 2)
os.utime(str(out / "subs.mp4"), (time.time() - 1 * 86400,) * 2)
os.utime(str(out / "dub.mp4"), (time.time() - 3 * 86400,) * 2)
main._media_sweep()
check(main._media_source(proj) is not None, "исходник без работы 10 дней ещё живёт")
check((out / "subs.mp4").exists() and not (out / "dub.mp4").exists(), "сборка суточная живёт, трёхдневная — удалена")
check((main.MEDIA_DIR / str(pid) / "tts").exists(), "кэш озвучки живёт, пока жив исходник")
old = time.time() - 15 * 86400
os.utime(str(src), (old, old))
main._media_sweep()
check(main._media_source(proj) is None and proj["media"]["kept"] is False, "исходник без работы 15 дней удалён")
check(not (main.MEDIA_DIR / str(pid) / "tts").exists(), "вместе с ним — кэш озвучки")
(main.MEDIA_DIR / str(pid) / "source.mp4").write_bytes(b"v")
os.utime(str(main.MEDIA_DIR / str(pid) / "source.mp4"), (old, old))
proj["media"]["kept"] = True
main._media_touch(proj)
main._media_sweep()
check(main._media_source(proj) is not None, "работа с видео продлевает хранение")

print("=== 9. Удаление уносит видео ===")
check((main.MEDIA_DIR / str(pid)).exists(), "папка видео есть")
r = c.delete("/api/projects/%d" % pid, headers=H(B))
check(r.status_code == 200 and not (main.MEDIA_DIR / str(pid)).exists(), "удалён проект — удалено видео")

print("=== 9б. Перевод реплик ПАЧКАМИ, тайминги в редакторе ===")
CHAT = {"calls": 0, "systems": [], "users": [], "mode": "retry_ok", "seen": set()}


def _chat_create(model=None, messages=None, **kw):
    CHAT["calls"] += 1
    system, user = messages[0]["content"], messages[1]["content"]
    CHAT["systems"].append(system)
    CHAT["users"].append(user)
    if "SUBTITLE MODE" in system:
        items = json.loads(user)
        if CHAT["mode"] == "quota":
            raise RuntimeError("Error code: 429 - insufficient_quota")
        lines = [{"n": it["n"], "text": "EN " + it["text"]} for it in items]
        first = items[0]["text"]
        if CHAT["mode"] == "retry_ok" and "номер 0 " in first and first not in CHAT["seen"]:
            # Первый ответ на первую пачку — без третьей реплики: пачку
            # переспрашивают, и второй ответ ровный.
            CHAT["seen"].add(first)
            lines = [x for x in lines if x["n"] != 3]
        elif CHAT["mode"] == "shift":
            # Слил реплики 2 и 3 и перенумеровал хвост — сдвиг, которого
            # по отдельной строке не видно. Пачку брать нельзя ни разу.
            lines = [{"n": i + 1, "text": x["text"]} for i, x in enumerate(lines[:1] + lines[2:])]
        content = ("```json\n" + json.dumps({"lines": lines}, ensure_ascii=False) + "\n```"
                   if CHAT["mode"] != "array" else json.dumps(lines, ensure_ascii=False))
    else:
        content = "EN1 " + user
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content), finish_reason="stop")],
        usage=types.SimpleNamespace(prompt_tokens=500, completion_tokens=40))


class _OpenAIChat(_OpenAI):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=_chat_create))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=_OpenAIChat)
cues20 = [{"start": i * 3.0, "end": i * 3.0 + 2.5, "text": "Реплика номер %d про лечение." % i} for i in range(20)]
srt20 = importers.render_cues(cues20, ".srt").encode("utf-8")
r = c.post("/api/projects/upload", headers=H(B), files={"file": ("lecture.srt", srt20, "application/x-subrip")},
           data={"src": "RU", "tgt": "EN"})
check(r.status_code == 200, "субтитры загружены: %s" % r.status_code)
sp = r.json()["id"]
r = c.post("/api/projects/%d/batch" % sp, headers=H(B), json={"limit": 50})
got = r.json()
check(got.get("ok") and got.get("count") == 20 and not got.get("errors"), "все 20 реплик переведены: %s" % {k: got.get(k) for k in ("count", "errors")})
check(CHAT["calls"] == 3, "две пачки (15 + 5), неровную первую переспросили один раз: %d вызова" % CHAT["calls"])
check(all("SUBTITLE MODE" in s for s in CHAT["systems"]), "все вызовы — пачками, поштучных нет")
segs = main._project_by_id(sp)["segments"]
check(all(s["target"] == "EN " + s["source"] for s in segs), "каждая реплика получила СВОЙ перевод")
packs = [json.loads(u) for s, u in zip(CHAT["systems"], CHAT["users"]) if "SUBTITLE MODE" in s]
check(sorted(len(p) for p in packs) == [5, 15, 15] and any(p[0] == {"n": 1, "text": segs[0]["source"]} for p in packs),
      "в пачку уходят реплики по порядку, пачки 15 и 5")
pj = c.get("/api/projects/%d" % sp, headers=H(B)).json()
check(pj.get("cueTimes", {}).get(str(segs[1]["id"])) == [3.0, 5.5], "тайминг строки — в карте проекта: %s"
      % (pj.get("cueTimes") or {}).get(str(segs[1]["id"])))


def cue_project(name, k):
    raw = importers.render_cues([{"start": i * 3.0, "end": i * 3.0 + 2.5, "text": "Фраза %s %d." % (name, i)}
                                 for i in range(k)], ".srt").encode("utf-8")
    return c.post("/api/projects/upload", headers=H(B), files={"file": (name + ".srt", raw, "application/x-subrip")},
                  data={"src": "RU", "tgt": "EN"}).json()["id"]


CHAT["mode"], n = "shift", CHAT["calls"]
p2 = cue_project("shift", 5)
got = c.post("/api/projects/%d/batch" % p2, headers=H(B), json={"limit": 50}).json()
segs2 = main._project_by_id(p2)["segments"]
check(CHAT["calls"] - n == 2 + 5 and all(s["target"] == "EN1 " + s["source"] for s in segs2),
      "ответ со сдвигом отвергнут дважды — реплики переведены по одной, каждая своя (%d вызовов)" % (CHAT["calls"] - n))
CHAT["mode"], n = "array", CHAT["calls"]
p3 = cue_project("array", 4)
c.post("/api/projects/%d/batch" % p3, headers=H(B), json={"limit": 50})
check(CHAT["calls"] - n == 1 and all(s["target"] == "EN " + s["source"] for s in main._project_by_id(p3)["segments"]),
      "ответ голым массивом тоже принимается")
CHAT["mode"], n = "quota", CHAT["calls"]
p4 = cue_project("quota", 6)
got = c.post("/api/projects/%d/batch" % p4, headers=H(B), json={"limit": 50}).json()
check(CHAT["calls"] - n == 1 and len(got.get("errors") or []) == 6,
      "пустой счёт у поставщика: один вызов и отказ, без поштучного обстрела (%d)" % (CHAT["calls"] - n))
CHAT["mode"] = "retry_ok"
check(main._cue_answer('{"lines": [{"n": 1, "text": "a"}, {"n": 1, "text": "b"}]}', 2) is None
      and main._cue_answer('{"lines": [{"n": 2, "text": "b"}, {"n": 1, "text": "a"}]}', 2) == {0: "a", 1: "b"},
      "повтор номера — отказ, порядок записей неважен")

n = CHAT["calls"]
r = c.post("/api/projects/upload", headers=H(B), files={"file": ("notes.txt", "Первая строка.\nВторая строка.\nТретья строка.".encode("utf-8"), "text/plain")},
           data={"src": "RU", "tgt": "EN"})
tp = r.json()["id"]
c.post("/api/projects/%d/batch" % tp, headers=H(B), json={"limit": 50})
check(CHAT["calls"] - n == 3 and "cueTimes" not in c.get("/api/projects/%d" % tp, headers=H(B)).json(),
      "обычный файл — по вызову на строку и без колонки времени")

print("=== 10. Настоящий ffmpeg ===")
import importlib
importlib.reload(media)
media.ABORT = main._media_abort
ok, why = media.available()
if not ok:
    print("  —    пропущено: " + why)
else:
    W = TMP / "real"
    W.mkdir()
    clip = W / "clip.mp4"
    media.run(media._ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=4",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
                            "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
                            "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-shortest", clip), timeout=120)
    info = media.probe(clip)
    check(info["video"]["codec"] == "h264" and info["video"]["width"] == 320 and abs(info["duration"] - 4) < 0.5,
          "заголовки прочитаны")
    au = W / "a.mp3"
    media.extract_audio(clip, au, info["duration"])
    check(au.stat().st_size > 1000, "звук вынут без кадров")
    pauses = media.silences(au, info["duration"])
    check(any(a >= 1.5 for a, _b in pauses), "пауза найдена: %s" % pauses)
    ch = media.split_audio(au, [2.0], W / "ch", info["duration"])
    check(len(ch) == 2 and ch[1][1] == 2.0, "звук разрезан копией потока")
    srt = W / "s.srt"
    srt.write_text(importers.render_cues([{"start": 0.5, "end": 2, "text": "Hello"}], ".srt"), encoding="utf-8")
    out = W / "subs.mp4"
    media.mux_subtitles(clip, srt, out, info, "eng")
    got = media.probe(out)
    check(got["video"]["codec"] == "h264" and out.stat().st_size > 0, "дорожка субтитров без перекодирования")
    pcm = b"\x00\x10" * media.TTS_RATE
    pcm2 = media.atempo_pcm(pcm, 1.25)
    check(0.75 < media.pcm_seconds(pcm2) < 0.85, "ускорение речи")
    track = W / "dub.raw"
    media.place_clips(track, info["duration"], [(0.5, pcm2)])
    dub = W / "dub.mp4"
    media.mux_dub(clip, track, dub, info, lang="eng")
    got = media.probe(dub)
    check(got["audioTracks"] == 2 and got["video"]["codec"] == "h264", "озвучка: две дорожки, видео копией")

shutil.rmtree(str(TMP), ignore_errors=True)
print("\nПРОВАЛЕНО: %d" % len(fail) if fail else "\nВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
