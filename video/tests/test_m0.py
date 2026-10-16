import copy
import json
import tempfile
import unittest
from pathlib import Path

from video_agent.assets import load_asset_manifest
from video_agent.characters import load_profiles
from video_agent.common.io import stable_digest
from video_agent.importer import import_evaluation_session
from video_agent.normalizer import normalize_session
from video_agent.pipeline import build_project
from video_agent.validation import validate_all, validate_manifest, validate_profiles, validate_session


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = Path(r"F:\制作物\その3\evaluation-v2\seed_2101_goal_completion_sync_fix")


class M0UnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SAMPLE.is_dir():
            raise unittest.SkipTest("formal sample session is unavailable")
        cls.source = import_evaluation_session(SAMPLE)
        cls.session = normalize_session(cls.source)
        cls.profiles = load_profiles(ROOT / "config")
        cls.manifest = load_asset_manifest(ROOT / "assets" / "manifest.json")

    def test_session_import(self):
        self.assertEqual(len(self.source["unified_events"]), 295)
        self.assertEqual(len(self.source["session_events"]), 383)

    def test_normalized_schema_validation(self):
        self.assertFalse([x for x in validate_session(self.session) if x["level"] == "ERROR"])

    def test_dialogue_mapping(self):
        self.assertTrue(any(x["event_type"] == "DIALOGUE" and x["text"] for x in self.session["events"]))

    def test_kp_mapping(self):
        self.assertTrue(any(x["event_type"] == "KP_DESCRIPTION" and x["speaker_id"] == "kp" for x in self.session["events"]))

    def test_dice_mapping(self):
        self.assertTrue(any(x["dice"] and x["dice"]["roll"] is not None for x in self.session["events"]))

    def test_san_mapping_capability(self):
        record = {
            "event_id": "san", "event_type": "SAN_RESULT",
            "san": {"kind": "ADJUDICATION", "before": 50, "after": 47, "loss": 3},
        }
        changed = copy.deepcopy(self.source)
        changed["unified_events"] = [record]
        changed["session_events"] = []
        san = normalize_session(changed)["events"][0]["san"]
        self.assertEqual(san["san_loss"], 3)

    def test_combat_mapping(self):
        combat = [x for x in self.session["events"] if x["event_type"] in {"COMBAT_START", "COMBAT_ACTION", "COMBAT_END"}]
        self.assertTrue(combat)
        self.assertTrue(any(x["combat"] for x in combat))

    def test_provenance(self):
        self.assertTrue(all(x["source_event_ids"] for x in self.session["events"]))
        self.assertEqual(len(self.session["events"]), 678)

    def test_major_dialogue_text_is_not_dropped(self):
        source_text = [str(x.get("text") or "") for x in self.source["session_events"]]
        normalized_text = [
            x["text"] for x in self.session["events"]
            if x["metadata"].get("source_stream") == "session_log"
        ]
        self.assertEqual(normalized_text, source_text)

    def test_unknown_field_handling(self):
        changed = copy.deepcopy(self.source)
        changed["unified_events"] = [{"event_id": "u1", "future_field": {"kept": True}}]
        changed["session_events"] = []
        event = normalize_session(changed)["events"][0]
        self.assertTrue(event["metadata"]["source_payload"]["future_field"]["kept"])

    def test_invalid_event_handling(self):
        changed = copy.deepcopy(self.session)
        changed["events"][1]["event_id"] = changed["events"][0]["event_id"]
        self.assertIn("DUPLICATE_EVENT_ID", {x["code"] for x in validate_session(changed)})

    def test_profile_loading(self):
        self.assertGreaterEqual(len(self.profiles["characters"]), 3)
        self.assertFalse([x for x in validate_profiles(self.profiles) if x["level"] == "ERROR"])

    def test_subtitle_outline_loading(self):
        self.assertTrue(all(x.get("outlines") for x in self.profiles["subtitles"]))
        self.assertGreaterEqual(len(self.profiles["subtitles"][0]["outlines"]), 2)

    def test_asset_manifest_validation(self):
        issues = validate_manifest(self.manifest)
        self.assertFalse([x for x in issues if x["level"] == "ERROR"])
        self.assertTrue(any(x["code"] == "UNKNOWN_ASSET_LICENSE" for x in issues))

    def test_deterministic_output(self):
        self.assertEqual(stable_digest(normalize_session(self.source)), stable_digest(normalize_session(self.source)))

    def test_missing_source_event_is_error(self):
        changed = copy.deepcopy(self.session)
        changed["events"][0]["source_event_ids"] = []
        self.assertIn("MISSING_SOURCE_EVENT_ID", {x["code"] for x in validate_session(changed)})

    def test_invalid_profile_reference(self):
        changed = copy.deepcopy(self.profiles)
        changed["characters"][0]["voice_profile_id"] = "missing"
        self.assertIn("INVALID_PROFILE_REFERENCE", {x["code"] for x in validate_profiles(changed)})


class M0IntegrationTests(unittest.TestCase):
    def test_formal_session_conversion(self):
        if not SAMPLE.is_dir():
            self.skipTest("formal sample session is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            session, provenance, validation = build_project(SAMPLE, tmp, ROOT)
            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(provenance["source_traceability_rate"], 1.0)
            self.assertEqual(provenance["dropped_events"], 0)
            self.assertTrue(any(x["event_type"] == "ENDING" for x in session["events"]))
            self.assertTrue(any(x["event_type"] == "LOCATION_CHANGE" for x in session["events"]))
            self.assertTrue(any(x["event_type"].startswith("COMBAT_") for x in session["events"]))
            self.assertTrue((Path(tmp) / "normalized_session.json").is_file())


if __name__ == "__main__":
    unittest.main()
