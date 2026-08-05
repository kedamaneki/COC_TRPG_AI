# -*- coding: utf-8 -*-
"""職業ロールプレイ判定（ボーナス／ペナルティ／判定省略）の単体テスト。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from CharacterManager import CharacterManager
from DiceEngine import DiceEngine, SuccessLevel
from NPCSocialManager import (
    NPCSocialManager,
    RELATIONSHIP_DICE_MOD,
    clamp_occupation_rp_mods,
    default_occupation_rp_judgment,
    normalize_occupation_rp_judgment,
    format_occupation_rp_log,
)
import main as game_main


class TestOccupationRpHelpers(unittest.TestCase):
    def test_clamp_sums_and_nets(self):
        rel = {"bonus": 0, "penalty": 1, "difficulty": "regular"}
        rp = {"fit": "good", "bonus_dice": 2, "penalty_dice": 0, "skip_roll": False}
        merged = clamp_occupation_rp_mods(rel, rp)
        # penalty1 + bonus2 → net bonus1
        self.assertEqual(merged["bonus"], 1)
        self.assertEqual(merged["penalty"], 0)
        self.assertEqual(merged["rp_bonus"], 2)
        self.assertEqual(merged["relationship_penalty"], 1)

    def test_clamp_max_two(self):
        rel = RELATIONSHIP_DICE_MOD["cooperative"]  # bonus 1
        rp = {"fit": "excellent", "bonus_dice": 2, "penalty_dice": 0}
        merged = clamp_occupation_rp_mods(rel, rp)
        self.assertLessEqual(merged["bonus"], 2)

    def test_skip_only_on_excellent(self):
        bad = normalize_occupation_rp_judgment({
            "fit": "good", "bonus_dice": 1, "skip_roll": True,
        })
        self.assertFalse(bad["skip_roll"])
        good = normalize_occupation_rp_judgment({
            "fit": "excellent", "bonus_dice": 2, "skip_roll": True,
            "auto_success_level": 3,
        })
        self.assertTrue(good["skip_roll"])
        self.assertEqual(good["auto_success_level"], 3)

    def test_default_fallback(self):
        d = default_occupation_rp_judgment()
        self.assertEqual(d["fit"], "neutral")
        self.assertFalse(d["skip_roll"])

    def test_format_log(self):
        text = format_occupation_rp_log({
            "fit": "excellent",
            "bonus_dice": 2,
            "penalty_dice": 0,
            "skip_roll": True,
            "auto_success_level": 2,
            "reason": "刑事としての身分開示",
        }, skipped=True)
        self.assertIn("判定省略", text)
        self.assertIn("刑事", text)


class TestOccupationRpNegotiation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pc_path = root / "pcs.json"
        self.npc_path = root / "npcs.json"
        self.pc_path.write_text(json.dumps({
            "pc_01": {
                "profile": {
                    "name": "マクガフィン刑事",
                    "occupation": "刑事",
                    "is_npc": False,
                    "action_guide": "捜査として身分を示す",
                },
                "attributes": {
                    "POW": 55,
                    "SAN": {"current": 55, "max": 99, "session_start": 55},
                    "HP": {"current": 12, "max": 12},
                    "MP": {"current": 11, "max": 11},
                    "LUCK": 45,
                },
                "skills": {"説得": 50, "威圧": 60},
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.npc_path.write_text(json.dumps({
            "artie_wilmott": {
                "profile": {"name": "アーティ・ウィルモット", "is_npc": True},
                "attributes": {"POW": 50},
                "skills": {"心理学": 40},
                "relationship_status": "uncooperative",
                "personality": "非協力的な編集者",
                "secrets": {
                    "secret_ref_room_gate": {
                        "content": "資料室は自分の裁量で許可する。",
                        "reveal_condition": "success_level >= 2",
                    },
                },
                "session_social": {
                    "relationship_status": "uncooperative",
                    "revealed_secrets": [],
                    "dialogue_count": 0,
                },
            },
        }, ensure_ascii=False), encoding="utf-8")
        self.char_mgr = CharacterManager(str(self.pc_path), str(self.npc_path))
        self.social = NPCSocialManager(self.char_mgr)
        self.dice = DiceEngine()

    def tearDown(self):
        self.tmp.cleanup()

    def test_skip_roll_does_not_call_dice(self):
        rp = {
            "fit": "excellent",
            "bonus_dice": 2,
            "penalty_dice": 0,
            "skip_roll": True,
            "auto_success_level": 2,
            "reason": "刑事として正式に捜査協力を求めた",
        }
        with mock.patch.object(self.dice, "execute_skill_roll") as mocked:
            result = self.social.resolve_negotiation(
                "pc_01", "artie_wilmott",
                skill_name="説得",
                dice_engine=self.dice,
                action_id="persuade",
                dialogue_text="市警の捜査で来ました。資料室を見せてください。",
                occupation_rp=rp,
            )
            mocked.assert_not_called()
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("skipped_roll"))
        self.assertTrue(result.get("is_success"))
        self.assertIn("判定省略", result.get("log", ""))
        self.assertEqual(result.get("success_level"), int(SuccessLevel.REGULAR_SUCCESS))

    def test_judge_failure_falls_back_neutral(self):
        with mock.patch.object(
            game_main, "_call_chat_completion", side_effect=RuntimeError("llm down"),
        ):
            judged = game_main.call_occupation_rp_judge("dummy")
        self.assertEqual(judged["fit"], "neutral")
        self.assertFalse(judged["skip_roll"])

    def test_penalty_rp_passed_to_dice(self):
        rp = {
            "fit": "terrible",
            "bonus_dice": 0,
            "penalty_dice": 2,
            "skip_roll": False,
            "reason": "編集者に対し場違いな威圧",
        }
        captured = {}

        def fake_roll(*args, **kwargs):
            captured.update(kwargs)
            return {
                "status": "ok",
                "success_level": int(SuccessLevel.FAILURE),
                "is_failure": True,
                "log": "【技能:説得】失敗",
            }

        with mock.patch.object(self.dice, "execute_skill_roll", side_effect=fake_roll):
            result = self.social.resolve_negotiation(
                "pc_01", "artie_wilmott",
                skill_name="説得",
                dice_engine=self.dice,
                action_id="persuade",
                occupation_rp=rp,
            )
        self.assertTrue(result.get("ok"))
        # uncooperative penalty1 + rp penalty2 → net penalty 2 (clamped)
        self.assertEqual(captured.get("penalty_dice"), 2)
        self.assertEqual(captured.get("bonus_dice"), 0)
        self.assertIn("職業RP判定", result.get("log", ""))


if __name__ == "__main__":
    unittest.main()
