"""
タスク1: 判定 Commit → KP描写の順序・失敗時再試行の単体テスト。

実行:
  python test_kp_narration_commit_order.py
  または: python -m pytest test_kp_narration_commit_order.py -q
"""
from __future__ import annotations

import unittest
from unittest import mock

import main


class TestKpNarrationCommitOrder(unittest.TestCase):
    def _base_state(self):
        return {
            "all_events_log": [],
            "current_loc": "study",
            "last_pl_action": {
                "action": "search",
                "target": "desk",
                "skill": "目星",
                "dialogue": "",
            },
            "last_system_result": {
                "log": "【判定】目星 成功。机の引き出しに手紙を見つけた。",
                "kp_instruction": "手紙の発見を描写せよ。",
                "san_check": {"required": False},
            },
            "pending_san_check": None,
            "stagnation_kp_nudge": "何かヒント",
            "pl_id": "pc_01",
            "char_name": "テスト探索者",
            "active_pcs": ["pc_01"],
            "active_pc_id": "pc_01",
        }

    def _system_entry(self, narrated=False):
        return {
            "channel": "IC",
            "location": "study",
            "secret_to": None,
            "text": "システム: 【判定】目星 成功。机の引き出しに手紙を見つけた。",
            "meta": {
                "action_id": "search",
                "target": "desk",
                "roll_type": "skill",
                "kp_narrated": narrated,
            },
        }

    def _scenario_mgr(self):
        mgr = mock.Mock()
        mgr.get_location_info.return_value = {
            "name": "書斎",
            "default_description": "薄暗い書斎。",
        }
        mgr.get_npcs_present.return_value = []
        mgr.get_object_info.return_value = {}
        mgr.get_all_location_ids.return_value = ["study"]
        mgr.location = "study"
        mgr.flags = {}
        return mgr

    def test_append_system_log_sets_kp_narrated_false(self):
        logs = []
        main.append_system_log_entry(logs, "study", "判定成功", action_id="search", target="desk")
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0]["text"].startswith("システム:"))
        self.assertFalse(logs[0]["meta"]["kp_narrated"])

    def test_kp_narrate_success_marks_narrated_and_clears_pointers(self):
        state = self._base_state()
        entry = self._system_entry(narrated=False)
        state["all_events_log"].append(entry)
        scenario_mgr = self._scenario_mgr()

        with mock.patch.object(
            main,
            "call_kp_api",
            return_value={
                "should_speak": True,
                "speak_mode": "system_narration",
                "text": "机の奥から古い手紙が現れた。どうしますか？",
            },
        ):
            ok = main.step_kp_narrate(state, scenario_mgr)

        self.assertTrue(ok)
        self.assertTrue(entry["meta"]["kp_narrated"])
        self.assertIsNone(state["last_pl_action"])
        self.assertIsNone(state["last_system_result"])
        self.assertIsNone(state["stagnation_kp_nudge"])
        self.assertTrue(any(e.get("text", "").startswith("KP:") for e in state["all_events_log"]))

    def test_kp_narrate_api_failure_leaves_unnarrated_for_retry(self):
        state = self._base_state()
        entry = self._system_entry(narrated=False)
        state["all_events_log"].append(entry)
        # fallback を拒否させるため last_system_result / entry を空寄りのままにしないよう、
        # allow_fallback=True 経路を避けて例外を直接発生させる。
        scenario_mgr = self._scenario_mgr()

        with mock.patch.object(main, "call_kp_api", side_effect=main.KpNarrationError("timeout")):
            ok = main.step_kp_narrate(state, scenario_mgr)

        self.assertFalse(ok)
        self.assertFalse(entry["meta"]["kp_narrated"])
        self.assertIsNotNone(state["last_system_result"])
        self.assertIsNotNone(state["last_pl_action"])
        self.assertFalse(any(e.get("text", "").startswith("KP:") for e in state["all_events_log"]))
        # 再試行可能な未描写エントリとして残る
        self.assertIs(main.find_last_unnarrated_system_entry(state["all_events_log"]), entry)

    def test_kp_narrate_empty_response_does_not_mark_narrated(self):
        state = self._base_state()
        entry = self._system_entry(narrated=False)
        state["all_events_log"].append(entry)
        scenario_mgr = self._scenario_mgr()

        with mock.patch.object(
            main,
            "call_kp_api",
            return_value={"should_speak": True, "speak_mode": "system_narration", "text": ""},
        ):
            with mock.patch.object(main, "_inject_handout_into_kp_data", side_effect=lambda d, *a, **k: d):
                ok = main.step_kp_narrate(state, scenario_mgr)

        self.assertFalse(ok)
        self.assertFalse(entry["meta"]["kp_narrated"])
        self.assertIsNotNone(state["last_system_result"])

    def test_kp_narrate_does_not_mutate_flags_or_pools(self):
        state = self._base_state()
        entry = self._system_entry(narrated=False)
        state["all_events_log"].append(entry)
        scenario_mgr = self._scenario_mgr()
        scenario_mgr.flags = {"letter_found": True}
        flags_before = dict(scenario_mgr.flags)

        with mock.patch.object(
            main,
            "call_kp_api",
            return_value={
                "should_speak": True,
                "speak_mode": "system_narration",
                "text": "手紙を手に取った。どうしますか？",
            },
        ):
            ok = main.step_kp_narrate(state, scenario_mgr)

        self.assertTrue(ok)
        self.assertEqual(scenario_mgr.flags, flags_before)

    def test_action_data_defers_system_processed_until_commit(self):
        state = self._base_state()
        pl_entry = {
            "channel": "IC",
            "location": "study",
            "secret_to": None,
            "text": "テスト探索者(PC): 机を調べる",
            "meta": {
                "pc_id": "pc_01",
                "action_id": "search",
                "target": "desk",
                "skill": "目星",
                "needs_system": True,
                "system_processed": False,
            },
        }
        state["all_events_log"].append(pl_entry)
        scenario_mgr = self._scenario_mgr()

        action = main._action_data_from_timeline(state, scenario_mgr, "テスト探索者", char_mgr=None)
        self.assertEqual(action.get("action"), "search")
        self.assertFalse(pl_entry["meta"]["system_processed"])
        self.assertIs(state.get("_pending_system_pl_entry"), pl_entry)

        main._mark_timeline_pl_action_processed(state)
        self.assertTrue(pl_entry["meta"]["system_processed"])
        self.assertNotIn("_pending_system_pl_entry", state)

    def test_execute_timeline_kp_narrate_advances_only_on_success(self):
        state = self._base_state()
        entry = self._system_entry(narrated=False)
        state["all_events_log"].append(entry)
        scenario_mgr = self._scenario_mgr()
        char_mgr = mock.Mock()
        dice_engine = mock.Mock()
        state_mgr = mock.Mock()
        state_mgr.in_combat = False
        managers = (char_mgr, dice_engine, state_mgr, scenario_mgr)

        with mock.patch.object(main, "step_kp_narrate", return_value=False):
            with mock.patch.object(main, "advance_exploration_turn") as advance:
                main.execute_timeline_step("kp_narrate", state, managers)
                advance.assert_not_called()

        with mock.patch.object(main, "step_kp_narrate", return_value=True):
            with mock.patch.object(main, "advance_exploration_turn") as advance:
                main.execute_timeline_step("kp_narrate", state, managers)
                advance.assert_called_once()


if __name__ == "__main__":
    unittest.main()
