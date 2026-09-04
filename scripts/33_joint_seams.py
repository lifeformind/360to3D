#!/usr/bin/env python3
"""Joint refinement of the per-section similarity placements: GPS terms for
every section + seam terms forcing the shared (overlap) frames of consecutive
sections to coincide. 4 params/section (log s, theta, tx, ty); robust loss.
Rewrites colmap_db/gpx/section_deltas.json (backup: section_deltas.indiv.json).
"""
import glob, json, os, shutil
import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import gaussian_filter1d

D = json.load(open('colmap_db/gpx/section_deltas.json'))
if not os.path.exists('colmap_db/gpx/section_deltas.indiv.json'):
    shutil.copy('colmap_db/gpx/section_deltas.json', 'colmap_db/gpx/section_deltas.indiv.json')
dt = D['dt']
g = np.load('raw/gpx_004.npz'); gt = g['t']
tt = np.arange(0, gt[-1] + 1e-6, 0.1)
GX = gaussian_filter1d(np.interp(tt, gt, g['x']), 15); GY = gaussian_filter1d(np.interp(tt, gt, g['y']), 15)
gps_at = lambda t: np.stack([np.interp(t, tt, GX), np.interp(t, tt, GY)], 1)
# GPS validity: only times within 2 s of a real fix (no fixes while parked)
has_fix = lambda t: np.abs(t[:, None] - gt[None, :]).min(1) < 2.0

SKIP = {'s10'}
secs = []
for k in range(1, 19):
    sec = f's{k:02d}'
    if sec in SKIP: continue
    d = D['sections'][sec]
    files = sorted(glob.glob(f'colmap_db/{sec}/lingbot_out/{sec}_fwd/frame_*.npz'))
    R_l, C_l = [], []
    for f in files:
        E = np.load(f)['extrinsic']; R_l.append(E[:, :3].T); C_l.append(-E[:, :3].T @ E[:, 3])
    R_l = np.array(R_l); C_l = np.array(C_l)
    mu = C_l.mean(0); _, _, Vt = np.linalg.svd(C_l - mu, full_matrices=False)
    b1, b2, n = Vt[0], Vt[1], Vt[2]
    if n @ (-R_l[:, :, 1].mean(0)) < 0: n, b2 = -n, -b2
    if np.linalg.det(np.stack([b1, b2, n], 1)) < 0: b1 = -b1
    P2 = np.stack([(C_l - mu) @ b1, (C_l - mu) @ b2], 1)
    P_old = np.load(f'colmap_db/{sec}/poses_aligned.npz')['c2w'][:, :2, 3]
    fg = d['frames'][0] + np.arange(len(files))
    t = (fg - 1) / 10.0 + dt
    # initial params from the individual fit: P_old -> ENU is (delta_scale, delta_rot, delta_t); we parametrise on P_old directly
    secs.append(dict(sec=sec, P=P_old, fg=fg, G=gps_at(t), ok=has_fix(t),
                     x0=[np.log(d['delta_scale']), np.radians(d['delta_rot_deg']), *d['delta_t']]))
idx = {s['sec']: i for i, s in enumerate(secs)}
def apply(x, i, P):
    ls, th, tx, ty = x[4*i:4*i+4]; c, s = np.cos(th), np.sin(th)
    return np.exp(ls) * (P @ np.array([[c, s], [-s, c]])) + [tx, ty]
SIG_GPS, SIG_SEAM, SIG_SEAM_LOOSE = 4.0, 0.7, 6.0
LOOSE = {'s08'}   # internally distorted (tight loop, 13 m GPS rms): don't let its seams drag neighbours
pairs = []
for a, b in zip(secs[:-1], secs[1:]):
    common, ia, ib = np.intersect1d(a['fg'], b['fg'], return_indices=True)
    if len(common): pairs.append((idx[a['sec']], idx[b['sec']], ia, ib))
def resid(x):
    r = []
    for i, s in enumerate(secs):
        m = s['ok']
        r.append(((apply(x, i, s['P'][m]) - s['G'][m]) / SIG_GPS).ravel())
    for i, j, ia, ib in pairs:
        sig = SIG_SEAM_LOOSE if (secs[i]['sec'] in LOOSE or secs[j]['sec'] in LOOSE) else SIG_SEAM
        r.append(((apply(x, i, secs[i]['P'][ia]) - apply(x, j, secs[j]['P'][ib])) / sig).ravel())
    return np.concatenate(r)
x0 = np.concatenate([s['x0'] for s in secs])
r0 = resid(x0)
sol = least_squares(resid, x0, loss='soft_l1', f_scale=1.0, max_nfev=2000)
x = sol.x
print(f'[joint] cost {0.5*(r0**2).sum():.0f} -> {sol.cost:.0f}, {len(secs)} sections, {len(pairs)} seams')
print(f'{"sec":4s} {"rmsGPS_ind":>10s} {"rmsGPS_joint":>12s} {"dscale%":>8s} {"drot":>6s} {"dshift_m":>8s}   seam_xy(prev->this) ind -> joint')
for i, s in enumerate(secs):
    m = s['ok']
    Pj = apply(x, i, s['P']); Pi = apply(x0, i, s['P'])
    ri = np.sqrt(((Pi[m] - s['G'][m])**2).sum(1).mean()); rj = np.sqrt(((Pj[m] - s['G'][m])**2).sum(1).mean())
    ds = (np.exp(x[4*i]) / np.exp(x0[4*i]) - 1) * 100; dr = np.degrees(x[4*i+1] - x0[4*i+1]); sh = np.linalg.norm(Pj.mean(0) - Pi.mean(0))
    seam = ''
    for a, b, ia, ib in pairs:
        if b == i:
            si = np.linalg.norm(apply(x0, a, secs[a]['P'][ia]) - apply(x0, b, secs[b]['P'][ib]), axis=1).mean()
            sj = np.linalg.norm(apply(x, a, secs[a]['P'][ia]) - apply(x, b, secs[b]['P'][ib]), axis=1).mean()
            seam = f'{si:5.2f} -> {sj:5.2f}'
    print(f"{s['sec']:4s} {ri:10.2f} {rj:12.2f} {ds:8.1f} {dr:6.1f} {sh:8.1f}   {seam}")
    d = D['sections'][s['sec']]
    d.update(delta_scale=float(np.exp(x[4*i])), delta_rot_deg=float(np.degrees(x[4*i+1])), delta_t=[float(x[4*i+2]), float(x[4*i+3])],
             rms_gps_new=float(rj), joint=True)
json.dump(D, open('colmap_db/gpx/section_deltas.json', 'w'), indent=1)
print('[done] section_deltas.json updated (joint); re-run 32_unity_placement.py')
