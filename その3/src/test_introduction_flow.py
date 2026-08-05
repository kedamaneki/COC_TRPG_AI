"""
導入フェーズ: 空オブジェクト no-roll / usable_actions / ノット氏対話・移動解禁。
実行: python test_introduction_flow.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from ScenarioManager import ScenarioManager
import main as game_main


CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"


class TestIntroductionFlowGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CORBITT.exists():
            raise unittest.SkipTest("scenario_corbitt.json がありません")
        cls.scenario_data = json.loads(CORBITT.read_text(encoding="utf-8"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        # 本番 npcs.json 相当の Knott + 最小 PC
        prod_npcs = Path(__file__).resolve().parent / "npcs.json"
        self.npc_path.write_text(prod_npcs.read_text(encoding="utf-8"), encoding="utf-8")
        self.pc_path.write_text(json.dumps({
            "pc_01": {
                "profile": {"name": "マクガフィン刑事", "is_npc": False},
                "attributes": {
                    "POW": 55, "INT": 65,
                    "SAN": {"current": 55, "max": 99, "session_start": 55},
                    "HP": {"current": 12, "max": 12},
                    "MP": {"current": 11, "max": 11},
                    "LUCK": 45,
                },
                "skills": {"目星": 65, "説得": 50},
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.scenario = ScenarioManager(json.loads(json.dumps(self.scenario_data)))
        self.scenario.location = "introduction"
        self.dice = DiceEngine()
        # 職業RP判定は単体では中立固定（LLM非依存）
        self._rp_patch = mock.patch.object(
            game_main,
            "judge_occupation_roleplay",
            return_value={
                "fit": "neutral",
                "bonus_dice": 0,
                "penalty_dice": 0,
                "skip_roll": False,
                "auto_success_level": 2,
                "reason": "テスト用中立",
            },
        )
        self._rp_patch.start()

    def tearDown(self):
        self._rp_patch.stop()
        self.tmp.cleanup()

    def test_office_desk_search_remapped_or_no_roll(self):
        """search は usable_actions 外 → inspect へ補正され、その後 no_roll。"""
        coerced = self.scenario.coerce_object_action("search", "office_desk", "introduction")
        self.assertTrue(coerced.get("remapped"))
        self.assertEqual(coerced.get("action_id"), "inspect")

        with mock.patch.object(self.dice, "execute_skill_roll") as mocked_roll:
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "search", "office_desk", "目星",
                "introduction", self.char_mgr, self.dice, self.scenario,
            )
            mocked_roll.assert_not_called()
        self.assertTrue(result.get("no_roll") or result.get("empty_clue") or result.get("blocked"))
        self.assertIn("判定なし", result.get("log", "") + result.get("kp_instruction", ""))
        self.assertNotIn("CC(1d100", result.get("log", ""))

    def test_empty_object_skips_dice(self):
        with mock.patch.object(self.dice, "execute_skill_roll") as mocked_roll:
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事", "inspect", "office_desk", "目星",
                "introduction", self.char_mgr, self.dice, self.scenario,
            )
            mocked_roll.assert_not_called()
        self.assertEqual(result.get("roll_type"), "no_roll")
        self.assertTrue(result.get("no_roll"))
        self.assertIn("判定なし", result.get("log", ""))
        self.assertIn("なさそう", result.get("log", ""))

    def test_steven_knott_talk_unlocks_exits(self):
        self.assertIsNotNone(self.char_mgr.characters.get("steven_knott"))
        self.assertFalse(self.scenario.flags.get("talked_with_knott"))
        exits_before = self.scenario.get_available_exits("introduction")
        self.assertEqual(exits_before, [])

        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "スティーブン・ノット", "",
            "introduction", self.char_mgr, self.dice, self.scenario,
        )
        self.assertIn(result.get("roll_type"), ("social_talk", "social_negotiate"))
        self.assertTrue(self.scenario.flags.get("talked_with_knott"))
        # 対話ルートで資料フラグも同期される
        self.assertTrue(self.scenario.flags.get("case_accepted"))
        self.assertTrue(self.scenario.flags.get("knott_letter_read"))
        self.assertTrue(self.scenario.flags.get("knott_memo_read"))
        self.assertIn("移動が解禁", result.get("log", ""))
        exits_after = self.scenario.get_available_exits("introduction")
        dest_ids = {e["id"] for e in exits_after}
        self.assertIn("boston_globe", dest_ids)
        # 屋敷外観も letter 同期により到達可能
        self.assertIn("corbitt_exterior", dest_ids)

    def test_steven_knott_talk_unlock_message_is_idempotent(self):
        """2回目の talk で解禁通知が重複しない。"""
        game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "steven_knott", "",
            "introduction", self.char_mgr, self.dice, self.scenario,
        )
        second = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "steven_knott", "",
            "introduction", self.char_mgr, self.dice, self.scenario,
        )
        unlock_count = second.get("log", "").count("移動が解禁")
        self.assertEqual(unlock_count, 0)

    def test_force_ic_rejects_wait_and_stale_talk(self):
        from ActionValidator import validate_force_ic_action
        self.scenario.flags["talked_with_knott"] = True
        wait_check = validate_force_ic_action(
            {"action": "wait"},
            force_ic_action=True,
            scenario_mgr=self.scenario,
            current_loc="introduction",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(wait_check["ok"])
        self.assertEqual(wait_check.get("error_code"), "force_ic_wait")

        talk_check = validate_force_ic_action(
            {"action": "talk", "target": "steven_knott"},
            force_ic_action=True,
            scenario_mgr=self.scenario,
            current_loc="introduction",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(talk_check["ok"])
        self.assertEqual(talk_check.get("error_code"), "force_ic_stale_talk")

    def test_forced_progress_breakout_moves_to_boston_globe(self):
        from GameStateManager import GameStateManager
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["case_accepted"] = True
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        self.scenario.location = "introduction"
        state_mgr = GameStateManager(self.char_mgr)
        state_mgr.flags = self.scenario.flags
        self.scenario.bind_game_state(state_mgr)
        state = {
            "all_events_log": [],
            "current_loc": "introduction",
            "force_ic_action": True,
            "stagnation_pl_hint": "ヒント",
            "autonomous_guard": {"chat_rounds_without_action": 3},
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
        }
        managers = (self.char_mgr, self.dice, state_mgr, self.scenario)
        forced = game_main.apply_forced_progress_breakout(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
        )
        self.assertIsNotNone(forced)
        self.assertEqual(forced.get("action"), "move")
        self.assertEqual(forced.get("target"), "boston_globe")
        self.assertEqual(state.get("current_loc"), "boston_globe")
        self.assertFalse(state.get("force_ic_action"))
        self.assertEqual(
            (state.get("autonomous_guard") or {}).get("chat_rounds_without_action"),
            0,
        )

    def test_master_json_not_polluted_by_session_social(self):
        """save_data が session_social / session_skill_marks をマスターへ書かない。"""
        knott = self.char_mgr.characters["steven_knott"]
        knott["session_social"] = {
            "relationship_status": "cooperative",
            "revealed_secrets": ["secret_case_brief"],
            "dialogue_count": 1,
        }
        self.char_mgr.characters["pc_01"]["session_skill_marks"] = ["目星"]
        self.char_mgr.save_data()

        npcs = json.loads(self.npc_path.read_text(encoding="utf-8"))
        pcs = json.loads(self.pc_path.read_text(encoding="utf-8"))
        self.assertNotIn("session_social", npcs.get("steven_knott", {}))
        self.assertNotIn("session_skill_marks", pcs.get("pc_01", {}))
        # メモリ上のセッション状態は残る
        self.assertIn("session_social", self.char_mgr.characters["steven_knott"])

    def test_letter_and_memo_also_unlock_exits(self):
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        exits = self.scenario.get_available_exits("introduction")
        self.assertIn("boston_globe", {e["id"] for e in exits})

    def test_kp_prompt_contains_strict_rules(self):
        text = game_main._build_kp_narrative_constraints()
        self.assertIn("厳格描写ルール", text)
        self.assertIn("捏造", text)
        self.assertIn("矛盾描写の禁止", text)
        loc = self.scenario.get_location_info("introduction")
        prompt = game_main.generate_kp_prompt(
            loc,
            last_pl_action={"action": "inspect", "target": "office_desk", "skill": "", "message": ""},
            last_system_result={
                "log": "【調査・判定なし】",
                "kp_instruction": "引導",
                "target": "office_desk",
                "no_roll": True,
                "empty_clue": True,
            },
            scenario_mgr=self.scenario,
        )
        self.assertIn("開示可能な確定情報", prompt)
        self.assertIn("office_desk", prompt)

    def test_sync_progress_managers_migrates_legacy_save(self):
        from GameStateManager import GameStateManager
        state_mgr = GameStateManager(self.char_mgr)
        scenario = ScenarioManager(json.loads(json.dumps(self.scenario_data)))
        save_data = {
            "game_state": {"turn_count": 0, "flags": {}},
            "scenario_manager": {
                "turn_counter": 3,
                "flags": {"knott_letter_read": True, "talked_with_knott": True},
            },
        }
        game_main.sync_progress_managers(state_mgr, scenario, save_data=save_data)
        self.assertEqual(state_mgr.turn_count, 3)
        self.assertTrue(state_mgr.flags.get("knott_letter_read"))
        self.assertTrue(scenario.flags.get("talked_with_knott"))

    def test_recover_pending_timeline_syncs_last_pl_action(self):
        app_state = {
            "all_events_log": [{
                "channel": "IC",
                "location": "introduction",
                "text": "エレノア教授(PC2): ノット氏、話を聞いてください",
                "meta": {
                    "pc_id": "pc_02",
                    "action_id": "talk",
                    "target": "",
                    "needs_system": True,
                    "system_processed": False,
                },
            }],
            "last_pl_action": {"action": "talk", "target": "", "skill": ""},
            "is_running": True,
            "current_loc": "introduction",
        }
        recovered = game_main.recover_pending_timeline_on_load(
            app_state, scenario_mgr=self.scenario, char_mgr=self.char_mgr,
        )
        self.assertEqual(recovered["last_pl_action"].get("target"), "steven_knott")
        self.assertEqual(
            recovered["all_events_log"][-1]["meta"].get("target"),
            "steven_knott",
        )

    def test_staged_knott_secrets_on_first_and_second_talk(self):
        from NPCSocialManager import NPCSocialManager
        knott = self.char_mgr.characters.get("steven_knott", {})
        knott["session_social"] = {
            "relationship_status": "cooperative",
            "revealed_secrets": [],
            "dialogue_count": 0,
        }
        social_mgr = NPCSocialManager(self.char_mgr)
        first = social_mgr.resolve_casual_talk("pc_01", "steven_knott", dialogue_text="依頼の概要を教えて")
        first_ids = {s["id"] for s in first.get("revealed_secrets", [])}
        self.assertIn("secret_case_brief", first_ids)
        self.assertNotIn("secret_tenant_hint", first_ids)

        second = social_mgr.resolve_casual_talk(
            "pc_01", "steven_knott", dialogue_text="前の借家人について教えて",
        )
        second_ids = {s["id"] for s in second.get("revealed_secrets", [])}
        self.assertIn("secret_tenant_hint", second_ids)

    def test_introduction_move_nudge_in_pl_prompt(self):
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        self.scenario.flags["talked_with_knott"] = True
        loc = self.scenario.get_location_info("introduction")
        prompt = game_main.generate_pl_prompt(
            "マクガフィン刑事", [], [], loc,
            available_exits=self.scenario.get_available_exits("introduction"),
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertIn("【システム通知（推奨行動）】", prompt)
        self.assertIn("boston_globe", prompt)


    def test_move_to_boston_globe_succeeds_when_unlocked(self):
        self.scenario.flags["talked_with_knott"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "move", "boston_globe", "",
            "introduction", self.char_mgr, self.dice, self.scenario,
        )
        self.assertFalse(result.get("blocked"), result.get("log"))
        self.assertTrue(result.get("location_changed"))
        self.assertEqual(result.get("new_location"), "boston_globe")
        self.assertEqual(self.scenario.location, "boston_globe")

    def test_move_to_boston_globe_blocked_before_unlock(self):
        self.scenario.flags.pop("talked_with_knott", None)
        self.scenario.flags["knott_letter_read"] = False
        self.scenario.flags["knott_memo_read"] = False
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "move", "boston_globe", "",
            "introduction", self.char_mgr, self.dice, self.scenario,
        )
        self.assertTrue(result.get("blocked") or "進むことはできません" in result.get("log", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
