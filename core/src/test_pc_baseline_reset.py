# -*- coding: utf-8 -*-
"""シナリオ開始時の baseline 復元テスト。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from CharacterManager import CharacterManager


class TestPcBaselineReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.npc_path.write_text("{}", encoding="utf-8")
        self.pc_path.write_text(json.dumps({
            "pc_01": {
                "profile": {"name": "テスト刑事", "is_npc": False},
                "baseline": {"SAN": 55, "LUCK": 45, "HP": 12, "MP": 11},
                "attributes": {
                    "STR": 55, "CON": 60, "POW": 55, "SIZ": 60,
                    "SAN": {"current": 20, "max": 99, "session_start": 20, "session_start_san": 20},
                    "HP": {"current": 3, "max": 12},
                    "MP": {"current": 2, "max": 11},
                    "LUCK": 10,
                },
                "skills": {"目星": 65},
                "states": [{"status": "insane", "label": "一時的発狂"}],
                "session_skill_marks": ["目星"],
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_begin_session_restores_baseline(self):
        self.assertEqual(self.char_mgr.get_stat_current("pc_01", "SAN"), 20)
        self.assertEqual(self.char_mgr.get_luck("pc_01"), 10)

        self.char_mgr.begin_session_stats("pc_01")

        self.assertEqual(self.char_mgr.get_stat_current("pc_01", "SAN"), 55)
        self.assertEqual(self.char_mgr.get_session_start_san("pc_01"), 55)
        self.assertEqual(self.char_mgr.get_luck("pc_01"), 45)
        self.assertEqual(self.char_mgr.get_stat_current("pc_01", "HP"), 12)
        self.assertEqual(self.char_mgr.get_stat_current("pc_01", "MP"), 11)
        self.assertEqual(self.char_mgr.characters["pc_01"].get("states"), [])
        self.assertEqual(self.char_mgr.get_skill_marks("pc_01"), [])

    def test_reset_all_pcs_to_baseline(self):
        self.char_mgr.reset_all_pcs_to_baseline(persist=True)
        self.assertEqual(self.char_mgr.get_stat_current("pc_01", "SAN"), 55)
        saved = json.loads(self.pc_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["pc_01"]["attributes"]["SAN"]["current"], 55)
        self.assertEqual(saved["pc_01"]["attributes"]["LUCK"], 45)
        self.assertEqual(saved["pc_01"]["baseline"]["SAN"], 55)


if __name__ == "__main__":
    unittest.main()
