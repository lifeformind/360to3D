// Editor utility: place the 18 AMAKENG section splats in the shared GPX-anchored frame.
// 1. Import each splat_output/sXX/ply/point_cloud_29999.ply with the UnityGaussianSplatting
//    asset creator and add a GaussianSplatRenderer GameObject per section, NAMED "s01".."s18".
// 2. Copy unity_placement.json into the project (e.g. Assets/Amakeng/unity_placement.json).
// 3. Menu: Amakeng > Place Sections (select the JSON in the file dialog).
// Frame: x = East, y = Up, z = North, metres; origin = first GPX fix. Road plane is y ~ 0.
// The negative z scale is required: the PLY data is right-handed, Unity is left-handed.
#if UNITY_EDITOR
using System;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class PlaceAmakengSections
{
    [Serializable] class Item { public string name, status; public float px, py, pz, qx, qy, qz, qw, sx, sy, sz; }
    [Serializable] class Root { public Item[] items; }

    [MenuItem("Amakeng/Place Sections")]
    public static void Place()
    {
        string path = EditorUtility.OpenFilePanel("unity_placement.json", Application.dataPath, "json");
        if (string.IsNullOrEmpty(path)) return;
        var root = JsonUtility.FromJson<Root>(File.ReadAllText(path));
        int placed = 0;
        foreach (var it in root.items)
        {
            var go = GameObject.Find(it.name);
            if (go == null) { Debug.LogWarning($"[Amakeng] no GameObject named {it.name}"); continue; }
            Undo.RecordObject(go.transform, "Place Amakeng section");
            go.transform.localPosition = new Vector3(it.px, it.py, it.pz);
            go.transform.localRotation = new Quaternion(it.qx, it.qy, it.qz, it.qw);
            go.transform.localScale = new Vector3(it.sx, it.sy, it.sz);
            if (it.status == "drop") { go.SetActive(false); Debug.Log($"[Amakeng] {it.name}: disabled (status=drop)"); }
            else if (it.status == "check") Debug.Log($"[Amakeng] {it.name}: placed — flagged 'check', verify overlaps");
            placed++;
        }
        Debug.Log($"[Amakeng] placed {placed}/{root.items.Length} sections");
    }
}
#endif
