#!/usr/bin/env bash
# Cron-driven guardian: if the watchdog's heartbeat is stale (>15 min),
# start a fresh watchdog. Survives session death and machine reboots.
set -u
cd /home/ldrgx10/360_to_3D
HB=logs/watchdog.heartbeat
grep -q "SCALEOUT BATCH FINISHED" logs/scaleout.log 2>/dev/null && exit 0
grep -q "relaunch cap" logs/watchdog.log 2>/dev/null && exit 0
age=$(( $(date +%s) - $(stat -c %Y "$HB" 2>/dev/null || echo 0) ))
if [ "$age" -gt 900 ]; then
    (
        flock -n 9 || exit 0
        echo "[$(date '+%F %T')] guardian: heartbeat stale ${age}s — starting watchdog" >> logs/watchdog.log
        setsid nohup ./scripts/watchdog_scaleout.sh > /dev/null 2>&1 < /dev/null &
    ) 9>logs/watchdog.guardian.lock
fi
