#!/usr/bin/env bash
# Cron-driven guardian: if the watchdog's heartbeat is stale (>15 min),
# start a fresh watchdog. Survives session death and machine reboots.
set -u
cd /home/ldrgx10/360_to_3D
HB=logs/watchdog_gps.heartbeat
grep -q "RETRAIN BATCH FINISHED" logs/retrain_gps.log 2>/dev/null && exit 0
grep -q "relaunch cap" logs/watchdog_gps.log 2>/dev/null && exit 0
age=$(( $(date +%s) - $(stat -c %Y "$HB" 2>/dev/null || echo 0) ))
if [ "$age" -gt 900 ]; then
    (
        flock -n 9 || exit 0
        echo "[$(date '+%F %T')] guardian: heartbeat stale ${age}s — starting watchdog" >> logs/watchdog_gps.log
        setsid nohup ./scripts/watchdog_gps.sh > /dev/null 2>&1 < /dev/null &
    ) 9>logs/watchdog_gps.guardian.lock
fi
