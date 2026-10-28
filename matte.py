"""Robust Video Matting (CPU, ONNX) -> grayscale alpha video (ffv1)."""
import subprocess, numpy as np, onnxruntime as ort, sys
import os
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "rvm.onnx")

def matte(src, out, w=576, h=1024, dsr=0.375):
    so = ort.SessionOptions(); so.intra_op_num_threads = 2
    sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
    rd = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                           "-c:v", "ffv1", out], stdin=subprocess.PIPE)
    rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4
    d = np.array([dsr], np.float32); n = 0
    while True:
        buf = rd.stdout.read(w * h * 3)
        if len(buf) < w * h * 3: break
        x = np.frombuffer(buf, np.uint8).reshape(h, w, 3).transpose(2, 0, 1)[None].astype(np.float32) / 255
        fgr, pha, *rec = sess.run(None, {"src": x, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2], "r4i": rec[3], "downsample_ratio": d})
        wr.stdin.write((pha[0, 0] * 255).clip(0, 255).astype(np.uint8).tobytes()); n += 1
    wr.stdin.close(); wr.wait(); rd.wait()
    return n

if __name__ == "__main__":
    print(matte(sys.argv[1], sys.argv[2]))

def green(src, out, w=576, h=1024, lo=40, hi=140):
    """Chroma-key matte for real green-screen footage (much cleaner than RVM when the background is pure green).
    alpha from green dominance d = G - max(R, B): d<=lo -> person, d>=hi -> background, soft ramp between (hair/edges)."""
    import cv2
    rd = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", "30", "-i", "-",
                           "-c:v", "ffv1", out], stdin=subprocess.PIPE)
    n = 0
    while True:
        buf = rd.stdout.read(w * h * 3)
        if len(buf) < w * h * 3: break
        f = np.frombuffer(buf, np.uint8).reshape(h, w, 3).astype(np.int16)
        d = f[..., 1] - np.maximum(f[..., 0], f[..., 2])
        a = np.clip((hi - d) / float(hi - lo), 0, 1)
        a = cv2.GaussianBlur((a * 255).astype(np.uint8), (0, 0), 0.8)
        wr.stdin.write(a.tobytes()); n += 1
    wr.stdin.close(); wr.wait(); rd.wait()
    return n
