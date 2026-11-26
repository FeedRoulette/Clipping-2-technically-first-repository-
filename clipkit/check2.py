"""Verify a v2 spec: kept text, length, and for every cut the audio level + distance to neighbouring speech."""
import json, sys
import numpy as np
sys.path.insert(0, __import__("os").path.dirname(__file__))
import editor as M, edl2

spec = json.load(open(sys.argv[1]))
M.SRC = spec["src"]
words = []
for w in json.load(open(spec["words"])):
    if words and w["w"].startswith(("-", ".", "%")) and w["s"] - words[-1]["e"] < 0.6:
        words[-1] = dict(words[-1], w=words[-1]["w"] + w["w"], e=w["e"])
    else:
        words.append(w)
env = M._energy()
edl, kept = (edl2.build3(words, spec["segments"], 30, spec.get("drop_at", [])) if spec.get("edit") == "v3" else edl2.build(words, spec["segments"], env, 30, spec.get("drop_at", [])))
total = sum(b - a for a, b in edl)
sp = float(spec.get("speed", 1.0))
speech = np.percentile(env, 75)
bad = []
for a, b in edl:
    for t, tag in ((a, "in"), (b, "out")):
        lv = env[min(len(env) - 1, int(t * 100))] - speech
        if lv > -12:
            bad.append(f"{tag}@{t:.2f}:{lv:+.0f}dB")
print(f"length {total:.1f}s -> {total / sp:.1f}s at {sp}x | pieces {len(edl)} | loud cuts: {bad or 'none'}")
print("TEXT:", " ".join(w["w"] for w in kept))
