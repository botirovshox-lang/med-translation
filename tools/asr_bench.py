"""Замер локального распознавания речи (faster-whisper) против эталона.

Зачем: решить, можно ли распознавать звук видео на НАШЕМ сервере вместо
облака (инвариант 38). Вызовов платных моделей нет. Запускается в ОТДЕЛЬНОМ
окружении (/opt/asr-bench/venv), а не в боевом `.venv`: faster-whisper тянет
ctranslate2 и av, и проверять их соседство с sherpa-onnx/onnxruntime надо до
того, как они попадут в requirements.

    venv/bin/python asr_bench.py --audio a.mp3 --lang ru --model large-v3 \
        [--ref ref.txt] [--threads 2] [--prompt "…"] [--out result.json]

Что меряем и почему так:
  * CER/WER против эталона — эталон даёт человек (сверенный текст) либо
    прежняя платная расшифровка; во втором случае это РАСХОЖДЕНИЕ, а не
    ошибка: whisper-1 — такое же мнение, а не истина. Поле `ref_kind` пишет,
    что именно сравнивали;
  * время на минуту звука и пиковая память процесса (ru_maxrss) — на общем
    сервере с Камолой это цена решения, а не «бесплатно»;
  * сколько сегментов отбросил бы наш фильтр выдумок (`media._is_noise_segment`)
    — его пороги подобраны по whisper-1, и сдвиг здесь значит перемер;
  * доля сегментов с отметками слов — без них `build_cues` режет фразы
    по линейке, а не по речи.
Ответ выгружается в форме verbose_json OpenAI (segments + words), той же,
что кладёт в кэш `_asr_chunk` — её можно скормить `media.build_cues` как есть.
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))


def _norm_words(text: str) -> list:
    t = unicodedata.normalize("NFKC", text or "").lower().replace("ё", "е")
    t = re.sub(r"[ʻʼ‘’`']", "'", t)
    return re.findall(r"[\w']+", t)


def _lev(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def error_rates(hyp: str, ref: str) -> dict:
    hw, rw = _norm_words(hyp), _norm_words(ref)
    hc, rc = "".join(hw), "".join(rw)
    return {"wer": round(_lev(hw, rw) / max(1, len(rw)), 4),
            "cer": round(_lev(hc, rc) / max(1, len(rc)), 4),
            "ref_words": len(rw), "hyp_words": len(hw)}


def ref_from_srt(path: str) -> str:
    """Текст реплик .srt/.vtt без номеров и времени."""
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.isdigit() or "-->" in s or s.upper() == "WEBVTT":
            continue
        out.append(re.sub(r"<[^>]+>|\{[^}]*\}", "", s))
    return " ".join(out)


def load_audio(path: str):
    """Звук → float32 16 кГц моно системным ffmpeg. Через PyAV (по умолчанию у
    faster-whisper) нельзя: свежий av убрал параметр, на который тот рассчитан."""
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def transcribe(audio: str, lang: str, model_name: str, threads: int, prompt: str, compute: str,
               vad: bool = False, cond: bool = True) -> dict:
    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type=compute, cpu_threads=threads)
    t_load = time.time() - t0
    t1 = time.time()
    segs, info = model.transcribe(load_audio(audio), language=lang or None, initial_prompt=prompt or None,
                                  word_timestamps=True, vad_filter=vad, beam_size=5,
                                  condition_on_previous_text=cond)
    segments, words = [], []
    for s in segs:
        segments.append({"start": s.start, "end": s.end, "text": s.text,
                         "no_speech_prob": s.no_speech_prob, "avg_logprob": s.avg_logprob,
                         "compression_ratio": s.compression_ratio})
        for w in (s.words or []):
            words.append({"word": w.word, "start": w.start, "end": w.end})
    t_run = time.time() - t1
    return {"duration": info.duration, "language": info.language, "segments": segments,
            "words": words, "_load_s": round(t_load, 1), "_run_s": round(t_run, 1)}


def _peak_rss_mb():
    try:
        import resource         # только Unix; на Windows замера памяти нет
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except ImportError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--lang", default="")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--prompt", default="")
    ap.add_argument("--ref", default="", help="эталон: .txt или .srt/.vtt")
    ap.add_argument("--ref-kind", default="human", choices=["human", "whisper-1"])
    ap.add_argument("--out", default="")
    ap.add_argument("--vad", action="store_true", help="нарезка по речи (Silero VAD)")
    ap.add_argument("--no-cond", action="store_true", help="без опоры на предыдущий текст")
    a = ap.parse_args(argv)

    resp = transcribe(a.audio, a.lang, a.model, a.threads, a.prompt, a.compute, a.vad, not a.no_cond)
    try:
        import media
        noise = sum(1 for s in resp["segments"] if media._is_noise_segment(s))
    except Exception as e:      # бенч не должен падать из-за импорта
        noise = "n/a: %s" % e
    text = " ".join(s["text"].strip() for s in resp["segments"])
    dur = resp["duration"] or 1
    report = {
        "model": a.model, "vad": a.vad, "cond": not a.no_cond, "compute": a.compute, "threads": a.threads, "lang": a.lang,
        "audio_sec": round(dur, 1), "load_s": resp["_load_s"], "run_s": resp["_run_s"],
        "sec_per_audio_min": round(resp["_run_s"] / (dur / 60), 1),
        "peak_rss_mb": _peak_rss_mb(),
        "segments": len(resp["segments"]), "noise_dropped": noise,
        "words_with_time": len(resp["words"]),
    }
    if a.ref:
        ref = ref_from_srt(a.ref) if a.ref.endswith((".srt", ".vtt")) else Path(a.ref).read_text(encoding="utf-8")
        report.update(error_rates(text, ref), ref_kind=a.ref_kind)
    print(json.dumps(report, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps({"report": report, "response": resp, "text": text},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
