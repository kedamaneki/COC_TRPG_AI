import copy
import json
import unittest
from pathlib import Path

from ProgressDirectorV2 import ensure_director_state
from ScenarioManager import ScenarioManager


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "v6_chapel_stagnation_frontier.json"
SCENARIO = Path(__file__).resolve().parent / "scenario_corbitt.json"


class V6ProgressionStagnationV7Tests(unittest.TestCase):
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
            "director_v2": {"stall": copy.deepcopy(self.fixture["stall"])},
        }

    def test_v6_stagnation_state_selects_reachable_frontier(self):
        runtime = ensure_director_state(self.state, self.scenario)
        candidate = runtime["goal"]["candidate_next_actions"][0]
        self.assertEqual(candidate["action"], "climb")
        self.assertEqual(candidate["target"], "rotting_floorboards")
        self.assertEqual(candidate["reason"], "reachable_frontier_event_override")
        self.assertEqual(
            candidate["event_id"],
            "chapel_of_contemplation__rotting_floorboards__climb_out_success",
        )

    def test_frontier_event_clears_scoped_access_and_unlocks_exit(self):
        payload = self.scenario.process_action("climb", "rotting_floorboards", 2)
        self.assertEqual(
            payload["trigger_event_id"],
            "chapel_of_contemplation__rotting_floorboards__climb_out_success",
        )
        self.assertFalse(self.scenario.flags["chapel_cellar_entered"])
        self.assertFalse(self.scenario.flags["in_basement"])
        exits = {item["id"] for item in self.scenario.get_available_exits(self.scenario.location)}
        self.assertIn("the_neighborhood", exits)

    def test_uninvestigated_unavailable_target_is_not_resurrected(self):
        self.scenario.flags["investigated_targets"] = []
        self.scenario.flags["floorboards_examined"] = False
        runtime = ensure_director_state(self.state, self.scenario)
        self.assertFalse(any(
            item.get("target") == "rotting_floorboards"
            for item in runtime["goal"]["candidate_next_actions"]
        ))


if __name__ == "__main__":
    unittest.main()
