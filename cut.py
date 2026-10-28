"""Pick the best (latest) take of each script line from a raw one-take recording,
remove dead air, and render cut.mp4 (1080x1920, 30fps) + timeline.json."""
import json, os, re, subprocess, numpy as np
from num2words import num2words
from rapidfuzz.distance import Levenshtein
from asr import transcribe

def norm_tokens(text):
    text = re.sub(r"\b([eE])-(\w)", r"\1\2", text)   # e-bike == ebike
    text = text.replace("-", " ").replace("’", "'")
    out = []
    for w in text.split():
        w = re.sub(r"[^\w']", "", w.lower())
        if not w: continue
        if re.fullmatch(r"\d+", w):
            out += re.sub(r"[^\w ]", " ", num2words(int(w))).replace(" and ", " ").split()
        else:
            out.append(w)
    return out

def tok_eq(a, b):
    return a == b or (len(a) > 3 and Levenshtein.normalized_similarity(a, b) >= 0.75)

def align(L, T):
    """LCS alignment of line tokens L to transcript tokens T, preferring the EARLIEST
    transcript match for each token (so a line never 'borrows' a word from the next sentence)."""
    n, m = len(L), len(T)
    dp = np.zeros((n + 1, m + 1), np.int32)          # dp[i,j] = LCS of L[i:], T[j:]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i, j] = dp[i + 1, j + 1] + 1 if tok_eq(L[i], T[j]) else max(dp[i + 1, j], dp[i, j + 1])
    pairs = []; i = j = 0
    while i < n and j < m:
        if tok_eq(L[i], T[j]) and dp[i, j] == dp[i + 1, j + 1] + 1:
            pairs.append((i, j)); i += 1; j += 1
        elif dp[i + 1, j] >= dp[i, j + 1]: i += 1
        else: j += 1
    return pairs

def expand_words(words):
    """transcript words -> normalized tokens with (time, word index)"""
    toks = []
    for wi, w in enumerate(words):
        for t in norm_tokens(w["w"]):
            toks.append((t, wi))
    return toks

def candidates(L, toks):
    """all windows where line L is spoken; score = matched fraction."""
    T = [t for t, _ in toks]; n = len(L); cands = []
    firsts = set(L[:3])
    for s in range(len(T)):
        if not any(tok_eq(T[s], f) for f in firsts): continue
        win = T[s:s + n + 6]
        pairs = align(L, win)
        if not pairs: continue
        # drop straggler matches at the tail (words borrowed from the next line)
        while len(pairs) > 2 and pairs[-1][1] - pairs[-2][1] > 2: pairs.pop()
        while len(pairs) > 2 and pairs[1][1] - pairs[0][1] > 2: pairs.pop(0)
        score = len(pairs) / n
        if score < 0.6: continue
        a, b = s + pairs[0][1], s + pairs[-1][1]
        # tighten end: the window can only match up to last matched token
        cands.append(dict(s=a, e=b, score=score, pairs=[(li, s + tj) for li, tj in pairs]))
    # dedupe identical starts, keep best
    best = {}
    for c in cands:
        if c["s"] not in best or c["score"] > best[c["s"]]["score"]: best[c["s"]] = c
    return sorted(best.values(), key=lambda c: c["s"])

def choose(lines_c):
    """DP: one candidate per line in increasing order; maximize score, prefer later takes."""
    import math
    nL = len(lines_c)
    # state: (line idx, cand idx) -> best total
    best = [dict() for _ in range(nL)]
    for i, cs in enumerate(lines_c):
        for k, c in enumerate(cs):
            val = c["score"] * 10 + 0.3 * c["s"] / 10000   # tiny later-take bonus
            prev_best, prev_ptr = 0.0, None
            if i > 0:
                for pk, (pv, _) in best[i - 1].items():
                    if lines_c[i - 1][pk]["e"] < c["s"] and pv > prev_best: prev_best, prev_ptr = pv, pk
                if prev_ptr is None and best[i - 1]:
                    prev_best = -5.0   # allow restart rather than losing earlier lines
            best[i][k] = (prev_best + val, prev_ptr)
    # backtrack (lines with no candidates are skipped)
    picks = [None] * nL
    i = nL - 1
    while i >= 0 and not best[i]: i -= 1
    if i < 0: return picks
    k = max(best[i], key=lambda kk: best[i][kk][0])
    while i >= 0 and k is not None:
        picks[i] = k; k = best[i][k][1]; i -= 1
    return picks

RNN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models/rnnoise/std.rnnn")

def rms_track(path, hop=0.01):
    # measure on DENOISED audio: room hiss sits just above a raw noise-floor threshold and made every pause "audible",
    # so no dead air between lines was ever removed
    af = ["-af", f"arnndn=m={RNN}"] if os.path.exists(RNN) else []
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path] + af + ["-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    h = int(16000 * hop); n = len(a) // h
    r = np.sqrt((a[:n * h].reshape(n, h) ** 2).mean(1) + 1e-12)
    db = 20 * np.log10(r)
    lo, hi = np.percentile(db, 10), np.percentile(db, 95)
    thr = lo + 0.22 * (hi - lo)
    global AUDIBLE
    AUDIBLE = db > max(np.percentile(db, 5) + 9, hi - 40)      # sensitive track: catches soft s/f/th endings
    return db > thr, hop

def speech_span(voiced, hop, t0, t1, lead=0.4, tail=1.0):
    """refine [t0 (first word start), t1 (last word start)] to actual voiced bounds"""
    i0 = int(t0 / hop); i1 = int(t1 / hop)
    s = i0
    while s > 0 and s > i0 - int(lead / hop) and voiced[s - 1]: s -= 1
    e = i1; quiet = 0
    while e < len(voiced) - 1 and e < i1 + int(tail / hop):
        e += 1
        quiet = quiet + 1 if not voiced[e] else 0
        if quiet >= 20: e -= quiet; break
    return s * hop, (e + 1) * hop

def plan(raw, script_lines, min_gap=0.22, pad=0.04, words=None):
    words = words or transcribe(raw)
    toks = expand_words(words)
    voiced, hop = rms_track(raw)
    lines_c = [candidates(norm_tokens(l), toks) for l in script_lines]
    picks = choose(lines_c)
    segs, line_words, report = [], [], []
    for li, (line, cs, k) in enumerate(zip(script_lines, lines_c, picks)):
        if k is None:
            report.append(f"MISSING line {li+1}: {line[:50]}"); line_words.append(None); continue
        c = cs[k]
        # false start inside the chosen take ("So now I'm gonna go to Hedwig... so now I'm gonna go to Hedwig Mail and...")
        # -> start from the LAST restart of the line's opening words
        L0 = norm_tokens(line); head = L0[:3]
        if len(head) == 3:
            restarts = [j for j in range(c["s"] + 1, c["e"] - 2)
                        if all(tok_eq(toks[j + q][0], head[q]) for q in range(3))]
            if restarts:
                ns = restarts[-1]
                Tw = [t for t, _ in toks[ns:c["e"] + 1]]
                pr = align(L0, Tw)
                if pr and len(pr) / len(L0) >= 0.6:
                    c = dict(c, s=ns, pairs=[(li_, ns + tj) for li_, tj in pr])
                    report.append(f"  line {li+1}: dropped false start before {toks[ns][0]!r}")
        w0, w1 = toks[c["s"]][1], toks[c["e"]][1]
        ws = words[w0:w1 + 1]
        a, b = speech_span(voiced, hop, ws[0]["s"], ws[-1]["s"])
        # extend over soft (fricative) audio at both ends, then tight pads -> no dead air
        aud = AUDIBLE; ib, ia = int(b / hop), int(a / hop); q = 0; lim = ib + int(0.35 / hop)
        while ib < min(len(aud) - 1, lim):
            ib += 1; q = q + 1 if not aud[ib] else 0
            if q >= 14: ib -= q; break
        lim = ia - int(0.15 / hop)
        while ia > max(0, lim) and aud[ia - 1]: ia -= 1
        a = max(0, ia * hop - 0.04); b = (ib + 1) * hop + 0.18
        # never bleed into neighbouring words (prevents repeats from overlaps / false starts)
        nxt = words[w1 + 1]["s"] - 0.04 if w1 + 1 < len(words) else b
        prv = words[w0 - 1]["e"] + 0.02 if w0 > 0 else 0
        min_end = ws[-1]["s"] + 0.25   # floor only; real ending comes from the sensitive audible track
        b = min(max(b, min_end), nxt); a = max(min(a, ws[0]["s"] - 0.06), prv)
        # remove internal silences
        i, cur = int(a / hop), a
        pieces = []; run = 0; j = int(a / hop)
        while j < int(b / hop):
            if not AUDIBLE[j]:
                run += 1
            else:
                if run * hop >= min_gap:
                    gs, ge = (j - run) * hop, j * hop
                    pieces.append((cur, gs + 0.09)); cur = ge - 0.05   # let the word before the pause fully ring out
                run = 0
            j += 1
        pieces.append((cur, b))
        # drop audio islands with no transcribed word in them (mumbled false starts the ASR skipped)
        pieces = [p for p in pieces if any(w["s"] - 0.15 < p[1] and w["e"] + 0.35 > p[0] for w in ws)]
        for pi, p in enumerate(pieces):
            if p[1] - p[0] > 0.05:
                sg = dict(s=round(p[0], 3), e=round(p[1], 3), line=li)
                if pi == 0: sg["w0"] = ws[0]["s"]                 # tightening may never eat into the first word
                segs.append(sg)
        report.append(f"line {li+1}: take {k+1}/{len(cs)} @ {ws[0]['s']:.1f}s score {c['score']:.2f}")
        # script-word -> source time via alignment
        L = norm_tokens(line)
        tmap = {li_: words[toks[ti][1]]["s"] for li_, ti in c["pairs"]}
        line_words.append(dict(tok_times=tmap, ntok=len(L)))
    # final tightening: shave quiet heads/tails to 0.05s, drop near-silent slivers
    tight = []
    for sg in segs:
        i0, i1 = int(sg["s"] / hop), int(sg["e"] / hop); seg = AUDIBLE[i0:i1]
        if len(seg) < 15 or seg.mean() < 0.3: continue
        lead = int(np.argmax(seg)); trail = int(np.argmax(seg[::-1]))
        sg["s"] = round(min(sg["s"] + max(0, lead * hop - 0.03), max(sg["s"], sg.pop("w0", 1e9) - 0.06)), 3)
        sg["e"] = round(sg["e"] - max(0, trail * hop - 0.13), 3)   # ASR word ends run long into silence; trust the audio here
        tight.append(sg)
    segs = tight
    clean = []
    for sg in segs:
        if clean and sg["s"] < clean[-1]["e"]:
            sg["s"] = clean[-1]["e"]
        if sg["e"] - sg["s"] > 0.05: clean.append(sg)
    return words, clean, line_words, report

def src_to_out(segs):
    acc = 0.0; table = []
    for s in segs:
        table.append((s["s"], s["e"], acc)); acc += s["e"] - s["s"]
    def f(t):
        best = None
        for a, b, o in table:
            if a - 0.05 <= t <= b: return o + max(0, t - a)
            if t < a: return o if best is None else best
            best = o + (b - a)
        return best
    return f, acc

def render_cut(raw, segs, out, fps=30):
    """low-memory: encode each segment separately (input seek), then concat."""
    import os, tempfile
    d = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(out)))
    lst = []
    for i, s in enumerate(segs):
        dur = s["e"] - s["s"]; fd = min(0.012, dur / 4); p = os.path.join(d, f"s{i:03d}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['s']:.3f}", "-i", raw, "-t", f"{dur:.3f}",
                        "-vf", f"fps={fps},scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                        "-af", f"afade=t=in:d={fd},afade=t=out:st={dur-fd:.4f}:d={fd}",
                        "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", p], check=True)
        lst.append(f"file '{p}'")
    open(os.path.join(d, "l.txt"), "w").write("\n".join(lst))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", os.path.join(d, "l.txt"), "-c", "copy", out], check=True)
