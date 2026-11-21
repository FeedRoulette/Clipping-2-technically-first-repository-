# Clipper — instructions for Claude

The user gives you a YouTube link (usually a podcast). You are the editor: the code does the
mechanical work, **you** pick the moments and write the hooks. Everything must stay free: no paid
APIs, no paid music, no subscriptions.

## Workflow

1. Setup if needed: `./setup.sh` (pip deps + whisper models).
2. `python3 -m clipper prep "<url or file>"` → prints `work/<id>/`.
   - Long videos (>45 min): keep the default `--model small`, it's ~0.25x realtime on CPU.
   - If YouTube says "confirm you're not a bot" (cloud IPs get blocked): ask the user for a
     `cookies.txt` (browser extension "Get cookies.txt LOCALLY", while logged in to YouTube), saved in
     the repo root, or for the video file itself, or to run this on their own computer. Don't use
     third-party mirror/proxy sites.
3. Read **all** of `work/<id>/transcript.txt` (read it in chunks for long episodes). Lines look like
   `[12:04 724.1-729.8] ! text`. `!` = louder than the speaker's average (passion, laughter, conflict),
   `>>` = fast talking. `meta.json` has the title and YouTube chapters.
4. Write `work/<id>/clips.json` (schema below): usually 5-10 clips, best first.
5. `python3 -m clipper render work/<id>` → `output/<id>/NN_title.mp4` + a `.json` with the post caption.
   `--only 01,03` re-renders single clips. Spot-check frames with ffmpeg before reporting back.
6. Give the user the files and a ranked list: title, hook, why it should work, length.

## How to pick moments (this is the important part)

Good clips are **self-contained stories with tension that pays off**. For each candidate, check:

- **Hook in the first 3 s.** Start on the strongest line: a bold claim, a number, a confession,
  conflict, or a question. Never start on "so", "yeah", "and", or mid-thought. If the payoff line
  comes later, start right before the setup, not 30 s earlier.
- **One idea, a full arc**: setup → tension → payoff/punchline. End right after the payoff (a laugh,
  a mic-drop line, a reveal). Don't trail off into the next topic.
- **Length 20-60 s** (sweet spot 30-45 s). Up to 90 s only for a truly gripping story.
- **Strongest signals**: contrarian takes, specific numbers/money, personal failures or wins,
  "nobody talks about…", heated disagreement, emotional moments, funny exchanges, actionable advice,
  famous names, a surprising story. `!` lines cluster around these.
- **Understandable without context**: no unexplained "he/that thing" from earlier in the episode.
- Clips must not overlap. Spread them across the episode. Rank by how far you'd scroll-stop.

## Writing the extras

- `hook`: the on-screen text for the first ~4.5 s. 3-8 words, curiosity gap, no clickbait lies.
  Patterns: "He lost $2M in one night", "Nobody tells you this about X", "The worst advice I ever got",
  "Why X is actually Y". It should add to what's said, not repeat the first sentence.
- `emphasis`: 3-6 single words from the clip that carry the punch (shown green + punch-in zoom).
  Numbers, money and words like "never/secret/best" are coloured automatically.
- `music` mood: `chill` (default talk), `inspiring` (lessons, success), `emotional` (vulnerable stories),
  `tense` (conflict, drama), `dark` (crime, failure), `upbeat` (fun, tips), `hype` (sports, energy),
  or `none`. It's mixed quietly and ducks under the voice automatically.
- `broll`: 1-3 cut-ins at moments where the speaker *mentions something visual* (a place, object,
  action). `at` is the source time in seconds, `dur` is 1.5-3 s, `query` is 2-3 concrete stock-footage words
  ("city skyline night", not "success"). Add `pop` with 1-3 big words as fallback text if no footage
  is found. Don't put B-roll over the hook or the punchline; the face sells those.
- `pops`: optional extra big keyword pop-ups `[{"at": 731.2, "text": "$2 MILLION"}]`. Use them sparingly.
- `caption` + `hashtags`: ready-to-paste post text (it goes in the output .json).

## clips.json schema

```json
{"clips": [{
  "id": "01", "title": "Short file title", "start": 724.1, "end": 761.8,
  "hook": "He turned down $10M", "hook_seconds": 4.5, "music": "tense",
  "emphasis": ["ten", "million", "walked"],
  "broll": [{"at": 740.0, "dur": 2.5, "query": "private jet runway", "pop": "PRIVATE JET"}],
  "pops": [], "cut_silences": true, "cut_fillers": true,
  "caption": "Would you have taken the deal?", "hashtags": ["#podcast", "#business"],
  "why": "one line on why this clip works", "score": 90
}]}
```
`start`/`end` are seconds in the source; they snap to word boundaries automatically.

## What the renderer does automatically

- Re-transcribes each clip with `large-v3-turbo` so captions are accurate
- Cuts silences > 0.45 s and filler words (um/uh) as jump cuts
- 9:16 reframing: face tracking + active-speaker detection, split screen when two people are on
  camera, blurred-background layout when there are no faces (screen shares)
- Word-by-word animated captions (Anton font, active word yellow, money words green, danger words red)
- Hook text box, jump zooms every 3-5 s, punch-in zooms on emphasis words (scaled down for low-res sources)
- B-roll from `assets/broll/` (filename keyword match) or Pexels (free key in `.env` as
  `PEXELS_API_KEY=...`), with a snap-zoom transition and a whoosh sound effect
- Background music: the user's tracks in `assets/music/<mood>/` if present, else an original
  procedurally generated track (copyright-free), sidechain-ducked under the voice
- Loudness normalised to about -14 LUFS, progress bar, 1080x1920 H.264, 30 fps max

`python3 -m clipper auto "<url>"` exists as a no-Claude fallback using keyword heuristics. It's much
worse than curated picks, so don't use it when you can read the transcript yourself.
