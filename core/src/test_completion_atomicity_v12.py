import unittest

import main as game_main
from CompletionAtomicity import (
    CompletionAtomicityError,
    commit_special_objective_completion,
    validate_completion_invariants,
)
from GameStateManager import GameStateManager
from ScenarioManager import ScenarioManager


class _Scenario:
    def __init__(self):
        self.flags = {"corbitt_defeated": True}
        self.current_phase = "investigation"


class _Combat:
    in_combat = False


class _Characters:
    active_pc_list = ["pc"]
    characters = {"pc": {"profile": {"name": "PC", "is_npc": False}, "attributes": {"DEX": 50}}}

    def get_attribute(self, _cid, key):
        return 50 if key == "DEX" else 0

    def get_stat_current(self, _cid, _key):
        return 10


def _event():
    return {
        "event_id": "evt-special",
        "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
        "adjudication_id": "adj-special",
        "target": "corbitt_body",
        "world_fact": {
            "event": "SPECIAL_OBJECTIVE_COMPLETED",
            "target": "corbitt_body",
            "fact": "CORBITT_BODY_DESTROYED",
        },
    }


class CompletionAtomicityV12Tests(unittest.TestCase):
    def test_v11_historical_failure_is_rejected(self):
        with self.assertRaisesRegex(CompletionAtomicityError, "DEFEATED_WITHOUT"):
            validate_completion_invariants(
                completed=True, clear=True, ending=True,
                corbitt_defeated=True, special_objective=False,
                active_combat=False,
            )

    def test_patched_success_commits_clear_atomically(self):
        state = {"unified_event_log": [_event()]}
        result = {"completion_phase_deferred": "clear", "adjudication_id": "adj-special", "target": "corbitt_body"}
        scenario = _Scenario()
        envelope = commit_special_objective_completion(state, result, scenario, _Combat())
        self.assertEqual(scenario.current_phase, "clear")
        self.assertEqual(envelope["gate"], "PASS")
        self.assertTrue(result["special_objective_evidence"])

    def test_defeated_without_objective_fails(self):
        with self.assertRaises(CompletionAtomicityError):
            validate_completion_invariants(completed=False, clear=False, ending=False, corbitt_defeated=True, special_objective=False, active_combat=False)

    def test_completed_during_combat_fails(self):
        with self.assertRaises(CompletionAtomicityError):
            validate_completion_invariants(completed=True, clear=True, ending=False, corbitt_defeated=True, special_objective=True, active_combat=True)

    def test_clear_without_ending_fails(self):
        with self.assertRaises(CompletionAtomicityError):
            validate_completion_invariants(completed=False, clear=True, ending=False, corbitt_defeated=False, special_objective=False, active_combat=False)

    def test_missing_event_prevents_completion_commit(self):
        scenario = _Scenario()
        with self.assertRaises(CompletionAtomicityError):
            commit_special_objective_completion(
                {"unified_event_log": []},
                {"completion_phase_deferred": "clear", "adjudication_id": "adj-special"},
                scenario, _Combat(),
            )
        self.assertEqual(scenario.current_phase, "investigation")

    def test_completion_commit_is_idempotent(self):
        state = {"unified_event_log": [_event()]}
        result = {"completion_phase_deferred": "clear", "adjudication_id": "adj-special", "target": "corbitt_body"}
        scenario = _Scenario()
        first = commit_special_objective_completion(state, result, scenario, _Combat())
        second = commit_special_objective_completion(state, result, scenario, _Combat())
        self.assertEqual(first, second)
        self.assertEqual(len(state["unified_event_log"]), 1)

    def test_inactive_finale_persists_objective_before_clear(self):
        scenario = ScenarioManager({
            "scenario_meta": {"title": "atomic-finale"},
            "initial_state": {"location": "room", "current_phase": "investigation", "flags": {"corbitt_defeated": False}},
            "locations": {"room": {"objects": {}}},
            "event_triggers": [{
                "event_id": "defeat",
                "priority": 1,
                "trigger_condition": "action_id == 'break' and target == 'corbitt_body' and success_level >= 2",
                "action_type": "update_and_describe",
                "payload": {
                    "flag_updates": {"corbitt_defeated": True},
                    "new_phase": "clear",
                    "combat_end": True,
                    "world_fact": {"event": "SPECIAL_OBJECTIVE_COMPLETED", "target": "corbitt_body", "fact": "CORBITT_BODY_DESTROYED"},
                    "resolution_reason": "SPECIAL_OBJECTIVE:CORBITT_BODY_DESTROYED",
                },
            }],
        })
        characters = _Characters()
        combat = GameStateManager(characters)
        state = {"current_loc": "room", "unified_event_log": []}
        payload = scenario.process_action("break", "corbitt_body", 2)
        self.assertEqual(scenario.current_phase, "investigation")
        payload.update({"adjudication_id": "adj-special", "resolution_mode": "NO_ROLL", "target": "corbitt_body", "selected_action": "break"})
        game_main._apply_combat_payload_effects(payload, combat, characters, "pc", game_state=state, current_loc="room")
        game_main._apply_combat_payload_effects(payload, combat, characters, "pc", game_state=state, current_loc="room")
        result = dict(payload)
        commit_special_objective_completion(state, result, scenario, combat)
        self.assertEqual([e["event_type"] for e in state["unified_event_log"]], ["COMBAT_ACTION_RESOLVED", "SPECIAL_OBJECTIVE_COMPLETED"])
        self.assertEqual(scenario.current_phase, "clear")


if __name__ == "__main__":
    unittest.main()
