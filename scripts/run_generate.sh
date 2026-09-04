#!/usr/bin/env bash
# Run all generator stages in order; stop on first failure.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=venv/Scripts/python
$PY scripts/60_prepare_rasters.py
$PY scripts/61_centerline.py
$PY scripts/62_terrain.py
$PY scripts/63_road_mesh.py
echo "generate: all stages OK"
