#!/bin/sh
# Модели стирания надписей на неровном фоне — в backend/data/models/ (данные, не git).
#   sh tools/install_paint_models.sh          # LaMa (big-lama, Apache-2.0), ONNX 512×512
#   sh tools/install_paint_models.sh migan    # MI-GAN (MIT, веса MIT), ONNX-конвейер
# Скачанное сверяется с sha256: подменённая модель — это чужой код на сервере.
# Нет модели — стирание идёт прежним способом (cv2.inpaint), отказа нет.
set -eu
cd "$(dirname "$0")/../backend"
mkdir -p data/models
cd data/models
get() {  # url файл sha256
  curl -fsSL -o "$2.part" "$1"
  echo "$3  $2.part" | sha256sum -c -
  mv "$2.part" "$2"
  ls -la "$2"
}
case "${1:-lama}" in
  lama)
    get https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx lama_fp32.onnx \
        1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6
    ;;
  migan)
    get https://huggingface.co/andraniksargsyan/migan/resolve/main/migan_pipeline_v2.onnx migan_pipeline_v2.onnx \
        6f1f3530a1a2324b19752018ce756088b07973cda8d7d890034ace5c8a48c40b
    ;;
  *) echo "неизвестная модель: $1" >&2; exit 2 ;;
esac
