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

- **RESOLVED 2026-09-09 — real trees work**: TreePackVol.1 trees run in URP after manual
  material rebuild (bark = URP Lit opaque; leaves = URP Lit alpha-cutout _Cutoff 0.4 Cull Off,
  same textures; wind sway lost; each of the 48 prefabs embeds its OWN materials — ~9 converted
  assets for 5 variants, not 2; sub-10 m sapling prefabs must be filtered before height
  scaling). Open tuning: cull the dark shard-leaf variants; enforce a minimum tree-to-road
  distance (~10 m) so big leaf-planes never sit at close range.
- `RenderSettings.reflectionIntensity = 0` is global — kills reflections on the vehicle and
  future shiny landmarks (Part B); scope it properly in the rollout.
- Bush wind animation lost with the green-tint material swap (accepted for the slice).

## Ops facts (also in project memory)

- Unity_Camera_Capture instance-ID path broken; use RunCommand + RenderTexture readback.
- Play-mode probing needs OS foreground focus (PowerShell force-focus).
- Row convention pinned by test: mosaic PNG top-origin, Unity UV bottom-origin
  (tests/test_stage69.py::test_v_row_convention).

## SeedMesh material recovery

The vertical-slice/URP-era `FixSeedMeshMaterialsForUrp()` (deleted in the Task 1 HDRP
migration) mutated the SeedMesh packs' own shipped `.mat` assets in place to make them
render under URP — 87 of 108 materials under `Assets/SeedMesh` in `C:\repos\AmakengCircuit`
were found corrupted this way when HDRP migration started. If `DressSlice.
WarnIfSeedMeshNotNative()` (runs on every `Dress()`) ever logs a material still on a
`Universal Render Pipeline/...` shader, run `venv/Scripts/python
scripts/fix_seedmesh_materials.py` (`--dry-run` first to preview) — it restores pristine
bytes for affected `.mat` files straight out of this machine's cached SeedMesh Asset Store
`.unitypackage` archives (GUID-matched against the project, so it never touches anything
that isn't actually the corrupted copy of a pristine original). See the script's own
docstring for the full mechanism and its "requires this machine's local Asset Store cache"
caveat. `AssetDatabase.ImportPackage` does not work for this — it was observed to never
actually execute when driven through the Unity MCP automation bridge this project's builds
use, hence the direct byte-restore approach.
