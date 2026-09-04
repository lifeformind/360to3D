#!/usr/bin/env python
"""Profile camera motion per clip from low-res probe frames.

Prints mean absolute frame difference per sample (0.5fps -> each sample = 2s)
and flags contiguous 'moving' segments, to pick usable capture windows.
Usage: motion_profile.py <probe_dir> [--thresh 6]
"""
import argparse
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--thresh", type=float, default=6.0)
    ap.add_argument("--step-sec", type=float, default=2.0)
    args = ap.parse_args()

    for clip_dir in sorted(p for p in args.dir.iterdir() if p.is_dir()):
        files = sorted(clip_dir.glob("*.jpg"))
        prev = None
        diffs = []
        for f in files:
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE).astype(np.float32)
            diffs.append(0.0 if prev is None else float(np.abs(img - prev).mean()))
            prev = img
        d = np.array(diffs)
        moving = d > args.thresh
        print(f"\n== clip {clip_dir.name}: {len(files)} samples, "
              f"median diff {np.median(d):.1f}, moving {moving.mean()*100:.0f}%")
        # contiguous moving segments
        segs = []
        start = None
        for i, m in enumerate(moving):
            if m and start is None:
                start = i
            elif not m and start is not None:
                segs.append((start, i))
                start = None
        if start is not None:
            segs.append((start, len(moving)))
        for s, e in segs:
            if e - s >= 5:  # >=10s of movement
                print(f"   moving segment: {s*args.step_sec:6.0f}s - {e*args.step_sec:6.0f}s "
                      f"({(e-s)*args.step_sec:.0f}s, mean diff {d[s:e].mean():.1f})")


if __name__ == "__main__":
    main()
