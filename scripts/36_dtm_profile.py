#!/usr/bin/env python3
"""Extract a terrain profile along the GPX track from the ArcGIS-Earth DTM screenshot (raw/DTM.tif).
1. register GPX (ENU) -> image px by fitting to the blue track overlay (similarity ICP);
2. sample DTM grey along the track; 3. calibrate grey -> metres by robust regression on GPS ele.
Writes colmap_db/gpx/dtm_profile.npz (t, grey, ele_dtm_m), overlay + profile PNGs.
"""
import numpy as np, cv2
from scipy.spatial import cKDTree
from scipy.ndimage import gaussian_filter1d, median_filter
im = cv2.imread('raw/DTM.tif', cv2.IMREAD_UNCHANGED)[..., :3]   # BGR
b, g_, r = im[..., 0].astype(int), im[..., 1].astype(int), im[..., 2].astype(int)
blue = (b > 150) & (b - r > 60) & (b - g_ > 20)
blue[:140] = False; blue[720:] = False
ys, xs = np.nonzero(blue); B = np.stack([xs, ys], 1).astype(float)
print(f'[reg] blue track pixels: {len(B)}')
g = np.load('raw/gpx_004.npz'); E = np.stack([g['x'], g['y']], 1); t = g['t']; ele = g['ele']
# init: scale bar 400 m = 218 px -> 1.835 m/px ; y flipped; north arrow ~ -15 deg (fit refines)
s0 = 1 / 1.835
def sim(p, s, th, tx, ty):
    c, sn = np.cos(th), np.sin(th); R = np.array([[c, -sn], [sn, c]])
    q = (s * (R @ (p * [1, -1]).T)).T; return q + [tx, ty]
best = None
tree = cKDTree(B)
for th0 in np.radians(np.arange(-40, 41, 5)):
    q = sim(E, s0, th0, 0, 0); tx, ty = B.mean(0) - q.mean(0)
    x = np.array([s0, th0, tx, ty])
    for it in range(30):   # ICP: nearest blue pixel, similarity Procrustes
        q = sim(E, *x); d, j = tree.query(q)
        keep = d < np.percentile(d, 80) + 3
        A_ = E[keep] * [1, -1]; T_ = B[j][keep]
        ma, mb = A_.mean(0), T_.mean(0)
        U, S, Vh = np.linalg.svd((A_ - ma).T @ (T_ - mb))
        D = np.eye(2); D[1, 1] = np.sign(np.linalg.det(Vh.T @ U.T)); R = Vh.T @ D @ U.T
        s = (S * np.diag(D)).sum() / ((A_ - ma) ** 2).sum()
        th = np.arctan2(R[1, 0], R[0, 0]); tt = mb - s * R @ ma
        x = np.array([s, th, tt[0], tt[1]])
    q = sim(E, *x); d, _ = tree.query(q); rms = np.sqrt((d ** 2).mean())
    if best is None or rms < best[0]: best = (rms, x)
rms, x = best
print(f'[reg] similarity fit: {1/x[0]:.3f} m/px, rotation {np.degrees(x[1]):.1f} deg, rms to blue line {rms:.2f} px (~{rms/x[0]:.1f} m)')
q = sim(E, *x)
# the ArcGIS Earth view is a tilted perspective: refine with a homography ICP
Hm = None
for it in range(40):
    d, j = tree.query(q); keep = d < np.percentile(d, 85) + 2
    Hm, _ = cv2.findHomography(E[keep].astype(np.float32), B[j][keep].astype(np.float32), 0)
    q = cv2.perspectiveTransform(E.reshape(-1, 1, 2).astype(np.float32), Hm).reshape(-1, 2).astype(float)
d, _ = tree.query(q); rms_h = np.sqrt((d ** 2).mean())
print(f'[reg] homography refine: rms to blue line {rms_h:.2f} px (~{rms_h/x[0]:.1f} m)')
grey = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(float)
# sample grey slightly off the blue line (the overlay hides the pixels under it): median of a ring 4-7 px
yy, xx = np.mgrid[-7:8, -7:8]; ring = (np.hypot(yy, xx) >= 4) & (np.hypot(yy, xx) <= 7)
vals = []
for (px, py) in q:
    px, py = int(round(px)), int(round(py))
    patch = grey[py-7:py+8, px-7:px+8]; m = ring & ~blue[py-7:py+8, px-7:px+8]
    vals.append(np.median(patch[m]) if m.sum() > 10 else np.nan)
vals = np.array(vals)
ok = np.isfinite(vals)
vals[~ok] = np.interp(t[~ok], t[ok], vals[ok])
gs = median_filter(vals, 9)
# robust linear calibration grey -> metres using GPS ele (noisy but unbiased)
A = np.c_[gs, np.ones_like(gs)]
w = np.ones_like(gs)
for _ in range(5):
    coef = np.linalg.lstsq(A * w[:, None], ele * w, rcond=None)[0]
    res = ele - A @ coef; mad = np.median(np.abs(res)) + 1e-6
    w = 1 / np.maximum(1, np.abs(res) / (3 * mad))
ele_dtm = A @ coef
print(f'[cal] ele = {coef[0]:.3f} * grey + {coef[1]:.1f}  (GPS-ele residual MAD {np.median(np.abs(ele-ele_dtm)):.1f} m); '
      f'DTM profile range {ele_dtm.min():.1f}..{ele_dtm.max():.1f} m; corr(grey, gps ele) = {np.corrcoef(gs, ele)[0,1]:.2f}')
np.savez('colmap_db/gpx/dtm_profile.npz', t=t, grey=gs, ele_dtm=ele_dtm, ele_gps=ele, px=q, reg=x)
ov = im.copy()
for i in range(len(q) - 1): cv2.line(ov, tuple(q[i].astype(int)), tuple(q[i+1].astype(int)), (0, 0, 255), 1)
cv2.imwrite('colmap_db/gpx/dtm_registration.png', ov)
# profile plot
W, H = 1200, 400; pl = np.full((H, W, 3), 255, np.uint8)
lo, hi = min(ele.min(), ele_dtm.min()) - 2, max(ele.max(), ele_dtm.max()) + 2
X = (40 + t / t[-1] * (W - 60)).astype(int); Yg = (H - 30 - (ele - lo) / (hi - lo) * (H - 60)).astype(int); Yd = (H - 30 - (ele_dtm - lo) / (hi - lo) * (H - 60)).astype(int)
for i in range(len(t) - 1):
    cv2.line(pl, (X[i], Yg[i]), (X[i+1], Yg[i+1]), (200, 200, 200), 1)
    cv2.line(pl, (X[i], Yd[i]), (X[i+1], Yd[i+1]), (0, 0, 255), 2)
for v in range(int(lo), int(hi) + 1, 5):
    y = int(H - 30 - (v - lo) / (hi - lo) * (H - 60)); cv2.line(pl, (40, y), (W - 20, y), (235, 235, 235), 1); cv2.putText(pl, f'{v} m', (2, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
for s_ in range(0, int(t[-1]) + 1, 60):
    xx_ = int(40 + s_ / t[-1] * (W - 60)); cv2.putText(pl, f'{s_}s', (xx_ - 10, H - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
cv2.putText(pl, 'terrain along track: red = DTM screenshot (calibrated), grey = raw GPS altitude', (50, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
cv2.imwrite('colmap_db/gpx/dtm_profile.png', pl)
print('[done] colmap_db/gpx/dtm_profile.{npz,png}, dtm_registration.png')
