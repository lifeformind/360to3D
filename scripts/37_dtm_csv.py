#!/usr/bin/env python3
"""Replace the screenshot-derived DTM profile with the QGIS per-fix sample CSVs.

Inputs : raw/dtm_profile.csv, raw/dsm_profile.csv  (QGIS 'Sample raster values' on GPX track_points)
Output : colmap_db/gpx/dtm_profile.npz  (t, ele_dtm, ele_dsm, ele_gps, offset_gps_minus_dtm)
Keeps the schema fields 32_unity_placement.py reads: t, ele_dtm.
"""
import csv, os, shutil, sys
from datetime import datetime, timezone
import numpy as np

def load(path, col):
    rows = list(csv.DictReader(open(path)))
    t = np.array([datetime.strptime(r['time'][:19], '%Y/%m/%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp() for r in rows])
    return t - t[0], np.array([float(r['ele']) for r in rows]), np.array([float(r[col]) if r[col] else np.nan for r in rows])

t_dtm, ele_gps, dtm = load('raw/dtm_profile.csv', 'dtm_1')
t_dsm, _, dsm = load('raw/dsm_profile.csv', 'dsm_1')
g = np.load('raw/gpx_004.npz')
assert len(t_dtm) == len(g['t']) == len(t_dsm), (len(t_dtm), len(g['t']), len(t_dsm))
assert np.abs(t_dtm - g['t']).max() < 0.5 and np.abs(t_dsm - g['t']).max() < 0.5, 'CSV timestamps do not match GPX'
assert np.abs(ele_gps - g['ele']).max() < 0.01, 'CSV ele column does not match GPX'
assert not np.isnan(dtm).any(), f'{np.isnan(dtm).sum()} NaN DTM samples'
if np.isnan(dsm).any():
    print(f'[warn] {np.isnan(dsm).sum()} NaN DSM samples, interpolating')
    dsm = np.interp(g['t'], g['t'][~np.isnan(dsm)], dsm[~np.isnan(dsm)])

off = ele_gps - dtm
print(f'DTM  {dtm.min():.1f}..{dtm.max():.1f} m   DSM {dsm.min():.1f}..{dsm.max():.1f} m   DSM-DTM median {np.median(dsm-dtm):.2f} (max {np.max(dsm-dtm):.1f})')
print(f'GPS-DTM offset: median {np.median(off):.2f} m, std {off.std():.2f} m, corr(GPS,DTM)={np.corrcoef(ele_gps, dtm)[0,1]:.3f}')
old = 'colmap_db/gpx/dtm_profile.npz'
if os.path.exists(old):
    o = np.load(old)
    if 'grey' in o.files:  # screenshot-derived version
        bak = 'colmap_db/gpx/dtm_profile_screenshot.npz'; shutil.copy(old, bak)
        d = (o['ele_dtm'] - o['ele_dtm'][0]) - (dtm - dtm[0])
        print(f'vs screenshot calibration (relative to start): rms {np.sqrt(np.mean(d**2)):.2f} m, max {np.abs(d).max():.2f} m  (backup -> {bak})')
np.savez(old, t=g['t'], ele_dtm=dtm, ele_dsm=dsm, ele_gps=ele_gps, offset_gps_minus_dtm=np.median(off))
print(f'wrote {old}  ({len(dtm)} samples, source=QGIS CSV)')
