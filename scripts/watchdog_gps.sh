#!/usr/bin/env bash
# Night watchdog for the scale-out batch. File-marker liveness only:
# - heartbeat: touches logs/watchdog_gps.heartbeat every cycle
# - batch alive test: logs/retrain_gps.log mtime fresh (trainer writes constantly)
# - if batch stale >20 min and not FINISHED: relaunch (flock-guarded, max 8)
set -u
cd /home/ldrgx10/360_to_3D
WLOG=logs/watchdog_gps.log
HB=logs/watchdog_gps.heartbeat
LOCK=logs/retrain_gps.launch.lock
note() { echo "[$(date '+%F %T')] $*" >> "$WLOG"; }
note "watchdog started (pid $$)"
relaunches=0
while true; do
    touch "$HB"
    if grep -q "RETRAIN BATCH FINISHED" logs/retrain_gps.log 2>/dev/null; then
        note "batch finished — watchdog exiting"
        exit 0
    fi
    age=$(( $(date +%s) - $(stat -c %Y logs/retrain_gps.log 2>/dev/null || echo 0) ))
    if [ "$age" -gt 1200 ]; then
        relaunches=$((relaunches+1))
        if [ "$relaunches" -gt 8 ]; then
            note "relaunch cap (8) reached — giving up; manual attention needed"
            exit 1
        fi
        note "scaleout.log stale ${age}s — relaunching batch (attempt $relaunches)"
        (
            flock -n 9 || exit 0
            setsid nohup ./scripts/34_retrain_gps.sh > /dev/null 2>&1 < /dev/null &
        ) 9>"$LOCK"
        sleep 300
    fi
    mem=$(free -g | awk '/^Mem:/{print $7}')
    [ "$mem" -lt 6 ] && note "LOW MEMORY WARNING: ${mem}G available"
    sleep 300
done
