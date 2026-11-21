import json
import subprocess
import sys
from pathlib import Path


def log(*a):
    print("[clipper]", *a, file=sys.stderr, flush=True)


def run(cmd, **kw):
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd[:6])}...\n{r.stderr[-3000:]}")
    return r.stdout


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,width,height,r_frame_rate",
               "-of", "json", path])
    d = json.loads(out)
    info = {"duration": float(d["format"]["duration"]), "has_audio": False}
    for s in d["streams"]:
        if s["codec_type"] == "video" and "width" not in info:
            num, den = s["r_frame_rate"].split("/")
            info.update(width=int(s["width"]), height=int(s["height"]),
                        fps=float(num) / float(den or 1))
        if s["codec_type"] == "audio":
            info["has_audio"] = True
    return info


def read_json(p):
    return json.loads(Path(p).read_text())


def write_json(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def ts(sec):
    sec = max(0, sec)
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
