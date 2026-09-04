"""Copy generated exports + Editor scripts into the Unity project."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITY = Path(r"C:\repos\AmakengCircuit\Assets\Amakeng")


def main():
    gen, ed = UNITY / "Generated", UNITY / "Editor"
    gen.mkdir(parents=True, exist_ok=True)
    ed.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "export").iterdir():
        if f.is_file():
            dest = gen / (f.name + ".bytes" if f.suffix == ".raw" else f.name)
            shutil.copy2(f, dest)
            print(f"  {f.name} -> {dest}")
    RUNTIME = {"VehicleController.cs"}
    for f in (ROOT / "unity").glob("*.cs"):
        dest_dir = (UNITY if f.name in RUNTIME else ed)
        shutil.copy2(f, dest_dir / f.name)
        print(f"  {f.name} -> {dest_dir / f.name}")


if __name__ == "__main__":
    main()
