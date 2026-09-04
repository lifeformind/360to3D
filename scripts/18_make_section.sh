#!/usr/bin/env bash
# Build a section scene from a 10fps derotated frame range via symlinks,
# then run masks + cubefaces + forward stream + LingBot on just that range.
# Usage: 18_make_section.sh <section_name> <first_frame> <last_frame>
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
SEC="${1:?section name}"; A="${2:?first}"; B="${3:?last}"
SRC="frames/amanorth10v/c04"

rm -rf "frames/$SEC" "cubefaces/$SEC" "cubefaces_rgba/$SEC" "cubefaces/${SEC}_fwd"
mkdir -p "frames/$SEC/c04"
i=0
for n in $(seq "$A" "$B"); do
    i=$((i+1))
    ln -s "$PROJECT_DIR/$SRC/$(printf 'c04_%05d.jpg' "$n")" \
          "frames/$SEC/c04/$(printf 'c04_%05d.jpg' "$i")"
done
log "section $SEC: $(ls frames/$SEC/c04 | wc -l) frames ($A..$B)"

if ! "$VENV_PY" scripts/make_masks.py --scene "$SEC"; then
    # static window: hull is identical across the derotated video — borrow a sibling mask
    SIB=$(ls frames/s*/c04/mask.png frames/pilot/c04/mask.png 2>/dev/null | head -1)
    [ -n "$SIB" ] || die "no sibling mask available for static section"
    cp "$SIB" "frames/$SEC/c04/mask.png"
    log "static section: borrowed hull mask from $SIB"
fi
# degenerate-mask guard: motion masking on near-static sections keeps almost
# nothing; below 40% coverage borrow a sibling mask instead
KEPT=$("$VENV_PY" -c "
import numpy as np; from PIL import Image
m = np.array(Image.open('frames/$SEC/c04/mask.png'))
print(f'{(m>127).mean():.3f}')")
if [ "$(echo "$KEPT < 0.20" | bc)" -eq 1 ]; then
    SIB=$(for f in frames/s*/c04/mask.png frames/pilot/c04/mask.png; do
        [ -f "$f" ] || continue
        K2=$("$VENV_PY" -c "
import numpy as np; from PIL import Image
print(f'{(np.array(Image.open(\"$f\"))>127).mean():.3f}')")
        if [ "$(echo "$K2 >= 0.20" | bc)" -eq 1 ]; then echo "$f"; break; fi
    done)
    [ -n "$SIB" ] || die "mask degenerate ($KEPT kept) and no healthy sibling >=20%"
    cp "$SIB" "frames/$SEC/c04/mask.png"
    log "mask degenerate ($KEPT kept): borrowed healthy sibling $SIB"
fi
"$VENV_PY" scripts/02_cubemap.py --scene "$SEC" --size 1024 --fov 110 --yaws 0,90,180,270

mkdir -p "cubefaces/${SEC}_fwd"
for f in cubefaces/"$SEC"/*_Y000.png; do
    ln -s "$PROJECT_DIR/$f" "cubefaces/${SEC}_fwd/$(basename "${f%_Y000.png}").png"
done

( cd tools/lingbot-map && "$VENV_PY" demo_render/batch_demo.py \
    --input_folder "$PROJECT_DIR/cubefaces/${SEC}_fwd" \
    --model_path weights/lingbot-map-long.pt \
    --output_folder "$PROJECT_DIR/colmap_db/$SEC/lingbot_out" \
    --mode streaming --keyframe_interval 2 \
    --mask_sky --skyseg_model_path weights/skyseg.onnx \
    --save_predictions --no_render )
log "section $SEC ready: colmap_db/$SEC/lingbot_out"
