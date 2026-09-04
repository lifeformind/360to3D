#!/usr/bin/env bash
# Rig-constrained COLMAP SfM for multi-view-per-frame 360 footage.
#
# The plain sequential mapper accumulates severe scale drift on long
# forward-motion (driving) corridors — the amakeng run drifted to an extent
# of ~800k model units for a ~2km drive, which makes 3DGS training produce
# mush. Constraining the 4 yaw views of each frame as a camera rig (shared
# center, fixed 90-degree relative rotations) couples the poses rigidly and
# suppresses the drift.
#
# Expects the per-yaw image layout from 02_cubemap.py: cubefaces/<scene>/Yxxx/<frame>.png
# plus an existing (possibly drifty) reconstruction whose image names match
# that layout, to derive rig extrinsics from (--derive_from).
#
# Usage: 03b_run_colmap_rig.sh <scene> <derive_reconstruction_path> [--face-size 1024] [--fov 110]
set -euo pipefail
source "$(dirname "$0")/env.sh"

SCENE="${1:?usage: 03b_run_colmap_rig.sh <scene>}"
shift 1
FACE_SIZE=1024
FOV=110
while [ $# -gt 0 ]; do
    case "$1" in
        --face-size) FACE_SIZE="$2"; shift 2;;
        --fov) FOV="$2"; shift 2;;
        *) die "unknown arg: $1";;
    esac
done

IMAGES="$PROJECT_DIR/cubefaces/$SCENE"
[ -d "$IMAGES" ] || die "no images at $IMAGES"
N_IMG=$(find "$IMAGES" -name "*.png" | wc -l)
WORK="$PROJECT_DIR/colmap_db/$SCENE"
mkdir -p "$WORK"
LOG="$LOGS_DIR/03b_colmap_${SCENE}.log"
F=$("$VENV_PY" -c "import math; print(f'{$FACE_SIZE/2/math.tan(math.radians($FOV/2)):.4f}')")
C=$((FACE_SIZE / 2))
CAM_PARAMS="$F,$F,$C,$C"

log "Rig SfM for $SCENE: $N_IMG images (log: $LOG)"

# Rig config: one camera per yaw subdir. Relative rotations are ANALYTICAL:
# each Yxxx camera is the Y000 camera yawed right by xxx degrees (py360convert
# +u = rightward, verified empirically), i.e. cam_from_rig = R_y(-yaw) with
# quaternion (w,x,y,z) = (cos(yaw/2), 0, -sin(yaw/2), 0). Shared optical
# center -> zero translation. (Deriving these from a drifty reconstruction
# instead gives garbage — its same-frame relative poses were inconsistent.)
# NOTE: do NOT put camera_model_name/camera_params here — the string form
# writes a zero-param camera row into the DB and the matcher aborts with
# "num_params == CameraModelNumParams (0 vs. 4)". Intrinsics already come
# from the feature_extractor priors.
"$VENV_PY" - "$IMAGES" > "$WORK/rig_config.json" <<'PYEOF'
import json, math, sys
from pathlib import Path
yaws = sorted(p.name for p in Path(sys.argv[1]).iterdir() if p.is_dir())
cams = []
for i, y in enumerate(yaws):
    entry = {"image_prefix": f"{y}/"}
    if i == 0:
        entry["ref_sensor"] = True
    else:
        th = math.radians(int(y[1:]))
        q = [math.cos(th / 2), 0.0, -math.sin(th / 2), 0.0]  # w,x,y,z
        if q[0] < 0:
            q = [-c for c in q]
        entry["cam_from_rig_rotation"] = q
        entry["cam_from_rig_translation"] = [0, 0, 0]
    cams.append(entry)
print(json.dumps([{"cameras": cams}], indent=2))
PYEOF

log "Feature extraction (GPU, camera per yaw folder)"
"$COLMAP_BIN" feature_extractor \
    --database_path "$WORK/database.db" \
    --image_path "$IMAGES" \
    --ImageReader.camera_model PINHOLE \
    --ImageReader.single_camera_per_folder 1 \
    --ImageReader.camera_params "$CAM_PARAMS" \
    --FeatureExtraction.use_gpu 1 >>"$LOG" 2>&1 || die "feature_extractor failed, see $LOG"

log "Configuring rigs (analytical extrinsics)"
"$COLMAP_BIN" rig_configurator \
    --database_path "$WORK/database.db" \
    --rig_config_path "$WORK/rig_config.json" >>"$LOG" 2>&1 || die "rig_configurator failed, see $LOG"

log "Sequential matching (rig-aware) with loop detection"
"$COLMAP_BIN" sequential_matcher \
    --database_path "$WORK/database.db" \
    --SequentialMatching.overlap 32 \
    --SequentialMatching.quadratic_overlap 1 \
    --SequentialMatching.loop_detection 1 \
    --SequentialMatching.loop_detection_period 10 \
    --SequentialMatching.loop_detection_num_images 30 \
    --SequentialMatching.vocab_tree_path "$VOCAB_TREE" \
    --FeatureMatching.use_gpu 1 >>"$LOG" 2>&1 || die "sequential_matcher failed, see $LOG"

log "Rig-constrained sparse reconstruction"
rm -rf "$WORK/sparse_raw"
mkdir -p "$WORK/sparse_raw"
"$COLMAP_BIN" mapper \
    --database_path "$WORK/database.db" \
    --image_path "$IMAGES" \
    --output_path "$WORK/sparse_raw" \
    --Mapper.init_min_tri_angle 4 \
    --Mapper.init_min_num_inliers 60 \
    --Mapper.init_num_trials 400 \
    --Mapper.ba_refine_sensor_from_rig 0 \
    --Mapper.ba_refine_focal_length 0 \
    --Mapper.ba_refine_extra_params 0 >>"$LOG" 2>&1 || die "mapper failed, see $LOG"

reg_count() { "$COLMAP_BIN" model_analyzer --path "$1" 2>&1 | grep -oE "Registered images: [0-9]+" | grep -oE "[0-9]+$" || echo 0; }
BEST=""; BEST_N=0
for m in "$WORK"/sparse_raw/*/; do
    n=$(reg_count "$m")
    log "  model $(basename "$m"): $n images"
    if [ "$n" -gt "$BEST_N" ]; then BEST="$m"; BEST_N=$n; fi
done
[ -n "$BEST" ] || die "mapper produced no model, see $LOG"
rm -rf "$WORK/sparse/0"
mkdir -p "$WORK/sparse/0"
cp "$BEST"/*.bin "$WORK/sparse/0/"

"$COLMAP_BIN" model_analyzer --path "$WORK/sparse/0" 2>&1 | tee -a "$LOG" | grep -E "Registered|Points|error" || true
MIN_REG=$((N_IMG * 30 / 100))
[ "$BEST_N" -ge "$MIN_REG" ] || die "only $BEST_N/$N_IMG images registered (<30%), see $LOG"
log "Rig sparse model at $WORK/sparse/0 ($BEST_N/$N_IMG images)"
