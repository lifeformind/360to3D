"""Stage 72: foliage cards -- candidate side-view crops, then feathered cards + placements."""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]


def candidates():
    track = json.loads((ROOT / "work" / "camera_track.json").read_text())
    calib = json.loads((ROOT / "work" / "camera_calib.json").read_text())
    out = ROOT / "work" / "card_candidates"
    out.mkdir(exist_ok=True)
    picks = track["frames"][:: len(track["frames"]) // 8][:8]
    for f in picks:
        for side, rel in (("L", -90), ("R", 90)):
            yaw = (f["heading"] + rel - calib["az0_deg"]) % 360
            if yaw > 180:
                yaw -= 360
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(f["v"]),
                            "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"),
                            "-frames:v", "1",
                            "-vf", f"v360=e:flat:yaw={yaw:.1f}:h_fov=70:v_fov=70,scale=768:768",
                            str(out / f"v{f['v']:.0f}_{side}.jpg")], check=True)
    print(f"candidates -> {out} (controller: pick crops into work/card_selection.json)")


def cut():
    """card_selection.json: [{"src": "v105_L.jpg", "box": [x0,y0,x1,y1]}, ...]"""
    sel = json.loads((ROOT / "work" / "card_selection.json").read_text())
    outdir = ROOT / "export" / "foliage_cards"
    outdir.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:512, 0:512]
    r = np.hypot((xx - 256) / 256, (yy - 256) / 256)
    alpha = np.clip((1.0 - r) * 3.0, 0, 1) ** 0.7  # feathered ellipse
    names = []
    for i, s in enumerate(sel):
        img = Image.open(ROOT / "work" / "card_candidates" / s["src"]).crop(s["box"])
        img = img.resize((512, 512))
        rgba = np.dstack([np.asarray(img), (alpha * 255).astype(np.uint8)])
        name = f"card_{i:02d}.png"
        Image.fromarray(rgba).save(outdir / name)
        names.append(name)

    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if 439 <= st["s"] <= 664]
    rng = np.random.default_rng(11)
    cards = []
    with rasterio.open(ROOT / "work" / "canopy_enu.tif") as can:
        for st in sts[:: 4]:  # every 4 m
            nx, ny = -st["ty"], st["tx"]
            for sgn in (1, -1):
                for lat in np.arange(5.0, 20.0, 1.5):
                    px, py = st["x"] + sgn * lat * nx, st["y"] + sgn * lat * ny
                    h = next(can.sample([(px, py)]))[0]
                    if h >= 3.0:
                        j = rng.uniform(-1.2, 1.2)
                        cards.append(dict(
                            x=round(px + j * nx, 2), y=round(py + j * ny, 2),
                            h=round(float(min(max(h, 2.0), 8.0)), 1),
                            img=str(rng.choice(names)),
                            yaw_deg=round(float(np.degrees(np.arctan2(-sgn * nx, -sgn * ny))), 1)))
                        break
    (outdir / "placements.json").write_text(json.dumps(dict(cards=cards)))
    print(f"{len(names)} cards, {len(cards)} placements")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument("--cut", action="store_true")
    a = ap.parse_args()
    (candidates if a.candidates else cut)()
