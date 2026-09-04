#!/usr/bin/env python
"""Build a per-clip static-region mask from extracted equirect frames.

For vehicle/rig-mounted 360 captures, anything rigidly attached to the camera
(vehicle hull, mount) stays pixel-identical across frames while the world
moves. Per-pixel temporal std over the clip separates the two: low std =
rig/hull/featureless sky -> masked out (black), rest kept (white).

Writes frames/<scene>/<clip>/mask.png at frame resolution.
Usage: make_masks.py --scene <scene> [--samples 60] [--std-thresh 5]
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

PROJECT_DIR = Path(__file__).resolve().parent.parent


def clip_mask(frame_paths, samples, flow_thresh, motion_thresh=4.0):
    """Median optical-flow magnitude over sampled frame pairs.

    Anything rigid w.r.t. the camera (hull, mount) has near-zero flow even
    when the vehicle vibrates; the world streams past with large flow.
    Plain temporal std fails here: vibration + moving shadows give the hull
    high variance too.
    """
    step = max(1, len(frame_paths) // (samples * 2))
    candidates = frame_paths[::step]
    mags = []
    prev = None
    for p in candidates:
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        g = cv2.resize(g, (1024, 512))
        if prev is not None and np.abs(
            g.astype(np.float32) - prev.astype(np.float32)
        ).mean() > motion_thresh:
            flow = cv2.calcOpticalFlowFarneback(
                prev, g, None, pyr_scale=0.5, levels=4, winsize=21,
                iterations=3, poly_n=7, poly_sigma=1.5, flags=0,
            )
            # Angular flow: horizontal pixels stretch by 1/cos(lat) in
            # equirect, which turns tiny rig vibration into huge pixel flow
            # near the nadir. Normalize so the threshold is latitude-fair.
            h = flow.shape[0]
            lat = np.radians(90 - 180 * (np.arange(h) + 0.5) / h)
            coslat = np.cos(lat)[:, None]
            mags.append(np.sqrt((flow[..., 0] * coslat) ** 2 + flow[..., 1] ** 2))
        prev = g
        if len(mags) >= samples:
            break
    if len(mags) < 10:
        return None, len(mags)
    med = np.median(np.stack(mags), axis=0)
    keep = (med > flow_thresh).astype(np.uint8) * 255
    # Cleanup: close pinholes in kept region, drop small kept islands, then
    # erode so the mask edge sits safely inside the moving world.
    k = np.ones((7, 7), np.uint8)
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, k, iterations=2)
    keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, k, iterations=2)
    keep = cv2.erode(keep, np.ones((5, 5), np.uint8))
    return keep, len(mags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--flow-thresh", type=float, default=4.0)
    args = ap.parse_args()

    frames_dir = PROJECT_DIR / "frames" / args.scene
    clip_dirs = sorted(p for p in frames_dir.iterdir() if p.is_dir())
    if not clip_dirs:
        raise SystemExit(f"no clip dirs under {frames_dir}")

    for clip_dir in clip_dirs:
        frame_paths = sorted(clip_dir.glob("*.jpg"))
        mask, n = clip_mask(frame_paths, args.samples, args.flow_thresh)
        if mask is None:
            raise SystemExit(
                f"{clip_dir.name}: only {n} moving samples — clip too static to mask"
            )
        # Upscale to frame resolution
        ref = cv2.imread(str(frame_paths[0]))
        h, w = ref.shape[:2]
        mask_full = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        out = clip_dir / "mask.png"
        cv2.imwrite(str(out), mask_full)
        kept = (mask > 0).mean() * 100
        print(f"{clip_dir.name}: mask from {n} samples, {kept:.0f}% of sphere kept -> {out}")


if __name__ == "__main__":
    main()
