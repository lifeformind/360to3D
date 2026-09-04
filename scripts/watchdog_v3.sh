#!/usr/bin/env bash
# Night watchdog for the v3 batch. File-marker liveness only:
# - heartbeat: touches logs/watchdog_v3.heartbeat every cycle
# - batch alive test: logs/batch_v3.log mtime fresh (trainer writes constantly)
# - if batch stale >20 min and not FINISHED: relaunch (flock-guarded, max 8)
set -u
cd /home/ldrgx10/360_to_3D
WLOG=logs/watchdog_v3.log
HB=logs/watchdog_v3.heartbeat
LOCK=logs/batch_v3.launch.lock
note() { echo "[$(date '+%F %T')] $*" >> "$WLOG"; }
note "watchdog started (pid $$)"
relaunches=0
while true; do
    touch "$HB"
    if grep -q "BATCH FINISHED" logs/batch_v3.log 2>/dev/null; then
        note "batch finished — watchdog exiting"
        exit 0
    fi
    age=$(( $(date +%s) - $(stat -c %Y logs/batch_v3.log 2>/dev/null || echo 0) ))
    if [ "$age" -gt 1200 ]; then
        relaunches=$((relaunches+1))
        if [ "$relaunches" -gt 8 ]; then
            note "relaunch cap (8) reached — giving up; manual attention needed"
            exit 1
        fi
        note "batch_v3.log stale ${age}s — relaunching batch (attempt $relaunches)"
        (
            flock -n 9 || exit 0
            setsid nohup ./scripts/45_batch_v3.sh > /dev/null 2>&1 < /dev/null &
        ) 9>"$LOCK"
        sleep 300
    fi
    mem=$(free -g | awk '/^Mem:/{print $7}')
    [ "$mem" -lt 6 ] && note "LOW MEMORY WARNING: ${mem}G available"
    sleep 300
done
