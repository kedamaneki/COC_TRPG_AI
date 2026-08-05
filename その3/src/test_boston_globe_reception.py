"""
ボストン・グローブ: 受付経由でアーティ紹介してから対話可能にする。
実行: python test_boston_globe_reception.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from ScenarioManager import ScenarioManager
from NPCSocialManager import find_npc_id_by_target, format_npc_directory_for_pl, npc_is_available
import main as game_main


CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"
NPCS = Path(__file__).resolve().parent / "npcs.json"


class TestBostonGlobeReceptionGate(unittest.TestCase):
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
                "skills": {"目星": 65, "説得": 50},
                "states": [],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.scenario = ScenarioManager(json.loads(json.dumps(self.scenario_data)))
        self.scenario.location = "boston_globe"
        self.scenario.flags["artie_introduced"] = False
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_npcs_present_and_artie_not_object(self):
        loc = self.scenario.get_location_info("boston_globe")
        self.assertIn("globe_receptionist", loc.get("npcs_present") or [])
        self.assertIn("artie_wilmott", loc.get("npcs_present") or [])
        self.assertNotIn("artie_wilmott", loc.get("objects") or {})
        self.assertIn("globe_receptionist", self.char_mgr.characters)
        self.assertIn("artie_wilmott", self.char_mgr.characters)

    def test_find_reception_aliases(self):
        self.assertEqual(find_npc_id_by_target(self.char_mgr, "受付"), "globe_receptionist")
        self.assertEqual(find_npc_id_by_target(self.char_mgr, "reception_desk"), "globe_receptionist")
        self.assertEqual(find_npc_id_by_target(self.char_mgr, "アーティ氏"), "artie_wilmott")

    def test_artie_blocked_before_reception(self):
        self.assertFalse(npc_is_available(self.char_mgr, "artie_wilmott", self.scenario.flags))
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "アーティ・ウィルモット", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertTrue(result.get("blocked"))
        self.assertFalse(self.scenario.flags.get("artie_introduced"))
        self.assertIn("受付", result.get("log", ""))

    def test_reception_talk_introduces_artie(self):
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "受付", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertIn(result.get("roll_type"), ("social_talk", "social_negotiate"))
        self.assertTrue(self.scenario.flags.get("artie_introduced"))
        self.assertTrue(npc_is_available(self.char_mgr, "artie_wilmott", self.scenario.flags))

        follow = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "talk", "アーティ", "",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertFalse(follow.get("blocked"))
        self.assertEqual(follow.get("roll_type"), "social_talk")

    def test_pl_directory_hides_artie_until_introduced(self):
        text = format_npc_directory_for_pl(
            self.char_mgr, current_loc="boston_globe", flags=self.scenario.flags,
        )
        self.assertIn("globe_receptionist", text)
        self.assertIn("未紹介", text)
        self.scenario.flags["artie_introduced"] = True
        text2 = format_npc_directory_for_pl(
            self.char_mgr, current_loc="boston_globe", flags=self.scenario.flags,
        )
        self.assertIn("artie_wilmott", text2)
        self.assertNotIn("未紹介", text2)

    def test_recommended_action_prefers_reception(self):
        rec = game_main._build_pl_recommended_action(self.scenario, "boston_globe")
        self.assertIn("globe_receptionist", rec)
        self.scenario.flags["artie_introduced"] = True
        rec2 = game_main._build_pl_recommended_action(self.scenario, "boston_globe")
        self.assertIn("artie_wilmott", rec2)

    def test_search_desk_remapped_to_talk(self):
        fixed = game_main.reconcile_pl_action(
            {
                "action": "search",
                "target": "reception_desk",
                "skill": "目星",
                "dialogue": "この受付デスク、少し調べてみるか。",
            },
            "PC", "", self.scenario, "boston_globe", char_mgr=self.char_mgr,
        )
        self.assertEqual(fixed["action"], "talk")
        self.assertEqual(fixed["target"], "globe_receptionist")

    def test_ref_room_dialogue_not_move_to_hall_of_records(self):
        """セーブで起きた誤り: 資料室と言いながら公文書館へ move → 拒否して PL 再生成。"""
        fixed = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "hall_of_records",
                "skill": "",
                "dialogue": "次は参考資料室の切り抜きファイルを調べるよ。古い記事も見つけられるかもしれないな。",
            },
            "PC", "", self.scenario, "boston_globe", char_mgr=self.char_mgr,
        )
        self.assertTrue(fixed.get("needs_pl_retry"))
        self.assertTrue(fixed.get("validation_error"))
        self.assertNotEqual(fixed.get("action"), "move")
        suggested = fixed.get("suggested_fix") or {}
        self.assertEqual(suggested.get("action"), "talk")
        self.assertEqual(suggested.get("target"), "globe_receptionist")

    def test_clipping_files_blocked_before_intro(self):
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "search", "reference_room_clipping_files", "目星",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertTrue(result.get("blocked"))
        self.assertIn("アクセス", result.get("log", ""))
        self.assertIn("導入", result.get("log", ""))

    def test_clipping_files_blocked_after_intro_without_permission(self):
        self.scenario.flags["artie_introduced"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "search", "reference_room_clipping_files", "目星",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertTrue(result.get("blocked"))
        self.assertIn("アクセス", result.get("log", ""))
        self.assertIn("artie_wilmott", result.get("log", ""))

    def test_clipping_files_allowed_when_access_flag_set(self):
        self.scenario.flags["artie_introduced"] = True
        self.scenario.flags["artie_reference_room_access_granted"] = True
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "search", "reference_room_clipping_files", "目星",
            "boston_globe", self.char_mgr, self.dice, self.scenario,
        )
        self.assertFalse(result.get("blocked"))


if __name__ == "__main__":
    unittest.main()
