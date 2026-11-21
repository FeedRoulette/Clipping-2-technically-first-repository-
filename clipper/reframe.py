"""Smart 16:9 -> 9:16 reframing.
Detects faces (YuNet), scene cuts, and the *active speaker* (mouth-region motion), then produces a
per-scene layout plan:
  track : 9:16 crop that follows the person talking (hard-cuts between speakers like an editor would)
  split : two people far apart on screen -> stacked top/bottom
  fit   : no faces (screen share, b-cam) -> full frame over blurred background
"""
import subprocess

import cv2
import numpy as np

from . import ASSETS
from .util import probe

MODEL = ASSETS / "models" / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 5


def _frames(path, fps, width):
    info = probe(path)
    h = int(round(info["height"] * width / info["width"] / 2) * 2)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={width}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    n = width * h * 3
    i = 0
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n:
            break
        yield i / fps, np.frombuffer(buf, np.uint8).reshape(h, width, 3)
        i += 1
    p.wait()


def analyze(path):
    info = probe(path)
    sw, sh = info["width"], info["height"]
    aw = 960
    ah = int(round(sh * aw / sw / 2) * 2)
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (aw, ah), 0.7, 0.3, 50)
    samples = []
    prev_gray, prev_hist = None, None
    prev_faces = []
    for t, fr in _frames(path, SAMPLE_FPS, aw):
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        cut = prev_hist is not None and cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA) > 0.35
        _, faces = det.detect(fr)
        fl = []
        for f in (faces if faces is not None else []):
            x, y, w, h = f[:4]
            if w * h < (aw * ah) * 0.002:
                continue
            mx1, my1, mx2, my2 = f[10], f[11], f[12], f[13]   # mouth corners
            mw = max(6, abs(mx2 - mx1))
            box = (int(min(mx1, mx2) - mw * .2), int(min(my1, my2) - mw * .35),
                   int(max(mx1, mx2) + mw * .2), int(max(my1, my2) + mw * .45))
            motion = 0.0
            if prev_gray is not None and not cut:
                x1, y1, x2, y2 = [max(0, v) for v in box]
                a = gray[y1:y2, x1:x2].astype(np.float32)
                b = prev_gray[y1:y2, x1:x2].astype(np.float32)
                if a.size and a.shape == b.shape:
                    # mouth motion relative to whole-face motion => talking, not head movement
                    fx1, fy1 = max(0, int(x)), max(0, int(y))
                    fa = gray[fy1:fy1 + int(h), fx1:fx1 + int(w)].astype(np.float32)
                    fb = prev_gray[fy1:fy1 + int(h), fx1:fx1 + int(w)].astype(np.float32)
                    head = np.abs(fa - fb).mean() if fa.size and fa.shape == fb.shape else 0
                    motion = max(0.0, float(np.abs(a - b).mean() - 0.6 * head))
            fl.append({"cx": (x + w / 2) / aw, "cy": (y + h / 2) / ah, "w": w / aw, "h": h / ah,
                       "area": w * h / (aw * ah), "motion": motion})
        samples.append({"t": t, "cut": cut, "faces": fl})
        prev_gray, prev_hist, prev_faces = gray, hist, fl
    return {"w": sw, "h": sh, "samples": samples}


def _tracks(scene):
    """Cluster faces in a scene into persistent people by x position."""
    xs = sorted(f["cx"] for s in scene for f in s["faces"])
    if not xs:
        return []
    clusters = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] > 0.12:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    min_n = max(2, len(scene) * 0.25)
    return [float(np.median(c)) for c in clusters if len(c) >= min_n]


def plan(analysis, out_aspect=9 / 16):
    sw, sh = analysis["w"], analysis["h"]
    S = analysis["samples"]
    crop_w_norm = min(1.0, sh * out_aspect / sw)   # width of a 9:16 crop in normalised units
    if sw / sh <= out_aspect + 0.02:
        return [{"t": 0.0, "mode": "fit_vertical"}]
    scenes, cur = [], []
    for s in S:
        if s["cut"] and cur:
            scenes.append(cur)
            cur = []
        cur.append(s)
    if cur:
        scenes.append(cur)

    keys = []
    for sid, sc in enumerate(scenes):
        people = _tracks(sc)
        with_face = sum(1 for s in sc if s["faces"]) / len(sc)
        if not people or with_face < 0.4:
            keys.append({"t": sc[0]["t"], "mode": "fit", "sid": sid})
            continue
        if len(people) >= 2 and people[-1] - people[0] > crop_w_norm * 0.9:
            # two people who don't fit in one crop: split if both are consistently visible
            both = sum(1 for s in sc if len(s["faces"]) >= 2) / len(sc)
            if both > 0.5:
                ys = [f["cy"] for s in sc for f in s["faces"]]
                sizes = [f["h"] for s in sc for f in s["faces"]]
                keys.append({"t": sc[0]["t"], "mode": "split", "x1": people[0], "x2": people[-1],
                             "y": float(np.median(ys)), "fh": float(np.median(sizes)), "sid": sid})
                continue
        if len(people) >= 2 and people[-1] - people[0] < crop_w_norm * 0.75:
            # everyone fits in one vertical frame (wide shot): frame the group, don't cut anyone out
            keys.append({"t": sc[0]["t"], "mode": "track", "x": (people[0] + people[-1]) / 2,
                         "who": -1, "sid": sid})
            continue
        # track the active speaker
        def nearest(x):
            return int(np.argmin([abs(x - p) for p in people]))
        talk = np.zeros((len(sc), len(people)))
        pos = [[[] for _ in people] for _ in sc]
        for i, s in enumerate(sc):
            for f in s["faces"]:
                k = nearest(f["cx"])
                talk[i, k] = max(talk[i, k], f["motion"])
                pos[i][k].append(f["cx"])
        # smooth talking evidence over ~1.2s
        k = max(1, int(SAMPLE_FPS * 1.2))
        ker = np.ones(k) / k
        talk = np.stack([np.convolve(talk[:, j], ker, mode="same") for j in range(len(people))], 1)
        active = int(np.argmax(talk[0])) if len(sc) else 0
        held = 0
        last_t = None
        for i, s in enumerate(sc):
            best = int(np.argmax(talk[i]))
            if best != active and talk[i, best] > talk[i, active] * 1.5 + 0.3:
                held += 1
                if held >= int(SAMPLE_FPS * 0.8):
                    active, held = best, 0
            else:
                held = 0
            xs = [x for row in pos[max(0, i - 7):i + 8] for x in row[active]]
            x = float(np.median(xs)) if xs else people[active]
            mode_key = {"t": s["t"], "mode": "track", "x": x, "who": active, "sid": sid}
            if last_t is None or keys[-1].get("who") != active or abs(keys[-1].get("x", -9) - x) > 0.015 \
                    or s["t"] - last_t > 1.0:
                keys.append(mode_key)
                last_t = s["t"]
    return keys


def at(keys, t):
    """Return the layout for time t, interpolating x inside a continuous track segment."""
    lo = 0
    for i, k in enumerate(keys):
        if k["t"] <= t:
            lo = i
        else:
            break
    k = dict(keys[lo])
    if k["mode"] == "track" and lo + 1 < len(keys):
        n = keys[lo + 1]
        if n["mode"] == "track" and n.get("who") == k.get("who") and n.get("sid") == k.get("sid") and n["t"] > k["t"]:
            a = (t - k["t"]) / (n["t"] - k["t"])
            a = a * a * (3 - 2 * a)
            k["x"] = k["x"] + (n["x"] - k["x"]) * a
    return k
