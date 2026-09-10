# VR Corridor Rendering — Design Spec

Date: 2026-09-10. Parent: `2026-09-08-vertical-slice-design.md` (slice recipe accepted with
mesh-as-base + SeedMesh vegetation). Supersedes the open density/backdrop questions in
`docs/full-circuit-rollout-notes.md` for the VR path.

## Target and constraints (new, binding)

The deliverable is a **VR driving experience, eventually standalone on Oculus Quest**
(XR2-class mobile GPU). Budgets that bind every technique below:
- ≤ ~1M triangles/frame (stereo), ≤ ~150–200 draw calls, 72 Hz.
- Tile-based GPU: alpha-BLENDED overdraw is prohibitive → all foliage is alpha-CUTOUT or
  opaque; minimize stacked cutout layers.
- Fully baked/static lighting; no realtime shadows (blob shadow under vehicle); single
  directional light. ASTC textures. Fixed Foveated Rendering on.
- Editor-GPU frame rates are meaningless for acceptance; profile via Quest Link early, on
  standalone before ship.
- Development order: build to standalone budgets NOW; iterate via editor + Link.

## Design principle

The player never leaves the road corridor. Perceived density therefore comes from
**photographic texture baked onto near-flat geometry**, not from instanced geometry. The
video is ground truth for the wall of leaves exactly as it was for the road surface.

## The stack (band by band)

| Band | Technique |
|---|---|
| road surface | projected mosaic (built; slice-proven) |
| 1–4 m verge | true-3D SeedMesh plants, GPU-instanced, cutout, merged per 20 m chunk (~5–10/10 m) |
| 3–15 m walls + overhead | **video-projected corridor shell** (this spec's core; pilot below) |
| above/behind shell | octahedral impostor trees where canopy pokes over the shell |
| far field | cylindrical panorama ring baked from mesh/video per sector (replaces live photogrammetry tiles on Quest) — the 54-tile mesh (~8.6M tri) is EDITOR-ONLY reference from here on |
| visibility | corridor sector occlusion: pre-baked PVS per ~50 m segment |

## The corridor shell

Geometry: a ruled surface swept along the centreline at 1 m stations. Cross-section per
station: left wall at lateral −W_L(s), right wall at +W_R(s), height H(s); a ceiling arc
closes the section wherever the canopy covers the road.
- W_side(s): distance from centreline to the canopy edge (first lateral with canopy ≥ 3 m in
  `work/canopy_enu.tif`), clamped [4, 15] m, smoothed along s.
- H(s): canopy height at the wall line, clamped [6, 20] m.
- Ceiling present where canopy ≥ 3 m ON the centreline (DSM−DTM over the road) — the
  "tunnels under dense canopy" the user described.
- Base z follows the road profile; shell is open at both slice ends (driver passes through).

Texture: inverse-projected from the drive video with the stage-67/68 machinery (camera track,
calib az0=110/h_cam=3.0, world-locked equirect mapping):
- Wall texels sample from the frame whose camera is ABEAM of the texel (s_cam ≈ s_texel):
  relative azimuth ±90°, the hull-free direction, closest range → sharpest texels.
- Ceiling texels sample looking up from the abeam frame (stabilized horizon ⇒ zenith clean).
- Push-broom strips per frame (~0.64 m), same exposure normalization + road-centring-style
  registration as stage 68 where needed; 5 cm/px target, atlas tiles per wall/ceiling.
- Known limitation: anything with true depth variation (gaps into the forest) bakes flat;
  the 1–4 m plant band restores parallax. Sky visible through thin canopy bakes into the
  ceiling — acceptable for the pilot, masked (cutout from luminance/blue-ness) later.

## Phasing

1. **Shell pilot (spike, throwaway code)**: build shell + projected textures for the existing
   slice (stations 439–664, the window with cached calibration), import as [PROBE] Shell,
   editor captures + user judgment vs the drive video. GO/NO-GO for the stack.
2. Shell productized (stage 74) + cutout cards swap + plant-band instancing/merging.
3. Impostors + panorama far ring + sector culling; retire live mesh tiles from the runtime
   scene (kept for authoring: landmark positions, shell calibration cross-checks).
4. Quest project settings (Android/ASTC/FFR), Link profiling, standalone profiling gates:
   ≥ 72 Hz sustained on Quest 2-class hardware over the full slice.

## Acceptance

- Pilot: shell view at driver height reads as "wall of leaves/creepers + canopy tunnel"
  matching the corresponding video frames; user verdict.
- Stack (later): full slice ≥ 72 Hz on device, ≤ 1M tris, ≤ 200 draw calls, and the drive
  "feels like the footage" per the standing project goal.

## Out of scope

Hand authoring of vegetation; PCVR-only visual features (realtime shadows, SSAO);
gameplay/audio; the loop connector's shell (no footage until the second video arrives).
