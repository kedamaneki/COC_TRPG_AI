# -*- coding: utf-8 -*-
"""
自律巡航の再開（safe_resume_ready）が再描画で潰されないことの回帰テスト。
実行: python test_autonomous_resume.py
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import main as game_main

SAVE = Path(__file__).resolve().parent / "save_autosave.json"
CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"


class TestAutonomousResume(unittest.TestCase):
    def _safe_resume_state(self, **overrides):
        tid = "txn-safe-resume-001"
        state = {
            "all_events_log": [
                {
                    "channel": "IC",
                    "location": "introduction",
                    "text": "PC: 話を聞いた。",
                    "meta": {
                        "pc_id": "pc_01",
                        "action_id": "talk",
                        "target": "steven_knott",
                        "needs_system": True,
                        "system_processed": True,
                        "transaction_id": tid,
                    },
                }
            ],
            "current_loc": "introduction",
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "active_pcs": ["pc_01"],
            "pending_action_id": tid,
            "last_processed_action_id": tid,
            "last_pl_action": {
                "action": "talk",
                "target": "steven_knott",
                "skill": "",
                "transaction_id": tid,
            },
            "last_system_result": {
                "log": "対話完了",
                "transaction_id": tid,
                "success_level": 2,
            },
            "is_running": True,
            "autonomous_paused": False,
            "autonomous_pause_reason": None,
            "autonomous_user_resumed": False,
            "runtime_load_normalized": False,
            "stop_requested": False,
        }
        state.update(overrides)
        return state

    def test_load_applies_safe_resume_ready_once(self):
        loaded = game_main.normalize_loaded_runtime_state(
            self._safe_resume_state(),
            enforce_half_turn_pause=False,
            from_save_load=True,
        )
        self.assertFalse(loaded.get("is_running"))
        self.assertTrue(loaded.get("autonomous_paused"))
        self.assertEqual(loaded.get("autonomous_pause_reason"), "safe_resume_ready")
        self.assertEqual(loaded.get("autonomous_pause_class"), game_main.PAUSE_CLASS_SAFE_RESUME)
        self.assertTrue(loaded.get("runtime_load_normalized"))
        self.assertFalse(loaded.get("autonomous_user_resumed"))

    def test_begin_runtime_then_normalize_does_not_repause(self):
        state = game_main.normalize_loaded_runtime_state(
            self._safe_resume_state(),
            from_save_load=True,
            enforce_half_turn_pause=False,
        )
        self.assertTrue(state.get("autonomous_paused"))

        started = game_main.begin_autonomous_runtime(state)
        self.assertTrue(started)
        self.assertTrue(state.get("is_running"))
        self.assertFalse(state.get("autonomous_paused"))
        self.assertIsNone(state.get("autonomous_pause_reason"))
        self.assertTrue(state.get("autonomous_user_resumed"))

        # Streamlit 再描画相当の正規化を複数回
        for _ in range(3):
            state = game_main.normalize_loaded_runtime_state(
                dict(state),
                enforce_half_turn_pause=False,
                from_save_load=False,
            )
            self.assertTrue(state.get("is_running"), "再描画で is_running が落ちた")
            self.assertFalse(state.get("autonomous_paused"), "再描画で pause に戻った")
            self.assertNotEqual(state.get("autonomous_pause_reason"), "safe_resume_ready")

    def test_apply_game_state_preserves_resume(self):
        state = game_main.normalize_loaded_runtime_state(
            self._safe_resume_state(), from_save_load=True, enforce_half_turn_pause=False,
        )
        game_main.begin_autonomous_runtime(state)
        session = SimpleNamespace()
        # apply_game_state が要求する最低限の属性
        for key, value in state.items():
            setattr(session, key, value)
        session.char_mgr = None
        game_main.apply_game_state(session, state, scenario_mgr=None)
        self.assertTrue(session.is_running)
        self.assertFalse(session.autonomous_paused)
        self.assertTrue(session.autonomous_user_resumed)

    def test_awaiting_system_process_cannot_resume(self):
        state = self._safe_resume_state(
            pending_action_id="txn-mid",
            last_processed_action_id="txn-prev",
            last_system_result=None,
            last_pl_action={"action": "search", "target": "desk"},
            is_running=False,
            autonomous_paused=True,
            autonomous_pause_reason="awaiting_system_process",
            autonomous_pause_class=game_main.PAUSE_CLASS_REEXEC_FORBIDDEN,
            runtime_load_normalized=True,
        )
        self.assertFalse(game_main.is_pause_safe_to_resume(state))
        self.assertFalse(game_main.begin_autonomous_runtime(state))
        self.assertTrue(state.get("autonomous_paused"))
        self.assertFalse(state.get("is_running"))

    def test_retryable_can_resume(self):
        state = self._safe_resume_state(
            is_running=False,
            autonomous_paused=True,
            autonomous_pause_reason=game_main.LLM_PAUSE_CONNECTION,
            autonomous_pause_class=game_main.PAUSE_CLASS_RETRYABLE,
            runtime_load_normalized=True,
        )
        self.assertTrue(game_main.is_pause_safe_to_resume(state))
        self.assertTrue(game_main.begin_autonomous_runtime(state))
        self.assertTrue(state.get("is_running"))
        self.assertFalse(state.get("autonomous_paused"))

        # 再描画でも維持
        again = game_main.normalize_loaded_runtime_state(
            dict(state), from_save_load=False, enforce_half_turn_pause=False,
        )
        self.assertTrue(again.get("is_running"))
        self.assertFalse(again.get("autonomous_paused"))

    def test_no_double_execution_after_resume_when_pending_equals_last(self):
        tid = "txn-dup-guard"
        state = game_main.normalize_loaded_runtime_state(
            self._safe_resume_state(
                pending_action_id=tid,
                last_processed_action_id=tid,
            ),
            from_save_load=True,
            enforce_half_turn_pause=False,
        )
        game_main.begin_autonomous_runtime(state)
        self.assertTrue(game_main.is_duplicate_action_transaction(state, tid))
        replay = game_main.build_idempotent_system_result(state, transaction_id=tid)
        self.assertTrue(replay.get("idempotent_replay"))

    def test_autosave_load_then_resume_survives_rerender(self):
        if not SAVE.exists():
            self.skipTest("save_autosave.json なし")
        raw = json.loads(SAVE.read_text(encoding="utf-8"))
        app = copy.deepcopy(raw.get("app_state") or {})
        app["is_running"] = True
        app["autonomous_paused"] = False
        app["autonomous_pause_reason"] = None
        app["autonomous_user_resumed"] = False
        app["runtime_load_normalized"] = False
        if app.get("last_processed_action_id") and not app.get("pending_action_id"):
            app["pending_action_id"] = app["last_processed_action_id"]
        elif not app.get("pending_action_id"):
            app["pending_action_id"] = "txn-load"
            app["last_processed_action_id"] = "txn-load"

        loaded = game_main.normalize_loaded_runtime_state(
            app, from_save_load=True, enforce_half_turn_pause=False,
        )
        self.assertFalse(loaded.get("is_running"))
        self.assertTrue(loaded.get("autonomous_paused"))

        self.assertTrue(game_main.begin_autonomous_runtime(loaded))
        rerender = game_main.normalize_loaded_runtime_state(
            dict(loaded), from_save_load=False, enforce_half_turn_pause=False,
        )
        self.assertTrue(rerender.get("is_running"))
        self.assertFalse(rerender.get("autonomous_paused"))

    def test_first_timeline_tick_runs_after_resume(self):
        """再開後にタイムライン1ステップが走ること（二重実行なし）。"""
        tid = "txn-tick-1"
        state = game_main.normalize_loaded_runtime_state(
            self._safe_resume_state(
                pending_action_id=tid,
                last_processed_action_id=tid,
            ),
            from_save_load=True,
            enforce_half_turn_pause=False,
        )
        game_main.begin_autonomous_runtime(state)

        tick_ran = {"count": 0}

        def fake_chain(st, managers, **kwargs):
            tick_ran["count"] += 1
            # 処理済み txn のまま進める（二重実行しない）
            self.assertTrue(
                game_main.is_duplicate_action_transaction(st, tid)
            )
            return None, []

        managers = (None, None, None, None)
        with mock.patch.object(game_main, "run_timeline_chain", side_effect=fake_chain):
            with mock.patch.object(game_main, "refresh_autonomous_step_budget_on_progress", return_value=False):
                pause = game_main.run_timeline_loop(
                    state,
                    managers,
                    max_iterations=1,
                    max_chain_per_tick=1,
                )
        self.assertIsNone(pause)
        self.assertEqual(tick_ran["count"], 1)
        self.assertTrue(state.get("is_running"))
        self.assertFalse(state.get("autonomous_paused"))
        # 追加正規化でも落ちない
        state = game_main.normalize_loaded_runtime_state(
            dict(state), from_save_load=False, enforce_half_turn_pause=False,
        )
        self.assertTrue(state.get("is_running"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
