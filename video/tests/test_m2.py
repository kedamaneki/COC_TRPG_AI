import json
import tempfile
import unittest
from pathlib import Path

from video_agent.common.io import read_json
from video_agent.editing.contracts import (
    CONTENT_DECISIONS, PRESENTATION_MODES, TEXT_TREATMENTS, safe_default,
    validate_provider_decision,
)
from video_agent.editing.continuity import build_continuity_report
from video_agent.editing.editor import SceneEditCache, cleanup_text, edit_scene, overlay_for
from video_agent.editing.pipeline import editing_qa, estimate_line_duration, part_candidates
from video_agent.editing.protection import detect_protected_events, meaningful_state_changes
from video_agent.editing.segmenter import scene_type, segment_events
from video_agent.rendering.pipeline import timeline_from_lines


ROOT = Path(__file__).resolve().parents[1]


def event(number, event_type="DIALOGUE", text="hello", speaker="pc_01", **extra):
    value = {
        "event_id": f"norm:test:{number:06d}", "event_type": event_type, "text": text,
        "speaker_id": speaker, "actor_id": speaker, "source_event_ids": [f"source:{number}"],
        "state_changes": {}, "metadata": {"source_stream": "test"},
    }
    value.update(extra)
    return value


def plan_for(item, decision="KEEP"):
    return {"source_event_id": item["event_id"], "content_decision": decision}


class M2ContractTests(unittest.TestCase):
    def test_content_decisions(self):
        self.assertEqual(CONTENT_DECISIONS, {"KEEP", "COMPRESS", "CUT"})

    def test_presentation_modes(self):
        self.assertIn("OVERLAY_ONLY", PRESENTATION_MODES)
        self.assertIn("SILENT_VISUAL", PRESENTATION_MODES)

    def test_text_treatments(self):
        self.assertEqual(len(TEXT_TREATMENTS), 5)

    def test_valid_provider_decision(self):
        value = {"source_event_id": "e", "content_decision": "KEEP", "presentation_mode": "VOICED",
                 "text_treatment": "VERBATIM", "confidence": 0.8, "reason": "ok"}
        self.assertTrue(validate_provider_decision(value, {"e"}))

    def test_invalid_provider_decision_rejected(self):
        value = {"source_event_id": "made-up", "content_decision": "KEEP", "presentation_mode": "VOICED",
                 "text_treatment": "VERBATIM", "confidence": 0.8, "reason": "ok"}
        self.assertFalse(validate_provider_decision(value, {"e"}))

    def test_safe_default_is_lossless(self):
        self.assertEqual(safe_default({"event_id": "e"})["content_decision"], "KEEP")


class M2EditingTests(unittest.TestCase):
    def test_self_name_prefix_removed(self):
        cleaned, treatment, reasons = cleanup_text(event(1, text="Alice(PC1): 扉を開ける"), {"pc_01": "Alice"})
        self.assertEqual(cleaned, "扉を開ける")
        self.assertEqual(treatment, "TRIM_REDUNDANCY")
        self.assertIn("SELF_NAME_PREFIX", reasons)

    def test_meaningful_self_reference_preserved(self):
        text = "私はAliceだと名乗る"
        self.assertEqual(cleanup_text(event(1, text=text), {"pc_01": "Alice"})[0], text)

    def test_system_result_is_overlay_only(self):
        item = event(1, "SKILL_CHECK", "システム: 技能結果", dice={"skill_name": "目星", "roll": 42})
        protected, _ = detect_protected_events([item])
        result = edit_scene({"scene_id": "scene_001"}, [item], protected, {"pc_01": "Alice"})
        self.assertEqual(result["lines"][0]["presentation_mode"], "OVERLAY_ONLY")
        self.assertIsNone(result["lines"][0]["voice_text"])

    def test_dice_overlay_fields(self):
        item = event(1, "SKILL_CHECK", dice={"skill_name": "目星", "target_value": 60, "roll": 42, "result": "成功"})
        self.assertEqual(overlay_for(item)["roll"], 42)

    def test_overlay_only_hides_character_portrait(self):
        lines = [{"line_id": "l1", "source_event_ids": ["e1"], "speaker_id": "pc_01",
                  "text": "system", "presentation_mode": "OVERLAY_ONLY", "portrait_asset_id": "portrait",
                  "subtitle_profile_id": "sub", "dice": None}]
        audio = {"l1": {"duration_sec": 2.0, "project_path": "silence.wav", "engine": "NONE"}}
        clip = timeline_from_lines(lines, audio, {"pc_01": {"display_name": "Alice"}}, 0, "bg")["clips"][0]
        self.assertEqual(clip["portrait_asset_ids"], [])

    def test_technical_log_cut(self):
        item = event(1, "SYSTEM_INTERNAL", "stall detector checkpoint", speaker="system")
        protected, _ = detect_protected_events([item])
        result = edit_scene({"scene_id": "scene_001"}, [item], protected, {})
        self.assertEqual(result["plans"][0]["content_decision"], "CUT")

    def test_protected_ending_not_cut(self):
        item = event(1, "ENDING", "生還した", speaker="kp")
        protected, _ = detect_protected_events([item])
        result = edit_scene({"scene_id": "scene_001"}, [item], protected, {})
        self.assertEqual(result["plans"][0]["content_decision"], "KEEP")

    def test_source_provenance_contains_normalized_and_original(self):
        item = event(1)
        protected, _ = detect_protected_events([item])
        line = edit_scene({"scene_id": "scene_001"}, [item], protected, {})["lines"][0]
        self.assertEqual(line["source_event_ids"], [item["event_id"], "source:1"])

    def test_exact_duplicate_compressed(self):
        items = [event(1, text="同じ発言"), event(2, text="同じ発言")]
        protected, _ = detect_protected_events(items)
        result = edit_scene({"scene_id": "scene_001"}, items, protected, {})
        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["plans"][1]["content_decision"], "COMPRESS")
        self.assertEqual(len(result["lines"][0]["source_event_ids"]), 4)


class M2StructureAndQATests(unittest.TestCase):
    def test_hard_protection(self):
        protected, _ = detect_protected_events([event(1, "CLUE_FOUND")])
        self.assertEqual(protected["norm:test:000001"]["level"], "HARD_PROTECTED")

    def test_technical_state_not_meaningful(self):
        item = event(1, state_changes={"turn_count": {"before": 1, "after": 2}})
        self.assertEqual(meaningful_state_changes(item), [])

    def test_story_state_is_meaningful(self):
        item = event(1, state_changes={"basement_open": {"before": False, "after": True}})
        self.assertEqual(meaningful_state_changes(item), ["basement_open"])

    def test_segmentation_on_location(self):
        items = [event(1), event(2, "LOCATION_CHANGE"), event(3)]
        protected, _ = detect_protected_events(items)
        self.assertEqual(len(segment_events(items, protected)), 2)

    def test_scene_classifies_combat(self):
        self.assertEqual(scene_type([event(1, "COMBAT_START")], 1), "COMBAT")

    def test_dependencies_are_deterministic(self):
        items = [event(1, "CLUE_FOUND"), event(2)]
        _, dependencies = detect_protected_events(items)
        self.assertEqual(dependencies[0]["dependent_event_id"], items[1]["event_id"])

    def test_continuity_detects_cut_clue(self):
        item = event(1, "CLUE_FOUND")
        protected, deps = detect_protected_events([item])
        report = build_continuity_report([item], {item["event_id"]: plan_for(item, "CUT")}, deps, protected)
        self.assertEqual(report["status"], "FAIL")

    def test_continuity_detects_missing_item_origin(self):
        item = event(1, "ITEM_GAINED")
        protected, deps = detect_protected_events([item])
        report = build_continuity_report([item], {item["event_id"]: plan_for(item, "CUT")}, deps, protected)
        self.assertEqual(report["missing_item_origin"], [item["event_id"]])
        self.assertEqual(report["status"], "FAIL")

    def test_qa_detects_participant_reattribution(self):
        item = event(1, text="Alice says hello", speaker="pc_01")
        protected, _ = detect_protected_events([item])
        line = {"script_line_id": "line", "source_event_ids": [item["event_id"]], "speaker_id": "pc_02",
                "presentation_mode": "VOICED", "display_text": item["text"], "original_text": item["text"]}
        qa = editing_qa([item], [plan_for(item)], [line], protected, {"status": "PASS"})
        self.assertEqual(qa["status"], "FAIL")

    def test_qa_rejects_hard_protected_cut(self):
        item = event(1, "ENDING", "end", speaker="kp")
        protected, _ = detect_protected_events([item])
        qa = editing_qa([item], [plan_for(item, "CUT")], [], protected,
                        {"status": "PASS"})
        self.assertEqual(qa["status"], "FAIL")

    def test_qa_rejects_unaccounted_event(self):
        items = [event(1), event(2)]
        protected, _ = detect_protected_events(items)
        qa = editing_qa(items, [plan_for(items[0])], [], protected, {"status": "PASS"})
        self.assertEqual(qa["status"], "FAIL")

    def test_nonvoiced_duration_is_bounded(self):
        line = {"presentation_mode": "OVERLAY_ONLY", "display_text": "x" * 200}
        self.assertEqual(estimate_line_duration(line), 6.0)

    def test_part_candidate_at_scene_boundary(self):
        scenes = [{"scene_id": "s1", "scene_type": "ROLEPLAY", "importance": 0.1},
                  {"scene_id": "s2", "scene_type": "ENDING", "importance": 1.0}]
        lines = [{"scene_id": "s1", "presentation_mode": "VOICED", "voice_text": "x" * 3400},
                 {"scene_id": "s2", "presentation_mode": "VOICED", "voice_text": "end"}]
        self.assertEqual(part_candidates(scenes, lines)[0]["after_scene_id"], "s2")

    def test_scene_cache_round_trip(self):
        cache_root = ROOT / "cache" / "test_tmp"
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache_root) as folder:
            cache = SceneEditCache(Path(folder), "v1")
            scene = {"scene_id": "s1"}
            key = cache.key(scene, [event(1)], {})
            cache.save(scene, key, {"plans": [], "lines": []})
            self.assertEqual(cache.load(scene, key), {"plans": [], "lines": []})

    def test_scene_cache_rejects_changed_scene(self):
        cache_root = ROOT / "cache" / "test_tmp"
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache_root) as folder:
            cache = SceneEditCache(Path(folder), "v1")
            scene = {"scene_id": "s1"}
            first_key = cache.key(scene, [event(1)], {})
            cache.save(scene, first_key, {"plans": ["old"], "lines": []})
            changed_key = cache.key(scene, [event(1, text="changed")], {})
            self.assertIsNone(cache.load(scene, changed_key))

    def test_full_project_outputs_cover_all_events(self):
        project = ROOT / "projects" / "corbitt_clear_001"
        session = read_json(project / "normalized_session.json")
        plan = read_json(project / "edit_plan.json")
        self.assertEqual(len(session["events"]), 678)
        self.assertEqual({e["event_id"] for e in session["events"]},
                         {e["source_event_id"] for e in plan["events"]})

    def test_full_project_qa_passes(self):
        report = read_json(ROOT / "projects" / "corbitt_clear_001" / "editing_qa_report.json")
        self.assertEqual(report["status"], "PASS")

    def test_full_project_continuity_passes(self):
        report = read_json(ROOT / "projects" / "corbitt_clear_001" / "continuity_report.json")
        self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
