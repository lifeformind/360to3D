#!/usr/bin/env bash
# Wait for the gsplat build, then run pose-optimized training on amanorthv.
set -u
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PY="$PROJECT_DIR/venv/bin/python"
# our pycolmap is built against conda-forge libs
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
LOG="$PROJECT_DIR/logs/gsplat_amanorthv.log"

echo "[runner] waiting for gsplat to become importable"
for i in $(seq 1 120); do
    "$PY" -c "import gsplat" 2>/dev/null && break
    sleep 60
done
"$PY" -c "import gsplat, sys; print('[runner] gsplat', gsplat.__version__)" || {
    echo "[runner] FAIL: gsplat never became importable"; exit 1; }

cd tools/gsplat/examples
exec "$PY" simple_trainer.py default \
    --data-dir "$PROJECT_DIR/colmap_db/amanorthv/gs_scene_tri" \
    --data-factor 1 \
    --result-dir "$PROJECT_DIR/splat_output/amanorthv_gsplat_tri" \
    \
    --post-processing bilateral_grid \
    --save-ply \
    >> "$LOG" 2>&1
