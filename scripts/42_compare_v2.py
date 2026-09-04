#!/usr/bin/env python3
"""Compare the original section splat with the corrected-mask / near-plane retrain, at training poses and at
driver-like novel views (camera lowered and shifted), against the video frame.

Usage: 42_compare_v2.py <sec> [tag=v2] [new_near=0.001] [frame_local ...]     (defaults: 6 spread frames)
Renders in the section's normalised frame (Parser normalize=True), old model with near=0.01 (as trained) and
new model with near=0.001.  Output: unity_bundle/check/compare_<sec>_v2_*.png + montage.
"""
import os, sys, json, numpy as np, torch, cv2
sys.path.insert(0, 'tools/gsplat/examples'); from datasets.colmap import Parser
from gsplat import rasterization

SEC = sys.argv[1]; TAG = sys.argv[2] if len(sys.argv) > 2 else 'v2'; NEW_NEAR = float(sys.argv[3]) if len(sys.argv) > 3 else 0.001
frames = [int(a) for a in sys.argv[4:]] or None
OUT = 'unity_bundle/check'; dev = 'cuda'
def read_ply(path):
    f = open(path, 'rb'); h = b''
    while not h.endswith(b'end_header\n'): h += f.readline()
    n = int([l for l in h.decode().split('\n') if l.startswith('element vertex')][0].split()[-1])
    return np.fromfile(path, dtype=np.float32, offset=len(h)).reshape(n, 59)
def to_t(d):
    N = len(d)
    sh = torch.cat([torch.tensor(d[:, 3:6]).view(N, 1, 3), torch.tensor(d[:, 6:51]).view(N, 3, 15).transpose(1, 2)], 1).to(dev)
    return (torch.tensor(d[:, :3], device=dev), torch.tensor(d[:, 55:59], device=dev), torch.exp(torch.tensor(d[:, 52:55], device=dev)),
            torch.sigmoid(torch.tensor(d[:, 51], device=dev)), sh)
def render(g, c2w, K, W, H, near):
    vm = torch.tensor(np.linalg.inv(c2w), device=dev, dtype=torch.float32)[None]
    with torch.no_grad():
        img, _, _ = rasterization(*g, vm, torch.tensor(K, device=dev, dtype=torch.float32)[None], W, H, sh_degree=3, near_plane=near, render_mode='RGB')
    return cv2.cvtColor((img[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)

p = Parser(f'colmap_db/{SEC}/gs_scene', factor=1, normalize=True, test_every=8)
scale = float(np.cbrt(abs(np.linalg.det(p.transform[:3, :3]))))          # normalised units per old unit
M = np.array(json.load(open('colmap_db/gpx/section_transforms.json'))['sections'][SEC]['M_ply_to_enu'])
m_per_unit = float(np.cbrt(np.linalg.det(M[:3, :3])))                         # metres per normalised unit
print(f'{SEC}: {m_per_unit:.0f} m per normalised unit; old near plane 0.01 = {0.01*m_per_unit:.1f} m, new 0.001 = {0.001*m_per_unit:.2f} m')
def rot6d(d6):
    a1, a2 = d6[:3], d6[3:]; b1 = a1 / np.linalg.norm(a1); b2 = a2 - np.dot(b1, a2) * b1; b2 /= np.linalg.norm(b2); b3 = np.cross(b1, b2)
    return np.stack([b1, b2, b3], 0)
def load_pose_adjust(tag):
    ckp = max(__import__('glob').glob(f'splat_output/{tag}/ckpts/ckpt_*_rank0.pt'), key=lambda q: int(q.split('ckpt_')[-1].split('_')[0]))
    ck = torch.load(ckp, map_location='cpu', weights_only=False)
    return ck['pose_adjust']['embeds.weight'].float().numpy()
train_idx = np.array([i for i in range(len(p.image_names)) if i % 8 != 0])
def adjusted(c2w, i, emb):     # replicate gsplat CameraOptModule.forward for training image index i
    pos = np.where(train_idx == i)[0]
    if len(pos) == 0: return c2w, False
    d = emb[pos[0]]; T = np.eye(4); T[:3, :3] = rot6d(d[3:] + np.array([1, 0, 0, 0, 1, 0.])); T[:3, 3] = d[:3]
    return c2w @ T, True
emb_old, emb_new = load_pose_adjust(SEC), load_pose_adjust(f'{SEC}_{TAG}')
assert len(emb_old) == len(train_idx) == len(emb_new), (len(emb_old), len(train_idx))
old = to_t(read_ply(f'splat_output/{SEC}/ply/point_cloud_29999.ply'))
newp = max(__import__('glob').glob(f'splat_output/{SEC}_{TAG}/ply/point_cloud_*.ply'), key=lambda q: int(q.split('_')[-1][:-4])); new = to_t(read_ply(newp)); print('new model:', newp)
names = [n for n in p.image_names if n.endswith('_Y000.png')]
locals_ = [int(n[4:9]) for n in names]
if frames is None: frames = [locals_[int(i)] for i in np.linspace(0, len(locals_) - 1, 6)]
frames = [f for f in frames if p.image_names.index(f'c04_{f:05d}_Y000.png') % 8 != 0] or [locals_[1]]   # training views only (pose deltas exist)
tiles = []
for fr in frames:
    i = p.image_names.index(f'c04_{fr:05d}_Y000.png'); c2w = p.camtoworlds[i]; K = p.Ks_dict[p.camera_ids[i]]; W, H = p.imsize_dict[p.camera_ids[i]]
    v = cv2.imread(f'cubefaces/{SEC}/c04_{fr:05d}_Y000.png')
    c2w_o, _ = adjusted(c2w, i, emb_old); c2w_n, _ = adjusted(c2w, i, emb_new)
    print(f'frame {fr}: pose-opt shift old {np.linalg.norm(c2w_o[:3,3]-c2w[:3,3])*m_per_unit:.1f} m, new {np.linalg.norm(c2w_n[:3,3]-c2w[:3,3])*m_per_unit:.1f} m')
    a = render(old, c2w_o, K, W, H, 0.01); b = render(new, c2w_n, K, W, H, NEW_NEAR)
    # driver-like novel view: 1.5 m lower, 1.2 m to the right, same orientation (in normalised units)
    co = c2w_o.copy(); co[:3, 3] += (1.5 * co[:3, 1] + 1.2 * co[:3, 0]) / m_per_unit
    cn = c2w_n.copy(); cn[:3, 3] += (1.5 * cn[:3, 1] + 1.2 * cn[:3, 0]) / m_per_unit
    a2 = render(old, co, K, W, H, 0.01); b2 = render(new, cn, K, W, H, NEW_NEAR)
    for im, t in [(v, f'video {SEC} f{fr}'), (a, 'OLD @train pose (near 8 m)'), (b, f'NEW {TAG} @train pose (near {NEW_NEAR*m_per_unit:.1f} m)'), (a2, 'OLD novel: 1.5 m down 1.2 m right'), (b2, 'NEW novel: same')]:
        cv2.putText(im, t, (15, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
    row = np.concatenate([v, a, b, a2, b2], 1); cv2.imwrite(f'{OUT}/compare_{SEC}_{TAG}_{fr:05d}.png', row); tiles.append(cv2.resize(row, (5 * 400, 400)))
    print('frame', fr, 'written')
cv2.imwrite(f'{OUT}/compare_{SEC}_{TAG}_montage.png', np.concatenate(tiles, 0)); print('montage written')
