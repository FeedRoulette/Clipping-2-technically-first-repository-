"""Animated word-by-word captions + on-screen hook, rendered as an ASS subtitle file (burned by ffmpeg/libass)."""
import re

W, H = 1080, 1920

# ASS colours are &HAABBGGRR
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
YELLOW = "&H0000E5FF"     # #FFE500 active word
GREEN = "&H0014FF39"      # #39FF14 emphasis / money words
RED = "&H003C3CFF"        # #FF3C3C danger words

STYLES = {
    # name: (font, size, primary, outline colour, outline px, shadow px)
    "bold":   ("Anton", 128, WHITE, BLACK, 8, 4),
    "clean":  ("Poppins Black", 84, WHITE, BLACK, 6, 3),
}

DANGER = {"never", "dead", "died", "kill", "killed", "worst", "lost", "lose", "broke", "fired", "wrong",
          "stop", "fail", "failed", "failure", "danger", "scared", "fear", "hate", "crazy", "insane",
          "war", "crash", "nobody"}
MONEY = re.compile(r"^(\$[\d,.]+[kmb]?|[\d,.]+%|\d[\d,.]*(k|m|b|million|billion|thousand)?|million|billion|"
                   r"money|rich|millionaire|billionaire|free|secret|best|first|everything|always|truth)$", re.I)


def _esc(t):
    return t.replace("\\", "").replace("{", "(").replace("}", ")")


def _clean(word):
    w = word.strip()
    w = re.sub(r"^[\"'“”‘’(\[]+|[\"'“”‘’)\],.;:]+$", "", w)
    return w


def chunk_words(words, max_words=3, max_chars=16, gap=0.35):
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur:
            text_len = sum(len(_clean(x["w"])) + 1 for x in cur) + len(_clean(w["w"]))
            brk = (len(cur) >= max_words or text_len > max_chars or w["s"] - cur[-1]["e"] > gap
                   or re.search(r"[.?!,;:]$", cur[-1]["w"]))
            if brk:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _t(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _word_colour(word, emphasis):
    base = _clean(word).lower()
    if base in emphasis:
        return GREEN
    if MONEY.match(base):
        return GREEN
    if base in DANGER:
        return RED
    return None


def build_ass(words, out_path, hook=None, hook_seconds=4.0, total=None, style="bold",
              caption_y=0.70, emphasis=(), uppercase=True, max_words=3, keywords=None):
    """words: [{w,s,e}] in OUTPUT timeline seconds. keywords: [(t, text)] big pop-up words (no-broll mode)."""
    font, size, prim, outc, outw, shad = STYLES.get(style, STYLES["bold"])
    emphasis = {e.lower() for e in emphasis}
    hook_size = 96 if hook and len(hook) < 34 else 86
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{prim},{prim},{outc},&H80000000,0,0,0,0,100,100,1,0,1,{outw},{shad},5,60,60,0,1
Style: Hook,Poppins Black,{hook_size},&H00101010,&H00101010,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,3,26,0,8,80,80,250,1
Style: Pop,Anton,170,{YELLOW},{YELLOW},{BLACK},&H80000000,0,0,0,0,100,100,2,0,1,10,6,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    cy = int(H * caption_y)
    for chunk in chunk_words(words, max_words=max_words):
        tokens = [_esc(_clean(w["w"]) or w["w"]) for w in chunk]
        if uppercase:
            tokens = [t.upper() for t in tokens]
        c_start = chunk[0]["s"]
        c_end = chunk[-1]["e"]
        for i, w in enumerate(chunk):
            s = w["s"] if i else c_start
            e = chunk[i + 1]["s"] if i + 1 < len(chunk) else max(c_end, w["e"]) + 0.05
            if e - s < 0.04:
                continue
            parts = []
            for j, tok in enumerate(tokens):
                col = _word_colour(chunk[j]["w"], emphasis)
                if j == i:
                    parts.append(f"{{\\c{col or YELLOW}\\fscx112\\fscy112}}{tok}{{\\c{prim}\\fscx100\\fscy100}}")
                elif col:
                    parts.append(f"{{\\c{col}}}{tok}{{\\c{prim}}}")
                else:
                    parts.append(tok)
            anim = "\\fscx70\\fscy70\\t(0,90,\\fscx100\\fscy100)" if i == 0 else ""
            ev.append(f"Dialogue: 1,{_t(s)},{_t(e)},Cap,,0,0,0,,{{\\pos({W // 2},{cy}){anim}}}{' '.join(parts)}")

    if hook:
        end = min(hook_seconds, total) if total else hook_seconds
        txt = _esc(hook.upper() if uppercase else hook)
        ev.append(f"Dialogue: 2,{_t(0)},{_t(end)},Hook,,0,0,0,,"
                  f"{{\\fad(120,250)\\fscx85\\fscy85\\t(0,140,\\fscx100\\fscy100)}}{txt}")

    for t, text in (keywords or []):
        ev.append(f"Dialogue: 3,{_t(t)},{_t(t + 0.9)},Pop,,0,0,0,,"
                  f"{{\\pos({W // 2},{int(H * 0.40)})\\fad(60,180)\\frz-4\\fscx40\\fscy40"
                  f"\\t(0,120,\\fscx110\\fscy110)\\t(120,220,\\fscx100\\fscy100)}}{_esc(text.upper())}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    return out_path
