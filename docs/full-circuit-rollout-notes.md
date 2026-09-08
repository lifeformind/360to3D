# Full-Circuit Appearance Rollout — carry-over notes (2026-09-09)

From the vertical-slice final review. These feed the full-circuit appearance spec after the
slice acceptance drive. Source of truth for slice decisions: the vertical-slice spec/plan and
git history on `vertical-slice`.

## Must-fix-before-scaling (will break, not just need retuning)

- **Stage 68 tile enumeration** samples only the endpoints of the covered range — breaks at ≥3
  tiles. Enumerate `range(int(s_lo//SPAN), int(s_hi//SPAN)+1)`.
- **Stage 68 memory**: whole mosaic in RAM ×2 passes ≈ 2 GB/km — full circuit (~3.2 km) needs
  chunked processing (per-tile accumulation).
- **Terrain detail resolution 512** across the whole terrain (~2 m cells vs the 0.5 m verge
  mask) — lossy at circuit scale; raise or per-region detail maps.

## Parameterize (currently slice-hardcoded)

- 67: `--v0/--v1` window; az0 search grid is window-anchored; test's 351-frame count.
- 68: assumes a single contiguous monotonic-s window (no parked-gap handling); streak
  percentile includes uncovered columns; tests hardcode tiles [2,3] and crop bounds.
- 69: emits only atlas-covered tiles; the blend/seam to non-slice tiling-gravel spans is
  unbuilt; tests hardcode object names.
- 71: grid bounds from tile-span stations; VERGE=(5,7).
- 72: station range 439–664 in `cut()`; curation (card_selection.json) is per-window
  controller judgment — needs a scalable review workflow for 15+ windows.
- 73: S_RANGE/MARGIN constants; tile-name format assumes positive indices; full run touches
  most of the 40 GB tile set.
- DressSlice: single `[GEN] Slice` root; single-barrier slice_extras schema;
  FixGroundMaterial ordering coupling with BuildScene (Build Scene alone regresses the ground
  look); generated materials accumulate in Assets/Amakeng root; full re-sync copies 222 MB of
  backdrop every run (make incremental).

## Recipe gaps / decisions for the user

- **No true 3D-tree band**: neither installed pack has URP-compatible tall trees (TreePackVol.1
  is Tree Creator = magenta). Canopy = foliage cards + photogrammetry backdrop + stretched
  bushes. Decide at acceptance: license/buy a URP tree pack vs accept the current look.
- `RenderSettings.reflectionIntensity = 0` is global — kills reflections on the vehicle and
  future shiny landmarks (Part B); scope it properly in the rollout.
- Bush wind animation lost with the green-tint material swap (accepted for the slice).

## Ops facts (also in project memory)

- Unity_Camera_Capture instance-ID path broken; use RunCommand + RenderTexture readback.
- Play-mode probing needs OS foreground focus (PowerShell force-focus).
- Row convention pinned by test: mosaic PNG top-origin, Unity UV bottom-origin
  (tests/test_stage69.py::test_v_row_convention).
