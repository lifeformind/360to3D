#!/usr/bin/env python3
"""Bake the GPX/terrain-anchored section transforms INTO the splat PLYs, in Unity's frame.

Why: aras-p UnityGaussianSplatting sorts/blends splats per GaussianSplatRenderer object, so 17 overlapping
objects would composite wrongly at every seam, and each object would need a ~1000x negative-z scale.
Instead: one PLY per section in Unity coordinates (x=East, y=Up, z=North, metres, road ~y=0, identity
transform) plus one merged PLY of the whole circuit.  Overlap zones between consecutive sections are cut
at the mid-overlap frame so each piece of road is represented once.

Reads : colmap_db/gpx/section_transforms.json (M_ply_to_enu, status), colmap_db/gpx/section_cams_enu.npz
Writes: unity_bundle/sections/sXX_unity.ply, unity_bundle/amakeng_merged_unity.ply,
        unity_bundle/road_centerline_unity.csv, unity_bundle/bake_report.json
"""
import json, os, sys, time
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

TAG = os.environ.get('TAG')            # e.g. TAG=v3 -> use splat_output/sXX_v3 (latest PLY), output unity_bundle_v3/
OUT = f'unity_bundle_{TAG}' if TAG else 'unity_bundle'; os.makedirs(f'{OUT}/sections', exist_ok=True)
import glob
def ply_path(sec):
    if not TAG: return T[sec]['ply']
    c = glob.glob(f'splat_output/{sec}_{TAG}/ply/point_cloud_*.ply')
    return max(c, key=lambda q: int(q.split('_')[-1][:-4])) if c else None
SWAP = np.array([[1., 0, 0], [0, 0, 1], [0, 1, 0]])          # ENU (x=E,y=N,z=Up) -> Unity (x=E,y=Up,z=N); det -1, self-inverse
OPACITY_MIN, MAX_CAM_DIST, MAX_SCALE = 0.02, 150.0, 15.0     # prune: invisible / far floaters / giant sky blobs
N_FLOATS = 59                                                # xyz f_dc*3 f_rest*45 opacity scale*3 rot*4(wxyz)

# ---- spherical harmonics (3DGS real-SH convention, degree <= 3), used to re-express view dependence ----
C1 = 0.4886025119029199
C2 = [1.0925484305920792, -1.0925484305920792, 0.31539156525252005, -1.0925484305920792, 0.5462742152960396]
C3 = [-0.5900435899266435, 2.890611442640554, -0.4570457994644658, 0.3731763325901154, -0.4570457994644658, 1.445305721320277, -0.5900435899266435]
def sh_basis(d):   # d: (N,3) unit dirs -> (N,15) basis values for f_rest coefficients 0..14
    x, y, z = d[:, 0], d[:, 1], d[:, 2]; xx, yy, zz, xy, yz, xz = x*x, y*y, z*z, x*y, y*z, x*z
    return np.stack([-C1*y, C1*z, -C1*x,
                     C2[0]*xy, C2[1]*yz, C2[2]*(2*zz-xx-yy), C2[3]*xz, C2[4]*(xx-yy),
                     C3[0]*y*(3*xx-yy), C3[1]*xy*z, C3[2]*y*(4*zz-xx-yy), C3[3]*z*(2*zz-3*xx-3*yy),
                     C3[4]*x*(4*zz-xx-yy), C3[5]*z*(xx-yy), C3[6]*x*(xx-3*yy)], 1)
def sh_transform(L):
    """A (15x15) with  coeffs_new = A @ coeffs_old  such that colour_new(d) == colour_old(L d) for all unit d."""
    rng = np.random.default_rng(0); d = rng.normal(size=(4000, 3)); d /= np.linalg.norm(d, axis=1, keepdims=True)
    X, Y = sh_basis(d), sh_basis(d @ L.T)
    A, *_ = np.linalg.lstsq(X, Y, rcond=None)             # Y = X A  ->  B_j(Ld) = sum_k A_kj B_k(d)
    assert np.abs(X @ A - Y).max() < 1e-9, 'SH space not closed under L (bug)'
    return A            # c_new = A @ c_old

def read_ply(path):
    f = open(path, 'rb'); hdr = b''
    while not hdr.endswith(b'end_header\n'): hdr += f.readline()
    n = int([l for l in hdr.decode().split('\n') if l.startswith('element vertex')][0].split()[-1])
    return np.fromfile(path, dtype=np.float32, offset=len(hdr)).reshape(n, N_FLOATS)
def write_ply(path, d):
    names = ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2'] + [f'f_rest_{i}' for i in range(45)] + ['opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3']
    hdr = 'ply\nformat binary_little_endian 1.0\nelement vertex %d\n' % len(d) + ''.join(f'property float {n}\n' for n in names) + 'end_header\n'
    with open(path, 'wb') as f: f.write(hdr.encode()); d.astype('<f4').tofile(f)

T = json.load(open('colmap_db/gpx/section_transforms.json'))['sections']
C = np.load('colmap_db/gpx/section_cams_enu.npz')
secs = [f's{k:02d}' for k in range(1, 19)]
active = [s for s in secs if T[s]['status'] != 'drop' and ply_path(s)]
print('sections in bundle:', active, '' if not TAG else f'(TAG={TAG}; missing: {[s for s in secs if T[s]["status"] != "drop" and not ply_path(s)]})')
frames = {s: T[s]['frames'] for s in secs}
def crop_bounds(s):
    k = secs.index(s); lo, hi = -np.inf, np.inf
    if k > 0 and secs[k-1] in active and frames[secs[k-1]][1] >= frames[s][0]: lo = (frames[s][0] + frames[secs[k-1]][1]) / 2
    if k < 17 and secs[k+1] in active and frames[secs[k+1]][0] <= frames[s][1]: hi = (frames[s][1] + frames[secs[k+1]][0]) / 2
    return lo, hi

report, merged, road = {}, [], []
for s in active:
    t0 = time.time()
    M = np.array(T[s]['M_ply_to_enu']); sc = float(np.cbrt(np.linalg.det(M[:3, :3]))); R = M[:3, :3] / sc
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-6) and sc > 0
    d = read_ply(ply_path(s)); n0 = len(d)
    # --- geometry: PLY frame -> ENU -> Unity ---
    P_enu = d[:, :3].astype(np.float64) @ M[:3, :3].T + M[:3, 3]
    cams, fg = C[f'{s}_cam'], C[f'{s}_fg']
    dist, nn = cKDTree(cams).query(P_enu)
    opac = 1 / (1 + np.exp(-d[:, 51].astype(np.float64)))
    smax = np.exp(d[:, 52:55].max(1).astype(np.float64)) * sc
    lo, hi = crop_bounds(s)
    keep = (opac >= OPACITY_MIN) & (dist <= MAX_CAM_DIST) & (smax <= MAX_SCALE) & (fg[nn] >= lo) & (fg[nn] <= hi)
    stats = dict(n_in=n0, pruned_opacity=int((opac < OPACITY_MIN).sum()), pruned_far=int((dist > MAX_CAM_DIST).sum()),
                 pruned_giant=int((smax > MAX_SCALE).sum()), cropped_overlap=int(((fg[nn] < lo) | (fg[nn] > hi)).sum()),
                 crop_frames=[None if np.isinf(lo) else float(lo), None if np.isinf(hi) else float(hi)])
    d, P_enu = d[keep], P_enu[keep]
    q_old = d[:, 55:59].astype(np.float64)                   # (w,x,y,z)
    Rg = Rotation.from_quat(q_old[:, [1, 2, 3, 0]]).as_matrix()          # scipy wants (x,y,z,w)
    R_u = SWAP @ (R @ Rg) @ SWAP                                         # proper rotation in the mirrored (Unity) frame
    q_u = Rotation.from_matrix(R_u).as_quat()[:, [3, 0, 1, 2]]           # back to (w,x,y,z)
    log_scale_u = (d[:, 52:55].astype(np.float64) + np.log(sc))[:, [0, 2, 1]]  # SWAP permutes the y/z axes of the local scale
    A = sh_transform(R.T @ SWAP)                                          # Unity view dir -> PLY-frame view dir
    F = d[:, 6:51].astype(np.float64).reshape(-1, 3, 15) @ A.T
    # --- self-check on a sample: covariance and view-dependent colour must be identical ---
    i = np.random.default_rng(1).choice(len(d), min(500, len(d)), replace=False)
    S_old = np.exp(d[i, 52:55].astype(np.float64)); Mtot = SWAP @ M[:3, :3]
    cov_ref = Mtot @ (Rg[i] @ (S_old[:, :, None]**2 * np.eye(3)) @ np.transpose(Rg[i], (0, 2, 1))) @ Mtot.T
    Su = np.exp(log_scale_u[i]); cov_new = R_u[i] @ (Su[:, :, None]**2 * np.eye(3)) @ np.transpose(R_u[i], (0, 2, 1))
    assert np.abs(cov_ref - cov_new).max() < 1e-6 * max(1.0, np.abs(cov_ref).max()), f'{s}: covariance mismatch'
    du = np.random.default_rng(2).normal(size=(len(i), 3)); du /= np.linalg.norm(du, axis=1, keepdims=True)
    col_old = np.einsum('nck,nk->nc', d[i, 6:51].astype(np.float64).reshape(-1, 3, 15), sh_basis(du @ (R.T @ SWAP).T))
    col_new = np.einsum('nck,nk->nc', F[i], sh_basis(du))
    assert np.abs(col_old - col_new).max() < 1e-6, f'{s}: SH colour mismatch'
    # --- assemble ---
    out = d.copy(); out[:, :3] = (P_enu @ SWAP.T); out[:, 6:51] = F.reshape(-1, 45); out[:, 52:55] = log_scale_u; out[:, 55:59] = q_u
    write_ply(f'{OUT}/sections/{s}_unity.ply', out); merged.append(out)
    stats.update(n_out=int(len(out)), sec=s, status=T[s]['status'], seconds=round(time.time() - t0, 1)); report[s] = stats
    print(f"{s} {T[s]['status']:5s} in {n0:8d}  opac-{stats['pruned_opacity']:6d} far-{stats['pruned_far']:6d} giant-{stats['pruned_giant']:5d} overlap-{stats['cropped_overlap']:7d}  -> {len(out):8d}  ({stats['seconds']}s)  checks OK")
    # road centreline: camera path, road height = cam z - camera height, only inside the crop window
    m = (fg >= lo) & (fg <= hi)
    road.append(np.c_[fg[m], cams[m][:, 0], cams[m][:, 2] - float(C[f'{s}_cam_h']), cams[m][:, 1], np.full(m.sum(), int(s[1:]))])

merged = np.concatenate(merged); write_ply(f'{OUT}/amakeng_merged_unity.ply', merged)
road = np.concatenate(road); road = road[np.argsort(road[:, 0], kind='stable')]
# average frames seen by two sections, then light smoothing
uf, inv = np.unique(road[:, 0], return_inverse=True)
xyz = np.stack([np.bincount(inv, road[:, c]) / np.bincount(inv) for c in (1, 2, 3)], 1)
sec_of = np.zeros(len(uf), int); sec_of[inv] = road[:, 4]
k = 9; pad = np.pad(xyz, ((k//2, k//2), (0, 0)), mode='edge'); xyz_s = np.stack([np.convolve(pad[:, c], np.ones(k)/k, 'valid') for c in range(3)], 1)
with open(f'{OUT}/road_centerline_unity.csv', 'w') as f:
    f.write('frame,t_video_s,x,y,z,section\n')
    for i in range(len(uf)): f.write(f'{int(uf[i])},{(uf[i]-1)/10:.1f},{xyz_s[i,0]:.3f},{xyz_s[i,1]:.3f},{xyz_s[i,2]:.3f},s{sec_of[i]:02d}\n')
json.dump(dict(frame='Unity: x=East, y=Up, z=North, metres; origin = first GPX fix; road ~ y=0 at track start',
               prune=dict(opacity_min=OPACITY_MIN, max_cam_dist_m=MAX_CAM_DIST, max_scale_m=MAX_SCALE), sections=report,
               merged=dict(n=int(len(merged)), bytes=int(os.path.getsize(f'{OUT}/amakeng_merged_unity.ply')))), open(f'{OUT}/bake_report.json', 'w'), indent=1)
print(f'merged: {len(merged)} splats, {os.path.getsize(f"{OUT}/amakeng_merged_unity.ply")/1e9:.2f} GB; centreline {len(uf)} frames -> {OUT}/')
