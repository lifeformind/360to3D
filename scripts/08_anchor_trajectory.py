#!/usr/bin/env python3
"""Anchor the LingBot-Map trajectory to the traced satellite route.

Loads per-frame extrinsics (w2c, OpenCV) from the LingBot NPZ directory,
projects camera centers onto their principal (ground) plane, matches them to
the route polyline by normalized arc length, fits a 2D similarity transform
(Procrustes), and reports the trajectory-quality gates:
  - consecutive-frame spacing p90/p10 (scale consistency)
  - RMS distance to route after alignment (shape agreement)
Writes an overlay PNG on the satellite map and the aligned transform JSON.

Usage: 08_anchor_trajectory.py <npz_dir> <route_json> <map_png> <out_prefix>
"""
import json, os, sys, glob
import numpy as np

def load_centers(npz_dir):
    files = sorted(glob.glob(os.path.join(npz_dir, "frame_*.npz")))
    C = []
    for f in files:
        d = np.load(f)
        E = d["extrinsic"]                    # (3,4) w2c
        R, t = E[:, :3], E[:, 3]
        C.append(-R.T @ t)
    return np.array(C), files

def arclen(P):
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    return np.concatenate([[0], np.cumsum(seg)])

def main(npz_dir, route_json, map_png, out_prefix):
    C3, files = load_centers(npz_dir)
    print(f"{len(C3)} camera centers")

    # spacing gate on raw 3D trajectory
    steps = np.linalg.norm(np.diff(C3, axis=0), axis=1)
    nz = steps[steps > 1e-9]
    p10, p50, p90 = np.percentile(nz, [10, 50, 90])
    print(f"spacing: p10={p10:.4f} p50={p50:.4f} p90={p90:.4f}  p90/p10={p90/max(p10,1e-12):.1f}x")

    # principal plane projection (driving trajectory ≈ planar)
    mu = C3.mean(0)
    U, S, Vt = np.linalg.svd(C3 - mu, full_matrices=False)
    P2 = (C3 - mu) @ Vt[:2].T                 # N x 2 in plane coords
    planarity = S[2] / max(S[1], 1e-12)
    print(f"plane singular values {S.round(1)}, out-of-plane ratio {planarity:.3f}")

    route = json.load(open(route_json))
    R2 = np.array(route["points_px"])
    # correspondence by normalized arc length
    sa, sb = arclen(P2), arclen(R2)
    sa /= sa[-1]; sb /= sb[-1]
    Rm = np.stack([np.interp(sa, sb, R2[:, 0]), np.interp(sa, sb, R2[:, 1])], 1)

    # 2D similarity Procrustes (allow reflection: plane basis has arbitrary handedness)
    ma, mb = P2.mean(0), Rm.mean(0)
    A, B = P2 - ma, Rm - mb
    H = A.T @ B
    Uh, Sh, Vh = np.linalg.svd(H)
    D = np.eye(2); D[1, 1] = np.sign(np.linalg.det(Vh.T @ Uh.T))
    Rot = Vh.T @ D @ Uh.T
    scale = (Sh * np.diag(D)).sum() / (A ** 2).sum()
    T2 = (scale * (Rot @ A.T)).T + mb
    rms = float(np.sqrt(((T2 - Rm) ** 2).sum(1).mean()))
    print(f"similarity fit: scale={scale:.4f} px/unit, RMS to route = {rms:.1f} px "
          f"(route length {arclen(R2)[-1]:.0f} px)")

    out = {"npz_dir": npz_dir, "n_frames": len(C3),
           "plane_origin": mu.tolist(), "plane_basis": Vt[:2].tolist(),
           "rot2d": Rot.tolist(), "scale_px_per_unit": float(scale),
           "trans_px": (mb - scale * Rot @ ma).tolist(),
           "spacing_p90_p10": float(p90 / max(p10, 1e-12)),
           "rms_px": rms}
    with open(out_prefix + "_anchor.json", "w") as f:
        json.dump(out, f, indent=1)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    im = np.array(Image.open(map_png).convert("RGB"))
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(im)
    ax.plot(R2[:, 0], R2[:, 1], "-", color="yellow", lw=2, alpha=0.8, label="traced route")
    sc = ax.scatter(T2[:, 0], T2[:, 1], c=np.linspace(0, 1, len(T2)), cmap="coolwarm", s=5,
                    label="LingBot trajectory (aligned)")
    ax.plot(*T2[0], "g^", ms=14); ax.plot(*T2[-1], "rs", ms=11)
    ax.legend(loc="lower right"); ax.axis("off")
    ax.set_title(f"LingBot trajectory on map — spacing p90/p10 {p90/max(p10,1e-12):.1f}x, RMS {rms:.0f}px")
    plt.tight_layout(); plt.savefig(out_prefix + "_overlay.png", dpi=90)
    print("overlay:", out_prefix + "_overlay.png")

if __name__ == "__main__":
    main(*sys.argv[1:5])
