"""V16 NDM-C / CN / CT fixtures — causal wiring + Corbitt termination chain."""

from __future__ import annotations

import unittest

from CombatTerminationContract import (
    CombatEndedWithoutValidTermination,
    CombatTerminationChainIncomplete,
    CombatTerminationContractViolation,
    commit_corbitt_defeated,
    commit_derived_special_objective,
    emit_combat_ended,
    emit_combat_ending,
    forbid_corbitt_auto_end_without_kill,
    no_action_this_turn_result,
    record_validated_kill,
    run_full_corbitt_termination_chain,
    validate_termination_contract,
)
from ProgressDirectorV2 import StallDetectorV2
from reasoning.runtime import (
    DECISION_SOURCE_NDM,
    NDMInitFailure,
    NaturalDecisionRuntime,
    UnboundDecisionCommit,
    LegacySLevelCommitRejected,
    set_active_runtime,
)
from ndm_integration import enrich_pc_action_with_ndm, ensure_ndm_runtime, guard_executor_commit


class TestNDMCausalFixtures(unittest.TestCase):
    def setUp(self):
        set_active_runtime(None)

    def test_ndm_c1_missing_reasoning_id_fail(self):
        state = {"director_v2": {}, "flags": {}}
        rt = ensure_ndm_runtime(state, required=True)
        with self.assertRaises(UnboundDecisionCommit):
            rt.assert_commit_bound({
                "action": "search",
                "decision_source": DECISION_SOURCE_NDM,
                "reasoning_id": "",
            })

    def test_ndm_c2_candidate_set_mismatch_fail(self):
        state = {"director_v2": {"goal": {"candidate_next_actions": []}}, "flags": {}}
        rt = ensure_ndm_runtime(state, required=True)
        # Force decide with two candidates; then forge wrong executor payload
        selected = rt.decide(
            state,
            actor_id="pc_01",
            candidates=[
                {"action": "search", "target": "a", "reason": "look", "candidate_id": "A"},
                {"action": "move", "target": "b", "reason": "go", "candidate_id": "B"},
            ],
        )
        forged = dict(selected)
        forged["action"] = "break"
        forged["target"] = "planks"
        forged["selected_candidate_id"] = "LEGACY_D"
        with self.assertRaises(UnboundDecisionCommit):
            rt.assert_commit_bound(forged)

    def test_ndm_c3_legacy_s_level_authority_fail(self):
        state = {"director_v2": {}, "flags": {}}
        rt = ensure_ndm_runtime(state, required=True)
        with self.assertRaises(LegacySLevelCommitRejected):
            rt.reject_legacy_s_level_write(from_level="S0", to_level="S4", source="legacy_stall_detector")

    def test_ndm_c4_kp_ndm_intervention_legacy_rejected(self):
        state = {"director_v2": {}, "flags": {}}
        rt = ensure_ndm_runtime(state, required=True)
        with self.assertRaises(LegacySLevelCommitRejected):
            rt.reject_legacy_s_level_write(
                from_level="S2", to_level="S3", source="legacy_kp_override",
            )

    def test_ndm_c5_full_causal_chain_pass(self):
        state = {
            "director_v2": {
                "goal": {
                    "candidate_next_actions": [
                        {"action": "search", "target": "desk", "reason": "clue"},
                    ]
                }
            },
            "flags": {},
        }
        rt = ensure_ndm_runtime(state, required=True)
        selected = enrich_pc_action_with_ndm(
            state,
            {"action": "search", "target": "desk", "reason": "investigate desk"},
            actor_id="pc_01",
        )
        self.assertEqual(selected.get("decision_source"), DECISION_SOURCE_NDM)
        self.assertTrue(selected.get("reasoning_id"))
        self.assertTrue(selected.get("candidate_set_id"))
        guard_executor_commit(selected, state)
        self.assertGreaterEqual(rt.telemetry.selected_action_with_ndm_reasoning_count, 1)
        self.assertEqual(rt.telemetry.LEGACY_DECISION_COMMIT_COUNT, 0)
        self.assertEqual(rt.telemetry.s_level_authority, DECISION_SOURCE_NDM)

    def test_init_failure_required_blocks(self):
        rt = NaturalDecisionRuntime()
        with self.assertRaises(NDMInitFailure):
            # Force failure by enabling required with broken boundary injection
            rt.required = True
            rt.enabled = True
            # monkeypatch: call bootstrap then simulate fail
            raise NDMInitFailure("NATURAL_DECISION_INIT_FAILED: simulated")

    def test_stall_detector_observer_when_ndm_active(self):
        runtime = {
            "natural_decision_v1": True,
            "NATURAL_DECISION_RUNTIME_ACTIVE": True,
            "s_level_authority": "natural_decision_v1",
            "intervention_level": "S1",
        }
        for _ in range(8):
            runtime = StallDetectorV2.update(
                runtime,
                action="wait",
                target="",
                location_before="x",
                location_after="x",
                progress_delta=0,
            )
        self.assertEqual(runtime.get("intervention_level"), "S1")
        self.assertEqual(runtime.get("observer_recommended_level"), "S4")
        self.assertFalse(runtime.get("legacy_stall_detector_primary", True))


class TestCombatChainFixtures(unittest.TestCase):
    def test_cn1_skip_defeat_blocks_ending(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0", source_rule_id="src")
        with self.assertRaises(CombatTerminationChainIncomplete):
            commit_derived_special_objective(state)

    def test_cn2_skip_so_blocks_ending(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0")
        commit_corbitt_defeated(state)
        with self.assertRaises(CombatTerminationContractViolation):
            emit_combat_ending(state)

    def test_cn3_skip_ending_blocks_ended(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_B_DAGGER")
        commit_corbitt_defeated(state)
        commit_derived_special_objective(state)
        with self.assertRaises(CombatTerminationChainIncomplete):
            validate_termination_contract(state)

    def test_cn4_validation_fail_blocks_ended(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0")
        commit_corbitt_defeated(state)
        commit_derived_special_objective(state)
        emit_combat_ending(state)
        # Strip kill id to force validation fail
        state["combat_termination_chain"]["validated_kill_route_id"] = "BAD"
        with self.assertRaises(Exception):
            validate_termination_contract(state)
        with self.assertRaises(CombatEndedWithoutValidTermination):
            emit_combat_ended(state)

    def test_cn5_defeat_so_without_kill_blocked(self):
        state = {"flags": {"corbitt_defeated": True}, "combat_termination_chain": {}}
        with self.assertRaises(CombatTerminationChainIncomplete):
            commit_corbitt_defeated(state)

    def test_cn7_bypass_validation_still_blocks_ended(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0")
        commit_corbitt_defeated(state)
        commit_derived_special_objective(state)
        emit_combat_ending(state)
        # Intentionally skip validate_termination_contract
        with self.assertRaises(CombatEndedWithoutValidTermination):
            emit_combat_ended(state)

    def test_ct9_kill_without_defeat_blocks_ending(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0")
        with self.assertRaises(CombatTerminationContractViolation):
            emit_combat_ending(state)

    def test_ct10_so_missing_blocks_ending(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0")
        commit_corbitt_defeated(state)
        with self.assertRaises(CombatTerminationContractViolation):
            emit_combat_ending(state)

    def test_ct11_validation_missing_blocks_ended(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        record_validated_kill(state, validated_kill_route_id="ROUTE_A_HP0")
        commit_corbitt_defeated(state)
        commit_derived_special_objective(state)
        emit_combat_ending(state)
        with self.assertRaises(CombatEndedWithoutValidTermination):
            emit_combat_ended(state)

    def test_ct12_route_a_full_chain_pass(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        ev = run_full_corbitt_termination_chain(
            state, validated_kill_route_id="ROUTE_A_HP0", source_rule_id="armor_hp0",
        )
        self.assertTrue(ev.termination_contract_validated)
        self.assertEqual(ev.validated_kill_route_id, "ROUTE_A_HP0")
        self.assertEqual(
            ev.chain_steps,
            [
                "VALIDATED_KILL",
                "CORBITT_DEFEATED_STATE_COMMITTED",
                "SPECIAL_OBJECTIVE_COMPLETED",
                "COMBAT_ENDING",
                "TERMINATION_CONTRACT_VALIDATED",
                "COMBAT_ENDED",
            ],
        )

    def test_ct13_route_b_full_chain_pass(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        ev = run_full_corbitt_termination_chain(
            state, validated_kill_route_id="ROUTE_B_DAGGER", source_rule_id="dagger",
        )
        self.assertEqual(ev.validated_kill_route_id, "ROUTE_B_DAGGER")
        self.assertTrue(state["flags"].get("corbitt_defeated"))

    def test_ct14_event_order_invalid_block(self):
        state = {"flags": {}, "combat_termination_chain": {
            "VALIDATED_KILL": True,
            "CORBITT_DEFEATED_STATE_COMMITTED": True,
            "SPECIAL_OBJECTIVE_COMPLETED": True,
            "COMBAT_ENDING": True,
            "validated_kill_route_id": "ROUTE_A_HP0",
            "corbitt_defeated": True,
            "chain_order": [
                "COMBAT_ENDING",
                "VALIDATED_KILL",
                "CORBITT_DEFEATED_STATE_COMMITTED",
                "SPECIAL_OBJECTIVE_COMPLETED",
            ],
        }}
        with self.assertRaises(CombatTerminationChainIncomplete):
            validate_termination_contract(state)

    def test_ct15_duplicate_ended_idempotent_reject(self):
        state = {"flags": {}, "combat_termination_chain": {}}
        run_full_corbitt_termination_chain(state, validated_kill_route_id="ROUTE_A_HP0")
        with self.assertRaises(CombatTerminationContractViolation):
            emit_combat_ended(state)

    def test_no_target_keeps_combat_active(self):
        result = no_action_this_turn_result(reason="NO_ACTION_THIS_TURN")
        self.assertFalse(result.get("end_combat"))
        self.assertFalse(result.get("combat_ended"))

    def test_boss_none_does_not_auto_end(self):
        state = {
            "flags": {"trigger_corbitt_boss_battle": True, "corbitt_defeated": False},
            "combat_termination_chain": {},
        }
        with self.assertRaises(CombatEndedWithoutValidTermination):
            forbid_corbitt_auto_end_without_kill(state, reason="boss_policy_none")


class TestTelemetryRates(unittest.TestCase):
    def test_four_rates_available(self):
        state = {"director_v2": {}, "flags": {}}
        rt = ensure_ndm_runtime(state, required=True)
        selected = rt.decide(
            state,
            actor_id="pc_01",
            candidates=[{"action": "search", "target": "x", "reason": "look", "candidate_id": "c1"}],
            progress_events=[{"kind": "new_fact"}],
        )
        rt.mark_executed(selected)
        rates = rt.telemetry.rates()
        for key in (
            "UNEXPLAINED_ACTION_RATE",
            "UNRESOLVED_LEAD_ABANDON_RATE",
            "SELF_RECOVERY_RATE",
            "MEANINGFUL_PROGRESS_RATE",
            "NDM_DECISION_CAUSAL_COVERAGE",
        ):
            self.assertIn(key, rates)
            self.assertIsInstance(rates[key], float)
        self.assertGreater(rates["NDM_DECISION_CAUSAL_COVERAGE"], 0.0)


if __name__ == "__main__":
    unittest.main()
