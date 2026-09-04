# Project: Amakeng Circuit — Hybrid Mesh Build (Unity)

## Goal
A drivable circuit in Unity that broadly feels like the Amakeng training circuit.
Priority: road surface > clearings > fences/signboards/man-made landmarks. Vegetation
detail does not matter. Built from GIS data (GPX + DTM/DSM), NOT reconstruction.

Authoritative context: `docs/hybrid_handoff.md`. History: `STATUS.md`.

## Approach (three parts, in build order)
- **A. Drivable core** — road ribbon mesh from the GPX centreline (smoothed plan,
  heights from the DTM raster), crowned profile + shoulders, terrain mesh/Unity
  Terrain from the DTM, MeshCollider, gravel material. Includes the loop-closure
  decision (recording ends 184 m from start).
- **B. Landmarks** — sheds, barriers, signs, gates, clearings as proxy meshes/primitives,
  positions from video frames via the time mapping (frame n → t = (n−1)/10 + 2.0 s →
  interpolate `raw/gpx_004.npz`), optionally photo-textured from frames.
- **C. Vegetation & backdrop** — tree prefabs where canopy (DSM − DTM) > ~3 m, scaled
  by height; grass verges; normal skybox.

## Coordinate conventions (exact — do not change)
- **ENU**: metres, origin = first GPX fix of clip 004 (lat 1.4064823, lon 103.7155928),
  x=East, y=North, z=Up. Equirect small-area projection (see `scripts/31_gpx_anchor.py`).
- **Unity**: x=East, y=Up, z=North (left-handed); ENU→Unity = (x, z, y). Sanity check:
  from above the circuit runs anticlockwise, starting eastward.
- **Elevation**: use DTM only (road = DTM surface). GPS altitude is +16.9 m off (geoid) — ignore it.
- GPS fix gaps (parked): 307–367 s, 380–392 s. Track: 532 fixes, 644 s, ~3.0 km.

## Key files
- `raw/dtm_clip.tif`, `raw/dsm_clip.tif` — elevation rasters (~0.5 m px)
- `raw/gpx_004.npz` (lat, lon, ele, t, x, y), `raw/VID_20260724_152412_00_004.gpx`
- `raw/3A_AMA North 360_.mp4` — stitched 8K equirect video of clip 004
- `colmap_db/gpx/section_transforms.json` — 18-section chapter index into the video
- `unity_bundle_v4/road_centerline_unity.csv` + `BuildAmakengRoad.cs` — starting road ribbon
- `venv/` — Python env (numpy, scipy, rasterio, shapely, trimesh, pyproj, gpxpy)

## Do NOT
- Do not propose Gaussian-splat / SfM / NeRF reconstruction — tried exhaustively,
  abandoned 2026-09-01 (see handoff §1). No more training runs.
- Do not use GPS altitude for heights; do not trust the hand-traced satellite map
  (`3A_Ama North Map.png`) for placement — GPX is the authority.
- DGX Spark / ARM64 / CUDA notes in old memory are irrelevant on this machine.
