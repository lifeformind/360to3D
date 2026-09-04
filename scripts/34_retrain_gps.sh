#!/usr/bin/env bash
# GPS-anchored retrain: 19b_align_gps (time-based fit to GPX) -> gsplat 30k -> 20b render.
# Outputs under colmap_db/sXX/gps/ and splat_output/sXX_gps/ (old splats untouched).
# Resumable via splat_output/sXX_gps/RENDER_DONE; all decisions are file-marker based.
# Usage: 34_retrain_gps.sh [sec ...]   (default: all 18 except s10 = parked)
set -u
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PY="$PROJECT_DIR/venv/bin/python"
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
LOG="logs/retrain_gps.log"
mark() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
N_SEC=18; OVERLAP=0.15; TOTAL_FRAMES=6474; DT=2.0; CAM_H=3.0
SECS=("$@"); [ ${#SECS[@]} -eq 0 ] && SECS=(s05 s01 s02 s03 s04 s06 s07 s08 s09 s11 s12 s13 s14 s15 s16 s17 s18)
mark "RETRAIN BATCH START: ${SECS[*]}"
for SEC in "${SECS[@]}"; do
    k=$((10#${SEC#s}))
    DONE="splat_output/${SEC}_gps/RENDER_DONE"
    [ -f "$DONE" ] && { mark "$SEC already complete — skipping"; continue; }
    A=$($PY -c "
n, ov, tf, k = $N_SEC, $OVERLAP, $TOTAL_FRAMES, $k
width = 1.0 / (n - (n - 1) * ov); step = width * (1 - ov)
print(max(1, int((k - 1) * step * tf)))")
    [ -f "colmap_db/$SEC/lingbot_out/${SEC}_fwd/frame_000000.npz" ] || { mark "$SEC FAILED: no LingBot output"; continue; }
    if [ ! -f "colmap_db/$SEC/gps/poses_aligned.npz" ]; then
        mark "$SEC: GPS align (first frame $A, dt $DT)"
        "$PY" scripts/19b_align_gps.py "$SEC" "$A" "$DT" "$CAM_H" >> "$LOG" 2>&1 \
            || { mark "$SEC FAILED at GPS align"; continue; }
        grep -E "\[gate\]|\[align\]" "$LOG" | tail -6 | while read -r l; do mark "$SEC $l"; done
    fi
    mark "$SEC: training -> splat_output/${SEC}_gps"
    tries=0
    until [ -f "splat_output/${SEC}_gps/ckpts/ckpt_29999_rank0.pt" ]; do
        tries=$((tries+1)); [ "$tries" -gt 3 ] && break
        RESUME=""; CKPT=$(ls -1v splat_output/"${SEC}_gps"/ckpts/ckpt_*_rank0.pt 2>/dev/null | tail -1)
        [ -n "$CKPT" ] && RESUME="--resume-ckpt $PROJECT_DIR/$CKPT"
        ( cd tools/gsplat/examples && "$PY" simple_trainer.py default \
            $RESUME --disable-video --disable-viewer \
            --pose-opt --pose-opt-lr 1e-4 \
            --data-dir "$PROJECT_DIR/colmap_db/$SEC/gps/gs_scene" --data-factor 1 \
            --result-dir "$PROJECT_DIR/splat_output/${SEC}_gps" \
            --max-steps 30000 --eval-steps 30000 --save-steps 10000 30000 \
            --strategy.grow-grad2d 0.0001 --strategy.refine-stop-iter 15000 \
            --strategy.reset-every 5000 \
            --post-processing bilateral_grid --save-ply ) >> "$LOG" 2>&1
    done
    [ -f "splat_output/${SEC}_gps/ckpts/ckpt_29999_rank0.pt" ] || { mark "$SEC FAILED at training after $tries tries"; continue; }
    "$PY" scripts/20b_render_section.py "$SEC" >> "$LOG" 2>&1 \
        && { grep "\[${SEC}_gps\]" "$LOG" | tail -3 | while read -r l; do mark "$l"; done; touch "$DONE"; mark "$SEC COMPLETE"; } \
        || mark "$SEC FAILED at render test"
done
mark "RETRAIN BATCH FINISHED: $(ls splat_output/s*_gps/RENDER_DONE 2>/dev/null | wc -l) sections complete (this run: ${SECS[*]})"
