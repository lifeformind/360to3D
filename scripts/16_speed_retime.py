#!/usr/bin/env python3
"""Re-time frame positions along the route from observed optical flow.

The arc-length/DTW mapping placed frames on the route with locally wrong
spacing (instantaneous baselines off by 2-3x), which makes nearby training
views geometrically contradictory at the tens-of-pixels level (measured).
For every consecutive forward-view pair this script searches the step-length
scale that minimizes the median disagreement between depth+pose-predicted
flow and Farneback optical flow, then redistributes cumulative arc length
along the route and rebuilds poses (positions on route, forward = tangent,
pitch/roll kept).

Usage: 16_speed_retime.py <scene> <out_npz>
"""
import sys, os, json
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d

RES = 512
STEP = 8

def main(scene, out_npz):
    d = np.load(f'colmap_db/{scene}/snapped/poses_snapped.npz', allow_pickle=True)
    c2w = d['c2w'].copy()
    scale = float(d['m_per_recon_unit'])
    m_per_px = float(d['m_per_px'])
    K518 = d['intrinsic']
    N = len(c2w)
    Kl = K518.copy(); Kl[:2] *= (RES / 518)

    route = json.load(open(f'colmap_db/{scene}/route_polyline.json'))
    Rpts = np.array(route['points_px']) * np.array([1.0, -1.0]) * m_per_px
    rseg = np.linalg.norm(np.diff(Rpts, axis=0), axis=1)
    rs = np.concatenate([[0], np.cumsum(rseg)])

    def load_gray(i):
        img = cv2.imread(f'cubefaces/{scene}_fwd/c04_{i+1:05d}.png', cv2.IMREAD_GRAYSCALE)
        return cv2.resize(img, (RES, RES))

    ys, xs = np.mgrid[0:RES:STEP, 0:RES:STEP].astype(np.float64)
    scales = np.ones(N - 1)
    prev = load_gray(0)
    zcache = np.load(f'colmap_db/{scene}/lingbot_out/{scene}_fwd/frame_{0:06d}.npz')
    for i in range(N - 1):
        cur = load_gray(i + 1)
        z = zcache
        zcache = np.load(f'colmap_db/{scene}/lingbot_out/{scene}_fwd/frame_{i+1:06d}.npz')
        depth = cv2.resize(z['depth'][..., 0] * scale, (RES, RES))
        conf = cv2.resize(z['depth_conf'], (RES, RES), interpolation=cv2.INTER_NEAREST)
        zs = depth[::STEP, ::STEP]
        ok = (zs > 1) & (zs < 80) & (conf[::STEP, ::STEP] > 1.5)
        if ok.sum() < 50:
            prev = cur
            continue
        fl = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 4, 25, 3, 7, 1.5, 0)
        fp = fl[::STEP, ::STEP]
        sane = ok & (np.abs(fp).max(-1) < RES * 0.2)
        if sane.sum() < 50:
            prev = cur
            continue
        pc = np.stack([(xs - Kl[0,2]) / Kl[0,0] * zs, (ys - Kl[1,2]) / Kl[1,1] * zs, zs], -1)
        T0, T1 = c2w[i], c2w[i + 1]
        R0, C0 = T0[:3,:3], T0[:3,3]
        R1, C1 = T1[:3,:3], T1[:3,3]
        base = C1 - C0
        def err(s):
            C1s = C0 + base * s
            pw = pc @ R0.T + C0
            pl = (pw - C1s) @ R1
            good = pl[..., 2] > 0.5
            uv = (pl[..., :2] / np.maximum(pl[..., 2:3], 1e-6)) * [Kl[0,0], Kl[1,1]] + [Kl[0,2], Kl[1,2]]
            fg = np.stack([uv[..., 0] - xs, uv[..., 1] - ys], -1)
            m = sane & good
            if m.sum() < 50:
                return 1e9
            return float(np.median(np.linalg.norm(fg[m] - fp[m], axis=-1)))
        # golden-ish grid search then refine
        ss = np.linspace(0.05, 3.0, 24)
        es = [err(s) for s in ss]
        s0 = ss[int(np.argmin(es))]
        for w in (0.3, 0.1):
            ss = np.linspace(max(0.02, s0 - w), s0 + w, 9)
            es = [err(s) for s in ss]
            s0 = ss[int(np.argmin(es))]
        scales[i] = s0
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{N-1} pairs, recent scale p50={np.median(scales[max(0,i-200):i+1]):.2f}")
        prev = cur

    scales = np.clip(scales, 0.05, 3.0)
    scales_s = gaussian_filter1d(scales, 2)
    steps_old = np.linalg.norm(np.diff(c2w[:, :2, 3], axis=0), axis=1)
    steps_new = steps_old * scales_s
    total_new = steps_new.sum()
    print(f"speed rescale: p50={np.percentile(scales_s,50):.2f} p10={np.percentile(scales_s,10):.2f} p90={np.percentile(scales_s,90):.2f}")
    print(f"total path: {steps_old.sum():.0f} m -> {total_new:.0f} m (route {rs[-1]:.0f} m)")
    # renormalize so the drive still spans the full route
    arc = np.concatenate([[0], np.cumsum(steps_new)]) * (rs[-1] / total_new)

    P = np.stack([np.interp(arc, rs, Rpts[:, 0]), np.interp(arc, rs, Rpts[:, 1])], 1)
    Ps = gaussian_filter1d(P, 5, axis=0, mode='nearest')
    tang = np.gradient(Ps, axis=0)
    new_bear = np.arctan2(tang[:, 1], tang[:, 0])
    old_pos = c2w[:, :2, 3]
    fwd = c2w[:, :3, 2]
    old_bear = np.arctan2(fwd[:, 1], fwd[:, 0])
    dpsi = np.unwrap(new_bear) - np.unwrap(old_bear)
    dpsi = gaussian_filter1d(dpsi, 8)
    for i in range(N):
        cz, sz = np.cos(dpsi[i]), np.sin(dpsi[i])
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        c2w[i, :3, :3] = Rz @ c2w[i, :3, :3]
        c2w[i, 0, 3], c2w[i, 1, 3] = P[i]
    np.savez(out_npz, c2w=c2w, intrinsic=d['intrinsic'], m_per_px=m_per_px,
             m_per_recon_unit=scale, names=d['names'], step_scales=scales_s)
    print("wrote", out_npz)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
