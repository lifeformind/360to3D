#!/usr/bin/env python3
"""GPX anchoring for the 18-section circuit.

A. Register the GPX track (ENU metres, origin = first fix) to the traced map
   route (arc-fraction Procrustes) -> true map scale, overlay image.
B. Re-fit every section's LingBot ground-plane trajectory to GPS positions by
   TIME correspondence (frame n at (n-1)/10 s + dt), search the video/GPS
   time offset dt jointly, and compute per-section delta similarity
   (old map-metre placement -> ENU metres) for the Unity assembly.
Outputs: colmap_db/gpx/gpx_map_fit.json, section_deltas.json, overlay PNGs.
"""
import os, glob, json, sys
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d

os.makedirs('colmap_db/gpx', exist_ok=True)
g = np.load('raw/gpx_004.npz')
gt, gx, gy = g['t'], g['x'], g['y']
# light smoothing of the 1 Hz fixes (canopy jitter), then a 10 Hz resampler
tt = np.arange(0, gt[-1] + 1e-6, 0.1)
GX = gaussian_filter1d(np.interp(tt, gt, gx), 15)   # sigma 1.5 s
GY = gaussian_filter1d(np.interp(tt, gt, gy), 15)
def gps_at(t):
    return np.stack([np.interp(t, tt, GX), np.interp(t, tt, GY)], 1)

def procrustes(A, B):
    """similarity (s, R, t) minimising |s R a + t - b|, no reflection; returns s,R,t,rms"""
    ma, mb = A.mean(0), B.mean(0)
    Ac, Bc = A - ma, B - mb
    U, S, Vh = np.linalg.svd(Ac.T @ Bc)
    D = np.eye(2); D[1, 1] = np.sign(np.linalg.det(Vh.T @ U.T))
    R = Vh.T @ D @ U.T
    s = (S * np.diag(D)).sum() / max((Ac ** 2).sum(), 1e-12)
    t = mb - s * R @ ma
    rms = float(np.sqrt((((s * (R @ A.T)).T + t - B) ** 2).sum(1).mean()))
    return s, R, t, rms

# ---------------- A. GPX <-> traced route ----------------
d = json.load(open('colmap_db/amanorthv/route_polyline.json'))
Rpx = np.array(d['points_px'])
Rm = Rpx * np.array([1.0, -1.0])             # y-flipped pixel frame (as 19_align), unscaled
rs = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(Rm, axis=0), axis=1))]); rs /= rs[-1]
gs_ = np.concatenate([[0], np.cumsum(np.hypot(np.diff(GX), np.diff(GY)))]); gs_ /= gs_[-1]
u = np.linspace(0, 1, 600)
Rs = np.stack([np.interp(u, rs, Rm[:, 0]), np.interp(u, rs, Rm[:, 1])], 1)
Gs = np.stack([np.interp(u, gs_, GX), np.interp(u, gs_, GY)], 1)
best = None
for rev in (False, True):
    Rtry = Rs[::-1] if rev else Rs
    s, R, t, rms = procrustes(Rtry, Gs)      # pixel-frame -> ENU
    print(f'[A] route {"reversed" if rev else "forward"}: m/px={s:.3f} rot={np.degrees(np.arctan2(R[1,0],R[0,0])):.1f}deg rms={rms:.1f} m')
    if best is None or rms < best[3]:
        best = (s, R, t, rms, rev)
s_px, R_px, t_px, rms_px, rev_px = best
print(f'[A] traced route length = {rs[-1]:.0f} (norm); GPX path 3005 m; fitted map scale {s_px:.3f} m/px (assumed 1.5)')
json.dump({'m_per_px': s_px, 'rot_deg': float(np.degrees(np.arctan2(R_px[1,0],R_px[0,0]))), 't': t_px.tolist(),
           'rms_m': rms_px, 'route_reversed': rev_px, 'note': 'maps y-flipped pixel coords -> ENU metres'},
          open('colmap_db/gpx/gpx_map_fit.json', 'w'), indent=1)
# old map frame (1.5 m/px, y flipped) -> ENU similarity:  enu = R_px @ (p_old/1.5) * s_px + t_px
def old_to_enu(P):
    return (s_px * (R_px @ (P / 1.5).T)).T + t_px
# overlay on the map image
img = cv2.imread('raw/3A_Ama North Map.png')
def enu_to_px(E):
    P = (np.linalg.inv(R_px) @ ((E - t_px) / s_px).T).T
    return P * np.array([1.0, -1.0])
G_px = enu_to_px(np.stack([GX, GY], 1))
for i in range(0, len(G_px) - 1, 2):
    cv2.line(img, tuple(G_px[i].astype(int)), tuple(G_px[i + 1].astype(int)), (0, 0, 255), 2)
cv2.circle(img, tuple(G_px[0].astype(int)), 8, (0, 255, 0), -1)
cv2.circle(img, tuple(G_px[-1].astype(int)), 8, (255, 0, 255), -1)
cv2.imwrite('colmap_db/gpx/overlay_gpx_on_map.png', img)

# ---------------- B. per-section time-based refit ----------------
N_SEC, OV, TF = 18, 0.15, 6474
width = 1.0 / (N_SEC - (N_SEC - 1) * OV); step = width * (1 - OV)
secs = []
for k in range(1, N_SEC + 1):
    sec = f's{k:02d}'
    fa = (k - 1) * step; fb = min(fa + width, 1.0)
    A = max(1, int(fa * TF)); B = min(TF, int(fb * TF))
    files = sorted(glob.glob(f'colmap_db/{sec}/lingbot_out/{sec}_fwd/frame_*.npz'))
    N = len(files)
    if N == 0 or not os.path.exists(f'colmap_db/{sec}/poses_aligned.npz'):
        print(f'[B] {sec}: missing artifacts — skipped'); continue
    R_l, C_l = [], []
    for f in files:
        E = np.load(f)['extrinsic']
        R_l.append(E[:, :3].T); C_l.append(-E[:, :3].T @ E[:, 3])
    R_l = np.array(R_l); C_l = np.array(C_l)
    mu = C_l.mean(0)
    _, S, Vt = np.linalg.svd(C_l - mu, full_matrices=False)
    b1, b2, n = Vt[0], Vt[1], Vt[2]
    if n @ (-R_l[:, :, 1].mean(0)) < 0:
        n, b2 = -n, -b2
    if np.linalg.det(np.stack([b1, b2, n], 1)) < 0:
        b1 = -b1
    P2 = np.stack([(C_l - mu) @ b1, (C_l - mu) @ b2], 1)
    old = np.load(f'colmap_db/{sec}/poses_aligned.npz')
    P_old = old['c2w'][:, :2, 3]
    # sanity: P_old must be a similarity image of P2
    _, _, _, chk = procrustes(P2, P_old)
    frames_global = A + np.arange(N)          # local i -> global frame n
    secs.append(dict(sec=sec, A=A, B=B, N=N, P2=P2, P_old=P_old, fg=frames_global, chk=chk,
                     scl_old=float(old['scale']), kappa=float(old['kappa'])))
print(f'[B] loaded {len(secs)} sections; max |P_old vs similarity(P2)| rms = {max(s["chk"] for s in secs):.3f} m (should be ~0)')

def fit_all(dt):
    out = []
    for s in secs:
        G = gps_at((s['fg'] - 1) / 10.0 + dt)
        out.append(procrustes(s['P2'], G))
    return out
dts = np.arange(-6, 6.01, 0.5)
tot = []
for dt in dts:
    r = fit_all(dt)
    tot.append(np.mean([x[3] for x in r]))
dt_best = float(dts[int(np.argmin(tot))])
print('[B] time-offset search (dt -> mean rms m): ' + ' '.join(f'{a:+.1f}:{b:.2f}' for a, b in zip(dts, tot)))
print(f'[B] best video->GPS offset dt = {dt_best:+.1f} s')
fits = fit_all(dt_best)

# deltas + reporting + overlay
img2 = cv2.imread('raw/3A_Ama North Map.png')
for i in range(0, len(G_px) - 1, 2):
    cv2.line(img2, tuple(G_px[i].astype(int)), tuple(G_px[i + 1].astype(int)), (0, 0, 255), 1)
deltas = {}
print(f'{"sec":4s} {"N":>4s} {"rmsGPS":>7s} {"rmsOLD":>7s} {"scale_new":>9s} {"scale_old":>9s} {"ratio":>6s} {"drot":>6s} {"shift":>6s}')
for s, (sn, Rn, tn, rmsn) in zip(secs, fits):
    G = gps_at((s['fg'] - 1) / 10.0 + dt_best)
    P_new = (sn * (Rn @ s['P2'].T)).T + tn
    P_old_enu = old_to_enu(s['P_old'])
    rms_old = float(np.sqrt(((P_old_enu - G) ** 2).sum(1).mean()))
    # delta: old map-metre frame -> ENU  (exact, both are similarity images of P2)
    sd, Rd, td, rmsd = procrustes(s['P_old'], P_new)
    assert rmsd < 0.05, (s['sec'], rmsd)
    drot = float(np.degrees(np.arctan2(Rd[1, 0], Rd[0, 0])))
    shift = float(np.linalg.norm(P_new.mean(0) - P_old_enu.mean(0)))
    # new trajectory scale in m per LingBot unit
    deltas[s['sec']] = dict(frames=[int(s['A']), int(s['B'])], N=int(s['N']), dt=dt_best,
                            delta_scale=float(sd), delta_rot_deg=drot, delta_t=[float(td[0]), float(td[1])],
                            rms_gps_new=rmsn, rms_gps_old_mapfit=rms_old,
                            scale_new_m_per_unit=float(sn), scale_old_m_per_unit=s['scl_old'], kappa=s['kappa'],
                            enu_centroid=P_new.mean(0).tolist())
    print(f"{s['sec']:4s} {s['N']:4d} {rmsn:7.2f} {rms_old:7.2f} {sn:9.2f} {s['scl_old']:9.2f} {sn/s['scl_old']:6.3f} {drot:6.1f} {shift:6.1f}")
    po = enu_to_px(P_old_enu).astype(int); pn = enu_to_px(P_new).astype(int)
    for j in range(0, len(pn) - 1, 3):
        cv2.line(img2, tuple(po[j]), tuple(po[j + 1]), (255, 120, 0), 2)   # old = blue-ish
        cv2.line(img2, tuple(pn[j]), tuple(pn[j + 1]), (0, 220, 0), 2)     # new = green
    cv2.putText(img2, s['sec'], tuple(pn[len(pn)//2] + np.array([6, -6])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
    cv2.putText(img2, s['sec'], tuple(pn[len(pn)//2] + np.array([6, -6])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
cv2.imwrite('colmap_db/gpx/overlay_sections_old_vs_gpx.png', img2)
json.dump(dict(map_fit=json.load(open('colmap_db/gpx/gpx_map_fit.json')), dt=dt_best, sections=deltas),
          open('colmap_db/gpx/section_deltas.json', 'w'), indent=1)
print('[done] colmap_db/gpx/{gpx_map_fit.json,section_deltas.json,overlay_*.png}')
