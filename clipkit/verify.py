import json, subprocess, sys, re, difflib, os
import numpy as np
from faster_whisper import WhisperModel
sys.path.insert(0, os.path.dirname(__file__))
import editor as M, edl2, fillercheck
m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=4)
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ").replace("$", "")).split()
for spec_path in sys.argv[1:]:
    spec = json.load(open(spec_path))
    words = json.load(open(spec["words"]))
    _, kept = edl2.build3(words, spec["segments"], 30, spec.get("drop_at", []), env=M._energy(), log=lambda x: None, trust_aligner=spec.get("trust_aligner", False))
    want = norm(" ".join(w["w"] for w in kept))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", spec["out"], "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    segs, _ = m.transcribe(a, language="en", beam_size=5, condition_on_previous_text=False, vad_filter=False, word_timestamps=True)
    segs = list(segs)
    ws = [w for sg in segs for w in sg.words]
    got = norm(" ".join(s.text for s in segs))
    sm = difflib.SequenceMatcher(None, want, got)
    issues = [(op, " ".join(want[i1:i2]), " ".join(got[j1:j2])) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    print(f"== {os.path.basename(spec['out'])}: word match {sm.ratio()*100:.0f}%  differences: {issues}")
    # visual jumps: frame-difference spikes
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", spec["out"], "-vf", "scale=64:114,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    fr = np.frombuffer(p, np.uint8).reshape(-1, 114, 64).astype(np.float32)
    d = np.abs(np.diff(fr, axis=0)).mean((1, 2))
    med = np.median(d)
    jumps = int(((d > med * 4) & (d > 6)).sum())
    print(f"   visual jumps: {jumps} in {len(fr)/30:.1f}s")
    # freezes: picture stalls (frame holds) feel like the video "stopped" - flag any 0.2 s+ near-frozen run
    p2 = subprocess.run(["ffmpeg", "-v", "error", "-i", spec["out"], "-vf", "scale=128:228,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    f2 = np.frombuffer(p2, np.uint8).reshape(-1, 228, 128).astype(np.float32)
    d2 = np.abs(np.diff(f2[:, 20:140], axis=0)).mean((1, 2))
    fz, run = [], 0
    for k, v in enumerate(list(d2) + [99]):
        if v < 0.6: run += 1
        else:
            if run >= 6: fz.append((round((k - run) / 30, 2), round(k / 30, 2)))
            run = 0
    print(f"   FREEZES (>=0.2s): {fz or 'none'}")
    # dead air: any stretch with no words (silence OR a dragged "uhhh") the viewer has to sit through
    dur = len(a) / 16000
    gaps = []
    if ws:
        if ws[0].start > 0.6: gaps.append((0.0, ws[0].start))
        for x, y in zip(ws, ws[1:]):
            if y.start - x.end > 0.6: gaps.append((x.end, y.start))
        if dur - ws[-1].end > 1.0: gaps.append((ws[-1].end, dur))
    fill = [(round(w.start, 1), w.word.strip()) for w in ws if re.sub(r"[^a-z]", "", w.word.lower()) in ("um", "uh", "uhm", "umm", "ah", "er", "hmm")]
    print(f"   DEAD AIR (>0.6s): {[(round(x,1), round(y,1)) for x, y in gaps] or 'none'}   fillers heard: {fill or 'none'}")
    fillercheck.check(spec['out'], m=m)   # verbatim pass: catches the ums/uhs/'you know'/repeats normal Whisper hides
