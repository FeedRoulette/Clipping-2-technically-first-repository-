# ClipKit — your podcast-to-viral-clips kit

Everything needed to make the same clips again in a brand-new chat: the code, fonts, 3D emoji, face-detection
model, your style rules, and a playbook that tells Claude exactly how to work. 100% free.

## How to use it in a new chat
1. Upload `clipkit.zip` (or point Claude at this folder in your GitHub repo).
2. Paste this message:

> Unzip clipkit.zip, read clipkit/PLAYBOOK.md and clipkit/STYLE.md, run clipkit/setup.sh, then make clips from
> this episode: <your Google Drive link>. Follow the playbook and my style rules exactly.

3. Claude will download the episode, transcribe it, pick the best moments, render them and send you the MP4s.

## What's inside
- `PLAYBOOK.md` – step-by-step workflow and every lesson learned (read by Claude)
- `STYLE.md` – your rules: hooks at the top, big words like "CEO", one story per clip, 15–35 s, etc.
- `render.py`, `editor.py` – the clip maker (captions, hook, B-roll, emoji, sound effects, music, framing)
- `transcribe.py`, `check.py` – transcription and the pre-render quality check
- `fetch_assets.py` – downloads the free Mixkit music / sound effects / stock footage (their licence doesn't allow
  shipping the raw files in a zip, so they're re-downloaded automatically)
- `assets/` – fonts (SIL Open Font License), Microsoft Fluent 3D emoji (MIT), YuNet face model (MIT)
- `examples/example_spec.json` – a real clip spec
