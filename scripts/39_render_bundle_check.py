#!/usr/bin/env python3
"""Render the baked Unity-frame merged PLY from cameras on the road centreline and put the real video
forward face next to it.  Unity is left-handed; gsplat is right-handed, so the render is mirrored back.
Outputs unity_bundle/check/*.png (left: video frame, right: splat render) + montage."""
import csv, json, os, sys
import numpy as np, torch, cv2
from gsplat import rasterization
OUT = 'unity_bundle/check'; os.makedirs(OUT, exist_ok=True)
W = H = 1024; FOV = 110.0; CAM_H = 3.0; LOOK_AHEAD = 12; NEAR = float(os.environ.get("NEAR", "8.0"))

def read_ply(path):
    f = open(path, 'rb'); hdr = b''
    while not hdr.endswith(b'end_header\n'): hdr += f.readline()
    n = int([l for l in hdr.decode().split('\n') if l.startswith('element vertex')][0].split()[-1])
    return np.fromfile(path, dtype=np.float32, offset=len(hdr)).reshape(n, 59)
d = read_ply('unity_bundle/amakeng_merged_unity.ply'); N = len(d); dev = 'cuda'
means = torch.tensor(d[:, :3], device=dev)
sh = torch.cat([torch.tensor(d[:, 3:6]).view(N, 1, 3), torch.tensor(d[:, 6:51]).view(N, 3, 15).transpose(1, 2)], 1).to(dev)
opac = torch.sigmoid(torch.tensor(d[:, 51], device=dev)); scales = torch.exp(torch.tensor(d[:, 52:55], device=dev)); quats = torch.tensor(d[:, 55:59], device=dev)
print(f'loaded {N} splats')
rows = list(csv.DictReader(open('unity_bundle/road_centerline_unity.csv')))
cl = {int(r['frame']): (np.array([float(r['x']), float(r['y']), float(r['z'])]), r['section']) for r in rows}
T = json.load(open('colmap_db/gpx/section_transforms.json'))['sections']
fx = (W / 2) / np.tan(np.radians(FOV / 2)); K = torch.tensor([[fx, 0, W / 2], [0, fx, H / 2], [0, 0, 1]], device=dev, dtype=torch.float32)

C = np.load('colmap_db/gpx/section_cams_enu.npz'); SW = np.array([[1., 0, 0], [0, 0, 1], [0, 1, 0]])
def render_c2w(c2w, mirror=True):
    vm = torch.tensor(np.linalg.inv(c2w), device=dev, dtype=torch.float32)[None]
    with torch.no_grad():
        img, _, _ = rasterization(means, quats, scales, opac, sh, vm, K[None], W, H, sh_degree=3, near_plane=NEAR, far_plane=1000, render_mode='RGB')
    im = (img[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
    if mirror: im = im[:, ::-1]
    return cv2.cvtColor(np.ascontiguousarray(im), cv2.COLOR_RGB2BGR)
def render(pos, fwd):
    f = fwd / np.linalg.norm(fwd); down = np.array([0, -1.0, 0]); right = np.cross(down, f); right /= np.linalg.norm(right); down = np.cross(f, right)
    c2w = np.eye(4); c2w[:3, :3] = np.stack([right, down, f], 1); c2w[:3, 3] = pos
    vm = torch.tensor(np.linalg.inv(c2w), device=dev, dtype=torch.float32)[None]
    with torch.no_grad():
        img, _, _ = rasterization(means, quats, scales, opac, sh, vm, K[None], W, H, sh_degree=3, near_plane=NEAR, far_plane=1000, render_mode='RGB')
    im = (img[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)[:, ::-1]      # mirror back to left-handed view
    return cv2.cvtColor(np.ascontiguousarray(im), cv2.COLOR_RGB2BGR)

frames = [int(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else None
if frames is None:   # mid-sections + every seam mid-overlap frame
    frames = []
    for k in range(1, 19):
        s = f's{k:02d}'; a, b = T[s]['frames']
        if T[s]['status'] != 'drop': frames.append((a + b) // 2)
        if k < 18 and T[f's{k+1:02d}']['status'] != 'drop' and T[s]['status'] != 'drop': frames.append((b + T[f's{k+1:02d}']['frames'][0]) // 2)
tiles = []
for fr in frames:
    if fr not in cl or (fr + LOOK_AHEAD) not in cl: print(f'frame {fr}: not on centreline, skipped'); continue
    p, sec = cl[fr]; q, _ = cl[fr + LOOK_AHEAD]; fwd = q - p; fwd[1] = 0
    if np.linalg.norm(fwd) < 0.5: print(f'frame {fr}: vehicle static, skipped'); continue
    j = np.where(C[f'{sec}_fg'] == fr)[0]
    if len(j):   # exact training pose (ENU) -> mirrored into the Unity-frame data: image comes out un-mirrored
        c2w = np.eye(4); c2w[:3, :3] = SW @ C[f'{sec}_R'][j[0]]; c2w[:3, 3] = SW @ C[f'{sec}_cam'][j[0]]
        r = render_c2w(c2w, mirror=False)
    else:
        r = render(p + [0, CAM_H, 0], fwd)
    loc = fr - T[sec]['frames'][0] + 1; vp = f'cubefaces/{sec}_fwd/c04_{loc:05d}.png'
    v = cv2.imread(vp) if os.path.exists(vp) else np.zeros_like(r)
    if v.shape[:2] != (H, W): v = cv2.resize(v, (W, H))
    tile = np.concatenate([v, r], 1); cv2.putText(tile, f'frame {fr} ({sec} local {loc}) video | render', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 2)
    cv2.imwrite(f'{OUT}/frame_{fr:05d}.png', tile); tiles.append(cv2.resize(tile, (1024, 512))); print(f'frame {fr} {sec} -> {OUT}/frame_{fr:05d}.png')
if tiles:
    rows_ = [np.concatenate(tiles[i:i + 2], 1) if i + 1 < len(tiles) else np.concatenate([tiles[i], np.zeros_like(tiles[i])], 1) for i in range(0, len(tiles), 2)]
    cv2.imwrite(f'{OUT}/montage.png', np.concatenate(rows_, 0)); print('montage written')
