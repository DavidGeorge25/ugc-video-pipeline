"""Cut a long raw recording into named parts (e.g. per-product intro/outro) so each video's raw list is in script order.
python3 split_parts.py RAW.mov OUT_DIR 'scooter_intro=1.6-16.05,scooter_outro=16.05-27.4,...'
Pick boundaries in the silence between lines (use a word-timestamp transcript of RAW)."""
import sys, os, subprocess
raw, out, spec = sys.argv[1:4]; os.makedirs(out, exist_ok=True)
for item in spec.split(","):
    name, rng = item.split("="); a, b = map(float, rng.split("-"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a}", "-i", raw, "-t", f"{b - a:.2f}", "-c:v", "libx264", "-crf", "14",
                    "-preset", "ultrafast", "-c:a", "aac", "-b:a", "192k", os.path.join(out, f"{name}.mov")], check=True)
    print(name, a, b)
