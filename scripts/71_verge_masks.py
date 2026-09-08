"""Stage 71: verge grass density from mosaic greenness, world-anchored 0.5 m grid."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
PX = 0.5
VERGE = (5.0, 7.0)


def main():
    meta = json.loads((ROOT / "export" / "road_albedo" / "atlas_meta.json").read_text())
    span, half, lat_px, road_px = (meta["tile_span_m"], meta["lateral_half_m"],
                                   meta["lateral_px"], meta["road_px"])
    gutter = (lat_px - road_px) // 2
    tiles = {k: np.asarray(Image.open(ROOT / "export" / "road_albedo" / f"tile_{k:02d}.png"))
             for k in meta["tiles"]}
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]
           and any(k * span <= st["s"] < (k + 1) * span for k in meta["tiles"])]
    S = np.array([st["s"] for st in sts])
    XY = np.array([[st["x"], st["y"]] for st in sts])
    N = np.array([[-st["ty"], st["tx"]] for st in sts])
    tree = cKDTree(XY)

    xmin, xmax = XY[:, 0].min() - 10, XY[:, 0].max() + 10
    ymin, ymax = XY[:, 1].min() - 10, XY[:, 1].max() + 10
    W, H = int((xmax - xmin) / PX), int((ymax - ymin) / PX)
    dens = np.zeros((H, W), np.uint8)
    gx, gy = np.meshgrid(xmin + (np.arange(W) + 0.5) * PX,
                         ymax - (np.arange(H) + 0.5) * PX)
    dist, idx = tree.query(np.stack([gx.ravel(), gy.ravel()], 1))
    rel = np.stack([gx.ravel(), gy.ravel()], 1) - XY[idx]
    latv = (rel * N[idx]).sum(axis=1)
    on_verge = (np.abs(latv) >= VERGE[0]) & (np.abs(latv) <= VERGE[1]) & (dist < 12)
    # note: road half-width is 5 m; verge band = 5..7 m from centreline
    for i in np.where(on_verge)[0]:
        s = S[idx[i]]
        k = int(s // span)
        if k not in tiles:
            continue
        u = int((s - k * span) / span * 4095)
        v = int(gutter + (latv[i] + half) / (2 * half) * road_px)
        px = tiles[k][np.clip(v, 0, lat_px - 1), u].astype(int)
        green = px[1] - (px[0] + px[2]) // 2
        r, c = divmod(i, W)
        dens[r, c] = np.clip(green * 6, 0, 255) if green > 4 else 0
    out = ROOT / "export" / "verge_masks"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(dens).save(out / "density.png")
    (out / "meta.json").write_text(json.dumps(dict(
        xmin=xmin, ymax=ymax, px_m=PX, width=W, height=H)))
    print(f"density {W}x{H}, verge cells {(dens > 0).sum()}")


if __name__ == "__main__":
    main()
