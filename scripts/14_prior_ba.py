#!/usr/bin/env python3
"""Prior-constrained bundle adjustment of the route-snapped poses.

1. Writes the snapped poses as a COLMAP reference model (all 4 yaw views).
2. hloc triangulation: imports SuperPoint/LightGlue features+matches into a
   COLMAP database, geometric verification, triangulates with poses fixed.
3. Injects Cartesian position priors (snapped positions, generous std) into
   the database's pose_priors table.
4. Runs COLMAP pose_prior_mapper: incremental mapping where image
   registration is anchored by the priors — local geometry from real
   correspondences, global layout held by the map.

Usage: 14_prior_ba.py <scene> <prior_std_xy_m> <prior_std_z_m>
"""
import os, sys, struct, sqlite3, subprocess, shutil
from pathlib import Path
import numpy as np

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

FACE, FOV = 1024, 110.0

def write_reference_model(snap, frames_dir, out_dir):
    d = np.load(snap, allow_pickle=True)
    c2w0 = d["c2w"]
    N = len(c2w0)
    frame_ids = sorted(os.path.splitext(f)[0] for f in os.listdir(frames_dir) if f.endswith(".jpg"))
    assert len(frame_ids) == N
    os.makedirs(out_dir, exist_ok=True)
    f_face = FACE / 2 / np.tan(np.radians(FOV / 2))
    with open(f"{out_dir}/cameras.bin", "wb") as f:
        f.write(struct.pack("<Q", 1))
        f.write(struct.pack("<iiQQ", 1, 1, FACE, FACE))
        f.write(struct.pack("<dddd", f_face, f_face, FACE/2, FACE/2))
    yaws = [0, 90, 180, 270]
    names, centers = [], []
    with open(f"{out_dir}/images.bin", "wb") as f:
        f.write(struct.pack("<Q", N * len(yaws)))
        img_id = 0
        for i in range(N):
            for yaw in yaws:
                img_id += 1
                Rc2w = c2w0[i, :3, :3] @ roty(np.radians(-yaw))
                C = c2w0[i, :3, 3]
                Rw2c = Rc2w.T
                t = -Rw2c @ C
                q = rot2quat(Rw2c)
                name = f"{frame_ids[i]}_Y{yaw:03d}.png"
                names.append(name); centers.append(C)
                f.write(struct.pack("<i", img_id))
                f.write(struct.pack("<dddd", *q))
                f.write(struct.pack("<ddd", *t))
                f.write(struct.pack("<i", 1))
                f.write(name.encode() + b"\x00")
                f.write(struct.pack("<Q", 0))
    with open(f"{out_dir}/points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", 0))
    return names, np.array(centers)

def main(scene, std_xy, std_z):
    std_xy, std_z = float(std_xy), float(std_z)
    root = Path(f"colmap_db/{scene}/ba")
    images = Path(f"cubefaces/{scene}")
    ref = root / "reference_model"
    names, centers = write_reference_model(
        f"colmap_db/{scene}/snapped/poses_snapped.npz", f"frames/{scene}/c04", ref)
    print(f"reference model: {len(names)} images")

    from hloc import triangulation
    sfm_dir = root / "triangulated"
    if not (sfm_dir / "database.db").exists():
        if sfm_dir.exists():
            shutil.rmtree(sfm_dir)
        triangulation.main(
            sfm_dir, ref, images,
            root / "pairs_windowed.txt",
            root / "feats-superpoint-n4096-r1024.h5",
            root / "feats-superpoint-n4096-r1024_matches-superpoint-lightglue_pairs_windowed.h5",
        )
    else:
        print("triangulated model exists — skipping to prior injection")

    # inject Cartesian position priors (COLMAP 4.x schema:
    # pose_prior_id, corr_data_id, corr_sensor_id, corr_sensor_type=CAMERA(0),
    # position, position_covariance, gravity, coordinate_system=CARTESIAN(1))
    db = sqlite3.connect(sfm_dir / "database.db")
    cur = db.cursor()
    cur.execute("DELETE FROM pose_priors")
    rows = list(cur.execute("SELECT name, image_id, camera_id FROM images"))
    name2row = {r[0]: r for r in rows}
    cov = np.diag([std_xy**2, std_xy**2, std_z**2]).astype(np.float64)
    n = 0
    for name, C in zip(names, centers):
        r = name2row.get(name)
        if r is None:
            continue
        _, iid, cam_id = r
        cur.execute("INSERT INTO pose_priors (corr_data_id, corr_sensor_id, corr_sensor_type, "
                    "position, position_covariance, gravity, coordinate_system) VALUES (?,?,?,?,?,?,?)",
                    (iid, cam_id, 0, np.asarray(C, np.float64).tobytes(),
                     cov.tobytes(), None, 1))
        n += 1
    db.commit(); db.close()
    print(f"injected {n} position priors (std xy={std_xy} m, z={std_z} m)")

    out = root / "prior_ba"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    colmap = os.path.expandvars("$PWD/tools/colmap-install/bin/colmap")
    env = dict(os.environ,
               LD_LIBRARY_PATH=os.path.abspath("tools/miniforge/envs/colmapdeps/lib"))
    subprocess.run([colmap, "pose_prior_mapper",
                    "--database_path", str(sfm_dir / "database.db"),
                    "--image_path", str(images),
                    "--output_path", str(out),
                    "--Mapper.ba_refine_focal_length", "0",
                    "--Mapper.ba_refine_extra_params", "0"],
                   check=True, env=env)
    print("pose_prior_mapper done ->", out)

if __name__ == "__main__":
    main(*sys.argv[1:4])
