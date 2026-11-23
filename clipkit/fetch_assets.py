"""Downloads the free Mixkit music, sound effects and stock B-roll used by the kit into assets/.
Mixkit licence: free for commercial + social use, no attribution; files must not be redistributed on their own,
which is why they are downloaded here instead of shipped in the zip.  python3 fetch_assets.py [extra_video_ids...]"""
import sys, urllib.request
from pathlib import Path

A = Path(__file__).resolve().parent / "assets"
UA = {"User-Agent": "Mozilla/5.0"}
MUSIC = {122: "Slow Rain (moody beat)", 349: "Basketball Training (energetic)", 587: "Discover (uplifting)",
         595: "Secret Garden (playful)", 22: "Piano Reflections (sad piano)"}
SFX = {1489: "whoosh (b-roll in)", 2358: "pop (emoji)", 1143: "boom (impact / first frame)"}
STOCK = {  # id: what it shows
    46991: "bitcoin stack", 38731: "golden bitcoins", 47799: "bitcoin circuit", 45704: "bitcoin + cash + chart",
    18305: "banknotes falling", 18249: "$100 bills rotating", 47005: "pile of cash", 9520: "dollars falling",
    9536: "world currencies", 8994: "card payment POS", 18264: "phone + card payment", 47016: "stock chart",
    14114: "rising stock indicators", 12823: "ATM", 22734: "wine pouring", 48004: "rain on street",
    4331: "rainy night traffic", 21751: "stadium sunset", 20425: "sunrise", 42549: "QB in practice",
    42553: "QB training passes", 42557: "players practicing", 42558: "team play", 42560: "player blocked",
    42545: "night football training", 42546: "agility ladder", 40969: "boxer knocked down", 40276: "boxer heavy bag",
    52088: "battle ropes", 52094: "barbell lift", 609: "runner on track", 48166: "classroom", 40531: "salad",
    47948: "lightning", 46656: "running in a field"}


def get(url, out):
    if out.exists() and out.stat().st_size > 0:
        return True
    try:
        out.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read())
        return True
    except Exception as e:
        print("  failed", url, e)
        return False


for d in ("music", "sfx", "stock"):
    (A / d).mkdir(parents=True, exist_ok=True)
for i, n in MUSIC.items():
    print("music", i, n, get(f"https://assets.mixkit.co/music/{i}/{i}.mp3", A / "music" / f"{i}.mp3"))
for i, n in SFX.items():
    print("sfx", i, n, get(f"https://assets.mixkit.co/active_storage/sfx/{i}/{i}-preview.mp3", A / "sfx" / f"{i}.mp3"))
for i in list(STOCK) + [int(x) for x in sys.argv[1:]]:
    ok = get(f"https://assets.mixkit.co/videos/{i}/{i}-1080.mp4", A / "stock" / f"{i}.mp4") or \
         get(f"https://assets.mixkit.co/videos/{i}/{i}-720.mp4", A / "stock" / f"{i}.mp4")
    print("stock", i, STOCK.get(i, "extra"), ok)
