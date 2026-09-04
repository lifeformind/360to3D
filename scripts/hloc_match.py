#!/usr/bin/env python
"""SuperPoint + LightGlue matching via hloc, writing into a COLMAP database.

Alternative matcher for low-texture scenes where SIFT struggles.
Produces the same database.db layout stage 03 expects, so the COLMAP mapper
can run on top of it.

Usage: hloc_match.py --images <dir> --workdir <dir> --camera_params fx,fy,cx,cy
"""
import argparse
from pathlib import Path

from hloc import extract_features, match_features
from hloc.reconstruction import create_empty_db, import_images, get_image_ids
from hloc.triangulation import (
    import_features,
    import_matches,
    estimation_and_geometric_verification,
)
import pycolmap


def sequential_pairs(names, window=32, quadratic=True):
    pairs = set()
    n = len(names)
    for i in range(n):
        for d in range(1, window + 1):
            if i + d < n:
                pairs.add((names[i], names[i + d]))
        if quadratic:
            d = window * 2
            while i + d < n:
                pairs.add((names[i], names[i + d]))
                d *= 2
    return sorted(pairs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--camera_params", required=True)
    ap.add_argument("--window", type=int, default=32)
    args = ap.parse_args()

    out = args.workdir / "hloc"
    out.mkdir(parents=True, exist_ok=True)
    sfm_pairs = out / "pairs.txt"

    image_list = sorted(p.name for p in args.images.glob("*.jpg"))
    print(f"{len(image_list)} images")

    feature_conf = extract_features.confs["superpoint_aachen"]
    matcher_conf = match_features.confs["superpoint+lightglue"]

    features = extract_features.main(
        feature_conf, args.images, out, image_list=image_list
    )
    pairs = sequential_pairs(image_list, window=args.window)
    sfm_pairs.write_text("\n".join(f"{a} {b}" for a, b in pairs))
    print(f"{len(pairs)} sequential pairs")
    matches = match_features.main(
        matcher_conf, sfm_pairs, feature_conf["output"], out
    )

    db_path = args.workdir / "database.db"
    if db_path.exists():
        db_path.unlink()
    create_empty_db(db_path)
    import_images(
        args.images, db_path, pycolmap.CameraMode.SINGLE, image_list=image_list,
        options={
            "camera_model": "PINHOLE",
            "camera_params": args.camera_params,
        },
    )
    image_ids = get_image_ids(db_path)
    db = pycolmap.Database.open(db_path)
    import_features(image_ids, db, features)
    import_matches(image_ids, db, sfm_pairs, matches,
                   min_match_score=None, skip_geometric_verification=True)
    db.close()
    estimation_and_geometric_verification(db_path, sfm_pairs)
    print("hloc matching complete ->", db_path)


if __name__ == "__main__":
    main()
