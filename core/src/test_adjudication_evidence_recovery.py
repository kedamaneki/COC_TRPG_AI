import json
import unittest
from pathlib import Path

import main as game_main
from CombatProgression import append_combat_event
from InvestigationFlow import append_investigation_event
from ScenarioManager import ScenarioManager
from DiceEngine import DiceEngine
from ObjectLifecycle import apply_object_transition


SCENARIO = Path(__file__).resolve().parent / "scenario_corbitt.json"


class AdjudicationEvidenceRecoveryTests(unittest.TestCase):
    def _scenario(self, location):
        manager = ScenarioManager(json.loads(SCENARIO.read_text(encoding="utf-8")))
        manager.location = location
        manager.current_phase = "investigation"
        return manager

    def test_san_loss_forms(self):
        cases = [
            ({"value": "0/1D4"}, ("0", "1D4")),
            ({"value": "0/1D3"}, ("0", "1D3")),
            ({"value": "1/1D6"}, ("1", "1D6")),
            ({"value": "1D4"}, ("0", "1D4")),
        ]
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(
                    (game_main._resolve_san_loss_dice(data, True),
                     game_main._resolve_san_loss_dice(data, False)),
                    expected,
                )

    def test_roll_contract_keeps_raw_and_final_result(self):
        result = game_main._attach_adjudication_evidence(
            {"success_level": 2}, adjudication_id="adj_test",
            actor_id="pc_01", target_id="wall", skill_or_stat="STR",
            dice_result={"target_value": 50, "roll": 59, "success_level": 1},
            modifier={"type": "LUCK_SPEND", "amount": 9,
                      "resource_before": 50, "resource_after": 41},
        )
        self.assertEqual(result["resolution_mode"], "ROLL")
        self.assertEqual((result["target_value"], result["roll"]), (50, 59))
        self.assertEqual(result["raw_result"], "FAILURE")
        self.assertEqual(result["final_result"], "REGULAR_SUCCESS")
        self.assertEqual(result["modifier"]["amount"], 9)

    def test_no_roll_is_explicit(self):
        result = game_main._attach_adjudication_evidence(
            {"success_level": 2}, adjudication_id="adj_auto",
            resolution_mode="NO_ROLL",
        )
        self.assertIsNone(result["roll"])
        self.assertIsNone(result["target_value"])
        self.assertEqual(result["automatic_result"], "REGULAR_SUCCESS")

    def test_simple_move_discards_synthetic_no_roll_evidence(self):
        result = game_main._attach_adjudication_evidence(
            {"success_level": 2, "location_changed": True, "new_location": "hall"},
            adjudication_id="adj_move", resolution_mode="NO_ROLL",
        )
        result = game_main._as_simple_move_lifecycle(
            result, action_id="move", from_location="entry",
        )
        self.assertEqual(result["event_type"], "LOCATION_CHANGE")
        self.assertEqual(result["from_location"], "entry")
        self.assertNotIn("resolution_mode", result)
        self.assertNotIn("adjudication_id", result)
        self.assertNotIn("adjudication", result)

    def test_investigation_unified_event_has_adjudication_tuple(self):
        state = {"unified_event_log": []}
        row = append_investigation_event(state, "INVESTIGATION_ROLLED", {
            "investigation_id": "inv_1", "adjudication_id": "adj_1",
            "actor_id": "pc_01", "target_id": "wall", "location": "cellar",
            "roll_required": True, "resolution_mode": "ROLL",
            "skill_id": "STR", "target_value": 50, "roll": 42,
            "result_level": 2, "raw_result": "REGULAR_SUCCESS",
            "final_result": "REGULAR_SUCCESS",
        })
        self.assertEqual(row["adjudication_id"], "adj_1")
        self.assertEqual((row["target_value"], row["roll"]), (50, 42))

    def test_combat_event_contract_and_termination(self):
        state = {"unified_event_log": []}
        row = append_combat_event(
            state, "COMBAT_ACTION_RESOLVED", adjudication_id="adj_combat",
            actor="pc_01", target="corbitt_floating_dagger",
            skill="近接戦闘", target_value=50, roll=20,
            raw_result="HARD_SUCCESS", final_result="HARD_SUCCESS",
            damage=1, HP_before=1, HP_after=0,
        )
        self.assertEqual(row["adjudication_id"], "adj_combat")
        self.assertEqual(row["resolution_mode"], "ROLL")
        self.assertEqual((row["target_value"], row["roll"]), (50, 20))

    def test_wall_break_uses_explicit_check_and_one_authoritative_result(self):
        success = self._scenario("corbitt_basement")
        required = success.get_required_check("break", "basement_planks")
        self.assertEqual(required["check_contract"], "OPPOSED_STR_CHECK")
        success.flags["basement_planks_broken"] = False
        success_result = success.process_action("break", "basement_planks", 2)
        self.assertTrue(success.flags["basement_planks_broken"])
        self.assertEqual(success_result["state_before"]["basement_planks_broken"], False)
        self.assertEqual(success_result["state_after"]["basement_planks_broken"], True)
        self.assertIn("basement_planks__success", success_result["trigger_event_id"])

        failure = self._scenario("corbitt_basement")
        failure.flags["basement_planks_broken"] = False
        failure_result = failure.process_action("break", "basement_planks", 1)
        self.assertFalse(failure.flags["basement_planks_broken"])
        self.assertIn("basement_planks__failure", failure_result["trigger_event_id"])
        self.assertNotEqual(failure_result["system_log"], success_result["system_log"])

    def test_knife_encounter_defines_complete_combat_contract(self):
        scenario = self._scenario("corbitt_basement")
        scenario.flags["has_corbitt_knife"] = False
        result = scenario.process_action("inspect", "corbitt_knife", 2)
        combat = result["combat_start"]
        self.assertEqual(combat["enemies"], ["corbitt_floating_dagger"])
        self.assertEqual(combat["combat_goal"], "ENEMY_DEFEATED")
        self.assertEqual(combat["termination"]["type"], "ENEMY_INCAPACITATED")
        self.assertEqual(combat["termination"]["enemy_id"], "corbitt_floating_dagger")
        self.assertEqual(combat["trigger_event_id"], result["trigger_event_id"])
        knife = scenario.flags["object_states"]["corbitt_knife"]
        self.assertEqual(knife["status"], "IN_COMBAT")
        self.assertFalse(knife["available"])
        self.assertFalse(scenario.flags["has_corbitt_knife"])

    def test_examine_does_not_claim_door_or_wall_destroyed(self):
        door = self._scenario("corbitt_ground_floor")
        door.flags["basement_door_examined"] = False
        result = door.process_action("inspect", "basement_door", 2)
        self.assertIn("まだ閉ざされている", result["system_log"])
        self.assertNotIn("確定手がかり", result["system_log"])
        self.assertFalse(door.flags.get("basement_door_unlocked", False))

        wall = self._scenario("corbitt_basement")
        wall.flags.update({"basement_planks_examined": False, "basement_planks_broken": False})
        result = wall.process_action("inspect", "basement_planks", 2)
        self.assertIn("壊す必要", result["system_log"])
        self.assertFalse(wall.flags["basement_planks_broken"])

    def test_nested_success_san_effect_is_mandatory(self):
        scenario = self._scenario("corbitt_ground_floor")
        scenario.flags["living_room_investigated"] = False
        result = scenario.process_action("inspect", "living_room_clutter", 3)
        self.assertTrue(result["san_check"]["required"])
        self.assertEqual(result["san_check"]["value"].upper(), "0/1D3")
        self.assertEqual(result["trigger_event_id"], "corbitt_ground_floor__living_room_clutter__success")

    def test_opposed_roll_has_both_authoritative_tuples(self):
        result = DiceEngine().execute_opposed_str_roll("PC", 60, "板", 50)
        self.assertEqual(result["resolution_mode"], "ROLL")
        self.assertEqual(result["target_value"], 60)
        self.assertIsNotNone(result["roll"])
        opposed = result["opposed_roll"]
        for side in ("actor", "opponent"):
            self.assertIsNotNone(opposed[side]["target_value"])
            self.assertIsNotNone(opposed[side]["roll"])
            self.assertIsNotNone(opposed[side]["result"])

    def test_object_lifecycle_rejects_destroyed_to_owned(self):
        states = {"knife": {"status": "UNDISCOVERED", "destroyed": False}}
        apply_object_transition(states, "knife", {"status": "IN_COMBAT", "transition_path": ["AVAILABLE", "IN_COMBAT"]})
        apply_object_transition(states, "knife", {"status": "DESTROYED", "destroyed": True})
        self.assertIsNone(states["knife"]["owner_id"])
        with self.assertRaisesRegex(ValueError, "OBJECT_STATE_INVALID_TRANSITION"):
            apply_object_transition(states, "knife", {"status": "OWNED", "owner_id": "pc_01"})

    def test_final_battle_break_body_no_longer_auto_clears(self):
        """WP-A: break+corbitt_body must not SPECIAL auto-clear (Route A/B only)."""
        from CorbittKillRoutes import remap_body_break_to_attack

        scenario = self._scenario("corbitt_basement_room2")
        scenario.flags.update({
            "corbitt_defeated": False,
            "corbitt_body_encountered": True,
            "learned_corbitt_weakness": False,
        })
        result = scenario.process_action("break", "corbitt_body", 2)
        self.assertFalse(bool(result.get("combat_end")))
        self.assertNotEqual(
            (result.get("world_fact") or {}).get("event"),
            "SPECIAL_OBJECTIVE_COMPLETED",
        )
        self.assertFalse(bool(scenario.flags.get("corbitt_defeated")))
        remap = remap_body_break_to_attack("break", "corbitt_body", scenario_mgr=scenario)
        self.assertTrue(remap["remapped"])
        self.assertEqual(remap["action_id"], "attack")
        self.assertEqual(remap["target"], "walter_corbitt")


if __name__ == "__main__":
    unittest.main()
