# -*- coding: utf-8 -*-
"""
save_autosave.json 最新ログで観測された問題の回帰テスト。
LLM 通信なし。save_autosave.json は読み取り専用（上書きしない）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

import main
from ActionValidator import (
    PL_IDENTITY_MISMATCH_CODE,
    detect_kp_narration_violations,
    detect_pl_identity_violation,
    object_is_currently_available,
)
from GameStateManager import GameStateManager
from LogEvaluator import extract_decision_cases
from NPCSocialManager import NPCSocialManager
from ScenarioManager import ScenarioManager
from test_knowledge_isolation import FakeCharMgr, FakeScenarioMgr

ROOT = Path(__file__).resolve().parent
SAVE = ROOT / "save_autosave.json"
CORBITT = ROOT / "scenario_corbitt.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LatestLogRegressionTests(unittest.TestCase):
    def setUp(self):
        self.cm = FakeCharMgr()
        self.cm.characters["pc_02"]["profile"].update(
            name="エレノア教授", occupation="民俗学教授",
        )
        self.cm.characters["pc_01"]["profile"].update(
            name="マクガフィン刑事", occupation="警官（刑事）",
        )
        self.state = {
            "current_loc": "study",
            "active_pcs": ["pc_01", "pc_02"],
            "pl_id": "pc_01",
            "actor_id": "pc_01",
            "all_events_log": [],
            "public_knowledge_ids": [],
        }
        self._save_hash = _sha(SAVE) if SAVE.exists() else None

    def tearDown(self):
        if self._save_hash and SAVE.exists():
            self.assertEqual(_sha(SAVE), self._save_hash)

    # ---------- 1. 職業偽装 ----------
    def test_false_role_without_formal_introduction(self):
        samples = [
            "刑事としての立場から情報提供をお願いします。",
            "刑事として捜査しています。",
            "刑事として情報提供を求める。",
            "刑事の権限で閲覧させてください。",
        ]
        for text in samples:
            with self.subTest(text=text):
                v = detect_pl_identity_violation(text, self_occupation="民俗学教授")
                self.assertIsNotNone(v)
                self.assertEqual(v["error_code"], PL_IDENTITY_MISMATCH_CODE)

        self.assertIsNone(detect_pl_identity_violation(
            "仲間の刑事としての立場を尊重します。", self_occupation="民俗学教授",
        ))
        self.assertIsNone(detect_pl_identity_violation(
            "マクガフィン刑事としての立場を尊重します。",
            self_occupation="民俗学教授",
            other_profiles=[{"name": "マクガフィン刑事", "short_name": "マクガフィン"}],
        ))
        # 自分の職業主張は違反ではない
        self.assertIsNone(detect_pl_identity_violation(
            "教授としての立場から文献調査の協力をお願いします。",
            self_occupation="民俗学教授",
        ))

    def test_false_identity_does_not_receive_occupation_bonus(self):
        with mock.patch.object(main, "call_occupation_rp_judge") as judge:
            result = main.judge_occupation_roleplay(
                char_mgr=self.cm,
                pc_id="pc_02",
                npc_id="clerk",
                dialogue_text="刑事としての立場から情報提供をお願いします。",
            )
        judge.assert_not_called()
        self.assertEqual(result["bonus_dice"], 0)
        self.assertFalse(result["skip_roll"])

    def test_apply_rejects_occupation_claim_without_ic_commit(self):
        logs = []
        scenario = FakeScenarioMgr()
        out = main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pc_action": {
                    "action": "talk",
                    "target": "artie_wilmott",
                    "dialogue": "刑事としての立場から情報提供をお願いします。",
                },
            },
            "エレノア教授",
            "boston_globe",
            logs,
            scenario_mgr=scenario,
            char_mgr=self.cm,
            pc_id="pc_02",
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertEqual(out.get("validation_error_code"), PL_IDENTITY_MISMATCH_CODE)
        self.assertFalse(any(
            "刑事としての立場から情報提供" in str(e.get("text") or "")
            and "(PC" in str(e.get("text") or "")
            for e in logs
        ))

    def test_pl_prompt_warns_against_false_occupation_claim(self):
        prompt = main.generate_pl_prompt(
            "エレノア教授", [], [],
            char_mgr=self.cm, pl_id="pc_02", active_pcs=["pc_01", "pc_02"],
            location_info={"name": "グローブ", "objects": {}},
        )
        self.assertIn("刑事としての立場", prompt)
        self.assertIn("模倣", prompt)

    # ---------- 2. 成功否定 ----------
    def test_success_negation_from_actual_log(self):
        result = {"success_level": 3, "confirmed_fact": "庭の手入れがされていない。"}
        self.assertIn(
            "success_negated",
            detect_kp_narration_violations(
                "特に何も見つかったわけではないが", last_system_result=result,
            ),
        )
        for phrase in (
            "何も見つからなかった",
            "何も見つかっていない",
            "何も発見できなかった",
            "手がかりはなかった",
            "手がかりが得られなかった",
            "許可は得られなかった",
            "失敗に終わった",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(
                    "success_negated",
                    detect_kp_narration_violations(phrase, last_system_result=result),
                )
        self.assertEqual(
            [],
            detect_kp_narration_violations(
                "前回は何も見つからなかったが、今回は手がかりを得た。",
                last_system_result=result,
            ),
        )

    # ---------- 3/4. 知識共有 ----------
    def social_result(self, **extras):
        return {
            "target": "dolly_shopkeeper",
            "log": "場所を聞いた。",
            "social": {
                "npc_id": "dolly_shopkeeper",
                "revealed_secrets": [{"id": "route", "content": "チャペルの場所"}],
            },
            **extras,
        }

    def test_public_talk_survives_location_and_history_change(self):
        main._append_result_log_with_knowledge(
            self.state, self.social_result(), current_loc="study",
            char_mgr=self.cm, pl_id="pc_02",
        )
        self.state["current_loc"] = "hallway"
        for pc in self.state["active_pcs"]:
            self.assertTrue(self.cm.pc_knows(pc, "secret:dolly_shopkeeper:route"))
            self.assertIn(
                "チャペルの場所",
                main._build_pl_known_knowledge_block(self.cm, pc, self.state),
            )
        self.assertFalse(
            main.apply_knowledge_grants_from_result(
                self.cm, "pc_02", self.social_result(), self.state,
            )
        )

    def test_private_talk_is_not_shared(self):
        main._append_result_log_with_knowledge(
            self.state, self.social_result(secret_to=["pc_02"]),
            current_loc="study", char_mgr=self.cm, pl_id="pc_02",
        )
        self.assertFalse(self.cm.pc_knows("pc_01", "secret:dolly_shopkeeper:route"))
        self.assertEqual(["pc_02"], self.state["all_events_log"][-1]["secret_to"])

    def test_nonparticipating_pc_does_not_receive_talk(self):
        self.state["active_pcs"] = ["pc_02"]
        main.apply_knowledge_grants_from_result(
            self.cm, "pc_02", self.social_result(), self.state,
        )
        self.assertFalse(self.cm.pc_knows("pc_01", "secret:dolly_shopkeeper:route"))

    def test_private_object_stays_private(self):
        main.apply_knowledge_grants_from_result(
            self.cm, "pc_02",
            {"target": "desk", "confirmed_fact": "秘密の手紙"},
            self.state,
        )
        self.assertFalse(self.cm.pc_knows("pc_01", "object:desk"))

    def test_scope_public_grant_reaches_all_active_pcs(self):
        result = {
            "knowledge_grants": [{
                "knowledge_id": "public:shared_clue",
                "scope": "public",
                "summary": "公開の手がかり",
                "mark_investigated": False,
            }],
        }
        main.apply_knowledge_grants_from_result(self.cm, "pc_02", result, self.state)
        self.assertIn("public:shared_clue", self.state["public_knowledge_ids"])
        for pc in ("pc_01", "pc_02"):
            self.assertTrue(self.cm.pc_knows(pc, "public:shared_clue"))

    def test_private_kp_narration_inherits_audience(self):
        result = {
            "target": "desk",
            "confirmed_fact": "秘密の手紙",
            "success_level": 2,
            "log": "手紙を発見。",
        }
        self.state.update(
            last_system_result=result,
            last_pl_action={"action": "search", "target": "desk"},
        )
        entry = {
            "text": "システム: 手紙を発見。",
            "secret_to": ["pc_01"],
            "meta": {"kp_narrated": False},
        }
        self.state["all_events_log"] = [entry]
        with mock.patch.object(main, "generate_kp_prompt", return_value="prompt"), \
             mock.patch.object(
                 main, "_inject_handout_into_kp_data",
                 side_effect=lambda data, *a, **kw: data,
             ), \
             mock.patch.object(
                 main, "call_kp_api",
                 return_value={
                     "should_speak": True,
                     "speak_mode": "system_narration",
                     "text": "秘密の手紙を発見した。",
                 },
             ):
            self.assertTrue(
                main.step_kp_eval(self.state, FakeScenarioMgr(), entry, self.cm)
            )
        self.assertEqual(["pc_01"], self.state["all_events_log"][-1]["secret_to"])

    # ---------- 5. 停滞スナップショット ----------
    def test_commit_reset_preserves_knowledge_snapshot(self):
        sm = FakeScenarioMgr()
        gm = GameStateManager(self.cm)
        self.cm.grant_knowledge(
            "pc_01", "secret:clerk:route", summary="道順", mark_investigated=False,
        )
        main.commit_system_resolution(
            self.state, {"log": "進展", "stagnation_progress": True},
            current_loc="study", char_mgr=self.cm, scenario_mgr=sm,
            state_mgr=gm, auto_resolve_san=False,
        )
        current = main._build_stagnation_progress_snapshot(self.state, sm, self.cm)
        self.assertFalse(
            gm.compute_state_delta(
                gm.stagnation_tracker["progress_snapshot"], current,
            )["has_progress"]
        )

    # ---------- 6. 移動破棄 ----------
    def test_move_cleanup_keeps_current_move_and_drops_stale_action(self):
        move = {
            "location": "study",
            "meta": {
                "action_id": "move",
                "target": "hallway",
                "needs_system": True,
                "transaction_id": "move-1",
            },
        }
        stale = {
            "location": "study",
            "meta": {
                "action_id": "search",
                "target": "desk",
                "needs_system": True,
                "transaction_id": "old-1",
            },
        }
        self.state.update(
            all_events_log=[move, stale],
            pending_action_id="move-1",
            _pending_system_pl_entry=move,
        )
        main.apply_location_change_side_effects(
            self.state,
            {
                "location_changed": True,
                "new_location": "hallway",
                "from_location": "study",
            },
        )
        self.assertNotIn("invalidated_by_move", move["meta"])
        self.assertTrue(stale["meta"]["invalidated_by_move"])
        self.assertEqual(1, self.state["all_events_log"][-1]["meta"]["count"])

    # ---------- 3. social_progress 二重実行 ----------
    def test_unlock_messages_are_once_only(self):
        data = json.loads(CORBITT.read_text(encoding="utf-8"))
        for npc, loc in (
            ("hall_records_clerk", "hall_of_records"),
            ("dolly_shopkeeper", "the_neighborhood"),
        ):
            with self.subTest(npc=npc):
                sm = ScenarioManager(copy.deepcopy(data))
                args = dict(
                    current_loc=loc, npc_id=npc, action_id="talk", social_result={},
                )
                first, _, _ = main._apply_social_progress_rules(sm, **args)
                self.assertIn("解禁", first)
                second, kp, _ = main._apply_social_progress_rules(sm, **args)
                self.assertEqual("", second)
                self.assertIn("完了済み", kp)

    def test_completed_social_prompt_does_not_invite_retry(self):
        manager = NPCSocialManager(self.cm)
        with mock.patch.object(manager, "get_personality", return_value=""), \
             mock.patch.object(manager, "get_secrets", return_value={"route": {}}), \
             mock.patch.object(manager, "get_revealed_secret_ids", return_value=["route"]), \
             mock.patch.object(manager, "build_npc_prompt_block", return_value=""):
            prompt = manager._build_kp_instruction(
                "clerk", "事務官", casual=True, skill="",
                revealed=[{"content": "道順"}], relationship="neutral",
                is_success=True, success_level=2,
            )
        self.assertIn("今回の確定情報", prompt)
        self.assertIn("情報開示完了", prompt)
        self.assertNotIn("決定的な秘密は明かさない", prompt)
        self.assertNotIn("もう一度話しかけ", prompt)

    # ---------- 7/8. 自動補正 ----------
    def test_correction_is_visible_to_autonomy_evaluation(self):
        entry = {
            "channel": "IC",
            "location": "study",
            "text": "探索者: 調べる。",
            "meta": {
                "pc_id": "pc_01",
                "actor_id": "pc_01",
                "action_id": "search",
                "target": "desk",
                "transaction_id": "t1",
                "action_origin": "SYSTEM_FORCED",
                "intent_replaced": True,
                "original_action": {"action": "talk", "target": "npc"},
                "forced_progress": True,
            },
        }
        cases = extract_decision_cases([entry], state=self.state, char_mgr=self.cm)
        self.assertTrue(cases)
        self.assertTrue(cases[0]["annotations"]["forced_progress"])

    def test_auto_correction_records_intent_replaced_and_dedupes_log(self):
        scenario = ScenarioManager(copy.deepcopy(json.loads(CORBITT.read_text(encoding="utf-8"))))
        scenario.location = "introduction"
        scenario.flags.update(
            talked_with_knott=True, knott_letter_read=True, knott_memo_read=True,
        )
        fixed = main._build_auto_correction_action(
            {"action": "move", "target": "corbitt_exterior", "dialogue": "屋敷へ"},
            {"action": "move", "target": "boston_globe"},
            scenario, "introduction", self.cm,
        )
        self.assertIsNotNone(fixed)
        self.assertTrue(fixed.get("intent_replaced"))
        self.assertTrue(fixed.get("forced_progress"))
        self.assertEqual(fixed["original_action"]["target"], "corbitt_exterior")
        self.assertEqual(fixed["action"], "move")
        self.assertEqual(fixed["target"], "boston_globe")

        logs = []
        fixed["transaction_id"] = "corr-1"
        main.apply_pl_response_to_logs(
            {"speak_as": "PC", "should_speak": True, "pc_action": fixed},
            "マクガフィン刑事", "introduction", logs,
            scenario_mgr=scenario, char_mgr=self.cm, pc_id="pc_01",
        )
        # 同じ補正を再適用してもログは1回
        main.apply_pl_response_to_logs(
            {"speak_as": "PC", "should_speak": True, "pc_action": dict(fixed)},
            "マクガフィン刑事", "introduction", logs,
            scenario_mgr=scenario, char_mgr=self.cm, pc_id="pc_01",
        )
        corr_logs = [
            e for e in logs
            if "【アクション自動補正】" in str(e.get("text") or "")
        ]
        self.assertEqual(1, len(corr_logs))

    # ---------- 9. 候補表示 ----------
    def test_locked_reference_room_not_in_guidance(self):
        data = json.loads(CORBITT.read_text(encoding="utf-8"))
        sm = ScenarioManager(copy.deepcopy(data))
        sm.location = "boston_globe"
        sm.flags["artie_introduced"] = False
        obj = sm.get_object_info("boston_globe", "reference_room_clipping_files")
        self.assertFalse(object_is_currently_available(obj, sm.flags))
        # char_mgr=None でも requires_flag / access_gate で候補から除外されること
        text = "\n".join(main.build_absent_npc_guidance(sm, "boston_globe", char_mgr=None))
        self.assertNotIn("reference_room_clipping_files", text)
        self.assertIn("globe_receptionist", text)
        self.assertNotIn("artie_wilmott", text)

        sm.flags["artie_introduced"] = True
        sm.flags["artie_reference_room_access_granted"] = True
        obj2 = sm.get_object_info("boston_globe", "reference_room_clipping_files")
        self.assertTrue(object_is_currently_available(obj2, sm.flags))

    # ---------- 10. scenario_mgr=None 移動 ----------
    def test_move_side_effects_safe_without_scenario_mgr(self):
        move = {
            "location": "study",
            "meta": {
                "action_id": "move",
                "target": "hallway",
                "needs_system": True,
                "transaction_id": "move-none-1",
            },
        }
        stale = {
            "location": "study",
            "meta": {
                "action_id": "search",
                "target": "desk",
                "needs_system": True,
                "transaction_id": "old-none-1",
            },
        }
        self.state.update(
            all_events_log=[move, stale],
            pending_action_id="move-none-1",
            current_loc="study",
            _pending_system_pl_entry=move,
        )
        # scenario_mgr=None でもクラッシュせず、移動と古いアクション整理は行う
        ok = main.apply_location_change_side_effects(
            self.state,
            {
                "location_changed": True,
                "new_location": "hallway",
                "from_location": "study",
            },
            scenario_mgr=None,
        )
        self.assertTrue(ok)
        self.assertEqual(self.state["current_loc"], "hallway")
        self.assertNotIn("invalidated_by_move", move["meta"])
        self.assertTrue(stale["meta"].get("invalidated_by_move"))

    # ---------- 11. 会話意図を move へ置換しない ----------
    def test_followup_talk_is_not_silently_replaced_with_move(self):
        scenario = ScenarioManager(copy.deepcopy(json.loads(CORBITT.read_text(encoding="utf-8"))))
        scenario.location = "introduction"
        scenario.flags.update(
            talked_with_knott=True, knott_letter_read=True, knott_memo_read=True,
        )
        logs = []
        out = main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pc_action": {
                    "action": "talk",
                    "target": "steven_knott",
                    "dialogue": "屋敷の鍵についてもう少し詳しく教えてください。",
                },
            },
            "エレノア教授",
            "introduction",
            logs,
            scenario_mgr=scenario,
            char_mgr=self.cm,
            pc_id="pc_02",
        )
        self.assertEqual(out.get("action"), "talk")
        self.assertEqual(out.get("target"), "steven_knott")
        self.assertFalse(out.get("auto_corrected"))
        self.assertFalse(any(
            (e.get("meta") or {}).get("action_id") == "move"
            and (e.get("meta") or {}).get("pc_id") == "pc_02"
            for e in logs
        ))
        self.assertTrue(any((e.get("meta") or {}).get("post_action_hint") for e in logs))

    def test_globe_done_talk_keeps_intent_and_suggests_next_location(self):
        scenario = ScenarioManager(copy.deepcopy(json.loads(CORBITT.read_text(encoding="utf-8"))))
        scenario.location = "boston_globe"
        scenario.flags.update(
            artie_introduced=True,
            artie_reference_room_access_granted=True,
            accessed_clipping_files=True,
            investigated_targets=["reference_room_clipping_files"],
        )
        logs = []
        out = main.apply_pl_response_to_logs(
            {
                "speak_as": "PC",
                "should_speak": True,
                "pc_action": {
                    "action": "talk",
                    "target": "artie_wilmott",
                    "dialogue": "記事の出典についてもう一点確認させてください。",
                },
            },
            "エレノア教授",
            "boston_globe",
            logs,
            scenario_mgr=scenario,
            char_mgr=self.cm,
            pc_id="pc_02",
        )
        self.assertEqual(out.get("action"), "talk")
        self.assertEqual(out.get("target"), "artie_wilmott")
        self.assertFalse(out.get("auto_corrected"))
        self.assertTrue(any(
            "central_library" in str(e.get("text") or "")
            or "公文書館" in str(e.get("text") or "")
            for e in logs
        ))

    # ---------- 12. LLM失敗後の再開／冪等 ----------
    def test_llm_failure_pauses_without_reprocessing_committed_action(self):
        tid = "e6594dc3-a24f-4536-81ef-d4db7a87a71b"
        state = main.ensure_transaction_state_fields({
            "all_events_log": [
                {
                    "channel": "IC",
                    "location": "boston_globe",
                    "text": "PC: 調査する",
                    "meta": {
                        "action_id": "search",
                        "target": "reference_room_clipping_files",
                        "needs_system": True,
                        "system_processed": True,
                        "transaction_id": tid,
                        "pc_id": "pc_01",
                    },
                },
            ],
            "current_loc": "boston_globe",
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "active_pcs": ["pc_01"],
            "pending_action_id": tid,
            "last_processed_action_id": tid,
            "last_system_result": {
                "log": "調査成功",
                "transaction_id": tid,
                "success_level": 3,
            },
            "is_running": True,
            "autonomous_paused": False,
        })
        category = main.apply_llm_failure_pause(state, {
            "category": main.LLM_PAUSE_CONNECTION,
            "message": "Connection refused",
            "attempts": 3,
        })
        self.assertEqual(category, main.LLM_PAUSE_CONNECTION)
        self.assertTrue(state["autonomous_paused"])
        self.assertFalse(state["is_running"])
        self.assertEqual(state["pending_action_id"], tid)
        self.assertEqual(state["last_processed_action_id"], tid)
        self.assertEqual(state.get("autonomous_pause_class"), main.PAUSE_CLASS_RETRYABLE)
        self.assertTrue(main.is_pause_safe_to_resume(state))
        self.assertTrue(any((e.get("meta") or {}).get("llm_failure") for e in state["all_events_log"]))

        # 同一 transaction は再判定しない
        replay = main.build_idempotent_system_result(state, transaction_id=tid)
        self.assertTrue(replay.get("idempotent_replay"))
        self.assertTrue(main.is_duplicate_action_transaction(state, tid))

    def test_autosave_load_resumes_from_safe_paused_state(self):
        if not SAVE.exists():
            self.skipTest("save_autosave.json がありません")
        raw = json.loads(SAVE.read_text(encoding="utf-8"))
        app = copy.deepcopy(raw.get("app_state") or {})
        # 現行セーブは is_running=True のまま保存されるケースがある
        app["is_running"] = True
        app["autonomous_paused"] = False
        app["autonomous_pause_reason"] = None
        # セーブに再開フラグが残っていても、明示ロードなら一度安全 pause する
        app["autonomous_user_resumed"] = False
        app["runtime_load_normalized"] = False
        # pending == last_processed ならロード時に安全 pause されること
        if app.get("last_processed_action_id"):
            app["pending_action_id"] = app["last_processed_action_id"]
        else:
            app["pending_action_id"] = "txn-load-safe"
            app["last_processed_action_id"] = "txn-load-safe"
        normalized = main.normalize_loaded_runtime_state(
            app, enforce_half_turn_pause=False, from_save_load=True,
        )
        self.assertFalse(normalized.get("is_running"))
        self.assertTrue(normalized.get("autonomous_paused"))
        self.assertTrue(normalized.get("current_loc"))
        self.assertIn(
            normalized.get("current_loc"),
            {
                "boston_globe",
                "introduction",
                "central_library",
                "hall_of_records",
                "the_neighborhood",
                "roxbury_sanitarium",
                "chapel_of_contemplation",
                "corbitt_exterior",
            },
        )
        self.assertEqual(
            normalized.get("pending_action_id"),
            normalized.get("last_processed_action_id"),
        )
        self.assertIn(
            normalized.get("autonomous_pause_reason"),
            {"safe_resume_ready", "loaded_while_running", "empty_tick", *main.LLM_PAUSE_REASONS},
        )
        self.assertIn(
            normalized.get("autonomous_pause_class"),
            {
                main.PAUSE_CLASS_SAFE_RESUME,
                main.PAUSE_CLASS_RETRYABLE,
            },
        )
        # 再描画相当では再pauseしない（正規化済みフラグが立つ）
        again = main.normalize_loaded_runtime_state(
            dict(normalized), enforce_half_turn_pause=False, from_save_load=False,
        )
        self.assertTrue(again.get("runtime_load_normalized"))
        self.assertTrue(again.get("autonomous_paused"))
        self.assertFalse(again.get("is_running"))


if __name__ == "__main__":
    unittest.main()
