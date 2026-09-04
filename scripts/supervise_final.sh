#!/usr/bin/env bash
# Supervisor for the triangulated-init gsplat training run.
# Completion marker: final checkpoint file. Restarts the runner on death,
# up to MAX_TRIES. Process detection scans /proc cmdlines for the actual
# trainer invocation (never pgrep -f patterns that can match wrappers).
set -u
cd "$(dirname "$0")/.."
SUP_LOG="logs/supervisor_final.log"
DONE_CKPT="splat_output/amanorthv_final/ckpts/ckpt_79999_rank0.pt"
MAX_TRIES=5
note() { echo "[$(date '+%F %T')] $*" >> "$SUP_LOG"; }

trainer_alive() {
    # require BOTH tokens in one cmdline: only the real python trainer has
    # them together; launcher wrappers may contain either alone
    for p in /proc/[0-9]*/cmdline; do
        c=$(tr '\0' ' ' < "$p" 2>/dev/null) || continue
        case "$c" in
            *simple_trainer.py*amanorthv_final*) return 0;;
        esac
    done
    return 1
}

tries=0
while [ ! -f "$DONE_CKPT" ]; do
    if trainer_alive; then sleep 180; continue; fi
    tries=$((tries+1))
    if [ "$tries" -gt "$MAX_TRIES" ]; then note "trainer died $MAX_TRIES times — giving up"; exit 1; fi
    note "trainer not running — (re)starting attempt $tries"
    setsid nohup ./scripts/run_gsplat_final.sh >> logs/gsplat_runner_final.log 2>&1 < /dev/null &
    sleep 120
done
note "training complete: $DONE_CKPT"
