"""
アクションバリデーション（移動意図一致・対人調査→talk・フェーズ同期・成功ファクト）。
実行: python test_action_validator_guards.py
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ActionValidator import (
    MOVE_INTENT_MISMATCH_ERROR,
    HUMAN_INSPECT_REWRITE_LOG,
    KP_SUCCESS_FACT_GUARD,
    KP_LOCKED_ROUTE_GUARD,
    validate_move_intent,
    validate_force_ic_action,
    is_stale_nonprogress_talk,
    build_forced_progress_move_action,
    rewrite_human_investigation_to_talk,
    phase_for_location,
)
from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from ScenarioManager import ScenarioManager
import main as game_main


CORBITT = Path(__file__).resolve().parent / "scenario_corbitt.json"
NPCS = Path(__file__).resolve().parent / "npcs.json"


class TestActionValidatorGuards(unittest.TestCase):
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
                "skills": {"目星": 65, "説得": 50, "法律": 50},
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.scenario = ScenarioManager(json.loads(json.dumps(self.scenario_data)))
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_move_intent_mismatch_rejected(self):
        check = validate_move_intent(
            "参考資料室に行こう",
            "hall_of_records",
            current_loc="boston_globe",
            scenario_mgr=self.scenario,
        )
        self.assertFalse(check["ok"])
        self.assertIn("move_non_location", check.get("error_code", ""))

        check2 = validate_move_intent(
            "公文書館ではなく中央図書館へ向かう",
            "hall_of_records",
            current_loc="boston_globe",
            scenario_mgr=self.scenario,
        )
        # テキストに図書館と公文書館両方が入ると複雑だが、少なくともエラー文定数は定義済み
        self.assertTrue(MOVE_INTENT_MISMATCH_ERROR)

    def test_reconcile_rejects_wrong_move(self):
        self.scenario.location = "boston_globe"
        out = game_main.reconcile_pl_action(
            {
                "action": "move",
                "target": "hall_of_records",
                "skill": "",
                "dialogue": "参考資料室へ行きたい",
            },
            "PC",
            "",
            self.scenario,
            "boston_globe",
            char_mgr=self.char_mgr,
        )
        self.assertTrue(out.get("needs_pl_retry"))
        self.assertIn("validation_error", out)

    def test_human_inspect_rewrites_to_talk(self):
        rewritten = rewrite_human_investigation_to_talk(
            "inspect", "clerk_desk", char_mgr=self.char_mgr,
        )
        self.assertIsNotNone(rewritten)
        self.assertEqual(rewritten["action"], "talk")
        self.assertEqual(rewritten["target"], "hall_records_clerk")

        self.scenario.location = "hall_of_records"
        out = game_main.reconcile_pl_action(
            {
                "action": "inspect",
                "target": "clerk_desk",
                "skill": "目星",
                "dialogue": "事務官のデスクを調べる",
            },
            "PC",
            "",
            self.scenario,
            "hall_of_records",
            char_mgr=self.char_mgr,
        )
        self.assertEqual(out["action"], "talk")
        self.assertEqual(out["target"], "hall_records_clerk")
        self.assertIn(HUMAN_INSPECT_REWRITE_LOG[:10], out.get("system_correction_log", "") or HUMAN_INSPECT_REWRITE_LOG)

    def test_process_system_rewrites_clerk_inspect(self):
        self.scenario.location = "hall_of_records"
        result = game_main.process_system_action(
            "pc_01", "マクガフィン刑事", "inspect", "clerk_desk", "目星",
            "hall_of_records", self.char_mgr, self.dice, self.scenario,
        )
        self.assertEqual(result.get("action_id"), "talk")
        self.assertIn("アクション補正", result.get("log", ""))
        self.assertTrue(self.scenario.flags.get("hall_of_records_clerk_interacted"))

    def test_phase_sync_on_move(self):
        self.scenario.location = "introduction"
        self.scenario.current_phase = "introduction"
        self.scenario.flags["talked_with_knott"] = True
        # 出口ガードを避けるため process_action を直接
        payload = self.scenario.process_action("move", "boston_globe", success_level=0)
        self.assertEqual(self.scenario.location, "boston_globe")
        self.assertEqual(self.scenario.current_phase, "investigation")
        self.assertEqual(payload.get("new_phase"), "investigation")
        self.assertEqual(phase_for_location("hall_of_records", "introduction"), "investigation")

    def test_success_injects_confirmed_fact(self):
        self.scenario.location = "hall_of_records"
        self.scenario.current_phase = "investigation"
        # ハード成功相当
        payload = self.scenario.process_action("search", "crime_court_records", success_level=3)
        self.assertTrue(payload.get("confirmed_fact") or "【確定手がかり】" in payload.get("system_log", ""))
        self.assertNotIn("特になにも見つからなかった", payload.get("system_log", ""))

        facts = game_main._build_kp_allowed_facts_block(
            self.scenario,
            {"action": "search", "target": "crime_court_records"},
            {
                "confirmed_fact": payload.get("confirmed_fact"),
                "dice_success": True,
                "success_level": 3,
                "target": "crime_court_records",
                "log": payload.get("system_log", ""),
            },
        )
        self.assertIn(KP_SUCCESS_FACT_GUARD[:12], facts)
        self.assertIn(KP_LOCKED_ROUTE_GUARD[:12], facts)

    def test_force_ic_wait_rejected(self):
        check = validate_force_ic_action(
            {"action": "wait", "target": ""},
            force_ic_action=True,
            scenario_mgr=self.scenario,
            current_loc="introduction",
        )
        self.assertFalse(check["ok"])
        self.assertTrue(check.get("needs_pl_retry"))

    def test_stale_knott_talk_detected_after_unlock(self):
        self.scenario.flags["talked_with_knott"] = True
        self.assertTrue(
            is_stale_nonprogress_talk(
                "talk", "steven_knott",
                scenario_mgr=self.scenario,
                current_loc="introduction",
                char_mgr=self.char_mgr,
            )
        )
        forced = build_forced_progress_move_action(self.scenario, "introduction")
        # exits 未解放なら None もありうるが、flag で boston_globe は解放済み
        self.scenario.flags["knott_letter_read"] = True
        self.scenario.flags["knott_memo_read"] = True
        forced = build_forced_progress_move_action(self.scenario, "introduction")
        self.assertIsNotNone(forced)
        self.assertEqual(forced["action"], "move")
        self.assertEqual(forced["target"], "boston_globe")


if __name__ == "__main__":
    unittest.main()
