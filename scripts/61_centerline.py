"""Stage 61: smoothed 1 m-station centreline from GPX + DTM, with provisional loop connector."""
import json
from pathlib import Path

import numpy as np
import rasterio
from scipy.interpolate import splev, splprep
from scipy.signal import savgol_filter

ROOT = Path(__file__).resolve().parents[1]
STEP = 1.0
WIDTH = 10.0


def load_track():
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    xy = np.stack([d["x"], d["y"]], axis=1)
    # Collapse parked stretches: drop fixes < 1 m from their predecessor.
    keep = [0]
    for i in range(1, len(xy)):
        if np.linalg.norm(xy[i] - xy[keep[-1]]) >= 1.0:
            keep.append(i)
    return xy[keep]


def smooth_resample(xy):
    # Arc-length parameterised smoothing spline; s tuned for ~1 Hz GPS jitter (~2-3 m).
    dist = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
    tck, _ = splprep([xy[:, 0], xy[:, 1]], u=dist, s=len(xy) * 2.0)
    dense_u = np.linspace(0, dist[-1], int(dist[-1] * 10))
    dx, dy = splev(dense_u, tck)
    dense = np.stack([dx, dy], axis=1)
    seg = np.linalg.norm(np.diff(dense, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s_out = np.arange(0, arc[-1], STEP)
    return np.stack([np.interp(s_out, arc, dense[:, 0]),
                     np.interp(s_out, arc, dense[:, 1])], axis=1)


def hermite_connector(p_end, t_end, p_start, t_start):
    """Cubic Hermite p_end->p_start honouring both tangents; resampled to 1 m."""
    chord = np.linalg.norm(p_start - p_end)
    m0, m1 = t_end * chord, t_start * chord
    u = np.linspace(0, 1, 400)[1:]  # exclude p_end (already a station)
    h00, h10 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u
    h01, h11 = -2 * u**3 + 3 * u**2, u**3 - u**2
    pts = (h00[:, None] * p_end + h10[:, None] * m0
           + h01[:, None] * p_start + h11[:, None] * m1)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s_out = np.arange(STEP, arc[-1], STEP)
    return np.stack([np.interp(s_out, arc, pts[:, 0]),
                     np.interp(s_out, arc, pts[:, 1])], axis=1)


def main():
    loop = smooth_resample(load_track())
    tangents = np.gradient(loop, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)
    conn = hermite_connector(loop[-1], tangents[-1], loop[0], tangents[0])

    # Filter connector to avoid near-coincident stations (< 0.5 m apart)
    kept_conn = []
    last_pt = loop[-1]  # Start from loop end
    for pt in conn:
        if np.linalg.norm(pt - last_pt) >= 0.5:
            kept_conn.append(pt)
            last_pt = pt

    # Drop trailing connector points within 0.5 m of loop[0]
    while kept_conn and np.linalg.norm(kept_conn[-1] - loop[0]) < 0.5:
        kept_conn.pop()

    conn = np.array(kept_conn) if kept_conn else np.empty((0, 2))
    xy = np.vstack([loop, conn])
    n_loop = len(loop)

    with rasterio.open(ROOT / "work" / "dtm_enu.tif") as ds:
        z_abs = np.array([v[0] for v in ds.sample(xy)], dtype=np.float64)
    z_abs = savgol_filter(z_abs, window_length=31, polyorder=2)
    z0 = float(z_abs[0])
    z = z_abs - z0

    tan = np.gradient(xy, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])

    stations = [dict(s=round(float(s[i]), 3), x=round(float(xy[i, 0]), 3),
                     y=round(float(xy[i, 1]), 3), z=round(float(z[i]), 3),
                     tx=round(float(tan[i, 0]), 5), ty=round(float(tan[i, 1]), 5),
                     w=WIDTH, provisional=i >= n_loop)
                for i in range(len(xy))]
    out = ROOT / "work" / "centerline.json"
    out.write_text(json.dumps(dict(z0=z0, px_per_m=1.0, stations=stations)))
    print(f"wrote {out}: {len(stations)} stations, {s[-1]:.0f} m "
          f"({len(stations) - n_loop} provisional), z0={z0:.2f}")


if __name__ == "__main__":
    main()
