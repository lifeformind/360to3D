#!/usr/bin/env python3
"""Pose-prior bundle adjustment of the triangulated model (global refinement).

Takes the hloc-triangulated reconstruction (snapped poses held fixed during
triangulation), frees all poses and points, and solves a single global BA
with per-image Cartesian position priors at the snapped positions. Local
geometry comes from real SuperPoint correspondences; the priors keep the
global layout on the circuit. Camera intrinsics stay fixed.

Usage: 15_prior_refine.py <scene> <prior_std_xy_m> <prior_std_z_m> <out_model_dir>
"""
import os, sys
import numpy as np
import pycolmap

def main(scene, std_xy, std_z, out_dir):
    std_xy, std_z = float(std_xy), float(std_z)
    tri = f"colmap_db/{scene}/ba/triangulated"
    rec = pycolmap.Reconstruction(tri)
    print(f"loaded: {rec.num_reg_images()} images, {len(rec.points3D)} points")

    snap = np.load(f"colmap_db/{scene}/snapped/poses_snapped.npz", allow_pickle=True)
    # rebuild name -> snapped center exactly as the reference model was written
    frame_ids = sorted(os.path.splitext(f)[0] for f in os.listdir(f"frames/{scene}/c04")
                       if f.endswith(".jpg"))
    c2w0 = snap["c2w"]
    def roty(th):
        c, s = np.cos(th), np.sin(th)
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    name2c = {}
    for i, fid in enumerate(frame_ids):
        for yaw in (0, 90, 180, 270):
            name2c[f"{fid}_Y{yaw:03d}.png"] = c2w0[i, :3, 3]

    cov = np.diag([std_xy**2, std_xy**2, std_z**2])
    priors = []
    cfg = pycolmap.BundleAdjustmentConfig()
    for img in rec.images.values():
        if not img.has_pose:
            continue
        cfg.add_image(img.image_id)
        cfg.set_constant_cam_intrinsics(img.camera_id) if hasattr(cfg, "set_constant_cam_intrinsics") else None
        p = pycolmap.PosePrior()
        p.position = np.asarray(name2c[img.name], np.float64)
        p.position_covariance = cov
        p.coordinate_system = pycolmap.PosePriorCoordinateSystem.CARTESIAN
        p.corr_data_id = pycolmap.data_t(pycolmap.sensor_t(pycolmap.SensorType.CAMERA, img.camera_id), img.image_id) if hasattr(pycolmap, "data_t") else p.corr_data_id
        priors.append(p)
    try:
        cfg.constant_cam_intrinsics(1)
    except Exception:
        pass

    opts = pycolmap.BundleAdjustmentOptions()
    opts.refine_focal_length = False
    opts.refine_principal_point = False
    opts.refine_extra_params = False
    opts.ceres.loss_function_type = pycolmap.LossFunctionType.CAUCHY
    opts.ceres.loss_function_scale = 2.0
    opts.ceres.solver_options.max_num_iterations = 2000
    popts = pycolmap.PosePriorBundleAdjustmentOptions()
    popts.alignment_ransac.max_error = 5.0

    print("building pose-prior bundle adjuster...")
    ba = pycolmap.create_pose_prior_bundle_adjuster(opts, popts, cfg, priors, rec)
    summary = ba.solve()
    cs = summary.ceres_summary
    print(f"termination={summary.termination_type} iters={cs.num_successful_steps} "
          f"cost {cs.initial_cost:.3e} -> {cs.final_cost:.3e}")

    os.makedirs(out_dir, exist_ok=True)
    rec.write(out_dir)
    print("wrote refined model ->", out_dir)

if __name__ == "__main__":
    main(*sys.argv[1:5])
