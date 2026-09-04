#!/usr/bin/env bash
# End-to-end: stitched equirect MP4(s) -> trained 3DGS .ply
# Usage: run_pipeline.sh <scene> [options] <video1.mp4> [video2.mp4 ...]
#   --fps N          frames per second to extract (default 2)
#   --face-size N    perspective view resolution (default 1024)
#   --fov N          view field-of-view in degrees (default 110)
#   --yaws LIST      yaw angles, comma separated (default 0,90,180,270)
#   --matcher M      colmap | hloc (default colmap)
#   --iters N        3DGS training iterations (default 30000)
set -euo pipefail
source "$(dirname "$0")/env.sh"

SCENE="${1:?usage: run_pipeline.sh <scene> [options] <video1.mp4> ...}"
shift
FPS=2; FACE_SIZE=1024; FOV=110; YAWS="0,90,180,270"; MATCHER=colmap; ITERS=30000; MASKS=1
VIDEOS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --no-masks) MASKS=0; shift;;
        --fps) FPS="$2"; shift 2;;
        --face-size) FACE_SIZE="$2"; shift 2;;
        --fov) FOV="$2"; shift 2;;
        --yaws) YAWS="$2"; shift 2;;
        --matcher) MATCHER="$2"; shift 2;;
        --iters) ITERS="$2"; shift 2;;
        *) VIDEOS+=("$1"); shift;;
    esac
done
[ "${#VIDEOS[@]}" -gt 0 ] || die "no input videos given"
for v in "${VIDEOS[@]}"; do [ -f "$v" ] || die "video not found: $v"; done

SECONDS=0
declare -A STAGE_T

log "=== Stage 1: frame extraction (${FPS} fps) ==="
t0=$SECONDS
i=0
for v in "${VIDEOS[@]}"; do
    i=$((i+1))
    clip=$(printf "c%02d" "$i")
    "$PROJECT_DIR/scripts/01_extract_frames.sh" "$v" "$SCENE" "$clip" "$FPS"
done
STAGE_T[extract]=$((SECONDS - t0))

log "=== Stage 1b: static-region masks ==="
t0=$SECONDS
if [ "$MASKS" = 1 ]; then
    "$VENV_PY" "$PROJECT_DIR/scripts/make_masks.py" --scene "$SCENE"
fi
STAGE_T[masks]=$((SECONDS - t0))

log "=== Stage 2: perspective view decomposition (${FACE_SIZE}px, fov $FOV, yaws $YAWS) ==="
t0=$SECONDS
"$VENV_PY" "$PROJECT_DIR/scripts/02_cubemap.py" \
    --scene "$SCENE" --size "$FACE_SIZE" --fov "$FOV" --yaws "$YAWS"
STAGE_T[cubemap]=$((SECONDS - t0))

log "=== Stage 3: COLMAP SfM (matcher: $MATCHER) ==="
t0=$SECONDS
"$PROJECT_DIR/scripts/03_run_colmap.sh" "$SCENE" --matcher "$MATCHER" --face-size "$FACE_SIZE" --fov "$FOV"
STAGE_T[sfm]=$((SECONDS - t0))

log "=== Stage 4: 3DGS training ($ITERS iters) ==="
t0=$SECONDS
"$PROJECT_DIR/scripts/04_train_splat.sh" "$SCENE" "$ITERS"
STAGE_T[train]=$((SECONDS - t0))

log "=== Pipeline complete for scene '$SCENE' ==="
for s in extract masks cubemap sfm train; do
    printf "  %-8s %6ds\n" "$s" "${STAGE_T[$s]}"
done
log "Output: $PROJECT_DIR/splat_output/$SCENE/point_cloud/iteration_${ITERS}/point_cloud.ply"
