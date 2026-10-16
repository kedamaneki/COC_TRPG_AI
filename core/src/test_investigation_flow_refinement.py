import unittest

from InvestigationFlow import (
    AVAILABLE,
    EXHAUSTED,
    NO_ROLL_REQUIRED,
    PUSH_AVAILABLE,
    REJECT_SKILL_PROPOSAL,
    ROLL_WITH_PROPOSED_SKILL,
    advance_context,
    adjudicate_investigation,
    context_version,
    create_rescue_route,
    ensure_investigation_state,
    filter_investigation_candidates,
    finalize_investigation,
    get_attempt_right,
    prepare_investigation,
    share_information,
)
from run_investigation_evaluation import event_metrics


class FakeScenario:
    def __init__(self):
        self.location = "archive"
        self.current_phase = "investigation"
        self.flags = {"new_tool_found": False}
        self.objects = {
            "ledger": {
                "required_skill": ["図書館", "法律"],
                "retry_context_flags": ["new_tool_found"],
            },
            "note": {"no_roll": True},
            "cabinet": {"required_skill": ["目星"]},
        }

    def get_object_info(self, location, target):
        return self.objects.get(target, {})

    def get_required_check(self, action, target, location=None):
        obj = self.objects.get(target, {})
        if obj.get("no_roll"):
            return {"type": "no_roll", "difficulty": "regular"}
        skills = list(obj.get("required_skill") or ["目星"])
        return {
            "type": "skill", "skill_name": skills[0],
            "allowed_skills": skills, "difficulty": "regular",
        }

    def get_action_difficulty(self, action, target, location=None, required_check=None):
        return (required_check or {}).get("difficulty", "regular")

    def resolve_investigation_skill(
        self, action, target, proposed_skill="", loc_id=None, required_check=None,
    ):
        required = required_check or self.get_required_check(action, target, loc_id)
        if required.get("type") == "no_roll":
            return {
                "skill_name": "", "allowed_skills": [], "difficulty": "regular",
                "required_check": required,
            }
        allowed = list(required.get("allowed_skills") or [])
        selected = proposed_skill if proposed_skill in allowed else allowed[0]
        check = dict(required)
        check["skill_name"] = selected
        return {
            "skill_name": selected, "allowed_skills": allowed,
            "difficulty": "regular", "required_check": check,
        }


class FakeCharacters:
    def __init__(self):
        self.known = {"pc_a": ["object:ledger"], "pc_b": []}
        self.notes = {"pc_a": {"object:ledger": "帳簿の原文"}, "pc_b": {}}

    def get_known_knowledge_ids(self, pc_id):
        return list(self.known.get(pc_id, []))

    def grant_knowledge(self, pc_id, knowledge_id, *, summary="", mark_investigated=True, **_):
        values = self.known.setdefault(pc_id, [])
        new = knowledge_id not in values
        if new:
            values.append(knowledge_id)
        if summary:
            self.notes.setdefault(pc_id, {})[knowledge_id] = summary
        return new


def committed_result(ctx, *, success_level=1, pending_push=False, **extra):
    result = {
        "investigation": ctx,
        "success_level": success_level,
        "status": success_level,
        "blocked": False,
        "pending_push_roll": {"decision_pending": True} if pending_push else None,
    }
    result.update(extra)
    return result


class AttemptRightsTests(unittest.TestCase):
    def setUp(self):
        self.state = {"unified_event_log": []}
        self.scenario = FakeScenario()

    def prepare(self, actor="pc_a", skill="図書館", *, push=False):
        return prepare_investigation(
            self.state, self.scenario, actor_id=actor, action_id="search",
            target="ledger", location="archive", proposed_skill=skill,
            proposal_reason="帳簿の出典を索引で確認する", is_push=push,
        )

    def test_same_pc_same_condition_cannot_retry(self):
        first = self.prepare()
        finalize_investigation(
            self.state, committed_result(first, pending_push=True),
            {"dialogue": "帳簿を調べる"}, active_pc_ids=["pc_a", "pc_b"],
        )
        second = self.prepare()
        self.assertFalse(second["attempt_allowed"])
        self.assertEqual(second["attempt_right_before"], PUSH_AVAILABLE)

    def test_other_pc_can_attempt_same_skill(self):
        first = self.prepare("pc_a")
        finalize_investigation(
            self.state, committed_result(first), {}, active_pc_ids=["pc_a", "pc_b"],
        )
        self.assertTrue(self.prepare("pc_b")["attempt_allowed"])

    def test_same_scene_multiple_pcs_can_prepare_before_resolution(self):
        first = self.prepare("pc_a")
        second = self.prepare("pc_b")
        self.assertTrue(first["attempt_allowed"])
        self.assertTrue(second["attempt_allowed"])
        self.assertNotEqual(first["investigation_id"], second["investigation_id"])

    def test_context_change_reopens_attempt(self):
        first = self.prepare()
        finalize_investigation(
            self.state, committed_result(first), {}, active_pc_ids=["pc_a"],
        )
        self.scenario.flags["new_tool_found"] = True
        reopened = self.prepare()
        self.assertTrue(reopened["attempt_allowed"])
        self.assertNotEqual(first["context_version"], reopened["context_version"])

    def test_explicit_context_advance_reopens_attempt(self):
        old = context_version(self.state, self.scenario, "archive", "ledger")
        advance_context(self.state, "archive", "ledger", reason="new evidence")
        new = context_version(self.state, self.scenario, "archive", "ledger")
        self.assertNotEqual(old, new)

    def test_push_is_the_only_same_condition_retry(self):
        first = self.prepare()
        finalize_investigation(
            self.state, committed_result(first, pending_push=True), {}, active_pc_ids=["pc_a"],
        )
        pushed = self.prepare(push=True)
        self.assertTrue(pushed["attempt_allowed"])
        result = committed_result(pushed, success_level=1)
        finalize_investigation(self.state, result, {}, active_pc_ids=["pc_a"])
        self.assertEqual(result["investigation"]["attempt_right_after"], EXHAUSTED)


class AdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.scenario = FakeScenario()

    def test_natural_declaration_gets_primary_skill(self):
        judged = adjudicate_investigation(
            self.scenario, "search", "ledger", location="archive",
        )
        self.assertEqual(judged["selected_skill"], "図書館")

    def test_scenario_alternative_is_approved(self):
        judged = adjudicate_investigation(
            self.scenario, "search", "ledger", proposed_skill="法律",
            proposal_reason="法的な記載形式を照合する", location="archive",
        )
        self.assertEqual(judged["adjudication"], ROLL_WITH_PROPOSED_SKILL)
        self.assertTrue(judged["alternative_skill_approved"])

    def test_unlisted_skill_is_rejected_without_skill_spam(self):
        state = {}
        ctx = prepare_investigation(
            state, self.scenario, actor_id="pc_a", action_id="search", target="ledger",
            location="archive", proposed_skill="聞き耳", proposal_reason="音を聞く",
        )
        self.assertEqual(ctx["adjudication"], REJECT_SKILL_PROPOSAL)
        result = committed_result(ctx, success_level=1)
        finalize_investigation(state, result, {}, active_pc_ids=["pc_a"])
        candidates = filter_investigation_candidates(
            state, [{"target": "ledger", "skill": "聞き耳"}], actor_id="pc_a",
            scenario_mgr=self.scenario, location="archive",
        )
        self.assertEqual(candidates, [])

    def test_kp_reasoned_alternative_can_be_allowed(self):
        judged = adjudicate_investigation(
            self.scenario, "search", "ledger", proposal_reason="インク年代を鑑定する",
            kp_selected_skill="化学", location="archive",
        )
        self.assertEqual(judged["selected_skill"], "化学")
        self.assertTrue(judged["alternative_skill_approved"])

    def test_no_roll_scenario_rule_wins(self):
        judged = adjudicate_investigation(
            self.scenario, "inspect", "note", proposed_skill="目星", location="archive",
        )
        self.assertEqual(judged["adjudication"], NO_ROLL_REQUIRED)
        self.assertFalse(judged["roll_required"])

    def test_kp_can_rule_no_roll_when_situation_justifies_it(self):
        judged = adjudicate_investigation(
            self.scenario, "inspect", "ledger", location="archive", kp_no_roll=True,
        )
        self.assertEqual(judged["adjudication"], NO_ROLL_REQUIRED)
        self.assertFalse(judged["roll_required"])

    def test_normal_skill_check_is_not_auto_succeeded_for_progress(self):
        judged = adjudicate_investigation(
            self.scenario, "search", "ledger", location="archive",
        )
        self.assertTrue(judged["roll_required"])


class KnowledgeAndExhaustionTests(unittest.TestCase):
    def test_normal_and_physical_information_sharing(self):
        state = {"unified_event_log": []}
        chars = FakeCharacters()
        shared = share_information(
            state, chars, from_pc="pc_a", to_pcs=["pc_b"],
            knowledge_ids=["object:ledger"], physical=True,
            summary_by_id={"object:ledger": "帳簿の原文"}, location="archive",
        )
        self.assertEqual(len(shared), 1)
        self.assertIn("object:ledger", chars.known["pc_b"])
        self.assertEqual(chars.notes["pc_b"]["object:ledger"], "帳簿の原文")
        self.assertEqual(state["unified_event_log"][-1]["event_type"], "INFORMATION_SHARED")

    def test_secret_information_is_not_shared(self):
        state = {}
        chars = FakeCharacters()
        shared = share_information(
            state, chars, from_pc="pc_a", to_pcs=["pc_b"],
            knowledge_ids=["object:ledger"], secret=True,
        )
        self.assertEqual(shared, [])
        self.assertNotIn("object:ledger", chars.known["pc_b"])

    def test_target_not_exhausted_while_other_pc_has_right(self):
        state = {}
        scenario = FakeScenario()
        ctx = prepare_investigation(
            state, scenario, actor_id="pc_a", action_id="search", target="ledger",
            location="archive", proposed_skill="図書館",
        )
        result = committed_result(ctx)
        finalize_investigation(state, result, {}, active_pc_ids=["pc_a", "pc_b"])
        self.assertFalse(result["investigation"]["target_exhausted"])

    def test_failure_partial_information_and_rescue_event(self):
        state = {}
        scenario = FakeScenario()
        ctx = prepare_investigation(
            state, scenario, actor_id="pc_a", action_id="search", target="ledger",
            location="archive", proposed_skill="図書館",
        )
        result = committed_result(ctx, partial_information="表紙の発行年だけ読めた")
        finalize_investigation(state, result, {}, active_pc_ids=["pc_a"])
        self.assertIn("表紙の発行年だけ読めた", result["investigation"]["information_gained"])
        route = create_rescue_route(
            state, target="ledger", location="archive",
            route={"type": "new_opportunity", "npc": "librarian"}, kp_stance="generous",
        )
        self.assertEqual(route["kp_stance"], "GENEROUS")
        self.assertEqual(state["unified_event_log"][-1]["event_type"], "KP_RESCUE_ROUTE_CREATED")

    def test_failure_may_yield_no_information(self):
        state = {}
        scenario = FakeScenario()
        ctx = prepare_investigation(
            state, scenario, actor_id="pc_a", action_id="search", target="cabinet",
            location="archive", proposed_skill="目星",
        )
        result = committed_result(ctx, success_level=1)
        finalized = finalize_investigation(state, result, {}, active_pc_ids=["pc_a"])
        self.assertEqual(finalized["information_gained"], [])
        self.assertEqual(finalized["attempt_right_after"], EXHAUSTED)

    def test_fumble_does_not_invent_misinformation(self):
        state = {}
        scenario = FakeScenario()
        ctx = prepare_investigation(
            state, scenario, actor_id="pc_a", action_id="search", target="cabinet",
            location="archive", proposed_skill="目星",
        )
        result = committed_result(ctx, success_level=0, fumble_side_effects=["大きな物音"])
        finalized = finalize_investigation(state, result, {}, active_pc_ids=["pc_a"])
        self.assertEqual(finalized["result"], 0)
        self.assertEqual(finalized["information_gained"], [])

    def test_target_exhausts_after_all_present_pcs_use_the_only_valid_skill(self):
        state = {}
        scenario = FakeScenario()
        first = prepare_investigation(
            state, scenario, actor_id="pc_a", action_id="search", target="cabinet",
            location="archive", proposed_skill="目星",
        )
        finalize_investigation(
            state, committed_result(first, success_level=1), {},
            active_pc_ids=["pc_a", "pc_b"],
        )
        second = prepare_investigation(
            state, scenario, actor_id="pc_b", action_id="search", target="cabinet",
            location="archive", proposed_skill="目星",
        )
        result = committed_result(second, success_level=1)
        finalize_investigation(state, result, {}, active_pc_ids=["pc_a", "pc_b"])
        self.assertTrue(result["investigation"]["target_exhausted"])


class EvaluationMetricTests(unittest.TestCase):
    def test_retry_and_stagnation_metrics_are_distinct(self):
        base = {
            "event_type": "INVESTIGATION_DECLARED", "target": "desk",
            "kp_selected_skill": "目星", "context_version": "v1",
        }
        events = [
            {**base, "actor": "pc_a", "investigation_id": "a1"},
            {**base, "actor": "pc_a", "investigation_id": "a2"},
            {**base, "actor": "pc_b", "investigation_id": "b1"},
            {
                "event_type": "ATTEMPT_EXHAUSTED", "investigation_id": "a2",
                "result": "BLOCKED",
            },
            {
                "scene_id": "s1", "location": "archive", "stall_count": 3,
                "action_origin": "SYSTEM_GUIDED",
                "state_before": {"location": "archive"},
                "state_after": {"location": "archive"},
            },
        ]
        metrics = event_metrics(events)
        self.assertEqual(metrics["same_pc_retry"], 1)
        self.assertEqual(metrics["same_pc_retry_blocked"], 1)
        self.assertEqual(metrics["other_pc_retry"], 1)
        self.assertEqual(metrics["max_stagnation"], 3)
        self.assertEqual(metrics["location_inconsistency"], 0)


if __name__ == "__main__":
    unittest.main()
