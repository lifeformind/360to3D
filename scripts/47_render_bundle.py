#!/usr/bin/env python3
"""Render a Unity bundle (merged PLY, Unity frame) from above and from driver height along its centreline.
Usage: 47_render_bundle.py <bundle_dir> [near_m=4] [cam_h=1.8]  -> <bundle_dir>/check_whole_track.png"""
import sys, numpy as np, torch, cv2, csv
from gsplat import rasterization
B = sys.argv[1]; NEAR = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0; CAMH = float(sys.argv[3]) if len(sys.argv) > 3 else 1.8
def read_ply(path):
    f = open(path, 'rb'); h = b''
    while not h.endswith(b'end_header\n'): h += f.readline()
    n = int([l for l in h.decode().split('\n') if l.startswith('element vertex')][0].split()[-1])
    return np.fromfile(path, dtype=np.float32, offset=len(h)).reshape(n, 59)
d = read_ply(f'{B}/amakeng_merged_unity.ply'); N = len(d); dev = 'cuda'
g = (torch.tensor(d[:, :3], device=dev), torch.tensor(d[:, 55:59], device=dev), torch.exp(torch.tensor(d[:, 52:55], device=dev)), torch.sigmoid(torch.tensor(d[:, 51], device=dev)),
     torch.cat([torch.tensor(d[:, 3:6]).view(N, 1, 3), torch.tensor(d[:, 6:51]).view(N, 3, 15).transpose(1, 2)], 1).to(dev))
rows = list(csv.DictReader(open(f'{B}/road_centerline_unity.csv'))); C = np.array([[float(r['x']), float(r['y']), float(r['z'])] for r in rows]); F = np.array([int(r['frame']) for r in rows])
def render(pos, look, W=1600, H=1000, fov=70, near=4.0, bg=0.5):
    f = look - pos; f /= np.linalg.norm(f); upw = np.array([0, 0, 1.]) if abs(f[1]) > 0.99 else np.array([0, 1., 0]); right = np.cross(f, upw); right /= np.linalg.norm(right); down = np.cross(f, right)
    c2w = np.eye(4); c2w[:3, :3] = np.stack([right, down, f], 1); c2w[:3, 3] = pos
    fx = (W / 2) / np.tan(np.radians(fov / 2)); K = torch.tensor([[fx, 0, W / 2], [0, fx, H / 2], [0, 0, 1]], device=dev, dtype=torch.float32)
    vm = torch.tensor(np.linalg.inv(c2w), device=dev, dtype=torch.float32)[None]
    with torch.no_grad(): img, _, _ = rasterization(*g, vm, K[None], W, H, sh_degree=3, near_plane=near, far_plane=5000, render_mode='RGB', backgrounds=torch.full((1, 3), bg, device=dev))
    im = (img[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)[:, ::-1]   # right-handed renderer -> mirror back to Unity's view
    return cv2.cvtColor(np.ascontiguousarray(im), cv2.COLOR_RGB2BGR)
def lab(im, t): cv2.putText(im, t, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 255), 3); return im
cen = C.mean(0); tiles = [lab(render(cen + [0, 900, 0], cen, near=50, bg=0.2), f'{B}: 900 m above, north up')]
p0 = C[0]; fwd = C[300] - p0; fwd[1] = 0; fwd /= np.linalg.norm(fwd)
tiles.append(lab(render(p0 - 80 * fwd + [0, 60, 0], p0 + 60 * fwd, near=10), 'oblique over start, 60 m up'))
for fr, name in [(600, 's02'), (2000, 's05/s06'), (3800, 's11/s12'), (4900, 's14'), (5600, 's16'), (6200, 's18')]:
    i = int(np.searchsorted(F, fr)); q0 = C[i]; j = min(i + 150, len(C) - 1); fw = C[j] - q0; fw[1] = 0
    if np.linalg.norm(fw) < 1: j = min(i + 400, len(C) - 1); fw = C[j] - q0; fw[1] = 0
    fw /= np.linalg.norm(fw); tiles.append(lab(render(q0 + [0, CAMH, 0], q0 + 40 * fw + [0, CAMH, 0], fov=90, near=NEAR), f'driver view frame {fr} ({name}), {CAMH} m up, near {NEAR} m'))
rows_ = [np.concatenate(tiles[i:i + 2], 1) for i in range(0, len(tiles), 2)]
cv2.imwrite(f'{B}/check_whole_track.png', np.concatenate(rows_, 0)); print('written', f'{B}/check_whole_track.png')
