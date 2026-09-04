import importlib
import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")
# Module name starts with a digit, so it can't be a plain `import` -- use importlib.
# conftest.py already puts scripts/ on sys.path.
cl61 = importlib.import_module("61_centerline")


@pytest.fixture(scope="module")
def cl():
    subprocess.run([PY, str(ROOT / "scripts" / "61_centerline.py")], check=True)
    return json.loads((ROOT / "work" / "centerline.json").read_text())


def arr(cl, key):
    return np.array([st[key] for st in cl["stations"]])


def test_stationing_and_spacing(cl):
    s = arr(cl, "s")
    assert (np.diff(s) > 0).all()
    xy = np.stack([arr(cl, "x"), arr(cl, "y")], axis=1)
    steps = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    assert abs(steps.mean() - 1.0) < 0.05 and steps.max() < 1.5
    assert steps.min() > 0.4
    assert 2900 < s[-1] < 3400  # ~3.0 km + 184 m connector


def test_starts_east_runs_anticlockwise(cl):
    st0 = cl["stations"][0]
    assert st0["tx"] > abs(st0["ty"])  # heading within 45 deg of east
    x, y = arr(cl, "x"), arr(cl, "y")
    area2 = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    assert area2 > 0  # CCW in ENU


def test_loop_closes_with_provisional_connector(cl):
    prov = arr(cl, "provisional")
    assert prov.any() and not prov[0]
    assert prov[np.argmax(prov):].all()  # one contiguous tail
    assert 120 < prov.sum() < 260       # ~184 m of connector
    first, last = cl["stations"][0], cl["stations"][-1]
    assert np.hypot(first["x"] - last["x"], first["y"] - last["y"]) < 1.5

    # Check curvature over joint region (last 20 loop stations + connector): min radius >= 7.5 m
    prov_start = np.argmax(prov)
    joint_start = max(0, prov_start - 20)  # Last 20 recorded stations + connector
    xy = np.stack([arr(cl, "x"), arr(cl, "y")], axis=1)[joint_start:]
    r = cl61.circumradius(xy[:-2], xy[1:-1], xy[2:])
    i_bad = joint_start + int(np.argmin(r))
    assert r.min() > 7.5, f"Turning radius {r.min():.1f} m too tight at stations {i_bad}-{i_bad+1}-{i_bad+2}"


def test_grades_and_datum(cl):
    z, s = arr(cl, "z"), arr(cl, "s")
    assert abs(z[0]) < 0.01  # z0 datum: starts at 0
    grade = np.abs((z[10:] - z[:-10]) / (s[10:] - s[:-10]))
    assert grade.max() < 0.25   # data-corruption guard; admits the real ~23.6% pitch at s≈1691
    assert np.percentile(grade, 95) < 0.15   # overall track character per handoff (grades ~9-12%)
    assert (arr(cl, "w") == 10.0).all()
