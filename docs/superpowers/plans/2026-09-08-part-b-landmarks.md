# Part B — Landmarks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks 3 and 5 are CONTROLLER/USER tasks (vision scan, review) — not implementer dispatches.

**Goal:** Landmark proxies (sheds, barriers, signboards, gates, fences, clearings) placed in the Unity scene at positions derived from the drive video, plus the clearing-driven road-width feedback into stages 61–63.

**Architecture:** ffmpeg samples the 8K equirect video at 1 fps into scan images; vision agents propose landmarks per batch; a merge stage clusters sightings into landmark candidates with ENU positions; the user reviews an HTML contact sheet; approved landmarks export to JSON consumed by a Unity Editor placement script (proxies + fence polylines + photo-textured signs). Clearings feed a width profile that re-runs stages 61–63.

**Tech Stack:** ffmpeg (with v360 filter), Python venv (numpy, scipy, rasterio), pytest, Unity 6000.3.19f1 + URP. Unity-side verification via the unity-editor-mcp tools (editor open) with headless CLI fallback.

**Spec:** `docs/superpowers/specs/2026-09-01-amakeng-hybrid-circuit-design.md` (Part B = stage 64 + PlaceLandmarks; width feedback; phasing §Phasing)

## Global Constraints

- ENU frame per `scripts/geo.py` (LAT0 1.4064823, LON0 103.71559285, R 6378137.0); Unity = (x_enu→x, z→y, y_enu→z); heading/compass azimuth: 0°=North(+y_enu), 90°=East(+x_enu), i.e. `degrees(atan2(dx, dy))`.
- Video↔GPS: video second v (1 fps sample) → GPS t = v + 2.0 s (verified `dt_video_to_gps_s` = 2.0); 10 fps global frame n = round(v·10)+1; sections from `colmap_db/gpx/section_transforms.json` key `sections` (s01–s18, `frames: [start, end]`).
- Parked GPS gaps (skip): t 39–53, 86–94, 222–230, 307–367, 380–392 → video seconds 37–51, 84–92, 220–228, 305–365, 378–390.
- Video: `raw/3A_AMA North 360_.mp4`, 7680×3840 equirect, 647.4 s.
- Landmark classes (exact strings): `shed`, `barrier`, `signboard`, `gate`, `fence`, `clearing`.
- Distance buckets → lateral metres: near=8, medium=15, far=25.
- Road width: base 10.0 m; clearings widen per-station `w` (cap 16 m); stage-63 sweep half-extent = w/2+2, so the curvature guard must use the WIDENED profile.
- Python: `venv/Scripts/python` from repo root; Git Bash /c/... paths. Unity project `C:\repos\AmakengCircuit`; repo `unity/*.cs` reach it via `venv/Scripts/python scripts/70_sync_unity.py`.
- Commit after every task; messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01AF1cy5Qz2ZhiHcRmRSQxia`

---

### Task 1: Stage 64 — frame sampling + index

**Files:**
- Create: `scripts/64_sample_frames.py`
- Test: `tests/test_stage64.py`

**Interfaces:**
- Consumes: `raw/3A_AMA North 360_.mp4`, `raw/gpx_004.npz`, `colmap_db/gpx/section_transforms.json`, `scripts/geo.py` conventions.
- Produces: `work/frames/f{v:04d}.jpg` (2048×1024 equirect, v = video second) for every non-parked second in [0, 646]; `work/frames/index.json`:
  ```json
  {"frames": [{"v": 0, "t": 2.0, "x": ..., "y": ..., "heading_deg": ..., "section": "s01"}, ...]}
  ```
  (x, y = ENU interp of gpx at t; heading_deg = compass tangent; section = the s01–s18 range containing frame n=v·10+1, or "" if none.)

- [ ] **Step 1: Write the failing test**

`tests/test_stage64.py`:
```python
import json
import subprocess
from pathlib import Path
import numpy as np
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")
PARKED = [(37, 51), (84, 92), (220, 228), (305, 365), (378, 390)]


@pytest.fixture(scope="module")
def index():
    subprocess.run([PY, str(ROOT / "scripts" / "64_sample_frames.py")], check=True)
    return json.loads((ROOT / "work" / "frames" / "index.json").read_text())["frames"]


def test_frames_exist_and_skip_parked(index):
    vs = [f["v"] for f in index]
    assert len(vs) == len(set(vs)) and vs == sorted(vs)
    for a, b in PARKED:
        assert not any(a <= v <= b for v in vs)
    assert 480 < len(vs) < 560  # 647 s minus ~120 parked
    for f in index[::50]:
        assert (ROOT / "work" / "frames" / f"f{f['v']:04d}.jpg").exists()


def test_index_fields(index):
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    for f in index[::25]:
        assert abs(f["t"] - (f["v"] + 2.0)) < 1e-6
        assert d["x"].min() - 1 <= f["x"] <= d["x"].max() + 1
        assert -180 <= f["heading_deg"] <= 180
    assert {f["section"] for f in index} >= {"s01", "s18"}


def test_start_heads_east(index):
    first = index[1]
    assert 45 < first["heading_deg"] < 135  # circuit starts eastward
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage64.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/64_sample_frames.py`**

```python
"""Stage 64: 1 fps equirect scan frames + per-frame GPS/heading/section index."""
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PARKED = [(37, 51), (84, 92), (220, 228), (305, 365), (378, 390)]
DT = 2.0
DURATION = 647


def parked(v):
    return any(a <= v <= b for a, b in PARKED)


def main():
    out = ROOT / "work" / "frames"
    out.mkdir(parents=True, exist_ok=True)
    # One pass: 1 fps, downscale, number by output index; map index->second after.
    # -r 1 after -i selects one frame per second of input timeline.
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"),
           "-vf", "fps=1,scale=2048:1024", "-q:v", "3", str(out / "all_%04d.jpg")]
    subprocess.run(cmd, check=True)
    # all_0001.jpg is at v=0; rename kept, delete parked.
    d = np.load(ROOT / "raw" / "gpx_004.npz")
    dx = np.gradient(d["x"]); dy = np.gradient(d["y"])
    secs = json.loads((ROOT / "colmap_db" / "gpx" / "section_transforms.json").read_text())["sections"]

    frames = []
    for f in sorted(out.glob("all_*.jpg")):
        v = int(f.stem.split("_")[1]) - 1
        if v > DURATION or parked(v):
            f.unlink()
            continue
        t = v + DT
        x = float(np.interp(t, d["t"], d["x"]))
        y = float(np.interp(t, d["t"], d["y"]))
        hx = float(np.interp(t, d["t"], dx))
        hy = float(np.interp(t, d["t"], dy))
        heading = float(np.degrees(np.arctan2(hx, hy)))
        n10 = v * 10 + 1
        sec = next((k for k, s in secs.items()
                    if isinstance(s, dict) and "frames" in s and s["frames"][0] <= n10 <= s["frames"][1]), "")
        f.rename(out / f"f{v:04d}.jpg")
        frames.append(dict(v=v, t=t, x=round(x, 2), y=round(y, 2),
                           heading_deg=round(heading, 1), section=sec))
    (out / "index.json").write_text(json.dumps(dict(frames=frames)))
    print(f"{len(frames)} scan frames -> {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage64.py -v` (extraction takes a few minutes on the 10 GB file)
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/64_sample_frames.py tests/test_stage64.py && git commit -m "feat: stage 64 - 1 fps scan frames with GPS/heading/section index"
```

---

### Task 2: Yaw calibration (equirect → compass azimuth)

**Files:**
- Create: `scripts/64b_yaw_probe.py`
- Create (by controller, after visual check): `work/yaw_calib.json`

**Interfaces:**
- Consumes: `work/frames/index.json`, `raw/3A_AMA North 360_.mp4`.
- Produces: `work/yaw_calib.json` — `{"mode": "world"|"vehicle", "az0_deg": <float>}` where for
  `world`: object compass azimuth `az = az0 + (col/W − 0.5)·360` (constant across video);
  for `vehicle`: `az = heading + az0 + (col/W − 0.5)·360` (az0 = forward offset).
  Every later consumer (Task 4) reads this file.

- [ ] **Step 1: Implement `scripts/64b_yaw_probe.py`** (no TDD — output is judged visually)

```python
"""Render yaw-probe crops from two frames with different headings to calibrate equirect azimuth.
Usage: 64b_yaw_probe.py [v1 v2]  (defaults: 10 and a frame heading ~90 deg away)"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def crop(v, yaw, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-ss", str(v), "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"),
                    "-frames:v", "1",
                    "-vf", f"v360=e:flat:yaw={yaw}:h_fov=100:v_fov=70,scale=960:540",
                    str(out)], check=True)


def main():
    idx = json.loads((ROOT / "work" / "frames" / "index.json").read_text())["frames"]
    by_v = {f["v"]: f for f in idx}
    if len(sys.argv) == 3:
        v1, v2 = int(sys.argv[1]), int(sys.argv[2])
    else:
        v1 = 10
        h1 = by_v[v1]["heading_deg"]
        v2 = next(f["v"] for f in idx if abs(((f["heading_deg"] - h1 + 180) % 360) - 180) > 80)
    out = ROOT / "work" / "yaw_probe"
    out.mkdir(exist_ok=True)
    for v in (v1, v2):
        for yaw in range(0, 360, 45):
            crop(v, yaw, out / f"v{v}_yaw{yaw:03d}.jpg")
        print(f"v={v} heading={by_v[v]['heading_deg']}  -> 8 crops in {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `venv/Scripts/python scripts/64b_yaw_probe.py`
Expected: 16 crops in `work/yaw_probe/` and two heading lines printed.

- [ ] **Step 3: CONTROLLER — visual calibration**

The controller Reads the 16 images and determines, for each of the two frames, which yaw shows the road-ahead (the direction of travel). Then:
- If road-ahead yaw is (approximately) the SAME for both frames → stabilization is vehicle-locked: `mode="vehicle"`, `az0_deg = −yaw_forward` (so `heading + az0 + yaw_forward·... = heading` when looking forward — concretely: forward column offset 0 ⇒ `az0 = −yaw_forward`... define as: `az0_deg` is the value that makes `az = heading + az0 + (col/W−0.5)·360` equal the true compass azimuth; for the forward-showing yaw Yf, `az0 = −Yf`).
- If road-ahead yaw differs between the frames by ≈ their heading difference → world-locked: `mode="world"`, `az0_deg` = the compass azimuth at image centre = `heading − Yf` (compute from either frame; check both agree within ~15°).
Write `work/yaw_calib.json` accordingly (controller writes the file directly), then re-render one confirmation crop per frame at the yaw predicted to be forward and verify visually.

- [ ] **Step 4: Commit**

```bash
git add scripts/64b_yaw_probe.py && git commit -m "feat: yaw calibration probe for equirect azimuth mapping"
```
(`work/` is gitignored; `yaw_calib.json` values get recorded in the merge-stage defaults note in Task 4's report.)

---

### Task 3: CONTROLLER — vision scan of all frames

Not an implementer dispatch. The controller batches `work/frames/f*.jpg` (~530 files) into
groups of 20 consecutive frames and dispatches vision-capable agents (haiku) — one per batch,
several in parallel — with this brief (paths + per-batch frame list substituted):

```
Read these 20 images (Unity drive video scan frames, 2048x1024 equirectangular 360° —
left/right image edges are BEHIND the vehicle, image centre azimuth varies; ignore the
vehicle hull at the bottom). For EACH image, list man-made objects and clearings visible
within ~40 m of the road: classes exactly one of shed|barrier|signboard|gate|fence|clearing.
For each sighting output JSON: {"v": <video second from filename f####.jpg>,
 "class": "...", "col": <horizontal centre of object as fraction 0..1 of image width>,
 "dist": "near|medium|far", "desc": "<8 words max>", "text": "<legible sign text or ''>"}.
near = within ~10 m, medium ~10-20 m, far ~20-40 m. A fence/barrier RUN spanning the frame:
one sighting at its centre. A clearing = widened open area of the road itself.
Skip: vegetation, the road surface, sky, distant background structures.
Write ALL sightings as a JSON array to <workspace>/scan/batch_<NNN>.json (empty array if none).
Reply with only: batch id, image count, sighting count.
```

- [ ] Batch and dispatch all frames (parallel groups of 4–6 agents; ~27 batches total)
- [ ] Spot-check 2 random batch outputs against their images (controller reads 2 images + the JSON)
- [ ] Concatenate to `work/scan_raw.json`: `python -c` one-liner merging all `<workspace>/scan/batch_*.json` arrays into one array — record the total sighting count in the ledger

---

### Task 4: Stage 64c — merge sightings into landmark proposals

**Files:**
- Create: `scripts/64c_merge_proposals.py`
- Test: `tests/test_stage64c.py`

**Interfaces:**
- Consumes: `work/scan_raw.json` (array of sightings per Task 3), `work/frames/index.json`,
  `work/yaw_calib.json`, video for thumbnails.
- Produces: `work/landmarks_proposed.json`:
  ```json
  {"landmarks": [{"id": "L001", "class": "shed", "x": ..., "y": ..., "n_sightings": 3,
                  "first_v": 123, "best_v": 125, "az_deg": ..., "dist_m": 15,
                  "desc": "...", "text": "", "thumb": "work/thumbs/L001.jpg"}, ...]}
  ```
  Position: for each sighting, `az` per yaw_calib formula; world offset = vehicle (x,y) +
  dist_m·(sin az, cos az). Cluster sightings of the same class within 30 m (greedy,
  chronological); landmark position = cluster median; `best_v` = sighting with |az −
  heading ±90°| minimal (most abeam). Thumbnail: v360 crop of `best_v` aimed at `az`
  (yaw = az − az0 [world] or az − heading − az0 [vehicle]), h_fov 80, 640×480, into `work/thumbs/`.
  Clearings additionally export `work/width_profile.json`:
  `{"clearings": [{"x": ..., "y": ..., "radius_m": 25, "width_m": 14.0}, ...]}`.

- [ ] **Step 1: Write the failing test**

`tests/test_stage64c.py`:
```python
import json
import subprocess
from pathlib import Path
import pytest
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def merged():
    # Synthetic scan input exercises clustering without the real scan.
    scan = [
        {"v": 100, "class": "shed", "col": 0.75, "dist": "medium", "desc": "green shed", "text": ""},
        {"v": 101, "class": "shed", "col": 0.74, "dist": "medium", "desc": "green shed", "text": ""},
        {"v": 300, "class": "clearing", "col": 0.5, "dist": "near", "desc": "wide area", "text": ""},
    ]
    (ROOT / "work" / "scan_test.json").write_text(json.dumps(scan))
    subprocess.run([PY, str(ROOT / "scripts" / "64c_merge_proposals.py"),
                    "--scan", str(ROOT / "work" / "scan_test.json"),
                    "--out", str(ROOT / "work" / "landmarks_test.json"),
                    "--no-thumbs"], check=True)
    return json.loads((ROOT / "work" / "landmarks_test.json").read_text())


def test_clusters_consecutive_sightings(merged):
    sheds = [l for l in merged["landmarks"] if l["class"] == "shed"]
    assert len(sheds) == 1 and sheds[0]["n_sightings"] == 2


def test_positions_in_track_bounds(merged):
    for l in merged["landmarks"]:
        assert -160 < l["x"] < 1152 and -320 < l["y"] < 352


def test_clearing_exports_width_profile(merged):
    wp = json.loads((ROOT / "work" / "width_profile.json").read_text())
    assert len(wp["clearings"]) == 1 and wp["clearings"][0]["width_m"] == 14.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage64c.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/64c_merge_proposals.py`**

```python
"""Stage 64c: cluster scan sightings into landmark proposals with ENU positions + thumbnails."""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DIST_M = {"near": 8.0, "medium": 15.0, "far": 25.0}
CLUSTER_M = 30.0
CLEARING_WIDTH = 14.0


def sighting_position(s, frame, calib):
    off = (s["col"] - 0.5) * 360.0
    if calib["mode"] == "world":
        az = calib["az0_deg"] + off
    else:
        az = frame["heading_deg"] + calib["az0_deg"] + off
    d = DIST_M[s["dist"]]
    return (frame["x"] + d * np.sin(np.radians(az)),
            frame["y"] + d * np.cos(np.radians(az)), az, d)


def make_thumb(v, yaw, out):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(v),
                    "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"), "-frames:v", "1",
                    "-vf", f"v360=e:flat:yaw={yaw:.1f}:h_fov=80:v_fov=60,scale=640:480",
                    str(out)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default=str(ROOT / "work" / "scan_raw.json"))
    ap.add_argument("--out", default=str(ROOT / "work" / "landmarks_proposed.json"))
    ap.add_argument("--no-thumbs", action="store_true")
    a = ap.parse_args()

    scan = json.loads(Path(a.scan).read_text())
    idx = {f["v"]: f for f in json.loads(
        (ROOT / "work" / "frames" / "index.json").read_text())["frames"]}
    calib = json.loads((ROOT / "work" / "yaw_calib.json").read_text())

    enriched = []
    for s in scan:
        f = idx.get(s["v"])
        if f is None:
            continue
        x, y, az, d = sighting_position(s, f, calib)
        enriched.append(dict(s, x=x, y=y, az=az, d=d, heading=f["heading_deg"]))

    clusters = []
    for s in sorted(enriched, key=lambda s: s["v"]):
        home = next((c for c in clusters if c[0]["class"] == s["class"]
                     and np.hypot(c[-1]["x"] - s["x"], c[-1]["y"] - s["y"]) < CLUSTER_M), None)
        (home.append(s) if home else clusters.append([s]))

    thumbs = ROOT / "work" / "thumbs"
    thumbs.mkdir(exist_ok=True)
    landmarks, clearings = [], []
    for i, c in enumerate(clusters, 1):
        lid = f"L{i:03d}"
        x, y = float(np.median([s["x"] for s in c])), float(np.median([s["y"] for s in c]))
        best = min(c, key=lambda s: abs(abs(((s["az"] - s["heading"] + 180) % 360) - 180) - 90))
        text = next((s["text"] for s in c if s.get("text")), "")
        lm = dict(id=lid, cls=c[0]["class"], x=round(x, 1), y=round(y, 1),
                  n_sightings=len(c), first_v=c[0]["v"], best_v=best["v"],
                  az_deg=round(best["az"], 1), dist_m=best["d"],
                  desc=best["desc"], text=text, thumb=f"work/thumbs/{lid}.jpg")
        lm["class"] = lm.pop("cls")
        landmarks.append(lm)
        if lm["class"] == "clearing":
            clearings.append(dict(x=lm["x"], y=lm["y"], radius_m=25, width_m=CLEARING_WIDTH))
        if not a.no_thumbs:
            yaw = (best["az"] - calib["az0_deg"] if calib["mode"] == "world"
                   else best["az"] - best["heading"] - calib["az0_deg"])
            make_thumb(best["v"], yaw % 360, thumbs / f"{lid}.jpg")

    Path(a.out).write_text(json.dumps(dict(landmarks=landmarks), indent=1))
    (ROOT / "work" / "width_profile.json").write_text(
        json.dumps(dict(clearings=clearings), indent=1))
    print(f"{len(landmarks)} landmarks ({len(clearings)} clearings) -> {a.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_stage64c.py -v`
Expected: 3 passed. (Requires `work/yaw_calib.json` from Task 2 and `work/frames/index.json` from Task 1.)

- [ ] **Step 5: Run on the real scan**

Run: `venv/Scripts/python scripts/64c_merge_proposals.py`
Expected: prints landmark/clearing counts; `work/thumbs/` populated.

- [ ] **Step 6: Commit**

```bash
git add scripts/64c_merge_proposals.py tests/test_stage64c.py && git commit -m "feat: stage 64c - sighting clustering into landmark proposals"
```

---

### Task 5: Review sheet + USER review gate

**Files:**
- Create: `scripts/64d_review_sheet.py`
- Produce: `work/landmark_review.html`, then (after user review) `export/landmarks.json`

**Interfaces:**
- Consumes: `work/landmarks_proposed.json`, `work/thumbs/*.jpg`.
- Produces: `export/landmarks.json` — same schema as proposals plus per-landmark
  `"approved": true`; only approved entries included. Clearing approvals also filter
  `work/width_profile.json`. Task 6/7 consume both.

- [ ] **Step 1: Implement `scripts/64d_review_sheet.py`**

```python
"""Stage 64d: self-contained HTML contact sheet for landmark review (thumbnails inlined)."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    lms = json.loads((ROOT / "work" / "landmarks_proposed.json").read_text())["landmarks"]
    cards = []
    for l in lms:
        p = ROOT / l["thumb"]
        img = (f'<img src="data:image/jpeg;base64,'
               f'{base64.b64encode(p.read_bytes()).decode()}">' if p.exists() else "(no thumb)")
        cards.append(
            f'<div class="card"><h3>{l["id"]} — {l["class"]}</h3>{img}'
            f'<p>{l["desc"]} | text: "{l["text"]}" | v={l["best_v"]}s | '
            f'({l["x"]}, {l["y"]}) | {l["n_sightings"]} sightings</p></div>')
    html = ('<title>Amakeng landmark review</title><style>body{font-family:sans-serif}'
            '.card{display:inline-block;width:340px;margin:8px;vertical-align:top}'
            '.card img{width:100%}</style>' + "\n".join(cards))
    out = ROOT / "work" / "landmark_review.html"
    out.write_text(html, encoding="utf-8")
    print(f"{len(lms)} cards -> {out}")


if __name__ == "__main__":
    main()
```

Run it; verify it prints the card count and the HTML opens.

- [ ] **Step 2: USER CHECKPOINT — review**

Controller presents `work/landmark_review.html` to the user (open locally; optionally published
as a private Artifact for phone review). User responds with corrections in chat: drop IDs,
reclassify, adjust positions ("L007 is on the other side"), add missed landmarks (with a video
timestamp). PAUSE until the user responds.

- [ ] **Step 3: Apply review verdicts**

Controller applies the user's edits directly to a copy: `export/landmarks.json` (approved
entries only, `"approved": true` added; corrections applied; additions given new IDs with
positions computed via the Task 4 formula from the user-supplied timestamp). Filter
`work/width_profile.json` to approved clearings. Record counts in the ledger.

- [ ] **Step 4: Commit**

```bash
git add scripts/64d_review_sheet.py export/landmarks.json && git commit -m "feat: stage 64d - landmark review sheet + approved landmark export"
```
Note: `export/` is gitignored — force-add the approved landmarks: `git add -f export/landmarks.json` (it is a curated artifact, not a regenerable one).

---

### Task 6: Width profile + section field in stage 61, curvature guard in 63

**Files:**
- Modify: `scripts/61_centerline.py` (width profile + `section` per station)
- Modify: `scripts/63_road_mesh.py` (curvature guard)
- Test: `tests/test_stage61.py` (extend), `tests/test_stage63.py` (extend)

**Interfaces:**
- Consumes: `work/width_profile.json` (optional — absent file ⇒ all stations 10.0 m), `work/frames/index.json` sections.
- Produces: `work/centerline.json` stations gain `"section": "s07"` (nearest scan-frame's section by ENU distance, "" for connector) and per-station `w` widened inside clearing radii: `w = 10 + (width_m − 10)·smoothstep(1 − dist/radius)`, capped 16.0. Stage 63 asserts min turning radius > max(w)/2 + 2 over the widened profile before sweeping.

- [ ] **Step 1: Write the failing tests** (append to existing files)

`tests/test_stage61.py` — add:
```python
def test_stations_have_section_and_width_profile(cl):
    secs = {st["s"] for st in cl["stations"]}  # reuse fixture pattern; field presence:
    assert all("section" in st for st in cl["stations"])
    tagged = [st for st in cl["stations"] if st["section"]]
    assert len(tagged) > 2000  # most recorded stations tagged
    assert all(st["section"] == "" for st in cl["stations"] if st["provisional"])
    ws = [st["w"] for st in cl["stations"]]
    assert min(ws) == 10.0 and max(ws) <= 16.0
```

`tests/test_stage63.py` — add:
```python
def test_curvature_guard_uses_widened_profile():
    import importlib
    m63 = importlib.import_module("63_road_mesh")
    # guard function exists and passes on current data
    m63.assert_sweepable()  # raises AssertionError if any radius <= max_halfwidth + 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_stage61.py tests/test_stage63.py -v`
Expected: new tests FAIL (missing field / missing function)

- [ ] **Step 3: Implement**

In `scripts/61_centerline.py` `main()` after `stations` assembly inputs exist (before writing):
```python
    # Optional clearing width profile (Part B feedback)
    wp_path = ROOT / "work" / "width_profile.json"
    widths = np.full(len(xy), WIDTH)
    if wp_path.exists():
        for c in json.loads(wp_path.read_text())["clearings"]:
            dd = np.hypot(xy[:, 0] - c["x"], xy[:, 1] - c["y"])
            tt = np.clip(1.0 - dd / c["radius_m"], 0.0, 1.0)
            blend = tt * tt * (3 - 2 * tt)
            widths = np.maximum(widths, np.minimum(WIDTH + (c["width_m"] - WIDTH) * blend, 16.0))

    # Section tag from the nearest scan frame (Part B); connector stays untagged
    sec_of = np.array([""] * len(xy), dtype=object)
    fi_path = ROOT / "work" / "frames" / "index.json"
    if fi_path.exists():
        frames = json.loads(fi_path.read_text())["frames"]
        fxy = np.array([[f["x"], f["y"]] for f in frames])
        fsec = [f["section"] for f in frames]
        from scipy.spatial import cKDTree
        dist, near = cKDTree(fxy).query(xy)
        for i in range(n_loop):
            if dist[i] < 30:
                sec_of[i] = fsec[near[i]]
```
and change the station dict line to use them:
```python
                     w=round(float(widths[i]), 2), section=str(sec_of[i]),
                     provisional=i >= n_loop)
```
(remove the old `w=WIDTH`).

In `scripts/63_road_mesh.py`, add after `sts = cl["stations"]`:
```python
def assert_sweepable(stations=None):
    if stations is None:
        stations = json.loads((ROOT / "work" / "centerline.json").read_text())["stations"]
    xy = np.array([[st["x"], st["y"]] for st in stations])
    a, b, c = xy[:-2], xy[1:-1], xy[2:]
    cross = (b[:, 0]-a[:, 0])*(c[:, 1]-a[:, 1]) - (b[:, 1]-a[:, 1])*(c[:, 0]-a[:, 0])
    ab = np.linalg.norm(b-a, axis=1); bc = np.linalg.norm(c-b, axis=1)
    ca = np.linalg.norm(c-a, axis=1); area2 = np.abs(cross)
    r = np.where(area2 > 1e-9, ab*bc*ca/(2*area2), 1e9)
    half_ext = max(st["w"] for st in stations) / 2 + 2
    bad = int((r <= half_ext).sum())
    assert bad == 0, f"{bad} stations with turn radius <= sweep half-extent {half_ext:.1f} m"
```
(move it to module level, call `assert_sweepable(sts)` at the top of `main()`).

- [ ] **Step 4: Regenerate and run the full suite**

Run: `venv/Scripts/python scripts/61_centerline.py && venv/Scripts/python scripts/62_terrain.py && venv/Scripts/python scripts/63_road_mesh.py && venv/Scripts/python -m pytest tests/ -v`
Expected: all pass (19+). If the curvature guard trips because a widened clearing sits on a curve, reduce that clearing's `width_m` in `work/width_profile.json` toward 12.0 until it passes and note it in the report (the guard exists precisely to catch this).

- [ ] **Step 5: Sync + rebuild scene**

```bash
venv/Scripts/python scripts/70_sync_unity.py
```
Then rebuild via MCP `Unity_RunCommand` (editor open): `Amakeng.BuildAmakeng.BuildScene(); Amakeng.BuildVehicle.Build();` wrapped in the CommandScript template — or headless CLI fallback if MCP is unavailable. Verify console clean via `Unity_GetConsoleLogs`.

- [ ] **Step 6: Commit**

```bash
git add scripts/61_centerline.py scripts/63_road_mesh.py tests/test_stage61.py tests/test_stage63.py && git commit -m "feat: clearing width profile + station sections + sweep curvature guard"
```

---

### Task 7: PlaceLandmarks.cs + validation layer fix

**Files:**
- Create: `unity/PlaceLandmarks.cs`
- Modify: `unity/BuildAmakeng.cs` (ValidateRoad: ignore vehicle colliders)

**Interfaces:**
- Consumes: `Assets/Amakeng/Generated/landmarks.json` (synced from `export/`), scene from Part A.
- Produces: menu **Amakeng > Place Landmarks** / static `Amakeng.PlaceLandmarks.Place()`:
  `[GEN] Landmarks` parent with one proxy per approved landmark, snapped to terrain height,
  oriented to face the road (toward the nearest centreline station from `road_meta.json`
  `stations_unity`). ValidateRoad ignores hits on objects under `[GEN] Vehicle`.

- [ ] **Step 1: Write `unity/PlaceLandmarks.cs`**

```csharp
// Places landmark proxies from Generated/landmarks.json. Menu: Amakeng > Place Landmarks.
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Amakeng
{
    public static class PlaceLandmarks
    {
        [MenuItem("Amakeng/Place Landmarks")]
        public static void Place()
        {
            EditorSceneManager.OpenScene(BuildAmakeng.ScenePath);
            var old = GameObject.Find("[GEN] Landmarks");
            if (old != null) Object.DestroyImmediate(old);
            var parent = new GameObject("[GEN] Landmarks");

            string json = File.ReadAllText("Assets/Amakeng/Generated/landmarks.json");
            var landmarks = MiniJsonLandmarks(json);
            var stations = BuildAmakeng.LoadStationsUnity();
            int n = 0;
            foreach (var l in landmarks)
            {
                var go = MakeProxy(l.cls, l.text);
                go.name = l.id + "_" + l.cls;
                go.transform.SetParent(parent.transform, false);
                float ux = l.x, uz = l.y;               // ENU -> Unity (x, z)
                float uy = TerrainY(ux, uz);
                go.transform.position = new Vector3(ux, uy, uz);
                var near = Nearest(stations, ux, uz);
                go.transform.rotation = Quaternion.LookRotation(
                    new Vector3(near.x - ux, 0, near.z - uz).normalized, Vector3.up);
                n++;
            }
            EditorSceneManager.MarkSceneDirty(parent.scene);
            EditorSceneManager.SaveScene(parent.scene);
            Debug.Log($"Amakeng: placed {n} landmark proxies");
        }

        static float TerrainY(float x, float z)
        {
            var t = Terrain.activeTerrain;
            return t != null ? t.SampleHeight(new Vector3(x, 0, z)) + t.transform.position.y : 0f;
        }

        static Vector3 Nearest(List<Vector3> pts, float x, float z)
        {
            Vector3 best = pts[0]; float bd = float.MaxValue;
            foreach (var p in pts)
            {
                float d = (p.x - x) * (p.x - x) + (p.z - z) * (p.z - z);
                if (d < bd) { bd = d; best = p; }
            }
            return best;
        }

        static GameObject MakeProxy(string cls, string text)
        {
            GameObject go;
            switch (cls)
            {
                case "shed":
                    go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    go.transform.localScale = new Vector3(6, 3, 4);
                    Tint(go, new Color(0.35f, 0.4f, 0.35f));
                    break;
                case "barrier":
                    go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    go.transform.localScale = new Vector3(4, 1, 0.3f);
                    Tint(go, new Color(0.8f, 0.25f, 0.2f));
                    break;
                case "signboard":
                    go = new GameObject("sign");
                    var post = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                    post.transform.SetParent(go.transform, false);
                    post.transform.localScale = new Vector3(0.1f, 1.25f, 0.1f);
                    post.transform.localPosition = new Vector3(0, 1.25f, 0);
                    var board = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    board.transform.SetParent(go.transform, false);
                    board.transform.localScale = new Vector3(1.6f, 1.0f, 0.05f);
                    board.transform.localPosition = new Vector3(0, 2.2f, 0);
                    Tint(board, new Color(0.9f, 0.85f, 0.6f));
                    break;
                case "gate":
                    go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    go.transform.localScale = new Vector3(8, 1.2f, 0.15f);
                    Tint(go, new Color(0.7f, 0.7f, 0.2f));
                    break;
                case "fence":
                    go = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    go.transform.localScale = new Vector3(10, 1.5f, 0.1f);
                    Tint(go, new Color(0.45f, 0.35f, 0.25f));
                    break;
                default: // clearing - marker only, small and flat
                    go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                    go.transform.localScale = new Vector3(2, 0.05f, 2);
                    Tint(go, new Color(0.9f, 0.9f, 0.3f));
                    break;
            }
            return go;
        }

        static void Tint(GameObject go, Color c)
        {
            var m = new Material(Shader.Find("Universal Render Pipeline/Lit")) { color = c };
            foreach (var r in go.GetComponentsInChildren<MeshRenderer>()) r.sharedMaterial = m;
        }

        static List<LandmarkEntry> MiniJsonLandmarks(string json)
        {
            // Same manual-parse approach as BuildAmakeng.MiniJsonStations (JsonUtility can't
            // parse the array-of-objects with our field set reliably enough for floats).
            var list = new List<LandmarkEntry>();
            int i = json.IndexOf("\"landmarks\"");
            i = json.IndexOf('[', i) + 1;
            while (true)
            {
                int a = json.IndexOf('{', i);
                if (a < 0) break;
                int b = json.IndexOf('}', a);
                string obj = json.Substring(a + 1, b - a - 1);
                var e = new LandmarkEntry
                {
                    id = Field(obj, "id"), cls = Field(obj, "class"), text = Field(obj, "text"),
                    x = FloatField(obj, "\"x\""), y = FloatField(obj, "\"y\"")
                };
                if (e.id != "") list.Add(e);
                i = b + 1;
                int nb = json.IndexOf(']', b);
                int no = json.IndexOf('{', b);
                if (no < 0 || (nb >= 0 && nb < no)) break;
            }
            return list;
        }

        static string Field(string obj, string name)
        {
            int i = obj.IndexOf("\"" + name + "\"");
            if (i < 0) return "";
            int q1 = obj.IndexOf('"', obj.IndexOf(':', i) + 1);
            int q2 = obj.IndexOf('"', q1 + 1);
            return obj.Substring(q1 + 1, q2 - q1 - 1);
        }

        static float FloatField(string obj, string key)
        {
            int i = obj.IndexOf(key);
            int c = obj.IndexOf(':', i) + 1;
            int e = obj.IndexOfAny(new[] { ',', '}' }, c);
            if (e < 0) e = obj.Length;
            return float.Parse(obj.Substring(c, e - c).Trim(),
                               System.Globalization.CultureInfo.InvariantCulture);
        }

        class LandmarkEntry { public string id, cls, text; public float x, y; }
    }
}
```

- [ ] **Step 2: Add `LoadStationsUnity` + vehicle-exclusion to `unity/BuildAmakeng.cs`**

Make the station loader public (rename the private helper): change
`static System.Collections.Generic.List<Vector3> MiniJsonStations(string json)` usage so:
```csharp
        public static System.Collections.Generic.List<Vector3> LoadStationsUnity()
        {
            var json = File.ReadAllText(Path.Combine(GenDir, "road_meta.json"));
            return MiniJsonStations(json);
        }
```
And in `ValidateRoad()`'s raycast loop, ignore vehicle hits:
```csharp
                if (!Physics.Raycast(origin, Vector3.down, out var hit, 100f) ||
                    hit.transform.root.name == "[GEN] Vehicle" ||
                    Mathf.Abs(hit.point.y - s.y) > 0.5f)
```
Wait — a vehicle hit should not count as bad if the road below is fine; use RaycastAll instead:
```csharp
                var hits = Physics.RaycastAll(origin, Vector3.down, 100f);
                bool ok = false;
                foreach (var h in hits)
                    if (h.transform.root.name != "[GEN] Vehicle" &&
                        Mathf.Abs(h.point.y - s.y) <= 0.5f) { ok = true; break; }
                if (!ok) bad++;
```
(replace the whole per-station check with the RaycastAll version; keep the warning log for failures.)

- [ ] **Step 3: Sync, place, validate via MCP**

```bash
venv/Scripts/python scripts/70_sync_unity.py
```
Then via `Unity_RunCommand` (CommandScript template): `Amakeng.PlaceLandmarks.Place();` then
`Amakeng.BuildAmakeng.ValidateRoad();` — expect "placed N landmark proxies" and
"641/641 stations OK" (vehicle exclusion removes the 2 false flags). Check
`Unity_GetConsoleLogs` for errors; capture a scene view via
`Unity_SceneView_CaptureMultiAngleSceneView` at a landmark position for visual confirmation.
Headless CLI fallback if MCP is down.

- [ ] **Step 4: Commit**

```bash
git add unity/PlaceLandmarks.cs unity/BuildAmakeng.cs && git commit -m "feat: landmark proxy placement + vehicle-excluded road validation"
```

- [ ] **Step 5: USER CHECKPOINT — drive with landmarks**

User drives the loop; landmarks should appear where remembered (spec acceptance:
"landmarks visible where expected"). Collect corrections (move/remove/resize) → controller
edits `export/landmarks.json`, re-syncs, re-places.

---

## Self-Review Notes

- Spec coverage: stage 64 (Tasks 1–5), PlaceLandmarks + photo context (Task 7; photo-TEXTURED
  signs deferred — proxies get legible `text` recorded for a later texture pass, noted as
  out-of-Part-B-scope trim per YAGNI since sign legibility at 8K equirect 1 fps is unproven),
  clearing→width feedback + re-run 61–63 (Task 6), Part B backlog from Part A final review:
  section field (Task 6), curvature guard (Task 6), ValidateRoad layer mask (Task 7). Fence
  runs: spec wants polylines; Task 7 uses single 10 m segments per clustered sighting —
  consecutive fence clusters approximate the run; full polyline arraying deferred until the
  scan shows real fence extents (ledger note for the reviewer).
- Placeholder scan: clean; all code blocks complete.
- Type consistency: `landmarks.json` schema identical across Tasks 4/5/7 (`class` string,
  `x`/`y` ENU floats); `yaw_calib.json` consumed only in Task 4 with the Task 2 formula;
  `width_profile.json` produced (4) / filtered (5) / consumed (6); `LoadStationsUnity()`
  defined in Task 7 Step 2 and used in Task 7 Step 1.
