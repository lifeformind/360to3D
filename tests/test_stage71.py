import json
import subprocess
import numpy as np
import pytest
from PIL import Image
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def mask():
    subprocess.run([PY, str(ROOT / "scripts" / "71_verge_masks.py")], check=True)
    meta = json.loads((ROOT / "export" / "verge_masks" / "meta.json").read_text())
    img = np.asarray(Image.open(ROOT / "export" / "verge_masks" / "density.png"))
    return meta, img


def test_dimensions_match_meta(mask):
    meta, img = mask
    assert img.shape == (meta["height"], meta["width"])
    assert meta["px_m"] == 0.5


def test_density_on_verges_only(mask):
    meta, img = mask
    assert (img > 0).mean() > 0.005          # some grass exists
    assert (img > 0).mean() < 0.5            # but not everywhere (road+far = 0)
