#!/usr/bin/env bash
# Train 3D Gaussian Splatting on the COLMAP sparse model.
# Usage: 04_train_splat.sh <scene> [iterations]
set -euo pipefail
source "$(dirname "$0")/env.sh"

SCENE="${1:?usage: 04_train_splat.sh <scene> [iterations]}"
ITERS="${2:-30000}"

WORK="$PROJECT_DIR/colmap_db/$SCENE"
IMAGES="$PROJECT_DIR/cubefaces/$SCENE"
OUT="$PROJECT_DIR/splat_output/$SCENE"
LOG="$LOGS_DIR/04_train_${SCENE}.log"
[ -d "$WORK/sparse/0" ] || die "no sparse model at $WORK/sparse/0 (run stage 03 first)"

# gaussian-splatting expects <src>/images + <src>/sparse/0.
# Prefer the RGBA set (alpha = static-rig mask -> masked training loss).
RGBA="$PROJECT_DIR/cubefaces_rgba/$SCENE"
if [ -d "$RGBA" ] && [ -n "$(ls -A "$RGBA" 2>/dev/null)" ]; then
    IMAGES="$RGBA"
    log "Training from masked RGBA views"
fi
SRC="$WORK/gs_scene"
mkdir -p "$SRC"
ln -sfn "$IMAGES" "$SRC/images"
ln -sfn "$WORK/sparse" "$SRC/sparse"

log "Training 3DGS for $ITERS iterations (log: $LOG)"
cd "$PROJECT_DIR/tools/gaussian-splatting"
"$VENV_PY" train.py -s "$SRC" -m "$OUT" \
    --iterations "$ITERS" \
    --save_iterations 7000 "$ITERS" \
    >>"$LOG" 2>&1 || die "train.py failed, see $LOG"

PLY="$OUT/point_cloud/iteration_${ITERS}/point_cloud.ply"
[ -f "$PLY" ] || die "training finished but no ply at $PLY"
log "Trained splat: $PLY ($(du -h "$PLY" | cut -f1))"
