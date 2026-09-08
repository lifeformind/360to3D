import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def outputs():
    subprocess.run([PY, str(ROOT / "scripts" / "67_camera_track.py"),
                    "--v0", "99", "--v1", "134"], check=True)
    track = json.loads((ROOT / "work" / "camera_track.json").read_text())
    calib = json.loads((ROOT / "work" / "camera_calib.json").read_text())
    return track, calib


def test_track_shape_and_monotonic(outputs):
    track, _ = outputs
    fr = track["frames"]
    assert len(fr) == 351  # inclusive 99.0..134.0 at 10 fps
    vs = [f["v"] for f in fr]
    ss = [f["s"] for f in fr]
    assert vs == sorted(vs)
    assert all(b >= a for a, b in zip(ss, ss[1:]))  # moving forward
    assert 430 < fr[0]["s"] < 470 and 650 < fr[-1]["s"] < 690
    assert all(abs(f["t"] - (f["v"] + 2.0)) < 1e-9 for f in fr[:5])


def test_calibration_ranges(outputs):
    _, calib = outputs
    assert calib["mode"] == "world"
    assert 100 <= calib["az0_deg"] <= 116
    assert 2.4 <= calib["h_cam_m"] <= 3.6
