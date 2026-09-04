#!/usr/bin/env bash
# Overnight supervisor for the full pilot: waits for the section chain to
# produce the scene, then keeps training alive (resume-aware) to completion,
# then runs the render test. Every state change is logged with a timestamp.
set -u
cd "$(dirname "$0")/.."
SUP_LOG="logs/supervisor_pilot.log"
note() { echo "[$(date '+%F %T')] $*" >> "$SUP_LOG"; }

trainer_alive() {
    for p in /proc/[0-9]*/cmdline; do
        c=$(tr '\0' ' ' < "$p" 2>/dev/null) || continue
        case "$c" in *simple_trainer.py*splat_output/pilot*) return 0;; esac
    done
    return 1
}
chain_alive() {
    for p in /proc/[0-9]*/cmdline; do
        c=$(tr '\0' ' ' < "$p" 2>/dev/null) || continue
        case "$c" in *run_pilot.sh*|*18_make_section*|*19_align_section*|*batch_demo.py*pilot*) return 0;; esac
    done
    return 1
}

# Phase 1: wait for the scene (chain output); restart chain if it dies early
tries=0
while [ ! -e colmap_db/pilot/gs_scene/sparse ]; do
    if grep -q "FAIL" logs/pilot.log 2>/dev/null; then note "chain reported FAIL — manual attention needed"; exit 1; fi
    if ! chain_alive; then
        tries=$((tries+1))
        [ "$tries" -gt 3 ] && { note "chain died 3x — giving up"; exit 1; }
        note "chain not running — restarting (attempt $tries)"
        setsid nohup /tmp/claude-1000/-home-ldrgx10-360-to-3D/8e4e0b1c-3988-474a-9c5d-9ebe44d2b15e/scratchpad/run_pilot.sh >> logs/pilot.log 2>&1 < /dev/null &
        sleep 120
    fi
    sleep 120
done
note "scene ready — entering training phase"

# Phase 2: training with resume until final checkpoint
tries=0
while [ ! -f splat_output/pilot/ckpts/ckpt_29999_rank0.pt ]; do
    if trainer_alive; then sleep 180; continue; fi
    tries=$((tries+1))
    [ "$tries" -gt 6 ] && { note "training died 6x — giving up"; exit 1; }
    note "starting training (attempt $tries)"
    setsid nohup ./scripts/run_pilot_train.sh >> logs/pilot_train_runner.log 2>&1 < /dev/null &
    sleep 180
done
note "training complete"

# Phase 3: render test
LD_LIBRARY_PATH="$PWD/tools/miniforge/envs/colmapdeps/lib" venv/bin/python scripts/20_render_pilot.py \
    >> logs/pilot_render.log 2>&1 && note "render test done: splat_output/pilot/test_renders" \
    || note "render test FAILED — see logs/pilot_render.log"
note "PILOT COMPLETE"
