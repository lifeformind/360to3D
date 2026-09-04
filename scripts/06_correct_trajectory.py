#!/usr/bin/env python3
"""Correct low-frequency scale drift in a reconstruction's trajectory.

The GLOMAP model of the AMAKENG drive has smooth ~120x scale drift along the
driving corridor (real speed is roughly constant). Per driving clip:
  1. take per-frame centers (Y000 view of each frame; all 4 yaw views share
     the physical optical center),
  2. compute step lengths, low-pass filter log(length) -> the drift profile
     (high-frequency speed changes like stops are kept),
  3. rescale each step to remove the drift profile, keeping step directions,
  4. re-integrate the trajectory and move every yaw view of each frame by
     its frame's correction delta.
Rotations are left untouched. Static clips (c02) are left untouched.
Points must be re-triangulated against the corrected poses afterwards.

Usage: 06_correct_trajectory.py <input_model_dir> <output_model_dir>
"""
import sys, re
import numpy as np
import pycolmap

SIGMA_FRAMES = 15          # low-pass width for the drift profile
STATIC_CLIPS = {"c02"}     # leave untouched

def gaussian_smooth(x, sigma):
    r = int(4 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    xp = np.pad(x, r, mode="edge")
    return np.convolve(xp, k, mode="valid")

def main(inp, outp):
    rec = pycolmap.Reconstruction(inp)
    print(f"loaded {rec.num_reg_images()} images, {len(rec.points3D)} points")

    # group images by (clip, frame_number); collect per-frame member images
    frames = {}
    pat = re.compile(r"(c\d+)_(\d+)_Y\d+\.png$")
    for img in rec.images.values():
        if not img.has_pose:
            continue
        m = pat.search(img.name)
        if not m:
            raise SystemExit(f"unparseable image name {img.name}")
        frames.setdefault((m.group(1), int(m.group(2))), []).append(img)

    deltas = {}  # (clip, frame) -> world-space correction of the center
    for clip in sorted({c for c, _ in frames}):
        if clip in STATIC_CLIPS:
            continue
        keys = sorted(k for k in frames if k[0] == clip)
        centers = np.array([np.mean([im.projection_center() for im in frames[k]], axis=0) for k in keys])
        nums = np.array([k[1] for k in keys])
        steps = np.diff(centers, axis=0)
        lens = np.linalg.norm(steps, axis=1)
        lens = np.maximum(lens, 1e-9)
        drift = np.exp(gaussian_smooth(np.log(lens), SIGMA_FRAMES))
        target = np.median(lens / drift * np.median(drift))  # constant nominal speed
        scale = drift / np.median(drift)                     # low-freq scale error, ~1 on average
        new_steps = steps / scale[:, None]
        # frame-number gaps (window cuts): keep the original relative jump, rescaled
        gap = np.diff(nums) != 1
        new_centers = np.empty_like(centers)
        new_centers[0] = centers[0]
        for i in range(len(steps)):
            new_centers[i + 1] = new_centers[i] + new_steps[i]
        for k, c0, c1 in zip(keys, centers, new_centers):
            deltas[k] = c1 - c0
        l0, l1 = lens, np.linalg.norm(new_steps, axis=1)
        print(f"{clip}: {len(keys)} frames; step p10/p50/p90 "
              f"before {np.percentile(l0,10):.4f}/{np.percentile(l0,50):.4f}/{np.percentile(l0,90):.4f} "
              f"after {np.percentile(l1,10):.4f}/{np.percentile(l1,50):.4f}/{np.percentile(l1,90):.4f} "
              f"(p90/p10 {np.percentile(l0,90)/max(np.percentile(l0,10),1e-9):.1f}x -> "
              f"{np.percentile(l1,90)/max(np.percentile(l1,10),1e-9):.1f}x)")

    # apply per-frame deltas to every member image pose
    moved = 0
    for key, imgs in frames.items():
        d = deltas.get(key)
        if d is None:
            continue
        for img in imgs:
            frame = rec.frames[img.frame_id]
            rfw = frame.rig_from_world
            R = rfw.rotation.matrix()
            t_new = rfw.translation - R @ d
            frame.rig_from_world = pycolmap.Rigid3d(rfw.rotation, t_new)
            moved += 1
    print(f"moved {moved} image poses")

    # points are now stale; drop them (re-triangulated by the next stage)
    for pid in list(rec.points3D):
        rec.delete_point3D(pid)
    import os
    os.makedirs(outp, exist_ok=True)
    rec.write(outp)
    print(f"written to {outp}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
