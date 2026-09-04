import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def objdata():
    subprocess.run([PY, str(ROOT / "scripts" / "63_road_mesh.py")], check=True)
    verts, faces, objects = [], [], set()
    for line in (ROOT / "export" / "road.obj").read_text().splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            verts.append([float(v) for v in p[1:4]])
        elif p[0] == "f":
            faces.append([int(tok.split("/")[0]) - 1 for tok in p[1:4]])
        elif p[0] == "o":
            objects.add(p[1])
    return np.array(verts), np.array(faces), objects


def test_structure(objdata):
    verts, faces, objects = objdata
    assert objects == {"road", "road_provisional"}
    assert len(verts) > 10000 and len(faces) > 20000


def test_no_degenerate_faces_and_up_normals(objdata):
    verts, faces, _ = objdata
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    n = np.cross(b - a, c - a)
    areas = np.linalg.norm(n, axis=1)
    assert areas.min() > 1e-6
    # OBJ frame has -x; flip back to Unity/world then check +y (up) normals
    n[:, 0] *= -1
    assert (n[:, 1] / areas > 0.5).all()


def test_width(objdata):
    verts, faces, _ = objdata
    # 7 verts per station in emission order; edge-to-edge (idx 1 to 5) = 10 m
    row0 = verts[0:7]
    assert abs(np.linalg.norm(row0[5] - row0[1]) - 10.0) < 0.05


def test_meta_start_pose():
    meta = json.loads((ROOT / "export" / "road_meta.json").read_text())
    assert abs(meta["start"]["y_unity"]) < 0.2      # z datum
    assert 45 < meta["start"]["heading_deg"] < 135  # east
    assert len(meta["stations_unity"]) > 500
