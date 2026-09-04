"""Audit raw inputs: DTM/DSM clips, GPX, video; overlay GPX on DTM."""
import numpy as np
import rasterio
import gpxpy
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RAW = Path(__file__).resolve().parents[1] / "raw"

def audit_raster(path):
    with rasterio.open(path) as ds:
        band = ds.read(1, masked=True)
        print(f"\n== {path.name} ==")
        print(f"  CRS:        {ds.crs}")
        print(f"  size:       {ds.width} x {ds.height} px")
        print(f"  pixel size: {ds.res[0]:.4f} x {ds.res[1]:.4f}")
        print(f"  extent:     {ds.bounds}")
        print(f"  nodata:     {ds.nodata}")
        print(f"  range:      {band.min():.2f} .. {band.max():.2f}  (mean {band.mean():.2f})")
        return ds.crs

crs_dtm = audit_raster(RAW / "dtm_clip.tif")
crs_dsm = audit_raster(RAW / "dsm_clip.tif")

# GPX
gpx_files = sorted(RAW.glob("*.gpx"))
for g in gpx_files:
    gp = gpxpy.parse(open(g, encoding="utf-8"))
    pts = [p for t in gp.tracks for s in t.segments for p in s.points]
    lats = [p.latitude for p in pts]; lons = [p.longitude for p in pts]
    print(f"\n== {g.name} ==")
    print(f"  points: {len(pts)}")
    print(f"  lat: {min(lats):.7f} .. {max(lats):.7f}")
    print(f"  lon: {min(lons):.7f} .. {max(lons):.7f}")
    print(f"  time: {pts[0].time} .. {pts[-1].time}")

# npz check
npz = np.load(RAW / "gpx_004.npz")
print(f"\n== gpx_004.npz ==\n  keys: {list(npz.keys())}")
print(f"  n={len(npz['t'])}, t {npz['t'][0]:.1f}..{npz['t'][-1]:.1f}s, "
      f"x {npz['x'].min():.1f}..{npz['x'].max():.1f}, y {npz['y'].min():.1f}..{npz['y'].max():.1f}")

# video
for v in ["3A_AMA North 360_.mp4"]:
    p = RAW / v
    print(f"\n== video ==\n  {v}: {'PRESENT' if p.exists() else 'MISSING'}"
          + (f" ({p.stat().st_size/1e9:.2f} GB)" if p.exists() else ""))

# Overlay GPX on DTM
import pyproj
with rasterio.open(RAW / "dtm_clip.tif") as ds:
    dtm = ds.read(1, masked=True)
    tf = pyproj.Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
    lats = npz["lat"]; lons = npz["lon"]
    X, Y = tf.transform(lons, lats)
    fig, ax = plt.subplots(figsize=(12, 12))
    extent = [ds.bounds.left, ds.bounds.right, ds.bounds.bottom, ds.bounds.top]
    im = ax.imshow(dtm, cmap="terrain", extent=extent, origin="upper")
    ax.plot(X, Y, "r-", lw=1.5, label="GPX track")
    ax.plot(X[0], Y[0], "go", ms=10, label="start")
    ax.plot(X[-1], Y[-1], "ms", ms=10, label="end")
    ax.legend(); ax.set_title(f"GPX over DTM ({ds.crs})")
    plt.colorbar(im, ax=ax, shrink=0.6, label="elev (m)")
    out = RAW.parent / "logs" / "gpx_on_dtm.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"\nOverlay written: {out}")
    # in-bounds check
    inb = ((X >= ds.bounds.left) & (X <= ds.bounds.right) &
           (Y >= ds.bounds.bottom) & (Y <= ds.bounds.top)).mean()
    print(f"GPX points inside DTM extent: {inb*100:.1f}%")
