# ClipKit playbook — instructions for Claude

You are the editor. The user sends a podcast (usually a Google Drive link) and wants short vertical clips that
stop the scroll. Everything must stay **free** (no paid APIs, no subscriptions). Read `STYLE.md` first — those are
the user's rules and they are not optional. Deliver finished MP4s in the chat (send the files), ranked best first.

## 0. Setup (once per fresh environment)
```bash
cd clipkit && ./setup.sh        # pip deps (opencv-contrib 4.10 — NOT 5.x), whisper models, Mixkit assets
```
Needs ffmpeg + python3. If `setup.sh` fails on a host, report the blocked host; don't route around policies.

## 1. Get the video
- Google Drive link: `gdown <FILE_ID> -O work/` (the ID is the part after `/d/`). Rename to `work/src.mp4`.
- YouTube links usually fail from cloud servers ("confirm you're not a bot") — ask for a Drive link instead.
  Never use third-party mirror/proxy sites.
- The user is on an iPad: uploads in chat are capped at ~30 MB, so Drive links are the normal path.

## 2. Transcribe and read EVERYTHING
```bash
python3 transcribe.py full work/src.mp4 work --vocab "Guest Name, Company, jargon"
```
Grab 4 sample frames (`ffmpeg -ss T -i work/src.mp4 -frames:v 1 f.png`) to see who is on camera.
Read all of `work/transcript.txt` (in chunks). Skip ads/sponsor reads.

## 3. Pick moments (quality over quantity)
Pick what a stranger scrolling would stop for (see STYLE.md): punchy advice / self-improvement, founder lessons,
wild true stories with a payoff, bold claims with big numbers. Each clip = **one continuous thought in the order it
was said** (you may drop a tangent between full sentences; never collage unrelated stats). 15–35 s. It must
make sense with zero context. Drop anything that opens on jargon or needs setup. Rank by scroll-stopping power.

## 4. Accurate words for each moment
```bash
python3 transcribe.py range work/src.mp4 m1 START END work --vocab "names"
```
(START/END = a few seconds around the moment.) It prints every word with its time — choose segment boundaries
at **sentence starts/ends**. A segment keeps every word whose START time is inside `[start, end)`; set `start`
a hair before the first word you want (but after the previous word's start) and `end` just after the last word's
start time.

## 5. Write the spec (see `examples/example_spec.json`)
| field | meaning |
|---|---|
| `src` | the episode video |
| `words` | the `*.words.json` from step 4 (merge lists with python if a clip uses 2 ranges) |
| `segments` | `[[start,end], ...]` source seconds, chronological, sentence boundaries |
| `hook_lines` | 2 lines `[[text, "white"/"yellow"/"red"], ...]` — big words: "$3.4B CEO…", "EX-SEC QB:", numbers |
| `hook_emoji` | one of the files in `assets/emoji/` (skull, fire, scream, exploding, eyes, rofl, …) |
| `keywords` | UPPERCASE words to colour yellow in captions |
| `emoji_pops` | `[{"at": source_time, "emoji": name}]` 1–3 per clip on punch words |
| `punch` | `[{"at": t}]` impact zoom+flash+boom; optional `"text"` stamp e.g. `"$100M"` (not during the hook) |
| `broll` | `[{"from","to","file":"stock/ID.mp4","offset","style":"full"|"card"}]` on the exact words it illustrates; never during the first ~4 s (hook) for cards |
| `music` | `music/ID.mp3` (see `fetch_assets.py` for moods); `music_db` -21 |
| `fixes` | `[[source_time, "replacement"]]` caption-only corrections ("" hides a word), e.g. `[[3195.0,"6'5\""]]` |
| `out` | output mp4 path |
| `theme` | optional brand colours, e.g. `{"accent": [209,254,23]}` → hook lines styled `"accent"`/`"black"`, lime caption boxes |
| `logo` | optional `{"file":"brand/x.png","width":620,"cy":1500}` → logo on EVERY frame, lower-middle, never over face/captions/hook |

A segment can be `[start, end, "tight"]`: use it when the speaker runs straight on with no pause and the
normal snap-to-silence drags in extra words; the cut then lands in the gap between the two words.

Need other B-roll? Search `https://mixkit.co/free-stock-video/<tag>/` (send a browser User-Agent), parse
`/free-stock-video/<slug>-<id>/` links, then `python3 fetch_assets.py <id> ...`. Preview a frame before using it.
Music: `https://mixkit.co/free-stock-music/mood/<mood>/` (track list is in the page's JSON-LD).

## 6. Check BEFORE rendering
```bash
python3 check.py spec.json
```
- Caption text must read as complete sentences; no stray fragments ("…SO SUCH SHORT…"), no clipped words.
- Every cut level should be below about -12 dB. If one is near 0 dB, the cut is inside speech: move that segment
  boundary to a real pause (often start at the previous sentence) or end the clip earlier.
- Length 15–35 s.

## 7. Render and QA
```bash
python3 render.py spec.json
ffmpeg -i out/clip.mp4 -vf "fps=2,scale=120:213,tile=15x4" -frames:v 1 grid.png   # look at it!
```
Look at the grid: hook readable at top and not covering the face, captions big and never doubled, B-roll on the
right words and not colliding with the hook, nothing odd. Fix and re-render before sending. You cannot hear audio —
say so and ask the user to listen.

## Editing v2 (use this for every clip)
Add to the spec: `"edit": "v2"`, `"speed": 1.08`, optional `"drop_at": [source times of words to remove]`,
and `"sr": true` for 720p or lower sources (AI upscaling, fixes blur when cropping to vertical).
v2 keeps exactly the chosen words, removes um/uh, "you know", "I mean", stutters and restarts
("you want me to, you want me to"), closes every pause (<0.15 s left) and only cuts inside real audio gaps.
Check before rendering:  `python3 check2.py spec.json`  (text + length)  and  `python3 cutdiag.py spec.json`
(every cut; "RISK" lines = glued words, verify the text reads right).

## Retention targets (user's YouTube Studio): >= 80% average viewed, 70-80% stayed-to-watch
- 18-25 s final length; zero dead air; 1.08x speed; end on the peak line; ideally the last line loops into the first.

## Hard-won lessons (don't repeat these mistakes)
- Never send a test render made from a DIFFERENT podcast — test on the episode you're clipping.
- If nothing meets the bar, say "none left" and send nothing. A weak clip is worse than no clip.
- Check who is actually speaking before writing a hook that quotes someone.
- Never cut at word-timestamp edges — the renderer snaps cuts to real audio silence; keep it that way.
- Don't remove "um"/"uh" mid-sentence (choppy). Don't over-trim pauses.
- Zooming in on a 1080p source blurs it; keep zoom minimal. AI upscalers barely help on YouTube-compressed sources.
- Hook at the top (y≈255 px), not the middle; the video drops below it for the first ~3.6 s so the face is clear.
- Captions are drawn one chunk per frame (no overlaps). Merge "4" + "-0" style tokens (the renderer does).
- Openings decide everything (the user once saw 25% stay rate): first words = the strongest line, plus the
  boom/zoom on frame 1. Hooks with "CEO", big money numbers, or a direct callout work best.
- B-roll cards that pop in during the hook collide with it — move them after the hook or use full-screen style.
- Ask for retention numbers ("stayed to watch") after posting and adapt.
