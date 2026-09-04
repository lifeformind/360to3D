#!/usr/bin/env python3
"""Render-test a trained section: masked train/val PSNR + side-by-sides.
Usage: 20_render_section.py <section>
"""
import sys, torch, numpy as np, os
sys.path.insert(0, 'tools/gsplat/examples')
from datasets.colmap import Parser, Dataset
from gsplat import rasterization
from PIL import Image

sec = sys.argv[1]
ck = torch.load(f'splat_output/{sec}/ckpts/ckpt_29999_rank0.pt', map_location='cuda', weights_only=False)
sp = ck['splats']
means, quats = sp['means'], sp['quats']
scales, opac = torch.exp(sp['scales']), torch.sigmoid(sp['opacities'])
colors = torch.cat([sp['sh0'], sp['shN']], 1)
print(f'[{sec}] gaussians: {len(means)}')
parser = Parser(f'colmap_db/{sec}/gs_scene', factor=1, normalize=True, test_every=8)
os.makedirs(f'splat_output/{sec}/test_renders', exist_ok=True)
for split in ('train', 'val'):
    ds = Dataset(parser, split=split)
    idxs = np.linspace(0, len(ds) - 1, 8).astype(int)
    psnrs = []
    for k, i in enumerate(idxs):
        d = ds[int(i)]
        K = d['K'].cuda()[None]
        viewmat = torch.linalg.inv(d['camtoworld'].cuda())[None]
        img = d['image'].cuda() / 255.0
        H, W = img.shape[:2]
        r, _, _ = rasterization(means, quats, scales, opac, colors, viewmat, K, W, H, sh_degree=3)
        r = r[0].clamp(0, 1)
        rm, imgm = r, img
        if 'mask' in d:
            m = d['mask'].cuda()[..., None].float()
            rm, imgm = r * m, img * m
        psnrs.append(float(-10 * torch.log10(((rm - imgm) ** 2).mean())))
        if k == 4:
            pair = np.concatenate([(r.cpu().numpy() * 255).astype(np.uint8),
                                   (img.cpu().numpy() * 255).astype(np.uint8)], 1)
            Image.fromarray(pair).save(
                f'splat_output/{sec}/test_renders/{split}_mid_psnr{psnrs[-1]:.1f}.jpg', quality=90)
    print(f'[{sec}] {split}: PSNR p50={np.median(psnrs):.2f}')
print(f'[{sec}] RENDER TEST DONE')
