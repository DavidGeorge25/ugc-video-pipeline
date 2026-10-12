"""Normalize one or more raw clips (any phone format/rotation) into a single 1080x1920 30fps H.264 file.
Low-memory: each part is encoded separately, then concatenated without re-encoding."""
import os, subprocess, sys, tempfile

def prepare_raw(parts, out):
    d = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(out))); lst = []
    for i, p in enumerate(parts):
        q = os.path.join(d, f"p{i:02d}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p,
                        "-vf", "fps=30,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                        "-c:v", "libx264", "-crf", "16", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", q], check=True)
        lst.append(f"file '{q}'")
    open(os.path.join(d, "l.txt"), "w").write("\n".join(lst))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", os.path.join(d, "l.txt"), "-c", "copy", out], check=True)
    return out

def share_copy(src, out, max_mb=28):
    """Re-encode to fit the 30MB chat-send limit (2-pass-free bitrate budget)."""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], capture_output=True, text=True).stdout)
    vk = int((max_mb * 8 * 1024) / dur - 170)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{vk}k", "-maxrate", f"{int(vk*1.2)}k",
                    "-bufsize", f"{vk*2}k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out], check=True)
    return out

if __name__ == "__main__":
    prepare_raw(sys.argv[2:], sys.argv[1])
