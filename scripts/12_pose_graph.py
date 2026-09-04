#!/usr/bin/env python3
"""Elastic pose-graph fusion of LingBot relative poses with the map route.

The hard snap (09) put every camera ON the drawn route line and its yaw on
the tangent, which destroyed LingBot's locally-excellent relative geometry
and produced multi-view inconsistency (= blur) that photometric pose
optimization cannot recover (basin too narrow). This stage instead solves a
planar pose graph over frames i with variables (x_i, y_i, yaw_i):

  binary constraints (strong): consecutive relative motion must match
      LingBot's relative pose, rotated into world by yaw_i and rescaled by
      the smooth local drift factor implied by the 09 arc mapping;
  unary constraints (weak):    position stays near the mapped route point,
      yaw stays near the camera-forward bearing implied by route tangent.

Result: locally rigid (sharp-trainable), globally on the circuit (drivable).
Heights and pitch/roll are carried over from the snapped poses.

Usage: 12_pose_graph.py <snap_npz> <lingbot_npz_dir> <out_npz>
"""
import sys, glob, os
import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import gaussian_filter1d

W_REL_POS = 10.0     # weight: relative position residuals (per metre)
W_REL_YAW = 20.0     # weight: relative yaw residuals (per rad)
W_ROUTE = 0.5        # weight: stay near route (per metre) — soft
W_YAW = 1.0          # weight: yaw near route-implied camera bearing (per rad)
HP_SIGMA = 15        # frames; relative-yaw drift removal scale

def main(snap_npz, npz_dir, out_npz):
    d = np.load(snap_npz, allow_pickle=True)
    c2w_snap = d["c2w"]
    N = len(c2w_snap)
    files = sorted(glob.glob(os.path.join(npz_dir, "frame_*.npz")))
    assert len(files) == N

    # LingBot camera-to-world poses (recon frame)
    R_l, C_l = [], []
    for f in files:
        E = np.load(f)["extrinsic"]
        R, t = E[:, :3], E[:, 3]
        R_l.append(R.T); C_l.append(-R.T @ t)
    R_l = np.array(R_l); C_l = np.array(C_l)

    # target route positions + yaws from the snapped poses (map frame, metres)
    P_route = c2w_snap[:, :2, 3]
    fwd = c2w_snap[:, :3, 2]
    yaw_route = np.arctan2(fwd[:, 1], fwd[:, 0])
    yaw_route_u = np.unwrap(yaw_route)

    # relative planar motion between consecutive frames in the LingBot frame,
    # expressed in the *local camera-forward* coordinate system so it can be
    # re-embedded at any global yaw. Planarization via the recon ground plane.
    mu = C_l.mean(0)
    _, _, Vt = np.linalg.svd(C_l - mu, full_matrices=False)
    b1, b2, n = Vt[0], Vt[1], Vt[2]
    up_hint = -R_l[:, :, 1].mean(0)          # camera -y is up-ish
    if n @ up_hint < 0:
        n, b2 = -n, -b2
    P2 = np.stack([(C_l - mu) @ b1, (C_l - mu) @ b2], 1)
    f2 = np.stack([R_l[:, :, 2] @ b1, R_l[:, :, 2] @ b2], 1)
    yaw_l = np.unwrap(np.arctan2(f2[:, 1], f2[:, 0]))

    # local drift rescale: smooth ratio of route speed to recon speed
    step_l = np.linalg.norm(np.diff(P2, axis=0), axis=1)
    step_r = np.linalg.norm(np.diff(P_route, axis=0), axis=1)
    ratio = gaussian_filter1d(step_r, 15) / np.maximum(gaussian_filter1d(step_l, 15), 1e-6)
    # high-pass the relative yaws: their low-frequency component IS the
    # orientation drift; replace it with the route's own turn profile so the
    # chain cannot re-import drift while steering detail survives
    d_yaw_raw = np.diff(yaw_l)
    d_yaw_route = np.diff(yaw_route_u)
    d_yaw = d_yaw_raw + gaussian_filter1d(d_yaw_route - d_yaw_raw, HP_SIGMA)
    # relative displacement in frame i's camera-forward coords
    rel = np.empty((N - 1, 2))
    for i in range(N - 1):
        c, s = np.cos(yaw_l[i]), np.sin(yaw_l[i])
        Rm = np.array([[c, s], [-s, c]])
        rel[i] = Rm @ (P2[i + 1] - P2[i]) * ratio[i]

    x0 = np.concatenate([P_route.ravel(), yaw_route_u])

    def residuals(x):
        P = x[:2 * N].reshape(N, 2)
        Y = x[2 * N:]
        res = []
        c, s = np.cos(Y[:-1]), np.sin(Y[:-1])
        dx = P[1:] - P[:-1]
        pred = np.stack([c * rel[:, 0] - s * rel[:, 1],
                         s * rel[:, 0] + c * rel[:, 1]], 1)
        res.append((W_REL_POS * (dx - pred)).ravel())
        res.append(W_REL_YAW * ((Y[1:] - Y[:-1]) - d_yaw))
        res.append((W_ROUTE * (P - P_route)).ravel())
        res.append(W_YAW * (Y - yaw_route_u))
        return np.concatenate(res)

    # sparse jacobian structure: residual blocks touch only neighboring frames
    from scipy.sparse import lil_matrix
    n_res = 2 * (N - 1) + (N - 1) + 2 * N + N
    S = lil_matrix((n_res, 3 * N), dtype=np.int8)
    r = 0
    for i in range(N - 1):                       # rel-pos rows: frames i, i+1, yaw i
        for c in (2*i, 2*i+1, 2*(i+1), 2*(i+1)+1, 2*N+i):
            S[r, c] = S[r+1, c] = 1
        r += 2
    for i in range(N - 1):                       # rel-yaw rows
        S[r, 2*N+i] = S[r, 2*N+i+1] = 1
        r += 1
    for i in range(N):                           # route unary
        S[r, 2*i] = 1; S[r+1, 2*i+1] = 1
        r += 2
    for i in range(N):                           # yaw unary
        S[r, 2*N+i] = 1
        r += 1

    print("solving pose graph (sparse)...")
    sol = least_squares(residuals, x0, method="trf", jac_sparsity=S.tocsr(),
                        max_nfev=60, verbose=1)
    P = sol.x[:2 * N].reshape(N, 2)
    Y = sol.x[2 * N:]

    # diagnostics
    move = np.linalg.norm(P - P_route, axis=1)
    dyaw = np.degrees(np.abs(Y - yaw_route_u))
    print(f"deviation from route: p50={np.percentile(move,50):.2f} p90={np.percentile(move,90):.2f} max={move.max():.2f} m")
    print(f"yaw change vs snap:   p50={np.percentile(dyaw,50):.2f} p90={np.percentile(dyaw,90):.2f} max={dyaw.max():.2f} deg")
    steps = np.linalg.norm(np.diff(P, axis=0), axis=1)
    nz = steps[steps > 1e-6]
    print(f"spacing p90/p10: {np.percentile(nz,90)/max(np.percentile(nz,10),1e-9):.1f}x")

    # rebuild c2w: rotate each snapped pose about world z by (Y - yaw_route)
    out = c2w_snap.copy()
    dpsi = Y - yaw_route_u
    for i in range(N):
        cz, sz = np.cos(dpsi[i]), np.sin(dpsi[i])
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        out[i, :3, :3] = Rz @ c2w_snap[i, :3, :3]
        out[i, 0, 3] = P[i, 0]
        out[i, 1, 3] = P[i, 1]
    np.savez(out_npz, c2w=out, intrinsic=d["intrinsic"],
             m_per_px=d["m_per_px"], m_per_recon_unit=d["m_per_recon_unit"],
             names=d["names"])
    print("wrote", out_npz)

if __name__ == "__main__":
    main(*sys.argv[1:4])
