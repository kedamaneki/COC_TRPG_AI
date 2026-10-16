import json
import tempfile
import unittest
from pathlib import Path

from video_agent.common.io import read_json, stable_digest
from video_agent.rendering.assets import compose_frame, create_test_assets
from video_agent.rendering.pipeline import (
    STATES, apply_dictionary, build_real_lines, build_synthetic_lines, timeline_from_lines,
)
from video_agent.rendering.subtitles import ass_color, ass_time, build_ass, wrap_text
from video_agent.voice.engines import VoiceEngine, VoiceResult, voice_cache_key


ROOT = Path(__file__).resolve().parents[1]


class DummyVoiceEngine(VoiceEngine):
    engine_name = "DUMMY"

    def synthesize(self, text, profile):
        return VoiceResult(self.cache_dir / "dummy.wav", 1.0, "key", self.engine_name, "1", False)


class M1UnitTests(unittest.TestCase):
    def test_aquestalk_profile_loading(self):
        profiles = read_json(ROOT / "config/voices/m1_profiles.json")
        aq = next(item for item in profiles if item["engine"] == "AQUESTALK")
        self.assertEqual(aq["voice_type"], "f1")
        self.assertGreater(aq["reading_speed"], 0)

    def test_voicevox_profile_loading(self):
        profiles = read_json(ROOT / "config/voices/m1_profiles.json")
        vv = [item for item in profiles if item["engine"] == "VOICEVOX"]
        self.assertEqual({item["style_id"] for item in vv}, {3, 11})

    def test_voice_cache_key_deterministic(self):
        profile = {"style_id": 3, "speed": 1.0}
        self.assertEqual(voice_cache_key("X", profile, "abc"), voice_cache_key("X", profile, "abc"))

    def test_voice_cache_key_changes_with_settings(self):
        self.assertNotEqual(voice_cache_key("X", {"speed": 1}, "abc"), voice_cache_key("X", {"speed": 2}, "abc"))

    def test_voice_engine_contract(self):
        path = ROOT / "cache/test_dummy"
        result = DummyVoiceEngine(path).synthesize("x", {})
        self.assertEqual(result.engine, "DUMMY")

    def test_script_line_generation(self):
        spec = read_json(ROOT / "projects/m1_synthetic/project.json")
        lines = build_synthetic_lines(spec)
        self.assertEqual(lines[0]["line_id"], "line_001")
        self.assertEqual(len(lines), 6)

    def test_real_script_preserves_text_and_provenance(self):
        spec = read_json(ROOT / "projects/m1_real_session/project.json")
        session = read_json(ROOT / spec["normalized_session"])
        lines = build_real_lines(spec, session)
        event = next(item for item in session["events"] if item["event_id"] == spec["event_lines"][0]["event_id"])
        self.assertEqual(lines[0]["text"], event["text"])
        self.assertIn(event["event_id"], lines[0]["source_event_ids"])

    def test_pronunciation_dictionary(self):
        self.assertEqual(apply_dictionary("SANとKP", {"SAN": "サン", "KP": "ケーピー"}), "サンとケーピー")

    def test_subtitle_profile_resolution(self):
        profiles = read_json(ROOT / "config/subtitles/defaults.json")
        self.assertIn("subtitle_kp", {item["subtitle_profile_id"] for item in profiles})

    def test_multi_outline_config(self):
        profiles = read_json(ROOT / "config/subtitles/defaults.json")
        self.assertGreaterEqual(len(profiles[0]["outlines"]), 2)

    def test_ass_helpers(self):
        self.assertEqual(ass_time(61.23), "0:01:01.23")
        self.assertEqual(ass_color("#FF0000"), "&H000000FF")

    def test_subtitle_wrap(self):
        wrapped, overflow = wrap_text("あ" * 68)
        self.assertFalse(overflow)
        self.assertIn("\\N", wrapped)

    def test_subtitle_overflow_detection(self):
        _, overflow = wrap_text("あ" * 137)
        self.assertTrue(overflow)

    def test_ass_contains_multi_outline_layers(self):
        profiles = {item["subtitle_profile_id"]: item for item in read_json(ROOT / "config/subtitles/defaults.json")}
        clips = [{"clip_id":"c","start_sec":0,"duration_sec":1,"subtitle_text":"テスト",
                  "subtitle_profile_id":"subtitle_kp","speaker_name":"KP","overlay":None}]
        temp_root = ROOT / "cache/test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            path = Path(directory) / "x.ass"
            self.assertEqual(build_ass(path, clips, profiles), [])
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("BodyOuter", text)
            self.assertIn("BodyInner", text)

    def _timeline(self):
        lines = [
            {"line_id":"line_001","source_event_ids":["e1"],"speaker_id":"pc_01","text":"a",
             "subtitle_profile_id":"s","portrait_asset_id":"p","dice":None},
            {"line_id":"line_002","source_event_ids":["e2"],"speaker_id":"pc_02","text":"b",
             "subtitle_profile_id":"s","portrait_asset_id":"q",
             "dice":{"skill_name":"目星","target_value":70,"roll":42,"result":"成功"}},
        ]
        audio = {"line_001":{"duration_sec":1,"project_path":"a.wav","engine":"AQUESTALK"},
                 "line_002":{"duration_sec":2,"project_path":"b.wav","engine":"VOICEVOX"}}
        chars = {"pc_01":{"display_name":"A"},"pc_02":{"display_name":"B"}}
        return timeline_from_lines(lines, audio, chars, 0.2, "bg")

    def test_timeline_duration(self):
        self.assertEqual(self._timeline()["duration_sec"], 3.4)

    def test_clip_ordering(self):
        timeline = self._timeline()
        self.assertLess(timeline["clips"][0]["start_sec"], timeline["clips"][1]["start_sec"])

    def test_dice_overlay_mapping(self):
        overlay = self._timeline()["clips"][1]["overlay"]
        self.assertEqual((overlay["roll"], overlay["result"]), (42, "成功"))

    def test_timeline_determinism(self):
        self.assertEqual(stable_digest(self._timeline()), stable_digest(self._timeline()))

    def test_resume_states(self):
        for state in ("VOICE_READY", "TIMELINE_READY", "PAUSED_RESUMABLE", "BLOCKED_VOICE_ENGINE"):
            self.assertIn(state, STATES)

    def test_asset_manifest_resolution(self):
        assets = {item["asset_id"]: item for item in read_json(ROOT / "assets/manifest.json")["assets"]}
        for asset_id in ("m1_background_fallback", "m1_portrait_aquestalk", "m1_portrait_voicevox"):
            self.assertEqual(assets[asset_id]["status"], "TEST_ONLY")

    def test_background_and_portrait_generation(self):
        assets = create_test_assets(ROOT / "assets/test_m1")
        self.assertTrue(all(path.exists() for path in assets.values()))

    def test_portrait_composition(self):
        assets = create_test_assets(ROOT / "assets/test_m1")
        output = ROOT / "cache/test_composed.png"
        compose_frame(assets["m1_background_fallback"], assets["m1_portrait_aquestalk"], output, "left")
        self.assertTrue(output.exists())

    def test_render_manifest_generation_outputs_exist(self):
        for name in ("m1_synthetic", "m1_real_session"):
            manifest = read_json(ROOT / f"projects/{name}/render_manifest.json")
            self.assertEqual(manifest["qa_status"], "PASS")
            self.assertTrue((ROOT / f"projects/{name}" / manifest["output"]).exists())


if __name__ == "__main__":
    unittest.main()
