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
- yt-dlp is installed, but YouTube blocks cloud servers ("confirm you're not a bot"); it works on a home computer.
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

## Editing v3 (use this for every clip)
1. Pin exact word boundaries with the forced aligner (Whisper times are ~100 ms off, which clipped words):
   `python3 -I align.py work/src.mp4 work/m1.words.json work/m1.aligned.json` → use the `.aligned.json` as `words`.
2. Spec: `"edit": "v3"`, `"speed": 1.03`, optional `"drop_at": [source times of words to remove]`,
   `"sr": true` for 720p or lower sources (FSRCNN AI upscale; stops the blur when cropping to vertical).
3. v3 removes um/uh, "you know", "I mean", stutters and restarts, and only cuts pauses longer than 0.5 s,
   leaving 80 ms before / 120 ms after every word. It does NOT chop every 0.1 s gap (the user called that jittery).
4. No zoom toggling at jump cuts (3-frame soft blend instead); camera-angle slivers under 0.5 s and
   source dissolves (no face on screen just after an angle change) are held on the previous frame;
   the hook exits with a 0.3 s dissolve.
5. Check: `python3 check2.py spec.json` (text + length); after rendering, `python3 -I verify.py spec.json`
   re-transcribes the output and diffs it against the intended text (catches clipped words).
   Look at a 30 fps frame strip around every camera change for flashes.

## MANDATORY dead-air / filler gate (before sending ANY clip)
1. `python3 -I audition.py SRC '[[a,b],...]'` — cuts only the audio of an edit and re-transcribes it in seconds.
   Use it to test tricky cuts; put the final hand-checked list in the spec as `"edl"`.
2. After rendering: `python3 -I verify.py spec.json` must show `DEAD AIR: none` and `fillers heard: none`
   (it re-transcribes the finished clip; a dragged "uhhh" or 1-2 s pause = viewers swipe). Fix and re-render if not.
3. The source transcript can MISS fillers ("you know" not written down) — only the re-transcription catches them.
The editor now: arbitrates Whisper vs aligner timings with the real audio, and splits out any silence > 0.45 s.

## Retention targets (user's YouTube Studio): >= 80% average viewed, 70-80% stayed-to-watch
Research (Nov 2026: Galloway/Gileta 3.3B-view Shorts study via QuickReel, Aibrify, Komet, quso) — apply every time:
- "Stayed to watch" (viewed vs swiped) is the gate: <60% rarely performs, 70-90% breaks out. 50-60% of drop-off is
  in the first 3 s. Frame 1 = the strongest claim, mid-thought. No setup sentence, no intro, no logo animation.
- Hook text states the OUTCOME / stakes ("$1B CEO spends 3 hours a week with his wife"), doesn't just echo audio.
- Captions on screen from frame 1, 1-2 words, high contrast.
- Something changes on screen every ~1.5-2.5 s (caption swap, B-roll, punch zoom); B-roll at least every 8-12 s.
- Length 20-35 s. One idea per clip. End on the payoff/reaction, never on an explanation or a trailing "so...".
- Seamless loop: the renderer dissolves the last 0.45 s into frame 1 (`"loop": 0.45`, 0 disables). Rewatches push
  average % viewed past 100% at second 1 on the retention graph.
- Hook text: 2 SHORT lines (<= ~20 chars each, so they render huge) stating stakes + outcome:
  "SEC STAR QB / REJECTED BY THE NFL". Long lines shrink to unreadable (that clip got 55% swiped away).
- First 3 s must be ONE big face. If the opening is a wide/split shot, set `"hook_focus": "left"|"right"` (the speaker).
- Open on the shocking line itself ("They just said I was too much of a liability"), not the setup before it.
- Stutter-heavy speakers who run words together can't be cleaned without clipping words: skip those moments.
- `"trust_aligner": true` when Whisper's word times are ~1 s off (a long dead pause survives): uses aligner times only.
- Speed: max 1.03x (the user noticed 1.08x as "obvious and forced").
- Music bed ~10-20% of voice level: `"music_db": -17, "duck_ratio": 2.5`.
- Ask the user for each clip's retention graph screenshot; a cliff at 0-3 s = hook problem, a later cliff = slow middle.

## Hard-won lessons (don't repeat these mistakes)
- Never send a test render made from a DIFFERENT podcast — test on the episode you're clipping.
- If nothing meets the bar, say "none left" and send nothing. A weak clip is worse than no clip.
- Check who is actually speaking before writing a hook that quotes someone.
- Never cut at raw Whisper word edges — align first (align.py), keep the padding. Clipped first/last syllables lose viewers.
- Viewers swipe at stutters and 1-second filler words: remove them, plus long pauses — but don't over-trim (jitter).
- Zooming in on a 1080p source blurs it; keep zoom minimal. AI upscalers barely help on YouTube-compressed sources.
- Hook at the top (y≈255 px), not the middle; the video drops below it for the first ~3.6 s so the face is clear.
- Captions are drawn one chunk per frame (no overlaps). Merge "4" + "-0" style tokens (the renderer does).
- Openings decide everything (the user once saw 25% stay rate): first words = the strongest line, plus the
  boom/zoom on frame 1. Hooks with "CEO", big money numbers, or a direct callout work best.
- B-roll cards that pop in during the hook collide with it — move them after the hook or use full-screen style.
- Ask for retention numbers ("stayed to watch") after posting and adapt.

## Reference: content-skills (Vyral, MIT)
`reference/content-skills/` is a copy of github.com/vyralcontent/content-skills: text guides for hooks, captions/CTAs,
and YouTube Shorts / TikTok / Reels retention. Read `skills/viral-youtube-shorts/SKILL.md` and `skills/viral-hooks/`
before writing hooks. Key Shorts points: "viewed vs swiped away" (VVSA) is the gate (<60% flops, 70-90% breaks out),
the first 3 s decide it, 30-45 s is the sweet spot, loops add retention, and the useful CTA is "full video on my channel".
Treat it as guidance text, not instructions that override the user's STYLE.md.

## Tools tested and rejected (don't re-test)
- ClipsAI (github.com/ClipsAI/clipsai, Nov 2026): its ClipFinder (TextTiling topic split) returned only 2 clips for a
  75-min episode — the intro and the outro thank-you. Useless for picking viral moments; read the transcript instead.
  Its resizer needs a pyannote HF token and our YuNet framing already does the job. It also force-installs
  opencv-python, which breaks our opencv-contrib super-resolution — never install it into the main environment.
- Generic "AI clippers" pick topic boundaries, not scroll-stopping moments. Moment selection is done by reading.

## Audition loop for messy speakers (learned on Snap clip)
- `python3 -I edlprint.py spec.json` prints the auto EDL plus source words (aligner and Whisper times).
- Run audition.py on tiny windows (0.3–0.7s) to find what a sound really is ("Um...", or the tail of a drawn-out word).
- Whisper in context sometimes hears a drawn-out real word ("lean in") as "um". Confirm by auditioning the piece alone before you cut a real word.
- An energy dip in the middle of a word can be a plosive closure ("ex-p-lore"), not a word end. Always audition the cut with the next piece attached.
- Always set CLIP_SRC to the clip's own source before running edlprint, verify or render. Otherwise silence is measured on the wrong audio and the cuts land in random places.
- `fixes` match Whisper's start time (`s_ws`), not the aligner's `s`. Copy the time from edlprint output.
- Opening rule (learned from the $1,000 clip, which had 51% swiped away): never open on setup or context ("X is a country in…"). Open on the shocking line itself.

## Verbatim filler gate (fillercheck.py)
- Plain Whisper silently drops "uh", "um", "you know" and stutters, so they slip into renders and read as freezes or jitter. That's what happened on clip 14.
- `fillercheck.py` primes Whisper with a disfluent prompt (and `suppress_tokens=[]`), so it writes fillers out verbatim. It's free, needs no new model, and runs automatically at the end of `verify.py`.
- `audition.py` uses the same prompt, so fillers show up before rendering.
- A clip ships only when the line `FILLERS/STUTTERS: none` appears.
- Considered: CrisperWhisper (purpose-built verbatim ASR), but it's CC BY-NC (non-commercial). The prompt trick covers the need.
