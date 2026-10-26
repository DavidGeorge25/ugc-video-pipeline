"""One command: raw clip + video config -> finished vertical video.
python3 make.py video.json raw_clip.mp4 out_dir
"""
import json, sys, os, re
from cut import plan, render_cut, norm_tokens
from matte import matte
from compose import compose
import sankey as sk

def build_timeline(cfg, segs, line_words):
    # output times per segment
    acc = 0.0
    for s in segs: s["o"] = acc; acc += s["e"] - s["s"]
    def s2o(t):
        for s in segs:
            if s["s"] - 0.02 <= t <= s["e"]: return s["o"] + max(0, t - s["s"])
        nxt = [s for s in segs if s["s"] > t]
        return nxt[0]["o"] if nxt else acc
    lines = []
    for li, C in enumerate(cfg["lines"]):
        ss = [s for s in segs if s["line"] == li]
        if not ss: continue
        st, en = ss[0]["o"], ss[-1]["o"] + ss[-1]["e"] - ss[-1]["s"]
        # display words -> times
        disp = C["text"].split(); lw = line_words[li]; words = []; k = 0
        for w in disp:
            toks = norm_tokens(w); ts = [lw["tok_times"][k + j] for j in range(len(toks)) if (k + j) in lw["tok_times"]]
            words.append([w, s2o(ts[0]) if ts else None]); k += len(toks)
        # interpolate missing
        for i, w in enumerate(words):
            if w[1] is None:
                prev = next((words[j][1] for j in range(i - 1, -1, -1) if words[j][1] is not None), st)
                nxt = next((words[j][1] for j in range(i + 1, len(words)) if words[j][1] is not None), en)
                w[1] = prev + (nxt - prev) * 0.5
        words[0][1] = max(st, min(words[0][1], st + 0.1))
        lines.append(dict(idx=li, start=st, end=en, words=words))
    for a, b in zip(lines, lines[1:]): a["end"] = b["start"]
    # sequence spans (consecutive lines with same bg)
    for i, L in enumerate(lines):
        bg = cfg["lines"][L["idx"]]["bg"]; j = i
        while j > 0 and cfg["lines"][lines[j - 1]["idx"]]["bg"] == bg: j -= 1
        k = i
        while k + 1 < len(lines) and cfg["lines"][lines[k + 1]["idx"]]["bg"] == bg: k += 1
        L["seq_start"], L["seq_dur"] = lines[j]["start"], lines[k]["end"] - lines[j]["start"]
    return dict(lines=lines, duration=acc)

def main(cfg_path, raw, out_dir):
    cfg = json.load(open(cfg_path)); os.makedirs(out_dir, exist_ok=True)
    base = os.path.dirname(os.path.abspath(cfg_path))
    A = {k: os.path.join(base, v) for k, v in cfg["assets"].items()}
    sk.build(json.load(open(A["sankey_config"])), os.path.join(out_dir, "sankey"))
    A["sankey_png"], A["sankey_json"] = os.path.join(out_dir, "sankey.png"), os.path.join(out_dir, "sankey.json")
    words, segs, line_words, report = plan(raw, [l["text"] for l in cfg["lines"]])
    print("\n".join(report))
    json.dump(dict(words=words, segs=segs), open(os.path.join(out_dir, "edit.json"), "w"), indent=0)
    cut = os.path.join(out_dir, "cut.mp4"); alpha = os.path.join(out_dir, "alpha.mkv")
    if not (os.environ.get("REUSE") and os.path.exists(cut) and os.path.exists(alpha)):
        render_cut(raw, segs, cut); matte(cut, alpha)
    # filter config lines to those present, keep order
    tl = build_timeline(cfg, segs, line_words)
    cfg2 = dict(cfg); cfg2["lines"] = [cfg["lines"][L["idx"]] for L in tl["lines"]]
    out = os.path.join(out_dir, cfg.get("name", "final") + ".mp4")
    n = compose(cfg2, tl, cut, alpha, out, A)
    json.dump(dict(lines=[dict(start=L["start"], end=L["end"], words=L["words"], text=cfg2["lines"][k]["text"]) for k, L in enumerate(tl["lines"])],
                   duration=tl["duration"]), open(os.path.join(out_dir, "timeline.json"), "w"), indent=0)
    final = varispeed(out, cfg, tl, cfg2) if cfg.get("speed_map") else finish(out, cfg, base)
    from review import review
    ok, rep = review(final, [l["text"] for l in cfg2["lines"]])
    open(os.path.join(out_dir, "review.txt"), "w").write(rep); print(rep)
    print(f"done: {final} ({n} frames, {tl['duration']:.1f}s before speed-up) REVIEW={'PASS' if ok else 'FAIL'}")

def finish(src, cfg, base):
    """speed-up (pitch preserved) + optional background music, then a share-size copy"""
    import subprocess
    sp = float(cfg.get("speed", 1.0)); music = cfg.get("music"); pitch = cfg.get("pitch_with_speed", False)
    out = src.replace(".mp4", f"_x{sp:g}.mp4")
    at = []; x = sp
    while x > 2.0: at.append("atempo=2.0"); x /= 2
    at.append(f"atempo={x:.4f}")
    if pitch: at = [f"asetrate={int(48000*sp)}", "aresample=48000"]   # chipmunk-style: pitch rises with speed
    vf = f"setpts=PTS/{sp},fps=30"
    if music:
        mvol = cfg.get("music_volume", 0.12)
        fc = (f"[0:v]{vf}[v];[0:a]{','.join(at)}[vo];"
              f"[1:a]volume={mvol},afade=t=in:d=1.5[m];[vo][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-stream_loop", "-1", "-i", os.path.join(base, music), "-filter_complex", fc]
    else:
        fc = f"[0:v]{vf}[v];[0:a]{','.join(at)}[a]"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", fc]
    cmd += ["-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    return out

# voice clarity: trim rumble and boxy low-mids, lift presence and air, even out level, TikTok loudness (-14 LUFS)
VOICE_EQ = ("afftdn=nr=12:nf=-42:tn=1,highpass=f=80,equalizer=f=300:t=q:w=1:g=-3,equalizer=f=4000:t=q:w=1:g=4,equalizer=f=10000:t=q:w=1:g=2,"
            "acompressor=threshold=-18dB:ratio=3:attack=5:release=60,loudnorm=I=-14:TP=-1.5:LRA=11")

def varispeed(src, cfg, tl, cfg2):
    """Mostly `base` speed, `slow` speed on punchline phrases. Pitch follows speed (tape-style)."""
    import subprocess, tempfile, re
    sm = cfg["speed_map"]; base, slow = sm.get("base", 1.25), sm.get("slow", 0.75)
    norm = lambda w: re.sub(r"\W", "", w.lower())
    ranges = []
    for prefix, w_from, w_to in sm.get("slow_phrases", []):
        k = next((i for i, c in enumerate(cfg2["lines"]) if c["text"].startswith(prefix)), None)
        if k is None: continue
        L = tl["lines"][k]; ws = L["words"]
        i0 = next((i for i, (w, _) in enumerate(ws) if norm(w) == norm(w_from)), None)
        i1 = next((i for i, (w, _) in enumerate(ws) if i >= (i0 or 0) and norm(w) == norm(w_to)), None)
        if i0 is None or i1 is None: continue
        a = max(L["start"], ws[i0][1] - 0.05); b = ws[i1 + 1][1] - 0.02 if i1 + 1 < len(ws) else L["end"]
        ranges.append((a, b))
    ranges.sort(); segs = []; t = 0.0; D = tl["duration"]
    for a, b in ranges:
        if a > t + 0.05: segs.append((t, a, base))
        segs.append((a, b, slow)); t = b
    if t < D - 0.05: segs.append((t, D, base))
    d = tempfile.mkdtemp(dir=os.path.dirname(src)); parts = []
    for i, (a, b, sp) in enumerate(segs):
        p = os.path.join(d, f"v{i:03d}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b-a:.3f}", "-i", src,   # -t BEFORE -i = input duration (no overlap)
                        "-filter_complex", f"[0:v]setpts=PTS/{sp},fps=30[v];[0:a]asetrate={int(48000*sp)},aresample=48000[a]",
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", p], check=True)
        parts.append(f"file '{p}'")
    open(os.path.join(d, "l.txt"), "w").write("\n".join(parts))
    out = src.replace(".mp4", "_varispeed.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", os.path.join(d, "l.txt"), "-c", "copy", "-movflags", "+faststart", out + ".tmp.mp4"], check=True)
    # hold the last frame 0.6s so the final word never sits on the cut edge
    music = cfg.get("music")
    if music:   # background bed: normalized well under the voice (~-30 LUFS vs voice -14), fades in/out, loops if short
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out + ".tmp.mp4"],
                                   capture_output=True, text=True).stdout) + 0.6
        fc = (f"[0:a]{VOICE_EQ},apad=pad_dur=0.6[v];"
              f"[1:a]loudnorm=I={cfg.get('music_lufs', -30)}:TP=-3,afade=t=in:d=1,afade=t=out:st={dur - 1.5:.2f}:d=1.5,atrim=0:{dur:.2f}[m];"
              f"[v][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[a]")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out + ".tmp.mp4", "-stream_loop", "-1", "-i", music, "-filter_complex", fc,
                        "-vf", "tpad=stop_mode=clone:stop_duration=0.6", "-map", "0:v", "-map", "[a]",
                        "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], check=True)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out + ".tmp.mp4", "-vf", "tpad=stop_mode=clone:stop_duration=0.6", "-af", VOICE_EQ + ",apad=pad_dur=0.6",
                        "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], check=True)
    print("speed segments:", [(round(a, 2), round(b, 2), sp) for a, b, sp in segs])
    return out

if __name__ == "__main__":
    main(*sys.argv[1:4])
