import copy
import unittest

from ActionAvailability import BLOCKED, filter_available_candidates
from ProgressDirectorV2 import apply_s4_candidate_override


class ScenarioStub:
    location = "ground_floor"
    flags = {}
    meta = {"id": "fixture"}

    def evaluate_pre_action_guard(self, action, target, loc_id="", pending_san_check=None):
        return {}

    def get_object_info(self, location, target):
        return {"id": target} if location == "basement" else {}


class LocationContextContractTests(unittest.TestCase):
    def test_fixture_location_context_001_marks_stale_object_route_requires_return(self):
        goal = {"candidate_next_actions": [{
            "action": "push", "target": "basement_planks",
            "required_location": "basement", "reachable": True, "executable": True,
        }]}
        filtered = filter_available_candidates(goal, ScenarioStub(), "ground_floor")
        self.assertEqual(filtered["candidate_next_actions"], [])
        blocked = filtered["blocked_candidate_actions"][0]
        self.assertEqual(blocked["availability_status"], BLOCKED)
        self.assertEqual(blocked["blocked_reason"], "REQUIRES_RETURN")
        self.assertFalse(blocked["reachable"])
        self.assertFalse(blocked["executable"])

    def test_fixture_s4_location_binding_001_never_binds_stale_route(self):
        state = {"current_loc": "ground_floor", "director_v2": {
            "stall": {"intervention_level": "S4"},
            "goal": {"candidate_next_actions": [{
                "action": "push", "target": "basement_planks",
                "required_location": "basement", "reachable": True, "executable": True,
            }]},
        }}
        original = {"action": "wait", "target": "", "transaction_id": "tx"}
        result = apply_s4_candidate_override(state, copy.deepcopy(original), ScenarioStub(), actor="pc_01")
        self.assertEqual(result, original)
        blocked = state["director_v2"]["goal"]["blocked_candidate_actions"][0]
        self.assertEqual(blocked["blocked_reason"], "REQUIRES_RETURN")


if __name__ == "__main__":
    unittest.main()
