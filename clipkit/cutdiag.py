import json, sys
import numpy as np
sys.path.insert(0, __import__("os").path.dirname(__file__))
import editor as M, edl2
spec = json.load(open(sys.argv[1])); M.SRC = spec["src"]
words = []
for w in json.load(open(spec["words"])):
    if words and w["w"].startswith(("-", ".", "%")) and w["s"] - words[-1]["e"] < 0.6:
        words[-1] = dict(words[-1], w=words[-1]["w"] + w["w"], e=w["e"])
    else:
        words.append(w)
env = M._energy()
edl, kept = edl2.build(words, spec["segments"], env, 30, spec.get("drop_at", []))
allw = sorted(words, key=lambda w: w["s"])
for a, b in edl:
    for t, tag in ((a, "IN "), (b, "OUT")):
        i = int(t * 100)
        here = env[i]; left = env[max(0, i - 12):i].max(); right = env[i + 1:i + 13].max()
        dip = min(left, right) - here
        before = [w["w"] for w in allw if w["e"] <= t + 0.05][-1:]
        after = [w["w"] for w in allw if w["s"] >= t - 0.05][:1]
        loc = env[max(0, i - 300):i + 300]
        rel = here - np.percentile(loc, 90)
        silent = rel < -18
        flag = "" if (silent or dip >= 6) else f"  <-- RISK (level {rel:+.0f}dB vs speech)"
        print(f"{tag} {t:8.2f}  dip {dip:4.1f}dB lvl {here - np.percentile(env[max(0,i-300):i+300],90):+5.1f}  between {before} | {after}{flag}")
