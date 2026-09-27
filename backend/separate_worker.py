"""Отделить голоса от фона в одном куске звука — отдельным процессом.

    python separate_worker.py МОДЕЛЬ ПОТОКИ ВХОД.raw ВЫХОД.raw

Вход и выход — s16le 44,1 кГц стерео; на выходе — ФОН (всё, кроме голосов)
той же длины. Модель — каталог Spleeter (vocals.fp16.onnx +
accompaniment.fp16.onnx) или файл UVR MDX-Net (.onnx с метаданными
sherpa-onnx).

Почему процесс, а не вызов внутри воркера (`media.separate_chunk`):
вызов нейросети на минуту звука не отменить посреди, а процесс `media.run`
убивает по кнопке «Отменить» и на выкате; у sherpa-onnx своя копия
onnxruntime рядом с той, что у распознавания картинок; нативное падение
уносит только этот процесс, а не сервис; память возвращается системе сразу.
"""
import os
import sys
from pathlib import Path

RATE = 44100


def main(argv) -> int:
    if len(argv) != 5:
        sys.stderr.write("usage: separate_worker.py MODEL THREADS IN OUT\n")
        return 2
    import numpy as np
    import sherpa_onnx as so
    model, threads, src, dst = Path(argv[1]), max(1, int(argv[2])), Path(argv[3]), Path(argv[4])
    if model.is_dir():
        mc = so.OfflineSourceSeparationModelConfig(
            spleeter=so.OfflineSourceSeparationSpleeterModelConfig(
                vocals=str(model / "vocals.fp16.onnx"), accompaniment=str(model / "accompaniment.fp16.onnx")),
            num_threads=threads, provider="cpu")
        k = 1                           # Spleeter: [голоса, сопровождение]
    else:
        mc = so.OfflineSourceSeparationModelConfig(
            uvr=so.OfflineSourceSeparationUvrModelConfig(model=str(model)),
            num_threads=threads, provider="cpu")
        # Первая стема — та, на которую модель учили: у «голосовых» (9482,
        # Voc_FT) это голоса, у «инструментальных» (Inst_*) — фон. Перепутай —
        # и в фон уходит сама речь (замер: у Inst_HQ_4 — на 96%).
        k = 0 if "inst" in model.stem.lower() else 1
        if os.environ.get("MEDIA_SEP_BG_STEM", "").strip() in ("0", "1"):
            # Своя модель с иным порядком стем — номер фона задаёт установщик.
            k = int(os.environ["MEDIA_SEP_BG_STEM"])
    sep = so.OfflineSourceSeparation(so.OfflineSourceSeparationConfig(model=mc))
    x = np.frombuffer(src.read_bytes(), dtype="<i2").reshape(-1, 2).T.astype(np.float32) / 32768.0
    n = x.shape[1]
    if n == 0:
        dst.write_bytes(b"")
        return 0
    out = sep.process(sample_rate=RATE, samples=np.ascontiguousarray(x))
    bg = np.asarray(out.stems[k].data, dtype=np.float32).reshape(2, -1)
    if bg.shape[1] < n:
        bg = np.pad(bg, ((0, 0), (0, n - bg.shape[1])))
    bg = bg[:, :n]
    tmp = dst.with_name(dst.name + ".part")
    tmp.write_bytes((np.clip(bg, -1.0, 1.0) * 32767.0).astype("<i2").T.tobytes())
    tmp.replace(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
