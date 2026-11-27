"""Verbatim filler/stutter detector: Whisper normally drops 'um', 'uh', repeats. Priming it with a disfluent
prompt makes it write them out. usage: python3 -I fillercheck.py video_or_audio [start end]"""
import sys, subprocess, re, numpy as np
from faster_whisper import WhisperModel
PROMPT = "Umm, so, uh, I mean, like, you know, I- I think, uh, we we just, hmm, yeah, um, okay."
FILL = {"um", "umm", "uh", "uhh", "uhm", "ah", "ahh", "er", "erm", "hmm", "mm"}
def check(path, ss=None, to=None, m=None):
    m = m or WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=4)
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(ss), "-to", str(to)] if ss is not None else []) + ["-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    a = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.int16).astype(np.float32) / 32768
    segs, _ = m.transcribe(a, language="en", beam_size=5, word_timestamps=True, initial_prompt=PROMPT,
                           condition_on_previous_text=False, vad_filter=False, suppress_tokens=[])
    ws = [(w.start, re.sub(r"[^a-z']", "", w.word.lower())) for s in segs for w in s.words]
    ws = [(t, x) for t, x in ws if x]
    hits = [(round(t, 1), x) for t, x in ws if x in FILL]
    hits += [(round(ws[i][0], 1), "you know") for i in range(len(ws) - 1) if ws[i][1] == "you" and ws[i + 1][1] == "know"]
    hits += [(round(ws[i][0], 1), f"repeat '{ws[i][1]}'") for i in range(len(ws) - 1)
             if ws[i][1] == ws[i + 1][1] and ws[i][1] not in ("that", "had", "very", "so")]
    print("  verbatim:", " ".join(x for _, x in ws))
    print("  FILLERS/STUTTERS:", sorted(hits) or "none")
    return hits
if __name__ == "__main__":
    a = sys.argv[1:]
    check(a[0], *(a[1:3] if len(a) > 2 else []))
