"""Stage 63: crowned road ribbon OBJ from the centreline. Vertices pre-flipped for Unity import."""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def cross_section(hw):
    offs = np.array([-hw - 2, -hw, -hw / 2, 0, hw / 2, hw, hw + 2])
    dz = np.array([-0.02 * hw - 0.30, -0.02 * hw, -0.01 * hw, 0,
                   -0.01 * hw, -0.02 * hw, -0.02 * hw - 0.30])
    return offs, dz


def main():
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = cl["stations"]
    nprof = 7
    verts, uvs, rows_prov = [], [], []
    for st in sts:
        offs, dz = cross_section(st["w"] / 2)
        nx, ny = -st["ty"], st["tx"]  # left normal in ENU
        for o, d in zip(offs, dz):
            ex, ey, ez = st["x"] + nx * o, st["y"] + ny * o, st["z"] + d
            verts.append((-ex, ez, ey))  # Unity-import frame (importer negates x back)
            uvs.append((o / st["w"] + 0.5, st["s"] / 4.0))
        rows_prov.append(st["provisional"])

    def face_rows(i):  # quads between station i and i+1 -> 2 tris each, CCW from above in ENU
        f = []
        for j in range(nprof - 1):
            a, b = i * nprof + j, i * nprof + j + 1
            c, d = (i + 1) * nprof + j, (i + 1) * nprof + j + 1
            f += [(a, c, b), (b, c, d)]
        return f

    faces_road, faces_prov = [], []
    for i in range(len(sts) - 1):
        (faces_prov if rows_prov[i] or rows_prov[i + 1] else faces_road).extend(face_rows(i))

    with open(ROOT / "export" / "road.mtl", "w") as m:
        m.write("newmtl gravel\nKd 0.45 0.42 0.38\n\n"
                "newmtl gravel_provisional\nKd 0.65 0.35 0.35\n")
    with open(ROOT / "export" / "road.obj", "w") as f:
        f.write("mtllib road.mtl\n")
        for v in verts:
            f.write(f"v {v[0]:.3f} {v[1]:.3f} {v[2]:.3f}\n")
        for u in uvs:
            f.write(f"vt {u[0]:.4f} {u[1]:.4f}\n")
        for name, mtl, faces in (("road", "gravel", faces_road),
                                 ("road_provisional", "gravel_provisional", faces_prov)):
            f.write(f"o {name}\nusemtl {mtl}\n")
            for a, b, c in faces:
                f.write(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")

    st0 = sts[0]
    heading = math.degrees(math.atan2(st0["tx"], st0["ty"]))  # Unity yaw: 0=N(+z), 90=E(+x)
    meta = dict(z0=cl["z0"],
                start=dict(x_unity=st0["x"], y_unity=st0["z"], z_unity=st0["y"],
                           heading_deg=heading),
                stations_unity=[[st["x"], st["z"], st["y"]] for st in sts[::5]])
    (ROOT / "export" / "road_meta.json").write_text(json.dumps(meta))
    print(f"road.obj: {len(verts)} verts, {len(faces_road)} road + {len(faces_prov)} provisional tris")


if __name__ == "__main__":
    main()
