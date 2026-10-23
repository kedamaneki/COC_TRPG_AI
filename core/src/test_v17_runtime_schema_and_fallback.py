"""V17 RecentAction schema, contract policy, SAFE_LEGACY, progress, counters."""

from __future__ import annotations

import unittest

from reasoning.recent_action import (
    RecentAction,
    RecentActionContractError,
    normalize_recent_action,
    normalize_recent_actions,
    make_recent_action,
    RECENT_ACTION_SCHEMA_VERSION,
)
from reasoning.error_class import (
    classify_exception,
    NDMRuntimeContractViolation,
    SafeFallbackFailure,
    PROGRAMMING_ERROR,
    RUNTIME_CONTRACT_VIOLATION,
)
from reasoning.progress_events import (
    make_progress_event,
    append_progress_event,
    progress_events_for_ndm,
    emit_progress_from_director_delta,
)
from reasoning.runtime import (
    NaturalDecisionRuntime,
    bootstrap_natural_decision,
    DECISION_SOURCE_NDM,
    DECISION_SOURCE_SAFE_LEGACY,
)
from ProgressDirectorV2 import StallDetectorV2


class RecentActionTests(unittest.TestCase):
    def test_ra1_legacy_list_to_canonical(self):
        ra = normalize_recent_action(["search", "desk"])
        self.assertEqual(ra.schema_version, RECENT_ACTION_SCHEMA_VERSION)
        self.assertEqual(ra.action, "search")
        self.assertEqual(ra.target, "desk")

    def test_ra2_canonical_dict_pass(self):
        raw = make_recent_action(action="move", target="hall", actor_id="pc_01")
        ra = normalize_recent_action(raw)
        self.assertEqual(ra.action, "move")
        self.assertEqual(ra.actor_id, "pc_01")

    def test_ra3_unknown_list_shape_violation(self):
        with self.assertRaises(RecentActionContractError):
            normalize_recent_action(["only_action"])
        with self.assertRaises(RecentActionContractError):
            normalize_recent_action(["a", "b", "c"])

    def test_ra4_required_field_missing(self):
        with self.assertRaises(RecentActionContractError):
            normalize_recent_action({"schema_version": 1, "target": "x"})


class RuntimeContractTests(unittest.TestCase):
    def test_rc1_attribute_error_not_safe_legacy(self):
        classified = classify_exception(AttributeError("'list' object has no attribute 'get'"))
        self.assertEqual(classified.error_class, PROGRAMMING_ERROR)
        self.assertFalse(classified.fallback_eligible)

    def test_rc2_timeout_fallback_eligible(self):
        classified = classify_exception(TimeoutError("provider timeout"))
        self.assertTrue(classified.fallback_eligible)

    def test_rc3_unsupported_schema_blocks(self):
        with self.assertRaises(RecentActionContractError):
            normalize_recent_action({"schema_version": 99, "action": "x", "target": "y"})

    def test_decide_malformed_recent_blocks(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        with self.assertRaises(NDMRuntimeContractViolation):
            rt.decide(
                state,
                actor_id="pc_01",
                candidates=[{"action": "search", "target": "a", "reason": "t", "candidate_id": "c1"}],
                recent_actions=[["bad", "shape", "extra"]],
            )
        self.assertGreaterEqual(rt.telemetry.RUNTIME_CONTRACT_VIOLATION_COUNT, 1)
        self.assertEqual(rt.telemetry.SAFE_LEGACY_DECISION_COMMIT_COUNT, 0)


class SafeFallbackTests(unittest.TestCase):
    def test_sf1_recoverable_safe_legacy_commit(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        # Force recoverable path via _fallback_select directly
        selected = rt._fallback_select(
            state,
            actor_id="pc_01",
            candidates=[{"action": "search", "target": "desk", "reason": "recover", "candidate_id": "c1"}],
            candidate_set_id="cset_test",
            decision_transaction_id="dtx_test",
            failure_reason="simulated recoverable",
            failure_class="RECOVERABLE_REASONING_FAILURE",
            recent_actions=[],
        )
        self.assertEqual(selected.get("decision_source"), DECISION_SOURCE_SAFE_LEGACY)
        self.assertEqual(rt.telemetry.SAFE_LEGACY_DECISION_COMMIT_COUNT, 1)
        self.assertEqual(rt.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT, 0)
        self.assertEqual(rt.telemetry.NDM_DECISION_COMMIT_COUNT, 0)

    def test_sf2_fallback_failure_blocks(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        with self.assertRaises(SafeFallbackFailure):
            rt._fallback_select(
                state,
                actor_id="pc_01",
                candidates=[{"action": "search", "target": "desk", "reason": "x", "candidate_id": "c1"}],
                candidate_set_id="cset_test",
                decision_transaction_id="dtx_test",
                failure_reason="x",
                recent_actions=[["bad", "len", "3"]],
            )
        self.assertGreaterEqual(rt.telemetry.SAFE_FALLBACK_FAILURE_COUNT, 1)

    def test_sf3_no_fallback_recursion(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        with self.assertRaises(SafeFallbackFailure):
            rt._fallback_select(
                state,
                actor_id="pc_01",
                candidates=[{"action": "wait", "target": "", "reason": "x", "candidate_id": "c1"}],
                candidate_set_id="cset_test",
                decision_transaction_id="dtx_test",
                failure_reason="x",
                recent_actions=[],
                _depth=1,
            )
        self.assertGreaterEqual(rt.telemetry.SAFE_FALLBACK_RECURSION_COUNT, 1)


class ProgressTelemetryTests(unittest.TestCase):
    def test_pt1_new_fact_event(self):
        ev = make_progress_event(progress_type="NEW_FACT", actor_id="pc_01")
        self.assertEqual(ev["progress_type"], "NEW_FACT")
        self.assertEqual(ev["kind"], "new_fact")

    def test_pt2_state_change_from_director(self):
        state = {"director_v2": {"goal": {}}}
        emitted = emit_progress_from_director_delta(
            state,
            progress={"progress_delta": 1, "flags_changed": True, "progress_reason": ["flag"]},
            actor_id="pc_01",
        )
        self.assertGreaterEqual(len(emitted), 1)
        self.assertTrue(progress_events_for_ndm(state))

    def test_pt3_self_recovery_counter_path(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        # Simulate assessment-driven self recovery increment
        rt.telemetry.self_recovery_count += 1
        rates = rt.telemetry.rates()
        self.assertIn("SELF_RECOVERY_RATE", rates)
        self.assertIsInstance(rates["SELF_RECOVERY_RATE"], float)

    def test_pt4_meaningful_progress_rate_positive(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        pev = make_progress_event(progress_type="NEW_LOCATION", actor_id="pc_01")
        append_progress_event(state, pev)
        selected = rt.decide(
            state,
            actor_id="pc_01",
            candidates=[{"action": "move", "target": "hall", "reason": "go", "candidate_id": "c1"}],
            recent_actions=[],
            progress_events=progress_events_for_ndm(state),
        )
        self.assertEqual(selected.get("decision_source"), DECISION_SOURCE_NDM)
        rates = rt.telemetry.rates()
        self.assertIsInstance(rates["MEANINGFUL_PROGRESS_RATE"], float)
        self.assertGreater(rt.telemetry.meaningful_progress_count, 0)


class CounterTests(unittest.TestCase):
    def test_c1_ndm_commit_only(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        rt.decide(
            state,
            actor_id="pc_01",
            candidates=[{"action": "search", "target": "a", "reason": "r", "candidate_id": "c1"}],
            recent_actions=[],
        )
        self.assertEqual(rt.telemetry.NDM_DECISION_COMMIT_COUNT, 1)
        self.assertEqual(rt.telemetry.SAFE_LEGACY_DECISION_COMMIT_COUNT, 0)
        self.assertEqual(rt.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT, 0)

    def test_c2_safe_legacy_counter_distinct(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        rt._fallback_select(
            state,
            actor_id="pc_01",
            candidates=[{"action": "wait", "target": "", "reason": "r", "candidate_id": "c1"}],
            candidate_set_id="cset",
            decision_transaction_id="dtx",
            failure_reason="x",
            recent_actions=[],
        )
        self.assertEqual(rt.telemetry.SAFE_LEGACY_DECISION_COMMIT_COUNT, 1)
        self.assertEqual(rt.telemetry.NDM_DECISION_COMMIT_COUNT, 0)
        self.assertEqual(rt.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT, 0)

    def test_c3_unsafe_legacy_increments(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        with self.assertRaises(Exception):
            rt.assert_commit_bound({"decision_source": "legacy_stall_detector", "reasoning_id": "x"})
        self.assertEqual(rt.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT, 1)

    def test_c4_contract_violation_counter(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        with self.assertRaises(NDMRuntimeContractViolation):
            rt.decide(
                state,
                actor_id="pc_01",
                candidates=[{"action": "a", "target": "b", "reason": "r", "candidate_id": "c1"}],
                recent_actions=[["x"]],
            )
        self.assertGreaterEqual(rt.telemetry.RUNTIME_CONTRACT_VIOLATION_COUNT, 1)


class StallDetectorCanonicalWriteTests(unittest.TestCase):
    def test_new_write_is_canonical_dict(self):
        state = StallDetectorV2.update(
            {}, action="search", target="desk",
            location_before="study", location_after="study", progress_delta=0,
        )
        recent = state["recent_actions"]
        self.assertTrue(recent)
        self.assertIsInstance(recent[0], dict)
        self.assertEqual(recent[0]["schema_version"], RECENT_ACTION_SCHEMA_VERSION)
        self.assertEqual(recent[0]["action"], "search")
        # Adapter still accepts legacy lists when reading mixed history
        mixed = normalize_recent_actions([["move", "hall"], recent[0]])
        self.assertEqual(len(mixed), 2)


class LegacyListNoLongerBreaksNdm(unittest.TestCase):
    def test_legacy_recent_actions_adapt_and_ndm_commits(self):
        state = {"director_v2": {}, "ndm_runtime": {}}
        rt = bootstrap_natural_decision(state, enabled=True, required=True)
        selected = rt.decide(
            state,
            actor_id="pc_01",
            candidates=[{"action": "search", "target": "desk", "reason": "look", "candidate_id": "c1"}],
            recent_actions=[["talk", "npc"], ["move", "lib"], ["search", "paper"]],
        )
        self.assertEqual(selected.get("decision_source"), DECISION_SOURCE_NDM)
        self.assertEqual(rt.telemetry.RUNTIME_CONTRACT_VIOLATION_COUNT, 0)
        self.assertEqual(rt.telemetry.NDM_DECISION_COMMIT_COUNT, 1)


if __name__ == "__main__":
    unittest.main()
