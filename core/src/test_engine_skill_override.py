"""
タスク3: PL提案技能をエンジン側が上書きすることの単体テスト。

実行:
  python test_engine_skill_override.py
"""
from __future__ import annotations

import unittest
from unittest import mock

from ActionValidator import resolve_engine_action_judgment
from DiceEngine import SuccessLevel
from ScenarioManager import ScenarioManager
import main


def _scenario_with_objects():
    return {
        "scenario_meta": {"title": "skill override test", "initial_location": "hall"},
        "initial_state": {
            "current_phase": "investigation",
            "location": "hall",
            "turn_counter": 0,
            "flags": {},
        },
        "locations": {
            "hall": {
                "name": "公文書館",
                "default_description": "薄暗い書庫。",
                "objects": {
                    "crime_records": {
                        "name": "犯罪記録",
                        "description": "法律か図書館で辿れる。",
                        "required_skill": ["法律", "図書館"],
                        "difficulty": "通常",
                        "usable_actions": ["search", "inspect"],
                        "investigated_flag": "crime_records_done",
                    },
                    "dusty_shelf": {
                        "name": "埃っぽい棚",
                        "description": "特に指定なし。",
                        "usable_actions": ["search", "inspect"],
                        "investigated_flag": "dusty_shelf_done",
                    },
                    "flavor_painting": {
                        "name": "装飾画",
                        "description": "雰囲気だけ。",
                        "empty_clue": True,
                        "no_roll": True,
                        "usable_actions": ["search", "inspect"],
                    },
                    "heavy_crate": {
                        "name": "重い木箱",
                        "description": "力比べ。",
                        "STR": 60,
                        "usable_actions": ["push", "break"],
                    },
                },
                "exits": {},
            }
        },
        "event_triggers": [],
    }


class TestEngineSkillOverride(unittest.TestCase):
    def setUp(self):
        self.mgr = ScenarioManager(_scenario_with_objects())

    def test_required_skill_overrides_wrong_pl_proposal(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "search", "crime_records", proposed_skill="目星", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "法律")
        self.assertTrue(judgment["skill_overridden"])
        self.assertEqual(judgment["difficulty"], "regular")
        self.assertIn("法律", judgment["allowed_skills"])
        self.assertIn("図書館", judgment["allowed_skills"])

    def test_allowed_proposed_skill_is_kept(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "search", "crime_records", proposed_skill="図書館", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "図書館")
        self.assertFalse(judgment["skill_overridden"])

    def test_empty_proposal_uses_first_required_skill(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "search", "crime_records", proposed_skill="", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "法律")
        self.assertFalse(judgment["skill_overridden"])

    def test_default_spot_hidden_when_no_required_skill(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "search", "dusty_shelf", proposed_skill="オカルト", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "目星")
        self.assertTrue(judgment["skill_overridden"])

    def test_move_ignores_proposed_skill(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "move", "elsewhere", proposed_skill="目星", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "")
        self.assertTrue(judgment["skill_overridden"])

    def test_social_invalid_skill_overridden(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "persuade", "clerk", proposed_skill="図書館", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "説得")
        self.assertTrue(judgment["skill_overridden"])

    def test_social_valid_skill_kept(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "negotiate", "clerk", proposed_skill="威圧", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "威圧")
        self.assertFalse(judgment["skill_overridden"])

    def test_physical_opposed_str_ignores_skill(self):
        judgment = resolve_engine_action_judgment(
            self.mgr, "push", "heavy_crate", proposed_skill="目星", loc_id="hall",
        )
        self.assertEqual(judgment["skill_name"], "")
        self.assertEqual(judgment["required_check"]["type"], "opposed_str")
        self.assertTrue(judgment["skill_overridden"])

    def test_process_system_action_uses_engine_skill_not_pl(self):
        char_mgr = mock.Mock()
        char_mgr.get_skill.return_value = 50
        char_mgr.can_offer_luck_burn.return_value = False
        char_mgr.mark_skill_success = mock.Mock()
        char_mgr.characters = {}
        char_mgr.active_pc_list = ["pc_01"]

        dice_engine = mock.Mock()
        dice_engine.execute_skill_roll.return_value = {
            "log": "【技能:法律】成功",
            "success_level": int(SuccessLevel.REGULAR_SUCCESS),
            "is_failure": False,
            "is_fumble": False,
            "roll": 30,
            "target_value": 50,
        }

        with mock.patch.object(self.mgr, "process_action", return_value={"kp_instruction": "ok"}):
            with mock.patch.object(self.mgr, "evaluate_pre_action_guard", return_value=None):
                result = main.process_system_action(
                    "pc_01",
                    "探索者",
                    "search",
                    "crime_records",
                    "目星",  # PLの誤提案
                    "hall",
                    char_mgr,
                    dice_engine,
                    self.mgr,
                )

        dice_engine.execute_skill_roll.assert_called()
        call_kwargs = dice_engine.execute_skill_roll.call_args
        # positional: char_name, skill_name, skill_value
        self.assertEqual(call_kwargs[0][1], "法律")
        self.assertTrue(result.get("engine_judgment", {}).get("skill_overridden"))
        self.assertEqual(result.get("engine_judgment", {}).get("resolved_skill"), "法律")
        self.assertEqual(result.get("engine_judgment", {}).get("proposed_skill"), "目星")
        self.assertIn("システム確定", result.get("log", ""))

    def test_get_required_check_exposes_allowed_skills(self):
        check = self.mgr.get_required_check("search", "crime_records", "hall")
        self.assertEqual(check["type"], "skill")
        self.assertEqual(check["allowed_skills"], ["法律", "図書館"])
        self.assertEqual(check["skill_name"], "法律")


if __name__ == "__main__":
    unittest.main()
