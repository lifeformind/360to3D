// Dresses the vertical-slice scene: road overlay, verge grass/fern detail, trees, foliage
// cards, backdrop mountains, barrier, sun + fog. Menu: Amakeng > Dress Slice.
// Idempotent: every step deletes/replaces its own [GEN] Slice child (or TerrainData layer)
// before rebuilding, so re-running Dress() after re-syncing exports is always safe.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
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

    public static class DressSlice
    {
        const string GenDir = "Assets/Amakeng/Generated";

        // Adaptation: TreePackVol.1 prefabs are wildly inconsistent in modelled scale
        // (measured render bounds: folder0/Tree1 ~33m tall, folder1/Tree ~2.2m,
        // folder4/Tree1 ~51m, Palm/Tree1 ~21m) - not a uniform "real metres" pack.
        // We therefore scale each prototype at placement time by its OWN measured
        // baseline height so a target canopy height (foliage_cards h, 5-8m) comes out
        // close to correct regardless of the source prefab's native scale.
        static readonly string[] TreePrefabPaths =
        {
            "Assets/TreePackVol.1/Prefabs/0/Tree1.prefab",
            "Assets/TreePackVol.1/Prefabs/1/Tree.prefab",
            "Assets/TreePackVol.1/Prefabs/4/Tree1.prefab",
            "Assets/TreePackVol.1/Prefabs/Palm/Tree 1.prefab",
        };

        [MenuItem("Amakeng/Dress Slice")]
        public static void Dress()
        {
            AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);
            var scene = EditorSceneManager.OpenScene(BuildAmakeng.ScenePath, OpenSceneMode.Single);

            ConvertPackMaterials();
            BuildOverlay();
            PaintDetails();
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
                    // Adaptation: road_overlay.obj's X axis is mirrored relative to the
                    // road_meta.json / road.obj / terrain frame. Verified by nearest-centreline
                    // -station distance over a sample of overlay vertices: 564 m average as
                    // exported vs 4.9 m average after negating X (consistent with the mesh's
                    // 7 m lateral half-width) - so X is negated here to align the overlay to
                    // the road ribbon.
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
                        cur.Faces.Add(idx[0]); cur.Faces.Add(idx[i]); cur.Faces.Add(idx[i + 1]);
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
            var grassPrefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/TerrainSampleAssets/Prefabs/Grass_A.prefab");
            var fernPrefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/TerrainSampleAssets/Prefabs/Fern_A.prefab");
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
        // 4. Trees (foliage_cards placements with h > 5 m).
        // -------------------------------------------------------------------
        static void PlantTrees()
        {
            var terrGo = GameObject.Find("[GEN] Terrain");
            if (terrGo == null)
            {
                Debug.LogError("[DressSlice] PlantTrees: [GEN] Terrain not found; run Amakeng/Build Scene first.");
                return;
            }
            var terrain = terrGo.GetComponent<Terrain>();
            var td = terrain.terrainData;

            var protoList = new List<TreePrototype>();
            var baselineHeights = new List<float>();
            foreach (var p in TreePrefabPaths)
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(p);
                if (prefab == null)
                {
                    Debug.LogWarning("[DressSlice] PlantTrees: tree prefab missing: " + p);
                    continue;
                }
                protoList.Add(new TreePrototype { prefab = prefab });
                float baseline = 6f;
                var renderers = prefab.GetComponentsInChildren<Renderer>();
                if (renderers.Length > 0)
                {
                    var b = renderers[0].bounds;
                    foreach (var r in renderers) b.Encapsulate(r.bounds);
                    baseline = Mathf.Max(0.5f, b.size.y);
                }
                baselineHeights.Add(baseline);
            }
            if (protoList.Count == 0)
            {
                Debug.LogError("[DressSlice] PlantTrees: no tree prototypes found; skipping.");
                return;
            }
            td.treePrototypes = protoList.ToArray();

            var placements = LoadPlacements();
            if (placements == null || placements.cards == null)
            {
                Debug.LogWarning("[DressSlice] PlantTrees: foliage_cards/placements.json missing; no trees placed.");
                td.SetTreeInstances(Array.Empty<TreeInstance>(), true);
                return;
            }

            Vector3 terrPos = terrGo.transform.position;
            Vector3 size = td.size;
            var rng = new System.Random(20260908);
            var instances = new List<TreeInstance>();
            int protoCursor = 0;
            foreach (var c in placements.cards)
            {
                if (c.h <= 5f) continue; // tall placements only; h<=5 handled by PlaceCards as quads
                float worldY = terrain.SampleHeight(new Vector3(c.x, 0f, c.y));
                float nx = (c.x - terrPos.x) / size.x;
                float nz = (c.y - terrPos.z) / size.z;
                float ny = (worldY - terrPos.y) / size.y;
                if (nx < 0f || nx > 1f || nz < 0f || nz > 1f) continue;

                int protoIdx = protoCursor % protoList.Count;
                protoCursor++;
                float jitter = 0.9f + (float)rng.NextDouble() * 0.2f;
                float scale = Mathf.Clamp(c.h / baselineHeights[protoIdx], 0.05f, 6f) * jitter;

                instances.Add(new TreeInstance
                {
                    position = new Vector3(nx, ny, nz),
                    prototypeIndex = protoIdx,
                    widthScale = scale,
                    heightScale = scale,
                    rotation = c.yaw_deg * Mathf.Deg2Rad,
                    color = Color.white,
                    lightmapColor = Color.white,
                });
            }
            td.SetTreeInstances(instances.ToArray(), true);
            Debug.Log("[DressSlice] PlantTrees: " + instances.Count + " tree instance(s) from " + protoList.Count + " prototype(s).");
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
                    m.SetFloat("_Surface", 0f);   // opaque
                    m.SetFloat("_AlphaClip", 1f);
                    m.SetFloat("_Cutoff", 0.3f);
                    m.EnableKeyword("_ALPHATEST_ON");
                    m.SetFloat("_Cull", (float)UnityEngine.Rendering.CullMode.Off); // two-sided
                    m.renderQueue = (int)UnityEngine.Rendering.RenderQueue.AlphaTest;

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
            var left = new Vector3(-tangent.z, 0f, tangent.x).normalized;
            var xz = centre + left * extras.barrier.lat;

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
