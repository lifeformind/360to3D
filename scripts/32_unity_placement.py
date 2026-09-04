#!/usr/bin/env python3
"""Per-section world transforms for the Unity assembly (GPX-anchored).

For each section: PLY (gsplat-normalized frame) -> old map-metre frame
(inverse of gsplat Parser normalize transform) -> ENU metres (GPX delta from
31_gpx_anchor.py; z: road plane at 0, cameras at 3 m) -> Unity (x=East,
y=Up, z=North; left-handed => one negative scale axis).
Writes colmap_db/gpx/section_transforms.json (full, with checks),
scripts/unity/unity_placement.json (flat array for the C# placer) and a
bird's-eye assembly check PNG built from the actual PLY gaussians.
"""
import sys, json, os
import numpy as np, cv2
sys.path.insert(0, 'tools/gsplat/examples')
from datasets.colmap import Parser

D = json.load(open('colmap_db/gpx/section_deltas.json'))
g = np.load('raw/gpx_004.npz'); gx, gy = g['x'], g['y']
SWAP = np.array([[1., 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]])   # ENU(x,y,z) -> Unity(x,y=up,z=north)
CAM_H = 3.0
DROP = {'s10': 'parked for its whole window (video static 315-366 s, no GPS fixes); LingBot trajectory degenerate '
               '(old scale 4097 m/unit) so the trained splat has no valid geometry. Road coverage is provided by s09/s11/s12.'}
FLAG = {'s11': 'mostly parked (two stops) — trajectory is ~23 m only; scale re-fit 0.15x; geometry plausible but verify in Unity.',
        's08': 'largest GPS-fit residual (13.4 m rms) — check alignment with s07/s09 in the overlap zones.'}

def read_ply_means(path, every=40):
    f = open(path, 'rb'); hdr = b''
    while not hdr.endswith(b'end_header\n'):
        hdr += f.readline()
    n = int([l for l in hdr.decode().split('\n') if l.startswith('element vertex')][0].split()[-1])
    d = np.fromfile(path, dtype=np.float32, offset=len(hdr)).reshape(n, 59)[::every]
    op = 1 / (1 + np.exp(-d[:, 51]))
    return d[:, :3].astype(np.float64), op

def mat2quat(R):   # returns (x, y, z, w), standard formula (valid for Unity's Quaternion)
    m = R; tr = np.trace(m)
    if tr > 0:
        S = np.sqrt(tr + 1.0) * 2; w = 0.25 * S; x = (m[2,1]-m[1,2])/S; y = (m[0,2]-m[2,0])/S; z = (m[1,0]-m[0,1])/S
    elif m[0,0] > m[1,1] and m[0,0] > m[2,2]:
        S = np.sqrt(1.0 + m[0,0] - m[1,1] - m[2,2]) * 2; w = (m[2,1]-m[1,2])/S; x = 0.25*S; y = (m[0,1]+m[1,0])/S; z = (m[0,2]+m[2,0])/S
    elif m[1,1] > m[2,2]:
        S = np.sqrt(1.0 + m[1,1] - m[0,0] - m[2,2]) * 2; w = (m[0,2]-m[2,0])/S; x = (m[0,1]+m[1,0])/S; y = 0.25*S; z = (m[1,2]+m[2,1])/S
    else:
        S = np.sqrt(1.0 + m[2,2] - m[0,0] - m[1,1]) * 2; w = (m[1,0]-m[0,1])/S; x = (m[0,2]+m[2,0])/S; y = (m[1,2]+m[2,1])/S; z = 0.25*S
    return [float(x), float(y), float(z), float(w)]

out, flat, flat_noterr, seam = {}, [], [], {}
TERR = os.path.exists('colmap_db/gpx/dtm_profile.npz')
if TERR:
    prof = np.load('colmap_db/gpx/dtm_profile.npz')
    ele_at = lambda tq: np.interp(tq, prof['t'], prof['ele_dtm'])
    ELE0 = float(ele_at(np.array([0.0]))[0])
    print(f'[terrain] DTM profile loaded; Unity y=0 at track start (DTM {ELE0:.1f} m)')
def rodrigues(axis, th):
    a = axis / np.linalg.norm(axis); K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K
W, H = 1300, 620
bird = np.full((H, W, 3), 30, np.uint8)
to_px = lambda E: np.stack([E[:, 0] + 120, H - 60 - (E[:, 1] + 240)], 1).astype(int)
gp = to_px(np.stack([gx, gy], 1))
for i in range(len(gp) - 1):
    cv2.line(bird, tuple(gp[i]), tuple(gp[i + 1]), (255, 255, 255), 1)
print(f'{"sec":4s} {"invT_check":>10s} {"rmsGPS":>7s} {"s_unity":>8s} {"road_z":>7s} {"float%":>7s} {"npts":>8s}   terrain: ele_mid slope% tilt fit_rms')
for k in range(1, 19):
    sec = f's{k:02d}'; d = D['sections'][sec]
    parser = Parser(f'colmap_db/{sec}/gs_scene', factor=1, normalize=True, test_every=8)
    T = parser.transform; Tinv = np.linalg.inv(T)
    # check 1: normalized cams -> inv(T) must reproduce poses_aligned (old frame)
    old = np.load(f'colmap_db/{sec}/poses_aligned.npz')['c2w']
    c2w_old = np.array([Tinv @ c for c in parser.camtoworlds]); cams_old = c2w_old[:, :3, 3]
    names = parser.image_names
    idx = np.array([int(n[4:9]) - 1 for n in names])
    chk = float(np.abs(cams_old - old[idx, :3, 3]).max())
    # delta (old -> ENU)
    s = d['delta_scale']; th = np.radians(d['delta_rot_deg']); c, sn = np.cos(th), np.sin(th)
    Delta = np.eye(4); Delta[:2, :2] = s * np.array([[c, -sn], [sn, c]]); Delta[2, 2] = s
    Delta[:3, 3] = [d['delta_t'][0], d['delta_t'][1], CAM_H * (1 - s)]
    M_enu = Delta @ Tinv
    # check 2: cameras in ENU vs GPS by time
    fg = d['frames'][0] + idx
    cam_enu = (Delta @ np.c_[cams_old, np.ones(len(cams_old))].T).T[:, :3]
    tq = (fg - 1) / 10.0 + d['dt']
    gt = g['t']; G = np.stack([np.interp(tq, gt, gx), np.interp(tq, gt, gy)], 1)
    rms = float(np.sqrt(((cam_enu[:, :2] - G) ** 2).sum(1).mean()))
    # Unity decomposition
    M_u = SWAP @ M_enu
    su = float(np.cbrt(abs(np.linalg.det(M_u[:3, :3]))))
    R = M_u[:3, :3] @ np.diag([1 / su, 1 / su, -1 / su])
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-6) and np.linalg.det(R) > 0, sec
    q = mat2quat(R)
    # bird's-eye + road-height check from the real PLY
    P, op = read_ply_means(f'splat_output/{sec}/ply/point_cloud_29999.ply')
    P = P[op > 0.3]
    E = (M_enu @ np.c_[P, np.ones(len(P))].T).T[:, :3]
    # points near the camera path (horizontal < 4 m): median z should be ~0 (road) .. cameras at 3 m
    from scipy.spatial import cKDTree
    # Vertical: measured on the trained PLYs, the road stayed 3 m below the cameras in the OLD frame
    # (ground-plane-calibrated init cloud won over the map-scaled trajectory), so road_old z = 0 and the
    # delta needs NO z offset: new_z = s * old_z. Road plane -> z = 0 in every section by construction.
    Delta[2, 3] = 0.0; M_enu = Delta @ Tinv; M_u = SWAP @ M_enu
    cam_enu[:, 2] -= CAM_H * (1 - s); E[:, 2] -= CAM_H * (1 - s)
    M_enu_flat = M_enu.copy(); M_u_flat = SWAP @ M_enu_flat
    terr = dict(applied=False)
    if TERR:
        # terrain: fit elevation vs along-track distance over this section's frames -> tilt + offset
        ele = ele_at(tq) - ELE0
        dist = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(G, axis=0), axis=1))])
        order = np.argsort(tq); dist = dist  # frames are time ordered already
        # chord through the overlap zones (first/last 64 frames = frames shared with the neighbours), so
        # consecutive sections agree on the road height where they meet
        ov = min(64, len(ele) // 4)
        e0, e1 = float(np.mean(ele[:ov])), float(np.mean(ele[-ov:])); d0, d1 = float(np.mean(dist[:ov])), float(np.mean(dist[-ov:]))
        mfit = (e1 - e0) / max(d1 - d0, 1e-6); cfit = e0 - mfit * d0
        fit_rms = float(np.sqrt(((mfit * dist + cfit - ele) ** 2).mean()))
        dvec = G[-1] - G[0]; dvec = dvec / max(np.linalg.norm(dvec), 1e-9)
        if dist[-1] < 50:   # parked/short section: offset only, no tilt
            mfit = 0.0; cfit = float(np.mean(ele)); fit_rms = float(np.std(ele))
        # offset so the chord passes through the section centroid (dist mean) — tilt is about the centroid
        ele_mid = float(mfit * np.mean(dist) + cfit)
        th_t = np.arctan(mfit)
        Rt = rodrigues(np.array([dvec[1], -dvec[0], 0.0]), th_t)
        c = np.array([cam_enu[:, 0].mean(), cam_enu[:, 1].mean(), 0.0])
        Tt = np.eye(4); Tt[:3, :3] = Rt; Tt[:3, 3] = c - Rt @ c + [0, 0, ele_mid]
        M_enu = Tt @ M_enu; M_u = SWAP @ M_enu
        cam_enu = (Tt @ np.c_[cam_enu, np.ones(len(cam_enu))].T).T[:, :3]
        E = (Tt @ np.c_[E, np.ones(len(E))].T).T[:, :3]
        terr = dict(applied=True, ele_mid_m=ele_mid, slope_pct=float(100 * mfit), tilt_deg=float(np.degrees(th_t)), linear_fit_rms_m=fit_rms)
    # check: mode of points just below the camera path should now sit at ~0 (the road)
    E_flat = (M_enu_flat @ np.c_[P, np.ones(len(P))].T).T[:, :3]
    near = cKDTree(cam_enu[:, :2]).query(E_flat[:, :2], distance_upper_bound=2.5)[0] < 2.5
    zb = E_flat[near, 2]; zb = zb[(zb > -20) & (zb < min(2.5, 3 * s - 0.5))]
    if len(zb) >= 20:
        hh, bb = np.histogram(zb, bins=np.arange(-20, 2.5, 0.25)); road_z = float(bb[np.argmax(hh)] + 0.125)
    else:
        road_z = float('nan')
    floaters = float(((E[:, 2] > 40) | (E[:, 2] < -10)).mean() * 100)
    Rfin = M_enu[:3, :3] @ T[:3, :3]; Rfin = Rfin / np.cbrt(np.linalg.det(Rfin))   # old frame -> final ENU, rotation part
    seam[sec] = dict(fg=fg, cam=cam_enu, cam_h=CAM_H * s, R=np.einsum('ab,nbc->nac', Rfin, c2w_old[:, :3, :3] / np.cbrt(np.linalg.det(c2w_old[0, :3, :3]))))
    keep = ~((E[:, 2] > 40) | (E[:, 2] < -10))
    col = tuple(int(v) for v in cv2.cvtColor(np.uint8([[[int(180 * (k - 1) / 18), 200, 230]]]), cv2.COLOR_HSV2BGR)[0, 0])
    if sec in DROP: col = (80, 80, 80)
    pp = to_px(E[keep])
    ok = (pp[:, 0] >= 0) & (pp[:, 0] < W) & (pp[:, 1] >= 0) & (pp[:, 1] < H)
    bird[pp[ok, 1], pp[ok, 0]] = col
    cp = to_px(cam_enu); cv2.putText(bird, sec, tuple(cp[len(cp)//2] + [4, -4]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    tinfo = f"   {terr['ele_mid_m']:6.1f} {terr['slope_pct']:6.1f} {terr['tilt_deg']:5.1f} {terr['linear_fit_rms_m']:5.2f}" if terr['applied'] else ''
    print(f'{sec:4s} {chk:10.2e} {rms:7.2f} {su:8.3f} {road_z:7.2f} {floaters:7.2f} {len(P):8d}{tinfo}')
    status = 'drop' if sec in DROP else ('check' if sec in FLAG else 'ok')
    qf = mat2quat(M_u_flat[:3, :3] @ np.diag([1 / su, 1 / su, -1 / su]))
    flat_noterr.append(dict(name=sec, status=status, px=M_u_flat[0, 3], py=M_u_flat[1, 3], pz=M_u_flat[2, 3],
                            qx=qf[0], qy=qf[1], qz=qf[2], qw=qf[3], sx=su, sy=su, sz=-su))
    out[sec] = dict(status=status, terrain=terr, road_mode_check_m=road_z, note=DROP.get(sec, FLAG.get(sec, '')), frames=d['frames'], rms_gps_m=rms,
                    M_ply_to_enu=M_enu.tolist(), unity=dict(position=M_u[:3, 3].tolist(), rotation_xyzw=q,
                    scale=[su, su, -su]), ply=f'splat_output/{sec}/ply/point_cloud_29999.ply')
    flat.append(dict(name=sec, status=status, px=M_u[0, 3], py=M_u[1, 3], pz=M_u[2, 3],
                     qx=q[0], qy=q[1], qz=q[2], qw=q[3], sx=su, sy=su, sz=-su))
# seam check: same global frame seen by consecutive sections -> position disagreement after placement
print('seam check (shared frames of consecutive sections, camera position disagreement in metres):')
for k in range(1, 18):
    a, b = f's{k:02d}', f's{k+1:02d}'
    common, ia, ib = np.intersect1d(seam[a]['fg'], seam[b]['fg'], return_indices=True)
    if len(common) == 0: continue
    dxy = np.linalg.norm(seam[a]['cam'][ia, :2] - seam[b]['cam'][ib, :2], axis=1)
    dz = (seam[a]['cam'][ia, 2] - seam[a]['cam_h']) - (seam[b]['cam'][ib, 2] - seam[b]['cam_h'])   # road-plane height difference
    out[a]['seam_to_next_m'] = dict(xy_mean=float(dxy.mean()), xy_max=float(dxy.max()), z_mean=float(dz.mean()))
    print(f'  {a}->{b}: {len(common):3d} shared frames  xy mean {dxy.mean():5.2f}  max {dxy.max():5.2f}   road dz mean {dz.mean():5.2f}')
json.dump(dict(frame='ENU metres, origin = first GPX fix (lat %.7f lon %.7f), x=East y=North z=Up; road plane z=0, cameras z=3' % (g['lat'][0], g['lon'][0]),
               unity_frame='x=East, y=Up, z=North (left-handed); apply position/rotation(xyzw)/scale to the GaussianSplatRenderer object of each section PLY',
               dt_video_to_gps_s=D['dt'], sections=out), open('colmap_db/gpx/section_transforms.json', 'w'), indent=1)
np.savez('colmap_db/gpx/section_cams_enu.npz', **{f'{k}_fg': v['fg'] for k, v in seam.items()}, **{f'{k}_cam': v['cam'] for k, v in seam.items()},
         **{f'{k}_cam_h': np.float64(v['cam_h']) for k, v in seam.items()}, **{f'{k}_R': v['R'] for k, v in seam.items()})
json.dump(dict(items=flat), open('scripts/unity/unity_placement.json', 'w'), indent=1)
json.dump(dict(items=flat_noterr), open('scripts/unity/unity_placement_flat.json', 'w'), indent=1)
for i in range(0, W, 100): cv2.putText(bird, f'{i-120}', (i, H - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)
cv2.imwrite('colmap_db/gpx/birdseye_assembly_enu.png', bird)
print('[done] colmap_db/gpx/section_transforms.json, scripts/unity/unity_placement.json, colmap_db/gpx/birdseye_assembly_enu.png')
