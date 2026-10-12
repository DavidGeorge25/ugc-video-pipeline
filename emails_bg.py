"""Dark mail-client 'sent' list, one row per brand. Tall PNG for vertical scrolling.
Usage: python3 emails_bg.py brands.txt "Request for a Free Car" out.png
brands.txt: one brand per line, optional '|dept' suffix (e.g. 'Tesla|Sales').
Uses monogram badges, not real logos.
"""
import sys, hashlib, colorsys
from PIL import Image, ImageDraw, ImageFont

W, ROW = 1080, 128
F = "/usr/share/fonts/opentype/inter/"
fb = lambda s: ImageFont.truetype(F + "Inter-SemiBold.otf", s)
fr = lambda s: ImageFont.truetype(F + "Inter-Regular.otf", s)
DEPTS = ["Sales", "Media", "Marketing", "Partnerships", "Comms", "Global PR", "Brand"]
OPEN = ["quick question about your creator program", "I'd love to feature one of your latest models",
        "would you be open to sending a car for a review", "I'm reaching out about a review vehicle for",
        "I'd love to try one of your new cars for a video"]

def color(name):
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, 0.65, 0.85)
    return int(r * 255), int(g * 255), int(b * 255)

def fit(d, text, font, maxw):
    if d.textlength(text, font=font) <= maxw: return text
    while text and d.textlength(text + "…", font=font) > maxw: text = text[:-1]
    return text + "…"

def star(d, cx, cy, r, col):
    import math
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5; rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, outline=col, width=3)

def build(brands, subject, out, date="Sep 24"):
    im = Image.new("RGB", (W, ROW * len(brands)), (12, 12, 13))
    d = ImageDraw.Draw(im)
    for i, line in enumerate(brands):
        name, _, dept = line.partition("|")
        dept = dept or DEPTS[i % len(DEPTS)]
        y = i * ROW
        d.line([(0, y + ROW - 1), (W, y + ROW - 1)], fill=(38, 38, 40), width=2)
        cx, cy, r = 78, y + ROW // 2, 42
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color(name))
        ini = "".join(p[0] for p in name.replace("-", " ").split()[:2]).upper()
        f = fb(30 if len(ini) == 1 else 26)
        d.text((cx, cy), ini, font=f, fill="white", anchor="mm")
        x = 150
        d.text((x, y + 18), "To: " + name, font=fb(34), fill="white")
        tw = d.textlength("To: " + name, font=fb(34))
        d.text((x + tw + 10, y + 27), "- " + dept, font=fr(24), fill=(150, 150, 155))
        d.text((W - 40, y + 22), date, font=fr(26), fill=(170, 170, 175), anchor="ra")
        d.text((x, y + 60), subject, font=fb(26), fill=(235, 235, 235))
        prev = f"Hi {name} team, {OPEN[i % len(OPEN)]}"
        d.text((x, y + 93), fit(d, prev, fr(23), W - x - 110), font=fr(23), fill=(140, 140, 145))
        star(d, W - 62, y + 92, 17, (150, 150, 155))
    im.save(out)

if __name__ == "__main__":
    brands = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    build(brands, sys.argv[2], sys.argv[3])
