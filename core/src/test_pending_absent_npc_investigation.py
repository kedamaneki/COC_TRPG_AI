# -*- coding: utf-8 -*-
"""
調査用再現テストと修正後の回帰テスト。

目的:
- search/front_door 意図と absent_npc_talk が同居しうる経路
- validation reject が log されても pending が settle されない経路
- stale pending_action_id が stagnation last_eval に再利用される経路
"""
from __future__ import annotations

import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from CharacterManager import CharacterManager
from ScenarioManager import ScenarioManager
import main as game_main

CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"
NPCS = Path(__file__).resolve().parent / "npcs.json"
AUTOSAVE = Path(__file__).resolve().parent / "save_autosave.json"


class TestPendingAbsentNpcInvestigation(unittest.TestCase):
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
        self.pc_path.write_text(
            json.dumps(
                {
                    "pc_01": {
                        "profile": {"name": "マクガフィン刑事", "is_npc": False},
                        "attributes": {
                            "POW": 55,
                            "INT": 65,
                            "DEX": 70,
                            "SAN": {"current": 55, "max": 99, "session_start": 55},
                            "HP": {"current": 12, "max": 12},
                            "MP": {"current": 11, "max": 11},
                            "LUCK": 45,
                        },
                        "skills": {"目星": 65, "説得": 50},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.scenario = ScenarioManager(json.loads(json.dumps(self.scenario_data)))
        self.scenario.location = "corbitt_exterior"
        self.scenario.current_phase = "investigation"
        for flag in (
            "talked_with_knott",
            "knott_letter_read",
            "knott_memo_read",
            "case_accepted",
            "exterior_approached",
        ):
            self.scenario.flags[flag] = True

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _legacy_orphan_tail_fixture():
        """実行中に更新される autosave へ依存せず、旧不整合を固定再現する。"""
        return {
            "pending_action_id": "legacy-orphan-pending",
            "last_processed_action_id": "legacy-last-processed",
            "current_loc": "corbitt_exterior",
            "char_name": "マクガフィン刑事",
            "pl_id": "pc_01",
            "active_pc_id": "pc_01",
            "last_system_result": None,
            "last_pl_action": {
                "action": "search", "target": "front_door", "skill": "目星",
                "message": "正面玄関を調べる。", "dialogue": "正面玄関を調べる。",
                "needs_pl_retry": False,
            },
            "all_events_log": [{
                "channel": "SYSTEM", "text": "旧検証拒否",
                "meta": {
                    "validation_error": "absent_npc_talk",
                    "error_code": "absent_npc_talk",
                    "settled_event_kind": "validation_reject",
                    "transaction_id": "legacy-validation-reject",
                },
            }],
        }

    def test_legacy_orphan_tail_fixture_invariants(self):
        """旧セーブ末尾の不整合を、独立fixtureとして固定観測する。"""
        app = self._legacy_orphan_tail_fixture()
        pending = str(app.get("pending_action_id") or "")
        last = str(app.get("last_processed_action_id") or "")
        self.assertTrue(pending)
        self.assertTrue(last)
        self.assertNotEqual(pending, last)

        logs = app.get("all_events_log") or []
        tids = {
            str((e.get("meta") or {}).get("transaction_id") or "")
            for e in logs
        }
        # pending がログに一度も出ていない（orphan pending）
        self.assertNotIn(pending, tids)

        last_pl = app.get("last_pl_action") or {}
        self.assertEqual(last_pl.get("action"), "search")
        self.assertEqual(last_pl.get("target"), "front_door")
        self.assertFalse(last_pl.get("needs_pl_retry"))
        self.assertFalse(str(last_pl.get("transaction_id") or "").strip())

        # IC の search/front_door はログに無い
        ic_search = [
            e
            for e in logs
            if (e.get("meta") or {}).get("action_id") == "search"
            and (e.get("meta") or {}).get("target") == "front_door"
        ]
        self.assertEqual(ic_search, [])

        reject = [
            e
            for e in logs
            if (e.get("meta") or {}).get("error_code") == "absent_npc_talk"
        ]
        self.assertTrue(reject)
        self.assertEqual(
            (reject[-1].get("meta") or {}).get("settled_event_kind"),
            "validation_reject",
        )

    def test_case1_soft_plan_is_discussion_not_talk(self):
        """ケース1: ドア/窓の方針発話は DISCUSSION / search 候補であり talk ではない。"""
        out = game_main.reconcile_pl_action(
            {
                "action": "wait",
                "target": "",
                "skill": "",
                "dialogue": "",
                "message": "",
            },
            speak_as="BOTH",
            pl_ooc="正面玄関のドアや窓から始めてみよう。何か手がかりを見つけられるかもしれない。",
            scenario_mgr=self.scenario,
            current_loc="corbitt_exterior",
            char_mgr=self.char_mgr,
        )
        intent = out.get("player_intent") or {}
        self.assertNotEqual(out.get("validation_error_code"), "absent_npc_talk")
        self.assertIn(
            intent.get("intent_type"),
            ("DISCUSSION_OR_PLAN", "ACTION_REQUEST", "UNCLEAR"),
        )
        if out.get("intent_non_execute"):
            self.assertEqual(out.get("action"), "wait")
            # soft plan は即時実行しない。候補は hint / intent.target_text のどちらかに出る。
            blob = " ".join(
                [
                    str(out.get("post_action_hint") or ""),
                    str(intent.get("target_text") or ""),
                    str(intent.get("notes") or ""),
                ]
            )
            self.assertTrue(
                ("front_door" in blob)
                or intent.get("intent_type") == "DISCUSSION_OR_PLAN"
                or out.get("action") == "wait"
            )
        elif intent.get("action") == "search":
            self.assertIn(intent.get("target_text"), ("front_door", "exterior_windows", "corbitt_house"))

    def test_case1_llm_talk_to_absent_npc_is_rejected(self):
        """LLM が talk を出した場合のみ absent_npc_talk になる（search ではない）。"""
        out = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "globe_receptionist",
                "skill": "",
                "dialogue": "正面玄関のドアや窓から始めてみよう。",
                "message": "",
            },
            speak_as="PC",
            pl_ooc="",
            scenario_mgr=self.scenario,
            current_loc="corbitt_exterior",
            char_mgr=self.char_mgr,
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertEqual(out.get("validation_error_code"), "absent_npc_talk")
        # この時点の player_intent は search 寄りでも、canonical は reject 側
        self.assertEqual(out.get("action"), "wait")

    def test_case1_search_front_door_does_not_become_absent_npc(self):
        """canonical が search/front_door なら absent_npc_talk にならない。"""
        out = game_main.reconcile_pl_action(
            {
                "action": "search",
                "target": "front_door",
                "skill": "目星",
                "dialogue": "",
                "message": "「……正面玄関のドア、調べてみよう」",
            },
            speak_as="PC",
            pl_ooc="",
            scenario_mgr=self.scenario,
            current_loc="corbitt_exterior",
            char_mgr=self.char_mgr,
        )
        self.assertFalse(out.get("needs_pl_retry"))
        self.assertNotEqual(out.get("validation_error_code"), "absent_npc_talk")
        self.assertEqual(out.get("action"), "search")
        self.assertEqual(out.get("target"), "front_door")

    def test_case2_library_reception_talk_is_absent(self):
        """ケース2: 図書館にいない受付への talk は absent_npc_talk。"""
        self.scenario.location = "central_library"
        out = game_main.reconcile_pl_action(
            {
                "action": "talk",
                "target": "globe_receptionist",
                "skill": "",
                "dialogue": "受付の方、手続きを済ませていただけますか。",
                "message": "",
            },
            speak_as="PC",
            pl_ooc="",
            scenario_mgr=self.scenario,
            current_loc="central_library",
            char_mgr=self.char_mgr,
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertEqual(out.get("validation_error_code"), "absent_npc_talk")

    def test_validation_reject_bind_without_commit_leaves_pending_gap(self):
        """reject は bind するが commit しない → pending != last_processed が残る。"""
        state = {
            "pending_action_id": "old-committed",
            "last_processed_action_id": "old-committed",
            "pl_id": "pc_01",
            "active_pc_id": "pc_01",
            "actor_id": "pc_01",
            "decision_owner_id": "pc_01",
        }
        pc_action = {
            "action": "wait",
            "needs_pl_retry": True,
            "validation_error_code": "absent_npc_talk",
        }
        tid = game_main.ensure_settled_nonprogress_event_id(
            pc_action, event_kind="validation_reject",
        )
        game_main.bind_action_transaction(
            state, transaction_id=tid, actor_id="pc_01", decision_owner_id="pc_01",
        )
        self.assertEqual(state["pending_action_id"], tid)
        self.assertEqual(state["last_processed_action_id"], "old-committed")
        self.assertNotEqual(state["pending_action_id"], state["last_processed_action_id"])
        # commit されない限りギャップは残る（reject 経路の仕様）
        self.assertNotEqual(state["pending_action_id"], state["last_processed_action_id"])

    def test_stagnation_does_not_reuse_stale_pending_for_another_pl_action(self):
        """ID がない別手番を古い pending と同一視しない。"""
        stale = "c11fc26b-bab0-47d3-b55e-78bae7f67093"
        pl_action = {"action": "wait", "target": "", "skill": ""}
        state = {"pending_action_id": stale, "last_processed_action_id": "7ac7f939-ddde-4d8d-9f0d-18f5dda516aa"}
        resolved = game_main.resolve_stagnation_transaction_id(None, pl_action, state)
        self.assertEqual(resolved, "")

    def test_legacy_autosave_search_is_enqueued_once(self):
        state = copy.deepcopy(self._legacy_orphan_tail_fixture())
        # orphan pending はロード時の timeline recovery が除去した後を再現する。
        state["pending_action_id"] = ""
        self.assertTrue(game_main.recover_unqueued_last_action(
            state, state.get("char_name", ""), self.scenario, self.char_mgr,
        ))
        tid = state["last_pl_action"]["transaction_id"]
        self.assertEqual(state["pending_action_id"], tid)
        self.assertFalse(game_main.recover_unqueued_last_action(
            state, state.get("char_name", ""), self.scenario, self.char_mgr,
        ))
        self.assertEqual(game_main.determine_timeline_next_step(
            state, state.get("char_name", ""), self.scenario, char_mgr=self.char_mgr,
        ), "system_process")

    def test_discussion_turn_commits_its_own_transaction(self):
        state = {
            "all_events_log": [], "current_loc": "corbitt_exterior",
            "pl_id": "pc_01", "char_name": "マクガフィン刑事",
            "active_pcs": ["pc_01"], "active_pc_id": "pc_01",
            "pending_action_id": "old-pending", "last_processed_action_id": "old-done",
            "pending_san_check": None, "pending_push_roll": None,
            "last_system_result": None, "pl_discussion_mode": False,
        }
        response = {
            "should_speak": False, "speak_as": "PL",
            "pl_ooc_chat": "まずは正面玄関のドアや窓を調べようか。",
            "pc_action": {"action": "wait", "target": "", "skill": "", "dialogue": "", "message": ""},
        }
        with mock.patch.object(game_main, "call_pl_api", return_value=response), \
             mock.patch.object(game_main, "generate_pl_prompt", return_value="prompt"), \
             mock.patch.object(game_main, "prepare_active_pc_for_pl_turn", return_value=True), \
             mock.patch.object(game_main, "format_prompt_history_logs", return_value=([], [])):
            action = game_main.step_pl_turn(
                state, self.char_mgr, self.scenario, "pc_01", "マクガフィン刑事",
            )
        tid = action.get("transaction_id")
        self.assertTrue(tid)
        self.assertEqual(state["pending_action_id"], tid)
        self.assertEqual(state["last_processed_action_id"], tid)
        self.assertTrue(any(
            (entry.get("meta") or {}).get("transaction_id") == tid
            for entry in state["all_events_log"]
        ))

    def test_retry_final_search_is_queued_for_system(self):
        """
        同一 step_pl_turn 内:
          1回目 apply → absent_npc log
          2回目 apply → search（should_speak=False で IC 未出力）
        のとき、最終 last_pl_action は search だが pending は更新されない。
        """
        logs = []
        state = {
            "all_events_log": logs,
            "current_loc": "corbitt_exterior",
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "active_pcs": ["pc_01"],
            "active_pc_id": "pc_01",
            "pending_action_id": "stale-pending",
            "last_processed_action_id": "7ac7f939-ddde-4d8d-9f0d-18f5dda516aa",
            "pending_san_check": None,
            "pending_push_roll": None,
            "last_system_result": None,
            "stagnation_pl_hint": None,
            "force_ic_action": False,
            "pl_discussion_mode": False,
            "validation_retry_state": {},
        }

        first = {
            "should_speak": True,
            "speak_as": "PC",
            "pl_ooc_chat": "",
            "pc_action": {
                "action": "talk",
                "target": "globe_receptionist",
                "skill": "",
                "dialogue": "正面玄関のドアや窓から始めてみよう。",
                "message": "",
            },
        }
        second = {
            "should_speak": False,  # IC を出さない経路
            "speak_as": "PC",
            "pl_ooc_chat": "",
            "pc_action": {
                "action": "search",
                "target": "front_door",
                "skill": "目星",
                "dialogue": "",
                "message": "「……正面玄関のドア、調べてみよう」",
            },
        }
        responses = [first, second]

        def fake_call_pl_api(*args, **kwargs):
            return responses.pop(0)

        with mock.patch.object(game_main, "call_pl_api", side_effect=fake_call_pl_api):
            with mock.patch.object(game_main, "generate_pl_prompt", return_value="prompt"):
                with mock.patch.object(game_main, "prepare_active_pc_for_pl_turn", return_value=True):
                    with mock.patch.object(
                        game_main,
                        "format_prompt_history_logs",
                        return_value=([], []),
                    ):
                        pc_action = game_main.step_pl_turn(
                            state,
                            self.char_mgr,
                            self.scenario,
                            "pc_01",
                            "マクガフィン刑事",
                            state_mgr=None,
                        )

        # 中間 reject はログに残る
        reject_logs = [
            e for e in logs if (e.get("meta") or {}).get("error_code") == "absent_npc_talk"
        ]
        self.assertTrue(reject_logs)

        # 最終の search は should_speak=False でも IC と transaction を持つ
        self.assertEqual(pc_action.get("action"), "search")
        self.assertEqual(pc_action.get("target"), "front_door")
        self.assertTrue(str(pc_action.get("transaction_id") or "").strip())
        ic_search = [
            e
            for e in logs
            if (e.get("meta") or {}).get("action_id") == "search"
            and (e.get("meta") or {}).get("target") == "front_door"
        ]
        self.assertEqual(len(ic_search), 1)
        self.assertEqual((ic_search[0].get("meta") or {}).get("transaction_id"), pc_action["transaction_id"])

        self.assertEqual(state["pending_action_id"], pc_action["transaction_id"])
        self.assertEqual(state["last_pl_action"].get("action"), "search")
        self.assertIsNone(state.get("last_system_result"))
        self.assertEqual(
            game_main.determine_timeline_next_step(
                state, state["char_name"], self.scenario, char_mgr=self.char_mgr,
            ),
            "system_process",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
