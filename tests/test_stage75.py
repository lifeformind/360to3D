import json
import subprocess
import numpy as np
import pytest
from scipy.spatial import cKDTree
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def forest():
    subprocess.run([PY, str(ROOT / "scripts" / "75_forest.py")], check=True)
    return json.loads((ROOT / "export" / "forest_placements.json").read_text())


def plants(forest):
    return [p for c in forest["chunks"] for p in c["plants"]]


def test_counts_and_layers(forest):
    ps = plants(forest)
    # expected-count math for the default slice window: ~60% of band cells vegetated
    # at mean cover_prob 0.42 -> ~1700-1900 structure+ground plants
    assert 1600 <= len(ps) <= 2400
    layers = {p["layer"] for p in ps}
    assert layers == {"canopy", "mid", "under", "ground", "wall"}
    assert all(p["h"] >= 12 for p in ps if p["layer"] == "canopy")
    assert all(6 <= p["h"] < 12 for p in ps if p["layer"] == "mid")


def test_road_exclusion(forest):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    tree = cKDTree([[st["x"], st["y"]] for st in sts])
    ps = plants(forest)
    d, _ = tree.query([[p["x"], p["y"]] for p in ps])
    assert d.min() >= 5.5
    assert d.max() <= 42.0


def test_deterministic(forest):
    first = json.dumps(forest, sort_keys=True)
    subprocess.run([PY, str(ROOT / "scripts" / "75_forest.py")], check=True)
    second = json.dumps(json.loads(
        (ROOT / "export" / "forest_placements.json").read_text()), sort_keys=True)
    assert first == second


def test_chunk_structure(forest):
    s0s = [c["s0"] for c in forest["chunks"]]
    assert s0s == sorted(s0s)
    assert all(abs((b - a) - 20.0) < 0.01 for a, b in zip(s0s, s0s[1:]))
