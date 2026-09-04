#!/usr/bin/env bash
# Rig-constrained COLMAP SfM driven by hloc SuperPoint+LightGlue matches.
#
# 03b (rig + SIFT) produced a scrambled trajectory; hloc+GLOMAP (good matches,
# no rig) produced 120x scale drift. This stage combines the two: copy the
# hloc database (keypoints + verified matches), rewrite it to the per-yaw
# rig layout, attach the analytical zero-baseline rig, and run the
# incremental mapper with rig constraints.
#
# Usage: 03c_run_colmap_rig_hloc.sh <scene> <hloc_db_scene>
#   e.g. 03c_run_colmap_rig_hloc.sh amakeng_rig2 amakeng_hloc
set -euo pipefail
source "$(dirname "$0")/env.sh"

SCENE="${1:?usage: 03c_run_colmap_rig_hloc.sh <scene> <hloc_db_scene>}"
HLOC_SCENE="${2:?usage: 03c_run_colmap_rig_hloc.sh <scene> <hloc_db_scene>}"
IMAGES="$PROJECT_DIR/cubefaces/amakeng_rig"   # per-yaw RGB layout (Y000/..Y270/)
[ -d "$IMAGES" ] || die "no images at $IMAGES"
N_IMG=$(find "$IMAGES" -name "*.png" | wc -l)
WORK="$PROJECT_DIR/colmap_db/$SCENE"
HLOC_DB="$PROJECT_DIR/colmap_db/$HLOC_SCENE/database.db"
[ -f "$HLOC_DB" ] || die "no hloc db at $HLOC_DB"
mkdir -p "$WORK"
LOG="$LOGS_DIR/03c_colmap_${SCENE}.log"

log "Rig+hloc SfM for $SCENE from $HLOC_DB ($N_IMG images, log: $LOG)"

log "Rewriting database to per-yaw rig layout"
cp "$HLOC_DB" "$WORK/database.db"
"$VENV_PY" - "$WORK/database.db" >>"$LOG" 2>&1 <<'PYEOF'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
cur = db.cursor()
cams = cur.execute("SELECT camera_id, model, width, height, params, prior_focal_length FROM cameras").fetchall()
assert len(cams) == 1, f"expected 1 shared camera, got {len(cams)}"
base = cams[0]
yaws = ["Y000", "Y090", "Y180", "Y270"]
# one camera row per yaw (identical intrinsics); Y000 keeps the existing id
yaw_cam = {yaws[0]: base[0]}
for y in yaws[1:]:
    cur.execute("INSERT INTO cameras (model, width, height, params, prior_focal_length) VALUES (?,?,?,?,?)", base[1:])
    yaw_cam[y] = cur.lastrowid
n = 0
for img_id, name in cur.execute("SELECT image_id, name FROM images").fetchall():
    stem = name.rsplit(".", 1)[0]          # c01_00001_Y000
    clipframe, yaw = stem.rsplit("_", 1)   # c01_00001, Y000
    assert yaw in yaw_cam, f"unexpected name {name}"
    cur.execute("UPDATE images SET name=?, camera_id=? WHERE image_id=?",
                (f"{yaw}/{clipframe}.png", yaw_cam[yaw], img_id))
    n += 1
db.commit()
print(f"renamed {n} images; cameras per yaw: {yaw_cam}")
db.close()
PYEOF

log "Configuring rigs (analytical zero-baseline extrinsics)"
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
"$COLMAP_BIN" rig_configurator \
    --database_path "$WORK/database.db" \
    --rig_config_path "$WORK/rig_config.json" >>"$LOG" 2>&1 || die "rig_configurator failed, see $LOG"

log "Rig-constrained sparse reconstruction (matches reused from hloc db)"
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
log "Rig+hloc sparse model at $WORK/sparse/0 ($BEST_N/$N_IMG images)"
