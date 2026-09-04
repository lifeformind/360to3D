// Assembles the Amakeng scene from generated data. Menu: Amakeng > Build Scene.
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Amakeng
{
    [System.Serializable]
    public class TerrainMeta
    {
        public int resolution;
        public float size_x, size_z, height_min, height_range, origin_enu_x, origin_enu_y, z0;
    }

    [System.Serializable]
    public class StartPose { public float x_unity, y_unity, z_unity, heading_deg; }

    [System.Serializable]
    public class RoadMeta { public float z0; public StartPose start; public float[][] stations_unity; }

    public static class BuildAmakeng
    {
        const string GenDir = "Assets/Amakeng/Generated";
        public const string ScenePath = "Assets/Amakeng/Amakeng.unity";

        [MenuItem("Amakeng/Build Scene")]
        public static void BuildScene()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            BuildTerrain();
            BuildRoad();
            EditorSceneManager.SaveScene(scene, ScenePath);
            Debug.Log("Amakeng: scene built and saved to " + ScenePath);
        }

        static T LoadJson<T>(string file)
        {
            // JsonUtility can't parse float[][]; stations are re-read manually where needed.
            return JsonUtility.FromJson<T>(File.ReadAllText(Path.Combine(GenDir, file)));
        }

        static void Replace(string name)
        {
            var old = GameObject.Find(name);
            if (old != null) Object.DestroyImmediate(old);
        }

        static void BuildTerrain()
        {
            Replace("[GEN] Terrain");
            var meta = LoadJson<TerrainMeta>("terrain_meta.json");
            int res = meta.resolution;
            var bytes = File.ReadAllBytes(Path.Combine(GenDir, "terrain.raw.bytes"));
            var heights = new float[res, res]; // [row=z, col=x], row 0 = south: matches raw layout
            for (int r = 0; r < res; r++)
                for (int c = 0; c < res; c++)
                {
                    int i = (r * res + c) * 2;
                    heights[r, c] = (bytes[i] | (bytes[i + 1] << 8)) / 65535f;
                }

            var td = new TerrainData();
            td.heightmapResolution = res;
            td.size = new Vector3(meta.size_x, meta.height_range, meta.size_z);
            td.SetHeights(0, 0, heights);
            AssetDatabase.DeleteAsset("Assets/Amakeng/TerrainData.asset");
            AssetDatabase.CreateAsset(td, "Assets/Amakeng/TerrainData.asset");

            var go = Terrain.CreateTerrainGameObject(td);
            go.name = "[GEN] Terrain";
            go.transform.position = new Vector3(meta.origin_enu_x, meta.height_min, meta.origin_enu_y);
        }

        static void BuildRoad()
        {
            Replace("[GEN] Road");
            AssetDatabase.ImportAsset(GenDir + "/road.obj", ImportAssetOptions.ForceUpdate);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(GenDir + "/road.obj");
            var root = (GameObject)PrefabUtility.InstantiatePrefab(model);
            root.name = "[GEN] Road";
            root.transform.position = Vector3.zero;

            var shader = Shader.Find("Universal Render Pipeline/Lit");
            var gravel = new Material(shader) { color = new Color(0.45f, 0.42f, 0.38f) };
            var gravelTex = MakeGravelTexture(false);
            gravel.mainTexture = gravelTex;
            var prov = new Material(shader) { color = new Color(0.70f, 0.40f, 0.40f) };
            var provTex = MakeGravelTexture(true);
            prov.mainTexture = provTex;
            AssetDatabase.DeleteAsset("Assets/Amakeng/Gravel.mat");
            AssetDatabase.DeleteAsset("Assets/Amakeng/GravelProvisional.mat");
            AssetDatabase.CreateAsset(gravel, "Assets/Amakeng/Gravel.mat");
            AssetDatabase.CreateAsset(prov, "Assets/Amakeng/GravelProvisional.mat");
            // Textures must be persisted as sub-assets or they are lost on save (fileID: 0).
            gravelTex.name = "GravelTex";
            AssetDatabase.AddObjectToAsset(gravelTex, gravel);
            gravel.mainTexture = gravelTex;
            gravel.SetTexture("_BaseMap", gravelTex);
            provTex.name = "GravelProvisionalTex";
            AssetDatabase.AddObjectToAsset(provTex, prov);
            prov.mainTexture = provTex;
            prov.SetTexture("_BaseMap", provTex);
            AssetDatabase.SaveAssets();

            foreach (var mf in root.GetComponentsInChildren<MeshFilter>())
            {
                var mc = mf.gameObject.AddComponent<MeshCollider>();
                mc.sharedMesh = mf.sharedMesh;
                var mr = mf.GetComponent<MeshRenderer>();
                bool isProv = mf.gameObject.name.Contains("provisional");
                mr.sharedMaterial = isProv ? prov : gravel;
            }
        }

        static Texture2D MakeGravelTexture(bool tinted)
        {
            var tex = new Texture2D(256, 256);
            var rng = new System.Random(42);
            for (int y = 0; y < 256; y++)
                for (int x = 0; x < 256; x++)
                {
                    float v = 0.55f + (float)rng.NextDouble() * 0.25f;
                    tex.SetPixel(x, y, tinted ? new Color(v, v * 0.6f, v * 0.6f)
                                              : new Color(v * 0.95f, v * 0.92f, v * 0.85f));
                }
            tex.Apply();
            return tex;
        }

        // Raycast the road along the centreline; used by Task 8 validation.
        public static void ValidateRoad()
        {
            var lines = File.ReadAllText(Path.Combine(GenDir, "road_meta.json"));
            var stations = MiniJsonStations(lines);
            int bad = 0;
            foreach (var s in stations)
            {
                var origin = new Vector3(s.x, s.y + 50f, s.z);
                if (!Physics.Raycast(origin, Vector3.down, out var hit, 100f) ||
                    Mathf.Abs(hit.point.y - s.y) > 0.5f)
                {
                    bad++;
                    Debug.LogWarning($"Amakeng validate: bad station at {s}");
                }
            }
            Debug.Log($"Amakeng validate: {stations.Count - bad}/{stations.Count} stations OK");
            if (bad > stations.Count / 100) throw new System.Exception($"Amakeng validate FAILED: {bad} bad stations");
        }

        static System.Collections.Generic.List<Vector3> MiniJsonStations(string json)
        {
            // stations_unity: [[x,y,z],...] - tiny manual parse (JsonUtility can't do nested arrays)
            var outp = new System.Collections.Generic.List<Vector3>();
            int i = json.IndexOf("\"stations_unity\"");
            i = json.IndexOf('[', i) + 1;
            while (true)
            {
                int a = json.IndexOf('[', i);
                if (a < 0) break;
                int b = json.IndexOf(']', a);
                var parts = json.Substring(a + 1, b - a - 1).Split(',');
                outp.Add(new Vector3(float.Parse(parts[0]), float.Parse(parts[1]), float.Parse(parts[2])));
                i = b + 1;
                if (json[i] == ']') break;
            }
            return outp;
        }
    }
}
