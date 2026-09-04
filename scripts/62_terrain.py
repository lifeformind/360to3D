"""Stage 62: DTM -> Unity Terrain RAW, terrain blended to road profile under the corridor."""
import json
from pathlib import Path

import numpy as np
import rasterio
from scipy.spatial import cKDTree

import geo

ROOT = Path(__file__).resolve().parents[1]
RES = 2049
BLEND_IN, BLEND_OUT = 7.0, 14.0
ROAD_DROP = 0.15


def main():
    g = geo.GRID
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    z0 = cl["z0"]
    st_xy = np.array([[st["x"], st["y"]] for st in cl["stations"]])
    st_z = np.array([st["z"] for st in cl["stations"]])

    with rasterio.open(ROOT / "work" / "dtm_enu.tif") as ds:
        dtm = ds.read(1).astype(np.float64) - z0  # row 0 = north

    # Heightmap sample grid (row 0 = south for Unity).
    xs = np.linspace(g["xmin"], g["xmax"], RES)
    ys = np.linspace(g["ymin"], g["ymax"], RES)
    X, Y = np.meshgrid(xs, ys)
    cols = np.clip((X - g["xmin"]) / g["px"], 0, g["width"] - 1).astype(int)
    rows = np.clip((g["ymax"] - Y) / g["px"], 0, g["height"] - 1).astype(int)
    h = dtm[rows, cols]

    dist, idx = cKDTree(st_xy).query(np.stack([X.ravel(), Y.ravel()], axis=1),
                                     distance_upper_bound=BLEND_OUT)
    dist, idx = dist.reshape(X.shape), idx.reshape(X.shape)
    near = np.isfinite(dist)
    road_h = np.where(near, st_z[np.clip(idx, 0, len(st_z) - 1)] - ROAD_DROP, 0.0)
    t = np.clip((dist - BLEND_IN) / (BLEND_OUT - BLEND_IN), 0.0, 1.0)
    w = np.where(near, 1.0 - t * t * (3 - 2 * t), 0.0)  # smoothstep: 1 inside, 0 outside
    h = w * road_h + (1.0 - w) * h

    hmin, hmax = float(h.min()), float(h.max())
    hrange = hmax - hmin
    (ROOT / "export").mkdir(exist_ok=True)
    ((h - hmin) / hrange * 65535).astype("<u2").tofile(ROOT / "export" / "terrain.raw")
    meta = dict(resolution=RES, size_x=g["xmax"] - g["xmin"], size_z=g["ymax"] - g["ymin"],
                height_min=hmin, height_range=hrange,
                origin_enu_x=g["xmin"], origin_enu_y=g["ymin"], z0=z0)
    (ROOT / "export" / "terrain_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"terrain.raw {RES}x{RES}, heights {hmin:.2f}..{hmax:.2f} (rel z0={z0:.2f})")


if __name__ == "__main__":
    main()
