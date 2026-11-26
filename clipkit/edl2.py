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
    keep = [i for i, w in enumerate(allw) if any(a - 0.08 <= w.get("s_ws", w["s"]) < b for a, b in segs)]
    drop = set()
    for i in keep:
        if _n(allw[i]["w"]) in FILLERS:
            drop.add(i)
        if any(abs(allw[i].get("s_ws", allw[i]["s"]) - t) < 0.04 for t in drop_times):
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


def _quiet(env, a, b):
    """time of the quietest 10 ms in [a, b] and its level (dB)."""
    i0, i1 = max(0, int(a * 100)), max(int(a * 100) + 1, int(b * 100) + 1)
    seg = env[i0:i1]
    k = int(np.argmin(seg))
    return (i0 + k + 0.5) / 100, float(seg[k])


def build3(words, segments, fps, drop_times=(), pause=0.5, pre=0.08, post=0.12, env=None, log=print, trust_aligner=False):
    """v3: aligned word boundaries; cut only long pauses (>pause) + removed words; generous padding.
    With env (10 ms dB envelope): a cut next to a removed word that is glued on (<0.2 s) goes to the quietest
    point between them; if there is no real dip there, a removed filler is put back (better a "like" than a
    clipped word)."""
    allw, ks = select_words(words, segments, drop_times)
    if not ks:
        return [], []
    segs = [(x[0], x[1]) for x in segments]
    in_seg = {i for i, w in enumerate(allw) if any(a - 0.08 <= w.get("s_ws", w["s"]) < b for a, b in segs)}
    ref = float(np.percentile(env[int(allw[ks[0]]["s"] * 100):int(allw[ks[-1]]["e"] * 100)], 75)) if env is not None else 0
    for _ in range(8):
        edl, risky = _edl3(allw, ks, pause, pre, post, env, ref, trust_aligner)
        back = [j for j in risky if j in in_seg and j not in ks]
        if not back:
            break
        ks = sorted(set(ks) | set(back))
    for j in risky:
        log(f"  RISK cut glued to '{allw[j]['w']}' @ {allw[j].get('s_ws', allw[j]['s']):.2f} (segment edge: move it)")
    merged = []
    for a, b in edl:
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for p_ in merged:
        p_[1] = p_[0] + max(1, round((p_[1] - p_[0]) * fps)) / fps
    return merged, [allw[i] for i in ks]


def _silent(env, a, b, q, last):
    """latest (last=True) or earliest 20 ms-silent point in [a, b]; None if the audio never goes quiet."""
    i0, i1 = max(1, int(a * 100)), int(b * 100)
    rng = range(i1, i0 - 1, -1) if last else range(i0, i1 + 1)
    for j in rng:
        if env[j] < q and env[j - 1] < q:
            return j
    return None


def _edl3(allw, ks, pause, pre, post, env, ref, trust_aligner=False):
    kset = set(ks)
    groups, cur = [], [ks[0]]
    for a, b in zip(ks, ks[1:]):
        if b == a + 1 and allw[b]["s"] - allw[a]["e"] < pause:
            cur.append(b)                     # natural short pause: keep it, no cut
        else:
            groups.append(cur); cur = [b]
    groups.append(cur)
    edl, risky = [], []
    q = ref - 22
    for g in groups:
        f, l = g[0], g[-1]
        p = allw[f - 1] if f > 0 else None
        n = allw[l + 1] if l + 1 < len(allw) else None
        w0, w1 = allw[f], allw[l]
        # take the earlier/later of the two estimates only when they roughly agree (Whisper is sometimes ~1 s off)
        s_ws, e_ws = w0.get("s_ws", w0["s"]), w1.get("e_ws", w1["e"])
        lim = 0.25 if trust_aligner else 99
        s_min = min(w0["s"], s_ws) if abs(s_ws - w0["s"]) < lim else w0["s"]
        e_max = max(w1["e"], e_ws) if abs(e_ws - w1["e"]) < lim else w1["e"]
        if env is None:
            edl.append([s_min - pre, e_max + post]); continue
        # IN: the last silence before the first word's onset (never inside the removed word before it)
        lo = s_min - 0.4
        if p:
            lo = max(lo, min(p["e"], p.get("e_ws", p["e"])) - 0.05)
        j = _silent(env, lo, s_min + 0.05, q, last=True)
        if j is None:
            t_in = _quiet(env, lo, s_min + 0.02)[0]
            if p and (f - 1) not in kset: risky.append(f - 1)
        else:
            k = j
            while k > j - 6 and k / 100 > lo and env[k - 1] < q:   # back off up to 50 ms inside the silence
                k -= 1
            t_in = k / 100
        # OUT: the first silence after the last word really ends
        hi = e_max + 0.45
        if n:
            hi = min(hi, max(n["s"], n.get("s_ws", n["s"])) + 0.05)
        j = _silent(env, e_max - 0.05, hi, q, last=False)
        if j is None:
            t_out = _quiet(env, e_max - 0.02, hi)[0]
            if n and (l + 1) not in kset: risky.append(l + 1)
        else:
            k, extra = j, (12 if l == ks[-1] else 5)
            while k < j + extra and k / 100 < hi and env[k + 1] < q:
                k += 1
            t_out = (k + 1) / 100
        edl.append([t_in, t_out])
    return edl, risky
