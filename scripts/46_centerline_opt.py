#!/usr/bin/env python3
"""Road centreline from the POSE-OPTIMISED cameras of a trained tag (the splat content follows these, not the SfM poses,
which pose-opt moved by 3-7 m).  Road surface = optimised camera - camera height (the depth loss anchored it there).

Usage: 46_centerline_opt.py <tag>      -> unity_bundle_<tag>/road_centerline_unity.csv (SfM version kept as *_sfm.csv)
"""
import sys, os, json, glob, numpy as np, torch
sys.path.insert(0, 'tools/gsplat/examples'); from datasets.colmap import Parser
TAG = sys.argv[1]; OUT = f'unity_bundle_{TAG}'
T = json.load(open('colmap_db/gpx/section_transforms.json'))['sections']
C = np.load('colmap_db/gpx/section_cams_enu.npz'); SW = np.array([[1., 0, 0], [0, 0, 1], [0, 1, 0]])
def rot6d(d6):
    a1, a2 = d6[:3], d6[3:]; b1 = a1 / np.linalg.norm(a1); b2 = a2 - np.dot(b1, a2) * b1; b2 /= np.linalg.norm(b2); return np.stack([b1, b2, np.cross(b1, b2)], 0)
rows = []; shifts = {}
for sec in [f's{k:02d}' for k in range(1, 19)]:
    cks = glob.glob(f'splat_output/{sec}_{TAG}/ckpts/ckpt_*_rank0.pt')
    if not cks or T[sec]['status'] == 'drop': continue
    ck = torch.load(max(cks, key=lambda q: int(q.split('ckpt_')[-1].split('_')[0])), map_location='cpu', weights_only=False)
    emb = ck['pose_adjust']['embeds.weight'].float().numpy()
    p = Parser(f'colmap_db/{sec}/gs_scene_v2', factor=1, normalize=True, test_every=8)
    M = np.array(T[sec]['M_ply_to_enu']); cam_h = float(C[f'{sec}_cam_h'])
    train_idx = np.array([i for i in range(len(p.image_names)) if i % 8 != 0]); assert len(train_idx) == len(emb)
    A = T[sec]['frames'][0]; d = []
    for pos, i in enumerate(train_idx):
        c2w = p.camtoworlds[i]; e = emb[pos]; Tm = np.eye(4); Tm[:3, :3] = rot6d(e[3:] + np.array([1, 0, 0, 0, 1, 0.])); Tm[:3, 3] = e[:3]
        adj = c2w @ Tm; enu = M[:3, :3] @ adj[:3, 3] + M[:3, 3]; enu0 = M[:3, :3] @ c2w[:3, 3] + M[:3, 3]
        fg = A + int(p.image_names[i][4:9]) - 1
        rows.append((fg, enu[0], enu[2] - cam_h, enu[1], int(sec[1:]))); d.append(np.linalg.norm(enu - enu0))
    shifts[sec] = (float(np.median(d)), float(np.max(d)))
    print(f'{sec}: pose-opt shift median {shifts[sec][0]:.1f} m, max {shifts[sec][1]:.1f} m')
R = np.array(rows); R = R[np.argsort(R[:, 0], kind='stable')]
uf, inv = np.unique(R[:, 0], return_inverse=True)
xyz = np.stack([np.bincount(inv, R[:, c]) / np.bincount(inv) for c in (1, 2, 3)], 1)
sec_of = np.zeros(len(uf), int); sec_of[inv] = R[:, 4]
k = 9; pad = np.pad(xyz, ((k // 2, k // 2), (0, 0)), mode='edge'); xs = np.stack([np.convolve(pad[:, c], np.ones(k) / k, 'valid') for c in range(3)], 1)
old = f'{OUT}/road_centerline_unity.csv'
if os.path.exists(old) and not os.path.exists(old.replace('.csv', '_sfm.csv')): os.rename(old, old.replace('.csv', '_sfm.csv'))
with open(old, 'w') as f:
    f.write('frame,t_video_s,x,y,z,section\n')
    for i in range(len(uf)): f.write(f'{int(uf[i])},{(uf[i]-1)/10:.1f},{xs[i,0]:.3f},{xs[i,1]:.3f},{xs[i,2]:.3f},s{sec_of[i]:02d}\n')
json.dump(shifts, open(f'{OUT}/pose_opt_shifts.json', 'w'), indent=1)
print(f'wrote {old}: {len(uf)} frames (4 faces per frame averaged; only training views)')
