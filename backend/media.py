"""Видео и звук: тайминги речи, субтитры, озвучка — БЕЗ декодирования кадров.

Чем модуль бережёт общий сервер (4 ядра на несколько проектов, файл клиента
до 2,5 ГБ):
  * кадры не декодируются НИКОГДА. Звук вынимается демультиплексором, видео
    при сборке идёт копией потока (`-c:v copy`). Поэтому разрешение, частота
    кадров и кодек видео на цену работы не влияют вовсе: 4K и 480p стоят
    одинаково — ровно столько, сколько весит звуковая дорожка;
  * каждый вызов ffmpeg идёт с `nice -n 19` и `ionice -c2 -n7` (чужие
    сервисы впереди) и с `-threads 1`;
  * у каждого вызова таймаут, отказ — исключение `MediaError` со словами,
    а не повисший процесс;
  * дорожка озвучки собирается в `numpy.memmap` НА ДИСКЕ: час речи — это
    170 МБ отсчётов, держать их в памяти единственного воркера нельзя;
  * субтитры по умолчанию кладутся ДОРОЖКОЙ в контейнер (плееры и YouTube
    их показывают) и отдаются файлом .srt/.vtt. Впечатанные в кадр (burn-in) —
    отдельная сборка по кнопке: это полное перекодирование, и она одна
    декодирует кадры — кусками, с потолком качества и длины (раздел
    «Субтитры В КАДРЕ» ниже).

Модуль не знает ни STATE, ни проектов, ни денег: это чистые функции над
файлами. Модель не зовёт: распознавание и синтез — забота вызывающего
(`main._job_asr`, `main._job_dub`), здесь только подготовка и сборка.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Что принимаем. Контейнеры видео — всё, что ffmpeg разбирает без кодеков
# на стороне: расширение лишь подсказка, решает `probe` (дорожка звука есть?).
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg", ".mpeg",
             ".ts", ".mts", ".m2ts", ".3gp", ".ogv"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".amr"}
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT

# Звук для распознавания: моно 16 кГц — ровно то, на чём обучена модель, —
# mp3 32 кбит/с: 14 МБ на час. Кусок до 10 минут весит ~2,4 МБ, то есть
# потолок поставщика в 25 МБ на запрос не достижим ни при каком файле.
ASR_RATE = 16000
ASR_BITRATE = "32k"
ASR_CHUNK_SEC = int(os.environ.get("ASR_CHUNK_SEC", "600"))
ASR_CUT_WINDOW = 90            # искать паузу в ±90 с от целевой границы куска

# Синтез речи отдаёт PCM 24 кГц, 16 бит, моно — ровно так и собираем дорожку.
TTS_RATE = 24000

# Реплика субтитра: не длиннее 6 с и 84 знаков (две строки по 42), не короче
# секунды — иначе глаз её не успевает прочесть.
CUE_MAX_SEC = 6.0
CUE_MAX_CHARS = 84
CUE_MIN_SEC = 1.0

# Единица перевода у распознанной речи — ПРЕДЛОЖЕНИЕ, а не кусок распознавания
# (`sentence_cues`). Распознавание режет речь по дыханию: на арабском боевом
# ролике — «بالنسبة لي» / «اللغة العربية» / «هي اللغة التي…», по 1–4 слова,
# часто без знаков препинания. Переведённый в одиночку, такой обрывок теряет
# смысл, а в языке с другим порядком слов (узбекский — глагол в конце) его
# нельзя перевести верно В ПРИНЦИПЕ. Поэтому строка проекта — фраза целиком,
# а на экранные куски она делится только на выходе (`display_cues`) —
# так устроен и профессиональный перевод субтитров: сначала предложение,
# потом сегментация по правилам языка перевода.
UNIT_MAX_SEC = float(os.environ.get("MEDIA_UNIT_MAX_SEC", "12"))
UNIT_MAX_CHARS = int(os.environ.get("MEDIA_UNIT_MAX_CHARS", "160"))
# Пауза закрывает единицу, только когда в ней уже есть законченная мысль:
# «ولذلك» (одно слово) | 1,46 с | «بدأت دراسة هذه اللغة» — одно предложение.
UNIT_PAUSE_SOFT = float(os.environ.get("MEDIA_UNIT_PAUSE_SOFT", "0.8"))
# Такая пауза закрывает всегда: иначе экранный кусок, время которого делится
# по длине текста, висел бы на экране посреди тишины.
UNIT_PAUSE_HARD = float(os.environ.get("MEDIA_UNIT_PAUSE_HARD", "2.5"))
UNIT_DONE_WORDS, UNIT_DONE_CHARS, UNIT_DONE_SEC = 4, 24, 2.5
# Экранный кусок на выходе: две строки по 42 знака (Netflix), не дольше 7 с;
# у письма без пробелов — 2 × 16.
SCREEN_MAX_CHARS = int(os.environ.get("MEDIA_SCREEN_MAX_CHARS", "84"))
SCREEN_MAX_CHARS_CJK = 32
SCREEN_MAX_SEC = float(os.environ.get("MEDIA_SCREEN_MAX_SEC", "7"))
# Пауза речи, через которую экранная часть не перекидывается.
SCREEN_GAP = float(os.environ.get("MEDIA_SCREEN_GAP", "1.0"))
# Версия правил деления на экран: входит в отпечаток кусков сборки в кадр —
# сменил правила, и незаконченная сборка не склеит куски разных правил.
DISPLAY_RULES = 1

# Укладка озвучки: до 1,3 раза ускорение звучит естественно, до 1,5 —
# заметно быстро, но разборчиво; дальше — не влезает, человек сокращает.
TEMPO_SOFT = 1.3
TEMPO_HARD = 1.5

# Кодеки видео, которые mp4 держит без перекодирования; остальное — в mkv,
# он принимает практически всё.
MP4_VCODECS = {"h264", "hevc", "av1", "mpeg4", "mjpeg"}
MP4_ACODECS = {"aac", "mp3", "alac", "ac3", "eac3", "opus", "flac"}


class MediaError(RuntimeError):
    """Отказ ffmpeg/ffprobe — со словами, пригодными для человека."""


def _bin(name: str) -> Optional[str]:
    env = os.environ.get(name.upper() + "_BIN")
    if env:
        return env if Path(env).exists() else None
    return shutil.which(name)


def available() -> tuple:
    """(есть ли чем работать, почему нет)."""
    if not _bin("ffmpeg"):
        return False, "На сервере не установлен ffmpeg"
    if not _bin("ffprobe"):
        return False, "На сервере не установлен ffprobe"
    return True, ""


def _polite(cmd: list) -> list:
    """Низкий приоритет CPU и диска. На Windows (разработка) их нет —
    команда идёт как есть."""
    pre = []
    if os.name == "posix":
        if shutil.which("nice"):
            pre += ["nice", "-n", "19"]
        if shutil.which("ionice"):
            # Лучший-усилием с низшим приоритетом, а не idle (-c3): на занятом
            # общем диске idle может не получить ввод-вывод вовсе.
            pre += ["ionice", "-c2", "-n7"]
    return pre + cmd


class Aborted(MediaError):
    """Сервис останавливается (выкат): ffmpeg убит, задача продолжит после
    рестарта. Долгая сборка иначе держала бы остановку до TimeoutStopSec."""


# Вызывающий подменяет (`main`): True — бросить работу. Спрашивается раз
# в секунду, пока ffmpeg идёт.
ABORT = lambda: False                                  # noqa: E731


class Cancelled(MediaError):
    """Человек нажал «Отменить»: ffmpeg убит, задача остановлена, а не
    отложена (в отличие от `Aborted` на выкате)."""


# Спрашивается на каждом тике ожидания ffmpeg, как `ABORT`. Без него отмена
# доходила бы только между кусками сборки, а дорожка и сведение озвучки —
# один вызов ffmpeg на десятки минут, и кнопка «Отменить» не значила бы ничего.
CANCEL = lambda: False                                 # noqa: E731


def run(cmd: list, timeout: float, stdin: Optional[bytes] = None,
        cwd=None) -> subprocess.CompletedProcess:
    """Запуск со всеми предохранителями; stdout — байты, stderr — байты.
    `cwd` — у впечатывания субтитров: файл .ass передаётся фильтру ИМЕНЕМ,
    без пути (в пути фильтров двоеточие и кавычки — служебные знаки)."""
    import time as _time
    try:
        proc = subprocess.Popen(_polite(cmd), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(cwd) if cwd else None)
    except OSError as e:
        raise MediaError("ffmpeg не запустился: %s" % e)
    deadline = _time.time() + timeout
    feed = stdin
    while True:
        try:
            out, err = proc.communicate(input=feed, timeout=1.0)
            break
        except subprocess.TimeoutExpired:
            feed = None                  # вход уже передан первым вызовом
            ab = ABORT()
            stop = not ab and CANCEL()
            if ab or stop or _time.time() > deadline:
                proc.kill()
                proc.communicate()
                if stop:
                    raise Cancelled("Сборка отменена")
                if _time.time() > deadline:
                    raise MediaError("Обработка звука не уложилась в %d с" % int(timeout))
                raise Aborted("Работа отложена до перезапуска сервиса")
    r = subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    if r.returncode != 0:
        tail = (r.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
        raise MediaError("ffmpeg отказал: %s" % " / ".join(tail)[:400])
    return r


def _ffmpeg(*args) -> list:
    return [_bin("ffmpeg") or "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-threads", "1"] + [str(a) for a in args]


# ─── Что за файл ─────────────────────────────────────────────────────

def probe(path) -> dict:
    """{duration, container, video: {codec, width, height} | None,
    audio: {codec, channels, rate} | None, audioTracks}. Читает только
    заголовки (секунды даже на 2 ГБ). Файл без звуковой дорожки — годный
    ответ (`audio: None`): отказ формулирует вызывающий."""
    cmd = [_bin("ffprobe") or "ffprobe", "-v", "error", "-print_format", "json",
           "-show_entries", "format=duration,format_name:stream=index,codec_type,codec_name,"
           "width,height,channels,sample_rate,sample_aspect_ratio,avg_frame_rate,r_frame_rate,pix_fmt"
           ":stream_disposition=attached_pic:stream_side_data=rotation:stream_tags=rotate",
           str(path)]
    r = run(cmd, timeout=60)
    try:
        info = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        raise MediaError("Файл не читается как видео или звук")
    fmt = info.get("format") or {}
    video = audio = None
    tracks = 0
    for s in info.get("streams") or []:
        kind = s.get("codec_type")
        if kind == "video" and video is None and not (s.get("disposition") or {}).get("attached_pic"):
            video = {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height")}
            # Как кадр ВИДИТ зритель: телефон пишет вертикальное видео
            # горизонтальными кадрами с пометкой поворота, у DVD пиксель
            # не квадратный. От этого зависят размер субтитров и кадр
            # результата, поэтому пишем, только если отличается от обычного.
            rot = _rotation(s)
            if rot:
                video["rotation"] = rot
            sar = _ratio(s.get("sample_aspect_ratio"))
            if sar and abs(sar - 1.0) > 0.01:
                video["sar"] = round(sar, 4)
            fps = _ratio(s.get("avg_frame_rate")) or _ratio(s.get("r_frame_rate"))
            if fps:
                video["fps"] = round(fps, 3)
            if s.get("pix_fmt"):
                video["pixfmt"] = s.get("pix_fmt")
        elif kind == "audio":
            tracks += 1
            if audio is None:
                audio = {"codec": s.get("codec_name"), "channels": s.get("channels"),
                         "rate": _num(s.get("sample_rate"))}
    dur = _num(fmt.get("duration"))
    return {"duration": round(dur, 3) if dur else 0.0, "container": fmt.get("format_name") or "",
            "video": video, "audio": audio, "audioTracks": tracks}


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ratio(v) -> float:
    """«30000/1001» → 29.97, «64:45» (пропорция пикселя пишется через
    двоеточие) → 1.4222, «0/0» и мусор → 0."""
    try:
        a, _s, b = str(v or "").replace(":", "/").partition("/")
        return float(a) / float(b) if b else float(a)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _rotation(stream: dict) -> int:
    """Поворот при показе, приведённый к 0/90/180/270. ffmpeg 5+ пишет его
    в side data, старые файлы — тегом rotate."""
    deg = None
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            deg = _num(sd.get("rotation"))
    if deg is None:
        deg = _num((stream.get("tags") or {}).get("rotate"))
    return int(round(deg / 90.0)) * 90 % 360


# ─── Звук для распознавания ──────────────────────────────────────────

def extract_audio(src, dst, duration: float, limit_sec: Optional[float] = None,
                  start: float = 0.0) -> None:
    """Первая звуковая дорожка → моно 16 кГц mp3. Видео не декодируется
    (`-vn`), поэтому время зависит от длины ролика, а не от разрешения.
    `start` — начало обрезки: звук берётся С НЕГО, и время реплик сразу
    выходит в шкале обрезанного видео (ноль = первый кадр результата)."""
    args = (["-ss", "%.3f" % start] if start > 0 else []) + [
        "-i", src, "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", 1, "-ar", ASR_RATE,
        "-c:a", "libmp3lame", "-b:a", ASR_BITRATE]
    if limit_sec:
        args += ["-t", "%.3f" % limit_sec]
    run(_ffmpeg(*(args + [dst])), timeout=max(300.0, duration * 0.6))


_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def silences(audio, duration: float) -> list:
    """[(начало, конец)] пауз — по ним режется звук на куски: разрез посреди
    слова дал бы два обрывка, и модель прочла бы оба неверно."""
    cmd = [_bin("ffmpeg") or "ffmpeg", "-nostdin", "-hide_banner", "-threads", "1", "-i", str(audio),
           "-af", "silencedetect=n=-35dB:d=0.4", "-f", "null", "-"]
    r = run(cmd, timeout=max(120.0, duration * 0.3))
    out, start = [], None
    for line in (r.stderr or b"").decode("utf-8", "replace").splitlines():
        m = _SIL_START.search(line)
        if m:
            start = float(m.group(1))
            continue
        m = _SIL_END.search(line)
        if m and start is not None:
            out.append((max(0.0, start), float(m.group(1))))
            start = None
    return out


def cut_points(duration: float, pauses: list, target: float = ASR_CHUNK_SEC,
               window: float = ASR_CUT_WINDOW) -> list:
    """Границы кусков: у каждой целевой отметки (10, 20, … минут) — середина
    ближайшей паузы в окне ±`window`; паузы нет — отметка как есть.
    Возвращает внутренние границы по возрастанию."""
    pts, t = [], target
    while t < duration - 1.0:
        best = None
        for a, b in pauses:
            mid = (a + b) / 2
            if abs(mid - t) <= window and (best is None or abs(mid - t) < abs(best - t)):
                best = mid
        p = best if best is not None else t
        if not pts or p > pts[-1] + 5:
            pts.append(round(p, 3))
        t = (pts[-1] if pts else t) + target
    return pts


def split_audio(audio, points: list, out_dir, duration: float) -> list:
    """[(путь куска, смещение в секундах)] — копией потока, без перекодирования."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bounds = [0.0] + list(points) + [duration]
    res = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.2:
            continue
        p = out_dir / ("chunk%03d.mp3" % i)
        if not (p.exists() and p.stat().st_size > 0):
            # Во временный файл и подменой: оборванный выкатом кусок иначе
            # остался бы на месте, прошёл проверку «уже есть» и тихо
            # потерял бы хвост речи.
            tmp = out_dir / ("chunk%03d.tmp.mp3" % i)
            run(_ffmpeg("-ss", "%.3f" % a, "-to", "%.3f" % b, "-i", audio, "-c", "copy", tmp),
                timeout=120)
            os.replace(str(tmp), str(p))
        res.append((p, a))
    return res


# ─── Реплики из ответа распознавания ─────────────────────────────────

_END_RE = re.compile(r"[.!?…。！？]\s*$")
_BREAK_RE = re.compile(r"(?<=[.!?…。！？;:,，、])\s+")


def _is_noise_segment(seg: dict) -> bool:
    """Выдумка модели на тишине («Продолжение следует…», «Субтитры сделал…»)
    приходит с высокой вероятностью «речи нет» или с зацикленным текстом.
    Такой кусок репликой не становится."""
    if (seg.get("no_speech_prob") or 0) > 0.6 and (seg.get("avg_logprob") or 0) < -0.8:
        return True
    if (seg.get("compression_ratio") or 0) > 2.6:
        return True
    return not (seg.get("text") or "").strip()


def _split_text(text: str, max_chars: int) -> list:
    """Длинную фразу — на куски по знакам препинания, затем по пробелам."""
    parts, cur = [], ""
    for piece in _BREAK_RE.split(text.strip()):
        if cur and len(cur) + 1 + len(piece) > max_chars:
            parts.append(cur)
            cur = piece
        else:
            cur = (cur + " " + piece).strip()
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        while len(p) > max_chars and " " in p[:max_chars]:
            cut = p.rfind(" ", 0, max_chars)
            out.append(p[:cut])
            p = p[cut + 1:]
        out.append(p)
    return [p for p in out if p.strip()]


def _time_at(frac: float, start: float, end: float, words: list) -> float:
    """Время внутри фразы по доле текста: по словам с отметками, если они
    есть (модель знает, где кончилось слово), иначе — по линейке."""
    if words:
        k = min(len(words) - 1, max(0, int(round(frac * len(words))) - 1))
        return max(start, min(end, float(words[k].get("end") or start)))
    return start + (end - start) * frac


def _hint_key(text: str) -> str:
    """Текст без регистра, пробелов и знаков препинания — для сверки
    с подсказкой. Огласовки (категория M) остаются: без них тайский
    и хинди сравнивались бы по согласным."""
    import unicodedata as _ud
    return "".join(ch for ch in (text or "").lower() if _ud.category(ch)[0] in "LNM")


def build_cues(segments: list, words: list, offset: float = 0.0,
               max_sec: float = CUE_MAX_SEC, max_chars: int = CUE_MAX_CHARS,
               hint: str = "") -> list:
    """Фразы распознавания → реплики субтитров [{start, end, text}]. Фраза
    длиннее `max_sec`/`max_chars` делится по препинанию, а время кусков
    берётся из отметок СЛОВ этой фразы. Смещение куска звука прибавляется.
    Кусок, который целиком повторяет подсказку распознаванию (`hint`) или
    её бОльшую часть, — это она протекла в ответ на тишине, а не речь: отсеивается."""
    hk = _hint_key(hint)
    cues = []
    for seg in segments or []:
        if _is_noise_segment(seg):
            continue
        sk = _hint_key(seg.get("text") or "")
        # Протечка — это подсказка целиком; кусок её (whisper на тишине любит
        # повторять ХВОСТ) — только когда распознавание само сомневается, что
        # это речь. Уверенно распознанная реплика, совпавшая с частью шаблонной
        # подсказки («Давайте продолжим»), — настоящая речь.
        if hk and sk and sk in hk and (sk == hk or (
                len(sk) >= 0.25 * len(hk)
                and ((seg.get("no_speech_prob") or 0) >= 0.2 or (seg.get("avg_logprob") or 0) < -0.7))):
            continue
        s, e = float(seg.get("start") or 0), float(seg.get("end") or 0)
        text = " ".join((seg.get("text") or "").split())
        if e <= s:
            continue
        ws = [w for w in (words or []) if s - 0.05 <= float(w.get("start") or 0) <= e + 0.05]
        if e - s <= max_sec and len(text) <= max_chars:
            cues.append({"start": s + offset, "end": e + offset, "text": text})
            continue
        pieces = _split_text(text, min(max_chars, max(20, int(len(text) * max_sec / (e - s)))))
        total = sum(len(p) for p in pieces) or 1
        done, t0 = 0, s
        for i, p in enumerate(pieces):
            done += len(p)
            t1 = e if i == len(pieces) - 1 else _time_at(done / total, s, e, ws)
            if t1 <= t0:
                t1 = min(e, t0 + 0.5)
            cues.append({"start": t0 + offset, "end": t1 + offset, "text": p})
            t0 = t1
    return cues


def tidy_cues(cues: list, min_sec: float = CUE_MIN_SEC) -> list:
    """Порядок по времени, без нахлёстов, короткие реплики — растянуть
    до `min_sec`, если есть куда (не залезая в следующую)."""
    cues = sorted((c for c in cues if (c.get("text") or "").strip()), key=lambda c: c["start"])
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        if c["end"] - c["start"] < min_sec:
            c["end"] = c["start"] + min_sec if nxt is None else min(c["start"] + min_sec, max(c["end"], nxt - 0.04))
        if nxt is not None and c["end"] > nxt - 0.02:
            c["end"] = max(c["start"] + 0.2, nxt - 0.02)
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    return cues


# ─── Нормы субтитров по языкам (backend/subtitle_norms.json) ─────────
#
# Языков в системе семь десятков, и одна мерка на всех врёт: японская строка
# — 13 знаков, китайская — 16, тайский режется только между фразами, у хинди
# конец предложения — «।», у армянского — «։», арабица пишется справа
# налево. Нормы лежат ДАННЫМИ (правит человек, знающий язык), язык находит
# свою письменность в каталоге languages.json. Без языка (старый вызов,
# неизвестный код) работает прежняя эвристика — поведение не меняется.

_NORMS_PATH = Path(__file__).resolve().parent / "subtitle_norms.json"
_LANGS_PATH = Path(__file__).resolve().parent / "languages.json"
_NORMS_CACHE: dict = {}

# Общие для всех языков знаки конца предложения и паузы внутри него; своё
# у письменности — в нормах (`sentence_end`, `clause`).
_SENT_END_BASE = ".!?…。！？؟۔"
_CLAUSE_BASE = ".!?…;:,，、。！？،؛；："
# Закрывающие кавычки и скобки после конца предложения («…」», «…»»).
_CLOSERS = "'\"»”’)\\]」』）》〉】"
# Кинсоку: с этих знаков японская и китайская строка НЕ начинается.
_NO_START = set("。、，．・：；？！）」』】〕〉》ーぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々ゝゞ,.!?;:)")


def _norm_tables() -> tuple:
    try:
        mt = (_NORMS_PATH.stat().st_mtime, _LANGS_PATH.stat().st_mtime)
    except OSError:
        return {}, {}
    hit = _NORMS_CACHE.get("t")
    if hit and hit[0] == mt:
        return hit[1], hit[2]
    try:
        norms = json.loads(_NORMS_PATH.read_text(encoding="utf-8"))
        cat = json.loads(_LANGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    langs = cat.get("languages", cat) if isinstance(cat, dict) else cat
    scripts = {str(x.get("code") or "").upper(): x.get("script") for x in langs or [] if isinstance(x, dict)}
    _NORMS_CACHE.clear()
    _NORMS_CACHE["t"] = (mt, norms, scripts)
    return norms, scripts


def sub_norm(lang) -> Optional[dict]:
    """Норма субтитров языка: line (графем в строке, строк две), read_cps,
    speak_cps, cut (word | char | phrase), join, sentence_end, clause, rtl.
    Порядок силы: default ← письменность ← язык. Нет языка — None (прежняя
    эвристика). Неизвестный код — умолчание: 42 знака и пробелы."""
    code = str(lang or "").upper().strip()
    if not code:
        return None
    norms, scripts = _norm_tables()
    out = {"line": 42, "read_cps": 17, "speak_cps": 15, "cut": "word", "join": " ",
           "sentence_end": "", "clause": "", "rtl": False}
    out.update(norms.get("default") or {})
    # Переменная окружения правит только УМОЛЧАНИЕ (у иероглифов и тайского
    # своя строка); мусор в ней не роняет выгрузку — берётся норма из файла.
    try:
        env_line = int(os.environ.get("MEDIA_SCREEN_MAX_CHARS") or 0)
    except ValueError:
        env_line = 0
    if env_line:
        out["line"] = max(8, env_line // 2)
    script = scripts.get(code) or scripts.get(code.split("-")[0])
    out.update((norms.get("scripts") or {}).get(script or "", {}))
    out.update((norms.get("languages") or {}).get(code, {}))
    out["code"], out["script"] = code, script
    return out


def glen(text: str) -> int:
    """Длина в ГРАФЕМАХ: комбинирующие знаки (огласовки деванагари, тайские
    тоны, арабские харакаты) и нулевой ширины ZWJ/ZWNJ отдельного места на
    экране не занимают — считать их знаками значило бы завысить хинди
    и тайский на 20–40%. У латиницы и кириллицы (NFC) — то же, что len()."""
    import unicodedata as _ud
    return sum(1 for ch in text or "" if not _ud.category(ch).startswith("M") and ch not in "‌‍")


# Знаки, которые пишутся ПОСЛЕ согласной, но категорией Lo (тайские «ะ า ำ ๅ»,
# лаосские «ະ າ ຳ»): отдельной графемой их не оторвать.
_TRAIL_LO = set("\u0e30\u0e32\u0e33\u0e45\u0eb0\u0eb2\u0eb3")
# Гласные, которые пишутся ПЕРЕД согласной (тайские «เ แ โ ใ ไ», лаосские):
# после них разрезать нельзя — гласная осталась бы без своей согласной.
_LEAD_LO = set("\u0e40\u0e41\u0e42\u0e43\u0e44\u0ec0\u0ec1\u0ec2\u0ec3\u0ec4")


def _joins_next(prev: str) -> bool:
    """После этой графемы следующий знак приклеивается к ней: вирама
    (деванагари «्», кхмерский коенг «្», бирманский «္» — за ней идёт
    ПОДПИСНАЯ согласная), ZWJ/ZWNJ, ведущая гласная, одинокий знак флага."""
    import unicodedata as _ud
    last = prev[-1]
    if last in "\u200c\u200d" or last in _LEAD_LO:
        return True
    if _ud.category(last) == "Mn" and ("VIRAMA" in _ud.name(last, "") or "COENG" in _ud.name(last, "")):
        return True
    return 0x1F1E6 <= ord(last) <= 0x1F1FF and len(prev) == 1


def _graphemes(text: str) -> list:
    """Текст → графемы: основа плюс идущие за ней комбинирующие знаки.
    Разрез только МЕЖДУ графемами — огласовка не отрывается от согласной,
    подписная согласная — от вирамы, тайское «ำ» не начинает строку,
    тон кожи эмодзи и флаг остаются целыми."""
    import unicodedata as _ud
    out = []
    for ch in text or "":
        glue = bool(out) and (_ud.category(ch).startswith("M") or ch in "\u200c\u200d"
                              or ch in _TRAIL_LO or 0x1F3FB <= ord(ch) <= 0x1F3FF
                              or (0x1F1E6 <= ord(ch) <= 0x1F1FF and len(out[-1]) == 1
                                  and 0x1F1E6 <= ord(out[-1]) <= 0x1F1FF)
                              or _joins_next(out[-1]))
        if glue:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _char_tokens(text: str) -> list:
    """Графемы, но слово НЕиероглифического письма внутри («COVID-19» среди
    иероглифов) — одним куском: латинское слово пополам не режется."""
    import unicodedata as _ud
    out = []
    for g in _graphemes(text):
        ch = g[0]
        word = ch.isalnum() and not _ud.name(ch, "").startswith(("CJK", "HIRAGANA", "KATAKANA", "HANGUL"))
        if word and out and out[-1][-1:].isalnum() and not _ud.name(out[-1][-1], "").startswith(
                ("CJK", "HIRAGANA", "KATAKANA", "HANGUL")):
            out[-1] += g
        else:
            out.append(g)
    return out


def _mode(text: str, n: Optional[dict]) -> str:
    if n:
        return n.get("cut") or "word"
    return "char" if _spaceless(text) else "word"


_RE_CACHE: dict = {}


def _sent_re(n: Optional[dict]):
    key = ("s", (n or {}).get("sentence_end") or "")
    if key not in _RE_CACHE:
        chars = _SENT_END_BASE + key[1]
        _RE_CACHE[key] = re.compile("[" + re.escape(chars) + "][" + re.escape(_CLOSERS) + r"]*\s*$")
    return _RE_CACHE[key]


def _clause_re(n: Optional[dict]):
    if not n:
        return _PUNCT_END
    key = ("c", (n.get("clause") or "") + (n.get("sentence_end") or ""))
    if key not in _RE_CACHE:
        chars = _CLAUSE_BASE + key[1]
        _RE_CACHE[key] = re.compile("[" + re.escape(chars) + "][" + re.escape(_CLOSERS) + r"]*$")
    return _RE_CACHE[key]


def _spaceless(text: str) -> bool:
    """Письмо без пробелов (иероглифы, кана, тайский): мерка длины своя.
    Эвристика — только когда язык не назван."""
    t = (text or "").strip()
    return len(t) > 12 and len(t.split()) <= max(1, len(t) // 12)


def _unit_done(u: dict, n: Optional[dict] = None) -> bool:
    """В единице уже есть законченная мысль (а не одно-два слова)."""
    t = u.get("text") or ""
    if _mode(t, n) != "word":
        return glen(t) >= 10 or u["end"] - u["start"] >= UNIT_DONE_SEC
    return (len(t.split()) >= UNIT_DONE_WORDS or glen(t) >= UNIT_DONE_CHARS
            or u["end"] - u["start"] >= UNIT_DONE_SEC)


def _unit_of(pieces: list, join: str = " ") -> dict:
    return {"start": pieces[0]["start"], "end": max(p["end"] for p in pieces),
            "text": join.join(p["text"] for p in pieces),
            "spans": [[p["start"], p["end"]] for p in pieces]}


def sentence_cues(cues: list, max_sec: float = None, max_chars: int = None, lang=None) -> list:
    """Реплики распознавания (по времени) → единицы-предложения
    [{start, end, text, spans}]. Граница — конец предложения (свои знаки
    у письменности: «।», «։», «።», «။»…); пауза ≥ UNIT_PAUSE_SOFT у
    законченной единицы; пауза ≥ UNIT_PAUSE_HARD всегда. Упёрлась в потолок
    времени или длины — режется на САМОЙ ДЛИННОЙ паузе внутри (там, скорее
    всего, и кончилась мысль). Потолок длины — в графемах и масштабируется
    по ширине строки языка (китайский — 16 из 42). Куски склеиваются по
    норме языка: иероглифы — без пробела. `spans` — время исходных кусков:
    по ним экранные части не повиснут в тишине (`display_cues`). Слова
    не теряются и не переставляются. У тайского точек почти нет — граница
    там только паузы и потолки."""
    n = sub_norm(lang)
    join = n.get("join", " ") if n else " "
    max_sec = UNIT_MAX_SEC if max_sec is None else max_sec
    if max_chars is None:
        max_chars = int(round(UNIT_MAX_CHARS * (n["line"] / 42.0))) if n else UNIT_MAX_CHARS
    end_re = _sent_re(n)
    out, cur = [], []

    def over(pcs):
        return (len(pcs) > 1 and (pcs[-1]["end"] - pcs[0]["start"] > max_sec
                                  or sum(glen(p["text"]) for p in pcs) + len(join) * (len(pcs) - 1) > max_chars))

    for c in sorted((c for c in cues or [] if (c.get("text") or "").strip()), key=lambda c: c["start"]):
        piece = {"start": float(c["start"]), "end": float(c["end"]), "text": " ".join(c["text"].split())}
        if cur:
            u = _unit_of(cur, join)
            gap = piece["start"] - u["end"]
            if (end_re.search(u["text"]) or gap >= UNIT_PAUSE_HARD
                    or (gap >= UNIT_PAUSE_SOFT and _unit_done(u, n))):
                out.append(u)
                cur = []
        cur.append(piece)
        while over(cur):
            # Режем на самой длинной паузе; при равных — ближе к концу,
            # чтобы голова единицы была как можно полнее.
            k = max(range(1, len(cur)), key=lambda j: (cur[j]["start"] - cur[j - 1]["end"], j))
            out.append(_unit_of(cur[:k], join))
            cur = cur[k:]
    if cur:
        out.append(_unit_of(cur, join))
    return out


def _cut_tokens(tokens: list, fracs: list, sep: str = " ", punct=None, no_start=None) -> list:
    """Куски (слова или графемы) → части с границами у долей `fracs` (по длине
    в графемах), в пределах пятой части длины части — после знака
    препинания. Граница не ставится перед знаком из `no_start` (кинсоку).
    Пустых частей нет."""
    punct = punct or _PUNCT_END
    total = sum(glen(t) + len(sep) for t in tokens) or 1
    bounds, acc = [], 0
    for i, t in enumerate(tokens[:-1]):
        acc += glen(t) + len(sep)
        nxt = tokens[i + 1]
        if no_start and nxt and (nxt[0] in no_start or nxt.strip() == ""):
            continue
        bounds.append((i + 1, acc, bool(punct.search(t))))
    cuts, pos, prev = [], 0, 0.0
    for f in fracs:
        target = total * f
        tol = total * (f - prev) * 0.2
        prev = f
        free = [b for b in bounds if b[0] > pos]
        cand = [b for b in free if abs(b[1] - target) <= tol and b[2]]
        pool = cand or free
        if not pool:
            break
        best = min(pool, key=lambda b: abs(b[1] - target))
        cuts.append(best[0])
        pos = best[0]
    edges = [0] + cuts + [len(tokens)]
    parts = [sep.join(tokens[edges[i]:edges[i + 1]]).strip() for i in range(len(edges) - 1)
             if edges[i] < edges[i + 1]]
    return [p for p in parts if p]


def _cut_words(words: list, fracs: list) -> list:
    """Слова → части (см. `_cut_tokens`)."""
    return _cut_tokens(words, fracs, " ")


def _text_parts(text: str, fracs: list, n: Optional[dict] = None) -> list:
    """Текст → части у долей `fracs` по правилу письма: word — по пробелам
    (одно слово не режется: буквы слова на двух экранах — не субтитры);
    char — между графемами, с кинсоку и предпочтением знака препинания;
    phrase — по пробелам (в тайском это граница фразы), а фраза без пробелов
    — между графемами, крайним ходом. Частей бывает меньше — вызывающий
    это видит."""
    t = " ".join((text or "").split())
    if not fracs or not t:
        return [t] if t else []
    punct = _clause_re(n)
    if n is None:
        # Язык не назван — прежний порядок: есть пробелы — по словам.
        if " " in t:
            return _cut_tokens(t.split(" "), fracs, " ", punct)
        if not _spaceless(t):
            return [t]
        return _cut_tokens(_char_tokens(t), fracs, "", punct, _NO_START)
    mode = _mode(t, n)
    if mode == "word" or (mode == "phrase" and " " in t):
        if " " in t:
            return _cut_tokens(t.split(" "), fracs, " ", punct)
        return [t]
    return _cut_tokens(_char_tokens(t), fracs, "", punct, _NO_START)


def _speech_runs(start: float, end: float, spans) -> list:
    """Отрезки речи единицы, разделённые паузами ≥ SCREEN_GAP: экранная часть
    через такую паузу не перекидывается. Без опорных точек — вся единица."""
    ss = sorted(([float(a), float(b)] for a, b in (spans or []) if b > a), key=lambda x: x[0])
    ss = [[max(a, start), min(b, end)] for a, b in ss if min(b, end) > max(a, start)]
    if not ss:
        return [[start, end]]
    runs = [list(ss[0])]
    for a, b in ss[1:]:
        if a - runs[-1][1] >= SCREEN_GAP:
            runs.append([a, b])
        else:
            runs[-1][1] = max(runs[-1][1], b)
    runs[0][0], runs[-1][1] = start, end
    return runs


def _screen_cap(text: str, n: Optional[dict]) -> int:
    """Графем на экранную часть: две строки языка."""
    if n:
        return 2 * int(n["line"])
    return SCREEN_MAX_CHARS_CJK if _spaceless(text) else SCREEN_MAX_CHARS


def _screen_k(text: str, dur: float, min_sec: float, n: Optional[dict] = None) -> int:
    k = max(1, -(-glen(text) // _screen_cap(text, n)), -(-int(dur * 1000) // int(SCREEN_MAX_SEC * 1000)))
    return max(1, min(k, int(dur // min_sec))) if min_sec > 0 else k


def _split_window(c: dict, a: float, b: float, text: str, src, min_sec: float,
                  n: Optional[dict] = None, ns: Optional[dict] = None) -> list:
    """Одно окно речи → экранные части поровну по длине текста."""
    dur = max(0.0, b - a)
    k = _screen_k(text, dur, min_sec, n)
    if src is not None:
        k = max(k, min(_screen_k(src, dur, min_sec, ns), max(1, int(dur // min_sec))))
    while True:
        parts = _text_parts(text, [j / k for j in range(1, k)], n) if k > 1 else [text]
        total = float(sum(glen(p) for p in parts)) or 1.0
        # Граница у знака препинания сдвигает долю на пятую часть — часть
        # короче `min_sec` глаз не прочтёт: частей тогда на одну меньше.
        if len(parts) < 2 or all(dur * glen(p) / total >= min_sec - 1e-6 for p in parts):
            break
        k = len(parts) - 1
    if src is not None:
        srcs = _text_parts(src, [j / len(parts) for j in range(1, len(parts))], ns) if len(parts) > 1 else [src]
        if len(srcs) != len(parts):
            srcs = [src] + [""] * (len(parts) - 1)
    total = float(sum(glen(p) for p in parts)) or 1.0
    out, t, acc = [], a, 0
    for j, p in enumerate(parts):
        acc += glen(p)
        e = b if j == len(parts) - 1 else a + dur * acc / total
        piece = dict(c, start=round(t, 3), end=round(e, 3), text=p)
        piece.pop("spans", None)
        if src is not None:
            piece["src"] = srcs[j]
        out.append(piece)
        t = e
    return out


def display_cues(cues: list, min_sec: float = CUE_MIN_SEC, lang=None, src_lang=None) -> list:
    """Единицы-предложения → экранные куски субтитров (то, что видит зритель).
    Сначала единица делится по крупным паузам речи (`spans`, пауза
    ≥ SCREEN_GAP): текст перевода раздаётся отрезкам речи по доле их времени,
    и ни одна часть не висит на экране в тишине. Затем отрезок длиннее двух
    строк языка (`sub_norm`: 42 знака, у китайского 16, у японского 13) или
    SCREEN_MAX_SEC делится на равные по длине части (граница — после знака
    препинания рядом; у иероглифов — между знаками с кинсоку, у тайского —
    между фразами); время частей — доли окна по длине ТЕКСТА части в
    графемах: перевод пословно речи не соответствует. Часть не короче
    `min_sec`. Поля реплики (`i` — её номер) переезжают в каждую часть; язык
    текста реплики — `lang` у самой реплики (непереведённая идёт на языке
    оригинала), иначе аргумент. У реплики с `src` (двуязычные субтитры)
    оригинал делится своим языком (`src_lang`) на то же число частей."""
    ns = sub_norm(src_lang)
    out = []
    for c in cues or []:
        text = " ".join((c.get("text") or "").split())
        if c.get("start") is None or c.get("end") is None or not text:
            out.append(c)
            continue
        n = sub_norm(c.get("lang") or lang)
        s0, e0 = float(c["start"]), float(c["end"])
        src = " ".join((c.get("src") or "").split()) if c.get("src") is not None else None
        runs = _speech_runs(s0, e0, c.get("spans"))
        runs = [r for r in runs if r[1] - r[0] > 0] or [[s0, e0]]
        # Раздать текст отрезкам речи по доле ВРЕМЕНИ; отрезок, которому
        # досталось меньше секунды, сливается с соседом (читать нечего).
        while len(runs) > 1 and min(r[1] - r[0] for r in runs) < min_sec:
            j = min(range(len(runs)), key=lambda x: runs[x][1] - runs[x][0])
            m = j - 1 if j == len(runs) - 1 or (j > 0 and runs[j - 1][1] - runs[j - 1][0]
                                                  <= runs[j + 1][1] - runs[j + 1][0]) else j + 1
            lo, hi = min(j, m), max(j, m)
            runs[lo:hi + 1] = [[runs[lo][0], runs[hi][1]]]
        if len(runs) > 1:
            speech = sum(r[1] - r[0] for r in runs)
            acc, fr = 0.0, []
            for r in runs[:-1]:
                acc += r[1] - r[0]
                fr.append(acc / speech)
            tp = _text_parts(text, fr, n)
            sp = _text_parts(src, fr, ns) if src is not None else None
            if len(tp) != len(runs):
                runs, tp, sp = [[s0, e0]], [text], ([src] if src is not None else None)
            elif sp is not None and len(sp) != len(runs):
                # Оригинал не делится так же (пуст, одно слово) — деление
                # по паузам решает перевод, оригинал остаётся в первой части.
                sp = [src] + [""] * (len(runs) - 1)
        else:
            tp, sp = [text], ([src] if src is not None else None)
        pieces = []
        for j, r in enumerate(runs):
            pieces += _split_window(c, r[0], r[1], tp[j], sp[j] if sp is not None else None, min_sec, n, ns)
        if len(pieces) == 1:
            one = dict(c)
            one.pop("spans", None)
            out.append(one)
        else:
            out.extend(pieces)
    return out


_RLM = "‏"


def screen_lines(text: str, lang) -> list:
    """Строки экрана одной части для .srt/.vtt по норме языка: до `line`
    графем — одна строка, длиннее — две равные (граница у знака препинания,
    у иероглифов — с кинсоку), очень длинная — три. У письма справа налево
    строка обрамлена меткой RLM: иначе строка, начатая цифрой или латиницей,
    у плеера переворачивается. Метка в счёт длины не входит (`glen`)."""
    n = sub_norm(lang) or sub_norm("EN")
    t = " ".join((text or "").split())
    width = int(n["line"])
    if glen(t) <= width:
        lines = [t] if t else []
    elif n.get("cut") == "word":
        # Письмо с пробелами — прежнее правило экрана: две РАВНЫЕ строки,
        # разрез на пробеле ближе к середине («лесенка» читается хуже).
        try:
            import importers as _imp
        except ImportError:                     # запуск как пакет backend
            from backend import importers as _imp  # type: ignore
        lines = _imp.wrap_cue(t, width)
    else:
        parts = _text_parts(t, [0.5], n)
        if len(parts) == 2 and glen(parts[1]) > width * 1.6:
            lines = [parts[0]] + [ln.strip(_RLM) for ln in screen_lines(parts[1], lang)]
        else:
            lines = parts
    if n.get("rtl"):
        lines = [_RLM + ln + _RLM for ln in lines]
    return lines


def budget_chars(sec, lang) -> Optional[int]:
    """Сколько графем перевода уложится в строку длиной `sec`: меньшая из
    скоростей ЧТЕНИЯ (экран) и РЕЧИ (озвучка) языка перевода — перевод
    идёт и туда, и туда. У русского и английского — прежние 15 зн/с."""
    if not sec or sec <= 0:
        return None
    n = sub_norm(lang) or sub_norm("EN")
    return max(1, int(round(float(sec) * min(float(n["read_cps"]), float(n["speak_cps"])))))


# ─── Озвучка ─────────────────────────────────────────────────────────

def fit_tempo(clip_sec: float, window_sec: float) -> tuple:
    """(ускорение, вердикт) — как уложить фразу длиной `clip_sec` в окно:
    ok | fast (заметно быстро) | over (не влезает и при предельном ускорении)."""
    if window_sec <= 0.05 or clip_sec <= window_sec:
        return 1.0, "ok"
    need = clip_sec / window_sec
    if need <= TEMPO_SOFT:
        return round(need, 3), "ok"
    if need <= TEMPO_HARD:
        return round(need, 3), "fast"
    return TEMPO_HARD, "over"


def atempo_pcm(pcm: bytes, tempo: float) -> bytes:
    """Ускорить речь без смены высоты голоса (фильтр atempo, 0.5–2.0)."""
    if abs(tempo - 1.0) < 0.01 or not pcm:
        return pcm
    r = run(_ffmpeg("-f", "s16le", "-ar", TTS_RATE, "-ac", 1, "-i", "pipe:0",
                    "-af", "atempo=%.3f" % tempo, "-f", "s16le", "-ar", TTS_RATE, "-ac", 1, "pipe:1"),
            timeout=120, stdin=pcm)
    return r.stdout


def pcm_seconds(pcm: bytes) -> float:
    return len(pcm) / 2.0 / TTS_RATE


def open_track(track_path, duration: float):
    """Пустая дорожка озвучки на диске (memmap): отсчёты не держатся в памяти
    воркера, клипы кладутся по одному (`add_clip`)."""
    import numpy as np
    n = int((duration + 1.0) * TTS_RATE)
    track = np.memmap(str(track_path), dtype=np.int16, mode="w+", shape=(n,))
    track[:] = 0
    return track


def add_clip(track, start: float, pcm: bytes) -> None:
    """Наложить клип с насыщением, а не переполнением."""
    import numpy as np
    a = np.frombuffer(pcm, dtype=np.int16)
    n = len(track)
    i = int(max(0.0, start) * TTS_RATE)
    if i >= n or not len(a):
        return
    a = a[:n - i]
    seg = track[i:i + len(a)].astype(np.int32) + a.astype(np.int32)
    track[i:i + len(a)] = np.clip(seg, -32768, 32767).astype(np.int16)


def close_track(track) -> None:
    track.flush()


def place_clips(track_path, duration: float, clips: list) -> None:
    """Собрать дорожку озвучки в файл сырых отсчётов (s16le 24 кГц моно)
    через memmap: [(начало в секундах, pcm)]. Наложение складывается
    с насыщением, а не переполнением."""
    import numpy as np
    n = int((duration + 1.0) * TTS_RATE)
    track = np.memmap(str(track_path), dtype=np.int16, mode="w+", shape=(n,))
    track[:] = 0
    for start, pcm in clips:
        a = np.frombuffer(pcm, dtype=np.int16)
        i = int(max(0.0, start) * TTS_RATE)
        if i >= n or not len(a):
            continue
        a = a[:n - i]
        seg = track[i:i + len(a)].astype(np.int32) + a.astype(np.int32)
        track[i:i + len(a)] = np.clip(seg, -32768, 32767).astype(np.int16)
    track.flush()
    del track


# ─── Сборка результата ───────────────────────────────────────────────

def output_ext(info: dict) -> str:
    """Контейнер результата: без видео — .m4a; видео, которое mp4 держит
    копией потока, — .mp4 (открывается везде, включая телефон); иначе .mkv."""
    v = info.get("video")
    if not v:
        return ".m4a"
    return ".mp4" if (v.get("codec") or "") in MP4_VCODECS else ".mkv"


def _vtag(info: dict, ext: str) -> list:
    """HEVC в mp4 с меткой hev1 плееры Apple не открывают — ставим hvc1."""
    v = info.get("video") or {}
    return ["-tag:v", "hvc1"] if ext == ".mp4" and v.get("codec") == "hevc" else []


def _span_in(span) -> list:
    """Входные ключи отрезка исходника: (с какой секунды, сколько). Для
    сборок копией потока начало — КЛЮЧЕВОЙ кадр (`keyframe_before`):
    копия не умеет начать посреди группы кадров."""
    if not span:
        return []
    ss, t = span
    return (["-ss", "%.3f" % ss] if ss > 0 else []) + (["-t", "%.3f" % t] if t else [])


def mux_subtitles(src, srt, dst, info: dict, lang: str = "", span=None) -> None:
    """Видео + дорожка субтитров, ВСЁ копией потока. В mp4 субтитры —
    mov_text (текст), в mkv — srt. Оригинальный звук не трогается."""
    ext = Path(dst).suffix.lower()
    scodec = "mov_text" if ext == ".mp4" else "srt"
    # Звук, который mp4 не держит (pcm из .mov, vorbis из .mkv), —
    # в aac; перекодировать звук дёшево, видео не трогается никогда.
    acodec = "copy"
    if ext == ".mp4" and (info.get("audio") or {}).get("codec") not in MP4_ACODECS:
        acodec = "aac"
    args = _span_in(span) + ["-i", src, "-i", srt, "-map", "0:v:0", "-map", "0:a?", "-map", "1:0",
            "-c:v", "copy", "-c:a", acodec, "-c:s", scodec] + _vtag(info, ext)
    # Дорожка помечается «показывать по умолчанию». Без метки плееры
    # (Кино и ТВ в Windows, телефоны, часть сборок VLC) её не включают сами,
    # и человек, скачавший «видео с субтитрами», видел видео без текста.
    args += ["-disposition:s:0", "default"]
    if lang:
        args += ["-metadata:s:s:0", "language=" + lang]
    if ext == ".mp4":
        args += ["-movflags", "+faststart"]
    run(_ffmpeg(*(args + [dst])), timeout=max(600.0, (info.get("duration") or 0) * 0.5))


def mux_dub(src, track_path, dst, info: dict, duck: float = 0.2, lang: str = "", span=None) -> None:
    """Закадровый перевод: оригинальный звук приглушается ПОД речью
    (sidechaincompress — пока говорит озвучка) и остаётся фоном, поверх —
    новая речь. Видео — копией потока; вторая дорожка — оригинальный звук
    как был, чтобы зритель мог переключиться. У звукового файла на входе
    результат — m4a с одной дорожкой."""
    ext = Path(dst).suffix.lower()
    has_video = bool(info.get("video")) and ext != ".m4a"
    base = max(0.05, min(1.0, float(duck)))
    fc = ("[1:a]aresample=48000,asplit=2[sc][voice];"
          "[0:a:0]aresample=48000,volume=%.2f[bg];"
          "[bg][sc]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[ducked];"
          "[ducked][voice]amix=inputs=2:normalize=0:duration=first[out]" % (0.6 + base))
    args = _span_in(span) + ["-i", src, "-f", "s16le", "-ar", TTS_RATE, "-ac", 1, "-i", track_path,
            "-filter_complex", fc]
    if has_video:
        args += ["-map", "0:v:0", "-c:v", "copy"] + _vtag(info, ext)
    args += ["-map", "[out]", "-c:a:0", "aac", "-b:a:0", "160k"]
    if has_video:
        args += ["-map", "0:a:0", "-c:a:1", "aac" if ext == ".mp4" and (info.get("audio") or {}).get("codec") not in MP4_ACODECS else "copy"]
        args += ["-disposition:a:0", "default", "-disposition:a:1", "0"]
        if lang:
            args += ["-metadata:s:a:0", "language=" + lang]
    if ext in (".mp4", ".m4a"):
        args += ["-movflags", "+faststart"]
    run(_ffmpeg(*(args + [dst])), timeout=max(900.0, (info.get("duration") or 0) * 1.0))


def keyframe_before(src, t: float) -> float:
    """Время ключевого кадра не позже `t`. Сборка копией потока начинается
    только с него, и вызывающий сдвигает реплики на разницу — иначе у
    обрезанного видео субтитры ехали бы на пару секунд. Читаются только
    пакеты около `t` (`-read_intervals`), кадры не декодируются."""
    if t <= 0.05:
        return 0.0
    # Время кадров у ffprobe — абсолютное (с `start_time` контейнера:
    # у MPEG-TS/AVCHD это секунда-полторы), а `-ss` ffmpeg считает от начала
    # файла. Сравниваем и отдаём в шкале `-ss`, иначе сдвиг реплик врал бы
    # ровно на start_time.
    r0 = run([_bin("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=start_time",
              "-of", "csv=p=0", str(src)], timeout=60)
    base = _num((r0.stdout or b"").decode("utf-8", "replace").strip().split(",")[0])
    for back in (20.0, 180.0):
        a = max(0.0, t - back)
        cmd = [_bin("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
               "-show_entries", "frame=pts_time,best_effort_timestamp_time", "-of", "csv=p=0",
               "-read_intervals", "%.3f%%+%.3f" % (base + a, t - a + 0.5), str(src)]
        r = run(cmd, timeout=120)
        best = None
        for line in (r.stdout or b"").decode("utf-8", "replace").splitlines():
            for v in line.split(","):
                x = _num(v) - base if v.strip() not in ("", "N/A") else None
                if x is not None and x <= t + 0.001 and (best is None or x > best):
                    best = x
        if best is not None:
            return round(max(0.0, best), 3)
    # Ключевого кадра рядом нет: берём файл с начала. Ролик выйдет длиннее
    # обрезки, но реплики сдвинутся на всю разницу и встанут верно.
    print("[media] ключевой кадр до %.1f с не найден — сборка с начала файла" % t, file=sys.stderr)
    return 0.0


# ─── Субтитры В КАДРЕ (burn-in) ──────────────────────────────────────
#
# Единственная работа модуля, которая ДЕКОДИРУЕТ кадры: текст рисуется
# в картинку, значит видео перекодируется целиком. Чем это ограничено:
#   * кусками по BURN_SEG_SEC: между кусками прогон уступает очередь
#     чужим задачам, а после рестарта продолжает с первого несделанного —
#     каждый кусок лежит файлом;
#   * короткая сторона кадра не больше 1080 (`BURN_QUALITIES`): 4K
#     кодировался бы вчетверо дольше на общем сервере;
#   * x264 veryfast, потоков BURN_THREADS, nice 19 (`_polite`).
# Шрифты — ТЕ ЖЕ файлы, что браузер берёт для предпросмотра
# (frontend/vendor/fonts/sub), а окончательное «как будет» показывает
# `preview_frame` — тем же фильтром и тем же документом, что сборка.

FONT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "vendor" / "fonts" / "sub"
BURN_SEG_SEC = float(os.environ.get("MEDIA_BURN_SEG_SEC", "120"))
BURN_THREADS = max(1, int(os.environ.get("MEDIA_BURN_THREADS", "2")))
BURN_PRESET = os.environ.get("MEDIA_BURN_PRESET", "veryfast")
BURN_CRF = int(os.environ.get("MEDIA_BURN_CRF", "23"))
# Сколько секунд работы на секунду видео 1080p 30 к/с. Замер на боевом
# сервере 25.09.2026: шумный синтетический ролик (худший случай для
# кодека), veryfast, 2 потока, nice 19 — 1,6; 720p — 0,85.
BURN_SPEED = float(os.environ.get("MEDIA_BURN_SPEED", "1.6"))
# Качество → потолок КОРОТКОЙ стороны кадра. «Как в оригинале» — тоже
# с потолком: 4K на общем сервере — это часы на каждый час видео.
BURN_QUALITIES = {"src": 1080, "720": 720, "480": 480}
BURN_FPS_MAX = 60.0

# Стиль субтитров. Размер — в процентах КОРОТКОЙ стороны кадра: так
# вертикальное видео с телефона и горизонтальное получают одинаково
# читаемый текст, а не текст во весь экран у вертикального.
SUB_BG = ("outline", "shadow", "box")
SUB_POS = ("bottom", "top")
STYLE_DEFAULT = {"font": "noto-sans", "size": 5.5, "bold": False, "color": "#FFFFFF",
                 "bg": "outline", "position": "bottom", "margin": 6.0,
                 "boxW": 90.0, "maxLines": 2, "fit": "both"}
SIZE_MIN, SIZE_MAX = 2.5, 12.0
MARGIN_MIN, MARGIN_MAX = 2.0, 30.0
# Безопасная область субтитров: ширина — доля кадра, высота — число строк
# (так её задают везде: «не больше двух строк»). Не влезает — `fit`:
# both — сначала уменьшить шрифт (не мельче FIT_MIN_SCALE), потом разделить
# реплику на части по времени; shrink / split — только одно из двух;
# none — ничего не менять, только назвать, какие реплики вылезли.
BOXW_MIN, BOXW_MAX = 30.0, 100.0
LINES_MIN, LINES_MAX = 1, 4
FIT_MODES = ("both", "shrink", "split", "none")
FIT_MIN_SCALE = float(os.environ.get("MEDIA_SUB_MIN_SCALE", "0.7"))
SPLIT_MIN_SEC = 0.8            # часть реплики короче — глаз её не успевает прочесть
# Доли кегля — ОДНИ на сборку и на предпросмотр в браузере (их отдаёт
# `/api/media/fonts`): вторая копия чисел в .jsx разошлась бы с этой.
SUB_METRICS = {"outline": 0.07, "shadowOutline": 0.03, "shadow": 0.06, "boxPad": 0.2,
               "marginLR": 0.06, "boxAlpha": 0.25, "shadowAlpha": 0.45}

_FONTS_CACHE: dict = {"mtime": None, "data": {"fonts": []}}


def fonts_catalog() -> dict:
    """Каталог шрифтов субтитров (`fonts.json` рядом с файлами; собирает
    tools/sub_fonts.py — там же считается, какие письменности шрифт
    покрывает). Перечитывается при изменении файла."""
    p = FONT_DIR / "fonts.json"
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {"fonts": []}
    if _FONTS_CACHE["mtime"] != mt:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"fonts": []}
        _FONTS_CACHE.update(mtime=mt, data=data)
    return _FONTS_CACHE["data"]


def font_of(fid) -> Optional[dict]:
    return next((f for f in fonts_catalog().get("fonts") or [] if f.get("id") == fid), None)


# Образец субтитра на ЯЗЫКЕ ПЕРЕВОДА — для предпросмотра, пока перевода
# нет. Нужен именно этот язык: у узбекской кириллицы «ў қ ғ ҳ», у латиницы
# «ʻ», и проверить шрифт можно только на них. Языка нет в списке — по-английски.
SUB_SAMPLES = {
    "EN": "This is how your subtitles will look",
    "RU": "Так будут выглядеть субтитры",
    "UZ": "Subtitrlar mana shunday koʻrinadi, gʻoyat qulay",
    "UZ-CYRL": "Субтитрлар мана шундай кўринади, ғоят қулай ҳам",
    "KK": "Субтитрлер осылай көрінеді, өте қолайлы",
    "KY": "Субтитрлер ушундай көрүнөт, абдан ыңгайлуу",
    "TG": "Субтитрҳо чунин менамоянд, хеле қулай",
    "TK": "Subtitrler şeýle görner, örän amatly",
    "AZ": "Altyazılar belə görünəcək, çox rahatdır",
    "TR": "Altyazılar böyle görünecek, çok kullanışlı",
    "UK": "Так виглядатимуть субтитри, дуже зручно",
    "BE": "Так будуць выглядаць субтытры",
    "DE": "So werden die Untertitel aussehen",
    "FR": "Voici à quoi ressembleront les sous-titres",
    "ES": "Así se verán los subtítulos",
    "IT": "Ecco come appariranno i sottotitoli",
    "PT": "É assim que as legendas vão ficar",
    "PL": "Tak będą wyglądać napisy",
    "AR": "هكذا ستظهر الترجمة على الشاشة",
    "FA": "زیرنویس‌ها این‌گونه نمایش داده می‌شوند",
    "HE": "כך ייראו הכתוביות",
    "ZH": "字幕将会这样显示",
    "JA": "字幕はこのように表示されます",
    "KO": "자막은 이렇게 표시됩니다",
    "HI": "उपशीर्षक ऐसे दिखेंगे",
    "EL": "Έτσι θα εμφανίζονται οι υπότιτλοι",
    "KA": "სუბტიტრები ასე გამოჩნდება",
    "HY": "Ենթագրերը կերևան այսպես",
    "VI": "Phụ đề sẽ trông như thế này",
}


def sub_sample(lang: str) -> str:
    return SUB_SAMPLES.get((lang or "").upper()) or SUB_SAMPLES["EN"]


def _clamp(v, lo: float, hi: float, dflt: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return dflt
    if x != x:                                   # NaN
        return dflt
    return round(min(hi, max(lo, x)), 2)


def style_clean(raw) -> dict:
    """Стиль из запроса → проверенный стиль. Неизвестное заменяется
    умолчанием, а не отказом: стиль — оформление, и опечатка в одном поле
    не должна стоить сборки."""
    s = dict(STYLE_DEFAULT)
    raw = raw if isinstance(raw, dict) else {}
    if font_of(raw.get("font")):
        s["font"] = raw["font"]
    elif not font_of(s["font"]):
        fonts = fonts_catalog().get("fonts") or []
        if fonts:
            s["font"] = fonts[0]["id"]
    s["size"] = _clamp(raw.get("size", s["size"]), SIZE_MIN, SIZE_MAX, s["size"])
    s["margin"] = _clamp(raw.get("margin", s["margin"]), MARGIN_MIN, MARGIN_MAX, s["margin"])
    s["bold"] = bool(raw.get("bold", s["bold"]))
    c = str(raw.get("color") or "").upper()
    if re.fullmatch(r"#[0-9A-F]{6}", c):
        s["color"] = c
    if raw.get("bg") in SUB_BG:
        s["bg"] = raw["bg"]
    if raw.get("position") in SUB_POS:
        s["position"] = raw["position"]
    s["boxW"] = _clamp(raw.get("boxW", s["boxW"]), BOXW_MIN, BOXW_MAX, s["boxW"])
    s["maxLines"] = int(_clamp(raw.get("maxLines", s["maxLines"]), LINES_MIN, LINES_MAX, s["maxLines"]))
    if raw.get("fit") in FIT_MODES:
        s["fit"] = raw["fit"]
    return s


def display_size(video: dict) -> tuple:
    """(ширина, высота) кадра, КАК ЕГО ВИДИТ зритель: с поворотом
    и с квадратным пикселем."""
    w, h = int((video or {}).get("width") or 0), int((video or {}).get("height") or 0)
    sar = float((video or {}).get("sar") or 1.0)
    if sar > 0 and abs(sar - 1.0) > 0.01:
        w = int(round(w * sar))
    if (video or {}).get("rotation") in (90, 270):
        w, h = h, w
    return w, h


def _even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def out_size(video: dict, quality: str = "src") -> tuple:
    """Кадр результата: видимый размер, короткая сторона не больше потолка
    качества, обе стороны чётные (yuv420p иначе не кодируется)."""
    w, h = display_size(video)
    if not w or not h:
        raise MediaError("Размер кадра не определяется")
    cap = BURN_QUALITIES.get(quality, BURN_QUALITIES["src"])
    short = min(w, h)
    if short > cap:
        k = cap / float(short)
        w, h = w * k, h * k
    return _even(w), _even(h)


def out_fps(video: dict):
    """Частота кадров результата — ПОСТОЯННАЯ (дробью, чтобы 29,97 не
    копили расхождение), не выше 60. У телефонного видео она плавает, а
    куски склеиваются без швов только при одинаковой постоянной частоте."""
    from fractions import Fraction
    f = float((video or {}).get("fps") or 0.0)
    if not (1.0 <= f <= 240.0):
        f = 25.0
    return Fraction(min(f, BURN_FPS_MAX)).limit_denominator(1001)


def is_hdr(video: dict) -> bool:
    """10-битное видео (обычно HDR) сводится к 8 битам: цвета могут стать
    бледнее. Это называется человеку, а не прячется."""
    pf = str((video or {}).get("pixfmt") or "")
    return "10" in pf or "12" in pf


def burn_plan(length: float, fps) -> list:
    """Куски: [(начало в шкале результата, кадров или None для хвоста)].
    Граница — ровно на кадре: кусок в N кадров при постоянной частоте
    длится ровно N/fps, и склейка не копит расхождения со звуком."""
    n = max(1, int(round(BURN_SEG_SEC * float(fps))))
    step = n / float(fps)
    out, a = [], 0.0
    while a < length - 0.5 / float(fps):
        last = a + step >= length - 0.01
        out.append((round(a, 6), None if last else n))
        a += step
    return out or [(0.0, None)]


def burn_eta(video: dict, quality: str, length: float) -> float:
    """Оценка времени сборки в секундах — по замеру (`BURN_SPEED`), не
    обещание: на спокойной картинке быстрее, на шумной — так."""
    try:
        w, h = out_size(video, quality)
    except MediaError:
        return 0.0
    px = (w * h) / float(1920 * 1080)
    fps = float(out_fps(video))
    return round(length * (0.25 + 1.35 * px) * (fps / 30.0) * (BURN_SPEED / 1.6), 1)


def _ass_color(hexc: str, alpha: float = 0.0) -> str:
    """«#RRGGBB» + прозрачность 0..1 → «&HAABBGGRR»."""
    c = (hexc or "#FFFFFF").lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return "&H%02X%02X%02X%02X" % (int(round(max(0.0, min(1.0, alpha)) * 255)), b, g, r)


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def _ass_text(s: str) -> str:
    """Текст реплики для ASS: фигурные скобки — начало команды оформления,
    обратная косая — перевод строки. Ни то, ни другое из перевода клиента
    командой стать не должно."""
    s = (s or "").replace("\\", "∖").replace("{", "(").replace("}", ")")
    return "\\N".join(x.strip() for x in s.splitlines() if x.strip())


def style_numbers(style: dict, w: int, h: int) -> dict:
    """Кегль, обводка, тень, поля — в пикселях кадра результата."""
    m = SUB_METRICS
    fs = max(8, int(round(style["size"] / 100.0 * min(w, h))))
    if style["bg"] == "box":
        border, outline, shadow = 3, max(2, int(round(fs * m["boxPad"]))), 0
    elif style["bg"] == "shadow":
        border, outline, shadow = 1, max(1, int(round(fs * m["shadowOutline"]))), max(1, int(round(fs * m["shadow"])))
    else:
        border, outline, shadow = 1, max(1, int(round(fs * m["outline"]))), 0
    # Поле сбоку — из ширины области, плюс обводка или поле плашки: они
    # рисуются СНАРУЖИ букв, и область держит всё видимое, а не только буквы.
    side = int(round((100.0 - float(style.get("boxW") or 100.0)) / 200.0 * w)) + outline
    return {"fs": fs, "border": border, "outline": outline, "shadow": shadow,
            "marginV": int(round(style["margin"] / 100.0 * h)), "marginLR": side,
            "wrapW": max(20, w - 2 * side)}


# ─── Подгонка в безопасную область ───────────────────────────────────
# Строки считаются ТЕМ ЖЕ файлом шрифта, что у libass, и так же: жадный
# перенос по пробелам в ширину области (libass при WrapStyle 0 выравнивает
# строки по длине, но их ЧИСЛО то же). Кегль ASS → em в пикселях через
# `emRatio` каталога (libass меряет кегль высотой winAscent+winDescent).
_PIL_FONTS: dict = {}
_METERS: dict = {}
_LOCK_FIT = __import__("threading").Lock()


def _pil_font(path, px: int):
    key = (str(path), int(px))
    f = _PIL_FONTS.get(key)
    if f is None:
        from PIL import ImageFont
        if len(_PIL_FONTS) > 256:
            _PIL_FONTS.clear()
        f = _PIL_FONTS[key] = ImageFont.truetype(str(path), max(1, int(px)))
    return f


class _Meter:
    """Ширина слов одним шрифтом одного кегля — с памятью: каждое слово
    меряется ОДИН раз, строка — сумма слов и пробелов. Мерить строку целиком
    на каждом шаге переноса — квадратичная работа: сотня реплик считалась бы
    минутами прямо в запросе. Кернинг через пробел ничтожен."""

    def __init__(self, path, px: int, extra: float = 1.0):
        self.font = _pil_font(path, px)
        self.extra = extra                      # запас на синтетический жирный
        self.words: dict = {}
        self.space = self.font.getlength(" ") * extra

    def w(self, word: str) -> float:
        v = self.words.get(word)
        if v is None:
            if len(self.words) > 20000:
                self.words.clear()
            v = self.words[word] = self.font.getlength(word) * self.extra
        return v


def _meter(path, px: int, extra: float = 1.0) -> "_Meter":
    key = (str(path), int(px), extra)
    with _LOCK_FIT:
        m = _METERS.get(key)
        if m is None:
            if len(_METERS) > 64:
                _METERS.clear()
            m = _METERS[key] = _Meter(path, px, extra)
    return m


def _words_of(para: str) -> list:
    """Слова — по ОБЫЧНОМУ пробелу. Неразрывный (U+00A0: «300 мг») libass
    не рвёт, и мы не рвём: иначе мерка насчитала бы строк меньше, чем
    окажется в кадре."""
    return [x for x in re.split(r"[ \t]+", para) if x]


def wrap_lines(text: str, meter, width: float) -> list:
    """Жадный перенос по пробелам → [(строка, ширина)]; переводы строк
    в тексте — жёсткие. Слово шире области остаётся строкой-переростком."""
    out = []
    for para in (text or "").splitlines():
        cur, cw = [], 0.0
        for wd in _words_of(para):
            ww = meter.w(wd)
            cand = cw + (meter.space if cur else 0.0) + ww
            if not cur or cand <= width:
                cur.append(wd)
                cw = cand
            else:
                out.append((" ".join(cur), cw))
                cur, cw = [wd], ww
        if cur:
            out.append((" ".join(cur), cw))
    return out


def _fits(lines: list, width: float, max_lines: int) -> bool:
    return len(lines) <= max_lines and all(lw <= width + 0.5 for _l, lw in lines)


_PUNCT_END = re.compile(r"[.!?…;:,，、。！？]$")


def _balanced_parts(words: list, k: int) -> list:
    """Слова → k частей РАВНОЙ длины: граница у отметки j/k текста, а в пределах
    пятой части длины части — после знака препинания («…sig‘maydi, | shuning…»).
    Жадный перенос тут не годится: он оставил бы последнее слово одно,
    и такую часть на экране не успеть прочесть."""
    total = sum(len(w_) + 1 for w_ in words)
    cuts, pos, acc = [], 0, 0
    bounds = []
    for i, w_ in enumerate(words[:-1]):
        acc += len(w_) + 1
        bounds.append((i + 1, acc, bool(_PUNCT_END.search(w_))))
    for j in range(1, k):
        target = total * j / k
        tol = total / k * 0.2
        cand = [b for b in bounds if b[0] > pos and abs(b[1] - target) <= tol and b[2]]
        pool = cand or [b for b in bounds if b[0] > pos]
        if not pool:
            break
        best = min(pool, key=lambda b: abs(b[1] - target))
        cuts.append(best[0])
        pos = best[0]
    edges = [0] + cuts + [len(words)]
    return [" ".join(words[edges[i]:edges[i + 1]]) for i in range(len(edges) - 1) if edges[i] < edges[i + 1]]


def _split_cue(c: dict, n_lines: int, max_lines: int, fits) -> list:
    """Реплика, которая не помещается, → части поровну по длине (столько,
    сколько нужно, чтобы каждая уместилась в `max_lines` строк); время —
    пропорционально длине текста части. Если какая-то часть выходит короче
    SPLIT_MIN_SEC, делить нельзя: такую глаз не успевает прочесть."""
    words = _words_of(" ".join((c.get("text") or "").splitlines()))
    need = max(2, -(-n_lines // max_lines))
    for k in range(need, need + 3):
        groups = _balanced_parts(words, k)
        if len(groups) == k and all(fits(g) for g in groups):
            break
    else:
        return []
    total = float(sum(len(g) for g in groups)) or 1.0
    dur = c["end"] - c["start"]
    if any(dur * len(g) / total < SPLIT_MIN_SEC for g in groups):
        return []
    out, t = [], c["start"]
    for k, g in enumerate(groups):
        e = c["end"] if k == len(groups) - 1 else t + dur * len(g) / total
        out.append(dict(c, start=round(t, 3), end=round(e, 3), text=g))
        t = e
    return out


def _letter_script(ch: str) -> str:
    """Письменность буквы по имени в Юникоде («CYRILLIC SMALL LETTER A»
    → CYRILLIC); иероглифы и слоговые азбуки — к своей записи каталога."""
    import unicodedata
    name = unicodedata.name(ch, "")
    head = name.split(" ", 1)[0]
    if head in ("CJK", "HIRAGANA", "KATAKANA", "IDEOGRAPHIC"):
        return "HAN"
    return head


# Письменности, о которых имеет смысл спрашивать. Вспомогательные буквы
# (MODIFIER LETTER — узбекские «ʻ» и «ʼ», и прочие) письменностью не считаются:
# их в шрифте проверяет tools/sub_fonts.py пробой латиницы, а сочти мы их
# «неизвестной письменностью» — мерка выключалась бы у всего узбекского.
_KNOWN_SCRIPTS = {"LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "GEORGIAN", "HEBREW", "ARABIC", "DEVANAGARI",
                  "BENGALI", "GUJARATI", "GURMUKHI", "TAMIL", "TELUGU", "THAI", "KHMER", "MYANMAR",
                  "ETHIOPIC", "HAN", "HANGUL", "SYRIAC", "THAANA", "SINHALA", "KANNADA", "MALAYALAM",
                  "ORIYA", "LAO", "TIBETAN", "MONGOLIAN"}


def _covered(texts: list, scripts: set) -> bool:
    """Все ли буквы реплик — из письменностей, которые шрифт знает. Нет —
    libass возьмёт системный шрифт с другими размерами, а Pillow меряла бы
    пустые квадраты: «уместилось» было бы враньём."""
    seen = set()
    for t in texts:
        for ch in t:
            if ch in seen or not ch.isalpha():
                continue
            seen.add(ch)
            sc = _letter_script(ch)
            if sc in _KNOWN_SCRIPTS and sc not in scripts:
                return False
    return True


def fit_cues(cues: list, style: dict, w: int, h: int) -> tuple:
    """(события для ASS, отчёт). Отчёт — номера реплик (`i` у реплики):
    shrunk — уменьшен шрифт, split — разделена по времени, over — не
    уместилась никак (длинное слово, слишком короткая реплика, режим none).
    Мерить нечем (нет Pillow, нет файла шрифта, буквы письменности, которой
    в шрифте нет) — события как есть, `measured: False`: «всё поместилось»
    без мерки было бы враньём."""
    rep = {"shrunk": [], "split": [], "over": [], "measured": False}
    cues = list(cues or [])
    font = font_of(style.get("font")) or {}
    name, extra = font.get("regular"), 1.0
    if style.get("bold"):
        if font.get("bold"):
            name = font["bold"]
        else:
            extra = 1.05                         # libass дорисует жирный сам — шире
    path = FONT_DIR / name if name else None
    if not path or not path.exists():
        return cues, rep
    if font.get("scripts") and not _covered([c.get("text") or "" for c in cues], set(font["scripts"])):
        return cues, rep
    try:
        _pil_font(path, 20)
    except Exception:
        return cues, rep
    rep["measured"] = True
    n = style_numbers(style, w, h)
    em = float(font.get("emRatio") or 1.0)
    width, base = n["wrapW"], n["fs"]
    maxl, mode = int(style.get("maxLines") or 2), style.get("fit") or "both"
    floor_fs = max(8, int(base * FIT_MIN_SCALE))

    def meter(fs):
        return _meter(path, round(fs * em), extra)

    def fits_at(fs, text):
        return _fits(wrap_lines(text, meter(fs), width), width, maxl)

    out = []
    m0 = meter(base)
    for c in cues:
        text = c.get("text") or ""
        lines = wrap_lines(text, m0, width)
        if _fits(lines, width, maxl):
            out.append(c)
            continue
        done = False
        if mode in ("shrink", "both") and fits_at(floor_fs, text):
            # Крупнейший кегль, при котором влезает, — двоичным поиском.
            lo, hi = floor_fs, base - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits_at(mid, text):
                    lo = mid
                else:
                    hi = mid - 1
            out.append(dict(c, fs=lo))
            rep["shrunk"].append(c.get("i"))
            done = True
        if not done and mode in ("split", "both"):
            # Сперва полным кеглем; в режиме «оба» — и уменьшенным: две
            # части мельче лучше трёх или «не влезло».
            for fs in ([base, floor_fs] if mode == "both" else [base]):
                parts = _split_cue(c, len(lines), maxl, lambda g, fs=fs: fits_at(fs, g))
                if parts:
                    out.extend(dict(p, fs=fs) if fs != base else p for p in parts)
                    rep["split"].append(c.get("i"))
                    done = True
                    break
        if not done:
            out.append(c)
            rep["over"].append(c.get("i"))
    return out, rep


def ass_document(cues: list, style: dict, w: int, h: int, fitted: Optional[list] = None) -> str:
    """Документ ASS: один стиль, по событию на реплику. PlayRes = кадр
    результата, поэтому кегль в пикселях — ровно тот, что посчитан.
    Реплики сперва подгоняются в безопасную область (`fit_cues`); уже
    подогнанные можно передать готовыми (`fitted`), чтобы не мерить дважды."""
    if fitted is None:
        fitted, _rep = fit_cues(cues, style, w, h)
    cues = fitted
    font = font_of(style.get("font")) or {}
    family = font.get("family") or "Noto Sans"
    n = style_numbers(style, w, h)
    dark = style["color"].upper() in ("#000000",)
    edge = "#FFFFFF" if dark else "#000000"
    if style["bg"] == "box":
        outc = backc = _ass_color(edge, SUB_METRICS["boxAlpha"])
    else:
        outc = _ass_color(edge)
        backc = _ass_color(edge, SUB_METRICS["shadowAlpha"])
    align = 8 if style["position"] == "top" else 2
    head = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % w, "PlayResY: %d" % h,
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: None", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,%s,%d,%s,%s,%s,%s,%d,0,0,0,100,100,0,0,%d,%d,%d,%d,%d,%d,%d,1" % (
            family, n["fs"], _ass_color(style["color"]), _ass_color(style["color"]), outc, backc,
            -1 if style.get("bold") else 0, n["border"], n["outline"], n["shadow"], align,
            n["marginLR"], n["marginLR"], n["marginV"]),
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    ev = []
    for c in sorted(cues or [], key=lambda x: x["start"]):
        text = _ass_text(c.get("text") or "")
        if not text or c["end"] <= c["start"]:
            continue
        if c.get("fs"):
            text = r"{\fs%d}" % int(c["fs"]) + text       # уменьшенный кегль — только этой реплике
        ev.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (_ass_time(c["start"]), _ass_time(c["end"]), text))
    return "\n".join(head + ev) + "\n"


def _fpath(p) -> str:
    """Путь в аргументе фильтра: косые вперёд, двоеточие экранировано
    (на Windows «C:» иначе резал бы параметры), в кавычках."""
    s = str(Path(p).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return "'" + s + "'"


def _burn_vf(ass_name: str, w: int, h: int, offset: float) -> str:
    """Масштаб в кадр результата (поворот ffmpeg применяет сам, до фильтров),
    квадратный пиксель, субтитры по времени шкалы РЕЗУЛЬТАТА (`offset` —
    где в ней начинается кусок), 8 бит."""
    return ("scale=%d:%d:flags=bicubic,setsar=1,setpts=PTS-STARTPTS+%.6f/TB,"
            "ass=%s:fontsdir=%s,setpts=PTS-STARTPTS,format=yuv420p"
            % (w, h, offset, ass_name, _fpath(FONT_DIR)))


def _ffmpeg_burn(*args) -> list:
    return [_bin("ffmpeg") or "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-threads", "1", "-filter_threads", "1"] + [str(a) for a in args]


def burn_segment(src, work_dir, ass_name: str, dst, src_start: float, offset: float,
                 frames: Optional[int], length: float, w: int, h: int, fps) -> None:
    """Один кусок видео с субтитрами в кадре, без звука (звук кладётся
    один раз на склейке). `src_start` — секунда исходника, `offset` — та
    же точка в шкале результата (исходник минус начало обрезки)."""
    src, dst = Path(src).resolve(), Path(dst).resolve()      # ffmpeg идёт в work_dir
    lim = ["-frames:v", int(frames)] if frames else ["-t", "%.3f" % max(0.04, length)]
    args = (["-ss", "%.3f" % src_start] if src_start > 0 else []) + [
        "-i", src, "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", _burn_vf(ass_name, w, h, offset),
        "-r", "%d/%d" % (fps.numerator, fps.denominator), "-fps_mode", "cfr"] + lim + [
        "-c:v", "libx264", "-preset", BURN_PRESET, "-crf", BURN_CRF, "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-x264-params", "threads=%d:lookahead-threads=1" % BURN_THREADS,
        "-video_track_timescale", "90000", dst]
    seg_len = (frames / float(fps)) if frames else length
    run(_ffmpeg_burn(*args), timeout=max(600.0, seg_len * 30.0), cwd=work_dir)


def burn_concat(work_dir, seg_names: list, src, dst, trim_start: float, length: float) -> None:
    """Куски — копией потока (у них одни настройки и постоянная частота),
    звук исходника на отрезке обрезки — в aac. У видео без звука дорожки
    просто нет (`1:a:0?`)."""
    work_dir = Path(work_dir)
    src, dst = Path(src).resolve(), Path(dst).resolve()
    lst = work_dir / "segments.txt"
    lst.write_text("".join("file '%s'\n" % n for n in seg_names), encoding="utf-8")
    args = ["-f", "concat", "-safe", "0", "-i", lst.name] + (
        ["-ss", "%.3f" % trim_start] if trim_start > 0 else []) + [
        "-t", "%.3f" % length, "-i", src,
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-t", "%.3f" % length, "-movflags", "+faststart", dst]
    run(_ffmpeg(*args), timeout=max(900.0, length * 0.6), cwd=work_dir)


def preview_frame(src, work_dir, ass_name: str, src_t: float, offset: float,
                  w: int, h: int, max_side: int = 1280) -> bytes:
    """Один кадр с впечатанными субтитрами — ТЕМ ЖЕ фильтром, что сборка:
    человек подтверждает то, что получит, а не приближение браузера.
    Большой кадр уменьшается уже ПОСЛЕ субтитров: они нарисованы в размере
    результата, как будут в файле."""
    src = Path(src).resolve()
    k = min(1.0, max_side / float(max(w, h)))
    pw, ph = _even(w * k), _even(h * k)
    vf = _burn_vf(ass_name, w, h, offset) + (",scale=%d:%d:flags=bicubic" % (pw, ph) if k < 1.0 else "")
    args = (["-ss", "%.3f" % src_t] if src_t > 0 else []) + [
        "-i", src, "-map", "0:v:0", "-frames:v", 1, "-an", "-sn", "-dn", "-vf", vf,
        "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", 3, "pipe:1"]
    r = run(_ffmpeg_burn(*args), timeout=60, cwd=work_dir)
    if not r.stdout:
        raise MediaError("Кадр не получился — возможно, это место за концом видео")
    return r.stdout


def lang3(code: str) -> str:
    """Код языка для метаданных дорожки (ISO 639-2): плеер пишет «русский»,
    а не «дорожка 2». Неизвестный — пусто."""
    return {"ru": "rus", "en": "eng", "uz": "uzb", "kk": "kaz", "ky": "kir", "tg": "tgk", "tr": "tur",
            "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "zh": "zho", "ja": "jpn",
            "ko": "kor", "ar": "ara", "fa": "fas", "hi": "hin", "uk": "ukr", "pl": "pol",
            "az": "aze", "tk": "tuk"}.get((code or "").split("-")[0].lower(), "")


if __name__ == "__main__":             # pragma: no cover — ручная проверка на сервере
    print(json.dumps(probe(sys.argv[1]), ensure_ascii=False, indent=1))
