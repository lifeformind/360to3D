# Amakeng Hybrid Circuit — Design Spec

Date: 2026-09-01. Supersedes the splat pipeline (abandoned; see `docs/hybrid_handoff.md` §1).

## Goal

A drivable circuit in Unity that broadly feels like the Amakeng training circuit.
Priority: road surface > clearings > fences/signboards/man-made landmarks. Vegetation
detail does not matter. Built from GIS data (GPX + DTM/DSM) and the drive video —
no reconstruction.

## Decisions (settled 2026-09-01)

| Question | Decision |
|---|---|
| Render pipeline | URP, new Unity 6000.3.19f1 project |
| Driving | WheelCollider physics vehicle, included in deliverable |
| Road width | ~10 m base, widened at the few clearings (identified in video scan) |
| Loop closure | Provisional generated connector now; real segment from a second video patched in later — pipeline is multi-segment aware |
| Landmarks | Claude scans sampled video frames, proposes a timestamped list; user reviews |
| Delivery | Python → OBJ + JSON + RAW heightmap; Unity Editor C# scripts assemble |
| Ground representation | Unity Terrain from DTM heightmap + precise generated road mesh (Option 1) |

## Coordinate conventions (fixed — from handoff §2)

- **ENU**: metres, origin = first GPX fix of clip 004 (lat 1.4064823, lon 103.7155928),
  x=East, y=North, z=Up. All generation happens here.
- **Unity**: x=East, y=Up, z=North (left-handed). ENU→Unity = (x, z, y), applied only at export.
- **Heights**: DTM only (GPS altitude is +17 m off — ignored). Road surface = DTM.
  Unity y=0 = DTM elevation at track start.
- **Video↔GPS**: frame n (10 fps, 1-based) at t = (n−1)/10 + 2.0 s after first fix;
  interpolate `raw/gpx_004.npz`. Parked gaps (no fixes): 307–367 s, 380–392 s.
- Sanity: from above, the circuit runs anticlockwise, starting eastward.

## Inputs (verified 2026-09-01)

- `raw/dtm_clip.tif` — EPSG:4326 (degrees), ~0.5 m px equivalent, 1.1–39.5 m
- `raw/dsm_clip.tif` — SVY21-style Transverse Mercator (metres), 0.5 m px, 1.1–61.8 m
- The two rasters have **different CRSs** — reprojected once in stage 60, never touched again
- `raw/gpx_004.npz` — 532 fixes, 644 s, ~3.0 km; ends 184 m from start
- `raw/3A_AMA North 360_.mp4` — stitched 8K equirect, 9.98 GB
- `colmap_db/gpx/section_transforms.json` — 18-section chapter index into the video

## Repo layout

```
work/       # generated intermediates (ENU rasters, centerline, frames, proposals)
export/     # OBJ + JSON + RAW heightmap + textures for Unity
unity/      # Editor C# scripts, copied/linked into the Unity project
scripts/    # 6x-numbered generator scripts, one per stage
```

Unity project: `C:\repos\AmakengCircuit` (separate from this repo); a small sync
script copies `export/` and `unity/*.cs` in.

## Pipeline stages

### 60_prepare_rasters.py
Reproject DTM (EPSG:4326) and DSM (SVY21-style) into a common local metric grid
(0.5 m) aligned to the ENU origin, clipped to track extent + 100 m. Outputs
`work/dtm_enu.tif`, `work/dsm_enu.tif`, `work/canopy_enu.tif` (DSM−DTM, clamped ≥0).
All CRS handling lives here and only here.

### 61_centerline.py
From `gpx_004.npz`: spline-smooth the 1 Hz fixes, resample at 1 m stations, sample
heights from `dtm_enu.tif`, drop parked gaps, append the provisional connector
(smooth blend end→start, DTM heights, tagged `provisional: true`). Output
`work/centerline.json` — single source of truth (station, x, y, z, tangent, width,
section, provisional flag). Multi-segment aware for the future second-video patch.
Per-station `width` defaults to 10 m; in Part A all stations use the default.
Clearing entries from the Part B landmark scan are fed back into a width profile,
after which stages 61–63 are re-run (they are idempotent) to widen those stretches.

### 62_terrain.py
`dtm_enu.tif` → Unity Terrain RAW (16-bit, 2049×2049 covering the padded-square
extent) + `export/terrain_meta.json` (world size, height range, Unity position
offset). Terrain heights within a ~14 m corridor of the centreline are blended
toward the road profile so terrain never pokes through the ribbon.

### 63_road_mesh.py
Sweep a crowned cross-section (per-station width, ~2% crown, shoulder skirts meeting
the blended terrain) along the centreline. Same height profile as the terrain blend,
so they agree by construction. Length-parameterised UVs for tiling gravel. Output
`export/road.obj` + `export/road_meta.json`. Provisional connector = separate
submesh so it renders visibly placeholder.

### 64_sample_frames.py
ffmpeg: ~1 fps frames from the equirect MP4 into `work/frames/` (~640 frames),
skipping parked ranges; `v360` forward crops on demand. Claude reviews frames and
writes `work/landmarks_proposed.json`: per object — `t_video`, frame, thumbnail,
class (shed / barrier / signboard / gate / fence-run / clearing), side-of-road,
rough size. Position = time mapping → GPX interp → ENU, plus lateral offset from
the centreline. Clearings feed stage 61's width profile. **User reviews**; approved
entries → `export/landmarks.json`. Fence runs are polylines between two timestamps,
not points. Legible signs/barriers get photo-textures cropped and rectified from
frames into `export/textures/`.

### 65_vegetation.py
From `canopy_enu.tif`: Poisson-disk tree instances where canopy > 3 m, density ∝
canopy cover, instance height from canopy value (observed up to ~29 m), jittered
rotation/scale; road corridor (centreline ± ~9 m) excluded. Output `export/trees.json`.
Grass verge band (road edge → ~15 m, canopy < 3 m) as a density map PNG for Terrain
detail painting. Budget: if > ~100k instances, keep full density within 50 m of the
centreline and thin beyond (raise canopy threshold).

### run_generate.sh
Runs 60→65 in order, stops on first failure. Every stage independently re-runnable,
idempotent, fixed output paths.

## Unity side (`unity/`)

- `BuildAmakeng.cs` — menu *Amakeng > Build Scene*: Terrain from RAW + meta; import
  `road.obj` with MeshCollider + URP tiling gravel material; position per meta JSONs.
- `PlaceLandmarks.cs` — *Amakeng > Place Landmarks*: class→prefab map (primitives /
  simple meshes, photo-textured where available), snap to terrain height, orient to
  road tangent; fence prefab arrayed along polylines.
- `PlaceVegetation.cs` — *Amakeng > Place Vegetation*: trees as Terrain tree
  instances (2–3 URP prefab variants), grass as Terrain detail layer from density map.
- Vehicle: minimal WheelCollider rig (box body, 4 wheels), tuned for gravel and
  grades to ~12%; spawn at track start facing east; driver-height follow camera;
  speed readout only.
- All assembly scripts idempotent: generated objects under tagged parents
  (`[GEN] Road`, `[GEN] Landmarks`, `[GEN] Trees`) replaced on rebuild.
- Backdrop: URP procedural sky (afternoon sun ≈ 15:24 capture), fog ~300 m to hide
  the raster edge.

## Testing

Generator (pytest-light, per stage):
- 60: output CRS/extent/pixel-size assertions
- 61: monotone stationing; max grade < 15%; starts heading east; loop anticlockwise
- 63: no degenerate triangles; normals up; width matches profile
- 65: zero trees inside the road corridor

Unity (manual): drive the full loop — no fall-through, no bottoming-out; slope feel
matches DTM profile (max ~9–12%); landmarks appear where expected; ~60 fps in editor.

## Phasing

1. **Part A** (stages 60–63 + BuildAmakeng + vehicle) → user drives bare road on
   terrain, confirms feel before further investment.
2. **Part B** (stage 64 + PlaceLandmarks) → scan, review cycle, place.
3. **Part C** (stage 65 + PlaceVegetation + sky/fog).

## Out of scope

Second-video patch (designed-for, not built now); gameplay/scoring/AI; audio;
night/weather; anything splat/SfM-related.
