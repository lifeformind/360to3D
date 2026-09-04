#!/usr/bin/env bash
# Preprocess every section for the v3 recipe: corrected masks (hull reused from s03) + analytic road depths.
# Idempotent: skips sections whose outputs exist. Log: logs/prep_all.log
set -uo pipefail
cd "$(dirname "$0")/.."; export LD_LIBRARY_PATH="$PWD/tools/miniforge/envs/colmapdeps/lib"
LOG=logs/prep_all.log; SECS="${SECS:-s01 s02 s04 s05 s06 s07 s08 s09 s11 s12 s13 s14 s15 s16 s17 s18}"
for SEC in $SECS; do
  N=$(ls colmap_db/$SEC/gs_scene/images/*.png 2>/dev/null | wc -l)
  if [ "$(ls colmap_db/$SEC/gs_scene_v2/images/*.png 2>/dev/null | wc -l)" -lt "$N" ] || [ "$N" -eq 0 ]; then
    echo "[$(date '+%F %T')] $SEC masks" >> $LOG
    venv/bin/python scripts/40_make_masks_v2.py --sec $SEC --hull-from s03 >> $LOG 2>&1 || { echo "[$(date '+%F %T')] $SEC MASKS FAILED" >> $LOG; continue; }
    venv/bin/python - "$SEC" >> $LOG 2>&1 <<'PY'
import sys, cv2, numpy as np, glob
sec=sys.argv[1]; hull=np.load(f'colmap_db/{sec}/gs_scene_v2/hull_masks.npz')
for f in glob.glob(f'colmap_db/{sec}/gs_scene_v2/images/*.png'):
    yaw=f.split('_')[-1][:-4]; im=cv2.imread(f, cv2.IMREAD_UNCHANGED); a=im[...,3]; a[(a==0)&(~hull[yaw])]=64; im[...,3]=a; cv2.imwrite(f, im)
print(sec,'alpha re-encoded (0 hull, 64 sky, 255 keep)')
PY
  fi
  if [ "$(ls colmap_db/$SEC/gs_scene_v2/road_depth/*.npz 2>/dev/null | wc -l)" -lt "$N" ]; then
    echo "[$(date '+%F %T')] $SEC road depth" >> $LOG
    venv/bin/python scripts/43_road_depth.py --sec $SEC >> $LOG 2>&1 || echo "[$(date '+%F %T')] $SEC ROAD DEPTH FAILED" >> $LOG
  fi
  echo "[$(date '+%F %T')] $SEC PREP DONE" >> $LOG
done
echo "[$(date '+%F %T')] PREP ALL FINISHED" >> $LOG
