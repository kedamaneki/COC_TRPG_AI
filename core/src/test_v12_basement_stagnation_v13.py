import copy
import json
import unittest
from pathlib import Path

from ProgressDirectorV2 import (
    ProgressTrackerV2,
    apply_s4_candidate_override,
    ensure_director_state,
    mark_progression_adjudication_started,
)
from ScenarioManager import ScenarioManager


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "v12_basement_planks_stagnation.json"
SCENARIO = Path(__file__).resolve().parent / "scenario_corbitt.json"


class V12BasementStagnationV13Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data = json.loads(SCENARIO.read_text(encoding="utf-8"))
        self.scenario = ScenarioManager(copy.deepcopy(data))
        self.scenario.location = self.fixture["current_location"]
        self.scenario.current_phase = self.fixture["current_phase"]
        self.scenario.flags.update(copy.deepcopy(self.fixture["flags"]))
        self.state = {
            "current_loc": self.fixture["current_location"],
            "current_phase": self.fixture["current_phase"],
            "actor_id": "pc_01",
            "unified_event_log": [],
            "director_v2": {"stall": copy.deepcopy(self.fixture["stall"])},
        }

    def _runtime(self):
        return ensure_director_state(self.state, self.scenario)

    def test_historical_v12_state_is_reproduced(self):
        self.assertTrue(self.scenario.flags["basement_planks_examined"])
        self.assertFalse(self.scenario.flags["basement_planks_broken"])
        self.assertEqual(self.state["director_v2"]["stall"]["no_progress_streak"], 20)
        self.assertEqual(self.state["director_v2"]["stall"]["intervention_level"], "S4")
        self.assertEqual(self.fixture["historical_stop_reason"], "PROGRESSION_STAGNATION_UNRESOLVED")

    def test_break_force_push_are_distinct_executable_frontiers(self):
        runtime = self._runtime()
        candidates = runtime["goal"]["candidate_next_actions"]
        self.assertEqual([x["action"] for x in candidates], ["push", "force", "break"])
        for candidate in candidates:
            self.assertTrue(candidate["reachable"])
            self.assertTrue(candidate["executable"])
            self.assertEqual(candidate["blocked_reason"], "")
            self.assertTrue(candidate["adjudication_route"].startswith("SCENARIO_EVENT:"))
            self.assertEqual(
                candidate["expected_state_effect"]["flag_updates"]["basement_planks_broken"],
                True,
            )

    def test_s4_binds_then_rotates_after_legal_failures(self):
        runtime = self._runtime()
        runtime["stall"]["intervention_level"] = "S4"
        selected = []
        for _ in range(3):
            action = apply_s4_candidate_override(
                self.state, {"action": "move", "target": "corbitt_ground_floor"},
                scenario_mgr=self.scenario, actor="pc_01",
            )
            selected.append(action["action"])
            binding = action["progression_binding"]
            self.assertTrue(binding["selected"])
            self.assertTrue(binding["proposal_bound"])
            self.assertFalse(binding["adjudication_started"])
            mark_progression_adjudication_started(
                action,
                {"adjudication_id": f"adj_{len(selected)}", "resolution_mode": "ROLL"},
            )
            self.assertTrue(action["progression_binding"]["adjudication_started"])
        self.assertEqual(selected, ["push", "force", "break"])

    def test_s4_does_not_force_dice_success(self):
        self._runtime()["stall"]["intervention_level"] = "S4"
        action = apply_s4_candidate_override(
            self.state, {"action": "wait", "target": ""},
            scenario_mgr=self.scenario, actor="pc_01",
        )
        mark_progression_adjudication_started(
            action,
            {"adjudication_id": "adj_failed", "resolution_mode": "ROLL", "final_result": "FAILURE"},
        )
        self.assertTrue(action["progression_binding"]["adjudication_started"])
        self.assertFalse(self.scenario.flags["basement_planks_broken"])

    def test_all_frontiers_blocked_emits_formal_stop_reason(self):
        runtime = self._runtime()
        runtime["stall"]["intervention_level"] = "S4"
        for candidate in runtime["goal"]["candidate_next_actions"]:
            runtime.setdefault("forced_action_contexts", []).append("|".join((
                candidate["action"], candidate["target"],
                candidate["availability_context_version"],
            )))
        unchanged = apply_s4_candidate_override(
            self.state, {"action": "wait", "target": ""},
            scenario_mgr=self.scenario, actor="pc_01",
        )
        self.assertEqual(unchanged["action"], "wait")
        self.assertEqual(
            self.state["unified_event_log"][-1]["event_type"],
            "REACHABLE_FRONTIER_EXHAUSTED",
        )

    def test_successful_frontier_is_meaningful_progress(self):
        before = ProgressTrackerV2.snapshot(self.state, self.scenario)
        payload = self.scenario.process_action("break", "basement_planks", 2)
        after = ProgressTrackerV2.snapshot(self.state, self.scenario)
        delta = ProgressTrackerV2.evaluate(before, after, result=payload)
        self.assertTrue(self.scenario.flags["basement_planks_broken"])
        self.assertGreater(delta["progress_delta"], 0)


if __name__ == "__main__":
    unittest.main()
