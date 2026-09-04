#!/usr/bin/env python3
"""Analytic road-depth supervision: the camera sits a fixed height above the road (rig on the roof), so for every
ground pixel the depth is the ray/ground-plane intersection — no learned depth, no scale drift.

For each training image: SegFormer ground classes ∩ keep-mask ∩ depression angle > MIN_DEPR → up to N pixels with
z-depth (in the scene's normalised units) → colmap_db/<sec>/gs_scene_v2/road_depth/<image>.npz (points (M,2) xy px,
depths (M,)). datasets/colmap.py uses these instead of SfM projections when the file exists (--depth_loss).

Usage: 43_road_depth.py --sec s03 [--cam-h 3.09] [--min-depr 12] [--n 4000]
Ground-plane assumption: road plane parallel to the vehicle floor (camera y-axis = down), height from
colmap_db/gpx/section_cams_enu.npz (<sec>_cam_h, metres) and metres-per-unit from section_transforms.json.
"""
import argparse, os, glob, json, time
import numpy as np, cv2, torch
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
import pycolmap

ap = argparse.ArgumentParser()
ap.add_argument('--sec', required=True); ap.add_argument('--cam-h', type=float, default=None); ap.add_argument('--min-depr', type=float, default=12.0)
ap.add_argument('--n', type=int, default=4000); ap.add_argument('--preview-frame', type=int, default=210)
a = ap.parse_args(); SEC = a.sec; SCENE = f'colmap_db/{SEC}/gs_scene_v2'; OUT = f'{SCENE}/road_depth'; os.makedirs(OUT, exist_ok=True)

C = np.load('colmap_db/gpx/section_cams_enu.npz'); cam_h = a.cam_h or float(C[f'{SEC}_cam_h'])
M = np.array(json.load(open('colmap_db/gpx/section_transforms.json'))['sections'][SEC]['M_ply_to_enu']); m_per_unit = float(np.cbrt(np.linalg.det(M[:3, :3])))
# The training scene is the normalised frame: Parser(normalize=True) scales the COLMAP model by 'scale' (rescale to unit-ish
# box).  Recover that factor exactly as datasets/colmap.py does (similarity transform from the camera positions).
import sys; sys.path.insert(0, 'tools/gsplat/examples'); from datasets.colmap import Parser
P = Parser(SCENE, factor=1, normalize=True, test_every=8)
h_norm = cam_h / m_per_unit
print(f'{SEC}: camera height {cam_h:.2f} m = {h_norm:.5f} normalised units ({m_per_unit:.0f} m/unit); depression > {a.min_depr} deg -> depth < {cam_h/np.sin(np.radians(a.min_depr)):.1f} m')

MODEL = 'nvidia/segformer-b2-finetuned-ade-512-512'
proc = SegformerImageProcessor.from_pretrained(MODEL); model = SegformerForSemanticSegmentation.from_pretrained(MODEL).cuda().eval().half()
GROUND = [6, 9, 11, 13, 29, 46, 52, 91, 94]   # road, grass, sidewalk, earth, field, sand, path, dirt track, land
def segment(bgrs):
    rgb = [cv2.cvtColor(b, cv2.COLOR_BGR2RGB) for b in bgrs]
    inp = proc(images=rgb, return_tensors='pt').to('cuda'); inp['pixel_values'] = inp['pixel_values'].half()
    with torch.no_grad(): logits = model(**inp).logits.float()
    return torch.nn.functional.interpolate(logits, size=bgrs[0].shape[:2], mode='bilinear', align_corners=False).argmax(1).cpu().numpy()

names = sorted(os.path.basename(p) for p in glob.glob(f'{SCENE}/images/*.png'))
K = P.Ks_dict[P.camera_ids[0]]; W, H = P.imsize_dict[P.camera_ids[0]]
u, v = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
dirs = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones_like(u)], -1); dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
# mount orientation: gravity direction expressed in camera coordinates, median over the section (the vehicle follows the
# road grade, so the section-constant mount tilt is what we need, not per-frame gravity)
R = M[:3, :3] / m_per_unit; up_norm = R.T @ np.array([0, 0, 1.0])
g_cam = np.array([c2w[:3, :3].T @ (-up_norm) for c2w in P.camtoworlds]); g_cam /= np.linalg.norm(g_cam, axis=1, keepdims=True)
down = np.median(g_cam, 0); down /= np.linalg.norm(down)
print(f'mount: camera "down" = {np.round(down, 3)} (pitch {np.degrees(np.arctan2(down[2], down[1])):+.1f} deg, roll {np.degrees(np.arctan2(down[0], down[1])):+.1f} deg); per-frame scatter {np.degrees(np.arccos(np.clip(g_cam @ down, -1, 1))).std():.1f} deg')
cosd = dirs @ down
depr = np.degrees(np.arcsin(np.clip(cosd, -1, 1)))
zdepth = np.where(cosd > 1e-3, h_norm / np.maximum(cosd, 1e-3) * dirs[..., 2], np.nan)   # z-depth of the ground-plane hit
rng = np.random.default_rng(0); t0 = time.time(); stats = []
for i in range(0, len(names), 8):
    batch = names[i:i + 8]; rgba = [cv2.imread(f'{SCENE}/images/{n}', cv2.IMREAD_UNCHANGED) for n in batch]
    labs = segment([r[..., :3] for r in rgba])
    for n, r, l in zip(batch, rgba, labs):
        ok = np.isin(l, GROUND) & (r[..., 3] == 255) & (depr > a.min_depr) & np.isfinite(zdepth)
        ys, xs = np.nonzero(ok)
        if len(ys) > a.n: sel = rng.choice(len(ys), a.n, replace=False); ys, xs = ys[sel], xs[sel]
        np.savez(f'{OUT}/{n[:-4]}.npz', points=np.stack([xs + 0.5, ys + 0.5], 1).astype(np.float32), depths=zdepth[ys, xs].astype(np.float32))
        stats.append((ok.mean(), len(ys)))
    if i % 400 == 0: print(f'  {i}/{len(names)} {time.time()-t0:.0f}s')
st = np.array(stats); print(f'done: ground-supervised pixels {100*st[:,0].mean():.1f}% of image on average, {int(st[:,1].mean())} samples/image; images with <100 samples: {(st[:,1]<100).sum()}')
# preview
tiles = []
for yaw in ['Y000', 'Y090', 'Y180', 'Y270']:
    n = f'c04_{a.preview_frame:05d}_{yaw}'; z = np.load(f'{OUT}/{n}.npz'); im = cv2.imread(f'{SCENE}/images/{n}.png')
    d_m = z['depths'] * m_per_unit
    for (x, y), dm in zip(z['points'][::4], d_m[::4]):
        c = cv2.applyColorMap(np.uint8([[int(255 * min(dm, 15) / 15)]]), cv2.COLORMAP_JET)[0, 0]; cv2.circle(im, (int(x), int(y)), 2, tuple(int(k) for k in c), -1)
    cv2.putText(im, f'{yaw} road depth 0..15 m (jet), {len(d_m)} pts', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3); tiles.append(cv2.resize(im, (512, 512)))
cv2.imwrite(f'unity_bundle/check/road_depth_{SEC}.png', np.concatenate([np.concatenate(tiles[:2], 1), np.concatenate(tiles[2:], 1)], 0))
