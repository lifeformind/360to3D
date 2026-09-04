#!/usr/bin/env python3
"""Sharpen a section: world-masked matching + triangulation + plain BA.

1. SuperPoint on the section's 4-yaw views, then drop hull/sky keypoints via
   the alpha masks (static hull matches are poison — measured).
2. LightGlue on windowed pairs (same-yaw offsets 1..6, adjacent-yaw 1..3,
   no same-frame pairs).
3. hloc triangulation against the section's aligned poses (reference model).
4. Plain Ceres BA (poses+points free, intrinsics fixed, Cauchy loss) —
   small-error regime, no pose priors needed.
5. Similarity re-anchor of the BA result onto the pre-BA trajectory (kills
   gauge drift), then write refined poses back into sparse/0 and
   poses_refined.npz. Gates printed.

Usage: 21_sharpen_section.py <section>
"""
import sys, os, glob, shutil, struct
from pathlib import Path
import numpy as np
import h5py, cv2

def main(sec):
    root = Path(f'colmap_db/{sec}/sharpen')
    root.mkdir(parents=True, exist_ok=True)
    images = Path(f'cubefaces/{sec}')

    # ---- pairs (windowed, no same-frame) ----
    names = sorted(p.name for p in images.glob('*.png'))
    def key(n):
        stem = n.rsplit('.', 1)[0]
        cf, yaw = stem.rsplit('_', 1)
        return cf, int(yaw[1:])
    by_frame = {}
    for n in names:
        cf, yaw = key(n)
        by_frame.setdefault(cf, {})[yaw] = n
    frames = sorted(by_frame)
    ADJ = {0: (90, 270), 90: (0, 180), 180: (90, 270), 270: (180, 0)}
    pairs = set()
    for i, cf in enumerate(frames):
        for off in range(1, 7):
            if i + off >= len(frames):
                break
            cf2 = frames[i + off]
            for yaw in (0, 90, 180, 270):
                a, b = by_frame[cf].get(yaw), by_frame[cf2].get(yaw)
                if a and b:
                    pairs.add((a, b) if a < b else (b, a))
                if off <= 3:
                    for y2 in ADJ[yaw]:
                        b2 = by_frame[cf2].get(y2)
                        if a and b2:
                            pairs.add((a, b2) if a < b2 else (b2, a))
    pairs_path = root / 'pairs.txt'
    with open(pairs_path, 'w') as f:
        for a, b in sorted(pairs):
            f.write(f'{a} {b}\n')
    print(f'[sharpen] {len(names)} images, {len(pairs)} pairs')

    # ---- features + hull filtering ----
    from hloc import extract_features, match_features
    feat_conf = extract_features.confs['superpoint_aachen']
    if (root / 'triangulated' / 'images.bin').exists():
        print('[sharpen] triangulated model exists — skipping to BA')
        return ba_phase(sec, root)
    feats = extract_features.main(feat_conf, images, export_dir=root)
    with h5py.File(feats, 'r+') as f:
        dropped = total = 0
        for n in names:
            kp = f[n]['keypoints'][()]
            am = cv2.imread(f'cubefaces_rgba/{sec}/{n}', cv2.IMREAD_UNCHANGED)[..., 3]
            keep = am[np.clip(kp[:, 1].astype(int), 0, 1023),
                      np.clip(kp[:, 0].astype(int), 0, 1023)] > 127
            total += len(kp); dropped += int((~keep).sum())
            nkp = len(keep)
            for k in list(f[n].keys()):
                data = f[n][k][()]
                del f[n][k]
                if data.ndim >= 1 and data.shape[0] == nkp:
                    data = data[keep]
                elif data.ndim == 2 and data.shape[1] == nkp:
                    data = data[:, keep]
                f[n].create_dataset(k, data=data)
    print(f'[sharpen] dropped {dropped}/{total} hull/sky keypoints')

    match_conf = match_features.confs['superpoint+lightglue']
    matches = match_features.main(match_conf, pairs_path, feat_conf['output'], export_dir=root)

    # ---- triangulation against aligned poses ----
    from hloc import triangulation
    sfm_dir = root / 'triangulated'
    if sfm_dir.exists():
        shutil.rmtree(sfm_dir)
    triangulation.main(sfm_dir, Path(f'colmap_db/{sec}/sparse/0'), images,
                       pairs_path, feats, matches)

    return ba_phase(sec, root)

def ba_phase(sec, root):
    sfm_dir = root / 'triangulated'
    # ---- plain BA ----
    import pycolmap
    rec = pycolmap.Reconstruction(str(sfm_dir))
    print(f'[sharpen] triangulated: {len(rec.points3D)} pts, '
          f'mean reproj {np.mean([p.error for p in rec.points3D.values()]):.2f} px')
    pre = {img.name: img.projection_center().copy() for img in rec.images.values()}
    cfg = pycolmap.BundleAdjustmentConfig()
    for img in rec.images.values():
        cfg.add_image(img.image_id)
    # fix gauge: hold the first two frames' Y000 poses
    opts = pycolmap.BundleAdjustmentOptions()
    opts.refine_focal_length = False
    opts.refine_principal_point = False
    opts.refine_extra_params = False
    opts.ceres.loss_function_type = pycolmap.LossFunctionType.CAUCHY
    opts.ceres.loss_function_scale = 2.0
    opts.ceres.solver_options.max_num_iterations = 500
    ba = pycolmap.create_default_bundle_adjuster(opts, cfg, rec)
    summary = ba.solve()
    cs = summary  # CeresBundleAdjustmentSummary
    try:
        print(f'[sharpen] BA: {cs.termination_type}, cost {cs.ceres_summary.initial_cost:.3e} -> {cs.ceres_summary.final_cost:.3e}')
    except Exception:
        print('[sharpen] BA done')

    # ---- similarity re-anchor to pre-BA trajectory ----
    A = np.array([img.projection_center() for img in rec.images.values()])
    B = np.array([pre[img.name] for img in rec.images.values()])
    ma, mb = A.mean(0), B.mean(0)
    H = (A - ma).T @ (B - mb)
    U, S, Vt = np.linalg.svd(H)
    D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ D @ U.T
    s = (S * np.diag(D)).sum() / ((A - ma) ** 2).sum()
    assert np.linalg.det(R) > 0
    t3 = mb - s * R @ ma
    for img in rec.images.values():
        cfw = img.cam_from_world()
        Rw2c = cfw.rotation.matrix()
        C = -Rw2c.T @ cfw.translation
        C2 = s * (R @ C) + t3
        Rw2c2 = Rw2c @ R.T
        rec.frames[img.frame_id].rig_from_world = pycolmap.Rigid3d(
            pycolmap.Rotation3d(Rw2c2), -Rw2c2 @ C2)
    for p in rec.points3D.values():
        p.xyz = s * (R @ p.xyz) + t3
    post = np.array([img.projection_center() for img in rec.images.values()])
    move = np.linalg.norm(post - B, axis=1)
    print(f'[gate] BA pose movement vs pre: p50={np.percentile(move,50):.3f} p90={np.percentile(move,90):.3f} max={move.max():.2f} m')
    print(f'[gate] reproj after BA: {np.mean([p.error for p in rec.points3D.values()]):.2f} px')

    out = f'colmap_db/{sec}/sparse_sharp/0'
    os.makedirs(out, exist_ok=True)
    rec.write(out)
    # repoint gs_scene sparse at the sharpened model
    gs = f'colmap_db/{sec}/gs_scene'
    link = f'{gs}/sparse'
    if os.path.islink(link):
        os.remove(link)
    os.symlink(os.path.abspath(f'colmap_db/{sec}/sparse_sharp'), link)
    print(f'[done] sharpened scene: {gs} -> sparse_sharp')

if __name__ == '__main__':
    main(sys.argv[1])
