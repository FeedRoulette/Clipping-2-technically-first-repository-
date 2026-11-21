"""B-roll finder. Sources, in order (all free):
  1. assets/broll/  — your own clips/images; filenames are matched against the query words
  2. Pexels API     — free key from https://www.pexels.com/api/ (no card). Put PEXELS_API_KEY=... in .env
  3. Wikimedia Commons — free, no key: openly licensed photos (CC0/CC BY/CC BY-SA), animated with Ken Burns.
     Credits are saved next to the file and copied into the clip's .json for the post description.
If nothing is found the renderer falls back to punch-in zooms + big keyword pop-ups."""
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import ASSETS, ROOT, WORK
from .util import log

MEDIA = (".mp4", ".mov", ".webm", ".mkv", ".jpg", ".jpeg", ".png", ".webp")


def _env_key(name):
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None


def _tokens(s):
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if len(t) > 2}


def local(query):
    lib = ASSETS / "broll"
    if not lib.exists():
        return None
    q = _tokens(query)
    best, score = None, 0
    for p in lib.rglob("*"):
        if p.suffix.lower() in MEDIA:
            sc = len(q & _tokens(p.stem + " " + p.parent.name))
            if sc > score:
                best, score = p, sc
    return best


def pexels(query, min_dur=2.0):
    key = _env_key("PEXELS_API_KEY")
    if not key:
        return None
    cache = WORK / "_broll_cache"
    cache.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower())[:50]
    hit = next(cache.glob(slug + ".*"), None)
    if hit:
        return hit
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "portrait", "per_page": 8, "size": "medium"})
    try:
        req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "clipper/1.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        vids = [v for v in data.get("videos", []) if v.get("duration", 0) >= min_dur]
        if not vids:
            req = urllib.request.Request(url.replace("orientation=portrait", "orientation=landscape"),
                                         headers={"Authorization": key, "User-Agent": "clipper/1.0"})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            vids = [v for v in data.get("videos", []) if v.get("duration", 0) >= min_dur]
        for v in vids:
            files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("height")]
            files.sort(key=lambda f: abs(min(f["height"], f["width"]) - 1080))
            if files:
                out = cache / f"{slug}.mp4"
                req = urllib.request.Request(files[0]["link"], headers={"User-Agent": "clipper/1.0"})
                out.write_bytes(urllib.request.urlopen(req, timeout=60).read())
                log(f"b-roll '{query}' <- pexels video {v['id']} by {v.get('user', {}).get('name')}")
                return out
    except Exception as e:  # network / quota issues should never kill a render
        log(f"pexels lookup failed for '{query}': {e}")
    return None


UA = "ClipperBot/1.0 (personal video editing tool)"
OK_LICENSES = ("cc0", "public domain", "cc by", "cc-by", "pdm")


def _get(url, timeout=30, tries=4):
    """GET with polite backoff on 429/503 (honours Retry-After)."""
    import time
    import urllib.error
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == tries - 1:
                raise
            wait = min(60, int(e.headers.get("Retry-After") or 0) or 5 * 2 ** i)
            log(f"  wikimedia busy, retrying in {wait}s")
            time.sleep(wait)


def wikimedia(query):
    cache = WORK / "_broll_cache"
    cache.mkdir(parents=True, exist_ok=True)
    slug = "wm_" + re.sub(r"[^a-z0-9]+", "_", query.lower())[:50]
    hit = cache / f"{slug}.jpg"
    if hit.exists():
        return hit
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6, "gsrlimit": 12, "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600, "format": "json"})
    try:
        pages = json.loads(_get(url)).get("query", {}).get("pages", {})
        best = None
        for pg in sorted(pages.values(), key=lambda p: p.get("index", 99)):
            ii = (pg.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "")
            if ii.get("mime") not in ("image/jpeg", "image/png") or not lic.lower().startswith(OK_LICENSES):
                continue
            if min(ii.get("width", 0), ii.get("height", 0)) < 900:
                continue
            best = (ii, lic, meta)
            break
        if not best:
            return None
        ii, lic, meta = best
        hit.write_bytes(_get(ii.get("thumburl") or ii["url"], timeout=60))
        artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "unknown")).strip()
        credit = f"{ii.get('descriptionurl', '')} by {artist} ({lic})"
        hit.with_suffix(".credit.txt").write_text(credit)
        log(f"b-roll '{query}' <- Wikimedia Commons: {credit}")
        return hit
    except Exception as e:
        log(f"wikimedia lookup failed for '{query}': {e}")
        return None


def credit_for(path):
    c = Path(path).with_suffix(".credit.txt")
    return c.read_text() if c.exists() else None


def find(query):
    return local(query) or pexels(query) or wikimedia(query)
