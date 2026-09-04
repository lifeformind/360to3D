#!/usr/bin/env bash
# Pilot section training: ~15 epochs over ~2000 views, lessons applied.
set -u
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PY="$PROJECT_DIR/venv/bin/python"
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
RESUME=""
CKPT=$(ls -1v "$PROJECT_DIR"/splat_output/pilot/ckpts/ckpt_*_rank0.pt 2>/dev/null | tail -1)
[ -n "$CKPT" ] && RESUME="--resume-ckpt $CKPT"
cd tools/gsplat/examples
exec "$PY" simple_trainer.py default \
    $RESUME \
    --disable-video \
    --disable-viewer \
    --pose-opt --pose-opt-lr 1e-4 \
    --data-dir "$PROJECT_DIR/colmap_db/pilot/gs_scene" \
    --data-factor 1 \
    --result-dir "$PROJECT_DIR/splat_output/pilot" \
    --max-steps 30000 \
    --eval-steps 10000 30000 \
    --save-steps 10000 30000 \
    --strategy.grow-grad2d 0.0001 \
    --strategy.refine-stop-iter 15000 \
    --strategy.reset-every 5000 \
    --post-processing bilateral_grid \
    --save-ply \
    >> "$PROJECT_DIR/logs/pilot_train.log" 2>&1
