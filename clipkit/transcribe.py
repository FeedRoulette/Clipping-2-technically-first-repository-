"""Transcription (free, local, faster-whisper).
  python3 transcribe.py full  VIDEO OUT_DIR [--vocab "Names, Jargon"]
      -> OUT_DIR/transcript.txt (read this to pick moments) + OUT_DIR/full.json
  python3 transcribe.py range VIDEO NAME START END OUT_DIR [--vocab "..."]
      -> OUT_DIR/NAME.words.json  (high-accuracy word timings for one moment; used by the renderer)
"""
import argparse, json, os, subprocess, wave
import numpy as np
from faster_whisper import WhisperModel


def load(video, start=None, end=None):
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start), "-to", str(end)]
    cmd += ["-i", video, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["full", "range"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--vocab", default="")
    a = ap.parse_args()
    threads = os.cpu_count() or 4
    if a.mode == "full":
        video, out = a.args
        os.makedirs(out, exist_ok=True)
        m = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=threads)
        segs, _ = m.transcribe(load(video), language="en", word_timestamps=True, vad_filter=True,
                               condition_on_previous_text=False, initial_prompt=a.vocab or None)
        words, sents = [], []
        for s in segs:
            words += [{"w": x.word.strip(), "s": round(x.start, 2), "e": round(x.end, 2)} for x in s.words if x.word.strip()]
            sents.append({"s": round(s.start, 2), "e": round(s.end, 2), "text": s.text.strip()})
        json.dump({"words": words, "sents": sents}, open(f"{out}/full.json", "w"))
        with open(f"{out}/transcript.txt", "w") as f:
            for s in sents:
                f.write(f"[{int(s['s'] // 60)}:{int(s['s'] % 60):02d} {s['s']:.1f}-{s['e']:.1f}] {s['text']}\n")
        print("wrote", f"{out}/transcript.txt", len(sents), "lines")
    else:
        video, name, start, end, out = a.args
        start, end = float(start), float(end)
        os.makedirs(out, exist_ok=True)
        m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=threads)
        segs, _ = m.transcribe(load(video, start, end), language="en", word_timestamps=True, beam_size=5,
                               initial_prompt=a.vocab or None, condition_on_previous_text=False, vad_filter=False)
        words = [{"w": x.word.strip(), "s": round(start + x.start, 3), "e": round(start + x.end, 3)}
                 for s in segs for x in s.words if x.word.strip()]
        json.dump(words, open(f"{out}/{name}.words.json", "w"), indent=0)
        line = ""
        for w in words:                                   # print with timings for choosing exact cut points
            line += f"{w['w']}[{w['s']:.2f}] "
            if len(line) > 160:
                print(line); line = ""
        print(line)


if __name__ == "__main__":
    main()
