"""Своё распознавание речи (asr_local_worker.py) и письмо его ответа.

Модель подменена: проверяется НАШ код — нарезка речи в тихом месте, сдвиг
времени слов на начало куска, формат ответа (тот же, что кэш облака),
повтор не считает готовое, узбекская латиница и кириллица ответа.
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np

import asr_local_worker as W
import tts_engines

fail = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        fail.append(label)


print("=== 1. Нарезка: куски до 10 с, граница — в тихом месте ===")
sr = W.SR
audio = np.full(sr * 25, 0.3, np.float32)
audio[int(8.5 * sr):int(8.6 * sr)] = 0.0              # тишина на 8,5 с — там и резать
audio[int(17.2 * sr):int(17.3 * sr)] = 0.0
cuts = W.pieces(audio, 0.0, 25.0)
check(all(e - s <= W.PIECE_S + 1e-6 for s, e in cuts), "ни один кусок не длиннее 10 с: %s" % cuts)
check(abs(cuts[0][1] - 8.55) < 0.05 and abs(cuts[1][1] - 17.25) < 0.05, "резы в тишине: %s" % cuts)
check(cuts[0][0] == 0.0 and cuts[-1][1] == 25.0 and all(a[1] == b[0] for a, b in zip(cuts, cuts[1:])),
      "куски покрывают отрезок без дыр и нахлёстов")
check(W.pieces(audio, 2.0, 6.0) == [(2.0, 6.0)], "короткий отрезок — одним куском")

print("=== 2. Ответ: вид кэша облака, время слов от начала куска ===")


class FakeModel:
    def __init__(self):
        self.calls = 0

    def transcribe(self, piece, word_timestamps=False):
        self.calls += 1
        w = types.SimpleNamespace(text="salom", start=0.2, end=0.6)
        return types.SimpleNamespace(text=" salom dunyo ", words=[w])


W.decode = lambda path: np.full(sr * 14, 0.3, np.float32)
W.speech_spans = lambda a: [(1.0, 13.0)]
m = FakeModel()
res = W.transcribe_file(m, "x.mp3")
check(res["duration"] == 14.0 and len(res["segments"]) == 2 and m.calls == 2, "отрезок 12 с — два куска")
seg = res["segments"][0]
check(seg["text"] == "salom dunyo" and seg["start"] == 1.0 and {"no_speech_prob", "avg_logprob",
      "compression_ratio"} <= set(seg), "сегмент — в виде ответа облака")
check(res["words"][0] == {"word": "salom", "start": 1.2, "end": 1.6}, "время слова — от начала ролика")
check(res["words"][1]["start"] == round(res["segments"][1]["start"] + 0.2, 3), "второй кусок — свой сдвиг")

print("=== 3. Запуск: готовое не считается заново ===")
tmp = Path(tempfile.mkdtemp())
done = tmp / "a.json"
done.write_text("{}", encoding="utf-8")
job = tmp / "job.json"
job.write_text(json.dumps([{"in": "a.mp3", "out": str(done)}]), encoding="utf-8")
W.load_model = lambda d, t: (_ for _ in ()).throw(AssertionError("модель грузить незачем"))
check(W.main(["m", "2", str(job)]) == 0, "всё готово — модель не грузится")
job.write_text(json.dumps([{"in": "b.mp3", "out": str(tmp / "b.json")}]), encoding="utf-8")
W.load_model = lambda d, t: FakeModel()
check(W.main(["m", "2", str(job)]) == 0 and json.loads((tmp / "b.json").read_text())["segments"],
      "новый кусок — ответ файлом")
check(not list(tmp.glob("*.tmp")), "без недописанных файлов")

print("=== 4. Письмо ответа ===")
check(tts_engines.uz_lat_apostrophes("bor yo'g'i ta'lim") == "bor yoʻgʻi taʼlim", "oʻ/gʻ и ʼ — буквами языка")
check(tts_engines.uz_lat_to_cyr("bor yo'g'i o'n sakkizta medal") == "бор йўғи ўн саккизта медал",
      "латиница → кириллица: йўғи, ўн")
check(tts_engines.uz_lat_to_cyr("ekin yer shahar choy ta'lim") == "экин ер шаҳар чой таълим",
      "э в начале слова, ер, ш, ч, ъ")
check(tts_engines.uz_lat_to_cyr("Toshkent SHAHAR 2024") == "Тошкент ШАҲАР 2024", "регистр и цифры")
check(tts_engines.uz_cyr_to_lat(tts_engines.uz_lat_to_cyr("salomatlik shubha ostida")) == "salomatlik shubha ostida",
      "туда и обратно — то же")

print("\nПРОВАЛЕНО: %d" % len(fail) if fail else "\nВСЁ ПРОШЛО")
sys.exit(1 if fail else 0)
