---
name: dgx-spark-toolchain
description: Key toolchain facts for building CUDA software on this DGX Spark (ARM64 + GB10)
metadata: 
  node_type: memory
  type: project
  originSessionId: 5030cfc8-6d29-40e8-9eaf-8a678c994dce
---

DGX Spark: aarch64, GB10 Blackwell **compute capability 12.1**, CUDA 13.0, system PyTorch 2.12.0+cu130, Python 3.12.3. No passwordless sudo — installs must be sudo-free (static builds, conda-forge via Miniforge at `tools/miniforge`, project venv at `venv/` with `--system-site-packages`).

**Why:** pip has no aarch64 wheels for pycolmap and others; apt unusable without sudo.

**How to apply:** Build CUDA code with `TORCH_CUDA_ARCH_LIST="12.1"` / `-DCMAKE_CUDA_ARCHITECTURES=121`. COLMAP/pycolmap 4.1.1 built from source in `tools/` (flags in `SETUP_NOTES.md`); binaries need `LD_LIBRARY_PATH=tools/miniforge/envs/colmapdeps/lib` (see [[pipeline-status-amakeng]]).
