"""
タスク2: 冪等性（Idempotency）とトランザクションIDの単体テスト。

実行:
  python test_idempotency_transaction.py
"""
from __future__ import annotations

import unittest
from unittest import mock

import main


class TestIdempotencyTransaction(unittest.TestCase):
    def _base_state(self, txn_id="txn-fixed-001"):
        return main.ensure_transaction_state_fields({
            "all_events_log": [],
            "current_loc": "study",
            "pl_id": "pc_01",
            "char_name": "テスト探索者",
            "active_pcs": ["pc_01"],
            "active_pc_id": "pc_01",
            "actor_id": "pc_01",
            "decision_owner_id": "pc_01",
            "pending_action_id": txn_id,
            "last_processed_action_id": None,
            "last_pl_action": {
                "action": "search",
                "target": "desk",
                "skill": "目星",
                "dialogue": "",
                "transaction_id": txn_id,
                "actor_id": "pc_01",
                "decision_owner_id": "pc_01",
            },
            "last_system_result": None,
            "pending_san_check": None,
            "pending_push_roll": None,
            "pending_luck_burn": None,
            "pending_combat_defense": None,
            "partial_system_log": None,
            "push_decision_required": False,
            "stagnation_pl_hint": None,
        })

    def _pending_entry(self, txn_id="txn-fixed-001", processed=False):
        return {
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
                "system_processed": processed,
                "transaction_id": txn_id,
                "actor_id": "pc_01",
                "decision_owner_id": "pc_01",
            },
        }

    def _scenario_mgr(self):
        mgr = mock.Mock()
        mgr.get_location_info.return_value = {"name": "書斎", "default_description": ""}
        mgr.get_npcs_present.return_value = []
        mgr.get_object_info.return_value = {}
        mgr.get_all_location_ids.return_value = ["study"]
        mgr.location = "study"
        mgr.flags = {}
        return mgr

    def test_ensure_transaction_fields_initialized(self):
        state = main.ensure_transaction_state_fields({"pl_id": "pc_01", "active_pc_id": "pc_01"})
        self.assertIn("pending_action_id", state)
        self.assertIn("last_processed_action_id", state)
        self.assertEqual(state["actor_id"], "pc_01")
        self.assertEqual(state["decision_owner_id"], "pc_01")

    def test_new_action_transaction_id_unique(self):
        a = main.new_action_transaction_id()
        b = main.new_action_transaction_id()
        self.assertTrue(a)
        self.assertTrue(b)
        self.assertNotEqual(a, b)

    def test_commit_updates_last_processed_action_id(self):
        state = self._base_state("txn-abc")
        main.commit_action_transaction(state, "txn-abc")
        self.assertEqual(state["last_processed_action_id"], "txn-abc")
        self.assertEqual(state["pending_action_id"], "txn-abc")

    def test_duplicate_guard_matches_last_processed(self):
        state = self._base_state("txn-dup")
        state["last_processed_action_id"] = "txn-dup"
        self.assertTrue(main.is_duplicate_action_transaction(state, "txn-dup"))
        self.assertFalse(main.is_duplicate_action_transaction(state, "txn-other"))

    def test_step_system_process_skips_duplicate_without_reroll(self):
        txn = "txn-idem-001"
        state = self._base_state(txn)
        entry = self._pending_entry(txn, processed=False)
        state["all_events_log"] = [entry]
        state["last_system_result"] = {
            "log": "【判定】目星 成功（初回確定）",
            "action_id": "search",
            "target": "desk",
            "san_check": {"required": False},
            "transaction_id": txn,
        }
        state["last_processed_action_id"] = txn

        scenario_mgr = self._scenario_mgr()
        char_mgr = mock.Mock()
        char_mgr.characters = {}
        dice_engine = mock.Mock()
        state_mgr = mock.Mock()

        with mock.patch.object(main, "process_system_action") as proc:
            result = main.step_system_process(
                state, char_mgr, dice_engine, scenario_mgr, state_mgr, "pc_01", "テスト探索者",
            )
            proc.assert_not_called()

        self.assertTrue(result.get("idempotent_replay"))
        self.assertEqual(result.get("transaction_id"), txn)
        self.assertIn("初回確定", result.get("log", ""))
        # システムログを二重追加していない
        system_logs = [e for e in state["all_events_log"] if str(e.get("text", "")).startswith("システム:")]
        self.assertEqual(len(system_logs), 0)

    def test_step_system_process_commits_transaction_id(self):
        txn = "txn-commit-002"
        state = self._base_state(txn)
        entry = self._pending_entry(txn, processed=False)
        state["all_events_log"] = [entry]
        scenario_mgr = self._scenario_mgr()
        char_mgr = mock.Mock()
        char_mgr.characters = {}
        dice_engine = mock.Mock()
        state_mgr = mock.Mock()

        fake_result = {
            "log": "【判定】目星 成功。手紙を見つけた。",
            "action_id": "search",
            "target": "desk",
            "roll_type": "skill",
            "san_check": {"required": False},
            "kp_instruction": "描写せよ",
        }

        with mock.patch.object(main, "process_system_action", return_value=fake_result):
            with mock.patch.object(main, "_maybe_auto_resolve_san_check_after_action", side_effect=lambda *a, **k: a[-1]):
                with mock.patch.object(main, "apply_location_change_side_effects", return_value=False):
                    with mock.patch.object(main, "reset_stagnation_state_on_progress"):
                        result = main.step_system_process(
                            state, char_mgr, dice_engine, scenario_mgr, state_mgr,
                            "pc_01", "テスト探索者",
                        )

        self.assertEqual(state["last_processed_action_id"], txn)
        self.assertEqual(result.get("transaction_id"), txn)
        self.assertTrue(entry["meta"]["system_processed"])
        system_logs = [e for e in state["all_events_log"] if str(e.get("text", "")).startswith("システム:")]
        self.assertEqual(len(system_logs), 1)
        self.assertEqual(system_logs[0]["meta"].get("transaction_id"), txn)
        self.assertFalse(system_logs[0]["meta"].get("kp_narrated"))

    def test_second_call_after_commit_is_idempotent(self):
        txn = "txn-twice-003"
        state = self._base_state(txn)
        entry = self._pending_entry(txn, processed=False)
        state["all_events_log"] = [entry]
        scenario_mgr = self._scenario_mgr()
        char_mgr = mock.Mock()
        char_mgr.characters = {}
        char_mgr.active_pc_list = ["pc_01"]
        char_mgr.list_pc_ids.return_value = ["pc_01"]
        dice_engine = mock.Mock()
        state_mgr = mock.Mock()

        fake_result = {
            "log": "【判定】成功（1回目）",
            "action_id": "search",
            "target": "desk",
            "roll_type": "skill",
            "san_check": {"required": False},
        }
        call_count = {"n": 0}

        def _proc(*args, **kwargs):
            call_count["n"] += 1
            return dict(fake_result)

        with mock.patch.object(main, "process_system_action", side_effect=_proc):
            with mock.patch.object(main, "_maybe_auto_resolve_san_check_after_action", side_effect=lambda *a, **k: a[-1]):
                with mock.patch.object(main, "apply_location_change_side_effects", return_value=False):
                    first = main.step_system_process(
                        state, char_mgr, dice_engine, scenario_mgr, state_mgr,
                        "pc_01", "テスト探索者",
                    )
                    # 再実行（rerun 想定）: last_pl_action は残るが entry は processed
                    state["_pending_system_pl_entry"] = None
                    entry["meta"]["system_processed"] = True
                    second = main.step_system_process(
                        state, char_mgr, dice_engine, scenario_mgr, state_mgr,
                        "pc_01", "テスト探索者",
                    )

        self.assertEqual(call_count["n"], 1)
        self.assertFalse(first.get("idempotent_replay"))
        self.assertTrue(second.get("idempotent_replay"))
        self.assertEqual(state["last_processed_action_id"], txn)
        system_logs = [e for e in state["all_events_log"] if str(e.get("text", "")).startswith("システム:")]
        self.assertEqual(len(system_logs), 1)

    def test_actor_and_decision_owner_separated_on_combat_defense(self):
        txn = "txn-combat-004"
        state = self._base_state(txn)
        entry = self._pending_entry(txn)
        state["all_events_log"] = [entry]
        scenario_mgr = self._scenario_mgr()
        char_mgr = mock.Mock()
        char_mgr.characters = {}
        dice_engine = mock.Mock()
        state_mgr = mock.Mock()
        state_mgr.set_pending_combat_defense = mock.Mock()

        pending = {
            "attacker_id": "npc_ghoul",
            "defender_id": "pc_02",
            "attack_type": "melee",
        }
        fake_result = {
            "log": "【戦闘】攻撃が飛んできた。防衛選択が必要。",
            "action_id": "attack",
            "combat_defense_required": True,
            "pending_combat_defense": pending,
            "partial_log": "攻撃宣言",
            "san_check": {"required": False},
        }

        with mock.patch.object(main, "process_system_action", return_value=fake_result):
            result = main.step_system_process(
                state, char_mgr, dice_engine, scenario_mgr, state_mgr,
                "pc_01", "テスト探索者",
            )

        self.assertEqual(state["decision_owner_id"], "pc_02")
        self.assertEqual(state["actor_id"], "npc_ghoul")
        self.assertEqual(state["last_processed_action_id"], txn)
        self.assertEqual(result.get("transaction_id"), txn)

    def test_apply_pl_response_stamps_transaction_id(self):
        logs = []
        ai_data = {
            "should_speak": True,
            "speak_as": "PC",
            "pl_ooc_chat": "",
            "pc_action": {
                "dialogue": "机を調べる",
                "action": "search",
                "target": "desk",
                "skill": "目星",
                "message": "机を調べる",
            },
        }
        scenario_mgr = self._scenario_mgr()
        with mock.patch.object(main, "reconcile_pl_action", side_effect=lambda pc, *a, **k: pc):
            with mock.patch.object(main, "validate_completed_knott_talk", return_value={"ok": True}):
                with mock.patch.object(main, "validate_completed_dolly_talk", return_value={"ok": True}):
                    with mock.patch.object(main, "validate_force_ic_action", return_value={"ok": True}):
                        with mock.patch.object(main, "is_stale_nonprogress_talk", return_value=False):
                            with mock.patch.object(main, "is_stale_boston_globe_talk", return_value=False):
                                pc = main.apply_pl_response_to_logs(
                                    ai_data, "テスト", "study", logs,
                                    scenario_mgr=scenario_mgr,
                                    pc_id="pc_01",
                                )
        self.assertTrue(pc.get("transaction_id"))
        ic = [e for e in logs if (e.get("meta") or {}).get("needs_system")]
        self.assertEqual(len(ic), 1)
        self.assertEqual(ic[0]["meta"]["transaction_id"], pc["transaction_id"])
        self.assertEqual(ic[0]["meta"]["actor_id"], "pc_01")


if __name__ == "__main__":
    unittest.main()
