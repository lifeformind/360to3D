#!/usr/bin/env python3
"""Re-time frame spacing along the route from SuperPoint matches + depth.

Same goal as 16_speed_retime.py but using verified sparse matches (robust to
large inter-frame motion, unlike dense flow): for each consecutive Y000 pair,
find the step-length scale minimizing the median distance between
depth-projected keypoints and their matched positions.

Usage: 16b_match_retime.py <scene> <out_npz>
"""
import sys, json
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d
from hloc.utils.io import get_matches
import h5py

def main(scene, out_npz, kappa_npy=None):
    d = np.load(f'colmap_db/{scene}/snapped/poses_snapped.npz', allow_pickle=True)
    c2w = d['c2w'].copy()
    scale = float(d['m_per_recon_unit'])
    kappa = np.load(kappa_npy) if kappa_npy else None
    m_per_px = float(d['m_per_px'])
    K518 = d['intrinsic']
    N = len(c2w)
    K1024 = K518.copy(); K1024[:2] *= (1024 / 518)

    feats = f'colmap_db/{scene}/ba/feats-superpoint-n4096-r1024.h5'
    matches = f'colmap_db/{scene}/ba/feats-superpoint-n4096-r1024_matches-superpoint-lightglue_pairs_windowed.h5'

    route = json.load(open(f'colmap_db/{scene}/route_polyline.json'))
    Rpts = np.array(route['points_px']) * np.array([1.0, -1.0]) * m_per_px
    rs = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(Rpts, axis=0), axis=1))])

    scales = np.full(N - 1, np.nan)
    for i in range(N - 1):
        n0, n1 = f'c04_{i+1:05d}_Y000.png', f'c04_{i+2:05d}_Y000.png'
        try:
            m, sc = get_matches(matches, n0, n1)
        except Exception:
            continue
        if len(m) < 30:
            continue
        import h5py
        with h5py.File(feats, 'r') as f:
            kp0 = f[n0]['keypoints'][()]
            kp1 = f[n1]['keypoints'][()]
        p0 = kp0[m[:, 0]].astype(np.float64)
        p1 = kp1[m[:, 1]].astype(np.float64)
        # exclude hull/sky keypoints via the alpha masks (static hull matches
        # are perfectly self-consistent and poison every motion estimate)
        a0 = cv2.imread(f'cubefaces_rgba/{scene}/{n0}', cv2.IMREAD_UNCHANGED)[..., 3]
        a1 = cv2.imread(f'cubefaces_rgba/{scene}/{n1}', cv2.IMREAD_UNCHANGED)[..., 3]
        w0 = a0[np.clip(p0[:,1].astype(int),0,1023), np.clip(p0[:,0].astype(int),0,1023)] > 127
        w1 = a1[np.clip(p1[:,1].astype(int),0,1023), np.clip(p1[:,0].astype(int),0,1023)] > 127
        world = w0 & w1
        if world.sum() < 30:
            continue
        p0, p1 = p0[world], p1[world]
        z = np.load(f'colmap_db/{scene}/lingbot_out/{scene}_fwd/frame_{i:06d}.npz')
        depth518 = z['depth'][..., 0] * (kappa[i] if kappa is not None else scale)
        conf518 = z['depth_conf']
        u5 = np.clip((p0[:, 0] * 518 / 1024).astype(int), 0, 517)
        v5 = np.clip((p0[:, 1] * 518 / 1024).astype(int), 0, 517)
        zs = depth518[v5, u5]
        ok = (zs > 1) & (zs < 80) & (conf518[v5, u5] > 1.5)
        if ok.sum() < 30:
            continue
        p0k, p1k, zk = p0[ok], p1[ok], zs[ok]
        pc = np.stack([(p0k[:, 0] - K1024[0, 2]) / K1024[0, 0] * zk,
                       (p0k[:, 1] - K1024[1, 2]) / K1024[1, 1] * zk, zk], 1)
        T0, T1 = c2w[i], c2w[i + 1]
        R0, C0 = T0[:3, :3], T0[:3, 3]
        R1, C1 = T1[:3, :3], T1[:3, 3]
        base = C1 - C0
        if np.linalg.norm(base) < 0.3:
            # degenerate snapped spacing: fall back to smoothed local direction
            j0, j1 = max(0, i - 3), min(N - 1, i + 4)
            base = c2w[j1, :3, 3] - c2w[j0, :3, 3]
            nb = np.linalg.norm(base)
            if nb < 0.5:
                continue
            base = base / nb * 2.0
        pw = pc @ R0.T + C0
        def err(s):
            pl = (pw - (C0 + base * s)) @ R1
            good = pl[:, 2] > 0.5
            if good.sum() < 20:
                return 1e9
            uv = (pl[good, :2] / pl[good, 2:3]) * [K1024[0, 0], K1024[1, 1]] + [K1024[0, 2], K1024[1, 2]]
            return float(np.median(np.linalg.norm(uv - p1k[good], axis=1)))
        ss = np.linspace(0.05, 4.0, 32)
        es = [err(s) for s in ss]
        s0 = ss[int(np.argmin(es))]
        for w in (0.3, 0.1, 0.03):
            ss = np.linspace(max(0.01, s0 - w), s0 + w, 9)
            es = [err(s) for s in ss]
            s0 = ss[int(np.argmin(es))]
        scales[i] = s0
        if (i + 1) % 200 == 0:
            v = scales[~np.isnan(scales)]
            print(f"  {i+1}/{N-1}: scale p50 so far {np.median(v):.2f}")

    valid = ~np.isnan(scales)
    print(f"pairs with estimate: {valid.sum()}/{N-1}")
    idx = np.arange(N - 1)
    scales = np.interp(idx, idx[valid], scales[valid])
    scales_s = gaussian_filter1d(np.clip(scales, 0.02, 4.0), 2)
    steps_old = np.linalg.norm(np.diff(c2w[:, :2, 3], axis=0), axis=1)
    steps_new = steps_old * scales_s
    print(f"rescale p10/p50/p90: {np.percentile(scales_s,10):.2f}/{np.percentile(scales_s,50):.2f}/{np.percentile(scales_s,90):.2f}")
    print(f"total path {steps_old.sum():.0f} -> {steps_new.sum():.0f} m (route {rs[-1]:.0f} m)")
    arc = np.concatenate([[0], np.cumsum(steps_new)]) * (rs[-1] / steps_new.sum())

    P = np.stack([np.interp(arc, rs, Rpts[:, 0]), np.interp(arc, rs, Rpts[:, 1])], 1)
    Ps = gaussian_filter1d(P, 5, axis=0, mode='nearest')
    tang = np.gradient(Ps, axis=0)
    new_bear = np.arctan2(tang[:, 1], tang[:, 0])
    fwd = c2w[:, :3, 2]
    old_bear = np.arctan2(fwd[:, 1], fwd[:, 0])
    dpsi = gaussian_filter1d(np.unwrap(new_bear) - np.unwrap(old_bear), 8)
    for i in range(N):
        cz, sz = np.cos(dpsi[i]), np.sin(dpsi[i])
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        c2w[i, :3, :3] = Rz @ c2w[i, :3, :3]
        c2w[i, 0, 3], c2w[i, 1, 3] = P[i]
    np.savez(out_npz, c2w=c2w, intrinsic=d['intrinsic'], m_per_px=m_per_px,
             m_per_recon_unit=scale, names=d['names'], step_scales=scales_s)
    print("wrote", out_npz)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
