#!/usr/bin/env python3
"""Which depth multiplier is consistent with the GPS-metric poses?
For frame pairs (i, i+k): unproject frame j depth*lam, re-project into frame i, compare with
lam*depth_i. The lam minimising median relative error is the parallax-consistent depth scale.
Compare with kappa (ground-plane, assumes cam_h) and recon-scale (translation head).
Usage: 35_depth_scale_check.py <sec> [k=3]
"""
import sys, glob, numpy as np, cv2
sec = sys.argv[1]; k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
z = np.load(f'colmap_db/{sec}/gps/poses_aligned.npz'); c2w = z['c2w']; kap = float(z['kappa']); scl = float(z['scale'])
files = sorted(glob.glob(f'colmap_db/{sec}/lingbot_out/{sec}_fwd/frame_*.npz')); N = len(files)
K = np.load(files[0])['intrinsic']; fx, fy, cx, cy = K[0,0], K[1,1], K[0,2], K[1,2]
ys, xs = np.mgrid[0:518:6, 0:518:6]; ys = ys.ravel(); xs = xs.ravel()
lams = np.exp(np.linspace(np.log(5), np.log(120), 60))
errs = np.zeros(len(lams)); cnt = 0
def load(i):
    d = np.load(files[i]); am = cv2.imread(f'cubefaces_rgba/{sec}/c04_{i+1:05d}_Y000.png', cv2.IMREAD_UNCHANGED)[..., 3]
    am = cv2.resize(am, (518, 518), interpolation=cv2.INTER_NEAREST) > 127
    return d['depth'][..., 0], d['depth_conf'], am
for i in range(0, N - k, max(1, N // 40)):
    di, ci, mi = load(i); dj, cj, mj = load(i + k)
    ok = (cj[ys, xs] > 1.5) & mj[ys, xs] & (dj[ys, xs] > 0)
    u, v, d = xs[ok], ys[ok], dj[ys, xs][ok]
    rays = np.stack([(u - cx) / fx, (v - cy) / fy, np.ones_like(d)], 1)
    T = np.linalg.inv(c2w[i]) @ c2w[i + k]   # cam j -> cam i (metric translation)
    for li, lam in enumerate(lams):
        Xj = rays * (lam * d)[:, None]
        Xi = Xj @ T[:3, :3].T + T[:3, 3]
        zz = Xi[:, 2]; good = zz > 0.5
        pu = (Xi[good, 0] / zz[good] * fx + cx).round().astype(int); pv = (Xi[good, 1] / zz[good] * fy + cy).round().astype(int)
        inb = (pu >= 0) & (pu < 518) & (pv >= 0) & (pv < 518)
        pu, pv, zp = pu[inb], pv[inb], zz[good][inb]
        vis = (ci[pv, pu] > 1.5) & mi[pv, pu] & (di[pv, pu] > 0)
        if vis.sum() < 50: errs[li] += 1.0; continue
        rel = np.abs(zp[vis] - lam * di[pv, pu][vis]) / (lam * di[pv, pu][vis])
        errs[li] += np.median(rel)
    cnt += 1
errs /= max(cnt, 1)
best = lams[np.argmin(errs)]
print(f'[{sec}] pairs={cnt} k={k}  parallax-consistent depth scale = {best:.1f} m/unit  (median rel err {errs.min():.3f})')
print(f'[{sec}] kappa(ground-plane, cam_h=3) = {kap:.1f}   recon-scale(translation head, GPS) = {scl:.1f}   err@kappa={errs[np.argmin(abs(lams-kap))]:.3f} err@scl={errs[np.argmin(abs(lams-scl))]:.3f}')
print('[curve] ' + ' '.join(f'{l:.0f}:{e:.3f}' for l, e in zip(lams[::4], errs[::4])))
