# AMAKENG scale-out STATUS  (updated 2026-08-14 22:46:10)

**Phase:** ALL DONE — 18/18 sections complete. Machine may be shut down.

**Safe to shut down at any time.** All progress is checkpointed:
- finished sections are final (splat_output/sXX/ply/point_cloud_29999.ply)
- an interrupted training resumes from its last 10k checkpoint on next launch
- on power-up, the user crontab (@reboot ensure_watchdog.sh) auto-resumes
  any unfinished sections; remove with: crontab -l | grep -v ensure_watchdog | crontab -

## Sections
- s01: COMPLETE (val PSNR 15.57)
- s02: COMPLETE (val PSNR 14.93)
- s03: COMPLETE (val PSNR 17.66)
- s04: COMPLETE (val PSNR 14.84)
- s05: COMPLETE (val PSNR 17.28)
- s06: COMPLETE (val PSNR 16.56)
- s07: COMPLETE (val PSNR 14.56)
- s08: COMPLETE (val PSNR 15.22)
- s09: COMPLETE (val PSNR 18.49)
- s10: COMPLETE (val PSNR 19.28)
- s11: COMPLETE (val PSNR 19.26)
- s12: COMPLETE (val PSNR 22.80)
- s13: COMPLETE (val PSNR 14.17)
- s14: COMPLETE (val PSNR 14.98)
- s15: COMPLETE (val PSNR 16.85)
- s16: COMPLETE (val PSNR 14.66)
- s17: COMPLETE (val PSNR 13.89)
- s18: COMPLETE (val PSNR 15.55)

## Next steps (deferred by user)
- Unity assembly: transform each section ply from its normalized frame to
  map metres (inverse of gsplat Parser normalize transform), import all as
  separate splat objects via aras-p UnityGaussianSplatting.
- Session pickup: memory file pipeline-status-amakeng.md has full context.

## 2026-08-21 GPX anchoring (done)
- GPX for clip 004 parsed and synced (+2.0 s). Hand-traced map route was wrong; GPS is now the placement authority.
- Unity placement: scripts/unity/unity_placement.json + scripts/unity/PlaceAmakengSections.cs (x=E, y=Up, z=N, metres, road at y=0).
  Full transforms + checks: colmap_db/gpx/section_transforms.json; bird's-eye check: colmap_db/gpx/birdseye_assembly_enu.png
- s10 = parked (drop); s11 mostly parked (check); s08 distorted loop (check seams with s07/s09).
- Recommended next quality step: GPS-anchored retrain of sections (fix 1.3-1.95x trajectory-scale conflict).

## 2026-08-21 15:35 GPS-anchored retrain batch RUNNING (s01 s02 s03 s04 s06 s07 s08 s09 s11 s12 s13 s14 s15 s16 s17 s18; s05 pilot done)
- Pilot s05_gps: train 15.9 / val 16.4 vs old 16.5 / 17.3 -> NO quality gain (slightly lower, within view-sampling noise); visually equivalent.
- Batch kept running for geometric consistency (true scale, cloud/camera agreement). Stop with: pkill -f 34_retrain_gps.sh; pkill -f simple_trainer.py; pkill -f watchdog_gps.sh; crontab -l | grep -v ensure_watchdog_gps | crontab -
- Outputs: splat_output/sXX_gps/ (old splat_output/sXX untouched). Log: logs/retrain_gps.log (marks only: grep -a "^\[20").
- Safeguards: watchdog_gps.sh heartbeat logs/watchdog_gps.heartbeat; crontab */10 + @reboot ensure_watchdog_gps.sh (self-disarm on RETRAIN BATCH FINISHED).

## 2026-08-21 15:50 DSM/DTM integrated (ArcGIS Earth screenshots, not rasters)
- raw/DTM.tif + raw/DSM.tif are ArcGIS Earth screenshots (RGBA, no geotags) with the GPX overlaid. Registered GPX->image by
  homography ICP on the blue track (0.5 px rms); DTM grey calibrated to metres against GPS altitude (corr 0.91) ->
  colmap_db/gpx/dtm_profile.{npz,png}. Terrain along track 17.5-39 m; grades up to ~12% (dip at ~460 s).
- Unity placement now terrain-aware: per-section tilt (chord through overlap zones) + height; road dz at seams within ~+-1.5 m
  (s13/s14 ~3 m where terrain curves inside a section). Unity y=0 = DTM 24.8 m at track start.
  scripts/unity/unity_placement.json (terrain) | unity_placement_flat.json (flat fallback). Better data still welcome:
  an elevation-profile CSV along the GPX from the real DTM would replace the screenshot calibration.

## 2026-08-21 18:25 GPS retrain STOPPED by user (2/17 done: s05_gps, s01_gps — neither improved PSNR)
- Stopped cleanly: batch, trainer, watchdog killed; crontab guardian removed; session cron deleted. s02_gps had no checkpoint yet (restarts from 0).
- To resume later: `setsid nohup ./scripts/34_retrain_gps.sh > /dev/null 2>&1 < /dev/null &` (+ optionally watchdog_gps.sh and the
  crontab lines `*/10 * * * * .../ensure_watchdog_gps.sh` / `@reboot ...`). Resumable via splat_output/sXX_gps/RENDER_DONE.
- Waiting on: elevation CSV along the GPX from ArcGIS — workflow written to docs/arcgis_elevation_export.md.

## 2026-08-31 14:05 Real DTM/DSM profile from QGIS integrated
- User exported per-fix DTM/DSM samples with QGIS (`raw/dtm_profile.csv`, `raw/dsm_profile.csv`, 532 rows, matched to GPX by time).
- `scripts/37_dtm_csv.py` → `colmap_db/gpx/dtm_profile.npz` (t, ele_dtm, ele_dsm, ele_gps); screenshot version backed up as `dtm_profile_screenshot.npz`.
  DTM 4.8–21.7 m; GPS − DTM = 16.9 m (std 2.0, corr 0.95); screenshot calibration was 1.8 m rms / 5.5 m max off the real DTM.
- `32_unity_placement.py` re-run (needs `venv/bin/python` + LD_LIBRARY_PATH): section heights moved ≤3 m (most ±1.5 m);
  slopes s09 9.4 %, s14 5.6 %, s06 3.8 %, others <3.5 %. Seams xy unchanged (0.4–3.8 m; s07/s08/s09 8–15 m), road dz −1.5..+2.2 m.
  Previous placement kept as `scripts/unity/unity_placement_screenshot.json`.
- GPS retrain still stopped (2/17 done, no PSNR gain) — resume command above if wanted.

## 2026-08-31 16:30 Unity bundle built (retrain skipped per user) — `unity_bundle/`
- `38_bake_unity_ply.py`: section transforms (GPS + terrain) baked INTO the PLYs, mirrored to Unity's left-handed frame
  (positions, quaternions, scales and SH coefficients all transformed; self-checks: covariance + view-dependent colour identical).
  Pruned opacity<0.02 / >150 m from path / >15 m gaussians; sections cropped at mid-overlap frame (nearest training camera).
  17 sections → `unity_bundle/sections/sXX_unity.ply` + `amakeng_merged_unity.ply` (5.04 M splats, 1.19 GB, ~3.0 km of road).
- `road_centerline_unity.csv` (6182 pts) + `BuildAmakengRoad.cs` (MeshCollider ribbon) for driving; `README.md` has the import steps.
- `32_unity_placement.py` now also writes `colmap_db/gpx/section_cams_enu.npz` (per-section ENU camera pos + rotation + global frame).
- `39_render_bundle_check.py`: renders the merged Unity PLY at exact training poses vs video (`unity_bundle/check/`, NEAR env var).
- **Near-plane finding**: gsplat trained with near_plane=0.01 *normalised* units = ~8 m in these scenes (scene scale 1/600..1/1100),
  so nothing within ~8 m of any camera was ever rendered in training → that zone is full of large unconstrained blobs; with a metric
  near plane (0.3 m) every view is a flat wall. Unity mitigation: camera near clip 6–8 m (aras-p clips whole splats by centre depth,
  verified in RenderGaussianSplats.shader). Real fix = retrain with `--near_plane 1e-3` + CORRECT masks (see 17:40 entry: training WAS masked via RGBA alpha,
  but the optical-flow masks also cover the road ahead/behind). s05_gps/s01_gps retrains had the same near plane.
- Quality is the known ceiling (PSNR ~16): blobby vegetation, road/clearings legible. Renders at training poses match the
  original models exactly, so assembly is verified; mirror check documented in README (circuit anticlockwise from above, starts east).

## 2026-08-31 17:40 Mask audit — existing training masks are wrong (road masked out)
- gs_scene images are RGBA; gsplat's loader uses alpha>127 as the loss mask (`datasets/colmap.py` "RGBA input"), so training WAS masked.
- The masks came from `make_masks.py` (optical-flow, low flow = rig). Low flow also = focus of expansion → the ROAD AHEAD and BEHIND
  and blank sky are masked: 42–75 % of every face (s03 f210: Y000 55 %, Y090 69 %, Y180 68 %, Y270 75 %); road only supervised
  from the side faces, partially. See `unity_bundle/check/existing_masks_s03_210.png`.
- Sky segmentation test: `nvidia/segformer-b2-finetuned-ade-512-512` (cached in ~/.cache/huggingface, works offline now):
  clean sky masks, ~70 ms/face on GB10 → ~30 min for all 26k faces (`unity_bundle/check/segformer_s03_210.png`).
  Its 'vehicle' classes catch the bonnet but not the rear rack/roof → hull mask must come from temporal statistics (per-face static)
  ∪ segformer-vehicle frequency, dilated (`unity_bundle/check/hullmask_s03.png` = temporal-std prototype, interior only).
- Retrain cost: s01_gps took 2 h 23 min (30k steps) → 17 sections ≈ 40 h GPU. Proposed: pilot ONE section with new masks +
  `--near_plane 1e-3`, compare renders, then batch.

## 2026-08-31 16:23 Pilot retrain s03_v2 STARTED (corrected masks + near_plane 1e-3)
- `scripts/40_make_masks_v2.py --sec s03` → `colmap_db/s03/gs_scene_v2/` (RGBA; sparse symlinked to gs_scene). Hull = static per face:
  median-sharpness ratio (rigid detail stays sharp in the temporal median, road at the FOE blurs) ∪ SegFormer vehicle classes,
  bottom-touching components, hole fill with border walls, + one manual polygon (Y180 rear deck), dilate 15 px @512.
  Sky = SegFormer-b2 ADE20K per frame, dilate 3 px. Road is unmasked everywhere. Masked: Y000 51 %, Y090 52 %, Y180 73 %, Y270 72 %
  (sky 23–34 %). Rejected criteria: temporal std (masks road at FOE), paint-colour region grow (eats road).
  Preview: `unity_bundle/check/masks_v2_s03.png`, hull only: `hull_v2_s03.png`.
- `scripts/41_train_v2.sh s03 0.001`: same gsplat flags as before + `--near-plane 0.001` (≈0.8 m); out `splat_output/s03_v2`,
  log `logs/train_v2_s03.log` (grep -a "^\[20"), ETA ~2.4 h. Compare against `splat_output/s03` by renders at training poses.

## 2026-08-31 18:50 Pilot 1 (s03_v2) FAILED — collapsed to a colour field; pilot 2 (s03_v3) started
- s03_v2 (masks v2 + near 0.8 m): sky ceiling gone (36 giant gaussians vs 2125) but the model is a smooth colour field
  (gsplat eval renders `splat_output/s03_v2/renders/`, my renders `unity_bundle/check/compare_s03_v2_*.png`). Masked PSNR at train
  views 15.3 dB (old 15.8) — blur-level. 39 % of gaussians within 8 m of a camera (old 19 %): with the near plane at 0.8 m the
  optimiser hung a blob cloud in front of every camera (unconstrained in the 50–73 % masked pixels); the 8 m near plane was what
  forced the old models to build any geometry at all.
- Pose-opt deltas are LARGE in both runs: median 3–4 m, max 10 m (checkpoint `pose_adjust.embeds`, ×810 m/unit). All renders at
  training views must apply them (42_compare_v2.py now does; validated: masked PSNR rises 14.7→15.8 old, 13.5→15.3 new).
  Implication for the bundle: the centreline/placement came from UN-optimised poses → metres of error vs the splat content.
- gsplat's built-in val PSNR (~6 dB) is meaningless with masks (render zeroed at masked pixels, GT not).
- Patched gsplat (tools/gsplat/examples): RGBA alpha==64 → `data["sky"]`; `--sky-alpha-lambda` adds λ·mean(rendered alpha over sky
  pixels). gs_scene_v2 alpha re-encoded: 0=hull, 64=sky (27.5 %), 255=keep. `41_train_v2.sh <sec> <near> <tag> [extra flags]`.
- s03_v3 = masks v2 + near 0.005 (4.05 m) + `--sky-alpha-lambda 0.5 --opacity-reg 0.005`. Log `logs/train_v3_s03.log`.
- Next lever if v3 is still weak: depth supervision of the road from LingBot depths (`colmap_db/sXX/lingbot_out/sXX_fwd/*.npz`)
  via gsplat `--depth_loss` (needs pseudo-points injected into the parser).

## 2026-08-31 19:55 Overnight plan (user: finish all sections tonight, whole track in the morning)
- Prep for all 16 remaining sections running: `scripts/44_prep_all.sh` (masks v2 with hull reused from s03 via `--hull-from`,
  alpha 0/64/255, analytic road depths) → `logs/prep_all.log`, "<sec> PREP DONE" markers.
- Pilots on s03: v3 (near 4 m + sky-alpha 0.5 + opacity-reg 0.005, 30k steps, ETA ~21:30) and v4 (same + `--depth-loss
  --depth-lambda 1e-3`, 8k steps — also validates the short schedule), running concurrently.
- Batch: `scripts/45_batch_v3.sh` (env TAG/MAX_STEPS/NEAR/EXTRA; resumable via splat_output/sXX_<TAG>/BATCH_DONE; waits for prep;
  2 tries per section; bakes `unity_bundle_<TAG>/` at the end via `TAG=<tag> 38_bake_unity_ply.py`). 8k steps ≈ 40 min/section
  → ~11 h for 16 sections. Guardian: `watchdog_v3.sh` + crontab `ensure_watchdog_v3.sh` (to be added at launch).
- Session crons: 2-hourly supervision tick, one-shot morning report 07:57.

## 2026-08-31 21:58 Overnight batch LAUNCHED — tag v4 (recipe = pilot s03_v4)
- Pilot s03_v4 (8k steps, near 4 m, sky-alpha 0.5, opacity-reg 0.005, --depth-loss --depth-lambda 1e-3 with analytic road depths):
  sky transparent, ground plane coherent, no wall at novel views; blurry (8k). Best so far → batch recipe.
  `unity_bundle/check/compare_s03_v4_montage.png`. s03_v3 (30k, no depth) still finishing — informational only.
- Batch: `TAG=v4 MAX_STEPS=8000 NEAR=0.005 EXTRA="…--depth-loss --depth-lambda 1e-3" scripts/45_batch_v3.sh`
  → logs/batch_v4.log, per-section logs/train_v4_sXX.log, markers splat_output/sXX_v4/BATCH_DONE, then bake → unity_bundle_v4/.
  Guardian: scripts/watchdog_v4.sh (logs/watchdog_v4.log, heartbeat) + crontab ensure_watchdog_v4.sh (*/10 + @reboot).
- s03's v4 model is the pilot output (splat_output/s03_v4) and is included in the bake.
- 22:35 RESTART: watchdog was testing staleness on batch_v4.log (quiet during training) and relaunching without the recipe env →
  fixed (newest train log, env exported in watchdog_v4.sh). s03_v3 pilot killed to free the GPU (no result). Rate 0.49 s/step alone →
  batch restarted with MAX_STEPS=4500 (~37 min/section, ETA ~08:30); s01 resumed from ckpt_2665. Lesson repeated: `pgrep -f`/`pkill -f`
  with a pattern present in your own command line kills your own shell (exit 144) — kill explicit PIDs only.

## 2026-09-01 06:20 Overnight v4 batch DONE — 16/16 sections, 0 failures, bundle baked
- Timeline: s01 21:53→22:50 (incl. restart), then 30–32 min per section, s18 done 06:07; bake 06:07 → `unity_bundle_v4/`
  (17 sections incl. s03 pilot; 2.04 M splats, 0.48 GB merged; per-section PLYs; centreline; BuildAmakengRoad.cs; SHA256SUMS).
- Top-down (`unity_bundle_v4/check_whole_track.png`): circuit reads as a road ribbon with visible pale road surface, no sky ceiling.
  Training-pose comparisons (`unity_bundle/check/compare_s14_v4_montage.png`, `compare_s08_v4_montage.png`): road plane coherent,
  sky transparent, no floaters; soft/blurry (4500 steps). Driver-height views on the merged file still weak.
- Guardian crontab removed; session crons removed; monitors stopped. Old bundle `unity_bundle/` (sky-ceiling models) is obsolete.
- Open: centreline/placement still from SfM poses while the trained content follows pose-optimised cameras (3–7 m shifts) →
  `46_centerline_opt.py` (centreline from optimised cams). Placement (31→33→32) should also be refit on optimised cams.
- 2026-09-01 12:32:43 deleted old models (sXX, sXX_gps, s03_v2/v3, amanorthv*, pilot) and unity_bundle/ — 36 GB; kept sXX_v4 + unity_bundle_v4, cubefaces_rgba, lingbot_out, all inputs
