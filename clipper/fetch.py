"""Step 1: get the source video (YouTube link or local file) into work/<id>/source.mp4."""
import hashlib
import re
import shutil
import sys
from pathlib import Path

from . import ROOT, WORK
from .util import log, run, write_json, probe


def _slug(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:60] or "video"


def _yt_id(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else hashlib.md5(url.encode()).hexdigest()[:11]


def fetch(src, cookies=None, max_height=1080):
    """Returns the work directory containing source.mp4 + meta.json."""
    p = Path(src)
    if p.exists():
        wd = WORK / _slug(p.stem)
        wd.mkdir(parents=True, exist_ok=True)
        out = wd / "source.mp4"
        if not out.exists():
            if p.suffix.lower() == ".mp4":
                shutil.copy(p, out)
            else:
                run(["ffmpeg", "-y", "-i", p, "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                     "-c:a", "aac", "-b:a", "192k", out])
        write_json(wd / "meta.json", {"source": str(p), "title": p.stem, **probe(out)})
        log("local file ready:", out)
        return wd

    vid = _yt_id(src)
    wd = WORK / vid
    wd.mkdir(parents=True, exist_ok=True)
    out = wd / "source.mp4"
    if out.exists():
        log("already downloaded:", out)
        return wd

    cookies = cookies or (ROOT / "cookies.txt" if (ROOT / "cookies.txt").exists() else None)
    base = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--js-runtimes", "node",
            "-f", f"bv*[height<={max_height}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={max_height}]+ba/b",
            "--merge-output-format", "mp4", "-o", str(wd / "source.%(ext)s"),
            "--write-info-json", "--no-write-comments"]
    if cookies:
        base += ["--cookies", str(cookies)]
    attempts = [[], ["--extractor-args", "youtube:player_client=mweb,web_safari"],
                ["--extractor-args", "youtube:player_client=tv,web_embedded"]]
    err = None
    for extra in attempts:
        try:
            log("downloading", src, extra or "")
            run(base + extra + [src])
            err = None
            break
        except RuntimeError as e:
            err = e
    if err:
        msg = str(err)
        if "not a bot" in msg or "403" in msg:
            raise SystemExit(
                "YouTube blocked this server's IP (common on cloud machines).\n"
                "Fix (free): export cookies from your browser while logged into YouTube using the\n"
                "'Get cookies.txt LOCALLY' extension, save as cookies.txt in the repo root, and retry.\n"
                "Or download the video yourself and pass the file path instead of the URL.\n\n" + msg[-800:])
        raise err
    if not out.exists():
        cand = sorted(wd.glob("source.*"))
        vids = [c for c in cand if c.suffix in (".mkv", ".webm", ".mp4")]
        if not vids:
            raise SystemExit("download produced no video")
        run(["ffmpeg", "-y", "-i", vids[0], "-c:v", "libx264", "-crf", "18", "-preset", "fast",
             "-c:a", "aac", "-b:a", "192k", out])
    title = src
    info = wd / "source.info.json"
    if info.exists():
        import json
        d = json.loads(info.read_text())
        title = d.get("title", src)
        write_json(wd / "meta.json", {"source": src, "title": title, "channel": d.get("channel"),
                                      "chapters": d.get("chapters"), **probe(out)})
        info.unlink()
    else:
        write_json(wd / "meta.json", {"source": src, "title": title, **probe(out)})
    log("downloaded:", out)
    return wd
