import json
import subprocess
import numpy as np
import pytest
from PIL import Image
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


def test_candidates_mode_produces_crops():
    subprocess.run([PY, str(ROOT / "scripts" / "72_foliage_cards.py"), "--candidates"],
                   check=True)
    crops = list((ROOT / "work" / "card_candidates").glob("*.jpg"))
    assert len(crops) >= 12


def test_cut_mode(tmp_path):
    sel = ROOT / "work" / "card_selection.json"
    if not sel.exists():
        pytest.skip("controller has not selected cards yet")
    subprocess.run([PY, str(ROOT / "scripts" / "72_foliage_cards.py"), "--cut"], check=True)
    pl = json.loads((ROOT / "export" / "foliage_cards" / "placements.json").read_text())
    assert len(pl["cards"]) > 30
    img = np.asarray(Image.open(ROOT / "export" / "foliage_cards" / pl["cards"][0]["img"]))
    assert img.shape == (512, 512, 4) and img[0, 0, 3] == 0  # corners transparent
