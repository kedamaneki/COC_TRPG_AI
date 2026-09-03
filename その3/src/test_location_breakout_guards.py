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
        log = result.get("log", "")
        self.assertTrue(
            ("この場所にいません" in log) or ("ロケーション不整合" in log),
            log,
        )
        self.assertTrue(
            (result.get("payload") or result).get("blocked")
            or ("この場所にいません" in log)
            or ("ロケーション不整合" in log)
        )

    def test_artie_introduced_message_idempotent(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "globe_receptionist", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertNotIn("内線で編集者", result.get("log", ""))
        kp = (result.get("kp_instruction") or "") + str(result.get("payload") or "")
        # 冪等KP: 初対面取り次ぎではなく交渉誘導
        combined = result.get("log", "") + " " + kp
        self.assertTrue(
            ("冪等" in combined)
            or ("呼び出済み" in combined)
            or ("persuade" in combined)
            or ("交渉" in combined),
            combined,
        )

    def test_context_hint_by_location(self):
        intro = build_context_stagnation_hint(self.scenario, "introduction")
        self.assertIn("boston_globe", intro)
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = False
        globe = build_context_stagnation_hint(self.scenario, "boston_globe")
        self.assertIn("persuade", globe)
        self.assertIn("intimidate", globe)
        self.assertIn("central_library", globe)
        self.assertNotIn("オカルト", globe)

    def test_forced_breakout_from_boston_globe(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = True
        forced = build_forced_progress_action(self.scenario, "boston_globe")
        self.assertIsNotNone(forced)
        # 許可済み・資料未調査なら search 優先
        self.assertEqual(forced["action"], "search")
        self.assertEqual(forced["target"], "reference_room_clipping_files")

    def test_forced_breakout_globe_moves_when_files_done(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = True
        self.scenario.flags["accessed_clipping_files"] = True
        forced = build_forced_progress_action(self.scenario, "boston_globe")
        self.assertIsNotNone(forced)
        self.assertEqual(forced["action"], "move")
        self.assertEqual(forced["target"], "central_library")

    def test_forced_breakout_globe_moves_before_access(self):
        """許可未取得時は資料室 search ではなく他ロケーションへ move。"""
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = False
        forced = build_forced_progress_action(self.scenario, "boston_globe")
        self.assertIsNotNone(forced)
        self.assertEqual(forced["action"], "move")
        self.assertIn(forced["target"], ("central_library", "hall_of_records", "introduction"))

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
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_reference_room_access_granted"] = True
        text = game_main._build_kp_situational_directives(
            scenario_mgr=self.scenario,
            last_system_result=None,
            state={"current_loc": "boston_globe"},
        )
        self.assertIn("許可は**既に降りている**", text)
        self.assertIn("門前払い", text)
        self.assertIn("切り抜きファイル", text)
        self.assertIn("reference_room_clipping_files", text)
        self.assertIn("ルース", text)

    def test_reset_guard_after_access_granted_clears_consecutive_count(self):
        state = {
            "autonomous_guard": {
                "consecutive_speaker": "PL:pc_01",
                "consecutive_count": 3,
                "chat_rounds_without_action": 2,
            },
            "stagnation_pl_hint": None,
        }
        game_main._reset_guard_after_access_granted(state)
        guard = state.get("autonomous_guard") or {}
        self.assertEqual(guard.get("consecutive_count"), 0)
        self.assertEqual(guard.get("chat_rounds_without_action"), 0)
        self.assertIn("reference_room_clipping_files", state.get("stagnation_pl_hint") or "")

    def test_defer_speaker_limit_while_clipping_search_pending(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_reference_room_access_granted"] = True
        state = {
            "current_loc": "boston_globe",
            "all_events_log": [],
            "last_pl_action": {
                "action": "search",
                "target": "reference_room_clipping_files",
                "skill": "目星",
            },
            "active_pcs": ["pc_01"],
        }
        self.assertTrue(
            game_main._should_defer_stagnation_interrupt_for_clipping_search(
                state, self.scenario,
            )
        )

    def test_post_access_talk_rejected_with_search_hint(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = True
        check = game_main._validate_post_access_must_search(
            {"action": "talk", "target": "artie_wilmott"},
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check.get("error_code"), "stale_post_access_social")
        self.assertEqual(
            (check.get("suggested_fix") or {}).get("target"),
            "reference_room_clipping_files",
        )
        ok_search = game_main._validate_post_access_must_search(
            {"action": "search", "target": "reference_room_clipping_files"},
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
        )
        self.assertTrue(ok_search.get("ok"))

    def test_globe_done_guidance_prefers_move_not_persuade(self):
        from ActionValidator import build_boston_globe_stale_guidance
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = True
        self.scenario.flags["accessed_clipping_files"] = True
        self.scenario.flags["investigated_targets"] = ["reference_room_clipping_files"]
        guidance = build_boston_globe_stale_guidance(self.scenario, "boston_globe")
        self.assertEqual(guidance.get("error_code"), "globe_investigation_done")
        self.assertIn("central_library", guidance.get("error") or "")
        self.assertNotIn("persuadeせよ", (guidance.get("error") or "").lower())
        suggested = guidance.get("suggested_fix") or {}
        self.assertEqual(suggested.get("action"), "move")
        check = game_main._validate_post_access_must_search(
            {"action": "talk", "target": "artie_wilmott"},
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check.get("error_code"), "globe_investigation_done")

    def test_flag_sync_mirrors_on_export(self):
        from GameStateManager import GameStateManager
        state_mgr = GameStateManager(self.char_mgr)
        self.scenario.bind_game_state(state_mgr)
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["accessed_clipping_files"] = True
        self.scenario.ensure_flags_synced()
        exported = self.scenario.export_to_dict()
        self.assertTrue((exported.get("flags") or {}).get("artie_introduced"))
        self.assertTrue((exported.get("flags") or {}).get("accessed_clipping_files"))
        self.assertEqual(
            exported["flags"].get("accessed_clipping_files"),
            state_mgr.flags.get("accessed_clipping_files"),
        )
        # game_state 優先で再同期
        save_blob = {
            "game_state": {"flags": {"talked_with_knott": True, "investigated_targets": []}, "turn_count": 3},
            "scenario_manager": {"flags": {"artie_introduced": True}, "turn_counter": 1},
        }
        game_main.sync_progress_managers(state_mgr, self.scenario, save_data=save_blob)
        self.assertTrue(state_mgr.flags.get("talked_with_knott"))
        self.assertTrue(self.scenario.flags.get("talked_with_knott"))
        self.assertTrue(self.scenario.flags.get("artie_introduced"))

    def test_progress_action_resets_consecutive_count(self):
        guard = game_main.AutonomousLoopGuard(
            consecutive_speaker="PL:pc_02", consecutive_count=3,
        )
        guard.record_pl_action(
            {"action": "search", "target": "local_history_section"},
            pending_san_check=None,
            scenario_mgr=self.scenario,
            current_loc="central_library",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(guard.consecutive_count, 0)
        self.assertEqual(guard.chat_rounds_without_action, 0)

    def test_clipping_success_exposes_handout_fact(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = True
        fact, _ = self.scenario._object_confirmed_fact("reference_room_clipping_files")
        self.assertIn("1918", fact)
        self.assertIn("マカリオ", fact)
        self.assertNotEqual(fact, self.scenario.get_object_info(
            "boston_globe", "reference_room_clipping_files",
        ).get("description"))

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

    def test_stagnation_force_thresholds_are_relaxed(self):
        from ActionValidator import (
            FORCE_IC_ACTION_CHAT_ROUNDS,
            POST_ACCESS_SEARCH_FORCE_TURNS,
            INVESTIGATION_DEADLOCK_FORCE_TURNS,
            STAGNATION_HINT_TURNS,
            STAGNATION_FORCE_TURNS,
        )
        self.assertGreaterEqual(FORCE_IC_ACTION_CHAT_ROUNDS, 5)
        self.assertGreaterEqual(POST_ACCESS_SEARCH_FORCE_TURNS, 5)
        self.assertGreaterEqual(INVESTIGATION_DEADLOCK_FORCE_TURNS, 5)
        self.assertLessEqual(STAGNATION_HINT_TURNS, 4)
        self.assertGreaterEqual(STAGNATION_FORCE_TURNS, 5)
        self.assertEqual(self.scenario.get_max_stagnation_turns(), 6)

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

    def test_central_library_exhausted_recommends_move(self):
        from ActionValidator import (
            should_apply_location_exhausted_move,
            build_location_exhausted_move_hint,
            LOCATION_EXHAUSTED_RESEARCH_REJECT,
        )
        self.scenario.location = "central_library"
        self.scenario.flags["found_newspaper_article_1918"] = True
        self.scenario.flags["found_corbitt_history_all"] = True
        self.scenario.flags["investigated_targets"] = [
            "newspaper_archives", "local_history_section",
        ]
        self.assertTrue(should_apply_location_exhausted_move(self.scenario, "central_library"))
        rec = game_main._build_pl_recommended_action(self.scenario, "central_library")
        self.assertIn("move", rec)
        self.assertIn("hall_of_records", rec)
        hint = build_location_exhausted_move_hint(self.scenario, "central_library")
        self.assertIn("調査はすべて完了", hint)
        self.assertIn("hall_of_records", hint)
        block = self.scenario.evaluate_pre_roll_block(
            "search", "newspaper_archives", "central_library",
        )
        self.assertIsNotNone(block)
        self.assertIn("他ロケーションへ移動", block.get("system_log", ""))
        forced = build_forced_progress_action(self.scenario, "central_library")
        self.assertEqual(forced["action"], "move")
        self.assertEqual(forced["target"], "hall_of_records")

    def test_location_exhausted_force_move_after_two_non_moves(self):
        from ActionValidator import STAGNATION_HINT_TURNS, LOCATION_EXHAUSTED_FORCE_TURNS
        self.scenario.location = "central_library"
        self.scenario.flags["found_newspaper_article_1918"] = True
        self.scenario.flags["found_corbitt_history_all"] = True
        self.scenario.flags["investigated_targets"] = [
            "newspaper_archives", "local_history_section",
        ]
        state = {
            "current_loc": "central_library",
            "all_events_log": [],
            "stagnation_pl_hint": None,
        }
        managers = (self.char_mgr, self.dice, None, self.scenario)
        # 1ターン目: まだヒントも強制もしない
        out1 = game_main._maybe_force_location_exhausted_move(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
            pending_non_move=True,
        )
        self.assertIsNone(out1)
        self.assertIsNone(state.get("stagnation_pl_hint"))

        for i in range(STAGNATION_HINT_TURNS - 1):
            state["all_events_log"].append({
                "channel": "IC",
                "location": "central_library",
                "text": f"マクガフィン刑事(PC): もう一度漁る{i}",
                "meta": {
                    "pc_id": "pc_01",
                    "action_id": "search",
                    "target": "newspaper_archives",
                },
            })
        out_hint = game_main._maybe_force_location_exhausted_move(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
            pending_non_move=True,
        )
        self.assertIsNone(out_hint)
        self.assertIn("調査はすべて完了", state.get("stagnation_pl_hint") or "")

        while len([
            e for e in state["all_events_log"]
            if (e.get("meta") or {}).get("pc_id")
        ]) < LOCATION_EXHAUSTED_FORCE_TURNS - 1:
            n = len(state["all_events_log"])
            state["all_events_log"].append({
                "channel": "IC",
                "location": "central_library",
                "text": f"マクガフィン刑事(PC): さらに漁る{n}",
                "meta": {
                    "pc_id": "pc_01",
                    "action_id": "search",
                    "target": "newspaper_archives",
                },
            })
        out2 = game_main._maybe_force_location_exhausted_move(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
            pending_non_move=True,
        )
        self.assertIsNotNone(out2)
        self.assertEqual(state.get("current_loc"), "hall_of_records")

    def test_globe_negotiate_grace_keeps_alternate_skill_hint(self):
        from ActionValidator import ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT
        self.assertIn("intimidate", ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT)
        self.assertIn("fast_talk", ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT)
        self.assertIn("再挑戦", ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT)
        self.assertIn("corbitt_exterior", ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT)

    def test_intro_complete_unlocks_house_from_globe(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        dest_ids = {e["id"] for e in self.scenario.get_available_exits("boston_globe")}
        self.assertIn("corbitt_exterior", dest_ids)

    def test_move_corbitt_house_alias_from_globe(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "move", "corbitt_house", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertFalse(result.get("blocked"), result.get("log"))
        self.assertEqual(result.get("new_location") or self.scenario.location, "corbitt_exterior")

    def test_investigation_deadlock_hint_and_force(self):
        from ActionValidator import (
            STAGNATION_HINT_TURNS,
            INVESTIGATION_DEADLOCK_FORCE_TURNS,
            count_investigation_deadlock_streak,
        )
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["artie_introduced"] = True

        def _deadlock_log(n_pc_actions):
            log = [
                {
                    "location": "boston_globe",
                    "text": "システム: 【交渉】失敗 / 【技能:説得】",
                    "meta": {"action_id": "persuade", "target": "artie_wilmott"},
                },
            ]
            for i in range(n_pc_actions):
                log.append({
                    "location": "boston_globe",
                    "text": f"マクガフィン刑事(PC): もう一度頼む{i}",
                    "meta": {"pc_id": "pc_01", "action_id": "persuade", "target": "artie_wilmott"},
                })
            return log

        early_log = _deadlock_log(1)
        self.assertEqual(count_investigation_deadlock_streak(early_log, "boston_globe"), 1)
        state = {
            "current_loc": "boston_globe",
            "all_events_log": early_log,
            "stagnation_pl_hint": None,
        }
        managers = (self.char_mgr, self.dice, None, self.scenario)
        too_early = game_main._maybe_force_investigation_deadlock_move(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
            pending_non_move=False,
        )
        self.assertIsNone(too_early)
        self.assertIsNone(state.get("stagnation_pl_hint"))

        hint_log = _deadlock_log(STAGNATION_HINT_TURNS)
        state = {
            "current_loc": "boston_globe",
            "all_events_log": hint_log,
            "stagnation_pl_hint": None,
        }
        hint_only = game_main._maybe_force_investigation_deadlock_move(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
            pending_non_move=False,
        )
        self.assertIsNone(hint_only)
        self.assertIn("コービット屋敷", state.get("stagnation_pl_hint") or "")
        self.assertTrue(
            any((e.get("meta") or {}).get("stagnation_hint") for e in state["all_events_log"])
        )

        force_log = _deadlock_log(INVESTIGATION_DEADLOCK_FORCE_TURNS)
        state = {
            "current_loc": "boston_globe",
            "all_events_log": force_log,
            "stagnation_pl_hint": None,
        }
        forced = game_main._maybe_force_investigation_deadlock_move(
            state, managers, pl_id="pc_01", char_name="マクガフィン刑事",
            pending_non_move=False,
        )
        self.assertIsNotNone(forced)
        self.assertEqual(state.get("current_loc"), "central_library")

    def test_knott_letter_success_exposes_handout_in_kp_ic(self):
        self.scenario.location = "introduction"
        payload = self.scenario.process_action("inspect", "knott_letter", success_level=2)
        desc = self.scenario.get_object_info("introduction", "knott_letter")["description"]
        self.assertTrue(self.scenario.flags.get("knott_letter_read"))
        self.assertIn("相続", payload.get("confirmed_fact") or "")
        self.assertIn("【確定手がかり】", payload.get("system_log") or "")
        self.assertIn("資料本文", payload.get("handout_ic_block") or "")
        kp_data = {
            "should_speak": True,
            "speak_mode": "system_narration",
            "text": "依頼書に目を通したようだ。どうしますか？",
        }
        injected = game_main._inject_handout_into_kp_data(
            kp_data,
            self.scenario,
            action={"action": "inspect", "target": "knott_letter"},
            result={
                "confirmed_fact": payload.get("confirmed_fact"),
                "handout_text": payload.get("handout_text"),
                "handout_ic_block": payload.get("handout_ic_block"),
                "target": "knott_letter",
            },
            current_loc="introduction",
        )
        logs = []
        game_main.append_kp_response_to_logs(injected, "introduction", logs)
        ic = logs[0]["text"]
        self.assertIn("資料本文", ic)
        self.assertIn(desc[:18], ic)

    def test_knott_memo_success_exposes_handout_text(self):
        self.scenario.location = "introduction"
        payload = self.scenario.process_action("search", "knott_memo", success_level=2)
        self.assertTrue(self.scenario.flags.get("knott_memo_read"))
        self.assertIn("ボストン・グローブ", payload.get("confirmed_fact") or "")
        self.assertIn("ボストン・グローブ", payload.get("system_log") or "")

    def test_pl_prompt_contains_bailout_algorithm(self):
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        loc = self.scenario.get_location_info("boston_globe")
        prompt = game_main.generate_pl_prompt(
            "マクガフィン刑事", [], [], loc,
            available_exits=self.scenario.get_available_exits("boston_globe"),
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
        )
        self.assertIn("すべての資料を集める必要はない", prompt)
        self.assertIn("corbitt_exterior", prompt)
        self.assertIn("行き詰まり時の行動選択アルゴリズム", prompt)

    def test_pl_prompt_contains_explorer_mindset(self):
        self.scenario.location = "boston_globe"
        loc = self.scenario.get_location_info("boston_globe")
        prompt = game_main.generate_pl_prompt(
            "マクガフィン刑事", [], [], loc,
            available_exits=self.scenario.get_available_exits("boston_globe"),
            scenario_mgr=self.scenario,
            current_loc="boston_globe",
        )
        self.assertIn("探索者の心得とプレイ姿勢", prompt)
        self.assertIn("事件の真相を解明し、原因を排除すること", prompt)
        self.assertIn("不完全な状態での挑戦を恐れない", prompt)
        self.assertIn(game_main.PL_EXPLORER_MINDSET_DIRECTIVE, prompt)

    def test_implied_progress_flags_house_entry_implies_exterior(self):
        self.scenario.flags["corbitt_house_entered"] = True
        self.scenario.flags["exterior_approached"] = False
        self.scenario.apply_implied_progress_flags()
        self.assertTrue(self.scenario.flags.get("exterior_approached"))

    def test_implied_progress_flags_dolly_talk_implies_neighbor_gossip(self):
        self.scenario.flags["dolly_told_chapel_location"] = True
        self.scenario.flags["dolly_told_sanitarium_location"] = True
        self.scenario.flags["neighbor_gossip_found"] = False
        self.scenario.flags["sanitarium_info_found"] = False
        self.scenario.apply_implied_progress_flags()
        self.assertTrue(self.scenario.flags.get("neighbor_gossip_found"))
        # 患者記録の investigated_flag はドーリー会話だけでは立てない
        self.assertFalse(self.scenario.flags.get("sanitarium_info_found"))

    def test_pl_prompt_ground_floor_focuses_living_room_and_basement_door(self):
        self.scenario.location = "corbitt_ground_floor"
        self.scenario.flags["corbitt_house_entered"] = True
        loc = self.scenario.get_location_info("corbitt_ground_floor")
        prompt = game_main.generate_pl_prompt(
            "マクガフィン刑事", [], [], loc,
            available_exits=self.scenario.get_available_exits("corbitt_ground_floor"),
            scenario_mgr=self.scenario,
            current_loc="corbitt_ground_floor",
        )
        self.assertIn("living_room_clutter", prompt)
        self.assertIn("living_room_junk", prompt)
        self.assertIn("basement_door", prompt)
        rec = game_main._build_pl_recommended_action(self.scenario, "corbitt_ground_floor")
        self.assertIn("living_room_clutter", rec)

    def test_autonomous_step_budget_resets_on_progress(self):
        self.assertGreaterEqual(game_main.MAX_AUTONOMOUS_ITERATIONS, 100)
        self.scenario.location = "boston_globe"
        self.scenario.flags["talked_with_knott"] = True
        state = {
            "current_loc": "boston_globe",
            "autonomous_step_count": 40,
            "autonomous_progress_fp": None,
        }
        # 初回は指紋を記録するだけ（リセットしない）
        self.assertFalse(
            game_main.refresh_autonomous_step_budget_on_progress(state, self.scenario)
        )
        self.assertEqual(state["autonomous_step_count"], 40)
        self.assertIsNotNone(state["autonomous_progress_fp"])

        # 無進行ならカウント維持
        self.assertFalse(
            game_main.refresh_autonomous_step_budget_on_progress(state, self.scenario)
        )
        self.assertEqual(state["autonomous_step_count"], 40)

        # 場所が進んだらカウントをリセット
        self.scenario.location = "central_library"
        state["current_loc"] = "central_library"
        self.assertTrue(
            game_main.refresh_autonomous_step_budget_on_progress(state, self.scenario)
        )
        self.assertEqual(state["autonomous_step_count"], 0)

        state["autonomous_step_count"] = 55
        self.scenario.flags["library_info_found"] = True
        self.assertTrue(
            game_main.refresh_autonomous_step_budget_on_progress(state, self.scenario)
        )
        self.assertEqual(state["autonomous_step_count"], 0)

    def test_inject_stagnation_interrupt_does_not_inflate_counter(self):
        from GameStateManager import GameStateManager
        state_mgr = GameStateManager(self.char_mgr)
        self.scenario.stagnation_counter = 2
        state_mgr.stagnation_tracker["streak"] = 2
        state = {"all_events_log": [], "current_loc": "boston_globe"}
        game_main.inject_stagnation_interrupt(
            state, self.scenario, "マクガフィン刑事", state_mgr=state_mgr,
        )
        self.assertEqual(self.scenario.stagnation_counter, 2)
        self.assertEqual(state_mgr.stagnation_tracker.get("streak"), 2)
        self.assertTrue(any((e.get("meta") or {}).get("stagnation_interrupt") for e in state["all_events_log"]))

    def test_same_speaker_limit_aligns_with_stagnation_window(self):
        self.assertGreaterEqual(game_main.MAX_CONSECUTIVE_SAME_SPEAKER, 5)
        guard = game_main.AutonomousLoopGuard(consecutive_speaker="PL:pc_01", consecutive_count=3)
        self.assertFalse(guard.should_break_same_speaker())
        guard.consecutive_count = game_main.MAX_CONSECUTIVE_SAME_SPEAKER + 1
        self.assertTrue(guard.should_break_same_speaker())

    def test_same_speaker_soft_yield_does_not_pause_or_inflate_counter(self):
        self.scenario.stagnation_counter = 2
        state = {
            "all_events_log": [],
            "current_loc": "boston_globe",
            "active_pcs": ["pc_01"],
            "active_pc_id": "pc_01",
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
        }
        guard = game_main.AutonomousLoopGuard(consecutive_speaker="PL:pc_01", consecutive_count=6)
        managers = (self.char_mgr, self.dice, None, self.scenario)
        game_main._handle_same_speaker_soft_yield(state, managers, guard)
        self.assertEqual(self.scenario.stagnation_counter, 2)
        self.assertEqual(guard.consecutive_count, 0)
        self.assertFalse(any((e.get("meta") or {}).get("stagnation_interrupt") for e in state["all_events_log"]))

    def test_recover_truncated_kp_json_text(self):
        raw = '{"thought": "描写する", "should_speak": true, "speak_mode": "system_narration", "text": "依頼書には屋敷の住所が'
        recovered = game_main._recover_text_field_from_partial_json(raw)
        self.assertIn("依頼書", recovered)
        repaired = game_main._loads_json_lenient(raw)
        self.assertIsInstance(repaired, dict)
        self.assertIn("依頼書", repaired.get("text") or recovered)
        fallback = game_main.default_kp_response(fallback_text="ノット氏からの依頼書を読んだ。")
        self.assertIn("依頼書", fallback["text"])
        self.assertNotIn("思考が途切れ", fallback["text"])

    def test_reconcile_inflated_stagnation_counter_on_load(self):
        from GameStateManager import GameStateManager
        state_mgr = GameStateManager(self.char_mgr)
        state_mgr.stagnation_tracker["streak"] = 2
        state_mgr.stagnation_tracker["intervened_at_streak"] = 6
        self.scenario.stagnation_counter = 6
        game_main._reconcile_loaded_stagnation_counters(state_mgr, self.scenario)
        self.assertEqual(self.scenario.stagnation_counter, 2)
        self.assertEqual(state_mgr.stagnation_tracker.get("intervened_at_streak"), 2)


if __name__ == "__main__":
    unittest.main()
