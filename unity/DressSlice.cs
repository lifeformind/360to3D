// Dresses the vertical-slice scene: road overlay, verge grass/fern detail, layered forest
// (PlantForest, stage-75 placements), foliage cards, backdrop mountains, barrier, sun.
// Atmosphere (sky/fog/exposure) is owned by SetupHdrp's [GEN] Atmosphere volume - Dress()
// only rotates the sun (NOAA position) and keeps its HDRP Lux intensity in sync, it does not
// write any RenderSettings.fog/sky. Menu: Amakeng > Dress Slice.
// Idempotent: every step deletes/replaces its own [GEN] Slice child (or TerrainData layer)
// before rebuilding, so re-running Dress() after re-syncing exports is always safe.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Amakeng
{
    [Serializable] public class CardPlacement { public float x, y, h, h_raw; public string img; public float yaw_deg; }
    [Serializable] public class PlacementsRoot { public CardPlacement[] cards; }
    [Serializable] public class VergeMeta { public float xmin, ymax, px_m; public int width, height; }
    [Serializable] public class BarrierExtra { public float s, lat, len_m; }
    [Serializable] public class SliceExtras { public BarrierExtra barrier; }
    [Serializable] public class CenterlineStation { public float s, x, y, z, tx, ty, w; public bool provisional; }
    [Serializable] public class CenterlineRoot { public float z0, px_per_m; public CenterlineStation[] stations; }

    // Minimal MiniJson-style recursive-descent parser (object -> Dictionary<string,object>,
    // array -> List<object>, number -> double, string -> string, true/false -> bool, null ->
    // null). export/forest_placements.json nests one level deeper than JsonUtility's existing
    // callers in this file handle (chunks[].plants[].{layer,x,y,h,yaw,scale} - an array of
    // objects each containing another array of objects, mixing a string field with floats) -
    // JsonUtility's FromJson<T> requires the whole shape to be declared as concrete
    // [Serializable] C# types up front and has known unreliable edge cases on nested
    // float-bearing object arrays, so PlantForest walks this generic parse result directly
    // instead (same "manual parse, don't trust JsonUtility for this shape" spirit as
    // ParseStations() below, generalized rather than hand-indexed since the schema nests
    // deeper than a single flat array).
    static class MiniJson
    {
        public static object Parse(string json)
        {
            int i = 0;
            return ParseValue(json, ref i);
        }

        static void SkipWs(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        static object ParseValue(string s, ref int i)
        {
            SkipWs(s, ref i);
            char c = s[i];
            if (c == '{') return ParseObject(s, ref i);
            if (c == '[') return ParseArray(s, ref i);
            if (c == '"') return ParseString(s, ref i);
            if (c == 't') { i += 4; return true; }
            if (c == 'f') { i += 5; return false; }
            if (c == 'n') { i += 4; return null; }
            return ParseNumber(s, ref i);
        }

        static Dictionary<string, object> ParseObject(string s, ref int i)
        {
            var d = new Dictionary<string, object>();
            i++; // '{'
            SkipWs(s, ref i);
            if (s[i] == '}') { i++; return d; }
            while (true)
            {
                SkipWs(s, ref i);
                string key = ParseString(s, ref i);
                SkipWs(s, ref i);
                i++; // ':'
                d[key] = ParseValue(s, ref i);
                SkipWs(s, ref i);
                if (s[i] == ',') { i++; continue; }
                i++; // '}'
                break;
            }
            return d;
        }

        static List<object> ParseArray(string s, ref int i)
        {
            var l = new List<object>();
            i++; // '['
            SkipWs(s, ref i);
            if (s[i] == ']') { i++; return l; }
            while (true)
            {
                l.Add(ParseValue(s, ref i));
                SkipWs(s, ref i);
                if (s[i] == ',') { i++; continue; }
                i++; // ']'
                break;
            }
            return l;
        }

        static string ParseString(string s, ref int i)
        {
            i++; // opening quote
            var sb = new StringBuilder();
            while (s[i] != '"')
            {
                if (s[i] == '\\')
                {
                    i++;
                    char e = s[i];
                    switch (e)
                    {
                        case 'n': sb.Append('\n'); break;
                        case 't': sb.Append('\t'); break;
                        case 'r': sb.Append('\r'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'u':
                            int code = int.Parse(s.Substring(i + 1, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                            sb.Append((char)code);
                            i += 4;
                            break;
                        default: sb.Append(e); break;
                    }
                    i++;
                }
                else { sb.Append(s[i]); i++; }
            }
            i++; // closing quote
            return sb.ToString();
        }

        static object ParseNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length && (char.IsDigit(s[i]) || s[i] == '-' || s[i] == '+' ||
                s[i] == '.' || s[i] == 'e' || s[i] == 'E')) i++;
            return double.Parse(s.Substring(start, i - start), CultureInfo.InvariantCulture);
        }
    }

    public static class DressSlice
    {
        const string GenDir = "Assets/Amakeng/Generated";
        const string TerrainPackRoot = "Assets/TerrainSampleAssets";
        // SeedMesh tropical packs use Shader Graph materials (Shader Graphs/SeedMesh_* and
        // Shader Graphs/Basic_vegetation), all HDRP-targeted only (HDTarget, no
        // UniversalTarget - confirmed by grepping "m_ActiveTargets"/"m_Type" in each
        // .shadergraph file). Under HDRP (this project's pipeline as of the Task 1 HDRP
        // migration) these are the packs' NATIVE shaders and need no conversion at all - see
        // WarnIfSeedMeshNotNative() below, which replaces the URP-era
        // FixSeedMeshMaterialsForUrp() workaround this project used to carry.
        const string SeedMeshJungleRoot = "Assets/SeedMesh/Jungle-Tropical Vegetation/Vegetation";
        const string SeedMeshTropicalPlantsRoot = "Assets/SeedMesh/Tropical Plants Package/Prefabs";
        const string SeedMeshGroundFoliageRoot = "Assets/SeedMesh/Ground Foliage Vol.2/Prefabs";

        // HDRP migration (Task 1): FixSeedMeshMaterialsForUrp() used to repoint every
        // HDRP-targeted SeedMesh material onto "Universal Render Pipeline/Lit" by MUTATING
        // the pack's own shipped .mat assets in place (same GUID/path, shader field
        // overwritten) - there was never a separate "converted" copy asset to delete, so the
        // brief's literal "delete the converted asset + reassign renderers to the prefab's
        // own sharedMaterials" cleanup does not apply to how this actually worked (instance
        // renderers were never given per-instance overrides either - PlantTrees/
        // ScatterUnderstory only ever set transform, never sharedMaterials - so there was
        // nothing to reassign there). The mutation had already corrupted 87 of the 108
        // materials under Assets/SeedMesh in this project; since the original shader
        // assignment is not recoverable from the mutated .mat file itself, the repair
        // restores pristine bytes for every affected .mat by GUID-matching against this
        // machine's cached SeedMesh Asset Store packages - see `scripts/
        // fix_seedmesh_materials.py` (its own docstring has the full method) and
        // `docs/full-circuit-rollout-notes.md`'s "SeedMesh material recovery" section. That
        // repair depends on machine-local package cache paths, so it's a script to run when
        // needed (WarnIfSeedMeshNotNative below names it), not something Dress() calls
        // automatically; what belongs here is (a) never calling FixSeedMeshMaterialsForUrp
        // again (deleted), and (b) a cheap regression guard that fails loudly if any
        // Assets/SeedMesh material is ever found back on a "Universal ..." shader.
        static void WarnIfSeedMeshNotNative()
        {
            var guids = AssetDatabase.FindAssets("t:Material", new[] { "Assets/SeedMesh" });
            int nonNative = 0;
            foreach (var guid in guids)
            {
                var mat = AssetDatabase.LoadAssetAtPath<Material>(AssetDatabase.GUIDToAssetPath(guid));
                if (mat != null && mat.shader != null && mat.shader.name.StartsWith("Universal Render Pipeline"))
                {
                    Debug.LogError("[DressSlice] WarnIfSeedMeshNotNative: " + AssetDatabase.GUIDToAssetPath(guid) +
                        " is still on a URP shader (" + mat.shader.name + "), not its native Shader Graph. Restore " +
                        "it with scripts/fix_seedmesh_materials.py (reads this machine's local Asset Store package " +
                        "cache - see that script's docstring).");
                    nonNative++;
                }
            }
            if (nonNative == 0)
                Debug.Log("[DressSlice] WarnIfSeedMeshNotNative: all Assets/SeedMesh materials are on native (non-URP) shaders.");

            // Orphaned leftovers from a removed TreePackVol.1-era feature: never referenced by
            // any renderer in the scene and not (re)created by any current code path, but
            // still sitting on Universal Render Pipeline/Lit - delete rather than "convert"
            // dead assets to HDRP/Lit for no purpose.
            foreach (var guid in AssetDatabase.FindAssets("TreeTint t:Material", new[] { "Assets/Amakeng" }))
                AssetDatabase.DeleteAsset(AssetDatabase.GUIDToAssetPath(guid));
        }
        // mesh-as-base baseline: with the photogrammetry mesh now standing in for the
        // ground close to the road, the flat foliage-card quads read as floating ovals
        // against it. Disabled for this baseline; the PlaceCards code path is kept intact
        // (just early-returns) for a future re-enable.
        const bool CARDS_ENABLED = false;

        static float MeasureHeight(GameObject prefab)
        {
            var renderers = prefab.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return 6f;
            var b = renderers[0].bounds;
            foreach (var r in renderers) b.Encapsulate(r.bounds);
            return Mathf.Max(0.5f, b.size.y);
        }

        // Terrain.SampleHeight() in this project does NOT reliably include the terrain
        // GameObject's own transform.position.y - confirmed by comparing it against a
        // Physics.Raycast onto the live TerrainCollider (ground truth): the raycast hit
        // matched SampleHeight(xz) + terrain.transform.position.y almost exactly (both
        // on- and off-road test points), not SampleHeight(xz) alone (which was off by
        // ~7.9 m, i.e. by |height_min| - the terrain's own Y origin). Centralised here so
        // every placement call site (trees, understory, barrier) uses the same, verified
        // formula instead of each guessing independently.
        static float WorldTerrainHeight(Terrain terrain, float worldX, float worldZ) =>
            terrain.SampleHeight(new Vector3(worldX, 0f, worldZ)) + terrain.transform.position.y;

        // Discovers prefabs under `root` (recursively, via FindAssets - robust to pack
        // reorganization) whose filename starts with `prefix` (case-insensitive), or all
        // prefabs under `root` matching an optional predicate. Sorted for a deterministic
        // order.
        static List<GameObject> DiscoverPrefabs(string root, Func<string, bool> nameFilter = null)
        {
            var guids = AssetDatabase.FindAssets("t:Prefab", new[] { root });
            IEnumerable<string> paths = guids.Select(AssetDatabase.GUIDToAssetPath).Distinct();
            if (nameFilter != null)
                paths = paths.Where(p => nameFilter(Path.GetFileNameWithoutExtension(p)));
            return paths.OrderBy(p => p, StringComparer.Ordinal)
                .Select(p => AssetDatabase.LoadAssetAtPath<GameObject>(p))
                .Where(go => go != null).ToList();
        }

        static List<GameObject> DiscoverByPrefix(string root, string prefix) =>
            DiscoverPrefabs(root, name => name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));

        // "Pot_*" prefabs in the Tropical Plants pack are potted-plant props (a container +
        // plant, meant for indoor/patio scenes) - excluded from outdoor roadside placement.
        static List<GameObject> DiscoverTropicalPlantsMix() =>
            DiscoverPrefabs(SeedMeshTropicalPlantsRoot,
                name => !name.StartsWith("Pot", StringComparison.OrdinalIgnoreCase));

        [MenuItem("Amakeng/Dress Slice")]
        public static void Dress()
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
            var scene = EditorSceneManager.OpenScene(BuildAmakeng.ScenePath, OpenSceneMode.Single);

            // Cleanup: remove the ad hoc "[PROBE] Trees" group used to hand-prove the
            // TreePackVol.1 URP material conversion recipe before it was wired into the
            // (since-removed) PlantTrees - that whole conversion path is gone along with the
            // TreePackVol.1 pack itself; SeedMesh needs no such conversion (see
            // WarnIfSeedMeshNotNative below).
            var probeTrees = GameObject.Find("[PROBE] Trees");
            if (probeTrees != null) UnityEngine.Object.DestroyImmediate(probeTrees);

            // Cleanup (SeedMesh rework): TreePackVol.1 is being removed at the user's
            // request (re-importable from their account if ever needed again) now that
            // SeedMesh supplies URP-native trees with no conversion step. Also removes the
            // TreeConv_* materials that were converted from it - both idempotent (no-op if
            // already gone). Assets/TerrainSampleAssets is NOT touched - its terrain layers
            // and grass/fern detail textures are still used by PaintDetails/FixGroundMaterial.
            if (AssetDatabase.IsValidFolder("Assets/TreePackVol.1"))
                AssetDatabase.DeleteAsset("Assets/TreePackVol.1");
            foreach (var guid in AssetDatabase.FindAssets("TreeConv", new[] { GeneratedMaterialsDir }))
                AssetDatabase.DeleteAsset(AssetDatabase.GUIDToAssetPath(guid));

            WarnIfSeedMeshNotNative();
            BuildOverlay();
            PaintDetails();
            FixGroundMaterial();
            PlantForest();
            PlaceCards();
            ImportBackdrop();
            PlaceBarrier();
            SetAtmosphere();

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            Debug.Log("[DressSlice] Dress: slice dressed and saved to " + BuildAmakeng.ScenePath);
        }

        static float Pf(string s) => float.Parse(s, CultureInfo.InvariantCulture);

        const string GeneratedMaterialsDir = "Assets/Amakeng/GeneratedMaterials";

        static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            var parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            var name = Path.GetFileName(path);
            AssetDatabase.CreateFolder(parent, name);
        }

        static GameObject GetSliceRoot()
        {
            var root = GameObject.Find("[GEN] Slice");
            if (root == null) root = new GameObject("[GEN] Slice");
            return root;
        }

        static GameObject ReplaceChild(GameObject parent, string name)
        {
            var existing = parent.transform.Find(name);
            if (existing != null) UnityEngine.Object.DestroyImmediate(existing.gameObject);
            var go = new GameObject(name);
            go.transform.SetParent(parent.transform, false);
            return go;
        }

        // Like ReplaceChild, but for a top-level "[GEN] X" root (a sibling of "[GEN] Slice"/
        // "[GEN] Terrain", not nested under either) - PlantForest's own [GEN] Forest root uses
        // this rather than ReplaceChild(GetSliceRoot(), ...) since the brief names it "[GEN]
        // Forest" (the same top-level naming convention as "[GEN] Terrain"), not "Forest" as a
        // child of "[GEN] Slice" (the convention the removed PlantTrees/ScatterUnderstory used
        // for their "Trees"/"Understory" children). Full delete+recreate (not per-child
        // ReplaceChild) is correct here: PlantForest has no sub-state worth preserving between
        // runs, and this guarantees stale chunk_NNN children from a previous placements.json
        // (different chunk count/names) never linger.
        static GameObject ReplaceRoot(string name)
        {
            var existing = GameObject.Find(name);
            if (existing != null) UnityEngine.Object.DestroyImmediate(existing);
            return new GameObject(name);
        }

        // Marks an instantiated placement (and all its children - SeedMesh prefabs are often
        // multi-renderer hierarchies) static, satisfying the "all instances static-flagged"
        // requirement (batching/GI/occlusion eligible - these are fixed set-dressing, never
        // move at runtime).
        static void MarkStaticRecursive(Transform t)
        {
            t.gameObject.isStatic = true;
            foreach (Transform child in t) MarkStaticRecursive(child);
        }

        static PlacementsRoot LoadPlacements()
        {
            string path = Path.Combine(GenDir, "foliage_cards", "placements.json");
            if (!File.Exists(path)) return null;
            return JsonUtility.FromJson<PlacementsRoot>(File.ReadAllText(path));
        }

        // Discovers a prefab under a pack root via AssetDatabase.FindAssets (robust to the
        // pack being reorganized), preferring an exact-name match and falling back to the
        // first prefab whose name contains the fallback substring.
        static GameObject FindPrefabPreferred(string root, string preferredName, string fallbackContains)
        {
            var guids = AssetDatabase.FindAssets("t:Prefab " + preferredName, new[] { root });
            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (Path.GetFileNameWithoutExtension(path) == preferredName)
                    return AssetDatabase.LoadAssetAtPath<GameObject>(path);
            }
            guids = AssetDatabase.FindAssets("t:Prefab", new[] { root });
            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (Path.GetFileNameWithoutExtension(path).IndexOf(fallbackContains, StringComparison.OrdinalIgnoreCase) >= 0)
                    return AssetDatabase.LoadAssetAtPath<GameObject>(path);
            }
            return null;
        }

        // -------------------------------------------------------------------
        // 2. Road overlay mesh (per-tile albedo).
        // -------------------------------------------------------------------
        class ObjGroup { public string Name; public List<int> Faces = new List<int>(); }

        // HDRP Unlit + Shadow Matte for the baked road-mosaic photography: Unlit so the
        // photo's own baked lighting isn't re-lit/double-exposed by the scene's directional
        // light, "Shadow Matte" so real-time cast shadows (trees, barrier) still composite
        // onto it.
        //
        // HDRP 17.3 API discovery (vs. the task brief's skeleton, which named
        // `_EnableShadowMatte` + keyword `_ENABLE_SHADOW_MATTE`): traced through the
        // installed HDRP package source (Runtime/Material/Unlit/*). The `_ENABLE_SHADOW_MATTE`
        // keyword only gates code inside `#if ... && (SHADERPASS == SHADERPASS_PATH_TRACING)`
        // blocks in Unlit.cs.hlsl/UnlitData.hlsl - it affects path-traced rendering only, not
        // the real-time raster passes this project uses. The actual raster-time mechanism
        // (Editor/Material/Unlit/UnlitAPI.cs: `ValidateMaterial`) reads a DIFFERENT property,
        // `HDStringConstants.kShadowMatteFilter` = "_ShadowMatteFilter", to decide whether to
        // set up the stencil bit that makes the surface receive real-time shadow/lighting
        // compositing - but that property is not declared in the fixed "HDRP/Unlit" shader's
        // own Properties block at all (confirmed by grep - zero occurrences in Unlit.shader),
        // so `Material.HasProperty("_ShadowMatteFilter")` - the exact gate ValidateMaterial
        // checks - is false on it regardless of what a script sets; Shadow Matte for Unlit
        // surfaces is implemented exclusively via the HD Unlit Shader Graph subtarget's
        // dedicated toggle (confirmed empirically too: a probe plane on "HDRP/Unlit" with
        // `_ShadowMatteFilter=1` showed no shadow from a cube suspended above it - see
        // task-1-report.md).
        //
        // Fix (per controller ruling, review round 2): rather than authoring that graph once
        // by hand in the Shader Graph editor UI and committing the binary asset (the one
        // exception to this project's "everything under Assets/Amakeng is generated by
        // committed code" discipline), `scripts/72_shadowmatte_shadergraph.py` generates
        // `Assets/Amakeng/HDRP/OverlayShadowMatteUnlit.shadergraph` from HDRP's own shipped
        // SolidColor.shadergraph (a minimal, known-good single-target HD Unlit graph) by
        // surgically editing its JSON text: swaps its Color property for a Texture2D property
        // (exposed as `_UnlitColorMap`, matching the texture-property name this method already
        // used) sampled through a "Sample Texture 2D" node into Base Color, and flips
        // HDUnlitData's Shadow Matte flag on. Verified live: the resulting material's
        // `_ShadowMatteFilter` property IS present (`HasProperty` true) and a shadow-casting
        // probe cube confirmed a real shadow composites onto it, unlike the plain "HDRP/Unlit"
        // shader - see task-1-report.md for the full comparison against the HDRP/Lit
        // alternative (which also receives shadows, but re-lights the baked photo through
        // normal PBR shading instead of keeping it Unlit; this Shader Graph route was chosen
        // as the closer match to the brief's literal "HDRP Unlit + Shadow Matte" requirement).
        public static Material MakeShadowMatteUnlit(Texture tex)
        {
            var shader = AssetDatabase.LoadAssetAtPath<Shader>(
                "Assets/Amakeng/HDRP/OverlayShadowMatteUnlit.shadergraph");
            if (shader == null)
            {
                Debug.LogError("[DressSlice] MakeShadowMatteUnlit: Assets/Amakeng/HDRP/OverlayShadowMatteUnlit.shadergraph " +
                    "not found - run scripts/72_shadowmatte_shadergraph.py (via scripts/70_sync_unity.py) before Dress().");
                shader = Shader.Find("HDRP/Unlit"); // degrade gracefully: still Unlit, just without Shadow Matte
            }
            var m = new Material(shader);
            if (tex != null) m.SetTexture("_UnlitColorMap", tex);
            if (m.HasProperty("_ShadowMatteFilter")) m.SetFloat("_ShadowMatteFilter", 1f);
            UnityEditor.Rendering.HighDefinition.HDShaderUtils.ResetMaterialKeywords(m);
            return m;
        }

        static void BuildOverlay()
        {
            var overlayRoot = ReplaceChild(GetSliceRoot(), "Overlay");

            string path = Path.Combine(GenDir, "road_overlay.obj");
            if (!File.Exists(path))
            {
                Debug.LogError("[DressSlice] BuildOverlay: missing " + path);
                return;
            }

            var positions = new List<Vector3>();
            var uvs = new List<Vector2>();
            var groups = new List<ObjGroup>();
            ObjGroup cur = null;

            foreach (var raw in File.ReadAllLines(path))
            {
                if (raw.Length < 2) continue;
                if (raw[0] == 'o' && raw[1] == ' ')
                {
                    cur = new ObjGroup { Name = raw.Substring(2).Trim() };
                    groups.Add(cur);
                }
                else if (raw[0] == 'v' && raw[1] == ' ')
                {
                    var p = raw.Substring(2).Trim().Split(' ');
                    // road_overlay.obj is authored in the same right-handed OBJ convention as
                    // road.obj (a known-good file in this project): Unity's standard model
                    // importer converts right-handed -> left-handed on import by negating X AND
                    // reversing triangle winding together, which is why road.obj (imported the
                    // normal way in BuildAmakeng.BuildRoad) lines up correctly without any extra
                    // handling. This method bypasses Unity's importer entirely (see BuildOverlay
                    // header comment for why) and parses the raw OBJ text instead, so it must
                    // replicate BOTH halves of that conversion itself: X is negated here, and
                    // winding is reversed in the face-triangulation loop below. Negating X alone
                    // was verified against road_meta.json centreline stations (nearest-station
                    // distance: 564 m average raw vs 4.9 m average once negated, consistent with
                    // the mesh's 7 m lateral half-width) before the winding half of the fix was
                    // added.
                    positions.Add(new Vector3(-Pf(p[0]), Pf(p[1]), Pf(p[2])));
                }
                else if (raw[0] == 'v' && raw[1] == 't')
                {
                    var p = raw.Substring(3).Trim().Split(' ');
                    uvs.Add(new Vector2(Pf(p[0]), Pf(p[1])));
                }
                else if (raw[0] == 'f' && raw[1] == ' ' && cur != null)
                {
                    var toks = raw.Substring(2).Trim().Split(' ');
                    var idx = new int[toks.Length];
                    for (int i = 0; i < toks.Length; i++)
                        idx[i] = int.Parse(toks[i].Split('/')[0], CultureInfo.InvariantCulture) - 1;
                    for (int i = 1; i < idx.Length - 1; i++) // fan-triangulate n-gons
                    {
                        // Winding is reversed here (idx[i+1] before idx[i]) to pair with the X
                        // negation above: Unity's own OBJ importer applies a mirror + winding
                        // flip together as a single right-handed -> left-handed conversion. This
                        // manual parser only negates X, so it must also reverse winding itself or
                        // normals come out inverted (RecalculateNormals follows winding) and the
                        // overlay back-face-culls from driver angles under URP Lit's default Cull
                        // Back.
                        cur.Faces.Add(idx[0]); cur.Faces.Add(idx[i + 1]); cur.Faces.Add(idx[i]);
                    }
                }
            }

            int built = 0;
            foreach (var g in groups)
            {
                if (g.Faces.Count == 0) continue;
                var map = new Dictionary<int, int>();
                var mVerts = new List<Vector3>();
                var mUvs = new List<Vector2>();
                var mTris = new List<int>(g.Faces.Count);
                foreach (var gi in g.Faces)
                {
                    if (!map.TryGetValue(gi, out int li))
                    {
                        li = mVerts.Count;
                        map[gi] = li;
                        mVerts.Add(positions[gi]);
                        mUvs.Add(uvs[gi]);
                    }
                    mTris.Add(li);
                }

                var mesh = new Mesh { name = g.Name };
                mesh.SetVertices(mVerts);
                mesh.SetUVs(0, mUvs);
                mesh.SetTriangles(mTris, 0);
                mesh.RecalculateNormals();
                mesh.RecalculateBounds();

                var go = new GameObject(g.Name);
                go.transform.SetParent(overlayRoot.transform, false);
                go.AddComponent<MeshFilter>().sharedMesh = mesh;
                var mr = go.AddComponent<MeshRenderer>();
                // no collider on the overlay - it rides visually on top of the road mesh, which
                // already carries the drivable MeshCollider.

                string tileNum = g.Name.Length >= 2 ? g.Name.Substring(g.Name.Length - 2) : "";
                string texPath = GenDir + "/road_albedo/tile_" + tileNum + ".png";
                // Final review: these 4096x512 mosaic tiles were importing at Unity's
                // default maxTextureSize (2048), halving them to 10 cm/px on the road
                // instead of the authored 5 cm/px. Force full resolution + uncompressed +
                // sRGB before loading, same pattern as PaintDetails' density.png override.
                var timp = AssetImporter.GetAtPath(texPath) as TextureImporter;
                if (timp != null && (timp.maxTextureSize < 4096 ||
                    timp.textureCompression != TextureImporterCompression.Uncompressed || !timp.sRGBTexture))
                {
                    timp.maxTextureSize = 4096;
                    timp.textureCompression = TextureImporterCompression.Uncompressed;
                    timp.sRGBTexture = true;
                    timp.SaveAndReimport();
                }
                var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(texPath);

                string matPath = "Assets/Amakeng/OverlayTile" + tileNum + ".mat";
                AssetDatabase.DeleteAsset(matPath);
                // HDRP Unlit + Shadow Matte: the road mosaic is baked (lit) photography, so it
                // should not be re-lit by the scene's directional light like a normal surface
                // (that would double-expose it) - Unlit keeps the photo's own baked lighting,
                // while Shadow Matte still composites real-time scene shadows (trees, barrier)
                // onto it for the "photo look, receives shadows" requirement.
                var mat = MakeShadowMatteUnlit(tex);
                mat.name = "OverlayTile" + tileNum;
                if (tex == null)
                    Debug.LogWarning("[DressSlice] BuildOverlay: albedo texture not found at " + texPath);
                AssetDatabase.CreateAsset(mat, matPath);
                mr.sharedMaterial = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                built++;
            }
            Debug.Log("[DressSlice] BuildOverlay: " + built + " tile mesh(es) built under [GEN] Slice/Overlay.");
        }

        // -------------------------------------------------------------------
        // 3. Terrain detail layers (verge grass/fern) painted from density.png.
        // -------------------------------------------------------------------
        static void PaintDetails()
        {
            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] PaintDetails: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();
            var td = terrain.terrainData;

            // Adaptation: use mesh-based detail prototypes (usePrototypeMesh, DetailRenderMode.
            // VertexLit) from the pack's Grass_A/Fern_A prefabs rather than raw grass/fern
            // textures painted with DetailRenderMode.GrassBillboard/Grass - those legacy render
            // modes use the built-in grass shader, which does not render correctly under URP.
            // The prefab meshes already carry pack-native (post-conversion) URP materials.
            // Discovered via AssetDatabase.FindAssets (see FindPrefabPreferred), not a hardcoded
            // path, so this keeps working if TerrainSampleAssets is reorganized.
            const string TerrainPackRoot = "Assets/TerrainSampleAssets";
            var grassPrefab = FindPrefabPreferred(TerrainPackRoot, "Grass_A", "Grass");
            var fernPrefab = FindPrefabPreferred(TerrainPackRoot, "Fern_A", "Fern");
            if (grassPrefab == null || fernPrefab == null)
            {
                Debug.LogError("[DressSlice] PaintDetails: TerrainSampleAssets Grass_A/Fern_A prefabs missing; skipping.");
                return;
            }

            td.detailPrototypes = new[]
            {
                new DetailPrototype { prototype = grassPrefab, usePrototypeMesh = true, renderMode = DetailRenderMode.VertexLit,
                    minWidth = 0.8f, maxWidth = 1.3f, minHeight = 0.6f, maxHeight = 1.0f, useInstancing = true },
                new DetailPrototype { prototype = fernPrefab, usePrototypeMesh = true, renderMode = DetailRenderMode.VertexLit,
                    minWidth = 0.6f, maxWidth = 1.0f, minHeight = 0.5f, maxHeight = 0.9f, useInstancing = true },
            };

            if (td.detailWidth != 512 || td.detailHeight != 512)
                td.SetDetailResolution(512, 32);

            var zeros = new int[td.detailHeight, td.detailWidth];
            td.SetDetailLayer(0, 0, 0, zeros);
            td.SetDetailLayer(0, 0, 1, zeros);

            string metaPath = Path.Combine(GenDir, "verge_masks", "meta.json");
            string relPng = GenDir + "/verge_masks/density.png";
            if (!File.Exists(metaPath) || !File.Exists(Path.Combine(GenDir, "verge_masks", "density.png")))
            {
                Debug.LogWarning("[DressSlice] PaintDetails: verge_masks missing; detail layers left empty.");
                return;
            }
            var meta = JsonUtility.FromJson<VergeMeta>(File.ReadAllText(metaPath));

            // Force uncompressed, unscaled, readable import: the default import settings
            // downscale this NPOT mask (e.g. 767x319 -> 512x256), which would silently
            // misalign the world<->pixel mapping below if left as-is.
            var imp = AssetImporter.GetAtPath(relPng) as TextureImporter;
            if (imp != null && (!imp.isReadable || imp.npotScale != TextureImporterNPOTScale.None ||
                imp.maxTextureSize < Mathf.Max(meta.width, meta.height) ||
                imp.textureCompression != TextureImporterCompression.Uncompressed))
            {
                imp.isReadable = true;
                imp.npotScale = TextureImporterNPOTScale.None;
                imp.maxTextureSize = Mathf.Max(2048, Mathf.NextPowerOfTwo(Mathf.Max(meta.width, meta.height)));
                imp.textureCompression = TextureImporterCompression.Uncompressed;
                imp.mipmapEnabled = false;
                imp.SaveAndReimport();
            }
            var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(relPng);
            if (tex == null)
            {
                Debug.LogWarning("[DressSlice] PaintDetails: could not load " + relPng);
                return;
            }
            if (tex.width != meta.width || tex.height != meta.height)
                Debug.LogWarning("[DressSlice] PaintDetails: density.png size " + tex.width + "x" + tex.height +
                    " does not match meta.json " + meta.width + "x" + meta.height + "; using texture size.");
            int texW = tex.width, texH = tex.height;
            var pix = tex.GetPixels();

            Vector3 terrPos = terrGo.transform.position;
            Vector3 size = td.size;
            var grassMap = new int[td.detailHeight, td.detailWidth];
            var fernMap = new int[td.detailHeight, td.detailWidth];

            float worldXmin = meta.xmin, worldXmax = meta.xmin + meta.width * meta.px_m;
            float worldZmax = meta.ymax, worldZmin = meta.ymax - meta.height * meta.px_m;

            int xIdxMin = Mathf.Clamp(Mathf.FloorToInt((worldXmin - terrPos.x) / size.x * td.detailWidth), 0, td.detailWidth - 1);
            int xIdxMax = Mathf.Clamp(Mathf.CeilToInt((worldXmax - terrPos.x) / size.x * td.detailWidth), 0, td.detailWidth);
            int yIdxMin = Mathf.Clamp(Mathf.FloorToInt((worldZmin - terrPos.z) / size.z * td.detailHeight), 0, td.detailHeight - 1);
            int yIdxMax = Mathf.Clamp(Mathf.CeilToInt((worldZmax - terrPos.z) / size.z * td.detailHeight), 0, td.detailHeight);

            // Map meta-space pixel coords (as authored, meta.width x meta.height) into the
            // actual imported texture's pixel grid, in case the importer still rescaled it.
            float scaleX = texW / (float)meta.width;
            float scaleY = texH / (float)meta.height;

            int painted = 0;
            for (int dy = yIdxMin; dy < yIdxMax; dy++)
            {
                float worldZ = terrPos.z + (dy + 0.5f) / td.detailHeight * size.z;
                for (int dx = xIdxMin; dx < xIdxMax; dx++)
                {
                    float worldX = terrPos.x + (dx + 0.5f) / td.detailWidth * size.x;
                    // density.png row 0 = top of image = ymax (north); Unity texture y=0 = bottom.
                    int imgCol = Mathf.RoundToInt((worldX - meta.xmin) / meta.px_m * scaleX);
                    int imgRow = Mathf.RoundToInt((meta.ymax - worldZ) / meta.px_m * scaleY);
                    if (imgCol < 0 || imgCol >= texW || imgRow < 0 || imgRow >= texH) continue;
                    int texY = texH - 1 - imgRow;
                    float density = pix[texY * texW + imgCol].grayscale;
                    if (density <= 0.001f) continue;
                    grassMap[dy, dx] = Mathf.RoundToInt(density * 6f);
                    fernMap[dy, dx] = Mathf.RoundToInt(density * 2f);
                    painted++;
                }
            }

            td.SetDetailLayer(0, 0, 0, grassMap);
            td.SetDetailLayer(0, 0, 1, fernMap);
            Debug.Log("[DressSlice] PaintDetails: painted " + painted + " detail cell(s) (grass+fern) from verge density mask.");
        }

        // -------------------------------------------------------------------
        // Ground material fix-up (review round 3, item 2): the terrain read as glossy
        // "minty waves" - Part A's procedural GroundLayer had non-zero default
        // smoothness/specular (URP Lit's defaults) giving it a wet/plastic sheen, and its
        // base colour (0.24, 0.34, 0.16) skewed brighter/greener than the footage's matte
        // verge tones. This is the Part A TerrainLayer set up in BuildAmakeng.BuildTerrain,
        // not something DressSlice normally owns, but the fix is applied here (in-place, on
        // the already-built [GEN] Terrain) rather than editing BuildAmakeng.cs, per review
        // instruction. Idempotent: rebuilds the same 128x128 texture with the same noise
        // algorithm/seed each run rather than editing pixels in place, so it doesn't depend
        // on the existing sub-asset texture still being CPU-readable.
        // -------------------------------------------------------------------
        static void FixGroundMaterial()
        {
            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] FixGroundMaterial: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();
            var td = terrain.terrainData;

            var newTex = new Texture2D(128, 128, TextureFormat.RGBA32, false) { name = "GroundTex" };
            var rng = new System.Random(7); // same seed/algorithm as BuildAmakeng.MakeGroundTexture
            var pixels = new Color[128 * 128];
            for (int i = 0; i < pixels.Length; i++)
            {
                float v = 0.85f + (float)rng.NextDouble() * 0.3f;
                pixels[i] = new Color(0.22f * v, 0.30f * v, 0.16f * v); // darker matte verge tone
            }
            newTex.SetPixels(pixels);
            newTex.Apply();

            // Fully replace the TerrainLayer asset (delete + recreate), mirroring
            // BuildAmakeng.BuildTerrain's own layer-creation pattern, rather than mutating
            // the existing TerrainLayer object's fields in place - simpler to reason about
            // and equally idempotent.
            const string layerPath = "Assets/Amakeng/GroundLayer.terrainlayer";
            AssetDatabase.DeleteAsset(layerPath);
            var layer = new TerrainLayer
            {
                tileSize = new Vector2(24, 24),
                specular = Color.black,
                smoothness = 0f,
                metallic = 0f,
            };
            AssetDatabase.CreateAsset(layer, layerPath);
            AssetDatabase.AddObjectToAsset(newTex, layer);
            layer.diffuseTexture = newTex;
            td.terrainLayers = new[] { layer };
            terrain.Flush();

            // Adaptation - the actual source of the "glossy minty wave" sheen: with
            // specular/smoothness/metallic all zeroed, a strong sheen persisted regardless
            // (confirmed by re-texturing the terrain solid red as a diagnostic - the same
            // bright highlight streaks showed up on red too, proving they weren't a colour
            // problem). Isolated by toggling RenderSettings.reflectionIntensity: at its
            // default of 1, URP's skybox-based environment reflection was contributing a
            // strong specular-like sheen to the terrain that a Lit material's own
            // smoothness=0 does not fully suppress (residual grazing-angle Fresnel/skybox
            // contribution); zeroing it eliminates the sheen completely in a side-by-side
            // capture. This is a global render setting, not terrain-specific, but it's the
            // fix that actually delivers "matte ground, not liquid" and this is the step
            // that establishes ground appearance, so it's set here.
            RenderSettings.reflectionIntensity = 0f;

            AssetDatabase.SaveAssets();
            Debug.Log("[DressSlice] FixGroundMaterial: TerrainLayer set matte (smoothness=0, specular=black, " +
                "metallic=0), ground colour darkened to ~(0.22,0.30,0.16), RenderSettings.reflectionIntensity=0 " +
                "(kills residual skybox-reflection sheen).");
        }

        // -------------------------------------------------------------------
        // 4. PlantForest: mass layered rainforest planting from stage 75's deterministic,
        // chunked placements (export/forest_placements.json, synced to Generated/ by
        // 70_sync_unity.py). Replaces PlantTrees (single foliage-card-driven canopy) +
        // ScatterUnderstory (a separate dense-band scatter pass) with one placement source
        // that already encodes 5 layers (canopy/mid/under/ground/wall), a 4-40 m lateral
        // band, and a >=5.5 m road exclusion (all decided in Python, not here - see
        // scripts/75_forest.py). All instances are ordinary instantiated GameObjects (not
        // Terrain tree prototypes - PlantTrees' header comment explains why that path never
        // worked here), grouped under a top-level "[GEN] Forest" root (sibling of "[GEN]
        // Slice"/"[GEN] Terrain", per the brief's own naming) with one "chunk_NNN" child per
        // stage-75 chunk (NNN = that chunk's s0 station, rounded to the metre).
        //
        // Pools (discovered once via FindAssets, same DiscoverPrefabs/DiscoverByPrefix
        // machinery PlantTrees/ScatterUnderstory used):
        //   canopy (h>=12, stage-75's own classification) -> Background_group_var* (multi-
        //     tree clusters) when h>=16, else the taller end of Dense_Jungle_Tree_Var*;
        //     uniformly scaled so the instance's renderer-bounds height reads as h (the same
        //     MeasureHeight-baseline approach PlantTrees used).
        //   mid (6<=h<12) -> Dense_Jungle_Tree_Var* + Banana_tree_group, same h-scaling.
        //   under (1.5<=h<6) -> Forest_bush_var*/Common_bush_var* + Tropical Plants Package
        //     (minus Pot_* props - DiscoverTropicalPlantsMix already excludes those).
        //   ground (<1.5, mostly ground cover - h here is just a locally-sampled canopy
        //     reading, not a target height; stage-75 can emit large h values for "ground" at
        //     spots directly under tall canopy, so ground/under/wall are deliberately NOT
        //     h-scaled) -> Ground Foliage Vol.2, minus the Forest_bush/Common_bush entries
        //     already reserved for "under" (keeps the two pools thematically distinct: low
        //     ground cover vs. knee/waist-height bushes).
        //   wall (canopy-edge creepers) -> Climbing_plants_var* + Hanging_vegetation_var*.
        // under/ground/wall use "native scale x placement.scale": the instance's localScale
        // is the prefab's own authored localScale (its "native" size) times the placement's
        // scale jitter, not normalized against h - matching the brief's pool table exactly.
        //
        // Pool pick is deterministic per placement (stable across runs/machines, not seeded
        // by iteration order): index = floor(x*7 + y*13) mod pool size, floored (not C#'s
        // truncating (int) cast, which rounds negative values toward zero rather than down -
        // these placements' y is always negative, ENU south of the anchor) and normalized
        // non-negative - see DeterministicPoolIndex.
        // -------------------------------------------------------------------
        const float ForestCanopyGroupMinH = 16f;

        static int DeterministicPoolIndex(float x, float y, int poolSize)
        {
            int raw = Mathf.FloorToInt(x * 7f + y * 13f);
            int idx = raw % poolSize;
            if (idx < 0) idx += poolSize;
            return idx;
        }

        static GameObject PickFromPool(List<GameObject> pool, float x, float y) =>
            pool.Count == 0 ? null : pool[DeterministicPoolIndex(x, y, pool.Count)];

        static float AsFloat(object o) => Convert.ToSingle(o, CultureInfo.InvariantCulture);

        static void PlantForest()
        {
            var forestRoot = ReplaceRoot("[GEN] Forest");

            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] PlantForest: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();
            // Idempotency carry-over from the removed PlantTrees: guard against any stale
            // Terrain tree prototypes/instances from an old scene predating that fix.
            // Instances must be cleared BEFORE prototypes (else Unity logs "Tree removed:
            // invalid prototype N" while the now-empty prototype list briefly can't satisfy
            // old instance references). Cheap no-op once already empty.
            terrain.terrainData.SetTreeInstances(new TreeInstance[0], true);
            terrain.terrainData.treePrototypes = new TreePrototype[0];

            string path = Path.Combine(GenDir, "forest_placements.json");
            if (!File.Exists(path))
            {
                Debug.LogError("[DressSlice] PlantForest: missing " + path + " (run 70_sync_unity.py " +
                    "after scripts/75_forest.py).");
                return;
            }
            var root = MiniJson.Parse(File.ReadAllText(path)) as Dictionary<string, object>;
            if (root == null || !root.ContainsKey("chunks"))
            {
                Debug.LogError("[DressSlice] PlantForest: " + path + " missing a top-level 'chunks' array.");
                return;
            }

            var canopyGroupPool = DiscoverByPrefix(SeedMeshJungleRoot, "Background_group_var");
            var canopyTallPool = DiscoverByPrefix(SeedMeshJungleRoot, "Dense_Jungle_Tree_Var");
            var midPool = DiscoverByPrefix(SeedMeshJungleRoot, "Dense_Jungle_Tree_Var")
                .Concat(DiscoverByPrefix(SeedMeshJungleRoot, "Banana_tree_group")).ToList();
            var underPool = DiscoverByPrefix(SeedMeshGroundFoliageRoot, "Forest_bush_var")
                .Concat(DiscoverByPrefix(SeedMeshGroundFoliageRoot, "Common_bush_var"))
                .Concat(DiscoverTropicalPlantsMix()).ToList();
            var groundPool = DiscoverPrefabs(SeedMeshGroundFoliageRoot, name =>
                !name.StartsWith("Forest_bush", StringComparison.OrdinalIgnoreCase) &&
                !name.StartsWith("Common_bush", StringComparison.OrdinalIgnoreCase));
            var wallPool = DiscoverByPrefix(SeedMeshJungleRoot, "Climbing_plants_var")
                .Concat(DiscoverByPrefix(SeedMeshJungleRoot, "Hanging_vegetation_var")).ToList();

            if (canopyGroupPool.Count == 0 && canopyTallPool.Count == 0)
                Debug.LogError("[DressSlice] PlantForest: no canopy prefabs found under " + SeedMeshJungleRoot + ".");
            if (midPool.Count == 0)
                Debug.LogError("[DressSlice] PlantForest: no mid-storey prefabs found under " + SeedMeshJungleRoot + ".");
            if (underPool.Count == 0)
                Debug.LogError("[DressSlice] PlantForest: no understory prefabs found under " +
                    SeedMeshGroundFoliageRoot + " / " + SeedMeshTropicalPlantsRoot + ".");
            if (groundPool.Count == 0)
                Debug.LogError("[DressSlice] PlantForest: no ground-cover prefabs found under " + SeedMeshGroundFoliageRoot + ".");
            if (wallPool.Count == 0)
                Debug.LogError("[DressSlice] PlantForest: no wall/creeper prefabs found under " + SeedMeshJungleRoot + ".");
            Debug.Log("[DressSlice] PlantForest pools: canopyGroup=" + canopyGroupPool.Count + " canopyTall=" +
                canopyTallPool.Count + " mid=" + midPool.Count + " under=" + underPool.Count + " ground=" +
                groundPool.Count + " wall=" + wallPool.Count);

            // Native-height baselines (MeasureHeight, same helper PlantTrees used), measured
            // once per prefab and cached - only canopy/mid scale against h, but pool members
            // can repeat across chunks so the cache still saves real work over 1000+ placements.
            var heightCache = new Dictionary<GameObject, float>();
            float Baseline(GameObject prefab)
            {
                if (!heightCache.TryGetValue(prefab, out float h))
                {
                    h = Mathf.Max(1f, MeasureHeight(prefab));
                    heightCache[prefab] = h;
                }
                return h;
            }

            var perLayer = new Dictionary<string, int> { { "canopy", 0 }, { "mid", 0 }, { "under", 0 }, { "ground", 0 }, { "wall", 0 } };
            int total = 0;

            foreach (var chunkObj in (List<object>)root["chunks"])
            {
                var chunk = (Dictionary<string, object>)chunkObj;
                float s0 = AsFloat(chunk["s0"]);
                string chunkName = "chunk_" + Mathf.RoundToInt(s0);
                var chunkGo = new GameObject(chunkName);
                chunkGo.transform.SetParent(forestRoot.transform, false);

                int chunkCount = 0;
                foreach (var plantObj in (List<object>)chunk["plants"])
                {
                    var p = (Dictionary<string, object>)plantObj;
                    string layer = (string)p["layer"];
                    float x = AsFloat(p["x"]);   // ENU east == Unity x
                    float y = AsFloat(p["y"]);   // ENU north == Unity z (identity mapping, per project convention)
                    float h = AsFloat(p["h"]);
                    float yaw = AsFloat(p["yaw"]);
                    float placementScale = AsFloat(p["scale"]);

                    GameObject prefab;
                    float localScale;
                    bool scaleToHeight;

                    switch (layer)
                    {
                        case "canopy":
                        {
                            bool useGroup = h >= ForestCanopyGroupMinH && canopyGroupPool.Count > 0;
                            var pool = useGroup ? canopyGroupPool : (canopyTallPool.Count > 0 ? canopyTallPool : canopyGroupPool);
                            prefab = PickFromPool(pool, x, y);
                            scaleToHeight = true;
                            break;
                        }
                        case "mid":
                            prefab = PickFromPool(midPool, x, y);
                            scaleToHeight = true;
                            break;
                        case "under":
                            prefab = PickFromPool(underPool, x, y);
                            scaleToHeight = false;
                            break;
                        case "ground":
                            prefab = PickFromPool(groundPool, x, y);
                            scaleToHeight = false;
                            break;
                        case "wall":
                            prefab = PickFromPool(wallPool, x, y);
                            scaleToHeight = false;
                            break;
                        default:
                            Debug.LogWarning("[DressSlice] PlantForest: unknown layer '" + layer + "' in " + chunkName + "; skipped.");
                            continue;
                    }
                    if (prefab == null) continue; // pool empty (already logged above)

                    localScale = scaleToHeight ? Mathf.Clamp(h / Baseline(prefab), 0.05f, 10f) : placementScale;
                    float worldY = WorldTerrainHeight(terrain, x, y);

                    var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                    inst.name = prefab.name + "_" + layer + "_" + total;
                    inst.transform.SetParent(chunkGo.transform, false);
                    inst.transform.position = new Vector3(x, worldY, y);
                    inst.transform.rotation = Quaternion.Euler(0f, yaw, 0f);
                    inst.transform.localScale = scaleToHeight
                        ? Vector3.one * localScale
                        : prefab.transform.localScale * localScale; // native scale x placement.scale
                    MarkStaticRecursive(inst.transform);

                    perLayer[layer]++;
                    chunkCount++;
                    total++;
                }
                Debug.Log("[DressSlice] PlantForest: " + chunkName + " -> " + chunkCount + " instance(s).");
            }

            Debug.Log("[DressSlice] PlantForest: TOTAL=" + total + " canopy=" + perLayer["canopy"] +
                " mid=" + perLayer["mid"] + " under=" + perLayer["under"] + " ground=" + perLayer["ground"] +
                " wall=" + perLayer["wall"]);
        }

        // -------------------------------------------------------------------
        // 5. Foliage card quads (foliage_cards placements with h <= 5 m).
        // -------------------------------------------------------------------
        static void PlaceCards()
        {
            var cardsRoot = ReplaceChild(GetSliceRoot(), "Cards");
            if (!CARDS_ENABLED)
            {
                Debug.Log("[DressSlice] Cards disabled (mesh-as-base baseline)");
                return;
            }

            // CARDS_ENABLED is a const false for this baseline, which makes everything
            // below statically unreachable (CS0162). Silenced deliberately - this path is
            // kept intact, not dead, for a future re-enable.
#pragma warning disable CS0162
            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] PlaceCards: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();

            var placements = LoadPlacements();
            if (placements == null || placements.cards == null)
            {
                Debug.LogWarning("[DressSlice] PlaceCards: foliage_cards/placements.json missing.");
                return;
            }

            var shader = Shader.Find("Universal Render Pipeline/Lit");
            var matCache = new Dictionary<string, Material>();
            int n = 0;
            foreach (var c in placements.cards)
            {
                if (c.h > 5f) continue; // tall placements are PlantForest's job now

                if (!matCache.TryGetValue(c.img, out var mat))
                {
                    string imgPath = GenDir + "/foliage_cards/" + c.img;
                    var tex = AssetDatabase.LoadAssetAtPath<Texture2D>(imgPath);
                    var m = new Material(shader) { name = "Card_" + Path.GetFileNameWithoutExtension(c.img) };
                    if (tex != null) { m.SetTexture("_BaseMap", tex); m.mainTexture = tex; }
                    else Debug.LogWarning("[DressSlice] PlaceCards: card texture not found at " + imgPath);
                    // Review round 3: alpha CLIP (hard cutoff at _Cutoff) was cutting the
                    // card PNGs' feathered edge into a hard-edged circle. Switch to alpha
                    // BLENDING so the soft feather actually fades: Transparent surface,
                    // standard SrcAlpha/OneMinusSrcAlpha blend, no depth write, Transparent
                    // queue. Cull stays off (two-sided).
                    m.SetFloat("_Surface", 1f); // Transparent
                    m.SetFloat("_Blend", 0f);   // Alpha
                    m.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
                    m.SetFloat("_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
                    m.SetFloat("_ZWrite", 0f);
                    m.SetFloat("_AlphaClip", 0f);
                    m.DisableKeyword("_ALPHATEST_ON");
                    m.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
                    m.SetOverrideTag("RenderType", "Transparent");
                    m.SetFloat("_Cull", (float)UnityEngine.Rendering.CullMode.Off); // two-sided
                    m.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;

                    string matPath = "Assets/Amakeng/CardMat_" + Path.GetFileNameWithoutExtension(c.img) + ".mat";
                    AssetDatabase.DeleteAsset(matPath);
                    AssetDatabase.CreateAsset(m, matPath);
                    mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    matCache[c.img] = mat;
                }

                float worldY = WorldTerrainHeight(terrain, c.x, c.y);
                var go = new GameObject("Card_" + n);
                go.transform.SetParent(cardsRoot.transform, false);
                go.transform.position = new Vector3(c.x, worldY + c.h * 0.5f, c.y);
                go.transform.rotation = Quaternion.Euler(0f, c.yaw_deg, 0f);
                go.AddComponent<MeshFilter>().sharedMesh = MakeQuadMesh(c.h, c.h);
                go.AddComponent<MeshRenderer>().sharedMaterial = mat;
                n++;
            }
            Debug.Log("[DressSlice] PlaceCards: " + n + " foliage card quad(s) placed under [GEN] Slice/Cards.");
#pragma warning restore CS0162
        }

        static Mesh MakeQuadMesh(float width, float height)
        {
            float hw = width * 0.5f, hh = height * 0.5f;
            var m = new Mesh { name = "CardQuad" };
            m.SetVertices(new List<Vector3>
            {
                new Vector3(-hw, -hh, 0f), new Vector3(hw, -hh, 0f),
                new Vector3(hw, hh, 0f), new Vector3(-hw, hh, 0f),
            });
            m.SetUVs(0, new List<Vector2> { new Vector2(0, 0), new Vector2(1, 0), new Vector2(1, 1), new Vector2(0, 1) });
            m.SetTriangles(new[] { 0, 1, 2, 0, 2, 3 }, 0);
            m.RecalculateNormals();
            m.RecalculateBounds();
            return m;
        }

        // -------------------------------------------------------------------
        // 6. Backdrop mountain tiles.
        // -------------------------------------------------------------------
        static void ImportBackdrop()
        {
            var backdropRoot = ReplaceChild(GetSliceRoot(), "Backdrop");

            // mesh-as-base baseline: the corridor clip (CLIP_M=7.5) leaves torn canopy
            // edges much closer to the camera than before, exposing backfaces through the
            // gaps. Clone each tile's material(s) with culling disabled so both sides
            // render; this only ensures GeneratedMaterialsDir exists (not wipe-and-recreate
            // the whole folder) and deletes/recreates its own per-tile files individually -
            // PlantForest places native SeedMesh prefabs and never writes into this folder,
            // but the shared-folder-not-wipe discipline is kept regardless.
            const string matDir = GeneratedMaterialsDir;
            EnsureFolder(matDir);

            var guids = AssetDatabase.FindAssets("t:Model", new[] { GenDir + "/backdrop" });
            int n = 0;
            foreach (var guid in guids)
            {
                var assetPath = AssetDatabase.GUIDToAssetPath(guid);
                if (!assetPath.EndsWith(".obj", StringComparison.OrdinalIgnoreCase)) continue;
                var model = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                if (model == null) continue;

                var inst = (GameObject)PrefabUtility.InstantiatePrefab(model);
                inst.name = Path.GetFileNameWithoutExtension(assetPath);
                inst.transform.SetParent(backdropRoot.transform, false);
                foreach (var mf in inst.GetComponentsInChildren<MeshFilter>())
                {
                    var mc = mf.gameObject.AddComponent<MeshCollider>();
                    mc.sharedMesh = mf.sharedMesh;
                }

                var hdLitShader = Shader.Find("HDRP/Lit");
                foreach (var mr in inst.GetComponentsInChildren<MeshRenderer>())
                {
                    var mats = mr.sharedMaterials;
                    for (int i = 0; i < mats.Length; i++)
                    {
                        var src = mats[i];
                        if (src == null) continue;
                        // Retarget onto HDRP/Lit explicitly (rather than cloning whatever
                        // shader the .obj's auto-generated default material happened to carry
                        // from import time) and mark double-sided the HDRP way: the
                        // _DoubleSidedEnable toggle plus doubleSidedGI, then
                        // ResetMaterialKeywords to sync the actual _CullMode the shader passes
                        // key off (same pattern as MakeShadowMatteUnlit above).
                        var clone = new Material(src) { name = src.name + "_DoubleSided", shader = hdLitShader };
                        clone.SetFloat("_DoubleSidedEnable", 1f);
                        clone.doubleSidedGI = true;
                        UnityEditor.Rendering.HighDefinition.HDShaderUtils.ResetMaterialKeywords(clone);
                        string matPath = matDir + "/" + inst.name + "_" + mr.gameObject.name + "_" + i + ".mat";
                        AssetDatabase.DeleteAsset(matPath);
                        AssetDatabase.CreateAsset(clone, matPath);
                        mats[i] = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    }
                    mr.sharedMaterials = mats;
                }
                n++;
            }
            Debug.Log("[DressSlice] ImportBackdrop: " + n + " backdrop tile(s) imported under [GEN] Slice/Backdrop.");
        }

        // -------------------------------------------------------------------
        // 7. Barrier (slice_extras.json: station + lateral offset).
        // -------------------------------------------------------------------
        static List<Vector3> ParseStations(string json)
        {
            var outp = new List<Vector3>();
            int i = json.IndexOf("\"stations_unity\"", StringComparison.Ordinal);
            if (i < 0) return outp;
            i = json.IndexOf('[', i) + 1;
            while (true)
            {
                int a = json.IndexOf('[', i);
                if (a < 0) break;
                int b = json.IndexOf(']', a);
                var parts = json.Substring(a + 1, b - a - 1).Split(',');
                outp.Add(new Vector3(Pf(parts[0]), Pf(parts[1]), Pf(parts[2])));
                i = b + 1;
                if (i >= json.Length || json[i] == ']') break;
            }
            return outp;
        }

        static bool TryStationPose(List<Vector3> stations, float s, out Vector3 pos, out Vector3 tangent)
        {
            pos = Vector3.zero;
            tangent = Vector3.forward;
            if (stations.Count < 2) return false;
            float acc = 0f;
            for (int i = 0; i < stations.Count - 1; i++)
            {
                Vector3 a = stations[i], b = stations[i + 1];
                Vector3 a2 = new Vector3(a.x, 0f, a.z), b2 = new Vector3(b.x, 0f, b.z);
                float seg = Vector3.Distance(a2, b2);
                if (s <= acc + seg || i == stations.Count - 2)
                {
                    float t = seg > 1e-5f ? Mathf.Clamp01((s - acc) / seg) : 0f;
                    pos = Vector3.Lerp(a, b, t);
                    tangent = (b2 - a2);
                    tangent = tangent.sqrMagnitude > 1e-8f ? tangent.normalized : Vector3.forward;
                    return true;
                }
                acc += seg;
            }
            return false;
        }

        static void PlaceBarrier()
        {
            var barrierRoot = ReplaceChild(GetSliceRoot(), "Barrier");

            string extrasPath = Path.Combine(GenDir, "slice_extras.json");
            string roadMetaPath = Path.Combine(GenDir, "road_meta.json");
            if (!File.Exists(extrasPath) || !File.Exists(roadMetaPath))
            {
                Debug.LogError("[DressSlice] PlaceBarrier: missing slice_extras.json or road_meta.json.");
                return;
            }
            var extras = JsonUtility.FromJson<SliceExtras>(File.ReadAllText(extrasPath));
            if (extras == null || extras.barrier == null)
            {
                Debug.LogWarning("[DressSlice] PlaceBarrier: no barrier entry in slice_extras.json.");
                return;
            }

            var stations = ParseStations(File.ReadAllText(roadMetaPath));
            if (!TryStationPose(stations, extras.barrier.s, out Vector3 centre, out Vector3 tangent))
            {
                Debug.LogError("[DressSlice] PlaceBarrier: could not resolve station s=" + extras.barrier.s);
                return;
            }
            // "Left" of the direction of travel, in the horizontal (x,z) plane: rotating the
            // tangent 90 deg counter-clockwise as seen from above (Unity x=East, z=North).
            // Derivation (review round 2, item 3 - rechecked from the ENU convention and
            // verified two independent ways, see the console cross-check logged below):
            // ENU is right-handed (x=East, y=North, z=Up); for a person facing ENU tangent
            // (tx,ty)=(0,1) (due north), their LEFT hand points west = (-1,0) - a physical/
            // geographic fact, not a convention choice. Rotating (tx,ty) by +90 deg CCW
            // (standard math rotation, (x,y)->(-y,x)) gives (-ty,tx); at (0,1) that's (-1,0)
            // = west, matching. So ENU left = (-ty, tx). road_meta.json's stations_unity use
            // the documented identity ENU->Unity axis mapping (unity_x=enu_x, unity_z=enu_y,
            // no sign flip - confirmed exactly: station 0 in road_meta.json, (0.179,1.079),
            // equals centerline.json's s=0 ENU (x,y) verbatim), so the same (-ty,tx) rotation
            // applies directly to the Unity-space tangent's (x,z) components: left =
            // (-tangent.z, 0, tangent.x). Independently confirmed against Unity's own
            // Quaternion.LookRotation(tangent, up) "left" (-transform.right): both give
            // (0,0,1) for forward=+x and (-1,0,0) for forward=+z.
            var left = new Vector3(-tangent.z, 0f, tangent.x).normalized;
            var xz = centre + left * extras.barrier.lat;

            // Independent numeric proof: recompute the expected Unity (x,z) directly from
            // the ENU ground-truth centreline (work/centerline.json, synced to
            // Generated/centerline.json), which carries an explicit per-station tangent
            // (tx,ty) rather than one derived by finite-differencing road_meta.json's
            // coarser ~5 m station spacing. Must land within 2 m (per review round 2).
            string centerlinePath = Path.Combine(GenDir, "centerline.json");
            if (File.Exists(centerlinePath))
            {
                var cl = JsonUtility.FromJson<CenterlineRoot>(File.ReadAllText(centerlinePath));
                if (cl != null && cl.stations != null && cl.stations.Length > 0)
                {
                    CenterlineStation nearest = cl.stations[0];
                    float bestDs = Mathf.Abs(nearest.s - extras.barrier.s);
                    foreach (var st in cl.stations)
                    {
                        float ds = Mathf.Abs(st.s - extras.barrier.s);
                        if (ds < bestDs) { bestDs = ds; nearest = st; }
                    }
                    // ENU left = (-ty, tx); ENU->Unity horizontal is the identity axis mapping.
                    float expectedX = nearest.x + extras.barrier.lat * (-nearest.ty);
                    float expectedZ = nearest.y + extras.barrier.lat * nearest.tx;
                    float mismatch = Vector2.Distance(new Vector2(xz.x, xz.z), new Vector2(expectedX, expectedZ));
                    Debug.Log("[DressSlice] PlaceBarrier ENU check: road_meta-derived unity(x,z)=(" +
                        xz.x.ToString("F3") + "," + xz.z.ToString("F3") + ")  ENU-ground-truth unity(x,z)=(" +
                        expectedX.ToString("F3") + "," + expectedZ.ToString("F3") + ")  mismatch=" +
                        mismatch.ToString("F3") + " m (tolerance 2 m, nearest centreline station s=" +
                        nearest.s.ToString("F1") + ")");
                    if (mismatch > 2f)
                        Debug.LogError("[DressSlice] PlaceBarrier: ENU ground-truth check FAILED - mismatch " +
                            mismatch.ToString("F3") + " m exceeds 2 m tolerance.");
                }
            }
            else
            {
                Debug.LogWarning("[DressSlice] PlaceBarrier: centerline.json not found (run 70_sync_unity.py); " +
                    "skipping ENU ground-truth check.");
            }

            var terrGo = GameObject.Find("[GEN] Terrain");
            float y = xz.y;
            if (terrGo != null)
                y = WorldTerrainHeight(terrGo.GetComponent<Terrain>(), xz.x, xz.z);

            float lenM = extras.barrier.len_m > 0f ? extras.barrier.len_m : 4f;
            var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = "Barrier";
            go.transform.SetParent(barrierRoot.transform, false);
            go.transform.position = new Vector3(xz.x, y + 0.5f, xz.z);
            go.transform.rotation = Quaternion.LookRotation(tangent, Vector3.up);
            // 1 m high, len_m long (along the direction of travel), 0.3 m thick.
            go.transform.localScale = new Vector3(0.3f, 1f, lenM);

            var shader = Shader.Find("HDRP/Lit");
            string stripePath = "Assets/Amakeng/Generated/barrier_stripe.png";
            var stripeTex = AssetDatabase.LoadAssetAtPath<Texture2D>(stripePath);
            string matPath = "Assets/Amakeng/BarrierMat.mat";
            AssetDatabase.DeleteAsset(matPath);
            var mat = new Material(shader) { name = "BarrierMat" };
            // HDRP/Lit's base-color texture property is _BaseColorMap (URP/Lit's is _BaseMap);
            // mainTexture/color still work as aliases (both tagged [MainTexture]/[MainColor]),
            // set explicitly here too for clarity.
            if (stripeTex != null) { mat.SetTexture("_BaseColorMap", stripeTex); mat.mainTexture = stripeTex; }
            else mat.color = new Color(0.85f, 0.1f, 0.1f); // red tint fallback (no barrier_stripe.png present)
            AssetDatabase.CreateAsset(mat, matPath);
            go.GetComponent<MeshRenderer>().sharedMaterial = AssetDatabase.LoadAssetAtPath<Material>(matPath);

            Debug.Log("[DressSlice] PlaceBarrier: placed at s=" + extras.barrier.s + " lat=" + extras.barrier.lat +
                " world=" + go.transform.position);
        }

        // -------------------------------------------------------------------
        // 8. Sun position (NOAA solar position formulas) + fog.
        // -------------------------------------------------------------------
        static void SetAtmosphere()
        {
            const double lat = 1.407, lon = 103.716, tzHours = 8.0; // 1.407 N, 103.716 E, SGT = UTC+8
            var local = new DateTime(2026, 7, 24, 15, 24, 0);
            int doy = local.DayOfYear;
            double hourDecimal = local.Hour + local.Minute / 60.0 + local.Second / 3600.0;

            double gamma = 2.0 * Math.PI / 365.0 * (doy - 1 + (hourDecimal - 12.0) / 24.0);
            double eqtime = 229.18 * (0.000075 + 0.001868 * Math.Cos(gamma) - 0.032077 * Math.Sin(gamma)
                - 0.014615 * Math.Cos(2 * gamma) - 0.040849 * Math.Sin(2 * gamma)); // minutes
            double decl = 0.006918 - 0.399912 * Math.Cos(gamma) + 0.070257 * Math.Sin(gamma)
                - 0.006758 * Math.Cos(2 * gamma) + 0.000907 * Math.Sin(2 * gamma)
                - 0.002697 * Math.Cos(3 * gamma) + 0.00148 * Math.Sin(3 * gamma); // radians

            double timeOffset = eqtime + 4.0 * lon - 60.0 * tzHours; // minutes
            double tst = hourDecimal * 60.0 + timeOffset;            // true solar time, minutes
            double haDeg = (tst / 4.0) - 180.0;
            double haRad = haDeg * Math.PI / 180.0;
            double latRad = lat * Math.PI / 180.0;

            double cosZenith = Math.Sin(latRad) * Math.Sin(decl) + Math.Cos(latRad) * Math.Cos(decl) * Math.Cos(haRad);
            cosZenith = Math.Max(-1.0, Math.Min(1.0, cosZenith));
            double zenith = Math.Acos(cosZenith);
            double elevation = Math.PI / 2.0 - zenith;

            double cosAz = (Math.Sin(latRad) * Math.Cos(zenith) - Math.Sin(decl)) / (Math.Cos(latRad) * Math.Sin(zenith));
            cosAz = Math.Max(-1.0, Math.Min(1.0, cosAz));
            double azimuthDeg = haDeg > 0
                ? (Math.Acos(cosAz) * 180.0 / Math.PI + 180.0) % 360.0
                : (540.0 - Math.Acos(cosAz) * 180.0 / Math.PI) % 360.0;

            float elevDeg = (float)(elevation * 180.0 / Math.PI);
            float azDeg = (float)azimuthDeg;

            // Compass azimuth (0=N,90=E,...) + elevation -> Unity direction (x=East,y=Up,z=North).
            var sunDir = new Vector3(
                Mathf.Sin(azDeg * Mathf.Deg2Rad) * Mathf.Cos(elevDeg * Mathf.Deg2Rad),
                Mathf.Sin(elevDeg * Mathf.Deg2Rad),
                Mathf.Cos(azDeg * Mathf.Deg2Rad) * Mathf.Cos(elevDeg * Mathf.Deg2Rad));

            var sunGo = GameObject.Find("Directional Light");
            if (sunGo == null)
            {
                sunGo = new GameObject("Directional Light");
                sunGo.AddComponent<Light>();
            }
            var light = sunGo.GetComponent<Light>();
            if (light == null) light = sunGo.AddComponent<Light>();
            light.type = LightType.Directional;

            var upHint = Mathf.Abs(sunDir.y) > 0.999f ? Vector3.forward : Vector3.up;
            sunGo.transform.rotation = Quaternion.LookRotation(-sunDir, upHint);
            // HDRP migration (Task 1): SetAtmosphere runs on every Dress(), including runs
            // after SetupHdrp.Run() - so it must not stomp SetupHdrp.EnsureSunForHdrp()'s
            // physically-plausible Lux intensity with the old URP-era flat multiplier (1.1),
            // which under HDRP's physical light units is close to no light at all (confirmed
            // live: post-Dress() the sun read back at 1.1 lux). Re-applies the same
            // HDAdditionalLightData/Lux setup here so SetAtmosphere alone (without a prior
            // SetupHdrp.Run() in the same session) is still correct, and the two stay in sync
            // by referencing SetupHdrp's own constant rather than duplicating the number.
            if (sunGo.GetComponent<UnityEngine.Rendering.HighDefinition.HDAdditionalLightData>() == null)
                sunGo.AddComponent<UnityEngine.Rendering.HighDefinition.HDAdditionalLightData>();
            light.lightUnit = UnityEngine.Rendering.LightUnit.Lux;
            light.intensity = SetupHdrp.SunIntensityLux;
            light.color = new Color(1f, 0.97f, 0.92f);
            RenderSettings.sun = light; // legacy "which light is the sun" pointer, not a fog/sky write - harmless under HDRP.

            // HDRP migration (Task 1 follow-up, this task): atmosphere - sky, fog, exposure -
            // is owned exclusively by SetupHdrp.BuildAtmosphereVolume()'s "[GEN] Atmosphere"
            // Volume (PhysicallyBasedSky + Fog(meanFreePath=250) + fixed Exposure). The old
            // URP-era RenderSettings.fog/fogMode/fogDensity/fogColor writes that used to live
            // here were built-in-render-pipeline fog settings HDRP's own Fog volume component
            // does not read - keeping them around risks looking like a second, conflicting
            // "source of truth" for fog even though they're currently inert, so they're
            // removed. SetAtmosphere's only remaining job is the sun: NOAA position (rotation)
            // plus keeping its HDRP Lux intensity in sync (needed so this method alone, without
            // a prior SetupHdrp.Run() in the same session, still leaves the sun correctly lit -
            // see task-1-report.md section 0 for the bug this fixed: SetAtmosphere used to stomp the
            // sun back down to a flat 1.1 "intensity", which under HDRP's physical Lux units is
            // close to no light at all).
            Debug.Log("[DressSlice] SetAtmosphere: sun elevation=" + elevDeg.ToString("F1") +
                " deg, azimuth=" + azDeg.ToString("F1") + " deg (compass), intensity=" +
                light.intensity + " lux (fog/sky owned by SetupHdrp's Atmosphere volume - not written here).");
        }
    }
}
