import subprocess
import numpy as np
import pytest
import rasterio
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module", autouse=True)
def run_stage():
    subprocess.run([PY, str(ROOT / "scripts" / "60_prepare_rasters.py")], check=True)


def _open(name):
    return rasterio.open(ROOT / "work" / name)


def test_grid_geometry():
    for name in ("dtm_enu.tif", "dsm_enu.tif", "canopy_enu.tif"):
        with _open(name) as ds:
            assert (ds.width, ds.height) == (2624, 1344)
            assert ds.res == (0.5, 0.5)
            assert ds.bounds == (-160.0, -320.0, 1152.0, 352.0)


def test_values_filled_and_plausible():
    with _open("dtm_enu.tif") as ds:
        dtm = ds.read(1)
    assert np.isfinite(dtm).all() and (dtm > -50).all()  # nodata filled
    assert 0.5 < dtm.min() < 6 and 30 < dtm.max() < 45   # source range 1.1..39.5
    with _open("canopy_enu.tif") as ds:
        canopy = ds.read(1)
    assert canopy.min() >= 0 and 20 < canopy.max() < 45  # canopy up to ~29 m on track


def test_track_elevations_match_handoff():
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    with _open("dtm_enu.tif") as ds:
        vals = np.array([v[0] for v in ds.sample(zip(d["x"], d["y"]))])
    assert 4.0 < vals.min() < 5.5 and 20.5 < vals.max() < 23.0  # handoff: 4.8..21.7
