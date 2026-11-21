"""Step 2: word-level transcription with faster-whisper (free, local, CPU)."""
import os
import wave
from pathlib import Path

import numpy as np

from .util import log, run, write_json, ts

_MODELS = {}


def _model(name):
    if name not in _MODELS:
        from faster_whisper import WhisperModel
        log(f"loading whisper model '{name}' (first time downloads it, free)")
        _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                     cpu_threads=os.cpu_count() or 4)
    return _MODELS[name]


def extract_wav(src, out, start=None, end=None):
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}", "-to", f"{end:.3f}"]
    cmd += ["-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out]
    run(cmd)
    return out


def load_wav(path):
    with wave.open(str(path)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return a, w.getframerate()


def whisper_words(wav, model="small", language=None, prompt=None):
    m = _model(model)
    audio, _ = load_wav(wav)
    segs, info = m.transcribe(audio, word_timestamps=True, vad_filter=True,
                              vad_parameters={"min_silence_duration_ms": 400},
                              language=language, initial_prompt=prompt,
                              condition_on_previous_text=False, beam_size=5)
    words, segments = [], []
    for s in segs:
        sw = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
               "p": round(w.probability, 3)} for w in (s.words or []) if w.word.strip()]
        words += sw
        segments.append({"s": round(s.start, 3), "e": round(s.end, 3), "text": s.text.strip()})
    return words, segments, info.language


def transcribe(wd, model="small", language=None):
    wd = Path(wd)
    out = wd / "transcript.json"
    if out.exists():
        log("transcript exists:", out)
        return out
    wav = extract_wav(wd / "source.mp4", wd / "audio16k.wav")
    log(f"transcribing with '{model}' ... (≈0.1-0.3x realtime on CPU)")
    words, segments, lang = whisper_words(wav, model, language)
    audio, sr = load_wav(wav)
    # loudness per segment -> helps spot heated / funny / emotional moments
    rms = []
    for s in segments:
        a = audio[int(s["s"] * sr):int(s["e"] * sr)]
        rms.append(float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0)
    if rms:
        arr = np.array(rms)
        mu, sd = arr.mean(), arr.std() + 1e-9
        for s, r in zip(segments, rms):
            s["energy"] = round(float((r - mu) / sd), 2)
            dur = max(0.1, s["e"] - s["s"])
            s["wps"] = round(len(s["text"].split()) / dur, 2)
    write_json(out, {"language": lang, "model": model, "words": words, "segments": segments})
    write_readable(wd, segments)
    log("transcript:", out)
    return out


def write_readable(wd, segments):
    """transcript.txt: what Claude reads to pick moments. '!' = louder than usual, '>>' = fast talk."""
    lines = []
    for s in segments:
        flag = ""
        if s.get("energy", 0) > 1.2:
            flag += "!"
        if s.get("wps", 0) > 4.3:
            flag += ">>"
        lines.append(f"[{ts(s['s'])} {s['s']:.1f}-{s['e']:.1f}]{(' ' + flag) if flag else ''} {s['text']}")
    (Path(wd) / "transcript.txt").write_text("\n".join(lines))


def caption_words(src, start, end, model, language=None):
    """High-accuracy re-transcription of just one clip for captions (times relative to `start`)."""
    tmp = Path(src).parent / f"_cap_{start:.0f}.wav"
    extract_wav(src, tmp, start, end)
    words, _, _ = whisper_words(tmp, model, language)
    tmp.unlink(missing_ok=True)
    return words
