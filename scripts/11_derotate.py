#!/usr/bin/env python3
"""Derotate direction-stabilized equirect frames to vehicle-locked yaw.

The Insta360 export is FlowState-stabilized: the equirect yaw frame is
world-locked and the vehicle rotates underneath it, which breaks the constant
hull mask and every camera-faces-travel assumption downstream. This script
measures each frame's hull azimuth by circular phase correlation of the hull
band (bottom rows) between consecutive frames, accumulates the shifts, and
rolls each panorama so the hull sits where it does in the REFERENCE frame
(one where the hood is at u=0, i.e. image center = direction of travel).

Usage: 11_derotate.py <src_frames_dir> <dst_frames_dir> [ref_frame_1based]
"""
import os, sys
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d

BAND = (0.55, 0.95)      # hull-dominated rows (fraction of height)
CORR_W = 1024            # correlation working width

def band_gray(path):
    im = Image.open(path).convert("L")
    w, h = im.size
    im = im.resize((CORR_W, CORR_W // 2))
    a = np.asarray(im, np.float32)
    h2 = a.shape[0]
    return a[int(BAND[0] * h2):int(BAND[1] * h2)]

def circ_shift(a, b):
    # horizontal circular shift b->a via phase correlation (columns)
    A = np.fft.fft(a, axis=1)
    B = np.fft.fft(b, axis=1)
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft(R, axis=1).real.sum(0)
    s = int(np.argmax(r))
    return s - CORR_W if s > CORR_W // 2 else s

def main(src, dst, ref=400):
    files = sorted(f for f in os.listdir(src) if f.endswith(".jpg"))
    n = len(files)
    print(f"{n} frames; measuring hull rotation...")
    prev = band_gray(os.path.join(src, files[0]))
    dsh = np.zeros(n)
    for i in range(1, n):
        cur = band_gray(os.path.join(src, files[i]))
        dsh[i] = circ_shift(cur, prev)
        prev = cur
    cum = np.cumsum(dsh)
    cum = gaussian_filter1d(cum, 2)
    cum -= cum[ref - 1]                       # reference frame keeps its yaw
    print(f"cumulative hull shift: min={cum.min():.0f} max={cum.max():.0f} px "
          f"({cum.min()*360/CORR_W:.0f}..{cum.max()*360/CORR_W:.0f} deg)")

    os.makedirs(dst, exist_ok=True)
    for i, f in enumerate(files):
        im = np.asarray(Image.open(os.path.join(src, f)))
        w = im.shape[1]
        shift_px = int(round(-cum[i] * w / CORR_W))
        Image.fromarray(np.roll(im, shift_px, axis=1)).save(
            os.path.join(dst, f), quality=92)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{n}")
    np.save(os.path.join(dst, "hull_yaw_px.npy"), cum)
    print(f"derotated frames -> {dst}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 400)
