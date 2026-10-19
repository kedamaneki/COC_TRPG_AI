import unittest

from video_agent.presentation.replay_consistency import (
    apply_actor_visibility,
    audit_actor_visibility,
    audit_location_consistency,
)


class ReplayLocationActorConsistencyTests(unittest.TestCase):
    def test_fixture_actor_visibility_001(self):
        base = {
            "table_event_id": "t1", "speaker_class": "PC",
            "speaker_icon_asset_id": "portrait_reimu",
            "scene_actor_asset_ids": ["portrait_pc01_kitsune_reimu"],
            "scene_state": {"present_npc_ids": ["npc_a"], "visible_scene_actor_ids": ["pc_01", "npc_a"]},
        }
        fixed = apply_actor_visibility(base, npc_portrait_ids={"npc_a": "portrait_npc_a"})
        self.assertEqual(fixed["scene_state"]["visible_scene_actor_ids"], ["npc_a"])
        self.assertEqual(fixed["scene_actor_asset_ids"], ["portrait_npc_a"])
        self.assertEqual(audit_actor_visibility([fixed])["status"], "PASS")

    def test_location_gate_rejects_stale_s4_and_video_background(self):
        raw = [{
            "event_id": "e1", "raw_event_offset": 2, "event_type": "ACTION_DECLARATION",
            "location": "ground_floor", "selected_action": "push", "target": "basement_planks",
            "required_location": "basement", "reachable": True, "executable": True,
            "intervention_level": "S4", "progression_binding": {"selected": True, "proposal_bound": True},
        }]
        table = [{"table_event_id": "t1", "scene_state": {"current_location": "ground_floor"}}]
        script = [{"source_table_event_id": "t1", "scene_state": {"current_location": "ground_floor"},
                   "background_asset_id": "basement_bg"}]
        report = audit_location_consistency(raw, table, script, [],
            object_locations={"basement_planks": "basement"}, background_locations={"basement_bg": "basement"})
        self.assertEqual(report["counts"]["OBJECT_INTERACTION_OUTSIDE_LOCATION"], 1)
        self.assertEqual(report["counts"]["STALE_FRONTIER_AFTER_LOCATION_CHANGE"], 1)
        self.assertEqual(report["counts"]["STALE_S4_PROPOSAL_AFTER_LOCATION_CHANGE"], 1)
        self.assertEqual(report["counts"]["VIDEO_LOCATION_CONTEXT_STALE"], 1)

    def test_location_gate_accepts_return_before_object_interaction(self):
        raw = [
            {"event_id": "m1", "raw_event_offset": 1, "event_type": "LOCATION_CHANGE",
             "location": "ground_floor", "target": "basement"},
            {"event_id": "a1", "raw_event_offset": 2, "event_type": "ACTION_DECLARATION",
             "location": "basement", "selected_action": "push", "target": "basement_planks",
             "required_location": "basement"},
        ]
        table = [{"table_event_id": "t1", "required_location": "basement",
                  "scene_state": {"current_location": "basement"}}]
        script = [{"source_table_event_id": "t1", "scene_state": {"current_location": "basement"},
                   "background_asset_id": "basement_bg"}]
        timeline = [{"source_table_event_id": "t1", "scene_state": {"current_location": "basement"},
                     "background_asset_id": "basement_bg"}]
        report = audit_location_consistency(raw, table, script, timeline,
            object_locations={"basement_planks": "basement"}, background_locations={"basement_bg": "basement"})
        self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
