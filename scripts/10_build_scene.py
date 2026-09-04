#!/usr/bin/env python3
"""Build a COLMAP-format 3DGS training scene from snapped poses + LingBot depth.

- Expands the forward-view poses to all 4 yaw views (shared optical center,
  exact 90-degree yaw steps, verified rig convention: cam_from_rig quaternion
  (cos t/2, 0, -sin t/2, 0) => c2w_k = c2w_0 @ Roty(+theta_k)).
- Fuses a colored point cloud by back-projecting LingBot depth maps
  (conf-filtered, range-capped) through the corrected poses, voxel-downsampled.
- Writes COLMAP 3.x binaries (cameras/images/points3D.bin) that the
  gaussian-splatting loader reads, plus gs_scene/ symlinks.

Usage: 10_build_scene.py <snap_npz> <lingbot_npz_dir> <scene>
"""
import os, sys, glob, struct
import numpy as np

FACE, FOV = 1024, 110.0
STRIDE, PIX_STEP = 3, 6
CONF_MIN, DEPTH_MAX_M, VOXEL_M = 1.5, 80.0, 0.15

def roty(th):
    c, s = np.cos(th), np.sin(th)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

def rot2quat(R):
    # returns wxyz
    K = np.array([
        [R[0,0]-R[1,1]-R[2,2], 0, 0, 0],
        [R[0,1]+R[1,0], R[1,1]-R[0,0]-R[2,2], 0, 0],
        [R[0,2]+R[2,0], R[1,2]+R[2,1], R[2,2]-R[0,0]-R[1,1], 0],
        [R[2,1]-R[1,2], R[0,2]-R[2,0], R[1,0]-R[0,1], R[0,0]+R[1,1]+R[2,2]]]) / 3.0
    w, V = np.linalg.eigh(K)
    q = V[[3, 0, 1, 2], np.argmax(w)]
    return q * np.sign(q[0] + 1e-12)

def main(snap_npz, npz_dir, scene):
    d = np.load(snap_npz, allow_pickle=True)
    c2w0, K518 = d["c2w"], d["intrinsic"]
    scale = float(d["m_per_recon_unit"])
    names = list(d["names"])
    N = len(c2w0)
    files = sorted(glob.glob(os.path.join(npz_dir, "frame_*.npz")))
    assert len(files) == N

    yaws = [0, 90, 180, 270]
    # per-yaw poses; image name convention matches cubefaces_rgba/<scene>: c04_XXXXX_Yyyy.png
    frame_ids = sorted(os.path.splitext(f)[0] for f in os.listdir(f"frames/{scene}/c04") if f.endswith('.jpg'))
    assert len(frame_ids) == N, (len(frame_ids), N)

    # sanity: yaw-90 forward should be 90deg clockwise (bearing -90) of yaw-0
    b0 = np.arctan2(c2w0[5, 1, 2], c2w0[5, 0, 2])
    c2w90 = c2w0[5, :3, :3] @ roty(np.radians(-90))
    b90 = np.arctan2(c2w90[1, 2], c2w90[0, 2])
    dbear = np.degrees((b90 - b0 + np.pi) % (2*np.pi) - np.pi)
    print(f"yaw-90 bearing offset check: {dbear:.1f} deg (want ~-90)")
    assert abs(dbear + 90) < 5, "yaw convention broken"

    # ---- fuse cloud ----
    fx, fy, cx, cy = K518[0,0], K518[1,1], K518[0,2], K518[1,2]
    pts_all, rgb_all = [], []
    for i in range(0, N, STRIDE):
        z = np.load(files[i])
        depth = z["depth"][..., 0]
        conf = z["depth_conf"]
        img = np.transpose(z["images"], (1, 2, 0))
        H, W = depth.shape
        ys, xs = np.mgrid[0:H:PIX_STEP, 0:W:PIX_STEP]
        ys, xs = ys.ravel(), xs.ravel()
        zvals = depth[ys, xs]
        ok = (conf[ys, xs] > CONF_MIN) & (zvals > 1e-3) & (zvals * scale < DEPTH_MAX_M)
        ys, xs, zvals = ys[ok], xs[ok], zvals[ok]
        pc = np.stack([(xs - cx) / fx * zvals, (ys - cy) / fy * zvals, zvals], 1) * scale
        R, C = c2w0[i, :3, :3], c2w0[i, :3, 3]
        pts_all.append(pc @ R.T + C)
        rgb_all.append((img[ys, xs] * 255).astype(np.uint8))
    P = np.concatenate(pts_all); RGB = np.concatenate(rgb_all)
    print(f"raw fused points: {len(P)}")
    key = np.round(P / VOXEL_M).astype(np.int64)
    _, idx = np.unique(key, axis=0, return_index=True)
    P, RGB = P[idx], RGB[idx]
    print(f"voxel-downsampled ({VOXEL_M} m): {len(P)}")

    # ---- write COLMAP binaries ----
    out = f"colmap_db/{scene}/sparse/0"
    os.makedirs(out, exist_ok=True)
    f_face = FACE / 2 / np.tan(np.radians(FOV / 2))
    with open(f"{out}/cameras.bin", "wb") as f:
        f.write(struct.pack("<Q", 1))
        f.write(struct.pack("<iiQQ", 1, 1, FACE, FACE))       # PINHOLE
        f.write(struct.pack("<dddd", f_face, f_face, FACE/2, FACE/2))
    with open(f"{out}/images.bin", "wb") as f:
        f.write(struct.pack("<Q", N * len(yaws)))
        img_id = 0
        for i in range(N):
            for k, yaw in enumerate(yaws):
                img_id += 1
                Rc2w = c2w0[i, :3, :3] @ roty(np.radians(-yaw))
                C = c2w0[i, :3, 3]
                Rw2c = Rc2w.T
                t = -Rw2c @ C
                q = rot2quat(Rw2c)
                f.write(struct.pack("<i", img_id))
                f.write(struct.pack("<dddd", *q))
                f.write(struct.pack("<ddd", *t))
                f.write(struct.pack("<i", 1))
                f.write(f"{frame_ids[i]}_Y{yaw:03d}.png".encode() + b"\x00")
                f.write(struct.pack("<Q", 0))
    with open(f"{out}/points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", len(P)))
        for j in range(len(P)):
            f.write(struct.pack("<Q", j + 1))
            f.write(struct.pack("<ddd", *P[j]))
            f.write(struct.pack("<BBB", *RGB[j]))
            f.write(struct.pack("<d", 1.0))
            f.write(struct.pack("<Q", 0))
    print(f"wrote {out}: {N*len(yaws)} images, {len(P)} points")

    gs = f"colmap_db/{scene}/gs_scene"
    os.makedirs(gs, exist_ok=True)
    pd = os.path.abspath(".")
    for link, target in [(f"{gs}/images", f"{pd}/cubefaces_rgba/{scene}"),
                         (f"{gs}/sparse", f"{pd}/colmap_db/{scene}/sparse")]:
        if os.path.islink(link):
            os.remove(link)
        os.symlink(target, link)
    print(f"gs_scene ready: {gs}")

if __name__ == "__main__":
    main(*sys.argv[1:4])
