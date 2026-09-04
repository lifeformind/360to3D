#!/usr/bin/env bash
# Feature extraction + matching + sparse reconstruction on cube faces.
# Usage: 03_run_colmap.sh <scene> [--matcher colmap|hloc] [--face-size 1024]
set -euo pipefail
source "$(dirname "$0")/env.sh"

SCENE="${1:?usage: 03_run_colmap.sh <scene> [--matcher colmap|hloc] [--face-size 1024] [--fov 110]}"
shift
MATCHER="colmap"
FACE_SIZE=1024
FOV=110
USE_MASKS=0
while [ $# -gt 0 ]; do
    case "$1" in
        --matcher) MATCHER="$2"; shift 2;;
        --face-size) FACE_SIZE="$2"; shift 2;;
        --fov) FOV="$2"; shift 2;;
        --use-masks) USE_MASKS=1; shift;;
        *) die "unknown arg: $1";;
    esac
done

IMAGES="$PROJECT_DIR/cubefaces/$SCENE"
[ -d "$IMAGES" ] || die "no cube faces at $IMAGES (run stage 02 first)"
N_IMG=$(ls "$IMAGES" | wc -l)
[ "$N_IMG" -gt 0 ] || die "cube face dir is empty"
# NOTE: masks are NOT used for SfM by default. Masking out the hull also
# removes low-parallax world content (forward road, distant trees) that
# registration needs — the masked run collapsed to 4/480 registered images,
# while unmasked registered 480/480 (the uniform hull contributes few SIFT
# features anyway). Masks still gate 3DGS training via the RGBA alpha channel.
MASKS="$PROJECT_DIR/cubefaces_masks/$SCENE"
MASK_ARGS=()
if [ "$USE_MASKS" = 1 ] && [ -d "$MASKS" ] && [ -n "$(ls -A "$MASKS" 2>/dev/null)" ]; then
    MASK_ARGS=(--ImageReader.mask_path "$MASKS")
    log "Using feature masks from $MASKS"
fi

WORK="$PROJECT_DIR/colmap_db/$SCENE"
mkdir -p "$WORK/sparse"
LOG="$LOGS_DIR/03_colmap_${SCENE}.log"
# Perspective views rendered with known FOV: f = (size/2) / tan(fov/2).
F=$("$VENV_PY" -c "import math; print(f'{$FACE_SIZE/2/math.tan(math.radians($FOV/2)):.4f}')")
C=$("$VENV_PY" -c "print($FACE_SIZE/2)")
CAM_PARAMS="$F,$F,$C,$C"

log "Scene $SCENE: $N_IMG images, matcher=$MATCHER (log: $LOG)"

if [ "$MATCHER" = "colmap" ]; then
    [ -f "$VOCAB_TREE" ] || die "vocab tree missing: $VOCAB_TREE"
    log "SIFT feature extraction (GPU)"
    "$COLMAP_BIN" feature_extractor \
        --database_path "$WORK/database.db" \
        --image_path "$IMAGES" \
        --ImageReader.camera_model PINHOLE \
        --ImageReader.single_camera 1 \
        --ImageReader.camera_params "$CAM_PARAMS" \
        "${MASK_ARGS[@]}" \
        --FeatureExtraction.use_gpu 1 >>"$LOG" 2>&1 || die "feature_extractor failed, see $LOG"

    log "Sequential matching with vocab-tree loop detection"
    "$COLMAP_BIN" sequential_matcher \
        --database_path "$WORK/database.db" \
        --SequentialMatching.overlap 32 \
        --SequentialMatching.quadratic_overlap 1 \
        --SequentialMatching.loop_detection 1 \
        --SequentialMatching.loop_detection_period 10 \
        --SequentialMatching.loop_detection_num_images 30 \
        --SequentialMatching.vocab_tree_path "$VOCAB_TREE" \
        --FeatureMatching.use_gpu 1 >>"$LOG" 2>&1 || die "sequential_matcher failed, see $LOG"
elif [ "$MATCHER" = "hloc" ]; then
    log "hloc SuperPoint+LightGlue pipeline"
    "$VENV_PY" "$PROJECT_DIR/scripts/hloc_match.py" \
        --images "$IMAGES" --workdir "$WORK" --camera_params "$CAM_PARAMS" \
        >>"$LOG" 2>&1 || die "hloc matching failed, see $LOG"
else
    die "unknown matcher: $MATCHER"
fi

log "Sparse reconstruction (mapper)"
# Init constraints relaxed for forward-motion (driving) footage: the default
# 16 deg triangulation-angle demand almost never holds and init fails.
rm -rf "$WORK/sparse_raw"
mkdir -p "$WORK/sparse_raw"
"$COLMAP_BIN" mapper \
    --database_path "$WORK/database.db" \
    --image_path "$IMAGES" \
    --output_path "$WORK/sparse_raw" \
    --Mapper.init_min_tri_angle 4 \
    --Mapper.init_min_num_inliers 60 \
    --Mapper.init_num_trials 400 \
    --Mapper.ba_refine_focal_length 0 \
    --Mapper.ba_refine_extra_params 0 >>"$LOG" 2>&1 || die "mapper failed, see $LOG"

# The mapper may emit several partial models; sparse_raw/0 is NOT necessarily
# the biggest. Pick the largest, try merging the top two (they usually share
# images), and land the winner at sparse/0 for the training stage.
reg_count() { "$COLMAP_BIN" model_analyzer --path "$1" 2>&1 | grep -oE "Registered images: [0-9]+" | grep -oE "[0-9]+$" || echo 0; }
BEST=""; BEST_N=0; SECOND=""; SECOND_N=0
for m in "$WORK"/sparse_raw/*/; do
    n=$(reg_count "$m")
    log "  model $(basename "$m"): $n images"
    if [ "$n" -gt "$BEST_N" ]; then
        SECOND="$BEST"; SECOND_N=$BEST_N; BEST="$m"; BEST_N=$n
    elif [ "$n" -gt "$SECOND_N" ]; then
        SECOND="$m"; SECOND_N=$n
    fi
done
[ -n "$BEST" ] || die "mapper produced no model, see $LOG"
if [ -n "$SECOND" ] && [ "$SECOND_N" -ge 10 ]; then
    MERGED="$WORK/sparse_raw/merged"
    mkdir -p "$MERGED"
    if "$COLMAP_BIN" model_merger --input_path1 "$BEST" --input_path2 "$SECOND" \
        --output_path "$MERGED" >>"$LOG" 2>&1 \
       && "$COLMAP_BIN" bundle_adjuster --input_path "$MERGED" --output_path "$MERGED" \
        --BundleAdjustment.refine_focal_length 0 \
        --BundleAdjustment.refine_extra_params 0 >>"$LOG" 2>&1; then
        MN=$(reg_count "$MERGED")
        log "  merged model: $MN images"
        if [ "$MN" -gt "$BEST_N" ]; then BEST="$MERGED"; BEST_N=$MN; fi
    else
        log "  model merge failed — keeping largest single model"
    fi
fi
rm -rf "$WORK/sparse/0"
mkdir -p "$WORK/sparse/0"
cp "$BEST"/*.bin "$WORK/sparse/0/" 2>/dev/null || cp "$BEST"/* "$WORK/sparse/0/"

# Merging can leave a handful of numerically-degenerate points with absurd
# reprojection errors; drop them so downstream stats and training stay sane.
"$VENV_PY" - "$WORK/sparse/0" <<'PYEOF' >>"$LOG" 2>&1
import sys
import numpy as np
import pycolmap
rec = pycolmap.Reconstruction(sys.argv[1])
bad = [pid for pid, p in rec.points3D.items()
       if p.error > 8 or not np.isfinite(p.error) or np.linalg.norm(p.xyz) > 1e6]
for pid in bad:
    rec.delete_point3D(pid)
print(f"filtered {len(bad)} degenerate points, {rec.num_points3D()} remain")
rec.write(sys.argv[1])
PYEOF

"$COLMAP_BIN" model_analyzer --path "$WORK/sparse/0" 2>&1 | tee -a "$LOG" | grep -E "Registered|Points|error" || true
MIN_REG=$((N_IMG * 30 / 100))
[ "$BEST_N" -ge "$MIN_REG" ] || die "only $BEST_N/$N_IMG images registered (<30%) — reconstruction unusable, see $LOG"
log "Sparse model at $WORK/sparse/0 ($BEST_N/$N_IMG images registered)"
