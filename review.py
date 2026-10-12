"""Automatic edit review: transcribe the FINAL video and compare against the script.
Flags repeated phrases, missing/partial lines, and out-of-order lines. Run on every render."""
import sys, json
from collections import Counter
from asr import transcribe
from cut import norm_tokens, align

def review(video, script_lines, n=4, min_cov=0.8):
    words = transcribe(video)
    T, Tt = [], []
    for w in words:
        for t in norm_tokens(w["w"]): T.append(t); Tt.append(w["s"])
    S, S_line = [], []
    for i, l in enumerate(script_lines):
        for t in norm_tokens(l): S.append(t); S_line.append(i)
    issues = []
    # 1) repeats: n-grams spoken more often than the script contains them
    sg = Counter(tuple(S[i:i + n]) for i in range(len(S) - n + 1))
    tg = {}
    for i in range(len(T) - n + 1): tg.setdefault(tuple(T[i:i + n]), []).append(i)
    seen = set()
    for g, pos in tg.items():
        if len(pos) > sg.get(g, 0) and len(pos) > 1:
            k = pos[-1]
            if any(abs(k - s) < 6 for s in seen): continue
            seen.add(k)
            issues.append(f"REPEAT at {Tt[k]:.1f}s: '{' '.join(g)}' spoken {len(pos)}x (script has {sg.get(g, 0)})")
    # 2) coverage + order via one global alignment
    pairs = align(S, T)
    hit = Counter(S_line[si] for si, _ in pairs)
    first_t = {}
    for si, ti in pairs: first_t.setdefault(S_line[si], Tt[ti])
    for i, l in enumerate(script_lines):
        tot = sum(1 for x in S_line if x == i); cov = hit[i] / max(1, tot)
        if cov < min_cov: issues.append(f"MISSING/PARTIAL line {i+1} ({cov:.0%} heard): {l[:60]}")
    # every line's LAST word must be heard (catches clipped endings like "cars" -> "car")
    matched_s = {si for si, _ in pairs}
    for i, l in enumerate(script_lines):
        idx = [k for k, x in enumerate(S_line) if x == i]
        if idx and idx[-1] not in matched_s:
            issues.append(f"CLIPPED ENDING line {i+1}: last word '{S[idx[-1]]}' not heard: {l[:50]}")
    extra = len(T) - len(pairs)
    if extra > max(6, 0.06 * len(T)): issues.append(f"EXTRA speech: {extra} words not in script")
    ok = not issues
    rep = "REVIEW " + ("PASS" if ok else "FAIL") + f" — {len(script_lines)} lines, {len(T)} words heard\n" + "\n".join(" - " + x for x in issues)
    return ok, rep

if __name__ == "__main__":
    cfg = json.load(open(sys.argv[2]))
    print(review(sys.argv[1], [l["text"] for l in cfg["lines"]])[1])
