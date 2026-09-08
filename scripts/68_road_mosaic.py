"""Stage 68: push-broom road mosaic with registration, streak masking, atlas tiling."""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.signal import savgol_filter

import importlib
cam67 = importlib.import_module("67_camera_track")

ROOT = Path(__file__).resolve().parents[1]
TEXEL = 0.05
HALF_W = 7.0
D_NEAR, D_FAR = 8.0, 13.0
TILE_SPAN = 204.8
LAT_PX, ROAD_PX = 512, 280
GUTTER = (LAT_PX - ROAD_PX) // 2


def extract_frames(track):
    tmp = Path(tempfile.mkdtemp(prefix="mosaic_"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-ss", str(track["v0"]), "-t", str(track["v1"] - track["v0"] + 0.2),
                    "-i", str(ROOT / "raw" / "3A_AMA North 360_.mp4"),
                    "-vf", f"fps={track['fps']}", "-q:v", "3",
                    str(tmp / "f%04d.jpg")], check=True)
    return tmp


def main():
    track = json.loads((ROOT / "work" / "camera_track.json").read_text())
    calib = json.loads((ROOT / "work" / "camera_calib.json").read_text())
    az0, h_cam = calib["az0_deg"], calib["h_cam_m"]
    interp = cam67.make_interp()
    frames = track["frames"]
    tmp = extract_frames(track)

    lat = (np.arange(ROAD_PX) + 0.5) * TEXEL - HALF_W
    s_lo = frames[0]["s"] - D_NEAR - 1
    s_hi = frames[-1]["s"] - D_NEAR + 1
    n_s = int((s_hi - s_lo) / TEXEL)
    near = np.zeros((ROAD_PX, n_s, 3), np.float32)
    far = np.zeros_like(near)
    have = np.zeros(n_s, bool)
    strip_of = np.full(n_s, -1)

    for k, f in enumerate(frames):
        p = tmp / f"f{k + 1:04d}.jpg"
        if not p.exists():
            continue
        img = np.asarray(Image.open(p))
        cam = np.array([f["x"], f["y"], f["z"] + h_cam])
        for D, dest in ((D_NEAR, near), (D_FAR, far)):
            a = f["s"] - D - 0.55
            cols = np.arange(max(0, int((a - s_lo) / TEXEL)),
                             min(n_s, int((a + 1.1 - s_lo) / TEXEL)))
            if not len(cols):
                continue
            s_vals = s_lo + (cols + 0.5) * TEXEL
            strip = cam67.sample_strip(img, cam, az0, interp, s_vals, lat)
            # exposure gain: normalize each strip's own luminance to 128
            # independently (near and far are different frames, so they need
            # their own gain, not a shared one)
            gain = 128.0 / max(20.0, strip.mean())
            dest[:, cols] = np.clip(strip * gain, 0, 255)
            if D == D_NEAR:
                have[cols] = True
                strip_of[cols] = k

    # --- registration: NCC pairwise (high-pass) + absolute road-centring ---
    CH = 20  # 1 m chunks
    nch = n_s // CH
    grey = near.mean(axis=2)
    rel = np.zeros(nch)
    for i in range(1, nch):
        a = grey[:, (i - 1) * CH:i * CH].mean(axis=1)
        b = grey[:, i * CH:(i + 1) * CH].mean(axis=1)
        shifts = range(-10, 11)
        scores = [np.corrcoef(a[10:-10], np.roll(b, sh)[10:-10])[0, 1] for sh in shifts]
        rel[i] = list(shifts)[int(np.argmax(scores))]
    acc = np.cumsum(rel)
    hp_win = min(nch - (1 - nch % 2), 61)
    if hp_win % 2 == 0:
        hp_win -= 1
    hp_win = max(hp_win, 5)
    acc -= savgol_filter(acc, hp_win, 2)  # high-pass

    centres = np.full(nch, ROAD_PX / 2)
    for i in range(nch):
        chunk = near[:, i * CH:(i + 1) * CH]
        g = chunk[..., 1] - (chunk[..., 0] + chunk[..., 2]) / 2
        prof = g.mean(axis=1)
        idx = np.where(prof < np.percentile(prof, 40))[0]
        if len(idx) > 20:
            centres[i] = idx.mean()
    win = min(nch - (1 - nch % 2), 31)
    if win % 2 == 0:
        win -= 1
    win = max(win, 5)
    centres = np.clip(savgol_filter(centres, win, 2), ROAD_PX / 2 - 60, ROAD_PX / 2 + 60)

    out = np.zeros_like(near)
    outf = np.zeros_like(far)
    for i in range(nch):
        shift = int(round(ROAD_PX / 2 - centres[i] + acc[i]))
        sl = slice(i * CH, (i + 1) * CH)
        out[:, sl] = np.roll(near[:, sl], shift, axis=0)
        outf[:, sl] = np.roll(far[:, sl], shift, axis=0)

    # --- streak mask: near/far disagreement (structural, exposure-invariant) ---
    # -> along-track median inpaint
    from scipy.ndimage import gaussian_filter
    hp_n = out - gaussian_filter(out, sigma=(4, 4, 0))
    hp_f = outf - gaussian_filter(outf, sigma=(4, 4, 0))
    diff = np.abs(hp_n - hp_f).mean(axis=2)
    thresh = np.percentile(diff, 97.0)
    mask = diff > thresh
    if mask.any():
        from scipy.ndimage import binary_dilation, median_filter
        mask = binary_dilation(mask, iterations=1)
    print(f"streak fraction: {mask.mean():.1%}")
    assert mask.mean() < 0.15, f"streak mask covers {mask.mean():.0%} - near/far disagreement is systematic, not object streaks"
    if mask.any():
        med = median_filter(out, size=(1, 41, 1))
        out[mask] = med[mask]

    # --- QA report + atlas tiles ---
    rep = Image.fromarray(out.astype(np.uint8)).resize((2250, 140))
    rep.save(ROOT / "work" / "mosaic_report.png")

    outdir = ROOT / "export" / "road_albedo"
    outdir.mkdir(parents=True, exist_ok=True)
    tiles = sorted({int(s // TILE_SPAN) for s in (s_lo + 1, s_hi - 1)})
    for k in tiles:
        tile = np.zeros((LAT_PX, 4096, 3), np.uint8)
        t0 = k * TILE_SPAN
        c0 = int((t0 - s_lo) / TEXEL)
        src_a, src_b = max(0, c0), min(n_s, c0 + 4096)
        dst_a = src_a - c0
        tile[GUTTER:GUTTER + ROAD_PX, dst_a:dst_a + (src_b - src_a)] = \
            out[:, src_a:src_b].astype(np.uint8)
        tile[:GUTTER] = tile[GUTTER]
        tile[GUTTER + ROAD_PX:] = tile[GUTTER + ROAD_PX - 1]
        Image.fromarray(tile).save(outdir / f"tile_{k:02d}.png")
    (outdir / "atlas_meta.json").write_text(json.dumps(dict(
        texel_m=TEXEL, tile_span_m=TILE_SPAN, lateral_half_m=HALF_W,
        lateral_px=LAT_PX, road_px=ROAD_PX, tiles=tiles)))
    print(f"tiles {tiles}; coverage {have.mean()*100:.1f}%; streak px {int(mask.sum())}")


if __name__ == "__main__":
    main()
