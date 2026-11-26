"""Editing core: edit decision list (audio-snapped cuts), face/shot analysis, framing, helpers."""
import json, re, subprocess, sys, os
from pathlib import Path
import cv2
import numpy as np

import os
SRC = os.environ.get("CLIP_SRC", "")
CODE = Path(__file__).resolve().parent
ASSETS = CODE / "assets"
FONTS = ASSETS / "fonts"
OW, OH, FPS = 1080, 1920, 30
YELLOW = "&H0000D7FF"   # #FFD700
WHITE = "&H00FFFFFF"
FILLERS = {"um", "uh", "uhm", "erm", "er"}
CENSOR = {"fuck": "f*ck", "fucking": "f*cking", "fuckin": "f*ckin", "shit": "sh*t", "shitting": "sh*tting",
          "motherfuckers": "motherf*ckers", "bullshit": "bullsh*t", "ass": "a**"}


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return r.stdout


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


# ------------------------------------------------------------------ edit decision list
def build_edl(words, segments, max_gap=0.5, keep_gap=None, pre_pad=0.12, post_pad=0.25):
    """Pieces = chosen segments, split only at real pauses (> max_gap). Generous padding so no word is clipped:
    0.12 s before and 0.25 s after every piece, but never reaching into a word that is not kept."""
    pieces, tight = [], []
    segs3 = [tuple(x) + (None,) * (3 - len(x)) for x in segments]
    segments = [(x[0], x[1]) for x in segs3]
    for a, b, flag in segs3:
        n0 = len(pieces)
        ws = [w for w in words if a - 0.08 <= w["s"] < b]      # any word that STARTS inside is kept whole
        cur = None
        for w in ws:
            s, e = w["s"], w["e"]
            if cur and s - cur[1] <= max_gap:
                cur[1] = max(cur[1], e)
            else:
                if cur:
                    pieces.append(cur)
                cur = [s, e]
        if cur:
            pieces.append(cur)
        tight += [flag == "tight"] * (len(pieces) - n0)
    kept = {(w["s"], w["e"]) for a, b in segments for w in words if a - 0.08 <= w["s"] < b}
    all_w = sorted(words, key=lambda w: w["s"])
    out = []
    for i, (s, e) in enumerate(pieces):
        prev_e = max([w["e"] for w in all_w if w["s"] < s - 0.001 and (w["s"], w["e"]) not in kept] or [-1])
        nxt_s = min([w["s"] for w in all_w if w["s"] > e - 0.001 and (w["s"], w["e"]) not in kept] or [1e9])
        prev_k = max([w["e"] for w in all_w if w["e"] <= s + 0.001 and w["s"] < s - 0.001] or [-1])
        nxt_k = min([w["s"] for w in all_w if w["s"] >= e - 0.001 and w["s"] > s] or [1e9])
        pre = min(pre_pad, s - prev_e - 0.03, max(0.0, (s - prev_k) / 2))
        post = post_pad + (0.3 if i == len(pieces) - 1 else 0)
        post = min(post, nxt_s - e - 0.03, max(0.05, (nxt_k - e) / 2) if nxt_k < 1e9 else post)
        out.append([max(0, s - max(0.0, pre)), e + max(0.0, post)])
    # snap every cut to the quietest moment near it (real audio, not word timestamps)
    env = _energy()
    if env is not None:
        def quiet(lo, hi):
            a, b = int(max(0, lo) * 100), int(max(lo + 0.02, hi) * 100)
            seg = env[a:b]
            return (a + int(np.argmin(seg))) / 100 if len(seg) else lo
        for i, (p, (s, e)) in enumerate(zip(out, pieces)):
            prev_e = max([w["e"] for w in all_w if w["s"] < s - 0.001] or [s - 0.4])
            nxt_s = min([w["s"] for w in all_w if w["s"] > e - 0.001 and w["s"] >= s + 0.001] or [e + 0.6])
            if tight[i]:
                # "tight": speech runs straight on - cut in the gap between the two words, never slide
                p[0] = quiet(max(prev_e, s - 0.3), s - 0.01) if prev_e < s else s - 0.02
                p[1] = quiet(e, max(e + 0.03, min(nxt_s - 0.01, e + 0.35))) + 0.01
                continue
            p[0] = quiet(max(s - 0.35, min(prev_e, s) - 0.05), s + 0.04)
            hi = min(e + (0.7 if i == len(pieces) - 1 else 0.4), max(nxt_s + 0.06, e + 0.12))
            p[1] = quiet(e - 0.06, hi) + 0.02
            # still inside speech? slide to the nearest real pause (keeps a word or two extra, never cuts one)
            floor = np.percentile(env, 75) - 14
            if i > 0 and env[int(p[0] * 100)] > floor:
                a = int((s - 1.5) * 100)
                gaps = [k for k in range(int(s * 100), max(a, 0), -1) if env[k] <= floor]
                if gaps:
                    p[0] = gaps[0] / 100
            if env[min(len(env) - 1, int(p[1] * 100))] > floor:
                b = int((e + 1.5) * 100)
                gaps = [k for k in range(int(e * 100), min(b, len(env))) if env[k] <= floor]
                if gaps:
                    p[1] = gaps[0] / 100 + 0.03
    for p in out:
        p[1] = p[0] + max(1, round((p[1] - p[0]) * FPS)) / FPS
    return out


_ENV = {}


def _energy():
    """10 ms RMS energy (dB) of the source's audio, cached per source."""
    if SRC in _ENV:
        return _ENV[SRC]
    cache = Path(SRC).with_suffix(".energy.npy")
    if cache.exists():
        _ENV[SRC] = np.load(cache)
        return _ENV[SRC]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", SRC, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = len(a) // 160
    rms = np.sqrt((a[:n * 160].reshape(n, 160) ** 2).mean(1) + 1e-10)
    env = 20 * np.log10(rms)
    env = np.convolve(env, np.ones(3) / 3, "same")
    np.save(cache, env)
    _ENV[SRC] = env
    return env


def cut(edl, out):
    """each piece is read as its own input (seeks straight to it), then concatenated; memory stays small
    even when pieces come from opposite ends of the episode."""
    inputs, parts, lab = [], [], ""
    for i, (s, e) in enumerate(edl):
        d = e - s
        pre = min(1.0, s)
        inputs += ["-ss", f"{s - pre:.3f}", "-t", f"{d + pre + 0.5:.3f}", "-i", SRC]
        parts.append(f"[{i}:v]trim=start={pre:.3f}:end={pre + d:.3f},setpts=PTS-STARTPTS,fps={FPS}[v{i}]")
        parts.append(f"[{i}:a]atrim=start={pre:.3f}:end={pre + d:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.015,afade=t=out:st={d - 0.02:.3f}:d=0.02[a{i}]")
        lab += f"[v{i}][a{i}]"
    fc = ";".join(parts) + f";{lab}concat=n={len(edl)}:v=1:a=1[v][a]"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "10", "-c:a", "pcm_s16le", out])


class Map:
    """output time <-> source time."""
    def __init__(self, edl):
        self.edl, self.off = edl, []
        acc = 0
        for s, e in edl:
            self.off.append(acc)
            acc += e - s
        self.total = acc

    def src(self, t):
        for (s, e), o in zip(self.edl, self.off):
            if t < o + (e - s):
                return s + (t - o), self.off.index(o)
        return self.edl[-1][1], len(self.edl) - 1

    def out(self, ts):
        for (s, e), o in zip(self.edl, self.off):      # piece that contains ts (works for re-ordered pieces)
            if s <= ts <= e:
                return o + ts - s
        best = min(zip(self.edl, self.off), key=lambda p: min(abs(ts - p[0][0]), abs(ts - p[0][1])))
        (s, e), o = best
        return o if ts < s else o + (e - s)


# ------------------------------------------------------------------ shot analysis on the source
AN_FPS = 30


def analyze(a, b):
    det = cv2.FaceDetectorYN.create(str(ASSETS / "models" / "face_detection_yunet_2023mar.onnx"), "", (960, 540), 0.75, 0.3, 50)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", SRC,
                          "-vf", f"fps={AN_FPS},scale=960:540", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         stdout=subprocess.PIPE)
    S, prev = [], None
    i = 0
    while True:
        buf = p.stdout.read(960 * 540 * 3)
        if len(buf) < 960 * 540 * 3:
            break
        fr = np.frombuffer(buf, np.uint8).reshape(540, 960, 3)
        h = cv2.calcHist([cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(h, h)
        cutf = prev is not None and cv2.compareHist(prev, h, cv2.HISTCMP_BHATTACHARYYA) > 0.3
        _, faces = det.detect(fr)
        fl = [{"cx": (f[0] + f[2] / 2) / 960, "cy": (f[1] + f[3] / 2) / 540, "h": f[3] / 540}
              for f in (faces if faces is not None else []) if f[2] * f[3] > 960 * 540 * 0.0015]
        S.append({"t": a + i / AN_FPS, "cut": cutf, "faces": fl})
        prev = h
        i += 1
    p.wait()
    shots, cur = [], []
    for s in S:
        if s["cut"] and cur:
            shots.append(cur)
            cur = []
        cur.append(s)
    shots.append(cur)
    plan = []
    for sh in shots:
        xs = sorted(f["cx"] for s in sh for f in s["faces"])
        clusters = []
        for x in xs:
            if clusters and x - clusters[-1][-1] < 0.1:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        people = [c for c in clusters if len(c) >= max(2, len(sh) * 0.3)]
        allf = [f for s in sh for f in s["faces"]]
        entry = {"t0": sh[0]["t"], "t1": sh[-1]["t"] + 1 / AN_FPS}
        if len(people) >= 2:
            p1, p2 = people[0], people[-1]
            ys1 = [f["cy"] for f in allf if abs(f["cx"] - np.median(p1)) < 0.1]
            ys2 = [f["cy"] for f in allf if abs(f["cx"] - np.median(p2)) < 0.1]
            hs = [f["h"] for f in allf]
            entry.update(mode="split", x1=float(np.median(p1)), x2=float(np.median(p2)),
                         y1=float(np.median(ys1)), y2=float(np.median(ys2)), fh=float(np.median(hs)))
        elif people:
            big = max(people, key=len)
            fs = [f for f in allf if abs(f["cx"] - np.median(big)) < 0.1]
            entry.update(mode="single", x=float(np.median([f["cx"] for f in fs])),
                         y=float(np.median([f["cy"] for f in fs])), fh=float(np.median([f["h"] for f in fs])))
        else:
            entry.update(mode="single", x=0.5, y=0.4, fh=0.3)
        entry["nf"] = len(people)
        plan.append(entry)
    # very short shots (camera dissolves, 1-12 frames) borrow the framing of the next real shot
    for k in range(len(plan)):
        if plan[k]["t1"] - plan[k]["t0"] < 0.4:
            src = next((plan[j] for j in range(k + 1, len(plan)) if plan[j]["t1"] - plan[j]["t0"] >= 0.4), None)
            src = src or next((plan[j] for j in range(k - 1, -1, -1) if plan[j]["t1"] - plan[j]["t0"] >= 0.4), None)
            if src:
                t0, t1 = plan[k]["t0"], plan[k]["t1"]
                plan[k] = dict(src, t0=t0, t1=t1)
    return plan


def shot_at(plan, ts):
    for i, p in enumerate(plan):
        if p["t0"] - 0.005 <= ts < p["t1"]:
            return i, p
    return len(plan) - 1, plan[-1]


# ------------------------------------------------------------------ drawing
def warp(fr, cx, cy, cw, ch, w, h):
    """sub-pixel crop (cx,cy centre, cw x ch) -> w x h, high quality."""
    H, W = fr.shape[:2]
    cw, ch = min(cw, W), min(ch, H)
    x0 = float(np.clip(cx - cw / 2, 0, W - cw))
    y0 = float(np.clip(cy - ch / 2, 0, H - ch))
    sx, sy = w / cw, h / ch
    M = np.float32([[sx, 0, -x0 * sx], [0, sy, -y0 * sy]])
    return cv2.warpAffine(fr, M, (w, h), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)


def sharpen(img, amount=0.55):
    blur = cv2.GaussianBlur(img, (0, 0), 1.0)
    return cv2.addWeighted(img, 1 + amount, blur, -amount, 0)


SPLIT_BOTTOM_OFFSET = 0.12


def compose(fr, shot, z):
    H, W = fr.shape[:2]
    if shot["mode"] == "split":
        half = OH // 2
        out = []
        for k, (x, y) in enumerate(((shot["x1"], shot["y1"]), (shot["x2"], shot["y2"]))):
            ch = min(H * 0.62, shot["fh"] * H * 3.2) / z
            cw = ch * OW / half
            # bottom panel: face sits higher so the lower third (chest) is free for the brand logo
            off = SPLIT_BOTTOM_OFFSET if k == 1 else 0.12
            out.append(warp(fr, x * W, y * H + ch * off, cw, ch, OW, half))
        img = np.vstack(out)
        img[half - 2:half + 2] = 0
        return img
    ch = H / z
    cw = ch * OW / OH
    cy = shot["y"] * H + ch * 0.13 if z > 1.001 else H / 2
    return warp(fr, shot["x"] * W, cy, cw, ch, OW, OH)


def cover(img, w, h, z=1.0):
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    cw, ch = w / s / z, h / s / z
    return warp(img, iw / 2, ih / 2, cw, ch, w, h)


# ------------------------------------------------------------------ captions
def esc(t):
    return t.replace("{", "(").replace("}", ")").replace("\\", "")


def cap_text(w):
    t = re.sub(r'^["“”‘’]+|["“”‘’]+$', "", w.strip()).strip("'") if not w.strip().endswith("s'") else w.strip()
    core = norm(t)
    if core in CENSOR:
        t = re.sub(re.escape(core), CENSOR[core], t, flags=re.I)
    t = re.sub(r"[,.;:!?]+$", "", t) if not t.endswith("?") else t
    return t.upper()


def chunks(words):
    out, cur = [], []
    for w in words:
        if cur:
            n = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if len(cur) >= 3 or n > 15 or w["s"] - cur[-1]["e"] > 0.3 or re.search(r"[.?!,]$", cur[-1]["w"]):
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def tt(s):
    s = max(0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def build_ass(owords, hook, hook_hi, total, layout_at, path):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OW}
PlayResY: {OH}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Montserrat Black,86,{WHITE},{WHITE},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Hook,Montserrat Black,90,{WHITE},{WHITE},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,8,4,8,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    chs = chunks(owords)
    for ci, ch in enumerate(chs):
        nxt = chs[ci + 1][0]["s"] if ci + 1 < len(chs) else 1e9
        toks = [esc(cap_text(w["w"])) for w in ch]
        y = int(OH * (0.5 if layout_at(ch[0]["s"]) == "split" else 0.68))
        for i, w in enumerate(ch):
            s = ch[0]["s"] if i == 0 else w["s"]
            e = ch[i + 1]["s"] if i + 1 < len(ch) else min(ch[-1]["e"] + 0.12, nxt)
            parts = [f"{{\\c{YELLOW}}}{t}{{\\c{WHITE}}}" if j == i else t for j, t in enumerate(toks)]
            pop = "\\fscx88\\fscy88\\t(0,70,\\fscx100\\fscy100)" if i == 0 else ""
            ev.append(f"Dialogue: 1,{tt(s)},{tt(e)},Cap,,0,0,0,,{{\\pos({OW // 2},{y}){pop}}}{' '.join(parts)}")
    if hook:
        txt = esc(hook.upper())
        for h in hook_hi:
            txt = txt.replace(h.upper(), f"{{\\c{YELLOW}}}{h.upper()}{{\\c{WHITE}}}")
        ev.append(f"Dialogue: 2,{tt(0)},{tt(min(3.6, total))},Hook,,0,0,0,,"
                  f"{{\\pos({OW // 2},{int(OH * 0.075)})\\fad(0,220)\\fscx80\\fscy80\\t(0,120,\\fscx100\\fscy100)}}{txt}")
    Path(path).write_text(head + "\n".join(ev) + "\n")


# ------------------------------------------------------------------ main
def main(spec_path):
    spec = json.load(open(spec_path))
    name = spec["name"]
    wd = Path(spec_path).parent / f"build_{name}"
    wd.mkdir(exist_ok=True)
    words = []
    for w in json.load(open(spec["words"])):     # glue "4" + "-0" -> "4-0", "head" + "-on" -> "head-on"
        if words and w["w"].startswith("-") and w["s"] - words[-1]["e"] < 0.6:
            words[-1] = dict(words[-1], w=words[-1]["w"] + w["w"], e=w["e"])
        else:
            words.append(w)
    edl = build_edl(words, spec["segments"])
    m = Map(edl)
    print(name, "pieces", len(edl), "duration", round(m.total, 1), flush=True)
    cutp = wd / "cut.mp4"
    cut(edl, cutp)

    plan = analyze(edl[0][0] - 0.2, edl[-1][1] + 0.2)
    print("shots:", [(round(p["t0"], 1), p["mode"]) for p in plan], flush=True)

    # output words (drop fillers, map times)
    ow = []
    for w in words:
        if norm(w["w"]) in FILLERS:
            continue
        inside = any(s - 0.01 <= w["s"] and w["e"] <= e + 0.05 for s, e in edl)
        if inside:
            ow.append(dict(w, s=m.out(w["s"]), e=max(m.out(w["s"]) + 0.06, m.out(w["e"]))))
    for fix in spec.get("fixes", []):          # manual caption corrections: [source_time, new_text]
        for w in ow:
            pass
    fixes = {round(t, 1): txt for t, txt in spec.get("fixes", [])}
    for w, src in zip(ow, [x for x in words if norm(x["w"]) not in FILLERS and
                            any(s - 0.01 <= x["s"] and x["e"] <= e + 0.05 for s, e in edl)]):
        k = round(src["s"], 1)
        if k in fixes:
            w["w"] = fixes[k]
    ow = [w for w in ow if w["w"]]

    def layout_at(t):
        return shot_at(plan, m.src(t)[0])[1]["mode"]

    ass = wd / "cap.ass"
    build_ass(ow, spec["hook"], spec.get("hook_hi", []), m.total, layout_at, ass)

    # b-roll windows in output time
    brolls = []
    for b in spec.get("broll", []):
        t0, t1 = m.out(b["from"]), m.out(b["to"])
        cap = cv2.VideoCapture(b["file"])
        fr = []
        cap.set(cv2.CAP_PROP_POS_MSEC, b.get("offset", 1.0) * 1000)
        sfps = cap.get(cv2.CAP_PROP_FPS) or 30
        need = int((t1 - t0) * sfps) + 2
        while len(fr) < need:
            ok, f = cap.read()
            if not ok:
                break
            fr.append(f)
        brolls.append((t0, t1, fr, sfps))

    # audio
    mix = wd / "mix.m4a"
    tot = m.total
    mv = spec.get("music_db", -27)
    fc = (f"[0:a]highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=2,"
          f"loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000,aformat=channel_layouts=stereo,asplit=2[v][sc];"
          f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=start={spec.get('music_start', 0)},"
          f"asetpts=PTS-STARTPTS,atrim=0:{tot:.3f},loudnorm=I={mv}:TP=-6,"
          f"afade=t=in:d=1.0,afade=t=out:st={max(0, tot - 2.0):.3f}:d=2.0[mu];"
          f"[mu][sc]sidechaincompress=threshold=0.04:ratio=4:attack=30:release=500[md];"
          f"[v][md]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89[out]")
    run(["ffmpeg", "-y", "-v", "error", "-i", cutp, "-stream_loop", "-1", "-i", spec["music"],
         "-filter_complex", fc, "-map", "[out]", "-t", f"{tot:.3f}", "-c:a", "aac", "-b:a", "192k", mix])

    # video
    out = Path(spec["out"])
    info = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                           "stream=width,height", "-of", "json", cutp]))["streams"][0]
    W, H = info["width"], info["height"]
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", cutp, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}",
                            "-r", str(FPS), "-i", "-", "-i", mix, "-vf", f"ass={ass}:fontsdir={FONTS}",
                            "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-profile:v", "high",
                            "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", out],
                           stdin=subprocess.PIPE)
    n = W * H * 3
    i = 0
    prev_key, base_z, key_start = None, 1.0, 0.0
    jumps = 0
    while True:
        buf = dec.stdout.read(n)
        if len(buf) < n:
            break
        t = i / FPS
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        ts, piece = m.src(t)
        si, shot = shot_at(plan, ts)
        key = (si, piece)
        if key != prev_key:
            if prev_key is not None and prev_key[0] == si:      # jump cut inside the same camera shot
                jumps += 1
                base_z = 1.09 if jumps % 2 else 1.0
            elif prev_key is None or prev_key[0] != si:
                base_z, jumps = 1.0, 0
            key_start = t
            prev_key = key
        z = base_z + min(0.04, (t - key_start) * 0.006)        # slow push-in
        img = compose(fr, shot, z if shot["mode"] != "split" else 1.0 + min(0.03, (t - key_start) * 0.004))
        for t0, t1, bfr, bfps in brolls:
            if t0 <= t < t1 and bfr:
                k = min(len(bfr) - 1, int((t - t0) * bfps))
                b = cover(bfr[k], OW, OH, 1.0 + 0.06 * (t - t0) / max(0.1, t1 - t0))
                fade = min(1.0, (t - t0) / 0.2, (t1 - t) / 0.2)
                img = cv2.addWeighted(b, fade, img, 1 - fade, 0) if fade < 1 else b
        img = sharpen(img)
        if t < 3.6:   # soft top gradient so the hook reads on any background
            g = np.linspace(0.55, 0, 520)[:, None, None] * min(1, (3.6 - t) / 0.25)
            img[:520] = (img[:520] * (1 - g)).astype(np.uint8)
        enc.stdin.write(np.ascontiguousarray(img).tobytes())
        i += 1
    dec.wait()
    enc.stdin.close()
    enc.wait()
    print("done", out, round(i / FPS, 1), "s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
