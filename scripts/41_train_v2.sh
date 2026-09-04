#!/usr/bin/env bash
# Pilot retrain with corrected masks (gs_scene_v2, from 40_make_masks_v2.py) and a metric-sane near plane.
# Usage: 41_train_v2.sh <sec> [near_plane_normalised=0.001] [tag=v2] [extra simple_trainer flags...]
# Same gsplat flags as the scale-out / GPS batches, so the comparison isolates masks + near plane.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SEC="${1:?section}"; NEAR="${2:-0.001}"; TAG="${3:-v2}"; shift 3 2>/dev/null || shift $#
EXTRA="$*"
# MAX_STEPS env overrides the 30k default; densification/reset schedule scales with it
MAX_STEPS="${MAX_STEPS:-30000}"; REFINE_STOP=$(( MAX_STEPS / 2 )); RESET_EVERY=$(( MAX_STEPS >= 30000 ? 5000 : (MAX_STEPS >= 12000 ? 3000 : 2500) ))
SAVE_STEPS="$(( MAX_STEPS / 3 )) $MAX_STEPS"
PY="$PROJECT_DIR/venv/bin/python"
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib"
LOG="$PROJECT_DIR/logs/train_${TAG}_${SEC}.log"; OUT="$PROJECT_DIR/splat_output/${SEC}_${TAG}"
mkdir -p "$PROJECT_DIR/logs" "$OUT"
echo "[$(date '+%F %T')] ${SEC}_${TAG} START steps=$MAX_STEPS near_plane=$NEAR extra=[$EXTRA] data=colmap_db/$SEC/gs_scene_v2" | tee -a "$LOG"
CKPT=$(ls -1 "$OUT"/ckpts/ckpt_*_rank0.pt 2>/dev/null | sort -V | tail -1 || true)
RESUME=""; [ -n "$CKPT" ] && RESUME="--resume-ckpt $CKPT" && echo "resuming from $CKPT" | tee -a "$LOG"
( cd "$PROJECT_DIR/tools/gsplat/examples" && "$PY" simple_trainer.py default \
    $RESUME --disable-video --disable-viewer \
    --pose-opt --pose-opt-lr 1e-4 \
    --data-dir "$PROJECT_DIR/colmap_db/$SEC/gs_scene_v2" --data-factor 1 \
    --result-dir "$OUT" \
    --near-plane "$NEAR" $EXTRA \
    --max-steps "$MAX_STEPS" --eval-steps "$MAX_STEPS" --save-steps $SAVE_STEPS \
    --strategy.grow-grad2d 0.0001 --strategy.refine-stop-iter "$REFINE_STOP" \
    --strategy.reset-every "$RESET_EVERY" \
    --post-processing bilateral_grid --save-ply ) >> "$LOG" 2>&1 \
  && echo "[$(date '+%F %T')] ${SEC}_${TAG} TRAINING DONE" | tee -a "$LOG" \
  || echo "[$(date '+%F %T')] ${SEC}_${TAG} TRAINING FAILED (exit $?)" | tee -a "$LOG"
