# UGC video pipeline (Hedwig "free car" format)

Raw one-take phone footage + script -> finished 1080x1920 TikTok/Reels video, auto-reviewed.

    ./setup.sh                                   # once per fresh machine/session
    python3 make.py videos/<name>.json raw.mp4 out/<name>     # one video
    python3 batch.py jobs.json out/                           # many videos (overnight)
    python3 review.py out/<name>/<final>.mp4 videos/<name>.json  # re-check any render

See SKILL notes in the "hedwig-ugc-video" skill for the full house style and rules.
