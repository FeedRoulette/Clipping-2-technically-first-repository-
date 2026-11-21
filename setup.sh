#!/usr/bin/env bash
# One-time setup (free). Needs: python3.10+, ffmpeg, node (for YouTube's JS challenge).
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Install ffmpeg first (apt install ffmpeg / brew install ffmpeg)"; exit 1; }
python3 -m pip install -q -r requirements.txt
# pre-download the two speech models (free, from Hugging Face)
python3 -c "from faster_whisper import WhisperModel as W; [W(m, device='cpu', compute_type='int8') for m in ('small','large-v3-turbo')]"
echo "Ready. Try: python3 -m clipper prep 'https://www.youtube.com/watch?v=...'"
