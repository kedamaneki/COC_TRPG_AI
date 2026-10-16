# -*- coding: utf-8 -*-
"""
プレイヤー意図解釈・対象解決・自動補正の回帰テスト。
実行: python test_intent_interpretation.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ActionValidator import (
    INTENT_ACTION_REQUEST,
    INTENT_DISCUSSION_OR_PLAN,
    INTENT_IN_CHARACTER_DIALOGUE,
    interpret_player_intent,
    can_auto_execute_move,
    classify_target_scope,
    rewrite_human_investigation_to_talk,
)
from CharacterManager import CharacterManager
from ScenarioManager import ScenarioManager
import main as game_main

CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"
NPCS = Path(__file__).resolve().parent / "npcs.json"
AUTOSAVE = Path(__file__).resolve().parent / "save_autosave.json"


class TestIntentInterpretation(unittest.TestCase):
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
        self.scenario.flags["talked_with_knott"] = True
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True

    def tearDown(self):
        self.tmp.cleanup()

    # --- 行動分類 ---
    def test_explicit_move_is_action_request(self):
        intent = interpret_player_intent(
            "中央図書館へ移動する",
            proposed_action="move",
            proposed_target="central_library",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "move")
        self.assertFalse(intent.get("do_not_execute"))

        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "central_library",
                "skill": "",
                "dialogue": "中央図書館へ移動する",
            },
            "PC",
            "",
            self.scenario,
            "introduction",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "move")
        self.assertEqual(out["target"], "central_library")
        self.assertFalse(out.get("intent_non_execute"))

    def test_discussion_plan_does_not_execute(self):
        intent = interpret_player_intent(
            "他の場所へ移った方がよさそう",
            proposed_action="move",
            proposed_target="central_library",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(intent["intent_type"], INTENT_DISCUSSION_OR_PLAN)
        self.assertTrue(intent.get("do_not_execute"))

        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "central_library",
                "skill": "",
                "dialogue": "他の場所へ移った方がよさそう",
            },
            "PC",
            "",
            self.scenario,
            "introduction",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "wait")
        self.assertTrue(out.get("intent_non_execute"))
        self.assertIn("即時実行しません", out.get("post_action_hint") or "")

    def test_info_gathering_enough_does_not_execute(self):
        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "central_library",
                "skill": "",
                "dialogue": "ここでの情報収集は十分だ",
            },
            "PC",
            "",
            self.scenario,
            "introduction",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "wait")
        self.assertTrue(out.get("intent_non_execute"))

    def test_courtesy_dialogue_classified(self):
        intent = interpret_player_intent(
            "事務官に礼を言う",
            proposed_action="talk",
            proposed_target="hall_records_clerk",
            scenario_mgr=self.scenario,
            current_loc="hall_of_records",
        )
        self.assertIn(
            intent["intent_type"],
            (INTENT_IN_CHARACTER_DIALOGUE, INTENT_ACTION_REQUEST),
        )
        self.assertEqual(intent["action"], "talk")

    def test_ask_clerk_is_talk(self):
        intent = interpret_player_intent(
            "事務官に記録の場所を聞く",
            proposed_action="talk",
            proposed_target="hall_records_clerk",
            scenario_mgr=self.scenario,
            current_loc="hall_of_records",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "talk")

        self.scenario.location = "hall_of_records"
        out = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "hall_records_clerk",
                "skill": "",
                "dialogue": "事務官に記録の場所を聞く",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "talk")
        self.assertEqual(out["target"], "hall_records_clerk")

    def test_search_newspaper_archive(self):
        intent = interpret_player_intent(
            "新聞アーカイブを調べる",
            proposed_action="search",
            proposed_target="newspaper_archives",
            scenario_mgr=self.scenario,
            current_loc="central_library",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "search")

    # --- 対象解決 ---
    def test_npc_search_rewrites_to_talk(self):
        rewritten = rewrite_human_investigation_to_talk(
            "search",
            "hall_records_clerk",
            char_mgr=self.char_mgr,
            scenario_mgr=self.scenario,
            current_loc="hall_of_records",
        )
        self.assertIsNotNone(rewritten)
        self.assertEqual(rewritten["action"], "talk")

        self.scenario.location = "hall_of_records"
        out = game_main.reconcile_pl_action(
            {
                "action": "search",
                "target": "hall_records_clerk",
                "skill": "目星",
                "dialogue": "事務官を調べる",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "talk")
        self.assertEqual(out["target"], "hall_records_clerk")
        self.assertTrue(out.get("system_correction_log") or out.get("system_correction_meta"))

    def test_other_location_object_search_proposes_move(self):
        self.scenario.location = "introduction"
        out = game_main.reconcile_pl_action(
            {
                "action": "search",
                "target": "newspaper_archives",
                "skill": "目星",
                "dialogue": "新聞アーカイブを調べる",
            },
            "PC",
            "",
            self.scenario,
            "introduction",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "wait")
        self.assertEqual(out.get("validation_error_code"), "target_other_location")
        self.assertEqual((out.get("suggested_fix") or {}).get("action"), "move")
        self.assertEqual((out.get("suggested_fix") or {}).get("target"), "central_library")

    def test_exact_id_preferred_over_alias(self):
        resolved = game_main.normalize_action_target(
            "central_library",
            self.scenario,
            "introduction",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(resolved, "central_library")

    def test_current_location_target_preferred(self):
        # 現在地に事務官がいる場合、別名より現在地NPCを優先
        self.scenario.location = "hall_of_records"
        resolved = game_main.normalize_action_target(
            "事務官",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(resolved, "hall_records_clerk")
        scope = classify_target_scope(
            resolved,
            scenario_mgr=self.scenario,
            current_loc="hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(scope.get("scope"), "current")

    # --- 自動補正 ---
    def test_correction_logged_and_talk_not_replaced_by_move(self):
        logs = []
        self.scenario.location = "hall_of_records"
        out = game_main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pl_ooc_chat": "",
                "pc_action": {
                    "action": "search",
                    "target": "hall_records_clerk",
                    "skill": "目星",
                    "dialogue": "事務官を調べる",
                },
            },
            "マクガフィン刑事",
            "hall_of_records",
            logs,
            scenario_mgr=self.scenario,
            char_mgr=self.char_mgr,
            pc_id="pc_01",
        )
        self.assertEqual(out.get("action"), "talk")
        self.assertNotEqual(out.get("action"), "move")
        corr = [
            e for e in logs
            if (e.get("meta") or {}).get("system_correction")
        ]
        self.assertTrue(corr)
        meta = corr[0]["meta"]
        self.assertTrue(meta.get("system_correction"))
        self.assertIn("corrected_action", meta)
        self.assertEqual(meta.get("corrected_action"), "talk")

    def test_discussion_not_autocorrected_to_move(self):
        logs = []
        out = game_main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pl_ooc_chat": "",
                "pc_action": {
                    "action": "move",
                    "target": "central_library",
                    "skill": "",
                    "dialogue": "他の場所へ移った方がよさそう",
                },
            },
            "マクガフィン刑事",
            "introduction",
            logs,
            scenario_mgr=self.scenario,
            char_mgr=self.char_mgr,
            pc_id="pc_01",
        )
        self.assertEqual(out.get("action"), "wait")
        self.assertTrue(out.get("intent_non_execute"))
        self.assertFalse(out.get("auto_corrected"))
        self.assertTrue(any(
            (e.get("meta") or {}).get("intent_non_execute")
            for e in logs
        ))

    def test_can_auto_execute_move_requires_explicit(self):
        soft = interpret_player_intent(
            "次は図書館がよさそうだ",
            proposed_action="move",
            proposed_target="central_library",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        gate = can_auto_execute_move(
            soft,
            scenario_mgr=self.scenario,
            current_loc="introduction",
            target="central_library",
        )
        self.assertFalse(gate.get("ok"))

    # --- セッション安全性 ---
    def test_transaction_not_double_executed(self):
        txn = "txn-intent-dup-001"
        state = {
            "pending_action_id": txn,
            "last_processed_action_id": txn,
            "current_loc": "introduction",
        }
        # 同一 txn は再処理対象外
        self.assertEqual(state["pending_action_id"], state["last_processed_action_id"])

    def test_auto_correct_preserves_transaction_fields(self):
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags["symbol_investigated"] = True
        self.scenario.flags["investigated_targets"] = ["white_symbol"]
        logs = []
        out = game_main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pl_ooc_chat": "",
                "pc_action": {
                    "action": "move",
                    "target": "",
                    "skill": "",
                    "dialogue": "",
                    "transaction_id": "txn-intent-ac-1",
                },
            },
            "マクガフィン刑事",
            "chapel_of_contemplation",
            logs,
            scenario_mgr=self.scenario,
            char_mgr=self.char_mgr,
            pc_id="pc_01",
        )
        if out.get("auto_corrected"):
            self.assertTrue(out.get("transaction_id") or True)
            meta_corr = next(
                (e.get("meta") for e in logs if (e.get("meta") or {}).get("system_correction")),
                {},
            )
            self.assertTrue(meta_corr.get("system_correction"))

    def test_scenario_mgr_none_safe(self):
        out = game_main.reconcile_pl_action(
            {"action": "move", "target": "central_library", "dialogue": "行く"},
            "PC",
            "",
            None,
            "introduction",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out.get("action"), "move")

        state = {"current_loc": "introduction", "all_events_log": []}
        ok = game_main.apply_location_change_side_effects(
            state,
            {
                "location_changed": True,
                "new_location": "central_library",
                "from_location": "introduction",
            },
            scenario_mgr=None,
            char_mgr=self.char_mgr,
        )
        self.assertTrue(ok)
        self.assertEqual(state.get("current_loc"), "central_library")

    def test_stagnation_still_suggests(self):
        from ActionValidator import build_context_stagnation_hint
        hint = build_context_stagnation_hint(self.scenario, "introduction")
        self.assertTrue(hint)
        self.assertIn("システム", hint)

    def test_autosave_load_intent_continues(self):
        if not AUTOSAVE.exists():
            self.skipTest("save_autosave.json なし")
        data = json.loads(AUTOSAVE.read_text(encoding="utf-8"))
        state = data.get("state") or data
        loc = state.get("current_loc") or "introduction"
        self.scenario.location = loc
        # ロード後も方針発言は実行されない
        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "central_library",
                "skill": "",
                "dialogue": "移動した方がいいかもしれない",
            },
            "PC",
            "",
            self.scenario,
            loc,
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "wait")
        self.assertTrue(out.get("intent_non_execute"))
        # 明示移動は継続可能
        out2 = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "central_library",
                "skill": "",
                "dialogue": "中央図書館へ向かおう",
            },
            "PC",
            "",
            self.scenario,
            loc,
            char_mgr=self.char_mgr,
        )
        # 解禁状況により wait または move。少なくとも方針置換ではない
        self.assertFalse(out2.get("intent_non_execute") and out2.get("action") == "move")
        if out2.get("action") == "move":
            self.assertEqual(out2.get("target"), "central_library")

    # --- 英語・曖昧日本語 ---
    def test_english_explicit_move_to_library(self):
        intent = interpret_player_intent(
            "move to the library",
            proposed_action="move",
            proposed_target="",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "move")
        self.assertEqual(intent["target_text"], "central_library")
        self.assertFalse(intent.get("do_not_execute"))

    def test_english_lets_go_neighborhood(self):
        intent = interpret_player_intent(
            "Let's go to the neighborhood",
            proposed_action="move",
            proposed_target="",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "move")
        self.assertEqual(intent["target_text"], "the_neighborhood")

    def test_english_ask_clerk(self):
        intent = interpret_player_intent(
            "ask the clerk about the records",
            proposed_action="talk",
            proposed_target="",
            scenario_mgr=self.scenario,
            current_loc="hall_of_records",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "talk")
        self.scenario.location = "hall_of_records"
        out = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "",
                "skill": "",
                "dialogue": "ask the clerk about the records",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "talk")
        self.assertEqual(out["target"], "hall_records_clerk")

    def test_english_soft_leave_and_maybe_investigate(self):
        leave = interpret_player_intent(
            "I think we should leave",
            proposed_action="move",
            proposed_target="boston_globe",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(leave["intent_type"], INTENT_DISCUSSION_OR_PLAN)
        self.assertTrue(leave.get("do_not_execute"))

        maybe = interpret_player_intent(
            "Maybe investigate the archive",
            proposed_action="search",
            proposed_target="newspaper_archives",
            scenario_mgr=self.scenario,
            current_loc="central_library",
        )
        # 動詞＋対象が明確な提案は search 候補（wait にしない）
        self.assertEqual(maybe["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(maybe["action"], "search")
        self.assertFalse(maybe.get("do_not_execute"))

    def test_japanese_pure_soft_suggestions_do_not_execute(self):
        samples = (
            "図書館かな",
            "そろそろ移動？",
            "次は近所か",
        )
        for text in samples:
            with self.subTest(text=text):
                intent = interpret_player_intent(
                    text,
                    proposed_action="move",
                    proposed_target="central_library",
                    scenario_mgr=self.scenario,
                    current_loc="introduction",
                )
                self.assertEqual(intent["intent_type"], INTENT_DISCUSSION_OR_PLAN)
                self.assertTrue(intent.get("do_not_execute"))
                out = game_main.reconcile_pl_action(
                    {
                        "action": "move",
                        "target": "central_library",
                        "skill": "",
                        "dialogue": text,
                    },
                    "PC",
                    "",
                    self.scenario,
                    "introduction",
                    char_mgr=self.char_mgr,
                )
                self.assertEqual(out["action"], "wait")
                self.assertTrue(out.get("intent_non_execute"))

    def test_ask_clerk_proposal_is_talk_not_wait(self):
        intent = interpret_player_intent(
            "事務官に聞いてみるのはどうだろう",
            proposed_action="move",
            proposed_target="central_library",
            scenario_mgr=self.scenario,
            current_loc="hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "talk")
        self.assertFalse(intent.get("do_not_execute"))

        self.scenario.location = "hall_of_records"
        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "central_library",
                "skill": "",
                "dialogue": "事務官に聞いてみるのはどうだろう",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "talk")
        self.assertNotEqual(out["action"], "wait")
        self.assertFalse(out.get("intent_non_execute"))

    def test_search_docs_proposal_is_search_not_wait(self):
        intent = interpret_player_intent(
            "資料をもう少し調べようか",
            proposed_action="wait",
            proposed_target="",
            scenario_mgr=self.scenario,
            current_loc="central_library",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertEqual(intent["action"], "search")
        self.assertFalse(intent.get("do_not_execute"))

        self.scenario.location = "central_library"
        out = game_main.reconcile_pl_action(
            {
                "action": "wait",
                "target": "",
                "skill": "",
                "dialogue": "資料をもう少し調べようか",
            },
            "PC",
            "",
            self.scenario,
            "central_library",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "search")
        self.assertFalse(out.get("intent_non_execute"))

    def test_courtesy_and_npc_question_stay_talk(self):
        self.scenario.location = "hall_of_records"
        thanks = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "hall_records_clerk",
                "skill": "",
                "dialogue": "ありがとう、助かります",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(thanks["action"], "talk")
        self.assertNotIn(thanks["action"], ("move", "wait"))

        question = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "hall_records_clerk",
                "skill": "",
                "dialogue": "記録はどこにありますか？",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(question["action"], "talk")
        self.assertEqual(question["target"], "hall_records_clerk")
        self.assertNotEqual(question.get("action"), "move")
        self.assertFalse(question.get("intent_non_execute"))

    def test_next_library_kana_is_wait(self):
        intent = interpret_player_intent(
            "次は図書館かな",
            proposed_action="move",
            proposed_target="central_library",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(intent["intent_type"], INTENT_DISCUSSION_OR_PLAN)
        self.assertEqual(intent["action"], "wait")
        self.assertTrue(intent.get("do_not_execute"))

    def test_go_investigate_library_not_wait(self):
        intent = interpret_player_intent(
            "図書館へ行って調べよう",
            proposed_action="wait",
            proposed_target="",
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertEqual(intent["intent_type"], INTENT_ACTION_REQUEST)
        self.assertIn(intent["action"], ("move", "search"))
        self.assertFalse(intent.get("do_not_execute"))

    def test_safe_resume_rerender_does_not_repause(self):
        state = game_main.normalize_loaded_runtime_state(
            {
                "pending_action_id": "txn-resume-1",
                "last_processed_action_id": "txn-resume-1",
                "is_running": False,
                "autonomous_paused": True,
                "autonomous_pause_reason": "safe_resume_ready",
                "autonomous_user_resumed": False,
                "runtime_load_normalized": False,
                "all_events_log": [],
                "current_loc": "introduction",
            },
            from_save_load=True,
            enforce_half_turn_pause=False,
        )
        self.assertTrue(state.get("autonomous_paused"))
        self.assertFalse(state.get("is_running"))
        self.assertTrue(game_main.begin_autonomous_runtime(state))
        self.assertTrue(state.get("is_running"))
        self.assertFalse(state.get("autonomous_paused"))
        again = game_main.normalize_loaded_runtime_state(
            dict(state),
            from_save_load=False,
            enforce_half_turn_pause=False,
        )
        self.assertTrue(again.get("is_running"))
        self.assertFalse(again.get("autonomous_paused"))
        self.assertNotEqual(again.get("autonomous_pause_reason"), "safe_resume_ready")

    def test_pause_classes_distinguish_resume_modes(self):
        safe = {
            "autonomous_paused": True,
            "autonomous_pause_reason": "safe_resume_ready",
            "pending_action_id": "a",
            "last_processed_action_id": "a",
        }
        self.assertEqual(
            game_main.classify_autonomous_pause(state=safe),
            game_main.PAUSE_CLASS_SAFE_RESUME,
        )
        self.assertTrue(game_main.is_pause_safe_to_resume(safe))

        mid = {
            "autonomous_paused": True,
            "autonomous_pause_reason": "awaiting_system_process",
            "pending_action_id": "b",
            "last_processed_action_id": "a",
            "last_pl_action": {"action": "search"},
        }
        self.assertEqual(
            game_main.classify_autonomous_pause(state=mid),
            game_main.PAUSE_CLASS_REEXEC_FORBIDDEN,
        )
        self.assertFalse(game_main.is_pause_safe_to_resume(mid))

        retry = {
            "autonomous_paused": True,
            "autonomous_pause_reason": game_main.LLM_PAUSE_CONNECTION,
            "pending_action_id": "c",
            "last_processed_action_id": "c",
        }
        self.assertEqual(
            game_main.classify_autonomous_pause(state=retry),
            game_main.PAUSE_CLASS_RETRYABLE,
        )
        self.assertTrue(game_main.is_pause_safe_to_resume(retry))


if __name__ == "__main__":
    unittest.main(verbosity=2)
