# Master Replica Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Task 4 Step 3 is a CONTROLLER step; Task 4 ends at a USER checkpoint.

**Goal:** The slice as a maximally realistic 3D replica: HDRP rendering with native SeedMesh quality, a mass-planted layered rainforest (~3,000–8,000 instances), dynamic tree shadows on the photo road, footage-matched grading — at ≥ 30 fps in-editor.

**Architecture:** In-place HDRP migration (pipeline asset + volume + material re-targeting; SeedMesh materials reverted to native shader graphs); a new python stage 75 generates deterministic layered forest placements from the canopy raster; DressSlice gains `PlantForest()` (replacing PlantTrees/ScatterUnderstory) planting into 20 m chunks; a fidelity pass matches grading to the footage.

**Tech Stack:** Unity 6000.3.19f1 + HDRP 17.3.0 (already in manifest), unity-editor-mcp (editor open), Python venv (numpy, rasterio, scipy), pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-master-replica-design.md` (+ Quest budgets contract in `2026-09-10-vr-corridor-rendering-design.md` — NOT binding for the master, only for later bakes)

## Global Constraints

- Workstation authoring target: ≥ 30 fps in-editor on the slice; poly count unconstrained.
- Road mosaic overlay material: **HDRP Unlit with Shadow Matte** (photographic look + receives dynamic shadows). Photogrammetry mesh/backdrop stays as underlay (HDRP Lit, double-sided as today).
- SeedMesh materials must run their NATIVE Shader Graph shaders under HDRP (the `FixSeedMeshMaterialsForUrp` conversion is deleted, its generated material assets removed).
- Forest planting: lateral band 4–40 m both sides; NOTHING within 5.5 m of the centreline; deterministic (fixed seed); chunked under `[GEN] Forest/chunk_NNN` per 20 m of track.
- Layers by local canopy height h: canopy h≥12 → `Background_group_var*`/tall `Dense_Jungle_Tree_Var*` scaled to h; midstory 6≤h<12 → `Dense_Jungle_Tree_Var*`/banana; understory 1.5–6 → bushes + Tropical Plants; ground <1.5 → Ground Foliage; wall creepers along the canopy edge.
- Grounding: ALWAYS `terrain.SampleHeight(p) + terrain.transform.position.y` (the −7.87 offset bug is history; a helper `WorldTerrainHeight` exists in DressSlice — use it).
- Unity workflow: edit repo `unity/*.cs` → `venv/Scripts/python scripts/70_sync_unity.py` → run via Unity_RunCommand (editor open; the RunCommand wrapper reports warnings as errors — the pack-converter warning is gone after this plan's Task 1, so expect clean runs). Max 4 attempts per failing operation then BLOCKED.
- Python: `venv/Scripts/python` from repo root; TDD for stage 75.
- Commit after every task; messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_017Q3x5rCM4ZaEXZz2DrBbxL`

---

### Task 1: HDRP migration

**Files:**
- Create: `unity/SetupHdrp.cs`
- Modify: `unity/DressSlice.cs` (delete FixSeedMeshMaterialsForUrp + converted-material creation; overlay material → HDRP Unlit Shadow Matte; backdrop/barrier/tree-tint materials → HDRP Lit)
- Modify: `unity/BuildAmakeng.cs` (gravel + provisional materials → HDRP/Lit)
- Modify: `unity/BuildVehicle.cs` only if its materials reference URP shaders (body/wheels use primitives' defaults — check)

**Interfaces:**
- Produces: menu **Amakeng > Setup HDRP** / `Amakeng.SetupHdrp.Run()` — idempotent: creates `Assets/Amakeng/HDRP/MasterHDRP.asset` (HDRenderPipelineAsset) + assigns to `GraphicsSettings.defaultRenderPipeline` and all quality levels; ensures HDRP global settings (`HDRenderPipelineGlobalSettings.Ensure()` or the API the version exposes); creates a scene Volume `[GEN] Atmosphere` with: sky (PhysicallyBasedSky or GradientSky matched to the current look), Fog (enabled, mean free path tuned to match the previous ~250 m visibility), Exposure (Fixed, tuned so the road mosaic reads correctly), ColorAdjustments (neutral defaults; Task 4 tunes). Deletes stale URP `[GEN]`-era settings only where they conflict (URP assets themselves stay on disk).
- Produces for later tasks: `Amakeng.DressSlice` compiles and `Dress()` runs clean under HDRP; helper `Material MakeShadowMatteUnlit(Texture tex)` in DressSlice (public static) used for overlay tiles now and shell bakes later.

- [ ] **Step 1: Write `unity/SetupHdrp.cs`** — contract implementation (HDRP API is version-sensitive; discovery-first adaptations allowed and documented). Core skeleton:

```csharp
// Switches the project to HDRP for master-replica authoring. Menu: Amakeng > Setup HDRP.
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Amakeng
{
    public static class SetupHdrp
    {
        [MenuItem("Amakeng/Setup HDRP")]
        public static void Run()
        {
            const string dir = "Assets/Amakeng/HDRP";
            if (!AssetDatabase.IsValidFolder(dir))
                AssetDatabase.CreateFolder("Assets/Amakeng", "HDRP");
            var asset = AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>(dir + "/MasterHDRP.asset");
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<HDRenderPipelineAsset>();
                AssetDatabase.CreateAsset(asset, dir + "/MasterHDRP.asset");
            }
            GraphicsSettings.defaultRenderPipeline = asset;
            for (int i = 0; i < QualitySettings.names.Length; i++)
                QualitySettings.SetRenderPipelineAssetAt(i, asset);

            // Volume: sky + fog + exposure (idempotent [GEN] Atmosphere object)
            var old = GameObject.Find("[GEN] Atmosphere");
            if (old != null) Object.DestroyImmediate(old);
            var go = new GameObject("[GEN] Atmosphere");
            var vol = go.AddComponent<Volume>();
            vol.isGlobal = true;
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            AssetDatabase.CreateAsset(profile, dir + "/Atmosphere.asset");
            vol.sharedProfile = profile;
            var fog = profile.Add<Fog>(true);
            fog.enabled.Override(true);
            fog.meanFreePath.Override(250f);
            var exp = profile.Add<Exposure>(true);
            exp.mode.Override(ExposureMode.Fixed);
            exp.fixedExposure.Override(11f); // start; tune vs mosaic in the same run
            // Sky: GradientSky as the robust default (PhysicallyBasedSky allowed if it
            // compiles/behaves; document which was used)
            var sky = profile.Add<GradientSky>(true);
            var vs = profile.Add<VisualEnvironment>(true);
            vs.skyType.Override((int)SkyType.Gradient);
            AssetDatabase.SaveAssets();
            Debug.Log("Amakeng: HDRP assigned + atmosphere volume created");
        }
    }
}
```
Adaptation zone: global-settings bootstrapping (`HDRenderPipelineGlobalSettings`), sky type
enum names, and exposure default may differ in HDRP 17 — adapt minimally, log choices, and
record them in the report. The scene's directional light keeps its NOAA rotation; ensure an
`HDAdditionalLightData` exists with intensity in a sane photographic range (e.g. ~100000 lux
for sunlight with fixed exposure tuned to match).

- [ ] **Step 2: Re-target generated materials**

In `unity/DressSlice.cs`:
- DELETE `FixSeedMeshMaterialsForUrp()` and its call; add a one-time cleanup in `Dress()` that
  `AssetDatabase.DeleteAsset`s any previously saved converted SeedMesh material assets and
  RE-ASSIGNS SeedMesh prefab instances' renderers back to the prefab's own sharedMaterials
  (simplest robust route: the planting code instantiates prefabs fresh each Dress — verify no
  per-instance material overrides remain after the converter is gone).
- Add:
```csharp
        public static Material MakeShadowMatteUnlit(Texture tex)
        {
            var m = new Material(Shader.Find("HDRP/Unlit"));
            m.SetTexture("_UnlitColorMap", tex);
            m.SetFloat("_EnableShadowMatte", 1f);
            m.EnableKeyword("_ENABLE_SHADOW_MATTE");
            return m;
        }
```
  and use it for the overlay tile materials in `BuildOverlay()` (replacing the URP Lit path).
- Backdrop double-sided clones, barrier material: `Shader.Find("HDRP/Lit")` with
  `_DoubleSidedEnable` = 1 + `m.doubleSidedGI = true` for backdrop (adapt property names to
  what HDRP/Lit exposes; verify visually).
In `unity/BuildAmakeng.cs`: gravel + provisional materials → `Shader.Find("HDRP/Lit")`
(keep textures/colors; smoothness stays low).
In `unity/BuildVehicle.cs`: primitives get default material automatically under HDRP — only
change if a magenta appears (report it).

- [ ] **Step 3: Sync, run Setup HDRP then rebuild chain via Unity_RunCommand**

`venv/Scripts/python scripts/70_sync_unity.py`, then in order: `Amakeng.SetupHdrp.Run();`
then `Amakeng.BuildAmakeng.BuildScene(); Amakeng.BuildVehicle.Build(); Amakeng.DressSlice.Dress();`.
Console must end with 0 errors. Expected one-time noise: HDRP resource imports/shader
compilation on first switch (can take minutes).

- [ ] **Step 4: Verify visually + technically**

Render the three driver captures (hdrp_s460/530/640.png, workspace) via the established
RenderTexture probe. Check: SeedMesh plants at NATIVE quality (no magenta, richer shading
than before, wind if the graphs animate), road mosaic photographic with tree shadows visible
on it, terrain/mesh/barrier intact, sky/fog plausible. Also verify no URP shaders remain in
`[GEN]`/`ShellPilot` renderers: a RunCommand listing any renderer whose material shader name
contains "Universal" (ShellPilot probe may be deleted instead — it is suspended throwaway:
delete `[PROBE] Shell` and `Assets/Amakeng/ShellPilot/`).

- [ ] **Step 5: Commit**

```bash
git add unity/ && git commit -m "feat: HDRP migration - pipeline asset, atmosphere volume, material retargeting"
```

---

### Task 2: Stage 75 — layered forest placements

**Files:**
- Create: `scripts/75_forest.py`
- Test: `tests/test_stage75.py`

**Interfaces:**
- Consumes: `work/centerline.json` (stations s/x/y/z/tx/ty/provisional), `work/canopy_enu.tif`.
- Produces: `export/forest_placements.json`:
  ```json
  {"seed": 20260910, "s_range": [439.0, 664.0],
   "chunks": [{"s0": 440.0, "plants": [{"layer": "canopy", "x": ..., "y": ...,
               "h": 14.2, "yaw": 231.0, "scale": 1.08}, ...]}, ...]}
  ```
  Chunks every 20 m (s0 = chunk start station). `layer` ∈ canopy|mid|under|ground|wall.
  `h` = local canopy height (m). Nothing within 5.5 m lateral of the centreline; band 4–40 m.

- [ ] **Step 1: Write the failing test**

`tests/test_stage75.py`:
```python
import json
import subprocess
import numpy as np
import pytest
from scipy.spatial import cKDTree
from conftest import ROOT

PY = str(ROOT / "venv" / "Scripts" / "python")


@pytest.fixture(scope="module")
def forest():
    subprocess.run([PY, str(ROOT / "scripts" / "75_forest.py")], check=True)
    return json.loads((ROOT / "export" / "forest_placements.json").read_text())


def plants(forest):
    return [p for c in forest["chunks"] for p in c["plants"]]


def test_counts_and_layers(forest):
    ps = plants(forest)
    assert 2500 <= len(ps) <= 9000
    layers = {p["layer"] for p in ps}
    assert layers == {"canopy", "mid", "under", "ground", "wall"}
    assert all(p["h"] >= 12 for p in ps if p["layer"] == "canopy")
    assert all(6 <= p["h"] < 12 for p in ps if p["layer"] == "mid")


def test_road_exclusion(forest):
    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"] if not st["provisional"]]
    tree = cKDTree([[st["x"], st["y"]] for st in sts])
    ps = plants(forest)
    d, _ = tree.query([[p["x"], p["y"]] for p in ps])
    assert d.min() >= 5.5
    assert d.max() <= 42.0


def test_deterministic(forest):
    first = json.dumps(forest, sort_keys=True)
    subprocess.run([PY, str(ROOT / "scripts" / "75_forest.py")], check=True)
    second = json.dumps(json.loads(
        (ROOT / "export" / "forest_placements.json").read_text()), sort_keys=True)
    assert first == second


def test_chunk_structure(forest):
    s0s = [c["s0"] for c in forest["chunks"]]
    assert s0s == sorted(s0s)
    assert all(abs((b - a) - 20.0) < 0.01 for a, b in zip(s0s, s0s[1:]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_stage75.py -v`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement `scripts/75_forest.py`**

```python
"""Stage 75: deterministic layered rainforest placements from the canopy raster."""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260910
BAND = (4.0, 40.0)
EXCLUDE = 5.5
CHUNK = 20.0
CELL = 2.0          # structure-pass cell (m)
GROUND_CELL = 1.5   # ground-cover pass cell, band 4-12 m
WALL_STEP = 3.0     # creeper spacing along the canopy edge


def layer_of(h):
    if h >= 12: return "canopy"
    if h >= 6: return "mid"
    if h >= 1.5: return "under"
    return "ground"


def cover_prob(h):
    return float(np.clip(h / 20.0, 0.15, 0.9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s0", type=float, default=439.0)
    ap.add_argument("--s1", type=float, default=664.0)
    a = ap.parse_args()

    cl = json.loads((ROOT / "work" / "centerline.json").read_text())
    sts = [st for st in cl["stations"]
           if not st["provisional"] and a.s0 <= st["s"] <= a.s1]
    can = rasterio.open(ROOT / "work" / "canopy_enu.tif")

    def canopy(px, py):
        return float(next(can.sample([(px, py)]))[0])

    chunks = {}
    def add(s, plant):
        s0 = a.s0 + int((s - a.s0) // CHUNK) * CHUNK
        chunks.setdefault(round(s0, 1), []).append(plant)

    for st in sts:
        s = st["s"]
        nx, ny = -st["ty"], st["tx"]
        for sgn in (1.0, -1.0):
            # structure pass: 2 m cells across the band, per 2 m of track (skip odd stations)
            if int(round(s)) % int(CELL) == 0:
                for lat in np.arange(BAND[0], BAND[1], CELL):
                    rng = np.random.default_rng(
                        SEED + hash((int(round(s)), int(sgn), int(lat * 10))) % (2**31))
                    px = st["x"] + sgn * lat * nx
                    py = st["y"] + sgn * lat * ny
                    h = canopy(px, py)
                    if h < 0.3 or rng.random() > cover_prob(h):
                        continue
                    jx, jy = rng.uniform(-0.9, 0.9, 2)
                    plat = lat + jx
                    if plat < EXCLUDE + 0.5:
                        continue
                    add(s, dict(layer=layer_of(h),
                                x=round(px + jx * nx * sgn + jy * st["tx"], 2),
                                y=round(py + jx * ny * sgn + jy * st["ty"], 2),
                                h=round(max(h, 0.4), 1),
                                yaw=round(float(rng.uniform(0, 360)), 1),
                                scale=round(float(rng.uniform(0.85, 1.25)), 2)))
            # ground-cover pass: 1.5 m cells, band 4-12 m, per 1.5 m of track
            if int(round(s / GROUND_CELL)) != int(round((s - 1) / GROUND_CELL)):
                for lat in np.arange(BAND[0], 12.0, GROUND_CELL):
                    rng = np.random.default_rng(
                        SEED + 7 + hash((int(round(s * 2)), int(sgn), int(lat * 10))) % (2**31))
                    if rng.random() > 0.5:
                        continue
                    jx, jy = rng.uniform(-0.6, 0.6, 2)
                    if lat + jx < EXCLUDE + 0.3:
                        continue
                    px = st["x"] + sgn * (lat + jx) * nx + jy * st["tx"]
                    py = st["y"] + sgn * (lat + jx) * ny + jy * st["ty"]
                    add(s, dict(layer="ground", x=round(px, 2), y=round(py, 2),
                                h=round(max(canopy(px, py), 0.4), 1),
                                yaw=round(float(rng.uniform(0, 360)), 1),
                                scale=round(float(rng.uniform(0.8, 1.3)), 2)))
        # wall creepers: canopy edge per side, every WALL_STEP
        if int(round(s)) % int(WALL_STEP) == 0:
            for sgn in (1.0, -1.0):
                rng = np.random.default_rng(
                    SEED + 13 + hash((int(round(s)), int(sgn))) % (2**31))
                for lat in np.arange(BAND[0], 15.0, 0.5):
                    px = st["x"] + sgn * lat * nx
                    py = st["y"] + sgn * lat * ny
                    if canopy(px, py) >= 3.0:
                        if lat >= EXCLUDE + 0.3:
                            add(s, dict(layer="wall", x=round(px, 2), y=round(py, 2),
                                        h=round(canopy(px, py), 1),
                                        yaw=round(float(rng.uniform(0, 360)), 1),
                                        scale=round(float(rng.uniform(0.9, 1.2)), 2)))
                        break

    out = dict(seed=SEED, s_range=[a.s0, a.s1],
               chunks=[dict(s0=k, plants=v) for k, v in sorted(chunks.items())])
    (ROOT / "export" / "forest_placements.json").write_text(json.dumps(out))
    n = sum(len(c["plants"]) for c in out["chunks"])
    per = {}
    for c in out["chunks"]:
        for p in c["plants"]:
            per[p["layer"]] = per.get(p["layer"], 0) + 1
    print(f"{n} plants in {len(out['chunks'])} chunks: {per}")


if __name__ == "__main__":
    main()
```
NOTE: python's builtin `hash()` on tuples is randomized per process (PYTHONHASHSEED) — that
breaks determinism across runs. The implementer MUST replace the three `hash((...))` calls
with a stable integer mix, e.g. `(a * 73856093) ^ (b * 19349663) ^ (c * 83492791)` from the
tuple components. The determinism test exists precisely to catch this.

- [ ] **Step 4: Run test to verify it passes** (fix the hash-mix per the note first)

Run: `venv/Scripts/python -m pytest tests/test_stage75.py -v`
Expected: 4 passed. Record the per-layer counts from the script output.

- [ ] **Step 5: Commit**

```bash
git add scripts/75_forest.py tests/test_stage75.py && git commit -m "feat: stage 75 - layered rainforest placements"
```

---

### Task 3: PlantForest in DressSlice

**Files:**
- Modify: `unity/DressSlice.cs` (remove PlantTrees + ScatterUnderstory; add PlantForest)
- Modify: `scripts/70_sync_unity.py` only if forest_placements.json isn't already covered by the recursive export copy (it is — verify)

**Interfaces:**
- Consumes: `Assets/Amakeng/Generated/forest_placements.json` (Task 2 schema), SeedMesh packs, `WorldTerrainHeight` helper.
- Produces: `PlantForest()` called from `Dress()`: idempotent `[GEN] Forest` root with `chunk_NNN` children (NNN = s0); per-layer prefab pools discovered once via FindAssets:
  - canopy → `Background_group_var*` (h ≥ 16) else tall `Dense_Jungle_Tree_Var*`, uniform-scaled so renderer height ≈ h (pool member native heights measured once)
  - mid → `Dense_Jungle_Tree_Var*` + `Banana_tree_group`, scaled to h
  - under → `Forest_bush*`/`Common_bush*` + Tropical Plants prefabs (native scale × placement scale)
  - ground → Ground Foliage prefabs (native scale × placement scale)
  - wall → `Climbing_plants_var*` + `Hanging_vegetation_var*` (positioned at the placement, yaw facing the road: yaw from placement is fine for the pilot)
  Deterministic pool pick: index = (int)(placement.x * 7 + placement.y * 13) mod pool size (stable across runs). All instances static-flagged, grounded via WorldTerrainHeight.

- [ ] **Step 1: Implement PlantForest** — rewrite the planting region of DressSlice per the
contract above. Parse the chunked JSON with the established manual-parse pattern (JsonUtility
can't do nested arrays of objects with floats reliably — reuse the MiniJson approach already
in the file, extended to the chunk/plants nesting). Remove PlantTrees/ScatterUnderstory and
their menu references; `Dress()` order becomes ...BuildOverlay → PaintDetails → PlantForest →
ImportBackdrop → PlaceBarrier → SetAtmosphere-compatible steps (atmosphere now owned by
SetupHdrp — Dress() must NOT recreate fog/sun conflicting with the volume; strip the old
RenderSettings fog/sun code, keep only the NOAA sun rotation on the directional light).

- [ ] **Step 2: Sync + Dress via Unity_RunCommand** — expect console clean; printout of
per-chunk and per-layer instance counts; total must match the JSON count.

- [ ] **Step 3: Editor fps probe** — Play mode via the established focus workaround, 300-frame
sample at the slice, record avg/worst fps (target ≥ 30 avg on this machine; if below, report
numbers — do NOT thin the forest on your own; the controller decides).

- [ ] **Step 4: Captures** — forest_s460/530/640.png to the workspace; verify: layered walls
of vegetation (ground cover, bushes, midstory, canopy), creepers at the wall line, no
floaters, no magenta, shadows from trees on the road mosaic.

- [ ] **Step 5: Commit**

```bash
git add unity/DressSlice.cs && git commit -m "feat: PlantForest - mass layered planting from stage 75"
```

---

### Task 4: Fidelity pass + acceptance

- [ ] **Step 1: Grading match**: extract 3 video reference frames (v=105/117/131 forward
crops via ffmpeg v360 at the calibrated az0=110 yaw offset — reuse the yaw-probe pattern:
`yaw = (heading − 110) normalized`, h_fov 70) and render matching captures; adjust the
`[GEN] Atmosphere` volume's ColorAdjustments (saturation/temperature/contrast) + Exposure via
Unity_RunCommand until the render's road/foliage tones sit close to the frames. Iterate ≤ 4
rounds; save volume changes to the profile asset. Record before/after values.
- [ ] **Step 2: Wind check**: report whether SeedMesh graphs animate under HDRP (observe two
captures 2 s apart in Play mode for foliage movement, or inspect the shader for time-based
nodes); if not animating, note it — do not chase custom wind in this plan.
- [ ] **Step 3: CONTROLLER — side-by-side review**: controller Reads render vs video frame
pairs and judges composition/tone; applies at most one more grading tweak round.
- [ ] **Step 4: Full suite + push**: `venv/Scripts/python -m pytest tests/` (35 expected =
31 + 4 new), commit any tuning, push branch.
- [ ] **Step 5: USER CHECKPOINT — the replica drive**: user drives the slice in-editor:
dense layered rainforest, tree shadows on the road, ≥ 30 fps, "looks like the footage"
judgment. Tuning notes → controller applies → re-dress.

---

## Self-Review Notes

- Spec coverage: HDRP migration incl. Unlit+Shadow-Matte road and SeedMesh reversion (Task 1),
  stage 75 layered/deterministic/chunked planting with band + exclusion (Task 2), PlantForest
  with pools/scaling/static/chunks + fps probe (Task 3), grading/wind/acceptance (Task 4).
  ShellPilot cleanup folded into Task 1 Step 4 (suspended throwaway). Underlay decision =
  backdrop stays (no removal task — correct).
- Placeholder scan: clean; stage-75 code is complete with an explicit implementer note on the
  hash-determinism fix (test-enforced).
- Type consistency: forest_placements.json schema identical in Tasks 2/3 (layer/x/y/h/yaw/
  scale, chunks[s0]); `WorldTerrainHeight` and `MakeShadowMatteUnlit` names match across
  tasks; sun/atmosphere ownership split (SetupHdrp owns volume; Dress keeps only NOAA
  rotation) stated in both Task 1 and Task 3.
