"""Word-accurate editor v2: keeps exactly the chosen words, removes fillers/stutters/dead air,
and cuts only inside real audio gaps (never across a neighbouring word -> no clipped or repeated words)."""
import re
import numpy as np

FILLERS = {"um", "uh", "uhm", "umm", "erm", "er", "ah", "hmm", "mm"}
BIGRAM_FILLERS = {("you", "know"), ("i", "mean")}


def _n(w):
    return re.sub(r"[^a-z0-9$%']", "", w.lower())


def select_words(words, segments, drop_times=()):
    allw = sorted(words, key=lambda w: w["s"])
    segs = [(x[0], x[1]) for x in segments]
    keep = [i for i, w in enumerate(allw) if any(a - 0.08 <= w["s"] < b for a, b in segs)]
    drop = set()
    for i in keep:
        if _n(allw[i]["w"]) in FILLERS:
            drop.add(i)
        if any(abs(allw[i]["s"] - t) < 0.04 for t in drop_times):
            drop.add(i)
    ks = [i for i in keep if i not in drop]
    # bigram fillers ("you know", "i mean")
    for a, b in zip(ks, ks[1:]):
        if b == a + 1 and (_n(allw[a]["w"]), _n(allw[b]["w"])) in BIGRAM_FILLERS:
            drop.update((a, b))
    ks = [i for i in keep if i not in drop]
    # stutters / restarts: "it's it's", "I I", "five nights five nights"
    changed = True
    while changed:
        changed = False
        for k in range(len(ks) - 1):
            a, b = ks[k], ks[k + 1]
            if _n(allw[a]["w"]) == _n(allw[b]["w"]) and allw[b]["s"] - allw[a]["e"] < 0.8:
                drop.add(a); changed = True
            for m in (4, 3, 2):                        # restarts: "you want me to, you want me to ..."
                if changed or k + 2 * m > len(ks):
                    continue
                first = [_n(allw[ks[k + j]]["w"]) for j in range(m)]
                second = [_n(allw[ks[k + m + j]]["w"]) for j in range(m)]
                if first == second and allw[ks[k + m]]["s"] - allw[ks[k + m - 1]]["e"] < 0.8:
                    drop.update(ks[k + j] for j in range(m)); changed = True
            if changed:
                ks = [i for i in keep if i not in drop]
                break
    return allw, [i for i in keep if i not in drop]


def build(words, segments, env, fps, drop_times=(), breath=0.10):
    """env: 10 ms dB envelope of the source. Returns (edl, kept_words)."""
    allw, ks = select_words(words, segments, drop_times)
    if not ks:
        return [], []
    # group kept words into continuous pieces
    groups, cur = [], [ks[0]]
    for a, b in zip(ks, ks[1:]):
        if b == a + 1 and allw[b]["s"] - allw[a]["e"] <= breath:
            cur.append(b)
        else:
            groups.append(cur); cur = [b]
    groups.append(cur)

    def E(t):
        return env[min(len(env) - 1, max(0, int(round(t * 100))))]

    def floor_at(t0, t1):
        a, b = int(max(0, t0 - 2) * 100), int(min(len(env) / 100, t1 + 2) * 100)
        seg = env[a:b]
        noise, speech = np.percentile(seg, 10), np.percentile(seg, 90)
        return max(noise + 6, speech - 26)

    def amin(lo, hi):
        a, b = int(lo * 100), max(int(lo * 100) + 1, int(hi * 100))
        seg = env[a:b]
        return (a + int(np.argmin(seg))) / 100 if len(seg) else lo

    edl = []
    for g in groups:
        f, l = g[0], g[-1]
        p = allw[f - 1] if f > 0 else None
        n = allw[l + 1] if l + 1 < len(allw) else None
        fl = floor_at(allw[f]["s"], allw[l]["e"])
        # IN: walk back from the first word's onset to the last silent frame (never before previous word's end)
        lo = (p["e"] if p else allw[f]["s"] - 0.4)
        t = allw[f]["s"] + 0.02
        while t > lo and E(t) > fl:
            t -= 0.01
        if t <= lo + 0.001 and E(t) > fl:         # glued to previous word: cut at the quietest point between them
            t = amin(max(lo - 0.04, (p["s"] + p["e"]) / 2 if p else lo), allw[f]["s"] + 0.04) - 0.02
            t_in = t                                   # glued: bias early so the kept word's onset is never chopped
        else:
            t_in = max(t - 0.03, lo + 0.005)
        # OUT: walk forward from the last word's end until real silence (never past next word's start)
        hi = (n["s"] if n else allw[l]["e"] + 0.5)
        t = allw[l]["e"] - 0.02
        while t < hi and E(t) > fl:
            t += 0.01
        if t >= hi - 0.001 and E(t) > fl:
            t = amin(allw[l]["e"] - 0.04, min(hi + 0.04, (n["s"] + n["e"]) / 2 if n else hi))
            t_out = t + 0.02                           # glued: bias late so the kept word's tail is never chopped
        else:
            t_out = min(t + 0.06, hi - 0.005)
        # trim silence the word timestamps over-reported at either edge
        while t_out - t_in > 0.15 and E(t_out - 0.07) <= fl - 3:
            t_out -= 0.01
        while t_out - t_in > 0.15 and E(t_in + 0.04) <= fl - 3:
            t_in += 0.01
        edl.append([t_in, max(t_out, t_in + 0.1)])
    # split pieces on real audio silences > 0.15 s that the word timestamps hid (breaths, hesitations)
    split = []
    for (a, b), g in zip(edl, groups):
        fl = floor_at(a, b)
        i0, i1 = int(a * 100), int(b * 100)
        quiet = [env[k] <= fl - 3 for k in range(i0, i1)]
        cur_a, k = a, 0
        while k < len(quiet):
            if quiet[k]:
                j = k
                while j < len(quiet) and quiet[j]:
                    j += 1
                if j - k > 15 and k > 3 and j < len(quiet) - 3:
                    split.append([cur_a, (i0 + k) / 100 + 0.04])
                    cur_a = (i0 + j) / 100 - 0.04
                k = j
            else:
                k += 1
        split.append([cur_a, b])
    edl = split
    groups = [None] * len(edl)
    # merge pieces that touch/overlap in the source (prevents any repeated audio)
    merged = []
    for (a, b), g in zip(edl, groups):
        if merged and a <= merged[-1][1] + 0.03:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    edl = merged
    for p_ in edl:
        p_[1] = p_[0] + max(1, round((p_[1] - p_[0]) * fps)) / fps
    kept = [allw[i] for i in ks]
    return edl, kept
