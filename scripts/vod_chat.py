"""Twitch VOD chat replay: download it and rank the moments where chat exploded.

usage: python vod_chat.py <twitch.tv/videos/ID or ID> [--top 10] [--out chat.jsonl]

Downloads the full chat replay (no account needed) by stepping through the VOD by timestamp, then scores every
10 s bucket against the chat rate around it (+-5 min). Giveaway/command spam, number guessing and links are
ignored, so a giveaway does not look like a moment. Prints the top spikes with sample messages; the event itself
is usually 10-30 s BEFORE the spike (stream delay + reaction time).

Writes chat.jsonl ({t, user, text}, t = seconds into the VOD) and spikes.json next to it.
"""
import argparse, collections, json, re, statistics, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

GQL = "https://gql.twitch.tv/gql"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch's public web client id (same one yt-dlp uses)
HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"  # VideoCommentsByOffsetOrCursor
NOISE = re.compile(r"(?i)giveaway|^!|\bwin(ner)?\b|\benter\b|copies|\bcopy\b|patreon|\braid|https?://|\bgift|subscribed|^\W*\d+\W*$")
WORD = re.compile(r"[\w']{2,}|[💀😂🔥😭]")

_session = requests.Session()


def _at(vid, off):
    """Comments starting at contentOffsetSeconds=off. Cursor paging is blocked by an integrity check; offsets are not."""
    for k in range(6):
        try:
            r = _session.post(GQL, json=[{"operationName": "VideoCommentsByOffsetOrCursor",
                                          "variables": {"videoID": vid, "contentOffsetSeconds": off},
                                          "extensions": {"persistedQuery": {"version": 1, "sha256Hash": HASH}}}],
                              headers={"Client-Id": CLIENT_ID}, timeout=20)
            c = r.json()[0]["data"]["video"]["comments"]
            if c is not None:
                return [e["node"] for e in c["edges"]]
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    return None


def download(vid, duration, out):
    failed = 0

    def sweep(a, b):
        nonlocal failed
        off, got = a, []
        while off < b:
            ns = _at(vid, off)
            if ns is None:
                failed += 1; off += 10; continue
            ns = [n for n in ns if n["contentOffsetSeconds"] >= off]
            if not ns:
                off += 10; continue
            got += ns
            last = max(n["contentOffsetSeconds"] for n in ns)
            off = last + 1 if last >= off else off + 10
        return got

    seen = {}
    with ThreadPoolExecutor(6) as ex:
        for res in ex.map(lambda c: sweep(*c), [(a, min(a + 900, duration + 1)) for a in range(0, duration + 1, 900)]):
            for n in res:
                seen[n["id"]] = n
    rows = []
    for n in sorted(seen.values(), key=lambda n: n["contentOffsetSeconds"]):
        rows.append({"t": n["contentOffsetSeconds"], "user": (n.get("commenter") or {}).get("login"),
                     "text": "".join(f.get("text", "") for f in n["message"]["fragments"])})
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows, failed


def spikes(rows, top=10, bucket=10, gap=90):
    dur = max((r["t"] for r in rows), default=0)
    n = dur // bucket + 1
    cnt = [0] * n; words = collections.defaultdict(collections.Counter); texts = collections.defaultdict(list)
    for r in rows:
        if NOISE.search(r["text"]):
            continue
        b = r["t"] // bucket
        cnt[b] += 1; texts[b].append(r["text"])
        for w in set(WORD.findall(r["text"].lower())):
            words[b][w] += 1
    w = 300 // bucket
    scored = []
    for i in range(n):
        base = statistics.median(cnt[max(0, i - w):i + w + 1]) or 0.5
        scored.append((cnt[i] / base * min(cnt[i], 40), i, cnt[i], base))
    scored.sort(reverse=True)
    out, used = [], []
    for sc, i, c, base in scored:
        if all(abs(i - j) * bucket > gap for j in used):
            used.append(i)
            sample = sorted(set(t for t in texts[i] if len(t) > 3), key=len, reverse=True)[:6]
            out.append({"t": i * bucket, "msgs_10s": c, "ratio": round(c / base, 1),
                        "top_words": [x for x, _ in words[i].most_common(5)], "sample": sample})
        if len(out) >= top:
            break
    return out


def hms(s):
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vod"); ap.add_argument("--top", type=int, default=10); ap.add_argument("--out", default="chat.jsonl")
    a = ap.parse_args()
    vid = re.sub(r"\D", "", a.vod.rstrip("/").split("/")[-1])
    sys.path.insert(0, str(Path(__file__).parent))
    from common import ytdlp_json
    dur = int(ytdlp_json(f"https://www.twitch.tv/videos/{vid}").get("duration") or 0)
    rows, failed = download(vid, dur, a.out)
    print(f"{len(rows)} chat messages over {hms(dur)} ({failed} failed requests) -> {a.out}")
    sp = spikes(rows, a.top)
    Path(a.out).with_name("spikes.json").write_text(json.dumps(sp, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, s in enumerate(sp, 1):
        print(f"{k:2d}. {hms(s['t'])}  {s['msgs_10s']} msgs/10s (x{s['ratio']})  {s['top_words']}")
        print("    " + " | ".join(t[:60] for t in s["sample"]))


if __name__ == "__main__":
    main()
