"""Fast check of an edit before rendering: cut ONLY the audio of the given pieces, transcribe it with word times,
print words + any dead air. usage: python3 -I audition.py SRC '[[a,b],[c,d]]'"""
import json, subprocess, sys
import numpy as np
from faster_whisper import WhisperModel
src, edl = sys.argv[1], json.loads(sys.argv[2])
parts = []
for a, b in edl:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", src, "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    parts.append(np.frombuffer(raw, np.int16).astype(np.float32) / 32768)
x = np.concatenate(parts)
m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=4)
segs, _ = m.transcribe(x, language="en", word_timestamps=True, condition_on_previous_text=False, initial_prompt="Umm, so, uh, I mean, like, you know, I- I think, uh, we we just, hmm, yeah, um, okay.", suppress_tokens=[])
ws = [w for s in segs for w in s.words]
print(" ".join(f"{w.word.strip()}@{w.start:.2f}" for w in ws))
gaps = [(round(p.end, 2), round(q.start, 2)) for p, q in zip(ws, ws[1:]) if q.start - p.end > 0.6]
print("dead air:", gaps or "none", " total", round(len(x) / 16000, 1), "s")
