"""Overnight batch: render every job, auto-review, write a summary.
jobs.json: [{"config": "videos/<name>.json", "raw": ["part1.mov", "part2.mov"]}, ...]
python3 batch.py jobs.json out_root"""
import json, os, sys, traceback, time
from prep import prepare_raw, share_copy
import make

def run(jobs_path, out_root):
    jobs = json.load(open(jobs_path)); base = os.path.dirname(os.path.abspath(jobs_path))
    os.makedirs(out_root, exist_ok=True); summary = []
    for j in jobs:
        cfg_path = os.path.join(base, j["config"]); name = json.load(open(cfg_path)).get("name", os.path.basename(cfg_path))
        od = os.path.join(out_root, name); os.makedirs(od, exist_ok=True); t0 = time.time()
        try:
            raw = os.path.join(od, "raw.mp4")
            if not os.path.exists(raw): prepare_raw([os.path.join(base, r) if not os.path.isabs(r) else r for r in j["raw"]], raw)
            make.main(cfg_path, raw, od)
            rep = open(os.path.join(od, "review.txt")).read()
            final = [f for f in os.listdir(od) if f.endswith("_varispeed.mp4") or f.endswith("_x1.25.mp4")]
            share = share_copy(os.path.join(od, final[0]), os.path.join(out_root, f"{name}.mp4")) if final else None
            summary.append(dict(name=name, status="PASS" if "REVIEW PASS" in rep else "FAIL", review=rep, share=share, mins=round((time.time() - t0) / 60, 1)))
        except Exception:
            summary.append(dict(name=name, status="ERROR", review=traceback.format_exc()[-1500:], share=None, mins=round((time.time() - t0) / 60, 1)))
        json.dump(summary, open(os.path.join(out_root, "summary.json"), "w"), indent=1)
    return summary

if __name__ == "__main__":
    for s in run(sys.argv[1], sys.argv[2]): print(s["status"], s["name"], s["share"], "\n", s["review"])
