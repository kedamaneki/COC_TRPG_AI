# -*- coding: utf-8 -*-
"""コービット外観: 入口優先・近所往復防止の回帰テスト。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ActionValidator import (
    build_forced_progress_action,
    is_corbitt_approach_pingpong_move,
    is_location_investigation_exhausted,
    pick_corbitt_exterior_entry_action,
    pick_forced_progress_move_target,
)
from CharacterManager import CharacterManager
from DiceEngine import DiceEngine, SuccessLevel
from GameStateManager import GameStateManager
from ScenarioManager import ScenarioManager
import main as game_main

CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"
NPCS = Path(__file__).resolve().parent / "npcs.json"


class TestCorbittExteriorEntryBreakout(unittest.TestCase):
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
                            "STR": 60,
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

    def _mark_exterior_searched(self):
        self.scenario.flags["corbitt_house_examined"] = True
        self.scenario.flags["front_door_investigated"] = True
        self.scenario.flags["ground_floor_windows_investigated"] = True
        inv = set(self.scenario.flags.get("investigated_targets") or [])
        inv.update({"corbitt_house", "front_door", "exterior_windows"})
        self.scenario.flags["investigated_targets"] = sorted(inv)

    def test_examined_unentered_recommends_entry_not_search_or_neighborhood(self):
        """外観・未入館・屋敷調査済み → use/break/force + corbitt_house。"""
        self._mark_exterior_searched()
        self.scenario.flags["corbitt_house_entered"] = False
        rec = game_main._build_pl_recommended_action(self.scenario, "corbitt_exterior")
        self.assertIn("corbitt_house", rec)
        self.assertRegex(rec, r"action:\s*(use|break|force)")
        self.assertNotIn("action: search", rec)
        self.assertNotIn("the_neighborhood", rec)

        entry = pick_corbitt_exterior_entry_action(self.scenario)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("target"), "corbitt_house")
        self.assertIn(entry.get("action"), ("use", "break", "force"))

        forced = build_forced_progress_action(self.scenario, "corbitt_exterior")
        self.assertIsNotNone(forced)
        self.assertEqual(forced.get("target"), "corbitt_house")
        self.assertIn(forced.get("action"), ("use", "break", "force"))
        self.assertNotEqual(forced.get("action"), "move")

        move = pick_forced_progress_move_target(self.scenario, "corbitt_exterior")
        self.assertNotEqual(move, "the_neighborhood")

    def test_entered_prefers_ground_floor_move(self):
        """入口を開いた後は corbitt_ground_floor への move を優先。"""
        self._mark_exterior_searched()
        self.scenario.flags["corbitt_house_entered"] = True
        self.scenario.flags["front_door_unlocked"] = True

        rec = game_main._build_pl_recommended_action(self.scenario, "corbitt_exterior")
        self.assertIn("corbitt_ground_floor", rec)
        self.assertIn("move", rec)

        forced = build_forced_progress_action(self.scenario, "corbitt_exterior")
        self.assertEqual(forced.get("action"), "move")
        self.assertEqual(forced.get("target"), "corbitt_ground_floor")

        move = pick_forced_progress_move_target(self.scenario, "corbitt_exterior")
        self.assertEqual(move, "corbitt_ground_floor")

    def test_entry_action_succeeds_and_failure_allows_retry(self):
        """入口行動がイベントまで通り、失敗後も再試行できる。"""
        self._mark_exterior_searched()
        self.scenario.flags["corbitt_house_entered"] = False

        block = self.scenario.evaluate_pre_action_guard(
            "use", "corbitt_house", "corbitt_exterior",
        )
        self.assertIsNone(block)

        fail = self.scenario.process_action(
            "use", "corbitt_house", int(SuccessLevel.FAILURE),
        )
        self.assertFalse(self.scenario.flags.get("corbitt_house_entered"))
        self.assertIsNotNone(fail)

        # 失敗後もブロックされない
        block2 = self.scenario.evaluate_pre_action_guard(
            "use", "corbitt_house", "corbitt_exterior",
        )
        self.assertIsNone(block2)

        ok = self.scenario.process_action(
            "use", "corbitt_house", int(SuccessLevel.REGULAR_SUCCESS),
        )
        self.assertTrue(self.scenario.flags.get("corbitt_house_entered"))
        self.assertTrue(self.scenario.flags.get("front_door_unlocked"))
        self.assertIn("入口", (ok.get("system_log") or ""))

        # process_system_action 経由でも成功する
        self.scenario.flags["corbitt_house_entered"] = False
        self.scenario.flags["front_door_unlocked"] = False
        dice = DiceEngine()
        state_mgr = GameStateManager(self.char_mgr)
        with mock.patch.object(dice, "execute_skill_roll", side_effect=AssertionError("no skill")):
            # use は required_check 無し → 自動成功経路
            result = game_main.process_system_action(
                "pc_01", "マクガフィン刑事",
                "use", "corbitt_house", "",
                "corbitt_exterior",
                self.char_mgr, dice, self.scenario,
                None, state_mgr, None,
            )
        self.assertTrue(self.scenario.flags.get("corbitt_house_entered"))
        self.assertFalse(result.get("blocked"))

    def test_neighborhood_exterior_pingpong_not_forced_and_not_progress(self):
        """近所↔外観の強制往復を再発させない。"""
        self._mark_exterior_searched()
        self.scenario.flags["corbitt_house_entered"] = False

        # 外観からは近所へ強制しない
        forced_ext = build_forced_progress_action(self.scenario, "corbitt_exterior")
        self.assertNotEqual(
            (forced_ext or {}).get("action"), "move",
        )
        self.assertNotEqual((forced_ext or {}).get("target"), "the_neighborhood")

        # 近所からは外観へ向かうのは可（片道）
        self.scenario.location = "the_neighborhood"
        forced_nb = build_forced_progress_action(self.scenario, "the_neighborhood")
        self.assertEqual((forced_nb or {}).get("action"), "move")
        self.assertEqual((forced_nb or {}).get("target"), "corbitt_exterior")

        self.assertTrue(
            is_corbitt_approach_pingpong_move("the_neighborhood", "corbitt_exterior")
        )
        self.assertTrue(
            is_corbitt_approach_pingpong_move("corbitt_exterior", "the_neighborhood")
        )
        self.assertFalse(
            is_corbitt_approach_pingpong_move("corbitt_exterior", "corbitt_ground_floor")
        )

        # 停滞: 往復だけでは streak リセットしない
        state_mgr = GameStateManager(self.char_mgr)
        snap_nb = state_mgr.build_progress_snapshot(
            flags=dict(self.scenario.flags),
            location_id="the_neighborhood",
        )
        state_mgr.stagnation_tracker.update({
            "location": "the_neighborhood",
            "progress_snapshot": snap_nb,
            "streak": 3,
            "last_reason": "chat_only",
        })
        det = state_mgr.detect_stagnation(
            location_id="corbitt_exterior",
            flags=dict(self.scenario.flags),
            max_stagnation_turns=6,
            chat_only=True,
            transaction_id="pingpong-1",
        )
        self.assertNotEqual(det.get("reason"), "progress_or_moved")
        self.assertGreaterEqual(int(det.get("streak") or 0), 3)

        # 他ロケ強制進行は壊さない（チャペル床板）
        self.scenario.location = "chapel_of_contemplation"
        self.scenario.flags.update({
            "in_basement": False,
            "symbol_investigated": True,
            "chapel_investigated": True,
            "floorboards_examined": True,
            "investigated_targets": [
                "white_symbol", "chapel_secret_cellar", "rotting_floorboards",
            ],
        })
        chapel = build_forced_progress_action(self.scenario, "chapel_of_contemplation")
        self.assertEqual((chapel or {}).get("action"), "break")
        self.assertEqual((chapel or {}).get("target"), "rotting_floorboards")

    def test_exterior_not_exhausted_while_entry_pending(self):
        self._mark_exterior_searched()
        self.scenario.flags["corbitt_house_entered"] = False
        self.assertFalse(
            is_location_investigation_exhausted(self.scenario, "corbitt_exterior")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
