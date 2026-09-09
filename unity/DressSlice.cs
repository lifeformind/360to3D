// Dresses the vertical-slice scene: road overlay, verge grass/fern detail, trees, foliage
// cards, backdrop mountains, barrier, sun + fog. Menu: Amakeng > Dress Slice.
// Idempotent: every step deletes/replaces its own [GEN] Slice child (or TerrainData layer)
// before rebuilding, so re-running Dress() after re-syncing exports is always safe.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
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

    public static class DressSlice
    {
        const string GenDir = "Assets/Amakeng/Generated";
        const string TerrainPackRoot = "Assets/TerrainSampleAssets";
        // SeedMesh tropical packs use Shader Graph materials (Shader Graphs/SeedMesh_* and
        // Shader Graphs/Basic_vegetation) - but every one of those .shadergraph assets'
        // Graph Settings has its Active Target set to HDTarget (HDRP) only, with no
        // UniversalTarget (confirmed by grepping "m_ActiveTargets"/"m_Type" in each
        // .shadergraph file). Under this project's URP pipeline that makes every material
        // using them render as Unity's flat magenta "shader not supported by this render
        // pipeline" placeholder - verified visually via isolated single-prefab
        // RenderTexture captures (reproduced with post-processing disabled and with
        // ShaderUtil.allowAsyncCompilation forced off, ruling out an async-compile
        // placeholder), even though ShaderUtil reports 0 compile messages and
        // shader.isSupported == true (it compiles fine, just for the wrong pipeline).
        // FixSeedMeshMaterialsForUrp() below repoints affected materials to a stock
        // "Universal Render Pipeline/Lit" shader, carrying over each material's own
        // base-color/normal textures and alpha-clip/double-sided settings - no tinting,
        // same source pack textures, just wired into a shader URP can actually render.
        const string SeedMeshJungleRoot = "Assets/SeedMesh/Jungle-Tropical Vegetation/Vegetation";
        const string SeedMeshTropicalPlantsRoot = "Assets/SeedMesh/Tropical Plants Package/Prefabs";
        const string SeedMeshGroundFoliageRoot = "Assets/SeedMesh/Ground Foliage Vol.2/Prefabs";

        // Every Shader Graph shipped in the SeedMesh packs we use, all HDRP-targeted only
        // (see comment above). Any material found under Assets/SeedMesh using one of these
        // shaders gets repointed to Universal Render Pipeline/Lit by
        // FixSeedMeshMaterialsForUrp().
        static readonly string[] SeedMeshHdrpShaderNames =
        {
            "Shader Graphs/SeedMesh_Foliage",
            "Shader Graphs/Basic_vegetation",
            "Shader Graphs/SeedMesh_Tree_Bark",
            "Shader Graphs/SeedMesh_Tree_Bark_Layered",
            "Shader Graphs/SeedMesh_Static_Objects",
            "Shader Graphs/Vegetation",
            "Shader Graphs/Cactus",
            "Shader Graphs/Moss",
            "Shader Graphs/Sea_water",
        };

        // One-time, idempotent repair: swaps every HDRP-targeted SeedMesh material (see
        // SeedMeshHdrpShaderNames) onto Universal Render Pipeline/Lit, copying over its own
        // base-color (_MainTex) and normal (Normal_vegetation) textures plus its
        // alpha-clip/double-sided flags. Changes are persisted to the .mat assets, so this
        // is safe (and cheap - a no-op scan) to call on every Dress() run.
        static void FixSeedMeshMaterialsForUrp()
        {
            var urpLit = Shader.Find("Universal Render Pipeline/Lit");
            if (urpLit == null)
            {
                Debug.LogError("[DressSlice] FixSeedMeshMaterialsForUrp: Universal Render Pipeline/Lit shader not found.");
                return;
            }

            var guids = AssetDatabase.FindAssets("t:Material", new[] { "Assets/SeedMesh" });
            int fixedCount = 0;
            foreach (var guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
                if (mat == null || mat.shader == null) continue;
                if (!SeedMeshHdrpShaderNames.Contains(mat.shader.name)) continue;

                var baseTex = mat.HasProperty("_MainTex") ? mat.GetTexture("_MainTex") : null;
                var normalTex = mat.HasProperty("Normal_vegetation") ? mat.GetTexture("Normal_vegetation") : null;
                Color tint = mat.HasProperty("_Color") ? mat.GetColor("_Color") : Color.white;
                float cutoff = mat.HasProperty("_cutoff") ? mat.GetFloat("_cutoff") : 0.33f;
                bool alphaClip = mat.HasProperty("_AlphaCutoffEnable") ? mat.GetFloat("_AlphaCutoffEnable") > 0.5f : true;
                bool doubleSided = mat.HasProperty("_DoubleSidedEnable") ? mat.GetFloat("_DoubleSidedEnable") > 0.5f : true;

                mat.shader = urpLit;
                mat.shaderKeywords = Array.Empty<string>();
                mat.SetFloat("_WorkflowMode", 1f); // Metallic
                mat.SetFloat("_Surface", 0f);      // Opaque (cutout, not alpha-blended)
                mat.SetFloat("_Smoothness", 0.08f);
                mat.SetFloat("_Metallic", 0f);
                if (baseTex != null) mat.SetTexture("_BaseMap", baseTex);
                mat.SetColor("_BaseColor", tint);
                if (normalTex != null)
                {
                    mat.SetTexture("_BumpMap", normalTex);
                    mat.EnableKeyword("_NORMALMAP");
                    mat.SetFloat("_BumpScale", 1f);
                }
                mat.SetFloat("_AlphaClip", alphaClip ? 1f : 0f);
                if (alphaClip)
                {
                    mat.SetFloat("_Cutoff", cutoff);
                    mat.EnableKeyword("_ALPHATEST_ON");
                    mat.renderQueue = (int)UnityEngine.Rendering.RenderQueue.AlphaTest;
                }
                mat.SetFloat("_Cull", (float)(doubleSided
                    ? UnityEngine.Rendering.CullMode.Off : UnityEngine.Rendering.CullMode.Back));
                mat.doubleSidedGI = doubleSided;
                EditorUtility.SetDirty(mat);
                fixedCount++;
            }
            if (fixedCount > 0) AssetDatabase.SaveAssets();
            Debug.Log("[DressSlice] FixSeedMeshMaterialsForUrp: repointed " + fixedCount +
                " HDRP-targeted SeedMesh material(s) to Universal Render Pipeline/Lit.");
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
            // TreePackVol.1 URP material conversion recipe before it was wired into
            // PlantTrees (that recipe is no longer used - see PlantTrees' header comment).
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

            ConvertPackMaterials();
            FixSeedMeshMaterialsForUrp();
            BuildOverlay();
            PaintDetails();
            FixGroundMaterial();
            PlantTrees();
            ScatterUnderstory();
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
        // 1. URP material conversion for imported packs.
        // -------------------------------------------------------------------
        static void ConvertPackMaterials()
        {
            try
            {
                UnityEditor.Rendering.Universal.Converters.RunInBatchMode(
                    UnityEditor.Rendering.Universal.ConverterContainerId.BuiltInToURP);
                Debug.Log("[DressSlice] ConvertPackMaterials: Built-in -> URP converter ran in batch mode.");
            }
            catch (Exception e)
            {
                Debug.LogWarning("[DressSlice] ConvertPackMaterials: URP converter unavailable or failed (" +
                    e.Message + "). Convert pack materials manually via Window > Rendering > Render Pipeline Converter.");
            }
            // Note: earlier rounds logged a "TreePackVol.1 trees may appear magenta" warning
            // here. As of review round 2, PlantTrees no longer places any TreePackVol.1 Tree
            // Creator prefab (it prefers TerrainSampleAssets bushes and only falls back to
            // non-Tree-Creator-shader TreePackVol.1 prefabs, of which there are none in this
            // pack), so that warning is stale and has been removed.
        }

        // -------------------------------------------------------------------
        // 2. Road overlay mesh (per-tile albedo).
        // -------------------------------------------------------------------
        class ObjGroup { public string Name; public List<int> Faces = new List<int>(); }

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

            var shader = Shader.Find("Universal Render Pipeline/Lit");
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
                var mat = new Material(shader) { name = "OverlayTile" + tileNum };
                mat.SetFloat("_Smoothness", 0.1f);
                if (tex != null) { mat.SetTexture("_BaseMap", tex); mat.mainTexture = tex; }
                else Debug.LogWarning("[DressSlice] BuildOverlay: albedo texture not found at " + texPath);
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
        // 4. Trees (foliage_cards placements): SeedMesh tropical packs, all Shader Graph/
        // URP-native - no material conversion needed (that whole machinery, built for the
        // Tree Creator-shader TreePackVol.1, is gone along with the pack - see Dress()'s
        // cleanup step and item 3 of the fix report).
        //   h_raw >  6 m: Dense_Jungle_Tree_Var* (single trees); h_raw >= 12 m prefers
        //     Background_group_var* (multi-tree clusters - reads as a treeline clump
        //     rather than one implausibly stretched single tree at that height).
        //   h_raw <= 6 m: Forest_bush_var*/Common_bush_var* + a mix of Tropical Plants
        //     prefabs (no tint needed - SeedMesh materials are already correct).
        // All instances placed as ordinary instantiated GameObjects under
        // [GEN] Slice/Trees (not Unity's built-in Terrain tree prototypes/instances -
        // see the round-2 fix report for why that path doesn't work here).
        // -------------------------------------------------------------------
        const float BackgroundGroupMinHRaw = 12f;

        static void PlantTrees()
        {
            var treesRoot = ReplaceChild(GetSliceRoot(), "Trees");

            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] PlantTrees: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();
            // Idempotency: clear any Terrain tree prototypes/instances left over from
            // before the round-2 fix (PlantTrees no longer populates terrainData.
            // treePrototypes / SetTreeInstances). Instances must be cleared BEFORE
            // prototypes, or Unity logs "Tree removed: invalid prototype N" while the
            // (now-empty) prototype list briefly can't satisfy old instances' references.
            terrain.terrainData.SetTreeInstances(new TreeInstance[0], true);
            terrain.terrainData.treePrototypes = new TreePrototype[0];

            var singleTrees = DiscoverByPrefix(SeedMeshJungleRoot, "Dense_Jungle_Tree_Var");
            var groupTrees = DiscoverByPrefix(SeedMeshJungleRoot, "Background_group_var");
            var lowPool = DiscoverByPrefix(SeedMeshGroundFoliageRoot, "Forest_bush_var")
                .Concat(DiscoverByPrefix(SeedMeshGroundFoliageRoot, "Common_bush_var"))
                .Concat(DiscoverTropicalPlantsMix()).ToList();

            if (singleTrees.Count == 0 && groupTrees.Count == 0)
                Debug.LogError("[DressSlice] PlantTrees: no jungle tree/group prefabs found under " +
                    SeedMeshJungleRoot + ".");
            if (lowPool.Count == 0)
                Debug.LogError("[DressSlice] PlantTrees: no bush/tropical-plant prefabs found under " +
                    SeedMeshGroundFoliageRoot + " / " + SeedMeshTropicalPlantsRoot + ".");
            Debug.Log("[DressSlice] PlantTrees: single trees=" + singleTrees.Count + ", group trees=" +
                groupTrees.Count + ", low-canopy pool=" + lowPool.Count + " (bush + tropical mix)");

            var placements = LoadPlacements();
            if (placements == null || placements.cards == null)
            {
                Debug.LogWarning("[DressSlice] PlantTrees: foliage_cards/placements.json missing; no trees placed.");
                return;
            }

            int nSingle = 0, nGroup = 0, nLow = 0;
            for (int i = 0; i < placements.cards.Length; i++)
            {
                var c = placements.cards[i];
                float worldY = WorldTerrainHeight(terrain, c.x, c.y);
                // Deterministic per placement (not per iteration order): variant pick, yaw,
                // and scale jitter are all seeded by the placement's own index.
                var rng = new System.Random(20260908 + i);

                if (c.h_raw > 6f)
                {
                    bool useGroup = c.h_raw >= BackgroundGroupMinHRaw && groupTrees.Count > 0;
                    var pool = useGroup ? groupTrees : (singleTrees.Count > 0 ? singleTrees : groupTrees);
                    if (pool.Count == 0) continue;
                    var prefab = pool[rng.Next(pool.Count)];
                    float baseline = Mathf.Max(1f, MeasureHeight(prefab));
                    float scale = Mathf.Clamp(c.h_raw / baseline, 0.02f, 10f);
                    float yaw = (float)(rng.NextDouble() * 360.0);

                    var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                    inst.name = prefab.name + "_" + i;
                    inst.transform.SetParent(treesRoot.transform, false);
                    inst.transform.position = new Vector3(c.x, worldY, c.y);
                    inst.transform.rotation = Quaternion.Euler(0f, yaw, 0f);
                    inst.transform.localScale = Vector3.one * scale;
                    if (useGroup) nGroup++; else nSingle++;
                }
                else
                {
                    if (lowPool.Count == 0) continue;
                    var prefab = lowPool[rng.Next(lowPool.Count)];
                    float baseline = Mathf.Max(0.2f, MeasureHeight(prefab));
                    float jitter = 0.9f + (float)rng.NextDouble() * 0.2f;
                    float scale = Mathf.Clamp(c.h / baseline, 0.05f, 6f) * jitter;

                    var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                    inst.name = prefab.name + "_" + i;
                    inst.transform.SetParent(treesRoot.transform, false);
                    inst.transform.position = new Vector3(c.x, worldY, c.y);
                    inst.transform.rotation = Quaternion.Euler(0f, c.yaw_deg, 0f);
                    inst.transform.localScale = Vector3.one * scale;
                    nLow++;
                }
            }
            Debug.Log("[DressSlice] PlantTrees: " + nSingle + " single tree(s), " + nGroup +
                " tree-group cluster(s), " + nLow + " low-canopy (bush/tropical) instance(s).");
        }

        // -------------------------------------------------------------------
        // 4b. Understory scatter (SeedMesh rework): a dense band of small ground-cover /
        // understory plants along both verges of the SLICE centreline, independent of the
        // foliage_cards placements above (which are sparser and driven by canopy-height
        // raster sampling, not a dense walk). Fixes "still sparse" between PlantTrees'
        // relatively few large-canopy instances.
        // -------------------------------------------------------------------
        const float UnderstorySRangeLo = 439f, UnderstorySRangeHi = 664f; // matches the slice's own station range
        const float UnderstoryStationStep = 1.5f;
        const float UnderstoryLatMin = 4f, UnderstoryLatMax = 9f;
        const float UnderstoryRoadClearance = 5.5f; // half-road + margin; anything closer is skipped
        const int UnderstoryMaxResample = 6; // retries to find a lateral clearing the road before skipping

        static void ScatterUnderstory()
        {
            var understoryRoot = ReplaceChild(GetSliceRoot(), "Understory");

            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] ScatterUnderstory: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();

            string centerlinePath = Path.Combine(GenDir, "centerline.json");
            if (!File.Exists(centerlinePath))
            {
                Debug.LogError("[DressSlice] ScatterUnderstory: centerline.json not found (run 70_sync_unity.py).");
                return;
            }
            var cl = JsonUtility.FromJson<CenterlineRoot>(File.ReadAllText(centerlinePath));
            if (cl == null || cl.stations == null || cl.stations.Length == 0)
            {
                Debug.LogError("[DressSlice] ScatterUnderstory: centerline.json has no stations.");
                return;
            }

            var pool = DiscoverPrefabs(SeedMeshGroundFoliageRoot).Concat(DiscoverTropicalPlantsMix()).ToList();
            if (pool.Count == 0)
            {
                Debug.LogError("[DressSlice] ScatterUnderstory: no prefabs found under " +
                    SeedMeshGroundFoliageRoot + " / " + SeedMeshTropicalPlantsRoot + ".");
                return;
            }

            var stations = cl.stations
                .Where(st => !st.provisional && st.s >= UnderstorySRangeLo && st.s <= UnderstorySRangeHi)
                .OrderBy(st => st.s).ToList();

            int n = 0, attempted = 0, skipped = 0;
            float nextS = UnderstorySRangeLo;
            foreach (var st in stations)
            {
                if (st.s < nextS) continue;
                nextS += UnderstoryStationStep;

                // ENU left normal = (-ty, tx) (see PlaceBarrier's derivation); side=+1 is
                // left of travel, side=-1 is right - covers "both sides" of the road.
                foreach (int side in new[] { 1, -1 })
                {
                    attempted++;
                    var rng = new System.Random(20260908 + attempted);
                    float lat = 0f;
                    for (int t = 0; t < UnderstoryMaxResample; t++)
                    {
                        lat = UnderstoryLatMin + (float)rng.NextDouble() * (UnderstoryLatMax - UnderstoryLatMin);
                        if (lat >= UnderstoryRoadClearance) break;
                    }
                    if (lat < UnderstoryRoadClearance) { skipped++; continue; }

                    float worldX = st.x + side * lat * (-st.ty);
                    float worldZ = st.y + side * lat * st.tx;
                    float worldY = WorldTerrainHeight(terrain, worldX, worldZ);

                    var prefab = pool[rng.Next(pool.Count)];
                    float yaw = (float)(rng.NextDouble() * 360.0);
                    float scale = 0.8f + (float)rng.NextDouble() * 0.5f;

                    var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                    inst.name = prefab.name + "_u" + n;
                    inst.transform.SetParent(understoryRoot.transform, false);
                    inst.transform.position = new Vector3(worldX, worldY, worldZ);
                    inst.transform.rotation = Quaternion.Euler(0f, yaw, 0f);
                    inst.transform.localScale = Vector3.one * scale;
                    n++;
                }
            }
            Debug.Log("[DressSlice] ScatterUnderstory: " + n + " instance(s) from " + pool.Count +
                " prefab(s) (" + attempted + " candidate slot(s), " + skipped + " skipped for road clearance).");
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
                if (c.h > 5f) continue; // tall placements handled by PlantTrees

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
            // render; stored under a dedicated folder shared with PlantTrees' converted
            // tree materials, so this only ensures the folder exists (not wipe-and-
            // recreate - that would delete PlantTrees' output, which runs earlier in
            // Dress()) and deletes/recreates its own per-tile files individually.
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

                foreach (var mr in inst.GetComponentsInChildren<MeshRenderer>())
                {
                    var mats = mr.sharedMaterials;
                    for (int i = 0; i < mats.Length; i++)
                    {
                        var src = mats[i];
                        if (src == null) continue;
                        var clone = new Material(src) { name = src.name + "_DoubleSided" };
                        clone.SetFloat("_Cull", (float)UnityEngine.Rendering.CullMode.Off);
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

            var shader = Shader.Find("Universal Render Pipeline/Lit");
            string stripePath = "Assets/Amakeng/Generated/barrier_stripe.png";
            var stripeTex = AssetDatabase.LoadAssetAtPath<Texture2D>(stripePath);
            string matPath = "Assets/Amakeng/BarrierMat.mat";
            AssetDatabase.DeleteAsset(matPath);
            var mat = new Material(shader) { name = "BarrierMat" };
            if (stripeTex != null) { mat.SetTexture("_BaseMap", stripeTex); mat.mainTexture = stripeTex; }
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
            light.intensity = 1.1f;
            light.color = new Color(1f, 0.97f, 0.92f);
            RenderSettings.sun = light;

            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.ExponentialSquared;
            RenderSettings.fogDensity = 0.004f;
            RenderSettings.fogColor = new Color(200f / 255f, 205f / 255f, 210f / 255f);

            Debug.Log("[DressSlice] SetAtmosphere: sun elevation=" + elevDeg.ToString("F1") +
                " deg, azimuth=" + azDeg.ToString("F1") + " deg (compass); fog Exp2 density=0.004.");
        }
    }
}
