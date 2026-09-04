#!/usr/bin/env bash
# Autonomous finisher: waits for the current batch, runs the s02/s07 rebuild
# sweep if needed, and maintains STATUS.md as the human-readable ground truth.
set -u
cd /home/ldrgx10/360_to_3D

status() {
    {
        echo "# AMAKENG scale-out STATUS  (updated $(date '+%F %T'))"
        echo
        echo "**Phase:** $1"
        echo
        echo "**Safe to shut down at any time.** All progress is checkpointed:"
        echo "- finished sections are final (splat_output/sXX/ply/point_cloud_29999.ply)"
        echo "- an interrupted training resumes from its last 10k checkpoint on next launch"
        echo "- on power-up, the user crontab (@reboot ensure_watchdog.sh) auto-resumes"
        echo "  any unfinished sections; remove with: crontab -l | grep -v ensure_watchdog | crontab -"
        echo
        echo "## Sections"
        for k in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18; do
            if [ -f "splat_output/s$k/RENDER_DONE" ]; then
                p=$(grep -h "\[s$k\] val: PSNR" logs/scaleout.log* 2>/dev/null | tail -1 | grep -oE '[0-9.]+$')
                echo "- s$k: COMPLETE (val PSNR $p)"
            else
                echo "- s$k: not complete"
            fi
        done
        echo
        echo "## Next steps (deferred by user)"
        echo "- Unity assembly: transform each section ply from its normalized frame to"
        echo "  map metres (inverse of gsplat Parser normalize transform), import all as"
        echo "  separate splat objects via aras-p UnityGaussianSplatting."
        echo "- Session pickup: memory file pipeline-status-amakeng.md has full context."
    } > STATUS.md
}

status "current batch running (s18 or earlier)"
while ! grep -q "SCALEOUT BATCH FINISHED" logs/scaleout.log 2>/dev/null; do sleep 300; done

if [ ! -f splat_output/s02/RENDER_DONE ] || [ ! -f splat_output/s07/RENDER_DONE ]; then
    status "final rebuild sweep for s02/s07 starting"
    mv logs/scaleout.log logs/scaleout.log.sweep2
    rm -f logs/watchdog.heartbeat
    setsid nohup ./scripts/30_scaleout.sh > /dev/null 2>&1 < /dev/null &
    sleep 30
    setsid nohup ./scripts/watchdog_scaleout.sh > /dev/null 2>&1 < /dev/null &
    status "final rebuild sweep for s02/s07 running"
    while ! grep -q "SCALEOUT BATCH FINISHED" logs/scaleout.log 2>/dev/null; do sleep 300; done
fi
n=$(ls splat_output/s*/RENDER_DONE 2>/dev/null | wc -l)
status "ALL DONE — $n/18 sections complete. Machine may be shut down."
