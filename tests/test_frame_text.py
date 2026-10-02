"""Текст В КАДРЕ видео и качество распознавания речи (инвариант 38).

Сторожится:
  1. слежение за надписями (`media.FrameTracker`): одна надпись на соседних
     кадрах — одна, пропуск одного кадра не рвёт её, другой текст на том же
     месте — другая надпись;
  2. `media.frame_text_cues`: субтитры речи и логотип не переводятся, логотип
     на весь ролик отсеивается сам, впечатанный субтитр речи — тоже, повторы
     склеиваются, время не короче `FRAME_MIN_SEC`;
  3. место перевода: метка «{\\anN}» в .srt, настройки в .vtt, нижняя треть
     уходит наверх; в кадре — плашкой «Frame» на месте надписи, подгонка её
     не трогает;
  4. задача НАСТОЯЩИМ кодом (кадры и детектор подменены, клиент модели —
     тоже): строки вида `frame` по времени среди речи, страницы, повтор
     не плодит строк, работа человека над надписью переживает повтор;
  5. выходы: .srt/.vtt/кадр несут перевод надписи, озвучка — нет;
     повторный импорт .srt надписи не теряет; дверь-кнопка и её отказы;
  6. распознавание речи: выдумки на тишине и протечка подсказки считаются,
     порог паузы и усиление — от уровня записи, термины проекта — в подсказке.
"""
import base64
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["APP_PASSWORD"] = "boot-password-1"
os.environ["AUTHORITY_CORPUS"] = "0"
os.environ["OPENAI_API_KEY"] = "test-key"
sys.path.insert(0, "backend")
import main
import importers
import media
from PIL import Image
from starlette.testclient import TestClient

TMP = Path(tempfile.mkdtemp(prefix="mct-frame-"))
main.SOURCE_DIR = TMP / "sources"
main.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
main.EXPORT_DIR = TMP / "exports"
main.MEDIA_DIR = TMP / "media"
main.MEDIA_UPLOAD_DIR = main.MEDIA_DIR / "uploads"
main.save_state = lambda *a, **k: None
main._ensure_job_worker = lambda: None
main.STATE["users"], main.STATE["tenants"], main.STATE["audit"] = [], [], []
main.STATE["spend"], main.STATE["projects"] = {}, []
main._SESSIONS.clear(); main._LOGIN_FAILS.clear()
main.TENANT_MAX_PAGES = 0
fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. Слежение за надписями ===")
tr = media.FrameTracker(1.0)
A = {"box": [0.3, 0.1, 0.7, 0.2], "sig": [100] * 576}
closed = []
for t in (2, 3, 4):
    closed += tr.feed(float(t), [dict(A)])
closed += tr.feed(5.0, [])                 # один кадр пропал — надпись жива
closed += tr.feed(6.0, [dict(A)])
check(not closed and len(tr.active) == 1 and tr.active[0]["n"] == 4, "пропуск одного кадра не рвёт надпись")
closed += tr.feed(7.0, [])
closed += tr.feed(8.0, [])
check(len(closed) == 1 and closed[0]["first"] == 2.0 and closed[0]["last"] == 6.0, "два пропуска подряд — надпись закрыта")
check(closed[0]["rep"]["t"] == 3.0, "образец для чтения — второй кадр надписи")
tr = media.FrameTracker(1.0)
tr.feed(0.0, [dict(A)])
out = tr.feed(1.0, [dict(A, sig=[250] * 288 + [0] * 288)])
check(len(tr.active) == 2, "на том же месте ДРУГОЙ текст — другая надпись")
check(media.box_iou([0, 0, 1, 1], [0, 0, 0.5, 1]) == 0.5, "перекрытие рамок")

print("=== 2. Надписи → реплики ===")
EV = [
    {"first": 2.0, "last": 6.0, "box": [0.3, 0.1, 0.7, 0.2], "text": "ГЛАВА ВТОРАЯ", "kind": "text"},
    {"first": 7.0, "last": 8.0, "box": [0.31, 0.1, 0.7, 0.2], "text": "Глава  вторая", "kind": "text"},
    {"first": 0.0, "last": 299.0, "box": [0.85, 0.02, 0.97, 0.08], "text": "NEWS24", "kind": "text"},
    {"first": 10.0, "last": 11.0, "box": [0.2, 0.85, 0.8, 0.93], "text": "Добрый день", "kind": "caption"},
    {"first": 12.0, "last": 12.0, "box": [0.1, 0.1, 0.2, 0.2], "text": "LIVE", "kind": "overlay"},
    {"first": 20.0, "last": 20.0, "box": [0.1, 0.45, 0.35, 0.55], "text": "Кабинет врача", "kind": "text"},
    {"first": 30.0, "last": 33.0, "box": [0.2, 0.85, 0.8, 0.93], "text": "сегодня говорим о туберкулёзе", "kind": "text"},
    {"first": 40.0, "last": 40.0, "box": [0.1, 0.1, 0.2, 0.2], "text": "12", "kind": "text"},
]
SPEECH = [{"start": 29.5, "end": 34.0, "text": "Коллеги, сегодня говорим о туберкулёзе."}]
cues, drop = media.frame_text_cues(EV, 300.0, SPEECH, 1.0)
texts = [c["text"] for c in cues]
check(texts == ["ГЛАВА ВТОРАЯ", "Кабинет врача"], "в перевод — только текст для зрителя: %s" % texts)
check(cues[0]["start"] == 1.5 and cues[0]["end"] == 8.5, "повтор той же надписи склеен, время по серединам: %s" % cues[0])
check(cues[1]["end"] - cues[1]["start"] >= media.FRAME_MIN_SEC, "надпись в один кадр — не короче %.1f с" % media.FRAME_MIN_SEC)
check(drop == {"caption": 1, "overlay": 1, "noise": 1, "persistent": 1, "speech": 1}, "отсеянное названо числом: %s" % drop)

print("=== 3. Место перевода надписи ===")
check(media.frame_place([0.3, 0.1, 0.7, 0.2])["an"] == 8, "вверху по центру — {\\an8}")
check(media.frame_place([0.0, 0.4, 0.2, 0.5])["an"] == 4, "посередине слева — {\\an4}")
check(media.frame_place([0.7, 0.85, 0.95, 0.95])["an"] == 9, "нижняя треть справа уходит наверх — {\\an9}")
check(media.frame_place([0.3, 0.85, 0.7, 0.95])["vtt"].startswith("line:5%"), "в .vtt — тоже наверх")
srt = importers.render_cues([{"start": 1, "end": 2, "text": "CHAPTER TWO", "place": media.frame_place([0.3, 0.1, 0.7, 0.2])},
                             {"start": 1, "end": 2, "text": "Hello"}], ".srt")
check("{\\an8}CHAPTER TWO" in srt and "\nHello" in srt and "{\\an" not in srt.split("Hello")[0].split("CHAPTER TWO")[1],
      ".srt: метка места только у надписи")
vtt = importers.render_cues([{"start": 1, "end": 2, "text": "CHAPTER TWO", "place": media.frame_place([0.3, 0.1, 0.7, 0.2])}], ".vtt")
check("--> 00:00:02.000 line:10% position:50% align:center" in vtt and "{\\an" not in vtt, ".vtt: настройки реплики")
check([c["text"] for c in importers.cue_list(vtt)] == ["CHAPTER TWO"], "свой .vtt читается обратно")
STYLE = media.style_clean({})
fc = {"start": 1.0, "end": 3.0, "text": "CHAPTER TWO " * 12, "box": [0.3, 0.1, 0.7, 0.2], "lineH": 0.05, "i": -7}
fitted, rep = media.fit_cues([fc], STYLE, 1920, 1080)
check(fitted == [fc] and -7 not in rep["over"] + rep["split"] + rep["shrunk"], "подгонка надпись не делит и не мерит")
ass = media.ass_document([fc, {"start": 1.0, "end": 3.0, "text": "Hello"}], STYLE, 1920, 1080, fitted=[fc, {"start": 1.0, "end": 3.0, "text": "Hello"}])
check("Style: Frame," in ass and ",Frame,,0,0,0,,{\\an5\\pos(960,162)" in ass, "в кадре — плашкой на месте надписи")
check(",Default,,0,0,0,,Hello" in ass, "диалог — прежним стилем")

print("=== 4. Задача НАСТОЯЩИМ кодом ===")
c = TestClient(main.app)
H = lambda t: {"Authorization": "Bearer " + t}
ADM = c.post("/api/auth/login", json={"login": "admin", "password": "boot-password-1"}).json()["token"]
c.post("/api/admin/tenants", headers=H(ADM),
       json={"id": "beta", "name": "Beta", "ownerLogin": "beta", "ownerPassword": "beta-pass-123"})
B = c.post("/api/auth/login", json={"login": "beta", "password": "beta-pass-123"}).json()["token"]
for t_ in main.STATE["tenants"]:
    if t_["id"] == "beta":
        t_["limitUsd"] = None
media.available = lambda: (True, "")
PROBE = {"duration": 30.0, "container": "mov,mp4", "video": {"codec": "h264", "width": 1920, "height": 1080},
         "audio": {"codec": "aac", "channels": 2, "rate": 48000}, "audioTracks": 1}
media.probe = lambda path: dict(PROBE)
pid = main._next_id()
PROJ = {"id": pid, "title": "clip", "titleEn": "clip", "src": "RU", "tgt": "EN", "domain": "general", "tenant": "beta",
        "status": "in_progress", "created": "2026-09-28", "deadline": "", "fileName": "clip.srt", "pages": 0.0,
        "pagesUnit": "words", "importKind": "video",
        "media": {"ext": ".mp4", "size": 10, "video": PROBE["video"], "audio": PROBE["audio"], "duration": 30.0,
                  "uploaded": "2026-09-28 10:00:00"},
        "mediaStatus": "transcribing", "segments": []}
main.STATE["projects"].insert(0, PROJ)
(main._media_dir(pid)).mkdir(parents=True, exist_ok=True)
(main._media_dir(pid) / "source.mp4").write_bytes(b"x" * 10)
main._media_apply_transcript(PROJ, [
    {"start": 1.0, "end": 4.0, "text": "Добрый день, коллеги."},
    {"start": 10.0, "end": 14.0, "text": "Здравствуйте, это вторая глава."},
    {"start": 22.0, "end": 25.0, "text": "Переходим к делу."}])
check(PROJ["mediaStatus"] == "ready" and len(PROJ["segments"]) == 3, "речь в проекте")
speech_pages = PROJ["mediaPages"]

# Ролик: заголовок сверху (2–6 с), впечатанный субтитр речи внизу (10–14 с),
# логотип в углу весь ролик, табличка посередине (18 и 20 с — на 19-й пропала).
W, Hh = media.frame_size(PROBE["video"])
SHAPES = {250: ([0.3, 0.1, 0.7, 0.2], lambda t: 2 <= t <= 6),
          200: ([0.25, 0.85, 0.75, 0.93], lambda t: 10 <= t <= 14),
          160: ([0.85, 0.02, 0.97, 0.08], lambda t: True),
          220: ([0.1, 0.45, 0.35, 0.55], lambda t: t in (18, 20))}
READ = {250: ("ГЛАВА ВТОРАЯ", "text"), 200: ("Здравствуйте, это вторая глава", "text"),
        160: ("NEWS24", "overlay"), 220: ("Кабинет врача", "text")}
SAMPLES = {"n": 0}


def fake_sample(src, out_dir, src_start, length, w, h, every=1.0):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    SAMPLES["n"] += 1
    res = []
    k = 0
    while k * every < length - 1e-6:
        t = src_start + k * every
        im = Image.new("L", (w, h), 0)
        for g, (box, on) in SHAPES.items():
            if on(round(t)):
                im.paste(g, (int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
        p = out_dir / ("f%05d.jpg" % (k + 1))
        im.save(p, "PNG")                      # PNG под именем .jpg: цвета — без потерь сжатия
        res.append((round(k * every, 3), p))
        k += 1
    return res


def fake_detect(img_bytes):
    import numpy as np
    a = np.asarray(Image.open(io.BytesIO(img_bytes)).convert("L"))
    out = []
    for g in SHAPES:
        ys, xs = np.nonzero(a == g)
        if len(xs):
            out.append({"box": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                        "conf": 0.9, "flat": 0.9})
    return out


media.sample_frames = fake_sample
main.image_text.engine_ready = lambda: (True, "")
main.image_text.detect_lines = fake_detect
main.image_text.release_engine = lambda: None
VISION = {"calls": 0, "system": ""}


def _completion(model=None, messages=None, **kw):
    VISION["calls"] += 1
    VISION["system"] = messages[0]["content"]
    blocks, i = [], None
    for part in messages[1]["content"]:
        if part["type"] == "text" and part["text"].startswith("Block "):
            i = int(part["text"][6:-1])
        elif part["type"] == "image_url" and i is not None:
            png = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
            im = Image.open(io.BytesIO(png)).convert("L")
            g = im.getpixel((im.width // 2, im.height // 2))
            text, kind = READ.get(g, ("", "text"))
            blocks.append({"i": i, "text": text, "kind": kind})
            i = None
    msg = types.SimpleNamespace(content=json.dumps({"blocks": blocks}, ensure_ascii=False))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")],
                                 usage=types.SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                                             prompt_tokens_details=None))


class _OpenAI:
    def __init__(self, **kw):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=_completion))


sys.modules["openai"] = types.SimpleNamespace(OpenAI=_OpenAI)

r = c.post("/api/projects/%d/media/frametext" % pid, headers=H(ADM))
check(r.status_code == 404, "чужой организации — 404: %s" % r.status_code)
r = c.post("/api/projects/%d/media/frametext" % pid, headers=H(B))
check(r.status_code == 200 and r.json()["project"]["frameText"]["status"] == "queued", "кнопка ставит задачу: %s" % r.text[:200])
job = main._JOBS[r.json()["job"]["id"]]
check(job["kind"] == "frametext", "вид задачи — frametext")
r2 = c.post("/api/projects/%d/media/frametext" % pid, headers=H(B))
check(r2.status_code == 409, "вторая, пока идёт первая, — 409")
main._job_execute(job)
check(job["status"] == "done", "задача завершена: %s %s" % (job["status"], job.get("error")))
frames = [s for s in PROJ["segments"] if main._is_frame_seg(s)]
check([s["source"] for s in frames] == ["ГЛАВА ВТОРАЯ", "Кабинет врача"], "надписи стали строками: %s" % [s["source"] for s in frames])
check("ON SCREEN" in VISION["system"] and '"caption"' in VISION["system"], "вопрос модели — про кадр и вид надписи")
order = [s["source"] for s in PROJ["segments"]]
check(order == ["Добрый день, коллеги.", "ГЛАВА ВТОРАЯ", "Здравствуйте, это вторая глава.", "Кабинет врача",
                "Переходим к делу."], "строки по времени среди речи: %s" % order)
f0 = frames[0]["origin"]
check(f0["start"] == 1.5 and f0["end"] == 6.5 and f0["box"] == [0.3, 0.1, 0.7, 0.2], "время и место надписи: %s" % f0)
check(frames[1]["origin"]["start"] == 17.5 and frames[1]["origin"]["end"] == 20.5, "пропуск кадра не разорвал табличку")
ft = PROJ["frameText"]
check(ft["status"] == "done" and ft["added"] == 2 and ft["drop"]["overlay"] == 1 and ft["drop"]["speech"] == 1,
      "отчёт: добавлено 2, логотип и субтитр речи отсеяны: %s" % ft)
check(PROJ["mediaPages"] > speech_pages and PROJ["framePages"] > 0, "страницы — речь плюс надписи")
check(not (main._media_dir(pid) / "frames").exists(), "кадры убраны с диска")
calls1 = VISION["calls"]
check(calls1 <= 4, "одно чтение на надпись, а не на кадр: %d вызовов" % calls1)

print("=== 5. Выходы ===")
fid = frames[0]["id"]
frames[0]["target"] = "CHAPTER TWO"
frames[0]["status"] = "confirmed"
for s in PROJ["segments"]:
    if s["source"] == "Добрый день, коллеги.":
        s["target"], s["status"] = "Good afternoon, colleagues.", "translated"
text, trm, _d = main._media_translations(PROJ)
srt_cues = main._media_srt(PROJ, text, trm)
body = importers.render_cues(srt_cues, ".srt")
check("{\\an8}CHAPTER TWO" in body and "Good afternoon" in body, ".srt: перевод надписи на её месте")
check("Кабинет врача" in body, "непереведённая надпись — оригиналом (как и речь)")
burn, _n = main._burn_cues(PROJ, text, trm)
check(any(c.get("box") and c["text"] == "CHAPTER TWO" for c in burn), "в кадр — перевод надписи")
check(not any(c["text"] == "Кабинет врача" for c in burn), "в кадр — только переведённое")
check(main._cue_seg_ids(PROJ, [-fid]) == [fid], "отчёт подгонки называет строку надписи")
cl = main._project_for_client(PROJ)
check(cl["cueTimes"].get(str(fid)) == [1.5, 6.5], "колонка «Время» у надписи")
check(len(main._text_segments(PROJ)) == 3, "надписи — не строки файла субтитров")
_t, tr_map, _ = main._media_translations(PROJ)
check(len(tr_map) == 1, "в озвучку надписи не идут (карта реплик — только речь)")

print("=== 5а. Повтор разбора ===")
PROJ["frameText"] = {"status": "queued"}
job2 = main._job_enqueue(pid, "frametext", [], {})
main._job_execute(job2)
frames2 = [s for s in PROJ["segments"] if main._is_frame_seg(s)]
check(len(frames2) == 2 and frames2[0]["id"] == fid and frames2[0]["target"] == "CHAPTER TWO",
      "повтор не плодит строк, перевод и подпись на месте")
main._frame_text_apply(PROJ, [])
left = [s["source"] for s in PROJ["segments"] if main._is_frame_seg(s)]
check(left == ["ГЛАВА ВТОРАЯ"], "разбор без надписей снимает машинную, заверенную оставляет: %s" % left)

print("=== 5а'. Повторный импорт .srt надпись не теряет ===")
srt_new = importers.render_cues([{"start": 1.0, "end": 4.0, "text": "Добрый день, коллеги."},
                                 {"start": 10.0, "end": 14.0, "text": "Здравствуйте, это вторая глава."},
                                 {"start": 22.0, "end": 25.0, "text": "Переходим к делу!"}], ".srt")
r = c.post("/api/projects/%d/reimport" % pid, headers=H(B),
           files={"file": ("clip.srt", srt_new.encode("utf-8"), "application/x-subrip")},
           data={"dry_run": "false"})
check(r.status_code == 200, "замена файла прошла: %s" % r.text[:200])
kept = [s for s in PROJ["segments"] if main._is_frame_seg(s)]
check([s["source"] for s in kept] == ["ГЛАВА ВТОРАЯ"] and kept[0]["target"] == "CHAPTER TWO",
      "надпись и её перевод пережили замену файла")
check(r.json().get("removed") == 1 and "ГЛАВА ВТОРАЯ" not in (r.json().get("removedSample") or []),
      "надпись не названа «удалённой строкой»: %s" % r.json().get("removedSample"))

print("=== 5б. Отказы двери ===")
PROJ["mediaStatus"] = "transcribing"
r = c.post("/api/projects/%d/media/frametext" % pid, headers=H(B))
check(r.status_code == 409, "до конца распознавания речи — 409")
PROJ["mediaStatus"] = "ready"
PROJ["media"]["video"] = None
r = c.post("/api/projects/%d/media/frametext" % pid, headers=H(B))
check(r.status_code == 400, "звук без видео — 400")
PROJ["media"]["video"] = PROBE["video"]
check(main._is_paid("POST", "/api/projects/%d/media/frametext" % pid), "дверь платная (лимит расхода)")

print("=== 6. Распознавание речи ===")
st = {}
segs = [{"start": 0, "end": 2, "text": " Субтитры сделал DimaTorzok", "no_speech_prob": 0.01, "avg_logprob": -0.1},
        {"start": 2, "end": 4, "text": " Спасибо за просмотр!", "no_speech_prob": 0.01, "avg_logprob": -0.1},
        {"start": 4, "end": 6, "text": " Спасибо за просмотр!", "no_speech_prob": 0.5, "avg_logprob": -0.3},
        {"start": 6, "end": 8, "text": " пиопневмоторакс, туберкулёма", "no_speech_prob": 0.4, "avg_logprob": -0.9},
        {"start": 8, "end": 10, "text": " Туберкулёма — ограниченный очаг.", "no_speech_prob": 0.01, "avg_logprob": -0.1}]
cues = media.build_cues(segs, [], hint=["Говорим спокойно.", "пиопневмоторакс, туберкулёма, каверна", "x"], stats=st)
check([c["text"] for c in cues] == ["Спасибо за просмотр!", "Туберкулёма — ограниченный очаг."],
      "титры субтитровщика и протечка терминов отсеяны, уверенная речь — нет: %s" % [c["text"] for c in cues])
check(st == {"noise": 2, "leak": 1}, "отсеянное посчитано: %s" % st)
check(media.build_cues(segs[4:], [], hint="") and media.build_cues(segs[4:], [], hint=None) is not None,
      "подсказка строкой и пустая — как раньше")
check(media.silence_floor(None) == -35.0, "без замера — прежний порог")
check(media.silence_floor({"mean": -20.0, "max": -2.0}) == -38.0, "порог паузы — от уровня записи")
check(media.silence_floor({"mean": -5.0, "max": 0.0}) == -30.0, "шумная запись — не выше −30 дБ")
check(media.asr_gain({"mean": -40.0, "max": -25.0}) == 20.0, "тихая запись — усиление, но не больше 20 дБ")
check(media.asr_gain({"mean": -20.0, "max": -4.0}) == 0.0, "нормальная — не трогаем")
check(media.ASR_BITRATE == "64k", "распознаванию — 64 кбит/с")
main.STATE.setdefault("glossary", [])
main.STATE["glossary"] += [
    {"id": 90001, "src": "пиопневмоторакс", "tgt": "pyopneumothorax", "tier": "verified", "lang": "RU→EN",
     "domain": "general", "tenant": "beta", "project": pid},
    {"id": 90002, "src": "каверна", "tgt": "cavity", "tier": "auto", "lang": "RU→EN",
     "domain": "general", "tenant": "beta", "project": pid},
    {"id": 90003, "src": "туберкулёма", "tgt": "tuberculoma", "tier": "verified", "lang": "RU→EN",
     "domain": "general", "tenant": "gamma"}]
main._invalidate_gloss_index()
main._JOB_TENANT.id = "beta"
terms = main._asr_terms(PROJ)
check(terms == "пиопневмоторакс", "в подсказку — приказные термины своей папки и организации: %r" % terms)
main.STATE["glossary"] += [{"id": 91000 + k, "src": "термин%02d" % k, "tgt": "t%d" % k, "tier": "verified",
                            "lang": "RU→EN", "domain": "general", "tenant": "beta"} for k in range(50)]
check(main._asr_terms(PROJ) == "пиопневмоторакс", "большой общий словарь в подсказку не идёт")

print()
print("ВСЁ ПРОШЛО" if not fail else "ПРОВАЛЕНО: %d" % len(fail))
sys.exit(1 if fail else 0)
