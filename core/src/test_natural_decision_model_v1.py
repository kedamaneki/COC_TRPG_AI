"""Deterministic fixtures for TRPG Natural Decision Model V1 (R1–R10, G1–G4, K1–K5, amendments, vignette)."""

from __future__ import annotations

import unittest

from reasoning.evidence import build_reasoning_evidence
from reasoning.frontier_recovery import FrontierRecoveryPolicy, basement_plank_frontier_example
from reasoning.group_decision import GroupDeliberation, PlayerProposal, ProposalResponse, PlayerResponse
from reasoning.hypothesis_tracker import HypothesisTracker, Hypothesis
from reasoning.knowledge_boundary import (
    EpistemicKind,
    KnowledgeBoundaryError,
    KnownFactView,
    ReasoningKnowledgeBoundary,
)
from reasoning.kp_assessment import assess_party_progress, stall_weight
from reasoning.kp_intervention import InterventionRuntimeState, KPInterventionPolicy
from reasoning.lead_tracker import Lead, LeadStatus, LeadTracker
from reasoning.pl_policy import PLDecisionPolicy, UnexplainedActionError
from reasoning.pl_state import FailureClass, PLReasoningState, classify_failure_from_signals
from reasoning.pipeline import NaturalDecisionPipeline
from reasoning.safe_fallback import SafeLegacyProgression, FallbackUnboundedError, MAX_FALLBACK_STREAK


def _boundary_with(*fact_ids):
    b = ReasoningKnowledgeBoundary()
    for fid in fact_ids:
        b.add_fact(KnownFactView(fact_id=fid, kind=EpistemicKind.FACT, text=fid))
    return b


class TestKnowledgeBoundary(unittest.TestCase):
    def test_k1_reject_unobserved_fact(self):
        b = _boundary_with("seen_planks")
        with self.assertRaises(KnowledgeBoundaryError) as ctx:
            b.assert_pl_may_cite(["hidden_solution"])
        self.assertEqual(ctx.exception.code, "REASONING_KNOWLEDGE_LEAK")

    def test_k2_ungrounded_kp_hint(self):
        b = _boundary_with("seen_planks")
        with self.assertRaises(KnowledgeBoundaryError) as ctx:
            b.assert_kp_hint_grounded(facts_referenced=["secret_route"])
        self.assertEqual(ctx.exception.code, "UNGROUNDED_KP_HINT")

    def test_k3_speculation_not_promoted_to_fact(self):
        b = ReasoningKnowledgeBoundary()
        b.add_fact(KnownFactView(fact_id="maybe", kind=EpistemicKind.SPECULATION))
        with self.assertRaises(KnowledgeBoundaryError):
            b.assert_fact_kind_not_upgraded("maybe", EpistemicKind.FACT)

    def test_k4_hidden_frontier_leak(self):
        b = ReasoningKnowledgeBoundary()
        with self.assertRaises(KnowledgeBoundaryError) as ctx:
            b.assert_frontier_value_visible(["is_correct_path"])
        self.assertIn(ctx.exception.code, {
            "HIDDEN_CORRECT_PATH_SIGNAL",
            "HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK",
        })

    def test_k5_forbidden_keys_scrubbed(self):
        b = ReasoningKnowledgeBoundary()
        cleaned = b.scrub_forbidden_inputs({"ok": 1, "is_correct_path": True})
        self.assertIn("ok", cleaned)
        self.assertNotIn("is_correct_path", cleaned)


class TestLeadHypothesis(unittest.TestCase):
    def test_lead_high_value_rejects_hidden(self):
        tracker = LeadTracker()
        with self.assertRaises(KnowledgeBoundaryError):
            tracker.upsert(Lead(
                lead_id="secret",
                value_reasons=["is_correct_path"],
                high_value=True,
                unresolved=True,
            ))

    def test_lead_defer_keeps_unresolved(self):
        tracker = LeadTracker()
        tracker.upsert(Lead(
            lead_id="basement_planks",
            value_reasons=["known_unresolved_lead", "available_actions_remain"],
            high_value=True,
            unresolved=True,
            available_action_count=2,
        ))
        lead = tracker.defer("basement_planks", leave_reason="seek_better_tool")
        self.assertEqual(lead.status, LeadStatus.DEFERRED)
        self.assertTrue(lead.unresolved)
        frontiers = tracker.unresolved_high_value_frontier_set()
        self.assertTrue(any(f["frontier_id"] == "basement_planks" for f in frontiers))

    def test_hypothesis_support_contradict(self):
        ht = HypothesisTracker()
        ht.upsert(Hypothesis(hypothesis_id="h1", statement="planks hide passage"))
        ht.apply_outcome("h1", "support", fact_id="f1")
        hyp = ht.apply_outcome("h1", "contradict", fact_id="f2", delta=0.4)
        self.assertIn("f1", hyp.supporting_fact_ids)
        self.assertIn("f2", hyp.contradicting_fact_ids)


class TestPLDecision(unittest.TestCase):
    def test_r1_after_failure_consider_alternatives(self):
        b = _boundary_with("seen_planks")
        policy = PLDecisionPolicy(b)
        st = PLReasoningState(actor_id="pc_01", known_facts=["seen_planks"], high_value_leads=["basement_planks"])
        st.record_failure(action="break", target="basement_planks", failure_class=FailureClass.ATTEMPT_FAILED)
        suggestions = policy.suggest_after_failure(
            st, failed_action="break", failed_target="basement_planks",
            failure_class=FailureClass.ATTEMPT_FAILED,
        )
        actions = {s["action"] for s in suggestions}
        self.assertTrue({"push", "move", "search"} & actions)

    def test_r2_leave_with_reason(self):
        b = _boundary_with("seen_planks")
        policy = PLDecisionPolicy(b)
        st = PLReasoningState(
            actor_id="pc_01",
            known_facts=["seen_planks"],
            high_value_leads=["basement_planks"],
            leave_reason="seek_better_tool",
        )
        cands = [{
            "action": "move",
            "target": "corbitt_ground_floor",
            "reason": "seek crowbar upstairs",
            "leave_reason": "seek_better_tool",
            "supporting_knowledge": ["seen_planks"],
        }]
        chosen, evidence = policy.select(st, cands)
        self.assertEqual(chosen["action"], "move")
        self.assertTrue(evidence.selection_reason)

    def test_r2_leave_without_reason_blocked(self):
        policy = PLDecisionPolicy(_boundary_with("seen_planks"))
        st = PLReasoningState(actor_id="pc_01", high_value_leads=["basement_planks"])
        with self.assertRaises(ValueError):
            policy.select(st, [{
                "action": "move",
                "target": "elsewhere",
                "reason": "leave",
                "supporting_knowledge": [],
            }])

    def test_r3_unresolved_lead_preserved_on_defer(self):
        tracker = LeadTracker()
        tracker.upsert(Lead(
            lead_id="basement_planks",
            value_reasons=["known_unresolved_lead"],
            high_value=True,
            unresolved=True,
            available_action_count=1,
        ))
        tracker.defer("basement_planks", leave_reason="pursue_other_lead")
        self.assertTrue(tracker.get("basement_planks").unresolved)

    def test_r10_hidden_knowledge_blocked(self):
        b = _boundary_with("seen_planks")
        policy = PLDecisionPolicy(b)
        st = PLReasoningState(actor_id="pc_01", known_facts=["seen_planks"])
        with self.assertRaises(KnowledgeBoundaryError):
            policy.select(st, [{
                "action": "break",
                "target": "basement_planks",
                "reason": "because secret solution",
                "supporting_knowledge": ["author_route"],
            }])

    def test_unexplained_action_blocked(self):
        policy = PLDecisionPolicy(_boundary_with())
        st = PLReasoningState(actor_id="pc_01")
        with self.assertRaises(UnexplainedActionError):
            policy.select(st, [{"action": "wait", "reason": ""}])

    def test_failure_not_impossible_on_first(self):
        st = PLReasoningState(actor_id="pc_01")
        entry = st.record_failure(
            action="break", target="planks", failure_class=FailureClass.TARGET_IMPOSSIBLE,
        )
        self.assertEqual(entry.failure_class, FailureClass.ATTEMPT_FAILED)
        fc = classify_failure_from_signals(same_method_count=1, dice_failed=True)
        self.assertEqual(fc, FailureClass.BAD_LUCK)


class TestKPIntervention(unittest.TestCase):
    def test_r4_no_intervention_during_meaningful_elsewhere(self):
        policy = KPInterventionPolicy(s1_threshold=2, s2_threshold=4, s3_threshold=6, s4_threshold=8)
        runtime = InterventionRuntimeState(stall_score=5.0, current_s_level=2)
        # V18: full de-escalation requires goal-directed progress (linked lead/goal),
        # not lateral NEW_FACT alone.
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks", "library_clue"],
            progress_events=[{
                "kind": "new_fact",
                "progress_type": "NEW_FACT",
                "lead_ids": ["basement_planks"],
                "goal_ids": ["investigate_basement"],
            }],
            visible_goal_ids=["investigate_basement"],
            recent_actions=[{"action": "search", "target": "library"}],
        )
        self.assertTrue(assessment.goal_directed_progress_this_cycle)
        decision, runtime = policy.decide(assessment, runtime, frontier_set=["basement_planks"])
        self.assertEqual(decision.s_level, 0)
        self.assertTrue(decision.deescalated)

    def test_r5_repetition_s1(self):
        policy = KPInterventionPolicy(s1_threshold=1.0, s2_threshold=10, s3_threshold=20, s4_threshold=30)
        runtime = InterventionRuntimeState()
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks"],
            recent_actions=[
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
            ],
        )
        self.assertTrue(assessment.merely_repeating)
        decision, runtime = policy.decide(
            assessment, runtime, frontier_set=["basement_planks"], stall_increment=1.0,
        )
        self.assertGreaterEqual(decision.s_level, 1)

    def test_r6_forgotten_known_s2(self):
        policy = KPInterventionPolicy(s1_threshold=0.5, s2_threshold=1.0, s3_threshold=10, s4_threshold=20)
        runtime = InterventionRuntimeState(stall_score=1.0)
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks"],
            party_understanding=["seen_planks"],
            recent_actions=[
                {"action": "wait", "target": "chapel"},
                {"action": "wait", "target": "chapel"},
                {"action": "wait", "target": "chapel"},
            ],
        )
        decision, runtime = policy.decide(
            assessment, runtime, frontier_set=["basement_planks"], stall_increment=1.0,
        )
        self.assertGreaterEqual(decision.s_level, 2)
        self.assertFalse(decision.payload.get("new_information", True) if decision.s_level >= 2 else True)

    def test_r7_s3_soft_guidance(self):
        policy = KPInterventionPolicy(s1_threshold=0.1, s2_threshold=0.2, s3_threshold=0.3, s4_threshold=99)
        runtime = InterventionRuntimeState(stall_score=0.3)
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks"],
            recent_actions=[
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
            ],
        )
        decision, _ = policy.decide(
            assessment, runtime, frontier_set=["basement_planks", "magic_dagger"], stall_increment=1.0,
        )
        self.assertEqual(decision.s_level, 3)
        self.assertTrue(decision.payload.get("forbid_correct_action_name"))
        self.assertIn("basement_planks", decision.payload.get("attention_leads") or [])

    def test_r8_s4_frontier_recovery_not_solution(self):
        policy = KPInterventionPolicy(s1_threshold=0.1, s2_threshold=0.2, s3_threshold=0.3, s4_threshold=0.4)
        runtime = InterventionRuntimeState(stall_score=0.4)
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks", "magic_dagger"],
            recent_actions=[
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
            ],
        )
        decision, runtime = policy.decide(
            assessment, runtime,
            frontier_set=["basement_planks", "magic_dagger"],
            restore_location="corbitt_basement",
            stall_increment=1.0,
        )
        self.assertEqual(decision.s_level, 4)
        self.assertEqual(decision.payload.get("mode"), "FRONTIER_SET_RECOVERY")
        self.assertFalse(decision.payload.get("force_solution"))
        self.assertGreaterEqual(len(decision.payload.get("frontier_set") or []), 2)
        # grace prevents immediate re-S4
        assessment2 = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks"],
            recent_actions=[
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
            ],
        )
        d2, runtime = policy.decide(assessment2, runtime, frontier_set=["basement_planks"], stall_increment=1.0)
        self.assertTrue(d2.recovery_grace_active or d2.s_level == 0)

    def test_r9_multiple_frontiers_choice_preserved(self):
        fs = basement_plank_frontier_example()
        self.assertGreaterEqual(len(fs.frontier_ids), 2)
        self.assertFalse(fs.forced_solution)
        actions = FrontierRecoveryPolicy().recovery_actions(fs)
        self.assertTrue(all(not a.get("force_solution") for a in actions))
        self.assertTrue(any(a["action"] == "move" for a in actions))

    def test_amendment_s3_to_s0_on_progress(self):
        policy = KPInterventionPolicy()
        runtime = InterventionRuntimeState(current_s_level=3, stall_score=6.0)
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks"],
            progress_events=[{
                "kind": "new_viable_lead",
                "progress_type": "NEW_VIABLE_LEAD",
                "lead_ids": ["basement_planks"],
                "goal_ids": ["investigate_basement"],
            }],
            visible_goal_ids=["investigate_basement"],
        )
        self.assertTrue(assessment.goal_directed_progress_this_cycle)
        decision, runtime = policy.decide(assessment, runtime, frontier_set=["basement_planks"])
        self.assertEqual(decision.s_level, 0)
        self.assertEqual(runtime.current_s_level, 0)

    def test_amendment_s4_recovery_to_s0(self):
        policy = KPInterventionPolicy(recovery_grace_cycles=2)
        runtime = InterventionRuntimeState(current_s_level=4, stall_score=0.0)
        runtime = policy.complete_s4_recovery(runtime)
        self.assertEqual(runtime.current_s_level, 0)
        self.assertGreater(runtime.recovery_grace_remaining, 0)

    def test_escalation_suspended_on_hypothesis(self):
        policy = KPInterventionPolicy(s4_threshold=0.1)
        runtime = InterventionRuntimeState(stall_score=5.0, current_s_level=2)
        assessment = assess_party_progress(
            unresolved_leads=["basement_planks"],
            available_frontiers=["basement_planks"],
            hypothesis_tests=[{"hypothesis_id": "h1"}],
            recent_actions=[{"action": "push", "target": "basement_planks"}],
        )
        decision, _ = policy.decide(assessment, runtime, frontier_set=["basement_planks"], stall_increment=1.0)
        self.assertEqual(decision.reason, "escalation_suspended_rational_exploration")
        self.assertLess(stall_weight(assessment), 1.0)


class TestSafeFallback(unittest.TestCase):
    def test_fallback_excludes_exhausted_and_hidden(self):
        fb = SafeLegacyProgression(_boundary_with("seen"))
        selected, evidence = fb.select(
            [
                {"action": "break", "target": "planks", "hidden_solution": True},
                {"action": "break", "target": "planks", "goal_relevance": 1.0},
                {"action": "search", "target": "shelf", "goal_relevance": 0.5},
            ],
            failure_reason="exception",
            exhausted_attempts=[{"action": "break", "target": "planks"}],
            hidden_candidate_ids={"bad"},
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["action"], "search")
        self.assertEqual(evidence.code, "REASONING_MODEL_FALLBACK")
        self.assertIn("attempt_exhausted_filtering", evidence.guards_active)

    def test_fallback_streak_bounded(self):
        fb = SafeLegacyProgression(max_streak=2)
        fb.select([{"action": "wait"}], failure_reason="a")
        fb.select([{"action": "wait"}], failure_reason="b")
        with self.assertRaises(FallbackUnboundedError):
            fb.select([{"action": "wait"}], failure_reason="c")


class TestGroupDecision(unittest.TestCase):
    def test_g1_proposals_and_minority(self):
        g = GroupDeliberation()
        g.add_proposal(PlayerProposal(
            actor_id="pc_01",
            proposal={"action": "search", "target": "planks"},
            reason="investigate obstacle",
            confidence=0.8,
            role="investigate",
        ))
        g.add_proposal(PlayerProposal(
            actor_id="pc_02",
            proposal={"action": "wait", "target": ""},
            reason="watch for danger",
            confidence=0.4,
            role="watch",
        ))
        g.add_response(PlayerResponse(
            actor_id="pc_02", toward_actor_id="pc_01",
            response=ProposalResponse.AGREE, reason="ok",
        ))
        decision = g.decide()
        self.assertEqual(decision.executor, "pc_01")
        self.assertFalse(decision.auto_consensus_only)
        self.assertIn("pc_02", decision.role_assignments)

    def test_g2_counterproposal(self):
        g = GroupDeliberation()
        g.add_proposal(PlayerProposal(
            actor_id="pc_01", proposal={"action": "break"}, reason="force",
        ))
        g.add_response({
            "actor_id": "pc_02",
            "toward_actor_id": "pc_01",
            "response": "counterproposal",
            "reason": "try push instead",
            "counterproposal": {"action": "push"},
        })
        decision = g.decide()
        self.assertTrue(decision.minority_opinion)


class TestBasementVignette(unittest.TestCase):
    def test_basement_plank_reasonable_candidates_and_escalation(self):
        b = _boundary_with("basement_planks_examined")
        leads = LeadTracker(b)
        leads.upsert(Lead(
            lead_id="basement_planks",
            source_fact_ids=["basement_planks_examined"],
            value_reasons=["known_unresolved_lead", "unresolved_state", "available_actions_remain"],
            high_value=True,
            unresolved=True,
            available_action_count=3,
        ))
        leads.upsert(Lead(
            lead_id="magic_dagger",
            source_fact_ids=["basement_planks_examined"],
            value_reasons=["party_stated_interest"],
            high_value=True,
            unresolved=True,
            available_action_count=1,
        ))
        st = PLReasoningState(
            actor_id="pc_01",
            known_facts=["basement_planks_examined"],
            high_value_leads=["basement_planks", "magic_dagger"],
        )
        st.record_failure(action="break", target="basement_planks", failure_class=FailureClass.ATTEMPT_FAILED)
        policy = PLDecisionPolicy(b)
        suggestions = policy.suggest_after_failure(
            st, failed_action="break", failed_target="basement_planks",
            failure_class=FailureClass.ATTEMPT_FAILED,
        )
        self.assertTrue(any(s.get("leave_reason") == "seek_better_tool" for s in suggestions))

        # Temporary leave keeps lead
        leads.defer("basement_planks", leave_reason="seek_better_tool")
        self.assertTrue(leads.get("basement_planks").unresolved)

        # Escalation path S1→S4 recovery without forcing plank destruction
        kp = KPInterventionPolicy(
            s1_threshold=1, s2_threshold=2, s3_threshold=3, s4_threshold=4, recovery_grace_cycles=1,
        )
        runtime = InterventionRuntimeState()
        frontier_ids = [f["frontier_id"] for f in leads.unresolved_high_value_frontier_set()]
        for _ in range(5):
            assessment = assess_party_progress(
                unresolved_leads=frontier_ids,
                available_frontiers=frontier_ids,
                recent_actions=[
                    {"action": "wait", "target": "chapel"},
                    {"action": "wait", "target": "chapel"},
                    {"action": "wait", "target": "chapel"},
                ],
            )
            decision, runtime = kp.decide(
                assessment, runtime,
                frontier_set=frontier_ids,
                restore_location="corbitt_basement",
                stall_increment=1.0,
            )
            if decision.s_level == 4:
                break
        self.assertEqual(decision.s_level, 4)
        self.assertNotIn("break", str(decision.payload))
        recovery = FrontierRecoveryPolicy(b).recovery_actions(
            FrontierRecoveryPolicy(b).build_set(leads, restore_location="corbitt_basement")
        )
        self.assertTrue(any(a["action"] == "move" and a["target"] == "corbitt_basement" for a in recovery))
        self.assertFalse(any(a["action"] in {"break", "destroy"} for a in recovery))
        runtime = kp.complete_s4_recovery(runtime)
        self.assertEqual(runtime.current_s_level, 0)


class TestPipelineIntegration(unittest.TestCase):
    def test_reasoning_exception_safe_legacy(self):
        pipe = NaturalDecisionPipeline(boundary=_boundary_with("f1"))
        # Force exception path by monkeypatching select
        original = pipe.pl_policy.select

        def boom(*a, **k):
            raise RuntimeError("reasoning crashed")

        pipe.pl_policy.select = boom
        result = pipe.run_cycle(
            pl_states=[PLReasoningState(actor_id="pc_01", known_facts=["f1"])],
            candidate_actions_by_actor={
                "pc_01": [
                    {"action": "search", "target": "a", "reason": "look around", "goal_relevance": 1},
                    {
                        "action": "break",
                        "target": "planks",
                        "reason": "force obstacle",
                        "hidden_solution": True,
                        "goal_relevance": 9,
                    },
                ],
            },
        )
        pipe.pl_policy.select = original
        self.assertEqual(result.mode, "SAFE_LEGACY_PROGRESSION")
        self.assertIsNotNone(result.fallback)
        self.assertNotEqual((result.selected_action or {}).get("hidden_solution"), True)
        self.assertEqual((result.selected_action or {}).get("action"), "search")

    def test_knowledge_leak_reject_not_fallback(self):
        pipe = NaturalDecisionPipeline(boundary=_boundary_with("f1"))
        result = pipe.run_cycle(
            pl_states=[PLReasoningState(actor_id="pc_01", known_facts=["f1"])],
            candidate_actions_by_actor={
                "pc_01": [{
                    "action": "break",
                    "target": "x",
                    "reason": "secret",
                    "supporting_knowledge": ["hidden"],
                }],
            },
        )
        self.assertEqual(result.mode, "REJECT")

    def test_evidence_no_cot(self):
        ev = build_reasoning_evidence(
            actor_id="pc_01",
            selection_reason="investigate",
            extras={"chain_of_thought": "secret thoughts", "ok": 1},
        )
        data = ev.to_dict()
        self.assertNotIn("chain_of_thought", data["extras"])
        self.assertEqual(data["extras"].get("ok"), 1)


class TestHiddenOnlyFrontierRejected(unittest.TestCase):
    def test_hidden_only_frontier_rejected(self):
        b = ReasoningKnowledgeBoundary()
        with self.assertRaises(KnowledgeBoundaryError) as ctx:
            b.assert_frontier_value_visible({
                "is_correct_path": True,
                "distance_to_solution": 1,
            })
        self.assertEqual(ctx.exception.code, "HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK")


if __name__ == "__main__":
    unittest.main()
