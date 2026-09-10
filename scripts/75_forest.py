"""Stage 75: deterministic layered rainforest placements from the canopy raster."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260910
BAND = (4.0, 40.0)
EXCLUDE = 5.5
CHUNK = 20.0
CELL = 2.0          # structure-pass cell (m)
GROUND_CELL = 1.5   # ground-cover pass cell, band 4-12 m
WALL_STEP = 3.0     # creeper spacing along the canopy edge


def layer_of(h):
    if h >= 12: return "canopy"
    if h >= 6: return "mid"
    if h >= 1.5: return "under"
    return "ground"


def cover_prob(h):
    return float(np.clip(h / 20.0, 0.15, 0.9))


def stable_hash_3(a, b, c):
    """Stable integer mix for 3-component hash (replaces builtin hash)."""
    s = f"{a}:{b}:{c}".encode()
    return int(hashlib.md5(s).hexdigest(), 16)


def stable_hash_2(a, b):
    """Stable integer mix for 2-component hash (replaces builtin hash)."""
    s = f"{a}:{b}".encode()
    return int(hashlib.md5(s).hexdigest(), 16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s0", type=float, default=439.0)
    ap.add_argument("--s1", type=float, default=664.0)
    a = ap.parse_args()

    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"]
           if not st["provisional"] and a.s0 <= st["s"] <= a.s1]
    can = rasterio.open(ROOT / "work" / "canopy_enu.tif")

    def canopy(px, py):
        return float(next(can.sample([(px, py)]))[0])

    chunks = {}
    def add(s, plant):
        s0 = a.s0 + int((s - a.s0) // CHUNK) * CHUNK
        chunks.setdefault(round(s0, 1), []).append(plant)

    for st in sts:
        s = st["s"]
        nx, ny = -st["ty"], st["tx"]
        for sgn in (1.0, -1.0):
            # structure pass: 2 m cells across the band, per 2 m of track (skip odd stations)
            if int(round(s)) % int(CELL) == 0:
                for lat in np.arange(BAND[0], BAND[1], CELL):
                    rng = np.random.default_rng(
                        SEED + stable_hash_3(int(round(s)), int(sgn), int(lat * 10)) % (2**31))
                    px = st["x"] + sgn * lat * nx
                    py = st["y"] + sgn * lat * ny
                    h = canopy(px, py)
                    if h < 0.3 or rng.random() > cover_prob(h):
                        continue
                    jx, jy = rng.uniform(-0.9, 0.9, 2)
                    plat = lat + jx
                    if plat < EXCLUDE + 0.5:
                        continue
                    h_rounded = round(max(h, 0.4), 1)
                    add(s, dict(layer=layer_of(h_rounded),
                                x=round(px + jx * nx * sgn + jy * st["tx"], 2),
                                y=round(py + jx * ny * sgn + jy * st["ty"], 2),
                                h=h_rounded,
                                yaw=round(float(rng.uniform(0, 360)), 1),
                                scale=round(float(rng.uniform(0.85, 1.25)), 2)))
            # ground-cover pass: 1.5 m cells, band 4-12 m, per 1.5 m of track
            if int(round(s / GROUND_CELL)) != int(round((s - 1) / GROUND_CELL)):
                for lat in np.arange(BAND[0], 12.0, GROUND_CELL):
                    rng = np.random.default_rng(
                        SEED + 7 + stable_hash_3(int(round(s * 2)), int(sgn), int(lat * 10)) % (2**31))
                    if rng.random() > 0.5:
                        continue
                    jx, jy = rng.uniform(-0.6, 0.6, 2)
                    if lat + jx < EXCLUDE + 0.3:
                        continue
                    px = st["x"] + sgn * (lat + jx) * nx + jy * st["tx"]
                    py = st["y"] + sgn * (lat + jx) * ny + jy * st["ty"]
                    h_ground = round(max(canopy(px, py), 0.4), 1)
                    add(s, dict(layer="ground", x=round(px, 2), y=round(py, 2),
                                h=h_ground,
                                yaw=round(float(rng.uniform(0, 360)), 1),
                                scale=round(float(rng.uniform(0.8, 1.3)), 2)))
        # wall creepers: canopy edge per side, every WALL_STEP
        if int(round(s)) % int(WALL_STEP) == 0:
            for sgn in (1.0, -1.0):
                rng = np.random.default_rng(
                    SEED + 13 + stable_hash_2(int(round(s)), int(sgn)) % (2**31))
                for lat in np.arange(BAND[0], 15.0, 0.5):
                    px = st["x"] + sgn * lat * nx
                    py = st["y"] + sgn * lat * ny
                    if canopy(px, py) >= 3.0:
                        if lat >= EXCLUDE + 0.3:
                            add(s, dict(layer="wall", x=round(px, 2), y=round(py, 2),
                                        h=round(canopy(px, py), 1),
                                        yaw=round(float(rng.uniform(0, 360)), 1),
                                        scale=round(float(rng.uniform(0.9, 1.2)), 2)))
                        break

    out = dict(seed=SEED, s_range=[a.s0, a.s1],
               chunks=[dict(s0=k, plants=v) for k, v in sorted(chunks.items())])
    (ROOT / "export" / "forest_placements.json").write_text(json.dumps(out))
    n = sum(len(c["plants"]) for c in out["chunks"])
    per = {}
    for c in out["chunks"]:
        for p in c["plants"]:
            per[p["layer"]] = per.get(p["layer"], 0) + 1
    print(f"{n} plants in {len(out['chunks'])} chunks: {per}")


if __name__ == "__main__":
    main()
