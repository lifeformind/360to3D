#!/usr/bin/env python3
"""Snap the LingBot trajectory onto the traced satellite route.

The LingBot trajectory is locally accurate but accumulates low-frequency yaw
drift over the corridor (no loop closures to correct it). The traced route is
the trusted global shape. Per frame:
  position   <- route point at the frame's normalized arc-length fraction
               (recon arc length <-> route arc length, both speed-independent)
  yaw        <- corrected by delta(s) = route tangent bearing - smoothed recon
               heading bearing, applied about the ground-plane normal
  pitch/roll <- kept from LingBot (local detail, trustworthy)
Height is flattened to the route plane (out-of-plane ratio was 0.016).

Outputs corrected c2w poses (world: map-plane meters, x=east/px-x, y=px-y,
z=up) as poses_snapped.npz, plus a diagnostics plot.

Usage: 09_snap_to_route.py <npz_dir> <route_json> <m_per_px> <out_dir>
"""
import json, os, sys, glob
import numpy as np
from scipy.ndimage import gaussian_filter1d

def main(npz_dir, route_json, m_per_px, out_dir):
    m_per_px = float(m_per_px)
    files = sorted(glob.glob(os.path.join(npz_dir, "frame_*.npz")))
    C, Rw2c = [], []
    for f in files:
        E = np.load(f)["extrinsic"]
        R, t = E[:, :3], E[:, 3]
        C.append(-R.T @ t); Rw2c.append(R)
    C = np.array(C); Rw2c = np.array(Rw2c)
    N = len(C)

    # recon ground plane basis (b1,b2 in-plane, n up-ish)
    mu = C.mean(0)
    _, _, Vt = np.linalg.svd(C - mu, full_matrices=False)
    b1, b2, n = Vt[0], Vt[1], Vt[2]
    # make n point "up": camera y-axis in w2c is down-ish; world up ≈ -mean cam y
    up_hint = -Rw2c[:, 1, :].mean(0)
    if n @ up_hint < 0:
        n = -n; b2 = -b2                      # keep right-handed (b1,b2,n)
    A_basis = np.stack([b1, b2, n], 1)        # plane -> recon-world
    P2 = np.stack([(C - mu) @ b1, (C - mu) @ b2], 1)

    # smoothed recon heading along arc
    seg = np.linalg.norm(np.diff(P2, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)]); s_norm = s / s[-1]
    Psm = gaussian_filter1d(P2, sigma=8, axis=0, mode="nearest")
    dP = np.gradient(Psm, axis=0)
    recon_bearing = np.arctan2(dP[:, 1], dP[:, 0])

    # route, in map px; y flipped so +y = north/up for a right-handed ground frame
    route = json.load(open(route_json))
    Rpts = np.array(route["points_px"]) * np.array([1.0, -1.0])
    rseg = np.linalg.norm(np.diff(Rpts, axis=0), axis=1)
    rs = np.concatenate([[0], np.cumsum(rseg)])

    # refine the recon->route arc mapping with curvature-profile DTW so bends
    # align with bends (proportional mapping misplaces turns -> yaw spikes)
    def resample(P, cum, M):
        u = np.linspace(0, cum[-1], M)
        return np.stack([np.interp(u, cum, P[:, 0]), np.interp(u, cum, P[:, 1])], 1)

    def curvature(P):
        d = np.gradient(gaussian_filter1d(P, 5, axis=0, mode="nearest"), axis=0)
        dd = np.gradient(d, axis=0)
        num = d[:, 0] * dd[:, 1] - d[:, 1] * dd[:, 0]
        den = (d[:, 0] ** 2 + d[:, 1] ** 2) ** 1.5 + 1e-12
        return num / den

    M = 600
    Pa, Pb = resample(P2, s, M), resample(Rpts, rs, M)
    ka = curvature(Pa) * (s[-1] / M)          # curvature per resample step
    kb = curvature(Pb) * (rs[-1] / M)
    # reflection handedness between plane basis and map frame is unknown;
    # pick the sign giving the better DTW cost
    def dtw_map(ka, kb, band=0.15):
        W = int(band * M)
        INF = 1e18
        D = np.full((M, M), INF)
        cost = np.abs(ka[:, None] - kb[None, :])
        D[0, 0] = cost[0, 0]
        for i in range(1, M):
            j0, j1 = max(0, i - W), min(M, i + W)
            for j in range(j0, j1):
                best = min(D[i-1, j], D[i-1, j-1] if j else INF, D[i, j-1] if j else INF)
                D[i, j] = cost[i, j] + best
        # backtrack
        i, j = M - 1, M - 1
        path = [(i, j)]
        while i or j:
            opts = []
            if i and j: opts.append((D[i-1, j-1], i-1, j-1))
            if i: opts.append((D[i-1, j], i-1, j))
            if j: opts.append((D[i, j-1], i, j-1))
            _, i, j = min(opts)
            path.append((i, j))
        path.reverse()
        return D[M-1, M-1], np.array(path)

    # handedness comes from the camera's gravity direction (up_hint), never
    # from DTW cost — curvature profiles can near-tie on drifted trajectories
    cost, path = dtw_map(ka, kb)
    print(f"curvature DTW (direct handedness): cost {cost:.1f}")
    # monotone mapping recon-fraction -> route-fraction (average j per i)
    ii, jj = path[:, 0], path[:, 1]
    jmap = np.array([jj[ii == k].mean() for k in range(M)])
    jmap = np.maximum.accumulate(jmap)
    s_route = np.interp(s_norm, np.linspace(0, 1, M), jmap / (M - 1))
    target = np.stack([np.interp(s_route, rs / rs[-1], Rpts[:, 0]),
                       np.interp(s_route, rs / rs[-1], Rpts[:, 1])], 1)
    Rsm = gaussian_filter1d(target, sigma=8, axis=0, mode="nearest")
    dR = np.gradient(Rsm, axis=0)
    route_bearing = np.arctan2(dR[:, 1], dR[:, 0])

    # per-frame yaw correction for ORIENTATIONS. LingBot's rotation and
    # translation heads drift at different rates (measured: camera forward
    # rotates ~135 deg over the sequence while the path direction rotates
    # ~360+), so the correction must target the camera's own forward bearing,
    # not the trajectory bearing. The camera faces the direction of travel
    # (hood view), so route tangent = target forward.
    fwd_plane = np.array([(A_basis.T @ Rw2c[i].T)[:, 2] for i in range(N)])
    fwd_bearing = np.unwrap(np.arctan2(fwd_plane[:, 1], fwd_plane[:, 0]))
    delta = np.unwrap(route_bearing) - fwd_bearing
    delta_s = gaussian_filter1d(delta, sigma=12, mode="nearest")
    step_change = np.degrees(np.abs(np.diff(delta_s)))
    print(f"yaw correction: range {np.degrees(delta_s.min()):.0f}..{np.degrees(delta_s.max()):.0f} deg, "
          f"per-frame change p50={np.percentile(step_change,50):.2f} p95={np.percentile(step_change,95):.2f} max={step_change.max():.1f} deg")

    # build corrected c2w: world = (east, north, up) in meters
    poses_c2w = np.zeros((N, 4, 4)); poses_c2w[:, 3, 3] = 1
    for i in range(N):
        Rc2w_recon = Rw2c[i].T
        cosd, sind = np.cos(delta_s[i]), np.sin(delta_s[i])
        Rot_plane = np.array([[cosd, -sind, 0], [sind, cosd, 0], [0, 0, 1]])
        # rotation expressed in plane coords, yaw-corrected, then to ENU world
        M = Rot_plane @ A_basis.T @ Rc2w_recon
        poses_c2w[i, :3, :3] = M
        poses_c2w[i, :3, 3] = [target[i, 0] * m_per_px, target[i, 1] * m_per_px, 0.0]
    # constant camera height above ground (mast on hull), settable later in Unity
    poses_c2w[:, 2, 3] = 3.0

    # self-check: corrected camera forward should track the route tangent
    fwd = poses_c2w[:, :3, 2]
    pos2 = poses_c2w[:, :2, 3]
    tang = np.gradient(gaussian_filter1d(pos2, 5, axis=0, mode="nearest"), axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
    f2 = fwd[:, :2] / (np.linalg.norm(fwd[:, :2], axis=1, keepdims=True) + 1e-9)
    ang = np.degrees(np.arccos(np.clip((f2 * tang).sum(1), -1, 1)))
    downz = poses_c2w[:, 2, 1].mean()
    print(f"SELF-CHECK forward-vs-tangent: p50={np.percentile(ang,50):.1f} p90={np.percentile(ang,90):.1f} deg "
          f"(want ~0-15); camera-down z-component {downz:.2f} (want ~-1)")
    if np.percentile(ang, 50) > 30 or downz > -0.5:
        raise SystemExit("SELF-CHECK FAILED: orientation frame is wrong — do not train on this")

    intr = np.load(files[0])["intrinsic"]
    os.makedirs(out_dir, exist_ok=True)
    # depth values from the recon are in recon units; convert via matched arc lengths
    m_per_recon_unit = (rs[-1] * m_per_px) / s[-1]
    print(f"scale: {m_per_recon_unit:.3f} m per recon unit (route {rs[-1]*m_per_px:.0f} m / recon arc {s[-1]:.1f})")
    np.savez(os.path.join(out_dir, "poses_snapped.npz"),
             c2w=poses_c2w, intrinsic=intr, m_per_px=m_per_px,
             m_per_recon_unit=m_per_recon_unit,
             names=[os.path.basename(f).replace('frame_', '').replace('.npz', '') for f in files])
    print(f"wrote {N} snapped poses -> {out_dir}/poses_snapped.npz")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    axes[0].plot(s_norm, np.degrees(delta), alpha=.4, label="raw")
    axes[0].plot(s_norm, np.degrees(delta_s), lw=2, label="smoothed (applied)")
    axes[0].set_xlabel("route fraction"); axes[0].set_ylabel("yaw correction (deg)")
    axes[0].legend(); axes[0].grid(alpha=.3); axes[0].set_title("yaw drift correction profile")
    axes[1].scatter(target[:, 0], target[:, 1], c=np.linspace(0, 1, N), cmap="coolwarm", s=4)
    axes[1].set_aspect("equal"); axes[1].grid(alpha=.3)
    axes[1].set_title("snapped positions (map frame)")
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "snap_diagnostics.png"), dpi=90)
    print("diagnostics:", os.path.join(out_dir, "snap_diagnostics.png"))

if __name__ == "__main__":
    main(*sys.argv[1:5])
