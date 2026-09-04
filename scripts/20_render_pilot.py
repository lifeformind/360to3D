#!/usr/bin/env python3
"""Render-test the trained pilot section: train/val PSNR + side-by-sides."""
import sys, torch, numpy as np, os
sys.path.insert(0, 'tools/gsplat/examples')
from datasets.colmap import Parser, Dataset
from gsplat import rasterization
from PIL import Image

ck = torch.load('splat_output/pilot/ckpts/ckpt_29999_rank0.pt', map_location='cuda', weights_only=False)
sp = ck['splats']
means, quats = sp['means'], sp['quats']
scales, opac = torch.exp(sp['scales']), torch.sigmoid(sp['opacities'])
colors = torch.cat([sp['sh0'], sp['shN']], 1)
print(f"gaussians: {len(means)}")
parser = Parser('colmap_db/pilot/gs_scene', factor=1, normalize=True, test_every=8)
os.makedirs('splat_output/pilot/test_renders', exist_ok=True)
for split in ('train', 'val'):
    ds = Dataset(parser, split=split)
    idxs = np.linspace(0, len(ds) - 1, 10).astype(int)
    psnrs = []
    for k, i in enumerate(idxs):
        d = ds[int(i)]
        K = d['K'].cuda()[None]
        viewmat = torch.linalg.inv(d['camtoworld'].cuda())[None]
        img = d['image'].cuda() / 255.0
        H, W = img.shape[:2]
        r, _, _ = rasterization(means, quats, scales, opac, colors, viewmat, K, W, H, sh_degree=3)
        r = r[0].clamp(0, 1)
        imgm, rm = img, r
        if 'mask' in d:
            m = d['mask'].cuda()[..., None].float()
            rm, imgm = r * m, img * m
        psnrs.append(float(-10 * torch.log10(((rm - imgm) ** 2).mean())))
        if k in (2, 5, 8):
            pair = np.concatenate([(r.cpu().numpy() * 255).astype(np.uint8),
                                   (img.cpu().numpy() * 255).astype(np.uint8)], 1)
            Image.fromarray(pair).save(
                f'splat_output/pilot/test_renders/{split}_{k}_psnr{psnrs[-1]:.1f}.jpg', quality=90)
    print(f"{split}: PSNR p50={np.median(psnrs):.2f} all={['%.1f' % p for p in psnrs]}")
print("done")
