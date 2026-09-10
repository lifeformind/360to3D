"""Copy generated exports + Editor scripts into the Unity project."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITY = Path(r"C:\repos\AmakengCircuit\Assets\Amakeng")

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _copy_export_tree(src: Path, dst: Path):
    """Recursively mirror src (export/) into dst (Generated/), preserving subfolders.
    Top-level .raw files are renamed to .raw.bytes (Unity TextAsset convention);
    .raw files nested in subfolders are copied as-is (none currently exist there).
    """
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_dir():
            _copy_export_tree(f, dst / f.name)
        elif f.is_file():
            is_top_level = src == (ROOT / "export")
            dest = dst / (f.name + ".bytes" if is_top_level and f.suffix == ".raw" else f.name)
            shutil.copy2(f, dest)
            print(f"  {f.relative_to(ROOT)} -> {dest}")


def main():
    gen, ed = UNITY / "Generated", UNITY / "Editor"
    gen.mkdir(parents=True, exist_ok=True)
    ed.mkdir(parents=True, exist_ok=True)
    _copy_export_tree(ROOT / "export", gen)
    # DressSlice.PlaceBarrier cross-checks its road_meta.json-derived barrier position
    # against the ENU ground-truth centreline (station + tangent) at runtime, so the
    # stage-69 intermediate centreline is also synced (not part of export/ proper).
    centerline = ROOT / "work" / "centerline.json"
    if centerline.exists():
        dest = gen / "centerline.json"
        shutil.copy2(centerline, dest)
        print(f"  work/centerline.json -> {dest}")
    RUNTIME = {"VehicleController.cs"}
    for f in (ROOT / "unity").glob("*.cs"):
        dest_dir = (UNITY if f.name in RUNTIME else ed)
        shutil.copy2(f, dest_dir / f.name)
        print(f"  {f.name} -> {dest_dir / f.name}")

    # HDRP migration (Task 1): generate the Shadow Matte HD Unlit shader graph the road
    # overlay uses (see scripts/72_shadowmatte_shadergraph.py's own docstring for why this is
    # generated rather than a committed binary asset). Idempotent (no-op if already present);
    # requires HDRP's package cache to already be resolved, which is only true after HDRP has
    # been activated at least once (Amakeng > Setup HDRP / SetupHdrp.Run()) - skipped with a
    # warning rather than failing the whole sync on a project where that hasn't happened yet.
    try:
        import importlib
        shadergraph = importlib.import_module("72_shadowmatte_shadergraph")
        shadergraph.generate()
    except FileNotFoundError as e:
        print(f"  (skipped shader graph generation: {e})")


if __name__ == "__main__":
    main()
