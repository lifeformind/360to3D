"""Restore Assets/SeedMesh material assets in the Unity project to their pristine, native-
shader content, by pulling the original bytes directly out of this machine's cached Asset
Store .unitypackage archives and overwriting the corresponding project files in place.

WHEN THIS IS NEEDED
--------------------
The vertical-slice/URP-era `FixSeedMeshMaterialsForUrp()` (deleted from unity/DressSlice.cs
in the Task 1 HDRP migration - see docs/full-circuit-rollout-notes.md, "SeedMesh material
recovery") used to repoint every HDRP-targeted SeedMesh Shader Graph material onto
"Universal Render Pipeline/Lit" by MUTATING the packs' own shipped .mat assets IN PLACE
(same GUID/path, shader field overwritten) - there was never a separate "converted" copy
asset, so there's nothing to just delete. If DressSlice.WarnIfSeedMeshNotNative() ever logs
an error naming a material still on a "Universal ..." shader (whether from that now-deleted
function having run historically, or from some other accidental conversion), this script is
the fix: it restores every affected material to its pristine, native (HD Shader Graph)
content.

HOW IT WORKS
------------
A .unitypackage is a gzipped tar archive; each asset inside lives under a GUID-named folder
containing 'pathname' (the Assets/... path it was authored at), 'asset' (the asset's own
serialized bytes), and 'asset.meta'. This script opens the three SeedMesh Asset Store
packages this project actually uses (paths below), and for every .mat entry whose GUID
matches the project's existing .meta at that exact path (i.e. it really is the same asset,
just corrupted vs. pristine), overwrites the project file with the pristine bytes pulled
from the package. It deliberately bypasses `AssetDatabase.ImportPackage` - that API was
observed live, when driven through the Unity MCP automation bridge used for this project's
agent-driven builds, to never actually execute the import (no console log, no file
timestamp change, even after a 30s wait) - this direct byte-level restore is the reliable
alternative and was verified end to end (93/108 SeedMesh materials restored; re-verified via
a live shader-name tally in Unity: the "Universal Render Pipeline/Lit" count dropped from 87
to 2, both of which are materials embedded inside unused demo-scene .fbx files, never
referenced by any placed prefab).

REQUIRES: this machine's local Unity Asset Store cache
--------------------------------------------------------
The three package paths below are specific to this machine
(`%APPDATA%\\Unity\\Asset Store-5.x\\SeedMesh Studio\\...`) - wherever the SeedMesh Studio
packages were downloaded when originally imported into this project. On a different machine
(or if the cache has been cleared), this script will report the missing package(s) and do
nothing; re-download the three packages from the Unity Asset Store /
com.unity3d.kharma:content_... "My Assets" page to the same cache location first (or update
the PACKAGES list below to point at wherever they land) - this is a real limitation, not a
bug: there is no other pristine, offline source for this content in this project.

SAFETY
------
Only ever overwrites a project file if (a) it already exists at that exact path and (b) its
.meta GUID matches the package entry's GUID exactly (i.e. this really is the same asset, just
re-importing pristine content over corrupted content) - it never creates new files or touches
anything outside Assets/SeedMesh's own material set. Run with --dry-run first to see exactly
what would be touched without writing anything.

USAGE
-----
    venv/Scripts/python scripts/fix_seedmesh_materials.py [--dry-run]

After running, reimport in Unity (`AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate)`,
or just let the Editor pick up the on-disk changes) and re-run
`Amakeng.DressSlice.WarnIfSeedMeshNotNative()` (part of every `Dress()` run) to confirm.
"""
import sys
import tarfile
from pathlib import Path

PROJECT = Path(r"C:\repos\AmakengCircuit")

PACKAGES = [
    r"C:\Users\AI PC\AppData\Roaming\Unity\Asset Store-5.x\SeedMesh Studio\3D ModelsEnvironments\Jungle - Tropical Vegetation.unitypackage",
    r"C:\Users\AI PC\AppData\Roaming\Unity\Asset Store-5.x\SeedMesh Studio\3D ModelsVegetation\Tropical Plants Package.unitypackage",
    r"C:\Users\AI PC\AppData\Roaming\Unity\Asset Store-5.x\SeedMesh Studio\3D ModelsVegetationPlants\Ground Foliage Vol 2.unitypackage",
]

DRY_RUN = "--dry-run" in sys.argv


def project_guid(rel_path: str):
    meta = PROJECT / (rel_path + ".meta")
    if not meta.exists():
        return None
    for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("guid:"):
            return line.split(":", 1)[1].strip()
    return None


def main():
    restored = []
    skipped_no_file = []
    skipped_guid_mismatch = []
    missing_packages = []

    for pkg in PACKAGES:
        if not Path(pkg).exists():
            missing_packages.append(pkg)
            continue
        with tarfile.open(pkg, "r:gz") as tf:
            names = set(tf.getnames())
            guid_dirs = sorted(set(n.split("/")[0] for n in names if "/" in n))
            for g in guid_dirs:
                pn_name = f"{g}/pathname"
                if pn_name not in names:
                    continue
                # The pathname entry is "Assets/.../Foo.mat\n00" in these archives (a second,
                # unrelated line follows the path) - only the first line is the actual path.
                path = tf.extractfile(pn_name).read().decode("utf-8", errors="replace").split("\n")[0].strip()
                if not path.lower().endswith(".mat"):
                    continue
                asset_name = f"{g}/asset"
                if asset_name not in names:
                    continue
                dest = PROJECT / path
                if not dest.exists():
                    skipped_no_file.append(path)
                    continue
                pg = project_guid(path)
                if pg != g:
                    skipped_guid_mismatch.append((path, pg, g))
                    continue
                data = tf.extractfile(asset_name).read()
                if not DRY_RUN:
                    dest.write_bytes(data)
                restored.append(path)
        print(f"done: {pkg}")

    if missing_packages:
        print(f"\nMISSING {len(missing_packages)} package(s) - see this script's docstring "
              f"('REQUIRES: this machine's local Asset Store cache'):")
        for p in missing_packages:
            print("  ", p)

    verb = "would restore" if DRY_RUN else "restored"
    print(f"\n{verb.upper()} {len(restored)} material(s):")
    for p in restored:
        print("  ", p)
    if skipped_no_file:
        print(f"\nSKIPPED (no existing file at that path) {len(skipped_no_file)}:")
        for p in skipped_no_file:
            print("  ", p)
    if skipped_guid_mismatch:
        print(f"\nSKIPPED (guid mismatch - not actually the same asset) {len(skipped_guid_mismatch)}:")
        for p, pg, g in skipped_guid_mismatch:
            print("  ", p, "project_guid=", pg, "package_guid=", g)


if __name__ == "__main__":
    main()
