"""Stage 67: per-frame camera poses + one-off az0/h_cam calibration (world-locked equirect)."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
FPS = 10
DT = 2.0
D_BACK = 8.0


def build_track(v0, v1):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    S = np.array([st["s"] for st in sts])
    XY = np.array([[st["x"], st["y"]] for st in sts])
    Z = np.array([st["z"] for st in sts])
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    dx, dy = np.gradient(d["x"]), np.gradient(d["y"])
    tree = cKDTree(XY)
    frames = []
    for k in range(int(round((v1 - v0) * FPS)) + 1):
        v = v0 + k / FPS
        t = v + DT
        gx = np.interp(t, d["t"], d["x"]); gy = np.interp(t, d["t"], d["y"])
        _, i = tree.query([gx, gy])
        heading = float(np.degrees(np.arctan2(np.interp(t, d["t"], dx),
                                              np.interp(t, d["t"], dy))))
        frames.append(dict(v=round(v, 1), t=round(t, 1), s=float(S[i]),
                           x=float(XY[i, 0]), y=float(XY[i, 1]), z=float(Z[i]),
                           heading=round(heading, 2)))
    return frames


def sample_strip(img, cam, az0, sts_interp, s_strip, lat):
    """Project one 1 m strip of texels; returns [n_lat, n_s, 3] uint8."""
    px, py, pz, nx, ny = sts_interp(s_strip)
    Px = px[None, :] + lat[:, None] * nx[None, :]
    Py = py[None, :] + lat[:, None] * ny[None, :]
    Pz = pz[None, :] - 0.02 * np.abs(lat[:, None])
    dxx = Px - cam[0]; dyy = Py - cam[1]; dzz = Pz - cam[2]
    az = np.degrees(np.arctan2(dxx, dyy))
    el = np.degrees(np.arctan2(dzz, np.hypot(dxx, dyy)))
    H, W = img.shape[:2]
    ci = np.clip((((az - az0 + 180.0) % 360.0) / 360.0 * W).astype(int), 0, W - 1)
    ri = np.clip(((90.0 - el) / 180.0 * H).astype(int), 0, H - 1)
    return img[ri, ci]


def make_interp():
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    S = np.array([st["s"] for st in sts])
    X = np.array([st["x"] for st in sts]); Y = np.array([st["y"] for st in sts])
    Z = np.array([st["z"] for st in sts])
    TX = np.array([st["tx"] for st in sts]); TY = np.array([st["ty"] for st in sts])

    def f(s_vals):
        px = np.interp(s_vals, S, X); py = np.interp(s_vals, S, Y)
        pz = np.interp(s_vals, S, Z)
        tx = np.interp(s_vals, S, TX); ty = np.interp(s_vals, S, TY)
        return px, py, pz, -ty, tx  # position + left normal
    return f


def road_span(strip):
    """Detected (width_m, centre_m) from greenness; texel 0.1 m, lat -7..7."""
    g = strip[..., 1].astype(float) - (strip[..., 0].astype(float) + strip[..., 2]) / 2
    prof = g.mean(axis=1)
    thresh = prof.min() + 0.35 * (prof.max() - prof.min())
    mask = prof < thresh
    # longest contiguous True run
    best_a = best_b = a = None
    for i, m in enumerate(mask):
        if m and a is None: a = i
        if (not m or i == len(mask) - 1) and a is not None:
            b = i + (1 if m else 0)
            if best_a is None or b - a > best_b - best_a: best_a, best_b = a, b
            a = None
    if best_a is None or (best_b - best_a) * 0.1 < 3.0:
        return None
    return ((best_b - best_a) * 0.1, (best_a + best_b) / 2 * 0.1 - 7.0)


def calibrate(frames):
    picks = frames[:: max(1, len(frames) // 40)][:40]
    tmp = Path(tempfile.mkdtemp())
    try:
        imgs = []
        for f in picks:
            out = tmp / f"c{f['v']}.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(f["v"]),
                            "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"), "-frames:v", "1",
                            "-vf", "scale=1920:960", str(out)], check=True)
            imgs.append(np.asarray(Image.open(out)))
        interp = make_interp()
        lat = np.arange(-7.0, 7.0, 0.1) + 0.05
        best = (1e9, 108.0, 3.0)
        for az0 in np.arange(104, 113, 2.0):
            for h in (2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0):
                spans = []
                for f, img in zip(picks, imgs):
                    cam = np.array([f["x"], f["y"], f["z"] + h])
                    s_strip = np.arange(f["s"] - D_BACK - 0.5, f["s"] - D_BACK + 0.5, 0.1)
                    sp = road_span(sample_strip(img, cam, az0, interp, s_strip, lat))
                    if sp:
                        spans.append(sp)
                if len(spans) < 20:
                    continue
                widths = np.array([s[0] for s in spans])
                centres = np.array([s[1] for s in spans])
                score = abs(np.median(widths) - 10.0) + 0.05 * centres.std()
                if score < best[0]:
                    best = (score, float(az0), float(h))
        best_h = best[2]
        assert best_h not in (2.0, 4.0), f"h_cam optimum at grid edge ({best_h}) - calibration signal suspect"
        return best
    finally:
        shutil.rmtree(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v0", type=float, default=99.0)
    ap.add_argument("--v1", type=float, default=134.0)
    a = ap.parse_args()
    frames = build_track(a.v0, a.v1)
    score, az0, h = calibrate(frames)
    (ROOT / "work" / "camera_track.json").write_text(
        json.dumps(dict(v0=a.v0, v1=a.v1, fps=FPS, frames=frames)))
    (ROOT / "work" / "camera_calib.json").write_text(
        json.dumps(dict(mode="world", az0_deg=az0, h_cam_m=h, score=round(score, 3))))
    print(f"{len(frames)} poses; calib az0={az0} h_cam={h} (score {score:.3f})")


if __name__ == "__main__":
    main()
