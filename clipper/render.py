"""Step 4: render one clip spec -> finished 1080x1920 vertical video."""
import math
import random
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import FONTS
from . import broll as broll_mod
from . import captions, music, reframe
from .transcribe import caption_words
from .util import log, probe, read_json, run, write_json

OW, OH = 1080, 1920
FILLERS = {"um", "uh", "uhm", "umm", "erm", "er", "ah", "hmm", "mm"}


def _norm(w):
    return re.sub(r"[^a-z0-9$%']", "", w.lower())


# ---------------------------------------------------------------- timeline editing
def snap(words, start, end):
    inside = [w for w in words if w["s"] >= start - 0.3 and w["e"] <= end + 0.6]
    if not inside:
        return start, end
    return max(0.0, inside[0]["s"] - 0.10), inside[-1]["e"] + 0.30


def keep_spans(words, dur, cut_silences=True, cut_fillers=True, max_gap=0.45):
    ws = [w for w in words if not (cut_fillers and _norm(w["w"]) in FILLERS)]
    if not cut_silences or not ws:
        return [(0.0, dur)], ws
    spans = []
    for w in ws:
        a, b = max(0.0, w["s"] - 0.08), min(dur, w["e"] + 0.14)
        if spans and a - spans[-1][1] <= max_gap:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    spans[0][0] = min(spans[0][0], 0.05)
    merged = []
    for a, b in spans:  # very short leftovers sound choppy: glue them on
        if merged and (b - a < 0.25 or a - merged[-1][1] < 0.12):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [tuple(s) for s in merged], ws


class TimeMap:
    def __init__(self, spans):
        self.spans = spans
        self.offsets = []
        acc = 0.0
        for a, b in spans:
            self.offsets.append(acc)
            acc += b - a
        self.total = acc

    def __call__(self, t):
        for (a, b), o in zip(self.spans, self.offsets):
            if t < a:
                return o
            if t <= b:
                return o + (t - a)
        return self.total


def cut_video(src, start, spans, out, fps):
    parts, labels = [], []
    for i, (a, b) in enumerate(spans):
        d = b - a
        fd = min(0.012, d / 4)
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={fd:.3f},afade=t=out:st={d - fd:.3f}:d={fd:.3f}[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    fc = ";".join(parts) + f";{''.join(labels)}concat=n={len(spans)}:v=1:a=1[v][a];[v]fps={fps}[vo]"
    end = start + spans[-1][1] + 0.05
    run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src, "-filter_complex", fc,
         "-map", "[vo]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
         "-c:a", "pcm_s16le", out])


# ---------------------------------------------------------------- visuals
def _cover(img, w, h):
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    r = cv2.resize(img, (max(w, int(iw * s + 0.5)), max(h, int(ih * s + 0.5))), interpolation=cv2.INTER_LINEAR)
    y, x = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y:y + h, x:x + w]


def _crop(fr, cx, cy, cw, ch, w, h):
    H, W = fr.shape[:2]
    cw, ch = min(cw, W), min(ch, H)
    x = int(np.clip(cx - cw / 2, 0, W - cw))
    y = int(np.clip(cy - ch / 2, 0, H - ch))
    return cv2.resize(fr[y:y + int(ch), x:x + int(cw)], (w, h), interpolation=cv2.INTER_LINEAR)


def compose(fr, lay, z):
    H, W = fr.shape[:2]
    m = lay["mode"]
    if m == "track":
        ch = H / z
        cw = ch * OW / OH
        cy = H / 2 if z <= 1.001 else H * 0.44
        return _crop(fr, lay["x"] * W, cy, cw, ch, OW, OH)
    if m == "split":
        half = OH // 2
        ch = min(H * 0.95, max(H * 0.45, lay.get("fh", 0.3) * H * 3.0))
        cw = ch * OW / half
        if cw > W / 2 + 40:
            cw = W / 2
            ch = cw * half / OW
        cy = lay.get("y", 0.4) * H + ch * 0.08
        top = _crop(fr, lay["x1"] * W, cy, cw, ch, OW, half)
        bot = _crop(fr, lay["x2"] * W, cy, cw, ch, OW, OH - half)
        out = np.vstack([top, bot])
        out[half - 3:half + 3] = 0
        return out
    if m == "fit_vertical":
        return _cover(fr, OW, OH)
    # fit: sharp full frame over blurred, darkened copy
    small = _cover(fr, OW // 8, OH // 8)
    bg = cv2.GaussianBlur(small, (0, 0), 6)
    bg = (cv2.resize(bg, (OW, OH)) * 0.55).astype(np.uint8)
    fw = int(OW * z)
    fh = int(H * fw / W)
    fg = cv2.resize(fr, (fw, fh), interpolation=cv2.INTER_LINEAR)
    if fw > OW:
        x0 = (fw - OW) // 2
        fg = fg[:, x0:x0 + OW]
    y = int(OH * 0.45 - fg.shape[0] / 2)
    y0, y1 = max(0, y), min(OH, y + fg.shape[0])
    bg[y0:y1, :fg.shape[1]] = fg[y0 - y:y1 - y]
    return bg


class BrollReader:
    def __init__(self, path, dur, fps):
        self.path, self.dur, self.fps = Path(path), dur, fps
        self.frames = []
        if self.path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            self.img = cv2.imread(str(self.path))
        else:
            self.img = None
            vf = f"scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},fps={fps}"
            p = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-ss", "0.5", "-i", str(path),
                                "-t", f"{dur + 0.2:.2f}", "-vf", vf, "-an", "-f", "rawvideo",
                                "-pix_fmt", "bgr24", "-"], capture_output=True)
            n = OW * OH * 3
            raw = p.stdout
            self.frames = [np.frombuffer(raw[i:i + n], np.uint8).reshape(OH, OW, 3)
                           for i in range(0, len(raw) - n + 1, n)]

    def get(self, local_t):
        prog = min(1.0, local_t / max(0.1, self.dur))
        if self.img is not None:  # Ken Burns
            z = 1.0 + 0.12 * prog
            base = _cover(self.img, int(OW * z), int(OH * z))
            y, x = (base.shape[0] - OH) // 2, (base.shape[1] - OW) // 2
            fr = base[y:y + OH, x:x + OW]
        else:
            if not self.frames:
                return None
            fr = self.frames[min(len(self.frames) - 1, int(local_t * self.fps))]
        if local_t < 0.18:  # snap-zoom transition in
            z = 1.18 - (local_t / 0.18) * 0.18
            fr = _crop(fr, OW / 2, OH / 2, OW / z, OH / z, OW, OH)
        return fr


def zoom_curve(words, total, emphasis_times, seed, strength=1.0):
    """Alternating 'jump zooms' every few seconds + smooth punch-ins on emphasis words."""
    rnd = random.Random(seed)
    jumps = []  # (t, level)
    level, nxt = 1.0, rnd.uniform(2.5, 4.0)
    for w in words:
        if w["s"] >= nxt:
            level = 1.08 if level == 1.0 else 1.0
            jumps.append((w["s"], level))
            nxt = w["s"] + rnd.uniform(3.0, 5.0)

    def z(t):
        base = 1.0
        for jt, lv in jumps:
            if jt <= t:
                base = lv
            else:
                break
        extra = 0.0
        for a, b in emphasis_times:
            if a - 0.01 <= t <= b + 0.6:
                k = min(1.0, (t - a) / 0.15) if t < a + 0.15 else (1.0 if t <= b + 0.35 else 1 - (t - b - 0.35) / 0.25)
                k = max(0.0, k)
                extra = max(extra, 0.08 * (k * k * (3 - 2 * k)))
        return 1.0 + (base + extra - 1.0) * strength
    return z


# ---------------------------------------------------------------- audio
def mix_audio(voice_src, total, mood, out, broll_times, music_vol, seed, wd):
    inputs = ["-i", voice_src]
    fc = ["[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100,aformat=channel_layouts=stereo,asplit=2[voice][sc]"]
    mix = ["[voice]"]
    if mood and mood != "none" and music_vol > 0:
        track = music.pick_track(mood, total, wd, seed)
        log("music:", Path(track).name)
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        fc.append(f"[1:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.3f},"
                  f"volume={music_vol},afade=t=in:d=0.8,afade=t=out:st={max(0, total - 1.5):.3f}:d=1.5[mus]")
        fc.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350:makeup=1[md]")
        mix.append("[md]")
    else:
        fc[0] = fc[0].replace(",asplit=2[voice][sc]", "[voice]")
    if broll_times:
        wpath = Path(wd) / "whoosh.wav"
        if not wpath.exists():
            music.whoosh(wpath)
        for i, t in enumerate(broll_times):
            idx = sum(1 for x in inputs if x == "-i")
            inputs += ["-i", str(wpath)]
            ms = max(0, int((t - 0.28) * 1000))
            fc.append(f"[{idx}:a]volume=0.35,adelay={ms}|{ms}[w{i}]")
            mix.append(f"[w{i}]")
    fc.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,alimiter=limit=0.95[out]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]", "-t", f"{total:.3f}",
         "-c:a", "aac", "-b:a", "192k", out])


# ---------------------------------------------------------------- main
def render_clip(wd, clip, out_dir, caption_model="large-v3-turbo", style="bold", music_vol=0.10,
                progress_bar=True, fps_cap=30, vocab=None):
    wd = Path(wd)
    src = wd / "source.mp4"
    tr = read_json(wd / "transcript.json")
    cid = str(clip.get("id", "clip"))
    tmp = wd / f"_tmp_{cid}"
    tmp.mkdir(exist_ok=True)
    start, end = snap(tr["words"], float(clip["start"]), float(clip["end"]))
    dur = end - start
    log(f"clip {cid}: {start:.1f}-{end:.1f} ({dur:.1f}s) '{clip.get('title', '')}'")

    if caption_model:
        words = caption_words(src, start, end, caption_model, tr.get("language"), vocab)
    else:
        words = [dict(w, s=w["s"] - start, e=w["e"] - start) for w in tr["words"]
                 if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]
    spans, words = keep_spans(words, dur, clip.get("cut_silences", True), clip.get("cut_fillers", True))
    tm = TimeMap(spans)
    log(f"  jump cuts: {len(spans) - 1}, {dur:.1f}s -> {tm.total:.1f}s")

    info = probe(src)
    fps = min(fps_cap, round(info["fps"])) or 30
    cut = tmp / "cut.mp4"
    cut_video(src, start, spans, cut, fps)
    total = probe(cut)["duration"]

    owords = [dict(w, s=tm(w["s"]), e=max(tm(w["s"]) + 0.05, tm(w["e"]))) for w in words]
    emphasis = {e.lower() for e in clip.get("emphasis", [])}
    emph_times = [(w["s"], w["e"]) for w in owords if _norm(w["w"]) in emphasis]

    # b-roll
    bwins, pops = [], []
    for b in clip.get("broll", []):
        t0 = tm(float(b["at"]) - start)
        d = float(b.get("dur", 2.5))
        media = broll_mod.find(b["query"]) if b.get("query") else None
        if media:
            bwins.append((t0, min(total, t0 + d), media))
        elif b.get("pop"):
            pops.append((t0, b["pop"]))
        else:
            log(f"  no b-roll for '{b.get('query')}' (add PEXELS_API_KEY or files in assets/broll/) -> zoom instead")
            emph_times.append((t0, t0 + 0.8))
    for p in clip.get("pops", []):
        pops.append((tm(float(p["at"]) - start), p["text"]))
    emph_times.sort()

    # captions + hook
    ass = tmp / "captions.ass"
    log("  reframing (face + active-speaker tracking)...")
    keys = reframe.plan(reframe.analyze(cut))
    split_share = sum(1 for k in keys if k["mode"] == "split") / max(1, len(keys))
    captions.build_ass(owords, ass, hook=clip.get("hook"), hook_seconds=float(clip.get("hook_seconds", 4.5)),
                       total=total, style=style, caption_y=0.5 if split_share > 0.5 else 0.70,
                       emphasis=emphasis, keywords=pops)

    # audio
    mix = tmp / "mix.m4a"
    mix_audio(str(cut), total, clip.get("music", "chill"), mix, [w[0] for w in bwins], music_vol,
              hash(cid) & 0xFFFF, tmp)

    # video
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{cid}_{re.sub(r'[^A-Za-z0-9]+', '_', clip.get('title', 'clip'))[:40].strip('_')}.mp4"
    out = out_dir / name
    # low-res sources pixelate when zoomed: scale zoom strength by source resolution
    zf = zoom_curve(owords, total, emph_times, hash(cid) & 0xFFFF,
                    strength=float(np.clip((info["height"] - 360) / 360, 0, 1)))
    dec_h = min(1080, info["height"])
    dec_w = int(round(info["width"] * dec_h / info["height"] / 2) * 2)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(cut), "-vf", f"scale={dec_w}:{dec_h}",
                            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    vf = f"ass={ass}:fontsdir={FONTS}"
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{OW}x{OH}", "-r", str(fps), "-i", "-", "-i", str(mix), "-vf", vf,
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-profile:v", "high", "-c:a", "copy", "-shortest", "-movflags", "+faststart",
                            str(out)], stdin=subprocess.PIPE)
    n = dec_w * dec_h * 3
    i = 0
    readers = {}
    nframes = int(total * fps)
    while True:
        buf = dec.stdout.read(n)
        if len(buf) < n:
            break
        t = i / fps
        fr = np.frombuffer(buf, np.uint8).reshape(dec_h, dec_w, 3)
        outf = None
        for j, (a, b, media) in enumerate(bwins):
            if a <= t < b:
                if j not in readers:
                    readers[j] = BrollReader(media, b - a, fps)
                outf = readers[j].get(t - a)
                break
            if t >= b and j in readers:
                readers.pop(j)
        if outf is None:
            lay = reframe.at(keys, t)
            outf = compose(fr, lay, 1.0 if lay["mode"] == "split" else zf(t))
        if progress_bar:
            outf = outf.copy() if not outf.flags.writeable else outf
            outf[0:12, :int(OW * min(1.0, t / max(0.1, total)))] = (0, 229, 255)
        enc.stdin.write(np.ascontiguousarray(outf).tobytes())
        i += 1
        if i % (fps * 10) == 0:
            log(f"  rendering {i}/{nframes} frames")
    dec.wait()
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("encoder failed")
    meta = {k: clip.get(k) for k in ("title", "hook", "caption", "hashtags", "why", "score")}
    meta.update(file=str(out), start=start, end=end, duration=round(total, 2))
    credits = [c for c in (broll_mod.credit_for(m) for _, _, m in bwins) if c]
    if credits:
        meta["broll_credits"] = credits
    write_json(out.with_suffix(".json"), meta)
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    log(f"  done -> {out}")
    return out
