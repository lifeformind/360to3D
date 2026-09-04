---
name: amakeng-deliverable-goal
description: "What the AMAKENG splat is actually for — drivable circuit, landmark fidelity over vegetation detail"
metadata: 
  node_type: memory
  type: project
  originSessionId: 38f76697-8b28-413a-b6e8-61b00fe9c261
  modified: 2026-08-05T07:14:37.331Z
---

The AMAKENG splat's purpose (stated 2026-08-05): a **drivable circuit in Unity** that *broadly feels like* Amakeng. Priority order: road surface, clearings, fences, signboards and other man-made landmarks. Exact placement/detail of leaves/trees does NOT matter.

**Why:** this relaxes the quality bar — metric accuracy and vegetation sharpness are negotiable; trajectory smoothness/plausibility and near-road landmark legibility are not.

**How to apply:** (1) global trajectory consistency (smooth, connected, plausibly scaled) outranks fine detail — a drivable path through the splat is the core deliverable; (2) heuristic fixes like constant-speed scale-drift correction of the trajectory are acceptable (the result only has to feel right, not be metrically exact); (3) vegetation can be trained/pruned aggressively; (4) segment-wise splats are a weaker fit since the circuit should be continuous. See [[pipeline-status-amakeng]].


**2026-09-01 pivot:** splat approach ABANDONED by the user ("nothing we have trained has been useful"). New direction = hybrid: road mesh from GPX centreline + DTM, landmarks as proxies, vegetation/backdrop procedurally or from video, drivable in Unity. Do not propose more splat training runs. See [[pipeline-status-amakeng]].
