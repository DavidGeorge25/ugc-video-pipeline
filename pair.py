"""Match raw clips to scripts by what is actually said (for batch runs with many files).
python3 pair.py scripts_dir raw1.mov raw2.mov ...  -> prints best script per clip with a score."""
import sys, os, glob, subprocess, tempfile
from asr import transcribe
from cut import norm_tokens

def head_tokens(path, secs=90):
    tmp = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", str(secs), "-i", path, "-vn", "-ac", "1", "-ar", "16000", tmp], check=True)
    return set(t for w in transcribe(tmp) for t in norm_tokens(w["w"]))

def pair(script_files, raws):
    scripts = {f: set(norm_tokens(open(f).read())) for f in script_files}
    out = []
    for r in raws:
        heard = head_tokens(r)
        scored = sorted(((len(heard & s) / max(1, len(heard)), f) for f, s in scripts.items()), reverse=True)
        out.append((r, scored[0][1], round(scored[0][0], 2), [(round(a, 2), os.path.basename(b)) for a, b in scored[:3]]))
    return out

if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(sys.argv[1], "*.txt")))
    for r, best, sc, top in pair(files, sys.argv[2:]): print(f"{os.path.basename(r)} -> {os.path.basename(best)}  score {sc}  {top}")
