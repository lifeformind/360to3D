#!/usr/bin/env bash
# Extract equirectangular frames from a stitched 360 MP4.
# Usage: 01_extract_frames.sh <input.mp4> <scene> <clip_name> [fps] [out_width]
set -euo pipefail
source "$(dirname "$0")/env.sh"

INPUT="${1:?usage: 01_extract_frames.sh <input.mp4> <scene> <clip_name> [fps] [out_width]}"
SCENE="${2:?scene name required}"
CLIP="${3:?clip name required}"
FPS="${4:-2}"
OUT_W="${5:-4096}"   # downscale equirect width; 4096 is enough for 1024px cube faces

[ -f "$INPUT" ] || die "input not found: $INPUT"
OUT_DIR="$PROJECT_DIR/frames/$SCENE/$CLIP"
mkdir -p "$OUT_DIR"
LOG="$LOGS_DIR/01_extract_${SCENE}_${CLIP}.log"

log "Extracting $INPUT -> $OUT_DIR at ${FPS}fps, width $OUT_W"
"$FFMPEG" -y -i "$INPUT" -vf "fps=$FPS,scale=$OUT_W:-1" -qmin 1 -qscale:v 2 \
    "$OUT_DIR/${CLIP}_%05d.jpg" >"$LOG" 2>&1 \
    || die "ffmpeg failed, see $LOG"

N=$(ls "$OUT_DIR" | wc -l)
[ "$N" -gt 0 ] || die "no frames extracted, see $LOG"
log "Extracted $N frames for clip $CLIP"
