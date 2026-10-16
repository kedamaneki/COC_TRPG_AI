"""
タスク4: 判定失敗後の pending_decision（Pending Decision）単体テスト。

実行:
  python test_pending_decision_flow.py
"""
from __future__ import annotations

import unittest
from unittest import mock

import CoCRules
import main
from DiceEngine import SuccessLevel


class FakeCharMgr:
    def __init__(self, luck=50):
        self._luck = luck
        self.characters = {
            "pc_01": {
                "profile": {"name": "テスト探索者", "is_npc": False},
                "attributes": {"LUK": luck},
                "skills": {"目星": 40, "心理学": 30, "格闘": 50, "射撃": 45},
            },
            "npc_01": {
                "profile": {"name": "敵", "is_npc": True},
                "attributes": {"LUK": 40},
                "skills": {"格闘": 55},
            },
        }

    def get_luck(self, char_id):
        return int(self.characters.get(char_id, {}).get("attributes", {}).get("LUK", 0))

    def can_offer_luck_burn(self, char_id, margin, max_burn=10):
        if margin <= 0 or margin > max_burn:
            return False
        return self.get_luck(char_id) >= margin

    def get_skill(self, char_id, skill_name):
        return self.characters.get(char_id, {}).get("skills", {}).get(skill_name, 0)

    def mark_skill_success(self, char_id, skill_name):
        return None


class TestCoCRulesLegalOptions(unittest.TestCase):
    def test_normal_failure_offers_accept_luck_and_push(self):
        info = CoCRules.build_post_roll_failure_legal_options(
            skill_name="目星",
            action_id="search",
            margin=5,
            current_luck=40,
            is_fumble=False,
        )
        self.assertEqual(
            info["legal_options"],
            ["accept", "spend_luck", "push"],
        )
        self.assertEqual(info["luck_cost"], 5)

    def test_fumble_excludes_spend_luck(self):
        info = CoCRules.build_post_roll_failure_legal_options(
            skill_name="目星",
            action_id="search",
            margin=3,
            current_luck=40,
            is_fumble=True,
        )
        self.assertIn("accept", info["legal_options"])
        self.assertNotIn("spend_luck", info["legal_options"])
        self.assertIn("push", info["legal_options"])

    def test_combat_skill_excludes_push(self):
        info = CoCRules.build_post_roll_failure_legal_options(
            skill_name="格闘",
            action_id="attack",
            margin=4,
            current_luck=40,
            in_combat=False,
        )
        self.assertNotIn("push", info["legal_options"])
        self.assertIn("spend_luck", info["legal_options"])

    def test_already_pushed_excludes_push_and_luck(self):
        info = CoCRules.build_post_roll_failure_legal_options(
            skill_name="目星",
            action_id="search",
            margin=4,
            current_luck=40,
            already_pushed=True,
        )
        self.assertEqual(info["legal_options"], ["accept"])

    def test_san_check_excludes_push_and_luck(self):
        info = CoCRules.build_post_roll_failure_legal_options(
            skill_name="正気度",
            action_id="san_check",
            roll_type="san_check",
            margin=2,
            current_luck=40,
        )
        self.assertEqual(info["legal_options"], ["accept"])

    def test_shoot_defense_options_exclude_fight_back(self):
        opts = CoCRules.build_combat_defense_legal_options(is_shoot=True)
        self.assertEqual(opts, ["dodge", "accept_hit"])
        self.assertNotIn("fight_back", opts)


class TestPendingDecisionFlow(unittest.TestCase):
    def _dice_fail(self, *, roll=55, target=40, fumble=False):
        margin = max(0, int(roll) - int(target))
        return {
            "roll": roll,
            "target_value": target,
            "failure_margin": margin,
            "is_failure": True,
            "is_fumble": fumble,
            "result": "ファンブル" if fumble else "失敗",
            "success_level": int(SuccessLevel.FUMBLE if fumble else SuccessLevel.FAILURE),
        }

    def test_handle_failure_builds_luck_pending_with_legal_options(self):
        char_mgr = FakeCharMgr(luck=50)
        fail_level, luck, push = main._handle_skill_roll_failure(
            self._dice_fail(roll=45, target=40),
            char_mgr, "pc_01", "desk", "目星", "search",
            0, 0, 0,
        )
        self.assertEqual(fail_level, int(SuccessLevel.FAILURE))
        self.assertIsNotNone(luck)
        self.assertIsNone(push)
        self.assertIn("accept", luck["legal_options"])
        self.assertIn("spend_luck", luck["legal_options"])
        self.assertIn("push", luck["legal_options"])
        self.assertEqual(luck["luck_cost"], 5)

    def test_fumble_skips_luck_but_may_offer_push(self):
        char_mgr = FakeCharMgr(luck=50)
        fail_level, luck, push = main._handle_skill_roll_failure(
            self._dice_fail(roll=100, target=40, fumble=True),
            char_mgr, "pc_01", "desk", "目星", "search",
            0, 0, 0,
            fail_level=int(SuccessLevel.FUMBLE),
        )
        self.assertEqual(fail_level, int(SuccessLevel.FUMBLE))
        self.assertIsNone(luck)
        self.assertIsNotNone(push)
        self.assertNotIn("spend_luck", push.get("legal_options", []))
        self.assertIn("push", push.get("legal_options", []))

    def test_combat_skill_failure_no_push(self):
        char_mgr = FakeCharMgr(luck=50)
        _, luck, push = main._handle_skill_roll_failure(
            self._dice_fail(roll=60, target=50),
            char_mgr, "pc_01", "npc_01", "格闘", "attack",
            0, 0, 0,
        )
        self.assertIsNone(push)
        if luck:
            self.assertNotIn("push", luck.get("legal_options", []))

    def test_system_result_attaches_pending_decision(self):
        char_mgr = FakeCharMgr(luck=50)
        _, luck, _ = main._handle_skill_roll_failure(
            self._dice_fail(roll=45, target=40),
            char_mgr, "pc_01", "desk", "目星", "search",
            0, 0, 0,
        )
        result = main._build_system_action_result(
            int(SuccessLevel.FAILURE),
            "失敗ログ",
            None,
            "search",
            None,
            luck_decision_required=True,
            pending_luck_burn=luck,
            roll_type="skill",
            action_target="desk",
            decision_owner_id="pc_01",
        )
        pd = result.get("pending_decision")
        self.assertIsNotNone(pd)
        self.assertEqual(pd["type"], "POST_ROLL_FAILURE")
        self.assertEqual(pd["decision_owner_id"], "pc_01")
        self.assertEqual(pd["luck_cost"], 5)
        self.assertEqual(set(pd["legal_options"]), {"accept", "spend_luck", "push"})

    def test_timeline_prioritizes_pending_decision_to_luck(self):
        state = main.ensure_transaction_state_fields({
            "pl_id": "pc_01",
            "active_pc_id": "pc_01",
            "pending_luck_burn": {
                "original_action": "search",
                "skill_name": "目星",
                "margin": 5,
                "allow_push": True,
                "legal_options": ["accept", "spend_luck", "push"],
            },
            "pending_push_roll": None,
            "pending_combat_defense": None,
            "pending_san_check": None,
            "decision_owner_id": "pc_01",
        })
        phase = main.get_timeline_pending_phase(state)
        self.assertEqual(phase, main.PENDING_LUCK_CONSUMPTION)
        self.assertIsNotNone(state.get("pending_decision"))
        self.assertEqual(state["pending_decision"]["type"], "POST_ROLL_FAILURE")
        step = main.determine_timeline_next_step(
            state, "テスト探索者", scenario_mgr=mock.Mock(flags={}),
        )
        self.assertEqual(step, "luck_decision")

    def test_after_luck_decline_pending_decision_drops_spend_luck(self):
        state = {
            "pl_id": "pc_01",
            "decision_owner_id": "pc_01",
            "pending_luck_burn": None,
            "pending_push_roll": {
                "original_action": "search",
                "skill_name": "目星",
                "decision_pending": True,
                "legal_options": ["accept", "push"],
            },
            "push_decision_required": True,
            "pending_combat_defense": None,
            "pending_san_check": None,
            "pending_decision": main.build_pending_decision(
                decision_type="POST_ROLL_FAILURE",
                target_action_id="search",
                decision_owner_id="pc_01",
                legal_options=["accept", "push"],
            ),
        }
        phase = main.get_timeline_pending_phase(state)
        self.assertEqual(phase, main.PENDING_PUSH_DECISION)
        self.assertNotIn("spend_luck", state["pending_decision"]["legal_options"])
        # 重複プッシュは legal_options に一度だけ
        self.assertEqual(state["pending_decision"]["legal_options"].count("push"), 1)

    def test_combat_defense_pending_decision(self):
        pending = {
            "attacker_id": "npc_01",
            "defender_id": "pc_01",
            "attack_type": "melee",
        }
        pd = main.build_combat_pending_decision(pending, decision_owner_id="pc_01")
        self.assertEqual(pd["type"], "COMBAT_DEFENSE")
        self.assertEqual(set(pd["legal_options"]), {"dodge", "fight_back"})

        shoot_pending = {
            "attacker_id": "npc_01",
            "defender_id": "pc_01",
            "attack_type": "shoot",
            "is_ranged": True,
        }
        pd2 = main.build_combat_pending_decision(shoot_pending, decision_owner_id="pc_01")
        self.assertEqual(pd2["type"], "SHOOT_DEFENSE")
        self.assertEqual(set(pd2["legal_options"]), {"dodge", "accept"})
        self.assertNotIn("fight_back", pd2["legal_options"])

    def test_clear_pending_decision_on_accept_path(self):
        state = {
            "pending_decision": main.build_pending_decision(
                decision_type="POST_ROLL_FAILURE",
                target_action_id="search",
                decision_owner_id="pc_01",
                legal_options=["accept"],
            ),
            "pending_luck_burn": None,
            "pending_push_roll": None,
            "pending_combat_defense": None,
        }
        main.clear_pending_decision(state)
        self.assertIsNone(state["pending_decision"])

    def test_apply_skill_roll_outcome_in_combat_no_pending(self):
        char_mgr = FakeCharMgr()
        level, luck, push = main._apply_skill_roll_outcome(
            self._dice_fail(roll=70, target=40),
            char_mgr, "pc_01", "npc_01", "目星", "search",
            0, 0, 0,
            in_combat=True,
        )
        self.assertEqual(level, int(SuccessLevel.FAILURE))
        self.assertIsNone(luck)
        self.assertIsNone(push)


if __name__ == "__main__":
    unittest.main(verbosity=2)
