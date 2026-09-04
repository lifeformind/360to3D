#!/usr/bin/env python3
"""GPS-ANCHORED variant of 19_align_section.py: align a section's LingBot trajectory to the
GPX track by TIME correspondence (frame n at (n-1)/10 + dt seconds) instead of the map route
window, and build the COLMAP training scene under colmap_db/<sec>/gps/.

Original docstring: Rigidly align a section's LingBot trajectory to its route window and
build the COLMAP training scene (poses + depth-fused cloud).

Sections are short enough (~150 m) that internal drift is negligible, so a
single similarity transform (arc-fraction correspondence + Procrustes, plus
plane handedness from the camera's gravity direction) replaces the whole
DTW/snap machinery. Depth scale is calibrated per section from the ground
plane using WORLD-masked road pixels only (hull excluded via alpha masks).

Gates printed: spacing p90/p10, camera-forward vs motion angle, residual
RMS to the route window, road-depth sanity.

Usage: 19b_align_gps.py <section> <first_global_frame> <dt_video_to_gps_s> <cam_height_m>
"""
import sys, os, glob, json, struct
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d

def gps_resampler():
    g = np.load('raw/gpx_004.npz'); gt = g['t']
    tt = np.arange(0, gt[-1] + 1e-6, 0.1)
    GX = gaussian_filter1d(np.interp(tt, gt, g['x']), 15)
    GY = gaussian_filter1d(np.interp(tt, gt, g['y']), 15)
    at = lambda t: np.stack([np.interp(t, tt, GX), np.interp(t, tt, GY)], 1)
    has = lambda t: np.abs(t[:, None] - gt[None, :]).min(1) < 2.0
    return at, has

FACE, FOV = 1024, 110.0

def roty(th):
    c, s = np.cos(th), np.sin(th)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

def rot2quat(R):
    K = np.array([
        [R[0,0]-R[1,1]-R[2,2], 0, 0, 0],
        [R[0,1]+R[1,0], R[1,1]-R[0,0]-R[2,2], 0, 0],
        [R[0,2]+R[2,0], R[1,2]+R[2,1], R[2,2]-R[0,0]-R[1,1], 0],
        [R[2,1]-R[1,2], R[0,2]-R[2,0], R[1,0]-R[0,1], R[0,0]+R[1,1]+R[2,2]]]) / 3.0
    w, V = np.linalg.eigh(K)
    q = V[[3, 0, 1, 2], np.argmax(w)]
    return q * np.sign(q[0] + 1e-12)

def main(sec, A, dt, cam_h):
    A, dt, cam_h = int(A), float(dt), float(cam_h)
    npz_dir = f'colmap_db/{sec}/lingbot_out/{sec}_fwd'
    files = sorted(glob.glob(os.path.join(npz_dir, 'frame_*.npz')))
    N = len(files)
    R_l, C_l, K518 = [], [], None
    for f in files:
        z = np.load(f)
        E = z['extrinsic']
        R_l.append(E[:, :3].T); C_l.append(-E[:, :3].T @ E[:, 3])
        if K518 is None:
            K518 = z['intrinsic']
    R_l = np.array(R_l); C_l = np.array(C_l)

    # ground plane basis, handedness from gravity
    mu = C_l.mean(0)
    _, S, Vt = np.linalg.svd(C_l - mu, full_matrices=False)
    b1, b2, n = Vt[0], Vt[1], Vt[2]
    if n @ (-R_l[:, :, 1].mean(0)) < 0:
        n, b2 = -n, -b2
    # SVD may return a left-handed row set; enforce det(+1) or every written
    # "rotation" is a reflection (det -1) and the whole scene is mirrored
    if np.linalg.det(np.stack([b1, b2, n], 1)) < 0:
        b1 = -b1
    P2 = np.stack([(C_l - mu) @ b1, (C_l - mu) @ b2], 1)

    # GPS positions at each frame's time (frame local i=1..N -> global n=A+i-1)
    gps_at, has_fix = gps_resampler()
    tq = (A + np.arange(N) - 1) / 10.0 + dt
    W = gps_at(tq); ok = has_fix(tq)
    path_m = float(np.hypot(*np.diff(W[ok], axis=0).T).sum()) if ok.sum() > 1 else 0.0
    print(f"[align] frames with GPS fixes: {ok.sum()}/{N}; GPS path in window {path_m:.1f} m")
    if ok.sum() < 100 or path_m < 30:
        raise SystemExit(f"[gate] GPS too sparse/static for {sec} (fixes {ok.sum()}, path {path_m:.1f} m) — refusing")
    # similarity Procrustes on fix-covered frames (time correspondence, no arc-fraction assumption)
    Wm = W
    ma, mb = P2[ok].mean(0), Wm[ok].mean(0)
    A_, B_ = P2[ok] - ma, Wm[ok] - mb
    H = A_.T @ B_
    U, Sv, Vh = np.linalg.svd(H)
    D = np.eye(2); D[1, 1] = np.sign(np.linalg.det(Vh.T @ U.T))
    Rot = Vh.T @ D @ U.T
    scl = (Sv * np.diag(D)).sum() / max((A_ ** 2).sum(), 1e-9)
    P_new = (scl * (Rot @ (P2 - ma).T)).T + mb
    rms = float(np.sqrt(((P_new[ok] - Wm[ok]) ** 2).sum(1).mean()))
    reflected = np.linalg.det(Rot) < 0

    # gates
    steps = np.linalg.norm(np.diff(P_new, axis=0), axis=1)
    nz = steps[steps > 1e-6]
    sp = np.percentile(nz, 90) / max(np.percentile(nz, 10), 1e-9)
    th = np.arctan2(Rot[1, 0], Rot[0, 0])
    print(f"[align] N={N} scale={scl:.3f} m/unit rot={np.degrees(th):.1f}deg reflected={reflected}")
    print(f"[gate] spacing p90/p10 = {sp:.2f}  (want < ~6)")
    print(f"[gate] rms to GPS = {rms:.2f} m  (want < ~8)")

    # rebuild c2w in world (map metres): rotate plane coords by Rot, lift
    cz, sz = np.cos(th), np.sin(th)
    c2w = np.zeros((N, 4, 4)); c2w[:, 3, 3] = 1
    A3 = np.stack([b1, b2, n], 1)
    Rz3 = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    fwd_ang = []
    for i in range(N):
        M = Rz3 @ A3.T @ R_l[i]
        c2w[i, :3, :3] = M
        c2w[i, 0, 3], c2w[i, 1, 3] = P_new[i]
        c2w[i, 2, 3] = cam_h
    fwd = c2w[:, :2, 2]
    tang = np.gradient(gaussian_filter1d(P_new, 5, axis=0), axis=0)
    cosang = (fwd * tang).sum(1) / (np.linalg.norm(fwd, axis=1) * np.linalg.norm(tang, axis=1) + 1e-9)
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    print(f"[gate] forward-vs-motion p50 = {np.percentile(ang, 50):.1f} deg  (want < ~20)")

    # depth scale from ground plane, world-masked
    fx518, cy518 = K518[0, 0], K518[1, 2]
    kaps = []
    conf_th = 1.5
    for i in range(0, N, 10):
        z = np.load(files[i])
        depth = z['depth'][..., 0]; conf = z['depth_conf']
        am = cv2.imread(f'cubefaces_rgba/{sec}/c04_{i+1:05d}_Y000.png', cv2.IMREAD_UNCHANGED)[..., 3]
        am = cv2.resize(am, (518, 518), interpolation=cv2.INTER_NEAREST) > 127
        pitch = np.arcsin(np.clip(-c2w[i, 2, 2], -1, 1))
        for v in range(int(cy518) + 40, 500, 8):
            dep = np.arctan((v - cy518) / fx518) + pitch
            if dep <= np.radians(3):
                continue
            row_ok = am[v] & (conf[v] > conf_th)
            if row_ok.sum() < 15:
                continue
            kaps.append((cam_h / np.sin(dep)) / np.median(depth[v][row_ok]))
    if not kaps:
        conf_th = 0.5
        for i in range(0, N, 10):
            z = np.load(files[i])
            depth = z['depth'][..., 0]; conf = z['depth_conf']
            am = cv2.imread(f'cubefaces_rgba/{sec}/c04_{i+1:05d}_Y000.png', cv2.IMREAD_UNCHANGED)[..., 3]
            am = cv2.resize(am, (518, 518), interpolation=cv2.INTER_NEAREST) > 127
            pitch = np.arcsin(np.clip(-c2w[i, 2, 2], -1, 1))
            for v in range(int(cy518) + 40, 500, 8):
                dep = np.arctan((v - cy518) / fx518) + pitch
                if dep <= np.radians(3):
                    continue
                row_ok = am[v] & (conf[v] > conf_th)
                if row_ok.sum() < 15:
                    continue
                kaps.append((cam_h / np.sin(dep)) / np.median(depth[v][row_ok]))
        if kaps:
            print(f'[gate] kappa recovered with relaxed conf {conf_th}')
    kap = float(np.median(kaps)) if kaps else float('nan')
    if not np.isfinite(kap):
        kap = 45.0   # fallback: typical ground-plane calibration across sections
        print('[gate] depth kappa: NO valid road rows — using fallback 45.0 m/unit')
    print(f"[gate] depth kappa = {kap:.1f} m/unit from {len(kaps)} road rows "
          f"(recon-scale {scl:.1f}; ratio {kap/scl:.2f} — want ~0.5-2)")

    # fused cloud with calibrated depth
    pts, rgb = [], []
    Kl = K518.copy()
    for i in range(0, N, 2):
        z = np.load(files[i])
        depth = z['depth'][..., 0] * kap
        conf = z['depth_conf']
        img = np.transpose(z['images'], (1, 2, 0))
        am = cv2.imread(f'cubefaces_rgba/{sec}/c04_{i+1:05d}_Y000.png', cv2.IMREAD_UNCHANGED)[..., 3]
        am = cv2.resize(am, (518, 518), interpolation=cv2.INTER_NEAREST) > 127
        ys, xs = np.mgrid[0:518:4, 0:518:4]
        zs = depth[ys, xs]
        ok = (conf[ys, xs] > conf_th) & (zs > 1) & (zs < 60) & am[ys, xs]
        ys, xs, zs = ys[ok], xs[ok], zs[ok]
        pc = np.stack([(xs - Kl[0, 2]) / Kl[0, 0] * zs, (ys - Kl[1, 2]) / Kl[1, 1] * zs, zs], 1)
        R, C = c2w[i, :3, :3], c2w[i, :3, 3]
        pts.append(pc @ R.T + C)
        rgb.append((img[ys, xs] * 255).astype(np.uint8))
    P = np.concatenate(pts); RGB = np.concatenate(rgb)
    key = np.round(P / 0.10).astype(np.int64)
    _, idx = np.unique(key, axis=0, return_index=True)
    P, RGB = P[idx], RGB[idx]
    print(f"[cloud] {len(P)} points (0.10 m voxel)")
    assert len(P) > 10000, f"cloud degenerate ({len(P)} pts) — refusing to write scene" 

    out = f'colmap_db/{sec}/gps/sparse/0'
    os.makedirs(out, exist_ok=True)
    f_face = FACE / 2 / np.tan(np.radians(FOV / 2))
    with open(f'{out}/cameras.bin', 'wb') as f:
        f.write(struct.pack('<Q', 1))
        f.write(struct.pack('<iiQQ', 1, 1, FACE, FACE))
        f.write(struct.pack('<dddd', f_face, f_face, FACE/2, FACE/2))
    yaws = [0, 90, 180, 270]
    with open(f'{out}/images.bin', 'wb') as f:
        f.write(struct.pack('<Q', N * 4))
        iid = 0
        for i in range(N):
            for yaw in yaws:
                iid += 1
                Rc2w = c2w[i, :3, :3] @ roty(np.radians(-yaw))
                Rw2c = Rc2w.T
                t = -Rw2c @ c2w[i, :3, 3]
                q = rot2quat(Rw2c)
                f.write(struct.pack('<i', iid))
                f.write(struct.pack('<dddd', *q))
                f.write(struct.pack('<ddd', *t))
                f.write(struct.pack('<i', 1))
                f.write(f'c04_{i+1:05d}_Y{yaw:03d}.png'.encode() + b'\x00')
                f.write(struct.pack('<Q', 0))
    with open(f'{out}/points3D.bin', 'wb') as f:
        f.write(struct.pack('<Q', len(P)))
        for j in range(len(P)):
            f.write(struct.pack('<Q', j + 1))
            f.write(struct.pack('<ddd', *P[j]))
            f.write(struct.pack('<BBB', *RGB[j]))
            f.write(struct.pack('<d', 1.0))
            f.write(struct.pack('<Q', 0))
    gs = f'colmap_db/{sec}/gps/gs_scene'
    os.makedirs(gs, exist_ok=True)
    for link, target in [(f'{gs}/images', os.path.abspath(f'cubefaces_rgba/{sec}')),
                         (f'{gs}/sparse', os.path.abspath(f'colmap_db/{sec}/gps/sparse'))]:
        if os.path.islink(link):
            os.remove(link)
        os.symlink(target, link)
    np.savez(f'colmap_db/{sec}/gps/poses_aligned.npz', c2w=c2w, kappa=kap, scale=scl, dt=dt, A=A)
    print(f'[done] scene: {gs}')

if __name__ == '__main__':
    main(*sys.argv[1:5])
