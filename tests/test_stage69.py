import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def obj():
    subprocess.run([PY, str(ROOT / "scripts" / "69_road_uv.py")], check=True)
    verts, uvs, objects = [], [], []
    for line in (ROOT / "export" / "road_overlay.obj").read_text().splitlines():
        p = line.split()
        if p and p[0] == "v":
            verts.append([float(x) for x in p[1:4]])
        elif p and p[0] == "vt":
            uvs.append([float(x) for x in p[1:3]])
        elif p and p[0] == "o":
            objects.append(p[1])
    return np.array(verts), np.array(uvs), objects


def test_objects_and_span(obj):
    verts, uvs, objects = obj
    assert objects == ["overlay_tile_02", "overlay_tile_03"]
    assert len(verts) > 2000


def test_uvs_in_range(obj):
    _, uvs, _ = obj
    assert uvs[:, 0].min() >= -0.001 and uvs[:, 0].max() <= 1.001
    assert uvs[:, 1].min() >= 116 / 512 - 0.001 and uvs[:, 1].max() <= 396 / 512 + 0.001


def test_overlay_above_road(obj):
    verts, _, _ = obj
    # centre-line vertices sit ~0.02 above station z; sanity: y within plausible band
    assert -10 < verts[:, 1].min() and verts[:, 1].max() < 25
