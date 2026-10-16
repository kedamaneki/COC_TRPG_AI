import copy
import unittest
from unittest import mock

from ActionAvailability import (
    AVAILABLE,
    BLOCKED,
    CONDITIONALLY_AVAILABLE,
    check_action_availability,
    compare_candidate_and_execution,
    filter_available_candidates,
)
from ProgressDirectorV2 import apply_s4_candidate_override
from ScenarioManager import ScenarioManager


def build_scenario():
    return ScenarioManager({
        "scenario_meta": {"id": "availability_fixture"},
        "initial_state": {
            "location": "lower_room",
            "phase": "investigation",
            "flags": {"below_hatch": True, "door_open": False, "has_key": False},
        },
        "locations": {
            "lower_room": {
                "objects": {
                    "hatch": {
                        "requires_flag": "!below_hatch",
                        "usable_actions": ["climb", "push"],
                    },
                    "door": {
                        "requires_flag": "door_open",
                        "usable_actions": ["open", "push"],
                    },
                },
                "connected_to": ["hall"],
                "exits": {"hall": {"requires_flag": "has_key"}},
            },
            "hall": {"objects": {}, "connected_to": ["lower_room"], "exits": {}},
        },
        "event_triggers": [{
            "event_id": "generic_hatch_climb_out",
            "trigger_condition": (
                "action_id in ['climb', 'push'] and target == 'hatch' and "
                "location == 'lower_room' and flags.below_hatch == true and success_level >= 2"
            ),
            "payload": {"flag_updates": {"below_hatch": False}},
        }],
    })


class ActionAvailabilityContractTests(unittest.TestCase):
    def setUp(self):
        self.scenario = build_scenario()
        self.state = {
            "current_loc": "lower_room",
            "current_scene_id": "scene_fixture",
            "unified_event_log": [],
        }

    def test_available_consistency_and_generic_hatch_escape(self):
        candidate = check_action_availability(
            self.scenario, actor="pc", action="climb", target="hatch",
            location="lower_room", state=self.state, source="candidate",
        )
        execution = check_action_availability(
            self.scenario, actor="pc", action="climb", target="hatch",
            location="lower_room", state=self.state, source="execution",
        )
        self.assertEqual(candidate["status"], AVAILABLE)
        self.assertEqual(execution["status"], AVAILABLE)
        self.assertEqual(candidate["context_version"], execution["context_version"])
        payload = self.scenario.process_action("climb", "hatch", 2)
        self.assertFalse(payload.get("blocked", False))
        self.assertFalse(self.scenario.flags["below_hatch"])

    def test_blocked_candidate_is_filtered(self):
        goal = {"candidate_next_actions": [
            {"action": "push", "target": "door", "skill": ""},
            {"action": "climb", "target": "hatch", "skill": ""},
        ]}
        filtered = filter_available_candidates(
            goal, self.scenario, "lower_room", actor="pc", state=self.state,
        )
        self.assertEqual(
            [(x["action"], x["target"]) for x in filtered["candidate_next_actions"]],
            [("climb", "hatch")],
        )
        self.assertEqual(filtered["blocked_candidate_actions"][0]["availability_status"], BLOCKED)

    def test_forced_override_never_selects_blocked_candidate(self):
        state = copy.deepcopy(self.state)
        state["director_v2"] = {
            "stall": {"intervention_level": "S4", "s4_override_used": False},
            "goal": {"candidate_next_actions": [
                {"action": "push", "target": "door", "skill": ""},
                {"action": "climb", "target": "hatch", "skill": ""},
            ]},
        }
        fixed = apply_s4_candidate_override(
            state, {"action": "wait", "target": ""},
            scenario_mgr=self.scenario, actor="pc",
        )
        self.assertEqual((fixed["action"], fixed["target"]), ("climb", "hatch"))

    def test_conditional_action_is_not_immediate_candidate(self):
        decision = check_action_availability(
            self.scenario, actor="pc", action="move", target="hall",
            location="lower_room", state=self.state,
        )
        self.assertEqual(decision["status"], CONDITIONALLY_AVAILABLE)
        filtered = filter_available_candidates(
            {"candidate_next_actions": [{"action": "move", "target": "hall"}]},
            self.scenario, "lower_room", actor="pc", state=self.state,
        )
        self.assertEqual(filtered["candidate_next_actions"], [])

    def test_state_change_records_availability_drift(self):
        self.scenario.flags["door_open"] = True
        candidate = check_action_availability(
            self.scenario, actor="pc", action="push", target="door",
            location="lower_room", state=self.state,
        )
        self.scenario.flags["door_open"] = False
        execution = check_action_availability(
            self.scenario, actor="pc", action="push", target="door",
            location="lower_room", state=self.state,
        )
        event = compare_candidate_and_execution(self.state, candidate, execution)
        self.assertEqual(event["event_type"], "ACTION_AVAILABILITY_DRIFT")

    def test_unchanged_state_records_contract_violation(self):
        self.scenario.flags["door_open"] = True
        candidate = check_action_availability(
            self.scenario, actor="pc", action="push", target="door",
            location="lower_room", state=self.state,
        )
        blocked_payload = {"blocked": True, "system_log": "blocked by divergent executor"}
        with mock.patch.object(self.scenario, "evaluate_pre_action_guard", return_value=blocked_payload):
            execution = check_action_availability(
                self.scenario, actor="pc", action="push", target="door",
                location="lower_room", state=self.state,
            )
        event = compare_candidate_and_execution(self.state, candidate, execution)
        self.assertEqual(event["event_type"], "ACTION_AVAILABILITY_CONTRACT_VIOLATION")

    def test_scenario_runtime_conflict_is_visible(self):
        result = check_action_availability(
            self.scenario, actor="pc", action="climb", target="hatch",
            location="lower_room", state=self.state, log_events=True,
        )
        self.assertTrue(result["scenario_runtime_conflict"])
        types = [x["event_type"] for x in self.state["unified_event_log"]]
        self.assertIn("SCENARIO_RUNTIME_AVAILABILITY_CONFLICT", types)

    def test_context_change_allows_re_evaluation(self):
        blocked = check_action_availability(
            self.scenario, actor="pc", action="push", target="door",
            location="lower_room", state=self.state,
        )
        self.scenario.flags["door_open"] = True
        available = check_action_availability(
            self.scenario, actor="pc", action="push", target="door",
            location="lower_room", state=self.state,
        )
        self.assertEqual(blocked["status"], BLOCKED)
        self.assertEqual(available["status"], AVAILABLE)
        self.assertNotEqual(blocked["context_version"], available["context_version"])


if __name__ == "__main__":
    unittest.main()
