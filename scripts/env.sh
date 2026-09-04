# Shared environment for the 360->3DGS pipeline. Source this from every stage script.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_DIR
export TOOLS_DIR="$PROJECT_DIR/tools"
export FFMPEG="$TOOLS_DIR/bin/ffmpeg"
export FFPROBE="$TOOLS_DIR/bin/ffprobe"
export COLMAP_BIN="$TOOLS_DIR/colmap-install/bin/colmap"
export VOCAB_TREE="$TOOLS_DIR/vocab_tree_faiss_flickr100K_words256K.bin"
export VENV_PY="$PROJECT_DIR/venv/bin/python"
export LOGS_DIR="$PROJECT_DIR/logs"
# COLMAP was built against conda-forge libs; it needs them at runtime.
export LD_LIBRARY_PATH="$TOOLS_DIR/miniforge/envs/colmapdeps/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
# conda OpenBLAS is not OpenMP-safe; Ceres/COLMAP thread themselves.
export OPENBLAS_NUM_THREADS=1
mkdir -p "$LOGS_DIR"

log() { echo "[$(date '+%F %T')] $*"; }
die() { echo "[$(date '+%F %T')] ERROR: $*" >&2; exit 1; }
