"""Copy generated exports + Editor scripts into the Unity project."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITY = Path(r"C:\repos\AmakengCircuit\Assets\Amakeng")


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
    RUNTIME = {"VehicleController.cs"}
    for f in (ROOT / "unity").glob("*.cs"):
        dest_dir = (UNITY if f.name in RUNTIME else ed)
        shutil.copy2(f, dest_dir / f.name)
        print(f"  {f.name} -> {dest_dir / f.name}")


if __name__ == "__main__":
    main()
