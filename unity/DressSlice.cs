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
    [Serializable] public class CardPlacement { public float x, y, h; public string img; public float yaw_deg; }
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
        const string TreePackRoot = "Assets/TreePackVol.1";

        // Adaptation (review round 2): PlantTrees prefers Assets/TerrainSampleAssets (a
        // Unity-6-era, URP-ready pack) over TreePackVol.1's Tree Creator prefabs, which are
        // unconvertible (procedural "Hidden/Nature/Tree Creator ..." shaders, confirmed via
        // an exhaustive scan of all 48 TreePackVol.1 prefabs - every one uses only Tree
        // Creator shaders, zero exceptions). TerrainSampleAssets, however, has no prefab
        // literally named "Tree" (also verified by FindAssets) - the tallest, most
        // canopy-shaped items it has are these 4 bushes, which share the same URP
        // "Shader Graphs/TerrainGrass" material family as the Grass_A/Fern_A detail
        // prototypes already used in PaintDetails (so no magenta risk). Standing them in
        // for "trees" also matches this project's own stated priority
        // (CLAUDE.md: "Vegetation detail does not matter").
        static readonly string[] PreferredTerrainTreeNames = { "Bush_A", "Bush_B", "BushDry_A", "BushDry_B" };
        const int MaxTreePrototypes = 4;

        static float MeasureHeight(GameObject prefab)
        {
            var renderers = prefab.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return 6f;
            var b = renderers[0].bounds;
            foreach (var r in renderers) b.Encapsulate(r.bounds);
            return Mathf.Max(0.5f, b.size.y);
        }

        static bool UsesUnconvertibleShader(GameObject prefab)
        {
            var shaders = prefab.GetComponentsInChildren<Renderer>()
                .SelectMany(r => r.sharedMaterials).Where(m => m != null).Select(m => m.shader.name);
            return shaders.Any(s =>
                s.IndexOf("Tree Creator", StringComparison.OrdinalIgnoreCase) >= 0 ||
                s.IndexOf("SpeedTree", StringComparison.OrdinalIgnoreCase) >= 0 ||
                s.IndexOf("Soft Occlusion", StringComparison.OrdinalIgnoreCase) >= 0);
        }

        // Discovers up to MaxTreePrototypes (prefab, measuredHeight) pairs: prefers
        // TerrainSampleAssets (see PreferredTerrainTreeNames adaptation note above), falls
        // back to any TreePackVol.1 prefab whose renderers do NOT use a Tree Creator /
        // SpeedTree / Soft-Occlusion shader (i.e. would actually render under URP).
        static List<(GameObject prefab, float baseline)> DiscoverTreePrototypes()
        {
            var chosen = new List<(GameObject, float)>();

            var terrainGuids = AssetDatabase.FindAssets("t:Prefab", new[] { TerrainPackRoot });
            foreach (var name in PreferredTerrainTreeNames)
            {
                if (chosen.Count >= MaxTreePrototypes) break;
                var guid = terrainGuids.FirstOrDefault(g =>
                    Path.GetFileNameWithoutExtension(AssetDatabase.GUIDToAssetPath(g)) == name);
                if (guid == null) continue;
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(guid));
                if (prefab != null) chosen.Add((prefab, MeasureHeight(prefab)));
            }

            if (chosen.Count < MaxTreePrototypes)
            {
                var treeGuids = AssetDatabase.FindAssets("t:Prefab", new[] { TreePackRoot });
                foreach (var guid in treeGuids)
                {
                    if (chosen.Count >= MaxTreePrototypes) break;
                    var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(guid));
                    if (prefab == null || UsesUnconvertibleShader(prefab)) continue;
                    chosen.Add((prefab, MeasureHeight(prefab)));
                }
            }
            return chosen;
        }

        [MenuItem("Amakeng/Dress Slice")]
        public static void Dress()
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
            var scene = EditorSceneManager.OpenScene(BuildAmakeng.ScenePath, OpenSceneMode.Single);

            ConvertPackMaterials();
            BuildOverlay();
            PaintDetails();
            FixGroundMaterial();
            PlantTrees();
            PlaceCards();
            ImportBackdrop();
            PlaceBarrier();
            SetAtmosphere();

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);
            Debug.Log("[DressSlice] Dress: slice dressed and saved to " + BuildAmakeng.ScenePath);
        }

        static float Pf(string s) => float.Parse(s, CultureInfo.InvariantCulture);

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
            // Adaptation/note: TreePackVol.1 prefabs use the legacy procedural "Hidden/Nature/Tree
            // Creator Bark/Leaves (Fast) Optimized" shaders (Tree Creator engine), which the
            // Built-in->URP material converter does not remap (it targets Standard/legacy-diffuse
            // materials). Trees may still render magenta/pink after this step; fix manually via
            // Window > Rendering > Render Pipeline Converter, or by reassigning tree materials.
            Debug.LogWarning("[DressSlice] ConvertPackMaterials: TreePackVol.1 uses legacy Tree Creator " +
                "shaders not covered by the URP converter - trees may still appear magenta; see Window > " +
                "Rendering > Render Pipeline Converter to fix manually.");
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

        // Adaptation (review round 3, item 3): TerrainSampleAssets' bush shader graph
        // ("Shader Graphs/TerrainGrass") exposes no discoverable/settable base-colour tint
        // property - Unity's generic Material.color/.mainTexture (which normally resolve a
        // shader's [MainColor]/[MainTexture]-tagged properties) both error with "doesn't
        // have a colour/texture property" for this shader, and none of its ~90 exposed
        // properties (dumped via ShaderUtil) is a plain base-colour multiplier. Its base
        // colour texture IS exposed, just under an auto-generated Shader-Graph property
        // name ("Texture2D_E1B0D043"), found by probing each TexEnv slot and matching the
        // returned texture against the prefab's own "<Name>_BaseColor" asset. Rather than
        // fight that shader, instantiated bushes get a fresh, ordinary URP/Lit material
        // using the same base-colour texture with _BaseColor multiplied toward
        // (0.5, 0.75, 0.45) - guaranteed to work (URP/Lit is already used throughout this
        // file) at the cost of losing the pack's wind animation on these background props,
        // an acceptable trade-off given CLAUDE.md's own priority ("Vegetation detail does
        // not matter"). Applied uniformly to all instantiated bushes (not just the two
        // "Dry" variants) because the pack only has 4 bush-like items total (2 green + 2
        // dry) and all 4 are needed to reach the requested prototype count.
        const string BushBaseColorTexProperty = "Texture2D_E1B0D043";

        static Material MakeGreenTintedBushMaterial(GameObject prefab)
        {
            var srcRenderer = prefab.GetComponentInChildren<Renderer>();
            var srcMat = srcRenderer != null ? srcRenderer.sharedMaterial : null;
            Texture baseTex = null;
            if (srcMat != null && srcMat.HasProperty(BushBaseColorTexProperty))
                baseTex = srcMat.GetTexture(BushBaseColorTexProperty);
            else
                Debug.LogWarning("[DressSlice] MakeGreenTintedBushMaterial: " + prefab.name +
                    "'s material has no '" + BushBaseColorTexProperty + "' property; using a flat tint.");

            var shader = Shader.Find("Universal Render Pipeline/Lit");
            var mat = new Material(shader) { name = "TreeTint_" + prefab.name };
            if (baseTex != null) { mat.SetTexture("_BaseMap", baseTex); mat.mainTexture = baseTex; }
            mat.SetColor("_BaseColor", new Color(0.5f, 0.75f, 0.45f, 1f));
            mat.SetFloat("_Cull", (float)UnityEngine.Rendering.CullMode.Off); // foliage cards within the mesh
            mat.SetFloat("_Smoothness", 0.15f);

            string matPath = "Assets/Amakeng/TreeTint_" + prefab.name + ".mat";
            AssetDatabase.DeleteAsset(matPath);
            AssetDatabase.CreateAsset(mat, matPath);
            return AssetDatabase.LoadAssetAtPath<Material>(matPath);
        }

        // -------------------------------------------------------------------
        // 4. Trees (foliage_cards placements with h > 5 m).
        // -------------------------------------------------------------------
        // Adaptation (review round 2, item 2 follow-up): placed as ordinary instantiated
        // GameObjects under [GEN] Slice/Trees, NOT as Unity's built-in Terrain tree
        // prototypes/instances (terrainData.treePrototypes / SetTreeInstances). Unity's
        // terrain tree renderer requires a Tree-Creator/SpeedTree/Soft-Occlusion-family
        // shader for correct billboarding and lighting - assigning the round-2 fix's
        // TerrainSampleAssets bushes (Shader Graphs/TerrainGrass) as tree PROTOTYPES
        // triggers exactly this in-editor warning: "The tree Bush_A must use the Nature/
        // Soft Occlusion shader. Otherwise billboarding/lighting will not work correctly."
        // That mismatch between the terrain tree renderer's expectations and any
        // URP-native, non-Tree-Creator shader is almost certainly the real source of the
        // "floating dark billboard blobs" reported alongside the magenta trees - Unity's
        // terrain billboard LOD system rendering non-compliant materials incorrectly.
        // Plain GameObjects (used here, and already used for backdrop/cards) have no such
        // requirement and render normally under URP.
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
            // before this fix (PlantTrees used to populate terrainData.treePrototypes /
            // SetTreeInstances; it no longer does - see the adaptation note above).
            // Instances must be cleared BEFORE prototypes, or Unity logs "Tree removed:
            // invalid prototype N" while the (now-empty) prototype list briefly can't
            // satisfy the still-present old instances' prototypeIndex references.
            terrain.terrainData.SetTreeInstances(new TreeInstance[0], true);
            terrain.terrainData.treePrototypes = new TreePrototype[0];

            var discovered = DiscoverTreePrototypes();
            if (discovered.Count == 0)
            {
                Debug.LogError("[DressSlice] PlantTrees: no tree prototypes found (checked " +
                    TerrainPackRoot + " and " + TreePackRoot + "); skipping.");
                return;
            }
            if (discovered.Count < MaxTreePrototypes)
                Debug.LogWarning("[DressSlice] PlantTrees: only " + discovered.Count + "/" + MaxTreePrototypes +
                    " tree prototypes available.");
            Debug.Log("[DressSlice] PlantTrees: prototypes = " +
                string.Join(", ", discovered.Select(d => d.prefab.name)));

            // Green-tint material per prototype (review round 3, item 3 - see the
            // adaptation note above MakeGreenTintedBushMaterial).
            var tintMats = discovered.Select(d => MakeGreenTintedBushMaterial(d.prefab)).ToList();

            var placements = LoadPlacements();
            if (placements == null || placements.cards == null)
            {
                Debug.LogWarning("[DressSlice] PlantTrees: foliage_cards/placements.json missing; no trees placed.");
                return;
            }

            var rng = new System.Random(20260908);
            int protoCursor = 0;
            int n = 0;
            foreach (var c in placements.cards)
            {
                if (c.h <= 5f) continue; // tall placements only; h<=5 handled by PlaceCards as quads
                float worldY = terrain.SampleHeight(new Vector3(c.x, 0f, c.y));

                int protoIdx = protoCursor % discovered.Count;
                protoCursor++;
                var prefab = discovered[protoIdx].prefab;
                float baseline = discovered[protoIdx].baseline;
                float jitter = 0.9f + (float)rng.NextDouble() * 0.2f;
                float scale = Mathf.Clamp(c.h / baseline, 0.05f, 6f) * jitter;

                var inst = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                inst.name = prefab.name + "_" + n;
                inst.transform.SetParent(treesRoot.transform, false);
                inst.transform.position = new Vector3(c.x, worldY, c.y);
                inst.transform.rotation = Quaternion.Euler(0f, c.yaw_deg, 0f);
                inst.transform.localScale = Vector3.one * scale;
                foreach (var r in inst.GetComponentsInChildren<Renderer>())
                    r.sharedMaterial = tintMats[protoIdx];
                n++;
            }
            Debug.Log("[DressSlice] PlantTrees: " + n + " tree instance(s) from " + discovered.Count + " prototype(s).");
        }

        // -------------------------------------------------------------------
        // 5. Foliage card quads (foliage_cards placements with h <= 5 m).
        // -------------------------------------------------------------------
        static void PlaceCards()
        {
            var cardsRoot = ReplaceChild(GetSliceRoot(), "Cards");

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

                float worldY = terrain.SampleHeight(new Vector3(c.x, 0f, c.y));
                var go = new GameObject("Card_" + n);
                go.transform.SetParent(cardsRoot.transform, false);
                go.transform.position = new Vector3(c.x, worldY + c.h * 0.5f, c.y);
                go.transform.rotation = Quaternion.Euler(0f, c.yaw_deg, 0f);
                go.AddComponent<MeshFilter>().sharedMesh = MakeQuadMesh(c.h, c.h);
                go.AddComponent<MeshRenderer>().sharedMaterial = mat;
                n++;
            }
            Debug.Log("[DressSlice] PlaceCards: " + n + " foliage card quad(s) placed under [GEN] Slice/Cards.");
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
                y = terrGo.GetComponent<Terrain>().SampleHeight(new Vector3(xz.x, 0f, xz.z));

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
