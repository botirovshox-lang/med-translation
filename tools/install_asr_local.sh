#!/bin/sh
# Своё распознавание речи (инвариант 38): окружение .venv-asr и модель
# GigaAM Multilingual Large CTC (MIT) в backend/data/models/gigaam-large_ctc.
#   sudo sh tools/install_asr_local.sh [КАТАЛОГ_МОДЕЛИ_ИСТОЧНИКА]
# Модель — та же, что у «Звонков AI» Камолы, ИСХОДНАЯ (не дообученная на
# звонках клиента), копируется с её каталога и сверяется с sha256: файл
# model_int8.pt распаковывается pickle'ом, то есть подменённый файл — это
# чужой код на сервере. Версии пакетов — те же, что у «Звонков»: int8-файл
# собран ими, и другая версия transformers/torch его не распакует.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-/var/lib/kamola/calls_ai_models/gigaam-large_ctc}"
DST="$ROOT/backend/data/models/gigaam-large_ctc"
VENV="$ROOT/.venv-asr"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 torchaudio==2.11.0
"$VENV/bin/pip" install -q transformers==5.17.0 hydra-core==1.3.7 omegaconf==2.3.1 sentencepiece==0.2.2 \
  silero-vad==6.2.3 onnxruntime==1.30.0 soundfile==0.14.0 numpy==2.5.3 huggingface_hub==1.33.0
mkdir -p "$DST"
for f in config.json modeling_gigaam.py model_int8.pt README.md REVISION; do
  cp "$SRC/$f" "$DST/$f.part"
done
cd "$DST"
cat > SHA256SUMS.part <<'SUMS'
5ea1089c77b60e094352d7fb7bfb6580906b380c4dc7053edb4f7f0a1f59c172  config.json.part
6d02e640fbb5738ab11c030520a68654ef32f4ff363723db10534cf8b5d5c0e7  modeling_gigaam.py.part
4a6d7aacc1513125e443e3254e61dfbc89a70e0ad8f136c52c58396908624479  model_int8.pt.part
097997908f232ec01f47f5155a462ad0b5aa9f1383594827903f46290e6b57bc  README.md.part
4d050213e2287478e3058b25d71655666b3dcb112fe451a1100b4ab7c6bbb91b  REVISION.part
SUMS
sha256sum -c SHA256SUMS.part
for f in config.json modeling_gigaam.py model_int8.pt README.md REVISION; do mv -f "$f.part" "$f"; done
rm -f SHA256SUMS.part
id medcat >/dev/null 2>&1 && chown -R medcat:medcat "$ROOT/backend/data/models/gigaam-large_ctc" || true
echo "Готово: $DST, окружение $VENV. Перезапустить medcat-worker."
