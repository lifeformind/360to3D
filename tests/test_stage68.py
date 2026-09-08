import json
import subprocess
import numpy as np
import pytest
from PIL import Image
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def atlas():
    subprocess.run([PY, str(ROOT / "scripts" / "68_road_mosaic.py")], check=True)
    meta = json.loads((ROOT / "export" / "road_albedo" / "atlas_meta.json").read_text())
    return meta


def test_tiles_exist_and_sized(atlas):
    assert atlas["tiles"] == [2, 3]
    for k in atlas["tiles"]:
        im = Image.open(ROOT / "export" / "road_albedo" / f"tile_{k:02d}.png")
        assert im.size == (4096, 512)


def test_coverage_and_content(atlas):
    # slice spans stations ~440..663; tile 2 covers absolute stations [409.6, 614.4),
    # so real coverage in tile 2 begins at px (440-409.6)/0.05 = 608, not the brief's
    # estimated 143 (that figure undercounted the tile-boundary offset). Crop from
    # 660 (safety margin past 608) to 4090 to check the genuinely covered span.
    im2 = np.asarray(Image.open(ROOT / "export" / "road_albedo" / "tile_02.png"))
    band = im2[116:396, 660:4090]  # road band, covered span
    nonblack = (band.sum(axis=2) > 30).mean()
    assert nonblack > 0.95
    # road band should be mostly grey (low chroma) vs green verges outside band
    g_excess = band[..., 1].astype(int) - (band[..., 0].astype(int) + band[..., 2]) // 2
    assert np.median(g_excess) < 12


def test_report_exists(atlas):
    assert (ROOT / "work" / "mosaic_report.png").exists()
