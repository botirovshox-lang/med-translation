#!/bin/sh
# Модели голосового контура — в backend/data/models/ (данные, не git).
#   sh tools/install_voice_models.sh            # Spleeter 2 stems (MIT), по умолчанию
#   sh tools/install_voice_models.sh uvr9482    # UVR MDX-Net 9482 — лицензия весов
#                                               # НЕ объявлена: только по решению владельца
# Скачанное сверяется с sha256: подменённая модель — это чужой код на сервере.
set -eu
cd "$(dirname "$0")/../backend"
mkdir -p data/models
cd data/models
B=https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models
case "${1:-spleeter}" in
  spleeter)
    f=sherpa-onnx-spleeter-2stems-fp16.tar.bz2
    sum=d54561979bd2e08a51e7dbd99ac36bb47564e089eefd403636dbca93e811bba2
    curl -fsSL -o "$f.part" "$B/$f"
    echo "$sum  $f.part" | sha256sum -c -
    tar xjf "$f.part" && rm -f "$f.part"
    ls -la sherpa-onnx-spleeter-2stems-fp16
    ;;
  uvr9482)
    f=UVR_MDXNET_9482.onnx
    sum=9d78f8566fa8198065214ab628be1de966a500c57786695aa4b13e2b27a7727d
    curl -fsSL -o "$f.part" "$B/$f"
    echo "$sum  $f.part" | sha256sum -c -
    mv "$f.part" "$f"
    echo "Включить: MEDIA_SEP_MODEL=$(pwd)/$f в /etc/medcat/env"
    ;;
  *) echo "неизвестная модель: $1" >&2; exit 2 ;;
esac
