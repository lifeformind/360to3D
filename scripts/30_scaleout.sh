#!/usr/bin/env bash
# 18-section scale-out: carve -> LingBot -> align+gates -> train -> render.
# Resumable: sections with a DONE marker are skipped; failures are logged
# and the batch moves on. All decisions are file-marker based.
set -u
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PY="$PROJECT_DIR/venv/bin/python"
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
LOG="logs/scaleout.log"
mark() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

N_SEC=18; OVERLAP=0.15; TOTAL_FRAMES=6474

for k in $(seq 1 $N_SEC); do
    SEC="s$(printf '%02d' "$k")"
    DONE="splat_output/$SEC/RENDER_DONE"
    [ -f "$DONE" ] && { mark "$SEC already complete — skipping"; continue; }

    read FA FB A B << PYEOF2
$($PY -c "
n, ov, tf, k = $N_SEC, $OVERLAP, $TOTAL_FRAMES, $k
width = 1.0 / (n - (n - 1) * ov)
step = width * (1 - ov)
fa = (k - 1) * step
fb = min(fa + width, 1.0)
print(f'{fa:.5f} {fb:.5f} {max(1, int(fa * tf))} {min(tf, int(fb * tf))}')")
PYEOF2

    mark "$SEC: frames $A..$B route $FA..$FB — section build"
    if [ ! -f "colmap_db/$SEC/lingbot_out/${SEC}_fwd/frame_000000.npz" ]; then
        ./scripts/18_make_section.sh "$SEC" "$A" "$B" >> "$LOG" 2>&1 \
            || { mark "$SEC FAILED at make_section"; continue; }
    fi
    if [ ! -f "colmap_db/$SEC/poses_aligned.npz" ]; then
        "$PY" scripts/19_align_section.py "$SEC" "$FA" "$FB" 3.0 >> "$LOG" 2>&1 \
            || { mark "$SEC FAILED at align"; continue; }
        grep -E "\[gate\]" "$LOG" | tail -4 | while read -r l; do mark "$SEC $l"; done
    fi

    mark "$SEC: training"
    tries=0
    until [ -f "splat_output/$SEC/ckpts/ckpt_29999_rank0.pt" ]; do
        tries=$((tries+1))
        [ "$tries" -gt 3 ] && break
        RESUME=""
        CKPT=$(ls -1v splat_output/"$SEC"/ckpts/ckpt_*_rank0.pt 2>/dev/null | tail -1)
        [ -n "$CKPT" ] && RESUME="--resume-ckpt $PROJECT_DIR/$CKPT"
        ( cd tools/gsplat/examples && "$PY" simple_trainer.py default \
            $RESUME --disable-video --disable-viewer \
            --pose-opt --pose-opt-lr 1e-4 \
            --data-dir "$PROJECT_DIR/colmap_db/$SEC/gs_scene" \
            --data-factor 1 \
            --result-dir "$PROJECT_DIR/splat_output/$SEC" \
            --max-steps 30000 --eval-steps 30000 --save-steps 10000 30000 \
            --strategy.grow-grad2d 0.0001 --strategy.refine-stop-iter 15000 \
            --strategy.reset-every 5000 \
            --post-processing bilateral_grid --save-ply ) >> "$LOG" 2>&1
    done
    if [ ! -f "splat_output/$SEC/ckpts/ckpt_29999_rank0.pt" ]; then
        mark "$SEC FAILED at training after $tries tries"; continue
    fi

    "$PY" scripts/20_render_section.py "$SEC" >> "$LOG" 2>&1 \
        && { grep "\[$SEC\]" "$LOG" | tail -3 | while read -r l; do mark "$l"; done; touch "$DONE"; mark "$SEC COMPLETE"; } \
        || mark "$SEC FAILED at render test"
done
mark "SCALEOUT BATCH FINISHED: $(ls splat_output/s*/RENDER_DONE 2>/dev/null | wc -l)/$N_SEC sections complete"
