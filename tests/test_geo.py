import numpy as np
from conftest import ROOT
import geo


def test_roundtrip_matches_npz():
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    x, y = geo.latlon_to_enu(d["lat"], d["lon"])
    assert np.abs(x - d["x"]).max() < 0.001
    assert np.abs(y - d["y"]).max() < 0.001
    lat, lon = geo.enu_to_latlon(x, y)
    assert np.abs(lat - d["lat"]).max() < 1e-9
    assert np.abs(lon - d["lon"]).max() < 1e-9


def test_grid_contains_track():
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    g = geo.GRID
    assert g["xmin"] < d["x"].min() - 99 and g["xmax"] > d["x"].max() + 99
    assert g["ymin"] < d["y"].min() - 99 and g["ymax"] > d["y"].max() + 99
    assert g["width"] == round((g["xmax"] - g["xmin"]) / g["px"])
    assert g["height"] == round((g["ymax"] - g["ymin"]) / g["px"])
