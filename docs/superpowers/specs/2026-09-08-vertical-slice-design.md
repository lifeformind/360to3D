# Amakeng Vertical Slice — Design Spec

Date: 2026-09-08. Parent spec: `2026-09-01-amakeng-hybrid-circuit-design.md` (this spec inserts
an appearance milestone between Part A and Part B; the Part B landmarks plan
`2026-09-08-part-b-landmarks.md` executes after the slice recipe is accepted).

## Goal

One 225 m stretch of the circuit — **stations 439–664** (video seconds 99–134, a straight,
a bend, a clearing edge, one red-white barrier) — dressed to final visual quality with every
element of the look: projected road texture, mosaic-driven verges, footage foliage cards,
3D trees, photogrammetry backdrop, one man-made proxy, and matched lighting. The user drives
through it; acceptance = "entering the slice feels like entering the real circuit" at
acceptable frame rate. The accepted recipe then becomes the template for the full-circuit
appearance pipeline spec.

## Principle

**The video supplies appearance; the canopy map and photogrammetry mesh supply placement.**
Distance bands cover each other's weaknesses:

| Band | Element | Technique |
|---|---|---|
| 0–15 m | road | inverse-projected video mosaic (validated by pilot) + tiling detail normal |
| 0–15 m | grass/underbrush | Unity terrain details (asset-pack grass/fern), density+tint from mosaic verge pixels |
| 3–20 m | foliage wall | alpha-cutout cards cropped from 8K frames, arrayed along the canopy edge |
| 10–60 m | trees | asset-pack tree prefabs (with LODs) painted as Terrain trees from DSM−DTM |
| 40 m+ | forest mass | photogrammetry mesh tiles, clipped to >40 m from centreline |
| anywhere | man-made | proxy geometry + video-cropped textures (slice: one barrier) |
| global | atmosphere | sun at 24 Jul 2026 15:24 SGT azimuth/elevation, URP fog, footage-matched grade |

## Established calibration facts (from the pilot spike)

- Stitched export is **world-locked** (direction-stabilized): equirect centre looks at a fixed
  compass azimuth **az0 ≈ 108°** (stage 67 refines it); horizon is level (pitch/roll ≈ 0).
- Camera height above road ≈ **3.0 m** (h_cam, stage 67 refines).
- Vehicle hull occupies azimuths around vehicle-FORWARD; the rear-facing view is clean →
  **sample road texels 7–9 m BEHIND the camera** (relative azimuth within ±60° of heading+180°).
- Push-broom mosaic at 10 fps / ~6.4 m/s gives ~0.64 m of fresh strip per frame; 5 cm/px
  texels; per-strip road-centring already removes most lateral jitter (proven).

## Pipeline stages (new; numbering continues the generator convention)

- **67_camera_track.py** — 10 fps camera poses for an arbitrary video window: t → GPS interp
  snapped to centreline station; z = station z + h_cam; heading from tangent. Refines az0 and
  h_cam once via a checkerboard-free self-check (projected road width == 10 m ⇒ h_cam;
  road-centre drift ⇒ az0) and stores `work/camera_calib.json` {az0_deg, h_cam_m, mode:"world"}.
  Output `work/camera_track.json` (per frame: v, t, s, x, y, z, heading).
- **68_road_mosaic.py** — pilot projector industrialized: strips 7–9 m behind camera;
  registration = per-strip road-centre alignment (greenness profile) + pairwise NCC of strip
  overlaps for residual longitudinal/lateral seams + per-frame exposure gain normalization;
  above-road streak mask (barrier/sign smears) inpainted from neighbouring strips. Outputs
  `export/road_albedo/tile_%02d.png` (4096² atlas tiles, 5 cm/px, station-major layout) +
  `work/mosaic_report.png` (coverage/seam QA image). Slice mode: only the window's tiles.
- **69_road_uv.py** — re-emits stage 63's road OBJ UVs from tiling (v = s/4) to atlas mapping
  (u = lateral 0..1 across 14 m corridor, v = s/atlas_span within tile, one material slot per
  tile span); adds `export/road_meta.json` field `atlas: {tile_span_m, tiles: [...]}`.
  Non-slice road spans keep the tiling gravel material.
- **71_verge_masks.py** — classifies mosaic verge pixels (green vs bare) → per-slice terrain
  detail density map PNGs + a tint map; writes `export/verge_masks/*.png` + meta.
- **72_foliage_cards.py** — cuts 10–15 foliage cutouts from slice-window frames (colour-key +
  manual curation by the controller), writes `export/foliage_cards/*.png` (RGBA) + a placement
  JSON along the canopy edge (DSM−DTM ≥ 3 m boundary within 20 m of centreline), spacing
  3–6 m jittered, sized from canopy height.
- **Unity: `DressSlice.cs`** — menu *Amakeng > Dress Slice*: assigns atlas road materials for
  slice spans; paints terrain details/tint from verge masks; instantiates foliage cards
  (two-sided cutout shader) and asset-pack Terrain trees from canopy; imports + clips the 3–4
  backdrop mesh tiles (>40 m mask by deleting triangles nearer the centreline); places the
  barrier proxy at the smear location with a cropped stripe texture; sets the sun via a
  solar-position computation for 1.407°N 103.716°E at 2026-07-24 15:24 SGT (NOAA formula,
  implemented in the script — not hand-estimated), URP fog and ambient.
  Idempotent under `[GEN] Slice` parent.

## Asset dependencies (user-imported, via Package Manager → My Assets)

- Terrain Sample Asset Pack (assetstore id 145808) — grass/fern details, base trees
- Tree Collection Pack 2017 (assetstore id 76974) — species variety
Scripts must FAIL SOFT with a clear console message if pack folders are absent, and must
reference pack assets by searched path (`AssetDatabase.FindAssets`) — exact folder names are
confirmed at implementation time after import.

## Verification

- Stage tests (pytest): camera track monotone stations + calib file schema; mosaic tiles
  exist, 4096², coverage > 95 % of slice, seam-QA metric below threshold (mean adjacent-strip
  NCC displacement < 2 texels); UV re-emit round-trips station↔uv; verge masks match mosaic
  dimensions.
- Editor: MCP-driven build (`Dress Slice`), console clean, scene-view captures at 3 driver-height
  points reviewed by controller before the user drive.
- USER: drive through the slice; acceptance criteria = transition feel + no obvious card
  billboarding artifacts at speed + frame rate ≥ 60 in editor Play mode.

## Out of scope

Full-circuit rollout (own spec after acceptance); Part B landmark scan (plan exists, runs
after); loop-connector/parked-gap synthetic road fill; species-accurate flora; audio.
