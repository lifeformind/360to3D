#!/usr/bin/env python
"""Phase A of the hloc rematch: SuperPoint features + LightGlue matches -> H5.

Pairs = sequential window (32, quadratic) + top-k retrieval loop closures
(EigenPlaces global descriptors). DB import happens separately (phase B)
under the GLOMAP-compatible pycolmap.
"""
from pathlib import Path

from hloc import extract_features, match_features, pairs_from_retrieval

ROOT = Path("/home/ldrgx10/360_to_3D")
IMAGES = ROOT / "cubefaces/amakeng"
OUT = ROOT / "colmap_db/amakeng_hloc"
OUT.mkdir(parents=True, exist_ok=True)


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
    return pairs


def main():
    image_list = sorted(p.name for p in IMAGES.glob("*.png"))
    print(f"{len(image_list)} images", flush=True)

    feature_conf = extract_features.confs["superpoint_aachen"]
    matcher_conf = match_features.confs["superpoint+lightglue"]
    retrieval_conf = extract_features.confs["openibl"]

    features = extract_features.main(feature_conf, IMAGES, OUT, image_list=image_list)
    print("local features done", flush=True)

    global_feats = extract_features.main(retrieval_conf, IMAGES, OUT, image_list=image_list)
    retr_pairs_path = OUT / "pairs_retrieval.txt"
    pairs_from_retrieval.main(global_feats, retr_pairs_path, num_matched=10)
    print("retrieval pairs done", flush=True)

    pairs = sequential_pairs(image_list)
    for line in retr_pairs_path.read_text().splitlines():
        a, b = line.split()
        if (b, a) not in pairs:
            pairs.add((a, b))
    pairs = sorted(pairs)
    (OUT / "pairs.txt").write_text("\n".join(f"{a} {b}" for a, b in pairs))
    print(f"{len(pairs)} total pairs", flush=True)

    match_features.main(matcher_conf, OUT / "pairs.txt", feature_conf["output"], OUT)
    print("PHASE_A_DONE", flush=True)


if __name__ == "__main__":
    main()
