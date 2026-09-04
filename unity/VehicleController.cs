// Minimal WheelCollider vehicle: arrows/WASD, rear drive, front steer, speed readout.
using UnityEngine;

namespace Amakeng
{
    public class VehicleController : MonoBehaviour
    {
        public WheelCollider fl, fr, rl, rr;
        public Transform[] wheelVisuals = new Transform[4];
        public float motorTorque = 1200f, maxSteer = 28f, brakeTorque = 2500f;
        Rigidbody rb;

        void Start()
        {
            rb = GetComponent<Rigidbody>();
            rb.centerOfMass = new Vector3(0, -0.6f, 0);
        }

        void FixedUpdate()
        {
            float steer = Input.GetAxis("Horizontal") * maxSteer;
            float drive = Input.GetAxis("Vertical") * motorTorque;
            bool brake = Input.GetKey(KeyCode.Space);
            fl.steerAngle = fr.steerAngle = steer;
            rl.motorTorque = rr.motorTorque = brake ? 0 : drive;
            fl.brakeTorque = fr.brakeTorque = rl.brakeTorque = rr.brakeTorque = brake ? brakeTorque : 0;
            var wcs = new[] { fl, fr, rl, rr };
            for (int i = 0; i < 4; i++)
            {
                if (wheelVisuals[i] == null) continue;
                wcs[i].GetWorldPose(out var p, out var q);
                wheelVisuals[i].SetPositionAndRotation(p, q);
            }
        }

        void OnGUI()
        {
            GUI.Label(new Rect(10, 10, 200, 30),
                      $"{rb.linearVelocity.magnitude * 3.6f:F0} km/h", new GUIStyle
                      { fontSize = 24, normal = { textColor = Color.white } });
        }
    }

    public class FollowCamera : MonoBehaviour
    {
        public Transform target;
        public Vector3 offset = new Vector3(0, 2.2f, -6f);

        void LateUpdate()
        {
            if (target == null) return;
            var want = target.TransformPoint(offset);
            transform.position = Vector3.Lerp(transform.position, want, 0.1f);
            transform.LookAt(target.position + Vector3.up * 1.2f);
        }
    }
}
