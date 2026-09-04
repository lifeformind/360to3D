# AMAKENG circuit — Unity bundle v4 (overnight retrain, 2026-09-01)

Retrained with corrected masks (vehicle hull + sky only; road unmasked), a 4 m training near plane, sky forced
transparent, and analytic road-depth supervision (camera is 3.09 m above the road). 17 sections (s10 dropped:
parked, no geometry), 4 500 training steps each — a first full pass, not final quality.

Everything is in **Unity's frame** (x = East, y = Up, z = North, metres, left-handed, origin = first GPX fix,
road ≈ y 0 at the start). Import with **identity transforms**.

| file | what |
|---|---|
| `amakeng_merged_unity.ply` | whole circuit, 2.04 M splats, 0.48 GB — **use this** |
| `sections/sXX_unity.ply` | same data per section |
| `road_centerline_unity.csv` | drivable centreline (`frame,t_video_s,x,y,z,section`), from the pose-optimised cameras; y = road surface. `*_sfm.csv` = older SfM-pose version |
| `BuildAmakengRoad.cs` | Editor menu *Amakeng > Build Road Collider*: 8 m-wide invisible MeshCollider along the centreline |
| `check_whole_track.png` | renders of this file: top-down, oblique, driver views |
| `pose_opt_shifts.json` | how far training moved each section's cameras from the SfM poses (median 2–4 m) |
| `SHA256SUMS` | verify after copying |

## Import (aras-p UnityGaussianSplatting)
1. Package Manager → Add package from git URL: `https://github.com/aras-p/UnityGaussianSplatting.git?path=/package`
2. Tools → Gaussian Splats → Create GaussianSplatAsset → `amakeng_merged_unity.ply`, quality **Very High**.
3. Empty GameObject at origin, identity rotation, scale (1,1,1) → add `GaussianSplatRenderer`, assign the asset.
4. Copy `BuildAmakengRoad.cs` + `road_centerline_unity.csv` into `Assets/Amakeng/`, run *Amakeng > Build Road Collider*.
5. Spawn the vehicle at the first centreline point (`0, 0.2, 0` + 1 m), facing east (+x). Use a **skybox** — the splat has no sky.
6. **Camera Near Clip Plane = 4 m** (the models were trained with a 4 m near plane; closer content is untrained).

Mirror check: from above with +z (north) up on screen the circuit must run anticlockwise, starting eastward.
If it runs clockwise, set the splat object's scale to (1, 1, −1).

## What to expect
Top-down the circuit is a clear road ribbon with verges; sky is transparent; no floaters. At driver height the
road is a soft, blurry plane and vegetation is blobby — 4 500 steps on a single fast pass of 10 fps footage.
The 30k-step recipe (≈2.4 h/section, ~40 h total) is the next quality step; the pipeline is ready for it
(`TAG=v5 MAX_STEPS=30000 … scripts/45_batch_v3.sh`).
Known weak sections: s01 (few gaussians), s08 (distorted trajectory), s11 (mostly parked).

## Provenance
`scripts/40_make_masks_v2.py` (masks) → `43_road_depth.py` (depth targets) → `41_train_v2.sh`/`45_batch_v3.sh`
(gsplat, patched: `--sky-alpha-lambda`, road-depth loader) → `38_bake_unity_ply.py` (TAG=v4) → `46_centerline_opt.py`.
