import json
import unittest
from pathlib import Path

from video_agent.common.io import read_json
from video_agent.presentation.narrative import (
    _coverage,
    _detect_gaps,
    _generated_entry,
    _short_response_audit,
    apply_narrative_presentation,
    build_narrative_artifacts,
    conservative_world_narrative,
    semantic_class,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "corbitt_clear_001"


class NarrativeCausalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edited = read_json(PROJECT / "edited_script.json")
        cls.normalized = read_json(PROJECT / "normalized_session.json")
        cls.scenes = read_json(PROJECT / "scene_plan.json")["scenes"]
        cls.protected = read_json(PROJECT / "protected_events.json")
        cls.artifacts = build_narrative_artifacts(
            project=PROJECT,
            edited=cls.edited,
            normalized=cls.normalized,
            scenes=cls.scenes,
            protected=cls.protected,
        )

    def test_world_event_classification(self):
        event = {"speaker_id": "system", "event_type": "SCENARIO_EVENT",
                 "text": "ナイフが宙に浮き、攻撃してきた。"}
        self.assertEqual(semantic_class(event), "WORLD_EVENT")

    def test_technical_internal_suppression_classification(self):
        event = {"speaker_id": "pc_01", "event_type": "DIALOGUE",
                 "text": "[Combat Director] 戦闘外行動を拒否します。"}
        self.assertEqual(semantic_class(event), "TECHNICAL_INTERNAL")

    def test_world_event_is_presented_as_kp(self):
        generated = self.artifacts["plan"]["generated_entries"]
        self.assertTrue(generated)
        self.assertTrue(all(item["presentation_as"] == "KP" for item in generated))

    def test_san_cause_visible(self):
        check = self.artifacts["causality"]["checks"]["SAN_CAUSE_VISIBLE"]
        self.assertEqual(check["status"], "PASS")

    def test_combat_start_context_visible(self):
        self.assertEqual(self.artifacts["causality"]["checks"]["COMBAT_START_CONTEXT_VISIBLE"]["status"], "PASS")

    def test_combat_end_context_visible(self):
        self.assertEqual(self.artifacts["causality"]["checks"]["COMBAT_END_CONTEXT_VISIBLE"]["status"], "PASS")

    def test_ending_cause_visible(self):
        self.assertEqual(self.artifacts["causality"]["checks"]["ENDING_CAUSE_VISIBLE"]["status"], "PASS")

    def test_structured_fact_narrative_generation_is_conservative(self):
        event = next(event for event in self.normalized["events"]
                     if event["event_id"] == "norm:unified:000291")
        self.assertEqual(conservative_world_narrative(event), "ウォルター・コービットの遺体が破壊されました。")

    def test_ungrounded_generated_narrative_is_rejected(self):
        with self.assertRaises(AssertionError):
            _generated_entry(presentation_id="x", source_event_ids=[], scene_id="scene_x",
                             display_text="出来事が起きます。", narrative_role="ACTION",
                             visual_source_script_line_id="x", presentation_order=1.0)

    def test_source_insufficient_classification(self):
        normalized = [{"event_id": "evt", "event_type": "ENDING", "metadata": {}, "text": None}]
        protected = {"events": [{"event_id": "evt", "level": "HARD_PROTECTED", "reasons": ["ENDING"]}]}
        report = _coverage([], normalized, protected, [], [])
        self.assertEqual(report["items"][0]["coverage_status"], "SOURCE_INSUFFICIENT")
        self.assertEqual(report["status"], "PASS")

    def test_source_gameplay_gap_classification(self):
        gaps, _ = _detect_gaps(self.edited["lines"], self.normalized["events"])
        knife = next(item for item in gaps if item["gap_id"] == "knife_attack_resolution_missing")
        self.assertEqual(knife["classification"], "SOURCE_GAMEPLAY_GAP")

    def test_source_contradiction_detection(self):
        _, contradictions = _detect_gaps(self.edited["lines"], self.normalized["events"])
        ids = {item["contradiction_id"] for item in contradictions}
        self.assertIn("basement_door_open_closed", ids)
        self.assertIn("knife_rediscovery_state_inconsistency", ids)

    def test_duplicate_generated_narrative_prevention(self):
        subset = [line for line in self.edited["lines"] if line["scene_id"] in {"scene_052", "scene_053"}]
        presented = apply_narrative_presentation(subset, self.artifacts["plan"])
        ids = [line["script_line_id"] for line in presented]
        self.assertEqual(ids.count("narrative_final_battle_resolution"), 1)
        self.assertEqual(ids.count("narrative_final_battle_consequence"), 1)

    def test_local_reorder_places_world_event_before_san(self):
        subset = [line for line in self.edited["lines"] if line["scene_id"] == "scene_048"]
        presented = apply_narrative_presentation(subset, self.artifacts["plan"])
        ids = [line["script_line_id"] for line in presented]
        self.assertLess(ids.index("scene_048_script_009"), ids.index("scene_048_script_008"))
        self.assertGreater(ids.index("scene_048_script_009"), ids.index("scene_048_script_007"))

    def test_reorder_provenance_is_retained(self):
        subset = [line for line in self.edited["lines"] if line["scene_id"] == "scene_048"]
        presented = apply_narrative_presentation(subset, self.artifacts["plan"])
        item = next(line for line in presented if line["script_line_id"] == "scene_048_script_009")
        self.assertEqual(item["reorder_reason"], "WORLD_EVENT_BEFORE_SAN")
        self.assertIsNotNone(item["original_order"])

    def test_orphan_yes_detection(self):
        audit = _short_response_audit(self.edited["lines"])
        orphan = [item for item in audit if item["classification"] == "UNRESOLVED"]
        self.assertEqual(len(audit), 13)
        self.assertEqual(len(orphan), 4)

    def test_full_protected_narrative_coverage(self):
        report = self.artifacts["coverage"]
        self.assertEqual(report["PROTECTED_NARRATIVE_COVERAGE"], "PASS")
        self.assertEqual(report["full_scene_count"], 53)
        self.assertEqual(report["missing_count"], 0)

    def test_action_availability_and_combat_director_are_removed(self):
        presented = apply_narrative_presentation(self.edited["lines"], self.artifacts["plan"])
        text = "\n".join(str(line.get("display_text") or "") for line in presented).lower()
        self.assertNotIn("action availability", text)
        self.assertNotIn("試行権消費済み", text)
        self.assertNotIn("combat director", text)

    def test_required_narrative_artifacts_exist(self):
        for name in (
            "narrative_presentation_plan.json",
            "m3_narrative_coverage_report.json",
            "m3_source_gap_report.json",
            "m3_contradiction_report.json",
            "m3_causality_report.json",
        ):
            self.assertTrue((PROJECT / name).exists(), name)
        self.assertTrue((ROOT / "docs" / "M3_NARRATIVE_CAUSALITY_REPORT.md").exists())

    def test_narrative_previews_and_publishability_gate(self):
        self.assertTrue((PROJECT / "review" / "m3_knife_encounter_preview.mp4").exists())
        self.assertTrue((PROJECT / "review" / "m3_final_battle_preview.mp4").exists())
        qa = read_json(PROJECT / "presentation_qa_report.json")
        self.assertEqual(qa["status"], "PASS")
        self.assertFalse(qa["publishable"])
        self.assertEqual(qa["publishability"], "BLOCKED_SOURCE_GAPS")


if __name__ == "__main__":
    unittest.main()
