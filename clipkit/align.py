"""Precise word boundaries with torchaudio's MMS forced aligner (wav2vec2 CTC).
Whisper gives the words; the aligner pins each word's true start/end in the audio (~20 ms accuracy).
usage: python3 align.py SRC words.json OUT.json"""
import json, re, subprocess, sys
import numpy as np
import torch, torchaudio
from num2words import num2words

SR = 16000
_bundle = torchaudio.pipelines.MMS_FA
_model = None


def _load():
    global _model
    if _model is None:
        torch.set_num_threads(4)
        _model = _bundle.get_model(with_star=False).eval()
    return _model


def spoken(w):
    t = w.lower().replace("%", " percent").replace("$", "")
    t = re.sub(r"(\d+)\.(\d+)", lambda m: num2words(int(m.group(1))) + " point " + " ".join(num2words(int(c)) for c in m.group(2)), t)
    t = re.sub(r"(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), to="ordinal"), t)
    t = re.sub(r"\d[\d,]*", lambda m: num2words(int(m.group(0).replace(",", ""))), t)
    t = t.replace("-", " ").replace("x", "x")
    t = re.sub(r"[^a-z' ]", "", t)
    return [p for p in t.split() if p.strip("'")]


def align(src, words, pad=0.6):
    words = sorted(words, key=lambda w: w["s"])
    a0 = max(0.0, words[0]["s"] - pad)
    a1 = words[-1]["e"] + pad
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a0:.3f}", "-to", f"{a1:.3f}", "-i", src, "-ac", "1",
                          "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    wav = torch.from_numpy(np.frombuffer(raw, np.float32).copy()).unsqueeze(0)
    toks, owner = [], []
    dic = _bundle.get_dict(star=None)
    for i, w in enumerate(words):
        for part in spoken(w["w"]):
            ids = [dic[c] for c in part if c in dic]
            if ids:
                toks.append(ids); owner.append(i)
    model = _load()
    with torch.inference_mode():
        emission, _ = model(wav)
    aligner = _bundle.get_aligner()
    spans = aligner(emission[0], toks)
    ratio = wav.shape[1] / emission.shape[1] / SR
    out = [dict(w, s_ws=w["s"], e_ws=w["e"]) for w in words]
    got = {}
    for sp, i in zip(spans, owner):
        s = a0 + sp[0].start * ratio
        e = a0 + sp[-1].end * ratio
        if i in got:
            got[i] = (min(got[i][0], s), max(got[i][1], e))
        else:
            got[i] = (s, e)
    for i, (s, e) in got.items():
        out[i]["s"], out[i]["e"] = round(s, 3), round(e, 3)
    return out


if __name__ == "__main__":
    src, inp, outp = sys.argv[1:4]
    W = json.load(open(inp))
    A = align(src, W)
    json.dump(A, open(outp, "w"), indent=0)
    d = [abs(a["s"] - a["s_ws"]) for a in A]
    print(f"aligned {len(A)} words; median shift {np.median(d)*1000:.0f} ms, max {max(d)*1000:.0f} ms")
