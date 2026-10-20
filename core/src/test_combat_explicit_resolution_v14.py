"""Phase 1 WP-C: combat resolution class fail-closed fixtures."""
import unittest

from AdjudicationEvidence import EvidenceContractError, explicit_no_roll_evidence, no_roll_evidence
from CombatResolutionGuard import (
    DETERMINISTIC_RULE,
    EXPLICIT_NO_ROLL,
    ROLL,
    UNRESOLVED_COMBAT_ACTION,
    CombatResolutionError,
    declare_resolution_class,
    guard_special_objective_payload,
    is_irreversible_candidate,
    may_define_kill_route,
    validate_victory_provenance,
)
from CompletionAtomicity import CompletionAtomicityError, commit_special_objective_completion


class _Scenario:
    def __init__(self):
        self.flags = {"corbitt_defeated": True}
        self.current_phase = "investigation"


class _Combat:
    in_combat = False


def _source_world_fact(route="ROUTE_A_HP0"):
    return {
        "event": "SPECIAL_OBJECTIVE_COMPLETED",
        "target": "corbitt_body",
        "fact": "CORBITT_BODY_DESTROYED",
        "validated_kill_route_id": route,
        "fact_origin": "SOURCE",
        "source_rule_id": "CORBITT_HP0_DUST",
        "may_define_kill_route": True,
    }


class CombatExplicitResolutionV14Tests(unittest.TestCase):
    def test_implicit_combat_none_is_unresolved(self):
        with self.assertRaises(CombatResolutionError) as ctx:
            declare_resolution_class(
                in_combat=True,
                action_id="break",
                target="corbitt_body",
                roll_type="none",
                dice_skipped=True,
            )
        self.assertEqual(ctx.exception.code, UNRESOLVED_COMBAT_ACTION)

    def test_irreversible_outside_combat_also_requires_class(self):
        with self.assertRaises(CombatResolutionError):
            declare_resolution_class(
                in_combat=False,
                action_id="break",
                target="corbitt_body",
                payload={"world_fact": {"event": "SPECIAL_OBJECTIVE_COMPLETED"}},
                roll_type="none",
                dice_skipped=True,
            )

    def test_non_combat_trivial_may_omit_class(self):
        cls = declare_resolution_class(
            in_combat=False,
            action_id="move",
            target="hall",
            roll_type="none",
            dice_skipped=True,
        )
        self.assertEqual(cls, "")

    def test_explicit_no_roll_requires_fields(self):
        with self.assertRaises(CombatResolutionError):
            declare_resolution_class(
                resolution_class=EXPLICIT_NO_ROLL,
                in_combat=True,
                action_id="wait",
                payload={"resolution_class": EXPLICIT_NO_ROLL},
            )

    def test_explicit_no_roll_accepted(self):
        payload = {
            "resolution_class": EXPLICIT_NO_ROLL,
            "explicit_no_roll_reason": "post defeat narrative",
            "source_rule_id": "POST_DEFEAT_NARRATIVE",
            "deterministic_precondition": {"corbitt_defeated": True},
        }
        cls = declare_resolution_class(
            resolution_class=EXPLICIT_NO_ROLL,
            in_combat=True,
            action_id="inspect",
            target="corbitt_body",
            payload=payload,
        )
        self.assertEqual(cls, EXPLICIT_NO_ROLL)
        evidence = explicit_no_roll_evidence(
            adjudication_id="adj-1",
            reason="POST_DEFEAT_NARRATIVE",
            final_outcome="REGULAR_SUCCESS",
            explicit_no_roll_reason="post defeat narrative",
            source_rule_id="POST_DEFEAT_NARRATIVE",
            deterministic_precondition={"corbitt_defeated": True},
        )
        self.assertEqual(evidence["resolution_class"], EXPLICIT_NO_ROLL)

    def test_legacy_no_roll_without_class_still_valid_for_non_combat_evidence(self):
        row = no_roll_evidence(
            adjudication_id="adj-2",
            reason="SCENARIO_NO_ROLL",
            final_outcome="REGULAR_SUCCESS",
        )
        self.assertEqual(row["resolution_mode"], "NO_ROLL")

    def test_explicit_no_roll_evidence_rejects_incomplete(self):
        with self.assertRaises(EvidenceContractError):
            no_roll_evidence(
                adjudication_id="adj-3",
                reason="x",
                final_outcome="REGULAR_SUCCESS",
                resolution_class="EXPLICIT_NO_ROLL",
            )

    def test_so_without_validated_kill_blocked(self):
        with self.assertRaises(CombatResolutionError) as ctx:
            guard_special_objective_payload({
                "world_fact": {
                    "event": "SPECIAL_OBJECTIVE_COMPLETED",
                    "fact": "CORBITT_BODY_DESTROYED",
                },
            })
        self.assertEqual(ctx.exception.code, "SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE")

    def test_so_with_source_kill_passes(self):
        guard_special_objective_payload({"world_fact": _source_world_fact()})

    def test_completion_without_source_provenance_blocked(self):
        state = {
            "unified_event_log": [{
                "event_id": "evt-special",
                "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
                "adjudication_id": "adj-special",
                "target": "corbitt_body",
                "world_fact": {
                    "event": "SPECIAL_OBJECTIVE_COMPLETED",
                    "target": "corbitt_body",
                    "fact": "CORBITT_BODY_DESTROYED",
                },
            }],
        }
        scenario = _Scenario()
        with self.assertRaises(CompletionAtomicityError):
            commit_special_objective_completion(
                state,
                {
                    "completion_phase_deferred": "clear",
                    "adjudication_id": "adj-special",
                    "target": "corbitt_body",
                },
                scenario,
                _Combat(),
            )
        self.assertEqual(scenario.current_phase, "investigation")

    def test_completion_with_source_kill_commits(self):
        fact = _source_world_fact()
        state = {
            "unified_event_log": [{
                "event_id": "evt-special",
                "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
                "adjudication_id": "adj-special",
                "target": "corbitt_body",
                "world_fact": fact,
            }],
        }
        scenario = _Scenario()
        envelope = commit_special_objective_completion(
            state,
            {
                "completion_phase_deferred": "clear",
                "adjudication_id": "adj-special",
                "target": "corbitt_body",
                "world_fact": fact,
            },
            scenario,
            _Combat(),
        )
        self.assertEqual(scenario.current_phase, "clear")
        self.assertEqual(envelope["validated_kill_route_id"], "ROUTE_A_HP0")

    def test_adaptation_transform_cannot_define_kill_route(self):
        self.assertFalse(may_define_kill_route("ADAPTATION_TRANSFORM", True))
        with self.assertRaises(CombatResolutionError):
            validate_victory_provenance({
                "validated_kill_route_id": "ROUTE_A_HP0",
                "fact_origin": "ADAPTATION_INFERENCE",
            })

    def test_break_body_is_irreversible(self):
        self.assertTrue(
            is_irreversible_candidate("break", "corbitt_body", in_combat=True)
        )


if __name__ == "__main__":
    unittest.main()
