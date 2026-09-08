import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def tiles():
    subprocess.run([PY, str(ROOT / "scripts" / "73_mesh_tiles.py")], check=True)
    return sorted((ROOT / "export" / "backdrop").glob("Tile_*.obj"))


def test_tiles_produced(tiles):
    # slice bbox +250 m margin spans 3x3..4x5 tiles of 200 m
    assert 9 <= len(tiles) <= 20


def test_clip_respected(tiles):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if 400 <= st["s"] <= 700]
    from scipy.spatial import cKDTree
    tree = cKDTree([[st["x"], st["y"]] for st in sts])
    verts, faces = [], []
    for line in tiles[0].read_text().splitlines():
        p = line.split()
        if p and p[0] == "v":
            verts.append([float(x) for x in p[1:4]])
        elif p and p[0] == "f":
            faces.append([int(t.split("/")[0]) - 1 for t in p[1:4]])
    verts = np.array(verts)
    used = np.unique(np.array(faces).ravel()) if faces else []
    if len(used):
        # Unity-import frame: ENU x = -vx, y_enu = vz
        enu = np.stack([-verts[used, 0], verts[used, 2]], 1)
        d, _ = tree.query(enu)
        near_slice = d[d < 250]
        if len(near_slice):
            assert near_slice.min() > 38.0
