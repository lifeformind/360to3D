#!/usr/bin/env python
"""Decompose equirectangular frames into overlapping perspective views.

Usage: 02_cubemap.py --scene <scene> [--size 1024] [--fov 110] [--yaws 0,90,180,270]
Reads  frames/<scene>/<clip>/*.jpg for every clip dir of the scene,
writes cubefaces/<scene>/<frame>_Y<yaw>.png (flat dir, ready for COLMAP).

FOV > 90 makes adjacent views overlap so they share feature tracks, which
COLMAP needs to glue the four view directions into one rigid model.
(Exact 90-degree cube faces tile the sphere with zero overlap - reconstruction
falls apart into disconnected components.)

If frames/<scene>/<clip>/mask.png exists (see make_masks.py), an RGBA copy
of each view (alpha = mask) is also written to cubefaces_rgba/<scene>/ —
gaussian-splatting trains masked from those, while COLMAP gets the clean RGB
views (alpha-in-the-SfM-images bakes a black boundary into the image that
generates zero-parallax junk features and kills registration).
"""
import argparse
import multiprocessing as mp
import sys
from pathlib import Path

import cv2
import numpy as np
import py360convert

PROJECT_DIR = Path(__file__).resolve().parent.parent
_mask_cache = {}


def get_mask(clip_dir):
    if clip_dir not in _mask_cache:
        p = Path(clip_dir) / "mask.png"
        _mask_cache[clip_dir] = (
            cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None
        )
    return _mask_cache[clip_dir]


def process_frame(args):
    src, out_dir, rgba_dir, size, fov, yaws, pitches = args
    img = cv2.imread(str(src))
    if img is None:
        return f"READ_FAIL {src}"
    mask = get_mask(str(src.parent))
    stem = src.stem
    for yaw in yaws:
        for pitch in pitches:
            view = py360convert.e2p(
                img, fov_deg=(fov, fov), u_deg=yaw, v_deg=pitch,
                out_hw=(size, size), mode="bilinear",
            )
            suffix = f"Y{yaw:03d}" if pitch == 0 else f"Y{yaw:03d}P{pitch:+03d}"
            name = f"{stem}_{suffix}"
            if mask is not None:
                mview = py360convert.e2p(
                    np.repeat(mask[..., None], 3, axis=2),
                    fov_deg=(fov, fov), u_deg=yaw, v_deg=pitch,
                    out_hw=(size, size), mode="nearest",
                )[..., 0]
                mview = (mview > 127).astype(np.uint8) * 255
                cv2.imwrite(str(rgba_dir / f"{name}.png"),
                            np.dstack([view, mview]))
            cv2.imwrite(str(out_dir / f"{name}.png"), view)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--fov", type=float, default=110.0)
    ap.add_argument("--yaws", default="0,90,180,270")
    ap.add_argument("--pitches", default="0",
                    help="extra pitch angles per yaw, e.g. 0,-30")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    yaws = [int(y) for y in args.yaws.split(",")]
    pitches = [int(p) for p in args.pitches.split(",")]

    frames_dir = PROJECT_DIR / "frames" / args.scene
    out_dir = PROJECT_DIR / "cubefaces" / args.scene
    rgba_dir = PROJECT_DIR / "cubefaces_rgba" / args.scene
    out_dir.mkdir(parents=True, exist_ok=True)
    rgba_dir.mkdir(parents=True, exist_ok=True)

    srcs = sorted(frames_dir.glob("*/*.jpg"))
    if not srcs:
        sys.exit(f"no frames found under {frames_dir}")

    tasks = [(s, out_dir, rgba_dir, args.size, args.fov, yaws, pitches) for s in srcs]
    failures = []
    with mp.Pool(args.workers) as pool:
        for i, res in enumerate(pool.imap_unordered(process_frame, tasks, chunksize=8)):
            if res:
                failures.append(res)
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{len(tasks)} frames", flush=True)

    if failures:
        sys.exit(f"{len(failures)} frames failed: {failures[:5]}")
    n_out = len(list(out_dir.glob("*.png"))) + len(list(out_dir.glob("*.jpg")))
    print(f"Wrote {n_out} perspective views to {out_dir}")


if __name__ == "__main__":
    main()
