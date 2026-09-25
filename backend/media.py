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
  * впечатанных (burn-in) субтитров нет намеренно: это полное перекодирование
    видео — часы CPU на двухгигабайтном файле. Субтитры кладутся дорожкой
    в контейнер (плееры и YouTube их показывают) и отдаются файлом .srt/.vtt.

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


def run(cmd: list, timeout: float, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    """Запуск со всеми предохранителями; stdout — байты, stderr — байты."""
    import time as _time
    try:
        proc = subprocess.Popen(_polite(cmd), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
            if ABORT() or _time.time() > deadline:
                proc.kill()
                proc.communicate()
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
           "width,height,channels,sample_rate:stream_disposition=attached_pic",
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


# ─── Звук для распознавания ──────────────────────────────────────────

def extract_audio(src, dst, duration: float, limit_sec: Optional[float] = None) -> None:
    """Первая звуковая дорожка → моно 16 кГц mp3. Видео не декодируется
    (`-vn`), поэтому время зависит от длины ролика, а не от разрешения."""
    args = ["-i", src, "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", 1, "-ar", ASR_RATE,
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


def build_cues(segments: list, words: list, offset: float = 0.0,
               max_sec: float = CUE_MAX_SEC, max_chars: int = CUE_MAX_CHARS) -> list:
    """Фразы распознавания → реплики субтитров [{start, end, text}]. Фраза
    длиннее `max_sec`/`max_chars` делится по препинанию, а время кусков
    берётся из отметок СЛОВ этой фразы. Смещение куска звука прибавляется."""
    cues = []
    for seg in segments or []:
        if _is_noise_segment(seg):
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


def mux_subtitles(src, srt, dst, info: dict, lang: str = "") -> None:
    """Видео + дорожка субтитров, ВСЁ копией потока. В mp4 субтитры —
    mov_text (текст), в mkv — srt. Оригинальный звук не трогается."""
    ext = Path(dst).suffix.lower()
    scodec = "mov_text" if ext == ".mp4" else "srt"
    # Звук, который mp4 не держит (pcm из .mov, vorbis из .mkv), —
    # в aac; перекодировать звук дёшево, видео не трогается никогда.
    acodec = "copy"
    if ext == ".mp4" and (info.get("audio") or {}).get("codec") not in MP4_ACODECS:
        acodec = "aac"
    args = ["-i", src, "-i", srt, "-map", "0:v:0", "-map", "0:a?", "-map", "1:0",
            "-c:v", "copy", "-c:a", acodec, "-c:s", scodec] + _vtag(info, ext)
    if lang:
        args += ["-metadata:s:s:0", "language=" + lang]
    if ext == ".mp4":
        args += ["-movflags", "+faststart"]
    run(_ffmpeg(*(args + [dst])), timeout=max(600.0, (info.get("duration") or 0) * 0.5))


def mux_dub(src, track_path, dst, info: dict, duck: float = 0.2, lang: str = "") -> None:
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
    args = ["-i", src, "-f", "s16le", "-ar", TTS_RATE, "-ac", 1, "-i", track_path,
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


def lang3(code: str) -> str:
    """Код языка для метаданных дорожки (ISO 639-2): плеер пишет «русский»,
    а не «дорожка 2». Неизвестный — пусто."""
    return {"ru": "rus", "en": "eng", "uz": "uzb", "kk": "kaz", "ky": "kir", "tg": "tgk", "tr": "tur",
            "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pt": "por", "zh": "zho", "ja": "jpn",
            "ko": "kor", "ar": "ara", "fa": "fas", "hi": "hin", "uk": "ukr", "pl": "pol",
            "az": "aze", "tk": "tuk"}.get((code or "").split("-")[0].lower(), "")


if __name__ == "__main__":             # pragma: no cover — ручная проверка на сервере
    print(json.dumps(probe(sys.argv[1]), ensure_ascii=False, indent=1))
