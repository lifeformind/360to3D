#!/usr/bin/env python
"""Phase B: import hloc features/matches into a GLOMAP-compatible database.

Must run under venv2 (pycolmap built from the GLOMAP-pinned COLMAP commit) so
the database schema matches what the bundled GLOMAP/COLMAP can read.
"""
from pathlib import Path

import pycolmap
from hloc.reconstruction import create_empty_db, import_images, get_image_ids
from hloc.triangulation import (
    import_features,
    import_matches,
    estimation_and_geometric_verification,
)

ROOT = Path("/home/ldrgx10/360_to_3D")
IMAGES = ROOT / "cubefaces/amakeng"
OUT = ROOT / "colmap_db/amakeng_hloc"
FEATURES = OUT / "feats-superpoint-n4096-r1024.h5"
MATCHES = OUT / "feats-superpoint-n4096-r1024_matches-superpoint-lightglue_pairs.h5"
PAIRS = OUT / "pairs.txt"


def main():
    print("pycolmap", pycolmap.__version__)
    matches = MATCHES
    if not matches.exists():
        cands = list(OUT.glob("*matches*.h5"))
        assert cands, "no matches h5 found"
        matches = cands[0]
    print("using matches file:", matches.name)

    image_list = sorted(p.name for p in IMAGES.glob("*.png"))
    db_path = OUT / "database.db"
    if db_path.exists():
        db_path.unlink()
    create_empty_db(db_path)
    import_images(
        IMAGES, db_path, pycolmap.CameraMode.SINGLE, image_list=image_list,
        options={
            "camera_model": "PINHOLE",
            "camera_params": "358.6003,358.6003,512,512",
        },
    )
    image_ids = get_image_ids(db_path)
    print(len(image_ids), "images in db")
    try:
        db = pycolmap.Database.open(db_path)
    except AttributeError:
        db = pycolmap.Database(db_path)
    import_features(image_ids, db, FEATURES)
    import_matches(image_ids, db, PAIRS, matches,
                   min_match_score=None, skip_geometric_verification=True)
    db.close()
    estimation_and_geometric_verification(db_path, PAIRS)
    print("PHASE_B_DONE ->", db_path)


if __name__ == "__main__":
    main()
