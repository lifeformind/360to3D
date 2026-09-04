#!/usr/bin/env bash
# Long-schedule gsplat training: ~15 epochs, aggressive densification.
set -u
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PY="$PROJECT_DIR/venv/bin/python"
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
RESUME=""
CKPT=$(ls -1v "$PROJECT_DIR"/splat_output/amanorthv_final/ckpts/ckpt_*_rank0.pt 2>/dev/null | tail -1)
[ -n "$CKPT" ] && RESUME="--resume-ckpt $CKPT"
cd tools/gsplat/examples
exec "$PY" simple_trainer.py default \
    $RESUME \
    --disable-video \
    --disable-viewer \
    --data-dir "$PROJECT_DIR/colmap_db/amanorthv/gs_scene_tri" \
    --data-factor 1 \
    --result-dir "$PROJECT_DIR/splat_output/amanorthv_final" \
    --max-steps 80000 \
    --eval-steps 20000 80000 \
    --save-steps 20000 80000 \
    --strategy.grow-grad2d 0.0001 \
    --strategy.refine-stop-iter 40000 \
    --strategy.reset-every 12000 \
    --post-processing bilateral_grid \
    --save-ply \
    >> "$PROJECT_DIR/logs/gsplat_final.log" 2>&1
