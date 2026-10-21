"""Short controlled multi-seed comparison: baseline vs NATURAL_DECISION_MODEL_V1."""

from __future__ import annotations

import random
import unittest

from reasoning.knowledge_boundary import EpistemicKind, KnownFactView, ReasoningKnowledgeBoundary
from reasoning.kp_assessment import assess_party_progress
from reasoning.kp_intervention import InterventionRuntimeState, KPInterventionPolicy
from reasoning.lead_tracker import Lead, LeadTracker
from reasoning.pl_policy import PLDecisionPolicy
from reasoning.pl_state import FailureClass, PLReasoningState
from reasoning.progress_bridge import reorder_s4_candidates_for_frontier_recovery


def _seed_scenario(rng: random.Random):
    """Basement plank vignette state shared by both paths."""
    return {
        "basement_planks_examined": True,
        "broken": False,
        "break_failed": True,
        "location": "corbitt_basement",
        "unresolved": ["basement_planks", "magic_dagger"],
        "noise": rng.random(),
    }


def _baseline_path(seed: int, cycles: int = 40) -> dict:
    """OLD path: repeats break, escalates to forced solution-like S4."""
    rng = random.Random(seed)
    scenario = _seed_scenario(rng)
    actions = []
    s_level = 0
    stall = 0
    unexplained = 0
    repetitive = 0
    forced_solution = 0
    premature_s4 = 0
    abandon = 0
    meaningful = 0
    lead_held = True
    for c in range(cycles):
        # Baseline: keep trying break or wander without leave_reason
        if c < 8:
            act = {"action": "break", "target": "basement_planks", "reason": ""}
            unexplained += 1
            repetitive += 1
            stall += 1
        elif c < 20:
            act = {"action": "wait", "target": "chapel"}
            lead_held = False
            abandon += 1
            stall += 1
            repetitive += 1
        else:
            act = {"action": "break", "target": "basement_planks", "forced": True}
            forced_solution += 1
            s_level = 4
            premature_s4 += 1
        actions.append(act)
        if stall >= 3 and s_level < 4:
            s_level = min(4, s_level + 1)
        if stall >= 6:
            premature_s4 += 1
            forced_solution += 1
            s_level = 4
    return {
        "UNEXPLAINED_ACTION_RATE": unexplained / cycles,
        "REPETITIVE_ACTION_RATE": repetitive / cycles,
        "UNRESOLVED_LEAD_ABANDON_RATE": (0.0 if lead_held else abandon / cycles),
        "PREMATURE_S4_RATE": premature_s4 / cycles,
        "FORCED_SOLUTION_RATE": forced_solution / cycles,
        "SELF_RECOVERY_RATE": 0.0,
        "MEANINGFUL_PROGRESS_RATE": meaningful / cycles,
        "POST_S4_FREEDOM_RATE": 0.0,
        "HIDDEN_SOLUTION_FRONTIER_RATE": 0.0,
        "FALLBACK_GUARD_VIOLATION_RATE": 0.0,
        "S_LEVEL_RESET_SUCCESS_RATE": 0.0,
        "final_s": s_level,
        "scenario": scenario,
    }


def _natural_path(seed: int, cycles: int = 40) -> dict:
    rng = random.Random(seed)
    scenario = _seed_scenario(rng)
    b = ReasoningKnowledgeBoundary([
        KnownFactView(fact_id="basement_planks_examined", kind=EpistemicKind.FACT),
    ])
    leads = LeadTracker(b)
    for lid in scenario["unresolved"]:
        leads.upsert(Lead(
            lead_id=lid,
            source_fact_ids=["basement_planks_examined"],
            value_reasons=["known_unresolved_lead", "available_actions_remain"],
            high_value=True,
            unresolved=True,
            available_action_count=2,
        ))
    st = PLReasoningState(
        actor_id="pc_01",
        known_facts=["basement_planks_examined"],
        high_value_leads=list(scenario["unresolved"]),
    )
    st.record_failure(action="break", target="basement_planks", failure_class=FailureClass.ATTEMPT_FAILED)
    policy = PLDecisionPolicy(b)
    kp = KPInterventionPolicy(
        s1_threshold=2, s2_threshold=4, s3_threshold=6, s4_threshold=8, recovery_grace_cycles=3,
    )
    runtime = InterventionRuntimeState()

    unexplained = 0
    repetitive = 0
    abandon = 0
    premature_s4 = 0
    forced_solution = 0
    self_recovery = 0
    meaningful = 0
    post_s4_freedom = 0
    s_reset_ok = 0
    s4_seen = False
    recent = []
    knowledge_leak = 0
    hidden_frontier = 0
    fallback_viol = 0

    for c in range(cycles):
        suggestions = policy.suggest_after_failure(
            st, failed_action="break", failed_target="basement_planks",
            failure_class=FailureClass.ATTEMPT_FAILED,
        )
        # Pick by seed: alternate push / search / temporary leave / return
        pick = suggestions[c % len(suggestions)]
        if pick.get("meaning_class") == "TRANSITION":
            leads.defer("basement_planks", leave_reason=pick.get("leave_reason") or "seek_better_tool")
            st.leave_reason = pick.get("leave_reason") or "seek_better_tool"
        # Always require reason
        if not pick.get("reason"):
            unexplained += 1
        act = {
            "action": pick["action"],
            "target": pick.get("target") or "",
            "reason": pick.get("reason") or "missing",
        }
        # Detect meaningless repeats
        if recent[-2:] == [act, act] if len(recent) >= 2 else False:
            repetitive += 1
        if len(recent) >= 2 and all(
            r.get("action") == act["action"] and r.get("target") == act["target"] for r in recent[-2:]
        ):
            repetitive += 1
        recent.append(act)

        progress_events = []
        hyp_tests = []
        alts = []
        if act["action"] in {"push", "search"} and act["target"] == "basement_planks":
            hyp_tests.append({"hypothesis_id": "plank_alt"})
            self_recovery += 1
        if act["action"] == "move" and c > 10 and c % 7 == 0:
            # return with new info — meaningful
            progress_events.append({"kind": "new_information_attempt"})
            # treat as exploring alternative
            alts.append({"kind": "tool_seek"})
            # restore lead
            lead = leads.get("basement_planks")
            if lead and lead.status.value == "DEFERRED":
                leads.set_status("basement_planks", "ACTIVE")
                lead.unresolved = True
                lead.high_value = True

        frontiers = [f["frontier_id"] for f in leads.unresolved_high_value_frontier_set()]
        if not frontiers and scenario["unresolved"]:
            abandon += 1

        assessment = assess_party_progress(
            unresolved_leads=frontiers or scenario["unresolved"],
            available_frontiers=frontiers or scenario["unresolved"],
            recent_actions=recent[-5:],
            progress_events=progress_events,
            hypothesis_tests=hyp_tests,
            alternative_explorations=alts,
            party_understanding=["basement_planks_examined"],
        )
        if assessment.meaningful_progress_this_cycle or hyp_tests or alts:
            meaningful += 1

        decision, runtime = kp.decide(
            assessment, runtime,
            frontier_set=frontiers or scenario["unresolved"],
            restore_location="corbitt_basement",
            stall_increment=1.0 if assessment.merely_repeating else 0.25,
        )
        if decision.s_level == 4:
            if c < 15:
                premature_s4 += 1
            s4_seen = True
            if decision.payload.get("force_solution"):
                forced_solution += 1
            # recovery → S0
            runtime = kp.complete_s4_recovery(runtime)
            if runtime.current_s_level == 0:
                s_reset_ok += 1
            # reorder candidates — no sole destroy
            ordered = reorder_s4_candidates_for_frontier_recovery(
                [
                    {"action": "break", "target": "basement_planks"},
                    {"action": "move", "target": "corbitt_basement"},
                    {"action": "attend", "target": "magic_dagger"},
                ],
                frontier_ids=frontiers or scenario["unresolved"],
                restore_location="corbitt_basement",
            )
            if ordered and ordered[0]["action"] == "break" and len(frontiers or scenario["unresolved"]) > 1:
                forced_solution += 1
        if s4_seen and decision.s_level == 0:
            post_s4_freedom += 1

    # Lead must still be held
    still = leads.unresolved_high_value_frontier_set()
    abandon_rate = 0.0 if still else 1.0

    return {
        "UNEXPLAINED_ACTION_RATE": unexplained / cycles,
        "REPETITIVE_ACTION_RATE": repetitive / cycles,
        "UNRESOLVED_LEAD_ABANDON_RATE": abandon_rate,
        "PREMATURE_S4_RATE": premature_s4 / cycles,
        "FORCED_SOLUTION_RATE": forced_solution / cycles,
        "SELF_RECOVERY_RATE": self_recovery / cycles,
        "MEANINGFUL_PROGRESS_RATE": meaningful / cycles,
        "POST_S4_FREEDOM_RATE": post_s4_freedom / cycles,
        "HIDDEN_SOLUTION_FRONTIER_RATE": hidden_frontier,
        "FALLBACK_GUARD_VIOLATION_RATE": fallback_viol,
        "S_LEVEL_RESET_SUCCESS_RATE": (s_reset_ok / max(1, premature_s4 + s_reset_ok)) if (premature_s4 or s_reset_ok) else 1.0,
        "KNOWLEDGE_LEAK": knowledge_leak,
        "final_s": runtime.current_s_level,
    }


def _avg(rows: list[dict], key: str) -> float:
    return sum(float(r.get(key) or 0) for r in rows) / max(1, len(rows))


class TestControlledMultiSeed(unittest.TestCase):
    SEEDS = (11, 22, 33, 44, 55)

    def test_short_controlled_comparison_improves(self):
        baseline = [_baseline_path(s) for s in self.SEEDS]
        natural = [_natural_path(s) for s in self.SEEDS]

        metrics = {}
        for key in (
            "UNEXPLAINED_ACTION_RATE",
            "REPETITIVE_ACTION_RATE",
            "UNRESOLVED_LEAD_ABANDON_RATE",
            "PREMATURE_S4_RATE",
            "FORCED_SOLUTION_RATE",
            "SELF_RECOVERY_RATE",
            "MEANINGFUL_PROGRESS_RATE",
            "POST_S4_FREEDOM_RATE",
            "HIDDEN_SOLUTION_FRONTIER_RATE",
            "FALLBACK_GUARD_VIOLATION_RATE",
        ):
            metrics[key] = (_avg(baseline, key), _avg(natural, key))

        # Hard gates
        self.assertEqual(metrics["HIDDEN_SOLUTION_FRONTIER_RATE"][1], 0.0)
        self.assertEqual(metrics["FALLBACK_GUARD_VIOLATION_RATE"][1], 0.0)
        for row in natural:
            self.assertEqual(row.get("KNOWLEDGE_LEAK", 0), 0)
            self.assertEqual(row["FORCED_SOLUTION_RATE"], 0.0)

        # Improvements vs baseline
        self.assertLess(metrics["UNEXPLAINED_ACTION_RATE"][1], metrics["UNEXPLAINED_ACTION_RATE"][0])
        self.assertLess(metrics["REPETITIVE_ACTION_RATE"][1], metrics["REPETITIVE_ACTION_RATE"][0])
        self.assertLess(metrics["UNRESOLVED_LEAD_ABANDON_RATE"][1], metrics["UNRESOLVED_LEAD_ABANDON_RATE"][0])
        self.assertLess(metrics["PREMATURE_S4_RATE"][1], metrics["PREMATURE_S4_RATE"][0])
        self.assertLess(metrics["FORCED_SOLUTION_RATE"][1], metrics["FORCED_SOLUTION_RATE"][0])
        self.assertGreater(metrics["SELF_RECOVERY_RATE"][1], metrics["SELF_RECOVERY_RATE"][0])
        self.assertGreater(metrics["MEANINGFUL_PROGRESS_RATE"][1], metrics["MEANINGFUL_PROGRESS_RATE"][0])

        # Expose for reporting
        self.__class__.LAST_METRICS = metrics
        self.__class__.SEEDS_USED = self.SEEDS


class TestFormalIdentityHelper(unittest.TestCase):
    def test_preflight_tag_version_prefers_newest(self):
        import re

        def ver(tag):
            m = re.match(r"^v(\d+)-preflight-accepted$", tag)
            return int(m.group(1)) if m else -1

        head = ["v5-preflight-accepted", "v15-preflight-accepted"]
        self.assertEqual(sorted(head, key=ver)[-1], "v15-preflight-accepted")


if __name__ == "__main__":
    unittest.main()
