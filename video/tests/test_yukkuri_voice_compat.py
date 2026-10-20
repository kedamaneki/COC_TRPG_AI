import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from video_agent.voice.yukkuri_voice_compat import (CANDIDATE_IDS, EXACT_SOURCE,
    PLAYBACK_RATE_SEMANTICS, SOURCE_RUNTIME_SHA256, generate_compatibility_fixtures,
    playback_filter, validate_portable_fixture_manifest, validate_runtime_fixtures,
    validate_source_profiles)


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


class YMM4VoiceCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice_document = json.loads((ROOT / "config/voice_profiles.json").read_text(encoding="utf-8"))
        cls.profiles = {item["voice_profile_id"]: item for item in cls.voice_document["profiles"]}
        cls.characters = json.loads((ROOT / "config/character_registry.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            (REPO / "fixtures/ymm4_voice_compat/fixture_manifest.json").read_text(encoding="utf-8")
        )
        cls.temporary = tempfile.TemporaryDirectory(prefix="ymm4_voice_compat_")
        cls.runtime_root = Path(cls.temporary.name)
        cls.generated = generate_compatibility_fixtures(ROOT, cls.runtime_root, cls.profiles)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_source_authority_values(self):
        self.assertEqual(validate_source_profiles(self.profiles), [])
        self.assertEqual(SOURCE_RUNTIME_SHA256, "50d4871eb5853e6e6f74f999c9017e4aea80b162c959e3ce9aab78f874459e4b")

    def test_exact_candidates_keep_speed_and_playback_separate(self):
        for character_id, candidate_id in CANDIDATE_IDS.items():
            candidate = self.profiles[candidate_id]
            source = EXACT_SOURCE[character_id]
            self.assertEqual(candidate["synthesis_speed"], source["synthesis_speed"])
            self.assertEqual(candidate["playback_rate_percent"], source["playback_rate_percent"])
            self.assertEqual(candidate["source_volume_percent"], 50.0)
            expected_status = "TUNING_REFERENCE" if character_id == "sakuya" else "HUMAN_REVIEW_CANDIDATE"
            self.assertEqual(candidate["usage_status"], expected_status)
            self.assertFalse(candidate["auto_use"])

    def test_playback_semantics_are_pitch_and_speed_coupled(self):
        self.assertEqual(PLAYBACK_RATE_SEMANTICS, "PITCH_AND_SPEED_COUPLED")
        sakuya = self.profiles["ymm_exact_sakuya_v1"]
        value = playback_filter(sakuya, 8000)
        self.assertIn("asetrate=9600", value)
        self.assertIn("aresample=48000", value)
        self.assertNotIn("atempo", value)

    def test_baselines_are_preserved(self):
        expected = {
            "m1_aq_f1": ("f1", 110, 100, 100, 0.15),
            "aq_marisa_default": ("f2", 105, 100, 100, 0.15),
            "aq_kp_sakuya_v21": ("f1", 102, 92, 100, 0.18),
        }
        for profile_id, values in expected.items():
            profile = self.profiles[profile_id]
            self.assertEqual((profile["voice_type"], profile["reading_speed"], profile["pitch_playback"],
                              profile["volume"], profile["post_silence_sec"]), values)

    def test_active_mapping_uses_human_approved_sakuya_selection(self):
        characters = {item["character_id"]: item for item in self.characters["characters"]}
        self.assertEqual(characters["reimu"]["voice_profile_id"], "m1_aq_f1")
        self.assertEqual(characters["marisa"]["voice_profile_id"], "aq_marisa_default")
        self.assertEqual(characters["sakuya"]["voice_profile_id"], "sakuya_tune_110_v1")

    def test_fixture_rendered_and_measured(self):
        self.assertEqual(self.manifest["fixture_id"], "FIXTURE_YMM4_VOICE_COMPAT_001")
        self.assertEqual(self.manifest["status"], "PASS")
        self.assertEqual(validate_portable_fixture_manifest(self.manifest), [])
        self.assertEqual(len(self.generated), 3)
        self.assertEqual(
            validate_runtime_fixtures(
                self.generated,
                self.manifest,
                require_historical_sha=self.manifest["bit_exact_policy"] == "DETERMINISTIC_PASS",
            ),
            [],
        )
        generated_count = 0
        for record in self.generated:
            for variant in ("baseline", "exact"):
                measurement = record[variant]["measurement"]
                path = Path(measurement["path"])
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)
                self.assertTrue(path.is_relative_to(self.runtime_root))
                self.assertEqual(measurement["sample_rate"], 48000)
                self.assertEqual(measurement["channels"], 1)
                self.assertEqual(measurement["sample_width_bytes"], 2)
                self.assertEqual(measurement["status"], "PASS")
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), measurement["sha256"])
                generated_count += 1
        self.assertEqual(generated_count, 6)

    def test_manifest_rejects_machine_specific_absolute_path(self):
        invalid = copy.deepcopy(self.manifest)
        invalid["records"][0]["baseline"]["measurement"]["relative_path"] = "".join(
            ("V", ":", "\\", "fixtures", "\\", "voice.wav")
        )
        self.assertTrue(any(error.startswith("ABSOLUTE_PATH:")
                            for error in validate_portable_fixture_manifest(invalid)))

    def test_runtime_generation_fails_closed_without_voice_runtime(self):
        with mock.patch.dict(os.environ, {key: value for key, value in os.environ.items()
                                         if key != "VOICE_RUNTIME_PATH"}, clear=True):
            with self.assertRaisesRegex(ValueError, "VOICE_RUNTIME_PATH is required"):
                generate_compatibility_fixtures(ROOT, self.runtime_root / "missing-runtime", self.profiles)

    def test_generated_contract_rejects_hash_mismatch(self):
        invalid = copy.deepcopy(self.generated)
        invalid[0]["baseline"]["measurement"]["sha256"] = "0" * 64
        self.assertIn(
            "GENERATED_SHA_MISMATCH:reimu:baseline",
            validate_runtime_fixtures(invalid, self.manifest, require_historical_sha=False),
        )


if __name__ == "__main__":
    unittest.main()
