"""Stage 69: thin road-overlay mesh with mosaic-atlas UVs (sits 2 cm above the road)."""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LIFT = 0.02
CROWN = 0.02


def main():
    meta = json.loads((ROOT / "export" / "road_albedo" / "atlas_meta.json").read_text())
    span, half, lat_px, road_px = (meta["tile_span_m"], meta["lateral_half_m"],
                                   meta["lateral_px"], meta["road_px"])
    gutter = (lat_px - road_px) // 2
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    lats = np.array([-7.0, -5.0, -2.0, 0.0, 2.0, 5.0, 7.0])

    lines = []
    vbase = 1
    for k in meta["tiles"]:
        tsts = [st for st in sts if k * span <= st["s"] < (k + 1) * span]
        if len(tsts) < 2:
            continue
        lines.append(f"o overlay_tile_{k:02d}")
        nv = 0
        for st in tsts:
            nx, ny = -st["ty"], st["tx"]
            u = (st["s"] - k * span) / span
            for l in lats:
                ex = st["x"] + nx * l
                ey = st["y"] + ny * l
                ez = st["z"] + LIFT - CROWN * abs(l)
                v = (gutter + (l + half) / (2 * half) * road_px) / lat_px
                lines.append(f"v {-ex:.3f} {ez:.3f} {ey:.3f}")
                lines.append(f"vt {u:.5f} {v:.5f}")
                nv += 1
        npf = len(lats)
        rows = nv // npf
        for i in range(rows - 1):
            for j in range(npf - 1):
                a = vbase + i * npf + j
                b = a + 1
                c = vbase + (i + 1) * npf + j
                dd = c + 1
                lines.append(f"f {a}/{a} {c}/{c} {b}/{b}")
                lines.append(f"f {b}/{b} {c}/{c} {dd}/{dd}")
        vbase += nv
    (ROOT / "export" / "road_overlay.obj").write_text("\n".join(lines))
    print(f"road_overlay.obj: {vbase - 1} verts, tiles {meta['tiles']}")


if __name__ == "__main__":
    main()
