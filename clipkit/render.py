"""Renderer: turns a clip spec (JSON) into a finished 1080x1920 clip. usage: python3 render.py spec.json"""
import bisect, json, math, re, subprocess, sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
import editor as M

CODE = Path(__file__).resolve().parent
ASSETS = CODE / "assets"
CAP_FONT = str(ASSETS / "fonts" / "Montserrat-Black.ttf")
HOOK_FONT = str(ASSETS / "fonts" / "Anton-Regular.ttf")
EMOJI = ASSETS / "emoji"
SFX = ASSETS / "sfx"
OW, OH, FPS = M.OW, M.OH, M.FPS
CAP_Y, CAP_Y_SPLIT = 1010, 960
HOOK_TOP = 300
HOOK_CY = None            # None = hook at the top (user preference)
HOOK_TOP_Y = 255          # just below TikTok/Shorts top bar
HOOK_DROP = 430
PALETTE = [(34, 197, 94), (139, 92, 246), (249, 115, 22), (236, 72, 153), (14, 165, 233)]
YEL = (255, 230, 0)
THEME = {"accent": None}            # set per spec: {"accent": [r,g,b]} -> brand colour theme
_f = {}


def font(path, size):
    k = (path, size)
    if k not in _f:
        _f[k] = ImageFont.truetype(path, size)
    return _f[k]


def emoji_img(key, size):
    return Image.open(EMOJI / f"{key}.png").convert("RGBA").resize((size, size), Image.LANCZOS)


def ease_back(u, over=1.6):
    """0..1 -> overshooting ease-out."""
    u = min(max(u, 0.0), 1.0) - 1
    return 1 + u * u * ((over + 1) * u + over)


def scale_img(im, s, rot=0.0):
    if s <= 0.01:
        return None
    out = im if abs(s - 1) < 0.005 else im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                                                  Image.BILINEAR)
    if abs(rot) > 0.05:
        out = out.rotate(rot, resample=Image.BICUBIC, expand=True)
    return out


def fade(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * max(0.0, a))))
    return im


def paste(frame, rgba, cx, cy):
    if rgba is None:
        return
    a = np.asarray(rgba)
    h, w = a.shape[:2]
    x0, y0 = int(cx - w / 2), int(cy - h / 2)
    x1, y1, x2, y2 = max(0, x0), max(0, y0), min(OW, x0 + w), min(OH, y0 + h)
    if x2 <= x1 or y2 <= y1:
        return
    sub = a[y1 - y0:y2 - y0, x1 - x0:x2 - x0].astype(np.float32)
    al = sub[..., 3:4] / 255.0
    roi = frame[y1:y2, x1:x2].astype(np.float32)
    frame[y1:y2, x1:x2] = (sub[..., :3][..., ::-1] * al + roi * (1 - al)).astype(np.uint8)


def shadowed(im, blur=10, off=(8, 12), strength=0.6):
    pad = blur * 3
    out = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 255))
    sh.putalpha(im.getchannel("A").point(lambda v: int(v * strength)))
    out.alpha_composite(sh, (pad + off[0], pad + off[1]))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(im, (pad, pad))
    return out


# ------------------------------------------------------------------ hook
_fdet = None


def render_hook(lines, emoji=None, max_size=112):
    """each line gets its own (largest fitting) size so the block uses the full width."""
    imgs = []
    for i, (t, style) in enumerate(lines):
        e = emoji if (emoji and i == len(lines) - 1) else None
        size = max_size
        while size > 60:
            f = font(HOOK_FONT, size)
            cap_h = f.getbbox("HGQ")[3] - f.getbbox("HGQ")[1]
            if f.getlength(t) + 70 + (cap_h * 1.3 if e else 0) <= 1000:
                break
            size -= 2
        f = font(HOOK_FONT, size)
        top, bot = f.getbbox("HGQ")[1], f.getbbox("HGQ")[3]
        cap_h = bot - top
        pad_x, pad_y = 34, int(size * 0.15)
        tw = f.getlength(t)
        w = int(tw + 2 * pad_x + (cap_h * 1.3 if e else 0))
        h = cap_h + 2 * pad_y
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        A = THEME["accent"]
        styles = {"white": ((255, 255, 255, 255), (0, 0, 0)), "yellow": ((255, 230, 0, 255), (0, 0, 0)),
                  "red": ((235, 40, 40, 255), (255, 255, 255))}
        if A:
            styles.update({"accent": (tuple(A) + (255,), (0, 0, 0)), "black": ((12, 12, 12, 255), tuple(A)),
                           "yellow": (tuple(A) + (255,), (0, 0, 0)), "red": ((12, 12, 12, 255), tuple(A))})
        bg, fg = styles[style]
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(size * 0.2), fill=bg)
        d.text((pad_x, pad_y - top), t, font=f, fill=fg)
        if e:
            em = emoji_img(e, int(cap_h * 1.25))
            im.alpha_composite(em, (int(pad_x + tw + cap_h * 0.08), (h - em.height) // 2))
        imgs.append(im)
    gap = 14
    W = max(i.width for i in imgs)
    H = sum(i.height for i in imgs) + gap * (len(imgs) - 1)
    block = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y = 0
    for im in imgs:
        block.alpha_composite(im, ((W - im.width) // 2, y))
        y += im.height + gap
    return shadowed(block).rotate(-2, resample=Image.BICUBIC, expand=True)


# ------------------------------------------------------------------ captions
def make_chunks(words, max_words=2, max_chars=12, gap=0.25):
    out, cur = [], []
    for w in words:
        if cur:
            n = sum(len(M.cap_text(x["w"])) + 1 for x in cur) + len(M.cap_text(w["w"]))
            if (len(cur) >= max_words or n > max_chars or w["s"] - cur[-1]["e"] > gap
                    or re.search(r"[.?!,]$", cur[-1]["w"])):
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


_cc = {}


def render_caption(ci, toks, active, keywords, bounce):
    key = (ci, active, round(bounce, 2))
    if key in _cc:
        return _cc[key]
    base = 158
    f0 = font(CAP_FONT, base)
    total = sum(f0.getlength(t) for t in toks) + f0.getlength(" ") * (len(toks) - 1) + 60 * len(toks)
    size = int(base * min(1.0, 980 / total))
    f = font(CAP_FONT, size)
    fa = font(CAP_FONT, max(10, int(size * bounce)))
    col_box = tuple(THEME["accent"]) if THEME["accent"] else PALETTE[ci % len(PALETTE)]
    kw_col = tuple(THEME["accent"]) if THEME["accent"] else YEL
    space = f.getlength(" ")
    widths = [(fa if j == active else f).getlength(t) for j, t in enumerate(toks)]
    padx = int(size * 0.18)
    W = int(sum(widths) + space * (len(toks) - 1) + 2 * padx * len(toks) + 60)
    H = int(size * 1.9 * max(1.0, bounce))
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 30
    sw = max(8, int(size * 0.09))
    for j, (t, w) in enumerate(zip(toks, widths)):
        ff = fa if j == active else f
        cx = x + padx + w / 2
        if j == active:
            bb = d.textbbox((cx, H / 2), t, font=ff, anchor="mm")
            d.rounded_rectangle([bb[0] - padx, bb[1] - int(size * 0.16), bb[2] + padx, bb[3] + int(size * 0.16)],
                                radius=int(size * 0.22), fill=col_box + (255,))
            if THEME["accent"]:
                d.text((cx, H / 2), t, font=ff, anchor="mm", fill=(0, 0, 0))
            else:
                d.text((cx, H / 2), t, font=ff, anchor="mm", fill=(255, 255, 255), stroke_width=int(sw * 0.6),
                       stroke_fill=(0, 0, 0))
        else:
            plain = re.sub(r"[^A-Z0-9$]", "", t)
            d.text((cx, H / 2), t, font=ff, anchor="mm", fill=kw_col if plain in keywords else (255, 255, 255),
                   stroke_width=sw, stroke_fill=(0, 0, 0))
        x += w + space + 2 * padx
    out = shadowed(im, blur=8, off=(6, 10), strength=0.7)
    _cc[key] = out
    return out


# ------------------------------------------------------------------ b-roll card
def card(frame_bgr, w=840, h=600, border=12, radius=44):
    img = M.cover(frame_bgr, w, h)
    im = Image.fromarray(img[..., ::-1]).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    im.putalpha(mask)
    framed = Image.new("RGBA", (w + 2 * border, h + 2 * border), (0, 0, 0, 0))
    ImageDraw.Draw(framed).rounded_rectangle([0, 0, framed.width - 1, framed.height - 1], radius=radius + border,
                                             fill=(255, 255, 255, 255))
    framed.alpha_composite(im, (border, border))
    return shadowed(framed, blur=14, off=(10, 16), strength=0.7)


def stamp(text, color):
    f = font(HOOK_FONT, 190)
    bb = f.getbbox(text)
    im = Image.new("RGBA", (bb[2] - bb[0] + 80, bb[3] - bb[1] + 80), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((40 - bb[0], 40 - bb[1]), text, font=f, fill=color, stroke_width=12,
                            stroke_fill=(0, 0, 0))
    return shadowed(im)


# ------------------------------------------------------------------ main
def main(spec_path):
    spec = json.load(open(spec_path))
    def res(p):
        q = Path(p)
        return str(q if q.is_absolute() or q.exists() else ASSETS / q)
    spec["music"] = res(spec["music"])
    for b in spec.get("broll", []):
        b["file"] = res(b["file"])
    if spec.get("logo"):
        spec["logo"]["file"] = res(spec["logo"]["file"])
    THEME["accent"] = spec.get("theme", {}).get("accent")
    _cc.clear()
    if spec.get("src"):
        M.SRC = spec["src"]
    if spec.get("sr"):                                   # AI super-resolution for low-res (720p) sources
        _orig_warp = getattr(M, "_orig_warp", M.warp)
        M._orig_warp = _orig_warp
        _sr = cv2.dnn_superres.DnnSuperResImpl_create()
        _sr.readModel(str(ASSETS / "sr" / "FSRCNN_x3.pb")); _sr.setModel("fsrcnn", 3)

        def warp_sr(fr, cx, cy, cw, ch, w, h):
            Hh, Ww = fr.shape[:2]
            cw, ch = min(cw, Ww), min(ch, Hh)
            if w / cw < 1.6:                              # little upscaling needed -> plain path
                return _orig_warp(fr, cx, cy, cw, ch, w, h)
            x0 = int(max(0, np.clip(cx - cw / 2, 0, Ww - cw) - 2)); y0 = int(max(0, np.clip(cy - ch / 2, 0, Hh - ch) - 2))
            x1 = int(min(Ww, x0 + cw + 5)); y1 = int(min(Hh, y0 + ch + 5))
            up = _sr.upsample(np.ascontiguousarray(fr[y0:y1, x0:x1]))
            b = cv2.GaussianBlur(up, (0, 0), 1.5); up = cv2.addWeighted(up, 1.5, b, -0.5, 0)
            return _orig_warp(up, (cx - x0) * 3, (cy - y0) * 3, cw * 3, ch * 3, w, h)
        M.warp = warp_sr
    name = spec["name"]
    wd = Path(spec.get("work_dir", Path(spec_path).parent)) / f"build_{name}"
    wd.mkdir(exist_ok=True)
    words = []
    for w in json.load(open(spec["words"])):
        if words and (w["w"].startswith(("-", ".", "%")) and w["w"][:2] != ". ") and w["s"] - words[-1]["e"] < 0.6:
            words[-1] = dict(words[-1], w=words[-1]["w"] + w["w"], e=w["e"])
        else:
            words.append(w)
    if spec.get("edit") == "v3":
        import edl2
        edl, kept_v2 = edl2.build3(words, spec["segments"], FPS, spec.get("drop_at", []), env=M._energy(), trust_aligner=spec.get("trust_aligner", False))
    elif spec.get("edit") == "v2":
        import edl2
        edl, kept_v2 = edl2.build(words, spec["segments"], M._energy(), FPS, spec.get("drop_at", []))
    else:
        edl, kept_v2 = M.build_edl(words, spec["segments"]), None
    mp = M.Map(edl)
    print(name, "pieces", len(edl), "duration", round(mp.total, 1), flush=True)
    if mp.total > spec.get("max_len", 31):
        raise SystemExit(f"too long: {mp.total:.1f}s")
    plan = []
    for a_, b_, *_ in sorted(spec["segments"]):                     # only scan the pieces we use
        plan += M.analyze(a_ - 0.3, b_ + 0.4)
    plan.sort(key=lambda p: p["t0"])
    # never open on a 1-3 frame sliver of another camera (it also shows on every loop): start on the new shot
    first_word = min((w["s"] for w in (kept_v2 or words)), default=edl[0][1])
    for p_ in plan:
        if edl[0][0] < p_["t0"] <= edl[0][0] + 0.3 and p_["t0"] < first_word - 0.02:
            n_ = round((edl[0][1] - p_["t0"]) * FPS)
            edl[0] = [edl[0][1] - n_ / FPS, edl[0][1]]
            mp = M.Map(edl)
            print("  start moved to camera cut", round(edl[0][0], 3), flush=True)
            break
    cutp = wd / "cut.mp4"
    M.cut(edl, cutp)

    ow = []
    for w in words:
        if (kept_v2 is not None and any(w is k for k in kept_v2)) or \
           (kept_v2 is None and any(s <= (w["s"] + w["e"]) / 2 < e for s, e in edl)):
            s = mp.out(w["s"])
            ow.append(dict(w, s=s, e=max(s + 0.08, mp.out(w["e"]))))
    for t, txt in spec.get("fixes", []):
        for w in ow:
            if ("s_ws" in w and abs(w["s_ws"] - t) < 0.04) or ("s_ws" not in w and abs(mp.out(t) - w["s"]) < 0.08):
                w["w"] = txt
    ow = sorted([w for w in ow if w["w"].strip()], key=lambda w: w["s"])
    chunks = make_chunks(ow)
    starts = [c[0]["s"] for c in chunks]
    keywords = {k.upper() for k in spec.get("keywords", [])}

    logo = None
    if spec.get("logo"):
        L = spec["logo"]
        li = Image.open(L["file"]).convert("RGBA")
        lw = int(L.get("width", 560))
        li = li.resize((lw, int(li.height * lw / li.width)), Image.LANCZOS)
        logo = (shadowed(li, blur=10, off=(4, 6), strength=0.85), L.get("cy", 1500))
        M.SPLIT_BOTTOM_OFFSET = 0.26          # keep the bottom speaker's face above the logo
    hl = spec["hook_lines"]
    if hl and isinstance(hl[0], list) and len(hl) == 1 and len(hl[0]) == 2 and hl[0][1] not in ("white", "yellow", "red"):
        hl = [[hl[0][0], "white"], [hl[0][1], "yellow"]]          # tolerate [["line 1", "line 2"]]
    hl = [[x, "white" if i == 0 else "yellow"] if isinstance(x, str) else x for i, x in enumerate(hl)]
    hook = render_hook([tuple(x) for x in hl], spec.get("hook_emoji"))
    hook_end = spec.get("hook_seconds", 3.6)
    pops = [(mp.out(p["at"]), emoji_img(p["emoji"], 230)) for p in spec.get("emoji_pops", [])]
    punches = [(0.0, None)] + [(mp.out(p["at"]), stamp(p["text"], tuple(p.get("color", THEME["accent"] or YEL))) if p.get("text") else None)
               for p in spec.get("punch", [])]

    brolls = []
    for b in spec.get("broll", []):
        t0, t1 = mp.out(b["from"]), mp.out(b["to"])
        if t0 < spec.get("hook_seconds", 3.6) + 0.4:        # never cover the hook with b-roll
            continue
        cap = cv2.VideoCapture(b["file"])
        cap.set(cv2.CAP_PROP_POS_MSEC, b.get("offset", 1.0) * 1000)
        sfps = cap.get(cv2.CAP_PROP_FPS) or 30
        fr = []
        while len(fr) < int((t1 - t0) * sfps) + 2:
            ok, f = cap.read()
            if not ok:
                break
            fr.append(f)
        brolls.append((t0, t1, fr, sfps, b.get("style", "card")))

    # ---- audio: voice + ducked music + sfx
    tot = mp.total
    sfx = [(t, "2358", 0.30) for t, _ in pops] + [(b[0] - 0.55, "1489", 0.45 if b[4] == "card" else 0.3) for k, b in enumerate(brolls)
           if k == 0 or b[0] - brolls[k - 1][1] > 0.6] + \
          [(t - 0.5, "1143", 0.9 if t == 0 else 0.75) for t, _ in punches]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", spec["music"], "-t", "120", "-ac", "1", "-ar", "8000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    ma = np.frombuffer(raw, np.float32)
    env = np.sqrt(np.convolve(ma ** 2, np.ones(8000 * 6) / (8000 * 6), "valid"))[::800]
    mstart = spec.get("music_start", float(np.argmax(env) * 0.1))
    inputs = ["-i", str(cutp), "-ss", f"{mstart:.2f}", "-stream_loop", "-1", "-i", spec["music"]]
    fc = [f"[0:a]highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=2,"
          f"loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000,aformat=channel_layouts=stereo,asplit=2[v][sc]",
          f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{tot:.3f},"
          f"loudnorm=I={spec.get('music_db', -25)}:TP=-6,"
          f"afade=t=out:st={max(0, tot - 1.2):.3f}:d=1.2[mu]",
          f"[mu][sc]sidechaincompress=threshold=0.04:ratio={spec.get('duck_ratio', 4)}:attack=30:release=450[md]"]
    labs = ["[v]", "[md]"]
    for k, (t, sid, vol) in enumerate(sfx):
        inputs += ["-i", str(SFX / f"{sid}.mp3")]
        ms = max(0, int(t * 1000))
        trim = f"atrim=start={-t:.3f},asetpts=PTS-STARTPTS," if t < 0 else ""
        fc.append(f"[{k + 2}:a]{trim}aresample=48000,aformat=channel_layouts=stereo,volume={vol},adelay={ms}|{ms}[s{k}]")
        labs.append(f"[s{k}]")
    fc.append(f"{''.join(labs)}amix=inputs={len(labs)}:normalize=0:duration=first,alimiter=limit=0.89[out]")
    mix = wd / "mix.m4a"
    M.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(fc), "-map", "[out]",
           "-t", f"{tot:.3f}", "-c:a", "aac", "-b:a", "192k", mix])

    # ---- video
    info = json.loads(M.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                             "stream=width,height", "-of", "json", cutp]))["streams"][0]
    W, H = info["width"], info["height"]
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", cutp, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}",
                            "-r", str(FPS), "-i", "-", "-i", mix, "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-tune", "film",
                            "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest",
                            "-movflags", "+faststart", spec["out"]], stdin=subprocess.PIPE)
    i = 0
    prev_key, base_z, key_start, jumps = None, 1.0, 0.0, 0
    _last = None
    _hold_frames, _held = set(), None
    if spec.get("edit") == "v3":
        keys_seq = []
        for fi in range(int(mp.total * FPS) + 1):
            ts_, pc_ = mp.src(fi / FPS)
            keys_seq.append((M.shot_at(plan, ts_)[0], pc_))
        run_start = 0
        for fi in range(1, len(keys_seq) + 1):
            if fi == len(keys_seq) or keys_seq[fi][0] != keys_seq[run_start][0]:
                if run_start > 0 and (fi - run_start) < 0.5 * FPS:      # sliver of another camera angle
                    _hold_frames.update(range(run_start, fi))
                run_start = fi
    while True:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = i / FPS
        fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        ts, piece = mp.src(t)
        si, shot = M.shot_at(plan, ts)
        if (si, piece) != prev_key:
            if prev_key is not None and prev_key[0] == si:
                jumps += 1
                base_z = 1.0 if spec.get("edit") == "v3" else (1.06 if jumps % 2 else 1.0)
            else:
                base_z, jumps = 1.0, 0
            key_start, prev_key = t, (si, piece)
        # punch-in on impacts
        pz, shake = 0.0, (0, 0)
        for pt, _ in punches:
            if pt <= t < pt + 0.45:
                k = 1 - (t - pt) / 0.45
                pz = max(pz, 0.08 * k)
                shake = (int(14 * k * math.sin(t * 90)), int(10 * k * math.cos(t * 77)))
        z = base_z + min(0.03, (t - key_start) * 0.006) + pz
        hf = spec.get("hook_focus")                      # "left"/"right": while the hook is up, one big face, no split
        if hf and shot["mode"] == "split" and t < hook_end + 0.3:
            Hs = fr.shape[0]
            pr = sorted([(shot["x1"], shot["y1"]), (shot["x2"], shot["y2"])])[1 if hf == "right" else 0]
            ch_p = min(Hs * 0.62, shot["fh"] * Hs * 3.2)
            img = M.compose(fr, {"mode": "single", "x": pr[0], "y": pr[1]}, max(1.002, Hs / (2.0 * ch_p)) * (1 + pz))
        else:
            img = M.compose(fr, shot, z if shot["mode"] != "split" else 1.0 + pz)
        # while the hook is up (at the top), the shot sits lower over a blurred extension of itself,
        # so the hook never covers the face; then it glides up to full frame
        hk_k = 1.0
        if t < hook_end + 0.45:
            hk_k = 0.0 if t < hook_end else min(1.0, (t - hook_end) / 0.45)
            hk_k = hk_k * hk_k * (3 - 2 * hk_k)
            drop = int(HOOK_DROP * (1 - hk_k))
            if spec.get("edit") == "v3" and t >= hook_end:
                full_img = img.copy()
                drop = HOOK_DROP if t < hook_end + 0.3 else 0
            if drop > 0:
                strip = img[:OH // 9]                                   # scenery above the head only
                small = cv2.resize(strip, (OW // 16, 12), interpolation=cv2.INTER_AREA)
                bg = cv2.resize(cv2.GaussianBlur(small, (0, 0), 2.0), (OW, OH // 2), interpolation=cv2.INTER_CUBIC)
                bg = (bg * 0.5).astype(np.uint8)
                out_ = np.empty_like(img)
                out_[:drop] = cv2.resize(bg, (OW, drop))
                out_[drop:] = img[:OH - drop]
                img = out_
                if spec.get("edit") == "v3" and t >= hook_end:
                    a_ = min(1.0, (t - hook_end) / 0.3)
                    img = cv2.addWeighted(full_img, a_, img, 1 - a_, 0)
        if shake != (0, 0):
            img = np.roll(img, shake, axis=(0, 1))
        if spec.get("edit") == "v3":
            if prev_key is not None and t - key_start < 0.3 and _held is not None and i not in _hold_frames:
                global _fdet
                if _fdet is None:
                    _fdet = cv2.FaceDetectorYN.create(str(M.ASSETS / "models" / "face_detection_yunet_2023mar.onnx"), "", (270, 480), 0.6, 0.3, 50)
                _sm = cv2.resize(img, (270, 480))
                if _fdet.detect(_sm)[1] is None:          # mid-dissolve / empty frame: keep the last good picture
                    _hold_frames.add(i)
            if i in _hold_frames and _held is not None:
                img = _held.copy()
            else:
                _held = img.copy()
        img = np.ascontiguousarray(M.sharpen(img))
        for pt, _ in punches:                        # white flash
            if pt > 0 and pt <= t < pt + 0.1:
                a = 0.55 * (1 - (t - pt) / 0.1)
                img = cv2.addWeighted(img, 1 - a, np.full_like(img, 255), a, 0)

        # b-roll cards
        for t0, t1, bfr, bfps, style in brolls:
            if t0 <= t < t1 and bfr and style == "full":
                # full-screen cutaway: snap-zoom in, slow push, quick out
                fb = bfr[min(len(bfr) - 1, int((t - t0) * bfps))]
                u = (t - t0) / 0.14
                zz = (1.25 - 0.25 * ease_back(u, 1.2)) if u < 1 else 1.0 + 0.06 * (t - t0) / max(0.1, t1 - t0)
                full = M.cover(fb, OW, OH, zz)
                a = min(1.0, (t1 - t) / 0.08)
                img = full if a >= 1 else cv2.addWeighted(full, a, img, 1 - a, 0)
                img = np.ascontiguousarray(img)
                continue
            if t0 <= t < t1 and bfr:
                c = card(bfr[min(len(bfr) - 1, int((t - t0) * bfps))])
                u_in, u_out = (t - t0) / 0.28, (t1 - t) / 0.2
                s = ease_back(u_in) if u_in < 1 else (max(0.0, u_out) if u_out < 1 else 1.0)
                rot = -4 + 2 * math.sin((t - t0) * 2.2) + (1 - min(1, u_in)) * -10
                paste(img, scale_img(c, s, rot), OW / 2, 560 + 10 * math.sin((t - t0) * 3))

        # captions (exactly one chunk at a time)
        ci = bisect.bisect_right(starts, t) - 1
        if ci >= 0:
            chk = chunks[ci]
            end = min(chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else 1e9, chk[-1]["e"] + 0.5)
            if t < end:
                active = max([j for j, w in enumerate(chk) if w["s"] <= t + 0.02] or [0])
                since = t - chk[active]["s"]
                bounce = 1.0 + 0.22 * max(0.0, 1 - since / 0.13) if since >= 0 else 1.0
                im = render_caption(ci, [M.cap_text(w["w"]) for w in chk], active, keywords,
                                    round(bounce * 20) / 20)
                s = 0.72 + 0.28 * ease_back((t - chk[0]["s"]) / 0.1, 2.0)
                rot = (-3 if ci % 2 else 3) * (1 - min(1, (t - chk[0]["s"]) / 0.2)) + (-1.5 if ci % 2 else 1.5)
                cy = CAP_Y_SPLIT if shot["mode"] == "split" else CAP_Y
                if shot["mode"] != "split":
                    cy += int(HOOK_DROP * (0.6 if logo else 0.75) * (1 - hk_k))
                paste(img, scale_img(im, max(0.3, s), rot), OW / 2, cy)

        # emoji stickers
        for pt, em in pops:
            if pt <= t < pt + 1.4:
                u = (t - pt) / 0.3
                s = ease_back(u, 2.2) * (1 - max(0, (t - pt - 1.2) / 0.2))
                rot = 12 * math.sin((t - pt) * 9) * math.exp(-(t - pt) * 1.5)
                cy = (CAP_Y_SPLIT if shot["mode"] == "split" else CAP_Y) - 250 - 30 * min(1, (t - pt))
                paste(img, scale_img(em, max(0.05, s), rot), OW / 2 + 260, cy)
        # punch stamps
        for pt, st in punches:
            if st is not None and pt <= t < pt + 1.1:
                s = 1.6 - 0.6 * ease_back((t - pt) / 0.18, 1.2)
                a = 1 - max(0, (t - pt - 0.9) / 0.2)
                paste(img, fade(scale_img(st, s, 6), a), OW / 2, 1240 if logo else 1290)
        # hook: drop in with bounce, pop out
        if t < hook_end + 0.2:
            if t < hook_end:
                yoff = 0
                hk = scale_img(hook, 1.0 + 0.10 * max(0.0, 1 - t / 0.15))
            else:
                k = (t - hook_end) / 0.2
                yoff, hk = 0, fade(scale_img(hook, 1 + 0.25 * k), 1 - k)
            if hk is not None:
                cy_h = HOOK_CY if HOOK_CY else HOOK_TOP_Y + hook.height / 2
                paste(img, hk, OW / 2, cy_h + yoff)
        if logo:                                      # brand logo: every frame, always on top
            paste(img, logo[0], OW / 2, logo[1])
        # v3: soften same-camera jump cuts with a 3-frame blend from the last frame before the cut
        if spec.get("edit") == "v3":
            if prev_key is not None and jumps and key_start <= t < key_start + 3 / FPS and _last is not None:
                k = (t - key_start) * FPS
                a_ = [0.6, 0.3, 0.1][min(2, int(round(k)))]
                img = cv2.addWeighted(_last, a_, img, 1 - a_, 0)
            _last = img.copy() if t >= key_start + 2 / FPS or _last is None else _last
        if i == 0:
            _first_out = img.copy()
        LOOP = float(spec.get("loop", 0.45))                 # seamless loop: last frames dissolve into frame 1
        if LOOP > 0 and t > tot - LOOP and i > 0:
            a_ = min(1.0, (t - (tot - LOOP)) / LOOP)
            a_ = a_ * a_ * (3 - 2 * a_)
            img = cv2.addWeighted(_first_out, a_, img, 1 - a_, 0)
        enc.stdin.write(img.tobytes())
        i += 1
    dec.wait()
    enc.stdin.close()
    enc.wait()
    sp = float(spec.get("speed", 1.0))
    if abs(sp - 1.0) > 0.001:                       # natural-pitch speed-up of the finished clip
        tmp_out = str(spec["out"]) + ".speed.mp4"
        M.run(["ffmpeg", "-y", "-v", "error", "-i", spec["out"], "-filter_complex",
               f"[0:v]setpts=PTS/{sp},fps={FPS}[v];[0:a]atempo={sp}[a]", "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-tune", "film", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp_out])
        Path(tmp_out).replace(spec["out"])
    print("done", spec["out"], round(i / FPS / sp, 1), "s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
