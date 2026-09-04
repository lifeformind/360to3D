import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def meta():
    subprocess.run([PY, str(ROOT / "scripts" / "62_terrain.py")], check=True)
    return json.loads((ROOT / "export" / "terrain_meta.json").read_text())


@pytest.fixture(scope="module")
def heights(meta):
    raw = np.fromfile(ROOT / "export" / "terrain.raw", dtype="<u2")
    h = raw.reshape(meta["resolution"], meta["resolution"]).astype(np.float64)
    return h / 65535.0 * meta["height_range"] + meta["height_min"]


def test_meta_and_shape(meta):
    assert meta["resolution"] == 2049
    assert (meta["size_x"], meta["size_z"]) == (1312.0, 672.0)
    assert meta["height_range"] > 10


def sample(heights, meta, x, y):
    col = (x - meta["origin_enu_x"]) / meta["size_x"] * (meta["resolution"] - 1)
    row = (y - meta["origin_enu_y"]) / meta["size_z"] * (meta["resolution"] - 1)
    return heights[int(round(row)), int(round(col))]


def test_terrain_blended_to_road(heights, meta):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    errs = [sample(heights, meta, st["x"], st["y"]) - (st["z"] - 0.15)
            for st in cl["stations"][::25]]
    assert np.abs(np.array(errs)).max() < 0.35  # heightmap px ~0.64 m -> small interp error


def test_far_terrain_matches_dtm(heights, meta):
    import rasterio
    with rasterio.open(ROOT / "work" / "dtm_enu.tif") as ds:
        dtm = ds.read(1)
    # NE-area probe point >14 m from any station: compare within 1 m
    x, y = 1100.0, 300.0
    row = int((meta["origin_enu_y"] + meta["size_z"] - y) / 0.5)  # dtm row 0 = north
    col = int((x - meta["origin_enu_x"]) / 0.5)
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    d = min(np.hypot(st["x"] - x, st["y"] - y) for st in cl["stations"])
    assert d > 14
    assert abs(sample(heights, meta, x, y) - (dtm[row, col] - meta["z0"])) < 1.0
