#!/usr/bin/env bash
# Verify every pipeline stage runs without network access.
#
# Without root we cannot drop the interface, so this uses belt-and-braces:
#  - bogus proxies (all libcurl/urllib HTTP goes to a dead port)
#  - offline flags for torch hub / HF
#  - checks that the known runtime-download paths (COLMAP vocab tree,
#    LightGlue weights) resolve to local files
# For a definitive test, physically disable networking and run this again.
set -euo pipefail
source "$(dirname "$0")/env.sh"

export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
export HTTP_PROXY=$http_proxy HTTPS_PROXY=$https_proxy
export no_proxy="" NO_PROXY=""
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

TMP=$(mktemp -d /tmp/airgap.XXXX)
trap 'rm -rf "$TMP"' EXIT
FAIL=0
check() {  # check <name> <cmd...>
    local name="$1"; shift
    if "$@" >"$TMP/$name.log" 2>&1; then
        echo "PASS  $name"
    else
        echo "FAIL  $name  (log: $TMP/$name.log)"; FAIL=1
        tail -3 "$TMP/$name.log" | sed 's/^/      /'
    fi
}

echo "== local asset presence =="
[ -f "$VOCAB_TREE" ] && echo "PASS  vocab tree on disk" || { echo "FAIL  vocab tree missing"; FAIL=1; }
ls ~/.cache/torch/hub/checkpoints/superpoint_v1.pth \
   ~/.cache/torch/hub/checkpoints/superpoint_lightglue_v0-1_arxiv.pth >/dev/null 2>&1 \
   && echo "PASS  SuperPoint/LightGlue weights cached" || { echo "FAIL  weights missing"; FAIL=1; }

echo "== tool smoke tests (proxied to dead port) =="
check ffmpeg "$FFMPEG" -version
check colmap "$COLMAP_BIN" help
check py360convert "$VENV_PY" -c "import py360convert, numpy as np; py360convert.e2c(np.zeros((64,128,3),np.uint8), face_w=32)"
check torch_cuda "$VENV_PY" -c "import torch; assert torch.cuda.is_available()"
check gs_extensions "$VENV_PY" -c "import diff_gaussian_rasterization, simple_knn, fused_ssim"
check lightglue_offline "$VENV_PY" -c "
from lightglue import LightGlue, SuperPoint
SuperPoint(max_num_keypoints=1024).eval(); LightGlue(features='superpoint').eval()"
check hloc_import "$VENV_PY" -c "import hloc, pycolmap"

echo "== mini end-to-end (16 images through SIFT+match+map) =="
MINI="$TMP/mini"; mkdir -p "$MINI/images"
n=0
for f in "$PROJECT_DIR"/cubefaces/test/*_Y090.*; do
    cp "$f" "$MINI/images/"; n=$((n+1)); [ $n -ge 16 ] && break
done
check mini_extract "$COLMAP_BIN" feature_extractor \
    --database_path "$MINI/db.db" --image_path "$MINI/images" \
    --ImageReader.camera_model PINHOLE --ImageReader.single_camera 1 \
    --ImageReader.camera_params "512,512,512,512"
check mini_match "$COLMAP_BIN" sequential_matcher \
    --database_path "$MINI/db.db" \
    --SequentialMatching.loop_detection 1 \
    --SequentialMatching.loop_detection_period 4 \
    --SequentialMatching.vocab_tree_path "$VOCAB_TREE"

if [ $FAIL -eq 0 ]; then
    echo "ALL AIR-GAP CHECKS PASSED"
else
    echo "AIR-GAP CHECK FAILURES — see logs above" >&2
    exit 1
fi
