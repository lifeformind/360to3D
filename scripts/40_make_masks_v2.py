#!/usr/bin/env python3
"""Corrected training masks: vehicle hull (static per yaw face) + sky (SegFormer, per frame). Road is NOT masked.

The original make_masks.py masks were optical-flow based; low flow also means the focus of expansion, so they blanked
the road ahead/behind (42-75 % of every face). This rebuilds the RGBA training set with alpha = keep.

Usage: 40_make_masks_v2.py --sec s03 [--samples 80] [--hull-std 16] [--sky-dilate 3] [--src colmap_db/<sec>/gs_scene]
Writes colmap_db/<sec>/gs_scene_v2/images/*.png (RGBA), symlinks sparse/, preview unity_bundle/check/masks_v2_<sec>.png
"""
import argparse, os, glob, time
import numpy as np, cv2, torch
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

ap = argparse.ArgumentParser()
ap.add_argument('--sec', required=True); ap.add_argument('--samples', type=int, default=80)
ap.add_argument('--hull-ratio', type=float, default=0.6, help='median-sharpness / frame-sharpness above which a textured pixel is rigid')
ap.add_argument('--hull-tex', type=float, default=6.0, help='min mean gradient magnitude for the ratio test to count')
ap.add_argument('--hull-flat-std', type=float, default=0.0, help='temporal std below which a textureless pixel counts as painted hull')
ap.add_argument('--hull-paint-dist', type=float, default=0.0, help='colour distance (0-255 RGB) to hull paint for region growing in the lower half')
ap.add_argument('--hull-from', default=None, help='reuse hull_masks.npz of this section instead of detecting')
ap.add_argument('--hull-only', action='store_true', help='only build + preview the hull masks')
ap.add_argument('--hull-freq', type=float, default=0.3, help='SegFormer vehicle-class frequency above which a pixel is hull')
ap.add_argument('--sky-dilate', type=int, default=3); ap.add_argument('--src', default=None); ap.add_argument('--preview-frame', type=int, default=210)
a = ap.parse_args()
SEC = a.sec; SRC = a.src or f'colmap_db/{SEC}/gs_scene'; DST = f'colmap_db/{SEC}/gs_scene_v2'
os.makedirs(f'{DST}/images', exist_ok=True)
if not os.path.exists(f'{DST}/sparse'): os.symlink(os.path.abspath(f'{SRC}/sparse'), f'{DST}/sparse')
names = sorted(os.path.basename(p) for p in glob.glob(f'{SRC}/images/*.png'))
yaws = sorted({n.split('_')[-1][:-4] for n in names})
print(f'{SEC}: {len(names)} images, faces {yaws}')

MODEL = 'nvidia/segformer-b2-finetuned-ade-512-512'
proc = SegformerImageProcessor.from_pretrained(MODEL); model = SegformerForSemanticSegmentation.from_pretrained(MODEL).cuda().eval().half()
id2label = model.config.id2label
SKY = [k for k, v in id2label.items() if v == 'sky'][0]
VEH = [k for k, v in id2label.items() if v in ('car', 'truck', 'van', 'bus')]
def segment(bgrs):   # list of HxWx3 BGR -> list of HxW label maps
    rgb = [cv2.cvtColor(b, cv2.COLOR_BGR2RGB) for b in bgrs]
    inp = proc(images=rgb, return_tensors='pt').to('cuda'); inp['pixel_values'] = inp['pixel_values'].half()
    with torch.no_grad(): logits = model(**inp).logits.float()
    up = torch.nn.functional.interpolate(logits, size=bgrs[0].shape[:2], mode='bilinear', align_corners=False)
    return up.argmax(1).cpu().numpy()

# ---- 1. static hull mask per yaw face ----
if a.hull_from:
    hz = np.load(f'colmap_db/{a.hull_from}/gs_scene_v2/hull_masks.npz'); hull = {y: hz[y] for y in hz.files}
    print(f'hull masks reused from {a.hull_from}: ' + ', '.join(f'{y} {100*hull[y].mean():.0f}%' for y in yaws))
MANUAL = {'Y180': [[(0, 428), (60, 420), (120, 405), (190, 393), (190, 512), (0, 512)]]}   # rear deck, textureless
hull = hull if a.hull_from else {}
for yaw in ([] if a.hull_from else yaws):
    fn = [n for n in names if n.endswith(f'_{yaw}.png')]; step = max(1, len(fn) // a.samples)
    sample = fn[::step][:a.samples]
    ims = [cv2.imread(f'cubefaces/{SEC}/{n}') for n in sample]
    small = np.stack([cv2.resize(im, (512, 512)).astype(np.float32) for im in ims])
    # rigid hull stays sharp in the temporal median; road at the focus of expansion (also low flow / low std) blurs out
    grad = lambda g: cv2.boxFilter(cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)), -1, (15, 15))
    grey = small.mean(-1); med = np.median(grey, 0)
    g_med = grad(med); g_frames = np.mean([grad(f) for f in grey], 0)
    ratio = g_med / (g_frames + 1e-3)
    std = small.std(0).mean(-1)
    veh_freq = np.zeros((512, 512), np.float32)
    for i in range(0, len(ims), 8):
        labs = segment(ims[i:i + 8])
        for l in labs: veh_freq += cv2.resize(np.isin(l, VEH).astype(np.float32), (512, 512), interpolation=cv2.INTER_NEAREST)
    veh_freq /= len(ims)
    rigid = (ratio > a.hull_ratio) & (g_frames > a.hull_tex)
    flat = (std < a.hull_flat_std) & (g_frames < a.hull_tex)      # painted panels: no texture, no change
    cand = (rigid | flat | (veh_freq > a.hull_freq)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, np.ones((41, 41), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand); keep = np.zeros_like(cand)
    for i in range(1, n):   # hull components touch the bottom edge of the face (camera is on the roof)
        if stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] >= 500 and stats[i, cv2.CC_STAT_AREA] > 1500: keep[lab == i] = 1
    # fill enclosed holes (windscreen reflections etc. have high std but are inside the hull)
    # region-grow into painted panels: same colour as the hull paint in the temporal median, connected to the hull
    if a.hull_paint_dist > 0 and keep.any():
        med_rgb = np.median(small, 0); paint = np.median(med_rgb[keep == 1], 0)
        grow = (np.linalg.norm(med_rgb - paint, axis=-1) < a.hull_paint_dist) & (np.arange(512)[:, None] > 0.5 * 512)
        grown = cv2.morphologyEx((keep | grow).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        n2, lab2 = cv2.connectedComponents(grown); keep2 = np.zeros_like(keep)
        for i in range(1, n2):
            if (keep[lab2 == i] == 1).any(): keep2[lab2 == i] = 1
        keep = keep2
    # hole fill from the top of the image; bottom row and the lower halves of the side columns act as walls so
    # textureless panels that touch the frame border still count as enclosed
    ff = keep.copy(); ff[-1, :] = 1; ff[256:, 0] = 1; ff[256:, -1] = 1
    m = np.zeros((514, 514), np.uint8); cv2.floodFill(ff, m, (0, 0), 2)
    if ff[0, 511] != 2: cv2.floodFill(ff, m, (511, 0), 2)
    if ff[0, 256] != 2: cv2.floodFill(ff, m, (256, 0), 2)
    filled = np.where(ff == 2, 0, 1).astype(np.uint8)
    for poly in MANUAL.get(yaw, []):   # known static hull areas with no detectable outline (512-px coords)
        cv2.fillPoly(filled, [np.array(poly, np.int32)], 1)
    filled = cv2.dilate(filled, np.ones((15, 15), np.uint8))
    hull[yaw] = cv2.resize(filled, (1024, 1024), interpolation=cv2.INTER_NEAREST).astype(bool)
    print(f'  hull {yaw}: rigid {100*rigid.mean():.1f}%  segformer-veh {100*(veh_freq > a.hull_freq).mean():.1f}%  -> hull {100*hull[yaw].mean():.1f}%')
    if a.hull_only:
        im = ims[len(ims)//2].copy(); im[hull[yaw]] = (0.4 * im[hull[yaw]] + [0, 0, 150]).astype(np.uint8)
        cv2.putText(im, f'{yaw} hull {100*hull[yaw].mean():.0f}%', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 255, 255), 3)
        hull.setdefault('_tiles', []).append(cv2.resize(im, (512, 512)))
if a.hull_only:
    t = hull.pop('_tiles'); cv2.imwrite(f'unity_bundle/check/hull_v2_{SEC}.png', np.concatenate([np.concatenate(t[:2], 1), np.concatenate(t[2:], 1)], 0)); raise SystemExit

# ---- 2. sky per frame + write RGBA ----
t0 = time.time(); sky_frac = {y: [] for y in yaws}; masked_frac = {y: [] for y in yaws}
ker = np.ones((2 * a.sky_dilate + 1,) * 2, np.uint8)
for i in range(0, len(names), 8):
    batch = names[i:i + 8]; ims = [cv2.imread(f'cubefaces/{SEC}/{n}') for n in batch]
    labs = segment(ims)
    for n, im, l in zip(batch, ims, labs):
        yaw = n.split('_')[-1][:-4]
        sky = cv2.dilate((l == SKY).astype(np.uint8), ker).astype(bool)
        masked = sky | hull[yaw]
        rgba = np.dstack([im, np.where(masked, 0, 255).astype(np.uint8)])
        cv2.imwrite(f'{DST}/images/{n}', rgba)
        sky_frac[yaw].append(sky.mean()); masked_frac[yaw].append(masked.mean())
    if i % 400 == 0: print(f'  {i}/{len(names)}  {time.time()-t0:.0f}s')
for y in yaws: print(f'  {y}: sky {100*np.mean(sky_frac[y]):.1f}%  total masked {100*np.mean(masked_frac[y]):.1f}%  (old masks: 42-75%)')

# ---- 3. preview ----
tiles = []
for yaw in yaws:
    n = f'c04_{a.preview_frame:05d}_{yaw}.png'
    if not os.path.exists(f'{DST}/images/{n}'): continue
    rgba = cv2.imread(f'{DST}/images/{n}', cv2.IMREAD_UNCHANGED); im = rgba[..., :3].copy(); al = rgba[..., 3] == 0
    im[al & hull[yaw]] = (0.4 * im[al & hull[yaw]] + [0, 0, 150]).astype(np.uint8)
    im[al & ~hull[yaw]] = (0.4 * im[al & ~hull[yaw]] + [150, 0, 0]).astype(np.uint8)
    cv2.putText(im, f'{yaw} masked {100*al.mean():.0f}% (hull red, sky blue)', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 255, 255), 3)
    tiles.append(cv2.resize(im, (512, 512)))
os.makedirs('unity_bundle/check', exist_ok=True)
cv2.imwrite(f'unity_bundle/check/masks_v2_{SEC}.png', np.concatenate([np.concatenate(tiles[:2], 1), np.concatenate(tiles[2:], 1)], 0))
np.savez(f'{DST}/hull_masks.npz', **{y: hull[y] for y in yaws})
print(f'done -> {DST}  ({time.time()-t0:.0f}s)')
