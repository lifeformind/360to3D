#!/usr/bin/env bash
# Supervisor for amakeng_hloc 3DGS training (SfM already done: hloc + GLOMAP,
# see logs/hloc_chain2.log). Restarts training after a crash/reboot, resuming
# from the newest chkpnt*.pth so lost work is bounded by the checkpoint stride.
set -u
cd "$(dirname "$0")/.."
source scripts/env.sh
SUP_LOG="$LOGS_DIR/supervisor_amakeng_hloc.log"
TRAIN_LOG="$LOGS_DIR/04_train_hloc.log"
MODEL_DIR="$PROJECT_DIR/splat_output/amakeng_hloc"
MAX_TRIES=5
note() { echo "[$(date '+%F %T')] $*" >> "$SUP_LOG"; }
train_ok() { grep -q "Training complete" "$TRAIN_LOG" 2>/dev/null; }

tries=0
while ! train_ok; do
    if pgrep -f "train.py -s.*amakeng_hloc" >/dev/null; then sleep 300; continue; fi
    tries=$((tries+1))
    if [ $tries -gt $MAX_TRIES ]; then note "training failed $MAX_TRIES times — giving up"; exit 1; fi
    ckpt=$(ls -1v "$MODEL_DIR"/chkpnt*.pth 2>/dev/null | tail -1)
    resume_args=()
    [ -n "$ckpt" ] && resume_args=(--start_checkpoint "$ckpt")
    note "starting training (attempt $tries)${ckpt:+, resuming from $ckpt}"
    ( cd tools/gaussian-splatting && "$VENV_PY" train.py \
        -s "$PROJECT_DIR/colmap_db/amakeng_hloc/gs_scene" \
        -m "$MODEL_DIR" \
        --iterations 100000 --densify_until_iter 50000 \
        --densify_grad_threshold 0.0001 --opacity_reset_interval 15000 \
        --position_lr_max_steps 100000 --save_iterations 50000 100000 \
        --checkpoint_iterations 10000 20000 30000 40000 50000 60000 70000 80000 90000 \
        "${resume_args[@]}" \
        >> "$TRAIN_LOG" 2>&1 ) || true
done
note "training complete: $MODEL_DIR/point_cloud/iteration_100000/point_cloud.ply"
