"""Fallback auto-picker (used by `auto` when Claude isn't in the loop).
Claude reading transcript.txt is the primary, far better 'brain' — see CLAUDE.md."""
import re

from .util import read_json, write_json

HOOKY = re.compile(r"\b(never|nobody|secret|truth|mistake|million|billion|crazy|insane|honestly|"
                   r"biggest|worst|best|first time|i realized|the reason|here's|nobody tells|"
                   r"changed my life|fired|broke|died|money|scared|afraid|hate|love)\b", re.I)


def auto_pick(wd, n=5, min_len=25, max_len=60):
    tr = read_json(wd / "transcript.json")
    segs = tr["segments"]
    cands = []
    for i in range(len(segs)):
        if i and not re.search(r"[.?!]$", segs[i - 1]["text"]):
            continue  # start on a sentence boundary
        j, text, en = i, [], []
        while j < len(segs) and segs[j]["e"] - segs[i]["s"] < max_len:
            text.append(segs[j]["text"])
            en.append(segs[j].get("energy", 0))
            j += 1
            dur = segs[j - 1]["e"] - segs[i]["s"]
            if dur >= min_len and re.search(r"[.?!]$", segs[j - 1]["text"]):
                body = " ".join(text)
                score = (sum(en) / len(en)) * 2 + len(HOOKY.findall(body)) * 1.5 \
                    + (2 if "?" in text[0] else 0) + len(re.findall(r"\d", body)) * 0.3 \
                    + (1.5 if HOOKY.search(text[0]) else 0) - abs(dur - 40) / 15
                cands.append((score, segs[i]["s"], segs[j - 1]["e"], body))
    cands.sort(reverse=True)
    picked = []
    for sc, a, b, body in cands:
        if all(b <= p["start"] or a >= p["end"] for p in picked):
            first = re.split(r"(?<=[.?!])\s", body)[0]
            hook = " ".join(first.split()[:9]).rstrip(",.")
            picked.append({"id": f"{len(picked) + 1:02d}", "title": hook[:50], "start": a, "end": b,
                           "hook": hook, "music": "chill", "score": round(sc, 2), "broll": [],
                           "emphasis": []})
        if len(picked) >= n:
            break
    picked.sort(key=lambda c: c["start"])
    write_json(wd / "clips.auto.json", {"clips": picked})
    return wd / "clips.auto.json"
