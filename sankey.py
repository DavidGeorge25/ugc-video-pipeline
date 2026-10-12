"""SankeyMATIC-style 3-column flow chart. Renders PNG at high res + node boxes JSON.
Usage: python3 sankey.py config.json out_prefix
"""
import json, sys, asyncio
from playwright.async_api import async_playwright

W, H = 2000, 1200
X = [275, 962, 1650]          # node left edges per column
NW = 50                       # node width
COL_H = 409                   # column-1 total height (px)
GAP = 117                     # gap between nodes in a column
TOP2 = 141                    # top of column 2
OP = 0.45                     # link opacity
FONT = "'Liberation Sans', Arial, Helvetica, sans-serif"

def layout(cfg):
    src = cfg["source"]; mids = cfg["mid"]; ends = cfg["end"]; parent = cfg["end_parent"]
    total = src["value"]
    k = COL_H * 0.995 / total
    mid_sum = sum(m["value"] for m in mids)
    col2_h = mid_sum * k + GAP * (len(mids) - 1)
    # column 1 centered relative to column 2 like the reference (530 vs 520)
    src_top = TOP2 + col2_h / 2 + 10 - total * k / 2
    nodes = {"__src": dict(src, col=0, x=X[0], y=src_top, h=total * k)}
    y = TOP2
    for m in mids:
        nodes[m["label"]] = dict(m, col=1, x=X[1], y=y, h=m["value"] * k); y += m["value"] * k + GAP
    p = nodes[parent]
    end_h = sum(e["value"] for e in ends) * k + GAP * (len(ends) - 1)
    y = p["y"] + p["h"] / 2 + 40 - end_h / 2
    y = min(y, H - 140 - end_h)
    for e in ends:
        nodes[e["label"]] = dict(e, col=2, x=X[2], y=y, h=max(e["value"] * k, 3)); y += e["value"] * k + GAP
    links = []
    sy = nodes["__src"]["y"]
    for m in mids:
        n = nodes[m["label"]]; links.append((X[0] + NW, sy, n["x"], n["y"], m["value"] * k, n["color"])); sy += m["value"] * k
    sy = p["y"]
    for e in ends:
        n = nodes[e["label"]]; links.append((X[1] + NW, sy, n["x"], n["y"], e["value"] * k, n["color"])); sy += e["value"] * k
    return nodes, links

def svg(cfg):
    nodes, links = layout(cfg)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<rect width="{W}" height="{H}" fill="#fff"/>']
    for x0, y0, x1, y1, w, c in links:
        xm = (x0 + x1) / 2
        d = (f"M{x0},{y0} C{xm},{y0} {xm},{y1} {x1},{y1} L{x1},{y1+w} "
             f"C{xm},{y1+w} {xm},{y0+w} {x0},{y0+w} Z")
        o.append(f'<path d="{d}" fill="{c}" fill-opacity="{OP}"/>')
    for key, n in nodes.items():
        o.append(f'<rect x="{n["x"]}" y="{n["y"]:.2f}" width="{NW}" height="{n["h"]:.2f}" fill="{n["color"]}"/>')
        cy = n["y"] + n["h"] / 2
        if n["col"] == 0:
            tx, anchor = n["x"] - 20, "end"
        else:
            tx, anchor = n["x"] + NW + 20, "start"
        o.append(f'<text x="{tx}" y="{cy-6:.1f}" font-family="{FONT}" font-size="54" text-anchor="{anchor}" fill="#000">{n["value"]:,}</text>')
        o.append(f'<text x="{tx}" y="{cy+44:.1f}" font-family="{FONT}" font-size="40" text-anchor="{anchor}" fill="#000">{n["label"]}</text>')
    if cfg.get("credit", True):
        o.append(f'<text x="{W/2}" y="1190" font-family="{FONT}" font-size="22" text-anchor="middle" fill="#336781">{cfg.get("credit_text","")}</text>')
    o.append("</svg>")
    return "\n".join(o), nodes

async def render(svg_s, out_png, scale):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium" if False else None)
        pg = await b.new_page(viewport={"width": W, "height": H}, device_scale_factor=scale)
        await pg.set_content(f"<html><body style='margin:0'>{svg_s}</body></html>")
        await pg.screenshot(path=out_png, clip={"x": 0, "y": 0, "width": W, "height": H})
        await b.close()

def build(cfg, prefix, scale=4):
    s, nodes = svg(cfg)
    open(prefix + ".svg", "w").write(s)
    asyncio.run(render(s, prefix + ".png", scale))
    boxes = {("Emails Sent" if k == "__src" else k): {kk: n[kk] for kk in ("x", "y", "h", "col", "value")} for k, n in nodes.items()}
    boxes["__scale"] = scale
    json.dump(boxes, open(prefix + ".json", "w"), indent=1)
    return boxes

if __name__ == "__main__":
    build(json.load(open(sys.argv[1])), sys.argv[2])
