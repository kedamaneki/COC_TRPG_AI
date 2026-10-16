"""
停滞検知: 非進展累積・State Delta・重複計上・セーブ互換の回帰テスト。

LLM 通信なし。save_autosave.json / pcs.json / npcs.json には書き込まない。
実行: python test_stagnation_nonprogress_accumulation.py
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from CharacterManager import CharacterManager, knowledge_id_for_object
from DiceEngine import DiceEngine, SuccessLevel
from GameStateManager import GameStateManager
from ScenarioManager import ScenarioManager
import main as game_main


ROOT = Path(__file__).resolve().parent
CORBITT = ROOT / "scenario_corbitt.json"
NPCS = ROOT / "npcs.json"
SAVE = ROOT / "save_autosave.json"


def _fail_talk(target, *, tid="t1", actor="pc_01"):
    return {
        "status": 0,
        "action_id": "talk",
        "target": target,
        "roll_type": "social_talk",
        "blocked": False,
        "log": f"【対話】{target} と雑談した。",
        "transaction_id": tid,
        "actor_id": actor,
        "stagnation_candidate": True,
        "social": {"casual": True, "relationship_changed": False, "revealed_secrets": []},
    }


def _blocked_absent(target, *, tid="t2"):
    return {
        "status": 0,
        "action_id": "talk",
        "target": target,
        "roll_type": "blocked",
        "blocked": True,
        "log": f"【対話ブロック】その人物（{target}）は現在この場所にいません。",
        "transaction_id": tid,
        "stagnation_candidate": True,
    }


def _negotiate_fail(target, *, tid="t3", skill="説得"):
    return {
        "status": int(SuccessLevel.FAILURE),
        "action_id": "persuade",
        "target": target,
        "roll_type": "social_negotiate",
        "blocked": False,
        "log": f"【交渉】〈{skill}〉失敗",
        "transaction_id": tid,
        "stagnation_candidate": True,
        "social": {
            "casual": False,
            "skill": skill,
            "relationship_changed": False,
            "relationship_improved": False,
            "revealed_secrets": [],
        },
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        npc_src = NPCS if NPCS.exists() else None
        if npc_src:
            self.npc_path.write_text(npc_src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            self.npc_path.write_text("{}", encoding="utf-8")
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
                "skills": {"説得": 70, "目星": 65, "法律": 55},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "states": [],
            },
            "pc_02": {
                "profile": {"name": "エレノア教授", "is_npc": False},
                "attributes": {
                    "POW": 60, "INT": 80,
                    "SAN": {"current": 60, "max": 99, "session_start": 60},
                    "HP": {"current": 10, "max": 10},
                    "MP": {"current": 12, "max": 12},
                    "LUCK": 50,
                },
                "skills": {"説得": 40, "目星": 70},
                "known_knowledge_ids": [],
                "investigated_targets": [],
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.char_mgr.active_pcs = ["pc_01", "pc_02"]
        self.state_mgr = GameStateManager(self.char_mgr)
        if CORBITT.exists():
            self.scenario = ScenarioManager(copy.deepcopy(json.loads(CORBITT.read_text(encoding="utf-8"))))
        else:
            self.scenario = ScenarioManager({
                "scenario_meta": {"title": "t", "max_stagnation_turns": 6},
                "initial_state": {"location": "higher_courts_police_station", "flags": {}},
                "locations": {
                    "higher_courts_police_station": {
                        "name": "裁判所",
                        "objects": {},
                        "npcs_present": ["kim_deblanc"],
                        "connected_to": [{"id": "hall_of_records", "name": "公文書館"}],
                    },
                    "hall_of_records": {"name": "公文書館", "objects": {}, "connected_to": []},
                },
                "event_triggers": [],
            })
        self.scenario.location = "higher_courts_police_station"
        self.dice = DiceEngine()
        flags = self.scenario.flags
        snap = GameStateManager.build_progress_snapshot(
            flags,
            location_id=self.scenario.location,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
        )
        self.state_mgr.reset_stagnation_tracker(
            self.scenario.location, flags, progress_snapshot=snap,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _state(self, **extra):
        st = {
            "current_loc": self.scenario.location,
            "all_events_log": [],
            "active_pcs": ["pc_01", "pc_02"],
            "pl_id": "pc_01",
            "char_name": "マクガフィン刑事",
            "public_knowledge_ids": [],
            "last_pl_action": {"action": "talk", "target": "kim_deblanc", "skill": ""},
            "last_system_result": None,
            "pending_san_check": None,
        }
        st.update(extra)
        return st

    def _detect(self, result, *, pl_action=None, chat_only=False, tid=None):
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags,
            location_id=self.scenario.location,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
        )
        return self.state_mgr.detect_stagnation(
            [],
            location_id=self.scenario.location,
            flags=self.scenario.flags,
            max_stagnation_turns=self.scenario.get_max_stagnation_turns(),
            last_pl_action=pl_action or {"action": "talk", "target": result.get("target")},
            last_system_result=result,
            chat_only=chat_only,
            made_progress=False,
            progress_snapshot=snap,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
            transaction_id=tid or result.get("transaction_id"),
        )


class TestNonprogressAccumulation(_Base):
    def test_01_same_npc_nonprogress_talk_accumulates_to_threshold(self):
        last = None
        for i in range(6):
            last = self._detect(_fail_talk("kim_deblanc", tid=f"same-{i}"))
        self.assertEqual(last["streak"], 6)
        self.assertTrue(last["is_stagnant"])
        self.assertTrue(last["needs_intervention"])

    def test_02_alternating_npcs_still_accumulate(self):
        targets = ["kim_deblanc", "hall_records_clerk", "kim_deblanc", "globe_receptionist"]
        last = None
        for i, t in enumerate(targets):
            last = self._detect(_fail_talk(t, tid=f"alt-{i}"))
        self.assertEqual(last["streak"], 4)
        self.assertEqual(last["reason"], "nonprogress")

    def test_03_talk_fail_absent_do_not_reset_on_target_change(self):
        self._detect(_fail_talk("kim_deblanc", tid="a1"))
        self._detect(_negotiate_fail("kim_deblanc", tid="a2"))
        self._detect(_blocked_absent("npc_guard_01", tid="a3"))
        last = self._detect(_fail_talk("kim_deblanc", tid="a4"))
        self.assertEqual(last["streak"], 4)

    def test_04_pc_swap_still_accumulates(self):
        self._detect(_fail_talk("kim_deblanc", tid="p1", actor="pc_01"))
        last = self._detect(_fail_talk("kim_deblanc", tid="p2", actor="pc_02"))
        self.assertEqual(last["streak"], 2)

    def test_05_regrant_same_knowledge_does_not_reset(self):
        kid = knowledge_id_for_object("police_archives")
        self.char_mgr.grant_knowledge("pc_01", kid, target="police_archives", summary="資料8")
        # baseline snapshot after knowledge
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        self.state_mgr.reset_stagnation_tracker(
            self.scenario.location, self.scenario.flags, progress_snapshot=snap,
        )
        self._detect(_fail_talk("kim_deblanc", tid="rg1"))
        # 再付与（新規ではない）
        again = self.char_mgr.grant_knowledge(
            "pc_01", kid, target="police_archives", summary="資料8再表示",
        )
        self.assertFalse(again)
        result = {
            "status": 2,
            "action_id": "search",
            "target": "police_archives",
            "roll_type": "skill",
            "knowledge_grants": [{"knowledge_id": kid}],
            "log": "【成功】すでに知る内容を再確認した。",
            "transaction_id": "rg2",
            "stagnation_candidate": True,
        }
        last = self._detect(result)
        self.assertEqual(last["streak"], 2)
        self.assertNotEqual(last["reason"], "progress_or_moved")

    def test_06_reinvestigate_police_archives_does_not_reset(self):
        self.scenario.flags["higher_courts_records_accessed"] = True
        kid = knowledge_id_for_object("police_archives")
        self.char_mgr.grant_knowledge("pc_01", kid, target="police_archives", summary="プレイヤー資料8…")
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        self.state_mgr.reset_stagnation_tracker(
            self.scenario.location, self.scenario.flags, progress_snapshot=snap,
        )
        self._detect(_fail_talk("kim_deblanc", tid="ri1"))
        result = {
            "status": 2,
            "action_id": "search",
            "target": "police_archives",
            "roll_type": "blocked",
            "blocked": True,
            "log": "【調査済み】警察記録は閲覧済みです。プレイヤー資料8を再確認した。",
            "confirmed_fact": "プレイヤー資料8…",
            "transaction_id": "ri2",
            "stagnation_candidate": True,
        }
        last = self._detect(result)
        self.assertEqual(last["streak"], 2)

    def test_07_new_knowledge_resets(self):
        self._detect(_fail_talk("kim_deblanc", tid="nk1"))
        self._detect(_fail_talk("kim_deblanc", tid="nk2"))
        self.assertEqual(self.state_mgr.stagnation_tracker["streak"], 2)
        self.char_mgr.grant_knowledge(
            "pc_01", knowledge_id_for_object("desk"), target="desk", summary="新情報",
        )
        self.scenario.flags["desk_searched"] = True
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        last = self.state_mgr.detect_stagnation(
            [],
            location_id=self.scenario.location,
            flags=self.scenario.flags,
            max_stagnation_turns=6,
            last_system_result={"status": 2, "transaction_id": "nk3"},
            made_progress=False,
            progress_snapshot=snap,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
            transaction_id="nk3",
        )
        self.assertEqual(last["streak"], 0)
        self.assertEqual(last["reason"], "progress_or_moved")

    def test_08_real_move_resets_same_loc_move_does_not(self):
        self._detect(_fail_talk("kim_deblanc", tid="mv1"))
        # 移動失敗
        fail_move = {
            "status": 0,
            "action_id": "move",
            "target": "nowhere",
            "roll_type": "blocked",
            "blocked": True,
            "log": "【移動不可】その場所へは行けません。",
            "transaction_id": "mv2",
            "stagnation_candidate": True,
        }
        last = self._detect(fail_move)
        self.assertEqual(last["streak"], 2)
        # 実移動
        self.scenario.location = "hall_of_records"
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id="hall_of_records",
            char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        moved = self.state_mgr.detect_stagnation(
            [],
            location_id="hall_of_records",
            flags=self.scenario.flags,
            max_stagnation_turns=6,
            last_system_result={
                "status": 2, "action_id": "move", "location_changed": True,
                "new_location": "hall_of_records", "transaction_id": "mv3",
                "stagnation_progress": True,
            },
            made_progress=False,
            progress_snapshot=snap,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
            transaction_id="mv3",
        )
        self.assertEqual(moved["streak"], 0)
        self.assertEqual(moved["reason"], "progress_or_moved")

    def test_09_damage_san_admin_not_progress(self):
        prev = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01"],
        )
        pc = self.char_mgr.characters["pc_01"]
        pc["attributes"]["HP"]["current"] = 10
        pc["attributes"]["SAN"]["current"] = 50
        self.scenario.stagnation_counter = 99  # 管理用
        curr = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01"],
        )
        delta = GameStateManager.compute_state_delta(prev, curr)
        self.assertFalse(delta["has_progress"])

    def test_10_no_double_count_same_transaction(self):
        r = _fail_talk("kim_deblanc", tid="dup-1")
        a = self._detect(r, tid="dup-1")
        b = self._detect(r, tid="dup-1")
        self.assertEqual(a["streak"], 1)
        self.assertTrue(a["counted"])
        self.assertEqual(b["streak"], 1)
        self.assertTrue(b["skipped_duplicate"])
        self.assertFalse(b["counted"])

    def test_11_pending_luck_push_not_counted_until_resolved(self):
        state = self._state(
            last_system_result={
                "status": 0,
                "luck_decision_required": True,
                "action_id": "search",
                "target": "desk",
                "transaction_id": "pend-1",
            },
        )
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        out = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        self.assertIsNone(out)
        self.assertEqual(self.state_mgr.stagnation_tracker["streak"], 0)

        # 確定後
        state["last_system_result"] = {
            "status": 0,
            "action_id": "search",
            "target": "desk",
            "roll_type": "skill",
            "log": "失敗",
            "transaction_id": "pend-1",
            "stagnation_candidate": True,
            "blocked": False,
        }
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="luck_decision",
        )
        self.assertEqual(out2["streak"], 1)

    def test_12_kp_retry_and_same_transaction_do_not_increment(self):
        state = self._state(last_system_result=_fail_talk("kim_deblanc", tid="kp1"))
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        # kp_eval は対象外
        out = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="kp_eval",
        )
        self.assertIsNone(out)
        self.assertEqual(self.state_mgr.stagnation_tracker["streak"], 1)
        # 同一 transaction_id の再実行は増やさない
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        self.assertTrue(out2.get("skipped_duplicate"))
        self.assertEqual(out2["streak"], 1)
        # 別手番で同じ内容の雑談（新しい transaction_id）は加算する
        state["last_system_result"] = _fail_talk("kim_deblanc", tid="kp2")
        out3 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        self.assertEqual(out3["streak"], 2)
        self.assertTrue(out3.get("counted"))

    def test_13_ooc_chat_loop_detected(self):
        state = self._state(
            last_pl_action={"action": "wait", "target": "", "skill": "", "transaction_id": "w1"},
            last_system_result=None,
        )
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        for i in range(3):
            state["last_pl_action"] = {
                "action": "wait", "target": "", "skill": "", "transaction_id": f"w{i}",
            }
            state["all_events_log"] = list(state["all_events_log"]) + [
                {"text": f"(PL): 様子を見る {i}", "channel": "IC"},
            ]
            game_main.evaluate_and_apply_stagnation_intervention(
                state, managers, after_step="pl_speak",
            )
        self.assertGreaterEqual(self.state_mgr.stagnation_tracker["streak"], 3)

    def test_14_intervention_not_duplicated_until_streak_grows(self):
        state = self._state()
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        # 閾値まで上げる
        for i in range(6):
            state["last_system_result"] = _fail_talk("kim_deblanc", tid=f"iv-{i}")
            game_main.evaluate_and_apply_stagnation_intervention(
                state, managers, after_step="system_process",
            )
        self.assertTrue(state.get("last_stagnation_intervention"))
        intervened_at = self.state_mgr.stagnation_tracker["intervened_at_streak"]
        # 同じ streak では needs_intervention False
        state["last_system_result"] = _fail_talk("kim_deblanc", tid="iv-dup")
        # 強制的に同一 streak 再評価を避けるため新しい tid で +1
        out = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        # 7回目で再介入可
        self.assertGreaterEqual(out["streak"], 7)
        # 進展でヒント解除
        self.scenario.location = "hall_of_records"
        state["current_loc"] = "hall_of_records"
        state["stagnation_pl_hint"] = "古いヒント"
        state["force_ic_action"] = True
        state["last_system_result"] = {
            "status": 2,
            "action_id": "move",
            "location_changed": True,
            "new_location": "hall_of_records",
            "transaction_id": "iv-move",
            "stagnation_progress": True,
            "roll_type": "move",
        }
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        self.assertEqual(out2["streak"], 0)
        self.assertIsNone(state.get("stagnation_pl_hint"))
        self.assertFalse(state.get("force_ic_action"))

    def test_15_old_save_load_continues_without_bulk_replay(self):
        # 実行中に更新される save_autosave.json ではなく、旧形式trackerを
        # 現在の状態から組み立てて後方互換を決定論的に検証する。
        snapshot = GameStateManager.build_progress_snapshot(
            self.scenario.flags,
            location_id=self.scenario.location,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
        )
        legacy_tracker = {
            "location": self.scenario.location,
            "progress_signature": GameStateManager.signature_from_snapshot(snapshot),
            "streak": 0,
        }
        game_state_data = self.state_mgr.export_to_dict()
        game_state_data["stagnation_tracker"] = legacy_tracker
        save = {
            "game_state": game_state_data,
            "character_manager": self.char_mgr.export_to_dict(),
            "scenario_manager": self.scenario.export_to_dict(),
            "app_state": self._state(current_loc=self.scenario.location),
        }
        app_state = game_main.restore_from_save_data(
            save, self.state_mgr, self.char_mgr, self.scenario,
        )
        streak_after_load = int(self.state_mgr.stagnation_tracker.get("streak") or 0)
        # 保存値を根拠なく大きく補正しない（過少でもそのまま継続）
        self.assertLessEqual(streak_after_load, 3)
        before = streak_after_load
        state = self._state(
            current_loc=self.scenario.location,
            all_events_log=list(app_state.get("all_events_log") or []),
            last_system_result=_fail_talk("npc_guard_01", tid="post-load-1"),
        )
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        out = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        self.assertEqual(out["streak"], before + 1)

    def test_16_combat_and_san_skip_exploration_intervention(self):
        state = self._state(last_system_result=_fail_talk("kim_deblanc", tid="c1"))
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        self.state_mgr.in_combat = True
        self.assertIsNone(game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        ))
        self.state_mgr.in_combat = False
        state["pending_san_check"] = {"required": True, "value": 50}
        self.assertIsNone(game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        ))

    def test_save_pattern_reinvestigate_absent_chat_absent(self):
        """セーブ末尾付近の流れ: 調査済み→不在→別NPC雑談→再び不在。"""
        self.scenario.flags["higher_courts_records_accessed"] = True
        kid = knowledge_id_for_object("police_archives")
        self.char_mgr.grant_knowledge("pc_01", kid, target="police_archives", summary="資料8")
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        self.state_mgr.reset_stagnation_tracker(
            self.scenario.location, self.scenario.flags, progress_snapshot=snap,
        )
        seq = [
            {
                "status": 2, "action_id": "search", "target": "police_archives",
                "roll_type": "blocked", "blocked": True,
                "log": "調査済みの警察記録を再確認した。",
                "transaction_id": "s1", "stagnation_candidate": True,
            },
            _blocked_absent("npc_guard_01", tid="s2"),
            _fail_talk("kim_deblanc", tid="s3"),
            _blocked_absent("npc_guard_01", tid="s4"),
        ]
        last = None
        for r in seq:
            last = self._detect(r)
        self.assertEqual(last["streak"], 4)
        # 対象切替ではリセットされない
        self.assertNotEqual(last["reason"], "signature_switch")


class TestProgressMarkers(_Base):
    def test_success_alone_is_not_progress_marker(self):
        self.assertFalse(game_main._is_system_action_progress({
            "status": 2, "log": "【成功】特に新しい情報はない。", "roll_type": "skill",
        }))

    def test_knowledge_grants_list_alone_is_not_progress(self):
        # 旧実装は knowledge_grants 有無だけで True にしていた → 修正
        self.assertFalse(game_main._is_system_action_progress({
            "status": 0,
            "knowledge_grants": [{"knowledge_id": "object:desk"}],
        }))

    def test_social_talk_is_stagnation_candidate(self):
        self.assertTrue(game_main._is_system_action_stagnation(_fail_talk("kim")))

    def test_relationship_worsening_not_delta_progress(self):
        prev = GameStateManager.build_progress_snapshot(
            {}, location_id="x", char_mgr=self.char_mgr, active_pcs=["pc_01"],
        )
        # kim が居れば関係を悪化
        if "kim_deblanc" in self.char_mgr.characters:
            social = self.char_mgr.characters["kim_deblanc"].setdefault("session_social", {})
            social["relationship_status"] = "hostile"
        curr = GameStateManager.build_progress_snapshot(
            {}, location_id="x", char_mgr=self.char_mgr, active_pcs=["pc_01"],
        )
        delta = GameStateManager.compute_state_delta(prev, curr)
        # 初回観測はベースライン、悪化のみでは進展なし
        self.assertFalse(delta["has_progress"])

    def test_ooc_event_id_reeval_and_new_turn(self):
        """同一OOCの再評価は加算せず、別手番の同文OOCはそれぞれ加算する。"""
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        # 記録時点で ID 付与（評価では発行しない）
        action1 = {"action": "wait", "target": "", "skill": "", "dialogue": ""}
        tid1 = game_main.ensure_settled_nonprogress_event_id(action1, event_kind="ooc_chat")
        state = self._state(last_pl_action=action1, last_system_result=None)
        out1 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertEqual(out1["streak"], 1)
        self.assertEqual(action1["transaction_id"], tid1)
        # 同一イベント再評価
        out1b = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertTrue(out1b.get("skipped_duplicate"))
        self.assertEqual(out1b["streak"], 1)
        self.assertEqual(action1["transaction_id"], tid1)
        # 別手番・同文
        action2 = {"action": "wait", "target": "", "skill": "", "dialogue": ""}
        tid2 = game_main.ensure_settled_nonprogress_event_id(action2, event_kind="ooc_chat")
        self.assertNotEqual(tid1, tid2)
        state["last_pl_action"] = action2
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertEqual(out2["streak"], 2)
        self.assertTrue(out2.get("counted"))

    def test_validation_reject_id_reeval_and_new_reject(self):
        """同一検証拒否の再評価は加算せず、新規生成の再拒否は加算する。"""
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        reject1 = {
            "action": "talk",
            "target": "npc_guard_01",
            "skill": "",
            "needs_pl_retry": True,
            "validation_error_code": "absent_npc_talk",
            "validation_error": "【対話ブロック】いません",
        }
        tid1 = game_main.ensure_settled_nonprogress_event_id(
            reject1, event_kind="validation_reject",
        )
        state = self._state(last_pl_action=reject1, last_system_result=None)
        out1 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertEqual(out1["streak"], 1)
        out1b = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertTrue(out1b.get("skipped_duplicate"))
        self.assertEqual(out1b["streak"], 1)
        self.assertEqual(reject1["transaction_id"], tid1)
        # 新しく生成された行動が再び拒否
        reject2 = {
            "action": "talk",
            "target": "npc_guard_01",
            "skill": "",
            "needs_pl_retry": True,
            "validation_error_code": "absent_npc_talk",
            "validation_error": "【対話ブロック】いません",
        }
        tid2 = game_main.ensure_settled_nonprogress_event_id(
            reject2, event_kind="validation_reject",
        )
        self.assertNotEqual(tid1, tid2)
        state["last_pl_action"] = reject2
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertEqual(out2["streak"], 2)
        self.assertTrue(out2.get("counted"))

    def test_save_load_does_not_double_count_settled_event(self):
        """セーブ／ロード後も、確定済みイベントを重複計上しない。"""
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        action = {"action": "wait", "target": "", "skill": ""}
        tid = game_main.ensure_settled_nonprogress_event_id(action, event_kind="ooc_chat")
        state = self._state(last_pl_action=action, last_system_result=None)
        out1 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertEqual(out1["streak"], 1)
        # セーブ相当: tracker + last_pl_action をコピー復元
        saved_tracker = copy.deepcopy(self.state_mgr.stagnation_tracker)
        saved_action = copy.deepcopy(action)
        self.assertEqual(saved_action["transaction_id"], tid)
        self.assertEqual(saved_tracker.get("last_eval_transaction_id"), tid)
        # ロード相当
        self.state_mgr.stagnation_tracker = self.state_mgr._default_stagnation_tracker()
        self.state_mgr.stagnation_tracker.update(saved_tracker)
        self.state_mgr._ensure_stagnation_tracker_shape()
        state2 = self._state(last_pl_action=saved_action, last_system_result=None)
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state2, managers, after_step="pl_speak",
        )
        self.assertTrue(out2.get("skipped_duplicate"))
        self.assertEqual(out2["streak"], 1)
        self.assertEqual(saved_action["transaction_id"], tid)

    def test_needs_pl_retry_counts_without_system_blocked(self):
        """SYSTEM に到達しない検証拒否も pl_speak で累積する。"""
        state = self._state(
            last_pl_action={
                "action": "talk",
                "target": "npc_guard_01",
                "skill": "",
                "needs_pl_retry": True,
                "validation_error_code": "absent_npc_talk",
                "validation_error": "【対話ブロック】いません",
                "transaction_id": "retry-1",
            },
            last_system_result=None,
        )
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        out = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["streak"], 1)
        self.assertEqual(out["reason"], "invalid_loop")
        self.assertEqual(out["cause"], "discussion_loop")
        # 別手番の再拒否も加算
        state["last_pl_action"] = {
            "action": "talk",
            "target": "npc_guard_01",
            "skill": "",
            "needs_pl_retry": True,
            "validation_error_code": "absent_npc_talk",
            "transaction_id": "retry-2",
        }
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="pl_speak",
        )
        self.assertEqual(out2["streak"], 2)

    def test_push_and_parent_count_once_with_different_ids(self):
        """別IDのプッシュ結果と親行動は合わせて一度だけ計上する。"""
        managers = (self.char_mgr, self.dice, self.state_mgr, self.scenario)
        parent_tid = "parent-search-001"
        child_tid = "push-child-002"
        self.assertNotEqual(parent_tid, child_tid)

        # 親失敗＋プッシュ待ち → 未確定のため加算しない
        pending_result = {
            "status": 0,
            "action_id": "search",
            "target": "desk",
            "roll_type": "skill",
            "log": "失敗（プッシュ判断待ち）",
            "transaction_id": parent_tid,
            "stagnation_transaction_id": parent_tid,
            "push_decision_required": True,
            "pending_push_roll": {
                "skill_name": "目星",
                "original_action": "search",
                "target": "desk",
                "parent_transaction_id": parent_tid,
                "decision_pending": True,
            },
            "stagnation_candidate": True,
        }
        state = self._state(
            last_pl_action={"action": "search", "target": "desk", "skill": "目星",
                            "transaction_id": parent_tid},
            last_system_result=pending_result,
        )
        out_pending = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="system_process",
        )
        self.assertIsNone(out_pending)
        self.assertEqual(self.state_mgr.stagnation_tracker["streak"], 0)

        # プッシュ確定（子は別ID）→ 親IDで1回だけ加算
        push_final = game_main.bind_push_family_transaction_ids(
            {
                "status": 0,
                "action_id": "search",
                "target": "desk",
                "roll_type": "skill",
                "log": "プッシュ失敗",
                "stagnation_candidate": True,
                "blocked": False,
            },
            {"parent_transaction_id": parent_tid, "original_action": "search"},
            parent_transaction_id=parent_tid,
            child_transaction_id=child_tid,
        )
        self.assertEqual(push_final["transaction_id"], child_tid)
        self.assertEqual(push_final["parent_transaction_id"], parent_tid)
        self.assertEqual(push_final["stagnation_transaction_id"], parent_tid)

        state["last_system_result"] = push_final
        out1 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="push_decision",
        )
        self.assertEqual(out1["streak"], 1)
        self.assertTrue(out1.get("counted"))
        self.assertEqual(
            self.state_mgr.stagnation_tracker.get("last_eval_transaction_id"),
            parent_tid,
        )

        # 子IDで再評価しても加算しない
        state["last_system_result"] = dict(push_final)
        out2 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="push_decision",
        )
        self.assertTrue(out2.get("skipped_duplicate"))
        self.assertEqual(out2["streak"], 1)

        # 親IDキーでも再評価しない
        out3 = self.state_mgr.detect_stagnation(
            [],
            location_id=self.scenario.location,
            flags=self.scenario.flags,
            max_stagnation_turns=6,
            last_system_result=push_final,
            made_progress=False,
            progress_snapshot=GameStateManager.build_progress_snapshot(
                self.scenario.flags, location_id=self.scenario.location,
                char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
            ),
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
            transaction_id=child_tid,
        )
        self.assertTrue(out3.get("skipped_duplicate"))
        self.assertEqual(out3["streak"], 1)

        # 別の親行動なら加算
        other = game_main.bind_push_family_transaction_ids(
            {
                "status": 0, "action_id": "search", "target": "shelf",
                "roll_type": "skill", "log": "失敗", "stagnation_candidate": True,
            },
            parent_transaction_id="parent-search-003",
            child_transaction_id="push-child-004",
        )
        state["last_system_result"] = other
        out4 = game_main.evaluate_and_apply_stagnation_intervention(
            state, managers, after_step="push_decision",
        )
        self.assertEqual(out4["streak"], 2)

    def test_resolve_stagnation_transaction_id_prefers_parent(self):
        tid = game_main.resolve_stagnation_transaction_id(
            {
                "transaction_id": "child",
                "parent_transaction_id": "parent",
                "stagnation_transaction_id": "parent",
            }
        )
        self.assertEqual(tid, "parent")

    def test_push_failure_flag_does_not_reset_stagnation(self):
        """失敗記録フラグ push_failure_dire_outcome は進展にしない。"""
        self.assertFalse(
            GameStateManager.is_scenario_progress_flag("push_failure_dire_outcome")
        )
        self.assertTrue(
            GameStateManager.is_scenario_progress_flag("higher_courts_records_accessed")
        )
        self._detect(_fail_talk("kim_deblanc", tid="pf1"))
        self._detect(_fail_talk("kim_deblanc", tid="pf2"))
        self.assertEqual(self.state_mgr.stagnation_tracker["streak"], 2)
        # 失敗フラグだけ立つ
        self.scenario.flags["push_failure_dire_outcome"] = True
        snap = GameStateManager.build_progress_snapshot(
            self.scenario.flags, location_id=self.scenario.location,
            char_mgr=self.char_mgr, active_pcs=["pc_01", "pc_02"],
        )
        self.assertNotIn("push_failure_dire_outcome", snap.get("flags_true") or ())
        last = self.state_mgr.detect_stagnation(
            [],
            location_id=self.scenario.location,
            flags=self.scenario.flags,
            max_stagnation_turns=6,
            last_system_result=_fail_talk("kim_deblanc", tid="pf3"),
            made_progress=False,
            progress_snapshot=snap,
            char_mgr=self.char_mgr,
            active_pcs=["pc_01", "pc_02"],
            transaction_id="pf3",
        )
        self.assertEqual(last["streak"], 3)
        self.assertNotEqual(last["reason"], "progress_or_moved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
