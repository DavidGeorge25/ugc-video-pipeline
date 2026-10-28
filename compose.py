"""Frame compositor: backgrounds (image / scrolling list / Sankey camera / screen recording),
cut-out person, title and word-timed captions -> final.mp4"""
import json, subprocess, re, math, numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OW, OH, FPS = 1080, 1920, 30
INTER = "/usr/share/fonts/opentype/inter/"
EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
import os as _os
TIKTOK = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "fonts", "TikTokSans-{}.ttf")   # TikTok "Classic" text style (OFL)

# ---------- text rendering ----------
def is_emoji(ch): return ord(ch) >= 0x2600 and not (0xFE00 <= ord(ch) <= 0xFE0F)

def _runs(text):
    """split into [(is_emoji, str)] so plain text keeps proper kerning"""
    out = []
    for ch in text:
        if ch == "\ufe0f": continue
        e = is_emoji(ch)
        if out and out[-1][0] == e and not e: out[-1][1] += ch
        else: out.append([e, ch])
    return out

def text_rgba(text, size, weight="SemiBold", stroke=0, shadow=True, maxw=940, line_gap=1.12):
    font = ImageFont.truetype(TIKTOK.format(weight), size) if isinstance(weight, int) else ImageFont.truetype(INTER + f"Inter-{weight}.otf", size)
    efont = ImageFont.truetype(EMOJI, 109)
    def run_w(s):
        return sum(size * 1.15 if e else font.getlength(t) for e, t in _runs(s))
    lines, cur = [], ""
    for word in text.split(" "):
        t = (cur + " " + word).strip()
        if run_w(t) > maxw and cur: lines.append(cur); cur = word
        else: cur = t
    lines.append(cur)
    lh = int(size * line_gap); pad = 30
    W = int(max(run_w(l) for l in lines)) + 2 * pad; H = lh * len(lines) + 2 * pad
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(txt)
    for i, l in enumerate(lines):
        x = (W - run_w(l)) / 2; y = pad + i * lh
        for e, t in _runs(l):
            if e:
                em = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
                ImageDraw.Draw(em).text((0, 0), t, font=efont, embedded_color=True)
                em = em.crop(em.getbbox() or (0, 0, 1, 1)).resize((int(size * 1.05), int(size * 1.05)), Image.LANCZOS)
                txt.alpha_composite(em, (int(x + size * 0.05), int(y + size * 0.08)))
                x += size * 1.15
            else:
                d.text((x, y), t, font=font, fill="white", stroke_width=stroke, stroke_fill=(20, 20, 20))
                x += font.getlength(t)
    if shadow:
        a = txt.split()[3].filter(ImageFilter.GaussianBlur(5))
        sh = Image.new("RGBA", txt.size, (0, 0, 0, 0)); sh.putalpha(a.point(lambda v: int(v * 0.55)))
        base = Image.new("RGBA", txt.size, (0, 0, 0, 0)); base.alpha_composite(sh, (0, 2)); base.alpha_composite(txt)
        txt = base
    return np.array(txt)

def curly(t):
    import re as _re
    t = _re.sub(r'"(\S)', '\u201c\\1', t); t = t.replace('"', '\u201d'); return t.replace("'", "\u2019")

def paste_rgba(frame, rgba, cx, cy):
    h, w = rgba.shape[:2]; x0 = int(cx - w / 2); y0 = int(cy - h / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(OW, x0 + w), min(OH, y0 + h)
    if xa >= xb or ya >= yb: return
    sub = rgba[ya - y0:yb - y0, xa - x0:xb - x0].astype(np.float32)
    a = sub[..., 3:4] / 255
    frame[ya:yb, xa:xb] = frame[ya:yb, xa:xb] * (1 - a) + sub[..., :3] * a

# ---------- camera ----------
def ease(x): x = min(1, max(0, x)); return x * x * (3 - 2 * x)
def lerp_view(a, b, k): return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))

def view_at(t, keys, prev_view=None, dur=0.45):
    """keys: [(t, view)] view=(cx, cy, w). transitions start at key time."""
    v = prev_view if prev_view is not None else keys[0][1]
    for kt, kv in keys:
        if t < kt: break
        k = ease((t - kt) / dur)
        v = lerp_view(v, kv, k)
    return v

_PYR = {}
def _level(img, f):
    """pre-shrunk copy so warps never downsample more than ~1.4x (avoids aliasing / mush)"""
    key = id(img); lv = _PYR.setdefault(key, {1: img})
    k = 1
    while f / (k * 2) >= 0.7 and k < 8: k *= 2
    if k not in lv:
        h, w = img.shape[:2]; lv[k] = cv2.resize(img, (max(1, w // k), max(1, h // k)), interpolation=cv2.INTER_AREA)
    return lv[k], k

def warp_view(img, view, border, cache=True):
    """view=(cx, cy, w) in img px -> OWxOH"""
    cx, cy, w = view; h = w * OH / OW
    f = w / OW                      # source px per output px
    src, k = _level(img, f) if cache else (img, 1)
    s = OW / (w / k)
    M = np.float32([[s, 0, -((cx - w / 2) / k) * s], [0, s, -((cy - h / 2) / k) * s]])
    return cv2.warpAffine(src, M, (OW, OH), flags=cv2.INTER_LANCZOS4 if s > 1.05 else cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)

# ---------- backgrounds ----------
DEMO_BG = (240, 240, 244)
def demo_card(frame, view, box):
    """Screen recording shown as a full-width card (no heavy zoom): source width w -> 1080 px,
    vertically limited to box=[top, height]; rest of the canvas is the app's own grey."""
    cx, cy, w = view; top, Hd = box
    s = OW / w; src_h = Hd / s
    M = np.float32([[s, 0, -(cx - w / 2) * s], [0, s, -(cy - src_h / 2) * s + top]])
    out = cv2.warpAffine(frame, M, (OW, OH), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=DEMO_BG)
    if s < 1:   # proper downscale (warpAffine AREA ~ linear): resize-then-place for crisp small text
        x0 = int(round(cx - w / 2)); y0 = int(round(cy - src_h / 2))
        pad = np.full((int(src_h), int(w), 3), DEMO_BG, np.uint8)
        xs, ys = max(0, x0), max(0, y0); xe, ye = min(frame.shape[1], x0 + int(w)), min(frame.shape[0], y0 + int(src_h))
        pad[ys - y0:ye - y0, xs - x0:xe - x0] = frame[ys:ye, xs:xe]
        card = cv2.resize(pad, (OW, Hd), interpolation=cv2.INTER_AREA)
        out = np.empty((OH, OW, 3), np.uint8); out[:] = DEMO_BG; out[top:top + Hd] = card
    out[:top] = DEMO_BG; out[top + Hd:] = DEMO_BG
    return out

class VideoBg:
    def __init__(self, path, fps=60):
        self.path, self.fps = path, fps
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                                          "-of", "json", path], capture_output=True, text=True).stdout)
        self.w, self.h = info["streams"][0]["width"], info["streams"][0]["height"]
        self.dur = float(info["format"]["duration"]); self.p = None; self.idx = -1; self.cur = None
    def get(self, t):
        want = max(0, min(int(t * self.fps), int(self.dur * self.fps) - 2))
        if self.p is None or want < self.idx:
            if self.p: self.p.kill()
            self.p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", self.path, "-vf", f"fps={self.fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                      stdout=subprocess.PIPE, bufsize=10 ** 8)
            self.idx = -1
        while self.idx < want:
            buf = self.p.stdout.read(self.w * self.h * 3)
            if len(buf) < self.w * self.h * 3: break
            self.cur = np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3); self.idx += 1
        return self.cur

# ---------- person ----------
def person_geometry(alpha_path, n=25):
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", alpha_path],
                          capture_output=True, text=True).stdout.strip().split(",")
    aw, ah = int(info[0]), int(info[1])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", alpha_path, "-vf", "fps=1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, ah, aw)[:n].astype(np.float32).mean(0) / 255
    rows = fr.sum(1) / aw
    top = int(np.argmax(rows > 0.04))
    head = fr[top:top + int(ah * 0.15)]
    cx = (head.sum(0) * np.arange(aw)).sum() / max(head.sum(), 1)
    return cx * OW / aw, top * OH / ah

PRESETS = {  # scale, angle(deg, +=CCW), head-top target (x, y frac)
    "center":    (0.95, 0.0, (540, 0.40)),
    "right":     (0.92, 0.0, (650, 0.30)),
    "tilt":      (0.80, 4.0, (560, 0.37)),
    "tilt_left": (0.80, -4.0, (470, 0.33)),
    "demo":      (0.62, 0.0, (540, 0.615)),   # small, below the demo card so it never covers the product
}

def person_matrix(preset, geo, mult=1.0):
    s, ang, (tx, tyf) = PRESETS[preset]; s *= mult
    hx, hy = geo
    M = cv2.getRotationMatrix2D((hx, hy), ang, s)
    M[0, 2] += tx - hx; M[1, 2] += tyf * OH - hy
    # anchor to the bottom like the professor/react videos: the footage's bottom edge always sits below the canvas,
    # so the body runs off-screen instead of ending in a visible (blurry) band mid-frame
    corners = np.array([[0, OH, 1], [OW, OH, 1]], np.float32) @ M.T
    lift = (OH + 12) - corners[:, 1].min()
    if lift > 0: M[1, 2] += lift
    return M

def solidify_alpha(a8, edge_feather=True):
    """Dark shirt on a dark room makes the matte semi-transparent inside the body (hazy, flickering shirt).
    Anything enclosed by the silhouette (the frame bottom counts as closed, the body runs off it) becomes opaque;
    soft edges (hair, fingers) keep their original matte."""
    h, w = a8.shape; sm = cv2.resize(a8, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    body = (sm > 50).astype(np.uint8)
    body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    pad = np.zeros((body.shape[0] + 2, body.shape[1] + 2), np.uint8); pad[1:-1, 1:-1] = body; pad[-1, :] = 1
    ff = pad.copy(); m = np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, m, (0, 0), 1)                     # background reachable from the top-left corner
    filled = pad | (1 - ff)                             # silhouette + its holes
    core = cv2.erode(filled[1:-1, 1:-1], np.ones((5, 5), np.uint8))
    core = cv2.GaussianBlur(cv2.resize(core * 255, (w, h), interpolation=cv2.INTER_LINEAR), (0, 0), 3)
    out = a8.astype(np.float32)        # NOTE: no hole filling: gaps between arm and body are real background
    # body (below the head): crisp, steady edge instead of RVM's wide smeary fringe on a dark shirt vs dark room.
    rows = np.where((sm > 128).any(1))[0]
    if len(rows):
        y0 = int((rows[0] * 4) + 0.20 * h)                       # ~ chin/neck line; hair above keeps its soft matte
        x = np.clip((out[y0:] - 70) / 120, 0, 1); x = x * x * (3 - 2 * x) * 255
        body = cv2.GaussianBlur(x, (0, 0), 1.2)
        ramp = np.clip(np.arange(h - y0) / 60.0, 0, 1)[:, None]   # blend in over 60px so the neck has no seam
        out[y0:] = out[y0:] * (1 - ramp) + body * ramp
    if not edge_feather:   # green screen: clean matte, hard cutoff where the shirt meets the frame edge
        return out.clip(0, 255).astype(np.uint8)
    fx = np.clip(np.minimum(np.arange(w), w - 1 - np.arange(w)) / (0.07 * w), 0, 1)
    fy = np.clip((h - 1 - np.arange(h)) / (0.05 * h), 0, 1)
    out *= (fx[None, :] ** 1.5) * (fy[:, None] ** 1.5)
    return out.clip(0, 255).astype(np.uint8)

# ---------- main ----------
def compose(cfg, tl, cut_mp4, alpha_mkv, out_mp4, assets):
    lines = tl["lines"]; total = tl["duration"]
    geo = person_geometry(alpha_mkv)
    sank = cv2.cvtColor(cv2.imread(assets["sankey_png"]), cv2.COLOR_BGR2RGB)
    boxes = json.load(open(assets["sankey_json"])); SS = boxes["__scale"]
    car = cv2.cvtColor(cv2.imread(assets["image"]), cv2.COLOR_BGR2RGB)
    # low-res photo: upscale once with Lanczos + gentle unsharp so it holds up full-screen
    ch, cw = car.shape[:2]; up = max(1.0, 1.35 * max(OW / cw, OH / ch))
    car = cv2.resize(car, (int(cw * up), int(ch * up)), interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(car, (0, 0), 2.0); car = cv2.addWeighted(car, 1.45, blur, -0.45, 0)
    emails = cv2.cvtColor(cv2.imread(assets["emails_png"]), cv2.COLOR_BGR2RGB)
    hed = VideoBg(assets["recording"]) if assets.get("recording") else None
    HV = cfg.get("recording_views", {})

    def sankey_view(focus):
        names = focus if isinstance(focus, list) else [focus]
        b = [boxes[n] for n in names]
        if b[0]["col"] == 0:
            w = 700; x = b[0]["x"] - 20 - 0.40 * w + w / 2 + 40   # label right-edge near 40% width
            cy = b[0]["y"] + b[0]["h"] / 2
            return ((x) * SS, (cy - 0.22 * w * 16 / 9 + w * 8 / 9) * SS, w * SS)
        w = 380 if len(b) == 1 else 470
        left = b[0]["x"] - 22
        top_label = b[0]["y"] + b[0]["h"] / 2
        frac = 0.20 if len(b) == 1 else 0.14
        cy = top_label - frac * w * 16 / 9 + w * 8 / 9
        return ((left + w / 2) * SS, cy * SS, w * SS)

    # prebuild per-line camera keys & overlays
    words_at = lambda line, word: next((t for (wd, t) in line["words"] if re.sub(r"\W", "", wd.lower()) == word.lower()), line["start"])
    prev_v = {}
    for i, (L, C) in enumerate(zip(lines, cfg["lines"])):
        L["cfg"] = C; bg = C["bg"]; keys = []
        if bg == "sankey":
            for f in C["focus"]:
                if isinstance(f, list) and len(f) == 2 and (f[1] is None or isinstance(f[1], str)) and f[0] in boxes:
                    keys.append((L["start"] if f[1] is None else words_at(L, f[1]), sankey_view(f[0])))
                else:
                    keys.append((L["start"], sankey_view(f)))
        elif bg == "recording":
            for name, at in C.get("views", [["inbox", None]]):
                keys.append((L["start"] if at is None else words_at(L, at), tuple(HV[name])))
        L["keys"] = keys
        L["title_img"] = text_rgba(C["title"], 77, 600, stroke=3, maxw=830, line_gap=1.24) if C.get("title") else None
        # caption chunks
        # "this many" (said while pointing at the chart) -> show the real number in the caption
        words = [list(w) for w in L["words"]]
        if C.get("num") is not None:
            for k in range(len(words) - 1):
                if re.sub(r"\W", "", words[k][0].lower()) in ("this", "that") and re.sub(r"\W", "", words[k + 1][0].lower()) == "many":
                    tail = re.sub(r"^[\w']+", "", words[k + 1][0])
                    words[k][0] = f"{C['num']:,}" + tail; del words[k + 1]; break
        chunks, cur = [], []
        for wd, t in words:
            cur.append((wd, t))
            if len(cur) >= 3 or sum(len(x[0]) for x in cur) >= 14 or re.search(r"[.,!?]$", wd):
                chunks.append(cur); cur = []
        if cur: chunks.append(cur)
        caps = []
        for j, ch in enumerate(chunks):
            st = ch[0][1]; en = chunks[j + 1][0][1] if j + 1 < len(chunks) else L["end"]
            caps.append((st, en, text_rgba(curly(" ".join(w for w, _ in ch)), 43, 600, stroke=2, maxw=900)))
        L["caps"] = caps
        if bg == "recording" and C.get("mode") == "play":
            d = L["end"] - L["start"]
            L["rate"] = min(2.6, max(1.0, (hed.dur - 0.4 - C.get('start_at', 0.0)) / d))

    # per-line white balance: measure skin tone in that line's own footage and neutralize warm/yellow light
    def _grab(t):
        f = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", cut_mp4, "-frames:v", "1", "-vf", "scale=270:480",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        a = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", alpha_mkv, "-frames:v", "1", "-vf", "scale=270:480",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
        if len(f) < 270 * 480 * 3 or len(a) < 270 * 480: return None, None
        return np.frombuffer(f, np.uint8).reshape(480, 270, 3).astype(np.float32), np.frombuffer(a, np.uint8).reshape(480, 270).astype(np.float32) / 255
    WB_TARGET = np.array([1.0, 0.80, 0.70])           # daylight-balanced skin ratio R:G:B
    for L in lines:
        L["wb"] = np.ones(3, np.float32)
        if not cfg.get("white_balance", True): continue
        px = []
        for t in np.linspace(L["start"] + 0.2, max(L["start"] + 0.3, L["end"] - 0.2), 3):
            f, a = _grab(t)
            if f is None: continue
            p = f[a > 0.6]; lum = p.mean(1); px.append(p[(lum > 90) & (p[:, 0] > p[:, 2])])
        px = np.concatenate(px) if px else np.zeros((0, 3))
        if len(px) > 200:
            r = px.mean(0) / px.mean(0)[0]
            g = WB_TARGET / r; g = np.clip(g / g.max(), 0.6, 1.0)
            L["wb"] = (g * cfg.get("exposure", 1.15)).astype(np.float32)
    rd_v = subprocess.Popen(["ffmpeg", "-v", "error", "-i", cut_mp4, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=10 ** 8)
    rd_a = subprocess.Popen(["ffmpeg", "-v", "error", "-i", alpha_mkv, "-vf", f"scale={OW}:{OH}:flags=bicubic", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                            stdout=subprocess.PIPE, bufsize=10 ** 8)
    wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                           "-i", cut_mp4, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_mp4], stdin=subprocess.PIPE)
    fi = 0; last_view = {}
    while True:
        buf = rd_v.stdout.read(OW * OH * 3); abuf = rd_a.stdout.read(OW * OH)
        if len(buf) < OW * OH * 3 or len(abuf) < OW * OH: break
        t = fi / FPS
        li = next((k for k, L in enumerate(lines) if L["start"] <= t < L["end"]), len(lines) - 1)
        L = lines[li]; C = L["cfg"]; bg = C["bg"]; lt = t - L["start"]
        # background
        if bg == "image":
            z = 1.0 + 0.05 * (t - L["seq_start"]) / max(1, L["seq_dur"])
            ih, iw = car.shape[:2]; s = max(OW / iw, OH / ih) * z
            bgf = warp_view(car, (iw / 2, ih / 2 + C.get("img_dy", 0), OW / s), (0, 0, 0))
        elif bg == "emails":
            # any-size screenshot: fit to width, then scroll slowly downward (never past the end)
            ew, eh = emails.shape[1], emails.shape[0]; k = ew / OW; vh = OH * k
            y = min(60 * k * (t - L["seq_start"]), max(0, eh - vh))
            border = tuple(int(v) for v in emails[min(eh - 1, int(vh) - 1), ew // 2])
            bgf = warp_view(emails, (ew / 2, vh / 2 + y, ew), border)
        elif bg == "sankey":
            pv = last_view.get("sankey") if L["seq_start"] < L["start"] else None
            v = view_at(t, L["keys"], prev_view=L.get("_from"))
            if "_from" not in L: L["_from"] = pv if pv else L["keys"][0][1]
            v = view_at(t, L["keys"], prev_view=L["_from"])
            drift = 1 - 0.025 * ease(lt / max(0.5, L["end"] - L["start"]))
            v = (v[0], v[1], v[2] * drift)
            last_view["sankey"] = v
            bgf = warp_view(sank, v, (255, 255, 255))
        elif bg == "recording":
            vt = 0.0 if C.get("mode") != "play" else C.get("start_at", 0.0) + lt * L.get("rate", 1.0)
            frame = hed.get(vt)
            if "_from" not in L: L["_from"] = last_view.get("rec") or L["keys"][0][1]
            cx, cy, w = view_at(t, L["keys"], prev_view=L["_from"])
            last_view["rec"] = (cx, cy, w)
            bgf = demo_card(frame, (cx, cy, w), cfg.get("demo_box", [60, 1140]))
        out = bgf.astype(np.float32)
        # person
        M = person_matrix(C.get("person", "tilt"), geo, cfg.get("person_scale", 1.0))
        fg = cv2.warpAffine(np.frombuffer(buf, np.uint8).reshape(OH, OW, 3), M, (OW, OH), flags=cv2.INTER_CUBIC)
        a8 = np.frombuffer(abuf, np.uint8).reshape(OH, OW)
        if cfg.get("solid_body", True): a8 = solidify_alpha(a8, cfg.get("matte") != "green")
        al = cv2.warpAffine(a8, M, (OW, OH), flags=cv2.INTER_LINEAR).astype(np.float32)[..., None] / 255
        # green-screen spill removal: green can never exceed the brighter of red/blue (skin, black shirt unaffected)
        fgf = fg.astype(np.float32)
        fgf[..., 1] = np.minimum(fgf[..., 1], np.maximum(fgf[..., 0], fgf[..., 2]))
        al = np.clip((al - 0.12) / 0.88, 0, 1)          # pull the soft edge in slightly so no green rim remains
        if not np.allclose(L["wb"], 1):
            fgf = 255 * np.power(np.clip(fgf * L["wb"] / 255, 0, 1), 0.9)
        out = out * (1 - al) + fgf * al
        # title + captions
        if L["title_img"] is not None:
            paste_rgba(out, L["title_img"], OW / 2, OH * C.get("title_y", 0.17))
        # captions sit just under his chin for the current layout (face is never covered), within 0.745-0.88 of the frame
        hy_c = geo[0] * M[1, 0] + geo[1] * M[1, 1] + M[1, 2]; sc_c = float(np.hypot(M[0, 0], M[0, 1]))
        cap_y = min(OH * 0.88, max(OH * 0.745, hy_c + 0.33 * OH * sc_c))
        for st, en, img in L["caps"]:
            if st <= t < en: paste_rgba(out, img, OW / 2, cap_y); break
        wr.stdin.write(out.clip(0, 255).astype(np.uint8).tobytes()); fi += 1
    wr.stdin.close(); wr.wait()
    return fi
