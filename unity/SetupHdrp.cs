// Switches the project to HDRP for master-replica authoring. Menu: Amakeng > Setup HDRP.
// Idempotent: safe to re-run - reuses/creates the pipeline asset and global settings by a
// fixed path, and replaces its own "[GEN] Atmosphere" volume each run.
//
// HDRP 17.3 API discoveries vs. the task brief's skeleton (all confirmed live against this
// project via Unity_RunCommand before being written here - see task-1-report.md):
//   1. `HDRenderPipelineGlobalSettings` is an `internal` class in this HDRP version (no
//      `public` modifier) - it cannot be named as a type in Assembly-CSharp-Editor code
//      (CS0122). Its own `Ensure()` helper is also `internal`. Worked around by operating
//      through the public base class `RenderPipelineGlobalSettings` everywhere, discovering
//      the concrete asset via `AssetDatabase.FindAssets("t:HDRenderPipelineGlobalSettings")`
//      (the "t:TypeName" search resolves by name even for a type this assembly can't see)
//      and creating one, if none exists, via the string overload
//      `ScriptableObject.CreateInstance("HDRenderPipelineGlobalSettings")` (also name-based,
//      no compile-time type reference needed).
//   2. The public API to wire a global settings asset to a render pipeline from an editor
//      script is `UnityEditor.Rendering.EditorGraphicsSettings
//      .SetRenderPipelineGlobalSettingsAsset<HDRenderPipeline>(RenderPipelineGlobalSettings)`
//      (namespace `UnityEditor.Rendering`, not `UnityEditor.Rendering.HighDefinition`).
//   3. `SkyType.Gradient`, `GradientSky`, `VisualEnvironment.skyType`, `Fog.enabled` /
//      `Fog.meanFreePath`, and `Exposure.mode` / `Exposure.fixedExposure` all matched the
//      brief's skeleton exactly - no adaptation needed there.
//   4. `HDAdditionalLightData` is a plain `MonoBehaviour` add-on; light intensity/unit live
//      on the stock `UnityEngine.Light` component itself in this Unity version
//      (`light.lightUnit`, `light.intensity`), not on HDAdditionalLightData.
//   5. `QualitySettings.SetRenderPipelineAssetAt(int, RenderPipelineAsset)` - the brief
//      skeleton's per-quality-level setter - does not exist in this Unity version (CS0117 on
//      a live compile attempt); only the read-only `GetRenderPipelineAssetAt(int)` remains.
//      The writable path is the settable `QualitySettings.renderPipeline` property, which
//      targets whichever level is currently active - so each level is set via
//      `QualitySettings.SetQualityLevel(i, false)` before assigning it.
//   6. Not in the brief's skeleton at all: this project's Player Settings were still on
//      Gamma color space (a URP/Built-in-era default), which HDRP refuses to render in
//      ("High Definition Render Pipeline doesn't support Gamma mode", logged as a real
//      Error every frame on the first live rebuild-chain run). Normally HDRP's own "HDRP
//      Wizard" flips this interactively the first time it's opened; since this setup is
//      headless, `Run()` now does it explicitly.
//   7. Also not in the skeleton: HDRP's `Tonemapping` volume component defaults to
//      `TonemappingMode.None` (confirmed in package source) - with no highlight roll-off at
//      all, a physically-lit scene at 100,000 lux blows straight through to solid-white/
//      posterized-black clipping (confirmed live in the first captures this round). Added
//      `Tonemapping(ACES)` to the atmosphere volume.
//   8. `GradientSky` (the brief's stated robust default) turned out not to pair with a
//      Lux-unit physical sun: its top/middle/bottom colours are artist-authored,
//      display-ready values meant to look right around EV100≈0, not radiometric values in
//      the same units as a 100,000 lux directional light. At the ~15 EV100 that light needs
//      to not blow out, GradientSky's colours get divided down by roughly 2^15 and render
//      solid black (confirmed live - only the exempt HDRP/Unlit road overlay stayed
//      visible). Switched to `PhysicallyBasedSky` (`SkyType.PhysicallyBased`,
//      `PhysicallyBasedSkyModel.EarthAdvanced` default), which the brief explicitly allowed
//      "if it compiles/behaves" - it is calibrated in the same physical units as the sun, so
//      one exposure setting now works for both.
using UnityEditor;
using UnityEditor.Rendering;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Amakeng
{
    public static class SetupHdrp
    {
        const string Dir = "Assets/Amakeng/HDRP";

        // Photographic pairing (brief §1): sunny-daylight directional sun in physical Lux,
        // matched by a fixed EV100 exposure so the road mosaic / SeedMesh foliage read at a
        // normal midtone brightness instead of blown out or crushed. Tuned empirically
        // against the hdrp_s460/530/640 captures (see task-1-report.md) - both live here so
        // DressSlice.SetAtmosphere (which sets the sun's NOAA rotation on every Dress() run)
        // can reuse the same intensity without duplicating the tuning rationale.
        public const float SunIntensityLux = 100000f;
        // Tuned empirically against the hdrp_s460/530/640 captures once PhysicallyBasedSky +
        // ACES tonemapping were both in place (discoveries #7/#8): 14.5 read plausible but
        // notably duskier/dimmer than a 15:24 equatorial sun should look; 13.0 brightens the
        // midtones (foliage, gravel) closer to a bright-daylight read while ACES still keeps
        // the sky/highlights from clipping.
        public const float FixedExposureEv100 = 13.0f;

        // Task 4 grading round 3 (final; see task-4-report.md): under Linear/HDRP + ACES the
        // untuned scene read with two opposite defects at once vs. the video reference frames
        // (ref_s475/546/650.png) - road surface over-bright/washed (baseline delta vs. ref up
        // to +31-47% per channel) while the canopy/rock foliage masses read far too dark
        // (baseline delta down to -65%). Both symptoms share one cause: the physically-lit
        // scene's dynamic range is wider than the reference photography's, so a single global
        // contrast reduction (ColorAdjustments.contrast) compresses both ends at once - it was
        // the single highest-leverage knob, more effective than Exposure alone (which moves
        // both problems the same direction instead of squeezing them together). Chosen over 3
        // empirically-measured rounds (grade_r0..r4_s*.png + grade_compare.py mean-RGB deltas
        // in this report's folder): contrast -45 + saturation +18 (compensates for the
        // flatter, less vivid look contrast reduction alone produces) + a slightly warm
        // colorFilter (cuts the ambient-sky blue cast Physically Based Sky adds to shadowed
        // foliage) + a small +0.15 EV postExposure trim. Final deltas: road within ~10-20% per
        // channel of reference at 2 of 3 stations (s475/s546), foliage no longer lime/red-
        // shifted (hue corrected) though still under-bright at one heavily-shadowed canopy
        // station (s650) - see task-4-report.md for the full per-round numbers and the
        // decision to stop at round 3 rather than keep chasing a single outlier station.
        public const float GradeContrast = -45f;
        public const float GradeSaturation = 18f;
        public static readonly Color GradeColorFilter = new Color(1.05f, 1.0f, 0.90f);
        public const float GradePostExposureEv = 0.15f;

        [MenuItem("Amakeng/Setup HDRP")]
        public static void Run()
        {
            // Discovery #6 (live, first real rebuild-chain run): HDRP refuses to render in
            // Gamma color space ("High Definition Render Pipeline doesn't support Gamma
            // mode" - logged as an Error every frame) and this project's Player Settings were
            // still on Gamma (a URP/Built-in-era default; HDRP's own "HDRP Wizard" normally
            // flips this for you interactively the first time you open it, which this
            // headless setup never does). Not part of the brief's skeleton at all - set here
            // so Setup HDRP is a complete, one-shot activation.
            if (PlayerSettings.colorSpace != ColorSpace.Linear)
            {
                PlayerSettings.colorSpace = ColorSpace.Linear;
                Debug.Log("[SetupHdrp] Run: PlayerSettings.colorSpace was Gamma (HDRP requires " +
                    "Linear) - set to Linear.");
            }

            if (!AssetDatabase.IsValidFolder(Dir))
                AssetDatabase.CreateFolder("Assets/Amakeng", "HDRP");

            var asset = AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>(Dir + "/MasterHDRP.asset");
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<HDRenderPipelineAsset>();
                AssetDatabase.CreateAsset(asset, Dir + "/MasterHDRP.asset");
            }

            EnsureGlobalSettings();

            GraphicsSettings.defaultRenderPipeline = asset;
            // Discovery: QualitySettings.SetRenderPipelineAssetAt (the brief skeleton's API)
            // does not exist in this Unity version (6000.3.19f1) - confirmed via CS0117 on a
            // live compile attempt. The per-quality-level override is set by switching to
            // each level and assigning the settable QualitySettings.renderPipeline property
            // instead (QualitySettings.GetRenderPipelineAssetAt(i) is the only indexed
            // accessor that still exists, and it is read-only).
            int originalLevel = QualitySettings.GetQualityLevel();
            for (int i = 0; i < QualitySettings.names.Length; i++)
            {
                QualitySettings.SetQualityLevel(i, false);
                QualitySettings.renderPipeline = asset;
            }
            QualitySettings.SetQualityLevel(originalLevel, false);

            BuildAtmosphereVolume();
            EnsureSunForHdrp();

            AssetDatabase.SaveAssets();
            Debug.Log("[SetupHdrp] HDRP pipeline assigned (all " + QualitySettings.names.Length +
                " quality level(s)) + atmosphere volume + sun created/updated.");
        }

        // See file header, discovery #1/#2.
        static void EnsureGlobalSettings()
        {
            var existing = GraphicsSettings.GetSettingsForRenderPipeline<HDRenderPipeline>();
            if (existing != null) return;

            RenderPipelineGlobalSettings asset = null;
            var guids = AssetDatabase.FindAssets("t:HDRenderPipelineGlobalSettings");
            if (guids.Length > 0)
                asset = AssetDatabase.LoadAssetAtPath<RenderPipelineGlobalSettings>(AssetDatabase.GUIDToAssetPath(guids[0]));

            if (asset == null)
            {
                var created = ScriptableObject.CreateInstance("HDRenderPipelineGlobalSettings") as RenderPipelineGlobalSettings;
                AssetDatabase.CreateAsset(created, Dir + "/HDRenderPipelineGlobalSettings.asset");
                asset = created;
                Debug.Log("[SetupHdrp] EnsureGlobalSettings: created new HDRP global settings asset at " + Dir + ".");
            }
            else
            {
                Debug.Log("[SetupHdrp] EnsureGlobalSettings: found existing HDRP global settings asset at " +
                    AssetDatabase.GetAssetPath(asset) + ".");
            }

            EditorGraphicsSettings.SetRenderPipelineGlobalSettingsAsset<HDRenderPipeline>(asset);
        }

        // Idempotent [GEN] Atmosphere volume: sky (PhysicallyBasedSky - see discovery #8
        // below for why GradientSky was tried first and swapped out), Fog (mean free path
        // tuned for the ~250 m visibility the old RenderSettings.fogDensity=0.004 exp2 fog
        // gave), fixed Exposure paired with the sun's Lux intensity, ACES Tonemapping
        // (discovery #7), and a neutral ColorAdjustments placeholder for Task 4 to tune.
        static void BuildAtmosphereVolume()
        {
            var old = GameObject.Find("[GEN] Atmosphere");
            if (old != null) Object.DestroyImmediate(old);

            var go = new GameObject("[GEN] Atmosphere");
            var vol = go.AddComponent<Volume>();
            vol.isGlobal = true;

            AssetDatabase.DeleteAsset(Dir + "/Atmosphere.asset");
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            AssetDatabase.CreateAsset(profile, Dir + "/Atmosphere.asset");
            vol.sharedProfile = profile;

            // Discovery #8 (live, this round): GradientSky's top/middle/bottom colours are
            // artist-authored display-ready values, designed to look right around EV100≈0 -
            // they are NOT expressed in the same physical radiometric units as a Lux-unit
            // directional light. Paired with the ~15 EV100 a 100,000 lux physical sun needs
            // (so Lit/Shader-Graph-lit surfaces don't blow out), the exposure post-process
            // divides GradientSky's colours down by roughly 2^15 - confirmed live: the sky
            // (and everything else lit by the directional light) rendered solid black, while
            // only the road overlay - HDRP/Unlit, exempt from the light/exposure interaction
            // because it carries its own baked brightness - still read correctly. Switched to
            // `PhysicallyBasedSky` (the brief's explicitly-allowed alternative, "if it
            // compiles/behaves"): its EarthAdvanced model is calibrated in the same physical
            // units as the Lux-unit sun, so it and the Lit-shaded scene share one consistent
            // exposure instead of needing two incompatible ones.
            var vs = profile.Add<VisualEnvironment>(true);
            vs.skyType.Override((int)SkyType.PhysicallyBased);

            var sky = profile.Add<PhysicallyBasedSky>(true);

            var fog = profile.Add<Fog>(true);
            fog.enabled.Override(true);
            fog.meanFreePath.Override(250f);
            fog.baseHeight.Override(30f);
            fog.maximumHeight.Override(80f);

            var exp = profile.Add<Exposure>(true);
            exp.mode.Override(ExposureMode.Fixed);
            exp.fixedExposure.Override(FixedExposureEv100);

            var color = profile.Add<ColorAdjustments>(true);
            // Task 4 grading (see constants above + task-4-report.md): baked in as the new
            // defaults so a future SetupHdrp.Run() (which deletes/recreates this profile every
            // time - see BuildAtmosphereVolume's own doc comment) does not silently wipe the
            // grading tuning back to neutral.
            color.contrast.Override(GradeContrast);
            color.saturation.Override(GradeSaturation);
            color.colorFilter.Override(GradeColorFilter);
            color.postExposure.Override(GradePostExposureEv);

            // Not in the brief's skeleton, but required: HDRP's Tonemapping volume component
            // defaults to TonemappingMode.None (confirmed in package source), i.e. no
            // highlight roll-off at all - a physically-lit scene (100,000 lux sun) renders
            // with values far above 1.0 and hard-clips to solid white/posterized silhouettes
            // wherever it does (confirmed live in the first hdrp_s460/530/640 captures this
            // round - see task-1-report.md). ACES is HDRP's standard filmic default.
            var tone = profile.Add<Tonemapping>(true);
            tone.mode.Override(TonemappingMode.ACES);

            // VolumeProfile.Add() (see package source, Runtime/Volume/VolumeProfile.cs) only
            // appends to the in-memory `components` list - it does not call
            // AssetDatabase.AddObjectToAsset itself, so every component added above must be
            // registered as a sub-asset explicitly or it will not survive being saved/reloaded
            // (the brief's skeleton only registered vs/sky/fog/exp and omitted the
            // ColorAdjustments instance entirely - fixed here by capturing it into `color`).
            AssetDatabase.AddObjectToAsset(vs, profile);
            AssetDatabase.AddObjectToAsset(sky, profile);
            AssetDatabase.AddObjectToAsset(fog, profile);
            AssetDatabase.AddObjectToAsset(exp, profile);
            AssetDatabase.AddObjectToAsset(color, profile);
            AssetDatabase.AddObjectToAsset(tone, profile);
            AssetDatabase.SaveAssets();

            Debug.Log("[SetupHdrp] BuildAtmosphereVolume: PhysicallyBasedSky + Fog(meanFreePath=250) + " +
                "Exposure(Fixed, " + FixedExposureEv100 + " EV100) + ColorAdjustments(Task 4 grading: contrast=" +
                GradeContrast + " saturation=" + GradeSaturation + " colorFilter=" + GradeColorFilter +
                " postExposure=" + GradePostExposureEv + ") + Tonemapping(ACES).");
        }

        // Discovery #4 (see file header): intensity/unit live on the stock Light component;
        // HDAdditionalLightData just needs to be present. Rotation (NOAA sun position) is
        // owned by DressSlice.SetAtmosphere() and is left untouched here.
        static void EnsureSunForHdrp()
        {
            var sunGo = GameObject.Find("Directional Light");
            if (sunGo == null) return; // DressSlice.SetAtmosphere creates it later if absent
            var light = sunGo.GetComponent<Light>();
            if (light == null) return;
            if (sunGo.GetComponent<HDAdditionalLightData>() == null)
                sunGo.AddComponent<HDAdditionalLightData>();
            light.lightUnit = LightUnit.Lux;
            light.intensity = SunIntensityLux;
            Debug.Log("[SetupHdrp] EnsureSunForHdrp: HDAdditionalLightData ensured, " +
                SunIntensityLux + " lux (paired with fixed exposure " + FixedExposureEv100 + " EV100).");
        }
    }
}
