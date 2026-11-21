# Clipper

Turns long podcasts and YouTube videos into vertical short clips, 100% free and running locally.
Claude reads the transcript and picks the moments; the code handles the editing.

**What every clip gets:** a scroll-stopping hook, word-by-word animated captions, active-speaker
auto-reframe to 9:16 (including split screen), jump cuts with silences and "um"s removed, punch-in zooms,
B-roll cut-ins with a whoosh, ducked background music (original and copyright-free), loudness
mastering for Shorts/TikTok/Reels, a progress bar, and ready-to-post caption text.

## Use it with Claude

Just say: *"Clip this: https://youtube.com/watch?v=..."*. Claude follows `CLAUDE.md`.

## Use it yourself

```bash
./setup.sh
python3 -m clipper prep "https://www.youtube.com/watch?v=..."   # download + transcript
# write work/<id>/clips.json (see CLAUDE.md), or let the heuristics do it:
python3 -m clipper render work/<id>
python3 -m clipper auto "https://www.youtube.com/watch?v=..."   # fully automatic fallback
```

## Optional, still free

- **B-roll footage**: get a free key at pexels.com/api and put `PEXELS_API_KEY=yourkey` in `.env`,
  and/or drop your own clips or images into `assets/broll/` (name files by what they show).
- **Your own music**: put royalty-free tracks in `assets/music/<mood>/` (chill, inspiring, emotional,
  tense, dark, upbeat, hype). Without them, original music is generated for each clip.
- **YouTube blocks cloud servers** sometimes ("confirm you're not a bot"). Add a `cookies.txt`
  exported from your browser, pass a downloaded video file, or run this on your own computer.

Fonts: Anton & Poppins (SIL Open Font License). Face detector: OpenCV YuNet (MIT).
