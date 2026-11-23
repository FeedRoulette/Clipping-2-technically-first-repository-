"""Pre-render check for a spec: prints the exact caption text the clip will contain, its length,
and the loudness of every cut point (should all be well below speech, e.g. < -12 dB).
  python3 check.py spec.json"""
import json, sys
import numpy as np
import editor as M
from render import make_chunks

spec = json.load(open(sys.argv[1]))
M.SRC = spec["src"]
words = []
for w in json.load(open(spec["words"])):
    if words and w["w"].startswith(("-", ".", "%")) and w["s"] - words[-1]["e"] < 0.6:
        words[-1] = dict(words[-1], w=words[-1]["w"] + w["w"], e=w["e"])
    else:
        words.append(w)
edl = M.build_edl(words, spec["segments"])
mp = M.Map(edl)
env = M._energy()
speech = np.percentile(env, 75)
levels = [round(float(env[min(len(env) - 1, int(x * 100))] - speech), 1) for s, e in edl for x in (s, e)]
ow = sorted([dict(w, s=mp.out(w["s"])) for w in words if any(s <= (w["s"] + w["e"]) / 2 < e for s, e in edl)],
            key=lambda w: w["s"])
print(f"length: {mp.total:.1f}s (target 15-35)")
print("cut levels vs speech (dB):", levels[1:], " <- anything above about -12 means a cut inside speech; move it")
print("captions:", " / ".join(" ".join(M.cap_text(w["w"]) for w in c) for c in make_chunks(ow)))
