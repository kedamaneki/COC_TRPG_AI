"""
シナリオビルド／静的バリデーションの単体テスト。
実行: python test_scenario_build.py
または: python -m pytest test_scenario_build.py -q
"""
from __future__ import annotations

import copy
import unittest

from scenario_validation import (
    ScenarioValidationError,
    extract_flag_names_from_expression,
    normalize_flag_token,
    validate_exits_and_locations,
    validate_flag_references,
    validate_scenario,
    validate_unique_ids,
)


def _minimal_scenario() -> dict:
    return {
        "scenario_meta": {
            "title": "テスト迷宮",
            "background": "単体テスト用",
            "initial_phase": "start",
            "initial_location": "room_a",
        },
        "initial_state": {
            "current_phase": "start",
            "location": "room_a",
            "turn_counter": 0,
            "flags": {
                "door_unlocked": False,
                "desk_investigated": False,
            },
        },
        "locations": {
            "room_a": {
                "name": "部屋A",
                "default_description": "簡素な部屋。",
                "connected_to": ["room_b"],
                "objects": {
                    "desk": {
                        "name": "机",
                        "description": "木の机。",
                        "investigated_flag": "desk_investigated",
                        "usable_actions": ["search", "inspect"],
                    }
                },
                "exits": {
                    "room_b": {
                        "name": "隣室へ",
                        "requires_flag": "door_unlocked",
                        "reject_message": "扉は閉ざされている。",
                    }
                },
            },
            "room_b": {
                "name": "部屋B",
                "default_description": "もう一つの部屋。",
                "connected_to": ["room_a"],
                "objects": {},
                "exits": {
                    "room_a": {
                        "name": "戻る",
                        "condition": "true",
                        "reject_message": "戻れない。",
                    }
                },
            },
        },
        "event_triggers": [
            {
                "event_id": "room_a__desk__success",
                "priority": 10,
                "trigger_condition": (
                    "action_id in ['search', 'inspect'] and target == 'desk' "
                    "and location == 'room_a' and flags.desk_investigated == false "
                    "and success_level >= 2"
                ),
                "action_type": "update_and_describe",
                "payload": {
                    "system_log": "机から鍵を見つけた。",
                    "kp_instruction": "鍵を描写せよ。",
                    "flag_updates": {
                        "desk_investigated": True,
                        "door_unlocked": True,
                    },
                    "san_check": {"required": False},
                },
            }
        ],
    }


class TestScenarioValidationHelpers(unittest.TestCase):
    def test_normalize_bang_flag(self):
        self.assertEqual(normalize_flag_token("!in_basement"), "in_basement")
        self.assertEqual(normalize_flag_token("door_unlocked"), "door_unlocked")

    def test_extract_flags_from_expression(self):
        expr = "flags.desk_investigated == false and success_level >= 2"
        self.assertEqual(extract_flag_names_from_expression(expr), {"desk_investigated"})


class TestScenarioValidationPasses(unittest.TestCase):
    def test_minimal_scenario_valid(self):
        errors, warnings = validate_scenario(_minimal_scenario(), raise_on_error=False)
        self.assertEqual(errors, [], msg=errors)


class TestScenarioValidationRejects(unittest.TestCase):
    def test_undefined_flag_in_requires_flag(self):
        scenario = _minimal_scenario()
        scenario["locations"]["room_a"]["exits"]["room_b"]["requires_flag"] = "typo_flag_xyz"
        with self.assertRaises(ScenarioValidationError) as ctx:
            validate_scenario(scenario, raise_on_error=True)
        self.assertIn("typo_flag_xyz", str(ctx.exception))
        self.assertTrue(any("フラグ" in e for e in ctx.exception.errors))

    def test_undefined_flag_in_trigger_condition(self):
        scenario = _minimal_scenario()
        scenario["event_triggers"][0]["trigger_condition"] = (
            "flags.never_defined_flag == true and success_level >= 2"
        )
        errors = validate_flag_references(scenario)
        self.assertTrue(any("never_defined_flag" in e for e in errors))

    def test_missing_exit_destination(self):
        scenario = _minimal_scenario()
        scenario["locations"]["room_a"]["connected_to"] = ["room_missing"]
        scenario["locations"]["room_a"]["exits"]["room_missing"] = {
            "name": "虚空へ",
            "reject_message": "行けない。",
        }
        errors = validate_exits_and_locations(scenario)
        self.assertTrue(any("room_missing" in e for e in errors))

    def test_duplicate_event_id(self):
        scenario = _minimal_scenario()
        dup = copy.deepcopy(scenario["event_triggers"][0])
        scenario["event_triggers"].append(dup)
        errors, _warnings = validate_unique_ids(scenario)
        self.assertTrue(any("event_id" in e and "重複" in e for e in errors))

    def test_duplicate_object_id_across_locations(self):
        scenario = _minimal_scenario()
        scenario["locations"]["room_b"]["objects"] = {
            "desk": {
                "name": "別の机",
                "description": "こちらにも机がある。",
                "investigated_flag": "other_desk_investigated",
                "usable_actions": ["search"],
            }
        }
        # other flag must be defined to isolate ID check — add to initial flags
        scenario["initial_state"]["flags"]["other_desk_investigated"] = False
        errors, _warnings = validate_unique_ids(scenario)
        self.assertTrue(any("object_id" in e and "desk" in e for e in errors))

    def test_build_rejects_bad_location_json_pipeline(self):
        """不整合なロケーション相当データを混ぜてもバリデーションが拒否する。"""
        scenario = _minimal_scenario()
        # わざと存在しないフラグを参照する「悪い loc」をマージした状態を模擬
        scenario["locations"]["evil_room"] = {
            "name": "呪われた部屋",
            "default_description": "危険。",
            "connected_to": ["room_a"],
            "objects": {
                "cursed_idol": {
                    "name": "偶像",
                    "description": "ぞっとする偶像。",
                    "investigated_flag": "cursed_idol_seen",
                    "usable_actions": ["search"],
                }
            },
            "exits": {
                "room_a": {
                    "name": "戻る",
                    "requires_flag": "misspelled_unlock_flag",
                    "reject_message": "出られない。",
                }
            },
        }
        scenario["initial_state"]["flags"]["cursed_idol_seen"] = False
        with self.assertRaises(ScenarioValidationError) as ctx:
            validate_scenario(scenario)
        self.assertIn("misspelled_unlock_flag", str(ctx.exception))


class TestCorbittBuildIntegration(unittest.TestCase):
    def test_current_corbitt_sources_validate(self):
        try:
            from build_corbitt_scenario import build_scenario_dict, staged_cache_available
        except ImportError:
            self.skipTest("build_corbitt_scenario を import できません")
        if not staged_cache_available():
            self.skipTest("ステージングキャッシュがありません")
        scenario = build_scenario_dict()
        errors, _warnings = validate_scenario(scenario, raise_on_error=False)
        self.assertEqual(errors, [], msg=errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
