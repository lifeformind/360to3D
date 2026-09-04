#!/usr/bin/env bash
# Full rerun of the LingBot pipeline on derotated (vehicle-locked) frames.
# Stages: masks -> cubefaces -> forward stream -> LingBot -> snap -> scene.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
SCENE=amanorthv
PY="$PROJECT_DIR/venv/bin/python"

echo "[chain] waiting for derotation to finish"
while pgrep -f "11_derotate" >/dev/null; do sleep 20; done
N=$(ls frames/$SCENE/c04/*.jpg | wc -l)
[ "$N" -eq 1295 ] || { echo "[chain] FAIL: derotation produced $N/1295 frames"; exit 1; }
echo "[chain] derotation done ($N frames)"

echo "[chain] masks"
"$PY" scripts/make_masks.py --scene $SCENE

echo "[chain] cubefaces (4 yaws RGBA+RGB)"
"$PY" scripts/02_cubemap.py --scene $SCENE --size 1024 --fov 110 --yaws 0,90,180,270

echo "[chain] forward stream links"
rm -rf cubefaces/${SCENE}_fwd && mkdir -p cubefaces/${SCENE}_fwd
for f in cubefaces/$SCENE/*_Y000.png; do
    ln -s "$PROJECT_DIR/$f" cubefaces/${SCENE}_fwd/$(basename "${f%_Y000.png}").png
done
echo "[chain] $(ls cubefaces/${SCENE}_fwd | wc -l) forward views"

echo "[chain] LingBot-Map"
( cd tools/lingbot-map && "$PY" demo_render/batch_demo.py \
    --input_folder "$PROJECT_DIR/cubefaces/${SCENE}_fwd" \
    --model_path weights/lingbot-map-long.pt \
    --output_folder "$PROJECT_DIR/colmap_db/$SCENE/lingbot_out" \
    --mode streaming --keyframe_interval 4 \
    --mask_sky --skyseg_model_path weights/skyseg.onnx \
    --save_predictions --no_render )

echo "[chain] snap to route"
"$PY" scripts/09_snap_to_route.py colmap_db/$SCENE/lingbot_out/${SCENE}_fwd \
    colmap_db/amanorth/route_polyline.json 1.5 colmap_db/$SCENE/snapped

echo "[chain] build scene"
"$PY" scripts/10_build_scene.py colmap_db/$SCENE/snapped/poses_snapped.npz \
    colmap_db/$SCENE/lingbot_out/${SCENE}_fwd $SCENE

echo "[chain] ALL DONE"
