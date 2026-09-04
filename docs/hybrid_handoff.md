# AMAKENG circuit — handoff to the hybrid (mesh-based) approach

Written 2026-09-01 on the DGX Spark, for continuing on a machine that has Unity, QGIS and the source data.
Read this first in the new Claude Code session; it replaces the conversation context.

## 1. Where we are and why

Goal (unchanged): a **drivable circuit in Unity that broadly feels like the Amakeng training circuit** —
priority order: road surface, clearings, fences, signboards and other man-made landmarks; vegetation detail
does not matter.

Gaussian-splat reconstruction from the Insta360 X5 drive footage was tried exhaustively and **abandoned on
2026-09-01**. Root causes, so nobody repeats it: single fast pass at 10 fps with ~9 px/degree per cube face,
motion blur, vehicle hull in ~40 % of every frame; LingBot monocular poses off by 1–3 m (training moved every
camera that far); reconstruction PSNR ~16 dB. Results: road a blur, foliage blobs. Corrected masks, sky loss,
analytic road-depth loss and a 4 m near plane improved the top-down picture but never the driver's view.

New direction (**hybrid**): build the road and terrain as real meshes from the GPS track and the DTM/DSM, place
landmarks as proxies at positions taken from the video timeline, dress with procedural vegetation guided by the
canopy height (DSM − DTM), use a normal skybox. Drivable on day one; fidelity comes from GIS data, not
reconstruction.

## 2. Coordinate conventions (keep these exactly)

- **ENU frame**: metres, origin = first GPX fix of clip 004, **lat 1.4064823, lon 103.7155928**, x = East,
  y = North, z = Up. Small-area equirectangular projection (`raw/gpx_004.npz` has `x,y` already computed;
  `31_gpx_anchor.py` shows the formula: x = (lon−lon0)·cos(lat0)·R, y = (lat−lat0)·R).
- **Unity frame**: x = East, y = Up, z = North (left-handed). ENU→Unity is the axis swap (x, z, y).
  Sanity check: seen from above with +z up on screen the circuit runs **anticlockwise** and starts heading
  **east**.
- **Elevation**: DTM heights are orthometric; GPS altitude sits 16.9 m above the DTM (ellipsoid/geoid offset).
  Use DTM for everything; ignore GPS altitude. Road surface = DTM (the vehicle drove on it).
- **Video ↔ GPS time**: 10 fps frames `c04_%05d.jpg` (1-based, from the stitched equirect MP4 of clip 004);
  frame n is at t = (n − 1)/10 + **2.0 s** after the first GPX fix (`dt = +2.0` verified from parking gaps).
  So any video frame → GPS position by interpolating `t` in `gpx_004.npz`. This is how landmarks get placed.
- GPS fix gaps (vehicle parked, no fixes): 307–367 s and 380–392 s.
- **Track facts**: 532 fixes over 644 s; ~3.0 km; the recording ends **184 m** from the start (the loop is
  not closed in this clip — decide whether to invent a connector or record the missing stretch).
  Terrain along the track: DTM 4.8–21.7 m, grades up to ~9–12 %; canopy (DSM − DTM) up to ~22 m.

## 3. Files in the handoff archive (`amakeng_hybrid_handoff.tar.gz`)

| path | what |
|---|---|
| `raw/VID_20260724_152412_00_004.gpx`, `raw/gpx_004.npz` (lat, lon, ele, t, x, y), `raw/track_004.kml` | the GPS track (clip 004 = the full circuit drive) |
| `raw/dtm_profile.csv`, `raw/dsm_profile.csv` | QGIS "Sample raster values" at each GPX fix (`dtm_1` / `dsm_1` columns, `time`) |
| `colmap_db/gpx/dtm_profile.npz` | same as arrays: `t, ele_dtm, ele_dsm, ele_gps` |
| `colmap_db/gpx/section_transforms.json` | the 18 video sections: global frame ranges (`frames`), status, notes (s10 parked, s11 mostly parked, s08 distorted) — useful as a chapter index into the video |
| `colmap_db/gpx/*.png` | overlays / bird's-eye diagnostics (reference only) |
| `unity_bundle_v4/road_centerline_unity.csv` | centreline in Unity metres per video frame (`frame,t_video_s,x,y,z,section`), y = road surface (DTM-relative, track start = 0). Good enough to start the road ribbon; regenerate from GPX + DTM raster for the final |
| `unity_bundle_v4/BuildAmakengRoad.cs` | Unity Editor script: builds an 8 m ribbon MeshCollider from that CSV (menu *Amakeng > Build Road Collider*) — starting point for the road mesh generator |
| `scripts/` | all pipeline scripts; relevant now: `31_gpx_anchor.py` (GPX parsing/ENU), `36_dtm_profile.py`, `37_dtm_csv.py`, `32_unity_placement.py` (ENU→Unity quaternion/handedness maths), `40_make_masks_v2.py` (SegFormer usage — reusable for detecting sheds/barriers/signs in frames) |
| `docs/arcgis_elevation_export.md` | how the DTM/DSM CSVs were produced (ArcGIS + QGIS Option D) |
| `STATUS.md`, `CLAUDE.md` | full chronological log of the splat effort; project instructions (now partly obsolete — rewrite for the hybrid) |
| `claude_memory/` | this Claude Code project's memory files — copy into the new machine's `~/.claude/projects/<project-path>/memory/` |

Not in the archive (you have them): the source `.insv` / stitched MP4 of clip 004, and the DTM/DSM GeoTIFF
rasters you are exporting from QGIS (clip to circuit + ~100 m, native resolution, note the EPSG code).

## 4. Design so far (brainstorming was in progress — continue from here)

Decomposition, in build order:
- **A. Drivable core**: road surface mesh (plan from GPX, smoothed; width TBD — measure from video, ~6–8 m
  gravel), height/slope from the DTM raster along the centreline, crowned profile, shoulders blending into a
  terrain mesh built from the DTM raster; MeshCollider; gravel material. Also the loop-closure decision.
- **B. Landmarks**: sheds, barriers, signboards, gates, clearings — positions from video frames via the
  time mapping above; proxies = simple textured meshes or Unity primitives/assets; optionally photo-textures
  cropped from the frames.
- **C. Vegetation & backdrop**: treeline/forest from the DSM − DTM canopy height (place tree prefabs where
  canopy > ~3 m, scale by height), grass on verges, skybox.

Open questions (ask in this order):
1. Unity setup: version, render pipeline, and whether a vehicle controller exists (WheelCollider sample /
   asset) or should be included; or camera-on-rails instead of physics.
2. Road width and cross-section (measure in a few frames; gravel single lane ~6 m? clearings wider).
3. Loop closure: invent a connector for the 184 m gap, or record it.
4. Landmark list: which objects matter and roughly where (video timestamps are enough).
5. Delivery format: OBJ/FBX + placement JSON + Editor scripts (recommended, matches what exists) vs a
   Unity package.

Approaches worth comparing for A: (i) pure generator in Python (GDAL/shapely/trimesh → OBJ + JSON, Unity
imports), (ii) generate in Unity from the CSV/raster via Editor scripts (spline + terrain sampling), (iii)
Unity Terrain from the DTM raster (heightmap import) + a spline road on top (e.g. Unity Splines package).
(iii)+(i) is probably the sweet spot: Unity Terrain for the ground (heightmap = DTM GeoTIFF), a generated
road mesh conforming to it, trees painted from a DSM-derived density map.

## 5. Tooling notes

- Python deps for the generator: numpy, rasterio (or GDAL), shapely, scipy, trimesh. No GPU needed.
- The old pipeline's DGX Spark-specific notes (ARM64 builds, CUDA 13, gsplat patches) are irrelevant now.
- Unity: aras-p Gaussian splatting package is no longer needed.
