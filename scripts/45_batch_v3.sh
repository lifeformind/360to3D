#!/usr/bin/env bash
# Overnight batch: train every section with the chosen recipe, then bake the Unity bundle.
# Resumable: sections with splat_output/<sec>_<TAG>/BATCH_DONE are skipped; a section with a checkpoint resumes.
# Recipe via env: TAG (default v3), MAX_STEPS (8000), NEAR (0.005), EXTRA (trainer flags). Log: logs/batch_<TAG>.log
set -uo pipefail
cd "$(dirname "$0")/.."; PROJECT_DIR="$PWD"
TAG="${TAG:-v3}"; export MAX_STEPS="${MAX_STEPS:-8000}"; NEAR="${NEAR:-0.005}"
EXTRA="${EXTRA:---sky-alpha-lambda 0.5 --opacity-reg 0.005}"
SECS="${SECS:-s01 s02 s04 s05 s06 s07 s08 s09 s11 s12 s13 s14 s15 s16 s17 s18}"
LOG="logs/batch_${TAG}.log"; touch "$LOG"
echo "[$(date '+%F %T')] BATCH START tag=$TAG steps=$MAX_STEPS near=$NEAR extra=[$EXTRA] secs=[$SECS]" | tee -a "$LOG"
for SEC in $SECS; do
  OUT="splat_output/${SEC}_${TAG}"
  [ -f "$OUT/BATCH_DONE" ] && { echo "[$(date '+%F %T')] $SEC already done" >> "$LOG"; continue; }
  # wait for preprocessing of this section (44_prep_all.sh runs concurrently)
  N=$(ls colmap_db/$SEC/gs_scene/images/*.png | wc -l)
  while [ "$(ls colmap_db/$SEC/gs_scene_v2/images/*.png 2>/dev/null | wc -l)" -lt "$N" ] || ! grep -q "$SEC PREP DONE" logs/prep_all.log 2>/dev/null; do
    grep -q "$SEC MASKS FAILED" logs/prep_all.log 2>/dev/null && break; sleep 60
  done
  if grep -q "$SEC MASKS FAILED" logs/prep_all.log 2>/dev/null; then echo "[$(date '+%F %T')] $SEC SKIPPED (mask prep failed)" | tee -a "$LOG"; continue; fi
  for TRY in 1 2; do
    echo "[$(date '+%F %T')] $SEC training (try $TRY)" | tee -a "$LOG"
    ./scripts/41_train_v2.sh "$SEC" "$NEAR" "$TAG" $EXTRA >> "$LOG" 2>&1
    if grep -q "${SEC}_${TAG} TRAINING DONE" "logs/train_${TAG}_${SEC}.log"; then
      touch "$OUT/BATCH_DONE"; echo "[$(date '+%F %T')] $SEC COMPLETE" | tee -a "$LOG"; break
    fi
    echo "[$(date '+%F %T')] $SEC try $TRY failed: $(grep -a -E 'Error|error|Traceback' logs/train_${TAG}_${SEC}.log | tail -1)" | tee -a "$LOG"
  done
done
echo "[$(date '+%F %T')] ALL SECTIONS PROCESSED" | tee -a "$LOG"
# bake whatever is complete into the Unity bundle (first cut; un-optimised-pose transforms)
export LD_LIBRARY_PATH="$PROJECT_DIR/tools/miniforge/envs/colmapdeps/lib"
TAG="$TAG" venv/bin/python scripts/38_bake_unity_ply.py >> "$LOG" 2>&1 && echo "[$(date '+%F %T')] BAKE DONE" | tee -a "$LOG" || echo "[$(date '+%F %T')] BAKE FAILED" | tee -a "$LOG"
echo "[$(date '+%F %T')] BATCH FINISHED" | tee -a "$LOG"
