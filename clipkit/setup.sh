#!/usr/bin/env bash
# One-time setup. Everything is free. Needs python3 + ffmpeg (+ internet).
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "install ffmpeg first (apt-get install -y ffmpeg / brew install ffmpeg)"; exit 1; }
pip uninstall -y -q opencv-python opencv-python-headless opencv-contrib-python-headless 2>/dev/null || true
pip install -q "opencv-contrib-python-headless==4.10.0.84" faster-whisper numpy Pillow gdown
python3 -c "from faster_whisper import WhisperModel as W; [W(m, device='cpu', compute_type='int8') for m in ('small','large-v3-turbo')]"
python3 fetch_assets.py
echo "clipkit ready"
