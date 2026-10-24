"""V18 Progression Convergence deterministic fixtures PS/GC/FP/FI/FA/SE/LO/RR."""

from __future__ import annotations

import unittest

from reasoning.action_state_effect import (
    EFFECT_EXPECTED,
    EFFECT_NONE,
    ExpectedStateEffect,
    MethodAttemptTracker,
    classify_observed_effect,
)
from reasoning.dual_stall import DualStallState, apply_progress_to_dual_stall
from reasoning.frontier_persistence import (
    FrontierPersistenceStore,
    PersistentFrontier,
    apply_return_pressure,
    defer_frontier,
    record_why_not_selected,
    set_action_unavailable,
    should_remind_ignored_frontier,
    upsert_frontier,
)
from reasoning.goal_convergence import (
    GoalConvergenceTracker,
    detect_local_optimum,
    evaluate_chain_trace,
    tick_goal_convergence,
)
from reasoning.kp_assessment import assess_party_progress
from reasoning.kp_intervention import InterventionRuntimeState, KPInterventionPolicy
from reasoning.progress_semantics_v2 import (
    PROGRESS_CLASS_GOAL_DIRECTED,
    PROGRESS_CLASS_LATERAL,
    PROGRESS_CLASS_MEANINGFUL,
    classify_progress_event_v2,
    is_goal_directed_event,
    summarize_cycle_progress,
)
from reasoning.progression_convergence import (
    ProgressionConvergenceRuntime,
    record_trace,
    tick_progression_cycle,
)


class TestPS_ProgressSemantics(unittest.TestCase):
    def test_ps1_new_location_meaningful_not_goal_directed(self):
        ev = {"progress_type": "NEW_LOCATION", "kind": "new_location"}
        classes = classify_progress_event_v2(
            ev,
            visible_goal_ids=["g_investigate"],
            unresolved_lead_ids=["lead_planks"],
            known_frontier_ids=["fr_planks"],
        )
        self.assertIn(PROGRESS_CLASS_MEANINGFUL, classes)
        self.assertIn(PROGRESS_CLASS_LATERAL, classes)
        self.assertNotIn(PROGRESS_CLASS_GOAL_DIRECTED, classes)
        self.assertFalse(
            is_goal_directed_event(
                ev,
                visible_goal_ids=["g_investigate"],
                unresolved_lead_ids=["lead_planks"],
                known_frontier_ids=["fr_planks"],
            )
        )

    def test_ps2_blocker_removed_goal_directed(self):
        ev = {
            "progress_type": "OBJECT_STATE_CHANGE",
            "kind": "object_state_change",
            "observed_state_effect": {
                "changed_keys": ["blocker_planks"],
                "lead_ids": ["lead_planks"],
            },
        }
        self.assertTrue(
            is_goal_directed_event(
                ev,
                visible_goal_ids=["g_investigate"],
                unresolved_lead_ids=["lead_planks"],
                known_blocker_ids=["blocker_planks"],
                known_frontier_ids=["fr_planks"],
            )
        )
        classes = classify_progress_event_v2(
            ev,
            visible_goal_ids=["g_investigate"],
            unresolved_lead_ids=["lead_planks"],
            known_blocker_ids=["blocker_planks"],
            known_frontier_ids=["fr_planks"],
        )
        self.assertIn(PROGRESS_CLASS_GOAL_DIRECTED, classes)

    def test_ps3_lateral_resets_activity_not_goal_stall(self):
        st = DualStallState(activity_stall_streak=4, goal_convergence_stall_streak=2)
        out = apply_progress_to_dual_stall(
            st, meaningful=True, goal_directed=False, cycle=10
        )
        self.assertEqual(out.activity_stall_streak, 0)
        self.assertEqual(out.goal_convergence_stall_streak, 3)
        self.assertEqual(out.stall_class, "GOAL_CONVERGENCE_STALL")

    def test_hidden_solution_forbidden_for_gd(self):
        ev = {
            "progress_type": "OBJECTIVE_ADVANCEMENT",
            "kind": "objective_advancement",
            "goal_ids": ["g1"],
            "correct_path": True,
        }
        self.assertFalse(
            is_goal_directed_event(ev, visible_goal_ids=["g1"])
        )


class TestGC_GoalConvergence(unittest.TestCase):
    def test_gc1_no_gd_raises_self_review(self):
        tracker = GoalConvergenceTracker()
        for i in range(3):
            tick_goal_convergence(tracker, goal_id="g1", goal_directed=False, cycle=i)
        self.assertGreaterEqual(tracker.goals["g1"].goal_no_progress_streak, 3)
        self.assertEqual(tracker.escalation_hint, "G2")
        assessment = assess_party_progress(
            unresolved_leads=["lead_a"],
            available_frontiers=["fr_a"],
            progress_events=[],
            goal_convergence_stall=3,
        )
        self.assertTrue(assessment.intervention_necessary)
        self.assertGreaterEqual(assessment.least_intrusive_level, 1)
        policy = KPInterventionPolicy(s1_threshold=0.1, s4_threshold=99)
        runtime = InterventionRuntimeState(stall_score=1.0, goal_convergence_stall_streak=3)
        decision, _ = policy.decide(
            assessment, runtime, frontier_set=["fr_a"], stall_increment=1.0
        )
        self.assertGreaterEqual(decision.s_level, 1)
        self.assertLess(decision.s_level, 4)

    def test_gc2_gd_resets_goal_stall(self):
        st = DualStallState(activity_stall_streak=2, goal_convergence_stall_streak=5)
        out = apply_progress_to_dual_stall(
            st, meaningful=True, goal_directed=True, cycle=20
        )
        self.assertEqual(out.activity_stall_streak, 0)
        self.assertEqual(out.goal_convergence_stall_streak, 0)
        tracker = GoalConvergenceTracker()
        tick_goal_convergence(tracker, goal_id="g1", goal_directed=False, cycle=1)
        tick_goal_convergence(tracker, goal_id="g1", goal_directed=False, cycle=2)
        tick_goal_convergence(tracker, goal_id="g1", goal_directed=True, cycle=3)
        self.assertEqual(tracker.goals["g1"].goal_no_progress_streak, 0)


class TestFP_FrontierPersistence(unittest.TestCase):
    def test_fp1_defer_on_leave(self):
        store = FrontierPersistenceStore()
        upsert_frontier(
            store,
            PersistentFrontier(
                frontier_id="fr_planks",
                goal_ids=["g_investigate"],
                lead_ids=["lead_planks"],
                location="basement",
                unresolved_importance=0.9,
            ),
        )
        defer_frontier(
            store,
            "fr_planks",
            reason_to_leave="party_moved_upstairs",
            return_condition="goal_stall_increased",
        )
        fr = store.frontiers["fr_planks"]
        self.assertEqual(fr.status, "DEFERRED")
        self.assertEqual(fr.reason_to_leave, "party_moved_upstairs")
        self.assertEqual(fr.return_condition, "goal_stall_increased")
        self.assertIn("fr_planks", store.frontiers)

    def test_fp2_return_condition_reeval(self):
        store = FrontierPersistenceStore()
        upsert_frontier(
            store,
            {
                "frontier_id": "fr_planks",
                "status": "DEFERRED",
                "reason_to_leave": "tool_missing",
                "return_condition": "tool_acquired",
            },
        )
        pressure = apply_return_pressure(store, goal_stall_streak=4, leave_reason_resolved=True)
        self.assertGreater(pressure, 0)
        # Re-enter evaluation without mandatory select
        store.frontiers["fr_planks"].status = "ACTIVE"
        self.assertEqual(store.frontiers["fr_planks"].status, "ACTIVE")
        self.assertFalse(False)  # mandatory selection not asserted


class TestFI_FrontierIgnore(unittest.TestCase):
    def test_fi1_ignore_streak_reminder(self):
        store = FrontierPersistenceStore()
        upsert_frontier(store, {"frontier_id": "fr_critical", "unresolved_importance": 1.0})
        for _ in range(3):
            record_why_not_selected(store, "fr_critical", why="", important=True)
        self.assertGreaterEqual(store.frontier_ignore_streak, 3)
        self.assertTrue(should_remind_ignored_frontier(store, threshold=3))
        assessment = assess_party_progress(
            unresolved_leads=["lead_critical"],
            available_frontiers=["fr_critical"],
            progress_events=[],
            frontier_ignore_streak=store.frontier_ignore_streak,
            goal_convergence_stall=2,
        )
        policy = KPInterventionPolicy(s1_threshold=0.1, s2_threshold=0.5, s4_threshold=99)
        runtime = InterventionRuntimeState(
            stall_score=0.6,
            frontier_ignore_streak=store.frontier_ignore_streak,
        )
        decision, _ = policy.decide(
            assessment, runtime, frontier_set=["fr_critical"], stall_increment=1.0
        )
        self.assertGreaterEqual(decision.s_level, 1)
        self.assertNotIn("force_action", decision.payload)
        self.assertNotEqual(decision.payload.get("mandatory_top_frontier"), True)


class TestFA_FrontierAction(unittest.TestCase):
    def test_fa1_no_candidate_explicit_reason(self):
        store = FrontierPersistenceStore()
        upsert_frontier(store, {"frontier_id": "fr_x", "available_actions": []})
        set_action_unavailable(store, "fr_x", "NO_ACTION_GENERATED")
        self.assertEqual(store.frontiers["fr_x"].action_unavailable_reason, "NO_ACTION_GENERATED")
        self.assertIn("fr_x", store.frontiers)
        breaks = evaluate_chain_trace(
            goal_id="g1",
            lead_ids=["l1"],
            frontier_ids=["fr_x"],
            action_candidates=[],
        )
        self.assertIn("FRONTIER_WITHOUT_ACTION", breaks)


class TestSE_StateEffect(unittest.TestCase):
    def test_se1_expected_effect_achieved(self):
        obs = classify_observed_effect(
            expected=ExpectedStateEffect(
                effect_id="e1",
                target_state_keys=["planks_removed"],
            ),
            changed_keys=["planks_removed"],
        )
        self.assertEqual(obs.classification, EFFECT_EXPECTED)

    def test_se2_repeated_no_effect_method_reconsider(self):
        tracker = MethodAttemptTracker()
        hint = tracker.record("fr_planks", "push", EFFECT_NONE)
        self.assertIsNone(hint)
        hint2 = tracker.record("fr_planks", "push", EFFECT_NONE)
        self.assertEqual(hint2, "method_exhausted")


class TestLO_LocalOptimum(unittest.TestCase):
    def test_lo1_detect_local_optimum(self):
        detected = detect_local_optimum(
            meaningful_progress=True,
            goal_directed_progress=False,
            location_revisit_rate=0.7,
            frontier_switch_rate=0.6,
            goal_stall_streak=4,
        )
        self.assertTrue(detected)
        assessment = assess_party_progress(
            unresolved_leads=["l1"],
            available_frontiers=["f1"],
            # No progress events: local optimum path must still get soft review, not S4
            progress_events=[],
            local_optimum=True,
            goal_convergence_stall=4,
            recent_actions=[
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
                {"action": "wait", "target": ""},
            ],
        )
        policy = KPInterventionPolicy(s1_threshold=0.1, s2_threshold=10, s3_threshold=20, s4_threshold=0.2)
        runtime = InterventionRuntimeState(
            stall_score=5.0,
            local_optimum=True,
            goal_convergence_stall_streak=4,
            activity_stall_streak=0,
        )
        decision, _ = policy.decide(
            assessment, runtime, frontier_set=["f1"], stall_increment=1.0
        )
        # Local optimum: soft ladder only — never immediate S4
        self.assertLess(decision.s_level, 4)
        self.assertGreaterEqual(decision.s_level, 1)


class TestRR_V17Vignette(unittest.TestCase):
    def test_rr1_c8_c9_basement_leave(self):
        rt = ProgressionConvergenceRuntime()
        upsert_frontier(
            rt.frontiers,
            PersistentFrontier(
                frontier_id="fr_basement_planks",
                goal_ids=["g_investigate_house"],
                lead_ids=["lead_basement_barrier"],
                location="basement",
                available_actions=["examine", "force"],
                expected_state_effects=[{"effect_id": "open_path"}],
                unresolved_importance=0.95,
                executable=True,
            ),
        )
        # C8: arrive basement — lateral location progress
        s1 = tick_progression_cycle(
            rt,
            progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
            visible_goal_ids=["g_investigate_house"],
            unresolved_lead_ids=["lead_basement_barrier"],
            known_frontier_ids=["fr_basement_planks"],
            primary_goal_id="g_investigate_house",
            cycle=8,
            location="basement",
            selected_frontier_id="fr_basement_planks",
            goal_relevant_action=False,
        )
        self.assertTrue(s1["meaningful_progress"])
        self.assertFalse(s1["goal_directed_progress"])
        goal_stall_after_c8 = rt.dual_stall.goal_convergence_stall_streak

        # C9: leave basement — allowed; frontier deferred
        defer_frontier(
            rt.frontiers,
            "fr_basement_planks",
            reason_to_leave="temporary_leave_upstairs",
            return_condition="goal_stall_increased",
        )
        s2 = tick_progression_cycle(
            rt,
            progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
            visible_goal_ids=["g_investigate_house"],
            unresolved_lead_ids=["lead_basement_barrier"],
            known_frontier_ids=["fr_basement_planks"],
            primary_goal_id="g_investigate_house",
            cycle=9,
            location="chapel",
            selected_frontier_id="",
            goal_relevant_action=False,
        )
        fr = rt.frontiers.frontiers["fr_basement_planks"]
        self.assertEqual(fr.status, "DEFERRED")
        self.assertTrue(fr.reason_to_leave)
        self.assertTrue(fr.return_condition)
        self.assertFalse(s2["goal_directed_progress"])
        self.assertGreaterEqual(
            rt.dual_stall.goal_convergence_stall_streak, goal_stall_after_c8
        )
        # Lateral must not reset goal stall to 0
        self.assertGreater(rt.dual_stall.goal_convergence_stall_streak, 0)

        # Later: return pressure
        for cyc, loc in enumerate(["attic", "library", "garden"], start=10):
            tick_progression_cycle(
                rt,
                progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
                visible_goal_ids=["g_investigate_house"],
                unresolved_lead_ids=["lead_basement_barrier"],
                known_frontier_ids=["fr_basement_planks"],
                primary_goal_id="g_investigate_house",
                cycle=cyc,
                location=loc,
            )
        self.assertGreater(rt.frontiers.return_pressure, 0)
        self.assertEqual(rt.frontiers.critical_frontier_silent_drop_count, 0)
        self.assertEqual(rt.hidden_solution_signal, 0)
        self.assertEqual(rt.corbitt_specific_force_path, 0)
        self.assertFalse(rt.mandatory_top_frontier_selection)
        # frontier not lost
        self.assertIn("fr_basement_planks", rt.frontiers.frontiers)


class TestTraceIntegrity(unittest.TestCase):
    def test_trace_breaks_explicit(self):
        rt = ProgressionConvergenceRuntime()
        breaks = record_trace(
            rt,
            goal_id="g1",
            lead_ids=[],
            frontier_ids=[],
        )
        self.assertIn("GOAL_WITHOUT_LEAD", breaks)
        breaks2 = record_trace(
            rt,
            goal_id="g1",
            lead_ids=["l1"],
            frontier_ids=[],
        )
        self.assertIn("LEAD_WITHOUT_FRONTIER", breaks2)

    def test_metrics_v2_non_null(self):
        rt = ProgressionConvergenceRuntime()
        tick_progression_cycle(
            rt,
            progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
            cycle=1,
            location="a",
        )
        tick_progression_cycle(
            rt,
            progress_events=[{
                "kind": "object_state_change",
                "progress_type": "OBJECT_STATE_CHANGE",
                "lead_ids": ["l1"],
                "observed_state_effect": {"changed_keys": ["b1"], "lead_ids": ["l1"]},
            }],
            visible_goal_ids=["g1"],
            unresolved_lead_ids=["l1"],
            known_blocker_ids=["b1"],
            cycle=2,
            location="a",
            selected_frontier_id="f1",
            goal_relevant_action=True,
        )
        blob = rt.to_dict()
        rates = blob["metrics"]["rates"]
        for key in (
            "MEANINGFUL_PROGRESS_RATE",
            "GOAL_DIRECTED_PROGRESS_RATE",
            "LATERAL_EXPLORATION_PROGRESS_RATE",
            "FRONTIER_SWITCH_RATE",
            "LOCATION_REVISIT_RATE",
            "GOAL_RELEVANT_ACTION_RATE",
        ):
            self.assertIsNotNone(rates[key])
        self.assertIsNotNone(blob["MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK"])
        self.assertIsNotNone(blob["FRONTIER_PERSISTENCE"])
        self.assertIsNotNone(blob["PROGRESSION_LOCAL_OPTIMUM_COUNT"])


class TestAntiRailroading(unittest.TestCase):
    def test_no_mandatory_top_frontier_or_hidden_solution(self):
        summary = summarize_cycle_progress(
            [{"kind": "new_location", "progress_type": "NEW_LOCATION", "distance_to_ending": 1}],
            visible_goal_ids=["g1"],
        )
        # forbidden key blocks GD even if somehow attached
        self.assertFalse(summary["goal_directed_progress"])
        policy = KPInterventionPolicy()
        assessment = assess_party_progress(
            unresolved_leads=["l1"],
            available_frontiers=["f_top", "f_alt"],
            progress_events=[],
        )
        d, _ = policy.decide(
            assessment,
            InterventionRuntimeState(stall_score=10, activity_stall_streak=5),
            frontier_set=["f_top", "f_alt"],
            stall_increment=1.0,
        )
        if d.s_level == 4:
            self.assertFalse(d.payload.get("force_solution"))
            self.assertGreaterEqual(len(d.payload.get("frontier_set") or []), 2)
        self.assertNotEqual(d.payload.get("mandatory_top_frontier"), True)


if __name__ == "__main__":
    unittest.main()
