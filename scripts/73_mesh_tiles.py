"""Stage 73: convert + clip photogrammetry tiles around the slice into Unity-import frame."""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pyproj
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "MESH OBJ"
CLIP_M = 7.5  # mesh-as-base experiment: clip only the road corridor (was 40.0 backdrop-only)
MARGIN = 250.0
S_RANGE = (439.0, 664.0)


def main():
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    z0 = cl["z0"]
    sts = [st for st in cl["stations"] if not st["provisional"]]
    tree = cKDTree([[st["x"], st["y"]] for st in sts])
    sl = [st for st in sts if S_RANGE[0] <= st["s"] <= S_RANGE[1]]
    xs = [st["x"] for st in sl]
    ys = [st["y"] for st in sl]

    to_svy = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3414", always_xy=True)
    to_wgs = pyproj.Transformer.from_crs("EPSG:3414", "EPSG:4326", always_xy=True)
    lat_a, lon_a = geo.enu_to_latlon(min(xs) - MARGIN, min(ys) - MARGIN)
    lat_b, lon_b = geo.enu_to_latlon(max(xs) + MARGIN, max(ys) + MARGIN)
    (sx_a, sy_a) = to_svy.transform(lon_a, lat_a)
    (sx_b, sy_b) = to_svy.transform(lon_b, lat_b)

    out = ROOT / "export" / "backdrop"
    out.mkdir(parents=True, exist_ok=True)
    n_done = 0
    for tx in range(int(sx_a // 200), int(sx_b // 200) + 1):
        for ty in range(int(sy_a // 200), int(sy_b // 200) + 1):
            tdir = SRC / f"Tile_+{tx:03d}_+{ty:03d}"
            if not tdir.exists():
                continue
            src_obj = next(tdir.glob("*.obj"))
            # two-pass: convert all verts + distances first, then filter faces
            txt = src_obj.read_text().splitlines()
            vs = [l for l in txt if l.startswith("v ")]

            # VECTORIZED: parse all verts into a numpy array for batch transform
            svy_verts = []
            for l in vs:
                p = l.split()
                svy_verts.append([float(p[1]), float(p[2]), float(p[3])])
            svy_verts = np.array(svy_verts)  # shape (n, 3)

            # Batch transform SVY21 -> WGS84 using pyproj
            sx_arr = svy_verts[:, 0]
            sy_arr = svy_verts[:, 1]
            sz_arr = svy_verts[:, 2]
            lon_arr, lat_arr = to_wgs.transform(sx_arr, sy_arr)

            # Batch convert WGS84 -> ENU using geo.py (vectorized via numpy)
            ex_arr, ey_arr = geo.latlon_to_enu(lat_arr, lon_arr)

            # Compute distances to centerline (for clipping)
            enu_pts = np.stack([ex_arr, ey_arr], axis=1)
            dist, _ = tree.query(enu_pts)

            # Generate Unity-import frame vertices (all at once)
            v_lines = []
            for i in range(len(svy_verts)):
                v_lines.append(f"v {-ex_arr[i]:.3f} {sz_arr[i] - z0:.3f} {ey_arr[i]:.3f}")

            # Filter: keep metadata + verts; filter faces by distance
            keep = []
            v_idx = 0
            for l in txt:
                if l.startswith("v "):
                    keep.append(v_lines[v_idx])
                    v_idx += 1
                elif l.startswith("f "):
                    idx = [int(t.split("/")[0]) - 1 for t in l.split()[1:]]
                    if min(dist[i] for i in idx) > CLIP_M:
                        keep.append(l)
                elif l.split() and l.split()[0] in ("vt", "vn", "mtllib", "usemtl", "o", "g"):
                    keep.append(l)

            (out / src_obj.name).write_text("\n".join(keep))
            shutil.copy2(tdir / (src_obj.stem + ".mtl"), out / (src_obj.stem + ".mtl"))
            for jpg in tdir.glob("*.jpg"):
                shutil.copy2(jpg, out / jpg.name)
            n_done += 1
    print(f"{n_done} backdrop tiles -> {out}")


if __name__ == "__main__":
    main()
