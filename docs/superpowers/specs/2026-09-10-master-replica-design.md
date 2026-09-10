# 3D Master Replica — Design Spec

Date: 2026-09-10. Supersedes the *sequencing* of `2026-09-10-vr-corridor-rendering-design.md`:
the corridor shell is SUSPENDED as a video-projection product and will later be **baked from
this master scene** (that spec's budgets/stack remain the Quest export contract). Parent
recipe: `2026-09-08-vertical-slice-design.md` (mosaic road + mesh-as-base + SeedMesh).

## Goal

A **maximally realistic, drivable 3D replica** of the circuit on the authoring workstation
(Ryzen AI Max 395, 128 GB unified memory). Poly count is not a constraint; the bar is "looks
like the drive footage" at driver height. Authoring interactivity target: ≥ 30 fps in-editor
on the slice (not a VR target — Quest consumes bakes later).

## Decisions (user, 2026-09-10)

- **Render pipeline: switch the project to HDRP** (SeedMesh packs are HDRP-native — full
  shader quality, wind, translucency return; best-in-Unity lighting for the master).
- **Photogrammetry mesh: underlay + replant** — mesh keeps supplying ground/berms and
  mid-field mass; dense 3D vegetation is planted through and in front of its melted blobs.

## Components

### 1. HDRP migration (in-place, this project)
- Assign an HDRP pipeline asset (GraphicsSettings + quality); remove URP-specific assets from
  the active slots (URP assets/packages stay installed for the future Quest export project).
- Revert SeedMesh materials to their native Shader Graph materials (delete/disable
  `FixSeedMeshMaterialsForUrp` and the converted material assets) — they are HDRP-target.
- Re-target OUR generated materials to HDRP: terrain (HDRP TerrainLit + existing layers),
  gravel road base, backdrop double-sided clones, barrier, card material (if re-enabled).
- **Road mosaic overlay**: the photo carries baked real light. Use **HDRP Unlit with Shadow
  Matte enabled** so it keeps its photographic look yet still receives dynamic tree shadows.
- Sky/fog/exposure via an HDRP Volume: physically-based sky or gradient matched to footage,
  exponential fog (same visual role as before), fixed exposure tuned once against the mosaic.
- Sun: existing NOAA position; shadows ON (this is the realism unlock the workstation buys).
- Wind: enable pack wind if the SeedMesh graphs expose it (they are authored with vegetation
  animation in the HDRP target; verify at migration).

### 2. Rainforest densification (stage 75)
Mass planting from the canopy raster + centreline, deterministic (seeded), chunked under
`[GEN] Forest/<chunk>` parents every 20 m of track for streaming/culling later:
- **Layers** (per placement, chosen from local canopy height h and lateral zone):
  - canopy (h ≥ 12): `Background_group_var*`, tall `Dense_Jungle_Tree_Var*` — scaled to h
  - midstory (6 ≤ h < 12): `Dense_Jungle_Tree_Var*`, banana groups
  - understory (1.5–6): `Forest_bush/Common_bush`, Tropical Plants mix
  - ground (< 1.5): Ground Foliage Vol.2 prefabs
  - **wall line**: climbing/hanging SeedMesh prefabs along the canopy edge (the creeper wall)
- **Density**: driven by canopy cover — target ~3,000–8,000 instances on the slice (≈15–35×
  today), lateral band 4–40 m both sides, excluded within 5.5 m of the centreline; Poisson
  jitter, scale/yaw variation.
- Output `export/forest_placements.json` (stage 75, python — reuses canopy sampling from 72);
  planted by a rewritten DressSlice `PlantForest()` (replaces PlantTrees/ScatterUnderstory).
- The 40 m+ field stays photogrammetry (underlay decision).

### 3. Fidelity pass
- Footage-matched grading (HDRP Volume: color adjustments) using a mosaic-vs-render
  comparison at 3 reference stations.
- Vehicle: shadow casting on, simple HDRP materials.
- Keep frame-rate probe in the loop: report editor fps on the slice each Dress.

## Phasing

1. HDRP migration + existing slice re-validated (captures: nothing magenta, road mosaic
   correct, mesh + terrain fine, SeedMesh at native quality).
2. Stage 75 densification on the slice → captures + editor fps → user judgment against the
   "wall of leaves" bar.
3. Circuit-wide: extend planting + (separately decided) mosaic road rollout.
4. Later, per the VR spec: bake corridor shell/impostors/panorama FROM this master for Quest.

## Acceptance

User drives the slice in-editor: dense layered rainforest walls, tree shadows on the road,
wind in the foliage, ≥ 30 fps; judged against the drive footage. Captures at the reference
stations accompany each iteration.

## Risks

- HDRP editor load on the Radeon iGPU: mitigate with HDRP quality tier tuning; the master
  never needs >60 fps.
- Double-lighting on photo textures: mitigated by Unlit+Shadow-Matte for the mosaic; judge
  the mesh tiles (they also carry baked light) — acceptable as underlay, revisit if jarring.
- Instance count vs editor responsiveness: chunked parents allow disabling distant chunks
  while authoring.

## Out of scope

Shell baking, impostors, panorama (VR spec, after the master is accepted); Part B landmark
scan (queued); loop connector; audio.
