"""Regression for the V5 Roxbury investigation ROLL producer failure."""

from __future__ import annotations

import unittest
from unittest import mock

from AdjudicationEvidence import EvidenceContractError
from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from InvestigationFlow import append_investigation_event, finalize_investigation
from ScenarioManager import ScenarioManager
import main


def _roxbury_fixture():
    return {
        "scenario_meta": {"title": "V5 investigation evidence", "initial_location": "roxbury_sanitarium"},
        "initial_state": {
            "current_phase": "investigation",
            "location": "roxbury_sanitarium",
            "turn_counter": 0,
            "flags": {"sanitarium_info_found": False},
        },
        "locations": {
            "roxbury_sanitarium": {
                "name": "ロックスベリー・サナトリウム",
                "objects": {
                    "patient_records": {
                        "name": "患者記録・カルテ",
                        "required_skill": ["医学", "図書館", "説得", "精神分析", "隠密"],
                        "difficulty": "通常",
                        "usable_actions": ["search", "inspect"],
                        "investigated_flag": "sanitarium_info_found",
                    }
                },
                "exits": {},
            }
        },
        "event_triggers": [],
    }


class TestV5InvestigationRollEvidence(unittest.TestCase):
    @staticmethod
    def _complete_roll_ctx():
        return {
            "investigation_id": "inv_complete", "adjudication_id": "adj_complete",
            "actor_id": "pc_01", "target_id": "patient_records",
            "location": "roxbury_sanitarium", "skill_id": "医学",
            "skill_or_stat": "医学", "roll_required": True,
            "resolution_mode": "ROLL", "target_value": 1, "roll": 55,
            "raw_result": "FAILURE", "final_result": "FAILURE",
        }

    def test_untrained_medicine_still_produces_authoritative_roll_evidence(self):
        """V5 pc_01 had no explicit Medicine entry; the base chance must roll."""
        scenario = ScenarioManager(_roxbury_fixture())
        char_mgr = mock.Mock()
        char_mgr.get_skill.side_effect = lambda _pc, skill: CharacterManager.BASE_SKILLS.get(skill, 0)
        char_mgr.can_offer_luck_burn.return_value = False
        char_mgr.mark_skill_success = mock.Mock()
        char_mgr.characters = {}
        char_mgr.active_pc_list = ["pc_01"]
        dice = DiceEngine()
        state = {"unified_event_log": [], "last_pl_action": {"skill_proposal_reason": "カルテを読む"}}

        with mock.patch.object(scenario, "evaluate_pre_action_guard", return_value=None), \
             mock.patch.object(scenario, "process_action", return_value={"kp_instruction": "ok"}), \
             mock.patch("DiceEngine.random.randint", side_effect=[5, 5]):
            result = main.process_system_action(
                "pc_01", "マクガフィン刑事", "search", "patient_records", "目星",
                "roxbury_sanitarium", char_mgr, dice, scenario, game_state=state,
            )

        self.assertEqual(result["resolution_mode"], "ROLL")
        self.assertEqual(result["skill_or_stat"], "医学")
        self.assertEqual(result["target_value"], 1)
        self.assertEqual(result["roll"], 55)
        self.assertEqual(result["raw_result"], "FAILURE")
        self.assertNotEqual(result.get("evidence_contract_status"), "TRANSIENT_INCOMPLETE")
        finalized = finalize_investigation(
            state, result, {"transaction_id": "tx_v5_fixture"}, active_pc_ids=["pc_01"],
        )
        self.assertIsNotNone(finalized)
        rolled = [e for e in state["unified_event_log"] if e.get("event_type") == "INVESTIGATION_ROLLED"]
        self.assertEqual(len(rolled), 1)
        self.assertEqual(rolled[0]["roll"], 55)

    def test_complete_roll_evidence_is_accepted(self):
        state = {"unified_event_log": []}
        row = append_investigation_event(
            state, "INVESTIGATION_ROLLED", self._complete_roll_ctx(),
        )
        self.assertEqual(row["adjudication_id"], "adj_complete")

    def test_each_required_roll_field_remains_fail_closed(self):
        for missing in ("target_value", "roll", "raw_result"):
            with self.subTest(missing=missing):
                state = {"unified_event_log": []}
                ctx = self._complete_roll_ctx()
                ctx.pop(missing)
                with self.assertRaises(EvidenceContractError):
                    append_investigation_event(state, "INVESTIGATION_ROLLED", ctx)

    def test_valid_no_roll_investigation_is_accepted(self):
        state = {"unified_event_log": []}
        ctx = {
            "investigation_id": "inv_no_roll", "adjudication_id": "adj_no_roll",
            "actor_id": "pc_01", "target_id": "public_notice",
            "location": "roxbury_sanitarium", "skill_id": "__NO_ROLL__",
            "resolution_mode": "NO_ROLL", "adjudication_id": "adj_no_roll",
            "resolution_reason": "SCENARIO_NO_ROLL", "final_result": "REGULAR_SUCCESS",
        }
        row = append_investigation_event(state, "ROLL_NOT_REQUIRED", ctx)
        self.assertEqual(row["resolution_mode"], "NO_ROLL")
        self.assertEqual(row["resolution_reason"], "SCENARIO_NO_ROLL")

    def test_non_investigation_wait_is_unaffected(self):
        scenario = ScenarioManager(_roxbury_fixture())
        char_mgr = mock.Mock()
        result = main.process_system_action(
            "pc_01", "マクガフィン刑事", "wait", "", "",
            "roxbury_sanitarium", char_mgr, DiceEngine(), scenario,
        )
        self.assertNotIn("investigation", result)
        self.assertEqual(result["resolution_mode"], "NO_ROLL")

    def test_incomplete_roll_remains_fail_closed(self):
        state = {"unified_event_log": []}
        ctx = {
            "investigation_id": "inv_bad", "adjudication_id": "adj_bad",
            "actor_id": "pc_01", "target_id": "patient_records",
            "location": "roxbury_sanitarium", "skill_id": "医学",
            "roll_required": True, "attempt_allowed": True,
            "attempt_right_before": "AVAILABLE", "context_version": "v5",
        }
        result = {
            "investigation": ctx, "success_level": 1, "status": 1,
            "resolution_mode": "ROLL", "skill_or_stat": "医学",
            "adjudication_id": "adj_bad", "final_result": "FAILURE",
        }
        with self.assertRaises(EvidenceContractError):
            finalize_investigation(state, result, {}, active_pc_ids=["pc_01"])


if __name__ == "__main__":
    unittest.main()
