#!/usr/bin/env python3
"""Extract the driven-route polyline from the annotated satellite map.

Isolates the teal route trace, skeletonizes it, and orders the pixels from
the Start end to the End end with a direction-momentum walk (handles the
route crossing itself). Start = the westernmost skeleton endpoint (the
purple Start label points there); direction is verified visually against
the map's arrows via the gradient overlay this script writes.

Outputs:
  colmap_db/<scene>/route_polyline.json  — ordered [x,y] px + cumulative arc length
  scratchpad overlay PNG for visual verification
Usage: 07_trace_route.py <map.png> <scene> <overlay_out.png>
"""
import json, os, sys
import numpy as np
from PIL import Image
from skimage.morphology import skeletonize, binary_closing, disk

def main(map_path, scene, overlay_out):
    im = np.array(Image.open(map_path).convert("RGB"))
    r, g, b = (im[..., i].astype(int) for i in range(3))
    mask = (g > 120) & (b > 120) & (abs(g - b) < 60) & (r < g - 40) & (r < b - 40)
    mask = binary_closing(mask, disk(3))
    skel = skeletonize(mask)
    ys, xs = np.nonzero(skel)
    pts = set(zip(xs.tolist(), ys.tolist()))
    print(f"route pixels {mask.sum()}, skeleton {len(pts)}")

    def neighbors(p):
        x, y = p
        return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and (x + dx, y + dy) in pts]

    # the direction arrows drawn ON the route cut the skeleton into fragments:
    # order each fragment with a momentum walk, then chain fragments across
    # the gaps by endpoint proximity + heading continuity
    from scipy.ndimage import label as cc_label
    lab, ncomp = cc_label(skel, structure=np.ones((3, 3)))
    comps = []
    for ci in range(1, ncomp + 1):
        cys, cxs = np.nonzero(lab == ci)
        if len(cxs) < 10:
            continue
        comps.append(set(zip(cxs.tolist(), cys.tolist())))
    print(f"{ncomp} raw components, {len(comps)} kept (>=10 px)")

    def order_component(cpts, seed=None):
        def nbrs(p):
            x, y = p
            return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if (dx or dy) and (x + dx, y + dy) in cpts]
        ends = [p for p in cpts if len(nbrs(p)) == 1]
        cur = seed if seed in (ends or []) else (min(ends, key=lambda p: p[0]) if ends else next(iter(cpts)))
        path, visited, heading = [cur], {cur}, np.zeros(2)
        while True:
            cand = [n for n in nbrs(cur) if n not in visited]
            if not cand:
                break
            if len(cand) == 1 or not heading.any():
                nxt = cand[0]
            else:
                def score(n):
                    v = np.array([n[0] - cur[0], n[1] - cur[1]], float)
                    return -float(v / np.linalg.norm(v) @ heading)
                nxt = min(cand, key=score)
            v = np.array([nxt[0] - cur[0], nxt[1] - cur[1]], float)
            heading = 0.7 * heading + 0.3 * v / np.linalg.norm(v)
            n = np.linalg.norm(heading)
            heading = heading / n if n > 0 else heading
            path.append(nxt); visited.add(nxt); cur = nxt
        return np.array(path, float)

    chains = [order_component(c) for c in comps]
    # start with the chain containing the westernmost point, oriented west-first
    starti = min(range(len(chains)), key=lambda i: chains[i][:, 0].min())
    first = chains.pop(starti)
    if first[-1, 0] < first[0, 0]:
        first = first[::-1]
    ordered = [first]
    MAX_GAP = 60.0
    while chains:
        tail = ordered[-1][-1]
        tail_dir = ordered[-1][-1] - ordered[-1][max(-6, -len(ordered[-1]))]
        n = np.linalg.norm(tail_dir)
        tail_dir = tail_dir / n if n > 0 else tail_dir
        best = None
        for i, ch in enumerate(chains):
            for flip in (False, True):
                cand = ch[::-1] if flip else ch
                d = np.linalg.norm(cand[0] - tail)
                if d > MAX_GAP:
                    continue
                v = cand[0] - tail
                cont = float(v / max(np.linalg.norm(v), 1e-9) @ tail_dir) if d > 2 else 1.0
                costv = d - 25.0 * cont
                if best is None or costv < best[0]:
                    best = (costv, i, flip, d)
        if best is None:
            print(f"chaining stopped: {len(chains)} fragments unreached "
                  f"(likely label leader-lines or noise): sizes {[len(c) for c in chains]}")
            break
        _, i, flip, d = best
        nxt = chains.pop(i)
        if flip:
            nxt = nxt[::-1]
        print(f"  chained fragment len={len(nxt)} across {d:.0f}px gap")
        ordered.append(nxt)
    P = np.concatenate(ordered)
    # light smoothing + uniform resample every ~3 px of arc length
    from scipy.ndimage import gaussian_filter1d
    P = gaussian_filter1d(P, sigma=3, axis=0, mode="nearest")
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    su = np.arange(0, total, 3.0)
    Pu = np.stack([np.interp(su, s, P[:, 0]), np.interp(su, s, P[:, 1])], 1)
    print(f"ordered path: {len(P)} px, arc length {total:.0f} px, resampled {len(Pu)} pts")
    print(f"start {P[0].round(0)}, end {P[-1].round(0)}, coverage {len(P)}/{len(pts)} skeleton px")

    outdir = f"colmap_db/{scene}"
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/route_polyline.json", "w") as f:
        json.dump({"map": os.path.basename(map_path),
                   "points_px": Pu.tolist(),
                   "arclength_px": su.tolist(),
                   "total_px": float(total)}, f)

    # gradient overlay: blue -> red along travel direction
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(im)
    ax.scatter(Pu[:, 0], Pu[:, 1], c=np.linspace(0, 1, len(Pu)), cmap="coolwarm", s=4)
    ax.plot(*P[0], "g^", ms=14, label="traced start")
    ax.plot(*P[-1], "rs", ms=12, label="traced end")
    ax.legend(); ax.set_title("traced route: blue=start of travel, red=end")
    ax.axis("off")
    plt.tight_layout(); plt.savefig(overlay_out, dpi=90)
    print(f"overlay: {overlay_out}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
