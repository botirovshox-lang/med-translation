"""Своё распознавание речи (GigaAM Multilingual CTC, MIT) — отдельным процессом.

    python asr_local_worker.py МОДЕЛЬ ПОТОКИ ЗАДАНИЕ.json

ЗАДАНИЕ — список {"in": кусок звука, "out": куда положить ответ}. Ответ — тот же
вид, что кэш облачного распознавания (`_asr_chunk`): duration, language,
segments [{start, end, text, …}], words [{word, start, end}] — его читает
`media.build_cues` как есть. Готовый ответ второй раз не считается.

Почему отдельный процесс (как `separate_worker.py`): модель — torch и 1,6 ГБ
памяти, её место не в процессе воркера; вызов нейросети не отменить посреди,
а снятый процесс (стоп, выкат) ничего не портит — ответы пишутся по одному
файлу через tmp + replace. Окружение СВОЁ (`ASR_LOCAL_PYTHON`): torch
и transformers не попадают в боевой .venv.

Модель та же, что у «Звонков AI» Камолы (исходная, не дообученная на звонках
клиента — та остаётся у Камолы). Путь тот же, что у её боевого распознавания:
паузы ищет silero, речь режется на куски до PIECE_S, у каждого слова — время
(кадры CTC). Замер 18.10.2026: FLEURS uz — 3,9% ошибок по буквам при 13 с
процессора на минуту звука (облако узбекский не принимает вовсе).
"""
import json
import os
import subprocess
import sys
import types

SR = 16000
PIECE_S = 10.0          # как у «Звонков»: на этом и мерили
PIECE_MIN_S = 7.0       # режем в самом тихом месте между 7 и 10 с, а не посреди слова
MIN_PIECE_S = 0.3
INT8_FILE = "model_int8.pt"


def _die_with_parent() -> None:
    """ffmpeg умирает вместе с нами: стоп и выкат снимают процесс модели,
    и ffmpeg-внук не должен доживать сиротой (Linux, PR_SET_PDEATHSIG)."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)
    except Exception:
        pass


def decode(path: str):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-map", "0:a:0", "-vn",
                          "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True,
                         preexec_fn=_die_with_parent if os.name == "posix" else None).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def load_model(model_dir: str, threads: int):
    import torch
    from transformers import AutoConfig, AutoModel
    torch.set_num_threads(max(1, threads))
    # Код модели при импорте спрашивает pyannote (нужен только её нарезке длинных
    # файлов, режем мы сами) — пустой модуль вместо 200 МБ.
    for name in ("pyannote", "pyannote.audio"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["pyannote.audio"].Pipeline = object
    int8 = os.path.join(model_dir, INT8_FILE)
    if os.path.isfile(int8):
        AutoConfig.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
        m = torch.load(int8, weights_only=False)        # наш файл (make_int8 «Звонков»)
    else:
        m = AutoModel.from_pretrained(model_dir, trust_remote_code=True, local_files_only=True)
    m.eval()
    mods = [v for k, v in sys.modules.items() if k.endswith("modeling_gigaam")]
    if not mods:
        raise RuntimeError("код GigaAM не найден")
    for mod in mods:                    # модель читает файлы — учим брать массив
        orig = mod.load_audio
        mod.load_audio = (lambda o: lambda x, *a, **k: (
            o(x, *a, **k) if isinstance(x, str) else torch.from_numpy(x).float()))(orig)
    return m


_VAD = []


def speech_spans(audio) -> list:
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    if not _VAD:
        _VAD.append(load_silero_vad(onnx=True))
    ts = get_speech_timestamps(torch.from_numpy(audio), _VAD[0], sampling_rate=SR,
                               min_silence_duration_ms=300, speech_pad_ms=100)
    return [(t["start"] / SR, t["end"] / SR) for t in ts]


def pieces(audio, s: float, e: float) -> list:
    """Отрезок речи → куски до PIECE_S; граница — самая тихая точка окна
    [PIECE_MIN_S, PIECE_S] от начала куска (20-мс кадры), чтобы не резать слово."""
    import numpy as np
    out, t = [], s
    while e - t > PIECE_S:
        lo, hi = int((t + PIECE_MIN_S) * SR), int((t + PIECE_S) * SR)
        win = audio[lo:hi]
        hop = int(0.02 * SR)
        n = max(1, len(win) // hop)
        rms = [float(np.sqrt(np.mean(win[i * hop:(i + 1) * hop] ** 2) + 1e-12)) for i in range(n)]
        cut = (lo + int(np.argmin(rms)) * hop + hop // 2) / SR
        out.append((t, cut))
        t = cut
    out.append((t, e))
    return out


def transcribe_file(model, path: str) -> dict:
    audio = decode(path)
    dur = len(audio) / SR
    segments, words = [], []
    for s, e in speech_spans(audio) if len(audio) else []:
        for ps, pe in pieces(audio, s, e):
            piece = audio[int(ps * SR):int(pe * SR)]
            if len(piece) < int(MIN_PIECE_S * SR):
                continue
            try:
                r = model.transcribe(piece, word_timestamps=True)
            except Exception as e:              # один кусок не роняет весь файл
                sys.stderr.write("кусок %.1f–%.1f не распознан: %s\n" % (ps, pe, e))
                continue
            text = str(getattr(r, "text", r) or "").strip()
            if not text:
                continue
            segments.append({"start": round(ps, 3), "end": round(pe, 3), "text": text,
                             "no_speech_prob": 0.0, "avg_logprob": 0.0, "compression_ratio": 1.0})
            for w in (getattr(r, "words", None) or []):
                words.append({"word": w.text, "start": round(ps + float(w.start), 3),
                              "end": round(ps + float(w.end), 3)})
    return {"duration": dur, "language": None, "segments": segments, "words": words}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 3:
        sys.stderr.write("usage: asr_local_worker.py MODEL THREADS JOB.json\n")
        return 2
    model_dir, threads, job = argv[0], int(argv[1]), argv[2]
    items = [x for x in json.load(open(job, encoding="utf-8")) if not os.path.exists(x["out"])]
    if not items:
        return 0
    model = load_model(model_dir, threads)
    for x in items:
        res = transcribe_file(model, x["in"])
        tmp = x["out"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False)
        os.replace(tmp, x["out"])
        sys.stdout.write("OK %s\n" % x["out"])
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
