"""Generates Assets/Amakeng/HDRP/OverlayShadowMatteUnlit.shadergraph: a minimal HD Unlit
Shader Graph (one Texture2D property -> Sample Texture 2D -> Base Color) with Shadow Matte
enabled, so the road-mosaic overlay can be genuinely Unlit (not re-lit/double-exposed by the
scene's directional light - it already carries its own baked lighting from the source video)
while still compositing real-time cast shadows onto it.

Why generate this instead of authoring it once by hand in the Shader Graph editor and
committing the resulting asset: this project's whole Assets/Amakeng subtree is otherwise
100% reproducible from committed generator code (BuildAmakeng/DressSlice/SetupHdrp build
everything procedurally each run; nothing under Assets/Amakeng is itself committed to this
git repo) - a hand-authored, committed .shadergraph binary asset would be the one exception
to that discipline. Shader Graph's own graph-construction API (GraphData, HDTarget,
HDUnlitSubTarget, GraphUtil, ...) is `internal` to Unity's Editor assemblies and not
reasonably scriptable from C# without deep reflection (see task-1-report.md), but a
.shadergraph file on disk is just Unity's "multi-json" format (a sequence of separate
top-level JSON objects, each with its own m_Type/m_ObjectId, cross-referenced by id) - so
this script instead starts from a real, minimal, known-good HD Unlit graph HDRP itself ships
(Runtime/ShaderLibrary/SolidColor.shadergraph: a single Color property feeding Base Color,
targeting HDUnlitSubTarget only) and surgically edits its JSON text: swaps the Color property
for a Texture2D property sampled through a "Sample Texture 2D" node (wiring pattern copied
from another HDRP-shipped graph, ParticleUnlit.shadergraph, which uses the identical
PropertyNode -> SampleTexture2DNode -> BlockNode pattern), and flips
HDUnlitData.m_EnableShadowMatte to true (confirmed live: this is the *only* way to get a
material where HasProperty("_ShadowMatteFilter") is true in this HDRP version - the fixed,
non-graph "HDRP/Unlit" shader never declares that property at all, so Shadow Matte silently
does nothing on it no matter what a script sets - see task-1-report.md's probe evidence).

Idempotent: does nothing if the output file already exists (delete it to force
regeneration - e.g. after an HDRP package upgrade changes SolidColor.shadergraph's internal
structure enough that the exact-substring edits below no longer match, in which case this
script will raise an AssertionError naming which substring went missing rather than silently
producing a broken graph).

Run via `venv/Scripts/python scripts/72_shadowmatte_shadergraph.py` (also invoked
automatically from scripts/70_sync_unity.py). Verified working end to end against Unity
6000.3.19f1 / HDRP 17.3.0: imports with 0 console errors, the generated material has both
_UnlitColorMap and _ShadowMatteFilter properties, and a shadow-casting probe cube confirmed a
real-time shadow actually composites onto a material using this shader (see
task-1-report.md).
"""
import glob
import json
import uuid
from pathlib import Path

UNITY_PROJECT = Path(r"C:\repos\AmakengCircuit")
OUT_PATH = UNITY_PROJECT / "Assets" / "Amakeng" / "HDRP" / "OverlayShadowMatteUnlit.shadergraph"

# The material-facing texture property name MakeShadowMatteUnlit() (unity/DressSlice.cs)
# sets via Material.SetTexture(...).
PROPERTY_REFERENCE_NAME = "_UnlitColorMap"

# Ids inside the source SolidColor.shadergraph that get removed/rewired. Pinned exactly (not
# discovered by parsing) so that if a future HDRP version renumbers/restructures this file,
# the asserts below fail loudly instead of this script silently generating nonsense.
OLD_COLOR_PROP_ID = "a437cd334d1a4b29b4334ed61fde5f0d"
OLD_PROP_NODE_ID = "9bc9270c15d54f598fb375cb904e9ef6"
OLD_PROP_NODE_SLOT_ID = "f5789c53f1524382871765a93249d7ad"  # Vector4MaterialSlot "ObjectColor"
CATEGORY_DATA_ID = "29728dabd62443fb8186c38d976e0666"
BASECOLOR_BLOCK_ID = "f2d95ecbdbbc4e4996539c2048726aee"  # SurfaceDescription.BaseColor BlockNode
HDUNLIT_DATA_ID = "dae70d3d5d5c4c278b35d1945d6b0b32"


def _find_source_shadergraph() -> Path:
    """Locate HDRP's shipped SolidColor.shadergraph without hardcoding the PackageCache
    folder's content-hash suffix (com.unity.render-pipelines.high-definition@<hash>), which
    varies by machine and changes on every package version bump."""
    pattern = str(UNITY_PROJECT / "Library" / "PackageCache" /
                  "com.unity.render-pipelines.high-definition@*" /
                  "Runtime" / "ShaderLibrary" / "SolidColor.shadergraph")
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(
            "Could not find HDRP's SolidColor.shadergraph under Library/PackageCache - "
            "is HDRP installed/imported yet? (Run Amakeng > Setup HDRP once first.)"
        )
    return Path(matches[0])


def _new_id() -> str:
    return uuid.uuid4().hex


def _block(obj) -> str:
    return json.dumps(obj, indent=4)


def _remove_block_exact(text: str, needle_containing_id: str, object_id: str) -> str:
    """Remove the one top-level {...} block whose body contains needle_containing_id, by
    locating its enclosing braces. Simpler and more robust to minor formatting drift than a
    regex, since it just balances braces from the first '{' before the id back to the
    matching '}' - but still pinned to an exact id, so it fails loudly (assert) rather than
    guessing if the id has moved or disappeared."""
    idx = text.find(needle_containing_id)
    assert idx >= 0, f"id {object_id} not found in source shadergraph - HDRP version changed?"
    start = text.rfind("{\n", 0, idx)
    assert start >= 0
    end = text.find("\n}\n", idx)
    assert end >= 0
    return text[:start] + text[end + 3:]


def generate() -> None:
    if OUT_PATH.exists():
        print(f"  {OUT_PATH.relative_to(UNITY_PROJECT)} already exists - skipping (delete it to force regeneration)")
        return

    src = _find_source_shadergraph()
    text = src.read_text(encoding="utf-8")

    for object_id in (OLD_COLOR_PROP_ID, OLD_PROP_NODE_ID, OLD_PROP_NODE_SLOT_ID,
                       CATEGORY_DATA_ID, BASECOLOR_BLOCK_ID, HDUNLIT_DATA_ID):
        assert object_id in text, f"expected id {object_id} not found - HDRP version changed?"

    text = _remove_block_exact(text, '"m_ObjectId": "' + OLD_COLOR_PROP_ID + '"', OLD_COLOR_PROP_ID)
    text = _remove_block_exact(text, '"m_ObjectId": "' + OLD_PROP_NODE_ID + '"', OLD_PROP_NODE_ID)
    text = _remove_block_exact(text, '"m_ObjectId": "' + OLD_PROP_NODE_SLOT_ID + '"', OLD_PROP_NODE_SLOT_ID)

    tex_prop_id = _new_id()
    tex_prop_node_id = _new_id()
    tex_prop_node_slot_id = _new_id()
    sample_node_id = _new_id()
    sample_rgba_id = _new_id()
    sample_r_id = _new_id()
    sample_g_id = _new_id()
    sample_b_id = _new_id()
    sample_a_id = _new_id()
    sample_tex_in_id = _new_id()
    sample_uv_id = _new_id()
    sample_sampler_id = _new_id()

    def replace_exact(old: str, new: str):
        nonlocal text
        assert old in text, f"exact substring not found (HDRP version changed?):\n{old[:200]}"
        text = text.replace(old, new, 1)

    replace_exact(
        '"m_Properties": [\n        {\n            "m_Id": "' + OLD_COLOR_PROP_ID + '"\n        }\n    ]',
        '"m_Properties": [\n        {\n            "m_Id": "' + tex_prop_id + '"\n        }\n    ]',
    )
    replace_exact(
        '{\n            "m_Id": "' + OLD_PROP_NODE_ID + '"\n        }',
        '{\n            "m_Id": "' + tex_prop_node_id + '"\n        },\n        {\n            "m_Id": "' + sample_node_id + '"\n        }',
    )
    replace_exact(
        '"m_ChildObjectList": [\n        {\n            "m_Id": "' + OLD_COLOR_PROP_ID + '"\n        }\n    ]',
        '"m_ChildObjectList": [\n        {\n            "m_Id": "' + tex_prop_id + '"\n        }\n    ]',
    )

    old_edge = (
        '{\n            "m_OutputSlot": {\n                "m_Node": {\n                    "m_Id": "'
        + OLD_PROP_NODE_ID
        + '"\n                },\n                "m_SlotId": 0\n            },\n            "m_InputSlot": {\n'
        + '                "m_Node": {\n                    "m_Id": "'
        + BASECOLOR_BLOCK_ID
        + '"\n                },\n                "m_SlotId": 0\n            }\n        }'
    )
    new_edges = (
        '{\n            "m_OutputSlot": {\n                "m_Node": {\n                    "m_Id": "'
        + tex_prop_node_id
        + '"\n                },\n                "m_SlotId": 0\n            },\n            "m_InputSlot": {\n'
        + '                "m_Node": {\n                    "m_Id": "'
        + sample_node_id
        + '"\n                },\n                "m_SlotId": 1\n            }\n        },\n'
        + '        {\n            "m_OutputSlot": {\n                "m_Node": {\n                    "m_Id": "'
        + sample_node_id
        + '"\n                },\n                "m_SlotId": 0\n            },\n            "m_InputSlot": {\n'
        + '                "m_Node": {\n                    "m_Id": "'
        + BASECOLOR_BLOCK_ID
        + '"\n                },\n                "m_SlotId": 0\n            }\n        }'
    )
    replace_exact(old_edge, new_edges)

    replace_exact(
        '"m_ObjectId": "' + HDUNLIT_DATA_ID + '",\n    "m_EnableShadowMatte": false,\n    "m_DistortionOnly": true',
        '"m_ObjectId": "' + HDUNLIT_DATA_ID + '",\n    "m_EnableShadowMatte": true,\n    "m_DistortionOnly": false',
    )

    new_blocks = [
        {
            "m_SGVersion": 0,
            "m_Type": "UnityEditor.ShaderGraph.Internal.Texture2DShaderProperty",
            "m_ObjectId": tex_prop_id,
            "m_Guid": {"m_GuidSerialized": str(uuid.uuid4())},
            "m_Name": "Unlit Color Map",
            "m_DefaultRefNameVersion": 0,
            "m_RefNameGeneratedByDisplayName": "",
            "m_DefaultReferenceName": "Texture2D_" + tex_prop_id[:8].upper(),
            "m_OverrideReferenceName": PROPERTY_REFERENCE_NAME,
            "m_GeneratePropertyBlock": True,
            "m_UseCustomSlotLabel": False,
            "m_CustomSlotLabel": "",
            "m_DismissedVersion": 0,
            "m_Precision": 0,
            "overrideHLSLDeclaration": False,
            "hlslDeclarationOverride": 0,
            "m_Hidden": False,
            "m_PerRendererData": False,
            "m_customAttributes": [],
            "m_Value": {
                "m_SerializedTexture": "{\"texture\":{\"fileID\":10300,\"guid\":\"0000000000000000f000000000000000\",\"type\":0}}",
                "m_Guid": "",
            },
            "isMainTexture": True,
            "useTilingAndOffset": False,
            "useTexelSize": False,
            "m_Modifiable": True,
            "m_DefaultType": 0,
        },
        {
            "m_SGVersion": 0,
            "m_Type": "UnityEditor.ShaderGraph.PropertyNode",
            "m_ObjectId": tex_prop_node_id,
            "m_Group": {"m_Id": ""},
            "m_Name": "Property",
            "m_DrawState": {
                "m_Expanded": True,
                "m_Position": {"serializedVersion": "2", "x": -900.0, "y": -100.0, "width": 140.0, "height": 36.0},
            },
            "m_Slots": [{"m_Id": tex_prop_node_slot_id}],
            "synonyms": [],
            "m_Precision": 0,
            "m_PreviewExpanded": True,
            "m_PreviewMode": 0,
            "m_CustomColors": {"m_SerializableColors": []},
            "m_Property": {"m_Id": tex_prop_id},
        },
        {
            "m_SGVersion": 0,
            "m_Type": "UnityEditor.ShaderGraph.Texture2DMaterialSlot",
            "m_ObjectId": tex_prop_node_slot_id,
            "m_Id": 0,
            "m_DisplayName": "Unlit Color Map",
            "m_SlotType": 1,
            "m_Hidden": False,
            "m_ShaderOutputName": "Out",
            "m_StageCapability": 3,
            "m_BareResource": False,
        },
        {
            "m_SGVersion": 0,
            "m_Type": "UnityEditor.ShaderGraph.SampleTexture2DNode",
            "m_ObjectId": sample_node_id,
            "m_Group": {"m_Id": ""},
            "m_Name": "Sample Texture 2D",
            "m_DrawState": {
                "m_Expanded": True,
                "m_Position": {"serializedVersion": "2", "x": -650.0, "y": -220.0, "width": 209.0, "height": 437.0},
            },
            "m_Slots": [
                {"m_Id": sample_rgba_id}, {"m_Id": sample_r_id}, {"m_Id": sample_g_id}, {"m_Id": sample_b_id},
                {"m_Id": sample_a_id}, {"m_Id": sample_tex_in_id}, {"m_Id": sample_uv_id}, {"m_Id": sample_sampler_id},
            ],
            "synonyms": ["tex2d"],
            "m_Precision": 0,
            "m_PreviewExpanded": True,
            "m_DismissedVersion": 0,
            "m_PreviewMode": 0,
            "m_CustomColors": {"m_SerializableColors": []},
            "m_TextureType": 0,
            "m_NormalMapSpace": 0,
            "m_EnableGlobalMipBias": True,
            "m_MipSamplingMode": 0,
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.Vector4MaterialSlot", "m_ObjectId": sample_rgba_id,
            "m_Id": 0, "m_DisplayName": "RGBA", "m_SlotType": 1, "m_Hidden": False, "m_ShaderOutputName": "RGBA",
            "m_StageCapability": 2, "m_Value": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0},
            "m_DefaultValue": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0}, "m_Labels": [],
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.Texture2DInputMaterialSlot", "m_ObjectId": sample_tex_in_id,
            "m_Id": 1, "m_DisplayName": "Texture", "m_SlotType": 0, "m_Hidden": False, "m_ShaderOutputName": "Texture",
            "m_StageCapability": 3, "m_BareResource": False, "m_Texture": {"m_SerializedTexture": "", "m_Guid": ""},
            "m_DefaultType": 0,
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.UVMaterialSlot", "m_ObjectId": sample_uv_id,
            "m_Id": 2, "m_DisplayName": "UV", "m_SlotType": 0, "m_Hidden": False, "m_ShaderOutputName": "UV",
            "m_StageCapability": 3, "m_Value": {"x": 0.0, "y": 0.0}, "m_DefaultValue": {"x": 0.0, "y": 0.0},
            "m_Labels": ["X", "Y"], "m_Channel": 0,
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.SamplerStateMaterialSlot", "m_ObjectId": sample_sampler_id,
            "m_Id": 3, "m_DisplayName": "Sampler", "m_SlotType": 0, "m_Hidden": False, "m_ShaderOutputName": "Sampler",
            "m_StageCapability": 3, "m_BareResource": False,
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.Vector1MaterialSlot", "m_ObjectId": sample_r_id,
            "m_Id": 4, "m_DisplayName": "R", "m_SlotType": 1, "m_Hidden": False, "m_ShaderOutputName": "R",
            "m_StageCapability": 2, "m_Value": 0.0, "m_DefaultValue": 0.0, "m_Labels": ["X"],
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.Vector1MaterialSlot", "m_ObjectId": sample_g_id,
            "m_Id": 5, "m_DisplayName": "G", "m_SlotType": 1, "m_Hidden": False, "m_ShaderOutputName": "G",
            "m_StageCapability": 2, "m_Value": 0.0, "m_DefaultValue": 0.0, "m_Labels": ["X"],
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.Vector1MaterialSlot", "m_ObjectId": sample_b_id,
            "m_Id": 6, "m_DisplayName": "B", "m_SlotType": 1, "m_Hidden": False, "m_ShaderOutputName": "B",
            "m_StageCapability": 2, "m_Value": 0.0, "m_DefaultValue": 0.0, "m_Labels": ["X"],
        },
        {
            "m_SGVersion": 0, "m_Type": "UnityEditor.ShaderGraph.Vector1MaterialSlot", "m_ObjectId": sample_a_id,
            "m_Id": 7, "m_DisplayName": "A", "m_SlotType": 1, "m_Hidden": False, "m_ShaderOutputName": "A",
            "m_StageCapability": 2, "m_Value": 0.0, "m_DefaultValue": 0.0, "m_Labels": ["X"],
        },
    ]

    text = text.rstrip("\n") + "\n\n" + "\n\n".join(_block(b) for b in new_blocks) + "\n"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"  generated {OUT_PATH.relative_to(UNITY_PROJECT)} (property '{PROPERTY_REFERENCE_NAME}', Shadow Matte enabled)")


if __name__ == "__main__":
    generate()
