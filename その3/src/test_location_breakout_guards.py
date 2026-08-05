"""
ロケーション移動時の幽霊NPC破棄・Knott即時拒絶・場面依存ヒント・受付冪等。
実行: python test_location_breakout_guards.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ActionValidator import (
    STALE_KNOTT_TALK_REJECT_ERROR,
    validate_completed_knott_talk,
    validate_force_ic_action,
    build_forced_progress_action,
    build_context_stagnation_hint,
    is_stale_nonprogress_talk,
)
from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from DiceEngine import SuccessLevel
from NPCSocialManager import NPCSocialManager
from ScenarioManager import ScenarioManager
import main as game_main


CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"
NPCS = Path(__file__).resolve().parent / "npcs.json"


class TestLocationBreakoutGuards(unittest.TestCase):
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
        self.npc_path.write_text(NPCS.read_text(encoding="utf-8"), encoding="utf-8")
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
                "skills": {"目星": 65, "説得": 50, "法律": 50},
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.scenario = ScenarioManager(json.loads(json.dumps(self.scenario_data)))
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_completed_knott_talk_rejected_immediately(self):
        self.scenario.flags["talked_with_knott"] = True
        check = validate_completed_knott_talk(
            {"action": "talk", "target": "steven_knott"},
            scenario_mgr=self.scenario,
            current_loc="introduction",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check.get("error"), STALE_KNOTT_TALK_REJECT_ERROR)
        self.assertTrue(check.get("needs_pl_retry"))

    def test_ghost_knott_talk_detected_at_boston_globe(self):
        self.scenario.flags["talked_with_knott"] = True
        self.assertTrue(
            is_stale_nonprogress_talk(
                "talk", "steven_knott",
                scenario_mgr=self.scenario,
                current_loc="boston_globe",
                char_mgr=self.char_mgr,
            )
        )

    def test_invalidate_pending_after_move(self):
        self.scenario.location = "introduction"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        state = {
            "current_loc": "introduction",
            "all_events_log": [
                {
                    "channel": "IC",
                    "location": "introduction",
                    "text": "マクガフィン刑事(PC): もう少し聞きます",
                    "meta": {
                        "pc_id": "pc_01",
                        "action_id": "talk",
                        "target": "steven_knott",
                        "needs_system": True,
                        "system_processed": False,
                    },
                },
            ],
            "last_pl_action": {"action": "talk", "target": "steven_knott"},
        }
        # 移動実行
        payload = self.scenario.process_action("move", "boston_globe", success_level=1)
        self.assertTrue(payload.get("invalidate_pending_actions"))
        cleared = game_main.invalidate_pending_actions_after_location_change(
            state,
            old_loc="introduction",
            new_loc="boston_globe",
            scenario_mgr=self.scenario,
            char_mgr=self.char_mgr,
        )
        self.assertGreaterEqual(cleared, 1)
        meta = state["all_events_log"][0]["meta"]
        self.assertTrue(meta.get("system_processed"))
        self.assertTrue(meta.get("invalidated_by_move"))
        self.assertIsNone(state.get("last_pl_action"))

    def test_ghost_npc_blocked_in_process_system_action(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "steven_knott", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertIn("ロケーション不整合", result.get("log", ""))
        self.assertTrue((result.get("payload") or result).get("blocked") or "ロケーション不整合" in result.get("log", ""))

    def test_artie_introduced_message_idempotent(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "globe_receptionist", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertNotIn("内線で編集者", result.get("log", ""))

    def test_context_hint_by_location(self):
        intro = build_context_stagnation_hint(self.scenario, "introduction")
        self.assertIn("boston_globe", intro)
        globe = build_context_stagnation_hint(self.scenario, "boston_globe")
        self.assertIn("言いくるめ", globe)
        self.assertIn("central_library", globe)
        self.assertNotIn("オカルト", globe)

    def test_forced_breakout_from_boston_globe(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["artie_introduced"] = True
        forced = build_forced_progress_action(self.scenario, "boston_globe")
        self.assertIsNotNone(forced)
        # 紹介済み・資料未調査なら search 優先
        self.assertEqual(forced["action"], "search")
        self.assertEqual(forced["target"], "reference_room_clipping_files")

    def test_forced_breakout_globe_moves_when_files_done(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["accessed_clipping_files"] = True
        forced = build_forced_progress_action(self.scenario, "boston_globe")
        self.assertIsNotNone(forced)
        self.assertEqual(forced["action"], "move")
        self.assertEqual(forced["target"], "central_library")

    def test_forced_breakout_globe_moves_before_artie(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = False
        forced = build_forced_progress_action(self.scenario, "boston_globe")
        self.assertIsNotNone(forced)
        self.assertEqual(forced["action"], "move")
        self.assertIn(forced["target"], ("central_library", "hall_of_records", "introduction"))

    def test_move_lifecycle_invalidates_via_process_system_action(self):
        """move 実行時、process_system_action(game_state=) 経由でキューが破棄される。"""
        self.scenario.location = "introduction"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        state = {
            "current_loc": "introduction",
            "all_events_log": [
                {
                    "channel": "IC",
                    "location": "introduction",
                    "text": "マクガフィン刑事(PC): もう少し聞きます",
                    "meta": {
                        "pc_id": "pc_01",
                        "action_id": "talk",
                        "target": "steven_knott",
                        "needs_system": True,
                        "system_processed": False,
                    },
                },
            ],
            "last_pl_action": {"action": "talk", "target": "steven_knott"},
        }
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "move", "boston_globe", "",
            "introduction", self.char_mgr, self.dice, self.scenario,
            game_state=state,
        )
        self.assertTrue(result.get("location_changed") or result.get("new_location"))
        self.assertEqual(state["current_loc"], "boston_globe")
        meta = state["all_events_log"][0]["meta"]
        self.assertTrue(meta.get("system_processed"))
        self.assertTrue(meta.get("invalidated_by_move"))
        self.assertIsNone(state.get("last_pl_action"))

    def test_force_ic_wait_rejected_at_globe(self):
        check = validate_force_ic_action(
            {"action": "wait", "target": ""},
            force_ic_action=True,
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
        )
        self.assertFalse(check["ok"])
        suggested = check.get("suggested_fix") or {}
        self.assertIn(suggested.get("action"), ("move", "search"))

    def test_social_success_softens_attitude_more(self):
        social_mgr = NPCSocialManager(self.char_mgr)
        delta_regular = social_mgr.compute_relationship_delta("説得", int(SuccessLevel.REGULAR_SUCCESS))
        delta_hard = social_mgr.compute_relationship_delta("信用", int(SuccessLevel.HARD_SUCCESS))
        self.assertEqual(delta_regular, 1)
        self.assertGreaterEqual(delta_hard, 2)

    def test_stale_knott_talk_auto_corrected_to_move(self):
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        logs = []
        pc_action = game_main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pl_ooc_chat": "",
                "pc_action": {
                    "action": "talk",
                    "target": "steven_knott",
                    "skill": "",
                    "dialogue": "もう一度ノット氏に確認します",
                },
            },
            "マクガフィン刑事",
            "introduction",
            logs,
            scenario_mgr=self.scenario,
            pc_id="pc_01",
            char_mgr=self.char_mgr,
            force_ic_action=False,
        )
        self.assertFalse(pc_action.get("needs_pl_retry"))
        self.assertEqual(pc_action.get("action"), "move")
        self.assertEqual(pc_action.get("target"), "boston_globe")
        self.assertTrue(any("アクション自動補正" in e.get("text", "") for e in logs))

    def test_duplicate_validation_error_log_suppressed(self):
        logs = []
        for _ in range(3):
            out = game_main.apply_pl_response_to_logs(
                {
                    "speak_as": "PC",
                    "should_speak": True,
                    "pl_ooc_chat": "",
                    "pc_action": {
                        "action": "move",
                        "target": "hall_of_records",
                        "dialogue": "参考資料室へ行く",
                        "skill": "",
                    },
                },
                "マクガフィン刑事",
                "boston_globe",
                logs,
                scenario_mgr=self.scenario,
                pc_id="pc_01",
                char_mgr=self.char_mgr,
                force_ic_action=False,
            )
            self.assertTrue(out.get("needs_pl_retry"))
        err_logs = [e for e in logs if (e.get("meta") or {}).get("validation_error")]
        self.assertEqual(len(err_logs), 1)

    def test_normalize_loaded_runtime_state_marks_half_turn_paused(self):
        state = {
            "all_events_log": [],
            "is_running": True,
            "stop_requested": False,
            "autonomous_paused": False,
            "autonomous_pause_reason": None,
            "last_pl_action": {"action": "move", "target": "boston_globe"},
            "last_system_result": None,
        }
        out = game_main.normalize_loaded_runtime_state(state)
        self.assertFalse(out.get("is_running"))
        self.assertTrue(out.get("autonomous_paused"))
        self.assertEqual(out.get("autonomous_pause_reason"), "awaiting_system_process")

    def test_validate_and_sync_pause_state_resolves_hanging_pause(self):
        app_state = {
            "all_events_log": [],
            "autonomous_paused": True,
            "autonomous_pause_reason": "awaiting_system_process",
            "last_pl_action": {
                "action": "wait",
                "target": "stale_target",
                "message": "古い文言",
            },
        }
        out = game_main.validate_and_sync_pause_state(dict(app_state))
        self.assertIsNone(out.get("autonomous_pause_reason"))
        self.assertFalse(out.get("autonomous_paused"))

        non_wait_state = {
            "all_events_log": [],
            "autonomous_paused": True,
            "autonomous_pause_reason": "awaiting_system_process",
            "last_pl_action": {"action": "talk", "target": "artie_wilmott"},
        }
        non_wait_state["all_events_log"] = [
            {
                "channel": "IC",
                "location": "boston_globe",
                "text": "マクガフィン刑事(PC1): 受付に確認します",
                "meta": {
                    "pc_id": "pc_01",
                    "action_id": "talk",
                    "target": "globe_receptionist",
                    "needs_system": True,
                    "system_processed": True,
                },
            },
        ]
        out2 = game_main.validate_and_sync_pause_state(dict(non_wait_state))
        self.assertIsNone(out2.get("autonomous_pause_reason"))
        self.assertFalse(out2.get("autonomous_paused"))

    def test_build_kp_situational_directives_injects_absolute_rule(self):
        self.scenario.flags["artie_reference_room_access_granted"] = True
        text = game_main._build_kp_situational_directives(
            scenario_mgr=self.scenario,
            last_system_result=None,
            state={"current_loc": "boston_globe"},
        )
        self.assertIn(
            "- 【絶対遵守】NPCアーティは既に参考資料室への立ち入りを許可済み。",
            text,
        )

    def test_reset_stagnation_state_on_progress_clears_all_counters(self):
        app_state = {
            "stagnation_pl_hint": "古いヒント",
            "stagnation_kp_nudge": "古いナッジ",
            "force_ic_action": True,
            "stagnation_streak": 4,
            "autonomous_guard": {
                "consecutive_speaker": "PL:pc_01",
                "consecutive_count": 3,
                "chat_rounds_without_action": 2,
            },
        }
        game_main.reset_stagnation_state_on_progress(app_state)
        self.assertIsNone(app_state.get("stagnation_pl_hint"))
        self.assertIsNone(app_state.get("stagnation_kp_nudge"))
        self.assertFalse(app_state.get("force_ic_action"))
        self.assertEqual(app_state.get("stagnation_streak"), 0)
        self.assertEqual(
            (app_state.get("autonomous_guard") or {}).get("chat_rounds_without_action"),
            0,
        )

    def test_normalize_pc_action_clears_residual_fields_on_wait(self):
        action = {
            "action": "wait",
            "target": "artie_wilmott",
            "skill": "説得",
            "message": "以前の長文メッセージ",
            "dialogue": "以前の台詞",
        }
        out = game_main.normalize_pc_action(action)
        self.assertEqual(out.get("action"), "wait")
        self.assertIsNone(out.get("target"))
        self.assertIsNone(out.get("message"))
        self.assertIsNone(out.get("dialogue"))


if __name__ == "__main__":
    unittest.main()
