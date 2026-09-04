#!/usr/bin/env python3
"""Windowed SuperPoint+LightGlue matching over the vehicle-locked views.

Pairs: same-yaw frames at offsets 1..6, and adjacent-yaw (90 deg) frames at
offsets 1..3. Same-frame pairs are excluded (zero baseline poisons mapping).
Outputs hloc features/matches h5 + pairs list under colmap_db/<scene>/ba/.

Usage: 13_hloc_windowed.py <scene>
"""
import sys
from pathlib import Path

from hloc import extract_features, match_features

def main(scene):
    root = Path(f"colmap_db/{scene}/ba")
    root.mkdir(parents=True, exist_ok=True)
    images = Path(f"cubefaces/{scene}")
    names = sorted(p.name for p in images.glob("*.png"))
    # name: c04_00001_Y000.png
    def key(n):
        stem = n.rsplit(".", 1)[0]
        clip_frame, yaw = stem.rsplit("_", 1)
        return clip_frame, int(yaw[1:])
    by_frame = {}
    for n in names:
        cf, yaw = key(n)
        by_frame.setdefault(cf, {})[yaw] = n
    frames = sorted(by_frame)
    pairs = []
    ADJ = {0: (90, 270), 90: (0, 180), 180: (90, 270), 270: (180, 0)}
    for i, cf in enumerate(frames):
        for off in range(1, 7):
            if i + off >= len(frames):
                break
            cf2 = frames[i + off]
            for yaw in (0, 90, 180, 270):
                a, b = by_frame[cf].get(yaw), by_frame[cf2].get(yaw)
                if a and b:
                    pairs.append((a, b))
            if off <= 3:
                for yaw in (0, 90, 180, 270):
                    a = by_frame[cf].get(yaw)
                    for y2 in ADJ[yaw]:
                        b = by_frame[cf2].get(y2)
                        if a and b:
                            pairs.append((a, b))
    # dedupe unordered
    seen = set(); uniq = []
    for a, b in pairs:
        k = (a, b) if a < b else (b, a)
        if k not in seen:
            seen.add(k); uniq.append((a, b))
    pairs_path = root / "pairs_windowed.txt"
    with open(pairs_path, "w") as f:
        for a, b in uniq:
            f.write(f"{a} {b}\n")
    print(f"{len(names)} images, {len(uniq)} pairs -> {pairs_path}")

    feat_conf = extract_features.confs["superpoint_aachen"]
    match_conf = match_features.confs["superpoint+lightglue"]
    feats = extract_features.main(feat_conf, images, export_dir=root)
    matches = match_features.main(match_conf, pairs_path, feat_conf["output"], export_dir=root)
    print("features:", feats, "\nmatches:", matches)

if __name__ == "__main__":
    main(sys.argv[1])
