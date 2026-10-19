import json
import unittest
from pathlib import Path

from ActionAvailability import filter_available_candidates
from ActionValidator import FORCE_IC_ACTION_CHAT_ROUNDS, LOCATION_EXHAUSTED_FORCE_TURNS
from ProgressDirectorV2 import (
    StallDetectorV2,
    apply_s4_candidate_override,
    apply_stall_candidate_guidance,
    ensure_director_state,
)
from ProgressionPolicy import (
    derive_action_phase,
    derive_location_objective_status,
    derive_target_statuses,
    enrich_runtime,
    filter_exhausted_candidates,
    limit_available_candidates,
    reconcile_location,
)
from ScenarioManager import ScenarioManager


class FakeScenario:
    def __init__(self):
        self.location = "library"
        self.current_phase = "investigation"
        self.flags = {"book_read": False, "investigated_targets": []}
        self.scenario_data = {
            "locations": {
                "library": {
                    "objects": {
                        "book": {"investigated_flag": "book_read", "usable_actions": ["search"]},
                        "door": {
                            "investigated_flag": "door_seen",
                            "usable_actions": ["search", "use"],
                            "triggers_flag_on_success": {"door_open": True},
                        },
                    },
                    "connected_to": ["hall"],
                    "exits": {"hall": {}},
                },
                "hall": {"objects": {}, "connected_to": ["library"], "exits": {"library": {}}},
            }
        }
        self.event_triggers = []

    def get_location_info(self, location):
        return self.scenario_data["locations"].get(location, {})

    def get_available_exits(self, location):
        return [{"id": x, "name": x} for x in self.get_location_info(location).get("connected_to", [])]


class ProgressionRevisitTests(unittest.TestCase):
    @staticmethod
    def _scenario_with_objects(objects, flags=None):
        scenario = ScenarioManager({
            "initial_state": {
                "current_phase": "investigation", "location": "room",
                "flags": dict(flags or {}),
            },
            "locations": {
                "room": {
                    "objects": objects,
                    "connected_to": ["hall"],
                    "exits": {"hall": {}},
                },
                "hall": {"objects": {}, "connected_to": ["room"], "exits": {"room": {}}},
            },
            "event_triggers": [],
        })
        return scenario

    def test_unmet_requires_flag_is_unavailable(self):
        scenario = self._scenario_with_objects({
            "sealed_notes": {"requires_flag": "seal_broken", "usable_actions": ["search"]},
        })
        self.assertEqual(derive_target_statuses(scenario, "room")["sealed_notes"], "UNAVAILABLE")

    def test_negated_requires_flag_uses_scenario_resolver(self):
        scenario = self._scenario_with_objects({
            "upper_mark": {"requires_flag": "!in_basement", "usable_actions": ["search"]},
        }, {"in_basement": False})
        self.assertEqual(derive_target_statuses(scenario, "room")["upper_mark"], "UNSEEN")
        scenario.flags["in_basement"] = True
        self.assertEqual(derive_target_statuses(scenario, "room")["upper_mark"], "UNAVAILABLE")

    def test_optional_unavailable_does_not_block_location_completion(self):
        statuses = {"done": "EXHAUSTED", "optional_later": "UNAVAILABLE"}
        self.assertEqual(derive_location_objective_status(statuses), "EXHAUSTED")

    def test_required_unavailable_blocks_location_completion(self):
        scenario = self._scenario_with_objects({
            "key_evidence": {
                "requires_flag": "vault_open", "required_for_completion": True,
                "usable_actions": ["search"],
            },
        })
        statuses = derive_target_statuses(scenario, "room")
        self.assertEqual(statuses["key_evidence"], "BLOCKED_REQUIRED_OBJECTIVE")
        self.assertEqual(derive_location_objective_status(statuses), "BLOCKED_REQUIRED_OBJECTIVE")

    def test_context_change_re_evaluates_unavailable_target(self):
        scenario = self._scenario_with_objects({
            "cellar_shelf": {"requires_flag": "in_basement", "usable_actions": ["search"]},
        })
        self.assertEqual(derive_target_statuses(scenario, "room")["cellar_shelf"], "UNAVAILABLE")
        scenario.flags["in_basement"] = True
        self.assertEqual(derive_target_statuses(scenario, "room")["cellar_shelf"], "UNSEEN")

    def test_candidate_limit_is_applied_after_availability_filtering(self):
        scenario = self._scenario_with_objects({
            **{
                f"blocked_{i}": {"requires_flag": "closed", "usable_actions": ["search"]}
                for i in range(3)
            },
            "open_1": {"usable_actions": ["search"]},
            "open_2": {"usable_actions": ["search"]},
        })
        goal = {"candidate_next_actions": [
            *[
                {"action": "search", "target": f"blocked_{i}", "skill": ""}
                for i in range(3)
            ],
            {"action": "search", "target": "open_1", "skill": ""},
            {"action": "search", "target": "open_2", "skill": ""},
            {"action": "move", "target": "hall", "skill": ""},
        ]}
        filtered = filter_available_candidates(goal, scenario, "room", source="test")
        limited = limit_available_candidates(filtered, "EXHAUSTED")
        self.assertEqual(
            [(x["action"], x["target"]) for x in limited["candidate_next_actions"]],
            [("search", "open_1"), ("search", "open_2"), ("move", "hall")],
        )

    def test_three_blocked_candidates_do_not_starve_available_move(self):
        scenario = self._scenario_with_objects({
            f"blocked_{i}": {"requires_flag": "closed", "usable_actions": ["search"]}
            for i in range(3)
        })
        goal = {"candidate_next_actions": [
            *[
                {"action": "search", "target": f"blocked_{i}", "skill": ""}
                for i in range(3)
            ],
            {"action": "move", "target": "hall", "skill": ""},
        ]}
        filtered = filter_available_candidates(goal, scenario, "room", source="test")
        limited = limit_available_candidates(filtered, "EXHAUSTED")
        self.assertEqual(
            [(x["action"], x["target"]) for x in limited["candidate_next_actions"]],
            [("move", "hall")],
        )

    def test_transition_move_survives_candidate_cap(self):
        goal = {"candidate_next_actions": [
            *[
                {"action": "search", "target": f"available_{i}", "skill": ""}
                for i in range(4)
            ],
            {"action": "move", "target": "hall", "skill": ""},
        ]}
        limited = limit_available_candidates(goal, "EXHAUSTED")
        self.assertEqual(len(limited["candidate_next_actions"]), 3)
        self.assertIn("move", [x["action"] for x in limited["candidate_next_actions"]])

    def test_cycle30_fixture_transitions_to_neighborhood(self):
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads((
            root / "goal-transition-move-candidate-analysis" / "cycle30_fixture.json"
        ).read_text(encoding="utf-8"))
        checkpoint = Path(fixture["derived_from"])
        scenario_data = json.loads((
            checkpoint / "runtime_data" / "datasets" / "corbitt_house.json"
        ).read_text(encoding="utf-8"))
        scenario = ScenarioManager(scenario_data)
        scenario.load_from_dict({
            "current_phase": fixture["current_phase"],
            "location": fixture["current_location"],
            "flags": fixture["flags"],
        })
        runtime = {}
        goal = enrich_runtime(runtime, {}, scenario, fixture["current_location"])
        for target in (
            "skeletons_in_robes", "shelf_with_records", "cult_diary", "grimoire_book_of_eibon",
        ):
            self.assertEqual(runtime["target_statuses"][target], "UNAVAILABLE")
        self.assertEqual(runtime["location_objective_status"], "EXHAUSTED")
        self.assertEqual(runtime["action_phase"], "TRANSITION")
        self.assertEqual(
            [(x["action"], x["target"], x["availability_status"]) for x in goal["candidate_next_actions"]],
            [("move", "the_neighborhood", "AVAILABLE")],
        )
        scenario.flags.update({
            "chapel_cellar_entered": True, "in_basement": True,
            "found_diary": True, "found_grimoire": True,
        })
        basement_statuses = derive_target_statuses(scenario, fixture["current_location"])
        for target in (
            "skeletons_in_robes", "shelf_with_records", "cult_diary", "grimoire_book_of_eibon",
        ):
            self.assertEqual(basement_statuses[target], "UNSEEN")

    def test_target_exhaustion_and_state_change_reopens(self):
        scenario = FakeScenario()
        scenario.flags.update({"book_read": True, "door_seen": True, "door_open": False})
        statuses = derive_target_statuses(scenario, "library")
        self.assertEqual(statuses["book"], "EXHAUSTED")
        self.assertEqual(statuses["door"], "INVESTIGATED")
        scenario.flags["door_open"] = True
        self.assertEqual(derive_target_statuses(scenario, "library")["door"], "EXHAUSTED")

    def test_exhausted_target_removed_and_transition_prioritized(self):
        goal = {"candidate_next_actions": [
            {"action": "search", "target": "book"},
            {"action": "move", "target": "hall"},
        ]}
        filtered = filter_exhausted_candidates(goal, {"book": "EXHAUSTED"}, "EXHAUSTED")
        self.assertEqual(filtered["candidate_next_actions"], [{"action": "move", "target": "hall"}])
        self.assertEqual(derive_location_objective_status({"book": "EXHAUSTED"}), "EXHAUSTED")
        self.assertEqual(derive_action_phase(filtered, {"book": "EXHAUSTED"}, "EXHAUSTED"), "TRANSITION")

    def test_non_actionable_dialogue_and_exit_limits(self):
        self.assertEqual(FORCE_IC_ACTION_CHAT_ROUNDS, 3)
        self.assertLessEqual(LOCATION_EXHAUSTED_FORCE_TURNS, 5)

    def test_stall_escalates_and_only_s4_overrides(self):
        runtime = {}
        levels = []
        for _ in range(6):
            runtime = StallDetectorV2.update(
                runtime, action="search", target="book",
                location_before="library", location_after="library", progress_delta=0,
            )
            levels.append(runtime["intervention_level"])
        self.assertEqual(levels, ["S0", "S1", "S2", "S2", "S3", "S4"])
        state = {"director_v2": {"stall": runtime, "goal": {
            "candidate_next_actions": [{"action": "move", "target": "hall"}],
        }}}
        fixed = apply_s4_candidate_override(state, {"action": "search", "target": "book"})
        self.assertEqual((fixed["action"], fixed["target"]), ("move", "hall"))
        second = apply_s4_candidate_override(state, {"action": "search", "target": "book"})
        self.assertEqual((second["action"], second["target"]), ("search", "book"))

    def test_s2_guides_exhausted_reselection_to_candidate(self):
        state = {"director_v2": {
            "stall": {"intervention_level": "S2"},
            "target_statuses": {"book": "EXHAUSTED"},
            "action_phase": "TRANSITION",
            "goal": {"candidate_next_actions": [{"action": "move", "target": "hall", "skill": ""}]},
        }}
        fixed = apply_stall_candidate_guidance(state, {"action": "search", "target": "book"})
        self.assertEqual((fixed["action"], fixed["target"]), ("move", "hall"))
        self.assertTrue(fixed["director_guided"])
        self.assertFalse(fixed.get("director_forced", False))

    def test_s3_guides_information_action_during_execute(self):
        state = {"director_v2": {
            "stall": {"intervention_level": "S3"},
            "target_statuses": {"door": "INVESTIGATED"},
            "action_phase": "EXECUTE",
            "goal": {"candidate_next_actions": [{"action": "use", "target": "door", "skill": ""}]},
        }}
        fixed = apply_stall_candidate_guidance(state, {"action": "search", "target": "door"})
        self.assertEqual((fixed["action"], fixed["target"]), ("use", "door"))

    def test_location_consistency_is_detected_and_repaired(self):
        scenario = FakeScenario()
        scenario.location = "hall"
        state = {"current_loc": "library", "all_events_log": []}
        result = reconcile_location(state, scenario)
        self.assertTrue(result["inconsistent"])
        self.assertEqual(scenario.location, "library")
        self.assertEqual(state["all_events_log"][-1]["meta"]["error_code"], "LOCATION_INCONSISTENCY")

    def test_chapel_cellar_does_not_imply_corbitt_house_entry(self):
        scenario = ScenarioManager({
            "scenario_meta": {}, "initial_state": {"location": "chapel_of_contemplation", "flags": {}},
            "locations": {"chapel_of_contemplation": {"objects": {}, "connected_to": [], "exits": {}}},
            "event_triggers": [],
        })
        scenario.location = "chapel_of_contemplation"
        scenario._apply_payload_updates({"flag_updates": {"in_basement": True}})
        scenario.apply_implied_progress_flags()
        self.assertTrue(scenario.flags["chapel_cellar_entered"])
        self.assertFalse(scenario.flags["in_basement"])
        self.assertFalse(scenario.flags.get("corbitt_house_entered", False))
        self.assertTrue(scenario._flag_requirement_met("in_basement", "chapel_of_contemplation"))

    def test_legacy_chapel_basement_flag_is_migrated(self):
        scenario = ScenarioManager({
            "scenario_meta": {}, "initial_state": {"location": "chapel_of_contemplation", "flags": {}},
            "locations": {"chapel_of_contemplation": {"objects": {}, "connected_to": [], "exits": {}}},
            "event_triggers": [],
        })
        scenario.flags["in_basement"] = True
        scenario.apply_implied_progress_flags()
        self.assertTrue(scenario.flags["chapel_cellar_entered"])
        self.assertFalse(scenario.flags["in_basement"])
        self.assertFalse(scenario.flags.get("corbitt_house_entered", False))

    def test_director_exposes_location_objective_and_action_phase(self):
        scenario = FakeScenario()
        state = {"current_loc": "library"}
        runtime = ensure_director_state(state, scenario)
        self.assertIn(runtime["location_objective_status"], {"ACTIVE", "SATISFIED", "EXHAUSTED"})
        self.assertIn(runtime["action_phase"], {"DISCOVER", "INVESTIGATE", "DECIDE", "EXECUTE", "TRANSITION"})

    def test_investigated_target_adds_state_change_candidate(self):
        scenario = FakeScenario()
        scenario.flags.update({"door_seen": True, "door_open": False})
        scenario.event_triggers = [{
            "event_id": "library__door__open",
            "priority": 10,
            "trigger_condition": (
                "action_id in ['use', 'force'] and target == 'door' and "
                "location == 'library' and flags.door_open == false and success_level >= 2"
            ),
            "payload": {"flag_updates": {"door_open": True}},
        }]
        runtime = ensure_director_state({"current_loc": "library"}, scenario)
        self.assertEqual(runtime["action_phase"], "EXECUTE")
        self.assertEqual(
            runtime["goal"]["candidate_next_actions"][0],
            {
                "action": "use", "target": "door", "skill": "",
                "reason": "state_change_after_investigation", "event_id": "library__door__open",
                "reachable": True, "executable": True, "blocked_reason": "",
                "adjudication_route": "SCENARIO_EVENT:library__door__open",
                "expected_state_effect": {"flag_updates": {"door_open": True}},
                "required_location": "library",
            },
        )

    def test_phase_change_event_adds_state_change_candidate(self):
        scenario = FakeScenario()
        scenario.scenario_data["locations"]["library"]["objects"] = {
            "ladder": {"investigated_flag": "ladder_seen", "usable_actions": ["search", "climb"]},
        }
        scenario.flags["ladder_seen"] = True
        scenario.event_triggers = [{
            "event_id": "library__ladder__escape",
            "trigger_condition": (
                "action_id == 'climb' and target == 'ladder' and location == 'library' "
                "and flags.ladder_seen == true"
            ),
            "payload": {"new_phase": "clear"},
        }]
        runtime = ensure_director_state({"current_loc": "library"}, scenario)
        self.assertEqual(runtime["action_phase"], "EXECUTE")
        self.assertEqual(runtime["goal"]["candidate_next_actions"][0]["action"], "climb")

    def test_exhausted_location_adds_move_candidate(self):
        scenario = FakeScenario()
        scenario.scenario_data["locations"]["library"]["objects"] = {
            "book": {"investigated_flag": "book_read", "usable_actions": ["search"]},
        }
        scenario.flags["book_read"] = True
        runtime = ensure_director_state({"current_loc": "library"}, scenario)
        self.assertEqual(runtime["location_objective_status"], "EXHAUSTED")
        self.assertEqual(runtime["action_phase"], "TRANSITION")
        self.assertEqual(runtime["goal"]["candidate_next_actions"][0]["action"], "move")

    def test_unseen_target_is_added_when_goal_route_is_empty(self):
        scenario = FakeScenario()
        scenario.flags["book_read"] = True
        runtime = ensure_director_state({"current_loc": "library"}, scenario)
        candidates = runtime["goal"]["candidate_next_actions"]
        self.assertTrue(any(
            item.get("action") == "search"
            and item.get("target") == "door"
            and item.get("reason") == "unseen_target"
            and item.get("reachable") is True
            and item.get("executable") is True
            for item in candidates
        ))

    def test_exhausted_location_prefers_unvisited_exit_over_roundtrip(self):
        scenario = FakeScenario()
        scenario.scenario_data["locations"]["library"]["connected_to"] = ["old_room", "new_room"]
        scenario.scenario_data["locations"]["library"]["objects"] = {
            "book": {"investigated_flag": "book_read", "usable_actions": ["search"]},
        }
        scenario.flags["book_read"] = True
        state = {"current_loc": "library", "director_v2": {
            "visited_locations": ["old_room", "library"],
            "stall": {"recent_locations": ["old_room", "library"]},
        }}
        runtime = ensure_director_state(state, scenario)
        self.assertEqual(runtime["goal"]["candidate_next_actions"][0]["target"], "new_room")


if __name__ == "__main__":
    unittest.main()
