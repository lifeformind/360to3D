# Part A — Drivable Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A drivable Unity scene: DTM terrain + 10 m crowned gravel road ribbon generated from the GPX centreline, with a WheelCollider vehicle, per spec Part A.

**Architecture:** Python generator stages 60–63 turn the two rasters + GPX into a Unity Terrain RAW heightmap and a road OBJ (all in ENU metres, converted only at export). Unity Editor C# scripts assemble the scene; a validation method raycasts the road. Every stage is idempotent with fixed output paths.

**Tech Stack:** Python 3.12 venv (`venv/Scripts/python`): numpy, scipy, rasterio, pyproj, pytest. Unity 6000.3.19f1 + URP, Editor at `C:\Program Files\Unity\Hub\Editor\6000.3.19f1\Editor\Unity.exe`.

**Spec:** `docs/superpowers/specs/2026-09-01-amakeng-hybrid-circuit-design.md`

## Global Constraints

- ENU frame: origin lat0=`1.4064823`, lon0=`103.71559285`, **R=6378137.0** (matches `raw/gpx_004.npz` x/y to <0.2 mm). x=East, y=North, z=Up, metres.
  Formula: `x = radians(lon-lon0)*cos(radians(lat0))*R`, `y = radians(lat-lat0)*R`.
- Unity frame: x=East, y=Up, z=North. **OBJ export writes (−x_enu, z_enu, y_enu)** because Unity's model importer negates X; after import vertices are (East, Up, North).
- Heights: DTM only. Unity y=0 = DTM elevation at track start (`z0`, computed in stage 61, stored in every meta JSON).
- Working grid (all ENU rasters): 0.5 m pixels, x ∈ [−160, 1152], y ∈ [−320, 352] → 2624 × 1344 px. GeoTIFF transform `from_origin(-160, 352, 0.5, 0.5)`, no CRS (frame is ENU by convention). Verified to lie inside both source rasters.
- Road: width 10.0 m all stations (Part A), 2 % crown, 2 m shoulder skirts.
- Paths: intermediates → `work/`, Unity-bound files → `export/`, C# → `unity/`. Unity project: `C:\repos\AmakengCircuit`.
- Run Python as `venv/Scripts/python`; tests as `venv/Scripts/python -m pytest`.
- Sanity invariants (test-enforced): track starts heading east; loop runs anticlockwise (positive shoelace area in ENU); grades < 15 %.
- Do NOT use GPS altitude; do NOT touch splat-era scripts (01–47).
- Commit after every task; commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01EDAAJgh4zLsVw4HfaRakj8`

---

### Task 1: Shared geo helpers + test scaffolding

**Files:**
- Create: `scripts/geo.py`
- Create: `tests/test_geo.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `geo.LAT0, geo.LON0, geo.R` (floats); `geo.latlon_to_enu(lat, lon) -> (x, y)` and `geo.enu_to_latlon(x, y) -> (lat, lon)` (numpy-broadcasting); `geo.GRID = dict(xmin=-160.0, xmax=1152.0, ymin=-320.0, ymax=352.0, px=0.5, width=2624, height=1344)`; `conftest.ROOT` (repo root Path fixture-free constant).

- [ ] **Step 1: Install pytest, create dirs**

```bash
cd "/c/repos/3D from 360" && venv/Scripts/python -m pip install --quiet pytest && mkdir -p tests work export unity
```

- [ ] **Step 2: Write the failing test**

`tests/conftest.py`:
```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
```

`tests/test_geo.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_geo.py -v`
Expected: FAIL (ModuleNotFoundError: geo)

- [ ] **Step 4: Implement `scripts/geo.py`**

```python
"""ENU frame shared by every generator stage. Conventions: spec 'Coordinate conventions'."""
import numpy as np

LAT0 = 1.4064823
LON0 = 103.71559285
R = 6378137.0  # WGS-84 semi-major; matches raw/gpx_004.npz to <0.2 mm

GRID = dict(xmin=-160.0, xmax=1152.0, ymin=-320.0, ymax=352.0,
            px=0.5, width=2624, height=1344)


def latlon_to_enu(lat, lon):
    x = np.radians(np.asarray(lon) - LON0) * np.cos(np.radians(LAT0)) * R
    y = np.radians(np.asarray(lat) - LAT0) * R
    return x, y


def enu_to_latlon(x, y):
    lon = LON0 + np.degrees(np.asarray(x) / (np.cos(np.radians(LAT0)) * R))
    lat = LAT0 + np.degrees(np.asarray(y) / R)
    return lat, lon
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_geo.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/geo.py tests/ && git commit -m "feat: ENU geo helpers + test scaffolding (Part A task 1)"
```

---

### Task 2: Stage 60 — prepare ENU rasters

**Files:**
- Create: `scripts/60_prepare_rasters.py`
- Test: `tests/test_stage60.py`

**Interfaces:**
- Consumes: `geo.GRID`, `geo.enu_to_latlon`; `raw/dtm_clip.tif` (EPSG:4326), `raw/dsm_clip.tif` (projected CRS read from file).
- Produces: `work/dtm_enu.tif`, `work/dsm_enu.tif`, `work/canopy_enu.tif` — float32, one band, 2624×1344, transform `from_origin(-160, 352, 0.5, 0.5)`, crs None, nodata None (fully filled). Row 0 = NORTH (y=352). Canopy = max(dsm−dtm, 0).

- [ ] **Step 1: Write the failing test**

`tests/test_stage60.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage60.py -v`
Expected: FAIL (script missing → CalledProcessError/FileNotFoundError)

- [ ] **Step 3: Implement `scripts/60_prepare_rasters.py`**

```python
"""Stage 60: reproject DTM/DSM into the common 0.5 m ENU grid. All CRS handling lives here."""
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt, map_coordinates

import geo

ROOT = Path(__file__).resolve().parents[1]
G = geo.GRID


def enu_pixel_centers():
    xs = G["xmin"] + (np.arange(G["width"]) + 0.5) * G["px"]
    ys = G["ymax"] - (np.arange(G["height"]) + 0.5) * G["px"]  # row 0 = north
    return np.meshgrid(xs, ys)


def sample_raster(src_path, lat, lon):
    """Bilinear-sample a source raster at lat/lon grids; returns float32 with NaN outside/nodata."""
    with rasterio.open(src_path) as ds:
        band = ds.read(1).astype(np.float64)
        if ds.nodata is not None:
            band[band == ds.nodata] = np.nan
        if ds.crs.to_epsg() == 4326:
            sx, sy = lon, lat
        else:
            tf = pyproj.Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
            sx, sy = tf.transform(lon, lat)
        inv = ~ds.transform
        cols, rows = inv * (sx, sy)
        out = map_coordinates(band, [rows - 0.5, cols - 0.5], order=1, mode="constant", cval=np.nan)
    return out.astype(np.float32)


def fill_nan_nearest(a):
    mask = np.isnan(a)
    if mask.any():
        idx = distance_transform_edt(mask, return_indices=True)[1]
        a = a[tuple(idx)]
    return a


def write(name, data):
    out = ROOT / "work" / name
    out.parent.mkdir(exist_ok=True)
    profile = dict(driver="GTiff", width=G["width"], height=G["height"], count=1,
                   dtype="float32", transform=from_origin(G["xmin"], G["ymax"], G["px"], G["px"]))
    with rasterio.open(out, "w", **profile) as ds:
        ds.write(data, 1)
    print(f"wrote {out}  range {np.nanmin(data):.2f}..{np.nanmax(data):.2f}")


def main():
    X, Y = enu_pixel_centers()
    lat, lon = geo.enu_to_latlon(X, Y)
    dtm = fill_nan_nearest(sample_raster(ROOT / "raw" / "dtm_clip.tif", lat, lon))
    dsm = fill_nan_nearest(sample_raster(ROOT / "raw" / "dsm_clip.tif", lat, lon))
    write("dtm_enu.tif", dtm)
    write("dsm_enu.tif", dsm)
    write("canopy_enu.tif", np.maximum(dsm - dtm, 0.0))


if __name__ == "__main__":
    main()
```

Note: `map_coordinates` pixel-center offset — rasterio's `~transform * (x, y)` returns fractional
col/row where integer+0.5 is a pixel center; subtracting 0.5 converts to `map_coordinates`'
integer-at-center convention.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage60.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/60_prepare_rasters.py tests/test_stage60.py && git commit -m "feat: stage 60 - DTM/DSM/canopy on common ENU grid"
```

---

### Task 3: Stage 61 — centreline

**Files:**
- Create: `scripts/61_centerline.py`
- Test: `tests/test_stage61.py`

**Interfaces:**
- Consumes: `raw/gpx_004.npz` (`x`, `y`, `t`), `work/dtm_enu.tif` (stage 60), `geo`.
- Produces: `work/centerline.json`:
  ```json
  {"z0": <float DTM elev at station 0>,
   "px_per_m": 1.0,
   "stations": [{"s": 0.0, "x": ..., "y": ..., "z": <DTM-z0>,
                 "tx": ..., "ty": <unit tangent>, "w": 10.0,
                 "provisional": false}, ...]}
  ```
  Stations at exactly 1.0 m spacing (`s` = arc length); recorded loop first, then the
  provisional end→start connector (`provisional: true`); the loop closes (last station within
  1.5 m of station 0).

- [ ] **Step 1: Write the failing test**

`tests/test_stage61.py`:
```python
import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


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


def test_grades_and_datum(cl):
    z, s = arr(cl, "z"), arr(cl, "s")
    assert abs(z[0]) < 0.01  # z0 datum: starts at 0
    grade = np.abs(np.diff(z) / np.diff(s))
    assert grade.max() < 0.15
    assert (arr(cl, "w") == 10.0).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage61.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/61_centerline.py`**

```python
"""Stage 61: smoothed 1 m-station centreline from GPX + DTM, with provisional loop connector."""
import json
from pathlib import Path

import numpy as np
import rasterio
from scipy.interpolate import splev, splprep
from scipy.signal import savgol_filter

import geo

ROOT = Path(__file__).resolve().parents[1]
STEP = 1.0
WIDTH = 10.0


def load_track():
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    xy = np.stack([d["x"], d["y"]], axis=1)
    # Collapse parked stretches: drop fixes < 1 m from their predecessor.
    keep = [0]
    for i in range(1, len(xy)):
        if np.linalg.norm(xy[i] - xy[keep[-1]]) >= 1.0:
            keep.append(i)
    return xy[keep]


def smooth_resample(xy):
    # Arc-length parameterised smoothing spline; s tuned for ~1 Hz GPS jitter (~2-3 m).
    dist = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
    tck, _ = splprep([xy[:, 0], xy[:, 1]], u=dist, s=len(xy) * 2.0)
    dense_u = np.linspace(0, dist[-1], int(dist[-1] * 10))
    dx, dy = splev(dense_u, tck)
    dense = np.stack([dx, dy], axis=1)
    seg = np.linalg.norm(np.diff(dense, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s_out = np.arange(0, arc[-1], STEP)
    return np.stack([np.interp(s_out, arc, dense[:, 0]),
                     np.interp(s_out, arc, dense[:, 1])], axis=1)


def hermite_connector(p_end, t_end, p_start, t_start):
    """Cubic Hermite p_end->p_start honouring both tangents; resampled to 1 m."""
    chord = np.linalg.norm(p_start - p_end)
    m0, m1 = t_end * chord, t_start * chord
    u = np.linspace(0, 1, 400)[1:]  # exclude p_end (already a station)
    h00, h10 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u
    h01, h11 = -2 * u**3 + 3 * u**2, u**3 - u**2
    pts = (h00[:, None] * p_end + h10[:, None] * m0
           + h01[:, None] * p_start + h11[:, None] * m1)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s_out = np.arange(STEP, arc[-1], STEP)
    return np.stack([np.interp(s_out, arc, pts[:, 0]),
                     np.interp(s_out, arc, pts[:, 1])], axis=1)


def main():
    loop = smooth_resample(load_track())
    tangents = np.gradient(loop, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True)
    conn = hermite_connector(loop[-1], tangents[-1], loop[0], tangents[0])
    xy = np.vstack([loop, conn])
    n_loop = len(loop)

    with rasterio.open(ROOT / "work" / "dtm_enu.tif") as ds:
        z_abs = np.array([v[0] for v in ds.sample(xy)], dtype=np.float64)
    z_abs = savgol_filter(z_abs, window_length=21, polyorder=2)
    z0 = float(z_abs[0])
    z = z_abs - z0

    tan = np.gradient(xy, axis=0)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])

    stations = [dict(s=round(float(s[i]), 3), x=round(float(xy[i, 0]), 3),
                     y=round(float(xy[i, 1]), 3), z=round(float(z[i]), 3),
                     tx=round(float(tan[i, 0]), 5), ty=round(float(tan[i, 1]), 5),
                     w=WIDTH, provisional=i >= n_loop)
                for i in range(len(xy))]
    out = ROOT / "work" / "centerline.json"
    out.write_text(json.dumps(dict(z0=z0, px_per_m=1.0, stations=stations)))
    print(f"wrote {out}: {len(stations)} stations, {s[-1]:.0f} m "
          f"({len(stations) - n_loop} provisional), z0={z0:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage61.py -v`
Expected: 4 passed. If `test_grades_and_datum` fails on grade, raise the Savitzky-Golay
`window_length` to 31 (grades in the DTM data reach ~12 %; only sampling noise should exceed that).

- [ ] **Step 5: Commit**

```bash
git add scripts/61_centerline.py tests/test_stage61.py && git commit -m "feat: stage 61 - smoothed centreline with provisional loop connector"
```

---

### Task 4: Stage 62 — Unity Terrain heightmap

**Files:**
- Create: `scripts/62_terrain.py`
- Test: `tests/test_stage62.py`

**Interfaces:**
- Consumes: `work/dtm_enu.tif`, `work/centerline.json`.
- Produces:
  - `export/terrain.raw` — 2049×2049 uint16 little-endian, **row 0 = SOUTH** (matches Unity `SetHeights` row order), value = `(h − height_min) / height_range * 65535` where `h` is DTM−z0 after road blending.
  - `export/terrain_meta.json`:
    ```json
    {"resolution": 2049, "size_x": 1312.0, "size_z": 672.0,
     "height_min": ..., "height_range": ...,
     "origin_enu_x": -160.0, "origin_enu_y": -320.0, "z0": ...}
    ```
    Unity terrain GameObject position = `(origin_enu_x, height_min, origin_enu_y)` after the
    ENU→Unity swap (terrain origin is its SW corner).
- Road blending: within 7 m of the centreline, terrain height → station `z − 0.15`; smoothstep
  falloff from 7 m to 14 m back to raw DTM.

- [ ] **Step 1: Write the failing test**

`tests/test_stage62.py`:
```python
import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def meta():
    subprocess.run([PY, str(ROOT / "scripts" / "62_terrain.py")], check=True)
    return json.loads((ROOT / "export" / "terrain_meta.json").read_text())


@pytest.fixture(scope="module")
def heights(meta):
    raw = np.fromfile(ROOT / "export" / "terrain.raw", dtype="<u2")
    h = raw.reshape(meta["resolution"], meta["resolution"]).astype(np.float64)
    return h / 65535.0 * meta["height_range"] + meta["height_min"]


def test_meta_and_shape(meta):
    assert meta["resolution"] == 2049
    assert (meta["size_x"], meta["size_z"]) == (1312.0, 672.0)
    assert meta["height_range"] > 10


def sample(heights, meta, x, y):
    col = (x - meta["origin_enu_x"]) / meta["size_x"] * (meta["resolution"] - 1)
    row = (y - meta["origin_enu_y"]) / meta["size_z"] * (meta["resolution"] - 1)
    return heights[int(round(row)), int(round(col))]


def test_terrain_blended_to_road(heights, meta):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    errs = [sample(heights, meta, st["x"], st["y"]) - (st["z"] - 0.15)
            for st in cl["stations"][::25]]
    assert np.abs(np.array(errs)).max() < 0.35  # heightmap px ~0.64 m -> small interp error


def test_far_terrain_matches_dtm(heights, meta):
    import rasterio
    with rasterio.open(ROOT / "work" / "dtm_enu.tif") as ds:
        dtm = ds.read(1)
    # NE-area probe point >14 m from any station: compare within 1 m
    x, y = 1100.0, 300.0
    row = int((meta["origin_enu_y"] + meta["size_z"] - y) / 0.5)  # dtm row 0 = north
    col = int((x - meta["origin_enu_x"]) / 0.5)
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    d = min(np.hypot(st["x"] - x, st["y"] - y) for st in cl["stations"])
    assert d > 14
    assert abs(sample(heights, meta, x, y) - (dtm[row, col] - meta["z0"])) < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage62.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/62_terrain.py`**

```python
"""Stage 62: DTM -> Unity Terrain RAW, terrain blended to road profile under the corridor."""
import json
from pathlib import Path

import numpy as np
import rasterio
from scipy.spatial import cKDTree

import geo

ROOT = Path(__file__).resolve().parents[1]
RES = 2049
BLEND_IN, BLEND_OUT = 7.0, 14.0
ROAD_DROP = 0.15


def main():
    g = geo.GRID
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    z0 = cl["z0"]
    st_xy = np.array([[st["x"], st["y"]] for st in cl["stations"]])
    st_z = np.array([st["z"] for st in cl["stations"]])

    with rasterio.open(ROOT / "work" / "dtm_enu.tif") as ds:
        dtm = ds.read(1).astype(np.float64) - z0  # row 0 = north

    # Heightmap sample grid (row 0 = south for Unity).
    xs = np.linspace(g["xmin"], g["xmax"], RES)
    ys = np.linspace(g["ymin"], g["ymax"], RES)
    X, Y = np.meshgrid(xs, ys)
    cols = np.clip((X - g["xmin"]) / g["px"], 0, g["width"] - 1).astype(int)
    rows = np.clip((g["ymax"] - Y) / g["px"], 0, g["height"] - 1).astype(int)
    h = dtm[rows, cols]

    dist, idx = cKDTree(st_xy).query(np.stack([X.ravel(), Y.ravel()], axis=1),
                                     distance_upper_bound=BLEND_OUT)
    dist, idx = dist.reshape(X.shape), idx.reshape(X.shape)
    near = np.isfinite(dist)
    road_h = np.where(near, st_z[np.clip(idx, 0, len(st_z) - 1)] - ROAD_DROP, 0.0)
    t = np.clip((dist - BLEND_IN) / (BLEND_OUT - BLEND_IN), 0.0, 1.0)
    w = np.where(near, 1.0 - t * t * (3 - 2 * t), 0.0)  # smoothstep: 1 inside, 0 outside
    h = w * road_h + (1.0 - w) * h

    hmin, hmax = float(h.min()), float(h.max())
    hrange = hmax - hmin
    (ROOT / "export").mkdir(exist_ok=True)
    ((h - hmin) / hrange * 65535).astype("<u2").tofile(ROOT / "export" / "terrain.raw")
    meta = dict(resolution=RES, size_x=g["xmax"] - g["xmin"], size_z=g["ymax"] - g["ymin"],
                height_min=hmin, height_range=hrange,
                origin_enu_x=g["xmin"], origin_enu_y=g["ymin"], z0=z0)
    (ROOT / "export" / "terrain_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"terrain.raw {RES}x{RES}, heights {hmin:.2f}..{hmax:.2f} (rel z0={z0:.2f})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage62.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/62_terrain.py tests/test_stage62.py && git commit -m "feat: stage 62 - Unity terrain RAW with road-corridor blending"
```

---

### Task 5: Stage 63 — road mesh OBJ + pipeline runner

**Files:**
- Create: `scripts/63_road_mesh.py`
- Create: `scripts/run_generate.sh`
- Test: `tests/test_stage63.py`

**Interfaces:**
- Consumes: `work/centerline.json`.
- Produces:
  - `export/road.obj` — objects `road` and `road_provisional`, materials `gravel` /
    `gravel_provisional` (mtllib `road.mtl`, also written). Vertices in **Unity-import frame**:
    `(−x_enu, z_station + profile, y_enu)`. UVs: `u = (offset/width)+0.5`, `v = s/4.0`.
    Winding CCW seen from +z_enu (up) BEFORE the x-flip; Unity's importer flip restores
    correct up-facing after negation.
  - `export/road_meta.json`:
    ```json
    {"z0": ..., "start": {"x_unity": ..., "y_unity": ..., "z_unity": ...,
                          "heading_deg": <Unity Y euler, 90=east>},
     "stations_unity": [[x, y, z], ...]}   // every 5th station, Unity frame (+x East)
    ```
- Cross-section per station (half-width `hw = w/2`, crown 2 %, shoulders):
  offsets `[-hw-2, -hw, -hw/2, 0, hw/2, hw, hw+2]`,
  dz `[-0.02*hw-0.30, -0.02*hw, -0.01*hw, 0, -0.01*hw, -0.02*hw, -0.02*hw-0.30]`.
  Left of tangent = normal `(-ty, tx)`.

- [ ] **Step 1: Write the failing test**

`tests/test_stage63.py`:
```python
import json
import subprocess
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def objdata():
    subprocess.run([PY, str(ROOT / "scripts" / "63_road_mesh.py")], check=True)
    verts, faces, objects = [], [], set()
    for line in (ROOT / "export" / "road.obj").read_text().splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            verts.append([float(v) for v in p[1:4]])
        elif p[0] == "f":
            faces.append([int(tok.split("/")[0]) - 1 for tok in p[1:4]])
        elif p[0] == "o":
            objects.add(p[1])
    return np.array(verts), np.array(faces), objects


def test_structure(objdata):
    verts, faces, objects = objdata
    assert objects == {"road", "road_provisional"}
    assert len(verts) > 10000 and len(faces) > 20000


def test_no_degenerate_faces_and_up_normals(objdata):
    verts, faces, _ = objdata
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    n = np.cross(b - a, c - a)
    areas = np.linalg.norm(n, axis=1)
    assert areas.min() > 1e-6
    # OBJ frame has -x; flip back to Unity/world then check +y (up) normals
    n[:, 0] *= -1
    assert (n[:, 1] / areas > 0.5).all()


def test_width(objdata):
    verts, faces, _ = objdata
    # 7 verts per station in emission order; edge-to-edge (idx 1 to 5) = 10 m
    row0 = verts[0:7]
    assert abs(np.linalg.norm(row0[5] - row0[1]) - 10.0) < 0.05


def test_meta_start_pose():
    meta = json.loads((ROOT / "export" / "road_meta.json").read_text())
    assert abs(meta["start"]["y_unity"]) < 0.2      # z datum
    assert 45 < meta["start"]["heading_deg"] < 135  # east
    assert len(meta["stations_unity"]) > 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage63.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/63_road_mesh.py`**

```python
"""Stage 63: crowned road ribbon OBJ from the centreline. Vertices pre-flipped for Unity import."""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def cross_section(hw):
    offs = np.array([-hw - 2, -hw, -hw / 2, 0, hw / 2, hw, hw + 2])
    dz = np.array([-0.02 * hw - 0.30, -0.02 * hw, -0.01 * hw, 0,
                   -0.01 * hw, -0.02 * hw, -0.02 * hw - 0.30])
    return offs, dz


def main():
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = cl["stations"]
    nprof = 7
    verts, uvs, rows_prov = [], [], []
    for st in sts:
        offs, dz = cross_section(st["w"] / 2)
        nx, ny = -st["ty"], st["tx"]  # left normal in ENU
        for o, d in zip(offs, dz):
            ex, ey, ez = st["x"] + nx * o, st["y"] + ny * o, st["z"] + d
            verts.append((-ex, ez, ey))  # Unity-import frame (importer negates x back)
            uvs.append((o / st["w"] + 0.5, st["s"] / 4.0))
        rows_prov.append(st["provisional"])

    def face_rows(i):  # quads between station i and i+1 -> 2 tris each, CCW from above in ENU
        f = []
        for j in range(nprof - 1):
            a, b = i * nprof + j, i * nprof + j + 1
            c, d = (i + 1) * nprof + j, (i + 1) * nprof + j + 1
            f += [(a, c, b), (b, c, d)]
        return f

    faces_road, faces_prov = [], []
    for i in range(len(sts) - 1):
        (faces_prov if rows_prov[i] or rows_prov[i + 1] else faces_road).extend(face_rows(i))

    with open(ROOT / "export" / "road.mtl", "w") as m:
        m.write("newmtl gravel\nKd 0.45 0.42 0.38\n\n"
                "newmtl gravel_provisional\nKd 0.65 0.35 0.35\n")
    with open(ROOT / "export" / "road.obj", "w") as f:
        f.write("mtllib road.mtl\n")
        for v in verts:
            f.write(f"v {v[0]:.3f} {v[1]:.3f} {v[2]:.3f}\n")
        for u in uvs:
            f.write(f"vt {u[0]:.4f} {u[1]:.4f}\n")
        for name, mtl, faces in (("road", "gravel", faces_road),
                                 ("road_provisional", "gravel_provisional", faces_prov)):
            f.write(f"o {name}\nusemtl {mtl}\n")
            for a, b, c in faces:
                f.write(f"f {a+1}/{a+1} {b+1}/{b+1} {c+1}/{c+1}\n")

    st0 = sts[0]
    heading = math.degrees(math.atan2(st0["tx"], st0["ty"]))  # Unity yaw: 0=N(+z), 90=E(+x)
    meta = dict(z0=cl["z0"],
                start=dict(x_unity=st0["x"], y_unity=st0["z"], z_unity=st0["y"],
                           heading_deg=heading),
                stations_unity=[[st["x"], st["z"], st["y"]] for st in sts[::5]])
    (ROOT / "export" / "road_meta.json").write_text(json.dumps(meta))
    print(f"road.obj: {len(verts)} verts, {len(faces_road)} road + {len(faces_prov)} provisional tris")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage63.py -v`
Expected: 4 passed

- [ ] **Step 5: Create `scripts/run_generate.sh`**

```bash
#!/usr/bin/env bash
# Run all generator stages in order; stop on first failure.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=venv/Scripts/python
$PY scripts/60_prepare_rasters.py
$PY scripts/61_centerline.py
$PY scripts/62_terrain.py
$PY scripts/63_road_mesh.py
echo "generate: all stages OK"
```

Run: `bash scripts/run_generate.sh` — Expected: all four stages print their outputs, then `generate: all stages OK`.

- [ ] **Step 6: Run the full test suite**

Run: `venv/Scripts/python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add scripts/63_road_mesh.py scripts/run_generate.sh tests/test_stage63.py && git commit -m "feat: stage 63 - road ribbon OBJ + pipeline runner"
```

---

### Task 6: Unity project + sync script

**Files:**
- Create: `scripts/70_sync_unity.py`
- Create (Unity side, by user action): project `C:\repos\AmakengCircuit`

**Interfaces:**
- Produces: files copied to `C:\repos\AmakengCircuit\Assets\Amakeng\Generated\` (all of `export/`)
  and `...\Assets\Amakeng\Editor\` (all of `unity/*.cs`). Later tasks rely on these exact
  target folders. `terrain.raw` is copied as `terrain.raw.bytes` (so Unity doesn't try to
  import it as an unsupported asset — the Editor script reads it via `File.ReadAllBytes`
  from the asset path).

- [ ] **Step 1: USER ACTION — create the Unity project**

Ask the user to: open Unity Hub → New project → editor 6000.3.19f1 → **Universal 3D**
(URP) template → name `AmakengCircuit`, location `C:\repos` → Create, then close Unity.
Verify from shell: `ls "/c/repos/AmakengCircuit/Assets" "/c/repos/AmakengCircuit/ProjectSettings/ProjectVersion.txt"`
(This is a checkpoint step — pause execution and wait for the user.)

- [ ] **Step 2: Write `scripts/70_sync_unity.py`**

```python
"""Copy generated exports + Editor scripts into the Unity project."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITY = Path(r"C:\repos\AmakengCircuit\Assets\Amakeng")


def main():
    gen, ed = UNITY / "Generated", UNITY / "Editor"
    gen.mkdir(parents=True, exist_ok=True)
    ed.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "export").iterdir():
        if f.is_file():
            dest = gen / (f.name + ".bytes" if f.suffix == ".raw" else f.name)
            shutil.copy2(f, dest)
            print(f"  {f.name} -> {dest}")
    for f in (ROOT / "unity").glob("*.cs"):
        shutil.copy2(f, ed / f.name)
        print(f"  {f.name} -> {ed / f.name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run and verify**

Run: `venv/Scripts/python scripts/70_sync_unity.py && ls "/c/repos/AmakengCircuit/Assets/Amakeng/Generated"`
Expected: `road.obj`, `road.mtl`, `road_meta.json`, `terrain.raw.bytes`, `terrain_meta.json` listed.

- [ ] **Step 4: Commit**

```bash
git add scripts/70_sync_unity.py && git commit -m "feat: Unity sync script"
```

---

### Task 7: BuildAmakeng.cs — scene assembly (terrain + road)

**Files:**
- Create: `unity/BuildAmakeng.cs`

**Interfaces:**
- Consumes: `Assets/Amakeng/Generated/terrain.raw.bytes`, `terrain_meta.json`, `road.obj`, `road_meta.json` (Task 6 layout).
- Produces: menu **Amakeng > Build Scene** and static method `Amakeng.BuildAmakeng.BuildScene()`
  (batchmode-callable). Creates/overwrites `Assets/Amakeng/Amakeng.unity` containing
  `[GEN] Terrain` (Terrain + TerrainCollider) and `[GEN] Road` (imported model + MeshCollider
  per child mesh). Also `Amakeng.BuildAmakeng.ValidateRoad()` used in Task 8.

- [ ] **Step 1: Write `unity/BuildAmakeng.cs`**

```csharp
// Assembles the Amakeng scene from generated data. Menu: Amakeng > Build Scene.
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Amakeng
{
    [System.Serializable]
    public class TerrainMeta
    {
        public int resolution;
        public float size_x, size_z, height_min, height_range, origin_enu_x, origin_enu_y, z0;
    }

    [System.Serializable]
    public class StartPose { public float x_unity, y_unity, z_unity, heading_deg; }

    [System.Serializable]
    public class RoadMeta { public float z0; public StartPose start; public float[][] stations_unity; }

    public static class BuildAmakeng
    {
        const string GenDir = "Assets/Amakeng/Generated";
        public const string ScenePath = "Assets/Amakeng/Amakeng.unity";

        [MenuItem("Amakeng/Build Scene")]
        public static void BuildScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            BuildTerrain();
            BuildRoad();
            EditorSceneManager.SaveScene(scene, ScenePath);
            Debug.Log("Amakeng: scene built and saved to " + ScenePath);
        }

        static T LoadJson<T>(string file)
        {
            // JsonUtility can't parse float[][]; stations are re-read manually where needed.
            return JsonUtility.FromJson<T>(File.ReadAllText(Path.Combine(GenDir, file)));
        }

        static void Replace(string name)
        {
            var old = GameObject.Find(name);
            if (old != null) Object.DestroyImmediate(old);
        }

        static void BuildTerrain()
        {
            Replace("[GEN] Terrain");
            var meta = LoadJson<TerrainMeta>("terrain_meta.json");
            int res = meta.resolution;
            var bytes = File.ReadAllBytes(Path.Combine(GenDir, "terrain.raw.bytes"));
            var heights = new float[res, res]; // [row=z, col=x], row 0 = south: matches raw layout
            for (int r = 0; r < res; r++)
                for (int c = 0; c < res; c++)
                {
                    int i = (r * res + c) * 2;
                    heights[r, c] = (bytes[i] | (bytes[i + 1] << 8)) / 65535f;
                }

            var td = new TerrainData();
            td.heightmapResolution = res;
            td.size = new Vector3(meta.size_x, meta.height_range, meta.size_z);
            td.SetHeights(0, 0, heights);
            AssetDatabase.CreateAsset(td, "Assets/Amakeng/TerrainData.asset");

            var go = Terrain.CreateTerrainGameObject(td);
            go.name = "[GEN] Terrain";
            go.transform.position = new Vector3(meta.origin_enu_x, meta.height_min, meta.origin_enu_y);
        }

        static void BuildRoad()
        {
            Replace("[GEN] Road");
            AssetDatabase.ImportAsset(GenDir + "/road.obj", ImportAssetOptions.ForceUpdate);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(GenDir + "/road.obj");
            var root = (GameObject)PrefabUtility.InstantiatePrefab(model);
            root.name = "[GEN] Road";
            root.transform.position = Vector3.zero;

            var shader = Shader.Find("Universal Render Pipeline/Lit");
            var gravel = new Material(shader) { color = new Color(0.45f, 0.42f, 0.38f) };
            gravel.mainTexture = MakeGravelTexture(false);
            var prov = new Material(shader) { color = new Color(0.70f, 0.40f, 0.40f) };
            prov.mainTexture = MakeGravelTexture(true);
            AssetDatabase.CreateAsset(gravel, "Assets/Amakeng/Gravel.mat");
            AssetDatabase.CreateAsset(prov, "Assets/Amakeng/GravelProvisional.mat");

            foreach (var mf in root.GetComponentsInChildren<MeshFilter>())
            {
                var mc = mf.gameObject.AddComponent<MeshCollider>();
                mc.sharedMesh = mf.sharedMesh;
                var mr = mf.GetComponent<MeshRenderer>();
                bool isProv = mf.gameObject.name.Contains("provisional");
                mr.sharedMaterial = isProv ? prov : gravel;
            }
        }

        static Texture2D MakeGravelTexture(bool tinted)
        {
            var tex = new Texture2D(256, 256);
            var rng = new System.Random(42);
            for (int y = 0; y < 256; y++)
                for (int x = 0; x < 256; x++)
                {
                    float v = 0.55f + (float)rng.NextDouble() * 0.25f;
                    tex.SetPixel(x, y, tinted ? new Color(v, v * 0.6f, v * 0.6f)
                                              : new Color(v * 0.95f, v * 0.92f, v * 0.85f));
                }
            tex.Apply();
            return tex;
        }

        // Raycast the road along the centreline; used by Task 8 validation.
        public static void ValidateRoad()
        {
            var lines = File.ReadAllText(Path.Combine(GenDir, "road_meta.json"));
            var stations = MiniJsonStations(lines);
            int bad = 0;
            foreach (var s in stations)
            {
                var origin = new Vector3(s.x, s.y + 50f, s.z);
                if (!Physics.Raycast(origin, Vector3.down, out var hit, 100f) ||
                    Mathf.Abs(hit.point.y - s.y) > 0.5f)
                    bad++;
            }
            Debug.Log($"Amakeng validate: {stations.Count - bad}/{stations.Count} stations OK");
            if (bad > 0) throw new System.Exception($"Amakeng validate FAILED: {bad} bad stations");
        }

        static System.Collections.Generic.List<Vector3> MiniJsonStations(string json)
        {
            // stations_unity: [[x,y,z],...] - tiny manual parse (JsonUtility can't do nested arrays)
            var outp = new System.Collections.Generic.List<Vector3>();
            int i = json.IndexOf("\"stations_unity\"");
            i = json.IndexOf('[', i) + 1;
            while (true)
            {
                int a = json.IndexOf('[', i);
                if (a < 0) break;
                int b = json.IndexOf(']', a);
                var parts = json.Substring(a + 1, b - a - 1).Split(',');
                outp.Add(new Vector3(float.Parse(parts[0]), float.Parse(parts[1]), float.Parse(parts[2])));
                i = b + 1;
                if (json[i] == ']') break;
            }
            return outp;
        }
    }
}
```

- [ ] **Step 2: Sync and build headless**

```bash
cd "/c/repos/3D from 360" && venv/Scripts/python scripts/70_sync_unity.py
"/c/Program Files/Unity/Hub/Editor/6000.3.19f1/Editor/Unity.exe" -batchmode -quit \
  -projectPath "C:\repos\AmakengCircuit" -executeMethod Amakeng.BuildAmakeng.BuildScene \
  -logFile "C:\repos\AmakengCircuit\build.log"; tail -30 "/c/repos/AmakengCircuit/build.log"
```
Expected: log contains `Amakeng: scene built and saved` and exits 0. If compile errors appear
in the log, fix `unity/BuildAmakeng.cs`, re-run sync + this command.

- [ ] **Step 3: Commit**

```bash
git add unity/BuildAmakeng.cs && git commit -m "feat: Unity scene assembly - terrain + road with colliders"
```

---

### Task 8: Vehicle + validation + drive checkpoint

**Files:**
- Create: `unity/VehicleController.cs` (runtime — sync copies it to `Editor/`; move: this file
  goes to `Assets/Amakeng/` root instead, see Step 2 note)
- Create: `unity/BuildVehicle.cs`
- Modify: `scripts/70_sync_unity.py` (route runtime scripts outside `Editor/`)

**Interfaces:**
- Consumes: `road_meta.json` start pose; scene from Task 7.
- Produces: menu **Amakeng > Build Vehicle** / `Amakeng.BuildVehicle.Build()` — adds `[GEN] Vehicle`
  (Rigidbody + 4 WheelColliders + follow camera) at the start pose to the saved scene.
  Menu **Amakeng > Validate Road** runs `BuildAmakeng.ValidateRoad()`.

- [ ] **Step 1: Write `unity/VehicleController.cs`** (runtime component)

```csharp
// Minimal WheelCollider vehicle: arrows/WASD, rear drive, front steer, speed readout.
using UnityEngine;

namespace Amakeng
{
    public class VehicleController : MonoBehaviour
    {
        public WheelCollider fl, fr, rl, rr;
        public Transform[] wheelVisuals = new Transform[4];
        public float motorTorque = 1200f, maxSteer = 28f, brakeTorque = 2500f;
        Rigidbody rb;

        void Start()
        {
            rb = GetComponent<Rigidbody>();
            rb.centerOfMass = new Vector3(0, -0.6f, 0);
        }

        void FixedUpdate()
        {
            float steer = Input.GetAxis("Horizontal") * maxSteer;
            float drive = Input.GetAxis("Vertical") * motorTorque;
            bool brake = Input.GetKey(KeyCode.Space);
            fl.steerAngle = fr.steerAngle = steer;
            rl.motorTorque = rr.motorTorque = brake ? 0 : drive;
            fl.brakeTorque = fr.brakeTorque = rl.brakeTorque = rr.brakeTorque = brake ? brakeTorque : 0;
            var wcs = new[] { fl, fr, rl, rr };
            for (int i = 0; i < 4; i++)
            {
                if (wheelVisuals[i] == null) continue;
                wcs[i].GetWorldPose(out var p, out var q);
                wheelVisuals[i].SetPositionAndRotation(p, q);
            }
        }

        void OnGUI()
        {
            GUI.Label(new Rect(10, 10, 200, 30),
                      $"{rb.linearVelocity.magnitude * 3.6f:F0} km/h", new GUIStyle
                      { fontSize = 24, normal = { textColor = Color.white } });
        }
    }

    public class FollowCamera : MonoBehaviour
    {
        public Transform target;
        public Vector3 offset = new Vector3(0, 2.2f, -6f);

        void LateUpdate()
        {
            if (target == null) return;
            var want = target.TransformPoint(offset);
            transform.position = Vector3.Lerp(transform.position, want, 0.1f);
            transform.LookAt(target.position + Vector3.up * 1.2f);
        }
    }
}
```

- [ ] **Step 2: Update `scripts/70_sync_unity.py`** — runtime scripts must NOT live under `Editor/`.
Replace the `*.cs` copy loop with:

```python
    RUNTIME = {"VehicleController.cs"}
    for f in (ROOT / "unity").glob("*.cs"):
        dest_dir = (UNITY if f.name in RUNTIME else ed)
        shutil.copy2(f, dest_dir / f.name)
        print(f"  {f.name} -> {dest_dir / f.name}")
```
(also remove a stale `Editor/VehicleController.cs` if one was synced earlier).

- [ ] **Step 3: Write `unity/BuildVehicle.cs`**

```csharp
// Builds the drivable vehicle at the road start pose. Menu: Amakeng > Build Vehicle.
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Amakeng
{
    public static class BuildVehicle
    {
        [MenuItem("Amakeng/Build Vehicle")]
        public static void Build()
        {
            EditorSceneManager.OpenScene(BuildAmakeng.ScenePath);
            var old = GameObject.Find("[GEN] Vehicle");
            if (old != null) Object.DestroyImmediate(old);

            var meta = JsonUtility.FromJson<RoadMeta>(
                File.ReadAllText("Assets/Amakeng/Generated/road_meta.json"));

            var root = new GameObject("[GEN] Vehicle");
            root.transform.SetPositionAndRotation(
                new Vector3(meta.start.x_unity, meta.start.y_unity + 1.0f, meta.start.z_unity),
                Quaternion.Euler(0, meta.start.heading_deg, 0));

            var body = GameObject.CreatePrimitive(PrimitiveType.Cube);
            body.name = "Body";
            body.transform.SetParent(root.transform, false);
            body.transform.localScale = new Vector3(1.9f, 0.9f, 4.2f);
            body.transform.localPosition = new Vector3(0, 0.7f, 0);

            var rb = root.AddComponent<Rigidbody>();
            rb.mass = 1500f;
            var vc = root.AddComponent<VehicleController>();

            var wheels = new WheelCollider[4];
            var pos = new[] { new Vector3(-0.8f, 0.35f, 1.4f), new Vector3(0.8f, 0.35f, 1.4f),
                              new Vector3(-0.8f, 0.35f, -1.4f), new Vector3(0.8f, 0.35f, -1.4f) };
            for (int i = 0; i < 4; i++)
            {
                var w = new GameObject("Wheel" + i);
                w.transform.SetParent(root.transform, false);
                w.transform.localPosition = pos[i];
                var wc = w.AddComponent<WheelCollider>();
                wc.radius = 0.35f;
                wc.suspensionDistance = 0.25f;
                var spring = wc.suspensionSpring;
                spring.spring = 45000f; spring.damper = 4000f;
                wc.suspensionSpring = spring;
                wheels[i] = wc;

                var vis = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                Object.DestroyImmediate(vis.GetComponent<Collider>());
                vis.transform.SetParent(root.transform, false);
                vis.transform.localScale = new Vector3(0.7f, 0.12f, 0.7f);
                vis.transform.localRotation = Quaternion.Euler(0, 0, 90);
                vc.wheelVisuals[i] = vis.transform;
            }
            vc.fl = wheels[0]; vc.fr = wheels[1]; vc.rl = wheels[2]; vc.rr = wheels[3];

            var cam = Camera.main ?? new GameObject("Main Camera").AddComponent<Camera>();
            cam.gameObject.tag = "MainCamera";
            var fc = cam.gameObject.AddComponent<FollowCamera>();
            fc.target = root.transform;

            EditorSceneManager.MarkSceneDirty(root.scene);
            EditorSceneManager.SaveScene(root.scene);
            Debug.Log("Amakeng: vehicle built at start pose");
        }

        [MenuItem("Amakeng/Validate Road")]
        public static void Validate()
        {
            EditorSceneManager.OpenScene(BuildAmakeng.ScenePath);
            BuildAmakeng.ValidateRoad();
        }
    }
}
```

- [ ] **Step 4: Sync, build vehicle, validate headless**

```bash
cd "/c/repos/3D from 360" && venv/Scripts/python scripts/70_sync_unity.py
U="/c/Program Files/Unity/Hub/Editor/6000.3.19f1/Editor/Unity.exe"
"$U" -batchmode -quit -projectPath "C:\repos\AmakengCircuit" -executeMethod Amakeng.BuildVehicle.Build -logFile "C:\repos\AmakengCircuit\vehicle.log"; tail -5 "/c/repos/AmakengCircuit/vehicle.log"
"$U" -batchmode -quit -projectPath "C:\repos\AmakengCircuit" -executeMethod Amakeng.BuildVehicle.Validate -logFile "C:\repos\AmakengCircuit\validate.log"; grep "Amakeng validate" "/c/repos/AmakengCircuit/validate.log"
```
Expected: `vehicle built at start pose`; validation reports all (or ≥ 99 %) stations OK and
does not throw. Note: `Physics.Raycast` in batchmode edit mode works against saved scene
colliders; if it reports 0 hits, open the scene in the editor and run *Amakeng > Validate Road*
from the menu instead.

- [ ] **Step 5: Commit**

```bash
git add unity/ scripts/70_sync_unity.py && git commit -m "feat: WheelCollider vehicle + road validation"
```

- [ ] **Step 6: USER CHECKPOINT — drive it**

Ask the user to open `AmakengCircuit` in Unity, open `Assets/Amakeng/Amakeng.unity`, press
Play, and drive the loop. Acceptance (from spec): full loop without falling through or
bottoming out; grades feel like the DTM profile (max ~9–12 %); provisional connector visibly
red-tinted; roughly 60 fps. Collect feedback (vehicle tuning, road feel, terrain seams) as
input to follow-up fixes before Part B.

---

## Self-Review Notes

- Spec coverage: stages 60–63 (Tasks 2–5), runner (Task 5), Unity assembly + gravel material +
  colliders (Task 7), vehicle + spawn + camera + speed readout (Task 8), validation raycast
  (Tasks 7/8), idempotent `[GEN]` parents (Replace() in build scripts), clearing widths and
  stages 64–65 are Part B/C — out of scope here. Per-station `w` field already exists for the
  Part B width feedback.
- The `RoadMeta.stations_unity` field is parsed manually (JsonUtility limitation) — covered in
  `MiniJsonStations`; `BuildVehicle` only uses `start`, which JsonUtility handles.
- Type consistency: `geo.GRID` keys used identically in stages 60/62; `centerline.json` keys
  (`s,x,y,z,tx,ty,w,provisional`, top-level `z0`) consistent across 61/62/63 and tests;
  Unity meta field names match the C# `[Serializable]` classes exactly (snake_case).
