"""
タスク6: State Delta に基づく停滞検知の単体テスト。

実行:
  python test_stagnation_state_delta.py
"""
from __future__ import annotations

import unittest

from ActionValidator import (
    build_reason_stagnation_hint,
    build_discussion_loop_hint,
    list_reachable_uninvestigated_for_pc,
)
from GameStateManager import GameStateManager
import main


class FakeCharMgr:
    def __init__(self):
        self.characters = {
            "pc_01": {
                "profile": {"name": "A", "is_npc": False},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "knowledge_notes": {},
            },
            "pc_02": {
                "profile": {"name": "B", "is_npc": False},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "knowledge_notes": {},
            },
            "npc_clerk": {
                "profile": {"name": "受付", "is_npc": True},
                "session_social": {"relationship_status": "neutral", "revealed_secrets": []},
            },
        }
        self.active_pcs = ["pc_01", "pc_02"]

    @property
    def active_pc_list(self):
        return list(self.active_pcs)

    def list_pc_ids(self):
        return ["pc_01", "pc_02"]

    def ensure_knowledge_context(self, char_id):
        return self.characters.get(char_id)

    def get_known_knowledge_ids(self, char_id):
        char = self.characters.get(char_id) or {}
        return list(char.get("known_knowledge_ids") or [])

    def get_pc_investigated_targets(self, char_id):
        char = self.characters.get(char_id) or {}
        return set(char.get("investigated_targets") or [])

    def grant_knowledge(self, char_id, knowledge_id, *, target=None, summary="", mark_investigated=True):
        char = self.characters[char_id]
        known = char.setdefault("known_knowledge_ids", [])
        if knowledge_id not in known:
            known.append(knowledge_id)
        if mark_investigated and target:
            inv = char.setdefault("investigated_targets", [])
            if target not in inv:
                inv.append(target)
        return True


class FakeScenario:
    def __init__(self):
        self.location = "study"
        self.flags = {"investigated_targets": []}
        self._objects = {
            "desk": {
                "name": "机",
                "purpose": "引き出しがある",
                "usable_actions": ["search"],
                "investigated_flag": "desk_searched",
            },
            "shelf": {
                "name": "棚",
                "purpose": "本が並ぶ",
                "usable_actions": ["search", "inspect"],
            },
            "hidden_trap": {
                "name": "隠し罠",
                "purpose": "発見前は見えない",
                "usable_actions": ["search"],
                "requires_flag": "found_trap",
            },
        }

    def get_location_info(self, loc=None):
        return {"name": "書斎", "objects": dict(self._objects)}

    def get_object_info(self, loc, oid):
        return dict(self._objects.get(oid) or {})

    def get_available_exits(self, loc=None):
        return [{"id": "hallway", "name": "廊下"}]

    def _is_research_reopened(self, target):
        return False


class TestStateDelta(unittest.TestCase):
    def test_compute_delta_flags_and_location(self):
        prev = GameStateManager.build_progress_snapshot(
            {"door_opened": False, "investigated_targets": []},
            location_id="study",
        )
        curr = GameStateManager.build_progress_snapshot(
            {"door_opened": True, "investigated_targets": ["desk"]},
            location_id="hallway",
        )
        # False→True と location 変化
        delta = GameStateManager.compute_state_delta(prev, curr)
        self.assertTrue(delta["has_progress"])
        self.assertTrue(delta["location_changed"])
        self.assertIn("door_opened", delta["new_flags"])
        self.assertIn("desk", delta["new_investigated"])
        self.assertIn("location", delta["progress_kinds"])
        self.assertIn("flags", delta["progress_kinds"])

    def test_knowledge_gain_resets_stagnation(self):
        char_mgr = FakeCharMgr()
        gsm = GameStateManager(char_mgr)
        flags = {"investigated_targets": []}
        snap0 = GameStateManager.build_progress_snapshot(
            flags, location_id="study", char_mgr=char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        gsm.reset_stagnation_tracker("study", flags, progress_snapshot=snap0)

        # 失敗を重ねてストリークを上げる
        fail = {"status": 0, "action_id": "search", "target": "desk", "log": "失敗", "blocked": False, "roll_type": "skill"}
        d = None
        for _ in range(3):
            d = gsm.detect_stagnation(
                [],
                location_id="study",
                flags=flags,
                max_stagnation_turns=6,
                last_system_result=fail,
                made_progress=False,
                progress_snapshot=GameStateManager.build_progress_snapshot(
                    flags, location_id="study", char_mgr=char_mgr, active_pcs=["pc_01"],
                ),
                char_mgr=char_mgr,
                active_pcs=["pc_01"],
            )
        self.assertGreaterEqual(d["streak"], 3)

        # 知識獲得 → リセット
        char_mgr.grant_knowledge("pc_01", "object:desk", target="desk", summary="机のメモ")
        flags = {"investigated_targets": ["desk"], "desk_searched": True}
        snap1 = GameStateManager.build_progress_snapshot(
            flags, location_id="study", char_mgr=char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        d2 = gsm.detect_stagnation(
            [],
            location_id="study",
            flags=flags,
            max_stagnation_turns=6,
            last_system_result={"status": 2, "stagnation_progress": True, "knowledge_grants": [{"knowledge_id": "object:desk"}]},
            made_progress=True,
            progress_snapshot=snap1,
            char_mgr=char_mgr,
            active_pcs=["pc_01", "pc_02"],
        )
        self.assertEqual(d2["streak"], 0)
        self.assertEqual(d2["reason"], "progress_or_moved")

    def test_npc_relationship_delta(self):
        char_mgr = FakeCharMgr()
        prev = GameStateManager.build_progress_snapshot(
            {}, location_id="globe", char_mgr=char_mgr, active_pcs=["pc_01"],
        )
        char_mgr.characters["npc_clerk"]["session_social"]["relationship_status"] = "friendly"
        curr = GameStateManager.build_progress_snapshot(
            {}, location_id="globe", char_mgr=char_mgr, active_pcs=["pc_01"],
        )
        delta = GameStateManager.compute_state_delta(prev, curr)
        self.assertTrue(delta["has_progress"])
        self.assertIn("npc_relationship", delta["progress_kinds"])

    def test_repeat_fail_without_delta_increments(self):
        gsm = GameStateManager(FakeCharMgr())
        flags = {"investigated_targets": []}
        snap = GameStateManager.build_progress_snapshot(flags, location_id="study")
        gsm.reset_stagnation_tracker("study", flags, progress_snapshot=snap)
        fail = {
            "status": 0, "action_id": "search", "target": "desk",
            "log": "すでに調査済みです", "roll_type": "blocked", "blocked": True,
        }
        last = None
        for _ in range(2):
            last = gsm.detect_stagnation(
                [],
                location_id="study",
                flags=flags,
                max_stagnation_turns=3,
                last_system_result=fail,
                made_progress=False,
                progress_snapshot=snap,
            )
        self.assertEqual(last["streak"], 2)
        self.assertEqual(last["cause"], "repeat_investigated")
        self.assertFalse(last["needs_intervention"])

        last = gsm.detect_stagnation(
            [],
            location_id="study",
            flags=flags,
            max_stagnation_turns=3,
            last_system_result=fail,
            made_progress=False,
            progress_snapshot=snap,
        )
        self.assertEqual(last["streak"], 3)
        self.assertTrue(last["needs_intervention"])
        self.assertEqual(last["cause"], "repeat_investigated")

    def test_is_system_action_progress_includes_knowledge(self):
        # knowledge_grants リストの存在だけでは進展にしない（本文再付与対策）
        self.assertFalse(main._is_system_action_progress({
            "status": 0,
            "knowledge_grants": [{"knowledge_id": "object:desk", "scope": "private"}],
        }))
        # 実際に新規付与された場合のみ
        self.assertTrue(main._is_system_action_progress({
            "status": 0,
            "knowledge_actually_new": True,
        }))
        # 関係改善フラグ付き
        self.assertTrue(main._is_system_action_progress({
            "status": 2,
            "social": {"relationship_changed": True, "relationship_improved": True},
        }))
        # 変化しても改善でなければ進展マーカーにしない
        self.assertFalse(main._is_system_action_progress({
            "status": 2,
            "social": {"relationship_changed": True, "relationship_improved": False},
        }))

    def test_reason_hints_do_not_leak_hidden(self):
        scenario = FakeScenario()
        char_mgr = FakeCharMgr()
        # desk は pc 調査済み → 候補に出ない
        char_mgr.characters["pc_01"]["investigated_targets"] = ["desk"]
        candidates = list_reachable_uninvestigated_for_pc(
            scenario, "study", char_mgr=char_mgr, pl_id="pc_01",
        )
        joined = " ".join(candidates)
        self.assertIn("shelf", joined)
        self.assertNotIn("hidden_trap", joined)
        self.assertNotIn("desk", joined)

        hint = build_reason_stagnation_hint(
            "repeat_investigated",
            scenario,
            "study",
            char_mgr=char_mgr,
            pl_id="pc_01",
            repeat_key=("blocked", "search", "desk"),
        )
        self.assertIn("既調査", hint)
        self.assertIn("shelf", hint)
        self.assertNotIn("hidden_trap", hint)

        d_hint = build_discussion_loop_hint()
        self.assertIn("作戦会議", d_hint)

    def test_classify_discussion_loop(self):
        cause = GameStateManager.classify_stagnation_cause("chat_only", ("chat",))
        self.assertEqual(cause, "discussion_loop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
