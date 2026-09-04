#!/usr/bin/env bash
# Supervisor for the amakeng_rig SfM + training pipeline.
# Restarts failed stages up to MAX_TRIES times, then gives up loudly.
# All state judged from log markers, so it can be re-run safely at any time.
set -u
cd "$(dirname "$0")/.."
source scripts/env.sh
SUP_LOG="$LOGS_DIR/supervisor_amakeng_rig.log"
MAX_TRIES=3
note() { echo "[$(date '+%F %T')] $*" >> "$SUP_LOG"; }

sfm_ok()   { grep -q "Rig sparse model" "$LOGS_DIR/run_amakeng_rig.log" 2>/dev/null; }
train_ok() { grep -q "Training complete" "$LOGS_DIR/04_train_amakeng_rig.log" 2>/dev/null; }

# ---- Stage 1: rig SfM ----
tries=0
while ! sfm_ok; do
    if pgrep -f "03b_run_colmap_rig.sh" >/dev/null; then sleep 120; continue; fi
    tries=$((tries+1))
    if [ $tries -gt $MAX_TRIES ]; then note "SfM failed $MAX_TRIES times — giving up"; exit 1; fi
    note "starting rig SfM (attempt $tries)"
    rm -f colmap_db/amakeng_rig/database.db
    ./scripts/03b_run_colmap_rig.sh amakeng_rig >> "$LOGS_DIR/run_amakeng_rig.log" 2>&1 || true
done
note "rig SfM complete"

# ---- Stage 2: training ----
mkdir -p colmap_db/amakeng_rig/gs_scene
ln -sfn "$PROJECT_DIR/cubefaces_rgba/amakeng_rig" colmap_db/amakeng_rig/gs_scene/images
ln -sfn "$PROJECT_DIR/colmap_db/amakeng_rig/sparse" colmap_db/amakeng_rig/gs_scene/sparse
tries=0
while ! train_ok; do
    if pgrep -f "train.py -s.*amakeng_rig" >/dev/null; then sleep 300; continue; fi
    tries=$((tries+1))
    if [ $tries -gt $MAX_TRIES ]; then note "training failed $MAX_TRIES times — giving up"; exit 1; fi
    note "starting training (attempt $tries)"
    ( cd tools/gaussian-splatting && "$VENV_PY" train.py \
        -s "$PROJECT_DIR/colmap_db/amakeng_rig/gs_scene" \
        -m "$PROJECT_DIR/splat_output/amakeng_rig" \
        --iterations 100000 --densify_until_iter 50000 \
        --densify_grad_threshold 0.0001 --opacity_reset_interval 15000 \
        --position_lr_max_steps 100000 --save_iterations 30000 60000 100000 \
        >> "$PROJECT_DIR/logs/04_train_amakeng_rig.log" 2>&1 ) || true
done
note "training complete: splat_output/amakeng_rig/point_cloud/iteration_100000/point_cloud.ply"
