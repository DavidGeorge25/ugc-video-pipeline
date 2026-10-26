#!/usr/bin/env bash
# One-time setup in a fresh session (~2 min). Models come from GitHub releases (allowed by the sandbox).
set -e
cd "$(dirname "$0")"
pip install --break-system-packages -q sherpa-onnx onnxruntime num2words rapidfuzz opencv-python-headless pillow playwright fonttools brotli
mkdir -p models
[ -f models/rvm.onnx ] || curl -sSL -o models/rvm.onnx https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3_fp32.onnx
if [ ! -d models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 ]; then
  curl -sSL https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2 | tar xj -C models
fi
mkdir -p models/rnnoise
[ -f models/rnnoise/std.rnnn ] || curl -sSL -o models/rnnoise/std.rnnn https://raw.githubusercontent.com/richardpl/arnndn-models/master/std.rnnn
python3 -c "import asr, cut, compose, matte, sankey, make, review; print('pipeline ready')"
