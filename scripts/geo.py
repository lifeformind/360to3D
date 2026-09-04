"""ENU frame shared by every generator stage. Conventions: spec 'Coordinate conventions'."""
import numpy as np

LAT0 = 1.4064823
LON0 = 103.71559285
R = 6378137.0  # WGS-84 semi-major; matches raw/gpx_004.npz to <0.2 mm

GRID = dict(xmin=-160.0, xmax=1152.0, ymin=-320.0, ymax=352.0,
            px=0.5, width=2624, height=1344)


def latlon_to_enu(lat, lon):
    x = np.radians(np.asarray(lon) - LON0) * np.cos(np.radians(LAT0)) * R
    y = np.radians(np.asarray(lat) - LAT0) * R
    return x, y


def enu_to_latlon(x, y):
    lon = LON0 + np.degrees(np.asarray(x) / (np.cos(np.radians(LAT0)) * R))
    lat = LAT0 + np.degrees(np.asarray(y) / R)
    return lat, lon
