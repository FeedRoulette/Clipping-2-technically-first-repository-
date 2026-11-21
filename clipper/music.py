"""Background music: use your own royalty-free tracks from assets/music/<mood>/, or generate an
original, copyright-free bed on the fly (pads + bass + drums + arps). No downloads, no fees, no strikes."""
import random
import wave
from pathlib import Path

import numpy as np

from . import ASSETS

SR = 44100
MOODS = ["chill", "upbeat", "tense", "inspiring", "dark", "emotional", "hype"]


def _midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


# chord progressions as MIDI note lists (one chord per bar)
PROGS = {
    "chill":     [[48, 55, 59, 64], [45, 52, 55, 60], [50, 57, 60, 65], [43, 50, 53, 59]],      # Cmaj7 Am7 Dm7 G7
    "upbeat":    [[48, 55, 60, 64], [43, 50, 55, 59], [45, 52, 57, 60], [41, 48, 53, 57]],      # C G Am F
    "inspiring": [[41, 48, 53, 57], [43, 50, 55, 59], [45, 52, 57, 60], [48, 55, 60, 64]],      # F G Am C
    "tense":     [[45, 52, 57, 60], [45, 52, 57, 60], [41, 48, 53, 60], [44, 51, 56, 59]],      # Am Am F G#dim-ish
    "dark":      [[40, 47, 52, 55], [36, 43, 48, 52], [38, 45, 50, 53], [35, 42, 47, 50]],      # Em C Dm Bdim
    "emotional": [[45, 52, 57, 60], [41, 48, 53, 57], [48, 55, 60, 64], [43, 50, 55, 59]],      # Am F C G
    "hype":      [[42, 49, 54, 57], [42, 49, 54, 57], [38, 45, 50, 54], [40, 47, 52, 56]],      # F#m F#m D E
}
CFG = {
    #            bpm  drums     arp    pad   crackle
    "chill":     (82, "lofi",   False, 0.9, True),
    "upbeat":    (118, "pop",   True,  0.6, False),
    "inspiring": (100, "build", True,  0.8, False),
    "tense":     (95, "tense",  True,  0.7, False),
    "dark":      (78, "trap",   False, 0.8, False),
    "emotional": (72, "soft",   True,  1.0, False),
    "hype":      (140, "trap",  True,  0.5, False),
}


def _env(n, a, r):
    e = np.ones(n)
    a, r = min(a, n // 2), min(r, n // 2)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _pad(freq, n, bright=0.5, rng=None):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for det in (-0.07, 0.0, 0.07):          # detuned voices = width
        f = freq * 2 ** (det / 12)
        ph = rng.random() * 6.28
        for h in range(1, 7):                  # soft saw (additive, rolled off)
            out += (bright ** (h - 1)) / h * np.sin(2 * np.pi * f * h * t + ph * h)
    return out / 6


def _pluck(freq, n):
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t) + 0.1 * np.sin(6 * np.pi * freq * t)
    return x * np.exp(-t * 9)


def _kick(n):
    t = np.arange(n) / SR
    f = 45 + 85 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)


def _noise_hp(n, rng, cut=0.6):
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    k = np.linspace(0, 1, len(X))
    X *= np.clip((k - cut * 0.5) / (cut * 0.5 + 1e-9), 0, 1)
    return np.fft.irfft(X, n)


def _snare(n, rng):
    t = np.arange(n) / SR
    return (_noise_hp(n, rng, 0.15) * 0.8 + np.sin(2 * np.pi * 190 * t) * 0.5) * np.exp(-t * 18)


def _hat(n, rng):
    t = np.arange(n) / SR
    return _noise_hp(n, rng, 0.7) * np.exp(-t * 60)


DRUMS = {  # 16 steps per bar: K kick, S snare, H hat, O open hat
    "lofi":  ("K.....K...S.....", "..H...H...H...H.", 0.12),
    "pop":   ("K...K...K...K...", "..H...H...H...H.", 0.0),
    "build": ("K.......K.K.....", "H.H.H.H.H.H.H.H.", 0.0),
    "tense": ("K..K....K..K....", "HHHHHHHHHHHHHHHH", 0.0),
    "trap":  ("K......K..K.....", "H.H.HHH.H.H.HHHH", 0.0),
    "soft":  ("K.........K.....", "....H.......H...", 0.0),
}
SNARE = {"lofi": "....S.......S...", "pop": "....S.......S...", "build": "....S.......S...",
         "tense": "........S.......", "trap": "........S.......", "soft": "............S..."}


def generate(mood, seconds, out_path, seed=None):
    mood = mood if mood in PROGS else "chill"
    rng = np.random.default_rng(seed if seed is not None else random.randrange(1 << 30))
    bpm, drums, arp, padv, crackle = CFG[mood]
    transpose = int(rng.integers(-2, 3))
    beat = 60 / bpm
    bar_n = int(SR * beat * 4)
    bars = int(np.ceil(seconds * SR / bar_n)) + 1
    total = bars * bar_n
    L = np.zeros(total)
    R = np.zeros(total)
    prog = PROGS[mood]
    step_n = bar_n // 16
    kpat, hpat, swing = DRUMS[drums]
    spat = SNARE[drums]
    kick = _kick(int(SR * 0.45))
    snare = _snare(int(SR * 0.25), rng)
    hat = _hat(int(SR * 0.06), rng)
    for b in range(bars):
        chord = [n + transpose for n in prog[b % len(prog)]]
        o = b * bar_n
        intro = b < 1  # first bar: pads only (gentle entry)
        # pads
        pad = sum(_pad(_midi(n + 12), bar_n, 0.45, rng) for n in chord[1:]) * _env(bar_n, 4000, 6000)
        L[o:o + bar_n] += pad * 0.16 * padv
        R[o:o + bar_n] += np.roll(pad, 300) * 0.16 * padv
        # bass (root, two hits)
        for k, off in enumerate((0, 8)):
            bn = step_n * 8
            t = np.arange(bn) / SR
            f = _midi(chord[0] - 12 if chord[0] > 40 else chord[0])
            bass = (np.sin(2 * np.pi * f * t) + 0.2 * np.sin(4 * np.pi * f * t)) * _env(bn, 200, 3000)
            if not intro:
                L[o + off * step_n:o + off * step_n + bn] += bass * 0.28
                R[o + off * step_n:o + off * step_n + bn] += bass * 0.28
        if intro:
            continue
        for s in range(16):
            p = o + s * step_n + (int(step_n * swing) if s % 2 else 0)
            def add(x, g, pan=0.0):
                e = min(total, p + len(x))
                L[p:e] += x[:e - p] * g * (1 - pan)
                R[p:e] += x[:e - p] * g * (1 + pan)
            if kpat[s] == "K":
                add(kick, 0.55)
            if spat[s] == "S":
                add(snare, 0.22)
            if hpat[s] == "H":
                add(hat, 0.07 + 0.03 * (s % 4 == 0), 0.3)
            if arp and s % 2 == 0:
                notes = chord[1:] + [chord[1] + 12]
                n = notes[(s // 2) % len(notes)] + 24
                add(_pluck(_midi(n), step_n * 2), 0.07, -0.4 if s % 4 else 0.4)
    if crackle:
        c = (rng.random(total) > 0.9993) * rng.standard_normal(total) * 0.15
        L += c + rng.standard_normal(total) * 0.003
        R += c + rng.standard_normal(total) * 0.003
    n = int(seconds * SR)
    st = np.stack([L[:n], R[:n]], 1)
    # soft saturation + normalise to -1 dBFS
    st = np.tanh(st * 1.2)
    st /= np.abs(st).max() + 1e-9
    st *= 10 ** (-1 / 20)
    fade = int(SR * 1.5)
    st[-fade:] *= np.linspace(1, 0, fade)[:, None]
    _write(out_path, st)
    return out_path


def whoosh(out_path, dur=0.55, seed=0):
    """Transition swoosh for B-roll cuts (time-varying band-passed noise)."""
    rng = np.random.default_rng(seed)
    n = int(SR * dur)
    x = rng.standard_normal(n)
    frame, hop = 1024, 256
    out = np.zeros(n + frame)
    win = np.hanning(frame)
    freqs = np.fft.rfftfreq(frame, 1 / SR)
    for i, p in enumerate(range(0, n - frame, hop)):
        prog = p / n
        centre = 300 + 5000 * np.sin(np.pi * prog) ** 1.5
        mask = np.exp(-((np.log(freqs + 1) - np.log(centre)) ** 2) / 0.5)
        seg = np.fft.irfft(np.fft.rfft(x[p:p + frame] * win) * mask, frame)
        out[p:p + frame] += seg * np.sin(np.pi * prog) ** 2
    out = out[:n]
    out /= np.abs(out).max() + 1e-9
    out *= 0.7
    _write(out_path, np.stack([out, out], 1))
    return out_path


def _write(path, st):
    data = (np.clip(st, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def pick_track(mood, seconds, out_dir, seed=None):
    """Prefer a user-supplied track in assets/music/<mood>/ (or assets/music/), else generate."""
    lib = ASSETS / "music"
    exts = (".mp3", ".wav", ".m4a", ".ogg", ".flac")
    cands = [p for p in (lib / mood).glob("*") if p.suffix.lower() in exts] if (lib / mood).exists() else []
    if not cands:
        cands = [p for p in lib.glob("*") if p.suffix.lower() in exts]
    if cands:
        return random.Random(seed).choice(cands)
    return generate(mood, seconds + 1, Path(out_dir) / f"music_{mood}.wav", seed)
