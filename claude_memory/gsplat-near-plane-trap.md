---
name: gsplat-near-plane-trap
description: gsplat default near_plane=0.01 is in NORMALISED units (~8 m for these road scenes) — nothing within 8 m of cameras was trained; renders/Unity need a 6-8 m near clip or a retrain with --near_plane 1e-3
metadata:
  type: project
---

All 18 AMAKENG sections (and the s01/s05 GPS retrains) were trained with gsplat's default `near_plane=0.01`, which with
`Parser(normalize=True)` (scene scale ≈ 1/600–1/1100) is ~8 m in metres. Everything within ~8 m of a training camera was
never rasterised during training, so that zone is unconstrained blob junk; with a metric near plane (Unity 0.3 m, gsplat
`near_plane=0.05` on baked-metric PLYs) every view is a flat green/grey wall. Discovered 2026-08-31 while validating
`unity_bundle/`.

**Why:** gsplat's near/far planes are in scene units and the trainer never rescales them; road-driving scenes are long so
the normalisation factor is tiny.

**How to apply:** (1) any render of these splats must use near ≈ 8 m (`NEAR=8` in `scripts/39_render_bundle_check.py`;
Unity camera Near Clip 6–8 m — aras-p clips whole splats by centre depth). (2) Any future training run must pass
`--near_plane 1e-3` (or scale it from `parser.scene_scale`) with corrected masks: gsplat's loader takes RGBA alpha as the loss mask (already used), but the existing optical-flow
masks also blank the road ahead/behind (42–75 % of each face) — regenerate as vehicle-hull (static per face) ∪ SegFormer sky. See [[pipeline-status-amakeng]].
