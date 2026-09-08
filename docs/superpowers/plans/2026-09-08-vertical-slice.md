# Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Task 5 Step 3 and Task 7 Step 2 are CONTROLLER steps; Task 8 ends at a USER checkpoint.

**Goal:** One 225 m stretch (stations 439–664) dressed to final visual quality: projected road mosaic, mosaic-driven verges, footage foliage cards, asset-pack trees, clipped photogrammetry backdrop, one barrier proxy, matched sun/fog.

**Architecture:** New generator stages 67 (camera track + calibration), 68 (registered mosaic tiles), 69 (road overlay mesh with atlas UVs), 71 (verge masks), 72 (foliage cards), 73 (clipped backdrop mesh tiles); one Unity editor script `DressSlice.cs` assembles everything idempotently under `[GEN] Slice`. Original Part A road/terrain stay untouched (overlay sits +2 cm above the road).

**Tech Stack:** Python venv (numpy, scipy, rasterio, PIL, pyproj), ffmpeg (v360), pytest; Unity 6000.3.19f1 URP + unity-editor-mcp tools (editor open; headless CLI fallback). Asset packs already imported: `Assets/TerrainSampleAssets/`, `Assets/TreePackVol.1/`.

**Spec:** `docs/superpowers/specs/2026-09-08-vertical-slice-design.md`

## Global Constraints

- Slice window: video seconds **99–134**, stations ≈ **439–664** (recorded loop only).
- Video↔GPS: t = v + 2.0; equirect is world-locked, initial az0 = 108.0°, h_cam = 3.0 m (stage 67 refines both); horizon level. Compass azimuth: 0°=N(+y_enu), 90°=E; heading = degrees(atan2(dx, dy)).
- Sample road texels 7–9 m BEHIND the camera (hull-free); equirect pixel mapping: col = ((az − az0 + 180) mod 360)/360·W, row = (90 − el)/180·H.
- Mosaic: 5 cm/px; atlas tiles span **204.8 m** (4096 px along-track), lateral 512 px with the 14 m road band (280 px) centred; global tile k covers stations [k·204.8, (k+1)·204.8) — slice touches tiles **2 and 3**. (Deviation from spec's "4096²" recorded: 4096×512 is sufficient and 8× smaller.)
- Road overlay mesh: +0.02 m above road surface; Unity-import frame = (−x_enu, z, y_enu) (importer negates X back).
- Mesh backdrop: SVY21 EPSG:3414 → ENU via pyproj + `scripts/geo.py`; drop triangles with any vertex within **40 m** of the centreline; z_unity = svy_z − z0.
- Asset-pack references discovered via `AssetDatabase.FindAssets` — never hardcoded GUIDs/paths beyond the two pack root folders; fail soft with a console error if packs are missing.
- Python: `venv/Scripts/python` from repo root; Git Bash /c/... paths; Unity project `C:\repos\AmakengCircuit`; sync via `venv/Scripts/python scripts/70_sync_unity.py`.
- Commit after every task; messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01AF1cy5Qz2ZhiHcRmRSQxia`

---

### Task 1: Stage 67 — camera track + calibration refinement

**Files:**
- Create: `scripts/67_camera_track.py`
- Test: `tests/test_stage67.py`

**Interfaces:**
- Consumes: `raw/gpx_004.npz`, `work/centerline.json`, `raw/3A_AMA North 360_.mp4` (calibration frames).
- Produces:
  - `work/camera_track.json`: `{"v0": 99.0, "v1": 134.0, "fps": 10, "frames": [{"v": 99.0, "t": 101.0, "s": ..., "x": ..., "y": ..., "z": ..., "heading": ...}, ...]}` (s/x/y/z from nearest centreline station to GPS-interp position; z = station z).
  - `work/camera_calib.json`: `{"mode": "world", "az0_deg": <refined>, "h_cam_m": <refined>}`.
- Calibration: extract 40 frames across the window at 1920×960, grid-search az0 ∈ {104…112 step 2} × h_cam ∈ {2.5, 2.75, 3.0, 3.25, 3.5}; for each candidate build mini-strips (lateral ±7 m, 0.1 m texels, 8 m behind), detect road span per strip via greenness (row profile of G−(R+B)/2, road = least-green run); score = |median road width − 10 m| + 0.05·std(road centre). Lowest score wins.

- [ ] **Step 1: Write the failing test**

`tests/test_stage67.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage67.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/67_camera_track.py`**

```python
"""Stage 67: per-frame camera poses + one-off az0/h_cam calibration (world-locked equirect)."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
FPS = 10
DT = 2.0
D_BACK = 8.0


def build_track(v0, v1):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    S = np.array([st["s"] for st in sts])
    XY = np.array([[st["x"], st["y"]] for st in sts])
    Z = np.array([st["z"] for st in sts])
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    dx, dy = np.gradient(d["x"]), np.gradient(d["y"])
    tree = cKDTree(XY)
    frames = []
    for k in range(int(round((v1 - v0) * FPS)) + 1):
        v = v0 + k / FPS
        t = v + DT
        gx = np.interp(t, d["t"], d["x"]); gy = np.interp(t, d["t"], d["y"])
        _, i = tree.query([gx, gy])
        heading = float(np.degrees(np.arctan2(np.interp(t, d["t"], dx),
                                              np.interp(t, d["t"], dy))))
        frames.append(dict(v=round(v, 1), t=round(t, 1), s=float(S[i]),
                           x=float(XY[i, 0]), y=float(XY[i, 1]), z=float(Z[i]),
                           heading=round(heading, 2)))
    return frames


def sample_strip(img, cam, az0, sts_interp, s_strip, lat):
    """Project one 1 m strip of texels; returns [n_lat, n_s, 3] uint8."""
    px, py, pz, nx, ny = sts_interp(s_strip)
    Px = px[None, :] + lat[:, None] * nx[None, :]
    Py = py[None, :] + lat[:, None] * ny[None, :]
    Pz = pz[None, :] - 0.02 * np.abs(lat[:, None])
    dxx = Px - cam[0]; dyy = Py - cam[1]; dzz = Pz - cam[2]
    az = np.degrees(np.arctan2(dxx, dyy))
    el = np.degrees(np.arctan2(dzz, np.hypot(dxx, dyy)))
    H, W = img.shape[:2]
    ci = np.clip((((az - az0 + 180.0) % 360.0) / 360.0 * W).astype(int), 0, W - 1)
    ri = np.clip(((90.0 - el) / 180.0 * H).astype(int), 0, H - 1)
    return img[ri, ci]


def make_interp():
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    S = np.array([st["s"] for st in sts])
    X = np.array([st["x"] for st in sts]); Y = np.array([st["y"] for st in sts])
    Z = np.array([st["z"] for st in sts])
    TX = np.array([st["tx"] for st in sts]); TY = np.array([st["ty"] for st in sts])

    def f(s_vals):
        px = np.interp(s_vals, S, X); py = np.interp(s_vals, S, Y)
        pz = np.interp(s_vals, S, Z)
        tx = np.interp(s_vals, S, TX); ty = np.interp(s_vals, S, TY)
        return px, py, pz, -ty, tx  # position + left normal
    return f


def road_span(strip):
    """Detected (width_m, centre_m) from greenness; texel 0.1 m, lat -7..7."""
    g = strip[..., 1].astype(float) - (strip[..., 0].astype(float) + strip[..., 2]) / 2
    prof = g.mean(axis=1)
    road = prof < np.percentile(prof, 45)
    idx = np.where(road)[0]
    if len(idx) < 10:
        return None
    return (len(idx) * 0.1, (idx.mean() + 0.5) * 0.1 - 7.0)


def calibrate(frames):
    picks = frames[:: max(1, len(frames) // 40)][:40]
    tmp = Path(tempfile.mkdtemp())
    imgs = []
    for f in picks:
        out = tmp / f"c{f['v']}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(f["v"]),
                        "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"), "-frames:v", "1",
                        "-vf", "scale=1920:960", str(out)], check=True)
        imgs.append(np.asarray(Image.open(out)))
    interp = make_interp()
    lat = np.arange(-7.0, 7.0, 0.1) + 0.05
    best = (1e9, 108.0, 3.0)
    for az0 in np.arange(104, 113, 2.0):
        for h in (2.5, 2.75, 3.0, 3.25, 3.5):
            spans = []
            for f, img in zip(picks, imgs):
                cam = np.array([f["x"], f["y"], f["z"] + h])
                s_strip = np.arange(f["s"] - D_BACK - 0.5, f["s"] - D_BACK + 0.5, 0.1)
                sp = road_span(sample_strip(img, cam, az0, interp, s_strip, lat))
                if sp:
                    spans.append(sp)
            if len(spans) < 20:
                continue
            widths = np.array([s[0] for s in spans])
            centres = np.array([s[1] for s in spans])
            score = abs(np.median(widths) - 10.0) + 0.05 * centres.std()
            if score < best[0]:
                best = (score, float(az0), float(h))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v0", type=float, default=99.0)
    ap.add_argument("--v1", type=float, default=134.0)
    a = ap.parse_args()
    frames = build_track(a.v0, a.v1)
    score, az0, h = calibrate(frames)
    (ROOT / "work" / "camera_track.json").write_text(
        json.dumps(dict(v0=a.v0, v1=a.v1, fps=FPS, frames=frames)))
    (ROOT / "work" / "camera_calib.json").write_text(
        json.dumps(dict(mode="world", az0_deg=az0, h_cam_m=h, score=round(score, 3))))
    print(f"{len(frames)} poses; calib az0={az0} h_cam={h} (score {score:.3f})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage67.py -v` (calibration extracts 40 frames — a few minutes)
Expected: 2 passed. Record the chosen az0/h_cam in the report.

- [ ] **Step 5: Commit**

```bash
git add scripts/67_camera_track.py tests/test_stage67.py && git commit -m "feat: stage 67 - camera track + equirect calibration"
```

---

### Task 2: Stage 68 — registered road mosaic tiles

**Files:**
- Create: `scripts/68_road_mosaic.py`
- Test: `tests/test_stage68.py`

**Interfaces:**
- Consumes: `work/camera_track.json`, `work/camera_calib.json`, `work/centerline.json`, video.
- Produces: `export/road_albedo/tile_02.png`, `tile_03.png` (4096×512 RGB; along-track u, lateral v with 280-px road band centred), `export/road_albedo/atlas_meta.json`:
  `{"texel_m": 0.05, "tile_span_m": 204.8, "lateral_half_m": 7.0, "lateral_px": 512, "road_px": 280, "tiles": [2, 3]}`, `work/mosaic_report.png` (QA strip).
- Registration order: per-strip exposure gain → pairwise NCC lateral shifts (high-pass of cumulative) → absolute road-centre alignment (smoothed) → streak mask via two-distance disagreement (D=8 vs D=13) with along-track median inpaint.

- [ ] **Step 1: Write the failing test**

`tests/test_stage68.py`:
```python
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
    # slice spans stations 439..664 -> tile 2 px 143..4096, tile 3 px 0..968 (0.05 m/px)
    im2 = np.asarray(Image.open(ROOT / "export" / "road_albedo" / "tile_02.png"))
    band = im2[116:396, 200:4090]  # road band, covered span
    nonblack = (band.sum(axis=2) > 30).mean()
    assert nonblack > 0.95
    # road band should be mostly grey (low chroma) vs green verges outside band
    g_excess = band[..., 1].astype(int) - (band[..., 0].astype(int) + band[..., 2]) // 2
    assert np.median(g_excess) < 12


def test_report_exists(atlas):
    assert (ROOT / "work" / "mosaic_report.png").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage68.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/68_road_mosaic.py`**

```python
"""Stage 68: push-broom road mosaic with registration, streak masking, atlas tiling."""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.signal import savgol_filter

import importlib
cam67 = importlib.import_module("67_camera_track")

ROOT = Path(__file__).resolve().parents[1]
TEXEL = 0.05
HALF_W = 7.0
D_NEAR, D_FAR = 8.0, 13.0
TILE_SPAN = 204.8
LAT_PX, ROAD_PX = 512, 280
GUTTER = (LAT_PX - ROAD_PX) // 2


def extract_frames(track):
    tmp = Path(tempfile.mkdtemp(prefix="mosaic_"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-ss", str(track["v0"]), "-t", str(track["v1"] - track["v0"] + 0.2),
                    "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"),
                    "-vf", f"fps={track['fps']}", "-q:v", "3",
                    str(tmp / "f%04d.jpg")], check=True)
    return tmp


def main():
    track = json.loads((ROOT / "work" / "camera_track.json").read_text())
    calib = json.loads((ROOT / "work" / "camera_calib.json").read_text())
    az0, h_cam = calib["az0_deg"], calib["h_cam_m"]
    interp = cam67.make_interp()
    frames = track["frames"]
    tmp = extract_frames(track)

    lat = (np.arange(ROAD_PX) + 0.5) * TEXEL - HALF_W
    s_lo = frames[0]["s"] - D_NEAR - 1
    s_hi = frames[-1]["s"] - D_NEAR + 1
    n_s = int((s_hi - s_lo) / TEXEL)
    near = np.zeros((ROAD_PX, n_s, 3), np.float32)
    far = np.zeros_like(near)
    have = np.zeros(n_s, bool)
    strip_of = np.full(n_s, -1)

    for k, f in enumerate(frames):
        p = tmp / f"f{k + 1:04d}.jpg"
        if not p.exists():
            continue
        img = np.asarray(Image.open(p))
        cam = np.array([f["x"], f["y"], f["z"] + h_cam])
        for D, dest in ((D_NEAR, near), (D_FAR, far)):
            a = f["s"] - D - 0.55
            cols = np.arange(max(0, int((a - s_lo) / TEXEL)),
                             min(n_s, int((a + 1.1 - s_lo) / TEXEL)))
            if not len(cols):
                continue
            s_vals = s_lo + (cols + 0.5) * TEXEL
            strip = cam67.sample_strip(img, cam, az0, interp, s_vals, lat)
            if D == D_NEAR:
                # exposure gain: normalize road-band luminance to 128
                lum = strip[GUTTER == 0][...] if False else strip
                gain = 128.0 / max(20.0, strip[..., :3].mean())
                dest[:, cols] = np.clip(strip * gain, 0, 255)
                have[cols] = True
                strip_of[cols] = k
            else:
                dest[:, cols] = strip

    # --- registration: NCC pairwise (high-pass) + absolute road-centring ---
    CH = 20  # 1 m chunks
    nch = n_s // CH
    grey = near.mean(axis=2)
    rel = np.zeros(nch)
    for i in range(1, nch):
        a = grey[:, (i - 1) * CH:i * CH].mean(axis=1)
        b = grey[:, i * CH:(i + 1) * CH].mean(axis=1)
        shifts = range(-10, 11)
        scores = [np.corrcoef(a[10:-10], np.roll(b, sh)[10:-10])[0, 1] for sh in shifts]
        rel[i] = list(shifts)[int(np.argmax(scores))]
    acc = np.cumsum(rel)
    acc -= savgol_filter(acc, min(len(acc) - (1 - len(acc) % 2), 61) | 1, 2)  # high-pass

    centres = np.full(nch, ROAD_PX / 2)
    for i in range(nch):
        chunk = near[:, i * CH:(i + 1) * CH]
        g = chunk[..., 1] - (chunk[..., 0] + chunk[..., 2]) / 2
        prof = g.mean(axis=1)
        idx = np.where(prof < np.percentile(prof, 40))[0]
        if len(idx) > 20:
            centres[i] = idx.mean()
    win = min(len(centres) - (1 - len(centres) % 2), 31) | 1
    centres = np.clip(savgol_filter(centres, win, 2), ROAD_PX / 2 - 60, ROAD_PX / 2 + 60)

    out = np.zeros_like(near)
    outf = np.zeros_like(far)
    for i in range(nch):
        shift = int(round(ROAD_PX / 2 - centres[i] + acc[i]))
        sl = slice(i * CH, (i + 1) * CH)
        out[:, sl] = np.roll(near[:, sl], shift, axis=0)
        outf[:, sl] = np.roll(far[:, sl], shift, axis=0)

    # --- streak mask: near/far disagreement -> along-track median inpaint ---
    diff = np.abs(out - outf).mean(axis=2)
    mask = diff > 55
    if mask.any():
        from scipy.ndimage import binary_dilation, median_filter
        mask = binary_dilation(mask, iterations=3)
        med = median_filter(out, size=(1, 41, 1))
        out[mask] = med[mask]

    # --- QA report + atlas tiles ---
    rep = Image.fromarray(out.astype(np.uint8)).resize((2250, 140))
    rep.save(ROOT / "work" / "mosaic_report.png")

    outdir = ROOT / "export" / "road_albedo"
    outdir.mkdir(parents=True, exist_ok=True)
    tiles = sorted({int(s // TILE_SPAN) for s in (s_lo + 1, s_hi - 1)})
    for k in tiles:
        tile = np.zeros((LAT_PX, 4096, 3), np.uint8)
        t0 = k * TILE_SPAN
        c0 = int((t0 - s_lo) / TEXEL)
        src_a, src_b = max(0, c0), min(n_s, c0 + 4096)
        dst_a = src_a - c0
        tile[GUTTER:GUTTER + ROAD_PX, dst_a:dst_a + (src_b - src_a)] = \
            out[:, src_a:src_b].astype(np.uint8)
        tile[:GUTTER] = tile[GUTTER]
        tile[GUTTER + ROAD_PX:] = tile[GUTTER + ROAD_PX - 1]
        Image.fromarray(tile).save(outdir / f"tile_{k:02d}.png")
    (outdir / "atlas_meta.json").write_text(json.dumps(dict(
        texel_m=TEXEL, tile_span_m=TILE_SPAN, lateral_half_m=HALF_W,
        lateral_px=LAT_PX, road_px=ROAD_PX, tiles=tiles)))
    print(f"tiles {tiles}; coverage {have.mean()*100:.1f}%; streak px {int(mask.sum())}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage68.py -v` (decodes 351 8K frames twice-sampled — allow ~10 min)
Expected: 3 passed.

- [ ] **Step 5: Controller looks at `work/mosaic_report.png`** (Read it) — seams should be visibly better than the pilot's v2; if not, tune NCC window/shift range once and note it.

- [ ] **Step 6: Commit**

```bash
git add scripts/68_road_mosaic.py tests/test_stage68.py && git commit -m "feat: stage 68 - registered road mosaic atlas tiles"
```

---

### Task 3: Stage 69 — road overlay mesh with atlas UVs

**Files:**
- Create: `scripts/69_road_uv.py`
- Test: `tests/test_stage69.py`

**Interfaces:**
- Consumes: `work/centerline.json`, `export/road_albedo/atlas_meta.json`.
- Produces: `export/road_overlay.obj` — objects `overlay_tile_02`, `overlay_tile_03`; flat 6-point cross-section spanning lateral ±7 m at road z + 0.02 − 0.02·|lat| (crown-following); Unity-import frame; UVs u = (s − k·204.8)/204.8, v = (GUTTER + (lat+7)/14·280)/512 with GUTTER = 116. Only stations inside each tile's covered span.

- [ ] **Step 1: Write the failing test**

`tests/test_stage69.py`:
```python
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def obj():
    subprocess.run([PY, str(ROOT / "scripts" / "69_road_uv.py")], check=True)
    verts, uvs, objects = [], [], []
    for line in (ROOT / "export" / "road_overlay.obj").read_text().splitlines():
        p = line.split()
        if p and p[0] == "v":
            verts.append([float(x) for x in p[1:4]])
        elif p and p[0] == "vt":
            uvs.append([float(x) for x in p[1:3]])
        elif p and p[0] == "o":
            objects.append(p[1])
    return np.array(verts), np.array(uvs), objects


def test_objects_and_span(obj):
    verts, uvs, objects = obj
    assert objects == ["overlay_tile_02", "overlay_tile_03"]
    assert len(verts) > 2000


def test_uvs_in_range(obj):
    _, uvs, _ = obj
    assert uvs[:, 0].min() >= -0.001 and uvs[:, 0].max() <= 1.001
    assert uvs[:, 1].min() >= 116 / 512 - 0.001 and uvs[:, 1].max() <= 396 / 512 + 0.001


def test_overlay_above_road(obj):
    verts, _, _ = obj
    # centre-line vertices sit ~0.02 above station z; sanity: y within plausible band
    assert -10 < verts[:, 1].min() and verts[:, 1].max() < 25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage69.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `scripts/69_road_uv.py`**

```python
"""Stage 69: thin road-overlay mesh with mosaic-atlas UVs (sits 2 cm above the road)."""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LIFT = 0.02
CROWN = 0.02


def main():
    meta = json.loads((ROOT / "export" / "road_albedo" / "atlas_meta.json").read_text())
    span, half, lat_px, road_px = (meta["tile_span_m"], meta["lateral_half_m"],
                                   meta["lateral_px"], meta["road_px"])
    gutter = (lat_px - road_px) // 2
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    lats = np.array([-7.0, -5.0, -2.0, 2.0, 5.0, 7.0])

    lines = []
    vbase = 1
    for k in meta["tiles"]:
        tsts = [st for st in sts if k * span <= st["s"] < (k + 1) * span]
        if len(tsts) < 2:
            continue
        lines.append(f"o overlay_tile_{k:02d}")
        nv = 0
        for st in tsts:
            nx, ny = -st["ty"], st["tx"]
            u = (st["s"] - k * span) / span
            for l in lats:
                ex = st["x"] + nx * l
                ey = st["y"] + ny * l
                ez = st["z"] + LIFT - CROWN * abs(l)
                v = (gutter + (l + half) / (2 * half) * road_px) / lat_px
                lines.append(f"v {-ex:.3f} {ez:.3f} {ey:.3f}")
                lines.append(f"vt {u:.5f} {v:.5f}")
                nv += 1
        npf = len(lats)
        rows = nv // npf
        for i in range(rows - 1):
            for j in range(npf - 1):
                a = vbase + i * npf + j
                b = a + 1
                c = vbase + (i + 1) * npf + j
                dd = c + 1
                lines.append(f"f {a}/{a} {c}/{c} {b}/{b}")
                lines.append(f"f {b}/{b} {c}/{c} {dd}/{dd}")
        vbase += nv
    (ROOT / "export" / "road_overlay.obj").write_text("\n".join(lines))
    print(f"road_overlay.obj: {vbase - 1} verts, tiles {meta['tiles']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, expect 3 passed; commit**

```bash
git add scripts/69_road_uv.py tests/test_stage69.py && git commit -m "feat: stage 69 - road overlay mesh with atlas UVs"
```

---

### Task 4: Stage 71 — verge masks

**Files:**
- Create: `scripts/71_verge_masks.py`
- Test: `tests/test_stage71.py`

**Interfaces:**
- Consumes: `export/road_albedo/tile_*.png` + `atlas_meta.json`, `work/centerline.json`.
- Produces: `export/verge_masks/density.png` (8-bit grayscale, 1 px = 0.5 m, world-anchored),
  `export/verge_masks/meta.json`: `{"xmin": ..., "ymax": ..., "px_m": 0.5, "width": ..., "height": ...}` —
  density = greenness of the nearest mosaic texel for world cells within 3–7 m laterally of the
  slice centreline span (grass grows on verges, not the roadway), 0 elsewhere.

- [ ] **Step 1: Write the failing test**

`tests/test_stage71.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails; Step 3: Implement `scripts/71_verge_masks.py`**

```python
"""Stage 71: verge grass density from mosaic greenness, world-anchored 0.5 m grid."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
PX = 0.5
VERGE = (3.0, 7.0)


def main():
    meta = json.loads((ROOT / "export" / "road_albedo" / "atlas_meta.json").read_text())
    span, half, lat_px, road_px = (meta["tile_span_m"], meta["lateral_half_m"],
                                   meta["lateral_px"], meta["road_px"])
    gutter = (lat_px - road_px) // 2
    tiles = {k: np.asarray(Image.open(ROOT / "export" / "road_albedo" / f"tile_{k:02d}.png"))
             for k in meta["tiles"]}
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]
           and any(k * span <= st["s"] < (k + 1) * span for k in meta["tiles"])]
    S = np.array([st["s"] for st in sts])
    XY = np.array([[st["x"], st["y"]] for st in sts])
    N = np.array([[-st["ty"], st["tx"]] for st in sts])
    tree = cKDTree(XY)

    xmin, xmax = XY[:, 0].min() - 10, XY[:, 0].max() + 10
    ymin, ymax = XY[:, 1].min() - 10, XY[:, 1].max() + 10
    W, H = int((xmax - xmin) / PX), int((ymax - ymin) / PX)
    dens = np.zeros((H, W), np.uint8)
    gx, gy = np.meshgrid(xmin + (np.arange(W) + 0.5) * PX,
                         ymax - (np.arange(H) + 0.5) * PX)
    dist, idx = tree.query(np.stack([gx.ravel(), gy.ravel()], 1))
    rel = np.stack([gx.ravel(), gy.ravel()], 1) - XY[idx]
    latv = (rel * N[idx]).sum(axis=1)
    on_verge = (np.abs(latv) >= VERGE[0] + 2.0) & (np.abs(latv) <= VERGE[1]) & (dist < 12)
    # note: road half-width is 5 m; verge band = 5..7 m from centreline
    for i in np.where(on_verge)[0]:
        s = S[idx[i]]
        k = int(s // span)
        if k not in tiles:
            continue
        u = int((s - k * span) / span * 4095)
        v = int(gutter + (latv[i] + half) / (2 * half) * road_px)
        px = tiles[k][np.clip(v, 0, lat_px - 1), u].astype(int)
        green = px[1] - (px[0] + px[2]) // 2
        r, c = divmod(i, W)
        dens[r, c] = np.clip(green * 6, 0, 255) if green > 4 else 0
    out = ROOT / "export" / "verge_masks"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(dens).save(out / "density.png")
    (out / "meta.json").write_text(json.dumps(dict(
        xmin=xmin, ymax=ymax, px_m=PX, width=W, height=H)))
    print(f"density {W}x{H}, verge cells {(dens > 0).sum()}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests (2 passed); Step 5: Commit**

```bash
git add scripts/71_verge_masks.py tests/test_stage71.py && git commit -m "feat: stage 71 - verge density masks from mosaic"
```

---

### Task 5: Stage 72 — foliage cards + curation

**Files:**
- Create: `scripts/72_foliage_cards.py`
- Test: `tests/test_stage72.py`

**Interfaces:**
- Consumes: `work/camera_track.json`, `work/camera_calib.json`, video, `work/canopy_enu.tif`, `work/centerline.json`.
- Produces: `export/foliage_cards/card_%02d.png` (RGBA 512×512, elliptical feathered alpha),
  `export/foliage_cards/placements.json`: `{"cards": [{"x":..., "y":..., "h": <height m>, "img": "card_03.png", "yaw_deg": <faces road>}]}` along both canopy edges through the slice, 3–6 m jittered spacing.
- Card SOURCE crops are side-view v360 renders (relative az ±90°) at 8 sampled times; the
  CONTROLLER picks the 10–15 best crops (Step 3); the script's `--cut` mode then applies the
  elliptical alpha and writes cards + placements.

- [ ] **Step 1: Write the failing test**

`tests/test_stage72.py`:
```python
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
```

- [ ] **Step 2: Implement `scripts/72_foliage_cards.py`**

```python
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
```

- [ ] **Step 3: CONTROLLER — curate cards**

Run `--candidates`; Read the 16 crops; choose 10–15 foliage regions (bush/frond filling the
box, roughly centred); write `work/card_selection.json` with `[{"src": ..., "box": [x0,y0,x1,y1]}, ...]`;
run `--cut`; Read 2 output cards to confirm feathering looks usable. Also record (from the
mosaic/report) the barrier smear station and side → write `export/slice_extras.json`:
`{"barrier": {"s": <station>, "lat": <signed lateral m>, "len_m": 4}}` for Task 7.

- [ ] **Step 4: Run tests (2 passed once selection exists); Step 5: Commit**

```bash
git add scripts/72_foliage_cards.py tests/test_stage72.py && git commit -m "feat: stage 72 - foliage cards + placements"
```

---

### Task 6: Stage 73 — clipped backdrop mesh tiles

**Files:**
- Create: `scripts/73_mesh_tiles.py`
- Test: `tests/test_stage73.py`

**Interfaces:**
- Consumes: `raw/MESH OBJ/Tile_*`, `work/centerline.json`, `scripts/geo.py`, z0 from centreline.
- Produces: `export/backdrop/Tile_*.obj|.mtl|*.jpg` — the tiles overlapping the slice ENU bbox
  (± 250 m), vertices converted SVY21→ENU→Unity-import frame (−x, z−z0, y), triangles with any
  vertex within **40 m** of the recorded centreline REMOVED, unreferenced vertices kept (harmless).
  MTL/JPG copied unchanged.

- [ ] **Step 1: Write the failing test**

`tests/test_stage73.py`:
```python
import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def tiles():
    subprocess.run([PY, str(ROOT / "scripts" / "73_mesh_tiles.py")], check=True)
    return sorted((ROOT / "export" / "backdrop").glob("Tile_*.obj"))


def test_tiles_produced(tiles):
    assert 2 <= len(tiles) <= 12


def test_clip_respected(tiles):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if 400 <= st["s"] <= 700]
    from scipy.spatial import cKDTree
    tree = cKDTree([[st["x"], st["y"]] for st in sts])
    verts, faces = [], []
    for line in tiles[0].read_text().splitlines():
        p = line.split()
        if p and p[0] == "v":
            verts.append([float(x) for x in p[1:4]])
        elif p and p[0] == "f":
            faces.append([int(t.split("/")[0]) - 1 for t in p[1:4]])
    verts = np.array(verts)
    used = np.unique(np.array(faces).ravel()) if faces else []
    if len(used):
        # Unity-import frame: ENU x = -vx, y_enu = vz
        enu = np.stack([-verts[used, 0], verts[used, 2]], 1)
        d, _ = tree.query(enu)
        near_slice = d[d < 250]
        if len(near_slice):
            assert near_slice.min() > 38.0
```

- [ ] **Step 2: Run to verify it fails; Step 3: Implement `scripts/73_mesh_tiles.py`**

```python
"""Stage 73: convert + clip photogrammetry tiles around the slice into Unity-import frame."""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pyproj
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "raw" / "MESH OBJ"
CLIP_M = 40.0
MARGIN = 250.0
S_RANGE = (439.0, 664.0)


def main():
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    z0 = cl["z0"]
    sts = [st for st in cl["stations"] if not st["provisional"]]
    tree = cKDTree([[st["x"], st["y"]] for st in sts])
    sl = [st for st in sts if S_RANGE[0] <= st["s"] <= S_RANGE[1]]
    xs = [st["x"] for st in sl]; ys = [st["y"] for st in sl]

    to_svy = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3414", always_xy=True)
    to_wgs = pyproj.Transformer.from_crs("EPSG:3414", "EPSG:4326", always_xy=True)
    lat_a, lon_a = geo.enu_to_latlon(min(xs) - MARGIN, min(ys) - MARGIN)
    lat_b, lon_b = geo.enu_to_latlon(max(xs) + MARGIN, max(ys) + MARGIN)
    (sx_a, sy_a) = to_svy.transform(lon_a, lat_a)
    (sx_b, sy_b) = to_svy.transform(lon_b, lat_b)

    out = ROOT / "export" / "backdrop"
    out.mkdir(parents=True, exist_ok=True)
    n_done = 0
    for tx in range(int(sx_a // 200), int(sx_b // 200) + 1):
        for ty in range(int(sy_a // 200), int(sy_b // 200) + 1):
            tdir = SRC / f"Tile_+{tx:03d}_+{ty:03d}"
            if not tdir.exists():
                continue
            src_obj = next(tdir.glob("*.obj"))
            # two-pass: convert all verts + distances first, then filter faces
            txt = src_obj.read_text().splitlines()
            vs = [l for l in txt if l.startswith("v ")]
            enu_pts = []
            v_lines = []
            for l in vs:
                p = l.split()
                sx, sy, sz = float(p[1]), float(p[2]), float(p[3])
                lon, lat = to_wgs.transform(sx, sy)
                ex, ey = geo.latlon_to_enu(lat, lon)
                enu_pts.append((float(ex), float(ey)))
                v_lines.append(f"v {-float(ex):.3f} {sz - z0:.3f} {float(ey):.3f}")
            dist, _ = tree.query(np.array(enu_pts))
            keep = []
            for l in txt:
                if l.startswith("v "):
                    keep.append(v_lines.pop(0))
                elif l.startswith("f "):
                    idx = [int(t.split("/")[0]) - 1 for t in l.split()[1:]]
                    if min(dist[i] for i in idx) > CLIP_M:
                        keep.append(l)
                elif l.split() and l.split()[0] in ("vt", "vn", "mtllib", "usemtl", "o", "g"):
                    keep.append(l)
            (out / src_obj.name).write_text("\n".join(keep))
            shutil.copy2(tdir / (src_obj.stem + ".mtl"), out / (src_obj.stem + ".mtl"))
            for jpg in tdir.glob("*.jpg"):
                shutil.copy2(jpg, out / jpg.name)
            n_done += 1
    print(f"{n_done} backdrop tiles -> {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests (2 passed; ~4–8 tiles, a few minutes for pyproj on ~800k verts); Step 5: Commit**

```bash
git add scripts/73_mesh_tiles.py tests/test_stage73.py && git commit -m "feat: stage 73 - clipped backdrop mesh tiles"
```

---

### Task 7: DressSlice.cs — scene assembly

**Files:**
- Create: `unity/DressSlice.cs`
- Modify: `scripts/70_sync_unity.py` (copy `export/road_albedo/`, `verge_masks/`, `foliage_cards/`, `backdrop/`, `road_overlay.obj`, `slice_extras.json` into `Assets/Amakeng/Generated/` preserving subfolders)

**Interfaces:**
- Consumes: everything under `Assets/Amakeng/Generated/` from Tasks 2–6; asset packs.
- Produces: menu **Amakeng > Dress Slice** / `Amakeng.DressSlice.Dress()`, idempotent under `[GEN] Slice`:
  1. URP-converts pack materials once: `UnityEditor.Rendering.Universal.Converters.RunInBatchMode(ConverterContainerId.BuiltInToURP)` in try/catch (log + continue on API absence; magenta trees then fixed manually via menu Window→Rendering→Render Pipeline Converter — say so in the console message).
  2. Imports `road_overlay.obj`; per-tile URP Lit material with `tile_NN.png` albedo (smoothness 0.1); no collider.
  3. Terrain details: find grass/fern textures in `Assets/TerrainSampleAssets` via `AssetDatabase.FindAssets("t:Texture2D grass", ...)` etc.; add 2 detail prototypes; write density into `terrainData.SetDetailLayer` for the slice world region by sampling `verge_masks/density.png` through its meta (world → detail-grid mapping via terrain position/size).
  4. Trees: find 3–4 tree prefabs (`t:Prefab` in `Assets/TreePackVol.1` + TerrainSampleAssets); add as tree prototypes; instances where canopy… placement comes from `foliage_cards/placements.json` positions with `h > 5` (tall = tree) — cards with `h <= 5` become card quads instead.
  5. Foliage cards: for each placement with h ≤ 5: vertical quad (two-sided URP Lit, alpha clip 0.3, base map = card PNG), size h × h, positioned at terrain height, yaw per JSON.
  6. Backdrop: import each `backdrop/Tile_*.obj`, add MeshCollider, parent under `[GEN] Slice/Backdrop`.
  7. Barrier: from `slice_extras.json` — striped box (1 m high, len_m long) at station+lat position; texture = `Generated/barrier_stripe.png` if present else red tint.
  8. Sun + fog: NOAA solar position for lat 1.407 lon 103.716 at 2026-07-24 15:24 SGT (implement the standard NOAA declination/hour-angle formulas in C#); RenderSettings.fog = true, fogMode Exp2, density 0.004, fog color sampled sky-grey (200,205,210).

- [ ] **Step 1: Update `scripts/70_sync_unity.py`** — replace the flat `export/` copy loop with a recursive copy that preserves subdirectories (`shutil.copytree(..., dirs_exist_ok=True)` for `export/` → `Generated/`, still renaming `.raw` → `.raw.bytes` at top level).

- [ ] **Step 2: Write `unity/DressSlice.cs`** — the implementer writes this file following the Produces contract above. Discovery-first: before coding steps 3–4, run a short `Unity_RunCommand` (or editor log print) listing `AssetDatabase.FindAssets` results for the pack folders and adapt asset queries to what exists (record chosen assets in the report). All Unity API uses that fail to compile may be adapted minimally — document each adaptation. Class layout: `public static void Dress()` calling private static methods `ConvertPackMaterials() / BuildOverlay() / PaintDetails() / PlantTrees() / PlaceCards() / ImportBackdrop() / PlaceBarrier() / SetAtmosphere()` in that order, each idempotent (delete-or-replace its own `[GEN] Slice` children / assets before creating).

- [ ] **Step 3: Sync + run via MCP**

`venv/Scripts/python scripts/70_sync_unity.py`, then `Unity_RunCommand`: `Amakeng.DressSlice.Dress();` — console must end clean (warnings about pack material conversion acceptable, note them). Fallback: headless `-executeMethod Amakeng.DressSlice.Dress`.

- [ ] **Step 4: Capture 3 driver-height views** via probe camera + `Unity_Camera_Capture` at stations 460, 545 (barrier), 640, looking along-track; controller Reads them against the corresponding video frames (v ≈ 102/115/130 forward crops) — composition should match: road, verge grass, foliage walls, treeline, backdrop.

- [ ] **Step 5: Commit**

```bash
git add unity/DressSlice.cs scripts/70_sync_unity.py && git commit -m "feat: DressSlice - vertical slice scene assembly"
```

---

### Task 8: Slice run + USER drive checkpoint

- [ ] **Step 1: Full regeneration order check** — `bash scripts/run_generate.sh` still passes (Part A stages unaffected), then stages 67 → 68 → 69 → 71 → 72(--cut) → 73 rerun cleanly from their outputs, full pytest suite green.
- [ ] **Step 2: Rebuild + dress via MCP**: `BuildAmakeng.BuildScene(); BuildVehicle.Build(); DressSlice.Dress();` console clean; validate road (expect 641/641).
- [ ] **Step 3: Frame rate probe**: enter Play mode via `Unity_ManageEditor` (or ask user), sample `Unity_Profiler_GetCounterSummary` FPS/frame-time around the slice; record. Target ≥ 60 fps.
- [ ] **Step 4: Commit any fixes; push branch.**
- [ ] **Step 5: USER CHECKPOINT — the acceptance drive.** User drives into and through the slice. Judgment: "entering the slice feels like entering the real circuit"; no gross card billboarding; fps acceptable. Collect tuning notes (card density, grass density, fog, tree species mix) → controller applies → re-dress → re-drive as needed.

---

## Self-Review Notes

- Spec coverage: stages 67 (Task 1), 68 (Task 2), 69 (Task 3), 71 (Task 4), 72 (Task 5),
  backdrop clipping (Task 6, added as stage 73 per spec's DressSlice mesh-tile bullet),
  DressSlice with material conversion + sun/fog (Task 7), acceptance drive (Task 8).
  Atlas tile size deviation (4096×512 vs spec's 4096²) recorded in Global Constraints.
- Placeholder scan: clean (Task 6's draft dead-code block was removed in review — only the
  two-pass implementation ships). Task 7's C# is a contract + method
  layout rather than verbatim code because pack asset names are unknowable until import-time
  discovery — the dispatch marks discovery-first adaptation as in-scope.
- Type consistency: atlas_meta fields identical across 68/69/71; placements.json consumed by
  DressSlice steps 4–5 with the h>5 tree/card split; camera_track/calib schemas shared by
  67→68→72; slice_extras.json produced in Task 5 Step 3, consumed in Task 7 step 7.
