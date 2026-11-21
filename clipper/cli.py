import argparse
from pathlib import Path

from . import ROOT
from .util import log, read_json


def main():
    ap = argparse.ArgumentParser(prog="python -m clipper", description="Podcast -> viral vertical clips (free, local)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prep", help="download + transcribe; then read work/<id>/transcript.txt and write clips.json")
    p.add_argument("src", help="YouTube URL or local video file")
    p.add_argument("--model", default="small", help="whisper model for the full transcript (small|medium|large-v3-turbo)")
    p.add_argument("--cookies", help="cookies.txt for YouTube if the server IP is blocked")
    p.add_argument("--lang", default=None)

    r = sub.add_parser("render", help="render clips from a clips.json")
    r.add_argument("workdir")
    r.add_argument("--clips", default=None, help="defaults to <workdir>/clips.json")
    r.add_argument("--only", default=None, help="comma-separated clip ids")
    r.add_argument("--caption-model", default="large-v3-turbo", help="re-transcribe each clip for perfect captions ('' to skip)")
    r.add_argument("--style", default="bold", choices=["bold", "clean"])
    r.add_argument("--music-vol", type=float, default=0.10)
    r.add_argument("--no-progress-bar", action="store_true")
    r.add_argument("--out", default=None, help="defaults to output/<workdir name>/")

    a = sub.add_parser("auto", help="fully automatic (heuristic picks; Claude-curated clips are better)")
    a.add_argument("src")
    a.add_argument("-n", type=int, default=5)
    a.add_argument("--cookies")

    m = sub.add_parser("music", help="preview the generated music for a mood")
    m.add_argument("mood")
    m.add_argument("--seconds", type=float, default=30)
    m.add_argument("--out", default="music_preview.wav")

    args = ap.parse_args()
    if args.cmd == "prep":
        from .fetch import fetch
        from .transcribe import transcribe
        wd = fetch(args.src, cookies=args.cookies)
        transcribe(wd, args.model, args.lang)
        print(wd)
    elif args.cmd in ("render", "auto"):
        from .render import render_clip
        if args.cmd == "auto":
            from .analyze import auto_pick
            from .fetch import fetch
            from .transcribe import transcribe
            wd = fetch(args.src, cookies=args.cookies)
            transcribe(wd)
            clips_path = auto_pick(wd, args.n)
            opts = dict(caption_model="large-v3-turbo", style="bold", music_vol=0.10, progress_bar=True)
            out_dir = ROOT / "output" / wd.name
        else:
            wd = Path(args.workdir)
            clips_path = Path(args.clips) if args.clips else wd / "clips.json"
            opts = dict(caption_model=args.caption_model or None, style=args.style,
                        music_vol=args.music_vol, progress_bar=not args.no_progress_bar)
            out_dir = Path(args.out) if args.out else ROOT / "output" / wd.name
        spec = read_json(clips_path)
        clips = spec["clips"]
        opts["vocab"] = spec.get("vocab")
        if getattr(args, "only", None):
            keep = set(args.only.split(","))
            clips = [c for c in clips if str(c["id"]) in keep]
        done = []
        for c in clips:
            try:
                done.append(render_clip(wd, c, out_dir, **opts))
            except Exception as e:  # keep going with the other clips
                log(f"clip {c.get('id')} FAILED: {e}")
        for d in done:
            print(d)
    elif args.cmd == "music":
        from .music import generate
        generate(args.mood, args.seconds, args.out)
        print(args.out)
