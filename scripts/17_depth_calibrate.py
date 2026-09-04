#!/usr/bin/env python3
"""Per-frame LingBot depth-scale calibration from the ground plane.

LingBot's depth head and position head have different (and drifting) scales;
the trajectory-derived m_per_recon_unit does NOT apply to depth (measured
~5-8x off via road-distance sanity check). The camera sits at a known height
above the local road plane, which anchors metric depth: for road-band pixels
the true depth along the ray is h / sin(depression angle). kappa_i =
median(true/predicted) per frame, smoothed along the drive.

Usage: 17_depth_calibrate.py <scene> <camera_height_m> <out_npy>
"""
import sys
import numpy as np
from scipy.ndimage import gaussian_filter1d

def main(scene, h, out_npy):
    h = float(h)
    d = np.load(f'colmap_db/{scene}/snapped/poses_snapped.npz', allow_pickle=True)
    K = d['intrinsic']
    fx, cy = K[0, 0], K[1, 2]
    N = len(d['c2w'])
    # forward-view pitch relative to horizontal, from the pose (camera z-axis)
    fwd = d['c2w'][:, :3, 2]
    pitch = np.arcsin(np.clip(-fwd[:, 2], -1, 1))   # + = looking down

    kappas = np.full(N, np.nan)
    ROWS = np.arange(int(cy) + 60, 440)             # below horizon, above hood
    COLS = slice(150, 370)
    for i in range(N):
        z = np.load(f'colmap_db/{scene}/lingbot_out/{scene}_fwd/frame_{i:06d}.npz')
        depth = z['depth'][..., 0]
        conf = z['depth_conf']
        ratios = []
        for v in ROWS[::6]:
            dep = np.arctan((v - cy) / fx) + pitch[i]
            if dep <= np.radians(2):
                continue
            true_d = h / np.sin(dep)
            band = depth[v, COLS]; cb = conf[v, COLS]
            ok = cb > 1.5
            if ok.sum() < 20:
                continue
            ratios.append(true_d / np.median(band[ok]))
        if ratios:
            kappas[i] = np.median(ratios)
        if (i + 1) % 300 == 0:
            v = kappas[~np.isnan(kappas)]
            print(f"  {i+1}/{N}: kappa p50 so far {np.median(v):.2f}")
    valid = ~np.isnan(kappas)
    print(f"frames calibrated: {valid.sum()}/{N}")
    idx = np.arange(N)
    kappas = np.interp(idx, idx[valid], kappas[valid])
    kappas_s = gaussian_filter1d(kappas, 5)
    print(f"kappa (m per depth-unit) p10/p50/p90: "
          f"{np.percentile(kappas_s,10):.2f}/{np.percentile(kappas_s,50):.2f}/{np.percentile(kappas_s,90):.2f}")
    np.save(out_npy, kappas_s)
    print("wrote", out_npy)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
