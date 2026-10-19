import copy
import json
import unittest
from pathlib import Path

from ProgressDirectorV2 import ensure_director_state
from ProgressionPolicy import rank_candidates_by_continuity
from ScenarioManager import ScenarioManager


SCENARIO = Path(__file__).with_name("scenario_corbitt.json")


class LocalFrontierContinuityV1Tests(unittest.TestCase):
    def test_local_planks_frontier_beats_unrelated_move(self):
        manager = ScenarioManager(copy.deepcopy(json.loads(SCENARIO.read_text(encoding="utf-8"))))
        manager.location = "corbitt_basement"
        manager.flags.update({"basement_planks_examined": True, "basement_planks_broken": False,
                              "investigated_targets": ["basement_planks"]})
        state = {"current_loc": "corbitt_basement", "actor_id": "pc_01", "unified_event_log": [],
                 "director_v2": {"stall": {"recent_actions": [["search", "basement_planks"]],
                                             "recent_failed_actions": [], "recent_locations": ["corbitt_basement"]}}}
        runtime = ensure_director_state(state, manager)
        candidates = runtime["goal"]["candidate_next_actions"]
        self.assertEqual([row["action"] for row in candidates[:3]], ["push", "force", "break"])
        scores = runtime["candidate_continuity_scores"][:3]
        self.assertTrue(all(row["local_frontier"] for row in scores))
        self.assertTrue(all(row["continuity_score"] >= 125 for row in scores))
        self.assertTrue(all(row["expected_state_effect"]["flag_updates"]["basement_planks_broken"]
                            for row in candidates[:3]))

    def test_attempt_exhausted_and_low_value_move_rank_below_local_frontier(self):
        goal = {"candidate_next_actions": [
            {"action": "search", "target": "old_desk", "required_location": "room",
             "availability_status": "AVAILABLE", "reachable": True, "executable": True},
            {"action": "move", "target": "hall", "required_location": "room",
             "availability_status": "AVAILABLE", "reachable": True, "executable": True,
             "expected_state_effect": {"new_location": "hall"}},
            {"action": "push", "target": "door", "required_location": "room",
             "availability_status": "AVAILABLE", "reachable": True, "executable": True,
             "event_id": "door_open", "expected_state_effect": {"flag_updates": {"door_open": True}}},
        ]}
        runtime = {"visited_locations": ["hall"], "stall": {
            "recent_actions": [["search", "old_desk"]],
            "recent_failed_actions": [["search", "old_desk"]],
            "recent_locations": ["hall", "room"],
        }}
        ranked = rank_candidates_by_continuity(
            goal, "room", {"old_desk": "EXHAUSTED", "door": "INVESTIGATED"}, runtime,
        )["candidate_next_actions"]
        self.assertEqual([(row["action"], row["target"]) for row in ranked],
                         [("push", "door"), ("move", "hall")])

    def test_expected_effect_is_an_intent_not_success_claim(self):
        goal = {"candidate_next_actions": [{
            "action": "search", "target": "cabinet", "required_location": "room",
            "availability_status": "AVAILABLE", "reachable": True, "executable": True,
            "expected_state_effect": {"intent": "investigate_target", "target_status": "INVESTIGATED"},
        }]}
        row = rank_candidates_by_continuity(goal, "room", {"cabinet": "UNSEEN"})["candidate_next_actions"][0]
        self.assertEqual(row["expected_state_effect"]["intent"], "investigate_target")
        self.assertNotIn("guaranteed", row["expected_state_effect"])


if __name__ == "__main__":
    unittest.main()
