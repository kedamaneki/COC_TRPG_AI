"""
結合テスト: CoC 7版ルールエンジン（SuccessLevel / 難易度 / 狂気）。
実行: python -m pytest test_coc7_rules.py -q
または: python test_coc7_rules.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from CharacterManager import CharacterManager
from DiceEngine import (
    DiceEngine,
    SuccessLevel,
    difficulty_target_value,
    is_failure_level,
    is_success_level,
    luck_points_needed,
    normalize_difficulty,
)
from GameStateManager import (
    GameStateManager,
    InterventionLevel,
)
from ScenarioManager import ScenarioManager
import main as game_main


class TestSuccessLevelsAndDifficulty(unittest.TestCase):
    def setUp(self):
        self.dice = DiceEngine()

    def test_normalize_difficulty_aliases(self):
        self.assertEqual(normalize_difficulty("通常"), "regular")
        self.assertEqual(normalize_difficulty("困難"), "hard")
        self.assertEqual(normalize_difficulty("extreme"), "extreme")

    def test_difficulty_targets(self):
        self.assertEqual(difficulty_target_value(50, "regular"), 50)
        self.assertEqual(difficulty_target_value(50, "hard"), 25)
        self.assertEqual(difficulty_target_value(50, "extreme"), 10)

    def test_fumble_under_50(self):
        self.assertTrue(self.dice.is_fumble(40, 96))
        self.assertTrue(self.dice.is_fumble(40, 100))
        self.assertFalse(self.dice.is_fumble(40, 95))

    def test_fumble_50_or_more(self):
        self.assertFalse(self.dice.is_fumble(50, 96))
        self.assertFalse(self.dice.is_fumble(80, 99))
        self.assertTrue(self.dice.is_fumble(50, 100))
        self.assertTrue(self.dice.is_fumble(99, 100))

    def test_critical_is_always_one(self):
        ev = self.dice.evaluate_roll(30, 1, "extreme")
        self.assertEqual(ev["success_level"], int(SuccessLevel.CRITICAL))

    def test_hard_difficulty_fails_regular_quality_only(self):
        # skill 60: hard target 30. roll 35 is regular quality but fails hard req
        ev = self.dice.evaluate_roll(60, 35, "hard")
        self.assertEqual(ev["success_level"], int(SuccessLevel.FAILURE))
        self.assertTrue(ev["is_failure"])

    def test_hard_difficulty_accepts_hard_success(self):
        ev = self.dice.evaluate_roll(60, 25, "hard")
        self.assertEqual(ev["success_level"], int(SuccessLevel.HARD_SUCCESS))
        self.assertTrue(is_success_level(ev["success_level"]))

    def test_extreme_difficulty(self):
        ev = self.dice.evaluate_roll(50, 10, "extreme")
        self.assertGreaterEqual(ev["success_level"], int(SuccessLevel.EXTREME_SUCCESS))
        ev_fail = self.dice.evaluate_roll(50, 11, "extreme")
        self.assertTrue(is_failure_level(ev_fail["success_level"]))

    def test_skill_roll_carries_difficulty(self):
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(20, [2], 0, 0)):
            result = self.dice.execute_skill_roll(
                "探", "目星", 50, required_difficulty="hard",
            )
        self.assertEqual(result["required_difficulty"], "hard")
        self.assertEqual(result["success_level"], int(SuccessLevel.HARD_SUCCESS))


class TestInsanityRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "inv1": {
                "profile": {"name": "調査員", "is_npc": False},
                "attributes": {
                    "INT": 60,
                    "POW": 50,
                    "CON": 50,
                    "SIZ": 50,
                    "DEX": 50,
                    "STR": 50,
                    "SAN": {"current": 50, "max": 99, "session_start": 50, "session_start_san": 50},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"目星": 50},
                "states": [],
            }
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text("{}", encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.state_mgr = GameStateManager(self.char_mgr)
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_start_san_helpers(self):
        self.assertEqual(self.char_mgr.get_session_start_san("inv1"), 50)
        self.char_mgr.apply_pool_damage("inv1", "SAN", 5)
        self.char_mgr.begin_session_stats("inv1")
        self.assertEqual(self.char_mgr.get_session_start_san("inv1"), self.char_mgr.get_stat_current("inv1", "SAN"))
        pool = self.char_mgr.get_stat_pool("inv1", "SAN")
        self.assertEqual(pool["session_start"], pool["session_start_san"])

    def test_temporary_insanity_on_int_success(self):
        with mock.patch.object(
            DiceEngine,
            "execute_int_roll",
            return_value={
                "roll": 10,
                "success_level": int(SuccessLevel.REGULAR_SUCCESS),
                "result": "レギュラー成功",
            },
        ):
            result = self.state_mgr.apply_san_damage(
                "inv1", 5, dice_engine=self.dice, char_name="調査員",
            )
        self.assertEqual(result["lost_san"], 5)
        self.assertTrue(any("一時的狂気" in e for e in result["events"]))
        self.assertTrue(any("INTロール" in e and "成功" in e for e in result["events"]))
        states = self.char_mgr.characters["inv1"]["states"]
        temp = [s for s in states if isinstance(s, dict) and s.get("kind") == "temporary_insanity"]
        self.assertEqual(len(temp), 1)
        self.assertTrue(temp[0].get("realtime_madness"))
        self.assertTrue(temp[0].get("bout_pending"))

    def test_temporary_insanity_avoided_on_int_failure(self):
        with mock.patch.object(
            DiceEngine,
            "execute_int_roll",
            return_value={
                "roll": 90,
                "success_level": int(SuccessLevel.FAILURE),
                "result": "失敗",
            },
        ):
            result = self.state_mgr.apply_san_damage(
                "inv1", 5, dice_engine=self.dice, char_name="調査員",
            )
        self.assertTrue(any("現実逃避" in e for e in result["events"]))
        temp = [
            s for s in self.char_mgr.characters["inv1"]["states"]
            if isinstance(s, dict) and s.get("kind") == "temporary_insanity"
        ]
        self.assertEqual(temp, [])

    def test_under_five_no_temp_check(self):
        result = self.state_mgr.apply_san_damage("inv1", 4, dice_engine=self.dice)
        self.assertFalse(any("INTロール" in e for e in result["events"]))

    def test_indefinite_insanity_20_percent(self):
        # session_start 50 → 20% = 10. Lose 10 without triggering temp INT success.
        with mock.patch.object(
            DiceEngine,
            "execute_int_roll",
            return_value={
                "roll": 99,
                "success_level": int(SuccessLevel.FAILURE),
                "result": "失敗",
            },
        ):
            result = self.state_mgr.apply_san_damage("inv1", 10, dice_engine=self.dice)
        self.assertTrue(any("不定の狂気" in e for e in result["events"]))
        indef = [
            s for s in self.char_mgr.characters["inv1"]["states"]
            if isinstance(s, dict) and s.get("kind") == "indefinite_insanity"
        ]
        self.assertEqual(len(indef), 1)

        # 二度目は重複しない
        result2 = self.state_mgr.apply_san_damage("inv1", 1, dice_engine=self.dice)
        self.assertFalse(any("不定の狂気" in e for e in result2["events"]))


class TestScenarioDifficultyWiring(unittest.TestCase):
    def test_get_action_difficulty_from_object(self):
        scenario = {
            "meta": {"title": "t"},
            "initial_state": {"location": "room", "flags": {}, "phase": "p"},
            "locations": {
                "room": {
                    "name": "部屋",
                    "objects": {
                        "lock": {"name": "錠", "difficulty": "困難", "usable_actions": ["search"]},
                    },
                    "connected_to": [],
                }
            },
            "event_triggers": [],
        }
        mgr = ScenarioManager(scenario)
        self.assertEqual(mgr.get_action_difficulty("search", "lock", "room"), "hard")

    def test_opposed_str_required_check_has_difficulty(self):
        scenario = {
            "meta": {"title": "t"},
            "initial_state": {"location": "room", "flags": {}, "phase": "p"},
            "locations": {
                "room": {
                    "name": "部屋",
                    "objects": {
                        "door": {
                            "name": "扉",
                            "STR": 60,
                            "difficulty": "hard",
                            "usable_actions": ["break"],
                        },
                    },
                    "connected_to": [],
                }
            },
            "event_triggers": [],
        }
        mgr = ScenarioManager(scenario)
        check = mgr.get_required_check("break", "door", "room")
        self.assertEqual(check["type"], "opposed_str")
        self.assertEqual(check["difficulty"], "hard")


class TestStagnationIntervention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "inv1": {
                "profile": {"name": "調査員", "is_npc": False},
                "attributes": {
                    "INT": 70,
                    "POW": 50,
                    "CON": 50,
                    "SIZ": 50,
                    "DEX": 50,
                    "STR": 50,
                    "LUK": 40,
                    "SAN": {"current": 50, "max": 99, "session_start": 50, "session_start_san": 50},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"目星": 50},
                "states": [],
            }
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text("{}", encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.state_mgr = GameStateManager(self.char_mgr)
        self.dice = DiceEngine()
        self.scenario = ScenarioManager({
            "scenario_meta": {
                "title": "t",
                "intervention_level": "light",
                "max_stagnation_turns": 3,
                "stagnation_hint": "机を別の技能で調べてみよう。",
            },
            "initial_state": {"location": "room", "flags": {"desk_searched": False}, "phase": "p"},
            "locations": {
                "room": {
                    "name": "部屋",
                    "objects": {
                        "desk": {"name": "机", "usable_actions": ["search"]},
                        "shelf": {"name": "棚", "usable_actions": ["search"]},
                    },
                    "connected_to": [],
                }
            },
            "event_triggers": [
                {
                    "event_id": "relief_knock",
                    "stagnation_relief": True,
                    "trigger_condition": "False",
                    "payload": {
                        "system_log": "【スタック救済】廊下からノック音が聞こえた。",
                        "kp_instruction": "ノック音を描写せよ。",
                        "flag_updates": {"visitor_knock": True},
                    },
                }
            ],
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_intervention_level_resolution(self):
        from GameStateManager import (
            InterventionLevel,
            normalize_intervention_level,
            resolve_effective_intervention_level,
            intervention_level_from_kp_style,
        )
        self.assertEqual(normalize_intervention_level("控えめ"), InterventionLevel.LIGHT)
        self.assertEqual(intervention_level_from_kp_style("helpful"), InterventionLevel.STANDARD)
        # scenario light + kp force = force
        self.assertEqual(
            resolve_effective_intervention_level("light", "force"),
            InterventionLevel.FORCE,
        )
        # scenario force + kp none = force
        self.assertEqual(
            resolve_effective_intervention_level("force", "none"),
            InterventionLevel.FORCE,
        )

    def test_scenario_meta_intervention_wiring(self):
        self.assertEqual(self.scenario.get_scenario_intervention_level(), "light")
        self.assertEqual(self.scenario.get_max_stagnation_turns(), 3)
        self.assertIn("机", self.scenario.get_stagnation_hint_text())

    def test_detect_stagnation_counter_increments(self):
        flags = dict(self.scenario.flags)
        fail_result = {
            "status": int(SuccessLevel.FAILURE),
            "action_id": "search",
            "target": "desk",
            "roll_type": "skill",
            "log": "失敗",
            "blocked": False,
        }
        pl_action = {"action": "search", "target": "desk", "skill": "目星"}

        for expected in (1, 2, 3):
            detection = self.state_mgr.detect_stagnation(
                [],
                location_id="room",
                flags=flags,
                max_stagnation_turns=3,
                last_pl_action=pl_action,
                last_system_result=fail_result,
                made_progress=False,
            )
            self.assertEqual(detection["streak"], expected)
            if expected < 3:
                self.assertFalse(detection["is_stagnant"])
                self.assertFalse(detection["needs_intervention"])
            else:
                self.assertTrue(detection["is_stagnant"])
                self.assertTrue(detection["needs_intervention"])

        # 進展でリセット
        detection = self.state_mgr.detect_stagnation(
            [],
            location_id="room",
            flags={**flags, "desk_searched": True},
            max_stagnation_turns=3,
            made_progress=True,
        )
        self.assertEqual(detection["streak"], 0)
        self.assertFalse(detection["is_stagnant"])

    def test_light_intervention_sets_kp_nudge(self):
        state = {
            "all_events_log": [],
            "current_loc": "room",
            "pl_id": "inv1",
            "char_name": "調査員",
            "intervention_level": "light",
            "kp_style": "classic",
        }
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        # scenario light + session light = light
        detection = {"streak": 3, "is_stagnant": True}
        applied = game_main.apply_stagnation_intervention(
            state, managers, InterventionLevel.LIGHT, detection,
        )
        self.assertIn("kp_nudge", applied["actions"])
        self.assertIn("不気味な変化", state["stagnation_kp_nudge"])
        prompt = game_main._build_kp_stagnation_injection(self.scenario, state=state)
        self.assertIn("隙間風", prompt)

    def test_standard_intervention_sets_pl_hint(self):
        state = {
            "all_events_log": [],
            "current_loc": "room",
            "pl_id": "inv1",
            "char_name": "調査員",
            "intervention_level": "standard",
        }
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        applied = game_main.apply_stagnation_intervention(
            state, managers, InterventionLevel.STANDARD, {"streak": 3},
        )
        self.assertIn("pl_hint", applied["actions"])
        self.assertIn("システムヒント", state["stagnation_pl_hint"])
        self.assertTrue(
            any("システムヒント" in (e.get("text") or "") for e in state["all_events_log"])
        )

    def test_force_intervention_fires_relief_or_idea(self):
        state = {
            "all_events_log": [],
            "current_loc": "room",
            "pl_id": "inv1",
            "char_name": "調査員",
            "intervention_level": "force",
        }
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        applied = game_main.apply_stagnation_intervention(
            state, managers, InterventionLevel.FORCE, {"streak": 3},
        )
        self.assertIn("relief_event", applied["actions"])
        self.assertTrue(self.scenario.flags.get("visitor_knock"))
        self.assertIn("スタック救済", state["last_system_result"]["log"])

    def test_force_idea_roll_without_relief_event(self):
        scenario = ScenarioManager({
            "scenario_meta": {
                "title": "t",
                "intervention_level": "force",
                "max_stagnation_turns": 2,
                "stagnation_hint": "棚を調べよ。",
            },
            "initial_state": {"location": "room", "flags": {}, "phase": "p"},
            "locations": {
                "room": {
                    "name": "部屋",
                    "objects": {"shelf": {"name": "棚", "usable_actions": ["search"]}},
                    "connected_to": [],
                }
            },
            "event_triggers": [],
        })
        state = {
            "all_events_log": [],
            "current_loc": "room",
            "pl_id": "inv1",
            "char_name": "調査員",
        }
        managers = (self.char_mgr, self.dice, self.state_mgr, scenario)
        with mock.patch.object(
            self.dice,
            "execute_int_roll",
            return_value={
                "log": "INTロール",
                "success_level": int(SuccessLevel.REGULAR_SUCCESS),
                "result": "レギュラー成功",
            },
        ):
            applied = game_main.apply_stagnation_intervention(
                state, managers, InterventionLevel.FORCE, {"streak": 2},
            )
        self.assertIn("idea_roll", applied["actions"])
        self.assertTrue(applied.get("idea_success"))
        self.assertIn("棚", state["last_system_result"]["log"])

    def test_session_effective_level_max(self):
        # scenario=light, session force → force
        state = {"intervention_level": "force", "kp_style": "classic"}
        level = game_main.resolve_session_intervention_level(state, self.scenario)
        self.assertEqual(level, InterventionLevel.FORCE)


class TestLuckAndPushRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "inv1": {
                "profile": {"name": "調査員", "is_npc": False},
                "attributes": {
                    "INT": 60,
                    "POW": 50,
                    "CON": 50,
                    "SIZ": 50,
                    "DEX": 50,
                    "STR": 50,
                    "LUK": 40,
                    "SAN": {"current": 50, "max": 99, "session_start": 50, "session_start_san": 50},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"目星": 50, "図書館": 40, "回避": 40},
                "states": [],
            }
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text("{}", encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.state_mgr = GameStateManager(self.char_mgr)
        self.dice = DiceEngine()
        self.scenario = ScenarioManager({
            "meta": {"title": "t"},
            "initial_state": {"location": "room", "flags": {}, "phase": "p"},
            "locations": {
                "room": {
                    "name": "部屋",
                    "objects": {
                        "desk": {"name": "机", "usable_actions": ["search"], "difficulty": "regular"},
                    },
                    "connected_to": [],
                }
            },
            "event_triggers": [],
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_luck_points_needed(self):
        self.assertEqual(luck_points_needed(60, 50), 10)
        self.assertEqual(luck_points_needed(50, 50), 0)
        self.assertEqual(self.dice.calculate_luck_points_needed(60, 50, "regular"), 10)
        self.assertEqual(self.dice.calculate_luck_points_needed(30, 50, "hard"), 5)  # hard target 25

    def test_failure_margin_includes_fumble(self):
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(100, [10], 0, 0)):
            result = self.dice.execute_skill_roll("探", "目星", 40)
        self.assertTrue(result["is_fumble"])
        self.assertEqual(result["failure_margin"], 60)

    def test_timeline_priority_pending_phases(self):
        state = {
            "pending_san_check": None,
            "pending_luck_burn": None,
            "pending_push_roll": None,
            "all_events_log": [],
            "char_name": "調査員",
        }
        self.assertIsNone(game_main.get_timeline_pending_phase(state))

        state["pending_push_roll"] = {"skill_name": "目星", "decision_pending": True}
        self.assertEqual(
            game_main.get_timeline_pending_phase(state),
            game_main.PENDING_PUSH_DECISION,
        )

        state["pending_luck_burn"] = {"margin": 5}
        self.assertEqual(
            game_main.get_timeline_pending_phase(state),
            game_main.PENDING_LUCK_CONSUMPTION,
        )

        state["pending_san_check"] = {"required": True, "success_loss": "0", "fail_loss": "1"}
        self.assertEqual(
            game_main.get_timeline_pending_phase(state),
            game_main.PENDING_SAN_CHECK,
        )

        step = game_main.determine_timeline_next_step(state, "調査員", self.scenario)
        self.assertEqual(step, "system_resolve_san")

        state["pending_san_check"] = None
        step = game_main.determine_timeline_next_step(state, "調査員", self.scenario)
        self.assertEqual(step, "luck_decision")

        state["pending_luck_burn"] = None
        step = game_main.determine_timeline_next_step(state, "調査員", self.scenario)
        self.assertEqual(step, "push_decision")

    def test_skill_fail_offers_luck_before_scenario(self):
        # skill 50, roll 55 → margin 5 → luck offered (LUK 40)
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(55, [5], 5, 0)):
            result = game_main.process_system_action(
                "inv1", "調査員", "search", "desk", "目星", "room",
                self.char_mgr, self.dice, self.scenario, state_mgr=self.state_mgr,
            )
        self.assertTrue(result.get("luck_decision_required"))
        self.assertEqual(result["pending_luck_burn"]["margin"], 5)
        self.assertIsNone(result.get("pending_push_roll"))

    def test_luck_decline_goes_to_push_decision_without_finalizing(self):
        pending_luck = game_main._build_push_roll_state(
            "desk", "目星", "search", 0, 0, 0,
            required_difficulty="regular",
            failed_success_level=int(SuccessLevel.FAILURE),
            allow_push=True,
        )
        pending_luck["margin"] = 5
        result = game_main.resolve_luck_burn_decision(
            "inv1", "調査員", False, pending_luck, "room",
            self.char_mgr, self.scenario, "【部分ログ】失敗",
        )
        self.assertTrue(result.get("push_decision_required"))
        self.assertTrue(result["pending_push_roll"]["decision_pending"])
        self.assertEqual(self.char_mgr.get_luck("inv1"), 40)

    def test_luck_accept_rewrites_success_and_spends(self):
        pending_luck = game_main._build_push_roll_state(
            "desk", "目星", "search", 0, 0, 0,
            required_difficulty="regular",
            failed_success_level=int(SuccessLevel.FAILURE),
            allow_push=True,
        )
        pending_luck["margin"] = 5
        result = game_main.resolve_luck_burn_decision(
            "inv1", "調査員", True, pending_luck, "room",
            self.char_mgr, self.scenario, "【部分ログ】失敗",
        )
        self.assertFalse(result.get("push_decision_required"))
        self.assertIsNone(result.get("pending_push_roll"))
        self.assertGreaterEqual(result["status"], int(SuccessLevel.REGULAR_SUCCESS))
        self.assertEqual(self.char_mgr.get_luck("inv1"), 35)

    def test_push_not_allowed_for_combat_skill(self):
        self.assertFalse(game_main._skill_allows_push("回避", "search"))
        self.assertFalse(game_main._skill_allows_push("近接戦闘", "attack", in_combat=True))
        self.assertTrue(game_main._skill_allows_push("目星", "search"))

    def test_insufficient_luck_goes_to_push(self):
        # margin 15 > LUCK_BURN_MAX 10 → no luck offer, push pending
        dice_result = {
            "is_failure": True,
            "is_fumble": False,
            "failure_margin": 15,
            "roll": 65,
            "target_value": 50,
            "success_level": int(SuccessLevel.FAILURE),
        }
        level, luck, push = game_main._handle_skill_roll_failure(
            dice_result, self.char_mgr, "inv1", "desk", "目星", "search",
            0, 0, 0, required_difficulty="regular",
        )
        self.assertIsNone(luck)
        self.assertIsNotNone(push)
        self.assertTrue(push["decision_pending"])
        self.assertEqual(level, int(SuccessLevel.FAILURE))

    def test_push_decline_finalizes_failure(self):
        pending = game_main._build_push_roll_state(
            "desk", "目星", "search", 0, 0, 0,
            failed_success_level=int(SuccessLevel.FAILURE),
        )
        result = game_main.resolve_push_decline(
            "inv1", "調査員", pending, "room", self.scenario, "失敗ログ",
        )
        self.assertEqual(result["status"], int(SuccessLevel.FAILURE))
        self.assertIsNone(result.get("pending_push_roll"))
        self.assertIn("プッシュ見送り", result["log"])

    def test_push_failure_applies_dire_penalty(self):
        with mock.patch.object(self.dice, "roll_dice_str", return_value=2):
            with mock.patch.object(
                DiceEngine,
                "execute_int_roll",
                return_value={
                    "roll": 99,
                    "success_level": int(SuccessLevel.FAILURE),
                    "result": "失敗",
                },
            ):
                penalty = self.state_mgr.apply_push_failure_penalty(
                    "inv1", dice_engine=self.dice, char_name="調査員",
                )
        self.assertEqual(penalty["san_loss"], 2)
        self.assertTrue(self.state_mgr.flags.get("push_failure_dire_outcome"))
        self.assertEqual(self.char_mgr.get_stat_current("inv1", "SAN"), 48)

    def test_push_roll_success_clears_pending(self):
        pending = game_main._build_push_roll_state(
            "desk", "目星", "search", 0, 0, 0,
            failed_success_level=int(SuccessLevel.FAILURE),
        )
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(20, [2], 0, 0)):
            result = game_main.process_system_action(
                "inv1", "調査員", "push_roll", "desk", "目星", "room",
                self.char_mgr, self.dice, self.scenario,
                state_mgr=self.state_mgr, pending_push_roll=pending,
            )
        self.assertTrue(is_success_level(result["status"]))
        self.assertIsNone(result.get("pending_push_roll"))


class TestCombatPipeline(unittest.TestCase):
    """DEX順戦闘・回避/応戦対抗・HP0意識不明の結合テスト。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "hero": {
                "profile": {"name": "英雄", "is_npc": False},
                "attributes": {
                    "INT": 50, "POW": 50, "CON": 50, "SIZ": 50,
                    "DEX": 70, "STR": 60, "EDU": 50,
                    "DB": "+1D4",
                    "LUK": 40,
                    "SAN": {"current": 50, "max": 99, "session_start": 50},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"近接戦闘": 60, "近接戦闘（格闘）": 60, "回避": 35},
                "weapons": [{
                    "name": "拳", "skill": "近接戦闘", "damage": "1D3",
                    "apply_damage_bonus": True,
                }],
                "states": [],
            }
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text(json.dumps({
            "goblin": {
                "profile": {"name": "ゴブリン", "is_npc": True, "monster": True},
                "attributes": {
                    "DEX": 40, "CON": 40, "SIZ": 40, "STR": 40,
                    "DB": "0",
                    "SAN": {"current": 0, "max": 99, "session_start": 0},
                    "HP": {"current": 8, "max": 8},
                    "MP": {"current": 5, "max": 5},
                },
                "skills": {"近接戦闘": 40, "回避": 20},
                "combat_profile": {"aggression": 80, "preferred_defense": "fight_back"},
                "weapons": [{
                    "name": "爪", "skill": "近接戦闘", "damage": "1D3",
                    "apply_damage_bonus": False,
                }],
                "states": [],
            },
            "swift": {
                "profile": {"name": "俊足の番人", "is_npc": True},
                "attributes": {
                    "DEX": 70, "CON": 50, "SIZ": 50, "STR": 50,
                    "DB": "0",
                    "SAN": {"current": 50, "max": 99, "session_start": 50},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"近接戦闘": 30, "回避": 35},
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.state_mgr = GameStateManager(self.char_mgr)
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_combat_pipeline(self):
        from CoCRules import resolve_melee_defense_outcome

        # --- DEX順イニシアチブ（同DEX時は近接技能が高い方優先）---
        with mock.patch("GameStateManager.random.randint", return_value=50):
            order = self.state_mgr.start_combat(["hero", "goblin", "swift"])
        # hero DEX70/近接60, swift DEX70/近接30 → hero が先
        self.assertEqual(order[0], "hero")
        self.assertEqual(order[1], "swift")
        self.assertEqual(order[2], "goblin")
        self.assertEqual(self.state_mgr.get_combat_turn_queue(), order)
        self.assertEqual(self.state_mgr.get_current_actor(), "hero")
        self.assertEqual(self.state_mgr.round_number, 1)

        # --- 回避ルール: 守 >= 攻 → 回避成功 ---
        self.assertEqual(resolve_melee_defense_outcome(3, 3, "dodge"), "dodged")
        self.assertEqual(resolve_melee_defense_outcome(4, 3, "dodge"), "hit_attacker")
        # --- 応戦ルール: 守 > 攻 → カウンター、守 <= 攻 → 攻撃命中 ---
        self.assertEqual(resolve_melee_defense_outcome(3, 4, "fight_back"), "counter")
        self.assertEqual(resolve_melee_defense_outcome(3, 3, "fight_back"), "hit_attacker")
        self.assertEqual(resolve_melee_defense_outcome(4, 2, "fight_back"), "hit_attacker")
        # --- 双方失敗 ---
        self.assertEqual(resolve_melee_defense_outcome(1, 1, "dodge"), "miss")
        self.assertEqual(resolve_melee_defense_outcome(0, 1, "fight_back"), "miss")

        # --- 攻撃宣言 → PENDING_COMBAT_DEFENSE（ダイス未実行）---
        begin = game_main.begin_combat_attack(
            "hero", "goblin",
            skill_name="近接戦闘",
            char_mgr=self.char_mgr,
            state_mgr=self.state_mgr,
        )
        self.assertTrue(begin["ok"])
        self.assertTrue(begin["combat_defense_required"])
        self.assertEqual(
            game_main.get_timeline_pending_phase({
                "pending_combat_defense": begin["pending_combat_defense"],
            }),
            game_main.PENDING_COMBAT_DEFENSE,
        )

        # --- 回避成功: ダメージ適用なし・手番が進む ---
        hp_before = self.char_mgr.get_stat_current("goblin", "HP")
        with mock.patch.object(
            DiceEngine, "execute_melee_opposed_roll",
            return_value={
                "outcome": "dodged",
                "defense_mode": "dodge",
                "attacker_level": 2,
                "defender_level": 3,
                "log": "mock dodge",
            },
        ):
            dodge_resolved = game_main.resolve_melee_combat_exchange(
                begin["pending_combat_defense"], "dodge",
                char_mgr=self.char_mgr, dice_engine=self.dice, state_mgr=self.state_mgr,
            )
        self.assertEqual(dodge_resolved["outcome"], "dodged")
        self.assertEqual(self.char_mgr.get_stat_current("goblin", "HP"), hp_before)
        self.assertEqual(self.state_mgr.get_current_actor(), "swift")

        # --- 応戦で攻撃命中パス ---
        self.state_mgr.current_turn_index = self.state_mgr.turn_order.index("hero")
        begin2 = game_main.begin_combat_attack(
            "hero", "goblin",
            char_mgr=self.char_mgr, state_mgr=self.state_mgr,
        )
        self.assertTrue(begin2["ok"])
        with mock.patch.object(
            DiceEngine, "execute_melee_opposed_roll",
            return_value={
                "outcome": "hit_attacker",
                "defense_mode": "fight_back",
                "attacker_level": 3,
                "defender_level": 2,
                "log": "mock opposed",
            },
        ):
            with mock.patch.object(self.state_mgr, "apply_melee_hit") as mock_hit:
                mock_hit.return_value = {
                    "damage": 3, "old_hp": 8, "new_hp": 5,
                    "damage_detail": "1D3→3", "weapon_name": "拳", "events": [],
                }
                hit_res = game_main.resolve_melee_combat_exchange(
                    begin2["pending_combat_defense"], "fight_back",
                    char_mgr=self.char_mgr, dice_engine=self.dice, state_mgr=self.state_mgr,
                )
        self.assertEqual(hit_res["outcome"], "hit_attacker")
        mock_hit.assert_called_once()

        # --- 応戦カウンターパス ---
        self.state_mgr.current_turn_index = self.state_mgr.turn_order.index("hero")
        begin3 = game_main.begin_combat_attack(
            "hero", "goblin",
            char_mgr=self.char_mgr, state_mgr=self.state_mgr,
        )
        with mock.patch.object(
            DiceEngine, "execute_melee_opposed_roll",
            return_value={
                "outcome": "counter",
                "defense_mode": "fight_back",
                "attacker_level": 2,
                "defender_level": 4,
                "log": "mock counter",
            },
        ):
            with mock.patch.object(self.state_mgr, "apply_melee_hit") as mock_counter:
                mock_counter.return_value = {
                    "damage": 2, "old_hp": 10, "new_hp": 8,
                    "damage_detail": "1D3→2", "weapon_name": "爪", "events": [],
                }
                counter_res = game_main.resolve_melee_combat_exchange(
                    begin3["pending_combat_defense"], "fight_back",
                    char_mgr=self.char_mgr, dice_engine=self.dice, state_mgr=self.state_mgr,
                )
        self.assertEqual(counter_res["outcome"], "counter")
        # カウンターは防御側→攻撃側
        args, kwargs = mock_counter.call_args
        self.assertEqual(args[0], "goblin")
        self.assertEqual(args[1], "hero")

        # --- HP0で意識不明 ---
        self.char_mgr.set_stat_current("goblin", "HP", 2)
        dmg = self.state_mgr.apply_physical_damage("goblin", 2)
        self.assertEqual(dmg["new_hp"], 0)
        self.assertTrue(
            dmg.get("unconscious")
            or "意識不明" in (self.char_mgr.characters["goblin"].get("states") or [])
        )
        self.assertTrue(self.state_mgr.is_combat_participant_incapacitated("goblin"))

        # 意識不明キャラは手番スキップ
        self.state_mgr.turn_order = ["goblin", "hero"]
        self.state_mgr.combat_turn_queue = list(self.state_mgr.turn_order)
        self.state_mgr.current_turn_index = 0
        self.state_mgr.in_combat = True
        actor = self.state_mgr._advance_to_capable_actor(reset_search=True)
        self.assertEqual(actor, "hero")

        # 即死: 一撃で最大HP以上
        fatal = self.state_mgr.apply_physical_damage("swift", 99)
        self.assertTrue(fatal.get("dead"))
        self.assertIn("死亡", self.char_mgr.characters["swift"].get("states") or [])


class TestFirearmCombatPipeline(unittest.TestCase):
    """銃器射撃解決: 応戦ガード / ゼロ距離ボーナス / 貫通ダメージ。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "hero": {
                "profile": {"name": "射撃手", "is_npc": False},
                "attributes": {
                    "DEX": 70, "CON": 50, "SIZ": 50, "STR": 50, "INT": 60, "POW": 50,
                    "DB": "0",
                    "LUK": 40,
                    "SAN": {"current": 50, "max": 99, "session_start": 50},
                    "HP": {"current": 12, "max": 12},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {
                    "近接戦闘": 25,
                    "射撃（拳銃）": 70,
                    "射撃": 70,
                    "回避": 40,
                },
                "weapons": [{
                    "name": ".38自動拳銃",
                    "skill": "射撃（拳銃）",
                    "damage": "1D10",
                    "apply_damage_bonus": False,
                    "type": "firearm",
                }],
                "states": [],
            }
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text(json.dumps({
            "target": {
                "profile": {"name": "標的", "is_npc": True},
                "attributes": {
                    "DEX": 40, "CON": 50, "SIZ": 50, "STR": 50,
                    "DB": "0",
                    "SAN": {"current": 50, "max": 99, "session_start": 50},
                    "HP": {"current": 20, "max": 20},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"近接戦闘": 40, "回避": 30, "射撃": 20},
                "combat_profile": {"preferred_defense": "fight_back", "aggression": 90},
                "states": [],
            },
            "gunner": {
                "profile": {"name": "銃使いNPC", "is_npc": True},
                "attributes": {
                    "DEX": 80, "CON": 50, "SIZ": 50, "STR": 50,
                    "DB": "0",
                    "SAN": {"current": 50, "max": 99, "session_start": 50},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"射撃（拳銃）": 80, "近接戦闘": 20, "回避": 40},
                "weapons": [{
                    "name": "拳銃", "skill": "射撃（拳銃）", "damage": "1D10",
                    "type": "firearm",
                }],
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.state_mgr = GameStateManager(self.char_mgr)
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fight_back_not_allowed_against_firearm(self):
        from CoCRules import resolve_firearm_defense_outcome

        self.assertEqual(
            resolve_firearm_defense_outcome(4, 2, "fight_back"),
            "not_allowed",
        )
        ok, mode, err = game_main.validate_shoot_defense_mode("fight_back")
        self.assertFalse(ok)
        self.assertIsNone(mode)
        self.assertIn("応戦", err)

        with mock.patch("GameStateManager.random.randint", return_value=50):
            self.state_mgr.start_combat(["hero", "target"])
        begin = game_main.begin_shoot_attack(
            "hero", "target",
            skill_name="射撃（拳銃）",
            char_mgr=self.char_mgr,
            state_mgr=self.state_mgr,
            current_loc="study",
        )
        self.assertTrue(begin["ok"])
        self.assertEqual(
            game_main.get_timeline_pending_phase({
                "pending_combat_defense": begin["pending_combat_defense"],
            }),
            game_main.PENDING_SHOOT_DEFENSE,
        )

        rejected = game_main.resolve_shoot_combat_exchange(
            begin["pending_combat_defense"], "fight_back",
            char_mgr=self.char_mgr, dice_engine=self.dice, state_mgr=self.state_mgr,
        )
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["outcome"], "not_allowed")
        self.assertTrue(rejected.get("rejected_fight_back"))
        # ガード時は pending を維持（手番を消費しない）
        self.assertIsNotNone(self.state_mgr.get_pending_combat_defense())

        # NPC は preferred_defense=fight_back でも射撃時は応戦を選ばない
        npc_mode = self.state_mgr.choose_npc_defense_mode("target", attack_type="shoot")
        self.assertIn(npc_mode, ("dodge", "accept"))
        self.assertNotEqual(npc_mode, "fight_back")

    def test_point_blank_grants_bonus_die(self):
        with mock.patch("GameStateManager.random.randint", return_value=50):
            self.state_mgr.start_combat(["hero", "target"])

        begin = game_main.begin_shoot_attack(
            "hero", "target",
            skill_name="射撃（拳銃）",
            char_mgr=self.char_mgr,
            state_mgr=self.state_mgr,
            current_loc="study",
        )
        self.assertTrue(begin["ok"])
        self.assertTrue(begin.get("point_blank"))
        self.assertEqual(begin.get("bonus_dice"), 1)
        self.assertEqual(begin["pending_combat_defense"].get("bonus_dice"), 1)

        # 遠距離指定武器ではボーナスなし
        long_gun = {
            "name": "ライフル", "skill": "射撃", "damage": "1D6+1",
            "range": "long", "type": "firearm",
        }
        begin_long = game_main.begin_shoot_attack(
            "hero", "target",
            weapon=long_gun,
            char_mgr=self.char_mgr,
            state_mgr=self.state_mgr,
            current_loc="study",
            skip_turn_check=True,
        )
        self.assertFalse(begin_long.get("point_blank"))
        self.assertEqual(begin_long.get("bonus_dice"), 0)

        # resolve 時に bonus_dice がロールへ渡る
        with mock.patch.object(
            DiceEngine, "execute_firearm_attack_roll",
            return_value={
                "outcome": "miss",
                "defense_mode": "accept",
                "attacker_level": 1,
                "defender_level": 0,
                "log": "mock",
            },
        ) as mock_roll:
            game_main.resolve_shoot_combat_exchange(
                begin["pending_combat_defense"], "accept",
                char_mgr=self.char_mgr, dice_engine=self.dice, state_mgr=self.state_mgr,
            )
        self.assertEqual(mock_roll.call_args.kwargs.get("attacker_bonus"), 1)

    def test_impale_damage_on_extreme_hit(self):
        from CoCRules import compute_firearm_damage, max_dice_formula_value

        self.assertEqual(max_dice_formula_value("1D10"), 10)

        # 貫通: 最大10 + ロール値
        with mock.patch("CoCRules.roll_dice_formula", return_value=7):
            dmg, detail = compute_firearm_damage("1D10", is_impale=True)
        self.assertEqual(dmg, 17)
        self.assertIn("貫通", detail)

        with mock.patch("GameStateManager.random.randint", return_value=50):
            self.state_mgr.start_combat(["hero", "target"])
        begin = game_main.begin_shoot_attack(
            "hero", "target",
            char_mgr=self.char_mgr, state_mgr=self.state_mgr, current_loc="alley",
        )
        hp_before = self.char_mgr.get_stat_current("target", "HP")

        with mock.patch.object(
            DiceEngine, "execute_firearm_attack_roll",
            return_value={
                "outcome": "hit_attacker",
                "defense_mode": "accept",
                "attacker_level": int(SuccessLevel.EXTREME_SUCCESS),
                "defender_level": 0,
                "log": "mock extreme hit",
            },
        ):
            with mock.patch("CoCRules.roll_dice_formula", return_value=4):
                resolved = game_main.resolve_shoot_combat_exchange(
                    begin["pending_combat_defense"], "accept",
                    char_mgr=self.char_mgr, dice_engine=self.dice, state_mgr=self.state_mgr,
                )

        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["outcome"], "hit_attacker")
        self.assertTrue(resolved.get("impale"))
        # 10 (max) + 4 (roll) = 14
        expected = 14
        hp_after = self.char_mgr.get_stat_current("target", "HP")
        self.assertEqual(hp_before - hp_after, expected)
        self.assertEqual(resolved["damage_results"][0]["damage"], expected)
        self.assertTrue(resolved["damage_results"][0].get("impale"))

    def test_firearm_initiative_uses_shoot_skill_tiebreak(self):
        # DEX同値時、射撃技能が高い gunner が hero より先
        self.char_mgr.characters["hero"]["attributes"]["DEX"] = 80
        self.char_mgr.characters["gunner"]["attributes"]["DEX"] = 80
        with mock.patch("GameStateManager.random.randint", return_value=50):
            order = self.state_mgr.start_combat(["hero", "gunner"])
        self.assertEqual(order[0], "gunner")
        self.assertEqual(order[1], "hero")

    def test_accept_hit_requires_regular_success(self):
        from CoCRules import resolve_firearm_defense_outcome

        self.assertEqual(resolve_firearm_defense_outcome(2, 0, "accept"), "hit_attacker")
        self.assertEqual(resolve_firearm_defense_outcome(1, 0, "accept"), "miss")
        self.assertEqual(resolve_firearm_defense_outcome(3, 3, "dodge"), "dodged")
        self.assertEqual(resolve_firearm_defense_outcome(4, 3, "dodge"), "hit_attacker")


class TestMultiPlayerSupport(unittest.TestCase):
    """複数PL: 探索ラウンドロビン / 戦闘DEX順 / active_pcs。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "pc_01": {
                "profile": {
                    "name": "マクガフィン刑事", "is_npc": False,
                    "occupation": "刑事",
                    "personality": "ぶっきらぼう",
                    "action_guide": "目星優先",
                },
                "attributes": {
                    "DEX": 70, "CON": 60, "SIZ": 60, "STR": 55, "INT": 65, "POW": 55,
                    "DB": "0",
                    "SAN": {"current": 55, "max": 99, "session_start": 55},
                    "HP": {"current": 12, "max": 12},
                    "MP": {"current": 11, "max": 11},
                    "LUCK": 45,
                },
                "skills": {"目星": 65, "近接戦闘": 55, "射撃（拳銃）": 50, "回避": 35},
                "states": [],
            },
            "pc_02": {
                "profile": {
                    "name": "エレノア教授", "is_npc": False,
                    "occupation": "民俗学教授",
                    "personality": "冷静",
                    "action_guide": "図書館優先",
                },
                "attributes": {
                    "DEX": 55, "CON": 50, "SIZ": 50, "STR": 40, "INT": 80, "POW": 70,
                    "DB": "-1",
                    "SAN": {"current": 60, "max": 99, "session_start": 60},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 14, "max": 14},
                    "LUCK": 50,
                },
                "skills": {"図書館": 75, "歴史": 70, "近接戦闘": 30, "回避": 27},
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text(json.dumps({
            "enemy": {
                "profile": {"name": "敵", "is_npc": True, "monster": True},
                "attributes": {
                    "DEX": 40, "CON": 50, "SIZ": 50, "STR": 50,
                    "DB": "0",
                    "SAN": {"current": 0, "max": 99, "session_start": 0},
                    "HP": {"current": 8, "max": 8},
                    "MP": {"current": 5, "max": 5},
                },
                "skills": {"近接戦闘": 40, "回避": 20},
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.char_mgr.set_active_pcs(["pc_01", "pc_02"])
        self.state_mgr = GameStateManager(self.char_mgr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_get_pc_and_active_list(self):
        self.assertIsNotNone(self.char_mgr.get_pc("pc_01"))
        self.assertIsNone(self.char_mgr.get_pc("enemy"))
        self.assertEqual(self.char_mgr.active_pc_list, ["pc_01", "pc_02"])
        sheet = self.char_mgr.build_character_sheet_summary("pc_01")
        self.assertIn("マクガフィン刑事", sheet)
        self.assertIn("PC1", sheet)
        self.assertIn("目星", sheet)

    def test_exploration_round_robin(self):
        state = {
            "active_pcs": ["pc_01", "pc_02"],
            "active_pc_id": "pc_01",
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "all_events_log": [],
        }
        game_main.ensure_multi_pl_state(state, self.char_mgr)
        self.assertEqual(state["active_pc_id"], "pc_01")

        next_id = game_main.advance_exploration_turn(state, self.char_mgr, self.state_mgr)
        self.assertEqual(next_id, "pc_02")
        self.assertEqual(state["pl_id"], "pc_02")
        self.assertEqual(state["char_name"], "エレノア教授")

        next_id = game_main.advance_exploration_turn(state, self.char_mgr, self.state_mgr)
        self.assertEqual(next_id, "pc_01")

        # 気絶 PC はスキップ
        self.char_mgr.characters["pc_01"]["states"] = ["意識不明"]
        self.char_mgr.set_stat_current("pc_01", "HP", 0)
        state["active_pc_id"] = "pc_02"
        next_id = game_main.advance_exploration_turn(state, self.char_mgr, self.state_mgr)
        self.assertEqual(next_id, "pc_02")

    def test_combat_queue_includes_all_pcs_by_dex(self):
        with mock.patch("GameStateManager.random.randint", return_value=50):
            order = self.state_mgr.start_combat(["pc_01", "pc_02", "enemy"])
        # pc_01 DEX70, pc_02 DEX55, enemy DEX40
        self.assertEqual(order[0], "pc_01")
        self.assertEqual(order[1], "pc_02")
        self.assertEqual(order[2], "enemy")
        self.assertEqual(self.state_mgr.get_current_actor(), "pc_01")

        # 次手番
        actor = self.state_mgr.next_turn()
        self.assertEqual(actor, "pc_02")
        actor = self.state_mgr.next_turn()
        self.assertEqual(actor, "enemy")

    def test_log_prefix_and_combat_start_participants(self):
        prefix = self.char_mgr.get_pc_log_prefix("pc_01", role="PC")
        self.assertEqual(prefix, "マクガフィン刑事(PC1)")
        parts = game_main._combat_start_participants(
            "pc_01", "enemy", active_pcs=["pc_01", "pc_02"],
        )
        self.assertEqual(parts, ["pc_01", "pc_02", "enemy"])

    def test_npc_picks_capable_pc_target(self):
        state = {
            "active_pcs": ["pc_01", "pc_02"],
            "pl_id": "pc_01",
            "active_pc_id": "pc_01",
        }
        with mock.patch("GameStateManager.random.randint", return_value=50):
            self.state_mgr.start_combat(["pc_01", "pc_02", "enemy"])
        # skip to enemy turn
        self.state_mgr.current_turn_index = self.state_mgr.turn_order.index("enemy")
        self.char_mgr.characters["pc_01"]["states"] = ["意識不明"]
        self.char_mgr.set_stat_current("pc_01", "HP", 0)
        target = game_main.pick_npc_combat_target(state, self.char_mgr, self.state_mgr)
        self.assertEqual(target, "pc_02")


class TestNPCSocialNegotiation(unittest.TestCase):
    """NPC対話・交渉技能・秘密開示・関係性更新。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "pc_01": {
                "profile": {"name": "マクガフィン刑事", "is_npc": False},
                "attributes": {
                    "POW": 55, "INT": 65, "APP": 50,
                    "SAN": {"current": 55, "max": 99, "session_start": 55},
                    "HP": {"current": 12, "max": 12},
                    "MP": {"current": 11, "max": 11},
                    "LUCK": 45,
                },
                "skills": {
                    "説得": 70, "言いくるめ": 60, "威圧": 55, "魅惑": 40, "心理学": 50,
                },
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text(json.dumps({
            "npc_neighbor_elder": {
                "profile": {"name": "近所の老人", "is_npc": True},
                "attributes": {
                    "POW": 50, "INT": 50, "APP": 45,
                    "SAN": {"current": 50, "max": 99, "session_start": 50},
                    "HP": {"current": 9, "max": 9},
                    "MP": {"current": 10, "max": 10},
                },
                "skills": {"心理学": 40, "聞き耳": 50},
                "personality": "頑固で疑り深い。",
                "relationship_status": "uncooperative",
                "secrets": {
                    "secret_01": {
                        "content": "夜になると、地下から鎖を引きずるような音ときしみ声が聞こえる。",
                        "reveal_condition": (
                            "success_level >= 2 and "
                            "(skill in ['説得', '言いくるめ', '威圧', '魅惑'])"
                        ),
                    },
                },
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.dice = DiceEngine()
        from NPCSocialManager import NPCSocialManager
        self.social = NPCSocialManager(self.char_mgr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_metadata_and_relationship_normalize(self):
        self.assertEqual(self.social.get_relationship("npc_neighbor_elder"), "uncooperative")
        self.assertIn("頑固", self.social.get_personality("npc_neighbor_elder"))
        secrets = self.social.get_secrets("npc_neighbor_elder")
        self.assertIn("secret_01", secrets)

    def test_casual_talk_no_dice_no_secret(self):
        result = self.social.resolve_casual_talk("pc_01", "npc_neighbor_elder")
        self.assertTrue(result["ok"])
        self.assertTrue(result["casual"])
        self.assertEqual(result["revealed_secrets"], [])
        self.assertEqual(result["relationship"], "uncooperative")
        self.assertIn("判定なし", result["log"])

    def test_negotiate_success_reveals_secret_and_can_improve_relation(self):
        # 出目を常に成功寄りに固定
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(15, [1], 5, 0)):
            result = self.social.resolve_negotiation(
                "pc_01", "npc_neighbor_elder",
                skill_name="説得", dice_engine=self.dice, action_id="persuade",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["is_success"])
        self.assertGreaterEqual(result["success_level"], 2)
        self.assertTrue(any(s["id"] == "secret_01" for s in result["revealed_secrets"]))
        self.assertIn("秘密開示", result["log"])
        # uncooperative + hard成功以上で +1 → neutral になり得る
        self.assertIn(result["relationship"], ("uncooperative", "neutral", "cooperative"))

    def test_negotiate_fumble_worsens_intimidate(self):
        self.social.set_relationship("npc_neighbor_elder", "neutral")
        # 出目100相当のファンブルを狙う（技能55未満なので96-100）
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(100, [9], 0, 0)):
            result = self.social.resolve_negotiation(
                "pc_01", "npc_neighbor_elder",
                skill_name="威圧", dice_engine=self.dice, action_id="intimidate",
            )
        self.assertFalse(result["is_success"])
        self.assertEqual(result["success_level"], 0)
        self.assertEqual(result["relationship"], "hostile")
        self.assertEqual(result["revealed_secrets"], [])

    def test_reveal_condition_evaluates_skill_list(self):
        revealed = self.social.evaluate_secret_reveals(
            "npc_neighbor_elder",
            success_level=2, skill="説得",
            relationship="neutral", is_success=True,
        )
        self.assertEqual(len(revealed), 1)
        self.assertIn("鎖", revealed[0]["content"])
        # 再開示なし
        again = self.social.evaluate_secret_reveals(
            "npc_neighbor_elder",
            success_level=5, skill="説得",
            relationship="cooperative", is_success=True,
        )
        self.assertEqual(again, [])

    def test_main_process_system_social_action(self):
        scenario_mgr = ScenarioManager({
            "scenario_meta": {"title": "test"},
            "initial_state": {
                "location": "street",
                "flags": {},
                "current_phase": "start",
            },
            "locations": {
                "street": {
                    "name": "通り",
                    "default_description": "静かな通り",
                    "objects": {},
                    "connected_to": [],
                },
            },
            "event_triggers": [],
        })
        with mock.patch.object(self.dice, "roll_1d100_with_bp", return_value=(15, [1], 5, 0)):
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "persuade", "近所の老人", "説得",
                "street", self.char_mgr, self.dice, scenario_mgr,
            )
        self.assertEqual(result.get("roll_type"), "social_negotiate")
        self.assertIn("npc_roleplay", result)
        self.assertIn("近所の老人", result.get("kp_instruction", ""))
        self.assertFalse(game_main.is_chat_only_pl_action({"action": "talk"}))
        self.assertFalse(game_main.is_chat_only_pl_action({"action": "persuade"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
