// Editor utility: build an invisible drivable road ribbon (MeshCollider) from road_centerline_unity.csv.
// The splats have no collision, so this gives the vehicle something to drive on.
// Menu: Amakeng > Build Road Collider (pick road_centerline_unity.csv in the file dialog).
// Frame: x = East, y = Up, z = North, metres — same frame as the baked section PLYs (identity transforms).
#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class BuildAmakengRoad
{
    const float RoadWidth = 8.0f;     // metres, total width of the ribbon
    const float Stride = 2.0f;        // metres between ribbon cross-sections
    const float Sink = 0.05f;         // put the collider slightly below the splat road surface

    [MenuItem("Amakeng/Build Road Collider")]
    public static void Build()
    {
        string path = EditorUtility.OpenFilePanel("road_centerline_unity.csv", Application.dataPath, "csv");
        if (string.IsNullOrEmpty(path)) return;
        var pts = new List<Vector3>();
        foreach (var line in File.ReadAllLines(path))
        {
            var f = line.Split(',');
            if (f.Length < 5 || f[0] == "frame") continue;
            var p = new Vector3(float.Parse(f[2]), float.Parse(f[3]) - Sink, float.Parse(f[4]));
            if (pts.Count == 0 || Vector3.Distance(pts[pts.Count - 1], p) >= Stride) pts.Add(p);
        }
        if (pts.Count < 2) { Debug.LogError("[Amakeng] centreline too short"); return; }

        var verts = new List<Vector3>(); var uvs = new List<Vector2>(); var tris = new List<int>();
        for (int i = 0; i < pts.Count; i++)
        {
            Vector3 fwd = (i + 1 < pts.Count ? pts[i + 1] - pts[i] : pts[i] - pts[i - 1]); fwd.y = 0;
            if (fwd.sqrMagnitude < 1e-6f) fwd = Vector3.forward;
            Vector3 right = Vector3.Cross(Vector3.up, fwd.normalized) * (RoadWidth * 0.5f);
            verts.Add(pts[i] - right); verts.Add(pts[i] + right);
            uvs.Add(new Vector2(0, i)); uvs.Add(new Vector2(1, i));
            if (i > 0)
            {
                int b = 2 * (i - 1);
                tris.AddRange(new[] { b, b + 2, b + 1, b + 1, b + 2, b + 3 });   // clockwise = up-facing in Unity
            }
        }
        var mesh = new Mesh { name = "AmakengRoad", indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
        mesh.SetVertices(verts); mesh.SetUVs(0, uvs); mesh.SetTriangles(tris, 0); mesh.RecalculateNormals(); mesh.RecalculateBounds();

        var go = GameObject.Find("AmakengRoad") ?? new GameObject("AmakengRoad");
        Undo.RegisterCreatedObjectUndo(go, "Build Amakeng road");
        go.transform.position = Vector3.zero; go.transform.rotation = Quaternion.identity; go.transform.localScale = Vector3.one;
        var mf = go.GetComponent<MeshFilter>() ?? go.AddComponent<MeshFilter>(); mf.sharedMesh = mesh;
        var mc = go.GetComponent<MeshCollider>() ?? go.AddComponent<MeshCollider>(); mc.sharedMesh = mesh;
        var mr = go.GetComponent<MeshRenderer>() ?? go.AddComponent<MeshRenderer>();
        mr.enabled = false;   // collider only; enable + assign a material to see the ribbon while tuning
        Debug.Log($"[Amakeng] road collider: {pts.Count} cross-sections, {verts.Count} verts, length ~{(pts.Count - 1) * Stride} m, start {pts[0]}");
    }
}
#endif
