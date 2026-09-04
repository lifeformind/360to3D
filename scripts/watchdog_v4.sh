#!/usr/bin/env bash
# Night watchdog for the v4 batch. File-marker liveness only:
# - heartbeat: touches logs/watchdog_v4.heartbeat every cycle
# - batch alive test: logs/batch_v4.log mtime fresh (trainer writes constantly)
# - if batch stale >20 min and not FINISHED: relaunch (flock-guarded, max 8)
set -u
cd /home/ldrgx10/360_to_3D
export TAG=v4 MAX_STEPS=4500 NEAR=0.005 EXTRA="--sky-alpha-lambda 0.5 --opacity-reg 0.005 --depth-loss --depth-lambda 1e-3"
WLOG=logs/watchdog_v4.log
HB=logs/watchdog_v4.heartbeat
LOCK=logs/batch_v4.launch.lock
note() { echo "[$(date '+%F %T')] $*" >> "$WLOG"; }
note "watchdog started (pid $$)"
relaunches=0   # relaunch counter; stale test uses the newest train log (the batch log is quiet during training)
while true; do
    touch "$HB"
    if grep -q "BATCH FINISHED" logs/batch_v4.log 2>/dev/null; then
        note "batch finished — watchdog exiting"
        exit 0
    fi
    newest=$(ls -t logs/batch_v4.log logs/train_v4_s*.log 2>/dev/null | head -1)
    age=$(( $(date +%s) - $(stat -c %Y "$newest" 2>/dev/null || echo 0) ))
    if [ "$age" -gt 1200 ]; then
        relaunches=$((relaunches+1))
        if [ "$relaunches" -gt 8 ]; then
            note "relaunch cap (8) reached — giving up; manual attention needed"
            exit 1
        fi
        note "batch_v4.log stale ${age}s — relaunching batch (attempt $relaunches)"
        (
            flock -n 9 || exit 0
            setsid nohup ./scripts/45_batch_v4.sh > /dev/null 2>&1 < /dev/null &
        ) 9>"$LOCK"
        sleep 300
    fi
    mem=$(free -g | awk '/^Mem:/{print $7}')
    [ "$mem" -lt 6 ] && note "LOW MEMORY WARNING: ${mem}G available"
    sleep 300
done
