"""Stage 60: reproject DTM/DSM into the common 0.5 m ENU grid. All CRS handling lives here."""
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt, map_coordinates

import geo

ROOT = Path(__file__).resolve().parents[1]
G = geo.GRID


def enu_pixel_centers():
    xs = G["xmin"] + (np.arange(G["width"]) + 0.5) * G["px"]
    ys = G["ymax"] - (np.arange(G["height"]) + 0.5) * G["px"]  # row 0 = north
    return np.meshgrid(xs, ys)


def sample_raster(src_path, lat, lon):
    """Bilinear-sample a source raster at lat/lon grids; returns float32 with NaN outside/nodata."""
    with rasterio.open(src_path) as ds:
        band = ds.read(1).astype(np.float64)
        if ds.nodata is not None:
            band[band == ds.nodata] = np.nan
        if ds.crs.to_epsg() == 4326:
            sx, sy = lon, lat
        else:
            tf = pyproj.Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
            sx, sy = tf.transform(lon, lat)
        inv = ~ds.transform
        cols, rows = inv * (sx, sy)
        out = map_coordinates(band, [rows - 0.5, cols - 0.5], order=1, mode="constant", cval=np.nan)
    return out.astype(np.float32)


def fill_nan_nearest(a):
    mask = np.isnan(a)
    if mask.any():
        idx = distance_transform_edt(mask, return_indices=True)[1]
        a = a[tuple(idx)]
    return a


def write(name, data):
    out = ROOT / "work" / name
    out.parent.mkdir(exist_ok=True)
    profile = dict(driver="GTiff", width=G["width"], height=G["height"], count=1,
                   dtype="float32", transform=from_origin(G["xmin"], G["ymax"], G["px"], G["px"]))
    with rasterio.open(out, "w", **profile) as ds:
        ds.write(data, 1)
    print(f"wrote {out}  range {np.nanmin(data):.2f}..{np.nanmax(data):.2f}")


def main():
    X, Y = enu_pixel_centers()
    lat, lon = geo.enu_to_latlon(X, Y)
    dtm = fill_nan_nearest(sample_raster(ROOT / "raw" / "dtm_clip.tif", lat, lon))
    dsm = fill_nan_nearest(sample_raster(ROOT / "raw" / "dsm_clip.tif", lat, lon))
    write("dtm_enu.tif", dtm)
    write("dsm_enu.tif", dsm)
    write("canopy_enu.tif", np.maximum(dsm - dtm, 0.0))


if __name__ == "__main__":
    main()
