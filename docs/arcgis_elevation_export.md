# Exporting the DTM / DSM elevation profile along the GPS track (ArcGIS)

Goal: a table of **elevation along the clip-004 GPS track**, sampled from the real DTM (and
optionally the DSM), so the splat pipeline can replace the screenshot-based terrain calibration
(`scripts/36_dtm_profile.py`) with measured values.

Inputs already prepared in this repo:
- `raw/VID_20260724_152412_00_004.gpx` — the GPS track (532 fixes, 1 Hz, WGS84)
- `raw/track_004.kml` — the same track as a KML line (for tools that want a line feature)

What to hand back: one CSV for the **DTM** (required) and, if easy, one for the **DSM**
(optional — used to cull floaters above the canopy). Drop them in `raw/` as
`dtm_profile.csv` / `dsm_profile.csv` and say which elevation layer was active.

---

## Option A — ArcGIS Pro (preferred): per-fix elevation with timestamps

This keeps the GPS timestamps, which the pipeline syncs against. Best result.

1. **Import the GPX as points**
   *Analysis ▸ Tools ▸ Conversion Tools ▸ From GPS ▸ GPX To Features*
   Input: `VID_20260724_152412_00_004.gpx` → output point feature class (keeps `DateTime`, `Elevation`).
2. **Sample the DTM at each point** — either:
   - *Spatial Analyst ▸ Extraction ▸ Extract Values to Points* (input points = step 1, raster = the DTM), or
   - *3D Analyst ▸ Functional Surface ▸ Add Surface Information* (input = step 1 points, surface = DTM, property = `Z`).
   The DTM may be a local raster or the Vantor elevation layer/service; both work as the raster input.
3. **Export the table**: right-click the resulting point layer ▸ *Data ▸ Export Table* ▸ choose `.csv`.
   Make sure the CSV contains latitude, longitude, `DateTime` and the sampled elevation column
   (`RASTERVALU` or `Z`). If the coordinates are not exported, run *Calculate Geometry* (X/Y in WGS84) first.
4. Repeat step 2–3 with the **DSM** if available → `dsm_profile.csv`.

## Option B — ArcGIS Pro: interactive elevation profile → CSV

Gives distance + elevation along the line (no timestamps, still fine).

1. **Set the DTM as the ground surface**
   - Map: *Map ▸ Add Data ▾ ▸ Elevation Source* → browse to the DTM raster / Vantor elevation service.
   - Scene: right-click the **Elevation Surfaces** header ▸ add the DTM under *Ground*, and switch off
     the default World Elevation so the DTM is what gets sampled.
2. **Add the track line**: *Add Data* → `raw/track_004.kml` (Pro converts it), or GPX To Features + *Points To Line*
   (sort field `DateTime`).
3. **Profile**: *Analysis ▸ Workflows ▸ Exploratory 3D Analysis ▾ ▸ Elevation Profile* → method **Along a Line**
   → select the track line → the profile graph opens.
4. **Export**: in the graph window click **Export Graph ▸ CSV Table** → set destination/name → OK.
5. Repeat with the DSM as ground if available.

## Option C — ArcGIS Earth only (no CSV; image fallback)

ArcGIS Earth cannot export profile values, only a picture of the graph — still better than nothing:

1. *Basemap and Terrain*: terrain on, with the Vantor DTM added as the elevation/terrain source.
2. Add `raw/track_004.kml`; in the table of contents **right-click the KML line ▸ Elevation Profile**
   (also reachable via *Interactive analysis* on the toolbar).
3. Maximise the graph window, then **Export image** → PNG with axis labels visible. Drop it in `raw/`
   as `dtm_profile_chart.png`; it will be digitised against the axes (less accurate than a CSV).

## After the file is in raw/

Tell Claude; the plan is: parse the CSV → replace the screenshot calibration in
`colmap_db/gpx/dtm_profile.npz` → re-run `scripts/32_unity_placement.py` (terrain-aware Unity
placement) → optionally relaunch the GPS retrain (`./scripts/34_retrain_gps.sh`, resumable).

Sources: Esri docs — ArcGIS Pro interactive elevation profile
(https://doc.esri.com/en/arcgis-pro/latest/help/mapping/exploratory-analysis/interactive-elevation-profile.html),
ArcGIS Earth interactive analysis (https://doc.arcgis.com/en/arcgis-earth/use/interactive-analysis.htm),
Esri KB: elevation profile from a GPX in Pro (https://support.esri.com/en-us/knowledge-base/how-to-generate-and-export-an-elevation-profile-view-ch-000034258).

## Option D — QGIS (open source; this is what was actually used, 2026-08-31)

1. **Layer → Add Layer → Add Raster Layer** → DTM (and DSM) GeoTIFF.
2. **Layer → Add Layer → Add Vector Layer** → `raw/VID_20260724_152412_00_004.gpx`, pick the
   `track_points` layer (per-fix timestamps are kept).
3. **Processing Toolbox → Raster analysis → Sample raster values**: input `track_points`,
   raster = DTM, prefix `dtm`. Repeat for the DSM with prefix `dsm`.
4. Right-click the result → **Export → Save Features As…** → CSV. Lat/lon are optional
   (`Geometry: AS_XY`) — the converter matches rows to the GPX by `time`.

Save as `raw/dtm_profile.csv` and `raw/dsm_profile.csv`, then run
`python3 scripts/37_dtm_csv.py` (validates row count / timestamps against `raw/gpx_004.npz`,
backs up the screenshot-derived profile to `colmap_db/gpx/dtm_profile_screenshot.npz`) and
`LD_LIBRARY_PATH=$PWD/tools/miniforge/envs/colmapdeps/lib venv/bin/python scripts/32_unity_placement.py`.

Result of the first real export: DTM 4.8–21.7 m, DSM up to 44 m (trees), GPS altitude sits
16.9 m above the DTM (ellipsoid/geoid offset, std 2.0 m, corr 0.95); the screenshot salvage
had been within 1.8 m rms of it.
