// Builds the drivable vehicle at the road start pose. Menu: Amakeng > Build Vehicle.
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Amakeng
{
    public static class BuildVehicle
    {
        [MenuItem("Amakeng/Build Vehicle")]
        public static void Build()
        {
            EditorSceneManager.OpenScene(BuildAmakeng.ScenePath);
            var old = GameObject.Find("[GEN] Vehicle");
            if (old != null) Object.DestroyImmediate(old);

            var meta = JsonUtility.FromJson<RoadMeta>(
                File.ReadAllText("Assets/Amakeng/Generated/road_meta.json"));

            var root = new GameObject("[GEN] Vehicle");
            root.transform.SetPositionAndRotation(
                new Vector3(meta.start.x_unity, meta.start.y_unity + 1.0f, meta.start.z_unity),
                Quaternion.Euler(0, meta.start.heading_deg, 0));

            var body = GameObject.CreatePrimitive(PrimitiveType.Cube);
            body.name = "Body";
            body.transform.SetParent(root.transform, false);
            body.transform.localScale = new Vector3(1.9f, 0.9f, 4.2f);
            body.transform.localPosition = new Vector3(0, 0.7f, 0);

            var rb = root.AddComponent<Rigidbody>();
            rb.mass = 1500f;
            var vc = root.AddComponent<VehicleController>();

            var wheels = new WheelCollider[4];
            var pos = new[] { new Vector3(-0.8f, 0.35f, 1.4f), new Vector3(0.8f, 0.35f, 1.4f),
                              new Vector3(-0.8f, 0.35f, -1.4f), new Vector3(0.8f, 0.35f, -1.4f) };
            for (int i = 0; i < 4; i++)
            {
                var w = new GameObject("Wheel" + i);
                w.transform.SetParent(root.transform, false);
                w.transform.localPosition = pos[i];
                var wc = w.AddComponent<WheelCollider>();
                wc.radius = 0.35f;
                wc.suspensionDistance = 0.25f;
                var spring = wc.suspensionSpring;
                spring.spring = 45000f; spring.damper = 4000f;
                wc.suspensionSpring = spring;
                wheels[i] = wc;

                var vis = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                Object.DestroyImmediate(vis.GetComponent<Collider>());
                vis.transform.SetParent(root.transform, false);
                vis.transform.localScale = new Vector3(0.7f, 0.12f, 0.7f);
                vis.transform.localRotation = Quaternion.Euler(0, 0, 90);
                vc.wheelVisuals[i] = vis.transform;
            }
            vc.fl = wheels[0]; vc.fr = wheels[1]; vc.rl = wheels[2]; vc.rr = wheels[3];

            var cam = Camera.main ?? new GameObject("Main Camera").AddComponent<Camera>();
            cam.gameObject.tag = "MainCamera";
            var fc = cam.gameObject.GetComponent<FollowCamera>() ?? cam.gameObject.AddComponent<FollowCamera>();
            fc.target = root.transform;

            EditorSceneManager.MarkSceneDirty(root.scene);
            EditorSceneManager.SaveScene(root.scene);
            Debug.Log("Amakeng: vehicle built at start pose");
        }

        [MenuItem("Amakeng/Validate Road")]
        public static void Validate()
        {
            EditorSceneManager.OpenScene(BuildAmakeng.ScenePath);
            BuildAmakeng.ValidateRoad();
        }
    }
}
